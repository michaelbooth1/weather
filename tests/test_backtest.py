import os
import sys
import unittest

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
)


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


if __name__ == "__main__":
    unittest.main()
