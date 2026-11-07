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


def test_legacy_lost_ack_reconcile_blocks_enrollment(tmp_path):
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
    from weather.market.lfc_campaign_runtime import Runtime
    ledger = ledger_with_baselines(tmp_path)
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'unused.json', release={},
                          clock=Clock(), control_root=tmp_path / 'control', task_enabled=lambda: False)
        _, result = private_result(runtime, None, faults=(), legacy=True)
        assert result['local_money_proof']['complete']
        state.enroll(NOW)


@pytest.mark.parametrize('name', ['journal.jsonl', 'prediction.json', 'session_end.json',
                                 'submit-1.intent.json', 'submit-1.ack.json'])
@pytest.mark.parametrize('enrolled', [False, True])
def test_legacy_private_evidence_is_required_at_enrollment_and_later_admission(tmp_path, name, enrolled):
    from tests.market.test_lfc_cli import ledger_with_baselines
    from weather.market.lfc_campaign_runtime import Runtime
    ledger = ledger_with_baselines(tmp_path)
    ledger.clock = Clock().now
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger)
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'unused.json', release={},
                          clock=Clock(), control_root=tmp_path / 'control', task_enabled=lambda: False)
        directory, result = private_result(runtime, None, faults=(), legacy=True)
        assert result['local_money_proof']['complete']
        if enrolled:
            state.enroll(NOW)
        path = directory / name
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(StateRefused):
            if enrolled:
                state.require_history()
            else:
                state.enroll(NOW)
        if enrolled:
            assert state.ledger.autostart_incidents
            path.write_bytes(original)  # Restoring bytes cannot clear the recorded incident.
            policy = parse_policy(policy_row())
            with pytest.raises(StateRefused, match='account_incident_latched'):
                state.claim(policy.entries[0], policy, NOW)


@pytest.mark.parametrize('rows,flags', [
    ([{'event': 'scoring_missed'}, {'event': 'cleanup_cancel_unavailable', 'order_id': 'o'}], {}),
    ([{'event': 'ordinary'}], {'failure_type': 'OSError', 'inventory_proven': False}),
])
def test_unproved_private_evidence_is_refused(tmp_path, rows, flags):
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


def test_pending_postcheck_refuses_deleted_private_journal(tmp_path, monkeypatch):
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
@pytest.mark.parametrize('seconds', [300, 21600])
def test_actual_inert_controller_produces_qualifiable_chained_private_evidence(tmp_path, faults, seconds):
    from tests.market.test_lfc_pilot import counted_table, PILOT_SLUG, CONDITION, OTHER, REGISTRY
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.lfc_pilot import PilotSession
    from weather.market.re1_rehearsal import RehearsalVenue
    from weather.market.lfc_cli import finish_session
    from weather.market.lfc_campaign_proof import local_money_proof
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        row = policy_row()
        row['max_session_seconds'] = row['entries'][0]['duration_seconds'] = seconds
        policy = parse_policy(row)
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
        reads = []
        def delayed_balance():
            if not reads:
                runtime.clock.sleep(1)  # Realistic nonzero opening latency at the supported lower boundary.
            reads.append(True)
            return {'available_collateral': '500'}
        venue.balances = delayed_balance
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
        session.deadline = runtime.clock.monotonic() + 3  # End only the synthetic controller loop early.
        result = session.run()
        assert result['post_count'] == 2 and result['cleanup_ok'] == (faults == 'none'), result
        finish_session(ledger, 's', result)
        write_new(directory / 'session_end.json', {'session_id': 's', **{k: result[k] for k in
                  ('unknown_submit', 'inventory_proven', 'evidence_complete')}})
        outcome = {'evidence_sha256': {name: file_sha(directory / name) for name in
                                      ('journal.jsonl', 'prediction.json', 'session_end.json')}}
        proof = local_money_proof(directory, ledger=ledger, session_id='s', attempt_id=claim['attempt_id'], outcome=outcome)
        assert proof['complete'] == (faults != 'scoring_and_core'), proof


def test_recovered_public_gap_remains_incomplete(tmp_path):
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


@pytest.mark.parametrize('seconds', [60, 120, 179, 180, 299])
@pytest.mark.parametrize('field', ['max_session_seconds', 'duration_seconds'])
def test_unsupported_short_duration_does_not_consume_date(tmp_path, seconds, field):
    from weather.market.lfc_campaign import CampaignCoordinator
    from weather.market.lfc_campaign_policy import PolicyRefused
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        row = policy_row()
        if field == 'max_session_seconds':
            row[field] = seconds
        else:
            row['entries'][0][field] = seconds
        coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock,
                                          control_root=tmp_path / 'control')
        with pytest.raises(PolicyRefused):
            coordinator.tick(lambda: parse_policy(row))
        assert runtime.state.claims() == [] and runtime.state.skips() == []
        assert not runtime.state.ledger.sessions


