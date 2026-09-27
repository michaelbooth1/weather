import csv
import json
from datetime import datetime
from pathlib import Path
import time

from weather.collection import forecast_archive as archive
from weather.collection import snapshot_read_index as index
from weather.collection.snapshot_store import SnapshotStore


def test_last_time_tail_and_triggered_only_fallback(tmp_path):
    store = SnapshotStore(root=tmp_path, event_slug="fixture")
    fields = ["captured_at_local", "snapshot_cadence", "padding"]
    scheduled = "2026-08-01T10:00:00+00:00"
    with store.long_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(zip(fields, [scheduled, "", "first"])))
        for _ in range(1000):
            writer.writerow(dict(zip(fields, ["2026-08-01T10:01:00+00:00", "triggered", "x" * 150])))
    assert store.last_snapshot_time("scheduled") == datetime.fromisoformat(scheduled)
    assert store.last_snapshot_time() == datetime.fromisoformat("2026-08-01T10:01:00+00:00")
    with store.long_path.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writerow(dict(zip(fields, [scheduled, "scheduled", "multi\nline"])))
    assert store.last_snapshot_time("scheduled") == datetime.fromisoformat(scheduled)


def test_forecast_index_warm_append_corruption_and_replacement(tmp_path, monkeypatch):
    path = tmp_path / "forecasts_long.csv"
    row = {"source": "eccc_citypage", "forecast_kind": "daily_high", "payload_hash": "one"}
    archive.append_rows(path, archive.FORECAST_COLUMNS, [row])
    assert archive.last_payload_hash(path, "eccc_citypage", "daily_high") == "one"
    archive.append_rows(path, archive.FORECAST_COLUMNS, [dict(row, payload_hash="two")])
    original = csv.DictReader
    monkeypatch.setattr(csv, "DictReader", lambda *a, **k: (_ for _ in ()).throw(AssertionError("warm source parse")))
    assert archive.last_payload_hash(path, "eccc_citypage", "daily_high") == "two"
    monkeypatch.setattr(csv, "DictReader", original)
    index._sidecar(path, "forecast").write_text('{"broken": true}', encoding="utf-8")
    assert archive.last_payload_hash(path, "eccc_citypage", "daily_high") == "two"
    archive.write_rows(path, archive.FORECAST_COLUMNS, [dict(row, payload_hash="replacement")])
    assert archive.last_payload_hash(path, "eccc_citypage", "daily_high") == "replacement"


def test_first_seen_survives_new_store_and_stale_index(tmp_path, monkeypatch):
    first = SnapshotStore(root=tmp_path, event_slug="fixture")
    assert first.payload_first_seen("forecast", "hash", None, "first") == ("first", "snapshot_capture")
    path = first.forecast_payloads_jsonl_path
    first.append_jsonl(path, {"payload_hash": "hash", "first_seen_at": "first",
                            "first_seen_basis": "snapshot_capture"}, durable=True)
    second = SnapshotStore(root=tmp_path, event_slug="fixture")
    monkeypatch.setattr(second, "read_jsonl", lambda *a: (_ for _ in ()).throw(AssertionError("warm manifest parse")))
    assert second.payload_first_seen("forecast", "hash", None, "later") == ("first", "snapshot_capture")
    # Simulate an interrupted writer: evidence appended, cache not updated.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"payload_hash": "new", "captured_at_utc": "new-first"}) + "\n")
    third = SnapshotStore(root=tmp_path, event_slug="fixture")
    assert third.payload_first_seen("forecast", "new", None, "later") == ("new-first", "existing_manifest")
    assert third.payload_first_seen("forecast", "hash", None, "later") == ("first", "snapshot_capture")


