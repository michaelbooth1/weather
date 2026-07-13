import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.taker_bot_daily_roll import (
    DEFAULT_STRATEGIES,
    build_taker_bot_command,
    ensure_for_date,
    load_status,
    pid_matches_taker_bot,
    retire_taker_bot_process_tree,
    start_for_date,
    target_date_for_roll,
)


def _write_status(path, tmp, *, started_at="2026-06-18T04:00:00+00:00", pid=7654):
    path.write_text(json.dumps({
        "schema_version": "taker_bot_daily_roll_v0.1",
        "runner": "taker_bot_daily_roll",
        "generated_at_utc": started_at,
        "started_at_utc": started_at,
        "target_date": "2026-06-18",
        "status": "started",
        "pid": pid,
        "runs_root": str(tmp / "taker_runs"),
        "console_log_path": str(tmp / "daily_roll_console.log"),
        "command": ["python.exe", "-m", "weather.market.taker_bot"],
    }), encoding="utf-8")


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def _write_run_artifacts(run_folder, *, timestamp, summary=None, include_orders=True, include_run_summary=True, include_strategy_summary=True):
    run_folder.mkdir(parents=True, exist_ok=True)
    if include_orders:
        orders = run_folder / "orders_long.csv"
        orders.write_text("order_status,action\nSKIPPED,NO_TRADE\n", encoding="utf-8")
        os.utime(orders, (timestamp, timestamp))
    budget = run_folder / "budget_ledger.jsonl"
    budget.write_text("{}\n", encoding="utf-8")
    os.utime(budget, (timestamp, timestamp))
    pnl = run_folder / "daily_pnl.json"
    pnl.write_text("{}\n", encoding="utf-8")
    os.utime(pnl, (timestamp, timestamp))
    if include_run_summary:
        run_summary = run_folder / "run_summary.json"
        run_summary.write_text(json.dumps({"summary": summary or {}}), encoding="utf-8")
        os.utime(run_summary, (timestamp, timestamp))
    if include_strategy_summary:
        strategy = run_folder / "strategy_summary.json"
        strategy.write_text("{}\n", encoding="utf-8")
        os.utime(strategy, (timestamp, timestamp))


