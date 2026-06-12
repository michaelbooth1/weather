import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("src"))

from family_secondary_artifacts import (  # noqa: E402
    feature_model_allowed,
    gate_for_market,
    market_gate,
)
from model_features import FeatureModelMixin  # noqa: E402


class _DummyModel(FeatureModelMixin):
    def __init__(self, manifest, market_id="denver", unit="F"):
        self.family_secondary_artifacts = manifest
        self.market_id = market_id
        self.spec = SimpleNamespace(display_unit=unit)
        self._last_family_secondary_gate = {}


class TestFamilySecondaryArtifacts(unittest.TestCase):
    def _artifact_statuses(self, status="ok"):
        return {
            "probability_calibration": {"status": status},
            "forecast_error": {"status": status},
            "settlement_lag": {"status": status},
        }

    def test_gate_allows_ml_only_when_trust_days_and_artifacts_clear(self):
        gate = gate_for_market(
            {"trust_score": 50, "settled_days": 3},
            self._artifact_statuses(),
            min_trust=25,
            min_settled_days=2,
        )

        self.assertEqual(gate["mode"], "ml")

    def test_gate_falls_back_empirical_for_unproven_market(self):
        gate = gate_for_market(
            {"trust_score": 15, "settled_days": 1},
            self._artifact_statuses(),
            min_trust=25,
            min_settled_days=2,
        )

        self.assertEqual(gate["mode"], "empirical")
        self.assertIn("trust 15 < 25", gate["reason"])
        self.assertIn("settled_days 1 < 2", gate["reason"])

    def test_feature_model_allowed_reads_market_gate_from_manifest(self):
        manifest = {
            "family_unit": "F",
            "markets": {
                "denver": {
                    "serving_gate": {
                        "mode": "empirical",
                        "reason": "trust 15 < 25",
                    },
                },
            },
        }

        self.assertFalse(feature_model_allowed(manifest, "denver"))
        self.assertEqual(market_gate(manifest, "toronto")["mode"], "ml")

    def test_feature_mixin_short_circuits_governed_unproven_market(self):
        manifest = {
            "family_unit": "F",
            "markets": {
                "denver": {
                    "serving_gate": {
                        "mode": "empirical",
                        "reason": "trust 15 < 25",
                    },
                },
            },
        }
        model = _DummyModel(manifest)

        self.assertFalse(model.family_secondary_feature_model_allowed())
        self.assertEqual(model._last_family_secondary_gate["reason"], "trust 15 < 25")

    def test_feature_mixin_ignores_non_family_units(self):
        manifest = {"family_unit": "F", "markets": {}}
        model = _DummyModel(manifest, market_id="toronto", unit="C")

        self.assertTrue(model.family_secondary_feature_model_allowed())


if __name__ == "__main__":
    unittest.main()