def test_cache_publish_race_does_not_bind_old_rows_to_new_file(tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    before = index.signature(path)
    path.write_text("{}\n{}\n", encoding="utf-8")
    index.save_index(path, "first-seen", {"old": ["time", "basis"]}, expected=before)
    assert index.read_index(path, "first-seen") is None


def test_fixture_cycle_read_and_cpu_measurement(tmp_path, monkeypatch):
    store = SnapshotStore(root=tmp_path, event_slug="fixture")
    fields = ["captured_at_local", "snapshot_cadence", "padding"]
    with store.long_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([dict(zip(fields, ["2026-08-01T10:00:00+00:00", "scheduled", "x" * 200]))] * 10000)
    forecast = tmp_path / "forecasts_long.csv"
    archive.append_rows(forecast, archive.FORECAST_COLUMNS, [
        {"source": "eccc_citypage", "forecast_kind": "daily_high", "payload_hash": "hash",
         "condition": "x" * 100}
    ] * 10000)
    manifest = store.forecast_payloads_jsonl_path
    row = {"payload_hash": "hash", "first_seen_at": "first", "first_seen_basis": "fixture"}
    manifest.write_text((json.dumps(row) + "\n") * 10000, encoding="utf-8")
    reads = [0]
    original = Path.open

    class Counted:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): return self.handle.__exit__(*args)
        def __getattr__(self, name): return getattr(self.handle, name)
        def __iter__(self): return self
        def _count(self, value):
            reads[0] += len(value if isinstance(value, bytes) else value.encode("utf-8"))
            return value
        def __next__(self): return self._count(next(self.handle))
        def read(self, *args): return self._count(self.handle.read(*args))
        def readline(self, *args): return self._count(self.handle.readline(*args))

    def opened(path, mode="r", *args, **kwargs):
        handle = original(path, mode, *args, **kwargs)
        return Counted(handle) if "r" in mode and path.parent == tmp_path else handle
    monkeypatch.setattr(Path, "open", opened)

    def old():
        with store.long_path.open(encoding="utf-8", newline="") as handle:
            last = list(csv.DictReader(handle))[-1]["captured_at_local"]
        with forecast.open(encoding="utf-8", newline="") as handle:
            digest = list(csv.DictReader(handle))[-1]["payload_hash"]
        values = {}
        index.add_first_seen(values, store.read_jsonl(manifest))
        return last, digest, tuple(values["hash"])

    def new():
        fresh = SnapshotStore(root=tmp_path, event_slug="fixture")
        return (fresh.last_snapshot_time("scheduled").isoformat(),
                archive.last_payload_hash(forecast, "eccc_citypage", "daily_high"),
                fresh.payload_first_seen("forecast", "hash", None, "later"))

    expected = old()
    assert new() == expected  # cold cache build
    measurements = {}
    for name, fn in [("full", old), ("warm", new)]:
        reads[0] = 0
        cpu, wall = time.process_time(), time.perf_counter()
        for _ in range(5):
            assert fn() == expected
        measurements[name] = {"logical_read_bytes_per_cycle": reads[0] // 5,
                              "cpu_seconds_per_cycle": (time.process_time() - cpu) / 5,
                              "wall_seconds_per_cycle": (time.perf_counter() - wall) / 5}
    assert measurements["warm"]["logical_read_bytes_per_cycle"] < measurements["full"]["logical_read_bytes_per_cycle"] / 10
    (tmp_path / "measurement.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
    print("SNAPSHOT_READ_MEASUREMENT=" + json.dumps(measurements, sort_keys=True))


def test_one_child_import_evaluation_keeps_memory_cap():
    import sys
    from weather.operations.long_job_guard import run_isolated_subprocess
    from weather.collection.snapshot_capture_batch import DEFAULT_CHILD_WORKING_SET_MAX_MB

    # Synthetic import-only workload: no capture, network, credentials or data.
    # This measures the proposed import saving, not fleet capture throughput.
    program = ("import time,json; start=time.process_time(); "
               "import weather.collection.snapshot_tracker; "
               "print(json.dumps({'cpu':time.process_time()-start}))")
    measurements = {}
    for name, count in [("three_children", 3), ("one_child", 1)]:
        cpu = 0.0
        started = time.perf_counter()
        for _ in range(count):
            result = run_isolated_subprocess(
                [sys.executable, "-c", program], timeout_seconds=60,
                working_set_max_bytes=DEFAULT_CHILD_WORKING_SET_MAX_MB * 1024 * 1024,
            )
            assert result["returncode"] == 0, result
            assert not result.get("resource_limit_exceeded")
            cpu += json.loads(result["stdout"].strip().splitlines()[-1])["cpu"]
        measurements[name] = {"child_import_cpu_seconds": cpu,
                              "wall_seconds": time.perf_counter() - started}
    print("SNAPSHOT_CHILD_MEASUREMENT=" + json.dumps(measurements, sort_keys=True))
