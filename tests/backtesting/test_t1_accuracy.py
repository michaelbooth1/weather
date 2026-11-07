"""Guards: charter accuracy gate, LFC pin 124603578 chain and receipt attribution; synthetic only."""
from copy import deepcopy
import hashlib
import json

import pytest

from tests.backtesting.t1_fixtures import at, book, config, journal_bytes, payload, receipts, tolerance, no_fill_checkpoints
from weather.backtesting.t1_accuracy import (accuracy_gate, clob_fills, combine_session_gates,
                                             pin_commands, pin_latency_evidence, read_pin_evidence, read_pin_journal)


def test_synthetic_session_passes_independent_reward_fill_and_markout_arithmetic():
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert report['status'] == 'CASH_PENDING'
    assert report['rewards']['absolute_error'] < report['rewards']['limit']
    assert report['fills']['o1']['absolute_error'] == 0
    assert report['markouts_per_share']['o1']['absolute_error'] == 0
    assert report['trial_can_pass'] is False
    assert report['synthetic'] is True
    assert len(report['config_sha256']) == 64


def test_no_fill_or_tiny_reward_cannot_certify_accuracy():
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance(min_filled_orders=5))
    assert report['status'] == 'CASH_PENDING'


def test_wrong_queue_prediction_fails_fill_and_markout_gates():
    raw, p = journal_bytes(), payload()
    p['events'][0] = book(size='100')
    report = accuracy_gate(p, config(), raw, receipts(raw), tolerance())
    assert report['status'] == 'FAIL'
    assert report['fills']['o1']['pass'] is False
    assert report['markouts_per_share']['o1']['pass'] is False


def test_wrong_reward_rate_fails_accuracy_gate():
    raw, p = journal_bytes(), payload()
    p['events'][1]['rate_per_day'] = '8640000'
    report = accuracy_gate(p, config(), raw, receipts(raw), tolerance())
    assert report['status'] == 'FAIL'
    assert report['rewards']['pass'] is False


@pytest.mark.parametrize('mutation', ['byte', 'newline', 'sequence', 'terminal'])
def test_pin_hash_chain_and_completion_required(mutation):
    raw = journal_bytes()
    if mutation == 'byte':
        raw = raw.replace(b'20', b'21', 1)
    elif mutation == 'newline':
        raw = raw.rstrip()
    elif mutation == 'sequence':
        raw = raw.replace(b'"sequence":1', b'"sequence":2')
    else:
        raw = b'\n'.join(raw.splitlines()[:-1]) + b'\n'
    with pytest.raises(ValueError):
        read_pin_journal(raw)


@pytest.mark.parametrize('mutation,reason', [
    ('pages', 'pagination'), ('wallet', 'wallet and CLOB'), ('reward', 'wallet credit'),
    ('cash', 'cash identity'), ('scope', 'scope mismatch'), ('exclusive', 'unattributed'),
    ('maturity', 'immature'), ('token', 'token mismatch'),
    ('ledger_quantity', 'ledger and CLOB'), ('ledger_cost', 'ledger cost identity'),
    ('maker_account', 'maker account mismatch'),
])
def test_independent_receipt_refusals(mutation, reason):
    raw = journal_bytes()
    receipt = receipts(raw)
    if mutation == 'pages':
        receipt['clob']['complete'] = False
    elif mutation == 'wallet':
        receipt['wallet']['fills'][0]['size'] = '9'
    elif mutation == 'reward':
        receipt['wallet']['reward_credit'] = '99'
    elif mutation == 'cash':
        receipt['wallet']['end_cash'] = '99'
    elif mutation == 'scope':
        receipt['journal_sha256'] = 'f' * 64
    elif mutation == 'exclusive':
        receipt['rewards'][0]['session_exclusive'] = False
    elif mutation == 'maturity':
        receipt['rewards'][1]['as_of_utc'] = at(7)
    elif mutation == 'ledger_quantity':
        receipt['lfc_ledger']['legs'][0]['size_matched'] = '9'
        receipt['lfc_ledger']['L'] = receipt['lfc_ledger']['L_filled'] = '4.41'
    elif mutation == 'ledger_cost':
        receipt['lfc_ledger']['L_filled'] = '0'
    elif mutation == 'maker_account':
        receipt['clob']['rows'][0]['maker_orders'][0]['maker_address'] = 'another-account'
    else:
        receipt['clob']['rows'][0]['maker_orders'][0]['asset_id'] = 'no1'
    with pytest.raises(ValueError, match=reason):
        accuracy_gate(payload(), config(), raw, receipt, tolerance())


