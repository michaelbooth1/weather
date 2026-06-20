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
import sys
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
from weather.operations.power import keep_system_awake
from weather.paths import data_path


SCHEMA_VERSION = "taker_bot_run_v0.1"
FINALIZATION_SCHEMA_VERSION = "taker_settlement_finalization_v0.1"
STRATEGY_REGISTRY_SCHEMA_VERSION = "taker_strategy_registry_v0.1"
STRATEGY_REPORT_SCHEMA_VERSION = "taker_strategy_report_v0.1"
STRATEGY_BAKEOFF_SCHEMA_VERSION = "taker_strategy_bakeoff_v0.1"
POLICY_VERSION = "taker_bot_policy_v0.1"
DEFAULT_RUNS_ROOT = data_path() / "taker_runs"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LABELS_CSV = data_path() / "backtest" / "market_day_labels.csv"
RECONCILIATION_WARNING_USDC = 1.0
SETTLEMENT_PNL_SOURCES = {"settlement", "settlement_finalized"}
DEFAULT_CONTROL_STRATEGY_ID = "raw_edge_control"
DEFAULT_EXPERIMENT_ID = "default_taker_strategy_experiment"
DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS = 1
DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC = 100.0

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
    "min_ask_size_at_best": 0.0,
    "min_capture_hour_local": -1,
    "max_current_high_band_distance": 9999.0,
    "require_current_high_trusted": False,
    "risk_adjusted_entry_enabled": False,
    "min_risk_adjusted_edge": 0.0,
    "calibration_confidence_floor": 0.15,
    "sizing_rule": "flat_notional",
    "kelly_fraction": 0.25,
    "ev_tier_low_edge": 0.05,
    "ev_tier_high_edge": 0.12,
    "ev_tier_low_multiplier": 0.25,
    "ev_tier_mid_multiplier": 0.5,
    "ev_tier_high_multiplier": 1.0,
    "tail_price_threshold": 0.05,
    "tail_lottery_max_order_usdc": 0.5,
    "max_market_notional_usdc": 0.0,
    "max_adjacent_cluster_notional_usdc": 0.0,
    "max_low_price_tail_notional_usdc": 0.0,
    "max_repeated_opinion_fills": 0,
    "require_clob_continuity": False,
    "max_mark_sanity_ratio": 3.0,
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

DEFAULT_STRATEGY_REGISTRY = {
    DEFAULT_CONTROL_STRATEGY_ID: {
        "strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": "raw_edge",
        "status": "control",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Current taker policy: buy YES when best ask is cheap versus model fair probability.",
        "config_overrides": {},
    },
    "small_order_probe": {
        "strategy_id": "small_order_probe",
        "strategy_family": "sizing_probe",
        "status": "shadow",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Same edge filter as control with a tiny per-order and per-token notional cap.",
        "config_overrides": {
            "max_order_usdc": 1.0,
            "max_position_per_token_usdc": 1.0,
        },
    },
    "strict_edge_probe": {
        "strategy_id": "strict_edge_probe",
        "strategy_family": "edge_threshold",
        "status": "shadow",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Control policy with a higher minimum raw edge for early strategy-quality comparisons.",
        "config_overrides": {
            "min_edge": 0.10,
        },
    },
    "calibrated_edge": {
        "strategy_id": "calibrated_edge",
        "strategy_family": "calibration_filter",
        "status": "candidate",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Higher edge, fresher model, and minimum displayed ask depth as a calibration proxy.",
        "config_overrides": {
            "min_edge": 0.06,
            "max_model_age_seconds": 300.0,
            "min_ask_size_at_best": 5.0,
            "risk_adjusted_entry_enabled": True,
            "min_risk_adjusted_edge": 0.03,
            "sizing_rule": "fractional_kelly",
            "max_market_notional_usdc": 25.0,
            "max_adjacent_cluster_notional_usdc": 15.0,
            "max_repeated_opinion_fills": 1,
        },
    },
    "low_price_tail_capped": {
        "strategy_id": "low_price_tail_capped",
        "strategy_family": "tail_risk_sizing",
        "status": "candidate",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Only cheap YES tails, with small per-order and per-token exposure caps.",
        "config_overrides": {
            "min_edge": 0.08,
            "max_price": 0.20,
            "max_order_usdc": 1.0,
            "max_position_per_token_usdc": 1.0,
            "max_daily_positions": 12,
            "sizing_rule": "tail_lottery",
            "tail_lottery_max_order_usdc": 0.5,
            "max_low_price_tail_notional_usdc": 3.0,
            "max_market_notional_usdc": 5.0,
            "max_repeated_opinion_fills": 1,
        },
    },
    "winner_centered_or_adjacent": {
        "strategy_id": "winner_centered_or_adjacent",
        "strategy_family": "current_high_context",
        "status": "candidate",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Only buy bands centered on, or adjacent to, the settlement-normalized current high.",
        "config_overrides": {
            "min_edge": 0.04,
            "max_current_high_band_distance": 1.0,
            "sizing_rule": "ev_tiered",
            "max_market_notional_usdc": 20.0,
            "max_adjacent_cluster_notional_usdc": 12.0,
            "max_repeated_opinion_fills": 1,
        },
    },
    "current_high_lockin": {
        "strategy_id": "current_high_lockin",
        "strategy_family": "current_high_context",
        "status": "candidate",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Only buy a trusted settlement-normalized current-high band.",
        "config_overrides": {
            "max_current_high_band_distance": 0.0,
            "require_current_high_trusted": True,
            "max_order_usdc": 2.0,
            "max_position_per_token_usdc": 2.0,
            "sizing_rule": "ev_tiered",
            "max_market_notional_usdc": 8.0,
            "max_adjacent_cluster_notional_usdc": 6.0,
            "max_repeated_opinion_fills": 1,
        },
    },
    "late_day_liquidity_filtered": {
        "strategy_id": "late_day_liquidity_filtered",
        "strategy_family": "timing_liquidity",
        "status": "candidate",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": "Only trade later local hours with fresh books and visible ask depth.",
        "config_overrides": {
            "min_capture_hour_local": 15,
            "max_book_age_seconds": 45.0,
            "min_ask_size_at_best": 10.0,
            "sizing_rule": "ev_tiered",
            "require_clob_continuity": True,
            "max_market_notional_usdc": 15.0,
            "max_adjacent_cluster_notional_usdc": 10.0,
            "max_repeated_opinion_fills": 1,
        },
    },
}

DEFAULT_BAKEOFF_STRATEGIES = ",".join([
    DEFAULT_CONTROL_STRATEGY_ID,
    "calibrated_edge",
    "low_price_tail_capped",
    "winner_centered_or_adjacent",
    "current_high_lockin",
    "late_day_liquidity_filtered",
])

