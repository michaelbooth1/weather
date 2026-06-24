import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from weather.market.market_registry import spec_for_id
from weather.sources.official_guidance_collection import (
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

    def test_collects_toronto_eccc_gem_rows_and_writes_csv(self):
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
        }
        payload = build_official_guidance_collection_payload(sources, spec, "2026-06-15")

        with tempfile.TemporaryDirectory() as tmp:
            result = write_official_guidance_collection_rows(Path(tmp) / "guidance.csv", payload)
            rows = list(csv.DictReader(Path(result["path"]).open(encoding="utf-8", newline="")))

        self.assertEqual(payload["source_counts"], {"eccc_gem": 2})
        self.assertEqual(rows[0]["source_family"], "official_canadian_guidance")
        self.assertEqual(rows[0]["model_name"], "gem_regional")
        self.assertEqual(rows[1]["model_name"], "gem_seamless")
        self.assertEqual(rows[1]["wind_gust_kmh"], "30.0")
        self.assertEqual(result["written_row_count"], 2)

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


if __name__ == "__main__":
    unittest.main()
