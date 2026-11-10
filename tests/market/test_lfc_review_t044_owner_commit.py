"""Guards: T044 RECHECK1 owner-close anchor-to-attempt-close crash boundary; synthetic only."""
import pytest
import json
from weather.market.lfc_recording_io import file_sha

from tests.market.test_lfc_campaign import MAKER, Mutexes
from weather.market.lfc_campaign_guard import account_lease


def assert_only_completion_appends(state, before, claim, closed, decision, *, published):
    """Old bytes are immutable; only this attempt's proved completion may append."""
    from weather.market.lfc_campaign_closures import fields
    after = state.ledger.path.read_bytes()
    assert after[:len(before)] == before
    rows = [json.loads(raw) for raw in after[len(before):].splitlines()]
    restored = 'autostart_owner_artifact_restored'
    assert [r['event'] for r in rows] == ([restored, 'autostart_close'] if published else
        ['autostart_close_intent', 'autostart_close', restored])
    expected = fields(state, closed)
    assert expected['attempt_id'] == claim['attempt_id']
    assert expected['file_sha256'] == file_sha(closed)
    for row in rows:
        if row['event'] == restored:
            assert row['artifact'] == 'state/closed/' + claim['attempt_id'] + '.json'
            assert row['closure_sha256'] == file_sha(decision)
            assert row['file_sha256'] == file_sha(closed)
            continue
        assert all(row[key] == value for key, value in expected.items())
        if row['event'] == 'autostart_close_intent':
            assert row['canonical_closure_utf8'].encode() == closed.read_bytes()
    # Project away exactly the validated additions, retaining a byte oracle.
    assert after[:-len(after[len(before):])] == before


def test_committed_owner_close_can_finish_missing_attempt_close_receipt(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close, binding
    from weather.market.lfc_campaign_recovery import recover_empty
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
        state = runtime.state
        original_save = state.save
        def crash(relative, row):
            if relative == 'closed/' + claim['attempt_id'] + '.json':
                raise OSError('synthetic_crash_after_owner_anchor_before_attempt_close')
            return original_save(relative, row)
        with monkeypatch.context() as patch:
            patch.setattr(state, 'save', crash)
            with pytest.raises(OSError, match='synthetic_crash'):
                owner_close(runtime, incident)
        path = state.root / 'owner-closures' / (incident + '.json')
        receipt = path.read_bytes()
        assert binding(state, claim['attempt_id']) is not None
        assert not state.ledger.unacknowledged_intents() and not state.ledger.unresolved_legs()
        assert state.incidents() == []
        assert not (state.root / 'closed' / (claim['attempt_id'] + '.json')).exists()
        runtime.reload_ledger()  # Real re-open validates the committed anchor.
        recover_empty(state, runtime.clock.now())
        # It may recover automatically or complete the same decision through a
        # fresh, explicitly confirmed retry. Neither may rewrite its evidence.
        if state.pending():
            assert owner_close(runtime, incident) == 0
        assert state.pending() == [] and state.incidents() == []
        assert path.read_bytes() == receipt


def test_committed_close_cannot_turn_into_a_new_ambiguous_incident(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_campaign import CampaignCoordinator
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
        state = runtime.state
        ordinary = state.save
        def crash(relative, row):
            if relative == 'closed/' + claim['attempt_id'] + '.json':
                raise OSError('synthetic_closeout_receipt_failure')
            return ordinary(relative, row)
        with monkeypatch.context() as patch:
            patch.setattr(state, 'save', crash)
            with pytest.raises(OSError):
                owner_close(runtime, incident)
        monkeypatch.setattr(runtime, 'notify_control', lambda row: None)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=runtime.clock,
                                         control_root=tmp_path / 'synthetic-control')
        coordinator.pending()
        assert not state.ledger.unacknowledged_intents() and not state.ledger.unresolved_legs()
        assert state.incidents() == [], 'A committed proved-money closure cannot become a new ambiguity occurrence'


@pytest.mark.parametrize('published', [False, True])
def test_committed_retry_neither_redecides_nor_rewrites_after_reboot(tmp_path, monkeypatch, published):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
        state = runtime.state
        original = state.save
        relative = 'closed/' + claim['attempt_id'] + '.json'
        def crash(name, fields):
            if name == relative:
                if published: original(name, fields)
                raise OSError('synthetic_final_receipt_interruption')
            return original(name, fields)
        with monkeypatch.context() as patch:
            patch.setattr(state, 'save', crash)
            with pytest.raises(OSError, match='synthetic_final_receipt_interruption'):
                owner_close(runtime, incident)
        decision = state.root / 'owner-closures' / (incident + '.json')
        receipt, history = decision.read_bytes(), state.ledger.path.read_bytes()
        runtime.reload_ledger()
        monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('committed decision must not be re-decided'))
        monkeypatch.setattr('builtins.input', lambda: pytest.fail('committed decision must not ask again'))
        assert owner_close(runtime, incident) == 0
        closed = state.root / relative
        original_closed = closed.read_bytes()
        runtime.reload_ledger()
        assert owner_close(runtime, incident) == 0
        assert decision.read_bytes() == receipt and closed.read_bytes() == original_closed
        assert_only_completion_appends(state, history, claim, closed, decision, published=published)
        assert len([r for r in state.ledger.rows if r['event'] == 'autostart_owner_close']) == 1
        assert claim['local_date'] in state.consumed_dates()
        assert not state.pending() and not state.incidents()
        assert state.read(closed)['proof']['research_evidence_complete'] is False


