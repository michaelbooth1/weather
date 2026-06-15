import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("src"))

from feature_model import (
    LATE_DAY_NUMERIC_FEATURES,
    evaluate_late_day_records,
    feature_family_columns,
    late_day_feature_columns,
    neutralize_feature_family,
    summarize_ablation_by_family,
)


class TestFeatureModelAblation(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
