import os
import sys
import unittest
from datetime import datetime

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel, TORONTO_TZ, _UNLOADED


def _wu_row(time, temp, dew=10.0, hum=60.0, press=1015.0,
            wind="SW", wind_kmh=15.0, clouds="Partly Cloudy",
            condition="Partly Cloudy"):
    """A row shaped like fetch_wu_history output."""
    return {
        "time": time,
        "datetime": f"2026-05-29T{time}:00-04:00",
        "temp_c": temp,
        "dewpoint_c": dew,
        "humidity": hum,
        "pressure": press,
        "clouds": clouds,
        "condition": condition,
        "wind": wind,
        "wind_kmh": wind_kmh,
        "gust_kmh": None,
    }


def _sources(rows, max_c):
    max_times = [r["time"] for r in rows if r["temp_c"] == max_c]
    return {
        "wu_history": {
            "ok": True,
            "data": {
                "url": "test",
                "rows": rows,
                "latest": rows[-1] if rows else None,
                "max_c": max_c,
                "max_times": max_times,
            },
        }
    }


class TestEstimateDistribution(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel()

    def _assert_valid_distribution(self, dist):
        self.assertIsInstance(dist, dict)
        if not dist:
            return
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=6)
        self.assertTrue(all(0.0 <= p <= 1.0 for p in dist.values()))
        self.assertTrue(all(isinstance(t, int) for t in dist))

    def test_returns_normalized_distribution(self):
        rows = [
            _wu_row("07:00", 14.0),
            _wu_row("10:00", 18.0),
            _wu_row("12:00", 21.0),
            _wu_row("14:00", 22.0),
        ]
        dist = self.model.estimate_distribution(_sources(rows, 22.0))
        self._assert_valid_distribution(dist)
        self.assertTrue(dist)  # non-empty for real inputs

    def test_floor_suppresses_buckets_below_printed_high(self):
        # A printed high of 26 C is the settlement floor: the final high can
        # only be >= 26, so probability below 26 must be negligible.
        rows = [
            _wu_row("07:00", 18.0),
            _wu_row("10:00", 23.0),
            _wu_row("12:00", 26.0),
            _wu_row("14:00", 25.0),
        ]
        dist = self.model.estimate_distribution(_sources(rows, 26.0))
        self._assert_valid_distribution(dist)
        below = sum(p for t, p in dist.items() if t < 26)
        at_or_above = sum(p for t, p in dist.items() if t >= 26)
        self.assertLess(below, 0.05)
        self.assertGreater(at_or_above, 0.80)

    def test_empty_sources_is_safe(self):
        dist = self.model.estimate_distribution({})
        self._assert_valid_distribution(dist)

    def test_deterministic_with_fixed_now(self):
        # With a pinned `now`, the engine must be fully deterministic — this is
        # what makes backtesting possible.
        rows = [_wu_row("07:00", 14.0), _wu_row("12:00", 21.0), _wu_row("14:00", 22.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)
        d1 = self.model.estimate_distribution(_sources(rows, 22.0), now=now)
        d2 = self.model.estimate_distribution(_sources(rows, 22.0), now=now)
        self.assertEqual(d1, d2)

    def test_build_threads_now_without_network(self):
        rows = [_wu_row("07:00", 14.0), _wu_row("13:00", 21.0)]
        now = datetime(2026, 5, 29, 14, 0, tzinfo=TORONTO_TZ)
        event = {"markets": [], "slug": "highest-temperature-in-toronto-on-may-29-2026"}
        model = self.model.build(
            event,
            historical_sources={},
            live_sources=_sources(rows, 21.0),
            now=now,
        )
        self.assertIn("distribution", model)
        self._assert_valid_distribution(model["distribution"])


class TestDistributionHelpers(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel()

    def test_blend_distribution_is_convex_combination(self):
        out = self.model.blend_distribution({20: 1.0}, {22: 1.0}, 0.5)
        self.assertAlmostEqual(out[20], 0.5)
        self.assertAlmostEqual(out[22], 0.5)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_blend_distribution_zero_weight_keeps_base(self):
        out = self.model.blend_distribution({20: 1.0, 21: 1.0}, {25: 1.0}, 0.0)
        self.assertAlmostEqual(out[20], 0.5)
        self.assertAlmostEqual(out[21], 0.5)
        self.assertNotIn(25, out)

    def test_apply_tail_target_moves_tail_mass(self):
        scores = {20: 1, 21: 1, 22: 1, 23: 1, 24: 1}
        out = self.model.apply_tail_target(scores, threshold=22, target_tail=0.8, weight=1.0)
        tail = sum(p for t, p in out.items() if t > 22)
        self.assertAlmostEqual(tail, 0.8, places=5)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_cap_prior_distribution_peaks_at_cap_and_decays(self):
        out = self.model.cap_prior_distribution(range(20, 30), cap_bucket=25, floor_bucket=22)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        self.assertEqual(max(out, key=out.get), 25)   # peak at the cap
        self.assertGreater(out[25], out[27])           # decays above the cap
        self.assertLess(out[20], out[25])              # suppressed below the floor

    def test_apply_floor_scales_below_floor_in_place(self):
        scores = {20: 1.0, 21: 1.0, 22: 1.0}
        self.model.apply_floor(scores, floor_bucket=22, multiplier=0.001)
        self.assertAlmostEqual(scores[20], 0.001)
        self.assertAlmostEqual(scores[21], 0.001)
        self.assertAlmostEqual(scores[22], 1.0)


class TestModelLoadCaching(unittest.TestCase):
    """#10: model artifacts should be read from disk once, then reused."""

    def test_feature_model_hgb_is_memoized(self):
        model = TorontoHighTempModel()
        self.assertIs(model._feature_model_hgb, _UNLOADED)
        first = model.load_feature_model_hgb()
        self.assertIsNot(model._feature_model_hgb, _UNLOADED)
        second = model.load_feature_model_hgb()
        self.assertIs(first, second)  # same object, not re-read from disk

    def test_late_day_coefs_is_memoized(self):
        model = TorontoHighTempModel()
        self.assertIs(model._late_day_model_coefs, _UNLOADED)
        first = model.load_late_day_model_coefs()
        second = model.load_late_day_model_coefs()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
