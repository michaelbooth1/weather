"""Daily refresh step adapters, registry, and status summary helpers."""

from __future__ import annotations

import json
import time
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    finalize_folders,
)
from weather.market import mm_paper
from weather.market import taker_bot
from weather.market.market_day_labels import discover_default_folders, parse_overrides
from weather.market.market_registry import all_specs
from weather.operations import clob_order_book_tiering
from weather.operations import replay_status_backfill
from weather.operations.daily_refresh_locks import (
    DiskPreflightError,
    as_path,
    backtest_path,
    promotion_disk_preflight,
    resume_command,
    stale_lock_repair_command,
    utc_iso,
    write_json,
)
from weather.reporting import active_variant_shadow_refresh
from weather.reporting import data_auditor
from weather.reporting import data_layer_audit
from weather.reporting import data_retention_inventory
from weather.reporting import daily_flow_analysis
from weather.reporting import daily_learning
from weather.reporting import daily_progress_ledger
from weather.reporting import daily_rollup_freshness
from weather.reporting import disagreement_casebook
from weather.reporting import distribution_stage_attribution
from weather.reporting import fleet_observability
from weather.reporting import frozen_baseline_replay_trend
from weather.reporting import hourly_model_performance
from weather.reporting import price_free_model_learning
from weather.reporting import proper_scoring_reliability_scorecard
from weather.reporting import progress_audit
from weather.reporting import promotion_refresh
from weather.reporting import settled_day_root_cause
from weather.reporting import shadow_ab_monitor
from weather.reporting import snapshot_evaluation
from weather.reporting import settlement_source_audit
from weather.reporting import taker_tail_casebook
from weather.reporting import ten_minute_model_performance
from weather.reporting import trading_evidence
from weather.reporting import variant_evidence_growth
from weather.schema_registry import schema_version
from weather.sources.reanalysis_history import ReanalysisClient, ReanalysisStore


