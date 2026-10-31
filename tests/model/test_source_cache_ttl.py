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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import requests

from weather.model.model_sources import request_with_retries
from weather.model.source_adapters import SourceExpectedUnavailable
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

    def test_scoped_cache_does_not_migrate_or_read_large_legacy_forecast_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_path = root / "legacy" / "last_good_sources.json"
            dedicated_path = root / "observation" / "market-a.json"
            legacy_path.parent.mkdir(parents=True)
            large_nbm_text = "N" * (4 * 1024 * 1024)
            legacy_path.write_text(json.dumps({
                "metar": {
                    "target_date": "2026-05-28",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "data": {"marker": "must_not_migrate"},
                },
                "nbm_probabilistic_tmax": {
                    "target_date": "2026-05-28",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "data": {"raw_payload": {"text": large_nbm_text}},
                },
            }), encoding="utf-8")
            del large_nbm_text

            model = TorontoHighTempModel(
                target_date="2026-05-28",
                source_cache_path=dedicated_path,
                source_cache_names=("wu_history", "wu_current", "metar", "eccc_swob"),
                source_cache_max_bytes=1024 * 1024,
            )
            model.spec = SimpleNamespace(data_root=legacy_path.parent, tz=ZoneInfo("UTC"))
            now = datetime.now(timezone.utc)
            original_open = Path.open

            def guarded_open(path, *args, **kwargs):
                if Path(path) == legacy_path:
                    raise AssertionError("scoped observation cache must not read the legacy cache")
                return original_open(path, *args, **kwargs)

            failed_fetch = {
                "metar": {
                    "ok": False,
                    "error": "provider unavailable",
                    "fetched_at": now.isoformat(),
                }
            }
            with patch.object(Path, "open", guarded_open):
                first = model.blend_with_last_good(failed_fetch)
                live = model.blend_with_last_good({
                    "metar": {
                        "ok": True,
                        "data": {"marker": "dedicated"},
                        "fetched_at": now.isoformat(),
                    }
                })
                fallback = model.blend_with_last_good(failed_fetch)

            dedicated = json.loads(dedicated_path.read_text(encoding="utf-8"))

        self.assertFalse(first["metar"]["ok"])
        self.assertEqual(first["metar"]["data"], {})
        self.assertEqual(live["metar"]["data"], {"marker": "dedicated"})
        self.assertTrue(fallback["metar"]["ok"])
        self.assertTrue(fallback["metar"]["stale"])
        self.assertEqual(fallback["metar"]["data"], {"marker": "dedicated"})
        self.assertEqual(set(dedicated), {"metar"})
        self.assertLess(len(json.dumps(dedicated).encode("utf-8")), 2048)

    def test_scoped_source_caches_do_not_cross_contaminate_markets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            now = datetime.now(timezone.utc)
            models = []
            for market_id in ("market-a", "market-b"):
                model = TorontoHighTempModel(
                    target_date="2026-05-28",
                    source_cache_path=root / f"{market_id}.json",
                    source_cache_names=("metar",),
                    source_cache_max_bytes=1024 * 1024,
                )
                model.spec = SimpleNamespace(data_root=root / "legacy", tz=ZoneInfo("UTC"))
                model.save_last_good_sources({
                    "metar": {
                        "target_date": "2026-05-28",
                        "fetched_at": now.isoformat(),
                        "data": {"market": market_id},
                    }
                })
                models.append(model)

            outputs = [
                model.blend_with_last_good({
                    "metar": {
                        "ok": False,
                        "error": "provider unavailable",
                        "fetched_at": now.isoformat(),
                    }
                })
                for model in models
            ]

        self.assertEqual(outputs[0]["metar"]["data"], {"market": "market-a"})
        self.assertEqual(outputs[1]["metar"]["data"], {"market": "market-b"})

    def test_scoped_cache_quarantines_out_of_scope_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "market-a.json"
            cache_path.write_text(json.dumps({
                "nbm_probabilistic_tmax": {"data": {"marker": "forecast"}}
            }), encoding="utf-8")
            model = TorontoHighTempModel(
                target_date="2026-05-28",
                source_cache_path=cache_path,
                source_cache_names=("metar",),
                source_cache_max_bytes=1024 * 1024,
            )

            payload = model.load_last_good_sources()
            quarantined = list(cache_path.parent.glob("market-a.corrupt.*.json"))

        self.assertEqual(payload, {})
        self.assertFalse(cache_path.exists())
        self.assertEqual(len(quarantined), 1)

    def test_scoped_cache_rejects_oversize_payload_before_json_materialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "market-a.json"
            cache_path.write_bytes(b"{" + b"N" * 4096 + b"}")
            model = TorontoHighTempModel(
                target_date="2026-05-28",
                source_cache_path=cache_path,
                source_cache_names=("metar",),
                source_cache_max_bytes=1024,
            )

            with patch("weather.model.model_sources.json.load") as json_load:
                payload = model.load_last_good_sources()

            quarantined = list(cache_path.parent.glob("market-a.corrupt.*.json"))

        json_load.assert_not_called()
        self.assertEqual(payload, {})
        self.assertFalse(cache_path.exists())
        self.assertEqual(len(quarantined), 1)

    def test_scoped_cache_rejects_oversize_write_before_atomic_whole_document_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "market-a.json"
            model = TorontoHighTempModel(
                target_date="2026-05-28",
                source_cache_path=cache_path,
                source_cache_names=("metar",),
                source_cache_max_bytes=1024,
            )
            payload = {
                "metar": {
                    "target_date": "2026-05-28",
                    "data": {"raw_payload": "M" * 4096},
                }
            }

            with patch("weather.model.model_sources.write_json_atomic") as atomic_write, \
                    self.assertLogs("weather.model.model_sources", level="WARNING") as logs:
                model.save_last_good_sources(payload)

        atomic_write.assert_not_called()
        self.assertFalse(cache_path.exists())
        self.assertIn("exceeds 1024 byte scope limit", "\n".join(logs.output))

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

    def test_open_meteo_cooldown_is_shared_across_isolated_capture_process_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cooldown_path = Path(tmpdir) / "source_family_cooldown.json"
            first_process = TorontoHighTempModel(target_date="2026-05-28")
            first_process._source_family_rate_limited_until = {}
            second_process = TorontoHighTempModel(target_date="2026-05-28")
            second_process._source_family_rate_limited_until = {}

            with patch.dict(
                os.environ,
                {"WEATHER_SOURCE_FAMILY_COOLDOWN_PATH": str(cooldown_path)},
            ):
                first_process.record_source_family_rate_limit(
                    "open_meteo",
                    retry_after_seconds=90,
                )
                state = second_process.source_family_rate_limit_state("open_meteo")

            payload = json.loads(cooldown_path.read_text(encoding="utf-8"))

        self.assertTrue(state["active"])
        self.assertGreater(state["retry_after_seconds"], 60)
        self.assertIn("open_meteo", payload)

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

    def test_wu_current_paid_provider_path_is_disabled_before_network(self):
        model = TorontoHighTempModel(target_date="2026-06-24", market_id="atlanta")
        called = False

        def fail_get_json(_url, _params):
            nonlocal called
            called = True
            raise AssertionError("disabled paid-provider path must not call get_json")

        model.get_json = fail_get_json

        with self.assertRaises(SourceExpectedUnavailable) as raised:
            model.fetch_wu_current()

        self.assertFalse(called)
        self.assertEqual(raised.exception.status, "paid_provider_disabled")
        self.assertEqual(raised.exception.cache_status, "expected_unavailable")

    def test_metar_carries_raw_payload_for_observation_sidecar(self):
        model = TorontoHighTempModel(target_date="2026-06-24", market_id="atlanta")
        raw = [{
            "reportTime": "2026-06-24T14:52:00Z",
            "temp": 28.0,
            "dewp": 20.0,
            "wdir": 210,
            "wspd": 8,
            "rh": 58.0,
            "altim": 1015.9,
            "slp": 1014.6,
            "rawOb": "KATL 241452Z 21008KT 10SM FEW040 28/20 A3000",
        }]
        model.get_json = lambda _url, _params: raw

        payload = model.fetch_metar()

        self.assertEqual(payload["raw_payload"], raw)
        self.assertEqual(payload["raw"], raw[0]["rawOb"])
        self.assertEqual(len(payload["rows"]), 1)
        self.assertAlmostEqual(payload["temp_native"], 82.4)
        self.assertAlmostEqual(payload["max_since_7am_native"], 82.4)
        self.assertEqual(payload["humidity"], 58.0)
        self.assertEqual(payload["pressure_hpa"], 1015.9)
        self.assertEqual(payload["sea_level_pressure_hpa"], 1014.6)
        self.assertNotIn("pressure", payload["rows"][0])

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


