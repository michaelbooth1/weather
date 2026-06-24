import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.daily.daily_flow_analysis import build_flow_analysis, render_report, write_outputs


def write_flow_artifacts(root, *, blocked=True):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "daily_refresh_status.json").write_text(
        json.dumps({
            "schema_version": "daily_refresh_v0.4",
            "generated_at_utc": "2026-06-21T23:55:00+00:00",
            "status": "ok",
            "steps": [
                {"name": "promotion_refresh", "status": "ok", "duration_seconds": 12.5},
                {"name": "daily_learning", "status": "ok", "duration_seconds": 3.0},
            ],
            "summary": {},
        }),
        encoding="utf-8",
    )
    learnings = []
    if blocked:
        learnings.append({
            "priority": "P0",
            "category": "operational_slo",
            "source": "fleet_observability",
            "signal": "live-forward SLO blocked for toronto",
            "action": "python -m weather.reporting.fleet.fleet_observability report",
            "blocker": True,
            "evidence": {"market_id": "toronto"},
        })
    else:
        learnings.append({
            "priority": "P2",
            "category": "model_gap_slice",
            "source": "snapshot_evaluation",
            "signal": "minor model slice gap",
            "action": "Track in tomorrow's replay.",
            "blocker": False,
        })
    (root / "daily_learning.json").write_text(
        json.dumps({
            "schema_version": "daily_learning_v0.1",
            "generated_at_utc": "2026-06-21T23:56:00+00:00",
            "run_date": "2026-06-21",
            "status": "BLOCKED" if blocked else "OK",
            "summary": {
                "learning_count": len(learnings),
                "blocker_count": 1 if blocked else 0,
            },
            "input_gate": {
                "status": "PASS",
                "coverage": {
                    "status": "PASS",
                    "present_count": 6,
                    "total_count": 6,
                    "critical_missing_inputs": [],
                },
                "freshness": {
                    "status": "PASS",
                    "critical_stale_inputs": [],
                },
                "consistency": {
                    "status": "PASS",
                    "failed_invariants": [],
                },
            },
            "retrain_plan": {
                "training_ready": not blocked,
                "promotion_ready": not blocked,
            },
            "scorecard": {
                "fleet": {
                    "status": "CRITICAL" if blocked else "OK",
                    "live_forward_slo": {"status": "BLOCK" if blocked else "PASS"},
                },
                "trading_evidence": {
                    "taker": {
                        "net_pnl_usdc": -4.5 if blocked else 2.0,
                        "quality_gate": {"status": "BLOCK" if blocked else "PASS"},
                    },
                    "market_making": {
                        "evidence_mode": "paper-live-forward",
                        "counts_toward_live_forward_gate": not blocked,
                    },
                },
            },
            "learnings": learnings,
        }),
        encoding="utf-8",
    )
    (root / "daily_progress_latest.json").write_text(
        json.dumps({
            "schema_version": "daily_progress_ledger_v0.1",
            "generated_at_utc": "2026-06-21T23:57:00+00:00",
            "run_date": "2026-06-21",
            "broad_improvement_claim_allowed": not blocked,
            "broad_improvement_claim_failures": json.dumps(["live_forward_slo_not_pass"] if blocked else []),
            "ops_disk_preflight_status": "OBSERVED",
        }),
        encoding="utf-8",
    )
    (root / "settled_day_root_cause.json").write_text(
        json.dumps({
            "schema_version": "settled_day_root_cause_v0.1",
            "generated_at_utc": "2026-06-21T23:58:00+00:00",
            "target_date": "2026-06-21",
            "status": "ACTIONABLE" if blocked else "OK",
            "summary": {
                "issue_count": 2 if blocked else 0,
                "issue_counts": {"MODEL_TOP_WARM_SIDE_MISS": 2} if blocked else {},
                "taker_net_pnl_usdc": -4.5 if blocked else 2.0,
            },
            "new_roadmap_item_candidates": [
                {
                    "issue_code": "MODEL_TOP_WARM_SIDE_MISS",
                    "count": 2,
                    "classification": "post_closure_recurrence",
                    "detail": "issue date is after completed owner",
                    "suggested_title": "Post-Closure Model Warm-Side Miss Recurrence",
                }
            ] if blocked else [],
        }),
        encoding="utf-8",
    )
    (root / "taker_finalization_watchdog.json").write_text(
        json.dumps({
            "schema_version": "taker_settlement_finalization_watchdog_v0.1",
            "generated_at_utc": "2026-06-21T23:58:30+00:00",
            "status": "OK",
            "summary": {
                "run_count": 1,
                "pending_finalization_count": 0,
                "sla_breach_count": 0,
                "champion_decision": "KEEP_CHAMPION",
            },
        }),
        encoding="utf-8",
    )
    (root / "taker_tail_casebook.json").write_text(
        json.dumps({
            "schema_version": "taker_tail_casebook_v0.1",
            "generated_at_utc": "2026-06-21T23:58:40+00:00",
            "summary": {
                "status": "PASS",
                "tail_fill_count": 0,
                "losing_tail_fill_count": 0,
                "no_go_candidate_count": 0,
            },
            "no_go_candidates": [],
        }),
        encoding="utf-8",
    )
    (root / "trading_evidence.json").write_text(
        json.dumps({
            "schema_version": "trading_evidence_summary_v0.1",
            "generated_at_utc": "2026-06-21T23:58:50+00:00",
            "status": "WARN" if blocked else "OK",
            "market_making": {
                "exists": True,
                "evidence_mode": "paper-live-forward",
                "counts_toward_live_forward_gate": not blocked,
                "evidence_starvation_status": "PASS",
            },
            "taker": {
                "exists": True,
                "net_pnl_usdc": -4.5 if blocked else 2.0,
                "pnl_evidence_status": "PROVISIONAL_MTM_ONLY" if blocked else "SETTLEMENT_SCORED",
                "quality_gate": {"status": "SAMPLE_PENDING_NEGATIVE_LATEST" if blocked else "PASS"},
            },
        }),
        encoding="utf-8",
    )


