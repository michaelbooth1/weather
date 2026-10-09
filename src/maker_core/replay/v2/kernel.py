"""The decision kernel shared by the v2 engine and its reference schedule (registration draft §5).

This is the frozen engine's per-record and per-decision logic (``maker_core.replay.engine`` at the exam
tree), unchanged except for the registered differences below:

- **C5 money.** Cash, reserves, inventory and fill costs are exact 1e-6 amounts (``money``).
- **No capture times of elidable records.** v1 re-entry after an ``INFO_PULL`` compared the outcome
  view's *capture* time, and its pull digests hashed every input's capture time (exam ``engine.py``
  :402 and :264). Duplicate elision (§6) changes those capture times, so here re-entry reads the view's
  payload ``as_of_utc`` and a pull digest hashes the latest payload hashes. Books are never elided;
  the book's capture time is still read.
- **C11 own legs on both sides (engine ruling W1(a)).** The decision book is ``compose_book``: every resting
  leg on its own bid array and, mirrored, on the complement's ask array, creating a level the public book
  lacks. The frozen loop added own size only at existing YES-side levels. A public book that moves onto a
  resting leg without a print now reads as crossed (``CROSSED_BOOK``, counted in ``own_leg_crossed``).
- **C12 replacement without the cancelled legs (engine ruling W2(a)).** A same-instant replacement decides
  on the public book; the frozen loop reused the pre-cancel book that still carried the cancelled legs.
- **Who is decided when** is not decided here. The kernel calls hooks; ``engine.EngineV2`` (lazy per-band
  timers, running totals, run-length intervals) and ``reference.ReferenceEngine`` (the frozen loop
  restricted to the wake set, recomputed totals, per-instant spans) implement them independently.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib

from maker_core.contracts import OutcomeView, Unavailable
from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.quoting.policy import (DecisionInputs, ExposureLimit, Portfolio, QuoteDecision, _event_active,
                                       blind_re1, decide, informed_v0)
from maker_core.replay.bundle import BundleError
from maker_core.replay.engine import DecisionEvent
from maker_core.replay.fill_model import BOUNDS, Fill, match
from maker_core.replay.payloads import number
from maker_core.replay.re1_counterfactual import tick as blind_tick
from maker_core.replay.v2.money import ZERO, add, mul, q, sub, total

D = Decimal
EPSILON = timedelta(microseconds=1)
MAX_OUTPUTS = 2**31
MAX_CLOCK_WINDOWS = 2**20
POLICIES = ("informed-v0", "blind_re1", "no_quote", "clock_only")
CAP_FIELDS = ("initial_cash", "band_cap", "order_cap", "wallet_cap", "event_cap", "factor_cap")
REPLACEMENT_REASONS = ("OUTSIDE_REQUOTE_WINDOW", "TOUCH_BUFFER", "SIZE_BELOW_MINIMUM",
                       "ADVERSE_LEG_CHANGED", "REQUOTE_REQUIRED", "UNCALIBRATED_ASYMMETRY")


@dataclass(frozen=True)
class V2Config:
    """v1's ``ReplayConfig`` fields with 1e-6 caps, an indexed clock calendar and a debug switch.

    ``debug`` recomputes the portfolio from every condition at every decision and refuses a running
    total that differs (registration §5); tests run with it on. ``keep`` retains decisions and intervals
    in memory for tests and the differential harness; a scored run streams them instead.
    """
    policy: str = "informed-v0"
    initial_cash: Decimal = D(100)
    band_cap: Decimal = D(100)
    order_cap: Decimal = D(60)
    wallet_cap: Decimal = D(100)
    event_cap: Decimal = D(100)
    factor_cap: Decimal = D(100)
    hazard_per_minute: float | None = None
    max_book_gap_seconds: int = 60
    fill_bound: str = "strictly_through"
    clock_pulls: tuple = ()  # (condition_id, from, until) UTC windows
    max_outputs: int = MAX_OUTPUTS
    debug: bool = False
    keep: bool = False

    def __post_init__(self):
        if self.policy not in POLICIES:
            raise BundleError("unsupported_replay_policy")
        if self.fill_bound not in BOUNDS:
            raise BundleError("unknown_fill_bound")
        for name in CAP_FIELDS:
            object.__setattr__(self, name, q(number(getattr(self, name))))
        if (type(self.max_book_gap_seconds) is not int or not 1 <= self.max_book_gap_seconds <= 60
                or type(self.max_outputs) is not int or not 1 <= self.max_outputs <= MAX_OUTPUTS):
            raise BundleError("invalid_engine_limit")
        if self.hazard_per_minute is not None:
            number(self.hazard_per_minute, maximum=D(1))
        if len(self.clock_pulls) > MAX_CLOCK_WINDOWS:
            raise BundleError("clock_window_cap")
        for cid, start, end in self.clock_pulls:
            if not isinstance(cid, str) or start.tzinfo is None or end.tzinfo is None or start >= end:
                raise BundleError("invalid_clock_window")


@dataclass
class CState:
    market_id: str
    domain_id: str
    windows: list = field(default_factory=list)
    clock: list = field(default_factory=list)
    re1: object | None = None
    latest: dict = field(default_factory=dict)
    sha: dict = field(default_factory=dict)  # kind -> payload SHA-256 of the latest decoded record
    legs: tuple = ()
    reserve: Decimal = ZERO
    placed_at: datetime | None = None
    last_quote: datetime | None = None
    previous_fair_value: float | None = None
    decided: bool = False
    resume_after: datetime | None = None
    decision: QuoteDecision | None = None
    reason: str = "MISSING_INPUT"
    covered: bool = False
    inventory_cost: Decimal = ZERO
    lots: list = field(default_factory=list)
    quotes: int = 0
    last_fill: datetime | None = None

    def set_legs(self, legs):
        self.legs = tuple(legs)
        self.reserve = total(q(mul(leg.price, leg.size)) for leg in self.legs)


@dataclass(frozen=True)
class Interval:
    """A run-length state interval of one condition: the frozen engine's ``Span`` without its unread event flag."""
    start: datetime
    end: datetime
    condition_id: str
    market_id: str
    covered: bool
    reason: str
    legs: tuple
    share_many: float
    rate_per_day: Decimal
    reserved: Decimal
    inventory_cost: Decimal
    evaluation_active: bool


