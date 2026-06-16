"""Item 17: per-source last-good cache TTLs + structured source diagnostics.

A single global 90-minute cap treated a stale settlement observation the same as
a stale slow-moving forecast. Now observation/settlement sources expire fast and
forecasts keep a longer stale window, and partial failures are queryable.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

import toronto_model
from toronto_model import TorontoHighTempModel


class TestSourceCacheTtl(unittest.TestCase):
    def test_ttl_map_values_and_fallback(self):
        m = TorontoHighTempModel()
        # Observations expire fast; forecasts keep the longer window.
        self.assertEqual(m.source_cache_ttl_minutes("wu_current"), 30)
        self.assertEqual(m.source_cache_ttl_minutes("wu_history"), 30)
        self.assertEqual(m.source_cache_ttl_minutes("eccc_swob"), 30)
        self.assertEqual(m.source_cache_ttl_minutes("metar"), 75)
        self.assertEqual(m.source_cache_ttl_minutes("marine_context"), 75)
        self.assertEqual(m.source_cache_ttl_minutes("mrms_precip"), 20)
        self.assertEqual(m.source_cache_ttl_minutes("open_meteo"), 90)
        self.assertEqual(m.source_cache_ttl_minutes("nws_grid"), 90)
        self.assertEqual(m.source_cache_ttl_minutes("eccc_citypage"), 120)
        self.assertEqual(m.source_cache_ttl_minutes("eccc_gem"), 120)
        self.assertEqual(m.source_cache_ttl_minutes("open_meteo_multimodel"), 120)
        # Unknown source falls back to the global cap.
        self.assertEqual(m.source_cache_ttl_minutes("mystery"), 90)

    def _blend_with_cached(self, source, age_minutes, fail=True):
        """Blend a failing fetch against a last-good cache of the given age."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_root = toronto_model.DEFAULT_DATA_ROOT
            toronto_model.DEFAULT_DATA_ROOT = Path(tmpdir)
            try:
                model = TorontoHighTempModel(target_date="2026-05-28")
                now = datetime.now(model.spec.tz)
                cache_path = model.spec.data_root / "last_good_sources.json"
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps({
                    source: {
                        "target_date": "2026-05-28",
                        "fetched_at": (now - timedelta(minutes=age_minutes)).isoformat(),
                        "data": {"marker": 1},
                    }
                }), encoding="utf-8")
                fetched = {source: {"ok": False, "error": "feed failed",
                                    "fetched_at": now.isoformat()}}
                return model.blend_with_last_good(fetched)
            finally:
                toronto_model.DEFAULT_DATA_ROOT = old_root

    def test_stale_observation_dropped_past_short_ttl(self):
        # 45 min is within the OLD global 90-min cap but past wu_current's 30-min
        # TTL, so the stale observation is now correctly dropped.
        blended = self._blend_with_cached("wu_current", 45)
        self.assertFalse(blended["wu_current"]["ok"])
        self.assertEqual(blended["wu_current"]["status"], "failed")
        self.assertEqual(blended["wu_current"]["data"], {})
        self.assertEqual(blended["wu_current"]["ttl_minutes"], 30)

    def test_stale_forecast_served_within_long_ttl(self):
        # The same 45-min-old cache is still served for a slow forecast source.
        blended = self._blend_with_cached("open_meteo", 45)
        self.assertTrue(blended["open_meteo"]["ok"])
        self.assertTrue(blended["open_meteo"]["stale"])
        self.assertEqual(blended["open_meteo"]["status"], "stale_cache")
        self.assertEqual(blended["open_meteo"]["data"], {"marker": 1})
        self.assertEqual(blended["open_meteo"]["ttl_minutes"], 90)

    def test_fresh_fetch_marked_fresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_root = toronto_model.DEFAULT_DATA_ROOT
            toronto_model.DEFAULT_DATA_ROOT = Path(tmpdir)
            try:
                model = TorontoHighTempModel(target_date="2026-05-28")
                now = datetime.now(model.spec.tz).isoformat()
                blended = model.blend_with_last_good({
                    "open_meteo": {"ok": True, "data": {"rows": []}, "fetched_at": now}
                })
            finally:
                toronto_model.DEFAULT_DATA_ROOT = old_root
        self.assertEqual(blended["open_meteo"]["status"], "fresh")
        self.assertFalse(blended["open_meteo"]["stale"])

    def test_fetch_source_group_records_latency_for_success_and_failure(self):
        model = TorontoHighTempModel()

        def fail():
            raise RuntimeError("boom")

        fetched = model.fetch_source_group({
            "open_meteo": lambda: {"rows": []},
            "wu_current": fail,
        })

        self.assertTrue(fetched["open_meteo"]["ok"])
        self.assertIn("latency_ms", fetched["open_meteo"])
        self.assertFalse(fetched["wu_current"]["ok"])
        self.assertIn("latency_ms", fetched["wu_current"])

    def test_source_diagnostics_structured(self):
        m = TorontoHighTempModel()
        now = datetime.now(m.spec.tz).isoformat()
        blended = {
            "open_meteo": {"ok": True, "stale": False, "status": "fresh", "fetched_at": now, "data": {}},
            "wu_current": {"ok": False, "stale": False, "status": "failed",
                           "fetched_at": now, "ttl_minutes": 30, "error": "boom", "data": {}},
        }
        diags = m.source_diagnostics(blended)
        by_source = {d["source"]: d for d in diags}
        self.assertEqual(by_source["open_meteo"]["status"], "fresh")
        self.assertEqual(by_source["open_meteo"]["ttl_minutes"], 90)
        self.assertEqual(by_source["wu_current"]["status"], "failed")
        self.assertEqual(by_source["wu_current"]["ttl_minutes"], 30)
        self.assertEqual(by_source["wu_current"]["error"], "boom")

    def test_diagnostics_infers_status_when_absent(self):
        # Older blended payloads (pre-item-17) lack an explicit status field.
        m = TorontoHighTempModel()
        blended = {"metar": {"ok": True, "stale": True, "fetched_at": None, "data": {}}}
        diags = m.source_diagnostics(blended)
        self.assertEqual(diags[0]["status"], "stale_cache")
        self.assertEqual(diags[0]["ttl_minutes"], 75)

    def test_marine_context_diagnostics_include_only_gated_active_state(self):
        m = TorontoHighTempModel()
        blended = {
            "marine_context": {"ok": True, "stale": False, "status": "fresh", "data": {
                "market": "toronto",
                "stations": [{
                    "station_id": "45159",
                    "usable": True,
                    "latest_age_minutes": 12,
                    "missing_sensors": [],
                    "distance_km": 43,
                    "onshore_direction_min": 60.0,
                    "onshore_direction_max": 160.0,
                    "latest": {
                        "water_temp_native": 14.0,
                        "air_temp_native": 18.0,
                        "wind_speed_kmh": 16.0,
                        "wind_direction_degrees": 120.0,
                    },
                    "rows": [],
                }],
            }},
        }

        by_source = {row["source"]: row for row in m.source_diagnostics(blended)}
        inactive = m.source_diagnostics({"marine_context": {"ok": True, "stale": False, "status": "fresh", "data": {
            "market": "toronto",
            "stations": [{"station_id": "45159", "usable": False, "latest": {}}],
        }}})

        self.assertEqual(by_source["marine_context"]["marine_context"]["regime"], "breeze_risk")
        self.assertNotIn("marine_context", inactive[0])


if __name__ == "__main__":
    unittest.main()
