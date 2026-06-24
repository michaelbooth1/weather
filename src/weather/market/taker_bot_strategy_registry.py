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
from weather.market.taker_edge_permission import DEFAULT_TAKER_EDGE_PERMISSION_MAP
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
COUNTERFACTUAL_TAPE_SCHEMA_VERSION = "taker_counterfactual_tape_v0.1"
POLICY_VERSION = "taker_bot_policy_v0.1"
DEFAULT_RUNS_ROOT = data_path() / "taker_runs"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LABELS_CSV = data_path() / "backtest" / "market_day_labels.csv"
COUNTERFACTUAL_TAPE_FILENAME = "counterfactual_orders_long.csv"
SETTLED_COUNTERFACTUAL_TAPE_FILENAME = "settled_counterfactual_orders_long.csv"
RECONCILIATION_WARNING_USDC = 1.0
SETTLEMENT_PNL_SOURCES = {"settlement", "settlement_finalized"}
DEFAULT_CONTROL_STRATEGY_ID = "raw_edge_control"
ACTIVE_DEFAULT_STRATEGY_ID = "low_price_tail_capped"
ACTIVE_DEFAULT_STRATEGY_CANARY_STARTED_DATE = "2026-06-21"
DEFAULT_EXPERIMENT_ID = "default_taker_strategy_experiment"
DEFAULT_TAKER_MODEL_VARIANT_BASKET = ",".join([
    "served_current",
    "dynamic_source_state",
    "exact_winner_catchup",
    "continuous_density",
    "clob_overlay",
])
DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS = 1
DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC = 100.0
DEFAULT_CANARY_MIN_SETTLED_ORDERS = 5
DEFAULT_CANARY_MIN_COMPLETE_LABEL_DAYS = 3
DEFAULT_PROMOTION_MIN_SETTLED_ORDERS = DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS
DEFAULT_PROMOTION_MIN_SETTLED_MARKETS = 1
DEFAULT_PROMOTION_MIN_SETTLED_NET_PNL_USDC = 0.0
DEFAULT_PROMOTION_MIN_SETTLED_EXPECTED_PNL_USDC = 0.0
DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION = 0.5

