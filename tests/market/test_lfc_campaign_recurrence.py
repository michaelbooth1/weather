"""B035 recovery authority and recurrence regressions, entirely synthetic.

Guards: owner confirmation/replay/scope and recurrent private-evidence incidents.
Desired safety behavior replaces the two adverse recurrence assertions.
"""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, NOW, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at, account_read
from tests.market.test_lfc_campaign_adversarial import owner_review_fixture, reconciled_legacy
from tests.market.lfc_campaign_fixtures import private_result
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_runtime import ScheduledAuthority
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha
from weather.market import lfc_campaign_cli as cli


@pytest.mark.parametrize('mode', ['noninteractive', 'wrong_phrase', 'bare_authority'])
def test_recovery_cannot_be_auto_satisfied_by_supported_entrypoint(tmp_path, monkeypatch, mode):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, _ = owner_review_fixture(tmp_path, monkeypatch)
        before = runtime.state.ledger.previous
        if mode == 'noninteractive':
            monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: False)
        elif mode == 'wrong_phrase':
            monkeypatch.setattr('builtins.input', lambda: 'recover 000000000000')
        if mode != 'bare_authority':
            monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('must refuse before account read'))
            with pytest.raises(StateRefused, match='owner_terminal_required|owner_confirmation_refused'):
                cli.owner_recover(runtime, claim['attempt_id'])
        else:
            proof = runtime.core_proof(runtime.state.ledger, account_read(runtime))
            with pytest.raises(StateRefused):
                runtime.state.close(claim, {**proof, 'authority': 'owner_recovery'}, NOW)
        assert runtime.state.ledger.previous == before
        assert runtime.state.pending() and runtime.state.incidents()
        assert not list((runtime.state.root / 'owner-closures').glob('*.json'))


def test_one_named_incident_recovery_leaves_second_incident_blocking(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, _ = owner_review_fixture(tmp_path, monkeypatch)
        other = 'b' * 32
        runtime.state.latch(other, 'independent_money_contradiction', NOW)
        assert cli.owner_recover(runtime, claim['attempt_id']) == 0
        assert [r['attempt_id'] for r in runtime.state.incidents()] == [other]
        assert runtime.state.pending() and not list((runtime.state.root / 'closed').glob('*.json'))
        # Reusing the first incident's owner receipt under the other name cannot
        # satisfy the second incident's hash binding.
        old = runtime.state.root / 'owner-closures' / (claim['attempt_id'] + '.json')
        other_path = runtime.state.root / 'owner-closures' / (other + '.json')
        other_path.write_bytes(old.read_bytes())
        with pytest.raises(StateRefused, match='incident_closure_invalid'):
            runtime.state.incidents()


def test_history_recovery_is_single_session_and_stale_proof_cannot_replay(tmp_path):
    from weather.market.lfc_campaign_history import history_refusals, record_owner_recovery
    ledger = reconciled_legacy(tmp_path)
    other = tmp_path / 'second-history'
    other.mkdir()
    (other / 'journal.jsonl').write_text('retained failed second-session evidence\n')
    ledger.record('session_start', session_id='second', counted=True,
                  owner_local_date='2026-11-10', directory='second-history')
    ledger.record('session_end', session_id='second', unknown_submit=True, cleanup_ok=False)
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path/'unused', release={},
                          clock=Clock(), control_root=tmp_path/'control', task_enabled=lambda:False)
        read = account_read(runtime)
        read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
        proof = runtime.core_proof(ledger, read)
        assert set(history_refusals(ledger, tmp_path)) == {'S0c-1','second'}
        record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                              now=NOW, containment_proven=True)
        assert set(history_refusals(ledger, tmp_path)) == {'second'}
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.enroll(NOW)
        # Old clean proof has the wrong ledger head, and the recovered issue
        # is no longer eligible. Neither duplicate nor cross-session replay works.
        for session in ('S0c-1','second'):
            with pytest.raises(ValueError, match='owner_history_repair_required'):
                record_owner_recovery(ledger, tmp_path, session, account_read=read, proof=proof,
                                      now=NOW, containment_proven=True)
        assert len(ledger.history_recoveries) == 1
        assert ledger.sessions['S0c-1']['end']['unknown_submit'] is True


