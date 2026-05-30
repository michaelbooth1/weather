import os
import sys
import unittest

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


def _wu_row(time, temp):
    return {
        "time": time, "datetime": f"2026-05-30T{time}:00-04:00", "temp_c": temp,
        "dewpoint_c": 10.0, "humidity": 60.0, "pressure": 1015.0,
        "clouds": "Partly Cloudy", "condition": "Partly Cloudy",
        "wind": "SW", "wind_kmh": 15.0, "gust_kmh": None,
    }


def _sources(rows, day_max_c=None):
    s = {"wu_history": {"ok": True, "data": {
        "rows": rows, "latest": rows[-1] if rows else None,
        "max_c": max((r["temp_c"] for r in rows), default=None),
    }}}
    if day_max_c is not None:
        s["open_meteo"] = {"ok": True, "data": {"rows": [], "day_max_c": day_max_c}}
    return s


class TestForecastFeatureExtraction(unittest.TestCase):
    """The forecast feature must be defined identically to training:
    forecast_high = Open-Meteo forecasted daily max; gap = forecast_high - high_so_far."""

    def setUp(self):
        self.m = TorontoHighTempModel()

    def test_forecast_gap_is_forecast_minus_high_so_far(self):
        rows = [_wu_row("07:00", 11.0), _wu_row("09:00", 13.0)]
        feats = self.m.extract_live_features(_sources(rows, day_max_c=21.0), cutoff_hour=9)
        self.assertEqual(feats["forecast_high"], 21.0)
        self.assertAlmostEqual(feats["forecast_gap"], 21.0 - feats["high_so_far"])

    def test_missing_open_meteo_yields_none(self):
        rows = [_wu_row("09:00", 13.0)]
        feats = self.m.extract_live_features(_sources(rows, day_max_c=None), cutoff_hour=9)
        self.assertIsNone(feats["forecast_high"])
        self.assertIsNone(feats["forecast_gap"])

    def test_distribution_still_valid_with_forecast(self):
        rows = [_wu_row("07:00", 11.0), _wu_row("09:00", 13.0)]
        dist = self.m.estimate_distribution(_sources(rows, day_max_c=21.0))
        self.assertTrue(dist)
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
