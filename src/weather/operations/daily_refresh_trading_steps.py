"""Daily refresh trading, tape, CLOB, and archive steps."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import csv

from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    LABEL_COLUMNS,
    finalize_folder,
    finalize_folders,
)
from weather.market import exchange_economics
from weather.market import mm_paper
from weather.market import taker_bot
from weather.market import taker_edge_permission
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
    carried_forward_steps,
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
from weather.reporting.source_gates import settlement_source_audit
from weather.reporting.casebooks import taker_tail_casebook
from weather.reporting.market import trading_evidence


DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS = 14
DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES = 512 * 1024 * 1024


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
    refresh = {}
    try:
        refresh = exchange_economics.publish_snapshot_from_template(
            template_path=(
                getattr(args, "exchange_economics_template", "")
                or exchange_economics.DEFAULT_TEMPLATE
            ),
            snapshot_path=snapshot_path,
            # Verify for the wall-clock date, not the settled-analysis target:
            # the proof must cover TODAY's active-day consumers (MM preflight,
            # taker), and a today-stamped proof also covers the settled D-1
            # target via the >= coverage rule. Passed explicitly because a
            # template that carries its own date would otherwise win over now.
            target_date=exchange_economics.utc_now(getattr(args, "as_of", None)).date().isoformat(),
            platform=getattr(args, "exchange_economics_platform", exchange_economics.DEFAULT_PLATFORM),
            now=getattr(args, "as_of", None),
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed gate evidence
        refresh = {
            "status": "BLOCK",
            "reason": str(exc),
            "snapshot_path": str(snapshot_path),
            "target_date": target,
        }
    payload = exchange_economics.build_drift_report(
        snapshot_path=snapshot_path,
        accepted_snapshot_path=accepted_snapshot_path,
        target_date=target,
        platform=getattr(args, "exchange_economics_platform", exchange_economics.DEFAULT_PLATFORM),
        now=getattr(args, "as_of", None),
    )
    payload["snapshot_refresh"] = refresh
    if refresh.get("status") == "BLOCK":
        payload["status"] = "BLOCK"
        payload.setdefault("blockers", []).insert(0, {
            "code": "exchange_economics_snapshot_refresh_failed",
            "detail": refresh.get("reason") or "exchange economics snapshot refresh failed",
        })
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
        "snapshot_refresh_status": refresh.get("status"),
        "snapshot_refresh_target_date": refresh.get("target_date"),
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


def _settled_taker_permission_tapes(taker_root):
    root = Path(taker_root)
    if not root.exists():
        return []
    paths = []
    for run_folder in sorted(path for path in root.glob("*/*") if path.is_dir()):
        counterfactual = run_folder / "settled_counterfactual_orders_long.csv"
        settled = run_folder / "settled_orders_long.csv"
        if counterfactual.exists():
            paths.append(counterfactual)
        elif settled.exists():
            paths.append(settled)
    return paths


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


def run_taker_edge_permission_map_step(args):
    if getattr(args, "skip_taker_edge_permission_map", False):
        return {"status": "SKIPPED", "reason": "skip_taker_edge_permission_map"}
    paths = _settled_taker_permission_tapes(getattr(args, "taker_root", taker_bot.DEFAULT_RUNS_ROOT))
    out = getattr(args, "taker_edge_permission_map_out", "") or backtest_path(args, "taker_edge_permission_map.json")
    if not paths:
        payload = taker_edge_permission.write_taker_edge_permission_map(
            out,
            rows=[],
            now=getattr(args, "as_of", None),
            source_artifacts=[],
        )
        return {
            "status": "NO_DATA",
            "json_out": as_path(out),
            "source_tape_count": 0,
            "record_count": 0,
            "edge_allowed_count": 0,
            "observe_count": 0,
            "deny_count": 0,
        }
    payload = taker_edge_permission.build_taker_edge_permission_map_from_tapes(
        paths,
        now=getattr(args, "as_of", None),
        min_settled_orders=getattr(args, "taker_edge_permission_min_settled_orders", 5),
        min_independent_days=getattr(args, "taker_edge_permission_min_independent_days", 3),
        min_after_fee_skill=getattr(args, "taker_edge_permission_min_after_fee_skill", 0.0),
        source_artifacts=[str(path) for path in paths],
    )
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    summary = payload.get("summary") or {}
    return {
        "status": "PASS",
        "json_out": as_path(out_path),
        "source_tape_count": len(paths),
        "record_count": summary.get("record_count"),
        "edge_allowed_count": summary.get("edge_allowed_count"),
        "observe_count": summary.get("observe_count"),
        "deny_count": summary.get("deny_count"),
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
    runs_root = getattr(args, "mm_root", mm_paper.DEFAULT_RUNS_ROOT)
    latest_runs = int(
        getattr(
            args,
            "maker_paper_latest_active_runs",
            DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS,
        )
    )
    max_input_bytes = int(
        getattr(
            args,
            "maker_paper_max_input_bytes",
            DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES,
        )
    )
    if latest_runs <= 0 or max_input_bytes <= 0:
        raise ValueError("maker paper run-count and input-byte bounds must be positive")
    discovered = mm_paper.discover_run_folders(runs_root)
    selected, selection = mm_paper.select_run_folders_for_paper(
        discovered,
        latest_n=latest_runs,
        evidence_mode=mm_paper.ACTIVE_DAY_EVIDENCE_MODE,
    )
    input_paths = [
        path
        for folder in selected
        for path in (
            Path(folder) / "quote_intents_long.csv",
            Path(folder) / "model_variant_quote_intents_long.csv",
        )
        if path.exists()
    ]
    input_bytes = sum(path.stat().st_size for path in input_paths)
    input_preflight = {
        "status": "PASS" if input_bytes <= max_input_bytes else "BLOCK",
        "reason": None if input_bytes <= max_input_bytes else "maker_paper_input_budget_exceeded",
        "evidence_mode": mm_paper.ACTIVE_DAY_EVIDENCE_MODE,
        "latest_run_limit": latest_runs,
        "selected_run_count": len(selected),
        "available_run_count": selection.get("available_run_folders_before_selection"),
        "input_file_count": len(input_paths),
        "input_bytes": input_bytes,
        "max_input_bytes": max_input_bytes,
        "selected_run_folders": [str(path) for path in selected],
    }
    if input_preflight["status"] == "BLOCK":
        return {
            "status": "BLOCK",
            "reason": input_preflight["reason"],
            "input_preflight": input_preflight,
            "selected_run_count": len(selected),
            "input_bytes": input_bytes,
            "max_input_bytes": max_input_bytes,
        }
    payload = mm_paper.build_paper_payload(
        runs_root=runs_root,
        snapshots_root=getattr(args, "snapshots_root", mm_paper.DEFAULT_SNAPSHOTS_ROOT),
        backtest_root=backtest_root,
        run_folder_latest_n=latest_runs,
        run_folder_evidence_mode=mm_paper.ACTIVE_DAY_EVIDENCE_MODE,
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
    payload["input_preflight"] = input_preflight
    payload.setdefault("summary", {})["input_preflight"] = {
        key: input_preflight[key]
        for key in (
            "status",
            "evidence_mode",
            "latest_run_limit",
            "selected_run_count",
            "input_file_count",
            "input_bytes",
            "max_input_bytes",
        )
    }
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
        "selected_run_count": len(selected),
        "input_bytes": input_bytes,
        "max_input_bytes": max_input_bytes,
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


def _provisional_target_blocker_slugs(payload, gate, target):
    """Event slugs to re-reconcile when a target-date gate blocked purely on
    PROVISIONAL reconciliation.

    Polymarket resolution can lag the morning finalize by an hour or two
    (2026-07-05: three July-4 labels were PROVISIONAL at the 10:47 audit and
    reconciled `match` by early afternoon, but the day's chain was already
    lost). Only a pure-PROVISIONAL block is retried; disagreements, missing
    rows, or any other blocker class still needs a human.
    """
    blockers = gate.get("blockers") or []
    if not blockers or not all(str(b).endswith(":PROVISIONAL") for b in blockers):
        return []
    return sorted({
        row.get("event_slug")
        for row in payload.get("rows") or []
        if row.get("target_date") == target
        and row.get("promotion_blocker")
        and str(row.get("status") or "").upper() == "PROVISIONAL"
        and row.get("event_slug")
    })


def _merge_labels_into_csv(labels_csv, labels):
    """Update specific rows of the labels CSV without dropping the rest.

    finalize_folders/write_labels_csv rewrite the whole CSV from the labels
    passed, so a subset re-finalize must merge by event_slug instead.
    """
    path = Path(labels_csv)
    existing = []
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = [row for row in csv.DictReader(handle) if row.get("event_slug")]
    by_slug = {row.get("event_slug"): row for row in existing}
    for label in labels:
        if label.get("event_slug"):
            by_slug[label["event_slug"]] = label
    merged = sorted(
        by_slug.values(),
        key=lambda row: (str(row.get("market_id") or ""), str(row.get("target_date") or "")),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in merged:
            writer.writerow(row)


def _retry_provisional_reconciliation(args, slugs):
    snapshots_root = Path(getattr(args, "snapshots_root", "") or "")
    labels = []
    missing = []
    for slug in slugs:
        folder = snapshots_root / slug
        if not folder.exists():
            missing.append(slug)
            continue
        label = finalize_folder(
            folder,
            daily_summary_path=getattr(args, "daily_summary", "") or None,
            overrides=parse_overrides(getattr(args, "settle", None)),
            interval_minutes=getattr(args, "interval_minutes", 10.0),
            gap_tolerance=getattr(args, "tolerance", 1.5),
            reconcile_polymarket=not getattr(args, "skip_polymarket_reconciliation", False),
            ledger_root=getattr(args, "ledger_root", DEFAULT_LEDGER_ROOT),
        )
        if label:
            labels.append(label)
    if labels:
        _merge_labels_into_csv(getattr(args, "labels_csv", DEFAULT_LABELS_CSV), labels)
    return {
        "attempted_slugs": list(slugs),
        "refinalized_count": len(labels),
        "missing_folders": missing,
        "statuses": sorted({
            f"{label.get('market_id')}:{label.get('reconciliation_status')}" for label in labels
        }),
    }


def run_settlement_source_audit_step(args):
    if getattr(args, "skip_settlement_source_audit", False):
        return {"status": "SKIPPED", "reason": "skip_settlement_source_audit"}
    payload = settlement_source_audit.build_settlement_source_audit(
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        ledger_root=getattr(args, "ledger_root", DEFAULT_LEDGER_ROOT),
        generated_at_utc=utc_iso(),
    )
    # The settled-day analysis barrier asserts truth-label proof for the day
    # being analyzed; item 319 ratified that historical non-proof-grade labels
    # (permanent capture-gap days) must not fail-close current settled-day
    # analysis. Gate the step on the analyzed target date and keep the global
    # audit outcome visible alongside it.
    target = settled_analysis_target_date(args).isoformat()
    gate = settlement_source_audit.settlement_label_gate_for_target_dates(payload, [target])
    reconciliation_retry = None
    if gate.get("status") == "BLOCK":
        retry_slugs = _provisional_target_blocker_slugs(payload, gate, target)
        if retry_slugs:
            reconciliation_retry = _retry_provisional_reconciliation(args, retry_slugs)
            if reconciliation_retry.get("refinalized_count"):
                payload = settlement_source_audit.build_settlement_source_audit(
                    labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
                    ledger_root=getattr(args, "ledger_root", DEFAULT_LEDGER_ROOT),
                    generated_at_utc=utc_iso(),
                )
                gate = settlement_source_audit.settlement_label_gate_for_target_dates(
                    payload, [target]
                )
    json_out, report_out = settlement_source_audit.write_outputs(
        payload,
        json_out=backtest_path(args, "settlement_source_revision_audit.json"),
        report_out=backtest_path(args, "settlement_source_revision_audit.md"),
    )
    summary = payload.get("summary") or {}
    return {
        "status": gate.get("status"),
        "target_date": target,
        "target_date_gate_blockers": gate.get("blockers") or [],
        "target_date_non_countable_reconciled": gate.get("non_countable_reconciled") or [],
        "reconciliation_retry": reconciliation_retry,
        "global_status": payload.get("status"),
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
        "mm_maker_countability_gate_status": (mm.get("maker_countability_gate") or {}).get("status"),
        "mm_maker_countability_blockers": (mm.get("maker_countability_gate") or {}).get("blockers") or [],
        "mm_blocks_maker_evidence_countability": mm.get("blocks_maker_evidence_countability"),
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
