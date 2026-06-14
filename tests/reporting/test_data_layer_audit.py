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
    build_gates,
    scan_snapshot_csv,
    source_status_summary_for_folder,
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

    def test_source_status_summary_counts_stale_and_failed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_status_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source", "ok", "stale", "status"])
                writer.writeheader()
                writer.writerow({"source": "wu_current", "ok": "True", "stale": "False", "status": "fresh"})
                writer.writerow({"source": "open_meteo", "ok": "True", "stale": "True", "status": "stale_cache"})
                writer.writerow({"source": "metar", "ok": "False", "stale": "False", "status": "failed"})

            summary = source_status_summary_for_folder(tmp)

        self.assertEqual(summary["row_count"], 3)
        self.assertEqual(summary["source_count"], 3)
        self.assertEqual(summary["stale_or_failed_rows"], 2)
        self.assertEqual(summary["status_counts"]["fresh"], 1)

    def test_build_gates_fails_missing_required_artifacts_and_warns_stale_sources(self):
        snapshot = {
            "folder_count": 2,
            "artifact_day_counts": {
                "replay_inputs": 2,
                "source_status": 1,
                "forecasts": 2,
                "forecast_payloads": 1,
            },
            "low_fill_fields": [{"field": "best_bid", "fill_rate": 0.4}],
            "source_status": {
                "row_count": 10,
                "stale_or_failed_rows": 2,
                "stale_or_failed_rate": 0.2,
            },
        }
        historical = {
            "markets": [
                {
                    "sources": {
                        "reanalysis": {"archive_coverage": {"raw_only_day_count": 1}},
                        "wu": {"quality": {"quarantined_raw_observations": 1}},
                    },
                },
            ],
        }

        gates = build_gates(snapshot, historical)
        by_name = {row["name"]: row for row in gates}

        self.assertEqual(by_name["snapshot_artifact_replay_input_status"]["status"], "FAIL")
        self.assertEqual(by_name["snapshot_artifact_source_status"]["status"], "WARN")
        self.assertEqual(by_name["forecast_payload_artifact_rate"]["status"], "WARN")
        self.assertEqual(by_name["source_status_stale_or_failed_rate"]["status"], "WARN")
        self.assertEqual(by_name["reanalysis_raw_only_days"]["status"], "WARN")


if __name__ == "__main__":
    unittest.main()
