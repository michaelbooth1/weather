import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.trading_evidence import build_trading_evidence_summary, write_outputs


def _write_active_mm_run(root, target_date, run_id):
    run = Path(root) / "mm_runs" / target_date / run_id
    run.mkdir(parents=True)
    (run / "run_summary.json").write_text(json.dumps({
        "schema_version": "mm_run_v0.2",
        "run_id": run_id,
        "target_date": target_date,
        "mode": "paper-live-forward",
        "evidence_mode": "active_day_live_forward",
        "counts_toward_live_forward_gate": True,
        "preflight_status": "PASS",
        "generated_at_utc": f"{target_date}T20:00:00+00:00",
    }), encoding="utf-8")
    (run / "quote_intents_long.csv").write_text(
        "run_id,target_date,run_mode,generated_at_utc,quote_permission,market_id,event_slug,range_label,"
        "bin_kind,bin_value,bin_value_hi,clob_token_id,fair_probability,market_mid,bid_price,bid_size,"
        "ask_price,ask_size,regime,source_fresh\n"
        f"{run_id},{target_date},paper-live-forward,{target_date}T16:00:00+00:00,True,atlanta,"
        f"highest-temperature-in-atlanta-on-{target_date},80-81 F,eq,80,81,token-{run_id},"
        "0.50,0.50,0.49,5,0.51,5,harvest,True\n",
        encoding="utf-8",
    )
    return run


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

    def test_stale_maker_paper_score_blocks_market_making_countability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_run = _write_active_mm_run(root, "2026-06-18", "old-active")
            _new_run = _write_active_mm_run(root, "2026-06-19", "new-active")
            report_json = root / "backtest" / "mm_paper_report.json"
            report_json.parent.mkdir(parents=True)
            report_json.write_text(json.dumps({
                "schema_version": "mm_paper_v0.1",
                "generated_at_utc": "2026-06-19T01:00:00+00:00",
                "summary": {
                    "conservative_fills": 33,
                    "gate_status": "OPEN",
                    "pnl": {"net_pnl_after_fees_incentives_usdc": 1.6556},
                    "paper_score_freshness": {
                        "covered_run_folders": [str(old_run)],
                    },
                },
                "run_configs": {str(old_run): {"run_id": "old-active"}},
            }), encoding="utf-8")

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                mm_paper_json=report_json,
            )
            json_out = root / "trading_evidence.json"
            report_out = root / "trading_evidence.md"
            write_outputs(summary, json_out=json_out, report_out=report_out)
            saved = json.loads(json_out.read_text(encoding="utf-8"))

        mm = summary["market_making"]
        self.assertEqual(mm["paper_score_freshness_status"], "STALE")
        self.assertEqual(mm["paper_score_latest_completed_active_day"], "2026-06-19")
        self.assertEqual(mm["paper_score_latest_covered_active_day"], "2026-06-18")
        self.assertEqual(mm["paper_score_conservative_fills"], 33)
        self.assertEqual(mm["countability_status"], "NON_COUNTABLE")
        self.assertIn("paper_score_freshness=STALE", mm["countability_blockers"])
        self.assertEqual(saved["status"], "BLOCK")

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

    def test_legacy_taker_profitability_artifacts_block_trading_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "legacy"
            run.mkdir(parents=True)
            (run / "orders_long.csv").write_text(
                "order_status,fee_usdc,pnl_fee_basis\n"
                "FILLED,0,paper_no_fee\n",
                encoding="utf-8",
            )
            payload = {
                "schema_version": "taker_bot_run_v0.1",
                "run_id": "legacy",
                "target_date": "2026-06-19",
                "mode": "paper-taker",
                "summary": {
                    "cumulative_filled_orders": 1,
                    "budget_spent_usdc": 1.0,
                    "cumulative_net_pnl_usdc": 0.0,
                },
                "pnl": {
                    "summary": {
                        "filled_order_count": 1,
                        "net_pnl_usdc": 0.0,
                        "mark_to_market_pnl_usdc": 0.0,
                        "settled_order_count": 0,
                        "unsettled_order_count": 1,
                    }
                },
            }
            (run / "run_summary.json").write_text(json.dumps(payload), encoding="utf-8")
            (run / "daily_pnl.json").write_text(json.dumps(payload["pnl"]), encoding="utf-8")

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
            )
            json_out = root / "trading_evidence.json"
            report_out = root / "trading_evidence.md"
            write_outputs(summary, json_out=json_out, report_out=report_out)
            saved = json.loads(json_out.read_text(encoding="utf-8"))
            report = report_out.read_text(encoding="utf-8")

        taker = summary["taker"]
        self.assertEqual(taker["profitability_artifact_verification_status"], "BLOCK")
        self.assertGreater(taker["profitability_artifact_failed_check_count"], 0)
        self.assertEqual(saved["status"], "BLOCK")
        self.assertIn("Profitability artifact verification", report)
        self.assertIn("BLOCK", report)

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

    def test_positive_mtm_rolling_sample_cannot_pass_quality_without_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for offset, day in enumerate(["2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20", "2026-06-21"]):
                run = root / "taker_runs" / day / f"taker-{offset}"
                run.mkdir(parents=True)
                (run / "run_summary.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "taker_bot_run_v0.1",
                            "run_id": f"taker-{offset}",
                            "target_date": day,
                            "mode": "paper-taker",
                            "summary": {
                                "cumulative_filled_orders": 50,
                                "budget_spent_usdc": 60.0,
                                "cumulative_net_pnl_usdc": 1000.0 + offset,
                            },
                            "pnl": {
                                "summary": {
                                    "filled_order_count": 50,
                                    "net_pnl_usdc": 1000.0 + offset,
                                    "mark_to_market_pnl_usdc": 1000.0 + offset,
                                    "settlement_pnl_usdc": 0.0,
                                    "settled_order_count": 0,
                                    "unsettled_order_count": 50,
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

        quality = summary["taker"]["quality_gate"]
        self.assertEqual(summary["taker"]["pnl_evidence_status"], "PROVISIONAL_MTM_ONLY")
        self.assertNotEqual(quality["status"], "PASS")
        self.assertFalse(quality["sample_ready"])
        self.assertEqual(quality["evidence_basis"], "settlement_scored")
        self.assertEqual(quality["rolling_run_count"], 0)
        self.assertEqual(quality["rolling_filled_orders"], 0)
        self.assertEqual(quality["rolling_net_pnl_usdc"], 0)
        self.assertEqual(quality["rolling_total_run_count"], 5)
        self.assertEqual(quality["rolling_total_filled_orders"], 250)
        self.assertAlmostEqual(quality["rolling_reported_net_pnl_usdc"], 5010.0)
        self.assertEqual(quality["rolling_provisional_mtm_run_count"], 5)
        self.assertIn("MTM-only", quality["interpretation"])

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

    def test_uncertain_settlement_audit_blocks_settled_taker_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-1"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(json.dumps({
                "schema_version": "taker_bot_run_v0.1",
                "run_id": "taker-1",
                "target_date": "2026-06-19",
                "mode": "paper-taker",
                "summary": {"cumulative_filled_orders": 1, "cumulative_net_pnl_usdc": 1.0},
                "pnl": {"summary": {"filled_order_count": 1, "settled_order_count": 0}},
            }), encoding="utf-8")
            (run / "settled_pnl.json").write_text(json.dumps({
                "schema_version": "taker_settlement_finalization_v0.1",
                "run_id": "taker-1",
                "target_date": "2026-06-19",
                "summary": {
                    "filled_order_count": 1,
                    "settled_order_count": 1,
                    "unsettled_order_count": 0,
                    "net_pnl_usdc": 1.0,
                    "pnl_source": "settlement_finalization",
                },
                "pnl": {
                    "summary": {
                        "filled_order_count": 1,
                        "settled_order_count": 1,
                        "unsettled_order_count": 0,
                        "net_pnl_usdc": 1.0,
                    }
                },
            }), encoding="utf-8")
            audit_json = root / "settlement_source_revision_audit.json"
            audit_json.write_text(json.dumps({
                "schema_version": "settlement_source_revision_audit_v0.1",
                "status": "BLOCK",
                "rows": [
                    {
                        "target_date": "2026-06-19",
                        "market_id": "atlanta",
                        "status": "PROVISIONAL",
                        "promotion_blocker": True,
                    }
                ],
            }), encoding="utf-8")

            summary = build_trading_evidence_summary(
                mm_runs_root=root / "mm_runs",
                taker_runs_root=root / "taker_runs",
                settlement_audit_json=audit_json,
            )
            json_out = root / "trading_evidence.json"
            report_out = root / "trading_evidence.md"
            write_outputs(summary, json_out=json_out, report_out=report_out)
            saved = json.loads(json_out.read_text(encoding="utf-8"))
            report = report_out.read_text(encoding="utf-8")

        taker = summary["taker"]
        self.assertEqual(taker["settlement_source_audit_status"], "BLOCK")
        self.assertIn("2026-06-19:atlanta:PROVISIONAL", taker["settlement_source_audit_blockers"])
        self.assertEqual(saved["status"], "BLOCK")
        self.assertIn("Settlement source audit", report)


if __name__ == "__main__":
    unittest.main()
