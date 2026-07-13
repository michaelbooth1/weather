import tempfile
import unittest
from pathlib import Path

from weather.reporting.candidate_lifecycle.variant_registry import (
    AUDIT_SCHEMA_VERSION,
    DEFAULT_REGISTRY_PATH,
    SCHEMA_VERSION,
    active_registry_variants,
    active_export_paths,
    audit_registry,
    headline_registry_variants,
    live_capture_export_paths,
    live_capture_registry_variants,
    load_registry,
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
        "live_capture_enabled": True,
        "counts_toward_weather_model_promotion": True,
        "promotion_status": "candidate",
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
    def test_live_capture_explicit_false_overrides_headline_with_legacy_fallback(self):
        explicit_false = _active_variant("explicit_false", live_capture_enabled=False)
        legacy = _active_variant("legacy")
        legacy.pop("live_capture_enabled")
        registry = {"variants": [explicit_false, legacy]}

        self.assertEqual(
            [row["variant_id"] for row in live_capture_registry_variants(registry)],
            ["legacy"],
        )

    def test_string_decision_flags_do_not_enable_lanes_and_fail_audit(self):
        malformed = _active_variant(
            "malformed",
            active_for_headline="false",
            live_capture_enabled="true",
            counts_toward_weather_model_promotion="false",
        )
        registry = {
            "schema_version": SCHEMA_VERSION,
            "exists": True,
            "path": "inline",
            "variants": [malformed],
        }

        self.assertEqual(headline_registry_variants(registry), [])
        self.assertEqual(live_capture_registry_variants(registry), [])
        payload = audit_registry(registry, evidence_paths=[], check_paths=False)
        invalid_types = [
            row
            for row in payload["checks"]
            if row["category"] == "invalid_decision_field_type"
        ]
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(len(invalid_types), 3)

    def test_registry_distinguishes_headline_and_live_capture_lanes(self):
        registry = load_registry(DEFAULT_REGISTRY_PATH)

        headline_ids = {
            row["variant_id"] for row in headline_registry_variants(registry)
        }
        live_capture_ids = {
            row["variant_id"] for row in live_capture_registry_variants(registry)
        }

        self.assertEqual(
            headline_ids,
            {"clob_overlay_gated_taxonomy", "clob_overlay_raw_oof"},
        )
        self.assertEqual(len(live_capture_ids), 8)
        self.assertEqual(
            {row["variant_id"] for row in active_registry_variants(registry)},
            headline_ids,
        )
        self.assertGreater(len(live_capture_export_paths(registry)), 1)

        for row in registry["variants"]:
            if row.get("lifecycle") == "archived":
                continue
            self.assertIn("active_for_headline", row)
            self.assertIn("live_capture_enabled", row)
            self.assertIn("counts_toward_weather_model_promotion", row)
            self.assertIn("promotion_status", row)

    def test_residual_distribution_is_registered_but_inert_until_qualified(self):
        registry = load_registry(DEFAULT_REGISTRY_PATH)
        residual = registry["by_id"]["residual_distribution_v1"]

        self.assertEqual(residual["lifecycle"], "shadow")
        self.assertFalse(residual["active_for_headline"])
        self.assertFalse(residual["live_capture_enabled"])
        self.assertFalse(residual["counts_toward_weather_model_promotion"])
        self.assertEqual(residual["promotion_status"], "blocked")
        self.assertEqual(residual["live_runtime"], "residual_distribution_v1")
        self.assertNotIn(
            residual["variant_id"],
            {row["variant_id"] for row in active_registry_variants(registry)},
        )

    def test_known_bad_density_variant_is_quarantined_from_headline_and_promotion(self):
        registry = load_registry(DEFAULT_REGISTRY_PATH)
        density = registry["by_id"]["pooled_continuous_density_hgb_v0_1"]

        self.assertEqual(density["lifecycle"], "shadow")
        self.assertFalse(density["active_for_headline"])
        self.assertTrue(density["live_capture_enabled"])
        self.assertFalse(density["counts_toward_weather_model_promotion"])
        self.assertEqual(density["promotion_status"], "blocked")
        self.assertIn("live-replay-divergence-quarantined", density["roles"])
        self.assertNotIn(
            density["variant_id"],
            {row["variant_id"] for row in active_registry_variants(registry)},
        )

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

    def test_audit_validates_live_capture_contract_without_promoting_its_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            headline_export = root / "headline.csv"
            headline_export.write_text(
                "variant_id,probability\nheadline,0.5\n",
                encoding="utf-8",
            )
            diagnostic_artifact = root / "diagnostic.pkl"
            diagnostic_artifact.write_bytes(b"diagnostic")
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": "inline",
                "variants": [
                    _active_variant(
                        "headline",
                        default_export_path=str(headline_export),
                    ),
                    _active_variant(
                        "diagnostic",
                        active_for_headline=False,
                        live_capture_enabled=True,
                        artifact_required=True,
                        artifact_path=str(diagnostic_artifact),
                        default_export_path=str(root / "diagnostic.csv"),
                    ),
                ],
            }

            payload = audit_registry(registry)

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["summary"]["headline_variant_count"], 1)
        self.assertEqual(payload["summary"]["active_contract_count"], 1)
        self.assertEqual(payload["summary"]["live_capture_variant_count"], 2)
        self.assertEqual(payload["summary"]["live_capture_contract_count"], 2)
        self.assertEqual(payload["missing_active_variant_ids"], [])

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

    def test_audit_rejects_active_local_data_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "variants.csv"
            export.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,current_probability,market_yes,outcome\n"
                "active_local,demo_family,nyc,2026-06-18,s1,eq:82,0.55,0.50,0.52,1\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": "inline",
                "variants": [
                    _active_variant(
                        "active_local",
                        artifact_required=True,
                        artifact_path="data/backtest/local_candidate.pkl",
                        default_export_path=str(export),
                    )
                ],
            }

            payload = audit_registry(registry, check_paths=False)

        self.assertEqual(payload["status"], "ERROR")
        categories = {row["category"] for row in payload["checks"]}
        self.assertIn("active_local_artifact_path", categories)

    def test_audit_warns_for_shadow_only_local_data_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "variants.csv"
            export.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,current_probability,market_yes,outcome\n"
                "shadow_local,demo_family,nyc,2026-06-18,s1,eq:82,0.55,0.50,0.52,1\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": "inline",
                "variants": [
                    _active_variant(
                        "shadow_local",
                        roles=["candidate", "shadow-only"],
                        artifact_required=True,
                        artifact_path="data/backtest/local_candidate.pkl",
                        default_export_path=str(export),
                    )
                ],
            }

            payload = audit_registry(registry, check_paths=False)

        self.assertEqual(payload["status"], "WARN")
        categories = {row["category"] for row in payload["checks"]}
        self.assertIn("shadow_local_candidate_artifact_path", categories)

    def test_audit_requires_route_recipe_for_active_row_route_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "variants.csv"
            export.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,current_probability,market_yes,outcome\n"
                "route_v1,demo_family,nyc,2026-06-18,s1,eq:82,0.55,0.50,0.52,1\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": "inline",
                "variants": [
                    _active_variant(
                        "route_v1",
                        live_runtime="candidate_row_route_composite",
                        default_export_path=str(export),
                    )
                ],
            }

            payload = audit_registry(registry)

        self.assertEqual(payload["status"], "ERROR")
        missing_checks = [
            row for row in payload["checks"]
            if row["category"] == "missing_export_contract_fields"
        ]
        self.assertTrue(any("route_recipe_path" in row["detail"] for row in missing_checks))

    def test_audit_requires_repair_specs_for_active_repair_integration_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = root / "variants.csv"
            export.write_text(
                "variant_id,variant_family,market_id,target_date,snapshot_id,band_key,probability,current_probability,market_yes,outcome\n"
                "repair_v1,demo_family,nyc,2026-06-18,s1,eq:82,0.55,0.50,0.52,1\n",
                encoding="utf-8",
            )
            registry = {
                "schema_version": SCHEMA_VERSION,
                "exists": True,
                "path": "inline",
                "variants": [
                    _active_variant(
                        "repair_v1",
                        live_runtime="repair_integration_active_contract",
                        default_export_path=str(export),
                    )
                ],
            }

            payload = audit_registry(registry)

        self.assertEqual(payload["status"], "ERROR")
        missing_checks = [
            row for row in payload["checks"]
            if row["category"] == "missing_export_contract_fields"
        ]
        self.assertTrue(any("repair_specs_path" in row["detail"] for row in missing_checks))


if __name__ == "__main__":
    unittest.main()