# --- Last-good cache keeps the national NBM bulletin by shared-CAS reference ---

_NBP_TEXT = """
 KBOS    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNMN  70  58| 73  62
TXNSD   2   2|  3   3
TXNP1  67  55| 69  58
TXNP2  68  56| 71  59
TXNP5  70  58| 73  62
TXNP7  71  59| 75  64
TXNP9  73  61| 77  66

 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNMN  84  68| 79  68
TXNSD   2   2|  4   3
TXNP1  81  64| 73  63
TXNP2  82  66| 76  66
TXNP5  84  68| 80  69
TXNP7  85  69| 82  71
TXNP9  86  70| 84  72
"""
_NBP_URL = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
    "blend.20260530/00/text/blend_nbptx.t00z"
)
_NBM = "nbm_probabilistic_tmax"


def _nbm_model(tmp_path, monkeypatch, *, cas=True):
    import weather.model.model_sources as model_sources
    from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
    from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax

    monkeypatch.setattr(toronto_model, "DEFAULT_DATA_ROOT", tmp_path / "wu")
    # Readers without an injected CAS use the fleet default root.
    monkeypatch.setattr(model_sources, "SHARED_FORECAST_PAYLOAD_CAS_ROOT", tmp_path / "default-cas")
    monkeypatch.setattr(model_sources, "_LAST_GOOD_RESTORE_FAILURES_LOGGED", set())
    monkeypatch.setattr(model_sources, "_LAST_GOOD_DECLARATION_MISMATCHES_LOGGED", set())
    model = TorontoHighTempModel(target_date="2026-05-30")
    if cas:
        model.shared_forecast_payload_cas = SharedForecastPayloadCAS(tmp_path / "cas")
    data = parse_nbp_station_tmax(
        _NBP_TEXT,
        "KLGA",
        "2026-05-30",
        source_url=_NBP_URL,
        fetched_at="2026-05-30T01:00:00+00:00",
    )
    return model, data


