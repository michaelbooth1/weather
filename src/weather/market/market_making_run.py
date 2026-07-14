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
from weather.market import exchange_economics
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
from weather.market.market_making_model_variants import (
    build_model_variant_quote_rows,
    render_model_variant_report,
)
from weather.market.live_observation_normalization import (
    current_high_probability_summary,
    normalized_high_for_market,
)
from weather.market.market_making_evidence import (
    EVIDENCE_MODE_AUTO,
    EVIDENCE_MODE_ACTIVE_DAY,
    EVIDENCE_MODE_CHOICES,
    classify_market_making_evidence,
)
from weather.runtime_identity import (  # noqa: E402
    current_identity_for,
    format_runtime_identity,
    get_runtime_identity,
    identities_match,
)
from weather.operations import event_metadata_validation
from weather.operations.power import keep_system_awake
from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
)
from weather.market.worker_release_binding import (
    load_worker_release_binding,
    stamp_worker_release_lineage,
    verify_worker_csv_tape_for_append,
    verify_worker_snapshot_binding,
    worker_tape_columns,
    worker_release_summary_fields,
)
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
USEFUL_WORK_LIVENESS_SCHEMA_VERSION = "mm_useful_work_liveness_v0.1"
USEFUL_WORK_STARTUP_GRACE_SECONDS = 180.0


def _uses_default_snapshot_root(path):
    try:
        return Path(path).resolve() == Path(DEFAULT_SNAPSHOTS_ROOT).resolve()
    except OSError:
        return Path(path) == Path(DEFAULT_SNAPSHOTS_ROOT)


def _event_metadata_preflight_payload(path, target, snapshots_root):
    explicit_path = path is not None
    path = Path(path or event_metadata_validation.DEFAULT_JSON_OUT)
    required = _uses_default_snapshot_root(snapshots_root) or explicit_path
    payload = event_metadata_validation.load_validation_payload(path) if required else None
    return {
        "required": required,
        "exists": payload is not None,
        "path": str(path),
        "target_date": target.isoformat(),
        "status": (payload or {}).get("status") if payload else ("missing" if required else "not_required"),
        "validation_hash": (payload or {}).get("validation_hash"),
        "payload": payload,
    }


def _event_metadata_gate_for_market(validation_state, market_id):
    if not (validation_state or {}).get("required"):
        return {"required": False, "ok": True, "reason": "not required for non-default snapshot root"}
    payload = (validation_state or {}).get("payload")
    gate = event_metadata_validation.gate_for_market(payload, market_id)
    if payload and payload.get("target_date") != validation_state.get("target_date"):
        gate = {
            **gate,
            "ok": False,
            "status": "BLOCK",
            "reason": (
                "event metadata validation target_date does not match maker run target_date: "
                f"{payload.get('target_date')} != {validation_state.get('target_date')}"
            ),
            "detail": (
                "event metadata validation target_date does not match maker run target_date: "
                f"{payload.get('target_date')} != {validation_state.get('target_date')}"
            ),
            "remediation_command": validation_state.get("validation_command")
            or event_metadata_validation.VALIDATION_COMMAND.replace(
                "<YYYY-MM-DD>",
                validation_state.get("target_date") or "<YYYY-MM-DD>",
            ),
        }
    return gate


def runtime_identity_snapshot(observation_status_path=DEFAULT_OBSERVATION_STATUS, snapshots_root=DEFAULT_SNAPSHOTS_ROOT):
    fallback_current = get_runtime_identity()

    def loop_row(name, path):
        status = read_json(path, {}) or {}
        process = status.get("runtime_identity") or {}
        current = current_identity_for(process) if process else fallback_current
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
        loop_row("weather_snapshots", Path(snapshots_root) / "loop_status.json"),
        loop_row("clob_books", Path(snapshots_root) / "clob_loop_status.json"),
        loop_row("observation_triggers", observation_status_path),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "current_identity": fallback_current,
        "current_identity_text": format_runtime_identity(fallback_current),
        "loops": loops,
        "drift_count": sum(1 for row in loops if row.get("runtime_identity_matches_current") is False),
    }


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _age_seconds_at(value, now):
    parsed = parse_time(value)
    if parsed is None:
        return None
    return round(max(0.0, (now - parsed).total_seconds()), 1)


def _first_present_mapping(row, *keys):
    row = row or {}
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested_has_status(value, status):
    if isinstance(value, dict):
        for key in ("status", "state", "runtime_code_state"):
            if str(value.get(key) or "").lower() == status:
                return True
        return any(_nested_has_status(item, status) for item in value.values())
    if isinstance(value, list):
        return any(_nested_has_status(item, status) for item in value)
    return False


def _nested_has_blocked(value):
    if isinstance(value, dict):
        if value.get("blocked") is True:
            return True
        return any(_nested_has_blocked(item) for item in value.values())
    if isinstance(value, list):
        return any(_nested_has_blocked(item) for item in value)
    return False


def _market_result_count(results, predicate):
    if not isinstance(results, dict):
        return 0
    return sum(1 for row in results.values() if isinstance(row, dict) and predicate(row))


def _positive_numeric(value):
    number = maybe_float(value)
    return number is not None and number > 0


