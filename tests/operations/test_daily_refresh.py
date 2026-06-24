import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from weather.market.taker_bot import ORDER_COLUMNS
from weather.operations.daily_refresh import (  # noqa: E402
    DEFAULT_RUNNERS,
    acquire_lock,
    build_parser,
    load_status,
    repair_stale_locks,
    release_lock,
    run_active_variant_shadow_step,
    run_clob_order_book_tiering_step,
    run_data_retention_inventory_step,
    run_daily_flow_analysis_step,
    run_daily_refresh,
    run_distribution_stage_attribution_step,
    run_frozen_baseline_replay_trend_step,
    run_ingest_quality_gate_step,
    run_maker_paper_score_step,
    run_market_beating_objective_scoreboard_step,
    run_model_variant_evidence_growth_step,
    run_promotion_refresh_step,
    run_price_free_model_learning_step,
    run_proper_scoring_reliability_scorecard_step,
    run_reanalysis_recent_refresh_step,
    run_settled_day_root_cause_step,
    run_settlement_source_audit_step,
    run_taker_finalization_watchdog_step,
    run_taker_tail_casebook_step,
    run_trading_evidence_step,
    run_winner_rank_parity_step,
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
        "lock_path": str(root / "backtest" / "daily_refresh.lock"),
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
        "fail_on_ten_minute_performance_gate": True,
        "fail_on_snapshot_evaluation": False,
        "fail_on_shadow_ab_alert": False,
        "fail_on_variant_evidence_alert": True,
        "fail_on_daily_learning_blocker": False,
        "fail_on_daily_flow_analysis_blocker": False,
        "skip_shadow_ab_monitor": False,
        "ab_current_tol": 0.003,
        "ab_market_tol": 0.003,
        "skip_active_variant_shadow": False,
        "active_variant_shadow_sources": "",
        "skip_proper_scoring_reliability_scorecard": False,
        "variant_registry": str(root / "config" / "model_variant_registry.json"),
        "skip_frozen_baseline_replay_trend": False,
        "frozen_baseline_current_predictions": "",
        "frozen_baseline_baseline_predictions": "",
        "frozen_baseline_manifest": str(root / "backtest" / "frozen_baseline_manifest.json"),
        "frozen_baseline_current_variant_id": "item50_pooled_forecast_v3_candidate",
        "frozen_baseline_baseline_variant_id": "",
        "frozen_baseline_code_identity": "",
        "frozen_baseline_trend_jsonl": str(root / "backtest" / "frozen_baseline_replay_trend.jsonl"),
        "frozen_baseline_json_out": str(root / "backtest" / "frozen_baseline_replay_trend.json"),
        "frozen_baseline_report_out": str(root / "backtest" / "frozen_baseline_replay_trend_report.md"),
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
        "skip_data_retention_inventory": False,
        "distribution_stage_min_rows": 20,
        "data_retention_min_free_bytes": 0,
        "data_retention_lookback_hours": 24.0,
        "data_retention_top_n": 25,
        "skip_daily_learning": False,
        "skip_market_beating_objective_scoreboard": False,
        "skip_daily_flow_analysis": False,
        "skip_hourly_model_performance": False,
        "skip_ten_minute_model_performance": False,
        "skip_price_free_model_learning": False,
        "skip_settled_day_root_cause": False,
        "settled_root_cause_date": "",
        "skip_winner_rank_parity": False,
        "winner_rank_parity_days": 7,
        "winner_rank_parity_min_snapshots": 1,
        "taker_root": str(root / "taker_runs"),
        "mm_root": str(root / "mm_runs"),
        "skip_taker_finalization_watchdog": False,
        "taker_finalization_date": "",
        "taker_finalization_sla_hours": 4.0,
        "taker_finalization_min_free_bytes": 0,
        "taker_finalization_no_finalize": False,
        "skip_taker_bakeoff": False,
        "taker_bakeoff_strategies": "raw_edge_control,small_order_probe",
        "taker_champion_strategy_id": "raw_edge_control",
        "taker_champion_min_complete_label_days": 3,
        "taker_champion_min_settled_orders": 5,
        "skip_taker_tail_casebook": False,
        "taker_tail_casebook_date": "",
        "taker_tail_casebook_max_runs": 0,
        "skip_maker_paper_score": False,
        "skip_settlement_source_audit": False,
        "skip_trading_evidence": False,
        "promotion_min_artifact_free_bytes": 1024 * 1024 * 1024,
        "quality_grades": "complete,manual_override",
        "markets": "",
        "hourly_min_rows": 30,
        "hourly_top_hours": 3,
        "hourly_min_regime_market_days": 10,
        "hourly_early_brier_regression_tolerance": 0.003,
        "hourly_early_logloss_regression_tolerance": 0.01,
        "hourly_early_ece_max": 0.12,
        "ten_minute_min_rows": 30,
        "ten_minute_top_slots": 20,
        "ten_minute_min_weak_market_days": 10,
        "ten_minute_weak_brier_regression_tolerance": 0.003,
        "ten_minute_weak_logloss_regression_tolerance": 0.01,
        "ten_minute_candidate_rows": str(root / "backtest" / "item147_time_split_alpha_variant_rows.csv"),
        "ten_minute_candidate_min_weak_market_days": 10,
        "ten_minute_candidate_weak_brier_improvement_min": 0.0,
        "ten_minute_candidate_weak_market_regression_tolerance": 0.003,
        "ten_minute_candidate_weak_logloss_regression_tolerance": 0.01,
        "skip_replay_status_backfill": False,
        "skip_closed_day_parquet_incremental": False,
        "closed_day_parquet_plan_only": False,
        "closed_day_parquet_max_scan_folders": 25,
        "closed_day_parquet_archive_root": "",
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


def _write_order_tape(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ORDER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            full = {column: "" for column in ORDER_COLUMNS}
            full.update(row)
            writer.writerow(full)


def _write_active_mm_run(root, target_date="2026-06-19", run_id="mm-active"):
    run = Path(root) / "mm_runs" / target_date / run_id
    run.mkdir(parents=True)
    run_config = {
        "schema_version": "mm_run_v0.2",
        "run_id": run_id,
        "mode": "paper-live-forward",
        "target_date": target_date,
        "policy_hash": f"policy-{run_id}",
    }
    (run / "run_config.json").write_text(json.dumps(run_config), encoding="utf-8")
    summary = {
        **run_config,
        "evidence_mode": "active_day_live_forward",
        "counts_toward_live_forward_gate": True,
        "preflight_status": "PASS",
        "generated_at_utc": f"{target_date}T20:00:00+00:00",
    }
    (run / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    quote_row = {
        "run_id": run_id,
        "target_date": target_date,
        "run_mode": "paper-live-forward",
        "generated_at_utc": f"{target_date}T16:00:00+00:00",
        "captured_at_utc": f"{target_date}T15:59:30+00:00",
        "policy_hash": f"policy-{run_id}",
        "quote_permission": "True",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": f"token-{run_id}",
        "fair_probability": "0.50",
        "market_mid": "0.50",
        "bid_price": "0.49",
        "bid_size": "5",
        "ask_price": "0.51",
        "ask_size": "5",
        "regime": "harvest",
        "source_fresh": "True",
        "book_imbalance_1pct": "0.10",
        "min_order_size": "1",
        "reason_code": "QUOTE_HARVEST_MID",
    }
    with (run / "quote_intents_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(quote_row.keys()))
        writer.writeheader()
        writer.writerow(quote_row)
    return run


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

    def test_acquire_lock_removes_dead_pid_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest" / "daily_refresh.lock"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"pid": -999, "created_at_utc": "2026-06-20T00:00:00+00:00"}), encoding="utf-8")

            acquired = acquire_lock(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            release_lock(acquired)

        self.assertEqual(acquired, path)
        self.assertEqual(payload["pid"], os.getpid())

    def test_acquire_lock_preserves_active_pid_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest" / "daily_refresh.lock"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"pid": os.getpid(), "created_at_utc": "2026-06-20T00:00:00+00:00"}), encoding="utf-8")

            acquired = acquire_lock(path)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertIsNone(acquired)
        self.assertEqual(payload["pid"], os.getpid())

    def test_repair_stale_locks_clears_only_verified_dead_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            daily_lock = Path(args.backtest_root) / "daily_refresh.lock"
            long_lock = Path(args.backtest_root) / "long_job_guard.lock"
            state = Path(args.long_job_state)
            daily_lock.parent.mkdir(parents=True)
            daily_lock.write_text(json.dumps({"pid": -999}), encoding="utf-8")
            long_lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            state.write_text(
                json.dumps({"status": "running", "active": True, "pid": -999}),
                encoding="utf-8",
            )
            args.lock_path = str(daily_lock)
            args.long_job_lock = str(long_lock)

            payload = repair_stale_locks(args)
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            daily_exists = daily_lock.exists()
            long_exists = long_lock.exists()

        self.assertEqual(payload["removed_lock_count"], 1)
        self.assertFalse(daily_exists)
        self.assertTrue(long_exists)
        self.assertTrue(payload["long_job_lock"]["owner_running"])
        self.assertFalse(state_payload["active"])
        self.assertEqual(state_payload["status"], "stale_cleared")

    def test_rollup_freshness_blocks_stale_daily_learning_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            (backtest / "daily_learning.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-20T01:00:00+00:00", "status": "ACTIONABLE"}),
                encoding="utf-8",
            )
            (backtest / "progress_audit.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-21T12:00:00+00:00", "status": "OK"}),
                encoding="utf-8",
            )

            payload, status_path, report_path = run_daily_refresh(
                args,
                runners=[("noop", lambda _args: {})],
            )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            report = Path(report_path).read_text(encoding="utf-8")

        freshness = payload["summary"]["rollup_freshness"]
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(saved["summary"]["rollup_freshness"]["status"], "BLOCK")
        self.assertEqual(freshness["blockers"][0]["rollup"], "daily_learning")
        self.assertIn("repair-stale-locks", freshness["repair_command"])
        self.assertIn("Daily Rollup Freshness", report)

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

    def test_cli_dry_run_defaults_to_dry_run_status_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parser = build_parser()
            args = parser.parse_args([
                "run",
                "--dry-run",
                "--backtest-root",
                str(root / "backtest"),
                "--snapshots-root",
                str(root / "snapshots"),
            ])
            captured = {}

            def fake_run(run_args):
                captured["status_out"] = run_args.status_out
                captured["report_out"] = run_args.report_out
                return {"status": "dry_run"}, Path(run_args.status_out), Path(run_args.report_out)

            with patch("weather.operations.daily_refresh_cli.run_daily_refresh", side_effect=fake_run):
                code = args.func(args)

        self.assertEqual(code, 0)
        self.assertTrue(captured["status_out"].endswith("daily_refresh_dry_run_status.json"))
        self.assertTrue(captured["report_out"].endswith("daily_refresh_dry_run_report.md"))

    def test_default_runner_order_repairs_replay_status_before_data_layer_audit(self):
        names = [name for name, _runner in DEFAULT_RUNNERS]

        self.assertLess(names.index("market_day_labels_finalize"), names.index("replay_status_backfill"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("taker_finalization_watchdog"))
        self.assertLess(names.index("taker_finalization_watchdog"), names.index("taker_tail_casebook"))
        self.assertLess(names.index("taker_tail_casebook"), names.index("maker_paper_score"))
        self.assertLess(names.index("maker_paper_score"), names.index("settlement_source_audit"))
        self.assertLess(names.index("settlement_source_audit"), names.index("trading_evidence"))
        self.assertLess(names.index("trading_evidence"), names.index("daily_learning"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("clob_order_book_tiering"))
        self.assertLess(names.index("clob_order_book_tiering"), names.index("replay_status_backfill"))
        self.assertLess(names.index("replay_status_backfill"), names.index("closed_day_parquet_incremental"))
        self.assertLess(names.index("closed_day_parquet_incremental"), names.index("data_layer_audit"))
        self.assertLess(names.index("replay_status_backfill"), names.index("data_layer_audit"))
        self.assertLess(names.index("data_layer_audit"), names.index("snapshot_evaluation"))
        self.assertLess(names.index("snapshot_evaluation"), names.index("distribution_stage_attribution"))
        self.assertLess(names.index("distribution_stage_attribution"), names.index("settled_day_root_cause"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("winner_rank_parity"))
        self.assertLess(names.index("settled_day_root_cause"), names.index("winner_rank_parity"))
        self.assertLess(names.index("winner_rank_parity"), names.index("data_retention_inventory"))
        self.assertLess(names.index("data_retention_inventory"), names.index("daily_learning"))
        self.assertLess(names.index("trading_evidence"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("winner_rank_parity"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("daily_learning"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("market_beating_objective_scoreboard"), names.index("daily_flow_analysis"))
        self.assertLess(names.index("replay_status_backfill"), names.index("hourly_model_performance"))
        self.assertLess(names.index("hourly_model_performance"), names.index("ten_minute_model_performance"))
        self.assertLess(names.index("ten_minute_model_performance"), names.index("price_free_model_learning"))
        self.assertLess(names.index("price_free_model_learning"), names.index("promotion_refresh"))
        self.assertLess(names.index("active_variant_shadow"), names.index("proper_scoring_reliability_scorecard"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("frozen_baseline_replay_trend"))
        self.assertLess(names.index("frozen_baseline_replay_trend"), names.index("model_variant_evidence_growth"))

    def test_market_beating_objective_scoreboard_step_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            artifacts = {
                "weather_only_model_proof_packet.json": {
                    "schema_version": "weather_only_model_proof_packet_v0.1",
                    "status": "PASS",
                    "gates": [{"gate": "weather_only_lane_separation", "status": "PASS"}],
                },
                "proper_scoring_reliability_scorecard.json": {
                    "schema_version": "proper_scoring_reliability_scorecard_v0.1",
                    "status": "PASS",
                    "lanes": [
                        {"lane": "weather_only", "status": "PASS", "brier": 0.02, "row_count": 2},
                        {"lane": "market_only", "status": "PASS", "brier": 0.03, "row_count": 2},
                        {"lane": "market_informed_overlay", "status": "PASS", "brier": 0.01, "row_count": 2},
                    ],
                },
                "market_benchmark_residual_edge.json": {
                    "schema_version": "market_benchmark_residual_edge_v0.1",
                    "status": "BLOCK",
                    "proof_guard": {"counts_toward_weather_model_promotion": False},
                    "settlement_accuracy": {"weather_only_vs_market": {"residual_edge_row_count": 0}},
                    "frozen_market_benchmark_contract": {"status": "PASS"},
                    "trading_execution": {
                        "status": "PASS",
                        "summary": {"promotion_evidence_basis": "settlement_scored", "mtm_promotion_allowed": False},
                    },
                },
                "winner_rank_parity.json": {
                    "schema_version": "winner_rank_parity_v0.1",
                    "status": "PASS",
                    "parity_gate": {"status": "PASS"},
                    "summary": {"parity_gate_status": "PASS"},
                },
                "daily_progress_latest.json": {
                    "schema_version": "daily_progress_ledger_v0.1",
                    "evidence_independent_baseline_status": "PRESENT",
                },
                "trading_evidence.json": {
                    "schema_version": "trading_evidence_summary_v0.1",
                    "status": "OK",
                    "taker": {"pnl_evidence_status": "UNSCORED", "mtm_promotion_allowed": False},
                    "market_making": {"countability_status": "NON_COUNTABLE"},
                },
            }
            for filename, payload in artifacts.items():
                (backtest / filename).write_text(json.dumps(payload), encoding="utf-8")

            result = run_market_beating_objective_scoreboard_step(args)
            payload = json.loads((backtest / "market_beating_objective_scoreboard.json").read_text(encoding="utf-8"))
            report_exists = (backtest / "market_beating_objective_scoreboard.md").exists()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["headline_status"], "PASS")
        self.assertEqual(payload["headline"]["first_success_lane"], "weather_only_market_beating")
        self.assertTrue(report_exists)

    def test_winner_rank_parity_step_writes_gate_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, as_of="2026-06-23", winner_rank_parity_min_snapshots=1)
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            rows = [
                {
                    "variant_id": "item50_pooled_forecast_v3_candidate",
                    "variant_family": "pooled_f_candidate",
                    "uses_market_features": "False",
                    "claim_lane": "weather_only_core_model",
                    "counts_toward_weather_model_promotion": "True",
                    "market_id": "miami",
                    "target_date": "2026-06-22",
                    "snapshot_id": "s1",
                    "band_key": "winner",
                    "probability": "0.20",
                    "market_yes": "0.70",
                    "outcome": "1",
                    "bin_type": "eq",
                    "bin_value": "90",
                    "cutoff_hour": "7",
                    "cutoff_regime": "early",
                    "settlement_distance_bucket": "0",
                    "forecast_disagreement_bucket": "high_disagreement",
                    "forecast_source_count_bucket": "two_sources",
                    "source_freshness_state": "all_fresh",
                },
                {
                    "variant_id": "item50_pooled_forecast_v3_candidate",
                    "variant_family": "pooled_f_candidate",
                    "uses_market_features": "False",
                    "claim_lane": "weather_only_core_model",
                    "counts_toward_weather_model_promotion": "True",
                    "market_id": "miami",
                    "target_date": "2026-06-22",
                    "snapshot_id": "s1",
                    "band_key": "loser",
                    "probability": "0.60",
                    "market_yes": "0.20",
                    "outcome": "0",
                    "bin_type": "eq",
                    "bin_value": "91",
                    "cutoff_hour": "7",
                    "cutoff_regime": "early",
                    "settlement_distance_bucket": "1",
                    "forecast_disagreement_bucket": "high_disagreement",
                    "forecast_source_count_bucket": "two_sources",
                    "source_freshness_state": "all_fresh",
                },
                {
                    "variant_id": "item50_pooled_forecast_v3_candidate",
                    "variant_family": "pooled_f_candidate",
                    "uses_market_features": "False",
                    "claim_lane": "weather_only_core_model",
                    "counts_toward_weather_model_promotion": "True",
                    "market_id": "miami",
                    "target_date": "2026-06-22",
                    "snapshot_id": "s2",
                    "band_key": "winner",
                    "probability": "0.70",
                    "market_yes": "0.20",
                    "outcome": "1",
                    "bin_type": "eq",
                    "bin_value": "90",
                    "cutoff_hour": "12",
                    "cutoff_regime": "ramp",
                    "settlement_distance_bucket": "0",
                    "forecast_disagreement_bucket": "high_disagreement",
                    "forecast_source_count_bucket": "two_sources",
                    "source_freshness_state": "all_fresh",
                },
                {
                    "variant_id": "item50_pooled_forecast_v3_candidate",
                    "variant_family": "pooled_f_candidate",
                    "uses_market_features": "False",
                    "claim_lane": "weather_only_core_model",
                    "counts_toward_weather_model_promotion": "True",
                    "market_id": "miami",
                    "target_date": "2026-06-22",
                    "snapshot_id": "s2",
                    "band_key": "loser",
                    "probability": "0.20",
                    "market_yes": "0.60",
                    "outcome": "0",
                    "bin_type": "eq",
                    "bin_value": "91",
                    "cutoff_hour": "12",
                    "cutoff_regime": "ramp",
                    "settlement_distance_bucket": "1",
                    "forecast_disagreement_bucket": "high_disagreement",
                    "forecast_source_count_bucket": "two_sources",
                    "source_freshness_state": "all_fresh",
                },
            ]
            path = backtest / "active_variant_shadow_long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row}))
                writer.writeheader()
                writer.writerows(rows)

            result = run_winner_rank_parity_step(args)
            payload = json.loads((backtest / "winner_rank_parity.json").read_text(encoding="utf-8"))
            report_exists = (backtest / "winner_rank_parity.md").exists()

        self.assertIn(result["status"], {"PASS", "BLOCK"})
        self.assertEqual(result["snapshot_case_count"], 2)
        self.assertEqual(payload["schema_version"], "winner_rank_parity_v0.1")
        self.assertTrue(report_exists)

    def test_promotion_refresh_disk_preflight_blocks_before_candidate_export(self):
        def after(_args):
            raise AssertionError("daily refresh should stop at disk preflight")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_steps.promotion_refresh.run_promotion_refresh") as run_refresh:
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
                patch("weather.operations.daily_refresh_steps.clob_order_book_tiering.run") as run, \
                patch("weather.operations.daily_refresh_steps.clob_order_book_tiering.write_outputs") as write_outputs:
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

    def test_ten_minute_performance_gate_marks_run_critical_by_default(self):
        def ten_minute(_args):
            return {
                "status": "BLOCK",
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "blocker_count": 1,
                    "first_blocker": {
                        "gate": "weak_slot_brier_regression",
                        "detail": "03:00 weak-slot cluster trails market",
                        "remediation_command": "run weak-slot remediation",
                    },
                },
                "candidate_ten_minute_gate": {"status": "MISSING"},
                "daily_summary": {
                    "weak_slots": ["03:00", "03:10"],
                    "worst_slots": ["03:00"],
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_daily_refresh(
                _args(tmp),
                runners=[("ten_minute_model_performance", ten_minute)],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["ten_minute_model_performance"]["status"], "BLOCK")
        self.assertIn("10-Minute Performance Gate", report)
        self.assertIn("03:00 weak-slot cluster trails market", report)

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

    def test_daily_flow_analysis_step_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            (backtest / "daily_learning.json").write_text(
                json.dumps({
                    "schema_version": "daily_learning_v0.1",
                    "generated_at_utc": "2026-06-21T23:50:00+00:00",
                    "run_date": "2026-06-21",
                    "status": "BLOCKED",
                    "summary": {"learning_count": 1, "blocker_count": 1},
                    "retrain_plan": {"training_ready": False, "promotion_ready": False},
                    "scorecard": {"fleet": {}, "trading_evidence": {}},
                    "learnings": [
                        {
                            "priority": "P0",
                            "category": "operational_slo",
                            "source": "fleet_observability",
                            "signal": "live-forward SLO blocked",
                            "action": "python -m weather.reporting.fleet_observability",
                            "blocker": True,
                        }
                    ],
                }),
                encoding="utf-8",
            )
            args = _args(tmp)
            setattr(args, "_daily_refresh_steps_so_far", [
                {"name": "daily_learning", "status": "ok", "duration_seconds": 1.0},
            ])

            result = run_daily_flow_analysis_step(args)
            json_exists = (backtest / "daily_flow_analysis.json").exists()
            report_exists = (backtest / "daily_flow_analysis_report.md").exists()
            actions_exists = (backtest / "daily_flow_analysis_actions.csv").exists()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocker_count"], 1)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertTrue(actions_exists)

    def test_fail_on_daily_flow_analysis_blocker_marks_run_critical(self):
        def flow(_args):
            return {"status": "BLOCKED", "blocker_count": 1}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, fail_on_daily_flow_analysis_blocker=True),
                runners=[("daily_flow_analysis", flow)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["summary"]["daily_flow_analysis"]["status"], "BLOCKED")

    def test_frozen_baseline_replay_trend_step_scores_pinned_manifest(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        current_row = (
            "item50_pooled_forecast_v3_candidate,f_family,False,False,nyc,"
            "2026-06-11,s1,eq:82,0.8,0.5,0.5,0.5,1,a,p,2026-06-15\n"
        )
        baseline_row = (
            "pooled_f_candidate_control,f_family,False,True,nyc,"
            "2026-06-11,s1,eq:82,0.2,0.5,0.5,0.5,1,a,p,2026-06-15\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            current = backtest / "active_variant_shadow_long.csv"
            baseline = backtest / "baseline.csv"
            manifest = backtest / "frozen_baseline_manifest.json"
            current.write_text(header + current_row, encoding="utf-8")
            baseline.write_text(header + baseline_row + current_row, encoding="utf-8")
            manifest.write_text(json.dumps({
                "schema_version": "frozen_baseline_manifest_v0.1",
                "baseline_id": "control",
                "code_identity": "pooled_f_candidate_control",
                "predictions_paths": [str(baseline)],
            }), encoding="utf-8")

            result = run_frozen_baseline_replay_trend_step(_args(tmp))
            payload = json.loads((backtest / "frozen_baseline_replay_trend.json").read_text(encoding="utf-8"))
            report = (backtest / "frozen_baseline_replay_trend_report.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "PRESENT")
        self.assertEqual(result["baseline_variant_id"], "pooled_f_candidate_control")
        self.assertEqual(result["shared_observations"], 1)
        self.assertLess(result["brier_delta_current_minus_baseline"], 0)
        self.assertEqual(payload["independent_baseline_status"], "PRESENT")
        self.assertIn("weather held constant", report)

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

    def test_data_retention_inventory_step_writes_daily_budget_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_root = root
            snapshot = data_root / "snapshots" / "demo" / "snapshots_long.csv"
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text("x" * 16, encoding="utf-8")
            args = _args(tmp, data_root=str(data_root), data_retention_min_free_bytes=0)

            result = run_data_retention_inventory_step(args)
            json_exists = Path(result["json_out"]).exists()
            report_exists = Path(result["report_out"]).exists()

            self.assertEqual(result["status"], "WARN")
            self.assertTrue(json_exists)
            self.assertTrue(report_exists)
            self.assertEqual(result["summary"]["file_count"], 1)

    def test_distribution_stage_attribution_step_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "snapshots" / "highest-temperature-in-test-on-june-1-2026"
            folder.mkdir(parents=True)
            (folder / "settlement.json").write_text(
                json.dumps({
                    "event_slug": folder.name,
                    "market_id": "test",
                    "target_date": "2026-06-01",
                    "settlement_bucket": 22,
                }),
                encoding="utf-8",
            )
            (folder / "components_long.csv").write_text(
                "\n".join([
                    "snapshot_id,captured_at_local,event_slug,cutoff_hour,active_model_kind,component_name,range_label,bin_kind,bin_value_c,component_probability",
                    f"s1,2026-06-01T12:00:00-04:00,{folder.name},12,hgb,climatology_prior,22-23 F,eq,22,0.40",
                    f"s1,2026-06-01T12:00:00-04:00,{folder.name},12,hgb,feature_blend,22-23 F,eq,22,0.70",
                    f"s1,2026-06-01T12:00:00-04:00,{folder.name},12,hgb,post_live_signals,22-23 F,eq,22,0.60",
                ]) + "\n",
                encoding="utf-8",
            )
            args = _args(tmp, distribution_stage_min_rows=1)

            result = run_distribution_stage_attribution_step(args)

            self.assertEqual(result["status"], "ACTIONABLE")
            self.assertTrue(Path(result["json_out"]).exists())
            self.assertTrue(Path(result["report_out"]).exists())
            self.assertEqual(result["settled_folder_count"], 1)
            self.assertEqual(result["market_stage_row_count"], 3)
            self.assertEqual(result["market_stage_cutoff_regime_row_count"], 3)
            self.assertEqual(result["bottom_location_winner_mass_blocker_count"], 0)
            self.assertEqual(result["top_net_negative_stage"]["group"], "post_live_signals")

    def test_settled_day_root_cause_step_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "snapshots" / "highest-temperature-in-test-on-june-20-2026"
            folder.mkdir(parents=True)
            (folder / "settlement.json").write_text(
                json.dumps({
                    "event_slug": folder.name,
                    "market_id": "test",
                    "target_date": "2026-06-20",
                    "settlement_bucket": 82,
                    "settlement_unit": "F",
                }),
                encoding="utf-8",
            )
            (folder / "snapshots_long.csv").write_text(
                "\n".join([
                    "snapshot_id,captured_at_local,event_slug,range_label,bin_kind,bin_value_c,bin_value_hi_c,model_probability,market_yes,forecast_disagreement,wu_history_high_c,wu_current_c,wu_max_since_7am_c",
                    f"s1,2026-06-20T12:00:00-04:00,{folder.name},82-83 F,eq,82,83,0.10,0.55,6.0,82,81,92",
                    f"s1,2026-06-20T12:00:00-04:00,{folder.name},86-87 F,eq,86,87,0.60,0.10,6.0,82,81,92",
                ]) + "\n",
                encoding="utf-8",
            )
            (folder / "features_long.csv").write_text(
                "snapshot_id,high_so_far,current_temp,forecast_disagreement,live_reading_minus_high\n"
                "s1,82,81,6,-1\n",
                encoding="utf-8",
            )
            args = _args(tmp, settled_root_cause_date="2026-06-20")

            result = run_settled_day_root_cause_step(args)

            self.assertEqual(result["status"], "ACTIONABLE")
            self.assertEqual(result["target_date"], "2026-06-20")
            self.assertTrue(Path(result["json_out"]).exists())
            self.assertTrue(Path(result["report_out"]).exists())
            issues_exists = Path(result["issues_out"]).exists()
        self.assertTrue(issues_exists)
        self.assertIn("MODEL_TOP_WARM_SIDE_MISS", result["issue_counts"])

    def test_taker_finalization_watchdog_step_writes_settled_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-1"
            event_slug = "highest-temperature-in-seattle-on-june-19-2026"
            _write_order_tape(
                run / "orders_long.csv",
                [
                    {
                        "schema_version": "taker_bot_run_v0.1",
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "generated_at_utc": "2026-06-19T20:00:00+00:00",
                        "market_id": "seattle",
                        "event_slug": event_slug,
                        "range_label": "80-81 F",
                        "bin_kind": "eq",
                        "bin_value": "80",
                        "bin_value_hi": "81",
                        "clob_token_id": "token-seattle-80",
                        "order_status": "FILLED",
                        "action": "BUY",
                        "fair_probability": "0.80",
                        "best_ask": "0.60",
                        "fill_price": "0.60",
                        "fill_size": "10",
                        "fill_notional_usdc": "6.0",
                        "total_spent_usdc": "6.0",
                        "fee_usdc": "0",
                        "reason_code": "BUY_EDGE",
                        "strategy_id": "raw_edge_control",
                        "strategy_family": "control",
                    }
                ],
            )
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "summary": {
                            "budget_usdc": 100,
                            "cumulative_filled_orders": 1,
                            "cumulative_net_pnl_usdc": 0.0,
                        },
                        "pnl": {"summary": {"filled_order_count": 1, "unsettled_order_count": 1}},
                    }
                ),
                encoding="utf-8",
            )
            labels = root / "backtest" / "market_day_labels.csv"
            labels.parent.mkdir(parents=True)
            labels.write_text(
                "\n".join(
                    [
                        "event_slug,market_id,target_date,settlement_bucket,winning_band,quality_grade",
                        f"{event_slug},seattle,2026-06-19,80,80-81 F,complete",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            args = _args(
                tmp,
                labels_csv=str(labels),
                taker_finalization_min_free_bytes=0,
                skip_taker_bakeoff=True,
            )

            result = run_taker_finalization_watchdog_step(args)
            settled_exists = (run / "settled_pnl.json").exists()
            json_exists = Path(result["json_out"]).exists()
            report_exists = Path(result["report_out"]).exists()

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["finalized_run_count"], 1)
        self.assertTrue(settled_exists)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)

    def test_taker_tail_casebook_step_writes_no_go_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_slug = "highest-temperature-in-atlanta-on-june-21-2026"
            run = root / "taker_runs" / "2026-06-21" / "taker-tail"
            _write_order_tape(
                run / "orders_long.csv",
                [
                    {
                        "run_id": "taker-tail",
                        "target_date": "2026-06-21",
                        "market_id": "atlanta",
                        "event_slug": event_slug,
                        "captured_at_utc": "2026-06-21T20:00:00+00:00",
                        "order_status": "FILLED",
                        "range_label": "84-85 F",
                        "bin_kind": "eq",
                        "bin_value": "84",
                        "bin_value_hi": "85",
                        "clob_token_id": "token-atlanta-84",
                        "fair_probability": "0.40",
                        "best_ask": "0.01",
                        "fill_size": "10",
                        "fill_notional_usdc": "0.1",
                        "total_spent_usdc": "0.1",
                        "low_price_tail": "True",
                        "source_freshness_state": "all_fresh",
                    }
                ],
            )
            labels = root / "backtest" / "market_day_labels.csv"
            labels.parent.mkdir(parents=True)
            labels.write_text(
                "\n".join(
                    [
                        "event_slug,market_id,target_date,settlement_bucket,winning_band,quality_grade",
                        f"{event_slug},atlanta,2026-06-21,80,80-81 F,complete",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_taker_tail_casebook_step(_args(tmp, labels_csv=str(labels)))
            json_exists = Path(result["json_out"]).exists()
            report_exists = Path(result["report_out"]).exists()

        self.assertEqual(result["status"], "BLOCK_BAD_TAIL_SLICES")
        self.assertEqual(result["tail_fill_count"], 1)
        self.assertEqual(result["no_go_candidate_count"], 1)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)

    def test_trading_evidence_step_writes_summary_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-1"
            run.mkdir(parents=True)
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-taker",
                        "summary": {
                            "cumulative_filled_orders": 10,
                            "budget_spent_usdc": 20.0,
                            "cumulative_net_pnl_usdc": -2.0,
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 10,
                                "net_pnl_usdc": -2.0,
                                "mark_to_market_pnl_usdc": -2.0,
                                "settled_order_count": 0,
                                "unsettled_order_count": 10,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_trading_evidence_step(_args(tmp))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report_exists = Path(result["report_out"]).exists()

        self.assertEqual(result["status"], "WARN")
        self.assertEqual(result["taker_quality_status"], "SAMPLE_PENDING_NEGATIVE_LATEST")
        self.assertEqual(payload["taker"]["run_id"], "taker-1")
        self.assertTrue(report_exists)

    def test_settlement_source_audit_step_writes_truth_label_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            daily = root / "daily_summary.csv"
            snapshot = root / "snapshots_long.csv"
            ledger = root / "settlements" / "atlanta" / "ledger.jsonl"
            daily.write_text("local_date,row_count,max_temp_bucket_c\n2026-06-19,24,84\n", encoding="utf-8")
            snapshot.write_text("snapshot_id,wu_history_high_c\ns1,84\n", encoding="utf-8")
            row = {
                "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                "market_id": "atlanta",
                "target_date": "2026-06-19",
                "settlement_bucket": "84",
                "settlement_source": "daily_summary",
                "quality_grade": "complete",
                "reconciliation_status": "match",
                "daily_summary_path": str(daily),
                "snapshot_tape_path": str(snapshot),
                "ledger_path": str(ledger),
                "resolution_timezone": "America/New_York",
                "finalized_at_utc": "2026-06-20T06:00:00+00:00",
            }
            labels = root / "labels.csv"
            labels.write_text(
                ",".join(row.keys()) + "\n" + ",".join(row.values()) + "\n",
                encoding="utf-8",
            )
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")

            result = run_settlement_source_audit_step(_args(tmp, labels_csv=str(labels), ledger_root=str(root / "settlements")))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report_exists = Path(result["report_out"]).exists()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["label_count"], 1)
        self.assertEqual(result["finalized_label_count"], 1)
        self.assertEqual(result["proof_grade_label_count"], 1)
        self.assertEqual(payload["summary"]["promotion_blocked_label_count"], 0)
        self.assertTrue(report_exists)

    def test_maker_paper_score_step_writes_fresh_standard_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run = _write_active_mm_run(tmp)

            result = run_maker_paper_score_step(_args(tmp))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report = Path(result["report_out"]).read_text(encoding="utf-8")
            fills_exists = Path(result["fills_out"]).exists()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["paper_score_freshness_status"], "PASS")
        self.assertEqual(result["latest_completed_active_day"], "2026-06-19")
        self.assertEqual(result["latest_covered_active_day"], "2026-06-19")
        self.assertTrue(fills_exists)
        self.assertEqual(payload["summary"]["paper_score_freshness_status"], "PASS")
        self.assertIn("Paper-score freshness", report)

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
            json_path = root / "backtest" / "active_variant_shadow.json"
            json_exists = json_path.exists()
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            report_path = root / "backtest" / "active_variant_shadow_report.md"
            report_exists = report_path.exists()
            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["summary"]["canonical_rows"], 1)
        self.assertEqual(result["missing_active_variant_ids"], ["missing_v"])
        self.assertEqual(payload["multi_variant_shadow"]["claim_lanes"]["weather_only_core_model"]["rows"], 1)
        self.assertTrue(long_exists)
        self.assertTrue(sidecar_exists)
        self.assertTrue(result["attribution_sidecar_out"].endswith("active_variant_shadow_attribution.jsonl"))
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertIn("Claim Lane Separation", report_text)
        self.assertIn("weather_only_core_model", report_text)

    def test_proper_scoring_reliability_scorecard_step_writes_model_review_artifacts(self):
        rows = [
            {
                "lane": "weather_only",
                "market_id": "atlanta",
                "target_date": "2026-06-19",
                "snapshot_id": "s1",
                "band_key": "eq:84",
                "bin_value": "84",
                "probability": "0.95",
                "market_yes": "0.90",
                "outcome": "1",
                "settlement_distance": "0",
                "cutoff_hour": "9",
                "source_freshness_state": "all_fresh",
                "runtime_identity": "desktop",
                "weak_slot_state": "normal",
                "distribution_family": "bucket",
                "served_probability": "0.94",
                "validated_probability": "0.95",
            },
            {
                "lane": "weather_only",
                "market_id": "atlanta",
                "target_date": "2026-06-19",
                "snapshot_id": "s1",
                "band_key": "eq:85",
                "bin_value": "85",
                "probability": "0.05",
                "market_yes": "0.10",
                "outcome": "0",
                "settlement_distance": "1",
                "cutoff_hour": "9",
                "source_freshness_state": "all_fresh",
                "runtime_identity": "desktop",
                "weak_slot_state": "normal",
                "distribution_family": "bucket",
                "served_probability": "0.04",
                "validated_probability": "0.05",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            source = backtest / "active_variant_shadow_long.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted({key for row in rows for key in row}))
                writer.writeheader()
                writer.writerows(rows)

            result = run_proper_scoring_reliability_scorecard_step(_args(tmp))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report = Path(result["report_out"]).read_text(encoding="utf-8")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_row_count"], 2)
        self.assertEqual(result["scored_probability_row_count"], 4)
        self.assertEqual(result["lane_count"], 2)
        self.assertEqual(result["served_validated_parity_status"], "PASS")
        self.assertEqual(payload["schema_version"], "proper_scoring_reliability_scorecard_v0.1")
        self.assertIn("Literature Appendix", report)

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

    def test_active_variant_shadow_step_executes_registry_predictions_when_sources_empty(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )

        def fake_execute_pooled_contract(variant, contract, **_kwargs):
            out = Path(contract["default_export_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                header
                + "active_v,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-18\n",
                encoding="utf-8",
            )
            return {
                "variant_id": variant["variant_id"],
                "live_runtime": contract["live_runtime"],
                "prediction_function": contract["prediction_function"],
                "status": "OK",
                "output_path": str(out),
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "backtest" / "promotion_corpus.json"
            corpus.parent.mkdir()
            corpus.write_text("{}", encoding="utf-8")
            export = root / "backtest" / "fresh_active.csv"
            registry = root / "config" / "model_variant_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {
                        "variant_id": "active_v",
                        "variant_family": "f_family",
                        "lifecycle": "active",
                        "track": "no_market",
                        "roles": ["candidate", "no-market"],
                        "active_for_headline": True,
                        "artifact_required": False,
                        "prediction_function": "weather.calibration.pooled_candidate_replay:run_pooled_candidate_replay",
                        "prediction_mode": "band_binary",
                        "export_family": "f_family",
                        "default_export_path": str(export),
                        "live_runtime": "pooled_candidate_replay",
                    },
                ],
            }), encoding="utf-8")
            args = _args(tmp, variant_registry=str(registry), promotion_min_artifact_free_bytes=0)

            with patch(
                "weather.reporting.active_variant_shadow_refresh._execute_pooled_candidate_replay_contract",
                side_effect=fake_execute_pooled_contract,
            ) as execute:
                result = run_active_variant_shadow_step(args)

            payload = json.loads((root / "backtest" / "active_variant_shadow.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["execution"]["status"], "OK")
        self.assertEqual(result["summary"]["execution_count"], 1)
        self.assertEqual(payload["execution"]["source_paths"], [str(export)])
        self.assertEqual(payload["registry"]["reported_active_variant_ids"], ["active_v"])
        execute.assert_called_once()

    def test_active_variant_shadow_explicit_sources_bypass_registry_execution(self):
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
                    {
                        "variant_id": "active_v",
                        "variant_family": "f_family",
                        "lifecycle": "active",
                        "track": "no_market",
                        "roles": ["candidate", "no-market"],
                        "active_for_headline": True,
                        "artifact_required": False,
                        "prediction_function": "weather.tests:predict",
                        "prediction_mode": "demo",
                        "export_family": "f_family",
                        "default_export_path": str(root / "unused.csv"),
                        "live_runtime": "pooled_candidate_replay",
                    },
                ],
            }), encoding="utf-8")
            args = _args(
                tmp,
                active_variant_shadow_sources=str(source),
                variant_registry=str(registry),
            )

            with patch("weather.reporting.active_variant_shadow_refresh.execute_registry_prediction_exports") as execute:
                result = run_active_variant_shadow_step(args)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["summary"]["source_path_count"], 1)
        execute.assert_not_called()

    def test_active_variant_shadow_failed_execution_does_not_fall_back_to_stale_exports(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = "active_v,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-18\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "stale.csv"
            stale.write_text(header + row, encoding="utf-8")
            registry = root / "config" / "model_variant_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {
                        "variant_id": "active_v",
                        "variant_family": "f_family",
                        "lifecycle": "active",
                        "track": "no_market",
                        "roles": ["candidate", "no-market"],
                        "active_for_headline": True,
                        "artifact_required": False,
                        "prediction_function": "weather.tests:predict",
                        "prediction_mode": "demo",
                        "export_family": "f_family",
                        "default_export_path": str(stale),
                        "live_runtime": "pooled_candidate_replay",
                    },
                ],
            }), encoding="utf-8")
            args = _args(tmp, variant_registry=str(registry))
            failed_execution = {
                "status": "BLOCK",
                "source_paths": [],
                "executions": [],
                "blockers": ["synthetic execution failure"],
            }

            with patch(
                "weather.reporting.active_variant_shadow_refresh.execute_registry_prediction_exports",
                return_value=failed_execution,
            ):
                result = run_active_variant_shadow_step(args)

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["summary"]["source_path_count"], 0)
        self.assertEqual(result["summary"]["selected_rows"], 0)
        self.assertEqual(result["missing_active_variant_ids"], ["active_v"])

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
        with patch("weather.operations.daily_refresh_steps.all_specs", return_value=[FakeSpec()]), \
                patch("weather.operations.daily_refresh_steps.ReanalysisClient", FakeClient), \
                patch("weather.operations.daily_refresh_steps.ReanalysisStore", FakeStore):
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
                patch("weather.operations.daily_refresh_steps.data_auditor.audit_fleet_historical_data", return_value=fake_results):
            result = run_ingest_quality_gate_step(_args(tmp, ingest_quality_years="2026"))

            self.assertEqual(result["status"], "WARN")
            self.assertTrue(Path(result["json_out"]).exists())
            self.assertTrue(Path(result["report_out"]).exists())
            self.assertEqual(result["summary"]["markets_with_missing_days"], 1)


if __name__ == "__main__":
    unittest.main()
