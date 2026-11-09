"""Guards: B071 one incident occurrence notifies once without delaying cleanup."""
from threading import Event, Thread
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW, policy_row
from tests.market.test_lfc_review_b067_integrity import prepared
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_campaign_runtime import ScheduledAuthority
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_control import latest_control, control_record


def test_same_incident_flag_changes_do_not_send_another_toast(tmp_path, monkeypatch):
    from weather.market import lfc_pilot
    from weather.market.lfc_campaign_visibility import notify_control
    from tests.market.test_lfc_campaign import Clock
    notices = []
    monkeypatch.setattr(lfc_pilot, 'notify_owner', lambda *a, **kw: notices.append(kw))
    runtime = SimpleNamespace(control_root=tmp_path/'control', clock=Clock())
    for unproven in (True, False, True):
        row = control_record(runtime.control_root, 'a'*32, phase='INCIDENT', now=NOW,
                             incident=True, orders_open_unproven=unproven)
        notify_control(runtime, row)
    assert len(notices) == 1
    row = control_record(runtime.control_root, 'b'*32, phase='INCIDENT', now=NOW, incident=True)
    notify_control(runtime, row)
    assert len(notices) == 2


def test_repeated_evidence_fault_notifies_only_the_new_occurrence(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, policy, claim, proof = prepared(tmp_path, monkeypatch)
        notices, notified = [], Event()
        def notify(row): notices.append(row); notified.set()
        runtime.notify_control = notify
        runtime.state.close(claim, proof, NOW)
        (runtime.state.root/'closed'/(claim['attempt_id']+'.json')).unlink()
        with pytest.raises(StateRefused): runtime.state.verify()
        assert notified.wait(2)
        before = len(list(runtime.control_root.glob('*.json')))
        for _ in range(4):
            runtime.clock.sleep(1)
            with pytest.raises(StateRefused): runtime.state.verify()
        assert len(runtime.state.ledger.autostart_incidents) == 1
        assert len(list(runtime.control_root.glob('*.json'))) == before == 1
        assert len(notices) == 1


def test_blocking_toast_cannot_delay_cleanup_start(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
    runtime.lease = SimpleNamespace(check=lambda: None)
    authority = ScheduledAuthority(runtime, claim, policy.entries[0], policy, {'baseline': {}})
    runtime.clock.sleep(16)
    entered, release, cleanup = Event(), Event(), Event()
    errors = []
    def blocking_notice(row):
        assert latest_control(runtime.control_root)['phase'] == 'INCIDENT'
        entered.set(); release.wait(5)
    runtime.notify_control = blocking_notice
    def run():
        try:
            with account_lease(MAKER, backend=Mutexes()):
                try: authority.check()
                except RuntimeError: cleanup.set()
        except BaseException as exc: errors.append(type(exc).__name__)
    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        assert latest_control(runtime.control_root)['phase'] == 'INCIDENT'
        assert cleanup.wait(.25), 'blocked notification delayed normal cleanup'
    finally:
        release.set(); thread.join(2)
    assert not thread.is_alive() and not errors
