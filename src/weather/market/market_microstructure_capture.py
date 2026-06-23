"""CLOB token, order-book, price-history, and WebSocket capture helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

import requests

from weather.io import normalize_csv_row
from weather.market.market_config import config_from_event
from weather.market.market_microstructure_constants import (
    BOOK_LEVEL_COLUMNS,
    BOOK_SUMMARY_COLUMNS,
    CLOB_BASE_URL,
    CLOB_WS_URL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CLOB_FEATURE_MAX_AGE_SECONDS,
    DEFAULT_INCLUDE_PRICE_HISTORY,
    DEFAULT_INCLUDE_WS_EVENTS,
    DEFAULT_WS_CONNECT_TIMEOUT,
    DEFAULT_WS_HEARTBEAT_SECONDS,
    DEFAULT_WS_MESSAGE_LIMIT,
    DEFAULT_WS_SECONDS,
    FIXED_EXECUTION_SIZES,
    PRICE_HISTORY_COLUMNS,
    TOKEN_COLUMNS,
    WS_EVENT_COLUMNS,
)
from weather.market.market_microstructure_features import write_clob_feature_rows
from weather.market.market_registry import all_specs, spec_for_id
from weather.market.polymarket_client import PolymarketClient
from weather.model.model_sources import request_with_retries
from weather.schema_registry import schema_version


CLOB_CAPTURE_STATUS_SCHEMA_VERSION = schema_version("clob_capture_status")


def utc_now():
    return datetime.now(timezone.utc)

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
        self.root = Path(root) if root is not None else data_path() / "snapshots" / str(event_slug)
        self.capture_status_path = self.root / "clob_capture_status.jsonl"
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
            writer.writerows(normalize_csv_row(row) for row in rows)

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
        self.write_ws_events([row], raw_record)

    def write_ws_events(self, rows, raw_record):
        self.append_csv(self.ws_events_path, WS_EVENT_COLUMNS, rows)
        self.append_jsonl(self.ws_jsonl_path, raw_record)

    def write_capture_status(self, payload):
        self.append_jsonl(self.capture_status_path, payload)


def capture_status_from_result(
    result,
    outcomes,
    include_price_history,
    include_ws_events,
    store,
    captured_at,
    status=None,
    error_stage=None,
    error=None,
    include_clob_features=True,
):
    captured_tokens = int(result.get("captured_tokens") or 0)
    books = int(result.get("books") or 0)
    if status is None:
        if captured_tokens <= 0:
            status = "NO_ACTIVE_TOKENS"
        elif books <= 0:
            status = "NO_BOOKS"
        else:
            status = "OK"
    return {
        "schema_version": CLOB_CAPTURE_STATUS_SCHEMA_VERSION,
        "captured_at_utc": captured_at.isoformat(),
        "event_slug": result.get("event_slug"),
        "market_id": result.get("market_id"),
        "status": status,
        "error_stage": error_stage,
        "error": error,
        "outcomes": outcomes,
        "include_price_history": bool(include_price_history),
        "include_ws_events": bool(include_ws_events),
        "include_clob_features": bool(include_clob_features),
        "token_rows": int(result.get("token_rows") or 0),
        "captured_tokens": captured_tokens,
        "books": books,
        "levels": int(result.get("levels") or 0),
        "price_history_rows": int(result.get("price_history_rows") or 0),
        "ws_messages": int(result.get("ws_messages") or 0),
        "ws_event_rows": int(result.get("ws_event_rows") or 0),
        "ws_error": result.get("ws_error"),
        "clob_feature_rows": int(result.get("clob_feature_rows") or 0),
        "clob_features_error": result.get("clob_features_error"),
        "capture_status_path": str(store.capture_status_path),
        "order_books_summary_path": str(store.books_summary_path),
        "order_books_long_path": str(store.books_long_path),
        "order_books_jsonl_path": str(store.books_jsonl_path),
        "clob_tokens_path": str(store.token_path),
    }


def capture_market_books(
    market_id,
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=DEFAULT_INCLUDE_PRICE_HISTORY,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
    include_ws_events=DEFAULT_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    websocket_factory=None,
    include_clob_features=True,
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
        include_ws_events=include_ws_events,
        ws_seconds=ws_seconds,
        ws_message_limit=ws_message_limit,
        ws_heartbeat_seconds=ws_heartbeat_seconds,
        ws_connect_timeout=ws_connect_timeout,
        websocket_factory=websocket_factory,
        include_clob_features=include_clob_features,
        now=now,
    )


def capture_event_books(
    event,
    market_id=None,
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=DEFAULT_INCLUDE_PRICE_HISTORY,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
    include_ws_events=DEFAULT_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    websocket_factory=None,
    include_clob_features=True,
    now=None,
):
    captured_at = now or utc_now()
    config = config_from_event(event)
    market_id = market_id or config.market_id
    store = MarketMicrostructureStore(root=root, event_slug=config.event_slug)
    clob_client = clob_client or ClobClient()
    all_token_rows = []
    token_rows = []
    summaries = []
    level_rows = []
    history_rows = []
    ws_result = {"messages": 0}
    feature_result = {"rows": 0, "csv_path": None, "jsonl_path": None}
    midpoint_by_token = {}
    stage = "tokens"
    try:
        all_token_rows = token_rows_from_event(event, market_id=market_id, captured_at=captured_at)
        token_rows = filter_token_rows(all_token_rows, outcomes=outcomes)
        store.write_token_rows(all_token_rows)
        token_lookup = {str(row["clob_token_id"]): row for row in token_rows if row.get("clob_token_id")}
        stage = "order_books"
        books = clob_client.get_order_books(list(token_lookup), batch_size=batch_size)

        raw_records = []
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

        history_raw = []
        if include_price_history:
            stage = "price_history"
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

        if include_ws_events:
            try:
                ws_result = record_market_websocket(
                    event,
                    market_id=market_id,
                    root=root,
                    outcomes=outcomes,
                    seconds=ws_seconds,
                    message_limit=ws_message_limit,
                    heartbeat_seconds=ws_heartbeat_seconds,
                    connect_timeout=ws_connect_timeout,
                    websocket_factory=websocket_factory,
                )
            except Exception as exc:  # noqa: BLE001 - WS capture should not drop REST book data
                ws_result = {"messages": 0, "error": f"{type(exc).__name__}: {exc}"}

        if include_clob_features and (store.root / "snapshots_long.csv").exists():
            try:
                feature_result = write_clob_feature_rows(
                    store.root,
                    max_age_seconds=DEFAULT_CLOB_FEATURE_MAX_AGE_SECONDS,
                    market_id=market_id,
                )
            except Exception as exc:  # noqa: BLE001 - derived features should not drop raw CLOB evidence
                feature_result = {"rows": 0, "error": f"{type(exc).__name__}: {exc}"}
    except Exception as exc:
        result = {
            "event_slug": config.event_slug,
            "market_id": market_id,
            "token_rows": len(all_token_rows),
            "captured_tokens": len(token_rows),
            "books": len(summaries),
            "levels": len(level_rows),
            "price_history_rows": len(history_rows),
            "ws_messages": ws_result.get("messages", 0),
            "ws_event_rows": ws_result.get("event_rows", 0),
            "ws_error": ws_result.get("error"),
            "clob_feature_rows": feature_result.get("rows", 0),
            "clob_features_error": feature_result.get("error"),
        }
        store.write_capture_status(capture_status_from_result(
            result,
            outcomes,
            include_price_history,
            include_ws_events,
            store,
            captured_at,
            status="ERROR",
            error_stage=stage,
            error=f"{type(exc).__name__}: {exc}",
            include_clob_features=include_clob_features,
        ))
        raise

    result = {
        "event_slug": config.event_slug,
        "market_id": market_id,
        "token_rows": len(all_token_rows),
        "captured_tokens": len(token_rows),
        "books": len(summaries),
        "levels": len(level_rows),
        "price_history_rows": len(history_rows),
        "ws_messages": ws_result.get("messages", 0),
        "ws_event_rows": ws_result.get("event_rows", 0),
        "ws_error": ws_result.get("error"),
        "market_ws_path": ws_result.get("market_ws_path"),
        "clob_feature_rows": feature_result.get("rows", 0),
        "clob_features_path": feature_result.get("csv_path"),
        "clob_features_error": feature_result.get("error"),
        "order_books_summary_path": str(store.books_summary_path),
        "order_books_long_path": str(store.books_long_path),
        "order_books_jsonl_path": str(store.books_jsonl_path),
        "clob_tokens_path": str(store.token_path),
        "clob_capture_status_path": str(store.capture_status_path),
        "midpoint_by_token": midpoint_by_token,
    }
    store.write_capture_status(capture_status_from_result(
        result,
        outcomes,
        include_price_history,
        include_ws_events,
        store,
        captured_at,
        include_clob_features=include_clob_features,
    ))
    return result


def capture_fleet_books(
    market_id="all",
    clob_client=None,
    root=None,
    outcomes="all",
    include_price_history=DEFAULT_INCLUDE_PRICE_HISTORY,
    history_minutes=240,
    history_interval=None,
    fidelity_minutes=1,
    batch_size=DEFAULT_BATCH_SIZE,
    include_ws_events=DEFAULT_INCLUDE_WS_EVENTS,
    ws_seconds=DEFAULT_WS_SECONDS,
    ws_message_limit=DEFAULT_WS_MESSAGE_LIMIT,
    ws_heartbeat_seconds=DEFAULT_WS_HEARTBEAT_SECONDS,
    ws_connect_timeout=DEFAULT_WS_CONNECT_TIMEOUT,
    websocket_factory=None,
    include_clob_features=True,
    progress_callback=None,
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
                include_ws_events=include_ws_events,
                ws_seconds=ws_seconds,
                ws_message_limit=ws_message_limit,
                ws_heartbeat_seconds=ws_heartbeat_seconds,
                ws_connect_timeout=ws_connect_timeout,
                websocket_factory=websocket_factory,
                include_clob_features=include_clob_features,
            )
        except Exception as exc:  # noqa: BLE001 - one market should not stop the fleet
            results[item] = {"error": f"{type(exc).__name__}: {exc}"}
        if progress_callback is not None:
            progress_callback(item, results[item])
    return results

def ws_summary_rows(received_at, event_slug, market_id, payload, raw_sha1=None):
    raw_sha1 = raw_sha1 or payload_sha1(payload)
    if isinstance(payload, list):
        payloads = payload
    else:
        payloads = [payload]
    rows = []
    for item in payloads:
        item = item if isinstance(item, dict) else {"message": item}
        price_changes = item.get("price_changes")
        if isinstance(price_changes, list) and price_changes:
            for change in price_changes:
                change = change if isinstance(change, dict) else {"price": change}
                rows.append({
                    "received_at_utc": received_at.isoformat(),
                    "event_slug": event_slug,
                    "market_id": market_id,
                    "event_type": change.get("event_type") or item.get("event_type"),
                    "asset_id": change.get("asset_id") or item.get("asset_id") or change.get("clob_token_id"),
                    "market": change.get("market") or item.get("market"),
                    "price": change.get("price"),
                    "size": change.get("size") or change.get("trade_size") or item.get("size"),
                    "trade_size": change.get("trade_size") or item.get("trade_size"),
                    "shares": change.get("shares") or item.get("shares"),
                    "amount": change.get("amount") or item.get("amount"),
                    "matched_amount": change.get("matched_amount") or item.get("matched_amount"),
                    "maker_amount": change.get("maker_amount") or item.get("maker_amount"),
                    "timestamp_utc": change.get("timestamp_utc") or item.get("timestamp_utc"),
                    "trade_time_utc": change.get("trade_time_utc") or item.get("trade_time_utc"),
                    "side": change.get("side") or item.get("side"),
                    "raw_sha1": raw_sha1,
                })
            continue
        rows.append({
            "received_at_utc": received_at.isoformat(),
            "event_slug": event_slug,
            "market_id": market_id,
            "event_type": item.get("event_type"),
            "asset_id": item.get("asset_id") or item.get("clob_token_id"),
            "market": item.get("market"),
            "price": item.get("price"),
            "size": item.get("size"),
            "trade_size": item.get("trade_size"),
            "shares": item.get("shares"),
            "amount": item.get("amount"),
            "matched_amount": item.get("matched_amount"),
            "maker_amount": item.get("maker_amount"),
            "timestamp_utc": item.get("timestamp_utc"),
            "trade_time_utc": item.get("trade_time_utc"),
            "side": item.get("side"),
            "raw_sha1": raw_sha1,
        })
    return rows


def record_market_websocket(
    event,
    market_id=None,
    root=None,
    outcomes="all",
    seconds=300,
    message_limit=None,
    heartbeat_seconds=10,
    connect_timeout=30,
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

    ws = websocket_factory(CLOB_WS_URL, timeout=connect_timeout)
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
    event_rows = 0
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
            raw_sha1 = payload_sha1(payload)
            rows = ws_summary_rows(received_at, config.event_slug, market_id, payload, raw_sha1=raw_sha1)
            store.write_ws_events(rows, {
                "received_at_utc": received_at.isoformat(),
                "event_slug": config.event_slug,
                "market_id": market_id,
                "subscription": sent,
                "raw_sha1": raw_sha1,
                "event_rows": len(rows),
                "payload": payload,
            })
            messages += 1
            event_rows += len(rows)
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
        "event_rows": event_rows,
        "market_ws_path": str(store.ws_jsonl_path),
    }