def configure_runtime(runtime, monkeypatch):
    from weather.market import lfc_campaign_runtime as adapter, lfc_cli, re1_owner_checks
    from weather.market import lfc_session_status
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', runtime.pilot_root.parent / 'fixture-owner-stop')
    @contextmanager
    def admission():
        yield
    def fresh_account():
        row = account_read(runtime)
        row['since'] = str(int(datetime.fromisoformat(runtime.state.ledger.rows[0]['recorded_at_utc']).timestamp()))
        stamp = runtime.clock.now().isoformat()
        row['started_at_utc'] = row['ended_at_utc'] = stamp
        for component in row['component_times'].values():
            component['started_at_utc'] = component['ended_at_utc'] = stamp
        return row
    runtime.lease = SimpleNamespace(check=lambda: None)
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'read_account', fresh_account)
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(adapter, 'workstation_headroom', lambda: {'fixture': True})
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **k: True)
    monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f' * 40)
    monkeypatch.setattr(runtime, 'readiness', lambda *a, **k: {'fixture': True})


def recover(runtime, incident, monkeypatch):
    path = runtime.state.root / 'incidents' / (incident + '.json')
    monkeypatch.setattr('builtins.input', lambda: 'recover ' + file_sha(path)[:12])
    assert cli.owner_recover(runtime, incident) == 0


def reopen_runtime(runtime, monkeypatch):
    old = runtime.state
    ledger = Ledger.open(old.ledger.path, clock=runtime.clock.now, maker_address=MAKER)
    state = AccountState(old.root.parent, ledger)
    reopened = Runtime(state=state, pilot_root=runtime.pilot_root, policy_path=runtime.policy_path,
                       release={}, clock=runtime.clock, control_root=runtime.control_root,
                       task_enabled=lambda: True, hold_path=runtime.hold_path)
    configure_runtime(reopened, monkeypatch)
    reopened.state.verify()
    return reopened


def next_policy(runtime, day):
    row = policy_row()
    date = '2026-11-' + str(day)
    row['entries'][0].update(local_date=date, window_start_utc=date + 'T16:00:00Z',
                              window_end_utc=date + 'T17:00:00Z')
    target = datetime.fromisoformat(date + 'T16:00:00+00:00')
    runtime.clock.sleep((target - runtime.clock.now()).total_seconds())
    return parse_policy(row)


