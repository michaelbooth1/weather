import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_making_daily_roll import (  # noqa: E402
    build_market_making_command,
    start_for_date,
    target_date_for_roll,
)


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
                "src.market_making_run",
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


if __name__ == "__main__":
    unittest.main()
