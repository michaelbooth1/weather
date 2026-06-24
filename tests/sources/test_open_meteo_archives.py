import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.market.market_registry import spec_for_id
from weather.sources.open_meteo_archives import (
    OpenMeteoArchiveStore,
    build_open_meteo_air_quality_archive_params,
    build_open_meteo_global_model_archive_params,
    normalize_open_meteo_air_quality_archive,
    normalize_open_meteo_global_model_archive,
)


class TestOpenMeteoArchives(unittest.TestCase):
    def test_global_model_archive_params_select_model_members(self):
        spec = spec_for_id("nyc")
        params = build_open_meteo_global_model_archive_params(spec, "2026-06-01", "2026-06-02")

        self.assertEqual(params["latitude"], spec.lat)
        self.assertEqual(params["start_date"], "2026-06-01")
        self.assertEqual(params["end_date"], "2026-06-02")
        self.assertEqual(params["hourly"], "temperature_2m")
        self.assertIn("ecmwf_ifs025", params["models"])
        self.assertIn("gfs_graphcast025", params["models"])

    def test_global_model_archive_normalizes_hourly_and_daily_rows(self):
        spec = spec_for_id("nyc")
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-01T13:00"],
                "temperature_2m_ecmwf_ifs025": [84.0, 86.0],
                "temperature_2m_ecmwf_aifs025": [85.0, 87.0],
                "temperature_2m_ncep_aigfs025": [83.0, 84.0],
                "temperature_2m_gfs_graphcast025": [88.0, 89.0],
            }
        }

        normalized = normalize_open_meteo_global_model_archive(
            payload,
            spec,
            fetched_at="2026-06-01T10:00:00+00:00",
        )

        self.assertEqual(normalized["schema_version"], "open_meteo_global_model_archive_v0.1")
        self.assertEqual(len(normalized["hourly_rows"]), 2)
        self.assertEqual(len(normalized["daily_rows"]), 1)
        first = normalized["hourly_rows"][0]
        daily = normalized["daily_rows"][0]
        self.assertEqual(first["market"], "nyc")
        self.assertEqual(first["ecmwf_ifs025_temp_native"], 84.0)
        self.assertEqual(first["model_temp_spread"], 5.0)
        self.assertEqual(daily["ecmwf_aifs025_high_native"], 87.0)
        self.assertEqual(daily["gfs_graphcast025_high_native"], 89.0)
        self.assertEqual(daily["day_max_native"], 86.5)
        self.assertEqual(daily["day_high_spread"], 5.0)

    def test_air_quality_archive_params_and_rows(self):
        spec = spec_for_id("toronto")
        params = build_open_meteo_air_quality_archive_params(spec, "2026-06-01", "2026-06-01")
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-01T13:00"],
                "pm2_5": [12.0, 36.0],
                "pm10": [18.0, 55.0],
                "aerosol_optical_depth": [0.14, 0.42],
                "dust": [2.0, 7.0],
                "us_aqi": [44, 105],
                "european_aqi": [20, 63],
            }
        }

        normalized = normalize_open_meteo_air_quality_archive(
            payload,
            spec,
            fetched_at="2026-06-01T10:00:00+00:00",
        )

        self.assertEqual(params["hourly"], "pm2_5,pm10,aerosol_optical_depth,dust,us_aqi,european_aqi")
        self.assertEqual(params["timezone"], "America/Toronto")
        self.assertEqual(normalized["schema_version"], "open_meteo_air_quality_archive_v0.1")
        self.assertEqual(len(normalized["hourly_rows"]), 2)
        self.assertEqual(normalized["hourly_rows"][1]["pm2_5"], 36.0)
        self.assertEqual(normalized["hourly_rows"][1]["aerosol_optical_depth"], 0.42)
        self.assertEqual(normalized["hourly_rows"][1]["us_aqi"], 105.0)

    def test_archive_store_writes_normalized_csvs_and_raw_payloads(self):
        spec = spec_for_id("nyc")
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m_ecmwf_ifs025": [84.0],
                "temperature_2m_ecmwf_aifs025": [85.0],
                "temperature_2m_ncep_aigfs025": [83.0],
                "temperature_2m_gfs_graphcast025": [88.0],
            }
        }
        normalized = normalize_open_meteo_global_model_archive(payload, spec)

        with tempfile.TemporaryDirectory() as tmp:
            store = OpenMeteoArchiveStore(tmp)
            result = store.write_global_model_archive(normalized, spec)
            hourly_rows = list(csv.DictReader(Path(result["hourly_path"]).open(encoding="utf-8", newline="")))
            daily_rows = list(csv.DictReader(Path(result["daily_path"]).open(encoding="utf-8", newline="")))
            raw_payload = json.loads(Path(result["raw_payload_path"]).read_text(encoding="utf-8"))

        self.assertEqual(result["hourly_rows"], 1)
        self.assertEqual(result["daily_rows"], 1)
        self.assertEqual(hourly_rows[0]["source"], "open_meteo_global_models")
        self.assertEqual(daily_rows[0]["day_high_spread"], "5.0")
        self.assertIn("hourly", raw_payload)

    def test_global_model_store_merges_chunks_and_reports_coverage(self):
        spec = spec_for_id("nyc")
        first_payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m_ecmwf_ifs025": [84.0],
                "temperature_2m_ecmwf_aifs025": [85.0],
                "temperature_2m_ncep_aigfs025": [83.0],
                "temperature_2m_gfs_graphcast025": [88.0],
            }
        }
        second_payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "temperature_2m_ecmwf_ifs025": [86.0, 80.0],
                "temperature_2m_ecmwf_aifs025": [87.0, 81.0],
                "temperature_2m_ncep_aigfs025": [84.0, 79.0],
                "temperature_2m_gfs_graphcast025": [89.0, 82.0],
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = OpenMeteoArchiveStore(tmp)
            store.write_global_model_archive(normalize_open_meteo_global_model_archive(first_payload, spec), spec)
            result = store.write_global_model_archive(normalize_open_meteo_global_model_archive(second_payload, spec), spec)
            hourly_rows = list(csv.DictReader(Path(result["hourly_path"]).open(encoding="utf-8", newline="")))
            daily_rows = list(csv.DictReader(Path(result["daily_path"]).open(encoding="utf-8", newline="")))
            coverage = store.global_model_coverage(spec, "2026-06-01", "2026-06-03")
            missing = store.global_model_missing_ranges(spec, "2026-06-01", "2026-06-03", chunk_days=2)

        self.assertEqual(result["hourly_rows"], 2)
        self.assertEqual(result["daily_rows"], 2)
        self.assertEqual(len(hourly_rows), 2)
        self.assertEqual(len(daily_rows), 2)
        self.assertEqual(hourly_rows[0]["ecmwf_ifs025_temp_native"], "86.0")
        self.assertEqual(daily_rows[0]["day_max_native"], "86.5")
        self.assertEqual(coverage["covered_days"], 2)
        self.assertEqual(missing[0][0].isoformat(), "2026-06-03")

    def test_air_quality_store_merges_chunks_and_reports_coverage(self):
        spec = spec_for_id("nyc")
        first_payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "pm2_5": [36.0],
                "pm10": [55.0],
                "aerosol_optical_depth": [0.42],
                "dust": [7.0],
                "us_aqi": [105],
                "european_aqi": [63],
            }
        }
        second_payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "pm2_5": [37.0, 12.0],
                "pm10": [56.0, 18.0],
                "aerosol_optical_depth": [0.43, 0.10],
                "dust": [8.0, 2.0],
                "us_aqi": [110, 40],
                "european_aqi": [65, 20],
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = OpenMeteoArchiveStore(tmp)
            store.write_air_quality_archive(normalize_open_meteo_air_quality_archive(first_payload, spec), spec)
            result = store.write_air_quality_archive(normalize_open_meteo_air_quality_archive(second_payload, spec), spec)
            hourly_rows = list(csv.DictReader(Path(result["hourly_path"]).open(encoding="utf-8", newline="")))
            coverage = store.air_quality_coverage(spec, "2026-06-01", "2026-06-03")
            missing = store.air_quality_missing_ranges(spec, "2026-06-01", "2026-06-03", chunk_days=2)

        self.assertEqual(result["hourly_rows"], 2)
        self.assertEqual(len(hourly_rows), 2)
        self.assertEqual(hourly_rows[0]["pm2_5"], "37.0")
        self.assertEqual(coverage["covered_days"], 2)
        self.assertEqual(coverage["missing_days"], 1)
        self.assertEqual(missing[0][0].isoformat(), "2026-06-03")


if __name__ == "__main__":
    unittest.main()
