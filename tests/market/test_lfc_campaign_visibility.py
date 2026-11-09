"""Synthetic unattended alerts and diagnostics; never a real toast or task.

Guards: B040 visibility 1-7, latched incidents, conservative cleanup and disk.
"""
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, StubRuntime, policy_row, state_at
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_control import control_record
from weather.market.lfc_campaign_guard import AdmissionBusy, account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_campaign_visibility import (DISK_FLOOR_BYTES, LOG_BYTES, STALL_SECONDS,
    disk_headroom, notify_control, safe_traceback, stalled, tick_log)


@pytest.fixture(autouse=True)
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


@pytest.mark.parametrize('phase', ['INCIDENT', 'POSTCHECK_PENDING', 'COMPLETE', 'MISSED', 'REFUSED', 'DEFERRED'])
def test_phase_notification_is_safe_and_deduplicated(tmp_path, monkeypatch, phase):
    from weather.market import lfc_pilot
    calls = []
    monkeypatch.setattr(lfc_pilot, 'notify_owner', lambda root, summary, **kw: calls.append((root, summary, kw)))
    runtime = SimpleNamespace(control_root=tmp_path / 'control')
    row = control_record(runtime.control_root, 'a' * 32, phase=phase, now=Clock().now())
    notify_control(runtime, row)
    notify_control(runtime, row)
    assert len(calls) == 1 and calls[0][1] == {}
    assert set(calls[0][2]['public_status']) == {'phase', 'attempt_id', 'orders_open_unproven',
                                               'incident', 'attention_required'}
    notify_control(runtime, {**row, 'phase': 'RUNNING'})
    notify_control(runtime, row)
    assert len(calls) == 2


def test_owner_notice_writes_only_safe_line_with_open_order_warning(tmp_path):
    from weather.market.lfc_pilot import notify_owner
    row = notify_owner(tmp_path, {'fills': 'EMBARGO_SECRET', 'L': 'PRIVATE'}, windows=False,
        printer=lambda *a, **k: None, public_status={'phase': 'INCIDENT', 'attempt_id': 'a' * 32, 'orders_open_unproven': True})
    data = (tmp_path / 'notifications.jsonl').read_text()
    assert 'EMBARGO_SECRET' not in data and 'PRIVATE' not in data and 'orders_open_unproven=true' in data
    assert not row['toast_delivered'] and row['toast_error'] == 'toast_requires_windows'


def test_pending_cannot_hide_existing_incident(tmp_path):
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock)
    policy = parse_policy(policy_row())
    claim = state.claim(policy.entries[0], policy, clock.now())
    state.ledger.record('session_start', session_id='pending', counted=True,
                        autostart_attempt_id=claim['attempt_id'])
    state.ledger.intent(session_id='pending', intent_key='pending:1', token_id='111',
                        condition_id='c', size='20', price='.4', fee_rate_bps='0')
    state.ledger.ack('pending:1', 'known-order')
    state.latch(claim['attempt_id'], 'clock_or_resume_uncertain', clock.now())
    runtime.saved_result = lambda _: {'unknown_submit': False}
    def postcheck(*args): raise TransientPrecheck('read delayed')
    runtime.postcheck = postcheck
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    assert coordinator.pending()
    rows = [json.loads(path.read_text()) for path in (tmp_path / 'control').glob('*.json')]
    assert rows and all(r['phase'] == 'INCIDENT' and r['incident'] and r['orders_open_unproven'] for r in rows)


@pytest.mark.parametrize('reason,expected', [('workload_busy', 'admission_busy'), ('hold_already_owned', 'hold_retained')])
def test_busy_and_retained_hold_have_distinct_reasons_through_window_end(tmp_path, reason, expected):
    clock = Clock()
    state = state_at(tmp_path, clock)
    runtime = StubRuntime(state, clock)
    @contextmanager
    def busy(): raise AdmissionBusy(reason); yield
    runtime.admission = busy
    policy = parse_policy(policy_row())
    coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
    from tests.market.test_lfc_campaign import bind_launch
    policy = bind_launch(coordinator, policy)
    assert coordinator.start(policy.entries[0], policy, lambda: policy) == 'MISSED'
    rows = [json.loads(path.read_text()) for path in (tmp_path / 'control').glob('*.json')]
    assert {r['reason'] for r in rows} == {expected}
    assert runtime.go_count == 0 and not state.ledger.autostart_claims


