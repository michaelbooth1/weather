import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath("src"))

from feature_model import (
    feature_family_columns,
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
            "wind_W-NW",
            "cloud_Fair/clear",
        ]

        families = feature_family_columns(feature_cols)

        self.assertEqual(families["forecast"], ["forecast_high", "forecast_gap"])
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


if __name__ == "__main__":
    unittest.main()
