import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from weather.artifacts import (
    artifact_candidates,
    artifact_path,
    build_artifact_registry,
    legacy_artifact_path,
    write_artifact_registry,
)


class TestArtifactPaths(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
