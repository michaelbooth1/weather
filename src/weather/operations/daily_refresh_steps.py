"""Daily refresh step adapters and compatibility exports."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    finalize_folders,
)
from weather.market import exchange_economics
from weather.market import mm_paper
from weather.market import taker_bot
from weather.market.market_day_labels import discover_default_folders, parse_overrides
from weather.market.market_registry import all_specs
from weather.operations import clob_order_book_tiering
from weather.operations import closed_market_day_archive
from weather.operations import daily_roll_log_hygiene
from weather.operations import event_metadata_validation
from weather.operations import nightly_health_checks
from weather.operations import replay_status_backfill
from weather.operations.daily_refresh_registry import (
    STEP_ORDER,
    filter_runners_for_resume,
    planned_steps,
)
from weather.operations.daily_refresh_settled_day import (
    SETTLED_DAY_ANALYSIS_DEPENDENCIES,
    SettledDayAnalysisBarrierError,
    build_settled_day_analysis_barrier,
    parse_date_arg,
    run_settled_day_analysis_barrier_step,
    settled_analysis_target_date,
)
from weather.operations.daily_refresh_status import (
    build_rollup_freshness_status,
    pipeline_summary,
    run_step,
    variant_learning_gate_from_steps,
)
from weather.operations.daily_refresh_locks import (
    DiskPreflightError,
    as_path,
    backtest_path,
    promotion_disk_preflight,
    resume_command,
    utc_iso,
    utc_now,
    write_json,
)
from weather.reporting.candidate_lifecycle import active_variant_shadow_refresh
from weather.reporting.data_quality import data_auditor
from weather.reporting.data_quality import data_layer_audit
from weather.reporting.data_quality import data_retention_inventory
from weather.reporting.daily import daily_flow_analysis
from weather.reporting.daily import daily_learning
from weather.reporting.daily import daily_progress_ledger
from weather.reporting.casebooks import disagreement_casebook
from weather.reporting.scorecards import distribution_stage_attribution
from weather.reporting.fleet import fleet_observability
from weather.reporting.scorecards import frozen_baseline_replay_trend
from weather.reporting.hourly import hourly_model_performance
from weather.reporting.location_analysis import june23_location_bias_repair
from weather.reporting.market import market_beating_objective_scoreboard
from weather.reporting.candidate_lifecycle import model_market_disagreement_analysis
from weather.reporting.candidate_lifecycle import price_free_model_learning
from weather.reporting.scorecards import proper_scoring_reliability_scorecard
from weather.reporting.scorecards import progress_audit
from weather.reporting.promotion import promotion_refresh
from weather.reporting.serving_gates import runtime_identity_reconciliation
from weather.reporting.scorecards import settled_day_root_cause
from weather.reporting.candidate_lifecycle import shadow_ab_monitor
from weather.reporting.scorecards import snapshot_evaluation
from weather.reporting.source_gates import settlement_source_audit
from weather.reporting.casebooks import taker_tail_casebook
from weather.reporting.hourly import ten_minute_model_performance
from weather.reporting.market import trading_evidence
from weather.reporting.candidate_lifecycle import variant_evidence_growth
from weather.reporting.scorecards import winner_rank_parity
from weather.schema_registry import schema_version
from weather.sources.reanalysis_history import ReanalysisClient, ReanalysisStore


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


def _ingest_gap_coverage_summary(raw_summary, gap_coverage):
    raw_summary = dict(raw_summary or {})
    gap_coverage = gap_coverage or {}
    markets = gap_coverage.get("markets") or {}
    if not markets:
        return raw_summary

    unresolved_missing = sum(
        1 for row in markets.values()
        if row.get("unresolved_missing_days")
    )
    unresolved_sparse = sum(
        1 for row in markets.values()
        if row.get("unresolved_sparse_days")
    )
    coverage_summary = gap_coverage.get("summary") or {}
    return {
        **raw_summary,
        "raw_markets_with_missing_days": raw_summary.get("markets_with_missing_days", 0),
        "raw_markets_with_sparse_days": raw_summary.get("markets_with_sparse_days", 0),
        "markets_with_missing_days": unresolved_missing,
        "markets_with_sparse_days": unresolved_sparse,
        "historical_gap_markets_with_unresolved_gaps": coverage_summary.get(
            "markets_with_unresolved_gaps", 0
        ),
        "historical_gap_unresolved_issue_days": coverage_summary.get(
            "unresolved_issue_days", 0
        ),
        "historical_gap_covered_issue_days": coverage_summary.get(
            "covered_issue_days", 0
        ),
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
        "raw_markets_with_missing_days",
        "raw_markets_with_sparse_days",
        "historical_gap_markets_with_unresolved_gaps",
        "historical_gap_unresolved_issue_days",
        "historical_gap_covered_issue_days",
    ]:
        if key in summary:
            lines.append(f"| {key} | {summary.get(key)} |")
    lines += ["", "## Fail Reasons", ""]
    for reason in payload.get("fail_reasons") or ["-"]:
        lines.append(f"- {reason}")
    lines += ["", "## Warn Reasons", ""]
    for reason in payload.get("warn_reasons") or ["-"]:
        lines.append(f"- {reason}")
    coverage_summary = (payload.get("historical_gap_coverage") or {}).get("summary") or {}
    if coverage_summary:
        lines += ["", "## Historical Gap Coverage", ""]
        for key in [
            "markets_with_unresolved_gaps",
            "unresolved_issue_days",
            "covered_issue_days",
        ]:
            lines.append(f"- {key}: {coverage_summary.get(key)}")
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
    raw_summary = data_auditor.audit_summary(results)
    results_json = {
        market_id: data_auditor.jsonable_result(result)
        for market_id, result in (results or {}).items()
    }
    gap_coverage = fleet_observability.historical_gap_coverage(results_json)
    summary = _ingest_gap_coverage_summary(raw_summary, gap_coverage)
    gate = ingest_quality_gate_status(summary)
    payload = {
        "schema_version": "ingest_quality_gate_v0.1",
        "generated_at_utc": utc_iso(),
        "status": gate["status"],
        "summary": summary,
        "raw_summary": raw_summary,
        "historical_gap_coverage": gap_coverage,
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


def run_event_metadata_validation_step(args):
    if getattr(args, "skip_event_metadata_validation", False):
        return {"status": "SKIPPED", "reason": "skip_event_metadata_validation"}
    configured_date = (
        getattr(args, "event_metadata_target_date", "")
        or getattr(args, "as_of", "")
        or None
    )
    target = parse_date_arg(configured_date) if configured_date else utc_now().date()
    fetch_live = bool(getattr(args, "event_metadata_live_fetch", False))
    payload = event_metadata_validation.build_validation_payload(
        target_date=target,
        markets=getattr(args, "event_metadata_markets", "") or getattr(args, "markets", "") or "all",
        locations_path=getattr(args, "event_metadata_locations", event_metadata_validation.DEFAULT_LOCATIONS),
        event_metadata_path=getattr(args, "event_metadata_config", event_metadata_validation.DEFAULT_EVENT_METADATA),
        fetch_live=fetch_live,
        timeout_seconds=getattr(args, "event_metadata_timeout_seconds", 10.0),
        max_age_hours=getattr(args, "event_metadata_max_age_hours", event_metadata_validation.DEFAULT_MAX_AGE_HOURS),
    )
    json_out, report_out = event_metadata_validation.write_outputs(
        payload,
        json_out=backtest_path(args, "event_metadata_validation.json"),
        report_out=backtest_path(args, "event_metadata_validation_report.md"),
    )
    setattr(args, "_daily_refresh_event_metadata_validation_payload", payload)
    summary = payload.get("summary") or {}
    first = summary.get("first_blocker") or {}
    return {
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "validation_hash": payload.get("validation_hash"),
        "summary": summary,
        "first_blocker": {
            "market_id": first.get("market_id"),
            "event_slug": first.get("event_slug"),
            "reason": first.get("reason"),
            "remediation_command": first.get("remediation_command"),
            "first_issue": (first.get("first_issue") or {}).get("code"),
        },
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


def run_exchange_economics_rule_drift_step(args):
    if getattr(args, "skip_exchange_economics_rule_drift", False):
        return {"status": "SKIPPED", "reason": "skip_exchange_economics_rule_drift"}
    target = settled_analysis_target_date(args).isoformat()
    snapshot_path = (
        getattr(args, "exchange_economics_snapshot", "")
        or backtest_path(args, "exchange_economics_snapshot.json")
    )
    accepted_snapshot_path = (
        getattr(args, "exchange_economics_accepted_snapshot", "")
        or backtest_path(args, "exchange_economics_accepted_snapshot.json")
    )
    payload = exchange_economics.build_drift_report(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_snapshot_path,
        target_date=target,
        platform=getattr(args, "exchange_economics_platform", exchange_economics.DEFAULT_PLATFORM),
        now=getattr(args, "as_of", None),
    )
    json_out = exchange_economics.write_drift_report(
        payload,
        backtest_path(args, "exchange_economics_drift.json"),
    )
    gate = payload.get("current_gate") or {}
    return {
        "status": payload.get("status"),
        "target_date": target,
        "json_out": as_path(json_out),
        "snapshot_path": str(snapshot_path),
        "accepted_snapshot_path": str(accepted_snapshot_path),
        "snapshot_id": payload.get("current_snapshot_id"),
        "snapshot_hash": payload.get("current_snapshot_hash"),
        "gate_status": gate.get("status"),
        "rescore_required": bool(payload.get("rescore_required")),
        "material_change_count": payload.get("material_change_count"),
        "blockers": payload.get("blockers") or [],
    }


def _taker_finalization_status(payload):
    summary = payload.get("summary") or {}
    if summary.get("sla_breach_count"):
        return "BREACH"
    if summary.get("pending_finalization_count") or summary.get("needs_finalization_count"):
        return "PENDING"
    return "OK"


def run_taker_finalization_watchdog_step(args):
    if getattr(args, "skip_taker_finalization_watchdog", False):
        return {"status": "SKIPPED", "reason": "skip_taker_finalization_watchdog"}
    champion_ledger_out = backtest_path(args, "taker_champion_challenger_ledger.json")
    champion_report_out = backtest_path(args, "taker_champion_challenger_ledger_report.md")
    target_date = (
        getattr(args, "taker_finalization_date", "")
        or settled_analysis_target_date(args).isoformat()
    )
    payload = taker_bot.finalization_watchdog(
        target_date=target_date,
        runs_root=getattr(args, "taker_root", taker_bot.DEFAULT_RUNS_ROOT),
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        now=getattr(args, "as_of", None),
        sla_hours=getattr(args, "taker_finalization_sla_hours", taker_bot.DEFAULT_FINALIZATION_SLA_HOURS),
        finalize_missing=not getattr(args, "taker_finalization_no_finalize", False),
        min_free_bytes=getattr(args, "taker_finalization_min_free_bytes", taker_bot.DEFAULT_MIN_FREE_BYTES),
        ensure_bakeoff=not getattr(args, "skip_taker_bakeoff", False),
        bakeoff_strategies=getattr(args, "taker_bakeoff_strategies", taker_bot.DEFAULT_BAKEOFF_STRATEGIES),
        champion_strategy_id=getattr(args, "taker_champion_strategy_id", taker_bot.ACTIVE_DEFAULT_STRATEGY_ID),
        champion_min_complete_label_days=getattr(
            args,
            "taker_champion_min_complete_label_days",
            taker_bot.DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS,
        ),
        champion_min_settled_orders=getattr(
            args,
            "taker_champion_min_settled_orders",
            taker_bot.DEFAULT_CHAMPION_MIN_SETTLED_ORDERS,
        ),
        champion_ledger_out=champion_ledger_out,
        champion_ledger_report_out=champion_report_out,
        exchange_economics_snapshot_path=(
            getattr(args, "exchange_economics_snapshot", "")
            or backtest_path(args, "exchange_economics_snapshot.json")
        ),
        exchange_economics_platform=getattr(
            args,
            "exchange_economics_platform",
            exchange_economics.DEFAULT_PLATFORM,
        ),
        exchange_economics_required=True,
    )
    status = _taker_finalization_status(payload)
    payload["status"] = status
    json_out = write_json(backtest_path(args, "taker_finalization_watchdog.json"), payload)
    report_out = backtest_path(args, "taker_finalization_watchdog_report.md")
    Path(report_out).parent.mkdir(parents=True, exist_ok=True)
    report_text = taker_bot.render_finalization_watchdog_report(payload)
    Path(report_out).write_text(report_text, encoding="utf-8")
    detail_json_out = write_json(backtest_path(args, f"taker_finalization_watchdog_{target_date}.json"), payload)
    detail_report_out = backtest_path(args, f"taker_finalization_watchdog_report_{target_date}.md")
    Path(detail_report_out).parent.mkdir(parents=True, exist_ok=True)
    Path(detail_report_out).write_text(report_text, encoding="utf-8")
    summary = payload.get("summary") or {}
    return {
        "status": status,
        "target_date": target_date,
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "detail_json_out": as_path(detail_json_out),
        "detail_report_out": as_path(detail_report_out),
        "run_count": summary.get("run_count"),
        "labelable_run_count": summary.get("labelable_run_count"),
        "needs_finalization_count": summary.get("needs_finalization_count"),
        "finalized_run_count": summary.get("finalized_run_count"),
        "sla_breach_count": summary.get("sla_breach_count"),
        "pending_finalization_count": summary.get("pending_finalization_count"),
        "bakeoff_created_count": summary.get("bakeoff_created_count"),
        "bakeoff_fresh_count": summary.get("bakeoff_fresh_count"),
        "champion_decision": summary.get("champion_decision"),
        "champion_recommended_strategy_id": summary.get("champion_recommended_strategy_id"),
        "champion_ledger_out": as_path(champion_ledger_out),
        "champion_ledger_report_out": as_path(champion_report_out),
    }


def run_taker_tail_casebook_step(args):
    if getattr(args, "skip_taker_tail_casebook", False):
        return {"status": "SKIPPED", "reason": "skip_taker_tail_casebook"}
    target_date = (
        getattr(args, "taker_tail_casebook_date", "")
        or settled_analysis_target_date(args).isoformat()
    )
    runs = taker_tail_casebook.discover_run_sources(
        getattr(args, "taker_root", taker_tail_casebook.DEFAULT_TAKER_RUNS_ROOT),
        target_date=target_date,
        max_runs=getattr(args, "taker_tail_casebook_max_runs", 0) or None,
    )
    payload = taker_tail_casebook.build_tail_casebook_from_paths(
        runs,
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        generated_at_utc=utc_iso(),
    )
    json_out = backtest_path(args, "taker_tail_casebook.json")
    report_out = backtest_path(args, "taker_tail_casebook_report.md")
    taker_tail_casebook.write_outputs(payload, json_out=json_out, report_out=report_out)
    detail_json_out = backtest_path(args, f"taker_tail_casebook_{target_date}.json")
    detail_report_out = backtest_path(args, f"taker_tail_casebook_report_{target_date}.md")
    taker_tail_casebook.write_outputs(payload, json_out=detail_json_out, report_out=detail_report_out)
    summary = payload.get("summary") or {}
    return {
        "status": summary.get("status"),
        "target_date": target_date,
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "detail_json_out": as_path(detail_json_out),
        "detail_report_out": as_path(detail_report_out),
        "source_run_count": len(runs),
        "tail_fill_count": summary.get("tail_fill_count"),
        "losing_tail_fill_count": summary.get("losing_tail_fill_count"),
        "low_price_tail_fill_count": summary.get("low_price_tail_fill_count"),
        "warm_tail_fill_count": summary.get("warm_tail_fill_count"),
        "no_go_candidate_count": summary.get("no_go_candidate_count"),
    }


def run_maker_paper_score_step(args):
    if getattr(args, "skip_maker_paper_score", False):
        return {"status": "SKIPPED", "reason": "skip_maker_paper_score"}
    backtest_root = Path(args.backtest_root)
    payload = mm_paper.build_paper_payload(
        runs_root=getattr(args, "mm_root", mm_paper.DEFAULT_RUNS_ROOT),
        snapshots_root=getattr(args, "snapshots_root", mm_paper.DEFAULT_SNAPSHOTS_ROOT),
        backtest_root=backtest_root,
        casebook_path=backtest_path(args, "disagreement_casebook.json"),
        promotion_refresh=backtest_path(args, "f_family_promotion_refresh.json"),
        now=getattr(args, "as_of", None) or utc_iso(),
        ledger_root=getattr(args, "ledger_root", None),
        exchange_economics_snapshot_path=(
            getattr(args, "exchange_economics_snapshot", "")
            or backtest_path(args, "exchange_economics_snapshot.json")
        ),
        exchange_economics_target_date=settled_analysis_target_date(args).isoformat(),
        exchange_economics_platform=getattr(
            args,
            "exchange_economics_platform",
            exchange_economics.DEFAULT_PLATFORM,
        ),
        exchange_economics_required=True,
    )
    payload, _known_edge = mm_paper.write_outputs(
        payload,
        json_out=backtest_path(args, "mm_paper_report.json"),
        report_out=backtest_path(args, "mm_paper_report.md"),
        fills_out=backtest_path(args, "mm_paper_fills_long.csv"),
        known_edge_out=backtest_path(args, "mm_known_edge_map.json"),
        known_edge_report_out=backtest_path(args, "mm_known_edge_map.md"),
        promotion_refresh=backtest_path(args, "f_family_promotion_refresh.json"),
    )
    summary = payload.get("summary") or {}
    freshness = summary.get("paper_score_freshness") or {}
    pnl = summary.get("pnl") or {}
    return {
        "status": "BLOCK" if freshness.get("status") == "STALE" or summary.get("exchange_economics_gate_status") == "BLOCK" else "PASS",
        "json_out": as_path(backtest_path(args, "mm_paper_report.json")),
        "report_out": as_path(backtest_path(args, "mm_paper_report.md")),
        "fills_out": as_path(backtest_path(args, "mm_paper_fills_long.csv")),
        "known_edge_out": as_path(backtest_path(args, "mm_known_edge_map.json")),
        "known_edge_report_out": as_path(backtest_path(args, "mm_known_edge_map.md")),
        "paper_score_freshness_status": freshness.get("status"),
        "paper_score_freshness_reason": freshness.get("reason"),
        "latest_completed_active_day": freshness.get("latest_completed_active_day"),
        "latest_covered_active_day": freshness.get("latest_covered_active_day"),
        "completed_active_run_count": freshness.get("completed_active_run_count"),
        "covered_active_run_count": freshness.get("covered_active_run_count"),
        "live_forward_day_count": freshness.get("live_forward_day_count"),
        "conservative_fills": summary.get("conservative_fills"),
        "net_pnl_after_fees_incentives_usdc": pnl.get("net_pnl_after_fees_incentives_usdc"),
        "gate_status": summary.get("gate_status"),
        "exchange_economics_gate_status": summary.get("exchange_economics_gate_status"),
        "exchange_economics_snapshot_id": summary.get("exchange_economics_snapshot_id"),
        "exchange_economics_hash": summary.get("exchange_economics_hash"),
        "blocks_maker_evidence_countability": freshness.get("blocks_maker_evidence_countability"),
    }


def run_settlement_source_audit_step(args):
    if getattr(args, "skip_settlement_source_audit", False):
        return {"status": "SKIPPED", "reason": "skip_settlement_source_audit"}
    payload = settlement_source_audit.build_settlement_source_audit(
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        ledger_root=getattr(args, "ledger_root", DEFAULT_LEDGER_ROOT),
        generated_at_utc=utc_iso(),
    )
    json_out, report_out = settlement_source_audit.write_outputs(
        payload,
        json_out=backtest_path(args, "settlement_source_revision_audit.json"),
        report_out=backtest_path(args, "settlement_source_revision_audit.md"),
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "label_count": summary.get("label_count"),
        "finalized_label_count": summary.get("finalized_label_count"),
        "provisional_label_count": summary.get("provisional_label_count"),
        "revised_label_count": summary.get("revised_label_count"),
        "source_disagreement_label_count": summary.get("source_disagreement_label_count"),
        "unreconciled_label_count": summary.get("unreconciled_label_count"),
        "promotion_blocked_label_count": summary.get("promotion_blocked_label_count"),
        "proof_grade_label_count": summary.get("proof_grade_label_count"),
    }


def run_trading_evidence_step(args):
    if getattr(args, "skip_trading_evidence", False):
        return {"status": "SKIPPED", "reason": "skip_trading_evidence"}
    target_date = settled_analysis_target_date(args).isoformat()
    payload = trading_evidence.build_trading_evidence_summary(
        mm_runs_root=getattr(args, "mm_root", trading_evidence.DEFAULT_MM_RUNS_ROOT),
        taker_runs_root=getattr(args, "taker_root", trading_evidence.DEFAULT_TAKER_RUNS_ROOT),
        mm_paper_json=backtest_path(args, "mm_paper_report.json"),
        settlement_audit_json=backtest_path(args, "settlement_source_revision_audit.json"),
        generated_at_utc=utc_iso(),
        target_date=target_date,
    )
    status = trading_evidence._summary_status(payload)
    payload["status"] = status
    json_out, report_out = trading_evidence.write_outputs(
        payload,
        json_out=backtest_path(args, "trading_evidence.json"),
        report_out=backtest_path(args, "trading_evidence_report.md"),
    )
    taker = payload.get("taker") or {}
    mm = payload.get("market_making") or {}
    return {
        "status": status,
        "target_date": payload.get("target_date"),
        "run_date": payload.get("run_date"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "mm_evidence_mode": mm.get("evidence_mode"),
        "mm_counts_toward_live_forward": mm.get("counts_toward_live_forward_gate"),
        "mm_evidence_starvation_status": mm.get("evidence_starvation_status"),
        "mm_maker_day_classification": mm.get("maker_day_classification"),
        "mm_quote_starvation_gate_status": (mm.get("quote_starvation_gate") or {}).get("status"),
        "mm_paper_score_freshness_status": mm.get("paper_score_freshness_status"),
        "mm_paper_latest_completed_active_day": mm.get("paper_score_latest_completed_active_day"),
        "mm_paper_latest_covered_active_day": mm.get("paper_score_latest_covered_active_day"),
        "mm_paper_conservative_fills": mm.get("paper_score_conservative_fills"),
        "mm_paper_gate_status": mm.get("paper_score_gate_status"),
        "taker_run_id": taker.get("run_id"),
        "taker_quality_status": (taker.get("quality_gate") or {}).get("status"),
        "taker_pnl_evidence_status": taker.get("pnl_evidence_status"),
        "taker_zero_fill_quality_classification": taker.get("zero_fill_quality_classification"),
        "taker_settlement_source_audit_status": taker.get("settlement_source_audit_status"),
        "taker_settlement_source_audit_blockers": taker.get("settlement_source_audit_blockers") or [],
        "taker_net_pnl_usdc": taker.get("net_pnl_usdc"),
        "taker_settled_order_count": taker.get("settled_order_count"),
        "taker_unsettled_order_count": taker.get("unsettled_order_count"),
    }


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


def _daily_archive_root(args):
    return (
        Path(args.backtest_root).parent
        / "archive"
        / "closed_market_days"
        / closed_market_day_archive.ARCHIVE_ROOT_VERSION
    )


def run_closed_day_parquet_incremental_step(args):
    if getattr(args, "skip_closed_day_parquet_incremental", False):
        return {"status": "SKIPPED", "reason": "skip_closed_day_parquet_incremental"}
    cursor_path = backtest_path(args, "closed_market_day_parquet_incremental_cursor.json")
    payload = closed_market_day_archive.build_incremental_payload(
        snapshots_root=args.snapshots_root,
        archive_root=getattr(args, "closed_day_parquet_archive_root", "") or _daily_archive_root(args),
        apply=not getattr(args, "closed_day_parquet_plan_only", False),
        as_of_date=getattr(args, "as_of", None),
        max_scan_folders=getattr(args, "closed_day_parquet_max_scan_folders", 25),
        cursor_path=cursor_path,
        generated_at_utc=utc_iso(),
    )
    json_out, report_out, cursor_out = closed_market_day_archive.write_incremental_outputs(
        payload,
        json_path=backtest_path(args, "closed_market_day_parquet_incremental.json"),
        report_path=backtest_path(args, "closed_market_day_parquet_incremental_report.md"),
        cursor_path=cursor_path,
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "cursor_out": as_path(cursor_out),
        "summary": summary,
        "scanned": summary.get("scanned"),
        "changed": summary.get("changed"),
        "converted": summary.get("converted"),
        "blocked": summary.get("blocked"),
        "failed": summary.get("failed"),
        "remaining_scan_backlog": summary.get("remaining_scan_backlog"),
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


def scoring_liveness_fields(payload):
    liveness = (payload or {}).get("scoring_liveness") or {}
    return {
        "last_scored_target_date": (payload or {}).get("last_scored_target_date"),
        "latest_settled_label_date": (payload or {}).get("latest_settled_label_date"),
        "scoring_liveness_status": liveness.get("status"),
        "scoring_liveness": liveness,
        "remediation_command": liveness.get("remediation_command"),
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
        **scoring_liveness_fields(payload),
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
        **scoring_liveness_fields(payload),
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
    liveness = payload.get("scoring_liveness") or {}
    return {
        "status": "BLOCK" if liveness.get("status") == "BLOCK" else payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "hourly_csv_out": as_path(hourly_csv_out),
        "current_max_csv_out": as_path(current_max_csv_out),
        "daily_summary": payload.get("daily_summary") or {},
        "corpus": payload.get("corpus") or {},
        "current_max_carryover_summary": current_max.get("summary") or {},
        **scoring_liveness_fields(payload),
    }


def run_model_market_disagreement_rehydration_step(args):
    if getattr(args, "skip_model_market_disagreement_rehydration", False):
        return {"status": "SKIPPED", "reason": "skip_model_market_disagreement_rehydration"}
    target = settled_analysis_target_date(args).isoformat()
    log_path = Path(
        getattr(args, "model_market_disagreement_log", "")
        or backtest_path(args, "model_market_disagreement_audit.jsonl")
    )
    labels_csv = Path(getattr(args, "labels_csv", DEFAULT_LABELS_CSV))
    generated_at = utc_iso()
    rehydration = model_market_disagreement_analysis.rehydrate_audit_log(
        log_path=log_path,
        labels_csv=labels_csv,
        target_date=target,
        generated_at_utc=generated_at,
    )
    payload = model_market_disagreement_analysis.build_payload(
        log_path=log_path,
        min_pattern_cases=getattr(args, "model_market_disagreement_min_pattern_cases", 1),
        generated_at_utc=generated_at,
        rehydration_summary=rehydration,
    )
    json_out, report_out = model_market_disagreement_analysis.write_outputs(
        payload,
        json_out=backtest_path(args, "model_market_disagreement_analysis.json"),
        report_out=backtest_path(args, "model_market_disagreement_analysis.md"),
        review_queue_out=backtest_path(args, "model_market_disagreement_review_queue.json"),
    )
    review_queue_out = backtest_path(args, "model_market_disagreement_review_queue.json")
    summary = payload.get("summary") or {}
    return {
        "status": rehydration.get("status"),
        "target_date": target,
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "review_queue_out": as_path(review_queue_out),
        "audit_log_path": str(log_path),
        "labels_csv": str(labels_csv),
        "target_row_count": rehydration.get("target_row_count"),
        "pending_before_count": rehydration.get("pending_before_count"),
        "rehydrated_count": rehydration.get("rehydrated_count"),
        "model_closer_rehydrated_count": rehydration.get("model_closer_rehydrated_count"),
        "market_closer_rehydrated_count": rehydration.get("market_closer_rehydrated_count"),
        "excluded_partial_label_count": rehydration.get("excluded_partial_label_count"),
        "excluded_missing_label_count": rehydration.get("excluded_missing_label_count"),
        "pending_after_count": rehydration.get("pending_after_count"),
        "unresolved_after_rehydrate_count": rehydration.get("unresolved_after_rehydrate_count"),
        "blocker_count": rehydration.get("blocker_count"),
        "blockers": rehydration.get("blockers") or [],
        "summary": {
            "resolved_count": summary.get("resolved_count"),
            "pending_count": summary.get("pending_count"),
            "settlement_rehydration_excluded_count": summary.get("settlement_rehydration_excluded_count"),
            "model_closer_count": summary.get("model_closer_count"),
            "market_closer_count": summary.get("market_closer_count"),
        },
        "rehydration": rehydration,
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


def _variant_evidence_baseline_paths(args):
    value = getattr(args, "variant_evidence_baseline", "") or ""
    if value:
        return [item.strip() for item in value.split(",") if item.strip()]
    preferred = backtest_path(args, "model_variant_evidence_baseline_active_shadow_long.csv")
    if Path(preferred).exists():
        return [preferred]
    return [backtest_path(args, "item70_71_full_multi_variant_shadow_long.csv")]


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


def run_proper_scoring_reliability_scorecard_step(args):
    if getattr(args, "skip_proper_scoring_reliability_scorecard", False):
        return {"status": "SKIPPED", "reason": "skip_proper_scoring_reliability_scorecard"}
    payload = proper_scoring_reliability_scorecard.build_scorecard(
        active_shadow_long=backtest_path(args, "active_variant_shadow_long.csv"),
        promotion_refresh=backtest_path(args, "f_family_promotion_refresh.json"),
        hourly=backtest_path(args, "hourly_model_performance.json"),
        ten_minute=backtest_path(args, "ten_minute_model_performance.json"),
        served_distribution=backtest_path(args, "served_distribution_calibration_contract.json"),
        generated_at_utc=utc_iso(),
    )
    json_out, report_out = proper_scoring_reliability_scorecard.write_outputs(
        payload,
        json_out=backtest_path(args, "proper_scoring_reliability_scorecard.json"),
        report_out=backtest_path(args, "proper_scoring_reliability_scorecard.md"),
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "source_row_count": summary.get("source_row_count"),
        "scored_probability_row_count": summary.get("scored_probability_row_count"),
        "lane_count": summary.get("lane_count"),
        "blocker_count": summary.get("blocker_count"),
        "lane_statuses": summary.get("lane_statuses") or {},
        "served_validated_parity_status": summary.get("served_validated_parity_status"),
    }


def _comma_paths(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _filter_variant(rows, variant_id):
    if not variant_id:
        return rows
    return [row for row in rows if row.get("variant_id") == variant_id]


def run_frozen_baseline_replay_trend_step(args):
    if getattr(args, "skip_frozen_baseline_replay_trend", False):
        return {"status": "SKIPPED", "reason": "skip_frozen_baseline_replay_trend"}
    current_paths = _comma_paths(getattr(args, "frozen_baseline_current_predictions", ""))
    if not current_paths:
        current_paths = [backtest_path(args, "active_variant_shadow_long.csv")]
    missing_current = [path for path in current_paths if not Path(path).exists()]
    if missing_current:
        return {
            "status": "SKIPPED",
            "reason": "missing_current_frozen_baseline_predictions",
            "missing_paths": missing_current,
        }

    manifest_path = Path(
        getattr(args, "frozen_baseline_manifest", "")
        or backtest_path(args, "frozen_baseline_manifest.json")
    )
    manifest = frozen_baseline_replay_trend.load_manifest(manifest_path) or {}
    baseline_paths = _comma_paths(getattr(args, "frozen_baseline_baseline_predictions", ""))
    if not baseline_paths:
        baseline_paths = manifest.get("predictions_paths") or []
    if not baseline_paths:
        return {
            "status": "MISSING",
            "reason": "missing_pinned_baseline",
            "manifest": as_path(manifest_path),
        }
    missing_baseline = [path for path in baseline_paths if not Path(path).exists()]
    if missing_baseline:
        return {
            "status": "MISSING",
            "reason": "missing_pinned_baseline_predictions",
            "manifest": as_path(manifest_path),
            "missing_paths": missing_baseline,
        }

    current_variant_id = getattr(args, "frozen_baseline_current_variant_id", "") or ""
    baseline_variant_id = (
        getattr(args, "frozen_baseline_baseline_variant_id", "")
        or manifest.get("code_identity")
        or ""
    )
    current_rows = _filter_variant(
        frozen_baseline_replay_trend.read_prediction_rows(current_paths),
        current_variant_id,
    )
    baseline_rows = _filter_variant(
        frozen_baseline_replay_trend.read_prediction_rows(baseline_paths),
        baseline_variant_id,
    )
    payload = frozen_baseline_replay_trend.build_payload(
        current_rows,
        baseline_rows,
        manifest=manifest,
        code_identity=(
            getattr(args, "frozen_baseline_code_identity", "")
            or current_variant_id
            or None
        ),
        current_paths=current_paths,
        baseline_paths=baseline_paths,
    )
    trend_jsonl = Path(
        getattr(args, "frozen_baseline_trend_jsonl", "")
        or backtest_path(args, "frozen_baseline_replay_trend.jsonl")
    )
    json_out = Path(
        getattr(args, "frozen_baseline_json_out", "")
        or backtest_path(args, "frozen_baseline_replay_trend.json")
    )
    report_out = Path(
        getattr(args, "frozen_baseline_report_out", "")
        or backtest_path(args, "frozen_baseline_replay_trend_report.md")
    )
    trend_rows = frozen_baseline_replay_trend.upsert_trend(
        frozen_baseline_replay_trend.trend_row(payload),
        trend_jsonl,
    )
    frozen_baseline_replay_trend.write_json(json_out, payload)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(
        frozen_baseline_replay_trend.render_report(payload, trend_rows),
        encoding="utf-8",
    )
    overall = payload.get("overall") or {}
    coverage = payload.get("coverage") or {}
    return {
        "status": payload.get("independent_baseline_status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "trend_jsonl": as_path(trend_jsonl),
        "manifest": as_path(manifest_path),
        "baseline_id": payload.get("baseline_id"),
        "current_variant_id": current_variant_id,
        "baseline_variant_id": baseline_variant_id,
        "shared_observations": coverage.get("shared_observations"),
        "shared_market_days": coverage.get("shared_market_days"),
        "brier_delta_current_minus_baseline": overall.get("brier_delta_current_minus_baseline"),
        "brier_delta_current_minus_market": overall.get("brier_delta_current_minus_market"),
        "status_reasons": payload.get("status_reasons") or [],
    }


def run_model_variant_evidence_growth_step(args):
    if getattr(args, "skip_model_variant_evidence_growth", False):
        return {"status": "SKIPPED", "reason": "skip_model_variant_evidence_growth"}
    current_paths = _variant_evidence_paths(
        args,
        "variant_evidence_current",
        "active_variant_shadow_long.csv",
    )
    baseline_paths = _variant_evidence_baseline_paths(args)
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
        "input_paths": payload.get("input_paths") or [],
        "baseline_paths": payload.get("baseline_paths") or [],
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


def run_runtime_identity_reconciliation_step(args):
    target_date = settled_analysis_target_date(args).isoformat()
    payload = runtime_identity_reconciliation.build_payload(
        snapshots_root=args.snapshots_root,
        target_date=target_date,
    )
    json_out, report_out = runtime_identity_reconciliation.write_outputs(
        payload,
        json_out=backtest_path(args, "runtime_identity_reconciliation.json"),
        report_out=backtest_path(args, "runtime_identity_reconciliation.md"),
    )
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "target_date": payload.get("target_date"),
        "mixed_runtime_identity": payload.get("mixed_runtime_identity"),
        "runtime_identity_count": payload.get("runtime_identity_count"),
        "snapshot_row_count": payload.get("snapshot_row_count"),
        "blocker_count": payload.get("blocker_count"),
        "first_blocker": payload.get("first_blocker"),
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
        parquet_incremental_path=backtest_path(args, "closed_market_day_parquet_incremental.json"),
    )
    json_out = fleet_observability.write_json(backtest_path(args, "fleet_observability.json"), payload)
    report_out = fleet_observability.write_markdown(backtest_path(args, "fleet_observability_report.md"), payload)
    provenance_out = fleet_observability.write_json(
        backtest_path(args, "artifact_provenance_manifest.json"),
        payload["artifact_provenance"],
    )
    setattr(args, "_daily_refresh_fleet_observability_payload", payload)
    return {
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "provenance_out": as_path(provenance_out),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "tape_backup_status": ((payload.get("tape_backup") or {}).get("status")),
        "collection_states": ((payload.get("collection") or {}).get("summary") or {}).get("states") or {},
    }


def run_daily_roll_log_hygiene_step(args):
    if getattr(args, "skip_daily_roll_log_hygiene", False):
        return {"status": "SKIPPED", "reason": "skip_daily_roll_log_hygiene"}
    configured = daily_roll_log_hygiene.parse_log_sources(
        getattr(args, "daily_roll_log_sources", "")
    )
    log_sources = configured or daily_roll_log_hygiene.DEFAULT_LOG_SOURCES
    current_root = (
        Path(getattr(args, "daily_roll_current_log_root", "") or "")
        if getattr(args, "daily_roll_current_log_root", "")
        else backtest_path(args, "daily_roll_current_logs")
    )
    incidents_out = Path(
        getattr(args, "daily_roll_log_incidents", "")
        or backtest_path(args, "daily_roll_log_incidents.jsonl")
    )
    payload = daily_roll_log_hygiene.build_payload(
        log_sources=log_sources,
        incidents_path=incidents_out,
        current_window_hours=getattr(
            args,
            "daily_roll_log_window_hours",
            daily_roll_log_hygiene.DEFAULT_CURRENT_WINDOW_HOURS,
        ),
        as_of=getattr(args, "as_of", None),
    )
    json_out, incidents_path, current_log_root = daily_roll_log_hygiene.write_outputs(
        payload,
        json_out=backtest_path(args, "daily_roll_log_hygiene.json"),
        incidents_out=incidents_out,
        current_log_root=current_root,
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "incidents_out": as_path(incidents_path),
        "current_log_root": as_path(current_log_root),
        "current_blocker_count": summary.get("current_blocker_count"),
        "current_signature_count": summary.get("current_signature_count"),
        "historical_error_count": summary.get("historical_error_count"),
        "archived_incident_count": summary.get("archived_incident_count"),
        "recurring_incident_count": summary.get("recurring_incident_count"),
        "missing_log_count": summary.get("missing_log_count"),
        "current_category_counts": summary.get("current_category_counts") or {},
        "first_current_blocker": next(iter(payload.get("current_blockers") or []), {}),
    }


def run_nightly_health_checks_step(args):
    if getattr(args, "skip_nightly_health_checks", False):
        return {"status": "SKIPPED", "reason": "skip_nightly_health_checks"}
    fleet_payload = getattr(args, "_daily_refresh_fleet_observability_payload", None)
    if not fleet_payload:
        fleet_payload = nightly_health_checks.load_fleet_payload(
            backtest_path(args, "fleet_observability.json")
        )
    payload = nightly_health_checks.build_payload(
        fleet_payload=fleet_payload,
        now=getattr(args, "as_of", None),
        timezone_name=getattr(
            args,
            "nightly_health_timezone",
            nightly_health_checks.DEFAULT_TIMEZONE,
        ),
        target_date=getattr(args, "nightly_health_date", "") or None,
        max_bot_activity_age_seconds=getattr(
            args,
            "nightly_health_max_bot_activity_age_seconds",
            nightly_health_checks.DEFAULT_MAX_BOT_ACTIVITY_AGE_SECONDS,
        ),
        startup_grace_seconds=getattr(
            args,
            "nightly_health_startup_grace_seconds",
            nightly_health_checks.DEFAULT_STARTUP_GRACE_SECONDS,
        ),
    )
    outputs = nightly_health_checks.write_outputs(
        payload,
        alert_root=getattr(args, "nightly_health_alert_root", nightly_health_checks.DEFAULT_ALERT_ROOT),
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "alert_root": outputs.get("alert_root"),
        "json_out": outputs.get("json_out"),
        "report_out": outputs.get("report_out"),
        "latest_json_out": outputs.get("latest_json_out"),
        "latest_report_out": outputs.get("latest_report_out"),
        "alert_count": summary.get("alert_count"),
        "critical_alerts": summary.get("critical_alerts"),
        "warning_alerts": summary.get("warning_alerts"),
        "first_alert": summary.get("first_alert") or {},
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
        archive_root=_daily_archive_root(args),
        archive_as_of_date=getattr(args, "as_of", None),
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
        "market_stage_row_count": len(payload.get("by_market_stage") or []),
        "market_stage_cutoff_regime_row_count": len(
            payload.get("by_market_stage_cutoff_regime") or []
        ),
        "net_negative_stage_count": (payload.get("summary") or {}).get("net_negative_stage_count"),
        "top_net_negative_stage": (payload.get("summary") or {}).get("top_net_negative_stage"),
        "bottom_location_winner_mass_blocker_count": (
            payload.get("summary") or {}
        ).get("bottom_location_winner_mass_blocker_count"),
        "top_bottom_location_winner_mass_blocker": (
            payload.get("summary") or {}
        ).get("top_bottom_location_winner_mass_blocker"),
    }


def run_settled_day_root_cause_step(args):
    if getattr(args, "skip_settled_day_root_cause", False):
        return {"status": "SKIPPED", "reason": "skip_settled_day_root_cause"}
    configured_date = getattr(args, "settled_root_cause_date", "") or ""
    target = parse_date_arg(configured_date) if configured_date else settled_analysis_target_date(args)
    target_date = target.isoformat()
    payload = settled_day_root_cause.build_payload(
        target_date,
        snapshots_root=args.snapshots_root,
        taker_root=getattr(args, "taker_root", settled_day_root_cause.DEFAULT_TAKER_ROOT),
        mm_root=getattr(args, "mm_root", settled_day_root_cause.DEFAULT_MM_ROOT),
        backtest_root=args.backtest_root,
        labels_csv=getattr(args, "labels_csv", settled_day_root_cause.DEFAULT_LABELS_CSV),
    )
    json_out, report_out, issues_out = settled_day_root_cause.write_outputs(
        payload,
        json_out=backtest_path(args, "settled_day_root_cause.json"),
        report_out=backtest_path(args, "settled_day_root_cause_report.md"),
        issues_out=backtest_path(args, "settled_day_root_cause_issues.csv"),
    )
    summary = payload.get("summary") or {}
    return {
        "status": payload.get("status"),
        "target_date": target_date,
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "issues_out": as_path(issues_out),
        "market_count": summary.get("market_count"),
        "snapshot_count": summary.get("snapshot_count"),
        "issue_count": summary.get("issue_count"),
        "issue_counts": summary.get("issue_counts") or {},
        "taker_net_pnl_usdc": summary.get("taker_net_pnl_usdc"),
        "mm_run_count": summary.get("mm_run_count"),
        **scoring_liveness_fields(payload),
    }


def run_winner_rank_parity_step(args):
    if getattr(args, "skip_winner_rank_parity", False):
        return {"status": "SKIPPED", "reason": "skip_winner_rank_parity"}
    payload = winner_rank_parity.build_payload(
        snapshots_root=args.snapshots_root,
        labels_csv=getattr(args, "labels_csv", winner_rank_parity.DEFAULT_LABELS_CSV),
        active_shadow_long=backtest_path(args, "active_variant_shadow_long.csv"),
        proper_scoring=backtest_path(args, "proper_scoring_reliability_scorecard.json"),
        settled_day_root_cause=backtest_path(args, "settled_day_root_cause.json"),
        as_of=getattr(args, "as_of", None),
        days=getattr(args, "winner_rank_parity_days", winner_rank_parity.DEFAULT_DAYS),
        generated_at_utc=utc_iso(),
        min_snapshots=getattr(args, "winner_rank_parity_min_snapshots", winner_rank_parity.DEFAULT_MIN_SNAPSHOTS),
    )
    json_out, report_out = winner_rank_parity.write_outputs(
        payload,
        json_out=backtest_path(args, "winner_rank_parity.json"),
        report_out=backtest_path(args, "winner_rank_parity.md"),
    )
    summary = payload.get("summary") or {}
    gate = payload.get("parity_gate") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "source_row_count": summary.get("source_row_count"),
        "candidate_row_count": summary.get("candidate_row_count"),
        "snapshot_case_count": summary.get("snapshot_case_count"),
        "variant_count": summary.get("variant_count"),
        "parity_gate_status": gate.get("status"),
        "blocker_count": gate.get("blocker_count"),
        "first_blocker": gate.get("first_blocker") or {},
        "model_top_hit_rate": summary.get("model_top_hit_rate"),
        "market_top_hit_rate": summary.get("market_top_hit_rate"),
        "market_top_model_miss_excess": summary.get("market_top_model_miss_excess"),
        "winner_probability_gap_market_minus_model": summary.get("winner_probability_gap_market_minus_model"),
        "brier_contribution": summary.get("brier_contribution"),
        "candidate_guardrail_block_count": summary.get("candidate_guardrail_block_count"),
    }


def run_june23_location_bias_repair_step(args):
    if getattr(args, "skip_june23_location_bias_repair", False):
        return {"status": "SKIPPED", "reason": "skip_june23_location_bias_repair"}
    json_out = backtest_path(args, "june23_location_bias_repair_packet.json")
    payload = june23_location_bias_repair.build_payload(
        snapshots_root=args.snapshots_root,
        labels_csv=getattr(args, "labels_csv", june23_location_bias_repair.DEFAULT_LABELS_CSV),
        target_date=getattr(
            args,
            "june23_location_bias_repair_date",
            june23_location_bias_repair.DEFAULT_TARGET_DATE,
        ),
        artifact_path=json_out,
        generated_at_utc=utc_iso(),
    )
    json_out, report_out = june23_location_bias_repair.write_outputs(
        payload,
        json_out=json_out,
        report_out=backtest_path(args, "june23_location_bias_repair_packet.md"),
    )
    summary = payload.get("summary") or {}
    replay = payload.get("repair_replay") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "target_date": payload.get("target_date"),
        "cases_scored": (payload.get("case_packet") or {}).get("cases_scored"),
        "repair_manifest_count": summary.get("repair_manifest_count"),
        "eligible_repair_manifest_count": summary.get("eligible_repair_manifest_count"),
        "repair_replay_status": replay.get("status"),
        "repair_improvement_count": replay.get("repair_improvement_count"),
        "protected_regression_count": replay.get("protected_regression_count"),
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
        run_date=settled_analysis_target_date(args).isoformat(),
        daily_refresh_summary=daily_refresh_summary,
        rollup_generated_at_overrides={"daily_progress_latest": utc_iso()},
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


def run_market_beating_objective_scoreboard_step(args):
    if getattr(args, "skip_market_beating_objective_scoreboard", False):
        return {"status": "SKIPPED", "reason": "skip_market_beating_objective_scoreboard"}
    payload = market_beating_objective_scoreboard.build_scoreboard(
        backtest_root=args.backtest_root,
        generated_at_utc=utc_iso(),
    )
    json_out, report_out = market_beating_objective_scoreboard.write_outputs(
        payload,
        json_out=backtest_path(args, "market_beating_objective_scoreboard.json"),
        report_out=backtest_path(args, "market_beating_objective_scoreboard.md"),
    )
    headline = payload.get("headline") or {}
    summary = payload.get("summary") or {}
    decisions = payload.get("decisions") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "headline_status": headline.get("status"),
        "first_success_lane": headline.get("first_success_lane"),
        "first_blocker": headline.get("first_blocker") or {},
        "weather_only_status": (decisions.get("weather_only_market_beating") or {}).get("status"),
        "residual_edge_status": (decisions.get("residual_edge") or {}).get("status"),
        "executable_profitability_status": (decisions.get("executable_profitability") or {}).get("status"),
        "anti_anchoring_status": ((payload.get("anti_anchoring") or {}).get("status")),
        "blocker_count": summary.get("blocker_count"),
    }


def run_daily_flow_analysis_step(args):
    if getattr(args, "skip_daily_flow_analysis", False):
        return {"status": "SKIPPED", "reason": "skip_daily_flow_analysis"}
    steps_so_far = getattr(args, "_daily_refresh_steps_so_far", None) or []
    daily_refresh_summary = pipeline_summary(steps_so_far) if steps_so_far else None
    payload = daily_flow_analysis.build_flow_analysis(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=settled_analysis_target_date(args).isoformat(),
        daily_refresh_steps=steps_so_far,
        daily_refresh_summary=daily_refresh_summary,
    )
    json_out, report_out, actions_out = daily_flow_analysis.write_outputs(
        payload,
        json_out=backtest_path(args, "daily_flow_analysis.json"),
        report_out=backtest_path(args, "daily_flow_analysis_report.md"),
        actions_out=backtest_path(args, "daily_flow_analysis_actions.csv"),
    )
    summary = payload.get("summary") or {}
    decision = payload.get("decision_record") or {}
    return {
        "status": payload.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "actions_out": as_path(actions_out),
        "action_count": summary.get("action_count"),
        "blocker_count": summary.get("blocker_count"),
        "p0_count": summary.get("p0_count"),
        "p1_count": summary.get("p1_count"),
        "training_ready": decision.get("training_ready"),
        "promotion_ready": decision.get("promotion_ready"),
        "next_command": decision.get("next_command"),
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
    ("event_metadata_validation", run_event_metadata_validation_step),
    ("market_day_labels_finalize", run_market_day_labels_finalize),
    ("exchange_economics_rule_drift", run_exchange_economics_rule_drift_step),
    ("taker_finalization_watchdog", run_taker_finalization_watchdog_step),
    ("taker_tail_casebook", run_taker_tail_casebook_step),
    ("maker_paper_score", run_maker_paper_score_step),
    ("settlement_source_audit", run_settlement_source_audit_step),
    ("trading_evidence", run_trading_evidence_step),
    ("clob_order_book_tiering", run_clob_order_book_tiering_step),
    ("replay_status_backfill", run_replay_status_backfill_step),
    ("closed_day_parquet_incremental", run_closed_day_parquet_incremental_step),
    ("hourly_model_performance", run_hourly_model_performance_step),
    ("ten_minute_model_performance", run_ten_minute_model_performance_step),
    ("price_free_model_learning", run_price_free_model_learning_step),
    ("model_market_disagreement_rehydration", run_model_market_disagreement_rehydration_step),
    ("settled_day_analysis_barrier", run_settled_day_analysis_barrier_step),
    ("runtime_identity_reconciliation", run_runtime_identity_reconciliation_step),
    ("fleet_observability", run_fleet_observability_step),
    ("promotion_refresh", run_promotion_refresh_step),
    ("shadow_ab_monitor", run_shadow_ab_monitor_step),
    ("active_variant_shadow", run_active_variant_shadow_step),
    ("proper_scoring_reliability_scorecard", run_proper_scoring_reliability_scorecard_step),
    ("frozen_baseline_replay_trend", run_frozen_baseline_replay_trend_step),
    ("model_variant_evidence_growth", run_model_variant_evidence_growth_step),
    ("progress_audit", run_progress_audit_step),
    ("disagreement_casebook", run_disagreement_casebook_step),
    ("daily_roll_log_hygiene", run_daily_roll_log_hygiene_step),
    ("nightly_health_checks", run_nightly_health_checks_step),
    ("data_layer_audit", run_data_layer_audit_step),
    ("snapshot_evaluation", run_snapshot_evaluation_step),
    ("distribution_stage_attribution", run_distribution_stage_attribution_step),
    ("settled_day_root_cause", run_settled_day_root_cause_step),
    ("winner_rank_parity", run_winner_rank_parity_step),
    ("june23_location_bias_repair", run_june23_location_bias_repair_step),
    ("data_retention_inventory", run_data_retention_inventory_step),
    ("daily_learning", run_daily_learning_step),
    ("market_beating_objective_scoreboard", run_market_beating_objective_scoreboard_step),
    ("daily_flow_analysis", run_daily_flow_analysis_step),
)


