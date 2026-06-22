import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.nbm_probabilistic_tmax_gate import (
    NBM_FEATURES,
    acceptance,
    build_report_payload,
    source_inventory_evidence,
    write_markdown_report,
)


class NbmProbabilisticTmaxGateTests(unittest.TestCase):
    def _write_hgb_csv(self, path, features):
        rows = [
            {
                "slice": "all",
                "feature": feature,
                "family": "official_us_guidance",
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
        nbm_payload_seen=True,
        historical_status="nbp_station_archive_available",
        active=True,
        parity="PASS",
        missing_folders=0,
    ):
        sources = ["nws_grid", "nws_hourly", "nbm_probabilistic_tmax"]
        payload_sources = sources if nbm_payload_seen else ["nws_grid", "nws_hourly"]
        return {
            "inventory": [
                {
                    "family_id": "nws_grid",
                    "source_keys": sources,
                    "historical_archive_status": historical_status,
                    "live_only": False,
                    "live_only_policy": "parity_required_before_promotion",
                    "train_serve_parity_status": parity,
                    "lineage_status": "PASS" if missing_folders == 0 else "PARTIAL_SOURCE_STATUS",
                    "active_model_usage_status": "ACTIVE_FEATURES" if active else "NOT_USED_BY_ACTIVE_ARTIFACT",
                    "feature_columns": list(NBM_FEATURES),
                    "active_model_feature_columns": list(NBM_FEATURES) if active else [],
                    "source_status": {"sources_seen": sources},
                    "forecast_payloads": {
                        "sources_seen": payload_sources,
                        "rows": 12,
                        "folder_count": 1,
                        "missing_folder_count": missing_folders,
                    },
                    "feature_missingness": {"missing_rate": 0.0},
                }
            ]
        }

    def _candidate(self, *, feature_subset="nbm_probabilistic_tmax", market_rows=2):
        return {
            "artifact": {
                "feature_subset": feature_subset,
                "feature_subset_contract": {
                    "name": feature_subset,
                    "allowed_feature_families": ["nbm_probabilistic_tmax", "market_climate_context"],
                },
                "schema_version": "pooled_feature_band_hgb_nbm_prob_v0.1",
            },
            "aggregate": {"delta_vs_current": -0.001},
            "blocked_validation": {"passed": True, "verdict": "PASS"},
            "by_nbm_us_market": [
                {"group": f"market-{idx}", "n": 10, "delta_vs_current": -0.001}
                for idx in range(market_rows)
            ],
            "verdict": "PASS",
            "cutover_decision": "SHADOW_READY",
        }

    def test_source_inventory_evidence_separates_status_from_payload_capture(self):
        evidence = source_inventory_evidence(
            self._inventory(
                nbm_payload_seen=False,
                historical_status="live_only_until_grid_archive_backfill",
                active=False,
                parity="LINEAGE_BLOCKED",
                missing_folders=3,
            )
        )

        self.assertTrue(evidence["nbm_source_status_seen"])
        self.assertFalse(evidence["nbm_forecast_payload_seen"])
        self.assertEqual(evidence["active_nbm_features"], [])
        self.assertEqual(evidence["missing_forecast_payload_folder_count"], 3)

    def test_acceptance_blocks_full_profile_without_nbm_replay(self):
        candidate = self._candidate(feature_subset="forecast_profile", market_rows=0)
        candidate["artifact"]["feature_subset_contract"] = {
            "name": "forecast_profile",
            "allowed_feature_families": ["forecast_profile_temperature", "market_climate_context"],
        }
        source_evidence = source_inventory_evidence(
            self._inventory(
                nbm_payload_seen=False,
                historical_status="live_only_until_grid_archive_backfill",
                active=False,
                parity="LINEAGE_BLOCKED",
                missing_folders=3,
            )
        )
        permutation = {"observed_expected_feature_count": 0, "missing_expected_features": list(NBM_FEATURES)}

        result = acceptance(candidate, source_evidence, permutation)

        codes = {row["code"] for row in result["blockers"]}
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("isolated_nbm_replay_missing", codes)
        self.assertIn("nbm_forecast_payload_missing", codes)
        self.assertIn("us_market_settlement_slices_missing", codes)

    def test_report_payload_passes_for_nbm_candidate_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "source_inventory.json"
            candidate_path = root / "candidate.json"
            hgb_path = root / "hgb.csv"
            report_path = root / "report.md"
            inventory_path.write_text(json.dumps(self._inventory()), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self._write_hgb_csv(hgb_path, NBM_FEATURES)

            payload = build_report_payload(inventory_path, candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "nbm_probabilistic_tmax_gate_v0.1")
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertEqual(payload["permutation_evidence"]["observed_expected_feature_count"], len(NBM_FEATURES))
        self.assertIn("NBM Probabilistic Tmax Gate", text)
        self.assertIn("No blockers.", text)


if __name__ == "__main__":
    unittest.main()
