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
from weather.reporting import data_layer_audit
from weather.reporting import data_auditor
from weather.reporting import data_retention_inventory
from weather.reporting import daily_learning
from weather.reporting import daily_progress_ledger
from weather.reporting import fleet_observability
from weather.reporting import hourly_model_performance
from weather.reporting import ten_minute_model_performance
from weather.reporting import price_free_model_learning
from weather.reporting import progress_audit
from weather.reporting import promotion_refresh
from weather.reporting import active_variant_shadow_refresh
from weather.operations import replay_status_backfill
from weather.reporting import shadow_ab_monitor
from weather.reporting import snapshot_evaluation
from weather.reporting import distribution_stage_attribution
from weather.reporting import variant_evidence_growth
from weather.market.market_registry import all_specs
from weather.operations import clob_order_book_tiering
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.sources.reanalysis_history import ReanalysisClient, ReanalysisStore
from weather.schema_registry import schema_version
from weather.reporting.artifact_disk_budget import DEFAULT_ROW_EXPORT_BYTES_PER_ROW


SCHEMA_VERSION = schema_version("daily_refresh")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_report.md"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "daily_refresh.lock"
DEFAULT_TASK_NAME = "WeatherDailySettlementPromotionRefresh"
STEP_ORDER = (
    "reanalysis_recent_refresh",
    "ingest_quality_gate",
    "market_day_labels_finalize",
    "clob_order_book_tiering",
    "replay_status_backfill",
    "hourly_model_performance",
    "ten_minute_model_performance",
    "price_free_model_learning",
    "promotion_refresh",
    "shadow_ab_monitor",
    "active_variant_shadow",
    "model_variant_evidence_growth",
    "progress_audit",
    "disagreement_casebook",
    "fleet_observability",
    "data_layer_audit",
    "snapshot_evaluation",
    "distribution_stage_attribution",
    "data_retention_inventory",
    "daily_learning",
)


class DiskPreflightError(RuntimeError):
    def __init__(self, message, payload):
        super().__init__(message)
        self.payload = payload


def utc_now():
    return shared_utc_now()


def utc_iso():
    return utc_now().isoformat()


def as_path(value):
    return str(Path(value)) if value is not None else None


def backtest_path(args, name):
    return str(Path(args.backtest_root) / name)


def cleanup_command(args, target_bytes):
    root = Path(args.backtest_root)
    manifest = root / "backtest_artifact_cleanup_manifest.json"
    return (
        "python -m weather.reporting.backtest_artifact_retention "
        f"--root {root} "
        f"--cleanup-manifest {manifest} "
        f"--cleanup-target-bytes {int(max(0, target_bytes))}"
    )


def resume_command(args, step_name):
    return (
        "python -m weather.operations.daily_refresh run "
        f"--backtest-root {Path(args.backtest_root)} "
        f"--snapshots-root {Path(args.snapshots_root)} "
        f"--resume-from-step {step_name}"
    )


def _read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def promotion_export_row_estimate(args):
    payload = _read_json(backtest_path(args, "pooled_candidate_replay_latest.json"))
    aggregate = payload.get("aggregate") or {}
    rows = aggregate.get("n") or aggregate.get("rows") or 0
    try:
        return int(float(rows))
    except (TypeError, ValueError):
        return 0


def promotion_disk_preflight(args, disk_usage_fn=None):
    disk_usage_fn = disk_usage_fn or shutil.disk_usage
    out_path = Path(backtest_path(args, "f_family_promotion_refresh.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    usage = disk_usage_fn(out_path.parent)
    min_free_bytes = int(getattr(
        args,
        "promotion_min_artifact_free_bytes",
        promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
    ) or 0)
    rows = promotion_export_row_estimate(args)
    projected_export_bytes = rows * int(max(1, DEFAULT_ROW_EXPORT_BYTES_PER_ROW))
    required_free_bytes = min_free_bytes + projected_export_bytes
    free_bytes = int(getattr(usage, "free"))
    insufficient_bytes = max(0, required_free_bytes - free_bytes)
    status = "PASS" if insufficient_bytes == 0 else "BLOCK"
    return {
        "schema_version": "daily_refresh_disk_preflight_v0.1",
        "step": "promotion_refresh",
        "status": status,
        "path": str(out_path),
        "free_bytes": free_bytes,
        "total_bytes": int(getattr(usage, "total", 0)),
        "required_free_bytes": int(required_free_bytes),
        "min_free_bytes": int(min_free_bytes),
        "projected_export_bytes": int(projected_export_bytes),
        "estimated_export_rows": rows,
        "bytes_per_row": int(DEFAULT_ROW_EXPORT_BYTES_PER_ROW),
        "insufficient_bytes": int(insufficient_bytes),
        "cleanup_command": cleanup_command(args, insufficient_bytes),
        "resume_command": resume_command(args, "promotion_refresh"),
    }


def write_json(path, payload):
    return write_json_atomic(path, payload, trailing_newline=True)


def acquire_lock(path, force=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if force:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags)
    except FileExistsError:
        return None
    payload = {
        "pid": os.getpid(),
        "created_at_utc": utc_iso(),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    return path


def release_lock(path):
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def planned_steps():
    return [
        {"name": name, "status": "planned"}
        for name in STEP_ORDER
    ]


def summarize_labels(labels):
    quality_counts = Counter(label.get("quality_grade") or "unknown" for label in labels)
    reconciliation_counts = Counter(label.get("reconciliation_status") or "-" for label in labels)
    complete_by_market = Counter(
        label.get("market_id") or "unknown"
        for label in labels
        if label.get("quality_grade") == "complete"
    )
    return {
        "label_count": len(labels),
        "quality_counts": dict(sorted(quality_counts.items())),
        "reconciliation_counts": dict(sorted(reconciliation_counts.items())),
        "complete_by_market": dict(sorted(complete_by_market.items())),
    }


def parse_date_arg(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def run_reanalysis_recent_refresh_step(args):
    if args.skip_reanalysis_refresh:
        return {"skipped": True, "reason": "skip_reanalysis_refresh"}
    end_date = parse_date_arg(args.reanalysis_end_date) or (utc_now().date() - timedelta(days=1))
    start_date = end_date - timedelta(days=max(1, int(args.reanalysis_lag_days)) - 1)
    client = ReanalysisClient(timeout=args.reanalysis_timeout, sleep_seconds=args.reanalysis_sleep)
    market_rows = []
    fetched_ranges = 0
    errors = {}
    for spec in all_specs():
        store = ReanalysisStore(spec)
        before = store.coverage(start_date, end_date)
        ranges = store.missing_ranges(start_date, end_date, args.reanalysis_chunk_days)
        try:
            for chunk_start, chunk_end in ranges:
                payload = client.fetch_range(spec, chunk_start, chunk_end)
                store.write_payload(chunk_start, chunk_end, payload)
                fetched_ranges += 1
                if args.reanalysis_sleep:
                    time.sleep(args.reanalysis_sleep)
            if ranges:
                store.rebuild()
            after = store.coverage(start_date, end_date)
            market_rows.append({
                "market_id": spec.id,
                "station": spec.icao,
                "ranges_fetched": len(ranges),
                "missing_before": before.get("missing_days"),
                "missing_after": after.get("missing_days"),
                "raw_only_after": after.get("raw_only_day_count"),
            })
        except Exception as exc:  # noqa: BLE001 - archive lag must not block promotion refresh
            errors[spec.id] = f"{type(exc).__name__}: {exc}"
            market_rows.append({
                "market_id": spec.id,
                "station": spec.icao,
                "ranges_fetched": 0,
                "missing_before": before.get("missing_days"),
                "missing_after": None,
                "error": errors[spec.id],
            })
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "lag_days": int(args.reanalysis_lag_days),
        "chunk_days": int(args.reanalysis_chunk_days),
        "fetched_ranges": fetched_ranges,
        "error_count": len(errors),
        "errors": errors,
        "markets": market_rows,
    }


def _year_list(value):
    if not value:
        return None
    return [int(item) for item in str(value).split(",") if item.strip()]


def ingest_quality_gate_status(summary):
    summary = summary or {}
    fail_reasons = []
    warn_reasons = []
    if summary.get("missing_market_audits"):
        fail_reasons.append(f"{summary.get('missing_market_audits')} market audits missing")
    if summary.get("markets_with_schema_errors"):
        fail_reasons.append(f"{summary.get('markets_with_schema_errors')} markets have schema errors")
    if summary.get("markets_with_duplicates"):
        fail_reasons.append(f"{summary.get('markets_with_duplicates')} markets have duplicate timestamps")
    if summary.get("markets_with_impossible_values"):
        fail_reasons.append(f"{summary.get('markets_with_impossible_values')} markets have impossible values")
    if summary.get("markets_with_missing_days"):
        warn_reasons.append(f"{summary.get('markets_with_missing_days')} markets have missing target-window days")
    if summary.get("markets_with_sparse_days"):
        warn_reasons.append(f"{summary.get('markets_with_sparse_days')} markets have sparse target-window days")
    if fail_reasons:
        status = "FAIL"
    elif warn_reasons:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "status": status,
        "fail_reasons": fail_reasons,
        "warn_reasons": warn_reasons,
    }


def render_ingest_quality_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Ingest Quality Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
    ]
    for key in [
        "market_count",
        "missing_market_audits",
        "markets_with_schema_errors",
        "markets_with_duplicates",
        "markets_with_impossible_values",
        "markets_with_missing_days",
        "markets_with_sparse_days",
    ]:
        lines.append(f"| {key} | {summary.get(key)} |")
    lines += ["", "## Fail Reasons", ""]
    for reason in payload.get("fail_reasons") or ["-"]:
        lines.append(f"- {reason}")
    lines += ["", "## Warn Reasons", ""]
    for reason in payload.get("warn_reasons") or ["-"]:
        lines.append(f"- {reason}")
    lines += ["", "## Corruption Markets", ""]
    for market_id in summary.get("corruption_markets") or ["-"]:
        lines.append(f"- {market_id}")
    return "\n".join(lines) + "\n"


def write_ingest_quality_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ingest_quality_report(payload), encoding="utf-8")
    return path


