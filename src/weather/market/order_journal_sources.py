"""Read-only inputs for the manual order journal: LAN reader and public CLOB.

The reader side is ``wallet_reader_client.read_account`` (fixed GET routes, the
existing client token file). The public side is a GET-only fetcher bound to the
public CLOB host and four exact paths with no auth headers, proxies, redirects or
retries. Every public request sends an explicit browser-style User-Agent: the
urllib default is refused with HTTP 403 (the RE-1 / 88a lesson). Nothing here can
place, cancel or sign an order.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time
from urllib.parse import urlencode

from weather.market.wallet_reader_security import CLOB, CONDITION

TOKEN = re.compile(r"[0-9]{1,78}\Z")
PUBLIC_QUERY = {
    "/book": {"token_id"},
    "/prices-history": {"market", "startTs", "endTs", "fidelity"},
}
MAX_BODY = 2_000_000
PUBLIC_TIMEOUT = 10
BOOK_LEVELS = 5
PUBLIC_USER_AGENT = "Mozilla/5.0 weather-manual-order-journal/1"


class SourceError(RuntimeError):
    """Fixed, data-free failure codes."""


def dec(value):
    try:
        if isinstance(value, bool) or value is None:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise SourceError("numeric_unreadable") from None


def text(value):
    """Canonical decimal text without exponent or float drift."""
    return format(dec(value).normalize(), "f")


def check_public(path, params):
    keys = PUBLIC_QUERY.get(path)
    if keys is None and (path.startswith("/rewards/markets/") and CONDITION.fullmatch(path[17:])
                         or path.startswith("/markets/") and CONDITION.fullmatch(path[9:])):
        keys = set()
    if keys is None or not isinstance(params, dict) or not set(params) <= keys:
        raise SourceError("public_request_refused")
    for key, value in params.items():
        if key in {"token_id", "market"} and not (isinstance(value, str) and TOKEN.fullmatch(value)):
            raise SourceError("public_request_refused")
        if key in {"startTs", "endTs", "fidelity"} and (isinstance(value, bool) or not isinstance(value, int)
                                                        or not 0 <= value < 10**11):
            raise SourceError("public_request_refused")


class PublicClob:
    """Bounded GET-only public CLOB reads; ``opener`` is injectable for fixtures."""

    def __init__(self, *, budget, deadline_seconds, opener=None, clock=time.monotonic):
        self.budget, self.used = budget, 0
        self.clock = clock
        self.deadline = clock() + deadline_seconds
        self.opener = opener
        self.hashes = {}

    def get(self, path, **params):
        check_public(path, params)
        if self.used >= self.budget or self.clock() >= self.deadline:
            raise SourceError("public_budget_exhausted")
        self.used += 1
        target = CLOB + path + ("?" + urlencode(params) if params else "")
        from urllib.request import ProxyHandler, Request, build_opener

        from weather.market.wallet_reader_transport import NoRedirect
        opener = self.opener or build_opener(ProxyHandler({}), NoRedirect())
        request = Request(target, method="GET", headers={"Accept": "application/json",
                                                           "User-Agent": PUBLIC_USER_AGENT})
        try:
            with opener.open(request, timeout=PUBLIC_TIMEOUT) as response:
                raw = response.read(MAX_BODY + 1)
                if response.geturl() != target or len(raw) > MAX_BODY or response.status != 200:
                    raise SourceError("public_response_refused")
        except SourceError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            raise SourceError(f"public_http_{code}" if isinstance(code, int) else "public_unreachable") from None
        self.hashes[path] = hashlib.sha256(raw).hexdigest()
        try:
            return json.loads(raw)
        except ValueError:
            raise SourceError("public_json_unreadable") from None


def book_view(payload):
    """Best levels, mid and spread from a public ``/book`` reply."""
    if not isinstance(payload, dict):
        raise SourceError("book_unreadable")
    sides = {}
    for name, best in (("bids", max), ("asks", min)):
        levels = []
        for level in payload.get(name) or []:
            price, size = dec(level.get("price")), dec(level.get("size"))
            if size > 0:
                levels.append((price, size))
        levels.sort(key=lambda row: row[0], reverse=name == "bids")
        sides[name] = levels
    bid = sides["bids"][0][0] if sides["bids"] else None
    ask = sides["asks"][0][0] if sides["asks"] else None
    two_sided = bid is not None and ask is not None and bid < ask
    return dict(best_bid=text(bid) if bid is not None else None, best_ask=text(ask) if ask is not None else None,
                mid=text((bid + ask) / 2) if two_sided else None,
                spread=text(ask - bid) if two_sided else None,
                bids=[[text(p), text(s)] for p, s in sides["bids"][:BOOK_LEVELS]],
                asks=[[text(p), text(s)] for p, s in sides["asks"][:BOOK_LEVELS]],
                book_timestamp=payload.get("timestamp"), tick_size=payload.get("tick_size"))


def reward_terms_view(payload):
    """Current reward program terms for one condition from ``/rewards/markets``."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return dict(active=False, daily_rate=None, max_spread_cents=None, min_size=None)
    row = rows[0]
    rate = row.get("rewards_daily_rate")
    if rate is None and isinstance(row.get("rewards_config"), list):
        rates = [c.get("rate_per_day") for c in row["rewards_config"] if isinstance(c, dict)]
        rate = sum((dec(r) for r in rates if r is not None), Decimal(0)) if rates else None
    return dict(active=True, daily_rate=text(rate) if rate is not None else None,
                max_spread_cents=text(row["rewards_max_spread"]) if row.get("rewards_max_spread") is not None else None,
                min_size=text(row["rewards_min_size"]) if row.get("rewards_min_size") is not None else None)


