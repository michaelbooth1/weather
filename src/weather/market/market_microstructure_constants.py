"""Shared constants for Polymarket CLOB microstructure capture."""

from pathlib import Path

CLOB_BASE_URL = "https://clob.polymarket.com"
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
DEFAULT_BOOK_INTERVAL_SECONDS = 60.0
DEFAULT_FAST_INTERVAL_SECONDS = 15.0
DEFAULT_BATCH_SIZE = 100
DEFAULT_INCLUDE_PRICE_HISTORY = True
DEFAULT_INCLUDE_WS_EVENTS = True
DEFAULT_LOOP_INCLUDE_PRICE_HISTORY = False
DEFAULT_LOOP_INCLUDE_WS_EVENTS = False
DEFAULT_WS_SECONDS = 1.0
DEFAULT_WS_MESSAGE_LIMIT = 5
DEFAULT_WS_HEARTBEAT_SECONDS = 10
DEFAULT_WS_CONNECT_TIMEOUT = 5.0
DEFAULT_CLOB_FEATURE_MAX_AGE_SECONDS = 180.0
FIXED_EXECUTION_SIZES = (10.0, 100.0, 1000.0)
SNAPSHOT_DATA_ROOT = Path("data") / "snapshots"
CLOB_PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_pause.flag"
CLOB_LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_status.json"
CLOB_DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "clob_diagnostics.jsonl"
CLOB_LOOP_CONSOLE_LOG_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_console.log"
CLOB_SUPERVISOR_LOCK_PATH = SNAPSHOT_DATA_ROOT / ".clob_supervisor.lock"

TOKEN_COLUMNS = [
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "event_title",
    "market_id",
    "polymarket_url",
    "polymarket_market_id",
    "condition_id",
    "question",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "unit",
    "outcome",
    "outcome_index",
    "clob_token_id",
    "enable_order_book",
    "active",
    "closed",
    "gamma_yes",
    "gamma_no",
    "gamma_outcome_price",
    "gamma_best_bid",
    "gamma_best_ask",
    "gamma_last_trade_price",
    "gamma_volume",
    "gamma_liquidity",
]

BOOK_SUMMARY_COLUMNS = [
    "capture_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "polymarket_market_id",
    "condition_id",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "unit",
    "outcome",
    "clob_token_id",
    "order_book_hash",
    "book_timestamp",
    "book_time_utc",
    "min_order_size",
    "tick_size",
    "neg_risk",
    "bid_count",
    "ask_count",
    "best_bid",
    "best_ask",
    "spread",
    "midpoint",
    "bid_size_at_best",
    "ask_size_at_best",
    "bid_depth_1pct",
    "ask_depth_1pct",
    "bid_depth_5pct",
    "ask_depth_5pct",
    "bid_depth_all",
    "ask_depth_all",
    "imbalance_1pct",
    "imbalance_5pct",
    "last_trade_price",
    "gamma_best_bid",
    "gamma_best_ask",
    "gamma_last_trade_price",
]

for _size in FIXED_EXECUTION_SIZES:
    _label = str(int(_size))
    BOOK_SUMMARY_COLUMNS.extend([
        f"buy_vwap_{_label}",
        f"buy_fillable_{_label}",
        f"sell_vwap_{_label}",
        f"sell_fillable_{_label}",
    ])

BOOK_LEVEL_COLUMNS = [
    "capture_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "polymarket_market_id",
    "condition_id",
    "range_label",
    "outcome",
    "clob_token_id",
    "side",
    "level_index",
    "price",
    "size",
    "cumulative_size",
]

PRICE_HISTORY_COLUMNS = [
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "market_id",
    "polymarket_market_id",
    "condition_id",
    "range_label",
    "outcome",
    "clob_token_id",
    "interval",
    "fidelity_minutes",
    "point_timestamp",
    "point_time_utc",
    "price",
]

WS_EVENT_COLUMNS = [
    "received_at_utc",
    "event_slug",
    "market_id",
    "event_type",
    "asset_id",
    "market",
    "price",
    "side",
    "raw_sha1",
]
