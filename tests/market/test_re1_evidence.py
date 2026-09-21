"""Persistent attempt limits and frozen evidence are independent of CLI flags."""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from tests.market.test_re1_attended import setup
from tests.market.test_mm_paid_incentive_reconciliation import evidence_fixture, add_payment, MAKER, CONDITION
from weather.market.mm_stage2_hold import write_new
from weather.market.re1_attended import SecretGuard
from weather.market.re1_evidence import load_prediction, reserve_attempt, payout_verdict
from weather.market.re1_attended_cli import parser, run_collect, confirmation
from weather.market.re1_transport import load_owner_credentials, OwnerVenue


def test_prediction_replay_and_tamper_refusal(tmp_path):
    session, _, clock = setup(tmp_path)
    result = session.run(rehearsal_seconds=120)
    prediction = tmp_path / 'prediction.json'
    now = clock.now() + timedelta(days=1)
    assert load_prediction(prediction, now=now) == result
    result['P_many'] += 1
    prediction.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='prediction_totals'):
        load_prediction(prediction, now=now)


def test_three_persistent_sessions_and_fourth_refused(tmp_path):
    for i in range(1, 4):
        clock_time = __import__('tests.market.stage2_fakes', fromlist=['Clock']).Clock().now() + timedelta(seconds=2)
        directory, marker = reserve_attempt(tmp_path, now=clock_time, selection_sha256='a' * 64)
        session, _, clock = setup(directory)
        session.run(rehearsal_seconds=1)
        assert marker['number'] == i
    with pytest.raises(RuntimeError, match='three_session_cap'):
        reserve_attempt(tmp_path, now=clock.now(), selection_sha256='a' * 64)


def test_unfinished_attempt_blocks_next_and_expiry(tmp_path):
    from tests.market.stage2_fakes import Clock
    now = Clock().now()
    reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)
    with pytest.raises((ValueError, OSError, RuntimeError)):
        reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)
    with pytest.raises(RuntimeError, match='campaign_expired'):
        reserve_attempt(tmp_path / 'expired', now=now + timedelta(days=10), selection_sha256='a' * 64)


@pytest.mark.parametrize('value,expected', [('1', 'PAID_AS_MODELLED'), ('0.2', 'PAID_DILUTED'), ('0', 'NOT_PAID'), ('0.1', 'INCONCLUSIVE')])
def test_exact_frozen_payout_thresholds(value, expected):
    prediction = {'P_many': 2, 'mode': 'live', 'evidence_complete': True, 'cleanup_ok': True, 'scoring_seen': True,
        'reward_terms_changed': False, 'visible_two_sided_minutes': 200, 'condition_id': CONDITION,
        'scope': {'maker_address': MAKER}, 'reward_day': '2026-09-01'}
    evidence = evidence_fixture()
    if value != '0': add_payment(evidence, programme='liquidity_reward', amount=value)
    accrual = {'rows': []}
    assert payout_verdict(prediction, accrual, evidence)['verdict'] == expected
    assert payout_verdict(prediction, accrual)['k'] is None
    assert payout_verdict(prediction, accrual)['verdict'] == 'INCONCLUSIVE'
    prediction['visible_two_sided_minutes'] = 179
    assert payout_verdict(prediction, accrual, evidence)['verdict'] == 'INCONCLUSIVE'


def test_collect_requires_prediction_before_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', lambda *_: pytest.fail('loaded credentials'))
    with pytest.raises((ValueError, OSError, RuntimeError)):
        run_collect(SimpleNamespace(prediction=tmp_path / 'absent', payment_evidence=None))


def test_rehearsal_cannot_load_credentials():
    with pytest.raises(RuntimeError, match='credentials_forbidden'):
        load_owner_credentials('rehearse')


def test_no_live_cli_limit_or_confirmation_override():
    for flag in ('--yes', '--confirmation', '--size', '--minutes', '--host', '--sessions', '--output'):
        with pytest.raises(SystemExit): parser().parse_args(['live', flag, '999'])


def test_redirected_confirmation_is_refused(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(RuntimeError, match='owner_terminal_required'):
        confirmation({}, SecretGuard(), reader=lambda: pytest.fail('read redirected confirmation'))


def test_readonly_venue_has_no_submit_cancel_or_heartbeat():
    venue = object.__new__(OwnerVenue)
    venue.readonly = True
    for action in (lambda: venue.submit({}, checkpoint=lambda: None), lambda: venue.cancel('x'), venue.cancel_all, venue.heartbeat):
        with pytest.raises(RuntimeError, match='read_only'): action()


def test_accrual_keeps_candidate_assets_and_uses_reported_rate():
    from weather.market.re1_transport import ASSETS
    prediction = {'P_many': 2, 'mode': 'live', 'evidence_complete': True, 'cleanup_ok': True, 'scoring_seen': True,
        'reward_terms_changed': False, 'visible_two_sided_minutes': 200, 'condition_id': CONDITION,
        'scope': {'maker_address': MAKER}, 'reward_day': '2026-09-01'}
    rows = [{'condition_id': CONDITION, 'maker_address': MAKER, 'date': '2026-09-01T00:00:00Z',
             'asset_address': asset, 'earnings': '1', 'asset_rate': rate}
            for asset, rate in zip(ASSETS, ['1', '0.9'])]
    result = payout_verdict(prediction, {'rows': rows})
    assert result['accrued'] == '1.9' and result['k_accrued'] == '0.95'
    assert len(result['earnings_by_asset']) == 2 and result['paid'] is None
    with pytest.raises(ValueError, match='duplicate'):
        payout_verdict(prediction, {'rows': rows + rows[:1]})
