import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.candidate_rank_sharpening_validation import (
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


def row(date, snapshot, band, probability, market_yes, outcome, bin_type="eq"):
    return {
        "market_id": "nyc",
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(probability),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "bin_type": bin_type,
        "cutoff_regime": "early",
        "forecast_bucket_pressure": "warm_side",
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class CandidateRankSharpeningValidationTests(unittest.TestCase):
    def test_policy_matches_candidate_rank_and_metadata_only(self):
        row_data = {"bin_type": "eq", "cutoff_regime": "early"}

        self.assertTrue(policy_matches(row_data, 1, "top2"))
        self.assertTrue(policy_matches(row_data, 2, "eq_top2"))
        self.assertTrue(policy_matches(row_data, 1, "early_eq_top1"))
        self.assertFalse(policy_matches({**row_data, "bin_type": "gte"}, 1, "eq_top1"))
        self.assertFalse(policy_matches({**row_data, "cutoff_regime": "late"}, 1, "early_eq_top1"))
        self.assertFalse(policy_matches(row_data, 3, "top2"))

    def test_shaped_probabilities_normalize_within_snapshot(self):
        rows = [
            {"market_id": "nyc", "snapshot_id": "s1", "probability": 0.50, "bin_type": "eq", "cutoff_regime": "early"},
            {"market_id": "nyc", "snapshot_id": "s1", "probability": 0.30, "bin_type": "eq", "cutoff_regime": "early"},
            {"market_id": "nyc", "snapshot_id": "s1", "probability": 0.20, "bin_type": "gte", "cutoff_regime": "early"},
        ]

        probabilities = shaped_probabilities(rows, "eq_top2", 2.0)

        self.assertAlmostEqual(sum(probabilities), 1.0)
        self.assertGreater(probabilities[0], 0.50)
        self.assertGreater(probabilities[1], 0.30)

    def test_build_payload_blocks_rank_policy_that_fails_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            report = Path(tmp) / "report.md"
            write_rows(path, [
                row("2026-06-01", "train", "eq:80", 0.55, 0.70, 1),
                row("2026-06-01", "train", "eq:82", 0.30, 0.20, 0),
                row("2026-06-01", "train", "gte:84", 0.15, 0.10, 0, "gte"),
                row("2026-06-02", "eval", "eq:80", 0.55, 0.20, 0),
                row("2026-06-02", "eval", "eq:82", 0.30, 0.70, 1),
                row("2026-06-02", "eval", "gte:84", 0.15, 0.10, 0, "gte"),
            ])

            payload = build_payload(
                [path],
                factor_grid="1,2,4",
                policies_csv="none,top1,eq_top1,power",
                market_tol=0.10,
            )
            write_markdown_report(report, payload)
            report_text = report.read_text(encoding="utf-8")

        result = payload["market_results"][0]
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["train_dates"], ["2026-06-01"])
        self.assertEqual(result["eval_dates"], ["2026-06-02"])
        self.assertIn(result["selected_policy"], {"top1", "eq_top1", "power"})
        self.assertEqual(payload["readiness_status"], "BLOCK")
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("not promotion evidence", report_text)


if __name__ == "__main__":
    unittest.main()
