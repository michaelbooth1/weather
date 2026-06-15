import os
import sys
import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from location_trust import grade_for, score_market, trust_from_components


SLUG = "highest-temperature-in-toronto-on-july-1-2026"


def write_tape(root):
    folder = Path(root) / SLUG
    folder.mkdir(parents=True)
    columns = [
        "snapshot_id",
        "captured_at_local",
        "event_slug",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "model_probability",
        "market_yes",
        "market_no",
        "wu_history_high_c",
    ]
    rows = [
        {
            "snapshot_id": "s1",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.40",
            "market_yes": "0.60",
            "market_no": "0.40",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s1",
            "captured_at_local": "2026-07-01T10:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.20",
            "market_yes": "0.30",
            "market_no": "0.70",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s2",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "25 C",
            "bin_kind": "eq",
            "bin_value_c": "25",
            "model_probability": "0.70",
            "market_yes": "0.50",
            "market_no": "0.50",
            "wu_history_high_c": "25.0",
        },
        {
            "snapshot_id": "s2",
            "captured_at_local": "2026-07-01T11:00:00-04:00",
            "event_slug": SLUG,
            "range_label": "26 C",
            "bin_kind": "eq",
            "bin_value_c": "26",
            "model_probability": "0.10",
            "market_yes": "0.20",
            "market_no": "0.80",
            "wu_history_high_c": "25.0",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (folder / "settlement.json").write_text(
        json.dumps(
            {
                "event_slug": SLUG,
                "market_id": "toronto",
                "target_date": "2026-07-01",
                "settlement_bucket": 25,
                "settlement_unit": "C",
                "quality_grade": "complete",
                "settlement_source": "test",
            }
        ),
        encoding="utf-8",
    )


class TestTrustFormula(unittest.TestCase):
    def test_unproven_when_no_settled_days(self):
        r = trust_from_components(0, None)
        self.assertEqual(r["grade"], "Unproven")
        self.assertLessEqual(r["trust_score"], 20)
        self.assertIsNone(r["calibration_subscore"])

    def test_mature_well_calibrated_scores_high(self):
        r = trust_from_components(40, 0.03)
        self.assertGreaterEqual(r["trust_score"], 80)
        self.assertEqual(r["grade"], "Strong")

    def test_poor_calibration_capped_even_with_data(self):
        # Lots of days but ECE at the poor floor -> calibration gates it low.
        r = trust_from_components(40, 0.16)
        self.assertLessEqual(r["trust_score"], 20)

    def test_more_days_raises_score(self):
        low = trust_from_components(5, 0.08)["trust_score"]
        high = trust_from_components(25, 0.08)["trust_score"]
        self.assertGreater(high, low)

    def test_better_calibration_raises_score(self):
        worse = trust_from_components(20, 0.11)["trust_score"]
        better = trust_from_components(20, 0.05)["trust_score"]
        self.assertGreater(better, worse)

    def test_grade_bands(self):
        self.assertEqual(grade_for(85), "Strong")
        self.assertEqual(grade_for(70), "Good")
        self.assertEqual(grade_for(50), "Moderate")
        self.assertEqual(grade_for(30), "Low")
        self.assertEqual(grade_for(10), "Unproven")

    def test_score_market_reports_winner_band_catchup(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tape(tmp)

            row = score_market(
                "toronto",
                root=tmp,
                daily_summary=Path(tmp) / "missing_daily.csv",
                as_of=date(2026, 7, 2),
            )

            self.assertEqual(row["settled_days"], 1)
            self.assertEqual(row["winner_rows"], 2)
            self.assertAlmostEqual(row["winner_model_probability"], 0.55)
            self.assertAlmostEqual(row["winner_market_probability"], 0.55)
            self.assertAlmostEqual(row["winner_catchup_gap"], 0.0)
            self.assertAlmostEqual(row["winner_catchup_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
