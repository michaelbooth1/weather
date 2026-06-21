import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from weather.model.toronto_model import TorontoHighTempModel
from weather.model.model_features import (
    build_us_guidance_replay_diagnostics,
    render_us_guidance_replay_diagnostics_markdown,
)


def _wu_row(time, temp):
    return {
        "time": time, "datetime": f"2026-05-30T{time}:00-04:00", "temp_c": temp,
        "dewpoint_c": 10.0, "humidity": 60.0, "pressure": 1015.0,
        "clouds": "Partly Cloudy", "condition": "Partly Cloudy",
        "wind": "SW", "wind_kmh": 15.0, "gust_kmh": None,
    }


def _sources(rows, day_max_c=None):
    s = {"wu_history": {"ok": True, "data": {
        "rows": rows, "latest": rows[-1] if rows else None,
        "max_c": max((r["temp_c"] for r in rows), default=None),
    }}}
    if day_max_c is not None:
        s["open_meteo"] = {"ok": True, "data": {"rows": [], "day_max_c": day_max_c}}
    return s


class TestForecastFeatureExtraction(unittest.TestCase):
    """The forecast feature must be defined identically to training:
    forecast_high = Open-Meteo forecasted daily max; gap = forecast_high - high_so_far."""

    def setUp(self):
        self.m = TorontoHighTempModel(target_date="2026-05-30")

    def test_forecast_gap_is_forecast_minus_high_so_far(self):
        rows = [_wu_row("07:00", 11.0), _wu_row("09:00", 13.0)]
        feats = self.m.extract_live_features(_sources(rows, day_max_c=21.0), cutoff_hour=9)
        self.assertEqual(feats["forecast_high"], 21.0)
        self.assertAlmostEqual(feats["forecast_gap"], 21.0 - feats["high_so_far"])

    def test_missing_open_meteo_yields_none(self):
        rows = [_wu_row("09:00", 13.0)]
        feats = self.m.extract_live_features(_sources(rows, day_max_c=None), cutoff_hour=9)
        self.assertIsNone(feats["forecast_high"])
        self.assertIsNone(feats["forecast_gap"])

    def test_forecast_day_max_preferred_over_truncated_rows(self):
        self.assertEqual(
            self.m.forecast_day_max({
                "day_max_c": 21.1,
                "rows": [{"temp_c": 16.2}],
            }),
            21.1,
        )

    def test_open_meteo_fetch_requests_expanded_environmental_fields(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        payload = {
            "hourly": {
                "time": ["2026-05-30T12:00"],
                "temperature_2m": [25.0],
                "cloud_cover": [40],
                "cloud_cover_low": [10],
                "cloud_cover_mid": [20],
                "cloud_cover_high": [30],
                "wind_speed_10m": [12],
                "shortwave_radiation": [700],
                "cape": [60],
                "temperature_925hPa": [21],
                "temperature_850hPa": [15],
                "geopotential_height_500hPa": [5730],
                "direct_radiation": [550],
                "diffuse_radiation": [160],
                "wind_gusts_10m": [28],
                "visibility": [18000],
                "precipitation_probability": [0],
                "precipitation": [0.0],
                "soil_temperature_0cm": [24],
                "soil_moisture_0_to_1cm": [0.23],
                "vapour_pressure_deficit": [0.8],
                "et0_fao_evapotranspiration": [0.2],
            }
        }
        captured = {}

        def fake_get_json(url, params):
            captured["url"] = url
            captured["params"] = params
            return payload

        model.get_json = fake_get_json

        data = model.fetch_open_meteo()

        hourly = captured["params"]["hourly"]
        for field in (
            "cape",
            "temperature_925hPa",
            "temperature_850hPa",
            "geopotential_height_500hPa",
            "direct_radiation",
            "diffuse_radiation",
            "wind_gusts_10m",
            "visibility",
            "precipitation_probability",
            "precipitation",
            "soil_temperature_0cm",
            "soil_moisture_0_to_1cm",
            "vapour_pressure_deficit",
            "et0_fao_evapotranspiration",
        ):
            self.assertIn(field, hourly)
        row = data["day_rows"][0]
        self.assertEqual(row["cape"], 60.0)
        self.assertEqual(row["temperature_925hpa"], 21.0)
        self.assertEqual(row["geopotential_height_500hpa"], 5730.0)
        self.assertEqual(row["direct_radiation"], 550.0)
        self.assertEqual(row["wind_gust_kmh"], 28.0)
        self.assertEqual(row["precipitation_probability"], 0.0)
        self.assertEqual(row["precipitation"], 0.0)
        self.assertEqual(row["soil_moisture_0_to_1cm"], 0.23)
        self.assertEqual(data["day_max_c"], 25.0)

    def test_open_meteo_air_quality_fetch_parses_aerosol_rows(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        payload = {
            "hourly": {
                "time": ["2026-05-30T12:00", "2026-05-30T13:00"],
                "pm2_5": [18.0, 36.0],
                "pm10": [24.0, 55.0],
                "aerosol_optical_depth": [0.16, 0.42],
                "dust": [3.0, 6.0],
                "us_aqi": [58, 104],
                "european_aqi": [24, 62],
            }
        }
        captured = {}

        def fake_get_json(url, params):
            captured["url"] = url
            captured["params"] = params
            return payload

        model.get_json = fake_get_json

        data = model.fetch_open_meteo_air_quality()

        self.assertEqual(captured["url"], "https://air-quality-api.open-meteo.com/v1/air-quality")
        self.assertEqual(captured["params"]["timezone"], "America/Toronto")
        hourly = captured["params"]["hourly"]
        for field in ("pm2_5", "pm10", "aerosol_optical_depth", "dust", "us_aqi", "european_aqi"):
            self.assertIn(field, hourly)
        row = data["day_rows"][1]
        self.assertEqual(row["time"], "13:00")
        self.assertEqual(row["pm2_5"], 36.0)
        self.assertEqual(row["pm10"], 55.0)
        self.assertEqual(row["aerosol_optical_depth"], 0.42)
        self.assertEqual(row["dust"], 6.0)
        self.assertEqual(row["us_aqi"], 104.0)
        self.assertEqual(data["provenance"]["provider"], "open_meteo_air_quality")
        self.assertIn("CAMS", data["provenance"]["upstream"])

    def test_open_meteo_air_quality_fetches_with_open_meteo_family(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        calls = []

        def fake_fetch_source_group(fetchers, max_workers=None):
            calls.append((tuple(fetchers), max_workers))
            return {}

        model.fetch_source_group = fake_fetch_source_group
        model.blend_with_last_good = lambda sources: sources

        model.fetch_live_sources()

        open_meteo_call = next(call for call in calls if "open_meteo" in call[0])
        self.assertIn("open_meteo_air_quality", open_meteo_call[0])
        self.assertIn("open_meteo_global_models", open_meteo_call[0])
        self.assertEqual(open_meteo_call[1], 1)

    def test_us_markets_fetch_nbm_probabilistic_tmax_with_official_guidance(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        calls = []

        def fake_fetch_source_group(fetchers, max_workers=None):
            calls.append((tuple(fetchers), max_workers))
            return {}

        model.fetch_source_group = fake_fetch_source_group
        model.blend_with_last_good = lambda sources: sources

        model.fetch_live_sources()

        regular_call = next(call for call in calls if "nws_grid" in call[0])
        self.assertIn("nbm_probabilistic_tmax", regular_call[0])

    def test_nbm_probabilistic_tmax_fetch_parses_station_bulletin(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        sample = """
 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
UTC    00  12| 00  12
FHR    24  36| 48  60
TXNMN  84  68| 79  68
TXNSD   2   2|  4   3
TXNP1  81  64| 73  63
TXNP2  82  66| 76  66
TXNP5  84  68| 80  69
TXNP7  85  69| 82  71
TXNP9  86  70| 84  72
"""
        seen_urls = []

        def fake_get_text(url):
            seen_urls.append(url)
            return sample

        model.get_text = fake_get_text
        cycle = datetime(2026, 5, 30, 0, tzinfo=timezone.utc)

        with patch("weather.model.model_sources.nbp_cycle_candidates", return_value=[cycle]):
            payload = model.fetch_nbm_probabilistic_tmax()

        self.assertEqual(seen_urls, ["https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20260530/00/text/blend_nbptx.t00z"])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["station_id"], "KLGA")
        self.assertEqual(payload["forecast_hour"], 24)
        self.assertEqual(payload["percentiles"]["10"], 81.0)
        self.assertEqual(payload["percentiles"]["50"], 84.0)
        self.assertEqual(payload["percentiles"]["90"], 86.0)
        self.assertEqual(payload["day_max_native"], 84.0)
        self.assertEqual(payload["iqr"], 3.0)
        self.assertEqual(payload["p10_p90_spread"], 5.0)
        self.assertFalse(payload["historical_archive_available"])
        self.assertEqual(payload["tried_urls"], seen_urls)

    def test_nws_grid_fetch_parses_grid_rows_and_metadata(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        model.cached_nws_grid_metadata = lambda points_url, headers: {
            "forecastGridData": "https://api.weather.gov/gridpoints/OKX/33,37",
            "gridId": "OKX",
            "gridX": 33,
            "gridY": 37,
        }
        payload = {
            "properties": {
                "generatedAt": "2026-05-30T10:00:00+00:00",
                "updateTime": "2026-05-30T10:05:00+00:00",
                "temperature": {"uom": "wmoUnit:degC", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 26.0},
                ]},
                "maxTemperature": {"uom": "wmoUnit:degC", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT12H", "value": 31.0},
                ]},
                "dewpoint": {"uom": "wmoUnit:degC", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 15.0},
                ]},
                "relativeHumidity": {"uom": "wmoUnit:percent", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 55},
                ]},
                "skyCover": {"uom": "wmoUnit:percent", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 70},
                ]},
                "windDirection": {"uom": "wmoUnit:degree_(angle)", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 180},
                ]},
                "windSpeed": {"uom": "wmoUnit:km_h-1", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 18},
                ]},
                "probabilityOfPrecipitation": {"uom": "wmoUnit:percent", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 0},
                ]},
                "quantitativePrecipitation": {"uom": "wmoUnit:mm", "values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": 0.0},
                ]},
                "weather": {"values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": []},
                ]},
                "hazards": {"values": [
                    {"validTime": "2026-05-30T12:00:00-04:00/PT1H", "value": [
                        {"phenomenon": "HT", "significance": "Y"},
                    ]},
                ]},
            }
        }

        model.get_json = lambda url, params, headers=None: payload

        data = model.fetch_nws_grid_forecast()

        self.assertEqual(data["url"], "https://api.weather.gov/gridpoints/OKX/33,37")
        self.assertEqual(data["grid_metadata"]["gridId"], "OKX")
        self.assertEqual(data["row_count"], 1)
        self.assertEqual(len(data["payload_hash"]), 40)
        self.assertIsNotNone(data["fetched_at"])
        self.assertIsNotNone(data["run_age_hours"])
        self.assertFalse(data["historical_archive_available"])
        self.assertIn("nws_grid_run_age_hours", data["live_only_fields"])
        row = data["day_rows"][0]
        self.assertAlmostEqual(row["temp_native"], 78.8)
        self.assertAlmostEqual(row["max_temp_native"], 87.8)
        self.assertEqual(row["precipitation_probability"], 0.0)
        self.assertEqual(row["quantitative_precipitation"], 0.0)
        self.assertEqual(row["hazards_count"], 1)
        self.assertAlmostEqual(data["day_max_c"], 87.8)

    def test_open_meteo_multimodel_fetch_parses_model_columns(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        payload = {
            "generationtime_ms": 1.2,
            "hourly": {
                "time": ["2026-05-30T12:00", "2026-05-30T13:00"],
                "temperature_2m_gfs_seamless": [84, 85],
                "temperature_2m_ncep_hrrr_conus": [86, 87],
                "temperature_2m_ncep_nbm_conus": [89, 90],
                "temperature_2m_ncep_nam_conus": [85, 86],
                "direct_radiation_ncep_hrrr_conus": [500, 550],
                "cape_ncep_nbm_conus": [100, 120],
            },
        }
        captured = {}

        def fake_get_json(url, params):
            captured["url"] = url
            captured["params"] = params
            return payload

        model.get_json = fake_get_json

        data = model.fetch_open_meteo_multimodel()

        self.assertEqual(captured["url"], "https://api.open-meteo.com/v1/gfs")
        self.assertIn("direct_radiation", captured["params"]["hourly"])
        self.assertIn("temperature_925hPa", captured["params"]["hourly"])
        self.assertEqual(
            captured["params"]["models"],
            "gfs_seamless,ncep_hrrr_conus,ncep_nbm_conus,ncep_nam_conus",
        )
        self.assertEqual(data["day_model_highs"]["ncep_nbm_conus"], 90.0)
        self.assertEqual(data["day_model_highs"]["gfs_seamless"], 85.0)
        self.assertEqual(data["day_high_spread"], 5.0)
        self.assertEqual(data["day_rows"][0]["model_temp_spread"], 5.0)
        self.assertFalse(data["historical_archive_available"])
        self.assertEqual(data["model_run_age_status"], "not_exposed_by_open_meteo_gfs")
        self.assertEqual(data["run_to_run_change_status"], "requires_previous_run_archive")
        self.assertIn("open_meteo_nbm_hrrr_disagreement_after_cutoff", data["live_only_fields"])
        self.assertEqual(
            data["day_rows"][0]["models"]["ncep_hrrr_conus"]["direct_radiation"],
            500.0,
        )
        self.assertEqual(data["day_rows"][1]["models"]["ncep_nbm_conus"]["cape"], 120.0)

    def test_open_meteo_global_models_fetch_parses_ecmwf_and_ml_members(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        payload = {
            "generationtime_ms": 1.4,
            "hourly": {
                "time": ["2026-05-30T12:00", "2026-05-30T13:00"],
                "temperature_2m_ecmwf_ifs025": [24.0, 25.0],
                "temperature_2m_ecmwf_aifs025": [25.0, 26.0],
                "temperature_2m_ncep_aigfs025": [23.0, 24.0],
                "temperature_2m_gfs_graphcast025": [26.0, 27.0],
            },
        }
        captured = {}

        def fake_get_json(url, params):
            captured["url"] = url
            captured["params"] = params
            return payload

        model.get_json = fake_get_json

        data = model.fetch_open_meteo_global_models()

        self.assertEqual(captured["url"], "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(
            captured["params"]["models"],
            "ecmwf_ifs025,ecmwf_aifs025,ncep_aigfs025,gfs_graphcast025",
        )
        self.assertEqual(data["day_model_highs"]["ecmwf_ifs025"], 25.0)
        self.assertEqual(data["day_model_highs"]["ecmwf_aifs025"], 26.0)
        self.assertEqual(data["day_model_highs"]["ncep_aigfs025"], 24.0)
        self.assertEqual(data["day_model_highs"]["gfs_graphcast025"], 27.0)
        self.assertEqual(data["day_max_c"], 25.5)
        self.assertEqual(data["day_high_spread"], 3.0)
        self.assertEqual(data["day_rows"][0]["model_temp_spread"], 3.0)
        self.assertIn("open_meteo_ecmwf_aifs_high_delta", data["live_only_fields"])
        self.assertFalse(data["historical_archive_available"])

    def test_live_features_include_us_grid_and_multimodel_guidance(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        rows = [_wu_row("07:00", 78.0), _wu_row("12:00", 80.0)]
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 80.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 86.0}},
            "nws_grid": {"ok": True, "data": {
                "day_max_c": 88.0,
                "run_age_hours": 1.5,
                "day_rows": [
                    {
                        "time": "12:00",
                        "precipitation_probability": 0.0,
                        "quantitative_precipitation": 0.0,
                        "sky_cover": 60.0,
                        "hazards_count": 1,
                    },
                    {
                        "time": "13:00",
                        "precipitation_probability": 40.0,
                        "quantitative_precipitation": 0.2,
                        "sky_cover": 80.0,
                        "hazards_count": 0,
                    },
                ],
            }},
            "nbm_probabilistic_tmax": {"ok": True, "data": {
                "available": True,
                "percentiles": {
                    "10": 81.0,
                    "25": 82.0,
                    "50": 84.0,
                    "75": 85.0,
                    "90": 86.0,
                },
                "mean_native": 84.0,
                "stddev_native": 2.0,
                "iqr": 3.0,
                "p10_p90_spread": 5.0,
            }},
            "open_meteo_multimodel": {"ok": True, "data": {
                "day_model_highs": {
                    "gfs_seamless": 84.0,
                    "ncep_hrrr_conus": 86.0,
                    "ncep_nbm_conus": 89.0,
                    "ncep_nam_conus": 85.0,
                },
                "previous_day_model_highs": {
                    "gfs_seamless": 83.0,
                    "ncep_hrrr_conus": 85.0,
                    "ncep_nbm_conus": 88.0,
                    "ncep_nam_conus": 84.0,
                },
                "model_run_age_hours": 2.0,
                "day_rows": [
                    {"time": "12:00", "models": {
                        "gfs_seamless": {"temp_native": 84.0},
                        "ncep_hrrr_conus": {"temp_native": 86.0},
                        "ncep_nbm_conus": {"temp_native": 89.0},
                        "ncep_nam_conus": {"temp_native": 85.0},
                    }},
                    {"time": "13:00", "models": {
                        "gfs_seamless": {"temp_native": 85.0},
                        "ncep_hrrr_conus": {"temp_native": 87.0},
                        "ncep_nbm_conus": {"temp_native": 90.0},
                        "ncep_nam_conus": {"temp_native": 86.0},
                    }},
                ],
            }},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 86.0)
        self.assertEqual(features["nws_grid_high"], 88.0)
        self.assertEqual(features["nws_grid_vs_forecast_high"], 2.0)
        self.assertEqual(features["nws_grid_pop_after_cutoff_max"], 40.0)
        self.assertEqual(features["nws_grid_qpf_after_cutoff_sum"], 0.2)
        self.assertEqual(features["nws_grid_sky_cover_after_cutoff_mean"], 70.0)
        self.assertEqual(features["nws_grid_hazard_count"], 1.0)
        self.assertEqual(features["nbm_prob_tmax_p10"], 81.0)
        self.assertEqual(features["nbm_prob_tmax_p50"], 84.0)
        self.assertEqual(features["nbm_prob_tmax_p90"], 86.0)
        self.assertEqual(features["nbm_prob_tmax_mean"], 84.0)
        self.assertEqual(features["nbm_prob_tmax_stddev"], 2.0)
        self.assertEqual(features["nbm_prob_tmax_iqr"], 3.0)
        self.assertEqual(features["nbm_prob_tmax_p10_p90_spread"], 5.0)
        self.assertEqual(features["nbm_prob_tmax_p50_vs_forecast_high"], -2.0)
        self.assertEqual(features["nbm_prob_tmax_p90_vs_forecast_high"], 0.0)
        self.assertAlmostEqual(features["nbm_prob_tmax_exceed_forecast_high"], 0.10)
        self.assertEqual(features["open_meteo_multimodel_high_spread"], 5.0)
        self.assertEqual(features["open_meteo_gfs_high_delta"], -2.0)
        self.assertEqual(features["open_meteo_hrrr_high_delta"], 0.0)
        self.assertEqual(features["open_meteo_nbm_high_delta"], 3.0)
        self.assertEqual(features["open_meteo_nam_high_delta"], -1.0)
        self.assertEqual(features["open_meteo_nbm_hrrr_disagreement"], 3.0)
        self.assertEqual(features["open_meteo_multimodel_next_3h_spread"], 5.0)
        self.assertEqual(features["nws_grid_run_age_hours"], 1.5)
        self.assertEqual(features["open_meteo_multimodel_run_age_hours"], 2.0)
        self.assertEqual(features["open_meteo_multimodel_run_to_run_high_change"], 1.0)
        self.assertEqual(features["open_meteo_nbm_hrrr_disagreement_after_cutoff"], 3.0)

    def test_live_features_include_open_meteo_global_model_guidance(self):
        model = TorontoHighTempModel(target_date="2026-05-30")
        rows = [_wu_row("07:00", 20.0), _wu_row("12:00", 24.0)]
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 24.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 30.0}},
            "open_meteo_global_models": {"ok": True, "data": {
                "day_max_c": 30.0,
                "day_max_native": 30.0,
                "day_model_highs": {
                    "ecmwf_ifs025": 28.0,
                    "ecmwf_aifs025": 30.0,
                    "ncep_aigfs025": 30.0,
                    "gfs_graphcast025": 32.0,
                },
                "previous_day_model_highs": {
                    "ecmwf_ifs025": 27.0,
                    "ecmwf_aifs025": 29.0,
                    "ncep_aigfs025": 29.0,
                    "gfs_graphcast025": 31.0,
                },
                "day_rows": [
                    {"time": "12:00", "models": {
                        "ecmwf_ifs025": {"temp_native": 26.0},
                        "ecmwf_aifs025": {"temp_native": 28.0},
                        "ncep_aigfs025": {"temp_native": 29.0},
                        "gfs_graphcast025": {"temp_native": 30.0},
                    }},
                    {"time": "13:00", "models": {
                        "ecmwf_ifs025": {"temp_native": 27.0},
                        "ecmwf_aifs025": {"temp_native": 29.0},
                        "ncep_aigfs025": {"temp_native": 30.0},
                        "gfs_graphcast025": {"temp_native": 31.0},
                    }},
                ],
            }},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 30.0)
        self.assertEqual(features["forecast_source_count"], 2)
        self.assertEqual(features["forecast_source_values"]["open_meteo_global_models"], 30.0)
        self.assertEqual(features["open_meteo_global_models_high_spread"], 4.0)
        self.assertEqual(features["open_meteo_ecmwf_ifs_high_delta"], -2.0)
        self.assertEqual(features["open_meteo_ecmwf_aifs_high_delta"], 0.0)
        self.assertEqual(features["open_meteo_ncep_aigfs_high_delta"], 0.0)
        self.assertEqual(features["open_meteo_gfs_graphcast_high_delta"], 2.0)
        self.assertEqual(features["open_meteo_ecmwf_ifs_aifs_disagreement"], 2.0)
        self.assertEqual(features["open_meteo_global_models_next_3h_spread"], 4.0)
        self.assertEqual(features["open_meteo_global_models_run_to_run_high_change"], 1.0)

    def test_us_guidance_replay_diagnostics_group_by_market_cutoff_and_regime(self):
        payload = build_us_guidance_replay_diagnostics([
            {
                "market": "nyc",
                "cutoff_hour": 12,
                "weather_regime": "hot_clear",
                "forecast_high": 86.0,
                "nws_grid_high": 88.0,
                "open_meteo_nbm_high_delta": 3.0,
                "open_meteo_hrrr_high_delta": 0.0,
                "settlement_high": 89.0,
            },
            {
                "market": "nyc",
                "cutoff_hour": 12,
                "weather_regime": "hot_clear",
                "forecast_high": 85.0,
                "nws_grid_high": 84.0,
                "open_meteo_nbm_high_delta": -1.0,
                "settlement_high": 84.0,
            },
        ])
        markdown = render_us_guidance_replay_diagnostics_markdown(payload)
        group = payload["groups"][0]

        self.assertEqual(payload["summary"]["scored_rows"], 2)
        self.assertEqual(group["market_id"], "nyc")
        self.assertEqual(group["cutoff_hour"], "12")
        self.assertEqual(group["weather_regime"], "hot_clear")
        self.assertEqual(group["sources"]["nws_grid"]["rows"], 2)
        self.assertEqual(group["sources"]["nws_grid"]["mean_abs_error"], 0.5)
        self.assertEqual(
            group["sources"]["open_meteo_nbm"]["mean_abs_error_improvement_vs_forecast"],
            2.0,
        )
        self.assertIn("open_meteo_nbm", markdown)

    def test_live_features_include_gated_marine_context(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        rows = [_wu_row("07:00", 78.0), _wu_row("12:00", 85.0)]

        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 85.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 88.0}},
            "marine_context": {"ok": True, "data": {
                "available": True,
                "stations": [{
                    "usable": True,
                    "latest_age_minutes": 25.0,
                    "missing_sensors": [],
                    "distance_km": 10.0,
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
            }},
        }, cutoff_hour=12, now=datetime(2026, 5, 30, 13, 0, tzinfo=model.spec.tz))

        self.assertEqual(features["marine_station_count"], 1.0)
        self.assertEqual(features["marine_latest_age_minutes"], 25.0)
        self.assertEqual(features["marine_water_minus_air_temp"], -10.0)
        self.assertEqual(features["marine_water_minus_forecast_high"], -28.0)
        self.assertEqual(features["marine_air_minus_current_temp"], -15.0)
        self.assertEqual(features["marine_onshore_flow"], 1.0)
        self.assertEqual(features["marine_onshore_water_minus_forecast_high"], -28.0)
        self.assertEqual(features["marine_onshore_cooling_potential"], 28.0)
        self.assertEqual(features["marine_post_cutoff_onshore_reversal"], 1.0)
        self.assertEqual(features["marine_breeze_risk"], 1.0)
        self.assertEqual(features["marine_layer_suppression"], 1.0)

    def test_live_features_include_mrms_precip_interruption(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="nyc")
        rows = [
            _wu_row("07:00", 78.0),
            _wu_row("10:00", 85.0),
            _wu_row("12:00", 85.0),
        ]

        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 85.0}},
            "mrms_precip": {"ok": True, "data": {
                "latest_object_age_minutes": 6.0,
                "rows": [
                    {"minute_of_day": 720, "precip_rate_mm_per_hr": 0.0},
                    {"minute_of_day": 735, "precip_rate_mm_per_hr": 18.0, "precip_detected": True},
                    {"minute_of_day": 755, "precip_rate_mm_per_hr": 6.0, "precip_detected": True},
                ],
            }},
        }, cutoff_hour=12, now=datetime(2026, 5, 30, 12, 45, tzinfo=model.spec.tz))

        self.assertEqual(features["mrms_row_count"], 3.0)
        self.assertEqual(features["mrms_source_lag_minutes"], 6.0)
        self.assertEqual(features["mrms_any_precip_last_15m"], 1.0)
        self.assertEqual(features["mrms_precip_since_cutoff_mm"], 0.8)
        self.assertEqual(features["mrms_max_rate_since_cutoff_mm_per_hr"], 18.0)
        self.assertEqual(features["mrms_convective_interruption"], 1.0)

    def test_live_features_include_eccc_gem_guidance_for_toronto(self):
        model = TorontoHighTempModel(target_date="2026-05-30", market_id="toronto")
        rows = [_wu_row("07:00", 18.0), _wu_row("12:00", 22.0)]
        gem_rows = [
            {"time": "12:00", "models": {
                "gem_seamless": {"wind_direction_degrees": 250.0, "wind_gust_kmh": 22.0, "cloud_cover": 40.0, "precipitation": 0.0},
                "gem_global": {"wind_direction_degrees": 250.0, "wind_gust_kmh": 20.0, "cloud_cover": 45.0, "precipitation": 0.0},
                "gem_regional": {"wind_direction_degrees": 250.0, "wind_gust_kmh": 21.0, "cloud_cover": 35.0, "precipitation": 0.0},
            }},
            {"time": "13:00", "models": {
                "gem_seamless": {"wind_direction_degrees": 120.0, "wind_gust_kmh": 30.0, "cloud_cover": 70.0, "precipitation": 0.2},
                "gem_global": {"wind_direction_degrees": 130.0, "wind_gust_kmh": 28.0, "cloud_cover": 65.0, "precipitation": 0.1},
                "gem_regional": {"wind_direction_degrees": 115.0, "wind_gust_kmh": 29.0, "cloud_cover": 75.0, "precipitation": 0.3},
            }},
        ]

        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 22.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 25.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"time": "13:00", "temp_c": 28.0}]}},
            "eccc_citypage": {"ok": True, "data": {"forecast_high_c": 27.0}},
            "eccc_gem": {"ok": True, "data": {
                "day_max_c": 27.0,
                "day_max_native": 27.0,
                "day_model_highs": {
                    "gem_seamless": 27.0,
                    "gem_global": 26.0,
                    "gem_regional": 28.0,
                },
                "day_rows": gem_rows,
            }},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 27.0)
        self.assertEqual(features["eccc_gem_high"], 27.0)
        self.assertEqual(features["eccc_gem_high_spread"], 2.0)
        self.assertEqual(features["eccc_gem_vs_forecast_high"], 0.0)
        self.assertEqual(features["eccc_gem_vs_open_meteo_high"], 2.0)
        self.assertEqual(features["eccc_gem_vs_weather_high"], -1.0)
        self.assertEqual(features["eccc_gem_vs_eccc_city_high"], 0.0)
        self.assertEqual(features["eccc_gem_gust_after_cutoff_max"], 30.0)
        self.assertAlmostEqual(features["eccc_gem_precip_after_cutoff_sum"], 0.6)
        self.assertEqual(features["eccc_gem_lake_breeze_wind_shift"], 1.0)

    def test_distribution_still_valid_with_forecast(self):
        rows = [_wu_row("07:00", 11.0), _wu_row("09:00", 13.0)]
        dist = self.m.estimate_distribution(_sources(rows, day_max_c=21.0))
        self.assertTrue(dist)
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
