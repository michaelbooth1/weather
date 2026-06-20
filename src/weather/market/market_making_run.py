"""Date/budget market-making run orchestrator.

The pure policy module decides whether a single band should quote. This module
owns operator concerns around target-date discovery, run folders, preflight
gates, budget accounting, and fail-closed shadow/paper run artifacts.
"""

from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import csv
import hashlib
import json
import math
import time
from collections import Counter
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from weather.market.market_config import config_for_date, ensure_date
from weather.market.info_event_calendar import summarize_event_gate_rows
from weather.market.market_microstructure import audit_book_tape
from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.mm_policy import (
    DEFAULT_OBSERVATION_STATUS,
    DEFAULT_KNOWN_EDGE_MAP,
    DEFAULT_POLICY_CONFIG,
    DEFAULT_PROMOTION_REFRESH,
    DEFAULT_SNAPSHOTS_ROOT,
    POLICY_VERSION,
    QUOTE_COLUMNS,
    SCHEMA_VERSION as POLICY_SCHEMA_VERSION,
    apply_known_edge_permission,
    bool_value,
    clamp_probability,
    config_with_clob_recon,
    decide_quote,
    first_present,
    load_clob_feature_index,
    load_known_edge_map,
    load_latest_snapshot_rows,
    load_observation_status,
    load_promotion_states,
    maybe_float,
    parse_config_overrides,
    parse_time,
    policy_hash,
    resolve_known_edge_record,
    source_freshness_state_from_rows,
    utc_now,
)
from weather.market.market_making_run_constants import (  # noqa: E402
    DEFAULT_DATA_LAYER_AUDIT,
    DEFAULT_PLATFORM_VERIFICATION,
    DEFAULT_QUOTE_TTL_SECONDS,
    DEFAULT_RUNS_ROOT,
    FILL_COLUMNS,
    PLATFORM_VERIFICATION_SCHEMA_VERSION,
    RUN_EXTRA_COLUMNS,
    RUN_MODES,
    RUN_QUOTE_COLUMNS,
    SCHEMA_VERSION,
)
from weather.market.market_making_run_support import (  # noqa: E402
    add_run_columns,
    append_csv,
    append_jsonl,
    apply_run_budget,
    assemble_policy_inputs_for_market,
    boolish_active,
    budget_exhausted_row,
    cancel_all_row,
    classify_zero_trade_root_cause,
    latest_book_rows,
    latest_clob_feature_rows,
    latest_rows_for_snapshot,
    lifecycle_blocked_by_budget_events,
    lifecycle_fill_transition,
    lifecycle_post_events,
    lifecycle_release_event,
    lifecycle_reserved_usdc,
    lifecycle_summary,
    load_live_readiness,
    load_open_lifecycle_orders,
    last_reserved_from_ledger,
    make_run_id,
    market_ids_from_arg,
    metadata_from_books,
    normalize_mode,
    placeholder_no_quote,
    preflight_market,
    preflight_no_quote,
    quote_leg_intents,
    quote_risk_usdc,
    read_csv_rows,
    read_json,
    read_jsonl_rows,
    row_key_without_token,
    run_folder_for,
    selected_specs,
    source_status_for_snapshot,
    source_status_is_current,
    write_csv,
    write_json,
)
from weather.market.live_forward_gate import build_live_forward_gate
from weather.market.live_observation_normalization import (
    current_high_probability_summary,
    normalized_high_for_market,
)
from weather.market.market_making_evidence import (
    EVIDENCE_MODE_AUTO,
    EVIDENCE_MODE_CHOICES,
    classify_market_making_evidence,
)
from weather.operations.runtime_identity import (  # noqa: E402
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.operations.power import keep_system_awake
from weather.market.market_making_preflight import (  # noqa: E402
    REMEDIATION_RULES,
    SECRET_FIELD_NAMES,
    SUPPORTED_PLATFORM_IDS,
    SUPPORTED_SIGNATURE_TYPE_IDS,
    SUPPORTED_SIGNATURE_TYPES,
    build_preflight_remediation,
    contains_secret_material,
    load_data_layer_live_gate,
    load_platform_verification_gate,
    non_empty_text,
    recent_utc_timestamp,
    remediation_last_good_artifact,
    remediation_risk_events,
    supported_signature_type,
)

SNAPSHOT_LOOP_STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "loop_status.json"
CLOB_LOOP_STATUS_PATH = DEFAULT_SNAPSHOTS_ROOT / "clob_loop_status.json"


def runtime_identity_snapshot(observation_status_path=DEFAULT_OBSERVATION_STATUS):
    current = get_runtime_identity()

    def loop_row(name, path):
        status = read_json(path, {}) or {}
        process = status.get("runtime_identity") or {}
        if process:
            matches = identities_match(process, current)
            code_state = "current" if matches else "different"
        else:
            matches = None
            code_state = "unknown"
        return {
            "name": name,
            "status_path": str(path),
            "pid": status.get("pid"),
            "last_heartbeat": status.get("last_heartbeat"),
            "consecutive_errors": status.get("consecutive_errors"),
            "last_error": status.get("last_error"),
            "runtime_code_state": code_state,
            "runtime_identity_matches_current": matches,
            "process_identity": process,
            "process_identity_text": format_runtime_identity(process),
            "current_identity_text": format_runtime_identity(current),
        }

    loops = [
        loop_row("weather_snapshots", SNAPSHOT_LOOP_STATUS_PATH),
        loop_row("clob_books", CLOB_LOOP_STATUS_PATH),
        loop_row("observation_triggers", observation_status_path),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "current_identity": current,
        "current_identity_text": format_runtime_identity(current),
        "loops": loops,
        "drift_count": sum(1 for row in loops if row.get("runtime_identity_matches_current") is False),
    }


def tape_integrity_summary(path, expected_rows, row_kind):
    actual_rows = len(read_csv_rows(path))
    expected_rows = int(expected_rows or 0)
    status = "PASS" if actual_rows == expected_rows else "WARN"
    return {
        "status": status,
        "path": str(path),
        "row_kind": row_kind,
        "expected_rows": expected_rows,
        "actual_rows": actual_rows,
        "detail": (
            f"{row_kind} tape row count matches summary"
            if status == "PASS"
            else f"{row_kind} tape has {actual_rows} rows but summary expected {expected_rows}"
        ),
    }


def cumulative_run_summary(run_folder, fallback_quote_rows=None, fallback_lifecycle=None):
    run_folder = Path(run_folder)
    quote_rows = read_csv_rows(run_folder / "quote_intents_long.csv")
    if not quote_rows:
        quote_rows = list(fallback_quote_rows or [])
    lifecycle_rows = read_jsonl_rows(run_folder / "order_lifecycle.jsonl")
    generated_times = sorted({
        str(row.get("generated_at_utc") or "")
        for row in quote_rows
        if row.get("generated_at_utc")
    })
    transition_counts = Counter(
        row.get("transition") or row.get("event") or "-"
        for row in lifecycle_rows
    )
    current_lifecycle = fallback_lifecycle or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "tick_count": len(generated_times),
        "row_count": len(quote_rows),
        "quote_permission_rows": sum(1 for row in quote_rows if bool_value(row.get("quote_permission"))),
        "live_trade_permission_rows": sum(1 for row in quote_rows if bool_value(row.get("live_trade_permission"))),
        "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
        "information_event_gate": summarize_event_gate_rows(quote_rows),
        "first_tick_utc": generated_times[0] if generated_times else None,
        "last_tick_utc": generated_times[-1] if generated_times else None,
        "order_lifecycle_transition_counts": dict(sorted(transition_counts.items())),
        "paper_posted_count": transition_counts.get("paper_posted", 0),
        "live_posted_count": transition_counts.get("live_posted", 0),
        "intended_count": transition_counts.get("intended", 0),
        "replaced_count": transition_counts.get("replaced", 0),
        "released_count": transition_counts.get("released", 0),
        "expired_count": transition_counts.get("expired", 0),
        "blocked_by_preflight_count": transition_counts.get("blocked_by_preflight", 0),
        "canceled_count": transition_counts.get("canceled", 0),
        "open_order_count": current_lifecycle.get("current_open_order_count", 0),
        "budget_reserved_usdc": current_lifecycle.get("current_reserved_usdc", 0.0),
        "budget_released_last_tick_usdc": current_lifecycle.get("released_this_tick_usdc", 0.0),
    }


