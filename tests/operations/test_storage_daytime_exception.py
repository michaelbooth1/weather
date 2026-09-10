"""Each dated owner exception preserves every non-time admission gate."""
from datetime import datetime
import json
import os
import subprocess
from zoneinfo import ZoneInfo

import pytest

from weather.operations import replay_cache_compression_admission as admission
from weather.operations import cold_snapshot_compression as cold
from weather.operations import storage_recovery_inventory_cli as inventory
from weather.paths import repo_path


TOKEN = admission.STORAGE_DAYTIME_EXCEPTION
TOKEN_SEPTEMBER_9 = "OWNER_APPROVED_STORAGE_RECOVERY_20260909"
NOW = datetime(2026, 9, 8, 12, tzinfo=ZoneInfo("America/Toronto"))


def healthy_arguments():
    return dict(now=NOW, available=8 * admission.GIB, commit=50,
                free_disk=30 * admission.GIB, loops=[
                    {"name": name, "active": True, "degraded": False,
                     "heartbeat_fresh": True, "pid_agreement": True,
                     "heartbeat_age_seconds": 1, "last_clean_iteration_age_seconds": 60,
                     "process_identity_matches_lock": True,
                     "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True}}
                    for name in ("snapshot", "clob", "observation_trigger")])


@pytest.mark.parametrize("checker", [cold.check_resources, inventory.check_resources])
@pytest.mark.parametrize("instant,token,allowed", [
    (NOW.replace(hour=9), TOKEN, True), (NOW.replace(hour=17, minute=59), TOKEN, True),
    (NOW, "", False), (NOW, "wrong", False),
    (NOW.replace(hour=8, minute=59), TOKEN, False),
    (NOW.replace(hour=18), TOKEN, False), (NOW.replace(day=9), TOKEN, False),
    (NOW.replace(hour=5), TOKEN, False),
    (NOW.replace(day=9, hour=9), TOKEN_SEPTEMBER_9, True),
    (NOW.replace(day=9, hour=17, minute=59), TOKEN_SEPTEMBER_9, True),
    (NOW.replace(day=9, hour=8, minute=59), TOKEN_SEPTEMBER_9, False),
    (NOW.replace(day=9, hour=18), TOKEN_SEPTEMBER_9, False),
    (NOW.replace(day=10), TOKEN_SEPTEMBER_9, False),
    (NOW, TOKEN_SEPTEMBER_9, False),
    (NOW.replace(day=9), TOKEN_SEPTEMBER_9.lower(), False),
])
def test_exception_date_time_and_explicit_scope(checker, instant, token, allowed):
    arguments = healthy_arguments()
    arguments["now"] = instant
    assert (checker(**arguments, owner_approved_exception=token)["status"] == "PASS") is allowed


@pytest.mark.parametrize("checker", [cold.check_resources, inventory.check_resources])
@pytest.mark.parametrize("fault", ["physical", "commit", "disk", "loops", "identity", "heartbeat", "clean"])
@pytest.mark.parametrize("day", [8, 9])
def test_storage_exception_keeps_resource_and_capture_refusals(checker, fault, day):
    arguments = healthy_arguments()
    arguments["now"] = NOW.replace(day=day)
    token = TOKEN if day == 8 else TOKEN_SEPTEMBER_9
    if fault == "physical": arguments["available"] = 4 * admission.GIB - 1
    elif fault == "commit": arguments["commit"] = 70
    elif fault == "disk": arguments["free_disk"] = 0
    elif fault == "loops": arguments["loops"] = []
    elif fault == "identity": arguments["loops"][0]["process_identity_matches_lock"] = False
    elif fault == "heartbeat": arguments["loops"][0]["heartbeat_age_seconds"] = 181
    elif fault == "clean": arguments["loops"][0]["last_clean_iteration_age_seconds"] = 901
    assert checker(**arguments, owner_approved_exception=token)["status"] == "BLOCK"


def test_cache_lane_stays_overnight_only():
    assert admission.check_resources(**healthy_arguments())["status"] == "BLOCK"


@pytest.mark.parametrize("policy,token,instant,allowed", [
    (admission.STORAGE_DAYTIME_POLICY, TOKEN, NOW, True),
    ("agent_heavy", "", NOW.replace(hour=1), True),
    (admission.STORAGE_DAYTIME_POLICY, "", NOW, False),
    ("agent_heavy", TOKEN, NOW, False),
    (admission.STORAGE_DAYTIME_POLICY, TOKEN, NOW.replace(hour=18), False),
    ("owner_approved_storage_recovery_20260909", TOKEN_SEPTEMBER_9, NOW.replace(day=9), True),
    ("owner_approved_storage_recovery_20260909", "", NOW.replace(day=9), False),
    (admission.STORAGE_DAYTIME_POLICY, TOKEN_SEPTEMBER_9, NOW.replace(day=9), False),
    ("owner_approved_storage_recovery_20260909", TOKEN, NOW, False),
    ("owner_approved_storage_recovery_20260909", TOKEN_SEPTEMBER_9, NOW.replace(day=10), False),
])
def test_exception_must_match_live_lease_policy(policy, token, instant, allowed):
    if allowed:
        admission.verify_storage_exception({"policy_window": policy}, token, instant)
    else:
        with pytest.raises(ValueError):
            admission.verify_storage_exception({"policy_window": policy}, token, instant)


@pytest.mark.skipif(os.name != "nt", reason="native PowerShell policy")
@pytest.mark.parametrize("day", [8, 9])
def test_native_policy_date_boundaries_and_workload_scope(day):
    # Mock identities only in this disposable test process; all negative scope
    # checks must occur before acquisition of any real lease or mutex.
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_TEST_ADMISSION
$day = [datetime]::Parse($env:WEATHER_TEST_STORAGE_DATE)
$token = 'OWNER_APPROVED_STORAGE_RECOVERY_' + $day.ToString('yyyyMMdd')
$accepted = Get-WeatherHeavyWorkloadPolicyWindow -Now $day.AddHours(12) -OwnerApprovedException $token
$refused = 0
foreach ($instant in @($day.AddHours(8).AddMinutes(59), $day.AddHours(18), $day.AddDays(1).AddHours(12))) {
    try { Get-WeatherHeavyWorkloadPolicyWindow -Now $instant -OwnerApprovedException $token }
    catch { $refused++ }
}
function Get-WeatherExecutionHostId { return ('a' * 64) }
function Get-WeatherExecutionHostAssignment {
    return @{ dedicated_capture_execution_host_id = ('a' * 64) }
}
$scoped = 0
foreach ($workload in @('quiet_window_merge', 'replay_cache_compression', 'pytest', 'archive')) {
    try { Enter-WeatherHeavyWorkloadLease -RepoRoot $env:TEMP -Workload $workload -OwnerApprovedException $token }
    catch {
        if ($_.Exception.Message -notlike '*restricted to dedicated capture storage recovery*') { throw }
        $scoped++
    }
}
[pscustomobject]@{accepted=$accepted; refused=$refused; scoped=$scoped} | ConvertTo-Json -Compress
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            env={**os.environ, "WEATHER_TEST_ADMISSION": str(repo_path("scripts/ops/workload_admission.ps1")),
                                 "WEATHER_TEST_STORAGE_DATE": f"2026-09-{day:02d}"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"accepted": f"owner_approved_storage_recovery_202609{day:02d}", "refused": 3, "scoped": 4}
