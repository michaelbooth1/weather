"""Guards: T035 RECHECK2 R1/R2 and B030; endpoint cash ceilings and honest F0 gaps.

Synthetic native observations and journals only, dated October 12-14.
"""
from copy import deepcopy
from decimal import Decimal as D
import json

import pytest

from tests.backtesting.t1_fixtures import config, tolerance
from tests.backtesting.t1_raw_fixtures import shared_raw_campaign
from tests.backtesting.test_t1_qualification import shared_reports, two_leg_session
from weather.backtesting import t1_accuracy
from weather.backtesting.t1_accuracy import accuracy_gate, combine_session_gates
from weather.backtesting.t1_net import net_checks
from weather.backtesting.t1_provenance import session_certificate
from weather.backtesting.t1_raw_projection import verify_projection
from weather.backtesting.t1_types import canonical, digest

OPTIONS = dict(min_sessions=2, min_filled_orders=4, min_paid_reward='1', expected_session_ids=['s1', 's2'])


@pytest.mark.parametrize('closing_units', [9, 4])
@pytest.mark.parametrize('net_field', ['cash', 'economic'])
def test_r2_composed_allowances_cannot_exceed_independent_net_ceiling(tmp_path, monkeypatch, closing_units, net_field):
    staged = shared_raw_campaign(tmp_path)
    original = t1_accuracy.replay

    def faulty(p, cfg):
        result = original(p, cfg)
        for key in (('cash_net_pnl',) if net_field == 'cash' else ('raw_net_pnl', 'economic_net_pnl', 'stressed_net_pnl')):
            result[key] += D('.0000045')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', faulty)
    reports, projections = [], []
    for verified, p, r, _ in staged:
        role = verified['wallet_observations']
        observations = json.loads(role['path'].read_bytes())
        final = next(s for s in observations['snapshots'] if s['id'] == 'final')
        final['collateral_evidence']['balance'] = str(D(final['collateral_evidence']['balance']) - closing_units)
        role['path'].write_bytes(canonical(observations))
        role['sha256'] = digest(observations)
        wallet_role = verified['wallet']
        wallet = json.loads(wallet_role['path'].read_bytes())
        wallet['closing']['collateral_evidence'] = deepcopy(final['collateral_evidence'])
        wallet_role['path'].write_bytes(canonical(wallet))
        wallet_role['sha256'] = digest(wallet)
        w = r['wallet']
        w['end_cash'] = str(D(w['end_cash']) - D(closing_units) / 1_000_000)
        for key in ('opening', 'period_closing', 'closing'):
            w[key + '_observation']['source_sha256'] = role['sha256']
        w['end_cash_source_sha256'], w['activity_source_sha256'] = role['sha256'], wallet_role['sha256']
        for row in w['cash_events'] + r['state_checkpoints']:
            row['source_sha256'] = wallet_role['sha256']
        report = accuracy_gate(p, config(), verified['journal']['path'], r,
                               tolerance(receipt_reconciliation_absolute='.00001'))
        projections.append(verify_projection(verified, r, p, report))
        reports.append(report)
    assert all(c['status'] == c['transitions']['status'] == c['wallet_observations']['status'] == 'PASS' for c in projections)
    assert all(r['net_identities']['metrics']['cash_prediction_accuracy']['pass'] for r in reports)
    assert all(r['net_identities']['metrics']['actual_cash_balance']['pass'] for r in reports)
    assert all(r['status'] == ('PASS' if closing_units == 4 else 'FAIL') for r in reports)
    campaign = combine_session_gates(json.loads(canonical(reports)), **OPTIONS)
    assert campaign['completed_cash_net_pnl']['pass'] and campaign['actual_campaign_cash_identity']['pass']
    bridge = campaign['predicted_campaign_' + net_field + '_bridge']
    observed_profit = reports[-1]['wallet_end_cash'] - reports[0]['capital_period']['opening_cash']
    assert bridge['actual'] == observed_profit
    primary = 'completed_cash_net_pnl' if net_field == 'cash' else 'economic_net_pnl'
    assert bridge['absolute_error'] == abs(campaign[primary]['predicted'] - observed_profit)
    assert bridge['absolute_error'] > bridge['limit'] == D('.00001')
    if closing_units == 9:
        assert bridge['absolute_error'] == pytest.approx(D('.000017238095238095238095238'), abs=D('1e-26'))
    assert not bridge['pass'] and campaign['status'] != 'PASS'


