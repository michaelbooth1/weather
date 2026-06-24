"""Daily settlement-to-promotion refresh automation.

This runner is intentionally thin: it executes the existing authoritative
commands in order and records one durable status artifact for operators.
"""
from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from weather.io import write_json_atomic
from weather.paths import data_path
from weather.time import utc_now as shared_utc_now

from types import SimpleNamespace

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    finalize_folders,
)
from weather.market.market_day_labels import discover_default_folders, parse_overrides
from weather.reporting import disagreement_casebook
from weather.reporting.data_quality import data_layer_audit
from weather.reporting.data_quality import data_auditor
from weather.reporting.data_quality import data_retention_inventory
from weather.reporting.daily import daily_learning
from weather.reporting.daily import daily_progress_ledger
from weather.reporting.daily import daily_rollup_freshness
from weather.reporting.fleet import fleet_observability
from weather.reporting import frozen_baseline_replay_trend
from weather.reporting import hourly_model_performance
from weather.reporting import market_beating_objective_scoreboard
from weather.reporting import ten_minute_model_performance
from weather.reporting import price_free_model_learning
from weather.reporting import progress_audit
from weather.reporting import promotion_refresh
from weather.reporting import active_variant_shadow_refresh
from weather.operations import replay_status_backfill
from weather.operations import event_metadata_validation
from weather.reporting import shadow_ab_monitor
from weather.reporting import snapshot_evaluation
from weather.reporting import distribution_stage_attribution
from weather.reporting import settled_day_root_cause
from weather.reporting import variant_evidence_growth
from weather.reporting import winner_rank_parity
from weather.reporting import taker_tail_casebook
from weather.reporting import trading_evidence
from weather.market import taker_bot
from weather.market.market_registry import all_specs
from weather.operations import clob_order_book_tiering
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
    process_is_running,
)
from weather.sources.reanalysis_history import ReanalysisClient, ReanalysisStore
from weather.schema_registry import schema_version
from weather.reporting.data_quality.artifact_disk_budget import DEFAULT_ROW_EXPORT_BYTES_PER_ROW


