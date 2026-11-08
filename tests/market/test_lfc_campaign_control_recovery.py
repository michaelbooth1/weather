"""Synthetic control, recording and confinement witnesses for unattended operation.

Guards: B046 C1-C5/C7; no venue, task activation, credentials or live paths.
"""
from contextlib import contextmanager
from datetime import timedelta, datetime, timezone
import json
import os
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, StubRuntime, state_at, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_control import control_record, orders_unproven
from weather.market.lfc_campaign_guard import account_lease, ExclusiveWorkload, AdmissionUncertain
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_recording_io import file_sha, write_new


@pytest.fixture(autouse=True)
def account_guard():
    with account_lease(MAKER, backend=Mutexes()):
        yield


@pytest.mark.parametrize('phase', ['IDLE', 'DISABLED', 'DEFERRED', 'MISSED', 'REFUSED', 'COMPLETE'])
def test_unclaimed_control_records_do_not_claim_orders_are_unproven(tmp_path, phase):
    row = control_record(tmp_path, 'a' * 32, phase=phase, now=Clock().now())
    assert row['orders_open_unproven'] is False


def test_unknown_intent_overrides_a_preflight_empty_account_snapshot(tmp_path):
    runtime = runtime_at(tmp_path)
    state = runtime.state
    policy = parse_policy(policy_row())
    claim = state.claim(policy.entries[0], policy, runtime.clock.now())
    state.ledger.record('session_start', session_id='s', counted=True, autostart_attempt_id=claim['attempt_id'])
    state.ledger.intent(session_id='s', intent_key='unknown', token_id='t', condition_id='c', price='.4', size='20', fee_rate_bps='0')
    runtime._orders_open_unproven = False
    assert orders_unproven(state, runtime)


def test_unbound_state_cannot_claim_open_order_absence():
    assert orders_unproven(None)


def test_complete_cleanup_absence_clears_flag_but_failed_read_restores_unknown(tmp_path):
    from tests.market.test_lfc_campaign_runtime import account_read
    from weather.market.lfc_campaign_state import StateRefused
    runtime = runtime_at(tmp_path)
    assert runtime.core_proof(runtime.state.ledger, account_read(runtime))['cleanup_proven']
    assert not orders_unproven(runtime.state, runtime)
    with pytest.raises(StateRefused):
        runtime.core_proof(runtime.state.ledger, {**account_read(runtime), 'complete': False})
    assert orders_unproven(runtime.state, runtime)


def test_scheduler_readback_is_cached_for_one_minute_with_a_five_second_native_bound(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_release as release
    runtime = runtime_at(tmp_path)
    reads = []
    def read_task():
        reads.append(runtime.clock.monotonic())
        return True
    runtime._read_task_enabled = read_task
    for _ in range(12):
        assert runtime.task_enabled()
        runtime.clock.sleep(5)
    assert len(reads) == 1
    assert runtime.task_enabled() and len(reads) == 2
    def native_read(args, **kw):
        assert kw['timeout'] == 5
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'schema_version': 'lfc_campaign_task_read_v0.1', 'definition_valid': True,
            'enabled': True, 'release_sha256': 'a' * 64}))
    monkeypatch.setattr(release.subprocess, 'run', native_read)
    assert release.task_enabled({}, tmp_path / 'fixture.json', 'a' * 64)


def test_no_qualifying_band_keeps_its_reason_through_the_window(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock)
    def no_band(*a): raise TransientPrecheck('no_qualifying_band')
    runtime.pre_go = no_band
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    coordinator.tick(lambda: parse_policy(policy_row()))
    rows = [json.loads(p.read_text()) for p in (tmp_path / 'control').glob('*.json')]
    assert {row['reason'] for row in rows} == {'no_qualifying_band'}
    assert any(row['phase'] == 'MISSED' for row in rows)
    assert not state.claims() and runtime.go_count == 0


@pytest.mark.parametrize('legacy', [False, True])
def test_same_incident_has_stable_control_identity_across_new_ticks(tmp_path, legacy):
    clock = Clock()
    state = state_at(tmp_path, clock)
    if legacy:
        from weather.market.lfc_campaign_incidents import latch_occurrence
        incident = latch_occurrence(state, 'admission', 'ownership_uncertain', 'attempt', clock.now(), initial_id='admission')
    else:
        incident = state.latch('admission', 'ownership_uncertain', clock.now())
        assert len(incident) == 32
    first = CampaignCoordinator(state=state, runtime=StubRuntime(state, clock), clock=clock, control_root=tmp_path / 'control')
    row = first.status('INCIDENT')
    clock.sleep(86400)
    second = CampaignCoordinator(state=state, runtime=StubRuntime(state, clock), clock=clock, control_root=tmp_path / 'control')
    other = second.status('INCIDENT')
    assert row['attempt_id'] == other['attempt_id'] and len(row['attempt_id']) == 32
    assert state.incidents()[0]['attempt_id'] == incident  # Original receipt identity is unchanged.
    assert len(state.incidents()) == 1


