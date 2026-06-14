import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from market_registry import NYC, SEATTLE
from pooled_feature_model import (
    add_city_features,
    adjacent_calibration_contexts,
    adjacent_calibration_factor,
    apply_band_postprocessing,
    apply_adjacent_calibration,
    band_prediction_record,
    feature_frame,
    fit_adjacent_calibration,
    hard_floor_probability,
    late_lockin_strength_from_features,
    support_floor_cap,
)


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
