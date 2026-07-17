import json
import logging
import os
import sys
import tempfile
import time
import unittest
import warnings
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from weather.operations import supervisor
from weather.operations import bot_daily_roll_supervisor
from weather.operations import windows_processes


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

    def test_file_lock_replaces_fresh_dead_owner_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "supervisor.lock"
            lock_path.write_text("5156", encoding="ascii")

            handle = supervisor.acquire_file_lock(
                lock_path,
                attempts=1,
                stale_after_seconds=120,
                pid_check=lambda pid: int(pid) != 5156,
            )
            try:
                self.assertIsNotNone(handle)
                self.assertNotEqual(lock_path.read_text(encoding="ascii"), "5156")
            finally:
                supervisor.release_file_lock(handle, lock_path)

    def test_file_lock_keeps_fresh_live_owner_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "supervisor.lock"
            lock_path.write_text("5156", encoding="ascii")

            handle = supervisor.acquire_file_lock(
                lock_path,
                attempts=1,
                stale_after_seconds=120,
                pid_check=lambda _pid: True,
            )

        self.assertIsNone(handle)

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

    def test_loop_writer_lock_health_requires_matching_live_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "loop_status.json"
            lock_path = status_path.with_name(".loop_status.json.writer.lock")

            missing = supervisor.loop_writer_lock_health(
                status_path,
                status_pid=1234,
                status_pid_alive=True,
            )
            lock_path.write_text(json.dumps({"pid": 9999}), encoding="utf-8")
            mismatched = supervisor.loop_writer_lock_health(
                status_path,
                status_pid=1234,
                status_pid_alive=True,
            )
            lock_path.write_text(json.dumps({"pid": 1234}), encoding="utf-8")
            healthy = supervisor.loop_writer_lock_health(
                status_path,
                status_pid=1234,
                status_pid_alive=True,
            )

        self.assertFalse(missing["healthy"])
        self.assertEqual(missing["reason"], "writer_lock_missing")
        self.assertFalse(mismatched["healthy"])
        self.assertEqual(mismatched["reason"], "writer_lock_pid_mismatch")
        self.assertTrue(healthy["healthy"])

    def test_persist_supervisor_status_exposes_block_and_exit_code(self):
        now = datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = supervisor.SupervisorSpec(
                name="example",
                module="weather.example",
                status_path=root / "loop_status.json",
                diagnostics_path=root / "diagnostics.jsonl",
                console_log_path=root / "console.log",
            )
            result = supervisor.persist_supervisor_status(
                spec,
                {
                    "action": "backoff",
                    "state": "DEAD",
                    "reason": "restart_backoff_active=30.0s",
                    "recovery_guard": {"allowed": False, "retry_after_seconds": 30.0},
                },
                now=now,
            )
            persisted = supervisor.read_supervisor_status(spec)

        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["ensure_status"], "BLOCKED")
        self.assertEqual(persisted["action"], "backoff")
        self.assertEqual(persisted["recovery_guard"]["retry_after_seconds"], 30.0)
        self.assertEqual(persisted["schema_version"], "loop_supervisor_status_v0.1")

    def test_ensure_exit_code_requires_a_successful_restart_launch(self):
        self.assertEqual(supervisor.ensure_exit_code({"action": "noop"}), 0)
        self.assertEqual(
            supervisor.ensure_exit_code({"action": "restart", "start": {"started": True}}),
            0,
        )
        self.assertEqual(
            supervisor.ensure_exit_code({"action": "restart", "start": {"started": False}}),
            1,
        )
        self.assertEqual(supervisor.ensure_exit_code({"action": "locked"}), 1)

    def test_quarantine_malformed_jsonl_preserves_valid_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop_console.log"
            first = {"time": "2026-06-16T12:00:00+00:00", "status": "ok"}
            second = {"time": "2026-06-16T12:01:00+00:00", "status": "still_ok"}
            path.write_text(
                json.dumps(first) + "\n"
                "Traceback: not json\n"
                + json.dumps(second) + "\n",
                encoding="utf-8",
            )

            result = supervisor.quarantine_malformed_jsonl(path)
            repaired = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            quarantine_rows = [
                json.loads(line)
                for line in Path(result["quarantine_path"]).read_text(encoding="utf-8").splitlines()
            ]
            backup_exists = Path(result["backup_path"]).exists()

        self.assertEqual(result["malformed_lines"], 1)
        self.assertEqual(repaired, [first, second])
        self.assertEqual(quarantine_rows[0]["classification"], "console_text")
        self.assertTrue(backup_exists)

    def test_supervisor_recovery_guard_backs_off_and_opens_circuit(self):
        now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics_path = root / "diagnostics.jsonl"
            spec = supervisor.SupervisorSpec(
                name="example",
                module="weather.example",
                status_path=root / "status.json",
                diagnostics_path=diagnostics_path,
                console_log_path=root / "console.log",
                restart_budget=2,
                restart_backoff_base_seconds=60,
            )

            diagnostics_path.write_text(
                json.dumps({
                    "time": (now - timedelta(seconds=30)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "DEAD",
                }) + "\n",
                encoding="utf-8",
            )
            backoff = supervisor.supervisor_recovery_guard(spec, "restart", now=now)

            diagnostics_path.write_text(
                "\n".join(
                    json.dumps({
                        "time": stamp.isoformat(),
                        "supervisor": "ensure",
                        "action": "restart",
                        "state": "DEAD",
                    })
                    for stamp in (
                        now - timedelta(minutes=10),
                        now - timedelta(minutes=5),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            circuit = supervisor.supervisor_recovery_guard(spec, "restart", now=now)

        self.assertFalse(backoff["allowed"])
        self.assertEqual(backoff["action"], "backoff")
        self.assertGreater(backoff["retry_after_seconds"], 0)
        self.assertFalse(circuit["allowed"])
        self.assertEqual(circuit["action"], "circuit_open")
        self.assertEqual(circuit["recent_recovery_count"], 2)

    def test_stale_code_restarts_do_not_consume_crash_budget(self):
        # A burst of commits makes every collection loop detect stale code and
        # exit cleanly; those benign current-code re-adoptions must not trip the
        # crash breaker. This is the 2026-06-24/25 snapshot-outage root cause:
        # 4 stale-code + 2 crash restarts hit the budget of 6 and went dark.
        now = datetime(2026, 6, 25, 18, 54, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics_path = root / "diagnostics.jsonl"
            spec = supervisor.SupervisorSpec(
                name="snapshot",
                module="weather.example",
                status_path=root / "status.json",
                diagnostics_path=diagnostics_path,
                console_log_path=root / "console.log",
                restart_budget=6,
                restart_backoff_base_seconds=60,
            )
            events = [
                {
                    "time": (now - timedelta(minutes=minutes)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "STALE_CODE",
                    "restart_cause": cause,
                }
                # Both benign re-adoption labels: snapshot uses STALE_CODE, the
                # CLOB/microstructure loop uses runtime_identity. Neither counts.
                for minutes, cause in (
                    (50, "STALE_CODE"),
                    (40, "STALE_CODE"),
                    (30, "runtime_identity"),
                    (20, "runtime_identity"),
                )
            ] + [
                {
                    "time": (now - timedelta(minutes=minutes)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "DEAD",
                    "restart_cause": "DEAD",
                }
                for minutes in (15, 10)
            ]
            diagnostics_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            guard = supervisor.supervisor_recovery_guard(spec, "restart", now=now)

        # Only the 2 crash restarts count toward the budget of 6; the 4 stale-code
        # re-adoptions are excluded, so the breaker stays closed and a relaunch is
        # allowed instead of going dark for the 24h window.
        self.assertEqual(guard["recent_recovery_count"], 2)
        self.assertTrue(guard["allowed"])
        self.assertNotEqual(guard["action"], "circuit_open")

    def test_policy_and_starvation_recycles_do_not_consume_crash_budget(self):
        # Regression (2026-07-03..05): the taker daily-roll worker was recycled
        # hourly for policy_no_edge / infra_starved_* / superseded_code —
        # conditions a restart cannot fix (no tradable edge, stale upstream
        # inputs, code re-adoption). Those recycles exhausted the 12-restart
        # budget by midday and opened the circuit every single day. Only
        # genuine worker-side failures may burn the budget.
        now = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics_path = root / "diagnostics.jsonl"
            spec = supervisor.SupervisorSpec(
                name="taker",
                module="weather.example",
                status_path=root / "status.json",
                diagnostics_path=diagnostics_path,
                console_log_path=root / "console.log",
                restart_budget=4,
                restart_backoff_base_seconds=60,
            )
            benign_causes = [
                "policy_no_edge",
                "infra_starved_snapshot",
                "infra_starved_clob",
                "superseded_code",
                "policy_no_edge",
                "infra_starved_snapshot",
            ]
            events = [
                {
                    "time": (now - timedelta(minutes=60 - 5 * index)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "IDLE",
                    "restart_cause": cause,
                }
                for index, cause in enumerate(benign_causes)
            ] + [
                {
                    "time": (now - timedelta(minutes=8)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "IDLE",
                    "restart_cause": "stale_heartbeat_metadata",
                }
            ]
            diagnostics_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            guard = supervisor.supervisor_recovery_guard(spec, "restart", now=now)

        # Only the stale-heartbeat recycle (a real worker-side wedge) counts.
        self.assertEqual(guard["recent_recovery_count"], 1)
        self.assertTrue(guard["allowed"])
        self.assertNotEqual(guard["action"], "circuit_open")

    def test_readoption_debounce_holds_recent_benign_readoption(self):
        now = datetime(2026, 6, 27, 5, 20, tzinfo=timezone.utc)
        # Benign re-adoption (stale_code) of a process that started 3 min ago is
        # held: relaunching again would kill the loop mid-iteration and starve
        # the tail markets before they are reached.
        held = supervisor.readoption_debounce(
            runtime_code_state="stale_code",
            process_started_at=(now - timedelta(minutes=3)).isoformat(),
            now=now,
            debounce_seconds=900.0,
        )
        self.assertTrue(held["debounced"])
        self.assertGreater(held["retry_after_seconds"], 0)

        # Once the window elapses the re-adoption is allowed.
        allowed = supervisor.readoption_debounce(
            runtime_code_state="runtime_identity",
            process_started_at=(now - timedelta(minutes=20)).isoformat(),
            now=now,
            debounce_seconds=900.0,
        )
        self.assertFalse(allowed["debounced"])
        self.assertEqual(allowed["reason"], "debounce_window_elapsed")

    def test_readoption_debounce_never_holds_crash_restart(self):
        now = datetime(2026, 6, 27, 5, 20, tzinfo=timezone.utc)
        # A genuine crash/hang restart (non-benign cause) is never debounced,
        # even seconds after the process started.
        result = supervisor.readoption_debounce(
            runtime_code_state="DEAD",
            process_started_at=(now - timedelta(seconds=5)).isoformat(),
            now=now,
            debounce_seconds=900.0,
        )
        self.assertFalse(result["debounced"])
        self.assertEqual(result["reason"], "not_benign_readoption")

    def test_circuit_open_diagnostic_emits_once_per_breaker_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics_path = root / "diagnostics.jsonl"
            spec = supervisor.SupervisorSpec(
                name="example",
                module="weather.example",
                status_path=root / "status.json",
                diagnostics_path=diagnostics_path,
                console_log_path=root / "console.log",
                restart_budget=2,
            )
            event = {
                "time": "2026-06-16T12:00:00+00:00",
                "supervisor": "ensure",
                "action": "circuit_open",
                "intended_action": "start",
                "remediation": "inspect diagnostics, then run an explicit restart",
                "recovery_guard": {
                    "action": "circuit_open",
                    "loop": "example",
                    "requested_action": "start",
                    "last_recovery_at_utc": "2026-06-16T11:59:00+00:00",
                    "restart_budget": 2,
                    "restart_budget_window_hours": 24.0,
                    "remediation": "inspect diagnostics, then run an explicit restart",
                },
            }

            self.assertTrue(supervisor.should_emit_recovery_block_diagnostic(spec, event))
            diagnostics_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            duplicate = {
                **event,
                "time": "2026-06-16T12:01:00+00:00",
                "reason": "restart_budget_exceeded=8>=2",
            }
            next_trip = {
                **event,
                "recovery_guard": {
                    **event["recovery_guard"],
                    "last_recovery_at_utc": "2026-06-16T12:30:00+00:00",
                },
            }

            self.assertFalse(supervisor.should_emit_recovery_block_diagnostic(spec, duplicate))
            self.assertTrue(supervisor.should_emit_recovery_block_diagnostic(spec, next_trip))
            self.assertTrue(supervisor.should_emit_recovery_block_diagnostic(spec, {"action": "backoff"}))

    def test_recent_recovery_events_skips_large_non_supervisor_lines(self):
        now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            diagnostics_path = Path(tmp) / "diagnostics.jsonl"
            market_row = {
                "time": (now - timedelta(minutes=1)).isoformat(),
                "markets": {"atlanta": {"payload": "x" * 1_000_000}},
            }
            recovery_row = {
                "time": now.isoformat(),
                "supervisor": "ensure",
                "action": "restart",
                "state": "DEAD",
            }
            diagnostics_path.write_text(
                json.dumps(market_row) + "\n" + json.dumps(recovery_row) + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(supervisor.json, "loads", wraps=json.loads) as loads:
                events = supervisor.recent_recovery_events(
                    diagnostics_path,
                    now=now,
                    window_hours=24,
                )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"]["action"], "restart")
        self.assertEqual(loads.call_count, 1)

    def test_configure_json_console_logging_emits_valid_json_lines(self):
        root_logger = logging.getLogger()
        old_handlers = list(root_logger.handlers)
        old_level = root_logger.level
        stream = StringIO()
        try:
            supervisor.configure_json_console_logging(stream=stream, level=logging.WARNING)
            logging.getLogger("weather.test").warning("cache lock busy: %s", "unit")
        finally:
            root_logger.handlers = old_handlers
            root_logger.setLevel(old_level)
            logging.captureWarnings(False)

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["logger"], "weather.test")
        self.assertEqual(payload["message"], "cache lock busy: unit")

    def test_configure_json_console_logging_routes_python_warnings(self):
        root_logger = logging.getLogger()
        old_handlers = list(root_logger.handlers)
        old_level = root_logger.level
        stream = StringIO()
        try:
            supervisor.configure_json_console_logging(stream=stream, level=logging.WARNING)
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn("raw warning should be JSON", UserWarning)
        finally:
            root_logger.handlers = old_handlers
            root_logger.setLevel(old_level)
            logging.captureWarnings(False)

        payload = json.loads(stream.getvalue().strip())
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["logger"], "py.warnings")
        self.assertIn("raw warning should be JSON", payload["message"])

    def test_daily_roll_health_does_not_restart_content_only_starvation(self):
        now = datetime(2026, 6, 18, 4, 20, tzinfo=timezone.utc)
        status = {
            "status": "started",
            "target_date": "2026-06-18",
            "started_at_utc": "2026-06-18T04:00:00+00:00",
            "pid": 7654,
            "artifact_liveness": {
                "ok": False,
                "status": "INFRA_STARVED_SNAPSHOT",
                "root_cause_class": "infra_starved_snapshot",
                "latest_useful_artifact": {
                    "path": "run_summary.json",
                    "modified_at_utc": "2026-06-18T04:19:30+00:00",
                    "age_seconds": 30,
                },
            },
            "latest_tick_scoring_liveness": {
                "status": "BLOCK",
                "classification": "infra_starved_snapshot",
                "countability_status": "NON_COUNTABLE",
                "latest_tick_rows": 132,
                "restart_recommended": False,
            },
            "operator_report": {
                "restart_recommended": False,
                "evidence_countability_status": "NON_COUNTABLE",
            },
        }

        health = bot_daily_roll_supervisor.daily_roll_health(
            status,
            target_date="2026-06-18",
            now=now,
            pid_alive=lambda pid, target_date=None: True,
        )

        self.assertEqual(health["state"], "RUNNING")
        self.assertEqual(health["action"], "noop")
        self.assertIsNone(health["restart_cause"])

    def test_daily_roll_health_still_restarts_scoring_crash(self):
        now = datetime(2026, 6, 18, 4, 20, tzinfo=timezone.utc)
        status = {
            "status": "started",
            "target_date": "2026-06-18",
            "started_at_utc": "2026-06-18T04:00:00+00:00",
            "pid": 7654,
            "artifact_liveness": {
                "ok": False,
                "status": "SCORING_CRASH",
                "root_cause_class": "scoring_crash",
            },
            "latest_tick_scoring_liveness": {
                "status": "BLOCK",
                "classification": "scoring_crash",
                "root_cause_class": "scoring_crash",
                "restart_recommended": True,
            },
        }

        health = bot_daily_roll_supervisor.daily_roll_health(
            status,
            target_date="2026-06-18",
            now=now,
            pid_alive=lambda pid, target_date=None: True,
        )

        self.assertEqual(health["state"], "IDLE")
        self.assertEqual(health["action"], "restart")
        self.assertEqual(health["restart_cause"], "scoring_crash")

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

    def test_managed_process_authorization_requires_exact_command_and_creation_token(self):
        command = ["C:/Python/python.exe", "-m", "weather.example", "loop", "--interval", "10"]
        identity = {
            "pid": 123,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        status = {"pid": 123, "managed_process": identity}
        lock = {"exists": True, "pid": 123, "managed_process": dict(identity)}

        authorized = supervisor.authorize_managed_process_termination(
            status,
            lock,
            command,
            observe_fn=lambda _pid: {
                "state": "running",
                "pid": 123,
                "argv": command,
                "command_line": "managed command",
                "creation_time_token": "win32-filetime:100",
                "inspectable": True,
            },
        )

        self.assertTrue(authorized["authorized"])
        self.assertEqual(authorized["reason"], "exact_managed_process_confirmed")

    def test_managed_stop_expected_command_adopts_pythonw_sibling_from_status(self):
        canonical = ["C:/venv/Scripts/python.exe", "-m", "weather.example", "--loop", "--interval", "10"]
        recorded = ["C:/venv/Scripts/pythonw.exe", "-m", "weather.example", "--loop", "--interval", "10"]
        status = {
            "pid": 123,
            "managed_process": {"pid": 123, "expected_command": list(recorded)},
        }

        self.assertEqual(
            supervisor.managed_stop_expected_command(status, canonical),
            recorded,
        )
        # The adopted expectation authorizes the recorded pythonw worker.
        identity = {
            "pid": 123,
            "expected_command": list(recorded),
            "creation_time_token": "win32-filetime:100",
        }
        authorized = supervisor.authorize_managed_process_termination(
            {"pid": 123, "managed_process": identity},
            {"exists": False},
            supervisor.managed_stop_expected_command(status, canonical),
            observe_fn=lambda _pid: {
                "state": "running",
                "pid": 123,
                "argv": list(recorded),
                "command_line": "managed command",
                "creation_time_token": "win32-filetime:100",
                "inspectable": True,
            },
        )
        self.assertTrue(authorized["authorized"])

    def test_managed_stop_expected_command_falls_back_to_canonical_on_any_other_difference(self):
        canonical = ["C:/venv/Scripts/python.exe", "-m", "weather.example", "--loop", "--interval", "10"]
        cases = {
            "different_module": ["C:/venv/Scripts/pythonw.exe", "-m", "weather.other", "--loop", "--interval", "10"],
            "different_args": ["C:/venv/Scripts/pythonw.exe", "-m", "weather.example", "--loop", "--interval", "60"],
            "different_directory": ["C:/otherenv/Scripts/pythonw.exe", "-m", "weather.example", "--loop", "--interval", "10"],
            "non_python_executable": ["C:/venv/Scripts/other.exe", "-m", "weather.example", "--loop", "--interval", "10"],
            "different_length": ["C:/venv/Scripts/pythonw.exe", "-m", "weather.example", "--loop"],
        }
        for label, recorded in cases.items():
            with self.subTest(label):
                status = {"managed_process": {"expected_command": recorded}}
                self.assertEqual(
                    supervisor.managed_stop_expected_command(status, canonical),
                    canonical,
                )
        self.assertEqual(
            supervisor.managed_stop_expected_command(None, canonical), canonical
        )
        self.assertEqual(
            supervisor.managed_stop_expected_command({}, canonical), canonical
        )

    def test_managed_command_comparison_keeps_non_executable_arguments_case_sensitive(self):
        expected = [
            "C:/Python/python.exe",
            "-m",
            "weather.example",
            "loop",
            "--market",
            "all",
        ]

        self.assertTrue(supervisor.commands_match_exact(list(expected), expected))
        self.assertFalse(
            supervisor.commands_match_exact(
                [*expected[:-1], "ALL"],
                expected,
            )
        )

    @unittest.skipUnless(
        os.name == "nt" and sys.prefix != sys.base_prefix,
        "Windows venv redirector semantics",
    )
    def test_managed_command_accepts_only_current_windows_venv_base_resolution(self):
        for executable_name in ("python.exe", "pythonw.exe"):
            with self.subTest(executable_name=executable_name):
                expected = [
                    str(Path(sys.prefix) / "Scripts" / executable_name),
                    "-m",
                    "weather.example",
                    "loop",
                    "--interval",
                    "10",
                ]
                observed = [
                    str(Path(sys.base_prefix) / executable_name),
                    *expected[1:],
                ]
                other_executable_name = (
                    "pythonw.exe" if executable_name == "python.exe" else "python.exe"
                )

                self.assertTrue(supervisor.commands_match_exact(observed, expected))
                self.assertFalse(
                    supervisor.commands_match_exact(
                        [
                            str(Path(sys.base_prefix) / other_executable_name),
                            *expected[1:],
                        ],
                        expected,
                    )
                )
                self.assertFalse(
                    supervisor.commands_match_exact(
                        [
                            str(Path(sys.base_prefix).parent / "UnrelatedPython" / executable_name),
                            *expected[1:],
                        ],
                        expected,
                    )
                )
                self.assertFalse(
                    supervisor.commands_match_exact(
                        observed,
                        [
                            str(Path(sys.prefix).parent / "other-venv" / "Scripts" / executable_name),
                            *expected[1:],
                        ],
                    )
                )
                self.assertFalse(
                    supervisor.commands_match_exact(
                        [*observed[:-1], "11"],
                        expected,
                    )
                )

    @unittest.skipUnless(
        os.name == "nt" and sys.prefix != sys.base_prefix,
        "Windows venv redirector semantics",
    )
    def test_capture_identity_records_verified_windows_venv_resolution(self):
        expected = [
            str(Path(sys.prefix) / "Scripts" / "python.exe"),
            "-m",
            "weather.example",
            "loop",
        ]
        observed_executable = str(Path(sys.base_prefix) / "python.exe")

        identity = supervisor.capture_managed_process_identity(
            123,
            expected,
            observe_fn=lambda _pid: {
                "state": "running",
                "pid": 123,
                "argv": [observed_executable, *expected[1:]],
                "command_line": "managed command",
                "image_path": observed_executable,
                "creation_time_token": "win32-filetime:100",
                "inspectable": True,
            },
        )

        self.assertTrue(identity["verified_at_capture"])
        self.assertEqual(identity["expected_command"], expected)
        self.assertEqual(identity["observed_executable"], observed_executable)
        self.assertEqual(identity["observed_image_path"], observed_executable)

    def test_managed_process_authorization_rejects_reused_pid_and_command_mismatch(self):
        command = ["C:/Python/python.exe", "-m", "weather.example", "loop"]
        identity = {
            "pid": 123,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        status = {"pid": 123, "managed_process": identity}
        lock = {"exists": True, "pid": 123, "managed_process": dict(identity)}

        reused = supervisor.authorize_managed_process_termination(
            status,
            lock,
            command,
            observe_fn=lambda _pid: {
                "state": "running",
                "pid": 123,
                "argv": command,
                "creation_time_token": "win32-filetime:200",
                "inspectable": True,
            },
        )
        mismatched_command = supervisor.authorize_managed_process_termination(
            status,
            lock,
            command,
            observe_fn=lambda _pid: {
                "state": "running",
                "pid": 123,
                "argv": ["C:/Python/python.exe", "-m", "weather.other", "loop"],
                "creation_time_token": "win32-filetime:100",
                "inspectable": True,
            },
        )

        self.assertFalse(reused["authorized"])
        self.assertEqual(reused["reason"], "reused_pid_process_instance_mismatch")
        self.assertFalse(mismatched_command["authorized"])
        self.assertEqual(mismatched_command["reason"], "managed_process_command_mismatch")

    def test_managed_process_authorization_fails_closed_on_unknown_or_live_lock_mismatch(self):
        command = ["C:/Python/python.exe", "-m", "weather.example", "loop"]
        identity = {
            "pid": 123,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        status = {"pid": 123, "managed_process": identity}

        unknown = supervisor.authorize_managed_process_termination(
            status,
            {"exists": False},
            command,
            observe_fn=lambda _pid: {"state": "unknown", "pid": 123},
        )
        mismatched_lock = supervisor.authorize_managed_process_termination(
            status,
            {"exists": True, "pid": 999},
            command,
            observe_fn=lambda pid: {
                "state": "running",
                "pid": pid,
                "inspectable": False,
            },
        )

        self.assertEqual(unknown["reason"], "live_process_identity_uninspectable")
        self.assertEqual(
            mismatched_lock["reason"],
            "mismatched_writer_lock_owner_is_authoritative",
        )

    def test_wait_for_managed_process_exit_distinguishes_same_instance_and_reused_pid(self):
        identity = {"pid": 123, "creation_time_token": "win32-filetime:100"}
        observations = iter([
            {
                "state": "running",
                "pid": 123,
                "creation_time_token": "win32-filetime:100",
            },
            {
                "state": "running",
                "pid": 123,
                "creation_time_token": "win32-filetime:200",
            },
        ])

        result = supervisor.wait_for_managed_process_exit(
            identity,
            observe_fn=lambda _pid: next(observations),
            attempts=2,
            sleep_seconds=0,
        )

        self.assertTrue(result["exited"])
        self.assertEqual(result["reason"], "pid_reused_after_managed_exit")

    def test_replacement_start_requires_confirmed_stop_or_proven_absence(self):
        self.assertTrue(supervisor.managed_stop_allows_start({"stopped": True}))
        self.assertTrue(supervisor.managed_stop_allows_start({
            "stopped": False,
            "authorization": {"process_gone": True},
        }))
        self.assertFalse(supervisor.managed_stop_allows_start({
            "stopped": False,
            "authorization": {"process_gone": False},
        }))
        self.assertFalse(supervisor.managed_stop_allows_start(None))

    @unittest.skipUnless(os.name == "nt", "Windows process snapshot semantics")
    def test_windows_process_snapshot_failure_is_unknown_not_absence(self):
        with mock.patch.object(windows_processes, "snapshot_processes", return_value=None):
            observation = supervisor.observe_process(123)

        self.assertEqual(observation["state"], "unknown")
        self.assertEqual(observation["reason"], "Windows process snapshot unavailable")

    @unittest.skipUnless(os.name == "nt", "Windows handle-scoped termination")
    def test_terminate_managed_process_passes_exact_token_and_command_check_to_handle_backend(self):
        command = ["C:/Python/python.exe", "-m", "weather.example", "loop"]
        identity = {
            "pid": 123,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        captured = {}

        def fake_terminate(pid, **kwargs):
            captured.update({"pid": pid, **kwargs})
            return {"pid": pid, "stopped": False, "reason": "process_command_changed_before_termination"}

        result = supervisor.terminate_managed_process(
            identity,
            command,
            windows_terminate_fn=fake_terminate,
        )

        self.assertFalse(result["stopped"])
        self.assertEqual(captured["pid"], 123)
        self.assertEqual(captured["expected_creation_time_token"], "win32-filetime:100")
        self.assertTrue(captured["command_line_check"]('"C:/Python/python.exe" -m weather.example loop'))
        self.assertFalse(captured["command_line_check"]('"C:/Python/python.exe" -m weather.other loop'))

    @unittest.skipUnless(
        os.name == "nt" and sys.prefix != sys.base_prefix,
        "Windows venv redirector semantics",
    )
    def test_handle_scoped_command_check_accepts_only_current_venv_resolution(self):
        command = [
            str(Path(sys.prefix) / "Scripts" / "python.exe"),
            "-m",
            "weather.example",
            "loop",
        ]
        identity = {
            "pid": 123,
            "expected_command": command,
            "creation_time_token": "win32-filetime:100",
        }
        captured = {}

        def fake_terminate(pid, **kwargs):
            captured.update({"pid": pid, **kwargs})
            return {"pid": pid, "stopped": True, "reason": "verified_process_exited"}

        result = supervisor.terminate_managed_process(
            identity,
            command,
            windows_terminate_fn=fake_terminate,
        )
        command_check = captured["command_line_check"]
        base_executable = Path(sys.base_prefix) / "python.exe"

        self.assertTrue(result["stopped"])
        self.assertTrue(
            command_check(f'"{base_executable}" -m weather.example loop')
        )
        self.assertFalse(
            command_check(
                f'"{Path(sys.base_prefix).parent / "UnrelatedPython" / "python.exe"}" '
                "-m weather.example loop"
            )
        )
        self.assertFalse(
            command_check(f'"{base_executable}" -m weather.other loop')
        )

    @unittest.skipUnless(os.name == "nt", "Windows handle-scoped termination")
    def test_windows_handle_backend_rejects_instance_change_before_terminate(self):
        with mock.patch.object(windows_processes, "_open_process", return_value=object()), \
                mock.patch.object(windows_processes, "_creation_time_token", return_value="win32-filetime:new"), \
                mock.patch.object(windows_processes, "TerminateProcess") as terminate, \
                mock.patch.object(windows_processes, "CloseHandle"):
            result = windows_processes.terminate_verified_process(
                123,
                expected_creation_time_token="win32-filetime:old",
                command_line_check=lambda _command: True,
            )

        self.assertFalse(result["stopped"])
        self.assertEqual(result["reason"], "process_instance_changed_before_termination")
        terminate.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows handle-scoped termination")
    def test_windows_handle_backend_waits_for_exact_instance_exit(self):
        handle = object()
        with mock.patch.object(windows_processes, "_open_process", return_value=handle), \
                mock.patch.object(windows_processes, "_creation_time_token", return_value="win32-filetime:100"), \
                mock.patch.object(windows_processes, "_remote_command_line", return_value="managed command"), \
                mock.patch.object(windows_processes, "TerminateProcess", return_value=True) as terminate, \
                mock.patch.object(windows_processes, "WaitForSingleObject", return_value=windows_processes.WAIT_OBJECT_0) as wait, \
                mock.patch.object(windows_processes, "CloseHandle"):
            result = windows_processes.terminate_verified_process(
                123,
                expected_creation_time_token="win32-filetime:100",
                command_line_check=lambda command: command == "managed command",
            )

        self.assertTrue(result["stopped"])
        self.assertTrue(result["exited"])
        self.assertEqual(result["termination_scope"], "verified_process_handle")
        terminate.assert_called_once_with(handle, 15)
        wait.assert_called_once_with(handle, 2000)


if __name__ == "__main__":
    unittest.main()
