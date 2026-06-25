import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.forecast_profile_calibration import (
    acceptance,
    build_report_payload,
    forecast_profile_subfamily_rows,
    write_markdown_report,
)


class ForecastProfileCalibrationTests(unittest.TestCase):
    def _write_hgb_csv(self, path):
        rows = [
            {
                "slice": "all",
                "feature": "forecast_high",
                "family": "open_meteo_forecast_profile",
                "hgb_delta_mae_mean": "0.50",
                "hgb_importance_q": "0.001",
            },
            {
                "slice": "all",
                "feature": "forecast_temp_14",
                "family": "open_meteo_forecast_profile",
                "hgb_delta_mae_mean": "0.04",
                "hgb_importance_q": "0.02",
            },
            {
                "slice": "all",
                "feature": "forecast_total_cloud_mean",
                "family": "open_meteo_forecast_profile",
                "hgb_delta_mae_mean": "0.01",
                "hgb_importance_q": "0.40",
            },
        ]
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_subfamily_rows_label_marginal_basis_after_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            hgb_path = Path(tmp) / "hgb.csv"
            self._write_hgb_csv(hgb_path)

            rows = forecast_profile_subfamily_rows(hgb_path)

        by_family = {row["subfamily"]: row for row in rows}
        self.assertEqual(by_family["forecast_high_anchor"]["marginal_basis"], "anchor_feature")
        self.assertEqual(
            by_family["hourly_temperature_profile"]["marginal_basis"],
            "marginal permutation with forecast_high retained in the fitted model",
        )
        self.assertEqual(by_family["hourly_temperature_profile"]["best_feature"], "forecast_temp_14")

    def test_acceptance_blocks_missing_or_regressing_slices(self):
        payload = {
            "artifact": {"feature_subset": "forecast_profile"},
            "daily_first": {"delta_vs_current": -0.01},
            "blocked_validation": {"passed": True},
            "by_cutoff_regime": [
                {"group": "early", "delta_vs_current": -0.02},
                {"group": "midday", "delta_vs_current": 0.002},
                {"group": "late", "delta_vs_current": 0.010},
            ],
            "forecast_profile_guardrails": {"blocked_markets": []},
        }

        result = acceptance(payload, current_tol=0.003)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("late slice regresses current", result["reasons"][0])

    def test_report_payload_and_markdown_include_slices_and_subfamilies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hgb_path = root / "hgb.csv"
            candidate_path = root / "candidate.json"
            report_path = root / "report.md"
            self._write_hgb_csv(hgb_path)
            candidate_path.write_text(
                json.dumps({
                    "artifact": {
                        "feature_subset": "forecast_profile",
                        "schema_version": "pooled_feature_band_hgb_forecast_profile_v0.1",
                    },
                    "verdict": "BLOCK",
                    "cutover_decision": "DO_NOT_CUT_OVER",
                    "daily_first": {"delta_vs_current": -0.01},
                    "blocked_validation": {"passed": True, "verdict": "PASS"},
                    "by_cutoff_regime": [
                        {"group": "early", "n": 3, "delta_vs_current": -0.01},
                        {"group": "midday", "n": 2, "delta_vs_current": 0.0},
                        {"group": "late", "n": 1, "delta_vs_current": 0.0},
                    ],
                    "by_forecast_disagreement": [
                        {"group": "high_disagreement", "n": 1, "delta_vs_current": 0.01},
                    ],
                    "forecast_profile_guardrails": {
                        "blocked_markets": [],
                        "rows": [],
                    },
                }),
                encoding="utf-8",
            )

            payload = build_report_payload(candidate_path, hgb_path)
            write_markdown_report(report_path, payload)
            text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "forecast_profile_calibration_v0.1")
        self.assertIn("Forecast-Profile Subfamilies", text)
        self.assertIn("hourly_temperature_profile", text)
        self.assertIn("Forecast Disagreement", text)


if __name__ == "__main__":
    unittest.main()
