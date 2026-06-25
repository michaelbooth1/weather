import unittest

from weather.reporting.location_analysis.location_similarity_pooling import (
    blend_prediction,
    build_payload,
    build_similarity_table,
    pooling_weights,
)


class TestLocationSimilarityPooling(unittest.TestCase):
    def test_similarity_weights_favor_climate_and_geo_neighbors(self):
        target = {
            "location_id": "nyc",
            "coordinates": {"lat": 40.7, "lon": -74.0, "elevation_m": 10},
            "climate_normal": 82.0,
            "climate_std": 7.0,
            "source_reliability_prior": 0.8,
            "forecast_error_mae": 2.5,
            "coastal": True,
        }
        close = {
            "location_id": "philadelphia",
            "coordinates": {"lat": 39.9, "lon": -75.2, "elevation_m": 12},
            "climate_normal": 84.0,
            "climate_std": 7.5,
            "source_reliability_prior": 0.78,
            "forecast_error_mae": 2.7,
            "coastal": True,
        }
        far = {
            "location_id": "phoenix",
            "coordinates": {"lat": 33.4, "lon": -112.0, "elevation_m": 346},
            "climate_normal": 101.0,
            "climate_std": 9.0,
            "source_reliability_prior": 0.65,
            "forecast_error_mae": 4.5,
            "coastal": False,
        }

        rows = build_similarity_table([target], [close, far])
        by_extra = {row["extra_location_id"]: row for row in rows}
        weights = pooling_weights(rows, target_location_id="nyc", target_local_weight=0.7)

        self.assertGreater(by_extra["philadelphia"]["similarity_score"], by_extra["phoenix"]["similarity_score"])
        self.assertGreater(weights["extra_weights"]["philadelphia"], weights["extra_weights"]["phoenix"])
        self.assertAlmostEqual(sum(weights["extra_weights"].values()), 0.3)

    def test_blend_prediction_exports_attribution_and_fallback(self):
        weights = {
            "target_location_id": "nyc",
            "target_local_weight": 0.7,
            "extra_weights": {"philadelphia": 0.2, "boston": 0.1},
            "fallback_to_target_only": False,
        }

        blended = blend_prediction(80.0, {"philadelphia": 82.0, "boston": 78.0}, weights)

        self.assertAlmostEqual(blended["prediction"], 80.2)
        self.assertEqual(len(blended["attribution"]), 3)
        self.assertEqual(blended["attribution"][0]["source"], "target_local")

        fallback = pooling_weights([], target_location_id="nyc")
        self.assertTrue(fallback["fallback_to_target_only"])

    def test_build_payload_records_policy_and_pairs(self):
        payload = build_payload(
            [{"location_id": "nyc", "coordinates": {"lat": 40.7, "lon": -74, "elevation_m": 10}}],
            [{"location_id": "philadelphia", "coordinates": {"lat": 39.9, "lon": -75.2, "elevation_m": 12}}],
        )

        self.assertEqual(payload["schema_version"], "location_similarity_partial_pooling_v0.1")
        self.assertEqual(payload["summary"]["similarity_pair_count"], 1)
        self.assertIn("selection_basis", payload["policy"])


if __name__ == "__main__":
    unittest.main()
