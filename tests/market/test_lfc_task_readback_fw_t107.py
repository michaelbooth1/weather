"""Guards: T107 paced control gaps, pre-first-order admission, and fatal bindings."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at, account_read
from tests.market.test_lfc_task_readback_b089 import wire_runtime
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import ScheduledAuthority
from weather.market.lfc_campaign_release import TaskReadbackUnavailable
from weather.market.mm_stage2_hold import HoldEnd


@pytest.fixture(autouse=True)
def owned_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def test_successful_control_gap_preserves_every_research_flag(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_controller import setup
    controller, account, status, ledger, clock = setup(tmp_path, enrolled=True)
    runtime, _ = wire_runtime(controller, account, status, ledger, clock, tmp_path)
    calls = []
    def read():
        calls.append(clock.monotonic())
        if len(calls) == 2:
            raise TaskReadbackUnavailable('timeout')
        return True
    runtime._read_task_enabled = read
    result = controller.run()
    assert result['reason'] == 'fixed_end' and result['failure_type'] is None
    assert result['evidence_complete'] and result['cleanup_ok']
    assert not controller.evidence_failed and not controller.account_evidence_faults
    status.open_rows, status.reason = controller.open_rows, result['reason']
    outcome = status.finish(success=result['cleanup_ok'])
    assert outcome['task_readback_gaps'] and outcome['evidence_complete']
    saved = runtime.session_result(account.claim, status, outcome, 0)
    assert saved['local_money_proof']['complete']
    assert saved['evidence_complete']
    runtime.save_result(account.claim, saved)
    from weather.market.mm_stage2_hold import digest
    from weather.market.lfc_campaign import CampaignCoordinator
    snapshot = {'complete': True, 'open_orders': [], 'synthetic_only': True}
    monkeypatch.setattr(runtime, 'read_account', lambda: snapshot)
    def proof(current_ledger, read):
        assert not current_ledger.unresolved_legs() and account.open_orders() == []
        return {'money_accounting_complete': True, 'cleanup_proven': True,
                'unknown_submit': False, 'money_contradiction': False,
                'read_sha256': digest(read), 'ledger_head_sha256': current_ledger.previous,
                'observed_at_utc': clock.now().isoformat()}
    monkeypatch.setattr(runtime, 'core_proof', proof)
    from weather.market import lfc_f2_economics
    monkeypatch.setattr(lfc_f2_economics, 'publish_supplements', lambda runtime: None)
    campaign = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock, control_root=runtime.control_root)
    assert campaign.pending()
    closed = runtime.state.read(runtime.state.root / 'closed' / (account.claim['attempt_id'] + '.json'))
    assert closed['proof']['research_evidence_complete']
    assert not runtime.state.incidents() and not runtime.state.pending()


def test_retry_spacing_and_hard_tolerance_never_renew_a_stale_proof(tmp_path):
    runtime = runtime_at(tmp_path)
    runtime.state.ledger.record('session_start', session_id='active')
    calls = []
    def read():
        calls.append(runtime.clock.monotonic())
        if len(calls) > 1:
            raise TaskReadbackUnavailable('failed')
        return True
    runtime._read_task_enabled = read
    assert runtime.task_enabled()
    runtime.clock.sleep(60)
    first = runtime.clock.monotonic()
    assert runtime.task_enabled()
    for seconds in range(1, 61):
        runtime.clock.sleep(1)
        if seconds < 60:
            assert runtime.task_enabled()
        else:
            with pytest.raises(HoldEnd) as caught:
                runtime.task_enabled()
            assert caught.value.reason == 'campaign_task_readback_unavailable'
    assert calls == [0, first, first + 20, first + 40]
    assert runtime._task_failures == 3


def test_paced_success_resets_the_failure_window(tmp_path):
    runtime = runtime_at(tmp_path)
    runtime.state.ledger.record('session_start', session_id='active')
    values = iter([True, TaskReadbackUnavailable('timeout'), True])
    def read():
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value
    runtime._read_task_enabled = read
    assert runtime.task_enabled()
    runtime.clock.sleep(60)
    assert runtime.task_enabled()
    runtime.clock.sleep(19)
    assert runtime.task_enabled() and runtime._task_failures == 1
    runtime.clock.sleep(1)
    assert runtime.task_enabled() and runtime._task_failures == 0
    runtime.clock.sleep(59)
    assert runtime.task_enabled()


def test_paced_false_is_immediate_and_an_unavailable_read_cannot_enable_it(tmp_path):
    runtime = runtime_at(tmp_path)
    runtime.state.ledger.record('session_start', session_id='active')
    values = iter([True, TaskReadbackUnavailable('failed'), False, TaskReadbackUnavailable('failed')])
    def read():
        value = next(values)
        if isinstance(value, Exception):
            raise value
        return value
    runtime._read_task_enabled = read
    assert runtime.task_enabled()
    runtime.clock.sleep(60)
    assert runtime.task_enabled()
    runtime.clock.sleep(20)
    assert runtime.task_enabled() is False and runtime._task_failures == 0
    runtime.clock.sleep(60)
    assert runtime.task_enabled() is False and runtime._task_failures == 1


def test_a_later_strict_admission_can_recover_without_a_stale_enable(tmp_path):
    from weather.market.lfc_campaign import TransientPrecheck
    runtime = runtime_at(tmp_path)
    def failed():
        raise TaskReadbackUnavailable('failed')
    runtime._read_task_enabled = failed
    with pytest.raises(TransientPrecheck, match='campaign_task_readback_unavailable'):
        runtime.task_enabled()
    runtime.clock.sleep(61)
    runtime._read_task_enabled = lambda: True
    assert runtime.task_enabled() and runtime._task_failures == 0


def test_control_gap_does_not_clear_real_faults_and_failed_write_propagates(tmp_path, monkeypatch):
    from tests.market.test_lfc_f2_controller import setup
    controller, _, _, _, _ = setup(tmp_path, enrolled=True)
    controller.evidence_failed = True
    controller.account_evidence_faults.add('sample_scoring')
    gap = {'readback_reason': 'timeout', 'consecutive_failures': 1, 'at_utc': controller.clock.now().isoformat()}
    controller.note_task_readback_gap(gap)
    assert controller.evidence_failed and controller.account_evidence_faults == {'sample_scoring'}
    def failed(*args, **kwargs):
        raise OSError('synthetic journal failure')
    monkeypatch.setattr(controller.journal, 'record', failed)
    with pytest.raises(OSError, match='synthetic journal failure'):
        controller.note_task_readback_gap(gap)
    assert len(controller.task_readback_gaps) == 1


@pytest.mark.parametrize('session_created', [False, True])
def test_claimed_pre_order_check_retries_instead_of_burning_the_date(tmp_path, session_created):
    runtime = runtime_at(tmp_path)
    policy = parse_policy(policy_row())
    entry = policy.entries[0]
    claim = runtime.state.claim(entry, policy, runtime.clock.now())
    if session_created:
        runtime.state.ledger.record('session_start', session_id='starting', autostart_attempt_id=claim['attempt_id'])
    runtime.lease = SimpleNamespace(check=lambda: None)
    runtime.clock.sleep(60)
    prepared = {'baseline': {}, 'account_read': account_read(runtime),
                'expires_utc': (runtime.clock.now() + timedelta(seconds=120)).isoformat()}
    authority = ScheduledAuthority(runtime, claim, entry, policy, prepared)
    calls = []
    def read():
        calls.append(runtime.clock.monotonic())
        if len(calls) == 1:
            raise TaskReadbackUnavailable('timeout')
        return True
    runtime._read_task_enabled = read
    authority.check(starting=True)
    assert len(calls) == 2 and calls[1] - calls[0] >= 20
    assert not runtime.state.incidents() and not runtime.state.ledger.autostart_results
    assert len(runtime.state.ledger.autostart_claims) == 1
    assert not runtime.state.ledger.unacknowledged_intents()


def test_claimed_pre_order_persistent_failure_is_clean_and_bounded(tmp_path):
    runtime = runtime_at(tmp_path)
    policy = parse_policy(policy_row())
    entry = policy.entries[0]
    claim = runtime.state.claim(entry, policy, runtime.clock.now())
    runtime.lease = SimpleNamespace(check=lambda: None)
    prepared = {'baseline': {}, 'account_read': account_read(runtime),
                'expires_utc': (runtime.clock.now() + timedelta(seconds=120)).isoformat()}
    authority = ScheduledAuthority(runtime, claim, entry, policy, prepared)
    def failed():
        raise TaskReadbackUnavailable('failed')
    runtime._read_task_enabled = failed
    start = runtime.clock.monotonic()
    with pytest.raises(HoldEnd) as caught:
        authority.check(starting=True)
    assert caught.value.reason == 'campaign_task_readback_unavailable'
    assert 60 <= runtime.clock.monotonic() - start < 66
    assert not runtime.state.incidents() and not runtime.state.ledger.unacknowledged_intents()


def test_claimed_initial_checkpoint_reaches_run_session_result_and_closure(tmp_path, monkeypatch):
    from dataclasses import replace
    import hashlib
    import json
    from tests.market.test_lfc_f2_controller import setup
    from weather.market import lfc_f2_runtime, lfc_f2_evidence, lfc_f2_economics
    from weather.market.lfc_campaign import CampaignCoordinator
    from weather.market.mm_stage2_hold import digest
    controller, account, previous_status, ledger, clock = setup(tmp_path, enrolled=True)
    runtime, _ = wire_runtime(controller, account, previous_status, ledger, clock, tmp_path)
    raw = runtime.policy_path.read_bytes()
    policy = replace(controller.policy, source_sha256=hashlib.sha256(raw).hexdigest())
    runtime.wrapper_launch = {'deadline_utc': (controller.entry.session_end(controller.entry.end) + timedelta(minutes=30)).isoformat(),
                              'policy_bytes_sha256': policy.source_sha256}
    runtime.notify_control = lambda row: None
    original = lfc_f2_evidence.F2Status
    class OwnedStatus(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.stop_file = tmp_path / 'OWNED-STOP-FIXTURE'
    monkeypatch.setattr(lfc_f2_evidence, 'F2Status', OwnedStatus)
    calls = []
    def native():
        calls.append(clock.monotonic())
        if len(calls) == 1:
            raise TaskReadbackUnavailable('timeout')
        return True
    runtime._task_checked, runtime._task_value = None, False
    runtime._read_task_enabled = native
    def session_stub(adapter, authority, status):
        assert len(calls) == 2 and calls[1] - calls[0] == 20
        assert not adapter.state.ledger.unacknowledged_intents()
        controller.status = status
        status.bind(controller.session_id, directory=controller.directory, selection={}, ledger=ledger)
        status.session = controller
        outcome = controller.run()
        status.reason, status.open_rows = outcome['reason'], controller.open_rows
        assert outcome['cleanup_ok'] and outcome['post_count'] == 4
        return 0
    monkeypatch.setattr(lfc_f2_runtime, 'run_live', session_stub)
    result = runtime.run_session(account.claim, controller.entry, policy,
                                 {'baseline': {}, 'account_read': account_read(runtime),
                                  'expires_utc': (clock.now() + timedelta(seconds=120)).isoformat()})
    assert result['outcome']['cleanup_ok'] and result['unknown_submit'] is False
    assert result['local_money_proof']['complete']
    snapshot = {'complete': True, 'open_orders': []}
    monkeypatch.setattr(runtime, 'read_account', lambda: snapshot)
    monkeypatch.setattr(runtime, 'core_proof', lambda current, read: {
        'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
        'money_contradiction': False, 'read_sha256': digest(read),
        'ledger_head_sha256': current.previous, 'observed_at_utc': clock.now().isoformat()})
    monkeypatch.setattr(lfc_f2_economics, 'publish_supplements', lambda runtime: None)
    campaign = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=clock, control_root=runtime.control_root)
    assert campaign.pending()
    assert not runtime.state.pending() and not runtime.state.incidents()
    assert len(runtime.state.ledger.autostart_claims) == 1
