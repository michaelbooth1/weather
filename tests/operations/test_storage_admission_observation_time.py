"""Regressions for heartbeat publication racing with storage admission reads."""

from datetime import datetime, timedelta, timezone
import json

import pytest

from weather.operations import replay_cache_compression_admission as admission


START = datetime(2026, 9, 8, 5, tzinfo=timezone.utc)
FINISH = START + timedelta(milliseconds=20)


def observe(tmp_path, monkeypatch, *, heartbeat, clean):
    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return START if cls.calls == 1 else FINISH

    monkeypatch.setattr(admission, "datetime", Clock)
    monkeypatch.setattr(admission, "observe_process_identity",
                        lambda pid: {"state": "running", "creation_time_token": "fixture-generation"})
    monkeypatch.setattr(admission, "available_memory_bytes", lambda: 8 * admission.GIB)
    monkeypatch.setattr(admission, "host_commit_percent", lambda: 50)
    monkeypatch.setattr(admission.shutil, "disk_usage",
                        lambda root: type("Usage", (), {"free": 30 * admission.GIB})())
    monkeypatch.setattr(admission, "process_memory_bytes",
                        lambda: {"private_bytes": 1024**2, "working_set_bytes": 1024**2})
    monkeypatch.setattr(admission, "current_process_priority", lambda: 0x4000)
    specs = admission.default_loop_specs(tmp_path / "data" / "snapshots")
    specs[0].status_path.parent.mkdir(parents=True)
    for spec in specs:
        spec.status_path.write_text(json.dumps({
            "pid": 1234, "consecutive_errors": 0, "paused": False,
            "last_heartbeat": heartbeat.isoformat(),
            "last_clean_iteration_at": clean.isoformat(),
        }))
        spec.status_path.with_name(f".{spec.status_path.name}.writer.lock").write_text(json.dumps({
            "pid": 1234,
            "managed_process": {"pid": 1234, "creation_time_token": "fixture-generation"},
        }))
    return admission.capture_admission(tmp_path)


def test_heartbeat_published_during_status_reads_is_not_future(tmp_path, monkeypatch):
    published = START + timedelta(milliseconds=7)
    result = observe(tmp_path, monkeypatch, heartbeat=published, clean=published)
    assert result["status"] == "PASS"
    assert result["checked_at_utc"] == FINISH.isoformat()
    for row in result["capture_loops"]:
        assert row["heartbeat_age_seconds"] == pytest.approx(0.013)
        assert row["last_clean_iteration_age_seconds"] == pytest.approx(0.013)


@pytest.mark.parametrize("kind", ["heartbeat", "clean"])
def test_timestamp_beyond_completed_read_is_still_rejected(tmp_path, monkeypatch, kind):
    future = FINISH + timedelta(milliseconds=1)
    result = observe(tmp_path, monkeypatch,
                     heartbeat=future if kind == "heartbeat" else START,
                     clean=future if kind == "clean" else START)
    assert result["status"] == "BLOCK"
    expected = "capture_unhealthy:snapshot" if kind == "heartbeat" else "snapshot_clean_iteration_missing_or_stale"
    assert expected in result["reasons"]


@pytest.mark.parametrize("kind,limit", [("heartbeat", 180), ("clean", 900)])
def test_timestamp_expiring_during_reads_is_rejected(tmp_path, monkeypatch, kind, limit):
    # Valid at the initial clock; stale by 13 ms when all reads have completed.
    expiring = START - timedelta(seconds=limit) + timedelta(milliseconds=7)
    result = observe(tmp_path, monkeypatch,
                     heartbeat=expiring if kind == "heartbeat" else START,
                     clean=expiring if kind == "clean" else START)
    assert result["status"] == "BLOCK"
    expected = "capture_unhealthy:snapshot" if kind == "heartbeat" else "snapshot_clean_iteration_missing_or_stale"
    assert expected in result["reasons"]
