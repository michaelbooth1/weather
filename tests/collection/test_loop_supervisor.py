import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("src"))

from snapshot_tracker import TORONTO_TZ, ensure_decision, loop_health

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=TORONTO_TZ)


def status(heartbeat_age_min=1.0, paused=False, errors=0, pid=1234, interval=10.0):
    return {
        "pid": pid,
        "interval_minutes": interval,
        "last_heartbeat": (NOW - timedelta(minutes=heartbeat_age_min)).isoformat(),
        "consecutive_errors": errors,
        "paused": paused,
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
    }


class TestEnsureDecision(unittest.TestCase):
    """The supervisor verb's pure decision logic: keep exactly one healthy
    loop alive across silent deaths (the 2026-06-10 02:24 incident), hangs,
    and reboots -- without fighting operator intent (pause) or masking
    capture errors with restarts."""

    def _state(self, st):
        return loop_health(st, NOW)["state"]

    def test_fresh_heartbeat_is_noop(self):
        state = self._state(status(heartbeat_age_min=5))
        self.assertEqual(state, "RUNNING")
        self.assertEqual(ensure_decision(state, pid_alive=True), "noop")

    def test_paused_is_operator_intent_noop(self):
        state = self._state(status(paused=True))
        self.assertEqual(state, "PAUSED")
        self.assertEqual(ensure_decision(state, pid_alive=True), "noop")

    def test_erroring_loop_is_left_visible(self):
        # Alive but failing captures: restarts would just mask the error.
        state = self._state(status(errors=5))
        self.assertEqual(state, "ERRORING")
        self.assertEqual(ensure_decision(state, pid_alive=True), "noop")

    def test_silent_death_starts_fresh(self):
        # The 02:24 incident: stale heartbeat, process gone.
        state = self._state(status(heartbeat_age_min=420))
        self.assertEqual(state, "DEAD")
        self.assertEqual(ensure_decision(state, pid_alive=False), "start")

    def test_hung_process_is_killed_and_restarted(self):
        # Stale heartbeat but the PID still exists: a hang Task Scheduler's
        # own restart-on-failure could never detect.
        state = self._state(status(heartbeat_age_min=60))
        self.assertEqual(state, "DEAD")
        self.assertEqual(ensure_decision(state, pid_alive=True), "restart")

    def test_never_ran_starts(self):
        state = self._state(None)
        self.assertEqual(state, "UNKNOWN")
        self.assertEqual(ensure_decision(state, pid_alive=False), "start")

    def test_heartbeat_tolerates_one_full_cycle(self):
        # dead_after = 2 * interval + 2: an 18-minute-old heartbeat on a
        # 10-minute loop (capture takes minutes) is still RUNNING.
        state = self._state(status(heartbeat_age_min=18))
        self.assertEqual(state, "RUNNING")
        self.assertEqual(ensure_decision(state, pid_alive=True), "noop")


if __name__ == "__main__":
    unittest.main()
