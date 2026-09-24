"""Persistent attempt limits and frozen evidence are independent of CLI flags."""
from datetime import timedelta
import json
import os
from types import SimpleNamespace

import pytest

from tests.market.test_re1_attended import setup
from tests.market.test_mm_paid_incentive_reconciliation import evidence_fixture, add_payment, MAKER, CONDITION
from weather.market.mm_stage2_hold import write_new
from weather.market.re1_attended import SecretGuard
from weather.market.re1_evidence import campaign_root, load_prediction, reserve_attempt, payout_verdict
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


def test_ten_persistent_sessions_and_eleventh_refused(tmp_path):
    for i in range(1, 11):
        clock_time = __import__('tests.market.stage2_fakes', fromlist=['Clock']).Clock().now() + timedelta(seconds=2)
        directory, marker = reserve_attempt(tmp_path, now=clock_time, selection_sha256='a' * 64)
        session, _, clock = setup(directory)
        session.run(rehearsal_seconds=1)
        assert marker['number'] == i
    with pytest.raises(RuntimeError, match='session_cap'):
        reserve_attempt(tmp_path, now=clock.now(), selection_sha256='a' * 64)


def test_unfinished_no_post_attempt_allows_next_and_expiry(tmp_path):
    from tests.market.stage2_fakes import Clock
    now = Clock().now()
    reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)
    _, marker = reserve_attempt(tmp_path, now=now, selection_sha256='a' * 64)
    assert marker['number'] == 2 and marker['session_number'] == 1
    with pytest.raises(RuntimeError, match='campaign_expired'):
        reserve_attempt(tmp_path / 'expired', now=now + timedelta(days=10), selection_sha256='a' * 64)


def test_incomplete_acknowledgement_blocks_next_attempt(tmp_path):
    from tests.market.stage2_fakes import Clock
    directory, _ = reserve_attempt(tmp_path, now=Clock().now(), selection_sha256='a' * 64)
    session, venue, clock = setup(directory)
    def lost(request, **kwargs):
        venue.before_post(request)
        raise ConnectionError('unknown submit outcome')
    venue.submit = lost
    result = session.run()
    assert result['cleanup_ok'] and not result['fill_seen'] and not result['evidence_complete']
    with pytest.raises(RuntimeError, match='reconciliation'):
        reserve_attempt(tmp_path, now=clock.now(), selection_sha256='a' * 64)


@pytest.mark.parametrize('value,expected', [('1', 'PAID_AS_MODELLED'), ('0.2', 'PAID_DILUTED'), ('0', 'NOT_PAID'), ('0.1', 'INCONCLUSIVE')])
def test_exact_frozen_payout_thresholds(value, expected):
    prediction = {'P_many': 2, 'mode': 'live', 'evidence_complete': True, 'cleanup_ok': True, 'scoring_seen': True,
        'reward_terms_changed': False, 'visible_two_sided_minutes': 200, 'condition_id': CONDITION,
        'scope': {'maker_address': MAKER}, 'reward_day': '2026-09-01'}
    evidence = evidence_fixture()
    if value != '0': add_payment(evidence, programme='liquidity_reward', amount=value)
    accrual = {'rows': []}
    assert payout_verdict(prediction, accrual, evidence)['verdict_frozen'] == expected
    assert payout_verdict(prediction, accrual)['k'] is None
    assert payout_verdict(prediction, accrual)['verdict'] == 'INCONCLUSIVE'
    prediction['visible_two_sided_minutes'] = 179
    assert payout_verdict(prediction, accrual, evidence)['verdict_frozen'] == 'INCONCLUSIVE'


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


@pytest.mark.skipif(os.name != 'nt', reason='actual Windows token profile contract')
def test_campaign_root_cannot_be_redirected_by_environment(monkeypatch, tmp_path):
    actual = campaign_root()
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'other-profile'))
    monkeypatch.setenv('HOME', str(tmp_path / 'other-home'))
    monkeypatch.setenv('HOMEDRIVE', 'Z:')
    monkeypatch.setenv('HOMEPATH', '\\other-profile')
    assert campaign_root() == actual
    assert actual.name == '.weather-re1m-20260921'


