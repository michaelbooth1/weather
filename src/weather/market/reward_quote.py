"""Pure RE-1 place-and-hold pricing. A quote is a proposal, never authority.

Prices and capital use Decimal. Reward shares are the two displayed-depth
scenarios from reward_share_estimate, not guaranteed payout bounds. This module
does not load credentials, construct clients, or submit orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import math
from typing import Iterable, Mapping

from weather.market.reward_share_estimate import order_score, q_min, share_of, side_score


class QuoteRefused(ValueError):
    """The supplied public inputs cannot support the frozen treatment."""


def _decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuoteRefused("invalid_number") from exc
    if isinstance(value, bool) or not number.is_finite() or not math.isfinite(float(number)):
        raise QuoteRefused("invalid_number")
    return number


def _levels(rows: Iterable[Mapping[str, object]]) -> tuple[tuple[Decimal, Decimal], ...]:
    levels = []
    try:
        for row in rows:
            price, size = _decimal(row["price"]), _decimal(row["size"])
            if not 0 < price < 1 or size <= 0:
                raise QuoteRefused("invalid_book")
            levels.append((price, size))
    except (KeyError, TypeError) as exc:
        raise QuoteRefused("invalid_book") from exc
    if not levels:
        raise QuoteRefused("one_sided_book")
    return tuple(levels)


@dataclass(frozen=True)
class RewardQuote:
    adjusted_mid: Decimal
    yes_buy: Decimal
    no_buy: Decimal
    size: Decimal
    reserve_pusd: Decimal
    own_q_min: float
    competing_q_many: float
    competing_q_single: float
    share_many: float
    share_single: float
    predicted_per_minute_many: float
    predicted_per_minute_single: float


def price_reward_quote(
    *,
    yes_bids: Iterable[Mapping[str, object]],
    yes_asks: Iterable[Mapping[str, object]],
    no_bids: Iterable[Mapping[str, object]],
    no_asks: Iterable[Mapping[str, object]],
    reward_min_size: object,
    reward_max_spread_cents: object,
    reward_rate_per_day: object,
    tick: object,
    post_only_available: bool,
    per_order_ceiling: object = "16",
    per_band_ceiling: object = "20",
) -> RewardQuote:
    """Price twenty shares per leg, 1.5 cents outward from size-adjusted mid.

The YES book supplies the estimator's two competing-depth scenarios. Both
actual token books supply touch checks; inferring a complementary ask is not
enough to prove that the NO buy would be nonmarketable. Reward-minimum-sized
levels supply the adjusted midpoint; smaller touch orders still bind safety.
Ceilings may only be lowered. No profile is selected by this pure calculation.
"""
    minimum = _decimal(reward_min_size)
    maximum = _decimal(reward_max_spread_cents)
    rate = _decimal(reward_rate_per_day)
    step = _decimal(tick)
    order_cap, band_cap = _decimal(per_order_ceiling), _decimal(per_band_ceiling)
    if not 0 < minimum <= 20:
        raise QuoteRefused("reward_minimum_outside_treatment")
    if maximum < 3 or rate < 40:
        raise QuoteRefused("reward_terms_outside_treatment")
    if step != Decimal("0.01"):
        raise QuoteRefused("unsupported_tick")
    if post_only_available is not True:
        raise QuoteRefused("post_only_unavailable")
    if not (0 < order_cap <= 16 and 0 < band_cap <= 20):
        raise QuoteRefused("invalid_capital_ceiling")
    yb, ya, nb, na = map(_levels, (yes_bids, yes_asks, no_bids, no_asks))
    for bids, asks in ((yb, ya), (nb, na)):
        if any(price % step for price, _ in (*bids, *asks)):
            raise QuoteRefused("off_tick_book")
        spread = min(price for price, _ in asks) - max(price for price, _ in bids)
        if spread <= 0:
            raise QuoteRefused("crossed_book")
        if spread > Decimal("0.06"):
            raise QuoteRefused("spread_too_wide")
    qualified_bids = [p for p, size in yb if size >= minimum]
    qualified_asks = [p for p, size in ya if size >= minimum]
    if not qualified_bids or not qualified_asks:
        raise QuoteRefused("no_size_adjusted_midpoint")
    mid = (max(qualified_bids) + min(qualified_asks)) / 2
    if not Decimal("0.20") <= mid <= Decimal("0.80"):
        raise QuoteRefused("midpoint_outside_treatment")

    def outward(value: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step

    yes = outward(mid - Decimal("0.015"))
    no = outward(1 - mid - Decimal("0.015"))
    for buy, asks in ((yes, ya), (no, na)):
        if buy <= 0 or min(price for price, _ in asks) - buy < step:
            raise QuoteRefused("would_cross_or_violate_touch_buffer")
    size = Decimal("20")
    reserve = size * (yes + no)
    if max(yes, no) * size > order_cap or reserve > band_cap:
        raise QuoteRefused("capital_ceiling_exceeded")
    distances = ((mid - yes) * 100, (1 - mid - no) * 100)
    if any(not Decimal("1.0") <= d <= Decimal("3.0") or d >= maximum for d in distances):
        raise QuoteRefused("outside_leave_alone_window")
    own = q_min(*(order_score(20, float(d), float(maximum), float(minimum)) for d in distances), float(mid))
    scores = [
        side_score([(float(p), float(s)) for p, s in levels], float(mid), float(maximum), float(minimum))[0]
        for levels in (yb, ya)
    ]
    many, single = sum(scores) / 2, q_min(*scores, float(mid))
    share_many, share_single = share_of(own, many), share_of(own, single)
    return RewardQuote(
        mid, yes, no, size, reserve, own, many, single, share_many, share_single,
        float(rate) / 1440 * share_many, float(rate) / 1440 * share_single,
    )
