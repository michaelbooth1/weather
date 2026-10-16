"""Queue-aware fill model v3 (item 330 build 1): versioned, opt-in, never the default.

The v2 rule (89a predicate behind ``fill_model.match``; bounds ``strictly_through`` and ``at_price``) stays the
default everywhere. Nothing here edits or monkeypatches the frozen v2 engine: ``EngineV3`` is a subclass that a
caller injects (``run_passes(engine=...)`` or direct construction), and ``BOUNDS`` is unchanged.

**The rule.** A resting BUY leg at price ``p`` joins the back of the displayed queue at its own level:

- ``q_ahead`` is the displayed size at ``p`` on the leg's own bid array (``yes_bids`` for a YES leg, ``no_bids``
  for a NO leg) in the last public 88a book the replay holds when the leg is placed (the replay's placement is
  the acknowledgement; the decision book with our own legs composed in is never used).
- A print is **eligible** for the leg when, on the YES axis exactly as in v2 (a NO print at ``x`` is a YES print at
  ``1 - x``; a NO leg at ``p`` is a YES offer at ``1 - p``), it is *at price* or *strictly through*.
- Each eligible print first consumes the queue ahead, ``c = min(size, queue)``; what is left of the print fills
  the leg, ``min(remaining, size - c)``. Over a window the leg's fill is
  ``min(leg size, max(0, V_at + V_thr - q_ahead))``.

**Minute aggregation (the pure rule).** ``deplete`` sums eligible volume per UTC minute of ``traded_at`` and,
within a minute, lets at-price volume consume the queue before strictly-through volume. Its result is therefore
invariant to print order within a minute (and its total to any order).

**Bounds (proved in the docstring of ``deplete`` and property-tested).** ``0 <= v3 <= at-price bound`` and
``v3 <= strictly-through bound + max(0, V_at - q_ahead)``.

**The engine** evaluates prints in capture order like v2 and, like v2, ends a placement at its first fill. The
existence and the minute of that first fill match the pure rule under any order within a minute; its size can
depend on that order (disclosed; registration draft §4).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial

from maker_core.evidence.journal import digest
from maker_core.quoting.policy import QuoteDecision
from maker_core.replay.bundle import BundleError
from maker_core.replay.fill_model import Fill
from maker_core.replay.fill_v3_embargo import check as embargo_check
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import EPSILON
from maker_core.replay.v2.money import add, mul, q, sub

VERSION = "fill-v3.0"
LABEL = "queue_aware"  # fill-bound label; VERSION carries the rule version
KINDS = ("at", "thr")
ZERO = Decimal(0)
ONE = Decimal(1)


# -- the predicate ----------------------------------------------------------------------------------------
def yes_axis_price(trade) -> Decimal:
    return trade.price if trade.outcome == "YES" else ONE - trade.price


def leg_axis(leg):
    """(side, quote) on the YES axis, exactly as ``fill_model.match``: side 0 bids YES, side 1 offers YES."""
    if leg.outcome == "YES":
        return 0, leg.price
    if leg.outcome == "NO":
        return 1, ONE - leg.price
    raise BundleError("v3_unknown_leg_outcome")


def eligibility(leg, trade) -> str | None:
    """'at' (at our price), 'thr' (strictly through our price) or None, on the YES axis."""
    side, quote = leg_axis(leg)
    price = yes_axis_price(trade)
    if price == quote:
        return "at"
    if (price < quote) if side == 0 else (price > quote):
        return "thr"
    return None


def q_ahead(book, leg) -> Decimal | None:
    """Displayed size at the leg's price on its own bid array; None without a book."""
    if book is None:
        return None
    levels = book.yes_bids if leg.outcome == "YES" else book.no_bids
    return sum((size for price, size in levels if price == leg.price), ZERO)


# -- the pure rule ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Print:
    """An eligible print for one leg: when it traded, whether at price or through, and its size."""
    traded_at: datetime
    kind: str
    size: Decimal

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError("v3_unknown_print_kind")
        if self.traded_at.tzinfo is None or self.traded_at.utcoffset() is None:
            raise ValueError("v3_naive_print_time")
        if not isinstance(self.size, Decimal) or not self.size > 0:
            raise ValueError("v3_print_size")


@dataclass(frozen=True)
class QueueFill:
    total: Decimal
    from_at: Decimal
    from_thr: Decimal
    queue_left: Decimal
    first_fill_minute: datetime | None


def minute_of(at: datetime) -> datetime:
    return at.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _check_leg(size, queue):
    if not isinstance(size, Decimal) or not size > 0:
        raise ValueError("v3_leg_size")
    if not isinstance(queue, Decimal) or queue < 0:
        raise ValueError("v3_queue_ahead")


