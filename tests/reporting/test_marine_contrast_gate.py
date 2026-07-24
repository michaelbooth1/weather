import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weather.reporting.source_gates.marine_contrast_gate import (
    WATER_CONTRAST_FEATURES,
    acceptance,
    build_report_payload,
    source_inventory_evidence,
    write_markdown_report,
)
from weather.reporting.source_gates.source_artifact_binding import (
    stable_json_artifact,
)
from tests.reporting.source_family_contract_fixtures import (
    operational_ablation_payload,
    operational_inventory,
)


class MarineContrastGateTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "weather.reporting.source_gates.marine_contrast_gate."
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
                "family": "marine_microclimate",
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
        historical_status="marine_station_archive_available",
        active=True,
        parity="PASS",
        missing_folders=0,
    ):
        return operational_inventory(
            [
                {
                    "family_id": "marine_context",
                    "source_keys": ["marine_context"],
                    "historical_archive_status": historical_status,
                    "live_only": False,
                    "live_only_policy": "parity_required_before_promotion",
                    "train_serve_parity_status": parity,
                    "lineage_status": "PASS" if missing_folders == 0 else "PARTIAL_SOURCE_STATUS",
                    "active_model_usage_status": "ACTIVE_FEATURES" if active else "NOT_USED_BY_ACTIVE_ARTIFACT",
                    "feature_columns": list(WATER_CONTRAST_FEATURES),
                    "active_model_feature_columns": list(WATER_CONTRAST_FEATURES) if active else [],
                    "source_status": {
                        "sources_seen": ["marine_context"],
                        "rows": 10,
                        "folder_count": 1,
                        "missing_folder_count": missing_folders,
                    },
                    "feature_missingness": {"missing_rate": 0.0},
                }
            ]
        )

    def _candidate(self, *, feature_subset="marine_context", onshore_rows=3):
        return {
            "artifact": {
                "feature_subset": feature_subset,
                "feature_subset_contract": {
                    "name": feature_subset,
                    "allowed_feature_families": ["marine_context", "market_climate_context", "market_band_geometry"],
                },
                "feature_names": [*WATER_CONTRAST_FEATURES, "band_mid", "market_id_nyc"],
                "schema_version": "pooled_feature_band_hgb_marine_context_v0.1",
            },
            "aggregate": {"delta_vs_current": -0.001},
            "blocked_validation": {"passed": True, "verdict": "PASS"},
            "by_marine_breeze_slice": [
                {"group": "onshore_breeze", "n": onshore_rows, "delta_vs_current": -0.02},
            ],
            "verdict": "PASS",
            "cutover_decision": "SHADOW_READY",
        }

    def _ablation(self, *, delta=0.01):
        return operational_ablation_payload(
            [
                {
                    "variant": "marine_context",
                    "delta": delta,
                    "market_days": 3,
                    "n": 100,
                    "market_days_source_helped": 2 if delta > 0 else 0,
                    "market_days_source_hurt": 0,
                }
            ]
        )

    def test_source_inventory_evidence_reports_partial_marine_lineage(self):
        evidence = source_inventory_evidence(
            self._inventory(
                historical_status="station_archive_partial",
                active=False,
                parity="PARTIAL_MISSINGNESS",
                missing_folders=4,
            )
        )

        self.assertTrue(evidence["marine_source_status_seen"])
        self.assertEqual(evidence["active_contrast_features"], [])
        self.assertEqual(evidence["missing_source_status_folder_count"], 4)
        self.assertEqual(evidence["train_serve_parity_status"], "PARTIAL_MISSINGNESS")

    def test_acceptance_blocks_full_profile_without_marine_contrast_replay(self):
        candidate = self._candidate(feature_subset="forecast_profile", onshore_rows=0)
        candidate["artifact"]["feature_subset_contract"] = {
            "name": "forecast_profile",
            "allowed_feature_families": ["forecast_profile_temperature", "market_climate_context"],
        }
        source_evidence = source_inventory_evidence(
            self._inventory(
                historical_status="station_archive_partial",
                active=False,
                parity="PARTIAL_MISSINGNESS",
                missing_folders=4,
            )
        )
        permutation = {
            "observed_water_contrast_feature_count": 0,
            "missing_water_contrast_features": list(WATER_CONTRAST_FEATURES),
        }

        result = acceptance(candidate, source_evidence, {"delta": 0.0}, permutation)

        codes = {row["code"] for row in result["blockers"]}
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("isolated_marine_replay_missing", codes)
        self.assertIn("marine_ablation_no_positive_lift", codes)
        self.assertIn("onshore_breeze_settlement_slice_missing", codes)

    def test_report_payload_passes_for_marine_candidate_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "source_inventory.json"
            ablation_path = root / "ablation.json"
            candidate_path = root / "candidate.json"
            hgb_path = root / "hgb.csv"
            report_path = root / "report.md"
            ablation_path.write_text(json.dumps(self._ablation()), encoding="utf-8")
            _ablation, ablation_receipt = stable_json_artifact(ablation_path)
            inventory = self._inventory()
            inventory["ablation_input_receipt"] = ablation_receipt
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self._write_hgb_csv(hgb_path, WATER_CONTRAST_FEATURES)

            payload = build_report_payload(inventory_path, ablation_path, candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "marine_contrast_gate_v0.1")
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertFalse(payload["serving_or_release_authorization"])
        self.assertEqual(payload["permutation_evidence"]["observed_water_contrast_feature_count"], len(WATER_CONTRAST_FEATURES))
        self.assertIn("Marine Contrast Gate", text)
        self.assertIn("runtime current-input revalidation is required", text)
        self.assertIn("No blockers.", text)

    def test_report_payload_blocks_ablation_replaced_after_inventory_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "source_inventory.json"
            ablation_path = root / "ablation.json"
            candidate_path = root / "candidate.json"
            hgb_path = root / "hgb.csv"
            ablation_path.write_text(json.dumps(self._ablation()), encoding="utf-8")
            _ablation, ablation_receipt = stable_json_artifact(ablation_path)
            inventory = self._inventory()
            inventory["ablation_input_receipt"] = ablation_receipt
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self._write_hgb_csv(hgb_path, WATER_CONTRAST_FEATURES)
            ablation_path.write_text(
                json.dumps(self._ablation(delta=0.02)),
                encoding="utf-8",
            )

            payload = build_report_payload(
                inventory_path,
                ablation_path,
                candidate_path,
                hgb_path,
            )

        codes = {
            row["code"] for row in payload["acceptance"]["blockers"]
        }
        self.assertEqual(payload["acceptance"]["status"], "BLOCK")
        self.assertIn("marine_ablation_not_bound_to_inventory", codes)


if __name__ == "__main__":
    unittest.main()
