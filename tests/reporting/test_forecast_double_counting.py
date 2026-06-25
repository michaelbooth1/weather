import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.forecast_double_counting import (
    acceptance,
    build_payload,
    forecast_pull_delta_summary,
    hgb_forecast_attribution,
    write_markdown_report,
)


def _write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ForecastDoubleCountingTests(unittest.TestCase):
    def _write_permutation_inputs(self, root):
        family = Path(root) / "family.csv"
        hgb = Path(root) / "hgb.csv"
        _write_csv(
            family,
            [
                {
                    "slice": "all",
                    "family": "open_meteo_forecast_profile",
                    "hgb_delta_mae_mean": "0.44",
                    "hgb_importance_q": "0.001",
                },
                {
                    "slice": "early",
                    "family": "open_meteo_forecast_profile",
                    "hgb_delta_mae_mean": "0.50",
                    "hgb_importance_q": "0.002",
                },
            ],
        )
        _write_csv(
            hgb,
            [
                {
                    "slice": "all",
                    "family": "open_meteo_forecast_profile",
                    "feature": "forecast_high",
                    "hgb_delta_mae_mean": "0.41",
                    "hgb_importance_q": "0.001",
                },
                {
                    "slice": "all",
                    "family": "open_meteo_forecast_profile",
                    "feature": "forecast_temp_14",
                    "hgb_delta_mae_mean": "0.02",
                    "hgb_importance_q": "0.020",
                },
            ],
        )
        return hgb, family

    def _write_distribution(self, root):
        path = Path(root) / "distribution.json"
        path.write_text(
            json.dumps(
                {
                    "forecast_shape_scope": {
                        "status": "PASS",
                        "current_identity_text": "master@abc src:current",
                        "current_code_feature_model_component_rows": 3,
                        "current_code_feature_model_forecast_shape_rows": 0,
                    },
                    "by_component": [
                        {
                            "group": "forecast_pull",
                            "n": 2,
                            "delta_n": 2,
                            "mean_delta_brier": -0.01,
                            "mean_delta_logloss": 0.04,
                            "mean_winner_probability_delta": 0.10,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_hgb_forecast_attribution_quantifies_forecast_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            hgb, family = self._write_permutation_inputs(tmp)
            payload = hgb_forecast_attribution(hgb, family)

        self.assertEqual(payload["status"], "PASS")
        self.assertAlmostEqual(payload["all_forecast_profile_delta_mae"], 0.44)
        self.assertAlmostEqual(payload["early_forecast_profile_delta_mae"], 0.50)
        self.assertEqual(payload["top_features"][0]["feature"], "forecast_high")

    def test_forecast_pull_delta_blocks_selected_empirical_market_regressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            distribution = self._write_distribution(tmp)
            payload = forecast_pull_delta_summary(
                distribution,
                tmp,
                rows=[
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "toronto",
                        "delta_brier": 0.01,
                        "delta_logloss": -0.02,
                    },
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "nyc",
                        "delta_brier": -0.03,
                        "delta_logloss": 0.04,
                    },
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "hgb",
                        "market_id": "a",
                        "delta_brier": -0.01,
                        "delta_logloss": 0.01,
                    },
                ],
            )

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["selected_empirical_brier_regressing_markets"], ["toronto"])
        self.assertEqual(payload["selected_empirical_logloss_regressing_markets"], ["nyc"])

    def test_forecast_pull_delta_treats_suppressed_empirical_regressions_as_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            distribution = self._write_distribution(tmp)
            payload = forecast_pull_delta_summary(
                distribution,
                tmp,
                rows=[
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "atlanta",
                        "delta_brier": 0.01,
                        "delta_logloss": 0.02,
                    },
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "toronto",
                        "delta_brier": -0.03,
                        "delta_logloss": -0.04,
                    },
                ],
            )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["suppressed_empirical_brier_regressing_markets"], ["atlanta"])
        self.assertEqual(payload["selected_empirical_brier_regressing_markets"], [])

    def test_build_payload_and_report_keep_acceptance_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            hgb, family = self._write_permutation_inputs(tmp)
            distribution = self._write_distribution(tmp)
            payload = build_payload(
                hgb_permutation=hgb,
                family_permutation=family,
                distribution_attribution=distribution,
                snapshots_root=tmp,
                forecast_pull_stage_rows=[
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "atlanta",
                        "delta_brier": 0.01,
                        "delta_logloss": -0.02,
                    },
                    {
                        "component_name": "forecast_pull",
                        "stage_regime": "empirical",
                        "market_id": "toronto",
                        "delta_brier": -0.01,
                        "delta_logloss": -0.02,
                    },
                ],
                now="2026-06-22T00:00:00+00:00",
            )
            report = Path(tmp) / "report.md"
            write_markdown_report(report, payload)
            text = report.read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["acceptance"]["checklist"]["hgb_forecast_feature_attribution_quantified"])
        self.assertTrue(payload["acceptance"]["checklist"]["empirical_fallback_no_per_market_regression"])
        self.assertIn("Forecast Double-Counting Verification", text)
        self.assertIn("Suppressed Empirical Fallback", text)

    def test_acceptance_passes_when_all_gates_are_clean(self):
        payload = {
            "hgb_forecast_attribution": {"status": "PASS"},
            "forecast_pull_delta": {
                "overall_forecast_pull": {"n": 1},
                "forecast_shape_scope": {
                    "status": "PASS",
                    "current_code_feature_model_component_rows": 2,
                    "current_code_feature_model_forecast_shape_rows": 0,
                },
                "selected_empirical_brier_regressing_market_count": 0,
                "selected_empirical_logloss_regressing_market_count": 0,
            },
            "capture_hour_contract": {"status": "PASS"},
        }

        result = acceptance(payload)

        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
