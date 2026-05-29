import os
import sys
import unittest

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from data_auditor import audit_historical_data


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


if __name__ == "__main__":
    unittest.main()
