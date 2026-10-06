"""Maker replay v2 engine (W3): a condition is decided only at its own events (registration draft §5).

Cost is O(own events), not O(instants x bands):

- **Lazy per-band timers.** A timer is pushed once, when the state that defines it arrives (book gap,
  terms expiry, view expiry, event-window boundaries, the last-three-hours boundary, coverage expiry,
  RE-1 session end), plus the fixed active-interval and clock-calendar boundaries. A popped timer is
  checked against the condition's *current* state and dropped if a newer record superseded it.
- **Record wakes** are decided per instant by comparing a condition's record signature before and after
  the instant (a changed decision-relevant book state — never an unchanged re-send, which only refreshes
  the freshness clock — a changed terms body, a changed view state (never a re-stamp that moves only its
  ``as_of_utc`` or ``stdev``) or event payload, a fill), and by a
  coverage state that changed (a refresh that leaves it unchanged wakes nothing).
- **Exact running totals.** Reserve, inventory, per-event and per-factor commitments are 1e-6 sums
  maintained on every change (``money``); a portfolio is read from them in O(factors). With
  ``debug`` on, every read is compared with a fresh recomputation and a difference raises.
- **Run-length intervals.** A condition's carried state is written as one interval per state change.

Ordering is the frozen engine's: at an instant, prints first, then every other record by sequence, then
the woken conditions in condition-ID order. ``reference.ReferenceEngine`` implements the same semantics
by brute force; the differential tests compare the two.
"""
from __future__ import annotations

from datetime import timedelta
import heapq

from maker_core.contracts import OutcomeView
from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2.kernel import (EPSILON, Kernel, coverage_ok, info_boundaries, interval_key, make_interval,
                                         record_signature, recomputed_portfolio, assemble)
from maker_core.replay.v2.money import ZERO, add, mul, q, sub, total


class RunningTotalsMismatch(AssertionError):
    """Debug mode: a running total differs from its recomputation."""


