import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from historical_backfill_plan import build_plan, split_ranges
from market_registry import NYC, TORONTO
from historical_coverage import fleet_coverage
from noaa_ghcnh_history import GHCNHStore, normalize_psv, resolve_station
from reanalysis_history import ReanalysisStore, normalize_payload


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
        self.assertEqual(plan["market_count"], 1)
        self.assertEqual(plan["sources"], ["wu"])
        self.assertIn("queue", plan)

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
            self.assertEqual(ranges, [(date(2026, 6, 2), date(2026, 6, 2))])


if __name__ == "__main__":
    unittest.main()
