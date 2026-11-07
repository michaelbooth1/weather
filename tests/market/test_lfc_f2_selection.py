"""F2's configured quote and one-per-city ranking, with synthetic public books.

Guards: B036 selection/token fields, strict monetary dominance and PLANNING-only rewards.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.market.test_lfc_pilot import Clock, snapshot
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_f2_selection import build_table, validate_table
from weather.market.market_registry import REGISTRY


NOW = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)


def universe():
    rows = []
    for index, city in enumerate(('denver', 'toronto')):
        snap = snapshot(Clock(NOW))
        cid, tokens = '0x' + str(index + 1) * 64, [str(100 + index * 2), str(101 + index * 2)]
        snap['condition_id'], snap['token_ids'] = cid, tokens
        snap['rules'] = {token: deepcopy(next(iter(snap['rules'].values()))) for token in tokens}
        rows.append({'market_id': city, 'market_timezone': REGISTRY[city].timezone,
                     'target_date': '2026-11-12', 'condition_id': cid, 'token_ids': tokens,
                     'event_condition_ids': [cid], 'event_slug': city + '-synthetic', 'snapshot': snap})
    return rows


def capital(cash='300'):
    return {'charged_native': 0, 'funding_native': 300_000_000, 'resting_reserve_native': 0,
            'segregated_profit_native': 0, 'segregated_incentives_native': 0, 'segregated_external_cash_native': 0}


def table(rows=None, row=None, cash='300', figures=None):
    return build_table(rows if rows is not None else universe(), now=NOW,
                       policy=parse_policy(row or example_policy()), cash=cash,
                       capital=figures or capital())


def test_two_city_pick_and_reproducible_planning_only_table():
    result = table()
    assert len(result['selected_condition_ids']) == 2
    assert len(validate_table(result, now=NOW, policy=parse_policy(example_policy()))) == 2
    assert result['planning_label'] == 'PLANNING' and result['prediction_booked_as_income'] is False


def test_one_per_city_with_ascending_condition_tie_and_no_substitute():
    rows = universe()
    extra = deepcopy(rows[0])
    extra['condition_id'] = '0x' + '0' * 64
    extra['snapshot']['condition_id'] = extra['condition_id']
    extra['event_condition_ids'] = [extra['condition_id']]
    rows.append(extra)
    result = table(rows)
    assert result['selected_condition_ids'][0] == extra['condition_id']
    assert len(result['selected_condition_ids']) == 2
    result = table(rows[:1])
    assert result['selected_condition_ids'] == [rows[0]['condition_id']]


def test_cash_admits_one_using_same_cross_city_rank():
    result = table(cash='20')
    assert len(result['selected_condition_ids']) == 1
    assert result['selected_condition_ids'] == result['ranked_conditions'][:1]
    result = table(cash='19.19')
    assert result['selected_condition_ids'] == []


@pytest.mark.parametrize('key,value', [('per_order_cap_pusd', '6.59'), ('per_band_cap_pusd', '19.19'),
                                     ('leg_price_range', ['.35', '.8']), ('market_ids', ['toronto']),
                                     ('local_event_dte', [2]), ('share_many_range', ['.6', '.7'])])
def test_each_configured_filter_changes_selection_instead_of_silent_fallback(key, value):
    row = example_policy()
    row[key] = value
    result = table(row=row)
    if key == 'market_ids':
        assert [r['market_id'] for r in result['rows'] if r['eligible']] == ['toronto']
    else:
        assert not result['selected_condition_ids']


def test_order_and_band_caps_dominate_point_eighty_price_ceiling():
    rows = universe()
    # .79 costs 15.80 and is inside the leg range. A stricter configured
    # monetary cap must dominate that permitted price.
    for source in rows:
        inputs = source['snapshot']['quote_inputs']
        inputs['yes_bids'] = [{'price': '.79', 'size': '100'}]
        inputs['yes_asks'] = [{'price': '.81', 'size': '100'}]
        inputs['no_bids'] = [{'price': '.19', 'size': '100'}]
        inputs['no_asks'] = [{'price': '.21', 'size': '100'}]
    row = example_policy()
    row['quote_offset_pusd'], row['requote_distance_cents'] = '.005', ['.5', '2']
    row['per_order_cap_pusd'] = '15.79'
    result = table(rows, row=row)
    assert not result['selected_condition_ids']
    assert all(source['refusal'] == 'capital_ceiling_exceeded' for source in result['rows'])


@pytest.mark.parametrize('offset,window', [('.015', ['1', '3']), ('.025', ['2', '4'])])
def test_adaptive_quote_distance_is_used_by_the_actual_proposer(offset, window):
    row = example_policy()
    row.update(quote_offset_pusd=offset, requote_distance_cents=window, policy_revision=2)
    rows = universe()
    for source in rows:
        inputs = source['snapshot']['quote_inputs']
        inputs['reward_max_spread_cents'] = '6'
        for key in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
            inputs[key][0]['size'], inputs[key][1]['size'] = '25', '50'
    result = table(rows, row=row)
    assert result['selected_condition_ids'], result['rows'][0]['refusal']
    price = Decimal(result['rows'][0]['quote']['yes_buy'])
    assert price == (Decimal('.33') if offset == '.015' else Decimal('.32'))


def test_requote_distance_outside_window_refuses_before_any_order():
    row = example_policy()
    row['requote_distance_cents'] = ['3', '4']
    result = table(row=row)
    assert not result['selected_condition_ids']


def test_current_horizon_is_rechecked_after_the_retained_table_crosses_midnight():
    result = table()
    tomorrow = datetime(2026, 11, 12, 5, tzinfo=timezone.utc)
    # Retained-table age also refuses; the per-order check independently covers
    # a long session after the initial fresh table was admitted.
    with pytest.raises(ValueError):
        validate_table(result, now=tomorrow, policy=parse_policy(example_policy()))
