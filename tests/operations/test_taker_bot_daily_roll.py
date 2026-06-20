import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from weather.operations.taker_bot_daily_roll import (
    build_taker_bot_command,
    load_status,
    start_for_date,
    target_date_for_roll,
)


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


if __name__ == "__main__":
    unittest.main()
