"""Read-only journal of the owner's manual resting orders (``owner-discretionary``).

    python -m weather.market.order_journal record --out <dir>
    python -m weather.market.order_journal verify --out <dir>
    python -m weather.market.order_journal report --out <dir> [--json <path>] [--markdown <path>]

Each ``record`` run appends one hash-chained line: open orders, their books and
reward terms, reward earnings and pool shares, cash and positions, newly detected
fills and any markouts that came due. Carried-forward ``state`` lets a run read
only the journal tail. Runbook: docs/operations/manual-order-journal.md.
No order, cancel or signing path exists here; manual orders never enter
automated campaign data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sys

from weather.market.order_journal_io import JournalError, append_record, verify_chain
from weather.market.order_journal_sources import (
    PublicClob, SourceError, book_view, dec, order_view, reward_earnings_view, reward_terms_view, text,
    trade_fills,
)
from weather.schema_registry import schema_version

SCOPE = "owner-discretionary"
HORIZONS = (("5m", 300), ("30m", 1800))
MARKOUT_GRACE = 60
MARK_WINDOW = 900
MARKOUT_GIVE_UP = 6 * 3600
SETTLEMENT_RECHECK = 3600
PRIOR_REWARDS_RECHECK = 3600
TRADES_OVERLAP = 3600
FIRST_TRADES_LOOKBACK = 86400
KEEP_SECONDS = 3 * 86400
PUBLIC_BUDGET = 40
PUBLIC_DEADLINE = 150
EPSILON = Decimal("0.000001")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def empty_state():
    return dict(orders={}, account_addresses=[], fill_keys={}, pending=[], settlement_checked_at={},
                prior_rewards={}, trades_ok_at=None)


class Recorder:
    """Builds one record from injectable reader/public callables."""

    def __init__(self, reader, public, now):
        self.reader, self.public, self.now = reader, public, int(now)
        self.errors = {}

    def _read(self, key, command, **kwargs):
        try:
            return self.reader(command, **kwargs)
        except Exception as exc:
            self.errors[key] = getattr(exc, "reason", None) or type(exc).__name__
            return None

    def _public(self, key, path, **params):
        try:
            return self.public.get(path, **params)
        except SourceError as exc:
            self.errors[key] = str(exc)
            return None

    def build(self, tail):
        state = json.loads(json.dumps((tail or {}).get("state") or empty_state()))
        now = self.now
        today = datetime.fromtimestamp(now, timezone.utc).date()
        rewards = []
        for day, key in ((today, "rewards_today"), (today - timedelta(days=1), "rewards_prior_day")):
            last = state["prior_rewards"].get(day.isoformat()) if key == "rewards_prior_day" else None
            if last is not None and now - last < PRIOR_REWARDS_RECHECK:
                continue
            payload = self._read(key, "rewards", day=day.isoformat())
            if payload is not None:
                try:
                    rewards.append(reward_earnings_view(payload))
                    if key == "rewards_prior_day":
                        state["prior_rewards"] = {day.isoformat(): now}
                except SourceError as exc:
                    self.errors[key] = str(exc)
        since = (state["trades_ok_at"] - TRADES_OVERLAP) if state["trades_ok_at"] else now - FIRST_TRADES_LOOKBACK
        trades = self._read("trades", "trades", since=str(max(0, since)))
        summary = self._read("summary", "summary")

        orders = None
        if summary is not None:
            try:
                raw = summary.get("open_orders")
                orders = [order_view(r) for r in raw] if isinstance(raw, list) else None
                if orders is None:
                    self.errors["open_orders"] = "unavailable"
            except (SourceError, AttributeError):
                self.errors["open_orders"] = "unreadable"
        addresses = set(state["account_addresses"]) | {o["maker_address"] for o in orders or [] if o["maker_address"]}
        state["account_addresses"] = sorted(addresses)

        books, terms = {}, {}
        for order in orders or []:
            token, condition = order["token_id"], order["condition_id"]
            if token not in books:
                payload = self._public(f"book:{token}", "/book", token_id=token)
                try:
                    books[token] = book_view(payload) if payload is not None else None
                except SourceError as exc:
                    books[token], self.errors[f"book:{token}"] = None, str(exc)
            if condition not in terms:
                payload = self._public(f"reward_terms:{condition}", "/rewards/markets/" + condition)
                terms[condition] = reward_terms_view(payload) if payload is not None else None

        fills, events = self._fills(state, orders, trades, books)
        markouts = self._markouts(state, fills)
        self._prune(state)
        return dict(
            schema_version=schema_version("manual_order_journal"), scope=SCOPE,
            mode="read_only_manual_order_journal", recorded_at_utc=iso(now),
            cash_pusd=(summary or {}).get("cash_pusd"),
            positions=[{k: p.get(k) for k in ("token_id", "condition_id", "outcome", "size", "avg_price", "title")}
                       for p in (summary or {}).get("positions") or [] if isinstance(p, dict)],
            open_orders=orders, books=books, reward_terms=terms, rewards=rewards,
            fills=fills, order_events=events, markouts=markouts,
            reads=dict(summary=summary is not None, trades=trades is not None,
                       public_gets_used=self.public.used, public_budget=self.public.budget),
            errors=dict(sorted(self.errors.items())), state=state)

    def _fills(self, state, orders, trades, books):
        now, known = self.now, state["orders"]
        fills, events = [], []
        if trades is not None:
            rows = trades.get("fills") if isinstance(trades, dict) else None
            try:
                if not isinstance(rows, list):
                    raise SourceError("trades_unreadable")
                own = set(known) | {o["order_id"] for o in orders or []}
                for trade in rows:
                    for fill in trade_fills(trade, own, set(state["account_addresses"])):
                        if fill["fill_key"] not in state["fill_keys"]:
                            fills.append(fill)
                state["trades_ok_at"] = now
            except (SourceError, AttributeError) as exc:
                self.errors["trades"] = str(exc) if isinstance(exc, SourceError) else "trades_unreadable"
                trades, fills = None, []
        current = {o["order_id"]: o for o in orders or []}
        for fill in fills:
            record = known.get(fill["order_id"]) or current.get(fill["order_id"]) or {}
            if fill["order_id"] in known:
                known[fill["order_id"]]["attributed_size"] = text(dec(known[fill["order_id"]]["attributed_size"])
                                                                  + dec(fill["size"]))
            fill.update(reference_mid=record.get("mid"), reference_mid_at=record.get("mid_at"),
                        attributed_to_known_order=fill["order_id"] in known)
        if orders is not None:
            for order_id, order in current.items():
                prior = known.get(order_id)
                if prior is None:
                    events.append(dict(order_id=order_id, event="appeared", at=iso(now)))
                    prior = known[order_id] = dict(order, attributed_size=text(order["size_matched"]),
                                                   first_seen=iso(now), delta_seen=None)
                    # Matching before the first sighting is outside the journal.
                prior.update({k: order[k] for k in ("size_matched", "status")}, last_seen=iso(now), closed_at=None)
                excess = dec(order["size_matched"]) - dec(prior["attributed_size"])
                if trades is not None and excess > EPSILON:
                    # Confirm across two trade-readable runs so a lagging trade row is not double-counted.
                    if prior.get("delta_seen"):
                        fills.append(dict(order_id=order_id, token_id=order["token_id"],
                                          condition_id=order["condition_id"], side=order["side"],
                                          outcome=order["outcome"], price=order["price"], size=text(excess),
                                          liquidity_role="maker", trade_id=None, source="order_delta",
                                          fill_time=int(datetime.fromisoformat(prior["delta_seen"].replace("Z", "+00:00")).timestamp()),
                                          fill_time_bound="first_seen_no_later_than",
                                          fill_key=f"delta:{order_id}:{order['size_matched']}",
                                          reference_mid=prior.get("mid"), reference_mid_at=prior.get("mid_at"),
                                          attributed_to_known_order=True))
                        prior.update(attributed_size=order["size_matched"], delta_seen=None)
                    else:
                        prior["delta_seen"] = iso(now)
                elif excess <= EPSILON:
                    prior["delta_seen"] = None
                book = books.get(order["token_id"])
                if book and book.get("mid") is not None:
                    prior.update(mid=book["mid"], mid_at=iso(now))
            for order_id, prior in known.items():
                if order_id not in current and not prior.get("closed_at"):
                    prior["closed_at"] = iso(now)
                    events.append(dict(order_id=order_id, event="closed", at=iso(now),
                                       unattributed_size=text(dec(prior["original_size"]) - dec(prior["attributed_size"]))))
        for fill in fills:
            fill["scope"] = SCOPE
            state["fill_keys"][fill["fill_key"]] = fill["fill_time"]
            state["pending"].append(dict({k: fill[k] for k in ("fill_key", "token_id", "condition_id", "side",
                                                               "price", "size", "fill_time")},
                                         needs=[h for h, _ in HORIZONS] + ["settlement"]))
        return fills, events

    def _markouts(self, state, fills):
        now, results = self.now, []
        by_token = {}
        for item in state["pending"]:
            for horizon, seconds in HORIZONS:
                if horizon in item["needs"] and now >= item["fill_time"] + seconds + MARKOUT_GRACE:
                    by_token.setdefault(item["token_id"], []).append((item, horizon, item["fill_time"] + seconds))
        for token, due in sorted(by_token.items()):
            start, end = min(t for *_, t in due) - MARK_WINDOW, max(t for *_, t in due) + MARK_WINDOW
            payload = self._public(f"prices_history:{token}", "/prices-history", market=token,
                                   startTs=start, endTs=end, fidelity=1)
            history = payload.get("history") if isinstance(payload, dict) else None
            if not isinstance(history, list):
                continue  # deferred: a missing or unreadable reply never gives a markout up
            for item, horizon, target in due:
                point = mark_point(history, target)
                if point is None and now - target < MARKOUT_GIVE_UP:
                    continue
                results.append(markout(item, horizon, point, target, "prices_history"))
                item["needs"].remove(horizon)
        conditions = sorted({i["condition_id"] for i in state["pending"] if "settlement" in i["needs"]})
        for condition in conditions:
            if now - state["settlement_checked_at"].get(condition, 0) < SETTLEMENT_RECHECK:
                continue
            payload = self._public(f"market:{condition}", "/markets/" + condition)
            if payload is None:
                continue
            state["settlement_checked_at"][condition] = now
            winners = settled_tokens(payload)
            if winners is None:
                continue
            for item in state["pending"]:
                if item["condition_id"] == condition and "settlement" in item["needs"]:
                    price = "1" if item["token_id"] in winners else "0"
                    results.append(markout(item, "settlement", (now, price), None, "clob_market_winner"))
                    item["needs"].remove("settlement")
        state["pending"] = [i for i in state["pending"] if i["needs"]]
        return results

    def _prune(self, state):
        cutoff = self.now - KEEP_SECONDS
        # Keep every key the next trades lookback can still return, however long the reader was down.
        lookback = (state["trades_ok_at"] or self.now) - TRADES_OVERLAP - 3600
        state["fill_keys"] = {k: v for k, v in state["fill_keys"].items() if v >= min(cutoff, lookback)}
        state["orders"] = {k: v for k, v in state["orders"].items()
                           if not v.get("closed_at") or v["closed_at"] >= iso(cutoff)}
        pending = {i["condition_id"] for i in state["pending"]}
        state["settlement_checked_at"] = {k: v for k, v in state["settlement_checked_at"].items() if k in pending}


def mark_point(history, target):
    """Last point at or before target within the window, else the first after."""
    points = []
    for row in history:
        try:
            points.append((int(row["t"]), dec(row["p"])))
        except (KeyError, TypeError, ValueError, SourceError):
            continue
    before = [p for p in points if target - MARK_WINDOW <= p[0] <= target]
    after = [p for p in points if target < p[0] <= target + MARK_WINDOW]
    if before:
        return max(before)
    return min(after) if after else None


def settled_tokens(payload):
    """Winning token ids of a closed market with exactly one winner, else None."""
    if not isinstance(payload, dict) or payload.get("closed") is not True or not isinstance(payload.get("tokens"), list):
        return None
    winners = {str(t.get("token_id")) for t in payload["tokens"] if isinstance(t, dict) and t.get("winner") is True}
    return winners if len(winners) == 1 else None


def markout(item, horizon, point, target, source):
    """Per-share and total markout, signed so positive favours the order."""
    base = dict(fill_key=item["fill_key"], horizon=horizon, source=source, scope=SCOPE,
                target_time=iso(target) if target is not None else None)
    if point is None:
        return dict(base, mark_price=None, mark_time=None, per_share=None, pusd=None, status="unavailable")
    price = dec(point[1])
    per_share = price - dec(item["price"]) if item["side"] == "BUY" else dec(item["price"]) - price
    return dict(base, mark_price=text(price), mark_time=iso(point[0]), per_share=text(per_share),
                pusd=text(per_share * dec(item["size"])), status="observed")


def record(out, *, reader=None, public=None, now=None, reader_config=None):
    if reader is None:
        from weather.market.wallet_reader_client import read_account

        def reader(command, **kwargs):
            return read_account(command, config=reader_config, **kwargs)
    public = public or PublicClob(budget=PUBLIC_BUDGET, deadline_seconds=PUBLIC_DEADLINE)
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    row, path, digest = append_record(out, Recorder(reader, public, now).build)
    return dict(status="recorded", sequence=row["sequence"], path=str(path), sha256=digest,
                open_orders=None if row["open_orders"] is None else len(row["open_orders"]),
                fills=len(row["fills"]), markouts=len(row["markouts"]), errors=sorted(row["errors"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "verify", "report"):
        command = sub.add_parser(name)
        command.add_argument("--out", required=True, help="Journal directory (one <UTC-date>.jsonl per day).")
        if name == "record":
            command.add_argument("--reader-config", help="Wallet reader client JSON (default config/local/wallet_reader_client.json).")
        if name == "report":
            command.add_argument("--json", help="Write the report JSON here.")
            command.add_argument("--markdown", help="Write the Markdown report here.")
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            result = record(args.out, reader_config=args.reader_config)
        elif args.command == "verify":
            records, head = verify_chain(args.out)
            result = dict(status="verified", records=len(records), head_sha256=head)
        else:
            from weather.market.order_journal_report import build_report, write_report
            report = build_report(verify_chain(args.out)[0])
            write_report(report, json_path=args.json, markdown_path=args.markdown)
            result = dict(status="reported", markets=len(report["markets"]), orders=len(report["orders"]))
    except JournalError as exc:
        print(json.dumps(dict(status="refused", reason=str(exc))))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