ORDER_COLUMNS = [
    "schema_version",
    "policy_version",
    "policy_hash",
    "experiment_id",
    "strategy_id",
    "strategy_family",
    "assignment_rule",
    "control_strategy_id",
    "strategy_config_hash",
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
    "reliability_context_key",
    "reliability_confidence",
    "reliability_adjusted_fair_probability",
    "reliability_adjustment",
    "reliability_reason",
    "risk_adjusted_edge",
    "risk_adjusted_expected_profit_per_share",
    "sizing_rule",
    "sizing_multiplier",
    "sizing_limit_reason",
    "low_price_tail",
    "tail_risk_bucket",
    "current_high_band_distance",
    "adjacent_bin_cluster_key",
    "market_notional_before_usdc",
    "adjacent_cluster_notional_before_usdc",
    "low_price_tail_notional_before_usdc",
    "repeated_opinion_fill_count_before",
    "clob_continuity_status",
    "clob_continuity_reason",
    "mark_sanity_status",
    "mark_sanity_reason",
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


def stable_hash(payload, length=16):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def default_run_id(target_date, config=None):
    target = ensure_date(target_date)
    digest = policy_hash({**DEFAULT_CONFIG, **(config or {})})[:8]
    return f"taker-{target.strftime('%Y%m%d')}-{digest}"


def default_experiment_id(target_date, strategy_ids=None):
    target = ensure_date(target_date)
    strategy_ids = list(strategy_ids or [DEFAULT_CONTROL_STRATEGY_ID])
    if strategy_ids == [DEFAULT_CONTROL_STRATEGY_ID]:
        return DEFAULT_EXPERIMENT_ID
    digest = stable_hash({"target_date": target.isoformat(), "strategy_ids": strategy_ids}, length=8)
    return f"taker-{target.strftime('%Y%m%d')}-{digest}"


def strategy_registry_payload(registry=None):
    registry = registry or DEFAULT_STRATEGY_REGISTRY
    return {
        "schema_version": STRATEGY_REGISTRY_SCHEMA_VERSION,
        "default_control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategies": [
            dict(registry[key], strategy_id=registry[key].get("strategy_id") or key)
            for key in sorted(registry)
        ],
    }


def strategy_ids_from_arg(value):
    if value in (None, "", "default"):
        return [DEFAULT_CONTROL_STRATEGY_ID]
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = str(value).replace(";", ",").split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def selected_strategy_specs(strategies=None, base_config=None, registry=None):
    registry = registry or DEFAULT_STRATEGY_REGISTRY
    base_config = {**DEFAULT_CONFIG, **(base_config or {})}
    specs = []
    for strategy_id in strategy_ids_from_arg(strategies):
        if strategy_id not in registry:
            known = ", ".join(sorted(registry))
            raise SystemExit(f"unknown taker strategy id {strategy_id!r}; known strategies: {known}")
        raw = dict(registry[strategy_id])
        config = {**base_config, **(raw.get("config_overrides") or {})}
        raw["strategy_id"] = raw.get("strategy_id") or strategy_id
        raw["strategy_family"] = raw.get("strategy_family") or "unknown"
        raw["assignment_rule"] = raw.get("assignment_rule") or "shared_inputs_full_shadow"
        raw["control_strategy_id"] = raw.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
        raw["config"] = config
        raw["policy_hash"] = policy_hash(config)
        raw["strategy_config_hash"] = stable_hash({
            "strategy_id": raw["strategy_id"],
            "strategy_family": raw["strategy_family"],
            "config": config,
        })
        specs.append(raw)
    return specs


def strategy_id_for_row(row):
    return str(row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID)


def normalize_order_strategy_fields(row, strategy=None, experiment_id=None):
    row = dict(row)
    strategy = strategy or {}
    strategy_id = strategy.get("strategy_id") or row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    row["experiment_id"] = experiment_id or row.get("experiment_id") or DEFAULT_EXPERIMENT_ID
    row["strategy_id"] = strategy_id
    row["strategy_family"] = strategy.get("strategy_family") or row.get("strategy_family") or "raw_edge"
    row["assignment_rule"] = (
        strategy.get("assignment_rule") or row.get("assignment_rule") or "shared_inputs_full_shadow"
    )
    row["control_strategy_id"] = (
        strategy.get("control_strategy_id") or row.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    )
    row["strategy_config_hash"] = (
        strategy.get("strategy_config_hash") or row.get("strategy_config_hash") or row.get("policy_hash") or ""
    )
    return row


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
    return [
        normalize_order_strategy_fields(row)
        for row in read_csv_rows(path, attach_diagnostics=True)
    ]


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


def low_price_tail_flag(row, config):
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    threshold = float(config.get("tail_price_threshold") or 0.0)
    return bool(threshold > 0 and best_ask is not None and best_ask <= threshold)


def tail_risk_bucket(row, config):
    if low_price_tail_flag(row, config):
        return "low_price_tail"
    distance = current_high_band_distance(row)
    if distance is not None and distance <= 1:
        return "current_high_or_adjacent"
    return "regular"


def adjacent_bin_cluster_key(row):
    kind, value, value_hi = band_key(row)
    market_id = row.get("market_id") or "unknown"
    event_slug = row.get("event_slug") or "unknown"
    if value is None:
        return f"{market_id}:{event_slug}:missing"
    if kind in {"lte", "gte"}:
        return f"{market_id}:{event_slug}:{kind}:{value}"
    cluster_floor = int(value) - (int(value) % 3)
    return f"{market_id}:{event_slug}:eq:{cluster_floor}-{cluster_floor + 2}"


def reliability_context_key(row):
    local, _zone_name = market_local_time(row)
    hour = maybe_float(row.get("capture_hour_local"))
    if hour is None and local is not None:
        hour = local.hour
    kind, value, value_hi = band_key(row)
    source_state = str(row.get("source_freshness_state") or "unknown").strip().lower() or "unknown"
    trust_state = "trusted_current_high" if bool_value(row.get("current_high_trusted"), True) else "untrusted_current_high"
    model_variant = row.get("model_version") or row.get("policy_version") or "unknown_model"
    return "|".join([
        row.get("market_id") or "unknown_market",
        str(model_variant),
        f"hour:{int(hour) if hour is not None else 'missing'}",
        f"band:{kind}:{value}:{value_hi}",
        f"source:{source_state}",
        trust_state,
    ])


def reliability_confidence(row, config):
    confidence = 1.0
    reasons = []
    source_state = str(row.get("source_freshness_state") or "").strip().lower()
    if source_state and source_state not in {"all_fresh", "fresh"}:
        confidence *= 0.80
        reasons.append(f"source_state:{source_state}")
    if not bool_value(row.get("current_high_trusted"), True):
        confidence *= 0.70
        reasons.append("untrusted_current_high")
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is not None and model_age > 300:
        confidence *= 0.85
        reasons.append("model_age_gt_300s")
    book_age = maybe_float(row.get("book_age_seconds"))
    if book_age is not None and book_age > 60:
        confidence *= 0.90
        reasons.append("book_age_gt_60s")
    if low_price_tail_flag(row, config):
        confidence *= 0.85
        reasons.append("low_price_tail")
    floor = float(config.get("calibration_confidence_floor", 0.15) or 0.15)
    confidence = max(floor, min(1.0, confidence))
    return confidence, reasons or ["full_confidence"]


def clob_continuity_state(row, config):
    best_bid = maybe_float(first_present(row, "best_bid", "clob_best_bid", "gamma_best_bid"))
    best_ask = maybe_float(first_present(row, "best_ask", "clob_best_ask", "gamma_best_ask"))
    book_age = maybe_float(row.get("book_age_seconds"))
    if best_ask is None:
        return "missing", "missing best ask"
    if best_bid is not None and best_bid > best_ask:
        return "broken", "best bid is above best ask"
    if book_age is None:
        return "missing", "missing book age"
    if book_age > float(config.get("max_book_age_seconds") or DEFAULT_CONFIG["max_book_age_seconds"]):
        return "stale", "book age exceeds strategy continuity window"
    return "pass", "book is continuous enough for sizing"


def mark_sanity_state(row, config):
    mark = maybe_float(first_present(row, "mark_pnl_usdc", "net_pnl_usdc"))
    spent = maybe_float(first_present(row, "total_spent_usdc", "fill_notional_usdc"))
    if mark is None or spent in (None, 0):
        return "not_available", "no mark P&L available"
    ratio = abs(mark) / max(1e-9, abs(spent))
    max_ratio = float(config.get("max_mark_sanity_ratio") or DEFAULT_CONFIG["max_mark_sanity_ratio"])
    if ratio > max_ratio:
        return "outlier", f"mark P&L/spend ratio {ratio:.3f} exceeds {max_ratio:.3f}"
    return "pass", "mark P&L is within sanity ratio"


def enrich_taker_risk_fields(row, config):
    out = dict(row)
    fair = clamp_probability(out.get("fair_probability"))
    best_ask = clamp_probability(first_present(out, "best_ask", "clob_best_ask"))
    edge = maybe_float(out.get("edge"))
    if edge is None and fair is not None and best_ask is not None:
        edge = fair - best_ask
    confidence, reasons = reliability_confidence(out, config)
    adjusted = None
    risk_edge = None
    if fair is not None and best_ask is not None and edge is not None:
        adjusted = clamp_probability(best_ask + (edge * confidence))
        risk_edge = adjusted - best_ask if adjusted is not None else None
    continuity_status, continuity_reason = clob_continuity_state(out, config)
    mark_status, mark_reason = mark_sanity_state(out, config)
    out.update({
        "reliability_context_key": reliability_context_key(out),
        "reliability_confidence": compact_float(confidence),
        "reliability_adjusted_fair_probability": compact_float(adjusted),
        "reliability_adjustment": compact_float((adjusted - fair) if adjusted is not None and fair is not None else None),
        "reliability_reason": ",".join(reasons),
        "risk_adjusted_edge": compact_float(risk_edge),
        "risk_adjusted_expected_profit_per_share": compact_float(risk_edge),
        "sizing_rule": config.get("sizing_rule") or "flat_notional",
        "sizing_multiplier": 1.0,
        "sizing_limit_reason": "base",
        "low_price_tail": low_price_tail_flag(out, config),
        "tail_risk_bucket": tail_risk_bucket(out, config),
        "current_high_band_distance": compact_float(current_high_band_distance(out)),
        "adjacent_bin_cluster_key": adjacent_bin_cluster_key(out),
        "clob_continuity_status": continuity_status,
        "clob_continuity_reason": continuity_reason,
        "mark_sanity_status": mark_status,
        "mark_sanity_reason": mark_reason,
    })
    return out


def base_order_row(input_row, run_id, target_date, now, config, config_hash, strategy=None, experiment_id=None):
    strategy = strategy or {}
    experiment_id = experiment_id or DEFAULT_EXPERIMENT_ID
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
        "experiment_id": experiment_id,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
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
        "experiment_id": experiment_id,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": strategy.get("strategy_family") or "raw_edge",
        "assignment_rule": strategy.get("assignment_rule") or "shared_inputs_full_shadow",
        "control_strategy_id": strategy.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_config_hash": strategy.get("strategy_config_hash") or config_hash,
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
        "reliability_context_key": "",
        "reliability_confidence": None,
        "reliability_adjusted_fair_probability": None,
        "reliability_adjustment": None,
        "reliability_reason": "",
        "risk_adjusted_edge": None,
        "risk_adjusted_expected_profit_per_share": None,
        "sizing_rule": config.get("sizing_rule") or "flat_notional",
        "sizing_multiplier": 1.0,
        "sizing_limit_reason": "base",
        "low_price_tail": False,
        "tail_risk_bucket": "",
        "current_high_band_distance": None,
        "adjacent_bin_cluster_key": "",
        "market_notional_before_usdc": 0.0,
        "adjacent_cluster_notional_before_usdc": 0.0,
        "low_price_tail_notional_before_usdc": 0.0,
        "repeated_opinion_fill_count_before": 0,
        "clob_continuity_status": "",
        "clob_continuity_reason": "",
        "mark_sanity_status": "",
        "mark_sanity_reason": "",
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
    min_ask_size = float(config.get("min_ask_size_at_best") or 0.0)
    if min_ask_size > 0 and ask_size < min_ask_size:
        return "NO_TRADE_INSUFFICIENT_ASK_DEPTH", "ask size at best is below strategy liquidity floor"
    if book_age is None or book_age > float(config["max_book_age_seconds"]):
        return "NO_TRADE_STALE_BOOK", "book age exceeds latency budget"
    if model_age is None or model_age > float(config["max_model_age_seconds"]):
        return "NO_TRADE_STALE_MODEL", "model age exceeds latency budget"
    min_capture_hour = maybe_float(config.get("min_capture_hour_local"))
    if min_capture_hour is not None and min_capture_hour >= 0:
        capture_hour = maybe_float(row.get("capture_hour_local"))
        if capture_hour is None:
            local, _zone_name = market_local_time(row)
            capture_hour = local.hour if local else None
        if capture_hour is None or capture_hour < min_capture_hour:
            return "NO_TRADE_TOO_EARLY_LOCAL_HOUR", "local capture hour is before strategy timing window"
    if config.get("require_current_high_trusted") and not bool_value(row.get("current_high_trusted"), False):
        return "NO_TRADE_CURRENT_HIGH_NOT_TRUSTED", "current-high state is not trusted enough for this strategy"
    if config.get("require_clob_continuity") and row.get("clob_continuity_status") != "pass":
        return "NO_TRADE_CLOB_CONTINUITY", row.get("clob_continuity_reason") or "CLOB continuity gate failed"
    max_current_high_distance = maybe_float(config.get("max_current_high_band_distance"))
    if max_current_high_distance is not None and max_current_high_distance < 9999.0:
        distance = current_high_band_distance(row)
        if distance is None or distance > max_current_high_distance:
            return (
                "NO_TRADE_CURRENT_HIGH_DISTANCE",
                "band is outside the strategy current-high distance window",
            )
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
    if config.get("risk_adjusted_entry_enabled"):
        risk_edge = maybe_float(row.get("risk_adjusted_edge"))
        min_risk_edge = float(config.get("min_risk_adjusted_edge") or 0.0)
        if risk_edge is None or risk_edge < min_risk_edge:
            return "NO_TRADE_RISK_ADJUSTED_EDGE_TOO_SMALL", "reliability-adjusted edge is too small"
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


def existing_notional_by(rows, key_func):
    totals = defaultdict(float)
    for row in rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        totals[key_func(row)] += maybe_float(row.get("fill_notional_usdc")) or 0.0
    return totals


def existing_low_price_tail_notional(rows):
    return round(sum(
        maybe_float(row.get("fill_notional_usdc")) or 0.0
        for row in rows or []
        if str(row.get("order_status") or "").upper() == "FILLED"
        and bool_value(row.get("low_price_tail"), False)
    ), 6)


def existing_opinion_fill_counts(rows):
    counts = Counter()
    for row in rows or []:
        if str(row.get("order_status") or "").upper() == "FILLED":
            counts[independent_opinion_key(row)] += 1
    return counts


def remaining_cap(cap_value, used_value):
    cap = maybe_float(cap_value)
    if cap is None or cap <= 0:
        return None
    return max(0.0, cap - float(used_value or 0.0))


def current_high_band_distance(row):
    current = maybe_float(first_present(row, "settlement_current_high", "raw_current_high_bucket", "raw_current_high"))
    kind, value, value_hi = band_key(row)
    if current is None or value is None:
        return None
    value_hi = value if value_hi is None else value_hi
    if kind == "lte":
        return 0.0 if current <= value else round(abs(current - value), 6)
    if kind == "gte":
        return 0.0 if current >= value else round(abs(value - current), 6)
    if value <= current <= value_hi:
        return 0.0
    return round(min(abs(current - value), abs(current - value_hi)), 6)


def sizing_notional_cap(row, config, remaining_budget, base_cap):
    rule = str(config.get("sizing_rule") or "flat_notional")
    base_cap = max(0.0, float(base_cap or 0.0))
    if base_cap <= 0:
        return 0.0, 0.0, "base_cap_zero"
    risk_edge = maybe_float(first_present(row, "risk_adjusted_edge", "edge"))
    confidence = maybe_float(row.get("reliability_confidence")) or 1.0
    price = maybe_float(first_present(row, "best_ask", "clob_best_ask"))
    adjusted_fair = maybe_float(first_present(row, "reliability_adjusted_fair_probability", "fair_probability"))
    if rule == "fractional_kelly":
        if price is None or adjusted_fair is None or price >= 1.0:
            return 0.0, 0.0, "fractional_kelly_missing_inputs"
        full_kelly = max(0.0, (adjusted_fair - price) / max(1e-9, 1.0 - price))
        multiplier = min(1.0, full_kelly * float(config.get("kelly_fraction") or 0.0) * confidence)
        return min(base_cap, float(remaining_budget) * multiplier), compact_float(multiplier), "fractional_kelly"
    if rule == "ev_tiered":
        if risk_edge is None or risk_edge <= 0:
            multiplier = 0.0
            reason = "ev_tier_no_positive_edge"
        elif risk_edge >= float(config.get("ev_tier_high_edge") or 0.0):
            multiplier = float(config.get("ev_tier_high_multiplier") or 1.0)
            reason = "ev_tier_high"
        elif risk_edge >= float(config.get("ev_tier_low_edge") or 0.0):
            multiplier = float(config.get("ev_tier_mid_multiplier") or 0.5)
            reason = "ev_tier_mid"
        else:
            multiplier = float(config.get("ev_tier_low_multiplier") or 0.25)
            reason = "ev_tier_low"
        multiplier = max(0.0, min(1.0, multiplier * confidence))
        return min(base_cap, base_cap * multiplier), compact_float(multiplier), reason
    if rule == "tail_lottery":
        if bool_value(row.get("low_price_tail"), False):
            cap = min(base_cap, float(config.get("tail_lottery_max_order_usdc") or base_cap))
            return cap, compact_float(cap / base_cap if base_cap else 0.0), "tail_lottery_cap"
        multiplier = min(1.0, 0.5 * confidence)
        return min(base_cap, base_cap * multiplier), compact_float(multiplier), "tail_lottery_non_tail"
    return base_cap, 1.0, "flat_notional"


def strategy_event_fields(run_id, now, strategy=None, experiment_id=None):
    strategy = strategy or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at_utc": now.isoformat(),
        "experiment_id": experiment_id or DEFAULT_EXPERIMENT_ID,
        "strategy_id": strategy.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_family": strategy.get("strategy_family") or "raw_edge",
        "assignment_rule": strategy.get("assignment_rule") or "shared_inputs_full_shadow",
        "control_strategy_id": strategy.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_config_hash": strategy.get("strategy_config_hash") or "",
    }