def run_ingest_quality_gate_step(args):
    if getattr(args, "skip_ingest_quality_gate", False):
        return {"skipped": True, "reason": "skip_ingest_quality_gate"}
    years = _year_list(getattr(args, "ingest_quality_years", ""))
    results = data_auditor.audit_fleet_historical_data(
        target_month=getattr(args, "audit_target_month", None),
        target_day=getattr(args, "audit_target_day", None),
        years=years,
        quiet=True,
    )
    summary = data_auditor.audit_summary(results)
    gate = ingest_quality_gate_status(summary)
    payload = {
        "schema_version": "ingest_quality_gate_v0.1",
        "generated_at_utc": utc_iso(),
        "status": gate["status"],
        "summary": summary,
        "fail_reasons": gate["fail_reasons"],
        "warn_reasons": gate["warn_reasons"],
        "markets": {
            market_id: data_auditor.jsonable_result(result)
            for market_id, result in sorted((results or {}).items())
        },
    }
    json_out = write_json(backtest_path(args, "ingest_quality_gate.json"), payload)
    report_out = write_ingest_quality_report(
        backtest_path(args, "ingest_quality_gate_report.md"),
        payload,
    )
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "status": payload["status"],
        "summary": summary,
        "fail_reasons": gate["fail_reasons"],
        "warn_reasons": gate["warn_reasons"],
    }


def run_market_day_labels_finalize(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    labels = finalize_folders(
        folders,
        daily_summary_path=args.daily_summary or None,
        labels_csv=args.labels_csv,
        overrides=parse_overrides(args.settle),
        interval_minutes=args.interval_minutes,
        gap_tolerance=args.tolerance,
        reconcile_polymarket=not args.skip_polymarket_reconciliation,
        ledger_root=args.ledger_root,
    )
    summary = summarize_labels(labels)
    summary.update({
        "folder_count": len(folders),
        "labels_csv": as_path(args.labels_csv),
        "ledger_root": as_path(args.ledger_root),
        "polymarket_reconciliation": not args.skip_polymarket_reconciliation,
    })
    return summary


def run_clob_order_book_tiering_step(args):
    if getattr(args, "skip_clob_order_book_tiering", False):
        return {"status": "SKIPPED", "reason": "skip_clob_order_book_tiering"}
    payload = clob_order_book_tiering.run(
        snapshots_root=args.snapshots_root,
        settled_before=getattr(args, "clob_tiering_settled_before", "") or None,
        min_free_bytes=getattr(
            args,
            "clob_tiering_min_free_bytes",
            clob_order_book_tiering.DEFAULT_MIN_FREE_BYTES,
        ),
        apply=True,
        delete_source=getattr(args, "clob_tiering_delete_source", True),
        limit=getattr(args, "clob_tiering_limit", None),
    )
    json_out, report_out = clob_order_book_tiering.write_outputs(
        payload,
        backtest_path(args, "clob_order_book_tiering.json"),
        backtest_path(args, "clob_order_book_tiering_report.md"),
    )
    apply_payload = payload.get("apply") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "settled_before": payload.get("settled_before"),
        "summary": payload.get("summary") or {},
        "apply_summary": apply_payload.get("summary") or {},
        "delete_source": apply_payload.get("delete_source"),
    }


def run_replay_status_backfill_step(args):
    if getattr(args, "skip_replay_status_backfill", False):
        return {"status": "SKIPPED", "reason": "skip_replay_status_backfill"}
    payload = replay_status_backfill.build_backfill_payload(
        snapshots_root=args.snapshots_root,
        folders=args.folders if getattr(args, "folders", None) else None,
        as_of=getattr(args, "as_of", None),
        overwrite=getattr(args, "overwrite_replay_status", False),
        reconstruct_missing=getattr(args, "reconstruct_missing_replay_inputs", False),
        include_active=getattr(args, "include_active_replay_status", False),
    )
    json_out, report_out = replay_status_backfill.write_outputs(
        payload,
        json_out=backtest_path(args, "replay_status_backfill.json"),
        report_out=backtest_path(args, "replay_status_backfill_report.md"),
    )
    summary = payload.get("summary") or {}
    return {
        "status": "WARN" if summary.get("irreparable_folder_count") else "OK",
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "summary": summary,
    }


def promotion_args(args):
    parser = promotion_refresh.build_parser()
    refresh_args = parser.parse_args([])
    refresh_args.snapshots_root = args.snapshots_root
    refresh_args.as_of = args.as_of
    refresh_args.quality_grades = args.quality_grades
    refresh_args.include_reconstructed = args.include_reconstructed
    refresh_args.allow_unsettled = args.allow_unsettled
    refresh_args.skip_serving_gauntlet = args.skip_serving_gauntlet
    refresh_args.require_exact_identity = args.require_exact_identity
    refresh_args.require_all_markets = args.require_all_markets
    refresh_args.corpus_out = backtest_path(args, "promotion_corpus.json")
    refresh_args.trust_out = backtest_path(args, "location_trust.json")
    refresh_args.candidate_report = backtest_path(args, "pooled_candidate_replay_latest_report.md")
    refresh_args.candidate_json = backtest_path(args, "pooled_candidate_replay_latest.json")
    refresh_args.current_replay_report = backtest_path(args, "pooled_candidate_current_replay_latest_report.md")
    refresh_args.serving_gauntlet_report = backtest_path(args, "promotion_gauntlet_latest_report.md")
    refresh_args.serving_replay_report = backtest_path(args, "promotion_replay_latest_report.md")
    refresh_args.hourly_performance_report = backtest_path(args, "hourly_model_performance.json")
    refresh_args.ten_minute_performance_report = backtest_path(args, "ten_minute_model_performance.json")
    refresh_args.candidate_ten_minute_performance_report = backtest_path(args, "ten_minute_model_performance.json")
    refresh_args.out = backtest_path(args, "f_family_promotion_refresh.json")
    refresh_args.report = backtest_path(args, "f_family_promotion_refresh_report.md")
    refresh_args.min_artifact_free_bytes = getattr(
        args,
        "promotion_min_artifact_free_bytes",
        getattr(refresh_args, "min_artifact_free_bytes", promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES),
    )
    return refresh_args


def run_promotion_refresh_step(args):
    disk_preflight = promotion_disk_preflight(args, disk_usage_fn=getattr(args, "disk_usage_fn", None))
    if disk_preflight["status"] == "BLOCK":
        raise DiskPreflightError(
            (
                "insufficient disk headroom before promotion_refresh: "
                f"free_bytes={disk_preflight['free_bytes']}, "
                f"required_free_bytes={disk_preflight['required_free_bytes']}"
            ),
            {
                "status": "BLOCK",
                "root_cause_class": "blocked_by_disk",
                "disk_preflight": disk_preflight,
                "resume_command": disk_preflight["resume_command"],
                "cleanup_command": disk_preflight["cleanup_command"],
                "no_partial_export": True,
            },
        )
    payload, out_path, report_path = promotion_refresh.run_promotion_refresh(promotion_args(args))
    decisions = payload.get("decisions") or {}
    candidate = payload.get("candidate") or {}
    aggregate = candidate.get("aggregate") or {}
    corpus = payload.get("corpus") or {}
    return {
        "status": payload.get("status") or "OK",
        "disk_preflight": disk_preflight,
        "resume_command": disk_preflight["resume_command"],
        "json_out": as_path(out_path),
        "report_out": as_path(report_path),
        "candidate_verdict": candidate.get("verdict"),
        "candidate_market_verdict": candidate.get("candidate_market_verdict"),
        "cutover_decision": candidate.get("cutover_decision"),
        "action_counts": decisions.get("action_counts") or {},
        "promote_markets": decisions.get("promote_markets") or [],
        "shadow_markets": decisions.get("shadow_markets") or [],
        "blocked_markets": decisions.get("blocked_markets") or [],
        "corpus_market_days": corpus.get("market_day_count"),
        "corpus_snapshots": corpus.get("snapshot_count"),
        "corpus_band_rows": corpus.get("band_row_count"),
        "candidate_brier": aggregate.get("candidate_brier"),
        "current_brier": aggregate.get("current_brier"),
        "market_brier": aggregate.get("market_brier"),
        "serving_gauntlet_verdict": (payload.get("serving_gauntlet") or {}).get("verdict"),
    }