def _loop_row(name, path, status, now, useful_keys, useful_count_fn=None):
    status = status or {}
    useful_at = _first_present_mapping(status, *useful_keys)
    started_at = _first_present_mapping(status, "started_at", "started_at_utc")
    startup_age = _age_seconds_at(started_at, now)
    within_startup_grace = startup_age is not None and startup_age < USEFUL_WORK_STARTUP_GRACE_SECONDS
    results = status.get("last_market_results") or status.get("last_poll_results") or {}
    if useful_count_fn:
        useful_count = useful_count_fn(results)
    elif isinstance(results, dict):
        useful_count = len(results)
    else:
        useful_count = 0
    result_items = results.items() if isinstance(results, dict) else []
    stale_code_markets = sorted(
        market_id
        for market_id, result in result_items
        if isinstance(result, dict) and _nested_has_status(result, "stale_code")
    )
    result_items = results.items() if isinstance(results, dict) else []
    blocked_markets = sorted(
        market_id
        for market_id, result in result_items
        if isinstance(result, dict) and _nested_has_blocked(result)
    )
    return {
        "name": name,
        "status_path": str(path),
        "exists": bool(status),
        "pid": status.get("pid"),
        "iterations": _safe_int(status.get("iterations")),
        "last_heartbeat": status.get("last_heartbeat"),
        "heartbeat_age_seconds": _age_seconds_at(status.get("last_heartbeat"), now),
        "last_useful_write_at": parse_time(useful_at).isoformat() if parse_time(useful_at) else None,
        "useful_write_age_seconds": _age_seconds_at(useful_at, now),
        "useful_iteration_count": useful_count,
        "last_error": status.get("last_error"),
        "consecutive_errors": _safe_int(status.get("consecutive_errors")) or 0,
        "started_at": parse_time(started_at).isoformat() if parse_time(started_at) else started_at,
        "startup_age_seconds": startup_age,
        "within_startup_grace": within_startup_grace,
        "stale_code_market_count": len(stale_code_markets),
        "stale_code_markets": stale_code_markets,
        "blocked_market_count": len(blocked_markets),
        "blocked_markets": blocked_markets,
    }


def _blocker(gate, root_cause, owner, detail, suggested_command, **extra):
    payload = {
        "gate": gate,
        "root_cause": root_cause,
        "owner": owner,
        "detail": detail,
        "suggested_command": suggested_command,
        "severity": "block",
        "market_id": extra.pop("market_id", "*"),
        "recoverable_same_day": bool(extra.pop("recoverable_same_day", True)),
        "can_still_count_live_forward_day": False,
    }
    payload.update(extra)
    return payload


def _all_market_scope(specs):
    selected = {spec.id for spec in specs or []}
    known = {spec.id for spec in all_specs()}
    return bool(selected) and selected == known


def _gate_failed(market, names):
    names = set(names)
    return any((gate.get("name") in names and not gate.get("ok")) for gate in market.get("gates") or [])