def _cache_file(model):
    return json.loads(model.last_good_sources_path().read_text(encoding="utf-8"))


def _fresh(model, data):
    now = datetime.now(model.spec.tz).isoformat()
    return model.blend_with_last_good({_NBM: {"ok": True, "data": data, "fetched_at": now}})


def _failed(model):
    now = datetime.now(model.spec.tz).isoformat()
    return model.blend_with_last_good(
        {_NBM: {"ok": False, "error": "feed failed", "fetched_at": now}}
    )


def test_save_replaces_bulletin_with_cas_ref_without_mutating_served_data(tmp_path, monkeypatch):
    import copy
    import hashlib

    model, data = _nbm_model(tmp_path, monkeypatch)
    original = copy.deepcopy(data)
    body = _NBP_TEXT.encode("utf-8")
    model.shared_forecast_payload_cas.put(body)

    blended = _fresh(model, data)

    # The served object is the fetched object and still carries its body.
    assert blended[_NBM]["data"] is data
    assert data == original
    stored_raw = _cache_file(model)[_NBM]["data"]["raw_payload"]
    digest = hashlib.sha256(body).hexdigest()
    assert "text" not in stored_raw
    assert stored_raw["text_ref"] == {
        "cas": "shared_forecast_payload",
        "payload_hash_algorithm": "sha256",
        "payload_hash": digest,
        "payload_ref": f"sha256/{digest[:2]}/{digest}.blob",
        "payload_bytes": len(body),
        "body_field": "text",
    }
    for kept in ("payload_hash", "source_url", "forecast_payload_attestation", "raw_station_block"):
        if kept in original["raw_payload"]:
            assert stored_raw[kept] == original["raw_payload"][kept]


