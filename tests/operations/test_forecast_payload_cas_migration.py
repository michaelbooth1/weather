import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.collection.snapshot_store import SnapshotStore
from weather.operations.event_day_manifest import _payload_blob_link_validation
from weather.operations.forecast_payload_cas_migration import (
    build_migration_dry_run,
    render_markdown,
)
from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax


NBP_TEXT = """
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


def test_migration_is_inventory_only_and_proves_restore_hash_and_replay(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": {
                    "raw_payload": {
                        "schema_version": "nbm_probabilistic_tmax_v0.1",
                        "source": "nbm_probabilistic_tmax",
                        "source_kind": "nbp_station_text",
                        "station_id": "KLGA",
                        "target_date": "2026-05-30",
                        "source_url": "https://example.test/legacy",
                        "fetched_at": "2026-05-30T01:00:00+00:00",
                        "text": NBP_TEXT,
                    }
                }
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
    )[0]
    legacy_path = Path(row["raw_payload_path"])
    before = legacy_path.read_bytes()

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["mode"] == "inventory_dry_run"
    assert report["mutation_performed"] is False
    assert report["deletion_enabled"] is False
    assert report["summary"]["candidate_row_count"] == 1
    assert report["summary"]["verified_candidate_row_count"] == 1
    assert report["summary"]["unique_shared_payload_count"] == 1
    assert report["candidates"][0]["restore_hash_status"] == "PASS"
    assert report["candidates"][0]["replay_status"] == "PASS"
    assert report["candidates"][0]["would_copy"] is True
    assert report["candidates"][0]["would_rewrite_manifest"] is False
    assert report["candidates"][0]["would_delete_legacy_blob"] is False
    assert legacy_path.read_bytes() == before
    assert not shared.exists()


def test_migration_reports_corrupt_legacy_blob_without_mutation(tmp_path):
    event = tmp_path / "snapshots" / "event"
    event.mkdir(parents=True)
    blob = event / "forecast_payloads" / "sha256" / ("a" * 2) / f"{'a' * 64}.json"
    blob.parent.mkdir(parents=True)
    blob.write_text(json.dumps({"text": NBP_TEXT}) + "\n", encoding="utf-8")
    manifest = event / "forecast_payloads.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "forecast_payload_manifest_v1",
                "snapshot_id": "s1",
                "event_slug": "event",
                "source": "nbm_probabilistic_tmax",
                "payload_hash": "a" * 64,
                "payload_bytes": 1,
                "raw_payload_path": str(blob),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = blob.read_bytes()

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=tmp_path / "shared",
    )

    assert report["summary"]["blocked_candidate_row_count"] == 1
    assert "legacy_hash_or_restore_failed" in report["candidates"][0]["issues"][0]
    assert blob.read_bytes() == before
    assert not (tmp_path / "shared").exists()


def test_event_day_payload_validation_accepts_and_verifies_shared_reference(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": parse_nbp_station_tmax(
                    NBP_TEXT,
                    "KLGA",
                    "2026-05-30",
                    source_url=(
                        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
                        "blend.20260530/00/text/blend_nbptx.t00z"
                    ),
                )
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
    )[0]

    validation = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family for family in validation["families"]
        if family["artifact_family"] == "forecast_payloads"
    )
    assert forecast["status"] == "PASS"
    assert forecast["shared_linked_blob_count"] == 1
    assert forecast["blob_count"] == 0

    Path(row["raw_payload_path"]).write_bytes(b"corrupt")
    corrupt = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family for family in corrupt["families"]
        if family["artifact_family"] == "forecast_payloads"
    )
    assert forecast["status"] == "BLOCK"
    assert any(
        issue["code"] == "raw_payload_blob_hash_mismatch"
        for issue in forecast["issues"]
    )


def test_event_day_validation_rejects_matching_blob_outside_expected_cas_root(tmp_path):
    event, shared, row = _write_shared_row(tmp_path)
    expected = Path(row["raw_payload_path"])
    rogue = (
        tmp_path
        / "rogue-cas"
        / "sha256"
        / row["payload_hash"][:2]
        / f"{row['payload_hash']}.blob"
    )
    rogue.parent.mkdir(parents=True)
    shutil.copy2(expected, rogue)
    row["raw_payload_path"] = str(rogue)
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    validation = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family
        for family in validation["families"]
        if family["artifact_family"] == "forecast_payloads"
    )

    assert forecast["status"] == "BLOCK"
    assert any(
        issue["code"] == "shared_payload_reference_invalid"
        for issue in forecast["issues"]
    )


def _write_shared_row(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": parse_nbp_station_tmax(
                    NBP_TEXT,
                    "KLGA",
                    "2026-05-30",
                    source_url=(
                        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
                        "blend.20260530/00/text/blend_nbptx.t00z"
                    ),
                    fetched_at="2026-05-30T01:00:00+00:00",
                )
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]
    return event, shared, row


def test_migration_shared_reachability_is_verified_and_partial_only(tmp_path):
    _event, shared, row = _write_shared_row(tmp_path)

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["inventory_scope"] == "snapshot_forecast_payload_jsonl_only"
    assert report["authoritative_for_garbage_collection"] is False
    assert report["reachability"]["status"] == "PARTIAL_INVENTORY_ONLY"
    assert report["reachability"]["authoritative_for_garbage_collection"] is False
    assert report["reachability"]["delete_candidates"] == []
    assert report["summary"]["candidate_row_count"] == 0
    assert report["summary"]["verified_shared_reference_row_count"] == 1
    assert report["summary"]["blocked_shared_reference_row_count"] == 0
    assert report["reachability"]["verified_active_shared_digests"] == [
        row["payload_hash"]
    ]
    assert "unreachable_candidate_digests" not in report["reachability"]
    markdown = render_markdown(report)
    assert "partial inventory only" in markdown
    assert "Authoritative for garbage collection: False" in markdown


@pytest.mark.parametrize(
    "tamper",
    [
        "ref",
        "size",
        "identity",
        "schema",
        "media",
        "retained",
        "blob",
        "request",
        "cycle",
        "market_station",
    ],
)
def test_migration_never_counts_unverified_shared_reference(tmp_path, tamper):
    event, shared, row = _write_shared_row(tmp_path)
    if tamper == "ref":
        row["payload_ref"] = f"sha256/ff/{'f' * 64}.blob"
    elif tamper == "size":
        row["payload_bytes"] += 1
    elif tamper == "identity":
        row["extraction_identity"] = "{}"
    elif tamper == "schema":
        row["extraction_schema"] = "unknown_extraction_v1"
    elif tamper == "media":
        row["payload_media_type"] = "application/octet-stream"
    elif tamper == "retained":
        row["raw_payload_retained"] = False
    elif tamper == "blob":
        Path(row["raw_payload_path"]).write_bytes(b"corrupt")
    elif tamper == "request":
        row["request_key"] = "nbm_probabilistic_tmax:GET:sha256:" + "f" * 64
    elif tamper == "cycle":
        row["cycle_key"] = "nbm-nbp:19990101T00Z"
    elif tamper == "market_station":
        row["market_id"] = "austin"
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["summary"]["verified_shared_reference_row_count"] == 0
    assert report["summary"]["blocked_shared_reference_row_count"] == 1
    assert report["reachability"]["verified_active_shared_digests"] == []
    assert report["reachability"]["delete_candidates"] == []
