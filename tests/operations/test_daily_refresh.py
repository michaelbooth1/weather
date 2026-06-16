import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from weather.operations.daily_refresh import (  # noqa: E402
    load_status,
    run_daily_refresh,
    run_ingest_quality_gate_step,
    run_model_variant_evidence_growth_step,
    run_reanalysis_recent_refresh_step,
)


def _args(tmp, **overrides):
    root = Path(tmp)
    values = {
        "snapshots_root": str(root / "snapshots"),
        "backtest_root": str(root / "backtest"),
        "roadmap": str(root / "ROADMAP.md"),
        "status_out": str(root / "backtest" / "daily_refresh_status.json"),
        "report_out": str(root / "backtest" / "daily_refresh_report.md"),
        "long_job_state": str(root / "backtest" / "long_job_guard_status.json"),
        "long_job_lock": str(root / "backtest" / "long_job_guard.lock"),
        "long_job_priority": "normal",
        "disable_long_job_guard": False,
        "force_long_job_lock": False,
        "dry_run": False,
        "continue_on_error": False,
        "fail_on_fleet_critical": False,
        "fail_on_ingest_quality": False,
        "fail_on_data_layer_audit": False,
        "fail_on_snapshot_evaluation": False,
        "fail_on_shadow_ab_alert": False,
        "skip_shadow_ab_monitor": False,
        "ab_current_tol": 0.003,
        "ab_market_tol": 0.003,
        "skip_model_variant_evidence_growth": False,
        "variant_evidence_current": "",
        "variant_evidence_baseline": "",
        "variant_evidence_min_unique_observations": 1,
        "variant_evidence_min_market_days": 1,
        "skip_ingest_quality_gate": False,
        "ingest_quality_years": "",
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
        self.assertTrue(saved["config"]["long_job_guard"]["enabled"])
        self.assertFalse(saved["config"]["long_job_guard"]["nested"])
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
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 11)

    def test_fail_on_ingest_quality_marks_run_critical(self):
        def ingest(_args):
            return {"status": "FAIL", "summary": {"markets_with_schema_errors": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_ingest_quality=True),
                runners=[("ingest_quality_gate", ingest)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["ingest_quality_gate"]["status"], "FAIL")

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

    def test_fail_on_snapshot_evaluation_marks_run_critical(self):
        def evaluation(_args):
            return {"status": "FAIL", "gate_counts": {"status": "FAIL"}}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_snapshot_evaluation=True),
                runners=[("snapshot_evaluation", evaluation)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["snapshot_evaluation"]["status"], "FAIL")

    def test_fail_on_shadow_ab_alert_marks_run_critical(self):
        def monitor(_args):
            return {"status": "ALERT", "summary": {"alert_count": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_shadow_ab_alert=True),
                runners=[("shadow_ab_monitor", monitor)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["shadow_ab_monitor"]["status"], "ALERT")

    def test_model_variant_evidence_growth_step_runs_from_daily_refresh_inputs(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row1 = "v1,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-15\n"
        row2 = "v2,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.7,0.5,0.5,0.5,1,a,p,2026-06-15\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current.csv"
            baseline = root / "baseline.csv"
            current.write_text(header + row1 + row2, encoding="utf-8")
            baseline.write_text(header + row1, encoding="utf-8")
            args = _args(
                tmp,
                variant_evidence_current=str(current),
                variant_evidence_baseline=str(baseline),
            )

            result = run_model_variant_evidence_growth_step(args)

        self.assertEqual(result["status"], "ALERT")
        self.assertEqual(result["summary"]["unique_observation_count"], 1)
        self.assertEqual(result["delta_vs_baseline"]["unique_observation_count"], 0)

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
        with patch("weather.operations.daily_refresh.all_specs", return_value=[FakeSpec()]), \
                patch("weather.operations.daily_refresh.ReanalysisClient", FakeClient), \
                patch("weather.operations.daily_refresh.ReanalysisStore", FakeStore):
            result = run_reanalysis_recent_refresh_step(args)

        self.assertEqual(result["start"], "2026-06-01")
        self.assertEqual(result["end"], "2026-06-02")
        self.assertEqual(result["fetched_ranges"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(len(stores[0].writes), 1)

    def test_ingest_quality_gate_writes_artifacts_and_warns_on_gaps(self):
        fake_results = {
            "nyc": {
                "missing_days": [date(2026, 6, 1)],
                "sparse_days": [],
                "duplicate_timestamps": [],
                "impossible_values": [],
                "schema_errors": [],
            }
        }

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh.data_auditor.audit_fleet_historical_data", return_value=fake_results):
            result = run_ingest_quality_gate_step(_args(tmp, ingest_quality_years="2026"))

            self.assertEqual(result["status"], "WARN")
            self.assertTrue(Path(result["json_out"]).exists())
            self.assertTrue(Path(result["report_out"]).exists())
            self.assertEqual(result["summary"]["markets_with_missing_days"], 1)


if __name__ == "__main__":
    unittest.main()
