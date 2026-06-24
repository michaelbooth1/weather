import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from weather.operations.nightly_retrain import (  # noqa: E402
    build_parser,
    nightly_run_sla_status,
    run_nightly_retrain,
)


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
        "--daily-learning-out", str(root / "backtest" / "daily_learning.json"),
        "--daily-learning-report", str(root / "backtest" / "daily_learning_report.md"),
        "--experiment-queue-results-out", str(root / "backtest" / "experiment_queue_results.json"),
        "--labels-csv", str(root / "backtest" / "market_day_labels.csv"),
        "--ledger-root", str(root / "settlements"),
        "--settled-day-freshness-out", str(root / "backtest" / "settled_day_freshness.json"),
        "--settled-day-freshness-report", str(root / "backtest" / "settled_day_freshness_report.md"),
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
            if "weather.reporting.promotion_refresh" in command:
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
            "settled_day_freshness",
            "daily_learning",
            "experiment_queue",
            "family_secondary_artifacts",
            "pooled_feature_model_band",
            "artifact_registry",
            "promotion_refresh",
            "shadow_ab_monitor",
        ])
        self.assertEqual(len(calls), 7)
        self.assertIn("weather.operations.settled_day_freshness", calls[0])
        self.assertEqual(payload["status"], "promote_ready")
        self.assertEqual(saved["promotion"]["promote_markets"], ["nyc"])
        self.assertTrue(saved["config"]["long_job_guard"]["enabled"])
        self.assertEqual(guard_state["status"], "complete")
        self.assertTrue(report_exists)

    def test_run_marks_blocked_when_promotion_blocks_markets(self):
        def runner(command, **_kwargs):
            if "weather.reporting.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, blocked=["miami"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["promotion"]["blocked_markets"], ["miami"])

    def test_run_stops_on_step_failure_by_default(self):
        def runner(command, **_kwargs):
            if "weather.calibration.pooled_feature_model" in command:
                return {"returncode": 2, "stdout": "", "stderr": "training failed"}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "error")
        self.assertEqual([step["name"] for step in payload["steps"]], [
            "settled_day_freshness",
            "daily_learning",
            "experiment_queue",
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
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 8)
        self.assertFalse(payload["config"]["long_job_guard"]["enabled"])

    def test_experiment_queue_step_executes_top_eligible_items_and_writes_results(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "ACTIONABLE",
                        "run_date": "2026-06-24",
                        "summary": {"learning_count": 1, "blocker_count": 0},
                        "retrain_plan": {
                            "training_ready": True,
                            "retrain_recommendation": {
                                "recommended": True,
                                "status": "RECOMMENDED",
                                "scheduled_fallback": False,
                                "reasons": [{"code": "eligible_experiment_queue"}],
                            },
                        },
                        "experiment_queue": {
                            "status": "READY",
                            "summary": {"queue_count": 1, "eligible_count": 1},
                            "items": [
                                {
                                    "queue_id": "item301:2026-06-23:seattle:cold_miss",
                                    "status": "queued",
                                    "priority": "P1",
                                    "source": "june23_location_bias_repair_packet",
                                    "category": "june23_location_bias_repair",
                                    "slice": "market_id=seattle;bias=cold_miss",
                                    "hypothesis": "repair seattle cold miss",
                                    "artifact_path": "data/backtest/june23_location_bias_repair_packet.json",
                                    "clearance_rule": "protect winners",
                                    "command": ["python", "-m", "weather.reporting.june23_location_bias_repair"],
                                }
                            ],
                        },
                        "learnings": [],
                    }),
                    encoding="utf-8",
                )
            if "weather.reporting.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, shadow=["nyc"])
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)
            results = json.loads((Path(tmp) / "backtest" / "experiment_queue_results.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "shadow")
        self.assertEqual(results["schema_version"], "experiment_queue_results_v0.1")
        self.assertEqual(results["executed_count"], 1)
        self.assertEqual(results["results"][0]["queue_id"], "item301:2026-06-23:seattle:cold_miss")
        self.assertTrue(any("weather.reporting.june23_location_bias_repair" in command for command in calls))

    def test_no_retrain_recommendation_can_skip_expensive_steps_without_disabling_default_schedule(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "ACTIONABLE",
                        "run_date": "2026-06-24",
                        "summary": {"learning_count": 0, "blocker_count": 0},
                        "retrain_plan": {
                            "training_ready": True,
                            "retrain_recommendation": {
                                "recommended": False,
                                "status": "NOT_RECOMMENDED",
                                "scheduled_fallback": False,
                                "reasons": [{"code": "no_new_drift_or_novelty"}],
                            },
                        },
                        "experiment_queue": {
                            "status": "EMPTY",
                            "summary": {"queue_count": 0, "eligible_count": 0},
                            "items": [],
                        },
                        "learnings": [],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(
                _args(tmp, "--skip-when-no-retrain-recommendation"),
                runner=runner,
            )

        self.assertEqual(payload["status"], "skipped_no_retrain_recommendation")
        self.assertEqual(payload["promotion"]["reason"], "retrain_not_recommended")
        self.assertIn("retrain_recommendation_gate", [step["name"] for step in payload["steps"]])
        self.assertFalse(any("weather.calibration.family_secondary_artifacts" in command for command in calls))

    def test_daily_learning_blocker_marks_run_blocked_by_default(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-16",
                        "summary": {"learning_count": 2, "blocker_count": 1},
                        "retrain_plan": {"training_ready": False},
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "data_quality",
                                "source": "data_layer_audit",
                                "signal": "Data-layer audit failed.",
                                "action": "Fix failed data-layer gates before retraining.",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            if "weather.reporting.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, shadow=["nyc"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_nightly_retrain(_args(tmp), runner=runner)
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["daily_learning"]["status"], "BLOCKED")
        self.assertEqual(payload["promotion"]["verdict"], "not_run")
        self.assertEqual(payload["promotion"]["reason"], "daily_learning_blocked")
        self.assertEqual([step["name"] for step in payload["steps"]], ["settled_day_freshness", "daily_learning"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(payload["nightly_sla"]["state"], "BLOCKED")
        self.assertIn("daily_learning_blocked", report)
        self.assertIn("Data-layer audit failed.", report)
        self.assertIn("Fix failed data-layer gates before retraining.", report)

    def test_nightly_report_surfaces_broad_live_forward_slo_recovery(self):
        def runner(command, **_kwargs):
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-17",
                        "summary": {"learning_count": 1, "blocker_count": 1},
                        "retrain_plan": {
                            "training_ready": False,
                            "promotion_ready": False,
                            "broad_live_forward_slo": {
                                "status": "BLOCK",
                                "counts_toward_live_forward_gate": False,
                                "reason": "clob_book_freshness blocks broad live-forward SLO for nyc",
                                "first_blocker": {
                                    "market_id": "nyc",
                                    "component": "clob_book_capture",
                                    "gate": "clob_book_freshness",
                                    "owner": "CLOB book supervisor",
                                    "repair_command": "python -m weather.market.market_microstructure ensure",
                                    "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                                },
                                "recovery_checklist": [
                                    {
                                        "market_id": "nyc",
                                        "component": "clob_book_capture",
                                        "gate": "clob_book_freshness",
                                        "owner": "CLOB book supervisor",
                                        "repair_command": "python -m weather.market.market_microstructure ensure",
                                    }
                                ],
                                "rerun_command": "python -m weather.reporting.fleet.fleet_observability report",
                            },
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "collection_health",
                                "source": "fleet_observability",
                                "signal": "clob_book_freshness blocks broad live-forward SLO for nyc",
                                "action": "python -m weather.market.market_microstructure ensure",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_nightly_retrain(_args(tmp), runner=runner)
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(
            payload["daily_learning"]["broad_live_forward_slo"]["first_blocker"]["gate"],
            "clob_book_freshness",
        )
        self.assertEqual(payload["nightly_sla"]["broad_live_forward_slo_counts"], False)
        self.assertIn("## Broad Live-Forward SLO", report)
        self.assertIn("clob_book_freshness", report)
        self.assertIn("weather.market.market_microstructure ensure", report)

    def test_nightly_status_carries_variant_learning_gate_from_daily_learning(self):
        def runner(command, **_kwargs):
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-18",
                        "summary": {"learning_count": 1, "blocker_count": 1},
                        "retrain_plan": {
                            "training_ready": False,
                            "variant_learning_gate": {
                                "status": "BLOCK",
                                "first_blocker": {
                                    "gate": "variant_evidence_sla",
                                    "detail": "no independent growth",
                                    "remediation_command": "Collect new settled labels.",
                                },
                            },
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "variant_learning_operational_gate",
                                "source": "daily_refresh_status",
                                "signal": "Variant learning operational gate blocked.",
                                "action": "Collect new settled labels.",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["daily_learning"]["variant_learning_gate"]["status"], "BLOCK")
        self.assertEqual(
            payload["daily_learning"]["variant_learning_gate"]["first_blocker"]["gate"],
            "variant_evidence_sla",
        )

    def test_nightly_run_sla_flags_missed_run_after_scheduled_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            sla = nightly_run_sla_status(
                status_path=Path(tmp) / "missing_status.json",
                task_status={"Registered": True, "State": "Ready"},
                now=datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(sla["state"], "CRITICAL")
        self.assertFalse(sla["fresh_for_latest_window"])
        self.assertEqual(sla["alerts"][0]["category"], "nightly_retrain_missed_run")

    def test_nightly_run_sla_surfaces_first_daily_learning_blocker(self):
        status_payload = {
            "status": "blocked",
            "generated_at_utc": "2026-06-17T08:00:00+00:00",
            "daily_learning": {
                "status": "BLOCKED",
                "blocker_count": 1,
                "blockers": [
                    {
                        "priority": "P0",
                        "category": "collection_health",
                        "source": "fleet_observability",
                        "signal": "Fleet status CRITICAL",
                        "action": "Repair collection loops.",
                    }
                ],
            },
        }

        sla = nightly_run_sla_status(
            status_payload=status_payload,
            task_status={"Registered": True, "State": "Ready"},
            now=datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(sla["state"], "BLOCKED")
        self.assertTrue(sla["fresh_for_latest_window"])
        self.assertEqual(sla["p0_gate"], "Fleet status CRITICAL")
        self.assertEqual(sla["p0_action"], "Repair collection loops.")


if __name__ == "__main__":
    unittest.main()
