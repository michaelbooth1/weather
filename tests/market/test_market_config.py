import os
import sys
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path


sys.path.insert(0, os.path.abspath("src"))

from market_config import config_for_date, date_from_event_slug, event_slug_for_date  # noqa: E402
from market_registry import (  # noqa: E402
    MARKET_REGISTRY_SCHEMA_VERSION,
    build_registry,
    load_external_registry,
    validate_market_registry,
)
from snapshot_tracker import SnapshotStore  # noqa: E402


class TestMarketConfig(unittest.TestCase):
    def test_event_slug_round_trips_target_date(self):
        target = date(2026, 5, 28)
        slug = event_slug_for_date(target)

        self.assertEqual(slug, "highest-temperature-in-toronto-on-may-28-2026")
        self.assertEqual(date_from_event_slug(slug), target)

    def test_config_for_date_coerces_datetime_to_date(self):
        target = datetime(2026, 5, 28, 14, 30)
        config = config_for_date(target)

        self.assertEqual(config.target_date, date(2026, 5, 28))
        self.assertIs(type(config.target_date), date)

    def test_snapshot_store_defaults_to_event_slug_folder(self):
        config = config_for_date(date(2026, 5, 28))
        store = SnapshotStore(event_slug=config.event_slug)

        self.assertEqual(
            store.root.as_posix(),
            "data/snapshots/highest-temperature-in-toronto-on-may-28-2026",
        )

    def test_external_market_registry_adds_market_without_code_edit(self):
        payload = {
            "schema_version": MARKET_REGISTRY_SCHEMA_VERSION,
            "markets": [
                {
                    "id": "phoenix",
                    "city_label": "Phoenix",
                    "slug_prefix": "highest-temperature-in-phoenix-on",
                    "timezone": "America/Phoenix",
                    "display_unit": "F",
                    "wu_history_id": "KPHX:9:US",
                    "icao": "KPHX",
                    "lat": 33.4343,
                    "lon": -112.0116,
                    "sources": ["wu_history", "wu_current", "metar", "weather_forecast", "open_meteo"],
                    "leading_obs": "metar",
                    "resolution_source": "wu_history",
                    "coastal": False,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "markets.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            external = load_external_registry(path)
            registry = build_registry(path)

        self.assertEqual(external["phoenix"].icao, "KPHX")
        self.assertEqual(external["phoenix"].resolution_source, "wu_history")
        self.assertIn("toronto", registry)
        self.assertEqual(registry["phoenix"].slug_prefix, "highest-temperature-in-phoenix-on")

    def test_external_market_registry_rejects_unknown_schema(self):
        payload = {"schema_version": "market_registry_v9", "markets": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "markets.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_external_registry(path)

    def test_builtin_markets_have_explicit_resolution_and_station_mapping(self):
        self.assertEqual(validate_market_registry(), [])

    def test_registry_validation_catches_resolution_source_not_fetched(self):
        registry = build_registry()
        bad = registry["toronto"].__class__(
            **{
                **registry["toronto"].__dict__,
                "resolution_source": "not_fetched",
            }
        )
        issues = validate_market_registry({**registry, "toronto": bad})

        self.assertEqual(issues[0]["field"], "resolution_source")


if __name__ == "__main__":
    unittest.main()
