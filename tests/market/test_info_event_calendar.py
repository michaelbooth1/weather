import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from weather.market.info_event_calendar import (
    event_gate_for_market,
    scheduled_events_for_market,
)


class TestInfoEventCalendar(unittest.TestCase):
    def test_default_calendar_builds_per_market_weather_and_market_events(self):
        rows = scheduled_events_for_market(
            "atlanta",
            now="2026-06-14T15:52:00+00:00",
            event_slug="highest-temperature-in-atlanta-on-june-14-2026",
            horizon_minutes=1440,
        )
        classes = {row["event_class"] for row in rows}

        self.assertIn("metar_print_window", classes)
        self.assertIn("nwp_release_cycle", classes)
        self.assertIn("forecast_archive_update", classes)
        self.assertIn("market_close", classes)

    def test_metar_print_window_pulls_quotes_by_default(self):
        gate = event_gate_for_market(
            "atlanta",
            now="2026-06-14T15:56:00+00:00",
            event_slug="highest-temperature-in-atlanta-on-june-14-2026",
        )

        self.assertEqual(gate["status"], "PULL")
        self.assertEqual(gate["action"], "suppress")
        self.assertEqual((gate["active_events"] or [{}])[0]["event_class"], "metar_print_window")


if __name__ == "__main__":
    unittest.main()
