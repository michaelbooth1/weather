import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from weather.market.market_registry import NYC, TORONTO
from weather.model.feature_store import build_historical_feature_record
from weather.sources.reanalysis_synoptic import (
    PRESSURE_LEVEL_CACHE_STATUS_SCHEMA_VERSION,
    REANALYSIS_SYNOPTIC_SCHEMA_VERSION,
    build_pressure_level_cache_status,
    build_reanalysis_synoptic_rows,
    default_pressure_level_root,
    load_pressure_level_daily_metrics,
    load_teleconnection_index,
    load_reanalysis_synoptic_features,
    pressure_level_raw_path,
    render_pressure_level_cache_status_markdown,
    write_feature_csv,
)
from weather.sources.reanalysis_history import DEFAULT_ROOT as REANALYSIS_DEFAULT_ROOT


class TestReanalysisSynoptic(unittest.TestCase):
    def test_default_pressure_level_root_uses_shared_cache(self):
        self.assertEqual(
            default_pressure_level_root(NYC),
            REANALYSIS_DEFAULT_ROOT / "pressure_level",
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                default_pressure_level_root(NYC, root=tmp),
                Path(tmp) / "pressure_level",
            )

    def test_pressure_level_cache_status_reports_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            air = pressure_level_raw_path(root, "air", 2026)
            air.parent.mkdir(parents=True, exist_ok=True)
            air.write_bytes(b"air")

            payload = build_pressure_level_cache_status(
                NYC,
                "2026-06-01",
                "2026-06-02",
                root=root,
                check_remote=False,
                include_metrics=False,
            )
            report = render_pressure_level_cache_status_markdown(payload)

        self.assertEqual(payload["schema_version"], PRESSURE_LEVEL_CACHE_STATUS_SCHEMA_VERSION)
        self.assertEqual(payload["status"], "MISSING_LOCAL_FILES")
        self.assertEqual(payload["summary"]["file_count"], 2)
        self.assertEqual(payload["summary"]["missing_local_files"], 1)
        self.assertIn("Pressure-Level Reanalysis Cache Status", report)
        self.assertIn("MISSING_LOCAL_FILES", report)

    def test_builds_antecedent_features_without_using_target_day(self):
        daily = [
            {
                "local_date": "2024-06-01",
                "max_temp": "24.0",
                "min_temp": "12.0",
                "avg_temp": "18.0",
                "max_dewpoint": "8.0",
                "max_wind_kmh": "20.0",
                "max_gust_kmh": "31.0",
            },
            {
                "local_date": "2025-06-01",
                "max_temp": "28.0",
                "min_temp": "16.0",
                "avg_temp": "22.0",
                "max_dewpoint": "12.0",
                "max_wind_kmh": "18.0",
                "max_gust_kmh": "29.0",
            },
            {
                "local_date": "2025-06-02",
                "max_temp": "35.0",
                "min_temp": "24.0",
                "avg_temp": "30.0",
                "max_dewpoint": "20.0",
                "max_wind_kmh": "10.0",
                "max_gust_kmh": "13.0",
            },
        ]
        hourly = {
            date(2025, 5, 31): {"pressure_mean_hpa": 1010.0},
            date(2025, 6, 1): {"pressure_mean_hpa": 1006.5},
        }
        raw = {
            date(2025, 6, 1): {
                "soil_temperature_0_to_7cm": 23.5,
                "soil_moisture_0_to_7cm": 0.21,
                "shortwave_radiation": 6100.0,
                "cloud_cover_low": 15.0,
            }
        }
        pressure_level = {
            date(2025, 6, 1): {
                "reanalysis_prev_day_temperature_850hpa_c": 14.25,
                "reanalysis_prev_day_geopotential_height_500hpa_m": 5740.0,
                "reanalysis_prev_day_thickness_1000_500hpa_m": 5605.0,
            },
            date(2025, 6, 2): {
                "reanalysis_prev_day_temperature_850hpa_c": 20.0,
                "reanalysis_prev_day_geopotential_height_500hpa_m": 5800.0,
                "reanalysis_prev_day_thickness_1000_500hpa_m": 5650.0,
            },
        }

        rows = build_reanalysis_synoptic_rows(
            TORONTO,
            daily,
            hourly_daily_metrics=hourly,
            raw_daily_metrics=raw,
            pressure_level_daily_metrics=pressure_level,
        )
        by_date = {row["local_date"]: row for row in rows}
        row = by_date["2025-06-02"]

        self.assertEqual(row["schema_version"], REANALYSIS_SYNOPTIC_SCHEMA_VERSION)
        self.assertEqual(row["antecedent_date"], "2025-06-01")
        self.assertEqual(row["reanalysis_prev_day_max_temp"], 28.0)
        self.assertEqual(row["reanalysis_prev_day_temp_range"], 12.0)
        self.assertEqual(row["reanalysis_prev_day_pressure_mean_hpa"], 1006.5)
        self.assertEqual(row["reanalysis_pressure_change_24h_hpa"], -3.5)
        self.assertEqual(row["reanalysis_prev_day_soil_temperature_0_to_7cm_mean"], 23.5)
        self.assertEqual(row["reanalysis_prev_day_soil_moisture_0_to_7cm_mean"], 0.21)
        self.assertEqual(row["reanalysis_prev_day_shortwave_radiation_sum"], 6100.0)
        self.assertEqual(row["reanalysis_prev_day_low_cloud_mean"], 15.0)
        self.assertEqual(row["reanalysis_pressure_level_available"], 1.0)
        self.assertEqual(row["reanalysis_prev_day_temperature_850hpa_c"], 14.25)
        self.assertEqual(row["reanalysis_prev_day_geopotential_height_500hpa_m"], 5740.0)
        self.assertEqual(row["reanalysis_prev_day_thickness_1000_500hpa_m"], 5605.0)
        self.assertEqual(row["reanalysis_coastal_flag"], 0.0)
        self.assertEqual(row["reanalysis_continentality_km"], 43.0)
        self.assertEqual(row["reanalysis_sea_breeze_context_flag"], 1.0)
        self.assertEqual(row["reanalysis_lake_breeze_context_flag"], 1.0)
        self.assertEqual(row["reanalysis_nearest_water_distance_km"], 43.0)
        self.assertEqual(row["reanalysis_marine_context_station_count"], 1.0)
        self.assertNotEqual(row["reanalysis_prev_day_max_temp"], 35.0)

    def test_writes_and_loads_feature_index(self):
        rows = build_reanalysis_synoptic_rows(
            NYC,
            [
                {"local_date": "2025-06-01", "max_temp": "82", "min_temp": "70"},
                {"local_date": "2025-06-02", "max_temp": "84", "min_temp": "72"},
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "features.csv"
            write_feature_csv(path, rows)

            index = load_reanalysis_synoptic_features(path)

        self.assertEqual(index["2025-06-02"]["reanalysis_prev_day_max_temp"], 82.0)
        self.assertEqual(index["2025-06-02"]["reanalysis_coastal_flag"], 1.0)
        self.assertEqual(index["2025-06-02"]["reanalysis_sea_breeze_context_flag"], 1.0)
        self.assertEqual(index["2025-06-02"]["reanalysis_lake_breeze_context_flag"], 0.0)
        self.assertIsNone(index["2025-06-01"]["reanalysis_prev_day_max_temp"])

    def test_lagged_teleconnections_do_not_use_target_month(self):
        daily = [
            {"local_date": "2025-04-30", "max_temp": "70", "min_temp": "50"},
            {"local_date": "2025-05-15", "max_temp": "72", "min_temp": "52"},
            {"local_date": "2025-06-02", "max_temp": "82", "min_temp": "61"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            oni_path = tmp / "oni.ascii.txt"
            pna_path = tmp / "pna.ascii"
            oni_path.write_text(
                " SEAS  YR   TOTAL   ANOM\n"
                "  FMA 2025  26.00   0.30\n"
                "  MAM 2025  26.40   0.60\n"
                "  AMJ 2025  26.90   1.10\n",
                encoding="utf-8",
            )
            pna_path.write_text(
                " 2025    4   -0.7000\n"
                " 2025    5    0.8000\n"
                " 2025    6    2.0000\n",
                encoding="utf-8",
            )
            teleconnections = load_teleconnection_index(oni_path=oni_path, pna_path=pna_path)

        rows = build_reanalysis_synoptic_rows(
            NYC,
            daily,
            teleconnection_index=teleconnections,
        )
        by_date = {row["local_date"]: row for row in rows}
        may = by_date["2025-05-15"]
        june = by_date["2025-06-02"]

        self.assertEqual(may["reanalysis_enso_oni_lagged"], 0.30)
        self.assertEqual(may["reanalysis_pna_lagged"], -0.70)
        self.assertEqual(may["reanalysis_pna_negative_flag"], 1.0)
        self.assertEqual(june["reanalysis_enso_oni_lagged"], 0.60)
        self.assertEqual(june["reanalysis_enso_oni_lag_months"], 2.0)
        self.assertEqual(june["reanalysis_enso_el_nino_flag"], 1.0)
        self.assertEqual(june["reanalysis_pna_lagged"], 0.80)
        self.assertEqual(june["reanalysis_pna_positive_flag"], 1.0)
        self.assertNotEqual(june["reanalysis_pna_lagged"], 2.0)

    def test_historical_feature_record_merges_reanalysis_sidecar(self):
        rows = [
            {
                "minute_of_day": 420,
                "temp_native": 16.0,
                "dewpoint_native": 10.0,
                "pressure": 1012.0,
                "humidity": 60,
                "wind_kmh": 8.0,
                "wind": "S",
                "condition": "Clear",
                "clouds": "Clear",
            },
            {
                "minute_of_day": 720,
                "temp_native": 22.0,
                "dewpoint_native": 11.0,
                "pressure": 1011.0,
                "humidity": 55,
                "wind_kmh": 10.0,
                "wind": "S",
                "condition": "Clear",
                "clouds": "Clear",
            },
        ]

        record = build_historical_feature_record(
            "2025-06-02",
            rows,
            {"bucket": 26},
            12,
            reanalysis_synoptic_features={
                "reanalysis_synoptic_available": 1.0,
                "reanalysis_prev_day_max_temp": 28.0,
            },
        )

        self.assertEqual(record["reanalysis_synoptic_available"], 1.0)
        self.assertEqual(record["reanalysis_prev_day_max_temp"], 28.0)
        self.assertIsNone(record["reanalysis_prev_day_soil_moisture_0_to_7cm_mean"])

    def test_load_pressure_level_daily_metrics_reads_cached_netcdf(self):
        def write_pressure_file(path, variable_name, values):
            path.parent.mkdir(parents=True, exist_ok=True)
            with netcdf_file(path, "w") as dataset:
                dataset.createDimension("time", 2)
                dataset.createDimension("level", 3)
                dataset.createDimension("lat", 2)
                dataset.createDimension("lon", 2)
                time = dataset.createVariable("time", "f8", ("time",))
                time.units = b"hours since 2025-06-01 00:00:00"
                time[:] = np.array([0.0, 24.0])
                level = dataset.createVariable("level", "f8", ("level",))
                level[:] = np.array([1000.0, 850.0, 500.0])
                lat = dataset.createVariable("lat", "f8", ("lat",))
                lat[:] = np.array([40.0, 41.0])
                lon = dataset.createVariable("lon", "f8", ("lon",))
                lon[:] = np.array([286.0, 287.0])
                variable = dataset.createVariable(variable_name, "f8", ("time", "level", "lat", "lon"))
                variable.units = b"degK" if variable_name == "air" else b"m"
                variable[:] = values

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            air = np.full((2, 3, 2, 2), 270.0)
            hgt = np.full((2, 3, 2, 2), 0.0)
            # NYC's nearest grid point in this fixture is lat=41, lon=286.
            air[0, 1, 1, 0] = 289.15
            air[1, 1, 1, 0] = 291.15
            hgt[0, 2, 1, 0] = 5740.0
            hgt[0, 0, 1, 0] = 135.0
            hgt[1, 2, 1, 0] = 5760.0
            hgt[1, 0, 1, 0] = 145.0
            write_pressure_file(pressure_level_raw_path(root, "air", 2025), "air", air)
            write_pressure_file(pressure_level_raw_path(root, "hgt", 2025), "hgt", hgt)

            metrics = load_pressure_level_daily_metrics(NYC, root=root)
            status = build_pressure_level_cache_status(
                NYC,
                "2025-06-01",
                "2025-06-03",
                root=root,
                check_remote=False,
            )

        first = metrics[date(2025, 6, 1)]
        second = metrics[date(2025, 6, 2)]
        self.assertAlmostEqual(first["reanalysis_prev_day_temperature_850hpa_c"], 16.0)
        self.assertEqual(first["reanalysis_prev_day_geopotential_height_500hpa_m"], 5740.0)
        self.assertEqual(first["reanalysis_prev_day_thickness_1000_500hpa_m"], 5605.0)
        self.assertAlmostEqual(second["reanalysis_prev_day_temperature_850hpa_c"], 18.0)
        self.assertEqual(second["reanalysis_prev_day_thickness_1000_500hpa_m"], 5615.0)
        self.assertEqual(status["status"], "CACHE_CURRENT")
        self.assertEqual(status["metric_coverage"]["requested_days"], 3)
        self.assertEqual(status["metric_coverage"]["complete_days"], 2)
        self.assertEqual(status["metric_coverage"]["missing_days"], 1)
        self.assertEqual(status["metric_coverage"]["latest_cached_metric_date"], "2025-06-02")

    def test_load_pressure_level_daily_metrics_reads_cached_netcdf4(self):
        from netCDF4 import Dataset

        def write_pressure_file(path, variable_name, values):
            path.parent.mkdir(parents=True, exist_ok=True)
            with Dataset(path, "w", format="NETCDF4") as dataset:
                dataset.createDimension("time", 2)
                dataset.createDimension("level", 3)
                dataset.createDimension("lat", 2)
                dataset.createDimension("lon", 2)
                time = dataset.createVariable("time", "f8", ("time",))
                time.units = "hours since 2025-06-01 00:00:00"
                time[:] = np.array([0.0, 24.0])
                level = dataset.createVariable("level", "f8", ("level",))
                level[:] = np.array([1000.0, 850.0, 500.0])
                lat = dataset.createVariable("lat", "f8", ("lat",))
                lat[:] = np.array([40.0, 41.0])
                lon = dataset.createVariable("lon", "f8", ("lon",))
                lon[:] = np.array([286.0, 287.0])
                variable = dataset.createVariable(variable_name, "f8", ("time", "level", "lat", "lon"))
                variable.units = "degK" if variable_name == "air" else "m"
                variable[:] = values

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            air = np.full((2, 3, 2, 2), 270.0)
            hgt = np.full((2, 3, 2, 2), 0.0)
            air[0, 1, 1, 0] = 289.15
            air[1, 1, 1, 0] = 291.15
            hgt[0, 2, 1, 0] = 5740.0
            hgt[0, 0, 1, 0] = 135.0
            hgt[1, 2, 1, 0] = 5760.0
            hgt[1, 0, 1, 0] = 145.0
            write_pressure_file(pressure_level_raw_path(root, "air", 2025), "air", air)
            write_pressure_file(pressure_level_raw_path(root, "hgt", 2025), "hgt", hgt)

            metrics = load_pressure_level_daily_metrics(NYC, root=root)

        first = metrics[date(2025, 6, 1)]
        second = metrics[date(2025, 6, 2)]
        self.assertAlmostEqual(first["reanalysis_prev_day_temperature_850hpa_c"], 16.0)
        self.assertEqual(first["reanalysis_prev_day_geopotential_height_500hpa_m"], 5740.0)
        self.assertEqual(first["reanalysis_prev_day_thickness_1000_500hpa_m"], 5605.0)
        self.assertAlmostEqual(second["reanalysis_prev_day_temperature_850hpa_c"], 18.0)
        self.assertEqual(second["reanalysis_prev_day_thickness_1000_500hpa_m"], 5615.0)


if __name__ == "__main__":
    unittest.main()