def build_run_config_payload(
    run_id,
    target_date,
    budget_usdc,
    mode,
    specs,
    run_folder,
    snapshots_root,
    promotion_refresh,
    known_edge_map,
    observation_status_path,
    policy_config,
    now,
    evidence_classification=None,
):
    evidence_classification = evidence_classification or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat(),
        "mode": mode,
        "budget_usdc": float(budget_usdc),
        "markets": [spec.id for spec in specs],
        "run_folder": str(run_folder),
        "snapshots_root": str(snapshots_root),
        "promotion_refresh": str(promotion_refresh),
        "known_edge_map": str(known_edge_map),
        "observation_status_path": str(observation_status_path),
        "policy_version": policy_config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(policy_config),
        "policy_config": policy_config,
        "evidence_mode": evidence_classification.get("evidence_mode"),
        "evidence_classification": evidence_classification,
        "shadow_safety": {
            "loads_private_keys": False,
            "posts_orders": False,
            "live_trade_permission_allowed": mode == "live-pilot",
        },
    }


def apply_evidence_mode_to_live_forward_gate(live_forward_gate, evidence_classification=None):
    payload = dict(live_forward_gate or {})
    evidence_classification = evidence_classification or {}
    raw_counts = bool(payload.get("counts_toward_live_forward_gate"))
    evidence_counts = bool(evidence_classification.get("counts_toward_live_forward_gate"))
    final_counts = bool(raw_counts and evidence_counts)
    evidence_mode = evidence_classification.get("evidence_mode")
    reason = evidence_classification.get("reason") or "evidence mode is not countable"

    payload["status_without_evidence_mode"] = payload.get("status")
    payload["evidence_mode"] = evidence_mode
    payload["evidence_classification"] = evidence_classification
    payload["counts_toward_live_forward_gate_without_evidence_mode"] = raw_counts
    payload["counts_toward_live_forward_gate_after_evidence_mode"] = final_counts
    payload["counts_toward_live_forward_gate"] = final_counts
    payload["evidence_mode_gate"] = {
        "name": "evidence_mode",
        "ok": evidence_counts,
        "severity": None if evidence_counts else "block",
        "detail": reason,
        "evidence_mode": evidence_mode,
        "counts_toward_live_forward_gate": evidence_counts,
    }
    if not evidence_counts:
        summary = dict(payload.get("summary") or {})
        failure_counts = dict(summary.get("first_failing_gate_counts") or {})
        failure_counts["evidence_mode"] = failure_counts.get("evidence_mode", 0) + 1
        summary["first_failing_gate_counts"] = dict(sorted(failure_counts.items()))
        summary["evidence_mode_reason"] = reason
        payload["summary"] = summary
    payload["status"] = "PASS" if final_counts else "BLOCK"
    return payload


