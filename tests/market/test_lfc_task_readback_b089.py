"""Guards: B089 bounded non-money Scheduler gaps never become disable or ambiguity."""
import json
from types import SimpleNamespace
import subprocess

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market import lfc_campaign_release as release
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority
from weather.market.lfc_campaign_proof import local_money_proof
from weather.market.mm_stage2_hold import HoldEnd, digest


@pytest.fixture(autouse=True)
def owned_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def response(*, enabled=True, **changes):
    return SimpleNamespace(returncode=0, stdout=json.dumps({
        'schema_version': 'lfc_campaign_task_read_v0.1', 'definition_valid': True,
        'enabled': enabled, 'release_sha256': 'a' * 64, **changes}))


@pytest.mark.parametrize('fault', ['timeout', 'exit', 'json', 'schema', 'enabled_type', 'missing'])
def test_transport_and_schema_faults_are_typed_and_keep_five_second_bound(tmp_path, monkeypatch, fault):
    def read(command, **kwargs):
        assert kwargs['timeout'] == 5
        if fault == 'timeout':
            raise subprocess.TimeoutExpired('read-only fixture', 5)
        if fault == 'exit':
            return SimpleNamespace(returncode=1, stdout='', stderr='DO_NOT_EXPORT')
        if fault == 'json':
            return SimpleNamespace(returncode=0, stdout='DO_NOT_EXPORT not JSON')
        if fault == 'schema':
            return response(schema_version='wrong')
        if fault == 'enabled_type':
            return response(enabled=1)
        return SimpleNamespace(returncode=0, stdout='{}')
    monkeypatch.setattr(release.subprocess, 'run', read)
    with pytest.raises(RuntimeError, match='campaign_task_readback_') as caught:
        release.task_enabled({}, tmp_path / 'synthetic.json', 'a' * 64)
    assert type(caught.value).__name__ == 'TaskReadbackUnavailable'
    assert 'DO_NOT_EXPORT' not in str(caught.value)


@pytest.mark.parametrize('fields', [{'release_sha256': 'b' * 64}, {'definition_valid': False}])
def test_proven_binding_change_never_enters_transient_fallback(tmp_path, monkeypatch, fields):
    runtime = runtime_at(tmp_path)
    runtime.state.ledger.record('session_start', session_id='active')
    runtime._read_task_enabled = lambda: release.task_enabled({}, tmp_path / 'synthetic.json', 'a' * 64)
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **k: response())
    assert runtime.task_enabled()
    runtime.clock.sleep(60)
    monkeypatch.setattr(release.subprocess, 'run', lambda *a, **k: response(**fields))
    with pytest.raises(RuntimeError, match='campaign_task_readback_invalid') as caught:
        runtime.task_enabled()
    assert type(caught.value) is RuntimeError
    assert runtime._task_failures == 0
    assert not list((runtime.state.root / 'task-readback-gaps').glob('*.json'))


@pytest.mark.parametrize('prior', [False, True])
def test_admission_failure_is_strict_even_with_an_older_success(tmp_path, monkeypatch, prior):
    runtime = runtime_at(tmp_path)
    runtime._read_task_enabled = lambda: release.task_enabled({}, tmp_path / 'synthetic.json', 'a' * 64)
    if prior:
        monkeypatch.setattr(release.subprocess, 'run', lambda *a, **k: response())
        assert runtime.task_enabled()
        runtime.clock.sleep(60)
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired('read-only fixture', 5)
    monkeypatch.setattr(release.subprocess, 'run', timeout)
    with pytest.raises(TransientPrecheck, match='campaign_task_readback_unavailable'):
        runtime.task_enabled()
    assert not runtime.state.ledger.autostart_claims and not runtime.state.incidents()
    assert len(list((runtime.state.root / 'task-readback-gaps').glob('*.json'))) == 1


def test_first_live_read_without_any_proof_cannot_enable_the_session(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path)
    runtime.state.ledger.record('session_start', session_id='starting')
    def timeout():
        raise subprocess.TimeoutExpired('read-only fixture', 5)
    runtime._read_task_enabled = timeout
    with pytest.raises(HoldEnd) as caught:
        runtime.task_enabled()
    assert caught.value.reason == 'campaign_task_readback_unavailable'
    assert runtime._task_checked is None and runtime._task_value is False


def test_initial_tick_read_failure_displays_deferred_without_an_incident(tmp_path, monkeypatch, capsys):
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_control import latest_control
    def unavailable(*args):
        raise TransientPrecheck('campaign_task_readback_unavailable')
    monkeypatch.setattr(cli, 'load_release', unavailable)
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    assert cli.main(['tick', '--release', str(tmp_path / 'unused.json'), '--release-sha256', 'a' * 64]) == 1
    row = latest_control(tmp_path / 'control')
    assert row['phase'] == 'DEFERRED' and row['reason'] == 'campaign_task_readback_unavailable'
    assert row.get('incident') is not True
    assert 'INCIDENT' not in capsys.readouterr().out


