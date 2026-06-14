import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


sys.path.insert(0, os.path.abspath("src"))

from forecast_archive import (
    FORECAST_COLUMNS,
    analyze_forecast_archive,
    append_rows,
    backfill_eccc_from_snapshots,
    build_forecast_rows,
    migrate_csv_schema,
)
from toronto_model import TORONTO_TZ


class FakeModelClient:
    def source_data(self, sources, name):
        item = sources.get(name, {})
        return item.get("data", {}) if item.get("ok") else {}


class TestForecastArchive(unittest.TestCase):
    def test_build_forecast_rows_tracks_issue_valid_and_eccc_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "forecasts_long.csv"
            captured_at = datetime(2026, 5, 27, 10, 0, tzinfo=TORONTO_TZ)
            sources = {
                "weather_forecast": {
                    "ok": True,
                    "data": {
                        "url": "weather-url",
                        "rows": [
                            {
                                "valid_time": "2026-05-27T11:00:00-04:00",
                                "temp_c": 21,
                                "cloud_cover": 50,
                                "wind_kmh": 12,
                                "condition": "Cloudy",
                            }
                        ],
                    },
                },
                "open_meteo": {"ok": True, "data": {"url": "om-url", "rows": []}},
                "eccc_citypage": {
                    "ok": True,
                    "data": {
                        "url": "eccc-url",
                        "last_updated": "2026-05-27T09:45:00-04:00",
                        "forecast_high_c": 24,
                        "forecast_summary": "High 24.",
                        "forecast_cloud": "Sunny",
                        "forecast_wind": "West 20 km/h",
                    },
                },
            }

            rows = build_forecast_rows(
                sources,
                FakeModelClient(),
                captured_at,
                "s1",
                "event",
                archive_path=archive_path,
            )
            append_rows(archive_path, FORECAST_COLUMNS, rows)
            second_rows = build_forecast_rows(
                sources,
                FakeModelClient(),
                captured_at,
                "s2",
                "event",
                archive_path=archive_path,
            )

            self.assertEqual({row["source"] for row in rows}, {"weather_forecast", "eccc_citypage"})
            self.assertEqual(rows[0]["horizon_minutes"], 60)
            self.assertEqual(rows[1]["issue_time_basis"], "source_last_updated")
            self.assertEqual([row["source"] for row in second_rows], ["weather_forecast"])

    def test_migrate_old_schema_maps_temp_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecasts_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "source",
                        "valid_time",
                        "temp_c",
                        "cloud_cover",
                        "wind_speed_kmh",
                        "condition",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-05-27T14:00:00+00:00",
                        "captured_at_local": "2026-05-27T10:00:00-04:00",
                        "source": "weather_forecast",
                        "valid_time": "11:00",
                        "temp_c": "21",
                    }
                )

            migrate_csv_schema(path, FORECAST_COLUMNS)

            rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
            self.assertEqual(rows[0]["target_temp_c"], "21")
            self.assertEqual(rows[0]["forecast_kind"], "hourly")
            self.assertIn("payload_hash", rows[0])

    def test_backfill_and_analyze_forecast_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "event"
            folder.mkdir()
            snapshots_path = folder / "snapshots_long.csv"
            with snapshots_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "snapshot_id",
                        "captured_at_utc",
                        "captured_at_local",
                        "event_slug",
                        "range_label",
                        "eccc_forecast_high_c",
                        "wu_history_high_c",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-05-27T14:00:00+00:00",
                        "captured_at_local": "2026-05-27T10:00:00-04:00",
                        "event_slug": "event",
                        "range_label": "24 C",
                        "eccc_forecast_high_c": "24",
                        "wu_history_high_c": "25",
                    }
                )

            count = backfill_eccc_from_snapshots(folder)
            result = analyze_forecast_archive(folder, data_root=Path(tmp) / "missing")

            self.assertEqual(count, 1)
            self.assertEqual(result["scored_rows"], 1)
            self.assertTrue((folder / "forecast_bias_report.md").exists())


if __name__ == "__main__":
    unittest.main()
