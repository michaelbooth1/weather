"""Guards: T114 outward W pricing, open entry and inclusive resting corridor."""
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json

import pytest

from tests.market.test_reward_quote import inputs
from weather.market.lfc_wide_quote import entry_allowed, order_evidence, price_quote, requote_legs
from weather.market.reward_quote import QuoteRefused, price_sized_reward_quote


def proposal_bytes(quote):
    return json.dumps(asdict(quote), default=str, sort_keys=True, separators=(',', ':')).encode()


# Generated from reward_quote.py at d086209afceda82d43b1925018e7bc60e2414adf,
# using synthetic cent-lattice books; includes exact serialized refusals.
@pytest.mark.parametrize('legs,offset,golden', [
    ((0,), '.015', 'be54f382d1536c79366e4414e787a24908f0ee64a4900708d24c78e2db18314a'),
    ((0,), '.025', '541227a7837ed6ac481d507a7e4c629c1dfc792a896532954b0bf004dc1afc19'),
    ((1,), '.015', '360d3faccbf1b2871877fcb6ed5b2b3fccb2a2714bc4d9646489507054019a2d'),
    ((1,), '.025', 'f05cdb39d850aaa26528f53c65b572f150eb29bc80ed38b1728ce57ad6ab9c17'),
    ((0, 1), '.015', '22021b4375ddc8cbfcd8b4db6359b522950cb6cdbe64e1bb37487469714dabfb'),
    ((0, 1), '.025', '6467ffab24fc67bab28c74ccdc8e714d51db471417084e0c3482d47d0270836e')])
def test_standard_proposals_keep_exact_original_serialization(legs, offset, golden):
    hasher = hashlib.sha256()
    for bid in range(20, 78):
        for spread in range(1, 7):
            values = dict(inputs(str(Decimal(bid)/100), str(Decimal(bid+spread)/100)),
                          size='20', quote_offset=offset, trade_legs=legs,
                          per_order_ceiling='15.80', per_band_ceiling='19.60')
            try:
                old = price_sized_reward_quote(**values)
            except QuoteRefused as exc:
                with pytest.raises(QuoteRefused, match=str(exc)):
                    price_quote(**values)
                result = {'refusal': str(exc)}
            else:
                assert proposal_bytes(price_quote(**values)) == proposal_bytes(old)
                assert proposal_bytes(price_quote(**values, quote_offset_mode='standard')) == proposal_bytes(old)
                result = asdict(price_quote(**values))
            hasher.update(json.dumps(result, default=str, sort_keys=True, separators=(',', ':')).encode()+b'\n')
    assert hasher.hexdigest() == golden


@pytest.mark.parametrize('bid,ask,prices,distances', [
    ('.34', '.36', ('.32', '.62'), ('3', '3')),
    ('.34', '.35', ('.31', '.62'), ('3.5', '3.5'))])
def test_wide_rounds_each_native_leg_outward(bid, ask, prices, distances):
    quote = price_quote(**inputs(bid, ask), size=20, quote_offset_mode='wide')
    assert (quote.yes_buy, quote.no_buy) == tuple(map(Decimal, prices))
    for leg, price in enumerate(prices):
        evidence = order_evidence(mid=quote.adjusted_mid, leg=leg, price=price, size=20,
                                  minimum=20, maximum='4.5', mode='wide', offset='.030')
        assert Decimal(evidence['scoring_distance_cents']) == Decimal(distances[leg])
        assert evidence['native_leg_reward_score'] == pytest.approx(20*((4.5-float(distances[leg]))/4.5)**2)


def test_entry_boundary_wait_is_distinct_from_resting_inclusive_band():
    prices = (Decimal('.30'), Decimal('.61'))
    assert entry_allowed('.345', prices, (0,), '4.5') is False
    assert entry_allowed('.345', prices, (0,), '6') is False
    assert requote_legs('.345', prices, (0, 1)) == []
    assert requote_legs('.3501', prices, (0, 1)) == [0]
    assert requote_legs('.3249', prices, (0,)) == [0]
    assert entry_allowed('.3449', prices, (0,), '4.5') is True


def test_reward_boundary_waits_after_tick_rounding():
    # 3c requested, 3.5c actual. Never post a normal zero-score leg.
    with pytest.raises(QuoteRefused, match='outside_leave_alone_window'):
        price_quote(**{**inputs(), 'reward_max_spread_cents': '3.5'}, size=20, quote_offset_mode='wide')
    assert not entry_allowed('.345', ('.30', '.61'), (0, 1), '4.5')


@pytest.mark.parametrize('change,reason', [({'per_order_ceiling': '1'}, 'capital_ceiling'),
    ({'per_band_ceiling': '1'}, 'capital_ceiling'), ({'size': 21}, 'treatment_size'),
    ({'tick': '.005'}, 'unsupported_tick'), ({'post_only_available': False}, 'post_only')])
def test_wide_keeps_proposal_screens_and_caps(change, reason):
    with pytest.raises(QuoteRefused, match=reason):
        price_quote(**{**inputs(), 'size': 20, **change}, quote_offset_mode='wide')


def test_complement_outside_spread_records_zero_native_score():
    evidence = order_evidence(mid='.345', leg=1, price='.50', size=20, minimum=20,
                              maximum='4.5', mode='wide', offset='.030')
    assert evidence['scoring_distance_cents'] == '15.500'
    assert evidence['native_leg_reward_score'] == 0