class EngineV2(Kernel):
    def __init__(self, config, plan, *, sink=None):
        super().__init__(config, plan)
        self.sink = sink
        self.heap, self._n = [], 0
        self.R = self.I = ZERO
        self.E, self.F, self.A = {}, {}, 0
        self.contrib = {}
        self.pre, self.touched, self.cov_check, self.cov = {}, set(), set(), {}
        self.open = {}
        self.intervals = [] if config.keep else None
        self.day = None
        self.finished = False
        self.timer_pops = self.stale_timers = self.wakes = self.instants = 0
        for cid, state in sorted(self.states.items()):
            for start, end in (*state.windows, *state.clock):
                self._push(start, cid, "fixed")
                self._push(end, cid, "fixed")
        for day in plan.days:
            self._push(day.start, None, "mark")
            self._push(day.start + timedelta(days=1), None, "mark")

    # -- timers -----------------------------------------------------------------------------------------
    def _push(self, when, cid, kind):
        if when <= self.horizon:
            self._n += 1
            heapq.heappush(self.heap, (when, self._n, cid, kind))

    def deadline(self, cid, at, when, kind):
        if at is None or when >= at:
            self._push(when, cid, kind)

    def _due(self, state, kind, at):
        latest = state.latest
        if kind == "book":
            book = latest.get("book")
            return book is not None and book.as_of_utc + timedelta(seconds=self.config.max_book_gap_seconds) == at
        if kind == "terms":
            terms = latest.get("terms")
            return terms is not None and terms.as_of_utc + timedelta(hours=1) + EPSILON == at
        if kind == "close":
            desc = latest.get("descriptor")
            return desc is not None and desc.market.close_at_utc - timedelta(hours=3) == at
        if kind == "view":
            view = latest.get("outcome_view")
            return self.informed and isinstance(view, OutcomeView) and view.valid_until_utc == at
        if kind == "info":
            return self.informed and any(at in info_boundaries(e) for e in latest.get("info_event") or ())
        if kind == "re1":
            return state.re1 is not None and state.re1.end == at
        return kind == "fixed"

    # -- per-instant bookkeeping --------------------------------------------------------------------------
    def before(self, cid):
        if cid not in self.pre:
            self.pre[cid] = record_signature(self.states[cid], self.informed)
            self.touched.add(cid)

    def coverage_touched(self, cid):
        self.cov_check.add(cid)

    def start_day(self, day_plan):
        if self.day is not None and day_plan.day <= self.day:
            raise BundleError("day_order")
        self.day = day_plan.day

    def instant(self, at, batch):
        self.advance(at)
        self._process(at, batch)

    def advance(self, until):
        while self.heap and self.heap[0][0] < until:
            self._process(self.heap[0][0], ())

    def finish(self):
        if self.finished:
            return self
        while self.heap and self.heap[0][0] <= self.horizon:
            self._process(self.heap[0][0], ())
        for cid in sorted(self.open):
            start, key = self.open[cid]
            if key is not None and start < self.horizon:
                self._emit(cid, start, self.horizon, key)
        self.open.clear()
        self.finished = True
        return self

    def _process(self, at, batch):
        if self.now is not None and at <= self.now:
            raise BundleError("instant_order")
        if self.now is not None and self.now.date() != at.date():
            self.reset_day()
        self.now = at
        self.instants += 1
        self.pre, self.touched, self.cov_check = {}, set(), set()
        for item in batch:
            if item.kind == "trade":
                self.on_trade(item.condition_id, item.value, item.error, at)
        for item in batch:
            if item.kind != "trade":
                self.ingest(item.condition_id, item.kind, item.payload_sha256, item.value, item.error, at)
        woken = set()
        heap = self.heap
        while heap and heap[0][0] == at:
            _, _, cid, kind = heapq.heappop(heap)
            if cid is None:
                continue
            self.timer_pops += 1
            if kind == "coverage":
                self.cov_check.add(cid)
            elif self._due(self.states[cid], kind, at):
                woken.add(cid)
            else:
                self.stale_timers += 1
        for cid in self.cov_check:
            ok = coverage_ok(self.states[cid], at)
            if ok != self.cov.get(cid, False):
                self.cov[cid] = ok
                woken.add(cid)
        for cid, signature in self.pre.items():
            if cid not in woken and record_signature(self.states[cid], self.informed) != signature:
                woken.add(cid)
        self.wakes += len(woken)
        for cid in sorted(woken):
            self.tick(cid, at)
        for cid in self.touched | woken:
            self._interval(cid, at)

    # -- intervals ----------------------------------------------------------------------------------------
    def _interval(self, cid, at):
        key = interval_key(self, cid, at)
        current = self.open.get(cid)
        if current is not None and current[1] == key:
            return
        if current is not None and current[1] is not None and current[0] < at:
            self._emit(cid, current[0], at, current[1])
        self.open[cid] = (at, key)

    def _emit(self, cid, start, end, key):
        if self.outputs() >= self.config.max_outputs:
            raise BundleError("engine_output_cap")
        self.interval_count += 1
        interval = make_interval(cid, self.states[cid].market_id, start, end, key)
        if self.intervals is not None:
            self.intervals.append(interval)
        if self.sink is not None:
            self.sink.interval(interval)

    # -- running totals -----------------------------------------------------------------------------------
    def _contribution(self, state):
        desc = state.latest.get("descriptor")
        return (state.reserve, state.inventory_cost, desc.market.event_id if desc is not None else None,
                tuple((f, abs(load)) for f, load in desc.factors) if desc is not None else (),
                bool(state.legs or state.lots))

    def _apply(self, c, sign):
        op = add if sign > 0 else sub
        reserve, inventory, eid, factors, flag = c
        self.R = q(op(self.R, reserve))
        self.I = q(op(self.I, inventory))
        both = add(reserve, inventory)
        if eid is not None:
            self.E[eid] = q(op(self.E.get(eid, ZERO), both))
        for factor, load in factors:
            self.F[factor] = q(op(self.F.get(factor, ZERO), q(mul(both, load))))
        self.A += sign * flag

    def changed(self, cid):
        new = self._contribution(self.states[cid])
        old = self.contrib.get(cid)
        if old == new:
            return
        if old is not None:
            self._apply(old, -1)
        self._apply(new, +1)
        self.contrib[cid] = new

    def total_reserve(self):
        if self.config.debug:
            recomputed = total(s.reserve for s in self.states.values())
            if recomputed != self.R or str(recomputed) != str(self.R):
                raise RunningTotalsMismatch("running_reserve_mismatch")
        return self.R

    def portfolio(self, cid):
        state = self.states[cid]
        desc = state.latest["descriptor"]
        other_reserve = q(sub(self.R, state.reserve))
        event_used = q(sub(self.E[desc.market.event_id], state.reserve))
        used = [q(sub(self.F[factor], q(mul(state.reserve, abs(load))))) for factor, load in desc.factors]
        active_other = self.A - bool(state.legs or state.lots)
        result = assemble(self, state, desc, other_reserve, self.I, event_used, used, active_other)
        if self.config.debug and canonical_bytes(result) != canonical_bytes(recomputed_portfolio(self, cid)):
            raise RunningTotalsMismatch("running_totals_mismatch")
        return result

    # -- result -------------------------------------------------------------------------------------------
    def summary(self):
        return dict(policy=self.config.policy, fill_bound=self.config.fill_bound, instants=self.instants,
                    wakes=self.wakes, timer_pops=self.timer_pops, stale_timers=self.stale_timers,
                    decisions=self.decision_count, decision_sha256=self.decision_sha.hexdigest(),
                    intervals=self.interval_count, fills=len(self.fills), final_cash=self.cash,
                    exclusions=dict(sorted(self.exclusions.counts.items())),
                    exclusions_sha256=self.exclusions.sha.hexdigest())
