import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.daily_progress_ledger import (
    build_progress_row,
    write_progress_outputs,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestDailyProgressLedger(unittest.TestCase):
    def test_build_progress_row_blocks_broad_claim_until_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            write_json(
                backtest / "progress_audit.json",
                {
                    "core_model_trend_claim": {
                        "claim_allowed": False,
                        "status": "DIRECTIONAL",
                        "summary": {
                            "positive_skill_days": 1,
                            "positive_daily_first_days": 1,
                            "rolling_daily_first_brier_skill": -0.3334,
                            "promotion_grade_market_days": 48,
                            "model_minus_market_brier_slope_per_day": -0.0007,
                            "brier_skill_slope_per_day": 0.0535,
                        },
                    }
                },
            )
            write_json(
                backtest / "f_family_promotion_refresh.json",
                {
                    "candidate": {
                        "aggregate": {"delta_vs_current": -0.0014, "delta_vs_market": 0.0042},
                        "verdict": "BLOCK",
                        "cutover_decision": "DO_NOT_CUT_OVER",
                    },
                    "corpus": {"market_day_count": 51, "snapshot_count": 6989},
                },
            )
            write_json(
                backtest / "fleet_observability.json",
                {
                    "status": "CRITICAL",
                    "live_forward_slo": {
                        "status": "BLOCK",
                        "counts_toward_live_forward_gate": False,
                        "snapshot_cadence_proof": {
                            "summary": {
                                "total_gap_count": 71,
                                "max_gap_minutes": 28.4,
                                "snapshot_coverage_gap_blocked_market_count": 12,
                            }
                        },
                    },
                    "collection": {
                        "source_status_proof": {
                            "summary": {"source_status_blocked_market_count": 0}
                        }
                    },
                    "clob": {"loop": {"state": "RUNNING"}},
                    "observation_trigger": {"state": "RUNNING"},
                    "current_code_soak": {"status": "BLOCK"},
                    "tape_backup": {"status": "OK"},
                },
            )
            write_json(
                backtest / "model_variant_evidence_growth.json",
                {"evidence_sla": {"status": "BLOCK", "reasons": ["missing baseline evidence"]}},
            )
            write_json(backtest / "snapshot_evaluation.json", {"snapshot_inventory": {"snapshot_count": 100}})
            write_json(backtest / "daily_learning.json", {"status": "BLOCKED"})
            mm = root / "mm_runs" / "2026-06-19" / "mm-1"
            mm.mkdir(parents=True)
            write_json(
                mm / "run_summary.json",
                {
                    "run_id": "mm-1",
                    "target_date": "2026-06-19",
                    "evidence_mode": "operator_drill",
                    "counts_toward_live_forward_gate": False,
                    "cumulative_quote_permission_rows": 4019,
                    "cumulative_live_trade_permission_rows": 0,
                    "live_forward_gate": {"status": "BLOCK", "evidence": {}},
                },
            )
            taker = root / "taker_runs" / "2026-06-19" / "taker-1"
            taker.mkdir(parents=True)
            write_json(
                taker / "run_summary.json",
                {
                    "run_id": "taker-1",
                    "target_date": "2026-06-19",
                    "summary": {
                        "cumulative_filled_orders": 50,
                        "cumulative_net_pnl_usdc": -17.2087,
                        "root_cause_class": "policy_no_edge",
                    },
                    "pnl": {"summary": {"mark_to_market_pnl_usdc": -17.2087}},
                },
            )
            write_json(
                taker / "settled_pnl.json",
                {
                    "schema_version": "taker_settlement_finalization_v0.1",
                    "run_id": "taker-1",
                    "target_date": "2026-06-19",
                    "settled_pnl_path": str(taker / "settled_pnl.json"),
                    "settled_report_path": str(taker / "settled_report.md"),
                    "summary": {
                        "filled_order_count": 4,
                        "net_pnl_usdc": 36.687839,
                        "settlement_pnl_usdc": 36.687839,
                        "mark_to_market_pnl_usdc": 0.0,
                        "settled_order_count": 4,
                        "unsettled_order_count": 0,
                        "pnl_source": "settlement_finalization",
                    },
                    "pnl": {
                        "summary": {
                            "filled_order_count": 4,
                            "net_pnl_usdc": 36.687839,
                            "settlement_pnl_usdc": 36.687839,
                            "mark_to_market_pnl_usdc": 0.0,
                            "settled_order_count": 4,
                            "unsettled_order_count": 0,
                        }
                    },
                    "reconciliation": {
                        "status": "WARN",
                        "preferred_pnl_source": "settlement_finalization",
                        "warnings": [
                            {"code": "reported_mark_to_market_diverges_from_settlement", "detail": "diff"}
                        ],
                    },
                },
            )
            daily_refresh = {
                "status": "error",
                "generated_at_utc": "2026-06-20T01:00:00+00:00",
                "summary": {"labels": {"total": 165, "quality_counts": {"complete": 54}}},
                "steps": [
                    {
                        "name": "promotion_refresh",
                        "status": "error",
                        "root_cause_class": "blocked_by_disk",
                        "error": (
                            "insufficient disk headroom for variant export: "
                            "free_bytes=485441536, required_free_bytes=1069048320"
                        ),
                    }
                ],
            }

            row = build_progress_row(backtest_root=backtest, daily_refresh_status=daily_refresh)

        self.assertFalse(row["broad_improvement_claim_allowed"])
        failures = json.loads(row["broad_improvement_claim_failures"])
        self.assertIn("positive_skill_days_below_3", failures)
        self.assertIn("rolling_daily_first_skill_negative", failures)
        self.assertIn("promotion_grade_market_days_below_84", failures)
        self.assertIn("live_forward_slo_not_pass", failures)
        self.assertIn("independent_baseline_missing", failures)
        self.assertEqual(row["ops_disk_preflight_status"], "BLOCK")
        self.assertEqual(row["ops_disk_free_bytes"], 485441536)
        self.assertEqual(row["ops_disk_required_free_bytes"], 1069048320)
        self.assertEqual(row["ops_disk_headroom_bytes"], -583606784)
        self.assertEqual(row["trading_mm_evidence_mode"], "operator_drill")
        self.assertEqual(row["trading_taker_root_cause"], "policy_no_edge")
        self.assertAlmostEqual(row["trading_taker_net_pnl_usdc"], 36.687839)
        self.assertEqual(row["trading_taker_pnl_source"], "settlement_finalization")
        self.assertEqual(row["trading_taker_settled_orders"], 4)
        self.assertEqual(row["trading_taker_unsettled_orders"], 0)
        self.assertEqual(row["trading_taker_reconciliation_status"], "WARN")

    def test_write_progress_outputs_appends_jsonl_csv_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "schema_version": "daily_progress_ledger_v0.1",
                "generated_at_utc": "2026-06-20T01:00:00+00:00",
                "run_date": "2026-06-20",
                "broad_improvement_claim_allowed": False,
                "broad_improvement_claim_failures": json.dumps(["x"]),
                "model_rolling_daily_first_brier_skill": -0.1,
                "model_positive_skill_days": 1,
                "evidence_promotion_grade_market_days": 48,
                "ops_live_forward_slo_status": "BLOCK",
                "ops_snapshot_gap_count": 12,
                "evidence_independent_baseline_status": "MISSING",
                "trading_mm_evidence_mode": "operator_drill",
                "trading_taker_net_pnl_usdc": -1.0,
            }

            result = write_progress_outputs(
                row,
                jsonl_out=root / "ledger.jsonl",
                csv_out=root / "ledger.csv",
                latest_out=root / "latest.json",
                report_out=root / "ledger.md",
            )
            updated_row = dict(row)
            updated_row["model_positive_skill_days"] = 2
            write_progress_outputs(
                updated_row,
                jsonl_out=root / "ledger.jsonl",
                csv_out=root / "ledger.csv",
                latest_out=root / "latest.json",
                report_out=root / "ledger.md",
            )

            lines = (root / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
            csv_rows = list(csv.DictReader((root / "ledger.csv").open(encoding="utf-8")))
            report = (root / "ledger.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(csv_rows), 1)
        self.assertEqual(json.loads(lines[0])["model_positive_skill_days"], 2)
        self.assertEqual(csv_rows[0]["model_positive_skill_days"], "2")
        self.assertIn("Daily Progress Ledger", report)


if __name__ == "__main__":
    unittest.main()
