"""Decimal venue reward scoring, including complementary books and own midpoint impact.

Grouped orders permit exact Q_min aggregation. Anonymous L2 supports only an
explicit denominator upper bound: sum of both sides' scores >= sum Q_min.
The latter is a conservative reward estimate, never an exact maker share.
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


@decimal_context
def reward_share(book, resting, terms, rule):
    """Expected random-minute sample share, for this captured condition only.

    Book excludes our orders; adapter must remove them for actual pilot replay.
    An own YES bid also contributes a NO ask to the displayed midpoint book.
    Both outcome books remain distinct venue books; no inferred execution asks.
    """
    minimum = number(terms['min_size'])
    spread = number(terms['max_spread_cents'])
    if minimum <= ZERO or spread <= ZERO:
        raise ValueError('invalid captured reward terms')
    def merged(outcome, side):
        sizes = defaultdict(lambda: ZERO)
        for row in levels(book[outcome][side]):
            sizes[row['price']] += row['size']
        return tuple(sorted(sizes.items()))

    public = Book(utc(book['at']), merged('YES', 'bids'), merged('YES', 'asks'),
                  merged('NO', 'bids'), merged('NO', 'asks'))
    display = compose_book(public, tuple(QuoteLeg(r['outcome'], r['price'], r['remaining']) for r in resting))
    bids = [p for p, s in display.yes_bids if s >= minimum]
    asks = [p for p, s in display.yes_asks if s >= minimum]
    if not bids or not asks or max(bids) >= min(asks):
        raise ValueError('no qualified midpoint')
    mid = (max(bids) + min(asks)) / D(2)
    own = [ZERO, ZERO]
    for order in resting:
        p = order['price'] if order['outcome'] == 'YES' else ONE - order['price']
        # Venue side equations include a native bid and its complement ask.
        # Score own displayed legs on the same four-book basis as competitors.
        own[0 if order['outcome'] == 'YES' else 1] += D(2) * order_score(
            order['remaining'], abs(p - mid) * 100, spread, minimum)
    grouped = defaultdict(lambda: [ZERO, ZERO])
    for outcome in ('YES', 'NO'):
        for side in ('bids', 'asks'):
            index = 0 if (outcome, side) in (('YES', 'bids'), ('NO', 'asks')) else 1
            for row in levels(book[outcome][side]):
                if rule == 'maker_grouped' and not row.get('maker_id'):
                    raise ValueError('anonymous competition cannot be exact')
                key = row.get('maker_id', 'anonymous')
                p = row['price'] if outcome == 'YES' else ONE - row['price']
                grouped[key][index] += order_score(row['size'], abs(p - mid) * 100, spread, minimum)
    competing = (sum((q_min(*scores, mid) for scores in grouped.values()), ZERO)
                 if rule == 'maker_grouped' else sum((sum(s, ZERO) for s in grouped.values()), ZERO))
    own_q = q_min(*own, mid)
    return ZERO if own_q <= ZERO else own_q / (own_q + competing)