def run_hourly_model_performance_step(args):
    if getattr(args, "skip_hourly_model_performance", False):
        return {"status": "SKIPPED", "reason": "skip_hourly_model_performance"}
    payload = hourly_model_performance.build_hourly_performance(
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        snapshots_root=args.snapshots_root,
        context_root=args.backtest_root,
        quality_grades=hourly_model_performance.parse_quality_grades(args.quality_grades),
        min_rows=getattr(args, "hourly_min_rows", hourly_model_performance.DEFAULT_MIN_ROWS),
        top_hours=getattr(args, "hourly_top_hours", hourly_model_performance.DEFAULT_TOP_HOURS),
        min_regime_market_days=getattr(
            args,
            "hourly_min_regime_market_days",
            hourly_model_performance.DEFAULT_MIN_REGIME_MARKET_DAYS,
        ),
        early_brier_regression_tolerance=getattr(
            args,
            "hourly_early_brier_regression_tolerance",
            hourly_model_performance.DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
        ),
        early_logloss_regression_tolerance=getattr(
            args,
            "hourly_early_logloss_regression_tolerance",
            hourly_model_performance.DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
        ),
        early_ece_max=getattr(args, "hourly_early_ece_max", hourly_model_performance.DEFAULT_EARLY_ECE_MAX),
    )
    json_out, report_out, csv_out = hourly_model_performance.write_outputs(
        payload,
        json_out=backtest_path(args, "hourly_model_performance.json"),
        report_out=backtest_path(args, "hourly_model_performance_report.md"),
        csv_out=backtest_path(args, "hourly_model_performance_by_hour.csv"),
    )
    gate = payload.get("hourly_performance_gate") or {}
    registry = payload.get("remediation_registry") or {}
    return {
        "status": gate.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "csv_out": as_path(csv_out),
        "daily_summary": payload.get("daily_summary") or {},
        "hourly_performance_gate": gate,
        "remediation_registry_summary": registry.get("summary") or {},
    }


def run_ten_minute_model_performance_step(args):
    if getattr(args, "skip_ten_minute_model_performance", False):
        return {"status": "SKIPPED", "reason": "skip_ten_minute_model_performance"}
    payload = ten_minute_model_performance.build_ten_minute_performance(
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        snapshots_root=args.snapshots_root,
        quality_grades=getattr(args, "quality_grades", ",".join(ten_minute_model_performance.DEFAULT_QUALITY_GRADES)),
        markets=getattr(args, "markets", ""),
        min_rows=getattr(args, "ten_minute_min_rows", ten_minute_model_performance.DEFAULT_MIN_ROWS),
        top_slots=getattr(args, "ten_minute_top_slots", ten_minute_model_performance.DEFAULT_TOP_SLOTS),
        item147_rows=getattr(args, "ten_minute_candidate_rows", ten_minute_model_performance.DEFAULT_ITEM147_ROWS),
        min_weak_market_days=getattr(
            args,
            "ten_minute_min_weak_market_days",
            ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
        ),
        weak_brier_regression_tolerance=getattr(
            args,
            "ten_minute_weak_brier_regression_tolerance",
            ten_minute_model_performance.DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
        ),
        weak_logloss_regression_tolerance=getattr(
            args,
            "ten_minute_weak_logloss_regression_tolerance",
            ten_minute_model_performance.DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
        ),
        candidate_min_weak_market_days=getattr(
            args,
            "ten_minute_candidate_min_weak_market_days",
            ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
        ),
        candidate_weak_brier_improvement_min=getattr(
            args,
            "ten_minute_candidate_weak_brier_improvement_min",
            ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
        ),
        candidate_weak_market_regression_tolerance=getattr(
            args,
            "ten_minute_candidate_weak_market_regression_tolerance",
            ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
        ),
        candidate_weak_logloss_regression_tolerance=getattr(
            args,
            "ten_minute_candidate_weak_logloss_regression_tolerance",
            ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
        ),
    )
    json_out, report_out, csv_out, candidate_csv_out = ten_minute_model_performance.write_outputs(
        payload,
        json_out=backtest_path(args, "ten_minute_model_performance.json"),
        report_out=backtest_path(args, "ten_minute_model_performance_report.md"),
        slot_csv_out=backtest_path(args, "ten_minute_model_performance_by_slot.csv"),
        candidate_csv_out=backtest_path(args, "ten_minute_item147_candidate_by_slot.csv"),
    )
    gate = payload.get("ten_minute_performance_gate") or {}
    candidate_gate = payload.get("candidate_ten_minute_gate") or {}
    return {
        "status": gate.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "csv_out": as_path(csv_out),
        "candidate_csv_out": as_path(candidate_csv_out) if candidate_csv_out else None,
        "daily_summary": payload.get("daily_summary") or {},
        "ten_minute_performance_gate": gate,
        "candidate_ten_minute_gate": candidate_gate,
        "weak_slots": (payload.get("weak_slots") or {}).get("slot_labels") or [],
        "variant_ids": payload.get("variant_ids") or [],
    }


def run_price_free_model_learning_step(args):
    if getattr(args, "skip_price_free_model_learning", False):
        return {"status": "SKIPPED", "reason": "skip_price_free_model_learning"}
    payload = price_free_model_learning.build_price_free_learning(
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        snapshots_root=args.snapshots_root,
        quality_grades=price_free_model_learning.parse_quality_grades(
            getattr(args, "quality_grades", ",".join(price_free_model_learning.DEFAULT_QUALITY_GRADES))
        ),
        markets=price_free_model_learning.parse_csv_values(getattr(args, "markets", "")),
    )
    json_out, report_out, hourly_csv_out, current_max_csv_out = price_free_model_learning.write_outputs(
        payload,
        json_out=backtest_path(args, "price_free_model_learning.json"),
        report_out=backtest_path(args, "price_free_model_learning_report.md"),
        hourly_csv_out=backtest_path(args, "price_free_model_learning_by_hour.csv"),
        current_max_csv_out=backtest_path(args, "price_free_model_learning_current_max_carryover.csv"),
    )
    current_max = payload.get("current_max_carryover") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "hourly_csv_out": as_path(hourly_csv_out),
        "current_max_csv_out": as_path(current_max_csv_out),
        "daily_summary": payload.get("daily_summary") or {},
        "corpus": payload.get("corpus") or {},
        "current_max_carryover_summary": current_max.get("summary") or {},
    }


def run_shadow_ab_monitor_step(args):
    if getattr(args, "skip_shadow_ab_monitor", False):
        return {"status": "SKIPPED", "reason": "skip_shadow_ab_monitor"}
    payload = shadow_ab_monitor.build_monitor(
        promotion_refresh=backtest_path(args, "f_family_promotion_refresh.json"),
        candidate_replay=backtest_path(args, "pooled_candidate_replay_latest.json"),
        current_tol=getattr(args, "ab_current_tol", 0.003),
        market_tol=getattr(args, "ab_market_tol", 0.003),
    )
    json_out = shadow_ab_monitor.write_json(backtest_path(args, "shadow_ab_monitor.json"), payload)
    report_out = shadow_ab_monitor.write_report(backtest_path(args, "shadow_ab_monitor_report.md"), payload)
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "summary": payload.get("summary") or {},
    }


def _variant_evidence_paths(args, attr, default_name):
    value = getattr(args, attr, "") or ""
    if value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [backtest_path(args, default_name)]


def run_active_variant_shadow_step(args):
    if getattr(args, "skip_active_variant_shadow", False):
        return {"status": "SKIPPED", "reason": "skip_active_variant_shadow"}
    source_paths = _variant_evidence_paths(
        args,
        "active_variant_shadow_sources",
        "",
    )
    if source_paths == [backtest_path(args, "")]:
        source_paths = []
    execution = {}
    if not source_paths:
        execution = active_variant_shadow_refresh.execute_registry_prediction_exports(
            registry_path=getattr(args, "variant_registry", active_variant_shadow_refresh.DEFAULT_REGISTRY_PATH),
            corpus_path=backtest_path(args, "promotion_corpus.json"),
            snapshots_root=getattr(args, "snapshots_root", None),
            out_dir=backtest_path(args, "active_variant_shadow_runs"),
            min_artifact_free_bytes=getattr(args, "promotion_min_artifact_free_bytes", 0),
            current_tol=getattr(args, "current_tol", 0.003),
            market_tol=getattr(args, "market_tol", 0.003),
            min_days=getattr(args, "min_days", 2),
            min_trust=getattr(args, "min_trust", 25),
            require_exact_identity=getattr(args, "require_exact_identity", False),
            require_all_markets=getattr(args, "require_all_markets", False),
        )
        source_paths = execution.get("source_paths") or []
    payload = active_variant_shadow_refresh.build_payload(
        source_paths,
        registry_path=getattr(args, "variant_registry", active_variant_shadow_refresh.DEFAULT_REGISTRY_PATH),
        execution=execution,
    )
    long_out, attribution_sidecar_out, json_out, report_out = active_variant_shadow_refresh.write_outputs(
        payload,
        long_out=backtest_path(args, "active_variant_shadow_long.csv"),
        attribution_sidecar_out=backtest_path(args, "active_variant_shadow_attribution.jsonl"),
        json_out=backtest_path(args, "active_variant_shadow.json"),
        report_out=backtest_path(args, "active_variant_shadow_report.md"),
    )
    return {
        "status": payload.get("status"),
        "long_out": as_path(long_out),
        "attribution_sidecar_out": as_path(attribution_sidecar_out),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "summary": payload.get("summary") or {},
        "blockers": payload.get("blockers") or [],
        "missing_active_variant_ids": (payload.get("registry") or {}).get("missing_active_variant_ids") or [],
        "execution": execution,
    }


