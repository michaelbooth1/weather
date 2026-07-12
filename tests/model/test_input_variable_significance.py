import unittest
from unittest.mock import patch

import pandas as pd

from tools.research import input_variable_significance as significance


class InputVariableSignificanceFeatureSelectionTests(unittest.TestCase):
    def test_empty_feature_columns_fallback_filters_derived_target_and_outcomes(self):
        data = pd.DataFrame(
            {
                "safe_weather_feature": [1.0],
                "target_market_z": [0.5],
                "outcome": [1],
                "settlement_high": [82.0],
                "cutoff_hour": [12],
            }
        )

        with (
            patch.object(significance, "FEATURE_COLUMNS", []),
            patch.object(significance, "FEATURE_COLUMNS_IMPORT_ERROR", None),
        ):
            selection = significance.candidate_feature_selection(data, include_diagnostics=False)

        self.assertEqual(selection.mode, "dataframe_fallback_empty_canonical")
        self.assertFalse(selection.promotion_grade)
        self.assertIn("safe_weather_feature", selection.features)
        self.assertIn("cutoff_hour", selection.features)
        self.assertNotIn("target_market_z", selection.features)
        self.assertNotIn("outcome", selection.features)
        self.assertNotIn("settlement_high", selection.features)
        self.assertIn("target_market_z", selection.rejected_forbidden_features)
        self.assertIn("outcome", selection.rejected_forbidden_features)

    def test_malicious_canonical_feature_list_is_filtered_and_not_promotion_grade(self):
        data = pd.DataFrame(
            {
                "safe_weather_feature": [1.0],
                "target_market_z": [0.5],
                "settlement_distance_bucket": [0],
            }
        )

        with (
            patch.object(
                significance,
                "FEATURE_COLUMNS",
                ["safe_weather_feature", "target_market_z", "settlement_distance_bucket"],
            ),
            patch.object(significance, "FEATURE_COLUMNS_IMPORT_ERROR", None),
        ):
            selection = significance.candidate_feature_selection(data, include_diagnostics=False)

        self.assertEqual(selection.features, ["safe_weather_feature"])
        self.assertFalse(selection.promotion_grade)
        self.assertEqual(
            selection.rejected_forbidden_features,
            ["settlement_distance_bucket", "target_market_z"],
        )


if __name__ == "__main__":
    unittest.main()
