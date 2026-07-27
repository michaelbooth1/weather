"""Daily refresh source, ingest, event, and settlement-label steps."""

from __future__ import annotations

import json
import time
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
from weather.sources.wu_history import (
    PUBLIC_WU_HISTORY_SOURCE,
    TRANSIENT_FAILURE,
    PublicWundergroundHistoryClient,
    WundergroundHistoryStore,
    failure_class_for_exception,
)


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _market_ids(value):
    if value in (None, "", "all"):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _restore_specs(value):
    specs = list(all_specs())
    requested = _market_ids(value)
    if not requested:
        return specs
    by_id = {spec.id: spec for spec in specs}
    missing = [market_id for market_id in requested if market_id not in by_id]
    if missing:
        raise ValueError(f"unknown WU settlement restore market(s): {', '.join(missing)}")
    return [by_id[market_id] for market_id in requested]


def _daily_row_for_target(daily_rows, target_date):
    target = target_date.isoformat()
    for row in daily_rows or []:
        if str(row.get("local_date") or "") == target:
            return row
    return None


def _daily_row_has_settlement_value(row):
    if not row:
        return False
    row_count = _daily_row_count(row)
    bucket = (
        row.get("max_temp_bucket_native")
        or row.get("max_temp_bucket")
        or row.get("max_temp_bucket_c")
    )
    return row_count > 0 and bucket not in (None, "")


def _daily_row_count(row):
    try:
        return int(float((row or {}).get("row_count") or 0))
    except (TypeError, ValueError):
        return 0


def _store_for_wu_restore(spec):
    return WundergroundHistoryStore(
        spec.data_root,
        station_icao=spec.icao,
        station_name=spec.city_label,
        history_id=spec.wu_history_id,
        tz=spec.tz,
        unit=spec.display_unit,
        wu_units=spec.wu_units,
    )


def run_public_wu_settlement_restore_step(args):
    if getattr(args, "skip_public_wu_settlement_restore", False):
        return {"status": "SKIPPED", "reason": "skip_public_wu_settlement_restore"}

    target = settled_analysis_target_date(args)
    market_specs = _restore_specs(getattr(args, "wu_settlement_restore_markets", "all"))
    sleep_seconds = getattr(args, "wu_settlement_restore_sleep", 0.2)
    timeout = getattr(args, "wu_settlement_restore_timeout", 30)
    skip_existing = getattr(args, "wu_settlement_restore_skip_existing", True)
    continue_on_error = getattr(args, "wu_settlement_restore_continue_on_error", True)
    retries = max(0, int(getattr(args, "wu_settlement_restore_retries", 2) or 0))
    retry_backoff = max(0.0, float(getattr(args, "wu_settlement_restore_retry_backoff", 5.0) or 0.0))

    rows = []
    fetched_range_count = 0
    error_count = 0
    restored_count = 0
    reused_raw_count = 0
    transient_retry_count = 0
    for spec in market_specs:
        store = _store_for_wu_restore(spec)
        had_raw_before = target in store.raw_dates()
        ranges = (
            store.missing_ranges(target, target, chunk_days=1)
            if skip_existing
            else [(target, target)]
        )
        market_errors = []
        fetched_ranges = []
        market_retries = 0
        if ranges:
            client = PublicWundergroundHistoryClient(
                sleep_seconds=sleep_seconds,
                timeout=timeout,
                history_id=spec.wu_history_id,
                station_icao=spec.icao,
                units=spec.wu_units,
            )
            for chunk_start, chunk_end in ranges:
                # One transient read timeout on one market used to BLOCK this whole step,
                # which refuses label finalization for every market and hard-stops the
                # pipeline at the settled-day barrier: on 2026-07-27 a single 30s timeout
                # on denver/KBKF cost the 23 downstream steps, including the learning and
                # model-vs-market scoring passes. "Transient" means try again, so try again
                # before recording a failure; anything else still fails on the first look.
                for attempt in range(retries + 1):
                    try:
                        payload = client.fetch_range(chunk_start, chunk_end, units=spec.wu_units)
                    except Exception as exc:  # noqa: BLE001 - record source failures and continue by default.
                        transient = failure_class_for_exception(exc) == TRANSIENT_FAILURE
                        if transient and attempt < retries:
                            market_retries += 1
                            transient_retry_count += 1
                            time.sleep(retry_backoff * (2 ** attempt))
                            continue
                        error_count += 1
                        error = store.write_fetch_error(
                            chunk_start,
                            chunk_end,
                            exc,
                            source=PUBLIC_WU_HISTORY_SOURCE,
                        )
                        market_errors.append(error)
                        if not continue_on_error:
                            raise
                        break
                    store.write_payload(chunk_start, chunk_end, payload)
                    fetched_range_count += 1
                    fetched_ranges.append({
                        "start": chunk_start.isoformat(),
                        "end": chunk_end.isoformat(),
                        "observation_count": len(payload.get("observations", []) or []),
                    })
                    break

        hourly_rows, daily_rows = store.rebuild_normalized_files()
        daily_row = _daily_row_for_target(daily_rows, target)
        raw_exists = target in store.raw_dates()
        daily_ready = _daily_row_has_settlement_value(daily_row)
        target_hourly_count = sum(
            1 for row in hourly_rows
            if str(row.get("local_date") or "") == target.isoformat()
        )
        if daily_ready:
            restored_count += 1
        if had_raw_before and raw_exists and not fetched_ranges:
            reused_raw_count += 1
        status = "PASS" if raw_exists and daily_ready and not market_errors else "BLOCK"
        rows.append({
            "market_id": spec.id,
            "station": spec.icao,
            "history_id": spec.wu_history_id,
            "data_root": as_path(store.root),
            "target_date": target.isoformat(),
            "status": status,
            "raw_existed_before": had_raw_before,
            "raw_exists_after": raw_exists,
            "fetched_ranges": fetched_ranges,
            "fetched_range_count": len(fetched_ranges),
            "target_hourly_row_count": target_hourly_count,
            "daily_summary_path": as_path(store.daily_root / "daily_summary.csv"),
            "daily_summary_row_present": bool(daily_row),
            "daily_summary_row_count": _daily_row_count(daily_row),
            "daily_summary_bucket": (
                (daily_row or {}).get("max_temp_bucket_native")
                or (daily_row or {}).get("max_temp_bucket")
                or (daily_row or {}).get("max_temp_bucket_c")
            ),
            "error_count": len(market_errors),
            "errors": market_errors,
            "transient_retry_count": market_retries,
        })

    blocked = [row for row in rows if row.get("status") != "PASS"]
    payload = {
        "schema_version": schema_version("public_wu_settlement_restore"),
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blocked else "BLOCK",
        "target_date": target.isoformat(),
        "source": PUBLIC_WU_HISTORY_SOURCE,
        "market_count": len(rows),
        "restored_market_count": restored_count,
        "reused_raw_market_count": reused_raw_count,
        "fetched_range_count": fetched_range_count,
        "error_count": error_count,
        "transient_retry_count": transient_retry_count,
        "blocked_market_count": len(blocked),
        "blocked_markets": [row.get("market_id") for row in blocked],
        "skip_existing": bool(skip_existing),
        "continue_on_error": bool(continue_on_error),
        "markets": rows,
    }
    json_out = write_json(backtest_path(args, "public_wu_settlement_restore.json"), payload)
    detail_json_out = write_json(
        backtest_path(args, f"public_wu_settlement_restore_{target.isoformat()}.json"),
        payload,
    )
    return {
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "json_out": as_path(json_out),
        "detail_json_out": as_path(detail_json_out),
        "market_count": payload.get("market_count"),
        "restored_market_count": payload.get("restored_market_count"),
        "reused_raw_market_count": payload.get("reused_raw_market_count"),
        "fetched_range_count": payload.get("fetched_range_count"),
        "error_count": payload.get("error_count"),
        # Surfaced so a fetch that only succeeded on retry is visible in the chain status
        # rather than looking indistinguishable from a clean first-try run.
        "transient_retry_count": payload.get("transient_retry_count"),
        "blocked_market_count": payload.get("blocked_market_count"),
        "blocked_markets": payload.get("blocked_markets") or [],
    }


