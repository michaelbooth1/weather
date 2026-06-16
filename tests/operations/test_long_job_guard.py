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
)


class TestLongJobGuard(unittest.TestCase):
    def setUp(self):
        self._original_guard_env = os.environ.pop(ACTIVE_ENV_VAR, None)

    def tearDown(self):
        if self._original_guard_env is None:
            os.environ.pop(ACTIVE_ENV_VAR, None)
        else:
            os.environ[ACTIVE_ENV_VAR] = self._original_guard_env

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


if __name__ == "__main__":
    unittest.main()
