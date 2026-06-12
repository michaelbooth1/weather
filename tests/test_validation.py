import os
import sys
import unittest
from datetime import date, datetime

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from wu_history import (
    normalize_observation,
    summarize_daily,
    to_number,
    round_half_up,
    get_code_version,
    calculate_sha256,
    WundergroundHistoryStore
)
from daily_summary import celsius_high, native_high
from toronto_model import TorontoHighTempModel

class TestWundergroundHistoryParsing(unittest.TestCase):
    def test_to_number(self):
        self.assertEqual(to_number("12.5"), 12.5)
        self.assertEqual(to_number(12.5), 12.5)
        self.assertIsNone(to_number(None))
        self.assertIsNone(to_number("invalid"))

    def test_round_half_up(self):
        self.assertEqual(round_half_up(12.5), 13)
        self.assertEqual(round_half_up(12.4), 12)
        self.assertEqual(round_half_up(12.6), 13)
        self.assertEqual(round_half_up(-1.5), -1)
        self.assertIsNone(round_half_up(None))

    def test_normalize_observation(self):
        obs = {
            "valid_time_gmt": 1779930000,  # Specific timestamp
            "temp": 15.2,
            "dewPt": 8.5,
            "rh": 65,
            "pressure": 1013.25,
            "clds": "SCT",
            "wx_phrase": "Partly Cloudy",
            "wdir_cardinal": "SSW",
            "wspd": 15.5,
            "gust": 20.0
        }
        res = normalize_observation(obs)
        self.assertEqual(res["schema_version"], "wu_hourly_native_v1")
        self.assertEqual(res["temperature_unit"], "C")
        self.assertEqual(res["temp_native"], 15.2)
        self.assertEqual(res["temp_c"], 15.2)
        self.assertEqual(res["dewpoint_c"], 8.5)
        self.assertEqual(res["humidity"], 65)
        self.assertEqual(res["pressure"], 1013.25)
        self.assertEqual(res["clouds"], "SCT")
        self.assertEqual(res["condition"], "Partly Cloudy")
        self.assertEqual(res["wind_cardinal"], "SSW")
        self.assertEqual(res["wind_speed_kmh"], 15.5)
        self.assertEqual(res["wind_gust_kmh"], 20.0)

    def test_normalize_observation_missing(self):
        # Empty dict should handle fields gracefully
        res = normalize_observation({})
        self.assertIsNone(res["temp_c"])
        self.assertIsNone(res["dewpoint_c"])
        self.assertIsNone(res["wind_cardinal"])

    def test_summarize_daily(self):
        records = [
            {"local_date": "2026-05-27", "valid_time_local": "2026-05-27T08:00:00", "local_time": "08:00", "minute": 0, "temp_c": 15.0, "clouds": "CLR", "condition": "Fair", "wind_cardinal": "SSW"},
            {"local_date": "2026-05-27", "valid_time_local": "2026-05-27T09:00:00", "local_time": "09:00", "minute": 0, "temp_c": 20.0, "clouds": "FEW", "condition": "Fair", "wind_cardinal": "S"},
            {"local_date": "2026-05-27", "valid_time_local": "2026-05-27T10:00:00", "local_time": "10:00", "minute": 0, "temp_c": 18.0, "clouds": "BKN", "condition": "Cloudy", "wind_cardinal": "S"},
            {"local_date": "2026-05-27", "valid_time_local": "2026-05-27T11:00:00", "local_time": "11:00", "minute": 0, "temp_c": 22.0, "clouds": "FEW", "condition": "Fair", "wind_cardinal": "SW"},
            {"local_date": "2026-05-27", "valid_time_local": "2026-05-27T12:00:00", "local_time": "12:00", "minute": 0, "temp_c": 12.0, "clouds": "CLR", "condition": "Fair", "wind_cardinal": "SSW"}
        ]
        summary_list = summarize_daily(records)
        self.assertEqual(len(summary_list), 1)
        summary = summary_list[0]
        self.assertEqual(summary["schema_version"], "wu_daily_native_v2")
        self.assertEqual(summary["temperature_unit"], "C")
        self.assertEqual(summary["row_count"], 5)
        self.assertEqual(summary["max_temp"], 22.0)
        self.assertEqual(summary["max_temp_bucket"], 22)
        self.assertEqual(summary["max_temp_c"], 22.0)
        self.assertEqual(summary["max_temp_bucket_c"], 22)
        self.assertEqual(summary["min_temp_c"], 12.0)
        self.assertEqual(summary["condition_mode"], "Fair")
        self.assertEqual(summary["cloud_mode"], "CLR")

    def test_fahrenheit_observation_keeps_native_and_true_celsius(self):
        obs = {
            "valid_time_gmt": 1779930000,
            "temp": 86.0,
            "dewPt": 68.0,
        }
        res = normalize_observation(obs, unit="F")
        self.assertEqual(res["temperature_unit"], "F")
        self.assertEqual(res["temp_native"], 86.0)
        self.assertAlmostEqual(res["temp_c"], 30.0)
        self.assertEqual(res["dewpoint_native"], 68.0)
        self.assertAlmostEqual(res["dewpoint_c"], 20.0)

    def test_fahrenheit_daily_summary_has_native_and_celsius_columns(self):
        records = [
            {
                "local_date": "2026-06-01",
                "valid_time_local": "2026-06-01T12:00:00",
                "local_time": "12:00",
                "minute": 0,
                "temperature_unit": "F",
                "temp_native": 84.0,
                "dewpoint_native": 65.0,
            },
            {
                "local_date": "2026-06-01",
                "valid_time_local": "2026-06-01T13:00:00",
                "local_time": "13:00",
                "minute": 0,
                "temperature_unit": "F",
                "temp_native": 86.0,
                "dewpoint_native": 68.0,
            },
        ]
        summary = summarize_daily(records)[0]
        self.assertEqual(summary["schema_version"], "wu_daily_native_v2")
        self.assertEqual(summary["temperature_unit"], "F")
        self.assertEqual(summary["max_temp"], 86.0)
        self.assertEqual(summary["max_temp_native"], 86.0)
        self.assertEqual(summary["max_temp_bucket"], 86)
        self.assertEqual(summary["max_temp_bucket_native"], 86)
        self.assertAlmostEqual(summary["max_temp_c"], 30.0)
        self.assertEqual(summary["max_temp_bucket_c"], 30)
        self.assertEqual(native_high(summary), 86.0)
        self.assertAlmostEqual(celsius_high(summary), 30.0)


