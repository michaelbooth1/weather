import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.market_anchor_validation import (
    anchored_probability,
    build_payload,
    clob_anchor_train_coverage_gate,
    clob_stability_summary,
    score_rows,
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
    "clob_midpoint",
    "clob_spread",
    "clob_liquidity_score",
]


def row(day, snapshot, probability, current, market, outcome, clob="", spread="", liquidity=""):
    return {
        "market_id": "nyc",
        "target_date": day,
        "snapshot_id": snapshot,
        "band_key": snapshot,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market),
        "outcome": str(outcome),
        "clob_midpoint": str(clob),
        "clob_spread": str(spread),
        "clob_liquidity_score": str(liquidity),
    }


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class MarketAnchorValidationTests(unittest.TestCase):
    def test_anchored_probability_blends_available_clob_midpoint(self):
        source = {
            "probability": 0.20,
            "market_probability": 0.80,
            "clob_midpoint": 0.60,
            "clob_spread": 0.02,
            "clob_liquidity_score": 0.70,
        }

        probability, used = anchored_probability(source, "clob_midpoint", 0.50, max_clob_spread=0.05)

        self.assertTrue(used)
        self.assertAlmostEqual(probability, 0.40)

    def test_anchored_probability_falls_back_when_clob_filtered(self):
        source = {
            "probability": 0.20,
            "market_probability": 0.80,
            "clob_midpoint": 0.60,
            "clob_spread": 0.20,
            "clob_liquidity_score": 0.70,
        }

        probability, used = anchored_probability(source, "clob_midpoint", 1.0, max_clob_spread=0.05)

        self.assertFalse(used)
        self.assertAlmostEqual(probability, 0.20)

    def test_score_rows_reports_anchor_coverage(self):
        rows = [
            {
                "probability": 0.20,
                "current_probability": 0.20,
                "market_probability": 0.80,
                "clob_midpoint": 0.80,
                "outcome": 1,
            },
            {
                "probability": 0.40,
                "current_probability": 0.40,
                "market_probability": 0.30,
                "clob_midpoint": None,
                "outcome": 0,
            },
        ]

        score = score_rows(rows, "clob_midpoint", 1.0)

        self.assertAlmostEqual(score["anchor_coverage"], 0.5)
        self.assertLess(score["candidate_brier"], score["current_brier"])

    def test_clob_stability_summary_reports_train_eval_quality_inputs(self):
        rows = [
            {
                "probability": 0.20,
                "current_probability": 0.20,
                "market_probability": 0.80,
                "clob_midpoint": 0.80,
                "clob_spread": 0.02,
                "clob_liquidity_score": 0.70,
                "outcome": 1,
            },
            {
                "probability": 0.40,
                "current_probability": 0.40,
                "market_probability": 0.30,
                "clob_midpoint": None,
                "clob_spread": None,
                "clob_liquidity_score": None,
                "outcome": 0,
            },
        ]

        summary = clob_stability_summary(rows)

        self.assertEqual(summary["anchor_rows"], 1)
        self.assertAlmostEqual(summary["anchor_coverage"], 0.5)
        self.assertLess(summary["clob_brier"], summary["candidate_brier"])
        self.assertAlmostEqual(summary["spread_p90"], 0.02)
        self.assertAlmostEqual(summary["liquidity_p10"], 0.70)

    def test_clob_anchor_train_coverage_gate_blocks_when_source_requested_without_train_anchor(self):
        gate = clob_anchor_train_coverage_gate(
            {"anchor_coverage": 0.0, "anchor_rows": 0},
            ["candidate", "clob_midpoint"],
            min_train_coverage=0.05,
        )

        self.assertEqual(gate["status"], "BLOCK")
        self.assertIn("below selector threshold", gate["reason"])

    def test_clob_anchor_train_coverage_gate_not_applicable_without_clob_source(self):
        gate = clob_anchor_train_coverage_gate(
            {"anchor_coverage": 0.0, "anchor_rows": 0},
            ["candidate", "market_yes"],
            min_train_coverage=0.05,
        )

        self.assertEqual(gate["status"], "NOT_APPLICABLE")

    def test_build_payload_selects_on_earlier_dates_and_reports_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path, [
                row("2026-06-01", "s1", 0.20, 0.20, 0.80, 1, clob=0.80, spread=0.01),
                row("2026-06-01", "s2", 0.70, 0.70, 0.20, 0, clob=0.20, spread=0.01),
                row("2026-06-02", "s3", 0.25, 0.25, 0.75, 1, clob=0.75, spread=0.01),
                row("2026-06-02", "s4", 0.65, 0.65, 0.15, 0, clob=0.15, spread=0.01),
            ])

            payload = build_payload(
                [rows_path],
                sources_csv="candidate,clob_midpoint",
                alpha_grid="0,0.5,1",
            )
            write_markdown_report(report_path, payload)
            report_text = report_path.read_text(encoding="utf-8")

        result = payload["market_results"][0]
        self.assertEqual(result["train_dates"], ["2026-06-01"])
        self.assertEqual(result["eval_dates"], ["2026-06-02"])
        self.assertEqual(result["selected_source"], "clob_midpoint")
        self.assertEqual(payload["no_leakage_audit"]["status"], "PASS")
        self.assertIn("not promotion evidence", report_text)
        self.assertIn("CLOB Stability", report_text)
        self.assertIn("oracle_eval", payload)
        self.assertIn("clob_stability", payload["market_results"][0])
        self.assertEqual(payload["clob_anchor_train_coverage_gate"]["status"], "PASS")

    def test_build_payload_blocks_clob_anchor_when_train_side_midpoint_coverage_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            write_rows(rows_path, [
                row("2026-06-01", "s1", 0.80, 0.80, 0.20, 0),
                row("2026-06-01", "s2", 0.20, 0.20, 0.80, 1),
                row("2026-06-02", "s3", 0.25, 0.25, 0.75, 1, clob=0.75, spread=0.01),
                row("2026-06-02", "s4", 0.65, 0.65, 0.15, 0, clob=0.15, spread=0.01),
            ])

            payload = build_payload(
                [rows_path],
                sources_csv="candidate,clob_midpoint",
                alpha_grid="0,1",
                min_train_clob_anchor_coverage=0.05,
            )

        self.assertEqual(payload["clob_anchor_train_coverage_gate"]["status"], "BLOCK")
        self.assertEqual(payload["readiness_status"], "BLOCK")
        self.assertTrue(
            any(blocker.get("blocker") == "clob_anchor_train_coverage" for blocker in payload["blockers"])
        )


if __name__ == "__main__":
    unittest.main()
