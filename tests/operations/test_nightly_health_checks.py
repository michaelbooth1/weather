import json
import tempfile
import unittest
from pathlib import Path

from weather.operations import nightly_health_checks


def _identity(source="src-current", commit="abc123"):
    return {
        "schema_version": "runtime_identity_v0.1",
        "git_branch": "master",
        "git_commit": commit,
        "source_fingerprint": source,
        "source_file_count": 10,
        "python_version": "3.11",
    }


def _fleet_payload(loop_row=None):
    row = loop_row or {
        "name": "snapshot_capture",
        "status": "PASS",
        "state": "RUNNING",
        "runtime_code_state": "current",
        "single_writer": True,
        "restart_count": 0,
        "restart_budget": 6,
        "blocking_reasons": [],
        "immediate_repair_commands": [],
    }
    return {
        "status": "OK",
        "generated_at_utc": "2026-06-18T22:55:00+00:00",
        "current_code_soak": {
            "status": "PASS" if row["status"] == "PASS" else "BLOCK",
            "loops": [row],
            "summary": {"blocking_loop_count": 0 if row["status"] == "PASS" else 1},
        },
        "live_forward_slo": {"status": "PASS"},
        "summary": {"critical_alerts": 0, "warning_alerts": 0},
        "alerts": [],
    }


class TestNightlyHealthChecks(unittest.TestCase):
    def test_build_payload_passes_when_loops_are_current(self):
        current = _identity()

        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(),
            current_identity=current,
            now="2026-06-18T23:00:00+00:00",
            target_date="2026-06-18",
        )

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["summary"]["running_bot_count"], 0)
        self.assertEqual(payload["summary"]["retired_bot_count"], 2)

    def test_build_payload_alerts_on_stale_loop(self):
        current = _identity()
        loop_row = {
            "name": "snapshot_capture",
            "status": "BLOCK",
            "state": "RUNNING",
            "runtime_code_state": "stale_code",
            "single_writer": True,
            "restart_count": 1,
            "restart_budget": 6,
            "blocking_reasons": ["runtime_code_state=stale_code"],
            "immediate_repair_commands": ["python -m weather.collection.snapshot_tracker --restart"],
            "status_path": "loop_status.json",
        }

        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(loop_row),
            current_identity=current,
            now="2026-06-18T23:00:00+00:00",
            target_date="2026-06-18",
        )

        categories = {alert["category"] for alert in payload["alerts"]}
        self.assertEqual(payload["status"], "CRITICAL")
        self.assertIn("loop_current_code_soak", categories)
        self.assertFalse(any(category.startswith("bot_") for category in categories))

    def test_write_outputs_creates_dated_and_latest_alert_reports(self):
        current = _identity()
        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(),
            current_identity=current,
            now="2026-06-18T23:00:00+00:00",
            target_date="2026-06-18",
        )

        with tempfile.TemporaryDirectory() as tmp:
            outputs = nightly_health_checks.write_outputs(payload, alert_root=Path(tmp) / "alerts")
            dated = Path(outputs["report_out"])
            latest = Path(outputs["latest_report_out"])
            saved = json.loads(Path(outputs["json_out"]).read_text(encoding="utf-8"))

        self.assertTrue(dated.name.endswith(".md"))
        self.assertEqual(dated.parent.name, "2026-06-18")
        self.assertTrue(latest.name.endswith(".md"))
        self.assertEqual(saved["schema_version"], "nightly_health_checks_v0.1")


if __name__ == "__main__":
    unittest.main()


def test_retired_bots_are_reported_without_reads_or_restarts():
    payload = nightly_health_checks.build_payload(
        fleet_payload=_fleet_payload(), current_identity=_identity(), now="2026-09-26T20:00:00Z",
    )
    assert payload["status"] == "OK"
    assert payload["summary"]["retired_bot_count"] == 2
    assert {row["component"] for row in payload["bots"]} == {"maker_bot", "taker_bot"}
    assert all(row["status"] == "RETIRED" and row["restart_command"] is None for row in payload["bots"])
    report = nightly_health_checks.render_report(payload)
    assert "start --force" not in report
    assert "daily_roll" not in report
    assert not hasattr(nightly_health_checks, "latest_maker_run_summary")
