import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather.reporting.source_gates.global_model_guidance_gate import (
    GLOBAL_MODEL_FEATURES,
    acceptance,
    build_report_payload,
    source_inventory_evidence,
    write_markdown_report,
)
from tests.reporting.source_family_contract_fixtures import operational_inventory


class GlobalModelGuidanceGateTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "weather.reporting.source_gates.global_model_guidance_gate."
            "source_family_inventory_consumer_contract",
            return_value={"status": "PASS", "blockers": []},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_hgb_csv(self, path, features):
        rows = [
            {
                "slice": "all",
                "feature": feature,
                "family": "official_multimodel_guidance",
                "hgb_delta_mae_mean": str(0.01 + idx / 1000),
                "hgb_delta_mae_sd": "0.001",
                "hgb_delta_mae_ci_low": "0.001",
                "hgb_delta_mae_ci_high": "0.010",
                "hgb_importance_p": "0.05",
                "n_permutations": "5",
                "hgb_importance_q": str(0.2 + idx / 100),
            }
            for idx, feature in enumerate(features)
        ]
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _inventory(
        self,
        *,
        global_seen=True,
        historical_status="model_run_archive_available",
        active=True,
        parity="PASS",
        missing_folders=0,
    ):
        return operational_inventory(
            [
                {
                    "family_id": "multi_model_guidance",
                    "source_keys": ["open_meteo_multimodel", "open_meteo_global_models", "global_ensemble"],
                    "historical_archive_status": historical_status,
                    "live_only": False,
                    "live_only_policy": "parity_required_before_promotion",
                    "train_serve_parity_status": parity,
                    "lineage_status": "PASS" if missing_folders == 0 else "PARTIAL_SOURCE_STATUS",
                    "active_model_usage_status": "ACTIVE_FEATURES" if active else "NOT_USED_BY_ACTIVE_ARTIFACT",
                    "feature_columns": list(GLOBAL_MODEL_FEATURES),
                    "active_model_feature_columns": list(GLOBAL_MODEL_FEATURES) if active else [],
                    "source_status": {
                        "sources_seen": ["open_meteo_global_models"] if global_seen else ["open_meteo_multimodel"],
                    },
                    "forecast_payloads": {
                        "sources_seen": ["open_meteo_global_models"] if global_seen else ["open_meteo_multimodel"],
                        "rows": 12,
                        "folder_count": 1,
                        "missing_folder_count": missing_folders,
                    },
                    "feature_missingness": {"missing_rate": 0.0},
                }
            ]
        )

    def _candidate(self, *, feature_subset="global_model_guidance", early_n=3):
        return {
            "artifact": {
                "feature_subset": feature_subset,
                "feature_subset_contract": {
                    "name": feature_subset,
                    "allowed_feature_families": ["global_model_guidance", "market_climate_context"],
                },
                "schema_version": "pooled_feature_band_hgb_global_model_guidance_v0.1",
            },
            "aggregate": {"delta_vs_current": -0.001},
            "blocked_validation": {"passed": True, "verdict": "PASS"},
            "by_cutoff_regime": [
                {"group": "early", "n": early_n, "delta_vs_current": -0.02},
                {"group": "late", "n": 1, "delta_vs_current": 0.0},
            ],
            "verdict": "PASS",
            "cutover_decision": "SHADOW_READY",
        }

    def test_source_inventory_evidence_reports_partial_global_model_lineage(self):
        evidence = source_inventory_evidence(
            self._inventory(
                global_seen=False,
                historical_status="live_only_until_model_run_archive_backfill",
                active=False,
                parity="LINEAGE_BLOCKED",
                missing_folders=2,
            )
        )

        self.assertFalse(evidence["global_model_source_status_seen"])
        self.assertFalse(evidence["global_model_forecast_payload_seen"])
        self.assertEqual(evidence["active_global_model_features"], [])
        self.assertEqual(evidence["missing_forecast_payload_folder_count"], 2)
        self.assertEqual(evidence["train_serve_parity_status"], "LINEAGE_BLOCKED")

    def test_acceptance_blocks_full_profile_without_global_model_replay(self):
        candidate = self._candidate(feature_subset="forecast_profile", early_n=3)
        candidate["artifact"]["feature_subset_contract"] = {
            "name": "forecast_profile",
            "allowed_feature_families": [
                "forecast_profile_temperature",
                "forecast_cloud_solar_radiation",
                "market_climate_context",
            ],
        }
        source_evidence = source_inventory_evidence(
            self._inventory(
                historical_status="live_only_until_model_run_archive_backfill",
                active=False,
                parity="LINEAGE_BLOCKED",
                missing_folders=2,
            )
        )
        permutation = {
            "observed_global_model_feature_count": 0,
            "missing_global_model_features": list(GLOBAL_MODEL_FEATURES),
        }

        result = acceptance(candidate, source_evidence, permutation)

        codes = {row["code"] for row in result["blockers"]}
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("isolated_global_model_replay_missing", codes)
        self.assertIn("historical_global_model_backfill_missing", codes)
        self.assertIn("global_model_permutation_evidence_missing", codes)

    def test_report_payload_passes_for_global_model_candidate_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "source_inventory.json"
            candidate_path = root / "candidate.json"
            hgb_path = root / "hgb.csv"
            report_path = root / "report.md"
            inventory_path.write_text(json.dumps(self._inventory()), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self._write_hgb_csv(hgb_path, GLOBAL_MODEL_FEATURES)

            payload = build_report_payload(inventory_path, candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "global_model_guidance_gate_v0.1")
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertFalse(payload["serving_or_release_authorization"])
        self.assertEqual(payload["permutation_evidence"]["observed_global_model_feature_count"], len(GLOBAL_MODEL_FEATURES))
        self.assertIn("Global Model Guidance Gate", text)
        self.assertIn("runtime current-input revalidation is required", text)
        self.assertIn("No blockers.", text)


if __name__ == "__main__":
    unittest.main()
