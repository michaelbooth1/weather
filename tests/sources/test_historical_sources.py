import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from historical_backfill_plan import build_plan, split_ranges
from market_registry import NYC, TORONTO
from historical_coverage import fleet_coverage
from forecast_history import daily_issue_rows, historical_forecast_rows, load_forecast_profiles, previous_run_rows, write_csv, RICH_FORECAST_COLUMNS
from noaa_ghcnh_history import GHCNHStore, normalize_psv, resolve_station
from reanalysis_history import ReanalysisStore, normalize_payload
from wu_history import normalize_observation, summarize_daily


GHCNH_SAMPLE = """STATION|Station_name|DATE|Year|Month|Day|Hour|Minute|LATITUDE|LONGITUDE|ELEVATION|temperature|temperature_Quality_Code|temperature_Report_Type|dew_point_temperature|dew_point_temperature_Quality_Code|station_level_pressure|sea_level_pressure|wind_direction|wind_speed|relative_humidity
USW00014732|LAGUARDIA AP|2023-06-01T12:51:00|2023|06|01|12|51|40.78|-73.88|3.0|23.3||FM-15|12.0||1010.1|1012.4|180|9.3|49
USW00014732|LAGUARDIA AP|2023-06-01T13:51:00|2023|06|01|13|51|40.78|-73.88|3.0|25.0||FM-15|13.0||1009.1|1011.4|190|11.1|47
"""


