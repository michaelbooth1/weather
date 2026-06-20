import tempfile
import unittest
from pathlib import Path

from weather.reporting.variant_registry import (
    AUDIT_SCHEMA_VERSION,
    SCHEMA_VERSION,
    active_export_paths,
    audit_registry,
    variant_contract_for_artifact,
)


def _active_variant(variant_id, **overrides):
    row = {
        "variant_id": variant_id,
        "variant_family": "demo_family",
        "lifecycle": "active",
        "track": "no_market",
        "roles": ["candidate", "no-market"],
        "active_for_headline": True,
        "artifact_required": False,
        "prediction_function": "weather.tests:predict",
        "prediction_mode": "demo_mode",
        "export_family": "demo_family",
        "default_export_path": "demo.csv",
        "live_runtime": "demo_runtime",
    }
    row.update(overrides)
    return row


class TestVariantRegistry(unittest.TestCase):
    def test_audit_passes_active_contracts_and_evidence_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model.pkl"
            artifact.write_bytes(b"demo")
            export = root / "variants.csv"
            export.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,current_probability,market_yes,outcome\n"
                "active_model,demo_family,nyc,2026-06-18,s1,eq:82,0.55,0.50,0.52,1\n"
                "active_policy,demo_family,nyc,2026-06-18,s1,eq:82,0.51,0.50,0.52,1\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": str(root / "registry.json"),
                "variants": [
                    _active_variant(
                        "active_model",
                        artifact_required=True,
                        artifact_path=str(artifact),
                        default_export_path=str(export),
                    ),
                    _active_variant(
                        "active_policy",
                        prediction_mode="policy_overlay",
                        default_export_path=str(export),
                    ),
                ],
            }

            payload = audit_registry(registry)

        self.assertEqual(payload["schema_version"], AUDIT_SCHEMA_VERSION)
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["active_contract_count"], 2)
        self.assertEqual(payload["missing_active_variant_ids"], [])
        self.assertEqual(active_export_paths(registry), [str(export)])
        contract = variant_contract_for_artifact(registry, str(artifact), prediction_function="weather.tests:predict")
        self.assertEqual(contract["variant_id"], "active_model")

    def test_audit_fails_duplicate_ids_missing_fields_and_missing_evidence(self):
        registry = {
            "schema_version": SCHEMA_VERSION,
            "exists": True,
            "path": "inline",
            "variants": [
                _active_variant("dup", prediction_function=""),
                _active_variant("dup", default_export_path="missing.csv"),
            ],
        }

        payload = audit_registry(registry)

        self.assertEqual(payload["status"], "ERROR")
        categories = {row["category"] for row in payload["checks"]}
        self.assertIn("duplicate_variant_id", categories)
        self.assertIn("missing_export_contract_fields", categories)
        self.assertIn("missing_export_path", categories)
        self.assertIn("active_variant_missing_from_evidence", categories)


if __name__ == "__main__":
    unittest.main()