def test_failed_fetch_restores_referenced_bulletin_exactly(tmp_path, monkeypatch):
    import copy

    model, data = _nbm_model(tmp_path, monkeypatch)
    original = copy.deepcopy(data)
    model.shared_forecast_payload_cas.put(_NBP_TEXT.encode("utf-8"))
    _fresh(model, data)

    blended = _failed(model)

    assert blended[_NBM]["ok"] is True
    assert blended[_NBM]["cache_status"] == "fallback"
    assert blended[_NBM]["data"] == original
    # The cache itself stays a reference after the fallback pass saved it.
    assert "text" not in _cache_file(model)[_NBM]["data"]["raw_payload"]


@pytest.mark.parametrize(
    "damage", ["missing_blob", "corrupt_blob", "sha1_mismatch", "default_root_without_blob"]
)
def test_unprovable_bulletin_reference_is_a_cache_miss(tmp_path, monkeypatch, caplog, damage):
    model, data = _nbm_model(tmp_path, monkeypatch)
    stored = model.shared_forecast_payload_cas.put(_NBP_TEXT.encode("utf-8"))
    _fresh(model, data)
    blob = Path(stored["path"])
    if damage == "missing_blob":
        blob.unlink()
    elif damage == "corrupt_blob":
        blob.write_bytes(b"x" * stored["payload_bytes"])
    elif damage == "sha1_mismatch":
        cache = _cache_file(model)
        cache[_NBM]["data"]["raw_payload"]["payload_hash"] = "0" * 40
        model.last_good_sources_path().write_text(json.dumps(cache), encoding="utf-8")
    else:
        model.shared_forecast_payload_cas = None

    with caplog.at_level("WARNING", logger="weather.model.model_sources"):
        blended = _failed(model)
        again = _failed(model)

    for result in (blended, again):
        assert result[_NBM]["ok"] is False
        assert result[_NBM]["status"] == "failed"
        # Distinct from a TTL miss.
        assert result[_NBM]["cache_status"] == "fallback_unprovable"
        assert result[_NBM]["data"] == {}
        assert "Last good payload reference could not be restored" in result[_NBM]["error"]
    # Logged once per digest, not on every pass.
    restore_logs = [r for r in caplog.records if "could not be restored" in r.getMessage()]
    assert len(restore_logs) == 1
    assert stored["payload_hash"] in restore_logs[0].getMessage()


def test_expired_referenced_entry_is_an_ordinary_ttl_miss(tmp_path, monkeypatch):
    model, data = _nbm_model(tmp_path, monkeypatch)
    model.shared_forecast_payload_cas.put(_NBP_TEXT.encode("utf-8"))
    _fresh(model, data)
    cache = _cache_file(model)
    cache[_NBM]["fetched_at"] = (datetime.now(model.spec.tz) - timedelta(hours=5)).isoformat()
    model.last_good_sources_path().write_text(json.dumps(cache), encoding="utf-8")

    blended = _failed(model)

    assert blended[_NBM]["cache_status"] == "miss"
    assert "could not be restored" not in blended[_NBM]["error"]