STEP_ORDER = (
    "reanalysis_recent_refresh",
    "ingest_quality_gate",
    "market_day_labels_finalize",
    "taker_finalization_watchdog",
    "taker_tail_casebook",
    "maker_paper_score",
    "settlement_source_audit",
    "trading_evidence",
    "clob_order_book_tiering",
    "replay_status_backfill",
    "hourly_model_performance",
    "ten_minute_model_performance",
    "price_free_model_learning",
    "promotion_refresh",
    "shadow_ab_monitor",
    "active_variant_shadow",
    "proper_scoring_reliability_scorecard",
    "frozen_baseline_replay_trend",
    "model_variant_evidence_growth",
    "progress_audit",
    "disagreement_casebook",
    "fleet_observability",
    "data_layer_audit",
    "snapshot_evaluation",
    "distribution_stage_attribution",
    "settled_day_root_cause",
    "data_retention_inventory",
    "daily_learning",
    "daily_flow_analysis",
)


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
    payload = taker_bot.finalization_watchdog(
        target_date=getattr(args, "taker_finalization_date", "") or None,
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
    )
    status = _taker_finalization_status(payload)
    payload["status"] = status
    json_out = write_json(backtest_path(args, "taker_finalization_watchdog.json"), payload)
    report_out = backtest_path(args, "taker_finalization_watchdog_report.md")
    Path(report_out).parent.mkdir(parents=True, exist_ok=True)
    Path(report_out).write_text(taker_bot.render_finalization_watchdog_report(payload), encoding="utf-8")
    summary = payload.get("summary") or {}
    return {
        "status": status,
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
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
    runs = taker_tail_casebook.discover_run_sources(
        getattr(args, "taker_root", taker_tail_casebook.DEFAULT_TAKER_RUNS_ROOT),
        target_date=getattr(args, "taker_tail_casebook_date", "") or None,
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
    summary = payload.get("summary") or {}
    return {
        "status": summary.get("status"),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
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
        now=utc_iso(),
        ledger_root=getattr(args, "ledger_root", None),
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
        "status": "BLOCK" if freshness.get("status") == "STALE" else "PASS",
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
    payload = trading_evidence.build_trading_evidence_summary(
        mm_runs_root=getattr(args, "mm_root", trading_evidence.DEFAULT_MM_RUNS_ROOT),
        taker_runs_root=getattr(args, "taker_root", trading_evidence.DEFAULT_TAKER_RUNS_ROOT),
        mm_paper_json=backtest_path(args, "mm_paper_report.json"),
        settlement_audit_json=backtest_path(args, "settlement_source_revision_audit.json"),
        generated_at_utc=utc_iso(),
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
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "mm_evidence_mode": mm.get("evidence_mode"),
        "mm_counts_toward_live_forward": mm.get("counts_toward_live_forward_gate"),
        "mm_evidence_starvation_status": mm.get("evidence_starvation_status"),
        "mm_paper_score_freshness_status": mm.get("paper_score_freshness_status"),
        "mm_paper_latest_completed_active_day": mm.get("paper_score_latest_completed_active_day"),
        "mm_paper_latest_covered_active_day": mm.get("paper_score_latest_covered_active_day"),
        "mm_paper_conservative_fills": mm.get("paper_score_conservative_fills"),
        "mm_paper_gate_status": mm.get("paper_score_gate_status"),
        "taker_run_id": taker.get("run_id"),
        "taker_quality_status": (taker.get("quality_gate") or {}).get("status"),
        "taker_pnl_evidence_status": taker.get("pnl_evidence_status"),
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
    configured_date = getattr(args, "settled_root_cause_date", "") or getattr(args, "as_of", "")
    target = parse_date_arg(configured_date) if configured_date else (utc_now().date() - timedelta(days=1))
    target_date = target.isoformat()
    payload = settled_day_root_cause.build_payload(
        target_date,
        snapshots_root=args.snapshots_root,
        taker_root=getattr(args, "taker_root", settled_day_root_cause.DEFAULT_TAKER_ROOT),
        mm_root=getattr(args, "mm_root", settled_day_root_cause.DEFAULT_MM_ROOT),
        backtest_root=args.backtest_root,
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


def run_daily_flow_analysis_step(args):
    if getattr(args, "skip_daily_flow_analysis", False):
        return {"status": "SKIPPED", "reason": "skip_daily_flow_analysis"}
    steps_so_far = getattr(args, "_daily_refresh_steps_so_far", None) or []
    daily_refresh_summary = pipeline_summary(steps_so_far) if steps_so_far else None
    payload = daily_flow_analysis.build_flow_analysis(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=getattr(args, "as_of", None),
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


def build_rollup_freshness_status(args, *, generated_at_overrides=None):
    return daily_rollup_freshness.build_rollup_freshness(
        args.backtest_root,
        snapshots_root=args.snapshots_root,
        generated_at_overrides=generated_at_overrides or {},
        repair_command=stale_lock_repair_command(args),
    )


DEFAULT_RUNNERS = (
    ("reanalysis_recent_refresh", run_reanalysis_recent_refresh_step),
    ("ingest_quality_gate", run_ingest_quality_gate_step),
    ("market_day_labels_finalize", run_market_day_labels_finalize),
    ("taker_finalization_watchdog", run_taker_finalization_watchdog_step),
    ("taker_tail_casebook", run_taker_tail_casebook_step),
    ("maker_paper_score", run_maker_paper_score_step),
    ("settlement_source_audit", run_settlement_source_audit_step),
    ("trading_evidence", run_trading_evidence_step),
    ("clob_order_book_tiering", run_clob_order_book_tiering_step),
    ("replay_status_backfill", run_replay_status_backfill_step),
    ("hourly_model_performance", run_hourly_model_performance_step),
    ("ten_minute_model_performance", run_ten_minute_model_performance_step),
    ("price_free_model_learning", run_price_free_model_learning_step),
    ("promotion_refresh", run_promotion_refresh_step),
    ("shadow_ab_monitor", run_shadow_ab_monitor_step),
    ("active_variant_shadow", run_active_variant_shadow_step),
    ("proper_scoring_reliability_scorecard", run_proper_scoring_reliability_scorecard_step),
    ("frozen_baseline_replay_trend", run_frozen_baseline_replay_trend_step),
    ("model_variant_evidence_growth", run_model_variant_evidence_growth_step),
    ("progress_audit", run_progress_audit_step),
    ("disagreement_casebook", run_disagreement_casebook_step),
    ("fleet_observability", run_fleet_observability_step),
    ("data_layer_audit", run_data_layer_audit_step),
    ("snapshot_evaluation", run_snapshot_evaluation_step),
    ("distribution_stage_attribution", run_distribution_stage_attribution_step),
    ("settled_day_root_cause", run_settled_day_root_cause_step),
    ("data_retention_inventory", run_data_retention_inventory_step),
    ("daily_learning", run_daily_learning_step),
    ("daily_flow_analysis", run_daily_flow_analysis_step),
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
    taker_finalization = ((by_name.get("taker_finalization_watchdog") or {}).get("result") or {})
    taker_tail = ((by_name.get("taker_tail_casebook") or {}).get("result") or {})
    maker_paper = ((by_name.get("maker_paper_score") or {}).get("result") or {})
    truth_audit = ((by_name.get("settlement_source_audit") or {}).get("result") or {})
    trading = ((by_name.get("trading_evidence") or {}).get("result") or {})
    clob_tiering = ((by_name.get("clob_order_book_tiering") or {}).get("result") or {})
    replay_backfill = ((by_name.get("replay_status_backfill") or {}).get("result") or {})
    promotion = ((by_name.get("promotion_refresh") or {}).get("result") or {})
    hourly = ((by_name.get("hourly_model_performance") or {}).get("result") or {})
    ten_minute = ((by_name.get("ten_minute_model_performance") or {}).get("result") or {})
    price_free = ((by_name.get("price_free_model_learning") or {}).get("result") or {})
    shadow_ab = ((by_name.get("shadow_ab_monitor") or {}).get("result") or {})
    active_variant_shadow = ((by_name.get("active_variant_shadow") or {}).get("result") or {})
    proper_scorecard = ((by_name.get("proper_scoring_reliability_scorecard") or {}).get("result") or {})
    frozen_baseline = ((by_name.get("frozen_baseline_replay_trend") or {}).get("result") or {})
    variant_evidence = ((by_name.get("model_variant_evidence_growth") or {}).get("result") or {})
    progress = ((by_name.get("progress_audit") or {}).get("result") or {})
    casebook = ((by_name.get("disagreement_casebook") or {}).get("result") or {})
    fleet = ((by_name.get("fleet_observability") or {}).get("result") or {})
    audit = ((by_name.get("data_layer_audit") or {}).get("result") or {})
    evaluation = ((by_name.get("snapshot_evaluation") or {}).get("result") or {})
    stage_attribution = ((by_name.get("distribution_stage_attribution") or {}).get("result") or {})
    root_cause = ((by_name.get("settled_day_root_cause") or {}).get("result") or {})
    learning = ((by_name.get("daily_learning") or {}).get("result") or {})
    flow = ((by_name.get("daily_flow_analysis") or {}).get("result") or {})
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
        "taker_finalization_watchdog": {
            "status": taker_finalization.get("status"),
            "run_count": taker_finalization.get("run_count"),
            "labelable_run_count": taker_finalization.get("labelable_run_count"),
            "needs_finalization_count": taker_finalization.get("needs_finalization_count"),
            "finalized_run_count": taker_finalization.get("finalized_run_count"),
            "sla_breach_count": taker_finalization.get("sla_breach_count"),
            "pending_finalization_count": taker_finalization.get("pending_finalization_count"),
            "bakeoff_created_count": taker_finalization.get("bakeoff_created_count"),
            "bakeoff_fresh_count": taker_finalization.get("bakeoff_fresh_count"),
            "champion_decision": taker_finalization.get("champion_decision"),
            "champion_recommended_strategy_id": taker_finalization.get("champion_recommended_strategy_id"),
        },
        "taker_tail_casebook": {
            "status": taker_tail.get("status"),
            "source_run_count": taker_tail.get("source_run_count"),
            "tail_fill_count": taker_tail.get("tail_fill_count"),
            "losing_tail_fill_count": taker_tail.get("losing_tail_fill_count"),
            "low_price_tail_fill_count": taker_tail.get("low_price_tail_fill_count"),
            "warm_tail_fill_count": taker_tail.get("warm_tail_fill_count"),
            "no_go_candidate_count": taker_tail.get("no_go_candidate_count"),
        },
        "maker_paper_score": {
            "status": maker_paper.get("status"),
            "paper_score_freshness_status": maker_paper.get("paper_score_freshness_status"),
            "latest_completed_active_day": maker_paper.get("latest_completed_active_day"),
            "latest_covered_active_day": maker_paper.get("latest_covered_active_day"),
            "completed_active_run_count": maker_paper.get("completed_active_run_count"),
            "covered_active_run_count": maker_paper.get("covered_active_run_count"),
            "live_forward_day_count": maker_paper.get("live_forward_day_count"),
            "conservative_fills": maker_paper.get("conservative_fills"),
            "net_pnl_after_fees_incentives_usdc": maker_paper.get("net_pnl_after_fees_incentives_usdc"),
            "gate_status": maker_paper.get("gate_status"),
            "blocks_maker_evidence_countability": maker_paper.get("blocks_maker_evidence_countability"),
        },
        "settlement_source_audit": {
            "status": truth_audit.get("status"),
            "label_count": truth_audit.get("label_count"),
            "finalized_label_count": truth_audit.get("finalized_label_count"),
            "provisional_label_count": truth_audit.get("provisional_label_count"),
            "revised_label_count": truth_audit.get("revised_label_count"),
            "source_disagreement_label_count": truth_audit.get("source_disagreement_label_count"),
            "unreconciled_label_count": truth_audit.get("unreconciled_label_count"),
            "proof_grade_label_count": truth_audit.get("proof_grade_label_count"),
            "promotion_blocked_label_count": truth_audit.get("promotion_blocked_label_count"),
        },
        "trading_evidence": {
            "status": trading.get("status"),
            "mm_evidence_mode": trading.get("mm_evidence_mode"),
            "mm_counts_toward_live_forward": trading.get("mm_counts_toward_live_forward"),
            "mm_evidence_starvation_status": trading.get("mm_evidence_starvation_status"),
            "mm_paper_score_freshness_status": trading.get("mm_paper_score_freshness_status"),
            "mm_paper_latest_completed_active_day": trading.get("mm_paper_latest_completed_active_day"),
            "mm_paper_latest_covered_active_day": trading.get("mm_paper_latest_covered_active_day"),
            "mm_paper_conservative_fills": trading.get("mm_paper_conservative_fills"),
            "mm_paper_gate_status": trading.get("mm_paper_gate_status"),
            "taker_run_id": trading.get("taker_run_id"),
            "taker_quality_status": trading.get("taker_quality_status"),
            "taker_pnl_evidence_status": trading.get("taker_pnl_evidence_status"),
            "taker_settlement_source_audit_status": trading.get("taker_settlement_source_audit_status"),
            "taker_settlement_source_audit_blockers": trading.get("taker_settlement_source_audit_blockers") or [],
            "taker_net_pnl_usdc": trading.get("taker_net_pnl_usdc"),
            "taker_settled_order_count": trading.get("taker_settled_order_count"),
            "taker_unsettled_order_count": trading.get("taker_unsettled_order_count"),
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
        "proper_scoring_reliability_scorecard": {
            "status": proper_scorecard.get("status"),
            "source_row_count": proper_scorecard.get("source_row_count"),
            "scored_probability_row_count": proper_scorecard.get("scored_probability_row_count"),
            "lane_count": proper_scorecard.get("lane_count"),
            "blocker_count": proper_scorecard.get("blocker_count"),
            "lane_statuses": proper_scorecard.get("lane_statuses") or {},
            "served_validated_parity_status": proper_scorecard.get("served_validated_parity_status"),
        },
        "frozen_baseline_replay_trend": {
            "status": frozen_baseline.get("status"),
            "baseline_id": frozen_baseline.get("baseline_id"),
            "current_variant_id": frozen_baseline.get("current_variant_id"),
            "baseline_variant_id": frozen_baseline.get("baseline_variant_id"),
            "shared_observations": frozen_baseline.get("shared_observations"),
            "shared_market_days": frozen_baseline.get("shared_market_days"),
            "brier_delta_current_minus_baseline": frozen_baseline.get(
                "brier_delta_current_minus_baseline"
            ),
            "brier_delta_current_minus_market": frozen_baseline.get(
                "brier_delta_current_minus_market"
            ),
            "status_reasons": frozen_baseline.get("status_reasons") or [],
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
        "settled_day_root_cause": {
            "status": root_cause.get("status"),
            "target_date": root_cause.get("target_date"),
            "market_count": root_cause.get("market_count"),
            "snapshot_count": root_cause.get("snapshot_count"),
            "issue_count": root_cause.get("issue_count"),
            "issue_counts": root_cause.get("issue_counts") or {},
            "taker_net_pnl_usdc": root_cause.get("taker_net_pnl_usdc"),
            "mm_run_count": root_cause.get("mm_run_count"),
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
        "daily_flow_analysis": {
            "status": flow.get("status"),
            "action_count": flow.get("action_count"),
            "blocker_count": flow.get("blocker_count"),
            "p0_count": flow.get("p0_count"),
            "p1_count": flow.get("p1_count"),
            "training_ready": flow.get("training_ready"),
            "promotion_ready": flow.get("promotion_ready"),
            "next_command": flow.get("next_command"),
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


