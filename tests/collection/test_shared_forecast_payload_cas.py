import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.collection.forecast_payload_cas import (
    ForecastPayloadCASIntegrityError,
    SharedForecastPayloadCAS,
    forecast_payload_byte_summary,
    resolve_forecast_payload_bytes,
)
from weather.collection.snapshot_store import SnapshotStore
from weather.sources.nbm_probabilistic_tmax import (
    parse_nbp_station_tmax,
    replay_nbp_shared_payload,
)


NBP_TEXT = """
 KBOS    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNMN  70  58| 73  62
TXNSD   2   2|  3   3
TXNP1  67  55| 69  58
TXNP2  68  56| 71  59
TXNP5  70  58| 73  62
TXNP7  71  59| 75  64
TXNP9  73  61| 77  66

 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNMN  84  68| 79  68
TXNSD   2   2|  4   3
TXNP1  81  64| 73  63
TXNP2  82  66| 76  66
TXNP5  84  68| 80  69
TXNP7  85  69| 82  71
TXNP9  86  70| 84  72
"""
SOURCE_URL = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
    "blend.20260530/00/text/blend_nbptx.t00z"
)


def _source(station_id):
    return {
        "nbm_probabilistic_tmax": {
            "ok": True,
            "fetched_at": "2026-05-30T01:00:00+00:00",
            "data": parse_nbp_station_tmax(
                NBP_TEXT,
                station_id,
                "2026-05-30",
                source_url=SOURCE_URL,
                fetched_at="2026-05-30T01:00:00+00:00",
            ),
        }
    }


def test_atomic_concurrent_put_converges_and_ignores_partial_staging(tmp_path):
    cas = SharedForecastPayloadCAS(tmp_path / "cas")
    payload = ("national bulletin\n" * 4096).encode()
    digest = __import__("hashlib").sha256(payload).hexdigest()
    final = cas.path_for(digest)
    final.parent.mkdir(parents=True)
    stale_staging = final.with_name(f".{final.name}.staging-dead-worker")
    stale_staging.write_bytes(payload[:37])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cas.put(payload), range(16)))

    assert sum(1 for row in results if row["created"]) == 1
    assert sum(1 for row in results if row["reused"]) == 15
    assert cas.read(digest) == payload
    assert stale_staging.read_bytes() == payload[:37]
    assert list((tmp_path / "cas" / "sha256").rglob("*.blob")) == [final]


def test_corrupt_or_missing_shared_blob_fails_closed(tmp_path):
    cas = SharedForecastPayloadCAS(tmp_path / "cas")
    payload = b"verified response"
    result = cas.put(payload)
    Path(result["path"]).write_bytes(b"corrupt")

    with pytest.raises(ForecastPayloadCASIntegrityError, match="hash mismatch"):
        cas.put(payload)
    with pytest.raises(ForecastPayloadCASIntegrityError, match="hash mismatch"):
        cas.read(result["payload_hash"])
    Path(result["path"]).unlink()
    with pytest.raises(ForecastPayloadCASIntegrityError, match="missing"):
        cas.read(result["payload_hash"])


