import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("src"))

from daily_refresh import load_status, run_daily_refresh  # noqa: E402


def _args(tmp, **overrides):
    root = Path(tmp)
    values = {
        "snapshots_root": str(root / "snapshots"),
        "backtest_root": str(root / "backtest"),
        "roadmap": str(root / "ROADMAP.md"),
        "status_out": str(root / "backtest" / "daily_refresh_status.json"),
        "report_out": str(root / "backtest" / "daily_refresh_report.md"),
        "dry_run": False,
        "continue_on_error": False,
        "fail_on_fleet_critical": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestDailyRefresh(unittest.TestCase):
    def test_run_daily_refresh_executes_steps_in_order_and_writes_status(self):
        calls = []

        def runner(name):
            def _run(_args):
                calls.append(name)
                return {"name": name}
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload, status_path, report_path = run_daily_refresh(
                args,
                runners=[
                    ("market_day_labels_finalize", runner("market_day_labels_finalize")),
                    ("promotion_refresh", runner("promotion_refresh")),
                    ("progress_audit", runner("progress_audit")),
                    ("disagreement_casebook", runner("disagreement_casebook")),
                    ("fleet_observability", runner("fleet_observability")),
                ],
            )

            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            report_exists = Path(report_path).exists()

        self.assertEqual(calls, [
            "market_day_labels_finalize",
            "promotion_refresh",
            "progress_audit",
            "disagreement_casebook",
            "fleet_observability",
        ])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(saved["status"], "ok")
        self.assertTrue(report_exists)

    def test_run_daily_refresh_stops_on_error_by_default(self):
        calls = []

        def ok(_args):
            calls.append("ok")
            return {}

        def bad(_args):
            calls.append("bad")
            raise RuntimeError("boom")

        def after(_args):
            calls.append("after")
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp),
                runners=[("one", ok), ("two", bad), ("three", after)],
            )

        self.assertEqual(calls, ["ok", "bad"])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["steps"][-1]["name"], "two")
        self.assertIn("boom", payload["steps"][-1]["error"])

    def test_run_daily_refresh_continue_on_error_runs_later_steps(self):
        calls = []

        def bad(_args):
            calls.append("bad")
            raise RuntimeError("boom")

        def after(_args):
            calls.append("after")
            return {"done": True}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, continue_on_error=True),
                runners=[("two", bad), ("three", after)],
            )

        self.assertEqual(calls, ["bad", "after"])
        self.assertEqual(payload["status"], "error")
        self.assertEqual([step["status"] for step in payload["steps"]], ["error", "ok"])

    def test_dry_run_records_planned_steps_without_calling_runners(self):
        def should_not_run(_args):
            raise AssertionError("dry run should not execute runners")

        with tempfile.TemporaryDirectory() as tmp:
            payload, status_path, _report_path = run_daily_refresh(
                _args(tmp, dry_run=True),
                runners=[("one", should_not_run)],
            )
            status = load_status(status_path)

        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(status["status"], "dry_run")
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 5)


if __name__ == "__main__":
    unittest.main()
