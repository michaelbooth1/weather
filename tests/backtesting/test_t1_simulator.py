"""Guards: edge trial charter section 2, EF 10m/10o; synthetic event dates <= 2026-10-14."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D, localcontext
from datetime import timedelta

import pytest

from tests.backtesting.t1_fixtures import at, book, config, payload
from weather.backtesting.t1_rewards import order_score, q_min, reward_share
from weather.backtesting.t1_simulator import market_centred_quote, replay
from weather.backtesting.t1_types import fee
from weather.backtesting.t1_types import utc


def test_queue_partial_fill_rebate_settlement_and_stress_arithmetic():
    result = replay(payload(), config())
    assert [f['size'] for f in result['fills']] == [D(5), D(5)]
    assert [f['at'].isoformat() for f in result['fills']] == [at(4), at(5)]
    assert result['cost'] == D('4.90')
    assert result['venue_payout'] == 10
    assert result['spread_capture_pusd'] == D('.10')
    assert result['inventory_move_pusd'] == D('5.00')
    assert result['maker_fees_pusd'] == 0
    assert result['rebate_accrued'] == D('.0312375')
    assert result['reward_accrued'] == pytest.approx(D(20) / 7 + D(10) / 13)
    assert result['rebate_payable'] == 0
    assert result['informed_stress_cost'] == D('3.675')
    assert result['stressed_net_pnl'] == result['raw_net_pnl'] - D('3.675')
    assert [f['markout_per_share'] for f in result['fills']] == [D('-.03')] * 2
    assert result['reasons'] == []
    assert result['trial_can_pass'] is False
    assert replay(payload(), config()) == result


def test_venue_scoring_uses_complements_and_per_maker_groups():
    b = book()
    own = [{'outcome': 'YES', 'price': D('.49'), 'remaining': D(20)},
           {'outcome': 'NO', 'price': D('.49'), 'remaining': D(20)}]
    terms = {'min_size': '20', 'max_spread_cents': '3'}
    assert reward_share(b, own, terms, 'maker_grouped') == D('.5')
    assert abs(reward_share(b, own, terms, 'aggregate_upper_bound') - D(1) / 3) < D('1e-25')
    for order in b['reward_orders']:
        order.pop('maker_id')
    with pytest.raises(ValueError, match='anonymous'):
        reward_share(b, own, terms, 'maker_grouped')
    assert abs(reward_share(b, own, terms, 'aggregate_upper_bound') - D(1) / 3) < D('1e-25')
    assert order_score(D(19), D(1), D(3), D(20)) == 0
    assert order_score(D(20), D(3), D(3), D(20)) == 0
    assert q_min(D(9), D(0), D('.1')) == 3
    assert q_min(D(9), D(0), D('.099')) == 0


def test_reward_competition_updates_and_minimum_change():
    p = payload()
    busy = book(3, size='2000')
    p['events'].append(busy)
    assert replay(p, config())['reward_accrued'] < replay(payload(), config())['reward_accrued']
    p = payload()
    new_terms = {**p['events'][1], 'at': at(3), 'min_size': '100'}
    p['events'].append(new_terms)
    assert replay(p, config())['reward_accrued'] < replay(payload(), config())['reward_accrued']


@pytest.mark.parametrize('trade_changes,expected', [
    ({'size': '20'}, [D(5)]), ({'aggressor': 'BUY'}, []), ({'price': '.49'}, [D(5)]),
])
def test_queue_and_aggressor_boundaries(trade_changes, expected):
    p = payload()
    p['events'][2].update(trade_changes)
    result = replay(p, config())
    assert [f['size'] for f in result['fills']] == expected


def test_at_price_sensitivity_still_requires_back_queue():
    p = payload()
    p['events'][2]['price'] = '.49'
    assert [r['size'] for r in replay(p, config(queue_rule='back_at_price'))['fills']] == [D(5), D(5)]


def test_trade_duplicates_do_not_duplicate_fills_and_conflicts_refuse():
    p = payload()
    p['events'].append(deepcopy(p['events'][2]))
    assert len(replay(p, config())['fills']) == 2
    p['events'][-1]['at'] = at(6)  # same execution retransmitted later
    assert len(replay(p, config())['fills']) == 2
    p['events'][-1]['size'] = '30'
    with pytest.raises(ValueError, match='conflicting duplicate'):
        replay(p, config())


def test_delayed_trade_receipt_does_not_fill_orders_placed_after_execution():
    p = payload()
    p['events'][2].update(traded_at=at(1), at=at(4))
    assert replay(p, config())['fills'] == []


def test_arrival_book_changes_post_only_result_and_later_latency():
    p = payload()
    p['events'].append(book(1, '.47', '.49'))
    result = replay(p, config())
    assert result['fills'] == []
    assert result['rejected'] == [{'id': 'o1', 'reason': 'post_only_cross'}]
    with pytest.raises(ValueError, match='latency'):
        config(latency_seconds='1')
    p = payload()
    p['commands'][0]['arrival_at'] = at(1)
    with pytest.raises(ValueError, match='latency'):
        replay(p, config())


def test_market_and_total_capital_bind_resting_and_inventory():
    p = payload()
    p['commands'].append({**p['commands'][0], 'id': 'o2', 'observed_at': at(3), 'decided_at': at(3)})
    result = replay(p, config(per_market_cap='5'))
    assert result['rejected'] == [{'id': 'o2', 'reason': 'capital_cap'}]
    result = replay(p, config(per_market_cap='5', total_cap='5'))
    assert result['rejected'][0]['reason'] == 'capital_cap'


def test_two_own_orders_do_not_reuse_public_volume():
    p = payload()
    p['commands'].append({**p['commands'][0], 'id': 'o2'})
    result = replay(p, config())
    assert sum((r['size'] for r in result['fills']), D(0)) == 10
    assert {r['order_id'] for r in result['fills']} == {'o1'}
    assert result['rejected'] == [{'id': 'o2', 'reason': 'one_order_per_outcome'}]


def test_cancel_race_trade_first_and_cancel_releases_only_unfilled_reserve():
    p = payload()
    p['commands'].append({'kind': 'cancel', 'id': 'o1', 'observed_at': at(2), 'decided_at': at(2)})
    result = replay(p, config())
    assert [r['size'] for r in result['fills']] == [D(5)]


def test_stale_terms_gap_and_missing_pool_are_incomplete():
    result = replay(payload(), config(max_book_age_seconds='1'))
    assert result['qualification'] == 'INCOMPLETE'
    p = payload()
    p['events'][1]['valid_until'] = at(3)
    p['rebate_pools'] = {}
    result = replay(p, config())
    assert set(result['reasons']) == {'capture_or_terms_gap', 'missing_rebate_pool'}


def test_missing_mark_and_nonvenue_settlement_fail_closed():
    p = payload()
    p['events'] = [e for e in p['events'] if e.get('at') != at(304)]
    result = replay(p, config(mark_max_delay_seconds='0'))
    assert 'missing_markout' in result['reasons']
    p['events'][-1]['source'] = 'reconstructed_weather_label'
    with pytest.raises(ValueError, match='venue settlement'):
        replay(p, config())


def test_policy_native_buys_and_fee_symmetry():
    quotes = market_centred_quote(book(), condition_id='c1', observed_at=at(0),
                                  size='20', distance_cents='1.5', tick='.01',
                                  expires_at=at(60), max_book_age_seconds='30')
    assert [(q['outcome'], q['price']) for q in quotes] == [('YES', '0.48'), ('NO', '0.48')]
    assert fee(100, '.5', '.05') == D('1.25')
    assert fee(100, '.3', '.05') == fee(100, '.7', '.05')
    assert replace(config(), informed_fraction='0').informed_fraction == '0'


def test_daily_payout_minimum_excludes_unpaid_rewards_from_pnl():
    p = payload()
    p['events'][1]['rate_per_day'] = '8640'
    result = replay(p, config())
    assert 0 < result['reward_accrued'] < 1
    assert result['reward_payable'] == 0
    assert result['raw_net_pnl'] == D('5.10')


def test_settlement_loss_does_not_replenish_global_cash_for_another_market():
    p = payload()
    p['end'] = at(610)
    p['conditions']['c1']['coverage_end'] = at(610)
    p['conditions']['c2'] = {**p['conditions']['c1'], 'token_ids': ['yes2', 'no2']}
    p['events'][-1].update(at=at(6), yes_payout='0')
    p['events'].append(book(307, condition='c2'))
    p['events'].append({**p['events'][1], 'at': at(307), 'condition_id': 'c2', 'valid_until': at(611)})
    p['commands'].append({**p['commands'][0], 'id': 'o2', 'condition_id': 'c2',
                          'observed_at': at(308), 'decided_at': at(308), 'expires_at': at(600)})
    result = replay(p, config(per_market_cap='5', total_cap='5'))
    assert result['venue_payout'] == 0
    assert result['rejected'] == [{'id': 'o2', 'reason': 'capital_cap'}]


def test_rewards_split_at_utc_midnight_before_daily_payout_floor():
    p = payload()
    delta = timedelta(hours=14, minutes=59, seconds=58)

    def shifted(value):
        return (utc(value) + delta).isoformat()

    for key in ('start', 'end'):
        p[key] = shifted(p[key])
    for condition in p['conditions'].values():
        for key in ('coverage_start', 'coverage_end'):
            condition[key] = shifted(condition[key])
    for row in p['events'] + p['commands']:
        for key in ('at', 'traded_at', 'valid_until', 'observed_at', 'decided_at', 'expires_at'):
            if key in row:
                row[key] = shifted(row[key])
    p['rebate_pools']['2026-10-13'] = p['rebate_pools']['2026-10-12']
    p['reward_epochs']['2026-10-13'] = p['reward_epochs']['2026-10-12']
    result = replay(p, config(latency_seconds='0', measured_p95_seconds='0',
                              order_latency_seconds='0', measured_order_p95_seconds='0'))
    assert {r['day'] for r in result['rewards']} == {'2026-10-12', '2026-10-13'}
    assert result['reward_payable'] == result['reward_accrued']
    assert result['reward_accrued'] == pytest.approx(D(40) / 7 + D(10) / 13)


def test_informed_fraction_changes_only_the_declared_stress():
    reports = [replay(payload(), config(informed_fraction=f)) for f in ('.25', '.5', '.75')]
    assert len({r['raw_net_pnl'] for r in reports}) == 1
    assert reports[0]['stressed_net_pnl'] > reports[1]['stressed_net_pnl'] > reports[2]['stressed_net_pnl']


def test_replay_decimal_context_is_pinned():
    expected = replay(payload(), config())
    with localcontext() as context:
        context.prec = 8
        assert replay(payload(), config()) == expected


def test_reward_epoch_uses_active_sample_normalization_and_requires_complete_denominator():
    p = payload()
    baseline = replay(p, config())['reward_accrued']
    p['reward_epochs']['2026-10-12']['c1']['active_seconds'] = '43200'
    assert abs(replay(p, config())['reward_accrued'] - baseline * 2) < D('1e-25')
    p['reward_epochs']['2026-10-12']['c1']['active_seconds'] = '1'
    with pytest.raises(ValueError, match='shorter than own eligible'):
        replay(p, config())
    p['reward_epochs'] = {}
    report = replay(p, config())
    assert 'missing_reward_epoch' in report['reasons']
    assert report['reward_accrued'] == 0


def test_full_account_day_threshold_uses_external_incentives_without_crediting_their_income():
    p = payload()
    p['events'][1]['rate_per_day'] = '8640'
    p['external_incentives'] = {'2026-10-12': {'reward_accrued': '2', 'rebate_accrued': '2',
                                               'complete': True, 'source_sha256': 'b' * 64}}
    report = replay(p, config())
    assert report['reward_payable'] == report['reward_accrued'] < 1
    assert report['rebate_payable'] == D('.0312375')
    assert report['raw_net_pnl'] == D('5.1') + report['reward_payable'] + report['rebate_payable']
    p['account_scope_complete'] = False
    assert 'incomplete_account_incentive_scope' in replay(p, config())['reasons']


def test_resolution_value_is_not_available_cash_until_explicit_redemption():
    p = payload()
    p['end'] = at(610)
    p['conditions']['c1']['coverage_end'] = at(610)
    p['conditions']['c2'] = {**p['conditions']['c1'], 'token_ids': ['yes2', 'no2']}
    p['events'][-1]['at'] = at(6)
    p['events'].append(book(8, condition='c2'))
    p['events'].append({**p['events'][1], 'at': at(8), 'condition_id': 'c2', 'valid_until': at(611)})
    p['reward_epochs']['2026-10-12']['c2'] = dict(p['reward_epochs']['2026-10-12']['c1'])
    p['commands'].append({**p['commands'][0], 'id': 'o2', 'condition_id': 'c2',
                          'observed_at': at(8), 'decided_at': at(8)})
    p['commands'].append({'kind': 'cancel', 'id': 'o2', 'observed_at': at(11), 'decided_at': at(11)})
    before = replay(p, config(per_market_cap='5', total_cap='5', informed_fraction='0'))
    assert before['rejected'] == [{'id': 'o2', 'reason': 'capital_cap'}]
    assert before['cash_redemptions_pusd'] == 0
    p['events'].append({'kind': 'redemption', 'condition_id': 'c1', 'at': at(7),
                        'fraction': '1', 'source': 'venue', 'source_sha256': 'c' * 64})
    after = replay(p, config(per_market_cap='5', total_cap='5', informed_fraction='0'))
    assert after['rejected'] == []
    assert after['cash_redemptions_pusd'] == 10
    assert after['unredeemed_venue_value'] == 0
    assert replay(p, config(per_market_cap='5', total_cap='5'))['rejected'] == []
    p['events'].append(dict(p['events'][-1]))
    with pytest.raises(ValueError, match='duplicate cash redemption'):
        replay(p, config(per_market_cap='5', total_cap='5', informed_fraction='0'))


def test_native_order_identity_changes_reward_share_without_changing_l2():
    b = book()
    own = [{'outcome': 'YES', 'price': D('.49'), 'remaining': D(20)},
           {'outcome': 'NO', 'price': D('.49'), 'remaining': D(20)}]
    terms = {'min_size': '20', 'max_spread_cents': '3'}
    assert reward_share(b, own, terms, 'maker_grouped') == D('.5')
    b['reward_orders'][1]['maker_id'] = 'another-maker'
    assert abs(reward_share(b, own, terms, 'maker_grouped') - D('.6')) < D('1e-25')
    b['reward_orders'].append(dict(b['reward_orders'][0]))
    with pytest.raises(ValueError, match='native reward order'):
        reward_share(b, own, terms, 'maker_grouped')
    b.pop('reward_orders')
    with pytest.raises(ValueError, match='native-order census'):
        reward_share(b, own, terms, 'maker_grouped')


def test_intent_and_transport_latency_prevent_backdated_arrival():
    p = payload()
    p['commands'][0]['decided_at'] = at(5)
    result = replay(p, config())
    assert result['fills'] == []  # arrival 6, after both public prints
    p['commands'][0]['arrival_at'] = at(2)
    with pytest.raises(ValueError, match='latency'):
        replay(p, config())


def test_expiry_precedes_same_instant_trade_and_cannot_be_omitted():
    p = payload()
    p['commands'][0]['expires_at'] = at(4)
    assert replay(p, config())['fills'] == []
    p['commands'][0].pop('expires_at')
    with pytest.raises(KeyError):
        replay(p, config())


def test_arrival_uses_captured_native_rules_and_oldest_observation_age():
    p = payload()
    changed = book(1)
    changed['YES']['tick'] = '.02'
    p['events'].append(changed)
    assert replay(p, config())['rejected'] == [{'id': 'o1', 'reason': 'arrival_market_rules'}]
    p = payload()
    delayed = book(2)
    delayed['observed_at'] = at(0)
    p['events'] = [e for e in p['events'] if e['kind'] != 'book' or e['at'] != at(0)]
    p['events'].append(delayed)
    assert replay(p, config(max_book_age_seconds='1'))['rejected'] == [
        {'id': 'o1', 'reason': 'stale_arrival_book'}]


def test_f_cost_reserve_does_not_change_settlement_or_use_the_winner_as_an_oracle():
    p = payload()
    winning = replay(p, config())
    p['events'][-1]['yes_payout'] = '0'
    losing = replay(p, config())
    assert winning['venue_payout'] == 10 and losing['venue_payout'] == 0
    assert winning['informed_stress_cost'] == losing['informed_stress_cost'] == D('3.675')
    assert winning['stress_rule'] == 'incremental_fill_cost_reserve'


def test_shared_tokens_across_conditions_and_early_cancels_refuse():
    p = payload()
    p['conditions']['c2'] = dict(p['conditions']['c1'])
    with pytest.raises(ValueError, match='token across conditions'):
        replay(p, config())
    p = payload()
    p['commands'].append({'kind': 'cancel', 'id': 'unknown', 'observed_at': at(0), 'decided_at': at(0)})
    with pytest.raises(ValueError, match='lacks its submitted'):
        replay(p, config())


def test_explicit_full_day_epoch_bound_requires_no_invented_active_sample_count():
    p = payload()
    baseline = replay(p, config())
    p['reward_epochs'] = {}
    bound = replay(p, config(reward_epoch_rule='full_day_upper_bound'))
    assert bound['reward_accrued'] == baseline['reward_accrued']
    assert 'missing_reward_epoch' not in bound['reasons']


@pytest.mark.parametrize('opening_state', [None, 'inventory'])
def test_opening_inventory_cannot_be_silently_reset(opening_state):
    p = payload()
    if opening_state is None:
        p.pop('opening_state')
    else:
        p['opening_state'] = opening_state
    with pytest.raises(ValueError, match='explicit flat opening state'):
        replay(p, config())