def run_model_variant_evidence_growth_step(args):
    if getattr(args, "skip_model_variant_evidence_growth", False):
        return {"status": "SKIPPED", "reason": "skip_model_variant_evidence_growth"}
    current_paths = _variant_evidence_paths(
        args,
        "variant_evidence_current",
        "active_variant_shadow_long.csv",
    )
    baseline_paths = _variant_evidence_paths(
        args,
        "variant_evidence_baseline",
        "item70_71_full_multi_variant_shadow_long.csv",
    )
    missing_current = [path for path in current_paths if not Path(path).exists()]
    if missing_current:
        return {
            "status": "SKIPPED",
            "reason": "missing_current_variant_evidence",
            "missing_paths": missing_current,
        }
    existing_baseline = [path for path in baseline_paths if Path(path).exists()]
    raw_rows = variant_evidence_growth.read_prediction_rows(current_paths)
    baseline_rows = (
        variant_evidence_growth.read_prediction_rows(existing_baseline)
        if existing_baseline else None
    )
    payload = variant_evidence_growth.build_payload(
        raw_rows,
        baseline_rows=baseline_rows,
        input_paths=current_paths,
        baseline_paths=existing_baseline,
        min_unique_observation_increment=getattr(
            args,
            "variant_evidence_min_unique_observations",
            1,
        ),
        min_market_day_increment=getattr(args, "variant_evidence_min_market_days", 1),
        rolling_7d_min_market_days=getattr(args, "variant_evidence_rolling_7d_min_market_days", 1),
        per_shadow_market_min_market_days=getattr(args, "variant_evidence_per_shadow_market_min_days", 4),
    )
    json_out = variant_evidence_growth.write_json(
        backtest_path(args, "model_variant_evidence_growth.json"),
        payload,
    )
    report_out = variant_evidence_growth.write_report(
        backtest_path(args, "model_variant_evidence_growth_report.md"),
        payload,
    )
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "summary": payload.get("summary") or {},
        "delta_vs_baseline": payload.get("delta_vs_baseline"),
        "evidence_sla": payload.get("evidence_sla") or {},
        "no_growth_reasons": payload.get("no_growth_reasons") or [],
        "trend": payload.get("trend") or [],
        "alerts": payload.get("alerts") or [],
    }


def run_progress_audit_step(args):
    payload = progress_audit.build_audit(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        roadmap_path=args.roadmap,
    )
    json_out, report_out = progress_audit.write_outputs(
        payload,
        json_out=backtest_path(args, "progress_audit.json"),
        report_out=backtest_path(args, "progress_audit_report.md"),
    )
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "answer": (payload.get("trend_assessment") or {}).get("answer"),
        "fleet_status": ((payload.get("fleet_observability") or {}).get("status")),
        "market_day_labels": payload.get("market_day_labels") or {},
        "promotion_refresh": payload.get("promotion_refresh") or {},
    }


def casebook_args(args):
    parser = disagreement_casebook.build_arg_parser()
    case_args = parser.parse_args([])
    case_args.snapshots_root = args.snapshots_root
    case_args.backtest_root = args.backtest_root
    case_args.json_out = backtest_path(args, "disagreement_casebook.json")
    case_args.report_out = backtest_path(args, "disagreement_casebook_report.md")
    case_args.operator_out = backtest_path(args, "disagreement_operator_report.md")
    case_args.include_clob = not args.no_clob_casebook
    return case_args


def run_disagreement_casebook_step(args):
    case_args = casebook_args(args)
    payload = disagreement_casebook.build_casebook(
        folders=case_args.folders,
        snapshots_root=case_args.snapshots_root,
        backtest_root=case_args.backtest_root,
        args=case_args,
    )
    json_out, report_out, operator_out = disagreement_casebook.write_outputs(
        payload,
        case_args.json_out,
        case_args.report_out,
        case_args.operator_out,
    )
    summary = payload.get("summary") or {}
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "operator_out": as_path(operator_out),
        "case_count": summary.get("case_count"),
        "settled_case_count": summary.get("settled_case_count"),
        "open_case_count": summary.get("open_case_count"),
        "model_win_count": summary.get("model_win_count"),
        "model_loss_count": summary.get("model_loss_count"),
        "taxonomy_counts": summary.get("taxonomy_counts") or {},
    }


def run_fleet_observability_step(args):
    years = [int(item) for item in args.audit_years.split(",") if item.strip()] if args.audit_years else None
    payload = fleet_observability.build_observability_payload(
        snapshots_root=Path(args.snapshots_root),
        interval_minutes=args.collection_interval_minutes,
        tolerance=args.collection_tolerance,
        target_month=args.audit_target_month,
        target_day=args.audit_target_day,
        years=years,
        include_audits=not args.skip_historical_audits,
        tape_backup_root=getattr(args, "tape_backup_root", fleet_observability.tape_backup.DEFAULT_BACKUP_ROOT),
        verify_tape_backup_checksums=getattr(args, "verify_tape_backup_checksums", False),
    )
    json_out = fleet_observability.write_json(backtest_path(args, "fleet_observability.json"), payload)
    report_out = fleet_observability.write_markdown(backtest_path(args, "fleet_observability_report.md"), payload)
    provenance_out = fleet_observability.write_json(
        backtest_path(args, "artifact_provenance_manifest.json"),
        payload["artifact_provenance"],
    )
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "provenance_out": as_path(provenance_out),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "tape_backup_status": ((payload.get("tape_backup") or {}).get("status")),
        "collection_states": ((payload.get("collection") or {}).get("summary") or {}).get("states") or {},
    }


def run_data_layer_audit_step(args):
    if args.skip_data_layer_audit:
        return {"skipped": True, "reason": "skip_data_layer_audit"}
    payload = data_layer_audit.build_audit(
        snapshots_root=Path(args.snapshots_root),
        backtest_root=Path(args.backtest_root),
        interval_minutes=args.collection_interval_minutes,
        tolerance=args.collection_tolerance,
        historical_start=data_layer_audit.parse_date(args.data_layer_historical_start),
        historical_end=data_layer_audit.parse_date(args.data_layer_historical_end),
    )
    json_out = data_layer_audit.write_json(backtest_path(args, "data_layer_audit.json"), payload)
    report_out = data_layer_audit.write_report(backtest_path(args, "data_layer_audit_report.md"), payload)
    gate_summary = payload.get("gate_summary") or {}
    rec_counts = Counter(item.get("priority") for item in payload.get("recommendations") or [])
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "gate_status": gate_summary.get("status"),
        "gate_summary": gate_summary,
        "recommendation_counts": dict(sorted(rec_counts.items())),
    }


def run_snapshot_evaluation_step(args):
    payload = snapshot_evaluation.build_evaluation(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
    )
    json_out, report_out = snapshot_evaluation.write_outputs(
        payload,
        json_out=backtest_path(args, "snapshot_evaluation.json"),
        report_out=backtest_path(args, "snapshot_evaluation_report.md"),
    )
    status = payload.get("status") or {}
    inventory = payload.get("snapshot_inventory") or {}
    backlog = payload.get("improvement_backlog") or {}
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "status": status.get("status"),
        "gate_counts": status,
        "snapshot_folders": inventory.get("folder_count"),
        "snapshots": inventory.get("snapshot_count"),
        "band_rows": inventory.get("band_row_count"),
        "top_gap_count": len(backlog.get("top_slices") or []),
    }


def run_distribution_stage_attribution_step(args):
    payload = distribution_stage_attribution.build_payload(
        snapshots_root=args.snapshots_root,
        min_stage_rows=getattr(args, "distribution_stage_min_rows", 20),
    )
    json_out, report_out = distribution_stage_attribution.write_outputs(
        payload,
        json_out=backtest_path(args, "distribution_stage_attribution.json"),
        report_out=backtest_path(args, "distribution_stage_attribution_report.md"),
    )
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "status": payload.get("status"),
        "folder_count": payload.get("folder_count"),
        "settled_folder_count": payload.get("settled_folder_count"),
        "attribution_row_count": payload.get("attribution_row_count"),
        "net_negative_stage_count": (payload.get("summary") or {}).get("net_negative_stage_count"),
        "top_net_negative_stage": (payload.get("summary") or {}).get("top_net_negative_stage"),
    }


