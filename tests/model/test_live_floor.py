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

    def test_current_floor_is_catchup_sized_not_near_hard(self):
        # v0.5.4: the current-reading floor uses the learned catch-up hedge
        # like SWOB. With wu_current catch-up 40%, one bucket below retains
        # 60% -- it must never be the old 0.001 near-hard hedge (finding #5).
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "catchup_contexts": {
                "source=weather_current|gap=1": {"n": 50, "catchup_rate": 0.40},
            },
        }
        peaked = {18: 0.50, 19: 0.25, 20: 0.20, 21: 0.05}

        out = self.m.apply_current_observed_floor(
            peaked,
            current_temp=19.0,
            metar_temp=None,
            history_max=18.0,
        )

        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        # 18 retains hedge = 1 - 0.40 = 0.60 of its mass pre-normalization.
        self.assertAlmostEqual(out[18] / out[19], 0.50 * 0.60 / 0.25, places=6)
        self.assertGreater(out[18], 0.20)   # decisively not near-hard

    def test_current_floor_hedge_never_below_clamp(self):
        # Even a 99% measured catch-up cannot make a non-resolution reading a
        # hard floor: the hedge clamps at 0.30 (the v0.4.8 lesson).
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "catchup_contexts": {
                "source=metar|gap=1": {"n": 200, "catchup_rate": 0.99},
            },
        }
        peaked = {18: 0.50, 19: 0.50}

        out = self.m.apply_current_observed_floor(
            peaked,
            current_temp=None,
            metar_temp=19.0,
            history_max=18.0,
        )

        self.assertAlmostEqual(out[18] / out[19], 0.30, places=6)

    def test_current_floor_defaults_to_soft_hedge_without_artifact(self):
        # US markets have no lag artifact yet: the default hedge is the same
        # 0.40 the SWOB floor uses, never the old 0.001.
        self.m.settlement_lag_model = None
        peaked = {18: 0.50, 19: 0.50}

        out = self.m.apply_current_observed_floor(
            peaked,
            current_temp=19.0,
            metar_temp=None,
            history_max=18.0,
        )

        self.assertAlmostEqual(out[18] / out[19], 0.40, places=6)

    def test_current_floor_sizes_by_the_leading_source(self):
        # METAR leads at 20 while wu_current reads 19: the floor sits at 20
        # and is sized by METAR's catch-up context.
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "catchup_contexts": {
                "source=metar|gap=2": {"n": 60, "catchup_rate": 0.50},
                "source=weather_current|gap=1": {"n": 60, "catchup_rate": 0.10},
            },
        }
        scores = {18: 0.25, 19: 0.25, 20: 0.25, 21: 0.25}

        out = self.m.apply_current_observed_floor(
            scores,
            current_temp=19.0,
            metar_temp=20.0,
            history_max=18.0,
        )

        # One below the METAR bucket (19) retains 1 - 0.50 = 0.50.
        self.assertAlmostEqual(out[19] / out[20], 0.50, places=6)
        self.assertLess(out[18], out[19])   # further below decays harder

    def test_current_floor_noop_when_history_covers_reading(self):
        scores = {18: 0.50, 19: 0.50}
        out = self.m.apply_current_observed_floor(
            scores,
            current_temp=18.4,
            metar_temp=None,
            history_max=19.0,
        )
        self.assertAlmostEqual(out[18], out[19])

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
