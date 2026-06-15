"""Shared constants for market-making run orchestration."""

from pathlib import Path

try:
    from .mm_policy import QUOTE_COLUMNS
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.market.mm_policy import QUOTE_COLUMNS

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