def deplete(size: Decimal, queue: Decimal, prints) -> QueueFill:
    """The v3 fill of one resting leg of ``size`` behind ``queue`` displayed shares, over eligible ``prints``.

    Per UTC minute, at-price volume ``a`` then strictly-through volume ``t`` each consume the queue and fill the
    rest. Summed, total = min(size, max(0, A + T - queue)) with A, T the window totals, because the queue is
    consumed before any fill and the fill is capped by the leg size. Hence total <= min(size, A + T) (the
    at-price bound) and total <= T + max(0, A - queue) (strictly-through plus the at-price volume beyond the
    queue), and total >= 0.
    """
    _check_leg(size, queue)
    minutes = {}
    for p in prints:
        if not isinstance(p, Print):
            raise ValueError("v3_print_required")
        bucket = minutes.setdefault(minute_of(p.traded_at), {"at": ZERO, "thr": ZERO})
        bucket[p.kind] += p.size
    left, remaining = queue, size
    filled = {"at": ZERO, "thr": ZERO}
    first = None
    for minute in sorted(minutes):
        for kind in KINDS:
            volume = minutes[minute][kind]
            consumed = min(volume, left)
            left -= consumed
            fill = min(remaining, volume - consumed)
            if fill > 0:
                remaining -= fill
                filled[kind] += fill
                first = first or minute
    return QueueFill(filled["at"] + filled["thr"], filled["at"], filled["thr"], left, first)


def at_price_bound(size: Decimal, prints) -> Decimal:
    """v2 ``at_price`` (89a optimistic) summed over a window without the first-fill end: min(size, A + T)."""
    return min(size, sum((p.size for p in prints), ZERO))


def strictly_through_bound(size: Decimal, prints) -> Decimal:
    """v2 ``strictly_through`` (89a conservative) summed over a window: min(size, T)."""
    return min(size, sum((p.size for p in prints if p.kind == "thr"), ZERO))


class QueueState:
    """The streaming form the engine uses: one leg's queue, consumed print by print in arrival order."""

    def __init__(self, size: Decimal, queue: Decimal):
        _check_leg(size, queue)
        self.size, self.left = size, queue

    def consume(self, size: Decimal) -> Decimal:
        """Consume one eligible print; return the leg's fill from it (the leg's full size at most)."""
        consumed = min(size, self.left)
        self.left -= consumed
        return min(self.size, size - consumed)


# -- the engine -------------------------------------------------------------------------------------------
class EngineV3(EngineV2):
    """``EngineV2`` with the v3 queue matcher; every other behaviour is inherited unchanged.

    ``purpose`` is required ('descriptive' or 'scored'): every plan day passes ``fill_v3_embargo.check`` before
    the engine exists, so the reserved window is refused for any purpose and a scored run is refused inside the
    shadow/panel embargo and while the v3 registration is unsigned.
    """

    fill_model = VERSION

    def __init__(self, config, plan, *, sink=None, purpose):
        for day in plan.days:
            embargo_check(day.day, purpose)
        self.purpose = purpose
        self.queues = {}  # condition_id -> tuple[QueueState | None, ...] aligned with state.legs
        super().__init__(config, plan, sink=sink)

    def record_decision(self, cid, at, decision):
        super().record_decision(cid, at, decision)
        state = self.states[cid]
        if decision.action == "QUOTE":
            book = state.latest.get("book")
            if book is None:
                raise BundleError("v3_queue_without_book")
            self.queues[cid] = tuple(QueueState(leg.size, q_ahead(book, leg)) for leg in state.legs)
        elif decision.action in ("CANCEL", "END", "NO_QUOTE"):
            self.queues.pop(cid, None)

    def match_v3(self, cid, legs, trade):
        """Deplete every eligible leg's queue; return the first leg with a fill and its size (v2 leg order)."""
        found = None
        for leg, queue in zip(legs, self.queues.get(cid, ())):
            if eligibility(leg, trade) is None:
                continue
            size = queue.consume(trade.size)
            if size > 0 and found is None:
                found = leg, size
        return found

    def on_trade(self, cid, value, error, at):
        # The kernel's on_trade (v2/kernel.py, frozen) with ``match`` replaced by ``match_v3``; every check, its
        # order and every side effect are the same.
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
        covered, _ = self.valid_coverage(state, at - EPSILON)
        if self.declared and not self.active(cid, at):
            return
        if not state.legs or not covered or not self.active(cid, at - EPSILON):
            return
        if trade.traded_at < state.placed_at:
            self.exclude(at, cid, "PRINT_PREDATES_ORDER")
            return
        matched = self.match_v3(cid, state.legs, trade)
        if matched is None:
            return
        leg, size = matched
        cost = q(mul(leg.price, size))
        fill = Fill(at, trade.traded_at, cid, state.market_id, trade.trade_id, leg.outcome, leg.price, size,
                    LABEL, self.event_window(state, at))
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

    def summary(self):
        return dict(super().summary(), fill_bound=LABEL, fill_model=VERSION, purpose=self.purpose)


def engine_factory(fill_model: str = "v2", *, purpose: str = "descriptive"):
    """The engine class to inject: ``EngineV2`` (the default) or ``EngineV3`` bound to ``purpose``."""
    if fill_model == "v2":
        return EngineV2
    if fill_model == "v3":
        return partial(EngineV3, purpose=purpose)
    raise BundleError("unknown_fill_model")