def run_data_retention_inventory_step(args):
    if getattr(args, "skip_data_retention_inventory", False):
        return {"status": "SKIPPED", "reason": "skip_data_retention_inventory"}
    root = getattr(args, "data_root", "") or str(Path(args.backtest_root).parent)
    payload = data_retention_inventory.build_payload(
        root=root,
        backup_status_path=Path(args.backtest_root) / "tape_backup_status.json",
        min_free_bytes=getattr(
            args,
            "data_retention_min_free_bytes",
            data_retention_inventory.DEFAULT_MIN_FREE_BYTES,
        ),
        lookback_hours=getattr(
            args,
            "data_retention_lookback_hours",
            data_retention_inventory.DEFAULT_LOOKBACK_HOURS,
        ),
        top_n=getattr(args, "data_retention_top_n", data_retention_inventory.DEFAULT_TOP_N),
    )
    json_out = data_retention_inventory.write_json(
        backtest_path(args, "data_retention_inventory.json"),
        payload,
    )
    report_out = data_retention_inventory.write_report(
        backtest_path(args, "data_retention_inventory_report.md"),
        payload,
    )
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "summary": payload.get("summary"),
        "disk": payload.get("disk"),
        "backup_status": payload.get("backup_status"),
    }


def run_daily_learning_step(args):
    if getattr(args, "skip_daily_learning", False):
        return {"status": "SKIPPED", "reason": "skip_daily_learning"}
    steps_so_far = getattr(args, "_daily_refresh_steps_so_far", None) or []
    daily_refresh_summary = pipeline_summary(steps_so_far) if steps_so_far else None
    payload = daily_learning.build_learning_payload(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=getattr(args, "as_of", None),
        daily_refresh_summary=daily_refresh_summary,
    )
    json_out, report_out = daily_learning.write_outputs(
        payload,
        json_out=backtest_path(args, "daily_learning.json"),
        report_out=backtest_path(args, "daily_learning_report.md"),
    )
    summary = payload.get("summary") or {}
    retrain_plan = payload.get("retrain_plan") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "learning_count": summary.get("learning_count"),
        "blocker_count": summary.get("blocker_count"),
        "high_priority_learning_count": summary.get("high_priority_learning_count"),
        "retrain_input_count": summary.get("retrain_input_count"),
        "training_ready": retrain_plan.get("training_ready"),
        "promotion_ready": retrain_plan.get("promotion_ready"),
    }


def write_daily_progress_ledger(args, daily_refresh_payload):
    row = daily_progress_ledger.build_progress_row(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        daily_refresh_status=daily_refresh_payload,
        generated_at_utc=daily_refresh_payload.get("generated_at_utc"),
    )
    return daily_progress_ledger.write_progress_outputs(
        row,
        jsonl_out=backtest_path(args, "daily_progress_ledger.jsonl"),
        csv_out=backtest_path(args, "daily_progress_ledger.csv"),
        latest_out=backtest_path(args, "daily_progress_latest.json"),
        report_out=backtest_path(args, "daily_progress_ledger_report.md"),
    )


DEFAULT_RUNNERS = (
    ("reanalysis_recent_refresh", run_reanalysis_recent_refresh_step),
    ("ingest_quality_gate", run_ingest_quality_gate_step),
    ("market_day_labels_finalize", run_market_day_labels_finalize),
    ("clob_order_book_tiering", run_clob_order_book_tiering_step),
    ("replay_status_backfill", run_replay_status_backfill_step),
    ("hourly_model_performance", run_hourly_model_performance_step),
    ("ten_minute_model_performance", run_ten_minute_model_performance_step),
    ("price_free_model_learning", run_price_free_model_learning_step),
    ("promotion_refresh", run_promotion_refresh_step),
    ("shadow_ab_monitor", run_shadow_ab_monitor_step),
    ("active_variant_shadow", run_active_variant_shadow_step),
    ("model_variant_evidence_growth", run_model_variant_evidence_growth_step),
    ("progress_audit", run_progress_audit_step),
    ("disagreement_casebook", run_disagreement_casebook_step),
    ("fleet_observability", run_fleet_observability_step),
    ("data_layer_audit", run_data_layer_audit_step),
    ("snapshot_evaluation", run_snapshot_evaluation_step),
    ("distribution_stage_attribution", run_distribution_stage_attribution_step),
    ("data_retention_inventory", run_data_retention_inventory_step),
    ("daily_learning", run_daily_learning_step),
)


def run_step(name, runner, args):
    started = time.time()
    row = {
        "name": name,
        "status": "running",
        "started_at_utc": utc_iso(),
    }
    try:
        row["result"] = runner(args)
        row["status"] = "ok"
    except DiskPreflightError as exc:
        row["status"] = "error"
        row["error"] = str(exc)
        row["root_cause_class"] = "blocked_by_disk"
        row["result"] = exc.payload
    except Exception as exc:  # noqa: BLE001
        row["status"] = "error"
        row["error"] = str(exc)
        row["traceback"] = traceback.format_exc()
        if not args.continue_on_error:
            raise
    finally:
        row["finished_at_utc"] = utc_iso()
        row["duration_seconds"] = round(time.time() - started, 3)
    return row


def pipeline_summary(steps):
    by_name = {step["name"]: step for step in steps}
    ingest = ((by_name.get("ingest_quality_gate") or {}).get("result") or {})
    finalize = ((by_name.get("market_day_labels_finalize") or {}).get("result") or {})
    clob_tiering = ((by_name.get("clob_order_book_tiering") or {}).get("result") or {})
    replay_backfill = ((by_name.get("replay_status_backfill") or {}).get("result") or {})
    promotion = ((by_name.get("promotion_refresh") or {}).get("result") or {})
    hourly = ((by_name.get("hourly_model_performance") or {}).get("result") or {})
    ten_minute = ((by_name.get("ten_minute_model_performance") or {}).get("result") or {})
    price_free = ((by_name.get("price_free_model_learning") or {}).get("result") or {})
    shadow_ab = ((by_name.get("shadow_ab_monitor") or {}).get("result") or {})
    active_variant_shadow = ((by_name.get("active_variant_shadow") or {}).get("result") or {})
    variant_evidence = ((by_name.get("model_variant_evidence_growth") or {}).get("result") or {})
    progress = ((by_name.get("progress_audit") or {}).get("result") or {})
    casebook = ((by_name.get("disagreement_casebook") or {}).get("result") or {})
    fleet = ((by_name.get("fleet_observability") or {}).get("result") or {})
    audit = ((by_name.get("data_layer_audit") or {}).get("result") or {})
    evaluation = ((by_name.get("snapshot_evaluation") or {}).get("result") or {})
    stage_attribution = ((by_name.get("distribution_stage_attribution") or {}).get("result") or {})
    learning = ((by_name.get("daily_learning") or {}).get("result") or {})
    variant_learning_gate = variant_learning_gate_from_steps(steps)
    disk_preflights = {
        step.get("name"): (step.get("result") or {}).get("disk_preflight")
        for step in steps
        if (step.get("result") or {}).get("disk_preflight")
    }
    return {
        "labels": {
            "total": finalize.get("label_count"),
            "quality_counts": finalize.get("quality_counts") or {},
            "reconciliation_counts": finalize.get("reconciliation_counts") or {},
        },
        "ingest_quality_gate": {
            "status": ingest.get("status"),
            "summary": ingest.get("summary") or {},
            "fail_reasons": ingest.get("fail_reasons") or [],
            "warn_reasons": ingest.get("warn_reasons") or [],
        },
        "promotion": {
            "candidate_verdict": promotion.get("candidate_verdict"),
            "cutover_decision": promotion.get("cutover_decision"),
            "action_counts": promotion.get("action_counts") or {},
            "promote_markets": promotion.get("promote_markets") or [],
            "shadow_markets": promotion.get("shadow_markets") or [],
            "blocked_markets": promotion.get("blocked_markets") or [],
        },
        "clob_order_book_tiering": {
            "status": clob_tiering.get("status"),
            "settled_before": clob_tiering.get("settled_before"),
            "summary": clob_tiering.get("summary") or {},
            "apply_summary": clob_tiering.get("apply_summary") or {},
            "delete_source": clob_tiering.get("delete_source"),
        },
        "hourly_model_performance": {
            "status": hourly.get("status"),
            "daily_summary": hourly.get("daily_summary") or {},
            "hourly_performance_gate": hourly.get("hourly_performance_gate") or {},
            "remediation_registry_summary": hourly.get("remediation_registry_summary") or {},
        },
        "ten_minute_model_performance": {
            "status": ten_minute.get("status"),
            "daily_summary": ten_minute.get("daily_summary") or {},
            "ten_minute_performance_gate": ten_minute.get("ten_minute_performance_gate") or {},
            "candidate_ten_minute_gate": ten_minute.get("candidate_ten_minute_gate") or {},
            "weak_slots": ten_minute.get("weak_slots") or [],
            "variant_ids": ten_minute.get("variant_ids") or [],
        },
        "price_free_model_learning": {
            "status": price_free.get("status"),
            "daily_summary": price_free.get("daily_summary") or {},
            "corpus": price_free.get("corpus") or {},
            "current_max_carryover_summary": price_free.get("current_max_carryover_summary") or {},
        },
        "replay_status_backfill": {
            "status": replay_backfill.get("status"),
            "summary": replay_backfill.get("summary") or {},
        },
        "shadow_ab_monitor": {
            "status": shadow_ab.get("status"),
            "summary": shadow_ab.get("summary") or {},
        },
        "active_variant_shadow": {
            "status": active_variant_shadow.get("status"),
            "summary": active_variant_shadow.get("summary") or {},
            "missing_active_variant_ids": active_variant_shadow.get("missing_active_variant_ids") or [],
            "blockers": active_variant_shadow.get("blockers") or [],
        },
        "model_variant_evidence_growth": {
            "status": variant_evidence.get("status"),
            "summary": variant_evidence.get("summary") or {},
            "delta_vs_baseline": variant_evidence.get("delta_vs_baseline"),
            "evidence_sla": variant_evidence.get("evidence_sla") or {},
            "no_growth_reasons": variant_evidence.get("no_growth_reasons") or [],
            "trend": variant_evidence.get("trend") or [],
        },
        "variant_learning_gate": variant_learning_gate,
        "progress_answer": progress.get("answer"),
        "casebook": {
            "case_count": casebook.get("case_count"),
            "settled_case_count": casebook.get("settled_case_count"),
            "open_case_count": casebook.get("open_case_count"),
        },
        "fleet": {
            "status": fleet.get("status"),
            "summary": fleet.get("summary") or {},
        },
        "data_layer_audit": {
            "gate_status": audit.get("gate_status"),
            "gate_summary": audit.get("gate_summary") or {},
            "recommendation_counts": audit.get("recommendation_counts") or {},
        },
        "snapshot_evaluation": {
            "status": evaluation.get("status"),
            "gate_counts": evaluation.get("gate_counts") or {},
            "snapshot_folders": evaluation.get("snapshot_folders"),
            "snapshots": evaluation.get("snapshots"),
            "top_gap_count": evaluation.get("top_gap_count"),
        },
        "distribution_stage_attribution": {
            "status": stage_attribution.get("status"),
            "settled_folder_count": stage_attribution.get("settled_folder_count"),
            "attribution_row_count": stage_attribution.get("attribution_row_count"),
            "net_negative_stage_count": stage_attribution.get("net_negative_stage_count"),
            "top_net_negative_stage": stage_attribution.get("top_net_negative_stage") or {},
        },
        "daily_learning": {
            "status": learning.get("status"),
            "learning_count": learning.get("learning_count"),
            "blocker_count": learning.get("blocker_count"),
            "high_priority_learning_count": learning.get("high_priority_learning_count"),
            "retrain_input_count": learning.get("retrain_input_count"),
            "training_ready": learning.get("training_ready"),
            "promotion_ready": learning.get("promotion_ready"),
        },
        "disk_preflight": disk_preflights,
    }