def test_unexpected_failure_cannot_qualify_paid_result():
    prediction = {'P_many': 2, 'mode': 'live', 'evidence_complete': True, 'cleanup_ok': True, 'scoring_seen': True,
        'failure_type': 'ConnectionError', 'reward_terms_changed': False, 'visible_two_sided_minutes': 200,
        'condition_id': CONDITION, 'scope': {'maker_address': MAKER}, 'reward_day': '2026-09-01'}
    evidence = evidence_fixture()
    add_payment(evidence, programme='liquidity_reward', amount='1')
    assert payout_verdict(prediction, {'rows': []}, evidence)['verdict'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('rc,stdout', [
    (0, ''), (1, '{"host_id":"fixture","principal_id":"fixture"}'),
    (0, '{"host_id":"fixture"}'), (0, '{"principal_id":"fixture"}'),
    (0, 'not JSON'), (0, '[]'), (0, 'null'), (0, '   '),
])
def test_host_identity_spawn_and_failed_child_diagnostic(monkeypatch, rc, stdout):
    from weather.market import re1_evidence as evidence
    calls = []
    stderr = 'running scripts is disabled on this system' + '!' * 220
    def child(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    # Replace the module binding, not the process-wide os.name (also runs on Linux).
    monkeypatch.setattr(evidence, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(evidence.subprocess, 'run', child)
    with pytest.raises(RuntimeError) as caught:
        with evidence.live_mutex():
            pytest.fail('invalid identity admitted')
    assert str(caught.value) == f'host_identity_query_failed: rc={rc} stderr={stderr[:200]}'
    args, kwargs = calls[0]
    assert args[:6] == ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command']
    assert len(args) == 8 and args[-1] == str(evidence.REPO_ROOT)
    assert 'Get-WeatherExecutionHostId' in args[6]
    assert kwargs == {'capture_output': True, 'text': True, 'timeout': 20}


def test_valid_host_query_still_enforces_assignment(tmp_path, monkeypatch):
    from weather.market import re1_evidence as evidence
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/international_live_execution_host.json').write_text(json.dumps({
        'assignment_status': 'ASSIGNED', 'dedicated_capture_execution_host_id': 'capture',
        'active_portable_execution_host_id': 'portable', 'active_portable_execution_principal_id': 'owner',
    }))
    monkeypatch.setattr(evidence, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(evidence, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(evidence.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"host_id":"capture","principal_id":"owner"}', stderr=''))
    with pytest.raises(RuntimeError, match='wrong_workstation_or_principal'):
        with evidence.live_mutex():
            pytest.fail('capture host admitted')


def test_re1_third_party_imports_have_declared_dependencies():
    """Resolve imports against core/live declarations and their required dependencies."""
    import ast
    from importlib import metadata
    import re
    import sys
    import tomllib
    from packaging.requirements import Requirement
    from weather.paths import REPO_ROOT

    def normalized(name):
        return re.sub(r'[-_.]+', '-', name).lower()

    project = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    core = project['dependencies']
    requirements = (REPO_ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
    assert 'python-dotenv==1.2.3' in core and 'python-dotenv==1.2.3' in requirements
    pending = [Requirement(item) for item in core + project['optional-dependencies']['live']]
    declared = set()
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
            continue
        name = normalized(requirement.name)
        if name in declared:
            continue
        declared.add(name)
        pending.extend(Requirement(item) for item in metadata.requires(requirement.name) or [])
    providers = metadata.packages_distributions()
    missing = []
    for path in sorted((REPO_ROOT / 'src/weather/market').glob('re1_*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else [])
            for name in names:
                top = name.split('.')[0]
                if top in sys.stdlib_module_names or top == 'weather':
                    continue
                distributions = {normalized(item) for item in providers.get(top, [])}
                if not distributions & declared:
                    missing.append(f'{path.name}:{node.lineno}: {top} -> {sorted(distributions)}')
    assert not missing, 'Undeclared RE-1 imports: ' + '; '.join(missing)
