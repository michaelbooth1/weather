"""Reference schedule (W4): the frozen loop with its ticks restricted to the wake set. Tests only.

Deliberately simple and deliberately slow — O(instants x bands), like the frozen engine:

- one global heap of every instant anything was ever scheduled for (records, every timer ever
  created, interval and calendar boundaries, UTC midnights); stale timers are never removed;
- at every instant, every condition's record signature, coverage state and full deadline set are
  recomputed from scratch, and a condition is woken iff one of them says so;
- every portfolio is recomputed from every condition (no running totals);
- spans are written for every condition at every instant, as the frozen engine does, and merged
  afterwards into run-length intervals.

It buffers a run's records in memory, so it is for short fixture windows only. ``EngineV2`` must agree
with it on every decision, fill, cash amount, settlement, interval and clock match (gate E8, S5).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import heapq

from maker_core.replay.bundle import BundleError
from maker_core.replay.v2.kernel import (Kernel, coverage_ok, interval_key, make_interval, record_signature,
                                         recomputed_portfolio)
from maker_core.replay.v2.money import total


class ReferenceEngine(Kernel):
    def __init__(self, config, plan, *, sink=None):
        super().__init__(config, plan)
        self.sink = sink
        self.heap, self.pending = [], set()
        self.records = defaultdict(list)
        self.spans = []
        self.intervals = [] if config.keep else None
        self.finished = False
        for state in self.states.values():
            for start, end in (*state.windows, *state.clock):
                self._schedule(start)
                self._schedule(end)
        for day in plan.days:
            self._schedule(day.start)
            self._schedule(day.start + timedelta(days=1))

    def _schedule(self, at):
        if at is not None and at <= self.horizon and at not in self.pending:
            self.pending.add(at)
            heapq.heappush(self.heap, at)

    def deadline(self, cid, at, when, kind):
        # Like the frozen engine, only future instants are scheduled; an instant equal to the current one
        # is found by the brute-force deadline check below.
        if at is None or when > at:
            self._schedule(when)

    def start_day(self, day_plan):
        pass

    def instant(self, at, batch):
        self.records[at].extend(batch)
        self._schedule(at)

    def portfolio(self, cid):
        return recomputed_portfolio(self, cid)

    def total_reserve(self):
        return total(s.reserve for s in self.states.values())

    def finish(self):
        if self.finished:
            return self
        previous, cov = None, {cid: False for cid in self.states}
        while self.heap:
            at = heapq.heappop(self.heap)
            self.pending.discard(at)
            if previous is not None:
                for cid in sorted(self.states):
                    key = interval_key(self, cid, previous)
                    if key is not None:
                        self.spans.append((cid, previous, at, key))
                if previous.date() != at.date():
                    self.reset_day()
            self.now = at
            before = {cid: record_signature(s, self.informed) for cid, s in self.states.items()}
            batch = self.records.pop(at, ())
            for item in batch:
                if item.kind == "trade":
                    self.on_trade(item.condition_id, item.value, item.error, at)
            for item in batch:
                if item.kind != "trade":
                    self.ingest(item.condition_id, item.kind, item.payload_sha256, item.value, item.error, at)
            woken = []
            for cid in sorted(self.states):
                state = self.states[cid]
                ok = coverage_ok(state, at)
                wake = ok != cov[cid] or record_signature(state, self.informed) != before[cid]
                cov[cid] = ok
                if wake or at in self.deadlines(state):
                    woken.append(cid)
            for cid in woken:
                self.tick(cid, at)
            previous = at
        if self.records:
            raise BundleError("reference_records_after_horizon")
        self._merge()
        self.finished = True
        return self

    def _merge(self):
        runs = {}
        for cid, start, end, key in sorted(self.spans, key=lambda s: (s[0], s[1])):
            run = runs.get(cid)
            if run is not None and run[2] == key and run[1] == start:
                runs[cid] = (run[0], end, key)
                continue
            if run is not None:
                self._emit(cid, *run)
            runs[cid] = (start, end, key)
        for cid in sorted(runs):
            self._emit(cid, *runs[cid])
        self.spans = []

    def _emit(self, cid, start, end, key):
        self.interval_count += 1
        interval = make_interval(cid, self.states[cid].market_id, start, end, key)
        if self.intervals is not None:
            self.intervals.append(interval)
        if self.sink is not None:
            self.sink.interval(interval)

    def summary(self):
        return dict(policy=self.config.policy, fill_bound=self.config.fill_bound, decisions=self.decision_count,
                    decision_sha256=self.decision_sha.hexdigest(), intervals=self.interval_count,
                    fills=len(self.fills), final_cash=self.cash,
                    exclusions=dict(sorted(self.exclusions.counts.items())),
                    exclusions_sha256=self.exclusions.sha.hexdigest())