class TestDailyFlowAnalysis(unittest.TestCase):
    def test_build_flow_analysis_prioritizes_blockers_and_root_cause_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_flow_artifacts(backtest_root, blocked=True)

            payload = build_flow_analysis(
                backtest_root=backtest_root,
                generated_at_utc="2026-06-22T04:00:00+00:00",
            )
            json_out, report_out, actions_out = write_outputs(
                payload,
                json_out=backtest_root / "daily_flow_analysis.json",
                report_out=backtest_root / "daily_flow_analysis_report.md",
                actions_out=backtest_root / "daily_flow_analysis_actions.csv",
            )
            areas = {row["area"] for row in payload["actions"]}
            report = Path(report_out).read_text(encoding="utf-8")
            json_exists = Path(json_out).exists()
            actions_exists = Path(actions_out).exists()

        self.assertEqual(payload["schema_version"], "daily_flow_analysis_v0.1")
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["summary"]["p0_count"], 1)
        self.assertIn("operational_slo", areas)
        self.assertIn("broad_claim_gate", areas)
        self.assertIn("root_cause_recurrence", areas)
        self.assertIn("settled_day_root_cause", areas)
        self.assertFalse(payload["decision_record"]["training_ready"])
        self.assertIn("fleet_observability", payload["decision_record"]["next_command"])
        self.assertTrue(json_exists)
        self.assertTrue(actions_exists)
        self.assertIn("Daily Flow Analysis", report)
        self.assertIn("Daily Learning Input Gate", report)
        self.assertIn("Post-Closure Model Warm-Side Miss Recurrence", report)

    def test_build_flow_analysis_uses_latest_date_stamped_root_cause_when_canonical_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_flow_artifacts(backtest_root, blocked=False)
            (backtest_root / "settled_day_root_cause.json").unlink()
            (backtest_root / "settled_day_root_cause_2026-06-21.json").write_text(
                json.dumps(
                    {
                        "schema_version": "settled_day_root_cause_v0.1",
                        "generated_at_utc": "2026-06-22T00:00:00+00:00",
                        "target_date": "2026-06-21",
                        "status": "ACTIONABLE",
                        "summary": {"issue_count": 1, "issue_counts": {"MODEL_TOP_WARM_SIDE_MISS": 1}},
                        "new_roadmap_item_candidates": [
                            {
                                "issue_code": "MODEL_TOP_WARM_SIDE_MISS",
                                "count": 1,
                                "suggested_title": "Post-Closure Model Warm-Side Miss Recurrence",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_flow_analysis(backtest_root=backtest_root)

        artifact = payload["input_artifacts"]["settled_day_root_cause"]
        self.assertTrue(artifact["exists"])
        self.assertTrue(artifact["path"].endswith("settled_day_root_cause_2026-06-21.json"))
        self.assertIn("root_cause_recurrence", {row["area"] for row in payload["actions"]})

    def test_build_flow_analysis_is_ok_when_only_low_priority_learning_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_flow_artifacts(backtest_root, blocked=False)

            payload = build_flow_analysis(backtest_root=backtest_root)
            report = render_report(payload)

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["action_count"], 0)
        self.assertTrue(payload["decision_record"]["training_ready"])
        self.assertIn("No blocking or high-priority daily-flow actions", report)

    def test_build_flow_analysis_surfaces_current_run_step_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_flow_artifacts(backtest_root, blocked=False)

            payload = build_flow_analysis(
                backtest_root=backtest_root,
                daily_refresh_steps=[
                    {
                        "name": "promotion_refresh",
                        "status": "error",
                        "duration_seconds": 0.1,
                        "error": "disk headroom",
                        "result": {"resume_command": "python -m weather.operations.daily_refresh run --resume-from-step promotion_refresh"},
                    }
                ],
            )
            action = payload["actions"][0]

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(action["area"], "refresh_error")
        self.assertIn("promotion_refresh", action["action"])

    def test_build_flow_analysis_blocks_taker_finalization_and_tail_no_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_flow_artifacts(backtest_root, blocked=False)
            (backtest_root / "taker_finalization_watchdog.json").write_text(
                json.dumps({
                    "schema_version": "taker_settlement_finalization_watchdog_v0.1",
                    "status": "BREACH",
                    "summary": {
                        "run_count": 2,
                        "pending_finalization_count": 1,
                        "sla_breach_count": 1,
                    },
                }),
                encoding="utf-8",
            )
            (backtest_root / "taker_tail_casebook.json").write_text(
                json.dumps({
                    "schema_version": "taker_tail_casebook_v0.1",
                    "summary": {
                        "status": "BLOCK_BAD_TAIL_SLICES",
                        "tail_fill_count": 3,
                        "losing_tail_fill_count": 2,
                        "no_go_candidate_count": 1,
                    },
                    "no_go_candidates": [
                        {"slice_key": "low_price_tail|atlanta|hour:16", "loss_count": 2}
                    ],
                }),
                encoding="utf-8",
            )

            payload = build_flow_analysis(backtest_root=backtest_root)
            areas = {row["area"] for row in payload["actions"]}
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("taker_settlement_finalization", areas)
        self.assertIn("taker_tail_no_go", areas)
        self.assertIn("Taker And Trading", report)
        self.assertIn("BLOCK_BAD_TAIL_SLICES", report)


if __name__ == "__main__":
    unittest.main()
