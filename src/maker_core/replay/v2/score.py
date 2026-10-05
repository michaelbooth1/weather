"""Streaming band-day scorer for maker replay v2 (W5; registration draft §7, C5).

An engine streams its intervals, decisions and fills here as it runs; nothing holds a whole day of
spans. Time is integer microseconds. Reward accrual is accumulated exactly (``rate x share x
microseconds``) and divided once per band-day (``money.round_once``), as are cash-hours and rebates.
The band-day fields, statuses and the net rule are the frozen scorer's (``maker_core.replay.score``):
net is null for a band-day with excluded exposure or an unresolved fill.

``Books`` is a policy-free observer of the shared parse: compact per-condition midpoint series for
markouts (both outcomes) and for the pull endpoint (YES, with the frozen one-minute freshness filter).
"""
from __future__ import annotations

from array import array
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from maker_core.replay.bundle import BundleError
from maker_core.replay.score import HORIZONS, MARK_TOLERANCE_SECONDS
from maker_core.replay.v2.money import ZERO, add, mul, round_once, sub

D = Decimal
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
US = 1_000_000
DAY_US = 86_400 * US
HOUR_US = 3_600 * US
MINUTE_US = 60 * US
MID_SCALE = D(10) ** 6  # midpoints are stored as (bid + ask) x 1e6, an exact integer for prices to 1e-6
_NONE = -1


def us(value: datetime) -> int:
    delta = value - EPOCH
    return delta.days * DAY_US + delta.seconds * US + delta.microseconds


def from_us(value: int) -> datetime:
    return EPOCH + timedelta(microseconds=value)


def seconds(micros: int) -> Decimal:
    return D(micros).scaleb(-6)


def _mid2(bid, ask):
    value = (bid + ask) * MID_SCALE
    if value != value.to_integral_value():
        raise BundleError("mark_price_precision")
    return int(value)


def mid_of(mid2: int) -> Decimal:
    return D(mid2).scaleb(-6) / 2


class Books:
    """Policy-free midpoint series from the shared parse (observer of ``lockstep.drive``)."""

    def __init__(self):
        self.marks = defaultdict(lambda: (array("q"), array("q")))  # (cid, outcome) -> (at, mid2)
        self.pull = defaultdict(lambda: (array("q"), array("q"), array("q")))  # cid -> (at, mid2, as_of), fresh
        self.books = 0

    def instant(self, at, batch):
        t = None
        for item in batch:
            if item.kind != "book" or item.error is not None:
                continue
            book = item.value
            t = us(at) if t is None else t
            self.books += 1
            for outcome, bids, asks in (("YES", book.yes_bids, book.yes_asks), ("NO", book.no_bids, book.no_asks)):
                if bids and asks:
                    bid, ask = max(p for p, _ in bids), min(p for p, _ in asks)
                    if bid <= ask:
                        times, mids = self.marks[item.condition_id, outcome]
                        times.append(t)
                        mids.append(_mid2(bid, ask))
            if book.yes_bids and book.yes_asks and timedelta(0) <= at - book.as_of_utc <= timedelta(minutes=1):
                bid, ask = max(p for p, _ in book.yes_bids), min(p for p, _ in book.yes_asks)
                if bid <= ask:
                    times, mids, as_of = self.pull[item.condition_id]
                    times.append(t)
                    mids.append(_mid2(bid, ask))
                    as_of.append(us(book.as_of_utc))

    def mark(self, cid, outcome, target_us):
        """First two-sided mark at or after ``target`` within the frozen 120 s tolerance."""
        times, mids = self.marks.get((cid, outcome), ((), ()))
        i = bisect_left(times, target_us)
        if i < len(times) and times[i] - target_us <= MARK_TOLERANCE_SECONDS * US:
            return mid_of(mids[i])
        return None


class _Row:
    __slots__ = ("market_id", "active", "covered", "excluded", "pulled", "reasons", "reward", "reserved",
                 "inventory", "quotes", "requotes", "fills")

    def __init__(self, market_id):
        self.market_id = market_id
        self.active = self.covered = self.excluded = self.pulled = 0
        self.reasons = Counter()
        self.reward = self.reserved = self.inventory = ZERO
        self.quotes = self.requotes = 0
        self.fills = []


