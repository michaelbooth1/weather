"""Capture-time event replay around the shared pure decide() kernel.

Local state is a counterfactual portfolio, never an account ledger. No network,
wall clock, source file or plugin IO is reachable from this engine.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import heapq

from maker_core.contracts import OutcomeView, Unavailable
from maker_core.evidence.journal import digest
from maker_core.quoting.policy import (DecisionInputs, ExposureLimit, Portfolio, QuoteDecision, QuoteLeg,
                                       _event_active, blind_re1, decide, informed_v0)
from maker_core.replay.bundle import Bundle, BundleError
from maker_core.replay.payloads import Descriptor, decode, number
from maker_core.replay.fill_model import BOUNDS, Fill, match


D = Decimal
EPSILON = timedelta(microseconds=1)


@dataclass(frozen=True)
class ReplayConfig:
    policy: str = "informed-v0"
    initial_cash: Decimal = D(100)
    band_cap: Decimal = D(100)
    order_cap: Decimal = D(60)
    wallet_cap: Decimal = D(100)
    event_cap: Decimal = D(100)
    factor_cap: Decimal = D(100)
    hazard_per_minute: float | None = None
    max_book_gap_seconds: int = 60
    max_events: int = 500_000
    fill_bound: str = "strictly_through"
    clock_pulls: tuple = ()  # Predeclared (condition_id, from, until) UTC windows.

    def __post_init__(self):
        if self.policy not in ("informed-v0", "blind_re1", "no_quote", "clock_only"):
            raise BundleError("unsupported_replay_policy")
        if self.fill_bound not in BOUNDS:
            raise BundleError("unknown_fill_bound")
        for name in ("initial_cash", "band_cap", "order_cap", "wallet_cap", "event_cap", "factor_cap"):
            object.__setattr__(self, name, number(getattr(self, name)))
        if (type(self.max_book_gap_seconds) is not int or not 1 <= self.max_book_gap_seconds <= 60
                or type(self.max_events) is not int or not 1 <= self.max_events <= 500_000):
            raise BundleError("invalid_engine_limit")
        if self.hazard_per_minute is not None:
            number(self.hazard_per_minute, maximum=D(1))
        if len(self.clock_pulls) > 2000:
            raise BundleError("clock_window_cap")
        for cid, start, end in self.clock_pulls:
            if not isinstance(cid, str) or start.tzinfo is None or end.tzinfo is None or start >= end:
                raise BundleError("invalid_clock_window")


@dataclass(frozen=True)
class DecisionEvent:
    at: datetime
    condition_id: str
    decision: QuoteDecision


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime
    condition_id: str
    market_id: str
    covered: bool
    reason: str
    legs: tuple[QuoteLeg, ...]
    share_many: float
    rate_per_day: Decimal
    reserved: Decimal
    inventory_cost: Decimal
    in_event_window: bool
    evaluation_active: bool = True


@dataclass
class State:
    re1: object | None = None
    latest: dict = field(default_factory=dict)
    captured: dict = field(default_factory=dict)
    legs: tuple[QuoteLeg, ...] = ()
    placed_at: datetime | None = None
    last_quote: datetime | None = None
    previous_fair_value: float | None = None
    decided: bool = False
    resume_after: datetime | None = None
    decision: QuoteDecision | None = None
    reason: str = "MISSING_INPUT"
    covered: bool = False
    inventory_cost: Decimal = D(0)
    lots: list = field(default_factory=list)
    quotes: int = 0
    last_fill: datetime | None = None

    @property
    def reserve(self):
        return sum((leg.price * leg.size for leg in self.legs), D(0))


@dataclass(frozen=True)
class ReplayResult:
    config: ReplayConfig
    decisions: tuple[DecisionEvent, ...]
    spans: tuple[Span, ...]
    fills: tuple
    exclusions: tuple[dict, ...]
    input_hashes: dict
    final_cash: Decimal
    settlements: dict
    books: tuple


class Lifecycle:
    def __init__(self, bundles: tuple[Bundle, ...], config: ReplayConfig, *, check=lambda: None):
        if not bundles or len(bundles) > 366 or len({b.day for b in bundles}) != len(bundles):
            raise BundleError("duplicate_or_unbounded_days")
        if (max(b.day for b in bundles) - min(b.day for b in bundles)).days >= 366:
            raise BundleError("calendar_span_cap")
        self.bundles, self.config, self.check = tuple(sorted(bundles, key=lambda b: b.day)), config, check
        self.profile = blind_re1 if config.policy == "blind_re1" else informed_v0
        self.states, self.conditions, self.windows = {}, {}, defaultdict(list)
        self.records, self.heap, self.pending = defaultdict(list), [], set()
        self.decisions, self.spans, self.fills, self.exclusions, self.books = [], [], [], [], []
        self.cash, self.ended = config.initial_cash, False
        self.settlements = {}
        self.trades_seen = {}
        self.processed = 0
        self.end = max(c.active_until for b in bundles for c in b.conditions)
        self.horizon = datetime.combine(max(b.day for b in bundles) + timedelta(days=1),
                                        datetime.min.time(), tzinfo=timezone.utc)
        for bundle in self.bundles:
            self.schedule(datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc))
            self.schedule(datetime.combine(bundle.day + timedelta(days=1), datetime.min.time(),
                                           tzinfo=timezone.utc))
            for c in bundle.conditions:
                previous = self.conditions.get(c.condition_id)
                if previous and (c.market_id, c.domain_id) != (previous.market_id, previous.domain_id):
                    raise BundleError("condition_cluster_identity_changed")
                self.conditions[c.condition_id] = c
                self.states.setdefault(c.condition_id, State())
                for start, end in bundle.windows(c):
                    self.windows[c.condition_id].append((start, end))
                    self.schedule(start)
                    self.schedule(end)
            for record in bundle.records:
                self.records[record.captured_at].append(record)
                self.schedule(record.captured_at)
        if sum(len(b.records) for b in bundles) > config.max_events:
            raise BundleError("engine_event_cap")
        for cid, start, end in config.clock_pulls:
            if cid not in self.states:
                raise BundleError("unknown_clock_condition")
            self.schedule(start)
            self.schedule(end)

    def schedule(self, at):
        if at > self.horizon:
            return
        if at not in self.pending:
            if len(self.pending) + self.processed >= self.config.max_events:
                raise BundleError("engine_event_cap")
            self.pending.add(at)
            heapq.heappush(self.heap, at)

    def active(self, cid, at):
        return any(start <= at < end for start, end in self.windows[cid])

    def event_window(self, state, at):
        return any(_event_active(event, at) for event in state.latest.get("info_event", ()))

    def valid_coverage(self, state, at):
        for key in ("descriptor", "book", "terms", "outcome_view", "info_event", "coverage"):
            if key not in state.latest:
                return False, "MISSING_" + key.upper()
        book = state.latest["book"]
        age = (at - book.as_of_utc).total_seconds()
        if not 0 <= age < self.config.max_book_gap_seconds:
            return False, "CAPTURE_GAP"
        coverage = state.latest["coverage"]
        if not coverage.trade_stream_ok or at >= coverage.valid_until_utc:
            return False, "TRADE_CAPTURE_GAP"
        if not 0 <= (at - state.latest["terms"].as_of_utc).total_seconds() <= 3600:
            return False, "TERMS_CAPTURE_GAP"
        return True, "COVERED"

    def portfolio(self, cid):
        state = self.states[cid]
        desc = state.latest["descriptor"]
        others = [(k, s) for k, s in self.states.items() if k != cid]
        other_reserve = sum((s.reserve for _, s in others), D(0))
        inventory = sum((s.inventory_cost for s in self.states.values()), D(0))
        event_used = state.inventory_cost
        for _, s in others:
            if ("descriptor" in s.latest
                    and s.latest["descriptor"].market.event_id == desc.market.event_id):
                event_used += s.reserve + s.inventory_cost
        exposures = []
        for factor, loading in desc.factors:
            used = sum(((s.reserve * (k != cid) + s.inventory_cost)
                        * abs(dict(s.latest["descriptor"].factors).get(factor, D(0)))
                        for k, s in self.states.items() if "descriptor" in s.latest), D(0))
            exposures.append(ExposureLimit(factor, loading, used, self.config.factor_cap))
        return Portfolio(self.cash, other_reserve, max(D(0), self.config.band_cap - state.inventory_cost),
                         self.config.order_cap, other_reserve + inventory, self.config.wallet_cap,
                         event_used, self.config.event_cap, tuple(exposures),
                         active_other_bands=sum(bool(s.legs or s.lots) for _, s in others))

    def record_decision(self, cid, at, decision):
        self.check()
        if len(self.decisions) + len(self.spans) >= self.config.max_events:
            raise BundleError("engine_output_cap")
        state = self.states[cid]
        state.decision, state.reason = decision, decision.reasons[0]
        self.decisions.append(DecisionEvent(at, cid, decision))
        if decision.action == "QUOTE":
            state.legs, state.placed_at, state.last_quote = decision.legs, at, at
            state.quotes += 1
        elif decision.action in ("CANCEL", "END", "NO_QUOTE"):
            state.legs = ()
            state.placed_at = None
        if decision.action == "END":
            self.ended = True

    def pull(self, cid, at, reason):
        state = self.states[cid]
        if self.config.policy == 'blind_re1' and state.re1 is not None:
            state.re1.finish('input_coverage_ended')
        decision = QuoteDecision("CANCEL" if state.legs else "NO_QUOTE", (), (reason,),
                                 digest({"at": at, "condition": cid, "reason": reason,
                                         "captured": state.captured}), self.profile.name)
        self.record_decision(cid, at, decision)

    def ingest(self, row, at):
        state = self.states[row.condition_id]
        try:
            value = decode(row)
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            state.latest.pop(row.kind, None)
            self.exclusions.append({"at": at, "condition_id": row.condition_id,
                                    "reason": "INVALID_" + row.kind.upper(), "error": type(exc).__name__})
            return
        if row.kind == "plugin_input":
            return
        state.latest[row.kind] = value
        state.captured[row.kind] = row.captured_at
        if row.kind == "descriptor":
            if value.market.domain_id != self.conditions[row.condition_id].domain_id:
                raise BundleError("descriptor_domain_mismatch")
            close = value.market.close_at_utc - timedelta(hours=3)
            if at < close <= self.end:
                self.schedule(close)
        elif row.kind == "coverage":
            self.schedule(value.valid_until_utc)
        elif row.kind == "book":
            self.books.append((at, row.condition_id, value))
            expiry = value.as_of_utc + timedelta(seconds=self.config.max_book_gap_seconds)
            if expiry > at:
                self.schedule(expiry)
        elif row.kind == "outcome_view" and isinstance(value, OutcomeView) and self.config.policy == "informed-v0":
            if at < value.valid_until_utc <= self.end:
                self.schedule(value.valid_until_utc)
        elif row.kind == "terms":
            expiry = value.as_of_utc + timedelta(hours=1) + EPSILON
            if at < expiry <= self.end:
                self.schedule(expiry)
        elif row.kind == "info_event" and self.config.policy == "informed-v0":
            for event in value:
                if (self.config.policy == "informed-v0" and
                        (event.decided or {}).get(row.condition_id, 0) >= .5 and _event_active(event, at)):
                    state.decided = True
                boundaries = []
                if event.scheduled_at_utc is not None:
                    boundaries += [event.scheduled_at_utc - timedelta(minutes=3),
                                   event.scheduled_at_utc + timedelta(minutes=10) + EPSILON]
                if event.active_until_utc is not None:
                    boundaries.append(event.active_until_utc + EPSILON)
                for boundary in boundaries:
                    if at < boundary <= self.end:
                        self.schedule(boundary)
        elif row.kind == "settlement":
            previous = self.settlements.get(row.condition_id)
            if previous is not None and previous.p_yes != value.p_yes:
                raise BundleError("conflicting_settlement")
            self.settlements[row.condition_id] = value
            if previous is None:
                self.cash += sum((lot.size * D(str(value.p_yes if lot.outcome == "YES" else 1-value.p_yes))
                                  for lot in state.lots), D(0))
                state.inventory_cost = D(0)
                state.lots.clear()

    def on_trade(self, row, at):
        state = self.states[row.condition_id]
        try:
            trade = decode(row)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            self.exclusions.append({"at": at, "condition_id": row.condition_id, "reason": "INVALID_TRADE"})
            state.latest.pop("coverage", None)
            self.pull(row.condition_id, at, "INVALID_TRADE")
            return
        key = row.condition_id, trade.trade_id
        signature = digest(trade)
        if key in self.trades_seen:
            if self.trades_seen[key] != signature:
                raise BundleError("conflicting_duplicate_trade")
            return
        self.trades_seen[key] = signature
        # Coverage is judged just before the capture boundary, so an equal-time
        # print may consume the expiring quote (89a tie rule). A late print can
        # never fill an order placed after its venue timestamp.
        covered, _ = self.valid_coverage(state, at - EPSILON)
        if any(b.active_intervals is not None for b in self.bundles) and not self.active(row.condition_id, at):
            return  # Declared maintenance/settlement exclusions include their starting instant.
        if not state.legs or not covered or not self.active(row.condition_id, at - EPSILON):
            return
        if trade.traded_at < state.placed_at:
            self.exclusions.append({"at": at, "condition_id": row.condition_id, "reason": "PRINT_PREDATES_ORDER"})
            return
        matched = match(state.legs, trade, self.config.fill_bound)
        if matched is None:
            return
        leg, size = matched
        fill = Fill(at, trade.traded_at, row.condition_id, self.conditions[row.condition_id].market_id,
                    trade.trade_id, leg.outcome, leg.price, size, self.config.fill_bound,
                    self.event_window(state, at))
        if fill.cost > self.cash:
            raise BundleError("fill_exceeds_cash")
        self.cash -= fill.cost
        state.inventory_cost += fill.cost
        state.lots.append(fill)
        self.fills.append(fill)
        state.last_fill = at
        # Both sibling and the filled leg's unfilled remainder are pulled. That
        # conservative lifecycle overlay differs from 89a's continuous maker.
        decision = QuoteDecision("END" if self.profile.first_fill_ends else "CANCEL", (),
                                 ("FIRST_FILL_ENDS" if self.profile.first_fill_ends else "FILL_CANCEL_SIBLING",),
                                 digest(fill), self.profile.name)
        self.record_decision(row.condition_id, at, decision)

    def tick(self, cid, at):
        state = self.states[cid]
        state.covered, why = self.valid_coverage(state, at)
        if not self.active(cid, at):
            state.covered = False
            if state.legs:
                self.pull(cid, at, "OUTSIDE_ACTIVE_INTERVAL")
            return
        if not state.covered:
            self.pull(cid, at, why)
            return
        if self.config.policy == "no_quote":
            self.pull(cid, at, "BASELINE_NO_QUOTE")
            return
        if self.config.policy == "clock_only" and any(
                key == cid and start <= at < end for key, start, end in self.config.clock_pulls):
            self.pull(cid, at, "CLOCK_ONLY_PULL")
            return
        if state.last_fill == at:
            return  # Never recreate the sibling at the fill instant.
        if self.ended or cid in self.settlements or state.decided:
            self.pull(cid, at, "SESSION_ENDED" if self.ended else "SETTLED" if cid in self.settlements else "DECIDED")
            return
        events = state.latest["info_event"] if self.config.policy == "informed-v0" else ()
        if any((e.decided or {}).get(cid, 0) >= .5 and _event_active(e, at) for e in events):
            state.decided = True
            self.pull(cid, at, "DECIDED")
            return
        if state.resume_after is not None and not any(e.action_hint == "pull" and _event_active(e, at) for e in events):
            if any(state.captured[k] <= state.resume_after for k in ("book", "outcome_view")):
                self.pull(cid, at, "AWAIT_FRESH_REENTRY_INPUTS")
                return
            state.resume_after = None
        if (self.config.policy != 'blind_re1' and not state.legs and state.last_quote is not None
                and at - state.last_quote < timedelta(seconds=60)):
            self.pull(cid, at, "REQUOTE_COOLDOWN")
            return
        desc = state.latest["descriptor"]
        # Captured public depth excludes counterfactual orders. decide() subtracts
        # own resting levels; add them only to already displayed matching levels
        # so competitor depth is preserved without inventing a new qualified mid.
        book = state.latest["book"]
        def add_own(levels, outcome, mirror=False):
            additions = {leg.price if not mirror else 1-leg.price: leg.size
                         for leg in state.legs if leg.outcome == outcome}
            return tuple((price, size + additions.get(price, D(0))) for price, size in levels)
        book = replace(book, yes_bids=add_own(book.yes_bids, "YES"),
                       yes_asks=add_own(book.yes_asks, "NO", True))
        fair_value = (state.latest["outcome_view"] if self.config.policy == "informed-v0"
                      else Unavailable("clock/blind baseline", at))
        value = DecisionInputs(desc.market, at, book, state.latest["terms"], fair_value,
                               self.portfolio(cid), desc.horizon_days, events, self.profile,
                               self.config.hazard_per_minute, existing=state.legs,
                               last_requote_at=state.last_quote, previous_fair_value=state.previous_fair_value)
        if self.config.policy == 'blind_re1':
            self.blind_tick(cid, at, value)
            if sum((s.reserve for s in self.states.values()), D(0)) > self.cash:
                raise BundleError("cash_overcommitment")
            return
        decision = self.decide_inputs(value)
        self.record_decision(cid, at, decision)
        if "INFO_PULL" in decision.reasons and state.resume_after is None:
            state.resume_after = at
        # Cancellation is immediate. Replacement waits out cooldown, then uses
        # the same current inputs with reservations released and no resting legs.
        if decision.action == "CANCEL" and decision.reasons[0] in (
                "OUTSIDE_REQUOTE_WINDOW", "TOUCH_BUFFER", "SIZE_BELOW_MINIMUM",
                "ADVERSE_LEG_CHANGED", "REQUOTE_REQUIRED", "UNCALIBRATED_ASYMMETRY"):
            if state.last_quote is None or at - state.last_quote >= timedelta(seconds=60):
                replacement = self.decide_inputs(replace(value, existing=(), portfolio=self.portfolio(cid)))
                self.record_decision(cid, at, replacement)
        view = state.latest["outcome_view"]
        if isinstance(view, OutcomeView) and state.decision.action == "QUOTE":
            state.previous_fair_value = view.p_yes
        if sum((s.reserve for s in self.states.values()), D(0)) > self.cash:
            raise BundleError("cash_overcommitment")

    def decide_inputs(self, value):
        return decide(value)

    def blind_tick(self, cid, at, value):
        raise BundleError('blind_adapter_not_installed')

    def run(self):
        previous = None
        while self.heap:
            self.check()
            at = heapq.heappop(self.heap)
            self.pending.remove(at)
            self.processed += 1
            if self.processed > self.config.max_events:
                raise BundleError("engine_event_cap")
            if previous is not None:
                for cid, state in sorted(self.states.items()):
                    if self.active(cid, previous) or state.inventory_cost:
                        self.check()
                        if len(self.decisions) + len(self.spans) >= self.config.max_events:
                            raise BundleError("engine_output_cap")
                        terms = state.latest.get("terms")
                        self.spans.append(Span(previous, at, cid, self.conditions[cid].market_id,
                            state.covered, state.reason, state.legs,
                            state.decision.share_many if state.decision and state.legs else 0.0,
                            terms.rate_per_day if terms else D(0), state.reserve, state.inventory_cost,
                            self.event_window(state, previous), self.active(cid, previous)))
            rows = sorted(self.records.pop(at, ()), key=lambda r: r.sequence)
            if previous is not None and previous.date() != at.date() and self.config.policy == "blind_re1":
                self.ended = False  # One retrospective RE-1 session per UTC capture day.
                for state in self.states.values():
                    state.re1 = None
            # All prints consume the expiring quote before any equal-time input
            # update or replacement, regardless of sequence within that capture.
            for row in rows:
                if row.kind == "trade":
                    self.on_trade(row, at)
            for row in rows:
                if row.kind != "trade":
                    self.ingest(row, at)
            if (self.config.policy == "informed-v0" or not rows or
                    any(r.kind not in ("info_event", "outcome_view", "plugin_input") for r in rows)):
                for cid in sorted(self.states):
                    self.tick(cid, at)
            previous = at
        hashes = {b.day.isoformat(): dict(b.input_hashes) for b in self.bundles}
        return ReplayResult(self.config, tuple(self.decisions), tuple(self.spans), tuple(self.fills),
                            tuple(self.exclusions), hashes, self.cash, self.settlements, tuple(self.books))
