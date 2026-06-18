import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.schema_registry import (  # noqa: E402
    SCHEMA_REGISTRY_SCHEMA_VERSION,
    audit_payload,
    registry_payload,
    schema_version,
    validate_schema_version,
)


class TestSchemaRegistry(unittest.TestCase):
    def test_registry_lookup_returns_public_versions(self):
        self.assertEqual(schema_version("feature_store"), "toronto_feature_store_v1.6")
        self.assertEqual(schema_version("reanalysis_synoptic_features"), "reanalysis_synoptic_features_v0.3")
        self.assertEqual(schema_version("historical_coverage"), "historical_coverage_v1")
        self.assertEqual(schema_version("forecast_history_coverage"), "forecast_history_coverage_v0.1")
        self.assertEqual(schema_version("forecast_history_long"), "forecast_history_long_v3")
        self.assertEqual(schema_version("daily_learning"), "daily_learning_v0.1")
        self.assertEqual(schema_version("live_forward_gate"), "live_forward_gate_v0.2")
        self.assertEqual(schema_version("market_making_daily_roll"), "market_making_daily_roll_v0.2")
        self.assertTrue(validate_schema_version("market_registry", "market_registry_v0.1"))
        self.assertTrue(validate_schema_version("live_forward_gate_legacy", "live_forward_gate_v0.1"))
        self.assertTrue(validate_schema_version("market_making_daily_roll_legacy", "market_making_daily_roll_v0.1"))

    def test_registry_payload_has_stable_schema(self):
        payload = registry_payload()

        self.assertEqual(payload["schema_version"], SCHEMA_REGISTRY_SCHEMA_VERSION)
        names = {row["name"] for row in payload["schemas"]}
        self.assertIn("feature_store", names)
        self.assertIn("observation_trigger_replay", names)
        self.assertIn("daily_learning", names)

    def test_audit_classifies_registered_and_unregistered_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.py"
            path.write_text(
                'KNOWN = "historical_coverage_v1"\n'
                'UNKNOWN = "made_up_payload_v9"\n',
                encoding="utf-8",
            )

            payload = audit_payload([tmp])

        by_version = {row["version"]: row for row in payload["discovered_literals"]}
        self.assertTrue(by_version["historical_coverage_v1"]["registered"])
        self.assertFalse(by_version["made_up_payload_v9"]["registered"])
        self.assertIn("made_up_payload_v9", payload["unregistered_versions"])


if __name__ == "__main__":
    unittest.main()
