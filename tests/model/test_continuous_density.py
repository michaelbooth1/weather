import os
import sys
import unittest
from weather.market.market_registry import NYC, TORONTO  # noqa: E402
from weather.model.continuous_density import (  # noqa: E402
    band_probability_from_density,
    band_probability_from_distribution,
    canonical_grid_f,
    continuous_density_payload,
    discretize_density_to_market_bands,
    is_continuous_density_payload,
)


class TestContinuousDensity(unittest.TestCase):
    def test_canonical_grid_uses_stable_step(self):
        self.assertEqual(canonical_grid_f(50.0, 50.3, 0.1), [50.0, 50.1, 50.2, 50.3])
        with self.assertRaises(ValueError):
            canonical_grid_f(50.0, 51.0, 0.0)

    def test_exact_fahrenheit_bucket_uses_half_open_rounding_interval(self):
        density = {
            79.49: 0.1,
            79.50: 0.2,
            80.00: 0.3,
            80.49: 0.2,
            80.50: 0.2,
        }

        self.assertAlmostEqual(
            band_probability_from_density(density, "F", "eq", 80),
            0.7,
        )
        self.assertAlmostEqual(
            band_probability_from_density(density, "F", "lte", 79),
            0.1,
        )
        self.assertAlmostEqual(
            band_probability_from_density(density, "F", "gte", 81),
            0.2,
        )

    def test_exact_celsius_bucket_is_serving_only_conversion_from_f_grid(self):
        density = {
            67.09: 0.1,
            67.10: 0.2,
            68.00: 0.3,
            68.89: 0.2,
            68.90: 0.2,
        }

        self.assertAlmostEqual(
            band_probability_from_density(density, "C", "eq", 20),
            0.7,
        )

    def test_market_band_rows_conserve_probability_for_exhaustive_bands(self):
        density = {
            79.49: 0.1,
            79.50: 0.2,
            80.00: 0.3,
            80.49: 0.2,
            80.50: 0.2,
        }
        rows = discretize_density_to_market_bands(
            density,
            NYC,
            [
                {"label": "<=79 F", "kind": "lte", "value": 79},
                {"label": "80 F", "kind": "eq", "value": 80},
                {"label": ">=81 F", "kind": "gte", "value": 81},
            ],
        )

        self.assertAlmostEqual(sum(row["probability"] for row in rows), 1.0)
        self.assertEqual(rows[0]["market_id"], "nyc")
        self.assertEqual(rows[0]["unit"], "F")

    def test_range_band_integrates_all_native_buckets_in_range(self):
        density = {
            67.09: 0.1,
            67.10: 0.2,
            68.00: 0.3,
            68.90: 0.2,
            70.69: 0.1,
            70.70: 0.1,
        }

        rows = discretize_density_to_market_bands(
            density,
            TORONTO,
            [{"label": "20-21 C", "kind": "eq", "value": 20, "value_hi": 21}],
        )

        self.assertEqual(rows[0]["unit"], "C")
        self.assertAlmostEqual(rows[0]["probability"], 0.8)

    def test_explicit_payload_projects_bands_without_touching_native_distributions(self):
        payload = continuous_density_payload({
            79.49: 0.1,
            79.50: 0.2,
            80.00: 0.3,
            80.49: 0.2,
            80.50: 0.2,
        })

        self.assertTrue(is_continuous_density_payload(payload))
        self.assertFalse(is_continuous_density_payload({79: 0.1, 80: 0.9}))
        self.assertAlmostEqual(
            band_probability_from_distribution(
                payload,
                NYC,
                {"kind": "eq", "value": 80},
            ),
            0.7,
        )


if __name__ == "__main__":
    unittest.main()