class TestTakerBotDailyRoll(unittest.TestCase):
    def test_target_date_rolls_to_new_local_day_at_midnight(self):
        self.assertEqual(
            target_date_for_roll(
                now="2026-06-18T00:00:05-04:00",
                timezone_name="America/Toronto",
            ),
            "2026-06-18",
        )

    def test_build_command_starts_loop_for_target_date(self):
        command = build_taker_bot_command(
            "2026-06-18",
            budget_usdc=100,
            markets="all",
            interval_seconds=60,
            python_executable="python.exe",
        )

        self.assertEqual(
            command,
            [
                "python.exe",
                "-m",
                "weather.market.taker_bot",
                "--date",
                "2026-06-18",
                "--budget-usdc",
                "100",
                "--markets",
                "all",
                "--interval-seconds",
                "60",
                "--loop",
                "--strategies",
                DEFAULT_STRATEGIES,
            ],
        )

    def test_once_command_omits_loop_for_debug_runs(self):
        command = build_taker_bot_command(
            "2026-06-18",
            python_executable="python.exe",
            once=True,
            config_overrides=["min_edge=0.05"],
        )

        self.assertNotIn("--loop", command)
        self.assertEqual(command[-2:], ["--config", "min_edge=0.05"])

    def test_build_command_can_launch_strategy_experiment(self):
        command = build_taker_bot_command(
            "2026-06-18",
            python_executable="python.exe",
            strategies="raw_edge_control,small_order_probe",
            experiment_id="exp-1",
            config_overrides=["min_edge=0.05"],
        )

        self.assertIn("--strategies", command)
        self.assertIn("raw_edge_control,small_order_probe", command)
        self.assertIn("--experiment-id", command)
        self.assertIn("exp-1", command)
        self.assertEqual(command[-2:], ["--config", "min_edge=0.05"])

    def test_start_for_date_records_current_high_trust_delayed_start_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                config_overrides=["current_high_trust_gate_start_hour_local=15"],
                launcher=lambda command, repo_root, console_log_path: 7654,
                pid_alive=lambda pid, target_date=None: False,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["config_warning_count"], 1)
        self.assertEqual(
            payload["config_warnings"][0]["code"],
            "CURRENT_HIGH_TRUST_GATE_DELAYED_START",
        )
        self.assertEqual(saved["config_warnings"], payload["config_warnings"])

    def test_start_for_date_records_child_pid_and_avoids_duplicate_same_day_run(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append({
                "command": command,
                "repo_root": str(repo_root),
                "console_log_path": str(console_log_path),
            })
            return 7654

        def pid_alive(pid, target_date=None):
            return int(pid or 0) == 7654 and target_date == "2026-06-18"

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            log_path = tmp / "daily_roll_console.log"

            first = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=log_path,
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:01:00+00:00",
                launcher=launcher,
                pid_alive=pid_alive,
            )
            second = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=log_path,
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:02:00+00:00",
                launcher=launcher,
                pid_alive=pid_alive,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(first["status"], "started")
        self.assertEqual(second["status"], "already_running")
        self.assertEqual(saved["pid"], 7654)
        self.assertEqual(saved["action"], "noop")
        self.assertEqual(first["schema_version"], "taker_bot_daily_roll_v0.1")

    def test_scheduled_start_retires_previous_date_tree_before_launch(self):
        launches = []
        retirements = []

        def retire_process_tree(pid, target_date):
            retirements.append((pid, target_date))
            return {"pid": pid, "target_date": target_date, "stopped": True}

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)

            payload = start_for_date(
                "2026-06-19",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                launcher=lambda command, repo_root, console_log_path: launches.append(command) or 9100,
                pid_alive=lambda pid, target_date=None: pid == 7654 and target_date == "2026-06-18",
                retire_process_tree=retire_process_tree,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(retirements, [(7654, "2026-06-18")])
        self.assertEqual(len(launches), 1)
        self.assertEqual(payload["status"], "started")
        self.assertTrue(payload["superseded_process_retirement"]["stopped"])
        self.assertEqual(saved["target_date"], "2026-06-19")
        self.assertEqual(saved["pid"], 9100)

    def test_scheduled_start_fails_closed_when_previous_date_tree_cannot_retire(self):
        launches = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)

            payload = start_for_date(
                "2026-06-19",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                launcher=lambda command, repo_root, console_log_path: launches.append(command) or 9100,
                pid_alive=lambda pid, target_date=None: pid == 7654 and target_date == "2026-06-18",
                retire_process_tree=lambda pid, target_date: {
                    "pid": pid,
                    "target_date": target_date,
                    "stopped": False,
                    "reason": "simulated taskkill failure",
                },
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(launches, [])
        self.assertEqual(payload["status"], "blocked_superseded_process")
        self.assertEqual(payload["action"], "blocked_start")
        self.assertFalse(payload["status_persisted"])
        self.assertEqual(saved["target_date"], "2026-06-18")
        self.assertEqual(saved["pid"], 7654)

    def test_pid_match_requires_exact_taker_module_and_target_date(self):
        with patch(
            "weather.operations.taker_bot_daily_roll.pid_is_python",
            return_value=True,
        ), patch(
            "weather.operations.taker_bot_daily_roll.process_command_line",
            return_value=(
                "pythonw.exe -m weather.market.taker_bot --date 2026-06-18 "
                "--budget-usdc 100 --loop"
            ),
        ):
            self.assertTrue(pid_matches_taker_bot(7654, "2026-06-18"))
            self.assertFalse(pid_matches_taker_bot(7654, "2026-06-19"))

        with patch(
            "weather.operations.taker_bot_daily_roll.pid_is_python",
            return_value=True,
        ), patch(
            "weather.operations.taker_bot_daily_roll.process_command_line",
            return_value="pythonw.exe -m weather.market.market_making --date 2026-06-18",
        ):
            self.assertFalse(pid_matches_taker_bot(7654, "2026-06-18"))

    def test_windows_retirement_uses_verified_tree_termination(self):
        calls = []

        def run_fn(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="SUCCESS", stderr="")

        with patch(
            "weather.operations.taker_bot_daily_roll.pid_matches_taker_bot",
            return_value=True,
        ), patch(
            "weather.operations.taker_bot_daily_roll.os.name",
            "nt",
        ), patch(
            "weather.operations.taker_bot_daily_roll._creationflags",
            return_value=0,
        ):
            result = retire_taker_bot_process_tree(
                7654,
                "2026-06-18",
                run_fn=run_fn,
            )

        self.assertTrue(result["stopped"])
        self.assertEqual(calls[0][0], ["taskkill.exe", "/PID", "7654", "/T", "/F"])
        self.assertEqual(calls[0][1]["timeout"], 15)

    def test_force_allows_manual_restart_for_same_date(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 8000 + len(calls)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            kwargs = {
                "status_path": status_path,
                "console_log_path": tmp / "daily_roll_console.log",
                "runs_root": tmp / "taker_runs",
                "repo_root": tmp,
                "python_executable": "python.exe",
                "launcher": launcher,
                "pid_alive": lambda pid, target_date=None: True,
            }
            first = start_for_date("2026-06-18", **kwargs)
            second = start_for_date("2026-06-18", force=True, **kwargs)

        self.assertEqual(len(calls), 2)
        self.assertEqual(first["pid"], 8001)
        self.assertEqual(second["pid"], 8002)
        self.assertTrue(second["forced"])

    def test_low_disk_blocks_before_launching_child(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            payload = start_for_date(
                "2026-06-18",
                status_path=tmp / "daily_roll_status.json",
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
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
            return 7654

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            first = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:01:00+00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )
            second = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:02:00+00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )
            status = load_status(
                status_path,
                now="2026-06-18T04:03:00+00:00",
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
            _write_status(status_path, tmp)

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["root_cause_class"], "stale_pid_no_recent_useful_artifacts")
        self.assertEqual(payload["activity_liveness"]["status"], "NO_ACTIVITY")
        self.assertEqual(payload["artifact_liveness"]["status"], "NO_RUN_FOLDER")
        self.assertEqual(saved["status"], "idle_process")
        self.assertEqual(calls, [])

    def test_fresh_empty_latest_run_inside_startup_grace_suppresses_stale_old_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp, started_at="2026-06-18T04:19:00+00:00")
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-old",
                timestamp=_ts("2026-06-18T04:00:00+00:00"),
                summary={"latest_tick_rows": 12, "latest_tick_filled_orders": 0},
            )
            old_run = tmp / "taker_runs" / "2026-06-18" / "taker-old"
            os.utime(
                old_run,
                (_ts("2026-06-18T04:00:00+00:00"), _ts("2026-06-18T04:00:00+00:00")),
            )
            empty_run = tmp / "taker_runs" / "2026-06-18" / "taker-new-empty"
            empty_run.mkdir(parents=True, exist_ok=True)
            os.utime(
                empty_run,
                (_ts("2026-06-18T04:19:30+00:00"), _ts("2026-06-18T04:19:30+00:00")),
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=120,
            )

        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["activity_liveness"]["status"], "STALE_ACTIVITY")
        self.assertEqual(payload["artifact_liveness"]["status"], "STARTUP_GRACE")
        self.assertFalse(payload["terminal"])

    def test_fresh_console_log_does_not_satisfy_taker_artifact_liveness(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            log_path = tmp / "daily_roll_console.log"
            _write_status(status_path, tmp)
            log_path.write_text("still printing\n", encoding="utf-8")
            os.utime(log_path, (_ts("2026-06-18T04:19:30+00:00"), _ts("2026-06-18T04:19:30+00:00")))

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=log_path,
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["root_cause_class"], "stale_pid_no_recent_useful_artifacts")
        self.assertEqual(payload["activity_liveness"]["existing_path_count"], 0)
        self.assertEqual(calls, [])

    def test_missing_orders_tape_marks_artifact_restart_required(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-empty",
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                include_orders=False,
                summary={"latest_tick_rows": 0, "latest_tick_filled_orders": 0},
            )

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["first_failing_gate"], "artifact_liveness")
        self.assertEqual(payload["root_cause_class"], "missing_orders_tape")
        self.assertEqual(payload["artifact_liveness"]["status"], "MISSING_ORDERS_TAPE")
        self.assertIn("orders_long.csv", payload["artifact_liveness"]["missing_required_artifacts"])
        self.assertEqual(calls, [])

    def test_stale_strategy_summary_marks_artifact_restart_required(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            run_folder = tmp / "taker_runs" / "2026-06-18" / "taker-stale-strategy"
            _write_run_artifacts(
                run_folder,
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={"latest_tick_rows": 12, "latest_tick_filled_orders": 0, "reason_counts": {"NO_TRADE_EDGE_TOO_SMALL": 12}},
            )
            os.utime(
                run_folder / "strategy_summary.json",
                (_ts("2026-06-18T04:00:00+00:00"), _ts("2026-06-18T04:00:00+00:00")),
            )

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["root_cause_class"], "stale_strategy_summary")
        self.assertEqual(payload["artifact_liveness"]["status"], "STALE_STRATEGY_SUMMARY")
        self.assertEqual(payload["operator_report"]["restart_recommended"], True)
        self.assertEqual(calls, [])

    def test_stale_book_summary_gets_specific_root_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-stale-book",
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={
                    "latest_tick_rows": 20,
                    "latest_tick_filled_orders": 0,
                    "cumulative_order_rows": 100,
                    "cumulative_filled_orders": 0,
                    "reason_counts": {"NO_TRADE_STALE_BOOK": 16, "NO_TRADE_EDGE_TOO_SMALL": 4},
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        # The stale-book no-fill is classified specifically as infra_starved_clob
        # (not a generic root cause). On a live + active taker that is now a
        # non-terminal advisory rather than idle_process/blocked_restart_required:
        # restarting the taker cannot refresh upstream CLOB books.
        self.assertIn(payload["status"], {"started", "already_running"})
        self.assertFalse(payload["terminal"])
        self.assertNotEqual(payload.get("action"), "blocked_restart_required")
        self.assertEqual(payload["artifact_liveness"]["status"], "INFRA_STARVED_CLOB")
        self.assertEqual(payload["artifact_health_status"], "INFRA_STARVED_CLOB")
        self.assertEqual(payload["latest_tick_scoring_liveness"]["classification"], "infra_starved_clob")
        self.assertEqual(payload["operator_report"]["latest_candidate_rows"], 100)
        self.assertFalse(payload["operator_report"]["restart_recommended"])

    def test_latest_tick_scoring_starvation_blocks_alive_pid_with_fresh_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-starved",
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={
                    "latest_tick_rows": 0,
                    "latest_tick_filled_orders": 0,
                    "cumulative_order_rows": 19184,
                    "cumulative_filled_orders": 0,
                    "cumulative_counterfactual_rows": 147906,
                    "cumulative_counterfactual_would_buy_count": 0,
                    "root_cause_class": "crashed_before_scoring",
                    "first_failing_gate": "scoring",
                    "upstream_dependency_status": {
                        "status": "BLOCK",
                        "first_failing_dependency": "clob",
                        "first_failing_gate": "clob_loop",
                        "newest_snapshot_timestamp_utc": "2026-06-18T18:07:00+00:00",
                        "latest_source_status_utc": "2026-06-18T18:07:00+00:00",
                        "dependencies": {
                            "snapshot": {
                                "status": "BLOCK",
                                "loop_state": "DEAD",
                                "heartbeat_age_seconds": 3600,
                            },
                            "clob": {
                                "status": "BLOCK",
                                "loop_state": "DEAD",
                                "heartbeat_age_seconds": 9000,
                            },
                        },
                    },
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["first_failing_gate"], "latest_tick_scoring_liveness")
        self.assertEqual(payload["root_cause_class"], "scoring_crash")
        self.assertEqual(payload["artifact_liveness"]["status"], "SCORING_CRASH")
        self.assertEqual(payload["latest_tick_scoring_liveness"]["status"], "BLOCK")
        self.assertEqual(payload["latest_tick_scoring_liveness"]["countability_status"], "NON_COUNTABLE")
        self.assertEqual(payload["operator_report"]["latest_tick_rows"], 0)
        self.assertEqual(payload["operator_report"]["last_nonzero_scored_tick_rows"], 19184)
        self.assertEqual(
            payload["latest_tick_scoring_liveness"]["last_nonzero_scored_tick"]["basis"],
            "cumulative_order_rows_fallback",
        )
        self.assertEqual(payload["operator_report"]["first_failing_dependency"], "clob")
        self.assertEqual(
            payload["remediation_command"],
            "python -m weather.market.market_microstructure ensure",
        )

    def test_policy_no_edge_idle_is_classified_without_restart(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-no-edge",
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={
                    "root_cause_class": "policy_no_edge",
                    "latest_tick_rows": 20,
                    "latest_tick_filled_orders": 0,
                    "cumulative_order_rows": 100,
                    "cumulative_filled_orders": 0,
                    "reason_counts": {"NO_TRADE_EDGE_TOO_SMALL": 20},
                },
            )

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )

        self.assertEqual(payload["status"], "already_running")
        self.assertEqual(payload["root_cause_class"], "policy_no_edge")
        self.assertEqual(payload["artifact_liveness"]["status"], "POLICY_NO_EDGE")
        self.assertEqual(payload["operator_report"]["restart_recommended"], False)
        self.assertEqual(calls, [])

    def test_live_active_taker_with_empty_latest_tick_is_not_idle(self):
        # A taker whose process is alive and still writing fresh run artifacts
        # but whose latest scoring tick emitted zero rows (LATEST_TICK_EMPTY) is a
        # quiet/no-edge tick, not a dead process. It must report a non-terminal
        # running status -- not idle_process / blocked_restart_required -- while
        # keeping the empty-tick signal visible as a non-terminal advisory.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            # Persisted state already cached a terminal idle action from a prior
            # tick; restoring a live, active taker to running must CLEAR it, not
            # inherit the cached blocked_restart_required.
            status_path.write_text(json.dumps({
                "schema_version": "taker_bot_daily_roll_v0.1",
                "runner": "taker_bot_daily_roll",
                "generated_at_utc": "2026-06-18T04:00:00+00:00",
                "started_at_utc": "2026-06-18T04:00:00+00:00",
                "target_date": "2026-06-18",
                "status": "idle_process",
                "action": "blocked_restart_required",
                "terminal": True,
                "pid": 7654,
                "runs_root": str(tmp / "taker_runs"),
                "console_log_path": str(tmp / "daily_roll_console.log"),
                "command": ["python.exe", "-m", "weather.market.taker_bot"],
            }), encoding="utf-8")
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-empty-tick",
                timestamp=_ts("2026-06-18T04:19:50+00:00"),  # fresh -> activity PASS
                summary={
                    "latest_tick_rows": 0,
                    "latest_tick_filled_orders": 0,
                    "cumulative_order_rows": 100,
                    "cumulative_filled_orders": 0,
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertIn(payload["status"], {"started", "already_running"})
        self.assertFalse(payload["terminal"])
        self.assertIn(payload.get("action"), {"noop", "start"})  # cached terminal action cleared
        self.assertEqual(payload["activity_liveness"]["status"], "PASS")
        self.assertEqual(payload["artifact_liveness"]["status"], "LATEST_TICK_EMPTY")
        # empty-tick signal preserved as a non-terminal advisory, restart fields cleared
        self.assertEqual(payload["artifact_health_status"], "LATEST_TICK_EMPTY")
        self.assertNotIn("first_failing_gate", payload)
        self.assertNotIn("remediation_command", payload)

    def test_live_active_taker_with_clob_input_starvation_is_advisory_not_restart(self):
        # Live + active taker whose latest tick attributes no fills to stale CLOB
        # book input: restarting the taker cannot add CLOB data (that is an
        # upstream-collection problem, monitored separately), so it is a
        # non-terminal advisory, not blocked_restart_required.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-clob-starved",
                timestamp=_ts("2026-06-18T04:19:50+00:00"),
                summary={
                    "latest_tick_rows": 5,
                    "latest_tick_filled_orders": 0,
                    "root_cause_class": "stale_book_input",
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertIn(payload["status"], {"started", "already_running"})
        self.assertFalse(payload["terminal"])
        self.assertNotEqual(payload.get("action"), "blocked_restart_required")
        self.assertEqual(payload["artifact_liveness"]["status"], "INFRA_STARVED_CLOB")
        self.assertEqual(payload["artifact_health_status"], "INFRA_STARVED_CLOB")

    def test_scoring_crash_still_latches_restart_required_when_live(self):
        # A scoring crash is the one latest-tick failure where restarting a
        # (possibly wedged) live process can help, so it must STAY terminal /
        # blocked_restart_required even when the process is alive and active.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-crash",
                timestamp=_ts("2026-06-18T04:19:50+00:00"),
                summary={
                    "latest_tick_rows": 0,
                    "root_cause_class": "crashed_before_scoring",
                    "first_failing_gate": "scoring",
                },
            )

            payload = load_status(
                status_path,
                now="2026-06-18T04:20:00+00:00",
                pid_alive=lambda pid, target_date=None: True,
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
            )

        self.assertEqual(payload["status"], "idle_process")
        self.assertEqual(payload["action"], "blocked_restart_required")
        self.assertTrue(payload["terminal"])
        self.assertEqual(payload["artifact_liveness"]["status"], "SCORING_CRASH")
        self.assertNotIn("artifact_health_status", payload)

    def test_force_restart_quarantines_unhealthy_latest_run_folder(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 9001

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            _write_status(status_path, tmp)
            stale_run = tmp / "taker_runs" / "2026-06-18" / "taker-stale"
            _write_run_artifacts(
                stale_run,
                timestamp=_ts("2026-06-18T04:00:00+00:00"),
                summary={"latest_tick_rows": 12, "latest_tick_filled_orders": 0},
            )

            payload = start_for_date(
                "2026-06-18",
                status_path=status_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                force=True,
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: True,
            )

            quarantine_path = Path(payload["forced_run_retirement"]["quarantine_path"])
            quarantine_exists = quarantine_path.exists()

        self.assertEqual(payload["status"], "started")
        self.assertEqual(payload["forced_run_retirement"]["status"], "QUARANTINED")
        self.assertFalse(stale_run.exists())
        self.assertTrue(quarantine_exists)
        self.assertEqual(len(calls), 1)

    def test_ensure_restarts_dead_existing_pid_with_force(self):
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 9001

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            diagnostics_path = tmp / "daily_roll_diagnostics.jsonl"
            _write_status(status_path, tmp)

            payload = ensure_for_date(
                "2026-06-18",
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                start_after_local_time="00:00",
                launcher=launcher,
                pid_alive=lambda pid, target_date=None: False,
            )
            saved = json.loads(status_path.read_text(encoding="utf-8"))
            diagnostics = [json.loads(line) for line in diagnostics_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(payload["action"], "start")
        self.assertEqual(payload["restart_cause"], "pid_missing")
        self.assertEqual(len(calls), 1)
        self.assertEqual(saved["status"], "started")
        self.assertEqual(saved["daily_roll_supervisor"]["action"], "start")
        self.assertEqual(diagnostics[-1]["restart_cause"], "pid_missing")

    def test_day_roll_start_stops_superseded_previous_day_worker(self):
        # Regression (2026-06-30, 2026-07-04): the 00:05 day roll started the
        # new date's worker but left yesterday's worker running, leaking
        # ~3GB/2h alongside it every night. A TARGET_MISMATCH start must stop
        # the live superseded worker (matched on ITS OWN target date) first.
        calls = []

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 9100

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            # Yesterday's worker: alive, healthy, but for 2026-06-18 while the
            # roll now targets 2026-06-19.
            _write_status(status_path, tmp)

            terminated = []

            def fake_terminate(pid, pid_check=None):
                terminated.append(pid)
                return {"pid": pid, "stopped": True}

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                side_effect=fake_terminate,
            ):
                payload = ensure_for_date(
                    "2026-06-19",
                    status_path=status_path,
                    diagnostics_path=tmp / "daily_roll_diagnostics.jsonl",
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=tmp / "taker_runs",
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-19T04:20:00+00:00",
                    start_after_local_time="00:00",
                    max_activity_age_seconds=120,
                    startup_grace_seconds=60,
                    launcher=launcher,
                    pid_alive=lambda pid, target_date=None: True,
                )

        self.assertEqual(payload["action"], "start")
        self.assertEqual(payload["state"], "TARGET_MISMATCH")
        self.assertEqual(payload["stop_superseded"]["stopped"], True)
        self.assertEqual(terminated, [7654])
        self.assertEqual(len(calls), 1)

    def test_ensure_restarts_superseded_code_and_quarantines_latest_run(self):
        calls = []
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "new",
            "source_fingerprint": "current",
        }
        stale_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "old",
            "source_fingerprint": "stale",
        }

        def launcher(command, repo_root, console_log_path):
            calls.append(command)
            return 9002

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            diagnostics_path = tmp / "daily_roll_diagnostics.jsonl"
            _write_status(status_path, tmp)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["runtime_identity"] = stale_identity
            status_path.write_text(json.dumps(status), encoding="utf-8")
            run_folder = tmp / "taker_runs" / "2026-06-18" / "taker-fresh-stale-code"
            _write_run_artifacts(
                run_folder,
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={"latest_tick_rows": 12, "latest_tick_filled_orders": 0},
            )

            with patch(
                "weather.operations.bot_daily_roll_supervisor.terminate_python_pid",
                return_value={"pid": 7654, "stopped": True},
            ):
                payload = ensure_for_date(
                    "2026-06-18",
                    status_path=status_path,
                    diagnostics_path=diagnostics_path,
                    console_log_path=tmp / "daily_roll_console.log",
                    runs_root=tmp / "taker_runs",
                    repo_root=tmp,
                    python_executable="python.exe",
                    now="2026-06-18T04:20:00+00:00",
                    start_after_local_time="00:00",
                    max_activity_age_seconds=120,
                    startup_grace_seconds=60,
                    current_identity=current_identity,
                    launcher=launcher,
                    pid_alive=lambda pid, target_date=None: True,
                )

            saved = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["action"], "restart")
        self.assertEqual(payload["restart_cause"], "superseded_code")
        self.assertEqual(payload["stop"]["stopped"], True)
        self.assertEqual(saved["forced_run_retirement"]["status"], "QUARANTINED")
        self.assertTrue(saved["forced_run_retirement"]["forced"])
        self.assertFalse(run_folder.exists())
        self.assertEqual(len(calls), 1)
        self.assertEqual(saved["daily_roll_supervisor"]["restart_cause"], "superseded_code")

    def test_ensure_backoff_blocks_repeated_superseded_code_restart(self):
        calls = []
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "new",
            "source_fingerprint": "current",
        }
        stale_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "main",
            "git_commit": "old",
            "source_fingerprint": "stale",
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            status_path = tmp / "daily_roll_status.json"
            diagnostics_path = tmp / "daily_roll_diagnostics.jsonl"
            _write_status(status_path, tmp)
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["runtime_identity"] = stale_identity
            status_path.write_text(json.dumps(status), encoding="utf-8")
            _write_run_artifacts(
                tmp / "taker_runs" / "2026-06-18" / "taker-stale-code",
                timestamp=_ts("2026-06-18T04:19:30+00:00"),
                summary={"latest_tick_rows": 12, "latest_tick_filled_orders": 0},
            )
            diagnostics_path.write_text(
                json.dumps({
                    "time": (datetime(2026, 6, 18, 4, 20, tzinfo=timezone.utc) - timedelta(seconds=30)).isoformat(),
                    "supervisor": "ensure",
                    "action": "restart",
                    "state": "STALE_CODE",
                })
                + "\n",
                encoding="utf-8",
            )

            payload = ensure_for_date(
                "2026-06-18",
                status_path=status_path,
                diagnostics_path=diagnostics_path,
                console_log_path=tmp / "daily_roll_console.log",
                runs_root=tmp / "taker_runs",
                repo_root=tmp,
                python_executable="python.exe",
                now="2026-06-18T04:20:00+00:00",
                start_after_local_time="00:00",
                max_activity_age_seconds=120,
                startup_grace_seconds=60,
                current_identity=current_identity,
                launcher=lambda command, repo_root, console_log_path: calls.append(command),
                pid_alive=lambda pid, target_date=None: True,
            )

        self.assertEqual(payload["action"], "backoff")
        self.assertEqual(payload["intended_action"], "restart")
        self.assertEqual(payload["restart_cause"], "superseded_code")


if __name__ == "__main__":
    unittest.main()