@pytest.mark.parametrize('second_file', ['journal.jsonl', 'submit-1.ack.json', 'result'])
@pytest.mark.parametrize('reboot', [False, True])
def test_recurrent_evidence_fault_requires_new_owner_decision(tmp_path, monkeypatch, second_file, reboot):
    """T037r1 N1: same journal/different ACK/result, including a reopened ledger."""
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        runtime.save_result(claim, result)
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        runtime.state.close(claim, proof, NOW)
        initial_dates = runtime.state.consumed_dates()
        journal = directory / 'journal.jsonl'
        original = journal.read_bytes()
        journal.unlink()
        with pytest.raises(StateRefused):
            runtime.state.require_retained_evidence()
        journal.write_bytes(original)
        first = runtime.state.incidents()[0]
        recover(runtime, first['attempt_id'], monkeypatch)
        closure = runtime.state.root / 'owner-closures' / (first['attempt_id'] + '.json')
        first_closure_sha = file_sha(closure)
        first_incident_sha = file_sha(runtime.state.root / 'incidents' / closure.name)
        if reboot:
            runtime = reopen_runtime(runtime, monkeypatch)
        following = next_policy(runtime, 12)
        prepared = runtime.pre_go_once(following.entries[0], following)
        path = (runtime.state.root / 'results' / (claim['attempt_id'] + '.json') if second_file == 'result'
                else directory / second_file)
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(StateRefused):
            runtime.state.require_retained_evidence()
        # Re-observing an open loss is idempotent, even after re-opening state.
        count = len(runtime.state.ledger.autostart_incidents)
        if reboot:
            runtime = reopen_runtime_after_missing_result(runtime, monkeypatch)
        with pytest.raises(StateRefused):
            runtime.state.require_retained_evidence()
        assert len(runtime.state.ledger.autostart_incidents) == count == 2
        path.write_bytes(original)
        runtime.state.require_retained_evidence()
        second = runtime.state.incidents()[0]
        assert second['attempt_id'] != first['attempt_id']
        assert second['source_attempt_id'] == first['source_attempt_id'] == claim['attempt_id']
        assert second['detection_sequence'] > first['detection_sequence']
        expected_artifact = ('results/' + claim['attempt_id'] + '.json' if second_file == 'result'
                             else 'private/' + second_file)
        assert second['artifact'] == expected_artifact
        assert file_sha(closure) == first_closure_sha
        assert file_sha(runtime.state.root / 'incidents' / closure.name) == first_incident_sha
        assert initial_dates <= runtime.state.consumed_dates()
        with pytest.raises(StateRefused, match='prior_money_unresolved'):
            runtime.pre_go_once(following.entries[0], following)
        with pytest.raises(StateRefused, match='account_incident_latched'):
            runtime.state.claim(following.entries[0], following, runtime.clock.now(), prepared=prepared)
        authority = ScheduledAuthority(runtime, {'attempt_id': 'f' * 32}, following.entries[0], following, prepared)
        assert 'account_incident_latched' in authority.start_gates(
            ledger=runtime.state.ledger, now=runtime.clock.now(), maker_address=MAKER, open_orders=[], positions=[])
        assert len(list((runtime.state.root / 'claims').glob('*.json'))) == 1
        recover(runtime, second['attempt_id'], monkeypatch)
        assert runtime.state.incidents() == [] and file_sha(closure) == first_closure_sha
        assert len(list((runtime.state.root / 'owner-closures').glob('*.json'))) == 2
        assert runtime.state.ledger.counted_sessions() == 1
        later = next_policy(runtime, 13)
        ready = runtime.pre_go_once(later.entries[0], later)
        admitted = runtime.state.claim(later.entries[0], later, runtime.clock.now(), prepared=ready)
        assert admitted['local_date'] == '2026-11-13'


def reopen_runtime_after_missing_result(runtime, monkeypatch):
    """A reboot opens the ledger even while ordinary evidence verification refuses."""
    old = runtime.state
    ledger = Ledger.open(old.ledger.path, clock=runtime.clock.now, maker_address=MAKER)
    state = AccountState(old.root.parent, ledger)
    reopened = Runtime(state=state, pilot_root=runtime.pilot_root, policy_path=runtime.policy_path,
                       release={}, clock=runtime.clock, control_root=runtime.control_root,
                       task_enabled=lambda: True, hold_path=runtime.hold_path)
    configure_runtime(reopened, monkeypatch)
    return reopened


