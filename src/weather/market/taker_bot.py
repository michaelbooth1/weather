"""Daily paper simulator for a profit-seeking taker bot.

The market-making simulator models passive quote intent and queue uncertainty.
This module models the opposite workflow: a keyless paper trader that buys YES
as a taker when the current best ask is cheap relative to the model fair value.
It spends a daily budget immediately, records pretend fills, and rewrites a
daily P&L artifact that can be read before or after settlement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, time as dt_time, timezone
from pathlib import Path

from weather.backtesting.settlement_ledger import ledger_label_for_slug, resolve_outcome
from weather.io import append_jsonl, read_csv_rows, read_json, write_csv_rows
from weather.market.market_config import config_for_date, ensure_date
from weather.market.market_making_run_support import (
    classify_zero_trade_root_cause,
    clob_token_discovery_health,
    clob_feature_index_from_rows,
    first_failed_gate,
    latest_book_rows,
    latest_clob_feature_rows,
    source_status_for_snapshot,
    source_status_is_current,
)
from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.live_observation_normalization import (
    current_high_probability_summary,
    normalized_high_fields,
    normalized_high_for_market,
)
from weather.market.mm_policy import (
    DEFAULT_OBSERVATION_STATUS,
    bool_value,
    first_present,
    load_latest_snapshot_rows,
    load_observation_status,
    maybe_float,
    parse_time,
    source_freshness_state_from_rows,
)
from weather.paths import data_path


SCHEMA_VERSION = "taker_bot_run_v0.1"
POLICY_VERSION = "taker_bot_policy_v0.1"
DEFAULT_RUNS_ROOT = data_path() / "taker_runs"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"

DEFAULT_CONFIG = {
    "policy_version": POLICY_VERSION,
    "min_edge": 0.03,
    "max_order_usdc": 10.0,
    "max_position_per_token_usdc": 10.0,
    "max_daily_positions": 50,
    "taker_fee_rate": 0.0,
    "min_price": 0.001,
    "max_price": 0.999,
    "max_book_age_seconds": 120.0,
    "max_model_age_seconds": 900.0,
    "require_active_market": True,
    "require_source_fresh": True,
    "early_hour_guardrail_enabled": True,
    "early_hour_start": 0,
    "early_hour_end": 8,
    "early_hour_min_edge": 0.10,
    "early_hour_min_edge_multiplier": 2.0,
    "early_hour_max_order_usdc": 2.0,
    "early_hour_max_position_per_token_usdc": 2.0,
    "early_hour_max_daily_positions": 12,
    "early_hour_require_source_states": "all_fresh",
    "early_hour_block_guarded_current_high": True,
}

ORDER_COLUMNS = [
    "schema_version",
    "policy_version",
    "policy_hash",
    "run_id",
    "target_date",
    "generated_at_utc",
    "intent_key",
    "order_id",
    "market_id",
    "event_slug",
    "snapshot_id",
    "captured_at_utc",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "condition_id",
    "clob_token_id",
    "side",
    "action",
    "order_status",
    "reason_code",
    "reason_detail",
    "fair_probability",
    "best_bid",
    "best_ask",
    "market_mid",
    "edge",
    "expected_profit_per_share",
    "ask_size_at_best",
    "min_order_size",
    "requested_notional_usdc",
    "fill_price",
    "fill_size",
    "fill_notional_usdc",
    "fee_usdc",
    "total_spent_usdc",
    "budget_usdc",
    "budget_spent_before_usdc",
    "budget_spent_after_usdc",
    "budget_remaining_usdc",
    "position_notional_before_usdc",
    "position_notional_after_usdc",
    "book_age_seconds",
    "model_age_seconds",
    "raw_current_high",
    "raw_current_high_bucket",
    "settlement_current_high",
    "high_source",
    "revision_state",
    "settlement_bin_key",
    "raw_current_high_bin_key",
    "probability_on_raw_current_high",
    "probability_on_settlement_current_high",
    "current_max_state",
    "current_max_disposition",
    "current_max_gap_to_wu_history",
    "current_max_gap_to_current_temp",
    "current_high_trusted",
    "current_high_guard_reason",
    "source_fresh",
    "source_freshness_state",
    "capture_hour_local",
    "capture_timezone",
    "early_hour_guardrail_status",
    "early_hour_guardrail_reason",
    "early_hour_guardrail_min_edge",
    "early_hour_guardrail_max_order_usdc",
    "early_hour_guardrail_max_position_per_token_usdc",
    "early_hour_guardrail_max_daily_positions",
    "settlement_status",
    "settlement_outcome",
    "settlement_payout_usdc",
    "settlement_pnl_usdc",
    "mark_price",
    "mark_pnl_usdc",
    "pnl_source",
    "net_pnl_usdc",
]


def utc_now(value=None):
    parsed = parse_time(value)
    return parsed or datetime.now(timezone.utc)


def compact_float(value, digits=6):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def clamp_probability(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def policy_hash(config):
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def default_run_id(target_date, config=None):
    target = ensure_date(target_date)
    digest = policy_hash({**DEFAULT_CONFIG, **(config or {})})[:8]
    return f"taker-{target.strftime('%Y%m%d')}-{digest}"


def run_folder_for(runs_root, target_date, run_id):
    return Path(runs_root) / ensure_date(target_date).isoformat() / run_id


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


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


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


def read_order_rows(path):
    return read_csv_rows(path, attach_diagnostics=True)


def order_key(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def latest_book_index(rows):
    by_token = {}
    by_band = {}
    for row in rows or []:
        kind, value, value_hi = snapshot_band_key(row)
        snapshot_id = row.get("snapshot_id") or ""
        token = row.get("clob_token_id") or row.get("clob_yes_token_id") or ""
        band_key = (snapshot_id, kind, value, value_hi)
        by_band[band_key] = row
        if token:
            by_token[(snapshot_id, kind, value, value_hi, str(token))] = row
    return by_token, by_band


def _book_for_snapshot(snapshot_row, by_token, by_band):
    kind, value, value_hi = snapshot_band_key(snapshot_row)
    token = snapshot_row.get("clob_token_id") or snapshot_row.get("clob_yes_token_id") or ""
    snapshot_id = snapshot_row.get("snapshot_id") or ""
    return (
        by_token.get((snapshot_id, kind, value, value_hi, str(token)))
        or by_token.get(("", kind, value, value_hi, str(token)))
        or by_band.get((snapshot_id, kind, value, value_hi))
        or by_band.get(("", kind, value, value_hi))
        or {}
    )


def age_seconds(timestamp, now):
    parsed = parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def market_mid(row):
    mid = clamp_probability(first_present(row, "market_mid", "clob_midpoint", "midpoint"))
    if mid is not None:
        return mid
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2.0
    return clamp_probability(row.get("market_yes"))


def model_age_seconds(row, now):
    value = maybe_float(row.get("model_age_seconds"))
    if value is not None:
        return max(0.0, value)
    return age_seconds(row.get("captured_at_utc"), now)


def book_age_seconds(row, now):
    value = maybe_float(first_present(row, "book_age_seconds", "clob_book_age_seconds"))
    if value is not None:
        return max(0.0, value)
    return age_seconds(first_present(row, "clob_book_captured_at_utc", "book_time_utc", "captured_at_utc"), now)


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


def csv_tokens(value):
    return {
        item.strip().lower()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    }


def market_local_time(row):
    timestamp = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    if timestamp is None:
        return None, ""
    try:
        spec = spec_for_id(row.get("market_id") or "")
        zone = spec.tz
    except Exception:  # noqa: BLE001 - an unknown market should not crash policy diagnostics
        zone = timezone.utc
    local = timestamp.astimezone(zone)
    return local, getattr(zone, "key", str(zone))


def hour_in_window(hour, start, end):
    if hour is None:
        return False
    hour = int(hour)
    start = int(start)
    end = int(end)
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def early_hour_guardrail_state(row, config):
    local, zone_name = market_local_time(row)
    hour = local.hour if local else None
    enabled = bool(config.get("early_hour_guardrail_enabled", True))
    in_window = enabled and hour_in_window(hour, config.get("early_hour_start", 0), config.get("early_hour_end", 8))
    min_edge = max(
        float(config["min_edge"]) * float(config.get("early_hour_min_edge_multiplier", 1.0)),
        float(config.get("early_hour_min_edge", config["min_edge"])),
    )
    max_order = min(float(config["max_order_usdc"]), float(config.get("early_hour_max_order_usdc", config["max_order_usdc"])))
    max_position = min(
        float(config["max_position_per_token_usdc"]),
        float(config.get("early_hour_max_position_per_token_usdc", config["max_position_per_token_usdc"])),
    )
    max_positions = min(
        int(config["max_daily_positions"]),
        int(float(config.get("early_hour_max_daily_positions", config["max_daily_positions"]))),
    )
    state = {
        "capture_hour_local": hour,
        "capture_timezone": zone_name,
        "early_hour_guardrail_status": "inactive",
        "early_hour_guardrail_reason": "",
        "early_hour_guardrail_min_edge": round(min_edge, 6),
        "early_hour_guardrail_max_order_usdc": round(max_order, 6),
        "early_hour_guardrail_max_position_per_token_usdc": round(max_position, 6),
        "early_hour_guardrail_max_daily_positions": max_positions,
    }
    if not in_window:
        return state

    state["early_hour_guardrail_status"] = "active"
    edge = maybe_float(row.get("edge"))
    allowed_states = csv_tokens(config.get("early_hour_require_source_states"))
    source_state = str(row.get("source_freshness_state") or "").strip().lower()
    disposition = str(row.get("current_max_disposition") or "").strip().lower()
    current_state = str(row.get("current_max_state") or "").strip()
    if (
        config.get("early_hour_block_guarded_current_high", True)
        and disposition in {"null_before_reset", "support_only"}
    ):
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": f"guarded_current_high:{current_state or disposition}",
        })
    elif allowed_states and source_state not in allowed_states:
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": f"source_state:{source_state or 'missing'}",
        })
    elif edge is not None and edge < min_edge:
        state.update({
            "early_hour_guardrail_status": "blocked",
            "early_hour_guardrail_reason": "edge_below_early_hour_minimum",
        })
    return state


def early_hour_effective_caps(row, config):
    if row.get("early_hour_guardrail_status") == "active":
        return {
            "max_order_usdc": maybe_float(row.get("early_hour_guardrail_max_order_usdc")) or float(config["max_order_usdc"]),
            "max_position_per_token_usdc": (
                maybe_float(row.get("early_hour_guardrail_max_position_per_token_usdc"))
                or float(config["max_position_per_token_usdc"])
            ),
            "max_daily_positions": int(float(row.get("early_hour_guardrail_max_daily_positions") or config["max_daily_positions"])),
        }
    return {
        "max_order_usdc": float(config["max_order_usdc"]),
        "max_position_per_token_usdc": float(config["max_position_per_token_usdc"]),
        "max_daily_positions": int(config["max_daily_positions"]),
    }


def assemble_taker_inputs_for_market(
    market_id,
    folder,
    snapshot_rows,
    source_rows,
    clob_feature_rows,
    book_rows,
    current_high_assessment=None,
):
    clob_by_token, clob_by_band = clob_feature_index_from_rows(clob_feature_rows)
    book_by_token, book_by_band = latest_book_index(book_rows)
    source_fresh = source_status_is_current(source_rows)
    source_state = source_freshness_state_from_rows(source_rows)
    rows = []
    for snapshot_row in snapshot_rows:
        kind, value, value_hi = snapshot_band_key(snapshot_row)
        token = snapshot_row.get("clob_token_id") or snapshot_row.get("clob_yes_token_id") or ""
        snapshot_id = snapshot_row.get("snapshot_id")
        band_key = (snapshot_id, kind, value, value_hi)
        token_key = (snapshot_id, kind, value, value_hi, str(token))
        clob_row = clob_by_token.get(token_key) or clob_by_band.get(band_key) or {}
        book_row = _book_for_snapshot({**snapshot_row, **clob_row}, book_by_token, book_by_band)
        merged = dict(snapshot_row)
        merged.update({key: value for key, value in clob_row.items() if value not in (None, "")})
        merged.update({key: value for key, value in book_row.items() if value not in (None, "")})
        merged["market_id"] = market_id
        merged["folder"] = str(folder)
        merged["fair_probability"] = first_present(merged, "fair_probability", "model_probability", "candidate_p")
        merged["market_mid"] = market_mid(merged)
        merged["source_fresh"] = source_fresh
        merged["source_freshness_state"] = source_state
        merged.update(normalized_high_fields(current_high_assessment))
        if not merged.get("clob_token_id"):
            merged["clob_token_id"] = token
        if "bin_value" not in merged and merged.get("bin_value_c") not in (None, ""):
            merged["bin_value"] = merged.get("bin_value_c")
        rows.append(merged)
    return rows


def preflight_summary_for_market(
    spec,
    target_date,
    folder,
    snapshot_rows,
    source_rows,
    book_rows,
    clob_feature_rows,
    current_high_assessment=None,
):
    latest_capture = parse_time(snapshot_rows[0].get("captured_at_utc")) if snapshot_rows else None
    token_rows = read_csv_rows(Path(folder) / "clob_tokens.csv", attach_diagnostics=True)
    token_discovery = clob_token_discovery_health(token_rows)
    status = "PASS"
    reasons = []
    gates = []

    def add_gate(name, ok, severity, detail):
        gates.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})
        return bool(ok)

    if not snapshot_rows:
        status = "BLOCK"
        reasons.append("missing current snapshot/model rows")
    add_gate("snapshot_model_rows", bool(snapshot_rows), "missing", "missing current snapshot/model rows")
    if not token_discovery.get("ok"):
        status = "BLOCK"
        reasons.append(token_discovery.get("reason"))
    add_gate("clob_discovery", token_discovery.get("ok"), "missing", token_discovery.get("reason"))
    if not book_rows:
        status = "BLOCK"
        reasons.append("missing current CLOB book rows")
    add_gate("clob_books", bool(book_rows), "missing", "missing current CLOB book rows")
    if not clob_feature_rows:
        status = "BLOCK"
        reasons.append("missing band-level CLOB feature rows")
    add_gate("clob_features", bool(clob_feature_rows), "missing", "missing band-level CLOB feature rows")
    if source_rows and not source_status_is_current(source_rows):
        status = "STALE" if status == "PASS" else status
        reasons.append("no fresh source-status row for latest snapshot")
        add_gate("source_status_fresh", False, "stale", "no fresh source-status row for latest snapshot")
    elif not source_rows:
        status = "STALE" if status == "PASS" else status
        reasons.append("missing current source-status rows")
        add_gate("source_status_rows", False, "stale", "missing current source-status rows")
    else:
        add_gate("source_status_fresh", True, "stale", "source status fresh")
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": ensure_date(target_date).isoformat(),
        "event_slug": config_for_date(target_date, spec.id).event_slug,
        "folder": str(folder),
        "status": status,
        "reasons": reasons or ["ok"],
        "gates": gates,
        "first_failing_gate": first_failed_gate({"gates": gates}),
        "snapshot_rows": len(snapshot_rows),
        "latest_snapshot_id": snapshot_rows[0].get("snapshot_id") if snapshot_rows else None,
        "latest_capture_utc": latest_capture.isoformat() if latest_capture else None,
        "source_status_rows": len(source_rows),
        "source_status_fresh": source_status_is_current(source_rows),
        "clob_token_discovery": token_discovery,
        "book_rows": len(book_rows),
        "clob_feature_rows": len(clob_feature_rows),
        "current_high_assessment": current_high_assessment or {},
    }


def base_order_row(input_row, run_id, target_date, now, config, config_hash):
    kind, value, value_hi = snapshot_band_key(input_row)
    token = input_row.get("clob_token_id") or input_row.get("clob_yes_token_id") or ""
    fair = clamp_probability(input_row.get("fair_probability"))
    best_bid = clamp_probability(first_present(input_row, "clob_best_bid", "best_bid", "gamma_best_bid"))
    best_ask = clamp_probability(first_present(input_row, "clob_best_ask", "best_ask", "gamma_best_ask"))
    mid = market_mid(input_row)
    edge = fair - best_ask if fair is not None and best_ask is not None else None
    ask_size = maybe_float(first_present(input_row, "ask_size_at_best", "clob_ask_size_at_best", "ask_depth_1pct"))
    if ask_size is None:
        ask_size = 0.0
    generated = now.isoformat()
    intent_payload = {
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "market_id": input_row.get("market_id") or "",
        "event_slug": input_row.get("event_slug") or "",
        "snapshot_id": input_row.get("snapshot_id") or "",
        "captured_at_utc": input_row.get("captured_at_utc") or "",
        "clob_token_id": token,
        "range_label": input_row.get("range_label") or "",
        "fair_probability": compact_float(fair),
        "best_ask": compact_float(best_ask),
    }
    intent = order_key(intent_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": config_hash,
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "generated_at_utc": generated,
        "intent_key": intent,
        "order_id": f"taker_{intent}",
        "market_id": input_row.get("market_id") or "",
        "event_slug": input_row.get("event_slug") or "",
        "snapshot_id": input_row.get("snapshot_id") or "",
        "captured_at_utc": input_row.get("captured_at_utc") or "",
        "range_label": input_row.get("range_label") or "",
        "bin_kind": input_row.get("bin_kind") or kind or "",
        "bin_value": input_row.get("bin_value") or input_row.get("bin_value_c") or value or "",
        "bin_value_hi": input_row.get("bin_value_hi") or value_hi or "",
        "condition_id": input_row.get("condition_id") or "",
        "clob_token_id": token,
        "side": "YES_BUY",
        "action": "NO_TRADE",
        "order_status": "SKIPPED",
        "reason_code": "",
        "reason_detail": "",
        "fair_probability": compact_float(fair),
        "best_bid": compact_float(best_bid),
        "best_ask": compact_float(best_ask),
        "market_mid": compact_float(mid),
        "edge": compact_float(edge),
        "expected_profit_per_share": compact_float(edge),
        "ask_size_at_best": compact_float(ask_size),
        "min_order_size": compact_float(first_present(input_row, "min_order_size", "minimum_order_size")),
        "requested_notional_usdc": 0.0,
        "fill_price": None,
        "fill_size": 0.0,
        "fill_notional_usdc": 0.0,
        "fee_usdc": 0.0,
        "total_spent_usdc": 0.0,
        "book_age_seconds": compact_float(book_age_seconds(input_row, now)),
        "model_age_seconds": compact_float(model_age_seconds(input_row, now)),
        "raw_current_high": compact_float(input_row.get("raw_current_high")),
        "raw_current_high_bucket": compact_float(input_row.get("raw_current_high_bucket")),
        "settlement_current_high": compact_float(input_row.get("settlement_current_high")),
        "high_source": input_row.get("high_source") or "",
        "revision_state": input_row.get("revision_state") or "",
        "settlement_bin_key": input_row.get("settlement_bin_key") or "",
        "raw_current_high_bin_key": input_row.get("raw_current_high_bin_key") or "",
        "probability_on_raw_current_high": compact_float(input_row.get("probability_on_raw_current_high")),
        "probability_on_settlement_current_high": compact_float(
            input_row.get("probability_on_settlement_current_high")
        ),
        "current_max_state": input_row.get("current_max_state") or "",
        "current_max_disposition": input_row.get("current_max_disposition") or "",
        "current_max_gap_to_wu_history": compact_float(input_row.get("current_max_gap_to_wu_history")),
        "current_max_gap_to_current_temp": compact_float(input_row.get("current_max_gap_to_current_temp")),
        "current_high_trusted": bool_value(input_row.get("current_high_trusted"), True),
        "current_high_guard_reason": input_row.get("current_high_guard_reason") or "",
        "source_fresh": bool_value(input_row.get("source_fresh"), False),
        "source_freshness_state": input_row.get("source_freshness_state") or "",
        "capture_hour_local": None,
        "capture_timezone": "",
        "early_hour_guardrail_status": "inactive",
        "early_hour_guardrail_reason": "",
        "early_hour_guardrail_min_edge": None,
        "early_hour_guardrail_max_order_usdc": None,
        "early_hour_guardrail_max_position_per_token_usdc": None,
        "early_hour_guardrail_max_daily_positions": None,
    }


def candidate_skip_reason(row, config):
    fair = maybe_float(row.get("fair_probability"))
    best_ask = maybe_float(row.get("best_ask"))
    ask_size = maybe_float(row.get("ask_size_at_best")) or 0.0
    edge = maybe_float(row.get("edge"))
    book_age = maybe_float(row.get("book_age_seconds"))
    model_age = maybe_float(row.get("model_age_seconds"))
    min_price = float(config["min_price"])
    max_price = float(config["max_price"])
    if config.get("require_active_market") and not boolish_active(first_present(row, "market_status", "active")):
        return "NO_TRADE_MARKET_INACTIVE", "market is not active"
    if config.get("require_source_fresh") and not bool_value(row.get("source_fresh"), False):
        return "NO_TRADE_SOURCE_STALE", "source freshness gate is false"
    if fair is None:
        return "NO_TRADE_MISSING_FAIR", "missing fair probability"
    if not row.get("clob_token_id"):
        return "NO_TRADE_MISSING_TOKEN", "missing CLOB token id"
    if best_ask is None:
        return "NO_TRADE_MISSING_ASK", "missing best ask"
    if best_ask < min_price or best_ask > max_price:
        return "NO_TRADE_PRICE_OUT_OF_RANGE", "best ask is outside allowed price bounds"
    if ask_size <= 0:
        return "NO_TRADE_NO_ASK_SIZE", "missing or zero ask size at best"
    if book_age is None or book_age > float(config["max_book_age_seconds"]):
        return "NO_TRADE_STALE_BOOK", "book age exceeds latency budget"
    if model_age is None or model_age > float(config["max_model_age_seconds"]):
        return "NO_TRADE_STALE_MODEL", "model age exceeds latency budget"
    if row.get("early_hour_guardrail_status") == "blocked":
        reason = str(row.get("early_hour_guardrail_reason") or "")
        if reason.startswith("guarded_current_high"):
            return (
                "NO_TRADE_EARLY_HOUR_CURRENT_HIGH_GUARDED",
                "early-hour current high is not validated as same-day evidence",
            )
        if reason.startswith("source_state"):
            return "NO_TRADE_EARLY_HOUR_SOURCE_STATE", "early-hour source agreement is too weak"
        return "NO_TRADE_EARLY_HOUR_EDGE_TOO_SMALL", "edge does not clear early-hour minimum"
    if edge is None or edge < float(config["min_edge"]):
        return "NO_TRADE_EDGE_TOO_SMALL", "best ask is not cheap enough versus fair value"
    return None, None


def existing_budget_spent(rows):
    total = 0.0
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        total += maybe_float(row.get("total_spent_usdc")) or 0.0
    return round(total, 6)


def existing_position_notional_by_token(rows):
    totals = defaultdict(float)
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        token = row.get("clob_token_id") or ""
        if not token:
            continue
        totals[token] += maybe_float(row.get("fill_notional_usdc")) or 0.0
    return totals


def apply_taker_budget(input_rows, existing_rows, budget_usdc, run_id, target_date, now, config):
    budget = float(budget_usdc)
    config_hash = policy_hash(config)
    existing_keys = {row.get("intent_key") for row in existing_rows or [] if row.get("intent_key")}
    seen_keys = set(existing_keys)
    rows = []
    candidates = []
    for input_row in input_rows:
        row = base_order_row(input_row, run_id, target_date, now, config, config_hash)
        if row["intent_key"] in seen_keys:
            continue
        seen_keys.add(row["intent_key"])
        row.update(early_hour_guardrail_state({**input_row, **row}, config))
        reason, detail = candidate_skip_reason({**input_row, **row}, config)
        if reason:
            row.update({"reason_code": reason, "reason_detail": detail})
            rows.append(row)
        else:
            candidates.append(row)

    candidates.sort(
        key=lambda row: (
            -(maybe_float(row.get("edge")) or 0.0),
            row.get("market_id") or "",
            row.get("range_label") or "",
        )
    )
    spent = existing_budget_spent(existing_rows)
    positions = existing_position_notional_by_token(existing_rows)
    filled_count = sum(1 for row in existing_rows or [] if str(row.get("order_status") or "").upper() == "FILLED")
    ledger = [{
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "event": "daily_budget_start",
        "budget_usdc": budget,
        "spent_usdc": spent,
        "remaining_usdc": round(max(0.0, budget - spent), 6),
    }]
    for row in candidates:
        caps = early_hour_effective_caps(row, config)
        token = row.get("clob_token_id") or ""
        price = maybe_float(row.get("best_ask")) or 0.0
        ask_size = maybe_float(row.get("ask_size_at_best")) or 0.0
        remaining_budget = max(0.0, budget - spent)
        position_before = positions[token]
        position_remaining = max(0.0, float(caps["max_position_per_token_usdc"]) - position_before)
        row["budget_usdc"] = round(budget, 6)
        row["budget_spent_before_usdc"] = round(spent, 6)
        row["position_notional_before_usdc"] = round(position_before, 6)

        if filled_count >= int(caps["max_daily_positions"]):
            row.update({
                "reason_code": (
                    "NO_TRADE_EARLY_HOUR_DAILY_POSITION_LIMIT"
                    if row.get("early_hour_guardrail_status") == "active"
                    else "NO_TRADE_DAILY_POSITION_LIMIT"
                ),
                "reason_detail": "max early-hour filled positions reached"
                if row.get("early_hour_guardrail_status") == "active"
                else "max daily filled positions reached",
            })
            rows.append(row)
            continue
        if position_remaining <= 1e-9:
            row.update({
                "reason_code": (
                    "NO_TRADE_EARLY_HOUR_POSITION_CAP"
                    if row.get("early_hour_guardrail_status") == "active"
                    else "NO_TRADE_POSITION_CAP"
                ),
                "reason_detail": "per-token early-hour position cap reached"
                if row.get("early_hour_guardrail_status") == "active"
                else "per-token daily position cap reached",
            })
            rows.append(row)
            continue
        fee_rate = max(0.0, float(config["taker_fee_rate"]))
        max_order_notional = min(float(caps["max_order_usdc"]), position_remaining)
        max_size_by_order = max_order_notional / price if price > 0 else 0.0
        max_size_by_budget = remaining_budget / (price * (1.0 + fee_rate)) if price > 0 else 0.0
        fill_size = min(ask_size, max_size_by_order, max_size_by_budget)
        min_order_size = maybe_float(first_present(row, "min_order_size", "minimum_order_size")) or 0.0
        if fill_size <= 1e-9 or (min_order_size > 0 and fill_size < min_order_size):
            row.update({
                "reason_code": "NO_TRADE_BUDGET_EXHAUSTED",
                "reason_detail": "remaining daily budget cannot fund the minimum taker buy",
                "budget_remaining_usdc": round(remaining_budget, 6),
                "position_notional_after_usdc": round(position_before, 6),
            })
            rows.append(row)
            ledger.append({
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "generated_at_utc": now.isoformat(),
                "event": "budget_exhausted",
                "market_id": row.get("market_id"),
                "event_slug": row.get("event_slug"),
                "clob_token_id": token,
                "remaining_usdc": round(remaining_budget, 6),
            })
            continue
        notional = price * fill_size
        fee = notional * fee_rate
        total = notional + fee
        spent_after = spent + total
        position_after = position_before + notional
        row.update({
            "action": "BUY",
            "order_status": "FILLED",
            "reason_code": "BUY_EDGE",
            "reason_detail": "best ask is cheap versus fair value",
            "requested_notional_usdc": round(max_order_notional, 6),
            "fill_price": round(price, 6),
            "fill_size": round(fill_size, 6),
            "fill_notional_usdc": round(notional, 6),
            "fee_usdc": round(fee, 6),
            "total_spent_usdc": round(total, 6),
            "budget_spent_after_usdc": round(spent_after, 6),
            "budget_remaining_usdc": round(max(0.0, budget - spent_after), 6),
            "position_notional_after_usdc": round(position_after, 6),
        })
        rows.append(row)
        spent = spent_after
        positions[token] = position_after
        filled_count += 1
        ledger.append({
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at_utc": now.isoformat(),
            "event": "taker_buy_filled",
            "market_id": row.get("market_id"),
            "event_slug": row.get("event_slug"),
            "range_label": row.get("range_label"),
            "clob_token_id": token,
            "fill_price": round(price, 6),
            "fill_size": round(fill_size, 6),
            "spent_usdc": round(spent_after, 6),
            "remaining_usdc": round(max(0.0, budget - spent_after), 6),
        })

    for row in rows:
        row.setdefault("budget_usdc", round(budget, 6))
        row.setdefault("budget_spent_before_usdc", round(spent, 6))
        row.setdefault("budget_spent_after_usdc", round(spent, 6))
        row.setdefault("budget_remaining_usdc", round(max(0.0, budget - spent), 6))
        row.setdefault("position_notional_before_usdc", 0.0)
        row.setdefault("position_notional_after_usdc", row.get("position_notional_before_usdc", 0.0))
    ledger.append({
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "event": "daily_budget_end",
        "budget_usdc": budget,
        "spent_usdc": round(spent, 6),
        "remaining_usdc": round(max(0.0, budget - spent), 6),
    })
    return rows, ledger


def label_numbers(row):
    import re

    return [int(value) for value in re.findall(r"-?\d+", str(row.get("range_label") or ""))]


def band_key(row):
    kind = str(row.get("bin_kind") or row.get("winning_band_kind") or "").strip().lower()
    value = row.get("bin_value")
    if value in (None, ""):
        value = row.get("bin_value_c") or row.get("winning_band_value")
    value_hi = row.get("bin_value_hi") or row.get("winning_band_value_hi")
    value = int(float(value)) if maybe_float(value) is not None else None
    value_hi = int(float(value_hi)) if maybe_float(value_hi) is not None else None
    nums = label_numbers(row)
    if value is None and nums:
        value = nums[0]
    if value_hi is None and nums:
        value_hi = nums[-1]
    if value_hi is None:
        value_hi = value
    if not kind:
        text = str(row.get("range_label") or "").lower()
        if "above" in text or "higher" in text:
            kind = "gte"
        elif "below" in text or "under" in text:
            kind = "lte"
        else:
            kind = "eq"
    return kind, value, value_hi


def settlement_for_folder(folder, event_slug, ledger_root=None):
    local = read_json(Path(folder) / "settlement.json", None)
    if local:
        return local
    try:
        return ledger_label_for_slug(event_slug, ledger_root=ledger_root)
    except TypeError:
        return ledger_label_for_slug(event_slug)


def settlement_outcome_for_order(row, settlement):
    if not settlement:
        return None
    bucket = maybe_float(settlement.get("settlement_bucket"))
    kind, value, value_hi = band_key(row)
    if bucket is None or value is None:
        return None
    try:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi=value_hi) else 0.0
    except TypeError:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi) else 0.0


def load_mark_rows(folder):
    folder = Path(folder)
    rows = []
    for row in read_csv_rows(folder / "price_history.csv", attach_diagnostics=True):
        token = row.get("clob_token_id") or row.get("asset_id") or row.get("token_id")
        ts = parse_time(row.get("point_time_utc") or row.get("captured_at_utc") or row.get("timestamp_utc"))
        price = clamp_probability(row.get("price") or row.get("midpoint") or row.get("last_trade_price"))
        if token and ts is not None and price is not None:
            rows.append({"time": ts, "clob_token_id": str(token), "price": price, "source": "price_history"})
    for row in read_csv_rows(folder / "order_books_summary.csv", attach_diagnostics=True):
        token = row.get("clob_token_id") or row.get("asset_id") or row.get("token_id")
        ts = parse_time(row.get("captured_at_utc") or row.get("book_time_utc"))
        price = clamp_probability(row.get("midpoint") or row.get("last_trade_price") or row.get("gamma_last_trade_price"))
        if token and ts is not None and price is not None:
            rows.append({"time": ts, "clob_token_id": str(token), "price": price, "source": "order_books_summary"})
    rows.sort(key=lambda item: (item["time"], item["source"]))
    return rows


def latest_mark(mark_rows, token, now):
    token_rows = [row for row in mark_rows if row.get("clob_token_id") == str(token)]
    if not token_rows:
        return None
    before = [row for row in token_rows if row["time"] <= now]
    return before[-1] if before else token_rows[-1]


def score_orders(order_rows, snapshots_root=DEFAULT_SNAPSHOTS_ROOT, ledger_root=None, now=None):
    now = utc_now(now)
    cache = {}
    scored = []
    for row in order_rows or []:
        out = dict(row)
        if str(row.get("order_status") or "").upper() != "FILLED":
            scored.append(out)
            continue
        event_slug = row.get("event_slug") or ""
        if event_slug not in cache:
            folder = Path(snapshots_root) / event_slug
            cache[event_slug] = {
                "folder": folder,
                "settlement": settlement_for_folder(folder, event_slug, ledger_root=ledger_root),
                "marks": load_mark_rows(folder),
            }
        item = cache[event_slug]
        fill_size = maybe_float(row.get("fill_size")) or 0.0
        fill_notional = maybe_float(row.get("fill_notional_usdc")) or 0.0
        fee = maybe_float(row.get("fee_usdc")) or 0.0
        cost = fill_notional + fee
        outcome = settlement_outcome_for_order(row, item["settlement"])
        mark = latest_mark(item["marks"], row.get("clob_token_id"), now)
        out["settlement_outcome"] = compact_float(outcome)
        out["mark_price"] = compact_float(mark.get("price") if mark else None)
        if outcome is not None:
            payout = outcome * fill_size
            pnl = payout - cost
            out.update({
                "settlement_status": "settled",
                "settlement_payout_usdc": compact_float(payout),
                "settlement_pnl_usdc": compact_float(pnl),
                "mark_pnl_usdc": None,
                "pnl_source": "settlement",
                "net_pnl_usdc": compact_float(pnl),
            })
        elif mark:
            mark_pnl = (float(mark["price"]) * fill_size) - cost
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": compact_float(mark_pnl),
                "pnl_source": "mark_to_market",
                "net_pnl_usdc": compact_float(mark_pnl),
            })
        else:
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": None,
                "pnl_source": "unscored",
                "net_pnl_usdc": None,
            })
        scored.append(out)
    return scored


def sum_field(rows, key):
    return round(sum(maybe_float(row.get(key)) or 0.0 for row in rows), 6)


def build_pnl_payload(order_rows, budget_usdc, run_id, target_date, now=None):
    now = utc_now(now)
    filled = [row for row in order_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    settled = [row for row in filled if row.get("pnl_source") == "settlement"]
    marked = [row for row in filled if row.get("pnl_source") == "mark_to_market"]
    unscored = [row for row in filled if row.get("pnl_source") == "unscored"]
    reason_counts = Counter(row.get("reason_code") or "unknown" for row in order_rows)
    by_market = defaultdict(lambda: {
        "filled_order_count": 0,
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
    })
    positions = defaultdict(lambda: {
        "market_id": "",
        "event_slug": "",
        "range_label": "",
        "clob_token_id": "",
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
        "pnl_source": "",
    })
    for row in filled:
        market_id = row.get("market_id") or "unknown"
        by_market[market_id]["filled_order_count"] += 1
        by_market[market_id]["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        by_market[market_id]["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        by_market[market_id]["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        token = row.get("clob_token_id") or row.get("order_id") or ""
        pos = positions[token]
        pos.update({
            "market_id": market_id,
            "event_slug": row.get("event_slug") or "",
            "range_label": row.get("range_label") or "",
            "clob_token_id": token,
            "pnl_source": row.get("pnl_source") or "",
        })
        pos["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        pos["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        pos["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
    spent = sum_field(filled, "total_spent_usdc")
    summary = {
        "budget_usdc": round(float(budget_usdc), 6),
        "budget_spent_usdc": spent,
        "budget_remaining_usdc": round(max(0.0, float(budget_usdc) - spent), 6),
        "order_rows": len(order_rows),
        "filled_order_count": len(filled),
        "filled_shares": sum_field(filled, "fill_size"),
        "settled_order_count": len(settled),
        "unsettled_order_count": len(marked) + len(unscored),
        "unscored_order_count": len(unscored),
        "gross_cost_usdc": sum_field(filled, "fill_notional_usdc"),
        "fees_usdc": sum_field(filled, "fee_usdc"),
        "settlement_payout_usdc": sum_field(settled, "settlement_payout_usdc"),
        "settlement_pnl_usdc": sum_field(settled, "settlement_pnl_usdc"),
        "mark_to_market_pnl_usdc": sum_field(marked, "mark_pnl_usdc"),
        "net_pnl_usdc": sum_field([row for row in filled if row.get("net_pnl_usdc") not in (None, "")], "net_pnl_usdc"),
        "win_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 1.0),
        "loss_count": sum(1 for row in settled if maybe_float(row.get("settlement_outcome")) == 0.0),
        "reason_counts": dict(sorted(reason_counts.items())),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "summary": summary,
        "by_market": [
            {
                "market_id": key,
                "filled_order_count": value["filled_order_count"],
                "filled_shares": round(value["filled_shares"], 6),
                "spent_usdc": round(value["spent_usdc"], 6),
                "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            }
            for key, value in sorted(by_market.items())
        ],
        "positions": [
            {
                **value,
                "filled_shares": round(value["filled_shares"], 6),
                "spent_usdc": round(value["spent_usdc"], 6),
                "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            }
            for _key, value in sorted(positions.items())
        ],
    }


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def fmt_num(value, digits=4):
    number = maybe_float(value)
    return "-" if number is None else f"{number:.{digits}f}"


def render_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    pnl_summary = pnl.get("summary") or {}
    tape_integrity = payload.get("tape_integrity") or summary.get("tape_integrity") or {}
    lines = [
        "# Taker Bot Paper Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Budget USDC", fmt_num(summary.get("budget_usdc"), 2)],
            ["Budget spent USDC", fmt_num(summary.get("budget_spent_usdc"), 2)],
            ["Budget remaining USDC", fmt_num(summary.get("budget_remaining_usdc"), 2)],
            ["Latest tick rows", summary.get("latest_tick_rows")],
            ["New filled buys", summary.get("latest_tick_filled_orders")],
            ["Cumulative filled buys", pnl_summary.get("filled_order_count")],
            ["Zero-trade root cause", summary.get("root_cause_class")],
            ["First failing gate", summary.get("first_failing_gate") or "-"],
            ["Zero trades expected", str(summary.get("zero_trades_expected")).lower()],
            [
                "Tape integrity",
                (
                    f"{tape_integrity.get('status') or '-'} "
                    f"({tape_integrity.get('actual_rows', 0)}/{tape_integrity.get('expected_rows', 0)} rows)"
                ),
            ],
            ["Settled / unsettled", f"{pnl_summary.get('settled_order_count')} / {pnl_summary.get('unsettled_order_count')}"],
            ["Net P&L USDC", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## P&L", ""])
    lines.extend(markdown_table(
        ["Component", "USDC"],
        [
            ["Gross cost", fmt_num(pnl_summary.get("gross_cost_usdc"), 4)],
            ["Fees", fmt_num(pnl_summary.get("fees_usdc"), 4)],
            ["Settlement payout", fmt_num(pnl_summary.get("settlement_payout_usdc"), 4)],
            ["Settlement P&L", fmt_num(pnl_summary.get("settlement_pnl_usdc"), 4)],
            ["Mark-to-market P&L", fmt_num(pnl_summary.get("mark_to_market_pnl_usdc"), 4)],
            ["Net P&L", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## Markets", ""])
    lines.extend(markdown_table(
        ["Market", "Filled", "Shares", "Spent", "Net P&L"],
        [
            [
                row.get("market_id"),
                row.get("filled_order_count"),
                fmt_num(row.get("filled_shares"), 3),
                fmt_num(row.get("spent_usdc"), 2),
                fmt_num(row.get("net_pnl_usdc"), 4),
            ]
            for row in pnl.get("by_market") or []
        ],
    ))
    high_rows = [
        (row.get("market_id"), row.get("current_high_assessment") or {})
        for row in payload.get("markets") or []
        if row.get("current_high_assessment")
    ]
    if high_rows:
        lines.extend(["", "## Current High Assessment", ""])
        lines.extend(markdown_table(
            [
                "Market",
                "Raw high",
                "Settlement high",
                "Raw prob",
                "Settlement prob",
                "Revision",
                "Current max state",
                "Trusted",
            ],
            [
                [
                    market_id,
                    assessment.get("raw_current_high"),
                    assessment.get("settlement_current_high"),
                    assessment.get("probability_on_raw_current_high"),
                    assessment.get("probability_on_settlement_current_high"),
                    assessment.get("revision_state") or "-",
                    assessment.get("current_max_state") or "-",
                    str(assessment.get("current_high_trusted")).lower(),
                ]
                for market_id, assessment in high_rows
            ],
        ))
    lines.extend(["", "## Reasons", ""])
    lines.extend(markdown_table(
        ["Reason", "Rows"],
        [[key, value] for key, value in sorted((pnl_summary.get("reason_counts") or {}).items())],
    ))
    lines.append("")
    return "\n".join(lines)


def discover_inputs(
    target_date,
    markets=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    config=None,
    now=None,
    observation_status=None,
):
    now = utc_now(now)
    config = {**DEFAULT_CONFIG, **(config or {})}
    rows = []
    market_summaries = []
    for spec in selected_specs(markets):
        market_config = config_for_date(target_date, spec.id)
        folder = Path(snapshots_root) / market_config.event_slug
        snapshot_rows = load_latest_snapshot_rows(folder)
        current_high_assessment = current_high_probability_summary(
            snapshot_rows,
            normalized_high_for_market(observation_status, spec.id),
        )
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_rows = source_status_for_snapshot(folder, snapshot_id)
        book_rows = latest_book_rows(folder)
        clob_feature_rows = latest_clob_feature_rows(
            folder,
            snapshot_id,
            build_if_missing=True,
            max_age_seconds=float(config["max_book_age_seconds"]),
            market_id=spec.id,
        )
        market_summaries.append(
            preflight_summary_for_market(
                spec,
                target_date,
                folder,
                snapshot_rows,
                source_rows,
                book_rows,
                clob_feature_rows,
                current_high_assessment=current_high_assessment,
            )
        )
        market_summaries[-1]["current_high_assessment"] = current_high_assessment
        if snapshot_rows:
            rows.extend(
                assemble_taker_inputs_for_market(
                    spec.id,
                    folder,
                    snapshot_rows,
                    source_rows,
                    clob_feature_rows,
                    book_rows,
                    current_high_assessment=current_high_assessment,
                )
            )
    return rows, market_summaries


def build_run_config_payload(
    run_id,
    target_date,
    budget_usdc,
    markets,
    run_folder,
    snapshots_root,
    config,
    now,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
):
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat(),
        "mode": "paper-taker",
        "budget_usdc": float(budget_usdc),
        "markets": [spec.id for spec in selected_specs(markets)],
        "run_folder": str(run_folder),
        "snapshots_root": str(snapshots_root),
        "observation_status_path": str(observation_status_path),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "policy_config": config,
        "shadow_safety": {
            "loads_private_keys": False,
            "posts_orders": False,
            "pretend_taker_orders_only": True,
        },
    }


def build_run_once(
    target_date,
    budget_usdc,
    markets=None,
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    run_id=None,
    config=None,
    now=None,
    append=True,
    ledger_root=None,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
):
    now = utc_now(now)
    target = ensure_date(target_date)
    config = {**DEFAULT_CONFIG, **(config or {})}
    run_id = run_id or default_run_id(target, config=config)
    run_folder = run_folder_for(runs_root, target, run_id)
    run_folder.mkdir(parents=True, exist_ok=True)
    order_path = run_folder / "orders_long.csv"
    existing_rows = read_order_rows(order_path) if append else []
    observation_status = load_observation_status(observation_status_path, now=now, config=config)
    input_rows, market_summaries = discover_inputs(
        target,
        markets=markets,
        snapshots_root=snapshots_root,
        config=config,
        now=now,
        observation_status=observation_status,
    )
    new_rows, budget_ledger = apply_taker_budget(
        input_rows,
        existing_rows,
        budget_usdc,
        run_id,
        target,
        now,
        config,
    )
    all_rows = score_orders([*existing_rows, *new_rows], snapshots_root=snapshots_root, ledger_root=ledger_root, now=now)
    write_csv_rows(order_path, ORDER_COLUMNS, all_rows)
    tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
    append_jsonl(run_folder / "budget_ledger.jsonl", budget_ledger)
    pnl_payload = build_pnl_payload(all_rows, budget_usdc, run_id, target, now=now)
    write_json(run_folder / "daily_pnl.json", pnl_payload)
    run_config = build_run_config_payload(
        run_id,
        target,
        budget_usdc,
        markets,
        run_folder,
        snapshots_root,
        config,
        now,
        observation_status_path=observation_status_path,
    )
    write_json(run_folder / "run_config.json", run_config)

    reason_counts = Counter(row.get("reason_code") or "unknown" for row in new_rows)
    latest_filled = [row for row in new_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    zero_trade_diagnosis = classify_zero_trade_root_cause(
        market_summaries,
        permission_rows=len(latest_filled),
        output_rows=len(new_rows),
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker",
        "budget_usdc": round(float(budget_usdc), 6),
        "budget_spent_usdc": pnl_payload["summary"]["budget_spent_usdc"],
        "budget_remaining_usdc": pnl_payload["summary"]["budget_remaining_usdc"],
        "latest_tick_rows": len(new_rows),
        "latest_tick_filled_orders": len(latest_filled),
        "latest_tick_spent_usdc": sum_field(latest_filled, "total_spent_usdc"),
        "cumulative_order_rows": len(all_rows),
        "cumulative_filled_orders": pnl_payload["summary"]["filled_order_count"],
        "cumulative_net_pnl_usdc": pnl_payload["summary"]["net_pnl_usdc"],
        "reason_counts": dict(sorted(reason_counts.items())),
        "market_status_counts": dict(sorted(Counter(row.get("status") for row in market_summaries).items())),
        "tape_integrity": tape_integrity,
        **zero_trade_diagnosis,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": target.isoformat(),
        "mode": "paper-taker",
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "orders_path": str(order_path),
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
        "daily_pnl_path": str(run_folder / "daily_pnl.json"),
        "run_report_path": str(run_folder / "run_report.md"),
        "summary": summary,
        "config": config,
        "observation_status": observation_status,
        "markets": market_summaries,
        "pnl": pnl_payload,
        "latest_orders": new_rows,
        "tape_integrity": tape_integrity,
        "operator_alert": {
            "run_folder": str(run_folder),
            "clob_status_command": "python -m weather.market.market_microstructure status",
            "first_failing_gate": zero_trade_diagnosis.get("first_failing_gate"),
            "root_cause_class": zero_trade_diagnosis.get("root_cause_class"),
            "remediation_command": "python -m weather.market.market_microstructure ensure",
        },
    }
    write_json(run_folder / "run_summary.json", payload)
    (run_folder / "run_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def paper_until_utc(target_date, markets=None):
    target = ensure_date(target_date)
    specs = selected_specs(markets)
    ends = [
        datetime.combine(target, dt_time(23, 59, 59), tzinfo=spec.tz).astimezone(timezone.utc)
        for spec in specs
    ]
    return max(ends) if ends else None


def run_loop(
    target_date,
    budget_usdc,
    markets=None,
    interval_seconds=60.0,
    until_utc=None,
    max_ticks=None,
    **kwargs,
):
    until = parse_time(until_utc) if until_utc else paper_until_utc(target_date, markets=markets)
    results = []
    tick = 0
    while True:
        now = utc_now()
        if until is not None and now > until:
            break
        if max_ticks is not None and tick >= int(max_ticks):
            break
        payload = build_run_once(
            target_date,
            budget_usdc,
            markets=markets,
            now=now,
            append=True,
            **kwargs,
        )
        results.append(payload)
        tick += 1
        if max_ticks is not None and tick >= int(max_ticks):
            break
        time.sleep(float(interval_seconds))
    return results[-1] if results else None


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value.")
        key, value = item.split("=", 1)
        if key not in DEFAULT_CONFIG:
            raise SystemExit(f"Unknown taker bot config key {key!r}.")
        default = DEFAULT_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, int):
            config[key] = int(float(value))
        elif isinstance(default, float):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the daily paper taker-bot simulator.")
    parser.add_argument("--date", required=True, help="Target market date, YYYY-MM-DD.")
    parser.add_argument("--budget-usdc", type=float, required=True, help="Daily simulated spend budget.")
    parser.add_argument("--markets", default="all", help="'all' or comma-separated market ids.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--config", action="append", default=[], help="Taker bot config override, key=value.")
    parser.add_argument("--fresh", action="store_true", help="Start a fresh run folder instead of appending daily state.")
    parser.add_argument("--loop", action="store_true", help="Run repeatedly until end of market day or --until-utc.")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--until-utc", default=None)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--ledger-root", default=None)
    args = parser.parse_args(argv)

    common = {
        "markets": args.markets,
        "runs_root": Path(args.runs_root),
        "snapshots_root": Path(args.snapshots_root),
        "run_id": args.run_id,
        "config": parse_config_overrides(args.config),
        "ledger_root": Path(args.ledger_root) if args.ledger_root else None,
        "observation_status_path": Path(args.observation_status),
    }
    if args.loop and args.now is None and not args.fresh:
        payload = run_loop(
            args.date,
            args.budget_usdc,
            interval_seconds=args.interval_seconds,
            until_utc=args.until_utc,
            max_ticks=args.max_ticks,
            **common,
        )
    else:
        payload = build_run_once(
            args.date,
            args.budget_usdc,
            now=args.now,
            append=not args.fresh,
            **common,
        )
    if payload is None:
        print("Taker bot: no ticks executed")
        return None
    summary = payload["summary"]
    print(
        "Taker bot: "
        f"{summary['latest_tick_filled_orders']} new buys, "
        f"{summary['cumulative_filled_orders']} cumulative buys, "
        f"P&L {summary['cumulative_net_pnl_usdc']} USDC -> {payload['run_folder']}"
    )
    return payload


if __name__ == "__main__":
    main()
