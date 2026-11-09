"""Guards: B070 an in-session latch is visible before cleanup can fail."""
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, NOW, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import ScheduledAuthority
from weather.market.lfc_campaign_control import latest_control, watch_status, control_record


def test_clock_latch_publishes_incident_before_failed_cleanup(tmp_path, monkeypatch):
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        notifications = []
        runtime.notify_control = notifications.append
        runtime.lease = SimpleNamespace(check=lambda: None)
        policy = parse_policy(policy_row())
        claim = runtime.state.claim(policy.entries[0], policy, NOW)
        authority = ScheduledAuthority(runtime, claim, policy.entries[0], policy, {'baseline': {}})
        control_record(runtime.control_root, claim['attempt_id'], phase='RUNNING', now=NOW,
                       orders_live=True, orders_open_unproven=True)
        assert watch_status(latest_control(runtime.control_root), now=NOW)[1] == 2
        runtime.clock.sleep(16)
        with pytest.raises(RuntimeError, match='clock_or_resume_uncertain'):
            authority.check()
        row = latest_control(runtime.control_root)
        assert row is not None and row['phase'] == 'INCIDENT' and row['incident'] is True
        assert notifications[-1]['phase'] == 'INCIDENT'
        assert watch_status(row, now=runtime.clock.now())[1] == 1
        with pytest.raises(OSError):
            raise OSError('synthetic_cleanup_failed')
        assert latest_control(runtime.control_root) == row
        assert len(runtime.state.ledger.autostart_incidents) == 1
