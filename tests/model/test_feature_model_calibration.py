import os
import sys
import unittest
from datetime import datetime

import numpy as np

from weather.calibration.feature_probability_calibration import temperature_scale_distribution
from weather.model.toronto_model import TorontoHighTempModel


class DummyHGB:
    classes_ = [18, 19]

    def predict_proba(self, _matrix):
        return [[0.90, 0.10]]


class DummyImputer:
    def transform(self, frame):
        return frame.to_numpy(dtype=float)


class TestFeatureModelServingCalibration(unittest.TestCase):
    def test_hgb_bundle_temperature_is_applied_at_serving(self):
        model = TorontoHighTempModel()
        model.extract_live_features = lambda sources, cutoff_hour, now=None: {
            "high_so_far": 18.0,
            "current_temp": 18.0,
            "rise_from_7am": 3.0,
            "dewpoint_c": 10.0,
            "humidity": 60.0,
            "pressure": 1012.0,
            "pressure_trend_3h": 0.0,
            "wind_speed_kmh": 10.0,
            "wind_group": "Other/variable",
            "cloud_group": "Fair/clear",
            "forecast_high": 20.0,
            "forecast_gap": 2.0,
            "forecast_source_count": 1.0,
            "forecast_disagreement": 0.0,
            "warming_rate_2h": 0.5,
            "hours_at_peak": 1.0,
        }
        hgb_bundle = {
            "12": {
                "model": DummyHGB(),
                "imputer": DummyImputer(),
                "feature_names": ["high_so_far"],
                "all_wind_groups": [],
                "all_cloud_groups": [],
                "probability_temperature": 2.0,
            }
        }

        distribution, kind = model._evaluate_feature_model_for_cutoff(
            {},
            12,
            hgb_bundle,
            lr_coefs=None,
        )

        self.assertEqual(kind, "hgb")
        expected = temperature_scale_distribution({18: 0.90, 19: 0.10}, 2.0)
        self.assertEqual(distribution, expected)
        self.assertAlmostEqual(sum(distribution.values()), 1.0)
        self.assertLess(distribution[18], 0.90)
        self.assertGreater(distribution[19], 0.10)

    def test_feature_ordinal_smoothing_defaults_to_disabled_for_existing_artifacts(self):
        model = TorontoHighTempModel()
        model.active_model_kind = "hgb"
        model.load_feature_model_hgb = lambda: {"12": {"blend_weight": 0.80}}

        config = model.feature_ordinal_smoothing_config(12)

        self.assertFalse(config["enabled"])
        self.assertEqual(config["source"], "artifact_absent")

    def test_feature_ordinal_smoothing_is_artifact_driven_when_enabled(self):
        model = TorontoHighTempModel()
        model.active_model_kind = "hgb"
        model.load_feature_model_hgb = lambda: {
            "12": {
                "ordinal_smoothing": {
                    "enabled": True,
                    "sigma": 0.75,
                    "blend_weight": 0.25,
                }
            }
        }

        config = model.feature_ordinal_smoothing_config(12)

        self.assertTrue(config["enabled"])
        self.assertAlmostEqual(config["sigma"], 0.75)
        self.assertAlmostEqual(config["blend_weight"], 0.25)

    def test_candidate_prior_keeps_positive_mass_on_contiguous_support_beyond_classes(self):
        model = TorontoHighTempModel()
        model.active_model_kind = "hgb"
        model.load_feature_model_hgb = lambda: {
            "12": {
                "serving_support": [18, 19, 20, 21],
                "target_date_aligned_prior": {
                    "18": 0.10,
                    "19": 0.20,
                    "20": 0.30,
                    "21": 0.40,
                },
            }
        }

        prior = model.feature_serving_prior(12)

        self.assertEqual(set(prior), {18, 19, 20, 21})
        self.assertGreater(prior[20], 0.0)
        self.assertGreater(prior[21], 0.0)
        self.assertAlmostEqual(sum(prior.values()), 1.0)

    def test_candidate_prior_fails_closed_on_support_hole(self):
        model = TorontoHighTempModel()
        model.active_model_kind = "hgb"
        model.load_feature_model_hgb = lambda: {
            "12": {
                "serving_support": [18, 20],
                "target_date_aligned_prior": {"18": 0.5, "20": 0.5},
            }
        }

        with self.assertRaisesRegex(ValueError, "not contiguous"):
            model.feature_serving_prior(12)

    def test_fahrenheit_missing_live_fields_use_hgb_imputer_median(self):
        class RecordingImputer:
            def __init__(self, row):
                self.row = row
                self.seen = None

            def transform(self, frame):
                self.seen = frame.copy()
                return np.array([self.row], dtype=float)

        class RecordingHGB:
            classes_ = [88, 89]

            def __init__(self):
                self.matrix = None

            def predict_proba(self, matrix):
                self.matrix = matrix.copy()
                return [[0.80, 0.20]]

        feature_names = [
            "high_so_far",
            "current_temp",
            "rise_from_7am",
            "dewpoint_c",
            "humidity",
            "wind_speed_kmh",
        ]
        imputed_row = [88.0, 87.0, 6.0, 65.0, 55.0, 11.0]
        imputer = RecordingImputer(imputed_row)
        hgb = RecordingHGB()
        hgb_bundle = {
            "12": {
                "model": hgb,
                "imputer": imputer,
                "feature_names": feature_names,
                "all_wind_groups": [],
                "all_cloud_groups": [],
            }
        }
        model = TorontoHighTempModel(target_date="2026-05-28", market_id="nyc")

        distribution, kind = model._evaluate_feature_model_for_cutoff(
            {},
            12,
            hgb_bundle,
            lr_coefs=None,
            now=datetime(2026, 5, 28, 12, 0),
        )

        self.assertEqual(kind, "hgb")
        self.assertEqual(distribution, {88: 0.80, 89: 0.20})
        for feature in feature_names:
            self.assertIsNone(imputer.seen.iloc[0][feature], feature)
        self.assertEqual(hgb.matrix[0].tolist(), imputed_row)
        self.assertNotEqual(hgb.matrix[0, 0], 17.0)


if __name__ == "__main__":
    unittest.main()
