"""Guards: B072 owner-only same-task upgrade; pure guards, no Scheduler access."""
import pytest
from tests.operations.test_lfc_campaign_task import powershell


PREVIOUS = r"""
$old=[pscustomobject]@{campaign_path='C:\fixture\campaign.json';maker_address='0xabc';ledger_genesis_sha256='genesis';state_id='state';host_id='host';principal_id='principal';task_name='WeatherLFCCampaign'}
$next=[pscustomobject]@{campaign_path='C:\fixture\campaign.json';maker_address='0xabc';ledger_genesis_sha256='genesis';state_id='state';host_id='host';principal_id='principal';task_name='WeatherLFCCampaign'}
"""


@pytest.mark.spawns
def test_owner_upgrade_guard_accepts_only_disabled_matching_identity():
    result = powershell(PREVIOUS + r"Assert-LfcCampaignUpgrade -Previous $old -Successor $next -CampaignPath 'C:\fixture\campaign.json' -Enabled $false -State 'Disabled'")
    assert result.returncode == 0 and result.stdout.strip() == 'True', result.stderr


@pytest.mark.spawns
@pytest.mark.parametrize('change', ["$next.state_id='different'", "$next.ledger_genesis_sha256='different'",
    "$next.maker_address='different'", r"$next.campaign_path='C:\fixture\other.json'",
    "$next.host_id='different'", "$next.principal_id='different'", "$next.task_name='OtherTask'"])
def test_owner_upgrade_guard_refuses_any_account_or_task_reset(change):
    result = powershell(PREVIOUS + change + r"; try {Assert-LfcCampaignUpgrade -Previous $old -Successor $next -CampaignPath 'C:\fixture\campaign.json' -Enabled $false -State 'Disabled'} catch { 'refused' }")
    assert result.returncode == 0 and result.stdout.strip() == 'refused'


@pytest.mark.spawns
@pytest.mark.parametrize('enabled,state', [('$true', 'Ready'), ('$false', 'Running'), ('$false', 'Queued')])
def test_owner_upgrade_guard_refuses_a_live_or_enabled_predecessor(enabled, state):
    result = powershell(PREVIOUS + r"try {Assert-LfcCampaignUpgrade -Previous $old -CampaignPath 'C:\fixture\campaign.json' -Enabled "+enabled+" -State '"+state+"'} catch {'refused'}")
    assert result.returncode == 0 and result.stdout.strip() == 'refused'