def interval_key(kernel, cid, at):
    """State carried into ``[at, next change)``: None when the frozen loop would write no span."""
    s = kernel.states[cid]
    active = kernel.active(cid, at)
    if not (active or s.inventory_cost):
        return None
    terms = s.latest.get("terms")
    return (s.covered, s.reason, s.legs, s.decision.share_many if s.decision and s.legs else 0.0,
            terms.rate_per_day if terms else D(0), s.reserve, s.inventory_cost, active)


def make_interval(cid, market_id, start, end, key):
    return Interval(start, end, cid, market_id, *key[:7], key[7])


def coverage_ok(state, at):
    coverage = state.latest.get("coverage")
    return coverage is not None and coverage.trade_stream_ok and at < coverage.valid_until_utc


def book_state(book):
    """The decision-relevant book state (registration draft §5 rule 1): what ``decide()`` reads of a book
    other than its clock.

    Every level of all four sides — ``yes_bids``, ``yes_asks``, ``no_bids``, ``no_asks`` — as decoded (each
    side's levels merged by price, zero sizes dropped, bids high-to-low and asks low-to-high, exact Decimal
    price and size), plus ``post_only_available``. ``as_of_utc`` is excluded: it is the data-freshness clock.
    A book record whose state equals the condition's previous state is a re-send, not an own event.
    """
    if book is None:
        return None
    return (book.yes_bids, book.yes_asks, book.no_bids, book.no_asks, book.post_only_available)


def freshness_clock(state):
    """The clock every freshness and staleness check reads: the latest book record's ``as_of_utc``.

    Every valid book record, changed or not, replaces the condition's latest book and re-arms its gap timer
    (``as_of`` + ``max_book_gap_seconds``) without calling ``decide()``. So a quiet but healthy feed that re-sends
    an unchanged book with a newer ``as_of`` never looks stale, and a silent feed, or a re-projection of an old
    fetch (same ``as_of``), still goes stale on time: the gap timer wakes the band and it is excluded.
    """
    book = state.latest.get("book")
    return None if book is None else book.as_of_utc


