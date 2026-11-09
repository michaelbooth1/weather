"""Guards: B072 wrapper deadline and task duration; pure XML, no Scheduler."""
from datetime import datetime, timedelta, timezone
import json
from xml.etree import ElementTree as ET
import pytest

from tests.market.lfc_pinb_fixtures import pinb_row
from tests.operations.test_lfc_campaign_task import powershell, BASE
from weather.market.lfc_campaign_policy import parse_policy


@pytest.mark.spawns
def test_pinb_wrapper_preserves_1845_end_and_cleanup(tmp_path):
    row = pinb_row(); path = tmp_path/'campaign.json'; path.write_text(json.dumps(row))
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    result = powershell("(Get-LfcCampaignDeadline -CampaignPath '"+str(path).replace("'", "''")+
        "' -NowUtc ([DateTimeOffset]'2026-11-11T14:00:00Z')).ToString('o')")
    assert result.returncode == 0, result.stderr
    deadline = datetime.fromisoformat(result.stdout.strip())
    assert deadline == datetime(2026, 11, 12, 0, 15, tzinfo=timezone.utc)
    for go in (entry.start, entry.end-timedelta(microseconds=1)):
        assert deadline >= entry.session_end(go)+timedelta(minutes=30)


@pytest.mark.spawns
def test_pinb_task_has_eleven_hour_containment_without_an_extra_action():
    result = powershell(BASE+'$xml')
    assert result.returncode == 0, result.stderr
    xml = ET.fromstring(result.stdout.strip()); ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert xml.find('t:Settings/t:ExecutionTimeLimit', ns).text == 'PT11H'
    assert len(xml.findall('t:Actions/t:Exec', ns)) == 1
