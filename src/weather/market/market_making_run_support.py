"""Support helpers for date/budget market-making runs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.io import (
    append_csv_rows,
    append_jsonl as io_append_jsonl,
    csv_encoding_issue,
    read_csv_rows as io_read_csv_rows,
    read_csv_rows_with_diagnostics,
    read_jsonl,
    write_csv_rows,
)
from weather.collection.collection_health import source_family_degradation
from weather.market.market_config import ensure_date
from weather.market.market_making_run_constants import (
    DEFAULT_QUOTE_TTL_SECONDS,
    RUN_MODES,
    SCHEMA_VERSION,
)
from weather.market.market_microstructure import (
    BOOK_AUDIT_STARTUP_GRACE_SECONDS,
    SNAPSHOT_DATA_ROOT,
    audit_book_tape,
    fleet_effective_book_gap_seconds,
    parse_utc_datetime,
    read_clob_loop_status,
)
from weather.market.market_microstructure_features import clob_feature_rows_for_folder, snapshot_band_key
from weather.market.live_observation_normalization import normalized_high_fields
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.mm_policy import (
    DEFAULT_POLICY_CONFIG,
    POLICY_VERSION,
    apply_known_edge_permission,
    bool_value,
    decide_quote,
    first_present,
    load_clob_feature_index,
    maybe_float,
    parse_time,
    resolve_known_edge_record,
    source_freshness_state_from_rows,
    utc_now,
)

def read_csv_rows(path):
    return io_read_csv_rows(path, attach_diagnostics=True)


def csv_read_diagnostics(path):
    _rows, diagnostics = read_csv_rows_with_diagnostics(path, attach_diagnostics=False)
    return diagnostics


def preflight_csv_encoding_diagnostics(folder):
    folder = Path(folder)
    files = [
        folder / "clob_tokens.csv",
        folder / "order_books_summary.csv",
        folder / "clob_features_long.csv",
        folder / "source_status_long.csv",
    ]
    diagnostics = [csv_read_diagnostics(path) for path in files]
    issues = [row for row in diagnostics if csv_encoding_issue(row)]
    return {
        "status": "WARN" if issues else "OK",
        "issue_count": len(issues),
        "quarantined_row_count": sum(int(row.get("quarantined_row_count") or 0) for row in issues),
        "files": issues,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def append_jsonl(path, rows):
    return io_append_jsonl(path, list(rows or []))


def read_jsonl_rows(path):
    return read_jsonl(path)


def last_reserved_from_ledger(path):
    path = Path(path)
    if not path.exists():
        return 0.0
    reserved = 0.0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = maybe_float(row.get("reserved_usdc"))
            if value is not None:
                reserved = value
    return max(0.0, reserved)


def write_csv(path, fieldnames, rows):
    return str(write_csv_rows(path, fieldnames, rows))


def append_csv(path, fieldnames, rows):
    return str(append_csv_rows(path, fieldnames, rows))


def normalize_mode(mode):
    value = str(mode or "shadow").strip().lower()
    if value == "live":
        value = "live-pilot"
    if value not in RUN_MODES:
        raise SystemExit(f"unknown run mode {mode!r}; expected one of {sorted(RUN_MODES)}")
    return value


def market_ids_from_arg(value):
    if value in (None, "", "all"):
        return None
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def selected_specs(markets=None):
    requested = market_ids_from_arg(markets)
    if requested is None:
        return list(all_specs())
    known = {spec.id for spec in all_specs()}
    unknown = [market_id for market_id in requested if market_id not in known]
    if unknown:
        raise SystemExit(f"unknown market id(s): {', '.join(unknown)}")
    return [spec_for_id(market_id) for market_id in requested]


def make_run_id(now=None):
    now = utc_now(now)
    return now.strftime("%Y%m%dT%H%M%S%fZ")


def run_folder_for(runs_root, target_date, run_id):
    return Path(runs_root) / ensure_date(target_date).isoformat() / run_id


def latest_rows_for_snapshot(rows, snapshot_id):
    if not rows:
        return []
    if snapshot_id:
        return [row for row in rows if row.get("snapshot_id") == snapshot_id]
    latest = max(
        rows,
        key=lambda row: parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return [row for row in rows if row.get("snapshot_id") == latest.get("snapshot_id")]


def latest_book_rows(folder, outcomes=None):
    allowed_outcomes = {str(value).lower() for value in (outcomes or {"yes", ""})}
    rows = [
        row
        for row in read_csv_rows(Path(folder) / "order_books_summary.csv")
        if str(row.get("outcome") or "").lower() in allowed_outcomes
    ]
    if not rows:
        return []
    latest_time = max(parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc) for row in rows)
    return [
        row for row in rows
        if (parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc)) == latest_time
    ]


def source_status_for_snapshot(folder, snapshot_id):
    return latest_rows_for_snapshot(read_csv_rows(Path(folder) / "source_status_long.csv"), snapshot_id)


def latest_clob_feature_rows(folder, snapshot_id, build_if_missing=False, max_age_seconds=180.0, market_id=None):
    rows = latest_rows_for_snapshot(read_csv_rows(Path(folder) / "clob_features_long.csv"), snapshot_id)
    if rows or not build_if_missing or not snapshot_id:
        return rows
    generated = clob_feature_rows_for_folder(
        folder,
        max_age_seconds=max_age_seconds,
        market_id=market_id,
    )
    return latest_rows_for_snapshot(generated, snapshot_id)


def row_key_without_token(row):
    kind, value, value_hi = snapshot_band_key(row)
    return row.get("snapshot_id"), kind, value, value_hi


def clob_feature_index_from_rows(rows):
    by_token = {}
    by_band = {}
    for row in rows or []:
        kind, value, value_hi = snapshot_band_key(row)
        token = row.get("clob_token_id") or row.get("clob_yes_token_id") or ""
        snapshot_id = row.get("snapshot_id")
        by_band[(snapshot_id, kind, value, value_hi)] = row
        if token:
            by_token[(snapshot_id, kind, value, value_hi, str(token))] = row
    return by_token, by_band


def assemble_policy_inputs_for_market(
    market_id,
    folder,
    snapshot_rows,
    source_rows,
    promotion,
    observation_status,
    known_edge_records=None,
    known_edge_map_loaded=False,
    clob_feature_rows=None,
    current_high_assessment=None,
):
    if clob_feature_rows is None:
        clob_by_token, clob_by_band = load_clob_feature_index(folder)
    else:
        clob_by_token, clob_by_band = clob_feature_index_from_rows(clob_feature_rows)
    source_freshness_state = source_freshness_state_from_rows(source_rows)
    rows = []
    for snapshot_row in snapshot_rows:
        kind, value, value_hi = snapshot_band_key(snapshot_row)
        token = snapshot_row.get("clob_token_id") or snapshot_row.get("clob_yes_token_id") or ""
        token_key = (snapshot_row.get("snapshot_id"), kind, value, value_hi, str(token))
        band_key = (snapshot_row.get("snapshot_id"), kind, value, value_hi)
        clob_row = clob_by_token.get(token_key) or clob_by_band.get(band_key) or {}
        merged = dict(snapshot_row)
        merged.update({key: value for key, value in clob_row.items() if value not in (None, "")})
        merged["market_id"] = market_id
        merged["promotion_state"] = promotion.get("promotion_state", "BLOCK")
        merged["fair_probability"] = first_present(merged, "fair_probability", "model_probability", "candidate_p")
        merged["market_mid"] = merged.get("clob_midpoint") or merged.get("market_yes")
        merged["book_spread"] = merged.get("clob_spread")
        if merged.get("book_spread") in (None, ""):
            best_ask = maybe_float(merged.get("best_ask"))
            best_bid = maybe_float(merged.get("best_bid"))
            merged["book_spread"] = (
                best_ask - best_bid
                if best_ask is not None and best_bid is not None
                else ""
            )
        merged["book_age_seconds"] = merged.get("clob_book_age_seconds")
        merged["watcher_age_seconds"] = observation_status.get("watcher_age_seconds")
        merged["heartbeat_ok"] = observation_status.get("heartbeat_ok", False)
        merged["source_fresh"] = observation_status.get("fresh", False)
        merged["source_freshness_state"] = source_freshness_state
        merged.update(normalized_high_fields(current_high_assessment))
        record = resolve_known_edge_record(merged, known_edge_records or [])
        merged = apply_known_edge_permission(
            merged,
            record=record,
            map_loaded=known_edge_map_loaded,
        )
        rows.append(merged)
    return rows


def boolish_active(value):
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"active", "open", "1", "true", "yes"}:
        return True
    if text in {"closed", "inactive", "0", "false", "no"}:
        return False
    return True


def clob_token_discovery_health(token_rows):
    rows = list(token_rows or [])
    yes_rows = [
        row for row in rows
        if str(row.get("outcome") or "").strip().lower() in {"", "yes"}
    ]
    active_rows = [
        row for row in yes_rows
        if boolish_active(row.get("active")) and not bool_value(row.get("closed"), False)
    ]
    rows_with_token = [row for row in active_rows if row.get("clob_token_id")]
    rows_with_condition = [row for row in active_rows if row.get("condition_id")]
    active_blank_rows = [
        row for row in active_rows
        if not row.get("clob_token_id") and not row.get("condition_id")
    ]
    if rows_with_token and rows_with_condition:
        status = "PASS"
        root_cause = None
        reason = "active CLOB token discovery has token and condition ids"
    elif not rows:
        status = "BLOCK"
        root_cause = "missing_clob_token_file_rows"
        reason = "clob_tokens.csv has no rows"
    elif yes_rows and not active_rows:
        status = "BLOCK"
        root_cause = "inactive_gamma_market_rows"
        reason = "all YES CLOB token rows are inactive or closed"
    elif active_rows and len(active_blank_rows) == len(active_rows):
        status = "BLOCK"
        root_cause = "blank_clob_token_ids"
        reason = "active CLOB token rows have blank clob_token_id and condition_id"
    else:
        status = "BLOCK"
        root_cause = "partial_clob_token_discovery"
        reason = "active CLOB token rows are missing token ids or condition ids"
    return {
        "status": status,
        "ok": status == "PASS",
        "root_cause": root_cause,
        "reason": reason,
        "token_file_rows": len(rows),
        "yes_token_rows": len(yes_rows),
        "active_token_file_rows": len(active_rows),
        "rows_with_token_id": len(rows_with_token),
        "rows_with_condition_id": len(rows_with_condition),
        "active_blank_token_rows": len(active_blank_rows),
    }


def first_failed_gate(preflight_row):
    for gate in preflight_row.get("gates") or []:
        if not gate.get("ok"):
            return gate
    return {}


def has_failed_gate(preflight_row, gate_name):
    return any(
        gate.get("name") == gate_name and not gate.get("ok")
        for gate in preflight_row.get("gates") or []
    )


def classify_zero_trade_root_cause(preflight_rows, *, permission_rows=0, output_rows=0):
    rows = list(preflight_rows or [])
    blocked = [row for row in rows if row.get("status") != "PASS"]
    first_gate = first_failed_gate(blocked[0]) if blocked else {}
    if blocked:
        if len(blocked) == len(rows) and rows and all(
            has_failed_gate(row, "clob_discovery")
            or has_failed_gate(row, "active_event")
            or has_failed_gate(row, "event_metadata_validation")
            for row in blocked
        ):
            root_class = "blocked_by_market_discovery"
        elif len(blocked) == len(rows) and rows and all(has_failed_gate(row, "clob_books") for row in blocked):
            root_class = "blocked_by_clob_books"
        else:
            root_class = "blocked_by_preflight"
        return {
            "root_cause_class": root_class,
            "first_failing_gate": first_gate.get("name"),
            "first_failing_detail": first_gate.get("detail"),
            "blocked_market_count": len(blocked),
            "zero_trades_expected": True,
        }
    if output_rows and not permission_rows:
        return {
            "root_cause_class": "policy_no_edge",
            "first_failing_gate": "policy",
            "first_failing_detail": "policy produced rows but no executable permissions",
            "blocked_market_count": 0,
            "zero_trades_expected": True,
        }
    if not output_rows:
        return {
            "root_cause_class": "crashed_before_scoring",
            "first_failing_gate": "scoring",
            "first_failing_detail": "no output rows were produced",
            "blocked_market_count": 0,
            "zero_trades_expected": False,
        }
    return {
        "root_cause_class": "trading_permissions_emitted",
        "first_failing_gate": None,
        "first_failing_detail": None,
        "blocked_market_count": 0,
        "zero_trades_expected": False,
    }


def source_status_is_current(rows):
    if not rows:
        return False
    return any(
        bool_value(row.get("ok"), False)
        and str(row.get("status") or "").lower() in {"fresh", "fresh_cache", "ok", "available", ""}
        and not bool_value(row.get("stale"), False)
        for row in rows
    )


def source_status_degradation_preflight(folder, snapshot_id):
    payload = source_family_degradation(folder)
    available = bool(payload.get("available"))
    payload_snapshot_id = payload.get("snapshot_id")
    snapshot_matches = bool(available and (not snapshot_id or payload_snapshot_id == snapshot_id))
    trading_allowed = bool(payload.get("trading_evidence_allowed"))
    if not available:
        status = "BLOCK"
        root_cause = "missing_source_status_row"
        reason = payload.get("reason") or "source-status proof is unavailable"
    elif not snapshot_matches:
        status = "BLOCK"
        root_cause = "stale_source_status_row"
        reason = (
            f"source-status proof snapshot {payload_snapshot_id or '(missing)'} "
            f"does not match latest snapshot {snapshot_id or '(missing)'}"
        )
    elif not trading_allowed:
        status = "BLOCK"
        root_cause = "source_status_degradation_blocked"
        reason = (
            "source-status degradation blocks trading evidence: "
            f"blocking_families={payload.get('blocking_family_count', 0)} "
            f"settlement_auth_failures={payload.get('settlement_auth_failure_source_count', 0)}"
        )
    else:
        status = "PASS"
        root_cause = "source_status_clean"
        reason = "source-status degradation allows trading evidence"
    return {
        "status": status,
        "ok": status == "PASS",
        "root_cause": root_cause,
        "reason": reason,
        "available": available,
        "snapshot_id": payload_snapshot_id,
        "snapshot_matches": snapshot_matches,
        "affected_family_count": payload.get("affected_family_count", 0),
        "blocking_family_count": payload.get("blocking_family_count", 0),
        "failed_source_count": payload.get("failed_source_count", 0),
        "fallback_source_count": payload.get("fallback_source_count", 0),
        "settlement_auth_failure_source_count": payload.get("settlement_auth_failure_source_count", 0),
        "provider_cooldown_source_count": payload.get("provider_cooldown_source_count", 0),
        "expected_unavailable_source_count": payload.get("expected_unavailable_source_count", 0),
        "trading_evidence_allowed": trading_allowed,
        "live_trade_permission_allowed": bool(payload.get("live_trade_permission_allowed")),
        "promotion_readiness_allowed": bool(payload.get("promotion_readiness_allowed")),
        "claim_lane_allowance": payload.get("claim_lane_allowance") or {},
    }


def metadata_from_books(rows):
    min_order_sizes = [maybe_float(row.get("min_order_size")) for row in rows]
    tick_sizes = [maybe_float(row.get("tick_size")) for row in rows]
    min_order_sizes = [value for value in min_order_sizes if value is not None]
    tick_sizes = [value for value in tick_sizes if value is not None]
    return {
        "available": bool(min_order_sizes and tick_sizes),
        "min_order_size": min(min_order_sizes) if min_order_sizes else None,
        "tick_size": min(tick_sizes) if tick_sizes else None,
    }


def uses_default_snapshot_root(folder):
    try:
        folder_path = Path(folder).resolve()
        default_root = SNAPSHOT_DATA_ROOT.resolve()
        return folder_path == default_root or default_root in folder_path.parents
    except OSError:
        return False


def preflight_book_audit(folder, now, max_gap_seconds, loop_status=None):
    """Audit active-day CLOB books with the same loop-aware policy as fleet checks."""
    loop_status = read_clob_loop_status() if loop_status is None and uses_default_snapshot_root(folder) else loop_status
    effective_gap_seconds = fleet_effective_book_gap_seconds(max_gap_seconds, loop_status)
    ignore_cutoff = None
    if loop_status:
        started_at = parse_utc_datetime(loop_status.get("started_at"))
        if started_at is not None:
            ignore_cutoff = started_at + timedelta(seconds=BOOK_AUDIT_STARTUP_GRACE_SECONDS)
    return audit_book_tape(
        folder,
        now=now,
        max_gap_seconds=effective_gap_seconds,
        ignore_gaps_before=ignore_cutoff,
    )


def preflight_market(
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
    live_ready=False,
    live_confirmed=False,
    pilot=False,
    data_layer_live_gate=None,
    platform_verification_gate=None,
    exchange_economics_gate=None,
    event_metadata_gate=None,
    current_high_assessment=None,
):
    gates = []
    blockers = []
    stale = []
    folder = Path(folder)
    snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
    latest_capture = parse_time(snapshot_rows[0].get("captured_at_utc")) if snapshot_rows else None
    model_age = (now - latest_capture).total_seconds() if latest_capture else None
    source_status_times = [
        parse_time(row.get("captured_at_utc") or row.get("fetched_at"))
        for row in source_rows or []
    ]
    source_status_times = [value for value in source_status_times if value is not None]
    source_status_latest = max(source_status_times) if source_status_times else None
    source_status_fresh = source_status_is_current(source_rows)
    source_status_degradation = source_status_degradation_preflight(folder, snapshot_id) if source_rows else {
        "status": "SKIPPED",
        "ok": True,
        "root_cause": "source_status_rows_missing",
        "reason": "source-status degradation gate skipped until source rows exist",
        "available": False,
        "snapshot_id": None,
        "snapshot_matches": False,
        "trading_evidence_allowed": False,
        "live_trade_permission_allowed": False,
        "promotion_readiness_allowed": False,
        "claim_lane_allowance": {},
    }
    book_audit = preflight_book_audit(
        folder,
        now=now,
        max_gap_seconds=float(policy_config["max_book_age_seconds"]),
    )
    csv_encoding = preflight_csv_encoding_diagnostics(folder)
    token_rows = read_csv_rows(folder / "clob_tokens.csv")
    token_discovery = clob_token_discovery_health(token_rows)
    token_count = sum(1 for row in token_rows if row.get("clob_token_id") and str(row.get("outcome") or "").lower() in {"yes", ""})
    condition_count = len({row.get("condition_id") for row in token_rows if row.get("condition_id")})
    reward_metadata = metadata_from_books(book_rows)

    def add_gate(name, ok, severity, detail):
        gate = {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}
        gates.append(gate)
        if ok:
            return
        if severity == "stale":
            stale.append(detail)
        else:
            blockers.append(detail)

    add_gate("active_event", any(boolish_active(row.get("market_status")) for row in snapshot_rows), "missing", "no active current market rows")
    event_metadata_gate = event_metadata_gate or {"required": False, "ok": True}
    if event_metadata_gate.get("required"):
        add_gate(
            "event_metadata_validation",
            bool(event_metadata_gate.get("ok")),
            "missing",
            event_metadata_gate.get("reason") or "event metadata validation does not permit active-day evidence",
        )
    add_gate("snapshot_model_rows", bool(snapshot_rows), "missing", "missing current snapshot/model rows")
    add_gate(
        "model_freshness",
        model_age is not None and model_age <= float(policy_config["max_model_age_seconds"]),
        "stale",
        "current model snapshot is stale or timestamp is missing",
    )
    add_gate("source_status_rows", bool(source_rows), "missing", "missing current source-status rows")
    add_gate("source_status_fresh", source_status_fresh, "stale", "no fresh source-status row for latest snapshot")
    if source_rows:
        add_gate(
            "source_status_degradation",
            source_status_degradation.get("ok"),
            "missing",
            source_status_degradation.get("reason") or "source-status degradation blocks trading evidence",
        )
    add_gate("clob_discovery", token_discovery.get("ok"), "missing", token_discovery.get("reason"))
    add_gate("clob_tokens", token_count > 0 and condition_count > 0, "missing", "missing CLOB token ids or condition ids")
    add_gate("clob_books", bool(book_rows), "missing", "missing current CLOB book rows")
    add_gate("clob_features", bool(clob_feature_rows), "missing", "missing band-level CLOB feature rows")
    add_gate("clob_freshness", bool(book_audit.get("ok")), "stale", book_audit.get("reason") or "CLOB book audit failed")
    add_gate("observation_trigger", bool(observation.get("fresh")), "stale", observation.get("reason") or "observation watcher is stale")
    add_gate("promotion_state", bool(promotion.get("promotion_state")), "missing", "missing promotion state")
    add_gate("reward_metadata", reward_metadata.get("available"), "missing", "missing min-order-size or tick-size metadata")
    data_layer_live_gate = data_layer_live_gate or {"required": False, "ok": True}
    if data_layer_live_gate.get("required"):
        add_gate(
            "data_layer_live_gate",
            bool(data_layer_live_gate.get("ok")),
            "missing",
            data_layer_live_gate.get("reason") or "latest data-layer audit does not prove live CLOB artifacts",
        )
    platform_verification_gate = platform_verification_gate or {"required": False, "ok": True}
    if platform_verification_gate.get("required"):
        add_gate(
            "platform_verification_gate",
            bool(platform_verification_gate.get("ok")),
            "missing",
            platform_verification_gate.get("reason") or "platform/account verification is not current",
        )
    exchange_economics_gate = exchange_economics_gate or {"required": False, "ok": True}
    if exchange_economics_gate.get("required"):
        add_gate(
            "exchange_economics_gate",
            bool(exchange_economics_gate.get("ok")),
            "missing",
            exchange_economics_gate.get("reason") or "exchange economics snapshot is not current",
        )

    live_gate = {
        "required": mode == "live-pilot",
        "pilot_flag": bool(pilot),
        "confirm_live_orders": bool(live_confirmed),
        "live_ready": bool(live_ready),
        "platform_verified": bool(platform_verification_gate.get("ok")),
        "ok": mode != "live-pilot" or (
            pilot and live_confirmed and live_ready and bool(platform_verification_gate.get("ok"))
        ),
    }
    if mode == "live-pilot" and not live_gate["ok"]:
        blockers.append(
            "live-pilot requires --pilot, --confirm-live-orders, "
            "a passing live-readiness file, and passing platform verification"
        )
        gates.append({
            "name": "live_account_gate",
            "ok": False,
            "severity": "missing",
            "detail": "live account/platform/wallet/allowance/heartbeat/user-WS readiness is not verified",
        })

    if blockers:
        status = "BLOCK"
        reason_kind = "missing_preflight"
    elif stale:
        status = "STALE"
        reason_kind = "stale_input"
    else:
        status = "PASS"
        reason_kind = None

    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": config.target_date.isoformat(),
        "event_slug": config.event_slug,
        "folder": str(folder),
        "status": status,
        "reason_kind": reason_kind,
        "blocking_reasons": blockers,
        "stale_reasons": stale,
        "gates": gates,
        "first_failing_gate": first_failed_gate({"gates": gates}),
        "snapshot_rows": len(snapshot_rows),
        "latest_snapshot_id": snapshot_rows[0].get("snapshot_id") if snapshot_rows else None,
        "latest_capture_utc": latest_capture.isoformat() if latest_capture else None,
        "model_age_seconds": round(model_age, 1) if model_age is not None else None,
        "source_status_rows": len(source_rows),
        "source_status_latest_utc": source_status_latest.isoformat() if source_status_latest else None,
        "source_status_fresh": source_status_fresh,
        "source_status_degradation": source_status_degradation,
        "clob_token_rows": token_count,
        "clob_token_discovery": token_discovery,
        "condition_ids": condition_count,
        "book_rows": len(book_rows),
        "clob_feature_rows": len(clob_feature_rows),
        "book_audit": book_audit,
        "csv_encoding": csv_encoding,
        "promotion_state": promotion.get("promotion_state"),
        "promotion_action": promotion.get("action"),
        "reward_metadata": reward_metadata,
        "live_gate": live_gate,
        "data_layer_live_gate": data_layer_live_gate,
        "platform_verification_gate": platform_verification_gate,
        "exchange_economics_gate": exchange_economics_gate,
        "event_metadata_gate": event_metadata_gate,
        "current_high_assessment": current_high_assessment or {},
    }


def preflight_no_quote(input_row, config, now, reason_kind, details):
    reason_code = "NO_QUOTE_STALE_INPUT" if reason_kind == "stale_input" else "NO_QUOTE_MISSING_PREFLIGHT"
    detail = "; ".join(details) if details else reason_kind
    row = decide_quote(
        {
            **input_row,
            "promotion_state": input_row.get("promotion_state") or "BLOCK",
            "heartbeat_ok": False,
            "source_fresh": False,
        },
        config=config,
        now=now,
    )
    row.update({
        "quote_permission": False,
        "action": "NO_QUOTE",
        "regime": "none",
        "side": "-",
        "reason_code": reason_code,
        "reason_detail": detail,
        "bid_price": None,
        "bid_size": 0.0,
        "ask_price": None,
        "ask_size": 0.0,
        "latency_budget_status": "blocked",
    })
    return row


def placeholder_no_quote(spec, config, now, policy_config, reason_code, reason_detail):
    row = decide_quote(
        {
            "market_id": spec.id,
            "event_slug": config.event_slug,
            "captured_at_utc": "",
            "promotion_state": "BLOCK",
            "heartbeat_ok": False,
            "source_fresh": False,
            "range_label": "",
        },
        config=policy_config,
        now=now,
    )
    row.update({
        "market_id": spec.id,
        "event_slug": config.event_slug,
        "reason_code": reason_code,
        "reason_detail": reason_detail,
    })
    return row


def quote_risk_usdc(row):
    bid = maybe_float(row.get("bid_price"))
    bid_size = maybe_float(row.get("bid_size")) or 0.0
    ask = maybe_float(row.get("ask_price"))
    ask_size = maybe_float(row.get("ask_size")) or 0.0
    risk = 0.0
    if bid is not None:
        risk += max(0.0, bid) * max(0.0, bid_size)
    if ask is not None:
        risk += max(0.0, 1.0 - ask) * max(0.0, ask_size)
    return risk


OPEN_LIFECYCLE_TRANSITIONS = {"paper_posted", "live_posted"}
TERMINAL_LIFECYCLE_TRANSITIONS = {
    "released",
    "replaced",
    "canceled",
    "expired",
    "blocked_by_preflight",
    "rejected",
}


def _round_money(value):
    return round(float(value or 0.0), 6)


def _lifecycle_hash(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def quote_leg_intents(row, run_id, target_date, mode, now, quote_ttl_seconds):
    """Split a quote-intent row into one lifecycle intent per posted leg."""
    if not row.get("quote_permission"):
        return []
    generated = parse_time(row.get("generated_at_utc")) or now
    ttl = float(quote_ttl_seconds or DEFAULT_QUOTE_TTL_SECONDS)
    expires = generated + timedelta(seconds=max(0.0, ttl))
    base = {
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "run_mode": mode,
        "generated_at_utc": generated.isoformat(),
        "event_slug": row.get("event_slug") or "",
        "market_id": row.get("market_id") or "",
        "condition_id": row.get("condition_id") or "",
        "clob_token_id": row.get("clob_token_id") or "",
        "range_label": row.get("range_label") or "",
        "policy_hash": row.get("policy_hash") or "",
        "policy_version": row.get("policy_version") or POLICY_VERSION,
        "quote_ttl_seconds": ttl,
        "expires_at_utc": expires.isoformat(),
    }
    legs = []
    bid = maybe_float(row.get("bid_price"))
    bid_size = maybe_float(row.get("bid_size")) or 0.0
    if bid is not None and bid_size > 0:
        legs.append({**base, "side": "YES_BID", "price": bid, "size": bid_size, "open_risk_usdc": bid * bid_size})
    ask = maybe_float(row.get("ask_price"))
    ask_size = maybe_float(row.get("ask_size")) or 0.0
    if ask is not None and ask_size > 0:
        legs.append({**base, "side": "YES_ASK", "price": ask, "size": ask_size, "open_risk_usdc": max(0.0, 1.0 - ask) * ask_size})
    for leg in legs:
        key_payload = {
            "run_id": leg["run_id"],
            "generated_at_utc": leg["generated_at_utc"],
            "event_slug": leg["event_slug"],
            "condition_id": leg["condition_id"],
            "clob_token_id": leg["clob_token_id"],
            "side": leg["side"],
            "price": round(float(leg["price"]), 6),
            "size": round(float(leg["size"]), 6),
            "policy_hash": leg["policy_hash"],
            "quote_ttl_seconds": leg["quote_ttl_seconds"],
        }
        leg["lifecycle_key"] = _lifecycle_hash(key_payload)
        leg["order_key"] = _lifecycle_hash({
            key: value
            for key, value in key_payload.items()
            if key not in {"generated_at_utc", "price", "size"}
        })
        leg["open_risk_usdc"] = _round_money(leg["open_risk_usdc"])
        leg["remaining_size"] = round(float(leg["size"]), 6)
        leg["remaining_risk_usdc"] = leg["open_risk_usdc"]
    return legs


def lifecycle_reserved_usdc(open_orders):
    return _round_money(sum(maybe_float(row.get("remaining_risk_usdc")) or maybe_float(row.get("open_risk_usdc")) or 0.0 for row in open_orders.values()))


def lifecycle_fill_transition(open_order, event):
    old_size = maybe_float(open_order.get("remaining_size")) or maybe_float(open_order.get("size")) or 0.0
    old_risk = maybe_float(open_order.get("remaining_risk_usdc")) or maybe_float(open_order.get("open_risk_usdc")) or 0.0
    fill_size = maybe_float(event.get("fill_size")) or maybe_float(event.get("filled_size")) or 0.0
    if old_size <= 0 or fill_size <= 0:
        return open_order
    new_size = max(0.0, old_size - fill_size)
    risk_per_share = old_risk / old_size if old_size > 0 else 0.0
    updated = dict(open_order)
    updated["remaining_size"] = round(new_size, 6)
    updated["remaining_risk_usdc"] = _round_money(new_size * risk_per_share)
    updated["last_fill_at_utc"] = event.get("generated_at_utc") or event.get("filled_at_utc")
    return updated if new_size > 1e-9 else None


def load_open_lifecycle_orders(path):
    state = {}
    for event in read_jsonl_rows(path):
        key = event.get("lifecycle_key")
        if not key:
            continue
        transition = event.get("transition") or event.get("event")
        if transition in OPEN_LIFECYCLE_TRANSITIONS:
            opened = dict(event)
            opened["remaining_size"] = maybe_float(opened.get("remaining_size")) or maybe_float(opened.get("size")) or 0.0
            opened["remaining_risk_usdc"] = maybe_float(opened.get("remaining_risk_usdc")) or maybe_float(opened.get("open_risk_usdc")) or 0.0
            state[key] = opened
        elif transition == "filled":
            if key in state:
                updated = lifecycle_fill_transition(state[key], event)
                if updated is None:
                    state.pop(key, None)
                else:
                    state[key] = updated
        elif transition in TERMINAL_LIFECYCLE_TRANSITIONS:
            state.pop(key, None)
    return state


def lifecycle_release_event(open_order, now, transition, reason, reserved_after):
    posted_at = parse_time(open_order.get("posted_at_utc") or open_order.get("generated_at_utc"))
    age = (now - posted_at).total_seconds() if posted_at else None
    risk = maybe_float(open_order.get("remaining_risk_usdc")) or maybe_float(open_order.get("open_risk_usdc")) or 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": open_order.get("run_id"),
        "generated_at_utc": now.isoformat(),
        "transition": transition,
        "lifecycle_key": open_order.get("lifecycle_key"),
        "order_key": open_order.get("order_key"),
        "market_id": open_order.get("market_id"),
        "event_slug": open_order.get("event_slug"),
        "condition_id": open_order.get("condition_id"),
        "clob_token_id": open_order.get("clob_token_id"),
        "range_label": open_order.get("range_label"),
        "side": open_order.get("side"),
        "price": open_order.get("price"),
        "size": open_order.get("size"),
        "remaining_size": open_order.get("remaining_size"),
        "released_risk_usdc": _round_money(risk),
        "reserved_usdc_after": _round_money(reserved_after),
        "reason": reason,
        "stale_age_seconds": round(age, 1) if age is not None else None,
    }


def lifecycle_post_events(leg, now, mode):
    posted_transition = "live_posted" if mode == "live-pilot" else "paper_posted"
    intended = {
        "schema_version": SCHEMA_VERSION,
        "run_id": leg["run_id"],
        "generated_at_utc": now.isoformat(),
        "transition": "intended",
        **leg,
    }
    posted = {
        "schema_version": SCHEMA_VERSION,
        "run_id": leg["run_id"],
        "generated_at_utc": now.isoformat(),
        "posted_at_utc": now.isoformat(),
        "transition": posted_transition,
        **leg,
    }
    return [intended, posted]


def lifecycle_blocked_by_budget_events(legs, now):
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": leg["run_id"],
            "generated_at_utc": now.isoformat(),
            "transition": "blocked_by_budget",
            "reason": "run budget exhausted before quote could be posted",
            **leg,
        }
        for leg in legs
    ]


def lifecycle_summary(open_orders, budget, released_events, posted_events, now):
    reserved_by_market = Counter()
    reserved_by_event = Counter()
    stale = []
    for order in open_orders.values():
        risk = maybe_float(order.get("remaining_risk_usdc")) or maybe_float(order.get("open_risk_usdc")) or 0.0
        reserved_by_market[order.get("market_id") or "-"] += risk
        reserved_by_event[order.get("event_slug") or "-"] += risk
        expires = parse_time(order.get("expires_at_utc"))
        if expires is not None and expires < now:
            stale.append(order.get("lifecycle_key"))
    released_total = sum(maybe_float(row.get("released_risk_usdc")) or 0.0 for row in released_events)
    current_reserved = lifecycle_reserved_usdc(open_orders)
    return {
        "schema_version": SCHEMA_VERSION,
        "current_open_order_count": len(open_orders),
        "current_reserved_usdc": current_reserved,
        "released_this_tick_usdc": _round_money(released_total),
        "released_this_tick_count": len(released_events),
        "posted_this_tick_count": sum(1 for row in posted_events if row.get("transition") in OPEN_LIFECYCLE_TRANSITIONS),
        "stale_open_order_count": len(stale),
        "reserved_by_market": {key: _round_money(value) for key, value in sorted(reserved_by_market.items())},
        "reserved_by_event": {key: _round_money(value) for key, value in sorted(reserved_by_event.items())},
        "platform_balance_semantics": {
            "operator_run_budget_usdc": float(budget),
            "operator_run_budget_is_binding": True,
            "polymarket_cross_market_open_orders_may_exceed_wallet_balance": True,
            "same_market_open_orders_still_need_event_level_worst_case_backing": True,
            "current_open_order_risk_usdc": current_reserved,
        },
    }


def budget_exhausted_row(row, now, budget, reserved, risk):
    out = dict(row)
    out.update({
        "quote_permission": False,
        "action": "NO_QUOTE",
        "regime": "none",
        "side": "-",
        "reason_code": "NO_QUOTE_BUDGET_EXHAUSTED",
        "reason_detail": "budget_exhausted: quote risk would exceed run budget",
        "bid_price": None,
        "bid_size": 0.0,
        "ask_price": None,
        "ask_size": 0.0,
        "quote_risk_usdc": round(risk, 6),
        "budget_reserved_usdc": round(reserved, 6),
        "budget_remaining_usdc": round(max(0.0, budget - reserved), 6),
        "budget_action": "budget_exhausted",
        "orchestrator_reason_code": "budget_exhausted",
        "generated_at_utc": now.isoformat(),
    })
    return out


def cancel_all_row(row, now, budget, reserved):
    out = dict(row)
    out.update({
        "quote_permission": False,
        "action": "NO_QUOTE",
        "regime": "none",
        "side": "-",
        "reason_code": "NO_QUOTE_CANCEL_ALL",
        "reason_detail": "cancel_all: global cancel-all flag is present",
        "bid_price": None,
        "bid_size": 0.0,
        "ask_price": None,
        "ask_size": 0.0,
        "quote_risk_usdc": 0.0,
        "budget_reserved_usdc": round(reserved, 6),
        "budget_remaining_usdc": round(max(0.0, budget - reserved), 6),
        "budget_action": "cancel_all",
        "orchestrator_reason_code": "cancel_all",
        "generated_at_utc": now.isoformat(),
    })
    return out


def add_run_columns(
    row,
    run_id,
    target_date,
    mode,
    budget,
    reserved,
    risk,
    budget_action,
    preflight_status,
    reason=None,
    lifecycle_keys=None,
    quote_ttl_seconds=None,
    open_order_count=0,
    released_usdc=0.0,
):
    out = dict(row)
    out.update({
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "run_mode": mode,
        "orchestrator_schema_version": SCHEMA_VERSION,
        "orchestrator_reason_code": reason or "",
        "preflight_status": preflight_status,
        "quote_risk_usdc": round(risk, 6),
        "run_budget_usdc": round(float(budget), 6),
        "budget_reserved_usdc": round(float(reserved), 6),
        "budget_remaining_usdc": round(max(0.0, float(budget) - float(reserved)), 6),
        "budget_action": budget_action,
        "exchange_validity_reserved_usdc": round(float(reserved), 6),
        "order_lifecycle_keys": ";".join(lifecycle_keys or []),
        "quote_ttl_seconds": float(quote_ttl_seconds or DEFAULT_QUOTE_TTL_SECONDS),
        "open_order_count": int(open_order_count or 0),
        "budget_released_usdc": round(float(released_usdc or 0.0), 6),
    })
    if mode != "live-pilot":
        out["live_trade_permission"] = False
    return out


def apply_run_budget(
    rows,
    budget_usdc,
    run_id,
    target_date,
    mode,
    now,
    preflight_by_market,
    initial_reserved_usdc=0.0,
    previous_open_orders=None,
    quote_ttl_seconds=DEFAULT_QUOTE_TTL_SECONDS,
    cancel_all=False,
):
    budget = float(budget_usdc)
    open_orders = dict(previous_open_orders or {})
    initial_reserved = lifecycle_reserved_usdc(open_orders)
    if not open_orders and initial_reserved_usdc:
        initial_reserved = min(max(0.0, float(initial_reserved_usdc or 0.0)), budget)
    out_rows = []
    ledger = [{
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "event": "run_budget_start",
        "budget_action": "run_budget_start",
        "budget_usdc": budget,
        "reserved_usdc": round(initial_reserved, 6),
        "remaining_usdc": round(max(0.0, budget - initial_reserved), 6),
        "detail": "run risk budget initialized",
    }]
    risk_events = []
    lifecycle_events = []

    current_legs_by_key = {}
    for row in rows:
        for leg in quote_leg_intents(row, run_id, target_date, mode, now, quote_ttl_seconds):
            current_legs_by_key[leg["lifecycle_key"]] = leg
    current_order_keys = {leg.get("order_key") for leg in current_legs_by_key.values()}

    released_events = []
    for key, open_order in list(open_orders.items()):
        market_preflight = preflight_by_market.get(open_order.get("market_id") or "", {})
        preflight_status = market_preflight.get("status") or "UNKNOWN"
        expires = parse_time(open_order.get("expires_at_utc"))
        transition = None
        reason = None
        if cancel_all:
            transition = "canceled"
            reason = "global cancel-all flag present"
        elif preflight_status != "PASS":
            transition = "blocked_by_preflight"
            reason = f"market preflight {preflight_status}"
        elif expires is not None and expires <= now:
            transition = "expired"
            reason = "quote TTL expired"
        elif key not in current_legs_by_key:
            if open_order.get("order_key") in current_order_keys:
                transition = "replaced"
                reason = "quote replaced by latest policy tick"
            else:
                transition = "released"
                reason = "quote no longer present in latest policy tick"
        if transition is None:
            continue
        open_orders.pop(key, None)
        reserved_after = lifecycle_reserved_usdc(open_orders)
        release_event = lifecycle_release_event(open_order, now, transition, reason, reserved_after)
        lifecycle_events.append(release_event)
        released_events.append(release_event)
        ledger.append({
            "run_id": run_id,
            "generated_at_utc": now.isoformat(),
            "event": f"reservation_{transition}",
            "budget_action": transition,
            "market_id": open_order.get("market_id"),
            "event_slug": open_order.get("event_slug"),
            "range_label": open_order.get("range_label"),
            "lifecycle_key": key,
            "quote_risk_usdc": round(maybe_float(open_order.get("remaining_risk_usdc")) or maybe_float(open_order.get("open_risk_usdc")) or 0.0, 6),
            "released_risk_usdc": release_event["released_risk_usdc"],
            "reserved_usdc": reserved_after,
            "remaining_usdc": round(max(0.0, budget - reserved_after), 6),
            "detail": reason,
        })
        risk_events.append({
            "run_id": run_id,
            "generated_at_utc": now.isoformat(),
            "severity": "info",
            "category": "order_lifecycle",
            "market_id": open_order.get("market_id"),
            "reason": transition,
            "detail": reason,
        })

    reserved = lifecycle_reserved_usdc(open_orders)
    released_total = sum(maybe_float(row.get("released_risk_usdc")) or 0.0 for row in released_events)
    posted_events = []
    for row in rows:
        legs = quote_leg_intents(row, run_id, target_date, mode, now, quote_ttl_seconds)
        lifecycle_keys = [leg["lifecycle_key"] for leg in legs]
        new_legs = [leg for leg in legs if leg["lifecycle_key"] not in open_orders]
        risk = sum(maybe_float(leg.get("open_risk_usdc")) or 0.0 for leg in new_legs) if row.get("quote_permission") else 0.0
        market_preflight = preflight_by_market.get(row.get("market_id") or "", {})
        preflight_status = market_preflight.get("status") or "UNKNOWN"
        if cancel_all and row.get("quote_permission"):
            canceled = cancel_all_row(row, now, budget, reserved)
            out_rows.append(add_run_columns(
                canceled,
                run_id,
                target_date,
                mode,
                budget,
                reserved,
                0.0,
                "cancel_all",
                preflight_status,
                reason="cancel_all",
                lifecycle_keys=lifecycle_keys,
                quote_ttl_seconds=quote_ttl_seconds,
                open_order_count=len(open_orders),
                released_usdc=released_total,
            ))
            lifecycle_events.extend({
                "schema_version": SCHEMA_VERSION,
                "run_id": leg["run_id"],
                "generated_at_utc": now.isoformat(),
                "transition": "canceled",
                "reason": "global cancel-all flag present before quote post",
                **leg,
            } for leg in new_legs)
            continue
        if row.get("quote_permission") and risk > max(0.0, budget - reserved) + 1e-9:
            exhausted = budget_exhausted_row(row, now, budget, reserved, risk)
            out_rows.append(add_run_columns(
                exhausted,
                run_id,
                target_date,
                mode,
                budget,
                reserved,
                risk,
                "budget_exhausted",
                preflight_status,
                reason="budget_exhausted",
                lifecycle_keys=lifecycle_keys,
                quote_ttl_seconds=quote_ttl_seconds,
                open_order_count=len(open_orders),
                released_usdc=released_total,
            ))
            lifecycle_events.extend(lifecycle_blocked_by_budget_events(new_legs, now))
            ledger.append({
                "run_id": run_id,
                "generated_at_utc": now.isoformat(),
                "event": "budget_exhausted",
                "budget_action": "budget_exhausted",
                "market_id": row.get("market_id"),
                "event_slug": row.get("event_slug"),
                "range_label": row.get("range_label"),
                "quote_risk_usdc": round(risk, 6),
                "reserved_usdc": round(reserved, 6),
                "remaining_usdc": round(max(0.0, budget - reserved), 6),
            })
            risk_events.append({
                "run_id": run_id,
                "generated_at_utc": now.isoformat(),
                "severity": "info",
                "category": "budget",
                "market_id": row.get("market_id"),
                "reason": "budget_exhausted",
                "detail": "quote skipped because run risk budget would be exceeded",
            })
            continue
        if row.get("quote_permission"):
            if new_legs:
                for leg in new_legs:
                    events = lifecycle_post_events(leg, now, mode)
                    lifecycle_events.extend(events)
                    posted_events.extend(events)
                    open_orders[leg["lifecycle_key"]] = events[-1]
                    reserved = lifecycle_reserved_usdc(open_orders)
                    ledger.append({
                        "run_id": run_id,
                        "generated_at_utc": now.isoformat(),
                        "event": "quote_reserved",
                        "budget_action": "reserved",
                        "market_id": row.get("market_id"),
                        "event_slug": row.get("event_slug"),
                        "range_label": row.get("range_label"),
                        "lifecycle_key": leg["lifecycle_key"],
                        "quote_risk_usdc": round(maybe_float(leg.get("open_risk_usdc")) or 0.0, 6),
                        "reserved_usdc": round(reserved, 6),
                        "remaining_usdc": round(max(0.0, budget - reserved), 6),
                    })
                action = "reserved"
            else:
                action = "already_reserved"
        else:
            action = "not_reserved"
        reason = ""
        if row.get("reason_code") == "NO_QUOTE_MISSING_PREFLIGHT":
            reason = "missing_preflight"
        elif row.get("reason_code") == "NO_QUOTE_STALE_INPUT":
            reason = "stale_input"
        out_rows.append(add_run_columns(
            row,
            run_id,
            target_date,
            mode,
            budget,
            reserved,
            quote_risk_usdc(row) if row.get("quote_permission") else 0.0,
            action,
            preflight_status,
            reason=reason,
            lifecycle_keys=lifecycle_keys,
            quote_ttl_seconds=quote_ttl_seconds,
            open_order_count=len(open_orders),
            released_usdc=released_total,
        ))
    ledger.append({
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "event": "run_budget_end",
        "budget_action": "run_budget_end",
        "budget_usdc": budget,
        "reserved_usdc": round(reserved, 6),
        "remaining_usdc": round(max(0.0, budget - reserved), 6),
        "detail": "run risk budget closed for this tick",
    })
    summary = lifecycle_summary(open_orders, budget, released_events, posted_events, now)
    return out_rows, ledger, risk_events, lifecycle_events, summary


def load_live_readiness(path):
    if not path:
        return {"path": None, "ok": False, "reason": "no live-readiness file provided"}
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "ok": False, "reason": "live-readiness file missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {"path": str(path), "ok": False, "reason": f"invalid live-readiness JSON: {exc}"}
    required = [
        "account_platform_verified",
        "wallet_ready",
        "allowance_ready",
        "heartbeat_ready",
        "user_websocket_ready",
        "cancel_all_ready",
    ]
    missing = [key for key in required if not bool_value(payload.get(key), False)]
    return {
        "path": str(path),
        "ok": not missing,
        "missing": missing,
        "payload": payload,
        "reason": "ok" if not missing else f"missing live gates: {', '.join(missing)}",
    }
