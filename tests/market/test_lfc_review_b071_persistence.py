"""Guards: B071 intact closure transactions recover transient storage failures."""
import os
from pathlib import Path
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_review_b067_integrity import prepared
from tests.market.test_lfc_review_b069_retry import coordinator, finish_window
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_campaign_control import latest_control, watch_status
from weather.market.lfc_ledger import Ledger, LedgerUnavailable


def cold(runtime):
    state = runtime.state
    runtime.state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))


def test_single_publish_failure_retries_without_a_latch(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        name = 'rename' if os.name == 'nt' else 'link'
        publish = getattr(os, name); hits = []
        def once(a, b):
            if Path(b).name == claim['attempt_id']+'.json' and not hits:
                hits.append(True); raise PermissionError('transient_publish_busy')
            return publish(a, b)
        monkeypatch.setattr(os, name, once)
        assert coordinator(runtime).tick(lambda: policy) == 'POSTCHECKS'
        assert hits and not runtime.state.ledger.autostart_incidents
        assert len(runtime.state.ledger.event_rows('autostart_close_intent')) == 1
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


@pytest.mark.parametrize('reopen', [False, True])
def test_matching_stage_remains_retry_pending_across_ticks(tmp_path, monkeypatch, reopen):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        name = 'rename' if os.name == 'nt' else 'link'
        original = getattr(os, name)
        def fail(a, b):
            if Path(b).name == claim['attempt_id']+'.json':
                raise PermissionError('bounded_publish_busy')
            return original(a, b)
        with monkeypatch.context() as failure:
            failure.setattr(os, name, fail)
            for _ in range(3):
                if reopen: cold(runtime)
                runtime.clock.sleep(1)
                assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
                assert watch_status(latest_control(runtime.control_root), now=runtime.clock.now())[1] == 1
                assert not runtime.state.ledger.autostart_incidents
                assert len(runtime.state.ledger.autostart_claims) == 1
                intents = runtime.state.ledger.event_rows('autostart_close_intent')
                assert len(intents) == 1 and not runtime.state.ledger.event_rows('autostart_close')
            raw = intents[0]['canonical_closure_utf8'].encode('utf-8')
        finish_window(runtime, policy)
        assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json')
        assert path.read_bytes() == raw and not runtime.state.ledger.autostart_incidents
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


@pytest.mark.parametrize('event', ['autostart_close_intent', 'autostart_close'])
@pytest.mark.parametrize('failure', ['fsync', 'snapshot'])
def test_complete_closure_append_exception_is_retry_pending(tmp_path, monkeypatch, event, failure):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state
        record, opened, sync, snapshot = Ledger.record, Path.open, os.fsync, Ledger.write_snapshot
        stage, target, hits = [], [], []
        def recorded(ledger, name, **fields):
            stage[:] = [name]
            return record(ledger, name, **fields)
        def file_open(p, mode='r', *a, **kw):
            stream = opened(p, mode, *a, **kw)
            if p == state.ledger.path and mode == 'ab': target[:] = [stream.fileno()]
            return stream
        def fsync(fd):
            sync(fd)
            if failure == 'fsync' and stage == [event] and target == [fd] and not hits:
                hits.append(True); raise OSError('complete_append_fsync_return_lost')
        def write_snapshot(ledger):
            if failure == 'snapshot' and stage == [event] and not hits:
                hits.append(True); raise LedgerUnavailable('ledger_snapshot_write_failed')
            return snapshot(ledger)
        with monkeypatch.context() as faults:
            faults.setattr(Ledger, 'record', recorded); faults.setattr(Path, 'open', file_open)
            faults.setattr(os, 'fsync', fsync); faults.setattr(Ledger, 'write_snapshot', write_snapshot)
            assert coordinator(runtime).tick(lambda: policy) == 'RETRY_PENDING'
        assert hits and not runtime.state.ledger.autostart_incidents
        assert len(runtime.state.ledger.event_rows(event)) == 1
        cold(runtime); finish_window(runtime, policy)
        assert coordinator(runtime).tick(lambda: policy) == 'IDLE'
        assert not runtime.state.ledger.autostart_incidents
        assert len(runtime.state.ledger.event_rows('autostart_close_intent')) == 1
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
