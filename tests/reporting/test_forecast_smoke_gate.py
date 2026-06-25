import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.forecast_smoke_gate import (
    SMOKE_FEATURES,
    acceptance,
    build_report_payload,
    source_inventory_evidence,
    write_markdown_report,
)


class ForecastSmokeGateTests(unittest.TestCase):
    def _write_hgb_csv(self, path, features):
        rows = [
            {
                "slice": "all",
                "feature": feature,
                "family": "open_meteo_forecast_profile",
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

    def _inventory(self, *, aq_seen=True, historical_status="historical_aq_archive_available", active=True):
        return {
            "inventory": [
                {
                    "family_id": "open_meteo_expanded",
                    "source_keys": ["open_meteo", "open_meteo_air_quality"],
                    "historical_archive_status": historical_status,
                    "live_only": False,
                    "live_only_policy": "parity_required_before_promotion",
                    "train_serve_parity_status": "PASS",
                    "lineage_status": "PASS",
                    "feature_columns": list(SMOKE_FEATURES),
                    "active_model_feature_columns": list(SMOKE_FEATURES) if active else [],
                    "source_status": {
                        "sources_seen": ["open_meteo", "open_meteo_air_quality"] if aq_seen else ["open_meteo"],
                    },
                    "forecast_payloads": {
                        "sources_seen": ["open_meteo", "open_meteo_air_quality"] if aq_seen else ["open_meteo"],
                        "rows": 12,
                        "folder_count": 1,
                    },
                    "feature_missingness": {"missing_rate": 0.0},
                }
            ]
        }

    def _candidate(self, *, feature_subset="forecast_aerosol_smoke", high_smoke_n=3):
        return {
            "artifact": {
                "feature_subset": feature_subset,
                "feature_subset_contract": {
                    "name": feature_subset,
                    "allowed_feature_families": ["forecast_aerosol_smoke", "market_climate_context"],
                },
                "schema_version": "pooled_feature_band_hgb_forecast_smoke_v0.1",
            },
            "aggregate": {"delta_vs_current": -0.001},
            "blocked_validation": {"passed": True, "verdict": "PASS"},
            "by_smoke_slice": [
                {"group": "high_smoke", "n": high_smoke_n, "delta_vs_current": -0.02},
            ],
            "verdict": "PASS",
            "cutover_decision": "SHADOW_READY",
        }

    def test_source_inventory_evidence_flags_missing_aq_capture_and_active_columns(self):
        evidence = source_inventory_evidence(
            self._inventory(aq_seen=False, historical_status="partial_forecast_history_archive", active=False)
        )

        self.assertFalse(evidence["aq_source_status_seen"])
        self.assertFalse(evidence["aq_forecast_payload_seen"])
        self.assertEqual(evidence["active_smoke_features"], [])
        self.assertEqual(evidence["historical_archive_status"], "partial_forecast_history_archive")

    def test_acceptance_blocks_full_profile_without_smoke_slice(self):
        candidate = self._candidate(feature_subset="forecast_profile", high_smoke_n=0)
        candidate["artifact"]["feature_subset_contract"] = {
            "name": "forecast_profile",
            "allowed_feature_families": [
                "forecast_profile_temperature",
                "forecast_cloud_solar_radiation",
                "market_climate_context",
            ],
        }
        source_evidence = source_inventory_evidence(
            self._inventory(aq_seen=False, historical_status="partial_forecast_history_archive", active=False)
        )
        permutation = {"observed_expected_feature_count": 0, "missing_expected_features": list(SMOKE_FEATURES)}

        result = acceptance(candidate, source_evidence, permutation)

        codes = {row["code"] for row in result["blockers"]}
        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("isolated_smoke_replay_missing", codes)
        self.assertIn("aq_payload_capture_missing", codes)
        self.assertIn("high_smoke_settlement_slice_missing", codes)

    def test_report_payload_passes_for_smoke_candidate_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "source_inventory.json"
            candidate_path = root / "candidate.json"
            hgb_path = root / "hgb.csv"
            report_path = root / "report.md"
            inventory_path.write_text(json.dumps(self._inventory()), encoding="utf-8")
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")
            self._write_hgb_csv(hgb_path, SMOKE_FEATURES)

            payload = build_report_payload(inventory_path, candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "forecast_smoke_gate_v0.1")
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertEqual(payload["permutation_evidence"]["observed_expected_feature_count"], len(SMOKE_FEATURES))
        self.assertIn("Forecast Smoke Suppression Gate", text)
        self.assertIn("No blockers.", text)


if __name__ == "__main__":
    unittest.main()
