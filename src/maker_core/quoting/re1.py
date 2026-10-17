"""Pure RE-1 observation rules, pinned to 2b9a0ca9e (re1_attended.observe).

Selection and submission have stricter gates than an already resting pair.
There is no share-floor pull, touch-buffer pull, or reward-width pull in observe.
"""
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_FLOOR

from maker_core.quoting.prices import QuoteRefused, _levels
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score

SOURCE_COMMIT = "2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8"
SIZES = (20, 30, 50, 75)


@dataclass(frozen=True)
class Observation:
    adjusted_mid: D
    requote_legs: tuple[int, ...]
    share_many: float
    per_minute_many: float


def observe(book, terms, prices, size):
    """The hold rule, including own-depth aggregation before subtraction."""
    if size not in SIZES:
        raise QuoteRefused("treatment_size")
    if terms is None:
        raise QuoteRefused("reward_rate_or_terms")
    minimum, maximum, rate = terms.min_size, terms.max_spread_cents, terms.rate_per_day
    if minimum > size:
        raise QuoteRefused("reward_minimum")
    if minimum <= 0 or maximum <= 0 or rate < 40:
        raise QuoteRefused("reward_rate_or_terms")
    sides = [getattr(book, k) for k in ("yes_bids", "yes_asks", "no_bids", "no_asks")]
    if any(not rows for rows in sides):
        raise QuoteRefused("one_sided_book")
    yb, ya, nb, na = [_levels({"price": p, "size": s} for p, s in rows) for rows in sides]
    for bids, asks in ((yb, ya), (nb, na)):
        if max(p for p, _ in bids) >= min(p for p, _ in asks):
            raise QuoteRefused("crossed_book")
    qb, qa = ([p for p, s in levels if s >= minimum] for levels in (yb, ya))
    if not qb or not qa:
        raise QuoteRefused("no_size_adjusted_midpoint")
    mid = (max(qb) + min(qa)) / 2
    yes, no = prices
    scores = []
    for levels, own_price in ((yb, yes), (ya, 1 - no)):
        aggregate = {}
        for p, s in levels:
            aggregate[p] = aggregate.get(p, D(0)) + s
        aggregate[own_price] = max(D(0), aggregate.get(own_price, D(0)) - size)
        scores.append(side_score([(float(p), float(s)) for p, s in aggregate.items() if s > 0],
                                 float(mid), float(maximum), float(minimum))[0])
    distances = ((mid - yes) * 100, (1 - mid - no) * 100)
    own = q_min(*(order_score(float(size), float(d), float(maximum), float(minimum))
                  for d in distances), float(mid))
    share = share_of(own, sum(scores) / 2)
    return Observation(mid, tuple(i for i, d in enumerate(distances) if not 1 <= d <= 3),
                       share, float(rate) / 1440 * share)


def replacement_price(mid, leg):
    centre = mid if leg == 0 else 1 - mid
    return ((centre - D('.015')) / D('.01')).to_integral_value(rounding=ROUND_FLOOR) * D('.01')


def reserve_budget(available):
    if not available.is_finite() or not 0 <= available <= 200:
        raise QuoteRefused('testing_wallet_cap')
    return min(available - 10, D(75))


def session_caps(size, available):
    if size not in SIZES:
        raise QuoteRefused('invalid_treatment_size')
    return D('.79') * size, min(D('.98') * size, reserve_budget(available))
