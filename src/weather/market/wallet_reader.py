"""Authenticated account reads and LAN CLI; no order-signing dependencies.

Owner startup and valuation assumptions: docs/operations/wallet-reader.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re

from weather.market.wallet_reader_security import (
    CLOB, DATA, GAMMA, CONDITION, ReaderError, lan_ip, load_owner_credentials,
)
from weather.market.wallet_reader_transport import ReadTransport


def number(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ReaderError("invalid_numeric_data") from None


def valid_date(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ReaderError("date_must_be_iso_day") from None
    return value


def valid_since(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}", value):
        raise ReaderError("since_must_be_unix_seconds")
    return value


def rows(value):
    if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
        raise ReaderError("rows_unreadable")
    return value


def portfolio_summary(balance, positions, orders, campaign_capital):
    """Equity less owner-confirmed net contributions, never recent-trade P&L.

Campaign capital = initial equity + subsequent deposits - withdrawals. A
dedicated campaign wallet is required. Reward accrual is not added to cash.
"""
    cash = number(balance["cash_pusd"])
    complete = all(p.get("mark_value_pusd") is not None and p.get("unrealized_pnl_pusd") is not None
                   for p in positions)
    marked = sum((number(p["mark_value_pusd"]) for p in positions), Decimal(0)) if complete else None
    unrealized = sum((number(p["unrealized_pnl_pusd"]) for p in positions), Decimal(0)) if complete else None
    campaign = cash + marked - number(campaign_capital) if complete and campaign_capital is not None else None
    bleed = cash < 60 or campaign is not None and campaign < -40
    return dict(cash_pusd=str(cash), positions=positions, open_orders=orders,
                marked_positions_pusd=str(marked) if marked is not None else None,
                unrealized_pnl_pusd=str(unrealized) if unrealized is not None else None,
                campaign_pnl_pusd=str(campaign) if campaign is not None else None,
                campaign_net_contributions_pusd=str(campaign_capital) if campaign_capital is not None else None,
                status="BLEED_LIMIT" if bleed else "INCOMPLETE" if campaign is None else "OBSERVED",
                mark_basis="two_sided_mid_not_liquidation_value", cache_seconds=30,
                captured_at_utc=datetime.now(timezone.utc).isoformat())


class WalletReader:
    def __init__(self, transport, *, signature_type, campaign_capital=None):
        if signature_type not in (2, 3):
            raise ReaderError("signature_type_must_be_2_or_3")
        if campaign_capital is not None and number(campaign_capital) < 0:
            raise ReaderError("negative_campaign_capital")
        self.transport = transport
        self.signature_type = signature_type
        self.campaign_capital = campaign_capital
        self.funder = transport.fields["FUNDER_ADDRESS"]

    def get(self, host, path, **params):
        return self.transport.request("GET", host, path, params)

    def pages(self, path, **params):
        found, seen = [], set()
        for _ in range(5):
            page = self.get(CLOB, path, **params)
            if not isinstance(page, dict):
                raise ReaderError("page_unreadable")
            found.extend(rows(page.get("data")))
            cursor = page.get("next_cursor")
            if len(found) > 2500:
                raise ReaderError("row_budget")
            if cursor == "LTE=":
                return found
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ReaderError("cursor_unreadable")
            seen.add(cursor)
            params["next_cursor"] = cursor
        raise ReaderError("pagination_incomplete")

    def balance(self):
        payload = self.get(CLOB, "/balance-allowance", asset_type="COLLATERAL",
                           signature_type=self.signature_type)
        if not isinstance(payload, dict):
            raise ReaderError("balance_unreadable")
        units = number(payload.get("balance"))
        if units < 0 or units != units.to_integral_value():
            raise ReaderError("balance_unreadable")
        return {"cash_pusd": str(units / 1_000_000), "source": "clob_balance_allowance_read",
                "cache_seconds": 30}

    def open_orders(self):
        result = self.pages("/data/orders")
        if any(str(r.get("maker_address", "")).lower() != self.funder.lower() for r in result):
            raise ReaderError("order_account_mismatch")
        return result

    def positions(self):
        result, tokens = [], set()
        for page in range(5):
            chunk = rows(self.get(DATA, "/positions", user=self.funder, sizeThreshold=0,
                                  limit=100, offset=page * 100))
            for row in chunk:
                token, condition = row.get("asset"), row.get("conditionId")
                if (str(row.get("proxyWallet", "")).lower() != self.funder.lower()
                        or not isinstance(token, str) or not re.fullmatch(r"[0-9]{1,78}", token)
                        or not isinstance(condition, str) or not CONDITION.fullmatch(condition)
                        or token in tokens):
                    raise ReaderError("position_identity_unreadable")
                tokens.add(token)
                if number(row.get("size")) < 0:
                    raise ReaderError("position_size_unreadable")
                result.append(row)
            if len(chunk) < 100:
                return [self.mark_position(r) for r in result]
        raise ReaderError("positions_incomplete")

    def mark_position(self, row):
        size, average = number(row["size"]), number(row.get("avgPrice"))
        if not 0 <= average <= 1:
            raise ReaderError("position_price_unreadable")
        result = dict(token_id=row["asset"], condition_id=row["conditionId"], title=row.get("title"),
                      outcome=row.get("outcome"), size=str(size), avg_price=str(average),
                      bid=None, ask=None, mid=None, mark_value_pusd=None,
                      unrealized_pnl_pusd=None, reward_min_size=None, reward_max_spread_cents=None,
                      reward_terms=None, errors=[])
        try:
            book = self.get(CLOB, "/book", token_id=row["asset"])
            if (book.get("asset_id", book.get("token_id")) != row["asset"]
                    or str(book.get("market", "")).lower() != row["conditionId"].lower()):
                raise ReaderError("book_identity_unreadable")
            levels = []
            for side in ("bids", "asks"):
                prices = []
                for level in rows(book.get(side)):
                    price, quantity = number(level.get("price")), number(level.get("size"))
                    if not 0 <= price <= 1 or quantity < 0:
                        raise ReaderError("book_level_unreadable")
                    if quantity > 0:
                        prices.append(price)
                levels.append(prices)
            bid = max(levels[0]) if levels[0] else None
            ask = min(levels[1]) if levels[1] else None
            result.update(bid=str(bid) if bid is not None else None, ask=str(ask) if ask is not None else None)
            if bid is None or ask is None or bid > ask:
                raise ReaderError("two_sided_mark_unavailable")
            mid = (bid + ask) / 2
            result.update(mid=str(mid), mark_value_pusd=str(size * mid),
                          unrealized_pnl_pusd=str(size * (mid - average)))
        except (ReaderError, AttributeError, TypeError):
            result["errors"].append("book_mark_unavailable")
        try:
            metadata = rows(self.get(GAMMA, "/markets", condition_ids=row["conditionId"], limit=2))
            if len(metadata) != 1 or str(metadata[0].get("conditionId", "")).lower() != row["conditionId"].lower():
                raise ReaderError("metadata_identity_unreadable")
            result.update(reward_min_size=metadata[0].get("rewardsMinSize"),
                          reward_max_spread_cents=metadata[0].get("rewardsMaxSpread"))
            result["reward_terms"] = self.get(CLOB, "/rewards/markets/" + row["conditionId"])
        except ReaderError:
            result["errors"].append("reward_terms_unavailable")
        return result

    def trades(self, since):
        valid_since(since)
        # Authenticated fills are exhaustive within the bounded cursor walk.
        # Public trades/activity are explicitly recent pages, never a P&L ledger.
        return {"fills": self.pages("/data/trades", maker_address=self.funder, after=since),
                "recent_public_trades": rows(self.get(DATA, "/trades", user=self.funder, limit=100,
                                                      offset=0, takerOnly="false")),
                "recent_activity": rows(self.get(DATA, "/activity", user=self.funder, limit=100,
                                                 offset=0, start=since, sortBy="TIMESTAMP", sortDirection="DESC")),
                "public_history_scope": "latest_100_not_complete_history"}

    def rewards(self, day):
        valid_date(day)
        return {"date": day, "earnings": self.pages("/rewards/user", date=day,
                                                    signature_type=self.signature_type),
                "total": self.get(CLOB, "/rewards/user/total", date=day, signature_type=self.signature_type),
                "percentages": self.get(CLOB, "/rewards/user/percentages", signature_type=self.signature_type),
                "payment_verified": False}

    def summary(self):
        balance, orders, positions = self.balance(), self.open_orders(), self.positions()
        return portfolio_summary(balance, positions, orders, self.campaign_capital)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Owner-started authenticated read-only LAN service")
    serve.add_argument("--bind", required=True)
    serve.add_argument("--allow", required=True, help="Exact production PC RFC1918 IPv4")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--signature-type", type=int, choices=(2, 3), required=True,
                       help="Owner-confirmed existing wallet type: 2 Safe, 3 deposit wallet")
    serve.add_argument("--campaign-capital", help="Dedicated campaign wallet net contributed pUSD; omit for unknown P&L")
    args = parser.parse_args(argv)
    try:
        lan_ip(args.bind)
        lan_ip(args.allow)
        if not 1 <= args.port <= 65535:
            raise ReaderError("port_invalid")
        if args.campaign_capital is not None and number(args.campaign_capital) < 0:
            raise ReaderError("negative_campaign_capital")
        fields, guard = load_owner_credentials()
        reader = WalletReader(ReadTransport(fields, guard), signature_type=args.signature_type,
                              campaign_capital=args.campaign_capital)
        from weather.market.wallet_reader_server import serve_reader
        serve_reader(reader, guard, fields["READER_TOKEN"], bind=args.bind, allow=args.allow, port=args.port)
    except KeyboardInterrupt:
        return 0
    except Exception:
        print(json.dumps({"error": "wallet_reader_failed"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
