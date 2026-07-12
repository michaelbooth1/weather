import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.scorecards.proper_scoring_reliability_scorecard import (
    build_scorecard,
    render_report,
    write_outputs,
)


def _write_rows(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestProperScoringReliabilityScorecard(unittest.TestCase):
    def test_scorecard_reports_lane_separated_proper_scores_and_rank_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "active_variant_shadow_long.csv"
            rows = [
                {
                    "lane": "weather_only",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "snapshot_id": "s1",
                    "band_key": "eq:84",
                    "bin_value": "84",
                    "probability": "0.95",
                    "market_yes": "0.90",
                    "outcome": "1",
                    "settlement_distance": "0",
                    "cutoff_hour": "9",
                    "source_freshness_state": "all_fresh",
                    "runtime_identity": "desktop",
                    "weak_slot_state": "normal",
                    "distribution_family": "bucket",
                    "served_probability": "0.94",
                    "validated_probability": "0.95",
                },
                {
                    "lane": "weather_only",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "snapshot_id": "s1",
                    "band_key": "eq:85",
                    "bin_value": "85",
                    "probability": "0.05",
                    "market_yes": "0.10",
                    "outcome": "0",
                    "settlement_distance": "1",
                    "cutoff_hour": "9",
                    "source_freshness_state": "all_fresh",
                    "runtime_identity": "desktop",
                    "weak_slot_state": "normal",
                    "distribution_family": "bucket",
                    "served_probability": "0.04",
                    "validated_probability": "0.05",
                },
            ]
            _write_rows(path, rows)

            payload = build_scorecard(active_shadow_long=path, generated_at_utc="2026-06-23T00:00:00+00:00")
            by_lane = {row["lane"]: row for row in payload["lanes"]}
            report = render_report(payload)
            json_out, report_out = write_outputs(payload, Path(tmp) / "scorecard.json", Path(tmp) / "scorecard.md")
            json_exists = json_out.exists()
            report_exists = report_out.exists()

        self.assertEqual(payload["schema_version"], "proper_scoring_reliability_scorecard_v0.1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["summary"]["scored_probability_row_count"], 4)
        self.assertIn("weather_only", by_lane)
        self.assertIn("market_only", by_lane)
        self.assertLess(by_lane["weather_only"]["brier"], by_lane["market_only"]["brier"])
        self.assertLess(by_lane["weather_only"]["log_loss"], by_lane["market_only"]["log_loss"])
        self.assertEqual(by_lane["weather_only"]["crps_status"], "PASS")
        self.assertEqual(by_lane["weather_only"]["top1_winner_hit_rate"], 1.0)
        self.assertEqual(payload["served_vs_validated_distribution_parity"]["status"], "PASS")
        self.assertIn("Literature Appendix", report)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)

    def test_scorecard_gracefully_skips_when_no_probability_rows_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.csv"

            payload = build_scorecard(active_shadow_long=path)

        self.assertEqual(payload["status"], "MISSING")
        self.assertEqual(payload["density_crps"]["status"], "SKIP")
        self.assertEqual(payload["served_vs_validated_distribution_parity"]["status"], "SKIP")

    def test_distribution_diagnostics_do_not_merge_variants_at_one_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "active_variant_shadow_long.csv"
            rows = []
            for variant_id, winner_probability in (("candidate_a", 0.8), ("candidate_b", 0.6)):
                rows.extend(
                    [
                        {
                            "lane": "weather_only",
                            "variant_id": variant_id,
                            "market_id": "atlanta",
                            "target_date": "2026-06-19",
                            "snapshot_id": "s1",
                            "band_key": "eq:84",
                            "bin_value": "84",
                            "probability": str(winner_probability),
                            "outcome": "1",
                        },
                        {
                            "lane": "weather_only",
                            "variant_id": variant_id,
                            "market_id": "atlanta",
                            "target_date": "2026-06-19",
                            "snapshot_id": "s1",
                            "band_key": "eq:85",
                            "bin_value": "85",
                            "probability": str(1.0 - winner_probability),
                            "outcome": "0",
                        },
                    ]
                )
            _write_rows(path, rows)

            payload = build_scorecard(active_shadow_long=path)

        weather = next(row for row in payload["lanes"] if row["lane"] == "weather_only")
        self.assertEqual(weather["distribution_group_count"], 2)
        self.assertEqual(weather["ranked_distribution_group_count"], 2)


if __name__ == "__main__":
    unittest.main()