def view_state(state):
    """Rule 4's decision-relevant outcome-view state (registration draft §5 rule 4; owner decision 2026-10-05,
    option B): the view's content without its clocks.

    An ``OutcomeView`` reduces to its condition, exact ``p_yes``, joint, ``valid_until_utc``, calibration
    grade, model and ``inputs_hash``; ``as_of_utc`` and ``stdev`` are excluded. An ``Unavailable`` reduces to
    its reason and kind. ``as_of_utc`` is the evaluation clock, and a producer's ``stdev`` may change only with
    its inputs (pinned by ``inputs_hash``) and with time (the producer contract test pins this). So a view
    re-stamped at every evaluation is not an own event; it still becomes the condition's latest view, and
    every wake reads its ``as_of_utc`` and ``stdev``, as rule 1 treats a book's ``as_of_utc``.
    """
    view = state.latest.get("outcome_view")
    if view is None:
        return None
    if isinstance(view, OutcomeView):
        joint = None if view.joint is None else tuple(sorted(view.joint.items()))
        return ("view", view.condition_id, view.p_yes, joint, view.valid_until_utc, view.calibration_grade,
                view.model_id, view.inputs_hash)
    if isinstance(view, Unavailable):
        return ("unavailable", view.reason, view.kind)
    raise BundleError("invalid_view_value")


def record_signature(state, informed):
    """Record-driven own events (§5 rules 1, 3, 4, 6), as a value compared across one instant.

    Rule 1: a change in the decision-relevant book state (``book_state``; an invalid book drops it), never a
    re-sent unchanged book. Rule 3: a changed terms body. Rule 4 (``informed-v0`` only): a changed view state
    (``view_state``; never a re-stamp that moves only ``as_of_utc`` or ``stdev``) or a changed event payload.
    Rule 6: a fill of a resting leg.
    """
    terms = state.latest.get("terms")
    body = (terms.min_size, terms.max_spread_cents, terms.rate_per_day) if terms is not None else None
    return (book_state(state.latest.get("book")), body,
            view_state(state) if informed else None,
            state.sha.get("info_event") if informed else None, state.last_fill)


class _Exclusions:
    """Counts and hashes exclusion records; blind RE-1's adapter appends here as to a list."""

    def __init__(self, keep):
        self.counts, self.sha, self.rows = Counter(), hashlib.sha256(), [] if keep else None

    def append(self, value):
        self.counts[value["reason"]] += 1
        self.sha.update(canonical_bytes(value))
        if self.rows is not None:
            self.rows.append(value)


