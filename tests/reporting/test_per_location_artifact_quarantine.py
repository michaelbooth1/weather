import unittest

from weather.reporting.data_quality.per_location_artifact_quarantine import build_payload, render_report


class PerLocationArtifactQuarantineTests(unittest.TestCase):
    def test_unregistered_stale_per_location_hgb_is_historical_only(self):
        registry = {
            "artifact_root": "artifacts",
            "artifacts": [
                {
                    "artifact_id": "models/hgb/feature_model_hgb_nyc.pkl",
                    "path": "artifacts/models/hgb/feature_model_hgb_nyc.pkl",
                    "kind": "hgb_model",
                    "registry_use": "unregistered_runtime_artifact",
                    "variant_refs": [],
                },
                {
                    "artifact_id": "models/coefs/feature_model_coefs_nyc.json",
                    "path": "artifacts/models/coefs/feature_model_coefs_nyc.json",
                    "kind": "coefs_model",
                    "registry_use": "unregistered_runtime_artifact",
                    "feature_schema_version": "toronto_feature_store_v0.3",
                    "variant_refs": [],
                },
            ],
        }

        payload = build_payload(
            registry_payload=registry,
            active_feature_schema_version="toronto_feature_store_v1.14",
            generated_at_utc="2026-06-22T00:00:00+00:00",
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["summary"]["historical_only_count"], 2)
        hgb = next(row for row in payload["artifacts"] if row["artifact_kind"] == "hgb_model")
        self.assertEqual(hgb["market_id"], "nyc")
        self.assertEqual(hgb["feature_schema_version"], "toronto_feature_store_v0.3")
        self.assertEqual(hgb["schema_status"], "stale_schema")
        self.assertEqual(hgb["disposition"], "historical_only")
        self.assertIn("unregistered runtime artifact", hgb["reasons"])

    def test_active_stale_per_location_artifact_blocks(self):
        registry = {
            "artifact_root": "artifacts",
            "artifacts": [
                {
                    "artifact_id": "models/hgb/feature_model_hgb_austin.pkl",
                    "path": "artifacts/models/hgb/feature_model_hgb_austin.pkl",
                    "kind": "hgb_model",
                    "registry_use": "active_promoted",
                    "variant_refs": [{"variant_id": "austin_legacy"}],
                },
                {
                    "artifact_id": "models/coefs/feature_model_coefs_austin.json",
                    "path": "artifacts/models/coefs/feature_model_coefs_austin.json",
                    "kind": "coefs_model",
                    "registry_use": "active_promoted",
                    "feature_schema_version": "toronto_feature_store_v0.2",
                    "variant_refs": [{"variant_id": "austin_legacy"}],
                },
            ],
        }

        payload = build_payload(
            registry_payload=registry,
            active_feature_schema_version="toronto_feature_store_v1.14",
            generated_at_utc="2026-06-22T00:00:00+00:00",
        )

        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["summary"]["active_candidate_violation_count"], 2)
        self.assertEqual(
            {row["disposition"] for row in payload["active_candidate_violations"]},
            {"active_candidate_blocked"},
        )

    def test_active_same_family_schema_artifact_is_migrated_before_quarantine(self):
        registry = {
            "artifact_root": "artifacts",
            "artifacts": [
                {
                    "artifact_id": "models/hgb/feature_model_hgb_austin.pkl",
                    "path": "artifacts/models/hgb/feature_model_hgb_austin.pkl",
                    "kind": "hgb_model",
                    "registry_use": "active_promoted",
                    "variant_refs": [{"variant_id": "austin_legacy"}],
                },
                {
                    "artifact_id": "models/coefs/feature_model_coefs_austin.json",
                    "path": "artifacts/models/coefs/feature_model_coefs_austin.json",
                    "kind": "coefs_model",
                    "registry_use": "active_promoted",
                    "feature_schema_version": "toronto_feature_store_v1.13",
                    "variant_refs": [{"variant_id": "austin_legacy"}],
                },
            ],
        }

        payload = build_payload(
            registry_payload=registry,
            active_feature_schema_version="toronto_feature_store_v1.15",
            generated_at_utc="2026-06-25T00:00:00+00:00",
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["summary"]["active_candidate_violation_count"], 0)
        self.assertEqual(payload["summary"]["migrated_schema_count"], 2)
        self.assertEqual(payload["summary"]["migratable_artifact_count"], 2)
        hgb = next(row for row in payload["artifacts"] if row["artifact_kind"] == "hgb_model")
        self.assertEqual(hgb["schema_status"], "migrated_schema")
        self.assertEqual(hgb["migration_status"], "migrated")
        self.assertEqual(hgb["effective_feature_schema_version"], "toronto_feature_store_v1.15")
        self.assertEqual(hgb["disposition"], "active_candidate")

    def test_pooled_hgb_artifacts_are_not_per_location_candidates(self):
        registry = {
            "artifact_root": "artifacts",
            "artifacts": [
                {
                    "artifact_id": "models/hgb/feature_model_hgb_f_pooled_v0_3.pkl",
                    "path": "artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl",
                    "kind": "hgb_model",
                    "registry_use": "active_promoted",
                    "variant_refs": [{"variant_id": "pooled"}],
                }
            ],
        }

        payload = build_payload(registry_payload=registry)

        self.assertEqual(payload["summary"]["per_location_artifact_count"], 0)
        self.assertEqual(payload["status"], "PASS")

    def test_report_labels_quarantined_artifacts(self):
        payload = build_payload(
            registry_payload={
                "artifact_root": "artifacts",
                "artifacts": [
                    {
                        "artifact_id": "models/coefs/feature_model_coefs_seattle.json",
                        "path": "artifacts/models/coefs/feature_model_coefs_seattle.json",
                        "kind": "coefs_model",
                        "registry_use": "unregistered_runtime_artifact",
                        "feature_schema_version": "toronto_feature_store_v0.2",
                    }
                ],
            },
            active_feature_schema_version="toronto_feature_store_v1.14",
            generated_at_utc="2026-06-22T00:00:00+00:00",
        )

        text = render_report(payload)

        self.assertIn("Historical-Only / Quarantined Artifacts", text)
        self.assertIn("historical_only", text)
        self.assertIn("feature_model_coefs_seattle.json", text)


if __name__ == "__main__":
    unittest.main()
