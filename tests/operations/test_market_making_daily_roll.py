import csv
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from weather.market.mm_scoring_projection import (  # noqa: E402
    BASE_PROJECTION_FILENAME,
    MANIFEST_FILENAME,
    MODEL_VARIANT_PROJECTION_FILENAME,
    SCORING_COLUMNS,
)
from weather.operations.market_making_daily_roll import (  # noqa: E402
    build_market_making_command,
    ensure_for_date,
    load_status,
    market_making_activity_paths,
    market_making_artifact_health,
    start_for_date,
    stop_status_file,
    target_date_for_roll,
)


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def _write_status(path, tmp, *, started_at="2026-06-16T23:00:00+00:00", pid=4321):
    path.write_text(json.dumps({
        "schema_version": "market_making_daily_roll_v0.2",
        "runner": "market_making_daily_roll",
        "generated_at_utc": started_at,
        "started_at_utc": started_at,
        "target_date": "2026-06-16",
        "status": "started",
        "pid": pid,
        "runs_root": str(tmp / "mm_runs"),
        "console_log_path": str(tmp / "daily_roll_console.log"),
        "command": ["python.exe", "-m", "weather.market.market_making_run"],
        "runtime_identity": {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "current",
            "source_fingerprint": "current",
        },
    }), encoding="utf-8")


def _write_run_artifacts(
    run_folder,
    *,
    timestamp,
    summary=None,
    live_forward_gate=None,
    include_quote=True,
    include_run_summary=True,
):
    run_folder.mkdir(parents=True, exist_ok=True)
    if include_quote:
        quote = run_folder / "quote_intents_long.csv"
        quote.write_text("market_id,reason_code\natlanta,NO_QUOTE_EDGE_TOO_SMALL\n", encoding="utf-8")
        os.utime(quote, (timestamp, timestamp))
    for name in ("budget_ledger.jsonl", "order_lifecycle.jsonl"):
        path = run_folder / name
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (timestamp, timestamp))
    if include_run_summary:
        run_summary = run_folder / "run_summary.json"
        run_summary.write_text(json.dumps(summary or {"row_count": 1}), encoding="utf-8")
        os.utime(run_summary, (timestamp, timestamp))
    if live_forward_gate is not None:
        gate = run_folder / "live_forward_gate.json"
        gate.write_text(json.dumps(live_forward_gate), encoding="utf-8")
        os.utime(gate, (timestamp, timestamp))


def _write_scoring_source_tape(run_folder):
    run_folder.mkdir(parents=True, exist_ok=True)
    quote_path = run_folder / "quote_intents_long.csv"
    row = {column: "" for column in SCORING_COLUMNS}
    row.update({
        "run_id": run_folder.name,
        "target_date": run_folder.parent.name,
        "generated_at_utc": "2026-06-16T23:59:00+00:00",
        "market_id": "atlanta",
        "reason_code": "NO_QUOTE_EDGE_TOO_SMALL",
    })
    with quote_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SCORING_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(row)
    return quote_path


