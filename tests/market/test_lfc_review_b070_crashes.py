"""Guards: B070 every durable close-intent/publication/anchor crash boundary."""
from copy import deepcopy
from pathlib import Path
import hashlib
import os
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW
from tests.market.test_lfc_review_b067_integrity import prepared
from weather.market import lfc_campaign_closures as closures
from weather.market.lfc_campaign_close_intent import validate, INLINE_LIMIT
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.mm_stage2_hold import canonical_bytes


def reopen(runtime):
    state = runtime.state
    return AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))


@pytest.mark.parametrize('point', ['before_intent', 'after_intent', 'before_publish', 'after_publish', 'before_anchor', 'after_anchor'])
@pytest.mark.parametrize('cold', [False, True])
def test_each_intent_publish_anchor_boundary_preserves_identity(tmp_path, monkeypatch, point, cold):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state
        path = state.root/'closed'/(claim['attempt_id']+'.json')
        ordinary_record = state.ledger.record
        ordinary_publish = os.rename if os.name == 'nt' else os.link
        def record(event, **fields):
            if point == 'before_intent' and event == 'autostart_close_intent':
                raise OSError('crash_before_intent')
            if point == 'before_anchor' and event == 'autostart_close':
                raise OSError('crash_before_anchor')
            result = ordinary_record(event, **fields)
            if point == 'after_intent' and event == 'autostart_close_intent' or point == 'after_anchor' and event == 'autostart_close':
                raise OSError('crash_after_append')
            return result
        def publish(a, b):
            if b == path and point == 'before_publish':
                raise OSError('crash_before_publication')
            result = ordinary_publish(a, b)
            if b == path and point == 'after_publish':
                raise OSError('crash_after_publication')
            return result
        with monkeypatch.context() as crash:
            crash.setattr(state.ledger, 'record', record)
            crash.setattr(os, 'rename' if os.name == 'nt' else 'link', publish)
            with pytest.raises(OSError): state.close(claim, proof, NOW)
        original = path.read_bytes() if path.exists() else None
        state = reopen(runtime) if cold else state
        if point in {'after_intent', 'before_publish'}:
            with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'): state.verify()
            assert not path.exists() and len(state.ledger.autostart_incidents) == 1
            intent = state.ledger.event_rows('autostart_close_intent')[0]
            raw = intent['canonical_closure_utf8'].encode('utf-8')
            assert intent['file_sha256'] == hashlib.sha256(raw).hexdigest()
            assert len(raw) == intent['file_size']
            state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))
            with pytest.raises(StateRefused): state.verify()
            assert len(state.ledger.autostart_incidents) == 1 and not path.exists()
        elif point == 'before_intent':
            state.verify()
            assert not path.exists() and not state.ledger.event_rows('autostart_close_intent')
            assert state.pending() == [claim] and not state.ledger.autostart_incidents
        else:
            state.verify(); state.verify()
            assert len(state.ledger.event_rows('autostart_close_intent')) == 1
            assert len(state.ledger.event_rows('autostart_close')) == 1
            assert path.read_bytes() == original and not state.ledger.autostart_incidents


@pytest.mark.parametrize('change', ['hash', 'size', 'body', 'noncanonical', 'duplicate', 'anchor_binding'])
def test_intent_replay_refuses_unproved_identity(tmp_path, monkeypatch, change):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        ledger = runtime.state.ledger
        row = deepcopy(ledger.event_rows('autostart_close_intent')[0])
        # Validate against precisely the historical prefix, before this intent.
        prefix = tmp_path/'prefix.jsonl'
        prefix.write_bytes(b''.join(canonical_bytes(r) for r in ledger.rows[:row['sequence']]))
        prior = Ledger.open(prefix, clock=runtime.clock.now)
        if change == 'hash': row['file_sha256'] = 'a'*64
        if change == 'size': row['file_size'] += 1
        if change == 'body': row['canonical_closure_utf8'] = '{}'
        if change == 'noncanonical': row['canonical_closure_utf8'] += ' '
        if change == 'duplicate': prior = ledger
        if change == 'anchor_binding':
            row['close_kind'] = 'owner_recovery'
        with pytest.raises(LedgerUnavailable): validate(prior, row)


def test_large_receipt_is_hash_bound_without_unbounded_inline_copy(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, {**proof, 'research_note': 'x'*INLINE_LIMIT}, NOW)
        intent = runtime.state.ledger.event_rows('autostart_close_intent')[0]
        assert intent['file_size'] > INLINE_LIMIT and intent['canonical_closure_utf8'] is None
        fresh = reopen(runtime); fresh.verify()
        assert not fresh.ledger.autostart_incidents


@pytest.mark.parametrize('torn', [False, True])
def test_actual_intent_append_failure_preserves_bytes_and_fails_closed(tmp_path, monkeypatch, torn):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state
        ordinary_open, ordinary_sync = Path.open, os.fsync
        ledger_path = state.ledger.path
        target = []
        class Torn:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *a): self.stream.close()
            def write(self, raw):
                self.stream.write(raw[:len(raw)//2]); self.stream.flush(); ordinary_sync(self.stream.fileno())
                raise OSError('partial_intent_append')
        def opened(p, mode='r', *a, **kw):
            stream = ordinary_open(p, mode, *a, **kw)
            if p == ledger_path and mode == 'ab':
                target[:] = [stream.fileno()]
                return Torn(stream) if torn else stream
            return stream
        def sync(fd):
            ordinary_sync(fd)
            if target == [fd]: raise OSError('intent_fsync_return_lost')
        with monkeypatch.context() as crash:
            crash.setattr(Path, 'open', opened); crash.setattr(os, 'fsync', sync)
            with pytest.raises(LedgerUnavailable): state.close(claim, proof, NOW)
        original = ledger_path.read_bytes()
        path = state.root/'closed'/(claim['attempt_id']+'.json')
        assert not path.exists()
        if torn:
            with pytest.raises(LedgerUnavailable): reopen(runtime)
            assert ledger_path.read_bytes() == original
        else:
            fresh = reopen(runtime)
            with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'): fresh.verify()
            assert len(fresh.ledger.autostart_incidents) == 1 and not path.exists()
            assert fresh.ledger.event_rows('autostart_close_intent')[0]['canonical_closure_utf8']


def test_missing_before_publication_can_be_owner_closed_without_regeneration(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_recording_io import file_sha
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state
        publish_name = 'rename' if os.name == 'nt' else 'link'
        with monkeypatch.context() as crash:
            crash.setattr(os, publish_name, lambda *a: (_ for _ in ()).throw(OSError('crash_before_publish')))
            with pytest.raises(OSError): state.close(claim, proof, NOW)
        path = state.root/'closed'/(claim['attempt_id']+'.json')
        with pytest.raises(StateRefused): state.verify()
        incident = state.ledger.autostart_incidents[-1]['attempt_id']
        incident_path = state.root/'incidents'/(incident+'.json')
        runtime.workload_path = tmp_path/'fixture-workload'
        monkeypatch.setattr('builtins.input', lambda: 'close '+file_sha(incident_path)[:12])
        assert owner_close(runtime, incident) == 0
        assert not path.exists() and not state.pending() and not state.incidents()
        assert len(state.ledger.autostart_claims) == 1
        assert len(state.ledger.event_rows('autostart_close_intent')) == 1
        assert not state.ledger.event_rows('autostart_close')
        fresh = reopen(runtime); fresh.verify()
        assert not fresh.pending() and not fresh.incidents() and not path.exists()
