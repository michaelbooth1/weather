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
    from market_config import config_for_date, ensure_date
    from market_microstructure import audit_book_tape
    from market_microstructure_features import snapshot_band_key
    from market_registry import all_specs, spec_for_id
    from mm_policy import (
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


SCHEMA_VERSION = "mm_run_v0.2"
RUN_MODES = {"shadow", "paper-live-forward", "live-pilot"}
DEFAULT_RUNS_ROOT = Path("data") / "mm_runs"
DEFAULT_QUOTE_TTL_SECONDS = 120.0
DEFAULT_DATA_LAYER_AUDIT = Path("data") / "backtest" / "data_layer_audit.json"

RUN_EXTRA_COLUMNS = [
    "run_id",
    "target_date",
    "run_mode",
    "orchestrator_schema_version",
    "orchestrator_reason_code",
    "preflight_status",
    "quote_risk_usdc",
    "run_budget_usdc",
    "budget_reserved_usdc",
    "budget_remaining_usdc",
    "budget_action",
    "exchange_validity_reserved_usdc",
    "order_lifecycle_keys",
    "quote_ttl_seconds",
    "open_order_count",
    "budget_released_usdc",
]

RUN_QUOTE_COLUMNS = RUN_EXTRA_COLUMNS + QUOTE_COLUMNS

FILL_COLUMNS = [
    "run_id",
    "generated_at_utc",
    "mode",
    "market_id",
    "event_slug",
    "snapshot_id",
    "range_label",
    "clob_token_id",
    "side",
    "intended_price",
    "intended_size",
    "fill_status",
    "fill_price",
    "fill_size",
    "simulator",
    "notes",
]


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def read_jsonl_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def append_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return str(path)


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


def latest_book_rows(folder):
    rows = [
        row
        for row in read_csv_rows(Path(folder) / "order_books_summary.csv")
        if str(row.get("outcome") or "").lower() in {"yes", ""}
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


def latest_clob_feature_rows(folder, snapshot_id):
    return latest_rows_for_snapshot(read_csv_rows(Path(folder) / "clob_features_long.csv"), snapshot_id)


def row_key_without_token(row):
    kind, value, value_hi = snapshot_band_key(row)
    return row.get("snapshot_id"), kind, value, value_hi


def assemble_policy_inputs_for_market(
    market_id,
    folder,
    snapshot_rows,
    source_rows,
    promotion,
    observation_status,
    known_edge_records=None,
    known_edge_map_loaded=False,
):
    clob_by_token, clob_by_band = load_clob_feature_index(folder)
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


def source_status_is_current(rows):
    if not rows:
        return False
    return any(
        bool_value(row.get("ok"), False)
        and str(row.get("status") or "").lower() in {"fresh", "ok", "available", ""}
        and not bool_value(row.get("stale"), False)
        for row in rows
    )


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
):
    gates = []
    blockers = []
    stale = []
    folder = Path(folder)
    latest_capture = parse_time(snapshot_rows[0].get("captured_at_utc")) if snapshot_rows else None
    model_age = (now - latest_capture).total_seconds() if latest_capture else None
    book_audit = audit_book_tape(
        folder,
        now=now,
        max_gap_seconds=float(policy_config["max_book_age_seconds"]),
    )
    token_rows = read_csv_rows(folder / "clob_tokens.csv")
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
    add_gate("snapshot_model_rows", bool(snapshot_rows), "missing", "missing current snapshot/model rows")
    add_gate(
        "model_freshness",
        model_age is not None and model_age <= float(policy_config["max_model_age_seconds"]),
        "stale",
        "current model snapshot is stale or timestamp is missing",
    )
    add_gate("source_status_rows", bool(source_rows), "missing", "missing current source-status rows")
    add_gate("source_status_fresh", source_status_is_current(source_rows), "stale", "no fresh source-status row for latest snapshot")
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

    live_gate = {
        "required": mode == "live-pilot",
        "pilot_flag": bool(pilot),
        "confirm_live_orders": bool(live_confirmed),
        "live_ready": bool(live_ready),
        "ok": mode != "live-pilot" or (pilot and live_confirmed and live_ready),
    }
    if mode == "live-pilot" and not live_gate["ok"]:
        blockers.append("live-pilot requires --pilot, --confirm-live-orders, and a passing live-readiness file")
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
        "snapshot_rows": len(snapshot_rows),
        "latest_snapshot_id": snapshot_rows[0].get("snapshot_id") if snapshot_rows else None,
        "latest_capture_utc": latest_capture.isoformat() if latest_capture else None,
        "model_age_seconds": round(model_age, 1) if model_age is not None else None,
        "source_status_rows": len(source_rows),
        "clob_token_rows": token_count,
        "condition_ids": condition_count,
        "book_rows": len(book_rows),
        "clob_feature_rows": len(clob_feature_rows),
        "book_audit": book_audit,
        "promotion_state": promotion.get("promotion_state"),
        "promotion_action": promotion.get("action"),
        "reward_metadata": reward_metadata,
        "live_gate": live_gate,
        "data_layer_live_gate": data_layer_live_gate,
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


def build_report(run_config, preflight, quote_rows, budget_ledger, lifecycle=None, remediation=None):
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    quote_rows_count = sum(1 for row in quote_rows if row.get("quote_permission"))
    live_rows = sum(1 for row in quote_rows if row.get("live_trade_permission"))
    lifecycle = lifecycle or {}
    remediation = remediation or {}
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
        f"- Quote rows: `{quote_rows_count}`",
        f"- No-quote rows: `{len(quote_rows) - quote_rows_count}`",
        f"- Live-trade permission rows: `{live_rows}`",
        f"- Budget reserved: `{reserved:.2f}` / `{budget:.2f}` USDC",
        f"- Remaining budget: `{max(0.0, budget - reserved):.2f}` USDC",
        f"- Open lifecycle orders: `{lifecycle.get('current_open_order_count', 0)}`",
        f"- Released this tick: `{float(lifecycle.get('released_this_tick_usdc') or 0.0):.2f}` USDC",
        f"- Preflight remediation incidents: `{remediation.get('incident_count', 0)}`",
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
    report = build_report(run_config, preflight_payload, quote_rows, budget_ledger, lifecycle=lifecycle, remediation=remediation_payload)
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
