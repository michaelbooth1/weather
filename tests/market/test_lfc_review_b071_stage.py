"""Guards: B071 staged retries cannot replace lost evidence or mutate status."""
from pathlib import Path
import os
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b067_integrity import prepared
from tests.market.test_lfc_review_b069_retry import coordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_campaign_status import ReadOnlyState
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_campaign_publication import PUBLISH_ATTEMPTS


def pending(tmp_path, monkeypatch):
    runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
    name = 'rename' if os.name == 'nt' else 'link'
    original = getattr(os, name); calls = []
    def busy(a, b):
        if Path(b).name == claim['attempt_id']+'.json':
            calls.append(True); raise PermissionError('sharing_violation')
        return original(a, b)
    with monkeypatch.context() as fault:
        fault.setattr(os, name, busy)
        assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
    assert len(calls) == PUBLISH_ATTEMPTS
    intent = runtime.state.ledger.event_rows('autostart_close_intent')[0]
    return runtime, policy, claim, intent


@pytest.mark.parametrize('change', ['deleted', 'changed'])
@pytest.mark.parametrize('reopen', [False, True])
def test_lost_or_changed_bound_stage_latches_without_a_fresh_read(tmp_path, monkeypatch, change, reopen):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, intent = pending(tmp_path, monkeypatch)
        stage = runtime.state.root/intent['staged_file']
        if change == 'deleted': stage.unlink()
        else: stage.write_bytes(stage.read_bytes()+b' ')
        if reopen:
            state = runtime.state
            runtime.state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))
        runtime.postcheck = lambda *a: pytest.fail('Lost bytes must not be freshly postchecked')
        for _ in range(2):
            runtime.clock.sleep(1)
            assert coordinator(runtime).tick(lambda: policy) == 'INCIDENT'
        assert len(runtime.state.ledger.autostart_incidents) == 1
        assert len(runtime.state.ledger.autostart_claims) == 1
        assert not runtime.state.ledger.event_rows('autostart_close')
        assert not (runtime.state.root/intent['file']).exists()


def test_readonly_status_does_not_publish_the_pending_stage(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, intent = pending(tmp_path, monkeypatch)
        state = runtime.state
        stage = state.root/intent['staged_file']
        raw, ledger_bytes = stage.read_bytes(), state.ledger.path.read_bytes()
        controls = {p.name: p.read_bytes() for p in runtime.control_root.glob('*.json')}
        observed = ReadOnlyState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))
        with pytest.raises(StateRefused, match='status_repair_required'): observed.verify()
        assert stage.read_bytes() == raw and state.ledger.path.read_bytes() == ledger_bytes
        assert not (state.root/intent['file']).exists()
        assert controls == {p.name: p.read_bytes() for p in runtime.control_root.glob('*.json')}


def test_pre_intent_failure_does_not_invent_a_committed_receipt(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        original = Ledger.record
        def refused(ledger, event, **fields):
            if event == 'autostart_close_intent': raise OSError('no_append_occurred')
            return original(ledger, event, **fields)
        with monkeypatch.context() as fault:
            fault.setattr(Ledger, 'record', refused)
            assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
        assert not runtime.state.ledger.event_rows('autostart_close_intent')
        assert not runtime.state.ledger.autostart_incidents
        runtime.clock.sleep(1)
        assert coordinator(runtime).tick(lambda: policy) == 'POSTCHECKS'
        assert len(runtime.state.ledger.event_rows('autostart_close_intent')) == 1
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


def test_a_stage_copy_cannot_replace_a_proved_published_closure(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_persistence import retry_failure
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state
        state.close(claim, proof, runtime.clock.now())
        intent = state.ledger.event_rows('autostart_close_intent')[0]
        path, stage = state.root/intent['file'], state.root/intent['staged_file']
        stage.write_bytes(path.read_bytes()); path.unlink()
        with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
            retry_failure(state, claim['attempt_id'], OSError('storage_error'))
        assert not path.exists() and len(state.ledger.autostart_incidents) == 1
