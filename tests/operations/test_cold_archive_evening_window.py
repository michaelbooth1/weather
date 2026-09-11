"""The evening owner exception remains exact, expiring, and archive-only."""
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess

import pytest

from weather.operations import replay_cache_compression_admission as admission
from weather.operations import production_cold_archive_stage_cli as staging
from weather.paths import repo_path


@pytest.mark.parametrize("stamp,accepted", [
    ("2026-09-10T22:30:00", False),
    ("2026-09-10T23:43:23", False),
    ("2026-09-10T23:43:24", True),
    ("2026-09-11T04:29:59", True),
    ("2026-09-11T04:30:00", False),
    ("2026-09-12T00:00:00", False),
])
def test_evening_token_has_no_retroactive_gap_or_late_authority(stamp, accepted):
    now = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    token = admission.ARCHIVE_EVENING_EXCEPTION
    assert admission.storage_daytime_authorized(now, token) is accepted
    lease = {"policy_window": token.lower()}
    if accepted:
        assert staging.verify_archive_exception(lease, now, exception=token) == token
    else:
        with pytest.raises(ValueError):
            staging.verify_archive_exception(lease, now, exception=token)


def test_evening_deadline_still_reserves_teardown():
    token = admission.ARCHIVE_EVENING_EXCEPTION
    now = datetime(2026, 9, 11, 4, 27, tzinfo=timezone.utc)
    staging.verify_archive_deadline(datetime(2026, 9, 11, 4, 29, 45, tzinfo=timezone.utc), now, token)
    with pytest.raises(ValueError, match="teardown"):
        staging.verify_archive_deadline(datetime(2026, 9, 11, 4, 29, 46, tzinfo=timezone.utc), now, token)


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"), reason="native Windows lease")
def test_native_evening_policy_refuses_expired_gap_and_stage_a():
    script = r"""
$ErrorActionPreference='Stop'
. $env:ARCHIVE_LEASE_SOURCE
$token='OWNER_APPROVED_ARCHIVE_RECOVERY_20260910_EVENING'
$accepted=Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-09-10T19:43:24' -OwnerApprovedException $token
$refused=0
foreach($stamp in @('2026-09-10T18:30:00','2026-09-10T19:43:23','2026-09-11T00:30:00')){
 try{Get-WeatherHeavyWorkloadPolicyWindow -Now $stamp -OwnerApprovedException $token|Out-Null}
 catch{$refused+=1}
}
try{Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-09-10T20:00:00' -OwnerApprovedException $token -AllowStageAWindow|Out-Null}
catch{$refused+=1}
@{accepted=$accepted;refused=$refused}|ConvertTo-Json -Compress
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            env={**os.environ, "ARCHIVE_LEASE_SOURCE": str(repo_path("scripts/ops/workload_admission.ps1"))},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"accepted": "owner_approved_archive_recovery_20260910_evening", "refused": 4}


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"), reason="native Windows lease")
@pytest.mark.parametrize("workload,host,stage_a", [
    ("quiet_window_merge", "a", False), ("storage_recovery_inventory", "a", False),
    ("cold_snapshot_compression", "a", False), ("production_cold_archive_reclaim", "b", False),
    ("production_cold_archive_stage", "a", True),
])
def test_native_evening_lease_cannot_authorize_other_workloads(tmp_path, workload, host, stage_a):
    script = r"""
$ErrorActionPreference='Stop'
. $env:ARCHIVE_LEASE_SOURCE
function Get-WeatherExecutionHostId{return $env:ARCHIVE_HOST}
function Get-WeatherExecutionHostAssignment{return [pscustomobject]@{dedicated_capture_execution_host_id=('a'*64)}}
try{
 Enter-WeatherHeavyWorkloadLease -RepoRoot $env:ARCHIVE_ROOT -Workload $env:ARCHIVE_WORKLOAD -OwnerApprovedException 'OWNER_APPROVED_ARCHIVE_RECOVERY_20260910_EVENING' -AllowStageAWindow:($env:ARCHIVE_STAGE_A -ceq 'True')
 throw 'unexpected admission'
}catch{
 if($_.Exception.Message -cne 'owner-approved archive exception requires the dedicated capture archive lane'){throw}
 'REFUSED_BEFORE_LEASE'
}
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            env={**os.environ, "ARCHIVE_LEASE_SOURCE": str(repo_path("scripts/ops/workload_admission.ps1")),
                                 "ARCHIVE_ROOT": str(tmp_path), "ARCHIVE_WORKLOAD": workload,
                                 "ARCHIVE_HOST": host * 64, "ARCHIVE_STAGE_A": str(stage_a)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REFUSED_BEFORE_LEASE"
    assert list(tmp_path.iterdir()) == []
