import os
import sys
import unittest
from unittest.mock import patch
from weather.market.market_registry import NYC, SEATTLE, TORONTO
from weather.calibration.pooled_feature_model import (
    add_city_features,
    add_dynamic_source_state_features,
    adjacent_calibration_contexts,
    adjacent_calibration_factor,
    apply_band_postprocessing,
    apply_adjacent_calibration,
    apply_exact_winner_catchup,
    band_feature_frame,
    band_prediction_record,
    canonical_density_record,
    default_band_postprocess,
    dynamic_source_state_features,
    evaluate_density_predictions,
    exact_winner_catchup_contexts,
    exact_winner_catchup_factor,
    feature_frame,
    fit_adjacent_calibration,
    fit_exact_winner_catchup,
    hard_floor_probability,
    historical_only_source_feature_manifest,
    late_lockin_strength_from_features,
    market_source_reliability,
    normalize_band_probabilities_for_rows,
    predict_density_rows_for_bundle,
    support_floor_cap,
    train_pooled_density_models,
)
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS


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

    def _density_records(self):
        records = []
        for idx in range(80):
            spec = TORONTO if idx % 2 == 0 else NYC
            if spec.display_unit == "C":
                high = 18.0 + (idx % 8)
                final_bucket = int(high + 1 + (idx % 3 == 0))
                climate = {"climate_normal": 22.0, "climate_std": 4.0}
            else:
                high = 65.0 + (idx % 14)
                final_bucket = int(high + 2 + (idx % 4 == 0))
                climate = {"climate_normal": 74.0, "climate_std": 6.0}
            record = {
                "high_so_far": high,
                "current_temp": high - 1.0,
                "rise_from_7am": 6.0 + (idx % 4),
                "warming_rate_2h": 1.0 + (idx % 3),
                "hours_at_peak": 0.5,
                "dewpoint_c": high - 6.0,
                "humidity": 55.0,
                "pressure": 29.9,
                "pressure_trend_3h": -0.1,
                "wind_speed_kmh": 10.0 + (idx % 5),
                "forecast_high": final_bucket + 0.5,
                "forecast_gap": final_bucket + 0.5 - high,
                "minutes_since_cutoff": 30.0,
                "live_reading_temp": high - 0.5,
                "live_reading_minus_high": -0.5,
                "wind_group": "S-SW",
                "cloud_group": "Fair/clear",
                "final_bucket": final_bucket,
                "cutoff_hour": 12,
                "year": 2024 if idx < 60 else 2025,
            }
            records.append(add_city_features(record, spec, climate))
        return records

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

    def test_canonical_density_record_converts_toronto_temperature_fields_to_f(self):
        record = add_city_features({
            **self._base_record(),
            "high_so_far": 25.0,
            "current_temp": 24.0,
            "rise_from_7am": 5.0,
            "forecast_gap": 2.0,
            "final_bucket": 26,
        }, TORONTO, {"climate_normal": 20.0, "climate_std": 3.0})

        converted = canonical_density_record(record)

        self.assertEqual(converted["native_unit"], "C")
        self.assertEqual(converted["final_bucket"], 26)
        self.assertAlmostEqual(converted["final_bucket_f"], 78.8)
        self.assertAlmostEqual(converted["high_so_far"], 77.0)
        self.assertAlmostEqual(converted["current_temp"], 75.2)
        self.assertAlmostEqual(converted["rise_from_7am"], 9.0)
        self.assertAlmostEqual(converted["forecast_gap"], 3.6)
        self.assertAlmostEqual(converted["climate_normal"], 68.0)
        self.assertAlmostEqual(converted["climate_std"], 5.4)

    def test_pooled_density_model_trains_and_predicts_payloads_for_mixed_units(self):
        records = self._density_records()

        artifact, validation_rows = train_pooled_density_models(
            records,
            holdout_year=2025,
            grid_step_f=0.5,
        )
        payloads = predict_density_rows_for_bundle(artifact, records[:6])
        score = evaluate_density_predictions(records[:6], payloads)

        self.assertEqual(artifact["schema_version"], "pooled_continuous_density_hgb_v0.1")
        self.assertEqual(artifact["prediction_mode"], "continuous_density_f")
        self.assertIn("12", artifact["models"])
        self.assertTrue(validation_rows)
        self.assertTrue(all(payload and payload["kind"] == "continuous_density_f" for payload in payloads))
        self.assertEqual(score["n"], 6)
        self.assertGreater(score["winning_bucket_brier"], 0.0)

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

        with patch("weather.calibration.pooled_feature_model.source_daily_indexes", return_value=indexes):
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

        with patch("weather.calibration.pooled_feature_model.source_daily_indexes", return_value=indexes):
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
        self.assertEqual(config["current_blend_market_alpha"]["miami"], 0.0)
        self.assertEqual(config["current_blend_market_alpha"]["san-francisco"], 0.0)

    def test_exact_winner_postprocess_uses_guardrail_alpha_whitelist(self):
        config = default_band_postprocess(exact_winner_catchup_enabled=True)

        self.assertEqual(config["current_blend_default_alpha"], 0.0)
        self.assertEqual(
            config["current_blend_market_alpha"],
            {
                "chicago": 0.10,
                "houston": 0.10,
                "nyc": 0.10,
                "seattle": 0.10,
            },
        )

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

    def test_exact_winner_catchup_contexts_use_inference_available_fields(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        }, source_reliability={"source_best_bucket_match": 0.75})
        row = band_prediction_record(record, "eq", 82, value_hi=83)
        row["source_freshness_state"] = "all_fresh"

        contexts = exact_winner_catchup_contexts(row)

        self.assertTrue(contexts)
        self.assertIn("source_trust=high", contexts[0])
        self.assertIn("source_state=all_fresh", contexts[0])
        self.assertEqual(exact_winner_catchup_contexts(band_prediction_record(record, "gte", 82)), [])

    def test_fit_exact_winner_catchup_boosts_underpredicted_exact_context(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        rows = []
        for _ in range(4):
            row = band_prediction_record(record, "eq", 82)
            row["outcome"] = 1
            rows.append(row)

        calibration = fit_exact_winner_catchup(
            rows,
            [0.25, 0.25, 0.25, 0.25],
            min_rows=1,
            prior_rows=0.0,
            factor_min=0.50,
            factor_max=1.80,
        )

        factor = exact_winner_catchup_factor(rows[0], {"exact_winner_catchup": calibration})
        self.assertAlmostEqual(factor, 1.80)
        self.assertAlmostEqual(
            apply_exact_winner_catchup(0.25, rows[0], {"exact_winner_catchup": calibration}),
            0.45,
        )

    def test_fit_exact_winner_catchup_tunes_strength_to_protect_one_above(self):
        exact_context = {
            "band_kind": "eq",
            "band_below_floor": 0.0,
            "market_id": "nyc",
            "cutoff_hour": 12,
            "band_mid_minus_high_so_far": 0.0,
            "band_mid_minus_forecast": 0.0,
            "band_width": 1.0,
            "source_best_bucket_match": 0.75,
            "source_freshness_state": "all_fresh",
        }
        rows = [
            {
                **exact_context,
                "date": "2025-06-01",
                "settlement_distance": 0,
                "outcome": 1,
            },
            {
                "band_kind": "gte",
                "market_id": "nyc",
                "cutoff_hour": 12,
                "date": "2025-06-01",
                "settlement_distance": 3,
                "outcome": 0,
            },
            {
                **exact_context,
                "date": "2025-06-02",
                "settlement_distance": 1,
                "outcome": 0,
            },
            {
                "band_kind": "gte",
                "market_id": "nyc",
                "cutoff_hour": 12,
                "date": "2025-06-02",
                "settlement_distance": 3,
                "outcome": 0,
            },
        ]
        probabilities = [0.20, 0.80, 0.20, 0.80]

        calibration = fit_exact_winner_catchup(
            rows,
            probabilities,
            min_rows=1,
            prior_rows=0.0,
            factor_min=0.50,
            factor_max=2.00,
            guardrail_rows=rows,
            guardrail_probabilities=probabilities,
            strength_grid=(1.0, 0.0),
            one_above_tolerance=0.0,
            normalization_gamma=1.0,
        )
        diagnostics = calibration["strength_diagnostics"]

        self.assertAlmostEqual(calibration["strength"], 0.0)
        self.assertFalse(diagnostics["candidates"][0]["passed"])
        self.assertGreater(diagnostics["candidates"][0]["one_above_delta_vs_base"], 0)
        self.assertAlmostEqual(
            apply_exact_winner_catchup(0.20, rows[0], {"exact_winner_catchup": calibration}),
            0.20,
        )

    def test_normalize_band_probabilities_for_rows_uses_market_date_hour_partition(self):
        rows = [
            {"market_id": "nyc", "date": "2025-06-01", "cutoff_hour": 12},
            {"market_id": "nyc", "date": "2025-06-01", "cutoff_hour": 12},
            {"market_id": "nyc", "date": "2025-06-01", "cutoff_hour": 13},
        ]

        normalized = normalize_band_probabilities_for_rows(rows, [0.25, 0.75, 0.40], gamma=1.0)

        self.assertAlmostEqual(sum(normalized[:2]), 1.0)
        self.assertAlmostEqual(normalized[2], 1.0)

    def test_exact_winner_catchup_is_disabled_by_default_postprocess(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        row = band_prediction_record(record, "eq", 82)
        config = default_band_postprocess()
        config["exact_winner_catchup"] = {
            "contexts": {
                exact_winner_catchup_contexts(row)[0]: {"factor": 1.80},
            }
        }

        self.assertFalse(config["exact_winner_catchup_enabled"])
        self.assertAlmostEqual(apply_band_postprocessing(0.25, row, config), 0.25)

    def test_dynamic_source_state_features_capture_failed_stale_and_ages(self):
        features = dynamic_source_state_features(
            sources={
                "wu_history": {
                    "ok": False,
                    "status": "failed",
                    "data": {"rows": [{"time": "11:53"}]},
                },
                "metar": {"ok": True, "status": "stale_cache", "stale": True, "cache_age_minutes": 18},
                "weather_forecast": {"ok": False, "status": "failed", "cache_age_minutes": 95},
                "open_meteo": {"ok": True, "status": "fresh", "cache_age_minutes": 8},
            },
            base_features={
                "cutoff_hour": 12,
                "minutes_since_cutoff": 15,
                "forecast_disagreement": 3.25,
            },
        )

        self.assertIn("failed:", features["source_status_group"])
        self.assertIn("stale:metar", features["source_status_group"])
        self.assertEqual(features["source_failed_count"], 2.0)
        self.assertEqual(features["source_stale_count"], 1.0)
        self.assertEqual(features["source_wu_history_failed"], 1.0)
        self.assertEqual(features["source_wu_history_latest_minute"], 713)
        self.assertAlmostEqual(features["source_wu_history_age_minutes"], 22.0)
        self.assertEqual(features["source_metar_stale"], 1.0)
        self.assertEqual(features["source_forecast_failed_count"], 1.0)
        self.assertAlmostEqual(features["source_forecast_payload_age_minutes"], 8.0)
        self.assertAlmostEqual(features["source_cross_source_max_disagreement"], 3.25)

    def test_dynamic_source_state_can_derive_from_source_status_rows(self):
        features = dynamic_source_state_features(
            source_status_rows=[
                {
                    "source": "wu_history",
                    "ok": "true",
                    "status": "fresh",
                    "stale": "false",
                    "age_minutes": "4.5",
                    "row_count": "12",
                },
                {
                    "source": "open_meteo",
                    "ok": "true",
                    "status": "fresh",
                    "stale": "false",
                    "age_minutes": "9",
                },
            ],
            base_features={"forecast_disagreement": 1.5},
        )

        self.assertEqual(features["source_status_group"], "all_fresh")
        self.assertEqual(features["source_state_all_fresh"], 1.0)
        self.assertAlmostEqual(features["source_wu_history_age_minutes"], 4.5)
        self.assertAlmostEqual(features["source_wu_history_row_count"], 12.0)
        self.assertAlmostEqual(features["source_cross_source_max_disagreement"], 1.5)

    def test_band_feature_frame_dynamic_source_state_is_opt_in_and_reindexed(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        add_dynamic_source_state_features(record, historical_default=True)
        row = band_prediction_record(record, "eq", 82)

        default_frame = band_feature_frame([row])
        dynamic_frame = band_feature_frame([row], include_dynamic_source_state=True)
        reindexed = band_feature_frame([row], feature_names=list(dynamic_frame.columns))

        self.assertNotIn("source_wu_history_age_minutes", default_frame.columns)
        self.assertIn("source_wu_history_age_minutes", dynamic_frame.columns)
        self.assertIn("source_status_group_all_fresh", dynamic_frame.columns)
        self.assertAlmostEqual(dynamic_frame.loc[0, "source_wu_history_age_minutes"], 30.0)
        self.assertAlmostEqual(reindexed.loc[0, "source_wu_history_age_minutes"], 30.0)


if __name__ == "__main__":
    unittest.main()
