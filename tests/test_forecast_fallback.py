import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


class TestResolveForecastHigh(unittest.TestCase):
    def setUp(self):
        self.m = TorontoHighTempModel(target_date=None)

    def test_open_meteo_used_when_present(self):
        # The common case must be unchanged (no train/serve skew).
        value, source = self.m.resolve_forecast_high(
            {"day_max_c": 28.0},
            {"rows": [{"temp_c": 29.0}]},   # other forecasts ignored when OM present
            {"forecast_high_c": 30.0},
        )
        self.assertEqual(value, 28.0)
        self.assertEqual(source, "open_meteo")

    def test_consensus_fallback_when_open_meteo_missing(self):
        value, source = self.m.resolve_forecast_high(
            {},                                  # OM down (502)
            {"rows": [{"temp_c": 29.0}]},        # Weather.com 29
            {"forecast_high_c": 30.0},           # ECCC 30
        )
        self.assertEqual(value, 29.5)            # median(29, 30)
        self.assertEqual(source, "fallback_consensus")

    def test_single_other_forecast(self):
        value, source = self.m.resolve_forecast_high(
            {"day_max_c": None},
            {"rows": []},                        # no Weather.com rows
            {"forecast_high_c": 30.0},
        )
        self.assertEqual(value, 30.0)
        self.assertEqual(source, "fallback_consensus")

    def test_none_when_no_forecasts_at_all(self):
        value, source = self.m.resolve_forecast_high({}, {"rows": []}, {})
        self.assertIsNone(value)
        self.assertEqual(source, "none")

    def test_extract_features_recovers_forecast_during_outage(self):
        # The June-4 shape: Open-Meteo 502, ECCC/Weather.com present. The HGB
        # must no longer be forecast-blind.
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
