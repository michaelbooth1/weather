from dataclasses import asdict
from decimal import Decimal as D
import itertools
import pytest

from maker_core.quoting import rewards, prices
from weather.market import reward_share_estimate as original
from .fixtures import re1_reward_quote as legacy


@pytest.mark.parametrize("size,distance,spread,minimum", itertools.product(
    (None, 0, 19, 20, 30, 50, 75, 100), (None, -3, 0, 1, 1.5, 3, 5), (0, 1, 3, 5), (20, 100)))
def test_order_score_differential(size, distance, spread, minimum):
    assert rewards.order_score(size, distance, spread, minimum) == original.order_score(size, distance, spread, minimum)


def test_other_reward_kernels_grid():
    for one, two, mid in itertools.product((0, 1, 20, 100), (0, 1, 30, 100), (.09, .10, .5, .90, .91)):
        assert rewards.q_min(one, two, mid) == original.q_min(one, two, mid)
        assert rewards.share_of(one, two) == original.share_of(one, two)
        levels = [(mid - .01, one), (mid - .03, two)]
        assert rewards.side_score(levels, mid, 3, 20) == original.side_score(levels, mid, 3, 20)
    for tick, minimum, cutoff, bids, asks in itertools.product(
        (.01, .001), (20, 100), (True, False),
        ([], [(.49, 10), (.48, 100)], [(.6, 100)]),
        ([], [(.51, 10), (.52, 100)], [(.5, 100)])):
        kwargs = dict(tick=tick, min_size=minimum, max_spread_cents=3,
                      min_size_for_mid=cutoff, sizes=(20, 30, 50, 75), distances_cents=(1, 1.5, 3))
        assert rewards.evaluate_sample(bids, asks, **kwargs) == original.evaluate_sample(bids, asks, **kwargs)


@pytest.mark.parametrize("mid,size", itertools.product((.205, .3, .495, .5, .705, .795), (20, 30, 50, 75)))
def test_re1_price_differential(mid, size):
    bid = prices.outward(D(str(mid)) - D(".01"), D(".01"))
    ask = bid + D(".03")
    def level(price):
        return [{"price": str(price), "size": "100"}]
    kwargs = dict(yes_bids=level(bid), yes_asks=level(ask), no_bids=level(1 - ask), no_asks=level(1 - bid),
                  reward_min_size=20, reward_max_spread_cents=3, reward_rate_per_day=100,
                  tick=".01", post_only_available=True, per_order_ceiling=D(".8") * size,
                  per_band_ceiling=size, size=size)
    a = prices.price_sized_reward_quote(**kwargs)
    b = legacy.price_sized_reward_quote(**kwargs)
    assert asdict(a) == asdict(b)
    qualified = prices.qualified_mid(prices._levels(kwargs["yes_bids"]), prices._levels(kwargs["yes_asks"]), D(20))
    assert qualified == b.adjusted_mid
    assert prices.outward(qualified - D(".015"), D(".01")) == b.yes_buy
    assert prices.touch_buffer(b.yes_buy, prices._levels(kwargs["yes_asks"]), D(".01"))


@pytest.mark.parametrize("field,value", [("tick", ".001"), ("post_only_available", False),
                                         ("reward_min_size", 100), ("reward_rate_per_day", 39)])
def test_price_rejections_match(field, value):
    kwargs = dict(yes_bids=[{"price": ".49", "size": 100}], yes_asks=[{"price": ".51", "size": 100}],
                  no_bids=[{"price": ".49", "size": 100}], no_asks=[{"price": ".51", "size": 100}],
                  reward_min_size=20, reward_max_spread_cents=3, reward_rate_per_day=100, tick=".01",
                  post_only_available=True)
    kwargs[field] = value
    with pytest.raises(prices.QuoteRefused) as a:
        prices.price_reward_quote(**kwargs)
    with pytest.raises(legacy.QuoteRefused) as b:
        legacy.price_reward_quote(**kwargs)
    assert str(a.value) == str(b.value)