def test_clob_boundary_duplicate_id_keeps_distinct_fills_in_same_transaction():
    raw = journal_bytes()
    _, known = pin_commands(read_pin_journal(raw), 'c1')
    clob = receipts(raw)['clob']
    for row in clob['rows']:
        row['transaction_hash'] = 'same-tx'
    clob['rows'].append(deepcopy(clob['rows'][0]))
    assert len(clob_fills(clob, known, ['yes1', 'no1'], account_id='synthetic-account')) == 2
    clob['rows'][-1]['match_time'] = at(7)
    with pytest.raises(ValueError, match='conflicting'):
        clob_fills(clob, known, ['yes1', 'no1'], account_id='synthetic-account')


def test_journal_cancellation_adapter_uses_real_pin_event_shapes():
    base = [json.loads(line) for line in journal_bytes().splitlines()]
    events = [(0, r['event'], {k: v for k, v in r.items() if k not in (
        'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event')}) for r in base[:-1]]
    events += [(3, 'cancel_request', {'request': {'order_id': 'o1'}}),
               (4, 'cancel_response', {'response': {'canceled': ['o1']}}),
               (5, 'cleanup_cancel_all_response', {'response': {'canceled': ['o1']}}),
               (6, 'terminal', {k: v for k, v in base[-1].items() if k not in (
                   'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event')})]
    commands, _ = pin_commands(read_pin_journal(journal_bytes(events)), 'c1')
    assert [c['kind'] for c in commands] == ['post', 'cancel']
    assert commands[-1]['observed_at'] == at(3)


def test_tolerance_hash_changes_and_zero_tolerance_does_not_mask_reward_error():
    raw = journal_bytes()
    first = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    second = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance(reward_absolute='1'))
    assert first['tolerance_sha256'] != second['tolerance_sha256']
    assert first['journal_sha256'] == hashlib.sha256(raw).hexdigest()


def test_campaign_cannot_reuse_one_session_and_requires_filled_order_floor():
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    with pytest.raises(ValueError, match='duplicate campaign'):
        combine_session_gates([report, report], min_sessions=2, min_filled_orders=2, min_paid_reward='1')
    combined = combine_session_gates([report], min_sessions=1, min_filled_orders=5, min_paid_reward='1')
    assert combined['status'] == 'INSUFFICIENT_EVIDENCE'
    assert combined['trial_can_pass'] is False


def test_clob_wire_unix_seconds_and_nonfinal_fills():
    raw = journal_bytes()
    _, known = pin_commands(read_pin_journal(raw), 'c1')
    clob = receipts(raw)['clob']
    from weather.backtesting.t1_types import utc

    for row in clob['rows']:
        row['match_time'] = str(int(utc(row['match_time']).timestamp()))
        row['match_time_precision_seconds'] = '1'
    fills = clob_fills(clob, known, ['yes1', 'no1'], account_id='synthetic-account')
    assert [r['at'].isoformat() for r in fills] == [at(4), at(5)]
    clob['rows'][0]['status'] = 'MATCHED'
    with pytest.raises(ValueError, match='unknown own trade status'):
        clob_fills(clob, known, ['yes1', 'no1'], account_id='synthetic-account')


def test_pinned_journal_exports_full_end_to_end_latency_samples():
    evidence = pin_latency_evidence(journal_bytes())
    assert evidence['samples'] == [{'observed_at': at(0), 'decided_at': at(1), 'acknowledged_at': at(2),
                                    'collection_started_at': at(0)}]
    assert evidence['sample_count'] == 1
    assert evidence['synthetic'] is True


