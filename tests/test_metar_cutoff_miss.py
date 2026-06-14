"""Item 5: quantify how often METAR-so-far misses the WU final settlement
bucket by intraday cutoff hour.

Synthetic hourly partitions + a passed-in WU truth dict (no network), so the
miss / match / exceed classification by cutoff hour is deterministic.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

import metar_history
from metar_history import MetarStore, cutoff_miss_analysis, read_hourly_by_date
from market_registry import spec_for_id


def _write_hourly(store, rows_by_date):
    """rows_by_date: {local_date: [(local_time, temp_native), ...]}."""
    by_month = {}
    for local_date, rows in rows_by_date.items():
        year, month, _day = local_date.split("-")
        by_month.setdefault((year, month), []).extend(
            {"local_date": local_date, "local_time": t, "temp_native": v}
            for t, v in rows
        )
    for (year, month), records in by_month.items():
        path = store.hourly_root / f"year={year}" / f"month={month}" / "observations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )


class TestCutoffMiss(unittest.TestCase):
    def setUp(self):
        self.spec = spec_for_id("toronto")
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MetarStore(self.spec, root=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_hourly_by_date_sorted_and_clean(self):
        _write_hourly(self.store, {"2025-05-20": [("15:00", 25.0), ("09:00", 20.0)]})
        # A malformed row must be skipped, not crash.
        bad = self.store.hourly_root / "year=2025" / "month=05" / "observations.jsonl"
        bad.write_text(bad.read_text(encoding="utf-8") + json.dumps(
            {"local_date": "2025-05-20", "local_time": "bad", "temp_native": 30}
        ) + "\n", encoding="utf-8")
        by_date = read_hourly_by_date(self.store)
        self.assertEqual(by_date["2025-05-20"], [(540, 20.0), (900, 25.0)])

    def test_miss_match_exceed_by_cutoff(self):
        _write_hourly(self.store, {
            # Day warms 20 -> 24 -> 25, settles at 25.
            "2025-05-20": [("09:00", 20.0), ("12:00", 24.0), ("15:00", 25.0)],
            # Day overshoots: 23 by 15:00, settles at 22.
            "2025-05-21": [("09:00", 20.0), ("15:00", 23.0)],
        })
        wu_rows = {
            "2025-05-20": {"high": 25.0, "bucket": 25},
            "2025-05-21": {"high": 22.0, "bucket": 22},
        }
        result = cutoff_miss_analysis(self.spec, self.store, wu_rows, cutoff_hours=(9, 12, 15))
        self.assertEqual(result["matched_days"], 2)

        c9 = result["per_cutoff"][9]
        # At 09:00 both days are below their final bucket -> all miss.
        self.assertEqual(c9["n"], 2)
        self.assertAlmostEqual(c9["miss_rate"], 1.0)
        self.assertAlmostEqual(c9["reached_rate"], 0.0)

        c15 = result["per_cutoff"][15]
        # At 15:00 day-20 matches (25==25), day-21 exceeds (23>22).
        self.assertAlmostEqual(c15["match_rate"], 0.5)
        self.assertAlmostEqual(c15["exceed_rate"], 0.5)
        self.assertAlmostEqual(c15["miss_rate"], 0.0)
        self.assertAlmostEqual(c15["reached_rate"], 1.0)
        # First hour where reached_rate >= 0.5 is 15 here (9 and 12 are below).
        self.assertEqual(result["reaches_final_by_hour"], 15)

    def test_mean_gap_to_final(self):
        _write_hourly(self.store, {"2025-05-20": [("12:00", 22.0)]})
        wu_rows = {"2025-05-20": {"high": 25.0, "bucket": 25}}
        result = cutoff_miss_analysis(self.spec, self.store, wu_rows, cutoff_hours=(12,))
        # final 25 - metar-so-far bucket 22 = 3.
        self.assertAlmostEqual(result["per_cutoff"][12]["mean_gap_to_final"], 3.0)

    def test_days_without_wu_truth_are_skipped(self):
        _write_hourly(self.store, {
            "2025-05-20": [("12:00", 22.0)],
            "2025-05-21": [("12:00", 22.0)],
        })
        wu_rows = {"2025-05-20": {"high": 25.0, "bucket": 25}}  # only one has truth
        result = cutoff_miss_analysis(self.spec, self.store, wu_rows, cutoff_hours=(12,))
        self.assertEqual(result["matched_days"], 1)


if __name__ == "__main__":
    unittest.main()
