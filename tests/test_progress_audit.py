import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from progress_audit import (  # noqa: E402
    classify_trend,
    load_market_day_labels,
    parse_backtest_report,
    parse_roadmap_baselines,
)


class TestProgressAudit(unittest.TestCase):
    def test_parse_backtest_report_extracts_headline_and_day_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest_report.md"
            path.write_text(
                "\n".join([
                    "# Settlement-Scored Backtest",
                    "",
                    "Generated: 2026-06-09 08:46",
                    "",
                    "Market days: 4  |  Total band-rows scored: 4763",
                    "",
                    "| Metric | Value |",
                    "| :--- | :--- |",
                    "| All-snapshot Brier skill vs market | -0.336 |",
                    "| Daily-first Brier skill vs market | -0.347 |",
                    "| All-snapshot log-loss delta (market - model) | -0.0503 |",
                    "",
                    "## Feature Vector Coverage",
                    "",
                    "| Rows | Rows with features | Coverage | Feature schemas |",
                    "| :--- | :--- | :--- | :--- |",
                    "| 4763 | 4059 | 85.2% | toronto_feature_store_v0.1 |",
                    "",
                    "## Score Summary",
                    "",
                    "| Scope | Days | Rows | Model Brier | Market Brier | Brier Delta | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                    "| All snapshots | - | 4763 | 0.0536 | 0.0401 | -0.0135 | -0.336 | 0.1748 | 0.1245 | -0.0503 | 9.1% |",
                    "| Daily-first equal-day average | 4 | 4763 | 0.0531 | 0.0394 | -0.0137 | -0.347 | 0.1733 | 0.1226 | -0.0507 | 9.1% |",
                    "",
                    "## Model Vs Market By Target Day",
                    "",
                    "| Date | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                    "| 2026-06-07 | 1540 | 0.0506 | 0.0536 | +0.055 | 0.1592 | 0.1586 | -0.0006 | 9.1% |",
                ]),
                encoding="utf-8",
            )

            parsed = parse_backtest_report(path)

        self.assertEqual(parsed["market_days"], 4)
        self.assertEqual(parsed["band_rows"], 4763)
        self.assertAlmostEqual(parsed["all_snapshot_brier_skill_vs_market"], -0.336)
        self.assertAlmostEqual(parsed["model_brier"], 0.0536)
        self.assertAlmostEqual(parsed["market_brier"], 0.0401)
        self.assertAlmostEqual(parsed["feature_coverage"]["coverage_rate"], 0.852)
        self.assertEqual(parsed["by_day"][0]["date"], "2026-06-07")
        self.assertAlmostEqual(parsed["by_day"][0]["brier_skill"], 0.055)

    def test_parse_roadmap_baselines_extracts_initial_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ROADMAP.md"
            path.write_text(
                "\n".join([
                    "The strict headline report therefore scores 1 clean market day and 704 band rows.",
                    "The uncalibrated model Brier was 0.0583 versus market Brier 0.0394,",
                    "for a Brier skill score of -0.478.",
                    "over 3 settled-looking market days and 1760 band rows. All-snapshot Brier skill was -1.500;",
                    "Brier improved from 0.0954 to 0.0775, log loss improved from 0.3705 to 0.2743,",
                    "and Brier skill versus Polymarket improved from -1.500 to -1.031.",
                ]),
                encoding="utf-8",
            )

            parsed = parse_roadmap_baselines(path)

        self.assertEqual(parsed["initial_strict_toronto"]["band_rows"], 704)
        self.assertAlmostEqual(parsed["initial_strict_toronto"]["model_brier"], 0.0583)
        self.assertAlmostEqual(parsed["initial_strict_toronto"]["brier_skill"], -0.478)
        self.assertAlmostEqual(parsed["pre_label_three_day"]["brier_skill"], -1.5)
        self.assertAlmostEqual(parsed["calibration_pre_label"]["skill_after"], -1.031)

    def test_load_market_day_labels_counts_quality_and_markets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market_day_labels.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["market_id", "target_date", "quality_grade"])
                writer.writeheader()
                writer.writerow({"market_id": "toronto", "target_date": "2026-06-01", "quality_grade": "complete"})
                writer.writerow({"market_id": "toronto", "target_date": "2026-06-02", "quality_grade": "partial"})
                writer.writerow({"market_id": "nyc", "target_date": "2026-06-02", "quality_grade": "complete"})

            parsed = load_market_day_labels(path)

        self.assertEqual(parsed["rows"], 3)
        self.assertEqual(parsed["quality_counts"]["complete"], 2)
        self.assertEqual(parsed["complete_by_market"]["toronto"], 1)
        self.assertEqual(parsed["target_date_count"], 2)

    def test_classify_trend_requires_positive_skill_for_market_beating(self):
        payload = {
            "roadmap_baselines": {
                "initial_strict_toronto": {
                    "brier_skill": -0.478,
                    "model_brier": 0.0583,
                }
            },
            "current_backtest": {
                "all_snapshot_brier_skill_vs_market": -0.336,
                "model_brier": 0.0536,
            },
            "pooled_candidate_series": [
                {"verdict": "BLOCK", "candidate_brier": 0.1370},
                {"verdict": "SHADOW_ONLY", "candidate_brier": 0.0515},
            ],
            "promotion_refresh": {
                "candidate_cutover_decision": "DO_NOT_CUT_OVER",
                "serving_gauntlet_verdict": "BLOCK",
            },
            "loop_statuses": {
                "snapshot_loop": {"state": "RUNNING"},
                "clob_loop": {"state": "RUNNING"},
            },
        }

        trend = classify_trend(payload)

        self.assertAlmostEqual(trend["model_skill_gain_vs_initial_strict"], 0.142)
        self.assertLess(trend["model_brier_delta_vs_initial_strict"], 0)
        self.assertTrue(trend["candidate_gate_improved"])
        self.assertFalse(trend["model_beats_market_on_current_headline"])
        self.assertTrue(trend["operational_capture_running"])


if __name__ == "__main__":
    unittest.main()
