import os
import sys
import unittest
from datetime import datetime, timezone
from weather.market.market_registry import spec_for_id  # noqa: E402
from weather.sources.marine_context import (  # noqa: E402
    COOPS_DATAGETTER_URL,
    active_marine_context_state,
    build_coops_params,
    derive_marine_context_features,
    fetch_marine_context_for_market,
    marine_context_backtest,
    merge_rows_by_time,
    normalize_coops_product,
    parse_ndbc_realtime_text,
    registry_for_market,
    render_marine_context_backtest_markdown,
    station_result,
)


NDBC_TEXT = """#YY  MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE
#yr  mo dy hr mn degT m/s  m/s m    sec sec degT hPa  degC degC degC nmi ft
2026 06 15 16 00 120 4.0 6.0 99.0 99 99 999 1012.0 19.0 15.0 14.0 99 99
"""


class TestMarineContext(unittest.TestCase):
    def test_registry_covers_coastal_and_lake_markets_only(self):
        self.assertTrue(registry_for_market("nyc"))
        self.assertTrue(registry_for_market("toronto"))
        self.assertTrue(registry_for_market("chicago"))
        self.assertEqual(registry_for_market("atlanta"), [])

    def test_coops_params_and_products_merge_by_time(self):
        spec = spec_for_id("nyc")
        station = registry_for_market("nyc")[0]
        params = build_coops_params(station["station_id"], "air_temperature", "2026-06-15")

        self.assertEqual(params["station"], station["station_id"])
        self.assertEqual(params["begin_date"], "20260615")
        self.assertEqual(params["time_zone"], "lst_ldt")

        rows = []
        rows.extend(normalize_coops_product(
            "air_temperature",
            {"data": [{"t": "2026-06-15 12:00", "v": "21.0"}]},
            spec,
            station,
            "2026-06-15",
        ))
        rows.extend(normalize_coops_product(
            "water_temperature",
            {"data": [{"t": "2026-06-15 12:00", "v": "18.0"}]},
            spec,
            station,
            "2026-06-15",
        ))
        rows.extend(normalize_coops_product(
            "wind",
            {"data": [{"t": "2026-06-15 12:00", "s": "5.0", "g": "7.0", "d": "135", "dr": "SE"}]},
            spec,
            station,
            "2026-06-15",
        ))
        merged = merge_rows_by_time(rows)

        self.assertEqual(len(merged), 1)
        row = merged[0]
        self.assertEqual(row["source"], "marine_context")
        self.assertAlmostEqual(row["air_temp_native"], 69.8)
        self.assertAlmostEqual(row["water_temp_native"], 64.4)
        self.assertEqual(row["wind_speed_kmh"], 18.0)
        self.assertEqual(row["wind_direction_degrees"], 135.0)

    def test_ndbc_realtime_parser_normalizes_missing_values_and_units(self):
        spec = spec_for_id("toronto")
        station = registry_for_market("toronto")[0]

        rows = parse_ndbc_realtime_text(NDBC_TEXT, spec, station, "2026-06-15")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["provider"], "ndbc")
        self.assertEqual(row["time"], "12:00")
        self.assertEqual(row["wind_direction_degrees"], 120.0)
        self.assertEqual(row["wind_speed_kmh"], 14.4)
        self.assertEqual(row["pressure_hpa"], 1012.0)
        self.assertEqual(row["air_temp_native"], 19.0)
        self.assertEqual(row["water_temp_native"], 15.0)
        self.assertIsNone(row["raw"].get("WVHT") if row.get("wave_height_m") else None)

    def test_station_result_marks_missing_and_stale_sources(self):
        spec = spec_for_id("toronto")
        station = registry_for_market("toronto")[0]
        rows = parse_ndbc_realtime_text(NDBC_TEXT, spec, station, "2026-06-15")

        fresh = station_result(
            station,
            rows,
            now=datetime(2026, 6, 15, 16, 30, tzinfo=timezone.utc),
        )
        stale = station_result(
            station,
            rows,
            now=datetime(2026, 6, 15, 18, 0, tzinfo=timezone.utc),
        )
        missing = station_result(
            station,
            [{**rows[0], "water_temp_native": None}],
            now=datetime(2026, 6, 15, 16, 30, tzinfo=timezone.utc),
        )

        self.assertTrue(fresh["usable"])
        self.assertFalse(fresh["missing_sensors"])
        self.assertTrue(stale["stale"])
        self.assertFalse(stale["usable"])
        self.assertIn("water_temperature", missing["missing_sensors"])

    def test_fetch_marine_context_for_market_collects_coops_and_ndbc(self):
        spec = spec_for_id("nyc")

        def fake_get_json(url, params):
            self.assertEqual(url, COOPS_DATAGETTER_URL)
            product = params["product"]
            if product == "wind":
                return {"data": [{"t": "2026-06-15 12:00", "s": "5.0", "g": "7.0", "d": "135"}]}
            if product == "air_temperature":
                return {"data": [{"t": "2026-06-15 12:00", "v": "21.0"}]}
            if product == "water_temperature":
                return {"data": [{"t": "2026-06-15 12:00", "v": "18.0"}]}
            if product == "air_pressure":
                return {"data": [{"t": "2026-06-15 12:00", "v": "1013.0"}]}
            if product == "humidity":
                return {"data": [{"t": "2026-06-15 12:00", "v": "82"}]}
            return {"data": []}

        payload = fetch_marine_context_for_market(
            spec,
            "2026-06-15",
            get_json=fake_get_json,
            get_text=lambda _url: NDBC_TEXT,
            now=datetime(2026, 6, 15, 16, 30, tzinfo=timezone.utc),
        )

        self.assertTrue(payload["available"])
        self.assertGreaterEqual(payload["usable_station_count"], 1)
        self.assertEqual(payload["schema_version"], "marine_context_v0.1")
        self.assertEqual(len(payload["payload_hash"]), 40)

    def test_derive_marine_features_flags_onshore_cool_suppression(self):
        marine_context = {
            "stations": [{
                "usable": True,
                "latest_age_minutes": 30,
                "missing_sensors": [],
                "distance_km": 10,
                "onshore_direction_min": 45.0,
                "onshore_direction_max": 165.0,
                "latest": {
                    "water_temp_native": 60.0,
                    "air_temp_native": 70.0,
                    "wind_speed_kmh": 18.0,
                    "wind_direction_degrees": 135.0,
                    "humidity": 82.0,
                },
                "rows": [
                    {"minute_of_day": 660, "wind_direction_degrees": 300.0},
                    {"minute_of_day": 780, "wind_direction_degrees": 135.0},
                ],
            }],
        }

        features = derive_marine_context_features(
            marine_context,
            current_temp_native=85.0,
            forecast_high_native=88.0,
            cutoff_hour=12,
            wall_minute=780,
        )

        self.assertEqual(features["marine_station_count"], 1.0)
        self.assertEqual(features["marine_latest_age_minutes"], 30)
        self.assertEqual(features["marine_water_minus_air_temp"], -10.0)
        self.assertEqual(features["marine_water_minus_forecast_high"], -28.0)
        self.assertEqual(features["marine_air_minus_current_temp"], -15.0)
        self.assertEqual(features["marine_onshore_flow"], 1.0)
        self.assertEqual(features["marine_offshore_flow"], 0.0)
        self.assertEqual(features["marine_onshore_water_minus_forecast_high"], -28.0)
        self.assertEqual(features["marine_onshore_cooling_potential"], 28.0)
        self.assertEqual(features["marine_post_cutoff_onshore_reversal"], 1.0)
        self.assertEqual(features["marine_breeze_risk"], 1.0)
        self.assertEqual(features["marine_layer_suppression"], 1.0)

    def test_active_state_requires_usable_station_gate(self):
        inactive = active_marine_context_state({"stations": [{"usable": False, "latest": {}}]})
        active = active_marine_context_state({
            "market": "nyc",
            "stations": [{
                "station_id": "8518750",
                "usable": True,
                "latest_age_minutes": 20,
                "missing_sensors": [],
                "distance_km": 10,
                "onshore_direction_min": 45.0,
                "onshore_direction_max": 165.0,
                "latest": {
                    "water_temp_native": 60.0,
                    "air_temp_native": 70.0,
                    "wind_speed_kmh": 18.0,
                    "wind_direction_degrees": 135.0,
                    "humidity": 82.0,
                },
                "rows": [],
            }],
        }, current_temp_native=85.0, forecast_high_native=88.0)

        self.assertIsNone(inactive)
        self.assertTrue(active["active"])
        self.assertEqual(active["regime"], "marine_layer_suppression")
        self.assertEqual(active["station_ids"], ["8518750"])
        self.assertEqual(active["water_minus_forecast_high"], -28.0)
        self.assertEqual(active["onshore_cooling_potential"], 28.0)

    def test_backtest_summarizes_marine_regimes_against_settlement_and_forecast_misses(self):
        payload = marine_context_backtest([
            {
                "market": "nyc",
                "features": {"marine_station_count": 1, "marine_breeze_risk": 1.0},
                "settlement_error": -1.0,
                "forecast_error": 2.0,
                "high_has_stood_reversal": True,
            },
            {
                "market": "nyc",
                "features": {"marine_station_count": 1, "marine_onshore_flow": 1.0},
                "settlement_error": 0.0,
                "forecast_error": -1.0,
                "high_has_stood_reversal": False,
            },
        ])
        by_regime = {row["regime"]: row for row in payload["regimes"]}
        markdown = render_marine_context_backtest_markdown(payload)

        self.assertEqual(payload["summary"]["rows"], 2)
        self.assertEqual(by_regime["breeze_risk"]["forecast_overcall_rate"], 1.0)
        self.assertEqual(by_regime["breeze_risk"]["settlement_miss_rate"], 1.0)
        self.assertEqual(by_regime["onshore_flow"]["settlement_miss_rate"], 0.0)
        self.assertIn("breeze_risk", markdown)


if __name__ == "__main__":
    unittest.main()
