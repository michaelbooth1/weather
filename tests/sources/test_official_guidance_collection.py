import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from weather.market.market_registry import spec_for_id
from weather.sources.official_guidance_collection import (
    build_hrdps_archive_collection_payload,
    build_official_guidance_collection_payload,
    collect_official_guidance_from_replay_inputs,
    write_official_guidance_collection_rows,
)


class TestOfficialGuidanceCollection(unittest.TestCase):
    def test_collects_nws_and_open_meteo_guidance_rows(self):
        spec = spec_for_id("nyc")
        sources = {
            "nws_grid": {"ok": True, "data": {
                "url": "https://api.weather.gov/gridpoints/OKX/33,37",
                "payload_hash": "nws-hash",
                "day_rows": [{
                    "time": "12:00",
                    "temp_native": 84.0,
                    "max_temp_native": 88.0,
                    "sky_cover": 60.0,
                    "precipitation_probability": 20.0,
                    "quantitative_precipitation": 0.1,
                    "hazards_count": 1,
                }],
            }},
            "open_meteo_multimodel": {"ok": True, "data": {
                "source_url": "https://api.open-meteo.com/v1/gfs",
                "payload_hash": "multi-hash",
                "day_rows": [{
                    "time": "12:00",
                    "model_temp_spread": 4.0,
                    "models": {
                        "gfs_seamless": {"temp_native": 84.0},
                        "ncep_nbm_conus": {"temp_native": 88.0, "cloud_cover": 30.0},
                    },
                }],
            }},
            "open_meteo_global_models": {"ok": True, "data": {
                "url": "https://api.open-meteo.com/v1/forecast",
                "payload_hash": "global-hash",
                "day_rows": [{
                    "time": "13:00",
                    "model_temp_spread": 3.0,
                    "models": {
                        "ecmwf_ifs025": {"temp_native": 85.0},
                        "gfs_graphcast025": {"temp_native": 88.0},
                    },
                }],
            }},
        }

        payload = build_official_guidance_collection_payload(
            sources,
            spec,
            "2026-06-15",
            captured_at=datetime(2026, 6, 15, 12, 0, tzinfo=spec.tz),
        )

        by_source = payload["source_counts"]
        rows = payload["rows"]
        self.assertEqual(payload["schema_version"], "official_guidance_collection_v0.1")
        self.assertEqual(by_source["nws_grid"], 1)
        self.assertEqual(by_source["open_meteo_multimodel"], 2)
        self.assertEqual(by_source["open_meteo_global_models"], 2)
        self.assertTrue(any(row["model_name"] == "ncep_nbm_conus" for row in rows))
        self.assertTrue(any(row["model_name"] == "ecmwf_ifs025" for row in rows))
        self.assertEqual(rows[0]["source_family"], "official_us_guidance")
        self.assertIn("temp_native", rows[0]["row_json"])

    def test_collects_toronto_eccc_gem_hrdps_rows_and_writes_csv(self):
        spec = spec_for_id("toronto")
        sources = {
            "eccc_gem": {"ok": True, "data": {
                "url": "https://api.open-meteo.com/v1/gem",
                "payload_hash": "gem-hash",
                "day_rows": [{
                    "time": "14:00",
                    "model_temp_spread": 2.0,
                    "models": {
                        "gem_seamless": {
                            "temp_native": 27.0,
                            "wind_direction_degrees": 120.0,
                            "wind_gust_kmh": 30.0,
                            "cloud_cover": 70.0,
                            "precipitation": 0.2,
                        },
                        "gem_regional": {"temp_native": 28.0},
                    },
                }],
            }},
            "eccc_hrdps": {"ok": True, "data": {
                "payload_hash": "hrdps-parent-hash",
                "rows": [{
                    "model": "HRDPS",
                    "product": "TMP",
                    "level": "AGL-2m",
                    "value": 299.15,
                    "unit": "K",
                    "run_time": "2026-06-15T18:00:00+00:00",
                    "forecast_hour": 1,
                    "valid_time": "2026-06-15T19:00:00+00:00",
                    "source_url": "https://dd.weather.gc.ca/today/model_hrdps/file.grib2",
                    "object_key": "20260615T18Z_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PT001H.grib2",
                    "payload_hash": "hrdps-hash",
                    "payload_bytes": 128,
                    "grid": "RLatLon0.0225",
                    "domain": "continental",
                    "fetched_at": "2026-06-15T19:05:00+00:00",
                }],
            }},
        }
        payload = build_official_guidance_collection_payload(sources, spec, "2026-06-15")

        with tempfile.TemporaryDirectory() as tmp:
            result = write_official_guidance_collection_rows(Path(tmp) / "guidance.csv", payload)
            rows = list(csv.DictReader(Path(result["path"]).open(encoding="utf-8", newline="")))

        self.assertEqual(payload["source_counts"], {"eccc_gem": 2, "eccc_hrdps": 1})
        self.assertEqual(rows[0]["source_family"], "official_canadian_guidance")
        self.assertEqual(rows[0]["model_name"], "gem_regional")
        self.assertEqual(rows[1]["model_name"], "gem_seamless")
        self.assertEqual(rows[1]["wind_gust_kmh"], "30.0")
        self.assertEqual(rows[2]["source"], "eccc_hrdps")
        self.assertEqual(rows[2]["model_name"], "HRDPS")
        self.assertEqual(rows[2]["product"], "TMP")
        self.assertEqual(rows[2]["forecast_hour"], "1")
        self.assertEqual(rows[2]["payload_hash"], "hrdps-hash")
        self.assertEqual(result["written_row_count"], 3)

    def test_collects_official_guidance_rows_from_replay_inputs(self):
        replay = {
            "event_slug": "highest-temperature-in-nyc-on-june-15-2026",
            "target_date": "2026-06-15",
            "captured_at_local": "2026-06-15T12:00:00-04:00",
            "sources": {
                "nws_grid": {"ok": True, "data": {
                    "day_rows": [{"time": "12:00", "max_temp_native": 88.0}],
                }},
                "open_meteo_global_models": {"ok": True, "data": {
                    "day_rows": [{
                        "time": "12:00",
                        "models": {"ecmwf_ifs025": {"temp_native": 86.0}},
                    }],
                }},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots" / "event"
            root.mkdir(parents=True)
            (root / "replay_inputs.jsonl").write_text(json.dumps(replay) + "\n", encoding="utf-8")
            csv_out = Path(tmp) / "guidance.csv"
            summary_out = Path(tmp) / "summary.json"

            payload = collect_official_guidance_from_replay_inputs(
                [Path(tmp) / "snapshots"],
                csv_out=csv_out,
                summary_out=summary_out,
            )
            rows = list(csv.DictReader(csv_out.open(encoding="utf-8", newline="")))
            summary = json.loads(summary_out.read_text(encoding="utf-8"))

        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["source_counts"], {"nws_grid": 1, "open_meteo_global_models": 1})
        self.assertEqual(rows[0]["market"], "nyc")
        self.assertEqual(summary["row_count"], 2)
        self.assertNotIn("rows", summary)

    def test_collect_can_dedupe_repeated_replay_source_rows(self):
        replay = {
            "event_slug": "highest-temperature-in-nyc-on-june-15-2026",
            "target_date": "2026-06-15",
            "sources": {
                "nws_grid": {"ok": True, "data": {
                    "payload_hash": "same-raw-payload",
                    "day_rows": [{"time": "12:00", "max_temp_native": 88.0}],
                }},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshots" / "event"
            root.mkdir(parents=True)
            (root / "replay_inputs.jsonl").write_text(
                json.dumps(replay | {"captured_at_local": "2026-06-15T12:00:00-04:00"}) + "\n"
                + json.dumps(replay | {"captured_at_local": "2026-06-15T12:05:00-04:00"}) + "\n",
                encoding="utf-8",
            )

            payload = collect_official_guidance_from_replay_inputs(
                [Path(tmp) / "snapshots"],
                dedupe=True,
            )

        self.assertEqual(payload["row_count"], 1)
        self.assertTrue(payload["dedupe"])
        self.assertEqual(payload["duplicate_row_count"], 1)
        self.assertEqual(payload["source_counts"], {"nws_grid": 1})

    def test_builds_hrdps_archive_rows_from_datamart_listing(self):
        listing = """
        <a href="20260623T00Z_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PT004H.grib2">x</a> 2026-06-23 02:58 4.1M
        <a href="20260623T00Z_MSC_HRDPS_GUST_AGL-10m_RLatLon0.0225_PT004H.grib2">x</a> 2026-06-23 02:58 2.3M
        <a href="20260623T00Z_MSC_HRDPS_TMP_ISBL_0850_RLatLon0.0225_PT004H.grib2">x</a> 2026-06-23 02:58 925K
        """

        payload = build_hrdps_archive_collection_payload(
            ["2026-06-23"],
            products=["TMP:AGL-2m", "GUST:AGL-10m"],
            captured_at=datetime(2026, 6, 23, 3, 0),
            fetch_text=lambda _url: listing,
        )

        self.assertEqual(payload["source"], "hrdps_datamart_archive")
        self.assertEqual(payload["source_counts"], {"eccc_hrdps": 2})
        self.assertEqual(payload["directory_count"], 69)
        first = payload["rows"][0]
        self.assertEqual(first["market"], "toronto")
        self.assertEqual(first["source"], "eccc_hrdps")
        self.assertEqual(first["model_name"], "HRDPS")
        self.assertEqual(first["valid_time"], "2026-06-23T04:00:00+00:00")
        self.assertEqual(first["minute_of_day"], 0)
        self.assertEqual(first["product"], "TMP")
        self.assertEqual(first["level"], "AGL-2m")
        self.assertEqual(first["payload_bytes"], 4299161)


if __name__ == "__main__":
    unittest.main()
