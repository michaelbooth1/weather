import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather import io as weather_io
from weather import time as weather_time
from weather.model.calibration_runtime import load_probability_calibration
from weather.operations.ops_monitor import nightly_retrain_status_rows, scheduled_task_rows
from weather.operations.supervisor import jsonl_integrity


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

    row = nightly_retrain_status_rows()

    assert row["Job"] == "Nightly retrain"
    assert row["State"] == "BLOCKED"
    assert row["Task Registered"] is True
    assert row["P0 Gate"] == "Data-layer audit failed."
