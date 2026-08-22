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
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from weather.io import write_json_atomic
from weather.paths import data_path, repo_path
from weather.time import utc_now as shared_utc_now


from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    finalize_folders,
)
from weather.market.market_day_labels import discover_default_folders, parse_overrides
from weather.reporting.casebooks import disagreement_casebook
from weather.reporting.data_quality import data_layer_audit
from weather.reporting.data_quality import data_auditor
from weather.reporting.data_quality import data_retention_inventory
from weather.reporting.daily import daily_learning
from weather.reporting.daily import daily_progress_ledger
from weather.reporting.daily import daily_rollup_freshness
from weather.reporting.fleet import fleet_observability
from weather.reporting.scorecards import frozen_baseline_replay_trend
from weather.reporting.scorecards import live_variant_settlement_scorecard
from weather.reporting.serving_gates import production_readiness_gate
from weather.reporting.hourly import hourly_model_performance
from weather.reporting.market import market_beating_objective_scoreboard
from weather.reporting.candidate_lifecycle import model_market_disagreement_analysis
from weather.reporting.hourly import ten_minute_model_performance
from weather.reporting.candidate_lifecycle import price_free_model_learning
from weather.reporting.scorecards import progress_audit
from weather.reporting.promotion import promotion_refresh
from weather.reporting.candidate_lifecycle import active_variant_shadow_refresh
from weather.operations import replay_status_backfill
from weather.operations import event_metadata_validation
from weather.operations import daily_roll_log_hygiene
from weather.operations.capture_resource_gate import (
    DAILY_REFRESH_WORKLOAD,
    DEFAULT_MIN_DISK_HEADROOM_DAYS as DEFAULT_CAPTURE_MIN_DISK_HEADROOM_DAYS,
    DEFAULT_MIN_FREE_DISK_BYTES as DEFAULT_CAPTURE_MIN_FREE_DISK_BYTES,
    DEFAULT_MIN_FREE_MEMORY_BYTES as DEFAULT_CAPTURE_MIN_FREE_MEMORY_BYTES,
    persist_pipeline_admission,
)
from weather.reporting.candidate_lifecycle import shadow_ab_monitor
from weather.reporting.scorecards import snapshot_evaluation
from weather.reporting.scorecards import distribution_stage_attribution
from weather.reporting.scorecards import settled_day_root_cause
from weather.reporting.candidate_lifecycle import variant_evidence_growth
from weather.reporting.scorecards import winner_rank_parity
from weather.reporting.location_analysis import june23_location_bias_repair
from weather.reporting.casebooks import taker_tail_casebook
from weather.reporting.market import trading_evidence
from weather.market import exchange_economics
from weather.market import taker_bot
from weather.market.market_registry import all_specs
from weather.operations import clob_order_book_tiering
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
    process_is_running,
    run_isolated_subprocess,
    touch_long_job_guard,
)
from weather.operations.daily_refresh_resources import (
    DEFAULT_STAGE_A_MAX_COMMIT_PERCENT,
    DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB,
    STAGE_A_ISOLATED_STEPS,
    StageAChildFailure,
    StageAResourceDeferred,
    bounded_resume_command,
    build_stage_a_step_admission,
    prepare_step_child_invocation,
    serializable_step_args,
    step_resource_budget,
)
from weather.operations.daily_refresh_lanes import (
    blocked_promotion_step as _blocked_promotion_step,
    chain_target_settlement_coverage as _chain_target_settlement_coverage,
    deferred_heavy_step as _deferred_heavy_step,
    lane_summary as _lane_summary,
    promotion_lane_outcome_blocker as _promotion_lane_outcome_blocker,
    resume_carry_state as _resume_carry_state,
    settlement_barrier_blocker as _settlement_barrier_blocker,
    step_lane as _step_lane,
)
from weather.operations.producer_provenance import (
    build_invocation_proof,
    build_lock_proof,
    build_stage_sla,
    producer_release_proof,
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
DAILY_HEAVY_STEPS = frozenset({"promotion_refresh", "active_variant_shadow"})
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
    DEFAULT_HEAVY_STEP_TIMEOUT_SECONDS,
    DEFAULT_HEAVY_STEP_WORKING_SET_MAX_MB,
    DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS,
    DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES,
    DEFAULT_RUNNERS,
    LANE_LEARNING,
    LANE_PROMOTION,
    STEP_PROMOTION_GATES,
    STEP_ORDER,
    STAGE_CHOICES,
    STAGE_EVIDENCE,
    STAGE_SETTLEMENT,
    build_rollup_freshness_status,
    carried_forward_stage_head,
    casebook_args,
    filter_runners_for_resume,
    filter_runners_for_stage,
    ingest_quality_gate_status,
    pipeline_summary,
    planned_steps,
    promotion_args,
    render_ingest_quality_report,
    run_active_variant_shadow_step,
    settled_analysis_target_date,
    run_clob_order_book_tiering_step,
    run_closed_day_parquet_incremental_step,
    run_daily_learning_step,
    run_daily_flow_analysis_step,
    run_data_layer_audit_step,
    run_data_retention_inventory_step,
    run_daily_roll_log_hygiene_step,
    run_disagreement_casebook_step,
    run_distribution_stage_attribution_step,
    run_event_metadata_validation_step,
    run_exchange_economics_rule_drift_step,
    run_fleet_observability_step,
    run_frozen_baseline_replay_trend_step,
    run_hourly_model_performance_step,
    run_ingest_quality_gate_step,
    run_june23_location_bias_repair_step,
    run_live_variant_settlement_scorecard_step,
    run_market_day_labels_finalize,
    run_market_beating_objective_scoreboard_step,
    run_maker_paper_score_step,
    run_model_market_disagreement_rehydration_step,
    run_model_variant_evidence_growth_step,
    run_observed_floor_safety_monitor_step,
    run_nightly_health_checks_step,
    run_price_free_model_learning_step,
    run_proper_scoring_reliability_scorecard_step,
    run_progress_audit_step,
    run_promotion_refresh_step,
    run_public_wu_settlement_restore_step,
    run_reanalysis_recent_refresh_step,
    run_replay_status_backfill_step,
    run_runtime_identity_reconciliation_step,
    run_settled_day_analysis_barrier_step,
    run_settled_day_root_cause_step,
    run_settlement_source_audit_step,
    run_shadow_ab_monitor_step,
    run_snapshot_evaluation_step,
    run_taker_edge_permission_map_step,
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
from weather.operations.daily_refresh_bounded import (
    bounded_trigger_skip,
    bounded_planned_steps,
    build_bounded_recovery_receipt,
    enforce_bounded_resume_binding,
    select_bounded_runners,
)
from weather.operations.daily_refresh_cli_dependencies import build_cli_dependencies
from weather.operations.daily_refresh_stage_manifests import (
    DEFAULT_EVIDENCE_TASK_NAME,
    DEFAULT_STAGE_A_MANIFEST,
    DEFAULT_STAGE_B_MANIFEST,
    STAGE_MANIFEST_SCHEMA_VERSION,
    _expected_overnight_stage_a_target,
    _promotion_receipts_before,
    _read_json_payload,
    _stage_a_binding,
    _stage_a_trigger_disposition,
    _stage_b_start_gate,
    _stage_barrier_summary,
    _stage_manifest_path,
    _stage_manifest_payload,
    _step_by_name,
    _write_stage_manifest,
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


def _capture_resource_preflight(args):
    backtest_root = Path(args.backtest_root)
    out = (
        getattr(args, "capture_resource_out", "")
        or backtest_root / "capture_resource_gate.json"
    )
    report = (
        getattr(args, "capture_resource_report", "")
        or backtest_root / "capture_resource_gate.md"
    )
    return persist_pipeline_admission(
        workload=DAILY_REFRESH_WORKLOAD,
        out=out,
        report=report,
        snapshots_root=args.snapshots_root,
        disk_path=(
            getattr(args, "capture_resource_disk_path", "")
            or args.backtest_root
        ),
        capture_mode=getattr(args, "capture_resource_mode", "live"),
        active_window_start_hour=getattr(
            args,
            "capture_resource_active_window_start_hour",
            None,
        ),
        active_window_end_hour=getattr(
            args,
            "capture_resource_active_window_end_hour",
            None,
        ),
        min_free_memory_bytes=int(
            getattr(
                args,
                "capture_resource_min_free_memory_bytes",
                DEFAULT_CAPTURE_MIN_FREE_MEMORY_BYTES,
            )
        ),
        min_free_disk_bytes=int(
            getattr(
                args,
                "capture_resource_min_free_disk_bytes",
                DEFAULT_CAPTURE_MIN_FREE_DISK_BYTES,
            )
        ),
        daily_disk_growth_bytes=getattr(
            args,
            "capture_resource_daily_disk_growth_bytes",
            None,
        ),
        min_disk_headroom_days=float(
            getattr(
                args,
                "capture_resource_min_disk_headroom_days",
                DEFAULT_CAPTURE_MIN_DISK_HEADROOM_DAYS,
            )
        ),
    )


def _capture_resource_deferred_step(admission):
    summary = admission.get("summary") or {}
    enforcement = admission.get("enforcement") or {}
    return {
        "name": "capture_resource_admission",
        "status": "deferred",
        "started_at_utc": admission.get("generated_at_utc"),
        "finished_at_utc": admission.get("generated_at_utc"),
        "duration_seconds": 0.0,
        "result": {
            "status": admission.get("status"),
            "decision": admission.get("decision"),
            "admitted": admission.get("admitted"),
            "workload": admission.get("workload"),
            "blocker_count": summary.get("blocker_count"),
            "blocker_codes": [
                row.get("code") for row in admission.get("blockers") or []
            ],
            "suggested_defer_until_utc": summary.get(
                "suggested_defer_until_utc"
            ),
            "proof_path": enforcement.get("json_path"),
            "hard_stop_pipeline": True,
        },
    }


def _configured_paths(value):
    if value in (None, ""):
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    return [str(path) for path in value if str(path or "").strip()]


def _configured_name_paths(value):
    if isinstance(value, dict):
        return {str(name): Path(path) for name, path in value.items()}
    parsed = {}
    for item in value or []:
        if "=" not in str(item):
            parsed[str(item)] = Path("")
            continue
        name, path = str(item).split("=", 1)
        parsed[name.strip()] = Path(path.strip())
    return parsed


def _captured_input_parity_preflight(args, release_identity):
    backtest_root = Path(args.backtest_root)
    active_pointer = (
        getattr(args, "active_release_pointer", "")
        or production_readiness_gate.DEFAULT_ACTIVE_RELEASE_POINTER
    )
    releases_root = (
        getattr(args, "releases_root", "")
        or production_readiness_gate.DEFAULT_RELEASES_ROOT
    )
    json_out = (
        getattr(args, "captured_input_parity_out", "")
        or backtest_root / "live_variant_replay_parity.json"
    )
    report_out = (
        getattr(args, "captured_input_parity_report", "")
        or backtest_root / "live_variant_replay_parity.md"
    )
    expected_release_id = str((release_identity or {}).get("release_id") or "")
    expected_manifest_sha256 = str(
        (release_identity or {}).get("release_manifest_sha256")
        or (release_identity or {}).get("manifest_sha256")
        or ""
    )
    try:
        return live_variant_settlement_scorecard.persist_captured_input_replay_parity(
            _configured_paths(getattr(args, "captured_input_parity_served", [])),
            _configured_paths(getattr(args, "captured_input_parity_replay", [])),
            json_out=json_out,
            report_out=report_out,
            protected_paths=[active_pointer],
            protected_roots=[releases_root],
            expected_release_id=expected_release_id,
            expected_manifest_sha256=expected_manifest_sha256,
            max_input_age_hours=float(
                getattr(
                    args,
                    "captured_input_parity_max_age_hours",
                    live_variant_settlement_scorecard.DEFAULT_PARITY_MAX_INPUT_AGE_HOURS,
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 - terminal BLOCK must still persist
        return live_variant_settlement_scorecard.persist_captured_input_replay_parity_failure(
            exc,
            json_out=json_out,
            report_out=report_out,
            protected_paths=[active_pointer],
            protected_roots=[releases_root],
            expected_release_id=expected_release_id,
            expected_manifest_sha256=expected_manifest_sha256,
        )


def _captured_input_parity_deferred_step(parity):
    first = parity.get("first_mismatch") or {}
    return {
        "name": "captured_input_replay_parity",
        "status": "deferred",
        "started_at_utc": parity.get("generated_at_utc"),
        "finished_at_utc": parity.get("generated_at_utc"),
        "duration_seconds": 0.0,
        "result": {
            "status": parity.get("status"),
            "mismatch_count": (parity.get("summary") or {}).get("mismatch_count"),
            "first_mismatch": first,
            "next_action": first.get("next_action")
            or "generate exact captured-input replay rows and rerun parity",
            "proof_path": (parity.get("outputs") or {}).get("json_path"),
            "hard_stop_pipeline": True,
        },
    }


def _production_readiness_status(args):
    backtest_root = Path(args.backtest_root)
    evidence_overrides = _configured_name_paths(
        getattr(args, "production_readiness_evidence", [])
    )
    evidence_overrides["replay_parity"] = Path(
        getattr(args, "captured_input_parity_out", "")
        or backtest_root / "live_variant_replay_parity.json"
    )
    evidence_overrides["capture_resource_gate"] = Path(
        getattr(args, "capture_resource_out", "")
        or backtest_root / "capture_resource_gate.json"
    )
    gate_kwargs = {
        "pointer_path": (
            getattr(args, "active_release_pointer", "")
            or production_readiness_gate.DEFAULT_ACTIVE_RELEASE_POINTER
        ),
        "releases_root": (
            getattr(args, "releases_root", "")
            or production_readiness_gate.DEFAULT_RELEASES_ROOT
        ),
        "served_artifact_paths": _configured_name_paths(
            getattr(args, "production_readiness_served_artifact", [])
        ),
        "served_route_path": (
            getattr(args, "production_readiness_served_route", "") or None
        ),
    }
    resolver = getattr(args, "production_readiness_release_resolver", None)
    if resolver is not None:
        gate_kwargs["release_resolver"] = resolver
    payload, json_path, report_path = (
        production_readiness_gate.build_and_write_production_readiness_status(
            backtest_root=backtest_root,
            evidence_paths=evidence_overrides,
            json_out=(
                getattr(args, "production_readiness_out", "")
                or backtest_root / "production_readiness_gate.json"
            ),
            report_out=(
                getattr(args, "production_readiness_report", "")
                or backtest_root / "production_readiness_gate.md"
            ),
            **gate_kwargs,
        )
    )
    attestation = payload.get("read_only_attestation") or {}
    return {
        "status": payload.get("status"),
        "stage": payload.get("stage"),
        "blocker_count": payload.get("blocker_count"),
        "first_blocker": payload.get("first_blocker"),
        "gate_sha256": payload.get("gate_sha256"),
        "json_out": str(json_path),
        "report_out": str(report_path),
        "read_only": attestation.get("pointer_unchanged") is True,
        "pointer_mutated": (
            False
            if attestation.get("pointer_unchanged") is True
            else True
            if attestation.get("pointer_unchanged") is False
            else None
        ),
        "pointer_sha256_before": (attestation.get("pointer_before") or {}).get("sha256"),
        "pointer_sha256_after": (attestation.get("pointer_after") or {}).get("sha256"),
    }


def _flush_incremental_status(args, payload, *, fail_closed=False):
    """Best-effort mid-run status persistence.

    Crash forensics (which step was live when the process died) and the seed
    for --resume-from-step after a hard death. Never fails the run.
    """
    snapshot = dict(payload)
    snapshot["generated_at_utc"] = utc_iso()
    snapshot["lanes"] = _lane_summary(args, payload.get("steps") or [])
    snapshot["summary"] = pipeline_summary(payload.get("steps") or [])
    try:
        write_json_atomic(getattr(args, "status_out", None), snapshot)
    except (OSError, TypeError, ValueError):
        if fail_closed:
            raise


def _isolated_subprocess_receipt(result):
    return {
        key: result.get(key)
        for key in (
            "command",
            "pid",
            "returncode",
            "timed_out",
            "duration_seconds",
            "working_set_limit",
            "resource_peaks",
            "resource_io",
            "resource_limit_exceeded",
            "containment",
            "termination",
            "runner_error",
        )
    }


def _bounded_step_result_metrics(result, *, limit=96):
    """Extract bounded cardinality/byte scalars from a step result."""

    metrics = {}
    markers = ("count", "bytes", "rows", "files", "markets", "inputs", "cardinality")

    def visit(value, prefix="", depth=0):
        if len(metrics) >= int(limit) or depth > 3:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                lowered = str(key).lower()
                if (
                    isinstance(item, (int, float))
                    and not isinstance(item, bool)
                    and any(marker in lowered for marker in markers)
                ):
                    metrics[name] = item
                elif isinstance(item, (list, tuple)) and any(
                    marker in lowered for marker in markers
                ):
                    metrics[f"{name}.length"] = len(item)
                if isinstance(item, dict):
                    visit(item, name, depth + 1)

    visit(result)
    return metrics


_COMPLETED_PROGRESS_STATUSES = {"complete", "completed", "ok", "skipped"}


def _progress_snapshot(steps, total_step_count):
    completed = [
        step
        for step in (steps or [])
        if str(step.get("status") or "").lower() in _COMPLETED_PROGRESS_STATUSES
    ]
    last = completed[-1] if completed else {}
    completed_count = len(completed)
    return {
        "last_completed_step": last.get("name"),
        "last_completed_step_status": last.get("status"),
        "completed_step_count": completed_count,
        "total_step_count": max(completed_count, int(total_step_count or 0)),
    }


def _run_isolated_stage_a_step(args, payload, step_name, *, run_id):
    reserve_mb = int(
        getattr(
            args,
            "stage_a_min_available_reserve_mb",
            DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB,
        )
    )
    budget = step_resource_budget(
        step_name,
        reserve_mb=reserve_mb,
        max_commit_percent=float(
            getattr(
                args,
                "stage_a_max_commit_percent",
                DEFAULT_STAGE_A_MAX_COMMIT_PERCENT,
            )
        ),
    )
    if budget is None:
        raise StageAChildFailure(
            f"missing isolated-step resource budget for {step_name}",
            {"status": "ERROR", "step": step_name, "hard_stop_pipeline": True},
        )
    resume = bounded_resume_command(args, step_name)
    previous_steps = payload.get("steps") or []
    total_step_count = int(
        getattr(args, "_daily_refresh_total_step_count", len(previous_steps) + 1)
    )
    prior_progress = _progress_snapshot(previous_steps, total_step_count)
    admission_before = build_stage_a_step_admission(
        args,
        step_name,
        budget,
        phase="before",
    )
    resource_record = {
        "step": step_name,
        "status": "admission_pending",
        "budget": budget,
        "resume_command": resume,
        "admission_before": admission_before,
        "admission_after": None,
        "child_pid": None,
        "last_progress": prior_progress,
        "last_progress_at_utc": utc_iso(),
    }
    payload.setdefault("resource_steps", []).append(resource_record)
    setattr(args, "_daily_refresh_resource_steps", payload["resource_steps"])
    payload["status"] = "interrupted"
    payload["terminal"] = True
    payload["finished_at_utc"] = utc_iso()
    payload["current_step"] = {
        "name": step_name,
        "status": "admission",
        "child_pid": None,
        "budget": budget,
        "last_progress": resource_record["last_progress"],
        "last_progress_at_utc": resource_record["last_progress_at_utc"],
        "resume_command": resume,
    }
    payload["interruption"] = {
        "status": "RESUMABLE",
        "reason": "isolated_step_not_terminal",
        "step": step_name,
        "resume_command": resume,
        "fallback_persisted_before_child": True,
    }
    # Unlike ordinary progress updates, failure to persist this terminal
    # fallback denies the child. A hard stop must never leave status=running.
    _flush_incremental_status(args, payload, fail_closed=True)
    if admission_before.get("decision") != "ADMIT":
        resource_record["status"] = "deferred"
        payload["current_step"]["status"] = "deferred"
        payload["interruption"]["reason"] = "resource_admission_blocked"
        _flush_incremental_status(args, payload, fail_closed=True)
        raise StageAResourceDeferred(
            f"{step_name} deferred by physical-memory/capture admission",
            {
                "status": "DEFERRED",
                "resource_execution": resource_record,
                "resume_command": resume,
            },
        )

    invocation = prepare_step_child_invocation(
        args,
        step_name,
        run_id=run_id,
    )
    resource_record["child_invocation"] = {
        "args_json": invocation["args_json"],
        "result_json": invocation["result_json"],
    }

    def child_started(info):
        child_pid = int(info["pid"])
        resource_record.update({
            "status": "running",
            "child_pid": child_pid,
            "child_started_at_utc": utc_iso(),
        })
        payload["current_step"].update({
            "status": "running_isolated",
            "child_pid": child_pid,
            "last_progress_at_utc": utc_iso(),
            "child_started_before_user_code": info.get("started_before_user_code"),
        })
        payload["interruption"]["child_pid"] = child_pid
        _flush_incremental_status(args, payload, fail_closed=True)
        touch_long_job_guard(
            getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
            progress={
                "current_step": step_name,
                "child_pid": child_pid,
                "budget": budget,
                "last_completed_step": prior_progress.get("last_completed_step"),
                "resume_command": resume,
            },
        )

    child_result = run_isolated_subprocess(
        invocation["command"],
        timeout_seconds=budget["timeout_seconds"],
        working_set_max_bytes=budget["working_set_max_bytes"],
        private_memory_max_bytes=budget["private_memory_max_bytes"],
        cwd=repo_path(),
        on_started=child_started,
    )
    child_receipt = _isolated_subprocess_receipt(child_result)
    resource_record["subprocess"] = child_receipt
    result_path = Path(invocation["result_json"])
    try:
        child_payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        child_payload = {}
    resource_record["child_terminal"] = {
        key: child_payload.get(key)
        for key in (
            "schema_version",
            "status",
            "pid",
            "parent_pid",
            "started_at_utc",
            "finished_at_utc",
            "error",
        )
    }

    def _matches_recorded_pid(value):
        try:
            return int(value) == int(child_result.get("pid"))
        except (TypeError, ValueError):
            return False

    child_pid_matches = _matches_recorded_pid(child_payload.get("pid"))
    child_pid_match_mode = "direct" if child_pid_matches else None
    if not child_pid_matches and _matches_recorded_pid(child_payload.get("parent_pid")):
        # venv\Scripts\python.exe is a launcher shim: the recorded spawn PID
        # is the shim, and the receipt's os.getpid() is the real interpreter
        # exactly one hop below it. Accept that ancestry and nothing looser;
        # the receipt must still match this invocation's unique result path,
        # step, schema, and terminal fields.
        child_pid_matches = True
        child_pid_match_mode = "launcher_parent"
    child_terminal_valid = bool(
        child_payload.get("schema_version") == schema_version("daily_refresh_step_child")
        and child_payload.get("status") == "ok"
        and child_payload.get("step") == step_name
        and child_pid_matches
        and child_payload.get("finished_at_utc")
    )
    resource_record["child_terminal_validation"] = {
        "status": "PASS" if child_terminal_valid else "BLOCK",
        "schema_matches": child_payload.get("schema_version")
        == schema_version("daily_refresh_step_child"),
        "step_matches": child_payload.get("step") == step_name,
        "pid_matches": child_pid_matches,
        "pid_match_mode": child_pid_match_mode,
        "finished_at_present": bool(child_payload.get("finished_at_utc")),
    }
    admission_after = build_stage_a_step_admission(
        args,
        step_name,
        budget,
        phase="after",
    )
    resource_record["admission_after"] = admission_after

    failure_reason = None
    if child_result.get("resource_limit_exceeded"):
        failure_reason = "resource_budget_exceeded"
    elif child_result.get("timed_out"):
        failure_reason = "timeout"
    elif (child_result.get("containment") or {}).get("status") != "PASS":
        failure_reason = "containment_setup_failed"
    elif int(child_result.get("returncode") or 0) != 0:
        failure_reason = "child_nonzero_exit"
    elif not child_terminal_valid:
        failure_reason = "invalid_or_error_child_terminal"

    if failure_reason:
        resource_record.update({
            "status": "error",
            "failure_reason": failure_reason,
            "finished_at_utc": utc_iso(),
        })
        payload["current_step"]["status"] = "error"
        payload["current_step"]["failure_reason"] = failure_reason
        payload["interruption"]["reason"] = failure_reason
        _flush_incremental_status(args, payload, fail_closed=True)
        raise StageAChildFailure(
            f"{step_name} isolated child failed: {failure_reason}",
            {
                "status": "ERROR",
                "hard_stop_pipeline": True,
                "resource_execution": resource_record,
                "resume_command": resume,
                "child_error": child_payload.get("error"),
                "stderr_tail": child_result.get("stderr") or "",
            },
        )

    resource_record.update({
        "status": "ok",
        "finished_at_utc": utc_iso(),
    })
    result = child_payload.get("result")
    if not isinstance(result, dict):
        result = {"value": result}
    resource_record["result_metrics"] = _bounded_step_result_metrics(result)
    result["resource_execution"] = resource_record
    if admission_after.get("decision") != "ADMIT":
        current_index = STEP_ORDER.index(step_name)
        next_step = (
            STEP_ORDER[current_index + 1]
            if current_index + 1 < len(STEP_ORDER)
            else step_name
        )
        next_resume = bounded_resume_command(args, next_step)
        resource_record.update({
            "status": "ok_postcheck_deferred",
            "post_step_failure_reason": "post_step_capture_or_physical_check_failed",
            "next_resume_step": next_step,
            "next_resume_command": next_resume,
        })
        payload.setdefault("steps", []).append({
            "name": step_name,
            "status": "ok",
            "started_at_utc": child_payload.get("started_at_utc"),
            "finished_at_utc": child_payload.get("finished_at_utc"),
            "duration_seconds": child_receipt.get("duration_seconds"),
            "result": result,
            "persisted_before_postcheck_resume": True,
        })
        payload["status"] = "interrupted"
        payload["terminal"] = True
        payload["finished_at_utc"] = utc_iso()
        payload["current_step"] = {
            "name": next_step,
            "status": "deferred_after_completed_step",
            "last_progress": _progress_snapshot(
                payload.get("steps"),
                total_step_count,
            ),
            "last_progress_at_utc": resource_record["finished_at_utc"],
            "resume_command": next_resume,
        }
        payload["interruption"] = {
            "status": "RESUMABLE",
            "reason": "post_step_capture_or_physical_check_failed",
            "completed_step": step_name,
            "selected_resume_step": next_step,
            "resume_command": next_resume,
        }
        _flush_incremental_status(args, payload, fail_closed=True)
        return result
    payload["status"] = "running"
    payload["terminal"] = False
    payload["finished_at_utc"] = None
    payload["current_step"].update({
        "status": "ok",
        "finished_at_utc": resource_record["finished_at_utc"],
    })
    payload["last_interruption_fallback"] = payload.pop("interruption")
    return result


def _stage_name(args):
    stage = getattr(args, "stage", "all") or "all"
    if stage not in STAGE_CHOICES:
        raise ValueError(f"unknown daily refresh stage: {stage}")
    return stage


def _write_stage_skip(args, *, started, started_at, gate):
    finished = utc_iso()
    duration_seconds = round(time.time() - started, 3)
    invocation = getattr(args, "_current_producer_invocation", {}) or {}
    lock_proof = getattr(args, "_current_producer_lock_proof", {}) or {}
    release_identity = getattr(args, "_current_producer_release_identity", {}) or {}
    sla = build_stage_sla(
        duration_seconds=duration_seconds,
        limit_seconds=getattr(args, "producer_sla_seconds", 0.0),
    )
    terminal_status = (
        "critical" if gate.get("status") == "BLOCK" else "skipped"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": finished,
        "started_at_utc": started_at,
        "finished_at_utc": finished,
        "status": terminal_status,
        "terminal": True,
        "current_step": None,
        "dry_run": False,
        "runner": "daily_refresh",
        "steps": [],
        "summary": pipeline_summary([]),
        "duration_seconds": duration_seconds,
        "invocation": invocation,
        "lock_proof": lock_proof,
        "sla": sla,
        "release_identity": release_identity,
        "release_id": release_identity.get("release_id") if release_identity.get("status") == "PASS" else "",
        "release_manifest_sha256": (
            release_identity.get("release_manifest_sha256")
            if release_identity.get("status") == "PASS"
            else ""
        ),
        "release_identity_status": (
            "verified_serving_binding"
            if release_identity.get("status") == "PASS"
            else "unverified"
        ),
        "config": {
            "snapshots_root": args.snapshots_root,
            "backtest_root": args.backtest_root,
            "roadmap": args.roadmap,
            "stage": STAGE_EVIDENCE,
            "settled_analysis_target_date": getattr(args, "settled_analysis_target_date", ""),
            "stage_gate": gate,
        },
        "skip_reason": gate.get("skip_reason"),
        "stage_gate": gate,
    }
    if gate.get("skip_reason") == "stage_b_already_completed":
        status_path = Path(
            gate.get("completed_status_out") or args.status_out
        )
        report_path = Path(
            gate.get("completed_report_out") or args.report_out
        )
        payload["preserved_completed_stage_b_artifacts"] = {
            "status": "PRESERVED",
            "status_out": as_path(status_path),
            "report_out": as_path(report_path),
        }
        return payload, status_path, report_path
    status_path = write_json(args.status_out, payload)
    report_path = write_report(args.report_out, payload)
    return payload, status_path, report_path


def _trigger_evidence_stage(args, manifest):
    if getattr(args, "disable_stage_trigger", False):
        return {"status": "SKIPPED", "reason": "disable_stage_trigger"}
    task_name = getattr(args, "evidence_task_name", DEFAULT_EVIDENCE_TASK_NAME) or DEFAULT_EVIDENCE_TASK_NAME
    if os.name != "nt":
        return {"status": "SKIPPED", "reason": "non_windows", "task_name": task_name}
    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - prompt trigger is best-effort
        return {"status": "ERROR", "task_name": task_name, "error": str(exc)}
    return {
        "status": "OK" if result.returncode == 0 else "ERROR",
        "task_name": task_name,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "target_date": manifest.get("target_date"),
    }


def _run_daily_refresh_guarded(args, runners=None, long_job_guard_info=None):
    started = time.time()
    started_at = utc_iso()
    run_id = f"{started_at.replace(':', '').replace('+', '_')}-{os.getpid()}"
    invocation = build_invocation_proof(
        args,
        module_name="weather.operations.daily_refresh",
        invocation_started_at_utc=started_at,
    )
    release_identity = producer_release_proof(args)
    lock_proof = build_lock_proof(
        getattr(args, "_daily_refresh_lock_acquisition", None),
        (long_job_guard_info or {}).get("lock_acquisition"),
        prior_repair=getattr(args, "_prior_lock_repair_outcomes", None),
        required_kinds=("daily_refresh_lock", "long_job_guard_lock"),
    )
    setattr(args, "_current_producer_invocation", invocation)
    setattr(args, "_current_producer_release_identity", release_identity)
    setattr(args, "_current_producer_lock_proof", lock_proof)
    stage = _stage_name(args)
    using_default_runners = runners is None
    default_runners_by_name = dict(DEFAULT_RUNNERS)
    stage_runners = filter_runners_for_stage(
        list(runners or DEFAULT_RUNNERS), stage
    )
    resume_from = getattr(args, "resume_from_step", "") or ""
    stop_after = getattr(args, "stop_after_step", "") or ""
    bounded_stage_runners, runners, bounded_step_names = select_bounded_runners(
        stage_runners, resume_from=resume_from, stop_after=stop_after
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": None,
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "status": "running",
        "dry_run": bool(args.dry_run),
        "runner": "daily_refresh",
        "run_id": run_id,
        "owner_pid": os.getpid(),
        "steps": [],
        "resource_steps": [],
        "resume_contract": {
            "argv": list(getattr(args, "_original_cli_argv", None) or []),
            "arguments": serializable_step_args(args),
        },
        "summary": {},
        "invocation": invocation,
        "lock_proof": lock_proof,
        "sla": {
            "status": "PENDING",
            "predeclared": float(getattr(args, "producer_sla_seconds", 0.0) or 0.0) > 0,
            "limit_seconds": float(getattr(args, "producer_sla_seconds", 0.0) or 0.0) or None,
            "duration_seconds": None,
        },
        "release_identity": release_identity,
        "release_id": release_identity.get("release_id") if release_identity.get("status") == "PASS" else "",
        "release_manifest_sha256": (
            release_identity.get("release_manifest_sha256")
            if release_identity.get("status") == "PASS"
            else ""
        ),
        "release_identity_status": (
            "verified_serving_binding"
            if release_identity.get("status") == "PASS"
            else "unverified"
        ),
        "config": {
            "snapshots_root": args.snapshots_root,
            "backtest_root": args.backtest_root,
            "roadmap": args.roadmap,
            "continue_on_error": args.continue_on_error,
            "fail_on_variant_evidence_alert": getattr(args, "fail_on_variant_evidence_alert", True),
            "fail_on_hourly_performance_gate": getattr(args, "fail_on_hourly_performance_gate", True),
            "fail_on_ten_minute_performance_gate": getattr(args, "fail_on_ten_minute_performance_gate", True),
            "fail_on_live_variant_settlement_scorecard": getattr(
                args,
                "fail_on_live_variant_settlement_scorecard",
                True,
            ),
            "fail_on_daily_flow_analysis_blocker": getattr(args, "fail_on_daily_flow_analysis_blocker", False),
            "fail_on_nightly_health_critical": getattr(args, "fail_on_nightly_health_critical", False),
            "long_job_guard": long_job_guard_info or {},
            "capture_resource_mode": getattr(
                args,
                "capture_resource_mode",
                "live",
            ),
            "capture_resource_out": str(
                getattr(args, "capture_resource_out", "")
                or Path(args.backtest_root) / "capture_resource_gate.json"
            ),
            "captured_input_replay_parity_required": not getattr(
                args,
                "skip_captured_input_replay_parity",
                False,
            ),
            "captured_input_parity_out": str(
                getattr(args, "captured_input_parity_out", "")
                or Path(args.backtest_root) / "live_variant_replay_parity.json"
            ),
            "production_readiness_gate_enabled": not getattr(
                args,
                "skip_production_readiness_gate",
                False,
            ),
            "fail_on_production_readiness_block": bool(
                getattr(args, "fail_on_production_readiness_block", False)
            ),
            "resume_from_step": resume_from,
            "stop_after_step": stop_after,
            "bounded_recovery_run": bool(stop_after),
            "maker_paper_latest_active_runs": int(
                getattr(
                    args,
                    "maker_paper_latest_active_runs",
                    DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS,
                )
            ),
            "maker_paper_max_input_bytes": int(
                getattr(
                    args,
                    "maker_paper_max_input_bytes",
                    DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES,
                )
            ),
            "stage_a_min_available_reserve_mb": int(
                getattr(
                    args,
                    "stage_a_min_available_reserve_mb",
                    DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB,
                )
            ),
            "stage_a_max_commit_percent": float(
                getattr(
                    args,
                    "stage_a_max_commit_percent",
                    DEFAULT_STAGE_A_MAX_COMMIT_PERCENT,
                )
            ),
            "stage_a_isolated_steps": sorted(STAGE_A_ISOLATED_STEPS),
            "stage": stage,
            "stage_a_manifest": str(getattr(args, "stage_a_manifest", DEFAULT_STAGE_A_MANIFEST)),
            "stage_b_manifest": str(getattr(args, "stage_b_manifest", DEFAULT_STAGE_B_MANIFEST)),
        },
    }
    if not getattr(args, "settled_analysis_target_date", "") and not args.dry_run:
        # Pin the settled-analysis target once at chain start. Steps used to
        # derive it from the wall clock at their own execution time, so a
        # chain crossing midnight analyzed two different "yesterdays"
        # (2026-07-07: settled_day_root_cause ran at 01:00 and targeted 07-06
        # while every pre-midnight step targeted 07-05, failing the settled
        # target-agreement invariant and blocking the experiment queue).
        # Stage B is deliberately scheduled after midnight. Compute the only
        # current Stage-A target from the operating clock rather than trusting
        # a manifest to select its own date. Explicit operator targets still
        # win above.
        stage_a_target = (
            _expected_overnight_stage_a_target(args)
            if stage == STAGE_EVIDENCE
            else ""
        )
        args.settled_analysis_target_date = (
            stage_a_target or settled_analysis_target_date(args).isoformat()
        )
    payload["config"]["settled_analysis_target_date"] = getattr(
        args, "settled_analysis_target_date", ""
    )
    payload["resume_contract"]["arguments"]["settled_analysis_target_date"] = (
        getattr(args, "settled_analysis_target_date", "")
    )
    if stage == STAGE_EVIDENCE and not args.dry_run:
        gate = _stage_b_start_gate(args)
        payload["config"]["stage_gate"] = gate
        if gate.get("status") in {"SKIP", "BLOCK"}:
            return _write_stage_skip(args, started=started, started_at=started_at, gate=gate)
    if resume_from and not args.dry_run:
        try:
            prior = json.loads(Path(args.status_out).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
        requested_target = getattr(args, "settled_analysis_target_date", "")
        current_stage_gate = (
            (payload.get("config") or {}).get("stage_gate") or {}
        )
        current_stage_a_binding = str(
            current_stage_gate.get("stage_a_binding") or ""
        )
        current_stage_a = (
            _read_json_payload(
                getattr(args, "stage_a_manifest", DEFAULT_STAGE_A_MANIFEST)
            )
            if stage == STAGE_EVIDENCE
            else {}
        )
        carry = _resume_carry_state(
            prior,
            current_stage_a,
            stage=stage,
            resume_from_step=resume_from,
            requested_target=requested_target,
            current_stage_a_binding=current_stage_a_binding,
        )
        if enforce_bounded_resume_binding(carry, stop_after):
            runners = list(bounded_stage_runners)
            payload["config"]["resume_restarted_from_stage_start"] = True
        payload["steps"] = carry["steps"]
        payload["resource_steps"] = carry["resource_steps"]
        payload["config"]["carried_forward_target_binding"] = carry[
            "binding"
        ]
        payload["config"]["carried_forward_step_count"] = len(
            carry["steps"]
        )
        payload["config"]["carried_forward_resource_step_count"] = len(
            payload["resource_steps"]
        )
        payload["config"]["carried_forward_from_run_started_at_utc"] = (
            carry["source_started_at_utc"]
        )
    elif stage == STAGE_EVIDENCE and not args.dry_run:
        prior = _read_json_payload(getattr(args, "stage_a_manifest", DEFAULT_STAGE_A_MANIFEST))
        carried = carried_forward_stage_head(prior.get("steps"), stage)
        payload["steps"] = carried
        payload["resource_steps"] = list(prior.get("resource_steps") or [])
        payload["config"]["carried_forward_step_count"] = len(carried)
        payload["config"]["carried_forward_resource_step_count"] = len(
            payload["resource_steps"]
        )
        payload["config"]["carried_forward_from_stage"] = STAGE_SETTLEMENT
        payload["config"]["carried_forward_from_run_started_at_utc"] = prior.get("started_at_utc")
    readiness_step_declared = bool(
        not args.dry_run
        and not stop_after
        and not getattr(args, "skip_production_readiness_gate", False)
    )
    total_step_count = (
        len(payload["steps"])
        + len(runners)
        + int(readiness_step_declared)
    )
    setattr(args, "_daily_refresh_total_step_count", total_step_count)
    setattr(args, "_daily_refresh_resource_steps", payload["resource_steps"])
    capture_resource_admission = None
    capture_resource_deferred = False
    stage_a_resource_deferred = False
    captured_input_parity = None
    captured_input_parity_deferred = False
    heavy_preflight_step = None
    promotion_blocked = False
    selected_step_names = {
        step.get("name") for step in payload.get("steps") or []
    } | {name for name, _runner in runners}
    required_promotion_receipts = _promotion_receipts_before(
        "promotion_refresh",
        names=(STEP_ORDER if using_default_runners else selected_step_names),
    )
    payload["config"]["required_promotion_receipts"] = list(
        required_promotion_receipts
    )
    if args.dry_run:
        if stop_after:
            payload["steps"] = bounded_planned_steps(
                planned_steps(stage), runners
            )
        else:
            # Preserve the established dry-run contract: it describes the
            # complete selected stage even when a unit/integration caller
            # supplies custom runners that must never execute.
            payload["steps"] = planned_steps(stage)
        payload["lanes"] = _lane_summary(args, payload["steps"])
        payload["status"] = "dry_run"
    else:
        for name, runner in runners:
            lane = _step_lane(name)
            if name == "live_variant_settlement_scorecard":
                promotion_blocker = _settlement_barrier_blocker(
                    payload["steps"],
                    target_date=getattr(
                        args, "settled_analysis_target_date", ""
                    ),
                )
            elif name == "promotion_refresh":
                promotion_blocker = (
                    ((payload.get("config") or {}).get("stage_gate") or {}).get(
                        "promotion_blocker"
                    )
                    or _promotion_lane_outcome_blocker(
                        payload["steps"],
                        required_names=required_promotion_receipts,
                        target_date=getattr(
                            args, "settled_analysis_target_date", ""
                        ),
                    )
                )
            else:
                promotion_blocker = {}
            if promotion_blocker:
                step = _blocked_promotion_step(name, promotion_blocker, args)
                payload["steps"].append(step)
                _flush_incremental_status(args, payload)
                touch_long_job_guard(
                    getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
                    progress=_progress_snapshot(
                        payload.get("steps"),
                        total_step_count,
                    ),
                )
                continue
            heavy_skip_requested = bool(
                name == "active_variant_shadow"
                and getattr(args, "skip_active_variant_shadow", False)
            )
            if name in DAILY_HEAVY_STEPS and not heavy_skip_requested:
                if capture_resource_admission is None:
                    capture_resource_admission, _proof_path, _proof_report = (
                        _capture_resource_preflight(args)
                    )
                    payload["capture_resource_admission"] = (
                        capture_resource_admission
                    )
                    if capture_resource_admission.get("admitted") is not True:
                        heavy_preflight_step = _capture_resource_deferred_step(
                            capture_resource_admission
                        )
                        payload["steps"].append(heavy_preflight_step)
                        capture_resource_deferred = True
                if (
                    heavy_preflight_step is None
                    and not getattr(
                        args,
                        "skip_captured_input_replay_parity",
                        False,
                    )
                    and captured_input_parity is None
                ):
                    captured_input_parity, _parity_path, _parity_report = (
                        _captured_input_parity_preflight(
                            args,
                            payload.get("release_identity") or {},
                        )
                    )
                    payload["captured_input_replay_parity"] = (
                        captured_input_parity
                    )
                    if captured_input_parity.get("status") != "PASS":
                        heavy_preflight_step = (
                            _captured_input_parity_deferred_step(
                                captured_input_parity
                            )
                        )
                        payload["steps"].append(heavy_preflight_step)
                        captured_input_parity_deferred = True
                if heavy_preflight_step is not None:
                    step = _deferred_heavy_step(name, heavy_preflight_step)
                    payload["steps"].append(step)
                    _flush_incremental_status(args, payload)
                    touch_long_job_guard(
                        getattr(
                            args,
                            "long_job_state",
                            DEFAULT_LONG_JOB_STATE_PATH,
                        ),
                        progress=_progress_snapshot(
                            payload.get("steps"),
                            total_step_count,
                        ),
                    )
                    continue
            if lane == LANE_LEARNING:
                setattr(
                    args,
                    "_daily_refresh_chain_target_settlement_coverage",
                    _chain_target_settlement_coverage(args, payload["steps"]),
                )
            if name in {
                "market_day_labels_finalize",
                "settled_day_analysis_barrier",
                "promotion_refresh",
                "daily_learning",
                "daily_flow_analysis",
            }:
                setattr(args, "_daily_refresh_steps_so_far", list(payload["steps"]))
            if name in STAGE_A_ISOLATED_STEPS:
                setattr(args, "_daily_refresh_steps_so_far", list(payload["steps"]))
            step_runner = runner
            if (
                name in STAGE_A_ISOLATED_STEPS
                and runner is default_runners_by_name.get(name)
            ):
                step_runner = lambda step_args, step_name=name: _run_isolated_stage_a_step(
                    step_args,
                    payload,
                    step_name,
                    run_id=run_id,
                )
            try:
                step = run_step(name, step_runner, args)
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
                if lane is not None:
                    step["lane"] = lane
                    step["blocks_promotion"] = STEP_PROMOTION_GATES.get(
                        name, False
                    )
                if lane is not None and name not in STAGE_A_ISOLATED_STEPS:
                    step["contained_by_lane"] = True
                    step["lane_blocker"] = STEP_PROMOTION_GATES.get(
                        name, False
                    )
                payload["steps"].append(step)
                _flush_incremental_status(args, payload)
                touch_long_job_guard(
                    getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
                    progress=_progress_snapshot(
                        payload.get("steps"),
                        total_step_count,
                    ),
                )
                if step.get("contained_by_lane"):
                    continue
                break
            if lane is not None:
                step["lane"] = lane
                step["blocks_promotion"] = STEP_PROMOTION_GATES.get(
                    name, False
                )
            if (
                step.get("status") == "error"
                and lane is not None
                and name not in STAGE_A_ISOLATED_STEPS
            ):
                step["contained_by_lane"] = True
                step["lane_blocker"] = STEP_PROMOTION_GATES.get(name, False)
            resource_execution = (
                (step.get("result") or {}).get("resource_execution") or {}
            )
            already_persisted = bool(
                resource_execution.get("status") == "ok_postcheck_deferred"
                and payload.get("steps")
                and payload["steps"][-1].get("name") == name
                and payload["steps"][-1].get("persisted_before_postcheck_resume")
            )
            if not already_persisted:
                payload["steps"].append(step)
            # Flush after every step: the 2026-07-04 chain died mid-step with
            # no status row, no error manifest, and no crash event — an
            # end-only status write leaves a multi-hour pipeline forensically
            # blank AND unresumable past its last completed run. This write is
            # also what --resume-from-step seeds from after a hard death.
            _flush_incremental_status(args, payload)
            touch_long_job_guard(
                getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
                progress=_progress_snapshot(
                    payload.get("steps"),
                    total_step_count,
                ),
            )
            if resource_execution.get("status") == "ok_postcheck_deferred":
                stage_a_resource_deferred = True
                break
            if step["status"] == "deferred":
                stage_a_resource_deferred = True
                break
            if step["status"] == "error" and (
                not step.get("contained_by_lane")
                and (
                    not args.continue_on_error
                    or name in STAGE_A_ISOLATED_STEPS
                    or (step.get("result") or {}).get("hard_stop_pipeline")
                )
            ):
                break
        payload["lanes"] = _lane_summary(args, payload["steps"])
        errors = [
            step
            for step in payload["steps"]
            if step.get("status") == "error"
            and not step.get("contained_by_lane")
        ]
        contained_errors = [
            step
            for step in payload["steps"]
            if step.get("status") == "error"
            and step.get("contained_by_lane")
        ]
        promotion_blocked = (
            (payload.get("lanes") or {}).get(LANE_PROMOTION) or {}
        ).get("status") == "BLOCKED"
        payload["status"] = (
            "deferred"
            if capture_resource_deferred
            or captured_input_parity_deferred
            or stage_a_resource_deferred
            else "error"
            if errors
            else "critical"
            if contained_errors or promotion_blocked
            else "ok"
        )
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
        exchange_step = next((step for step in payload["steps"] if step.get("name") == "exchange_economics_rule_drift"), {})
        exchange_status = ((exchange_step.get("result") or {}).get("status"))
        if exchange_status == "BLOCK" and payload["status"] == "ok":
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
        if getattr(args, "fail_on_live_variant_settlement_scorecard", True):
            live_score_step = next(
                (
                    step
                    for step in payload["steps"]
                    if step.get("name") == "live_variant_settlement_scorecard"
                ),
                {},
            )
            live_score_status = (live_score_step.get("result") or {}).get("status")
            if live_score_status not in {None, "PASS", "SKIPPED"} and payload["status"] == "ok":
                payload["status"] = "critical"
        scoring_liveness_blockers = [
            {
                "step": step.get("name"),
                "last_scored_target_date": (step.get("result") or {}).get("last_scored_target_date"),
                "latest_settled_label_date": (step.get("result") or {}).get("latest_settled_label_date"),
                "remediation_command": (step.get("result") or {}).get("remediation_command"),
            }
            for step in payload["steps"]
            if ((step.get("result") or {}).get("scoring_liveness_status") == "BLOCK")
        ]
        if scoring_liveness_blockers:
            payload["scoring_liveness_blockers"] = scoring_liveness_blockers
            if payload["status"] == "ok":
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
    readiness_blocked_by_pipeline = bool(
        payload.get("status") in {"error", "interrupted"}
        or capture_resource_deferred
        or stage_a_resource_deferred
        or promotion_blocked
    )
    if (
        not args.dry_run
        and not stop_after
        and not getattr(args, "skip_production_readiness_gate", False)
        and not readiness_blocked_by_pipeline
    ):
        readiness_started = time.time()
        readiness_step = {
            "name": "production_readiness_gate",
            "status": "running",
            "started_at_utc": utc_iso(),
            "finished_at_utc": None,
            "duration_seconds": 0.0,
        }
        try:
            readiness_step["result"] = _production_readiness_status(args)
            readiness_step["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - final status persistence is mandatory
            readiness_step.update(
                {
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            payload["status"] = "error"
        readiness_step["finished_at_utc"] = utc_iso()
        readiness_step["duration_seconds"] = round(
            time.time() - readiness_started,
            3,
        )
        payload["steps"].append(readiness_step)
        payload["production_readiness"] = readiness_step.get("result") or {
            "status": "ERROR",
            "error": readiness_step.get("error"),
        }
        if (
            getattr(args, "fail_on_production_readiness_block", False)
            and payload["production_readiness"].get("status") != "PASS"
            and payload.get("status") != "error"
        ):
            payload["status"] = "critical"
    elif (
        not args.dry_run
        and not stop_after
        and not getattr(args, "skip_production_readiness_gate", False)
        and readiness_blocked_by_pipeline
    ):
        payload["production_readiness"] = {
            "status": "SKIPPED",
            "reason": "upstream_pipeline_not_successful",
            "pipeline_status": payload.get("status"),
        }
    if not args.dry_run:
        touch_long_job_guard(
            getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
            progress=_progress_snapshot(
                payload.get("steps"),
                total_step_count,
            ),
        )
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["terminal"] = True
    if payload.get("status") in {"ok", "critical", "dry_run", "skipped"}:
        payload["current_step"] = None
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["sla"] = build_stage_sla(
        duration_seconds=payload["duration_seconds"],
        limit_seconds=getattr(args, "producer_sla_seconds", 0.0),
    )
    payload["summary"] = pipeline_summary(payload["steps"])
    if stop_after:
        payload["bounded_recovery"] = build_bounded_recovery_receipt(
            payload,
            step_names=bounded_step_names,
            resume_from=resume_from,
            stop_after=stop_after,
            dry_run=bool(args.dry_run),
        )
        if payload["bounded_recovery"]["status"] == "BLOCK" and payload["status"] == "ok":
            payload["status"] = "error"
    progress_will_write = (
        not args.dry_run
        and not stop_after
        and not getattr(args, "skip_daily_progress_ledger", False)
    )
    rollup_overrides = {}
    if progress_will_write:
        rollup_overrides["daily_progress_latest"] = payload["generated_at_utc"]
    if stop_after:
        payload["summary"]["rollup_freshness"] = {
            "status": "SKIPPED",
            "reason": "bounded_recovery_run",
        }
    else:
        payload["summary"]["rollup_freshness"] = build_rollup_freshness_status(
            args,
            generated_at_overrides=rollup_overrides,
        )
        if payload["summary"]["rollup_freshness"].get("status") == "BLOCK" and payload["status"] == "ok":
            payload["status"] = "critical"
    if (
        not args.dry_run
        and not stop_after
        and not getattr(args, "skip_daily_progress_ledger", False)
    ):
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
    if (
        not args.dry_run
        and not stop_after
        and stage in {STAGE_SETTLEMENT, STAGE_EVIDENCE}
    ):
        try:
            _write_stage_manifest(
                args,
                payload,
                stage=stage,
                status_path=status_path,
                report_path=report_path,
            )
        except Exception as exc:  # noqa: BLE001 - publication must fail closed
            failure_at = utc_iso()
            error = f"{type(exc).__name__}: {exc}"
            payload.update({
                "status": "error",
                "terminal": True,
                "current_step": None,
                "finished_at_utc": failure_at,
                "generated_at_utc": failure_at,
                "duration_seconds": round(time.time() - started, 3),
                "stage_manifest_error": error,
                "stage_manifest_publication": {
                    "status": "ERROR",
                    "stage": stage,
                    "path": as_path(_stage_manifest_path(args, stage)),
                    "error": error,
                },
            })
            # The first status/report pair predates the publication attempt.
            # Replace both atomically-owned artifacts so no durable surface
            # can report success when the required stage manifest is absent.
            status_path = write_json(args.status_out, payload)
            report_path = write_report(args.report_out, payload)
    return payload, status_path, report_path


def trigger_evidence_stage_after_lock(args, payload):
    if skip := bounded_trigger_skip(payload.get("config") or {}):
        return skip
    config = payload.get("config") or {}
    if config.get("stage") != STAGE_SETTLEMENT:
        return {"status": "SKIPPED", "reason": "not_settlement_stage"}
    if payload.get("status") not in {"ok", "critical"}:
        return {"status": "SKIPPED", "reason": "stage_a_not_successful", "payload_status": payload.get("status")}
    if getattr(args, "disable_stage_trigger", False):
        # The scheduled topology published this final disposition in the first
        # atomic manifest write. Returning it directly is deliberately
        # idempotent: there is no second manifest write that can fail open.
        return _stage_a_trigger_disposition(args)
    path = _stage_manifest_path(args, STAGE_SETTLEMENT)
    if path is None:
        return {"status": "SKIPPED", "reason": "no_stage_a_manifest_path"}
    manifest = _read_json_payload(path)
    if not manifest:
        return {"status": "SKIPPED", "reason": "missing_stage_a_manifest", "stage_a_manifest": str(path)}
    trigger = _trigger_evidence_stage(args, manifest)
    manifest["evidence_trigger"] = trigger
    try:
        write_json_atomic(path, manifest, trailing_newline=True)
    except Exception as exc:  # noqa: BLE001 - trigger publication must fail closed
        failure_at = utc_iso()
        error = f"{type(exc).__name__}: {exc}"
        payload.update({
            "status": "error",
            "terminal": True,
            "current_step": None,
            "finished_at_utc": failure_at,
            "generated_at_utc": failure_at,
            "stage_trigger_manifest_error": error,
            "stage_trigger_manifest_publication": {
                "status": "ERROR",
                "stage": STAGE_SETTLEMENT,
                "path": as_path(path),
                "error": error,
                "trigger": trigger,
            },
        })
        status_path = write_json(args.status_out, payload)
        report_path = write_report(args.report_out, payload)
        return {
            "status": "ERROR",
            "reason": "stage_trigger_manifest_write_failed",
            "task_name": trigger.get("task_name"),
            "error": error,
            "status_out": as_path(status_path),
            "report_out": as_path(report_path),
        }
    return trigger


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
    return build_cli_dependencies(globals())


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
