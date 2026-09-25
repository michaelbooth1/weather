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

GAMMA_CHUNK_SIZE = 20


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


def portfolio_summary(balance, positions, orders, campaign_capital, *, resolved=(), inventory_complete=True):
    """Equity less owner-confirmed net contributions, never recent-trade P&L.

Campaign capital = initial equity + subsequent deposits - withdrawals. A
dedicated campaign wallet is required. Reward accrual is not added to cash.
"""
    cash = number(balance["cash_pusd"]) if balance is not None else None
    holdings = [*positions, *resolved]
    complete = inventory_complete and all(p.get("mark_value_pusd") is not None and p.get("unrealized_pnl_pusd") is not None
                                          for p in holdings)
    marked = sum((number(p["mark_value_pusd"]) for p in holdings), Decimal(0)) if complete else None
    unrealized = sum((number(p["unrealized_pnl_pusd"]) for p in holdings), Decimal(0)) if complete else None
    campaign = cash + marked - number(campaign_capital) if complete and cash is not None and campaign_capital is not None else None
    bleed = cash is not None and cash < 60 or campaign is not None and campaign < -40
    return dict(cash_pusd=str(cash) if cash is not None else None, positions=positions, open_orders=orders,
                marked_positions_pusd=str(marked) if marked is not None else None,
                unrealized_pnl_pusd=str(unrealized) if unrealized is not None else None,
                campaign_pnl_pusd=str(campaign) if campaign is not None else None,
                campaign_net_contributions_pusd=str(campaign_capital) if campaign_capital is not None else None,
                status="BLEED_LIMIT" if bleed else "INCOMPLETE" if campaign is None or orders is None else "OBSERVED",
                mark_basis="live_two_sided_mid_resolved_terminal_last_price", cache_seconds=30,
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

    def _position_rows(self):
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
                if number(row.get("size")) < 0 or not 0 <= number(row.get("avgPrice")) <= 1:
                    raise ReaderError("position_numeric_data_unreadable")
                result.append(row)
            if len(chunk) < 100:
                return result
        raise ReaderError("positions_incomplete")

    @staticmethod
    def _position_shell(row):
        size, average = number(row["size"]), number(row.get("avgPrice"))
        if not 0 <= average <= 1:
            raise ReaderError("position_price_unreadable")
        return dict(token_id=row["asset"], condition_id=row["conditionId"], title=row.get("title"),
                      outcome=row.get("outcome"), size=str(size), avg_price=str(average),
                      bid=None, ask=None, mid=None, mark_value_pusd=None,
                      unrealized_pnl_pusd=None, reward_min_size=None, reward_max_spread_cents=None,
                      reward_terms=None, errors=[])

    def _inventory(self):
        """Classify non-redeemable holdings in bounded chunks, then plan reads."""
        payload = dict(positions=[], resolved_positions=[], unclassified_positions=[], errors={},
                       inventory_complete=False, plan={})
        try:
            holdings = self._position_rows()
        except ReaderError:
            payload["errors"]["positions"] = "positions_unavailable"
            return payload
        payload["inventory_complete"] = True
        metadata = {}
        conditions = sorted({r["conditionId"].lower() for r in holdings if r.get("redeemable") is not True})
        for start in range(0, len(conditions), GAMMA_CHUNK_SIZE):
            chunk = conditions[start:start + GAMMA_CHUNK_SIZE]
            try:
                batch = rows(self.get(GAMMA, "/markets", condition_ids=chunk, limit=len(chunk)))
                chunk_metadata = {}
                for market in batch:
                    key = str(market.get("conditionId", "")).lower()
                    if key not in chunk or key in chunk_metadata:
                        raise ReaderError("metadata_identity_unreadable")
                    chunk_metadata[key] = market
                # Publish only a fully validated chunk; retain successful peers.
                metadata.update(chunk_metadata)
            except ReaderError:
                payload["errors"]["metadata"] = "classification_metadata_unavailable"
        live = []
        for row in holdings:
            market = metadata.get(row["conditionId"].lower(), {})
            result = self._position_shell(row)
            last = None
            try:
                last = number(row.get("curPrice"))
                if not 0 <= last <= 1:
                    last = None
            except ReaderError:
                pass
            # An expired date or a zero price alone does not prove resolution.
            # Gamma may still mark an overdue market active. Missing/conflicting
            # metadata stays unknown unless the venue says it is redeemable.
            result.update(redeemable=row.get("redeemable") is True,
                          last_price=str(last) if last is not None else None, end_date=row.get("endDate"))
            if row.get("redeemable") is True or market.get("closed") is True:
                result["classification"] = "resolved"
                result["classification_basis"] = "redeemable" if row.get("redeemable") is True else "gamma_closed"
                if last in (Decimal(0), Decimal(1)):
                    result.update(mark_value_pusd=str(number(row["size"]) * last),
                                  unrealized_pnl_pusd=str(number(row["size"]) * (last - number(row["avgPrice"]))))
                else:
                    result["errors"].append("resolved_value_unavailable")
                payload["resolved_positions"].append(result)
            elif market.get("closed") is False and market.get("active") is True:
                live.append((row, market, result, number(row["size"]) * (last if last is not None else number(row["avgPrice"]))))
            else:
                result.update(classification="unknown", errors=["classification_unavailable"])
                payload["unclassified_positions"].append(result)
                payload["inventory_complete"] = False
        # Prioritize the largest reported value, deterministic token tie-break.
        # Cached upstream reads cost zero; even failures are isolated by key.
        available = self.transport.remaining()
        planned = []
        for row, market, result, value in sorted(live, key=lambda item: (-item[3], item[0]["asset"])):
            calls = [(CLOB, "/book", {"token_id": row["asset"]}),
                     (CLOB, "/rewards/markets/" + row["conditionId"], {})]
            cost = sum(self.transport.request_cost(*call) for call in calls)
            admitted = cost <= available
            if admitted:
                available -= cost
            planned.append((row, market, result, admitted))
        payload["plan"] = dict(live_positions=len(live), resolved_positions=len(payload["resolved_positions"]),
                               planned_live_positions=sum(int(p[3]) for p in planned),
                               deferred_live_positions=sum(int(not p[3]) for p in planned))
        for row, market, result, admitted in planned:
            if not admitted:
                result.update(classification="live", errors=["budget_deferred"])
            else:
                result = self.mark_position(row, market, result)
            payload["positions"].append(result)
        payload["plan"]["deferred_live_positions"] = sum(
            "budget_deferred" in p["errors"] for p in payload["positions"])
        return payload

    @staticmethod
    def _visible_inventory(payload, include_resolved):
        result = dict(payload)
        result["resolved_count"] = len(payload["resolved_positions"])
        if not include_resolved:
            result.pop("resolved_positions")
        result["status"] = "PARTIAL" if (payload["errors"] or payload["unclassified_positions"]
                                         or any(p["errors"] for p in [*payload["positions"], *payload["resolved_positions"]])) else "OBSERVED"
        return result

    def positions(self, *, include_resolved=False):
        with self.transport.composite() as plan:
            payload = self._inventory()
            payload["plan"].update(max_gets=plan["max_gets"], used_gets=plan["used_gets"])
            return self._visible_inventory(payload, include_resolved)

    def mark_position(self, row, metadata, result):
        size, average = number(row["size"]), number(row["avgPrice"])
        result.update(classification="live", reward_min_size=metadata.get("rewardsMinSize"),
                      reward_max_spread_cents=metadata.get("rewardsMaxSpread"))
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
        except (ReaderError, AttributeError, TypeError) as exc:
            result["errors"].append("budget_deferred" if str(exc) == "upstream_minute_budget" else "book_mark_unavailable")
        try:
            result["reward_terms"] = self.get(CLOB, "/rewards/markets/" + row["conditionId"])
        except ReaderError as exc:
            error = "budget_deferred" if str(exc) == "upstream_minute_budget" else "reward_terms_unavailable"
            if error not in result["errors"]:
                result["errors"].append(error)
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

    def summary(self, *, include_resolved=False):
        with self.transport.composite() as plan:
            errors, balance, orders = {}, None, None
            try:
                balance = self.balance()
            except ReaderError:
                errors["cash"] = "balance_unavailable"
            try:
                orders = self.open_orders()
            except ReaderError:
                errors["open_orders"] = "open_orders_unavailable"
            inventory = self._inventory()
            result = portfolio_summary(balance, inventory["positions"], orders, self.campaign_capital,
                                       resolved=inventory["resolved_positions"],
                                       inventory_complete=inventory["inventory_complete"])
            result.update(errors={**errors, **inventory["errors"]},
                          unclassified_positions=inventory["unclassified_positions"],
                          resolved_count=len(inventory["resolved_positions"]),
                          plan={**inventory["plan"], "max_gets": plan["max_gets"], "used_gets": plan["used_gets"]})
            if include_resolved:
                result["resolved_positions"] = inventory["resolved_positions"]
            return result


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
