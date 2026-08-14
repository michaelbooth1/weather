"""Select a fresh public market for the bounded International lifecycle probe.

This command performs no authentication and cannot place or cancel orders. It
binds a current validated economics snapshot to current public CLOB books and
chooses a built-in weather token whose one-tick minimum-size BUY is nonmarketable
and within the adapter's single-order cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.exchange_economics import (
    load_exchange_economics_gate,
    snapshot_hash,
)
from weather.market.market_config import ensure_date
from weather.market.market_microstructure_capture import ClobClient
from weather.market.market_registry import BUILTIN_SPECS
from weather.market.mm_policy import utc_now
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_live_market_candidate_plan")
PLATFORM = "polymarket_global"
SETTLEMENT_UNIT = "pUSD"
MAX_SINGLE_ORDER_NOTIONAL = Decimal("10")
MIN_MIDPOINT = Decimal("0.20")
MAX_MIDPOINT = Decimal("0.80")
MAX_BOOK_SPREAD = Decimal("0.05")
MAX_ALTERNATES = 5
MAX_PLAN_AGE_SECONDS = 300


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_plan_sha256(payload):
    return _canonical_sha256({
        key: value for key, value in dict(payload or {}).items()
        if key != "plan_sha256"
    })


def _decimal(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _book_levels(book, side):
    levels = []
    for row in book.get(side) or []:
        price = _decimal(row.get("price")) if isinstance(row, dict) else None
        size = _decimal(row.get("size")) if isinstance(row, dict) else None
        if price is not None and size is not None and 0 < price < 1 and size > 0:
            levels.append((price, size))
    return levels


def _candidate_for_book(market, token_id, outcome_index, book):
    if str(book.get("asset_id") or "") != str(token_id):
        return None
    condition_id = str(market.get("condition_id") or "").lower()
    observed_condition = str(book.get("market") or "").lower()
    if observed_condition != condition_id:
        return None
    bids = _book_levels(book, "bids")
    asks = _book_levels(book, "asks")
    if not bids or not asks:
        return None
    best_bid = max(price for price, _size in bids)
    best_ask = min(price for price, _size in asks)
    if best_bid >= best_ask:
        return None
    spread = best_ask - best_bid
    midpoint = (best_bid + best_ask) / 2
    min_size = _decimal(market.get("order_min_size"))
    tick_size = _decimal(market.get("order_price_min_tick_size"))
    book_min_size = _decimal(book.get("min_order_size"))
    book_tick_size = _decimal(book.get("tick_size"))
    book_neg_risk = book.get("neg_risk")
    fee = dict(market.get("fee_schedule") or {})
    fee_rate = _decimal(fee.get("rate"))
    rebate_rate = _decimal(fee.get("rebate_rate"))
    if not all((
        market.get("fees_enabled") is True,
        min_size is not None and min_size > 0,
        tick_size is not None and 0 < tick_size < 1,
        book_min_size == min_size,
        book_tick_size == tick_size,
        isinstance(book_neg_risk, bool),
        fee_rate is not None and fee_rate > 0,
        rebate_rate is not None and rebate_rate > 0,
        best_ask > tick_size,
        MIN_MIDPOINT <= midpoint <= MAX_MIDPOINT,
        spread <= MAX_BOOK_SPREAD,
        min_size * tick_size <= MAX_SINGLE_ORDER_NOTIONAL,
    )):
        return None
    best_bid_depth = sum(size for price, size in bids if price == best_bid)
    best_ask_depth = sum(size for price, size in asks if price == best_ask)
    rewards = dict(market.get("liquidity_rewards") or {})
    reward_max_spread = _decimal(rewards.get("rewards_max_spread_cents"))
    reward_min_size = _decimal(rewards.get("rewards_min_size"))
    result = {
        "location_id": market.get("location_id"),
        "event_date": market.get("event_date"),
        "event_slug": market.get("event_slug"),
        "question": market.get("question"),
        "condition_id": condition_id,
        "token_id": str(token_id),
        "outcome_index": int(outcome_index),
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "midpoint": float(midpoint),
        "spread": float(spread),
        "best_bid_depth": float(best_bid_depth),
        "best_ask_depth": float(best_ask_depth),
        "order_min_size": float(min_size),
        "tick_size": float(tick_size),
        "neg_risk": book_neg_risk,
        "fee_rate": float(fee_rate),
        "maker_rebate_rate": float(rebate_rate),
        "reward_min_size": float(reward_min_size)
        if reward_min_size is not None else None,
        "reward_max_spread_cents": float(reward_max_spread)
        if reward_max_spread is not None else None,
        "current_book_within_reward_spread": (
            reward_max_spread is not None
            and spread * 100 <= reward_max_spread
        ),
        "lifecycle_probe_reward_min_size_met": (
            reward_min_size is not None and min_size >= reward_min_size
        ),
        "book_sha256": _canonical_sha256(book),
    }
    result["stage1_intent"] = {
        "side": "BUY",
        "price": float(tick_size),
        "size": float(min_size),
        "notional_pusd": float(tick_size * min_size),
        "post_only": True,
    }
    return result


def select_live_pilot_candidate(
    economics_snapshot,
    target_date,
    plan_out,
    *,
    now=None,
    book_reader=None,
):
    target_text = ensure_date(target_date).isoformat()
    output = Path(plan_out).resolve()
    if output.exists():
        raise RuntimeError("candidate-plan output path must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    gate = load_exchange_economics_gate(
        economics_snapshot,
        target_text,
        platform=PLATFORM,
        now=now,
        max_age_hours=2,
    )
    created_at = utc_now(now)
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCK",
        "created_at_utc": created_at.isoformat(),
        "expires_at_utc": (
            created_at + timedelta(seconds=MAX_PLAN_AGE_SECONDS)
        ).isoformat(),
        "target_date": target_text,
        "platform": PLATFORM,
        "settlement_unit": SETTLEMENT_UNIT,
        "exchange_economics_snapshot_id": gate.get("snapshot_id"),
        "exchange_economics_sha256": gate.get("exchange_economics_hash"),
        "economics_gate_ok": gate.get("ok") is True,
        "economics_gate_missing": list(gate.get("missing") or []),
        "selection_is_trading_authorization": False,
        "secret_values_retained": False,
        "selection_policy": {
            "built_in_locations_only": True,
            "positive_fee_and_rebate_required": True,
            "midpoint_interval": [float(MIN_MIDPOINT), float(MAX_MIDPOINT)],
            "max_spread": float(MAX_BOOK_SPREAD),
            "minimum_tick_buy_must_be_nonmarketable": True,
            "book_tick_min_size_and_neg_risk_must_be_current": True,
            "plan_max_age_seconds": MAX_PLAN_AGE_SECONDS,
            "max_single_order_notional_pusd": float(MAX_SINGLE_ORDER_NOTIONAL),
            "ranking": "spread_asc_then_best_level_depth_desc_then_midpoint_distance",
        },
        "candidate_count": 0,
        "selected": None,
        "alternates": [],
        "missing": [],
    }
    if not gate.get("ok"):
        base["missing"] = ["current_exchange_economics_gate"]
        base["plan_sha256"] = candidate_plan_sha256(base)
        write_json_atomic(output, base, trailing_newline=True)
        return base
    snapshot = json.loads(Path(economics_snapshot).read_text(encoding="utf-8-sig"))
    if snapshot_hash(snapshot) != gate.get("exchange_economics_hash"):
        raise RuntimeError("economics snapshot changed after validation")
    built_in_locations = {spec.id for spec in BUILTIN_SPECS}
    markets = [
        row for row in snapshot.get("markets") or []
        if row.get("location_id") in built_in_locations
        and row.get("event_date") == target_text
    ]
    token_map = {}
    for market in markets:
        for outcome_index, token_id in enumerate(market.get("token_ids") or []):
            token_map[str(token_id)] = (market, outcome_index)
    reader = book_reader or ClobClient(timeout=15).get_order_books
    books = reader(list(token_map))
    candidates = []
    for book in books or []:
        if not isinstance(book, dict):
            continue
        token_id = str(book.get("asset_id") or "")
        bound = token_map.get(token_id)
        if bound is None:
            continue
        candidate = _candidate_for_book(bound[0], token_id, bound[1], book)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda row: (
        row["spread"],
        -(row["best_bid_depth"] + row["best_ask_depth"]),
        abs(row["midpoint"] - 0.5),
        row["location_id"],
        row["token_id"],
    ))
    base["candidate_count"] = len(candidates)
    if candidates:
        base["status"] = "PASS"
        base["selected"] = candidates[0]
        base["alternates"] = candidates[1:1 + MAX_ALTERNATES]
    else:
        base["missing"] = ["current_safe_fee_eligible_book_candidate"]
    base["plan_sha256"] = candidate_plan_sha256(base)
    write_json_atomic(output, base, trailing_newline=True)
    return base


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--economics-snapshot", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--plan-out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = select_live_pilot_candidate(
            args.economics_snapshot,
            args.target_date,
            args.plan_out,
        )
    except Exception as exc:
        print(f"candidate selection failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result["status"] != "PASS":
        print("candidate selection BLOCK", file=sys.stderr)
        return 1
    print("candidate selection PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