def test_duration_support_matches_preclaim_boundary_and_keeps_default_terms(tmp_path):
    from dataclasses import replace
    from weather.market.lfc_campaign_policy import MIN_SESSION_SECONDS, PolicyRefused, parameter_support
    row = policy_row()
    assert parse_policy(row).entries[0].seconds == 21600
    row['max_session_seconds'] = row['entries'][0]['duration_seconds'] = MIN_SESSION_SECONDS
    policy = parse_policy(row)
    assert policy.entries[0].permits(NOW)
    assert parameter_support()['entries']['duration_min_seconds'] == 300
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        entry = replace(policy.entries[0], seconds=MIN_SESSION_SECONDS - 1)
        with pytest.raises(PolicyRefused, match='unsupported_duration_seconds'):
            runtime.state.claim(entry, policy, NOW)
        assert runtime.state.claims() == [] and runtime.state.skips() == []


@pytest.mark.parametrize('market,zone,hour', [('toronto','America/Toronto',5), ('denver','America/Denver',7)])
def test_dst_native_midnights_and_folds(market, zone, hour):
    from weather.market.lfc_horizon import local_event_dte
    row = {'market_id': market, 'market_timezone': zone, 'target_date': '2026-11-12'}
    before = datetime(2026,11,12,hour,0,0,tzinfo=timezone.utc) - timedelta(microseconds=1)
    assert local_event_dte(row,before) == 1
    assert local_event_dte(row,before+timedelta(microseconds=1)) == 0
    row['target_date'] = '2026-11-02'
    # Repeated 01:30 at the fall transition must not change the native day.
    first = datetime(2026,11,1,hour,30,tzinfo=timezone.utc)
    assert local_event_dte(row,first) == local_event_dte(row,first+timedelta(hours=1)) == 1


def test_witness_cancel_outage_leaves_resting_orders_and_reserve(tmp_path):
    from tests.market.test_lfc_pilot import setup
    session, venue, clock, ledger = setup(tmp_path)
    def outage(*args, **kwargs):
        raise ConnectionError('synthetic cancellation outage')
    venue.cancel = venue.cancel_all = outage
    result = session.run(rehearsal_seconds=1)
    assert not result['cleanup_ok'] and venue.open_orders()
    assert ledger.L_resting() > 0 and ledger.unresolved_legs()
    assert all(row['expiration'] == int(session.end.timestamp()) + 60 for row in venue.open_orders())


@pytest.mark.parametrize('outage', [False, True])
def test_cancellation_requested_and_proven_remain_distinct_with_gtd_contract(tmp_path, outage):
    from tests.market.test_lfc_pilot import setup, events
    from weather.market.lfc_session_status import SessionStatus
    session, venue, clock, ledger = setup(tmp_path)
    if outage:
        def unavailable(*_, **__):
            raise ConnectionError('synthetic cancellation outage')
        venue.cancel = venue.cancel_all = unavailable
    status = SessionStatus(kind='fixture', clock=clock.now, monotonic=clock.monotonic)
    status.directory, status.stop_file = tmp_path / 'status', tmp_path / 'STOP'
    status.bind(session.session_id, directory=session.directory, selection=session.table['rows'][0], ledger=ledger)
    status.session = session
    result = session.run(rehearsal_seconds=1)
    status.open_rows = venue.open_orders()
    outcome = status.finish(success=result['cleanup_ok'])
    assert outcome['cancellation_requested'] is True
    assert outcome['cancellation_proven'] is (not outage)
    for row in events(session, 'submit_request'):
        # Arithmetic against the documented venue threshold, not a fake venue
        # claiming it has observed server expiry during a cancellation outage.
        assert row['request']['expiration'] - 60 <= session.end.timestamp()
        assert session.end.timestamp() - (row['request']['expiration'] - 60) < 1
    if outage:
        assert not outcome['cleanup_ok'] and outcome['state'] != 'COMPLETE'
        assert ledger.L_resting() > 0


