"""Pure proposal kernel shared by offline fixtures and future runners.

All clocks, portfolio reservations, hazards and caps are caller inputs. This
module grants no trading authority. Cents are explicitly named; prices are
Decimal probabilities. No default wallet or risk-cap authority is invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math

from maker_core.contracts import MarketDescriptor, OutcomeView, Unavailable, InfoEvent, utc_time
from maker_core.evidence.journal import digest
from maker_core.quoting.prices import (
    QuoteRefused, _levels, qualified_mid, outward, touch_buffer, price_sized_reward_quote,
)
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score

D = Decimal


@dataclass(frozen=True)
class Profile:
    name: str
    informed: bool
    d0_cents: Decimal = D("1.5")
    d_lo_cents: Decimal = D("1")
    d_hi_cents: Decimal = D("3")
    sizes: tuple[int, ...] = (20, 30, 50, 75)
    first_fill_ends: bool = False
    max_bands: int | None = None
    stale_sigma_per_hour: float = 0.01
    # Unscored probabilities cannot skew/drop a leg or justify the largest sizes.
    # These are conservative offline defaults, not empirically fitted parameters.
    grade_size_caps: tuple[int, int, int] = (30, 50, 75)
    eligible_horizons: tuple[int, ...] | None = (1, 2)


informed_v0 = Profile("informed_v0", True)
blind_re1 = Profile("blind_re1", False, first_fill_ends=True, max_bands=1, eligible_horizons=None)


@dataclass(frozen=True)
class Book:
    as_of_utc: datetime
    yes_bids: tuple[tuple[Decimal, Decimal], ...]
    yes_asks: tuple[tuple[Decimal, Decimal], ...]
    no_bids: tuple[tuple[Decimal, Decimal], ...]
    no_asks: tuple[tuple[Decimal, Decimal], ...]
    post_only_available: bool = True

    def __post_init__(self):
        utc_time(self.as_of_utc)
        for name in ("yes_bids", "yes_asks", "no_bids", "no_asks"):
            object.__setattr__(self, name, tuple(tuple(level) for level in getattr(self, name)))


@dataclass(frozen=True)
class RewardTerms:
    as_of_utc: datetime
    min_size: Decimal
    max_spread_cents: Decimal
    rate_per_day: Decimal

    def __post_init__(self):
        utc_time(self.as_of_utc)
        if any(not v.is_finite() or v <= 0 for v in
               (self.min_size, self.max_spread_cents, self.rate_per_day)):
            raise ValueError("invalid reward terms")


@dataclass(frozen=True)
class ExposureLimit:
    factor: str
    loading: Decimal
    used: Decimal
    cap: Decimal


@dataclass(frozen=True)
class Portfolio:
    cash: Decimal
    reserved_elsewhere: Decimal
    band_cap: Decimal
    order_cap: Decimal
    wallet_used: Decimal
    wallet_cap: Decimal
    event_used: Decimal
    event_cap: Decimal
    exposures: tuple[ExposureLimit, ...] = ()
    foreign_open_order: bool = False
    unknown_position: bool = False
    safety_breached: bool = False
    active_other_bands: int = 0

    def __post_init__(self):
        values = (self.cash, self.reserved_elsewhere, self.band_cap, self.order_cap,
                  self.wallet_used, self.wallet_cap, self.event_used, self.event_cap)
        if any(not v.is_finite() or v < 0 for v in values):
            raise ValueError("invalid portfolio")
        object.__setattr__(self, "exposures", tuple(self.exposures))
        for e in self.exposures:
            if any(not v.is_finite() for v in (e.loading, e.used, e.cap)) or min(e.used, e.cap) < 0:
                raise ValueError("invalid exposure")


@dataclass(frozen=True)
class QuoteLeg:
    outcome: str
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class DecisionInputs:
    market: MarketDescriptor
    now: datetime
    book: Book
    terms: RewardTerms | None
    fair_value: OutcomeView | Unavailable
    portfolio: Portfolio
    horizon_days: int  # Plugin-owned LOCAL date calculation, never UTC inferred.
    events: tuple[InfoEvent, ...] = ()
    profile: Profile = informed_v0
    hazard_per_minute: float | None = None
    adverse_markout: float = 0.0043  # Probability-unit loss per filled share.
    existing: tuple[QuoteLeg, ...] = ()
    fill_seen: bool = False
    last_requote_at: datetime | None = None
    previous_fair_value: float | None = None

    def __post_init__(self):
        utc_time(self.now)
        if self.hazard_per_minute is not None and not math.isfinite(self.hazard_per_minute):
            raise ValueError("nonfinite hazard")
        if not math.isfinite(self.adverse_markout):
            raise ValueError("nonfinite markout")
        if self.last_requote_at is not None:
            utc_time(self.last_requote_at)
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "existing", tuple(self.existing))


@dataclass(frozen=True)
class QuoteDecision:
    action: str  # QUOTE / HOLD / NO_QUOTE / CANCEL / END
    legs: tuple[QuoteLeg, ...]
    reasons: tuple[str, ...]
    input_hash: str
    profile: str
    centre: Decimal | None = None
    share_many: float = 0.0
    net_per_minute: float = 0.0


def _rows(levels):
    return tuple({"price": p, "size": s} for p, s in levels)


def _fits(legs, p):
    reserve = sum((leg.price * leg.size for leg in legs), D(0))
    return (reserve <= p.band_cap and reserve <= p.cash - p.reserved_elsewhere
            and reserve + p.wallet_used <= p.wallet_cap
            and reserve + p.event_used <= p.event_cap
            and all(leg.price * leg.size <= p.order_cap for leg in legs)
            and all(e.used + reserve * abs(e.loading) <= e.cap for e in p.exposures))


def _event_active(event, now):
    if event.active_until_utc is not None and now > event.active_until_utc:
        return False
    if event.detected_at_utc is not None:
        return event.detected_at_utc <= now  # Caller retains unresolved detected events.
    if event.observed_at_utc is not None:
        return event.observed_at_utc <= now
    return (event.scheduled_at_utc is not None
            and event.scheduled_at_utc - timedelta(minutes=3) <= now
            <= event.scheduled_at_utc + timedelta(minutes=10))


def decide(inputs: DecisionInputs) -> QuoteDecision:
    """Deterministic proposal; cancels precede cooldowns and economic screens.

    Portfolio used/reserved values exclude the current band's replaceable open
    orders, include held inventory, and include all other markets' commitments.
    """
    i, p = inputs, inputs.profile
    h = digest(i)
    mid = None

    def result(reason, *, legs=(), action=None, share=0.0, net=0.0):
        return QuoteDecision(action or ("CANCEL" if i.existing else "NO_QUOTE"),
                             tuple(legs), (reason,), h, p.name, mid, share, net)

    if p.name not in ("informed_v0", "blind_re1") or p.informed != (p.name == "informed_v0"):
        return result("UNSUPPORTED_PROFILE")
    if i.fill_seen:
        return result("FIRST_FILL_ENDS" if p.first_fill_ends else "FILL_CANCEL_SIBLING",
                      action="END" if p.first_fill_ends else "CANCEL")
    portfolio = i.portfolio
    if portfolio.foreign_open_order or portfolio.unknown_position:
        return result("UNKNOWN_ACCOUNT_STATE")
    if (portfolio.safety_breached or portfolio.wallet_used > portfolio.wallet_cap
            or portfolio.event_used > portfolio.event_cap
            or portfolio.reserved_elsewhere > portfolio.cash
            or any(e.used > e.cap for e in portfolio.exposures)):
        return result("SAFETY_BUDGET")
    if p.max_bands is not None and portfolio.active_other_bands >= p.max_bands:
        return result("ONE_BAND_ONLY")
    if not 0 <= (i.now - i.book.as_of_utc).total_seconds() <= 10:
        return result("BOOK_STALE_OR_FUTURE")
    t = i.terms
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
    if not D(".2") <= mid <= D(".8"):
        return result("MID_OUTSIDE_RANGE")
    active = [e for e in i.events if i.market.condition_id in e.affects and _event_active(e, i.now)]
    if p.informed:
        if any((e.decided or {}).get(i.market.condition_id, 0) >= .5 for e in active):
            return result("DECIDED")
        if any(e.action_hint == "pull" for e in active):
            return result("INFO_PULL")
        if p.eligible_horizons is not None and i.horizon_days not in p.eligible_horizons:
            return result("HORIZON_NOT_ELIGIBLE")
        if (i.hazard_per_minute is None or not math.isfinite(i.hazard_per_minute)
                or not 0 <= i.hazard_per_minute <= 1 or not math.isfinite(i.adverse_markout)
                or i.adverse_markout < .0043):
            return result("MISSING_CONSERVATIVE_FILL_BOUND")
    view = i.fair_value if p.informed and isinstance(i.fair_value, OutcomeView) else None
    if view is not None:
        if (view.condition_id != i.market.condition_id
                or not view.as_of_utc <= i.now < view.valid_until_utc):
            return result("FAIR_VALUE_INVALID_OR_EXPIRED")
        if abs(view.p_yes - float(mid)) > view.stdev:
            return result("FAIR_VALUE_DISAGREEMENT")
    elif p.informed and i.fair_value.as_of_utc > i.now:
        return result("FAIR_VALUE_FUTURE")

    maximum_width = min(p.d_hi_cents, t.max_spread_cents - i.market.tick * 100)
    if maximum_width < p.d_lo_cents:
        return result("NO_REWARD_WIDTH")
    width, skew = p.d0_cents, D(0)
    size_cap = p.grade_size_caps[0] if p.informed else 75
    sigma_eff = 0.0
    if view:
        age_hours = (i.now - view.as_of_utc).total_seconds() / 3600
        sigma_eff = math.hypot(view.stdev, age_hours * p.stale_sigma_per_hour)
        width = max(width, D(str(sigma_eff * 100)))
        if view.calibration_grade != "none":
            skew = D(str(view.p_yes)) - mid
        size_cap = p.grade_size_caps[("none", "shadow", "scored").index(view.calibration_grade)]
    if p.informed:
        width = max(width, *(D(str(e.severity)) * t.max_spread_cents for e in active
                             if e.action_hint in ("widen", "recentre")), p.d_lo_cents)
    width = min(max(width, p.d_lo_cents), maximum_width)
    distances = (width - D(".5") * skew * 100, width + D(".5") * skew * 100)

    def external_levels(rows, outcome):
        own = {}
        for leg in i.existing:
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

    external = (external_levels(yb, "YES"), external_levels(ya, "NO"))
    comp = [side_score([(float(a), float(b)) for a, b in rows], float(mid),
                       float(t.max_spread_cents), float(t.min_size)) for rows in external]
    competing = (comp[0][0] + comp[1][0]) / 2
    displayed_depth = [sum((size for price, size in rows
                            if abs(price - mid) * 100 < t.max_spread_cents), D(0))
                       for rows in external]

    def economics(legs):
        scores = {leg.outcome: order_score(float(leg.size),
                  float(((mid if leg.outcome == "YES" else 1 - mid) - leg.price) * 100),
                  float(t.max_spread_cents), float(t.min_size)) for leg in legs}
        own = q_min(scores.get("YES", 0), scores.get("NO", 0), float(mid))
        share = share_of(own, competing)
        # Hazard is a per-band-minute bound: size is maximum shares filled in that bound.
        cost = (i.hazard_per_minute or 0) * i.adverse_markout * float(max(leg.size for leg in legs))
        return share, float(t.rate_per_day) / 1440 * share - cost

    def eligible(legs):
        if not legs or not _fits(legs, portfolio):
            return "CASH_OR_CAP"
        if view and view.calibration_grade == "none":
            sides = {leg.outcome: leg for leg in legs}
            if (len(legs) != 2 or set(sides) != {"YES", "NO"}
                    or sides["YES"].size != sides["NO"].size
                    or mid - sides["YES"].price != 1 - mid - sides["NO"].price):
                return "UNCALIBRATED_ASYMMETRY"
        for leg in legs:
            if leg.outcome not in ("YES", "NO") or leg.size not in p.sizes or leg.size < max(t.min_size, i.market.min_order_size):
                return "SIZE_BELOW_MINIMUM"
            centre = mid if leg.outcome == "YES" else 1 - mid
            distance = (centre - leg.price) * 100
            if (leg.price % i.market.tick or not p.d_lo_cents <= distance <= p.d_hi_cents
                    or distance >= t.max_spread_cents):
                return "OUTSIDE_REQUOTE_WINDOW"
            if not touch_buffer(leg.price, ya if leg.outcome == "YES" else na, i.market.tick):
                return "TOUCH_BUFFER"
        if p.informed and min(displayed_depth) < max(75, max(leg.size for leg in legs)):
            return "INSUFFICIENT_DEPTH"
        return None

    desired = None
    rejection = "NO_ELIGIBLE_SIZE"
    for size in reversed(p.sizes):
        if size > size_cap or size < max(t.min_size, i.market.min_order_size):
            continue
        if not p.informed:
            try:
                quote = price_sized_reward_quote(
                    yes_bids=_rows(yb), yes_asks=_rows(ya), no_bids=_rows(nb), no_asks=_rows(na),
                    reward_min_size=t.min_size, reward_max_spread_cents=t.max_spread_cents,
                    reward_rate_per_day=t.rate_per_day, tick=i.market.tick,
                    post_only_available=i.book.post_only_available, size=size,
                    per_order_ceiling=min(portfolio.order_cap, D(".8") * size),
                    per_band_ceiling=min(portfolio.band_cap, D(size)))
                legs = (QuoteLeg("YES", quote.yes_buy, D(size)), QuoteLeg("NO", quote.no_buy, D(size)))
            except QuoteRefused as exc:
                rejection = str(exc).upper()
                continue
        else:
            def snapped(centre, distance):
                price = outward(centre - max(p.d_lo_cents, distance) / 100, i.market.tick)
                if ((centre - price) * 100 > p.d_hi_cents
                        and (centre - price - i.market.tick) * 100 >= p.d_lo_cents):
                    price += i.market.tick
                return price

            legs = tuple(QuoteLeg(outcome, snapped(centre, d), D(size))
                         for outcome, centre, d in zip(("YES", "NO"), (mid, 1 - mid), distances)
                         if d <= maximum_width)
        reason = eligible(legs)
        if reason:
            rejection = reason
            continue
        share, net = economics(legs)
        if p.informed and net <= 0:
            rejection = "NONPOSITIVE_NET"
            continue
        if p.informed and not .15 <= share <= .70:
            rejection = "COMPETITION_OUTSIDE_RANGE"
            continue
        desired = (legs, share, net)
        break

    if i.existing:
        if any(leg.size > size_cap for leg in i.existing):
            return result("GRADE_SIZE_CAP")
        reason = eligible(i.existing)
        if reason:
            return result(reason)  # cancel before any replacement proposal
        old_share, old_net = economics(i.existing)
        if old_share < .05:
            return result("SHARE_BELOW_PULL_FLOOR")
        if p.informed and old_net <= 0:
            return result("NONPOSITIVE_NET")
        if not p.informed:
            return result("WITHIN_REQUOTE_WINDOW", legs=i.existing, action="HOLD", share=old_share, net=old_net)
        delta = (abs(D(str(view.p_yes)) - D(str(i.previous_fair_value)))
                 if i.previous_fair_value is not None and view is not None else D(0))
        # Midpoint drift is not new fair-value information. Only a changed view
        # can bypass cooldown while otherwise eligible resting legs remain safe.
        if delta / 2 >= i.market.tick or delta > D(str(max(sigma_eff, .01))):
            return result("ADVERSE_LEG_CHANGED")
        if not delta or desired is None or desired[0] == i.existing:
            return result("WITHIN_REQUOTE_WINDOW", legs=i.existing, action="HOLD", share=old_share, net=old_net)
        if i.last_requote_at is not None:
            elapsed = (i.now - i.last_requote_at).total_seconds()
            if elapsed < 0:
                return result("REQUOTE_CLOCK_FUTURE")
            if elapsed < 60:
                return result("REQUOTE_COOLDOWN", legs=i.existing, action="HOLD", share=old_share, net=old_net)
        return result("REQUOTE_REQUIRED")
    if desired is None:
        return result(rejection)
    legs, share, net = desired
    return result("INFORMED_QUOTE" if p.informed else "BLIND_RE1_QUOTE",
                  legs=legs, action="QUOTE", share=share, net=net)


def rank(candidates: tuple[DecisionInputs, ...]) -> tuple[QuoteDecision, ...]:
    """Rank eligible proposals: low decided, near 0.5, then conservative net.

    Rank does not reserve cash. The caller must update the shared portfolio and
    call decide again before admitting each additional band.
    """
    eligible = []
    for inputs in candidates:
        decision = decide(inputs)
        if decision.action == "QUOTE":
            decided = max((e.decided.get(inputs.market.condition_id, 0)
                           for e in inputs.events if e.decided and _event_active(e, inputs.now)), default=0)
            eligible.append(((decided, abs(decision.centre - D(".5")), -decision.net_per_minute,
                              inputs.market.condition_id), decision))
    return tuple(d for _, d in sorted(eligible, key=lambda row: row[0]))


def inventory_action(*, model_move: float, exit_price: float, expected_adverse_move: float,
                     reward_eligible_resting_sell: bool) -> str:
    """Advisory inventory rule only; no orders and no second portfolio ledger."""
    if not all(math.isfinite(v) for v in (model_move, exit_price, expected_adverse_move)):
        raise ValueError("finite inventory inputs required")
    if not 0 <= exit_price <= 1 or expected_adverse_move < 0:
        raise ValueError("invalid inventory inputs")
    fee = .05 * exit_price * (1 - exit_price)
    if model_move > fee + expected_adverse_move:
        return "EXIT_REVIEW"
    return "RESTING_REWARD_SELL" if reward_eligible_resting_sell else "HOLD"
