"""Guards: T014 F01-F20; funded-session financial accuracy and honest qualification gaps.

All receipts and event dates are synthetic and no later than 2026-10-14.
"""
from copy import deepcopy
from decimal import Decimal as D
import hashlib
import json

import pytest

from tests.backtesting.t1_fixtures import at, book, config, journal_bytes, payload, receipts, tolerance
from weather.backtesting import t1_accuracy
from weather.backtesting.t1_accuracy import accuracy_gate, combine_session_gates, F0_PIN
from weather.backtesting.t1_capture import verify_own_exclusions
from weather.backtesting.t1_policy import asof_commands
from weather.backtesting.t1_provenance import certify_campaign, verify_bundle, verify_ledger
from weather.backtesting.t1_rewards import qualified_price, reward_share
from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_types import canonical, digest, fee, utc


@pytest.mark.parametrize('field', ['venue_payout', 'cost', 'raw_net_pnl', 'cash_available', 'cash_redemptions_pusd',
                                  'unredeemed_venue_value', 'wallet_end_cash', 'cost_reserve', 'stressed_net_pnl'])
def test_financial_mutations_cannot_hide_behind_good_fill_reward_and_markouts(monkeypatch, field):
    original = t1_accuracy.replay

    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        result[field] += D('.25')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', corrupted)
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert report['status'] == 'FAIL'
    assert not report['economics'][{'cost_reserve': 'cost_reserve_identity', 'stressed_net_pnl': 'stressed_net_identity'}.get(field, field)]['pass']
    assert report['rewards']['pass'] and report['fills']['o1']['pass'] and report['markouts_per_share']['o1']['pass']


@pytest.mark.parametrize('stage', ['terminal_positions', 'end_positions'])
def test_predicted_position_mutation_fails_even_with_correct_pnl(monkeypatch, stage):
    original = t1_accuracy.replay

    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        result[stage]['c1']['yes1'] += 1
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', corrupted)
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert not report['positions'][stage]['yes1']['pass']
    assert report['status'] == 'FAIL'


def test_better_price_print_retires_only_that_queue_then_at_price_can_fill_losing_lot():
    p = payload()
    b = p['events'][0]
    b.pop('reward_orders')
    b['reward_orders_complete'] = False
    b['YES']['bids'].insert(0, {'price': '.50', 'size': '100'})
    b['NO']['asks'].insert(0, {'price': '.50', 'size': '100'})
    p['events'][2].update(price='.50', size='100')
    p['events'][3].update(price='.49', size='25')
    p['events'][-1]['yes_payout'] = '0'
    at_price = replay(p, config(queue_rule='back_at_price', competition_rule='aggregate_upper_bound'))
    through = replay(p, config(competition_rule='aggregate_upper_bound'))
    assert sum((r['size'] for r in at_price['fills']), D(0)) == 5
    assert through['fills'] == []
    # The smaller fill path is financially better on this losing exposure.
    assert at_price['cost'] == D('2.45') and through['cost'] == 0
    assert at_price['venue_payout'] - at_price['cost'] < through['venue_payout'] - through['cost']
    assert at_price['all_posted_lots_loss_floor'] == through['all_posted_lots_loss_floor'] == D('-4.9')
    assert at_price['passive_incentive_lower_bound'] == 0
    p['events'][-1]['yes_payout'] = '1'
    winning = replay(p, config(queue_rule='back_at_price', competition_rule='aggregate_upper_bound'))
    assert winning['venue_payout'] - winning['cost'] > through['venue_payout'] - through['cost']


def test_complementary_buy_consumes_no_maker_once_and_failed_print_cannot_fill():
    p = payload()
    p['commands'][0]['outcome'] = 'NO'
    p['commands'][0]['price'] = '.48'
    p['events'][2].update(aggressor='BUY', price='.52', execution_route='complementary_mint', route_source_sha256='a' * 64)
    p['events'][3].update(outcome='NO')
    mirror = {**p['events'][2], 'outcome': 'NO', 'aggressor': 'SELL', 'price': '.48', 'execution_route': 'native_sell', 'id': 'mirror'}
    p['events'].append(mirror)
    report = replay(p, config(queue_rule='back_at_price'))
    assert sum((r['size'] for r in report['fills']), D(0)) == 10
    p['events'][2]['status'] = mirror['status'] = 'FAILED'
    assert sum((r['size'] for r in replay(p, config(queue_rule='back_at_price'))['fills']), D(0)) == 0


