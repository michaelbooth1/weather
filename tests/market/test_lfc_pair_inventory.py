"""Guards: T113 consumes canonical K6 money states, exact lots and removals."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from weather.market.lfc_pair_inventory import fill_time, held_inventory


def inputs():
    legs = {'o1': {'intent_key': 's1:1', 'condition_id': 'c', 'token_id': 'yes',
                   'price': '.26', 'size_matched': '20', 'status': 'terminal'},
            'o2': {'intent_key': 's2:1', 'condition_id': 'c', 'token_id': 'no',
                   'price': '.72', 'size_matched': '5.000001', 'status': 'terminal'}}
    held = {'s1:1': {'condition_id': 'c', 'token_id': 'yes', 'remaining_quantity': '20'},
            's2:1': {'condition_id': 'c', 'token_id': 'no', 'remaining_quantity': '5.000001'}}
    records = [{'trade_id': 't'+oid, 'own_order_id': oid, 'identity_basis': 'venue_trade_id',
        'condition_id': 'c', 'token_id': leg['token_id'], 'side': 'BUY', 'liquidity_role': 'MAKER',
        'price': leg['price'], 'shares': leg['size_matched'], 'status': 'CONFIRMED',
        'state': 'confirmed', 'final': True, 'money_counted': True,
        'exchange_match_time': '2026-11-13T20:00:0'+str(index)+'Z',
        'provenance': [{'source': 'rest', 'status': 'CONFIRMED'}]} for index, (oid, leg) in enumerate(legs.items())]
    return records, legs, held


def project(records, legs, held):
    return held_inventory(records, legs, held, campaign_id='campaign', condition_id='c', tokens=('yes', 'no'))


def test_canonical_trade_precision_and_cross_session_own_lots():
    value = project(*inputs())
    assert str(value.u) == '14.999999'
    assert str(value.average_cost) == '0.26'
    assert str(value.pairs[0].shares) == '5.000001'


def test_native_rounded_venue_price_keeps_canonical_cost_without_position_rounding():
    records, legs, held = inputs()
    records[0]['price'] = '0.260000000001'
    # This increase crosses a native ceiling boundary and must refuse.
    with pytest.raises(ValueError, match='completion_projection_binding'):
        project(records, legs, held)
    records[0]['price'] = '0.2800000056085686'
    records[0]['shares'] = legs['o1']['size_matched'] = held['s1:1']['remaining_quantity'] = '14.263889'
    legs['o1']['price'] = '.28'
    value = project(records, legs, held)
    assert value.average_cost == D('0.2800000056085686')


@pytest.mark.parametrize('status', ['MATCHED', 'MINED', 'RETRYING'])
def test_provisional_money_counted_fills_preserve_k6_money_rule(status):
    records, legs, held = inputs()
    records[0].update(status=status, state='provisional', final=False)
    assert project(records, legs, held).yes_shares == 20


def test_failed_execution_never_creates_inventory():
    records, legs, held = inputs()
    failed = deepcopy(records[0])
    failed.update(trade_id='failed', status='FAILED', state='failed', final=True, money_counted=False)
    assert project(records+[failed], legs, held) == project(records, legs, held)


def test_provisional_to_final_does_not_double_count():
    records, legs, held = inputs()
    records[0].update(status='MINED', state='provisional', final=False)
    before = project(records, legs, held)
    records[0].update(status='CONFIRMED', state='confirmed', final=True)
    assert project(records, legs, held) == before


def test_duplicate_rows_must_be_canonicalized_before_inventory():
    records, legs, held = inputs()
    with pytest.raises(ValueError, match='completion_projection_not_canonical'):
        project(records+[deepcopy(records[0])], legs, held)


def test_evidenced_removal_changes_held_inventory_without_cash_inference():
    records, legs, held = inputs()
    held['s1:1']['remaining_quantity'] = '10'
    value = project(records, legs, held)
    assert str(value.u) == '4.999999'
    held['s1:1']['remaining_quantity'] = '0'
    assert str(project(records, legs, held).u) == '-5.000001'


@pytest.mark.parametrize('change', [
    {'price': '.27'}, {'token_id': 'foreign'}, {'side': 'SELL'}, {'liquidity_role': 'TAKER'},
    {'condition_id': 'foreign'}, {'identity_basis': 'legacy_content_sha256'}, {'provenance': []},
    {'money_counted': False}, {'final': 1}, {'exchange_match_time': None},
])
def test_canonical_identity_and_lifecycle_mismatch_refuses(change):
    records, legs, held = inputs()
    records[0].update(change)
    with pytest.raises(ValueError, match='completion_'):
        project(records, legs, held)


@pytest.mark.parametrize('quantity', ['19.9999', '20.000001'])
def test_terminal_coverage_is_exact_not_position_precision(quantity):
    records, legs, held = inputs()
    legs['o1']['size_matched'] = quantity
    with pytest.raises(ValueError, match='completion_terminal_fill_coverage'):
        project(records, legs, held)


def test_still_open_filled_order_is_not_a_terminal_lot():
    records, legs, held = inputs()
    legs['o1']['status'] = 'live'
    with pytest.raises(ValueError, match='completion_terminal_fill_coverage'):
        project(records, legs, held)


def test_absent_or_increased_held_lot_refuses():
    records, legs, held = inputs()
    del held['s1:1']
    with pytest.raises(ValueError, match='completion_held_lot_binding'):
        project(records, legs, held)
    records, legs, held = inputs()
    held['s1:1']['remaining_quantity'] = '20.000001'
    with pytest.raises(ValueError, match='completion_held_lot_quantity'):
        project(records, legs, held)


def test_match_clock_accepts_retained_iso_and_epoch_without_read_time_substitution():
    assert fill_time('1794600000') == fill_time(1794600000)
    assert fill_time('2026-11-13T20:00:00Z').year == 2026
    for value in (None, True, 'bad', 'NaN'):
        with pytest.raises(ValueError, match='completion_fill_time_unproven'):
            fill_time(value)
