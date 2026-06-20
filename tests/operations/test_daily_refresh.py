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
    DEFAULT_RUNNERS,
    load_status,
    run_active_variant_shadow_step,
    run_clob_order_book_tiering_step,
    run_daily_refresh,
    run_ingest_quality_gate_step,
    run_model_variant_evidence_growth_step,
    run_promotion_refresh_step,
    run_price_free_model_learning_step,
    run_reanalysis_recent_refresh_step,
)
from weather.reporting.active_variant_shadow_refresh import build_payload as build_active_variant_shadow_payload


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
        "resume_from_step": "",
        "fail_on_fleet_critical": False,
        "fail_on_ingest_quality": False,
        "fail_on_data_layer_audit": False,
        "fail_on_hourly_performance_gate": True,
        "fail_on_snapshot_evaluation": False,
        "fail_on_shadow_ab_alert": False,
        "fail_on_variant_evidence_alert": True,
        "fail_on_daily_learning_blocker": False,
        "skip_shadow_ab_monitor": False,
        "ab_current_tol": 0.003,
        "ab_market_tol": 0.003,
        "skip_active_variant_shadow": False,
        "active_variant_shadow_sources": "",
        "variant_registry": str(root / "config" / "model_variant_registry.json"),
        "skip_model_variant_evidence_growth": False,
        "variant_evidence_current": "",
        "variant_evidence_baseline": "",
        "variant_evidence_min_unique_observations": 1,
        "variant_evidence_min_market_days": 1,
        "variant_evidence_rolling_7d_min_market_days": 1,
        "variant_evidence_per_shadow_market_min_days": 4,
        "skip_ingest_quality_gate": False,
        "ingest_quality_years": "",
        "skip_reanalysis_refresh": False,
        "reanalysis_lag_days": 10,
        "reanalysis_chunk_days": 5,
        "reanalysis_sleep": 0.0,
        "reanalysis_timeout": 30,
        "reanalysis_end_date": "",
        "skip_data_layer_audit": False,
        "skip_daily_learning": False,
        "skip_hourly_model_performance": False,
        "skip_price_free_model_learning": False,
        "promotion_min_artifact_free_bytes": 1024 * 1024 * 1024,
        "quality_grades": "complete,manual_override",
        "markets": "",
        "hourly_min_rows": 30,
        "hourly_top_hours": 3,
        "hourly_min_regime_market_days": 10,
        "hourly_early_brier_regression_tolerance": 0.003,
        "hourly_early_logloss_regression_tolerance": 0.01,
        "hourly_early_ece_max": 0.12,
        "skip_replay_status_backfill": False,
        "skip_clob_order_book_tiering": False,
        "clob_tiering_settled_before": "",
        "clob_tiering_min_free_bytes": 1024 * 1024 * 1024,
        "clob_tiering_limit": None,
        "clob_tiering_delete_source": True,
        "overwrite_replay_status": False,
        "reconstruct_missing_replay_inputs": False,
        "include_active_replay_status": False,
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

    def test_run_daily_refresh_writes_progress_ledger_on_error(self):
        def bad(_args):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload, _status_path, report_path = run_daily_refresh(
                args,
                runners=[("promotion_refresh", bad)],
            )
            ledger = Path(args.backtest_root) / "daily_progress_ledger.jsonl"
            latest = Path(args.backtest_root) / "daily_progress_latest.json"
            lines = ledger.read_text(encoding="utf-8").strip().splitlines()
            latest_payload = json.loads(latest.read_text(encoding="utf-8"))
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["daily_progress_ledger"]["status"], "OK")
        self.assertEqual(len(lines), 1)
        self.assertFalse(latest_payload["broad_improvement_claim_allowed"])
        self.assertIn("Daily Progress Ledger", report)

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
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * len(DEFAULT_RUNNERS))

    def test_default_runner_order_repairs_replay_status_before_data_layer_audit(self):
        names = [name for name, _runner in DEFAULT_RUNNERS]

        self.assertLess(names.index("market_day_labels_finalize"), names.index("replay_status_backfill"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("clob_order_book_tiering"))
        self.assertLess(names.index("clob_order_book_tiering"), names.index("replay_status_backfill"))
        self.assertLess(names.index("replay_status_backfill"), names.index("data_layer_audit"))
        self.assertLess(names.index("replay_status_backfill"), names.index("hourly_model_performance"))
        self.assertLess(names.index("hourly_model_performance"), names.index("price_free_model_learning"))
        self.assertLess(names.index("price_free_model_learning"), names.index("promotion_refresh"))
        self.assertLess(names.index("active_variant_shadow"), names.index("model_variant_evidence_growth"))

    def test_promotion_refresh_disk_preflight_blocks_before_candidate_export(self):
        def after(_args):
            raise AssertionError("daily refresh should stop at disk preflight")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh.promotion_refresh.run_promotion_refresh") as run_refresh:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            (backtest / "pooled_candidate_replay_latest.json").write_text(
                json.dumps({"aggregate": {"n": 10}}),
                encoding="utf-8",
            )

            payload, _status_path, report_path = run_daily_refresh(
                _args(
                    tmp,
                    disable_long_job_guard=True,
                    promotion_min_artifact_free_bytes=1000,
                    disk_usage_fn=lambda _path: SimpleNamespace(total=2000, used=1900, free=100),
                ),
                runners=[
                    ("promotion_refresh", run_promotion_refresh_step),
                    ("daily_learning", after),
                ],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        run_refresh.assert_not_called()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(len(payload["steps"]), 1)
        step = payload["steps"][0]
        result = step["result"]
        disk = result["disk_preflight"]
        self.assertEqual(step["status"], "error")
        self.assertEqual(result["root_cause_class"], "blocked_by_disk")
        self.assertEqual(disk["status"], "BLOCK")
        self.assertEqual(disk["projected_export_bytes"], 10 * 1024)
        self.assertEqual(disk["required_free_bytes"], 1000 + 10 * 1024)
        self.assertGreater(disk["insufficient_bytes"], 0)
        self.assertTrue(result["no_partial_export"])
        self.assertFalse((Path(tmp) / "backtest" / "f_family_promotion_refresh.json").exists())
        self.assertIn("## Disk Preflight", report)
        self.assertIn("--resume-from-step promotion_refresh", report)

    def test_resume_from_step_skips_upstream_steps(self):
        calls = []

        def runner(name):
            def _run(_args):
                calls.append(name)
                return {"name": name}
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, disable_long_job_guard=True, resume_from_step="promotion_refresh"),
                runners=[
                    ("price_free_model_learning", runner("price_free_model_learning")),
                    ("promotion_refresh", runner("promotion_refresh")),
                    ("daily_learning", runner("daily_learning")),
                ],
            )

        self.assertEqual(calls, ["promotion_refresh", "daily_learning"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["config"]["resume_from_step"], "promotion_refresh")

    def test_price_free_model_learning_step_can_be_skipped(self):
        result = run_price_free_model_learning_step(
            _args(tempfile.gettempdir(), skip_price_free_model_learning=True)
        )

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "skip_price_free_model_learning")

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

    def test_clob_order_book_tiering_step_applies_settled_compression(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh.clob_order_book_tiering.run") as run, \
                patch("weather.operations.daily_refresh.clob_order_book_tiering.write_outputs") as write_outputs:
            root = Path(tmp)
            payload = {
                "status": "PASS",
                "settled_before": "2026-06-19",
                "summary": {"candidate_files": 2},
                "apply": {
                    "delete_source": True,
                    "summary": {
                        "compressed_files": 2,
                        "deleted_sources": 2,
                        "insufficient_headroom": 0,
                    },
                },
            }
            run.return_value = payload
            write_outputs.return_value = (
                root / "backtest" / "clob_order_book_tiering.json",
                root / "backtest" / "clob_order_book_tiering_report.md",
            )

            result = run_clob_order_book_tiering_step(
                _args(
                    tmp,
                    clob_tiering_settled_before="2026-06-19",
                    clob_tiering_min_free_bytes=123,
                    clob_tiering_limit=5,
                )
            )

        run.assert_called_once_with(
            snapshots_root=str(root / "snapshots"),
            settled_before="2026-06-19",
            min_free_bytes=123,
            apply=True,
            delete_source=True,
            limit=5,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["summary"]["candidate_files"], 2)
        self.assertEqual(result["apply_summary"]["compressed_files"], 2)
        self.assertTrue(result["delete_source"])

    def test_clob_order_book_tiering_step_can_be_skipped(self):
        result = run_clob_order_book_tiering_step(
            _args(tempfile.gettempdir(), skip_clob_order_book_tiering=True)
        )

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "skip_clob_order_book_tiering")

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

    def test_hourly_performance_gate_marks_run_critical_by_default(self):
        def hourly(_args):
            return {
                "status": "BLOCK",
                "hourly_performance_gate": {
                    "status": "BLOCK",
                    "blocker_count": 1,
                    "first_blocker": {
                        "gate": "early_hour_brier_regression",
                        "detail": "early hour regressed",
                        "remediation_command": "run hourly remediation",
                    },
                },
                "daily_summary": {"worst_hours": ["03:00"]},
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_daily_refresh(
                _args(tmp),
                runners=[("hourly_model_performance", hourly)],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["hourly_model_performance"]["status"], "BLOCK")
        self.assertIn("Hourly Performance Gate", report)
        self.assertIn("early hour regressed", report)

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

    def test_variant_evidence_alert_marks_run_critical_by_default(self):
        def active_shadow(_args):
            return {"status": "OK", "summary": {"canonical_rows": 10}}

        def evidence(_args):
            return {
                "status": "ALERT",
                "summary": {"alert_count": 1, "unique_observation_count": 1},
                "evidence_sla": {
                    "status": "BLOCK",
                    "reasons": ["scored rows grew without independent observations"],
                },
                "no_growth_reasons": [
                    {
                        "scope": "overall",
                        "status": "BLOCK",
                        "reason": "variant_rows_only",
                        "action": "Collect new settled labels.",
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_daily_refresh(
                _args(tmp),
                runners=[
                    ("active_variant_shadow", active_shadow),
                    ("model_variant_evidence_growth", evidence),
                ],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        gate = payload["summary"]["variant_learning_gate"]
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["first_blocker"]["gate"], "variant_evidence_sla")
        self.assertIn("Collect new settled labels.", gate["first_blocker"]["remediation_command"])
        self.assertIn("Variant Learning Gate", report)
        self.assertIn("Collect new settled labels.", report)

    def test_variant_evidence_alert_can_be_allowed_for_research_runs(self):
        def evidence(_args):
            return {
                "status": "ALERT",
                "evidence_sla": {"status": "BLOCK", "reasons": ["no independent growth"]},
                "no_growth_reasons": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_variant_evidence_alert=False),
                runners=[("model_variant_evidence_growth", evidence)],
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["summary"]["variant_learning_gate"]["status"], "BLOCK")

    def test_missing_active_variant_shadow_evidence_marks_run_critical(self):
        def active_shadow(_args):
            return {
                "status": "BLOCK",
                "blockers": ["active registry variants missing from canonical shadow output"],
                "missing_active_variant_ids": ["v1"],
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp),
                runners=[("active_variant_shadow", active_shadow)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(
            payload["summary"]["variant_learning_gate"]["first_blocker"]["gate"],
            "active_variant_shadow_coverage",
        )

    def test_fail_on_daily_learning_blocker_marks_run_critical(self):
        def learning(_args):
            return {"status": "BLOCKED", "blocker_count": 1}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_daily_learning_blocker=True),
                runners=[("daily_learning", learning)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["daily_learning"]["status"], "BLOCKED")

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
        self.assertFalse(result["evidence_sla"]["broad_promotion_claim_allowed"])
        self.assertEqual(result["no_growth_reasons"][0]["reason"], "variant_rows_only")

    def test_active_variant_shadow_step_writes_canonical_outputs_and_missing_ids(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = "active_v,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-18\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            source.write_text(header + row, encoding="utf-8")
            registry = root / "config" / "model_variant_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {"variant_id": "active_v", "lifecycle": "active", "track": "no_market", "active_for_headline": True},
                    {"variant_id": "missing_v", "lifecycle": "active", "track": "no_market", "active_for_headline": True},
                ],
            }), encoding="utf-8")
            args = _args(
                tmp,
                active_variant_shadow_sources=str(source),
                variant_registry=str(registry),
            )

            result = run_active_variant_shadow_step(args)
            long_exists = (root / "backtest" / "active_variant_shadow_long.csv").exists()
            sidecar_exists = (root / "backtest" / "active_variant_shadow_attribution.jsonl").exists()
            json_exists = (root / "backtest" / "active_variant_shadow.json").exists()
            report_exists = (root / "backtest" / "active_variant_shadow_report.md").exists()

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["summary"]["canonical_rows"], 1)
        self.assertEqual(result["missing_active_variant_ids"], ["missing_v"])
        self.assertTrue(long_exists)
        self.assertTrue(sidecar_exists)
        self.assertTrue(result["attribution_sidecar_out"].endswith("active_variant_shadow_attribution.jsonl"))
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)

    def test_active_variant_shadow_uses_registry_export_paths_by_default(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = "active_v,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-18\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            source.write_text(header + row, encoding="utf-8")
            registry = root / "model_variant_registry.json"
            registry.write_text(json.dumps({
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {
                        "variant_id": "active_v",
                        "variant_family": "f_family",
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "artifact_required": False,
                        "prediction_function": "weather.tests:predict",
                        "prediction_mode": "demo_mode",
                        "export_family": "f_family",
                        "default_export_path": str(source),
                        "live_runtime": "demo_runtime",
                    },
                ],
            }), encoding="utf-8")

            payload = build_active_variant_shadow_payload([], registry_path=registry)

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["registry"]["contract_status"], "OK")
        self.assertEqual(payload["summary"]["source_path_count"], 1)
        self.assertEqual(payload["registry"]["reported_active_variant_ids"], ["active_v"])

    def test_model_variant_evidence_growth_defaults_to_active_variant_shadow_long(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = "active_v,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-18\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir()
            (backtest / "active_variant_shadow_long.csv").write_text(header + row, encoding="utf-8")
            args = _args(tmp)

            result = run_model_variant_evidence_growth_step(args)
            payload = json.loads((backtest / "model_variant_evidence_growth.json").read_text(encoding="utf-8"))

        self.assertEqual(result["summary"]["unique_observation_count"], 1)
        self.assertEqual(payload["input_paths"], [str(backtest / "active_variant_shadow_long.csv")])

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
