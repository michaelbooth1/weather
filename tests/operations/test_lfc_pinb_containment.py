"""Guards: B074 native/Python effective ends fit the earliest PT11H task kill."""
from datetime import timedelta
import json
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.market.test_lfc_pinb_boundaries_review import native_launch
from weather.market.lfc_campaign_launch import require_launch, LaunchDeferred
from weather.market.lfc_campaign_policy import load_policy


@pytest.mark.spawns
@pytest.mark.parametrize('window,end', [(['07:00:00', '09:00:00'], '17:25'),
    (['08:00:00', '10:00:00'], '18:25'), (['09:00:00', '09:15:00'], '18:45')])
def test_earliest_full_envelope_tick_and_latest_go_fit_scheduler(window, end, tmp_path):
    row = pinb_row(); row['start_window_toronto'] = window
    path = tmp_path/'campaign.json'; path.write_text(json.dumps(row)); policy = load_policy(path)
    from weather.market.lfc_campaign_policy import ZONE
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    assert entry.fixed_end.astimezone(ZONE).strftime('%H:%M') == end
    lookback = max(timedelta(minutes=5), timedelta(minutes=30)-(entry.end-entry.start))
    earliest = entry.start-lookback
    for launched in (earliest, entry.start, entry.end-timedelta(seconds=1)):
        packet = native_launch(path, launched)
        require_launch(packet, policy, entry)
        from datetime import datetime
        assert entry.session_end(entry.end)+timedelta(minutes=30) <= datetime.fromisoformat(packet['deadline_utc']) <= launched+timedelta(hours=11)
    with pytest.raises(LaunchDeferred, match='wrapper_cleanup_budget_insufficient'):
        require_launch(native_launch(path, earliest-timedelta(seconds=1)), policy, entry)


@pytest.mark.spawns
def test_slow_outer_launcher_cannot_shift_its_scheduler_deadline(tmp_path):
    from datetime import datetime
    from tests.operations.test_lfc_campaign_task import powershell
    row = pinb_row(); path = tmp_path/'campaign.json'; path.write_text(json.dumps(row)); policy = load_policy(path)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    # PowerShell starts on time, but the outer action began three hours earlier.
    began = entry.start-timedelta(hours=3)
    result = powershell("Get-LfcCampaignLaunch -CampaignPath '"+str(path).replace("'", "''")+
        "' -NowUtc ([DateTimeOffset]'"+entry.start.isoformat()+"') -TaskStartedUtc ([DateTimeOffset]'"+
        began.isoformat()+"') | ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    packet = json.loads(result.stdout)
    assert datetime.fromisoformat(packet['deadline_utc']) == began+timedelta(hours=11)
    with pytest.raises(LaunchDeferred, match='wrapper_cleanup_budget_insufficient'):
        require_launch(packet, policy, entry)
