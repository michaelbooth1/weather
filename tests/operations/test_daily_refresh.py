import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from weather.market import exchange_economics, mm_paper
from weather.market.taker_bot import ORDER_COLUMNS
from weather.market.market_config import event_slug_for_date
from weather.market.mm_scoring_projection import (
    BASE_PROJECTION_FILENAME,
    LIVE_APPEND_PREFIX_BINDING_MODE,
    MODEL_VARIANT_PROJECTION_FILENAME,
    SCORING_COLUMNS,
    resolve_run_scoring_inputs,
    write_run_scoring_projections,
)
from weather.operations.daily_refresh import (  # noqa: E402
    DEFAULT_RUNNERS,
    _captured_input_parity_preflight,
    acquire_lock,
    build_parser,
    cmd_run,
    load_status,
    repair_stale_locks,
    release_lock,
    run_active_variant_shadow_step,
    run_clob_order_book_tiering_step,
    run_data_retention_inventory_step,
    run_daily_flow_analysis_step,
    run_daily_refresh,
    run_distribution_stage_attribution_step,
    run_exchange_economics_rule_drift_step,
    run_frozen_baseline_replay_trend_step,
    run_ingest_quality_gate_step,
    run_june23_location_bias_repair_step,
    run_live_variant_settlement_scorecard_step,
    run_market_day_labels_finalize,
    run_maker_paper_score_step,
    run_market_beating_objective_scoreboard_step,
    run_model_market_disagreement_rehydration_step,
    run_model_variant_evidence_growth_step,
    run_observed_floor_safety_monitor_step,
    run_promotion_refresh_step,
    run_price_free_model_learning_step,
    run_public_wu_settlement_restore_step,
    run_proper_scoring_reliability_scorecard_step,
    run_reanalysis_recent_refresh_step,
    run_daily_roll_log_hygiene_step,
    run_runtime_identity_reconciliation_step,
    run_settled_day_analysis_barrier_step,
    run_settled_day_root_cause_step,
    run_settlement_source_audit_step,
    run_taker_edge_permission_map_step,
    run_taker_finalization_watchdog_step,
    run_taker_tail_casebook_step,
    run_trading_evidence_step,
    run_winner_rank_parity_step,
    pipeline_summary,
)
from weather.operations.daily_refresh_registry import (
    COVERAGE_MODE_CHOICES,
    LANE_CHOICES,
    LANE_LEARNING,
    LANE_PROMOTION,
    STEP_LANES,
    STEP_LEARNING_COVERAGE_DEPENDENCIES,
    STEP_LEARNING_COVERAGE_MODES,
    STEP_ORDER,
    STEP_PROMOTION_GATES,
    STEP_PROMOTION_RECEIPT_POLICIES,
    STEP_REGISTRY,
    carried_forward_steps,
    step_names_for_stage,
)
from weather.operations.daily_refresh_lanes import (
    promotion_lane_outcome_blocker,
)
from weather.operations.daily_refresh_settled_day import (
    SETTLED_DAY_ANALYSIS_DEPENDENCIES,
    _dependency_status,
)
from weather.operations.daily_refresh_steps import SettledDayAnalysisBarrierError
from weather.operations.daily_refresh_report import render_report as render_daily_refresh_report
from weather.reporting.candidate_lifecycle.active_variant_shadow_refresh import build_payload as build_active_variant_shadow_payload


