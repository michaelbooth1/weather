"""One-sided edge maker profile: a second candidate beside the frozen informed-v0.

The model trails the market in every measured slice, so a model direction is off
unless a calibration table marks the cell skilled. Observation decidedness is
the only default directional signal. With no signal, or an edge inside the
margin, the unchanged informed-v0 kernel decides. No IO, clocks or authority.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal
import math

from maker_core.contracts import OutcomeView
from maker_core.evidence.journal import digest
from maker_core.quoting.policy import (
    DecisionInputs, Profile, QuoteDecision, QuoteLeg, _event_active, _fits, _rows, decide, informed_v0,
)
from maker_core.quoting.prices import QuoteRefused, _levels, outward, qualified_mid, touch_buffer
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score

D = Decimal
NAME = "one-sided-edge-v0"
MIN_MARGIN = 0.0043  # Probability units: the conservative adverse markout floor.
ONE_SIDED_MID = (D(".10"), D(".90"))  # One-sided reward score is S/3 inside, zero outside.
BAND_KINDS = ("lte", "eq", "gte")


@dataclass(frozen=True)
class EdgeProfile(Profile):
    """Extra fields live only here, so informed-v0 input-hash bytes cannot change.

    z, a and K are fixed after the 10-15 reliability table by an owner signature.
    Until then z and K are None and the model-probability side cannot fire.
    """
    eligible_horizons: tuple[int, ...] | None = (0, 1, 2)
    z: float | None = None
    a: float = MIN_MARGIN
    K: float | None = None
    skilled_cells: tuple[tuple[str, int], ...] = ()  # (model_id, horizon_days) from a calibration table.

    def __post_init__(self):
        if self.name != NAME or not self.informed or self.first_fill_ends or self.max_bands is not None:
            raise ValueError("edge profile identity")
        if isinstance(self.a, bool) or not math.isfinite(self.a) or self.a < MIN_MARGIN:
            raise ValueError("edge margin below the adverse markout floor")
        for value in (self.z, self.K):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value <= 0):
                raise ValueError("edge parameters must be positive and finite")
        object.__setattr__(self, "skilled_cells", tuple(tuple(c) for c in self.skilled_cells))
        if any(len(c) != 2 or not isinstance(c[0], str) or type(c[1]) is not int for c in self.skilled_cells):
            raise ValueError("skilled cell is (model_id, horizon_days)")


one_sided_edge_v0 = EdgeProfile(NAME, True)


@dataclass(frozen=True)
class EdgeDecisionInputs(DecisionInputs):
    band_kind: str | None = None  # Captured band shape; None means decidedness has no direction.
    event_yes_elsewhere: bool = False  # Another band of this event holds a YES leg or YES inventory.

    def __post_init__(self):
        super().__post_init__()
        if self.band_kind not in (None, *BAND_KINDS) or type(self.event_yes_elsewhere) is not bool:
            raise ValueError("invalid edge inputs")


@dataclass(frozen=True)
class EdgeQuoteDecision(QuoteDecision):
    signal: str = "none"  # none / observed_dead / model
    expected_edge: float | None = None  # Per filled share at the leg price; never in the net screen.


def edge_inputs(value: DecisionInputs, profile: EdgeProfile = one_sided_edge_v0, **extra) -> EdgeDecisionInputs:
    base = {f.name: getattr(value, f.name) for f in fields(DecisionInputs)}
    return EdgeDecisionInputs(**{**base, "profile": profile, **extra})


def _base(i: EdgeDecisionInputs) -> DecisionInputs:
    return DecisionInputs(**{**{f.name: getattr(i, f.name) for f in fields(DecisionInputs)}, "profile": informed_v0})


def decide_one_sided(i: EdgeDecisionInputs) -> EdgeQuoteDecision:
    """Deterministic one-leg proposal; cancels precede any replacement proposal."""
    p, h, cid = i.profile, digest(i), i.market.condition_id
    mid = None

    def result(reason, *, legs=(), action=None, share=0.0, net=0.0, signal="none", edge=None):
        return EdgeQuoteDecision(action or ("CANCEL" if i.existing else "NO_QUOTE"), tuple(legs), (reason,),
                                 h, NAME, mid, share, net, signal, edge)

    if not isinstance(p, EdgeProfile) or not isinstance(i, EdgeDecisionInputs):
        return result("UNSUPPORTED_PROFILE")
    if i.fill_seen:
        return result("HOLD_TO_SETTLEMENT")  # Exit is advisory only: policy.inventory_action.
    portfolio, t = i.portfolio, i.terms
    if portfolio.foreign_open_order or portfolio.unknown_position:
        return result("UNKNOWN_ACCOUNT_STATE")
    if (portfolio.safety_breached or portfolio.wallet_used > portfolio.wallet_cap
            or portfolio.event_used > portfolio.event_cap or portfolio.reserved_elsewhere > portfolio.cash
            or any(e.used > e.cap for e in portfolio.exposures)):
        return result("SAFETY_BUDGET")
    if not 0 <= (i.now - i.book.as_of_utc).total_seconds() <= 10:
        return result("BOOK_STALE_OR_FUTURE")
    if t is None or not 0 <= (i.now - t.as_of_utc).total_seconds() <= 3600:
        return result("TERMS_MISSING_STALE_OR_FUTURE")
    if not i.book.post_only_available:
        return result("POST_ONLY_UNAVAILABLE")
    if i.market.close_at_utc - i.now <= timedelta(hours=3):
        return result("LAST_THREE_HOURS")
    try:
        yb, ya, nb, na = tuple(_levels(_rows(levels)) for levels in
                               (i.book.yes_bids, i.book.yes_asks, i.book.no_bids, i.book.no_asks))
        for bids, asks in ((yb, ya), (nb, na)):
            if max(v for v, _ in bids) >= min(v for v, _ in asks):
                return result("CROSSED_BOOK")
            if any(price % i.market.tick for price, _ in (*bids, *asks)):
                return result("OFF_TICK_BOOK")
        mid = qualified_mid(yb, ya, t.min_size)
    except (QuoteRefused, ValueError, TypeError):
        return result("NO_QUALIFIED_MID")
    if p.eligible_horizons is not None and i.horizon_days not in p.eligible_horizons:
        return result("HORIZON_NOT_ELIGIBLE")
    if (i.hazard_per_minute is None or not 0 <= i.hazard_per_minute <= 1
            or not math.isfinite(i.adverse_markout) or i.adverse_markout < MIN_MARGIN):
        return result("MISSING_CONSERVATIVE_FILL_BOUND")

    active = [e for e in i.events if cid in e.affects and _event_active(e, i.now)]
    vetoes, side, signal, fair = set(), None, "none", None
    if any((e.decided or {}).get(cid, 0) >= .5 for e in active):
        if i.band_kind is None:
            return result("DECIDED_DIRECTION_UNKNOWN")
        if i.band_kind == "gte":
            vetoes.add("NO")  # The open-top band, once reached, cannot lose.
        else:
            # A running maximum only rises, so later prints cannot revive a dead
            # band: its pull hints do not pull the NO leg, and YES is vetoed.
            vetoes.add("YES")
            side, signal, fair = "NO", "observed_dead", D(1)
    view = i.fair_value if isinstance(i.fair_value, OutcomeView) else None
    if view is not None and (view.condition_id != cid or not view.as_of_utc <= i.now < view.valid_until_utc):
        view = None
    sigma_eff = 0.0
    if view is not None:
        sigma_eff = math.hypot(view.stdev, (i.now - view.as_of_utc).total_seconds() / 3600 * p.stale_sigma_per_hour)
    if side is None and view is not None and p.z is not None and p.K is not None and (
            view.calibration_grade == "scored" and (view.model_id, i.horizon_days) in p.skilled_cells):
        e = view.p_yes - float(mid)
        if p.z * sigma_eff + p.a <= abs(e) <= p.K * sigma_eff:
            model_side = "YES" if e > 0 else "NO"
            if model_side not in vetoes:
                if any(x.action_hint == "pull" for x in active):
                    return result("INFO_PULL")
                if any(x.action_hint == "widen" and view.as_of_utc < _reference(x) for x in active):
                    return result("AWAIT_FRESH_VIEW")
                side, signal = model_side, "model"
                fair = D(str(view.p_yes)) if side == "YES" else 1 - D(str(view.p_yes))

    if side is None:
        if len(i.existing) == 1:
            return result("SIGNAL_LOST")
        base = decide(_base(i))
        if any(leg.outcome in vetoes for leg in (*base.legs, *i.existing)):
            return result("OBSERVED_VETO")
        return EdgeQuoteDecision(base.action, base.legs, (*base.reasons, "SYMMETRIC_FALLBACK"), h, NAME,
                                 base.centre, base.share_many, base.net_per_minute)
    if side == "YES" and i.event_yes_elsewhere:
        return result("ONE_YES_PER_EVENT")
    if len(i.existing) > 1:
        return result("SIGNAL_ONSET")
    if i.existing and i.existing[0].outcome != side:
        return result("SIDE_FLIP")
    if not ONE_SIDED_MID[0] <= mid <= ONE_SIDED_MID[1]:
        return result("MID_OUTSIDE_ONE_SIDED_RANGE")

    centre, asks = (mid, ya) if side == "YES" else (1 - mid, na)
    external = (_external(yb, i.existing, "YES"), _external(ya, i.existing, "NO"))
    competing = sum(side_score([(float(a), float(b)) for a, b in rows], float(mid),
                               float(t.max_spread_cents), float(t.min_size))[0] for rows in external) / 2
    quoted_depth = sum((size for price, size in external[side == "NO"]
                        if abs(price - mid) * 100 < t.max_spread_cents), D(0))
    size_cap = p.grade_size_caps[("none", "shadow", "scored").index(view.calibration_grade) if view else 0]

    def eligible(leg):
        distance = (centre - leg.price) * 100
        if leg.size not in p.sizes or leg.size < max(t.min_size, i.market.min_order_size) or leg.size > size_cap:
            return "SIZE_BELOW_MINIMUM"
        if leg.price % i.market.tick or not p.d_lo_cents <= distance < t.max_spread_cents:
            return "OUTSIDE_REQUOTE_WINDOW"
        if not touch_buffer(leg.price, asks, i.market.tick):
            return "TOUCH_BUFFER"
        if not _fits((leg,), portfolio):
            return "CASH_OR_CAP"
        if quoted_depth < max(75, leg.size):
            return "INSUFFICIENT_DEPTH"
        return None

    def economics(leg):
        own = order_score(float(leg.size), float((centre - leg.price) * 100), float(t.max_spread_cents), float(t.min_size))
        share = share_of(q_min(own, 0.0, float(mid)), competing)
        # Rewards only: expected edge is recorded, never credited against hazard.
        return share, float(t.rate_per_day) / 1440 * share - i.hazard_per_minute * i.adverse_markout * float(leg.size)

    desired, rejection = None, "NO_ELIGIBLE_SIZE"
    for size in reversed(p.sizes):
        if size > size_cap or size < max(t.min_size, i.market.min_order_size):
            continue
        price = outward(centre - p.d_lo_cents / 100, i.market.tick)
        leg, reason = None, "OUTSIDE_REQUOTE_WINDOW"
        while price > 0 and (centre - price) * 100 < t.max_spread_cents:
            leg = QuoteLeg(side, price, D(size))
            reason = eligible(leg)
            if reason != "TOUCH_BUFFER":
                break
            price -= i.market.tick  # Tightest reward-eligible distance behind the touch.
        if reason:
            rejection = reason
            continue
        share, net = economics(leg)
        if net <= 0:
            rejection = "NONPOSITIVE_NET"
            continue
        desired = leg, share, net
        break

    if i.existing:
        held = i.existing[0]
        reason = eligible(held)
        if reason:
            return result(reason)
        share, net = economics(held)
        if net <= 0:
            return result("NONPOSITIVE_NET")
        edge = float(fair - held.price)
        if desired is None or desired[0] == held:
            return result("WITHIN_REQUOTE_WINDOW", legs=i.existing, action="HOLD", share=share, net=net,
                          signal=signal, edge=edge)
        if i.last_requote_at is not None and 0 <= (i.now - i.last_requote_at).total_seconds() < 60:
            return result("REQUOTE_COOLDOWN", legs=i.existing, action="HOLD", share=share, net=net,
                          signal=signal, edge=edge)
        return result("REQUOTE_REQUIRED")
    if desired is None:
        return result(rejection)
    leg, share, net = desired
    return result("ONE_SIDED_QUOTE", legs=(leg,), action="QUOTE", share=share, net=net,
                  signal=signal, edge=float(fair - leg.price))


def _reference(event):
    return event.detected_at_utc or event.observed_at_utc or event.scheduled_at_utc


def _external(rows, existing, outcome):
    """Displayed depth with own resting size removed, as informed-v0 measures it."""
    own = {}
    for leg in existing:
        if leg.outcome == outcome:
            price = leg.price if outcome == "YES" else 1 - leg.price
            own[price] = own.get(price, D(0)) + leg.size
    remaining = []
    for price, size in rows:
        removed = min(size, own.get(price, D(0)))
        own[price] = own.get(price, D(0)) - removed
        if size > removed:
            remaining.append((price, size - removed))
    return remaining
