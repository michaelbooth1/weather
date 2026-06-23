import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.calibration.afternoon_residual_centering import (
    build_artifact,
    residual_rows_from_folder,
    write_outputs,
)
from weather.model.calibration_runtime import (
    apply_afternoon_residual_centering,
    distribution_mean,
)


def _write_csv(path, fieldnames, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestAfternoonResidualCentering(unittest.TestCase):
    def test_trainer_fits_market_afternoon_residual_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-nyc-on-june-22-2026"
            folder.mkdir()
            (folder / "settlement.json").write_text(
                json.dumps({
                    "event_slug": folder.name,
                    "market_id": "nyc",
                    "target_date": "2026-06-22",
                    "settlement_bucket": 88,
                    "settlement_unit": "F",
                }),
                encoding="utf-8",
            )
            fields = [
                "snapshot_id",
                "captured_at_local",
                "event_slug",
                "bin_kind",
                "bin_value_c",
                "bin_value_hi_c",
                "model_probability",
                "forecast_disagreement",
            ]
            _write_csv(
                folder / "snapshots_long.csv",
                fields,
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-22T16:00:00-04:00",
                        "event_slug": folder.name,
                        "bin_kind": "eq",
                        "bin_value_c": "88",
                        "bin_value_hi_c": "88",
                        "model_probability": "0.25",
                        "forecast_disagreement": "5.0",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-22T16:00:00-04:00",
                        "event_slug": folder.name,
                        "bin_kind": "eq",
                        "bin_value_c": "90",
                        "bin_value_hi_c": "90",
                        "model_probability": "0.75",
                        "forecast_disagreement": "5.0",
                    },
                ]
                + [
                    {
                        "snapshot_id": f"s{idx}",
                        "captured_at_local": "2026-06-22T16:00:00-04:00",
                        "event_slug": folder.name,
                        "bin_kind": "eq",
                        "bin_value_c": value,
                        "bin_value_hi_c": value,
                        "model_probability": probability,
                        "forecast_disagreement": "5.0",
                    }
                    for idx in range(2, 5)
                    for value, probability in (("88", "0.25"), ("90", "0.75"))
                ]
                + [
                    {
                        "snapshot_id": "s5",
                        "captured_at_local": "2026-06-22T14:00:00-04:00",
                        "event_slug": folder.name,
                        "bin_kind": "eq",
                        "bin_value_c": "90",
                        "bin_value_hi_c": "90",
                        "model_probability": "1.0",
                        "forecast_disagreement": "5.0",
                    }
                ],
            )

            rows = residual_rows_from_folder(folder)
            artifact = build_artifact(rows, [folder], generated_at_utc="2026-06-23T00:00:00+00:00")
            artifact_path, report_path = write_outputs(
                artifact,
                Path(tmp) / "afternoon.json",
                Path(tmp) / "afternoon.md",
            )
            artifact_exists = artifact_path.exists()
            report_exists = report_path.exists()

        self.assertEqual(len(rows), 4)
        self.assertEqual(artifact["schema_version"], "afternoon_residual_centering_v0.1")
        self.assertLess(artifact["contexts"]["market=nyc|hour=16"]["mean_residual"], 0.0)
        self.assertGreater(artifact["validation"]["mean_bias_before"], 0.0)
        self.assertAlmostEqual(artifact["validation"]["mean_bias_after"], 0.0)
        self.assertTrue(artifact_exists)
        self.assertTrue(report_exists)

    def test_runtime_applies_only_afternoon_shift_and_disagreement_spread(self):
        artifact = {
            "component": {
                "enabled": True,
                "start_hour": 15,
                "end_hour": 18,
                "min_context_n": 1,
                "max_abs_shift": 2.0,
                "disagreement_reference": 3.0,
                "spread_sigma_base": 0.75,
                "spread_sigma_per_unit": 0.05,
                "spread_blend_base": 0.0,
                "spread_blend_per_unit": 0.05,
                "spread_blend_max": 0.35,
            },
            "contexts": {
                "market=nyc|hour=16": {
                    "n": 4,
                    "mean_residual": -1.0,
                    "mean_expected_minus_settlement": 1.0,
                }
            },
        }
        scores = {88: 0.2, 89: 0.3, 90: 0.5}

        adjusted, context = apply_afternoon_residual_centering(
            scores,
            artifact,
            market_id="nyc",
            regime_id="marine",
            hour=16,
            forecast_disagreement=6.0,
        )
        inactive, inactive_context = apply_afternoon_residual_centering(
            scores,
            artifact,
            market_id="nyc",
            regime_id="marine",
            hour=14,
            forecast_disagreement=6.0,
        )

        self.assertTrue(context["active"])
        self.assertEqual(context["context_key"], "market=nyc|hour=16")
        self.assertLess(distribution_mean(adjusted), distribution_mean(scores))
        self.assertGreater(context["spread_blend_weight"], 0.0)
        self.assertFalse(inactive_context["active"])
        self.assertEqual(inactive, scores)

    def test_runtime_keeps_global_contexts_diagnostic_by_default(self):
        artifact = {
            "component": {
                "enabled": True,
                "start_hour": 15,
                "end_hour": 18,
                "min_context_n": 4,
                "max_abs_shift": 2.0,
                "allow_global_fallback": False,
            },
            "contexts": {
                "global|hour=16": {
                    "n": 40,
                    "mean_residual": -1.5,
                    "mean_expected_minus_settlement": 1.5,
                }
            },
        }
        scores = {88: 0.2, 89: 0.3, 90: 0.5}

        adjusted, context = apply_afternoon_residual_centering(
            scores,
            artifact,
            market_id="untrained-market",
            regime_id="untrained-regime",
            hour=16,
            forecast_disagreement=6.0,
        )

        self.assertFalse(context["active"])
        self.assertEqual(context["reason"], "no_context")
        self.assertIsNone(context["context_key"])
        self.assertEqual(adjusted, scores)


if __name__ == "__main__":
    unittest.main()