def test_independently_attributed_other_wallet_cashflows_reconcile_but_do_not_change_session_rewards():
    from decimal import Decimal as D

    raw = journal_bytes()
    receipt = receipts(raw)
    receipt['wallet']['other_attributed_cashflows'] = [{'id': 'external-1', 'session_id': 'other-session',
                                                       'amount': '-2', 'source_sha256': 'b' * 64}]
    receipt['wallet']['end_cash'] = str(D(receipt['wallet']['end_cash']) - 2)
    cash_at = '2026-10-13T09:00:01+00:00'
    receipt['wallet']['cash_events'].append({'id': 'external-1', 'kind': 'EXTERNAL', 'amount': '-2',
        'at': cash_at, 'finalized_at': cash_at, 'status': 'CONFIRMED', 'source_sha256': 'b' * 64})
    receipt['state_checkpoints'].append({'id': 'cash:external-1', 'at': cash_at,
        'cash': receipt['wallet']['end_cash'], 'reserved': '0', 'cost_at_risk': '0',
        'positions': {'yes1': '10', 'no1': '0'}, 'source_sha256': 'b' * 64})
    report = accuracy_gate(payload(), config(), raw, receipt, tolerance())
    assert report['status'] == 'CASH_PENDING'
    assert report['rewards']['actual'] == D(receipt['rewards'][1]['paid_reward'])


def test_journal_streams_discarded_observations_but_verifies_their_chain(tmp_path):
    from tests.backtesting.t1_fixtures import BASE
    from weather.backtesting.t1_types import utc

    base = [json.loads(line) for line in journal_bytes().splitlines()]
    events = [(int((utc(r['recorded_at_utc']) - BASE).total_seconds()), r['event'],
               {k: v for k, v in r.items() if k not in (
                   'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event')})
              for r in base]
    events[-1:-1] = [(3, 'heartbeat_acknowledged', {'heartbeat_counter': i}) for i in range(1000)]
    raw = journal_bytes(events)
    path = tmp_path / 'pilot.jsonl'
    path.write_bytes(raw)
    evidence = read_pin_evidence(path)
    assert evidence.record_count == 1006
    assert len(evidence.rows) == 6
    assert evidence.byte_count == len(raw)
    assert evidence.sha256 == hashlib.sha256(raw).hexdigest()
    assert pin_latency_evidence(path)['journal_sha256'] == evidence.sha256
    path.write_bytes(raw.replace(b'"heartbeat_counter":1,', b'"heartbeat_counter":9,', 1))
    with pytest.raises(ValueError, match='journal chain'):
        read_pin_evidence(path)


def test_lifecycle_rejection_cannot_hide_behind_loose_economic_tolerances():
    from tests.backtesting.t1_fixtures import BASE
    from weather.backtesting.t1_types import utc

    raw, p = journal_bytes(), payload()
    base = [json.loads(line) for line in raw.splitlines()]
    excluded = ('schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event')
    events = [(int((utc(r['recorded_at_utc']) - BASE).total_seconds()), r['event'],
               {k: v for k, v in r.items() if k not in excluded}) for r in base[:-1]]
    request = {**base[2]['request'], 'token_id': 'no1'}
    terminal = {k: v for k, v in base[-1].items() if k not in excluded}
    terminal.update(post_count=2, order_ids=['o1', 'o2'])
    events += [(2, 'submit_market_snapshot', {'snapshot': base[1]['snapshot']}),
               (2.1, 'submit_request', {'request': request}),
               (2.2, 'submit_response', {'response': {'orderID': 'o2', 'status': 'live'}}),
               (6, 'terminal', terminal)]
    raw = journal_bytes(events)
    receipt = receipts(raw)
    extra = {**receipt['lfc_ledger']['legs'][0], 'order_id': 'o2', 'intent_key': 'synthetic-session:2',
             'token_id': 'no1', 'size_matched': '0'}
    receipt['lfc_ledger']['legs'].append(extra)
    receipt['lfc_ledger']['our_order_ids'].append('o2')
    report = accuracy_gate(p, config(per_market_cap='5', total_cap='5'), raw, receipt, tolerance(
        reward_absolute='100', fill_absolute_shares='100', markout_absolute_per_share='100'))
    assert report['status'] == 'FAIL'
    assert report['simulator_complete'] is False
    assert report['lifecycle_rejections'] == [{'id': 'o2', 'reason': 'capital_cap'}]
    assert report['rewards']['pass'] and all(m['pass'] for m in report['fills'].values())
    assert all(m['pass'] for m in report['markouts_per_share'].values())