def summarize_labels(labels):
    quality_counts = Counter(label.get("quality_grade") or "unknown" for label in labels)
    reconciliation_counts = Counter(label.get("reconciliation_status") or "-" for label in labels)
    material_coverage_counts = Counter(label.get("material_coverage_grade") or "missing" for label in labels)
    complete_by_market = Counter(
        label.get("market_id") or "unknown"
        for label in labels
        if label.get("quality_grade") == "complete"
    )
    promotion_countability_available = any("promotion_countable" in label for label in labels)
    promotion_countable_labels = (
        [label for label in labels if _truthy(label.get("promotion_countable"))]
        if promotion_countability_available
        else []
    )
    promotion_blocked_labels = (
        [label for label in labels if not _truthy(label.get("promotion_countable"))]
        if promotion_countability_available
        else []
    )
    return {
        "label_count": len(labels),
        "quality_counts": dict(sorted(quality_counts.items())),
        "reconciliation_counts": dict(sorted(reconciliation_counts.items())),
        "material_coverage_counts": dict(sorted(material_coverage_counts.items())),
        "promotion_countability_available": promotion_countability_available,
        "promotion_countable_label_count": len(promotion_countable_labels),
        "promotion_blocked_label_count": len(promotion_blocked_labels),
        "material_coverage_blocked_sample": [
            {
                "event_slug": label.get("event_slug"),
                "market_id": label.get("market_id"),
                "target_date": label.get("target_date"),
                "quality_grade": label.get("quality_grade"),
                "material_coverage_grade": label.get("material_coverage_grade"),
                "material_coverage_reason": label.get("material_coverage_reason"),
                "promotion_countable_reason": label.get("promotion_countable_reason"),
                "coverage_reason": label.get("coverage_reason"),
            }
            for label in promotion_blocked_labels[:5]
        ],
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
    steps_so_far = getattr(args, "_daily_refresh_steps_so_far", None)
    if steps_so_far is not None:
        restore_step = next(
            (step for step in steps_so_far if step.get("name") == "public_wu_settlement_restore"),
            None,
        )
        restore_status = ((restore_step or {}).get("result") or {}).get("status")
        if restore_step is not None and restore_status != "PASS":
            return {
                "status": "BLOCK",
                "reason": "public_wu_settlement_restore_not_passed",
                "restore_status": restore_status,
                "target_date": ((restore_step.get("result") or {}).get("target_date")),
            }
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


