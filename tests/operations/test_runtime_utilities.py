import hashlib
import importlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather import io as weather_io
from weather import time as weather_time
from weather.model.calibration_runtime import load_probability_calibration
from weather.operations import ops_monitor
from weather.operations.ops_monitor import nightly_retrain_status_rows, scheduled_task_rows
from weather.operations.supervisor import jsonl_integrity
from weather.paths import REPO_ROOT, SRC_ROOT


def test_repo_root_import_helpers_are_tracked():
    result = subprocess.run(
        ["git", "ls-files", "sitecustomize.py", "weather/__init__.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert set(result.stdout.splitlines()) == {"sitecustomize.py", "weather/__init__.py"}


def test_supervisor_reexports_shared_writer_lock_primitives():
    supervisor = importlib.import_module("weather.operations.supervisor")

    for name in (
        "writer_lock_path",
        "file_lock_is_stale",
        "acquire_writer_lock",
        "release_writer_lock",
    ):
        assert getattr(supervisor, name) is getattr(weather_io, name)


def test_file_hash_consumers_reexport_shared_helper(tmp_path):
    path = tmp_path / "payload.bin"
    payload = b"weather-code-health\x00\xff"
    path.write_bytes(payload)
    modules = (
        "weather.point_in_time_contract",
        "weather.release_artifacts",
        "weather.calibration.residual_distribution_corpus",
        "weather.operations.cleanup_preflight",
        "weather.operations.closed_market_day_archive",
        "weather.operations.event_day_manifest",
    )

    assert weather_io.sha256_file(path) == hashlib.sha256(payload).hexdigest()
    for module_name in modules:
        module = importlib.import_module(module_name)
        assert module.sha256_file is weather_io.sha256_file


def test_repo_root_subprocess_imports_weather_with_tracked_helpers():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import weather.paths; print(weather.paths.REPO_ROOT)",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert Path(result.stdout.strip()) == REPO_ROOT


def test_non_repo_subprocess_imports_weather_with_explicit_package_path(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import weather.paths; print(weather.paths.REPO_ROOT)",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert Path(result.stdout.strip()) == REPO_ROOT


def test_ops_monitor_restart_clob_preserves_status_config(monkeypatch):
    status = {
        "market_id": "all",
        "target_date": "2026-06-27",
        "interval_seconds": 60.0,
        "fast_interval_seconds": 15.0,
        "fast_hours_before_close": 4.0,
        "fast_after_local_hour": 15.0,
        "fast_on_mid_change_bps": 500.0,
        "outcomes": "all",
        "batch_size": 100,
        "include_price_history": False,
        "include_ws_events": False,
        "websocket_seconds": 1.0,
        "websocket_message_limit": 5,
        "websocket_heartbeat_seconds": 10,
        "websocket_connect_timeout": 5.0,
    }
    captured = {}
    lock = object()

    monkeypatch.setattr(ops_monitor, "read_clob_loop_status", lambda: status)
    monkeypatch.setattr(ops_monitor, "acquire_clob_supervisor_lock", lambda: lock)
    monkeypatch.setattr(ops_monitor, "release_clob_supervisor_lock", lambda handle: None)
    monkeypatch.setattr(ops_monitor, "stop_clob_loop", lambda: {"stopped": True})

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {"started": True}

    monkeypatch.setattr(ops_monitor, "start_clob_loop_detached", fake_start)

    result = ops_monitor.restart_clob_loop()

    assert result["stop"]["stopped"] is True
    assert result["start"]["started"] is True
    assert captured["target_date"] == "2026-06-27"
    assert captured["include_price_history"] is False
    assert captured["include_ws_events"] is False


def test_json_helpers_write_tolerantly_read_and_append_jsonl(tmp_path):
    status_path = tmp_path / "status.json"
    jsonl_path = tmp_path / "events.jsonl"

    weather_io.write_json_atomic(status_path, {"state": "ok", "pid": 123}, trailing_newline=True)
    weather_io.append_jsonl(jsonl_path, {"event": "start", "pid": 123})
    weather_io.append_jsonl(jsonl_path, [{"event": "stop", "pid": 123}])
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write("{invalid json}\n")

    assert weather_io.read_json(status_path)["state"] == "ok"
    assert status_path.read_text(encoding="utf-8").endswith("\n")
    assert [row["event"] for row in weather_io.read_jsonl(jsonl_path)] == ["start", "stop"]
    with pytest.raises(json.JSONDecodeError):
        weather_io.read_jsonl(jsonl_path, skip_invalid=False)
    assert weather_io.read_json(tmp_path / "missing.json", default={"missing": True}) == {"missing": True}


def test_rotating_jsonl_uses_timestamped_collision_safe_siblings(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    now = datetime(2026, 8, 9, 14, 30, tzinfo=timezone.utc)
    path.write_text("legacy\n", encoding="utf-8")

    weather_io.append_rotating_jsonl(path, {"event": "first"}, max_bytes=1, now=now)
    weather_io.append_rotating_jsonl(path, {"event": "second"}, max_bytes=1, now=now)

    rotated = weather_io.rotated_sidecar_paths(path)
    assert {item.name for item in rotated} == {
        "diagnostics.20260809T143000000000Z.jsonl",
        "diagnostics.20260809T143000000000Z.1.jsonl",
    }
    by_name = {item.name: item for item in rotated}
    assert by_name["diagnostics.20260809T143000000000Z.jsonl"].read_text(encoding="utf-8") == "legacy\n"
    assert json.loads(
        by_name["diagnostics.20260809T143000000000Z.1.jsonl"].read_text(encoding="utf-8")
    )["event"] == "first"
    assert json.loads(path.read_text(encoding="utf-8"))["event"] == "second"


def test_rotate_sidecar_retries_transient_windows_permission_error(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text("legacy\n", encoding="utf-8")
    original_rename = Path.rename
    attempts = []
    sleeps = []

    def flaky_rename(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError("transient scanner lock")
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)
    rotated = weather_io.rotate_sidecar(
        path,
        max_bytes=1,
        now=datetime(2026, 8, 9, 14, 30, tzinfo=timezone.utc),
        retry_delay_seconds=0.1,
        sleep_fn=sleeps.append,
    )

    assert rotated is not None and rotated.exists()
    assert not path.exists()
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]


def test_rotate_sidecar_persistent_permission_error_still_fails_closed(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text("legacy\n", encoding="utf-8")
    attempts = []
    sleeps = []

    def locked_rename(source, target):
        attempts.append((source, target))
        raise PermissionError("persistent scanner lock")

    monkeypatch.setattr(Path, "rename", locked_rename)
    with pytest.raises(PermissionError, match="persistent scanner lock"):
        weather_io.rotate_sidecar(
            path,
            max_bytes=1,
            now=datetime(2026, 8, 9, 14, 30, tzinfo=timezone.utc),
            max_attempts=3,
            retry_delay_seconds=0.1,
            sleep_fn=sleeps.append,
        )

    assert path.exists()
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]


def test_jsonl_integrity_counts_malformed_lines(tmp_path):
    path = tmp_path / "loop_console.log"
    path.write_text('{"ok": true}\nnot-json\n{"ok": false}\n', encoding="utf-8")

    payload = jsonl_integrity(path)

    assert payload["line_count"] == 3
    assert payload["valid_json_lines"] == 2
    assert payload["malformed_lines"] == 1
    assert not payload["ok"]


def test_atomic_json_write_retries_replace_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    original_replace = Path.replace
    calls = {"count": 0}

    def flaky_replace(self, target):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("locked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    weather_io.write_json_atomic(path, {"status": "ok"}, retries=2, sleep_fn=lambda _seconds: None)

    assert calls["count"] == 2
    assert weather_io.read_json(path)["status"] == "ok"


def test_csv_helpers_write_and_append_rows(tmp_path):
    path = tmp_path / "rows.csv"

    weather_io.write_csv_rows(path, ["name", "value"], [{"name": "a", "value": 1, "extra": "ignored"}])
    weather_io.append_csv_rows(path, ["name", "value"], [{"name": "b", "value": 2}])

    assert path.read_text(encoding="utf-8").splitlines() == [
        "name,value",
        "a,1",
        "b,2",
    ]


def test_time_helpers_parse_utc_and_compute_age():
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    then = now - timedelta(seconds=90)

    assert weather_time.parse_datetime(then.isoformat()) == then
    assert weather_time.parse_datetime("2026-06-16T11:58:30Z") == then
    assert weather_time.age_seconds(now, then.isoformat()) == 90
    assert weather_time.age_minutes(now, then.isoformat()) == 1.5
    assert weather_time.parse_datetime("not-a-date") is None


def test_runtime_artifact_load_failures_use_logging(tmp_path, caplog):
    path = tmp_path / "probability_calibration.json"
    path.write_text("{invalid", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="weather.model.calibration_runtime"):
        assert load_probability_calibration(path) is None

    assert "Error loading probability calibration artifact" in caplog.text


def test_operations_task_inventory_includes_nightly_retrain():
    tasks = {row["Task"] for row in scheduled_task_rows()}

    assert "WeatherNightlyRetrainValidatePromote" in tasks


def test_operations_dashboard_includes_nightly_retrain_sla_row(monkeypatch):
    monkeypatch.setattr(
        "weather.operations.ops_monitor.scheduled_task_status",
        lambda _name: {"Registered": True, "State": "Ready", "Last Run": None, "Next Run": None, "Result": None},
    )
    monkeypatch.setattr(
        "weather.operations.ops_monitor.nightly_run_sla_status",
        lambda **_kwargs: {
            "state": "BLOCKED",
            "run_status": "blocked",
            "task_registered": True,
            "task_state": "Ready",
            "task_last_run": None,
            "task_next_run": "2026-06-18T03:30:00",
            "latest_due_local": "2026-06-17T03:30:00-04:00",
            "fresh_for_latest_window": True,
            "run_generated_at_utc": "2026-06-17T08:00:00+00:00",
            "run_age_hours": 2.0,
            "daily_learning_status": "BLOCKED",
            "daily_learning_blocker_count": 1,
            "p0_gate": "Data-layer audit failed.",
        },
    )

    row = nightly_retrain_status_rows(status_payload={})

    assert row["Job"] == "Nightly retrain"
    assert row["State"] == "BLOCKED"
    assert row["Task Registered"] is True
    assert row["P0 Gate"] == "Data-layer audit failed."


def test_operations_dashboard_uses_delegated_nightly_sla_binding(monkeypatch):
    observed = {}

    def task_status(name):
        observed["task"] = name
        return {"Registered": True, "State": "Disabled"}

    def sla_status(**kwargs):
        observed.update(kwargs)
        return {
            "state": "PENDING",
            "run_status": "blocked",
            "task_registered": True,
            "task_state": "Disabled",
            "fresh_for_latest_window": False,
        }

    monkeypatch.setattr(
        "weather.operations.ops_monitor.scheduled_task_status", task_status
    )
    monkeypatch.setattr(
        "weather.operations.ops_monitor.nightly_run_sla_status", sla_status
    )
    payload = {
        "invocation": {
            "scheduler_attested": True,
            "task_name": "WeatherTrainingWindow",
        },
        "nightly_sla": {
            "task_name": "WeatherTrainingWindow",
            "schedule_local_time": "01:00",
            "schedule_timezone": "America/Toronto",
        },
    }

    row = nightly_retrain_status_rows(status_payload=payload)

    assert observed["task"] == "WeatherTrainingWindow"
    assert observed["task_name"] == "WeatherTrainingWindow"
    assert observed["schedule_local_time"] == "01:00"
    assert row["Task State"] == "Disabled"
    assert row["Topology Bound"] is True


def test_operations_dashboard_rejects_unattested_delegated_hint(monkeypatch):
    observed = {}

    def task_status(name):
        observed["task"] = name
        return {"Registered": True, "State": "Disabled"}

    monkeypatch.setattr(
        "weather.operations.ops_monitor.scheduled_task_status", task_status
    )
    monkeypatch.setattr(
        "weather.operations.ops_monitor.nightly_run_sla_status",
        lambda **kwargs: observed.update(kwargs) or {"state": "PENDING"},
    )
    payload = {
        "invocation": {
            "scheduler_attested": False,
            "task_name": "WeatherTrainingWindow",
        },
        "nightly_sla": {
            "task_name": "WeatherTrainingWindow",
            "schedule_local_time": "01:00",
            "schedule_timezone": "America/Toronto",
        },
    }

    row = nightly_retrain_status_rows(status_payload=payload)

    assert observed["task"] == "WeatherNightlyRetrainValidatePromote"
    assert observed["schedule_local_time"] == "03:30"
    assert row["Topology Bound"] is False
