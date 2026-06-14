import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

from probability_calibration import (
    apply_exact_distribution_calibration,
    calibrate_market_probability,
)
from toronto_model import TorontoHighTempModel


def _artifact(weight=0.6, base_rate=0.35, preserve_distribution_coherence=False):
    return {
        "exact_distribution": {
            "enabled": True,
            "method": "temperature",
            "temperature": 2.0,
            "prior_weight": 0.0,
        },
        "market_bin": {
            "enabled": True,
            "method": "prior_shrink",
            "weight": weight,
            "min_context_n": 1,
            "context_shrink_k": 0.0,
            "min_probability": 0.000001,
            "max_probability": 0.999999,
            "preserve_distribution_coherence": preserve_distribution_coherence,
            "contexts": {
                "global": {"n": 100, "base_rate": base_rate},
            },
        },
    }


class TestProbabilityCalibration(unittest.TestCase):
    def test_exact_distribution_calibration_normalizes_and_respects_floor(self):
        calibrated = apply_exact_distribution_calibration(
            {23: 0.20, 24: 0.30, 25: 0.50},
            _artifact(),
            floor_bucket=24,
        )

        self.assertAlmostEqual(sum(calibrated.values()), 1.0, places=6)
        self.assertEqual(calibrated[23], 0.0)
        self.assertGreater(calibrated[24], 0.0)
        self.assertGreater(calibrated[25], 0.0)

    def test_market_calibration_uses_hard_wu_floor_for_settled_bins(self):
        artifact = _artifact()
        context = {"cutoff_hour": 13, "observed_floor_bucket": 25}

        self.assertEqual(
            calibrate_market_probability(0.2, {"kind": "gte", "value": 25}, artifact, context),
            1.0,
        )
        self.assertEqual(
            calibrate_market_probability(0.8, {"kind": "lte", "value": 24}, artifact, context),
            0.0,
        )
        self.assertEqual(
            calibrate_market_probability(0.4, {"kind": "eq", "value": 24}, artifact, context),
            0.0,
        )

    def test_market_calibration_shrinks_non_hard_extremes_toward_base_rate(self):
        calibrated = calibrate_market_probability(
            0.95,
            {"kind": "eq", "value": 26},
            _artifact(weight=0.5, base_rate=0.30),
            {"cutoff_hour": 13, "observed_floor_bucket": 25},
        )

        self.assertLess(calibrated, 0.95)
        self.assertGreater(calibrated, 0.30)

    def test_market_calibration_does_not_lift_exact_floor_bucket(self):
        artifact = _artifact(weight=0.6, base_rate=0.35)
        raw = 0.0015

        guarded = calibrate_market_probability(
            raw,
            {"kind": "eq", "value": 17},
            artifact,
            {
                "cutoff_hour": 9,
                "observed_floor_bucket": 17,
                "observed_support_bucket": 19,
            },
        )

        self.assertAlmostEqual(guarded, raw)

    def test_market_calibration_does_not_lift_exact_bin_below_observed_support(self):
        artifact = _artifact(weight=0.6, base_rate=0.35)
        raw = 0.004

        guarded = calibrate_market_probability(
            raw,
            {"kind": "eq", "value": 18},
            artifact,
            {
                "cutoff_hour": 13,
                "observed_floor_bucket": 17,
                "observed_support_bucket": 19,
            },
        )

        self.assertAlmostEqual(guarded, raw)

    def test_market_calibration_does_not_lift_any_exact_bucket_by_default(self):
        artifact = _artifact(weight=0.6, base_rate=0.35, preserve_distribution_coherence=True)

        calibrated = calibrate_market_probability(
            0.02,
            {"kind": "eq", "value": 22},
            artifact,
            {"cutoff_hour": 15, "observed_floor_bucket": 18},
        )

        self.assertAlmostEqual(calibrated, 0.02)

    def test_market_calibration_preserves_distribution_coherence_by_default(self):
        artifact = _artifact(weight=0.6, base_rate=0.35)
        artifact["market_bin"].pop("preserve_distribution_coherence")

        self.assertAlmostEqual(
            calibrate_market_probability(
                0.80,
                {"kind": "eq", "value": 20},
                artifact,
                {"cutoff_hour": 15, "observed_floor_bucket": 18},
            ),
            0.80,
        )
        self.assertAlmostEqual(
            calibrate_market_probability(
                0.02,
                {"kind": "gte", "value": 25},
                artifact,
                {"cutoff_hour": 15, "observed_floor_bucket": 18},
            ),
            0.02,
        )

    def test_model_bin_probability_is_raw_without_artifact(self):
        model = TorontoHighTempModel()
        model.probability_calibration = None

        self.assertEqual(
            model.bin_probability({25: 1.0}, {"kind": "eq", "value": 24}),
            0.0,
        )

    def test_model_bin_probability_applies_loaded_artifact(self):
        model = TorontoHighTempModel()
        model.probability_calibration = _artifact(weight=0.5, base_rate=0.30)
        model._last_probability_calibration_context = {
            "cutoff_hour": 13,
            "observed_floor_bucket": 25,
        }

        calibrated = model.bin_probability({26: 0.95, 27: 0.05}, {"kind": "eq", "value": 26})

        self.assertLess(calibrated, 0.95)
        self.assertGreater(calibrated, 0.30)


if __name__ == "__main__":
    unittest.main()
