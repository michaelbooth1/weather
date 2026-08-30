"""Shared constants for market-making run orchestration."""

from weather.paths import data_path
from weather.market.mm_policy import QUOTE_COLUMNS

SCHEMA_VERSION = "mm_run_v0.2"
PLATFORM_VERIFICATION_SCHEMA_VERSION = "mm_platform_verification_v0.6"
RUN_MODES = {"shadow", "paper-live-forward", "live-pilot"}
PERMISSION_PROFILES = {"model", "market_harvest"}
DEFAULT_RUNS_ROOT = data_path() / "mm_runs"
DEFAULT_QUOTE_TTL_SECONDS = 120.0
MAX_OPERATOR_PILOT_BUDGET_USDC = 100.0
DEFAULT_DATA_LAYER_AUDIT = data_path() / "backtest" / "data_layer_audit.json"
DEFAULT_PLATFORM_VERIFICATION = data_path() / "backtest" / "mm_platform_verification.json"

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
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
]

RUN_QUOTE_COLUMNS = RUN_EXTRA_COLUMNS + QUOTE_COLUMNS

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
