import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.validation.forecast_side_rank_validation import (
    SCHEMA_VERSION,
    build_payload,
    policy_matches,
    shaped_probabilities,
    write_markdown_report,
)


FIELDNAMES = [
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
]


def row(date, snapshot, band, probability, market_yes, outcome, pressure, market="seattle"):
    return {
        "market_id": market,
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(probability),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "bin_type": "eq",
        "cutoff_regime": "early",
        "forecast_bucket_pressure": pressure,
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class ForecastSideRankValidationTests(unittest.TestCase):
    def test_policy_matches_forecast_pressure_rank_and_metadata(self):
        warm_row = {"forecast_bucket_pressure": "warm_side", "bin_type": "eq", "cutoff_regime": "early"}
        cool_row = {"forecast_bucket_pressure": "cool_side", "bin_type": "eq", "cutoff_regime": "midday"}
        tail_row = {"forecast_bucket_pressure": "warm_side", "bin_type": "gte", "cutoff_regime": "early"}

        self.assertTrue(policy_matches(warm_row, 1, "warm_side_top1"))
        self.assertTrue(policy_matches(warm_row, 2, "off_forecast_pressure_top2"))
        self.assertTrue(policy_matches(warm_row, 1, "early_eq_pressure_top1"))
        self.assertFalse(policy_matches(cool_row, 1, "warm_side_top1"))
        self.assertFalse(policy_matches(cool_row, 1, "early_eq_pressure_top1"))
        self.assertFalse(policy_matches(tail_row, 1, "eq_pressure_top1"))
        self.assertFalse(policy_matches(warm_row, 3, "pressure_top2"))

    def test_shaped_probabilities_boost_top_row_within_each_pressure_side(self):
        rows = [
            {"market_id": "seattle", "target_date": "2026-06-01", "snapshot_id": "s1", "probability": 0.20, "forecast_bucket_pressure": "warm_side", "bin_type": "eq", "cutoff_regime": "early"},
            {"market_id": "seattle", "target_date": "2026-06-01", "snapshot_id": "s1", "probability": 0.60, "forecast_bucket_pressure": "cool_side", "bin_type": "eq", "cutoff_regime": "early"},
            {"market_id": "seattle", "target_date": "2026-06-01", "snapshot_id": "s1", "probability": 0.20, "forecast_bucket_pressure": "near_forecast", "bin_type": "eq", "cutoff_regime": "early"},
        ]

        probabilities = shaped_probabilities(rows, "warm_side_top1", 4.0)

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertGreater(probabilities[0], 0.20)
        self.assertLess(probabilities[1], 0.60)

    def test_build_payload_selects_on_train_and_reports_eval_oracle_as_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            report = Path(tmp) / "report.md"
            write_rows(path, [
                row("2026-06-01", "train", "eq:64", 0.20, 0.70, 1, "warm_side"),
                row("2026-06-01", "train", "eq:62", 0.60, 0.20, 0, "cool_side"),
                row("2026-06-01", "train", "eq:66", 0.20, 0.10, 0, "near_forecast"),
                row("2026-06-02", "eval", "eq:74", 0.20, 0.70, 1, "warm_side"),
                row("2026-06-02", "eval", "eq:72", 0.60, 0.20, 0, "cool_side"),
                row("2026-06-02", "eval", "eq:76", 0.20, 0.10, 0, "near_forecast"),
            ])

            payload = build_payload(
                [path],
                factor_grid="1,4",
                policies_csv="none,warm_side_top1,cool_side_top1,pressure_top1",
                market_tol=0.10,
            )
            write_markdown_report(report, payload)
            report_text = report.read_text(encoding="utf-8")

        result = payload["market_results"][0]
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["train_dates"], ["2026-06-01"])
        self.assertEqual(result["eval_dates"], ["2026-06-02"])
        self.assertEqual(result["selected_policy"], "warm_side_top1")
        self.assertEqual(payload["readiness_status"], "PASS")
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("eval oracle is diagnostic only", report_text)


if __name__ == "__main__":
    unittest.main()