def test_multi_market_nbm_manifests_share_one_blob_and_replay_per_market(tmp_path):
    cas_root = tmp_path / "shared-cas"
    ny_store = SnapshotStore(
        root=tmp_path / "ny-event",
        event_slug="ny-event",
        shared_forecast_payload_cas_root=cas_root,
    )
    bos_store = SnapshotStore(
        root=tmp_path / "bos-event",
        event_slug="bos-event",
        shared_forecast_payload_cas_root=cas_root,
    )
    ny_store.root.mkdir(parents=True)
    bos_store.root.mkdir(parents=True)
    ny_time = datetime(2026, 5, 30, 1, 1, tzinfo=timezone.utc)
    bos_time = datetime(2026, 5, 30, 1, 3, tzinfo=timezone.utc)

    ny_row = ny_store.write_forecast_payloads(
        _source("KLGA"),
        "ny-snapshot",
        ny_time,
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]
    bos_row = bos_store.write_forecast_payloads(
        _source("KBOS"),
        "bos-snapshot",
        bos_time,
        "model-v",
        config_identity={"market_id": "boston", "target_date": "2026-05-30"},
    )[0]

    assert ny_row["schema_version"] == "forecast_payload_manifest_v2"
    assert ny_row["payload_hash"] == bos_row["payload_hash"]
    assert ny_row["raw_payload_path"] == bos_row["raw_payload_path"]
    assert ny_row["payload_blob_created"] is True
    assert bos_row["payload_blob_reused"] is True
    assert ny_row["captured_at_utc"] != bos_row["captured_at_utc"]
    assert ny_row["market_id"] == "nyc"
    assert bos_row["market_id"] == "boston"
    assert not ny_store.forecast_payload_dir.exists()
    assert not bos_store.forecast_payload_dir.exists()
    assert len(list(cas_root.rglob("*.blob"))) == 1

    ny_bytes = resolve_forecast_payload_bytes(ny_row, shared_cas_root=cas_root)
    bos_bytes = resolve_forecast_payload_bytes(bos_row, shared_cas_root=cas_root)
    assert ny_bytes == bos_bytes == NBP_TEXT.encode("utf-8")
    restored_cas = tmp_path / "restored-cas"
    shutil.copytree(cas_root, restored_cas)
    assert (
        resolve_forecast_payload_bytes(ny_row, shared_cas_root=restored_cas)
        == ny_bytes
    )
    ny_replay = replay_nbp_shared_payload(
        ny_bytes,
        json.loads(ny_row["extraction_identity"]),
        source_url=ny_row["source_url"],
        fetched_at=ny_row["fetched_at"],
    )
    bos_replay = replay_nbp_shared_payload(
        bos_bytes,
        json.loads(bos_row["extraction_identity"]),
        source_url=bos_row["source_url"],
        fetched_at=bos_row["fetched_at"],
    )
    assert ny_replay["percentiles"]["50"] == 84.0
    assert bos_replay["percentiles"]["50"] == 70.0

    summary = forecast_payload_byte_summary([ny_row, bos_row], physical_write_budget_bytes=len(ny_bytes))
    assert summary["created_blob_count"] == 1
    assert summary["reused_blob_count"] == 1
    assert summary["logical_referenced_bytes"] == 2 * len(ny_bytes)
    assert summary["physical_bytes_written"] == len(ny_bytes)
    assert summary["avoided_bytes"] == len(ny_bytes)
    assert summary["physical_write_budget_status"] == "PASS"


def test_non_attested_forecast_payload_remains_market_local(tmp_path):
    store = SnapshotStore(
        root=tmp_path / "event",
        event_slug="event",
        shared_forecast_payload_cas_root=tmp_path / "shared",
    )
    row = store.write_forecast_payloads(
        {"nws_grid": {"data": {"raw_payload": {"values": [1, 2, 3]}}}},
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
    )[0]

    assert row["payload_storage_scope"] == "market_local"
    assert "/forecast_payloads/sha256/" in Path(row["raw_payload_path"]).as_posix()
    assert not (tmp_path / "shared").exists()


def test_incomplete_market_invariant_attestation_fails_closed(tmp_path):
    store = SnapshotStore(
        root=tmp_path / "event",
        event_slug="event",
        shared_forecast_payload_cas_root=tmp_path / "shared",
    )
    store.root.mkdir(parents=True)
    payload = {
        "text": "bulletin",
        "forecast_payload_attestation": {
            "market_invariant": True,
            "source": "nbm_probabilistic_tmax",
            "body_field": "text",
            "encoding": "utf-8",
            "media_type": "text/plain; charset=utf-8",
        },
    }

    with pytest.raises(
        ForecastPayloadCASIntegrityError,
        match="requires request_key",
    ):
        store.write_forecast_payloads(
            {"nbm_probabilistic_tmax": {"data": {"raw_payload": payload}}},
            "s1",
            datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
            "model-v",
        )

    assert not (tmp_path / "shared").exists()


def test_nbm_shared_attestation_requires_replay_complete_extraction_identity(tmp_path):
    store = SnapshotStore(
        root=tmp_path / "event",
        event_slug="event",
        shared_forecast_payload_cas_root=tmp_path / "shared",
    )
    store.root.mkdir(parents=True)
    payload = {
        "station_id": "KLGA",
        "target_date": "2026-05-30",
        "text": NBP_TEXT,
        "forecast_payload_attestation": {
            "market_invariant": True,
            "source": "nbm_probabilistic_tmax",
            "request_key": "request-key",
            "cycle_key": "cycle-key",
            "body_field": "text",
            "encoding": "utf-8",
            "media_type": "text/plain; charset=utf-8",
            "extraction_schema": "nbm_nbp_station_target_v1",
            "extraction_identity": {},
        },
    }

    with pytest.raises(
        ForecastPayloadCASIntegrityError,
        match="requires a valid station_id",
    ):
        store.write_forecast_payloads(
            {"nbm_probabilistic_tmax": {"data": {"raw_payload": payload}}},
            "s1",
            datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
            "model-v",
        )

    assert not (tmp_path / "shared").exists()