DEFAULT_CONFIG = {
    "policy_version": POLICY_VERSION,
    "min_edge": 0.03,
    "max_order_usdc": 10.0,
    "max_position_per_token_usdc": 10.0,
    "max_daily_positions": 50,
    "taker_fee_rate": 0.05,
    "taker_fee_model": "polymarket_symmetric_price_v1",
    "taker_fee_market_category": "weather",
    "taker_fee_effective_date": "2026-03-30",
    "taker_fee_provenance_url": "https://docs.polymarket.us/fees",
    "maker_fee_rate": 0.0,
    "executable_depth_model": "top_of_book_plus_1pct_depth_v1",
    "executable_depth_slippage_bps": 100.0,
    "executable_depth_haircut": 1.0,
    "two_sided_real_no_book_required_for_promotion": True,
    "two_sided_real_no_book_max_age_seconds": 120.0,
    "two_sided_real_no_book_min_ask_size": 0.0,
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
    "current_high_trust_gate_enabled": True,
    "current_high_trust_gate_start_hour_local": 0,
    "current_high_trust_gate_action": "deny_aggressive",
    "current_high_trust_missing_blocks": True,
    "current_high_trust_gate_size_multiplier": 0.25,
    "current_high_trust_gate_aggressive_min_edge": 0.08,
    "current_high_trust_gate_aggressive_max_price": 0.20,
    "current_high_trust_gate_lockin_distance": 1.0,
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
    "bad_tail_no_go_enabled": True,
    "bad_tail_no_go_low_price_tail_enabled": True,
    "bad_tail_no_go_low_price_tail_max_price": 0.05,
    "bad_tail_no_go_warm_tail_enabled": True,
    "bad_tail_no_go_block_strategy_families": "*",
    "bad_tail_no_go_allow_strategy_families": "",
    "bad_tail_no_go_allow_strategy_ids": "",
    "bad_tail_no_go_allow_slice_ids": "",
    "require_clob_continuity": False,
    "max_mark_sanity_ratio": 3.0,
    "active_strategy_lifecycle": "",
    "active_strategy_canary_started_date": ACTIVE_DEFAULT_STRATEGY_CANARY_STARTED_DATE,
    "canary_min_settled_orders": DEFAULT_CANARY_MIN_SETTLED_ORDERS,
    "canary_min_complete_label_days": DEFAULT_CANARY_MIN_COMPLETE_LABEL_DAYS,
    "canary_missing_settlement_blocks_after_age_days": 1,
    "canary_require_after_fee_pnl": True,
    "counterfactual_tape_enabled": True,
    "counterfactual_strategies": "",
    "counterfactual_retention_days": 14,
    "taker_model_variant_basket": DEFAULT_TAKER_MODEL_VARIANT_BASKET,
    "taker_model_variant_include_missing": False,
    "promotion_min_settled_orders": DEFAULT_PROMOTION_MIN_SETTLED_ORDERS,
    "promotion_min_settled_markets": DEFAULT_PROMOTION_MIN_SETTLED_MARKETS,
    "promotion_min_settled_net_pnl_usdc": DEFAULT_PROMOTION_MIN_SETTLED_NET_PNL_USDC,
    "promotion_min_settled_expected_pnl_usdc": DEFAULT_PROMOTION_MIN_SETTLED_EXPECTED_PNL_USDC,
    "promotion_min_independent_target_days": 3,
    "promotion_min_independent_markets": 2,
    "promotion_cluster_alpha": 0.05,
    "promotion_max_tail_fill_fraction": DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION,
    "canary_max_top_market_spend_share": 1.0,
    "canary_max_repeated_opinion_count": 0,
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
    "weak_slot_guard_enabled": True,
    "weak_slot_guard_report_path": "",
    "hourly_gate_report_path": "",
    "weak_slot_guard_slot_minutes": "",
    "weak_slot_guard_hours": "7,8,9",
    "weak_slot_guard_block_statuses": "BLOCK",
    "weak_slot_guard_block_strategy_families": "*",
    "weak_slot_guard_allow_strategy_families": "",
    "weak_slot_guard_allow_strategy_ids": "",
    "market_centered_warm_tail_guard_enabled": True,
    "market_centered_warm_tail_min_distance": 1.0,
    "market_centered_warm_tail_block_strategy_families": "*",
    "market_centered_warm_tail_allow_strategy_families": "",
    "market_centered_warm_tail_allow_strategy_ids": "",
    "market_centered_warm_tail_max_notional_usdc": 0.5,
    "market_centered_warm_tail_require_risk_adjusted": True,
    "market_centered_warm_tail_min_risk_adjusted_edge": 0.03,
    "market_centered_warm_tail_require_clob_continuity": True,
    "max_same_snapshot_adjacent_cluster_fills": 0,
    "snapshot_cadence_quality_enabled": True,
    "snapshot_cadence_missing_blocks": True,
    "snapshot_cadence_missing_allow_strategy_families": "",
    "snapshot_cadence_missing_allow_strategy_ids": "",
    "max_snapshot_cadence_gap_seconds": 900.0,
    "snapshot_cadence_stale_model_seconds": 900.0,
    "snapshot_cadence_confidence_haircut": 0.75,
    "snapshot_cadence_degraded_permission": "deny",
    "taker_edge_permission_enabled": True,
    "taker_edge_permission_map_path": str(DEFAULT_TAKER_EDGE_PERMISSION_MAP),
    "taker_edge_permission_missing_map_blocks": True,
    "calibrated_entry_enabled": True,
    "calibrated_sizing_enabled": True,
    "min_after_cost_ev_per_share": 0.0,
    "market_no_trade_precondition_enabled": True,
    "adverse_selection_edge_cap_enabled": True,
    "adverse_selection_edge_cap": 0.30,
    "adverse_selection_cap_min_skill_weight": 0.5,
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
    "fade_overpriced": {
        "strategy_id": "fade_overpriced",
        "strategy_family": "two_sided",
        "status": "shadow",
        "owner": "weather.market.taker_bot",
        "assignment_rule": "shared_inputs_full_shadow",
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "description": (
            "Two-sided probe (item 253): also buys the NO token of an over-priced "
            "band (fair_no - no_ask >= min_edge) under the same gates as the YES "
            "side, as a tiny settlement-scored shadow arm."
        ),
        "config_overrides": {
            "two_sided_enabled": True,
            "min_edge": 0.08,
            "max_order_usdc": 1.0,
            "max_position_per_token_usdc": 1.0,
            "max_daily_positions": 12,
            "max_market_notional_usdc": 5.0,
            "max_repeated_opinion_fills": 1,
            "risk_adjusted_entry_enabled": True,
            "min_risk_adjusted_edge": 0.03,
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
    "fade_overpriced",
    "winner_centered_or_adjacent",
    "current_high_lockin",
    "late_day_liquidity_filtered",
])

ORDER_COLUMNS = [
    "schema_version",
    "policy_version",
    "policy_hash",
    "model_variant_id",
    "model_variant_family",
    "model_variant_role",
    "model_variant_basket_id",
    "model_variant_basket_size",
    "model_variant_probability",
    "model_variant_probability_source",
    "model_variant_prediction_generated_at_utc",
    "served_model_version",
    "model_artifact_path",
    "model_artifact_hash",
    "model_feature_schema",
    "model_runtime_identity",
    "experiment_id",
    "strategy_id",
    "strategy_family",
    "strategy_status",
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
    "clob_yes_token_id",
    "clob_no_token_id",
    "clob_token_id",
    "side",
    "action",
    "order_status",
    "reason_code",
    "reason_detail",
    "fair_probability",
    "best_bid",
    "best_ask",
    "no_best_bid",
    "no_best_ask",
    "no_bid_size_at_best",
    "no_ask_size_at_best",
    "no_ask_depth_1pct",
    "no_book_source",
    "no_book_captured_at_utc",
    "no_book_age_seconds",
    "no_book_fresh",
    "real_no_book_depth_eligible",
    "market_mid",
    "edge",
    "expected_profit_per_share",
    "calibrated_model_probability",
    "market_implied_probability",
    "calibrated_fair_probability",
    "calibrated_fair",
    "taker_skill_weight",
    "calibrated_edge",
    "calibrated_expected_profit_per_share",
    "calibrated_after_fee_edge",
    "after_cost_ev_per_share",
    "entry_ev_per_share",
    "taker_edge_permission",
    "taker_edge_permission_reason",
    "taker_edge_permission_record_key",
    "taker_edge_permission_evidence_status",
    "taker_edge_permission_sample_size",
    "taker_edge_permission_independent_days",
    "taker_edge_permission_market_count",
    "taker_edge_permission_after_fee_skill",
    "taker_edge_permission_hit_rate",
    "market_benchmark_precondition",
    "market_benchmark_recommendation",
    "adverse_selection_status",
    "adverse_selection_reason",
    "adverse_selection_edge_cap",
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
    "market_modal_band_key",
    "market_modal_probability",
    "market_modal_band_distance",
    "market_centered_warm_tail",
    "warm_tail_guard_status",
    "warm_tail_guard_reason",
    "bad_tail_no_go_status",
    "bad_tail_no_go_action",
    "bad_tail_no_go_slice_id",
    "bad_tail_no_go_reason",
    "weak_slot_gate_status",
    "weak_slot_gate_reason",
    "weak_slot_gate_source",
    "current_high_band_distance",
    "adjacent_bin_cluster_key",
    "market_notional_before_usdc",
    "adjacent_cluster_notional_before_usdc",
    "low_price_tail_notional_before_usdc",
    "market_centered_warm_tail_notional_before_usdc",
    "same_snapshot_adjacent_cluster_fill_count_before",
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
    "fee_model_version",
    "fee_model_name",
    "fee_market_category",
    "fee_rate",
    "fee_effective_date",
    "fee_provenance_url",
    "pnl_fee_basis",
    "executable_depth_model_version",
    "executable_depth_mode",
    "top_of_book_size",
    "executable_depth_size",
    "executable_depth_1pct_size",
    "frictionless_fill_price",
    "frictionless_notional_usdc",
    "executable_fill_price",
    "slippage_price_impact_bps",
    "slippage_usdc",
    "expected_profit_after_friction_per_share",
    "gross_pnl_usdc",
    "fee_pnl_usdc",
    "slippage_pnl_usdc",
    "executable_net_pnl_usdc",
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
    "current_high_trust_state_present",
    "current_high_trusted",
    "current_high_guard_reason",
    "current_high_trust_gate_status",
    "current_high_trust_gate_action",
    "current_high_trust_gate_reason",
    "current_high_trust_gate_aggressive",
    "current_high_trust_gate_size_multiplier",
    "source_fresh",
    "source_freshness_state",
    "snapshot_cadence_state_present",
    "snapshot_cadence",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_max_gap_seconds",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_reason",
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

COUNTERFACTUAL_ORDER_COLUMNS = [
    *ORDER_COLUMNS,
    "counterfactual_schema_version",
    "counterfactual_id",
    "counterfactual_source",
    "counterfactual_strategy_set",
    "counterfactual_action",
    "counterfactual_order_status",
    "counterfactual_reason_code",
    "counterfactual_reason_detail",
    "counterfactual_requested_notional_usdc",
    "counterfactual_fill_size",
    "counterfactual_total_spent_usdc",
    "counterfactual_pnl_source",
    "real_action",
    "real_order_status",
    "real_reason_code",
    "real_strategy_id",
    "real_order_id",
    "real_fill_size",
    "real_total_spent_usdc",
    "real_pnl_source",
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


def active_strategy_lifecycle_for_spec(strategy=None, config=None):
    config = config or {}
    override = str(config.get("active_strategy_lifecycle") or "").strip()
    if override in {"candidate_canary", "promoted_default", "blocked", "manual_override"}:
        return override
    status = str((strategy or {}).get("status") or "").strip().lower()
    if status in {"promoted", "active", "default"}:
        return "promoted_default"
    if status == "blocked":
        return "blocked"
    if status == "candidate":
        return "candidate_canary"
    return "manual_override"


def _canary_age_days(started_date, target_date):
    if not started_date or not target_date:
        return None
    try:
        started = ensure_date(started_date)
        target = ensure_date(target_date)
    except (TypeError, ValueError):
        return None
    return max(0, (target - started).days)


def active_strategy_lifecycle_payload(strategy_specs=None, config=None, target_date=None):
    strategy_specs = list(strategy_specs or [])
    config = config or {}
    active_strategy = strategy_specs[0] if len(strategy_specs) == 1 else None
    active_id = (active_strategy or {}).get("strategy_id")
    lifecycle = active_strategy_lifecycle_for_spec(active_strategy, config=config) if active_strategy else None
    started_date = config.get("active_strategy_canary_started_date") or ACTIVE_DEFAULT_STRATEGY_CANARY_STARTED_DATE
    min_settled = int(config.get("canary_min_settled_orders") or DEFAULT_CANARY_MIN_SETTLED_ORDERS)
    min_complete = int(config.get("canary_min_complete_label_days") or DEFAULT_CANARY_MIN_COMPLETE_LABEL_DAYS)
    canary = {
        "strategy_id": active_id,
        "lifecycle": lifecycle,
        "paper_only": lifecycle == "candidate_canary",
        "requalification_required": lifecycle == "candidate_canary",
        "started_date": started_date if lifecycle == "candidate_canary" else None,
        "age_days": _canary_age_days(started_date, target_date) if lifecycle == "candidate_canary" else None,
        "min_settled_orders": min_settled,
        "min_complete_label_days": min_complete,
    }
    return {
        "active_strategy_id": active_id,
        "active_strategy_lifecycle": lifecycle,
        "active_strategy_canary": canary,
    }


def strategy_id_for_row(row):
    return str(row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID)


def normalize_order_strategy_fields(row, strategy=None, experiment_id=None):
    row = dict(row)
    strategy = strategy or {}
    strategy_id = strategy.get("strategy_id") or row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    row["experiment_id"] = experiment_id or row.get("experiment_id") or DEFAULT_EXPERIMENT_ID
    row["strategy_id"] = strategy_id
    row["strategy_family"] = strategy.get("strategy_family") or row.get("strategy_family") or "raw_edge"
    row["strategy_status"] = strategy.get("status") or row.get("strategy_status") or "control"
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
