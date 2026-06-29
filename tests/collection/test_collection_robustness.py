import os
import sys
import tempfile
import unittest
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import pandas as pd
from weather.collection.redaction import has_unredacted_sensitive_url_parts, redact_sensitive_url_parts
import weather.collection.snapshot_tracker as tracker  # noqa: E402
from weather.model.model_sources import request_with_retries, _is_retryable
from weather.collection.snapshot_tracker import SnapshotStore, loop_health, run_loop
from weather.collection.collection_health import (
    detect_gaps,
    coverage_summary,
    fleet_capture_liveness,
    live_coverage_summary,
    latest_market_folder,
    parse_times,
    source_family_degradation,
    summarize_folder,
)
from weather.market.market_config import config_for_date
from weather.market.market_registry import spec_for_id


class TestRetries(unittest.TestCase):
    def test_succeeds_after_transient_failures(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.ConnectionError("blip")
            return "ok"

        slept = []
        out = request_with_retries(fn, attempts=3, base_delay=0.01, sleep=slept.append)
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(slept), 2)  # backoff between the 3 attempts

    def test_gives_up_after_attempts(self):
        with self.assertRaises(requests.Timeout):
            request_with_retries(lambda: (_ for _ in ()).throw(requests.Timeout("slow")),
                                 attempts=2, base_delay=0.0, sleep=lambda s: None)

    def test_non_retryable_raises_immediately(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("bad")

        with self.assertRaises(ValueError):
            request_with_retries(fn, attempts=3, sleep=lambda s: None)
        self.assertEqual(calls["n"], 1)  # not retried

    def test_http_5xx_retryable_4xx_not(self):
        e503 = requests.HTTPError()
        e503.response = SimpleNamespace(status_code=503)
        e404 = requests.HTTPError()
        e404.response = SimpleNamespace(status_code=404)
        self.assertTrue(_is_retryable(e503))
        self.assertFalse(_is_retryable(e404))


class TestLoopHealth(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 5, 30, 14, 0)

    def _status(self, **kw):
        base = {"interval_minutes": 10.0, "last_heartbeat": self.now.isoformat(),
                "consecutive_errors": 0, "pid": 123}
        base.update(kw)
        return base

    def test_unknown_when_no_status(self):
        self.assertEqual(loop_health(None, self.now)["state"], "UNKNOWN")

    def test_capture_liveness_pending_market_is_not_an_alarm(self):
        # A western market whose afternoon window has not started is PENDING; it
        # must not fire a liveness alarm (this is the tz artifact that cried wolf
        # measuring gaps in UTC during the pre-dawn hours).
        markets = [
            {"market_id": "nyc", "state": "COLLECTING", "latest_age_minutes": 4.0,
             "freshness_sla_minutes": 15.0},
            {"market_id": "los-angeles", "state": "PENDING", "latest_age_minutes": None,
             "freshness_sla_minutes": 15.0},
            {"market_id": "seattle", "state": "CLEAN", "latest_age_minutes": 8.0,
             "freshness_sla_minutes": 15.0},
        ]
        verdict = fleet_capture_liveness(markets)
        self.assertEqual(verdict["status"], "OK")
        self.assertEqual(verdict["stale_market_count"], 0)
        self.assertIn("los-angeles", verdict["pending_markets"])

    def test_capture_liveness_flags_market_dark_inside_window(self):
        # A market inside its open window whose latest capture has missed
        # multiple cycles is the real "went dark" signal a monitor must catch.
        markets = [
            {"market_id": "nyc", "state": "COLLECTING", "latest_age_minutes": 4.0,
             "freshness_sla_minutes": 15.0},
            {"market_id": "denver", "state": "AT_RISK", "latest_age_minutes": 58.0,
             "freshness_sla_minutes": 15.0},
            # AT_RISK but latest capture is fresh -> an earlier gap, not a
            # liveness problem; must NOT alarm.
            {"market_id": "miami", "state": "AT_RISK", "latest_age_minutes": 6.0,
             "freshness_sla_minutes": 15.0},
        ]
        verdict = fleet_capture_liveness(markets, interval_minutes=10.0)
        self.assertEqual(verdict["status"], "STALE")
        self.assertEqual(verdict["stale_market_count"], 1)
        self.assertEqual(verdict["stale_markets"][0]["market_id"], "denver")

    def test_capture_liveness_ignores_end_of_sleep_jitter(self):
        # The loop captures markets sequentially then sleeps ~one interval, so a
        # market legitimately reaches ~1.x intervals old at end-of-sleep. That is
        # NOT going dark and must not alarm (the exact cry-wolf this replaces). It
        # only alarms past ~2 intervals + slack.
        markets = [
            {"market_id": m, "state": "AT_RISK", "latest_age_minutes": age,
             "freshness_sla_minutes": 15.0}
            for m, age in [("dallas", 18.0), ("denver", 17.5), ("seattle", 16.0)]
        ]
        verdict = fleet_capture_liveness(markets, interval_minutes=10.0)
        self.assertEqual(verdict["status"], "OK")
        self.assertEqual(verdict["stale_market_count"], 0)
        self.assertEqual(verdict["stale_after_minutes"], 22.0)

    def test_running_when_fresh(self):
        self.assertEqual(loop_health(self._status(), self.now, pid_alive=True)["state"], "RUNNING")

    def test_dead_when_heartbeat_stale(self):
        old = (self.now - timedelta(minutes=40)).isoformat()
        self.assertEqual(loop_health(self._status(last_heartbeat=old), self.now, pid_alive=True)["state"], "DEAD")

    def test_erroring_on_consecutive_errors(self):
        self.assertEqual(loop_health(self._status(consecutive_errors=3), self.now, pid_alive=True)["state"], "ERRORING")

    def test_paused(self):
        self.assertEqual(loop_health(self._status(paused=True), self.now, pid_alive=True)["state"], "PAUSED")

    def test_run_loop_records_elapsed_cycle_and_sleeps_from_start(self):
        current = datetime(2026, 6, 14, 12, 0)
        slept = []

        def now_fn():
            return current

        def capture_fn(force=False, market_id="toronto"):
            nonlocal current
            current = current + timedelta(minutes=4)
            return {"written": True, "snapshot_id": f"{market_id}-snapshot"}

        specs = [
            SimpleNamespace(id="toronto"),
            SimpleNamespace(id="nyc"),
            SimpleNamespace(id="atlanta"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "all_specs", lambda: specs), \
                    patch.object(tracker, "current_fleet_collection_health", lambda **kwargs: {"summary": {}, "markets": []}):
                status = run_loop(
                    interval_minutes=10.0,
                    max_iterations=1,
                    capture_fn=capture_fn,
                    sleep_fn=slept.append,
                    now_fn=now_fn,
                )
                written = json.loads((tmp_path / "loop_status.json").read_text(encoding="utf-8"))

        self.assertEqual(slept, [])
        self.assertEqual(status["last_iteration_elapsed_minutes"], 12.0)
        self.assertEqual(status["max_recent_iteration_elapsed_minutes"], 12.0)
        self.assertEqual(written["last_sleep_seconds"], 1.0)
        self.assertEqual(written["last_snapshot_id"], "atlanta-snapshot")
        self.assertEqual(written["last_market_in_progress"], None)

    def test_run_loop_sleeps_until_earliest_due_market_after_due_preflight_skip(self):
        current = datetime(2026, 6, 14, 12, 0)
        specs = [
            SimpleNamespace(id="toronto"),
            SimpleNamespace(id="nyc"),
        ]

        due_rows = [
            (
                specs[0],
                {
                    "market_id": "toronto",
                    "event_slug": "highest-temperature-in-toronto-on-june-14-2026",
                    "target_date": "2026-06-14",
                    "due": False,
                    "next_due_at": "2026-06-14T12:02:00",
                    "last_snapshot_at": "2026-06-14T11:52:00",
                },
            ),
            (
                specs[1],
                {
                    "market_id": "nyc",
                    "event_slug": "highest-temperature-in-nyc-on-june-14-2026",
                    "target_date": "2026-06-14",
                    "due": False,
                    "next_due_at": "2026-06-14T12:08:00",
                    "last_snapshot_at": "2026-06-14T11:58:00",
                },
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "all_specs", lambda: specs), \
                    patch.object(tracker, "ordered_snapshot_specs", lambda specs, target_date=None, now=None: due_rows), \
                    patch.object(tracker, "current_fleet_collection_health", lambda **kwargs: {"summary": {}, "markets": []}):
                status = run_loop(
                    interval_minutes=10.0,
                    max_iterations=1,
                    sleep_fn=lambda _seconds: None,
                    now_fn=lambda: current,
                )
                written = json.loads((tmp_path / "loop_status.json").read_text(encoding="utf-8"))

        self.assertEqual(status["last_sleep_seconds"], 120.0)
        self.assertEqual(status["last_sleep_reason"], "next_due_at")
        self.assertEqual(status["next_due_at"], "2026-06-14T12:02:00")
        self.assertEqual(written["last_sleep_seconds"], 120.0)
        self.assertEqual(written["last_sleep_reason"], "next_due_at")

    def test_run_loop_records_per_market_cadence_attribution_for_skipped_due_drift(self):
        base = datetime(2026, 6, 14, 12, 0)
        after_due = datetime(2026, 6, 14, 12, 3)
        times = [base, base, after_due, after_due, after_due, after_due, after_due]

        def now_fn():
            if times:
                return times.pop(0)
            return after_due

        specs = [SimpleNamespace(id="toronto")]
        due_rows = [
            (
                specs[0],
                {
                    "market_id": "toronto",
                    "event_slug": "highest-temperature-in-toronto-on-june-14-2026",
                    "target_date": "2026-06-14",
                    "due": False,
                    "next_due_at": "2026-06-14T12:02:00",
                    "last_snapshot_at": "2026-06-14T11:52:00",
                },
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "all_specs", lambda: specs), \
                    patch.object(tracker, "ordered_snapshot_specs", lambda specs, target_date=None, now=None: due_rows), \
                    patch.object(tracker, "current_fleet_collection_health", lambda **kwargs: {"summary": {}, "markets": []}):
                status = run_loop(
                    interval_minutes=10.0,
                    max_iterations=1,
                    sleep_fn=lambda _seconds: None,
                    now_fn=now_fn,
                )
                diagnostic = json.loads((tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()[-1])

        cadence = status["last_cadence_attribution"]
        market = cadence["markets"]["toronto"]
        self.assertEqual(cadence["skipped_not_due_count"], 1)
        self.assertEqual(cadence["skipped_after_due_count"], 1)
        self.assertEqual(cadence["skipped_after_due_markets"], ["toronto"])
        self.assertTrue(market["became_due_during_iteration"])
        self.assertTrue(market["skipped_after_due_at_completion"])
        self.assertEqual(market["due_lag_seconds_at_completion"], 60.0)
        self.assertEqual(diagnostic["cadence_attribution"]["skipped_after_due_count"], 1)

    def test_run_loop_passes_explicit_target_date_to_capture_fn(self):
        current = datetime(2026, 6, 14, 12, 0)
        calls = []

        def capture_fn(force=False, market_id="toronto", target_date=None):
            calls.append({
                "force": force,
                "market_id": market_id,
                "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
            })
            return {"written": True, "snapshot_id": f"{market_id}-snapshot"}

        specs = [
            SimpleNamespace(id="toronto"),
            SimpleNamespace(id="austin"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "all_specs", lambda: specs), \
                    patch.object(tracker, "current_fleet_collection_health", lambda **kwargs: {"summary": {}, "markets": []}):
                run_loop(
                    force=True,
                    interval_minutes=10.0,
                    max_iterations=1,
                    capture_fn=capture_fn,
                    now_fn=lambda: current,
                    target_date="2026-06-27",
                )

        self.assertEqual(
            calls,
            [
                {"force": True, "market_id": "toronto", "target_date": "2026-06-27"},
                {"force": True, "market_id": "austin", "target_date": "2026-06-27"},
            ],
        )

    def test_run_loop_exits_cleanly_on_stale_runtime_identity(self):
        # started_at is captured on the first now_fn() call; advance the clock
        # past the re-adoption debounce window so the stale-code exit fires. The
        # debounce only holds a re-adoption that happened very recently.
        base = datetime(2026, 6, 14, 12, 0)
        after_debounce = base + timedelta(minutes=20)  # > 900s default debounce
        clock = {"n": 0}

        def now_fn():
            clock["n"] += 1
            return base if clock["n"] == 1 else after_debounce

        slept = []
        stale_guard = {
            "runtime_code_state": "stale_code",
            "detail": "running process code identity differs from current source tree",
        }

        def capture_fn(**_kwargs):
            raise AssertionError("stale-code loop should exit before capture")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "runtime_identity_status", return_value=stale_guard):
                status = run_loop(
                    interval_minutes=10.0,
                    max_iterations=5,
                    capture_fn=capture_fn,
                    sleep_fn=slept.append,
                    now_fn=now_fn,
                )
                diagnostics = [
                    json.loads(line)
                    for line in (tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
                ]

        self.assertEqual(slept, [])
        self.assertEqual(status["iterations"], 1)
        self.assertEqual(status["stale_code_exit_requested_at"], after_debounce.isoformat())
        self.assertEqual(diagnostics[-1]["status"], "stale_code")
        self.assertEqual(diagnostics[-1]["action"], "exit_cleanly")

    def test_run_loop_debounces_recently_readopted_stale_code(self):
        # Stale code but the process re-adopted moments ago: the loop must NOT
        # exit mid-flight. It completes a full capture cycle (so a burst of
        # commits cannot kill it repeatedly and starve the tail markets) and only
        # re-adopts once the debounce window elapses.
        base = datetime(2026, 6, 14, 12, 0)  # constant clock -> process age ~0
        slept = []
        captured = []
        stale_guard = {
            "runtime_code_state": "stale_code",
            "detail": "running process code identity differs from current source tree",
        }

        def capture_fn(**kwargs):
            captured.append(kwargs.get("market_id"))
            return {"written": False, "snapshot_id": None}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(tracker, "LOOP_STATUS_PATH", tmp_path / "loop_status.json"), \
                    patch.object(tracker, "DIAGNOSTICS_PATH", tmp_path / "diagnostics.jsonl"), \
                    patch.object(tracker, "PAUSE_FLAG_PATH", tmp_path / "pause.flag"), \
                    patch.object(tracker, "runtime_identity_status", return_value=stale_guard):
                status = run_loop(
                    interval_minutes=10.0,
                    max_iterations=1,
                    capture_fn=capture_fn,
                    sleep_fn=slept.append,
                    now_fn=lambda: base,
                )
                diagnostics = [
                    json.loads(line)
                    for line in (tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
                ]

        # It captured (did not exit on stale) and recorded the debounce decision.
        self.assertTrue(captured)
        self.assertEqual(status["iterations"], 1)
        self.assertNotIn("stale_code_exit_requested_at", status)
        self.assertTrue(any(d.get("status") == "stale_code_debounced" for d in diagnostics))
        self.assertTrue(
            status["runtime_guard"].get("readoption_debounce", {}).get("debounced")
        )

    def test_capture_snapshot_uses_explicit_target_date(self):
        calls = {}

        class FakePolymarketClient:
            def __init__(self, timeout=10, target_date=None, market_id="toronto"):
                self.config = config_for_date(target_date, market_id)
                calls["client"] = {
                    "market_id": market_id,
                    "target_date": self.config.target_date.isoformat(),
                }

            def get_event(self):
                return {"slug": self.config.event_slug, "markets": []}

        class FakeModelClient:
            def __init__(self, target_date=None, market_id="toronto"):
                self.target_date = target_date
                calls["model"] = {
                    "market_id": market_id,
                    "target_date": target_date.isoformat(),
                }

            def fetch_historical_sources(self):
                return {}

            def fetch_live_sources(self):
                return {}

            def build(self, event, historical_sources=None, live_sources=None):
                calls["built_event_slug"] = event["slug"]
                return {"ok": True}

        class FakeStore:
            def __init__(self, event_slug=None):
                self.event_slug = event_slug
                calls["store_event_slug"] = event_slug

            def maybe_write(self, event, model, model_client, **kwargs):
                calls["write"] = {
                    "event_slug": self.event_slug,
                    "force": kwargs.get("force"),
                    "target_date": model_client.target_date.isoformat(),
                }
                return {"written": True, "snapshot_id": "snapshot-1", "event_slug": self.event_slug}

        with patch("weather.market.polymarket_client.PolymarketClient", FakePolymarketClient), \
                patch("weather.model.toronto_model.TorontoHighTempModel", FakeModelClient), \
                patch("weather.operations.event_metadata_validation.build_validation_payload", return_value={"validation_hash": "hash"}), \
                patch("weather.operations.event_metadata_validation.gate_for_market", return_value={"ok": True}), \
                patch.object(tracker, "SnapshotStore", FakeStore):
            result = tracker.capture_snapshot(force=True, market_id="austin", target_date="2026-06-27")

        expected_slug = config_for_date("2026-06-27", "austin").event_slug
        self.assertTrue(result["written"])
        self.assertEqual(calls["client"]["target_date"], "2026-06-27")
        self.assertEqual(calls["model"], {"market_id": "austin", "target_date": "2026-06-27"})
        self.assertEqual(calls["store_event_slug"], expected_slug)
        self.assertEqual(calls["write"]["target_date"], "2026-06-27")

    def test_capture_snapshot_skips_event_ahead_of_local_date(self):
        # Auto mode (no target_date): the live event resolves to june-27 but it is
        # still june-26 in the market's local tz -> skip the stray pre-local-day
        # capture instead of writing a snapshot hours ahead of the active window.
        class FakePolymarketClient:
            def __init__(self, timeout=10, target_date=None, market_id="los-angeles"):
                self.config = config_for_date(target_date, market_id)

            def get_event(self):
                return {
                    "slug": "highest-temperature-in-los-angeles-on-june-27-2026",
                    "markets": [],
                }

        def boom_store(*args, **kwargs):
            raise AssertionError("must not write a pre-local-day snapshot")

        with patch("weather.market.polymarket_client.PolymarketClient", FakePolymarketClient), \
                patch.object(tracker, "default_target_date", return_value=date(2026, 6, 26)), \
                patch.object(tracker, "SnapshotStore", boom_store):
            result = tracker.capture_snapshot(market_id="los-angeles")

        self.assertFalse(result["written"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["skipped_reason"], "event_date_ahead_of_local_date")
        self.assertEqual(result["target_date"], "2026-06-27")
        self.assertEqual(result["local_date"], "2026-06-26")

    def test_capture_snapshot_captures_when_event_matches_local_date(self):
        # Auto mode and the event date equals the market's local date -> not a
        # stray; capture proceeds and writes normally.
        calls = {}

        class FakePolymarketClient:
            def __init__(self, timeout=10, target_date=None, market_id="austin"):
                self.config = config_for_date(target_date, market_id)

            def get_event(self):
                return {"slug": "highest-temperature-in-austin-on-june-27-2026", "markets": []}

        class FakeModelClient:
            def __init__(self, target_date=None, market_id="austin"):
                self.target_date = target_date

            def fetch_historical_sources(self):
                return {}

            def fetch_live_sources(self):
                return {}

            def build(self, event, historical_sources=None, live_sources=None):
                return {"ok": True}

        class FakeStore:
            def __init__(self, event_slug=None):
                self.event_slug = event_slug

            def maybe_write(self, event, model, model_client, **kwargs):
                calls["written"] = True
                return {"written": True, "snapshot_id": "snap-1", "event_slug": self.event_slug}

        with patch("weather.market.polymarket_client.PolymarketClient", FakePolymarketClient), \
                patch("weather.model.toronto_model.TorontoHighTempModel", FakeModelClient), \
                patch("weather.operations.event_metadata_validation.build_validation_payload", return_value={"validation_hash": "h"}), \
                patch("weather.operations.event_metadata_validation.gate_for_market", return_value={"ok": True}), \
                patch.object(tracker, "default_target_date", return_value=date(2026, 6, 27)), \
                patch.object(tracker, "SnapshotStore", FakeStore):
            result = tracker.capture_snapshot(market_id="austin")

        self.assertTrue(result["written"])
        self.assertTrue(calls.get("written"))

    def test_latest_market_folder_can_require_explicit_target_date(self):
        spec = spec_for_id("austin")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            june26 = root / config_for_date("2026-06-26", "austin").event_slug
            june27 = root / config_for_date("2026-06-27", "austin").event_slug
            june26.mkdir()
            june27.mkdir()
            (june26 / "snapshots_long.csv").write_text("snapshot_id\nold\n", encoding="utf-8")
            (june27 / "snapshots_long.csv").write_text("snapshot_id\nnew\n", encoding="utf-8")

            self.assertEqual(latest_market_folder(spec, snapshots_root=root), june27)
            self.assertEqual(
                latest_market_folder(spec, snapshots_root=root, target_date="2026-06-26"),
                june26,
            )
            self.assertIsNone(latest_market_folder(spec, snapshots_root=root, target_date="2026-06-28"))


class TestSourceStatusRedaction(unittest.TestCase):
    def test_sensitive_query_detector_allows_redacted_values_only(self):
        raw = "https://api.weather.com/v1/history?apiKey=secret123&units=e"
        redacted = redact_sensitive_url_parts(raw)

        self.assertTrue(has_unredacted_sensitive_url_parts(raw))
        self.assertFalse(has_unredacted_sensitive_url_parts(redacted))

    def test_sensitive_query_detector_treats_empty_values_as_unredacted(self):
        raw = "https://api.weather.com/v1/history?apiKey=&units=e"
        redacted = redact_sensitive_url_parts(raw)

        self.assertTrue(has_unredacted_sensitive_url_parts(raw))
        self.assertFalse(has_unredacted_sensitive_url_parts(redacted))
        self.assertIn("apiKey=<redacted>", redacted)
        self.assertNotIn("apiKey=&", redacted)

    def test_source_status_rows_redact_secret_query_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=Path(tmp), event_slug="event")
            rows = store.source_status_rows(
                {
                    "wu_history": {
                        "ok": False,
                        "status": "failed",
                        "error": (
                            "400 Client Error for url: "
                            "https://api.weather.com/v1/history?apiKey=secret123&units=e"
                        ),
                        "data": {
                            "url": "https://api.weather.com/v1/history?apiKey=secret123&units=e",
                            "rows": [],
                        },
                    }
                },
                model_client=SimpleNamespace(source_cache_ttl_minutes=lambda _source: 30),
                snapshot_id="s1",
                captured_at=datetime(2026, 6, 27, 5, 0, tzinfo=timezone.utc),
                model_version="test",
            )

        self.assertEqual(len(rows), 1)
        self.assertNotIn("secret123", rows[0]["error"])
        self.assertNotIn("secret123", rows[0]["source_url"])
        self.assertIn("apiKey=<redacted>", rows[0]["error"])
        self.assertIn("apiKey=<redacted>", rows[0]["source_url"])

    def test_source_status_rows_redact_empty_secret_query_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=Path(tmp), event_slug="event")
            rows = store.source_status_rows(
                {
                    "wu_history": {
                        "ok": False,
                        "status": "failed",
                        "error": (
                            "400 Client Error for url: "
                            "https://api.weather.com/v1/history?apiKey=&units=e"
                        ),
                        "data": {
                            "url": "https://api.weather.com/v1/history?apiKey=&units=e",
                            "rows": [],
                        },
                    }
                },
                model_client=SimpleNamespace(source_cache_ttl_minutes=lambda _source: 30),
                snapshot_id="s1",
                captured_at=datetime(2026, 6, 27, 5, 0, tzinfo=timezone.utc),
                model_version="test",
            )

        self.assertEqual(len(rows), 1)
        self.assertNotIn("apiKey=&", rows[0]["error"])
        self.assertNotIn("apiKey=&", rows[0]["source_url"])
        self.assertIn("apiKey=<redacted>", rows[0]["error"])
        self.assertIn("apiKey=<redacted>", rows[0]["source_url"])

    def test_source_family_degradation_redacts_existing_unredacted_error_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-27T05:00:00+00:00",
                        "captured_at_local": "2026-06-27T01:00:00-04:00",
                        "source": "wu_history",
                        "ok": "False",
                        "stale": "False",
                        "status": "failed",
                        "source_family": "wu_history",
                        "http_status": "400",
                        "degradation_state": "failed",
                        "cache_status": "miss",
                        "fetched_at": "2026-06-27T01:00:00-04:00",
                        "error": (
                            "400 Client Error for url: "
                            "https://api.weather.com/v1/history?apiKey=secret123&units=e"
                        ),
                    }
                ]
            ).to_csv(folder / "source_status_long.csv", index=False)

            payload = source_family_degradation(folder)

        detail = payload["families"]["wu_history"]["source_details"][0]
        self.assertNotIn("secret123", detail["error"])
        self.assertIn("apiKey=<redacted>", detail["error"])


class TestSnapshotStoreRuntimeGuard(unittest.TestCase):
    def test_maybe_write_returns_stale_code_result_without_writing(self):
        stale_guard = {
            "ok": False,
            "state": "stale_code",
            "detail": "snapshot process code identity differs from current source tree",
            "process_identity": {"source_fingerprint": "old"},
            "current_identity": {"source_fingerprint": "new"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(
                root=tmp,
                event_slug="highest-temperature-in-toronto-on-june-13-2026",
            )

            def fail_write(*args, **kwargs):
                raise AssertionError("write should not run")

            store.runtime_identity_guard = lambda: stale_guard
            store.write = fail_write

            result = store.maybe_write(
                {"slug": "highest-temperature-in-toronto-on-june-13-2026", "markets": []},
                {},
                SimpleNamespace(target_date=datetime(2026, 6, 13).date()),
                force=True,
            )

            self.assertFalse(result["written"])
            self.assertTrue(result["blocked"])
            self.assertEqual(result["status"], "stale_code")
            self.assertEqual(result["detail"], stale_guard["detail"])
            self.assertFalse((Path(tmp) / "snapshots_long.csv").exists())

    def test_write_still_rejects_stale_code_guard(self):
        stale_guard = {
            "ok": False,
            "state": "stale_code",
            "detail": "snapshot process code identity differs from current source tree",
        }

        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(
                root=tmp,
                event_slug="highest-temperature-in-toronto-on-june-13-2026",
            )

            with self.assertRaises(RuntimeError):
                store.write(
                    {"slug": "highest-temperature-in-toronto-on-june-13-2026", "markets": []},
                    {},
                    SimpleNamespace(target_date=datetime(2026, 6, 13).date()),
                    datetime(2026, 6, 13, 12, 0),
                    runtime_guard=stale_guard,
                )


class TestGapDetection(unittest.TestCase):
    def _times(self, *hhmm):
        return parse_times([f"2026-05-30T{t}:00" for t in hhmm])

    def test_no_gaps_regular_cadence(self):
        times = self._times("12:00", "12:10", "12:20", "12:30")
        self.assertEqual(detect_gaps(times, 10.0), [])

    def test_detects_gap(self):
        times = self._times("12:00", "12:10", "13:00", "13:10")  # 50-min hole
        gaps = detect_gaps(times, 10.0)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0]["gap_minutes"], 50.0)

    def test_scheduled_due_ignores_recent_triggered_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(
                root=tmp,
                interval=timedelta(minutes=10),
                event_slug="highest-temperature-in-toronto-on-may-30-2026",
            )
            pd.DataFrame([
                {
                    "snapshot_id": "scheduled",
                    "captured_at_local": "2026-05-30T12:00:00",
                    "snapshot_cadence": "scheduled",
                },
                {
                    "snapshot_id": "triggered",
                    "captured_at_local": "2026-05-30T12:08:00",
                    "snapshot_cadence": "triggered",
                },
            ]).to_csv(store.long_path, index=False)

            due_at = datetime(2026, 5, 30, 12, 10)

            self.assertEqual(store.last_snapshot_time(), datetime(2026, 5, 30, 12, 8))
            self.assertEqual(
                store.last_snapshot_time(cadence="scheduled"),
                datetime(2026, 5, 30, 12, 0),
            )
            self.assertTrue(store.is_due(due_at, cadence="scheduled"))
            # Due one interval minus the 60s due tolerance after the last
            # scheduled write (item 320), so an on-cadence loop tick is not
            # skipped for landing a few seconds short of the boundary.
            self.assertEqual(store.next_due_at(cadence="scheduled"), "2026-05-30T12:09:00")

    def test_due_tolerance_absorbs_boundary_jitter(self):
        # The managed loop fires on a period equal to the interval, so a tick can
        # land a few seconds short of the boundary. With a strict predicate that
        # tick is rejected and the market waits a whole extra cycle (~2x
        # interval), capping cadence/capture-ratio (item 320). The due tolerance
        # absorbs that jitter.
        slug = "highest-temperature-in-toronto-on-may-30-2026"
        with tempfile.TemporaryDirectory() as tmp:
            store = SnapshotStore(root=tmp, interval=timedelta(minutes=10), event_slug=slug)
            pd.DataFrame([{
                "snapshot_id": "scheduled",
                "captured_at_local": "2026-05-30T12:00:00",
                "snapshot_cadence": "scheduled",
            }]).to_csv(store.long_path, index=False)

            # 9m30s after the last write: a hair short of the 10-min interval but
            # within the 60s tolerance -> due (the on-cadence loop tick).
            self.assertTrue(store.is_due(datetime(2026, 5, 30, 12, 9, 30), cadence="scheduled"))
            # Well inside the interval -> not due (no double-write / cadence creep).
            self.assertFalse(store.is_due(datetime(2026, 5, 30, 12, 5, 0), cadence="scheduled"))

            # A strict store (zero tolerance) still requires a full interval.
            strict = SnapshotStore(
                root=tmp, interval=timedelta(minutes=10), event_slug=slug,
                due_tolerance=timedelta(0),
            )
            self.assertFalse(strict.is_due(datetime(2026, 5, 30, 12, 9, 30), cadence="scheduled"))
            self.assertTrue(strict.is_due(datetime(2026, 5, 30, 12, 10, 0), cadence="scheduled"))

    def test_early_hour_coverage_uses_market_native_timezone(self):
        # Los Angeles rows are persisted with the process/local -04:00 offset,
        # but the proof window is the market's 00:00-08:00 local day. A tape
        # beginning at 03:03 -04:00 is 00:03 Pacific and must count.
        slug = "highest-temperature-in-los-angeles-on-june-28-2026"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / slug
            folder.mkdir()
            rows = []
            start = datetime.fromisoformat("2026-06-28T03:03:00-04:00")
            for index in range(48):
                captured_at = start + timedelta(minutes=10 * index)
                rows.append({
                    "snapshot_id": f"s{index}",
                    "captured_at_local": captured_at.isoformat(),
                    "snapshot_cadence": "scheduled",
                })
            pd.DataFrame(rows).to_csv(folder / "snapshots_long.csv", index=False)

            summary = summarize_folder(
                folder,
                interval_minutes=10.0,
                tolerance=1.5,
                live=True,
                as_of=datetime.fromisoformat("2026-06-28T12:00:00-07:00"),
            )

        early = summary["early_hour_coverage"]
        self.assertEqual(early["status"], "PASS")
        self.assertTrue(early["counts_toward_early_hour_evidence"])
        self.assertEqual(early["snapshot_count"], 48)
        self.assertTrue(early["first_snapshot_at_local"].startswith("2026-06-28T00:03:00"))

    def test_coverage_clean_full_afternoon(self):
        start = datetime(2026, 5, 30, 11, 0)
        times = [start + timedelta(minutes=10 * i) for i in range(49)]  # 11:00..19:00
        cov = coverage_summary(times, 10.0)
        self.assertTrue(cov["clean"])
        self.assertTrue(cov["covers_afternoon"])
        self.assertEqual(cov["gaps"], [])

    def test_coverage_flags_gap_and_short_window(self):
        times = self._times("13:00", "13:10", "14:00")  # gap + starts too late
        cov = coverage_summary(times, 10.0)
        self.assertFalse(cov["clean"])
        self.assertFalse(cov["covers_afternoon"])

    def test_coverage_ignores_gap_after_settlement_window(self):
        times = self._times(
            "11:50", "12:00", "12:10", "12:20", "12:30", "12:40",
            "12:50", "13:00", "13:10", "13:20", "13:30", "13:40",
            "13:50", "14:00", "14:10", "14:20", "14:30", "14:40",
            "14:50", "15:00", "15:10", "15:20", "15:30", "15:40",
            "15:50", "16:00", "16:10", "16:20", "16:30", "16:40",
            "16:50", "17:00", "17:10", "17:20", "17:30", "17:40",
            "17:50", "18:00", "23:00", "23:30",
        )

        cov = coverage_summary(times, 10.0, target_date=datetime(2026, 5, 30).date())

        self.assertTrue(cov["clean"])
        self.assertEqual(cov["gaps"], [])

    def test_coverage_keeps_gap_crossing_window_start(self):
        times = self._times("11:50", "12:20", "12:30", "18:00")

        cov = coverage_summary(times, 10.0, target_date=datetime(2026, 5, 30).date())

        self.assertFalse(cov["clean"])
        self.assertIn("gap", cov["reason"])

    def test_live_coverage_collecting_before_afternoon_window(self):
        times = self._times("09:40", "09:50", "10:00")
        cov = live_coverage_summary(times, 10.0, as_of=datetime(2026, 5, 30, 10, 5))

        self.assertEqual(cov["state"], "COLLECTING")
        self.assertFalse(cov["action_required"])

    def test_live_coverage_flags_overdue_capture(self):
        times = self._times("12:00", "12:10")
        cov = live_coverage_summary(times, 10.0, as_of=datetime(2026, 5, 30, 12, 40))

        self.assertEqual(cov["state"], "AT_RISK")
        self.assertTrue(cov["action_required"])
        self.assertIn("latest capture", cov["reason"])

    def test_live_coverage_closes_clean_after_window(self):
        start = datetime(2026, 5, 30, 11, 0)
        times = [start + timedelta(minutes=10 * i) for i in range(49)]  # 11:00..19:00
        cov = live_coverage_summary(times, 10.0, as_of=datetime(2026, 5, 30, 19, 5))

        self.assertEqual(cov["state"], "CLEAN")
        self.assertFalse(cov["action_required"])

    def test_live_coverage_closes_partial_after_gap(self):
        times = self._times("11:50", "12:00", "13:00", "18:00")
        cov = live_coverage_summary(times, 10.0, as_of=datetime(2026, 5, 30, 19, 0))

        self.assertEqual(cov["state"], "PARTIAL")
        self.assertTrue(cov["action_required"])

    def test_summarize_folder_live_uses_event_slug_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-toronto-on-may-30-2026"
            folder.mkdir()
            pd.DataFrame([
                {
                    "snapshot_id": "s1",
                    "captured_at_local": "2026-05-30T09:40:00",
                },
                {
                    "snapshot_id": "s2",
                    "captured_at_local": "2026-05-30T09:50:00",
                },
            ]).to_csv(folder / "snapshots_long.csv", index=False)

            cov = summarize_folder(
                folder,
                interval_minutes=10.0,
                live=True,
                as_of=datetime(2026, 5, 30, 10, 0),
            )

            self.assertEqual(cov["event_slug"], folder.name)
            self.assertEqual(cov["state"], "COLLECTING")


if __name__ == "__main__":
    unittest.main()
