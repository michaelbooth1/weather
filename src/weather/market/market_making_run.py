"""Date/budget market-making run orchestrator.

The pure policy module decides whether a single band should quote. This module
owns operator concerns around target-date discovery, run folders, preflight
gates, budget accounting, and fail-closed shadow/paper run artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections import Counter
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

try:
    from .market_config import config_for_date, ensure_date
    from .market_microstructure import audit_book_tape
    from .market_microstructure_features import snapshot_band_key
    from .market_registry import all_specs, spec_for_id
    from .mm_policy import (
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
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.market.market_config import config_for_date, ensure_date
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



try:
    from .market_making_run_constants import (  # noqa: E402
        DEFAULT_DATA_LAYER_AUDIT,
        DEFAULT_QUOTE_TTL_SECONDS,
        DEFAULT_RUNS_ROOT,
        FILL_COLUMNS,
        RUN_EXTRA_COLUMNS,
        RUN_MODES,
        RUN_QUOTE_COLUMNS,
        SCHEMA_VERSION,
    )
    from .market_making_run_support import (  # noqa: E402
        add_run_columns,
        append_csv,
        append_jsonl,
        apply_run_budget,
        assemble_policy_inputs_for_market,
        boolish_active,
        budget_exhausted_row,
        cancel_all_row,
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
except ImportError:  # pragma: no cover - direct src compatibility
    from weather.market.market_making_run_constants import (  # noqa: E402
        DEFAULT_DATA_LAYER_AUDIT,
        DEFAULT_QUOTE_TTL_SECONDS,
        DEFAULT_RUNS_ROOT,
        FILL_COLUMNS,
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

try:
    from ..operations.runtime_identity import (  # noqa: E402
        format_runtime_identity,
        get_runtime_identity,
        identities_match,
    )
except ImportError:  # pragma: no cover - direct src compatibility
    from weather.operations.runtime_identity import (  # noqa: E402
        format_runtime_identity,
        get_runtime_identity,
        identities_match,
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


def load_data_layer_live_gate(path, target_date, mode):
    required = mode == "live-pilot"
    if not required:
        return {"required": False, "ok": True, "reason": "not required outside live-pilot"}
    path = Path(path) if path else None
    if path is None:
        return {"required": True, "ok": False, "path": None, "reason": "no data-layer audit path provided"}
    if not path.exists():
        return {"required": True, "ok": False, "path": str(path), "reason": "data-layer audit artifact missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"required": True, "ok": False, "path": str(path), "reason": f"invalid data-layer audit JSON: {exc}"}
    snapshots = payload.get("snapshots") or {}
    clob = snapshots.get("clob_features") or {}
    target_text = ensure_date(target_date).isoformat()
    target_folders = [
        row for row in snapshots.get("folders") or []
        if row.get("target_date") == target_text
    ]
    target_token_days = sum(
        1 for row in target_folders
        if int(row.get("rows_with_market_token_ids") or 0) > 0
    )
    target_clob_feature_days = sum(
        1 for row in target_folders
        if ((row.get("artifact_presence") or {}).get("clob_features"))
    )
    target_book_available_days = sum(
        1 for row in target_folders
        if int(((row.get("clob_features") or {}).get("book_available_rows")) or 0) > 0
    )
    checks = {
        "has_market_token_ids": bool(snapshots.get("has_market_token_ids")),
        "clob_feature_rows": int(clob.get("row_count") or 0) > 0,
        "clob_book_available_rows": int(clob.get("book_available_rows") or 0) > 0,
        "target_date_folder_present": bool(target_folders),
        "target_date_token_ids": target_token_days > 0,
        "target_date_clob_features": target_clob_feature_days > 0,
        "target_date_book_available": target_book_available_days > 0,
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "required": True,
        "ok": not missing,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "gate_summary_status": (payload.get("gate_summary") or {}).get("status"),
        "target_date": target_text,
        "checks": checks,
        "missing": missing,
        "reason": "ok" if not missing else "data-layer audit missing live CLOB proof: " + ", ".join(missing),
        "target_date_folder_count": len(target_folders),
        "target_date_token_days": target_token_days,
        "target_date_clob_feature_days": target_clob_feature_days,
        "target_date_book_available_days": target_book_available_days,
    }


REMEDIATION_RULES = {
    "active_event": {
        "root_cause": "missing_active_event",
        "owner": "market registry / Gamma event discovery",
        "suggested_command": "python -m src.market_microstructure refresh-tokens",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "snapshot_model_rows": {
        "root_cause": "missing_snapshot_model_rows",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m src.snapshot_tracker status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "model_freshness": {
        "root_cause": "stale_model_row",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m src.snapshot_tracker status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_rows": {
        "root_cause": "missing_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m src.snapshot_tracker --backfill-source-status --overwrite-source-status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "source_status_fresh": {
        "root_cause": "stale_source_status_row",
        "owner": "snapshot source-status writer",
        "suggested_command": "python -m src.snapshot_tracker status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_tokens": {
        "root_cause": "missing_clob_tokens",
        "owner": "CLOB token discovery",
        "suggested_command": "python -m src.market_microstructure refresh-tokens",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_books": {
        "root_cause": "missing_clob_book_rows",
        "owner": "CLOB book loop",
        "suggested_command": "python -m src.market_microstructure status",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_features": {
        "root_cause": "missing_clob_feature_rows",
        "owner": "CLOB feature builder",
        "suggested_command": "python -m src.market_microstructure_features",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "clob_freshness": {
        "root_cause": "stale_clob_book_tape",
        "owner": "CLOB book supervisor",
        "suggested_command": "python -m src.market_microstructure ensure",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "observation_trigger": {
        "root_cause": "watcher_stale",
        "owner": "observation-trigger supervisor",
        "suggested_command": "python -m src.observation_trigger ensure",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "promotion_state": {
        "root_cause": "promotion_blocked_or_missing",
        "owner": "promotion refresh",
        "suggested_command": "python -m src.promotion_refresh",
        "recoverable_same_day": False,
        "counts_after_failure": False,
    },
    "reward_metadata": {
        "root_cause": "missing_reward_metadata",
        "owner": "CLOB book/token metadata",
        "suggested_command": "python -m src.market_microstructure ensure",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "live_account_gate": {
        "root_cause": "live_gate_blocked",
        "owner": "live account/platform readiness",
        "suggested_command": "review live-readiness JSON and run cancel-all probe",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
    "data_layer_live_gate": {
        "root_cause": "data_layer_live_gate_blocked",
        "owner": "data-layer audit / CLOB capture",
        "suggested_command": "python -m src.data_layer_audit --fleet --json",
        "recoverable_same_day": True,
        "counts_after_failure": False,
    },
}


def remediation_last_good_artifact(market_row, gate_name):
    folder = market_row.get("folder") or ""
    if gate_name.startswith("source_status"):
        return {
            "artifact": str(Path(folder) / "source_status_long.csv") if folder else "",
            "latest_snapshot_id": market_row.get("latest_snapshot_id"),
            "latest_capture_utc": market_row.get("latest_capture_utc"),
            "source_status_rows": market_row.get("source_status_rows"),
        }
    if gate_name.startswith("clob"):
        audit = market_row.get("book_audit") or {}
        filename = "clob_tokens.csv" if gate_name == "clob_tokens" else "order_books_summary.csv"
        if gate_name == "clob_features":
            filename = "clob_features_long.csv"
        return {
            "artifact": str(Path(folder) / filename) if folder else "",
            "last_capture_utc": audit.get("last_capture_utc"),
            "trailing_age_seconds": audit.get("trailing_age_seconds"),
            "gaps_over_threshold": audit.get("gaps_over_threshold"),
            "max_counted_gap_seconds": audit.get("max_counted_gap_seconds"),
        }
    return {
        "artifact": folder,
        "latest_snapshot_id": market_row.get("latest_snapshot_id"),
        "latest_capture_utc": market_row.get("latest_capture_utc"),
    }


def build_preflight_remediation(preflight, now, previous=None):
    previous_by_key = {
        row.get("incident_key"): row
        for row in ((previous or {}).get("incidents") or [])
        if row.get("incident_key")
    }
    incidents = []
    owner_counts = Counter()
    root_counts = Counter()
    for market in preflight.get("markets", []):
        for gate in market.get("gates") or []:
            if gate.get("ok"):
                continue
            rule = REMEDIATION_RULES.get(gate.get("name"), {
                "root_cause": gate.get("name") or "unknown_preflight_failure",
                "owner": "unknown",
                "suggested_command": "inspect preflight.json",
                "recoverable_same_day": False,
                "counts_after_failure": False,
            })
            detail = gate.get("detail") or ""
            key = "|".join([
                str(market.get("market_id") or ""),
                str(gate.get("name") or ""),
                str(rule["root_cause"]),
                detail,
            ])
            prior = previous_by_key.get(key) or {}
            incident = {
                "incident_key": key,
                "run_id": preflight.get("run_id"),
                "generated_at_utc": now.isoformat(),
                "first_seen_utc": prior.get("first_seen_utc") or now.isoformat(),
                "last_seen_utc": now.isoformat(),
                "market_id": market.get("market_id"),
                "event_slug": market.get("event_slug"),
                "status": market.get("status"),
                "gate": gate.get("name"),
                "severity": gate.get("severity"),
                "root_cause": rule["root_cause"],
                "owner": rule["owner"],
                "detail": detail,
                "suggested_command": rule["suggested_command"],
                "recoverable_same_day": bool(rule["recoverable_same_day"]),
                "can_still_count_live_forward_day": bool(rule["counts_after_failure"]),
                "alert_within_seconds": 60,
                "last_good_artifact": remediation_last_good_artifact(market, gate.get("name") or ""),
            }
            incidents.append(incident)
            owner_counts[incident["owner"]] += 1
            root_counts[incident["root_cause"]] += 1
    has_missing = any(row.get("severity") != "stale" for row in incidents)
    status = "PASS" if not incidents else ("BLOCK" if has_missing else "WARN")
    non_countable = [
        row["incident_key"]
        for row in incidents
        if not row.get("can_still_count_live_forward_day")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": preflight.get("run_id"),
        "target_date": preflight.get("target_date"),
        "mode": preflight.get("mode"),
        "status": status,
        "incident_count": len(incidents),
        "alert_within_seconds": 60,
        "counts_toward_live_forward_gate": preflight.get("status") == "PASS" and not incidents,
        "non_countable_incidents": non_countable,
        "root_cause_counts": dict(sorted(root_counts.items())),
        "owner_counts": dict(sorted(owner_counts.items())),
        "incidents": incidents,
    }


def remediation_risk_events(remediation):
    rows = []
    for incident in remediation.get("incidents") or []:
        rows.append({
            "run_id": remediation.get("run_id"),
            "generated_at_utc": remediation.get("generated_at_utc"),
            "severity": "warning" if incident.get("severity") == "stale" else "critical",
            "category": "preflight_remediation",
            "market_id": incident.get("market_id"),
            "reason": incident.get("root_cause"),
            "detail": incident.get("detail"),
            "owner": incident.get("owner"),
            "suggested_command": incident.get("suggested_command"),
            "alert_within_seconds": incident.get("alert_within_seconds"),
        })
    return rows


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
):
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
        "shadow_safety": {
            "loads_private_keys": False,
            "posts_orders": False,
            "live_trade_permission_allowed": mode == "live-pilot",
        },
    }


def build_report(run_config, preflight, quote_rows, budget_ledger, lifecycle=None, remediation=None, cumulative=None):
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    quote_rows_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    live_rows = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    lifecycle = lifecycle or {}
    remediation = remediation or {}
    cumulative = cumulative or {}
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
        f"- Latest-tick no-quote rows: `{len(quote_rows) - quote_rows_count}`",
        f"- Latest-tick live-trade permission rows: `{live_rows}`",
        f"- Cumulative ticks: `{cumulative.get('tick_count', 1 if quote_rows else 0)}`",
        f"- Cumulative quote rows: `{cumulative.get('quote_permission_rows', quote_rows_count)}`",
        f"- Cumulative paper-posted lifecycle legs: `{cumulative.get('paper_posted_count', 0)}`",
        f"- Budget reserved: `{reserved:.2f}` / `{budget:.2f}` USDC",
        f"- Remaining budget: `{max(0.0, budget - reserved):.2f}` USDC",
        f"- Open lifecycle orders: `{lifecycle.get('current_open_order_count', 0)}`",
        f"- Released this tick: `{float(lifecycle.get('released_this_tick_usdc') or 0.0):.2f}` USDC",
        f"- Preflight remediation incidents: `{remediation.get('incident_count', 0)}`",
        f"- Counts toward live-forward gate: `{str(remediation.get('counts_toward_live_forward_gate', False)).lower()}`",
        "",
        "## Preflight By Market",
        "",
        "| Market | Status | Event | Rows | Detail |",
        "| :--- | :--- | :--- | ---: | :--- |",
    ]
    for row in preflight.get("markets", []):
        details = row.get("blocking_reasons") or row.get("stale_reasons") or ["ok"]
        lines.append(
            f"| {row.get('market_id')} | {row.get('status')} | {row.get('event_slug')} | "
            f"{row.get('snapshot_rows', 0)} | {'; '.join(details)} |"
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
):
    mode = normalize_mode(mode)
    now = utc_now(now)
    target = ensure_date(target_date)
    specs = selected_specs(markets)
    run_id = run_id or make_run_id(now)
    run_folder = run_folder_for(runs_root, target, run_id)
    run_folder.mkdir(parents=True, exist_ok=True)
    policy_config = {**DEFAULT_POLICY_CONFIG, **(policy_config or {})}
    policy_config["max_daily_loss"] = min(float(policy_config.get("max_daily_loss", budget_usdc)), float(budget_usdc))
    policy_config.setdefault("quote_ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS)

    promotion_states, promotion_diag = load_promotion_states(promotion_refresh)
    known_edge_records, known_edge_diag = load_known_edge_map(known_edge_map)
    observation = load_observation_status(observation_status_path, now=now, config=policy_config)
    runtime_identity = runtime_identity_snapshot(observation_status_path)
    live_readiness = load_live_readiness(live_readiness_path)
    live_ready = bool(live_readiness.get("ok"))
    data_layer_live_gate = load_data_layer_live_gate(data_layer_audit_path, target, mode)

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
    )
    write_json(run_folder / "run_config.json", run_config)

    raw_quote_rows = []
    preflight_rows = []
    risk_events = []
    for spec in specs:
        config = config_for_date(target, spec.id)
        folder = Path(snapshots_root) / config.event_slug
        snapshot_rows = load_latest_snapshot_rows(folder)
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_rows = source_status_for_snapshot(folder, snapshot_id)
        book_rows = latest_book_rows(folder)
        clob_feature_rows = latest_clob_feature_rows(folder, snapshot_id)
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
        "status": preflight_status,
        "promotion": promotion_diag,
        "known_edge_map": known_edge_diag,
        "observation_status": observation,
        "runtime_identity": runtime_identity,
        "live_readiness": live_readiness,
        "data_layer_live_gate": data_layer_live_gate,
        "markets": preflight_rows,
    }
    remediation_path = run_folder / "preflight_remediation.json"
    preflight_payload["preflight_remediation_path"] = str(remediation_path)
    previous_remediation = read_json(remediation_path, {}) if append else {}
    remediation_payload = build_preflight_remediation(preflight_payload, now, previous=previous_remediation)
    write_json(run_folder / "preflight.json", preflight_payload)
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
    report = build_report(
        run_config,
        preflight_payload,
        quote_rows,
        budget_ledger,
        lifecycle=lifecycle,
        remediation=remediation_payload,
        cumulative=cumulative,
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
        "risk_events_path": str(run_folder / "risk_events.jsonl"),
        "fills_path": str(run_folder / "fills_long.csv"),
        "run_report_path": str(run_folder / "run_report.md"),
        "preflight_status": preflight_status,
        "row_count": len(quote_rows),
        "quote_permission_rows": sum(1 for row in quote_rows if row.get("quote_permission")),
        "live_trade_permission_rows": sum(1 for row in quote_rows if row.get("live_trade_permission")),
        "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
        "budget_reserved_usdc": lifecycle.get("current_reserved_usdc", 0.0),
        "budget_released_usdc": lifecycle.get("released_this_tick_usdc", 0.0),
        "open_order_count": lifecycle.get("current_open_order_count", 0),
        "budget_usdc": float(budget_usdc),
        "latest_tick": {
            "row_count": len(quote_rows),
            "quote_permission_rows": sum(1 for row in quote_rows if row.get("quote_permission")),
            "live_trade_permission_rows": sum(1 for row in quote_rows if row.get("live_trade_permission")),
            "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
        },
        "cumulative": cumulative,
        "cumulative_tick_count": cumulative.get("tick_count", 0),
        "cumulative_row_count": cumulative.get("row_count", 0),
        "cumulative_quote_permission_rows": cumulative.get("quote_permission_rows", 0),
        "cumulative_live_trade_permission_rows": cumulative.get("live_trade_permission_rows", 0),
        "cumulative_paper_posted_count": cumulative.get("paper_posted_count", 0),
        "cumulative_lifecycle_transition_counts": cumulative.get("order_lifecycle_transition_counts", {}),
        "runtime_identity": runtime_identity,
        "order_lifecycle": lifecycle,
        "preflight_remediation": {
            "status": remediation_payload.get("status"),
            "incident_count": remediation_payload.get("incident_count", 0),
            "root_cause_counts": remediation_payload.get("root_cause_counts", {}),
            "owner_counts": remediation_payload.get("owner_counts", {}),
            "counts_toward_live_forward_gate": remediation_payload.get("counts_toward_live_forward_gate", False),
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
    parser.add_argument("--once", action="store_true", help="For paper-live-forward, run one tick instead of looping.")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--until-utc", default=None)
    parser.add_argument("--max-ticks", type=int, default=None)
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
