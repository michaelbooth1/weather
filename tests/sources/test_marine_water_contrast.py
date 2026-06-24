import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from weather.market.market_registry import NYC, TORONTO
from weather.sources.marine_water_contrast import (
    MarineWaterContrastStore,
    build_feature_rows,
    cutoff_context_from_station_history,
    extract_gridded_sst_points_from_netcdf,
    load_marine_water_contrast_features,
)


def station_history_payload():
    return {
        "schema_version": "marine_station_history_v0.1",
        "source": "marine_station_history",
        "market": "toronto",
        "target_date": "2026-06-15",
        "payload_hash": "station-hash",
        "provenance": {"history_basis": "unit test station history"},
        "stations": [
            {
                "provider": "ndbc",
                "station_id": "45159",
                "station_name": "Northwest Lake Ontario buoy",
                "water_body": "Lake Ontario",
                "distance_km": 43.0,
                "required_sensors": ["wind", "water_temperature"],
                "sensor_support": ["wind", "air_temperature", "water_temperature"],
                "onshore_direction_min": 60.0,
                "onshore_direction_max": 160.0,
                "rows": [
                    {
                        "valid_time_utc": "2026-06-15T16:00:00+00:00",
                        "minute_of_day": 720,
                        "water_temp_native": 15.0,
                        "air_temp_native": 19.0,
                        "wind_speed_kmh": 14.0,
                        "wind_direction_degrees": 120.0,
                        "source_url": "https://example.test/noaa/45159",
                    },
                    {
                        "valid_time_utc": "2026-06-15T22:00:00+00:00",
                        "minute_of_day": 1080,
                        "water_temp_native": 25.0,
                        "air_temp_native": 24.0,
                        "wind_speed_kmh": 10.0,
                        "wind_direction_degrees": 300.0,
                        "source_url": "https://example.test/noaa/45159",
                    },
                ],
            }
        ],
    }


class MarineWaterContrastTests(unittest.TestCase):
    def test_station_history_context_filters_rows_to_cutoff_wall_time(self):
        payload = station_history_payload()

        noon_context = cutoff_context_from_station_history(payload, 13, wall_minute=780)
        evening_context = cutoff_context_from_station_history(payload, 19, wall_minute=1140)

        self.assertTrue(noon_context["available"])
        self.assertEqual(noon_context["stations"][0]["latest"]["water_temp_native"], 15.0)
        self.assertEqual(noon_context["stations"][0]["latest"]["wind_direction_degrees"], 120.0)
        self.assertEqual(noon_context["stations"][0]["latest_age_minutes"], 60)
        self.assertEqual(evening_context["stations"][0]["latest"]["water_temp_native"], 25.0)
        self.assertEqual(evening_context["stations"][0]["latest"]["wind_direction_degrees"], 300.0)

    def test_build_feature_rows_uses_station_wind_and_gridded_sst_with_provenance(self):
        rows = build_feature_rows(
            TORONTO,
            station_history_payloads={"2026-06-15": station_history_payload()},
            gridded_sst_rows={
                "2026-06-15": {
                    "provider": "glsea",
                    "product": "GLSEA",
                    "market_id": "toronto",
                    "local_date": "2026-06-15",
                    "water_temp_c": 12.0,
                    "water_temp_native": 12.0,
                    "source_url": "https://example.test/glsea",
                    "payload_hash": "glsea-hash",
                }
            },
            forecast_high_index={"2026-06-15": 30.0},
            cutoff_hours=(13,),
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        provenance = json.loads(row["provenance"])
        self.assertEqual(row["feature_source"], "station_history_plus_gridded_sst")
        self.assertEqual(row["sst_provider"], "glsea")
        self.assertEqual(row["marine_water_temp_native"], 12.0)
        self.assertEqual(row["marine_water_minus_forecast_high"], -18.0)
        self.assertEqual(row["marine_onshore_flow"], 1.0)
        self.assertEqual(row["marine_onshore_cooling_potential"], 18.0)
        self.assertEqual(provenance["station_payload_hash"], "station-hash")
        self.assertEqual(provenance["gridded_sst_payload_hash"], "glsea-hash")

    def test_extract_gridded_sst_points_from_netcdf_nearest_market_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oisst.nc"
            with netcdf_file(path, "w") as dataset:
                dataset.createDimension("time", 2)
                dataset.createDimension("lat", 2)
                dataset.createDimension("lon", 2)
                time = dataset.createVariable("time", "f8", ("time",))
                time.units = b"days since 2026-06-15 00:00:00"
                time[:] = np.array([0.0, 1.0])
                lat = dataset.createVariable("lat", "f8", ("lat",))
                lat[:] = np.array([40.0, 41.0])
                lon = dataset.createVariable("lon", "f8", ("lon",))
                lon[:] = np.array([286.0, 287.0])
                sst = dataset.createVariable("analysed_sst", "f8", ("time", "lat", "lon"))
                sst.units = b"kelvin"
                values = np.full((2, 2, 2), 290.0)
                values[0, 1, 0] = 294.15
                values[1, 1, 0] = 295.15
                sst[:] = values

            rows = extract_gridded_sst_points_from_netcdf(path, NYC, provider="oisst")

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["schema_version"], "marine_gridded_sst_point_v0.1")
        self.assertEqual(first["provider"], "oisst")
        self.assertEqual(first["local_date"], "2026-06-15")
        self.assertAlmostEqual(first["water_temp_c"], 21.0)
        self.assertAlmostEqual(first["water_temp_native"], 69.8)
        self.assertEqual(first["grid_lon"], 286.0)
        self.assertTrue(first["payload_hash"])

    def test_store_writes_sidecar_and_loads_cutoff_feature_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MarineWaterContrastStore(TORONTO, root=tmp)
            store.write_station_history_payload("2026-06-15", station_history_payload())
            rows = store.build_features(
                forecast_high_index={"2026-06-15": 30.0},
                cutoff_hours=(13,),
            )
            loaded = load_marine_water_contrast_features(path=store.features_path)
            written_rows = list(csv.DictReader(store.features_path.open(encoding="utf-8", newline="")))
            manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(loaded[("2026-06-15", 13)]["marine_water_temp_native"], 15.0)
        self.assertEqual(written_rows[0]["feature_source"], "station_history")
        self.assertEqual(manifest["schema_version"], "marine_water_contrast_backfill_v0.1")
        self.assertEqual(manifest["feature_rows"], 1)


if __name__ == "__main__":
    unittest.main()
