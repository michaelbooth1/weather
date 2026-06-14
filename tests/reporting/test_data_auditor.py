import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from data_auditor import audit_historical_data, audit_summary


class TestDataAuditor(unittest.TestCase):
    """Wire the data auditor into the suite as a data-quality regression guard.

    Known gaps (a few missing/sparse target-window days) are tolerated, but
    duplicate timestamps and physically-impossible values indicate real
    corruption and must stay at zero.
    """

    def test_no_corruption_in_target_window(self):
        result = audit_historical_data(target_month=5, target_day=27)
        self.assertIsNotNone(result, "daily_summary.csv should exist in the repo")
        self.assertEqual(result["duplicate_timestamps"], [])
        self.assertEqual(result["impossible_values"], [])
        self.assertGreater(result["hourly_days_audited"], 0)

    def test_fahrenheit_market_uses_native_temperature_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily").mkdir(parents=True)
            (root / "hourly" / "year=2026" / "month=06").mkdir(parents=True)
            (root / "daily" / "daily_summary.csv").write_text(
                "\n".join([
                    "schema_version,local_date,temperature_unit,row_count,max_temp_native,max_temp_c,max_temp_bucket_native",
                    "wu_daily_native_v2,2026-06-07,F,18,88,31.1111,88",
                ]) + "\n",
                encoding="utf-8",
            )
            hourly_rows = [
                {
                    "local_date": "2026-06-07",
                    "local_time": f"{hour:02d}:00",
                    "temperature_unit": "F",
                    "temp_native": 70 + hour,
                    "humidity": 55,
                    "pressure_hpa": 1012,
                    "wind_speed_kmh": 12,
                }
                for hour in range(18)
            ]
            (root / "hourly" / "year=2026" / "month=06" / "observations.jsonl").write_text(
                "\n".join(__import__("json").dumps(row) for row in hourly_rows) + "\n",
                encoding="utf-8",
            )

            result = audit_historical_data(
                data_root=root,
                market_id="nyc",
                target_month=6,
                target_day=7,
                years=[2026],
                quiet=True,
            )

        self.assertEqual(result["impossible_values"], [])
        self.assertEqual(result["duplicate_timestamps"], [])
        self.assertEqual(result["hourly_days_audited"], 1)

    def test_fleet_audit_summary_tracks_corruption_markets(self):
        summary = audit_summary({
            "nyc": {
                "missing_days": [],
                "sparse_days": [],
                "duplicate_timestamps": [],
                "impossible_values": [],
            },
            "miami": {
                "missing_days": [],
                "sparse_days": [],
                "duplicate_timestamps": [],
                "impossible_values": ["KMIA 2005-06-11: Temp 171 F is impossible"],
            },
        })

        self.assertEqual(summary["market_count"], 2)
        self.assertEqual(summary["markets_with_impossible_values"], 1)
        self.assertEqual(summary["corruption_markets"], ["miami"])


if __name__ == "__main__":
    unittest.main()
