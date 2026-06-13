import argparse
import csv
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path

import requests

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import config_from_event, config_for_date  # noqa: E402
from market_registry import all_specs, spec_for_id  # noqa: E402
from model_sources import request_with_retries  # noqa: E402
from polymarket_client import PolymarketClient  # noqa: E402


CLOB_BASE_URL = "https://clob.polymarket.com"
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
DEFAULT_BOOK_INTERVAL_SECONDS = 60.0
DEFAULT_FAST_INTERVAL_SECONDS = 15.0
DEFAULT_BATCH_SIZE = 100
FIXED_EXECUTION_SIZES = (10.0, 100.0, 1000.0)
SNAPSHOT_DATA_ROOT = Path("data") / "snapshots"
CLOB_PAUSE_FLAG_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_pause.flag"
CLOB_LOOP_STATUS_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_status.json"
CLOB_DIAGNOSTICS_PATH = SNAPSHOT_DATA_ROOT / "clob_diagnostics.jsonl"
CLOB_LOOP_CONSOLE_LOG_PATH = SNAPSHOT_DATA_ROOT / "clob_loop_console.log"
CLOB_SUPERVISOR_LOCK_PATH = SNAPSHOT_DATA_ROOT / ".clob_supervisor.lock"
REPO_ROOT = Path(__file__).resolve().parent.parent

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


def utc_now():
    return datetime.now(timezone.utc)


def read_clob_loop_status(path=None):
    path = Path(path or CLOB_LOOP_STATUS_PATH)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_clob_loop_status(status, path=None):
    path = Path(path or CLOB_LOOP_STATUS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, sort_keys=True, default=str)
    tmp.replace(path)


