import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestResolveForecastHigh(unittest.TestCase):
    """The canonical forecast feature is the MEDIAN of available sources
    (v0.5.3). With one source available -- the only case that exists in the
    historical training archive -- the median IS that source's value, which is
    what keeps train/serve parity without retraining."""

    def setUp(self):
        self.m = TorontoHighTempModel(target_date=None)

    def test_median_of_all_three_sources(self):
        value, source = self.m.resolve_forecast_high(
            {"day_max_c": 28.0},
            {"rows": [{"temp_c": 29.0}]},
            {"forecast_high_c": 30.0},
        )
        self.assertEqual(value, 29.0)            # median(28, 29, 30)
        self.assertEqual(source, "median_of_3")

    def test_one_busted_source_cannot_own_the_feature(self):
        # The 2026-06-09 Toronto shape: Open-Meteo stale at 27.6 while
        # Weather.com had already dropped to 24. OM-first served 27.6 all
        # afternoon; the median stays anchored by the sane sources.
        value, _ = self.m.resolve_forecast_high(
            {"day_max_c": 27.6},
            {"rows": [{"temp_c": 24.0}]},
            {"forecast_high_c": 26.0},
        )
        self.assertEqual(value, 26.0)            # median(24, 26, 27.6)

    def test_median_of_two_when_eccc_missing(self):
        # The F-market shape (no ECCC source).
        value, source = self.m.resolve_forecast_high(
            {"day_max_c": 28.0},
            {"rows": [{"temp_c": 29.0}]},
            {},
        )
        self.assertEqual(value, 28.5)            # median(28, 29)
        self.assertEqual(source, "median_of_2")

    def test_single_source_is_that_source(self):
        # The training-archive case: exactly one source -> its own value.
        # This identity is the train/serve parity argument.
        value, source = self.m.resolve_forecast_high(
            {"day_max_c": 26.0}, {"rows": []}, {},
        )
        self.assertEqual(value, 26.0)
        self.assertEqual(source, "open_meteo")

    def test_consensus_when_open_meteo_missing(self):
        value, source = self.m.resolve_forecast_high(
            {},                                  # OM down (502)
            {"rows": [{"temp_c": 29.0}]},        # Weather.com 29
            {"forecast_high_c": 30.0},           # ECCC 30
        )
        self.assertEqual(value, 29.5)            # median(29, 30)
        self.assertEqual(source, "median_of_2")

    def test_none_when_no_forecasts_at_all(self):
        value, source = self.m.resolve_forecast_high({}, {"rows": []}, {})
        self.assertIsNone(value)
        self.assertEqual(source, "none")

    def test_extract_features_recovers_forecast_during_outage(self):
        # The June-4 shape: Open-Meteo 502, ECCC/Weather.com present. The HGB
        # must not go forecast-blind.
        sources = {
            "wu_history": {"ok": True, "data": {"rows": [
                {"time": "09:00", "temp_c": 23.0, "dewpoint_c": 7.0, "humidity": 36,
                 "pressure": 1001.0, "wind": "SW", "condition": "Mostly Cloudy"},
            ], "max_c": 23.0}},
            "wu_current": {"ok": True, "data": {"temp_c": 23.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"temp_c": 29.0}]}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 30.0}},
            "open_meteo": {"ok": False, "data": {}},   # outage
        }
        feats = self.m.extract_live_features(sources, 9)
        self.assertEqual(feats["forecast_high"], 29.5)       # consensus, not None
        self.assertAlmostEqual(feats["forecast_gap"], 29.5 - 23.0)


if __name__ == "__main__":
    unittest.main()
