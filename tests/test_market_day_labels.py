import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath("src"))

from market_day_labels import finalize_folders, missing_fraction, quality_grade


class TestMarketDayLabels(unittest.TestCase):
    def test_quality_grade(self):
        self.assertEqual(quality_grade(0, 0, None, "none"), "missing_settlement")
        self.assertEqual(quality_grade(0, 0, 25, "daily_summary"), "missing_tape")
        self.assertEqual(quality_grade(8, 10, 25, "override"), "manual_override")
        self.assertEqual(quality_grade(3, 10, 25, "daily_summary"), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary(sparse)"), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary", collection_clean=False), "partial")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary", 0.25), "stale_source")
        self.assertEqual(quality_grade(8, 10, 25, "daily_summary"), "complete")

    def test_missing_fraction_flags_missing_core_columns(self):
        frame = pd.DataFrame([{"model_probability": 0.5}, {"model_probability": None}])

        self.assertEqual(missing_fraction(frame, ["market_yes"]), 1.0)
        self.assertAlmostEqual(missing_fraction(frame, ["model_probability"]), 0.5)

    def test_finalize_writes_folder_json_and_labels_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-may-27-2026"
            folder.mkdir()
            start = datetime(2026, 5, 27, 11, 0)
            pd.DataFrame([
                {
                    "snapshot_id": f"s{i}",
                    "captured_at_local": (start + timedelta(minutes=10 * i)).isoformat(),
                    "range_label": "25 C",
                    "bin_kind": "eq",
                    "bin_value_c": 25,
                    "model_probability": 0.8,
                    "market_yes": 0.4,
                    "wu_history_high_c": 25.0,
                }
                for i in range(43)
            ]).to_csv(folder / "snapshots_long.csv", index=False)
            daily = root / "daily.csv"
            daily.write_text(
                "local_date,row_count,max_temp_bucket_c\n2026-05-27,24,25\n",
                encoding="utf-8",
            )
            labels_csv = root / "labels.csv"

            labels = finalize_folders([folder], daily_summary_path=daily, labels_csv=labels_csv)
            folder_label = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
            csv_rows = list(csv.DictReader(labels_csv.open(encoding="utf-8", newline="")))

            self.assertEqual(labels[0]["quality_grade"], "complete")
            self.assertTrue(labels[0]["coverage_clean"])
            self.assertIn("quality_reason", folder_label)
            self.assertEqual(folder_label["settlement_bucket"], 25)
            self.assertEqual(csv_rows[0]["event_slug"], folder.name)
            self.assertIn("quality_reason", csv_rows[0])
            self.assertIn("coverage_reason", csv_rows[0])


if __name__ == "__main__":
    unittest.main()
