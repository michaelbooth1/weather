"""Guards: new ordinary Pin B quotes must satisfy the fresh distance rule.

Synthetic books only. The sentinel ends the test before monetary authority.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from weather.market.lfc_f2_controller import F2Band
from weather.market.lfc_f2_pinb import SCHEMA
from weather.market.lfc_pair_completion import OwnLot, inventory
from weather.market.mm_stage2_hold import HoldEnd
from weather.market.re1_attended import HOST, Session


D = Decimal
AT = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)


def book(yes_bid='.50', yes_ask='.54', width='3'):
    def level(price):
        return [{'price': str(price), 'size': '100'}]

    terms = {'yes_bids': level(yes_bid), 'yes_asks': level(yes_ask),
             'no_bids': level(1 - D(yes_ask)), 'no_asks': level(1 - D(yes_bid)),
             'reward_min_size': '20', 'reward_max_spread_cents': width, 'reward_rate_per_day': '50'}
    rule = {'tick_size': '.01', 'min_order_size': '5', 'fee_rate_bps': '0'}
    return {'condition_id': 'band', 'token_ids': ['yes', 'no'], 'observed_at_utc': AT.isoformat(),
            'quote_inputs': terms, 'rules': {'yes': rule, 'no': rule}}


def band_for(fresh, prices=('.48', '.48'), legs=(0, 1), *, schema=SCHEMA, completion=False, lots=()):
    band = F2Band.__new__(F2Band)
    band.mode, band.condition, band.tokens = 'rehearse', 'band', ('yes', 'no')
    band.venue = SimpleNamespace(host=HOST, maker='simulated', open_orders=lambda: [])
    band.public = SimpleNamespace(snapshot=lambda *args, **kwargs: fresh)
    band.clock = SimpleNamespace(now=lambda: AT, monotonic=lambda: 0)
    band.journal = SimpleNamespace(record=lambda *args, **kwargs: None)
    band.required = lambda name, function, **kwargs: function()
    band.control = lambda **kwargs: None
    band.start_allowed = lambda now: True
    band.start, band.end, band.planned_seconds = AT, AT + timedelta(hours=1), 3600
    band.submits, band.requotes, band.active = 0, 0, {}
    band.size, band.SIZES, band.sized = D(20), (D(20),), True
    band.order_cap, band.band_cap, band.BAND_CEILING = D('15.80'), D('19.60'), D('19.60')
    band.prices, band.TRADE_LEGS, band.LEG_PRICE_RANGE = list(map(D, prices)), legs, (D('.17'), D('.80'))
    band.REQUOTE_WINDOW, band.MIN_REWARD_RATE, band.OFFSET = (D(1), D(3)), D(0), D('.015')
    band.campaign_policy = SimpleNamespace(raw={'schema_version': schema, 'min_reward_rate': '0',
        'min_book_depth': '20', 'share_many_range': ['0', '1'],
        'post_fill_mode': 'complete_pairs' if completion else 'continue'})
    band.pair_state = inventory(lots, campaign_id='campaign', condition_id='band')
    band.pair_since, band.pair_elapsed = None, D(0)
    band.observe_eligibility = lambda *args: None
    return band


class ReachedAuthorization(Exception):
    pass


def stop_before_authority(*args):
    raise ReachedAuthorization


@pytest.mark.parametrize('leg,completion', [(0, False), (1, False), (0, True), (1, True)])
def test_pending_stale_leg_never_reaches_authorization(leg, completion):
    # Stale .48/.48 paired prices were valid at mid .50. New mid .52 makes
    # YES 4c outward and NO exactly at mid, despite both still passing the ask.
    band = band_for(book(), completion=completion)
    band.authorize_post = stop_before_authority
    with pytest.raises(HoldEnd) as halted:
        Session.submit(band, leg, band.prices[leg])
    assert halted.value.reason == 'outside_leave_alone_window'
    assert band.prices == [D('.48'), D('.48')]
    assert band.submits == 0


@pytest.mark.parametrize('price,width,accepted', [
    ('.51', '3', True), ('.49', '4', True), ('.49', '3', False),
])
def test_selected_cheap_leg_keeps_inclusive_window_and_strict_reward_boundary(price, width, accepted):
    fresh = book(width=width)
    band = band_for(fresh, (price, '.48'), (0,))
    band.authorize_post = stop_before_authority
    if accepted:
        with pytest.raises(ReachedAuthorization):
            Session.submit(band, 0, D(price))
    else:
        with pytest.raises(HoldEnd) as halted:
            Session.submit(band, 0, D(price))
        assert halted.value.reason == 'outside_leave_alone_window'
    assert band.submits == 0


def test_pending_in_range_leg_can_go_despite_other_legs_distance_signal():
    fresh = book()
    band = band_for(fresh, ('.50', '.48'))
    band.active = {'already-resting': (1, D('.48'))}
    # Compatible with the independent active-depth estimator patch.
    band.own_trades = SimpleNamespace(traded_shares=lambda: {})
    band.check_pending_quote(fresh, 0, D('.50'))
    assert band.active == {'already-resting': (1, D('.48'))}
    assert band.prices == [D('.50'), D('.48')]


def test_capped_nonflat_complement_retains_its_wider_ordinary_distance():
    fresh = book('.48', '.52')
    lot = OwnLot('t', 'o', 'campaign', 'band', 0, D(20), D('.56'), AT)
    band = band_for(fresh, ('.48', '.42'), (1,), completion=True, lots=[lot])
    band.check_pending_quote(fresh, 1, D('.42'))
    assert band.pair_last_quote.allowed
    assert band.pair_last_quote.price == D('.42')


def test_historical_f2_schema_keeps_its_previous_observation_behavior():
    fresh = book()
    band = band_for(fresh, schema='lfc_campaign_policy_v0.3')
    band.check_pending_quote(fresh, 0, D('.48'))