def two_leg_session(index, allocation):
    """Independent 13/21 reward, one losing YES, winning NO and a real redemption.

    Two disjoint flat capital periods share ONE account-day payment. Rewards are
    not available to finance period two; only redeemed trading cash is reused.
    """
    offset, cid = (index - 1) * 400, f'c{index}'
    yes, no, sid = f'yes{index}', f'no{index}', f's{index}'
    oy, on = f'yes-order-{index}', f'no-order-{index}'
    scope = {'condition_id': cid, 'token_ids': [yes, no], 'maker_address': 'synthetic-account', 'session_id': sid}
    snap = {'condition_id': cid, 'token_ids': [yes, no], 'observed_at_utc': at(offset)}
    request = lambda token: {'token_id': token, 'side': 'BUY', 'price': '.49', 'size': '10',
                             'post_only': True, 'expiration': int(utc(at(offset + 60)).timestamp())}
    raw = journal_bytes([(offset, 'opened', {'scope': scope, 'mode': 'rehearse', 'profile_sha256': 'e' * 64}),
                         (offset, 'submit_market_snapshot', {'snapshot': snap}),
                         (offset + 1, 'submit_request', {'request': request(yes)}),
                         (offset + 2, 'submit_response', {'response': {'orderID': oy, 'status': 'live'}}),
                         (offset + 2.1, 'submit_request', {'request': request(no)}),
                         (offset + 2.25, 'submit_response', {'response': {'orderID': on, 'status': 'live'}}),
                         (offset + 6, 'terminal', {'cleanup_ok': True, 'evidence_complete': True, 'unknown_submit': False,
                                                  'inventory_proven': True, 'post_count': 2, 'order_ids': [oy, on]})])
    p = payload()
    p.update(start=at(offset), end=at(offset + 306), commands=[],
             conditions={cid: {**p['conditions']['c1'], 'token_ids': [yes, no],
                               'coverage_start': at(offset), 'coverage_end': at(offset + 306)}})
    term = {**p['events'][1], 'condition_id': cid, 'at': at(offset), 'valid_until': at(offset + 307), 'rate_per_day': '86400'}
    trade = {**p['events'][2], 'condition_id': cid, 'at': at(offset + 4), 'traded_at': at(offset + 4), 'size': '30'}
    opening_book = book(offset, condition=cid)
    for outcome, other in (('YES', 'NO'), ('NO', 'YES')):
        opening_book[outcome]['bids'].append({'price': '.45', 'size': '20'})
        opening_book[other]['asks'].append({'price': '.55', 'size': '20'})
        opening_book['reward_orders'].append({'order_id': f'far-{outcome}', 'maker_id': 'competitor',
                                               'outcome': outcome, 'side': 'BUY', 'price': '.45', 'size': '20'})
    raw_sides = {o: deepcopy(opening_book[o]) for o in ('YES', 'NO')}
    opening_book['own_exclusion'].update(raw_sides=raw_sides, raw_sides_sha256=digest(raw_sides))
    p['events'] = [opening_book, term,
                    {**trade, 'id': f't-yes-{index}', 'consumption_id': f't-yes-{index}'},
                    {**trade, 'id': f't-no-{index}', 'consumption_id': f't-no-{index}', 'aggressor': 'BUY',
                     'price': '.52', 'execution_route': 'complementary_mint', 'route_source_sha256': 'a' * 64},
                    *[book(offset + t, '.45', '.47', condition=cid) for t in (304, 305, 306)],
                    {'kind': 'settlement', 'condition_id': cid, 'at': at(offset + 306), 'yes_payout': '0', 'source': 'venue', 'source_sha256': 'c' * 64},
                    {'kind': 'redemption', 'id': f'redeem-{index}', 'condition_id': cid, 'at': at(offset + 306),
                     'tokens': {yes: '10', no: '10'}, 'source': 'venue', 'source_sha256': 'c' * 64}]
    p['reward_epochs']['2026-10-12'] = {cid: {'active_seconds': '86400', 'complete': True, 'source_sha256': 'a' * 64}}
    r = receipts(raw)
    r['scope'] = {'condition_id': cid, 'account_id': 'synthetic-account', 'session_id': sid, 'reward_day': '2026-10-12'}
    amount = D(13) / 21  # .25 * 1/7 + 1.75 * 1/3, reward rate 1 per second
    r['clob']['rows'] = [{'id': f'private-{oid}', 'market': cid, 'status': 'CONFIRMED', 'match_time': at(offset + 4),
                         'match_time_precision_seconds': '0', 'asset_id': token,
                         'maker_orders': [{'order_id': oid, 'asset_id': token, 'side': 'BUY', 'maker_address': 'synthetic-account',
                                           'price': '.49', 'matched_amount': '10'}]} for oid, token in ((oy, yes), (on, no))]
    r['lfc_ledger'].update(our_order_ids=[oy, on], L='9.8', L_filled='9.8', recorded_at_utc=at(offset + 6), legs=[
        {'session_id': sid, 'intent_key': f'{sid}:{leg}', 'order_id': oid, 'token_id': token, 'condition_id': cid,
         'price': '.49', 'size': '10', 'status': 'terminal', 'size_matched': '10'} for leg, (oid, token) in enumerate(((oy, yes), (on, no)))])
    w = r['wallet']
    w.update(session_id=sid, yes_payout='0', settlement_value='10', start_as_of_utc=at(offset),
             opening_positions={yes: '0', no: '0'}, terminal_positions={yes: '10', no: '10'}, end_positions={yes: '0', no: '0'},
             start_cash=str(D(100) + D('.2') * (index - 1)), end_cash=str(D('100.4') + 2 * amount),
             reward_credit=str(amount), redemption_credit='10',
             fills=[{'order_id': oid, 'price': '.49', 'size': '10'} for oid in (oy, on)],
             redemptions=[{'id': f'redeem-{index}', 'session_id': sid, 'at': at(offset + 306),
                           'tokens': {yes: '10', no: '10'}, 'credit': '10', 'source_sha256': 'c' * 64}],
             payment_ids={'reward': ['shared-day-payment'], 'rebate': [], 'redemption': [f'redeem-{index}']},
             other_attributed_cashflows=[{'id': f'other-session-cash-{index}', 'session_id': f's{3-index}',
                                           'amount': str(amount + (D('.2') if index == 1 else D(0))), 'source_sha256': 'a' * 64}])
    r['payment_ids'] = w['payment_ids']
    r['state_checkpoints'] = [{'id': 'terminal', 'at': at(offset + 6), 'cash': str(D(w['start_cash']) - D('9.8')),
                               'reserved': '0', 'cost_at_risk': '9.8', 'positions': {yes: '10', no: '10'}, 'source_sha256': 'a' * 64}]
    r['mark_books'] = [book(offset + t, '.45', '.47', condition=cid) for t in (304, 305, 306)]
    for read in r['rewards']:
        read.update(r['scope'], session_exclusive=False, allocation=deepcopy(allocation), paid_reward=str(amount))
    return p, raw, r