def apply_taker_budget(
    input_rows,
    existing_rows,
    budget_usdc,
    run_id,
    target_date,
    now,
    config,
    strategy=None,
    experiment_id=None,
):
    strategy = strategy or selected_strategy_specs(None, base_config=config)[0]
    experiment_id = experiment_id or DEFAULT_EXPERIMENT_ID
    budget = float(budget_usdc)
    config_hash = policy_hash(config)
    existing_keys = {row.get("intent_key") for row in existing_rows or [] if row.get("intent_key")}
    seen_keys = set(existing_keys)
    rows = []
    candidates = []
    for input_row in input_rows:
        row = base_order_row(
            input_row,
            run_id,
            target_date,
            now,
            config,
            config_hash,
            strategy=strategy,
            experiment_id=experiment_id,
        )
        if row["intent_key"] in seen_keys:
            continue
        seen_keys.add(row["intent_key"])
        row.update(early_hour_guardrail_state({**input_row, **row}, config))
        row.update(enrich_taker_risk_fields({**input_row, **row}, config))
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
    market_positions = existing_notional_by(existing_rows, lambda item: item.get("market_id") or "unknown")
    cluster_positions = existing_notional_by(
        existing_rows,
        lambda item: item.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(item),
    )
    tail_notional = existing_low_price_tail_notional(existing_rows)
    opinion_counts = existing_opinion_fill_counts(existing_rows)
    filled_count = sum(1 for row in existing_rows or [] if str(row.get("order_status") or "").upper() == "FILLED")
    ledger = [{
        **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
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
        market_key = row.get("market_id") or "unknown"
        cluster_key = row.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(row)
        opinion_key = independent_opinion_key(row)
        market_before = market_positions[market_key]
        cluster_before = cluster_positions[cluster_key]
        repeated_before = opinion_counts[opinion_key]
        row["budget_usdc"] = round(budget, 6)
        row["budget_spent_before_usdc"] = round(spent, 6)
        row["position_notional_before_usdc"] = round(position_before, 6)
        row["market_notional_before_usdc"] = round(market_before, 6)
        row["adjacent_cluster_notional_before_usdc"] = round(cluster_before, 6)
        row["low_price_tail_notional_before_usdc"] = round(tail_notional, 6)
        row["repeated_opinion_fill_count_before"] = int(repeated_before)

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
        max_repeated = int(float(config.get("max_repeated_opinion_fills") or 0))
        if max_repeated > 0 and repeated_before >= max_repeated:
            row.update({
                "reason_code": "NO_TRADE_REPEATED_OPINION_CAP",
                "reason_detail": "strategy repeated-opinion fill cap reached",
            })
            rows.append(row)
            continue
        market_remaining = remaining_cap(config.get("max_market_notional_usdc"), market_before)
        if market_remaining is not None:
            if market_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_MARKET_EXPOSURE_CAP",
                    "reason_detail": "strategy market-level exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, market_remaining)
        cluster_remaining = remaining_cap(config.get("max_adjacent_cluster_notional_usdc"), cluster_before)
        if cluster_remaining is not None:
            if cluster_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_ADJACENT_CLUSTER_EXPOSURE_CAP",
                    "reason_detail": "strategy adjacent-bin cluster exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, cluster_remaining)
        tail_remaining = remaining_cap(config.get("max_low_price_tail_notional_usdc"), tail_notional)
        if bool_value(row.get("low_price_tail"), False) and tail_remaining is not None:
            if tail_remaining <= 1e-9:
                row.update({
                    "reason_code": "NO_TRADE_LOW_PRICE_TAIL_EXPOSURE_CAP",
                    "reason_detail": "strategy low-price tail exposure cap reached",
                })
                rows.append(row)
                continue
            position_remaining = min(position_remaining, tail_remaining)
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
        base_order_notional = min(float(caps["max_order_usdc"]), position_remaining)
        max_order_notional, sizing_multiplier, sizing_reason = sizing_notional_cap(
            row,
            config,
            remaining_budget,
            base_order_notional,
        )
        row["sizing_multiplier"] = sizing_multiplier
        row["sizing_limit_reason"] = sizing_reason
        if max_order_notional <= 1e-9:
            row.update({
                "reason_code": "NO_TRADE_SIZING_RULE_ZERO",
                "reason_detail": "strategy sizing rule returned no spend",
                "budget_remaining_usdc": round(remaining_budget, 6),
                "position_notional_after_usdc": round(position_before, 6),
            })
            rows.append(row)
            continue
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
                **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
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
        market_positions[market_key] += notional
        cluster_positions[cluster_key] += notional
        if bool_value(row.get("low_price_tail"), False):
            tail_notional += notional
        opinion_counts[opinion_key] += 1
        filled_count += 1
        ledger.append({
            **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
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
        **strategy_event_fields(run_id, now, strategy=strategy, experiment_id=experiment_id),
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


def load_settlement_labels(labels_csv=DEFAULT_LABELS_CSV):
    """Load finalized market-day labels keyed by event slug and market/date."""
    labels = {
        "by_event_slug": {},
        "by_market_date": {},
    }
    for row in read_csv_rows(labels_csv, attach_diagnostics=True):
        event_slug = row.get("event_slug") or ""
        market_id = row.get("market_id") or ""
        target_date = row.get("target_date") or ""
        if event_slug:
            labels["by_event_slug"][event_slug] = row
        if market_id and target_date:
            labels["by_market_date"][(market_id, target_date)] = row
    return labels


def settlement_label_for_order(row, labels):
    event_slug = row.get("event_slug") or ""
    if event_slug and event_slug in labels.get("by_event_slug", {}):
        return labels["by_event_slug"][event_slug]
    key = (row.get("market_id") or "", row.get("target_date") or "")
    return labels.get("by_market_date", {}).get(key)


def score_orders_against_labels(order_rows, labels):
    """Score filled taker orders against finalized labels without touching raw tape."""
    scored = []
    matched = 0
    unmatched = 0
    for row in order_rows or []:
        out = dict(row)
        if str(row.get("order_status") or "").upper() != "FILLED":
            scored.append(out)
            continue
        label = settlement_label_for_order(row, labels)
        outcome = settlement_outcome_for_order(row, label)
        out["settlement_outcome"] = compact_float(outcome)
        if outcome is None:
            unmatched += 1
            out.update({
                "settlement_status": "unsettled",
                "settlement_payout_usdc": None,
                "settlement_pnl_usdc": None,
                "mark_pnl_usdc": None,
                "pnl_source": "unscored",
                "net_pnl_usdc": None,
            })
            scored.append(out)
            continue
        matched += 1
        fill_size = maybe_float(row.get("fill_size")) or 0.0
        fill_notional = maybe_float(row.get("fill_notional_usdc"))
        if fill_notional is None:
            fill_notional = maybe_float(row.get("total_spent_usdc")) or 0.0
        fee = maybe_float(row.get("fee_usdc")) or 0.0
        cost = fill_notional + fee
        payout = float(outcome) * fill_size
        pnl = payout - cost
        out.update({
            "settlement_status": "settled",
            "settlement_payout_usdc": compact_float(payout),
            "settlement_pnl_usdc": compact_float(pnl),
            "mark_pnl_usdc": None,
            "pnl_source": "settlement_finalized",
            "net_pnl_usdc": compact_float(pnl),
        })
        scored.append(out)
    return scored, {
        "matched_filled_orders": matched,
        "unmatched_filled_orders": unmatched,
        "label_count": len(labels.get("by_event_slug", {})),
    }


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


def pnl_source_for_group(settled_count, marked_count, unscored_count):
    if settled_count > 0 and marked_count == 0 and unscored_count == 0:
        return "settlement"
    if settled_count > 0:
        return "mixed_settlement_and_unscored"
    if marked_count > 0:
        return "mark_to_market"
    return "unscored"


def independent_opinion_key(row):
    return (
        row.get("market_id") or "",
        row.get("event_slug") or "",
        row.get("range_label") or "",
        row.get("bin_kind") or "",
        str(row.get("bin_value") or ""),
        str(row.get("bin_value_hi") or ""),
    )


def build_pnl_payload(order_rows, budget_usdc, run_id, target_date, now=None):
    now = utc_now(now)
    filled = [row for row in order_rows if str(row.get("order_status") or "").upper() == "FILLED"]
    settled = [row for row in filled if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES]
    marked = [row for row in filled if row.get("pnl_source") == "mark_to_market"]
    unscored = [row for row in filled if row.get("pnl_source") == "unscored"]
    reason_counts = Counter(row.get("reason_code") or "unknown" for row in order_rows)
    by_market = defaultdict(lambda: {
        "filled_order_count": 0,
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "net_pnl_usdc": 0.0,
    })
    by_strategy = defaultdict(lambda: {
        "experiment_id": "",
        "strategy_id": "",
        "strategy_family": "",
        "assignment_rule": "",
        "control_strategy_id": "",
        "strategy_config_hash": "",
        "order_rows": 0,
        "filled_order_count": 0,
        "filled_shares": 0.0,
        "spent_usdc": 0.0,
        "gross_cost_usdc": 0.0,
        "fees_usdc": 0.0,
        "settlement_payout_usdc": 0.0,
        "settlement_pnl_usdc": 0.0,
        "mark_to_market_pnl_usdc": 0.0,
        "expected_pnl_usdc": 0.0,
        "risk_adjusted_expected_pnl_usdc": 0.0,
        "net_pnl_usdc": 0.0,
        "settled_order_count": 0,
        "unsettled_order_count": 0,
        "unscored_order_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "low_price_tail_fill_count": 0,
        "low_price_tail_spent_usdc": 0.0,
        "clob_continuity_fail_count": 0,
        "mark_sanity_outlier_count": 0,
        "stale_book_rows": 0,
        "source_stale_rows": 0,
        "reason_counts": Counter(),
        "filled_opinions": set(),
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
    for row in order_rows:
        strategy_id = strategy_id_for_row(row)
        strat = by_strategy[strategy_id]
        strat["experiment_id"] = row.get("experiment_id") or DEFAULT_EXPERIMENT_ID
        strat["strategy_id"] = strategy_id
        strat["strategy_family"] = row.get("strategy_family") or "raw_edge"
        strat["assignment_rule"] = row.get("assignment_rule") or "shared_inputs_full_shadow"
        strat["control_strategy_id"] = row.get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
        strat["strategy_config_hash"] = row.get("strategy_config_hash") or row.get("policy_hash") or ""
        strat["order_rows"] += 1
        reason = row.get("reason_code") or "unknown"
        strat["reason_counts"][reason] += 1
        if reason in {"NO_TRADE_STALE_BOOK"}:
            strat["stale_book_rows"] += 1
        if reason in {"NO_TRADE_SOURCE_STALE", "NO_TRADE_EARLY_HOUR_SOURCE_STATE"}:
            strat["source_stale_rows"] += 1
    for row in filled:
        market_id = row.get("market_id") or "unknown"
        strategy_id = strategy_id_for_row(row)
        strat = by_strategy[strategy_id]
        by_market[market_id]["filled_order_count"] += 1
        by_market[market_id]["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        by_market[market_id]["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        by_market[market_id]["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        strat["filled_order_count"] += 1
        strat["filled_shares"] += maybe_float(row.get("fill_size")) or 0.0
        strat["spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        strat["gross_cost_usdc"] += maybe_float(row.get("fill_notional_usdc")) or 0.0
        strat["fees_usdc"] += maybe_float(row.get("fee_usdc")) or 0.0
        strat["settlement_payout_usdc"] += maybe_float(row.get("settlement_payout_usdc")) or 0.0
        strat["settlement_pnl_usdc"] += maybe_float(row.get("settlement_pnl_usdc")) or 0.0
        strat["mark_to_market_pnl_usdc"] += maybe_float(row.get("mark_pnl_usdc")) or 0.0
        edge = maybe_float(first_present(row, "expected_profit_per_share", "edge"))
        if edge is not None:
            strat["expected_pnl_usdc"] += (edge * (maybe_float(row.get("fill_size")) or 0.0)) - (
                maybe_float(row.get("fee_usdc")) or 0.0
            )
        risk_edge = maybe_float(first_present(row, "risk_adjusted_expected_profit_per_share", "risk_adjusted_edge"))
        if risk_edge is not None:
            strat["risk_adjusted_expected_pnl_usdc"] += (
                risk_edge * (maybe_float(row.get("fill_size")) or 0.0)
            ) - (maybe_float(row.get("fee_usdc")) or 0.0)
        if bool_value(row.get("low_price_tail"), False):
            strat["low_price_tail_fill_count"] += 1
            strat["low_price_tail_spent_usdc"] += maybe_float(row.get("total_spent_usdc")) or 0.0
        if row.get("clob_continuity_status") not in {"", "pass"}:
            strat["clob_continuity_fail_count"] += 1
        if row.get("mark_sanity_status") == "outlier":
            strat["mark_sanity_outlier_count"] += 1
        strat["net_pnl_usdc"] += maybe_float(row.get("net_pnl_usdc")) or 0.0
        if row.get("pnl_source") in SETTLEMENT_PNL_SOURCES:
            strat["settled_order_count"] += 1
        elif row.get("pnl_source") == "mark_to_market":
            strat["unsettled_order_count"] += 1
        else:
            strat["unsettled_order_count"] += 1
            strat["unscored_order_count"] += 1
        if maybe_float(row.get("settlement_outcome")) == 1.0:
            strat["win_count"] += 1
        elif maybe_float(row.get("settlement_outcome")) == 0.0:
            strat["loss_count"] += 1
        strat["filled_opinions"].add(independent_opinion_key(row))
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
    strategy_rows = []
    for key, value in sorted(by_strategy.items()):
        row = {
            "experiment_id": value["experiment_id"],
            "strategy_id": key,
            "strategy_family": value["strategy_family"],
            "assignment_rule": value["assignment_rule"],
            "control_strategy_id": value["control_strategy_id"],
            "strategy_config_hash": value["strategy_config_hash"],
            "order_rows": value["order_rows"],
            "filled_order_count": value["filled_order_count"],
            "filled_shares": round(value["filled_shares"], 6),
            "spent_usdc": round(value["spent_usdc"], 6),
            "gross_cost_usdc": round(value["gross_cost_usdc"], 6),
            "fees_usdc": round(value["fees_usdc"], 6),
            "settlement_payout_usdc": round(value["settlement_payout_usdc"], 6),
            "settlement_pnl_usdc": round(value["settlement_pnl_usdc"], 6),
            "mark_to_market_pnl_usdc": round(value["mark_to_market_pnl_usdc"], 6),
            "expected_pnl_usdc": round(value["expected_pnl_usdc"], 6),
            "risk_adjusted_expected_pnl_usdc": round(value["risk_adjusted_expected_pnl_usdc"], 6),
            "realized_minus_expected_pnl_usdc": round(
                value["net_pnl_usdc"] - value["expected_pnl_usdc"],
                6,
            ),
            "realized_minus_risk_adjusted_expected_pnl_usdc": round(
                value["net_pnl_usdc"] - value["risk_adjusted_expected_pnl_usdc"],
                6,
            ),
            "net_pnl_usdc": round(value["net_pnl_usdc"], 6),
            "settled_order_count": value["settled_order_count"],
            "unsettled_order_count": value["unsettled_order_count"],
            "unscored_order_count": value["unscored_order_count"],
            "win_count": value["win_count"],
            "loss_count": value["loss_count"],
            "independent_opinion_count": len(value["filled_opinions"]),
            "low_price_tail_fill_count": value["low_price_tail_fill_count"],
            "low_price_tail_spent_usdc": round(value["low_price_tail_spent_usdc"], 6),
            "clob_continuity_fail_count": value["clob_continuity_fail_count"],
            "mark_sanity_outlier_count": value["mark_sanity_outlier_count"],
            "stale_book_rows": value["stale_book_rows"],
            "source_stale_rows": value["source_stale_rows"],
            "pnl_source": pnl_source_for_group(
                value["settled_order_count"],
                value["unsettled_order_count"] - value["unscored_order_count"],
                value["unscored_order_count"],
            ),
            "quality_candidate_countable": bool(
                value["settled_order_count"] > 0 and value["unsettled_order_count"] == 0
            ),
            "reason_counts": dict(sorted(value["reason_counts"].items())),
        }
        strategy_rows.append(row)
    best_by_net = max(strategy_rows, key=lambda row: row["net_pnl_usdc"], default=None)
    countable_candidates = [row for row in strategy_rows if row["quality_candidate_countable"]]
    best_countable = max(countable_candidates, key=lambda row: row["net_pnl_usdc"], default=None)
    strategy_comparison = {
        "schema_version": STRATEGY_REPORT_SCHEMA_VERSION,
        "strategy_count": len(strategy_rows),
        "best_strategy_id": (best_by_net or {}).get("strategy_id"),
        "best_strategy_net_pnl_usdc": (best_by_net or {}).get("net_pnl_usdc"),
        "best_settlement_scored_strategy_id": (best_countable or {}).get("strategy_id"),
        "best_settlement_scored_net_pnl_usdc": (best_countable or {}).get("net_pnl_usdc"),
        "countable_strategy_quality_candidate": best_countable or {},
        "countable_strategy_quality_candidate_status": (
            "COUNTABLE_SETTLED" if best_countable else "MISSING_SETTLED_SAMPLE"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "summary": summary,
        "by_strategy": strategy_rows,
        "strategy_comparison": strategy_comparison,
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
    strategy_rows = pnl.get("by_strategy") or []
    if strategy_rows:
        lines.extend(["", "## Strategies", ""])
        lines.extend(markdown_table(
            ["Strategy", "Family", "Orders", "Filled", "Opinions", "Spent", "Net P&L", "P&L Source"],
            [
                [
                    row.get("strategy_id"),
                    row.get("strategy_family"),
                    row.get("order_rows"),
                    row.get("filled_order_count"),
                    row.get("independent_opinion_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    row.get("pnl_source"),
                ]
                for row in strategy_rows
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


def build_strategy_summary_payload(pnl_payload, run_config=None, run_id=None, target_date=None, now=None):
    now = utc_now(now)
    return {
        "schema_version": STRATEGY_REPORT_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id or (pnl_payload or {}).get("run_id"),
        "target_date": ensure_date(target_date or (pnl_payload or {}).get("target_date")),
        "experiment_id": (run_config or {}).get("experiment_id"),
        "control_strategy_id": (run_config or {}).get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_registry": (run_config or {}).get("strategy_registry") or strategy_registry_payload(),
        "strategies": (pnl_payload or {}).get("by_strategy") or [],
        "comparison": (pnl_payload or {}).get("strategy_comparison") or {},
    }


def render_strategy_report(payload):
    comparison = payload.get("comparison") or {}
    strategies = payload.get("strategies") or []
    lines = [
        "# Taker Strategy Comparison Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Experiment ID: `{payload.get('experiment_id') or '-'}`",
        f"Control strategy: `{payload.get('control_strategy_id') or DEFAULT_CONTROL_STRATEGY_ID}`",
        "",
        "## Comparison",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Strategy count", comparison.get("strategy_count")],
            ["Best strategy by net P&L", comparison.get("best_strategy_id") or "-"],
            ["Best strategy net P&L", fmt_num(comparison.get("best_strategy_net_pnl_usdc"), 4)],
            ["Best settlement-scored strategy", comparison.get("best_settlement_scored_strategy_id") or "-"],
            ["Settlement-scored candidate status", comparison.get("countable_strategy_quality_candidate_status")],
        ],
    ))
    lines.extend(["", "## Strategies", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Family",
            "Orders",
            "Filled",
            "Opinions",
            "Settled",
            "Unsettled",
            "Spent",
            "Expected P&L",
            "Risk-Adj Exp P&L",
            "Settlement P&L",
            "MTM P&L",
            "Net P&L",
            "Realized - Expected",
            "Tail Fills",
            "Countable",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("order_rows"),
                row.get("filled_order_count"),
                row.get("independent_opinion_count"),
                row.get("settled_order_count"),
                row.get("unsettled_order_count"),
                fmt_num(row.get("spent_usdc"), 2),
                fmt_num(row.get("expected_pnl_usdc"), 4),
                fmt_num(row.get("risk_adjusted_expected_pnl_usdc"), 4),
                fmt_num(row.get("settlement_pnl_usdc"), 4),
                fmt_num(row.get("mark_to_market_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                fmt_num(row.get("realized_minus_expected_pnl_usdc"), 4),
                row.get("low_price_tail_fill_count"),
                str(row.get("quality_candidate_countable")).lower(),
            ]
            for row in strategies
        ],
    ))
    lines.append("")
    return "\n".join(lines)


def replay_input_key_payload(row):
    kind, value, value_hi = band_key(row)
    return {
        "target_date": row.get("target_date") or "",
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "range_label": row.get("range_label") or "",
        "bin_kind": kind or "",
        "bin_value": value,
        "bin_value_hi": value_hi,
        "clob_token_id": row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        "fair_probability": compact_float(row.get("fair_probability")),
        "best_ask": compact_float(first_present(row, "best_ask", "clob_best_ask")),
    }


def replay_input_key(row):
    return stable_hash(replay_input_key_payload(row), length=24)


def replay_input_rows_from_orders(order_rows):
    by_key = {}
    for row in order_rows or []:
        key = replay_input_key(row)
        if key not in by_key:
            by_key[key] = dict(row)
    return list(by_key.values())


def replay_tick_sort_key(row):
    timestamp = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    return (
        timestamp.isoformat() if timestamp else "",
        row.get("snapshot_id") or "",
        row.get("market_id") or "",
        row.get("event_slug") or "",
    )


def replay_input_ticks(replay_inputs):
    ticks = []
    current_key = None
    current_rows = []
    for row in sorted(replay_inputs or [], key=replay_tick_sort_key):
        key = (
            row.get("captured_at_utc") or row.get("generated_at_utc") or "",
            row.get("snapshot_id") or "",
        )
        if current_key is not None and key != current_key:
            ticks.append(current_rows)
            current_rows = []
        current_key = key
        current_rows.append(row)
    if current_rows:
        ticks.append(current_rows)
    return ticks


def strategy_filled_rows(order_rows, strategy_id):
    return [
        row for row in order_rows or []
        if strategy_id_for_row(row) == strategy_id and str(row.get("order_status") or "").upper() == "FILLED"
    ]


def cumulative_drawdown_usdc(rows):
    ordered = sorted(
        rows or [],
        key=lambda row: (
            row.get("generated_at_utc") or "",
            row.get("captured_at_utc") or "",
            row.get("order_id") or "",
        ),
    )
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for row in ordered:
        pnl = maybe_float(row.get("net_pnl_usdc"))
        if pnl is None:
            continue
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return round(drawdown, 6)


def source_mark_sign_flip_count(source_rows, scored_rows, strategy_id):
    source_marks = {}
    for row in source_rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        mark = maybe_float(row.get("mark_pnl_usdc"))
        if mark is None and row.get("pnl_source") == "mark_to_market":
            mark = maybe_float(row.get("net_pnl_usdc"))
        if mark is not None:
            source_marks[replay_input_key(row)] = mark
    count = 0
    for row in strategy_filled_rows(scored_rows, strategy_id):
        mark = source_marks.get(replay_input_key(row))
        settled = maybe_float(first_present(row, "settlement_pnl_usdc", "net_pnl_usdc"))
        if mark is not None and settled is not None and mark * settled < 0:
            count += 1
    return count


def strategy_concentration_summary(rows, strategy_id):
    filled = strategy_filled_rows(rows, strategy_id)
    by_market = defaultdict(float)
    by_token = defaultdict(float)
    by_cluster = defaultdict(float)
    by_opinion = Counter()
    total = 0.0
    low_tail = 0.0
    for row in filled:
        spent = maybe_float(row.get("total_spent_usdc")) or 0.0
        total += spent
        by_market[row.get("market_id") or "unknown"] += spent
        by_token[row.get("clob_token_id") or row.get("order_id") or "unknown"] += spent
        by_cluster[row.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(row)] += spent
        by_opinion[independent_opinion_key(row)] += 1
        if bool_value(row.get("low_price_tail"), False):
            low_tail += spent
    top_market_id, top_market_spent = max(by_market.items(), key=lambda item: item[1], default=("", 0.0))
    top_token_id, top_token_spent = max(by_token.items(), key=lambda item: item[1], default=("", 0.0))
    top_cluster_key, top_cluster_spent = max(by_cluster.items(), key=lambda item: item[1], default=("", 0.0))
    repeated_opinion_count = sum(max(0, count - 1) for count in by_opinion.values())
    return {
        "spent_usdc": round(total, 6),
        "top_market_id": top_market_id,
        "top_market_spent_usdc": round(top_market_spent, 6),
        "top_market_spend_share": compact_float(top_market_spent / total if total > 0 else 0.0),
        "top_token_id": top_token_id,
        "top_token_spent_usdc": round(top_token_spent, 6),
        "top_token_spend_share": compact_float(top_token_spent / total if total > 0 else 0.0),
        "top_adjacent_cluster_key": top_cluster_key,
        "top_adjacent_cluster_spent_usdc": round(top_cluster_spent, 6),
        "top_adjacent_cluster_spend_share": compact_float(top_cluster_spent / total if total > 0 else 0.0),
        "low_price_tail_spent_usdc": round(low_tail, 6),
        "low_price_tail_spend_share": compact_float(low_tail / total if total > 0 else 0.0),
        "repeated_opinion_count": repeated_opinion_count,
    }


def label_summary_for_target(labels_csv, target_date):
    target = ensure_date(target_date).isoformat()
    rows = [
        row for row in read_csv_rows(labels_csv, attach_diagnostics=True)
        if row.get("target_date") == target
    ]
    quality_counts = Counter(row.get("quality_grade") or "unknown" for row in rows)
    return {
        "target_date": target,
        "label_rows": len(rows),
        "complete_rows": quality_counts.get("complete", 0),
        "partial_rows": quality_counts.get("partial", 0),
        "quality_counts": dict(sorted(quality_counts.items())),
    }


def strategy_gate_for_bakeoff(
    strategy_row,
    scored_rows,
    source_rows,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
):
    strategy_id = strategy_row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    filled = strategy_filled_rows(scored_rows, strategy_id)
    settled = int(strategy_row.get("settled_order_count") or 0)
    unsettled = int(strategy_row.get("unsettled_order_count") or 0)
    unscored = int(strategy_row.get("unscored_order_count") or 0)
    clob_failures = int(strategy_row.get("clob_continuity_fail_count") or 0)
    mark_outliers = int(strategy_row.get("mark_sanity_outlier_count") or 0)
    spent = maybe_float(strategy_row.get("spent_usdc")) or 0.0
    net = maybe_float(strategy_row.get("net_pnl_usdc")) or 0.0
    roi = net / spent if spent > 0 else None
    drawdown = cumulative_drawdown_usdc(filled)
    sign_flips = source_mark_sign_flip_count(source_rows, scored_rows, strategy_id)
    concentration = strategy_concentration_summary(scored_rows, strategy_id)
    gates = [
        {
            "name": "min_settled_sample",
            "ok": settled >= int(min_settled_orders),
            "value": settled,
            "threshold": int(min_settled_orders),
        },
        {
            "name": "non_negative_settled_roi",
            "ok": settled >= int(min_settled_orders) and roi is not None and roi >= 0 and net >= 0,
            "value": compact_float(roi),
            "threshold": 0.0,
        },
        {
            "name": "max_drawdown",
            "ok": drawdown <= float(max_drawdown_usdc),
            "value": compact_float(drawdown),
            "threshold": float(max_drawdown_usdc),
        },
        {
            "name": "no_unresolved_orders",
            "ok": unsettled == 0 and unscored == 0,
            "value": unsettled + unscored,
            "threshold": 0,
        },
        {
            "name": "no_resolved_stale_mark_sign_flips",
            "ok": sign_flips == 0,
            "value": sign_flips,
            "threshold": 0,
        },
        {
            "name": "no_clob_continuity_failures",
            "ok": clob_failures == 0,
            "value": clob_failures,
            "threshold": 0,
        },
        {
            "name": "no_mark_sanity_outliers",
            "ok": mark_outliers == 0,
            "value": mark_outliers,
            "threshold": 0,
        },
    ]
    failed = [row["name"] for row in gates if not row["ok"]]
    return {
        "strategy_id": strategy_id,
        "strategy_family": strategy_row.get("strategy_family") or "unknown",
        "status": "PASS" if not failed else "BLOCK",
        "failed_gates": failed,
        "filled_order_count": int(strategy_row.get("filled_order_count") or 0),
        "settled_order_count": settled,
        "unsettled_order_count": unsettled,
        "unscored_order_count": unscored,
        "spent_usdc": compact_float(spent),
        "net_pnl_usdc": compact_float(net),
        "roi": compact_float(roi),
        "max_drawdown_usdc": compact_float(drawdown),
        "stale_mark_sign_flip_count": sign_flips,
        "clob_continuity_fail_count": clob_failures,
        "mark_sanity_outlier_count": mark_outliers,
        "concentration": concentration,
        "gates": gates,
    }


def paired_strategy_comparisons(strategy_rows, promotion_gates, control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID):
    by_strategy = {row.get("strategy_id"): row for row in strategy_rows or []}
    by_gate = {row.get("strategy_id"): row for row in promotion_gates or []}
    control = by_strategy.get(control_strategy_id) or {}
    control_spent = maybe_float(control.get("spent_usdc")) or 0.0
    control_net = maybe_float(control.get("net_pnl_usdc")) or 0.0
    control_roi = control_net / control_spent if control_spent > 0 else None
    comparisons = []
    for row in strategy_rows or []:
        strategy_id = row.get("strategy_id")
        if strategy_id == control_strategy_id:
            continue
        spent = maybe_float(row.get("spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc")) or 0.0
        roi = net / spent if spent > 0 else None
        comparisons.append({
            "control_strategy_id": control_strategy_id,
            "candidate_strategy_id": strategy_id,
            "candidate_strategy_family": row.get("strategy_family") or "unknown",
            "control_status": (by_gate.get(control_strategy_id) or {}).get("status"),
            "candidate_status": (by_gate.get(strategy_id) or {}).get("status"),
            "control_net_pnl_usdc": compact_float(control_net),
            "candidate_net_pnl_usdc": compact_float(net),
            "delta_net_pnl_usdc": compact_float(net - control_net),
            "control_roi": compact_float(control_roi),
            "candidate_roi": compact_float(roi),
            "delta_roi": compact_float(roi - control_roi) if roi is not None and control_roi is not None else None,
            "control_filled_order_count": int(control.get("filled_order_count") or 0),
            "candidate_filled_order_count": int(row.get("filled_order_count") or 0),
            "control_spent_usdc": compact_float(control_spent),
            "candidate_spent_usdc": compact_float(spent),
        })
    return comparisons


def render_bakeoff_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    strategies = pnl.get("by_strategy") or []
    gates = payload.get("promotion_gates") or []
    comparisons = payload.get("paired_comparisons") or []
    blockers = payload.get("blockers") or []
    gate_by_strategy = {row.get("strategy_id"): row for row in gates}
    lines = [
        "# Settlement-Scored Taker Strategy Bakeoff",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Source run: `{payload.get('source_run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Input orders: `{payload.get('input_orders_path')}`",
        f"Labels: `{payload.get('labels_csv')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Strategy count", summary.get("strategy_count")],
            ["Replay input rows", summary.get("replay_input_rows")],
            ["Replay ticks", summary.get("replay_tick_count")],
            ["Scored order rows", summary.get("scored_order_rows")],
            ["Label rows for date", (payload.get("label_summary") or {}).get("label_rows")],
            ["Blockers", len(blockers)],
        ],
    ))
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(markdown_table(
            ["Code", "Detail"],
            [[row.get("code"), row.get("detail")] for row in blockers],
        ))
    lines.extend(["", "## Strategy Results", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Family",
            "Filled",
            "Settled",
            "Unresolved",
            "Expected P&L",
            "Risk-Adj Exp P&L",
            "Net P&L",
            "ROI",
            "Drawdown",
            "Tail Spent",
            "Top Market Share",
            "Gate",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("filled_order_count"),
                row.get("settled_order_count"),
                row.get("unsettled_order_count"),
                fmt_num(row.get("expected_pnl_usdc"), 4),
                fmt_num(row.get("risk_adjusted_expected_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("roi"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("max_drawdown_usdc"), 4),
                fmt_num(row.get("low_price_tail_spent_usdc"), 2),
                fmt_num(
                    ((gate_by_strategy.get(row.get("strategy_id")) or {}).get("concentration") or {}).get(
                        "top_market_spend_share"
                    ),
                    4,
                ),
                (gate_by_strategy.get(row.get("strategy_id")) or {}).get("status"),
            ]
            for row in strategies
        ],
    ))
    if comparisons:
        lines.extend(["", "## Paired Against Control", ""])
        lines.extend(markdown_table(
            ["Candidate", "Status", "Delta Net P&L", "Delta ROI", "Candidate Spent", "Control Spent"],
            [
                [
                    row.get("candidate_strategy_id"),
                    row.get("candidate_status"),
                    fmt_num(row.get("delta_net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_roi"), 4),
                    fmt_num(row.get("candidate_spent_usdc"), 2),
                    fmt_num(row.get("control_spent_usdc"), 2),
                ]
                for row in comparisons
            ],
        ))
    lines.extend(["", "## Promotion Gates", ""])
    gate_rows = []
    for row in gates:
        gate_rows.append([
            row.get("strategy_id"),
            row.get("status"),
            ", ".join(row.get("failed_gates") or []) or "-",
            row.get("settled_order_count"),
            fmt_num(row.get("net_pnl_usdc"), 4),
            fmt_num(row.get("roi"), 4),
            fmt_num(row.get("max_drawdown_usdc"), 4),
            row.get("stale_mark_sign_flip_count"),
            row.get("clob_continuity_fail_count"),
            row.get("mark_sanity_outlier_count"),
        ])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Status",
            "Failed Gates",
            "Settled",
            "Net P&L",
            "ROI",
            "Drawdown",
            "Sign Flips",
            "CLOB Fails",
            "Mark Outliers",
        ],
        gate_rows,
    ))
    lines.append("")
    return "\n".join(lines)


def run_taker_strategy_bakeoff(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    budget_usdc=None,
    out_json=None,
    out_report=None,
    now=None,
    experiment_id=None,
    config=None,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
):
    now = utc_now(now)
    run_folder = Path(run_folder)
    labels_csv = Path(labels_csv)
    input_orders_path = run_folder / "orders_long.csv"
    source_rows = read_order_rows(input_orders_path)
    replay_inputs = replay_input_rows_from_orders(source_rows)
    run_config = read_json(run_folder / "run_config.json", {}) or {}
    source_summary = read_json(run_folder / "run_summary.json", {}) or {}
    target = ensure_date(
        run_config.get("target_date")
        or source_summary.get("target_date")
        or (source_rows[0].get("target_date") if source_rows else None)
        or run_folder.parent.name
    )
    source_run_id = (
        run_config.get("run_id")
        or source_summary.get("run_id")
        or (source_rows[0].get("run_id") if source_rows else None)
        or run_folder.name
    )
    base_config = {
        **DEFAULT_CONFIG,
        **(run_config.get("policy_config") or {}),
        **(config or {}),
    }
    budget = float(
        budget_usdc
        if budget_usdc is not None
        else run_config.get("budget_usdc")
        or ((source_summary.get("summary") or {}).get("budget_usdc"))
        or 100.0
    )
    strategy_specs = selected_strategy_specs(strategies, base_config=base_config)
    strategy_ids = [row["strategy_id"] for row in strategy_specs]
    experiment_id = experiment_id or default_experiment_id(target, strategy_ids)
    bakeoff_run_id = f"{source_run_id}-bakeoff"
    replay_ticks = replay_input_ticks(replay_inputs)
    generated_rows = []
    budget_ledger = []
    for strategy in strategy_specs:
        strategy_existing_fills = []
        for tick_rows in replay_ticks:
            rows, ledger = apply_taker_budget(
                tick_rows,
                strategy_existing_fills,
                strategy.get("budget_usdc") or budget,
                bakeoff_run_id,
                target,
                now,
                strategy["config"],
                strategy=strategy,
                experiment_id=experiment_id,
            )
            strategy_existing_fills.extend(
                row for row in rows
                if str(row.get("order_status") or "").upper() == "FILLED"
            )
            generated_rows.extend(rows)
            budget_ledger.extend(ledger)
    labels = load_settlement_labels(labels_csv)
    scored_rows, score_summary = score_orders_against_labels(generated_rows, labels)
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget) for item in strategy_specs)
    pnl_payload = build_pnl_payload(scored_rows, total_budget_usdc, bakeoff_run_id, target, now=now)
    label_summary = label_summary_for_target(labels_csv, target)
    promotion_gates = [
        strategy_gate_for_bakeoff(
            row,
            scored_rows,
            source_rows,
            min_settled_orders=min_settled_orders,
            max_drawdown_usdc=max_drawdown_usdc,
        )
        for row in pnl_payload.get("by_strategy") or []
    ]
    paired = paired_strategy_comparisons(
        pnl_payload.get("by_strategy") or [],
        promotion_gates,
        control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID,
    )
    blockers = []
    if not source_rows:
        blockers.append({
            "code": "missing_orders_tape",
            "detail": f"No orders_long.csv rows found at {input_orders_path}",
        })
    if label_summary["label_rows"] == 0:
        blockers.append({
            "code": "missing_target_date_labels",
            "detail": f"No settlement labels for {target.isoformat()} in {labels_csv}",
        })
    elif label_summary["complete_rows"] < label_summary["label_rows"]:
        blockers.append({
            "code": "partial_target_date_labels",
            "detail": (
                f"{label_summary['label_rows'] - label_summary['complete_rows']} of "
                f"{label_summary['label_rows']} settlement labels for {target.isoformat()} "
                "are partial-quality labels; do not promote from this bakeoff alone"
            ),
        })
    if score_summary.get("unmatched_filled_orders"):
        blockers.append({
            "code": "unmatched_filled_orders",
            "detail": (
                f"{score_summary['unmatched_filled_orders']} filled replay orders had no settlement label"
            ),
        })
    out_json = Path(out_json) if out_json else run_folder / "strategy_bakeoff.json"
    out_report = Path(out_report) if out_report else run_folder / "strategy_bakeoff.md"
    payload = {
        "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": bakeoff_run_id,
        "source_run_id": source_run_id,
        "target_date": target.isoformat(),
        "input_run_folder": str(run_folder),
        "input_orders_path": str(input_orders_path),
        "labels_csv": str(labels_csv),
        "output_json_path": str(out_json),
        "output_report_path": str(out_report),
        "experiment_id": experiment_id,
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_ids": strategy_ids,
        "budget_per_strategy_usdc": compact_float(budget),
        "budget_scope": "per_strategy",
        "strategy_registry": strategy_registry_payload(),
        "strategies": [
            {
                key: value
                for key, value in item.items()
                if key not in {"config"}
            }
            for item in strategy_specs
        ],
        "label_summary": label_summary,
        "score_summary": score_summary,
        "summary": {
            "strategy_count": len(strategy_specs),
            "source_order_rows": len(source_rows),
            "replay_input_rows": len(replay_inputs),
            "replay_tick_count": len(replay_ticks),
            "generated_order_rows": len(generated_rows),
            "scored_order_rows": len(scored_rows),
            "promotion_pass_count": sum(1 for row in promotion_gates if row.get("status") == "PASS"),
            "promotion_block_count": sum(1 for row in promotion_gates if row.get("status") != "PASS"),
        },
        "pnl": pnl_payload,
        "promotion_gates": promotion_gates,
        "paired_comparisons": paired,
        "budget_ledger": budget_ledger,
        "blockers": blockers,
    }
    write_json(out_json, payload)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(render_bakeoff_report(payload), encoding="utf-8")
    return payload


def first_numeric(*values, default=None):
    for value in values:
        number = maybe_float(value)
        if number is not None:
            return number
    return default


def first_int(*values, default=0):
    number = first_numeric(*values, default=None)
    return int(number) if number is not None else int(default)


def reported_taker_pnl_summary(run_summary=None, daily_pnl=None):
    run_summary = run_summary or {}
    daily_pnl = daily_pnl or {}
    summary = run_summary.get("summary") or {}
    run_pnl = (run_summary.get("pnl") or {}).get("summary") or {}
    daily_summary = daily_pnl.get("summary") or {}
    return {
        "reported_filled_order_count": first_int(
            summary.get("cumulative_filled_orders"),
            run_pnl.get("filled_order_count"),
            daily_summary.get("filled_order_count"),
        ),
        "reported_unsettled_order_count": first_int(
            run_pnl.get("unsettled_order_count"),
            daily_summary.get("unsettled_order_count"),
        ),
        "reported_settled_order_count": first_int(
            run_pnl.get("settled_order_count"),
            daily_summary.get("settled_order_count"),
        ),
        "reported_net_pnl_usdc": first_numeric(
            summary.get("cumulative_net_pnl_usdc"),
            run_pnl.get("net_pnl_usdc"),
            daily_summary.get("net_pnl_usdc"),
        ),
        "reported_mark_to_market_pnl_usdc": first_numeric(
            run_pnl.get("mark_to_market_pnl_usdc"),
            daily_summary.get("mark_to_market_pnl_usdc"),
        ),
        "reported_settlement_pnl_usdc": first_numeric(
            run_pnl.get("settlement_pnl_usdc"),
            daily_summary.get("settlement_pnl_usdc"),
        ),
    }


def reconciliation_warning(code, detail, **values):
    out = {"code": code, "detail": detail}
    for key, value in values.items():
        if isinstance(value, float):
            out[key] = compact_float(value)
        else:
            out[key] = value
    return out


def build_settlement_reconciliation(final_summary, reported_summary, threshold_usdc=RECONCILIATION_WARNING_USDC):
    final_summary = final_summary or {}
    reported_summary = reported_summary or {}
    settled_orders = int(final_summary.get("settled_order_count") or 0)
    unsettled_orders = int(final_summary.get("unsettled_order_count") or 0)
    final_net = first_numeric(final_summary.get("net_pnl_usdc"), default=0.0)
    final_settlement = first_numeric(final_summary.get("settlement_pnl_usdc"), default=0.0)
    reported_net = first_numeric(reported_summary.get("reported_net_pnl_usdc"), default=None)
    reported_mtm = first_numeric(reported_summary.get("reported_mark_to_market_pnl_usdc"), default=None)
    reported_unsettled = int(reported_summary.get("reported_unsettled_order_count") or 0)
    gross_cost = first_numeric(final_summary.get("gross_cost_usdc"), default=0.0)
    warnings = []

    if settled_orders > 0 and reported_unsettled > 0:
        warnings.append(reconciliation_warning(
            "reported_unsettled_after_labels_available",
            "Run summary still treated filled orders as unsettled after finalized labels were available.",
            reported_unsettled_order_count=reported_unsettled,
            finalized_settled_order_count=settled_orders,
        ))
    if settled_orders > 0 and reported_mtm is not None:
        diff_mtm = final_net - reported_mtm
        if abs(diff_mtm) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "reported_mark_to_market_diverges_from_settlement",
                "Reported mark-to-market P&L differs materially from settlement-finalized P&L.",
                difference_usdc=diff_mtm,
                reported_mark_to_market_pnl_usdc=reported_mtm,
                finalized_net_pnl_usdc=final_net,
            ))
        if gross_cost > 0 and abs(reported_mtm) > max(threshold_usdc, gross_cost * 2.0):
            warnings.append(reconciliation_warning(
                "resolved_mark_to_market_outlier",
                "Resolved-day mark-to-market was too large relative to filled cost; treat it as stale CLOB mark evidence.",
                reported_mark_to_market_pnl_usdc=reported_mtm,
                finalized_gross_cost_usdc=gross_cost,
            ))
        if final_settlement != 0 and reported_mtm * final_settlement < 0 and abs(diff_mtm) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "resolved_mark_to_market_sign_flip",
                "Reported mark-to-market and settlement-finalized P&L have opposite signs.",
                reported_mark_to_market_pnl_usdc=reported_mtm,
                settlement_pnl_usdc=final_settlement,
            ))
    if settled_orders > 0 and reported_net is not None:
        diff_net = final_net - reported_net
        if abs(diff_net) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "reported_net_pnl_diverges_from_settlement",
                "Reported net P&L differs materially from settlement-finalized P&L.",
                difference_usdc=diff_net,
                reported_net_pnl_usdc=reported_net,
                finalized_net_pnl_usdc=final_net,
            ))

    if settled_orders > 0 and unsettled_orders == 0:
        preferred = "settlement_finalization"
    elif settled_orders > 0:
        preferred = "mixed_settlement_and_unscored"
    elif reported_mtm is not None:
        preferred = "mark_to_market"
    else:
        preferred = "unscored"
    return {
        "status": "WARN" if warnings else "PASS",
        "preferred_pnl_source": preferred,
        "large_difference_threshold_usdc": threshold_usdc,
        "reported": reported_summary,
        "finalized": {
            "settled_order_count": settled_orders,
            "unsettled_order_count": unsettled_orders,
            "net_pnl_usdc": compact_float(final_net),
            "settlement_pnl_usdc": compact_float(final_settlement),
        },
        "differences": {
            "net_minus_reported_net_usdc": (
                compact_float(final_net - reported_net) if reported_net is not None else None
            ),
            "net_minus_reported_mark_to_market_usdc": (
                compact_float(final_net - reported_mtm) if reported_mtm is not None else None
            ),
        },
        "warnings": warnings,
    }


def render_settlement_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    pnl_summary = pnl.get("summary") or {}
    reconciliation = payload.get("reconciliation") or {}
    warnings = reconciliation.get("warnings") or []
    lines = [
        "# Taker Settlement Finalization Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Source run folder: `{payload.get('run_folder')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Filled orders", pnl_summary.get("filled_order_count")],
            ["Settled / unsettled", f"{pnl_summary.get('settled_order_count')} / {pnl_summary.get('unsettled_order_count')}"],
            ["P&L source", summary.get("pnl_source")],
            ["Reconciliation status", reconciliation.get("status")],
            ["Warnings", len(warnings)],
            ["Labels CSV", payload.get("labels_csv")],
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
            ["Finalized net P&L", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
            ["Reported net P&L", fmt_num(summary.get("reported_net_pnl_usdc"), 4)],
            ["Reported mark-to-market P&L", fmt_num(summary.get("reported_mark_to_market_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## Reconciliation", ""])
    lines.extend(markdown_table(
        ["Check", "Value"],
        [
            ["Status", reconciliation.get("status")],
            ["Net minus reported net", fmt_num((reconciliation.get("differences") or {}).get("net_minus_reported_net_usdc"), 4)],
            [
                "Net minus reported MTM",
                fmt_num((reconciliation.get("differences") or {}).get("net_minus_reported_mark_to_market_usdc"), 4),
            ],
        ],
    ))
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(markdown_table(
            ["Code", "Detail"],
            [[row.get("code"), row.get("detail")] for row in warnings],
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
    if pnl.get("by_strategy"):
        lines.extend(["", "## Strategies", ""])
        lines.extend(markdown_table(
            ["Strategy", "Filled", "Settled", "Unsettled", "Spent", "Settlement P&L", "Net P&L", "Countable"],
            [
                [
                    row.get("strategy_id"),
                    row.get("filled_order_count"),
                    row.get("settled_order_count"),
                    row.get("unsettled_order_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("settlement_pnl_usdc"), 4),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    str(row.get("quality_candidate_countable")).lower(),
                ]
                for row in pnl.get("by_strategy") or []
            ],
        ))
    lines.append("")
    return "\n".join(lines)


def finalize_taker_run(run_folder, labels_csv=DEFAULT_LABELS_CSV, now=None):
    run_folder = Path(run_folder)
    order_path = run_folder / "orders_long.csv"
    if not order_path.exists():
        raise FileNotFoundError(f"missing taker orders tape: {order_path}")
    now = utc_now(now)
    run_summary = read_json(run_folder / "run_summary.json", {}) or {}
    daily_pnl = read_json(run_folder / "daily_pnl.json", {}) or {}
    target_date = (
        run_summary.get("target_date")
        or daily_pnl.get("target_date")
        or run_folder.parent.name
    )
    run_id = run_summary.get("run_id") or daily_pnl.get("run_id") or run_folder.name
    summary = run_summary.get("summary") or {}
    daily_summary = daily_pnl.get("summary") or {}
    budget_usdc = first_numeric(
        summary.get("budget_usdc"),
        daily_summary.get("budget_usdc"),
        run_summary.get("budget_usdc"),
        default=0.0,
    )

    labels = load_settlement_labels(labels_csv)
    raw_orders = read_order_rows(order_path)
    scored_orders, label_summary = score_orders_against_labels(raw_orders, labels)
    pnl_payload = build_pnl_payload(scored_orders, budget_usdc, run_id, target_date, now=now)
    reported_summary = reported_taker_pnl_summary(run_summary, daily_pnl)
    reconciliation = build_settlement_reconciliation(pnl_payload.get("summary") or {}, reported_summary)
    settled_orders_path = run_folder / "settled_orders_long.csv"
    settled_pnl_path = run_folder / "settled_pnl.json"
    settled_report_path = run_folder / "settled_report.md"
    settled_strategy_summary_path = run_folder / "settled_strategy_summary.json"
    settled_strategy_report_path = run_folder / "settled_strategy_report.md"
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=read_json(run_folder / "run_config.json", {}) or {},
        run_id=run_id,
        target_date=target_date,
        now=now,
    )
    final_summary = {
        **(pnl_payload.get("summary") or {}),
        "pnl_source": reconciliation.get("preferred_pnl_source"),
        "reconciliation_status": reconciliation.get("status"),
        "reconciliation_warning_count": len(reconciliation.get("warnings") or []),
        "settled_orders_path": str(settled_orders_path),
        "settled_report_path": str(settled_report_path),
        "settled_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_strategy_report_path": str(settled_strategy_report_path),
        **reported_summary,
    }
    payload = {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "run_folder": str(run_folder),
        "orders_path": str(order_path),
        "settled_orders_path": str(settled_orders_path),
        "settled_pnl_path": str(settled_pnl_path),
        "settled_report_path": str(settled_report_path),
        "settled_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_strategy_report_path": str(settled_strategy_report_path),
        "labels_csv": str(Path(labels_csv)),
        "label_summary": label_summary,
        "summary": final_summary,
        "pnl": pnl_payload,
        "strategy_summary": strategy_summary,
        "reconciliation": reconciliation,
        "warnings": reconciliation.get("warnings") or [],
    }
    write_csv_rows(settled_orders_path, ORDER_COLUMNS, scored_orders)
    write_json(settled_pnl_path, payload)
    write_json(settled_strategy_summary_path, strategy_summary)
    settled_report_path.write_text(render_settlement_report(payload), encoding="utf-8")
    settled_strategy_report_path.write_text(render_strategy_report(strategy_summary), encoding="utf-8")
    return payload


def taker_run_folders(runs_root=DEFAULT_RUNS_ROOT, target_date=None):
    root = Path(runs_root)
    if target_date:
        pattern_root = root / ensure_date(target_date).isoformat()
        candidates = sorted(pattern_root.glob("*"))
    else:
        candidates = sorted(root.glob("*/*"))
    return [path for path in candidates if path.is_dir() and (path / "orders_long.csv").exists()]


def finalize_taker_runs(
    target_date=None,
    runs_root=DEFAULT_RUNS_ROOT,
    labels_csv=DEFAULT_LABELS_CSV,
    run_folder=None,
    now=None,
):
    now = utc_now(now)
    folders = [Path(run_folder)] if run_folder else taker_run_folders(runs_root, target_date=target_date)
    payloads = [finalize_taker_run(folder, labels_csv=labels_csv, now=now) for folder in folders]
    return {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat() if target_date else None,
        "run_count": len(payloads),
        "runs": [
            {
                "run_id": payload.get("run_id"),
                "target_date": payload.get("target_date"),
                "run_folder": payload.get("run_folder"),
                "settled_pnl_path": payload.get("settled_pnl_path"),
                "settled_report_path": payload.get("settled_report_path"),
                "net_pnl_usdc": (payload.get("summary") or {}).get("net_pnl_usdc"),
                "settled_order_count": (payload.get("summary") or {}).get("settled_order_count"),
                "unsettled_order_count": (payload.get("summary") or {}).get("unsettled_order_count"),
                "reconciliation_status": (payload.get("reconciliation") or {}).get("status"),
            }
            for payload in payloads
        ],
    }


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
    experiment_id=DEFAULT_EXPERIMENT_ID,
    strategy_specs=None,
    registry=None,
):
    strategy_specs = strategy_specs or selected_strategy_specs(None, base_config=config, registry=registry)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat(),
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "budget_usdc": float(budget_usdc),
        "budget_scope": "per_strategy",
        "markets": [spec.id for spec in selected_specs(markets)],
        "run_folder": str(run_folder),
        "snapshots_root": str(snapshots_root),
        "observation_status_path": str(observation_status_path),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "policy_config": config,
        "experiment_id": experiment_id,
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_ids": [item.get("strategy_id") for item in strategy_specs],
        "strategy_registry": strategy_registry_payload(registry=registry),
        "strategies": [
            {
                key: value
                for key, value in item.items()
                if key not in {"config"}
            }
            for item in strategy_specs
        ],
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
    strategies=None,
    experiment_id=None,
    strategy_registry=None,
):
    now = utc_now(now)
    target = ensure_date(target_date)
    config = {**DEFAULT_CONFIG, **(config or {})}
    strategy_specs = selected_strategy_specs(strategies, base_config=config, registry=strategy_registry)
    strategy_ids = [item["strategy_id"] for item in strategy_specs]
    experiment_id = experiment_id or default_experiment_id(target, strategy_ids)
    if run_id is None:
        if strategy_ids == [DEFAULT_CONTROL_STRATEGY_ID] and experiment_id == DEFAULT_EXPERIMENT_ID:
            run_id = default_run_id(target, config=config)
        else:
            run_id = default_run_id(target, config={
                **config,
                "experiment_id": experiment_id,
                "strategy_ids": strategy_ids,
            })
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
    new_rows = []
    budget_ledger = []
    for strategy in strategy_specs:
        strategy_existing_rows = [
            row for row in existing_rows
            if strategy_id_for_row(row) == strategy["strategy_id"]
        ]
        strategy_rows, strategy_ledger = apply_taker_budget(
            input_rows,
            strategy_existing_rows,
            strategy.get("budget_usdc") or budget_usdc,
            run_id,
            target,
            now,
            strategy["config"],
            strategy=strategy,
            experiment_id=experiment_id,
        )
        new_rows.extend(strategy_rows)
        budget_ledger.extend(strategy_ledger)
    all_rows = score_orders([*existing_rows, *new_rows], snapshots_root=snapshots_root, ledger_root=ledger_root, now=now)
    write_csv_rows(order_path, ORDER_COLUMNS, all_rows)
    tape_integrity = tape_integrity_summary(order_path, len(all_rows), "orders_long")
    append_jsonl(run_folder / "budget_ledger.jsonl", budget_ledger)
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget_usdc) for item in strategy_specs)
    pnl_payload = build_pnl_payload(all_rows, total_budget_usdc, run_id, target, now=now)
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
        experiment_id=experiment_id,
        strategy_specs=strategy_specs,
        registry=strategy_registry,
    )
    write_json(run_folder / "run_config.json", run_config)
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=run_config,
        run_id=run_id,
        target_date=target,
        now=now,
    )
    write_json(run_folder / "strategy_summary.json", strategy_summary)
    strategy_report_path = run_folder / "strategy_report.md"
    strategy_report_path.write_text(render_strategy_report(strategy_summary), encoding="utf-8")

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
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "strategy_count": len(strategy_specs),
        "strategy_ids": strategy_ids,
        "budget_usdc": round(total_budget_usdc, 6),
        "budget_per_strategy_usdc": round(float(budget_usdc), 6),
        "budget_scope": "per_strategy",
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
        "mode": "paper-taker-multi-arm" if len(strategy_specs) > 1 else "paper-taker",
        "experiment_id": experiment_id,
        "run_folder": str(run_folder),
        "run_config_path": str(run_folder / "run_config.json"),
        "orders_path": str(order_path),
        "budget_ledger_path": str(run_folder / "budget_ledger.jsonl"),
        "daily_pnl_path": str(run_folder / "daily_pnl.json"),
        "run_report_path": str(run_folder / "run_report.md"),
        "strategy_summary_path": str(run_folder / "strategy_summary.json"),
        "strategy_report_path": str(strategy_report_path),
        "summary": summary,
        "config": config,
        "strategy_registry": strategy_registry_payload(strategy_registry),
        "strategies": run_config.get("strategies"),
        "strategy_summary": strategy_summary,
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
    with keep_system_awake("weather taker bot loop"):
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