def _recent_active_variant_row(as_of=None):
    """Return settled evidence that cannot age out as the calendar advances."""
    current = as_of or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    target_date = (
        current.astimezone(ZoneInfo("America/Toronto")).date()
        - timedelta(days=1)
    ).isoformat()
    return (
        "active_v,f_family,False,False,nyc,"
        f"{target_date},s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,{target_date}\n"
    )


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
        "as_of": None,
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
        "fail_on_nightly_health_critical": False,
        "skip_shadow_ab_monitor": False,
        "ab_current_tol": 0.003,
        "ab_market_tol": 0.003,
        "skip_active_variant_shadow": False,
        "active_variant_shadow_sources": "",
        "active_variant_shadow_window_dates": 14,
        "heavy_step_subprocess": False,
        "heavy_step_timeout_seconds": 60.0,
        "heavy_step_working_set_max_mb": 0,
        "capture_resource_mode": "offline_host",
        "capture_resource_disk_path": str(root),
        "capture_resource_out": str(root / "backtest" / "capture_resource_gate.json"),
        "capture_resource_report": str(root / "backtest" / "capture_resource_gate.md"),
        "capture_resource_min_free_memory_bytes": 0,
        "capture_resource_min_free_disk_bytes": 0,
        "capture_resource_daily_disk_growth_bytes": None,
        "capture_resource_min_disk_headroom_days": 30.0,
        "capture_resource_active_window_start_hour": None,
        "capture_resource_active_window_end_hour": None,
        "captured_input_parity_served": [],
        "captured_input_parity_replay": [],
        "captured_input_parity_out": str(
            root / "backtest" / "live_variant_replay_parity.json"
        ),
        "captured_input_parity_report": str(
            root / "backtest" / "live_variant_replay_parity.md"
        ),
        "captured_input_parity_max_age_hours": 48.0,
        "skip_captured_input_replay_parity": True,
        "production_readiness_evidence": [],
        "production_readiness_served_artifact": [],
        "production_readiness_served_route": "",
        "production_readiness_out": str(
            root / "backtest" / "production_readiness_gate.json"
        ),
        "production_readiness_report": str(
            root / "backtest" / "production_readiness_gate.md"
        ),
        "skip_production_readiness_gate": True,
        "fail_on_production_readiness_block": False,
        "skip_proper_scoring_reliability_scorecard": False,
        "_daily_refresh_steps_so_far": [
            {
                "name": "live_variant_settlement_scorecard",
                "status": "ok",
                "result": {"status": "PASS"},
            }
        ],
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
        "skip_public_wu_settlement_restore": False,
        "wu_settlement_restore_markets": "all",
        "wu_settlement_restore_sleep": 0.0,
        "wu_settlement_restore_timeout": 30.0,
        "wu_settlement_restore_skip_existing": True,
        "wu_settlement_restore_continue_on_error": True,
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
        "skip_model_market_disagreement_rehydration": False,
        "model_market_disagreement_log": str(root / "backtest" / "model_market_disagreement_audit.jsonl"),
        "model_market_disagreement_min_pattern_cases": 1,
        "skip_settled_day_analysis_barrier": False,
        "settled_analysis_target_date": "",
        "skip_settled_day_root_cause": False,
        "settled_root_cause_date": "",
        "skip_winner_rank_parity": False,
        "winner_rank_parity_days": 7,
        "winner_rank_parity_min_snapshots": 1,
        "skip_june23_location_bias_repair": False,
        "june23_location_bias_repair_date": "2026-06-23",
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
        "skip_exchange_economics_rule_drift": False,
        "exchange_economics_snapshot": str(root / "backtest" / "exchange_economics_snapshot.json"),
        "exchange_economics_accepted_snapshot": str(root / "backtest" / "exchange_economics_accepted_snapshot.json"),
        "exchange_economics_platform": exchange_economics.DEFAULT_PLATFORM,
        "event_metadata_config": str(root / "config" / "location_market_events.json"),
        "skip_taker_tail_casebook": False,
        "skip_taker_edge_permission_map": False,
        "taker_edge_permission_map_out": str(root / "backtest" / "taker_edge_permission_map.json"),
        "taker_edge_permission_min_settled_orders": 5,
        "taker_edge_permission_min_independent_days": 3,
        "taker_edge_permission_min_after_fee_skill": 0.0,
        "taker_tail_casebook_date": "",
        "taker_tail_casebook_max_runs": 0,
        "skip_maker_paper_score": False,
        "skip_settlement_source_audit": False,
        "fail_on_observed_floor_safety": False,
        "skip_trading_evidence": False,
        "promotion_min_artifact_free_bytes": 1024 * 1024 * 1024,
        "replay_cache": "read_write",
        "replay_cache_root": "",
        "disable_replay_cache_sentinel": False,
        "include_reconstructed": False,
        "allow_unsettled": False,
        "skip_serving_gauntlet": False,
        "require_exact_identity": False,
        "require_all_markets": False,
        "quality_grades": "complete,manual_override",
        "labels_csv": str(root / "backtest" / "market_day_labels.csv"),
        "ledger_root": str(root / "settlements"),
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
        "skip_nightly_health_checks": False,
        "skip_daily_roll_log_hygiene": False,
        "daily_roll_log_window_hours": 24.0,
        "daily_roll_log_sources": "",
        "daily_roll_log_incidents": "",
        "daily_roll_current_log_root": "",
        "nightly_health_alert_root": str(root / "alerts"),
        "nightly_health_timezone": "America/Toronto",
        "nightly_health_date": "",
        "nightly_health_max_bot_activity_age_seconds": 300.0,
        "nightly_health_startup_grace_seconds": 180.0,
        "data_layer_historical_start": "2000-01-01",
        "data_layer_historical_end": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _write_exchange_snapshot(path, *, target_date="2026-06-19", now="2026-06-20T12:00:00+00:00", **overrides):
    payload = exchange_economics.build_snapshot_payload(
        target_date=target_date,
        verified_at_utc=now,
        **overrides,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _collect_test_exchange_snapshot(**kwargs):
    payload = exchange_economics.build_snapshot_payload(
        target_date=kwargs["target_date"],
        verified_at_utc=kwargs.get("now") or "2026-06-20T12:00:00+00:00",
    )
    path = Path(kwargs["snapshot_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {
        "status": "PASS",
        "snapshot_path": str(path),
        "target_date": kwargs["target_date"],
        "payload": payload,
    }


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
    token_id = f"token-{run_id}"
    captured_payload = exchange_economics.build_snapshot_payload(
        target_date=target_date,
        verified_at_utc=f"{target_date}T15:55:00+00:00",
        token_ids=[token_id, f"other-{run_id}"],
    )
    captured_path = run / exchange_economics.RUN_CAPTURE_FILENAME
    exchange_economics.write_json(captured_path, captured_payload)
    captured_gate = exchange_economics.load_exchange_economics_gate(
        captured_path,
        target_date,
        now=f"{target_date}T20:00:00+00:00",
    )
    captured_economics = {
        "status": "CAPTURED",
        "captured": True,
        "path": str(captured_path),
        "filename": exchange_economics.RUN_CAPTURE_FILENAME,
        "snapshot_id": captured_gate["snapshot_id"],
        "snapshot_hash": captured_gate["snapshot_hash"],
        "source_hash": captured_gate["source_hash"],
        "file_sha256": hashlib.sha256(captured_path.read_bytes()).hexdigest(),
    }
    run_config = {
        "schema_version": "mm_run_v0.2",
        "run_id": run_id,
        "created_at_utc": f"{target_date}T20:00:00+00:00",
        "mode": "paper-live-forward",
        "target_date": target_date,
        "policy_hash": f"policy-{run_id}",
        "exchange_economics_capture": captured_economics,
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
        "clob_token_id": token_id,
        "exchange_economics_snapshot_id": captured_gate["snapshot_id"],
        "exchange_economics_hash": captured_gate["snapshot_hash"],
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


def _stage_a_promotion_receipts(target_date, *, overrides=None):
    overrides = overrides or {}
    rows = []
    for name in step_names_for_stage("settlement"):
        if not STEP_PROMOTION_GATES[name]:
            continue
        action_statuses = STEP_PROMOTION_RECEIPT_POLICIES[name][
            "action_statuses"
        ]
        accepted_status = next(
            status
            for status in ("PASS", "OK", "BLOCK")
            if status in action_statuses
        )
        result = {"status": accepted_status}
        for field in STEP_PROMOTION_RECEIPT_POLICIES[name].get(
            "target_fields", ()
        ):
            result[field] = target_date
        for field in STEP_PROMOTION_RECEIPT_POLICIES[name].get(
            "positive_count_fields", ()
        ):
            result[field] = 1
        row = {
            "name": name,
            "status": "ok",
            "result": result,
        }
        rows.append(overrides.get(name, row))
    return rows


def _settled_barrier_dependency_steps(target_date, *, restore=True, restore_after_finalize=False):
    restore_step = {
        "name": "public_wu_settlement_restore",
        "status": "ok",
        "result": {"status": "PASS", "target_date": target_date},
    }
    finalize_step = {
        "name": "market_day_labels_finalize",
        "status": "ok",
        "result": {"label_count": 0},
    }
    steps = []
    if restore and not restore_after_finalize:
        steps.append(restore_step)
    steps.append(finalize_step)
    if restore and restore_after_finalize:
        steps.append(restore_step)
    steps.extend([
        {
            "name": "exchange_economics_rule_drift",
            "status": "ok",
            "result": {"status": "PASS", "target_date": target_date},
        },
        {"name": "taker_finalization_watchdog", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "taker_edge_permission_map", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "taker_tail_casebook", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "maker_paper_score", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "settlement_source_audit", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "observed_floor_safety_monitor", "status": "ok", "result": {"status": "PASS", "target_date": target_date}},
        {"name": "trading_evidence", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "replay_status_backfill", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "hourly_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "ten_minute_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "price_free_model_learning", "status": "ok", "result": {"status": "SKIPPED"}},
        {"name": "model_market_disagreement_rehydration", "status": "ok", "result": {"status": "SKIPPED"}},
    ])
    return steps


class TestDailyRefresh(unittest.TestCase):
    def test_run_daily_refresh_executes_steps_in_order_and_writes_status(self):
        calls = []

        def runner(name, result=None):
            def _run(_args):
                calls.append(name)
                return result or {"name": name}
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date="2026-07-07")
            payload, status_path, report_path = run_daily_refresh(
                args,
                runners=[
                    ("market_day_labels_finalize", runner("market_day_labels_finalize")),
                    (
                        "settled_day_analysis_barrier",
                        runner(
                            "settled_day_analysis_barrier",
                            {"status": "PASS", "target_date": "2026-07-07"},
                        ),
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        runner(
                            "live_variant_settlement_scorecard",
                            {
                                "status": "PASS",
                                "target_date": "2026-07-07",
                                "source_row_count": 1,
                                "valid_prediction_partition_count": 1,
                            },
                        ),
                    ),
                    (
                        "fleet_observability",
                        runner("fleet_observability", {"status": "OK"}),
                    ),
                    (
                        "promotion_refresh",
                        runner("promotion_refresh", {"status": "OK"}),
                    ),
                    ("progress_audit", runner("progress_audit")),
                    ("disagreement_casebook", runner("disagreement_casebook")),
                ],
            )

            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            guard_state = json.loads(Path(args.long_job_state).read_text(encoding="utf-8"))
            report_exists = Path(report_path).exists()
            capture_proof = json.loads(
                Path(args.capture_resource_out).read_text(encoding="utf-8")
            )

        self.assertEqual(calls, [
            "market_day_labels_finalize",
            "settled_day_analysis_barrier",
            "live_variant_settlement_scorecard",
            "fleet_observability",
            "promotion_refresh",
            "progress_audit",
            "disagreement_casebook",
        ])
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["capture_resource_admission"]["admitted"])
        self.assertEqual(payload["capture_resource_admission"]["decision"], "ADMIT")
        self.assertEqual(
            capture_proof["enforcement"]["status"],
            "PASS",
        )
        self.assertEqual(saved["status"], "ok")
        self.assertTrue(saved["config"]["long_job_guard"]["enabled"])
        self.assertFalse(saved["config"]["long_job_guard"]["nested"])
        self.assertEqual(guard_state["status"], "complete")
        self.assertEqual(
            guard_state["progress"]["last_completed_step"],
            "disagreement_casebook",
        )
        self.assertEqual(guard_state["progress"]["completed_step_count"], 7)
        self.assertEqual(guard_state["progress"]["total_step_count"], 7)
        self.assertTrue(report_exists)

    def test_progress_counts_only_terminal_successes_and_keeps_declared_total(self):
        def ok(_args):
            return {"status": "PASS"}

        def failed(_args):
            raise RuntimeError("expected failure")

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, continue_on_error=True)
            payload, _status_path, report_path = run_daily_refresh(
                args,
                runners=[
                    ("ingest_quality_gate", ok),
                    ("event_metadata_validation", failed),
                ],
            )
            guard_state = json.loads(Path(args.long_job_state).read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(guard_state["progress"]["last_completed_step"], "ingest_quality_gate")
        self.assertEqual(guard_state["progress"]["completed_step_count"], 1)
        self.assertEqual(guard_state["progress"]["total_step_count"], 2)

    def test_cli_exit_code_matches_written_normal_and_deferred_status(self):
        for terminal_status, expected_exit in (("ok", 0), ("deferred", 2)):
            with self.subTest(status=terminal_status), tempfile.TemporaryDirectory() as tmp:
                args = _args(tmp, dry_run=True)

                def fake_run(run_args):
                    payload = {"status": terminal_status, "terminal": True}
                    status_path = Path(run_args.status_out)
                    report_path = Path(run_args.report_out)
                    status_path.parent.mkdir(parents=True, exist_ok=True)
                    status_path.write_text(json.dumps(payload), encoding="utf-8")
                    report_path.write_text("# test\n", encoding="utf-8")
                    return payload, status_path, report_path

                with patch(
                    "weather.operations.daily_refresh.run_daily_refresh",
                    side_effect=fake_run,
                ), patch(
                    "weather.operations.daily_refresh.trigger_evidence_stage_after_lock",
                    return_value={"status": "SKIPPED"},
                ):
                    actual_exit = cmd_run(args)
                saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))

            self.assertEqual(actual_exit, expected_exit)
            self.assertEqual(saved["status"], terminal_status)

    def test_live_capture_denial_defers_heavy_steps_but_runs_lightweight_learning(self):
        calls = []

        def heavy(_args):
            calls.append("heavy_child_started")
            return {"status": "PASS"}

        def learning(_args):
            calls.append("daily_learning")
            return {"status": "BLOCKED"}

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, capture_resource_mode="live")
            snapshots = Path(args.snapshots_root)
            snapshots.mkdir(parents=True)
            now = datetime.now(timezone.utc).isoformat()
            status = snapshots / "loop_status.json"
            status.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "last_heartbeat": now,
                        "interval_seconds": 600,
                        "consecutive_errors": 0,
                    }
                ),
                encoding="utf-8",
            )
            status.with_name(f".{status.name}.writer.lock").write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "loop": "snapshot",
                        "module": "weather.collection.snapshot_tracker",
                        "acquired_at_utc": now,
                    }
                ),
                encoding="utf-8",
            )

            payload, status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("promotion_refresh", heavy),
                    ("active_variant_shadow", heavy),
                    ("daily_learning", learning),
                ],
            )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            proof = json.loads(Path(args.capture_resource_out).read_text(encoding="utf-8"))

        self.assertEqual(calls, ["daily_learning"])

        self.assertEqual(payload["status"], "deferred")
        admission = next(
            step
            for step in payload["steps"]
            if step["name"] == "capture_resource_admission"
        )
        self.assertEqual(admission["status"], "deferred")
        deferred = {
            step["name"]: step
            for step in payload["steps"]
            if step["name"] in {"promotion_refresh", "active_variant_shadow"}
        }
        self.assertEqual(deferred["promotion_refresh"]["status"], "deferred")
        self.assertEqual(deferred["active_variant_shadow"]["status"], "deferred")
        learning_step = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        self.assertEqual(learning_step["status"], "ok")
        self.assertEqual(
            learning_step["result"]["target_settlement_coverage"]["coverage_status"],
            "GAPPED",
        )
        self.assertEqual(saved["status"], "deferred")
        self.assertFalse(proof["admitted"])
        self.assertEqual(proof["decision"], "DEFER")
        self.assertEqual(
            proof["enforcement"]["outcome"],
            "DEFERRED_BEFORE_HEAVY_WORK",
        )
        self.assertIn(
            "live_capture_loop_active",
            {row["code"] for row in proof["blockers"]},
        )

    def test_live_capture_denial_rewrites_real_daily_learning_with_gap(self):
        calls = []

        def promotion(_args):
            calls.append("promotion_refresh")
            return {"status": "SHOULD_NOT_RUN"}

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                capture_resource_mode="live",
                settled_analysis_target_date="2026-07-07",
            )
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            (backtest / "f_family_promotion_refresh.json").write_text(
                json.dumps(
                    {
                        "generated_at_utc": "2026-07-07T12:00:00+00:00",
                        "status": "PASS",
                        "corpus": {"date_max": "2026-07-06"},
                    }
                ),
                encoding="utf-8",
            )
            snapshots = Path(args.snapshots_root)
            snapshots.mkdir(parents=True)
            now = datetime.now(timezone.utc).isoformat()
            status = snapshots / "loop_status.json"
            status.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "last_heartbeat": now,
                        "interval_seconds": 600,
                        "consecutive_errors": 0,
                    }
                ),
                encoding="utf-8",
            )
            status.with_name(f".{status.name}.writer.lock").write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "loop": "snapshot",
                        "module": "weather.collection.snapshot_tracker",
                        "acquired_at_utc": now,
                    }
                ),
                encoding="utf-8",
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    ("promotion_refresh", promotion),
                    ("daily_learning", dict(DEFAULT_RUNNERS)["daily_learning"]),
                ],
            )
            artifact = json.loads(
                (Path(args.backtest_root) / "daily_learning.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(calls, [])
        self.assertEqual(payload["status"], "deferred")
        self.assertEqual(artifact["status"], "BLOCKED")
        self.assertEqual(
            artifact["target_settlement_coverage"]["coverage_status"],
            "GAPPED",
        )
        self.assertEqual(
            artifact["target_settlement_coverage"]["corpus_date_max"],
            "2026-07-06",
        )
        self.assertEqual(
            artifact["target_settlement_coverage"]["staleness_days"],
            1,
        )
        self.assertEqual(
            payload["lanes"][LANE_LEARNING]["status"],
            "PARTIAL",
        )

    def test_skipped_active_shadow_bypasses_heavy_preflight_after_promotion_block(self):
        calls = []

        def barrier(_args):
            raise SettledDayAnalysisBarrierError(
                "settlement unavailable",
                {
                    "status": "BLOCK",
                    "target_date": "2026-07-07",
                    "hard_stop_pipeline": True,
                },
            )

        def learning(_args):
            calls.append("daily_learning")
            return {"status": "BLOCKED"}

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                capture_resource_mode="live",
                settled_analysis_target_date="2026-07-07",
                skip_active_variant_shadow=True,
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("settled_day_analysis_barrier", barrier),
                    (
                        "promotion_refresh",
                        lambda _args: self.fail("promotion work started"),
                    ),
                    (
                        "active_variant_shadow",
                        dict(DEFAULT_RUNNERS)["active_variant_shadow"],
                    ),
                    ("daily_learning", learning),
                ],
            )

        self.assertEqual(calls, ["daily_learning"])
        self.assertNotIn("capture_resource_admission", {
            step["name"] for step in payload["steps"]
        })
        active = next(
            step for step in payload["steps"] if step["name"] == "active_variant_shadow"
        )
        self.assertEqual(active["result"]["status"], "SKIPPED")
        self.assertEqual(payload["status"], "critical")

    def test_isolated_stage_a_orchestration_error_hard_stops_continue_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            args = _args(
                tmp,
                stage="settlement",
                resume_from_step="maker_paper_score",
                continue_on_error=True,
                disable_long_job_guard=True,
                skip_production_readiness_gate=False,
                stage_a_manifest=str(Path(tmp) / "backtest" / "stage_a.json"),
                stage_b_manifest=str(Path(tmp) / "backtest" / "stage_b.json"),
            )
            maker_runner = dict(DEFAULT_RUNNERS)["maker_paper_score"]

            def later(_args):
                calls.append("settlement_source_audit")
                return {"status": "PASS"}

            with patch(
                "weather.operations.daily_refresh._run_isolated_stage_a_step",
                side_effect=OSError("status persistence failed"),
            ), patch(
                "weather.operations.daily_refresh._production_readiness_status"
            ) as readiness:
                payload, _status, _report = run_daily_refresh(
                    args,
                    runners=[
                        ("maker_paper_score", maker_runner),
                        ("settlement_source_audit", later),
                    ],
                )

        self.assertEqual(calls, [])
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["steps"][-1]["name"], "maker_paper_score")
        self.assertEqual(payload["production_readiness"]["status"], "SKIPPED")
        readiness.assert_not_called()

    def test_missing_captured_input_replay_defers_heavy_steps_but_runs_learning(self):
        calls = []

        def heavy(_args):
            calls.append("heavy_child_started")
            return {"status": "PASS"}

        def learning(_args):
            calls.append("daily_learning")
            return {"status": "BLOCKED"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            served = root / "captured" / "served.json"
            served.parent.mkdir(parents=True)
            served.write_text("[]\n", encoding="utf-8")
            args = _args(
                tmp,
                skip_captured_input_replay_parity=False,
                captured_input_parity_served=[str(served)],
                captured_input_parity_replay=[
                    str(root / "captured" / "replay.json")
                ],
            )
            with patch(
                "weather.operations.daily_refresh.producer_release_proof",
                return_value={
                    "status": "PASS",
                    "release_id": "active-r1",
                    "release_manifest_sha256": "a" * 64,
                },
            ):
                payload, status_path, _report_path = run_daily_refresh(
                    args,
                    runners=[
                        ("promotion_refresh", heavy),
                        ("active_variant_shadow", heavy),
                        ("daily_learning", learning),
                    ],
                )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            parity = json.loads(
                Path(args.captured_input_parity_out).read_text(encoding="utf-8")
            )
            report_exists = Path(args.captured_input_parity_report).is_file()

        self.assertEqual(calls, ["daily_learning"])
        self.assertEqual(payload["status"], "deferred")
        parity_step = next(
            step
            for step in payload["steps"]
            if step["name"] == "captured_input_replay_parity"
        )
        self.assertEqual(parity_step["status"], "deferred")
        self.assertTrue(parity_step["result"]["hard_stop_pipeline"])
        self.assertIn(
            "generate exact captured-input replay rows",
            parity_step["result"]["next_action"],
        )
        learning_step = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        self.assertEqual(learning_step["status"], "ok")
        self.assertEqual(saved["status"], "deferred")
        self.assertEqual(parity["status"], "BLOCK")
        self.assertIn(
            "replay_parity_input_missing",
            {row["code"] for row in parity["mismatches"]},
        )
        self.assertTrue(report_exists)

    def test_production_readiness_is_final_read_only_daily_status_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = root / "releases" / "current_release.json"
            args = _args(
                tmp,
                skip_production_readiness_gate=False,
                active_release_pointer=str(pointer),
                releases_root=str(root / "releases"),
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("fleet_observability", lambda _args: {"status": "OK"}),
                ],
            )
            gate = json.loads(
                Path(args.production_readiness_out).read_text(encoding="utf-8")
            )
            gate_report_exists = Path(args.production_readiness_report).is_file()

        self.assertEqual(payload["steps"][-1]["name"], "production_readiness_gate")
        self.assertEqual(payload["steps"][-1]["status"], "ok")
        self.assertEqual(payload["production_readiness"]["status"], "BLOCK")
        self.assertTrue(payload["production_readiness"]["read_only"])
        self.assertFalse(payload["production_readiness"]["pointer_mutated"])
        self.assertEqual(gate["status"], "BLOCK")
        self.assertFalse(pointer.exists())
        self.assertTrue(gate_report_exists)

    def test_parity_exception_persists_block_and_skips_stale_final_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                skip_captured_input_replay_parity=False,
                skip_production_readiness_gate=False,
            )
            with patch(
                "weather.operations.daily_refresh.live_variant_settlement_scorecard.persist_captured_input_replay_parity",
                side_effect=ValueError("bad parity configuration"),
            ):
                payload, _status, _report = run_daily_refresh(
                    args,
                    runners=[("promotion_refresh", lambda _args: self.fail("heavy work started"))],
                )
            parity = json.loads(Path(args.captured_input_parity_out).read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "deferred")
        self.assertEqual(payload["steps"][-1]["name"], "promotion_refresh")
        self.assertEqual(payload["production_readiness"]["status"], "SKIPPED")
        self.assertEqual(
            payload["production_readiness"]["reason"],
            "upstream_pipeline_not_successful",
        )
        self.assertEqual(parity["status"], "BLOCK")
        self.assertEqual(parity["first_mismatch"]["code"], "parity_preflight_exception")
        parity_step = next(row for row in payload["steps"] if row["name"] == "captured_input_replay_parity")
        self.assertEqual(parity_step["result"]["proof_path"], args.captured_input_parity_out)

    def test_parity_output_alias_cannot_modify_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = root / "releases" / "current_release.json"
            pointer.parent.mkdir(parents=True)
            original = b'{"release_id":"active-r1"}\n'
            pointer.write_bytes(original)
            args = _args(
                tmp,
                captured_input_parity_out=str(pointer),
                captured_input_parity_report=str(root / "backtest" / "parity.md"),
                active_release_pointer=str(pointer),
                releases_root=str(pointer.parent),
            )
            with patch(
                "weather.operations.daily_refresh.live_variant_settlement_scorecard.persist_captured_input_replay_parity_failure"
            ) as failure_persistence:
                parity, proof_path, report_path = _captured_input_parity_preflight(
                    args,
                    {
                        "release_id": "active-r1",
                        "release_manifest_sha256": "a" * 64,
                    },
                )

            self.assertEqual(pointer.read_bytes(), original)
            self.assertEqual(parity["status"], "BLOCK")
            self.assertEqual(
                parity["first_mismatch"]["code"],
                "parity_output_protected_path",
            )
            self.assertIsNone(proof_path)
            self.assertIsNone(report_path)
            self.assertFalse((root / "backtest" / "parity.md").exists())
            failure_persistence.assert_not_called()

    def test_readiness_block_policy_marks_daily_pipeline_critical(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                skip_production_readiness_gate=False,
                fail_on_production_readiness_block=True,
            )
            payload, _status, _report = run_daily_refresh(
                args,
                runners=[("fleet_observability", lambda _args: {"status": "OK"})],
            )

        self.assertEqual(payload["production_readiness"]["status"], "BLOCK")
        self.assertEqual(payload["status"], "critical")

    def test_stage_step_slices_split_after_fleet_observability(self):
        settlement = step_names_for_stage("settlement")
        evidence = step_names_for_stage("evidence")

        self.assertEqual(settlement[-1], "fleet_observability")
        self.assertEqual(evidence[0], "promotion_refresh")
        self.assertNotIn("promotion_refresh", settlement)
        self.assertNotIn("fleet_observability", evidence)

    def test_every_registered_step_declares_exactly_one_lane(self):
        self.assertEqual(tuple(STEP_LANES), STEP_ORDER)
        self.assertEqual(
            tuple(name for name, _lane, _gate in STEP_REGISTRY),
            STEP_ORDER,
        )
        self.assertEqual(len(STEP_REGISTRY), len(set(STEP_ORDER)))
        self.assertEqual(set(STEP_LANES.values()), set(LANE_CHOICES))
        self.assertEqual(tuple(STEP_PROMOTION_GATES), STEP_ORDER)
        promotion_gate_names = {
            name
            for name, blocks in STEP_PROMOTION_GATES.items()
            if blocks
        }
        self.assertEqual(
            set(STEP_PROMOTION_RECEIPT_POLICIES),
            promotion_gate_names,
        )
        self.assertTrue(
            all(
                policy["action_statuses"] <= policy["known_statuses"]
                for policy in STEP_PROMOTION_RECEIPT_POLICIES.values()
            )
        )
        learning_names = {
            name for name, lane in STEP_LANES.items() if lane == LANE_LEARNING
        }
        self.assertEqual(set(STEP_LEARNING_COVERAGE_MODES), learning_names)
        self.assertTrue(
            set(STEP_LEARNING_COVERAGE_MODES.values()).issubset(
                set(COVERAGE_MODE_CHOICES)
            )
        )
        dependency_names = {
            name
            for name, mode in STEP_LEARNING_COVERAGE_MODES.items()
            if mode == "dependencies"
        }
        self.assertEqual(
            set(STEP_LEARNING_COVERAGE_DEPENDENCIES),
            dependency_names,
        )
        self.assertTrue(
            all(
                isinstance(blocks_promotion, bool)
                for _name, _lane, blocks_promotion in STEP_REGISTRY
            )
        )
        self.assertEqual(tuple(name for name, _runner in DEFAULT_RUNNERS), STEP_ORDER)

    def test_promotion_receipts_fail_closed_on_malformed_or_vacuous_evidence(self):
        target = "2026-07-07"
        cases = (
            (
                "unknown_status",
                "ingest_quality_gate",
                {"status": "MYSTERY"},
                "promotion_receipt_unknown_status",
            ),
            (
                "target_missing",
                "hourly_model_performance",
                {"status": "PASS"},
                "promotion_receipt_target_missing",
            ),
            (
                "target_mismatch",
                "ten_minute_model_performance",
                {
                    "status": "PASS",
                    "last_scored_target_date": "2026-07-06",
                },
                "promotion_receipt_target_mismatch",
            ),
            (
                "runtime_zero_rows",
                "runtime_identity_reconciliation",
                {
                    "status": "PASS",
                    "target_date": target,
                    "snapshot_row_count": 0,
                },
                "promotion_receipt_vacuous",
            ),
            (
                "live_zero_rows",
                "live_variant_settlement_scorecard",
                {
                    "status": "PASS",
                    "target_date": target,
                    "source_row_count": 0,
                    "valid_prediction_partition_count": 1,
                },
                "promotion_receipt_vacuous",
            ),
            (
                "fleet_warning",
                "fleet_observability",
                {"status": "WARN"},
                "promotion_gate_negative_verdict",
            ),
            (
                "fleet_critical",
                "fleet_observability",
                {"status": "CRITICAL"},
                "promotion_gate_negative_verdict",
            ),
        )
        for label, name, result, expected_class in cases:
            with self.subTest(label=label):
                blocker = promotion_lane_outcome_blocker(
                    [{"name": name, "status": "ok", "result": result}],
                    required_names=(name,),
                    target_date=target,
                )
                self.assertEqual(blocker["step"], name)
                self.assertEqual(
                    blocker["root_cause_class"], expected_class
                )

    def test_settlement_stage_writes_manifest_and_skips_evidence_tail(self):
        calls = []

        def runner(name, result=None):
            def _run(_args):
                calls.append(name)
                return result or {"status": "OK"}
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            stage_a_manifest = Path(tmp) / "backtest" / "stage_a.json"
            args = _args(
                tmp,
                stage="settlement",
                stage_a_manifest=str(stage_a_manifest),
                disable_stage_trigger=True,
                settled_analysis_target_date="2026-07-07",
            )
            args.producer_sla_seconds = 3600.0
            args._producer_invocation = {
                "status": "PASS",
                "mode": "scheduled",
                "scheduler_attested": True,
                "task_name": "WeatherDailySettlementPromotionRefresh",
                "task_definition_sha256": "a" * 64,
                "manual_intervention": False,
                "manual_intervention_reasons": [],
                "resume_from_step": "",
                "resumed": False,
                "dry_run": False,
                "contract": {"status": "PASS", "contract_sha256": "b" * 64},
                "task_run_correlation": {"status": "PASS"},
            }
            args._producer_release_identity = {
                "status": "PASS",
                "served_bindings_verified": True,
                "release_id": "release-fixture",
                "release_manifest_sha256": "c" * 64,
            }
            args._daily_refresh_lock_acquisition = {
                "instrumented": True,
                "kind": "daily_refresh_lock",
                "guard_enabled": True,
                "nested": False,
                "stale_lock_detected_count": 0,
                "stale_lock_repair_count": 0,
                "forced_lock_acquisition_count": 0,
                "forced_lock_repair_count": 0,
                "acquired": True,
            }
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("reanalysis_recent_refresh", runner("reanalysis_recent_refresh")),
                    (
                        "settled_day_analysis_barrier",
                        runner(
                            "settled_day_analysis_barrier",
                            {"status": "PASS", "target_date": "2026-07-07"},
                        ),
                    ),
                    ("fleet_observability", runner("fleet_observability")),
                    ("promotion_refresh", runner("promotion_refresh")),
                ],
            )
            manifest = json.loads(stage_a_manifest.read_text(encoding="utf-8"))

        self.assertEqual(calls, [
            "reanalysis_recent_refresh",
            "settled_day_analysis_barrier",
            "fleet_observability",
        ])
        self.assertEqual(payload["config"]["stage"], "settlement")
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(manifest["target_date"], "2026-07-07")
        self.assertEqual(manifest["barrier"]["status"], "PASS")
        self.assertEqual(manifest["evidence_trigger"]["status"], "PENDING")
        self.assertEqual(manifest["invocation"]["status"], "PASS")
        self.assertTrue(manifest["invocation"]["scheduler_attested"])
        self.assertEqual(manifest["lock_proof"]["status"], "PASS")
        self.assertEqual(manifest["sla"]["status"], "PASS")
        self.assertEqual(manifest["release_identity"]["status"], "PASS")
        self.assertEqual(manifest["release_id"], "release-fixture")

    def test_evidence_stage_skips_when_stage_a_manifest_missing(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(Path(tmp) / "backtest" / "missing_stage_a.json"),
                settled_analysis_target_date="2026-07-07",
            )
            payload, status_path, _report_path = run_daily_refresh(
                args,
                runners=[("promotion_refresh", lambda _args: calls.append("promotion_refresh"))],
            )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))

        self.assertEqual(calls, [])
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(saved["skip_reason"], "missing_stage_a_manifest")

    def test_evidence_stage_carries_stage_a_steps_forward(self):
        calls = []
        seen = {}

        def promotion(_args):
            calls.append("promotion_refresh")
            return {"status": "OK"}

        def learning(args):
            calls.append("daily_learning")
            seen["steps"] = list(getattr(args, "_daily_refresh_steps_so_far", []))
            return {"status": "ACTIONABLE"}

        with tempfile.TemporaryDirectory() as tmp:
            stage_a_manifest = Path(tmp) / "backtest" / "stage_a.json"
            stage_a_manifest.parent.mkdir(parents=True)
            stage_a_manifest.write_text(
                json.dumps({
                    "schema_version": "daily_refresh_stage_manifest_v0.1",
                    "stage": "settlement",
                    "status": "COMPLETED",
                    "target_date": "2026-07-07",
                    "started_at_utc": "2026-07-08T09:30:00+00:00",
                    "barrier": {"status": "OK", "target_date": "2026-07-07"},
                    "steps": _stage_a_promotion_receipts("2026-07-07"),
                }),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(Path(tmp) / "backtest" / "stage_b.json"),
                settled_analysis_target_date="2026-07-07",
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("promotion_refresh", promotion),
                    ("daily_learning", learning),
                ],
            )

        self.assertEqual(calls, ["promotion_refresh", "daily_learning"])
        self.assertEqual(payload["config"]["stage"], "evidence")
        self.assertEqual(payload["config"]["carried_forward_from_stage"], "settlement")
        expected_carried = _stage_a_promotion_receipts("2026-07-07")
        self.assertTrue(
            all(
                step.get("carried_forward")
                for step in seen["steps"][: len(expected_carried)]
            )
        )
        self.assertEqual(
            [
                step["name"]
                for step in seen["steps"][: len(expected_carried)]
            ],
            [step["name"] for step in expected_carried],
        )

    def test_evidence_stage_runs_learning_only_when_stage_a_barrier_blocked(self):
        calls = []

        def promotion(_args):
            calls.append("promotion_refresh")
            return {"status": "SHOULD_NOT_RUN"}

        def learning(_args):
            calls.append("daily_learning")
            return {
                "status": "BLOCKED",
                "latest_settled_label_date": "2026-07-06",
            }

        with tempfile.TemporaryDirectory() as tmp:
            stage_a_manifest = Path(tmp) / "backtest" / "stage_a.json"
            stage_a_manifest.parent.mkdir(parents=True)
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "started_at_utc": "2026-07-08T09:30:00+00:00",
                        "barrier": {
                            "status": "BLOCK",
                            "step_status": "error",
                            "target_date": "2026-07-07",
                        },
                        "steps": _stage_a_promotion_receipts(
                            "2026-07-07",
                            overrides={
                                "settled_day_analysis_barrier": {
                                    "name": "settled_day_analysis_barrier",
                                    "status": "error",
                                    "root_cause_class": (
                                        "settled_day_analysis_barrier"
                                    ),
                                    "result": {
                                        "status": "BLOCK",
                                        "target_date": "2026-07-07",
                                        "hard_stop_pipeline": True,
                                    },
                                },
                                "live_variant_settlement_scorecard": {
                                    "name": (
                                        "live_variant_settlement_scorecard"
                                    ),
                                    "status": "blocked",
                                    "result": {"status": "BLOCK"},
                                },
                                "fleet_observability": {
                                    "name": "fleet_observability",
                                    "status": "ok",
                                    "result": {"status": "CRITICAL"},
                                },
                            },
                        ),
                    }
                ),
                encoding="utf-8",
            )
            stage_b_manifest = Path(tmp) / "backtest" / "stage_b.json"
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(stage_b_manifest),
                settled_analysis_target_date="2026-07-07",
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("promotion_refresh", promotion),
                    ("daily_learning", learning),
                ],
            )
            manifest = json.loads(stage_b_manifest.read_text(encoding="utf-8"))

        self.assertEqual(calls, ["daily_learning"])
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["config"]["stage_gate"]["status"], "RUN")
        self.assertEqual(payload["config"]["stage_gate"]["learning_mode"], "GAPPED")
        promotion_step = next(
            step for step in payload["steps"] if step["name"] == "promotion_refresh"
        )
        self.assertEqual(promotion_step["status"], "blocked")
        learning_step = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        coverage = learning_step["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(coverage["requested_target_date"], "2026-07-07")
        self.assertEqual(manifest["status"], "COMPLETED")
        self.assertEqual(manifest["lanes"][LANE_PROMOTION]["status"], "BLOCKED")

    def test_evidence_stage_missing_required_receipt_blocks_only_promotion(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backtest"
            root.mkdir(parents=True)
            stage_a_manifest = root / "stage_a.json"
            receipts = [
                row
                for row in _stage_a_promotion_receipts("2026-07-07")
                if row["name"] != "runtime_identity_reconciliation"
            ]
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "run_id": "stage-a-truncated",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "barrier": {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                        "steps": receipts,
                    }
                ),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(root / "stage_b.json"),
                settled_analysis_target_date="2026-07-07",
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    (
                        "promotion_refresh",
                        lambda _args: calls.append("promotion_refresh")
                        or {"status": "SHOULD_NOT_RUN"},
                    ),
                    (
                        "daily_learning",
                        lambda _args: calls.append("daily_learning")
                        or {"status": "ACTIONABLE"},
                    ),
                ],
            )

        self.assertEqual(calls, ["daily_learning"])
        blocker = payload["config"]["stage_gate"]["promotion_blocker"]
        self.assertEqual(blocker["step"], "runtime_identity_reconciliation")
        self.assertEqual(
            blocker["root_cause_class"],
            "promotion_receipt_missing",
        )
        promotion_step = next(
            step
            for step in payload["steps"]
            if step["name"] == "promotion_refresh"
        )
        self.assertEqual(promotion_step["status"], "blocked")

    def test_repaired_stage_a_binding_reruns_completed_stage_b_for_same_target(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backtest"
            root.mkdir(parents=True)
            stage_a_manifest = root / "stage_a.json"
            stage_b_manifest = root / "stage_b.json"
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "run_id": "stage-a-repaired",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "barrier": {"status": "PASS", "target_date": "2026-07-07"},
                        "steps": _stage_a_promotion_receipts("2026-07-07"),
                    }
                ),
                encoding="utf-8",
            )
            stage_b_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "stage": "evidence",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "source_stage_a_binding": "stage-a-before-repair",
                    }
                ),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(stage_b_manifest),
                settled_analysis_target_date="2026-07-07",
            )
            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    (
                        "promotion_refresh",
                        lambda _args: calls.append("promotion_refresh")
                        or {"status": "OK"},
                    ),
                    (
                        "daily_learning",
                        lambda _args: calls.append("daily_learning")
                        or {"status": "ACTIONABLE"},
                    ),
                ],
            )
            manifest = json.loads(stage_b_manifest.read_text(encoding="utf-8"))

        self.assertEqual(calls, ["promotion_refresh", "daily_learning"])
        self.assertEqual(payload["config"]["stage_gate"]["status"], "RUN")
        self.assertEqual(manifest["source_stage_a_binding"], "stage-a-repaired")

    def test_completed_stage_b_fallback_preserves_completed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backtest"
            root.mkdir(parents=True)
            stage_a_manifest = root / "stage_a.json"
            stage_b_manifest = root / "stage_b.json"
            status_path = root / "evidence_status.json"
            report_path = root / "evidence_report.md"
            completed_status = {
                "status": "ok",
                "config": {
                    "stage": "evidence",
                    "settled_analysis_target_date": "2026-07-07",
                    "stage_gate": {"stage_a_binding": "stage-a-current"},
                },
                "steps": [{"name": "daily_learning", "status": "ok"}],
            }
            status_path.write_text(
                json.dumps(completed_status), encoding="utf-8"
            )
            report_path.write_text(
                "# completed evidence report\n", encoding="utf-8"
            )
            status_before = status_path.read_bytes()
            report_before = report_path.read_bytes()
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "run_id": "stage-a-current",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "barrier": {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                        "steps": _stage_a_promotion_receipts("2026-07-07"),
                    }
                ),
                encoding="utf-8",
            )
            stage_b_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "stage": "evidence",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "source_stage_a_binding": "stage-a-current",
                        "status_out": str(status_path),
                        "report_out": str(report_path),
                    }
                ),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(stage_b_manifest),
                status_out=str(status_path),
                report_out=str(report_path),
                settled_analysis_target_date="2026-07-07",
            )
            payload, returned_status, returned_report = run_daily_refresh(
                args,
                runners=[
                    (
                        "daily_learning",
                        lambda _args: self.fail("completed Stage B reran"),
                    )
                ],
            )

            self.assertEqual(status_path.read_bytes(), status_before)
            self.assertEqual(report_path.read_bytes(), report_before)

        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["skip_reason"], "stage_b_already_completed")
        self.assertEqual(
            payload["preserved_completed_stage_b_artifacts"]["status"],
            "PRESERVED",
        )
        self.assertEqual(Path(returned_status), status_path)
        self.assertEqual(Path(returned_report), report_path)

    def test_evidence_learning_exception_leaves_stage_b_incomplete_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backtest"
            root.mkdir(parents=True)
            stage_a_manifest = root / "stage_a.json"
            stage_b_manifest = root / "stage_b.json"
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "run_id": "stage-a-current",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "barrier": {"status": "PASS", "target_date": "2026-07-07"},
                        "steps": _stage_a_promotion_receipts("2026-07-07"),
                    }
                ),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(stage_b_manifest),
                settled_analysis_target_date="2026-07-07",
            )

            def learning(_args):
                raise RuntimeError("learning write failed")

            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("promotion_refresh", lambda _args: {"status": "OK"}),
                    ("daily_learning", learning),
                ],
            )
            manifest = json.loads(stage_b_manifest.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(manifest["status"], "INCOMPLETE")
        self.assertEqual(manifest["execution_failure_steps"], ["daily_learning"])
        self.assertEqual(manifest["source_stage_a_binding"], "stage-a-current")

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
                json.dumps({
                    "status": "running",
                    "active": True,
                    "pid": -999,
                    "progress": {
                        "last_completed_step": "closed_day_parquet_incremental",
                        "last_completed_step_status": "ok",
                    },
                    "last_progress_at_utc": "2026-07-13T14:40:00+00:00",
                }),
                encoding="utf-8",
            )
            Path(args.status_out).write_text(
                json.dumps({
                    "schema_version": "daily_refresh_v0.5",
                    "status": "running",
                    "owner_pid": -999,
                }),
                encoding="utf-8",
            )
            args.lock_path = str(daily_lock)
            args.long_job_lock = str(long_lock)
            args.resume_from_step = "settlement_source_audit"

            payload = repair_stale_locks(args)
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            refresh_status = json.loads(Path(args.status_out).read_text(encoding="utf-8"))
            daily_exists = daily_lock.exists()
            long_exists = long_lock.exists()

        self.assertEqual(payload["removed_lock_count"], 1)
        self.assertFalse(daily_exists)
        self.assertTrue(long_exists)
        self.assertTrue(payload["long_job_lock"]["owner_running"])
        self.assertFalse(state_payload["active"])
        self.assertEqual(state_payload["status"], "stale_cleared")
        self.assertTrue(payload["daily_refresh_status"]["updated"])
        self.assertEqual(refresh_status["status"], "interrupted")
        self.assertTrue(refresh_status["terminal"])
        self.assertEqual(refresh_status["current_step"]["owner_pid"], -999)
        self.assertEqual(
            refresh_status["current_step"]["resume_selection"],
            "verified_last_completed_step",
        )
        self.assertIn(
            "--resume-from-step hourly_model_performance",
            refresh_status["current_step"]["resume_command"],
        )

    def test_repair_recovers_verified_child_terminal_before_advancing(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, stage="settlement")
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            daily_lock = Path(args.lock_path)
            long_lock = Path(args.long_job_lock)
            state = Path(args.long_job_state)
            daily_lock.write_text(json.dumps({"pid": -999}), encoding="utf-8")
            long_lock.write_text(json.dumps({"pid": -999}), encoding="utf-8")
            state.write_text(
                json.dumps({
                    "status": "running",
                    "active": True,
                    "pid": -999,
                    "progress": {
                        "last_completed_step": "taker_tail_casebook",
                        "last_completed_step_status": "ok",
                    },
                }),
                encoding="utf-8",
            )
            result_path = (
                backtest
                / "daily_refresh_step_children"
                / "run-1"
                / "maker_paper_score.result.json"
            )
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                json.dumps({
                    "schema_version": "daily_refresh_step_child_v0.2",
                    "status": "ok",
                    "step": "maker_paper_score",
                    "pid": 4321,
                    "started_at_utc": "2026-07-13T14:00:00+00:00",
                    "finished_at_utc": "2026-07-13T14:01:00+00:00",
                    "result": {"status": "PASS", "selected_run_count": 14},
                }),
                encoding="utf-8",
            )
            Path(args.status_out).write_text(
                json.dumps({
                    "schema_version": "daily_refresh_v0.5",
                    "status": "interrupted",
                    "terminal": True,
                    "owner_pid": -999,
                    "config": {
                        "backtest_root": str(backtest),
                        "settled_analysis_target_date": "2026-07-12",
                    },
                    "steps": [],
                    "current_step": {
                        "name": "maker_paper_score",
                        "child_pid": 4321,
                    },
                    "resource_steps": [{
                        "step": "maker_paper_score",
                        "status": "running",
                        "child_pid": 4321,
                        "child_invocation": {"result_json": str(result_path)},
                    }],
                }),
                encoding="utf-8",
            )

            repair = repair_stale_locks(args)
            saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))

        self.assertTrue(repair["daily_refresh_status"]["updated"])
        self.assertTrue(
            repair["daily_refresh_status"]["recovered_child_terminal"]["recovered"]
        )
        self.assertEqual(saved["steps"][-1]["name"], "maker_paper_score")
        self.assertEqual(saved["steps"][-1]["status"], "ok")
        self.assertTrue(saved["steps"][-1]["recovered_from_child_terminal"])
        self.assertEqual(saved["current_step"]["name"], "settlement_source_audit")
        self.assertIn(
            "--settled-analysis-target-date 2026-07-12",
            saved["current_step"]["resume_command"],
        )

    def test_repair_does_not_rewrite_status_while_daily_owner_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, stage="settlement")
            backtest = Path(args.backtest_root)
            backtest.mkdir(parents=True)
            Path(args.lock_path).write_text(
                json.dumps({"pid": os.getpid()}),
                encoding="utf-8",
            )
            Path(args.long_job_state).write_text(
                json.dumps({"status": "running", "active": True, "pid": -999}),
                encoding="utf-8",
            )
            Path(args.status_out).write_text(
                json.dumps({
                    "schema_version": "daily_refresh_v0.5",
                    "status": "running",
                    "owner_pid": -999,
                }),
                encoding="utf-8",
            )

            repair = repair_stale_locks(args)
            saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))

        self.assertFalse(repair["daily_refresh_status"]["updated"])
        self.assertEqual(
            repair["daily_refresh_status"]["reason"],
            "daily_refresh_lock_owner_running",
        )
        self.assertEqual(saved["status"], "running")

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
                runners=[("unregistered_failure", bad)],
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

    def test_settled_day_barrier_blocks_promotion_but_learning_continues(self):
        calls = []

        def barrier(_args):
            calls.append("barrier")
            raise SettledDayAnalysisBarrierError(
                "settled-day barrier blocked",
                {
                    "status": "BLOCK",
                    "target_date": "2026-06-23",
                    "hard_stop_pipeline": True,
                    "resume_command": "python -m weather.operations.daily_refresh run --resume-from-step settled_day_analysis_barrier",
                },
            )

        def promotion(_args):
            calls.append("promotion")
            return {"status": "SHOULD_NOT_RUN"}

        def learning(_args):
            calls.append("learning")
            return {
                "status": "BLOCKED",
                "latest_settled_label_date": "2026-06-22",
                "last_scored_target_date": "2026-06-22",
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_daily_refresh(
                _args(
                    tmp,
                    continue_on_error=True,
                    settled_analysis_target_date="2026-06-23",
                ),
                runners=[
                    ("settled_day_analysis_barrier", barrier),
                    ("promotion_refresh", promotion),
                    ("daily_learning", learning),
                ],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(calls, ["barrier", "learning"])
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["steps"][0]["root_cause_class"], "settled_day_analysis_barrier")
        promotion_step = next(
            step for step in payload["steps"] if step["name"] == "promotion_refresh"
        )
        self.assertEqual(promotion_step["status"], "blocked")
        self.assertTrue(promotion_step["result"]["promotion_not_run"])
        learning_step = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        coverage = learning_step["result"]["target_settlement_coverage"]
        self.assertEqual(learning_step["lane"], LANE_LEARNING)
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(coverage["requested_target_date"], "2026-06-23")
        self.assertEqual(coverage["latest_settled_date"], "2026-06-22")
        self.assertEqual(
            coverage["blocker_step"], "settled_day_analysis_barrier"
        )
        self.assertEqual(coverage["settlement_barrier_status"], "BLOCK")
        self.assertEqual(payload["lanes"][LANE_PROMOTION]["status"], "BLOCKED")
        lane_coverage = payload["lanes"][LANE_LEARNING][
            "target_settlement_coverage"
        ]
        self.assertEqual(lane_coverage["latest_settled_date"], "2026-06-22")
        self.assertEqual(lane_coverage["corpus_date_max"], "2026-06-22")
        self.assertEqual(lane_coverage["staleness_days"], 1)
        self.assertEqual(
            lane_coverage["blocker_step"], "settled_day_analysis_barrier"
        )
        self.assertIn("## Execution Lanes", report)
        self.assertIn("Promotion lane: **BLOCKED**", report)
        self.assertIn("Target coverage: `GAPPED`", report)
        self.assertIn(
            "latest settled: `2026-06-22`; corpus max: `2026-06-22`",
            report,
        )
        self.assertIn(
            "upstream settled_day_analysis_barrier", report
        )
        self.assertIn("settled-day barrier blocked", report)

    def test_learning_lane_error_does_not_stop_later_learning_steps(self):
        calls = []

        def bad(_args):
            calls.append("bad")
            raise RuntimeError("learning failed")

        def after(_args):
            calls.append("after")
            return {"status": "BLOCKED"}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp),
                runners=[
                    ("daily_learning", bad),
                    ("market_beating_objective_scoreboard", after),
                ],
            )

        self.assertEqual(calls, ["bad", "after"])
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(
            [step["status"] for step in payload["steps"]],
            ["error", "ok"],
        )
        self.assertTrue(payload["steps"][0]["contained_by_lane"])
        self.assertEqual(payload["lanes"][LANE_LEARNING]["status"], "PARTIAL")

    def test_statusless_learning_skip_marks_lane_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp),
                runners=[
                    (
                        "reanalysis_recent_refresh",
                        lambda _args: {
                            "skipped": True,
                            "reason": "explicit_test_skip",
                        },
                    ),
                ],
            )

        step = payload["steps"][0]
        self.assertEqual(
            step["result"]["target_settlement_coverage"][
                "coverage_status"
            ],
            "NOT_APPLICABLE",
        )
        self.assertEqual(payload["lanes"][LANE_LEARNING]["status"], "PARTIAL")
        self.assertEqual(
            payload["lanes"][LANE_LEARNING]["incomplete_steps"],
            ["reanalysis_recent_refresh"],
        )

    def test_policy_receipts_reach_canonical_promotion_adapter(self):
        calls = []

        def run(name, result):
            def _runner(_args):
                calls.append(name)
                return result

            return _runner

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "trading_evidence",
                        run("trading_evidence", {"status": "BLOCK"}),
                    ),
                    (
                        "hourly_model_performance",
                        run(
                            "hourly_model_performance",
                            {
                                "status": "BLOCK",
                                "last_scored_target_date": "2026-07-07",
                            },
                        ),
                    ),
                    (
                        "ten_minute_model_performance",
                        run(
                            "ten_minute_model_performance",
                            {
                                "status": "BLOCK",
                                "last_scored_target_date": "2026-07-07",
                            },
                        ),
                    ),
                    (
                        "settled_day_analysis_barrier",
                        run(
                            "settled_day_analysis_barrier",
                            {"status": "PASS", "target_date": "2026-07-07"},
                        ),
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        run(
                            "live_variant_settlement_scorecard",
                            {
                                "status": "PASS",
                                "target_date": "2026-07-07",
                                "source_row_count": 1,
                                "valid_prediction_partition_count": 1,
                            },
                        ),
                    ),
                    (
                        "promotion_refresh",
                        run("promotion_refresh", {"status": "OK"}),
                    ),
                    (
                        "daily_learning",
                        run(
                            "daily_learning",
                            {
                                "status": "ACTIONABLE",
                                "latest_settled_label_date": "2026-07-07",
                                "last_scored_target_date": "2026-07-07",
                            },
                        ),
                    ),
                ],
            )

        self.assertEqual(
            calls,
            [
                "trading_evidence",
                "hourly_model_performance",
                "ten_minute_model_performance",
                "settled_day_analysis_barrier",
                "live_variant_settlement_scorecard",
                "promotion_refresh",
                "daily_learning",
            ],
        )
        barrier_step = next(
            step
            for step in payload["steps"]
            if step["name"] == "settled_day_analysis_barrier"
        )
        self.assertEqual(barrier_step["result"]["status"], "PASS")
        promotion_step = next(
            step for step in payload["steps"] if step["name"] == "promotion_refresh"
        )
        self.assertEqual(promotion_step["status"], "ok")
        self.assertFalse(STEP_PROMOTION_GATES["trading_evidence"])
        learning_step = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        self.assertEqual(
            learning_step["result"]["target_settlement_coverage"]["coverage_status"],
            "COMPLETE",
        )

    def test_shared_learning_producer_error_blocks_only_promotion_action(self):
        calls = []

        def barrier(_args):
            calls.append("barrier")
            return {"status": "PASS", "target_date": "2026-07-07"}

        def runtime(_args):
            calls.append("runtime")
            raise RuntimeError("runtime reconciliation failed")

        def live(_args):
            calls.append("live")
            return {"status": "PASS"}

        def fleet(_args):
            calls.append("fleet")
            return {"status": "PASS"}

        def promotion(_args):
            calls.append("promotion")
            return {"status": "SHOULD_NOT_RUN"}

        def learning(_args):
            calls.append("learning")
            return {"status": "ACTIONABLE"}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    ("settled_day_analysis_barrier", barrier),
                    ("runtime_identity_reconciliation", runtime),
                    ("live_variant_settlement_scorecard", live),
                    ("fleet_observability", fleet),
                    ("promotion_refresh", promotion),
                    ("daily_learning", learning),
                ],
            )

        self.assertEqual(calls, ["barrier", "runtime", "live", "fleet", "learning"])
        promotion_step = next(
            step for step in payload["steps"] if step["name"] == "promotion_refresh"
        )
        self.assertEqual(promotion_step["status"], "blocked")
        self.assertEqual(
            promotion_step["result"]["upstream_blocker"]["step"],
            "runtime_identity_reconciliation",
        )
        self.assertEqual(payload["status"], "critical")

    def test_explicitly_skipped_required_gate_blocks_only_promotion(self):
        calls = []

        def called(name, result):
            def _runner(_args):
                calls.append(name)
                return result

            return _runner

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "ingest_quality_gate",
                        called("ingest", {"skipped": True}),
                    ),
                    (
                        "settled_day_analysis_barrier",
                        called(
                            "barrier",
                            {"status": "PASS", "target_date": "2026-07-07"},
                        ),
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        called(
                            "live",
                            {"status": "PASS", "target_date": "2026-07-07"},
                        ),
                    ),
                    (
                        "promotion_refresh",
                        called("promotion", {"status": "SHOULD_NOT_RUN"}),
                    ),
                    (
                        "daily_learning",
                        called("learning", {"status": "ACTIONABLE"}),
                    ),
                ],
            )

        self.assertEqual(calls, ["ingest", "barrier", "live", "learning"])
        promotion = next(
            row for row in payload["steps"] if row["name"] == "promotion_refresh"
        )
        blocker = promotion["result"]["upstream_blocker"]
        self.assertEqual(blocker["step"], "ingest_quality_gate")
        self.assertEqual(blocker["result_status"], "SKIPPED")

    def test_learning_without_own_dates_never_inherits_barrier_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                            "source_row_count": 1,
                            "valid_prediction_partition_count": 1,
                        },
                    ),
                    (
                        "daily_learning",
                        lambda _args: {"status": "ACTIONABLE"},
                    ),
                ],
            )

        learning = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        coverage = learning["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "UNKNOWN")
        self.assertIsNone(coverage["target_included"])
        self.assertEqual(
            coverage["gap_reason"],
            "step_has_no_target_dated_corpus",
        )
        self.assertEqual(payload["lanes"][LANE_LEARNING]["status"], "UNKNOWN")

    def test_no_data_result_cannot_be_complete_from_matching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                            "source_row_count": 1,
                            "valid_prediction_partition_count": 1,
                        },
                    ),
                    (
                        "settled_day_root_cause",
                        lambda _args: {
                            "status": "NO_DATA",
                            "target_date": "2026-07-07",
                        },
                    ),
                ],
            )

        root_cause = next(
            step
            for step in payload["steps"]
            if step["name"] == "settled_day_root_cause"
        )
        coverage = root_cause["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(coverage["gap_reason"], "learning_step_result_no_data")

    def test_scoring_staleness_uses_last_scored_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "hourly_model_performance",
                        lambda _args: {
                            "status": "PASS",
                            "latest_settled_label_date": "2026-07-07",
                            "last_scored_target_date": "2026-07-06",
                        },
                    ),
                ],
            )

        hourly = next(
            step
            for step in payload["steps"]
            if step["name"] == "hourly_model_performance"
        )
        coverage = hourly["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(coverage["latest_settled_date"], "2026-07-07")
        self.assertEqual(coverage["corpus_date_max"], "2026-07-06")
        self.assertEqual(coverage["staleness_days"], 1)

    def test_requested_target_without_rows_is_not_corpus_proof(self):
        for step_name, count_field in (
            ("runtime_identity_reconciliation", "snapshot_row_count"),
            ("model_market_disagreement_rehydration", "target_row_count"),
        ):
            with self.subTest(step=step_name), tempfile.TemporaryDirectory() as tmp:
                payload, _status_path, _report_path = run_daily_refresh(
                    _args(tmp, settled_analysis_target_date="2026-07-07"),
                    runners=[
                        (
                            "settled_day_analysis_barrier",
                            lambda _args: {
                                "status": "PASS",
                                "target_date": "2026-07-07",
                            },
                        ),
                        (
                            step_name,
                            lambda _args, field=count_field: {
                                "status": "PASS",
                                "target_date": "2026-07-07",
                                field: 0,
                            },
                        ),
                    ],
                )

                step = next(
                    row for row in payload["steps"] if row["name"] == step_name
                )
                coverage = step["result"]["target_settlement_coverage"]
                self.assertEqual(coverage["coverage_status"], "UNKNOWN")
                self.assertIsNone(coverage["target_included"])

    def test_latest_label_without_scored_target_is_a_coverage_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "hourly_model_performance",
                        lambda _args: {
                            "status": "BLOCK",
                            "scoring_liveness_status": "BLOCK",
                            "latest_settled_label_date": "2026-07-07",
                            "last_scored_target_date": None,
                        },
                    ),
                ],
            )

        hourly = next(
            row
            for row in payload["steps"]
            if row["name"] == "hourly_model_performance"
        )
        coverage = hourly["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(
            coverage["gap_reason"],
            "learning_input_gate_block",
        )

    def test_barrier_target_mismatch_blocks_target_consumers(self):
        calls = []

        def called(name, result):
            def _runner(_args):
                calls.append(name)
                return result

            return _runner

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        called(
                            "barrier",
                            {"status": "PASS", "target_date": "2026-07-06"},
                        ),
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        called("live", {"status": "SHOULD_NOT_RUN"}),
                    ),
                    (
                        "promotion_refresh",
                        called("promotion", {"status": "SHOULD_NOT_RUN"}),
                    ),
                    (
                        "daily_learning",
                        called(
                            "learning",
                            {
                                "status": "ACTIONABLE",
                                "last_scored_target_date": "2026-07-06",
                            },
                        ),
                    ),
                ],
            )

        self.assertEqual(calls, ["barrier", "learning"])
        live = next(
            step
            for step in payload["steps"]
            if step["name"] == "live_variant_settlement_scorecard"
        )
        self.assertEqual(live["status"], "blocked")
        self.assertEqual(
            live["result"]["upstream_blocker"]["root_cause_class"],
            "settlement_barrier_target_mismatch",
        )
        coverage = payload["lanes"][LANE_LEARNING][
            "target_settlement_coverage"
        ]
        self.assertEqual(coverage["coverage_status"], "GAPPED")

    def test_dependency_coverage_propagates_weakest_current_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                            "source_row_count": 1,
                            "valid_prediction_partition_count": 1,
                        },
                    ),
                    (
                        "promotion_refresh",
                        lambda _args: {
                            "status": "OK",
                            "corpus_date_max": "2026-07-06",
                        },
                    ),
                    ("shadow_ab_monitor", lambda _args: {"status": "PASS"}),
                ],
            )

        shadow = next(
            row for row in payload["steps"] if row["name"] == "shadow_ab_monitor"
        )
        coverage = shadow["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_mode"], "dependencies")
        self.assertEqual(coverage["coverage_status"], "GAPPED")
        self.assertEqual(coverage["corpus_date_max"], "2026-07-06")
        self.assertEqual(coverage["staleness_days"], 1)
        self.assertEqual(coverage["blocker_step"], "promotion_refresh")

    def test_blocked_daily_learning_result_marks_learning_lane_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    ("daily_learning", lambda _args: {"status": "BLOCKED"}),
                ],
            )

        self.assertEqual(payload["lanes"][LANE_LEARNING]["status"], "PARTIAL")
        self.assertIn(
            "daily_learning",
            payload["lanes"][LANE_LEARNING]["incomplete_steps"],
        )

    def test_policy_block_does_not_falsify_complete_target_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp, settled_analysis_target_date="2026-07-07"),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "daily_learning",
                        lambda _args: {
                            "status": "BLOCKED",
                            "latest_settled_label_date": "2026-07-07",
                            "last_scored_target_date": "2026-07-07",
                            "input_consistency": {
                                "status": "FAIL",
                                "checks": [
                                    {
                                        "name": "non_settlement_policy",
                                        "status": "FAIL",
                                        "evidence": {},
                                    }
                                ],
                            },
                        },
                    ),
                ],
            )

        learning = next(
            step for step in payload["steps"] if step["name"] == "daily_learning"
        )
        coverage = learning["result"]["target_settlement_coverage"]
        self.assertEqual(coverage["coverage_status"], "COMPLETE")
        self.assertTrue(coverage["target_included"])
        self.assertEqual(payload["lanes"][LANE_LEARNING]["status"], "PARTIAL")

    def test_blocked_promotion_skips_production_readiness(self):
        def barrier(_args):
            raise SettledDayAnalysisBarrierError(
                "settlement unavailable",
                {
                    "status": "BLOCK",
                    "target_date": "2026-07-07",
                    "hard_stop_pipeline": True,
                },
            )

        with tempfile.TemporaryDirectory() as tmp, patch(
            "weather.operations.daily_refresh._production_readiness_status"
        ) as readiness:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(
                    tmp,
                    settled_analysis_target_date="2026-07-07",
                    skip_production_readiness_gate=False,
                ),
                runners=[
                    ("settled_day_analysis_barrier", barrier),
                    ("daily_learning", lambda _args: {"status": "BLOCKED"}),
                ],
            )

        readiness.assert_not_called()
        self.assertEqual(payload["production_readiness"]["status"], "SKIPPED")

    def test_carried_forward_steps_trims_to_pre_resume_and_marks(self):
        prior = [
            {"name": "public_wu_settlement_restore", "status": "ok", "result": {"status": "PASS"}},
            {"name": "hourly_model_performance", "status": "ok", "result": {"status": "BLOCK"}},
            {"name": "settled_day_analysis_barrier", "status": "error", "result": {"status": "BLOCK"}},
            {"name": "promotion_refresh", "status": "ok", "result": {}},
            {"name": "not_a_registered_step", "status": "ok", "result": {}},
        ]
        carried = carried_forward_steps(prior, "settled_day_analysis_barrier")
        self.assertEqual(
            [step["name"] for step in carried],
            ["public_wu_settlement_restore", "hourly_model_performance"],
        )
        self.assertTrue(all(step["carried_forward"] for step in carried))
        self.assertEqual(carried_forward_steps(prior, ""), [])

    def test_resume_seeds_prior_steps_for_barrier_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                resume_from_step="settled_day_analysis_barrier",
                settled_analysis_target_date="2026-07-07",
            )
            prior = {
                "started_at_utc": "2026-07-02T13:30:00+00:00",
                "config": {"settled_analysis_target_date": "2026-07-07"},
                "steps": [
                    {"name": "market_day_labels_finalize", "status": "ok", "result": {"label_count": 3}},
                    {"name": "hourly_model_performance", "status": "ok", "result": {"status": "BLOCK"}},
                ],
                "resource_steps": [{
                    "step": "hourly_model_performance",
                    "status": "ok",
                    "subprocess": {"duration_seconds": 5.0},
                }],
            }
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(prior), encoding="utf-8")

            seen = {}

            def capture(step_args):
                seen["steps"] = list(getattr(step_args, "_daily_refresh_steps_so_far", []))
                seen["resource_steps"] = list(
                    getattr(step_args, "_daily_refresh_resource_steps", [])
                )
                return {"status": "PASS"}

            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[("settled_day_analysis_barrier", capture)],
            )
            guard_state = json.loads(Path(args.long_job_state).read_text(encoding="utf-8"))

        self.assertEqual(
            [step["name"] for step in seen["steps"]],
            ["market_day_labels_finalize", "hourly_model_performance"],
        )
        self.assertTrue(all(step.get("carried_forward") for step in seen["steps"]))
        self.assertEqual(
            [step["name"] for step in payload["steps"]],
            ["market_day_labels_finalize", "hourly_model_performance", "settled_day_analysis_barrier"],
        )
        self.assertEqual(payload["config"]["carried_forward_step_count"], 2)
        self.assertEqual(payload["config"]["carried_forward_resource_step_count"], 1)
        self.assertEqual(seen["resource_steps"][0]["step"], "hourly_model_performance")
        self.assertEqual(
            payload["config"]["carried_forward_from_run_started_at_utc"],
            "2026-07-02T13:30:00+00:00",
        )
        self.assertEqual(guard_state["progress"]["completed_step_count"], 3)
        self.assertEqual(guard_state["progress"]["total_step_count"], 3)

    def test_resume_progress_includes_final_production_readiness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                resume_from_step="settled_day_analysis_barrier",
                skip_production_readiness_gate=False,
                settled_analysis_target_date="2026-07-07",
            )
            prior = {
                "started_at_utc": "2026-07-02T13:30:00+00:00",
                "config": {"settled_analysis_target_date": "2026-07-07"},
                "steps": [
                    {"name": "market_day_labels_finalize", "status": "ok", "result": {}},
                    {
                        "name": "hourly_model_performance",
                        "status": "ok",
                        "result": {
                            "status": "PASS",
                            "last_scored_target_date": "2026-07-07",
                        },
                    },
                ],
            }
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(prior), encoding="utf-8")

            with patch(
                "weather.operations.daily_refresh._production_readiness_status",
                return_value={"status": "PASS"},
            ):
                payload, _status_path, _report_path = run_daily_refresh(
                    args,
                    runners=[
                        (
                            "settled_day_analysis_barrier",
                            lambda _args: {
                                "status": "PASS",
                                "target_date": "2026-07-07",
                            },
                        )
                    ],
                )
            guard_state = json.loads(Path(args.long_job_state).read_text(encoding="utf-8"))

        self.assertEqual(payload["steps"][-1]["name"], "production_readiness_gate")
        self.assertEqual(guard_state["progress"]["last_completed_step"], "production_readiness_gate")
        self.assertEqual(guard_state["progress"]["completed_step_count"], 4)
        self.assertEqual(guard_state["progress"]["total_step_count"], 4)

    def test_resume_rejects_carried_receipts_from_different_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                resume_from_step="settled_day_analysis_barrier",
                settled_analysis_target_date="2026-07-07",
            )
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(
                    {
                        "started_at_utc": "2026-07-07T13:30:00+00:00",
                        "config": {
                            "settled_analysis_target_date": "2026-07-06"
                        },
                        "steps": [
                            {
                                "name": "hourly_model_performance",
                                "status": "ok",
                                "result": {"status": "PASS"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            seen = {}

            def barrier(step_args):
                seen["steps"] = list(
                    getattr(step_args, "_daily_refresh_steps_so_far", [])
                )
                return {"status": "PASS", "target_date": "2026-07-07"}

            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[("settled_day_analysis_barrier", barrier)],
            )

        self.assertEqual(seen["steps"], [])
        binding = payload["config"]["carried_forward_target_binding"]
        self.assertEqual(binding["status"], "BLOCK")
        self.assertEqual(binding["prior_target_date"], "2026-07-06")
        self.assertEqual(payload["config"]["carried_forward_step_count"], 0)

    def test_evidence_resume_rejects_receipts_from_repaired_stage_a(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "backtest"
            root.mkdir(parents=True)
            stage_a_manifest = root / "stage_a.json"
            stage_b_manifest = root / "stage_b.json"
            stage_a_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "daily_refresh_stage_manifest_v0.1",
                        "run_id": "stage-a-repaired",
                        "stage": "settlement",
                        "status": "COMPLETED",
                        "target_date": "2026-07-07",
                        "barrier": {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                        "steps": _stage_a_promotion_receipts("2026-07-07"),
                    }
                ),
                encoding="utf-8",
            )
            args = _args(
                tmp,
                stage="evidence",
                stage_a_manifest=str(stage_a_manifest),
                stage_b_manifest=str(stage_b_manifest),
                resume_from_step="daily_learning",
                settled_analysis_target_date="2026-07-07",
            )
            status_path = Path(args.status_out)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(
                    {
                        "started_at_utc": "2026-07-07T13:30:00+00:00",
                        "config": {
                            "settled_analysis_target_date": "2026-07-07",
                            "stage_gate": {
                                "stage_a_binding": "stage-a-before-repair"
                            },
                        },
                        "steps": [
                            {
                                "name": "promotion_refresh",
                                "status": "ok",
                                "result": {
                                    "status": "OK",
                                    "source": "stale_prior_stage_b",
                                },
                            }
                        ],
                        "resource_steps": [
                            {"step": "promotion_refresh", "status": "ok"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            seen = {}

            def promotion(_step_args):
                seen["promotion_called"] = True
                return {"status": "OK", "source": "repaired_stage_a"}

            def learning(step_args):
                seen["steps"] = list(
                    getattr(step_args, "_daily_refresh_steps_so_far", [])
                )
                seen["resources"] = list(
                    getattr(step_args, "_daily_refresh_resource_steps", [])
                )
                return {"status": "ACTIONABLE"}

            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[
                    ("promotion_refresh", promotion),
                    ("daily_learning", learning),
                ],
            )
            manifest = json.loads(
                stage_b_manifest.read_text(encoding="utf-8")
            )

        self.assertTrue(seen["promotion_called"])
        promotions = [
            step
            for step in seen["steps"]
            if step.get("name") == "promotion_refresh"
        ]
        self.assertEqual(len(promotions), 1)
        self.assertEqual(
            promotions[0]["result"]["source"], "repaired_stage_a"
        )
        self.assertTrue(
            all(
                step.get("carried_forward_source_stage") == "settlement"
                for step in seen["steps"]
                if step.get("name") != "promotion_refresh"
            )
        )
        self.assertEqual(seen["resources"], [])
        carry = payload["config"]["carried_forward_target_binding"]
        self.assertEqual(carry["status"], "BLOCK")
        self.assertEqual(carry["reason"], "resume_stage_a_binding_mismatch")
        self.assertEqual(
            carry["current_stage_a_binding"], "stage-a-repaired"
        )
        self.assertEqual(
            carry["prior_stage_a_binding"], "stage-a-before-repair"
        )
        self.assertTrue(
            payload["config"]["resume_restarted_from_stage_start"]
        )
        self.assertEqual(manifest["source_stage_a_binding"], "stage-a-repaired")

    def test_run_pins_settled_target_once_at_chain_start(self):
        # Regression (2026-07-07): steps derived the settled target from the
        # wall clock at their own execution time, so a chain crossing midnight
        # analyzed two different "yesterdays" (root-cause targeted 07-06 at
        # 01:00 while pre-midnight steps targeted 07-05), failing the settled
        # target-agreement invariant and blocking the experiment queue. The
        # runner must resolve the target once and pin it for every step.
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, as_of="2026-07-06T15:00:00+00:00")
            seen = {}

            def capture(step_args):
                seen["pinned"] = getattr(step_args, "settled_analysis_target_date", "")
                return {"status": "PASS"}

            payload, _status_path, _report_path = run_daily_refresh(
                args,
                runners=[("ingest_quality_gate", capture)],
            )

        self.assertEqual(seen["pinned"], "2026-07-05")
        self.assertEqual(payload["config"]["settled_analysis_target_date"], "2026-07-05")

    def test_settled_day_barrier_blocks_pre_finalization_target_date(self):
        target_date = "2026-06-17"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            slug = event_slug_for_date(target_date, "nyc")
            folder = snapshots / slug
            folder.mkdir(parents=True)
            (folder / "snapshots_long.csv").write_text(
                "event_slug,snapshot_id,captured_at_local,range_label,bin_kind,bin_value_c,model_probability,market_yes\n"
                f"{slug},s1,{target_date}T12:00:00-04:00,77 F,eq,77,0.5,0.5\n",
                encoding="utf-8",
            )
            args = _args(
                tmp,
                snapshots_root=str(snapshots),
                settled_analysis_target_date=target_date,
                markets="nyc",
            )
            args._daily_refresh_steps_so_far = [
                {
                    "name": "public_wu_settlement_restore",
                    "status": "ok",
                    "result": {"status": "PASS", "target_date": target_date},
                },
                {"name": "market_day_labels_finalize", "status": "ok", "result": {"label_count": 0}},
                {"name": "taker_finalization_watchdog", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "taker_edge_permission_map", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "taker_tail_casebook", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "maker_paper_score", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "settlement_source_audit", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "observed_floor_safety_monitor", "status": "ok", "result": {"status": "PASS", "target_date": target_date}},
                {"name": "trading_evidence", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "replay_status_backfill", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "hourly_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "ten_minute_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "price_free_model_learning", "status": "ok", "result": {"status": "SKIPPED"}},
            ]

            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)
            payload = raised.exception.payload
            freshness = json.loads((root / "backtest" / "settled_day_freshness.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "BLOCK")
        self.assertTrue(payload["hard_stop_pipeline"])
        self.assertEqual(payload["target_date"], target_date)
        self.assertEqual(freshness["status"], "FAIL")
        self.assertEqual(freshness["summary"]["needs_finalization_count"], 1)
        self.assertIn("settled_day_freshness", {row["component"] for row in payload["blockers"]})

    def test_settled_day_barrier_counts_material_partial_labels_for_promotion(self):
        target_date = "2026-06-17"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            slug = event_slug_for_date(target_date, "nyc")
            folder = snapshots / slug
            folder.mkdir(parents=True)
            (folder / "snapshots_long.csv").write_text(
                "event_slug,snapshot_id,captured_at_local,range_label,bin_kind,bin_value_c,model_probability,market_yes\n"
                f"{slug},s1,{target_date}T12:00:00-04:00,77 F,eq,77,0.5,0.5\n",
                encoding="utf-8",
            )
            (folder / "replay_inputs.jsonl").write_text('{"snapshot_id": "s1"}\n', encoding="utf-8")
            (folder / "source_status_long.csv").write_text(
                "snapshot_id,source,ok,status\ns1,wu_history,True,fresh\n",
                encoding="utf-8",
            )
            (folder / "replay_input_status_long.csv").write_text(
                "snapshot_id,replay_input_status,replay_input_source\ns1,captured,replay_inputs.jsonl\n",
                encoding="utf-8",
            )
            label = {
                "event_slug": slug,
                "market_id": "nyc",
                "target_date": target_date,
                "settlement_bucket": "77",
                "winning_band": "77 F",
                "settlement_source": "daily_summary",
                "quality_grade": "partial",
                "coverage_reason": "1 gap(s), max 20 min",
                "material_coverage_grade": "minor_gap_material",
                "material_coverage_reason": "1 non-material gap(s), max 20 min",
                "material_coverage_gap_windows": "peak_heating_window:20m",
                "promotion_countable": "True",
                "promotion_countable_reason": "settlement reconciled and material coverage countable",
                "reconciliation_status": "match",
            }
            labels = root / "backtest" / "market_day_labels.csv"
            labels.parent.mkdir(parents=True)
            with labels.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(label))
                writer.writeheader()
                writer.writerow(label)
            ledger = root / "settlements" / "nyc" / "ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps(label) + "\n", encoding="utf-8")
            (folder / "settlement.json").write_text(json.dumps(label), encoding="utf-8")
            args = _args(
                tmp,
                snapshots_root=str(snapshots),
                labels_csv=str(labels),
                ledger_root=str(root / "settlements"),
                settled_analysis_target_date=target_date,
                markets="nyc",
            )
            args._daily_refresh_steps_so_far = [
                {
                    "name": "public_wu_settlement_restore",
                    "status": "ok",
                    "result": {"status": "PASS", "target_date": target_date},
                },
                {
                    "name": "market_day_labels_finalize",
                    "status": "ok",
                    "result": {
                        "label_count": 1,
                        "quality_counts": {"partial": 1},
                        "material_coverage_counts": {"minor_gap_material": 1},
                        "promotion_countability_available": True,
                        "promotion_countable_label_count": 1,
                        "promotion_blocked_label_count": 0,
                    },
                },
                {"name": "exchange_economics_rule_drift", "status": "ok", "result": {"status": "PASS"}},
                {"name": "taker_finalization_watchdog", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "taker_edge_permission_map", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "taker_tail_casebook", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "maker_paper_score", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "settlement_source_audit", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "observed_floor_safety_monitor", "status": "ok", "result": {"status": "PASS", "target_date": target_date}},
                {"name": "trading_evidence", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "replay_status_backfill", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "hourly_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "ten_minute_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "price_free_model_learning", "status": "ok", "result": {"status": "SKIPPED"}},
                {"name": "model_market_disagreement_rehydration", "status": "ok", "result": {"status": "SKIPPED"}},
            ]

            payload = run_settled_day_analysis_barrier_step(args)

        countability = payload["label_countability"]
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(countability["promotion_countable"])
        self.assertEqual(countability["strict_partial_label_count"], 1)
        self.assertEqual(countability["material_promotion_countable_label_count"], 1)
        self.assertIn("passed material coverage", countability["reason"])

    def _barrier_fixture_args(self, tmp, target_date):
        root = Path(tmp)
        snapshots = root / "snapshots"
        slug = event_slug_for_date(target_date, "nyc")
        folder = snapshots / slug
        folder.mkdir(parents=True)
        (folder / "snapshots_long.csv").write_text(
            "event_slug,snapshot_id,captured_at_local,range_label,bin_kind,bin_value_c,model_probability,market_yes\n"
            f"{slug},s1,{target_date}T12:00:00-04:00,77 F,eq,77,0.5,0.5\n",
            encoding="utf-8",
        )
        (folder / "replay_inputs.jsonl").write_text('{"snapshot_id": "s1"}\n', encoding="utf-8")
        (folder / "source_status_long.csv").write_text(
            "snapshot_id,source,ok,status\ns1,wu_history,True,fresh\n",
            encoding="utf-8",
        )
        (folder / "replay_input_status_long.csv").write_text(
            "snapshot_id,replay_input_status,replay_input_source\ns1,captured,replay_inputs.jsonl\n",
            encoding="utf-8",
        )
        label = {
            "event_slug": slug,
            "market_id": "nyc",
            "target_date": target_date,
            "settlement_bucket": "77",
            "winning_band": "77 F",
            "settlement_source": "daily_summary",
            "quality_grade": "complete",
            "material_coverage_grade": "materially_complete",
            "material_coverage_reason": "no gaps",
            "promotion_countable": "True",
            "promotion_countable_reason": "settlement reconciled and material coverage countable",
            "reconciliation_status": "match",
        }
        labels = root / "backtest" / "market_day_labels.csv"
        labels.parent.mkdir(parents=True)
        with labels.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(label))
            writer.writeheader()
            writer.writerow(label)
        ledger = root / "settlements" / "nyc" / "ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(label) + "\n", encoding="utf-8")
        (folder / "settlement.json").write_text(json.dumps(label), encoding="utf-8")
        return _args(
            tmp,
            snapshots_root=str(snapshots),
            labels_csv=str(labels),
            ledger_root=str(root / "settlements"),
            settled_analysis_target_date=target_date,
            markets="nyc",
        )

    def _barrier_steps(self, target_date, **result_overrides):
        steps = [
            {
                "name": "public_wu_settlement_restore",
                "status": "ok",
                "result": {"status": "PASS", "target_date": target_date},
            },
            {
                "name": "market_day_labels_finalize",
                "status": "ok",
                "result": {
                    "label_count": 1,
                    "quality_counts": {"complete": 1},
                    "promotion_countability_available": True,
                    "promotion_countable_label_count": 1,
                    "promotion_blocked_label_count": 0,
                },
            },
            {"name": "exchange_economics_rule_drift", "status": "ok", "result": {"status": "PASS"}},
            {"name": "taker_finalization_watchdog", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "taker_edge_permission_map", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "taker_tail_casebook", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "maker_paper_score", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "settlement_source_audit", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "observed_floor_safety_monitor", "status": "ok", "result": {"status": "PASS", "target_date": target_date}},
            {"name": "trading_evidence", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "replay_status_backfill", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "hourly_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "ten_minute_model_performance", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "price_free_model_learning", "status": "ok", "result": {"status": "SKIPPED"}},
            {"name": "model_market_disagreement_rehydration", "status": "ok", "result": {"status": "SKIPPED"}},
        ]
        for step in steps:
            override = result_overrides.get(step["name"])
            if override is not None:
                step["result"] = override
        return steps

    def test_settled_day_barrier_records_skill_and_countability_blocks_as_policy_verdicts(self):
        target_date = "2026-06-17"
        with tempfile.TemporaryDirectory() as tmp:
            args = self._barrier_fixture_args(tmp, target_date)
            args._daily_refresh_steps_so_far = self._barrier_steps(
                target_date,
                hourly_model_performance={"status": "BLOCK"},
                ten_minute_model_performance={"status": "BLOCK"},
                trading_evidence={
                    "status": "BLOCK",
                    "target_date": target_date,
                    "run_date": target_date,
                },
            )

            payload = run_settled_day_analysis_barrier_step(args)

        # Fail-closed skill/countability verdicts are recorded and enforced
        # downstream (early-hour promotion blocker, countability gates), but
        # do not halt settled-day analysis for a valid label day.
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["blocker_count"], 0)
        self.assertEqual(payload["policy_verdict_count"], 3)
        self.assertEqual(
            {row["component"] for row in payload["policy_verdicts"]},
            {"hourly_model_performance", "ten_minute_model_performance", "trading_evidence"},
        )

    def test_settled_day_barrier_still_blocks_on_infra_failures_and_date_mismatch(self):
        target_date = "2026-06-17"
        with tempfile.TemporaryDirectory() as tmp:
            args = self._barrier_fixture_args(tmp, target_date)
            args._daily_refresh_steps_so_far = self._barrier_steps(
                target_date,
                trading_evidence={"status": "CRITICAL"},
            )
            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)
        self.assertIn(
            "trading_evidence",
            {row["component"] for row in raised.exception.payload["blockers"]},
        )

        with tempfile.TemporaryDirectory() as tmp:
            args = self._barrier_fixture_args(tmp, target_date)
            steps = self._barrier_steps(
                target_date,
                trading_evidence={
                    "status": "BLOCK",
                    "target_date": "2026-06-16",
                    "run_date": "2026-06-16",
                },
            )
            args._daily_refresh_steps_so_far = steps
            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)
        blockers = {row["component"]: row["detail"] for row in raised.exception.payload["blockers"]}
        self.assertIn("trading_evidence", blockers)
        self.assertIn("target_date_mismatch", blockers["trading_evidence"])

        with tempfile.TemporaryDirectory() as tmp:
            args = self._barrier_fixture_args(tmp, target_date)
            steps = self._barrier_steps(target_date)
            for step in steps:
                if step["name"] == "hourly_model_performance":
                    step["status"] = "error"
                    step["error"] = "scoring crashed"
            args._daily_refresh_steps_so_far = steps
            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)
        self.assertIn(
            "hourly_model_performance",
            {row["component"] for row in raised.exception.payload["blockers"]},
        )

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
        self.assertEqual(
            [step["lane"] for step in payload["steps"]],
            [STEP_LANES[step["name"]] for step in payload["steps"]],
        )

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

    def test_cli_run_defaults_heavy_steps_to_subprocess_isolation(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--dry-run"])

        self.assertTrue(args.heavy_step_subprocess)
        self.assertEqual(args.heavy_step_timeout_seconds, 8 * 60 * 60)
        self.assertEqual(args.heavy_step_working_set_max_mb, 6144)
        self.assertEqual(args.stage_a_min_available_reserve_mb, 1536)
        self.assertEqual(args.stage_a_max_commit_percent, 70.0)
        self.assertEqual(args.capture_resource_mode, "live")
        self.assertFalse(args.skip_captured_input_replay_parity)
        self.assertFalse(args.skip_production_readiness_gate)
        self.assertEqual(args.maker_paper_latest_active_runs, 14)
        self.assertEqual(args.maker_paper_max_input_bytes, 512 * 1024 * 1024)

        disabled = parser.parse_args([
            "run",
            "--dry-run",
            "--disable-heavy-step-subprocess",
            "--heavy-step-timeout-seconds",
            "5",
            "--heavy-step-working-set-max-mb",
            "256",
            "--capture-resource-mode",
            "offline_host",
            "--maker-paper-latest-active-runs",
            "3",
            "--maker-paper-max-input-bytes",
            "1024",
        ])
        self.assertFalse(disabled.heavy_step_subprocess)
        self.assertEqual(disabled.heavy_step_timeout_seconds, 5)
        self.assertEqual(disabled.heavy_step_working_set_max_mb, 256)
        self.assertEqual(disabled.capture_resource_mode, "offline_host")
        self.assertEqual(disabled.maker_paper_latest_active_runs, 3)
        self.assertEqual(disabled.maker_paper_max_input_bytes, 1024)

    def test_cli_run_injects_lock_diagnostic_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parser = build_parser()
            args = parser.parse_args([
                "run",
                "--backtest-root",
                str(root / "backtest"),
                "--snapshots-root",
                str(root / "snapshots"),
                "--status-out",
                str(root / "backtest" / "daily_refresh_status.json"),
                "--report-out",
                str(root / "backtest" / "daily_refresh_report.md"),
                "--lock-path",
                str(root / "backtest" / "daily_refresh.lock"),
                "--long-job-state",
                str(root / "backtest" / "long_job_guard_status.json"),
                "--long-job-lock",
                str(root / "backtest" / "long_job_guard.lock"),
                "--stage-a-manifest",
                str(root / "backtest" / "stage_a.json"),
                "--stage-b-manifest",
                str(root / "backtest" / "stage_b.json"),
                "--disable-long-job-guard",
            ])
            captured = {}

            def fake_run(run_args):
                captured["preflight"] = getattr(run_args, "_daily_refresh_cli_lock_preflight", {})
                captured["paths"] = [
                    run_args.status_out,
                    run_args.report_out,
                    run_args.lock_path,
                    run_args.long_job_state,
                    run_args.long_job_lock,
                    run_args.stage_a_manifest,
                    run_args.stage_b_manifest,
                ]
                return {"status": "ok"}, Path(run_args.status_out), Path(run_args.report_out)

            with (
                patch("weather.operations.daily_refresh_cli.acquire_lock", return_value={"pid": 123}),
                patch("weather.operations.daily_refresh_cli.release_lock"),
                patch("weather.operations.daily_refresh_cli.run_daily_refresh", side_effect=fake_run),
                patch(
                    "weather.operations.daily_refresh_cli.trigger_evidence_stage_after_lock",
                    return_value={"status": "SKIPPED", "reason": "test_isolation"},
                ),
            ):
                code = args.func(args)

        self.assertEqual(code, 0)
        self.assertIn("daily_refresh_lock_after_acquire", captured["preflight"])
        self.assertTrue(
            all(Path(path).resolve().is_relative_to(root.resolve()) for path in captured["paths"])
        )

    def test_default_runner_order_repairs_replay_status_before_data_layer_audit(self):
        names = [name for name, _runner in DEFAULT_RUNNERS]

        self.assertLess(names.index("ingest_quality_gate"), names.index("event_metadata_validation"))
        self.assertLess(names.index("event_metadata_validation"), names.index("public_wu_settlement_restore"))
        self.assertLess(names.index("public_wu_settlement_restore"), names.index("market_day_labels_finalize"))
        self.assertLess(names.index("event_metadata_validation"), names.index("market_day_labels_finalize"))
        self.assertLess(names.index("event_metadata_validation"), names.index("trading_evidence"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("replay_status_backfill"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("exchange_economics_rule_drift"))
        self.assertLess(names.index("exchange_economics_rule_drift"), names.index("taker_finalization_watchdog"))
        self.assertLess(names.index("exchange_economics_rule_drift"), names.index("maker_paper_score"))
        self.assertLess(names.index("taker_finalization_watchdog"), names.index("taker_edge_permission_map"))
        self.assertLess(names.index("taker_edge_permission_map"), names.index("taker_tail_casebook"))
        self.assertLess(names.index("taker_tail_casebook"), names.index("maker_paper_score"))
        self.assertLess(names.index("maker_paper_score"), names.index("settlement_source_audit"))
        self.assertLess(names.index("settlement_source_audit"), names.index("observed_floor_safety_monitor"))
        self.assertLess(names.index("observed_floor_safety_monitor"), names.index("trading_evidence"))
        self.assertLess(names.index("settlement_source_audit"), names.index("trading_evidence"))
        self.assertLess(names.index("trading_evidence"), names.index("daily_learning"))
        self.assertLess(names.index("market_day_labels_finalize"), names.index("clob_order_book_tiering"))
        self.assertLess(names.index("clob_order_book_tiering"), names.index("replay_status_backfill"))
        self.assertLess(names.index("replay_status_backfill"), names.index("closed_day_parquet_incremental"))
        self.assertLess(names.index("settled_day_analysis_barrier"), names.index("fleet_observability"))
        self.assertLess(names.index("fleet_observability"), names.index("promotion_refresh"))
        self.assertLess(names.index("fleet_observability"), names.index("progress_audit"))
        self.assertLess(names.index("fleet_observability"), names.index("nightly_health_checks"))
        self.assertLess(names.index("fleet_observability"), names.index("daily_roll_log_hygiene"))
        self.assertLess(names.index("daily_roll_log_hygiene"), names.index("nightly_health_checks"))
        self.assertLess(names.index("nightly_health_checks"), names.index("data_layer_audit"))
        self.assertLess(names.index("closed_day_parquet_incremental"), names.index("data_layer_audit"))
        self.assertLess(names.index("replay_status_backfill"), names.index("data_layer_audit"))
        self.assertLess(names.index("data_layer_audit"), names.index("snapshot_evaluation"))
        self.assertLess(names.index("snapshot_evaluation"), names.index("distribution_stage_attribution"))
        self.assertLess(names.index("distribution_stage_attribution"), names.index("settled_day_root_cause"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("winner_rank_parity"))
        self.assertLess(names.index("settled_day_root_cause"), names.index("winner_rank_parity"))
        self.assertLess(names.index("winner_rank_parity"), names.index("june23_location_bias_repair"))
        self.assertLess(names.index("june23_location_bias_repair"), names.index("data_retention_inventory"))
        self.assertLess(names.index("data_retention_inventory"), names.index("daily_learning"))
        self.assertLess(names.index("trading_evidence"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("winner_rank_parity"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("daily_learning"), names.index("market_beating_objective_scoreboard"))
        self.assertLess(names.index("market_beating_objective_scoreboard"), names.index("daily_flow_analysis"))
        self.assertLess(names.index("replay_status_backfill"), names.index("hourly_model_performance"))
        self.assertLess(names.index("hourly_model_performance"), names.index("ten_minute_model_performance"))
        self.assertLess(names.index("ten_minute_model_performance"), names.index("price_free_model_learning"))
        self.assertLess(names.index("price_free_model_learning"), names.index("model_market_disagreement_rehydration"))
        self.assertLess(names.index("model_market_disagreement_rehydration"), names.index("settled_day_analysis_barrier"))
        self.assertLess(names.index("price_free_model_learning"), names.index("settled_day_analysis_barrier"))
        self.assertLess(names.index("settled_day_analysis_barrier"), names.index("runtime_identity_reconciliation"))
        self.assertLess(names.index("runtime_identity_reconciliation"), names.index("fleet_observability"))
        self.assertLess(names.index("runtime_identity_reconciliation"), names.index("promotion_refresh"))
        self.assertLess(names.index("runtime_identity_reconciliation"), names.index("progress_audit"))
        self.assertLess(names.index("settled_day_analysis_barrier"), names.index("promotion_refresh"))
        self.assertLess(names.index("active_variant_shadow"), names.index("proper_scoring_reliability_scorecard"))
        self.assertLess(names.index("proper_scoring_reliability_scorecard"), names.index("frozen_baseline_replay_trend"))
        self.assertLess(names.index("frozen_baseline_replay_trend"), names.index("model_variant_evidence_growth"))

    def test_public_wu_settlement_restore_fetches_missing_raw_and_rebuilds_outputs(self):
        target_date = "2026-06-19"
        target = date.fromisoformat(target_date)
        calls = []

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            def fetch_range(self, start, end, units=None):
                calls.append((start, end, units))
                return {"observations": [{"valid_time_gmt": 1, "temp": 77}]}

        class FakeStore:
            def __init__(self, root, **_kwargs):
                self.root = Path(root)
                self.daily_root = self.root / "daily"
                self._raw = set()

            def raw_dates(self):
                return set(self._raw)

            def missing_ranges(self, start, end, chunk_days=1):
                return [] if start in self._raw else [(start, end)]

            def write_payload(self, start, _end, _payload):
                self._raw.add(start)

            def rebuild_normalized_files(self):
                return (
                    [{"local_date": target_date}],
                    [{"local_date": target_date, "row_count": "24", "max_temp_bucket_native": "77"}],
                )

            def write_fetch_error(self, *_args, **_kwargs):
                raise AssertionError("restore should not record errors")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_source_steps.all_specs", return_value=[
                    SimpleNamespace(
                        id="nyc",
                        icao="KLGA",
                        city_label="NYC",
                        wu_history_id="KLGA:9:US",
                        tz="America/New_York",
                        display_unit="F",
                        wu_units="e",
                        data_root=Path(tmp) / "wunderground" / "klga",
                    )
                ]), \
                patch("weather.operations.daily_refresh_source_steps.PublicWundergroundHistoryClient", FakeClient), \
                patch("weather.operations.daily_refresh_source_steps.WundergroundHistoryStore", FakeStore):
            result = run_public_wu_settlement_restore_step(
                _args(tmp, settled_analysis_target_date=target_date, wu_settlement_restore_markets="nyc")
            )
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(calls, [(target, target, "e")])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["target_date"], target_date)
        self.assertEqual(result["restored_market_count"], 1)
        self.assertEqual(result["fetched_range_count"], 1)
        self.assertEqual(payload["markets"][0]["daily_summary_bucket"], "77")

    def test_market_day_label_finalization_blocks_when_wu_restore_did_not_pass(self):
        target_date = "2026-06-19"
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date=target_date)
            args._daily_refresh_steps_so_far = [
                {
                    "name": "public_wu_settlement_restore",
                    "status": "ok",
                    "result": {
                        "status": "BLOCK",
                        "target_date": target_date,
                        "blocked_markets": ["nyc"],
                    },
                }
            ]

            result = run_market_day_labels_finalize(args)

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "public_wu_settlement_restore_not_passed")
        self.assertEqual(result["restore_status"], "BLOCK")

    def test_settled_day_barrier_requires_wu_restore_step_before_labels(self):
        target_date = "2026-06-19"
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date=target_date)
            args._daily_refresh_steps_so_far = _settled_barrier_dependency_steps(
                target_date,
                restore=False,
            )

            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)

        blockers = raised.exception.payload["blockers"]
        self.assertIn("public_wu_settlement_restore", {row["component"] for row in blockers})

    def test_settled_day_barrier_blocks_wu_restore_after_label_finalization(self):
        target_date = "2026-06-19"
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date=target_date)
            args._daily_refresh_steps_so_far = _settled_barrier_dependency_steps(
                target_date,
                restore_after_finalize=True,
            )

            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)

        details = {row["detail"] for row in raised.exception.payload["blockers"]}
        self.assertIn(
            "step_order_violation=public_wu_settlement_restore_after_market_day_labels_finalize",
            details,
        )

    def test_runtime_identity_reconciliation_step_uses_settled_target_date(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_reporting_steps.runtime_identity_reconciliation.build_payload") as build, \
                patch("weather.operations.daily_refresh_reporting_steps.runtime_identity_reconciliation.write_outputs") as write:
            root = Path(tmp)
            payload = {
                "status": "BLOCK",
                "target_date": "2026-06-19",
                "mixed_runtime_identity": True,
                "runtime_identity_count": 2,
                "snapshot_row_count": 10,
                "blocker_count": 1,
                "first_blocker": {"category": "mixed_runtime_identity"},
            }
            build.return_value = payload
            write.return_value = (
                root / "backtest" / "runtime_identity_reconciliation.json",
                root / "backtest" / "runtime_identity_reconciliation.md",
            )

            result = run_runtime_identity_reconciliation_step(
                _args(tmp, settled_analysis_target_date="2026-06-19")
            )

        build.assert_called_once_with(
            snapshots_root=str(root / "snapshots"),
            target_date="2026-06-19",
        )
        write.assert_called_once_with(
            payload,
            json_out=str(root / "backtest" / "runtime_identity_reconciliation.json"),
            report_out=str(root / "backtest" / "runtime_identity_reconciliation.md"),
        )
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["target_date"], "2026-06-19")
        self.assertTrue(result["mixed_runtime_identity"])
        self.assertEqual(result["blocker_count"], 1)

    def test_exchange_economics_rule_drift_step_blocks_on_material_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date="2026-06-19", as_of="2026-06-20T12:00:00+00:00")
            current = _write_exchange_snapshot(Path(args.exchange_economics_snapshot))
            accepted_payload = json.loads(current.read_text(encoding="utf-8"))
            accepted_payload["market_rules"]["tick_size"] = 0.005
            accepted = Path(args.exchange_economics_accepted_snapshot)
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.write_text(json.dumps(accepted_payload), encoding="utf-8")

            with patch(
                "weather.operations.daily_refresh_trading_steps.exchange_economics.collect_and_publish_global_snapshot",
                side_effect=_collect_test_exchange_snapshot,
            ):
                result = run_exchange_economics_rule_drift_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(result["rescore_required"])
        self.assertEqual(payload["material_change_count"], 1)
        self.assertEqual(payload["material_changes"][0]["field"], "market_rules.tick_size")

    def test_exchange_economics_rule_drift_step_passes_with_accepted_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date="2026-06-19", as_of="2026-06-20T12:00:00+00:00")
            current = _write_exchange_snapshot(Path(args.exchange_economics_snapshot))
            accepted = Path(args.exchange_economics_accepted_snapshot)
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")

            with patch(
                "weather.operations.daily_refresh_trading_steps.exchange_economics.collect_and_publish_global_snapshot",
                side_effect=_collect_test_exchange_snapshot,
            ):
                result = run_exchange_economics_rule_drift_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["rescore_required"])
        self.assertTrue(payload["accepted_snapshot_present"])
        self.assertEqual(payload["current_gate"]["evidence_basis"], "current_exchange_economics")

    def test_exchange_economics_rule_drift_step_refreshes_stale_target_date_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp, settled_analysis_target_date="2026-06-19", as_of="2026-06-20T12:00:00+00:00")
            stale = _write_exchange_snapshot(
                Path(args.exchange_economics_snapshot),
                target_date="2026-06-17",
                now="2026-06-17T12:00:00+00:00",
            )
            accepted = Path(args.exchange_economics_accepted_snapshot)
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.write_text(stale.read_text(encoding="utf-8"), encoding="utf-8")

            with patch(
                "weather.operations.daily_refresh_trading_steps.exchange_economics.collect_and_publish_global_snapshot",
                side_effect=_collect_test_exchange_snapshot,
            ):
                result = run_exchange_economics_rule_drift_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            refreshed_snapshot = json.loads(Path(args.exchange_economics_snapshot).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["snapshot_refresh_status"], "PASS")
        # Current API economics are stamped and validated for the operating
        # day. They are not backfilled onto the settled-analysis target.
        self.assertEqual(result["target_date"], "2026-06-20")
        self.assertEqual(result["settled_analysis_target_date"], "2026-06-19")
        self.assertEqual(result["snapshot_refresh_target_date"], "2026-06-20")
        self.assertEqual(refreshed_snapshot["verified_for_target_date"], "2026-06-20")
        self.assertEqual(payload["current_gate"]["status"], "PASS")
        self.assertEqual(payload["current_gate"]["verified_for_target_date"], "2026-06-20")
        self.assertEqual(payload["settled_analysis_target_date"], "2026-06-19")

    def test_exchange_economics_refresh_uses_operating_date_not_utc_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                settled_analysis_target_date="2026-06-18",
                as_of="2026-06-20T01:00:00+00:00",
            )
            current = _write_exchange_snapshot(
                Path(args.exchange_economics_snapshot),
                target_date="2026-06-19",
                now="2026-06-20T01:00:00+00:00",
            )
            accepted = Path(args.exchange_economics_accepted_snapshot)
            accepted.parent.mkdir(parents=True, exist_ok=True)
            accepted.write_text(current.read_text(encoding="utf-8"), encoding="utf-8")

            with patch(
                "weather.operations.daily_refresh_trading_steps.exchange_economics.collect_and_publish_global_snapshot",
                side_effect=_collect_test_exchange_snapshot,
            ) as collect:
                result = run_exchange_economics_rule_drift_step(args)

        self.assertEqual(result["snapshot_refresh_target_date"], "2026-06-19")
        self.assertEqual(collect.call_args.kwargs["target_date"], "2026-06-19")

    def test_model_market_disagreement_rehydration_step_writes_resolved_revision(self):
        target_date = "2026-06-21"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            slug = event_slug_for_date(target_date, "nyc")
            log_path = backtest / "model_market_disagreement_audit.jsonl"
            audit_row = {
                "schema_version": "model_market_disagreement_audit_v0.1",
                "audit_key": "mma-step-test",
                "audit_revision": 1,
                "audited_at_utc": "2026-06-21T18:00:00+00:00",
                "status": "pending_settlement",
                "event_slug": slug,
                "market_id": "nyc",
                "target_date": target_date,
                "snapshot_id": "s1",
                "captured_at_local": "2026-06-21T14:00:00-04:00",
                "range_label": "77 F",
                "band_key": "eq:77",
                "model_probability": 0.9,
                "market_yes": 0.1,
                "fair_value_probability": None,
                "model_minus_market_points": 80.0,
                "gap_points": 80.0,
                "closer_source": "pending_settlement",
                "outcome": None,
            }
            log_path.write_text(json.dumps(audit_row) + "\n", encoding="utf-8")
            labels = backtest / "market_day_labels.csv"
            labels.write_text(
                "event_slug,market_id,target_date,settlement_bucket,settlement_unit,"
                "settlement_source,quality_grade,winning_band,finalized_at_utc\n"
                f"{slug},nyc,{target_date},77,F,daily_summary,complete,77 F,"
                "2026-06-22T01:00:00+00:00\n",
                encoding="utf-8",
            )
            args = _args(
                tmp,
                labels_csv=str(labels),
                model_market_disagreement_log=str(log_path),
                settled_analysis_target_date=target_date,
            )

            result = run_model_market_disagreement_rehydration_step(args)
            json_exists = Path(result["json_out"]).exists()
            report_exists = Path(result["report_out"]).exists()
            rows = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").strip().splitlines()
            ]

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["rehydrated_count"], 1)
        self.assertEqual(result["model_closer_rehydrated_count"], 1)
        self.assertEqual(result["pending_after_count"], 0)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["status"], "resolved")
        self.assertEqual(rows[-1]["closer_source"], "model")

    def test_daily_roll_log_hygiene_archives_old_errors_and_promotes_recurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            logs.mkdir()
            taker_log = logs / "taker.log"
            taker_log.write_text(
                "\n".join([
                    "2026-06-20T01:00:00+00:00 No space left on device while writing tape",
                    "2026-06-20T02:00:00+00:00 UnicodeDecodeError: codec can't decode byte 0xff",
                    "2026-06-24T11:00:00+00:00 daily roll healthy",
                ])
                + "\n",
                encoding="utf-8",
            )
            args = _args(
                tmp,
                as_of="2026-06-24T12:00:00+00:00",
                daily_roll_log_sources=f"taker={taker_log}",
                daily_roll_log_window_hours=6.0,
                daily_roll_log_incidents=str(root / "backtest" / "daily_roll_log_incidents.jsonl"),
            )

            first = run_daily_roll_log_hygiene_step(args)
            first_incidents_exists = Path(first["incidents_out"]).exists()
            first_current_log_exists = (Path(first["current_log_root"]) / "taker.current.log").exists()
            taker_log.write_text(
                "\n".join([
                    "2026-06-20T01:00:00+00:00 No space left on device while writing tape",
                    "2026-06-24T11:30:00+00:00 No space left on device while writing tape",
                ])
                + "\n",
                encoding="utf-8",
            )
            second = run_daily_roll_log_hygiene_step(args)

        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["current_blocker_count"], 0)
        self.assertEqual(first["historical_error_count"], 2)
        self.assertEqual(first["archived_incident_count"], 2)
        self.assertTrue(first_incidents_exists)
        self.assertTrue(first_current_log_exists)
        self.assertEqual(second["status"], "BLOCK")
        self.assertEqual(second["current_blocker_count"], 1)
        self.assertEqual(second["recurring_incident_count"], 1)
        self.assertEqual(
            second["first_current_blocker"]["recurrence_of_incident_id"],
            second["first_current_blocker"]["incident_id"],
        )

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
        calls = []

        def after(_args):
            calls.append("daily_learning")
            return {"status": "BLOCKED"}

        def promotion_for_test(step_args):
            return run_promotion_refresh_step(step_args)

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_reporting_steps.promotion_refresh.run_promotion_refresh") as run_refresh:
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
                    replay_cache_root=str(backtest / "replay_cache"),
                ),
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": getattr(
                                _args,
                                "settled_analysis_target_date",
                            ),
                        },
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": getattr(
                                _args,
                                "settled_analysis_target_date",
                            ),
                            "source_row_count": 1,
                            "valid_prediction_partition_count": 1,
                        },
                    ),
                    ("promotion_refresh", promotion_for_test),
                    ("daily_learning", after),
                ],
            )
            report = Path(report_path).read_text(encoding="utf-8")

        run_refresh.assert_not_called()
        self.assertEqual(calls, ["daily_learning"])
        self.assertEqual(payload["status"], "critical")
        self.assertEqual(len(payload["steps"]), 4)
        step = next(
            row for row in payload["steps"] if row["name"] == "promotion_refresh"
        )
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

    def test_promotion_refresh_step_uses_subprocess_handoff_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            (backtest / "pooled_candidate_replay_latest.json").write_text(
                json.dumps({"aggregate": {"n": 1}}),
                encoding="utf-8",
            )
            captured = {}

            def fake_child(command, **kwargs):
                captured["command"] = [str(item) for item in command]
                captured["kwargs"] = kwargs
                (backtest / "f_family_promotion_refresh.json").write_text(
                    json.dumps({
                        "status": "OK",
                        "decisions": {
                            "action_counts": {"promote": 1},
                            "promote_markets": ["nyc"],
                            "shadow_markets": [],
                            "blocked_markets": [],
                        },
                        "candidate": {
                            "verdict": "PASS",
                            "candidate_market_verdict": "PASS",
                            "cutover_decision": "promote",
                            "aggregate": {"candidate_brier": 0.1, "current_brier": 0.2},
                        },
                        "corpus": {
                            "market_day_count": 1,
                            "snapshot_count": 2,
                            "band_row_count": 3,
                        },
                        "serving_gauntlet": {"verdict": "PASS"},
                    }),
                    encoding="utf-8",
                )
                return {
                    "command": [str(item) for item in command],
                    "returncode": 0,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "",
                    "working_set_limit": {"requested": False},
                }

            with patch(
                "weather.operations.daily_refresh_reporting_steps.run_isolated_subprocess",
                side_effect=fake_child,
            ) as child, patch(
                "weather.operations.daily_refresh_reporting_steps.promotion_refresh.run_promotion_refresh"
            ) as in_process:
                result = run_promotion_refresh_step(_args(
                    tmp,
                    heavy_step_subprocess=True,
                    heavy_step_working_set_max_mb=512,
                    promotion_min_artifact_free_bytes=0,
                ))

        child.assert_called_once()
        in_process.assert_not_called()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["subprocess"]["returncode"], 0)
        self.assertEqual(captured["kwargs"]["working_set_max_bytes"], 512 * 1024 * 1024)
        self.assertIn("-m", captured["command"])
        self.assertIn("weather.reporting.promotion.promotion_refresh", captured["command"])
        self.assertEqual(
            captured["command"][captured["command"].index("--output-root") + 1],
            str((Path(tmp) / "backtest").resolve()),
        )
        self.assertIn("--out", captured["command"])

    def test_resume_from_step_skips_upstream_steps(self):
        calls = []

        def runner(name):
            def _run(_args):
                calls.append(name)
                return {
                    "status": "OK" if name == "promotion_refresh" else "PASS",
                    "name": name,
                }
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
                patch("weather.operations.daily_refresh_trading_steps.clob_order_book_tiering.run") as run, \
                patch("weather.operations.daily_refresh_trading_steps.clob_order_book_tiering.write_outputs") as write_outputs:
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

    def test_scoring_liveness_block_marks_run_critical(self):
        def price_free(_args):
            return {
                "status": "BLOCK",
                "last_scored_target_date": "2026-06-21",
                "latest_settled_label_date": "2026-06-23",
                "scoring_liveness_status": "BLOCK",
                "remediation_command": "python -m weather.reporting.candidate_lifecycle.price_free_model_learning",
                "scoring_liveness": {
                    "status": "BLOCK",
                    "artifact_name": "price_free_model_learning",
                    "last_scored_target_date": "2026-06-21",
                    "latest_settled_label_date": "2026-06-23",
                    "remediation_command": "python -m weather.reporting.candidate_lifecycle.price_free_model_learning",
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_daily_refresh(
                _args(tmp),
                runners=[("price_free_model_learning", price_free)],
            )

        self.assertEqual(payload["status"], "critical")
        self.assertEqual(payload["scoring_liveness_blockers"][0]["step"], "price_free_model_learning")
        self.assertEqual(
            payload["summary"]["price_free_model_learning"]["scoring_liveness_status"],
            "BLOCK",
        )

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
                            "action": "python -m weather.reporting.fleet.fleet_observability",
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

    def test_model_variant_evidence_growth_prefers_pinned_active_shadow_baseline(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        baseline_row = "v1,f_family,False,False,nyc,2026-06-11,s1,eq:82,0.6,0.5,0.5,0.5,1,a,p,2026-06-15\n"
        new_row = "v1,f_family,False,False,nyc,2026-06-12,s2,eq:83,0.7,0.5,0.5,0.5,0,a,p,2026-06-15\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            (backtest / "active_variant_shadow_long.csv").write_text(
                header + baseline_row + new_row,
                encoding="utf-8",
            )
            baseline = backtest / "model_variant_evidence_baseline_active_shadow_long.csv"
            baseline.write_text(header + baseline_row, encoding="utf-8")
            args = _args(tmp)

            result = run_model_variant_evidence_growth_step(args)

        self.assertEqual(result["baseline_paths"], [str(baseline)])
        self.assertEqual(result["delta_vs_baseline"]["unique_observation_count"], 1)
        self.assertEqual(result["delta_vs_baseline"]["market_day_count"], 1)

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
                settled_analysis_target_date="2026-06-19",
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

    def test_taker_finalization_watchdog_step_finalizes_zero_fill_and_writes_dated_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-zero"
            event_slug = "highest-temperature-in-seattle-on-june-19-2026"
            base_row = {
                "schema_version": "taker_bot_run_v0.1",
                "run_id": "taker-zero",
                "target_date": "2026-06-19",
                "generated_at_utc": "2026-06-19T20:00:00+00:00",
                "captured_at_utc": "2026-06-19T20:00:00+00:00",
                "market_id": "seattle",
                "event_slug": event_slug,
                "range_label": "80-81 F",
                "bin_kind": "eq",
                "bin_value": "80",
                "bin_value_hi": "81",
                "clob_token_id": "token-seattle-80",
                "fair_probability": "0.80",
                "best_ask": "0.60",
                "reason_code": "NO_TRADE_EDGE_TOO_SMALL",
                "strategy_id": "strict_edge_probe",
                "strategy_family": "probe",
            }
            _write_order_tape(
                run / "orders_long.csv",
                [{**base_row, "order_status": "SKIPPED", "action": "NO_TRADE"}],
            )
            _write_order_tape(
                run / "counterfactual_orders_long.csv",
                [
                    {
                        **base_row,
                        "order_status": "FILLED",
                        "action": "BUY",
                        "fill_price": "0.60",
                        "fill_size": "10",
                        "fill_notional_usdc": "6.0",
                        "total_spent_usdc": "6.0",
                        "reason_code": "BUY_EDGE",
                        "strategy_id": "raw_edge_control",
                    }
                ],
            )
            (run / "run_config.json").write_text(
                json.dumps({
                    "run_id": "taker-zero",
                    "target_date": "2026-06-19",
                    "budget_usdc": 12,
                    "active_strategy_id": "strict_edge_probe",
                    "strategy_ids": ["strict_edge_probe"],
                    "policy_config": {"min_edge": 0.25, "max_order_usdc": 10},
                }),
                encoding="utf-8",
            )
            (run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "taker-zero",
                        "target_date": "2026-06-19",
                        "summary": {
                            "budget_usdc": 12,
                            "latest_tick_rows": 1,
                            "latest_tick_filled_orders": 0,
                            "cumulative_filled_orders": 0,
                            "cumulative_net_pnl_usdc": 0.0,
                            "reason_counts": {"NO_TRADE_EDGE_TOO_SMALL": 1},
                            "root_cause_class": "policy_no_edge",
                        },
                        "pnl": {"summary": {"filled_order_count": 0, "unsettled_order_count": 0}},
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
                settled_analysis_target_date="2026-06-19",
                taker_finalization_min_free_bytes=0,
            )

            result = run_taker_finalization_watchdog_step(args)
            settled_exists = (run / "settled_pnl.json").exists()
            bakeoff_exists = (run / "strategy_bakeoff.json").exists()
            detail_json_exists = Path(result["detail_json_out"]).exists()
            detail_report_exists = Path(result["detail_report_out"]).exists()

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["target_date"], "2026-06-19")
        self.assertEqual(result["finalized_run_count"], 1)
        self.assertTrue(settled_exists)
        self.assertTrue(bakeoff_exists)
        self.assertTrue(detail_json_exists)
        self.assertTrue(detail_report_exists)

    def test_taker_edge_permission_map_step_rebuilds_from_settled_tapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "taker_runs" / "2026-06-19" / "taker-map"
            run.mkdir(parents=True)
            rows = []
            for index in range(5):
                rows.append({
                    "target_date": f"2026-06-{14 + index:02d}",
                    "market_id": "atlanta",
                    "captured_at_utc": f"2026-06-{14 + index:02d}T16:00:00+00:00",
                    "capture_hour_local": "12",
                    "side": "YES_BUY",
                    "source_freshness_state": "all_fresh",
                    "snapshot_cadence_quality_state": "clean",
                    "current_high_trusted": "True",
                    "current_high_band_distance": "0",
                    "model_variant_id": "served_current",
                    "fair_probability": "0.90",
                    "market_mid": "0.55",
                    "best_ask": "0.60",
                    "settlement_outcome": "1",
                })
            with (run / "settled_counterfactual_orders_long.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            args = _args(
                tmp,
                taker_edge_permission_map_out=str(root / "backtest" / "taker_edge_permission_map.json"),
            )

            result = run_taker_edge_permission_map_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_tape_count"], 1)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["edge_allowed_count"], 1)
        self.assertEqual(payload["records"][0]["permission"], "edge_allowed")

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

            result = run_taker_tail_casebook_step(
                _args(tmp, labels_csv=str(labels), settled_analysis_target_date="2026-06-21")
            )
            json_exists = Path(result["json_out"]).exists()
            report_exists = Path(result["report_out"]).exists()
            detail_json_exists = Path(result["detail_json_out"]).exists()
            detail_report_exists = Path(result["detail_report_out"]).exists()

        self.assertEqual(result["status"], "BLOCK_BAD_TAIL_SLICES")
        self.assertEqual(result["target_date"], "2026-06-21")
        self.assertEqual(result["tail_fill_count"], 1)
        self.assertEqual(result["no_go_candidate_count"], 1)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)
        self.assertTrue(detail_json_exists)
        self.assertTrue(detail_report_exists)

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
                        "exchange_economics_gate": {"required": False, "ok": True, "status": "PASS"},
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

            result = run_trading_evidence_step(_args(tmp, settled_analysis_target_date="2026-06-19"))
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

            result = run_settlement_source_audit_step(_args(
                tmp,
                labels_csv=str(labels),
                ledger_root=str(root / "settlements"),
                as_of="2026-06-20T12:00:00+00:00",
            ))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report_exists = Path(result["report_out"]).exists()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["target_date"], "2026-06-19")
        self.assertEqual(result["target_date_gate_blockers"], [])
        self.assertEqual(result["global_status"], "PASS")
        self.assertEqual(result["label_count"], 1)
        self.assertEqual(result["finalized_label_count"], 1)
        self.assertEqual(result["proof_grade_label_count"], 1)
        self.assertEqual(payload["summary"]["promotion_blocked_label_count"], 0)
        self.assertTrue(report_exists)

    def test_settlement_source_audit_step_gates_on_analyzed_target_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            daily = root / "daily_summary.csv"
            snapshot = root / "snapshots_long.csv"
            ledger = root / "settlements" / "atlanta" / "ledger.jsonl"
            daily.write_text("local_date,row_count,max_temp_bucket_c\n2026-06-19,24,84\n", encoding="utf-8")
            snapshot.write_text("snapshot_id,wu_history_high_c\ns1,84\n", encoding="utf-8")
            current_row = {
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
            historical_row = {
                **current_row,
                "event_slug": "highest-temperature-in-atlanta-on-june-01-2026",
                "target_date": "2026-06-01",
                "quality_grade": "partial",
                "reconciliation_status": "match",
                "promotion_countable": "False",
                "promotion_countable_reason": "capture_ratio 49.3% below material threshold 80%",
            }
            fieldnames = sorted(set(current_row) | set(historical_row))
            labels = root / "labels.csv"
            labels.write_text(
                ",".join(fieldnames) + "\n"
                + ",".join(current_row.get(key, "") for key in fieldnames) + "\n"
                + ",".join(historical_row.get(key, "") for key in fieldnames) + "\n",
                encoding="utf-8",
            )
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps(current_row) + "\n" + json.dumps(historical_row) + "\n",
                encoding="utf-8",
            )

            result = run_settlement_source_audit_step(_args(
                tmp,
                labels_csv=str(labels),
                ledger_root=str(root / "settlements"),
                as_of="2026-06-20T12:00:00+00:00",
            ))

        # Historical non-proof-grade labels keep the global audit BLOCK for
        # visibility but must not fail-close analysis of the current settled day.
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["target_date"], "2026-06-19")
        self.assertEqual(result["target_date_gate_blockers"], [])
        self.assertEqual(result["global_status"], "BLOCK")
        self.assertEqual(result["promotion_blocked_label_count"], 1)

    def test_observed_floor_safety_monitor_step_writes_settled_day_artifacts(self):
        target_date = "2026-06-19"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "snapshots" / "atlanta-day"
            folder.mkdir(parents=True)
            tape = folder / "snapshots_long.csv"
            tape.write_text(
                "snapshot_id,range_label\ns1,84 F\ns1,85 F\n",
                encoding="utf-8",
            )
            (folder / "snapshot_explanations.jsonl").write_text(
                json.dumps({
                    "snapshot_id": "s1",
                    "market_id": "atlanta",
                    "target_date": target_date,
                    "explanations": {
                        "probability_calibration_context": {
                            "observed_floor_bucket": 84,
                            "effective_observed_floor_bucket": 84,
                            "effective_observed_high_source": "current_or_station_max_since_7am",
                        }
                    },
                }) + "\n",
                encoding="utf-8",
            )
            labels = root / "labels.csv"
            labels.write_text(
                "event_slug,market_id,target_date,settlement_bucket,snapshot_tape_path\n"
                f"atlanta-day,atlanta,{target_date},84,{tape}\n",
                encoding="utf-8",
            )

            result = run_observed_floor_safety_monitor_step(_args(
                tmp,
                labels_csv=str(labels),
                settled_analysis_target_date=target_date,
            ))
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["target_date"], target_date)
        self.assertEqual(result["enforced_floor_count"], 1)
        self.assertEqual(result["over_final_count"], 0)
        self.assertEqual(result["enforcement_mode"], "alert_only")
        self.assertFalse(result["hard_stop_pipeline"])
        self.assertEqual(payload["summary"]["snapshot_count"], 1)

    def test_settled_day_barrier_treats_default_floor_alert_as_advisory(self):
        target_date = "2026-06-19"
        dependency = next(
            row
            for row in SETTLED_DAY_ANALYSIS_DEPENDENCIES
            if row.get("step") == "observed_floor_safety_monitor"
        )
        result = _dependency_status(
            {
                "name": "observed_floor_safety_monitor",
                "status": "ok",
                "result": {
                    "status": "ALERT",
                    "target_date": target_date,
                    "enforcement_mode": "alert_only",
                    "hard_stop_pipeline": False,
                    "over_final_count": 1,
                },
            },
            dependency,
            target_date,
        )

        self.assertIsNone(result["blocker"])
        self.assertTrue(result["policy_verdict"])

    def test_settled_day_barrier_hard_stops_on_one_over_final_floor(self):
        target_date = "2026-06-19"
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                settled_analysis_target_date=target_date,
                fail_on_observed_floor_safety=True,
            )
            steps = _settled_barrier_dependency_steps(target_date)
            floor_step = next(
                step
                for step in steps
                if step.get("name") == "observed_floor_safety_monitor"
            )
            floor_step["result"] = {
                "status": "ALERT",
                "target_date": target_date,
                "enforcement_mode": "fail_closed",
                "hard_stop_pipeline": True,
                "over_final_count": 1,
            }
            args._daily_refresh_steps_so_far = steps

            with self.assertRaises(SettledDayAnalysisBarrierError) as raised:
                run_settled_day_analysis_barrier_step(args)

        blocker = next(
            row
            for row in raised.exception.payload["blockers"]
            if row.get("component") == "observed_floor_safety_monitor"
        )
        self.assertEqual(blocker["detail"], "step_result_status=ALERT")
        self.assertIn(
            "--resume-from-step observed_floor_safety_monitor",
            blocker["resume_command"],
        )
        self.assertIn("--fail-on-observed-floor-safety", blocker["resume_command"])

    def test_daily_report_puts_alert_only_floor_alert_before_steps(self):
        alert = {
            "market_id": "toronto",
            "target_date": "2026-07-30",
            "snapshot_id": "s1",
            "floor_bucket": 28,
            "settlement_bucket": 27,
            "rescue_source": "current_or_station_max_since_7am",
            "overshoot_buckets": 1,
        }
        report = render_daily_refresh_report({
            "generated_at_utc": "2026-07-31T12:00:00+00:00",
            "status": "ok",
            "duration_seconds": 1,
            "steps": [{
                "name": "observed_floor_safety_monitor",
                "status": "ok",
                "duration_seconds": 0.1,
                "result": {
                    "status": "ALERT",
                    "target_date": "2026-07-30",
                    "enforcement_mode": "alert_only",
                    "hard_stop_pipeline": False,
                    "over_final_count": 1,
                    "evidence_blocker_count": 0,
                    "enforced_floor_count": 1,
                    "alerts": [alert],
                },
            }],
        })

        self.assertLess(report.index("## OVER-FINAL FLOOR ALERT"), report.index("## Steps"))
        self.assertIn("| toronto | 2026-07-30 | s1 | 28 | 27 |", report)
        self.assertIn("Enforcement mode: `alert_only`; pipeline hard stop: `False`.", report)

    def test_provisional_blocker_slugs_only_for_pure_provisional_gates(self):
        from weather.operations.daily_refresh_trading_steps import (
            _provisional_target_blocker_slugs,
        )

        payload = {
            "rows": [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-july-4-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-07-04",
                    "status": "PROVISIONAL",
                    "promotion_blocker": True,
                },
                {
                    "event_slug": "highest-temperature-in-nyc-on-july-4-2026",
                    "market_id": "nyc",
                    "target_date": "2026-07-04",
                    "status": "PROVISIONAL",
                    "promotion_blocker": False,
                },
            ]
        }
        pure = {"blockers": ["2026-07-04:atlanta:PROVISIONAL"]}
        self.assertEqual(
            _provisional_target_blocker_slugs(payload, pure, "2026-07-04"),
            ["highest-temperature-in-atlanta-on-july-4-2026"],
        )
        # Any non-PROVISIONAL blocker class disables the retry (fail closed).
        mixed = {"blockers": ["2026-07-04:atlanta:PROVISIONAL", "2026-07-04:nyc:SOURCE_DISAGREEMENT"]}
        self.assertEqual(_provisional_target_blocker_slugs(payload, mixed, "2026-07-04"), [])
        self.assertEqual(_provisional_target_blocker_slugs(payload, {"blockers": []}, "2026-07-04"), [])

    def test_merge_labels_into_csv_updates_only_matching_slugs(self):
        from weather.backtesting.settlement_ledger import LABEL_COLUMNS
        from weather.operations.daily_refresh_trading_steps import _merge_labels_into_csv

        with tempfile.TemporaryDirectory() as tmp:
            labels_csv = Path(tmp) / "labels.csv"
            with labels_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerow({
                    "event_slug": "highest-temperature-in-atlanta-on-july-4-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-07-04",
                    "reconciliation_status": "PROVISIONAL",
                })
                writer.writerow({
                    "event_slug": "highest-temperature-in-chicago-on-july-4-2026",
                    "market_id": "chicago",
                    "target_date": "2026-07-04",
                    "reconciliation_status": "match",
                })

            _merge_labels_into_csv(labels_csv, [{
                "event_slug": "highest-temperature-in-atlanta-on-july-4-2026",
                "market_id": "atlanta",
                "target_date": "2026-07-04",
                "reconciliation_status": "match",
            }])

            with labels_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = {row["event_slug"]: row for row in csv.DictReader(handle)}

        # The retried label updated in place; the untouched label survived the
        # rewrite (finalize's write_labels_csv would have dropped it).
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            rows["highest-temperature-in-atlanta-on-july-4-2026"]["reconciliation_status"],
            "match",
        )
        self.assertEqual(
            rows["highest-temperature-in-chicago-on-july-4-2026"]["reconciliation_status"],
            "match",
        )

    def test_maker_paper_score_step_writes_fresh_standard_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_active_mm_run(tmp)
            args = _args(tmp, as_of="2026-06-20T12:00:00+00:00")
            _write_exchange_snapshot(Path(args.exchange_economics_snapshot))

            result = run_maker_paper_score_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report = Path(result["report_out"]).read_text(encoding="utf-8")
            fills_exists = Path(result["fills_out"]).exists()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["paper_score_freshness_status"], "PASS")
        self.assertEqual(result["latest_completed_active_day"], "2026-06-19")
        self.assertEqual(result["latest_covered_active_day"], "2026-06-19")
        self.assertEqual(result["selected_run_count"], 1)
        self.assertTrue(fills_exists)
        self.assertEqual(payload["summary"]["paper_score_freshness_status"], "PASS")
        self.assertTrue(payload["summary"]["bounded_run_selection"])
        self.assertEqual(payload["summary"]["run_folder_selection"]["latest_n"], 14)
        self.assertEqual(
            payload["summary"]["run_folder_selection"]["evidence_mode"],
            "active_day_live_forward",
        )
        self.assertEqual(payload["summary"]["input_preflight"]["status"], "PASS")
        self.assertEqual(
            payload["input_preflight"]["selected_run_folders"],
            payload["run_folder_selection"]["selected_run_folders"],
        )
        self.assertIn("Paper-score freshness", report)

    def test_maker_paper_score_step_blocks_before_loading_over_budget_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_active_mm_run(tmp)
            args = _args(
                tmp,
                as_of="2026-06-20T12:00:00+00:00",
                maker_paper_max_input_bytes=1,
            )

            with patch(
                "weather.operations.daily_refresh_trading_steps.mm_paper.build_paper_payload"
            ) as build_payload:
                result = run_maker_paper_score_step(args)

        # Not even the single newest run fits, so nothing is admitted and the
        # step still fails loudly rather than scoring an empty corpus.
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "maker_paper_input_budget_exceeded")
        self.assertGreater(result["candidate_input_bytes"], result["max_input_bytes"])
        self.assertEqual(result["input_bytes"], 0)
        self.assertEqual(result["selected_run_count"], 0)
        self.assertEqual(result["input_preflight"]["latest_run_limit"], 14)
        build_payload.assert_not_called()

    def test_maker_paper_score_step_trims_oldest_runs_to_fit_input_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            oldest = _write_active_mm_run(tmp, target_date="2026-06-17", run_id="mm-oldest")
            middle = _write_active_mm_run(tmp, target_date="2026-06-18", run_id="mm-middle")
            latest = _write_active_mm_run(tmp, target_date="2026-06-19", run_id="mm-latest")

            sizing = _args(tmp, as_of="2026-06-20T12:00:00+00:00")
            _write_exchange_snapshot(Path(sizing.exchange_economics_snapshot))
            per_run_bytes = sum(
                int(receipt["input_bytes"])
                for receipt in (
                    resolve_run_scoring_inputs(folder)
                    for folder in (oldest, middle, latest)
                )
            ) // 3

            # Budget fits the two newest runs but not all three.
            args = _args(
                tmp,
                as_of="2026-06-20T12:00:00+00:00",
                maker_paper_max_input_bytes=per_run_bytes * 2,
            )
            result = run_maker_paper_score_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        preflight = payload["input_preflight"]
        # The step proceeds on the freshest evidence instead of blocking, and
        # the admitted set never exceeds the memory guard.
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["candidate_run_count"], 3)
        self.assertEqual(result["input_budget_trimmed_run_count"], 1)
        self.assertEqual(result["selected_run_count"], 2)
        self.assertLessEqual(result["input_bytes"], result["max_input_bytes"])
        self.assertEqual(
            preflight["selected_run_folders"],
            [str(middle), str(latest)],
        )
        self.assertEqual(
            preflight["input_budget_trimmed_run_folders"],
            [str(oldest)],
        )
        # Provenance stays consistent with what was actually scored.
        self.assertEqual(
            payload["run_folder_selection"]["selected_run_folders"],
            preflight["selected_run_folders"],
        )
        self.assertEqual(payload["run_folder_selection"]["input_budget_trimmed_run_count"], 1)
        self.assertEqual(payload["summary"]["run_folders"], 2)
        self.assertEqual(list(payload["run_configs"]), [str(middle), str(latest)])

    def test_maker_paper_score_step_scores_exact_preflight_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_active_mm_run(tmp, target_date="2026-06-18", run_id="mm-older")
            latest = _write_active_mm_run(
                tmp,
                target_date="2026-06-19",
                run_id="mm-latest",
            )
            args = _args(
                tmp,
                as_of="2026-06-20T12:00:00+00:00",
                maker_paper_latest_active_runs=1,
            )
            _write_exchange_snapshot(Path(args.exchange_economics_snapshot))

            result = run_maker_paper_score_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        selected = payload["input_preflight"]["selected_run_folders"]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(selected, [str(latest)])
        self.assertEqual(payload["run_folder_selection"]["selected_run_folders"], selected)
        self.assertEqual(payload["summary"]["run_folders"], 1)
        self.assertEqual(list(payload["run_configs"]), [str(latest)])
        self.assertEqual(payload["summary"]["quote_rows"], 1)

    def test_maker_paper_score_step_uses_mixed_scoring_inputs_and_byte_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            fallback = _write_active_mm_run(
                tmp,
                target_date="2026-06-18",
                run_id="mm-canonical-fallback",
            )
            projected = _write_active_mm_run(
                tmp,
                target_date="2026-06-19",
                run_id="mm-projected",
            )
            for run_folder in (fallback, projected):
                canonical_projection_source = run_folder / "quote_intents_long.csv"
                with canonical_projection_source.open(
                    "r", encoding="utf-8", newline=""
                ) as handle:
                    source_row = next(csv.DictReader(handle))
                with canonical_projection_source.open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=SCORING_COLUMNS)
                    writer.writeheader()
                    writer.writerow({
                        column: source_row.get(column, "")
                        for column in SCORING_COLUMNS
                    })
            fallback_variant_source = fallback / "model_variant_quote_intents_long.csv"
            fallback_variant_source.write_bytes(
                (fallback / "quote_intents_long.csv").read_bytes()
            )
            write_run_scoring_projections(fallback)
            (fallback / MODEL_VARIANT_PROJECTION_FILENAME).write_text(
                "corrupt_header\ncorrupt_value\n",
                encoding="utf-8",
            )
            write_run_scoring_projections(projected)
            expected_paths = {
                str(fallback): {
                    "base": str(fallback / "quote_intents_long.csv"),
                    "model_variant": str(
                        fallback / "model_variant_quote_intents_long.csv"
                    ),
                },
                str(projected): {
                    "base": str(projected / BASE_PROJECTION_FILENAME),
                    "model_variant": str(
                        projected / MODEL_VARIANT_PROJECTION_FILENAME
                    ),
                },
            }
            fallback_input_bytes = sum(
                path.stat().st_size
                for path in (
                    fallback / "quote_intents_long.csv",
                    fallback_variant_source,
                )
            )
            projected_input_bytes = sum(
                path.stat().st_size
                for path in (
                    projected / BASE_PROJECTION_FILENAME,
                    projected / MODEL_VARIANT_PROJECTION_FILENAME,
                )
            )
            expected_input_bytes = fallback_input_bytes + projected_input_bytes
            projected_canonical_bytes = (
                projected / "quote_intents_long.csv"
            ).stat().st_size
            expected_canonical_bytes = (
                fallback_input_bytes + projected_canonical_bytes
            )

            args = _args(tmp, as_of="2026-06-20T12:00:00+00:00")
            _write_exchange_snapshot(Path(args.exchange_economics_snapshot))
            with patch(
                "weather.operations.daily_refresh_trading_steps.mm_paper.build_paper_payload",
                wraps=mm_paper.build_paper_payload,
            ) as build_payload:
                result = run_maker_paper_score_step(args)
                passed_paths = build_payload.call_args.kwargs[
                    "scoring_input_paths_by_folder"
                ]
                passed_bindings = build_payload.call_args.kwargs[
                    "scoring_input_bindings_by_folder"
                ]
            payload = json.loads(
                Path(result["json_out"]).read_text(encoding="utf-8")
            )
        preflight = payload["input_preflight"]
        selected_inputs = {
            receipt["run_folder"]: receipt
            for receipt in preflight["selected_inputs"]
        }
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(passed_paths, expected_paths)
        self.assertEqual(
            {folder: receipt["input_paths"] for folder, receipt in selected_inputs.items()},
            expected_paths,
        )
        self.assertEqual(
            passed_bindings,
            {folder: receipt["input_bindings"] for folder, receipt in selected_inputs.items()},
        )
        fallback_receipt = selected_inputs[str(fallback)]
        projected_receipt = selected_inputs[str(projected)]
        self.assertEqual(fallback_receipt["input_mode"], "canonical_fallback")
        self.assertEqual(
            {
                binding.get("binding_mode")
                for binding in fallback_receipt["input_bindings"].values()
            },
            {LIVE_APPEND_PREFIX_BINDING_MODE},
        )
        self.assertTrue(
            all(
                len(binding.get("sha256") or "") == 64
                for binding in fallback_receipt["input_bindings"].values()
            )
        )
        self.assertEqual(
            fallback_receipt["projection_reason"],
            "model_variant_projection_binding_mismatch",
        )
        self.assertEqual(fallback_receipt["input_bytes"], fallback_input_bytes)
        self.assertEqual(fallback_receipt["canonical_bytes"], fallback_input_bytes)
        self.assertEqual(projected_receipt["input_mode"], "projection")
        self.assertTrue(
            all(
                "binding_mode" not in binding
                for binding in projected_receipt["input_bindings"].values()
            )
        )
        self.assertEqual(projected_receipt["input_bytes"], projected_input_bytes)
        self.assertEqual(
            projected_receipt["canonical_bytes"], projected_canonical_bytes
        )
        self.assertEqual(preflight["projection_run_count"], 1)
        self.assertEqual(preflight["canonical_fallback_run_count"], 1)
        self.assertEqual(preflight["input_file_count"], 4)
        self.assertEqual(preflight["input_bytes"], expected_input_bytes)
        self.assertEqual(preflight["canonical_input_bytes"], expected_canonical_bytes)
        self.assertEqual(
            preflight["projected_vs_canonical_byte_ratio"],
            expected_input_bytes / expected_canonical_bytes,
        )
        self.assertEqual(result["input_bytes"], expected_input_bytes)
        self.assertEqual(result["canonical_input_bytes"], expected_canonical_bytes)
        self.assertEqual(result["projection_run_count"], 1)
        self.assertEqual(result["canonical_fallback_run_count"], 1)

    def test_active_variant_shadow_step_writes_canonical_outputs_and_missing_ids(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = _recent_active_variant_row()
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
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "live_capture_enabled": False,
                        "counts_toward_weather_model_promotion": True,
                    },
                    {
                        "variant_id": "missing_v",
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "live_capture_enabled": False,
                        "counts_toward_weather_model_promotion": True,
                    },
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

    def test_recent_active_variant_row_uses_last_completed_toronto_market_date(self):
        row = _recent_active_variant_row(
            datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
        ).strip().split(",")

        self.assertEqual(row[5], "2026-07-11")
        self.assertEqual(row[-1], "2026-07-11")

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
                        "live_capture_enabled": True,
                        "counts_toward_weather_model_promotion": True,
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
                + _recent_active_variant_row(),
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
                        "live_capture_enabled": True,
                        "counts_toward_weather_model_promotion": True,
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
                "weather.reporting.candidate_lifecycle.active_variant_shadow_refresh._execute_pooled_candidate_replay_contract",
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

    def test_active_variant_shadow_step_uses_subprocess_handoff_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            backtest.mkdir(parents=True)
            registry = root / "config" / "model_variant_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps({"schema_version": "model_variant_registry_v0.1", "variants": []}),
                encoding="utf-8",
            )
            captured = {}

            def fake_child(command, **kwargs):
                captured["command"] = [str(item) for item in command]
                captured["kwargs"] = kwargs
                (backtest / "active_variant_shadow.json").write_text(
                    json.dumps({
                        "schema_version": "active_variant_shadow_refresh_v0.1",
                        "status": "OK",
                        "summary": {"source_path_count": 1, "execution_count": 1},
                        "blockers": [],
                        "registry": {"missing_active_variant_ids": []},
                        "execution": {
                            "status": "OK",
                            "source_paths": [str(backtest / "fresh_active.csv")],
                            "executions": [{"variant_id": "active_v", "status": "OK"}],
                        },
                        "evidence_window": {
                            "path": str(backtest / "active_variant_shadow_window_corpus.json"),
                            "windowed": True,
                            "window_dates": 14,
                        },
                    }),
                    encoding="utf-8",
                )
                return {
                    "command": [str(item) for item in command],
                    "returncode": 0,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "",
                    "working_set_limit": {"requested": False},
                }

            with patch(
                "weather.operations.daily_refresh_reporting_steps.run_isolated_subprocess",
                side_effect=fake_child,
            ) as child, patch(
                "weather.operations.daily_refresh_reporting_steps.active_variant_shadow_refresh.execute_registry_prediction_exports"
            ) as in_process_execute:
                result = run_active_variant_shadow_step(_args(
                    tmp,
                    variant_registry=str(registry),
                    heavy_step_subprocess=True,
                    heavy_step_working_set_max_mb=768,
                    promotion_min_artifact_free_bytes=0,
                ))

        child.assert_called_once()
        in_process_execute.assert_not_called()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["summary"]["execution_count"], 1)
        self.assertEqual(result["subprocess"]["returncode"], 0)
        self.assertEqual(captured["kwargs"]["working_set_max_bytes"], 768 * 1024 * 1024)
        self.assertIn("weather.reporting.candidate_lifecycle.active_variant_shadow_refresh", captured["command"])
        self.assertIn("--execute-registry-contracts", captured["command"])
        self.assertIn("--window-corpus-out", captured["command"])
        self.assertIn("--replay-cache", captured["command"])

    def test_active_variant_shadow_explicit_sources_bypass_registry_execution(self):
        header = (
            "variant_id,variant_family,uses_market_features,is_control,market_id,"
            "target_date,snapshot_id,band_key,probability,current_probability,"
            "recorded_probability,market_yes,outcome,artifact_hash,"
            "postprocess_config_hash,experiment_start_date\n"
        )
        row = _recent_active_variant_row()
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
                        "live_capture_enabled": True,
                        "counts_toward_weather_model_promotion": True,
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

            with patch("weather.reporting.candidate_lifecycle.active_variant_shadow_refresh.execute_registry_prediction_exports") as execute:
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
                        "live_capture_enabled": True,
                        "counts_toward_weather_model_promotion": True,
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
                "weather.reporting.candidate_lifecycle.active_variant_shadow_refresh.execute_registry_prediction_exports",
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
        with patch("weather.operations.daily_refresh_source_steps.all_specs", return_value=[FakeSpec()]), \
                patch("weather.operations.daily_refresh_source_steps.ReanalysisClient", FakeClient), \
                patch("weather.operations.daily_refresh_source_steps.ReanalysisStore", FakeStore):
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
        fake_coverage = {
            "markets": {
                "nyc": {
                    "unresolved_missing_days": ["2026-06-01"],
                    "unresolved_sparse_days": [],
                }
            },
            "summary": {
                "markets_with_unresolved_gaps": 1,
                "unresolved_issue_days": 1,
                "covered_issue_days": 0,
            },
        }

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_source_steps.data_auditor.audit_fleet_historical_data", return_value=fake_results), \
                patch("weather.operations.daily_refresh_source_steps.fleet_observability.historical_gap_coverage", return_value=fake_coverage):
            result = run_ingest_quality_gate_step(_args(tmp, ingest_quality_years="2026"))

            self.assertEqual(result["status"], "WARN")
            self.assertTrue(Path(result["json_out"]).exists())
            self.assertTrue(Path(result["report_out"]).exists())
            self.assertEqual(result["summary"]["markets_with_missing_days"], 1)
            self.assertEqual(result["summary"]["raw_markets_with_missing_days"], 1)

    def test_ingest_quality_gate_passes_when_raw_gaps_have_redundant_coverage(self):
        fake_results = {
            "nyc": {
                "missing_days": [date(2026, 6, 1)],
                "sparse_days": [(date(2026, 6, 2), 1)],
                "duplicate_timestamps": [],
                "impossible_values": [],
                "schema_errors": [],
            }
        }
        fake_coverage = {
            "markets": {
                "nyc": {
                    "unresolved_missing_days": [],
                    "unresolved_sparse_days": [],
                }
            },
            "summary": {
                "markets_with_unresolved_gaps": 0,
                "unresolved_issue_days": 0,
                "covered_issue_days": 2,
            },
        }

        with tempfile.TemporaryDirectory() as tmp, \
                patch("weather.operations.daily_refresh_source_steps.data_auditor.audit_fleet_historical_data", return_value=fake_results), \
                patch("weather.operations.daily_refresh_source_steps.fleet_observability.historical_gap_coverage", return_value=fake_coverage):
            result = run_ingest_quality_gate_step(_args(tmp, ingest_quality_years="2026"))

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["summary"]["markets_with_missing_days"], 0)
            self.assertEqual(result["summary"]["markets_with_sparse_days"], 0)
            self.assertEqual(result["summary"]["raw_markets_with_missing_days"], 1)
            self.assertEqual(result["summary"]["raw_markets_with_sparse_days"], 1)
            self.assertEqual(result["summary"]["historical_gap_covered_issue_days"], 2)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["raw_summary"]["markets_with_sparse_days"], 1)

    def test_live_variant_settlement_scorer_precedes_promotion_and_heavy_shadow(self):
        names = [name for name, _ in DEFAULT_RUNNERS]
        self.assertLess(
            names.index("live_variant_settlement_scorecard"),
            names.index("promotion_refresh"),
        )
        self.assertLess(
            names.index("live_variant_settlement_scorecard"),
            names.index("active_variant_shadow"),
        )
        self.assertIn(
            "live_variant_settlement_scorecard",
            step_names_for_stage("settlement"),
        )

    def test_live_variant_settlement_step_writes_skipped_artifacts_when_no_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                settled_analysis_target_date="2026-07-01",
            )
            result = run_live_variant_settlement_scorecard_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))
            report = Path(result["report_out"]).read_text(encoding="utf-8")

        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "no_live_variant_tape_for_target_date")
        self.assertEqual(payload["schema_version"], "live_variant_settlement_scorecard_v0.1")
        self.assertEqual(payload["blocker_count"], 0)
        self.assertIn("Status: **SKIPPED**", report)

    def test_live_variant_settlement_step_scores_only_pinned_target_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                settled_analysis_target_date="2026-07-01",
            )
            folder = Path(args.snapshots_root) / event_slug_for_date(date(2026, 7, 1), "nyc")
            folder.mkdir(parents=True)
            tape = folder / "variant_predictions_long.csv"
            fields = [
                "target_date",
                "market_id",
                "snapshot_id",
                "variant_id",
                "release_id",
                "claim_lane",
                "band_key",
                "bin_kind",
                "bin_value_c",
                "bin_value_hi_c",
                "prediction_status",
                "variant_probability",
                "market_yes",
            ]
            rows = [
                ["2026-07-01", "nyc", "s1", "candidate", "release-1", "weather_only_core_model", "lte69", "lte", 69, 69, "predicted", 0.2, 0.1],
                ["2026-07-01", "nyc", "s1", "candidate", "release-1", "weather_only_core_model", "eq70", "eq", 70, 70, "predicted", 0.6, 0.7],
                ["2026-07-01", "nyc", "s1", "candidate", "release-1", "weather_only_core_model", "gte71", "gte", 71, 71, "predicted", 0.2, 0.2],
            ]
            with tape.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerows(rows)
            (folder / "snapshots_long.csv").write_text(
                tape.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (folder / "settlement.json").write_text(
                json.dumps(
                    {
                        "target_date": "2026-07-01",
                        "market_id": "nyc",
                        "settlement_bucket": 70,
                        "promotion_countable": True,
                    }
                ),
                encoding="utf-8",
            )
            registry = Path(args.variant_registry)
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {
                        "variants": [
                            {
                                "variant_id": "candidate",
                                "lifecycle": "active",
                                "track": "no_market",
                                "roles": ["candidate"],
                                "active_for_headline": True,
                                "live_capture_enabled": True,
                                "counts_toward_weather_model_promotion": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            # A different day exists but must never enter this bounded step.
            other = Path(args.snapshots_root) / event_slug_for_date(date(2026, 6, 30), "nyc")
            other.mkdir(parents=True)
            (other / "variant_predictions_long.csv").write_text("not,read\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {"SETTLEMENT_LEDGER_ROOT": str(Path(tmp) / "settlements")},
            ):
                result = run_live_variant_settlement_scorecard_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["source_tape_count"], 1)
        self.assertEqual(result["eligible_prediction_coverage"], 1.0)
        self.assertEqual(payload["bounded_preflight"]["selected_tape_count"], 1)
        self.assertEqual(payload["bounded_preflight"]["selected_snapshot_tape_count"], 1)
        self.assertEqual(payload["configuration"]["target_date"], "2026-07-01")
        self.assertEqual(
            payload["configuration"]["expected_partition_contract"],
            "sibling_snapshot_tape",
        )
        self.assertEqual(payload["coverage"]["expected_snapshot_partition_count"], 1)
        self.assertEqual(
            payload["configuration"]["expected_variants_manifest"],
            str(registry),
        )

    def test_live_variant_settlement_preflight_blocks_missing_configured_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.csv"
            args = _args(
                tmp,
                settled_analysis_target_date="2026-07-01",
                live_variant_settlement_tapes=str(missing),
            )
            result = run_live_variant_settlement_scorecard_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(payload["first_blocker"]["code"], "configured_live_tape_missing")
        self.assertEqual(payload["bounded_preflight"]["status"], "BLOCK")

    def test_live_variant_settlement_preflight_requires_bounded_sibling_snapshot_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "snapshots" / "fixture"
            folder.mkdir(parents=True)
            tape = folder / "variant_predictions_long.csv"
            tape.write_text("variant_id\nfixture\n", encoding="utf-8")
            args = _args(
                tmp,
                settled_analysis_target_date="2026-07-01",
                live_variant_settlement_tapes=str(tape),
            )

            result = run_live_variant_settlement_scorecard_step(args)
            payload = json.loads(Path(result["json_out"]).read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(payload["bounded_preflight"]["status"], "BLOCK")
        self.assertTrue(
            any(
                row["code"] == "expected_snapshot_tape_missing"
                for row in payload["blockers"]
            )
        )

    def test_blocked_live_settlement_scorecard_prevents_promotion_work(self):
        args = _args(tempfile.gettempdir())
        args._daily_refresh_steps_so_far = [
            {
                "name": "live_variant_settlement_scorecard",
                "status": "ok",
                "result": {
                    "status": "BLOCK",
                    "blocker_count": 1,
                    "first_blocker": {"detail": "simplex mismatch"},
                    "json_out": "scorecard.json",
                },
            }
        ]
        with patch(
            "weather.operations.daily_refresh_reporting_steps.promotion_disk_preflight"
        ) as disk_preflight:
            result = run_promotion_refresh_step(args)

        disk_preflight.assert_not_called()
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["candidate_verdict"], "BLOCK")
        self.assertEqual(result["cutover_decision"], "DO_NOT_CUT_OVER")
        self.assertTrue(result["promotion_not_run"])

    def test_skipped_or_missing_live_settlement_scorecard_prevents_promotion(self):
        for prior_steps, expected_status in (
            (
                [
                    {
                        "name": "live_variant_settlement_scorecard",
                        "status": "ok",
                        "result": {
                            "status": "SKIPPED",
                            "reason": "no_live_variant_tape_for_target_date",
                        },
                    }
                ],
                "SKIPPED",
            ),
            ([], "MISSING"),
        ):
            with self.subTest(expected_status=expected_status):
                args = _args(tempfile.gettempdir())
                args._daily_refresh_steps_so_far = prior_steps
                with patch(
                    "weather.operations.daily_refresh_reporting_steps.promotion_disk_preflight"
                ) as disk_preflight:
                    result = run_promotion_refresh_step(args)
                disk_preflight.assert_not_called()
                self.assertEqual(result["status"], "BLOCK")
                self.assertEqual(result["cutover_decision"], "DO_NOT_CUT_OVER")
                self.assertEqual(
                    result["live_variant_settlement_scorecard"]["status"],
                    expected_status,
                )

    def test_live_settlement_status_is_summarized_and_rendered(self):
        steps = [
            {
                "name": "live_variant_settlement_scorecard",
                "status": "ok",
                "duration_seconds": 0.1,
                "result": {
                    "status": "BLOCK",
                    "target_date": "2026-07-01",
                    "source_tape_count": 1,
                    "eligible_partition_count": 2,
                    "valid_prediction_partition_count": 1,
                    "eligible_prediction_coverage": 0.5,
                    "expected_snapshot_partition_count": 3,
                    "missing_expected_snapshot_partition_count": 1,
                    "missing_expected_snapshot_band_count": 1,
                    "unsupported_runtime_skip_band_count": 3,
                    "blocker_count": 1,
                    "first_blocker": {"detail": "unsupported runtime"},
                },
            }
        ]
        summary = pipeline_summary(steps)
        report = render_daily_refresh_report(
            {
                "generated_at_utc": "2026-07-02T00:00:00+00:00",
                "status": "critical",
                "duration_seconds": 1,
                "steps": steps,
                "summary": summary,
            }
        )

        self.assertEqual(summary["live_variant_settlement_scorecard"]["status"], "BLOCK")
        self.assertEqual(summary["live_variant_settlement_scorecard"]["eligible_prediction_coverage"], 0.5)
        self.assertEqual(
            summary["live_variant_settlement_scorecard"][
                "missing_expected_snapshot_partition_count"
            ],
            1,
        )
        self.assertIn("## Live Variant Settlement Scorecard", report)
        self.assertIn("Missing sibling snapshots: `1`", report)
        self.assertIn("unsupported runtime", report)

    def test_live_settlement_block_is_critical_but_no_tape_skip_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "weather.operations.daily_refresh.build_rollup_freshness_status",
            return_value={"status": "PASS"},
        ):
            blocked_args = _args(
                tmp,
                disable_long_job_guard=True,
                skip_daily_progress_ledger=True,
                settled_analysis_target_date="2026-07-07",
            )
            blocked, _, _ = run_daily_refresh(
                blocked_args,
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        lambda _args: {"status": "BLOCK", "blocker_count": 1},
                    )
                ],
            )
            skipped_args = _args(
                tmp,
                status_out=str(Path(tmp) / "backtest" / "skip_status.json"),
                report_out=str(Path(tmp) / "backtest" / "skip_report.md"),
                disable_long_job_guard=True,
                skip_daily_progress_ledger=True,
                settled_analysis_target_date="2026-07-07",
            )
            skipped, _, _ = run_daily_refresh(
                skipped_args,
                runners=[
                    (
                        "settled_day_analysis_barrier",
                        lambda _args: {
                            "status": "PASS",
                            "target_date": "2026-07-07",
                        },
                    ),
                    (
                        "live_variant_settlement_scorecard",
                        lambda _args: {"status": "SKIPPED", "reason": "no_live_variant_tape_for_target_date"},
                    )
                ],
            )

        self.assertEqual(blocked["status"], "critical")
        self.assertEqual(skipped["status"], "critical")
        self.assertEqual(
            skipped["lanes"][LANE_PROMOTION]["status"], "BLOCKED"
        )


if __name__ == "__main__":
    unittest.main()