def shared_reports():
    amount = D(13) / 21
    allocation = {'method': 'independent_venue_accrual_deltas', 'source_sha256': 'a' * 64,
                  'payment_id': 'shared-day-payment', 'day_total': str(2 * amount), 'account_day_complete': True,
                  'sessions': {'s1': str(amount), 's2': str(amount)}}
    return [accuracy_gate(p, config(), raw, r, tolerance()) for p, raw, r in (two_leg_session(i, allocation) for i in (1, 2))]


def test_losing_fill_redemption_shared_reward_day_and_funded_campaign_reconcile():
    reports = shared_reports()
    assert all(r['status'] == 'PASS' for r in reports), [
        {'status': r['status'], 'reasons': r['simulator_reasons'], 'gaps': r['evidence_gaps'],
         'failed_economics': {k: v for k, v in r['economics'].items() if not v['pass']}} for r in reports]
    for r in reports:
        assert r['simulation']['venue_payout'] == 10 and r['simulation']['cash_redemptions_pusd'] == 10
        assert r['simulation']['cost'] == D('9.8')
        assert r['settlement_markout_per_share'][f"yes-order-{r['scope']['session_id'][-1]}"] == D('-.49')
        assert all(m['pass'] for m in r['economics'].values())
    campaign = combine_session_gates(reports, min_sessions=2, min_filled_orders=4, min_paid_reward='1', expected_session_ids=['s1', 's2'])
    assert campaign['status'] == 'PASS'
    assert campaign['paid_rewards'] == pytest.approx(D(26) / 21)
    assert campaign['net_pnl']['actual'] == pytest.approx(D('.4') + D(26) / 21)
    assert campaign['net_pnl']['absolute_error'] < D('1e-20')


