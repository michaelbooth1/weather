import os
import sys
import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import pandas as pd
import weather.collection.snapshot_tracker as tracker  # noqa: E402
from weather.model.model_sources import request_with_retries, _is_retryable
from weather.collection.snapshot_tracker import SnapshotStore, loop_health, run_loop
from weather.collection.collection_health import (
    detect_gaps,
    coverage_summary,
    live_coverage_summary,
    parse_times,
    summarize_folder,
)


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
            self.assertEqual(store.next_due_at(cadence="scheduled"), "2026-05-30T12:10:00")

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
