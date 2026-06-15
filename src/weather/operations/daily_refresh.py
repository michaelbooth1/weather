"""Daily settlement-to-promotion refresh automation.

This runner is intentionally thin: it executes the existing authoritative
commands in order and records one durable status artifact for operators.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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
from weather.reporting import fleet_observability
from weather.reporting import progress_audit
from weather.reporting import promotion_refresh
from weather.reporting import snapshot_evaluation
from weather.market.market_registry import all_specs
from weather.sources.reanalysis_history import ReanalysisClient, ReanalysisStore
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_refresh")
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_refresh_report.md"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "daily_refresh.lock"
DEFAULT_TASK_NAME = "WeatherDailySettlementPromotionRefresh"
STEP_ORDER = (
    "reanalysis_recent_refresh",
    "ingest_quality_gate",
    "market_day_labels_finalize",
    "promotion_refresh",
    "progress_audit",
    "disagreement_casebook",
    "fleet_observability",
    "data_layer_audit",
    "snapshot_evaluation",
)


def utc_now():
    return datetime.now(timezone.utc)


def utc_iso():
    return utc_now().isoformat()


def as_path(value):
    return str(Path(value)) if value is not None else None


def backtest_path(args, name):
    return str(Path(args.backtest_root) / name)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


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
    refresh_args.out = backtest_path(args, "f_family_promotion_refresh.json")
    refresh_args.report = backtest_path(args, "f_family_promotion_refresh_report.md")
    return refresh_args


def run_promotion_refresh_step(args):
    payload, out_path, report_path = promotion_refresh.run_promotion_refresh(promotion_args(args))
    decisions = payload.get("decisions") or {}
    candidate = payload.get("candidate") or {}
    aggregate = candidate.get("aggregate") or {}
    corpus = payload.get("corpus") or {}
    return {
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


DEFAULT_RUNNERS = (
    ("reanalysis_recent_refresh", run_reanalysis_recent_refresh_step),
    ("ingest_quality_gate", run_ingest_quality_gate_step),
    ("market_day_labels_finalize", run_market_day_labels_finalize),
    ("promotion_refresh", run_promotion_refresh_step),
    ("progress_audit", run_progress_audit_step),
    ("disagreement_casebook", run_disagreement_casebook_step),
    ("fleet_observability", run_fleet_observability_step),
    ("data_layer_audit", run_data_layer_audit_step),
    ("snapshot_evaluation", run_snapshot_evaluation_step),
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
    promotion = ((by_name.get("promotion_refresh") or {}).get("result") or {})
    progress = ((by_name.get("progress_audit") or {}).get("result") or {})
    casebook = ((by_name.get("disagreement_casebook") or {}).get("result") or {})
    fleet = ((by_name.get("fleet_observability") or {}).get("result") or {})
    audit = ((by_name.get("data_layer_audit") or {}).get("result") or {})
    evaluation = ((by_name.get("snapshot_evaluation") or {}).get("result") or {})
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
            detail = (
                f"{result.get('candidate_verdict')} / {result.get('cutover_decision')}; "
                f"actions {result.get('action_counts')}"
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
        else:
            detail = "-"
        lines.append(
            f"| {step.get('name')} | {step.get('status')} | "
            f"{step.get('duration_seconds', '-')} | {detail} |"
        )
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
    started = time.time()
    started_at = utc_iso()
    runners = list(runners or DEFAULT_RUNNERS)
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
        },
    }
    if args.dry_run:
        payload["steps"] = planned_steps()
        payload["status"] = "dry_run"
    else:
        for name, runner in runners:
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
        if getattr(args, "fail_on_snapshot_evaluation", False):
            evaluation_step = next((step for step in payload["steps"] if step.get("name") == "snapshot_evaluation"), {})
            evaluation_status = ((evaluation_step.get("result") or {}).get("status"))
            if evaluation_status == "FAIL" and payload["status"] == "ok":
                payload["status"] = "critical"
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["summary"] = pipeline_summary(payload["steps"])
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-fleet-critical", action="store_true")
    parser.add_argument("--fail-on-ingest-quality", action="store_true")
    parser.add_argument("--fail-on-data-layer-audit", action="store_true")
    parser.add_argument("--fail-on-snapshot-evaluation", action="store_true")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default="complete,manual_override")
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
    parser.add_argument("--no-clob-casebook", action="store_true")
    parser.add_argument("--collection-interval-minutes", type=float, default=10.0)
    parser.add_argument("--collection-tolerance", type=float, default=1.5)
    parser.add_argument("--audit-target-month", type=int, default=None)
    parser.add_argument("--audit-target-day", type=int, default=None)
    parser.add_argument("--audit-years", default="")
    parser.add_argument("--skip-historical-audits", action="store_true")
    parser.add_argument("--skip-ingest-quality-gate", action="store_true")
    parser.add_argument("--ingest-quality-years", default="", help="Comma-separated years; default 2000-2025.")
    parser.add_argument("--skip-reanalysis-refresh", action="store_true")
    parser.add_argument("--reanalysis-lag-days", type=int, default=10)
    parser.add_argument("--reanalysis-chunk-days", type=int, default=5)
    parser.add_argument("--reanalysis-sleep", type=float, default=0.2)
    parser.add_argument("--reanalysis-timeout", type=float, default=30)
    parser.add_argument("--reanalysis-end-date", default="")
    parser.add_argument("--skip-data-layer-audit", action="store_true")
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