def _step_result(steps, name):
    for step in steps:
        if step.get("name") == name:
            return step.get("result") or {}
    return {}


def _variant_blocker(component, gate, detail, remediation_command, extra=None):
    return {
        "component": component,
        "gate": gate,
        "detail": detail,
        "remediation_command": remediation_command,
        "suggested_command": remediation_command,
        **(extra or {}),
    }


def filter_runners_for_resume(runners, resume_from_step=""):
    if not resume_from_step:
        return list(runners)
    if resume_from_step not in STEP_ORDER:
        raise ValueError(f"unknown resume step: {resume_from_step}")
    start = STEP_ORDER.index(resume_from_step)
    allowed = set(STEP_ORDER[start:])
    return [(name, runner) for name, runner in runners if name in allowed]


def _first_no_growth_remediation(evidence):
    for row in evidence.get("no_growth_reasons") or []:
        if row.get("status") in {"BLOCK", "WARN"} and row.get("action"):
            return row.get("action")
    for alert in evidence.get("alerts") or []:
        if alert.get("action"):
            return alert.get("action")
    return "Collect new independent settled market-day evidence before making a broad promotion claim."


def variant_learning_gate_from_steps(steps):
    active = _step_result(steps, "active_variant_shadow")
    evidence = _step_result(steps, "model_variant_evidence_growth")
    blockers = []
    active_status = active.get("status")
    evidence_status = evidence.get("status")

    if active_status in {"BLOCK", "ERROR"}:
        detail = "; ".join(active.get("blockers") or []) or f"active variant shadow status {active_status}"
        missing = active.get("missing_active_variant_ids") or []
        if missing:
            detail = f"{detail}; missing active variants: {', '.join(missing)}"
        blockers.append(_variant_blocker(
            "active_variant_shadow",
            "active_variant_shadow_coverage",
            detail,
            "python -m weather.operations.daily_refresh run --active-variant-shadow-sources <current-active-variant-exports>",
            {"missing_active_variant_ids": missing},
        ))

    if evidence_status == "SKIPPED" and evidence.get("reason") == "missing_current_variant_evidence":
        missing = evidence.get("missing_paths") or []
        blockers.append(_variant_blocker(
            "model_variant_evidence_growth",
            "variant_evidence_missing",
            "current active-variant evidence is missing: " + (", ".join(missing) or "-"),
            "python -m weather.operations.daily_refresh run --active-variant-shadow-sources <current-active-variant-exports>",
            {"missing_paths": missing},
        ))
    elif evidence_status == "ALERT":
        sla = evidence.get("evidence_sla") or {}
        reasons = sla.get("reasons") or []
        detail = "; ".join(reasons) or "model_variant_evidence_growth is ALERT"
        blockers.append(_variant_blocker(
            "model_variant_evidence_growth",
            "variant_evidence_sla",
            detail,
            _first_no_growth_remediation(evidence),
            {
                "evidence_sla_status": sla.get("status"),
                "no_growth_reasons": evidence.get("no_growth_reasons") or [],
            },
        ))

    if blockers:
        status = "BLOCK"
    elif active_status == "SKIPPED" or evidence_status == "SKIPPED":
        status = "SKIPPED"
    elif active or evidence:
        status = "PASS"
    else:
        status = "SKIPPED"
    return {
        "schema_version": schema_version("variant_learning_operational_gate"),
        "status": status,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "active_variant_shadow_status": active_status,
        "model_variant_evidence_growth_status": evidence_status,
    }


