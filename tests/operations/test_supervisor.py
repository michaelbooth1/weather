import json
import logging
import os
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


if __name__ == "__main__":
    unittest.main()
