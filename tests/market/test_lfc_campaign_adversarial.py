"""Desired-behavior regressions for the independent T037 witnesses.

Guards: B032 R1-R4, legacy ambiguity and retained private/public evidence.
All account, clock, process and Scheduler inputs are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, NOW, policy_row
from tests.market.test_lfc_campaign_runtime import account_read, runtime_at, health
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_recording_io import file_sha, write_new
from tests.market.lfc_campaign_fixtures import private_result


def reconciled_legacy(tmp_path):
    from tests.market.test_lfc_cli import lost_ack, FakeVenue, venue_order
    from weather.market.lfc_cli import reconcile_ledger
    ledger = lost_ack(tmp_path)
    venue = FakeVenue([], {'o1': {'id': 'o1', 'status': 'CANCELED', 'size_matched': '0'},
                           'o2': venue_order('o2')})
    report, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda _: None)
    assert report['adopted_order_ids'] == ['o2'] and report['closed_sessions'] == ['S0c-1']
    assert ledger.sessions['S0c-1']['end']['unknown_submit'] is True
    ledger.clock = Clock().now
    return ledger


def test_witness_enrollment_forgets_legacy_unknown_submission(tmp_path):
    """Real lost-ACK reconcile cannot silently become the owner recovery ceremony."""
    ledger = reconciled_legacy(tmp_path)
    original = deepcopy(ledger.sessions['S0c-1']['end'])
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.enroll(NOW)
        assert not state.root.exists() and ledger.enrollment is None
        assert ledger.sessions['S0c-1']['end'] == original


def test_explicit_owner_history_recovery_preserves_flags_and_consumed_date(tmp_path):
    from weather.market.lfc_campaign_history import history_refusals, record_owner_recovery
    from weather.market.lfc_campaign_runtime import Runtime
    ledger = reconciled_legacy(tmp_path)
    original = deepcopy(ledger.sessions['S0c-1']['end'])
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'unused.json', release={}, clock=Clock(),
                          control_root=tmp_path / 'control', task_enabled=lambda: False)
        read = account_read(runtime)
        read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
        proof = runtime.core_proof(ledger, read)
        assert proof['money_accounting_complete'] and proof['cleanup_proven']
        with pytest.raises(ValueError, match='owner_history_repair_required'):
            record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                                  now=NOW, containment_proven=False)
        record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                              now=NOW, containment_proven=True)
        assert history_refusals(ledger, tmp_path) == {}
        state.enroll(NOW)
        policy = parse_policy(policy_row())
        state.claim(policy.entries[0], policy, NOW)
        assert ledger.sessions['S0c-1']['end'] == original
        recovery = tmp_path / ledger.history_recoveries[0]['file']
        recovery.rename(recovery.with_suffix('.lost'))
        with pytest.raises(StateRefused, match='historical_recovery_evidence_fault'):
            state.require_history()


def test_qualified_intentional_s0_exercises_are_not_blanket_rejected(tmp_path):
    from tests.market.test_lfc_cli import ledger_with_baselines, pass_all_session0
    ledger = ledger_with_baselines(tmp_path)
    pass_all_session0(ledger, tmp_path)
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        state.enroll(NOW)
        state.require_history()


def test_proved_f0_history_can_enroll_but_later_legacy_ambiguity_blocks_claim(tmp_path):
    from tests.market.test_lfc_campaign import state_at
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
        state.ledger.record('session_start', session_id='manual', counted=True, owner_local_date='2026-11-10')
        state.ledger.record('session_end', session_id='manual', unknown_submit=True, cleanup_ok=False)
        policy = parse_policy(policy_row())
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            state.claim(policy.entries[0], policy, NOW)
        assert not list((state.root / 'claims').glob('*.json'))


def test_proved_normal_f0_history_remains_enrollable(tmp_path):
    from tests.market.test_lfc_cli import ledger_with_baselines
    ledger = ledger_with_baselines(tmp_path)
    ledger.record('session_start', session_id='proved-F0', counted=True, owner_local_date='2026-11-09')
    ledger.record('session_end', session_id='proved-F0', unknown_submit=False, cleanup_ok=True,
                  inventory_proven=True, evidence_complete=True, reason='fixed_end')
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        AccountState(tmp_path / 'state', ledger).enroll(NOW)


@pytest.mark.parametrize('rows,flags', [
    ([{'event': 'scoring_missed'}, {'event': 'cleanup_cancel_unavailable', 'order_id': 'o'}], {}),
    ([{'event': 'ordinary'}], {'failure_type': 'OSError', 'inventory_proven': False}),
])
def test_witness_unproved_private_evidence_is_accepted(tmp_path, rows, flags):
    """T037's former accepted weak journal must now be refused."""
    from weather.market.lfc_campaign_proof import local_money_proof
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        (directory / 'journal.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        prediction = json.loads((directory / 'prediction.json').read_text())
        prediction.update(flags, journal_sha256=file_sha(directory / 'journal.jsonl'))
        (directory / 'prediction.json').write_text(json.dumps(prediction))
        result['outcome']['evidence_sha256'] = {name: file_sha(directory / name) for name in
                                               ('journal.jsonl', 'prediction.json', 'session_end.json')}
        proof = local_money_proof(directory, ledger=runtime.state.ledger, session_id='s',
                                  attempt_id=claim['attempt_id'], outcome=result['outcome'])
        assert not proof['complete'] and proof['unknown_submit']


@pytest.mark.parametrize('fault', ['unclassified_core_fault', 'unknown_private_error'])
def test_scoring_gap_never_excuses_an_unclassified_core_fault(tmp_path, fault):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim, faults=('scoring_missed', fault))
        assert not result['local_money_proof']['complete']


