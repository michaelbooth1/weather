import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from data_layer_audit import (  # noqa: E402
    build_recommendations,
    scan_snapshot_csv,
    season_dates,
)


class TestDataLayerAudit(unittest.TestCase):
    def test_season_dates_respects_requested_bounds(self):
        days = season_dates(date(2025, 6, 29), date(2026, 5, 21))

        self.assertEqual(days[0], date(2025, 6, 29))
        self.assertEqual(days[-1], date(2026, 5, 21))
        self.assertIn(date(2025, 6, 30), days)
        self.assertIn(date(2026, 5, 20), days)
        self.assertNotIn(date(2026, 5, 19), days)

    def test_scan_snapshot_csv_counts_fill_and_missing_token_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshots_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["snapshot_id", "market_yes", "best_bid", "clob_token_id"],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "market_yes": "0.4",
                    "best_bid": "",
                    "clob_token_id": "",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "market_yes": "0.6",
                    "best_bid": "0.5",
                    "clob_token_id": "123",
                })

            scanned = scan_snapshot_csv(path)

        self.assertEqual(scanned["row_count"], 2)
        self.assertEqual(scanned["nonempty"]["best_bid"], 1)
        self.assertEqual(scanned["rows_with_market_token_ids"], 1)

    def test_recommendations_prioritize_microstructure_and_cadence(self):
        recs = build_recommendations(
            {
                "has_market_token_ids": False,
                "low_fill_fields": [{"field": "best_bid", "fill_rate": 0.45}],
                "artifact_day_counts": {"replay_inputs": 2},
                "folder_count": 3,
            },
            {
                "markets": [
                    {
                        "market_id": "nyc",
                        "sources": {
                            "metar": {
                                "target_season": {
                                    "coverage_rate": 0.5,
                                    "covered_days": 1,
                                    "expected_days": 2,
                                },
                            },
                        },
                    },
                ],
            },
            {"configured_interval_minutes": 10},
        )

        titles = [item["title"] for item in recs]
        self.assertIn("Persist CLOB token IDs and full order-book snapshots", titles)
        self.assertIn("Split weather/model cadence from market-book cadence", titles)
        self.assertIn("Deep-fill redundant historical weather sources for the target season", titles)

    def test_recommendations_respect_managed_clob_loop(self):
        base_snapshot = {
            "has_market_token_ids": True,
            "low_fill_fields": [],
            "artifact_day_counts": {"replay_inputs": 2},
            "folder_count": 3,
        }
        historical = {"markets": []}
        loop = {"configured_interval_minutes": 10}

        running = build_recommendations(
            base_snapshot,
            historical,
            loop,
            {"state": "RUNNING", "status_path": "data/snapshots/clob_loop_status.json"},
        )
        dead = build_recommendations(
            base_snapshot,
            historical,
            loop,
            {"state": "DEAD", "status_path": "data/snapshots/clob_loop_status.json"},
        )

        running_titles = [item["title"] for item in running]
        dead_titles = [item["title"] for item in dead]
        self.assertNotIn("Split weather/model cadence from market-book cadence", running_titles)
        self.assertIn("Start and supervise the CLOB book loop", dead_titles)


if __name__ == "__main__":
    unittest.main()
