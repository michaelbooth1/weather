import os
import sys
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from weather.market.market_config import (  # noqa: E402
    MarketConfig,
    config_for_date,
    config_from_event,
    date_from_event_slug,
    event_slug_for_date,
)
from weather.market.market_registry import (  # noqa: E402
    DEFAULT_MARKET_ID,
    MARKET_REGISTRY_SCHEMA_VERSION,
    REGISTRY,
    TORONTO,
    build_registry,
    load_external_registry,
    spec_for_id,
    validate_market_registry,
)
from weather.collection.snapshot_tracker import SnapshotStore  # noqa: E402
from weather.paths import data_path  # noqa: E402


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

    def test_only_absent_market_identity_defaults(self):
        self.assertIs(spec_for_id(), TORONTO)
        self.assertIs(spec_for_id(None), TORONTO)
        target = date(2026, 5, 28)
        self.assertEqual(config_for_date(target, None), config_for_date(target))
        self.assertEqual(config_for_date(target, None).market_id, DEFAULT_MARKET_ID)

    def test_explicit_invalid_ids_never_resolve_or_build_a_toronto_config(self):
        for market_id in ("nycc", "", " ", "\t\n", "NYC", " nyc", "nyc ", 0, False, [], {}):
            with self.subTest(market_id=market_id):
                for resolve in (
                    lambda: spec_for_id(market_id),
                    lambda: config_for_date("2026-05-28", market_id),
                    lambda: config_for_date(market_id=market_id),
                    lambda: event_slug_for_date("2026-05-28", market_id),
                ):
                    with self.assertRaisesRegex(ValueError, "unknown market id"):
                        resolve()

    def test_blank_external_registry_key_cannot_enable_an_empty_id(self):
        with patch.dict(REGISTRY, {"": TORONTO, " ": TORONTO}):
            for market_id in ("", " "):
                with self.subTest(market_id=market_id):
                    with self.assertRaisesRegex(ValueError, "unknown market id"):
                        spec_for_id(market_id)

    def test_market_identity_binds_native_units_timezone_and_event(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                # Toronto has entered June 1 while Los Angeles is still May 31.
                return cls(2026, 6, 1, 6, 30, tzinfo=timezone.utc).astimezone(tz)

        cases = (
            ("toronto", "C", "America/Toronto", date(2026, 6, 1), "june-1-2026"),
            ("los-angeles", "F", "America/Los_Angeles", date(2026, 5, 31), "may-31-2026"),
        )
        with patch.dict(os.environ, {"TORONTO_MARKET_DATE": ""}), patch(
            "weather.market.market_config.datetime", FixedDateTime
        ):
            for market_id, unit, zone, target, suffix in cases:
                with self.subTest(market_id=market_id):
                    config = config_for_date(market_id=market_id)
                    self.assertEqual(config.market_id, market_id)
                    self.assertEqual(config.spec.id, market_id)
                    self.assertEqual(config.spec.unit, unit)
                    self.assertEqual(config.spec.tz.key, zone)
                    self.assertEqual(config.target_date, target)
                    self.assertEqual(config.event_slug, f"highest-temperature-in-{market_id}-on-{suffix}")
                    self.assertEqual(config.polymarket_url, f"https://polymarket.com/event/{config.event_slug}")

    def test_direct_config_construction_rejects_inconsistent_identity(self):
        valid = config_for_date("2026-05-28", "nyc")
        for changes in (
            {"market_id": "toronto"},
            {"market_id": "nycc"},
            {"market_id": ""},
            {"target_date": date(2026, 5, 29)},
            {"event_slug": "highest-temperature-in-toronto-on-may-28-2026"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    MarketConfig(**{**valid.__dict__, **changes})

    def test_event_config_uses_exact_event_identity_and_date(self):
        for market_id in ("toronto", "nyc"):
            expected = config_for_date("2026-05-28", market_id)
            for event in (
                {"slug": expected.event_slug},
                {"eventSlug": expected.event_slug},
                {"slug": expected.event_slug, "eventSlug": expected.event_slug},
            ):
                with self.subTest(event=event):
                    self.assertEqual(config_from_event(event, fallback_date="2026-05-29"), expected)

    def test_absent_event_keeps_legacy_date_fallback(self):
        for event in (None, {}, {"slug": None, "eventSlug": None}):
            with self.subTest(event=event):
                self.assertEqual(config_from_event(event, "2026-05-28"), config_for_date("2026-05-28"))

    def test_explicit_unrecognized_event_never_defaults_or_repairs_the_slug(self):
        for slug in (
            "",
            " ",
            "highest-temperature-in-nycc-on-may-28-2026",
            "highest-temperature-in-nyc-on-february-30-2026",
            "highest-temperature-in-nyc-on-may-28",
            "prefix-highest-temperature-in-nyc-on-may-28-2026",
            "highest-temperature-in-nyc-on-may-28-2026-suffix",
            "highest-temperature-in-nyc-on-may-28-2026/highest-temperature-in-toronto-on-may-28-2026",
        ):
            with self.subTest(slug=slug):
                with self.assertRaisesRegex(ValueError, "unrecognized market event slug"):
                    config_from_event({"slug": slug}, fallback_date="2026-05-28")

    def test_event_config_rejects_conflicting_slug_fields(self):
        with self.assertRaisesRegex(ValueError, "conflicting event slug identities"):
            config_from_event({
                "slug": "highest-temperature-in-nyc-on-may-28-2026",
                "eventSlug": "highest-temperature-in-toronto-on-may-28-2026",
            })

    def test_legacy_diagnostic_readers_distinguish_absent_and_invalid_identity(self):
        from weather.market.taker_bot_tape_io import market_local_time
        from weather.market.taker_edge_permission import _row_local_hour

        timestamp = {"captured_at_utc": "2026-05-28T15:00:00+00:00"}
        for row in (timestamp, {**timestamp, "market_id": None}):
            with self.subTest(row=row):
                local, zone = market_local_time(row)
                self.assertEqual((local.hour, zone), (11, "America/Toronto"))
                self.assertEqual(_row_local_hour(row), 11)
        for market_id in ("", " ", "nycc"):
            with self.subTest(market_id=market_id):
                row = {**timestamp, "market_id": market_id}
                local, zone = market_local_time(row)
                self.assertEqual((local.hour, zone), (15, "UTC"))
                self.assertEqual(_row_local_hour(row), 15)

    def test_snapshot_store_defaults_to_event_slug_folder(self):
        config = config_for_date(date(2026, 5, 28))
        store = SnapshotStore(event_slug=config.event_slug)

        self.assertEqual(store.root, data_path("snapshots", config.event_slug))

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