def append_clob_diagnostic(record, path=None):
    path = Path(path or CLOB_DIAGNOSTICS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def clob_supervisor_lock_is_stale(path=None, max_age_seconds=120):
    path = Path(path or CLOB_SUPERVISOR_LOCK_PATH)
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > max_age_seconds


def acquire_clob_supervisor_lock(path=None, attempts=30, sleep_fn=time.sleep):
    path = Path(path or CLOB_SUPERVISOR_LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii"))
            return handle
        except FileExistsError:
            if clob_supervisor_lock_is_stale(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            sleep_fn(0.1)
    return None


def release_clob_supervisor_lock(handle, path=None):
    os.close(handle)
    try:
        Path(path or CLOB_SUPERVISOR_LOCK_PATH).unlink()
    except FileNotFoundError:
        pass


def _age_seconds(now, iso_value):
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value))
    except ValueError:
        return None
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds()


def clob_loop_health(status, now=None, interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS):
    """Heartbeat-based liveness for the fast market-book loop."""
    now = now or utc_now()
    if not status:
        return {"state": "UNKNOWN", "detail": "no CLOB loop status file"}
    interval = to_number(status.get("interval_seconds")) or float(interval_seconds)
    heartbeat_age = _age_seconds(now, status.get("last_heartbeat"))
    capture_age = _age_seconds(now, status.get("last_books_captured_at"))
    errors = int(status.get("consecutive_errors") or 0)
    error_markets = status.get("error_markets") or []
    dead_after = max(2 * interval + 30.0, 90.0)
    if status.get("paused"):
        state = "PAUSED"
    elif heartbeat_age is None or heartbeat_age > dead_after:
        state = "DEAD"
    elif errors >= 3:
        state = "ERRORING"
    elif error_markets:
        state = "DEGRADED"
    else:
        state = "RUNNING"
    return {
        "state": state,
        "pid": status.get("pid"),
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "last_books_age_seconds": round(capture_age, 1) if capture_age is not None else None,
        "consecutive_errors": errors,
        "error_markets": error_markets,
        "last_error": status.get("last_error"),
        "started_at": status.get("started_at"),
        "market_id": status.get("market_id"),
        "interval_seconds": interval,
        "fast_interval_seconds": status.get("fast_interval_seconds"),
        "last_mode": status.get("last_mode"),
        "last_sleep_seconds": status.get("last_sleep_seconds"),
    }


BOOK_AUDIT_MAX_GAP_SECONDS = 120.0


def book_capture_times(folder):
    """Distinct book capture timestamps recorded in a folder's summary tape."""
    path = Path(folder) / "order_books_summary.csv"
    if not path.exists():
        return []
    times = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                value = row.get("captured_at_utc")
                if not value:
                    continue
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                times.add(parsed)
    except (OSError, csv.Error):
        return []
    return sorted(times)


def audit_book_tape(folder, now=None, max_gap_seconds=BOOK_AUDIT_MAX_GAP_SECONDS):
    """Cadence audit for one event folder's book tape.

    `ok` means the tape has captures, no internal gap above the threshold, and
    a fresh trailing capture. Trailing age only matters while the folder is the
    active market day, which is how the fleet audit calls this.
    """
    folder = Path(folder)
    now = now or utc_now()
    times = book_capture_times(folder)
    result = {
        "folder": str(folder),
        "captures": len(times),
        "first_capture_utc": times[0].isoformat() if times else None,
        "last_capture_utc": times[-1].isoformat() if times else None,
        "median_gap_seconds": None,
        "max_gap_seconds": None,
        "gaps_over_threshold": 0,
        "trailing_age_seconds": None,
        "max_gap_seconds_threshold": float(max_gap_seconds),
        "ok": False,
        "reason": None,
    }
    if not times:
        result["reason"] = "no book captures"
        return result
    gaps = [(later - earlier).total_seconds() for earlier, later in zip(times, times[1:])]
    if gaps:
        result["median_gap_seconds"] = round(statistics.median(gaps), 1)
        result["max_gap_seconds"] = round(max(gaps), 1)
        result["gaps_over_threshold"] = sum(1 for gap in gaps if gap > float(max_gap_seconds))
    trailing = (now - times[-1]).total_seconds()
    result["trailing_age_seconds"] = round(trailing, 1)
    if result["gaps_over_threshold"]:
        result["reason"] = (
            f"{result['gaps_over_threshold']} gaps over {float(max_gap_seconds):.0f}s "
            f"(max {result['max_gap_seconds']}s)"
        )
    elif trailing > float(max_gap_seconds):
        result["reason"] = f"last book capture is {trailing:.0f}s old"
    else:
        result["ok"] = True
    return result


def fleet_book_audit(
    market_id="all",
    snapshots_root=None,
    now=None,
    max_gap_seconds=BOOK_AUDIT_MAX_GAP_SECONDS,
):
    """Audit every registered market's active-day book tape cadence."""
    now = now or utc_now()
    root = Path(snapshots_root) if snapshots_root is not None else SNAPSHOT_DATA_ROOT
    market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
    rows = []
    for item in market_ids:
        spec = spec_for_id(item)
        config = config_for_date(now.astimezone(spec.tz).date(), item)
        audit = audit_book_tape(
            root / config.event_slug,
            now=now,
            max_gap_seconds=max_gap_seconds,
        )
        rows.append({"market_id": item, "event_slug": config.event_slug, **audit})
    return {
        "generated_at_utc": now.isoformat(),
        "max_gap_seconds_threshold": float(max_gap_seconds),
        "markets": rows,
        "ok": all(row["ok"] for row in rows) if rows else False,
    }


def pid_is_python(pid):
    """True when pid exists and belongs to a Python process."""
    if not pid:
        return False
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        ).stdout
        return "python" in out.lower()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def parse_json_list(value):
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def to_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timestamp_to_iso(value):
    number = to_number(value)
    if number is None:
        return None
    if number > 10_000_000_000:
        number = number / 1000.0
    try:
        return datetime.fromtimestamp(number, timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def status_value(market):
    if market.get("closed"):
        return market.get("umaResolutionStatus") or "closed"
    if market.get("active"):
        return "active"
    return "inactive"


def price_for_outcome(name, outcomes, prices):
    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == name.lower() and index < len(prices):
            return to_number(prices[index])
    return None


def label_bin_metadata(label, unit):
    import re

    digits = [int(value) for value in re.findall(r"\d+", str(label or ""))]
    if not digits:
        return {"bin_kind": None, "bin_value": None, "bin_value_hi": None, "unit": unit}
    lower_label = str(label).lower()
    value = digits[0]
    value_hi = digits[-1]
    if "below" in lower_label:
        kind = "lte"
        value_hi = value
    elif "higher" in lower_label or "above" in lower_label:
        kind = "gte"
        value_hi = value
    else:
        kind = "eq"
    return {
        "bin_kind": kind,
        "bin_value": value,
        "bin_value_hi": value_hi,
        "unit": unit,
    }


def token_rows_from_event(event, market_id=None, captured_at=None):
    """Flatten Gamma event markets into CLOB token rows.

    Gamma already carries condition ids and clobTokenIds. This function makes
    those identifiers durable and keeps the surrounding market metadata needed
    to join fast book captures back to model bands.
    """
    config = config_from_event(event)
    market_id = market_id or config.market_id
    spec = spec_for_id(market_id)
    captured_at = captured_at or utc_now()
    captured_at_local = captured_at.astimezone(spec.tz)
    rows = []
    for market in event.get("markets", []) or []:
        label = (
            market.get("groupItemTitle")
            or market.get("group_item_title")
            or market.get("question", "")
        )
        outcomes = parse_json_list(market.get("outcomes"))
        prices = parse_json_list(market.get("outcomePrices") or market.get("outcome_prices"))
        token_ids = parse_json_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
        yes_price = price_for_outcome("Yes", outcomes, prices)
        no_price = price_for_outcome("No", outcomes, prices)
        bin_meta = label_bin_metadata(label, spec.display_unit)
        max_len = max(len(outcomes), len(token_ids))
        for index in range(max_len):
            outcome = str(outcomes[index]) if index < len(outcomes) else ""
            token_id = str(token_ids[index]) if index < len(token_ids) else ""
            outcome_price = to_number(prices[index]) if index < len(prices) else None
            rows.append({
                "captured_at_utc": captured_at.isoformat(),
                "captured_at_local": captured_at_local.isoformat(),
                "event_slug": config.event_slug,
                "event_title": event.get("title") or event.get("question") or event.get("slug"),
                "market_id": market_id,
                "polymarket_url": config.polymarket_url,
                "polymarket_market_id": market.get("id"),
                "condition_id": market.get("conditionId") or market.get("condition_id"),
                "question": market.get("question"),
                "range_label": label,
                **bin_meta,
                "outcome": outcome,
                "outcome_index": index,
                "clob_token_id": token_id,
                "enable_order_book": market.get("enableOrderBook"),
                "active": market.get("active"),
                "closed": market.get("closed"),
                "gamma_yes": yes_price,
                "gamma_no": no_price,
                "gamma_outcome_price": outcome_price,
                "gamma_best_bid": to_number(market.get("bestBid")),
                "gamma_best_ask": to_number(market.get("bestAsk")),
                "gamma_last_trade_price": to_number(market.get("lastTradePrice")),
                "gamma_volume": to_number(market.get("volumeNum") or market.get("volume")),
                "gamma_liquidity": to_number(market.get("liquidityNum") or market.get("liquidity")),
            })
    return sorted(rows, key=token_sort_key)


def token_sort_key(row):
    kind = row.get("bin_kind")
    value = row.get("bin_value")
    if kind == "lte":
        base = -1
    elif kind == "gte":
        base = 10_000
    else:
        base = value if value is not None else 9_999
    return (base, row.get("outcome_index") or 0)


def filter_token_rows(token_rows, outcomes="all"):
    if outcomes == "all":
        return [row for row in token_rows if row.get("clob_token_id")]
    wanted = {item.strip().lower() for item in str(outcomes).split(",") if item.strip()}
    return [
        row
        for row in token_rows
        if row.get("clob_token_id") and str(row.get("outcome", "")).lower() in wanted
    ]


def normalize_levels(levels, side):
    normalized = []
    for level in levels or []:
        price = to_number(level.get("price"))
        size = to_number(level.get("size"))
        if price is None or size is None:
            continue
        normalized.append({"price": price, "size": size})
    reverse = side == "bid"
    return sorted(normalized, key=lambda item: item["price"], reverse=reverse)


def depth_within(levels, best_price, pct, side):
    if best_price is None:
        return None
    if side == "bid":
        limit = best_price * (1.0 - pct)
        eligible = [level for level in levels if level["price"] >= limit]
    else:
        limit = best_price * (1.0 + pct)
        eligible = [level for level in levels if level["price"] <= limit]
    return sum(level["size"] for level in eligible)


def imbalance(bid_depth, ask_depth):
    if bid_depth is None or ask_depth is None:
        return None
    total = bid_depth + ask_depth
    if total <= 0:
        return None
    return (bid_depth - ask_depth) / total


def vwap_for_size(levels, requested_size):
    remaining = requested_size
    notional = 0.0
    filled = 0.0
    for level in levels:
        take = min(remaining, level["size"])
        if take <= 0:
            continue
        notional += take * level["price"]
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return {
        "vwap": (notional / filled) if filled else None,
        "fillable": filled,
    }


def payload_sha1(payload):
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def capture_id_for_book(captured_at, token_id, book):
    raw = "|".join([
        captured_at.isoformat(),
        str(token_id or ""),
        str(book.get("hash") or ""),
        payload_sha1(book),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def summarize_order_book(book, token_row, captured_at, capture_id=None):
    token_row = token_row or {}
    token_id = str(book.get("asset_id") or token_row.get("clob_token_id") or "")
    capture_id = capture_id or capture_id_for_book(captured_at, token_id, book)
    bids = normalize_levels(book.get("bids"), "bid")
    asks = normalize_levels(book.get("asks"), "ask")
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    bid_depth_1 = depth_within(bids, best_bid, 0.01, "bid")
    ask_depth_1 = depth_within(asks, best_ask, 0.01, "ask")
    bid_depth_5 = depth_within(bids, best_bid, 0.05, "bid")
    ask_depth_5 = depth_within(asks, best_ask, 0.05, "ask")
    row = {
        "capture_id": capture_id,
        "captured_at_utc": captured_at.isoformat(),
        "captured_at_local": token_row.get("captured_at_local"),
        "event_slug": token_row.get("event_slug"),
        "market_id": token_row.get("market_id"),
        "polymarket_market_id": token_row.get("polymarket_market_id"),
        "condition_id": book.get("market") or token_row.get("condition_id"),
        "range_label": token_row.get("range_label"),
        "bin_kind": token_row.get("bin_kind"),
        "bin_value": token_row.get("bin_value"),
        "bin_value_hi": token_row.get("bin_value_hi"),
        "unit": token_row.get("unit"),
        "outcome": token_row.get("outcome"),
        "clob_token_id": token_id,
        "order_book_hash": book.get("hash"),
        "book_timestamp": book.get("timestamp"),
        "book_time_utc": timestamp_to_iso(book.get("timestamp")),
        "min_order_size": to_number(book.get("min_order_size")),
        "tick_size": to_number(book.get("tick_size")),
        "neg_risk": book.get("neg_risk"),
        "bid_count": len(bids),
        "ask_count": len(asks),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": (best_ask - best_bid) if best_bid is not None and best_ask is not None else None,
        "midpoint": (best_ask + best_bid) / 2.0 if best_bid is not None and best_ask is not None else None,
        "bid_size_at_best": bids[0]["size"] if bids else None,
        "ask_size_at_best": asks[0]["size"] if asks else None,
        "bid_depth_1pct": bid_depth_1,
        "ask_depth_1pct": ask_depth_1,
        "bid_depth_5pct": bid_depth_5,
        "ask_depth_5pct": ask_depth_5,
        "bid_depth_all": sum(level["size"] for level in bids),
        "ask_depth_all": sum(level["size"] for level in asks),
        "imbalance_1pct": imbalance(bid_depth_1, ask_depth_1),
        "imbalance_5pct": imbalance(bid_depth_5, ask_depth_5),
        "last_trade_price": to_number(book.get("last_trade_price")),
        "gamma_best_bid": token_row.get("gamma_best_bid"),
        "gamma_best_ask": token_row.get("gamma_best_ask"),
        "gamma_last_trade_price": token_row.get("gamma_last_trade_price"),
    }
    for size in FIXED_EXECUTION_SIZES:
        label = str(int(size))
        buy = vwap_for_size(asks, size)
        sell = vwap_for_size(bids, size)
        row[f"buy_vwap_{label}"] = buy["vwap"]
        row[f"buy_fillable_{label}"] = buy["fillable"]
        row[f"sell_vwap_{label}"] = sell["vwap"]
        row[f"sell_fillable_{label}"] = sell["fillable"]
    return row


def order_book_level_rows(book, token_row, captured_at, capture_id):
    rows = []
    base = {
        "capture_id": capture_id,
        "captured_at_utc": captured_at.isoformat(),
        "captured_at_local": token_row.get("captured_at_local"),
        "event_slug": token_row.get("event_slug"),
        "market_id": token_row.get("market_id"),
        "polymarket_market_id": token_row.get("polymarket_market_id"),
        "condition_id": book.get("market") or token_row.get("condition_id"),
        "range_label": token_row.get("range_label"),
        "outcome": token_row.get("outcome"),
        "clob_token_id": book.get("asset_id") or token_row.get("clob_token_id"),
    }
    for side_name, levels in (("bid", normalize_levels(book.get("bids"), "bid")),
                              ("ask", normalize_levels(book.get("asks"), "ask"))):
        cumulative = 0.0
        for index, level in enumerate(levels, start=1):
            cumulative += level["size"]
            rows.append({
                **base,
                "side": side_name,
                "level_index": index,
                "price": level["price"],
                "size": level["size"],
                "cumulative_size": cumulative,
            })
    return rows


def price_history_rows(response, token_row, captured_at, interval=None, fidelity_minutes=None):
    rows = []
    for point in (response or {}).get("history") or []:
        timestamp = point.get("t") or point.get("timestamp")
        rows.append({
            "captured_at_utc": captured_at.isoformat(),
            "captured_at_local": token_row.get("captured_at_local"),
            "event_slug": token_row.get("event_slug"),
            "market_id": token_row.get("market_id"),
            "polymarket_market_id": token_row.get("polymarket_market_id"),
            "condition_id": token_row.get("condition_id"),
            "range_label": token_row.get("range_label"),
            "outcome": token_row.get("outcome"),
            "clob_token_id": token_row.get("clob_token_id"),
            "interval": interval,
            "fidelity_minutes": fidelity_minutes,
            "point_timestamp": timestamp,
            "point_time_utc": timestamp_to_iso(timestamp),
            "price": to_number(point.get("p") if "p" in point else point.get("price")),
        })
    return rows


class ClobClient:
    def __init__(self, base_url=CLOB_BASE_URL, timeout=10, session=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def get_order_book(self, token_id):
        def _fetch():
            response = self.session.get(
                f"{self.base_url}/book",
                params={"token_id": token_id},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        return request_with_retries(_fetch)

    def get_order_books(self, token_ids, batch_size=DEFAULT_BATCH_SIZE):
        books = []
        for chunk in chunked([token_id for token_id in token_ids if token_id], batch_size):
            try:
                books.extend(self._post_order_books(chunk))
            except Exception:
                for token_id in chunk:
                    books.append(self.get_order_book(token_id))
        return books

    def _post_order_books(self, token_ids):
        def _fetch():
            response = self.session.post(
                f"{self.base_url}/books",
                json=[{"token_id": token_id} for token_id in token_ids],
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("books"), list):
                return payload["books"]
            return []
        return request_with_retries(_fetch)

    def get_price_history(
        self,
        token_id,
        start_ts=None,
        end_ts=None,
        interval=None,
        fidelity_minutes=1,
    ):
        params = {"market": token_id}
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts
        if interval:
            params["interval"] = interval
        if fidelity_minutes is not None:
            params["fidelity"] = int(fidelity_minutes)

        def _fetch():
            response = self.session.get(
                f"{self.base_url}/prices-history",
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        return request_with_retries(_fetch)


def chunked(values, size):
    size = max(1, int(size))
    for index in range(0, len(values), size):
        yield values[index:index + size]


class MarketMicrostructureStore:
    def __init__(self, root=None, event_slug=None):
        self.event_slug = event_slug
        self.root = Path(root) if root is not None else Path("data") / "snapshots" / str(event_slug)
        self.token_path = self.root / "clob_tokens.csv"
        self.token_jsonl_path = self.root / "clob_tokens.jsonl"
        self.books_summary_path = self.root / "order_books_summary.csv"
        self.books_long_path = self.root / "order_books_long.csv"
        self.books_jsonl_path = self.root / "order_books.jsonl"
        self.price_history_path = self.root / "price_history.csv"
        self.price_history_jsonl_path = self.root / "price_history.jsonl"
        self.ws_events_path = self.root / "market_ws_events.csv"
        self.ws_jsonl_path = self.root / "market_ws.jsonl"

    def append_csv(self, path, columns, rows):
        if not rows:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        if not write_header:
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    existing_header = next(csv.reader(handle), None)
                if existing_header:
                    columns = existing_header
            except (OSError, csv.Error):
                pass
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", restval="")
            if write_header:
                writer.writeheader()
            writer.writerows(rows)

    def append_jsonl(self, path, payload):
        self.root.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def write_token_rows(self, rows):
        self.append_csv(self.token_path, TOKEN_COLUMNS, rows)
        for row in rows:
            self.append_jsonl(self.token_jsonl_path, row)

    def write_books(self, summaries, level_rows, raw_records):
        self.append_csv(self.books_summary_path, BOOK_SUMMARY_COLUMNS, summaries)
        self.append_csv(self.books_long_path, BOOK_LEVEL_COLUMNS, level_rows)
        for record in raw_records:
            self.append_jsonl(self.books_jsonl_path, record)

    def write_price_history(self, rows, raw_records):
        self.append_csv(self.price_history_path, PRICE_HISTORY_COLUMNS, rows)
        for record in raw_records:
            self.append_jsonl(self.price_history_jsonl_path, record)

    def write_ws_event(self, row, raw_record):
        self.append_csv(self.ws_events_path, WS_EVENT_COLUMNS, [row])
        self.append_jsonl(self.ws_jsonl_path, raw_record)


def capture_market_books(
    market_id,
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=False,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
    now=None,
):
    event_client = PolymarketClient(market_id=market_id)
    event = event_client.get_event()
    return capture_event_books(
        event,
        market_id=market_id,
        clob_client=clob_client,
        root=root,
        outcomes=outcomes,
        include_price_history=include_price_history,
        history_minutes=history_minutes,
        history_interval=history_interval,
        fidelity_minutes=fidelity_minutes,
        batch_size=batch_size,
        now=now,
    )


def capture_event_books(
    event,
    market_id=None,
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=False,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
    now=None,
):
    captured_at = now or utc_now()
    config = config_from_event(event)
    market_id = market_id or config.market_id
    store = MarketMicrostructureStore(root=root, event_slug=config.event_slug)
    clob_client = clob_client or ClobClient()
    all_token_rows = token_rows_from_event(event, market_id=market_id, captured_at=captured_at)
    token_rows = filter_token_rows(all_token_rows, outcomes=outcomes)
    store.write_token_rows(all_token_rows)
    token_lookup = {str(row["clob_token_id"]): row for row in token_rows if row.get("clob_token_id")}
    books = clob_client.get_order_books(list(token_lookup), batch_size=batch_size)

    summaries = []
    level_rows = []
    raw_records = []
    midpoint_by_token = {}
    for book in books:
        token_id = str(book.get("asset_id") or "")
        token_row = token_lookup.get(token_id, {"clob_token_id": token_id})
        capture_id = capture_id_for_book(captured_at, token_id, book)
        summary = summarize_order_book(book, token_row, captured_at, capture_id=capture_id)
        summaries.append(summary)
        midpoint_by_token[token_id] = summary.get("midpoint")
        level_rows.extend(order_book_level_rows(book, token_row, captured_at, capture_id))
        raw_records.append({
            "capture_id": capture_id,
            "captured_at_utc": captured_at.isoformat(),
            "event_slug": config.event_slug,
            "market_id": market_id,
            "clob_token_id": token_id,
            "token": token_row,
            "book": book,
        })
    store.write_books(summaries, level_rows, raw_records)

    history_rows = []
    history_raw = []
    if include_price_history:
        end_ts = int(captured_at.timestamp())
        start_ts = end_ts - int(history_minutes * 60)
        for token_id, token_row in token_lookup.items():
            response = clob_client.get_price_history(
                token_id,
                start_ts=start_ts,
                end_ts=end_ts,
                interval=history_interval,
                fidelity_minutes=fidelity_minutes,
            )
            rows = price_history_rows(
                response,
                token_row,
                captured_at,
                interval=history_interval,
                fidelity_minutes=fidelity_minutes,
            )
            history_rows.extend(rows)
            history_raw.append({
                "captured_at_utc": captured_at.isoformat(),
                "event_slug": config.event_slug,
                "market_id": market_id,
                "clob_token_id": token_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "interval": history_interval,
                "fidelity_minutes": fidelity_minutes,
                "response": response,
            })
        store.write_price_history(history_rows, history_raw)

    return {
        "event_slug": config.event_slug,
        "market_id": market_id,
        "token_rows": len(all_token_rows),
        "captured_tokens": len(token_rows),
        "books": len(summaries),
        "levels": len(level_rows),
        "price_history_rows": len(history_rows),
        "order_books_summary_path": str(store.books_summary_path),
        "order_books_long_path": str(store.books_long_path),
        "order_books_jsonl_path": str(store.books_jsonl_path),
        "clob_tokens_path": str(store.token_path),
        "midpoint_by_token": midpoint_by_token,
    }


def capture_fleet_books(
    market_id="all",
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=False,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
):
    market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
    results = {}
    for item in market_ids:
        try:
            results[item] = capture_market_books(
                item,
                clob_client=clob_client,
                root=root,
                outcomes=outcomes,
                include_price_history=include_price_history,
                history_minutes=history_minutes,
                history_interval=history_interval,
                fidelity_minutes=fidelity_minutes,
                batch_size=batch_size,
            )
        except Exception as exc:  # noqa: BLE001 - one market should not stop the fleet
            results[item] = {"error": f"{type(exc).__name__}: {exc}"}
    return results


def target_close_time(config):
    spec = spec_for_id(config.market_id)
    close_date = config.target_date + timedelta(days=1)
    return datetime.combine(close_date, dt_time.min, tzinfo=spec.tz)


def should_use_fast_interval(
    configs,
    now,
    last_midpoints,
    current_midpoints,
    fast_hours_before_close,
    fast_after_local_hour,
    fast_on_mid_change_bps,
):
    for config in configs:
        spec = spec_for_id(config.market_id)
        local_now = now.astimezone(spec.tz)
        if fast_after_local_hour is not None and local_now.date() == config.target_date:
            if local_now.hour + local_now.minute / 60.0 >= fast_after_local_hour:
                return True
        if fast_hours_before_close is not None:
            hours_to_close = (target_close_time(config) - local_now).total_seconds() / 3600.0
            if 0 <= hours_to_close <= fast_hours_before_close:
                return True
    if fast_on_mid_change_bps is None or not last_midpoints:
        return False
    threshold = float(fast_on_mid_change_bps) / 10_000.0
    for token_id, midpoint in current_midpoints.items():
        previous = last_midpoints.get(token_id)
        if midpoint is None or previous is None:
            continue
        if abs(float(midpoint) - float(previous)) >= threshold:
            return True
    return False


def summarize_loop_results(results):
    summary = {}
    for market_id, value in (results or {}).items():
        if not isinstance(value, dict):
            summary[market_id] = {"error": f"unexpected result type {type(value).__name__}"}
            continue
        summary[market_id] = {
            "books": value.get("books"),
            "captured_tokens": value.get("captured_tokens"),
            "levels": value.get("levels"),
            "error": value.get("error"),
        }
    return summary


def clob_ensure_decision(health_state, pid_alive):
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_alive:
        return "noop"
    if pid_alive:
        return "restart"
    if health_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING"):
        return "restart"
    return "start"


def stop_clob_loop(now=None):
    now = now or utc_now()
    status = read_clob_loop_status()
    pid = (status or {}).get("pid")
    if not pid_is_python(pid):
        return {"stopped": False, "reason": f"no live CLOB loop process (pid={pid})"}
    os.kill(int(pid), signal.SIGTERM)
    if status is not None:
        status["last_stop_requested_at"] = now.isoformat()
        write_clob_loop_status(status)
    append_clob_diagnostic({"time": now.isoformat(), "supervisor": "stop", "pid": pid})
    return {"stopped": True, "pid": pid}


def _clob_loop_command(
    market_id="all",
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
):
    return [
        sys.executable,
        "-m",
        "src.market_microstructure",
        "loop",
        "--market",
        str(market_id),
        "--outcomes",
        str(outcomes),
        "--interval-seconds",
        str(interval_seconds),
        "--fast-interval-seconds",
        str(fast_interval_seconds),
        "--fast-hours-before-close",
        str(fast_hours_before_close),
        "--fast-after-local-hour",
        str(fast_after_local_hour),
        "--fast-on-mid-change-bps",
        str(fast_on_mid_change_bps),
        "--batch-size",
        str(batch_size),
    ]


def start_clob_loop_detached(
    market_id="all",
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    now=None,
):
    now = now or utc_now()
    CLOB_LOOP_CONSOLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = CLOB_LOOP_CONSOLE_LOG_PATH.open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    child = subprocess.Popen(
        _clob_loop_command(
            market_id=market_id,
            interval_seconds=interval_seconds,
            fast_interval_seconds=fast_interval_seconds,
            fast_hours_before_close=fast_hours_before_close,
            fast_after_local_hour=fast_after_local_hour,
            fast_on_mid_change_bps=fast_on_mid_change_bps,
            outcomes=outcomes,
            batch_size=batch_size,
        ),
        cwd=str(REPO_ROOT),
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
    )
    log_handle.close()
    write_clob_loop_status({
        "pid": child.pid,
        "started_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "market_id": market_id,
        "outcomes": outcomes,
        "interval_seconds": interval_seconds,
        "fast_interval_seconds": fast_interval_seconds,
        "fast_hours_before_close": fast_hours_before_close,
        "fast_after_local_hour": fast_after_local_hour,
        "fast_on_mid_change_bps": fast_on_mid_change_bps,
        "batch_size": batch_size,
        "iterations": 0,
        "consecutive_errors": 0,
        "error_markets": [],
        "last_error": None,
        "paused": CLOB_PAUSE_FLAG_PATH.exists(),
        "started_by": "supervisor",
    })
    append_clob_diagnostic({
        "time": now.isoformat(),
        "supervisor": "start",
        "pid": child.pid,
        "market_id": market_id,
        "interval_seconds": interval_seconds,
    })
    return {"started": True, "pid": child.pid}


def ensure_clob_loop(
    market_id="all",
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    now=None,
):
    now = now or utc_now()
    lock_handle = acquire_clob_supervisor_lock()
    if lock_handle is None:
        return {"action": "locked", "state": "UNKNOWN", "reason": "another CLOB supervisor action is running"}
    try:
        status = read_clob_loop_status()
        health = clob_loop_health(status, now=now, interval_seconds=interval_seconds)
        alive = pid_is_python((status or {}).get("pid"))
        action = clob_ensure_decision(health["state"], alive)
        result = {"action": action, "state": health["state"], "pid": health.get("pid")}
        if action == "restart":
            result["stop"] = stop_clob_loop(now=now)
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
                interval_seconds=interval_seconds,
                fast_interval_seconds=fast_interval_seconds,
                fast_hours_before_close=fast_hours_before_close,
                fast_after_local_hour=fast_after_local_hour,
                fast_on_mid_change_bps=fast_on_mid_change_bps,
                outcomes=outcomes,
                batch_size=batch_size,
                now=now,
            )
        elif action == "start":
            result["start"] = start_clob_loop_detached(
                market_id=market_id,
                interval_seconds=interval_seconds,
                fast_interval_seconds=fast_interval_seconds,
                fast_hours_before_close=fast_hours_before_close,
                fast_after_local_hour=fast_after_local_hour,
                fast_on_mid_change_bps=fast_on_mid_change_bps,
                outcomes=outcomes,
                batch_size=batch_size,
                now=now,
            )
        if action != "noop":
            append_clob_diagnostic({"time": now.isoformat(), "supervisor": "ensure", **result})
        return result
    finally:
        release_clob_supervisor_lock(lock_handle)


def run_book_loop(
    market_id="all",
    interval_seconds=DEFAULT_BOOK_INTERVAL_SECONDS,
    fast_interval_seconds=DEFAULT_FAST_INTERVAL_SECONDS,
    fast_hours_before_close=4.0,
    fast_after_local_hour=15.0,
    fast_on_mid_change_bps=500.0,
    outcomes="all",
    batch_size=DEFAULT_BATCH_SIZE,
    max_iterations=None,
    capture_fn=None,
    sleep_fn=time.sleep,
    now_fn=utc_now,
):
    capture_fn = capture_fn or capture_fleet_books
    last_midpoints = {}
    status = {
        "pid": os.getpid(),
        "started_at": now_fn().isoformat(),
        "market_id": market_id,
        "outcomes": outcomes,
        "interval_seconds": interval_seconds,
        "fast_interval_seconds": fast_interval_seconds,
        "fast_hours_before_close": fast_hours_before_close,
        "fast_after_local_hour": fast_after_local_hour,
        "fast_on_mid_change_bps": fast_on_mid_change_bps,
        "batch_size": batch_size,
        "iterations": 0,
        "consecutive_errors": 0,
        "error_markets": [],
        "last_error": None,
        "paused": False,
    }
    while True:
        loop_started = now_fn()
        status["iterations"] += 1
        status["last_heartbeat"] = loop_started.isoformat()
        status["paused"] = CLOB_PAUSE_FLAG_PATH.exists()
        market_ids = [spec.id for spec in all_specs()] if market_id == "all" else [market_id]
        configs = [config_for_date(loop_started.astimezone(spec_for_id(item).tz).date(), item) for item in market_ids]
        if status["paused"]:
            sleep_seconds = interval_seconds
            status["last_mode"] = "paused"
            status["last_sleep_seconds"] = sleep_seconds
            write_clob_loop_status(status)
            append_clob_diagnostic({"time": loop_started.isoformat(), "status": "paused"})
            print(json.dumps({"status": "paused", "time": loop_started.isoformat()}), flush=True)
        else:
            try:
                results = capture_fn(
                    market_id=market_id,
                    outcomes=outcomes,
                    include_price_history=False,
                    batch_size=batch_size,
                )
                current_midpoints = {}
                for result in results.values():
                    if isinstance(result, dict):
                        current_midpoints.update(result.get("midpoint_by_token") or {})
                fast = should_use_fast_interval(
                    configs,
                    loop_started,
                    last_midpoints,
                    current_midpoints,
                    fast_hours_before_close,
                    fast_after_local_hour,
                    fast_on_mid_change_bps,
                )
                sleep_seconds = fast_interval_seconds if fast else interval_seconds
                summary = summarize_loop_results(results)
                errors = {
                    item: value.get("error")
                    for item, value in summary.items()
                    if value.get("error")
                }
                full_error = bool(summary) and len(errors) == len(summary)
                status["consecutive_errors"] = status["consecutive_errors"] + 1 if full_error else 0
                status["error_markets"] = sorted(errors)
                status["last_error"] = "; ".join(f"{item}: {err}" for item, err in errors.items()) or None
                status["last_market_results"] = summary
                status["last_mode"] = "fast" if fast else "baseline"
                status["last_sleep_seconds"] = sleep_seconds
                if any((value.get("books") or 0) > 0 for value in summary.values()):
                    status["last_books_captured_at"] = loop_started.isoformat()
                write_clob_loop_status(status)
                append_clob_diagnostic({
                    "time": loop_started.isoformat(),
                    "mode": status["last_mode"],
                    "sleep_seconds": sleep_seconds,
                    "markets": summary,
                })
                print(json.dumps({
                    "time": loop_started.isoformat(),
                    "mode": status["last_mode"],
                    "sleep_seconds": sleep_seconds,
                    "results": summary,
                }, sort_keys=True), flush=True)
                last_midpoints = current_midpoints
            except Exception as exc:  # noqa: BLE001 - keep the collector alive
                status["consecutive_errors"] += 1
                status["error_markets"] = list(market_ids)
                status["last_error"] = f"{type(exc).__name__}: {exc}"
                status["last_mode"] = "error"
                sleep_seconds = interval_seconds
                status["last_sleep_seconds"] = sleep_seconds
                write_clob_loop_status(status)
                append_clob_diagnostic({
                    "time": loop_started.isoformat(),
                    "status": "error",
                    "error": status["last_error"],
                })
                print(json.dumps({
                    "time": loop_started.isoformat(),
                    "status": "error",
                    "error": status["last_error"],
                }, sort_keys=True), flush=True)
        if max_iterations is not None and status["iterations"] >= max_iterations:
            return status
        elapsed = (now_fn() - loop_started).total_seconds()
        sleep_fn(max(1.0, sleep_seconds - elapsed))


def ws_summary_row(received_at, event_slug, market_id, payload):
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    payload = payload if isinstance(payload, dict) else {"message": payload}
    return {
        "received_at_utc": received_at.isoformat(),
        "event_slug": event_slug,
        "market_id": market_id,
        "event_type": payload.get("event_type"),
        "asset_id": payload.get("asset_id") or payload.get("asset_id"),
        "market": payload.get("market"),
        "price": payload.get("price"),
        "side": payload.get("side"),
        "raw_sha1": payload_sha1(payload),
    }


def record_market_websocket(
    event,
    market_id=None,
    root=None,
    outcomes="all",
    seconds=300,
    message_limit=None,
    heartbeat_seconds=10,
    websocket_factory=None,
):
    config = config_from_event(event)
    market_id = market_id or config.market_id
    store = MarketMicrostructureStore(root=root, event_slug=config.event_slug)
    token_rows = filter_token_rows(
        token_rows_from_event(event, market_id=market_id, captured_at=utc_now()),
        outcomes=outcomes,
    )
    token_ids = [row["clob_token_id"] for row in token_rows]
    if not token_ids:
        return {"event_slug": config.event_slug, "market_id": market_id, "messages": 0, "reason": "no token ids"}
    timeout_exceptions = (TimeoutError,)
    if websocket_factory is None:
        try:
            import websocket  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "websocket-client is required for live WebSocket capture; "
                "install requirements.txt or pass a websocket_factory in tests."
            ) from exc
        websocket_factory = websocket.create_connection
        timeout_exceptions = (TimeoutError, websocket.WebSocketTimeoutException)

    ws = websocket_factory(CLOB_WS_URL, timeout=30)
    recv_timeout = max(1.0, min(float(seconds), float(heartbeat_seconds), 10.0))
    try:
        ws.settimeout(recv_timeout)
    except AttributeError:
        pass
    sent = {"operation": "subscribe", "assets_ids": token_ids}
    ws.send(json.dumps(sent))
    deadline = time.time() + float(seconds)
    next_heartbeat = time.time() + float(heartbeat_seconds)
    messages = 0
    try:
        while time.time() < deadline:
            if message_limit is not None and messages >= message_limit:
                break
            if time.time() >= next_heartbeat:
                ws.send("PING")
                next_heartbeat = time.time() + float(heartbeat_seconds)
            try:
                raw = ws.recv()
            except timeout_exceptions:
                continue
            received_at = utc_now()
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                payload = raw
            row = ws_summary_row(received_at, config.event_slug, market_id, payload)
            store.write_ws_event(row, {
                "received_at_utc": received_at.isoformat(),
                "event_slug": config.event_slug,
                "market_id": market_id,
                "subscription": sent,
                "payload": payload,
            })
            messages += 1
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001 - closing a socket should not hide captured data
            pass
    return {
        "event_slug": config.event_slug,
        "market_id": market_id,
        "tokens": len(token_ids),
        "messages": messages,
        "market_ws_path": str(store.ws_jsonl_path),
    }


def _market_choices():
    return ["all"] + [spec.id for spec in all_specs()]


def add_loop_options(parser):
    parser.add_argument("--market", choices=_market_choices(), default="all")
    parser.add_argument("--outcomes", default="all")
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_BOOK_INTERVAL_SECONDS)
    parser.add_argument("--fast-interval-seconds", type=float, default=DEFAULT_FAST_INTERVAL_SECONDS)
    parser.add_argument("--fast-hours-before-close", type=float, default=4.0)
    parser.add_argument("--fast-after-local-hour", type=float, default=15.0)
    parser.add_argument("--fast-on-mid-change-bps", type=float, default=500.0)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Capture Polymarket CLOB books, price history, and market WebSocket events."
    )
    subparsers = parser.add_subparsers(dest="command")

    capture = subparsers.add_parser("capture", help="Capture one REST book batch.")
    capture.add_argument("--market", choices=_market_choices(), default="all")
    capture.add_argument("--outcomes", default="all", help="'all', 'yes', 'no', or comma-separated outcomes.")
    capture.add_argument("--price-history", action="store_true", help="Also capture /prices-history for each token.")
    capture.add_argument("--history-minutes", type=int, default=240)
    capture.add_argument("--history-interval", default=None)
    capture.add_argument("--fidelity-minutes", type=int, default=1)
    capture.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    loop = subparsers.add_parser("loop", help="Run a fast CLOB book capture loop.")
    add_loop_options(loop)

    status = subparsers.add_parser("status", help="Print the managed CLOB loop health and exit.")
    status.add_argument("--interval-seconds", type=float, default=DEFAULT_BOOK_INTERVAL_SECONDS)

    stop = subparsers.add_parser("stop", help="Terminate the managed CLOB loop process.")
    stop.set_defaults(_stop=True)

    start = subparsers.add_parser("start-detached", help="Start the CLOB loop as a detached process.")
    add_loop_options(start)

    restart = subparsers.add_parser("restart", help="Stop the managed CLOB loop and start a fresh detached one.")
    add_loop_options(restart)

    ensure = subparsers.add_parser(
        "ensure",
        help="Supervisor check: start/restart the CLOB loop only if it is dead or hung.",
    )
    add_loop_options(ensure)

    audit = subparsers.add_parser(
        "audit",
        help="Audit the active market day's book-tape cadence per market.",
    )
    audit.add_argument("--market", choices=_market_choices(), default="all")
    audit.add_argument("--max-gap-seconds", type=float, default=BOOK_AUDIT_MAX_GAP_SECONDS)
    audit.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any market has a gap over the threshold or a stale/missing tape.",
    )

    ws = subparsers.add_parser("websocket", help="Record the public CLOB market WebSocket.")
    ws.add_argument("--market", choices=[spec.id for spec in all_specs()], default="toronto")
    ws.add_argument("--outcomes", default="all")
    ws.add_argument("--seconds", type=int, default=300)
    ws.add_argument("--message-limit", type=int, default=None)
    ws.add_argument("--heartbeat-seconds", type=int, default=10)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    command = args.command
    if command == "capture":
        result = capture_fleet_books(
            market_id=args.market,
            outcomes=args.outcomes,
            include_price_history=args.price_history,
            history_minutes=args.history_minutes,
            history_interval=args.history_interval,
            fidelity_minutes=args.fidelity_minutes,
            batch_size=args.batch_size,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    if command == "loop":
        run_book_loop(
            market_id=args.market,
            interval_seconds=args.interval_seconds,
            fast_interval_seconds=args.fast_interval_seconds,
            fast_hours_before_close=args.fast_hours_before_close,
            fast_after_local_hour=args.fast_after_local_hour,
            fast_on_mid_change_bps=args.fast_on_mid_change_bps,
            outcomes=args.outcomes,
            batch_size=args.batch_size,
        )
        return
    if command == "status":
        health = clob_loop_health(
            read_clob_loop_status(),
            now=utc_now(),
            interval_seconds=args.interval_seconds,
        )
        print(json.dumps(health, indent=2, sort_keys=True, default=str))
        return
    if command == "audit":
        result = fleet_book_audit(
            market_id=args.market,
            max_gap_seconds=args.max_gap_seconds,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        if args.strict and not result["ok"]:
            sys.exit(2)
        return
    if command == "stop":
        print(json.dumps(stop_clob_loop(), indent=2, sort_keys=True, default=str))
        return
    if command == "start-detached":
        lock_handle = acquire_clob_supervisor_lock()
        if lock_handle is None:
            print(json.dumps({"started": False, "reason": "another CLOB supervisor action is running"}, indent=2))
            return
        try:
            health = clob_loop_health(
                read_clob_loop_status(),
                now=utc_now(),
                interval_seconds=args.interval_seconds,
            )
            if health["state"] in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING") and pid_is_python(health.get("pid")):
                print(json.dumps({"started": False, "reason": f"CLOB loop already {health['state']}"}, indent=2))
                return
            print(json.dumps(start_clob_loop_detached(
                market_id=args.market,
                interval_seconds=args.interval_seconds,
                fast_interval_seconds=args.fast_interval_seconds,
                fast_hours_before_close=args.fast_hours_before_close,
                fast_after_local_hour=args.fast_after_local_hour,
                fast_on_mid_change_bps=args.fast_on_mid_change_bps,
                outcomes=args.outcomes,
                batch_size=args.batch_size,
            ), indent=2, sort_keys=True, default=str))
        finally:
            release_clob_supervisor_lock(lock_handle)
        return
    if command == "restart":
        lock_handle = acquire_clob_supervisor_lock()
        if lock_handle is None:
            print(json.dumps({"restarted": False, "reason": "another CLOB supervisor action is running"}, indent=2))
            return
        try:
            result = {
                "stop": stop_clob_loop(),
                "start": start_clob_loop_detached(
                    market_id=args.market,
                    interval_seconds=args.interval_seconds,
                    fast_interval_seconds=args.fast_interval_seconds,
                    fast_hours_before_close=args.fast_hours_before_close,
                    fast_after_local_hour=args.fast_after_local_hour,
                    fast_on_mid_change_bps=args.fast_on_mid_change_bps,
                    outcomes=args.outcomes,
                    batch_size=args.batch_size,
                ),
            }
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        finally:
            release_clob_supervisor_lock(lock_handle)
        return
    if command == "ensure":
        print(json.dumps(ensure_clob_loop(
            market_id=args.market,
            interval_seconds=args.interval_seconds,
            fast_interval_seconds=args.fast_interval_seconds,
            fast_hours_before_close=args.fast_hours_before_close,
            fast_after_local_hour=args.fast_after_local_hour,
            fast_on_mid_change_bps=args.fast_on_mid_change_bps,
            outcomes=args.outcomes,
            batch_size=args.batch_size,
        ), indent=2, sort_keys=True, default=str))
        return
    if command == "websocket":
        event = PolymarketClient(market_id=args.market).get_event()
        result = record_market_websocket(
            event,
            market_id=args.market,
            outcomes=args.outcomes,
            seconds=args.seconds,
            message_limit=args.message_limit,
            heartbeat_seconds=args.heartbeat_seconds,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return


if __name__ == "__main__":
    main()
