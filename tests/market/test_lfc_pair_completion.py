"""Guards: T113 own-lot FIFO, complementary-only prices, dust and recovery.

All inputs are inert canonical-lot fixtures; no venue or live session is run.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from weather.market.lfc_pair_completion import (
    COMPLETE_PAIRS, CONTINUE, OwnLot, completion_seconds, effective_legs,
    inventory, mode, quote,
)
from weather.market.lfc_f2_breadth import PROTOCOL, daily_gate
from weather.market.lfc_capital import CapitalRefused


AT = datetime(2026, 11, 13, 19, 0, tzinfo=timezone.utc)


def lot(number, side, amount, cost, **changes):
    values = dict(trade_id=f't{number}', order_id=f'o{number}', campaign_id='campaign',
                  condition_id='condition', leg=side, shares=amount, price=cost,
                  at_utc=AT+timedelta(seconds=number))
    return OwnLot(**(values | changes))


def state(*lots):
    return inventory(lots, campaign_id='campaign', condition_id='condition')


def proposal(value, prices=('0.22', '0.76'), **changes):
    rules = dict(tick='0.01', leg_bounds=('0.17', '0.80'), reward_min_size='20')
    return quote(value, prices, **(rules | changes))


def test_austin_partial_complement_keeps_exact_residual_and_margin():
    value = state(lot(1, 0, '20', '.24'), lot(2, 1, '5', '.74'), lot(3, 1, '5', '.74'))
    assert value.u == 10 and value.unpaired_cost == D('2.40')
    assert value.average_cost == D('.24') and value.completion_leg == 1
    assert sum(p.shares for p in value.pairs) == 10
    assert sum(p.margin for p in value.pairs) == D('.20')
    result = proposal(value)
    assert result.pair_cap == D('.745') and result.price == D('.74')
    assert result.shares == 20 and result.allowed


def test_fifo_consumes_old_expensive_lot_before_new_cheap_one():
    value = state(lot(1, 0, 7, '.31'), lot(2, 0, 13, '.23'), lot(3, 1, 10, '.65'))
    assert value.u == 10 and value.unpaired_cost == D('2.30')
    assert [(p.shares, p.margin_per_share) for p in value.pairs] == [(D(7), D('.04')), (D(3), D('.12'))]
    assert value.residuals == ((lot(2, 0, 13, '.23'), D(10)),)
    assert proposal(value).pair_cap == D('.755')


def test_asymmetric_microfills_use_trade_precision_instead_of_position_truncation():
    value = state(lot(1, 0, '14.263889', '.28'), lot(2, 1, '3.440001', '.65'))
    assert value.u == D('10.823888')
    assert value.unpaired_cost == D('3.03068864')
    assert value.average_cost == D('.28')


@pytest.mark.parametrize('first_leg', [0, 1])
def test_twenty_share_over_completion_flips_symmetrically(first_leg):
    value = state(lot(1, first_leg, 5, '.30'), lot(2, 1-first_leg, 20, '.60'))
    assert value.u == (D('-15') if first_leg == 0 else D('15'))
    assert value.completion_leg == first_leg
    assert value.average_cost == D('.60') and value.flips == (('t2', 'o2'),)
    assert proposal(value, ('.7', '.7')).price == D('.38')
    assert sum(p.margin for p in value.pairs) == D('.5')


def test_full_completion_returns_cheap_arm_to_its_original_leg():
    original = (0,)
    first = lot(1, 0, 20, '.26')
    assert effective_legs(state(first), original, post_fill_mode=COMPLETE_PAIRS) == (1,)
    flat = state(first, lot(2, 1, 20, '.72'))
    assert not flat.completing and flat.u == 0 and flat.average_cost is None
    assert effective_legs(flat, original, post_fill_mode=COMPLETE_PAIRS) == original
    assert proposal(flat) is None


def test_miami_second_yes_is_never_an_allowed_new_leg():
    first = state(lot(1, 0, 20, '.26'))
    assert effective_legs(first, (0,), post_fill_mode=COMPLETE_PAIRS) == (1,)
    assert effective_legs(first, (0, 1), post_fill_mode=COMPLETE_PAIRS) == (1,)
    assert proposal(first).price == D('.72')


def test_continue_keeps_the_exact_original_arm_when_nonflat():
    value = state(lot(1, 1, 20, '.25'))
    assert effective_legs(value, (0, 1), post_fill_mode=CONTINUE) == (0, 1)
    assert effective_legs(value, (1,), post_fill_mode=CONTINUE) == (1,)


@pytest.mark.parametrize('shares,completing', [('0.000099', False), ('0.0001', False), ('0.000101', True)])
def test_dust_boundary_keeps_actual_residual_in_evidence(shares, completing):
    value = state(lot(1, 0, shares, '.24'))
    assert value.completing is completing
    assert value.evidence()['u'] == shares
    assert (proposal(value) is not None) is completing


def test_duplicate_own_trade_order_is_counted_once():
    first = lot(1, 0, 20, '.26')
    assert state(first, first).u == 20


def test_same_parent_trade_has_separate_own_order_allocations():
    first = lot(1, 0, 5, '.26')
    second = replace(first, order_id='second', shares=D(7))
    assert state(first, second).u == 12


@pytest.mark.parametrize('changes', [{'shares': D(21)}, {'price': D('.27')}, {'leg': 1}, {'at_utc': AT}])
def test_conflicting_duplicate_refuses(changes):
    first = lot(1, 0, 20, '.26')
    with pytest.raises(ValueError, match='completion_conflicting_fill'):
        state(first, replace(first, **changes))


def test_foreign_campaign_and_condition_holdings_cannot_complete_our_lots():
    value = state(lot(1, 0, 20, '.26'), lot(2, 1, 20, '.72', campaign_id='owner'),
                  lot(3, 1, 20, '.72', condition_id='different'))
    assert value.u == 20 and not value.pairs


def test_restart_reconstructs_nonzero_u_and_fifo_cost_across_sessions():
    first_session = [lot(1, 0, 20, '.26'), lot(2, 1, 5, '.72')]
    # New process receives the same immutable canonical lots, not a mode flag.
    recovered = inventory(tuple(first_session), campaign_id='campaign', condition_id='condition')
    assert recovered.u == 15 and recovered.average_cost == D('.26')
    assert effective_legs(recovered, (0,), post_fill_mode=COMPLETE_PAIRS) == (1,)
    assert proposal(recovered).price == D('.72')


@pytest.mark.parametrize('changes', [
    {'leg': True}, {'leg': 2}, {'shares': 0}, {'shares': '-1'}, {'price': 'NaN'},
    {'shares': 'Infinity'}, {'price': 1}, {'trade_id': ''}, {'order_id': None},
    {'at_utc': datetime(2026, 11, 13)},
])
def test_invalid_lot_fails_closed(changes):
    with pytest.raises((ValueError, TypeError)):
        lot(1, 0, 20, '.26', **changes)


def test_noncanonical_input_refuses():
    with pytest.raises(ValueError, match='completion_canonical_lot_required'):
        state({'size': 20, 'price': '.26'})


@pytest.mark.parametrize('normal,expected', [('.70', '.70'), ('.745', '.74'), ('.76', '.74')])
def test_normal_quote_is_only_lowered_and_always_tick_floored(normal, expected):
    result = proposal(state(lot(1, 0, 20, '.24')), ('.2', normal))
    assert result.price == D(expected)
    assert result.price <= result.uncapped_price and result.price <= result.pair_cap


def test_exact_tick_economic_cap_is_not_rounded_an_extra_tick():
    result = proposal(state(lot(1, 0, 20, '.245')))
    assert result.pair_cap == D('.740') and result.price == D('.74')


def test_cost_average_is_not_rounded_before_tick_floor():
    value = state(lot(1, 0, '1.000001', '.245'), lot(2, 0, '1', '.245001'))
    assert proposal(value).price == D('.73')


@pytest.mark.parametrize('cost,normal,changes,reason', [
    ('.82', '.76', {}, 'completion_leg_price_bounds'),
    ('.24', '.16', {}, 'completion_leg_price_bounds'),
    ('.10', '.81', {}, 'completion_leg_price_bounds'),
    ('.24', '.76', {'venue_bounds': ('.17', '.73')}, 'completion_venue_price_bounds'),
    ('.24', '.76', {'min_order_size': 21}, 'completion_venue_minimum'),
    ('.24', '.76', {'reward_min_size': '20.000001'}, 'completion_reward_minimum'),
])
def test_bound_and_minimum_refusal_preserves_diagnostic_price(cost, normal, changes, reason):
    result = proposal(state(lot(1, 0, 20, cost)), ('.2', normal), **changes)
    assert not result.allowed and result.refusal == reason
    assert result.evidence()['capped_completion_price'] == str(result.price)


def test_failed_price_bound_can_resume_on_a_later_normal_book():
    value = state(lot(1, 0, 20, '.24'))
    assert not proposal(value, ('.2', '.16')).allowed
    assert proposal(value, ('.2', '.73')).allowed


def test_cap_still_reserves_full_twenty_shares_and_cannot_shrink_to_fit():
    start = dict(protocol=PROTOCOL, market_id='austin', quote_day_utc='2026-11-13',
                 recorded_at_utc='2026-11-13T19:00:00+00:00', per_band_daily_filled_cap_pusd='30')
    value = state(lot(1, 0, 20, '.24'))
    result = proposal(value)
    reserve = result.shares * result.price
    leg = dict(status='terminal', size_matched='20', price='.24')
    ledger = SimpleNamespace(band_day_legs=lambda market, day: [(leg, False)])
    assert daily_gate(ledger, start, reserve=reserve)['remaining_native'] == 10400000
    leg.update(size_matched='64')  # 15.36 spent + 14.80 prospective > unchanged cap.
    with pytest.raises(CapitalRefused, match='per_band_daily_filled_cap'):
        daily_gate(ledger, start, reserve=reserve)
    assert result.shares == 20


def test_mixed_cost_fifo_slice_margins_are_reported_without_inventing_a_guarantee():
    value = state(lot(1, 0, 10, '.30'), lot(2, 0, 10, '.20'))
    assert proposal(value).price == D('.73')  # average-cost cap .735
    partial = state(lot(1, 0, 10, '.30'), lot(2, 0, 10, '.20'), lot(3, 1, 5, '.73'))
    assert partial.pairs[0].margin_per_share == D('-.03')
    assert partial.average_cost == D('3.50') / 15


def test_completion_duration_spans_restart_and_excludes_flat_periods():
    events = [(AT, True), (AT+timedelta(seconds=30), True),
              (AT+timedelta(seconds=100), False), (AT+timedelta(seconds=130), True)]
    assert completion_seconds(events, until=AT+timedelta(seconds=180)) == 150


@pytest.mark.parametrize('events,end', [
    ([(AT+timedelta(seconds=2), True), (AT, False)], AT+timedelta(seconds=3)),
    ([(AT, True)], AT-timedelta(seconds=1)), ([(AT, 1)], AT),
])
def test_completion_duration_refuses_invalid_clocks(events, end):
    with pytest.raises(ValueError, match='completion_interval'):
        completion_seconds(events, until=end)


@pytest.mark.parametrize('value', [None, '', True, 1, [], 'Complete_Pairs', 'retire'])
def test_only_two_exact_post_fill_modes_are_supported(value):
    with pytest.raises(ValueError, match='unsupported_post_fill_mode'):
        mode({'post_fill_mode': value})


def test_historical_mode_default_does_not_mutate_snapshot():
    raw = {'policy_revision': 5}
    assert mode(raw) == CONTINUE and raw == {'policy_revision': 5}
    assert mode({'post_fill_mode': COMPLETE_PAIRS}) == COMPLETE_PAIRS