def test_missing_incident_receipt_cannot_project_pending_without_incident(tmp_path):
    clock = Clock(); state = state_at(tmp_path, clock)
    incident = state.latch('admission', 'ownership_uncertain', clock.now())
    (state.root / 'incidents' / (incident + '.json')).unlink()
    coordinator = CampaignCoordinator(state=state, runtime=StubRuntime(state, clock), clock=clock,
                                      control_root=tmp_path / 'control')
    row = coordinator.status('POSTCHECK_PENDING', postchecks_pending=True)
    assert row['phase'] == 'INCIDENT' and row['incident'] and len(row['attempt_id']) == 32


def test_repeated_admission_fault_deduplicates_only_its_open_occurrence(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock)
    @contextmanager
    def refused(): raise AdmissionUncertain('workload_poison'); yield
    runtime.admission = refused
    policy = parse_policy(policy_row())
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    for _ in range(2): assert coordinator.start(policy.entries[0], policy, lambda: policy) == 'INCIDENT'
    assert len(state.incidents()) == 1 and not state.claims()
    assert len(state.incidents()[0]['attempt_id']) == 32


@pytest.mark.parametrize('foreign,alive', [(False, False), (True, False), (False, True)])
def test_recording_can_observe_only_own_proved_dead_marker_and_cannot_grant_live_authority(tmp_path, monkeypatch, foreign, alive):
    from weather.market import lfc_campaign_workload as workload
    from weather.operations import process_lock_identity
    monkeypatch.setattr(process_lock_identity, 'current_process_identity',
                        lambda: {'pid': os.getpid(), 'creation_time_token': 'fixture-instance'})
    monkeypatch.setattr(process_lock_identity, 'lock_owner_status', lambda row: {'stale': not alive})
    monkeypatch.setattr(workload, 'current_boot_id', lambda: 7)
    marker = workload.WorkloadMarker(poison_root=tmp_path, state_id='state', maker=MAKER, boot_id=7)
    marker.acquire(hold_sha256='a' * 64, hold_owner='fixture')
    before = marker.path.read_bytes()
    lease = ExclusiveWorkload(MAKER, backend=Mutexes(), namespace='fixture', poison_root=tmp_path,
                              read_only=True, state_id='other' if foreign else 'state')
    if foreign or alive:
        with pytest.raises(AdmissionUncertain, match='workload_poison'):
            with lease: pytest.fail('foreign/live marker must refuse')
    else:
        with lease:
            assert len(lease.handles) == 9
            with pytest.raises(AdmissionUncertain, match='read_only_lease_has_no_live_authority'): lease.check()
    assert marker.path.read_bytes() == before
    with pytest.raises(AdmissionUncertain, match='workload_poison'):
        with ExclusiveWorkload(MAKER, backend=Mutexes(), namespace='fixture', poison_root=tmp_path): pass


def test_latched_pending_attempt_still_records_followup_without_account_or_placement_client(tmp_path, monkeypatch):
    from weather.market import lfc_f2_followup as followup, lfc_f2_economics as economics
    from weather.market.lfc_f2_policy import example_policy
    runtime = runtime_at(tmp_path, now=datetime(2026, 11, 11, 14, tzinfo=timezone.utc))
    policy = parse_policy(example_policy())
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    claim = runtime.state.claim(entry, policy, runtime.clock.now())
    ledger = runtime.state.ledger
    ledger.record('session_start', session_id='pending', counted=True, autostart_attempt_id=claim['attempt_id'])
    ledger.intent(session_id='pending', intent_key='lost', token_id='t', condition_id='c', size='20', price='.4', fee_rate_bps='0')
    runtime.state.latch(claim['attempt_id'], 'ambiguous_placement', runtime.clock.now())
    @contextmanager
    def readonly():
        assert runtime.lease is None
        yield
    monkeypatch.setattr(runtime, 'readonly_admission', readonly)
    monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('an evidence-only follow-up cannot read money proof'))
    monkeypatch.setattr(runtime, 'admission', lambda: pytest.fail('recording cannot acquire live authority'))
    monkeypatch.setattr(runtime, 'notify_control', lambda row: None)
    calls = []
    monkeypatch.setattr(followup, 'collect', lambda r: calls.append('record') or {
        'observed_at_utc': r.clock.now().isoformat(), 'observations': [], 'gaps': [], 'monetary_action': False})
    monkeypatch.setattr(economics, 'publish_supplements', lambda r: None)
    coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock,
        control_root=tmp_path / 'control', followup=runtime.followup)
    assert coordinator.tick(lambda: policy) == 'POSTCHECKS'
    assert calls == ['record'] and runtime.state.incidents() and ledger.unacknowledged_intents()
    saved = runtime.state.read(next((runtime.state.root / 'followups').glob('*.json')))
    assert not saved['money_proof_complete'] and not saved['monetary_action']
    assert saved['gaps'] == ['money_or_evidence_incident_retained']


