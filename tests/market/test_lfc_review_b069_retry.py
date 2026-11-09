"""Guards: B069 persistence retries stay visible without evidence-loss latches."""
from contextlib import nullcontext
from pathlib import Path
from datetime import timedelta
import os
import json
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW
from tests.market.test_lfc_review_b067_integrity import prepared
from weather.market import lfc_campaign_closures as closures
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_campaign_persistence import ClosureRetryPending
from weather.market.lfc_campaign_control import latest_control, watch_status
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import canonical_bytes


@pytest.fixture(autouse=True)
def account_guard():
    with account_lease(MAKER, backend=Mutexes()): yield


def interrupted(tmp_path, monkeypatch):
    runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
    with monkeypatch.context() as crash:
        crash.setattr(closures, 'anchor', lambda *a: (_ for _ in ()).throw(OSError('before_anchor')))
        with pytest.raises(OSError): runtime.state.close(claim, proof, NOW)
    path = runtime.state.root/'closed'/(claim['attempt_id']+'.json')
    runtime.state = AccountState(runtime.state.root.parent, Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now))
    runtime.pre_go = lambda *a: pytest.fail('Retry must not enter pre_go')
    return runtime, policy, claim, path, path.read_bytes()


def coordinator(runtime):
    return CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock, control_root=runtime.control_root)


