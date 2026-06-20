import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.winner_underpricing_casebook import (
    SCHEMA_VERSION,
    build_payload,
    effective_band_count,
    read_rows,
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
    "captured_at_local",
    "cutoff_hour",
    "cutoff_regime",
    "bin_type",
    "bin_value",
    "settlement_distance_bucket",
    "source_freshness_state",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
]


def row(snapshot, band, probability, market_yes, outcome, **extra):
    data = {
        "market_id": extra.get("market_id", "seattle"),
        "target_date": extra.get("target_date", "2026-06-13"),
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": probability,
        "current_probability": extra.get("current_probability", probability),
        "market_yes": market_yes,
        "outcome": outcome,
        "captured_at_local": extra.get("captured_at_local", "2026-06-13T04:00:00-04:00"),
        "cutoff_hour": extra.get("cutoff_hour", "7"),
        "cutoff_regime": extra.get("cutoff_regime", "early"),
        "bin_type": extra.get("bin_type", "eq"),
        "bin_value": extra.get("bin_value", band.replace("eq:", "")),
        "settlement_distance_bucket": extra.get("settlement_distance_bucket", "0" if outcome else "1"),
        "source_freshness_state": extra.get("source_freshness_state", "all_fresh"),
        "forecast_bucket_pressure": extra.get("forecast_bucket_pressure", "near"),
        "forecast_disagreement_bucket": extra.get("forecast_disagreement_bucket", "low"),
        "forecast_source_count_bucket": extra.get("forecast_source_count_bucket", "three_plus"),
    }
    return {key: str(value) for key, value in data.items()}


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class WinnerUnderpricingCasebookTests(unittest.TestCase):
    def test_effective_band_count_normalizes_probabilities(self):
        rows = [
            {"probability": 2.0},
            {"probability": 2.0},
        ]

        self.assertAlmostEqual(effective_band_count(rows, "probability"), 2.0)

    def test_build_payload_finds_early_market_ranked_winner_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_rows(path, [
                row("s1", "eq:70", 0.30, 0.10, 0, bin_value="70", settlement_distance_bucket="1"),
                row("s1", "eq:71", 0.28, 0.05, 0, bin_value="71", settlement_distance_bucket="1"),
                row("s1", "eq:72", 0.12, 0.70, 1, bin_value="72", settlement_distance_bucket="0"),
                row("s1", "eq:73", 0.30, 0.15, 0, bin_value="73", settlement_distance_bucket="1"),
            ])

            payload = build_payload([path], markets=["seattle"], limit=10)

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["summary"]["case_count"], 1)
        case = payload["cases"][0]
        self.assertEqual(case["winner_band_key"], "eq:72")
        self.assertEqual(case["winner_market_rank"], 1)
        self.assertGreater(case["winner_probability_gap_vs_market"], 0.50)
        self.assertGreater(case["candidate_effective_bands"], case["market_effective_bands"])
        pattern_rows = payload["summary"]["pattern_summary"]
        self.assertIn({
            "market_id": "seattle",
            "field": "forecast_bucket_pressure",
            "value": "near",
            "cases": 1,
            "share": 1.0,
            "avg_winner_probability_gap_vs_market": case["winner_probability_gap_vs_market"],
            "avg_winner_rank_gap_vs_market": case["winner_rank_gap_vs_market"],
            "avg_effective_band_gap_vs_market": case["effective_band_gap_vs_market"],
        }, pattern_rows)

    def test_build_payload_skips_late_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            write_rows(path, [
                row("s1", "eq:70", 0.30, 0.10, 0, captured_at_local="2026-06-13T13:00:00-04:00"),
                row("s1", "eq:72", 0.12, 0.70, 1, captured_at_local="2026-06-13T13:00:00-04:00"),
            ])

            payload = build_payload([path], markets=["seattle"])

        self.assertEqual(payload["summary"]["case_count"], 0)

    def test_read_rows_filters_markets_and_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            invalid = row("s1", "eq:72", "", 0.70, 1)
            write_rows(path, [
                row("s1", "eq:72", 0.12, 0.70, 1, market_id="seattle"),
                row("s2", "eq:72", 0.12, 0.70, 1, market_id="nyc"),
                invalid,
            ])

            rows = read_rows([path], markets={"seattle"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_id"], "seattle")

    def test_write_markdown_report_outputs_case_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path, [
                row("s1", "eq:70", 0.30, 0.10, 0, bin_value="70"),
                row("s1", "eq:72", 0.12, 0.70, 1, bin_value="72"),
            ])
            payload = build_payload([rows_path], markets=["seattle"])

            write_markdown_report(report_path, payload)

            text = report_path.read_text(encoding="utf-8")
        self.assertIn("Winner Underpricing Casebook", text)
        self.assertIn("Dominant Patterns", text)
        self.assertIn("forecast_bucket_pressure", text)
        self.assertIn("eq:72", text)


if __name__ == "__main__":
    unittest.main()