def test_reported_net_alias_cannot_compose_another_cash_allowance():
    r = shared_reports()[0]
    r['tolerance']['receipt_reconciliation_absolute'] = '.00001'
    r['actual_accounts']['cash_balance_net_pnl'] -= D('.000006')
    r['actual_accounts']['balance_net_pnl'] -= D('.000006')
    r['economics']['cash_net_pnl']['predicted'] += D('.000006')
    result = net_checks(r['simulation'], r['actual_accounts'], r['economics'], r['rewards']['actual'],
                        r['rebates']['actual'], r['capital_period']['opening_cash'], r['tolerance'])
    assert result['metrics']['cash_prediction_balance_bridge']['pass']
    assert result['metrics']['reported_cash_net_pnl']['pass']
    assert not result['metrics']['reported_balance_bridge_cash_net_pnl']['pass']
    assert not result['pass']


def test_r1_coherent_primitive_and_net_overstatement_still_fails(monkeypatch):
    allocation = shared_reports()[0]['reward_allocation']
    original = t1_accuracy.replay

    def faulty(p, cfg):
        result = original(p, cfg)
        for key in ('cash_redemptions_pusd', 'venue_payout', 'raw_net_pnl', 'economic_net_pnl',
                    'cash_net_pnl', 'cash_available', 'wallet_end_cash', 'stressed_net_pnl'):
            result[key] += D('.000011')
        return result

    monkeypatch.setattr(t1_accuracy, 'replay', faulty)
    p, raw, r = two_leg_session(1, allocation)
    report = accuracy_gate(p, config(), raw, r, tolerance(receipt_reconciliation_absolute='.00001'))
    assert report['net_identities']['metrics']['predicted_cash_formula']['pass']
    assert not report['net_identities']['metrics']['cash_prediction_balance_bridge']['pass']
    assert report['status'] == 'FAIL' and report['joint_error']['pass']


@pytest.mark.spawns
def test_partial_cli_certificate_gaps_match_native_evidence_without_false_diagnoses(tmp_path):
    from tests.backtesting.test_t1_cli import test_native_f0_intake_cli_accepts_empty_measurement_and_receipts_with_gap_flags

    test_native_f0_intake_cli_accepts_empty_measurement_and_receipts_with_gap_flags(tmp_path)
    envelope = json.loads((tmp_path / 'result.json').read_bytes())
    result, certificate = envelope['result'], envelope['accuracy_certificate']
    assert certificate['status'] == 'NOT QUALIFIED' and certificate['claim'] == 'PARTIAL_INTAKE_NOT_CERTIFIABLE'
    assert certificate['gaps'] == sorted(result['gap_flags'])
    assert certificate['gap_flags'] == result['gap_flags']
    assert certificate['recorder_pin'] == result['recorder_pin']
    assert 'synthetic_receipts' in certificate['provenance_gaps']
    assert {'cash_positions', 'reward_payment', 'settlement_redemption', 'provenance'} <= set(certificate['gaps'])
    assert all('changed' not in key and 'exceeds' not in key and 'unreviewed' not in key for key in certificate['gaps'])
    assert result['cash'] is result['net_pnl'] is result['end_positions'] is None
    assert certificate['trial_can_pass'] is False
    assert 'normalized_accuracy_certification' in certificate['not_evaluated']
    result['supplemental_accuracy'] = {'status': 'PASS', 'metrics_pass': True}
    supplemented = session_certificate(result, envelope['code'], {}, {}, tmp_path)
    assert supplemented['status'] == 'NOT QUALIFIED' and supplemented['gap_flags'] == result['gap_flags']


def test_complete_report_still_diagnoses_actually_changed_inputs(tmp_path):
    allocation = shared_reports()[0]['reward_allocation']
    p, raw, r = two_leg_session(1, allocation)
    report = accuracy_gate(p, config(), raw, r, tolerance())
    r['wallet']['end_cash'] = '0'
    certificate = session_certificate(report, {'worktree_clean': True}, r, p, tmp_path)
    assert 'arithmetic_inputs_changed_before_certification' in certificate['gaps']