@pytest.mark.spawns
@pytest.mark.parametrize('schema', ['lfc_campaign_policy_v0.2', 'lfc_campaign_policy_v0.3'])
@pytest.mark.parametrize('stamp,seconds,expected', [
    ('2026-11-11T14:14:50Z', 21600, '2026-11-11T20:30:00+00:00'),
    ('2026-11-11T14:14:50Z', 300, '2026-11-11T14:49:50+00:00'),
    ('2026-11-11T13:59:59Z', 21600, '2026-11-11T14:29:59+00:00'),
    ('2026-11-11T14:15:00Z', 21600, '2026-11-11T14:45:00+00:00')])
def test_wrapper_deadline_uses_effective_end_plus_thirty_minutes(tmp_path, stamp, seconds, expected, schema):
    from tests.operations.test_lfc_campaign_task import powershell
    from weather.market.lfc_f2_policy import example_policy
    if schema == 'lfc_campaign_policy_v0.3':
        from weather.market.lfc_f2_breadth import example_policy
    row = example_policy(); row['max_session_seconds'] = seconds
    path = tmp_path / 'campaign.json'; path.write_text(json.dumps(row))
    result = powershell("(Get-LfcCampaignDeadline -CampaignPath '" + str(path).replace("'", "''") +
        "' -NowUtc ([DateTimeOffset]'" + stamp + "')).ToString('o')")
    assert result.returncode == 0, result.stderr
    assert datetime.fromisoformat(result.stdout.strip()) == datetime.fromisoformat(expected)


@pytest.mark.spawns
def test_every_child_policy_schema_has_a_wrapper_deadline_after_its_session_end(tmp_path):
    import ast
    import inspect
    from tests.operations.test_lfc_campaign_task import powershell
    from weather.market import lfc_campaign_policy as child
    from weather.market.lfc_f2_policy import example_policy as f2
    from weather.market.lfc_f2_breadth import example_policy as breadth
    examples = [policy_row(), f2(), breadth()]
    accepted = {node.value for node in ast.walk(ast.parse(inspect.getsource(child.parse_policy)))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith('lfc_campaign_policy_v')}
    accepted.add(child.POLICY_SCHEMA)
    assert {row['schema_version'] for row in examples} == accepted
    for number, row in enumerate(examples):
        policy = child.parse_policy(row)
        entry = policy.entries[0]
        now = entry.start
        assert entry.permits(now)
        path = tmp_path / f'campaign-{number}.json'; path.write_text(json.dumps(row))
        result = powershell("(Get-LfcCampaignDeadline -CampaignPath '" + str(path).replace("'", "''") +
            "' -NowUtc ([DateTimeOffset]'" + now.isoformat() + "')).ToString('o')")
        assert result.returncode == 0, result.stderr
        assert datetime.fromisoformat(result.stdout.strip()) >= entry.session_end(now) + timedelta(minutes=30), row['schema_version']


@pytest.mark.spawns
@pytest.mark.parametrize('malformed,maximum', [(False, 21600), (False, 300), (True, 21600)])
def test_reference_deadline_and_malformed_policy_are_bounded_without_silent_admission(tmp_path, malformed, maximum):
    from tests.operations.test_lfc_campaign_task import powershell
    row = policy_row(); row['max_session_seconds'] = maximum
    policy = parse_policy(row); now = policy.entries[0].start
    path = tmp_path / 'campaign.json'; path.write_text('{' if malformed else json.dumps(row))
    expected = now + timedelta(minutes=30) if malformed else policy.entries[0].session_end(now) + timedelta(minutes=30)
    result = powershell("(Get-LfcCampaignDeadline -CampaignPath '" + str(path).replace("'", "''") +
        "' -NowUtc ([DateTimeOffset]'" + now.isoformat() + "')).ToString('o')")
    assert result.returncode == 0, result.stderr
    assert datetime.fromisoformat(result.stdout.strip()) == expected
