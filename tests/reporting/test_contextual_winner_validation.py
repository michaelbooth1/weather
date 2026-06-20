import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.contextual_winner_validation import (
    build_payload,
    context_key,
    contextual_probabilities,
    fit_context_factors,
    write_markdown_report,
)


FIELDS = [
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "bin_type",
    "cutoff_regime",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
]


def row(day, snapshot, band, probability, current, market, outcome, bin_type="eq", **extra):
    data = {
        "market_id": "nyc",
        "target_date": day,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": probability,
        "current_probability": current,
        "market_yes": market,
        "outcome": outcome,
        "bin_type": bin_type,
        "cutoff_regime": extra.get("cutoff_regime", "early"),
        "forecast_bucket_pressure": extra.get("forecast_bucket_pressure", "cool_side"),
        "forecast_disagreement_bucket": extra.get("forecast_disagreement_bucket", "low"),
        "forecast_source_count_bucket": extra.get("forecast_source_count_bucket", "many"),
        "source_freshness_state": extra.get("source_freshness_state", "all_fresh"),
    }
    return {key: str(value) for key, value in data.items()}


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class ContextualWinnerValidationTests(unittest.TestCase):
    def test_context_key_uses_inference_available_fields(self):
        source = row("2026-06-01", "s1", "eq:80", 0.20, 0.20, 0.80, 1)
        source["outcome"] = "0"
        source["settlement_distance_bucket"] = "9"

        key = context_key(source, ("cutoff_regime", "forecast_bucket_pressure"))

        self.assertEqual(key, ("nyc", "early", "cool_side"))

    def test_context_key_can_use_candidate_band_key(self):
        source = row("2026-06-01", "s1", "eq:80", 0.20, 0.20, 0.80, 1)

        key = context_key(source, ("band_key", "forecast_bucket_pressure"))

        self.assertEqual(key, ("nyc", "eq:80", "cool_side"))

    def test_contextual_probabilities_normalize_within_snapshot(self):
        rows = [
            {
                "market_id": "nyc",
                "snapshot_id": "s1",
                "probability": 0.25,
                "bin_type": "eq",
                "cutoff_regime": "early",
            },
            {
                "market_id": "nyc",
                "snapshot_id": "s1",
                "probability": 0.75,
                "bin_type": "gte",
                "cutoff_regime": "early",
            },
        ]
        factors = {("nyc", "early"): {"factor": 3.0}}

        probabilities = contextual_probabilities(rows, ("cutoff_regime",), factors)

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertGreater(probabilities[0], 0.25)

    def test_fit_context_factors_boosts_underpriced_context(self):
        rows = [
            {
                "market_id": "nyc",
                "probability": 0.20,
                "outcome": 1,
                "bin_type": "eq",
                "cutoff_regime": "early",
            },
            {
                "market_id": "nyc",
                "probability": 0.30,
                "outcome": 0,
                "bin_type": "eq",
                "cutoff_regime": "early",
            },
        ]

        factors = fit_context_factors(rows, ("cutoff_regime",), min_rows=1, prior_rows=0.0)

        self.assertGreater(factors[("nyc", "early")]["factor"], 1.0)

    def test_build_payload_selects_on_earlier_dates_and_reports_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path, [
                row("2026-06-01", "s1", "eq:80", 0.20, 0.20, 0.60, 1),
                row("2026-06-01", "s1", "eq:82", 0.30, 0.30, 0.20, 0),
                row("2026-06-01", "s1", "gte:84", 0.50, 0.50, 0.20, 0, bin_type="gte"),
                row("2026-06-02", "s2", "eq:80", 0.25, 0.25, 0.55, 1),
                row("2026-06-02", "s2", "eq:82", 0.25, 0.25, 0.25, 0),
                row("2026-06-02", "s2", "gte:84", 0.50, 0.50, 0.20, 0, bin_type="gte"),
            ])

            payload = build_payload(
                [rows_path],
                templates_csv="market,cutoff_regime",
                min_rows=1,
                prior_rows=0.0,
                factor_max=4.0,
            )
            write_markdown_report(report_path, payload)
            report_text = report_path.read_text(encoding="utf-8")

        result = payload["market_results"][0]
        self.assertEqual(result["train_dates"], ["2026-06-01"])
        self.assertEqual(result["eval_dates"], ["2026-06-02"])
        self.assertIn(result["selected_template"], {"market", "cutoff_regime"})
        self.assertIn("eval_oracle", result)
        self.assertEqual(payload["eval_oracle"]["classification"], "diagnostic_only_later_date_selected")
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("eval oracle", report_text)
        self.assertIn("not promotion evidence", report_text)

    def test_build_payload_accepts_band_key_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            write_rows(rows_path, [
                row("2026-06-01", "s1", "eq:80", 0.20, 0.20, 0.60, 1),
                row("2026-06-01", "s1", "eq:82", 0.30, 0.30, 0.20, 0),
                row("2026-06-01", "s1", "gte:84", 0.50, 0.50, 0.20, 0, bin_type="gte"),
                row("2026-06-02", "s2", "eq:80", 0.25, 0.25, 0.55, 1),
                row("2026-06-02", "s2", "eq:82", 0.25, 0.25, 0.25, 0),
                row("2026-06-02", "s2", "gte:84", 0.50, 0.50, 0.20, 0, bin_type="gte"),
            ])

            payload = build_payload(
                [rows_path],
                templates_csv="market,band_key,band_key+forecast_bucket_pressure",
                min_rows=1,
                prior_rows=0.0,
                factor_max=4.0,
            )

        self.assertEqual(payload["schema_version"], "contextual_winner_time_split_validation_v0.2")
        self.assertIn(
            payload["selected_template_by_market"]["nyc"],
            {"market", "band_key", "band_key+forecast_bucket_pressure"},
        )


if __name__ == "__main__":
    unittest.main()