def render_report(payload):
    lines = [
        "# Daily Settlement-To-Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Duration seconds: `{payload.get('duration_seconds')}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Seconds | Result |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for step in payload.get("steps") or []:
        result = step.get("result") or {}
        if step.get("status") == "error":
            detail = step.get("error") or "-"
        elif step.get("name") == "market_day_labels_finalize":
            detail = f"labels {result.get('label_count')} {result.get('quality_counts')}"
        elif step.get("name") == "replay_status_backfill":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                detail = (
                    f"{result.get('status')}; wrote {summary.get('written_folder_count')}; "
                    f"irreparable {summary.get('irreparable_folder_count')}; "
                    f"training_ready {summary.get('training_ready_folder_count')}"
                )
        elif step.get("name") == "clob_order_book_tiering":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                apply_summary = result.get("apply_summary") or {}
                detail = (
                    f"{result.get('status')}; candidates {summary.get('candidate_files')}; "
                    f"compressed {apply_summary.get('compressed_files')}; "
                    f"deleted {apply_summary.get('deleted_sources')}; "
                    f"blocked {apply_summary.get('insufficient_headroom')}"
                )
        elif step.get("name") == "reanalysis_recent_refresh":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                detail = f"fetched {result.get('fetched_ranges')} ranges; errors {result.get('error_count')}"
        elif step.get("name") == "ingest_quality_gate":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                detail = (
                    f"{result.get('status')}; "
                    f"schema {summary.get('markets_with_schema_errors')}; "
                    f"duplicates {summary.get('markets_with_duplicates')}; "
                    f"impossible {summary.get('markets_with_impossible_values')}; "
                    f"missing {summary.get('markets_with_missing_days')}; "
                    f"sparse {summary.get('markets_with_sparse_days')}"
                )
        elif step.get("name") == "promotion_refresh":
            disk = result.get("disk_preflight") or {}
            if result.get("status") == "BLOCK" and disk:
                detail = (
                    f"disk BLOCK; free {disk.get('free_bytes')}; "
                    f"required {disk.get('required_free_bytes')}; "
                    f"short {disk.get('insufficient_bytes')}"
                )
            else:
                detail = (
                    f"{result.get('candidate_verdict')} / {result.get('cutover_decision')}; "
                    f"actions {result.get('action_counts')}"
                )
        elif step.get("name") == "hourly_model_performance":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                gate = result.get("hourly_performance_gate") or {}
                daily = result.get("daily_summary") or {}
                detail = (
                    f"{gate.get('status')}; blockers {gate.get('blocker_count', 0)}; "
                    f"worst {', '.join(daily.get('worst_hours') or []) or '-'}"
                )
        elif step.get("name") == "ten_minute_model_performance":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                gate = result.get("ten_minute_performance_gate") or {}
                daily = result.get("daily_summary") or {}
                detail = (
                    f"{gate.get('status')}; blockers {gate.get('blocker_count', 0)}; "
                    f"weak {', '.join(daily.get('weak_slots') or []) or '-'}"
                )
        elif step.get("name") == "price_free_model_learning":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                daily = result.get("daily_summary") or {}
                carryover = result.get("current_max_carryover_summary") or {}
                detail = (
                    f"{result.get('status')}; days {daily.get('scored_market_days')}; "
                    f"rows {daily.get('hourly_checkpoint_rows')}; "
                    f"current_max_guarded {carryover.get('risky_or_guarded_count', 0)}"
                )
        elif step.get("name") == "shadow_ab_monitor":
            detail = f"{result.get('status')} {result.get('summary')}"
        elif step.get("name") == "active_variant_shadow":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')} "
                    f"{(result.get('summary') or {}).get('canonical_rows')} rows; "
                    f"missing {len(result.get('missing_active_variant_ids') or [])}"
                )
        elif step.get("name") == "model_variant_evidence_growth":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')} "
                    f"{(result.get('summary') or {}).get('unique_observation_count')} unique obs; "
                    f"delta {result.get('delta_vs_baseline')}"
                )
        elif step.get("name") == "progress_audit":
            detail = result.get("answer") or "-"
        elif step.get("name") == "disagreement_casebook":
            detail = (
                f"cases {result.get('case_count')}; "
                f"settled {result.get('settled_case_count')}; open {result.get('open_case_count')}"
            )
        elif step.get("name") == "fleet_observability":
            detail = f"{result.get('status')} {result.get('summary')}"
        elif step.get("name") == "data_layer_audit":
            if result.get("skipped"):
                detail = result.get("reason") or "skipped"
            else:
                detail = f"gates {result.get('gate_status')} {result.get('gate_summary')}"
        elif step.get("name") == "snapshot_evaluation":
            detail = (
                f"{result.get('status')} {result.get('gate_counts')}; "
                f"snapshots {result.get('snapshots')}; gaps {result.get('top_gap_count')}"
            )
        elif step.get("name") == "distribution_stage_attribution":
            top_stage = (result.get("top_net_negative_stage") or {}).get("group") or "-"
            detail = (
                f"{result.get('status')}; rows {result.get('attribution_row_count')}; "
                f"net_negative {result.get('net_negative_stage_count')}; top {top_stage}"
            )
        elif step.get("name") == "data_retention_inventory":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                summary = result.get("summary") or {}
                disk = result.get("disk") or {}
                detail = (
                    f"{result.get('status')}; data {summary.get('total_human')}; "
                    f"recent {summary.get('recent_human')}; free {disk.get('free_human')}; "
                    f"restore_blocks {summary.get('restore_block_count')}"
                )
        elif step.get("name") == "daily_learning":
            if result.get("status") == "SKIPPED":
                detail = result.get("reason") or "skipped"
            else:
                detail = (
                    f"{result.get('status')}; learnings {result.get('learning_count')}; "
                    f"blockers {result.get('blocker_count')}; "
                    f"training_ready {result.get('training_ready')}"
                )
        else:
            detail = "-"
        lines.append(
            f"| {step.get('name')} | {step.get('status')} | "
            f"{step.get('duration_seconds', '-')} | {detail} |"
        )
    hourly_summary = (payload.get("summary") or {}).get("hourly_model_performance") or {}
    hourly_gate = hourly_summary.get("hourly_performance_gate") or {}
    if hourly_gate:
        first = hourly_gate.get("first_blocker") or {}
        daily = hourly_summary.get("daily_summary") or {}
        lines += [
            "",
            "## Hourly Performance Gate",
            "",
            f"Status: `{hourly_gate.get('status')}`",
            f"Best hours: {', '.join(daily.get('best_hours') or []) or '-'}",
            f"Worst hours: {', '.join(daily.get('worst_hours') or []) or '-'}",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    ten_minute_summary = (payload.get("summary") or {}).get("ten_minute_model_performance") or {}
    ten_minute_gate = ten_minute_summary.get("ten_minute_performance_gate") or {}
    if ten_minute_gate:
        first = ten_minute_gate.get("first_blocker") or {}
        daily = ten_minute_summary.get("daily_summary") or {}
        candidate_gate = ten_minute_summary.get("candidate_ten_minute_gate") or {}
        lines += [
            "",
            "## 10-Minute Performance Gate",
            "",
            f"Status: `{ten_minute_gate.get('status')}`",
            f"Weak slots: {', '.join(daily.get('weak_slots') or []) or '-'}",
            f"Worst slots: {', '.join(daily.get('worst_slots') or []) or '-'}",
            f"Candidate gate: `{candidate_gate.get('status') or '-'}`",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    price_free_summary = (payload.get("summary") or {}).get("price_free_model_learning") or {}
    price_free_daily = price_free_summary.get("daily_summary") or {}
    price_free_carryover = price_free_summary.get("current_max_carryover_summary") or {}
    if price_free_summary.get("status"):
        lines += [
            "",
            "## Price-Free Model Learning",
            "",
            f"Status: `{price_free_summary.get('status')}`",
            f"Scored market-days: `{price_free_daily.get('scored_market_days', 0)}`",
            f"Hourly checkpoint rows: `{price_free_daily.get('hourly_checkpoint_rows', 0)}`",
            f"Final top-hit rate: `{price_free_daily.get('final_top_hit_rate')}`",
            f"Current-max guarded rows: `{price_free_carryover.get('risky_or_guarded_count', 0)}`",
            "",
        ]
    variant_gate = (payload.get("summary") or {}).get("variant_learning_gate") or {}
    if variant_gate:
        first = variant_gate.get("first_blocker") or {}
        lines += [
            "",
            "## Variant Learning Gate",
            "",
            f"Status: `{variant_gate.get('status')}`",
            f"First blocker: {first.get('detail') or '-'}",
            f"Remediation: `{first.get('remediation_command') or '-'}`",
            "",
        ]
    disk_preflights = (payload.get("summary") or {}).get("disk_preflight") or {}
    if disk_preflights:
        lines += ["", "## Disk Preflight", ""]
        disk_rows = []
        for step_name, disk in sorted(disk_preflights.items()):
            disk_rows.append([
                step_name,
                disk.get("status"),
                disk.get("free_bytes"),
                disk.get("required_free_bytes"),
                disk.get("projected_export_bytes"),
                disk.get("insufficient_bytes"),
                disk.get("cleanup_command"),
                disk.get("resume_command"),
            ])
        lines += [
            "| Step | Status | Free Bytes | Required Bytes | Projected Export Bytes | Shortfall | Cleanup Command | Resume Command |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | :--- | :--- |",
        ]
        for row in disk_rows:
            lines.append(
                f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} |"
            )
    progress_ledger = payload.get("daily_progress_ledger") or {}
    if progress_ledger:
        lines += [
            "",
            "## Daily Progress Ledger",
            "",
            f"Status: `{progress_ledger.get('status')}`",
            f"Broad improvement claim allowed: `{progress_ledger.get('broad_improvement_claim_allowed')}`",
            (
                "Claim failures: "
                f"`{', '.join(progress_ledger.get('broad_improvement_claim_failures') or []) or '-'}`"
            ),
            f"JSONL: `{progress_ledger.get('jsonl_out') or '-'}`",
            f"CSV: `{progress_ledger.get('csv_out') or '-'}`",
            f"Report: `{progress_ledger.get('report_out') or '-'}`",
            "",
        ]
    lines += [
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(payload.get("summary") or {}, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def run_daily_refresh(args, runners=None):
    guard_enabled = (
        not getattr(args, "dry_run", False)
        and not getattr(args, "disable_long_job_guard", False)
    )
    with long_job_guard(
        "daily_refresh",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=guard_enabled,
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        return _run_daily_refresh_guarded(args, runners=runners, long_job_guard_info=guard)


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
            "long_job_guard": long_job_guard_info or {},
            "resume_from_step": getattr(args, "resume_from_step", ""),
        },
    }
    if args.dry_run:
        payload["steps"] = planned_steps()
        payload["status"] = "dry_run"
    else:
        for name, runner in runners:
            if name == "daily_learning":
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
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["summary"] = pipeline_summary(payload["steps"])
    if not args.dry_run and not getattr(args, "skip_daily_progress_ledger", False):
        try:
            payload["daily_progress_ledger"] = write_daily_progress_ledger(args, payload)
        except Exception as exc:  # noqa: BLE001 - status must still persist after refresh errors
            payload["daily_progress_ledger"] = {
                "status": "ERROR",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
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


def build_run_parser(parser):
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders for settlement finalization.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--roadmap", default=str(progress_audit.DEFAULT_ROADMAP))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--force-lock", action="store_true")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--resume-from-step", default="", choices=("", *STEP_ORDER))
    parser.add_argument("--fail-on-fleet-critical", action="store_true")
    parser.add_argument("--fail-on-ingest-quality", action="store_true")
    parser.add_argument("--fail-on-data-layer-audit", action="store_true")
    parser.set_defaults(fail_on_hourly_performance_gate=True)
    parser.add_argument("--fail-on-hourly-performance-gate", dest="fail_on_hourly_performance_gate", action="store_true")
    parser.add_argument("--allow-hourly-performance-gate", dest="fail_on_hourly_performance_gate", action="store_false")
    parser.set_defaults(fail_on_ten_minute_performance_gate=True)
    parser.add_argument(
        "--fail-on-ten-minute-performance-gate",
        dest="fail_on_ten_minute_performance_gate",
        action="store_true",
    )
    parser.add_argument(
        "--allow-ten-minute-performance-gate",
        dest="fail_on_ten_minute_performance_gate",
        action="store_false",
    )
    parser.add_argument("--fail-on-snapshot-evaluation", action="store_true")
    parser.add_argument("--fail-on-shadow-ab-alert", action="store_true")
    parser.set_defaults(fail_on_variant_evidence_alert=True)
    parser.add_argument("--fail-on-variant-evidence-alert", dest="fail_on_variant_evidence_alert", action="store_true")
    parser.add_argument("--allow-variant-evidence-alert", dest="fail_on_variant_evidence_alert", action="store_false")
    parser.add_argument("--fail-on-daily-learning-blocker", action="store_true")
    parser.add_argument("--skip-shadow-ab-monitor", action="store_true")
    parser.add_argument("--ab-current-tol", type=float, default=0.003)
    parser.add_argument("--ab-market-tol", type=float, default=0.003)
    parser.add_argument("--skip-model-variant-evidence-growth", action="store_true")
    parser.add_argument("--skip-active-variant-shadow", action="store_true")
    parser.add_argument(
        "--active-variant-shadow-sources",
        default="",
        help="Comma-separated current active variant row paths used to build active_variant_shadow_long.csv.",
    )
    parser.add_argument("--variant-registry", default=str(active_variant_shadow_refresh.DEFAULT_REGISTRY_PATH))
    parser.add_argument(
        "--variant-evidence-current",
        default="",
        help="Comma-separated current variant long-table paths; defaults to active_variant_shadow_long.csv.",
    )
    parser.add_argument(
        "--variant-evidence-baseline",
        default="",
        help="Comma-separated baseline variant long-table paths; defaults to item 70/71 long CSV.",
    )
    parser.add_argument("--variant-evidence-min-unique-observations", type=int, default=1)
    parser.add_argument("--variant-evidence-min-market-days", type=int, default=1)
    parser.add_argument("--variant-evidence-rolling-7d-min-market-days", type=int, default=1)
    parser.add_argument("--variant-evidence-per-shadow-market-min-days", type=int, default=4)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--skip-hourly-model-performance", action="store_true")
    parser.add_argument("--skip-ten-minute-model-performance", action="store_true")
    parser.add_argument("--skip-price-free-model-learning", action="store_true")
    parser.add_argument("--markets", default="", help="Comma-separated market IDs for price-free diagnostics.")
    parser.add_argument(
        "--promotion-min-artifact-free-bytes",
        type=int,
        default=promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
        help="Daily-refresh preflight minimum free bytes before promotion refresh artifact exports.",
    )
    parser.add_argument("--hourly-min-rows", type=int, default=hourly_model_performance.DEFAULT_MIN_ROWS)
    parser.add_argument("--hourly-top-hours", type=int, default=hourly_model_performance.DEFAULT_TOP_HOURS)
    parser.add_argument("--hourly-min-regime-market-days", type=int, default=hourly_model_performance.DEFAULT_MIN_REGIME_MARKET_DAYS)
    parser.add_argument(
        "--hourly-early-brier-regression-tolerance",
        type=float,
        default=hourly_model_performance.DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--hourly-early-logloss-regression-tolerance",
        type=float,
        default=hourly_model_performance.DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--hourly-early-ece-max", type=float, default=hourly_model_performance.DEFAULT_EARLY_ECE_MAX)
    parser.add_argument("--ten-minute-min-rows", type=int, default=ten_minute_model_performance.DEFAULT_MIN_ROWS)
    parser.add_argument("--ten-minute-top-slots", type=int, default=ten_minute_model_performance.DEFAULT_TOP_SLOTS)
    parser.add_argument(
        "--ten-minute-min-weak-market-days",
        type=int,
        default=ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
    )
    parser.add_argument(
        "--ten-minute-weak-brier-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-weak-logloss-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-candidate-rows",
        default=str(ten_minute_model_performance.DEFAULT_ITEM147_ROWS),
    )
    parser.add_argument(
        "--ten-minute-candidate-min-weak-market-days",
        type=int,
        default=ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-brier-improvement-min",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-market-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-logloss-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--daily-summary", default="")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--settle", action="append", default=[])
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    parser.add_argument("--skip-polymarket-reconciliation", action="store_true")
    parser.add_argument("--skip-replay-status-backfill", action="store_true")
    parser.add_argument("--skip-clob-order-book-tiering", action="store_true")
    parser.add_argument("--clob-tiering-settled-before", default="")
    parser.add_argument(
        "--clob-tiering-min-free-bytes",
        type=int,
        default=clob_order_book_tiering.DEFAULT_MIN_FREE_BYTES,
    )
    parser.add_argument("--clob-tiering-limit", type=int, default=None)
    parser.set_defaults(clob_tiering_delete_source=True)
    parser.add_argument("--clob-tiering-delete-source", dest="clob_tiering_delete_source", action="store_true")
    parser.add_argument("--keep-clob-order-book-source", dest="clob_tiering_delete_source", action="store_false")
    parser.add_argument("--overwrite-replay-status", action="store_true")
    parser.add_argument("--reconstruct-missing-replay-inputs", action="store_true")
    parser.add_argument("--include-active-replay-status", action="store_true")
    parser.add_argument("--no-clob-casebook", action="store_true")
    parser.add_argument("--collection-interval-minutes", type=float, default=10.0)
    parser.add_argument("--collection-tolerance", type=float, default=1.5)
    parser.add_argument("--audit-target-month", type=int, default=None)
    parser.add_argument("--audit-target-day", type=int, default=None)
    parser.add_argument("--audit-years", default="")
    parser.add_argument("--skip-historical-audits", action="store_true")
    parser.add_argument("--tape-backup-root", default=str(fleet_observability.tape_backup.DEFAULT_BACKUP_ROOT))
    parser.add_argument("--verify-tape-backup-checksums", action="store_true")
    parser.add_argument("--skip-ingest-quality-gate", action="store_true")
    parser.add_argument("--ingest-quality-years", default="", help="Comma-separated years; default 2000-2025.")
    parser.add_argument("--skip-reanalysis-refresh", action="store_true")
    parser.add_argument("--reanalysis-lag-days", type=int, default=10)
    parser.add_argument("--reanalysis-chunk-days", type=int, default=5)
    parser.add_argument("--reanalysis-sleep", type=float, default=0.2)
    parser.add_argument("--reanalysis-timeout", type=float, default=30)
    parser.add_argument("--reanalysis-end-date", default="")
    parser.add_argument("--skip-data-layer-audit", action="store_true")
    parser.add_argument("--skip-data-retention-inventory", action="store_true")
    parser.add_argument("--distribution-stage-min-rows", type=int, default=20)
    parser.add_argument(
        "--data-retention-min-free-bytes",
        type=int,
        default=data_retention_inventory.DEFAULT_MIN_FREE_BYTES,
    )
    parser.add_argument(
        "--data-retention-lookback-hours",
        type=float,
        default=data_retention_inventory.DEFAULT_LOOKBACK_HOURS,
    )
    parser.add_argument("--data-retention-top-n", type=int, default=data_retention_inventory.DEFAULT_TOP_N)
    parser.add_argument("--skip-daily-learning", action="store_true")
    parser.add_argument("--data-layer-historical-start", default="2000-01-01")
    parser.add_argument("--data-layer-historical-end", default="")
    return parser


def cmd_run(args):
    lock = None
    if not args.dry_run:
        lock = acquire_lock(args.lock_path, force=args.force_lock)
        if lock is None:
            print(f"Daily refresh already running or stale lock exists: {args.lock_path}", file=sys.stderr)
            return 3
    try:
        payload, status_path, report_path = run_daily_refresh(args)
    finally:
        release_lock(lock)
    print(f"Daily refresh: {payload['status']}")
    print(f"Status written to {status_path}")
    print(f"Report written to {report_path}")
    if payload["status"] == "error":
        return 1
    if payload["status"] == "critical":
        return 2
    return 0


def cmd_status(args):
    status = load_status(args.status_out)
    if not status.get("exists"):
        print(f"No daily refresh status at {status['path']}")
        return 1
    print(json.dumps(status, indent=2, sort_keys=True, default=str))
    if status.get("status") in {"error", "unreadable"}:
        return 1
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Run or inspect the daily settlement-to-promotion refresh.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = build_run_parser(sub.add_parser("run"))
    run.set_defaults(func=cmd_run)
    status = sub.add_parser("status")
    status.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
