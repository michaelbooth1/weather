"""Guards: B067 closure loss, durable crash gaps, legacy refusal and clean pending."""
from copy import deepcopy
from datetime import timedelta
import json
import os
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW, policy_row, bind_launch
from tests.market.test_lfc_campaign_runtime import runtime_at
from tests.market.test_lfc_campaign_recurrence import configure_runtime
from tests.market.lfc_campaign_fixtures import private_result
from tests.market.test_lfc_review_b065_idle import idle_fixture, reboot
from weather.market import lfc_campaign_closures as closures
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_campaign_control import latest_control, row_is_clean
from weather.market.lfc_ledger import Ledger
from weather.market.mm_stage2_hold import digest


def prepared(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path); configure_runtime(runtime, monkeypatch)
    runtime.notify_control = lambda row: None
    policy = parse_policy(policy_row())
    claim = runtime.state.claim(policy.entries[0], policy, NOW)
    directory, result = private_result(runtime, claim, faults=())
    runtime.save_result(claim, result)
    proof = runtime.postcheck(claim, runtime.saved_result(claim))
    return runtime, policy, claim, proof


@pytest.mark.parametrize('cold', [False, True])
@pytest.mark.parametrize('change', ['delete', 'same_size', 'size'])
def test_anchor_fault_precedes_postcheck_and_full_validator(tmp_path, monkeypatch, cold, change):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, coordinator, policy, _, _ = idle_fixture(tmp_path, monkeypatch)
        assert coordinator.tick(lambda: policy) == 'IDLE'
        claim = runtime.state.claims()[0]
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json')
        original, stamp = path.read_bytes(), path.stat()
        if change == 'delete':
            path.unlink()
        else:
            old = json.loads(original)['closed_at_utc']
            from datetime import datetime
            new = (datetime.fromisoformat(old)+timedelta(seconds=1)).isoformat()
            changed = original.replace(('"closed_at_utc":"'+old+'"').encode(),
                                       ('"closed_at_utc":"'+new+'"').encode(), 1)
            assert len(changed) == len(original) and json.loads(changed)['closed_at_utc'] == new
            path.write_bytes(changed if change == 'same_size' else original+b' ')
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        if cold:
            reboot(runtime, coordinator)
        runtime.clock.value += timedelta(seconds=1)
        monkeypatch.setattr(AccountState, 'require_retained_evidence',
            lambda self: pytest.fail('Anchor must be checked before full validation'))
        runtime.postcheck = lambda *a: pytest.fail('A missing completed close cannot get a new read')
        assert coordinator.tick(lambda: policy) == 'INCIDENT'
        runtime.clock.value += timedelta(seconds=1)
        assert coordinator.tick(lambda: policy) == 'INCIDENT'
        assert len(runtime.state.ledger.autostart_claims) == 1
        assert len(runtime.state.ledger.autostart_incidents) == 1
        control = latest_control(runtime.control_root)
        assert control['incident'] is True and control['attention_required'] is True
        assert not row_is_clean(control)
        if change == 'delete':
            assert not path.exists()
        else:
            assert path.read_bytes() != original


@pytest.mark.parametrize('point', ['before_anchor', 'after_fsync'])
def test_file_first_crash_reopens_and_anchors_exactly_once(tmp_path, monkeypatch, point):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        state = runtime.state; attempt = claim['attempt_id']
        original = closures.anchor
        def interrupted(s, aid):
            if point == 'after_fsync':
                original(s, aid)
            raise OSError('fixture crash')
        with monkeypatch.context() as crash:
            crash.setattr(closures, 'anchor', interrupted)
            with pytest.raises(OSError, match='fixture crash'):
                state.close(claim, proof, NOW)
        path = state.root/'closed'/(attempt+'.json'); saved = path.read_bytes()
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))
        state.verify(); state.verify()
        state = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=runtime.clock.now))
        state.verify()
        anchors = state.ledger.event_rows('autostart_close', field='attempt_id', value=attempt)
        assert len(anchors) == 1 and path.read_bytes() == saved
        assert not state.ledger.autostart_incidents
        row = json.loads(saved)
        assert anchors[0]['closed_at_utc'] == row['closed_at_utc']
        assert anchors[0]['proof_sha256'] == row['proof_sha256']
        assert anchors[0]['read_binding']['read_sha256'] == proof['read_sha256']
        assert anchors[0]['file_size'] == len(saved)


