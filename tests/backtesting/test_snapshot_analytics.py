import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.abspath("src"))

from snapshot_analytics import analyze_snapshot_folder, build_band_metrics, load_snapshot_frame


class TestSnapshotAnalytics(unittest.TestCase):
    def write_snapshot_csv(self, folder):
        path = Path(folder) / "snapshots_long.csv"
        columns = [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "event_updated_at",
            "model_version",
            "top_temp_c",
            "top_probability",
            "range_label",
            "bin_kind",
            "bin_value_c",
            "model_probability",
            "market_yes",
            "market_no",
            "edge",
            "best_bid",
            "best_ask",
            "last_trade_price",
            "volume",
            "liquidity",
            "market_status",
            "wu_history_high_c",
            "wu_current_c",
            "wu_max_since_7am_c",
            "eccc_swob_max_c",
            "weather_forecast_max_c",
            "open_meteo_max_c",
            "eccc_forecast_high_c",
        ]
        rows = []
        snapshots = [
            ("s1", "2026-05-27T14:00:00+00:00", "2026-05-27T10:00:00-04:00", 0.55, 0.40),
            ("s2", "2026-05-27T14:10:00+00:00", "2026-05-27T10:10:00-04:00", 0.60, 0.42),
            ("s3", "2026-05-27T14:20:00+00:00", "2026-05-27T10:20:00-04:00", 0.52, 0.50),
        ]
        for snapshot_id, utc_time, local_time, model_24, market_24 in snapshots:
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "captured_at_utc": utc_time,
                    "captured_at_local": local_time,
                    "event_slug": "test-event",
                    "event_updated_at": utc_time,
                    "model_version": "test",
                    "top_temp_c": 24,
                    "top_probability": model_24,
                    "range_label": "24 C",
                    "bin_kind": "eq",
                    "bin_value_c": 24,
                    "model_probability": model_24,
                    "market_yes": market_24,
                    "market_no": 1 - market_24,
                    "edge": model_24 - market_24,
                    "best_bid": market_24 - 0.01,
                    "best_ask": market_24 + 0.01,
                    "last_trade_price": market_24,
                    "volume": 100,
                    "liquidity": 1000,
                    "market_status": "active",
                    "wu_history_high_c": 24,
                    "wu_current_c": 23,
                    "wu_max_since_7am_c": 24,
                    "eccc_swob_max_c": 23.9,
                    "weather_forecast_max_c": 25,
                    "open_meteo_max_c": 25.2,
                    "eccc_forecast_high_c": 25,
                }
            )
            rows.append(
                {
                    **rows[-1],
                    "range_label": "25 C",
                    "bin_value_c": 25,
                    "model_probability": 1 - model_24,
                    "market_yes": 1 - market_24,
                    "market_no": market_24,
                    "edge": (1 - model_24) - (1 - market_24),
                }
            )

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_analyze_snapshot_folder_writes_ascii_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.write_snapshot_csv(folder)

            result = analyze_snapshot_folder(folder, edge_threshold=0.05, write_plots=False)

            self.assertEqual(result["snapshot_count"], 3)
            report = (folder / "analytics_report.md").read_text(encoding="utf-8")
            self.assertIn("## Detailed Design", report)
            self.assertIn("## Edge Episodes", report)
            self.assertIn("WU printed high", report)
            self.assertNotIn(chr(194), report)

    def test_band_metrics_track_threshold_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_snapshot_csv(tmp)
            df = load_snapshot_frame(path)

            metrics = build_band_metrics(df, edge_threshold=0.05)
            metric_24 = next(row for row in metrics if row["range_label"] == "24 C")

            self.assertEqual(metric_24["longest_threshold_run"]["count"], 2)
            self.assertEqual(metric_24["threshold_crossings"], 1)


if __name__ == "__main__":
    unittest.main()
