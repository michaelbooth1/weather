"""Guards: charter accuracy gate, LFC pin 124603578 chain and receipt attribution; synthetic only."""
from copy import deepcopy
import hashlib
import json

import pytest

from tests.backtesting.t1_fixtures import at, config, journal_bytes, payload, receipts, tolerance
from weather.backtesting.t1_accuracy import (accuracy_gate, clob_fills, combine_session_gates,
                                             pin_commands, read_pin_journal)


def test_synthetic_session_passes_independent_reward_fill_and_markout_arithmetic():
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert report['status'] == 'PASS'
    assert report['rewards']['absolute_error'] < report['rewards']['limit']
    assert report['fills']['o1']['absolute_error'] == 0
    assert report['markouts_per_share']['o1']['absolute_error'] == 0
    assert report['trial_can_pass'] is False
    assert len(report['config_sha256']) == 64


def test_no_fill_or_tiny_reward_cannot_certify_accuracy():
    raw = journal_bytes()
    report = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance(min_filled_orders=5))
    assert report['status'] == 'INSUFFICIENT_EVIDENCE'


def test_wrong_queue_prediction_fails_fill_and_markout_gates():
    raw, p = journal_bytes(), payload()
    p['events'][0]['YES']['bids'][0]['size'] = '100'
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
    assert len(clob_fills(clob, known, ['yes1', 'no1'])) == 2
    clob['rows'][-1]['match_time'] = at(7)
    with pytest.raises(ValueError, match='conflicting'):
        clob_fills(clob, known, ['yes1', 'no1'])


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
    fills = clob_fills(clob, known, ['yes1', 'no1'])
    assert [r['at'].isoformat() for r in fills] == [at(4), at(5)]
    clob['rows'][0]['status'] = 'MATCHED'
    with pytest.raises(ValueError, match='unknown own trade status'):
        clob_fills(clob, known, ['yes1', 'no1'])
