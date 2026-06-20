import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.blocked_market_repair_diagnostics import (
    build_payload,
    classify_market,
    market_diagnostics,
    read_variant_rows,
    slice_diagnostics,
    write_markdown_report,
    winner_summary,
)


FIELDNAMES = [
    "variant_id",
    "variant_family",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "cutoff_hour",
    "cutoff_regime",
    "bin_type",
    "settlement_distance_bucket",
    "source_freshness_state",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
]


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def row(market, date, idx, probability, current, market_yes, outcome, **extra):
    data = {
        "variant_id": "candidate",
        "variant_family": "repair",
        "market_id": market,
        "target_date": date,
        "snapshot_id": f"{market}-{date}-{idx}",
        "band_key": f"eq:{idx}",
        "probability": probability,
        "current_probability": current,
        "recorded_probability": current,
        "market_yes": market_yes,
        "outcome": outcome,
        "cutoff_hour": extra.get("cutoff_hour", "7"),
        "cutoff_regime": extra.get("cutoff_regime", "early"),
        "bin_type": extra.get("bin_type", "eq"),
        "settlement_distance_bucket": extra.get("settlement_distance_bucket", "0"),
        "source_freshness_state": extra.get("source_freshness_state", "all_fresh"),
        "forecast_disagreement_bucket": extra.get("forecast_disagreement_bucket", "low"),
        "forecast_bucket_pressure": extra.get("forecast_bucket_pressure", "center"),
    }
    return {key: str(value) for key, value in data.items()}


class BlockedMarketRepairDiagnosticsTests(unittest.TestCase):
    def test_classifies_current_fallback_market(self):
        rows = [
            row("fallback", "2026-06-01", 1, 0.20, 0.20, 0.85, 1),
            row("fallback", "2026-06-01", 2, 0.80, 0.80, 0.15, 0),
        ]

        self.assertEqual(classify_market(rows), "current_fallback_trails_market")

    def test_winner_summary_detects_market_underpricing(self):
        rows = [
            row("underpriced", "2026-06-01", 1, 0.25, 0.20, 0.90, 1),
            row("underpriced", "2026-06-01", 2, 0.50, 0.50, 0.10, 0),
        ]

        summary = winner_summary(rows)

        self.assertAlmostEqual(summary["variant_winner_probability"], 0.25)
        self.assertAlmostEqual(summary["market_winner_probability"], 0.90)
        self.assertLess(summary["variant_winner_gap_vs_market"], -0.60)
        self.assertEqual(classify_market(rows), "winner_underpricing_vs_market")

    def test_slice_diagnostics_ranks_weighted_market_gap(self):
        rows = [
            row("m", "2026-06-01", 1, 0.20, 0.20, 0.90, 1, cutoff_hour="7"),
            row("m", "2026-06-01", 2, 0.90, 0.90, 0.10, 0, cutoff_hour="7"),
            row("m", "2026-06-01", 3, 0.10, 0.10, 0.15, 0, cutoff_hour="12"),
        ]

        diagnostics = slice_diagnostics(rows, min_rows=1, limit=2)

        self.assertEqual(diagnostics[0]["slice"], "cutoff_hour")
        self.assertEqual(diagnostics[0]["group"], "7")
        self.assertGreater(diagnostics[0]["weighted_market_gap"], 0.0)

    def test_build_payload_reads_multiple_row_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.csv"
            second = Path(tmp) / "second.csv"
            write_rows(first, [
                row("fallback", "2026-06-01", 1, 0.20, 0.20, 0.85, 1),
                row("fallback", "2026-06-01", 2, 0.80, 0.80, 0.15, 0),
            ])
            write_rows(second, [
                row("underpriced", "2026-06-01", 1, 0.25, 0.20, 0.90, 1),
                row("underpriced", "2026-06-01", 2, 0.50, 0.50, 0.10, 0),
            ])

            payload = build_payload([first, second], min_slice_rows=1)

        self.assertEqual(payload["schema_version"], "blocked_market_repair_diagnostics_v0.1")
        self.assertEqual(payload["row_count"], 4)
        self.assertIn("fallback", payload["summary"]["current_fallback_markets"])
        self.assertIn("underpriced", payload["summary"]["winner_underpricing_markets"])
        self.assertEqual(
            payload["summary"]["primary_repair_actions"]["fallback"],
            "add_non_current_market_signal",
        )
        self.assertEqual(
            payload["summary"]["primary_repair_actions"]["underpriced"],
            "repair_winner_probability_mass",
        )

    def test_market_diagnostics_flags_current_regression_guard(self):
        rows = [
            row("regressor", "2026-06-01", 1, 0.80, 0.20, 0.20, 0),
            row("regressor", "2026-06-01", 2, 0.20, 0.20, 0.20, 0),
        ]

        [market] = market_diagnostics(rows, min_slice_rows=1)

        self.assertTrue(market["candidate_regresses_current"])
        self.assertEqual(market["primary_repair_action"], "add_current_regression_guard")
        self.assertEqual(market["repair_actions"][0]["priority"], "P0")

    def test_read_variant_rows_skips_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.csv"
            valid = row("m", "2026-06-01", 1, 0.20, 0.20, 0.90, 1)
            invalid = dict(valid)
            invalid["probability"] = ""
            write_rows(path, [valid, invalid])

            rows = read_variant_rows([path])

        self.assertEqual(len(rows), 1)

    def test_write_markdown_report_outputs_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path, [
                row("fallback", "2026-06-01", 1, 0.20, 0.20, 0.85, 1),
                row("fallback", "2026-06-01", 2, 0.80, 0.80, 0.15, 0),
            ])
            payload = build_payload([rows_path], min_slice_rows=1)

            write_markdown_report(report_path, payload)

            text = report_path.read_text(encoding="utf-8")
        self.assertIn("Blocked Market Repair Diagnostics", text)
        self.assertIn("current_fallback_trails_market", text)
        self.assertIn("Recommended repairs", text)
        self.assertIn("add_non_current_market_signal", text)


if __name__ == "__main__":
    unittest.main()