def build_useful_work_liveness(
    preflight_rows,
    *,
    runtime_identity,
    observation_status_path,
    snapshots_root,
    runs_root,
    policy_config,
    now,
    all_market_scope,
    evidence_mode,
    mode,
    snapshot_loop_status=None,
    clob_loop_status=None,
    observation_status_raw=None,
    daily_roll_status=None,
):
    """Run-level all-market useful-write SLA for maker evidence countability."""
    now = utc_now(now)
    snapshots_root = Path(snapshots_root)
    runs_root = Path(runs_root)
    snapshot_status_path = snapshots_root / "loop_status.json"
    clob_status_path = snapshots_root / "clob_loop_status.json"
    observation_status_path = Path(observation_status_path)
    daily_roll_status_path = runs_root / "daily_roll_status.json"
    if snapshot_loop_status is None:
        snapshot_loop_status = read_json(snapshot_status_path, {}) or {}
    if clob_loop_status is None:
        clob_loop_status = read_json(clob_status_path, {}) or {}
    if observation_status_raw is None:
        observation_status_raw = read_json(observation_status_path, {}) or {}
    if daily_roll_status is None:
        daily_roll_status = read_json(daily_roll_status_path, {}) or {}

    loops = [
        _loop_row(
            "weather_snapshots",
            snapshot_status_path,
            snapshot_loop_status,
            now,
            ("last_snapshot_written_at",),
            useful_count_fn=lambda results: _market_result_count(results, lambda row: bool(row.get("written"))),
        ),
        _loop_row(
            "clob_books",
            clob_status_path,
            clob_loop_status,
            now,
            ("last_books_captured_at",),
            useful_count_fn=lambda results: _market_result_count(
                results,
                lambda row: (
                    _positive_numeric(row.get("books"))
                    or _positive_numeric(row.get("captured_books"))
                    or _positive_numeric(row.get("captured_tokens"))
                ),
            ),
        ),
        _loop_row(
            "observation_triggers",
            observation_status_path,
            observation_status_raw,
            now,
            ("last_poll_at_utc", "last_heartbeat"),
            useful_count_fn=lambda results: _market_result_count(results, lambda row: not row.get("error")),
        ),
    ]
    active_day_scope = (
        bool(all_market_scope)
        and evidence_mode == EVIDENCE_MODE_ACTIVE_DAY
        and mode == "paper-live-forward"
    )
    blockers = []
    if active_day_scope:
        for row in (runtime_identity or {}).get("loops") or []:
            if row.get("runtime_identity_matches_current") is False:
                blockers.append(_blocker(
                    "runtime_identity",
                    "stale_runtime_identity",
                    row.get("name") or "maker supervisor",
                    f"{row.get('name') or 'loop'} runtime identity differs from current source tree",
                    "restart the stale supervisor process so it reloads current source",
                    loop=row.get("name"),
                    status_path=row.get("status_path"),
                ))

        snapshot_loop = loops[0]
        model_threshold = maybe_float(policy_config.get("max_model_age_seconds")) or 0.0
        if not snapshot_loop["exists"]:
            blockers.append(_blocker(
                "snapshot_loop_activity",
                "snapshot_loop_status_missing",
                "weather snapshot/model loop",
                "snapshot loop status file is missing",
                "python -m weather.collection.snapshot_tracker --status",
                status_path=snapshot_loop["status_path"],
            ))
        elif snapshot_loop.get("last_useful_write_at") is None:
            blockers.append(_blocker(
                "snapshot_loop_activity",
                "snapshot_loop_no_useful_write",
                "weather snapshot/model loop",
                "snapshot loop has no last_snapshot_written_at useful-write timestamp",
                "python -m weather.collection.snapshot_tracker --status",
                status_path=snapshot_loop["status_path"],
            ))
        elif snapshot_loop.get("useful_write_age_seconds") is not None and snapshot_loop["useful_write_age_seconds"] > model_threshold:
            blockers.append(_blocker(
                "snapshot_loop_activity",
                "snapshot_loop_stale_useful_write",
                "weather snapshot/model loop",
                f"snapshot loop last useful write age {snapshot_loop['useful_write_age_seconds']}s exceeds {model_threshold}s",
                "python -m weather.collection.snapshot_tracker --status",
                last_good_timestamp=snapshot_loop.get("last_useful_write_at"),
                age_seconds=snapshot_loop.get("useful_write_age_seconds"),
                stale_threshold_seconds=model_threshold,
            ))

        clob_loop = loops[1]
        book_threshold = maybe_float(policy_config.get("max_book_age_seconds")) or 0.0
        if not clob_loop["exists"]:
            blockers.append(_blocker(
                "clob_loop_activity",
                "clob_loop_status_missing",
                "CLOB book supervisor",
                "CLOB loop status file is missing",
                "python -m weather.market.market_microstructure status",
                status_path=clob_loop["status_path"],
            ))
        elif clob_loop.get("iterations") == 0 and not clob_loop.get("within_startup_grace"):
            blockers.append(_blocker(
                "clob_loop_activity",
                "clob_loop_zero_iterations",
                "CLOB book supervisor",
                "CLOB loop has zero iterations after startup grace",
                "python -m weather.market.market_microstructure ensure",
                status_path=clob_loop["status_path"],
            ))
        elif clob_loop.get("last_useful_write_at") is None and not clob_loop.get("within_startup_grace"):
            blockers.append(_blocker(
                "clob_loop_activity",
                "clob_loop_no_useful_write",
                "CLOB book supervisor",
                "CLOB loop has no last_books_captured_at useful-write timestamp",
                "python -m weather.market.market_microstructure status",
                status_path=clob_loop["status_path"],
            ))
        elif clob_loop.get("useful_write_age_seconds") is not None and clob_loop["useful_write_age_seconds"] > book_threshold:
            blockers.append(_blocker(
                "clob_loop_activity",
                "clob_loop_stale_useful_write",
                "CLOB book supervisor",
                f"CLOB loop last useful write age {clob_loop['useful_write_age_seconds']}s exceeds {book_threshold}s",
                "python -m weather.market.market_microstructure ensure",
                last_good_timestamp=clob_loop.get("last_useful_write_at"),
                age_seconds=clob_loop.get("useful_write_age_seconds"),
                stale_threshold_seconds=book_threshold,
            ))

        observation_loop = loops[2]
        if not observation_loop["exists"]:
            blockers.append(_blocker(
                "observation_loop_activity",
                "observation_status_missing",
                "observation-trigger supervisor",
                "observation trigger status file is missing",
                "python -m weather.operations.observation_trigger ensure",
                status_path=observation_loop["status_path"],
            ))
        elif not (observation_status_raw or {}).get("last_poll_results"):
            blockers.append(_blocker(
                "observation_loop_activity",
                "observation_trigger_no_poll_results",
                "observation-trigger supervisor",
                "observation trigger has no per-market last_poll_results",
                "python -m weather.operations.observation_trigger ensure",
                status_path=observation_loop["status_path"],
            ))
        if observation_loop.get("stale_code_market_count"):
            blockers.append(_blocker(
                "observation_trigger_runtime",
                "observation_trigger_stale_code_markets",
                "observation-trigger supervisor",
                (
                    f"{observation_loop['stale_code_market_count']} observation-trigger market(s) "
                    "reported stale_code"
                ),
                "python -m weather.operations.observation_trigger ensure --force",
                market_count=observation_loop["stale_code_market_count"],
                markets=observation_loop.get("stale_code_markets") or [],
            ))
        if observation_loop.get("blocked_market_count"):
            blockers.append(_blocker(
                "observation_trigger_runtime",
                "observation_trigger_blocked_markets",
                "observation-trigger supervisor",
                f"{observation_loop['blocked_market_count']} observation-trigger market(s) returned blocked results",
                "python -m weather.operations.observation_trigger ensure",
                market_count=observation_loop["blocked_market_count"],
                markets=observation_loop.get("blocked_markets") or [],
            ))

        stale_model_markets = sorted(
            row.get("market_id") for row in preflight_rows
            if _gate_failed(row, {"snapshot_model_rows", "model_freshness"})
        )
        stale_clob_markets = sorted(
            row.get("market_id") for row in preflight_rows
            if _gate_failed(row, {"clob_books", "clob_features", "clob_freshness"})
        )
        if stale_model_markets:
            blockers.append(_blocker(
                "snapshot_model_useful_write",
                "stale_or_missing_snapshot_model_rows",
                "weather snapshot/model loop",
                f"{len(stale_model_markets)} selected market(s) have stale or missing snapshot/model rows",
                "python -m weather.collection.snapshot_tracker --status",
                market_count=len(stale_model_markets),
                markets=stale_model_markets,
            ))
        if stale_clob_markets:
            blockers.append(_blocker(
                "clob_book_useful_write",
                "stale_or_missing_clob_book_rows",
                "CLOB book supervisor",
                f"{len(stale_clob_markets)} selected market(s) have stale or missing CLOB book evidence",
                "python -m weather.market.market_microstructure ensure",
                market_count=len(stale_clob_markets),
                markets=stale_clob_markets,
            ))

        encoding_markets = sorted(
            row.get("market_id") for row in preflight_rows
            if int(((row.get("csv_encoding") or {}).get("issue_count")) or 0) > 0
        )
        if encoding_markets:
            blockers.append(_blocker(
                "clob_csv_encoding",
                "clob_csv_encoding_issue",
                "CLOB book/token artifact writer",
                f"{len(encoding_markets)} selected market(s) have CLOB CSV encoding diagnostics",
                "inspect quarantined CSV rows and rerun CLOB capture",
                market_count=len(encoding_markets),
                markets=encoding_markets,
            ))

        disk_preflight = (daily_roll_status or {}).get("disk_capacity_preflight") or {}
        if daily_roll_status and (
            daily_roll_status.get("status") == "disk_full"
            or disk_preflight.get("ok") is False
        ):
            blockers.append(_blocker(
                "daily_roll_disk",
                "disk_full_or_low_space",
                "market-making daily roll",
                disk_preflight.get("reason") or daily_roll_status.get("error") or "daily roll disk preflight failed",
                disk_preflight.get("remediation_command") or "free local disk space, then restart daily roll with --force",
                status_path=str(daily_roll_status_path),
                disk_capacity_preflight=disk_preflight,
            ))

    root_counts = Counter(row.get("root_cause") for row in blockers)
    owner_counts = Counter(row.get("owner") for row in blockers)
    status = "SKIPPED"
    reason = "not all-market active-day paper-live-forward evidence"
    if active_day_scope:
        status = "PASS" if not blockers else "BLOCK"
        reason = "all-market active-day useful-write SLA passed" if not blockers else "all-market active-day useful-write SLA blocked"
    artifact_checks = {
        "selected_market_count": len(preflight_rows or []),
        "all_market_scope": bool(all_market_scope),
        "active_day_scope": active_day_scope,
        "stale_model_market_count": sum(
            1 for row in preflight_rows if _gate_failed(row, {"snapshot_model_rows", "model_freshness"})
        ),
        "stale_clob_market_count": sum(
            1 for row in preflight_rows if _gate_failed(row, {"clob_books", "clob_features", "clob_freshness"})
        ),
        "csv_encoding_issue_count": sum(
            int(((row.get("csv_encoding") or {}).get("issue_count")) or 0)
            for row in preflight_rows
        ),
        "daily_roll_status": daily_roll_status.get("status") if daily_roll_status else None,
        "daily_roll_status_path": str(daily_roll_status_path),
        "disk_capacity_status": ((daily_roll_status or {}).get("disk_capacity_preflight") or {}).get("status"),
    }
    return {
        "schema_version": USEFUL_WORK_LIVENESS_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "status": status,
        "ok": not active_day_scope or not blockers,
        "enforced": active_day_scope,
        "reason": reason,
        "all_market_scope": bool(all_market_scope),
        "evidence_mode": evidence_mode,
        "mode": mode,
        "startup_grace_seconds": USEFUL_WORK_STARTUP_GRACE_SECONDS,
        "blocker_count": len(blockers),
        "root_cause_counts": dict(sorted(root_counts.items())),
        "owner_counts": dict(sorted(owner_counts.items())),
        "blockers": blockers,
        "loops": loops,
        "artifact_checks": artifact_checks,
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


def _top_preflight_items(items, limit=20):
    ranked = sorted(
        items.values(),
        key=lambda item: (-int(item.get("market_count") or 0), str(item.get("reason") or item.get("gate") or "")),
    )
    return ranked[:limit]


def preflight_diagnostics_summary(preflight_rows, *, limit=20):
    rows = list(preflight_rows or [])
    status_counts = Counter(row.get("status") or "-" for row in rows)
    reason_items = {}
    stale_items = {}
    gate_items = {}
    for row in rows:
        market_id = row.get("market_id") or "-"
        for reason in row.get("blocking_reasons") or []:
            item = reason_items.setdefault(reason, {"reason": reason, "market_count": 0, "markets": []})
            item["market_count"] += 1
            item["markets"].append(market_id)
        for reason in row.get("stale_reasons") or []:
            item = stale_items.setdefault(reason, {"reason": reason, "market_count": 0, "markets": []})
            item["market_count"] += 1
            item["markets"].append(market_id)
        for gate in row.get("gates") or []:
            if gate.get("ok"):
                continue
            key = (gate.get("name") or "-", gate.get("detail") or "-", gate.get("severity") or "-")
            item = gate_items.setdefault(key, {
                "gate": key[0],
                "detail": key[1],
                "severity": key[2],
                "market_count": 0,
                "markets": [],
            })
            item["market_count"] += 1
            item["markets"].append(market_id)
    for collection in (reason_items, stale_items, gate_items):
        for item in collection.values():
            item["markets"] = sorted(set(item["markets"]))
    gate_ranked = sorted(
        gate_items.values(),
        key=lambda item: (
            -int(item.get("market_count") or 0),
            str(item.get("gate") or ""),
            str(item.get("detail") or ""),
        ),
    )
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "blocked_market_count": status_counts.get("BLOCK", 0),
        "stale_market_count": status_counts.get("STALE", 0),
        "pass_market_count": status_counts.get("PASS", 0),
        "top_blocking_reasons": _top_preflight_items(reason_items, limit=limit),
        "top_stale_reasons": _top_preflight_items(stale_items, limit=limit),
        "top_failing_gates": gate_ranked[:limit],
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
    model_variant_bakeoff=None,
):
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    quote_intent_count = len(quote_rows)
    quote_permission_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    no_quote_count = max(0, quote_intent_count - quote_permission_count)
    live_rows = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    lifecycle = lifecycle or {}
    remediation = remediation or {}
    cumulative = cumulative or {}
    live_forward_gate = live_forward_gate or {}
    evidence_classification = evidence_classification or {}
    tape_integrity = tape_integrity or {}
    model_variant_bakeoff = model_variant_bakeoff or {}
    useful_work = preflight.get("useful_work_liveness") or live_forward_gate.get("useful_work_liveness") or {}
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
    if quote_permission_count:
        quote_outcome = "quoted"
    elif preflight.get("status") in {"BLOCK", "STALE", "WARN"}:
        quote_outcome = "preflight_blocked"
    elif not quote_rows:
        quote_outcome = "crashed_before_scoring"
    else:
        quote_outcome = "policy_no_quote"
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        preflight.get("markets") or [],
        permission_rows=quote_permission_count,
        output_rows=quote_intent_count,
    )
    cumulative_quote_intent_rows = int(cumulative.get("row_count", quote_intent_count) or 0)
    cumulative_quote_permission_rows = int(cumulative.get("quote_permission_rows", quote_permission_count) or 0)
    cumulative_no_quote_rows = max(0, cumulative_quote_intent_rows - cumulative_quote_permission_rows)
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
        f"- Latest-tick quote-intent rows: `{quote_intent_count}`",
        f"- Latest-tick quote-permission rows: `{quote_permission_count}`",
        f"- Quote outcome: `{quote_outcome}`",
        f"- Latest-tick no-quote rows: `{no_quote_count}`",
        f"- Zero-trade root cause: `{zero_trade_diagnosis.get('root_cause_class')}`",
        f"- First failing gate: `{zero_trade_diagnosis.get('first_failing_gate') or '-'}`",
        f"- Zero trades expected: `{str(zero_trade_diagnosis.get('zero_trades_expected')).lower()}`",
        f"- Latest-tick live-trade permission rows: `{live_rows}`",
        f"- Cumulative ticks: `{cumulative.get('tick_count', 1 if quote_rows else 0)}`",
        f"- Cumulative quote-intent rows: `{cumulative_quote_intent_rows}`",
        f"- Cumulative quote-permission rows: `{cumulative_quote_permission_rows}`",
        f"- Cumulative no-quote rows: `{cumulative_no_quote_rows}`",
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
    if useful_work:
        artifact_checks = useful_work.get("artifact_checks") or {}
        root_counts = useful_work.get("root_cause_counts") or {}
        lines.extend([
            "",
            "## Useful Work Liveness",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| Status | {useful_work.get('status') or '-'} |",
            f"| Enforced | {str(useful_work.get('enforced', False)).lower()} |",
            f"| All-market scope | {str(useful_work.get('all_market_scope', False)).lower()} |",
            f"| Reason | {useful_work.get('reason') or '-'} |",
            f"| Blockers | {useful_work.get('blocker_count', 0)} |",
            f"| Stale-code markets | {root_counts.get('observation_trigger_stale_code_markets', 0)} |",
            f"| Stale/missing model markets | {artifact_checks.get('stale_model_market_count', 0)} |",
            f"| Stale/missing CLOB markets | {artifact_checks.get('stale_clob_market_count', 0)} |",
            f"| CSV encoding issues | {artifact_checks.get('csv_encoding_issue_count', 0)} |",
            f"| Disk capacity status | {artifact_checks.get('disk_capacity_status') or '-'} |",
            "",
            "| Loop | Last useful write | Age seconds | Useful iterations | Status | Detail |",
            "| :--- | :--- | ---: | ---: | :--- | :--- |",
        ])
        for loop in useful_work.get("loops") or []:
            loop_status = "missing"
            if loop.get("exists"):
                if loop.get("last_useful_write_at"):
                    loop_status = "useful_write_seen"
                elif loop.get("within_startup_grace"):
                    loop_status = "startup_grace"
                else:
                    loop_status = "no_useful_write"
            detail = loop.get("last_error") or "-"
            if loop.get("stale_code_market_count"):
                detail = f"stale_code markets={','.join(loop.get('stale_code_markets') or [])}"
            elif loop.get("blocked_market_count"):
                detail = f"blocked markets={','.join(loop.get('blocked_markets') or [])}"
            lines.append(
                f"| {loop.get('name')} | {loop.get('last_useful_write_at') or '-'} | "
                f"{loop.get('useful_write_age_seconds') if loop.get('useful_write_age_seconds') is not None else '-'} | "
                f"{loop.get('useful_iteration_count', 0)} | {loop_status} | {detail} |"
            )
        if useful_work.get("blockers"):
            lines.extend([
                "",
                "| Gate | Root cause | Owner | Detail |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for blocker in useful_work.get("blockers")[:20]:
                lines.append(
                    f"| {blocker.get('gate')} | {blocker.get('root_cause')} | "
                    f"{blocker.get('owner')} | {blocker.get('detail')} |"
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
    if model_variant_bakeoff:
        lines.extend([
            "",
            "## Model-Variant Bakeoff",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| Status | {model_variant_bakeoff.get('status') or '-'} |",
            f"| Basket | {model_variant_bakeoff.get('basket_id') or '-'} |",
            f"| Base input rows | {model_variant_bakeoff.get('base_input_rows', 0)} |",
            f"| Materialized variant rows | {model_variant_bakeoff.get('materialized_input_rows', 0)} |",
            f"| Emitted variants | {', '.join(model_variant_bakeoff.get('emitted_variant_ids') or []) or '-'} |",
            f"| Multiple-testing family size | {model_variant_bakeoff.get('multiple_testing_family_size', 0)} |",
            "",
            "| Variant | Policy | Rows | Quote rows | Quote rate | Delta vs served |",
            "| :--- | :--- | ---: | ---: | ---: | ---: |",
        ])
        for row in (model_variant_bakeoff.get("model_variant_by_policy") or [])[:20]:
            lines.append(
                f"| {row.get('model_variant_id')} | {row.get('policy_id')} | "
                f"{row.get('row_count', 0)} | {row.get('quote_permission_rows', 0)} | "
                f"{row.get('quote_permission_rate', 0.0)} | "
                f"{row.get('delta_quote_permission_rate_vs_served_current', 0.0)} |"
            )
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
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    event_metadata_validation_path=None,
    evidence_mode=EVIDENCE_MODE_AUTO,
    active_release_pointer_path=None,
    releases_root=DEFAULT_RELEASES_ROOT,
    release_repo_root=REPO_ROOT,
    release_check_runtime=True,
):
    mode = normalize_mode(mode)
    now = utc_now(now)
    target = ensure_date(target_date)
    release_binding = load_worker_release_binding(
        pointer_path=active_release_pointer_path or DEFAULT_ACTIVE_RELEASE_POINTER,
        releases_root=releases_root,
        repo_root=release_repo_root,
        check_runtime=release_check_runtime,
        enabled=(
            active_release_pointer_path is not None
            or Path(snapshots_root).resolve()
            == Path(DEFAULT_SNAPSHOTS_ROOT).resolve()
        ),
    )
    release_summary_fields = worker_release_summary_fields(release_binding)
    quote_columns = worker_tape_columns(RUN_QUOTE_COLUMNS, release_binding)
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
    quote_path = run_folder / "quote_intents_long.csv"
    model_variant_quote_path = run_folder / "model_variant_quote_intents_long.csv"
    if append:
        verify_worker_csv_tape_for_append(
            quote_path,
            quote_columns,
            release_binding,
            label="maker quote-intent tape",
        )
        verify_worker_csv_tape_for_append(
            model_variant_quote_path,
            quote_columns,
            release_binding,
            label="maker model-variant quote-intent tape",
        )
    policy_config = {**DEFAULT_POLICY_CONFIG, **(policy_config or {})}
    policy_config["max_daily_loss"] = min(float(policy_config.get("max_daily_loss", budget_usdc)), float(budget_usdc))
    policy_config.setdefault("quote_ttl_seconds", DEFAULT_QUOTE_TTL_SECONDS)
    policy_config, clob_recon_diag = config_with_clob_recon(policy_config)

    promotion_states, promotion_diag = load_promotion_states(promotion_refresh)
    known_edge_records, known_edge_diag = load_known_edge_map(known_edge_map)
    observation = load_observation_status(observation_status_path, now=now, config=policy_config)
    runtime_identity = runtime_identity_snapshot(observation_status_path, snapshots_root=snapshots_root)
    live_readiness = load_live_readiness(live_readiness_path)
    live_ready = bool(live_readiness.get("ok"))
    data_layer_live_gate = load_data_layer_live_gate(data_layer_audit_path, target, mode)
    platform_verification_gate = load_platform_verification_gate(platform_verification_path, target, mode, now=now)
    exchange_economics_required = _uses_default_snapshot_root(snapshots_root) or exchange_economics_snapshot_path is not None
    exchange_economics_snapshot_path = exchange_economics_snapshot_path or exchange_economics.DEFAULT_SNAPSHOT
    exchange_economics_gate = exchange_economics.load_exchange_economics_gate(
        exchange_economics_snapshot_path,
        target,
        platform=exchange_economics_platform,
        now=now,
        required=exchange_economics_required,
    )
    exchange_economics_fields = exchange_economics.exchange_economics_artifact_fields(exchange_economics_gate)
    event_metadata_state = _event_metadata_preflight_payload(
        event_metadata_validation_path,
        target,
        snapshots_root,
    )
    event_metadata_state["validation_command"] = event_metadata_validation.VALIDATION_COMMAND.replace(
        "<YYYY-MM-DD>",
        target.isoformat(),
    )

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
    run_config["exchange_economics_gate"] = exchange_economics_gate
    run_config.update(exchange_economics_fields)
    run_config["event_metadata_validation"] = {
        key: value
        for key, value in event_metadata_state.items()
        if key != "payload"
    }
    run_config.update(release_summary_fields)

    raw_quote_rows = []
    model_variant_policy_inputs = []
    preflight_rows = []
    risk_events = []
    for spec in specs:
        config = config_for_date(target, spec.id)
        folder = Path(snapshots_root) / config.event_slug
        snapshot_rows = load_latest_snapshot_rows(folder)
        verify_worker_snapshot_binding(
            folder,
            snapshot_rows,
            release_binding,
            market_id=spec.id,
            target_date=target,
        )
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
            exchange_economics_gate=exchange_economics_gate,
            event_metadata_gate=_event_metadata_gate_for_market(event_metadata_state, spec.id),
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
                model_variant_policy_inputs.extend(policy_inputs)
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

    write_json(run_folder / "run_config.json", run_config)
    preflight_status = "PASS"
    if any(row.get("status") == "BLOCK" for row in preflight_rows):
        preflight_status = "BLOCK" if all(row.get("status") != "PASS" for row in preflight_rows) else "WARN"
    elif any(row.get("status") == "STALE" for row in preflight_rows):
        preflight_status = "STALE" if all(row.get("status") != "PASS" for row in preflight_rows) else "WARN"
    useful_work_liveness = build_useful_work_liveness(
        preflight_rows,
        runtime_identity=runtime_identity,
        observation_status_path=observation_status_path,
        snapshots_root=snapshots_root,
        runs_root=runs_root,
        policy_config=policy_config,
        now=now,
        all_market_scope=_all_market_scope(specs),
        evidence_mode=evidence_classification.get("evidence_mode"),
        mode=mode,
    )
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
        **release_summary_fields,
        "useful_work_liveness": useful_work_liveness,
        "live_readiness": live_readiness,
        "data_layer_live_gate": data_layer_live_gate,
        "platform_verification_gate": platform_verification_gate,
        "exchange_economics_gate": exchange_economics_gate,
        **exchange_economics_fields,
        "event_metadata_validation": {
            key: value
            for key, value in event_metadata_state.items()
            if key != "payload"
        },
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
    raw_model_variant_rows, model_variant_bakeoff = build_model_variant_quote_rows(
        model_variant_policy_inputs,
        policy_config,
        target_date=target.isoformat(),
        runtime_identity=runtime_identity,
        now=now,
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
    for row in quote_rows:
        row.update({
            "exchange_economics_snapshot_id": exchange_economics_fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": exchange_economics_fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": exchange_economics_fields.get("exchange_economics_evidence_basis"),
        })
    stamp_worker_release_lineage(quote_rows, release_binding)
    risk_events.extend(budget_risk_events)
    model_variant_quote_rows = [
        add_run_columns(
            row,
            run_id,
            target,
            mode,
            budget_usdc,
            0.0,
            quote_risk_usdc(row),
            "model_variant_shadow",
            preflight_status,
            reason="model_variant_shadow",
            quote_ttl_seconds=float(policy_config.get("quote_ttl_seconds") or DEFAULT_QUOTE_TTL_SECONDS),
        )
        for row in raw_model_variant_rows
    ]
    for row in model_variant_quote_rows:
        row.update({
            "exchange_economics_snapshot_id": exchange_economics_fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": exchange_economics_fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": exchange_economics_fields.get("exchange_economics_evidence_basis"),
        })
    stamp_worker_release_lineage(model_variant_quote_rows, release_binding)
    if any(row.get("live_trade_permission") for row in quote_rows) and mode != "live-pilot":
        raise RuntimeError("shadow/paper run attempted to emit live-trade permission")
    event_gate_summary = summarize_event_gate_rows(quote_rows)
    quote_intent_count = len(quote_rows)
    quote_permission_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    live_trade_permission_count = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    no_quote_count = max(0, quote_intent_count - quote_permission_count)
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
        output_rows=quote_intent_count,
    )
    preflight_diagnostics = preflight_diagnostics_summary(preflight_rows)
    top_preflight_blocker = (preflight_diagnostics.get("top_blocking_reasons") or [{}])[0]
    top_preflight_gate = (preflight_diagnostics.get("top_failing_gates") or [{}])[0]

    if append:
        append_csv(quote_path, quote_columns, quote_rows)
        append_csv(model_variant_quote_path, quote_columns, model_variant_quote_rows)
    else:
        write_csv(quote_path, quote_columns, quote_rows)
        write_csv(model_variant_quote_path, quote_columns, model_variant_quote_rows)
    model_variant_bakeoff_path = run_folder / "model_variant_bakeoff.json"
    model_variant_report_path = run_folder / "model_variant_bakeoff.md"
    write_json(model_variant_bakeoff_path, model_variant_bakeoff)
    model_variant_report_path.write_text(render_model_variant_report(model_variant_bakeoff), encoding="utf-8")
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
        model_variant_bakeoff=model_variant_bakeoff,
    )
    (run_folder / "run_report.md").write_text(report, encoding="utf-8")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": mode,
        **release_summary_fields,
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "preflight_path": str(run_folder / "preflight.json"),
        "quote_intents_path": str(quote_path),
        "model_variant_quote_intents_path": str(model_variant_quote_path),
        "model_variant_bakeoff_path": str(model_variant_bakeoff_path),
        "model_variant_bakeoff_report_path": str(model_variant_report_path),
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
            "quote_intent_rows": quote_intent_count,
            "quote_rows": quote_intent_count,
            "no_quote_rows": no_quote_count,
            "row_count": quote_intent_count,
            "preflight_status": preflight_status,
            **zero_trade_diagnosis,
        },
        "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
        "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
        "first_failing_detail": zero_trade_diagnosis.get("first_failing_detail"),
        "zero_trades_expected": zero_trade_diagnosis.get("zero_trades_expected"),
        "preflight_diagnostics": preflight_diagnostics,
        "known_edge_map": known_edge_diag,
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "top_preflight_blocking_reason": top_preflight_blocker.get("reason"),
            "top_preflight_blocking_markets": top_preflight_blocker.get("markets") or [],
            "top_preflight_failing_gate": top_preflight_gate.get("gate"),
            "top_preflight_failing_gate_detail": top_preflight_gate.get("detail"),
            "remediation_command": (
                (remediation_payload.get("incidents") or [{}])[0].get("suggested_command")
                if remediation_payload.get("incidents")
                else None
            ),
        },
        "live_forward_gate_status": live_forward_gate_payload.get("status"),
        "counts_toward_live_forward_gate": live_forward_gate_payload.get("counts_toward_live_forward_gate"),
        "exchange_economics_gate": exchange_economics_gate,
        **exchange_economics_fields,
        "useful_work_liveness": useful_work_liveness,
        "evidence_mode": evidence_classification.get("evidence_mode"),
        "evidence_classification": evidence_classification,
        "live_forward_gate_counts_without_evidence_mode": live_forward_gate_payload.get(
            "counts_toward_live_forward_gate_without_evidence_mode"
        ),
        "row_count": quote_intent_count,
        "quote_intent_rows": quote_intent_count,
        "quote_rows": quote_intent_count,
        "no_quote_rows": no_quote_count,
        "model_variant_row_count": len(model_variant_quote_rows),
        "quote_permission_rows": quote_permission_count,
        "live_trade_permission_rows": live_trade_permission_count,
        "reason_counts": dict(sorted(Counter(row.get("reason_code") for row in quote_rows).items())),
        "information_event_gate": event_gate_summary,
        "budget_reserved_usdc": lifecycle.get("current_reserved_usdc", 0.0),
        "budget_released_usdc": lifecycle.get("released_this_tick_usdc", 0.0),
        "open_order_count": lifecycle.get("current_open_order_count", 0),
        "budget_usdc": float(budget_usdc),
        "latest_tick": {
            "row_count": quote_intent_count,
            "quote_intent_rows": quote_intent_count,
            "quote_rows": quote_intent_count,
            "no_quote_rows": no_quote_count,
            "model_variant_row_count": len(model_variant_quote_rows),
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
        "model_variant_bakeoff": {
            "status": model_variant_bakeoff.get("status"),
            "basket_id": model_variant_bakeoff.get("basket_id"),
            "base_input_rows": model_variant_bakeoff.get("base_input_rows", 0),
            "materialized_input_rows": model_variant_bakeoff.get("materialized_input_rows", 0),
            "emitted_variant_ids": model_variant_bakeoff.get("emitted_variant_ids") or [],
            "multiple_testing_family_size": model_variant_bakeoff.get("multiple_testing_family_size", 0),
            "model_variant_by_policy": model_variant_bakeoff.get("model_variant_by_policy") or [],
            "skipped_variants": model_variant_bakeoff.get("skipped_variants") or [],
        },
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
            "useful_work_liveness": live_forward_gate_payload.get("useful_work_liveness"),
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


def format_run_cli_summary(payload):
    quote_intent_rows = int(payload.get("quote_intent_rows", payload.get("quote_rows", payload.get("row_count", 0))) or 0)
    quote_permission_rows = int(payload.get("quote_permission_rows", 0) or 0)
    no_quote_rows = int(payload.get("no_quote_rows", max(0, quote_intent_rows - quote_permission_rows)) or 0)
    live_permission_rows = int(payload.get("live_trade_permission_rows", 0) or 0)
    return (
        "MM run: "
        f"{quote_intent_rows} quote-intent rows, "
        f"{quote_permission_rows} quote-permission rows, "
        f"{no_quote_rows} no-quote rows, "
        f"{live_permission_rows} live-permission rows, "
        f"preflight {payload['preflight_status']} -> {payload['run_folder']}"
    )


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
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT), help="Current exchange economics snapshot required for paper/shadow/live evidence.")
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    parser.add_argument("--event-metadata-validation", default=str(event_metadata_validation.DEFAULT_JSON_OUT), help="Event metadata validation JSON required for default-root active-day evidence.")
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
        "exchange_economics_snapshot_path": Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        "exchange_economics_platform": args.exchange_economics_platform,
        "event_metadata_validation_path": Path(args.event_metadata_validation) if args.event_metadata_validation else None,
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
    print(format_run_cli_summary(payload))
    return payload


if __name__ == "__main__":
    main()
