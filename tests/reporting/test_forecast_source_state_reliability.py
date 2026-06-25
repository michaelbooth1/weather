import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.forecast_source_state_reliability import (
    build_report_payload,
    build_reliability_rows,
    source_state_risk,
    write_markdown_report,
)


def write_variant_csv(path):
    rows = []
    specs = [
        ("all_fresh", "three_plus_sources", "low_disagreement", 0.70, 0.55, 0.65, 1),
        ("failed:open_meteo", "low_count", "high_disagreement", 0.90, 0.30, 0.40, 0),
        ("stale:metar", "two_sources", "moderate_disagreement", 0.20, 0.35, 0.25, 0),
    ]
    for day in ("2026-06-07", "2026-06-08"):
        for idx, (freshness, count, disagreement, forecast_p, current_p, market_p, outcome) in enumerate(specs):
            rows.append({
                "variant_id": "item134_forecast_profile_v0_1",
                "variant_family": "forecast_profile_calibration",
                "uses_market_features": "False",
                "is_control": "False",
                "market_id": "atlanta",
                "target_date": day,
                "snapshot_id": f"{day}-{idx}",
                "band_key": f"eq:{idx}",
                "probability": str(forecast_p),
                "current_probability": str(current_p),
                "recorded_probability": str(current_p),
                "market_yes": str(market_p),
                "outcome": str(outcome),
                "artifact_hash": "abc",
                "postprocess_config_hash": "schema",
                "experiment_start_date": "2026-06-18",
                "captured_at_local": f"{day}T08:00:00-04:00",
                "range_label": "",
                "bin_type": "eq",
                "bin_value": str(idx),
                "cutoff_hour": "8",
                "cutoff_regime": "early",
                "source_freshness_state": freshness,
                "forecast_source_count_bucket": count,
                "forecast_disagreement_bucket": disagreement,
                "forecast_bucket_pressure": "near_forecast",
            })
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class ForecastSourceStateReliabilityTests(unittest.TestCase):
    def test_source_state_risk_scores_failed_low_count_disagreement_high(self):
        risk = source_state_risk({
            "source_freshness_state": "failed:open_meteo",
            "forecast_source_count_bucket": "low_count",
            "forecast_disagreement_bucket": "high_disagreement",
        })

        self.assertEqual(risk["bucket"], "high_risk")
        self.assertLess(risk["alpha"], 0.25)
        self.assertIn("failed source", risk["reason"])

    def test_build_report_payload_scores_reliability_shadow(self):
        with tempfile.TemporaryDirectory() as tmp:
            variant_path = Path(tmp) / "variants.csv"
            out_path = Path(tmp) / "reliability.csv"
            write_variant_csv(variant_path)

            payload = build_report_payload(variant_path, variant_out=out_path)
            rows = build_reliability_rows(variant_path)

            out_exists = out_path.exists()

        self.assertEqual(payload["schema_version"], "forecast_source_state_reliability_v0.1")
        self.assertEqual(payload["variant"]["rows"], 6)
        self.assertTrue(out_exists)
        self.assertTrue(payload["calibration_curve"])
        self.assertEqual(payload["quote_risk_reporting"]["reason_field"], "source_state_reliability_reason")
        self.assertEqual(payload["quote_risk_reporting"]["claim_lane"], "weather_only_quote_risk_diagnostic")
        high_risk = next(row for row in rows if row["source_state_risk_bucket"] == "high_risk")
        self.assertLess(high_risk["reliability_probability"], high_risk["forecast_profile_probability"])
        self.assertEqual(
            {row["group"] for row in payload["by_source_state_slice"]},
            {"all_fresh", "degraded_source"},
        )

    def test_markdown_report_includes_slices_curve_and_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            variant_path = Path(tmp) / "variants.csv"
            report_path = Path(tmp) / "report.md"
            write_variant_csv(variant_path)
            payload = build_report_payload(variant_path, variant_out=None)

            write_markdown_report(report_path, payload)

            text = report_path.read_text(encoding="utf-8")
        self.assertIn("Reliability Slices", text)
        self.assertIn("Calibration Curve", text)
        self.assertIn("Per-Market Reliability Thresholds", text)
        self.assertIn("Quote-Risk Reporting", text)


if __name__ == "__main__":
    unittest.main()
