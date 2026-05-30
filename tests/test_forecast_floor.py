import os
import sys
import unittest

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestForecastFloorTimeWeight(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_strong_morning_zero_late(self):
        self.assertEqual(self.m.forecast_floor_time_weight(9), 1.0)
        self.assertEqual(self.m.forecast_floor_time_weight(12), 1.0)
        self.assertAlmostEqual(self.m.forecast_floor_time_weight(13), 0.8)
        self.assertAlmostEqual(self.m.forecast_floor_time_weight(15), 0.4)
        self.assertEqual(self.m.forecast_floor_time_weight(17), 0.0)
        self.assertEqual(self.m.forecast_floor_time_weight(18), 0.0)


class TestForecastFloorPlan(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_agreeing_forecasts_morning(self):
        plan = self.m.forecast_floor_plan([20.0, 19.8, 22.0], hour=9, observed_bucket=13)
        self.assertIsNotNone(plan)
        threshold, strength = plan
        self.assertEqual(threshold, 19)   # round(mean 20.6)=21, minus margin 2
        self.assertGreater(strength, 0.0)

    def test_disagreeing_forecasts_no_floor(self):
        self.assertIsNone(self.m.forecast_floor_plan([18.0, 25.0], hour=9, observed_bucket=13))

    def test_single_source_no_floor(self):
        self.assertIsNone(self.m.forecast_floor_plan([20.0], hour=9, observed_bucket=13))

    def test_late_afternoon_no_floor(self):
        self.assertIsNone(self.m.forecast_floor_plan([20.0, 21.0], hour=17, observed_bucket=13))


class TestApplyForecastFloor(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()
        self.scores = {t: 1.0 for t in range(13, 23)}  # uniform 13..22

    def test_suppresses_below_threshold_but_stays_soft(self):
        out = self.m.apply_forecast_floor(
            self.scores, [20.0, 20.0, 20.0], hour=9, observed_bucket=13)  # threshold 18
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        # Monotonic suppression below the threshold.
        self.assertLess(out[15], out[16])
        self.assertLess(out[16], out[17])
        self.assertLess(out[17], out[18])
        # At/above the threshold is untouched (equal pre-norm).
        self.assertAlmostEqual(out[18], out[20])
        # Soft: never zero, even several degrees below.
        self.assertGreater(out[13], 0.0)

    def test_noop_when_forecasts_disagree(self):
        out = self.m.apply_forecast_floor(
            self.scores, [18.0, 25.0], hour=9, observed_bucket=13)
        # Plan is None -> distribution is just normalized, so it stays uniform.
        self.assertAlmostEqual(out[15], out[20])

    def test_noop_late_afternoon(self):
        out = self.m.apply_forecast_floor(
            self.scores, [20.0, 21.0], hour=17, observed_bucket=13)
        self.assertAlmostEqual(out[15], out[20])


if __name__ == "__main__":
    unittest.main()
