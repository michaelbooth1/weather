"""Guards: T035 C1-C9 and B024; synthetic adversarial receipts only (Oct 12-14).

Nominal-live wire headers below are adversarial test inputs, never real evidence.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal as D
import hashlib
import json
import re

import pytest

from tests.backtesting.t1_fixtures import at, book, config, journal_bytes, payload, receipts, tolerance, no_fill_checkpoints, attach_activity_prefixes
from tests.backtesting.test_t1_qualification import shared_reports, two_leg_session
from weather.backtesting import t1_accuracy, t1_cli
from weather.backtesting.t1_accuracy import accuracy_gate, combine_session_gates
from weather.backtesting.t1_provenance import session_certificate, certify_campaign
from weather.backtesting.t1_raw_projection import PROJECTOR, verify_projection, without_lineage
from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_types import canonical, digest, utc


def contradictory_cli_bundle(root, monkeypatch):
    """T035 C1, including its non-executing exporter and contradictory raw money."""
    entries, hashes = [], {}

    def retain(role, value, extension='.json'):
        data = value if isinstance(value, bytes) else canonical(value)
        path = root / (role + extension)
        path.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        entries.append({'role': role, 'path': path.name, 'sha256': sha})
        hashes[role] = sha

    for role in ('profile', 'clob', 'reward_d1', 'reward_d2', 'books', 'marks', 'terms', 'settlement',
                 'redemptions', 'rebates', 'reward_samples', 'market_state', 'clock', 'rebate_rounding'):
        retain(role, {'synthetic_test_only': True, 'role': role})
    retain('wallet', {'synthetic_test_only': True, 'end_cash': '0', 'start_cash': '100',
                       'actual_profit': '-100', 'end_positions': {'yes1': '0', 'no1': '0'}})
    retain('exporter', b'raise RuntimeError("Exporter must never be trusted merely by hash")\n', '.py')
    events = []
    for line in journal_bytes().splitlines():
        row = json.loads(line)
        seconds = (utc(row['recorded_at_utc']) - utc(at(0))).total_seconds()
        fields = {k: v for k, v in row.items() if k not in (
            'schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event')}
        if row['event'] == 'opened':
            fields.update(mode='live', profile_sha256=hashes['profile'])
        events.append((seconds, row['event'], fields))
    raw = journal_bytes(events)
    retain('journal', raw, '.jsonl')
    p, r = payload(), receipts(raw)
    p['reward_realization'] = 'observed_samples'
    p['events'][1]['rate_per_day'] = '34'
    p['events'].append({'kind': 'reward_sample', 'condition_id': 'c1', 'at': at(3),
                        'epoch_active_sample_count': '1', 'source_sha256': hashes['reward_samples']})
    pool = p['rebate_pools']['2026-10-12']
    p['rebate_pools']['2026-10-12'] = {'conditions': {'c1': {**pool, 'condition_id': 'c1', 'eligible': True,
        'fee_coefficient': '.05', 'rebate_fraction': '.25', 'valid_from': '2026-10-12T00:00:00Z', 'valid_until': '2026-10-13T00:00:00Z'}}}
    mapping = dict(zip(('a' * 64, 'b' * 64, 'c' * 64, 'd' * 64, 'e' * 64, 'f' * 64, '3' * 64, '4' * 64),
                       (hashes[k] for k in ('clock', 'terms', 'settlement', 'rebates', 'books', 'clob', 'reward_d1', 'reward_d2'))))

    def remap(value):
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    p, r = remap(p), remap(r)
    r['profile_sha256'] = hashes['profile']
    r['wallet']['end_cash_source_sha256'] = hashes['wallet']
    p['midpoint_rule_evidence'] = {'semantics': 'level_filter', 'basis': 'dated_venue_rule', 'source_sha256': hashes['terms']}
    p['reward_sample_evidence'] = {'method': 'venue_observed_samples', 'day_complete': True, 'source_sha256': hashes['reward_samples']}
    p['fee_rounding_evidence'] = {'rule': 'per_match_5dp_half_even', 'granularity': 'per_match', 'source_sha256': hashes['rebate_rounding']}
    leg = r['lfc_ledger']['legs'][0]
    ledger_events = [(0, 'genesis', {'budget_pusd': '100', 'maker_address': 'synthetic-account'}),
        (0, 'session_start', {'session_id': 'synthetic-session'}),
        (1, 'leg_intent', {k: leg[k] for k in ('session_id', 'intent_key', 'token_id', 'condition_id', 'price', 'size')}),
        (2, 'leg_ack', {'intent_key': leg['intent_key'], 'order_id': 'o1'}),
        (5, 'leg_terminal', {'order_id': 'o1', 'size_matched': '10'}),
        (6, 'session_end', {'session_id': 'synthetic-session'})]
    previous, lines = None, []
    for i, (seconds, event, fields) in enumerate(ledger_events):
        line = canonical({'schema_version': 'lfc_ledger_v0.2', 'kind': 'lfc_ledger', 'sequence': i,
                          'previous_sha256': previous, 'recorded_at_utc': at(seconds), 'event': event, **fields})
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    retain('ledger', b''.join(lines), '.jsonl')
    r['lfc_ledger'].update(history_rows=len(lines), history_last_sha256=previous)
    latency = t1_accuracy.pin_latency_evidence(raw, recorder_pin=r['journal_pin'])
    cfg = config(fee_rounding_rule='per_match_5dp_half_even', latency_source_sha256=digest(latency))
    result = accuracy_gate(p, cfg, raw, r, tolerance())
    # Isolate raw verification from the unrelated dirty-checkout guard. The CLI
    # itself, argument parsing, disk reads and certificate path remain unchanged.
    code = {'git_commit': 'a' * 40, 'worktree_clean': True, 'source_sha256': {'synthetic_test_only': 'a' * 64}}
    monkeypatch.setattr(t1_cli, 'source_binding', lambda: code)
    retain('recorder_manifest', {'git_commit': r['journal_pin'], 'worktree_clean': True,
        'journal_sha256': result['journal_sha256'], 'profile_sha256': hashes['profile'], 'session_id': 'synthetic-session'})
    retain('preregistration', {'code': code, 'config_sha256': result['config_sha256'],
        'tolerance_sha256': result['tolerance_sha256'], 'exporter_sha256': hashes['exporter'],
        'missing_session_rule': 'FAIL_WHOLE_CAMPAIGN_RETAIN_FULL_LOSS_ROWS',
        'expected_session_ids': ['synthetic-session'], 'frozen_at_utc': at(-1)})
    r['evidence_bundle'] = {'files': entries}
    for name, value in (('inputs', p), ('config', asdict(cfg)), ('receipts', r), ('tolerance', asdict(tolerance())), ('latency', latency)):
        (root / (name + '.json')).write_bytes(canonical(value))
    args = ['accuracy']
    for flag, name in (('inputs', 'inputs.json'), ('config', 'config.json'), ('receipts', 'receipts.json'),
                       ('tolerance', 'tolerance.json'), ('latency-evidence', 'latency.json'), ('journal', 'journal.jsonl'), ('output', 'result.json')):
        args.extend(['--' + flag, str(root / name)])
    return args


def test_t035_c1_cli_rejects_contradictory_retained_raw_wallet(tmp_path, monkeypatch):
    args = contradictory_cli_bundle(tmp_path, monkeypatch)
    assert t1_cli.main(args) == 2
    report = json.loads((tmp_path / 'result.json').read_bytes())
    assert report['accuracy_certificate']['status'] == 'NOT QUALIFIED'
    assert 'wallet/end_cash' in report['accuracy_certificate']['raw_projection']['reason']


def test_t035_c4_external_depth_is_not_charged_for_our_fill(monkeypatch):
    p = payload()
    later = book(3, size='40')
    later['reward_orders'] = deepcopy(p['events'][0]['reward_orders'])
    later['reward_orders'] += [{**row, 'order_id': 'late-' + row['order_id']}
                               for row in deepcopy(later['reward_orders'])]
    p['events'].append(later)
    seen = []
    from weather.backtesting import t1_simulator

    original = t1_simulator.reward_share

    def observe(b, resting, terms, rule, midpoint_rule):
        if b['at'] == at(3):
            seen.append((deepcopy(b), [r['remaining'] for r in resting]))
        return original(b, resting, terms, rule, midpoint_rule)

    monkeypatch.setattr(t1_simulator, 'reward_share', observe)
    result = replay(p, config())
    after = next(b for b, remaining in seen if remaining == [D(5)])
    assert sum((D(row['size']) for row in after['YES']['bids']), D(0)) == 20
    assert not result['reasons']
    assert result['reward_accrued'] == pytest.approx(D(10) / 7 + D(20) / 13)


@pytest.mark.parametrize('denominators,reason', [(['1', '1', '1'], 'exceed'), (['3', '2', '3'], 'inconsistent')])
def test_t035_c5_rejects_invalid_sample_denominators(denominators, reason):
    p = payload()
    p['events'] = [e for e in p['events'] if e['kind'] not in ('trade', 'settlement')]
    p['commands'][0]['expires_at'] = at(200)
    p['reward_realization'] = 'observed_samples'
    for second, count in zip((3, 63, 123), denominators):
        p['events'].append({'kind': 'reward_sample', 'condition_id': 'c1', 'at': at(second),
                            'epoch_active_sample_count': count, 'source_sha256': 'a' * 64})
    with pytest.raises(ValueError, match=reason):
        replay(p, config())


def test_t035_c6_persisted_campaign_decodes_decimal_strings(tmp_path):
    reports = shared_reports()
    path = tmp_path / 'reports.json'
    path.write_bytes(canonical(reports))
    options = dict(min_sessions=2, min_filled_orders=4, min_paid_reward='1', expected_session_ids=['s1', 's2'])
    expected = combine_session_gates(reports, **options)
    actual = combine_session_gates(json.loads(path.read_bytes()), **options)
    assert actual['status'] == expected['status'] == 'PASS'
    assert actual['net_pnl'] == expected['net_pnl']


def zero_fill_session():
    p, raw = payload(), journal_bytes()
    p['events'] = [e for e in p['events'] if e['kind'] not in ('trade', 'settlement')]
    p['events'][1]['rate_per_day'] = '0'
    r = receipts(raw)
    r['clob']['rows'] = []
    r['lfc_ledger']['legs'][0]['size_matched'] = '0'
    r['lfc_ledger']['L'] = r['lfc_ledger']['L_filled'] = '0'
    r['wallet'].update(fills=[], settlement_value='0', redemption_credit='0', reward_credit='0', end_cash='100',
        terminal_positions={'yes1': '0', 'no1': '0'}, end_positions={'yes1': '0', 'no1': '0'})
    r['wallet']['payment_ids']['reward'] = []
    r['state_checkpoints'][0].update(cash='100', cost_at_risk='0', positions={'yes1': '0', 'no1': '0'})
    for read in r['rewards']:
        read['paid_reward'] = '0'
    no_fill_checkpoints(r, '0', settlement=False)
    return p, raw, r


def test_t035_c7_zero_fill_accounting_certification_has_no_positive_session_floor(tmp_path):
    p, raw, r = zero_fill_session()
    report = accuracy_gate(p, config(), raw, r, tolerance())
    assert report['metrics_pass'] and report['status'] == 'INSUFFICIENT_EVIDENCE'
    cert = session_certificate(report, {'worktree_clean': True}, r, p, tmp_path)
    assert 'session_metrics_not_passed' not in cert['gaps']


def test_interrupted_population_member_is_retained_in_campaign_denominator():
    reports = shared_reports()
    reports.append({'scope': {'session_id': 'interrupted'}, 'status': 'NOT_QUALIFIED'})
    result = combine_session_gates(reports, min_sessions=3, min_filled_orders=4, min_paid_reward='1',
                                    expected_session_ids=['s1', 's2', 'interrupted'])
    assert result['status'] == 'NOT_QUALIFIED' and result['sessions'] == 3
    assert 'interrupted' in result['session_ids'] and result['net_pnl'] is None


def test_completed_zero_activity_member_counts_in_campaign_population():
    reports = shared_reports()
    scope = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'maker_address': 'synthetic-account', 'session_id': 'idle'}
    raw = journal_bytes([(800, 'opened', {'scope': scope, 'mode': 'rehearse', 'profile_sha256': 'e' * 64}),
        (806, 'terminal', {'cleanup_ok': True, 'evidence_complete': True, 'unknown_submit': False,
                          'inventory_proven': True, 'post_count': 0, 'order_ids': []})])
    p, r = payload(), receipts(raw)
    p.update(start=at(800), end=at(806), events=[], commands=[], rebate_pools={}, reward_epochs={})
    p['conditions']['c1'].update(coverage_start=at(800), coverage_end=at(806))
    r['scope']['session_id'] = 'idle'
    r['clob']['rows'], r['mark_books'] = [], []
    r['lfc_ledger'].update(legs=[], our_order_ids=[], L='0', L_filled='0', recorded_at_utc=at(806))
    amount = D(13) / 21
    w = r['wallet']
    w.update(session_id='idle', fills=[], start_as_of_utc=at(800), start_cash='100.4',
        end_cash=str(D('100.4') + 2 * amount), reward_credit='0', settlement_value='0', yes_payout='0',
        terminal_positions={'yes1': '0', 'no1': '0'}, end_positions={'yes1': '0', 'no1': '0'},
        payment_ids={'reward': [], 'rebate': [], 'redemption': []})
    w['other_attributed_cashflows'] = [{'id': 'idle-external-' + sid, 'session_id': sid,
        'amount': str(amount), 'source_sha256': 'a' * 64} for sid in ('s1', 's2')]
    w['cash_events'] = [{**flow, 'kind': 'EXTERNAL', 'at': f'2026-10-13T09:00:0{i}+00:00',
        'finalized_at': f'2026-10-13T09:00:0{i}+00:00', 'status': 'CONFIRMED'}
        for i, flow in enumerate(w['other_attributed_cashflows'])]
    r['state_checkpoints'] = [{'id': key, 'at': when, 'cash': str(cash), 'reserved': '0', 'cost_at_risk': '0',
        'positions': {'yes1': '0', 'no1': '0'}, 'source_sha256': 'a' * 64}
        for key, when, cash in [('opening', at(800), D('100.4')), ('terminal', at(806), D('100.4')),
            *[('cash:' + flow['id'], flow['at'], D('100.4') + (i + 1) * amount)
              for i, flow in enumerate(w['cash_events'])]]]
    for read in r['rewards']:
        read.update(session_id='idle', paid_reward='0')
    idle = accuracy_gate(p, config(), raw, r, tolerance())
    assert idle['metrics_pass'] and idle['accounting_complete'] and idle['completed_cash']['status'] == 'COMPLETE'
    combined = combine_session_gates([*reports, idle], min_sessions=3, min_filled_orders=4,
        min_paid_reward='1', expected_session_ids=['s1', 's2', 'idle'])
    assert combined['status'] == 'PASS' and combined['sessions'] == 3


def test_campaign_joint_budget_cannot_cancel_opposite_session_errors():
    reports = shared_reports()
    for report, error in zip(reports, (D('.006'), D('-.006'))):
        report['economics']['raw_net_pnl']['predicted'] += error
        report['joint_error']['absolute_error'] = abs(error)
    combined = combine_session_gates(reports, min_sessions=2, min_filled_orders=4, min_paid_reward='1')
    assert combined['net_pnl']['pass']
    assert combined['joint_error']['absolute_error'] == D('.012')
    assert not combined['joint_error']['pass'] and combined['status'] == 'FAIL'


def test_t035_c3_offsetting_components_fail_joint_error_budget(monkeypatch):
    original = t1_accuracy.replay

    def faulty(*args, **kwargs):
        result = original(*args, **kwargs)
        result['cost'] += D('.009')
        result['venue_payout'] += D('.009')
        result['cost_reserve'] = D('.75') * result['cost']
        result['stressed_net_pnl'] = result['raw_net_pnl'] - result['cost_reserve']
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', faulty)
    raw = journal_bytes()
    result = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert result['status'] == 'FAIL'
    assert result['joint_error']['absolute_error'] == pytest.approx(D('.018'), abs=D('1e-24'))
    assert not result['joint_error']['pass']


def test_offsetting_redemption_and_residual_errors_share_no_netting_allowance(monkeypatch):
    original = t1_accuracy.replay

    def faulty(*args, **kwargs):
        result = original(*args, **kwargs)
        result['cash_redemptions_pusd'] += D('.006')
        result['unredeemed_venue_value'] -= D('.006')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', faulty)
    raw = journal_bytes()
    result = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert result['economics']['venue_payout']['pass'] and result['economics']['raw_net_pnl']['pass']
    assert result['joint_error']['absolute_error'] == pytest.approx(D('.012'), abs=D('1e-24'))
    assert result['status'] == 'FAIL'


def test_terminal_only_checkpoint_cannot_certify_transition_path(tmp_path):
    raw = journal_bytes()
    p, r = payload(), receipts(raw)
    r['state_checkpoints'] = r['state_checkpoints'][:1]
    result = accuracy_gate(p, config(), raw, r, tolerance())
    assert not result['accounting_complete']
    assert 'post:o1' in result['transition_verification']['missing']
    certificate = session_certificate(result, {'worktree_clean': True}, r, p, tmp_path)
    assert 'economic_transition_coverage_or_state_not_verified' in certificate['gaps']


def test_t035_c2_unredeemed_economic_profit_cannot_be_completed_cash(tmp_path):
    raw = journal_bytes()
    p, r = payload(), receipts(raw)
    result = accuracy_gate(p, config(), raw, r, tolerance())
    assert result['actual_accounts']['economic_net_pnl'] > 0
    assert result['actual_accounts']['cash_net_pnl'] < 0
    assert result['completed_cash']['status'] == 'NOT COMPLETE'
    assert 'unredeemed_venue_value' in result['completed_cash']['gaps']
    certificate = session_certificate(result, {'worktree_clean': True}, r, p, tmp_path)
    assert 'completed_cash_not_final' in certificate['gaps']


def test_t035_c8_truthful_d1_pending_d2_paid_is_accepted():
    raw = journal_bytes()
    r = receipts(raw)
    r['rewards'][0]['paid_reward'] = '0'
    paid_at = '2026-10-14T09:00:00+00:00'
    r['wallet']['cash_events'][0].update(at=paid_at, finalized_at=paid_at)
    next(p for p in r['state_checkpoints'] if p['id'].startswith('cash:'))['at'] = paid_at
    report = accuracy_gate(payload(), config(), raw, r, tolerance())
    assert report['metrics_pass']
    assert report['rewards']['actual'] == D(r['rewards'][1]['paid_reward'])
    assert r['rewards'][0]['paid_reward'] == '0'


def test_later_immutable_payment_followup_does_not_rewrite_d1_or_d2():
    # Shift this episode to Oct 11 so its D+3 payment is also <= Oct 14.
    def earlier(data):
        return re.sub(rb'2026-10-(12|13|14)', lambda m: f'2026-10-{int(m[1]) - 1:02d}'.encode(), data)

    previous, lines = None, []
    for row in map(json.loads, earlier(journal_bytes()).splitlines()):
        row['previous_sha256'] = previous
        if row['event'] == 'submit_request':
            row['request']['expiration'] -= 86400
        line = canonical(row)
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    raw = b''.join(lines)
    p, r = json.loads(earlier(canonical([payload(), receipts(raw)])))
    paid = r['wallet']['reward_credit']
    for read in r['rewards']:
        read['paid_reward'] = '0'
    followup = {**r['rewards'][-1], 'as_of_utc': '2026-10-14T10:00:00Z', 'source_sha256': '5' * 64, 'paid_reward': paid}
    r['reward_followups'] = [followup]
    r['wallet']['as_of_utc'] = followup['as_of_utc']
    r['wallet']['cash_events'][0].update(at=followup['as_of_utc'], finalized_at=followup['as_of_utc'])
    next(p for p in r['state_checkpoints'] if p['id'].startswith('cash:'))['at'] = followup['as_of_utc']
    result = accuracy_gate(p, config(), raw, r, tolerance())
    assert result['metrics_pass']
    assert result['rewards']['actual'] == D(paid)
    assert [read['paid_reward'] for read in r['rewards']] == ['0', '0']


@pytest.mark.spawns
def test_t035_c9_native_f0_partial_intake_matches_recorded_shapes(tmp_path):
    from tests.backtesting.test_t1_qualification import test_f0_full_snapshot_partial_fill_cleanup_and_confirmed_trade_shapes_are_accepted
    from tests.backtesting.test_t1_cli import test_native_f0_intake_cli_accepts_empty_measurement_and_receipts_with_gap_flags

    test_f0_full_snapshot_partial_fill_cleanup_and_confirmed_trade_shapes_are_accepted()
    test_native_f0_intake_cli_accepts_empty_measurement_and_receipts_with_gap_flags(tmp_path)
    report = json.loads((tmp_path / 'result.json').read_bytes())
    assert report['result']['status'] == 'NOT_QUALIFIED'


def native_snapshot(snapshot, account='synthetic-account'):
    """Retain native six-decimal collateral and complete v2 position responses."""
    snapshot.setdefault('cash', '100')
    snapshot['collateral_evidence'] = {'balance': str(D(snapshot['cash']) * 1_000_000)}
    rows = [{'token_id': t, 'condition_id': 'c1', 'proxy_wallet': account, 'current_size': str(size)}
            for t, size in snapshot['positions'].items() if D(size)]
    snapshot['position_walks'] = {status: [[{'request_cursor': None, 'response': {
        'data': rows if status == 'OPEN' else [], 'pagination': {'next_cursor': None, 'has_more': False}}}]]
        for status in ('OPEN', 'REDEEMABLE_LOST')}
    snapshot['order_pages'] = [{'request_cursor': None, 'response': {'data': [], 'next_cursor': 'LTE='}}]
    return snapshot


def numeric_tokens(value):
    if isinstance(value, dict):
        return {numeric_tokens(k): numeric_tokens(v) for k, v in value.items()}
    if isinstance(value, list):
        return [numeric_tokens(v) for v in value]
    return {'yes1': '1001', 'no1': '1002'}.get(value, value) if isinstance(value, str) else value


def stage_raw_financial_fixture(root):
    """Positive raw primitive check, independent of a qualified market model."""
    previous, lines = None, []
    for row in map(json.loads, journal_bytes().splitlines()):
        row = numeric_tokens(row)
        row['previous_sha256'] = previous
        line = canonical(row)
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    raw_journal = b''.join(lines)
    p, r = numeric_tokens(payload()), numeric_tokens(receipts(raw_journal))
    reward = D(r['wallet']['reward_credit']).quantize(D('.000001'))
    r['wallet'].update(reward_credit=str(reward), end_cash=str(D('95.1') + reward))
    for read in r['rewards']:
        read['paid_reward'] = str(reward)
    next(c for c in r['state_checkpoints'] if c['id'].startswith('cash:'))['cash'] = r['wallet']['end_cash']
    pay_at = '2026-10-13T09:00:00+00:00'
    cash_event = {'id': 'reward-day-1', 'kind': 'REWARD', 'at': pay_at, 'amount': str(reward),
                  'status': 'CONFIRMED', 'finalized_at': pay_at}
    r['wallet'].update(cash_events=[{**cash_event, 'source_sha256': 'a' * 64}], cash_followup_complete=True,
                       payment_scope_complete=True, closing_open_orders=[])
    r['wallet']['fills'] = [{'order_id': 'o1', 'price': '.49', 'size': '5'} for _ in range(2)]
    activity = [{'id': f'buy-{i}', 'kind': 'BUY', 'at': at(second), 'status': 'CONFIRMED',
                 'order_id': 'o1', 'token_id': '1001', 'price': '.49', 'size': '5', 'cash_delta': '-2.45'}
                for i, second in enumerate((4, 5))]
    activity.append({k: v for k, v in {**cash_event, 'cash_delta': str(reward)}.items() if k != 'amount'})
    wallet = {'format': PROJECTOR, 'account_id': r['scope']['account_id'], 'session_id': r['scope']['session_id'],
              'opening': {'at': at(0), 'cash': '100', 'positions': {'yes1': '0', 'no1': '0'},
                          'open_orders': [], 'other_positions': [], 'other_open_orders': []},
              'terminal': {'at': at(6), 'cash': '95.1', 'positions': {'yes1': '10', 'no1': '0'}},
              'closing': {'at': r['wallet']['as_of_utc'], 'cash': r['wallet']['end_cash'],
                          'positions': {'yes1': '10', 'no1': '0'}, 'open_orders': [], 'activity_final': True},
              'activity': activity, 'activity_cursor': 'LTE=',
              'checkpoints': without_lineage(deepcopy(r['state_checkpoints']))}
    wallet = numeric_tokens(wallet)
    attach_activity_prefixes(wallet, r['state_checkpoints'])
    for snapshot in [wallet[k] for k in ('opening', 'terminal', 'closing')] + wallet['checkpoints']:
        native_snapshot(snapshot)
    roles = {'journal': raw_journal,
             'wallet': wallet,
             'clob': {'endpoint': r['clob']['endpoint'], 'pages': [{'request_cursor': None,
                       'response': {'data': r['clob']['rows'], 'next_cursor': 'LTE='}}]},
             'settlement': {'resolutions': [{'condition_id': 'c1', 'token_ids': ['1001', '1002'], 'status': 'FINAL',
                                            'available_at': at(306),
                                            'payout_denominator': '1', 'payout_numerators': ['1', '0']}]},
             'redemptions': {'transactions': []}}
    for role, read in zip(('reward_d1', 'reward_d2'), r['rewards']):
        roles[role] = {**{k: read[k] for k in ('account_id', 'condition_id', 'reward_day', 'as_of_utc')},
                       'credits': [{'id': 'reward-day-1', 'at': pay_at, 'status': 'CONFIRMED',
                                    'finalized_at': pay_at,
                                    'amount': str(reward), 'sessions': {r['scope']['session_id']: str(reward)}}]}
    verified = {}
    for role, data in roles.items():
        path = root / (role + ('.jsonl' if role == 'journal' else '.json'))
        content = data if isinstance(data, bytes) else canonical(data)
        path.write_bytes(content)
        verified[role] = {'path': path, 'sha256': hashlib.sha256(content).hexdigest()}
    r['wallet']['end_cash_source_sha256'] = verified['wallet']['sha256']
    r['wallet']['settlement_source_sha256'] = verified['settlement']['sha256']
    next(e for e in p['events'] if e['kind'] == 'settlement')['source_sha256'] = verified['settlement']['sha256']
    r['wallet']['cash_events'][0]['source_sha256'] = verified['wallet']['sha256']
    for checkpoint in r['state_checkpoints']:
        checkpoint['source_sha256'] = verified['wallet']['sha256']
    for role, read in zip(('reward_d1', 'reward_d2'), r['rewards']):
        read['source_sha256'] = verified[role]['sha256']
    report = accuracy_gate(p, config(), raw_journal, r, tolerance())
    return verified, p, r, report


def test_raw_wallet_snapshots_activity_and_clob_recompute_actual_pnl(tmp_path):
    verified, p, r, report = stage_raw_financial_fixture(tmp_path)
    check = verify_projection(verified, r, p, report)
    assert check['status'] == 'PASS'
    assert check['transitions']['status'] == 'PASS', check['transitions']
    assert check['actual_accounts']['cost'] == D('4.9')
    assert check['actual_accounts']['cash_net_pnl'] < 0 < check['actual_accounts']['raw_net_pnl']


@pytest.mark.parametrize('field', ['cash', 'positions'])
def test_raw_projection_rejects_internally_contradictory_closing_snapshot(tmp_path, field):
    verified, p, r, report = stage_raw_financial_fixture(tmp_path)
    path = verified['wallet']['path']
    wallet = json.loads(path.read_bytes())
    wallet['closing'][field] = '0' if field == 'cash' else {'1001': '0', '1002': '0'}
    path.write_bytes(canonical(wallet))
    verified['wallet']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='wallet/'):
        verify_projection(verified, r, p, report)


@pytest.mark.parametrize('change', ['cash', 'positions', 'cursor'])
def test_native_wallet_pages_are_verified_without_convenience_totals(tmp_path, change):
    verified, p, r, report = stage_raw_financial_fixture(tmp_path)
    path = verified['wallet']['path']
    wallet = json.loads(path.read_bytes())
    closing = wallet['closing']
    del closing['cash'], closing['positions']
    if change == 'cash':
        closing['collateral_evidence']['balance'] = '0'
    elif change == 'positions':
        closing['position_walks']['OPEN'][0][0]['response']['data'][0]['current_size'] = '0'
    else:
        closing['position_walks']['OPEN'][0][0]['response']['pagination'] = {'next_cursor': 'more', 'has_more': True}
    path.write_bytes(canonical(wallet))
    verified['wallet']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verify_projection(verified, r, p, report)


def test_raw_settlement_availability_cannot_be_backdated(tmp_path):
    verified, p, r, report = stage_raw_financial_fixture(tmp_path)
    next(e for e in p['events'] if e['kind'] == 'settlement')['at'] = at(5)
    with pytest.raises(ValueError, match='settlement event source, clock or payout'):
        verify_projection(verified, r, p, report)


def test_latest_raw_pending_credit_blocks_completed_payment(tmp_path):
    verified, p, r, report = stage_raw_financial_fixture(tmp_path)
    role = verified['reward_d2']
    raw = json.loads(role['path'].read_bytes())
    raw['credits'].append({'id': 'still-pending', 'status': 'PENDING', 'at': at(5)})
    role['path'].write_bytes(canonical(raw))
    role['sha256'] = hashlib.sha256(role['path'].read_bytes()).hexdigest()
    r['rewards'][-1]['source_sha256'] = role['sha256']
    with pytest.raises(ValueError, match='latest retained reward observation still has pending credits'):
        verify_projection(verified, r, p, report)


def test_unredeemed_losing_tokens_do_not_claim_completed_cash():
    raw = journal_bytes()
    p, r = payload(), receipts(raw)
    next(e for e in p['events'] if e['kind'] == 'settlement')['yes_payout'] = '0'
    r['wallet'].update(yes_payout='0', settlement_value='0')
    result = accuracy_gate(p, config(), raw, r, tolerance())
    assert result['metrics_pass'] and result['status'] == 'CASH_PENDING'
    assert 'unredeemed_token_positions' in result['completed_cash']['gaps']


@pytest.mark.spawns
def test_t035_c6_actual_cli_envelope_files_round_trip_through_campaign(tmp_path):
    amount = D(13) / 21
    allocation = {'method': 'independent_venue_accrual_deltas', 'source_sha256': 'a' * 64,
                  'payment_id': 'shared-day-payment', 'day_total': str(2 * amount), 'account_day_complete': True,
                  'sessions': {'s1': str(amount), 's2': str(amount)}}
    latency = {'kind': 'observation_to_order_ack', 'sample_count': 1, 'synthetic': True,
               'samples': [{'observed_at': at(0), 'decided_at': at(1), 'acknowledged_at': at(2)}]}
    envelopes = []
    for i in (1, 2):
        folder = tmp_path / str(i)
        folder.mkdir()
        p, journal, r = two_leg_session(i, allocation)
        values = {'inputs': p, 'receipts': r, 'tolerance': asdict(tolerance()), 'latency': latency,
                  'config': config(latency_source_sha256=digest(latency)).projection()}
        for name, value in values.items():
            (folder / (name + '.json')).write_bytes(canonical(value))
        (folder / 'journal.jsonl').write_bytes(journal)
        args = ['accuracy']
        for flag, name in (('inputs', 'inputs.json'), ('config', 'config.json'), ('receipts', 'receipts.json'),
                           ('tolerance', 'tolerance.json'), ('latency-evidence', 'latency.json'),
                           ('journal', 'journal.jsonl'), ('output', 'report.json')):
            args.extend(['--' + flag, str(folder / name)])
        assert t1_cli.main(args) == 2  # synthetic cannot become real qualification
        envelopes.append(json.loads((folder / 'report.json').read_bytes()))
    combined = certify_campaign(envelopes, expected_session_ids=['s1', 's2'], min_sessions=2,
        min_filled_orders=4, min_paid_reward='1', synthetic_diagnostic=True)
    assert combined['status'] == 'SYNTHETIC_PASS'
    assert combined['completed_cash_net_pnl']['actual'] == pytest.approx(D('.4') + D(26) / 21)
    assert combined['trial_can_pass'] is False
    with pytest.raises(ValueError, match='real clean-code'):
        certify_campaign(envelopes, expected_session_ids=['s1', 's2'], min_sessions=2, min_filled_orders=4, min_paid_reward='1')


def test_missing_or_changed_transition_cannot_hide_behind_final_state(monkeypatch):
    original = t1_accuracy.replay

    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        result['transitions']['fill:o1:1']['cash'] += D('.00002')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', corrupted)
    raw = journal_bytes()
    result = accuracy_gate(payload(), config(), raw, receipts(raw), tolerance())
    assert not result['accounting_complete'] and result['status'] == 'FAIL'
    assert not result['transition_verification']['metrics']['fill:o1:1']['cash']['pass']


def test_raw_sample_population_is_verified_and_cannot_be_hash_only():
    from weather.backtesting.t1_raw_market import verify_samples

    p = payload()
    p['events'] = [e for e in p['events'] if e['kind'] != 'trade']
    p['events'] += [{'kind': 'reward_sample', 'condition_id': 'c1', 'at': at(t),
                     'epoch_active_sample_count': '3', 'source_sha256': 'a' * 64} for t in (3, 63, 123)]
    raw = {'epochs': [{'condition_id': 'c1', 'day': '2026-10-12', 'active_sample_count': '3',
                       'sample_times': [at(t) for t in (3, 63, 123)]}]}
    assert verify_samples(raw, p, 'a' * 64)['status'] == 'PASS'
    raw['epochs'][0]['active_sample_count'] = '1'
    with pytest.raises(ValueError, match='population'):
        verify_samples(raw, p, 'a' * 64)


def test_raw_book_projection_checks_acceptance_as_well_as_price_depth():
    from weather.backtesting.t1_capture import captured_book
    from weather.backtesting.t1_raw_market import verify_books

    sides = book()
    raw_books = {token: {'asset_id': token, 'market': 'c1', 'bids': sides[o]['bids'],
        'asks': sides[o]['asks'], 'tick_size': '.01', 'min_order_size': '5', 'accepting_orders': False}
        for token, o in (('yes1', 'YES'), ('no1', 'NO'))}
    record = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'raw_books': raw_books,
              'captured_at': at(0), 'observed_at': at(0), 'own': []}
    projected = captured_book(raw_books, condition_id='c1', token_ids=record['token_ids'],
                             captured_at=at(0), observed_at=at(0), source_sha256='a' * 64)
    assert verify_books({'captures': [record]}, [projected], 'a' * 64)['status'] == 'PASS'
    projected['accepting_orders'] = True
    with pytest.raises(ValueError, match='accepting_orders'):
        verify_books({'captures': [record]}, [projected], 'a' * 64)


def test_raw_public_print_projection_checks_wire_fields_and_preserves_authority_gap():
    from weather.backtesting.t1_capture import captured_print
    from weather.backtesting.t1_raw_market import verify_prints

    p = payload()
    row = {'event_type': 'last_trade_price', 'asset_id': 'yes1', 'side': 'SELL', 'price': '.49', 'size': '25',
           'timestamp': str(int(utc(at(4)).timestamp() * 1000)), 'execution_id': 't1',
           'status': 'CONFIRMED', 'execution_route': 'native_sell', 'consumption_id': 't1'}
    raw = {'prints': [{'condition_id': 'c1', 'row': row, 'captured_at': at(4)}]}
    p['events'] = [captured_print(row, captured_at=at(4), condition_id='c1', token_ids=['yes1', 'no1'], source_sha256='a' * 64)]
    result = verify_prints(raw, p, 'a' * 64)
    assert result['status'] == 'PASS' and result['authority_status'] == 'NOT QUALIFIED'
    p['events'][0]['size'] = '30'
    with pytest.raises(ValueError, match='market_state/prints'):
        verify_prints(raw, p, 'a' * 64)


def test_finality_clock_blocks_completed_cash_even_after_redemption():
    report = shared_reports()[0]
    assert report['completed_cash']['status'] == 'COMPLETE'
    allocation = report['reward_allocation']
    p, raw, r = two_leg_session(1, allocation)
    r['wallet']['redemptions'][0]['finalized_at'] = '2026-10-14T23:00:00Z'
    r['wallet']['as_of_utc'] = '2026-10-14T10:00:00Z'
    pending = accuracy_gate(p, config(), raw, r, tolerance())
    assert pending['status'] == 'CASH_PENDING'
    assert 'payment_or_redemption_not_final' in pending['completed_cash']['gaps']


def test_idle_raw_accounting_member_is_eligible_without_fill_reward_or_market_floors(tmp_path):
    """A fully reconciled synthetic idle member has only the synthetic barrier."""
    verified, entries = {}, []

    def retain(role, data):
        content = data if isinstance(data, bytes) else canonical(data)
        path = tmp_path / (role + ('.jsonl' if role in ('journal', 'ledger') else '.json'))
        path.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        verified[role] = {'path': path, 'sha256': sha}
        entries.append({'path': path.name, 'role': role, 'sha256': sha})
        return sha

    profile = retain('profile', {'role': 'synthetic profile'})
    scope = {'condition_id': 'c1', 'token_ids': ['yes1', 'no1'], 'maker_address': 'synthetic-account',
             'session_id': 'synthetic-session'}
    raw = journal_bytes([(0, 'opened', {'scope': scope, 'mode': 'rehearse', 'profile_sha256': profile}),
                         (6, 'terminal', {'cleanup_ok': True, 'evidence_complete': True, 'unknown_submit': False,
                                          'inventory_proven': True, 'post_count': 0, 'order_ids': []})])
    retain('journal', raw)
    p, r = payload(), receipts(raw)
    p.update(events=[], commands=[], rebate_pools={}, reward_epochs={})
    r['clob']['rows'] = []
    r['profile_sha256'] = profile
    r['mark_books'] = []
    w = r['wallet']
    w.update(fills=[], terminal_positions={'yes1': '0', 'no1': '0'}, end_positions={'yes1': '0', 'no1': '0'},
             end_cash='100', reward_credit='0', settlement_value='0', yes_payout='0', cash_events=[],
             payment_ids={'reward': [], 'rebate': [], 'redemption': []})
    r['state_checkpoints'] = [{'id': key, 'at': at(t), 'cash': '100', 'reserved': '0', 'cost_at_risk': '0',
                               'positions': {'yes1': '0', 'no1': '0'}, 'source_sha256': 'a' * 64}
                              for key, t in (('opening', 0), ('terminal', 6))]
    raw_wallet = {'format': PROJECTOR, 'account_id': 'synthetic-account', 'session_id': 'synthetic-session',
        'opening': {'at': at(0), 'cash': '100', 'positions': {'yes1': '0', 'no1': '0'},
                    'open_orders': [], 'other_positions': [], 'other_open_orders': []},
        'terminal': {'at': at(6), 'positions': {'yes1': '0', 'no1': '0'}},
        'closing': {'at': w['as_of_utc'], 'cash': '100', 'positions': {'yes1': '0', 'no1': '0'},
                    'open_orders': [], 'activity_final': True},
        'activity': [], 'activity_cursor': 'LTE=', 'checkpoints': without_lineage(r['state_checkpoints'])}
    for snapshot in [raw_wallet[k] for k in ('opening', 'terminal', 'closing')] + raw_wallet['checkpoints']:
        native_snapshot(snapshot)
    raw_wallet['period_closing'] = native_snapshot({'at': p['end'], 'cash': '100', 'positions': {'yes1': '0', 'no1': '0'}})
    observation_rows = []
    for key in ('opening', 'period_closing', 'closing'):
        observation_rows.append({'id': key, **deepcopy(raw_wallet[key])})
        raw_wallet[key + '_observation_id'] = key
    observation_hash = retain('wallet_observations', {'account_id': 'synthetic-account', 'account_scope_complete': True,
                                                    'snapshots': observation_rows})
    for key in ('opening', 'period_closing', 'closing'):
        w[key + '_observation'] = {'id': key, 'source_sha256': observation_hash}
    wallet_hash = retain('wallet', raw_wallet)
    w['end_cash_source_sha256'] = observation_hash
    w['activity_source_sha256'] = wallet_hash
    for row in r['state_checkpoints']:
        row['source_sha256'] = wallet_hash
    w['settlement_source_sha256'] = retain('settlement', {'resolutions': []})
    retain('redemptions', {'transactions': []})
    retain('clob', {'endpoint': r['clob']['endpoint'], 'pages': [
        {'request_cursor': None, 'response': {'data': [], 'next_cursor': 'LTE='}}]})
    for role, read in zip(('reward_d1', 'reward_d2'), r['rewards']):
        read['paid_reward'] = '0'
        read['source_sha256'] = retain(role, {**{k: read[k] for k in ('account_id', 'condition_id', 'reward_day', 'as_of_utc')}, 'credits': []})
    previous, lines = None, []
    for i, (event, fields, seconds) in enumerate((('genesis', {'maker_address': 'synthetic-account', 'budget_pusd': '100'}, 0),
        ('session_start', {'session_id': 'synthetic-session'}, 0), ('session_end', {'session_id': 'synthetic-session'}, 6))):
        line = canonical({'schema_version': 'lfc_ledger_v0.2', 'kind': 'lfc_ledger', 'sequence': i,
                           'previous_sha256': previous, 'recorded_at_utc': at(seconds), 'event': event, **fields})
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    retain('ledger', b''.join(lines))
    r['lfc_ledger'].update(legs=[], our_order_ids=[], history_rows=3, history_last_sha256=previous, L='0', L_filled='0')
    result = accuracy_gate(p, config(), raw, r, tolerance())
    assert result['metrics_pass'] and result['accounting_complete']
    assert result['completed_cash']['status'] == 'COMPLETE' and result['status'] == 'INSUFFICIENT_EVIDENCE'
    code = {'worktree_clean': True, 'git_commit': 'a' * 40, 'source_sha256': {}}
    retain('clock', {'role': 'synthetic clock evidence'})
    exporter = retain('exporter', {'role': 'synthetic exporter identity; internal projector verifies facts'})
    retain('recorder_manifest', {'git_commit': r['journal_pin'], 'worktree_clean': True,
        'journal_sha256': result['journal_sha256'], 'profile_sha256': profile, 'session_id': 'synthetic-session'})
    retain('preregistration', {'code': code, 'config_sha256': result['config_sha256'],
        'tolerance_sha256': result['tolerance_sha256'], 'exporter_sha256': exporter,
        'missing_session_rule': 'FAIL_WHOLE_CAMPAIGN_RETAIN_FULL_LOSS_ROWS',
        'expected_session_ids': ['synthetic-session'], 'frozen_at_utc': at(-1)})
    # The evidence bundle is added after the arithmetic input hash, as in the
    # certificate-producing CLI; all raw monetary facts are independently checked.
    r['evidence_bundle'] = {'files': entries}
    result = accuracy_gate(p, config(), raw, r, tolerance())
    cert = session_certificate(result, code, r, p, tmp_path)
    assert cert['gaps'] == ['synthetic_receipts'], cert
    assert cert['components']['midpoint_semantics']['status'] == 'NOT APPLICABLE'
    assert cert['raw_projection']['transitions']['status'] == 'PASS'
