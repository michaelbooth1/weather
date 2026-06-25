import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from weather.market.market_registry import NYC, SEATTLE, TORONTO
from weather.calibration.feature_model import feature_model_frame
from weather.calibration.pooled_feature_model import (
    BAND_MERGE_PAYLOAD_KEY,
    FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION,
    FEATURE_SUBSET_FORECAST_PROFILE,
    FEATURE_SUBSET_MARINE_WATER_CONTRAST,
    add_city_features,
    add_dynamic_source_state_features,
    adjacent_calibration_contexts,
    adjacent_calibration_factor,
    apply_band_postprocessing,
    apply_adjacent_calibration,
    apply_exact_winner_catchup,
    apply_forecast_centering,
    apply_market_bias_calibration,
    apply_forecast_relative_density_calibration,
    apply_reanalysis_lane_metadata,
    apply_reanalysis_promotion_lane_to_record,
    band_feature_frame,
    band_prediction_record,
    band_training_support,
    build_band_rows,
    canonical_density_record,
    density_residuals_from_means,
    default_band_postprocess,
    dynamic_source_state_features,
    evaluate_density_predictions,
    exact_winner_catchup_contexts,
    exact_winner_catchup_factor,
    feature_frame,
    fit_density_market_band_postprocess,
    fit_adjacent_calibration,
    fit_exact_winner_catchup,
    fit_market_bias_calibration,
    forecast_anchor_probability,
    hard_floor_probability,
    historical_only_source_feature_manifest,
    late_lockin_strength_from_features,
    market_source_reliability,
    market_bias_calibration_contexts,
    merge_pooled_band_artifacts,
    normalize_band_probabilities_for_rows,
    density_market_band_score,
    preflight_training_artifacts,
    predict_density_rows_for_bundle,
    support_floor_cap,
    train_pooled_band_models,
    train_pooled_density_models,
    tune_density_shape_policy,
    tune_density_sigma_f,
    write_density_report,
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

    def _band_shard_artifact(self, hour, objective="binary_market_band_brier_source_reliability"):
        postprocess = default_band_postprocess()
        rows = []
        probabilities = []
        for idx in range(12):
            rows.append({
                "market_id": "austin",
                "cutoff_hour": int(hour),
                "band_kind": "eq",
                "band_value": 90 + (idx % 3),
                "band_value_hi": None,
                "observed_floor_bucket": 89,
                "observed_support_bucket": 89,
                "band_mid_minus_high_so_far": float(idx % 4),
                "outcome": 1 if idx % 5 == 0 else 0,
            })
            probabilities.append(0.18 + (idx % 4) * 0.02)
        return {
            "schema_version": "pooled_feature_band_hgb_v0.3",
            "feature_schema_version": "toronto_feature_store_v1.6",
            "family_unit": "F",
            "prediction_mode": "band_binary",
            "objective": objective,
            "feature_subset": "all",
            "feature_subset_contract": {"subset": "all"},
            "dynamic_source_state_enabled": False,
            "dynamic_source_state_columns": [],
            "source_family_lanes": {
                "reanalysis_synoptic": {"allowed_markets": ["austin"]},
            },
            "reanalysis_promotion_lane": {"allowed_markets": ["austin"]},
            "support": {"F": {"low": 70, "high": 110}},
            "postprocess": postprocess,
            "models": {
                str(hour): {
                    "feature_names": ["forecast_high"],
                    "postprocess": dict(postprocess),
                    "train_rows": 12,
                    "source_rows": 3,
                },
            },
            BAND_MERGE_PAYLOAD_KEY: {
                "holdout_year": 2025,
                "hours": [int(hour)],
                "rows": rows,
                "probabilities": probabilities,
            },
        }

    def test_merge_pooled_band_artifacts_refits_postprocess_and_combines_hours(self):
        merged = merge_pooled_band_artifacts(
            [
                self._band_shard_artifact(7),
                self._band_shard_artifact(8),
            ],
            required_hours=(7, 8),
            shard_paths=("hour07.pkl", "hour08.pkl"),
        )

        self.assertEqual(sorted(merged["models"]), ["7", "8"])
        self.assertEqual(merged["training_shards"]["shard_count"], 2)
        self.assertEqual(merged["training_shards"]["postprocess_fit_rows"], 24)
        self.assertIn("adjacent_calibration", merged["postprocess"])
        self.assertIn("market_bias_calibration", merged["postprocess"])
        self.assertEqual(
            merged["models"]["7"]["postprocess"],
            merged["postprocess"],
        )

    def test_merge_pooled_band_artifacts_rejects_missing_required_hour(self):
        with self.assertRaisesRegex(ValueError, "missing required hour"):
            merge_pooled_band_artifacts(
                [self._band_shard_artifact(7)],
                required_hours=(7, 8),
            )

    def test_merge_pooled_band_artifacts_rejects_incompatible_shard(self):
        with self.assertRaisesRegex(ValueError, "incompatible"):
            merge_pooled_band_artifacts([
                self._band_shard_artifact(7),
                self._band_shard_artifact(8, objective="different_objective"),
            ])

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

    def test_feature_frame_builders_do_not_emit_fragmentation_warnings(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        band = band_prediction_record(record, "eq", 80)

        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.PerformanceWarning)
            pooled = feature_frame(
                [record],
                include_historical_only=True,
                include_dynamic_source_state=True,
            )
            band_frame = band_feature_frame(
                [band],
                include_historical_only=True,
                include_dynamic_source_state=True,
            )
            per_market, feature_cols = feature_model_frame(
                [self._base_record()],
                ["S-SW", "Other/variable"],
                ["Fair/clear", "Other"],
            )

        self.assertIn("source_supplemental_available", pooled.columns)
        self.assertIn("band_mid", band_frame.columns)
        self.assertIn("wind_S-SW", per_market.columns)
        self.assertIn("wind_S-SW", feature_cols)

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
        with tempfile.TemporaryDirectory() as tmp:
            report_path = write_density_report(
                Path(tmp) / "density_report.md",
                records,
                {"nyc": len(records)},
                validation_rows,
                2025,
                "artifact.pkl",
                artifact=artifact,
            )
            report = Path(report_path).read_text(encoding="utf-8")
        payloads = predict_density_rows_for_bundle(artifact, records[:6])
        score = evaluate_density_predictions(records[:6], payloads)

        self.assertEqual(artifact["schema_version"], "pooled_continuous_density_hgb_v0.7")
        self.assertEqual(artifact["prediction_mode"], "continuous_density_f")
        self.assertEqual(artifact["sigma_policy"]["preferred"], "holdout_market_band_brier_grid_search")
        self.assertEqual(
            artifact["density_shape_policy"]["preferred"],
            "holdout_market_band_brier_shape_grid_search",
        )
        self.assertEqual(artifact["density_postprocess"]["schema_version"], "density_market_band_postprocess_v0.2")
        self.assertGreater(artifact["density_postprocess"]["calibration_rows"], 0)
        self.assertIn("forecast_relative_calibration", artifact["density_postprocess"])
        self.assertIn("12", artifact["models"])
        self.assertEqual(artifact["models"]["12"]["sigma_source"], "holdout_market_band_brier_shape_grid_search")
        self.assertEqual(artifact["models"]["12"]["sigma_residual_count"], 20)
        self.assertIn("sigma_tuning", artifact["models"]["12"])
        self.assertIn("density_shape", artifact["models"]["12"])
        self.assertIn("density_shape_tuning", artifact["models"]["12"])
        self.assertTrue(validation_rows)
        self.assertEqual(validation_rows[0]["final_sigma_source"], "holdout_market_band_brier_shape_grid_search")
        self.assertIn("final_density_shape_id", validation_rows[0])
        self.assertEqual(validation_rows[0]["holdout_sigma_residual_count"], 20)
        self.assertIn("baseline_eval_score", validation_rows[0])
        self.assertIn("market_band_brier", validation_rows[0]["eval_score"])
        self.assertIn("sigma_tuning", validation_rows[0])
        self.assertIn("density_shape_tuning", validation_rows[0])
        self.assertIn("training_metrics", validation_rows[0])
        self.assertIn("matrix_build_seconds", validation_rows[0]["training_metrics"])
        self.assertIn("Training Throughput", report)
        self.assertIn("Matrix Columns", report)
        self.assertIn("holdout_market_band_brier_shape_grid_search", report)
        self.assertIn("Tuned Band Brier", report)
        self.assertIn("Shape", report)
        self.assertIn("Density Market-Band Postprocess", report)
        self.assertTrue(all(payload and payload["kind"] == "continuous_density_f" for payload in payloads))
        self.assertTrue(all(payload.get("density_shape_id") for payload in payloads))
        self.assertEqual(score["n"], 6)
        self.assertGreater(score["winning_bucket_brier"], 0.0)

    def test_mixed_unit_band_training_support_stays_native(self):
        nyc_record = add_city_features({
            **self._base_record(),
            "market_id": "nyc",
            "final_bucket": 83,
            "high_so_far": 80.0,
            "forecast_high": 84.0,
        }, NYC, {"climate_normal": 82.0, "climate_std": 5.0})
        toronto_record = add_city_features({
            **self._base_record(),
            "market_id": "toronto",
            "final_bucket": 26,
            "high_so_far": 25.0,
            "current_temp": 24.0,
            "live_reading_temp": 24.5,
            "forecast_high": 27.0,
        }, TORONTO, {"climate_normal": 24.0, "climate_std": 3.0})
        support = band_training_support([nyc_record, toronto_record], family_unit="all")

        rows = build_band_rows([nyc_record, toronto_record], support)
        nyc_values = [row["band_value"] for row in rows if row["market_id"] == "nyc"]
        toronto_values = [row["band_value"] for row in rows if row["market_id"] == "toronto"]

        self.assertEqual(set(support), {"C", "F"})
        self.assertTrue(nyc_values)
        self.assertTrue(toronto_values)
        self.assertGreater(min(nyc_values), 60)
        self.assertLess(max(toronto_values), 40)

    def test_pooled_band_model_can_train_mixed_unit_all_family_artifact(self):
        records = []
        for idx in range(120):
            final_bucket = 80 + (idx % 5)
            records.append(add_city_features({
                **self._base_record(),
                "market_id": "nyc",
                "high_so_far": 77.0 + (idx % 3),
                "forecast_high": final_bucket + 0.25,
                "final_bucket": final_bucket,
                "cutoff_hour": 12,
                "year": 2024 if idx < 80 else 2025,
            }, NYC, {"climate_normal": 82.0, "climate_std": 5.0}))
            c_bucket = 24 + (idx % 5)
            records.append(add_city_features({
                **self._base_record(),
                "market_id": "toronto",
                "high_so_far": 22.0 + (idx % 3),
                "current_temp": 22.0 + (idx % 2),
                "live_reading_temp": 22.5 + (idx % 2),
                "forecast_high": c_bucket + 0.25,
                "final_bucket": c_bucket,
                "cutoff_hour": 12,
                "year": 2024 if idx < 80 else 2025,
            }, TORONTO, {"climate_normal": 24.0, "climate_std": 3.0}))

        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            family_unit="all",
        )
        feature_names = set(artifact["models"]["12"]["feature_names"])

        self.assertEqual(artifact["family_unit"], "all")
        self.assertEqual(artifact["schema_version"], "pooled_all_market_band_hgb_v0.1")
        self.assertEqual(set(artifact["support"]), {"C", "F"})
        self.assertIn("market_id_nyc", feature_names)
        self.assertIn("market_id_toronto", feature_names)
        self.assertIn("market_bias_calibration", artifact["postprocess"])
        self.assertIn("market_bias_calibration_enabled", artifact["models"]["12"]["postprocess"])
        self.assertTrue(validation_rows)

    def test_all_market_exact_winner_keeps_item35_blend_and_source_guardrail(self):
        records = []
        for idx in range(120):
            final_bucket = 80 + (idx % 5)
            records.append(add_city_features({
                **self._base_record(),
                "market_id": "nyc",
                "high_so_far": 77.0 + (idx % 3),
                "forecast_high": final_bucket + 0.25,
                "final_bucket": final_bucket,
                "cutoff_hour": 12,
                "year": 2024 if idx < 80 else 2025,
            }, NYC, {"climate_normal": 82.0, "climate_std": 5.0}))
            c_bucket = 24 + (idx % 5)
            records.append(add_city_features({
                **self._base_record(),
                "market_id": "toronto",
                "high_so_far": 22.0 + (idx % 3),
                "current_temp": 22.0 + (idx % 2),
                "live_reading_temp": 22.5 + (idx % 2),
                "forecast_high": c_bucket + 0.25,
                "final_bucket": c_bucket,
                "cutoff_hour": 12,
                "year": 2024 if idx < 80 else 2025,
            }, TORONTO, {"climate_normal": 24.0, "climate_std": 3.0}))

        artifact, _validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            exact_winner_catchup=True,
            family_unit="all",
            source_freshness_guardrail=True,
        )
        postprocess = artifact["postprocess"]

        self.assertEqual(artifact["schema_version"], "pooled_all_market_band_hgb_exact_winner_v0.1")
        self.assertEqual(
            artifact["objective"],
            "binary_native_market_band_brier_all_market_exact_winner_catchup",
        )
        self.assertTrue(postprocess["exact_winner_catchup_enabled"])
        self.assertEqual(postprocess["current_blend_default_alpha"], 1.0)
        self.assertEqual(postprocess["current_blend_market_alpha"]["nyc"], 0.20)
        self.assertEqual(postprocess["current_blend_source_freshness_default_alpha"], 0.0)
        self.assertEqual(postprocess["current_blend_source_freshness_alpha"], {"all_fresh": 1.0})
        self.assertEqual(
            artifact["models"]["12"]["postprocess"]["source_freshness_guardrail_policy"],
            "item35_all_fresh_only_candidate_v0_1",
        )

    def test_density_sigma_falls_back_to_in_sample_when_holdout_is_too_small(self):
        records = self._density_records()[:65]

        artifact, validation_rows = train_pooled_density_models(
            records,
            holdout_year=2025,
            grid_step_f=1.0,
        )

        self.assertEqual(artifact["models"]["12"]["sigma_source"], "in_sample_residual_rmse")
        self.assertEqual(artifact["models"]["12"]["density_shape_id"], "gaussian")
        self.assertLess(validation_rows[0]["holdout_sigma_residual_count"], 20)
        self.assertEqual(validation_rows[0]["final_sigma_source"], "in_sample_residual_rmse")
        self.assertEqual(validation_rows[0]["final_density_shape_source"], "gaussian_fallback")

    def test_density_residuals_from_means_uses_canonical_f_targets(self):
        rows = [
            {"final_bucket_f": 80.0},
            {"final_bucket_f": 82.0},
            {"final_bucket_f": None},
        ]

        self.assertEqual(density_residuals_from_means(rows, [79.5, 82.25, 70.0]), [0.5, -0.25])

    def test_density_sigma_tuning_prefers_market_band_brier(self):
        rows = [
            {"market_id": "nyc", "final_bucket": 80, "unit": "F", "cutoff_hour": 12}
            for _ in range(20)
        ]
        means = [81.2 for _ in rows]
        grid = [round(72.0 + idx * 0.1, 6) for idx in range(181)]

        tuned = tune_density_sigma_f(rows, means, grid, base_sigma_f=3.0)
        direct_score = density_market_band_score(rows, means, grid, tuned["selected_sigma_f"])

        self.assertIsNotNone(tuned)
        self.assertIsNotNone(direct_score)
        self.assertIn("market_band_brier", tuned["selected_score"])
        baseline = next(
            row for row in tuned["candidates"]
            if abs(row["sigma_f"] - tuned["base_sigma_f"]) < 1e-9
        )
        self.assertLess(
            tuned["selected_score"]["market_band_brier"],
            baseline["market_band_brier"],
        )
        self.assertAlmostEqual(
            tuned["selected_score"]["market_band_brier"],
            direct_score["market_band_brier"],
        )

    def test_density_market_band_postprocess_fits_exact_and_adjacent_contexts(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        }, source_reliability={"source_best_bucket_match": 0.80})
        rows = []
        probabilities = []
        for _ in range(90):
            exact = band_prediction_record(record, "eq", 82)
            exact["outcome"] = 1
            exact["source_freshness_state"] = "all_fresh"
            exact["settlement_distance"] = 0
            rows.append(exact)
            probabilities.append(0.20)

            adjacent = band_prediction_record(record, "eq", 83)
            adjacent["outcome"] = 0
            adjacent["source_freshness_state"] = "all_fresh"
            adjacent["settlement_distance"] = 1
            rows.append(adjacent)
            probabilities.append(0.40)

        postprocess = fit_density_market_band_postprocess(rows, probabilities)

        self.assertTrue(postprocess["enabled"])
        self.assertEqual(postprocess["schema_version"], "density_market_band_postprocess_v0.2")
        self.assertGreater(postprocess["adjacent_calibration"]["context_count"], 0)
        self.assertGreater(postprocess["exact_winner_catchup"]["context_count"], 0)
        self.assertIn("strength", postprocess["exact_winner_catchup"])

    def test_density_market_band_postprocess_fits_forecast_relative_contexts(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        record["forecast_high"] = 82.0
        record["forecast_source_count"] = 2
        record["forecast_disagreement"] = 0.4
        rows = []
        probabilities = []
        for _ in range(130):
            row = band_prediction_record(record, "gte", 82)
            row["outcome"] = 0
            row["settlement_distance"] = 2
            rows.append(row)
            probabilities.append(0.50)

        postprocess = fit_density_market_band_postprocess(rows, probabilities)
        calibrated = apply_forecast_relative_density_calibration(
            0.50,
            rows[0],
            config={
                "forecast_relative_calibration": postprocess["forecast_relative_calibration"],
            },
        )

        self.assertTrue(postprocess["enabled"])
        self.assertGreater(postprocess["forecast_relative_calibration"]["context_count"], 0)
        self.assertGreater(postprocess["forecast_relative_calibration"]["strength"], 0.0)
        self.assertLess(calibrated, 0.50)

    def test_density_shape_tuning_can_select_forecast_anchor_mixture(self):
        rows = [
            {
                "market_id": "nyc",
                "final_bucket": 80,
                "unit": "F",
                "cutoff_hour": 12,
                "forecast_high": 80.0,
                "climate_normal": 70.0,
            }
            for _ in range(20)
        ]
        means = [86.0 for _ in rows]
        grid = [round(72.0 + idx * 0.1, 6) for idx in range(201)]

        tuned = tune_density_shape_policy(rows, means, grid, base_sigma_f=1.0)
        direct_score = density_market_band_score(
            rows,
            means,
            grid,
            tuned["selected_sigma_f"],
            shape_config=tuned["selected_density_shape"],
        )
        baseline = next(
            row for row in tuned["candidates"]
            if row["density_shape_id"] == "gaussian"
            and abs(row["sigma_f"] - tuned["base_sigma_f"]) < 1e-9
        )

        self.assertIsNotNone(tuned)
        self.assertTrue(tuned["selected_density_shape_id"].startswith("forecast_w"))
        self.assertLess(
            tuned["selected_score"]["market_band_brier"],
            baseline["market_band_brier"],
        )
        self.assertAlmostEqual(
            tuned["selected_score"]["market_band_brier"],
            direct_score["market_band_brier"],
        )

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

    def test_forecast_centering_postprocess_blends_toward_forecast_anchor(self):
        record = self._base_record()
        record["cutoff_hour"] = 3
        record["high_so_far"] = 78.0
        record["forecast_high"] = 84.0
        near_forecast = band_prediction_record(record, "eq", 84)
        away_from_forecast = band_prediction_record(record, "eq", 79)
        config = {
            "forecast_centering_enabled": True,
            "forecast_centering_early_alpha": 0.5,
            "forecast_centering_sigma": 1.25,
        }

        boosted = apply_forecast_centering(0.10, near_forecast, config)
        reduced = apply_forecast_centering(0.30, away_from_forecast, config)

        self.assertGreater(forecast_anchor_probability(near_forecast), forecast_anchor_probability(away_from_forecast))
        self.assertGreater(boosted, 0.10)
        self.assertLess(reduced, 0.30)

    def test_reanalysis_promotion_lane_masks_quarantined_market_and_tags_artifact(self):
        lane = {
            "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
            "allowed_markets": ["austin"],
            "quarantined_markets": ["nyc"],
        }
        allowed = {
            "market_id": "austin",
            "reanalysis_synoptic_available": 1.0,
            "reanalysis_prev_day_max_temp": 91.0,
        }
        quarantined = {
            "market_id": "nyc",
            "reanalysis_synoptic_available": 1.0,
            "reanalysis_prev_day_max_temp": 82.0,
        }

        self.assertEqual(
            apply_reanalysis_promotion_lane_to_record(allowed, lane)["reanalysis_prev_day_max_temp"],
            91.0,
        )
        masked = apply_reanalysis_promotion_lane_to_record(quarantined, lane)
        artifact = apply_reanalysis_lane_metadata(
            {"objective": "candidate", "postprocess": {"current_blend_market_alpha": {}}, "models": {"7": {}}},
            lane,
        )

        self.assertEqual(masked["reanalysis_synoptic_available"], 0.0)
        self.assertIsNone(masked["reanalysis_prev_day_max_temp"])
        self.assertEqual(
            artifact["source_family_lanes"]["reanalysis_synoptic"]["status"],
            "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
        )
        self.assertEqual(artifact["postprocess"]["current_blend_market_alpha"]["nyc"], 0.0)
        self.assertEqual(artifact["models"]["7"]["postprocess"]["current_blend_market_alpha"]["nyc"], 0.0)

    def test_reanalysis_promotion_lane_can_block_pressure_subfamily_only(self):
        lane = {
            "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
            "allowed_markets": ["austin"],
            "blocked_feature_prefixes": ["reanalysis_prev_day_temperature_850hpa"],
            "blocked_feature_columns": [
                "reanalysis_pressure_level_available",
                "reanalysis_prev_day_geopotential_height_500hpa_m",
                "reanalysis_prev_day_thickness_1000_500hpa_m",
            ],
        }
        record = {
            "market_id": "austin",
            "reanalysis_synoptic_available": 1.0,
            "reanalysis_pressure_level_available": 1.0,
            "reanalysis_prev_day_max_temp": 91.0,
            "reanalysis_prev_day_temperature_850hpa_c": 12.5,
            "reanalysis_prev_day_geopotential_height_500hpa_m": 5900.0,
            "reanalysis_prev_day_thickness_1000_500hpa_m": 5600.0,
        }

        masked = apply_reanalysis_promotion_lane_to_record(record, lane)

        self.assertEqual(masked["reanalysis_synoptic_available"], 1.0)
        self.assertEqual(masked["reanalysis_prev_day_max_temp"], 91.0)
        self.assertIsNone(masked["reanalysis_pressure_level_available"])
        self.assertIsNone(masked["reanalysis_prev_day_temperature_850hpa_c"])
        self.assertIsNone(masked["reanalysis_prev_day_geopotential_height_500hpa_m"])
        self.assertIsNone(masked["reanalysis_prev_day_thickness_1000_500hpa_m"])

    def test_training_output_preflight_blocks_before_low_disk_artifact_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "candidate.pkl"
            report = Path(tmp) / "candidate_report.md"

            with self.assertRaises(OSError) as caught:
                preflight_training_artifacts(
                    artifact,
                    report,
                    min_free_bytes=10**18,
                )

        self.assertIn("pooled feature model training outputs", str(caught.exception))

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

    def test_market_bias_calibration_uses_inference_contexts_and_gated_factor(self):
        record = add_city_features(self._base_record(), NYC, {
            "climate_normal": 82.0,
            "climate_std": 5.0,
        })
        rows = []
        for _ in range(4):
            row = band_prediction_record(record, "eq", 82)
            row["outcome"] = 1
            rows.append(row)

        calibration = fit_market_bias_calibration(
            rows,
            [0.20, 0.20, 0.20, 0.20],
            min_rows=1,
            prior_rows=0.0,
            factor_max=2.25,
            min_improvement=0.0,
        )
        context = market_bias_calibration_contexts(rows[0])[0]

        self.assertTrue(calibration["enabled"])
        self.assertIn(context, calibration["contexts"])
        self.assertGreater(
            apply_market_bias_calibration(0.20, rows[0], {"market_bias_calibration": calibration}),
            0.20,
        )

    def test_market_bias_calibration_honors_market_and_source_state_guardrails(self):
        record = add_city_features(self._base_record(), TORONTO, {
            "climate_normal": 24.0,
            "climate_std": 3.0,
        })
        toronto = band_prediction_record(record, "eq", 25)
        toronto["source_freshness_state"] = "all_fresh"
        degraded = {**toronto, "market_id": "nyc", "source_freshness_state": "failed:wu_history"}
        healthy = {**toronto, "market_id": "nyc", "source_freshness_state": "all_fresh"}
        calibration = {
            "enabled": True,
            "excluded_markets": ["toronto"],
            "allowed_source_freshness_states": ["all_fresh"],
            "contexts": {
                market_bias_calibration_contexts(healthy)[0]: {"factor": 2.0},
                market_bias_calibration_contexts(toronto)[0]: {"factor": 2.0},
            },
        }

        self.assertAlmostEqual(
            apply_market_bias_calibration(0.20, toronto, {"market_bias_calibration": calibration}),
            0.20,
        )
        self.assertAlmostEqual(
            apply_market_bias_calibration(0.20, degraded, {"market_bias_calibration": calibration}),
            0.20,
        )
        self.assertGreater(
            apply_market_bias_calibration(0.20, healthy, {"market_bias_calibration": calibration}),
            0.20,
        )

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

    def test_forecast_profile_band_subset_excludes_observed_path_columns(self):
        records = []
        for idx in range(80):
            final_bucket = 80 + (idx % 5)
            record = {
                **self._base_record(),
                "market_id": "nyc",
                "high_so_far": 74.0 + (idx % 3),
                "current_temp": 75.0 + (idx % 3),
                "forecast_high": final_bucket + 0.25,
                "forecast_gap": 4.0 + (idx % 2),
                "forecast_source_count": 3,
                "forecast_disagreement": 0.5 + (idx % 4) * 0.25,
                "forecast_temp_14": final_bucket - 0.5,
                "forecast_remaining_degree_hours": 10.0 + idx,
                "forecast_total_cloud_mean": 20.0,
                "forecast_global_ensemble_spread": 1.5,
                "final_bucket": final_bucket,
                "cutoff_hour": 8,
                "year": 2024 if idx < 60 else 2025,
            }
            records.append(add_city_features(record, NYC, {
                "climate_normal": 82.0,
                "climate_std": 5.0,
            }))

        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            feature_subset=FEATURE_SUBSET_FORECAST_PROFILE,
        )
        feature_names = set(artifact["models"]["8"]["feature_names"])

        self.assertEqual(artifact["schema_version"], "pooled_feature_band_hgb_forecast_profile_v0.1")
        self.assertEqual(artifact["feature_subset"], FEATURE_SUBSET_FORECAST_PROFILE)
        self.assertEqual(
            artifact["forecast_profile_calibration"]["anchor_feature"],
            "forecast_high",
        )
        self.assertTrue(validation_rows)
        self.assertIn("forecast_high", feature_names)
        self.assertIn("forecast_gap", feature_names)
        self.assertIn("forecast_temp_14", feature_names)
        self.assertIn("band_mid_minus_forecast", feature_names)
        self.assertIn("market_id_nyc", feature_names)
        self.assertNotIn("high_so_far", feature_names)
        self.assertNotIn("current_temp", feature_names)
        self.assertNotIn("live_reading_temp", feature_names)
        self.assertNotIn("band_mid_minus_high_so_far", feature_names)

    def test_pooled_band_model_can_train_forecast_radiation_subset(self):
        records = []
        for idx in range(80):
            final_bucket = 80 + (idx % 5)
            record = {
                **self._base_record(),
                "market_id": "nyc",
                "high_so_far": 74.0 + (idx % 3),
                "current_temp": 75.0 + (idx % 3),
                "forecast_high": final_bucket + 0.25,
                "forecast_gap": 4.0 + (idx % 2),
                "forecast_temp_14": final_bucket - 0.5,
                "forecast_remaining_solar_sum": 1200.0 + idx,
                "forecast_next_3h_solar_mean": 400.0 + (idx % 9),
                "forecast_total_cloud_mean": 20.0 + (idx % 7),
                "forecast_total_cloud_max": 45.0 + (idx % 5),
                "forecast_low_cloud_mean": 14.0 + (idx % 3),
                "forecast_low_cloud_max": 30.0 + (idx % 5),
                "forecast_mid_cloud_mean": 8.0 + (idx % 4),
                "forecast_high_cloud_mean": 5.0 + (idx % 6),
                "forecast_cloud_trend_3h": -2.0 + (idx % 5),
                "forecast_remaining_direct_radiation_sum": 800.0 + idx,
                "forecast_remaining_diffuse_radiation_sum": 300.0 + (idx % 11),
                "forecast_next_3h_direct_radiation_mean": 260.0 + (idx % 13),
                "forecast_next_3h_diffuse_radiation_mean": 90.0 + (idx % 3),
                "forecast_remaining_direct_radiation_share": 0.70,
                "forecast_next_3h_direct_radiation_share": 0.74,
                "forecast_global_ensemble_spread": 1.5,
                "final_bucket": final_bucket,
                "cutoff_hour": 8,
                "year": 2024 if idx < 60 else 2025,
            }
            records.append(add_city_features(record, NYC, {
                "climate_normal": 82.0,
                "climate_std": 5.0,
            }))

        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            feature_subset=FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION,
        )
        feature_names = set(artifact["models"]["8"]["feature_names"])

        self.assertEqual(artifact["schema_version"], "pooled_feature_band_hgb_forecast_radiation_v0.1")
        self.assertEqual(artifact["feature_subset"], FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION)
        self.assertEqual(
            artifact["feature_subset_contract"]["allowed_feature_families"],
            [
                "forecast_cloud_solar_radiation",
                "market_climate_context",
                "forecast_relative_band_geometry",
            ],
        )
        self.assertEqual(
            artifact["forecast_radiation_calibration"]["anchor_feature"],
            "forecast_high",
        )
        self.assertTrue(validation_rows)
        self.assertIn("forecast_remaining_solar_sum", feature_names)
        self.assertIn("forecast_remaining_direct_radiation_sum", feature_names)
        self.assertIn("forecast_next_3h_direct_radiation_share", feature_names)
        self.assertIn("forecast_total_cloud_mean", feature_names)
        self.assertIn("band_mid_minus_forecast", feature_names)
        self.assertIn("market_id_nyc", feature_names)
        self.assertNotIn("forecast_high", feature_names)
        self.assertNotIn("forecast_gap", feature_names)
        self.assertNotIn("forecast_temp_14", feature_names)
        self.assertNotIn("high_so_far", feature_names)
        self.assertNotIn("current_temp", feature_names)
        self.assertNotIn("live_reading_temp", feature_names)
        self.assertNotIn("band_mid_minus_high_so_far", feature_names)

    def test_pooled_band_model_can_train_marine_water_contrast_subset(self):
        records = []
        for idx in range(80):
            final_bucket = 80 + (idx % 5)
            cooling = 8.0 + (idx % 4)
            record = {
                **self._base_record(),
                "market_id": "nyc",
                "high_so_far": 74.0 + (idx % 3),
                "current_temp": 75.0 + (idx % 3),
                "forecast_high": final_bucket + 0.25,
                "forecast_gap": 4.0 + (idx % 2),
                "forecast_temp_14": final_bucket - 0.5,
                "marine_station_count": 1.0,
                "marine_latest_age_minutes": 15.0 + (idx % 5),
                "marine_missing_sensor_count": 0.0,
                "marine_water_temp_native": final_bucket - cooling,
                "marine_water_minus_forecast_high": -cooling,
                "marine_wind_speed_kmh": 12.0 + (idx % 6),
                "marine_onshore_flow": 1.0 if idx % 2 == 0 else 0.0,
                "marine_offshore_flow": 0.0 if idx % 2 == 0 else 1.0,
                "marine_onshore_water_minus_forecast_high": -cooling if idx % 2 == 0 else 0.0,
                "marine_onshore_cooling_potential": cooling if idx % 2 == 0 else 0.0,
                "marine_breeze_risk": 1.0 if idx % 2 == 0 else 0.0,
                "marine_layer_suppression": 0.0,
                "final_bucket": final_bucket,
                "cutoff_hour": 8,
                "year": 2024 if idx < 60 else 2025,
            }
            records.append(add_city_features(record, NYC, {
                "climate_normal": 82.0,
                "climate_std": 5.0,
            }))

        artifact, validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            feature_subset=FEATURE_SUBSET_MARINE_WATER_CONTRAST,
        )
        feature_names = set(artifact["models"]["8"]["feature_names"])

        self.assertEqual(artifact["schema_version"], "pooled_feature_band_hgb_marine_contrast_v0.1")
        self.assertEqual(artifact["feature_subset"], FEATURE_SUBSET_MARINE_WATER_CONTRAST)
        self.assertEqual(
            artifact["feature_subset_contract"]["allowed_feature_families"],
            [
                "marine_context",
                "market_climate_context",
                "market_band_geometry",
            ],
        )
        self.assertEqual(
            artifact["marine_contrast_calibration"]["anchor_feature"],
            "marine_water_minus_forecast_high",
        )
        self.assertTrue(validation_rows)
        self.assertIn("marine_water_minus_forecast_high", feature_names)
        self.assertIn("marine_onshore_water_minus_forecast_high", feature_names)
        self.assertIn("marine_onshore_cooling_potential", feature_names)
        self.assertIn("marine_breeze_risk", feature_names)
        self.assertIn("band_mid_anomaly", feature_names)
        self.assertIn("market_id_nyc", feature_names)
        self.assertNotIn("forecast_high", feature_names)
        self.assertNotIn("forecast_temp_14", feature_names)
        self.assertNotIn("high_so_far", feature_names)
        self.assertNotIn("current_temp", feature_names)
        self.assertNotIn("live_reading_temp", feature_names)
        self.assertNotIn("band_mid_minus_forecast", feature_names)

    def test_pooled_band_model_records_weak_input_family_preflight(self):
        records = []
        for idx in range(80):
            final_bucket = 80 + (idx % 5)
            record = {
                **self._base_record(),
                "market_id": "nyc",
                "forecast_high": final_bucket + 0.25,
                "forecast_gap": 4.0 + (idx % 2),
                "final_bucket": final_bucket,
                "cutoff_hour": 8,
                "year": 2024 if idx < 60 else 2025,
            }
            records.append(add_city_features(record, NYC, {
                "climate_normal": 82.0,
                "climate_std": 5.0,
            }))
        weak_policy = {
            "families": [
                {
                    "family": "surface_weather",
                    "disposition": "diagnostic_only",
                    "coverage": {
                        "low_coverage_feature_count": 0,
                        "near_constant_feature_count": 0,
                    },
                    "blockers": ["no positive broad family permutation gate"],
                }
            ]
        }

        artifact, _validation_rows = train_pooled_band_models(
            records,
            holdout_year=2025,
            weak_family_disposition=weak_policy,
        )
        preflight = artifact["weak_input_family_preflight"]

        self.assertEqual(preflight["status"], "WARN")
        self.assertEqual(preflight["diagnostic_only_families"], ["surface_weather"])
        self.assertTrue(any(row["family"] == "surface_weather" for row in preflight["warnings"]))


if __name__ == "__main__":
    unittest.main()
