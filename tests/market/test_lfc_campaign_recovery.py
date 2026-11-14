"""Claimed but unposted attempts close without placement in the recovery tick.

Guards: B046 A1/A2/A3; durable no-intent proof, cleanup progress and ambiguity.
"""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, StubRuntime, policy_row, state_at
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_recovery import recover_empty, attempt_intents
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_campaign_visibility import stalled
from weather.market.lfc_ledger import Ledger


@pytest.fixture(autouse=True)
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


@pytest.mark.parametrize('reason', ['go_window_or_freshness_expired', 'account_read_stale',
    'inventory_changed_after_baseline', 'session_stalled', 'console_closed', 'logoff', 'power_loss'])
def test_unposted_claim_after_hard_exit_closes_missed_and_allows_clean_retry(tmp_path, reason):
    clock = Clock()
    state = state_at(tmp_path, clock)
    policy = parse_policy(policy_row())
    claim = state.claim(policy.entries[0], policy, clock.now())
    state.ledger.record('session_start', session_id='empty-band', counted=True,
                        autostart_attempt_id=claim['attempt_id'], owner_local_date=claim['local_date'],
                        synthetic_interruption=reason)
    # Simulate a hard kill: no run_session finally/result exists in this process.
    state = AccountState(tmp_path / 'state', Ledger.open(state.ledger.path, clock=clock.now))
    runtime = StubRuntime(state, clock)
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    coordinator.tick(lambda: policy)
    assert not state.pending() and not state.incidents() and runtime.go_count == 0
    assert state.ledger.open_sessions() == [] and claim['local_date'] not in state.consumed_dates()
    closed = state.read(state.root / 'closed' / (claim['attempt_id'] + '.json'))
    assert closed['state'] == 'MISSED' and closed['proof']['authority'] == 'automatic_no_intent'
    assert closed['proof']['research_evidence_complete'] is False
    assert not attempt_intents(state.ledger, claim['attempt_id'])
    assert state.ledger.sessions['empty-band']['start']['synthetic_interruption'] == reason
    retry = state.claim(policy.entries[0], policy, clock.now())
    assert retry['attempt_id'] != claim['attempt_id'] and state.pending() == [retry]
    assert state.read(state.root / 'closed' / (claim['attempt_id'] + '.json')) == closed


def test_reachable_postclaim_exception_is_saved_before_unposted_close(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock, crash=True)
    policy = parse_policy(policy_row())
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    from tests.market.test_lfc_campaign import bind_launch
    policy = bind_launch(coordinator, policy)
    assert coordinator.start(policy.entries[0], policy, lambda: policy) == 'FAILED_NO_ORDERS'
    claim = state.claims()[0]
    assert claim['attempt_id'] in runtime.results
    assert runtime.results[claim['attempt_id']]['unknown_submit'] is False
    assert not state.pending() and not state.incidents()