def build_report(
    run_config,
    preflight,
    quote_rows,
    budget_ledger,
    lifecycle=None,
    remediation=None,
    cumulative=None,
    event_gate=None,
    live_forward_gate=None,
    evidence_classification=None,
    tape_integrity=None,
):
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    quote_rows_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    live_rows = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    lifecycle = lifecycle or {}
    remediation = remediation or {}
    cumulative = cumulative or {}
    live_forward_gate = live_forward_gate or {}
    evidence_classification = evidence_classification or {}
    tape_integrity = tape_integrity or {}
    evidence_counts = bool(evidence_classification.get("counts_toward_live_forward_gate"))
    live_gate_counts = bool(live_forward_gate.get("counts_toward_live_forward_gate"))
    final_counts = bool(evidence_counts and live_gate_counts)
    if not evidence_counts:
        countability_reason = evidence_classification.get("reason") or "evidence mode is not countable"
    elif not live_gate_counts:
        countability_reason = "live-forward gate failed"
    else:
        countability_reason = "active-day evidence and live-forward gate both count"
    reserved = maybe_float(lifecycle.get("current_reserved_usdc"))
    if reserved is None:
        reserved = max((maybe_float(row.get("reserved_usdc")) or 0.0 for row in budget_ledger), default=0.0)
    budget = float(run_config["budget_usdc"])
    selected = ", ".join(run_config["markets"]) or "-"
    blocked_markets = [
        row["market_id"]
        for row in preflight.get("markets", [])
        if row.get("status") != "PASS"
    ]
    encoding_issue_count = sum(
        int(((row.get("csv_encoding") or {}).get("issue_count")) or 0)
        for row in preflight.get("markets", [])
    )
    encoding_quarantined_rows = sum(
        int(((row.get("csv_encoding") or {}).get("quarantined_row_count")) or 0)
        for row in preflight.get("markets", [])
    )
    if quote_rows_count:
        quote_outcome = "quoted"
    elif preflight.get("status") in {"BLOCK", "STALE", "WARN"}:
        quote_outcome = "preflight_blocked"
    elif not quote_rows:
        quote_outcome = "crashed_before_scoring"
    else:
        quote_outcome = "policy_no_quote"
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        preflight.get("markets") or [],
        permission_rows=quote_rows_count,
        output_rows=len(quote_rows),
    )
    lines = [
        "# Market-Making Run Report",
        "",
        f"Generated: {preflight.get('generated_at_utc')}",
        f"Run ID: `{run_config['run_id']}`",
        f"Mode: `{run_config['mode']}`",
        f"Target date: `{run_config['target_date']}`",
        f"Selected markets: {selected}",
        "",
        "## Summary",
        "",
        f"- Preflight status: `{preflight.get('status')}`",
        f"- Latest-tick quote rows: `{quote_rows_count}`",
        f"- Quote outcome: `{quote_outcome}`",
        f"- Latest-tick no-quote rows: `{len(quote_rows) - quote_rows_count}`",
        f"- Zero-trade root cause: `{zero_trade_diagnosis.get('root_cause_class')}`",
        f"- First failing gate: `{zero_trade_diagnosis.get('first_failing_gate') or '-'}`",
        f"- Zero trades expected: `{str(zero_trade_diagnosis.get('zero_trades_expected')).lower()}`",
        f"- Latest-tick live-trade permission rows: `{live_rows}`",
        f"- Cumulative ticks: `{cumulative.get('tick_count', 1 if quote_rows else 0)}`",
        f"- Cumulative quote rows: `{cumulative.get('quote_permission_rows', quote_rows_count)}`",
        f"- Cumulative paper-posted lifecycle legs: `{cumulative.get('paper_posted_count', 0)}`",
        (
            f"- Quote tape integrity: `{tape_integrity.get('status') or '-'}` "
            f"({tape_integrity.get('actual_rows', 0)}/{tape_integrity.get('expected_rows', 0)} rows)"
        ),
        f"- Budget reserved: `{reserved:.2f}` / `{budget:.2f}` USDC",
        f"- Remaining budget: `{max(0.0, budget - reserved):.2f}` USDC",
        f"- Open lifecycle orders: `{lifecycle.get('current_open_order_count', 0)}`",
        f"- Released this tick: `{float(lifecycle.get('released_this_tick_usdc') or 0.0):.2f}` USDC",
        f"- Preflight remediation incidents: `{remediation.get('incident_count', 0)}`",
        f"- CSV encoding issues: `{encoding_issue_count}` files / `{encoding_quarantined_rows}` rows",
        f"- Evidence mode: `{evidence_classification.get('evidence_mode', '-')}`",
        f"- Evidence mode reason: `{countability_reason}`",
        f"- Counts toward live-forward gate: `{str(final_counts).lower()}`",
        "",
        "## Preflight By Market",
        "",
        "| Market | Status | Event | Rows | Encoding | Detail |",
        "| :--- | :--- | :--- | ---: | :--- | :--- |",
    ]
    for row in preflight.get("markets", []):
        details = row.get("blocking_reasons") or row.get("stale_reasons") or ["ok"]
        encoding = row.get("csv_encoding") or {}
        encoding_text = (
            f"{encoding.get('status')} ({encoding.get('quarantined_row_count', 0)} rows)"
            if encoding
            else "-"
        )
        lines.append(
            f"| {row.get('market_id')} | {row.get('status')} | {row.get('event_slug')} | "
            f"{row.get('snapshot_rows', 0)} | {encoding_text} | {'; '.join(details)} |"
        )
    high_rows = [
        (row.get("market_id"), row.get("current_high_assessment") or {})
        for row in preflight.get("markets", [])
        if row.get("current_high_assessment")
    ]
    if high_rows:
        lines.extend([
            "",
            "## Current High Assessment",
            "",
            "| Market | Raw high | Settlement high | Raw prob | Settlement prob | Revision |",
            "| :--- | ---: | ---: | ---: | ---: | :--- |",
        ])
        for market_id, assessment in high_rows:
            lines.append(
                f"| {market_id} | {assessment.get('raw_current_high') if assessment.get('raw_current_high') is not None else '-'} | "
                f"{assessment.get('settlement_current_high') if assessment.get('settlement_current_high') is not None else '-'} | "
                f"{assessment.get('probability_on_raw_current_high')} | "
                f"{assessment.get('probability_on_settlement_current_high')} | "
                f"{assessment.get('revision_state') or '-'} |"
            )
    lines.extend([
        "",
        "## Quote Reasons",
        "",
        "| Reason | Rows |",
        "| :--- | ---: |",
    ])
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"| {reason or '-'} | {count} |")
    if cumulative:
        lines.extend([
            "",
            "## Cumulative Run",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| Ticks | {cumulative.get('tick_count', 0)} |",
            f"| Rows | {cumulative.get('row_count', 0)} |",
            f"| Quote rows | {cumulative.get('quote_permission_rows', 0)} |",
            f"| Live-trade rows | {cumulative.get('live_trade_permission_rows', 0)} |",
            f"| Paper posted legs | {cumulative.get('paper_posted_count', 0)} |",
            f"| Replaced legs | {cumulative.get('replaced_count', 0)} |",
            f"| Released legs | {cumulative.get('released_count', 0)} |",
            f"| Blocked-by-preflight legs | {cumulative.get('blocked_by_preflight_count', 0)} |",
        ])
    event_gate = event_gate or {}
    if event_gate:
        lines.extend([
            "",
            "## Information Event Gate",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| Pull rows | {event_gate.get('pull_rows', 0)} |",
            f"| Widen rows | {event_gate.get('widen_rows', 0)} |",
            f"| Exception rows | {event_gate.get('exception_rows', 0)} |",
            f"| Quote rows during event | {event_gate.get('quote_rows_during_event', 0)} |",
        ])
        active = event_gate.get("active_events") or []
        if active:
            lines.extend([
                "",
                "| Active event | Market | Class | Action | Ends |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for event in active[:12]:
                lines.append(
                    f"| {event.get('event_id')} | {event.get('market_id')} | "
                    f"{event.get('event_class')} | {event.get('action')} | "
                    f"{event.get('ends_at_utc')} |"
                )
        next_events = event_gate.get("next_events") or []
        if next_events:
            lines.extend([
                "",
                "| Next event | Market | Class | Starts |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for event in next_events[:12]:
                lines.append(
                    f"| {event.get('event_id')} | {event.get('market_id')} | "
                    f"{event.get('event_class')} | {event.get('starts_at_utc')} |"
                )
    if live_forward_gate:
        evidence = live_forward_gate.get("evidence") or {}
        paper = evidence.get("paper_trading_evidence") or {}
        model_review = evidence.get("model_review_evidence") or {}
        live_trade = evidence.get("live_trade_permission_evidence") or {}
        lines.extend([
            "",
            "## Live-Forward Gate",
            "",
            "| Evidence class | Countable markets | Blocked markets | All selected count |",
            "| :--- | ---: | ---: | :--- |",
            (
                f"| Model review | {model_review.get('countable_market_count', 0)} | "
                f"{model_review.get('blocked_market_count', 0)} | "
                f"{str(model_review.get('all_selected_markets_count', False)).lower()} |"
            ),
            (
                f"| Paper trading | {paper.get('countable_market_count', 0)} | "
                f"{paper.get('blocked_market_count', 0)} | "
                f"{str(paper.get('all_selected_markets_count', False)).lower()} |"
            ),
            (
                f"| Live trade permission | {live_trade.get('countable_market_count', 0)} | "
                f"{live_trade.get('blocked_market_count', 0)} | "
                f"{str(live_trade.get('all_selected_markets_count', False)).lower()} |"
            ),
            "",
            "| Market | Verdict | First failing gate | Owner | Detail |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for market in live_forward_gate.get("markets") or []:
            first_failure = market.get("first_failing_gate") or {}
            lines.append(
                f"| {market.get('market_id')} | {market.get('preflight_status')} | "
                f"{first_failure.get('name') or '-'} | {first_failure.get('owner') or '-'} | "
                f"{first_failure.get('detail') or 'ok'} |"
            )
    if lifecycle:
        lines.extend([
            "",
            "## Budget Lifecycle",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| Current open-order risk | {float(lifecycle.get('current_reserved_usdc') or 0.0):.4f} USDC |",
            f"| Released this tick | {float(lifecycle.get('released_this_tick_usdc') or 0.0):.4f} USDC |",
            f"| Posted this tick | {lifecycle.get('posted_this_tick_count', 0)} orders |",
            f"| Stale open orders | {lifecycle.get('stale_open_order_count', 0)} |",
            f"| Polymarket cross-market gross-open note | {str((lifecycle.get('platform_balance_semantics') or {}).get('polymarket_cross_market_open_orders_may_exceed_wallet_balance')).lower()} |",
        ])
    if remediation.get("incidents"):
        lines.extend([
            "",
            "## Preflight Remediation",
            "",
            "| Market | Gate | Root Cause | Owner | Command |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for incident in remediation.get("incidents", [])[:20]:
            lines.append(
                f"| {incident.get('market_id')} | {incident.get('gate')} | "
                f"{incident.get('root_cause')} | {incident.get('owner')} | "
                f"`{incident.get('suggested_command')}` |"
            )
    lines.extend([
        "",
        "## Next Gating Status",
        "",
    ])
    if run_config["mode"] != "live-pilot":
        lines.append("- This run is keyless and must not place live orders.")
    if blocked_markets:
        lines.append(f"- Markets failing preflight: {', '.join(blocked_markets)}.")
    if live_rows:
        lines.append("- Live permission rows were emitted; verify live gates before any adapter consumes them.")
    else:
        lines.append("- No live-trade permission rows were emitted.")
    if reason_counts.get("NO_QUOTE_BUDGET_EXHAUSTED"):
        lines.append("- Increase the run budget or narrow market selection before live-pilot review.")
    return "\n".join(lines) + "\n"


def build_run_once(
    target_date,
    budget_usdc,
    mode="shadow",
    markets=None,
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    known_edge_map=DEFAULT_KNOWN_EDGE_MAP,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    run_id=None,
    policy_config=None,
    now=None,
    live_readiness_path=None,
    pilot=False,
    confirm_live_orders=False,
    append=False,
    data_layer_audit_path=DEFAULT_DATA_LAYER_AUDIT,
    platform_verification_path=DEFAULT_PLATFORM_VERIFICATION,
    evidence_mode=EVIDENCE_MODE_AUTO,
):
    mode = normalize_mode(mode)
    now = utc_now(now)
    target = ensure_date(target_date)
    specs = selected_specs(markets)
    evidence_timezone = getattr(getattr(specs[0], "tz", None), "key", None) if specs else None
    evidence_classification = classify_market_making_evidence(
        target,
        now=now,
        timezone_name=evidence_timezone or "America/Toronto",
        requested_mode=evidence_mode,
        run_mode=mode,
    )
    run_id = run_id or make_run_id(now)
    run_folder = run_folder_for(runs_root, target, run_id)
    run_folder.mkdir(parents=True, exist_ok=True)
    policy_config = {**DEFAULT_POLICY_CONFIG, **(policy_config or {})}
    policy_config["max_daily_loss"] = min(float(policy_config.get("max_daily_loss", budget_usdc)), float(budget_usdc))
    policy_config.setdefault("quote_ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS)
    policy_config, clob_recon_diag = config_with_clob_recon(policy_config)

    promotion_states, promotion_diag = load_promotion_states(promotion_refresh)
    known_edge_records, known_edge_diag = load_known_edge_map(known_edge_map)
    observation = load_observation_status(observation_status_path, now=now, config=policy_config)
    runtime_identity = runtime_identity_snapshot(observation_status_path)
    live_readiness = load_live_readiness(live_readiness_path)
    live_ready = bool(live_readiness.get("ok"))
    data_layer_live_gate = load_data_layer_live_gate(data_layer_audit_path, target, mode)
    platform_verification_gate = load_platform_verification_gate(platform_verification_path, target, mode, now=now)

    run_config = build_run_config_payload(
        run_id,
        target,
        budget_usdc,
        mode,
        specs,
        run_folder,
        snapshots_root,
        promotion_refresh,
        known_edge_map,
        observation_status_path,
        policy_config,
        now,
        evidence_classification=evidence_classification,
    )
    run_config["clob_recon"] = clob_recon_diag
    run_config["data_layer_live_gate"] = data_layer_live_gate
    run_config["platform_verification_gate"] = platform_verification_gate
    write_json(run_folder / "run_config.json", run_config)

    raw_quote_rows = []
    preflight_rows = []
    risk_events = []
    for spec in specs:
        config = config_for_date(target, spec.id)
        folder = Path(snapshots_root) / config.event_slug
        snapshot_rows = load_latest_snapshot_rows(folder)
        current_high_assessment = current_high_probability_summary(
            snapshot_rows,
            normalized_high_for_market(observation, spec.id),
        )
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_rows = source_status_for_snapshot(folder, snapshot_id)
        book_rows = latest_book_rows(folder)
        clob_feature_rows = latest_clob_feature_rows(
            folder,
            snapshot_id,
            build_if_missing=True,
            max_age_seconds=float(policy_config["max_book_age_seconds"]),
            market_id=spec.id,
        )
        promotion = promotion_states.get(spec.id, {"promotion_state": "BLOCK"})
        preflight = preflight_market(
            spec,
            config,
            folder,
            snapshot_rows,
            source_rows,
            book_rows,
            clob_feature_rows,
            promotion,
            observation,
            now,
            mode,
            policy_config,
            live_ready=live_ready,
            live_confirmed=confirm_live_orders,
            pilot=pilot,
            data_layer_live_gate=data_layer_live_gate,
            platform_verification_gate=platform_verification_gate,
            current_high_assessment=current_high_assessment,
        )
        preflight_rows.append(preflight)
        if preflight["status"] != "PASS":
            risk_events.append({
                "run_id": run_id,
                "generated_at_utc": now.isoformat(),
                "severity": "warning",
                "category": preflight["reason_kind"] or "preflight",
                "market_id": spec.id,
                "reason": preflight["status"],
                "detail": "; ".join(preflight.get("blocking_reasons") or preflight.get("stale_reasons") or []),
            })
        csv_encoding = preflight.get("csv_encoding") or {}
        for issue in csv_encoding.get("files") or []:
            risk_events.append({
                "run_id": run_id,
                "generated_at_utc": now.isoformat(),
                "severity": "warning",
                "category": "csv_encoding",
                "market_id": spec.id,
                "reason": issue.get("status"),
                "detail": (
                    f"{issue.get('path')} read as {issue.get('encoding')}; "
                    f"quarantined rows={issue.get('quarantined_row_count', 0)}"
                ),
            })
        if snapshot_rows:
            policy_inputs = assemble_policy_inputs_for_market(
                spec.id,
                folder,
                snapshot_rows,
                source_rows,
                promotion,
                observation,
                known_edge_records=known_edge_records,
                known_edge_map_loaded=known_edge_diag.get("exists", False),
                clob_feature_rows=clob_feature_rows,
                current_high_assessment=current_high_assessment,
            )
            if preflight["status"] == "PASS":
                raw_quote_rows.extend(decide_quote(row, config=policy_config, now=now) for row in policy_inputs)
            else:
                details = preflight.get("blocking_reasons") or preflight.get("stale_reasons") or [preflight["status"]]
                raw_quote_rows.extend(
                    preflight_no_quote(row, policy_config, now, preflight["reason_kind"], details)
                    for row in policy_inputs
                )
        else:
            detail = "; ".join(preflight.get("blocking_reasons") or ["missing current snapshot/model rows"])
            raw_quote_rows.append(placeholder_no_quote(
                spec,
                config,
                now,
                policy_config,
                "NO_QUOTE_MISSING_PREFLIGHT",
                detail,
            ))

    preflight_status = "PASS"
    if any(row.get("status") == "BLOCK" for row in preflight_rows):
        preflight_status = "BLOCK" if all(row.get("status") != "PASS" for row in preflight_rows) else "WARN"
    elif any(row.get("status") == "STALE" for row in preflight_rows):
        preflight_status = "STALE" if all(row.get("status") != "PASS" for row in preflight_rows) else "WARN"
    preflight_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": mode,
        "evidence_mode": evidence_classification.get("evidence_mode"),
        "evidence_classification": evidence_classification,
        "status": preflight_status,
        "promotion": promotion_diag,
        "known_edge_map": known_edge_diag,
        "clob_recon": clob_recon_diag,
        "observation_status": observation,
        "runtime_identity": runtime_identity,
        "live_readiness": live_readiness,
        "data_layer_live_gate": data_layer_live_gate,
        "platform_verification_gate": platform_verification_gate,
        "markets": preflight_rows,
    }
    live_forward_gate_payload = build_live_forward_gate(
        preflight_payload,
        policy_config=policy_config,
        now=now,
    )
    live_forward_gate_payload = apply_evidence_mode_to_live_forward_gate(
        live_forward_gate_payload,
        evidence_classification=evidence_classification,
    )
    live_forward_gate_path = run_folder / "live_forward_gate.json"
    preflight_payload["live_forward_gate_path"] = str(live_forward_gate_path)
    remediation_path = run_folder / "preflight_remediation.json"
    preflight_payload["preflight_remediation_path"] = str(remediation_path)
    previous_remediation = read_json(remediation_path, {}) if append else {}
    remediation_payload = build_preflight_remediation(preflight_payload, now, previous=previous_remediation)
    write_json(run_folder / "preflight.json", preflight_payload)
    write_json(live_forward_gate_path, live_forward_gate_payload)
    write_json(remediation_path, remediation_payload)
    risk_events.extend(remediation_risk_events(remediation_payload))

    preflight_by_market = {row["market_id"]: row for row in preflight_rows}
    lifecycle_path = run_folder / "order_lifecycle.jsonl"
    previous_open_orders = load_open_lifecycle_orders(lifecycle_path) if append else {}
    initial_reserved = last_reserved_from_ledger(run_folder / "budget_ledger.jsonl") if append and not previous_open_orders else 0.0
    cancel_all = (run_folder / "cancel_all.flag").exists()
    quote_rows, budget_ledger, budget_risk_events, lifecycle_events, lifecycle = apply_run_budget(
        raw_quote_rows,
        budget_usdc,
        run_id,
        target,
        mode,
        now,
        preflight_by_market,
        initial_reserved_usdc=initial_reserved,
        previous_open_orders=previous_open_orders,
        quote_ttl_seconds=float(policy_config.get("quote_ttl_seconds") or DEFAULT_QUOTE_TTL_SECONDS),
        cancel_all=cancel_all,
    )
    risk_events.extend(budget_risk_events)
    if any(row.get("live_trade_permission") for row in quote_rows) and mode != "live-pilot":
        raise RuntimeError("shadow/paper run attempted to emit live-trade permission")
    event_gate_summary = summarize_event_gate_rows(quote_rows)
    quote_permission_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    live_trade_permission_count = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    no_quote_status = "quoted"
    no_quote_reason = "quote permissions emitted"
    if not quote_rows:
        no_quote_status = "crashed_before_scoring"
        no_quote_reason = "no quote-intent rows were produced"
    elif quote_permission_count == 0:
        if preflight_status in {"BLOCK", "STALE", "WARN"}:
            no_quote_status = "preflight_blocked"
            no_quote_reason = f"preflight status {preflight_status}"
        else:
            no_quote_status = "policy_no_quote"
            no_quote_reason = "policy produced no quote permissions"
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        preflight_rows,
        permission_rows=quote_permission_count,
        output_rows=len(quote_rows),
    )

    quote_path = run_folder / "quote_intents_long.csv"
    if append:
        append_csv(quote_path, RUN_QUOTE_COLUMNS, quote_rows)
    else:
        write_csv(quote_path, RUN_QUOTE_COLUMNS, quote_rows)
    append_jsonl(run_folder / "budget_ledger.jsonl", budget_ledger)
    append_jsonl(lifecycle_path, lifecycle_events)
    append_jsonl(run_folder / "risk_events.jsonl", risk_events)
    if not (run_folder / "fills_long.csv").exists():
        write_csv(run_folder / "fills_long.csv", FILL_COLUMNS, [])
    cumulative = cumulative_run_summary(run_folder, fallback_quote_rows=quote_rows, fallback_lifecycle=lifecycle)
    tape_integrity = tape_integrity_summary(quote_path, cumulative.get("row_count", 0), "quote_intents_long")
    report = build_report(
        run_config,
        preflight_payload,
        quote_rows,
        budget_ledger,
        lifecycle=lifecycle,
        remediation=remediation_payload,
        cumulative=cumulative,
        event_gate=event_gate_summary,
        live_forward_gate=live_forward_gate_payload,
        evidence_classification=evidence_classification,
        tape_integrity=tape_integrity,
    )
    (run_folder / "run_report.md").write_text(report, encoding="utf-8")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": mode,
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "preflight_path": str(run_folder / "preflight.json"),
        "quote_intents_path": str(quote_path),
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
        "order_lifecycle_path": str(lifecycle_path),
        "preflight_remediation_path": str(remediation_path),
        "live_forward_gate_path": str(live_forward_gate_path),
        "risk_events_path": str(run_folder / "risk_events.jsonl"),
        "fills_path": str(run_folder / "fills_long.csv"),
        "run_report_path": str(run_folder / "run_report.md"),
        "preflight_status": preflight_status,
        "quote_outcome": {
            "status": no_quote_status,
            "reason": no_quote_reason,
            "quote_permission_rows": quote_permission_count,
            "row_count": len(quote_rows),
            "preflight_status": preflight_status,
            **zero_trade_diagnosis,
        },
        "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
        "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
        "first_failing_detail": zero_trade_diagnosis.get("first_failing_detail"),
        "zero_trades_expected": zero_trade_diagnosis.get("zero_trades_expected"),
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "remediation_command": (
                (remediation_payload.get("incidents") or [{}])[0].get("suggested_command")
                if remediation_payload.get("incidents")
                else None
            ),
        },
        "live_forward_gate_status": live_forward_gate_payload.get("status"),
        "counts_toward_live_forward_gate": live_forward_gate_payload.get("counts_toward_live_forward_gate"),
        "evidence_mode": evidence_classification.get("evidence_mode"),
        "evidence_classification": evidence_classification,
        "live_forward_gate_counts_without_evidence_mode": live_forward_gate_payload.get(
            "counts_toward_live_forward_gate_without_evidence_mode"
        ),
        "row_count": len(quote_rows),
        "quote_permission_rows": quote_permission_count,
        "live_trade_permission_rows": live_trade_permission_count,
        "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
        "information_event_gate": event_gate_summary,
        "budget_reserved_usdc": lifecycle.get("current_reserved_usdc", 0.0),
        "budget_released_usdc": lifecycle.get("released_this_tick_usdc", 0.0),
        "open_order_count": lifecycle.get("current_open_order_count", 0),
        "budget_usdc": float(budget_usdc),
        "latest_tick": {
            "row_count": len(quote_rows),
            "quote_permission_rows": quote_permission_count,
            "live_trade_permission_rows": live_trade_permission_count,
            "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
            "information_event_gate": event_gate_summary,
        },
        "cumulative": cumulative,
        "tape_integrity": tape_integrity,
        "cumulative_tick_count": cumulative.get("tick_count", 0),
        "cumulative_row_count": cumulative.get("row_count", 0),
        "cumulative_quote_permission_rows": cumulative.get("quote_permission_rows", 0),
        "cumulative_live_trade_permission_rows": cumulative.get("live_trade_permission_rows", 0),
        "cumulative_paper_posted_count": cumulative.get("paper_posted_count", 0),
        "cumulative_lifecycle_transition_counts": cumulative.get("order_lifecycle_transition_counts", {}),
        "runtime_identity": runtime_identity,
        "order_lifecycle": lifecycle,
        "clob_recon": clob_recon_diag,
        "preflight_remediation": {
            "status": remediation_payload.get("status"),
            "incident_count": remediation_payload.get("incident_count", 0),
            "root_cause_counts": remediation_payload.get("root_cause_counts", {}),
            "owner_counts": remediation_payload.get("owner_counts", {}),
            "counts_toward_live_forward_gate": remediation_payload.get("counts_toward_live_forward_gate", False),
        },
        "live_forward_gate": {
            "status": live_forward_gate_payload.get("status"),
            "counts_toward_live_forward_gate": live_forward_gate_payload.get("counts_toward_live_forward_gate"),
            "status_without_evidence_mode": live_forward_gate_payload.get("status_without_evidence_mode"),
            "counts_toward_live_forward_gate_without_evidence_mode": live_forward_gate_payload.get(
                "counts_toward_live_forward_gate_without_evidence_mode"
            ),
            "counts_toward_live_forward_gate_after_evidence_mode": live_forward_gate_payload.get(
                "counts_toward_live_forward_gate_after_evidence_mode"
            ),
            "evidence_mode_gate": live_forward_gate_payload.get("evidence_mode_gate"),
            "evidence": live_forward_gate_payload.get("evidence"),
            "summary": live_forward_gate_payload.get("summary"),
        },
        "markets": preflight_rows,
    }
    write_json(run_folder / "run_summary.json", payload)
    return payload


def paper_until_utc(target_date, specs):
    target = ensure_date(target_date)
    ends = [
        datetime.combine(target, dt_time(23, 59, 59), tzinfo=spec.tz).astimezone(timezone.utc)
        for spec in specs
    ]
    return max(ends)


def run_loop(
    target_date,
    budget_usdc,
    mode,
    markets=None,
    interval_seconds=60.0,
    until_utc=None,
    max_ticks=None,
    **kwargs,
):
    specs = selected_specs(markets)
    until = parse_time(until_utc) if until_utc else paper_until_utc(target_date, specs)
    run_id = kwargs.pop("run_id", None)
    results = []
    tick = 0
    with keep_system_awake("weather market-making bot loop"):
        while True:
            now = utc_now()
            if until is not None and now > until:
                break
            if max_ticks is not None and tick >= int(max_ticks):
                break
            result = build_run_once(
                target_date,
                budget_usdc,
                mode=mode,
                markets=[spec.id for spec in specs],
                run_id=run_id,
                now=now,
                append=tick > 0,
                **kwargs,
            )
            run_id = result["run_id"]
            results.append(result)
            tick += 1
            if max_ticks is not None and tick >= int(max_ticks):
                break
            time.sleep(float(interval_seconds))
    return results[-1] if results else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the date/budget market-making orchestrator.")
    parser.add_argument("--date", required=True, help="Target market date, YYYY-MM-DD.")
    parser.add_argument("--budget-usdc", type=float, required=True, help="Total run risk budget.")
    parser.add_argument("--mode", choices=sorted(RUN_MODES | {"live"}), default="shadow")
    parser.add_argument("--markets", default="all", help="'all' or comma-separated market ids.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--known-edge-map", default=str(DEFAULT_KNOWN_EDGE_MAP))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--config", action="append", default=[], help="Policy config override, key=value.")
    parser.add_argument("--pilot", action="store_true", help="Required for live-pilot mode.")
    parser.add_argument("--confirm-live-orders", action="store_true", help="Required for live-pilot mode.")
    parser.add_argument("--live-readiness", default=None, help="JSON file proving live account/platform gates.")
    parser.add_argument("--data-layer-audit", default=str(DEFAULT_DATA_LAYER_AUDIT), help="Latest data-layer audit JSON for live-pilot CLOB artifact gating.")
    parser.add_argument("--platform-verification", default=str(DEFAULT_PLATFORM_VERIFICATION), help="Current account/platform verification JSON required for live-pilot.")
    parser.add_argument("--once", action="store_true", help="For paper-live-forward, run one tick instead of looping.")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--until-utc", default=None)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--evidence-mode", default=EVIDENCE_MODE_AUTO, choices=sorted(EVIDENCE_MODE_CHOICES))
    args = parser.parse_args(argv)

    mode = normalize_mode(args.mode)
    common = {
        "markets": args.markets,
        "runs_root": Path(args.runs_root),
        "snapshots_root": Path(args.snapshots_root),
        "promotion_refresh": Path(args.promotion_refresh),
        "known_edge_map": Path(args.known_edge_map),
        "observation_status_path": Path(args.observation_status),
        "run_id": args.run_id,
        "policy_config": parse_config_overrides(args.config),
        "live_readiness_path": args.live_readiness,
        "data_layer_audit_path": Path(args.data_layer_audit) if args.data_layer_audit else None,
        "platform_verification_path": Path(args.platform_verification) if args.platform_verification else None,
        "evidence_mode": args.evidence_mode,
        "pilot": args.pilot,
        "confirm_live_orders": args.confirm_live_orders,
    }
    if mode == "paper-live-forward" and not args.once and args.now is None:
        payload = run_loop(
            args.date,
            args.budget_usdc,
            mode,
            interval_seconds=args.interval_seconds,
            until_utc=args.until_utc,
            max_ticks=args.max_ticks,
            **common,
        )
    else:
        payload = build_run_once(
            args.date,
            args.budget_usdc,
            mode=mode,
            now=args.now,
            **common,
        )
    if payload is None:
        print("MM run: no ticks executed")
        return None
    print(
        "MM run: "
        f"{payload['quote_permission_rows']} quote rows, "
        f"{payload['row_count'] - payload['quote_permission_rows']} no-quote rows, "
        f"preflight {payload['preflight_status']} -> {payload['run_folder']}"
    )
    return payload


if __name__ == "__main__":
    main()
