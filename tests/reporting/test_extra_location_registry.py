import unittest

from weather.reporting.extra_location_registry import (
    BLOCKED,
    PASS,
    SHADOW_ONLY,
    build_compatibility_report,
    grade_location,
    render_report,
)


def _location(**extra):
    row = {
        "location_id": "test-extra",
        "station_id": "KAAA",
        "source_ids": ["wunderground_history", "open_meteo_forecast"],
        "timezone": "America/New_York",
        "unit": "F",
        "coordinates": {"lat": 40.0, "lon": -75.0, "elevation_m": 100},
        "coastal": False,
        "target_definition": "daily_high_temperature",
        "cutoff_policy": "local day max",
        "station_stability": "stable",
        "climate_similarity_class": "humid_continental_us",
        "independent_labeled_days": 80,
        "forecast_history_days": 70,
        "observation_days": 90,
    }
    row.update(extra)
    return row


class TestExtraLocationRegistry(unittest.TestCase):
    def test_grades_pass_when_required_provenance_and_coverage_clear(self):
        result = grade_location(_location())

        self.assertEqual(result["status"], PASS)
        self.assertTrue(result["training_eligible"])
        self.assertEqual(result["provenance"]["station_id"], "KAAA")

    def test_rejects_missing_station_provenance(self):
        result = grade_location(_location(station_id="", source_ids=[]))

        self.assertEqual(result["status"], BLOCKED)
        self.assertFalse(result["training_eligible"])
        self.assertTrue(any("station_provenance" in reason for reason in result["reasons"]))

    def test_rejects_ambiguous_target_definition_and_missing_timezone(self):
        result = grade_location(_location(target_definition="airport_temperature", timezone=""))

        self.assertEqual(result["status"], BLOCKED)
        self.assertTrue(any("settlement_label_compatibility" in reason for reason in result["reasons"]))
        self.assertTrue(any("unit_timezone_cutoff" in reason for reason in result["reasons"]))

    def test_insufficient_forecast_coverage_is_shadow_only(self):
        result = grade_location(_location(forecast_history_days=2))

        self.assertEqual(result["status"], SHADOW_ONLY)
        self.assertFalse(result["training_eligible"])
        self.assertTrue(any("forecast_history_coverage" in reason for reason in result["reasons"]))

    def test_report_counts_training_and_diagnostic_location_days(self):
        payload = build_compatibility_report({
            "schema_version": "no_market_extra_location_registry_v0.1",
            "path": "inline",
            "locations": [
                _location(location_id="pass-extra"),
                _location(location_id="shadow-extra", forecast_history_days=0),
            ],
        })

        self.assertEqual(payload["summary"]["training_eligible_location_count"], 1)
        self.assertEqual(payload["summary"]["shadow_only_location_count"], 1)
        self.assertEqual(payload["training_eligible_location_ids"], ["pass-extra"])
        self.assertIn("No-Market Extra-Location Compatibility", render_report(payload))


if __name__ == "__main__":
    unittest.main()
