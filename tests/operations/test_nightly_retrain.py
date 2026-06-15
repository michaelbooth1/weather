import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from nightly_retrain import build_parser, run_nightly_retrain  # noqa: E402


def _args(tmp, *extra):
    root = Path(tmp)
    return build_parser().parse_args([
        "run",
        "--snapshots-root", str(root / "snapshots"),
        "--backtest-root", str(root / "backtest"),
        "--status-out", str(root / "backtest" / "nightly_retrain_status.json"),
        "--report-out", str(root / "backtest" / "nightly_retrain_report.md"),
        "--family-secondary-out", str(root / "artifacts" / "f_family_secondary_artifacts.json"),
        "--pooled-band-artifact", str(root / "artifacts" / "feature_model_hgb_f_pooled_v0_3.pkl"),
        "--artifact-registry", str(root / "artifacts" / "model_artifact_registry.json"),
        "--promotion-out", str(root / "backtest" / "f_family_promotion_refresh.json"),
        "--promotion-report", str(root / "backtest" / "f_family_promotion_refresh_report.md"),
        "--shadow-ab-out", str(root / "backtest" / "shadow_ab_monitor.json"),
        "--shadow-ab-report", str(root / "backtest" / "shadow_ab_monitor_report.md"),
        "--long-job-state", str(root / "backtest" / "long_job_guard_status.json"),
        "--long-job-lock", str(root / "backtest" / "long_job_guard.lock"),
        "--long-job-priority", "normal",
        *extra,
    ])


def _write_promotion(path, *, promote=None, shadow=None, blocked=None):
    payload = {
        "readiness": {"status": "READY"},
        "serving_gauntlet": {"verdict": "PASS_WITH_SHADOWS"},
        "decisions": {
            "promote_markets": promote or [],
            "shadow_markets": shadow or [],
            "blocked_markets": blocked or [],
            "markets": [
                {"market_id": market_id}
                for market_id in [*(promote or []), *(shadow or []), *(blocked or [])]
            ],
        },
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestNightlyRetrain(unittest.TestCase):
    def test_run_executes_steps_and_reports_promote_ready_status(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "src.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, promote=["nyc"], shadow=["denver"])
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload, status_path, report_path = run_nightly_retrain(args, runner=runner)
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            guard_state = json.loads((Path(tmp) / "backtest" / "long_job_guard_status.json").read_text(encoding="utf-8"))
            report_exists = Path(report_path).exists()

        self.assertEqual([step["name"] for step in payload["steps"]], [
            "family_secondary_artifacts",
            "pooled_feature_model_band",
            "artifact_registry",
            "promotion_refresh",
            "shadow_ab_monitor",
        ])
        self.assertEqual(len(calls), 5)
        self.assertEqual(payload["status"], "promote_ready")
        self.assertEqual(saved["promotion"]["promote_markets"], ["nyc"])
        self.assertTrue(saved["config"]["long_job_guard"]["enabled"])
        self.assertEqual(guard_state["status"], "complete")
        self.assertTrue(report_exists)

    def test_run_marks_blocked_when_promotion_blocks_markets(self):
        def runner(command, **_kwargs):
            if "src.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, blocked=["miami"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["promotion"]["blocked_markets"], ["miami"])

    def test_run_stops_on_step_failure_by_default(self):
        def runner(command, **_kwargs):
            if "src.pooled_feature_model" in command:
                return {"returncode": 2, "stdout": "", "stderr": "training failed"}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "error")
        self.assertEqual([step["name"] for step in payload["steps"]], [
            "family_secondary_artifacts",
            "pooled_feature_model_band",
        ])
        self.assertEqual(payload["steps"][-1]["returncode"], 2)

    def test_dry_run_records_plan_without_running_steps(self):
        def runner(_command, **_kwargs):
            raise AssertionError("dry run should not execute commands")

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(
                _args(tmp, "--dry-run"),
                runner=runner,
            )

        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 5)
        self.assertFalse(payload["config"]["long_job_guard"]["enabled"])


if __name__ == "__main__":
    unittest.main()
