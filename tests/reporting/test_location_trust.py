import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from location_trust import grade_for, trust_from_components


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


if __name__ == "__main__":
    unittest.main()