class Kernel:
    """Per-condition state and the frozen decision logic; subclasses own scheduling, totals and intervals."""

    # Owner Q2(a), 2026-10-08: blind RE-1 gets informed-v0's horizon gate. ``decide()`` applies
    # ``eligible_horizons`` only to informed profiles, so the kernel applies it to blind RE-1 before its runtime.
    # None turns it off (the attribution tool's pre-Q2 variants only).
    blind_horizons = informed_v0.eligible_horizons

    def __init__(self, config: V2Config, plan):
        self.config, self.plan = config, plan
        self.profile = blind_re1 if config.policy == "blind_re1" else informed_v0
        self.informed = config.policy == "informed-v0"
        self.states = {}
        self.cash = config.initial_cash
        self.ended = False
        self.settlements = {}
        self.trades_seen = {}
        self.fills = []
        self.exclusions = _Exclusions(config.keep)
        self.decision_count, self.decision_sha = 0, hashlib.sha256()
        self.decisions = [] if config.keep else None
        self.interval_count = 0
        self.horizon, self.declared = plan.horizon, plan.declared
        self.sink = None
        self._ticking = None
        self.own_leg_crossed = Counter()  # UTC date -> CROSSED_BOOK decisions on a public book that is not crossed
        for day in plan.days:
            for c in day.conditions:
                state = self.states.get(c.condition_id)
                if state is None:
                    state = self.states[c.condition_id] = CState(c.market_id, c.domain_id)
                elif (state.market_id, state.domain_id) != (c.market_id, c.domain_id):
                    raise BundleError("condition_cluster_identity_changed")
                state.windows.extend(day.windows.get(c.condition_id, ()))
        for state in self.states.values():
            state.windows.sort()
        for cid, start, end in config.clock_pulls:
            if cid not in self.states:
                raise BundleError("unknown_clock_condition")
            self.states[cid].clock.append((start, end))
        for state in self.states.values():
            state.clock.sort()
        self.now = None

    # -- hooks ------------------------------------------------------------------------------------------
    def before(self, cid):
        """Called before a condition's state changes at the current instant."""

    def coverage_touched(self, cid):
        """Called when a condition's coverage record changes or is dropped."""

    def deadline(self, cid, at, when, kind):
        """A timer of ``cid`` created at ``at`` for instant ``when`` (``kind`` names the source)."""
        raise NotImplementedError

    def changed(self, cid):
        """A condition's reserve, inventory or descriptor changed: portfolio totals may move."""

    def portfolio(self, cid) -> Portfolio:
        raise NotImplementedError

    def total_reserve(self) -> Decimal:
        raise NotImplementedError

    def decision_book(self, state, legs):
        """The book ``decide()`` reads: the public book with the resting legs (C11, W1(a))."""
        return compose_book(state.latest["book"], legs)

    def replacement_book(self, state, cancelled):
        """The book of a same-instant replacement: the public book without the cancelled legs (C12, W2(a))."""
        return self.decision_book(state, ())

    def evaluate(self, value, cancelled=None):
        """One ``decide()`` call; ``cancelled`` holds the cancelled legs when it is a same-instant replacement."""
        return decide(value)

    def schedule(self, at):
        """blind RE-1's adapter schedules its session end through this name."""
        self.deadline(self._ticking, self.now, at, "re1")

    # -- predicates ---------------------------------------------------------------------------------------
    def active(self, cid, at):
        return any(start <= at < end for start, end in self.states[cid].windows)

    def in_clock(self, cid, at):
        return any(start <= at < end for start, end in self.states[cid].clock)

    def event_window(self, state, at):
        return any(_event_active(event, at) for event in state.latest.get("info_event") or ())

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

    def deadlines(self, state):
        """Every current own-timer instant of a condition, from its state alone (§5 rules 2-5)."""
        result = set()
        book, terms, desc = state.latest.get("book"), state.latest.get("terms"), state.latest.get("descriptor")
        if book is not None:
            result.add(book.as_of_utc + timedelta(seconds=self.config.max_book_gap_seconds))
        if terms is not None:
            result.add(terms.as_of_utc + timedelta(hours=1) + EPSILON)
        if desc is not None:
            result.add(desc.market.close_at_utc - timedelta(hours=3))
        if self.informed:
            view = state.latest.get("outcome_view")
            if isinstance(view, OutcomeView):
                result.add(view.valid_until_utc)
            for event in state.latest.get("info_event") or ():
                result.update(info_boundaries(event))
        for start, end in state.windows:
            result.update((start, end))
        for start, end in state.clock:
            result.update((start, end))
        if state.re1 is not None:
            result.add(state.re1.end)
        return result

    # -- outputs ----------------------------------------------------------------------------------------
    def outputs(self):
        return self.decision_count + self.interval_count

    def record_decision(self, cid, at, decision):
        if self.outputs() >= self.config.max_outputs:
            raise BundleError("engine_output_cap")
        state = self.states[cid]
        self.before(cid)
        state.decision, state.reason = decision, decision.reasons[0]
        event = DecisionEvent(at, cid, decision)
        self.decision_count += 1
        self.decision_sha.update(canonical_bytes(event))
        if self.decisions is not None:
            self.decisions.append(event)
        if self.sink is not None:
            self.sink.decision(event)
        if decision.action == "QUOTE":
            state.set_legs(decision.legs)
            state.placed_at, state.last_quote = at, at
            state.quotes += 1
        elif decision.action in ("CANCEL", "END", "NO_QUOTE"):
            state.set_legs(())
            state.placed_at = None
        if decision.action == "END":
            self.ended = True
        if (decision.action in ("CANCEL", "END", "NO_QUOTE") and decision.reasons[0].upper() == "CROSSED_BOOK"
                and not crossed(state.latest.get("book"))):
            self.own_leg_crossed[at.date()] += 1
        self.changed(cid)

    def pull(self, cid, at, reason):
        state = self.states[cid]
        if self.config.policy == "blind_re1" and state.re1 is not None:
            state.re1.finish("input_coverage_ended")
        decision = QuoteDecision("CANCEL" if state.legs else "NO_QUOTE", (), (reason,),
                                 digest({"at": at, "condition": cid, "reason": reason,
                                         "inputs": dict(sorted(state.sha.items()))}), self.profile.name)
        self.record_decision(cid, at, decision)

    def exclude(self, at, cid, reason, **extra):
        self.exclusions.append(dict(at=at, condition_id=cid, reason=reason, **extra))

    # -- records ----------------------------------------------------------------------------------------
    def ingest(self, cid, kind, payload_sha, value, error, at):
        state = self.states[cid]
        self.before(cid)
        if error is not None:
            state.latest.pop(kind, None)
            state.sha.pop(kind, None)
            self.exclude(at, cid, "INVALID_" + kind.upper(), error=error)
            if kind == "coverage":
                self.coverage_touched(cid)
            elif kind == "descriptor":
                self.changed(cid)
            return
        if kind == "plugin_input":
            return
        state.latest[kind] = value
        state.sha[kind] = payload_sha
        if kind == "descriptor":
            if value.market.domain_id != state.domain_id:
                raise BundleError("descriptor_domain_mismatch")
            self.deadline(cid, at, value.market.close_at_utc - timedelta(hours=3), "close")
            self.changed(cid)
        elif kind == "coverage":
            self.deadline(cid, at, value.valid_until_utc, "coverage")
            self.coverage_touched(cid)
        elif kind == "book":
            # The freshness clock moves with every book record; whether decide() runs is rule 1's business.
            self.deadline(cid, at, value.as_of_utc + timedelta(seconds=self.config.max_book_gap_seconds), "book")
        elif kind == "outcome_view":
            if self.informed and isinstance(value, OutcomeView):
                self.deadline(cid, at, value.valid_until_utc, "view")
        elif kind == "terms":
            self.deadline(cid, at, value.as_of_utc + timedelta(hours=1) + EPSILON, "terms")
        elif kind == "info_event":
            if self.informed:
                for event in value:
                    if (event.decided or {}).get(cid, 0) >= .5 and _event_active(event, at):
                        state.decided = True
                    for boundary in info_boundaries(event):
                        self.deadline(cid, at, boundary, "info")
        elif kind == "settlement":
            previous = self.settlements.get(cid)
            if previous is not None and previous.p_yes != value.p_yes:
                raise BundleError("conflicting_settlement")
            self.settlements[cid] = value
            if previous is None:
                payout = total(q(mul(lot.size, D(str(value.p_yes if lot.outcome == "YES" else 1 - value.p_yes))))
                               for lot in state.lots)
                self.cash = q(add(self.cash, payout))
                state.inventory_cost = ZERO
                state.lots.clear()
                self.changed(cid)

    def on_trade(self, cid, value, error, at):
        state = self.states[cid]
        self.before(cid)
        if error is not None:
            self.exclude(at, cid, "INVALID_TRADE")
            state.latest.pop("coverage", None)
            state.sha.pop("coverage", None)
            self.coverage_touched(cid)
            self.pull(cid, at, "INVALID_TRADE")
            return
        trade = value
        key = cid, trade.trade_id
        signature = digest(trade)
        if key in self.trades_seen:
            if self.trades_seen[key] != signature:
                raise BundleError("conflicting_duplicate_trade")
            return
        self.trades_seen[key] = signature
        # Coverage is judged just before the capture boundary (89a tie rule), exactly as in v1.
        covered, _ = self.valid_coverage(state, at - EPSILON)
        if self.declared and not self.active(cid, at):
            return
        if not state.legs or not covered or not self.active(cid, at - EPSILON):
            return
        if trade.traded_at < state.placed_at:
            self.exclude(at, cid, "PRINT_PREDATES_ORDER")
            return
        matched = match(state.legs, trade, self.config.fill_bound)
        if matched is None:
            return
        leg, size = matched
        cost = q(mul(leg.price, size))
        fill = Fill(at, trade.traded_at, cid, state.market_id, trade.trade_id, leg.outcome, leg.price, size,
                    self.config.fill_bound, self.event_window(state, at))
        if cost > self.cash:
            raise BundleError("fill_exceeds_cash")
        self.cash = q(sub(self.cash, cost))
        state.inventory_cost = q(add(state.inventory_cost, cost))
        state.lots.append(fill)
        self.fills.append(fill)
        if self.sink is not None:
            self.sink.fill(fill)
        state.last_fill = at
        self.changed(cid)
        decision = QuoteDecision("END" if self.profile.first_fill_ends else "CANCEL", (),
                                 ("FIRST_FILL_ENDS" if self.profile.first_fill_ends else "FILL_CANCEL_SIBLING",),
                                 digest(fill), self.profile.name)
        self.record_decision(cid, at, decision)

    # -- the decision -----------------------------------------------------------------------------------
    def tick(self, cid, at):
        state = self.states[cid]
        self._ticking = cid
        self.before(cid)
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
        if self.config.policy == "clock_only" and self.in_clock(cid, at):
            self.pull(cid, at, "CLOCK_ONLY_PULL")
            return
        if state.last_fill == at:
            return  # Never recreate the sibling at the fill instant.
        if self.ended or cid in self.settlements or state.decided:
            self.pull(cid, at, "SESSION_ENDED" if self.ended else "SETTLED" if cid in self.settlements else "DECIDED")
            return
        events = state.latest["info_event"] if self.informed else ()
        if any((e.decided or {}).get(cid, 0) >= .5 and _event_active(e, at) for e in events):
            state.decided = True
            self.pull(cid, at, "DECIDED")
            return
        if state.resume_after is not None and not any(e.action_hint == "pull" and _event_active(e, at) for e in events):
            # Payload clocks only (§6): the book's freshness clock and the view's as_of, never a capture time.
            if (freshness_clock(state) <= state.resume_after
                    or state.latest["outcome_view"].as_of_utc <= state.resume_after):
                self.pull(cid, at, "AWAIT_FRESH_REENTRY_INPUTS")
                return
            state.resume_after = None
        if (self.config.policy != "blind_re1" and not state.legs and state.last_quote is not None
                and at - state.last_quote < timedelta(seconds=60)):
            self.pull(cid, at, "REQUOTE_COOLDOWN")
            return
        desc = state.latest["descriptor"]
        if (self.config.policy == "blind_re1" and self.blind_horizons is not None
                and desc.horizon_days not in self.blind_horizons):
            self.pull(cid, at, "HORIZON_NOT_ELIGIBLE")
            return
        book = self.decision_book(state, state.legs)
        fair_value = (state.latest["outcome_view"] if self.informed else Unavailable("clock/blind baseline", at))
        value = DecisionInputs(desc.market, at, book, state.latest["terms"], fair_value, self.portfolio(cid),
                               desc.horizon_days, events, self.profile, self.config.hazard_per_minute,
                               existing=state.legs, last_requote_at=state.last_quote,
                               previous_fair_value=state.previous_fair_value)
        if self.config.policy == "blind_re1":
            blind_tick(self, cid, at, value)
            if self.total_reserve() > self.cash:
                raise BundleError("cash_overcommitment")
            return
        decision = self.evaluate(value)
        self.record_decision(cid, at, decision)
        if "INFO_PULL" in decision.reasons and state.resume_after is None:
            state.resume_after = at
        if decision.action == "CANCEL" and decision.reasons[0] in REPLACEMENT_REASONS:
            if state.last_quote is None or at - state.last_quote >= timedelta(seconds=60):
                if state.legs:  # record_decision(CANCEL) cleared them; survives python -O
                    raise BundleError("replacement_with_resting_legs")
                replacement = self.evaluate(replace(value, existing=(), portfolio=self.portfolio(cid),
                                                    book=self.replacement_book(state, value.existing)),
                                            value.existing)
                self.record_decision(cid, at, replacement)
        view = state.latest["outcome_view"]
        if isinstance(view, OutcomeView) and state.decision.action == "QUOTE":
            state.previous_fair_value = view.p_yes
        if self.total_reserve() > self.cash:
            raise BundleError("cash_overcommitment")

    def reset_day(self):
        """One retrospective RE-1 session per UTC capture day (v1)."""
        if self.config.policy == "blind_re1":
            self.ended = False
            for state in self.states.values():
                state.re1 = None