def test_recurrent_fault_while_attempt_pending_keeps_each_occurrence_independent(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        runtime.save_result(claim, result)
        journal = directory / 'journal.jsonl'
        saved = journal.read_bytes()
        journal.unlink()
        with pytest.raises(StateRefused):
            runtime.postcheck(claim, runtime.saved_result(claim))
        journal.write_bytes(saved)
        first = runtime.state.incidents()[0]['attempt_id']
        other = 'b' * 32
        runtime.state.latch(other, 'independent_money_contradiction', NOW)
        recover(runtime, first, monkeypatch)
        assert runtime.state.pending()
        journal.unlink()
        with pytest.raises(StateRefused):
            runtime.postcheck(claim, runtime.saved_result(claim))
        journal.write_bytes(saved)
        active = runtime.state.incidents()
        second = next(r['attempt_id'] for r in active if r['source_attempt_id'] == claim['attempt_id'])
        assert second != first and len(active) == 2
        recover(runtime, second, monkeypatch)
        assert [r['attempt_id'] for r in runtime.state.incidents()] == [other]
        assert runtime.state.pending()
        recover(runtime, other, monkeypatch)
        assert runtime.state.incidents() == [] and runtime.state.pending() == []


@pytest.mark.parametrize('reason', ['private_evidence_fault', 'clock_or_resume_uncertain'])
def test_reusable_incident_identity_has_new_sequence_after_recovery(tmp_path, monkeypatch, reason):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        source = 'legacy-history' if reason == 'private_evidence_fault' else 'c' * 32
        def detect():
            if reason == 'private_evidence_fault':
                return runtime.state.evidence_fault(source, artifact='history/retained-original')
            return runtime.state.latch(source, reason, runtime.clock.now())
        first = detect()
        assert detect() == first
        recover(runtime, first, monkeypatch)
        closure = runtime.state.root / 'owner-closures' / (first + '.json')
        sha = file_sha(closure)
        runtime = reopen_runtime(runtime, monkeypatch)
        second = detect()
        assert second != first and detect() == second
        assert runtime.state.incidents()[0]['detection_sequence'] == 2
        assert file_sha(closure) == sha
        recover(runtime, second, monkeypatch)
        third = detect()
        assert third not in {first, second} and runtime.state.incidents()[0]['detection_sequence'] == 3


def test_distinct_artifacts_are_independent_while_first_occurrence_open(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        source = 'a' * 32
        first = runtime.state.evidence_fault(source, artifact='private/journal.jsonl')
        second = runtime.state.evidence_fault(source, artifact='private/submit-1.ack.json')
        assert first != second
        for _ in range(5):
            assert runtime.state.evidence_fault(source, artifact='private/journal.jsonl') == first
            assert runtime.state.evidence_fault(source, artifact='private/submit-1.ack.json') == second
        assert len(runtime.state.ledger.autostart_incidents) == 2
        recover(runtime, first, monkeypatch)
        assert [row['attempt_id'] for row in runtime.state.incidents()] == [second]
        recover(runtime, second, monkeypatch)
        assert runtime.state.incidents() == []


def test_old_owner_receipt_cannot_clear_a_new_occurrence(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        first = runtime.state.evidence_fault('a' * 32, artifact='private/journal.jsonl')
        recover(runtime, first, monkeypatch)
        closure = runtime.state.root / 'owner-closures' / (first + '.json')
        old = closure.read_bytes()
        second = runtime.state.evidence_fault('a' * 32, artifact='private/journal.jsonl')
        (closure.parent / (second + '.json')).write_bytes(old)
        with pytest.raises(StateRefused, match='incident_closure_invalid'):
            runtime.state.incidents()
        assert closure.read_bytes() == old


def test_recurrent_legacy_history_file_loss_requires_fresh_owner_recovery(tmp_path, monkeypatch):
    from tests.market.test_lfc_cli import ledger_with_baselines
    ledger = ledger_with_baselines(tmp_path)
    clock = Clock()
    ledger.clock = clock.now
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'unused.json', release={},
                          clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: True,
                          hold_path=tmp_path / 'fixtureHOLD')
        configure_runtime(runtime, monkeypatch)
        directory, _ = private_result(runtime, None, faults=(), legacy=True)
        state.enroll(NOW)
        first_closure = None
        for index, name in enumerate(('journal.jsonl', 'submit-1.ack.json')):
            path = directory / name
            original = path.read_bytes()
            path.unlink()
            with pytest.raises(StateRefused, match='historical_recovery_evidence_fault'):
                runtime.state.require_history()
            count = len(runtime.state.ledger.autostart_incidents)
            with pytest.raises(StateRefused):
                runtime.state.require_history()
            assert len(runtime.state.ledger.autostart_incidents) == count == index + 1
            path.write_bytes(original)
            runtime.state.require_history()
            active = runtime.state.incidents()
            assert len(active) == 1 and active[0]['source_attempt_id'] == 'legacy-history'
            assert active[0]['artifact'].endswith('/' + name)
            with pytest.raises(StateRefused, match='account_incident_latched'):
                policy = parse_policy(policy_row())
                runtime.state.claim(policy.entries[0], policy, runtime.clock.now())
            recover(runtime, active[0]['attempt_id'], monkeypatch)
            closure = runtime.state.root / 'owner-closures' / (active[0]['attempt_id'] + '.json')
            if first_closure is None:
                first_closure = (closure, closure.read_bytes())
                runtime = reopen_runtime(runtime, monkeypatch)
            assert first_closure[0].read_bytes() == first_closure[1]
        assert runtime.state.incidents() == [] and runtime.state.ledger.counted_sessions() == 1


def test_closed_legacy_incident_identity_cannot_suppress_recurrence(tmp_path, monkeypatch):
    from weather.market.mm_stage2_hold import digest
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        source = 'a' * 32
        legacy = digest({'attempt': source, 'reason': 'private_evidence_fault'})[:32]
        sha = runtime.state.save('incidents/' + legacy + '.json', {
            'attempt_id': legacy, 'source_attempt_id': source, 'reason': 'private_evidence_fault',
            'at_utc': NOW.isoformat(), 'local_date': '2026-11-11'})
        runtime.state.ledger.record('autostart_incident', attempt_id=legacy, file_sha256=sha)
        recover(runtime, legacy, monkeypatch)
        closure = runtime.state.root / 'owner-closures' / (legacy + '.json')
        old = closure.read_bytes()
        new = runtime.state.evidence_fault(source, artifact='private/journal.jsonl')
        assert new != legacy and runtime.state.incidents()[0]['detection_sequence'] == 2
        assert closure.read_bytes() == old


def test_partially_created_incident_cannot_be_closed_or_ignored(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        orphan = 'a' * 32
        runtime.state.save('incidents/' + orphan + '.json', {
            'attempt_id': orphan, 'reason': 'private_evidence_fault', 'source_attempt_id': 'legacy-history',
            'artifact': 'history/retained-original', 'detection_sequence': 1})
        with pytest.raises(StateRefused, match='incident_continuity'):
            runtime.state.incidents()
        monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('refuse before account read'))
        with pytest.raises(StateRefused, match='incident_continuity'):
            recover(runtime, orphan, monkeypatch)
        assert not list((runtime.state.root / 'owner-closures').glob('*.json'))


@pytest.mark.parametrize('name', ['journal.jsonl', 'submit-1.ack.json', 'result'])
def test_recovery_of_closed_occurrence_cannot_waive_missing_original(tmp_path, monkeypatch, name):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        runtime.save_result(claim, result)
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        runtime.state.close(claim, proof, NOW)
        path = (runtime.state.root / 'results' / (claim['attempt_id'] + '.json') if name == 'result'
                else directory / name)
        old = path.read_bytes()
        path.unlink()
        with pytest.raises(StateRefused):
            runtime.state.require_retained_evidence()
        incident = runtime.state.ledger.autostart_incidents[-1]['attempt_id']
        with pytest.raises(StateRefused):
            recover(runtime, incident, monkeypatch)
        assert not list((runtime.state.root / 'owner-closures').glob('*.json'))
        path.write_bytes(old)
        recover(runtime, incident, monkeypatch)
        assert runtime.state.incidents() == []


def test_owner_check_refuses_a_restored_but_unrecovered_occurrence(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        configure_runtime(runtime, monkeypatch)
        incident = runtime.state.evidence_fault('a' * 32, artifact='private/journal.jsonl')
        monkeypatch.setattr(cli, 'load_release', lambda *a: {
            'maker_address': MAKER, 'campaign_path': str(runtime.policy_path)})
        monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
        monkeypatch.setattr(cli, 'bound_state', lambda *a: (runtime.pilot_root, runtime.state))
        @contextmanager
        def synthetic_account(*a, **k):
            yield
        monkeypatch.setattr(cli, 'account_lease', synthetic_account)
        monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
        args = ['check', '--release', 'synthetic', '--release-sha256', 'f' * 64]
        assert cli.main(args) == 1
        recover(runtime, incident, monkeypatch)
        assert cli.main(args) == 0
