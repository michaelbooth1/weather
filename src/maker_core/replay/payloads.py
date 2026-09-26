"""Typed neutral payload projections; source capture time always bounds availability."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from maker_core.contracts import MarketDescriptor, OutcomeView, Unavailable, InfoEvent, SettlementFact
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import BundleError, CapturedRecord, timestamp

D = Decimal


def number(value, *, minimum=D(0), maximum=None):
    if isinstance(value, bool):
        raise BundleError("boolean_number")
    result = D(str(value))
    if not result.is_finite() or result < minimum or (maximum is not None and result > maximum):
        raise BundleError("invalid_numeric_payload")
    return result


def captured_time(value, record):
    result = timestamp(value)
    if result > record.captured_at:
        raise BundleError("payload_time_after_capture")
    return result


@dataclass(frozen=True)
class Descriptor:
    market: MarketDescriptor
    horizon_days: int
    factors: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True)
class Trade:
    trade_id: str
    outcome: str
    price: Decimal
    size: Decimal
    traded_at: datetime
    aggressor_side: str


@dataclass(frozen=True)
class Coverage:
    trade_stream_ok: bool
    valid_until_utc: datetime


def decode(row: CapturedRecord):
    """No IO, no provider queries and no inferred timestamps or market probabilities."""
    p = row.payload
    if row.kind == "coverage":
        until = timestamp(p["valid_until_utc"])
        if (type(p["trade_stream_ok"]) is not bool
                or not 0 < (until - row.captured_at).total_seconds() <= 60):
            raise BundleError("invalid_trade_coverage")
        return Coverage(p["trade_stream_ok"], until)
    if row.kind == "descriptor":
        m = dict(p["market"])
        m["close_at_utc"] = timestamp(m["close_at_utc"])
        m["settle_at_utc"] = timestamp(m["settle_at_utc"]) if m.get("settle_at_utc") else None
        m["tick"], m["min_order_size"] = number(m["tick"]), number(m["min_order_size"])
        market = MarketDescriptor(**m)
        horizon = p["horizon_days"]
        if type(horizon) is not int or not -1 <= horizon <= 366:
            raise BundleError("invalid_local_horizon")
        if market.condition_id != row.condition_id:
            raise BundleError("descriptor_identity_mismatch")
        factors = tuple(sorted((str(k), number(v, minimum=D("-1000000")))
                               for k, v in p.get("exposure_factors", {}).items()))
        return Descriptor(market, horizon, factors)
    if row.kind == "book":
        sides = []
        for side in ("yes_bids", "yes_asks", "no_bids", "no_asks"):
            levels = {}
            for price, size in p[side]:
                price, size = number(price, maximum=D(1)), number(size)
                if size == 0:
                    continue
                levels[price] = levels.get(price, D(0)) + size
            sides.append(tuple(sorted(levels.items(), reverse=side.endswith("bids"))))
        available = p.get("post_only_available", True)
        if type(available) is not bool:
            raise BundleError("invalid_post_only_flag")
        return Book(captured_time(p["as_of_utc"], row), *sides, available)
    if row.kind == "terms":
        return RewardTerms(captured_time(p["as_of_utc"], row), number(p["min_size"]),
                           number(p["max_spread_cents"]), number(p["rate_per_day"]))
    if row.kind == "outcome_view":
        value = dict(p["value"])
        value["as_of_utc"] = captured_time(value["as_of_utc"], row)
        if p["available"] is False:
            return Unavailable(**value)
        if p["available"] is not True:
            raise BundleError("invalid_view_availability")
        value["valid_until_utc"] = timestamp(value["valid_until_utc"])
        view = OutcomeView(**value)
        if view.condition_id != row.condition_id:
            raise BundleError("view_identity_mismatch")
        return view
    if row.kind == "info_event":
        events = []
        for raw in p["events"]:
            value = dict(raw)
            for key in ("scheduled_at_utc", "observed_at_utc", "detected_at_utc", "active_until_utc"):
                value[key] = timestamp(value[key]) if value.get(key) else None
            for key in ("observed_at_utc", "detected_at_utc"):
                if value[key] is not None and value[key] > row.captured_at:
                    raise BundleError("event_not_yet_observed")
            event = InfoEvent(**value)
            if row.condition_id not in event.affects:
                raise BundleError("event_identity_mismatch")
            events.append(event)
        return tuple(events)
    if row.kind == "settlement":
        value = dict(p)
        value["as_of_utc"] = captured_time(value["as_of_utc"], row)
        fact = SettlementFact(**value)
        if fact.condition_id != row.condition_id or fact.reconciliation_status != "reconciled":
            raise BundleError("unreconciled_settlement")
        return fact
    if row.kind == "trade":
        if (not isinstance(p["trade_id"], str) or not p["trade_id"]
                or p["outcome"] not in ("YES", "NO") or p["aggressor_side"] not in ("BUY", "SELL")):
            raise BundleError("invalid_trade_identity_or_side")
        size = number(p["size"])
        if not size:
            raise BundleError("zero_trade_size")
        return Trade(p["trade_id"], p["outcome"], number(p["price"], maximum=D(1)), size,
                     captured_time(p["traded_at_utc"], row), p["aggressor_side"])
    if row.kind == "plugin_input":
        return p  # Retained provenance; only the typed view enters decide().
    raise BundleError("unknown_payload_kind")