class TestHistoricalSources(unittest.TestCase):
    def test_fleet_coverage_includes_all_item29_sources(self):
        payload = fleet_coverage(["nyc"])

        self.assertEqual(payload["schema_version"], "historical_coverage_v1")
        sources = payload["markets"][0]["sources"]
        self.assertIn("wu", sources)
        self.assertIn("ghcnh", sources)
        self.assertIn("reanalysis", sources)

    def test_backfill_plan_has_stable_shape(self):
        plan = build_plan(
            market_ids=["nyc"],
            sources=["wu"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            python="python",
        )

        self.assertEqual(plan["schema_version"], "historical_backfill_plan_v1")
        self.assertEqual(plan["queue_mode"], "market_source")
        self.assertEqual(plan["market_count"], 1)
        self.assertEqual(plan["sources"], ["wu"])
        self.assertIn("queue", plan)

    def test_market_source_plan_coalesces_missing_ranges(self):
        class FakeStore:
            def missing_ranges(self, start_date, end_date, chunk_days=14):
                return [
                    (date(2026, 1, 1), date(2026, 1, 2)),
                    (date(2026, 1, 5), date(2026, 1, 5)),
                ]

        with patch("historical_backfill_plan.wu_store", return_value=FakeStore()):
            plan = build_plan(
                market_ids=["nyc"],
                sources=["wu"],
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 5),
                python="python",
            )

        self.assertEqual(plan["queue_count"], 1)
        item = plan["queue"][0]
        self.assertEqual(item["detail"]["kind"], "market_source_date_window")
        self.assertEqual(item["detail"]["missing_ranges"], 2)
        self.assertEqual(item["detail"]["missing_days"], 3)
        self.assertEqual(item["command"][item["command"].index("--start") + 1], "2026-01-01")
        self.assertEqual(item["command"][item["command"].index("--end") + 1], "2026-01-05")

    def test_split_ranges_chunks_contiguous_missing_days(self):
        ranges = split_ranges(
            [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5)],
            chunk_days=1,
        )

        self.assertEqual(ranges, [
            (date(2026, 1, 1), date(2026, 1, 1)),
            (date(2026, 1, 2), date(2026, 1, 2)),
            (date(2026, 1, 5), date(2026, 1, 5)),
        ])

    def test_wu_normalizer_quarantines_impossible_temperature(self):
        base = {
            "key": "KMIA",
            "obs_id": "KMIA",
            "obs_name": "Miami Intl",
            "valid_time_gmt": int(datetime(2005, 6, 11, 14, 0, tzinfo=timezone.utc).timestamp()),
            "rh": 72,
            "pressure": 29.95,
            "vis": 10,
            "wdir": 120,
            "wspd": 8,
            "gust": None,
            "clds": "FEW",
            "wx_phrase": "Fair",
        }
        bad = {
            **base,
            "temp": 171,
            "dewPt": 171,
            "heat_index": 403,
            "wc": 171,
        }
        good = {
            **base,
            "valid_time_gmt": int(datetime(2005, 6, 11, 15, 0, tzinfo=timezone.utc).timestamp()),
            "temp": 86,
            "dewPt": 78,
            "heat_index": 95,
            "wc": 86,
        }

        self.assertIsNone(normalize_observation(bad, NYC.tz, unit="F"))
        row = normalize_observation(good, NYC.tz, unit="F")

        self.assertIsNotNone(row)
        daily = summarize_daily([row])
        self.assertEqual(daily[0]["max_temp_bucket"], 86)

    def test_forecast_history_writes_source_issue_rows(self):
        payload = {
            "hourly": {
                "time": ["2026-06-11T14:00", "2026-06-11T15:00"],
                "temperature_2m": [82, 85],
                "cloud_cover": [20, 35],
                "cloud_cover_low": [10, 15],
                "cloud_cover_mid": [5, 10],
                "cloud_cover_high": [30, 40],
                "shortwave_radiation": [700, 800],
                "wind_speed_10m": [8, 9],
                "temperature_2m_previous_day1": [80, 83],
                "temperature_2m_previous_day2": [79, 81],
            }
        }

        stitched = historical_forecast_rows(payload, NYC)
        previous = previous_run_rows(payload, NYC, leads=(1, 2))
        daily_rows = daily_issue_rows(stitched + previous)

        self.assertEqual(stitched[0]["source"], "open_meteo_historical_forecast")
        self.assertEqual(stitched[0]["issue_time_basis"], "stitched_continuous_archive")
        self.assertEqual(stitched[0]["low_cloud"], 10)
        self.assertEqual(stitched[0]["shortwave_radiation"], 700)
        self.assertEqual(previous[0]["source"], "open_meteo_previous_runs")
        self.assertEqual(previous[0]["issue_time_basis"], "fixed_lead_day_offset")
        self.assertEqual(previous[0]["lead_days"], 1)
        self.assertIn("2026-06-10T00:00", previous[0]["issue_time"])
        lead_two = [
            row for row in daily_rows
            if row["source"] == "open_meteo_previous_runs" and row["lead_days"] == 2
        ][0]
        self.assertEqual(lead_two["forecast_high_native"], 81)
        self.assertEqual(lead_two["hourly_rows"], 2)

    def test_forecast_profile_loader_reads_new_radiation_and_cloud_layers(self):
        payload = {
            "hourly": {
                "time": ["2026-06-11T12:00", "2026-06-11T13:00"],
                "temperature_2m": [82, 85],
                "cloud_cover": [20, 35],
                "cloud_cover_low": [10, 15],
                "cloud_cover_mid": [5, 10],
                "cloud_cover_high": [30, 40],
                "shortwave_radiation": [700, 800],
                "wind_speed_10m": [8, 9],
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forecast_long.csv"
            write_csv(path, RICH_FORECAST_COLUMNS, historical_forecast_rows(payload, NYC))

            profiles = load_forecast_profiles(path)

        self.assertEqual(profiles["2026-06-11"][0]["minute_of_day"], 720)
        self.assertEqual(profiles["2026-06-11"][0]["low_cloud"], 10.0)
        self.assertEqual(profiles["2026-06-11"][1]["solar"], 800.0)

    def test_ghcnh_station_resolves_by_icao(self):
        station = resolve_station(NYC, [
            {"GHCN_ID": "USW00099999", "ICAO": "XXXX", "LATITUDE": "0", "LONGITUDE": "0"},
            {"GHCN_ID": "USW00014732", "ICAO": "KLGA", "LATITUDE": "40.779", "LONGITUDE": "-73.88"},
        ])

        self.assertEqual(station["GHCN_ID"], "USW00014732")

    def test_ghcnh_station_resolves_canadian_blank_icao_by_nearest_wmo(self):
        station = resolve_station(TORONTO, [
            {
                "GHCN_ID": "CAN06158733",
                "ICAO": "",
                "ISO_CODE": "CA",
                "WMO_ID": "",
                "LATITUDE": "43.677",
                "LONGITUDE": "-79.631",
            },
            {
                "GHCN_ID": "CAN06158731",
                "ICAO": "",
                "ISO_CODE": "CA",
                "WMO_ID": "71624",
                "LATITUDE": "43.677",
                "LONGITUDE": "-79.631",
            },
        ])

        self.assertEqual(station["GHCN_ID"], "CAN06158731")

    def test_ghcnh_normalizes_to_native_unit_schema(self):
        station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}

        records = normalize_psv(GHCNH_SAMPLE, NYC, station)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "noaa_ghcnh")
        self.assertEqual(records[0]["temperature_unit"], "F")
        self.assertAlmostEqual(records[0]["temp_native"], 73.94)
        self.assertEqual(records[0]["local_date"], "2023-06-01")
        self.assertEqual(records[0]["station"], "USW00014732")

    def test_ghcnh_store_rebuild_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GHCNHStore(NYC, tmp)
            station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}
            store.write_station(station)
            store.write_year("USW00014732", 2023, GHCNH_SAMPLE)

            records, daily = store.rebuild()

            self.assertEqual(len(records), 2)
            self.assertEqual(daily[0]["max_temp_bucket"], 77)
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            self.assertTrue((Path(tmp) / "hourly" / "year=2023" / "month=06" / "observations.jsonl").exists())

    def test_ghcnh_source_unavailable_years_are_not_refetch_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = GHCNHStore(NYC, tmp)
            station = {"GHCN_ID": "USW00014732", "NAME": "LAGUARDIA AP"}
            store.write_station(station)
            store.write_year("USW00014732", 2023, GHCNH_SAMPLE)
            store.record_source_unavailable_year(
                "USW00014732",
                2022,
                "https://example.test/GHCNh_USW00014732_2022.psv",
                "404 Client Error",
            )

            records, daily = store.rebuild()
            coverage = store.coverage(2022, 2023)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(len(records), 2)
            self.assertEqual(daily[0]["local_date"], "2023-06-01")
            self.assertEqual(store.missing_years(2022, 2023), [])
            self.assertEqual(coverage["missing_years"], [])
            self.assertEqual(coverage["source_unavailable_years"], [2022])
            self.assertEqual(coverage["raw_missing_years"], [2022])
            self.assertEqual(manifest["metadata"]["source_unavailable_year_count"], 1)

    def test_reanalysis_normalizes_to_native_unit_schema(self):
        payload = {
            "generationtime_ms": 1.2,
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-01T13:00"],
                "temperature_2m": [20.1, 21.6],
                "dew_point_2m": [11.0, 12.0],
                "relative_humidity_2m": [55, 52],
                "pressure_msl": [1012.0, 1011.8],
                "wind_speed_10m": [8.0, 9.0],
                "wind_direction_10m": [180, 190],
                "wind_gusts_10m": [14.0, 15.0],
                "cloud_cover": [20, 25],
            },
        }

        records = normalize_payload(payload, TORONTO)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "open_meteo_era5_reanalysis")
        self.assertEqual(records[0]["temperature_unit"], "C")
        self.assertEqual(records[1]["temp_native"], 21.6)
        self.assertEqual(records[1]["local_date"], "2026-06-01")

    def test_reanalysis_store_rebuild_writes_manifest(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m": [75.0],
                "dew_point_2m": [60.0],
                "relative_humidity_2m": [60],
                "pressure_msl": [1012.0],
                "wind_speed_10m": [8.0],
                "wind_direction_10m": [180],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(__import__("datetime").date(2026, 6, 1), __import__("datetime").date(2026, 6, 1), payload)

            records, daily = store.rebuild()

            self.assertEqual(len(records), 1)
            self.assertEqual(daily[0]["max_temp_bucket"], 75)
            self.assertTrue((Path(tmp) / "manifest.json").exists())
            manifest = json.loads((Path(tmp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "open_meteo_era5_reanalysis")

    def test_reanalysis_coverage_uses_normalized_daily_dates(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00"],
                "temperature_2m": [75.0],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)
            store.rebuild()

            coverage = store.coverage(date(2026, 6, 1), date(2026, 6, 2))
            ranges = store.missing_ranges(date(2026, 6, 1), date(2026, 6, 2))

            self.assertEqual(coverage["raw_covered_days"], 2)
            self.assertEqual(coverage["normalized_daily_days"], 1)
            self.assertEqual(coverage["covered_days"], 1)
            self.assertEqual(coverage["missing_days"], 1)
            self.assertEqual(coverage["raw_only_days"], ["2026-06-02"])
            self.assertEqual(coverage["raw_only_day_count"], 1)
            self.assertEqual(coverage["raw_only_normalizable_days"], [])
            self.assertEqual(coverage["raw_only_normalizable_day_count"], 0)
            self.assertEqual(coverage["raw_only_source_lag_days"], ["2026-06-02"])
            self.assertEqual(coverage["raw_only_source_lag_day_count"], 1)
            self.assertEqual(ranges, [(date(2026, 6, 2), date(2026, 6, 2))])

    def test_reanalysis_coverage_flags_normalizable_raw_only_days(self):
        payload = {
            "hourly": {
                "time": ["2026-06-01T12:00", "2026-06-02T12:00"],
                "temperature_2m": [75.0, 76.0],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ReanalysisStore(NYC, tmp)
            store.write_payload(date(2026, 6, 1), date(2026, 6, 2), payload)

            coverage = store.coverage(date(2026, 6, 1), date(2026, 6, 2))

            self.assertEqual(coverage["raw_only_days"], ["2026-06-01", "2026-06-02"])
            self.assertEqual(coverage["raw_only_normalizable_days"], ["2026-06-01", "2026-06-02"])
            self.assertEqual(coverage["raw_only_normalizable_day_count"], 2)
            self.assertEqual(coverage["raw_only_source_lag_days"], [])


if __name__ == "__main__":
    unittest.main()