class TestMarketMakingDailyRoll(unittest.TestCase):
    def test_target_date_rolls_to_new_local_day_at_midnight(self):
        self.assertEqual(
            target_date_for_roll(
                now="2026-06-16T00:00:05-04:00",
                timezone_name="America/Toronto",
            ),
            "2026-06-16",
        )

    def test_build_command_uses_default_paper_forward_settings(self):
        command = build_market_making_command(
            "2026-06-16",
            budget_usdc=500,
            mode="paper-live-forward",
            markets="all",
            interval_seconds=60,
            python_executable="python.exe",
        )

        self.assertEqual(
            command,
            [
                "python.exe",
                "-m",
                "weather.market.market_making_run",
                "--date",
                "2026-06-16",
                "--budget-usdc",
                "500",
                "--mode",
                "paper-live-forward",
                "--markets",
                "all",
                "--interval-seconds",
                "60",
            ],
        )

    def test_build_command_adds_market_harvest_companion_only_when_opted_in(self):
        default = build_market_making_command(
            "2026-06-16",
            python_executable="python.exe",
        )
        opted_in = build_market_making_command(
            "2026-06-16",
            python_executable="python.exe",
            market_harvest_companion=True,
        )

        self.assertNotIn("--enable-market-harvest-companion", default)
        self.assertEqual(opted_in.count("--enable-market-harvest-companion"), 1)

    def test_start_for_date_records_child_pid_and_avoids_duplicate_same_day_run(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append({
                "command": command,
                "repo_root": str(repo_root),
                "console_log_path": str(console_log_path),
            })
            return 4321

        def pid_alive(pid, target_date=None):
            return int(pid or 0) == 4321 and target_date == "2026-06-16"

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            log_path = tmp / "daily_roll_console.log"

            first = start_for_date(
                "2026-06-16",
                status_path=status_path,
                console_log_path=log_path,
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T04:01:00+00:00",
                launcher=launcher,
                pid_alive=pid_alive,
            )
            second = start_for_date(
                "2026-06-16",
                status_path=status_path,
                console_log_path=log_path,
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T04:02:00+00:00",
                launcher=launcher,
                pid_alive=pid_alive,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(first["status"], "started")
        self.assertEqual(second["status"], "already_running")
        self.assertEqual(saved["pid"], 4321)
        self.assertEqual(saved["action"], "noop")
        self.assertEqual(first["evidence_mode"], "operator_drill")
        self.assertFalse(first["counts_toward_live_forward_gate"])

    def test_direct_start_and_supervisor_ensure_serialize_launch_decision(self):
        launch_entered = threading.Event()
        release_launch = threading.Event()
        ensure_entered = threading.Event()
        calls = []
        results = {}
        errors = []

        def launcher(command, repo_root, console_log_path):
            calls.append(list(command))
            launch_entered.set()
            if not release_launch.wait(5):
                raise RuntimeError("test timed out waiting to release the launcher")
            return 4321

        def pid_alive(pid, target_date=None):
            return int(pid or 0) == 4321 and target_date == "2026-06-16"

        def record(name, callback):
            try:
                results[name] = callback()
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            common = {
                "status_path": status_path,
                "console_log_path": tmp / "daily_roll_console.log",
                "runs_root": tmp / "mm_runs",
                "repo_root": tmp,
                "python_executable": "python.exe",
                "now": "2026-06-16T23:00:00+00:00",
                "pid_alive": pid_alive,
                "launcher": launcher,
            }
            direct = threading.Thread(
                target=record,
                args=("direct", lambda: start_for_date("2026-06-16", **common)),
            )

            def ensure_callback():
                ensure_entered.set()
                return ensure_for_date(
                    "2026-06-16",
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    start_after_local_time="00:00",
                    **common,
                )

            supervisor = threading.Thread(
                target=record,
                args=("supervisor", ensure_callback),
            )
            direct.start()
            self.assertTrue(launch_entered.wait(2))
            supervisor.start()
            self.assertTrue(ensure_entered.wait(2))
            time.sleep(0.2)
            self.assertTrue(supervisor.is_alive())
            release_launch.set()
            direct.join(15)
            supervisor.join(15)
            lock_path = status_path.with_name(f"{status_path.name}.launch.lock")

        self.assertFalse(direct.is_alive())
        self.assertFalse(supervisor.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(results["direct"]["status"], "started")
        self.assertEqual(results["supervisor"]["action"], "noop")
        self.assertFalse(lock_path.exists())

    def test_after_window_roll_is_post_settlement_and_non_countable(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 4321

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            payload = start_for_date(
                "2026-06-16",
                status_path=tmp / "daily_roll_status.json",
                console_log_path=tmp / "daily_roll_console.log",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-17T00:31:18+00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )

        self.assertEqual(payload["evidence_mode"], "post_settlement_evaluation")
        self.assertFalse(payload["counts_toward_live_forward_gate"])
        self.assertIn("after active-day evidence window", payload["evidence_classification"]["reason"])
        self.assertIn("--evidence-mode", calls[0])
        self.assertIn("post_settlement_evaluation", calls[0])

    def test_active_window_roll_counts_as_live_forward_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            payload = start_for_date(
                "2026-06-16",
                status_path=tmp / "daily_roll_status.json",
                console_log_path=tmp / "daily_roll_console.log",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T23:30:00+00:00",
                launcher=lambda command, repo_root, console_log_path: 4321,
                pid_alive=lambda pid, target_date=None: False,
            )

        self.assertEqual(payload["evidence_mode"], "active_day_live_forward")
        self.assertTrue(payload["counts_toward_live_forward_gate"])

    def test_force_allows_manual_restart_for_same_date(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 5000 + len(calls)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            kwargs = {
                "status_path": status_path,
                "console_log_path": tmp / "daily_roll_console.log",
                "repo_root": tmp,
                "python_executable": "python.exe",
                "launcher": launcher,
                "pid_alive": lambda pid, target_date=None: True,
            }
            first = start_for_date("2026-06-16", **kwargs)
            second = start_for_date("2026-06-16", force=True, **kwargs)

        self.assertEqual(len(calls), 2)
        self.assertEqual(first["pid"], 5001)
        self.assertEqual(second["pid"], 5002)
        self.assertTrue(second["forced"])

    def test_low_disk_blocks_before_launching_child(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            payload = start_for_date(
                "2026-06-16",
                status_path=tmp / "daily_roll_status.json",
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "mm_runs",
                repo_root=tmp,
                python_executable="python.exe",
                min_free_bytes=100,
                disk_usage_fn=lambda _path: SimpleNamespace(total=1000, used=950, free=50),
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: False,
            )

        self.assertEqual(payload["status"], "disk_full")
        self.assertEqual(payload["root_cause_class"], "blocked_by_disk")
        self.assertEqual(payload["disk_capacity_preflight"]["insufficient_bytes"], 50)
        self.assertEqual(calls, [])

    def test_dead_existing_pid_records_terminal_status_without_restart(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 4321

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            first = start_for_date(
                "2026-06-16",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T04:01:00+00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )
            second = start_for_date(
                "2026-06-16",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T04:02:00+00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )
            status = load_status(
                status_path,
                now="2026-06-16T04:03:00+00:00",
                pid_alive=lambda pid, target_date=None: False,
            )

        self.assertEqual(first["status"], "started")
        self.assertEqual(second["status"], "pid_missing")
        self.assertEqual(status["status"], "pid_missing")
        self.assertEqual(len(calls), 1)

    def test_alive_existing_pid_with_stale_activity_records_idle_process(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")

            payload = start_for_date(
                "2026-06-16",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "mm_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-16T23:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["root_cause_class"], "stale_pid_no_recent_useful_artifacts")
        self.assertEqual(payload["artifact_liveness"]["status"], "NO_RUN_FOLDER")
        self.assertEqual(saved["status"], "idle_process")
        self.assertEqual(calls, [])

    def test_saved_activity_idle_restores_when_latest_artifacts_are_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            saved.update({
                "status": "idle_process",
                "action": "blocked_restart_required",
                "terminal": True,
                "first_failing_gate": "activity_liveness",
                "root_cause_class": "idle_process_no_recent_tape_or_log_activity",
                "completed_at_utc": "2026-06-16T23:15:00+00:00",
                "remediation_command": "inspect the console log and run tape freshness, then restart the daily roll with --force",
                "activity_liveness": {
                    "status": "STALE_ACTIVITY",
                    "ok": False,
                    "latest_activity_age_seconds": 900.0,
                },
            })
            status_path.write_text(json.dumps(saved), encoding="utf-8")
            _write_run_artifacts(
                tmp / "mm_runs" / "2026-06-16" / "mm-fresh",
                timestamp=_ts("2026-06-16T23:19:30+00:00"),
                summary={"row_count": 1, "quote_permission_rows": 0},
            )

            payload = load_status(
                status_path,
                now="2026-06-16T23:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertEqual(payload["status"], "already_running")
        self.assertEqual(payload["action"], "noop")
        self.assertTrue(payload["pid_alive"])
        self.assertEqual(payload["artifact_liveness"]["status"], "PASS")
        self.assertNotIn("first_failing_gate", payload)
        self.assertNotIn("remediation_command", payload)

    def test_live_forward_gate_block_overrides_current_countable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            saved.update({
                "mode": "paper-live-forward",
                "evidence_mode": "active_day_live_forward",
                "counts_toward_live_forward_gate": True,
                "evidence_classification": {
                    "counts_toward_live_forward_gate": True,
                    "evidence_mode": "active_day_live_forward",
                },
            })
            status_path.write_text(json.dumps(saved), encoding="utf-8")
            _write_run_artifacts(
                tmp / "mm_runs" / "2026-06-16" / "mm-blocked",
                timestamp=_ts("2026-06-16T23:19:30+00:00"),
                summary={
                    "mode": "paper-live-forward",
                    "evidence_mode": "active_day_live_forward",
                    "row_count": 132,
                    "quote_permission_rows": 0,
                    "useful_work_liveness": {
                        "status": "BLOCK",
                        "reason": "all-market active-day useful-write SLA blocked",
                    },
                },
                live_forward_gate={
                    "status": "BLOCK",
                    "counts_toward_live_forward_gate": False,
                    "summary": {"run_level_ok": False},
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-16T23:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["artifact_liveness"]["status"], "PASS")
        self.assertEqual(payload["live_forward_gate_status"], "BLOCK")
        self.assertFalse(payload["counts_toward_live_forward_gate"])
        self.assertFalse(payload["current_counts_toward_live_forward_gate"])
        self.assertTrue(payload["evidence_classification"]["counts_toward_live_forward_gate"])
        self.assertEqual(
            payload["operator_report"]["useful_work_liveness_status"],
            "BLOCK",
        )
        self.assertFalse(
            payload["operator_report"]["current_counts_toward_live_forward_gate"],
        )

    def test_operator_report_exposes_supervisor_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            saved["daily_roll_supervisor"] = {
                "state": "STALE_CODE",
                "action": "backoff",
                "intended_action": "restart",
                "restart_cause": "superseded_code",
                "reason": "restart_backoff_active=300.0s",
                "target_date": "2026-06-16",
                "expected_target_date": "2026-06-17",
                "runtime_identity_matches_current": False,
                "start_time_gate": {
                    "allowed": False,
                    "reason": "before_daily_start_time",
                    "start_after_local_time": "19:30",
                    "timezone": "America/Toronto",
                },
                "recovery_guard": {
                    "remediation": "wait for the supervisor backoff window",
                    "retry_after_seconds": 300.0,
                    "retry_at_utc": "2026-06-16T23:25:00+00:00",
                },
            }
            status_path.write_text(json.dumps(saved), encoding="utf-8")
            _write_run_artifacts(
                tmp / "mm_runs" / "2026-06-16" / "mm-current",
                timestamp=_ts("2026-06-16T23:19:30+00:00"),
                summary={
                    "mode": "paper-live-forward",
                    "evidence_mode": "active_day_live_forward",
                    "row_count": 132,
                    "quote_permission_rows": 0,
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-16T23:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        report = payload["operator_report"]
        self.assertEqual(report["supervisor_state"], "STALE_CODE")
        self.assertEqual(report["supervisor_action"], "backoff")
        self.assertEqual(report["supervisor_intended_action"], "restart")
        self.assertEqual(report["supervisor_restart_cause"], "superseded_code")
        self.assertFalse(report["supervisor_runtime_identity_matches_current"])
        self.assertEqual(report["supervisor_remediation"], "wait for the supervisor backoff window")
        self.assertEqual(report["supervisor_retry_after_seconds"], 300.0)
        self.assertEqual(report["supervisor_retry_at_utc"], "2026-06-16T23:25:00+00:00")
        self.assertEqual(payload["supervisor_state"], "STALE_CODE")
        self.assertEqual(payload["supervisor_action"], "backoff")
        self.assertEqual(payload["supervisor_intended_action"], "restart")
        self.assertEqual(payload["supervisor_restart_cause"], "superseded_code")
        self.assertEqual(payload["expected_target_date"], "2026-06-17")
        self.assertEqual(payload["supervisor_target_date"], "2026-06-16")
        self.assertFalse(payload["start_time_gate_allowed"])
        self.assertEqual(payload["start_reason"], "before_daily_start_time")
        self.assertEqual(payload["start_after_local_time"], "19:30")
        self.assertEqual(payload["start_time_gate_timezone"], "America/Toronto")

    def test_daily_roll_health_ignores_newer_shadow_probe_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            runs_root = tmp / "mm_runs"
            daily_folder = runs_root / "2026-06-16" / "daily-paper"
            shadow_folder = runs_root / "2026-06-16" / "shadow-probe"
            _write_run_artifacts(
                daily_folder,
                timestamp=_ts("2026-06-16T23:00:00+00:00"),
                summary={
                    "mode": "paper-live-forward",
                    "evidence_mode": "active_day_live_forward",
                    "row_count": 1,
                    "quote_permission_rows": 0,
                },
            )
            _write_run_artifacts(
                shadow_folder,
                timestamp=_ts("2026-06-16T23:19:30+00:00"),
                summary={
                    "mode": "shadow",
                    "evidence_mode": "operator_drill",
                    "row_count": 1,
                    "quote_permission_rows": 0,
                },
            )

            paths = market_making_activity_paths(
                runs_root,
                "2026-06-16",
                expected_mode="paper-live-forward",
                expected_evidence_mode="active_day_live_forward",
            )
            health = market_making_artifact_health(
                runs_root,
                "2026-06-16",
                now="2026-06-16T23:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                expected_mode="paper-live-forward",
                expected_evidence_mode="active_day_live_forward",
            )

        self.assertTrue(paths)
        self.assertTrue(all("daily-paper" in str(path) for path in paths))
        self.assertEqual(health["latest_run_folder"], str(daily_folder))
        self.assertEqual(health["operator_report"]["latest_run_folder"], str(daily_folder))
        self.assertEqual(health["status"], "STALE_HEARTBEAT_METADATA")

    def test_ensure_restarts_stale_market_making_run_summary(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 7001

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            diagnostics_path = tmp / "daily_roll_diagnostics.jsonl"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")
            run_folder = tmp / "mm_runs" / "2026-06-16" / "mm-stale"
            _write_run_artifacts(
                run_folder,
                timestamp=_ts("2026-06-16T23:00:00+00:00"),
                summary={"row_count": 1, "quote_permission_rows": 0},
            )

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                return_value={"pid": 4321, "stopped": True},
            ):
                payload = ensure_for_date(
                    "2026-06-16",
                    status_path=status_path,
                    diagnostics_path=diagnostics_path,
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=tmp / "mm_runs",
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-16T23:20:00+00:00",
                    start_after_local_time="19:00",
                    max_activity_age_seconds=120,
                    startup_grace_seconds=60,
                    launcher=launcher,
                    pid_alive=lambda pid, target_date=None: True,
                )
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            diagnostics = [json.loads(line) for line in diagnostics_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(payload["action"], "restart")
        self.assertEqual(payload["restart_cause"], "stale_heartbeat_metadata")
        self.assertEqual(payload["stop"]["stopped"], True)
        self.assertEqual(saved["status"], "started")
        self.assertEqual(saved["forced_run_retirement"]["status"], "QUARANTINED")
        self.assertFalse(run_folder.exists())
        self.assertEqual(len(calls), 1)
        self.assertEqual(diagnostics[-1]["restart_cause"], "stale_heartbeat_metadata")

    def test_ensure_persists_start_time_gate_during_scheduled_wait(self):
        def launcher(command, repo_root, console_log_path):
            raise AssertionError("scheduled wait must not launch a new roll")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            diagnostics_path = tmp / "daily_roll_diagnostics.jsonl"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")

            payload = ensure_for_date(
                "2026-06-17",
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "mm_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-17T06:18:00+00:00",
                start_after_local_time="19:30",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: True,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["action"], "scheduled_wait")
        supervisor = saved["daily_roll_supervisor"]
        self.assertEqual(supervisor["state"], "SCHEDULED_WAIT")
        self.assertEqual(supervisor["target_date"], "2026-06-16")
        self.assertEqual(supervisor["expected_target_date"], "2026-06-17")
        self.assertFalse(supervisor["start_time_gate"]["allowed"])
        self.assertEqual(supervisor["start_time_gate"]["start_after_local_time"], "19:30")
        self.assertEqual(supervisor["start_time_gate"]["reason"], "before_daily_start_time")

    def test_ensure_does_not_launch_after_evidence_window(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00")

            payload = ensure_for_date(
                "2026-06-16",
                status_path=status_path,
                diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "mm_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-17T03:01:00+00:00",
                start_after_local_time="07:05",
                start_no_later_than_local_time="20:00",
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: False,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(calls, [])
        self.assertEqual(payload["action"], "scheduled_wait")
        self.assertEqual(payload["intended_action"], "start")
        self.assertEqual(payload["state"], "SCHEDULED_WAIT")
        self.assertEqual(payload["reason"], "after_daily_end_time")
        self.assertNotIn("recovery_guard", payload)
        self.assertEqual(
            saved["daily_roll_supervisor"]["start_time_gate"][
                "start_no_later_than_local_time"
            ],
            "20:00",
        )

    def test_ensure_rejects_inverted_launch_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaisesRegex(
                ValueError,
                "start_after_local_time must be earlier",
            ):
                ensure_for_date(
                    "2026-06-16",
                    status_path=tmp / "daily_roll_status.json",
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=tmp / "mm_runs",
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-16T16:00:00+00:00",
                    start_after_local_time="20:00",
                    start_no_later_than_local_time="07:05",
                    launcher=lambda command, repo_root, console_log_path: 9100,
                    pid_alive=lambda pid, target_date=None: False,
                )

    def test_day_roll_finalizes_superseded_scoring_projection_and_persists_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            runs_root = tmp / "mm_runs"
            run_folder = runs_root / "2026-06-16" / "mm-settled"
            _write_status(status_path, tmp)
            canonical_path = _write_scoring_source_tape(run_folder)
            canonical_before = canonical_path.read_bytes()

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                return_value={"pid": 4321, "stopped": True},
            ), patch(
                "weather.operations.market_making_daily_roll.wait_for_superseded_process_exit",
                return_value={
                    "exited": True,
                    "reason": "superseded_process_not_alive",
                },
            ):
                payload = ensure_for_date(
                    "2026-06-17",
                    status_path=status_path,
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=runs_root,
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-17T04:20:00+00:00",
                    start_after_local_time="00:00",
                    launcher=lambda command, repo_root, console_log_path: 9100,
                    pid_alive=lambda pid, target_date=None: True,
                )

            saved = json.loads(status_path.read_text(encoding="utf-8"))
            receipt = payload["superseded_run_scoring_projection_finalization"]
            canonical_after = canonical_path.read_bytes()
            projection_exists = (run_folder / BASE_PROJECTION_FILENAME).exists()
            variant_projection_exists = (
                run_folder / MODEL_VARIANT_PROJECTION_FILENAME
            ).exists()
            manifest_exists = (run_folder / MANIFEST_FILENAME).exists()

        self.assertEqual(payload["action"], "start")
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["target_date"], "2026-06-16")
        self.assertEqual(receipt["run_count"], 1)
        self.assertEqual(receipt["written_run_count"], 1)
        self.assertEqual(receipt["error_run_count"], 0)
        self.assertEqual(
            saved["superseded_run_scoring_projection_finalization"],
            receipt,
        )
        self.assertEqual(canonical_after, canonical_before)
        self.assertTrue(projection_exists)
        self.assertTrue(variant_projection_exists)
        self.assertTrue(manifest_exists)

    def test_day_roll_waits_for_superseded_pid_exit_before_finalizing_projection(self):
        events = []
        state = {"termination_requested": False, "exit_polls": 0}

        def terminate(pid, **kwargs):
            state["termination_requested"] = True
            events.append("terminate")
            return {"pid": int(pid), "stopped": True}

        def pid_alive(pid, target_date=None):
            if not state["termination_requested"]:
                return True
            state["exit_polls"] += 1
            events.append(f"poll_{state['exit_polls']}")
            return state["exit_polls"] < 3

        def finalize(runs_root, target_date):
            events.append("finalize")
            self.assertEqual(state["exit_polls"], 3)
            return {
                "status": "PASS",
                "target_date": target_date,
                "run_count": 0,
                "written_run_count": 0,
                "skipped_run_count": 0,
                "error_run_count": 0,
                "runs": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                side_effect=terminate,
            ), patch(
                "weather.operations.market_making_daily_roll.time.sleep",
                side_effect=lambda seconds: events.append("sleep"),
            ), patch(
                "weather.operations.market_making_daily_roll.finalize_scoring_projections_for_date",
                side_effect=finalize,
            ):
                payload = ensure_for_date(
                    "2026-06-17",
                    status_path=status_path,
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=tmp / "mm_runs",
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-17T04:20:00+00:00",
                    start_after_local_time="00:00",
                    launcher=lambda command, repo_root, console_log_path: 9100,
                    pid_alive=pid_alive,
                )

            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(
            events,
            ["terminate", "poll_1", "sleep", "poll_2", "sleep", "poll_3", "finalize"],
        )
        self.assertEqual(payload["superseded_process_exit_wait"]["attempts"], 3)
        self.assertTrue(payload["superseded_process_exit_wait"]["exited"])
        self.assertEqual(
            saved["superseded_process_exit_wait"],
            payload["superseded_process_exit_wait"],
        )

    def test_day_roll_does_not_finalize_when_superseded_worker_fails_to_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            runs_root = tmp / "mm_runs"
            run_folder = runs_root / "2026-06-16" / "mm-still-live"
            _write_status(status_path, tmp)
            canonical_path = _write_scoring_source_tape(run_folder)
            canonical_before = canonical_path.read_bytes()

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                return_value={
                    "pid": 4321,
                    "stopped": False,
                    "reason": "termination timeout",
                },
            ), patch(
                "weather.operations.market_making_daily_roll.finalize_scoring_projections_for_date",
            ) as finalize:
                payload = ensure_for_date(
                    "2026-06-17",
                    status_path=status_path,
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=runs_root,
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-17T04:20:00+00:00",
                    start_after_local_time="00:00",
                    launcher=lambda command, repo_root, console_log_path: 9100,
                    pid_alive=lambda pid, target_date=None: True,
                )

            saved = json.loads(status_path.read_text(encoding="utf-8"))
            receipt = payload["superseded_run_scoring_projection_finalization"]
            canonical_after = canonical_path.read_bytes()
            projection_exists = (run_folder / BASE_PROJECTION_FILENAME).exists()
            manifest_exists = (run_folder / MANIFEST_FILENAME).exists()

        finalize.assert_not_called()
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(receipt["target_date"], "2026-06-16")
        self.assertIn("did not stop cleanly", receipt["error"])
        self.assertEqual(
            saved["superseded_run_scoring_projection_finalization"],
            receipt,
        )
        self.assertEqual(canonical_after, canonical_before)
        self.assertFalse(projection_exists)
        self.assertFalse(manifest_exists)

    def test_stop_status_file_stops_matching_paper_roll(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-16T23:00:00+00:00", pid=4321)

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                return_value={"pid": 4321, "stopped": True},
            ) as terminate:
                payload = stop_status_file(
                    status_path,
                    target_date="2026-06-16",
                    now="2026-06-16T23:30:00+00:00",
                    pid_alive=lambda pid, target_date=None: int(pid or 0) == 4321 and target_date == "2026-06-16",
                )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(payload["pid_alive"])
        self.assertEqual(payload["stop_target_date"], "2026-06-16")
        self.assertEqual(payload["stop_result"]["pid"], 4321)
        self.assertTrue(payload["stop_result"]["stopped"])
        self.assertEqual(saved["status"], "stopped")
        terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