def test_ambiguous_intent_never_uses_the_no_order_recovery(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    policy = parse_policy(policy_row())
    claim = state.claim(policy.entries[0], policy, clock.now())
    state.ledger.record('session_start', session_id='band', counted=True, autostart_attempt_id=claim['attempt_id'])
    state.ledger.intent(session_id='band', intent_key='lost-ack', token_id='111', condition_id='c',
                        size='20', price='.4', fee_rate_bps='0')
    assert recover_empty(state, clock.now()) == []
    runtime = StubRuntime(state, clock)
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    coordinator.tick(lambda: policy)
    assert state.pending() and state.incidents()
    assert not (state.root / 'closed' / (claim['attempt_id'] + '.json')).exists()
    assert state.ledger.unacknowledged_intents() and runtime.go_count == 0


@pytest.mark.parametrize('phase', ['SETUP', 'CLEANUP', 'VERIFY', 'FINALIZE'])
def test_bounded_nonquoting_phases_do_not_hard_exit_mid_cleanup(phase):
    exits = []
    assert not stalled(None, None, last_progress=0, now_mono=130, phase=phase, exit_process=exits.append)
    assert exits == []


def test_empty_close_receipt_cannot_clear_a_different_attempt_or_later_intent(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    policy = parse_policy(policy_row())
    claim = state.claim(policy.entries[0], policy, clock.now())
    state.latch(claim['attempt_id'], 'claimed_attempt_interrupted', clock.now())
    assert len(recover_empty(state, clock.now())) == 1 and not state.incidents()
    from weather.market.lfc_ledger import LedgerUnavailable
    with pytest.raises(LedgerUnavailable, match='attempt_already_closed'):
        state.ledger.record('session_start', session_id='retry', counted=True, autostart_attempt_id=claim['attempt_id'])


def test_real_elapsed_band_cleanup_keeps_other_band_heartbeat_and_authority_alive(tmp_path, monkeypatch):
    import time
    from tests.market.test_lfc_f2_controller import setup
    from weather.market import lfc_f2_controller as controller_module
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.lfc_recording_io import write_new
    from weather.market.re1_resilience import HeartbeatLoop
    controller, account, status, ledger, clock = setup(tmp_path)
    started = time.monotonic()
    real = SimpleNamespace(monotonic=time.monotonic,
                           now=lambda: clock.base + timedelta(seconds=time.monotonic() - started))
    policy_path = tmp_path / 'campaign.json'
    write_new(policy_path, {**controller.policy.raw, 'enabled': True})
    incidents, heartbeats = [], []
    runtime = SimpleNamespace(clock=real, pilot_root=tmp_path, policy_path=policy_path,
        lease=SimpleNamespace(check=lambda: None), sidecar=None, control_root=tmp_path / 'control',
        state=SimpleNamespace(verify=lambda: None, latch=lambda *a: incidents.append(a), ledger=ledger,
                              root=tmp_path / 'fixture-state'), task_enabled=lambda: True)
    authority = ScheduledAuthority(runtime, {'attempt_id': 'a' * 32, **controller.policy.labels('2026-11-11')},
                                   controller.entry, controller.policy, {'baseline': {}})
    status.checkpoint_hook = authority.check
    status.resync_hook = authority.resync
    loops = []
    def heartbeat_loop(ignored_clock, send, journal, **kwargs):
        def observed_send():
            heartbeats.append(time.monotonic())
            return send()
        loop = HeartbeatLoop(real, observed_send, journal, threaded=True)
        loops.append(loop)
        return loop
    monkeypatch.setattr(controller_module, 'HeartbeatLoop', heartbeat_loop)
    first = account.raws[0]
    original_cancel, original_order = first.cancel, first.order
    def slow_cancel(oid):
        time.sleep(11)
        return original_cancel(oid)
    def slow_order(oid):
        if status.phase == 'CLEANUP':
            time.sleep(6)
        return original_order(oid)
    monkeypatch.setattr(first, 'cancel', slow_cancel)
    monkeypatch.setattr(first, 'order', slow_order)
    account.filled_band, account.fill_at = 0, 12
    result = controller.run()
    elapsed = time.monotonic() - started
    assert elapsed >= 21, elapsed  # Actual elapsed wall time, not the fixture clock.
    assert not incidents and loops[0].failure is None
    assert len(heartbeats) >= 8 and max(b - a for a, b in zip(heartbeats, heartbeats[1:])) < 8
    assert controller.results[controller.bands[0].session_id]['reason'] == 'fill'
    assert controller.results[controller.bands[1].session_id]['reason'] == 'fixed_end'
    assert all(when >= 300 for when, _ in account.raws[1].cancellations)
    assert result['cleanup_ok'], result


@pytest.mark.parametrize('gone', [False, True])
def test_same_boot_workload_recovery_requires_proved_process_exit(tmp_path, monkeypatch, gone):
    import os
    from weather.market.lfc_campaign_workload import WorkloadMarker, owner_release_workload_after_reboot
    from weather.market.lfc_campaign_guard import OwnedHold, AdmissionUncertain
    from weather.market.lfc_recording_io import file_sha
    from weather.operations import process_lock_identity
    monkeypatch.setattr(process_lock_identity, 'current_process_identity',
                        lambda: {'pid': os.getpid(), 'creation_time_token': 'fixture-creation'})
    hold = OwnedHold(tmp_path / 'hold')
    hold.acquire()
    marker = WorkloadMarker(poison_root=tmp_path, state_id='state', maker=MAKER, boot_id=7)
    marker.acquire(hold_sha256=file_sha(hold.path), hold_owner=hold.identity)
    monkeypatch.setattr(process_lock_identity, 'lock_owner_status', lambda row: {'stale': gone})
    args = dict(path=marker.path, expected_sha=file_sha(marker.path), state_id='state', maker=MAKER,
                boot_id=7, backend=Mutexes(), hold_path=hold.path, owner_terminal=True,
                confirmation='clear workload ' + file_sha(marker.path)[:12])
    if not gone:
        with pytest.raises(AdmissionUncertain, match='owner_reboot_continuity_required'):
            owner_release_workload_after_reboot(**args)
        assert marker.path.exists() and hold.path.exists()
    else:
        owner_release_workload_after_reboot(**args)
        assert not marker.path.exists() and not hold.path.exists()


def test_owner_can_close_proved_dead_hold_without_a_workload_marker(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_workload import owner_release_hold_only
    from weather.market.lfc_recording_io import file_sha, write_new
    from weather.operations import process_lock_identity
    hold = SimpleNamespace(path=tmp_path / 'hold')
    write_new(hold.path, {'schema_version': 'lfc_campaign_hold_v0.1', 'owner': 'fixture-owner',
        'boot_id': 7, 'pid': 123, 'owner_process_identity': {'pid': 123, 'creation_time_token': 'fixture-creation'}})
    monkeypatch.setattr(process_lock_identity, 'lock_owner_status', lambda row: {'stale': True})
    row = json.loads(hold.path.read_text())
    owner_release_hold_only(path=hold.path, expected_sha=file_sha(hold.path), boot_id=row['boot_id'],
        backend=Mutexes(), owner_terminal=True, confirmation='clear hold ' + file_sha(hold.path)[:12])
    assert not hold.path.exists()


def owner_runtime(tmp_path, monkeypatch, *, ack=True):
    from contextlib import contextmanager
    from tests.market.test_lfc_campaign_runtime import runtime_at, account_read
    runtime = runtime_at(tmp_path)
    policy = parse_policy(policy_row())
    state, ledger = runtime.state, runtime.state.ledger
    claim = state.claim(policy.entries[0], policy, runtime.clock.now())
    directory = runtime.pilot_root / 'session-interrupted'
    directory.mkdir()
    ledger.record('session_start', session_id='interrupted', counted=True,
        autostart_attempt_id=claim['attempt_id'], condition_id='c', directory=directory.relative_to(runtime.pilot_root).as_posix())
    ledger.intent(session_id='interrupted', intent_key='intent', token_id='111', condition_id='c', size='20', price='.4', fee_rate_bps='0')
    if ack: ledger.ack('intent', 'known-order')
    incident = state.latch(claim['attempt_id'], 'claimed_attempt_interrupted', runtime.clock.now())
    read = account_read(runtime)
    now = runtime.clock.now().isoformat()
    read['terminal_orders'] = {'known-order': {'row': {'id': 'known-order', 'status': 'CANCELED',
        'original_size': '20', 'size_matched': '0'}, 'started_at_utc': now, 'ended_at_utc': now}}
    runtime.workload_path = tmp_path / 'fixture-workload-marker'
    monkeypatch.setattr(runtime, 'read_account', lambda: read)
    @contextmanager
    def admission(): yield
    monkeypatch.setattr(runtime, 'admission', admission)
    from weather.market.lfc_recording_io import file_sha
    sha = file_sha(state.root / 'incidents' / (incident + '.json'))
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda: 'close ' + sha[:12])
    return runtime, claim, incident, directory


def test_one_owner_close_handles_a_missing_result_with_known_ack_and_terminal_proof(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, claim, incident, _ = owner_runtime(tmp_path, monkeypatch)
    assert owner_close(runtime, incident) == 0
    assert not runtime.state.pending() and not runtime.state.incidents()
    runtime.state.require_retained_evidence()
    assert runtime.state.ledger.legs['intent']['status'] == 'terminal'
    closed = runtime.state.read(runtime.state.root / 'closed' / (claim['attempt_id'] + '.json'))
    assert closed['proof']['research_evidence_complete'] is False
    assert not (runtime.state.root / 'results' / (claim['attempt_id'] + '.json')).exists()
    assert claim['local_date'] in runtime.state.consumed_dates()


def test_owner_close_cannot_waive_an_unproved_placement(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, claim, incident, _ = owner_runtime(tmp_path, monkeypatch, ack=False)
    monkeypatch.setattr(runtime, 'read_account', lambda: pytest.fail('no read can waive an unknown intent'))
    with pytest.raises(StateRefused, match='owner_close_ambiguous_placement'): owner_close(runtime, incident)
    assert runtime.state.ledger.unacknowledged_intents()
    assert not (runtime.state.root / 'closed' / (claim['attempt_id'] + '.json')).exists()


def test_owner_close_requires_an_interactive_explicit_decision(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, _, incident, _ = owner_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(StateRefused, match='owner_terminal_required'): owner_close(runtime, incident)


@pytest.mark.parametrize('artifact', ['journal.jsonl', 'submit-1.ack.json'])
@pytest.mark.parametrize('reboot', [False, True])
def test_owner_accepted_loss_restored_then_lost_again_requires_new_occurrence(tmp_path, monkeypatch, artifact, reboot):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
    assert owner_close(runtime, incident) == 0
    journal = directory / artifact
    journal.write_text('restored retained fragment; financial flags still incomplete\n')
    runtime.state.require_retained_evidence()
    assert any(row['event'] == 'autostart_owner_artifact_restored' for row in runtime.state.ledger.rows)
    if reboot:
        runtime.state = AccountState(runtime.state.root.parent,
            Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now))
    journal.unlink()
    with pytest.raises(StateRefused, match='owner_accepted_artifact_recurred'): runtime.state.require_retained_evidence()
    assert len(runtime.state.ledger.autostart_incidents) == 2
    assert runtime.state.ledger.autostart_incidents[-1]['attempt_id'] != incident


def test_owner_close_does_not_accept_a_nonterminal_order(tmp_path, monkeypatch):
    from weather.market.lfc_campaign_owner_close import owner_close
    runtime, claim, incident, _ = owner_runtime(tmp_path, monkeypatch)
    read = runtime.read_account()
    read['terminal_orders']['known-order']['row']['status'] = 'OPEN'
    with pytest.raises(StateRefused, match='owner_close_terminal_pending'): owner_close(runtime, incident)
    assert runtime.state.ledger.unresolved_legs()