def reward_earnings_view(payload):
    """Per-condition earnings, total and pool percentages from reader ``/rewards``."""
    if not isinstance(payload, dict):
        raise SourceError("rewards_unreadable")
    by_condition = {}
    for row in payload.get("earnings") or []:
        if not isinstance(row, dict):
            raise SourceError("rewards_unreadable")
        key = row.get("condition_id") if isinstance(row.get("condition_id"), str) else "unattributed"
        by_condition[key] = by_condition.get(key, Decimal(0)) + dec(row.get("earnings"))
    total = payload.get("total")
    if isinstance(total, list):
        total = sum((dec(r.get("earnings")) for r in total if isinstance(r, dict)), Decimal(0))
    elif isinstance(total, dict):
        total = total.get("earnings")
    percentages = payload.get("percentages")
    percentages = ({k: text(v) for k, v in percentages.items() if isinstance(k, str)}
                   if isinstance(percentages, dict) else {})
    return dict(date=payload.get("date"), by_condition={k: text(v) for k, v in sorted(by_condition.items())},
                total=text(total) if total is not None else None, percentages=percentages,
                payment_verified=False)


def order_view(row):
    """Compact open order; raises on any unreadable identity or number."""
    order_id, token, condition = row.get("id"), str(row.get("asset_id", "")), row.get("market")
    side = str(row.get("side", "")).upper()
    if (not isinstance(order_id, str) or not order_id or not TOKEN.fullmatch(token)
            or not isinstance(condition, str) or not CONDITION.fullmatch(condition) or side not in {"BUY", "SELL"}):
        raise SourceError("order_identity_unreadable")
    price, size, matched = dec(row.get("price")), dec(row.get("original_size")), dec(row.get("size_matched", 0))
    if not 0 < price < 1 or size <= 0 or not 0 <= matched <= size:
        raise SourceError("order_numeric_unreadable")
    return dict(order_id=order_id, condition_id=condition, token_id=token, side=side,
                outcome=row.get("outcome"), price=text(price), original_size=text(size),
                size_matched=text(matched), status=row.get("status"), created_at=row.get("created_at"),
                order_type=row.get("order_type"), maker_address=str(row.get("maker_address", "")).lower())


def trade_fills(trade, own_orders, own_addresses):
    """Our legs of one CLOB trade: the taker leg, or matched maker orders."""
    trade_id, when = trade.get("id"), trade.get("match_time")
    if not isinstance(trade_id, str) or not trade_id or not re.fullmatch(r"[0-9]{1,12}", str(when)):
        raise SourceError("trade_identity_unreadable")
    legs = []
    if str(trade.get("trader_side", "")).upper() == "TAKER":
        legs.append(dict(order_id=trade.get("taker_order_id"), token_id=str(trade.get("asset_id")),
                         condition_id=trade.get("market"), side=str(trade.get("side", "")).upper(),
                         price=trade.get("price"), size=trade.get("size"), outcome=trade.get("outcome"),
                         liquidity_role="taker"))
    else:
        for maker in trade.get("maker_orders") or []:
            if not isinstance(maker, dict):
                raise SourceError("trade_identity_unreadable")
            if maker.get("order_id") in own_orders or str(maker.get("maker_address", "")).lower() in own_addresses:
                legs.append(dict(order_id=maker.get("order_id"), token_id=str(maker.get("asset_id")),
                                 condition_id=trade.get("market"), side=str(maker.get("side", "")).upper(),
                                 price=maker.get("price"), size=maker.get("matched_amount"),
                                 outcome=maker.get("outcome"), liquidity_role="maker"))
    fills = []
    for leg in legs:
        if (not TOKEN.fullmatch(leg["token_id"]) or leg["side"] not in {"BUY", "SELL"}
                or not isinstance(leg["condition_id"], str) or not CONDITION.fullmatch(leg["condition_id"])):
            raise SourceError("trade_identity_unreadable")
        price, size = dec(leg["price"]), dec(leg["size"])
        if not 0 < price < 1 or size <= 0:
            raise SourceError("trade_numeric_unreadable")
        fills.append(dict(leg, price=text(price), size=text(size), trade_id=trade_id, fill_time=int(when),
                          fill_key=f"{trade_id}:{leg['order_id'] or 'none'}:{leg['token_id']}", source="reader_trades",
                          trade_status=trade.get("status")))
    return fills
