import os
import sys
import unittest
from datetime import datetime, timezone
from weather.market.market_registry import spec_for_id  # noqa: E402
from weather.sources.eccc_gridded import (  # noqa: E402
    OPEN_METEO_GEM_URL,
    build_hrdps_datamart_url,
    build_open_meteo_gem_params,
    derive_eccc_gridded_features,
    fetch_open_meteo_gem_for_market,
    normalize_open_meteo_gem_payload,
    parse_hrdps_datamart_filename,
    probe_hrdps_grib_payload,
    render_eccc_toronto_score_markdown,
    score_eccc_toronto_features,
)


def gem_payload():
    return {
        "generationtime_ms": 1.5,
        "hourly": {
            "time": ["2026-06-15T11:00", "2026-06-15T12:00", "2026-06-15T13:00"],
            "temperature_2m_gem_seamless": [24.0, 25.0, 27.0],
            "temperature_2m_gem_global": [23.0, 24.0, 26.0],
            "temperature_2m_gem_regional": [25.0, 26.0, 28.0],
            "wind_speed_10m_gem_seamless": [12.0, 14.0, 18.0],
            "wind_speed_10m_gem_global": [10.0, 11.0, 15.0],
            "wind_speed_10m_gem_regional": [11.0, 13.0, 17.0],
            "wind_direction_10m_gem_seamless": [240.0, 250.0, 120.0],
            "wind_direction_10m_gem_global": [240.0, 250.0, 130.0],
            "wind_direction_10m_gem_regional": [240.0, 250.0, 115.0],
            "wind_gusts_10m_gem_seamless": [20.0, 24.0, 30.0],
            "wind_gusts_10m_gem_global": [18.0, 22.0, 28.0],
            "wind_gusts_10m_gem_regional": [19.0, 23.0, 29.0],
            "cloud_cover_gem_seamless": [30.0, 40.0, 70.0],
            "cloud_cover_gem_global": [35.0, 45.0, 65.0],
            "cloud_cover_gem_regional": [25.0, 35.0, 75.0],
            "precipitation_gem_seamless": [0.0, 0.0, 0.2],
            "precipitation_gem_global": [0.0, 0.0, 0.1],
            "precipitation_gem_regional": [0.0, 0.0, 0.3],
            "relative_humidity_2m_gem_seamless": [55.0, 60.0, 78.0],
            "relative_humidity_2m_gem_global": [50.0, 58.0, 72.0],
            "relative_humidity_2m_gem_regional": [52.0, 62.0, 80.0],
            "surface_pressure_gem_seamless": [1005.0, 1004.0, 1003.0],
            "surface_pressure_gem_global": [1006.0, 1005.0, 1004.0],
            "surface_pressure_gem_regional": [1005.5, 1004.5, 1003.5],
            "temperature_925hPa_gem_seamless": [21.0, 22.0, 23.0],
            "temperature_925hPa_gem_global": [20.0, 21.0, 22.0],
            "temperature_925hPa_gem_regional": [21.5, 22.5, 23.5],
            "temperature_850hPa_gem_seamless": [15.0, 16.0, 17.0],
            "temperature_850hPa_gem_global": [14.0, 15.0, 16.0],
            "temperature_850hPa_gem_regional": [15.5, 16.5, 17.5],
            "geopotential_height_500hPa_gem_seamless": [5700.0, 5710.0, 5720.0],
            "geopotential_height_500hPa_gem_global": [5690.0, 5700.0, 5710.0],
            "geopotential_height_500hPa_gem_regional": [5705.0, 5715.0, 5725.0],
        },
    }


