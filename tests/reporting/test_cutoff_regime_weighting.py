import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.candidate_lifecycle.cutoff_regime_weighting import (
    build_report_payload,
    cutoff_regime,
    family_weight_rows,
    write_markdown_report,
)


FAMILIES = [
    "open_meteo_forecast_profile",
    "observed_temp_path",
    "forecast_source_state",
    "time_context",
    "surface_weather",
]


def write_family_csv(path):
    rows = []
    values = {
        "early": {
            "open_meteo_forecast_profile": 0.50,
            "observed_temp_path": 0.05,
            "forecast_source_state": 0.03,
            "time_context": 0.01,
            "surface_weather": 0.01,
        },
        "midday": {
            "open_meteo_forecast_profile": 0.30,
            "observed_temp_path": 0.20,
            "forecast_source_state": 0.01,
            "time_context": 0.01,
            "surface_weather": 0.0,
        },
        "late": {
            "open_meteo_forecast_profile": 0.05,
            "observed_temp_path": 0.70,
            "forecast_source_state": 0.0,
            "time_context": 0.01,
            "surface_weather": 0.0,
        },
    }
    for slice_name, by_family in values.items():
        for family in FAMILIES:
            rows.append({
                "slice": slice_name,
                "family": family,
                "hgb_delta_mae_mean": by_family[family],
                "hgb_delta_mae_sd": "0.01",
                "hgb_delta_mae_ci_low": "0",
                "hgb_delta_mae_ci_high": "1",
                "hgb_importance_p": "0.01",
                "n_permutations": "5",
                "n_features": "2",
                "hgb_importance_q": "0.02",
            })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_variant_csv(path):
    rows = []
    specs = [
        ("early", 8, 0.75, 0.40, 0.70, 1),
        ("midday", 12, 0.65, 0.55, 0.62, 1),
        ("late", 16, 0.20, 0.82, 0.78, 1),
        ("final", 19, 0.10, 0.86, 0.84, 1),
    ]
    for day in ("2026-06-07", "2026-06-08"):
        for label, hour, forecast_p, current_p, market_p, outcome in specs:
            rows.append({
                "variant_id": "item134_forecast_profile_v0_1",
                "variant_family": "forecast_profile_calibration",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "atlanta",
                "target_date": day,
                "snapshot_id": f"{day}-{label}",
                "band_key": "eq:90.0",
                "probability": str(forecast_p),
                "current_probability": str(current_p),
                "recorded_probability": str(current_p),
                "market_yes": str(market_p),
                "outcome": str(outcome),
                "artifact_hash": "abc",
                "postprocess_config_hash": "schema",
                "experiment_start_date": "2026-06-18",
                "captured_at_local": f"{day}T{hour:02d}:00:00-04:00",
                "range_label": "",
                "bin_type": "eq",
                "bin_value": "90.0",
                "cutoff_hour": str(hour),
            })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class CutoffRegimeWeightingTests(unittest.TestCase):
    def test_cutoff_regime_boundaries(self):
        self.assertEqual(cutoff_regime(8), "early")
        self.assertEqual(cutoff_regime(12), "midday")
        self.assertEqual(cutoff_regime(16), "late")
        self.assertEqual(cutoff_regime(19), "final_lock_in")

    def test_family_weights_shift_from_forecast_to_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            family_path = Path(tmp) / "family.csv"
            write_family_csv(family_path)
            rows = {row["regime"]: row for row in family_weight_rows(family_path)}

        self.assertGreater(rows["early"]["forecast_component_weight"], 0.85)
        self.assertLess(rows["late"]["forecast_component_weight"], 0.10)
        self.assertGreater(rows["late"]["observed_component_weight"], 0.90)
        self.assertEqual(rows["final_lock_in"]["evidence_status"], "late_slice_proxy_until_final_rows_exist")

    def test_report_scores_market_day_clustered_shadow_blend(self):
        with tempfile.TemporaryDirectory() as tmp:
            family_path = Path(tmp) / "family.csv"
            variant_path = Path(tmp) / "variants.csv"
            variant_out = Path(tmp) / "item135.csv"
            write_family_csv(family_path)
            write_variant_csv(variant_path)

            payload = build_report_payload(family_path, variant_path, variant_out=variant_out)
            variant_exists = variant_out.exists()

        self.assertEqual(payload["schema_version"], "cutoff_regime_weighting_v0.1")
        self.assertEqual(payload["no_leakage_audit"]["primary_evidence_unit"], "market_day")
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertEqual(payload["variant"]["rows"], 8)
        self.assertEqual({row["regime"] for row in payload["regime_thresholds"]}, {
            "early",
            "midday",
            "late",
            "final_lock_in",
        })
        self.assertTrue(variant_exists)

    def test_markdown_report_includes_weights_thresholds_and_casebook(self):
        with tempfile.TemporaryDirectory() as tmp:
            family_path = Path(tmp) / "family.csv"
            variant_path = Path(tmp) / "variants.csv"
            report_path = Path(tmp) / "report.md"
            write_family_csv(family_path)
            write_variant_csv(variant_path)
            payload = build_report_payload(family_path, variant_path, variant_out=None)

            write_markdown_report(report_path, payload)

            text = report_path.read_text(encoding="utf-8")
        self.assertIn("Regime Family Weights", text)
        self.assertIn("Separate Regime Thresholds", text)
        self.assertIn("Disagreement Casebook", text)


if __name__ == "__main__":
    unittest.main()