@pytest.mark.parametrize('mutation', ['cash_reset', 'duplicate_order', 'duplicate_redemption', 'allocation', 'omitted_session', 'campaign_net'])
def test_campaign_refuses_reused_capital_credits_population_or_bad_net(mutation):
    reports = shared_reports()
    if mutation == 'cash_reset':
        reports[1]['capital_period']['opening_cash'] = D(100)
    elif mutation == 'duplicate_order':
        reports[1]['order_ids'] = reports[0]['order_ids']
    elif mutation == 'duplicate_redemption':
        reports[1]['payment_ids']['redemption'] = reports[0]['payment_ids']['redemption']
    elif mutation == 'allocation':
        reports[1]['reward_allocation']['method'] = 'simulated_share'
    elif mutation == 'omitted_session':
        reports = reports[:1]
    else:
        reports[1]['economics']['raw_net_pnl']['predicted'] += D('.1')
        result = combine_session_gates(reports, min_sessions=2, min_filled_orders=4, min_paid_reward='1')
        assert result['status'] == 'FAIL' and not result['net_pnl']['pass']
        return
    with pytest.raises(ValueError):
        combine_session_gates(reports, min_sessions=2, min_filled_orders=4, min_paid_reward='1', expected_session_ids=['s1', 's2'])


def test_f0_real_shape_intake_preserves_gaps_and_rehearsal_identity():
    raw = journal_bytes().replace(b'"mode":"replay"', b'"mode":"rehearse"')
    # Rebuild the canonical chain after changing the mode.
    rows = [json.loads(line) for line in raw.splitlines()]
    previous = None
    rebuilt = []
    for row in rows:
        row['previous_sha256'] = previous
        line = canonical(row)
        previous = hashlib.sha256(line).hexdigest()
        rebuilt.append(line)
    raw = b''.join(rebuilt)
    r = accuracy_gate({'input_kind': 'f0_lfc_recording', 'recorder_pin': F0_PIN}, config(), raw, {}, tolerance())
    assert r['status'] == 'NOT_QUALIFIED' and r['synthetic']
    assert r['net_pnl'] is None and r['cash'] is None
    assert r['commands'][0]['arrival_at'] == at(2)
    assert 'public_executions' in r['gap_flags'] and 'cash_positions' in r['gap_flags']


def test_f0_full_snapshot_partial_fill_cleanup_and_confirmed_trade_shapes_are_accepted():
    b = book()
    snap = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'observed_at_utc': at(0),
            'rules': {t: {'tick_size': '.01', 'min_order_size': '5', 'fee_rate_bps': '0'} for t in ('yes1', 'no1')},
            'quote_inputs': {'yes_bids': b['YES']['bids'], 'yes_asks': b['YES']['asks'],
                             'no_bids': b['NO']['bids'], 'no_asks': b['NO']['asks'],
                             'reward_min_size': '5', 'reward_max_spread_cents': '3', 'reward_rate_per_day': '100'},
            'fee_evidence': {'gamma': {'feesEnabled': True}, 'clob': {}, 'error': None}}
    scope = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'maker_address': 'synthetic-account', 'session_id': 's1'}
    req = {'token_id': 'yes1', 'side': 'BUY', 'price': '.49', 'size': '10', 'post_only': True, 'expiration': int(utc(at(60)).timestamp())}
    raw = journal_bytes([(0, 'opened', {'scope': scope, 'mode': 'rehearse', 'profile_sha256': 'a' * 64}),
                         (0, 'submit_market_snapshot', {'snapshot': snap}),
                         (1, 'submit_request', {'request': req}),
                         (2, 'submit_response', {'response': {'orderID': 'oy', 'success': True, 'status': 'live'}}),
                         (2.1, 'submit_request', {'request': {**req, 'token_id': 'no1'}}),
                         (2.25, 'submit_response', {'response': {'orderID': 'on', 'success': True, 'status': 'live'}}),
                         (3, 'market_snapshot', {'snapshot': {**snap, 'observed_at_utc': at(3)}}),
                         (4.1, 'terminal_trades', {'rows': [{'id': 'partial', 'status': 'CONFIRMED',
                            'maker_orders': [{'order_id': 'oy', 'matched_amount': '5', 'price': '.49'}]}]}),
                         (4.2, 'cleanup_cancel_all_request', {}),
                         (5, 'cleanup_cancel_all_response', {'response': {'canceled': ['oy', 'on']}}),
                         (6, 'terminal', {'cleanup_ok': True, 'evidence_complete': True, 'unknown_submit': False,
                                         'inventory_proven': True, 'post_count': 2, 'order_ids': ['oy', 'on']})])
    result = accuracy_gate({'input_kind': 'f0_lfc_recording', 'recorder_pin': F0_PIN}, config(), raw, {}, tolerance())
    assert result['status'] == 'NOT_QUALIFIED'
    assert len(result['commands']) == 4 and len(result['snapshots']) == 2
    assert result['snapshots'][0]['terms']['fee_evidence'] == snap['fee_evidence']
    assert result['confirmed_terminal_trades'][0]['maker_orders'][0]['matched_amount'] == '5'
    assert len(result['submit_latency_evidence']['cancel_samples']) == 2
    assert result['snapshots'][0]['use'] == 'RAW_DIAGNOSTIC_ONLY'