@pytest.mark.parametrize('delta,accept', [(0, True), (-1, False), (1, True)])
def test_disk_floor_is_five_gib_before_admission(tmp_path, monkeypatch, delta, accept):
    from weather.market import lfc_campaign_visibility as visibility
    assert DISK_FLOOR_BYTES == 5 * 1024 ** 3
    monkeypatch.setattr(visibility.shutil, 'disk_usage', lambda _: SimpleNamespace(free=DISK_FLOOR_BYTES + delta))
    if accept:
        assert disk_headroom(tmp_path)['available_disk_bytes'] >= DISK_FLOOR_BYTES
    else:
        with pytest.raises(StateRefused, match='disk_free_below_floor'): disk_headroom(tmp_path)


def test_stalled_loop_publishes_incident_before_exiting_without_cleanup_claim(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_visibility as visibility
    notices, exits = [], []
    monkeypatch.setattr(visibility, 'notify_control', lambda *a: notices.append(a[1]))
    runtime = SimpleNamespace(control_root=tmp_path / 'control', clock=Clock(), state=SimpleNamespace(policy_binding={}))
    claim = {'attempt_id': 'b' * 32}
    assert not stalled(runtime, claim, last_progress=0, now_mono=STALL_SECONDS, exit_process=exits.append)
    assert stalled(runtime, claim, last_progress=0, now_mono=STALL_SECONDS + 1, exit_process=exits.append)
    assert exits == [1] and notices[0]['phase'] == 'INCIDENT' and notices[0]['orders_open_unproven']
    assert json.loads((tmp_path / 'campaign-ticks.jsonl').read_text())['exit_code'] == 1


@pytest.mark.parametrize('failure', [False, True])
def test_every_cli_tick_records_exit_and_sanitized_traceback(tmp_path, monkeypatch, failure):
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    def dispatch(args, **kw):
        if failure: raise RuntimeError('secret credential path; prices=999 id=private')
        return 0
    monkeypatch.setattr(cli, 'dispatch', dispatch)
    if failure:
        with pytest.raises(RuntimeError): cli.main(['tick'])
    else:
        assert cli.main(['tick']) == 0
    text = (tmp_path / 'campaign-ticks.jsonl').read_text()
    row = json.loads(text)
    assert row['exit_code'] == int(failure) and bool(row['traceback']) == failure
    assert 'secret' not in text and 'credential' not in text and '999' not in text and 'private' not in text


def test_tick_log_rotates_and_retains_old_evidence(tmp_path):
    path = tmp_path / 'campaign-ticks.jsonl'
    path.write_text('x' * LOG_BYTES)
    tick_log(tmp_path, now=Clock().now(), attempt_id='c' * 32, exit_code=0)
    assert len(list(tmp_path.glob('campaign-ticks-*.jsonl'))) == 1
    assert path.stat().st_size < 1024


def test_disk_refusal_precedes_reload_reads_and_date_claim(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_runtime as adapter, lfc_campaign_visibility as visibility, lfc_session_status
    runtime = runtime_at(tmp_path)
    runtime.lease = SimpleNamespace(check=lambda: None)
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path / 'OWNER_ONLY_STOP_FIXTURE')
    monkeypatch.setattr(adapter, 'workstation_headroom', lambda: {})
    monkeypatch.setattr(visibility.shutil, 'disk_usage', lambda _: SimpleNamespace(free=DISK_FLOOR_BYTES - 1))
    monkeypatch.setattr(runtime, 'reload_ledger', lambda: pytest.fail('must refuse before reads'))
    policy = parse_policy(policy_row())
    with pytest.raises(StateRefused, match='disk_free_below_floor'): runtime.pre_go(policy.entries[0], policy)
    assert not runtime.state.ledger.autostart_claims


def test_existing_hold_is_retained_without_any_staleness_guess(tmp_path):
    runtime = runtime_at(tmp_path)
    runtime.hold_path.write_text('retained; owner identity unproved')
    with pytest.raises(AdmissionBusy, match='hold_already_owned'):
        with runtime.admission(): pytest.fail('retained hold cannot admit')
    assert runtime.hold_path.read_text() == 'retained; owner identity unproved'


def test_watchdog_still_exits_when_status_disk_fails(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_visibility as visibility
    def failed(*a, **k): raise OSError('private path must not leak')
    monkeypatch.setattr(visibility, 'control_record', failed)
    runtime = SimpleNamespace(control_root=tmp_path / 'control', clock=Clock(), state=SimpleNamespace(policy_binding={}))
    exits = []
    with pytest.raises(OSError): stalled(runtime, {'attempt_id': 'd' * 32}, last_progress=0,
                                       now_mono=STALL_SECONDS + 1, exit_process=exits.append)
    assert exits == [1]
