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

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
