"""Shared constants for market-making paper scoring."""

from pathlib import Path

from weather.paths import data_path

SCHEMA_VERSION = "mm_paper_v0.1"
EXECUTION_EVIDENCE_SCHEMA_VERSION = "mm_execution_evidence_v0.1"
KNOWN_EDGE_SCHEMA_VERSION = "mm_known_edge_map_v0.2"
EARLY_HOUR_GUARDRAIL_SHADOW_SCHEMA_VERSION = "early_hour_market_guardrail_shadow_v0.1"
EXECUTION_RAW_TAPE_FILENAME = "mm_execution_tape.jsonl"
EXECUTION_CANONICAL_TAPE_FILENAME = "mm_execution_tape.csv"
EXECUTION_SESSION_FILENAME = "mm_execution_tape_sessions.jsonl"
EXECUTION_CONNECTION_SEQUENCE_SCOPE = "local_to_session_websocket_connection"
EXECUTION_BOOK_ALIGNMENT_SEQUENCE_STATUS = "not_exposed_by_public_feed"

DEFAULT_RUNS_ROOT = data_path() / "mm_runs"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "mm_paper_report.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "mm_paper_report.md"
DEFAULT_FILLS_OUT = DEFAULT_BACKTEST_ROOT / "mm_paper_fills_long.csv"
DEFAULT_KNOWN_EDGE_OUT = DEFAULT_BACKTEST_ROOT / "mm_known_edge_map.json"
DEFAULT_KNOWN_EDGE_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "mm_known_edge_map.md"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_CASEBOOK = DEFAULT_BACKTEST_ROOT / "disagreement_casebook.json"

MARKOUT_HORIZONS = [
    ("30s", 30),
    ("1m", 60),
    ("5m", 300),
    ("30m", 1800),
]

DEFAULT_CONFIG = {
    "quote_ttl_seconds": 60.0,
    "maker_fee_rate": 0.05,
    "maker_rebate_pool_share": 0.25,
    "flattening_fee_rate": 0.05,
    "reward_distance_threshold": 0.045,
    "reward_c": 3.0,
    "reward_campaign_pool_usdc": 0.0,
    "reward_competitor_q": 100.0,
    "reward_min_payout_usdc": 1.0,
    "reward_book_max_age_seconds": 120.0,
    "confidence_z": 1.96,
    "min_edge_allowed_live_days": 14,
    "min_edge_allowed_fills": 10,
    "min_edge_research_fills": 1,
    "model_variant_promotion_alpha": 0.05,
    "model_variant_promotion_bootstrap_iterations": 1000,
    "model_variant_promotion_min_market_day_clusters": 10,
    "model_variant_promotion_min_target_days": 3,
    "model_variant_promotion_min_markets": 3,
    "model_variant_promotion_all_market_min_markets": 10,
    "fill_evidence_require_clob_recon_coverage": True,
    "fill_evidence_max_missing_size_trade_rows": 0,
    "fill_evidence_max_missing_book_queue_legs": 0,
    "fill_evidence_max_missing_trade_size_queue_legs": 0,
    "fill_evidence_max_unresolved_resting_quotes": 0,
}

FILL_COLUMNS = [
    "paper_schema_version",
    "execution_evidence_schema_version",
    "run_id",
    "run_folder",
    "run_mode",
    "policy_hash",
    "model_variant_id",
    "model_variant_family",
    "model_variant_role",
    "model_variant_basket_id",
    "model_variant_probability_source",
    "model_variant_counterfactual",
    "served_model_version",
    "quote_id",
    "leg_id",
    "fill_id",
    "fill_time_utc",
    "event_slug",
    "market_id",
    "target_date",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "side",
    "quote_time_utc",
    "quote_expires_at_utc",
    "quote_age_seconds",
    "quote_price",
    "quote_size",
    "fill_price",
    "fill_size",
    "through_trade_price",
    "through_trade_size",
    "trade_source",
    "execution_id",
    "canonical_execution_id",
    "supplied_canonical_execution_id",
    "native_execution_id",
    "transaction_hash",
    "execution_exchange_time_utc",
    "execution_received_time_utc",
    "execution_time_source",
    "execution_time_precision_seconds",
    "execution_side",
    "execution_condition_id",
    "execution_raw_sha1",
    "execution_audit_bindings_json",
    "execution_source_representations",
    "conservative_fill_rule",
    "queue_status",
    "queue_fill_size",
    "queue_initial_ahead",
    "queue_depleted_ahead",
    "queue_reason",
    "market_mid",
    "fair_probability",
    "edge",
    "capture_hour_utc",
    "capture_hour_local",
    "capture_timezone",
    "hourly_trust_band",
    "hourly_trust_multiplier",
    "current_high_trusted",
    "current_high_guard_reason",
    "current_high_trust_gate_status",
    "current_high_trust_gate_action",
    "current_high_trust_gate_reason",
    "current_high_trust_gate_aggressive",
    "current_high_trust_gate_size_multiplier",
    "current_high_trust_gate_quote_widen_buffer",
    "early_hour_guardrail_status",
    "early_hour_guardrail_reason",
    "early_hour_guardrail_min_edge",
    "early_hour_guardrail_size_multiplier",
    "early_hour_guardrail_quote_widen_buffer",
    "early_hour_guardrail_override_allowed",
    "early_hour_guardrail_market_weight",
    "market_aware_overlay_probability",
    "market_aware_overlay_edge",
    "market_aware_overlay_used_for_risk_only",
    "spread_capture_usdc",
    "adverse_selection_30m_usdc",
    "settlement_pnl_usdc",
    "maker_fee_equivalent_usdc",
    "maker_rebate_estimate_usdc",
    "maker_rebate_accepted_usdc",
    "maker_rebate_acceptance_status",
    "liquidity_reward_estimate_usdc",
    "liquidity_reward_accepted_usdc",
    "reward_acceptance_status",
    "flattening_fee_estimate_usdc",
    "acceptance_horizon",
    "acceptance_pnl_status",
    "provisional_net_30m_usdc",
    "net_pnl_after_fees_incentives_usdc",
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
    "markout_30s_per_share",
    "markout_1m_per_share",
    "markout_5m_per_share",
    "markout_30m_per_share",
    "settlement_markout_per_share",
    "settlement_outcome",
    "regime",
    "source_fresh",
    "source_freshness_state",
    "book_imbalance_bucket",
    "band_distance_bucket",
    "casebook_taxonomy",
    "casebook_case_id",
]