@pytest.mark.parametrize('fault', ['closure_changed', 'artifact_changed', 'foreign_receipt'])
def test_committed_completion_refuses_changed_evidence_or_a_foreign_receipt(tmp_path, monkeypatch, fault):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close, complete_committed
    from weather.market.lfc_campaign_state import StateRefused
    import json
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
        journal = directory / 'journal.jsonl'
        journal.write_text('synthetic retained original fragment')
        state = runtime.state
        original = state.save
        relative = 'closed/' + claim['attempt_id'] + '.json'
        def crash(name, fields):
            if name == relative: raise OSError('synthetic_committed_only')
            return original(name, fields)
        with monkeypatch.context() as patch:
            patch.setattr(state, 'save', crash)
            with pytest.raises(OSError, match='synthetic_committed_only'):
                owner_close(runtime, incident)
        path = state.root / 'owner-closures' / (incident + '.json')
        if fault == 'closure_changed':
            row = state.read(path); row['research_evidence_complete'] = True
            path.write_text(json.dumps(row))
        elif fault == 'artifact_changed':
            journal.write_text('changed after this occurrence was closed')
        else:
            proof = dict(state.read(path)['proof'], ledger_head_sha256=state.ledger.previous)
            from weather.market.mm_stage2_hold import digest
            before = state.ledger.path.read_bytes()
            with pytest.raises(StateRefused, match='^closeout_continuity$'):
                original(relative, {'attempt_id': 'f' * 32, 'proof': proof, 'proof_sha256': digest(proof)})
            assert state.ledger.path.read_bytes() == before
            assert not (state.root / relative).exists()
            return  # The production writer refuses this corruption before publication.
        receipt = path.read_bytes()
        target = state.root / relative
        target_before = target.read_bytes() if target.exists() else None
        with pytest.raises(StateRefused):
            complete_committed(state, claim['attempt_id'], runtime.clock.now())
        assert path.read_bytes() == receipt
        assert (target.read_bytes() if target.exists() else None) == target_before
        if fault == 'artifact_changed':
            assert len(state.ledger.autostart_incidents) == 2
            assert state.ledger.autostart_incidents[-1]['attempt_id'] != incident
            with pytest.raises(StateRefused, match='owner_accepted_artifact_recurred'):
                complete_committed(state, claim['attempt_id'], runtime.clock.now())
            assert len(state.ledger.autostart_incidents) == 2
