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


def observed_runtime_command(command):
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        return [str(Path(sys.base_prefix) / Path(command[0]).name), *command[1:]]
    return list(command)


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

    def test_missing_writer_lock_restarts_apparently_live_status(self):
        self.assertEqual(
            ensure_decision("RUNNING", pid_alive=True, writer_lock_healthy=False),
            "restart",
        )

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

    def test_thrashing_sweep_is_flagged_degraded_but_not_restarted(self):
        # 2026-07-03 stall: the heartbeat updates per market inside a sweep,
        # so a loop crawling under host memory pressure reads RUNNING while
        # per-market captures gap for 80+ minutes. Restarting would not
        # relieve external pressure (and would storm every ensure tick), so
        # the condition is a visibility flag, not a state.
        health = loop_health(
            status(
                heartbeat_age_min=5,
                last_snapshot_written_at=(NOW - timedelta(minutes=80)).isoformat(),
            ),
            NOW,
            pid_alive=True,
        )

        self.assertEqual(health["state"], "RUNNING")
        self.assertTrue(health["capture_degraded"])
        self.assertIn("last snapshot 80.0 min old", health["capture_degraded_reason"])
        self.assertEqual(ensure_decision(health["state"], pid_alive=True), "noop")

    def test_healthy_sweep_is_not_degraded(self):
        health = loop_health(
            status(
                heartbeat_age_min=1,
                last_snapshot_written_at=(NOW - timedelta(minutes=3)).isoformat(),
            ),
            NOW,
            pid_alive=True,
        )

        self.assertEqual(health["state"], "RUNNING")
        self.assertFalse(health["capture_degraded"])
        self.assertIsNone(health["capture_degraded_reason"])

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
            status_path.with_name(".loop_status.json.writer.lock").write_text(
                json.dumps({"pid": 1234}),
                encoding="utf-8",
            )
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
                    patch.object(snapshot_tracker, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(snapshot_tracker, "get_runtime_identity", return_value=current_identity), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker, "stop_loop") as stop_loop, \
                    patch.object(snapshot_tracker, "start_loop_detached") as start_loop:
                result = snapshot_tracker.ensure_loop(now=NOW)

        self.assertEqual(result["action"], "backoff")
        self.assertEqual(result["intended_action"], "restart")
        self.assertEqual(result["restart_cause"], "STALE_CODE")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        self.assertEqual(result["exit_code"], 1)
        stop_loop.assert_not_called()
        start_loop.assert_not_called()

    def test_ensure_loop_restarts_dead_pid_with_stale_status(self):
        old_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "old",
            "source_fingerprint": "old",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            status_path.write_text(
                json.dumps(status(heartbeat_age_min=0, pid=7654, runtime_identity=old_identity)),
                encoding="utf-8",
            )
            diagnostics_path = root / "diagnostics.jsonl"
            diagnostics_path.write_text("", encoding="utf-8")
            console_path = root / "console.log"
            console_path.write_text("", encoding="utf-8")

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", diagnostics_path), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", console_path), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=False), \
                    patch.object(snapshot_tracker, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch.object(snapshot_tracker, "loop_file_offsets", return_value={}), \
                    patch.object(snapshot_tracker, "quarantine_malformed_loop_lines", return_value={}), \
                    patch.object(
                        snapshot_tracker,
                        "start_loop_detached",
                        return_value={"started": True, "pid": 8765},
                    ) as start_loop:
                result = snapshot_tracker.ensure_loop(now=NOW)
                persisted = json.loads(
                    (root / "loop_supervisor_status.json").read_text(encoding="utf-8")
                )

        self.assertEqual(result["action"], "start")
        self.assertEqual(result["state"], "DEAD")
        self.assertEqual(result["restart_cause"], "DEAD")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(persisted["ensure_status"], "OK")
        start_loop.assert_called_once_with(10.0, now=NOW)

    def test_ensure_loop_lock_contention_is_persisted_and_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(snapshot_tracker, "acquire_supervisor_lock", return_value=None), \
                    patch.object(snapshot_tracker, "start_loop_detached") as start_loop:
                result = snapshot_tracker.ensure_loop(now=NOW)
                persisted = json.loads(
                    (root / "loop_supervisor_status.json").read_text(encoding="utf-8")
                )

        self.assertEqual(result["action"], "locked")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(persisted["action"], "locked")
        start_loop.assert_not_called()

    def test_ensure_cli_returns_persisted_nonzero_exit_code(self):
        result = {"action": "backoff", "ensure_status": "BLOCKED", "exit_code": 1}
        with patch.object(snapshot_tracker, "ensure_loop", return_value=result), \
                patch.object(sys, "argv", ["snapshot_tracker", "--ensure"]), \
                patch("builtins.print"):
            exit_code = snapshot_tracker.main()

        self.assertEqual(exit_code, 1)

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

    def test_start_loop_detached_rotates_all_sidecars_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics_path = root / "diagnostics.jsonl"
            console_path = root / "loop_console.log"
            diagnostics_path.write_text("legacy-diagnostics\n", encoding="utf-8")
            console_path.write_text("legacy-console\n", encoding="utf-8")

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                self.assertFalse(diagnostics_path.exists())
                self.assertEqual(stdout.tell(), 0)
                self.assertIs(stdout, stderr)
                stdout.write("new-child-console\n")
                stdout.flush()
                return FakeProcess()

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", diagnostics_path), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", console_path), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch("weather.io.DEFAULT_SIDECAR_ROTATE_BYTES", 1), \
                    patch.object(snapshot_tracker.subprocess, "Popen", fake_popen):
                result = snapshot_tracker.start_loop_detached(now=NOW)

            rotated_diagnostics = list(root.glob("diagnostics.*.jsonl"))
            rotated_console = list(root.glob("loop_console.*.log"))

        self.assertTrue(result["started"])
        self.assertEqual(len(rotated_diagnostics), 1)
        self.assertEqual(len(rotated_console), 1)
        self.assertEqual(len(result["sidecar_rotations"]), 2)

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
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "not_found", "pid": 9999}), \
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
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "running", "pid": 9999}), \
                    patch.object(snapshot_tracker.subprocess, "Popen", fail_popen):
                result = snapshot_tracker.start_loop_detached(interval_minutes=10.0, now=NOW)
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer_lock_owner_not_proven_dead")
        self.assertTrue(lock_still_exists)

    def test_start_loop_detached_fails_closed_when_writer_owner_is_uninspectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", root / "loop_status.json"), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch("weather.operations.supervisor.observe_process", return_value={"state": "unknown", "pid": 9999}), \
                    patch.object(snapshot_tracker.subprocess, "Popen") as popen:
                result = snapshot_tracker.start_loop_detached(now=NOW)
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "writer_lock_owner_not_proven_dead")
        self.assertTrue(lock_still_exists)
        popen.assert_not_called()

    def test_snapshot_cleanup_retains_same_pid_replacement_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({
                "pid": 1234,
                "managed_process": {"pid": 1234, "creation_time_token": "win32-filetime:new"},
            }), encoding="utf-8")
            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path):
                result = snapshot_tracker._cleanup_loop_writer_lock(
                    expected_pid=1234,
                    confirmed_exit={"exited": True},
                    exited_identity={"pid": 1234, "creation_time_token": "win32-filetime:old"},
                )
                lock_still_exists = lock_path.exists()

        self.assertFalse(result["removed"])
        self.assertEqual(result["reason"], "writer_lock_process_instance_mismatch")
        self.assertTrue(lock_still_exists)

    def test_stop_loop_accepts_venv_resolution_and_removes_stopped_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            command = snapshot_tracker._snapshot_loop_command(10.0)
            identity = {
                "pid": 1234,
                "expected_command": command,
                "creation_time_token": "win32-filetime:100",
            }
            status_path.write_text(
                json.dumps(status(pid=1234, managed_process=identity)),
                encoding="utf-8",
            )
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(
                json.dumps({"pid": 1234, "managed_process": identity}),
                encoding="utf-8",
            )

            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch("weather.operations.supervisor.observe_process", return_value={
                        "state": "running",
                        "pid": 1234,
                        "argv": observed_runtime_command(command),
                        "command_line": "managed snapshot command",
                        "creation_time_token": "win32-filetime:100",
                        "inspectable": True,
                    }), \
                    patch.object(snapshot_tracker, "terminate_managed_process", return_value={
                        "pid": 1234,
                        "stopped": True,
                        "exited": True,
                        "reason": "verified_process_exited",
                        "termination_scope": "verified_process_handle",
                    }):
                result = snapshot_tracker.stop_loop(now=NOW)

        self.assertTrue(result["stopped"])
        self.assertTrue(result["writer_lock"]["removed"])
        self.assertFalse(lock_path.exists())

    def test_stop_loop_rejects_reused_pid_command_mismatch_and_unknown_identity(self):
        command = snapshot_tracker._snapshot_loop_command(10.0)
        identity = {
            "pid": 1234,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        cases = (
            (
                "reused_pid_process_instance_mismatch",
                {"state": "running", "pid": 1234, "argv": observed_runtime_command(command), "creation_time_token": "win32-filetime:200", "inspectable": True},
            ),
            (
                "managed_process_command_mismatch",
                {"state": "running", "pid": 1234, "argv": [*observed_runtime_command(command)[:-1], "99.0"], "creation_time_token": "win32-filetime:100", "inspectable": True},
            ),
            (
                "live_process_identity_uninspectable",
                {"state": "unknown", "pid": 1234},
            ),
        )
        for expected_reason, observation in cases:
            with self.subTest(expected_reason=expected_reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                status_path = root / "loop_status.json"
                status_path.write_text(
                    json.dumps(status(pid=1234, managed_process=identity)),
                    encoding="utf-8",
                )
                lock_path = root / ".loop_status.json.writer.lock"
                lock_path.write_text(
                    json.dumps({"pid": 1234, "managed_process": identity}),
                    encoding="utf-8",
                )
                with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                        patch("weather.operations.supervisor.observe_process", return_value=observation), \
                        patch.object(snapshot_tracker, "terminate_managed_process") as terminate:
                    result = snapshot_tracker.stop_loop(now=NOW)

                self.assertFalse(result["stopped"])
                self.assertEqual(result["reason"], expected_reason)
                self.assertTrue(lock_path.exists())
                terminate.assert_not_called()

    def test_ensure_snapshot_live_lock_mismatch_blocks_kill_and_replacement(self):
        command = snapshot_tracker._snapshot_loop_command(10.0)
        identity = {
            "pid": 1234,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            status_path.write_text(
                json.dumps(status(pid=1234, managed_process=identity)),
                encoding="utf-8",
            )
            lock_path = root / ".loop_status.json.writer.lock"
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(snapshot_tracker, "acquire_supervisor_lock", return_value=object()), \
                    patch.object(snapshot_tracker, "release_supervisor_lock"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch("weather.operations.supervisor.observe_process", return_value={
                        "state": "running",
                        "pid": 9999,
                        "inspectable": False,
                    }), \
                    patch.object(snapshot_tracker, "terminate_managed_process") as terminate, \
                    patch.object(snapshot_tracker, "start_loop_detached") as start:
                result = snapshot_tracker.ensure_loop(now=NOW)
                lock_still_exists = lock_path.exists()

        self.assertEqual(result["action"], "restart_blocked")
        self.assertEqual(result["reason"], "mismatched_writer_lock_owner_is_authoritative")
        self.assertEqual(result["ensure_status"], "BLOCKED")
        terminate.assert_not_called()
        start.assert_not_called()
        self.assertTrue(lock_still_exists)

    def test_ensure_snapshot_restarts_when_managed_instance_is_already_gone(self):
        already_gone = {
            "stopped": False,
            "reason": "managed_process_not_running",
            "authorization": {"process_gone": True},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "loop_status.json"
            status_path.write_text(json.dumps(status(pid=1234)), encoding="utf-8")
            with patch.object(snapshot_tracker, "LOOP_STATUS_PATH", status_path), \
                    patch.object(snapshot_tracker, "DIAGNOSTICS_PATH", root / "diagnostics.jsonl"), \
                    patch.object(snapshot_tracker, "LOOP_CONSOLE_LOG_PATH", root / "console.log"), \
                    patch.object(snapshot_tracker, "PAUSE_FLAG_PATH", root / "pause.flag"), \
                    patch.object(snapshot_tracker, "SUPERVISOR_LOCK_PATH", root / "supervisor.lock"), \
                    patch.object(snapshot_tracker, "acquire_supervisor_lock", return_value=object()), \
                    patch.object(snapshot_tracker, "release_supervisor_lock"), \
                    patch.object(snapshot_tracker, "pid_is_python", return_value=True), \
                    patch.object(snapshot_tracker, "ensure_decision", return_value="restart"), \
                    patch.object(snapshot_tracker, "supervisor_recovery_guard", return_value={"allowed": True}), \
                    patch.object(snapshot_tracker, "loop_file_offsets", return_value={}), \
                    patch.object(snapshot_tracker, "quarantine_malformed_loop_lines", return_value={}), \
                    patch.object(snapshot_tracker, "stop_loop", return_value=already_gone), \
                    patch.object(
                        snapshot_tracker,
                        "start_loop_detached",
                        return_value={"started": True, "pid": 8765},
                    ) as start:
                result = snapshot_tracker.ensure_loop(now=NOW)

        self.assertEqual(result["action"], "restart")
        self.assertEqual(result["stop"], already_gone)
        start.assert_called_once_with(10.0, now=NOW)

    def test_snapshot_restart_cli_does_not_start_after_blocked_stop(self):
        blocked = {
            "stopped": False,
            "reason": "managed_process_provenance_missing_or_mismatched",
            "authorization": {"process_gone": False},
        }
        with patch.object(snapshot_tracker, "stop_loop", return_value=blocked), \
                patch.object(snapshot_tracker, "start_loop_detached") as start, \
                patch.object(sys, "argv", ["snapshot_tracker", "--restart"]), \
                patch("builtins.print"):
            snapshot_tracker.main()

        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
