import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from backtest import (
    resolve_outcome,
    brier,
    binary_log_loss,
    score_rows,
    trade_pnl,
    pnl_trades,
    settlement_for_tape,
    backtest_tape,
    daily_first_score,
    fixed_cutoff_rows,
    last_pre_close_rows,
    run_backtest,
)
from feature_store import FEATURE_AUDIT_COLUMNS, FEATURE_SCHEMA_VERSION


class TestOutcomeResolution(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(resolve_outcome("eq", 25, 25), 1)
        self.assertEqual(resolve_outcome("eq", 25, 24), 0)

    def test_lte_or_below(self):
        self.assertEqual(resolve_outcome("lte", 19, 18), 1)
        self.assertEqual(resolve_outcome("lte", 19, 19), 1)
        self.assertEqual(resolve_outcome("lte", 19, 20), 0)

    def test_gte_or_higher(self):
        self.assertEqual(resolve_outcome("gte", 29, 30), 1)
        self.assertEqual(resolve_outcome("gte", 29, 29), 1)
        self.assertEqual(resolve_outcome("gte", 29, 28), 0)

    def test_unknown_settlement(self):
        self.assertIsNone(resolve_outcome("eq", 25, None))


class TestScoring(unittest.TestCase):
    def test_brier(self):
        self.assertAlmostEqual(brier(1.0, 1), 0.0)
        self.assertAlmostEqual(brier(0.0, 1), 1.0)
        self.assertAlmostEqual(brier(0.7, 1), 0.09)

    def test_log_loss_perfect_and_wrong(self):
        self.assertLess(binary_log_loss(0.99, 1), 0.02)
        self.assertGreater(binary_log_loss(0.01, 1), 4.0)

    def test_score_rows_skill(self):
        # Model nails it (p=1 when yes, 0 when no); market is a coin flip.
        rows = [
            {"model_probability": 1.0, "market_yes": 0.5, "outcome": 1},
            {"model_probability": 0.0, "market_yes": 0.5, "outcome": 0},
        ]
        s = score_rows(rows)
        self.assertAlmostEqual(s["model_brier"], 0.0)
        self.assertAlmostEqual(s["market_brier"], 0.25)
        self.assertEqual(s["brier_skill_score"], 1.0)  # model perfectly beats market


class TestPnl(unittest.TestCase):
    def test_buy_yes_win(self):
        # edge +0.3 -> buy YES at 0.4, outcome 1 -> pnl = 1 - 0.4
        self.assertAlmostEqual(trade_pnl(0.7, 0.4, 0.6, 1, 0.05), 0.6)

    def test_buy_yes_loss(self):
        self.assertAlmostEqual(trade_pnl(0.7, 0.4, 0.6, 0, 0.05), -0.4)

    def test_buy_no_win(self):
        # edge -0.3 -> buy NO at market_no=0.4, outcome 0 -> pnl = 1 - 0.4
        self.assertAlmostEqual(trade_pnl(0.3, 0.6, 0.4, 0, 0.05), 0.6)

    def test_no_trade_below_threshold(self):
        self.assertIsNone(trade_pnl(0.52, 0.50, 0.50, 1, 0.05))

    def test_market_no_fallback(self):
        # market_no missing -> uses 1 - market_yes
        self.assertAlmostEqual(trade_pnl(0.3, 0.6, None, 0, 0.05), (1 - 0) - (1 - 0.6))

    def test_pnl_trades_aggregate(self):
        agg = pnl_trades([0.6, -0.4, 0.6])
        self.assertEqual(agg["n"], 3)
        self.assertAlmostEqual(agg["pnl"], 0.8)
        self.assertAlmostEqual(agg["hit_rate"], 2 / 3)


def _tape(rows):
    return pd.DataFrame(rows)


class TestSettlementAndTape(unittest.TestCase):
    def test_settlement_prefers_override(self):
        df = _tape([{"wu_history_high_c": 25.0}])
        from datetime import date
        bucket, source, _ = settlement_for_tape(df, date(2026, 5, 27), {}, {"2026-05-27": 22})
        self.assertEqual((bucket, source), (22, "override"))

    def test_settlement_uses_snapshot_high_when_summary_incomplete(self):
        from datetime import date
        df = _tape([{"wu_history_high_c": 24.6}, {"wu_history_high_c": 25.0}])
        daily = {"2026-05-27": (22, 12)}  # only 12 rows -> incomplete
        bucket, source, note = settlement_for_tape(df, date(2026, 5, 27), daily, {})
        self.assertEqual(bucket, 25)  # half-up of 25.0
        self.assertEqual(source, "snapshot_high")
        self.assertIn("disagree", note)

    def test_settlement_trusts_complete_summary(self):
        from datetime import date
        df = _tape([{"wu_history_high_c": 25.0}])
        daily = {"2026-05-27": (25, 30)}
        bucket, source, _ = settlement_for_tape(df, date(2026, 5, 27), daily, {})
        self.assertEqual((bucket, source), (25, "daily_summary"))

    def test_backtest_tape_scores_and_trades(self):
        # Two snapshots, two bands; settlement = 25.
        df = _tape([
            {"snapshot_id": "s1", "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
             "model_probability": 0.8, "market_yes": 0.4, "market_no": 0.6},
            {"snapshot_id": "s1", "range_label": "26 C", "bin_kind": "eq", "bin_value_c": 26,
             "model_probability": 0.1, "market_yes": 0.5, "market_no": 0.5},
            {"snapshot_id": "s2", "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
             "model_probability": 0.9, "market_yes": 0.5, "market_no": 0.5},
            {"snapshot_id": "s2", "range_label": "26 C", "bin_kind": "eq", "bin_value_c": 26,
             "model_probability": 0.05, "market_yes": 0.45, "market_no": 0.55},
        ])
        rows, per_snap, first_entry, persistence = backtest_tape(df, 25, [0.10])
        self.assertEqual(len(rows), 4)
        # 25 C settled YES, 26 C settled NO.
        self.assertEqual({r["band"]: r["outcome"] for r in rows if r["snapshot_id"] == "s1"},
                         {"25 C": 1, "26 C": 0})
        # First-entry takes one trade per band (2 bands).
        self.assertEqual(first_entry[0.10]["n"], 2)
        # Both edges point the right way (buy YES 25, buy NO 26) and both win -> positive P&L.
        self.assertGreater(first_entry[0.10]["pnl"], 0)

    def test_backtest_tape_adds_cutoff_hour_and_bin_type(self):
        from datetime import date
        df = _tape([
            {"snapshot_id": "s1", "captured_at_local": "2026-05-27T12:14:00-04:00",
             "range_label": "25 C or higher", "bin_kind": "gte", "bin_value_c": 25,
             "model_probability": 0.8, "market_yes": 0.4, "market_no": 0.6},
        ])
        rows, _, _, _ = backtest_tape(df, 25, [0.10], target_date=date(2026, 5, 27))
        self.assertEqual(rows[0]["target_date"], "2026-05-27")
        self.assertEqual(rows[0]["cutoff_hour"], 12)
        self.assertEqual(rows[0]["capture_minute"], 12 * 60 + 14)
        self.assertEqual(rows[0]["bin_type"], "gte")

    def test_last_pre_close_rows_selects_last_day_band_snapshot(self):
        rows = [
            {"target_date": "2026-05-27", "band": "25 C", "snapshot_id": "early",
             "captured_at_local": "2026-05-27T12:00:00-04:00"},
            {"target_date": "2026-05-27", "band": "25 C", "snapshot_id": "late",
             "captured_at_local": "2026-05-27T18:00:00-04:00"},
            {"target_date": "2026-05-27", "band": "26 C", "snapshot_id": "other",
             "captured_at_local": "2026-05-27T13:00:00-04:00"},
        ]
        selected = last_pre_close_rows(rows)
        self.assertEqual({row["snapshot_id"] for row in selected}, {"late", "other"})

    def test_fixed_cutoff_rows_selects_first_at_or_after_cutoff(self):
        rows = [
            {"target_date": "2026-05-27", "band": "25 C", "snapshot_id": "s09",
             "captured_at_local": "2026-05-27T09:10:00-04:00", "capture_minute": 9 * 60 + 10},
            {"target_date": "2026-05-27", "band": "25 C", "snapshot_id": "s12",
             "captured_at_local": "2026-05-27T12:10:00-04:00", "capture_minute": 12 * 60 + 10},
            {"target_date": "2026-05-27", "band": "25 C", "snapshot_id": "s15",
             "captured_at_local": "2026-05-27T15:10:00-04:00", "capture_minute": 15 * 60 + 10},
        ]
        selected = fixed_cutoff_rows(rows, fixed_cutoffs=[10, 15])
        self.assertEqual([row["snapshot_id"] for row in selected[10]], ["s12"])
        self.assertEqual([row["snapshot_id"] for row in selected[15]], ["s15"])

    def test_daily_first_score_equal_weights_market_days(self):
        day_a = score_rows([
            {"model_probability": 1.0, "market_yes": 0.5, "outcome": 1},
            {"model_probability": 1.0, "market_yes": 0.5, "outcome": 1},
        ])
        day_b = score_rows([
            {"model_probability": 0.0, "market_yes": 0.5, "outcome": 1},
        ])
        score = daily_first_score([
            {"score": day_a},
            {"score": day_b},
        ])
        # Equal-day average: day A model brier 0, day B model brier 1 => 0.5.
        self.assertAlmostEqual(score["model_brier"], 0.5)
        self.assertEqual(score["n_days"], 2)

    def test_run_backtest_writes_v2_report_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            tape = folder / "snapshots_long.csv"
            pd.DataFrame([
                {"snapshot_id": "s1", "captured_at_local": "2026-05-27T12:00:00-04:00",
                 "event_slug": folder.name, "model_version": "test-model",
                 "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
                 "model_probability": 0.8, "market_yes": 0.4, "market_no": 0.6,
                 "wu_history_high_c": 25.0},
                {"snapshot_id": "s2", "captured_at_local": "2026-05-27T18:00:00-04:00",
                 "event_slug": folder.name, "model_version": "test-model",
                 "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
                 "model_probability": 0.9, "market_yes": 0.5, "market_no": 0.5,
                 "wu_history_high_c": 25.0},
            ]).to_csv(tape, index=False)
            out = root / "report.md"
            results = run_backtest([str(folder)], root / "missing_daily.csv", {}, [0.10], out, fixed_cutoffs=[12, 18])
            text = out.read_text(encoding="utf-8")
            self.assertIn("## Model Card", text)
            self.assertIn("## Run Inputs And Settlement", text)
            self.assertIn("## Fixed-Cutoff Performance", text)
            self.assertIn("## Reliability By Market Band", text)
            self.assertEqual(results["model_versions"], ["test-model"])
            self.assertIsNotNone(results["daily_first_score"])

    def test_run_backtest_can_filter_by_label_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folders = []
            for day, grade in [("27", "complete"), ("28", "partial")]:
                folder = root / f"highest-temperature-in-toronto-on-may-{day}-2026"
                folder.mkdir()
                folders.append(folder)
                pd.DataFrame([
                    {"snapshot_id": "s1", "captured_at_local": f"2026-05-{day}T12:00:00-04:00",
                     "event_slug": folder.name, "model_version": "test-model",
                     "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
                     "model_probability": 0.8, "market_yes": 0.4, "market_no": 0.6,
                     "wu_history_high_c": 25.0},
                ]).to_csv(folder / "snapshots_long.csv", index=False)
                (folder / "settlement.json").write_text(
                    json.dumps({"quality_grade": grade}),
                    encoding="utf-8",
                )
            out = root / "report.md"

            results = run_backtest(
                [str(folder) for folder in folders],
                root / "missing_daily.csv",
                {},
                [0.10],
                out,
                quality_grades=["complete"],
            )

            self.assertEqual([day["date"] for day in results["days"]], ["2026-05-27"])
            self.assertEqual(results["quality_filter"], ["complete"])
            self.assertIn("Quality filter: complete", out.read_text(encoding="utf-8"))

    def test_run_backtest_joins_snapshot_feature_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            pd.DataFrame([
                {"snapshot_id": "s1", "captured_at_local": "2026-05-27T12:00:00-04:00",
                 "event_slug": folder.name, "model_version": "test-model",
                 "range_label": "25 C", "bin_kind": "eq", "bin_value_c": 25,
                 "model_probability": 0.8, "market_yes": 0.4, "market_no": 0.6,
                 "wu_history_high_c": 25.0},
            ]).to_csv(folder / "snapshots_long.csv", index=False)
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-05-27T16:00:00+00:00",
                    "captured_at_local": "2026-05-27T12:00:00-04:00",
                    "event_slug": folder.name,
                    "target_date": "2026-05-27",
                    "model_version": "test-model",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "cutoff_hour": 12,
                    "forecast_gap": 3.0,
                    "high_so_far": 22.0,
                }
            ], columns=FEATURE_AUDIT_COLUMNS).to_csv(folder / "features_long.csv", index=False)
            out = root / "report.md"

            results = run_backtest([str(folder)], root / "missing_daily.csv", {}, [0.10], out)

            self.assertEqual(results["feature_vector_coverage"]["rows_with_features"], 1)
            self.assertEqual(results["all_rows"][0]["feature_forecast_gap_bucket"], ">2C")
            self.assertIn("## Feature Vector Coverage", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