def wire_runtime(controller, account, status, ledger, clock, tmp_path):
    path = tmp_path / 'campaign.json'
    path.write_text(json.dumps({**controller.policy.raw, 'enabled': True}))
    runtime = Runtime(state=account.state, pilot_root=tmp_path, policy_path=path, release={},
                      clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: True,
                      hold_path=tmp_path / 'own-hold', heavy_hold_path=tmp_path / 'manual-hold')
    runtime.lease = SimpleNamespace(check=lambda: None)
    runtime._task_status = status
    runtime.notify_control = lambda row: None
    authority = ScheduledAuthority(runtime, account.claim, controller.entry, controller.policy, {'baseline': {}})
    def check():
        account.checkpoint()
        authority.check()
    status.checkpoint_hook = check
    status.resync_hook = authority.resync
    return runtime, authority


@pytest.mark.parametrize('fault,failures', [('timeout', 1), ('timeout', 3), ('exit', 1), ('json', 1), ('disabled', 0)])
def test_live_readback_gap_through_cancels_private_proof_and_campaign_close(tmp_path, monkeypatch, fault, failures):
    from tests.market.test_lfc_f2_controller import setup
    controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
    runtime, authority = wire_runtime(controller, account, status, ledger, clock, tmp_path)
    reads, failed = [], 0
    def native_read(command, **kwargs):
        nonlocal failed
        assert kwargs['timeout'] == 5
        reads.append(clock.monotonic())
        if len(reads) > 1 and fault == 'disabled':
            return response(enabled=False)
        if len(reads) > 1 and failed < failures:
            failed += 1
            clock.sleep(5)  # Full timeout latency, with matching wall and monotonic clocks.
            if fault == 'timeout':
                raise subprocess.TimeoutExpired('read-only fixture', 5)
            if fault == 'exit':
                return SimpleNamespace(returncode=1, stdout='', stderr='DO_NOT_EXPORT')
            return SimpleNamespace(returncode=0, stdout='DO_NOT_EXPORT invalid JSON')
        return response()
    monkeypatch.setattr(release.subprocess, 'run', native_read)
    runtime._read_task_enabled = lambda: release.task_enabled({}, tmp_path / 'synthetic.json', 'a' * 64)
    result = controller.run()
    expected = ('campaign_task_readback_unavailable' if failures == 3 else
                'owner_campaign_disabled' if fault == 'disabled' else 'fixed_end')
    assert result['reason'] == expected and result['failure_type'] is None, result
    assert result['unknown_submit'] is False and result['cancellation_ok'] and result['inventory_proven']
    assert not ledger.unresolved_legs() and account.open_orders() == []
    assert result['post_count'] == 4 and all(raw.cancellations for raw in account.raws)
    assert not account.state.incidents(), 'Five-second reads must not trip the 15-second clock guard'
    if failures == 1:
        assert 25 <= reads[2] - reads[1] < 35, reads  # Twenty seconds after the five-second failed read.
        assert runtime._task_failures == 0
    if failures == 3:
        assert len(reads) == 4 and clock.monotonic() <= 125  # Fixed sixty-second tolerance from the first failure.
    outcome = status.finish(success=result['cleanup_ok'])
    gaps = outcome.get('task_readback_gaps', [])
    assert len(gaps) == failures
    assert [row['consecutive_failures'] for row in gaps] == list(range(1, failures + 1))
    assert 'DO_NOT_EXPORT' not in json.dumps(outcome)
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                              attempt_id=account.claim['attempt_id'], outcome=outcome)
    assert proof['complete'] and proof['unknown_submit'] is False, proof
    assert ('campaign_task_readback_unavailable' in proof['explained_gaps']) is bool(failures)
    # Exercise the real result persistence and campaign latch/close path. Only
    # the external account snapshot proof is inert; private originals stay real.
    saved = runtime.session_result(account.claim, status, outcome, 0 if result['cleanup_ok'] else 1)
    assert saved['local_money_proof']['complete'] and saved['unknown_submit'] is False
    runtime.save_result(account.claim, saved)
    snapshot = {'complete': True, 'open_orders': [], 'fixture_only': True}
    monkeypatch.setattr(runtime, 'read_account', lambda: snapshot)
    def account_proof(current_ledger, read):
        assert not current_ledger.unresolved_legs() and account.open_orders() == []
        return {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
                'money_contradiction': False, 'read_sha256': digest(read),
                'ledger_head_sha256': current_ledger.previous, 'observed_at_utc': clock.now().isoformat()}
    monkeypatch.setattr(runtime, 'core_proof', account_proof)
    from weather.market import lfc_f2_economics
    monkeypatch.setattr(lfc_f2_economics, 'publish_supplements', lambda runtime: None)
    campaign = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock, control_root=runtime.control_root)
    assert campaign.pending()
    assert not runtime.state.incidents() and not runtime.state.pending()
    assert (runtime.state.root / 'closed' / (account.claim['attempt_id'] + '.json')).exists()
