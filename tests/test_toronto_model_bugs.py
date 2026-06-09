import os
import sys
import unittest
from datetime import datetime

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel, TORONTO_TZ


class TestParseWeatherComTime(unittest.TestCase):
    """Bug 2: parse_weather_com_time had a duplicated format and rejected
    common ISO-8601 offset variants."""

    def setUp(self):
        self.model = TorontoHighTempModel()

    def test_standard_offset_without_colon(self):
        parsed = self.model.parse_weather_com_time("2026-05-29T14:23:00-0400")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 14)

    def test_offset_with_colon(self):
        parsed = self.model.parse_weather_com_time("2026-05-29T14:23:00-04:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 14)

    def test_trailing_z(self):
        # 18:23 UTC -> 14:23 in Toronto (EDT) on this date.
        parsed = self.model.parse_weather_com_time("2026-05-29T18:23:00Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 14)

    def test_garbage_returns_none(self):
        self.assertIsNone(self.model.parse_weather_com_time("not a time"))
        self.assertIsNone(self.model.parse_weather_com_time(""))
        self.assertIsNone(self.model.parse_weather_com_time(None))


class TestLiveSourcesPreserveWuHistory(unittest.TestCase):
    """Regression (v0.5.1 -> v0.5.2): fetch_live_sources briefly injected a
    fabricated wu_current row into wu_history rows, backdated to the top of
    the hour. wu_history rows are settlement-source evidence and must be
    returned exactly as fetched."""

    def test_fetch_live_sources_does_not_append_to_wu_history_rows(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        printed_rows = [
            {"time": "13:00", "temp_c": 19.0},
            {"time": "14:00", "temp_c": 19.5},
        ]
        fetched = {
            "wu_history": {
                "ok": True,
                "data": {"rows": list(printed_rows), "max_c": 19.5, "max_times": ["14:00"]},
                "fetched_at": "2026-05-28T14:40:00-04:00",
            },
            "wu_current": {
                "ok": True,
                "data": {"temp_c": 21.0, "time": "2026-05-28T14:40:00-0400"},
                "fetched_at": "2026-05-28T14:40:00-04:00",
            },
        }
        model.fetch_source_group = lambda fetchers: fetched
        model.blend_with_last_good = lambda sources: sources

        result = model.fetch_live_sources()

        self.assertEqual(result["wu_history"]["data"]["rows"], printed_rows)
        self.assertEqual(
            [row["time"] for row in result["wu_history"]["data"]["rows"]],
            ["13:00", "14:00"],
        )


class TestFindAnalogDaysReturnShape(unittest.TestCase):
    """Bug 3: find_analog_days returned [] on early exits but a dict on
    success. It must always return the dict shape."""

    def setUp(self):
        self.model = TorontoHighTempModel()

    def test_empty_sources_returns_dict(self):
        now = datetime.now(TORONTO_TZ)
        result = self.model.find_analog_days({}, 13, now)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("analogs"), [])
        self.assertIn("today_features", result)
        self.assertIn("cutoff_hour", result)


class TestDeepDiveReusesAnalogs(unittest.TestCase):
    """Bug 1: deep_dive_rows recomputed analogs at a different (wall-clock)
    cutoff. It must reuse analogs passed in from build() and not recompute."""

    def setUp(self):
        self.model = TorontoHighTempModel()

    def test_uses_passed_analogs_without_recomputing(self):
        def _boom(*args, **kwargs):
            raise AssertionError("find_analog_days should not be recomputed")

        self.model.find_analog_days = _boom
        analogs = {
            "cutoff_hour": 13,
            "today_features": {},
            "analogs": [{"final_bucket": 25}, {"final_bucket": 24}],
        }
        # Should not raise, because analogs are provided.
        rows = self.model.deep_dive_rows({}, {}, analogs)
        analog_row = next(
            r for r in rows if r["Question"] == "What do historical analogs say?"
        )
        self.assertEqual(analog_row["Answer"], "2 analogs found")


if __name__ == "__main__":
    unittest.main()
