import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.operations import supervisor


class FakeProcess:
    pid = 2468


class TestSupervisorPrimitives(unittest.TestCase):
    def test_atomic_json_and_jsonl_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = root / "nested" / "status.json"
            diagnostics_path = root / "diagnostics.jsonl"

            supervisor.atomic_write_json(status_path, {"state": "RUNNING", "pid": 123}, trailing_newline=True)
            supervisor.append_jsonl(diagnostics_path, {"event": "start", "pid": 123})
            supervisor.append_jsonl(diagnostics_path, {"event": "stop", "pid": 123})

            self.assertEqual(supervisor.read_json_file(status_path)["state"], "RUNNING")
            self.assertTrue(status_path.read_text(encoding="utf-8").endswith("\n"))
            rows = [
                json.loads(line)
                for line in diagnostics_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["event"] for row in rows], ["start", "stop"])

    def test_file_lock_acquire_busy_release_and_stale_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "supervisor.lock"
            handle = supervisor.acquire_file_lock(lock_path)
            try:
                self.assertIsNotNone(handle)
                self.assertIsNone(
                    supervisor.acquire_file_lock(lock_path, attempts=1, sleep_fn=lambda _seconds: None)
                )
            finally:
                supervisor.release_file_lock(handle, lock_path)

            stale_time = time.time() - 300
            lock_path.write_text("old", encoding="ascii")
            os.utime(lock_path, (stale_time, stale_time))
            handle = supervisor.acquire_file_lock(lock_path, attempts=2, stale_after_seconds=120)
            try:
                self.assertIsNotNone(handle)
                self.assertNotEqual(lock_path.read_text(encoding="ascii"), "old")
            finally:
                supervisor.release_file_lock(handle, lock_path)

    def test_heartbeat_state_and_age_helpers(self):
        now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
        status = {
            "last_heartbeat": (now - timedelta(seconds=75)).isoformat(),
            "consecutive_errors": 0,
        }

        self.assertEqual(supervisor.age_seconds(now, status["last_heartbeat"]), 75)
        self.assertEqual(
            supervisor.heartbeat_state(
                status,
                now,
                interval_seconds=60,
                dead_after_seconds=150,
            )["state"],
            "RUNNING",
        )
        self.assertEqual(
            supervisor.heartbeat_state(
                {**status, "last_heartbeat": (now - timedelta(seconds=151)).isoformat()},
                now,
                interval_seconds=60,
                dead_after_seconds=150,
            )["state"],
            "DEAD",
        )
        self.assertEqual(
            supervisor.heartbeat_state(
                {**status, "paused": True},
                now,
                interval_seconds=60,
                dead_after_seconds=150,
            )["state"],
            "PAUSED",
        )
        self.assertEqual(
            supervisor.heartbeat_state(
                {**status, "consecutive_errors": 3},
                now,
                interval_seconds=60,
                dead_after_seconds=150,
            )["state"],
            "ERRORING",
        )

    def test_default_ensure_decision(self):
        self.assertEqual(supervisor.default_ensure_decision("RUNNING", True), "noop")
        self.assertEqual(supervisor.default_ensure_decision("ERRORING", True), "noop")
        self.assertEqual(supervisor.default_ensure_decision("DEAD", True), "restart")
        self.assertEqual(supervisor.default_ensure_decision("UNKNOWN", False), "start")
        self.assertEqual(
            supervisor.default_ensure_decision(
                "DEGRADED",
                True,
                tolerated_states=("RUNNING", "PAUSED", "DEGRADED", "ERRORING"),
            ),
            "noop",
        )

    def test_module_command_and_detached_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = supervisor.SupervisorSpec(
                name="example",
                module="weather.example",
                status_path=root / "status.json",
                diagnostics_path=root / "diagnostics.jsonl",
                console_log_path=root / "console.log",
                cwd=root,
            )
            calls = {}

            def fake_popen(command, cwd=None, stdout=None, stderr=None, creationflags=0):
                calls["command"] = command
                calls["cwd"] = cwd
                calls["stdout_closed_during_call"] = stdout.closed
                calls["stderr_is_stdout"] = stderr is stdout
                calls["creationflags"] = creationflags
                return FakeProcess()

            child = supervisor.launch_detached(
                spec.command("loop", "--interval", 10, python_executable="python"),
                cwd=spec.cwd,
                console_log_path=spec.console_log_path,
                popen_fn=fake_popen,
                creationflags=7,
            )

            self.assertEqual(child.pid, 2468)
            self.assertEqual(calls["command"], ["python", "-m", "weather.example", "loop", "--interval", "10"])
            self.assertEqual(calls["cwd"], str(root))
            self.assertFalse(calls["stdout_closed_during_call"])
            self.assertTrue(calls["stderr_is_stdout"])
            self.assertEqual(calls["creationflags"], 7)

    def test_pid_checks_and_termination_are_injectable(self):
        class Result:
            stdout = "python.exe"

        calls = {}

        def fake_run(command, **kwargs):
            calls["command"] = command
            calls["creationflags"] = kwargs.get("creationflags")
            return Result()

        self.assertTrue(supervisor.pid_is_python(123, run_fn=fake_run))
        self.assertFalse(supervisor.pid_is_python("not-a-pid", run_fn=fake_run))
        self.assertIn("123", " ".join(calls["command"]))

        killed = []
        result = supervisor.terminate_python_pid(
            123,
            pid_check=lambda pid: int(pid) == 123,
            kill_fn=lambda pid, signal_number: killed.append((pid, signal_number)),
        )

        self.assertTrue(result["stopped"])
        self.assertEqual(killed[0][0], 123)


if __name__ == "__main__":
    unittest.main()
