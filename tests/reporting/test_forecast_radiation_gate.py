import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.forecast_radiation_gate import (
    CLOUD_PROXY_FEATURES,
    EXPECTED_FEATURES,
    RADIATION_FEATURES,
    acceptance,
    build_report_payload,
    permutation_evidence,
    write_markdown_report,
)


class ForecastRadiationGateTests(unittest.TestCase):
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

    def _write_variant_csv(self, path):
        fieldnames = [
            "market_id",
            "target_date",
            "snapshot_id",
            "probability",
            "current_probability",
            "recorded_probability",
            "market_yes",
            "outcome",
            "cutoff_hour",
            "cutoff_regime",
            "bin_type",
            "settlement_distance_bucket",
            "source_freshness_state",
            "forecast_source_count_bucket",
            "forecast_disagreement_bucket",
            "forecast_bucket_pressure",
        ]
        rows = []
        for market in ("austin", "dallas"):
            for day in ("2026-06-07", "2026-06-08"):
                for hour, regime in ((7, "early"), (12, "midday"), (17, "late")):
                    rows.append({
                        "market_id": market,
                        "target_date": day,
                        "snapshot_id": f"{market}-{day}-{hour}",
                        "probability": "0.80",
                        "current_probability": "0.60",
                        "recorded_probability": "0.50",
                        "market_yes": "0.78",
                        "outcome": "1",
                        "cutoff_hour": str(hour),
                        "cutoff_regime": regime,
                        "bin_type": "eq",
                        "settlement_distance_bucket": "0",
                        "source_freshness_state": "all_fresh",
                        "forecast_source_count_bucket": "two_sources",
                        "forecast_disagreement_bucket": "low_disagreement",
                        "forecast_bucket_pressure": "near_forecast",
                    })
        for day in ("2026-06-07", "2026-06-08"):
            for hour, regime in ((7, "early"), (12, "midday"), (17, "late")):
                rows.append({
                    "market_id": "chicago",
                    "target_date": day,
                    "snapshot_id": f"chicago-{day}-{hour}",
                    "probability": "0.40",
                    "current_probability": "0.39",
                    "recorded_probability": "0.50",
                    "market_yes": "0.80",
                    "outcome": "1",
                    "cutoff_hour": str(hour),
                    "cutoff_regime": regime,
                    "bin_type": "eq",
                    "settlement_distance_bucket": "0",
                    "source_freshness_state": "all_fresh",
                    "forecast_source_count_bucket": "two_sources",
                    "forecast_disagreement_bucket": "low_disagreement",
                    "forecast_bucket_pressure": "near_forecast",
                })
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _candidate(self, *, feature_subset="forecast_cloud_solar_radiation", blocked_passed=True):
        return {
            "artifact": {
                "feature_subset": feature_subset,
                "schema_version": "pooled_feature_band_hgb_forecast_radiation_v0.1",
                "feature_subset_contract": {
                    "name": feature_subset,
                    "allowed_feature_families": [
                        "forecast_cloud_solar_radiation",
                        "market_climate_context",
                    ],
                },
            },
            "verdict": "PASS",
            "cutover_decision": "SHADOW_READY",
            "blocked_validation": {"passed": blocked_passed, "verdict": "PASS" if blocked_passed else "BLOCK"},
            "by_cutoff_regime": [
                {"group": "early", "n": 3, "delta_vs_current": -0.01},
                {"group": "midday", "n": 2, "delta_vs_current": -0.002},
                {"group": "late", "n": 1, "delta_vs_current": 0.0},
            ],
            "forecast_profile_guardrails": {"blocked_markets": []},
        }

    def test_permutation_evidence_reports_missing_direct_diffuse_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            hgb_path = Path(tmp) / "hgb.csv"
            self._write_hgb_csv(
                hgb_path,
                [
                    "forecast_remaining_solar_sum",
                    "forecast_next_3h_solar_mean",
                    "forecast_high_cloud_mean",
                ],
            )

            evidence = permutation_evidence(hgb_path)

        self.assertEqual(evidence["observed_expected_feature_count"], 3)
        self.assertIn("forecast_remaining_direct_radiation_sum", evidence["missing_direct_diffuse_features"])
        self.assertIn("forecast_total_cloud_mean", evidence["missing_cloud_proxy_features"])
        self.assertEqual(evidence["best_feature"], "forecast_high_cloud_mean")

    def test_acceptance_blocks_full_profile_replay_even_when_slices_improve(self):
        candidate = self._candidate(feature_subset="forecast_profile")
        candidate["artifact"]["feature_subset_contract"] = {
            "name": "forecast_profile",
            "allowed_feature_families": [
                "forecast_cloud_solar_radiation",
                "forecast_profile_temperature",
                "forecast_gap",
                "market_climate_context",
            ],
        }
        evidence = {
            "observed_expected_feature_count": len(EXPECTED_FEATURES),
            "missing_direct_diffuse_features": [],
            "missing_cloud_proxy_features": [],
        }

        result = acceptance(candidate, evidence)

        self.assertEqual(result["status"], "BLOCK")
        self.assertIn("isolated_radiation_replay_missing", {row["code"] for row in result["blockers"]})

    def test_report_payload_passes_for_isolated_replay_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hgb_path = root / "hgb.csv"
            candidate_path = root / "candidate.json"
            report_path = root / "report.md"
            self._write_hgb_csv(hgb_path, EXPECTED_FEATURES)
            candidate_path.write_text(json.dumps(self._candidate()), encoding="utf-8")

            payload = build_report_payload(candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "forecast_radiation_gate_v0.1")
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertEqual(len(payload["permutation_evidence"]["rows"]), len(RADIATION_FEATURES) + len(CLOUD_PROXY_FEATURES))
        self.assertIn("Forecast Radiation & Insolation Gate", text)
        self.assertIn("No blockers.", text)

    def test_report_payload_can_score_positive_market_lane_from_variant_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hgb_path = root / "hgb.csv"
            candidate_path = root / "candidate.json"
            variant_path = root / "variants.csv"
            self._write_hgb_csv(hgb_path, EXPECTED_FEATURES)
            self._write_variant_csv(variant_path)
            candidate_path.write_text(json.dumps(self._candidate(blocked_passed=False)), encoding="utf-8")

            payload = build_report_payload(
                candidate_path,
                hgb_path,
                candidate_variant_csv=variant_path,
            )

        lane = payload["candidate"]["promotion_lane"]
        self.assertEqual(payload["acceptance"]["status"], "PASS")
        self.assertEqual(lane["policy"], "positive_markets_only")
        self.assertEqual(lane["allowed_markets"], ["austin", "dallas"])
        self.assertEqual(lane["quarantined_markets"], ["chicago"])
        self.assertEqual(payload["candidate"]["blocked_validation"]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
