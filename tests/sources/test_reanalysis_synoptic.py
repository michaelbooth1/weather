import tempfile
import unittest
from datetime import date
from pathlib import Path

from weather.market.market_registry import NYC, TORONTO
from weather.model.feature_store import build_historical_feature_record
from weather.sources.reanalysis_synoptic import (
    REANALYSIS_SYNOPTIC_SCHEMA_VERSION,
    build_reanalysis_synoptic_rows,
    load_teleconnection_index,
    load_reanalysis_synoptic_features,
    write_feature_csv,
)


class TestReanalysisSynoptic(unittest.TestCase):
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

        rows = build_reanalysis_synoptic_rows(
            TORONTO,
            daily,
            hourly_daily_metrics=hourly,
            raw_daily_metrics=raw,
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


if __name__ == "__main__":
    unittest.main()
