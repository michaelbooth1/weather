import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.forecast_smoke_slice_prep import (
    SCHEMA_VERSION,
    build_payload,
    daily_smoke_slice_rows,
    write_report,
)


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ForecastSmokeSlicePrepTests(unittest.TestCase):
    def test_daily_rows_label_high_aod_high_pm_slice(self):
        rows = daily_smoke_slice_rows(
            [
                {
                    "market_id": "nyc",
                    "target_date": "2026-06-18",
                    "station": "KLGA",
                    "pm2_5": "36.0",
                    "pm10": "60.0",
                    "aerosol_optical_depth": "0.45",
                    "dust": "7.0",
                },
                {
                    "market_id": "nyc",
                    "target_date": "2026-06-18",
                    "station": "KLGA",
                    "pm2_5": "20.0",
                    "pm10": "30.0",
                    "aerosol_optical_depth": "0.20",
                    "dust": "3.0",
                },
                {
                    "market_id": "nyc",
                    "target_date": "2026-06-19",
                    "station": "KLGA",
                    "pm2_5": "10.0",
                    "pm10": "20.0",
                    "aerosol_optical_depth": "0.10",
                    "dust": "2.0",
                },
            ]
        )

        by_date = {row["target_date"]: row for row in rows}
        self.assertEqual(by_date["2026-06-18"]["smoke_slice"], "high_aod_high_pm")
        self.assertTrue(by_date["2026-06-18"]["high_smoke_flag"])
        self.assertEqual(by_date["2026-06-19"]["smoke_slice"], "normal")

    def test_build_payload_reads_archive_rows_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_root = root / "open_meteo_archives"
            report_path = root / "report.md"
            write_csv(
                archive_root / "klga" / "air_quality" / "hourly.csv",
                [
                    {
                        "schema_version": "open_meteo_air_quality_archive_v0.1",
                        "market": "nyc",
                        "station": "KLGA",
                        "source": "open_meteo_air_quality",
                        "target_date": "2026-06-18",
                        "valid_time": "2026-06-18T14:00:00-04:00",
                        "minute_of_day": "840",
                        "pm2_5": "36.0",
                        "pm10": "60.0",
                        "aerosol_optical_depth": "0.45",
                        "dust": "7.0",
                        "us_aqi": "105",
                        "european_aqi": "63",
                        "payload_hash": "abc",
                        "fetched_at": "2026-06-18T12:00:00+00:00",
                    }
                ],
            )

            payload = build_payload(
                archive_root=archive_root,
                markets="nyc",
                generated_at_utc="2026-06-18T20:00:00+00:00",
            )
            write_report(report_path, payload)
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["summary"]["high_aod_high_pm_day_count"], 1)
        self.assertEqual(payload["summary"]["candidate_slice_rows"][1]["group"], "high_aod_high_pm")
        self.assertIn("Forecast Smoke Slice Prep", report_text)


if __name__ == "__main__":
    unittest.main()
