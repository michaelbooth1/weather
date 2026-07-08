import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.operations.long_job_guard import (  # noqa: E402
    ACTIVE_ENV_VAR,
    LongJobBusy,
    acquire_long_job_lock,
    long_job_guard,
    release_long_job_lock,
    run_isolated_subprocess,
    touch_long_job_guard,
)


class TestLongJobGuard(unittest.TestCase):
    def setUp(self):
        self._original_guard_env = os.environ.pop(ACTIVE_ENV_VAR, None)

    def tearDown(self):
        if self._original_guard_env is None:
            os.environ.pop(ACTIVE_ENV_VAR, None)
        else:
            os.environ[ACTIVE_ENV_VAR] = self._original_guard_env

    @unittest.skipUnless(os.name == "nt", "Windows SetPriorityClass path")
    def test_lower_process_priority_applies_on_windows(self):
        # Run in a subprocess so the test runner's own priority is untouched.
        # Regression: without ctypes restype/argtypes the pseudo-handle is
        # truncated on 64-bit Windows and SetPriorityClass always fails.
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json;"
                    "from weather.operations.long_job_guard import lower_process_priority;"
                    "print(json.dumps(lower_process_priority('below_normal')))"
                ),
            ],
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
        )
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload["applied"], payload)
        self.assertEqual(payload["method"], "SetPriorityClass")
        # Regression (2026-07-03): CPU priority alone let a 7 GB replay evict
        # the collection loops' pages and stall capture for ~80 minutes; the
        # guard must also lower memory priority so the long job's pages are
        # trimmed first under pressure.
        memory = payload.get("memory_priority") or {}
        self.assertTrue(memory.get("applied"), payload)
        self.assertEqual(memory.get("memory_priority"), 4)

    def test_guard_writes_running_and_complete_state_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with long_job_guard(
                "unit_test",
                state_path=state_path,
                lock_path=lock_path,
                priority="normal",
            ) as guard:
                running = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertTrue(lock_path.exists())
                self.assertEqual(os.environ.get(ACTIVE_ENV_VAR), str(os.getpid()))
                self.assertTrue(guard["enabled"])
                self.assertFalse(guard["nested"])
                self.assertEqual(running["status"], "running")
                self.assertTrue(running["active"])
                self.assertEqual(running["job_name"], "unit_test")
                self.assertEqual(running["priority"]["requested"], "normal")

            complete = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(lock_path.exists())
            self.assertNotIn(ACTIVE_ENV_VAR, os.environ)
            self.assertEqual(complete["status"], "complete")
            self.assertFalse(complete["active"])
            self.assertGreaterEqual(complete["duration_seconds"], 0.0)

    def test_touch_updates_running_guard_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with long_job_guard(
                "unit_test",
                state_path=state_path,
                lock_path=lock_path,
                priority="normal",
            ):
                result = touch_long_job_guard(
                    state_path,
                    progress={
                        "last_completed_step": "daily_learning",
                        "completed_step_count": 3,
                        "total_step_count": 8,
                    },
                )
                running = json.loads(state_path.read_text(encoding="utf-8"))

            complete = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(result["updated"])
        self.assertEqual(running["progress"]["last_completed_step"], "daily_learning")
        self.assertEqual(running["progress"]["completed_step_count"], 3)
        self.assertIn("last_progress_at_utc", running)
        self.assertEqual(complete["progress"]["last_completed_step"], "daily_learning")
        self.assertEqual(complete["status"], "complete")

    def test_guard_records_error_state_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with self.assertRaisesRegex(RuntimeError, "boom"):
                with long_job_guard(
                    "unit_test",
                    state_path=state_path,
                    lock_path=lock_path,
                    priority="normal",
                ):
                    raise RuntimeError("boom")

            failed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(lock_path.exists())
            self.assertNotIn(ACTIVE_ENV_VAR, os.environ)
            self.assertEqual(failed["status"], "error")
            self.assertFalse(failed["active"])
            self.assertIn("RuntimeError: boom", failed["error"])

    def test_guard_does_not_suppress_error_when_state_file_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with self.assertRaisesRegex(RuntimeError, "boom"):
                with long_job_guard(
                    "unit_test",
                    state_path=state_path,
                    lock_path=lock_path,
                    priority="normal",
                ):
                    state_path.unlink()
                    raise RuntimeError("boom")

            self.assertFalse(lock_path.exists())
            self.assertNotIn(ACTIVE_ENV_VAR, os.environ)

    def test_nested_guard_reuses_outer_process_guard_without_locking(self):
        os.environ[ACTIVE_ENV_VAR] = "outer"
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with long_job_guard(
                "nested",
                state_path=state_path,
                lock_path=lock_path,
                priority="normal",
            ) as guard:
                self.assertTrue(guard["enabled"])
                self.assertTrue(guard["nested"])
                self.assertFalse(lock_path.exists())
                self.assertFalse(state_path.exists())

    def test_guard_blocks_when_another_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"
            lock = acquire_long_job_lock(lock_path, "already_running")
            try:
                with self.assertRaises(LongJobBusy):
                    with long_job_guard(
                        "contender",
                        state_path=state_path,
                        lock_path=lock_path,
                        priority="normal",
                    ):
                        pass
            finally:
                release_long_job_lock(lock)

    def test_guard_replaces_stale_lock_from_dead_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"
            lock_path.write_text(
                json.dumps({
                    "schema_version": "long_job_guard_v0.1",
                    "job_name": "stale",
                    "pid": 999999999,
                    "started_at_utc": "2026-01-01T00:00:00+00:00",
                }),
                encoding="utf-8",
            )

            with long_job_guard(
                "replacement",
                state_path=state_path,
                lock_path=lock_path,
                priority="normal",
            ):
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["job_name"], "replacement")
                self.assertEqual(payload["pid"], os.getpid())

    def test_isolated_subprocess_returns_output_and_working_set_status(self):
        result = run_isolated_subprocess(
            [sys.executable, "-c", "print('isolated-ok')"],
            timeout_seconds=60,
            working_set_max_bytes=64 * 1024 * 1024,
        )

        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])
        self.assertIn("isolated-ok", result["stdout"])
        self.assertTrue(result["working_set_limit"]["requested"])
        if os.name == "nt":
            self.assertIn("applied", result["working_set_limit"])
        else:
            self.assertEqual(result["working_set_limit"]["reason"], "non_windows")


if __name__ == "__main__":
    unittest.main()
