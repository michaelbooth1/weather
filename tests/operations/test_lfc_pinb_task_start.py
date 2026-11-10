"""Guards: B074 outer action creation time crosses the native wrapper seam."""
from datetime import datetime, timezone
import json
import os
import subprocess
import pytest

from tests.market.test_lfc_campaign_windowless import fixture, argv
from tests.native_child_environment import clean_native_environment


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='Windows GUI action and process creation time')
def test_windowless_action_passes_its_native_start_to_an_inert_wrapper(tmp_path):
    marker = tmp_path/'observed-start.json'
    body = ("param([string]$ReleasePath,[string]$ReleaseSha256,[DateTimeOffset]$TaskStartedUtc)\n"
        "@{started=$TaskStartedUtc.ToString('o');observed=[DateTimeOffset]::UtcNow.ToString('o')} | "
        "ConvertTo-Json -Compress | Set-Content -LiteralPath '"+str(marker).replace("'", "''")+"'")
    pythonw, launcher, release, row = fixture(tmp_path, body)
    before = datetime.now(timezone.utc)
    child = subprocess.run(argv(pythonw, launcher, release), timeout=15, env=clean_native_environment())
    assert child.returncode == 0
    result = json.loads(marker.read_text())
    started, observed = (datetime.fromisoformat(result[key]) for key in ('started', 'observed'))
    assert before <= started <= observed <= datetime.now(timezone.utc)


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='PowerShell timestamp contract')
def test_launch_normalizes_offset_aware_task_start_to_utc(tmp_path):
    from tests.operations.test_lfc_campaign_task import powershell
    from weather.market.lfc_f2_pinb import example_policy
    policy = tmp_path/'campaign.json'
    policy.write_text(json.dumps(example_policy()))
    path = str(policy).replace("'", "''")
    local = powershell(f"Get-LfcCampaignLaunch -CampaignPath '{path}' -NowUtc '2026-11-11T09:00:00-05:00' -TaskStartedUtc '2026-11-11T08:59:00-05:00' | ConvertTo-Json -Compress")
    utc = powershell(f"Get-LfcCampaignLaunch -CampaignPath '{path}' -NowUtc '2026-11-11T14:00:00Z' -TaskStartedUtc '2026-11-11T13:59:00Z' | ConvertTo-Json -Compress")
    assert local.returncode == utc.returncode == 0, local.stderr+utc.stderr
    assert json.loads(local.stdout) == json.loads(utc.stdout)
    assert datetime.fromisoformat(json.loads(local.stdout)['deadline_utc']).utcoffset().total_seconds() == 0


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='PowerShell timestamp contract')
@pytest.mark.parametrize('value', ["'2026-11-11T13:59:00'", "([datetime]'2026-11-11T13:59:00')", '$null'])
def test_launch_refuses_naive_or_missing_explicit_task_start(tmp_path, value):
    from tests.operations.test_lfc_campaign_task import powershell
    policy = str(tmp_path/'unused.json').replace("'", "''")
    result = powershell(f"try {{ Get-LfcCampaignLaunch -CampaignPath '{policy}' -NowUtc '2026-11-11T14:00:00Z' -TaskStartedUtc {value}; throw 'accepted' }} catch {{ if($_.Exception.Message -eq 'accepted'){{throw}}; 'REFUSED' }}")
    assert result.returncode == 0 and result.stdout.strip() == 'REFUSED'


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='PowerShell wrapper mandatory argument')
def test_real_wrapper_refuses_missing_native_task_start_before_release_read(tmp_path):
    from weather.paths import REPO_ROOT
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',
        str(REPO_ROOT/'scripts/ops/lfc_campaign_task.ps1'), '-ReleasePath',str(tmp_path/'missing.json'),
        '-ReleaseSha256','a'*64], capture_output=True,text=True,timeout=15,env=clean_native_environment())
    assert result.returncode != 0 and 'TaskStartedUtc' in result.stderr
