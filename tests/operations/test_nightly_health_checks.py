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


def _maker_status(identity):
    return {
        "exists": True,
        "path": "maker-status.json",
        "status": "started",
        "pid": 1001,
        "target_date": "2026-06-18",
        "started_at_utc": "2026-06-18T19:30:00+00:00",
        "runs_root": "mm-runs",
        "runtime_identity": identity,
    }


def _taker_status(identity, status="already_running"):
    return {
        "exists": True,
        "path": "taker-status.json",
        "status": status,
        "pid": 2002,
        "target_date": "2026-06-18",
        "started_at_utc": "2026-06-18T00:05:00+00:00",
        "runtime_identity": identity,
        "artifact_liveness": {
            "status": "PASS",
            "ok": True,
            "latest_useful_artifact": {"age_seconds": 30.0},
        },
    }


def _maker_run_summary():
    return {
        "exists": True,
        "status": "ok",
        "path": "run_summary.json",
        "age_seconds": 30.0,
        "useful_work_liveness": {"status": "PASS", "blocker_count": 0},
    }


class TestNightlyHealthChecks(unittest.TestCase):
    def test_build_payload_passes_when_loops_and_bots_are_current(self):
        current = _identity()

        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(),
            maker_status=_maker_status(current),
            taker_status=_taker_status(current),
            maker_run_summary=_maker_run_summary(),
            current_identity=current,
            now="2026-06-18T23:00:00+00:00",
            target_date="2026-06-18",
        )

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["summary"]["running_bot_count"], 2)
        self.assertEqual(payload["summary"]["current_code_bot_count"], 2)

    def test_build_payload_alerts_on_stale_loop_stale_maker_and_dead_taker(self):
        current = _identity()
        stale = _identity(source="src-old", commit="old123")
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
        taker = _taker_status(current, status="pid_missing")
        taker["root_cause_class"] = "pid_missing"

        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(loop_row),
            maker_status=_maker_status(stale),
            taker_status=taker,
            maker_run_summary=_maker_run_summary(),
            current_identity=current,
            now="2026-06-18T23:00:00+00:00",
            target_date="2026-06-18",
        )

        categories = {alert["category"] for alert in payload["alerts"]}
        self.assertEqual(payload["status"], "CRITICAL")
        self.assertIn("loop_current_code_soak", categories)
        self.assertIn("bot_runtime_identity", categories)
        self.assertIn("bot_liveness", categories)

    def test_write_outputs_creates_dated_and_latest_alert_reports(self):
        current = _identity()
        payload = nightly_health_checks.build_payload(
            fleet_payload=_fleet_payload(),
            maker_status=_maker_status(current),
            taker_status=_taker_status(current),
            maker_run_summary=_maker_run_summary(),
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