def test_every_enrolled_admission_gate_rechecks_legacy_ambiguity(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_runtime as module, lfc_session_status
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        ledger = runtime.state.ledger
        ledger.record('session_start', session_id='late-manual', counted=True, owner_local_date='2026-11-10')
        ledger.record('session_end', session_id='late-manual', unknown_submit=True, cleanup_ok=False)
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(module, 'workstation_headroom', lambda: {})
        monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path / 'STOP')
        policy = parse_policy(policy_row())
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            runtime.pre_go_once(policy.entries[0], policy)
        prepared = {'baseline': runtime.original_baseline(runtime.state.ledger), 'account_read': account_read(runtime),
                    'expires_utc': (NOW + timedelta(seconds=120)).isoformat()}
        authority = ScheduledAuthority(runtime, {'attempt_id': 'a' * 32}, policy.entries[0], policy, prepared)
        with pytest.raises(StateRefused, match='historical_money_ambiguity_requires_owner_recovery'):
            authority.start_gates(ledger=runtime.state.ledger, now=NOW, maker_address=MAKER, open_orders=[], positions=[])


def test_owner_history_recovery_refuses_noninteractive_before_operational_paths(monkeypatch):
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(cli, 'pilot_root', lambda: pytest.fail('no operational path may be reached'))
    with pytest.raises(StateRefused, match='owner_terminal_required'):
        cli.main(['owner-recover-history', '--head', 'f' * 40, '--session', 'fixture'])


def test_owner_history_command_is_explicit_readonly_and_retains_originals(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from weather.market import lfc_campaign_cli as cli, lfc_campaign_guard as guard
    from weather.market import lfc_campaign_runtime as adapter, lfc_campaign_release as release
    from weather.market import lfc_campaign_workload as workload
    from weather import execution_host
    from weather.market.lfc_campaign_history import history_refusals
    from weather.market.lfc_ledger import Ledger
    root = tmp_path / 'fixture pilot'
    ledger = reconciled_legacy(root)
    issue = history_refusals(ledger, root)['S0c-1']
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda: 'recover legacy ' + issue[:12])
    monkeypatch.setattr(cli, 'pilot_root', lambda: root)
    monkeypatch.setattr(adapter, 'CampaignClock', Clock)
    monkeypatch.setattr(release, 'git_identity', lambda _: 'f' * 40)
    monkeypatch.setattr(execution_host, 'require_current_portable_execution_assignment', lambda: None)
    monkeypatch.setattr(cli, 'account_lease', lambda maker: account_lease(maker, backend=Mutexes()))
    monkeypatch.setattr(guard, 'HOLD_PATH', tmp_path / 'HOLD')
    poison = tmp_path / 'poison'
    poison.mkdir()
    @contextmanager
    def lease(_):
        yield SimpleNamespace(poison_root=poison)
    monkeypatch.setattr(guard, 'ExclusiveWorkload', lease)
    marker_type = workload.WorkloadMarker
    monkeypatch.setattr(workload, 'WorkloadMarker', lambda **kwargs: marker_type(**kwargs, boot_id=7))
    def read(runtime):
        row = account_read(runtime)
        row['since'] = str(int(datetime.fromisoformat(runtime.state.ledger.rows[0]['recorded_at_utc']).timestamp()))
        return row
    monkeypatch.setattr(adapter.Runtime, 'account_read_once', read)
    assert cli.main(['owner-recover-history', '--head', 'f' * 40, '--session', 'S0c-1']) == 0
    reopened = Ledger.open(ledger.path, clock=Clock().now)
    assert reopened.rows[-1]['event'] == 'owner_history_recovery'
    assert reopened.sessions['S0c-1']['end']['unknown_submit'] is True
    assert history_refusals(reopened, root) == {}
    assert not (tmp_path / 'HOLD').exists() and not (poison / 'heavy_workload_v1.poison').exists()


def owner_review_fixture(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from weather.market import lfc_campaign_cli as cli
    runtime = runtime_at(tmp_path)
    policy = parse_policy(policy_row())
    claim = runtime.state.claim(policy.entries[0], policy, NOW)
    directory, result = private_result(runtime, claim, faults=('unclassified_core_fault',), unknown_submit=True)
    assert result['unknown_submit'] and not result['local_money_proof']['complete']
    runtime.save_result(claim, result)
    runtime.state.latch(claim['attempt_id'], 'ambiguous_placement', NOW)
    # Explicit synthetic OWNER repair. The automatic postchecker never adopts.
    runtime.state.ledger.adopt('s:1', 'o', source='owner_reviewed_fixture', evidence={'fixture': True})
    runtime.state.ledger.terminal('o', {'id': 'o', 'status': 'CANCELED', 'size_matched': '0'}, source='owner_fixture')
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'read_account', lambda: account_read(runtime))
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    incident = runtime.state.root / 'incidents' / (claim['attempt_id'] + '.json')
    monkeypatch.setattr('builtins.input', lambda: 'recover ' + file_sha(incident)[:12])
    return runtime, claim, directory


