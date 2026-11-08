"""Actual authority failures after claiming must retain and close an empty attempt.

Guards: B046 A1 / B010; late go and stale component witnesses, fixture-only.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes, policy_row
from tests.market.test_lfc_campaign_runtime import runtime_at, account_read
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy


@pytest.mark.parametrize('fault', ['late_go', 'account_read_stale'])
def test_actual_start_check_failure_is_retained_and_empty_claim_recovers(tmp_path, monkeypatch, fault):
    from weather.market import lfc_cli, lfc_session_status
    original_status = lfc_session_status.SessionStatus
    def fixture_status(**kw):
        status = original_status(**kw)
        status.stop_file = tmp_path / 'owner-stop-fixture'
        return status
    monkeypatch.setattr(lfc_session_status, 'SessionStatus', fixture_status)
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path, now=datetime(2026, 11, 11, 14, tzinfo=timezone.utc))
        row = policy_row()
        row['entries'][0].update(window_start_utc='2026-11-11T14:00:00Z',
                                  window_end_utc='2026-11-11T14:15:00Z')
        policy = parse_policy(row); entry = policy.entries[0]
        runtime.policy_path.write_text(json.dumps(row))
        runtime.clock.value = entry.end - timedelta(seconds=5) if fault == 'late_go' else entry.start
        runtime.lease = SimpleNamespace(check=lambda: None)
        read = account_read(runtime)
        stamp = runtime.clock.now()
        if fault == 'account_read_stale': stamp -= timedelta(seconds=116)
        read.update(started_at_utc=stamp.isoformat(), ended_at_utc=stamp.isoformat(),
            component_times={name: {'started_at_utc': stamp.isoformat(), 'ended_at_utc': stamp.isoformat()}
                             for name in read['component_times']})
        runtime.pre_go = lambda *a: {'baseline': {}, 'account_read': read,
             'expires_utc': (runtime.clock.now() + timedelta(seconds=120)).isoformat()}
        @contextmanager
        def admission(): yield
        runtime.admission = admission
        monkeypatch.setattr(runtime, 'notify_control', lambda row: None)
        def opening_read(*args, scheduled, **kwargs):
            runtime.clock.sleep(6)
            scheduled.check(starting=True)
            pytest.fail('expired setup must never reach placement')
        monkeypatch.setattr(lfc_cli, '_run_live', opening_read)
        coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock,
                                           control_root=tmp_path / 'control')
        assert coordinator.start(entry, policy, lambda: policy) == 'FAILED_NO_ORDERS'
        claim = runtime.state.claims()[0]
        result = runtime.saved_result(claim)
        assert result and result['unknown_submit'] is False  # No intent or POST exists.
        assert not result['evidence_complete'] and not result['inventory_proven']
        assert result['outcome']['halt_reason'] == 'exception_RuntimeError'
        assert not runtime.state.pending() and not runtime.state.incidents()
        closed = runtime.state.read(runtime.state.root / 'closed' / (claim['attempt_id'] + '.json'))
        assert closed['proof']['unknown_submit'] is False
        assert closed['proof']['authority'] == 'automatic_no_intent'
        assert not runtime.state.ledger.legs and entry.local_date in runtime.state.consumed_dates()