def test_neither_file_nor_anchor_keeps_the_normal_postcheck(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        assert runtime.state.pending() == [claim]
        coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime,
            clock=runtime.clock, control_root=runtime.control_root)
        policy = bind_launch(coordinator, policy)
        assert coordinator.tick(lambda: policy) == 'POSTCHECKS'
        assert not runtime.state.pending()
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
        assert not runtime.state.incidents()


@pytest.mark.parametrize('remove_file', [False, True])
def test_pre_b067_root_refuses_even_if_completed_receipt_is_also_missing(tmp_path, monkeypatch, remove_file):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, coordinator, policy, _, _ = idle_fixture(tmp_path, monkeypatch)
        claim = runtime.state.claims()[0]
        # Simulate the old enrollment's absent protocol. Refusal must precede
        # all file inference, independently of optional later closure anchors.
        runtime.state.ledger.enrollment.pop('closure_anchor_protocol')
        if remove_file:
            (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
        with pytest.raises(StateRefused, match='closure_anchor_protocol_required'):
            runtime.state.verify()
        assert coordinator.tick(lambda: policy) != 'IDLE'


def test_closure_publishes_before_ledger_anchor_and_never_overwrites(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        seen, operations = [], []
        real = runtime.state.ledger.record
        fsync = os.fsync
        publish_name = 'rename' if os.name == 'nt' else 'link'
        publish = getattr(os, publish_name)
        def flushed(fd):
            operations.append('fsync'); return fsync(fd)
        def published(*args):
            operations.append('publish'); return publish(*args)
        monkeypatch.setattr(os, 'fsync', flushed)
        monkeypatch.setattr(os, publish_name, published)
        def record(event, **fields):
            if event == 'autostart_close_intent':
                operations.append('intent')
                assert not (runtime.state.root/fields['file']).exists()
            if event == 'autostart_close':
                operations.append('anchor')
                path = runtime.state.root/fields['file']
                assert path.is_file() and json.loads(path.read_bytes())['proof_sha256'] == fields['proof_sha256']
                seen.append(fields)
            return real(event, **fields)
        monkeypatch.setattr(runtime.state.ledger, 'record', record)
        runtime.state.close(claim, proof, NOW)
        assert len(seen) == 1
        assert operations == ['fsync', 'intent', 'fsync', 'publish', 'anchor', 'fsync']
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json'); saved = path.read_bytes()
        with pytest.raises(FileExistsError):
            closures.write_closure(path, {'changed': True}, max_bytes=1000)
        assert path.read_bytes() == saved


@pytest.mark.parametrize('corrupt', [False, True])
def test_one_owner_close_acknowledges_lost_original_without_recreating_it(tmp_path, monkeypatch, corrupt):
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_recording_io import file_sha
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json')
        original = path.read_bytes()
        if corrupt:
            path.write_bytes(b'['+original[1:])
        else:
            path.unlink()
        with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
            runtime.state.verify()
        incident = runtime.state.ledger.autostart_incidents[-1]['attempt_id']
        incident_path = runtime.state.root/'incidents'/(incident+'.json')
        runtime.workload_path = tmp_path/'fixture-workload'
        monkeypatch.setattr('builtins.input', lambda: 'close '+file_sha(incident_path)[:12])
        assert owner_close(runtime, incident) == 0
        assert not runtime.state.pending() and not runtime.state.incidents()
        from weather.market.lfc_completion import ledger_completion
        completion = ledger_completion(runtime.pilot_root, runtime.state.ledger)
        assert completion['evidence_complete'] is False and completion['unknown_submit'] is False
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
        if corrupt:
            assert path.read_bytes() == b'['+original[1:]
        else:
            assert not path.exists()
            path.write_bytes(original)
            runtime.state.verify()  # Records restoration against the owner receipt.
            path.unlink()
            with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
                runtime.state.verify()
            assert len(runtime.state.ledger.autostart_incidents) == 2
            assert runtime.state.ledger.autostart_incidents[-1]['attempt_id'] != incident


def test_no_intent_file_before_both_anchors_is_completed_once_after_crash(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_recovery import close_empty, recover_empty
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        real = runtime.state.ledger.record
        def interrupted(event, **fields):
            if event == 'autostart_no_intent_close':
                raise OSError('fixture interrupted no-intent anchor')
            return real(event, **fields)
        with monkeypatch.context() as crash:
            crash.setattr(runtime.state.ledger, 'record', interrupted)
            with pytest.raises(OSError):
                close_empty(runtime.state, claim, NOW)
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json'); saved = path.read_bytes()
        runtime.state = AccountState(runtime.state.root.parent,
            Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now))
        recover_empty(runtime.state, NOW); recover_empty(runtime.state, NOW)
        assert path.read_bytes() == saved and not runtime.state.pending()
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1
        assert len(runtime.state.ledger.event_rows('autostart_no_intent_close')) == 1


@pytest.mark.parametrize('command', ['status', 'check'])
def test_cli_binding_fault_publishes_incident_even_before_outer_state_assignment(tmp_path, monkeypatch, command):
    from contextlib import nullcontext
    from weather.market import lfc_campaign_cli as cli
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        state_id = runtime.state.verify()['state_id']
        (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
        release = {'maker_address': MAKER, 'ledger_genesis_sha256': runtime.state.ledger.row_sha256(0),
                   'state_id': state_id, 'campaign_path': str(tmp_path/'not-read')}
        monkeypatch.setattr(cli, 'load_release', lambda *a: release)
        monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
        monkeypatch.setattr(cli, 'pilot_root', lambda: runtime.pilot_root)
        monkeypatch.setattr(cli, 'DEFAULT_STATE_ROOT', runtime.state.root.parent)
        monkeypatch.setattr(cli, 'CONTROL_ROOT', runtime.control_root)
        monkeypatch.setattr(cli, 'account_lease', lambda maker: nullcontext())
        if command == 'status':
            from weather.market import lfc_campaign_guard as guard
            monkeypatch.setattr(guard, 'account_lease_busy', lambda maker: False)
            before = {str(p): p.read_bytes() for p in runtime.state.root.rglob('*') if p.is_file()}
            assert cli.main([command, '--release', 'fixture', '--release-sha256', 'a'*64]) == 1
            assert before == {str(p): p.read_bytes() for p in runtime.state.root.rglob('*') if p.is_file()}
            assert not list(runtime.control_root.glob('*'))
            return  # Observation reports the fault; only an owning check/tick latches it.
        assert cli.main([command, '--release', 'fixture', '--release-sha256', 'a'*64]) == 1
        row = latest_control(runtime.control_root)
        assert row['phase'] == 'INCIDENT' and row['incident'] is True
        assert row['attention_required'] is True and not row_is_clean(row)


def test_shared_verify_completion_cannot_pass_a_deleted_campaign_closure(tmp_path, monkeypatch):
    from weather.market.lfc_completion import ledger_completion, complete_evidence
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
        result = ledger_completion(runtime.pilot_root, runtime.state.ledger)
        assert not complete_evidence(result)
        assert result['unknown_submit'] is False
        assert 'campaign_closure_evidence' in result['evidence_refusals']
        reopened = Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now)
        assert len(reopened.autostart_incidents) == 1


def test_deleted_no_intent_close_is_fault_even_in_gap_before_generic_anchor(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_recovery import close_empty
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path); policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        with monkeypatch.context() as crash:
            def interrupted(*args):
                raise OSError('fixture after dedicated anchor')
            crash.setattr(closures, 'anchor', interrupted)
            with pytest.raises(OSError):
                close_empty(runtime.state, claim, NOW)
        (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
        with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
            runtime.state.verify()
        assert len(runtime.state.ledger.autostart_incidents) == 1


def test_partial_close_with_missing_private_file_needs_only_one_owner_close(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_recording_io import file_sha
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        with monkeypatch.context() as crash:
            def interrupted(*args):
                raise OSError('fixture partial normal close')
            crash.setattr(closures, 'anchor', interrupted)
            with pytest.raises(OSError):
                runtime.state.close(claim, proof, NOW)
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json'); original = path.read_bytes()
        (runtime.pilot_root/'private-session'/'journal.jsonl').unlink()
        with pytest.raises(StateRefused):
            runtime.state.verify()
        with pytest.raises(StateRefused):
            runtime.state.verify()
        assert len(runtime.state.ledger.autostart_incidents) == 1
        incident = runtime.state.ledger.autostart_incidents[0]['attempt_id']
        incident_path = runtime.state.root/'incidents'/(incident+'.json')
        runtime.workload_path = tmp_path/'fixture-workload'
        monkeypatch.setattr('builtins.input', lambda: 'close '+file_sha(incident_path)[:12])
        assert owner_close(runtime, incident) == 0
        assert not runtime.state.pending() and not runtime.state.incidents()
        assert path.read_bytes() == original
        assert len(runtime.state.ledger.event_rows('autostart_close')) == 1


def test_owner_review_retains_read_access_but_persists_the_closure_fault(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        runtime.state.close(claim, proof, NOW)
        path = runtime.state.root/'closed'/(claim['attempt_id']+'.json'); path.unlink()
        runtime.state.verify(owner_fault_review=True)
        assert len(runtime.state.ledger.autostart_incidents) == 1 and not path.exists()
        with pytest.raises(StateRefused, match='anchored_closure_evidence_fault'):
            runtime.state.verify()
        assert len(runtime.state.ledger.autostart_incidents) == 1


def test_unenrolled_verify_keeps_existing_session_name_semantics(tmp_path, monkeypatch):
    from weather.market.lfc_completion import ledger_completion
    from tests.market.test_lfc_campaign import Clock
    ledger = Ledger.create(tmp_path/'ledger.jsonl', clock=Clock().now, maker_address=MAKER)
    monkeypatch.setattr(closures, 'verify_enrolled', lambda *a: pytest.fail('F0 must not enter campaign verification'))
    assert ledger_completion(tmp_path, ledger)['evidence_complete'] is True
    ledger.record('session_start', session_id='campaign_closure_evidence', counted=False, directory='missing')
    ledger.record('session_end', session_id='campaign_closure_evidence')
    report = ledger_completion(tmp_path, ledger)
    assert report['unknown_submit'] is True
    assert report['evidence_refusals'] == ['campaign_closure_evidence']


def test_old_result_without_either_closure_or_anchor_cannot_be_inferred_pending(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        assert len(runtime.state.ledger.autostart_results) == 1
        assert not runtime.state.ledger.event_rows('autostart_close')
        assert not (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).exists()
        runtime.state.ledger.enrollment.pop('closure_anchor_protocol')
        runtime.postcheck = lambda *a: pytest.fail('Legacy uncertainty cannot trigger a new close read')
        with pytest.raises(StateRefused, match='closure_anchor_protocol_required'):
            runtime.state.verify()
        coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime,
            clock=runtime.clock, control_root=runtime.control_root)
        assert coordinator.tick(lambda: policy) == 'INCIDENT'
        assert len(runtime.state.ledger.autostart_claims) == 1