def test_single_subtraction_can_empty_competitor_side_but_cannot_erase_other_depth():
    from weather.backtesting.t1_capture import captured_book

    b = book()
    raw = {token: {'asset_id': token, 'market': 'c1', 'bids': b[outcome]['bids'], 'asks': b[outcome]['asks'],
                   'tick_size': '.01', 'min_order_size': '5', 'accepting_orders': True}
           for outcome, token in (('YES', 'yes1'), ('NO', 'no1'))}
    normalized = captured_book(raw, condition_id='c1', token_ids=['yes1', 'no1'], captured_at=at(3), observed_at=at(3),
                               source_sha256='a' * 64, token_times={o: {'started_at': at(3), 'completed_at': at(3)} for o in ('YES', 'NO')},
                               own=[{'order_id': 'o1', 'outcome': 'YES', 'price': '.49', 'remaining': '20'}])
    command = {'kind': 'post', 'id': 'o1', 'condition_id': 'c1', 'outcome': 'YES', 'price': '.49', 'size': '20',
               'decided_at': at(1), 'arrival_at': at(2), 'expires_at': at(60)}
    assert normalized['YES']['bids'] == [] and verify_own_exclusions([normalized], [command], []) == []
    own = [{'outcome': 'YES', 'price': D('.49'), 'remaining': D(20)}]
    assert reward_share(normalized, own, {'min_size': '5', 'max_spread_cents': '3'}, 'aggregate_upper_bound') > 0
    normalized['NO']['bids'][0]['size'] = D(19)
    with pytest.raises(ValueError, match='subtracted exactly once'):
        verify_own_exclusions([normalized], [command], [])


def test_duplicate_price_representation_cannot_weaken_aggregate_denominator():
    b = book(size='20')
    own = [{'outcome': 'YES', 'price': D('.49'), 'remaining': D(20)}, {'outcome': 'NO', 'price': D('.49'), 'remaining': D(20)}]
    terms = {'min_size': '20', 'max_spread_cents': '3'}
    original = reward_share(b, own, terms, 'aggregate_upper_bound')
    for outcome in ('YES', 'NO'):
        for side in ('bids', 'asks'):
            row = b[outcome][side][0]
            b[outcome][side] = [{**row, 'size': '10'}, {**row, 'size': '10'}]
    assert reward_share(b, own, terms, 'aggregate_upper_bound') == original


def test_midpoint_semantics_and_own_cross_or_halt_are_explicit():
    rows = [(D('.49'), D(10)), (D('.48'), D(10)), (D('.47'), D(20))]
    assert qualified_price(rows, D(20), bids=True, semantics='level_filter') == D('.47')
    assert qualified_price(rows, D(20), bids=True, semantics='cumulative_depth') == D('.48')
    p = payload()
    p['commands'] = [{**p['commands'][0], 'price': '.5'}, {**p['commands'][0], 'id': 'other', 'outcome': 'NO', 'price': '.5'}]
    assert replay(p, config())['rejected'] == [{'id': 'other', 'reason': 'own_post_only_cross'}]
    p['events'][0]['accepting_orders'] = False
    assert all(r['reason'] == 'market_not_accepting_orders' for r in replay(p, config())['rejected'])


