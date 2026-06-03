import os
import sys
import unittest

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestLiveObservedFloor(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_suppresses_below_swob_with_one_bucket_hedge(self):
        scores = {t: 1.0 for t in range(16, 22)}  # uniform 16..21
        # SWOB has observed 19.4 (bucket 19); WU history stuck at 18.
        out = self.m.apply_live_observed_floor(scores, swob_max=19.4, history_max=18.0)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        # At/above the SWOB bucket: untouched (equal pre-norm).
        self.assertAlmostEqual(out[19], out[20])
        self.assertAlmostEqual(out[20], out[21])
        # One below (18) is the hedge zone; two below (17) much weaker; both > 0.
        self.assertLess(out[18], out[19])
        self.assertLess(out[17], out[18])
        self.assertGreater(out[18], 0.0)

    def test_replays_todays_lag_peak_moves_off_stuck_wu(self):
        # The real failure: model peaked at 18 (stuck WU) while SWOB had hit 20.
        peaked = {16: 0.05, 17: 0.10, 18: 0.50, 19: 0.20, 20: 0.10, 21: 0.05}
        out = self.m.apply_live_observed_floor(peaked, swob_max=20.0, history_max=18.0)
        # Peak should jump from the stuck-WU bucket (18) up to the SWOB bucket (20).
        self.assertEqual(max(out, key=out.get), 20)
        self.assertLess(out[18], peaked[18])  # the stuck bucket is suppressed

    def test_current_observed_floor_nearly_eliminates_buckets_below_current_temp(self):
        peaked = {18: 0.50, 19: 0.25, 20: 0.20, 21: 0.05}

        out = self.m.apply_current_observed_floor(
            peaked,
            current_observed_max=19.0,
            history_max=18.0,
        )

        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertLess(out[18], 0.001)
        self.assertEqual(max(out, key=out.get), 19)

    def test_noop_when_swob_not_ahead_of_wu(self):
        scores = {t: 1.0 for t in range(16, 22)}
        out = self.m.apply_live_observed_floor(scores, swob_max=18.0, history_max=19.0)
        self.assertAlmostEqual(out[16], out[21])  # WU floor already covers it

    def test_noop_when_swob_missing(self):
        scores = {t: 1.0 for t in range(16, 22)}
        out = self.m.apply_live_observed_floor(scores, swob_max=None, history_max=18.0)
        self.assertAlmostEqual(out[16], out[21])


if __name__ == "__main__":
    unittest.main()
