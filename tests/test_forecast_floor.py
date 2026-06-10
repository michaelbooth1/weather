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


class TestUnfalsifiedForecasts(unittest.TestCase):
    """The stale-forecast bench (v0.5.5): a source still claiming >=1C above a
    WU high that has stood unimproved 90+ minutes (past 13:00) loses its
    floor/pull vote. The 2026-06-09 shape: high 24 printed 12:35, Open-Meteo
    27.6 all afternoon."""

    def setUp(self):
        self.m = TorontoHighTempModel()

    def _now(self, hour, minute=0):
        from datetime import datetime
        return datetime(2026, 6, 9, hour, minute)

    def test_benches_stale_sources_past_peak(self):
        history = {"max_c": 24.0, "max_times": ["12:35"]}
        votes = self.m.unfalsified_forecasts(
            [24.0, 27.6, 26.0], history, self._now(14, 30)
        )
        # OM 27.6 and ECCC 26 are benched (> 24 + 1); Weather.com 24 survives.
        self.assertEqual(votes, [24.0])

    def test_no_bench_in_the_morning(self):
        # Mornings plateau before the ramp; benching at 09:00 would recreate
        # the measured morning-skepticism failure.
        history = {"max_c": 18.0, "max_times": ["07:10"]}
        votes = self.m.unfalsified_forecasts(
            [27.0, 26.0], history, self._now(9, 0)
        )
        self.assertEqual(votes, [27.0, 26.0])

    def test_no_bench_while_high_is_fresh(self):
        # High reached 40 minutes ago: the day may still be ramping.
        history = {"max_c": 24.0, "max_times": ["13:50"]}
        votes = self.m.unfalsified_forecasts(
            [27.6, 26.0], history, self._now(14, 30)
        )
        self.assertEqual(votes, [27.6, 26.0])

    def test_rising_high_resets_the_clock(self):
        # The high improved to 25 at 14:20 (max_times resets to the new max):
        # sources above it get a fresh window.
        history = {"max_c": 25.0, "max_times": ["14:20"]}
        votes = self.m.unfalsified_forecasts(
            [27.6, 26.0], history, self._now(15, 0)
        )
        self.assertEqual(votes, [27.6, 26.0])

    def test_claims_near_the_high_keep_their_vote(self):
        history = {"max_c": 24.0, "max_times": ["12:35"]}
        votes = self.m.unfalsified_forecasts(
            [24.8, 25.0, None], history, self._now(15, 0)
        )
        # Within high + 1: both keep voting; None passes through untouched.
        self.assertEqual(votes, [24.8, 25.0, None])

    def test_no_history_high_means_no_bench(self):
        votes = self.m.unfalsified_forecasts(
            [27.0], {"max_c": None, "max_times": []}, self._now(15, 0)
        )
        self.assertEqual(votes, [27.0])


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