SCHEMA_VERSION = schema_version("daily_refresh")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_report.md"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "daily_refresh.lock"
DEFAULT_TASK_NAME = "WeatherDailySettlementPromotionRefresh"
from weather.operations.daily_refresh_locks import (
    DiskPreflightError,
    _remove_lock_if_verified_stale,
    acquire_lock,
    as_path,
    backtest_path,
    cleanup_command,
    clear_stale_long_job_state,
    lock_diagnostic,
    lock_preflight,
    long_job_state_diagnostic,
    promotion_disk_preflight,
    promotion_export_row_estimate,
    release_lock,
    resume_command,
    stale_lock_repair_command,
    utc_iso,
    utc_now,
    write_json,
)
from weather.operations.daily_refresh_steps import (
    DEFAULT_RUNNERS,
    STEP_ORDER,
    build_rollup_freshness_status,
    casebook_args,
    filter_runners_for_resume,
    ingest_quality_gate_status,
    parse_date_arg,
    pipeline_summary,
    planned_steps,
    promotion_args,
    render_ingest_quality_report,
    run_active_variant_shadow_step,
    run_clob_order_book_tiering_step,
    run_closed_day_parquet_incremental_step,
    run_daily_learning_step,
    run_daily_flow_analysis_step,
    run_data_layer_audit_step,
    run_data_retention_inventory_step,
    run_disagreement_casebook_step,
    run_distribution_stage_attribution_step,
    run_event_metadata_validation_step,
    run_fleet_observability_step,
    run_frozen_baseline_replay_trend_step,
    run_hourly_model_performance_step,
    run_ingest_quality_gate_step,
    run_market_day_labels_finalize,
    run_market_beating_objective_scoreboard_step,
    run_maker_paper_score_step,
    run_model_variant_evidence_growth_step,
    run_nightly_health_checks_step,
    run_price_free_model_learning_step,
    run_proper_scoring_reliability_scorecard_step,
    run_progress_audit_step,
    run_promotion_refresh_step,
    run_reanalysis_recent_refresh_step,
    run_replay_status_backfill_step,
    run_settled_day_root_cause_step,
    run_settlement_source_audit_step,
    run_shadow_ab_monitor_step,
    run_snapshot_evaluation_step,
    run_taker_finalization_watchdog_step,
    run_taker_tail_casebook_step,
    run_trading_evidence_step,
    run_winner_rank_parity_step,
    run_step,
    run_ten_minute_model_performance_step,
    summarize_labels,
    variant_learning_gate_from_steps,
    write_daily_progress_ledger,
    write_ingest_quality_report,
)
from weather.operations.daily_refresh_report import render_report, write_report
def run_daily_refresh(args, runners=None):
    guard_enabled = (
        not getattr(args, "dry_run", False)
        and not getattr(args, "disable_long_job_guard", False)
    )
    preflight = getattr(args, "_daily_refresh_cli_lock_preflight", None) or lock_preflight(args)
    with long_job_guard(
        "daily_refresh",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=guard_enabled,
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        guard_info = dict(guard or {})
        guard_info["preflight"] = preflight
        return _run_daily_refresh_guarded(args, runners=runners, long_job_guard_info=guard_info)


def _run_daily_refresh_guarded(args, runners=None, long_job_guard_info=None):
    started = time.time()
    started_at = utc_iso()
    runners = filter_runners_for_resume(
        list(runners or DEFAULT_RUNNERS),
        getattr(args, "resume_from_step", ""),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": None,
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "status": "running",
        "dry_run": bool(args.dry_run),
        "runner": "daily_refresh",
        "steps": [],
        "summary": {},
        "config": {
            "snapshots_root": args.snapshots_root,
            "backtest_root": args.backtest_root,
            "roadmap": args.roadmap,
            "continue_on_error": args.continue_on_error,
            "fail_on_variant_evidence_alert": getattr(args, "fail_on_variant_evidence_alert", True),
            "fail_on_hourly_performance_gate": getattr(args, "fail_on_hourly_performance_gate", True),
            "fail_on_ten_minute_performance_gate": getattr(args, "fail_on_ten_minute_performance_gate", True),
            "fail_on_daily_flow_analysis_blocker": getattr(args, "fail_on_daily_flow_analysis_blocker", False),
            "fail_on_nightly_health_critical": getattr(args, "fail_on_nightly_health_critical", False),
            "long_job_guard": long_job_guard_info or {},
            "resume_from_step": getattr(args, "resume_from_step", ""),
        },
    }
    if args.dry_run:
        payload["steps"] = planned_steps()
        payload["status"] = "dry_run"
    else:
        for name, runner in runners:
            if name in {"daily_learning", "daily_flow_analysis"}:
                setattr(args, "_daily_refresh_steps_so_far", list(payload["steps"]))
            try:
                step = run_step(name, runner, args)
            except Exception as exc:  # noqa: BLE001
                step = {
                    "name": name,
                    "status": "error",
                    "started_at_utc": utc_iso(),
                    "finished_at_utc": utc_iso(),
                    "duration_seconds": 0.0,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                payload["steps"].append(step)
                break
            payload["steps"].append(step)
            if step["status"] == "error" and not args.continue_on_error:
                break
        errors = [step for step in payload["steps"] if step.get("status") == "error"]
        payload["status"] = "error" if errors else "ok"
        if args.fail_on_fleet_critical:
            fleet_step = next((step for step in payload["steps"] if step.get("name") == "fleet_observability"), {})
            fleet_status = ((fleet_step.get("result") or {}).get("status"))
            if fleet_status == "CRITICAL" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_nightly_health_critical", False):
            health_step = next((step for step in payload["steps"] if step.get("name") == "nightly_health_checks"), {})
            health_status = ((health_step.get("result") or {}).get("status"))
            if health_status == "CRITICAL" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_ingest_quality", False):
            ingest_step = next((step for step in payload["steps"] if step.get("name") == "ingest_quality_gate"), {})
            ingest_status = ((ingest_step.get("result") or {}).get("status"))
            if ingest_status == "FAIL" and payload["status"] == "ok":
                payload["status"] = "critical"
        if args.fail_on_data_layer_audit:
            audit_step = next((step for step in payload["steps"] if step.get("name") == "data_layer_audit"), {})
            gate_status = ((audit_step.get("result") or {}).get("gate_status"))
            if gate_status == "FAIL" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_hourly_performance_gate", True):
            hourly_step = next((step for step in payload["steps"] if step.get("name") == "hourly_model_performance"), {})
            hourly_status = ((hourly_step.get("result") or {}).get("status"))
            if hourly_status == "BLOCK" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_ten_minute_performance_gate", True):
            ten_minute_step = next(
                (step for step in payload["steps"] if step.get("name") == "ten_minute_model_performance"),
                {},
            )
            ten_minute_status = ((ten_minute_step.get("result") or {}).get("status"))
            if ten_minute_status == "BLOCK" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_snapshot_evaluation", False):
            evaluation_step = next((step for step in payload["steps"] if step.get("name") == "snapshot_evaluation"), {})
            evaluation_status = ((evaluation_step.get("result") or {}).get("status"))
            if evaluation_status == "FAIL" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_shadow_ab_alert", False):
            shadow_step = next((step for step in payload["steps"] if step.get("name") == "shadow_ab_monitor"), {})
            shadow_status = ((shadow_step.get("result") or {}).get("status"))
            if shadow_status == "ALERT" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_variant_evidence_alert", True):
            variant_gate = variant_learning_gate_from_steps(payload["steps"])
            if variant_gate.get("status") == "BLOCK" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_daily_learning_blocker", False):
            learning_step = next((step for step in payload["steps"] if step.get("name") == "daily_learning"), {})
            learning_status = ((learning_step.get("result") or {}).get("status"))
            if learning_status == "BLOCKED" and payload["status"] == "ok":
                payload["status"] = "critical"
        if getattr(args, "fail_on_daily_flow_analysis_blocker", False):
            flow_step = next((step for step in payload["steps"] if step.get("name") == "daily_flow_analysis"), {})
            flow_status = ((flow_step.get("result") or {}).get("status"))
            if flow_status in {"BLOCKED", "MISSING_INPUTS"} and payload["status"] == "ok":
                payload["status"] = "critical"
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["summary"] = pipeline_summary(payload["steps"])
    progress_will_write = not args.dry_run and not getattr(args, "skip_daily_progress_ledger", False)
    rollup_overrides = {}
    if progress_will_write:
        rollup_overrides["daily_progress_latest"] = payload["generated_at_utc"]
    payload["summary"]["rollup_freshness"] = build_rollup_freshness_status(
        args,
        generated_at_overrides=rollup_overrides,
    )
    if payload["summary"]["rollup_freshness"].get("status") == "BLOCK" and payload["status"] == "ok":
        payload["status"] = "critical"
    if not args.dry_run and not getattr(args, "skip_daily_progress_ledger", False):
        try:
            payload["daily_progress_ledger"] = write_daily_progress_ledger(args, payload)
        except Exception as exc:  # noqa: BLE001 - status must still persist after refresh errors
            payload["daily_progress_ledger"] = {
                "status": "ERROR",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            payload["summary"]["rollup_freshness"] = build_rollup_freshness_status(args)
            if payload["summary"]["rollup_freshness"].get("status") == "BLOCK" and payload["status"] == "ok":
                payload["status"] = "critical"
    status_path = write_json(args.status_out, payload)
    report_path = write_report(args.report_out, payload)
    return payload, status_path, report_path


def load_status(path=DEFAULT_STATUS_OUT):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"exists": True, "path": str(path), "status": "unreadable", "error": str(exc)}
    payload["exists"] = True
    payload["path"] = str(path)
    return payload


def _cli_dependencies():
    return SimpleNamespace(
        DEFAULT_SNAPSHOTS_ROOT=DEFAULT_SNAPSHOTS_ROOT,
        DEFAULT_BACKTEST_ROOT=DEFAULT_BACKTEST_ROOT,
        DEFAULT_STATUS_OUT=DEFAULT_STATUS_OUT,
        DEFAULT_REPORT_OUT=DEFAULT_REPORT_OUT,
        DEFAULT_LOCK_PATH=DEFAULT_LOCK_PATH,
        DEFAULT_LONG_JOB_STATE_PATH=DEFAULT_LONG_JOB_STATE_PATH,
        DEFAULT_LONG_JOB_LOCK_PATH=DEFAULT_LONG_JOB_LOCK_PATH,
        DEFAULT_LABELS_CSV=DEFAULT_LABELS_CSV,
        DEFAULT_LEDGER_ROOT=DEFAULT_LEDGER_ROOT,
        STEP_ORDER=STEP_ORDER,
        progress_audit=progress_audit,
        active_variant_shadow_refresh=active_variant_shadow_refresh,
        frozen_baseline_replay_trend=frozen_baseline_replay_trend,
        hourly_model_performance=hourly_model_performance,
        ten_minute_model_performance=ten_minute_model_performance,
        settled_day_root_cause=settled_day_root_cause,
        winner_rank_parity=winner_rank_parity,
        taker_bot=taker_bot,
        taker_tail_casebook=taker_tail_casebook,
        trading_evidence=trading_evidence,
        promotion_refresh=promotion_refresh,
        clob_order_book_tiering=clob_order_book_tiering,
        fleet_observability=fleet_observability,
        data_retention_inventory=data_retention_inventory,
        run_daily_refresh=run_daily_refresh,
        load_status=load_status,
        lock_preflight=lock_preflight,
        lock_diagnostic=lock_diagnostic,
        acquire_lock=acquire_lock,
        release_lock=release_lock,
        _remove_lock_if_verified_stale=_remove_lock_if_verified_stale,
        clear_stale_long_job_state=clear_stale_long_job_state,
        utc_iso=utc_iso,
    )


def build_run_parser(parser):
    from weather.operations.daily_refresh_cli import build_run_parser as _build_run_parser
    return _build_run_parser(parser, _cli_dependencies())


def cmd_run(args):
    from weather.operations.daily_refresh_cli import cmd_run as _cmd_run
    from weather.operations.daily_refresh_cli import configure
    configure(_cli_dependencies())
    return _cmd_run(args)


def cmd_status(args):
    from weather.operations.daily_refresh_cli import cmd_status as _cmd_status
    from weather.operations.daily_refresh_cli import configure
    configure(_cli_dependencies())
    return _cmd_status(args)


def repair_stale_locks(args):
    from weather.operations.daily_refresh_cli import repair_stale_locks as _repair_stale_locks
    from weather.operations.daily_refresh_cli import configure
    configure(_cli_dependencies())
    return _repair_stale_locks(args)


def cmd_repair_stale_locks(args):
    from weather.operations.daily_refresh_cli import cmd_repair_stale_locks as _cmd_repair_stale_locks
    from weather.operations.daily_refresh_cli import configure
    configure(_cli_dependencies())
    return _cmd_repair_stale_locks(args)


def build_parser():
    from weather.operations.daily_refresh_cli import build_parser as _build_parser
    return _build_parser(_cli_dependencies())


def main(argv=None):
    from weather.operations.daily_refresh_cli import main as _main
    return _main(argv, _cli_dependencies())


if __name__ == "__main__":
    raise SystemExit(main())
