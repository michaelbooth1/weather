"""Fixture-only scheduled campaign tests.

Guards: T026 B01/B02/M01-M07, B020 bounded deferral and no restart after claims.
No runtime adapter, credentials, Scheduler, pilot root or venue is invoked.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_guard import (AdmissionBusy, AdmissionUncertain, ExclusiveWorkload,
                                               OwnedHold, account_lease)
from weather.market.lfc_campaign_policy import PolicyRefused, parse_policy
from weather.market.lfc_campaign_state import AccountState, StateRefused
from weather.market.lfc_ledger import Ledger, LedgerUnavailable, take_baseline, write_baseline
from weather.market.lfc_recording_io import strict_json
from weather.market.mm_account_reads import order_terminal


MAKER = '0x' + 'a' * 40
NOW = datetime(2026, 11, 11, 16, tzinfo=timezone.utc)


def bind_launch(coordinator, policy):
    """Supply explicit inert parent bytes/budget to non-launch campaign tests."""
    from dataclasses import replace
    import hashlib
    import json
    raw = json.dumps(policy.raw).encode()
    policy = replace(policy, source_sha256=policy.source_sha256 or hashlib.sha256(raw).hexdigest())
    entry = next((entry for entry in policy.entries if entry.permits(coordinator.clock.now())), policy.entries[0])
    deadline = entry.session_end(entry.end) + timedelta(minutes=30)
    coordinator.wrapper_launch = {'deadline_utc': deadline.isoformat(), 'policy_bytes_sha256': policy.source_sha256}
    return policy


def policy_row():
    return {'schema_version': 'lfc_campaign_policy_v0.1', 'enabled': True, 'campaign_id': 'fixture',
            'revision': 1, 'timezone': 'America/Toronto', 'sidecar': None,
            'policy_name': 'LFC-F0-reference', 'policy_revision': 1, 'local_event_dte': [1, 2],
            'band_limit_session': 1, 'band_limit_concurrent': 1, 'bands_per_event': 1,
            'start_window_toronto': None, 'trading_end_toronto': None, 'max_sessions_per_day': 1,
            'concurrent_sessions': 1, 'max_session_seconds': 21600, 'learning_dates': [],
            'confirmation_dates': [], 'capital_mode': 'committed_cost_no_recycling',
            'terms': {'budget_pusd': '100', 'shares_per_leg': '20', 'k_max': 1, 'per_order_cap': '15.80',
                      'per_band_cap': '19.60', 'per_date_cap': '100', 'daily_loss_cap': None,
                      'realised_stop': None, 'unknown_settlement': 'full_loss', 'max_sessions': 8,
                      'last_start_local_date': '2026-11-20', 'fill_retires': 'band'},
            'entries': [{'id': 'day1', 'local_date': '2026-11-11', 'window_start_utc': '2026-11-11T16:00:00Z',
                         'window_end_utc': '2026-11-11T17:00:00Z', 'duration_seconds': 21600}]}


class Mutexes:
    def __init__(self, busy=None, uncertain=None):
        self.busy, self.uncertain, self.held, self.history = busy, uncertain, [], []

    def acquire(self, name):
        self.history.append(name)
        if name == self.busy:
            raise AdmissionBusy('busy')
        if name == self.uncertain:
            raise AdmissionUncertain('abandoned')
        self.held.append(name)
        return name

    def release(self, handle):
        self.held.remove(handle)


class Clock:
    def __init__(self):
        self.value = NOW

    def now(self):
        return self.value

    def monotonic(self):
        return (self.value - NOW).total_seconds()

    def sleep(self, seconds):
        self.value += timedelta(seconds=seconds)


def state_at(tmp_path, clock):
    ledger = Ledger.create(tmp_path / 'pilot' / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER, positions=[], open_orders=[],
                             available_collateral='100')
    write_baseline(ledger.path.parent, baseline, ledger)
    state = AccountState(tmp_path / 'state', ledger)
    state.enroll(clock.now())
    return state


class StubRuntime:
    def __init__(self, state, clock, *, transient=0, crash=False):
        self.state, self.clock, self.transient, self.crash = state, clock, transient, crash
        self.go_count, self.prechecks, self.results = 0, 0, {}
        self.enabled = True

    def task_enabled(self):
        return self.enabled

    def followup(self, load, *, evidence_only=False):
        pass  # Closed session stub has no public or authenticated recorder.

    @contextmanager
    def admission(self):
        yield

    def pre_go(self, entry, policy):
        self.prechecks += 1
        if self.prechecks <= self.transient:
            raise TransientPrecheck('temporary')
        return {'fixture': True}

    def run_session(self, claim, entry, policy, prepared):
        self.go_count += 1
        if self.crash:
            raise RuntimeError('simulated_power_loss')
        return {'unknown_submit': False, 'evidence_complete': False}

    def save_result(self, claim, result):
        self.results[claim['attempt_id']] = result

    def saved_result(self, claim):
        return self.results.get(claim['attempt_id'])

    def postcheck(self, claim, result):
        return {'unknown_submit': False, 'money_accounting_complete': True, 'cleanup_proven': True,
                'research_evidence_complete': False}

    def record_skip(self, entry, policy, reason):
        path = 'skips/' + entry.local_date + '.json'
        if not (self.state.root / path).exists():
            self.state.save(path, {'local_date': entry.local_date, 'reason': reason})


def test_policy_unchanged_defaults_and_supported_lower_caps():
    row = policy_row()
    policy = parse_policy(row)
    assert policy.terms['shares_per_leg'] == '20' and policy.terms['k_max'] == 1
    assert policy.terms['budget_pusd'] == '100'
    row['terms'].update(budget_pusd='90', daily_loss_cap='50', realised_stop='40')
    assert parse_policy(row).terms['daily_loss_cap'] == '50'


@pytest.mark.parametrize('key,value', [('k_max', 4), ('shares_per_leg', '40'), ('budget_pusd', '300'),
                                      ('max_sessions', True), ('max_sessions', 12),
                                      ('last_start_local_date', '2026-11-27'), ('fill_retires', 'all')])
def test_unsupported_expansion_refused_precisely(key, value):
    row = policy_row()
    row['terms'][key] = value
    with pytest.raises(PolicyRefused, match='unsupported'):
        parse_policy(row)


@pytest.mark.parametrize('change', [
    {'window_end_utc': '2026-11-11T23:00:00Z'}, {'window_start_utc': '2026-11-11T11:00:00-05:00'},
    {'local_date': '2026-11-12'}, {'duration_seconds': True}, {'duration_seconds': 21601}])
def test_half_open_explicit_utc_windows_and_full_duration(change):
    row = policy_row()
    row['entries'][0].update(change)
    with pytest.raises(PolicyRefused):
        parse_policy(row)


def test_window_exact_boundaries():
    entry = parse_policy(policy_row()).entries[0]
    assert entry.permits(NOW) and not entry.permits(entry.end)


@pytest.mark.parametrize('field,value', [('id', 'other'), ('status', 'UNKNOWN'), ('size_matched', None),
                                      ('size_matched', '20.000001'), ('size_matched', '-1'),
                                      ('size_matched', 'NaN'), ('size_matched', True), ('original_size', '21')])
def test_terminal_proof_binds_identity_and_bounded_quantity(field, value):
    row = {'id': 'ours', 'status': 'CANCELED', 'original_size': '20', 'size_matched': '0'}
    assert order_terminal(row, order_id='ours', size='20')
    row[field] = value
    assert not order_terminal(row, order_id='ours', size='20')


def test_terminal_missing_identity_cannot_release_ledger_reserve(tmp_path):
    clock = Clock()
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    ledger.record('session_start', session_id='s')
    ledger.intent(session_id='s', intent_key='i', token_id='t', condition_id='c', size='20', price='.5', fee_rate_bps='0')
    ledger.ack('i', 'ours')
    assert ledger.L() == 10
    assert ledger.terminal('ours', {'status': 'CANCELED', 'size_matched': '0'}, source='fixture') is None
    assert ledger.L() == 10
    ledger.terminal('ours', {'id': 'ours', 'status': 'CANCELED', 'size_matched': '0'}, source='fixture')
    assert ledger.L() == 0


@pytest.mark.parametrize('busy_slot', range(9))
def test_all_slots_and_barrier_exclude_and_release_partial_ownership(tmp_path, busy_slot):
    names = ['test.Exclusive', 'test'] + [f'test.Slot{i}' for i in range(2, 9)]
    mutex = Mutexes(busy=names[busy_slot])
    with account_lease(MAKER, backend=mutex):
        with pytest.raises(AdmissionBusy):
            with ExclusiveWorkload(MAKER, backend=mutex, namespace='test', poison_root=tmp_path):
                pytest.fail('admitted overlap')
        assert len(mutex.held) == 1  # only account lease remains
    assert mutex.held == []


def test_workload_poison_never_recovered(tmp_path):
    poison = tmp_path / 'heavy_workload_v1.slot8.poison'
    poison.write_text('retained')
    mutex = Mutexes()
    with account_lease(MAKER, backend=mutex):
        with pytest.raises(AdmissionUncertain, match='poison'):
            with ExclusiveWorkload(MAKER, backend=mutex, namespace='test', poison_root=tmp_path):
                pass
    assert poison.read_text() == 'retained'


def test_synthetic_trigger_pre_go_session_postchecks_and_control_status(tmp_path):
    clock, mutex = Clock(), Mutexes()
    with account_lease(MAKER, backend=mutex):
        state = state_at(tmp_path, clock)
        runtime = StubRuntime(state, clock, transient=2)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        policy = bind_launch(coordinator, parse_policy(policy_row()))
        assert coordinator.tick(lambda: policy) == 'STARTED'
        assert runtime.go_count == 1 and runtime.prechecks == 3
        assert clock.value == NOW + timedelta(seconds=15)
        assert not state.pending() and not state.incidents()
        rows = [strict_json(path.read_bytes()) for path in (tmp_path / 'control').glob('*.json')]
        assert {'DEFERRED', 'RUNNING', 'MISSED'} <= {r['phase'] for r in rows}
        assert all(not {'tokens', 'event', 'fills', 'price', 'account'} & r.keys() for r in rows)
        missed = next(r for r in rows if r['phase'] == 'MISSED')
        assert missed['research_gaps'] is True and missed['orders_open_unproven'] is False
        assert coordinator.tick(lambda: parse_policy(policy_row())) == 'IDLE'
        assert runtime.go_count == 1


def test_crash_latch_survives_reboot_reinstall_and_campaign_rename(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        runtime = StubRuntime(state, clock, crash=True)
        original_run = runtime.run_session
        def placement_then_crash(claim, entry, policy, prepared):
            state.ledger.record('session_start', session_id='lost-ack', counted=True,
                                autostart_attempt_id=claim['attempt_id'])
            state.ledger.intent(session_id='lost-ack', intent_key='lost-ack:1', token_id='111',
                                condition_id='c', size='20', price='.4', fee_rate_bps='0')
            return original_run(claim, entry, policy, prepared)
        runtime.run_session = placement_then_crash
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        policy = bind_launch(coordinator, parse_policy(policy_row()))
        with pytest.raises(RuntimeError, match='power_loss'):
            coordinator.tick(lambda: policy)
    # New ledger object, runtime, mutex and policy: no in-memory latch relied on.
    with account_lease(MAKER, backend=Mutexes()):
        ledger = Ledger.open(state.ledger.path, clock=clock.now)
        restarted = AccountState(tmp_path / 'state', ledger)
        runtime2 = StubRuntime(restarted, clock)
        changed = policy_row()
        changed.update(campaign_id='renamed', revision=2)
        second = CampaignCoordinator(state=restarted, runtime=runtime2, clock=clock, control_root=tmp_path / 'control')
        assert second.tick(lambda: parse_policy(changed)) == 'POSTCHECKS'
        assert runtime2.go_count == 0 and restarted.incidents()
        with pytest.raises(StateRefused, match='incident'):
            restarted.claim(parse_policy(changed).entries[0], parse_policy(changed), clock.now())


def test_missed_window_is_recorded_without_pre_go_or_live(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        clock.value += timedelta(hours=1)
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        assert coordinator.tick(lambda: parse_policy(policy_row())) == 'IDLE'
        assert len(state.skips()) == 1 and runtime.go_count == runtime.prechecks == 0


def test_enrolled_ledger_refuses_unlocked_writer_and_missing_state(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        old_bytes = state.ledger.path.read_bytes()
    ledger = Ledger.open(state.ledger.path, clock=clock.now)
    with pytest.raises(AdmissionUncertain, match='guard_required'):
        ledger.record('halt', reason='fixture')
    assert ledger.path.read_bytes() == old_bytes
    missing = AccountState(tmp_path / 'reinstalled-empty', ledger)
    with pytest.raises(RuntimeError):
        missing.verify()


def test_prospective_loss_limits_include_carried_inventory(tmp_path):
    clock = Clock()
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    ledger.record('session_start', session_id='s', owner_local_date='2026-11-10', event_date='2026-11-12')
    ledger.intent(session_id='s', intent_key='i', token_id='t', condition_id='c', size='98', price='.5', fee_rate_bps='0')
    ledger.ack('i', 'o')
    ledger.terminal('o', {'id': 'o', 'status': 'MATCHED', 'size_matched': '98'}, source='fixture')
    ledger.record('session_end', session_id='s')
    row = policy_row()
    row['terms']['daily_loss_cap'] = '50'
    policy = parse_policy(row)
    policy.cost_gate(ledger, policy.entries[0], Decimal('1'))
    with pytest.raises(PolicyRefused, match='daily_loss'):
        policy.cost_gate(ledger, policy.entries[0], Decimal('15.8'))
    row['terms'].update(daily_loss_cap=None, realised_stop='50')
    policy = parse_policy(row)
    with pytest.raises(PolicyRefused, match='realised_stop'):
        policy.cost_gate(ledger, policy.entries[0], Decimal('1.01'))


def test_owned_hold_honors_other_holder_and_retains_uncertain_teardown(tmp_path):
    path = tmp_path / 'HOLD_HEAVY'
    owner = OwnedHold(path)
    owner.acquire()
    original = path.read_bytes()
    with pytest.raises(AdmissionBusy):
        OwnedHold(path).acquire()
    assert path.read_bytes() == original
    with pytest.raises(AdmissionUncertain, match='retained'):
        owner.release(contained=False)
    assert path.read_bytes() == original
    owner.release(contained=True)
    assert not path.exists()


def test_deleted_claim_or_incident_is_not_a_fresh_install(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        policy = parse_policy(policy_row())
        claim = state.claim(policy.entries[0], policy, clock.now())
        path = state.root / 'claims' / (claim['local_date'] + '.json')
        content = path.read_bytes()
        path.unlink()
        with pytest.raises((OSError, RuntimeError)):
            state.verify()
        path.write_bytes(content)
        state.latch(claim['attempt_id'], 'fixture', clock.now())
        (state.root / 'incidents' / (claim['attempt_id'] + '.json')).unlink()
        with pytest.raises((OSError, RuntimeError)):
            state.verify()


def test_scheduled_entrypoint_synthetic_end_to_end_and_skip_after_reboot(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_cli as cli
    from weather.market import lfc_campaign_runtime as runtime_module
    from weather.market.lfc_campaign_policy import load_policy
    import json
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
    policy_path = tmp_path / 'campaign.json'
    policy_path.write_text(json.dumps(policy_row()))
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    monkeypatch.setattr(cli, 'load_release', lambda *a: {'maker_address': MAKER, 'campaign_path': str(policy_path)})
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'account_lease', lambda maker: account_lease(maker, backend=Mutexes()))
    monkeypatch.setattr(cli, 'bound_state', lambda *a, **kw: (state.ledger.path.parent, state))
    monkeypatch.setattr(runtime_module, 'CampaignClock', lambda: clock)
    runtime = StubRuntime(state, clock, transient=2)
    monkeypatch.setattr(runtime_module, 'Runtime', lambda **kwargs: runtime)
    def wrapper_args():
        policy = load_policy(policy_path)
        entry = policy.entries[0]
        return ['tick', '--release', str(tmp_path / 'fixture-release.json'), '--release-sha256', 'a' * 64,
                '--wrapper-deadline-utc', (entry.session_end(entry.end) + timedelta(minutes=30)).isoformat(),
                '--wrapper-policy-sha256', policy.source_sha256]
    args = wrapper_args()
    assert cli.main(args) == 0
    assert runtime.go_count == 1 and not state.pending()
    # Reboot creates a new runtime and verifies persisted account state. The
    # scheduled dispatcher still refuses to run the consumed account/date.
    rebooted = AccountState(tmp_path / 'state', Ledger.open(state.ledger.path, clock=clock.now))
    monkeypatch.setattr(cli, 'bound_state', lambda *a, **kw: (rebooted.ledger.path.parent, rebooted))
    runtime2 = StubRuntime(rebooted, clock)
    monkeypatch.setattr(runtime_module, 'Runtime', lambda **kwargs: runtime2)
    assert cli.main(args) == 0 and runtime2.go_count == 0
    row = policy_row()
    row['entries'][0].update(id='day2', local_date='2026-11-12', window_start_utc='2026-11-12T16:00:00Z',
                              window_end_utc='2026-11-12T17:00:00Z')
    policy_path.write_text(json.dumps(row))
    clock.value = NOW + timedelta(days=1, hours=1)
    args = wrapper_args()
    assert cli.main(args) == 0 and runtime2.go_count == 0
    assert rebooted.skips()[0]['local_date'] == '2026-11-12'


@pytest.mark.parametrize('field,value', [('local_event_dte', [0]), ('local_event_dte', [1, 1]),
    ('local_event_dte', [True]), ('band_limit_session', 2), ('band_limit_concurrent', 2),
    ('bands_per_event', 2), ('max_sessions_per_day', 2), ('concurrent_sessions', 2),
    ('capital_mode', 'fixed_sleeve_redeemed_principal_only'), ('policy_revision', True),
    ('max_session_seconds', 21601), ('confirmation_dates', ['2026-11-17', '2026-12-22'])])
def test_b021_unsupported_fields_refuse_without_fallback(field, value):
    row = policy_row()
    row[field] = value
    with pytest.raises(PolicyRefused):
        parse_policy(row)


def test_b021_fixed_toronto_end_requires_full_late_duration_and_enforces_global_max():
    row = policy_row()
    row['entries'][0].update(window_start_utc='2026-11-11T14:00:00Z', window_end_utc='2026-11-11T14:15:00Z')
    row.update(start_window_toronto=['09:00:00', '09:15:00'], trading_end_toronto='15:15:00')
    entry = parse_policy(row).entries[0]
    early, late = NOW - timedelta(hours=2), NOW - timedelta(hours=1, minutes=50)
    assert entry.session_end(early) == NOW + timedelta(hours=4)
    assert entry.session_end(late) == late + timedelta(hours=6)
    assert entry.permits(late) and not entry.permits(entry.end)
    row['trading_end_toronto'] = '15:00:00'
    with pytest.raises(PolicyRefused, match='trading_end_before_full_session'):
        parse_policy(row)  # An otherwise on-time deferral cannot clip six hours.
    row['max_session_seconds'] = 1800
    shorter = parse_policy(row).entries[0]
    assert shorter.seconds == 1800 and shorter.session_end(late) == late + timedelta(minutes=30)


def test_b021_policy_labels_and_economic_revision_are_immutable_per_claim(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        row = policy_row()
        row.update(learning_dates=['2026-11-09', '2026-11-15'], confirmation_dates=['2026-11-17', '2026-11-20'])
        first = parse_policy(row)
        claim = state.claim(first.entries[0], first, clock.now())
        assert claim['policy_name'] == 'LFC-F0-reference' and claim['policy_revision'] == 1
        assert claim['evidence_lane'] == 'learning'
        assert state.ledger.rows[-1]['policy_name'] == claim['policy_name']
        row['entries'][0].update(id='day2', local_date='2026-11-12', window_start_utc='2026-11-12T16:00:00Z',
                                window_end_utc='2026-11-12T17:00:00Z')
        row['terms']['per_date_cap'] = '25'
        clock.value += timedelta(days=1)
        second = parse_policy(row)
        with pytest.raises(StateRefused, match='requires_revision'):
            state.claim(second.entries[0], second, clock.now())
        row['policy_revision'] = 2
        third = parse_policy(row)
        assert state.claim(third.entries[0], third, clock.now())['policy_revision'] == 2


def test_pending_money_postchecks_ignore_missing_current_policy_and_never_fall_through(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from tests.market.test_lfc_campaign_recurrence import configure_runtime
    from tests.market.lfc_campaign_fixtures import private_result
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        state, clock = runtime.state, runtime.clock
        configure_runtime(runtime, monkeypatch)
        policy = parse_policy(policy_row())
        claim = state.claim(policy.entries[0], policy, NOW)
        _, result = private_result(runtime, claim)
        runtime.save_result(claim, result)
        monkeypatch.setattr(runtime, 'run_session', lambda *a: pytest.fail('pending proof cannot start a session'))
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        def missing_policy():
            raise FileNotFoundError('synthetic current config missing')
        assert coordinator.tick(missing_policy) == 'POSTCHECKS'
        assert not state.pending()


def test_partial_ledger_rollback_is_detected_by_closeout_anchor(tmp_path):
    clock = Clock()
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        policy = parse_policy(policy_row())
        claim = state.claim(policy.entries[0], policy, NOW)
        old = state.ledger.path.read_bytes()
        state.ledger.record('session_start', session_id='fixture', counted=True)
        state.ledger.record('session_end', session_id='fixture')
        state.close(claim, {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False}, NOW)
        state.ledger.path.write_bytes(old)
        rolled = AccountState(tmp_path / 'state', Ledger.open(state.ledger.path, clock=clock.now))
        with pytest.raises(StateRefused, match='closeout_ledger_continuity'):
            rolled.verify()
