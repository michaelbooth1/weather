import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


def p_ge(dist, bucket):
    return sum(v for k, v in dist.items() if k >= bucket)


class TestForecastPullTimeWeight(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_weight_curve(self):
        self.assertEqual(self.m.forecast_pull_time_weight(10), 1.0)   # morning: full
        self.assertEqual(self.m.forecast_pull_time_weight(11), 1.0)
        self.assertEqual(self.m.forecast_pull_time_weight(16), 0.0)   # mid-afternoon: off
        self.assertEqual(self.m.forecast_pull_time_weight(20), 0.0)
        self.assertAlmostEqual(self.m.forecast_pull_time_weight(13), (16 - 13) / 5)


class TestApplyForecastPull(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()
        # An under-calling morning distribution: peak at 27-28, little above.
        self.under = {25: 0.10, 26: 0.20, 27: 0.30, 28: 0.25, 29: 0.10, 30: 0.05}

    def test_raises_tail_toward_reach_rate(self):
        out = self.m.apply_forecast_pull(
            self.under, forecasts=[29, 29, 30], hour=9,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        # P(>=29) lifted from 0.15 toward the 0.70 target, but never past it.
        self.assertGreater(p_ge(out, 29), 0.50)
        self.assertLessEqual(p_ge(out, 29), 0.70 + 1e-9)
        self.assertLess(out[27], self.under[27])  # body gave up mass

    def test_one_directional_noop_when_already_confident(self):
        confident = {28: 0.2, 29: 0.5, 30: 0.3}  # P(>=29)=0.8 > target
        out = self.m.apply_forecast_pull(
            confident, forecasts=[29, 29], hour=9,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(p_ge(out, 29), 0.8, places=6)  # unchanged

    def test_noop_when_forecasts_disagree(self):
        out = self.m.apply_forecast_pull(
            dict(self.under), forecasts=[25, 31], hour=9,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])  # proportions kept

    def test_noop_late_in_day(self):
        out = self.m.apply_forecast_pull(
            dict(self.under), forecasts=[29, 29], hour=17,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])

    def test_noop_when_high_already_reached_forecast(self):
        out = self.m.apply_forecast_pull(
            dict(self.under), forecasts=[29, 29], hour=9,
            observed_bucket=30, current_observed_bucket=30,  # already above the forecast
        )
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])

    def test_noop_single_forecast(self):
        out = self.m.apply_forecast_pull(
            dict(self.under), forecasts=[29], hour=9,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])


if __name__ == "__main__":
    unittest.main()