def finalize_main(argv=None):
    parser = argparse.ArgumentParser(description="Finalize taker-bot paper P&L against settled labels.")
    parser.add_argument("--date", default=None, help="Target market date to finalize, YYYY-MM-DD.")
    parser.add_argument("--run-folder", default=None, help="Finalize one taker run folder.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    args = parser.parse_args(argv)
    payload = finalize_taker_runs(
        target_date=args.date,
        runs_root=Path(args.runs_root),
        labels_csv=Path(args.labels_csv),
        run_folder=Path(args.run_folder) if args.run_folder else None,
        now=args.now,
    )
    print(f"Taker finalization: {payload['run_count']} run(s) finalized")
    for row in payload["runs"]:
        print(
            f"- {row['run_id']} {row['target_date']}: "
            f"net={row['net_pnl_usdc']} USDC, "
            f"settled/unsettled={row['settled_order_count']}/{row['unsettled_order_count']}, "
            f"reconciliation={row['reconciliation_status']} -> {row['settled_pnl_path']}"
        )
    return payload


def bakeoff_main(argv=None):
    parser = argparse.ArgumentParser(description="Run a settlement-scored taker strategy bakeoff.")
    parser.add_argument("--run-folder", required=True, help="Taker run folder containing orders_long.csv.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--strategies", default=DEFAULT_BAKEOFF_STRATEGIES)
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--budget-usdc", type=float, default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-report", default=None)
    parser.add_argument("--now", default=None, help="Testing/replay timestamp.")
    parser.add_argument("--min-settled-orders", type=int, default=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS)
    parser.add_argument("--max-drawdown-usdc", type=float, default=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC)
    parser.add_argument("--config", action="append", default=[], help="Taker bot config override, key=value.")
    args = parser.parse_args(argv)
    payload = run_taker_strategy_bakeoff(
        Path(args.run_folder),
        labels_csv=Path(args.labels_csv),
        strategies=args.strategies,
        budget_usdc=args.budget_usdc,
        out_json=Path(args.out_json) if args.out_json else None,
        out_report=Path(args.out_report) if args.out_report else None,
        now=args.now,
        experiment_id=args.experiment_id,
        config=parse_config_overrides(args.config),
        min_settled_orders=args.min_settled_orders,
        max_drawdown_usdc=args.max_drawdown_usdc,
    )
    summary = payload["summary"]
    print(
        "Taker strategy bakeoff: "
        f"{summary['strategy_count']} strategy arm(s), "
        f"{summary['promotion_pass_count']} pass, "
        f"{summary['promotion_block_count']} block -> {payload['output_json_path']}"
    )
    return payload


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "finalize":
        return finalize_main(raw_argv[1:])
    if raw_argv and raw_argv[0] == "bakeoff":
        return bakeoff_main(raw_argv[1:])
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
    parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated taker strategy IDs to run as isolated paper arms.",
    )
    parser.add_argument("--experiment-id", default=None, help="Stable experiment ID for multi-arm attribution.")
    parser.add_argument("--fresh", action="store_true", help="Start a fresh run folder instead of appending daily state.")
    parser.add_argument("--loop", action="store_true", help="Run repeatedly until end of market day or --until-utc.")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--until-utc", default=None)
    parser.add_argument("--max-ticks", type=int, default=None)
    parser.add_argument("--ledger-root", default=None)
    args = parser.parse_args(raw_argv)

    common = {
        "markets": args.markets,
        "runs_root": Path(args.runs_root),
        "snapshots_root": Path(args.snapshots_root),
        "run_id": args.run_id,
        "config": parse_config_overrides(args.config),
        "ledger_root": Path(args.ledger_root) if args.ledger_root else None,
        "observation_status_path": Path(args.observation_status),
        "strategies": args.strategies,
        "experiment_id": args.experiment_id,
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