def compose_book(book, legs):
    """The decision book: the public book plus own resting legs as the venue displays them (engine ruling W1(a)).

    A YES leg (p, s) adds s at p on yes_bids and at 1 - p on no_asks; a NO leg (p, s) adds s at p on no_bids
    and at 1 - p on yes_asks. A level absent from the public book is created; sizes at one price are summed;
    order is bids high-to-low, asks low-to-high. as_of_utc and post_only_available are unchanged.
    """
    def merged(levels, additions, descending):
        if not additions:
            return levels
        sizes = {}
        for price, size in levels:
            if price in sizes:
                raise BundleError("unmerged_book_levels")  # guard for the live adapter (N3)
            sizes[price] = size
        for price, size in additions:
            sizes[price] = sizes.get(price, D(0)) + size
        return tuple(sorted(sizes.items(), key=lambda row: row[0], reverse=descending))
    yes = [(leg.price, leg.size) for leg in legs if leg.outcome == "YES"]
    no = [(leg.price, leg.size) for leg in legs if leg.outcome == "NO"]
    return replace(book,
                   yes_bids=merged(book.yes_bids, yes, True),
                   no_asks=merged(book.no_asks, [(1 - p, s) for p, s in yes], False),
                   no_bids=merged(book.no_bids, no, True),
                   yes_asks=merged(book.yes_asks, [(1 - p, s) for p, s in no], False))