class TestTorontoModelCore(unittest.TestCase):
    def setUp(self):
        self.model = TorontoHighTempModel()

    def test_normalize_scores(self):
        scores = {20: 1.0, 21: 2.0, 22: 1.0}
        normed = self.model.normalize_scores(scores)
        self.assertAlmostEqual(sum(normed.values()), 1.0)
        self.assertAlmostEqual(normed[20], 0.25)
        self.assertAlmostEqual(normed[21], 0.50)
        self.assertAlmostEqual(normed[22], 0.25)

    def test_normalize_scores_all_zero(self):
        scores = {20: 0.0, 21: 0.0}
        normed = self.model.normalize_scores(scores)
        self.assertEqual(normed, {})

    def test_market_bins(self):
        event = {
            "markets": [
                {
                    "groupItemTitle": "24 C or below",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.40", "0.60"]'
                },
                {
                    "groupItemTitle": "25 C",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.35", "0.65"]'
                },
                {
                    "groupItemTitle": "26 C or higher",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.25", "0.75"]'
                }
            ]
        }
        bins = self.model.market_bins(event)
        self.assertEqual(len(bins), 3)
        
        # Verify first bin (lte 24 C)
        self.assertEqual(bins[0]["kind"], "lte")
        self.assertEqual(bins[0]["value"], 24)
        self.assertAlmostEqual(bins[0]["market_yes"], 0.40)
        
        # Verify second bin (eq 25 C)
        self.assertEqual(bins[1]["kind"], "eq")
        self.assertEqual(bins[1]["value"], 25)
        self.assertAlmostEqual(bins[1]["market_yes"], 0.35)
        
        # Verify third bin (gte 26 C)
        self.assertEqual(bins[2]["kind"], "gte")
        self.assertEqual(bins[2]["value"], 26)
        self.assertAlmostEqual(bins[2]["market_yes"], 0.25)


class TestWundergroundHistoryRebuildAndAudit(unittest.TestCase):
    def test_get_code_version(self):
        ver = get_code_version()
        self.assertTrue(ver.startswith("git:") or ver.startswith("file_sha256:"))

    def test_checksum_calculation(self):
        import tempfile
        import hashlib
        with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8") as f:
            f.write("test content")
            filename = f.name
        try:
            expected = hashlib.sha256("test content".encode("utf-8")).hexdigest()
            actual = calculate_sha256(filename)
            self.assertEqual(actual, expected)
        finally:
            os.unlink(filename)

    def test_audit_partitions_success(self):
        from wu_history import DEFAULT_DATA_ROOT
        store = WundergroundHistoryStore(DEFAULT_DATA_ROOT)
        if store.root.exists():
            success = store.audit_partitions()
            self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
