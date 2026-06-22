import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from weather.model.feature_store import (
    FEATURE_AUDIT_COLUMNS,
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    audit_row,
    build_historical_feature_record,
    build_live_feature_record,
    current_max_trust_features,
    expanded_open_meteo_promotion_gate,
    forecast_profile_missing_zero_report,
    forecast_profile_features,
    merge_forecast_air_quality_rows,
    render_forecast_profile_missing_zero_markdown,
    row_air_temp_native,
    row_dewpoint_native,
    row_forecast_high_native,
    row_max_native,
    row_max_since_7am_native,
    row_same_day_max_native,
    row_temp_native,
)
from weather.collection.snapshot_tracker import SnapshotStore
from weather.model.toronto_model import TORONTO_TZ, TorontoHighTempModel


class TestFeatureStore(unittest.TestCase):
    def test_live_feature_record_has_stable_schema(self):
        record = build_live_feature_record(
            "2026-05-28",
            12,
            datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ),
            "model-v",
            {
                "high_so_far": 20.0,
                "current_temp": 19.5,
                "forecast_gap": 2.0,
                "latest_wu_history_time": "12:53",
                "latest_wu_history_minute": 773,
                "latest_wu_history_temp": 20.0,
                "wind_group": "W-NW",
            },
        )

        self.assertEqual(record["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertEqual(record["cutoff_hour"], 12)
        self.assertEqual(record["forecast_gap"], 2.0)
        self.assertEqual(record["latest_wu_history_time"], "12:53")
        self.assertEqual(record["latest_wu_history_minute"], 773)
        self.assertEqual(record["latest_wu_history_temp"], 20.0)
        self.assertIn("wind_group", record)

    def test_audit_row_keeps_expected_columns(self):
        row = audit_row(
            {"snapshot_id": "s1", "event_slug": "event"},
            {"feature_schema_version": FEATURE_SCHEMA_VERSION, "high_so_far": 21.0},
        )

        self.assertEqual(set(row), set(FEATURE_AUDIT_COLUMNS))
        self.assertEqual(row["snapshot_id"], "s1")
        self.assertEqual(row["high_so_far"], 21.0)

    def test_native_accessors_prefer_native_fields_with_legacy_fallback(self):
        self.assertEqual(row_temp_native({"temp_native": 86.0, "temp_c": 30.0}), 86.0)
        self.assertEqual(row_temp_native({"temp_c": 30.0}), 30.0)
        self.assertEqual(row_air_temp_native({"air_temp_native": 87.0, "air_temp_c": 27.0}), 87.0)
        self.assertEqual(row_air_temp_native({"air_temp_c": 27.0}), 27.0)
        self.assertEqual(row_dewpoint_native({"dewpoint_native": 68.0, "dewpoint_c": 20.0}), 68.0)
        self.assertEqual(row_dewpoint_native({"dewpoint_c": 20.0}), 20.0)
        self.assertEqual(
            row_forecast_high_native({"forecast_high_native": 91.0, "forecast_high_c": 33.0}),
            91.0,
        )
        self.assertEqual(row_forecast_high_native({"forecast_high_c": 33.0}), 33.0)
        self.assertEqual(row_max_native({"max_native": 91.0, "max_c": 33.0}), 91.0)
        self.assertEqual(row_max_native({"max_c": 33.0}), 33.0)
        self.assertEqual(
            row_max_since_7am_native({"max_since_7am_native": 92.0, "max_since_7am_c": 34.0}),
            92.0,
        )
        self.assertEqual(row_max_since_7am_native({"max_since_7am_c": 34.0}), 34.0)
        self.assertEqual(
            row_same_day_max_native({"same_day_max_native": 90.0, "same_day_max_c": 32.0}),
            90.0,
        )
        self.assertEqual(row_same_day_max_native({"same_day_max_c": 32.0}), 32.0)

    def test_current_max_trust_features_quarantine_large_warm_gap(self):
        features = current_max_trust_features(
            93.0,
            history_max=83.0,
            current_temp=81.0,
            cutoff_hour=7,
            unit="F",
        )

        self.assertIsNone(features["trusted_current_max"])
        self.assertEqual(features["quarantined_current_max"], 93.0)
        self.assertEqual(features["current_max_quarantined_flag"], 1.0)
        self.assertEqual(features["current_max_disposition"], "quarantined")

    def test_live_feature_extraction_quarantines_f_market_startup_sentinel(self):
        model = TorontoHighTempModel(market_id="nyc", target_date="2026-06-20")
        rows = [{"time": "00:05", "minute_of_day": 5, "temp_native": 17.0}]

        features = model.extract_live_features(
            {
                "wu_history": {"ok": True, "data": {"rows": rows}},
                "wu_current": {"ok": True, "data": {}},
                "open_meteo": {"ok": True, "data": {"rows": [], "day_max_native": 83.0}},
            },
            cutoff_hour=0,
        )

        self.assertIsNone(features["high_so_far"])
        self.assertIsNone(features["current_temp"])
        self.assertIsNone(features["live_reading_temp"])
        self.assertEqual(features["startup_feature_quarantined_flag"], 1.0)
        self.assertIn("current_temp", features["startup_feature_quarantine_reason"])

    def test_forecast_profile_uses_native_temperature_alias(self):
        features = forecast_profile_features(
            forecast_rows=[
                {"time": "12:00", "temp_native": 90.0, "temp_c": 32.0},
                {"time": "16:00", "temp_native": 94.0, "temp_c": 34.0},
            ],
            cutoff_hour=12,
            high_so_far=88.0,
        )

        self.assertEqual(features["forecast_temp_12"], 90.0)
        self.assertEqual(features["forecast_temp_16"], 94.0)
        self.assertEqual(features["forecast_afternoon_slope"], 4.0)

    def test_forecast_profile_missing_zero_report_separates_missing_from_zero(self):
        report = forecast_profile_missing_zero_report(
            [
                {
                    "source": "open_meteo_historical_forecast",
                    "direct_radiation": 0.0,
                    "diffuse_radiation": None,
                    "precipitation_probability": 0.0,
                },
                {
                    "source": "open_meteo_historical_forecast",
                    "direct_radiation": None,
                    "diffuse_radiation": 120.0,
                    "precipitation_probability": 30.0,
                },
            ],
            fields=["direct_radiation", "diffuse_radiation", "precipitation_probability"],
        )
        by_field = {row["field"]: row for row in report["fields"]}
        markdown = render_forecast_profile_missing_zero_markdown(report)

        self.assertEqual(by_field["direct_radiation"]["present_rows"], 1)
        self.assertEqual(by_field["direct_radiation"]["missing_rows"], 1)
        self.assertEqual(by_field["direct_radiation"]["zero_rows"], 1)
        self.assertEqual(by_field["diffuse_radiation"]["nonzero_rows"], 1)
        self.assertEqual(by_field["precipitation_probability"]["zero_rows"], 1)
        self.assertEqual(by_field["precipitation_probability"]["nonzero_rows"], 1)
        self.assertIn("direct_radiation", markdown)

    def test_expanded_open_meteo_promotion_gate_requires_backfill_retrain_and_replay_lift(self):
        blocked = expanded_open_meteo_promotion_gate(
            backfill_status={"all_active_markets_backfilled": True},
            replay_report={"summary": {"scored_rows": 40}, "baseline": {"brier": 0.20}, "candidate": {"brier": 0.19}},
        )
        ok = expanded_open_meteo_promotion_gate(
            backfill_status={
                "all_active_markets_backfilled": True,
                "per_market_candidates_retrained": True,
                "pooled_candidate_retrained": True,
            },
            replay_report={"summary": {"scored_rows": 40}, "baseline": {"brier": 0.20}, "candidate": {"brier": 0.19}},
        )

        self.assertFalse(blocked["ok"])
        self.assertIn("per_market_retrain_not_complete", blocked["reasons"])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["status"], "promotable")

    def test_historical_builder_uses_native_temperature_aliases_for_anchors(self):
        rows = [
            {
                "time": "07:00",
                "minute_of_day": 420,
                "temperature_native": 70.0,
                "temp_c": 20.0,
                "dewpoint_native": 60.0,
                "humidity": 60.0,
                "pressure": 1015.0,
            },
            {
                "time": "10:00",
                "minute_of_day": 600,
                "target_temp_native": 78.0,
                "temp_c": 25.0,
                "dewpoint_native": 62.0,
                "humidity": 58.0,
                "pressure": 1014.5,
            },
            {
                "time": "12:00",
                "minute_of_day": 720,
                "temp_native": 82.0,
                "temp_c": 28.0,
                "dewpoint_native": 64.0,
                "humidity": 55.0,
                "pressure": 1014.0,
            },
        ]

        historical = build_historical_feature_record(
            "2026-06-07",
            rows,
            {"bucket": 82},
            12,
        )

        self.assertEqual(historical["current_temp"], 82.0)
        self.assertEqual(historical["high_so_far"], 82.0)
        self.assertEqual(historical["rise_from_7am"], 12.0)
        self.assertEqual(historical["warming_rate_2h"], 4.0)

    def test_model_build_returns_feature_vector(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        rows = [
            {"time": "07:00", "temp_c": 15.0, "dewpoint_c": 10.0, "humidity": 60.0, "pressure": 1015.0},
            {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
        ]
        built = model.build(
            {"slug": "highest-temperature-in-toronto-on-may-28-2026", "markets": []},
            live_sources={
                "wu_history": {"ok": True, "data": {"max_c": 20.0, "rows": rows}},
                "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
                "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            },
            historical_sources={},
            now=datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ),
        )

        self.assertEqual(built["feature_vector"]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertAlmostEqual(built["feature_vector"]["forecast_gap"], 3.0)

    def test_historical_builder_matches_live_feature_extraction(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        rows = [
            {
                "time": "07:00",
                "minute_of_day": 420,
                "temp_c": 15.0,
                "dewpoint_c": 10.0,
                "humidity": 60.0,
                "pressure": 1015.0,
                "wind": "W",
                "wind_kmh": 12.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "time": "09:00",
                "minute_of_day": 540,
                "temp_c": 18.0,
                "dewpoint_c": 10.5,
                "humidity": 58.0,
                "pressure": 1014.5,
                "wind": "W",
                "wind_kmh": 13.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "time": "12:00",
                "minute_of_day": 720,
                "temp_c": 20.0,
                "dewpoint_c": 11.0,
                "humidity": 55.0,
                "pressure": 1014.0,
                "wind": "W",
                "wind_kmh": 14.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
        ]
        live = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
        }, cutoff_hour=12)
        historical = build_historical_feature_record(
            "2026-05-28",
            rows,
            {"bucket": 20},
            12,
            forecast_high=23.0,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
        )

        for column in FEATURE_COLUMNS:
            self.assertEqual(historical[column], live[column], column)

    def test_forecast_profile_features_match_between_train_and_live(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        obs_rows = [
            {
                "time": "07:00",
                "minute_of_day": 420,
                "temp_c": 17.0,
                "dewpoint_c": 10.0,
                "humidity": 60.0,
                "pressure": 1015.0,
                "wind": "W",
                "wind_kmh": 12.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "time": "12:00",
                "minute_of_day": 720,
                "temp_c": 20.0,
                "dewpoint_c": 11.0,
                "humidity": 55.0,
                "pressure": 1014.0,
                "wind": "W",
                "wind_kmh": 14.0,
                "condition": "Clear",
                "clouds": "Clear",
            },
        ]
        forecast_rows = [
            {
                "time": "11:00",
                "temp_c": 21.0,
                "cloud_cover": 60.0,
                "low_cloud": 20.0,
                "mid_cloud": 30.0,
                "high_cloud": 40.0,
                "solar": 500.0,
                "direct_radiation": 400.0,
                "diffuse_radiation": 100.0,
                "precipitation": 0.0,
                "precipitation_probability": 5.0,
                "cape": 10.0,
                "temperature_925hpa": 18.0,
                "temperature_850hpa": 12.0,
                "geopotential_height_500hpa": 5700.0,
                "wind_gust_kmh": 20.0,
                "visibility": 20000.0,
                "soil_temperature_0cm": 19.0,
                "soil_moisture_0_to_1cm": 0.20,
                "vapour_pressure_deficit": 0.5,
                "et0_fao_evapotranspiration": 0.1,
            },
            {
                "time": "12:00",
                "temp_c": 22.0,
                "cloud_cover": 50.0,
                "low_cloud": 10.0,
                "mid_cloud": 25.0,
                "high_cloud": 50.0,
                "solar": 700.0,
                "direct_radiation": 500.0,
                "diffuse_radiation": 150.0,
                "precipitation": 0.0,
                "precipitation_probability": 0.0,
                "cape": 30.0,
                "temperature_925hpa": 19.0,
                "temperature_850hpa": 13.0,
                "geopotential_height_500hpa": 5710.0,
                "wind_gust_kmh": 22.0,
                "visibility": 20000.0,
                "soil_temperature_0cm": 20.0,
                "soil_moisture_0_to_1cm": 0.21,
                "vapour_pressure_deficit": 0.6,
                "et0_fao_evapotranspiration": 0.2,
            },
            {
                "time": "13:00",
                "temp_c": 24.0,
                "cloud_cover": 40.0,
                "low_cloud": 5.0,
                "mid_cloud": 20.0,
                "high_cloud": 60.0,
                "solar": 800.0,
                "direct_radiation": 600.0,
                "diffuse_radiation": 160.0,
                "precipitation": 0.2,
                "precipitation_probability": 20.0,
                "cape": 60.0,
                "temperature_925hpa": 20.0,
                "temperature_850hpa": 14.0,
                "geopotential_height_500hpa": 5720.0,
                "wind_gust_kmh": 28.0,
                "visibility": 15000.0,
                "soil_temperature_0cm": 21.0,
                "soil_moisture_0_to_1cm": 0.22,
                "vapour_pressure_deficit": 0.7,
                "et0_fao_evapotranspiration": 0.3,
            },
            {
                "time": "14:00",
                "temp_c": 25.0,
                "cloud_cover": 30.0,
                "low_cloud": 3.0,
                "mid_cloud": 15.0,
                "high_cloud": 55.0,
                "solar": 900.0,
                "direct_radiation": 700.0,
                "diffuse_radiation": 170.0,
                "precipitation": 0.0,
                "precipitation_probability": 40.0,
                "cape": 90.0,
                "temperature_925hpa": 21.0,
                "temperature_850hpa": 15.0,
                "geopotential_height_500hpa": 5730.0,
                "wind_gust_kmh": 32.0,
                "visibility": 10000.0,
                "soil_temperature_0cm": 22.0,
                "soil_moisture_0_to_1cm": 0.23,
                "vapour_pressure_deficit": 0.8,
                "et0_fao_evapotranspiration": 0.4,
            },
            {
                "time": "15:00",
                "temp_c": 26.0,
                "cloud_cover": 20.0,
                "low_cloud": 2.0,
                "mid_cloud": 10.0,
                "high_cloud": 40.0,
                "solar": 700.0,
                "direct_radiation": 500.0,
                "diffuse_radiation": 180.0,
                "precipitation": 0.1,
                "precipitation_probability": 30.0,
                "cape": 120.0,
                "temperature_925hpa": 22.0,
                "temperature_850hpa": 16.0,
                "geopotential_height_500hpa": 5740.0,
                "wind_gust_kmh": 35.0,
                "visibility": 12000.0,
                "soil_temperature_0cm": 23.0,
                "soil_moisture_0_to_1cm": 0.24,
                "vapour_pressure_deficit": 0.9,
                "et0_fao_evapotranspiration": 0.5,
            },
            {
                "time": "16:00",
                "temp_c": 24.0,
                "cloud_cover": 35.0,
                "low_cloud": 10.0,
                "mid_cloud": 15.0,
                "high_cloud": 35.0,
                "solar": 400.0,
                "direct_radiation": 250.0,
                "diffuse_radiation": 190.0,
                "precipitation": 0.0,
                "precipitation_probability": 10.0,
                "cape": 80.0,
                "temperature_925hpa": 21.0,
                "temperature_850hpa": 15.0,
                "geopotential_height_500hpa": 5750.0,
                "wind_gust_kmh": 30.0,
                "visibility": 18000.0,
                "soil_temperature_0cm": 22.0,
                "soil_moisture_0_to_1cm": 0.25,
                "vapour_pressure_deficit": 1.0,
                "et0_fao_evapotranspiration": 0.2,
            },
        ]
        ensemble_rows = [
            {"time": "12:00", "ensemble_member_spread": 2.0},
            {"time": "13:00", "ensemble_member_spread": 3.0},
            {"time": "14:00", "ensemble_member_spread": 4.0},
        ]
        air_quality_rows = [
            {"time": "12:00", "pm2_5": 18.0, "pm10": 24.0, "aerosol_optical_depth": 0.16, "dust": 3.0},
            {"time": "13:00", "pm2_5": 36.0, "pm10": 55.0, "aerosol_optical_depth": 0.42, "dust": 6.0},
            {"time": "14:00", "pm2_5": 32.0, "pm10": 44.0, "aerosol_optical_depth": 0.35, "dust": 4.0},
            {"time": "15:00", "pm2_5": 30.0, "pm10": 38.0, "aerosol_optical_depth": 0.30, "dust": 5.0},
            {"time": "16:00", "pm2_5": 22.0, "pm10": 30.0, "aerosol_optical_depth": 0.20, "dust": 2.0},
        ]
        historical_profile_rows = merge_forecast_air_quality_rows(forecast_rows, air_quality_rows)

        live = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": obs_rows}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {
                "ok": True,
                "data": {"rows": forecast_rows[1:], "day_rows": forecast_rows, "day_max_c": 26.0},
            },
            "open_meteo_air_quality": {
                "ok": True,
                "data": {"rows": air_quality_rows, "day_rows": air_quality_rows},
            },
            "global_ensemble": {
                "ok": True,
                "data": {
                    "rows": ensemble_rows,
                    "day_rows": ensemble_rows,
                    "day_mean_member_spread": 3.0,
                    "day_member_high_p10": 24.0,
                    "day_member_high_p90": 27.0,
                },
            },
        }, cutoff_hour=12)
        historical = build_historical_feature_record(
            "2026-05-28",
            obs_rows,
            {"bucket": 26},
            12,
            forecast_high=26.0,
            forecast_profile_rows=historical_profile_rows,
            global_ensemble_profile_rows=ensemble_rows,
            global_ensemble_day_mean_spread=3.0,
            global_ensemble_day_high_p10=24.0,
            global_ensemble_day_high_p90=27.0,
            wind_group_fn=model.wind_group,
            cloud_group_fn=model.cloud_group,
        )

        for column in FEATURE_COLUMNS:
            self.assertEqual(historical[column], live[column], column)
        self.assertEqual(live["forecast_peak_hour"], 15.0)
        self.assertEqual(live["forecast_peak_after_cutoff_hours"], 3.0)
        self.assertEqual(live["forecast_afternoon_slope"], 2.0)
        self.assertEqual(live["forecast_remaining_degree_hours"], 21.0)
        self.assertEqual(live["forecast_remaining_solar_sum"], 3500.0)
        self.assertEqual(live["forecast_next_3h_solar_mean"], 800.0)
        self.assertEqual(live["forecast_cloud_trend_3h"], -20.0)
        self.assertEqual(live["forecast_remaining_direct_radiation_sum"], 2550.0)
        self.assertEqual(live["forecast_remaining_diffuse_radiation_sum"], 850.0)
        self.assertEqual(live["forecast_next_3h_direct_radiation_mean"], 600.0)
        self.assertEqual(live["forecast_next_3h_diffuse_radiation_mean"], 160.0)
        self.assertEqual(live["forecast_remaining_direct_radiation_share"], 0.75)
        self.assertAlmostEqual(live["forecast_next_3h_direct_radiation_share"], 1800.0 / 2280.0)
        self.assertAlmostEqual(live["forecast_remaining_precipitation_sum"], 0.3)
        self.assertAlmostEqual(live["forecast_next_3h_precipitation_sum"], 0.2)
        self.assertEqual(live["forecast_next_3h_precipitation_probability_max"], 40.0)
        self.assertEqual(live["forecast_remaining_cape_mean"], 76.0)
        self.assertEqual(live["forecast_next_3h_cape_max"], 90.0)
        self.assertEqual(live["forecast_cape_trend_3h"], 50.0)
        self.assertEqual(live["forecast_temperature_925hpa_mean"], 20.6)
        self.assertEqual(live["forecast_temperature_850hpa_mean"], 14.6)
        self.assertAlmostEqual(live["forecast_surface_to_925_lapse_proxy"], 3.6)
        self.assertAlmostEqual(live["forecast_925_to_850_lapse_proxy"], 6.0)
        self.assertEqual(live["forecast_geopotential_height_500hpa_mean"], 5730.0)
        self.assertEqual(live["forecast_wind_gust_max"], 35.0)
        self.assertEqual(live["forecast_visibility_min"], 10000.0)
        self.assertEqual(live["forecast_soil_temperature_0cm_mean"], 21.6)
        self.assertAlmostEqual(live["forecast_soil_moisture_0_to_1cm_mean"], 0.23)
        self.assertAlmostEqual(live["forecast_vapour_pressure_deficit_mean"], 0.8)
        self.assertAlmostEqual(live["forecast_et0_fao_evapotranspiration_sum"], 1.6)
        self.assertAlmostEqual(live["forecast_remaining_aerosol_optical_depth_mean"], 0.286)
        self.assertAlmostEqual(live["forecast_next_3h_aerosol_optical_depth_mean"], 0.31)
        self.assertAlmostEqual(live["forecast_remaining_pm2_5_mean"], 27.6)
        self.assertAlmostEqual(live["forecast_next_3h_pm2_5_mean"], 86.0 / 3.0)
        self.assertAlmostEqual(live["forecast_remaining_pm10_mean"], 38.2)
        self.assertAlmostEqual(live["forecast_remaining_dust_mean"], 4.0)
        self.assertEqual(live["forecast_smoke_suppression_flag"], 1.0)
        self.assertEqual(live["forecast_global_ensemble_high_spread_80"], 3.0)

    def test_live_features_measure_forecast_source_disagreement(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": [
                {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
            ]}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [
                {"time": "13:00", "temp_c": 25.0},
                {"time": "14:00", "temp_c": 24.0},
            ]}},
            "eccc_citypage": {"ok": True, "data": {}},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 24.0)
        self.assertEqual(features["forecast_source_count"], 2)
        self.assertEqual(features["forecast_disagreement"], 2.0)

    def test_live_features_include_nws_and_global_ensemble_forecasts(self):
        model = TorontoHighTempModel(target_date="2026-05-28")
        features = model.extract_live_features({
            "wu_history": {"ok": True, "data": {"rows": [
                {"time": "12:00", "temp_c": 20.0, "dewpoint_c": 11.0, "humidity": 55.0, "pressure": 1014.0},
            ]}},
            "wu_current": {"ok": True, "data": {"temp_c": 20.0}},
            "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 23.0}},
            "weather_forecast": {"ok": True, "data": {"rows": [{"time": "13:00", "temp_c": 25.0}]}},
            "nws_hourly": {"ok": True, "data": {"rows": [], "day_max_c": 26.0}},
            "global_ensemble": {"ok": True, "data": {"rows": [], "day_max_c": 24.0}},
            "eccc_citypage": {"ok": True, "data": {}},
        }, cutoff_hour=12)

        self.assertEqual(features["forecast_high"], 24.5)
        self.assertEqual(features["forecast_source_count"], 4)
        self.assertEqual(features["forecast_disagreement"], 3.0)

    def test_snapshot_store_persists_feature_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="event")
            captured_at = datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ)
            model_client = TorontoHighTempModel(target_date="2026-05-28")
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "model_version": "model-v",
                "sources": {},
                "distribution_components": {
                    "schema_version": "components-v",
                    "cutoff_hour": 12,
                    "active_model_kind": "hgb",
                    "components": {
                        "feature_model": {19: 0.2, 20: 0.5, 21: 0.3},
                    },
                },
                "feature_vector": {
                    "target_date": "2026-05-28",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "cutoff_hour": 12,
                    "high_so_far": 20.0,
                },
            }
            event = {
                "markets": [
                    {
                        "groupItemTitle": "20 C",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.40","0.60"]',
                    },
                    {
                        "groupItemTitle": "21 C or higher",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.30","0.70"]',
                    },
                ],
                "slug": "event",
            }

            result = store.write(event, model, model_client, captured_at)
            rows = list(csv.DictReader((root / "features_long.csv").open(encoding="utf-8", newline="")))
            component_rows = list(csv.DictReader((root / "components_long.csv").open(encoding="utf-8", newline="")))

            self.assertEqual(result["features_path"], str(root / "features_long.csv"))
            self.assertEqual(result["components_path"], str(root / "components_long.csv"))
            self.assertEqual(rows[0]["snapshot_id"], captured_at.strftime("%Y%m%dT%H%M%S%z"))
            self.assertEqual(rows[0]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
            self.assertEqual(len(component_rows), 2)
            self.assertEqual(component_rows[0]["component_schema_version"], "components-v")
            self.assertEqual(component_rows[0]["component_name"], "feature_model")
            self.assertEqual(component_rows[0]["bin_value_hi_c"], "20")
            self.assertAlmostEqual(float(component_rows[0]["component_probability"]), 0.5)
            self.assertAlmostEqual(float(component_rows[1]["component_probability"]), 0.3)

    def test_snapshot_store_persists_model_explanation_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="event")
            captured_at = datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ)
            model_client = TorontoHighTempModel(target_date="2026-05-28")
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "model_version": "model-v",
                "sources": {
                    "wu_history": {
                        "ok": True,
                        "data": {"rows": [{"time": "11:00", "temp": 20.0}], "raw_payload": {"drop": "me"}},
                    }
                },
                "distribution_components": {
                    "schema_version": "components-v",
                    "cutoff_hour": 12,
                    "active_model_kind": "hgb",
                    "components": {
                        "feature_model": {20: 1.0},
                        "final_model": {20: 1.0},
                    },
                },
                "feature_vector": {
                    "target_date": "2026-05-28",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "cutoff_hour": 12,
                    "high_so_far": 20.0,
                },
                "analog_search": {"neighbors": [{"date": "2026-05-20", "distance": 0.2}], "limit": 5},
                "boundary_transitions": {"p_ge_21": 0.12},
                "late_day_risk": {"lock_in": True, "risk_score": 0.7},
                "source_diagnostics": [{"source": "wu_history", "status": "fresh", "latency_ms": 44}],
                "source_health": {"status": "PASS"},
                "family_secondary_gate": {"status": "PASS", "mode": "served"},
                "model_explanation": {
                    "feature_cutoff_hour": 12,
                    "driver_breakdown": [{"Driver": "ML feature blend", "20 C": "100.0%"}],
                    "waterfall": [{"Driver": "Final model", "20 C": "100.0%"}],
                },
            }
            event = {
                "markets": [
                    {
                        "groupItemTitle": "20 C",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.40","0.60"]',
                    }
                ],
                "slug": "event",
            }

            result = store.write(event, model, model_client, captured_at)
            explanation_rows = list(csv.DictReader((root / "snapshot_explanations_long.csv").open(encoding="utf-8", newline="")))
            explanation_payload = json.loads((root / "snapshot_explanations.jsonl").read_text(encoding="utf-8").strip())
            observation_rows = list(csv.DictReader((root / "observation_payloads_long.csv").open(encoding="utf-8", newline="")))
            observation_payload = json.loads((root / "observation_payloads.jsonl").read_text(encoding="utf-8").strip())
            feature_rows = list(csv.DictReader((root / "features_long.csv").open(encoding="utf-8", newline="")))
            component_rows = list(csv.DictReader((root / "components_long.csv").open(encoding="utf-8", newline="")))
            replay_payload = json.loads((root / "replay_inputs.jsonl").read_text(encoding="utf-8").strip())
            observation_raw_exists = Path(observation_rows[0]["raw_payload_path"]).exists()

        snapshot_id = captured_at.strftime("%Y%m%dT%H%M%S%z")
        self.assertEqual(result["snapshot_explanation_rows"], len(explanation_rows))
        self.assertEqual(result["snapshot_explanations_path"], str(root / "snapshot_explanations_long.csv"))
        self.assertEqual(result["snapshot_explanations_jsonl_path"], str(root / "snapshot_explanations.jsonl"))
        self.assertEqual(result["observation_payload_rows"], 1)
        self.assertEqual(result["observation_payloads_path"], str(root / "observation_payloads_long.csv"))
        self.assertEqual(result["observation_payloads_jsonl_path"], str(root / "observation_payloads.jsonl"))
        self.assertEqual(explanation_payload["schema_version"], "snapshot_explanations_v0.1")
        self.assertEqual(explanation_payload["snapshot_id"], snapshot_id)
        self.assertIn("model_explanation", explanation_payload["sections"])
        self.assertIn("analog_search", explanation_payload["sections"])
        sections = {row["section"] for row in explanation_rows}
        self.assertIn("model_explanation", sections)
        self.assertIn("source_diagnostics", sections)
        self.assertIn("family_secondary_gate", sections)
        self.assertTrue(all(row["snapshot_id"] == snapshot_id for row in explanation_rows))
        self.assertEqual(feature_rows[0]["snapshot_id"], snapshot_id)
        self.assertEqual(component_rows[0]["snapshot_id"], snapshot_id)
        self.assertEqual(replay_payload["snapshot_id"], snapshot_id)
        self.assertEqual(explanation_rows[0]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertTrue(explanation_rows[0]["source_hash"])
        self.assertEqual(observation_rows[0]["source"], "wu_history")
        self.assertEqual(observation_payload["source"], "wu_history")
        self.assertTrue(observation_raw_exists)
        self.assertNotIn("raw_payload", json.dumps(replay_payload["sources"], sort_keys=True))

    def test_snapshot_store_backfills_explanation_tape_from_existing_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-nyc-on-june-20-2026")
            snapshot_id = "20260620T120000-0400"
            snapshot = {
                "snapshot_id": snapshot_id,
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": "highest-temperature-in-nyc-on-june-20-2026",
                "model_version": "model-v",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "runtime_identity": {"git_commit": "abc"},
                "runtime_guard": {"state": "current"},
                "model_identity": {"artifact": "model.pkl"},
                "distribution": {"82": 1.0},
                "distribution_components": {
                    "schema_version": "components-v",
                    "cutoff_hour": 12,
                    "active_model_kind": "hgb",
                    "components": {"final_model": {"82": 1.0}},
                },
                "feature_vector": {"feature_schema_version": FEATURE_SCHEMA_VERSION},
                "model_explanation": {"feature_cutoff_hour": 12},
            }
            replay = {
                "snapshot_id": snapshot_id,
                "target_date": "2026-06-20",
                "model_version": "model-v",
                "recorded_distribution": {"82": 1.0},
                "sources": {"wu_history": {"ok": True, "data": {"rows": [{"temp": 82}]}}},
            }
            store.append_jsonl(root / "snapshots.jsonl", snapshot)
            store.append_jsonl(root / "replay_inputs.jsonl", replay)

            first = store.backfill_snapshot_explanations()
            second = store.backfill_snapshot_explanations()
            rows = list(csv.DictReader((root / "snapshot_explanations_long.csv").open(encoding="utf-8", newline="")))
            payload = json.loads((root / "snapshot_explanations.jsonl").read_text(encoding="utf-8").strip())

        self.assertEqual(first["written_snapshot_count"], 1)
        self.assertEqual(second["written_snapshot_count"], 0)
        self.assertEqual(second["skipped_existing_snapshot_count"], 1)
        self.assertEqual(payload["snapshot_id"], snapshot_id)
        self.assertIn("model_explanation", payload["sections"])
        self.assertTrue(any(row["section"] == "distribution_component_metadata" for row in rows))
        self.assertTrue(all(row["snapshot_id"] == snapshot_id for row in rows))

    def test_snapshot_store_backfills_core_sidecars_from_existing_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-nyc-on-june-20-2026")
            snapshot = {
                "snapshot_id": "s1",
                "captured_at_local": "2026-06-20T12:00:00-04:00",
                "event_slug": "highest-temperature-in-nyc-on-june-20-2026",
                "model_version": "model-v",
                "feature_vector": {
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "cutoff_hour": 12,
                    "forecast_high_c": 82,
                },
                "distribution_components": {
                    "schema_version": "components-v",
                    "cutoff_hour": 12,
                    "active_model_kind": "hgb",
                    "components": {
                        "final_model": {"82": 0.7, "83": 0.3},
                    },
                },
                "bands": [
                    {
                        "range_label": "82-83 F",
                        "bin_kind": "eq",
                        "bin_value_c": "82",
                        "bin_value_hi_c": "83",
                        "market_yes": "0.55",
                    }
                ],
            }
            store.append_jsonl(root / "snapshots.jsonl", snapshot)

            first = store.backfill_feature_component_sidecars()
            second = store.backfill_feature_component_sidecars()
            feature_rows = list(csv.DictReader((root / "features_long.csv").open(encoding="utf-8", newline="")))
            component_rows = list(csv.DictReader((root / "components_long.csv").open(encoding="utf-8", newline="")))

        self.assertEqual(first["written_feature_row_count"], 1)
        self.assertEqual(first["written_component_row_count"], 1)
        self.assertEqual(second["written_feature_row_count"], 0)
        self.assertEqual(second["skipped_existing_feature_snapshot_count"], 1)
        self.assertEqual(feature_rows[0]["snapshot_id"], "s1")
        self.assertEqual(component_rows[0]["component_schema_version"], "components-v")
        self.assertEqual(component_rows[0]["bin_value_hi_c"], "83")

    def test_snapshot_store_backfills_observation_payloads_from_forecast_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="event")
            (root / "forecast_payloads_long.csv").write_text(
                "\n".join([
                    "snapshot_id,captured_at_utc,captured_at_local,event_slug,model_version,source,status,stale,source_family,degradation_state,cache_status,fetched_at,age_minutes,ttl_minutes,provider_issue_time,provider_update_time,payload_hash,payload_bytes,row_count,source_url,raw_payload_path",
                    "s1,2026-06-20T16:00:00+00:00,2026-06-20T12:00:00-04:00,event,model-v,wu_current,fresh,False,wu_current,healthy,live,2026-06-20T16:00:00+00:00,0,10,,2026-06-20T16:00:00+00:00,abc,12,1,https://example.test,raw.json",
                    "s1,2026-06-20T16:00:00+00:00,2026-06-20T12:00:00-04:00,event,model-v,open_meteo,fresh,False,open_meteo,healthy,live,2026-06-20T16:00:00+00:00,0,10,,2026-06-20T16:00:00+00:00,def,12,1,https://example.test,raw2.json",
                ]) + "\n",
                encoding="utf-8",
            )

            first = store.backfill_observation_payloads_from_forecast_payloads()
            second = store.backfill_observation_payloads_from_forecast_payloads()
            rows = list(csv.DictReader((root / "observation_payloads_long.csv").open(encoding="utf-8", newline="")))
            payload = json.loads((root / "observation_payloads.jsonl").read_text(encoding="utf-8").strip())

        self.assertEqual(first["written_row_count"], 1)
        self.assertEqual(second["written_row_count"], 0)
        self.assertEqual(second["skipped_existing_row_count"], 1)
        self.assertEqual(rows[0]["source"], "wu_current")
        self.assertEqual(payload["source"], "wu_current")

    def test_snapshot_store_persists_range_band_upper_endpoint(self):
        class RangeModelClient:
            target_date = datetime(2026, 5, 28).date()

            def market_bins(self, _event):
                return [{
                    "label": "90-91 F",
                    "kind": "eq",
                    "value": 90,
                    "value_hi": 91,
                    "market_yes": 0.4,
                    "market_no": 0.6,
                }]

            def bin_probability(self, distribution, bin_data):
                return sum(
                    probability
                    for bucket, probability in distribution.items()
                    if int(bin_data["value"]) <= int(bucket) <= int(bin_data["value_hi"])
                )

            def source_data(self, _sources, _name):
                return {}

            def forecast_ensemble_metrics(self, *_args, **_kwargs):
                return {}

            def max_row_temp(self, _rows):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="event")
            captured_at = datetime(2026, 5, 28, 12, 0, tzinfo=TORONTO_TZ)
            model = {
                "distribution": {90: 0.10, 91: 0.85, 92: 0.05},
                "top_temp": 91,
                "model_version": "model-v",
                "sources": {},
                "feature_vector": {
                    "target_date": "2026-05-28",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                },
                "distribution_components": {
                    "schema_version": "components-v",
                    "components": {"feature_model": {90: 0.10, 91: 0.85, 92: 0.05}},
                },
            }

            result = store.write({"slug": "event", "markets": []}, model, RangeModelClient(), captured_at)
            long_rows = list(csv.DictReader((root / "snapshots_long.csv").open(encoding="utf-8", newline="")))
            component_rows = list(csv.DictReader((root / "components_long.csv").open(encoding="utf-8", newline="")))
            wide_header = (root / "snapshots_wide.csv").read_text(encoding="utf-8").splitlines()[0]
            snapshot_json = json.loads((root / "snapshots.jsonl").read_text(encoding="utf-8").strip())

        self.assertEqual(result["snapshot_self_check"]["status"], "pass")
        self.assertEqual(long_rows[0]["bin_value_c"], "90")
        self.assertEqual(long_rows[0]["bin_value_hi_c"], "91")
        self.assertEqual(long_rows[0]["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertTrue(long_rows[0]["runtime_source_fingerprint"])
        self.assertEqual(component_rows[0]["bin_value_hi_c"], "91")
        self.assertIn("model_eq_90_91c", wide_header)
        self.assertEqual(snapshot_json["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertEqual(snapshot_json["snapshot_self_check"]["rows_checked"], 1)

    def test_snapshot_probability_self_check_rejects_range_metadata_mismatch(self):
        class RangeModelClient:
            def bin_probability(self, distribution, bin_data):
                return sum(
                    probability
                    for bucket, probability in distribution.items()
                    if int(bin_data["value"]) <= int(bucket) <= int(bin_data["value_hi"])
                )

        store = SnapshotStore(root=Path("."), event_slug="event")
        with self.assertRaises(ValueError):
            store.check_snapshot_probabilities(
                {90: 0.10, 91: 0.85},
                [{
                    "range_label": "90-91 F",
                    "bin_kind": "eq",
                    "bin_value_c": 90,
                    "bin_value_hi_c": 91,
                    "model_probability": 0.10,
                }],
                RangeModelClient(),
            )

    def test_append_csv_widens_existing_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            path.write_text("snapshot_id,bin_value_c\nold,90\n", encoding="utf-8")
            store = SnapshotStore(root=tmp, event_slug="event")

            store.append_csv(
                path,
                ["snapshot_id", "bin_value_c", "bin_value_hi_c"],
                [{"snapshot_id": "new", "bin_value_c": 90, "bin_value_hi_c": 91}],
            )
            rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))

        self.assertEqual(rows[0]["snapshot_id"], "old")
        self.assertEqual(rows[0]["bin_value_hi_c"], "")
        self.assertEqual(rows[1]["snapshot_id"], "new")
        self.assertEqual(rows[1]["bin_value_hi_c"], "91")

    def test_snapshot_component_probability_sums_range_bands(self):
        store = SnapshotStore(root=Path("."), event_slug="event")
        distribution = {90: 0.10, 91: 0.85, 92: 0.05}
        band = {"kind": "eq", "value": 90, "value_hi": 91}

        self.assertAlmostEqual(store.raw_bin_probability(distribution, band), 0.95)

    def test_snapshot_source_values_read_native_aliases_first(self):
        store = SnapshotStore(root=Path("."), event_slug="event")
        model = TorontoHighTempModel(target_date="2026-05-28", market_id="nyc")

        values = store.source_values(
            {
                "wu_history": {
                    "ok": True,
                    "data": {"max_native": 91.0, "max_c": 33.0},
                },
                "wu_current": {
                    "ok": True,
                    "data": {
                        "temp_native": 89.0,
                        "temp_c": 32.0,
                        "max_since_7am_native": 92.0,
                        "max_since_7am_c": 34.0,
                    },
                },
                "eccc_swob": {
                    "ok": True,
                    "data": {"same_day_max_native": 90.0, "same_day_max_c": 32.0},
                },
                "weather_forecast": {
                    "ok": True,
                    "data": {"rows": [{"temp_native": 93.0, "temp_c": 34.0}]},
                },
                "open_meteo": {"ok": True, "data": {"rows": []}},
                "nws_hourly": {"ok": True, "data": {"rows": []}},
                "global_ensemble": {"ok": True, "data": {"rows": []}},
                "eccc_citypage": {
                    "ok": True,
                    "data": {"forecast_high_native": 94.0, "forecast_high_c": 35.0},
                },
            },
            model,
        )

        self.assertEqual(values["wu_history_high_c"], 91.0)
        self.assertEqual(values["wu_current_c"], 89.0)
        self.assertEqual(values["wu_max_since_7am_c"], 92.0)
        self.assertEqual(values["eccc_swob_max_c"], 90.0)
        self.assertEqual(values["weather_forecast_max_c"], 93.0)
        self.assertEqual(values["eccc_forecast_high_c"], 94.0)


if __name__ == "__main__":
    unittest.main()