def crossed(book):
    """The public book alone is crossed on either outcome (the ``OWN_LEG_CROSSED`` test, spec v3.2 §1.2)."""
    if book is None:
        return False
    return any(bids and asks and max(p for p, _ in bids) >= min(p for p, _ in asks)
               for bids, asks in ((book.yes_bids, book.yes_asks), (book.no_bids, book.no_asks)))


def info_boundaries(event):
    result = []
    if event.scheduled_at_utc is not None:
        result += [event.scheduled_at_utc - timedelta(minutes=3),
                   event.scheduled_at_utc + timedelta(minutes=10) + EPSILON]
    if event.active_until_utc is not None:
        result.append(event.active_until_utc + EPSILON)
    return result


def recomputed_portfolio(kernel, cid) -> Portfolio:
    """The frozen engine's portfolio, recomputed from every condition, in 1e-6 amounts."""
    states = kernel.states
    state = states[cid]
    desc = state.latest["descriptor"]
    others = [(k, s) for k, s in states.items() if k != cid]
    other_reserve = total(s.reserve for _, s in others)
    inventory = total(s.inventory_cost for s in states.values())
    event_used = total([state.inventory_cost] + [add(s.reserve, s.inventory_cost) for _, s in others
                                                 if "descriptor" in s.latest
                                                 and s.latest["descriptor"].market.event_id == desc.market.event_id])
    used = []
    for factor, _ in desc.factors:
        used.append(total(q(mul(add(s.reserve if k != cid else ZERO, s.inventory_cost),
                                abs(dict(s.latest["descriptor"].factors).get(factor, D(0)))))
                          for k, s in states.items() if "descriptor" in s.latest))
    active_other = sum(bool(s.legs or s.lots) for _, s in others)
    return assemble(kernel, state, desc, other_reserve, inventory, event_used, used, active_other)


def assemble(kernel, state, desc, other_reserve, inventory, event_used, used, active_other) -> Portfolio:
    c = kernel.config
    band_room = q(sub(c.band_cap, state.inventory_cost))
    return Portfolio(kernel.cash, other_reserve, band_room if band_room > 0 else ZERO, c.order_cap,
                     q(add(other_reserve, inventory)), c.wallet_cap, event_used, c.event_cap,
                     tuple(ExposureLimit(factor, loading, u, c.factor_cap)
                           for (factor, loading), u in zip(desc.factors, used)),
                     active_other_bands=active_other)


def group_by_instant(items):
    """(captured_at, records) groups from a ``(captured_at, sequence)``-ordered record stream."""
    current, batch = None, []
    for item in items:
        at = item[0].captured_at
        if current is not None and at != current:
            yield current, batch
            batch = []
        current = at
        batch.append(item)
    if batch:
        yield current, batch


def by_condition(rows):
    result = defaultdict(list)
    for row in rows:
        result[row.condition_id].append(row)
    return result
