"""Guards: T035r1 N1/N2/N4/N5; derived net, shared observations, transition ordering.

Only deterministic synthetic receipts with event and follow-up dates <= Oct 14.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import json

import pytest

from tests.backtesting.t1_fixtures import at, config, tolerance
from tests.backtesting.t1_raw_fixtures import build_two_leg_raw, shared_raw_campaign
from tests.backtesting.test_t1_qualification import shared_reports, two_leg_session
from weather.backtesting import t1_accuracy
from weather.backtesting import t1_cli
from weather.backtesting.t1_accuracy import accuracy_gate, combine_session_gates
from weather.backtesting.t1_provenance import certify_campaign, session_certificate
from weather.backtesting.t1_raw_projection import verify_projection
from weather.backtesting.t1_types import canonical, digest

OPTIONS = dict(min_sessions=2, min_filled_orders=4, min_paid_reward='1', expected_session_ids=['s1', 's2'])


def test_n1_injected_opposite_cash_net_errors_fail_session_and_persisted_campaign(monkeypatch):
    original = t1_accuracy.replay

    def fault(payload, cfg):
        result = original(payload, cfg)
        result['cash_net_pnl'] += D('.006') if 'c1' in payload['conditions'] else D('-.006')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', fault)
    reports = shared_reports()
    assert all(r['status'] == 'FAIL' and not r['net_identities']['pass'] for r in reports)
    assert all(not r['net_identities']['metrics']['predicted_cash_formula']['pass'] for r in reports)
    campaign = combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    assert campaign['status'] != 'PASS'
    assert all(not r['pass'] for r in campaign['session_net_identities'].values())


def test_n2_campaign_tolerance_cannot_admit_point_018_net_error(monkeypatch):
    with pytest.raises(ValueError, match='campaign net tolerance exceeds cash-conservation ceiling'):
        replace(tolerance(), campaign_net_absolute='.02')
    original = t1_accuracy.replay

    def fault(payload, cfg):
        result = original(payload, cfg)
        result['cash_net_pnl'] += D('.009')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', fault)
    reports = shared_reports()
    campaign = combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    assert campaign['status'] != 'PASS'
    assert campaign['completed_cash_net_pnl']['absolute_error'] == pytest.approx(D('.018'), abs=D('1e-24'))
    assert campaign['completed_cash_net_pnl']['limit'] <= D('.00001')


def test_persisted_net_flags_cannot_replace_recomputation():
    reports = shared_reports()
    for report, error in zip(reports, (D('.006'), D('-.006'))):
        report['simulation']['cash_net_pnl'] += error
        report['economics']['cash_net_pnl']['predicted'] += error
        # Leave all stored pass flags and joint statistics untouched.
    combined = combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    assert combined['status'] == 'FAIL'
    assert all(not r['pass'] for r in combined['session_net_identities'].values())


def test_persisted_campaign_tolerance_and_completed_cash_alias_are_checked():
    reports = shared_reports()
    for report in reports:
        report['tolerance']['campaign_net_absolute'] = '.02'
    with pytest.raises(ValueError, match='campaign net tolerance exceeds cash-conservation ceiling'):
        combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    reports = shared_reports()
    reports[0]['completed_cash'] = {**reports[0]['completed_cash'], 'net_pnl': D('100')}
    result = combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    assert result['status'] == 'FAIL'
    assert not result['session_net_identities']['s1']['metrics']['reported_completed_cash_alias']['pass']


@pytest.mark.spawns
def test_n4_two_raw_verified_cli_sessions_share_closing_and_funding_observations(tmp_path):
    staged = shared_raw_campaign(tmp_path)
    envelopes = []
    latency = {'kind': 'observation_to_order_ack', 'sample_count': 1, 'synthetic': True,
               'samples': [{'observed_at': at(0), 'decided_at': at(1), 'acknowledged_at': at(2)}]}
    for index, (verified, p, r, report) in enumerate(staged, 1):
        check = verify_projection(verified, r, p, report)
        assert check['status'] == check['transitions']['status'] == check['wallet_observations']['status'] == 'PASS', check
        assert report['status'] == 'PASS'
        folder = tmp_path / str(index)
        r['evidence_bundle'] = {'files': [{'role': role, 'path': item['path'].name, 'sha256': item['sha256']}
                                        for role, item in verified.items()]}
        values = {'inputs': p, 'receipts': r, 'tolerance': report['tolerance'], 'latency': latency,
                  'config': config(latency_source_sha256=digest(latency)).projection()}
        args = ['accuracy']
        for flag, key in (('inputs', 'inputs'), ('receipts', 'receipts'), ('config', 'config'),
                          ('tolerance', 'tolerance'), ('latency-evidence', 'latency')):
            path = folder / ('normalized-' + key + '.json')
            path.write_bytes(canonical(values[key]))
            args += ['--' + flag, str(path)]
        args += ['--journal', str(verified['journal']['path']), '--output', str(folder / 'session.json')]
        assert t1_cli.main(args) == 2  # Synthetic plus deliberate unsupported authority, not production PASS.
        envelope = json.loads((folder / 'session.json').read_bytes())
        assert envelope['accuracy_certificate']['raw_projection']['wallet_observations']['status'] == 'PASS'
        envelopes.append(envelope)
    assert len({r['result']['wallet_activity_source_sha256'] for r in envelopes}) == 2
    assert len({r['result']['wallet_end_cash_source_sha256'] for r in envelopes}) == 1
    first, second = (e['result']['wallet_observations'] for e in envelopes)
    assert first['period_closing'] == second['opening']
    assert first['closing'] == second['closing']
    campaign = certify_campaign(envelopes, synthetic_diagnostic=True, **OPTIONS)
    assert campaign['status'] == 'SYNTHETIC_PASS' and campaign['sessions'] == 2


def test_n4_mutated_shared_closing_native_body_is_rejected(tmp_path):
    staged = shared_raw_campaign(tmp_path)
    verified, p, r, report = staged[0]
    role = verified['wallet_observations']
    raw = json.loads(role['path'].read_bytes())
    next(s for s in raw['snapshots'] if s['id'] == 'final')['collateral_evidence']['balance'] = '0'
    role['path'].write_bytes(canonical(raw))
    role['sha256'] = digest(raw)
    for kind in ('opening', 'period_closing', 'closing'):
        r['wallet'][kind + '_observation']['source_sha256'] = role['sha256']
    r['wallet']['end_cash_source_sha256'] = role['sha256']
    with pytest.raises(ValueError, match='shared_observation/closing'):
        verify_projection(verified, r, p, report)


def test_n5_same_clock_settlement_then_redemption_accepts_distinct_observed_prefixes(tmp_path):
    verified, p, r, report = build_two_leg_raw(tmp_path / 'simultaneous', 1, separate_redemption=False)
    check = verify_projection(verified, r, p, report)
    assert report['status'] == 'PASS'
    assert check['transitions']['status'] == 'PASS', check['transitions']
    settlement = next(c for c in r['state_checkpoints'] if c['id'].startswith('settlement:'))
    redemption = next(c for c in r['state_checkpoints'] if c['id'].startswith('redemption:'))
    assert settlement['at'] == redemption['at']
    assert D(redemption['cash']) - D(settlement['cash']) == 10
    assert len(redemption['activity_prefix_ids']) == len(settlement['activity_prefix_ids']) + 1


def test_n5_missing_same_clock_activity_order_stays_unqualified(tmp_path):
    verified, p, r, report = build_two_leg_raw(tmp_path / 'ambiguous', 1, separate_redemption=False)
    role = verified['wallet']
    raw = json.loads(role['path'].read_bytes())
    next(c for c in raw['checkpoints'] if c['id'].startswith('settlement:')).pop('activity_prefix_ids')
    next(c for c in r['state_checkpoints'] if c['id'].startswith('settlement:')).pop('activity_prefix_ids')
    role['path'].write_bytes(canonical(raw))
    role['sha256'] = digest(raw)
    r['wallet']['end_cash_source_sha256'] = role['sha256']
    for point in r['wallet']['cash_events'] + r['state_checkpoints']:
        point['source_sha256'] = role['sha256']
    check = verify_projection(verified, r, p, report)
    assert check['transitions']['status'] == 'NOT QUALIFIED'
    assert 'explicit activity prefix' in check['transitions']['reason']


def test_same_clock_payments_use_observed_prefixes_without_invented_timestamps(tmp_path):
    verified, p, r, _ = build_two_leg_raw(tmp_path / 'payments', 1, separate_redemption=False)
    role = verified['wallet']
    raw = json.loads(role['path'].read_bytes())
    paid_at = r['wallet']['cash_events'][0]['at']
    other_id = r['wallet']['cash_events'][1]['id']
    r['wallet']['cash_events'][1].update(at=paid_at, finalized_at=paid_at)
    next(a for a in raw['activity'] if a['id'] == other_id).update(at=paid_at, finalized_at=paid_at)
    for points in (raw['checkpoints'], r['state_checkpoints']):
        next(c for c in points if c['id'] == 'cash:' + other_id)['at'] = paid_at
    role['path'].write_bytes(canonical(raw))
    role['sha256'] = digest(raw)
    r['wallet']['end_cash_source_sha256'] = role['sha256']
    for point in r['wallet']['cash_events'] + r['state_checkpoints']:
        point['source_sha256'] = role['sha256']
    report = accuracy_gate(p, config(), verified['journal']['path'], r, tolerance())
    check = verify_projection(verified, r, p, report)
    assert report['status'] == 'PASS' and check['transitions']['status'] == 'PASS', check
    assert len({p['at'] for p in r['state_checkpoints'] if p['id'].startswith('cash:')}) == 1


def test_authority_and_persistent_carry_stay_explicitly_unqualified(tmp_path):
    _, p, r, report = shared_raw_campaign(tmp_path)[0]
    cert = session_certificate(report, {'worktree_clean': True}, r, p, tmp_path)
    for name in ('realized_reward_sampling', 'midpoint_semantics', 'persistent_capital'):
        assert cert['components'][name]['status'] == 'NOT QUALIFIED'
        assert cert['components'][name]['evidence_required']
    assert cert['capital_scope'] == 'VERIFIED_FLAT_NONOVERLAPPING_PERIODS'