def test_integer_second_fill_markouts_are_bounded_over_timestamp_uncertainty():
    from weather.backtesting.t1_types import utc

    raw, p = journal_bytes(), payload()
    receipt = receipts(raw)
    for row in receipt['clob']['rows']:
        row['match_time'] = str(int(utc(row['match_time']).timestamp()))
        row['match_time_precision_seconds'] = '1'
    report = accuracy_gate(p, config(), raw, receipt, tolerance())
    assert report['status'] == 'CASH_PENDING'
    for index, event in enumerate(p['events']):
        if event['kind'] == 'book' and event['at'] in (at(305), at(306)):
            p['events'][index] = book(305 if event['at'] == at(305) else 306, '.55', '.57')
    report = accuracy_gate(p, config(), raw, receipt, tolerance())
    assert report['status'] == 'FAIL'
    assert report['markouts_per_share']['o1']['pass'] is False


def test_rebate_disagreement_cannot_pass_with_reconciled_wallet_cash():
    from decimal import Decimal as D

    raw = journal_bytes()
    receipt = receipts(raw)
    receipt['wallet']['rebate_credit'] = '.5'
    receipt['wallet']['payment_ids']['rebate'] = ['independent-rebate-credit']
    receipt['wallet']['end_cash'] = str(D(receipt['wallet']['end_cash']) + D('.5'))
    report = accuracy_gate(payload(), config(), raw, receipt, tolerance())
    assert report['status'] == 'FAIL'
    assert report['rebates']['pass'] is False
    assert report['rewards']['pass'] and all(m['pass'] for m in report['fills'].values())


def test_wrong_venue_payout_refuses_even_when_rewards_fills_markouts_agree():
    raw, p = journal_bytes(), payload()
    p['events'][-1]['yes_payout'] = '0'
    with pytest.raises(ValueError, match='wallet and captured venue settlement'):
        accuracy_gate(p, config(), raw, receipts(raw), tolerance())


@pytest.mark.parametrize('field,value', [('account_id', 'foreign-account'), ('session_id', 'foreign-session')])
def test_journal_identity_cannot_be_relabelled_by_receipt_export(field, value):
    raw = journal_bytes()
    receipt = receipts(raw)
    receipt['scope'][field] = value
    with pytest.raises(ValueError, match='receipt/journal scope mismatch'):
        accuracy_gate(payload(), config(), raw, receipt, tolerance())


def test_true_zero_fill_session_agrees_but_cannot_certify_fill_accuracy():
    from decimal import Decimal as D

    raw, p = journal_bytes(), payload()
    p['events'] = [e for e in p['events'] if e['kind'] != 'trade']
    receipt = receipts(raw)
    reward = D(40) / 7  # own score share 1/7 from arrival 2 to terminal 6
    receipt['clob']['rows'] = []
    receipt['lfc_ledger']['legs'][0]['size_matched'] = '0'
    receipt['lfc_ledger']['L'] = receipt['lfc_ledger']['L_filled'] = '0'
    receipt['wallet'].update(fills=[], settlement_value='0', redemption_credit='0',
                              reward_credit=str(reward), end_cash=str(D(100) + reward),
                              terminal_positions={'yes1': '0', 'no1': '0'}, end_positions={'yes1': '0', 'no1': '0'})
    receipt['state_checkpoints'][0].update(cash='100', cost_at_risk='0', positions={'yes1': '0', 'no1': '0'})
    no_fill_checkpoints(receipt, reward)
    for read in receipt['rewards']:
        read['paid_reward'] = str(reward)
    report = accuracy_gate(p, config(), raw, receipt, tolerance())
    assert report['status'] == 'INSUFFICIENT_EVIDENCE'
    assert report['metrics_pass'] is True
    assert report['actual_filled_orders'] == 0
