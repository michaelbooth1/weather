import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel
from model_distribution import (
    FORECAST_PULL_END_HOUR,
    FORECAST_PULL_START_HOUR,
    FORECAST_PULL_TARGET_REACH,
)


def p_ge(dist, bucket):
    return sum(v for k, v in dist.items() if k >= bucket)


class TestForecastPullTimeWeight(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_weight_curve(self):
        self.assertEqual(self.m.forecast_pull_time_weight(FORECAST_PULL_START_HOUR), 1.0)  # full
        self.assertEqual(self.m.forecast_pull_time_weight(FORECAST_PULL_START_HOUR - 1), 1.0)
        self.assertEqual(self.m.forecast_pull_time_weight(FORECAST_PULL_END_HOUR), 0.0)    # off
        self.assertEqual(self.m.forecast_pull_time_weight(FORECAST_PULL_END_HOUR + 4), 0.0)
        mid = (FORECAST_PULL_START_HOUR + FORECAST_PULL_END_HOUR) // 2
        span = FORECAST_PULL_END_HOUR - FORECAST_PULL_START_HOUR
        self.assertAlmostEqual(self.m.forecast_pull_time_weight(mid),
                               (FORECAST_PULL_END_HOUR - mid) / span)


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
        # P(>=29) lifted from 0.15 toward the reach-rate target, but never past it.
        self.assertGreater(p_ge(out, 29), 0.50)
        self.assertLessEqual(p_ge(out, 29), FORECAST_PULL_TARGET_REACH + 1e-9)
        self.assertLess(out[27], self.under[27])  # body gave up mass

    def test_one_directional_noop_when_already_confident(self):
        # Already above the target -> the one-directional pull must leave it alone.
        confident = {28: 0.05, 29: 0.45, 30: 0.50}  # P(>=29)=0.95 > target
        out = self.m.apply_forecast_pull(
            confident, forecasts=[29, 29], hour=9,
            observed_bucket=23, current_observed_bucket=23,
        )
        self.assertAlmostEqual(p_ge(out, 29), 0.95, places=6)  # unchanged

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
