import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from market_registry import NYC, SEATTLE
from pooled_feature_model import (
    add_city_features,
    adjacent_calibration_contexts,
    adjacent_calibration_factor,
    apply_band_postprocessing,
    apply_adjacent_calibration,
    band_feature_frame,
    band_prediction_record,
    default_band_postprocess,
    feature_frame,
    fit_adjacent_calibration,
    hard_floor_probability,
    historical_only_source_feature_manifest,
    late_lockin_strength_from_features,
    market_source_reliability,
    support_floor_cap,
)
from market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS


class TestPooledFeatureModel(unittest.TestCase):
    def _base_record(self):
        return {
            "high_so_far": 80.0,
            "current_temp": 79.0,
            "rise_from_7am": 12.0,
            "warming_rate_2h": 3.0,
            "hours_at_peak": 0.5,
            "dewpoint_c": 60.0,
            "humidity": 55.0,
            "pressure": 29.9,
            "pressure_trend_3h": -0.1,
            "wind_speed_kmh": 10.0,
            "forecast_high": 84.0,
            "forecast_gap": 4.0,
            "minutes_since_cutoff": 30.0,
            "live_reading_temp": 81.0,
            "live_reading_minus_high": 1.0,
            "wind_group": "S-SW",
            "cloud_group": "Fair/clear",
            "final_bucket": 83,
            "cutoff_hour": 14,
        }

    def test_city_features_and_market_one_hot_enter_frame(self):
        left = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        }, source_reliability={
            "source_redundant_streams": 2.0,
            "source_best_bucket_match": 0.75,
        })
        right = add_city_features(self._base_record(), SEATTLE, {
            "climate_normal": 75.0,
            "climate_std": 4.0,
        }, source_reliability={
            "source_redundant_streams": 3.0,
            "source_best_bucket_match": 0.90,
        })

        frame = feature_frame([left, right])

        self.assertIn("latitude", frame.columns)
        self.assertIn("coastal", frame.columns)
        self.assertIn("high_so_far_anomaly", frame.columns)
        self.assertIn("source_redundant_streams", frame.columns)
        self.assertIn("source_best_bucket_match", frame.columns)
        self.assertIn("market_id_nyc", frame.columns)
        self.assertIn("market_id_seattle", frame.columns)
        self.assertAlmostEqual(frame.loc[0, "high_so_far_anomaly"], -2.0)
        self.assertAlmostEqual(frame.loc[1, "high_so_far_anomaly"], 5.0)
        self.assertAlmostEqual(frame.loc[0, "source_redundant_streams"], 2.0)
        self.assertAlmostEqual(frame.loc[1, "source_best_bucket_match"], 0.90)

    def test_market_source_reliability_populates_ghcnh_and_reanalysis_priors(self):
        indexes = {
            "wu": {
                "2026-06-01": {"high": 80.0, "bucket": 80, "peak_minute": 900},
                "2026-06-02": {"high": 82.0, "bucket": 82, "peak_minute": 960},
            },
            "metar": {},
            "ghcnh": {
                "2026-06-01": {"high": 81.0, "bucket": 81, "peak_minute": 840},
                "2026-06-02": {"high": 83.0, "bucket": 83, "peak_minute": 900},
            },
            "reanalysis": {
                "2026-06-01": {"high": 78.0, "bucket": 78, "peak_minute": 1020},
                "2026-06-02": {"high": 82.0, "bucket": 82, "peak_minute": 960},
            },
        }

        with patch("pooled_feature_model.source_daily_indexes", return_value=indexes):
            reliability = market_source_reliability(NYC)

        self.assertEqual(reliability["source_redundant_streams"], 2.0)
        self.assertEqual(reliability["source_overlap_days"], 4.0)
        self.assertAlmostEqual(reliability["source_ghcnh_bias"], 1.0)
        self.assertAlmostEqual(reliability["source_ghcnh_mae"], 1.0)
        self.assertAlmostEqual(reliability["source_ghcnh_bucket_match"], 0.0)
        self.assertAlmostEqual(reliability["source_reanalysis_bias"], -1.0)
        self.assertAlmostEqual(reliability["source_reanalysis_mae"], 1.0)
        self.assertAlmostEqual(reliability["source_reanalysis_bucket_match"], 0.5)
        self.assertAlmostEqual(reliability["source_best_bucket_match"], 0.5)
        self.assertAlmostEqual(reliability["source_best_mae"], 1.0)

    def test_supplemental_reliability_columns_are_historical_only_opt_in(self):
        indexes = {
            "wu": {
                "2026-06-01": {"high": 80.0, "bucket": 80, "peak_minute": 900},
                "2026-06-02": {"high": 82.0, "bucket": 82, "peak_minute": 960},
            },
            "ghcnh_supplemental__nearby": {
                "2026-06-01": {
                    "high": 80.2,
                    "bucket": 80,
                    "peak_minute": 900,
                    "supplemental_distance_km": 0.5,
                },
                "2026-06-02": {
                    "high": 81.0,
                    "bucket": 81,
                    "peak_minute": 960,
                    "supplemental_distance_km": 0.5,
                },
            },
        }

        with patch("pooled_feature_model.source_daily_indexes", return_value=indexes):
            reliability = market_source_reliability(NYC, include_historical_only=True)

        self.assertEqual(reliability["source_supplemental_available"], 1.0)
        self.assertEqual(reliability["source_supplemental_count"], 1.0)
        self.assertEqual(reliability["source_supplemental_overlap_days"], 2.0)
        self.assertAlmostEqual(reliability["source_supplemental_best_mae"], 0.6)
        self.assertAlmostEqual(reliability["source_supplemental_best_bucket_match"], 0.5)
        self.assertAlmostEqual(reliability["source_supplemental_min_distance_km"], 0.5)

        record = add_city_features(
            self._base_record(),
            NYC,
            {"climate_normal": 82.0, "climate_std": 5.0},
            source_reliability=reliability,
            include_historical_only=True,
        )
        default_frame = feature_frame([record])
        opt_in_frame = feature_frame([record], include_historical_only=True)
        band_frame = band_feature_frame(
            [band_prediction_record(record, "eq", 80)],
            include_historical_only=True,
        )
        manifest = historical_only_source_feature_manifest()

        self.assertNotIn("source_supplemental_available", default_frame.columns)
        self.assertIn("source_supplemental_available", opt_in_frame.columns)
        self.assertIn("source_supplemental_best_mae", band_frame.columns)
        self.assertFalse(manifest["live_serving_eligible"])
        self.assertFalse(manifest["default_in_feature_frame"])

    def test_band_prediction_record_adds_floor_and_band_context(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })

        band = band_prediction_record(record, "eq", 80, value_hi=81)

        self.assertEqual(band["band_kind"], "eq")
        self.assertEqual(band["band_width"], 2.0)
        self.assertEqual(band["observed_floor_bucket"], 80)
        self.assertEqual(band["band_contains_floor"], 1.0)
        self.assertAlmostEqual(band["band_mid_minus_high_so_far"], 0.5)

    def test_band_feature_frame_includes_clob_columns_when_values_exist(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        band = band_prediction_record(record, "eq", 82, value_hi=83)
        band.update({
            "clob_feature_available": 1.0,
            "clob_midpoint": 0.42,
            "clob_liquidity_score": 2.75,
        })

        frame = band_feature_frame([band])

        self.assertIn("clob_feature_available", frame.columns)
        self.assertIn("clob_midpoint", frame.columns)
        self.assertIn("clob_liquidity_score", frame.columns)
        self.assertAlmostEqual(frame.loc[0, "clob_midpoint"], 0.42)

    def test_band_feature_frame_drops_all_empty_clob_columns_for_legacy_rows(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        band = band_prediction_record(record, "eq", 82, value_hi=83)

        frame = band_feature_frame([band])

        for column in CLOB_MODEL_FEATURE_COLUMNS:
            self.assertNotIn(column, frame.columns)

    def test_hard_floor_probability_prices_already_settled_bands(self):
        self.assertEqual(hard_floor_probability("gte", 79, 80), 1.0)
        self.assertEqual(hard_floor_probability("lte", 79, 80), 0.0)
        self.assertEqual(hard_floor_probability("eq", 78, 80), 0.0)
        self.assertIsNone(hard_floor_probability("eq", 80, 80))

    def test_late_lockin_postprocess_blends_toward_printed_high_resolution(self):
        record = self._base_record()
        record["cutoff_hour"] = 17
        record["high_so_far"] = 80.0
        record["live_reading_temp"] = 77.0
        band = band_prediction_record(record, "eq", 80)

        self.assertEqual(late_lockin_strength_from_features(record), 1.0)
        adjusted = apply_band_postprocessing(
            0.20,
            band,
            {"late_lockin_enabled": True, "late_lockin_max_strength": 0.85},
        )

        self.assertGreater(adjusted, 0.80)

    def test_support_floor_caps_bands_below_live_support(self):
        self.assertAlmostEqual(support_floor_cap("eq", 90, 92, value_hi=91), 0.08)
        self.assertAlmostEqual(support_floor_cap("eq", 90, 93, value_hi=91), 0.02)
        self.assertAlmostEqual(support_floor_cap("lte", 90, 92), 0.02)
        self.assertIsNone(support_floor_cap("eq", 92, 92))

    def test_adjacent_calibration_skips_floor_bucket_and_shrinks_above_floor(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        floor_band = band_prediction_record(record, "eq", 80)
        above_floor = band_prediction_record(record, "eq", 82)
        context = adjacent_calibration_contexts(above_floor)[0]
        config = {
            "adjacent_calibration": {
                "contexts": {
                    context: {"factor": 0.50},
                },
            },
        }

        self.assertEqual(adjacent_calibration_contexts(floor_band), [])
        self.assertAlmostEqual(adjacent_calibration_factor(above_floor, config), 0.50)
        self.assertAlmostEqual(apply_adjacent_calibration(0.40, above_floor, config), 0.20)

    def test_default_band_postprocess_keeps_regressing_markets_on_current(self):
        config = default_band_postprocess()

        self.assertTrue(config["current_blend_enabled"])
        self.assertEqual(config["current_blend_market_alpha"]["dallas"], 0.0)
        self.assertEqual(config["current_blend_market_alpha"]["san-francisco"], 0.0)

    def test_fit_adjacent_calibration_smooths_context_factors(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        rows = []
        for _ in range(4):
            row = band_prediction_record(record, "eq", 82)
            row["outcome"] = 0
            rows.append(row)

        calibration = fit_adjacent_calibration(
            rows,
            [0.50, 0.50, 0.50, 0.50],
            min_rows=1,
            prior_rows=0.0,
            factor_min=0.15,
            factor_max=2.50,
        )

        context = adjacent_calibration_contexts(rows[0])[0]
        self.assertIn(context, calibration["contexts"])
        self.assertAlmostEqual(calibration["contexts"][context]["factor"], 0.15)


if __name__ == "__main__":
    unittest.main()
