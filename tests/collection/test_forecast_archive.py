import csv
import json
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
                        "provider_update_time": "2026-05-27T09:50:00-04:00",
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
            self.assertEqual(rows[0]["issue_time"], "2026-05-27T09:50:00-04:00")
            self.assertEqual(rows[0]["issue_time_basis"], "source_provider_time")
            self.assertEqual(rows[0]["provider_update_time"], "2026-05-27T09:50:00-04:00")
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

    def test_build_forecast_rows_persists_radiation_cloud_layers_and_ensemble_spread(self):
        captured_at = datetime(2026, 5, 27, 12, 0, tzinfo=TORONTO_TZ)
        sources = {
            "open_meteo": {
                "ok": True,
                "data": {
                    "url": "om-url",
                    "rows": [
                        {
                            "valid_time": "2026-05-27T13:00:00-04:00",
                            "temp_c": 24,
                            "cloud_cover": 50,
                            "low_cloud": 10,
                            "mid_cloud": 20,
                            "high_cloud": 30,
                            "wind_kmh": 14,
                            "solar": 800,
                        }
                    ],
                },
            },
            "global_ensemble": {
                "ok": True,
                "data": {
                    "url": "ens-url",
                    "day_mean_member_spread": 3.5,
                    "day_member_high_p10": 22,
                    "day_member_high_p90": 27,
                    "rows": [
                        {
                            "valid_time": "2026-05-27T13:00:00-04:00",
                            "temp_c": 24,
                            "ensemble_member_spread": 4.0,
                            "ensemble_member_p10": 22.0,
                            "ensemble_member_p90": 26.0,
                        }
                    ],
                },
            },
        }

        rows = build_forecast_rows(
            sources,
            FakeModelClient(),
            captured_at,
            "s1",
            "event",
        )

        open_meteo = [row for row in rows if row["source"] == "open_meteo"][0]
        ensemble = [row for row in rows if row["source"] == "global_ensemble"][0]
        self.assertEqual(open_meteo["shortwave_radiation"], 800)
        self.assertEqual(open_meteo["low_cloud"], 10)
        self.assertEqual(ensemble["ensemble_member_spread"], 4.0)
        self.assertEqual(ensemble["ensemble_day_mean_spread"], 3.5)
        self.assertEqual(ensemble["ensemble_day_high_p90"], 27)

    def test_build_forecast_rows_prefers_native_source_aliases(self):
        captured_at = datetime(2026, 5, 27, 12, 0, tzinfo=TORONTO_TZ)
        sources = {
            "weather_forecast": {
                "ok": True,
                "data": {
                    "rows": [{
                        "valid_time": "2026-05-27T13:00:00-04:00",
                        "temp_native": 84,
                        "temp_c": 28.9,
                    }],
                },
            },
            "open_meteo": {
                "ok": True,
                "data": {
                    "rows": [{
                        "valid_time": "2026-05-27T14:00:00-04:00",
                        "temp_native": 86,
                        "temp_c": 30.0,
                    }],
                },
            },
            "nws_hourly": {
                "ok": True,
                "data": {
                    "rows": [{
                        "valid_time": "2026-05-27T15:00:00-04:00",
                        "temp_native": 88,
                        "temp_c": 31.1,
                    }],
                },
            },
            "global_ensemble": {
                "ok": True,
                "data": {
                    "rows": [{
                        "valid_time": "2026-05-27T16:00:00-04:00",
                        "temp_native": 90,
                        "temp_c": 32.2,
                    }],
                },
            },
            "eccc_citypage": {
                "ok": True,
                "data": {
                    "forecast_high_native": 91,
                    "forecast_high_c": 33,
                },
            },
        }

        rows = build_forecast_rows(
            sources,
            FakeModelClient(),
            captured_at,
            "s1",
            "event",
        )

        by_source = {row["source"]: row for row in rows}
        self.assertEqual(by_source["weather_forecast"]["target_temp_c"], 84)
        self.assertEqual(by_source["open_meteo"]["target_temp_c"], 86)
        self.assertEqual(by_source["nws_hourly"]["target_temp_c"], 88)
        self.assertEqual(by_source["global_ensemble"]["target_temp_c"], 90)
        self.assertEqual(by_source["eccc_citypage"]["forecast_high_c"], 91)
        self.assertEqual(by_source["eccc_citypage"]["target_temp_c"], 91)

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
                        "wu_history_high_native",
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
                        "wu_history_high_native": "27",
                        "wu_history_high_c": "25",
                    }
                )

            count = backfill_eccc_from_snapshots(folder)
            result = analyze_forecast_archive(folder, data_root=Path(tmp) / "missing")

            self.assertEqual(count, 1)
            self.assertEqual(result["scored_rows"], 1)
            scored = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))["scored_rows"]
            self.assertEqual(scored[0]["final_high_c"], 27.0)
            self.assertTrue((folder / "forecast_bias_report.md").exists())


if __name__ == "__main__":
    unittest.main()
