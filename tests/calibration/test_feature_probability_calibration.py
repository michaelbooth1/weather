import math
import os
import sys
import unittest
from weather.calibration.feature_probability_calibration import (
    blend_distribution,
    fit_temperature_blend_grid,
    log_loss,
    temperature_scale_distribution,
)


class TestFeatureProbabilityCalibration(unittest.TestCase):
    def test_temperature_scale_softens_and_sharpens_distribution(self):
        raw = {18: 0.90, 19: 0.10}

        softened = temperature_scale_distribution(raw, temperature=2.0)
        sharpened = temperature_scale_distribution(raw, temperature=0.70)

        self.assertAlmostEqual(sum(softened.values()), 1.0)
        self.assertLess(softened[18], raw[18])
        self.assertGreater(softened[19], raw[19])
        self.assertGreater(sharpened[18], raw[18])

    def test_temperature_blend_grid_includes_legacy_and_improves_logloss(self):
        folds = [
            ({18: 0.50, 19: 0.50}, {18: 0.95, 19: 0.05}, 19),
            ({18: 0.50, 19: 0.50}, {18: 0.90, 19: 0.10}, 19),
            ({18: 0.50, 19: 0.50}, {18: 0.80, 19: 0.20}, 18),
        ]

        fitted = fit_temperature_blend_grid(folds)
        legacy = sum(
            log_loss(blend_distribution(base, raw, 0.80), actual)
            for base, raw, actual in folds
        ) / len(folds)

        self.assertLessEqual(fitted["logloss"], legacy + 1e-12)
        self.assertTrue(math.isfinite(fitted["temperature"]))
        self.assertTrue(math.isfinite(fitted["blend_weight"]))


if __name__ == "__main__":
    unittest.main()
