import json
from datetime import datetime, timezone
from unittest import mock

from streamlit.testing.v1 import AppTest

from app.views.operations import (
    _capture_streak_from_host_status,
    _daily_refresh_summary,
    _json_artifact,
    host_status_snapshot,
)


def _operations_fixture():
    return {
        "host_status": {
            "available": True,
            "path": "fixture://status.ps1",
            "payload": {
                "ts": "2026-06-25 08:30",
                "verdict": "OK",
                "flags": [],
                "warns": ["mirror receipt is aging"],
                "ram_free_gb": 5.2,
                "disk": {"free_gb": 220.0, "days_left": 71},
                "watchdog": {"verdict": "OK", "age_min": 8},
            },
        },
        "capture_streak": {
            "available": True,
            "path": "fixture://streak_status.py",
            "payload": {
                "streak_days": 9,
                "target": 14,
                "streak_start": "2026-06-16",
                "most_recent_settled": "2026-06-24",
                "projected_lock_date_if_all_clean": "2026-06-29",
                "today_health": {
                    "verdict": "on_track",
                    "captures": 20,
                    "max_window_gap_min": 10,
                },
                "recent_tape": [
                    {"date": "2026-06-23", "grade": "complete"},
                    {"date": "2026-06-24", "grade": "complete"},
                ],
            },
        },
        "release_clock": {
            "available": True,
            "path": "fixture://release-clock.json",
            "recorded_at": "2026-06-25T08:00:00+00:00",
            "age": "30 minutes ago",
            "payload": {
                "contiguous_pass_days": 7,
                "streak_start_date": "2026-06-18",
                "evaluation_end_date": "2026-06-24",
                "latest_status": "PASS",
                "latest_reason_code": "release_admissible",
            },
        },
        "daily_refresh": {
            "available": True,
            "path": "fixture://daily-refresh.json",
            "recorded_at": "2026-06-25T08:15:00+00:00",
            "age": "15 minutes ago",
            "payload": {
                "status": "critical",
                "terminal": True,
                "steps": [{"name": "promotion_gate", "status": "ok"}],
            },
        },
        "morning_briefing": {
            "available": True,
            "path": "fixture://MORNING_BRIEFING.md",
            "recorded_at": "2026-06-25T08:20:00+00:00",
            "age": "10 minutes ago",
            "text": "# Fixture briefing\n\nNo capture incidents are open.",
        },
    }


def test_host_truth_panel_distinguishes_capture_and_release_clocks_visibly():
    script = "\n".join((
        "from app.views.operations import render_host_truth",
        f"snapshot = {_operations_fixture()!r}",
        "render_host_truth(snapshot)",
    ))
    app_test = AppTest.from_string(script).run()

    assert not app_test.exception
    assert "Host Status" in [item.value for item in app_test.subheader]
    assert "Capture and Release Clocks" in [item.value for item in app_test.subheader]
    assert "Daily Refresh" in [item.value for item in app_test.subheader]
    assert "Morning Briefing" in [item.value for item in app_test.subheader]
    metrics = {item.label: item.value for item in app_test.metric}
    assert metrics["Host verdict"] == "OK"
    assert metrics["Disk headroom"] == "71 days"
    assert metrics["Capture streak"] == "9 / 14"
    assert metrics["Release-admissible days"] == "7"
    assert metrics["Today's capture"] == "ON_TRACK"
    assert metrics["Daily refresh"] == "CRITICAL"
    captions = "\n".join(item.value for item in app_test.caption)
    assert "necessary, never sufficient" in captions
    assert "not proof that a run is active now" in captions


def test_host_truth_panel_surfaces_missing_evidence_instead_of_defaulting_to_healthy():
    missing = {
        key: {"available": False, "path": f"fixture://{key}", "error": "file missing"}
        for key in (
            "host_status",
            "capture_streak",
            "release_clock",
            "daily_refresh",
            "morning_briefing",
        )
    }

    script = "\n".join((
        "from app.views.operations import render_host_truth",
        f"snapshot = {missing!r}",
        "render_host_truth(snapshot)",
    ))
    app_test = AppTest.from_string(script).run()

    assert not app_test.exception
    warning_text = "\n".join(item.value for item in app_test.warning)
    info_text = "\n".join(item.value for item in app_test.info)
    assert "Capture streak unavailable: file missing" in warning_text
    assert "Host status unavailable: file missing" in warning_text
    assert "Release clock unavailable: file missing" in warning_text
    assert "Daily refresh status unavailable: file missing" in warning_text
    assert "Morning briefing unavailable: file missing" in info_text


def test_daily_refresh_running_step_overrides_stale_terminal_flag():
    summary = _daily_refresh_summary({
        "available": True,
        "payload": {
            "status": "critical",
            "terminal": True,
            "current_step": {"name": "daily_learning", "status": "running"},
        },
    })

    assert summary["run_state"] == "RUNNING NOW"
    assert summary["step"] == "daily_learning"


def test_json_artifact_reports_malformed_and_records_age(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert _json_artifact(malformed)["available"] is False

    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps({"generated_at_utc": "2026-06-25T08:00:00+00:00", "status": "ok"}),
        encoding="utf-8",
    )
    artifact = _json_artifact(valid)

    assert artifact["available"] is True
    assert artifact["recorded_at"] == "2026-06-25T08:00:00+00:00"
    assert "hours ago" in artifact["age"] or "minutes ago" in artifact["age"]
    assert datetime.fromisoformat(artifact["recorded_at"]).astimezone(timezone.utc)


@mock.patch("app.views.operations.subprocess.run")
def test_host_attention_exit_is_valid_and_supplies_capture_clock(mock_run):
    mock_run.return_value = mock.Mock(
        returncode=2,
        stdout=json.dumps({
            "verdict": "ATTENTION",
            "flags": ["capture loop down"],
            "streak": {
                "days": 4,
                "target": 14,
                "start": "2026-06-21",
                "today": "AT_RISK",
                "lock": "2026-07-01",
                "settled": "2026-06-24",
            },
        }),
        stderr="",
    )

    host = host_status_snapshot(script_path="fixture-status.ps1")
    capture = _capture_streak_from_host_status(host)

    assert host["available"] is True
    assert host["payload"]["verdict"] == "ATTENTION"
    assert capture["payload"]["streak_days"] == 4
    assert capture["payload"]["today_summary"] == "AT_RISK"
