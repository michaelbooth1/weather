import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from daily_refresh import load_status, run_daily_refresh, run_reanalysis_recent_refresh_step  # noqa: E402


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
        "fail_on_data_layer_audit": False,
        "skip_reanalysis_refresh": False,
        "reanalysis_lag_days": 10,
        "reanalysis_chunk_days": 5,
        "reanalysis_sleep": 0.0,
        "reanalysis_timeout": 30,
        "reanalysis_end_date": "",
        "skip_data_layer_audit": False,
        "data_layer_historical_start": "2000-01-01",
        "data_layer_historical_end": "",
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
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 7)

    def test_fail_on_data_layer_audit_marks_run_critical(self):
        def audit(_args):
            return {"gate_status": "FAIL", "gate_summary": {"status": "FAIL"}}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_data_layer_audit=True),
                runners=[("data_layer_audit", audit)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["data_layer_audit"]["gate_status"], "FAIL")

    def test_reanalysis_recent_refresh_fetches_missing_ranges_without_raising(self):
        stores = []

        class FakeSpec:
            id = "nyc"
            icao = "KLGA"

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            def fetch_range(self, spec, start, end):
                return {"market": spec.id, "start": start.isoformat(), "end": end.isoformat()}

        class FakeStore:
            def __init__(self, spec):
                self.spec = spec
                self.writes = []
                stores.append(self)

            def coverage(self, _start, _end):
                return {
                    "missing_days": 2 if not self.writes else 0,
                    "raw_only_day_count": 0,
                }

            def missing_ranges(self, _start, _end, _chunk_days):
                return [(date(2026, 6, 1), date(2026, 6, 2))]

            def write_payload(self, start, end, payload):
                self.writes.append((start, end, payload))

            def rebuild(self):
                return [], []

        args = _args(
            tempfile.gettempdir(),
            reanalysis_end_date="2026-06-02",
            reanalysis_lag_days=2,
            reanalysis_chunk_days=5,
        )
        with patch("daily_refresh.all_specs", return_value=[FakeSpec()]), \
                patch("daily_refresh.ReanalysisClient", FakeClient), \
                patch("daily_refresh.ReanalysisStore", FakeStore):
            result = run_reanalysis_recent_refresh_step(args)

        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-02")
        self.assertEqual(result["fetched_ranges"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(len(stores[0].writes), 1)


if __name__ == "__main__":
    unittest.main()
