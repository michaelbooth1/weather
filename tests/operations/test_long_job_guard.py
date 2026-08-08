import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from weather.operations.long_job_guard import (  # noqa: E402
    ACTIVE_ENV_VAR,
    LongJobBusy,
    acquire_long_job_lock,
    long_job_guard,
    process_is_running,
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

    def wait_for_process_exit(self, pid, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not process_is_running(pid):
                return True
            time.sleep(0.05)
        return not process_is_running(pid)

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

    def test_touch_repairs_historical_completed_count_above_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "guard_status.json"
            lock_path = Path(tmp) / "guard.lock"

            with long_job_guard(
                "unit_test",
                state_path=state_path,
                lock_path=lock_path,
                priority="normal",
            ):
                touch_long_job_guard(
                    state_path,
                    progress={
                        "last_completed_step": "closed_day_parquet_incremental",
                        "completed_step_count": 14,
                        "total_step_count": 13,
                    },
                )
                running = json.loads(state_path.read_text(encoding="utf-8"))

        progress = running["progress"]
        self.assertEqual(progress["completed_step_count"], 14)
        self.assertEqual(progress["total_step_count"], 14)
        self.assertEqual(
            progress["progress_counter_repair"]["original_total_step_count"],
            13,
        )

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
            # 64 MiB does not start a CPython 3.11 interpreter on this host.
            # ``working_set_max_bytes`` doubles as the Job private-COMMIT cap when
            # no private_memory_max_bytes is given (long_job_guard.py ~1070), so the
            # child died with STATUS_QUOTA_EXCEEDED (0xC0000044) before running.
            # Measured 2026-08-08: 64 MiB fails, 96 MiB is the first that starts.
            # 256 MiB matches every other cap in this file and keeps the margin.
            working_set_max_bytes=256 * 1024 * 1024,
        )

        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])
        self.assertIn("isolated-ok", result["stdout"])
        self.assertEqual(result["containment"]["status"], "PASS")
        self.assertTrue(result["containment"]["process_tree_contained"])
        self.assertFalse(result["termination"]["triggered"])
        self.assertTrue(result["working_set_limit"]["requested"])
        self.assertIn("read_bytes", result["resource_io"])
        self.assertIn("write_bytes", result["resource_io"])
        if os.name == "nt":
            self.assertTrue(result["working_set_limit"]["applied"])
            self.assertEqual(result["containment"]["method"], "windows_job_object")
            self.assertEqual(
                result["resource_io"]["source"],
                "windows_job_object_lifetime",
            )
            self.assertTrue(result["containment"]["assigned_before_resume"])
            self.assertGreaterEqual(result["containment"]["accounting"]["total_processes"], 2)
            lifetime = result["resource_peaks"]["process_lifetime"]
            self.assertEqual(lifetime["status"], "PASS", lifetime)
            self.assertEqual(
                lifetime["tracked_process_count"],
                result["containment"]["accounting"]["total_processes"],
            )
            self.assertEqual(
                lifetime["closed_handle_count"],
                lifetime["retained_handle_count"],
            )
            self.assertTrue(
                lifetime["checks"][
                    "completion_port_associated_before_assignment"
                ]
            )
            self.assertTrue(
                lifetime["checks"]["completion_queue_flushed"]
            )
            self.assertTrue(
                all(
                    row["job_membership_verified"]
                    for row in lifetime["processes"]
                )
            )
            self.assertGreaterEqual(
                result["resource_peaks"]["working_set_peak_bytes"],
                result["resource_peaks"]["sampled_working_set_peak_bytes"],
            )
        else:
            self.assertEqual(result["working_set_limit"]["reason"], "non_windows")

    def test_isolated_subprocess_retains_only_bounded_child_output(self):
        result = run_isolated_subprocess(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.write('x'*200000);sys.stdout.flush()",
            ],
            timeout_seconds=60,
            # 64 MiB does not start a CPython 3.11 interpreter on this host.
            # ``working_set_max_bytes`` doubles as the Job private-COMMIT cap when
            # no private_memory_max_bytes is given (long_job_guard.py ~1070), so the
            # child died with STATUS_QUOTA_EXCEEDED (0xC0000044) before running.
            # Measured 2026-08-08: 64 MiB fails, 96 MiB is the first that starts.
            # 256 MiB matches every other cap in this file and keeps the margin.
            working_set_max_bytes=256 * 1024 * 1024,
            output_tail_chars=1024,
            output_max_bytes=4096,
        )

        self.assertEqual(
            result["resource_limit_exceeded"]["resource"],
            "child_output_bytes",
        )
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), 1024)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object lifetime accounting")
    def test_fast_child_accepts_lifetime_io_accounting_without_live_sample(self):
        unavailable_sample = {
            "available": False,
            "process_count": 0,
            "working_set_bytes": 0,
            "private_bytes": 0,
            "io_accounting_available": True,
            "read_bytes": 0,
            "write_bytes": 0,
        }
        with patch(
            "weather.operations.long_job_guard._contained_process_memory_metrics",
            return_value=unavailable_sample,
        ):
            result = run_isolated_subprocess(
                [sys.executable, "-c", "pass"],
                timeout_seconds=60,
                io_read_max_bytes=512 * 1024 * 1024,
                io_write_max_bytes=512 * 1024 * 1024,
            )

        self.assertIsNone(result["runner_error"], result)
        self.assertIsNone(result["resource_limit_exceeded"], result)
        self.assertEqual(
            result["resource_io"]["source"],
            "windows_job_object_lifetime",
        )
        self.assertTrue(result["resource_io"]["enforcement_verified"])

    @unittest.skipUnless(os.name == "nt", "Windows terminal lifetime peaks")
    def test_terminal_handle_captures_late_descendant_peak_between_samples(self):
        descendant = (
            "import time;"
            "time.sleep(0.8);"
            "payload=bytearray(64*1024*1024);"
            "sum(payload[::4096]);"
            "time.sleep(0.05)"
        )
        launcher = (
            "import subprocess,sys;"
            f"child=subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
            "raise SystemExit(child.wait())"
        )
        result = run_isolated_subprocess(
            [sys.executable, "-c", launcher],
            timeout_seconds=30,
            working_set_max_bytes=512 * 1024 * 1024,
            private_memory_max_bytes=512 * 1024 * 1024,
            resource_sample_interval_seconds=0.5,
        )

        self.assertEqual(result["returncode"], 0, result)
        lifetime = result["resource_peaks"]["process_lifetime"]
        self.assertEqual(lifetime["status"], "PASS", lifetime)
        self.assertTrue(
            lifetime["checks"][
                "completion_port_associated_before_assignment"
            ]
        )
        self.assertTrue(lifetime["checks"]["completion_queue_flushed"])
        self.assertTrue(
            all(
                row["job_membership_verified"]
                for row in lifetime["processes"]
            )
        )
        self.assertGreaterEqual(lifetime["tracked_process_count"], 2)
        self.assertGreaterEqual(
            lifetime["lifetime_working_set_upper_bound_bytes"],
            48 * 1024 * 1024,
        )
        self.assertGreater(
            lifetime["lifetime_working_set_upper_bound_bytes"],
            result["resource_peaks"]["sampled_working_set_peak_bytes"],
        )
        self.assertEqual(
            result["resource_peaks"]["working_set_peak_bytes"],
            lifetime["lifetime_working_set_upper_bound_bytes"],
        )

    def test_timeout_kills_launcher_descendants_without_touching_unrelated_process(self):
        base_python = getattr(sys, "_base_executable", sys.executable)
        sentinel = subprocess.Popen([base_python, "-c", "import time; time.sleep(60)"])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                child_pid_path = Path(tmp) / "child.pid"
                launcher = (
                    "import pathlib,subprocess,sys,time;"
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                    "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                    f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid));"
                    "print('launcher-ready', flush=True);"
                    "time.sleep(60)"
                )
                result = run_isolated_subprocess(
                    [sys.executable, "-c", launcher],
                    timeout_seconds=1,
                    working_set_max_bytes=256 * 1024 * 1024,
                )
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))

            self.assertTrue(result["timed_out"], result)
            self.assertEqual(result["containment"]["status"], "PASS", result)
            self.assertTrue(result["termination"]["triggered"])
            self.assertEqual(result["termination"]["reason"], "timeout")
            self.assertTrue(self.wait_for_process_exit(result["pid"]))
            self.assertTrue(self.wait_for_process_exit(child_pid))
            self.assertTrue(process_is_running(sentinel.pid))
            if os.name == "nt":
                self.assertEqual(result["termination"]["method"], "TerminateJobObject")
                self.assertGreaterEqual(result["containment"]["accounting"]["total_processes"], 3)
            else:
                self.assertEqual(result["termination"]["method"], "os.killpg")
        finally:
            sentinel.terminate()
            try:
                sentinel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sentinel.kill()
                sentinel.wait(timeout=5)

    def test_nonzero_launcher_exit_cleans_up_background_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            child_pid_path = Path(tmp) / "child.pid"
            launcher = (
                "import pathlib,subprocess,sys;"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid));"
                "sys.exit(7)"
            )
            result = run_isolated_subprocess(
                [sys.executable, "-c", launcher],
                timeout_seconds=20,
                working_set_max_bytes=256 * 1024 * 1024,
            )
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        self.assertEqual(result["returncode"], 7)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["containment"]["status"], "PASS", result)
        self.assertTrue(result["termination"]["triggered"])
        self.assertEqual(result["termination"]["reason"], "descendant_cleanup")
        self.assertTrue(self.wait_for_process_exit(child_pid))

    @unittest.skipUnless(os.name == "nt", "Windows Job Object memory limit")
    def test_job_memory_limit_applies_to_real_venv_interpreter_descendant(self):
        maximum = 96 * 1024 * 1024
        result = run_isolated_subprocess(
            [
                sys.executable,
                "-c",
                "payload=bytearray(256*1024*1024);print(len(payload))",
            ],
            timeout_seconds=30,
            working_set_max_bytes=maximum,
        )

        self.assertNotEqual(result["returncode"], 0, result)
        self.assertEqual(result["containment"]["status"], "PASS")
        self.assertTrue(result["working_set_limit"]["job_commit_cap"])
        self.assertTrue(result["working_set_limit"]["working_set_cap"])
        self.assertIsNotNone(result["resource_limit_exceeded"], result)
        self.assertEqual(
            result["resource_limit_exceeded"]["resource"],
            "private_memory_bytes",
        )
        self.assertGreaterEqual(result["containment"]["accounting"]["total_processes"], 2)
        self.assertLessEqual(
            result["containment"]["accounting"]["peak_job_memory_bytes"],
            maximum,
        )

    @unittest.skipUnless(os.name == "nt", "Windows sampled working-set fallback")
    def test_missing_working_set_sampler_fails_closed(self):
        with patch(
            "weather.operations.long_job_guard._contained_process_memory_metrics",
            return_value={"available": False, "process_count": 0},
        ):
            result = run_isolated_subprocess(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout_seconds=30,
                working_set_max_bytes=256 * 1024 * 1024,
                private_memory_max_bytes=512 * 1024 * 1024,
                resource_sample_interval_seconds=0.02,
                resource_sampling_grace_seconds=0.1,
            )

        self.assertEqual(
            result["resource_limit_exceeded"]["resource"],
            "working_set_enforcement",
        )
        self.assertEqual(result["termination"]["reason"], "resource_budget_exceeded")
        self.assertFalse(
            result["working_set_limit"]["working_set_enforcement_verified"]
        )


if __name__ == "__main__":
    unittest.main()
