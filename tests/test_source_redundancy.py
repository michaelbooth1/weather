import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from source_redundancy import (  # noqa: E402
    build_payload,
    forecast_ensemble_features,
)


def write_daily(root, icao, rows):
    path = Path(root) / icao.lower() / "daily" / "daily_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp",
                "max_temp_bucket",
                "max_temp_times",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "schema_version": "historical_daily_native_v1",
                "temperature_unit": "C",
                "row_count": 24,
                **row,
            })


class TestSourceRedundancy(unittest.TestCase):
    def test_build_payload_fills_missing_wu_from_redundant_source_and_learns_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wu_root = root / "wu"
            ghcnh_root = root / "ghcnh"
            reanalysis_root = root / "reanalysis"
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()

            write_daily(wu_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 20.0, "max_temp_bucket": 20, "max_temp_times": "15:00"},
            ])
            write_daily(ghcnh_root, "cyyz", [
                {"local_date": "2026-06-01", "max_temp": 21.0, "max_temp_bucket": 21, "max_temp_times": "14:00"},
                {"local_date": "2026-06-02", "max_temp": 22.0, "max_temp_bucket": 22, "max_temp_times": "16:00"},
            ])
            write_daily(reanalysis_root, "cyyz", [
                {"local_date": "2026-06-02", "max_temp": 21.5, "max_temp_bucket": 22, "max_temp_times": "17:00"},
            ])

            payload = build_payload(
                market_ids=["toronto"],
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 2),
                source_roots={
                    "wu": wu_root,
                    "ghcnh": ghcnh_root,
                    "reanalysis": reanalysis_root,
                },
                snapshots_root=snapshots_root,
                disagreement_threshold=0.5,
            )

        market = payload["markets"]["toronto"]
        self.assertEqual(market["summary"]["filled_days"], 1)
        self.assertEqual(market["summary"]["disagreement_alert_days"], 1)
        filled = [row for row in market["daily_truth"] if row["fill_candidate"]]
        self.assertEqual(filled[0]["local_date"], "2026-06-02")
        self.assertEqual(filled[0]["selected_source"], "ghcnh")
        self.assertEqual(filled[0]["selected_bucket"], 22)
        self.assertAlmostEqual(market["source_bias_vs_wu"]["ghcnh"]["bias_source_minus_wu"], 1.0)
        self.assertAlmostEqual(market["source_bias_vs_wu"]["ghcnh"]["mean_peak_time_lead_minutes"], -60.0)
        commands = market["gap_fill"]["refetch_commands"]
        self.assertTrue(any(command["source"] == "wu" and command["start"] == "2026-06-02" for command in commands))

    def test_forecast_ensemble_features_extract_source_count_and_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-2-2026"
            folder.mkdir(parents=True)
            path = folder / "forecasts_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "event_slug",
                        "target_date",
                        "source",
                        "forecast_high_c",
                        "target_temp_c",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-06-02T09:00:00-04:00",
                    "event_slug": folder.name,
                    "target_date": "2026-06-02",
                    "source": "open_meteo",
                    "forecast_high_c": "",
                    "target_temp_c": 24.0,
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-06-02T09:00:00-04:00",
                    "event_slug": folder.name,
                    "target_date": "2026-06-02",
                    "source": "weather_forecast",
                    "forecast_high_c": "",
                    "target_temp_c": 26.0,
                })

            rows = forecast_ensemble_features(snapshots_root=root, market_ids=["toronto"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["forecast_source_count"], 2)
        self.assertEqual(rows[0]["ensemble_forecast_high"], 25.0)
        self.assertEqual(rows[0]["forecast_disagreement"], 2.0)


if __name__ == "__main__":
    unittest.main()
