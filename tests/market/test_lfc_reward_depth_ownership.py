"""Guards: F2 reward estimates subtract only outstanding own depth.

All books, orders and inventory in these tests are synthetic.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from weather.market.lfc_f2_controller import F2Band
from weather.market.lfc_pair_completion import OwnLot, inventory
from weather.market.lfc_pair_replay import RecordedBook, candidate
from weather.market.reward_quote import price_sized_reward_quote


def book(yes_size=20, no_size=20):
    def level(price, size):
        return [{'price': price, 'size': str(size)}]

    return {
        'token_ids': ['yes', 'no'],
        'rules': {'yes': {'tick_size': '.01', 'min_order_size': 5},
                  'no': {'tick_size': '.01', 'min_order_size': 5}},
        'quote_inputs': {
            'yes_bids': level('.48', yes_size), 'yes_asks': level('.52', no_size),
            'no_bids': level('.48', no_size), 'no_asks': level('.52', yes_size),
            'reward_min_size': 5, 'reward_max_spread_cents': 3,
            'reward_rate_per_day': 50, 'tick': '.01', 'post_only_available': True,
        },
    }


def policy(low='0'):
    return SimpleNamespace(raw={'share_many_range': [low, '1'], 'min_reward_rate': 0,
                                'min_book_depth': 20, 'leg_price_range': ['.17', '.80']})


def band_observation(snapshot, active, matched=None):
    band = F2Band.__new__(F2Band)
    band.active = active
    band.own_trades = SimpleNamespace(traded_shares=lambda: matched or {})
    band.prices = [Decimal('.48'), Decimal('.48')]
    band.size, band.SIZES = Decimal(20), (Decimal(20),)
    band.REQUOTE_WINDOW, band.TRADE_LEGS, band.MIN_REWARD_RATE = (1, 3), (0, 1), 0
    band.campaign_policy = policy()
    return band.observe_snapshot(snapshot)


def test_unposted_pair_matches_selection_on_the_same_public_book():
    snapshot = book()
    selection = price_sized_reward_quote(**snapshot['quote_inputs'], size=20)
    observation = band_observation(snapshot, {})
    assert selection.share_many == pytest.approx(.5)
    assert observation['share_many'] == pytest.approx(selection.share_many)
    assert observation['share_single'] == pytest.approx(selection.share_single)
    assert observation['visible_two_sided'] is False


def test_one_ack_only_removes_one_leg_and_mirrors_the_no_bid_once():
    snapshot = book(yes_size=20, no_size=40)
    active = {'no-ack': (1, Decimal('.48'))}
    assert band_observation(snapshot, active)['share_many'] == pytest.approx(.5)
    active['yes-ack'] = (0, Decimal('.48'))
    observation = band_observation(snapshot, active)
    assert observation['share_many'] == pytest.approx(2 / 3)
    assert observation['visible_two_sided'] is True


def test_partial_fill_removes_only_the_known_outstanding_quantity():
    active = {'yes-ack': (0, Decimal('.48'))}
    assert band_observation(book(yes_size=30), active, {'yes-ack': '10'})['share_many'] == pytest.approx(.5)


def test_a_smaller_displayed_level_cannot_establish_own_depth():
    snapshot = book(yes_size=15)
    # Qualifying external depth closer to the midpoint keeps the F2 depth gate
    # open. The adjusted midpoint stays at .50 on this symmetric book.
    snapshot['quote_inputs']['yes_bids'].append({'price': '.49', 'size': '5'})
    snapshot['quote_inputs']['yes_asks'].append({'price': '.51', 'size': '5'})
    assert band_observation(snapshot, {'yes-ack': (0, Decimal('.48'))})['share_many'] == (
        band_observation(snapshot, {})['share_many'])


def test_hypothetical_completion_uses_full_competing_depth_at_its_price():
    at = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)
    lot = OwnLot('trade', 'order', 'campaign', 'condition', 0, Decimal(20), Decimal('.48'), at)
    state = inventory([lot], campaign_id='campaign', condition_id='condition')
    recorded = RecordedBook(at, book(), 'synthetic')
    proposed = candidate(state, recorded, policy=policy('.30'), offset='.015')
    assert Decimal(proposed['capped_completion_price']) == Decimal('.48')
    # One hypothetical NO leg earns one third of a paired score. Against
    # equally sized real competitors on both sides its share is exactly 1/4.
    assert proposed['screen_refusal'] == 'share_many_outside_range'
    assert candidate(state, recorded, policy=policy('.249'), offset='.015')['screen_refusal'] is None
