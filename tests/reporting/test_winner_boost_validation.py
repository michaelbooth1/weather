import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.validation.winner_boost_validation import (
    build_payload,
    policy_matches,
    boosted_probabilities,
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
    "settlement_distance_bucket",
]


def write_rows(path):
    rows = []

    def add(day, snapshot, band, probability, current, market, outcome, bin_type):
        rows.append({
            "market_id": "nyc",
            "target_date": day,
            "snapshot_id": snapshot,
            "band_key": band,
            "probability": probability,
            "current_probability": current,
            "market_yes": market,
            "outcome": outcome,
            "bin_type": bin_type,
            "cutoff_regime": "early",
            "forecast_bucket_pressure": "cool_side",
            "settlement_distance_bucket": "0" if outcome else "1",
        })

    # Earlier date: exact row is underpriced, so an EQ boost should train well.
    add("2026-06-01", "s1", "eq:80", 0.20, 0.20, 0.60, 1, "eq")
    add("2026-06-01", "s1", "eq:82", 0.30, 0.30, 0.20, 0, "eq")
    add("2026-06-01", "s1", "gte:84", 0.50, 0.50, 0.20, 0, "gte")
    # Later date evaluates the selected policy without overlapping dates.
    add("2026-06-02", "s2", "eq:80", 0.25, 0.25, 0.55, 1, "eq")
    add("2026-06-02", "s2", "eq:82", 0.25, 0.25, 0.25, 0, "eq")
    add("2026-06-02", "s2", "gte:84", 0.50, 0.50, 0.20, 0, "gte")

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class WinnerBoostValidationTests(unittest.TestCase):
    def test_policy_matches_use_inference_available_fields(self):
        row = {
            "bin_type": "eq",
            "cutoff_regime": "early",
            "forecast_bucket_pressure": "cool_side",
            "settlement_distance_bucket": "0",
        }

        self.assertTrue(policy_matches(row, "all_eq"))
        self.assertTrue(policy_matches(row, "early_eq"))
        self.assertFalse(policy_matches(row, "midday_eq"))
        self.assertTrue(policy_matches(row, "off_forecast_eq"))
        self.assertTrue(policy_matches(row, "cool_side_eq"))
        self.assertTrue(policy_matches(row, "early_cool_side_eq"))
        self.assertFalse(policy_matches(row, "early_warm_side_eq"))
        self.assertFalse(policy_matches(row, "near_forecast_eq"))
        self.assertFalse(policy_matches({**row, "bin_type": "gte"}, "all_eq"))

    def test_boosted_probabilities_normalize_within_snapshot(self):
        rows = [
            {"market_id": "nyc", "snapshot_id": "s1", "probability": 0.25, "bin_type": "eq", "cutoff_regime": "early", "forecast_bucket_pressure": "cool_side"},
            {"market_id": "nyc", "snapshot_id": "s1", "probability": 0.75, "bin_type": "gte", "cutoff_regime": "early", "forecast_bucket_pressure": "cool_side"},
        ]

        probabilities = boosted_probabilities(rows, "all_eq", 3.0)

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertGreater(probabilities[0], 0.25)

    def test_build_payload_selects_on_earlier_dates_and_reports_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path)

            payload = build_payload(
                [rows_path],
                factor_grid="1,2,3",
                policies_csv="none,all_eq,early_eq,off_forecast_eq,cool_side_eq,early_cool_side_eq",
            )
            write_markdown_report(report_path, payload)
            report_text = report_path.read_text(encoding="utf-8")

        result = payload["market_results"][0]
        self.assertEqual(result["train_dates"], ["2026-06-01"])
        self.assertEqual(result["eval_dates"], ["2026-06-02"])
        self.assertIn(
            result["selected_policy"],
            {"all_eq", "early_eq", "off_forecast_eq", "cool_side_eq", "early_cool_side_eq"},
        )
        self.assertGreater(result["selected_factor"], 1.0)
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("not promotion evidence", report_text)


if __name__ == "__main__":
    unittest.main()
