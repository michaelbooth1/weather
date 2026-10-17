"""Frozen RE-1 observe/replacement functions from the pinned source manifest.
Only imports and the inert HoldEnd exception are adapted for offline testing.
"""
from decimal import Decimal, ROUND_FLOOR
from maker_core.quoting.prices import _decimal as number, _levels
from maker_core.quoting.rewards import order_score, q_min, share_of, side_score
SIZE = Decimal('20')
SIZES = (20, 30, 50, 75)
class HoldEnd(Exception):
    pass

def observe(snapshot, prices, size=SIZE):
    """84b scoring: hold prices may drift; drift requests a re-quote, not exit.

Reuse the estimator formulas; do not invoke 80b's hold-only re-pricing gates.
True touch remains a separate submit safety check. Plain mid is sensitivity.
"""
    size = number(size)
    if size not in SIZES:
        raise HoldEnd('treatment_size')
    values = snapshot['quote_inputs']
    minimum, maximum, rate = (number(values[k]) for k in
        ('reward_min_size', 'reward_max_spread_cents', 'reward_rate_per_day'))
    if minimum > size:
        raise HoldEnd('reward_minimum')
    if minimum <= 0 or maximum <= 0 or rate < 40:
        raise HoldEnd('reward_rate_or_terms')
    sides = ('yes_bids', 'yes_asks', 'no_bids', 'no_asks')
    if any(not values[k] for k in sides):
        raise HoldEnd('one_sided_book')
    yb, ya, nb, na = [_levels(values[k]) for k in sides]
    for bids, asks in ((yb, ya), (nb, na)):
        if max(p for p, _ in bids) >= min(p for p, _ in asks):
            raise HoldEnd('crossed_book')
    qb, qa = ([p for p, s in levels if s >= minimum] for levels in (yb, ya))
    if not qb or not qa:
        raise HoldEnd('no_size_adjusted_midpoint')
    mid = (max(qb) + min(qa)) / 2
    plain = (max(p for p, _ in yb) + min(p for p, _ in ya)) / 2
    yes, no = map(number, prices)
    visible = all(sum(s for p, s in levels if p == price) >= size
                  for levels, price in ((yb, yes), (nb, no)))

    def shares(at):
        scores = []
        for levels, own_price in ((yb, yes), (ya, 1 - no)):
            aggregate = {}
            for p, s in levels:
                aggregate[p] = aggregate.get(p, Decimal(0)) + s
            aggregate[own_price] = max(Decimal(0), aggregate.get(own_price, Decimal(0)) - size)
            scores.append(side_score([(float(p), float(s)) for p, s in aggregate.items() if s > 0],
                                     float(at), float(maximum), float(minimum))[0])
        own = q_min(*(order_score(float(size), float(d), float(maximum), float(minimum))
                      for d in ((at - yes) * 100, (1 - at - no) * 100)), float(at))
        return share_of(own, sum(scores) / 2), share_of(own, q_min(*scores, float(at)))

    many, single = shares(mid)
    plain_many, _ = shares(plain)
    distances = [(mid - yes) * 100, (1 - mid - no) * 100]
    return {'adjusted_mid': str(mid), 'plain_mid': str(plain),
            'visible_two_sided': visible, 'share_many': many, 'share_single': single,
            'share_many_plain_mid': plain_many,
            'per_minute_many': float(rate) / 1440 * many,
            'per_minute_single': float(rate) / 1440 * single,
            'per_minute_many_plain_mid': float(rate) / 1440 * plain_many,
            'requote_legs': [i for i, d in enumerate(distances) if not 1 <= d <= 3]}

def replacement_price(mid, leg):
    value = number(mid) if leg == 0 else 1 - number(mid)
    return ((value - Decimal('.015')) / Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.01')
