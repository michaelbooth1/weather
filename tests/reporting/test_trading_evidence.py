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

    def test_positive_mtm_taker_day_is_provisional_not_promotion_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-21" / "taker-20260621-bbe63642"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_bot_run_v0.1",
                        "run_id": "taker-20260621-bbe63642",
                        "target_date": "2026-06-21",
                        "mode": "paper-taker",
                        "summary": {
                            "cumulative_filled_orders": 50,
                            "budget_spent_usdc": 59.80507,
                            "cumulative_net_pnl_usdc": 1702.209,
                            "active_strategy_id": "low_price_tail_capped",
                            "active_strategy_lifecycle": "candidate_canary",
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 50,
                                "net_pnl_usdc": 1702.209,
                                "mark_to_market_pnl_usdc": 1702.209,
                                "settlement_pnl_usdc": 0.0,
                                "settled_order_count": 0,
                                "unsettled_order_count": 50,
                                "low_price_tail_fill_count": 31,
                                "low_price_tail_fill_fraction": 0.62,
                                "tail_fill_quality_status": "WARN_HIGH_TAIL_SHARE",
                                "tail_fill_alert_count": 2,
                                "reason_counts": {"BUY_EDGE": 50},
                            },
                            "strategy_comparison": {
                                "strategy_count": 1,
                                "best_strategy_id": "low_price_tail_capped",
                                "best_strategy_net_pnl_usdc": 1702.209,
                                "best_settlement_scored_strategy_id": None,
                                "best_settlement_scored_net_pnl_usdc": None,
                                "countable_strategy_quality_candidate_status": "MISSING_SETTLED_SAMPLE",
                                "countable_strategy_quality_candidate": {},
                                "promotion_evidence_basis": "settlement_scored",
                                "mtm_promotion_allowed": False,
                            },
                            "tail_fill_quality": {
                                "summary": {
                                    "status": "WARN_HIGH_TAIL_SHARE",
                                    "filled_order_count": 50,
                                    "low_price_tail_fill_count": 31,
                                    "low_price_tail_fill_fraction": 0.62,
                                    "max_tail_fill_fraction": 0.5,
                                    "settled_tail_fill_count": 0,
                                    "unsettled_tail_fill_count": 31,
                                    "alert_count": 2,
                                    "alerts": [
                                        {"code": "HIGH_TAIL_FILL_FRACTION", "detail": "31/50"},
                                        {"code": "TAIL_FILLS_MISSING_SETTLEMENT", "detail": "pending"},
                                    ],
                                }
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

        taker = summary["taker"]
        self.assertEqual(taker["pnl_source"], "mark_to_market")
        self.assertEqual(taker["pnl_evidence_status"], "PROVISIONAL_MTM_ONLY")
        self.assertEqual(taker["settled_order_count"], 0)
        self.assertEqual(taker["unsettled_order_count"], 50)
        self.assertEqual(taker["strategy_quality_candidate_status"], "MISSING_SETTLED_SAMPLE")
        self.assertIsNone(taker["best_settlement_scored_strategy_id"])
        self.assertFalse(taker["active_strategy_promotion_eligible"])
        self.assertFalse(taker["mtm_promotion_allowed"])
        self.assertEqual(taker["tail_fill_quality_status"], "WARN_HIGH_TAIL_SHARE")
        self.assertEqual(taker["low_price_tail_fill_count"], 31)
        self.assertAlmostEqual(taker["low_price_tail_fill_fraction"], 0.62)
        self.assertEqual(taker["tail_fill_alert_count"], 2)

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
                            },
                            "by_strategy": [
                                {
                                    "strategy_id": "raw_edge_control",
                                    "filled_order_count": 4,
                                    "settled_order_count": 4,
                                    "unsettled_order_count": 0,
                                    "net_pnl_usdc": 36.687839,
                                    "quality_candidate_countable": True,
                                }
                            ],
                            "strategy_comparison": {
                                "strategy_count": 1,
                                "best_strategy_id": "raw_edge_control",
                                "best_strategy_net_pnl_usdc": 36.687839,
                                "best_settlement_scored_strategy_id": "raw_edge_control",
                                "best_settlement_scored_net_pnl_usdc": 36.687839,
                                "countable_strategy_quality_candidate_status": "COUNTABLE_SETTLED",
                                "countable_strategy_quality_candidate": {
                                    "strategy_id": "raw_edge_control",
                                    "net_pnl_usdc": 36.687839,
                                },
                            },
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
        self.assertEqual(taker["best_strategy_id"], "raw_edge_control")
        self.assertEqual(taker["strategy_quality_candidate_id"], "raw_edge_control")
        self.assertEqual(taker["strategy_quality_candidate_status"], "COUNTABLE_SETTLED")


if __name__ == "__main__":
    unittest.main()
