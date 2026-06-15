"""Shared constants for market-making paper scoring."""

from pathlib import Path

SCHEMA_VERSION = "mm_paper_v0.1"
KNOWN_EDGE_SCHEMA_VERSION = "mm_known_edge_map_v0.2"

DEFAULT_RUNS_ROOT = Path("data") / "mm_runs"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
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
    "confidence_z": 1.96,
    "min_edge_allowed_live_days": 14,
    "min_edge_allowed_fills": 10,
    "min_edge_research_fills": 1,
}

FILL_COLUMNS = [
    "paper_schema_version",
    "run_id",
    "run_folder",
    "run_mode",
    "policy_hash",
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
    "conservative_fill_rule",
    "queue_status",
    "queue_fill_size",
    "queue_initial_ahead",
    "queue_depleted_ahead",
    "queue_reason",
    "market_mid",
    "spread_capture_usdc",
    "adverse_selection_30m_usdc",
    "settlement_pnl_usdc",
    "maker_fee_equivalent_usdc",
    "maker_rebate_estimate_usdc",
    "liquidity_reward_estimate_usdc",
    "flattening_fee_estimate_usdc",
    "net_pnl_after_fees_incentives_usdc",
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