def test_asof_policy_cannot_see_settlement_or_accept_hindsight_commands():
    p = payload()
    policy = {'kind': 'first_book_pair_v1', 'eligible_conditions': ['c1'], 'size': '10', 'distance_cents': '1', 'lifetime_seconds': 60}
    p.update(policy=policy, commands=[])
    first = replay(p, config())['decision_trace']
    p['events'][-1]['yes_payout'] = '0'
    assert replay(p, config())['decision_trace'] == first
    p['commands'] = [{**first[0], 'price': '.01'}]
    with pytest.raises(ValueError, match='deterministic as-of'):
        replay(p, config())


def test_raw_bundle_hashes_and_full_ledger_chain_are_verified(tmp_path):
    raw = canonical({'kind': 'retained_receipt'})
    path = tmp_path / 'receipt.json'
    path.write_bytes(raw)
    bundle = {'files': [{'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'role': 'wallet'}]}
    assert verify_bundle(bundle, tmp_path)['wallet']['sha256'] == hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        verify_bundle(bundle, tmp_path)
    bundle['files'][0]['path'] = '../outside.json'
    with pytest.raises(ValueError, match='within the staged'):
        verify_bundle(bundle, tmp_path)


def test_full_pinned_ledger_transitions_must_match_snapshot(tmp_path):
    rows = [
        ('genesis', {'budget_pusd': '100', 'maker_address': 'synthetic-account'}),
        ('session_start', {'session_id': 's1'}),
        ('leg_intent', {'session_id': 's1', 'intent_key': 'i1', 'token_id': 'yes1', 'condition_id': 'c1', 'price': '.49', 'size': '10'}),
        ('leg_ack', {'intent_key': 'i1', 'order_id': 'o1'}),
        ('leg_terminal', {'order_id': 'o1', 'size_matched': '5'}),
        ('session_end', {'session_id': 's1'})]
    lines, previous = [], None
    for sequence, (event, fields) in enumerate(rows):
        line = canonical({'schema_version': 'lfc_ledger_v0.2', 'kind': 'lfc_ledger', 'sequence': sequence,
                          'previous_sha256': previous, 'recorded_at_utc': at(sequence), 'event': event, **fields})
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    snapshot = {'history_rows': len(rows), 'history_last_sha256': previous, 'budget_pusd': '100',
                'recorded_at_utc': at(5), 'our_order_ids': ['o1'], 'legs': [
                    {'session_id': 's1', 'intent_key': 'i1', 'token_id': 'yes1', 'condition_id': 'c1',
                     'price': '.49', 'size': '10', 'order_id': 'o1', 'status': 'terminal', 'size_matched': '5'}]}
    path = tmp_path / 'ledger.jsonl'
    path.write_bytes(b''.join(lines))
    assert verify_ledger(path, snapshot, 'synthetic-account')['legs'] == 1
    snapshot['legs'][0]['size_matched'] = '6'
    with pytest.raises(ValueError, match='snapshot disagrees'):
        verify_ledger(path, snapshot, 'synthetic-account')
    path.write_bytes(b''.join(lines).replace(b'"size_matched":"5"', b'"size_matched":"6"'))
    with pytest.raises(ValueError, match='history chain'):
        verify_ledger(path, snapshot, 'synthetic-account')


def test_missing_losing_share_fails_dollars_even_under_one_share_fill_allowance(monkeypatch):
    p, raw = payload(), journal_bytes()
    p['events'][-1]['yes_payout'] = '0'
    r = receipts(raw)
    r['wallet'].update(yes_payout='0', settlement_value='0')
    original = t1_accuracy.replay

    def missed_losing_share(*args, **kwargs):
        result = original(*args, **kwargs)
        result['fills'][-1]['size'] -= 1
        result['cost'] -= D('.49')
        result['raw_net_pnl'] += D('.49')
        result['terminal_positions']['c1']['yes1'] -= 1
        result['end_positions']['c1']['yes1'] -= 1
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', missed_losing_share)
    report = accuracy_gate(p, config(), raw, r, tolerance(fill_absolute_shares='1'))
    assert report['fills']['o1']['pass'] and not report['economics']['raw_net_pnl']['pass']
    assert report['status'] == 'FAIL'


def test_unresolved_inventory_stays_full_loss_and_zero_fill_needs_no_settlement():
    p, raw = payload(), journal_bytes()
    p['events'] = [e for e in p['events'] if e['kind'] != 'settlement']
    r = receipts(raw)
    r['wallet'].update(settlement_complete=False, settlement_value='0')
    report = accuracy_gate(p, config(), raw, r, tolerance())
    assert report['actual_accounts']['venue_payout'] == 0
    assert not report['metrics_pass'] and 'unsettled_inventory' in report['simulator_reasons']
    assert report['actual_accounts']['raw_net_pnl'] == pytest.approx(-D('4.9') + D(r['wallet']['reward_credit']))


def test_recorded_sampling_is_separate_from_continuous_accrual_and_repeated_minutes_refuse():
    p = payload()
    p['reward_realization'] = 'observed_samples'
    sample = {'kind': 'reward_sample', 'condition_id': 'c1', 'at': at(3), 'epoch_active_sample_count': '1440', 'source_sha256': 'a' * 64}
    p['events'].append(sample)
    result = replay(p, config())
    assert result['reward_accrued'] == pytest.approx(D('864000') / 1440 / 7)
    p['events'].append(dict(sample))
    with pytest.raises(ValueError, match='duplicate reward sample'):
        replay(p, config())


def test_wide_independent_mark_interval_is_unidentified_not_model_error():
    p, raw = payload(), journal_bytes()
    r = receipts(raw)
    for row in r['clob']['rows']:
        row['match_time'] = str(int(utc(row['match_time']).timestamp()))
        row['match_time_precision_seconds'] = '1'
    r['mark_books'][1:] = [book(305, '.35', '.37'), book(306, '.55', '.57')]
    report = accuracy_gate(p, config(), raw, r, tolerance())
    assert report['status'] == 'NOT_QUALIFIED'
    assert 'markout_time_resolution_insufficient' in report['evidence_gaps']
    assert report['markouts_per_share']['o1']['pass']
    assert report['markouts_per_share']['o1']['identified'] is False


def test_condition_day_rebate_pools_reconcile_category_and_eligibility():
    p = payload()
    condition_pool = {**p['rebate_pools']['2026-10-12'], 'condition_id': 'c1', 'eligible': True,
                      'fee_coefficient': '.05', 'rebate_fraction': '.25',
                      'valid_from': '2026-10-12T00:00:00Z', 'valid_until': '2026-10-13T00:00:00Z'}
    p['rebate_pools']['2026-10-12'] = {'conditions': {'c1': condition_pool},
        'category_totals': {'total_taker_fees': '10', 'total_maker_fee_weight': '10', 'complete': True, 'source_sha256': 'd' * 64}}
    assert replay(p, config())['rebate_scope_qualification'] == 'CONDITION_DAY_REQUIRES_RAW_PROOF'
    condition_pool['eligible'] = False
    with pytest.raises(ValueError, match='not eligible'):
        replay(p, config())
    condition_pool['eligible'] = True
    condition_pool['total_taker_fees'] = '9'
    with pytest.raises(ValueError, match='category aggregates'):
        replay(p, config())


def test_fee_precision_and_synthetic_certificate_cannot_masquerade_as_real():
    assert fee(1, '.49', '.05', 'per_match_5dp_half_even') == D('.01250')
    with pytest.raises(ValueError, match='real clean-code'):
        certify_campaign([{'synthetic': True}], expected_session_ids=['s1'], min_sessions=1, min_filled_orders=1, min_paid_reward='1')


def test_common_closing_cash_independently_checks_actual_campaign_net():
    reports = shared_reports()
    reports[1]['economics']['raw_net_pnl']['actual'] += D('.2')
    campaign = combine_session_gates(reports, min_sessions=2, min_filled_orders=4, min_paid_reward='1')
    assert campaign['status'] == 'FAIL'
    assert not campaign['actual_campaign_cash_identity']['pass']


def test_campaign_envelope_cannot_be_changed_after_certificate_binding():
    # A deliberately fabricated, invalid envelope exercises a guard only. No
    # real or qualifying receipt is created by setting this nonsynthetic flag.
    envelope = {'synthetic': False, 'code': {'worktree_clean': True}, 'result': {}, 'inputs': {},
                'accuracy_certificate': {'status': 'PASS', 'result_sha256': 'a' * 64}}
    with pytest.raises(ValueError, match='changed after receipt certification'):
        certify_campaign([envelope], expected_session_ids=['s1'], min_sessions=1, min_filled_orders=1, min_paid_reward='1')