class BandDayScorer:
    """Sink for one engine pass: band-day sums, merged excluded intervals and (optionally) pull runs."""

    def __init__(self, policy, bound, *, pull_runs=False):
        self.policy, self.bound = policy, bound
        self.rows = {}
        self.quoted = set()
        self.excluded = defaultdict(list)  # cid -> [[start_us, end_us, reason], ...] merged
        self.excluded_runs = 0
        self.state_runs = defaultdict(list) if pull_runs else None  # cid -> [[start, end, legs]] active
        self.covered_runs = defaultdict(list) if pull_runs else None  # cid -> [[start, end]] covered & active

    def _row(self, day, cid, market_id):
        key = day, cid
        row = self.rows.get(key)
        if row is None:
            row = self.rows[key] = _Row(market_id)
        return row

    def interval(self, iv):
        start_us, end_us = us(iv.start), us(iv.end)
        share = D(str(iv.share_many)) if iv.legs else ZERO
        cursor = start_us
        while cursor < end_us:
            stop = min(end_us, (cursor // DAY_US + 1) * DAY_US)
            m = stop - cursor
            row = self._row(from_us(cursor).date().isoformat(), iv.condition_id, iv.market_id)
            row.reserved = add(row.reserved, mul(iv.reserved, m))
            row.inventory = add(row.inventory, mul(iv.inventory_cost, m))
            if iv.evaluation_active:
                row.active += m
                if not iv.covered:
                    row.excluded += m
                    row.reasons[iv.reason] += m
                else:
                    row.covered += m
                    if not iv.legs:
                        row.pulled += m
                    else:
                        row.reward = add(row.reward, mul(mul(iv.rate_per_day, share), m))
            cursor = stop
        if iv.evaluation_active and not iv.covered:
            runs = self.excluded[iv.condition_id]
            if runs and runs[-1][1] == start_us and runs[-1][2] == iv.reason:
                runs[-1][1] = end_us
            else:
                runs.append([start_us, end_us, iv.reason])
                self.excluded_runs += 1
        if self.state_runs is not None and iv.evaluation_active:
            _extend(self.state_runs[iv.condition_id], start_us, end_us, bool(iv.legs))
            if iv.covered:
                _extend(self.covered_runs[iv.condition_id], start_us, end_us, None)

    def decision(self, event):
        if event.decision.action != "QUOTE":
            return
        cid = event.condition_id
        row = self.rows.get((event.at.date().isoformat(), cid))
        if row is None:
            row = self._row(event.at.date().isoformat(), cid, None)
        row.quotes += 1
        row.requotes += int(cid in self.quoted)
        self.quoted.add(cid)

    def fill(self, fill):
        self._row(fill.at.date().isoformat(), fill.condition_id, fill.market_id).fills.append(fill)

    def band_days(self, settlements, books: Books, markets) -> list[dict]:
        """The frozen band-day fields, exact; settlement P&L is attributed to the fill date."""
        result = []
        for (day, cid), r in sorted(self.rows.items()):
            fills = r.fills
            rebate = pnl = shares = ZERO
            unresolved = in_events = 0
            markouts = {h: dict(pnl=ZERO, shares=ZERO, missing_fills=0) for h in (*HORIZONS, "settlement")}
            settlement = settlements.get(cid)
            for fill in fills:
                shares = add(shares, fill.size)
                in_events += int(fill.in_event_window)
                rebate = add(rebate, mul(mul(mul(D(".0125"), fill.price), sub(1, fill.price)), fill.size))
                payout = None if settlement is None else D(str(settlement.p_yes if fill.outcome == "YES"
                                                                else 1 - settlement.p_yes))
                if payout is None:
                    unresolved += 1
                else:
                    pnl = add(pnl, mul(sub(payout, fill.price), fill.size))
                for horizon in (*HORIZONS, "settlement"):
                    mark = payout if horizon == "settlement" else books.mark(
                        cid, fill.outcome, us(fill.at) + HORIZONS[horizon] * US)
                    m = markouts[horizon]
                    if mark is None:
                        m["missing_fills"] += 1
                    else:
                        m["pnl"] = add(m["pnl"], mul(sub(mark, fill.price), fill.size))
                        m["shares"] = add(m["shares"], fill.size)
            covered = seconds(r.covered)
            status = "EXCLUDED" if not r.covered else "PARTIAL" if r.excluded else "COVERED"
            reward_k1 = round_once(r.reward, DAY_US)
            reward_k05 = round_once(r.reward, 2 * DAY_US)
            reward_k03 = round_once(mul(r.reward, D("0.3")), DAY_US)
            rebate_r, pnl_r = round_once(rebate, 1), round_once(pnl, 1)
            reserved_h, inventory_h = round_once(r.reserved, HOUR_US), round_once(r.inventory, HOUR_US)
            row = dict(date=day, condition_id=cid, market_id=r.market_id or markets[cid], policy=self.policy,
                       fill_bound=self.bound, active_seconds=seconds(r.active), covered_seconds=covered,
                       excluded_seconds=seconds(r.excluded), pulled_seconds=seconds(r.pulled),
                       excluded_by_reason={k: seconds(v) for k, v in sorted(r.reasons.items())},
                       reward_k1=reward_k1, reward_k05=reward_k05, reward_k03=reward_k03,
                       nominal_rebate=rebate_r, maker_fees=ZERO, reserved_cash_hours=reserved_h,
                       inventory_cash_hours=inventory_h, cash_hours=round_once(add(r.reserved, r.inventory), HOUR_US),
                       fills=len(fills), fills_in_events=in_events, fills_outside_events=len(fills) - in_events,
                       filled_shares=shares, unresolved_fills=unresolved, settled_inventory_pnl=pnl_r,
                       quotes=r.quotes, requotes=r.requotes, status=status,
                       pulled_minute_fraction=(seconds(r.pulled) / covered) if r.covered else None)
            for k, reward in (("k1", reward_k1), ("k05", reward_k05), ("k03", reward_k03)):
                row["modeled_net_" + k] = (add(add(reward, rebate_r), pnl_r)
                                           if status == "COVERED" and not unresolved else None)
            for m in markouts.values():
                m["per_share"] = m["pnl"] / m["shares"] if m["shares"] else None
            row["markouts"] = markouts
            result.append(row)
        return result


def _extend(runs, start, end, value):
    if runs and runs[-1][1] == start and runs[-1][2] == value:
        runs[-1][1] = end
    else:
        runs.append([start, end, value])