def test_legacy_inline_cache_is_served_then_shrunk_on_next_save(tmp_path, monkeypatch):
    import copy

    model, data = _nbm_model(tmp_path, monkeypatch)
    original = copy.deepcopy(data)
    model.shared_forecast_payload_cas.put(_NBP_TEXT.encode("utf-8"))
    cache_path = model.last_good_sources_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({_NBM: {
        "target_date": "2026-05-30",
        "fetched_at": datetime.now(model.spec.tz).isoformat(),
        "data": data,
    }}), encoding="utf-8")

    blended = _failed(model)

    assert blended[_NBM]["ok"] is True
    assert blended[_NBM]["data"] == original
    stored_raw = _cache_file(model)[_NBM]["data"]["raw_payload"]
    assert "text" not in stored_raw
    assert stored_raw["text_ref"]["payload_bytes"] == len(_NBP_TEXT.encode("utf-8"))


@pytest.mark.parametrize("cas", [True, False])
def test_bulletin_stays_inline_without_a_confirmed_blob(tmp_path, monkeypatch, cas):
    # cas=False: no injected CAS, and the default root holds no blob.
    model, data = _nbm_model(tmp_path, monkeypatch, cas=cas)
    if cas:
        # A blob of the wrong size under the right digest is not confirmation.
        import hashlib

        digest = hashlib.sha256(_NBP_TEXT.encode("utf-8")).hexdigest()
        path = model.shared_forecast_payload_cas.path_for(digest)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"short")

    _fresh(model, data)

    stored_raw = _cache_file(model)[_NBM]["data"]["raw_payload"]
    assert stored_raw["text"] == _NBP_TEXT
    assert "text_ref" not in stored_raw


def test_reader_without_injected_cas_uses_the_default_root(tmp_path, monkeypatch):
    from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS

    model, data = _nbm_model(tmp_path, monkeypatch, cas=False)
    SharedForecastPayloadCAS(tmp_path / "default-cas").put(_NBP_TEXT.encode("utf-8"))
    _fresh(model, data)
    assert "text_ref" in _cache_file(model)[_NBM]["data"]["raw_payload"]

    blended = _failed(model)

    assert blended[_NBM]["cache_status"] == "fallback"
    assert blended[_NBM]["data"]["raw_payload"]["text"] == _NBP_TEXT


@pytest.mark.parametrize("declaration", ["matching", "decoy"])
def test_prepublished_declaration_is_only_a_cross_check(tmp_path, monkeypatch, caplog, declaration):
    import hashlib

    model, data = _nbm_model(tmp_path, monkeypatch)
    cas = model.shared_forecast_payload_cas
    body = _NBP_TEXT.encode("utf-8")
    stored = cas.put(body)
    # A same-size blob with other bytes: trusting a declaration that names it
    # would make the reference point at the wrong bulletin.
    decoy = cas.put(b"x" * len(body))
    declared = stored if declaration == "matching" else decoy
    data["raw_payload"]["forecast_payload_attestation"]["single_fetch"] = {
        "prepublished_payload_hash": declared["payload_hash"],
        "prepublished_payload_ref": declared["payload_ref"],
        "prepublished_payload_bytes": declared["payload_bytes"],
    }

    with caplog.at_level("WARNING", logger="weather.model.model_sources"):
        _fresh(model, data)
        _fresh(model, data)

    text_ref = _cache_file(model)[_NBM]["data"]["raw_payload"]["text_ref"]
    assert text_ref["payload_hash"] == hashlib.sha256(body).hexdigest()
    assert text_ref["payload_ref"] == stored["payload_ref"]
    # A disagreeing declaration is logged once per digest, not every save.
    mismatch_logs = [r for r in caplog.records if "declaration disagrees" in r.getMessage()]
    assert len(mismatch_logs) == (1 if declaration == "decoy" else 0)
    assert _failed(model)[_NBM]["data"]["raw_payload"]["text"] == _NBP_TEXT


if __name__ == "__main__":
    unittest.main()
