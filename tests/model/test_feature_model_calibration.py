import os
import sys
import unittest


sys.path.insert(0, os.path.abspath("src"))

from toronto_model import TorontoHighTempModel


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
        self.assertAlmostEqual(sum(distribution.values()), 1.0)
        self.assertLess(distribution[18], 0.90)
        self.assertGreater(distribution[19], 0.10)


if __name__ == "__main__":
    unittest.main()
