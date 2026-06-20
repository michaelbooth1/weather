import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.trading_evidence import build_trading_evidence_summary


class TestTradingEvidence(unittest.TestCase):
    def test_operator_drill_market_making_run_remains_non_countable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "mm_runs" / "2026-06-19" / "run-1"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "mm_run_v0.2",
                        "run_id": "run-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-live-forward",
                        "evidence_mode": "operator_drill",
                        "counts_toward_live_forward_gate": False,
                        "preflight_status": "PASS",
                        "markets": ["toronto", "nyc"],
                        "cumulative_quote_permission_rows": 4019,
                        "cumulative_paper_posted_count": 8026,
                        "cumulative_live_trade_permission_rows": 0,
                        "live_forward_gate": {
                            "status": "BLOCK",
                            "summary": {"evidence_mode_reason": "operator override"},
                            "evidence": {
                                "model_review_evidence": {"countable_market_count": 2},
                                "paper_trading_evidence": {"countable_market_count": 2},
                                "live_trade_permission_evidence": {"countable_market_count": 0},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
            )

        mm = summary["market_making"]
        self.assertEqual(mm["evidence_mode"], "operator_drill")
        self.assertFalse(mm["counts_toward_live_forward_gate"])
        self.assertIn("evidence_mode=operator_drill", mm["countability_blockers"])
        self.assertEqual(mm["quote_rows"], 4019)
        self.assertEqual(mm["paper_posted_lifecycle_legs"], 8026)
        self.assertEqual(mm["live_trade_permission_rows"], 0)

    def test_negative_single_taker_day_is_sample_pending_not_strategy_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-1"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_bot_run_v0.1",
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-taker",
                        "summary": {
                            "cumulative_filled_orders": 50,
                            "budget_spent_usdc": 59.80507,
                            "cumulative_net_pnl_usdc": -17.208695,
                            "root_cause_class": "policy_no_edge",
                            "first_failing_gate": "policy",
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 50,
                                "net_pnl_usdc": -17.208695,
                                "mark_to_market_pnl_usdc": -17.208695,
                                "settled_order_count": 0,
                                "unsettled_order_count": 50,
                                "reason_counts": {"BUY_EDGE": 50},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
            )

        taker = summary["taker"]
        self.assertEqual(taker["filled_orders"], 50)
        self.assertAlmostEqual(taker["net_pnl_usdc"], -17.208695)
        self.assertEqual(taker["quality_gate"]["status"], "SAMPLE_PENDING_NEGATIVE_LATEST")
        self.assertFalse(taker["quality_gate"]["sample_ready"])

    def test_taker_evidence_prefers_settled_finalization_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-1"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_bot_run_v0.1",
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-taker",
                        "summary": {
                            "cumulative_filled_orders": 50,
                            "budget_spent_usdc": 59.80507,
                            "cumulative_net_pnl_usdc": -17.208695,
                            "root_cause_class": "policy_no_edge",
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 50,
                                "net_pnl_usdc": -17.208695,
                                "mark_to_market_pnl_usdc": -17.208695,
                                "settled_order_count": 0,
                                "unsettled_order_count": 50,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            settled_path = run / "settled_pnl.json"
            settled_path.write_text(
                json.dumps(
                    {
                        "schema_version": "taker_settlement_finalization_v0.1",
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "settled_pnl_path": str(settled_path),
                        "settled_report_path": str(run / "settled_report.md"),
                        "summary": {
                            "filled_order_count": 4,
                            "budget_spent_usdc": 59.80507,
                            "net_pnl_usdc": 36.687839,
                            "settlement_pnl_usdc": 36.687839,
                            "mark_to_market_pnl_usdc": 0.0,
                            "settled_order_count": 4,
                            "unsettled_order_count": 0,
                            "pnl_source": "settlement_finalization",
                            "reported_net_pnl_usdc": -17.208695,
                            "reported_mark_to_market_pnl_usdc": -17.208695,
                            "reported_unsettled_order_count": 50,
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 4,
                                "budget_spent_usdc": 59.80507,
                                "net_pnl_usdc": 36.687839,
                                "settlement_pnl_usdc": 36.687839,
                                "mark_to_market_pnl_usdc": 0.0,
                                "settled_order_count": 4,
                                "unsettled_order_count": 0,
                                "reason_counts": {"BUY_EDGE": 4},
                            }
                        },
                        "reconciliation": {
                            "status": "WARN",
                            "preferred_pnl_source": "settlement_finalization",
                            "warnings": [
                                {"code": "reported_mark_to_market_diverges_from_settlement", "detail": "diff"}
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
            )

        taker = summary["taker"]
        self.assertEqual(taker["filled_orders"], 4)
        self.assertAlmostEqual(taker["net_pnl_usdc"], 36.687839)
        self.assertAlmostEqual(taker["settlement_pnl_usdc"], 36.687839)
        self.assertEqual(taker["pnl_source"], "settlement_finalization")
        self.assertEqual(taker["settlement_reconciliation_status"], "WARN")
        self.assertEqual(taker["quality_gate"]["status"], "SAMPLE_PENDING")
        self.assertEqual(taker["reported_unsettled_order_count"], 50)


if __name__ == "__main__":
    unittest.main()
