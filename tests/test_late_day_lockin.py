import os
import sys
import unittest

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestLateDayLockinStrength(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_zero_before_late_or_while_still_warm(self):
        self.assertEqual(self.m.late_day_lockin_strength(14, 19.0, 25.0), 0.0)   # too early
        self.assertEqual(self.m.late_day_lockin_strength(20, 25.0, 25.0), 0.0)   # temp still at the high
        self.assertEqual(self.m.late_day_lockin_strength(20, None, 25.0), 0.0)   # no reading

    def test_full_when_late_and_past_peak(self):
        self.assertEqual(self.m.late_day_lockin_strength(20, 19.0, 25.0), 1.0)
        self.assertEqual(self.m.late_day_lockin_strength(23, 18.0, 25.0), 1.0)

    def test_ramps_with_time_and_drop(self):
        # hour 16 -> time (16-15)/(17-15)=0.5; drop 1 -> peak 0.5; strength 0.25
        self.assertAlmostEqual(self.m.late_day_lockin_strength(16, 24.0, 25.0), 0.5 * 0.5)


class TestLearnedLockinStrength(unittest.TestCase):
    """v0.5.6: the lag artifact's revision-up curve floors the lock-in late,
    covering the evening plateau (current == high -> heuristic drop 0) where
    the 2026-06-09 model held 20%+ above the high against a learned ~2-5%
    revision rate."""

    def setUp(self):
        from datetime import datetime
        self.datetime = datetime
        self.m = TorontoHighTempModel()
        self.m.settlement_lag_model = {
            "component": {"min_context_n": 20},
            "revision_contexts": {
                "hour=17": {"n": 600, "revision_up_rate": 0.08},
                "hour=19": {"n": 600, "revision_up_rate": 0.02},
                "hour=20": {"n": 600, "revision_up_rate": 0.003},
            },
        }
        self.history = {"max_c": 24.0, "max_times": ["12:35"]}

    def _now(self, hour, minute=0):
        return self.datetime(2026, 6, 9, hour, minute)

    def test_plateau_evening_gets_learned_lock(self):
        strength = self.m.learned_lockin_strength(19, self.history, self._now(19, 10))
        self.assertAlmostEqual(strength, 0.98)

    def test_zero_before_learned_start_hour(self):
        self.assertEqual(
            self.m.learned_lockin_strength(16, self.history, self._now(16, 30)), 0.0
        )

    def test_zero_while_high_is_fresh(self):
        fresh = {"max_c": 24.0, "max_times": ["18:40"]}
        self.assertEqual(
            self.m.learned_lockin_strength(19, fresh, self._now(19, 30)), 0.0
        )

    def test_zero_without_artifact(self):
        self.m.settlement_lag_model = None
        self.assertEqual(
            self.m.learned_lockin_strength(19, self.history, self._now(19, 10)), 0.0
        )

    def test_late_evening_clamps_to_last_trained_hour(self):
        # hour 22 reuses the 20:00 context.
        strength = self.m.learned_lockin_strength(22, self.history, self._now(22, 0))
        self.assertAlmostEqual(strength, 0.997)

    def test_thin_context_is_ignored(self):
        self.m.settlement_lag_model["revision_contexts"]["hour=19"]["n"] = 5
        self.assertEqual(
            self.m.learned_lockin_strength(19, self.history, self._now(19, 10)), 0.0
        )


class TestApplyLateDayLockin(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_replays_june2_evening_locks_onto_observed_high(self):
        # The real failure: evening model kept ~35% on 26 while WU settled 25.
        peaked = {24: 0.10, 25: 0.50, 26: 0.35, 27: 0.05}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=19.0, hour=22)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)
        self.assertEqual(max(out, key=out.get), 25)   # concentrates onto the observed high
        self.assertLess(out[26], peaked[26])           # upper tail suppressed
        self.assertGreater(out[26], 0.0)               # but soft (WU could revise up a degree)

    def test_noop_when_not_locked_in(self):
        peaked = {24: 0.10, 25: 0.50, 26: 0.40}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=25.5, hour=14)
        # Strength 0 -> proportions preserved.
        self.assertAlmostEqual(out[26] / out[25], 0.40 / 0.50)

    def test_does_not_touch_at_or_below_observed(self):
        peaked = {23: 0.2, 24: 0.2, 25: 0.4, 26: 0.2}
        out = self.m.apply_late_day_lockin(peaked, history_max=25.0, current_reading=18.0, hour=21)
        # 23, 24, 25 keep their pre-norm ratios; only 26 is suppressed.
        self.assertAlmostEqual(out[23] / out[24], 1.0)
        self.assertAlmostEqual(out[24] / out[25], 0.2 / 0.4)


if __name__ == "__main__":
    unittest.main()
