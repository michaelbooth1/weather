import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from weather.artifacts import artifact_candidates, artifact_path, legacy_artifact_path


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


if __name__ == "__main__":
    unittest.main()