@pytest.mark.parametrize('failure_type', ['OSError', 'RuntimeError', 'invented'])
def test_failure_type_is_never_a_blanket_evidence_exemption(tmp_path, failure_type):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim, failure_type=failure_type)
        assert not result['local_money_proof']['complete']


def test_witness_pending_postcheck_accepts_deleted_private_journal(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        assert result['local_money_proof']['complete']
        runtime.save_result(claim, result)
        (directory / 'journal.jsonl').rename(directory / 'journal-lost.fixture')
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
        with pytest.raises(StateRefused, match='retained_private_evidence_fault'):
            runtime.postcheck(claim, runtime.saved_result(claim))
        assert runtime.state.ledger.autostart_incidents
        assert not list((runtime.state.root / 'closed').glob('*.json'))


@pytest.mark.parametrize('stage', ['pending', 'closed'])
@pytest.mark.parametrize('name', ['journal.jsonl', 'prediction.json', 'session_end.json', 'result',
                                 'submit-1.intent.json', 'submit-1.ack.json'])
@pytest.mark.parametrize('damage', ['delete', 'truncate', 'corrupt', 'mismatch'])
def test_retained_core_files_are_required_pending_and_after_close(tmp_path, monkeypatch, stage, name, damage):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        assert result['local_money_proof']['complete']
        runtime.save_result(claim, result)
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
        if stage == 'closed':
            proof = runtime.postcheck(claim, runtime.saved_result(claim))
            runtime.state.close(claim, proof, NOW)
        path = runtime.state.root / 'results' / (claim['attempt_id'] + '.json') if name == 'result' else directory / name
        if damage == 'delete':
            path.unlink()
        elif damage == 'truncate':
            raw = path.read_bytes()
            path.write_bytes(raw[:max(1, len(raw) // 2)])
        elif damage == 'corrupt':
            path.write_bytes(b'{corrupt}')
        else:
            path.write_bytes(path.read_bytes() + b' ')
        with pytest.raises(StateRefused):
            if stage == 'pending':
                runtime.postcheck(claim, runtime.saved_result(claim))
            else:
                runtime.state.require_retained_evidence()
        assert runtime.state.ledger.autostart_incidents


def test_supported_scoring_gap_with_complete_core_evidence_can_close(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim)
        assert result['local_money_proof']['complete']
        runtime.save_result(claim, result)
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        assert proof['money_accounting_complete'] and not proof['research_evidence_complete']
        runtime.state.close(claim, proof, NOW)
        runtime.state.require_retained_evidence()
        assert runtime.state.pending() == []


def test_acknowledged_terminal_read_outage_defers_then_finishes_without_adoption(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim, faults=('terminal_order_unavailable',), terminal_read_gap=True)
        assert result['local_money_proof']['complete']
        runtime.save_result(claim, result)
        runtime.lease = SimpleNamespace(check=lambda: None)
        read = account_read(runtime)
        monkeypatch.setattr(runtime, 'read_account', lambda: read)
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        assert not proof['money_accounting_complete'] and not proof['cleanup_proven'] and not proof['unknown_submit']
        assert not runtime.state.incidents() and runtime.state.ledger.L_resting() == 10
        read['terminal_orders'] = {'o': {'row': {'id': 'o', 'status': 'CANCELED', 'size_matched': '0'},
                                       'started_at_utc': NOW.isoformat(), 'ended_at_utc': NOW.isoformat()}}
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        assert proof['money_accounting_complete'] and proof['cleanup_proven'] and not proof['unknown_submit']
        assert not proof['raw_evidence_flags']['inventory_proven']
        assert not any(row['event'] == 'leg_adopt' for row in runtime.state.ledger.rows)
        runtime.state.close(claim, proof, NOW)


@pytest.mark.parametrize('faults', ['none', 'scoring', 'scoring_and_core'])
def test_actual_inert_controller_produces_qualifiable_chained_private_evidence(tmp_path, faults):
    from tests.market.test_lfc_pilot import counted_table, PILOT_SLUG, CONDITION, OTHER, REGISTRY
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.lfc_pilot import PilotSession
    from weather.market.re1_rehearsal import RehearsalVenue
    from weather.market.lfc_cli import finish_session
    from weather.market.lfc_campaign_proof import local_money_proof
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        runtime.lease = SimpleNamespace(check=lambda: None)
        ledger = runtime.state.ledger
        ledger.record('session_start', session_id='s', counted=True, owner_local_date='2026-11-11',
                      autostart_attempt_id=claim['attempt_id'])
        prepared = {'baseline': runtime.original_baseline(ledger), 'account_read': account_read(runtime),
                    'expires_utc': (NOW + timedelta(seconds=120)).isoformat()}
        authority = ScheduledAuthority(runtime, claim, policy.entries[0], policy, prepared)
        table = counted_table(runtime.clock)
        confirmation = authority.confirmation(table, ledger)
        directory = runtime.pilot_root / 'actual-private'
        venue = RehearsalVenue(table['rows'][0]['snapshot'], directory, clock=runtime.clock)
        venue.balances = lambda: {'available_collateral': '500'}
        venue.trades = lambda: []
        exclusion = {'event_slug': PILOT_SLUG, 'condition_ids': [CONDITION, OTHER],
                     'timezone_name': REGISTRY['denver'].timezone}
        session = PilotSession(ledger=ledger, session_id='s', profile=authority.profile, root=runtime.pilot_root,
                               exclusion=exclusion, venue=venue, public=venue, table=table, clock=runtime.clock,
                               directory=directory, mode='live', confirmation=confirmation, scheduled_authority=authority,
                               attempt={'counted': True, 'session_number': 1})
        if faults != 'none':
            def scoring_unavailable(*_):
                raise TimeoutError('synthetic scoring gap')
            venue.scoring = scoring_unavailable
        if faults == 'scoring_and_core':
            original_scoring = session.sample_scoring
            def mixed_fault():
                original_scoring()
                session.evidence_failed = True  # An unrelated, unclassified core failure.
            session.sample_scoring = mixed_fault
        session.deadline = runtime.clock.monotonic() + 1  # End only the synthetic controller loop early.
        result = session.run()
        assert result['post_count'] == 2 and result['cleanup_ok'] == (faults == 'none'), result
        finish_session(ledger, 's', result)
        write_new(directory / 'session_end.json', {'session_id': 's', **{k: result[k] for k in
                  ('unknown_submit', 'inventory_proven', 'evidence_complete')}})
        outcome = {'evidence_sha256': {name: file_sha(directory / name) for name in
                                      ('journal.jsonl', 'prediction.json', 'session_end.json')}}
        proof = local_money_proof(directory, ledger=ledger, session_id='s', attempt_id=claim['attempt_id'], outcome=outcome)
        assert proof['complete'] == (faults != 'scoring_and_core'), proof


def test_witness_recovered_public_gap_becomes_complete(tmp_path):
    import hashlib
    from weather.market.lfc_campaign_sidecar import health_receipt
    row = health(tmp_path, gap=False, final=True)
    row['counts'].update(gaps=1, coverage_gap_end=1)
    row['secondary_errors'] = ['a retained recorder error']
    body = {k: v for k, v in row.items() if k != 'health_receipt_sha256'}
    row['health_receipt_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    (tmp_path / 'health.json').write_text(json.dumps(row))
    proof = health_receipt(tmp_path, event_slug='event', health_schema='fixture', final=True)
    assert proof['ready_now'] and proof['source_gaps'] and proof['historical_gaps']
    assert not proof['research_evidence_complete'] and not proof['whole_session_coverage_proven']
    assert proof['writer_counts']['gaps'] == 1 and proof['errors']


def test_enabled_sidecar_refuses_before_date_claim_or_process_start(tmp_path):
    from weather.market.lfc_campaign_policy import PolicyRefused, parameter_support
    from weather.market.lfc_campaign_sidecar import Sidecar
    row = policy_row()
    row['sidecar'] = {'enabled': True, 'release_manifest': str(tmp_path / 'manifest.json')}
    with pytest.raises(PolicyRefused, match='unsupported_sidecar_interval_coverage'):
        parse_policy(row)
    assert parameter_support()['sidecar']['enabled_values'] == [False]
    with pytest.raises(ValueError, match='unsupported_sidecar_interval_coverage'):
        Sidecar(manifest=tmp_path / 'absent.json', output=tmp_path / 'capture', scope={}, started=NOW, seconds=21600,
                process_factory=lambda *a, **k: pytest.fail('no child may start'))
    assert not (tmp_path / 'capture').exists()
    row['sidecar']['enabled'] = False
    assert parse_policy(row).raw['sidecar']['enabled'] is False


def test_recovered_public_gap_remains_in_postcheck_quality_flags(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim, faults=())
        result['public_coverage'] = {'configured': True, 'gap': None, 'source_gaps': True,
                                     'historical_gaps': True, 'research_evidence_complete': False}
        runtime.save_result(claim, result)
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
        proof = runtime.postcheck(claim, runtime.saved_result(claim))
        assert proof['money_accounting_complete'] and not proof['research_evidence_complete']
