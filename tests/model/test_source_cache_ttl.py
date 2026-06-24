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
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

from weather.model.model_sources import request_with_retries
import weather.model.toronto_model as toronto_model
from weather.model.toronto_model import TorontoHighTempModel


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
        self.assertEqual(m.source_cache_ttl_minutes("open_meteo_air_quality"), 120)
        self.assertEqual(m.source_cache_ttl_minutes("open_meteo_global_models"), 120)
        self.assertEqual(m.source_cache_ttl_minutes("nbm_probabilistic_tmax"), 120)
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

    def test_last_good_source_cache_write_uses_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            calls = []

            def fake_atomic(path, payload):
                calls.append((Path(path), payload))
                Path(path).write_text(json.dumps(payload), encoding="utf-8")
                return Path(path)

            payload = {"open_meteo": {"target_date": "2026-05-28", "data": {"marker": 1}}}
            with patch("weather.model.model_sources.write_json_atomic", fake_atomic):
                model.save_last_good_sources(payload)

        self.assertEqual(calls[0][0].name, "last_good_sources.json")
        self.assertEqual(calls[0][1], payload)

    def test_last_good_source_cache_write_merges_with_existing_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "global_ensemble": {
                    "target_date": "2026-05-28",
                    "data": {"marker": "global"},
                }
            }), encoding="utf-8")

            model.save_last_good_sources({
                "wu_current": {
                    "target_date": "2026-05-28",
                    "data": {"marker": "observation"},
                }
            })

            saved = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["global_ensemble"]["data"], {"marker": "global"})
        self.assertEqual(saved["wu_current"]["data"], {"marker": "observation"})

    def test_last_good_source_cache_write_skips_when_writer_lock_is_busy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            original = {
                "global_ensemble": {
                    "target_date": "2026-05-28",
                    "data": {"marker": "global"},
                }
            }
            cache_path.write_text(json.dumps(original), encoding="utf-8")

            with patch("weather.model.model_sources.acquire_writer_lock", return_value=None), \
                    patch("weather.model.model_sources.write_json_atomic") as atomic_write, \
                    self.assertLogs("weather.model.model_sources", level="WARNING") as logs:
                model.save_last_good_sources({
                    "wu_current": {
                        "target_date": "2026-05-28",
                        "data": {"marker": "observation"},
                    }
                })

            saved = json.loads(cache_path.read_text(encoding="utf-8"))
        atomic_write.assert_not_called()
        self.assertEqual(saved, original)
        self.assertIn("writer lock is busy", "\n".join(logs.output))

    def test_corrupt_last_good_source_cache_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text("{broken", encoding="utf-8")

            with self.assertLogs("weather.model.model_sources", level="WARNING") as logs:
                payload = model.load_last_good_sources()

            quarantined = list(model.spec.data_root.glob("last_good_sources.corrupt.*.json"))
            self.assertEqual(payload, {})
            self.assertFalse(cache_path.exists())
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_text(encoding="utf-8"), "{broken")
            self.assertIn("Quarantined invalid last good sources cache", "\n".join(logs.output))

    def test_non_object_last_good_source_cache_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text("[]", encoding="utf-8")

            payload = model.load_last_good_sources()

            self.assertEqual(payload, {})
            self.assertFalse(cache_path.exists())
            self.assertEqual(len(list(model.spec.data_root.glob("last_good_sources.corrupt.*.json"))), 1)

    def test_request_with_retries_uses_retry_after_for_429(self):
        class Response:
            status_code = 429
            headers = {"Retry-After": "2"}

        calls = {"count": 0}
        sleeps = []

        def fetch():
            calls["count"] += 1
            if calls["count"] == 1:
                exc = requests.HTTPError("too many requests")
                exc.response = Response()
                raise exc
            return "ok"

        self.assertEqual(
            request_with_retries(fetch, attempts=2, sleep=sleeps.append),
            "ok",
        )
        self.assertEqual(sleeps, [2.0])

    def test_open_meteo_fresh_cache_reuse_skips_provider_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            now = datetime.now(model.spec.tz)
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "open_meteo": {
                    "target_date": "2026-05-28",
                    "fetched_at": (now - timedelta(minutes=5)).isoformat(),
                    "data": {"marker": 1, "rows": []},
                }
            }), encoding="utf-8")

            def provider_call():
                raise AssertionError("fresh cache should prevent provider call")

            fetched = model.fetch_source_group({
                "open_meteo": model.source_fetcher_with_budget("open_meteo", provider_call),
            })
            blended = model.blend_with_last_good(fetched)

        self.assertEqual(blended["open_meteo"]["status"], "fresh_cache")
        self.assertFalse(blended["open_meteo"]["stale"])
        self.assertEqual(blended["open_meteo"]["source_family"], "open_meteo")
        self.assertEqual(blended["open_meteo"]["cache_status"], "fresh_cache")
        self.assertEqual(blended["open_meteo"]["data"]["marker"], 1)

    def test_open_meteo_cache_reuse_extends_to_source_ttl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            now = datetime.now(model.spec.tz)
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "open_meteo": {
                    "target_date": "2026-05-28",
                    "fetched_at": (now - timedelta(minutes=80)).isoformat(),
                    "data": {"marker": 3, "rows": []},
                }
            }), encoding="utf-8")

            def provider_call():
                raise AssertionError("TTL-valid Open-Meteo cache should prevent provider call")

            fetched = model.fetch_source_group({
                "open_meteo": model.source_fetcher_with_budget("open_meteo", provider_call),
            })
            blended = model.blend_with_last_good(fetched)

        self.assertEqual(blended["open_meteo"]["status"], "fresh_cache")
        self.assertFalse(blended["open_meteo"]["stale"])
        self.assertLessEqual(blended["open_meteo"]["cache_age_minutes"], 90)
        self.assertEqual(blended["open_meteo"]["data"]["marker"], 3)

    def test_open_meteo_cache_reuse_expires_at_source_ttl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            now = datetime.now(model.spec.tz)
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "open_meteo": {
                    "target_date": "2026-05-28",
                    "fetched_at": (now - timedelta(minutes=95)).isoformat(),
                    "data": {"marker": "expired", "rows": []},
                }
            }), encoding="utf-8")
            calls = {"count": 0}

            def provider_call():
                calls["count"] += 1
                return {"marker": "live", "rows": []}

            fetched = model.fetch_source_group({
                "open_meteo": model.source_fetcher_with_budget("open_meteo", provider_call),
            })
            blended = model.blend_with_last_good(fetched)

        self.assertEqual(calls["count"], 1)
        self.assertEqual(blended["open_meteo"]["status"], "fresh")
        self.assertEqual(blended["open_meteo"]["cache_status"], "live")
        self.assertEqual(blended["open_meteo"]["data"]["marker"], "live")

    def test_open_meteo_family_fetches_sequentially_share_same_cycle_cooldown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            model._source_family_rate_limited_until = {}
            calls = {"open_meteo": 0, "eccc_gem": 0}

            class Response:
                status_code = 429
                headers = {"Retry-After": "60"}

            def open_meteo_call():
                calls["open_meteo"] += 1
                exc = requests.HTTPError("too many requests")
                exc.response = Response()
                raise exc

            def eccc_gem_call():
                calls["eccc_gem"] += 1
                return {"marker": "should not be called"}

            fetched = model.fetch_live_source_groups({
                "open_meteo": model.source_fetcher_with_budget("open_meteo", open_meteo_call),
                "eccc_gem": model.source_fetcher_with_budget("eccc_gem", eccc_gem_call),
            })

        self.assertEqual(calls, {"open_meteo": 1, "eccc_gem": 0})
        self.assertFalse(fetched["open_meteo"]["ok"])
        self.assertFalse(fetched["eccc_gem"]["ok"])
        self.assertEqual(fetched["open_meteo"]["status"], "rate_limited")
        self.assertEqual(fetched["eccc_gem"]["status"], "rate_limited")
        self.assertEqual(fetched["eccc_gem"]["cache_status"], "provider_cooldown")

    def test_open_meteo_same_cycle_cooldown_still_serves_ttl_valid_family_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            model._source_family_rate_limited_until = {}
            now = datetime.now(model.spec.tz)
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "eccc_gem": {
                    "target_date": "2026-05-28",
                    "fetched_at": (now - timedelta(minutes=80)).isoformat(),
                    "data": {"marker": "cached-gem"},
                }
            }), encoding="utf-8")
            calls = {"open_meteo": 0, "eccc_gem": 0}

            class Response:
                status_code = 429
                headers = {"Retry-After": "60"}

            def open_meteo_call():
                calls["open_meteo"] += 1
                exc = requests.HTTPError("too many requests")
                exc.response = Response()
                raise exc

            def eccc_gem_call():
                calls["eccc_gem"] += 1
                raise AssertionError("TTL-valid ECCC GEM cache should skip provider call")

            fetched = model.fetch_live_source_groups({
                "open_meteo": model.source_fetcher_with_budget("open_meteo", open_meteo_call),
                "eccc_gem": model.source_fetcher_with_budget("eccc_gem", eccc_gem_call),
            })

        self.assertEqual(calls, {"open_meteo": 1, "eccc_gem": 0})
        self.assertFalse(fetched["open_meteo"]["ok"])
        self.assertTrue(fetched["eccc_gem"]["ok"])
        self.assertEqual(fetched["eccc_gem"]["status"], "fresh_cache")
        self.assertEqual(fetched["eccc_gem"]["data"]["marker"], "cached-gem")

    def test_eccc_swob_skips_missing_latest_file_from_directory_index(self):
        model = TorontoHighTempModel(target_date="2026-06-19")
        model.target_date = date(2026, 6, 19)
        model.target_date_str = "20260619"

        class Response:
            def __init__(self, text="", status_code=200):
                self.text = text
                self.status_code = status_code
                self.headers = {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    exc = requests.HTTPError(f"{self.status_code} error")
                    exc.response = self
                    raise exc

        index_html = """
        <html>
          <a href="2026-06-19-2200-CYYZ-MAN-swob.xml">2200</a>
          <a href="2026-06-19-2300-CYYZ-MAN-swob.xml">2300</a>
        </html>
        """
        xml_2200 = """
        <root>
          <value name="date_tm" value="2026-06-19T22:00:00Z" />
          <value name="air_temp" value="21.5" />
          <value name="max_air_temp_pst1hr" value="22.0" />
        </root>
        """

        def fake_get(url, timeout=None, **_kwargs):
            if url.endswith("/CYYZ/"):
                return Response(index_html)
            if url.endswith("2026-06-19-2200-CYYZ-MAN-swob.xml"):
                return Response(xml_2200)
            if url.endswith("2026-06-19-2300-CYYZ-MAN-swob.xml"):
                return Response(status_code=404)
            raise AssertionError(f"unexpected URL: {url}")

        with patch("weather.model.model_sources.requests.get", side_effect=fake_get):
            payload = model.fetch_eccc_swob()

        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["latest"]["time"], "2026-06-19T22:00:00Z")
        self.assertEqual(payload["same_day_max_c"], 21.5)
        self.assertEqual(payload["skipped_missing_file_count"], 1)
        self.assertEqual(payload["skipped_missing_files"], ["2026-06-19-2300-CYYZ-MAN-swob.xml"])
        self.assertEqual(payload["raw_payload"]["source"], "eccc_swob")
        self.assertEqual(payload["raw_payload"]["base_url"].split("/")[-2], "CYYZ")
        self.assertEqual(payload["raw_payload"]["files"][0]["filename"], "2026-06-19-2200-CYYZ-MAN-swob.xml")
        self.assertIn("max_air_temp_pst1hr", payload["raw_payload"]["files"][0]["text"])
        self.assertEqual(payload["raw_payload"]["skipped_missing_files"], ["2026-06-19-2300-CYYZ-MAN-swob.xml"])

    def test_wu_current_carries_raw_payload_for_observation_sidecar(self):
        model = TorontoHighTempModel(target_date="2026-06-24", market_id="atlanta")
        raw = {
            "validTimeLocal": "2026-06-24T10:00:00-0400",
            "temperature": 82,
            "temperatureMax24Hour": 84,
            "temperatureMaxSince7Am": 83,
            "temperatureDewPoint": 70,
            "relativeHumidity": 66,
            "cloudCover": 25,
            "wxPhraseLong": "Partly Cloudy",
            "windSpeed": 8,
        }
        model.get_json = lambda _url, _params: raw

        payload = model.fetch_wu_current()

        self.assertEqual(payload["temp_native"], 82)
        self.assertEqual(payload["raw_payload"], raw)

    def test_metar_carries_raw_payload_for_observation_sidecar(self):
        model = TorontoHighTempModel(target_date="2026-06-24", market_id="atlanta")
        raw = [{
            "reportTime": "2026-06-24T14:52:00Z",
            "temp": 28.0,
            "dewp": 20.0,
            "wdir": 210,
            "wspd": 8,
            "rawOb": "KATL 241452Z 21008KT 10SM FEW040 28/20 A3000",
        }]
        model.get_json = lambda _url, _params: raw

        payload = model.fetch_metar()

        self.assertEqual(payload["raw_payload"], raw)
        self.assertEqual(payload["raw"], raw[0]["rawOb"])

    def test_rate_limited_open_meteo_uses_explicit_cache_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)
            now = datetime.now(model.spec.tz)
            cache_path = model.spec.data_root / "last_good_sources.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                "open_meteo": {
                    "target_date": "2026-05-28",
                    "fetched_at": (now - timedelta(minutes=45)).isoformat(),
                    "data": {"marker": 2, "rows": []},
                }
            }), encoding="utf-8")

            blended = model.blend_with_last_good({
                "open_meteo": {
                    "ok": False,
                    "status": "rate_limited",
                    "source_family": "open_meteo",
                    "http_status": 429,
                    "retry_after_seconds": 60.0,
                    "error": "too many requests",
                    "fetched_at": now.isoformat(),
                }
            })

        self.assertTrue(blended["open_meteo"]["ok"])
        self.assertTrue(blended["open_meteo"]["stale"])
        self.assertEqual(blended["open_meteo"]["status"], "rate_limited_cache")
        self.assertEqual(blended["open_meteo"]["http_status"], 429)
        self.assertEqual(blended["open_meteo"]["degradation_state"], "rate_limited_fallback")
        self.assertEqual(blended["open_meteo"]["cache_status"], "fallback")
        self.assertEqual(blended["open_meteo"]["data"]["marker"], 2)

    def test_toronto_forecast_source_failures_remain_independent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model = TorontoHighTempModel(target_date="2026-05-28")
            model.spec = SimpleNamespace(data_root=Path(tmpdir), tz=ZoneInfo("UTC"))
            model.target_date = date(2026, 5, 28)

            def fail(message):
                def _inner():
                    raise RuntimeError(message)
                return _inner

            fetched = model.fetch_source_group({
                "eccc_swob": fail("swob offline"),
                "eccc_citypage": fail("citypage offline"),
                "eccc_gem": fail("gem offline"),
                "weather_forecast": fail("weather forecast offline"),
                "open_meteo": fail("open meteo offline"),
                "wu_current": lambda: {"temp_native": 21.0},
            })
            blended = model.blend_with_last_good(fetched)

        self.assertTrue(blended["wu_current"]["ok"])
        self.assertEqual(blended["eccc_swob"]["status"], "failed")
        self.assertEqual(blended["eccc_citypage"]["status"], "failed")
        self.assertEqual(blended["eccc_gem"]["status"], "failed")
        self.assertEqual(blended["weather_forecast"]["status"], "failed")
        self.assertEqual(blended["open_meteo"]["status"], "failed")
        self.assertIn("swob offline", blended["eccc_swob"]["error"])
        self.assertIn("citypage offline", blended["eccc_citypage"]["error"])
        self.assertIn("gem offline", blended["eccc_gem"]["error"])
        self.assertIn("weather forecast offline", blended["weather_forecast"]["error"])
        self.assertIn("open meteo offline", blended["open_meteo"]["error"])

    def test_toronto_official_source_health_warns_late_day_degradation(self):
        model = TorontoHighTempModel(target_date="2026-06-16", market_id="toronto")
        now = datetime(2026, 6, 16, 16, 0, tzinfo=model.spec.tz)
        sources = {
            "eccc_swob": {"ok": False, "status": "failed", "error": "swob offline"},
            "eccc_citypage": {"ok": True, "status": "fresh", "stale": False},
            "eccc_gem": {"ok": True, "status": "stale_cache", "stale": True},
        }

        health = model.toronto_official_source_health(sources, now=now)

        self.assertEqual(health["status"], "WARN")
        self.assertTrue(health["late_day_lockin_window"])
        self.assertEqual(health["official_sources_available"], 1)
        self.assertEqual(health["missing_sources"], ["eccc_swob", "eccc_gem"])

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
