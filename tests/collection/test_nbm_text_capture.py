import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
from weather.collection.nbm_text_capture import market_text_stations, run_capture
from weather.operations.storage_classes import CANONICAL_EVIDENCE, classify_storage_path
from weather.schema_registry import schema_version
from weather.sources.nbm_text_bulletins import NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nbm_text"
NOW = datetime(2026, 10, 1, 12, 50, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, data=None, status=200, declared=None):
        self.data, self.status_code = data, status
        self.headers = {} if data is None else {"Content-Length": str(declared or len(data))}
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]

    def close(self):
        self.closed = True


class FakeNoaa:
    """Serves the 12Z fixtures from the primary host only; everything else is 404."""

    def __init__(self, declared=None, mirror_only=False):
        self.calls, self.declared, self.mirror_only = [], declared, mirror_only

    def __call__(self, url):
        self.calls.append(url)
        published = "s3.amazonaws.com" in url if self.mirror_only else "nomads" in url
        if published and ".t12z" in url:
            name = "blend_nbhtx.t12z.excerpt.txt" if "nbhtx" in url else "blend_nbstx.t12z.excerpt.txt"
            return FakeResponse((FIXTURES / name).read_bytes(), declared=self.declared)
        return FakeResponse(status=404)


def rows(root):
    return [json.loads(line) for line in (root / "20261001.jsonl").read_text().splitlines()]


def capture(tmp_path, noaa, **kwargs):
    return run_capture(now_utc=NOW, hours_back=1, cas_root=tmp_path / "cas",
                       manifest_root=tmp_path / "manifests", stream_fn=noaa, **kwargs)


def test_market_stations_include_toronto():
    stations = market_text_stations()
    assert "CYYZ" in stations and "KLGA" in stations and len(stations) == 12


def test_capture_stores_gzip_extract_in_shared_cas_once(tmp_path):
    noaa = FakeNoaa()
    summary = capture(tmp_path, noaa)
    assert summary["status"] == "ok"
    statuses = {row["cycle_key"]: row["status"] for row in summary["cycles"]}
    assert statuses == {"nbm-nbh:20261001T12Z": "success", "nbm-nbh:20261001T11Z": "not_published",
                        "nbm-nbs:20261001T12Z": "success", "nbm-nbs:20261001T11Z": "not_published"}
    manifest = rows(tmp_path / "manifests")
    assert [row["cycle_key"] for row in manifest] == ["nbm-nbh:20261001T12Z", "nbm-nbs:20261001T12Z"]
    cas = SharedForecastPayloadCAS(tmp_path / "cas")
    for row in manifest:
        assert row["schema_version"] == NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION
        assert row["feature_use"] == "none_capture_only"
        assert row["stations_found"] == sorted(market_text_stations()) and not row["stations_missing"]
        assert row["payload_encoding"] == "gzip" and row["payload_ref"].startswith("sha256/")
        text = gzip.decompress(cas.read(row["payload_hash"], expected_bytes=row["payload_bytes"]))
        assert len(text) == row["extract_bytes"] and row["national_bytes"] > row["extract_bytes"]
        assert row["payload_bytes"] < 10_000  # 12 stations, well under 1 MB/day at 48 cycles
        assert classify_storage_path("data/forecast_payload_cas/" + row["payload_ref"]).artifact_family == (
            "shared_forecast_payload_cas")
    first_calls = len(noaa.calls)
    again = capture(tmp_path, noaa)
    done = [row for row in again["cycles"] if row["status"] == "already_captured"]
    assert len(done) == 2 and len(noaa.calls) == first_calls + 4  # only 11Z retried (2 products x 2 hosts)
    assert len(rows(tmp_path / "manifests")) == 2


def test_identical_extract_reuses_the_blob(tmp_path):
    capture(tmp_path, FakeNoaa())
    (tmp_path / "manifests" / "20261001.jsonl").unlink()
    capture(tmp_path, FakeNoaa())
    assert {row["payload_blob_created"] for row in rows(tmp_path / "manifests")} == {False}


def test_mirror_is_used_when_primary_has_not_published(tmp_path):
    capture(tmp_path, FakeNoaa(mirror_only=True), products=["nbh"])
    (row,) = rows(tmp_path / "manifests")
    assert row["status"] == "success" and "s3.amazonaws.com" in row["source_url"]
    assert len(row["tried_urls"]) == 2


def test_truncated_transfer_is_recorded_and_retried(tmp_path):
    capture(tmp_path, FakeNoaa(declared=10**9), products=["nbh"])
    (row,) = rows(tmp_path / "manifests")
    assert row["status"] == "truncated" and "payload_hash" not in row
    assert not (tmp_path / "cas" / "sha256").exists()
    capture(tmp_path, FakeNoaa(), products=["nbh"])
    assert [row["status"] for row in rows(tmp_path / "manifests")] == ["truncated", "success"]


def test_transfer_error_does_not_raise(tmp_path):
    def broken(url):
        raise requests.ConnectionError("offline")

    summary = capture(tmp_path, broken, products=["nbs"])
    assert summary["status"] == "ok"
    assert {row["status"] for row in rows(tmp_path / "manifests")} == {"transfer_error"}


def test_dry_run_and_lock(tmp_path):
    noaa = FakeNoaa()
    summary = capture(tmp_path, noaa, dry_run=True)
    assert {row["status"] for row in summary["cycles"]} == {"would_fetch"} and noaa.calls == []
    lock = tmp_path / "manifests" / ".capture.writer.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}")
    assert capture(tmp_path, noaa)["status"] == "locked" and noaa.calls == []


def test_manifest_is_registered_canonical_evidence():
    assert schema_version("nbm_text_station_blocks") == NBM_TEXT_STATION_BLOCKS_SCHEMA_VERSION
    family = classify_storage_path("data/forecast_payload_cas/nbm_text_manifests/20261001.jsonl")
    assert family.artifact_family == "nbm_text_station_block_manifest"
    assert family.storage_class == CANONICAL_EVIDENCE and family.protected


@pytest.mark.parametrize("module", ["weather.model.model_sources", "weather.model.model_features"])
def test_capture_is_not_read_by_serving(module):
    import importlib

    source = Path(importlib.import_module(module).__file__).read_text(encoding="utf-8")
    assert "nbm_text" not in source
