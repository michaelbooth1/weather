import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from schema_registry import (  # noqa: E402
    SCHEMA_REGISTRY_SCHEMA_VERSION,
    audit_payload,
    registry_payload,
    schema_version,
    validate_schema_version,
)


class TestSchemaRegistry(unittest.TestCase):
    def test_registry_lookup_returns_public_versions(self):
        self.assertEqual(schema_version("feature_store"), "toronto_feature_store_v0.6")
        self.assertEqual(schema_version("historical_coverage"), "historical_coverage_v1")
        self.assertTrue(validate_schema_version("market_registry", "market_registry_v0.1"))

    def test_registry_payload_has_stable_schema(self):
        payload = registry_payload()

        self.assertEqual(payload["schema_version"], SCHEMA_REGISTRY_SCHEMA_VERSION)
        names = {row["name"] for row in payload["schemas"]}
        self.assertIn("feature_store", names)
        self.assertIn("observation_trigger_replay", names)

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
