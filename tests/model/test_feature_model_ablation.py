import os
import sys
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd
from weather.calibration.feature_model import (
    LATE_DAY_NUMERIC_FEATURES,
    ablation_month_label,
    ablation_observation,
    ablation_season_label,
    evaluate_feature_family_segments,
    evaluate_late_day_records,
    feature_blocked_validation_plan,
    feature_family_columns,
    fold_local_feature_matrices,
    inner_hgb_calibration_rows,
    feature_family_promotion_decisions,
    late_day_feature_columns,
    neutralize_feature_family,
    nested_temperature_blend_predictions,
    summarize_ablation_by_family,
    summarize_ablation_by_group,
    train_late_day_continuation_models,
)
from weather.model.toronto_model import TorontoHighTempModel


class TestFeatureModelAblation(unittest.TestCase):
    def test_blocked_preprocessing_is_fit_only_on_training_rows(self):
        frame = pd.DataFrame({
            "high_so_far": [10.0, 12.0, 1000.0],
            "forecast_high": [20.0, np.nan, np.nan],
            "wind_W-NW": [0.0, 1.0, 1.0],
        })
        matrices = fold_local_feature_matrices(
            frame,
            train_idx=[0, 1],
            val_idx=[2],
            feature_cols=list(frame.columns),
            numeric_feature_count=2,
        )

        self.assertEqual(matrices["imputer"].statistics_.tolist(), [11.0, 20.0, 0.5])
        self.assertEqual(matrices["scaler"].mean_.tolist(), [11.0, 20.0])
        self.assertEqual(matrices["lr_train"][:, 0].tolist(), [-1.0, 1.0])
        self.assertGreater(matrices["lr_validation"][0, 0], 900.0)
        self.assertTrue(np.isnan(matrices["hgb_validation"][0, 1]))

    def test_nested_calibration_never_fits_on_the_outer_rows_it_scores(self):
        outer_rows = [
            {
                "validation_index": 0,
                "train_indices": (2, 3),
                "climatology": {0: 0.5, 1: 0.5},
                "raw_model": {0: 0.8, 1: 0.2},
                "actual": 90,
            },
            {
                "validation_index": 1,
                "train_indices": (0, 1),
                "climatology": {0: 0.5, 1: 0.5},
                "raw_model": {0: 0.2, 1: 0.8},
                "actual": 91,
            },
        ]
        builder_calls = []
        fitter_actuals = []

        def inner_builder(*args):
            outer_train_indices = tuple(args[-1])
            builder_calls.append(outer_train_indices)
            inner_actual = 10 if outer_train_indices == (0, 1) else 11
            return [({0: 0.5, 1: 0.5}, {0: 0.6, 1: 0.4}, inner_actual)]

        def fitter(rows, *, blend_weights):
            fitter_actuals.append([row[2] for row in rows])
            self.assertEqual(blend_weights, [0.8])
            return {"temperature": 1.0, "blend_weight": 0.8, "logloss": 0.1}

        results = nested_temperature_blend_predictions(
            outer_rows,
            x_frame=pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0]}),
            y=pd.Series([0, 1, 0, 1]),
            records=[{"final_bucket": value} for value in (0, 1, 0, 1)],
            bucket_space=[0, 1],
            feature_cols=["x"],
            numeric_feature_count=1,
            blend_weights=[0.8],
            inner_row_builder=inner_builder,
            calibration_fitter=fitter,
        )

        self.assertEqual(set(builder_calls), {(0, 1), (2, 3)})
        self.assertEqual({actual for call in fitter_actuals for actual in call}, {10, 11})
        self.assertTrue({90, 91}.isdisjoint(actual for call in fitter_actuals for actual in call))
        self.assertEqual([row["validation_index"] for row in results], [0, 1])
        self.assertTrue(all(row["calibration_status"] == "nested_inner_oof" for row in results))

    def test_inner_calibration_rows_are_blocked_oof_with_fold_local_missingness(self):
        records = []
        values = []
        outcomes = []
        for year in (2023, 2024, 2025):
            for day in range(1, 5):
                outcome = day % 2
                records.append({
                    "target_date": date(year, 6, day),
                    "final_bucket": outcome,
                })
                values.append({
                    "high_so_far": float(day + outcome),
                    "forecast_high": np.nan if day == 4 else float(day + 2),
                })
                outcomes.append(outcome)
        rows = inner_hgb_calibration_rows(
            pd.DataFrame(values),
            pd.Series(outcomes),
            records,
            bucket_space=[0, 1],
            feature_cols=["high_so_far", "forecast_high"],
            numeric_feature_count=2,
            outer_train_indices=range(len(records)),
        )

        self.assertEqual(len(rows), len(records))
        self.assertTrue(all(actual in {0, 1} for _clim, _raw, actual in rows))
        self.assertTrue(all(abs(sum(raw.values()) - 1.0) < 1e-9 for _clim, raw, _actual in rows))

    def test_feature_family_columns_groups_schema_features(self):
        feature_cols = [
            "high_so_far",
            "current_temp",
            "forecast_high",
            "forecast_gap",
            "forecast_source_count",
            "forecast_disagreement",
            "onshore_flow",
            "onshore_wind_speed_kmh",
            "lake_breeze_proxy",
            "wind_W-NW",
            "cloud_Fair/clear",
        ]

        families = feature_family_columns(feature_cols)

        self.assertEqual(
            families["forecast"],
            ["forecast_high", "forecast_gap", "forecast_source_count", "forecast_disagreement"],
        )
        self.assertEqual(
            families["microclimate"],
            ["onshore_flow", "onshore_wind_speed_kmh", "lake_breeze_proxy"],
        )
        self.assertEqual(families["wind_regime"], ["wind_W-NW"])
        self.assertEqual(families["cloud_regime"], ["cloud_Fair/clear"])

    def test_neutralize_feature_family_uses_nan_for_forecast_and_zero_for_one_hot(self):
        feature_cols = ["forecast_high", "forecast_gap", "wind_W-NW", "high_so_far"]
        row = np.array([23.0, 3.0, 1.0, 20.0])
        train = np.array([
            [21.0, 1.0, 0.0, 18.0],
            [25.0, 4.0, 1.0, 22.0],
        ])

        forecast_neutral = neutralize_feature_family(
            row,
            train,
            feature_cols,
            ["forecast_high", "forecast_gap"],
        )
        wind_neutral = neutralize_feature_family(
            row,
            train,
            feature_cols,
            ["wind_W-NW"],
        )
        temp_neutral = neutralize_feature_family(
            row,
            train,
            feature_cols,
            ["high_so_far"],
        )

        self.assertTrue(np.isnan(forecast_neutral[0]))
        self.assertTrue(np.isnan(forecast_neutral[1]))
        self.assertEqual(wind_neutral[2], 0.0)
        self.assertEqual(temp_neutral[3], 20.0)

    def test_summarize_ablation_by_family_weights_rows(self):
        summary = summarize_ablation_by_family([
            {
                "family": "forecast",
                "n": 2,
                "full_logloss": 1.0,
                "ablated_logloss": 1.5,
                "delta_logloss": 0.5,
                "full_brier": 0.2,
                "ablated_brier": 0.4,
                "delta_brier": 0.2,
            },
            {
                "family": "forecast",
                "n": 1,
                "full_logloss": 2.0,
                "ablated_logloss": 2.3,
                "delta_logloss": 0.3,
                "full_brier": 0.5,
                "ablated_brier": 0.7,
                "delta_brier": 0.2,
            },
        ])

        self.assertEqual(summary[0]["family"], "forecast")
        self.assertAlmostEqual(summary[0]["delta_logloss"], (0.5 * 2 + 0.3) / 3)
        self.assertAlmostEqual(summary[0]["delta_brier"], 0.2)

    def test_ablation_observations_group_by_month_and_season(self):
        may_row = ablation_observation(
            12,
            "2026-05-27",
            "microclimate",
            full_loss=1.0,
            ablated_loss=1.2,
            full_brier=0.2,
            ablated_brier=0.3,
        )
        june_row = ablation_observation(
            12,
            pd.Timestamp("2026-06-03"),
            "microclimate",
            full_loss=2.0,
            ablated_loss=2.1,
            full_brier=0.4,
            ablated_brier=0.5,
        )

        by_month = summarize_ablation_by_group([may_row, june_row], ["month"])
        by_season = summarize_ablation_by_group([may_row, june_row], ["season"])
        by_hour_month = summarize_ablation_by_group([may_row, june_row], ["hour", "month"])

        self.assertEqual(ablation_month_label("2026-05-27"), "05-May")
        self.assertEqual(ablation_season_label("2026-05-27"), "spring")
        self.assertEqual(ablation_season_label("2026-06-03"), "summer")
        self.assertEqual([row["month"] for row in by_month], ["05-May", "06-Jun"])
        self.assertEqual({row["season"] for row in by_season}, {"spring", "summer"})
        self.assertEqual(by_hour_month[0]["hour"], 12)
        self.assertAlmostEqual(by_month[0]["delta_logloss"], 0.2)

    def test_item27_day_fold_segment_evaluation_reports_promotion_decisions(self):
        records = []
        start = date(2026, 5, 20)
        for i in range(18):
            local_date = start + timedelta(days=i)
            warm_signal = float(i % 2)
            final_bucket = 26 if warm_signal else 24
            records.append({
                "target_date": local_date,
                "final_bucket": final_bucket,
                "high_so_far": 23.0 + warm_signal,
                "current_temp": 22.0 + warm_signal,
                "rise_from_7am": 5.0 + warm_signal,
                "dewpoint_c": 14.0 + warm_signal,
                "humidity": 55.0,
                "pressure": 1012.0,
                "pressure_trend_3h": -0.2,
                "wind_speed_kmh": 9.0 + warm_signal,
                "wind_gust_kmh": 15.0 + warm_signal,
                "wind_shift_3h_degrees": 20.0 + warm_signal,
                "onshore_flow": warm_signal,
                "onshore_wind_speed_kmh": 9.0 * warm_signal,
                "lake_breeze_proxy": warm_signal,
                "wind_group": "W-NW" if warm_signal else "N-NE",
                "cloud_group": "Fair/clear",
            })

        validation_rows, ablation_rows = evaluate_feature_family_segments(
            {12: records},
            ["W-NW", "N-NE"],
            ["Fair/clear"],
            [24, 26],
            n_splits=3,
        )
        decisions = feature_family_promotion_decisions(ablation_rows, min_rows=1)

        self.assertEqual(validation_rows[0]["hour"], 12)
        self.assertGreater(validation_rows[0]["n"], 0)
        self.assertEqual(
            validation_rows[0]["blocked_validation"]["schema_version"],
            "blocked_validation_v0.1",
        )
        self.assertEqual(
            validation_rows[0]["leakage_risk_verdict"],
            "WARN_MODULO_FOLD_NOT_PROMOTION_GRADE",
        )
        self.assertIn("month", ablation_rows[0])
        self.assertIn("season", ablation_rows[0])
        self.assertIn("microclimate", {row["family"] for row in ablation_rows})
        self.assertIn(
            "decision",
            {key for row in decisions for key in row.keys()},
        )

    def test_feature_blocked_validation_plan_excludes_validation_year(self):
        records = []
        for year in (2024, 2025):
            for day in range(1, 4):
                records.append({
                    "target_date": date(year, 6, day),
                    "final_bucket": 24 + (day % 2),
                })

        plan = feature_blocked_validation_plan(records)

        assert plan["mode"] == "holdout_year"
        assert plan["audit"]["schema_version"] == "blocked_validation_v0.1"
        for validation_index, train_indices in plan["train_indices_by_validation_index"].items():
            validation_year = records[validation_index]["target_date"].year
            assert train_indices
            assert {records[index]["target_date"].year for index in train_indices} == (
                {2025} if validation_year == 2024 else {2024}
            )

    def test_late_day_features_include_forecast_gap_before_one_hot_columns(self):
        columns = late_day_feature_columns(["W-NW"], ["Fair/clear"])

        self.assertEqual(columns[:len(LATE_DAY_NUMERIC_FEATURES)], LATE_DAY_NUMERIC_FEATURES)
        self.assertIn("forecast_high", columns)
        self.assertIn("forecast_gap", columns)
        self.assertEqual(columns[-2:], ["wind_W-NW", "cloud_Fair/clear"])

    def test_late_day_validation_reports_forecast_ablation(self):
        rows = []
        for i in range(12):
            extended = float(i % 2)
            high_so_far = 25.0
            forecast_gap = 4.0 if extended else -1.0
            rows.append({
                "date_ordinal": 738000 + i,
                "time_since_reached": 30.0 + i,
                "high_so_far": high_so_far,
                "current_temp": high_so_far,
                "rise_from_7am": 6.0,
                "dewpoint_c": 17.0,
                "humidity": 60.0,
                "pressure": 1012.0,
                "pressure_trend_3h": -0.5,
                "wind_speed_kmh": 12.0,
                "wind_gust_kmh": 18.0,
                "wind_shift_3h_degrees": 45.0,
                "forecast_high": high_so_far + forecast_gap,
                "forecast_gap": forecast_gap,
                "wind_W-NW": 1.0,
                "cloud_Fair/clear": 1.0,
                "is_extended": extended,
            })
        frame = pd.DataFrame(rows)
        feature_cols = late_day_feature_columns(["W-NW"], ["Fair/clear"])

        summary, ablations = evaluate_late_day_records(
            frame,
            feature_cols,
            numeric_feature_count=len(LATE_DAY_NUMERIC_FEATURES),
            n_splits=3,
        )

        self.assertEqual(summary["n"], 12)
        self.assertIsNotNone(summary["logloss"])
        self.assertIsNotNone(summary["brier"])
        self.assertIsNotNone(summary["ece"])
        self.assertIn("forecast", {row["family"] for row in ablations})

    def test_late_day_training_prefers_native_temperature_aliases(self):
        model = TorontoHighTempModel(target_date="2026-05-29", market_id="nyc")
        local_date = pd.Timestamp("2026-05-29").date()
        daily = {local_date: {"max_temp_native": 92.0, "bucket": 92}}
        by_date = {
            local_date: [
                {
                    "minute_of_day": 420,
                    "temp_native": 80.0,
                    "temp_c": 26.7,
                    "dewpoint_native": 60.0,
                    "dewpoint_c": 15.6,
                    "humidity": 50.0,
                    "pressure": 1015.0,
                    "wind": "SW",
                    "wind_kmh": 8.0,
                    "condition": "Fair",
                    "clouds": "Clear",
                },
                {
                    "minute_of_day": 900,
                    "temp_native": 91.0,
                    "temp_c": 32.8,
                    "dewpoint_native": 70.0,
                    "dewpoint_c": 21.1,
                    "humidity": 45.0,
                    "pressure": 1012.0,
                    "wind": "SW",
                    "wind_kmh": 10.0,
                    "condition": "Fair",
                    "clouds": "Clear",
                },
            ],
        }

        info, _validation, _ablations = train_late_day_continuation_models(
            model,
            daily,
            by_date,
            {local_date.isoformat(): 93.0},
            all_wind_groups=["S-SW"],
            all_cloud_groups=["Fair/clear"],
            trained_at="test",
        )

        feature_names = info["15"]["numeric_feature_names"]
        means = dict(zip(feature_names, info["15"]["scaler_mean"]))
        self.assertEqual(means["high_so_far"], 91.0)
        self.assertEqual(means["current_temp"], 91.0)
        self.assertEqual(means["rise_from_7am"], 11.0)
        self.assertEqual(means["dewpoint_c"], 70.0)


if __name__ == "__main__":
    unittest.main()
