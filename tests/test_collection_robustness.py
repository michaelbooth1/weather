import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import requests

# Add src to the path
sys.path.insert(0, os.path.abspath("src"))

from model_sources import request_with_retries, _is_retryable
from snapshot_tracker import loop_health
from collection_health import detect_gaps, coverage_summary, parse_times


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
        self.assertEqual(loop_health(self._status(), self.now)["state"], "RUNNING")

    def test_dead_when_heartbeat_stale(self):
        old = (self.now - timedelta(minutes=40)).isoformat()
        self.assertEqual(loop_health(self._status(last_heartbeat=old), self.now)["state"], "DEAD")

    def test_erroring_on_consecutive_errors(self):
        self.assertEqual(loop_health(self._status(consecutive_errors=3), self.now)["state"], "ERRORING")

    def test_paused(self):
        self.assertEqual(loop_health(self._status(paused=True), self.now)["state"], "PAUSED")


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


if __name__ == "__main__":
    unittest.main()