class TestEcccGridded(unittest.TestCase):
    def test_open_meteo_gem_params_request_overlapping_item74_fields(self):
        spec = spec_for_id("toronto")
        params = build_open_meteo_gem_params(spec)

        self.assertEqual(params["models"], "gem_seamless,gem_global,gem_regional")
        self.assertIn("temperature_925hPa", params["hourly"])
        self.assertIn("geopotential_height_500hPa", params["hourly"])
        self.assertEqual(params["timezone"], "America/Toronto")

    def test_normalize_open_meteo_gem_payload_model_columns(self):
        spec = spec_for_id("toronto")
        data = normalize_open_meteo_gem_payload(
            gem_payload(),
            spec,
            "2026-06-15",
            now=datetime(2026, 6, 15, 10, 0, tzinfo=spec.tz),
        )

        self.assertTrue(data["available"])
        self.assertEqual(data["day_model_highs"]["gem_seamless"], 27.0)
        self.assertEqual(data["day_model_highs"]["gem_global"], 26.0)
        self.assertEqual(data["day_model_highs"]["gem_regional"], 28.0)
        self.assertEqual(data["day_max_c"], 27.0)
        self.assertEqual(data["day_high_spread"], 2.0)
        row = data["day_rows"][1]
        self.assertEqual(row["models"]["gem_seamless"]["wind_gust_kmh"], 24.0)
        self.assertEqual(row["models"]["gem_regional"]["temperature_850hpa"], 16.5)
        self.assertEqual(row["source_url"], OPEN_METEO_GEM_URL)
        self.assertEqual(row["payload_hash"], data["payload_hash"])
        self.assertEqual(row["grid"], "point")
        self.assertEqual(row["domain"], "open_meteo_gem")
        self.assertIsNone(row["run_time"])
        self.assertIsNone(row["forecast_hour"])
        self.assertEqual(row["run_time_status"], "not_exposed_by_open_meteo")
        self.assertEqual(row["fetch_lag_status"], "not_exposed_by_open_meteo")

    def test_fetch_open_meteo_gem_is_toronto_only(self):
        nyc = spec_for_id("nyc")
        payload = fetch_open_meteo_gem_for_market(
            nyc,
            "2026-06-15",
            get_json=lambda _url, _params: gem_payload(),
        )

        self.assertFalse(payload["available"])
        self.assertIn("Toronto-only", payload["reason"])

    def test_hrdps_datamart_url_parse_and_probe_metadata(self):
        url = build_hrdps_datamart_url(
            datetime(2026, 6, 15, 18, tzinfo=timezone.utc),
            1,
            variable="TMP",
            level="AGL-2m",
        )
        parsed = parse_hrdps_datamart_filename(url)
        probe = probe_hrdps_grib_payload(
            b"GRIB\x00\x00\x00\x02payload",
            source_url=url,
            object_key=url.split("/")[-1],
            fetched_at="2026-06-15T19:00:00+00:00",
        )

        self.assertIn("/18/001/", url)
        self.assertTrue(url.endswith("20260615T18Z_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PT001H.grib2"))
        self.assertEqual(parsed["run_time_utc"], "2026-06-15T18:00:00+00:00")
        self.assertEqual(parsed["valid_time_utc"], "2026-06-15T19:00:00+00:00")
        self.assertEqual(probe["schema_version"], "eccc_gridded_v0.1")
        self.assertEqual(probe["model"], "HRDPS")
        self.assertEqual(probe["product"], "TMP")
        self.assertEqual(probe["level"], "AGL-2m")
        self.assertEqual(probe["forecast_hour"], 1)
        self.assertEqual(probe["grid"], "RLatLon0.0225")
        self.assertEqual(probe["domain"], "continental")
        self.assertEqual(probe["source_url"], url)
        self.assertEqual(probe["fetch_lag_minutes"], 60.0)
        self.assertEqual(probe["fetch_lag_basis"], "fetched_at_minus_run_time")

    def test_derive_eccc_gridded_features(self):
        spec = spec_for_id("toronto")
        data = normalize_open_meteo_gem_payload(
            gem_payload(),
            spec,
            "2026-06-15",
            now=datetime(2026, 6, 15, 10, 0, tzinfo=spec.tz),
        )
        features = derive_eccc_gridded_features(
            data,
            forecast_high=26.0,
            open_meteo_high=25.0,
            weather_high=28.0,
            eccc_city_high=27.0,
            cutoff_hour=12,
            wall_minute=720,
        )

        self.assertEqual(features["eccc_gem_high"], 27.0)
        self.assertEqual(features["eccc_gem_seamless_high"], 27.0)
        self.assertEqual(features["eccc_gem_high_spread"], 2.0)
        self.assertEqual(features["eccc_gem_vs_forecast_high"], 1.0)
        self.assertEqual(features["eccc_gem_vs_open_meteo_high"], 2.0)
        self.assertEqual(features["eccc_gem_vs_weather_high"], -1.0)
        self.assertEqual(features["eccc_gem_vs_eccc_city_high"], 0.0)
        self.assertEqual(features["eccc_gem_gust_after_cutoff_max"], 30.0)
        self.assertAlmostEqual(features["eccc_gem_precip_after_cutoff_sum"], 0.6)
        self.assertEqual(features["eccc_gem_lake_breeze_wind_shift"], 1.0)
        self.assertAlmostEqual(features["eccc_gem_temperature_925hpa_mean"], 22.3333333333)
        self.assertAlmostEqual(features["eccc_gem_temperature_850hpa_mean"], 16.3333333333)

    def test_score_eccc_toronto_features_groups_toronto_only_cases(self):
        report = score_eccc_toronto_features(
            [
                {
                    "market": "toronto",
                    "local_date": "2026-06-15",
                    "forecast_high": 26.0,
                    "eccc_gem_high": 24.0,
                    "eccc_gem_vs_forecast_high": -2.0,
                    "eccc_gem_high_spread": 2.5,
                    "eccc_gem_lake_breeze_wind_shift": 1.0,
                    "eccc_gem_precip_after_cutoff_sum": 0.2,
                    "settlement_high": 24.0,
                },
                {
                    "market": "toronto",
                    "local_date": "2026-06-16",
                    "forecast_high": 28.0,
                    "eccc_gem_high": 29.0,
                    "eccc_gem_vs_forecast_high": 1.0,
                    "settlement_high": 30.0,
                },
                {
                    "market": "nyc",
                    "forecast_high": 90.0,
                    "eccc_gem_high": 91.0,
                    "settlement_high": 91.0,
                },
            ],
            min_scored_rows=2,
        )
        cases = {row["case"]: row for row in report["cases"]}
        markdown = render_eccc_toronto_score_markdown(report)

        self.assertEqual(report["summary"]["input_rows"], 3)
        self.assertEqual(report["summary"]["toronto_rows"], 2)
        self.assertEqual(report["summary"]["skipped_non_toronto_rows"], 1)
        self.assertEqual(report["summary"]["scored_rows"], 2)
        self.assertEqual(report["summary"]["mean_abs_error_improvement"], 1.5)
        self.assertTrue(report["expansion_gate"]["eligible_for_canadian_expansion_review"])
        self.assertEqual(cases["lake_breeze_wind_shift"]["scored_rows"], 1)
        self.assertEqual(cases["lake_breeze_wind_shift"]["mean_abs_error_improvement"], 2.0)
        self.assertIn("gem_cooler_than_consensus", cases)
        self.assertIn("lake_breeze_wind_shift", markdown)


if __name__ == "__main__":
    unittest.main()
