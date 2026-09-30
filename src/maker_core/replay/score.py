"""Counterfactual band/UTC-day accounting; missing observations stay missing.

Bought-side mark-price, nominal .25*.05*p*(1-p), and the first-at/after
horizon lookup with 120s tolerance are copied from execution_tape_markout's
pure logic. No account rebates or reward payments are inferred from this model.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

HORIZONS = {"1m": 60, "5m": 300, "30m": 1800}
MARK_TOLERANCE_SECONDS = 120


def nominal_rebate(price):
    return D(".25") * D(".05") * price * (1 - price)


def _parts(start, end):
    """Split continuous inventory holding and quote exposure at UTC midnight."""
    while start < end:
        boundary = datetime.combine(start.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        stop = min(end, boundary)
        yield start.date().isoformat(), D(str((stop - start).total_seconds()))
        start = stop


class Marks:
    def __init__(self, books):
        self.points = defaultdict(list)
        for at, cid, book in books:
            for outcome, bids, asks in (("YES", book.yes_bids, book.yes_asks),
                                         ("NO", book.no_bids, book.no_asks)):
                if bids and asks:
                    bid, ask = max(p for p, _ in bids), min(p for p, _ in asks)
                    if bid <= ask:
                        self.points[cid, outcome].append((at, (bid + ask) / 2))
        self.times = {}
        for key, points in self.points.items():
            points.sort(key=lambda p: p[0])
            self.times[key] = [p[0] for p in points]

    def at_horizon(self, fill, seconds):
        key = fill.condition_id, fill.outcome
        target = fill.at + timedelta(seconds=seconds)
        points, times = self.points[key], self.times.get(key, [])
        index = bisect_left(times, target)
        if index < len(times) and (times[index] - target).total_seconds() <= MARK_TOLERANCE_SECONDS:
            return points[index][1]
        return None


def score(result, *, check=lambda: None):
    """Return deterministic rows; settlement P&L is attributed to the fill date.

    Net sensitivities sum modeled rewards, nominal rebate and settled inventory
    P&L. They are null for excluded exposure or any unresolved fill. Markouts are
    alternative valuations, never added to settlement P&L.
    """
    rows = {}
    def row(day, cid, market):
        key = day, cid
        if key not in rows:
            rows[key] = dict(date=day, condition_id=cid, market_id=market, policy=result.config.policy,
                fill_bound=result.config.fill_bound, active_seconds=D(0), covered_seconds=D(0),
                excluded_seconds=D(0), pulled_seconds=D(0), reward_k1=D(0), reward_k05=D(0),
                nominal_rebate=D(0), maker_fees=D(0), cash_hours=D(0), reserved_cash_hours=D(0),
                inventory_cash_hours=D(0), fills=0, fills_in_events=0, fills_outside_events=0,
                filled_shares=D(0), unresolved_fills=0, settled_inventory_pnl=D(0), quotes=0, requotes=0,
                markouts={h: dict(pnl=D(0), shares=D(0), missing_fills=0) for h in (*HORIZONS, "settlement")})
        return rows[key]
    markets = {}
    for span in result.spans:
        check()
        markets[span.condition_id] = span.market_id
        for day, seconds in _parts(span.start, span.end):
            check()
            r = row(day, span.condition_id, span.market_id)
            r["reserved_cash_hours"] += span.reserved * seconds / 3600
            r["inventory_cash_hours"] += span.inventory_cost * seconds / 3600
            if not span.evaluation_active:
                continue
            r["active_seconds"] += seconds
            if not span.covered:
                r["excluded_seconds"] += seconds
                continue
            r["covered_seconds"] += seconds
            if not span.legs:
                r["pulled_seconds"] += seconds
            else:
                r["reward_k1"] += span.rate_per_day * D(str(span.share_many)) * seconds / 86400
    seen_quotes = set()
    for event in result.decisions:
        check()
        if event.decision.action != "QUOTE":
            continue
        r = row(event.at.date().isoformat(), event.condition_id, markets[event.condition_id])
        r["quotes"] += 1
        r["requotes"] += int(event.condition_id in seen_quotes)
        seen_quotes.add(event.condition_id)
    marks = Marks(result.books)
    for fill in result.fills:
        check()
        r = row(fill.at.date().isoformat(), fill.condition_id, fill.market_id)
        r["fills"] += 1
        r["filled_shares"] += fill.size
        r["fills_in_events" if fill.in_event_window else "fills_outside_events"] += 1
        r["nominal_rebate"] += nominal_rebate(fill.price) * fill.size
        settlement = result.settlements.get(fill.condition_id)
        payout = None if settlement is None else D(str(settlement.p_yes if fill.outcome == "YES" else 1-settlement.p_yes))
        if payout is None:
            r["unresolved_fills"] += 1
        else:
            r["settled_inventory_pnl"] += (payout - fill.price) * fill.size
        for horizon in (*HORIZONS, "settlement"):
            mark = payout if horizon == "settlement" else marks.at_horizon(fill, HORIZONS[horizon])
            m = r["markouts"][horizon]
            if mark is None:
                m["missing_fills"] += 1
            else:
                m["pnl"] += (mark - fill.price) * fill.size
                m["shares"] += fill.size
    for r in rows.values():
        r["status"] = "EXCLUDED" if not r["covered_seconds"] else "PARTIAL" if r["excluded_seconds"] else "COVERED"
        r["cash_hours"] = r["reserved_cash_hours"] + r["inventory_cash_hours"]
        r["pulled_minute_fraction"] = r["pulled_seconds"] / r["covered_seconds"] if r["covered_seconds"] else None
        r["reward_k05"] = r["reward_k1"] / 2
        # Clarification 2 measured-reaction sensitivity (RE-1 long-horizon share): reported only.
        r["reward_k03"] = r["reward_k1"] * D("0.3")
        for k in ("k1", "k05", "k03"):
            r["modeled_net_" + k] = (r["reward_" + k] + r["nominal_rebate"] + r["settled_inventory_pnl"]
                                      if r["status"] == "COVERED" and not r["unresolved_fills"] else None)
        for m in r["markouts"].values():
            m["per_share"] = m["pnl"] / m["shares"] if m["shares"] else None
    return [rows[key] for key in sorted(rows)]
