import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel
from model_distribution import (
    FORECAST_PULL_END_HOUR,
    FORECAST_PULL_START_HOUR,
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


class TestForecastSoftDensity(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()
        self.support = list(range(20, 34))

    def test_spread_and_capped(self):
        # A single forecast must not concentrate one bucket: a sigma>=1.5 Gaussian
        # peaks at well under a third of its mass on the centre.
        d = self.m.forecast_soft_density([28], self.support)
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)
        self.assertLess(max(d.values()), 0.30)
        self.assertEqual(max(d, key=d.get), 28)  # centred on the forecast

    def test_stable_across_rounding_boundary(self):
        # The whole point: a 0.5C wiggle across x.5 barely moves any bucket.
        lo = self.m.forecast_soft_density([27.3, 26, 26], self.support)
        hi = self.m.forecast_soft_density([27.8, 26, 26], self.support)
        for b in self.support:
            self.assertLess(abs(hi[b] - lo[b]), 0.03)

    def test_disagreement_spreads_wider(self):
        agree = self.m.forecast_soft_density([26, 26, 26], self.support)
        disagree = self.m.forecast_soft_density([24, 26, 28], self.support)
        self.assertLess(max(disagree.values()), max(agree.values()))  # flatter


class TestApplyForecastPull(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()
        self.under = {25: 0.10, 26: 0.20, 27: 0.30, 28: 0.25, 29: 0.10, 30: 0.05}

    def _norm(self, d):
        t = sum(d.values())
        return {k: v / t for k, v in d.items()}

    def test_blends_toward_forecast_region(self):
        # Under-calling morning: forecasts agree high; the pull lifts that region.
        base = {24: 0.4, 25: 0.3, 26: 0.2, 27: 0.07, 28: 0.03}
        out = self.m.apply_forecast_pull(
            dict(base), forecasts=[28, 28, 29], hour=9,
            observed_bucket=22, current_observed_bucket=22,
        )
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertGreater(p_ge(out, 28), p_ge(base, 28))

    def test_stable_across_rounding_boundary(self):
        lo = self.m.apply_forecast_pull(dict(self.under), forecasts=[27.3, 26, 26], hour=12,
                                        observed_bucket=22, current_observed_bucket=22)
        hi = self.m.apply_forecast_pull(dict(self.under), forecasts=[27.8, 26, 26], hour=12,
                                        observed_bucket=22, current_observed_bucket=22)
        self.assertLess(abs(hi.get(28, 0) - lo.get(28, 0)), 0.03)  # was a hard bucket flip

    def test_deflates_single_bucket_overcall(self):
        spike = {26: 0.10, 27: 0.25, 28: 0.53, 29: 0.08, 30: 0.04}
        out = self.m.apply_forecast_pull(dict(spike), forecasts=[27.8, 26, 26], hour=12,
                                         observed_bucket=22, current_observed_bucket=22)
        self.assertLess(out.get(28, 0), self._norm(spike)[28])  # over-call pulled down

    def test_noop_late_in_day(self):
        out = self.m.apply_forecast_pull(dict(self.under), forecasts=[29, 29], hour=17,
                                         observed_bucket=23, current_observed_bucket=23)
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])

    def test_noop_when_forecasts_disagree(self):
        out = self.m.apply_forecast_pull(dict(self.under), forecasts=[20, 31], hour=9,
                                         observed_bucket=23, current_observed_bucket=23)
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])

    def test_noop_when_high_already_reached(self):
        out = self.m.apply_forecast_pull(dict(self.under), forecasts=[29, 29], hour=9,
                                         observed_bucket=30, current_observed_bucket=30)
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])

    def test_noop_single_forecast(self):
        out = self.m.apply_forecast_pull(dict(self.under), forecasts=[29], hour=9,
                                         observed_bucket=23, current_observed_bucket=23)
        self.assertAlmostEqual(out[29] / out[27], self.under[29] / self.under[27])


if __name__ == "__main__":
    unittest.main()
