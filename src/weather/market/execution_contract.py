"""Shared execution evidence schema and owner pilot cap; no paper-policy imports."""

SCHEMA_VERSION = "mm_run_v0.2"


PLATFORM_VERIFICATION_SCHEMA_VERSION = "mm_platform_verification_v0.6"


MAX_OPERATOR_PILOT_BUDGET_USDC = 100.0


FILL_COLUMNS = [
    "run_id",
    "generated_at_utc",
    "mode",
    "lifecycle_key",
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
    "exchange_order_id",
    "trade_id",
    "transaction_hash",
    "maker_address",
    "condition_id",
    "liquidity_role",
    "fee_rate_bps",
    "official_trade_status",
    "maker_rebate_estimate_usdc",
    "markout_30m",
    "simulator",
    "notes",
]

DEFAULT_QUOTE_TTL_SECONDS = 120.0