def test_explicit_owner_recovery_can_clear_resolved_ambiguity_without_rewriting_flags(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_cli import owner_recover
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, directory = owner_review_fixture(tmp_path, monkeypatch)
        before = file_sha(runtime.state.root / 'results' / (claim['attempt_id'] + '.json'))
        assert owner_recover(runtime, claim['attempt_id']) == 0
        assert runtime.state.pending() == [] and runtime.state.incidents() == []
        runtime.state.require_retained_evidence()
        result = runtime.saved_result(claim)
        assert result['unknown_submit'] and not result['local_money_proof']['complete']
        assert file_sha(runtime.state.root / 'results' / (claim['attempt_id'] + '.json')) == before
        assert runtime.state.ledger.sessions['s']['end']['unknown_submit'] is True
        closed = runtime.state.read(runtime.state.root / 'closed' / (claim['attempt_id'] + '.json'))
        assert closed['proof']['authority'] == 'owner_recovery'
        assert closed['proof']['unknown_submit'] is False and closed['proof']['original_result_retained'] is True
        assert '2026-11-11' in runtime.state.consumed_dates() and runtime.state.ledger.counted_sessions() == 1
        row = policy_row()
        row['entries'][0].update(local_date='2026-11-12', window_start_utc='2026-11-12T16:00:00Z',
                                  window_end_utc='2026-11-12T17:00:00Z')
        runtime.clock.sleep(86400)
        next_policy = parse_policy(row)
        following = runtime.state.claim(next_policy.entries[0], next_policy, runtime.clock.now())
        assert following['local_date'] == '2026-11-12'


@pytest.mark.parametrize('name', ['journal.jsonl', 'prediction.json', 'session_end.json', 'submit-1.intent.json', 'result'])
@pytest.mark.parametrize('damage', ['delete', 'mismatch'])
def test_owner_confirmation_cannot_waive_missing_or_changed_originals(tmp_path, monkeypatch, name, damage):
    from weather.market.lfc_campaign_cli import owner_recover
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, directory = owner_review_fixture(tmp_path, monkeypatch)
        path = runtime.state.root / 'results' / (claim['attempt_id'] + '.json') if name == 'result' else directory / name
        if damage == 'delete':
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b' ')
        with pytest.raises(StateRefused):
            owner_recover(runtime, claim['attempt_id'])
        assert not list((runtime.state.root / 'closed').glob('*.json'))
        assert not list((runtime.state.root / 'owner-closures').glob('*.json'))


@pytest.mark.parametrize('name', ['journal.jsonl', 'prediction.json', 'session_end.json', 'result', 'owner_closure'])
def test_owner_recovered_originals_remain_required_for_later_admission(tmp_path, monkeypatch, name):
    from weather.market.lfc_campaign_cli import owner_recover
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, directory = owner_review_fixture(tmp_path, monkeypatch)
        assert owner_recover(runtime, claim['attempt_id']) == 0
        path = (runtime.state.root / 'results' / (claim['attempt_id'] + '.json') if name == 'result' else
                runtime.state.root / 'owner-closures' / (claim['attempt_id'] + '.json') if name == 'owner_closure' else
                directory / name)
        path.unlink()
        with pytest.raises(StateRefused):
            runtime.state.require_retained_evidence()


def test_automatic_close_cannot_claim_owner_authority_without_owner_receipt(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, claim, _ = owner_review_fixture(tmp_path, monkeypatch)
        # An actual closure is still required; scalar green account flags or an
        # authority string cannot clear the original incident automatically.
        proof = runtime.core_proof(runtime.state.ledger, account_read(runtime))
        with pytest.raises(StateRefused):
            runtime.state.close(claim, {**proof, 'authority': 'owner_recovery'}, NOW)
        assert runtime.state.pending()


@pytest.mark.parametrize('name', ['submit-1.ack.json', 'prediction.json'])
def test_owner_recovery_refuses_conflicting_pre_save_evidence_hashes(tmp_path, name):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        directory, result = private_result(runtime, claim)
        path = directory / name
        path.write_bytes(path.read_bytes() + b' ')  # Still valid JSON, different original bytes.
        runtime.save_result(claim, result)
        with pytest.raises(StateRefused, match='owner_original_evidence_fault'):
            runtime.state.owner_result_binding(claim)
        assert runtime.state.ledger.autostart_incidents