def test_repeated_append_failures_are_retry_pending_then_one_clean_anchor(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ledger_path = runtime.state.ledger.path
    before = ledger_path.read_bytes(); ordinary = Path.open; calls = []
    def fail(p, mode='r', *a, **kw):
        if p == ledger_path and mode == 'ab':
            calls.append(True); raise OSError('storage_unavailable')
        return ordinary(p, mode, *a, **kw)
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', fail)
        for index in range(3):
            runtime.clock.sleep(1)
            assert coordinator(runtime).tick(lambda: pytest.fail('Retry must not load a new policy')) == 'RETRY_PENDING'
            row = latest_control(runtime.control_root)
            public, code = watch_status(row, now=runtime.clock.now())
            assert code == 1 and public['reason'] == 'retry_pending'
            assert row['phase'] == 'RETRY_PENDING' and row['incident'] is False
            assert row['policy_name'] == policy.raw['policy_name'] and row['sleeve_loss_basis'] == 'gross'
            assert ledger_path.read_bytes() == before and path.read_bytes() == original
            assert not runtime.state.ledger.autostart_incidents
            assert len(runtime.state.ledger.autostart_claims) == 1
    assert len(calls) == 3
    for _ in range(2):
        runtime.clock.sleep(1)
        assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
        assert watch_status(latest_control(runtime.control_root), now=runtime.clock.now())[1] == 0
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
        assert path.read_bytes() == original and not runtime.state.ledger.autostart_incidents


def test_after_fsync_exception_replays_one_anchor_on_the_same_state(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ordinary_open, ordinary_sync = Path.open, os.fsync
    target, hits = [], []
    def opened(p, mode='r', *a, **kw):
        handle = ordinary_open(p, mode, *a, **kw)
        if p == runtime.state.ledger.path and mode == 'ab': target[:] = [handle.fileno()]
        return handle
    def sync(fd):
        ordinary_sync(fd)
        if target == [fd] and not hits:
            hits.append(True); raise OSError('after_successful_fsync')
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', opened); failure.setattr(os, 'fsync', sync)
        assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
    assert hits and len(runtime.state.ledger.event_rows('autostart_close')) == 1
    assert not runtime.state.ledger.autostart_incidents and path.read_bytes() == original
    runtime.clock.sleep(1)
    assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
    assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


def test_torn_recovery_append_still_refuses_and_never_truncates(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ledger_path = runtime.state.ledger.path; ordinary = Path.open
    class Torn:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *a): self.stream.close()
        def write(self, raw):
            self.stream.write(raw[:len(raw)//2]); self.stream.flush(); os.fsync(self.stream.fileno())
            raise OSError('torn_anchor')
    def opened(p, mode='r', *a, **kw):
        handle = ordinary(p, mode, *a, **kw)
        return Torn(handle) if p == ledger_path and mode == 'ab' else handle
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', opened)
        with pytest.raises(LedgerUnavailable) as caught: runtime.state.verify()
        assert not isinstance(caught.value, ClosureRetryPending)
    torn = ledger_path.read_bytes()
    with pytest.raises(LedgerUnavailable): Ledger.open(ledger_path, clock=runtime.clock.now)
    assert ledger_path.read_bytes() == torn and path.read_bytes() == original
    assert not runtime.state.ledger.autostart_incidents


@pytest.mark.parametrize('command', ['check', 'tick'])
def test_binding_retry_publishes_retry_pending_without_an_incident(tmp_path, monkeypatch, capsys, command):
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_runtime as runtime_module
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    state = runtime.state; ordinary = Path.open
    def fail(p, mode='r', *a, **kw):
        if p == state.ledger.path and mode == 'ab': raise OSError('append_unavailable')
        return ordinary(p, mode, *a, **kw)
    release = {'maker_address': MAKER, 'ledger_genesis_sha256': state.ledger.row_sha256(0),
        'state_id': state.ledger.enrollment['state_id'], 'campaign_path': 'not-read'}
    monkeypatch.setattr(cli, 'load_release', lambda *a: release)
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'pilot_root', lambda: runtime.pilot_root)
    monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', state.root.parent)
    monkeypatch.setattr(cli, 'CONTROL_ROOT', runtime.control_root)
    monkeypatch.setattr(cli, 'account_lease', lambda maker: nullcontext())
    monkeypatch.setattr(runtime_module, 'CampaignClock', lambda: runtime.clock)
    monkeypatch.setattr(runtime_module, 'Runtime', lambda **kw: pytest.fail('Binding retry constructed a runtime'))
    monkeypatch.setattr(Path, 'open', fail)
    args = [command, '--release', 'inert', '--release-sha256', 'a'*64]
    if command == 'tick': args += ['--wrapper-deadline-utc', (NOW+timedelta(hours=7)).isoformat(), '--wrapper-policy-sha256', 'c'*64]
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[0])['state'] == 'retry_pending'
    row = latest_control(runtime.control_root)
    assert row['phase'] == 'RETRY_PENDING' and row['reason'] == 'retry_pending' and row['incident'] is False
    assert not Ledger.open(state.ledger.path, clock=runtime.clock.now).autostart_incidents
    assert path.read_bytes() == original


def test_a_real_deletion_after_successful_retry_still_latches(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    runtime.state.verify()
    assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
    path.unlink()
    with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'): runtime.state.verify()
    assert len(runtime.state.ledger.autostart_incidents) == 1
    assert coordinator(runtime).tick(lambda: policy) == 'INCIDENT' and not path.exists()


def test_a_receipt_changed_during_append_failure_is_a_real_evidence_fault(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ordinary = Path.open; hits = []
    def changed(p, mode='r', *a, **kw):
        if p == runtime.state.ledger.path and mode == 'ab' and not hits:
            hits.append(True)
            row = json.loads(original); row['closed_at_utc'] = (NOW+timedelta(seconds=1)).isoformat()
            path.write_bytes(canonical_bytes(row))
            raise OSError('append_failed_after_change')
        return ordinary(p, mode, *a, **kw)
    monkeypatch.setattr(Path, 'open', changed)
    with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'): runtime.state.verify()
    assert hits and len(runtime.state.ledger.autostart_incidents) == 1
    assert not runtime.state.ledger.event_rows('autostart_close')


def test_read_only_status_reports_retry_without_appending(tmp_path, monkeypatch, capsys):
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_guard as guard
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    state = runtime.state
    release = {'maker_address': MAKER, 'ledger_genesis_sha256': state.ledger.row_sha256(0),
        'state_id': state.ledger.enrollment['state_id'], 'campaign_path': 'not-read'}
    monkeypatch.setattr(cli, 'load_release', lambda *a: release)
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'pilot_root', lambda: runtime.pilot_root)
    monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', state.root.parent)
    monkeypatch.setattr(cli, 'CONTROL_ROOT', runtime.control_root)
    monkeypatch.setattr(guard, 'account_lease_busy', lambda maker: False)
    monkeypatch.setattr(cli, 'account_lease', lambda maker: pytest.fail('Status acquired a lease'))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert cli.main(['status', '--release', 'inert', '--release-sha256', 'a'*64]) == 1
    assert json.loads(capsys.readouterr().out)['state'] == 'retry_pending'
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_shared_completion_reports_retry_without_inventing_unknown_submit(tmp_path, monkeypatch):
    from weather.market.lfc_completion import ledger_completion
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    ordinary = Path.open
    def fail(p, mode='r', *a, **kw):
        if p == runtime.state.ledger.path and mode == 'ab': raise OSError('storage_unavailable')
        return ordinary(p, mode, *a, **kw)
    monkeypatch.setattr(Path, 'open', fail)
    row = ledger_completion(runtime.pilot_root, runtime.state.ledger)
    assert row['retry_pending'] is True and row['unknown_submit'] is False
    assert row['evidence_complete'] is False and 'campaign_closure_retry_pending' in row['evidence_refusals']
    assert 'campaign_closure_evidence' not in row['evidence_refusals']
    assert not runtime.state.ledger.autostart_incidents and path.read_bytes() == original


@pytest.mark.parametrize('basis', ['gross', 'net_of_retained_gains'])
def test_retry_replay_keeps_f2_funding_unknown_cash_and_basis_exact(tmp_path, monkeypatch, basis):
    from tests.market.test_lfc_review_b060_refill import opening
    from tests.market.test_lfc_review_b066_incoming import incoming
    from weather.market.lfc_capital import CapitalBook
    ledger, state, claim, policy = opening(tmp_path, basis)
    incoming(ledger, kind='DEPOSIT', amount='100', missing=True)
    before = CapitalBook(ledger).figures()
    proof = {'unknown_submit': False, 'money_accounting_complete': True, 'cleanup_proven': True}
    with monkeypatch.context() as crash:
        crash.setattr(closures, 'anchor', lambda *a: (_ for _ in ()).throw(OSError('before_anchor')))
        with pytest.raises(OSError): state.close(claim, proof, ledger.clock())
    path = state.root/'closed'/(claim['attempt_id']+'.json'); original = path.read_bytes()
    ordinary = Path.open
    def fail(p, mode='r', *a, **kw):
        if p == state.ledger.path and mode == 'ab': raise OSError('append_unavailable')
        return ordinary(p, mode, *a, **kw)
    with monkeypatch.context() as failure:
        failure.setattr(Path, 'open', fail)
        with pytest.raises(ClosureRetryPending): state.verify()
    for _ in range(2):
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=ledger.clock))
        state.verify()
        assert CapitalBook(state.ledger).figures() == before
        assert state.ledger.sleeve_loss_basis == basis
        assert before['funding_native'] == 300_000_000
        assert before['retained_gains_available_native'] == 0
        assert len(state.ledger.event_rows('autostart_close')) == 1
        assert not state.ledger.autostart_incidents and path.read_bytes() == original


def test_retry_never_masks_an_independent_existing_incident(tmp_path, monkeypatch):
    runtime, policy, claim, path, original = interrupted(tmp_path, monkeypatch)
    runtime.state.evidence_fault('independent', artifact='other-original')
    existing = list(runtime.state.ledger.autostart_incidents)
    ordinary = Path.open
    def fail(p, mode='r', *a, **kw):
        if p == runtime.state.ledger.path and mode == 'ab': raise OSError('append_unavailable')
        return ordinary(p, mode, *a, **kw)
    monkeypatch.setattr(Path, 'open', fail)
    assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
    row = latest_control(runtime.control_root)
    assert row['phase'] == 'INCIDENT' and row['incident'] is True
    assert runtime.state.ledger.autostart_incidents == existing
    assert path.read_bytes() == original and len(runtime.state.ledger.autostart_claims) == 1


@pytest.mark.parametrize('event', ['autostart_no_intent_close', 'autostart_close'])
def test_new_no_intent_close_retries_each_append_stage(tmp_path, monkeypatch, event):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from tests.market.test_lfc_campaign_recurrence import configure_runtime
    from tests.market.test_lfc_campaign import policy_row
    from weather.market.lfc_campaign_policy import parse_policy
    runtime = runtime_at(tmp_path); configure_runtime(runtime, monkeypatch)
    runtime.notify_control = lambda row: None
    policy = parse_policy(policy_row())
    claim = runtime.state.claim(policy.entries[0], policy, NOW)
    runtime.pre_go = lambda *a: pytest.fail('No second live attempt')
    original_record = runtime.state.ledger.record; ordinary = Path.open; stage, hits = [], []
    def record(name, **fields):
        stage[:] = [name]
        return original_record(name, **fields)
    def opened(p, mode='r', *a, **kw):
        if p == runtime.state.ledger.path and mode == 'ab' and stage == [event] and not hits:
            hits.append(True); raise OSError('first_anchor_append_failed')
        return ordinary(p, mode, *a, **kw)
    monkeypatch.setattr(runtime.state.ledger, 'record', record)
    monkeypatch.setattr(Path, 'open', opened)
    assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
    path = runtime.state.root/'closed'/(claim['attempt_id']+'.json'); original = path.read_bytes()
    assert hits and not runtime.state.ledger.autostart_incidents
    runtime.clock.sleep(1)
    assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
    assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
    assert len(runtime.state.ledger.event_rows('autostart_no_intent_close')) == 1
    assert path.read_bytes() == original and not runtime.state.ledger.autostart_incidents


def test_committed_no_intent_anchor_with_deleted_original_is_not_a_retry(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from tests.market.test_lfc_campaign_recurrence import configure_runtime
    from tests.market.test_lfc_campaign import policy_row
    from weather.market.lfc_campaign_policy import parse_policy
    runtime = runtime_at(tmp_path); configure_runtime(runtime, monkeypatch)
    runtime.notify_control = lambda row: None
    policy = parse_policy(policy_row()); claim = runtime.state.claim(policy.entries[0], policy, NOW)
    path = runtime.state.root/'closed'/(claim['attempt_id']+'.json')
    original_record = runtime.state.ledger.record; hits = []
    def committed_then_failed(event, **fields):
        result = original_record(event, **fields)
        if event == 'autostart_no_intent_close' and not hits:
            hits.append(True); path.unlink()
            raise LedgerUnavailable('ledger_write_failed')
        return result
    monkeypatch.setattr(runtime.state.ledger, 'record', committed_then_failed)
    assert coordinator(runtime).tick(lambda: policy) == 'INCIDENT'
    assert hits and not path.exists() and len(runtime.state.ledger.autostart_incidents) == 1
    assert len(runtime.state.ledger.event_rows('autostart_no_intent_close')) == 1
    assert not runtime.state.ledger.event_rows('autostart_close')
