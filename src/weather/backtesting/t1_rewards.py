"""Venue Q_min on unique native orders, or an explicit anonymous-book lower bound.

Displayed complementary levels are not independent orders. Exact mode requires
a complete unique native-order census, reconciled to both displayed books.
Public L2 mode uses sum(side scores)/2 >= sum(maker Q_min) as a denominator
upper bound; duplicated mirror levels only make that estimate more conservative.
"""
from collections import defaultdict
from decimal import Decimal as D

from maker_core.quoting.book import compose_book
from maker_core.quoting.policy import Book, QuoteLeg

from weather.backtesting.t1_types import ONE, ZERO, decimal_context, levels, number, utc


def order_score(size, distance, spread, minimum):
    if size < minimum or distance >= spread:
        return ZERO
    return size * ((spread - distance) / spread) ** 2


def q_min(one, two, mid):
    both = min(one, two)
    return max(both, max(one, two) / D(3)) if D('.10') <= mid <= D('.90') else both


def level_map(book, outcome, side):
    out = defaultdict(lambda: ZERO)
    for row in levels(book[outcome][side]):
        out[row['price']] += row['size']
    return dict(out)


def native_competitor_score(book, mid, spread, minimum):
    if book.get('reward_orders_complete') is not True or 'reward_orders' not in book:
        raise ValueError('exact rewards require a complete native-order census')
    grouped, seen = defaultdict(lambda: [ZERO, ZERO]), set()
    reconstructed = {(outcome, side): defaultdict(lambda: ZERO)
                     for outcome in ('YES', 'NO') for side in ('bids', 'asks')}
    for order in book['reward_orders']:
        oid, maker = order.get('order_id'), order.get('maker_id')
        outcome, side = order['outcome'], order['side']
        if not oid or oid in seen or not maker or outcome not in ('YES', 'NO') or side not in ('BUY', 'SELL'):
            raise ValueError('invalid or anonymous native reward order')
        seen.add(oid)
        p, size = number(order['price'], maximum=ONE), number(order['size'])
        if not ZERO < p < ONE or size <= ZERO:
            raise ValueError('invalid native reward price or size')
        index = 0 if (outcome, side) in (('YES', 'BUY'), ('NO', 'SELL')) else 1
        yes_price = p if outcome == 'YES' else ONE - p
        grouped[maker][index] += order_score(size, abs(yes_price - mid) * 100, spread, minimum)
        native_side, mirror_side = ('bids', 'asks') if side == 'BUY' else ('asks', 'bids')
        complement = 'NO' if outcome == 'YES' else 'YES'
        reconstructed[(outcome, native_side)][p] += size
        reconstructed[(complement, mirror_side)][ONE - p] += size
    for (outcome, side), expected in reconstructed.items():
        if dict(expected) != level_map(book, outcome, side):
            raise ValueError('native reward census differs from captured book')
    return sum((q_min(*scores, mid) for scores in grouped.values()), ZERO)


@decimal_context
def qualified_price(rows, minimum, *, bids, semantics):
    if semantics not in ('level_filter', 'cumulative_depth'):
        raise ValueError('unknown qualified midpoint semantics')
    ordered = sorted(rows, reverse=bids)
    total = ZERO
    for price, size in ordered:
        total += size
        if (size if semantics == 'level_filter' else total) >= minimum:
            return price
    return None


@decimal_context
def reward_share(book, resting, terms, rule, midpoint_rule='level_filter'):
    minimum, spread = number(terms['min_size']), number(terms['max_spread_cents'])
    if minimum <= ZERO or spread <= ZERO:
        raise ValueError('invalid captured reward terms')
    public = Book(utc(book['at']), tuple(level_map(book, 'YES', 'bids').items()),
                  tuple(level_map(book, 'YES', 'asks').items()), tuple(level_map(book, 'NO', 'bids').items()),
                  tuple(level_map(book, 'NO', 'asks').items()))
    display = compose_book(public, tuple(QuoteLeg(r['outcome'], r['price'], r['remaining']) for r in resting))
    bid = qualified_price(display.yes_bids, minimum, bids=True, semantics=midpoint_rule)
    ask = qualified_price(display.yes_asks, minimum, bids=False, semantics=midpoint_rule)
    if bid is None or ask is None or bid >= ask:
        raise ValueError('no qualified midpoint')
    mid = (bid + ask) / 2
    own = [ZERO, ZERO]
    for order in resting:
        p = order['price'] if order['outcome'] == 'YES' else ONE - order['price']
        own[0 if order['outcome'] == 'YES' else 1] += order_score(
            order['remaining'], abs(p - mid) * 100, spread, minimum)
    if rule == 'maker_grouped':
        competing = native_competitor_score(book, mid, spread, minimum)
    elif rule == 'aggregate_upper_bound':
        total = ZERO
        for outcome in ('YES', 'NO'):
            for side in ('bids', 'asks'):
                for price, size in level_map(book, outcome, side).items():
                    p = price if outcome == 'YES' else ONE - price
                    total += order_score(size, abs(p - mid) * 100, spread, minimum)
        competing = total / 2
    else:
        raise ValueError('unknown competition rule')
    own_q = q_min(*own, mid)
    return ZERO if own_q <= ZERO else own_q / (own_q + competing)
