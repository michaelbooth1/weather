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
        # hour 17 -> time (17-15)/(20-15)=0.4; drop 1 -> peak 0.5; strength 0.2
        self.assertAlmostEqual(self.m.late_day_lockin_strength(17, 24.0, 25.0), 0.4 * 0.5)


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
