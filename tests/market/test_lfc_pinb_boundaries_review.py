"""Guards: Pin B effective Scheduler containment, not just child hand-off."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_campaign import MAKER, Mutexes, StubRuntime
from tests.market.test_lfc_pinb_migration import existing_pina, stamp
from tests.operations.test_lfc_campaign_task import powershell
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_launch import require_launch, LaunchDeferred
from weather.market.lfc_campaign_policy import load_policy


def native_launch(path, now):
    result = powershell("Get-LfcCampaignLaunch -CampaignPath '" + str(path).replace("'", "''") +
        "' -NowUtc ([DateTimeOffset]'" + now.isoformat() + "') | ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.spawns
@pytest.mark.parametrize('early', [False, True])
def test_admitted_retry_session_and_cleanup_fit_scheduler_limit(tmp_path, early):
    row = pinb_row(); row['enabled'] = True
    row['start_window_toronto'] = ['07:00:00', '09:00:00'] if early else ['09:00:00', '09:15:00']
    path = tmp_path/'policy.json'; path.write_text(json.dumps(row))
    policy = load_policy(path)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    launch = native_launch(path, entry.start)
    wrapper_kill = datetime.fromisoformat(launch['deadline_utc'])
    scheduler_kill = entry.start + timedelta(hours=11)
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, old, old_claim = existing_pina(tmp_path/'account')
        clock.value = entry.start
        runtime = StubRuntime(state, clock)
        runtime.notify_control = lambda row: None
        ready = entry.end - timedelta(minutes=2)
        def retry(entry, policy):
            if clock.now() < ready: raise TransientPrecheck('one_continuous_transport_outage')
            return {'fixture': True}
        runtime.pre_go = retry
        calls = []
        ordinary = runtime.run_session
        def run(claim, selected, current, prepared):
            require_launch(launch, current, selected)
            calls.append({'go': clock.now(), 'end': selected.session_end(clock.now())})
            return ordinary(claim, selected, current, prepared)
        runtime.run_session = run
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock,
            control_root=tmp_path/'control', wrapper_launch=launch)
        outcome = coordinator.tick(lambda: load_policy(path))
        assert outcome == 'STARTED' and len(calls) == 1 and not state.incidents()
        actual = calls[0]
        assert actual['end'] + timedelta(minutes=30) <= min(wrapper_kill, scheduler_kill), {
            'go': str(actual['go']), 'end': str(actual['end']), 'wrapper_kill': str(wrapper_kill),
            'scheduler_kill': str(scheduler_kill), 'claims': len(state.ledger.autostart_claims)}


@pytest.mark.spawns
@pytest.mark.parametrize('minutes', [-15, 0, 14])
def test_default_pinb_deadline_and_one_second_short_refusal(tmp_path, minutes):
    row = pinb_row(); path = tmp_path/'policy.json'; path.write_text(json.dumps(row))
    policy = load_policy(path)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    now = entry.start+timedelta(minutes=minutes)
    launch = native_launch(path, now)
    deadline = datetime.fromisoformat(launch['deadline_utc'])
    assert deadline == stamp('2026-11-13T00:15:00Z')
    require_launch(launch, policy, entry)
    assert deadline <= now+timedelta(hours=11)
    with pytest.raises(LaunchDeferred, match='wrapper_cleanup_budget_insufficient'):
        require_launch({**launch, 'deadline_utc': (deadline-timedelta(seconds=1)).isoformat()}, policy, entry)
