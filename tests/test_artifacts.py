import json
import tempfile
import unittest
from pathlib import Path
from weather.artifacts import (
    CandidateArtifactPathError,
    artifact_candidates,
    artifact_path,
    build_artifact_externalization_manifest,
    build_artifact_promotion_preflight,
    build_artifact_size_audit,
    build_artifact_registry,
    legacy_artifact_path,
    training_artifact_output_policy,
    write_artifact_size_audit,
    write_artifact_registry,
)


class TestArtifactPaths(unittest.TestCase):
    def test_candidate_training_path_policy_is_shared_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            candidates = root / "candidates"
            releases = root / "releases"
            candidate = training_artifact_output_policy(
                candidates / "r1" / "model.pkl",
                candidates_root=candidates,
                releases_root=releases,
                active_pointer=releases / "current_release.json",
            )
            self.assertEqual(candidate["status"], "CANDIDATE_ONLY")
            with self.assertRaises(CandidateArtifactPathError):
                training_artifact_output_policy(
                    root / "models" / "active.pkl",
                    candidates_root=candidates,
                    releases_root=releases,
                    active_pointer=releases / "current_release.json",
                )
            quarantined = training_artifact_output_policy(
                root / "models" / "active.pkl",
                candidates_root=candidates,
                releases_root=releases,
                active_pointer=releases / "current_release.json",
                allow_legacy_serving_output=True,
            )
            self.assertFalse(quarantined["release_eligible"])
            with self.assertRaises(CandidateArtifactPathError):
                training_artifact_output_policy(
                    releases / "r1" / "model.pkl",
                    candidates_root=candidates,
                    releases_root=releases,
                    active_pointer=releases / "current_release.json",
                    allow_legacy_serving_output=True,
                )

    def test_model_artifacts_route_outside_src_tree(self):
        cases = {
            "feature_model_hgb.pkl": Path("artifacts/models/hgb/feature_model_hgb.pkl"),
            "feature_model_coefs.json": Path("artifacts/models/coefs/feature_model_coefs.json"),
            "late_day_model_coefs_nyc.json": Path("artifacts/models/coefs/late_day_model_coefs_nyc.json"),
            "forecast_error_model_f.json": Path("artifacts/calibration/forecast_error_model_f.json"),
            "f_family_secondary_artifacts.json": Path("artifacts/manifests/f_family_secondary_artifacts.json"),
        }

        for name, suffix in cases.items():
            with self.subTest(name=name):
                path = artifact_path(name)
                self.assertTrue(str(path).replace("\\", "/").endswith(str(suffix).replace("\\", "/")))
                self.assertNotIn("/src/", str(path).replace("\\", "/"))

    def test_legacy_candidate_is_read_fallback_only(self):
        candidates = artifact_candidates("feature_model_coefs.json")

        self.assertEqual(candidates[0], artifact_path("feature_model_coefs.json"))
        self.assertEqual(candidates[1], legacy_artifact_path("feature_model_coefs.json"))

    def test_model_artifact_registry_fingerprints_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calibration = root / "calibration"
            calibration.mkdir()
            model = root / "models" / "hgb"
            model.mkdir(parents=True)
            (calibration / "calibrated_weights.json").write_text(
                '{"schema_version":"calibrated_weights_v0.1","feature_schema_version":"feature_store_v1"}\n',
                encoding="utf-8",
            )
            (model / "feature_model_hgb.pkl").write_bytes(b"model-bytes")

            registry = build_artifact_registry(root=root, generated_at="2026-06-15T00:00:00+00:00")

        self.assertEqual(registry["schema_version"], "model_artifact_registry_v0.1")
        self.assertEqual(registry["artifact_count"], 2)
        self.assertEqual(registry["kind_counts"], {"calibration": 1, "hgb_model": 1})
        rows = {row["artifact_id"]: row for row in registry["artifacts"]}
        self.assertEqual(
            rows["calibration/calibrated_weights.json"]["schema_version"],
            "calibrated_weights_v0.1",
        )
        self.assertEqual(len(rows["models/hgb/feature_model_hgb.pkl"]["sha256"]), 64)

    def test_write_artifact_registry_creates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            root.mkdir()
            (root / "demo.json").write_text('{"schema_version":"demo_v1"}\n', encoding="utf-8")
            out = Path(tmp) / "registry.json"

            written = write_artifact_registry(out, root=root)

            self.assertEqual(written, out)
            self.assertIn("model_artifact_registry_v0.1", out.read_text(encoding="utf-8"))

    def test_artifact_size_audit_warns_before_hosting_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            model = root / "models" / "hgb"
            model.mkdir(parents=True)
            (model / "small.pkl").write_bytes(b"1" * 20)
            (model / "large.pkl").write_bytes(b"1" * 80)

            audit = build_artifact_size_audit(
                root=root,
                generated_at="2026-06-18T00:00:00+00:00",
                individual_warning_bytes=50,
                individual_failure_bytes=100,
                total_warning_bytes=90,
                total_failure_bytes=200,
            )

        self.assertEqual(audit["schema_version"], "model_artifact_size_audit_v0.1")
        self.assertEqual(audit["status"], "WARN")
        self.assertEqual(audit["total_bytes"], 100)
        checks = {(row["kind"], row["status"], row.get("artifact_id")) for row in audit["checks"]}
        self.assertIn(("individual_artifact", "WARN", "models/hgb/large.pkl"), checks)
        self.assertIn(("total_artifacts", "WARN", None), checks)
        self.assertEqual(audit["largest_artifacts"][0]["artifact_id"], "models/hgb/large.pkl")

    def test_artifact_size_audit_fails_at_hard_limit_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            model = root / "models" / "hgb"
            model.mkdir(parents=True)
            (model / "too_large.pkl").write_bytes(b"1" * 120)
            out = Path(tmp) / "model_artifact_size_audit.json"

            written = write_artifact_size_audit(
                out,
                root=root,
                individual_warning_bytes=50,
                individual_failure_bytes=100,
                total_warning_bytes=90,
                total_failure_bytes=200,
            )
            audit = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(written, out)
        self.assertEqual(audit["status"], "FAIL")
        self.assertEqual(audit["checks"][0]["artifact_id"], "models/hgb/too_large.pkl")

    def test_externalization_manifest_reports_managed_restore_entries(self):
        manifest = build_artifact_externalization_manifest(root=Path("missing-artifact-root"))

        self.assertEqual(manifest["schema_version"], "model_artifact_externalization_v0.1")
        self.assertEqual(manifest["managed_artifact_count"], 0)
        self.assertIn("git_lfs", manifest["restore_instructions"])

    def test_promotion_preflight_blocks_active_local_data_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            root.mkdir()
            (root / "demo.json").write_text('{"schema_version":"demo_v1"}\n', encoding="utf-8")
            registry = Path(tmp) / "model_variant_registry.json"
            registry.write_text(
                json.dumps({
                    "variants": [
                        {
                            "variant_id": "active_local",
                            "lifecycle": "active",
                            "roles": ["candidate"],
                            "active_for_headline": True,
                            "artifact_path": "data/backtest/local_candidate.pkl",
                            "artifact_required": True,
                        }
                    ]
                }),
                encoding="utf-8",
            )

            payload = build_artifact_promotion_preflight(
                root=root,
                variant_registry_path=registry,
                generated_at="2026-06-20T00:00:00+00:00",
            )

        self.assertEqual(payload["schema_version"], "model_artifact_promotion_preflight_v0.1")
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("active_local_artifact_path", {row["category"] for row in payload["checks"]})


if __name__ == "__main__":
    unittest.main()
