import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import weather.collection.snapshot_tracker as snapshot_tracker
from weather.collection.snapshot_tracker import TORONTO_TZ, ensure_decision, loop_health

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=TORONTO_TZ)


class FakeProcess:
    pid = 4321


def status(heartbeat_age_min=1.0, paused=False, errors=0, pid=1234, interval=10.0, **extra):
    base = {
        "pid": pid,
        "interval_minutes": interval,
        "last_heartbeat": (NOW - timedelta(minutes=heartbeat_age_min)).isoformat(),
        "consecutive_errors": errors,
        "paused": paused,
        "started_at": (NOW - timedelta(hours=2)).isoformat(),
    }
    base.update(extra)
    return base


class TestEnsureDecision(unittest.TestCase):
    """The supervisor verb's pure decision logic: keep exactly one healthy
    loop alive across silent deaths (the 2026-06-10 02:24 incident), hangs,
    and reboots -- without fighting operator intent (pause) or masking
    capture errors with restarts."""

    def _state(self, st, pid_alive=True):
        return loop_health(st, NOW, pid_alive=pid_alive)["state"]

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
        state = self._state(status(heartbeat_age_min=420), pid_alive=False)
        self.assertEqual(state, "DEAD")
        self.assertEqual(ensure_decision(state, pid_alive=False), "start")

    def test_fresh_provisional_heartbeat_with_dead_pid_is_dead(self):
        # A failed detached start writes a fresh provisional heartbeat before
        # the child can acquire the writer lock; PID liveness must win.
        state = self._state(status(heartbeat_age_min=0, iterations=0), pid_alive=False)
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

    def test_stale_runtime_identity_restarts_loop(self):
        old_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "abc",
            "source_fingerprint": "old",
        }
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "abc",
            "source_fingerprint": "new",
        }

        health = loop_health(
            status(runtime_identity=old_identity),
            NOW,
            current_identity=current_identity,
            pid_alive=True,
        )

        self.assertEqual(health["state"], "STALE_CODE")
        self.assertEqual(health["runtime_code_state"], "stale_code")
        self.assertEqual(ensure_decision(health["state"], pid_alive=True), "restart")

    def test_ensure_loop_backs_off_repeated_stale_code_recovery(self):
        old_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "abc",
            "source_fingerprint": "old",
        }
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "abc",
            "source_fingerprint": "new",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            diagnostics_path = root / "diagnostics.jsonl"
            console_path = root / "loop_console.log"
            status_path.write_text(json.dumps(status(runtime_identity=old_identity)), encoding="utf-8")
            diagnostics_path.write_text(
                json.dumps({
                    "time": (NOW - timedelta(seconds=30)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "STALE_CODE",
                }) + "\n",
                encoding="utf-8",
            )
            console_path.write_text("", encoding="utf-8")

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", diagnostics_path), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", console_path), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "get_runtime_identity", return_value=current_identity), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker, "stop_loop") as stop_loop, \
                    patch.object(snapshot_tracker, "start_loop_detached") as start_loop:
                result = snapshot_tracker.ensure_loop(now=NOW)

        self.assertEqual(result["action"], "backoff")
        self.assertEqual(result["intended_action"], "restart")
        self.assertEqual(result["restart_cause"], "STALE_CODE")
        stop_loop.assert_not_called()
        start_loop.assert_not_called()

    def test_start_loop_detached_writes_snapshot_supervisor_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = {}

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                calls["command"] = command
                calls["cwd"] = cwd
                calls["stdout_closed_during_call"] = stdout.closed
                calls["stderr_is_stdout"] = stderr is stdout
                return FakeProcess()

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "loop_console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker.subprocess, "Popen", fake_popen):
                result = snapshot_tracker.start_loop_detached(interval_minutes=12.5, now=NOW)
                payload = json.loads((root / "loop_status.json").read_text(encoding="utf-8"))

        self.assertTrue(result["started"])
        self.assertEqual(payload["pid"], 4321)
        self.assertEqual(payload["interval_minutes"], 12.5)
        self.assertEqual(payload["started_by"], "supervisor")
        self.assertIn("weather.collection.snapshot_tracker", calls["command"])
        self.assertIn("--interval-minutes", calls["command"])
        self.assertFalse(calls["stdout_closed_during_call"])
        self.assertTrue(calls["stderr_is_stdout"])

    def test_start_loop_detached_removes_dead_writer_lock_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                return FakeProcess()

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "loop_console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=False), \
                    patch.object(snapshot_tracker.subprocess, "Popen", fake_popen):
                result = snapshot_tracker.start_loop_detached(interval_minutes=10.0, now=NOW)

        self.assertTrue(result["started"])
        self.assertTrue(result["writer_lock"]["removed"])
        self.assertFalse(lock_path.exists())

    def test_start_loop_detached_does_not_fight_live_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")

            def fail_popen(*args, **kwargs):
                raise AssertionError("Popen should not be called while another writer is live")

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "loop_console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker.subprocess, "Popen", fail_popen):
                result = snapshot_tracker.start_loop_detached(interval_minutes=10.0, now=NOW)
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer lock owner is still live")
        self.assertTrue(lock_still_exists)

    def test_stop_loop_removes_stopped_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            status_path.write_text(json.dumps(status(pid=1234)), encoding="utf-8")
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker, "terminate_python_pid", return_value={"pid": 1234, "stopped": True}):
                result = snapshot_tracker.stop_loop(now=NOW)

        self.assertTrue(result["stopped"])
        self.assertTrue(result["writer_lock"]["removed"])
        self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
