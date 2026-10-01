"""Stage B's overnight trigger cannot collide with another shared-lease holder.

The former 00:35 trigger fell inside the cold-snapshot nightly's 00:30-04:45
lease, so every scheduled Stage B run refused. These tests pin the 05:00
schedule against the other registrars' literals and exercise the collision
check and bounded lease wait the registrar and wrapper share.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
CONTRACT = OPS / "daily_refresh_contract.ps1"
WRAPPER = OPS / "daily_refresh.ps1"
REGISTER = OPS / "register_daily_refresh.ps1"
COLD_REGISTER = OPS / "register_cold_snapshot_nightly.ps1"
COLD_RUN = OPS / "cold_snapshot_nightly_run.ps1"
TRAINING_REGISTER = OPS / "register_training_window.ps1"

windows_only = pytest.mark.skipif(os.name != "nt", reason="PowerShell contract")


def _minute(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _contract_text():
    return CONTRACT.read_text(encoding="utf-8-sig")


def test_evidence_trigger_follows_the_cold_snapshot_nightly_hard_end():
    contract = _contract_text()
    trigger = re.search(r'TriggerAt = "(\d\d:\d\d)"', contract).group(1)

    cold_register = COLD_REGISTER.read_text(encoding="utf-8-sig")
    cold_at = re.search(r"New-ScheduledTaskTrigger -Daily -At '(\d\d:\d\d)'", cold_register).group(1)
    cold_limit = int(re.search(r"New-TimeSpan -Minutes (\d+)", cold_register).group(1))
    cold_run = COLD_RUN.read_text(encoding="utf-8-sig")
    cold_hard_stop = int(re.search(r"AddMinutes\((\d+)\)", cold_run).group(1))

    assert _minute(cold_at) + cold_limit <= _minute(trigger)
    assert cold_hard_stop <= _minute(trigger)
    # The retired trigger sat inside the nightly's lease.
    assert _minute(cold_at) < _minute("00:35") < _minute(cold_at) + cold_limit


def test_evidence_trigger_follows_the_training_restore_and_quiet_window():
    contract = _contract_text()
    trigger = _minute(re.search(r'TriggerAt = "(\d\d:\d\d)"', contract).group(1))
    training = TRAINING_REGISTER.read_text(encoding="utf-8-sig")
    restore_at = re.search(r'\$RestoreAt = "(\d\d:\d\d)"', training).group(1)
    assert "-ExecutionTimeLimit (New-TimeSpan -Minutes 15)" in training

    assert _minute(restore_at) + 15 <= trigger
    assert _minute("04:00") <= trigger  # quiet merge window end


def test_evidence_lease_wait_stays_inside_scheduler_correlation():
    contract = _contract_text()
    wait = int(re.search(r"LeaseWaitSeconds = (\d+)", contract).group(1))
    retry = int(re.search(r"LeaseRetrySeconds = (\d+)", contract).group(1))
    correlation = int(
        re.search(r'"--scheduler-correlation-seconds", "(\d+)"', contract).group(1)
    )

    assert 0 < retry < wait < correlation
    # Leave at least a minute for the child to start and attest.
    assert correlation - wait >= 60


def test_wrapper_waits_for_the_lease_only_on_the_evidence_stage():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    evidence_branch = wrapper.split('if ($Stage -eq "evidence") {\n    # Absorb', 1)[1]
    evidence_branch = evidence_branch.split("} else {", 1)[0]

    assert "Enter-DailyRefreshLeaseWithin -Acquire $acquireLease" in evidence_branch
    assert "$evidenceSchedule.LeaseWaitSeconds" in evidence_branch
    assert "$workloadLease = & $acquireLease" in wrapper
    assert wrapper.index("Enter-DailyRefreshLeaseWithin") < wrapper.index(
        "Start-WeatherProcessInJob"
    )
    assert 'Write-Output "REFUSED: another heavyweight host workload' in wrapper


def test_registration_refuses_overlap_before_registering_anything():
    registration = REGISTER.read_text(encoding="utf-8-sig")

    check = registration.index("Get-DailyRefreshEvidenceTriggerCollisions")
    assert check < registration.index("Register-ScheduledTask")
    assert "OvernightLeaseHolderTaskPatterns" in registration
    assert "overlaps an enabled shared-lease holder" in registration
    assert "SLA + lease wait < wrapper span < Scheduler limit" in registration
    for name in (
        "WeatherColdSnapshotNightly",
        "WeatherTrainingWindow",
        "WeatherNightlyRetrainValidatePromote",
        "WeatherIntegrationSuite_*",
        "WeatherIntegrationMerge_*",
    ):
        assert f'"{name}"' in _contract_text()


def _run_contract(body):
    env = os.environ.copy()
    env["WEATHER_DAILY_CONTRACT"] = str(CONTRACT)
    script = "$ErrorActionPreference = 'Stop'\n. $env:WEATHER_DAILY_CONTRACT\n" + body
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@windows_only
def test_collision_check_classifies_lease_holder_windows():
    rows = _run_contract(r"""
$now = [datetime]'2026-10-01T12:00:00'
function Holder($name, $start, $recurring, $limit) {
    [pscustomobject]@{
        TaskName = $name; StartBoundary = [datetime]$start
        Recurring = $recurring; ExecutionTimeLimit = $limit
    }
}
$cases = [ordered]@{
    nightly_at_0500 = @{ at = '05:00'; holders = @(Holder 'Cold' '2026-09-30T00:30:00' $true 'PT4H15M') }
    nightly_at_0035 = @{ at = '00:35'; holders = @(Holder 'Cold' '2026-09-30T00:30:00' $true 'PT4H15M') }
    training_once = @{ at = '05:00'; holders = @(Holder 'Train' '2026-10-02T01:00:00' $false 'PT3H45M') }
    late_training_once = @{ at = '05:00'; holders = @(Holder 'Train' '2026-10-02T01:30:00' $false 'PT3H45M') }
    past_suite_once = @{ at = '05:00'; holders = @(Holder 'Suite' '2026-09-30T00:30:00' $false 'PT8H') }
    future_suite_once = @{ at = '05:00'; holders = @(Holder 'Suite' '2026-10-02T00:30:00' $false 'PT8H') }
    unbounded = @{ at = '05:00'; holders = @(Holder 'Loose' '2026-09-30T02:00:00' $true '') }
    zero_limit = @{ at = '05:00'; holders = @(Holder 'Loose' '2026-09-30T02:00:00' $true 'PT0S') }
    wraps_midnight = @{ at = '05:00'; holders = @(Holder 'Late' '2026-09-30T23:00:00' $true 'PT7H') }
    ends_at_trigger = @{ at = '05:00'; holders = @(Holder 'Edge' '2026-09-30T04:00:00' $true 'PT1H') }
    after_stage_b = @{ at = '05:00'; holders = @(Holder 'StageA' '2026-09-30T09:30:00' $true 'PT4H') }
    none = @{ at = '05:00'; holders = @() }
}
$out = [ordered]@{}
foreach ($key in $cases.Keys) {
    $found = @(Get-DailyRefreshEvidenceTriggerCollisions -Holders $cases[$key].holders `
        -EvidenceAt $cases[$key].at -EvidenceLimitMinutes 255 -Now $now)
    $out[$key] = @($found | ForEach-Object { $_.TaskName })
}
$out | ConvertTo-Json -Compress
""")

    assert rows["nightly_at_0500"] == []
    assert rows["nightly_at_0035"] == ["Cold"]
    assert rows["training_once"] == []
    assert rows["late_training_once"] == ["Train"]
    assert rows["past_suite_once"] == []
    assert rows["future_suite_once"] == ["Suite"]
    assert rows["unbounded"] == ["Loose"]
    assert rows["zero_limit"] == ["Loose"]
    assert rows["wraps_midnight"] == ["Late"]
    assert rows["ends_at_trigger"] == []
    assert rows["after_stage_b"] == []
    assert rows["none"] == []


@windows_only
def test_lease_wait_retries_then_acquires_or_refuses_within_budget():
    result = _run_contract(r"""
function Run-Case([int]$freeAfter, [int]$wait, [int]$retry) {
    $state = @{ now = [datetime]'2026-10-02T09:00:00Z'; calls = 0; slept = @() }
    $lease = Enter-DailyRefreshLeaseWithin `
        -Acquire { $state.calls += 1; if ($state.calls -gt $freeAfter) { 'LEASE' } else { $null } }.GetNewClosure() `
        -WaitSeconds $wait -RetrySeconds $retry `
        -Sleep { param($s) $state.slept += $s; $state.now = $state.now.AddSeconds($s) }.GetNewClosure() `
        -Clock { $state.now }.GetNewClosure()
    [ordered]@{
        lease = $lease; calls = $state.calls
        slept = @($state.slept); total = ($state.slept | Measure-Object -Sum).Sum
    }
}
[ordered]@{
    immediate = Run-Case 0 240 15
    after_three = Run-Case 3 240 15
    never = Run-Case 1000 240 15
    uneven = Run-Case 1000 40 15
} | ConvertTo-Json -Compress -Depth 4
""")

    assert result["immediate"]["lease"] == "LEASE"
    assert result["immediate"]["calls"] == 1
    assert result["immediate"]["slept"] == []

    assert result["after_three"]["lease"] == "LEASE"
    assert result["after_three"]["calls"] == 4
    assert result["after_three"]["slept"] == [15, 15, 15]

    assert result["never"]["lease"] is None
    assert result["never"]["total"] == 240
    assert result["never"]["calls"] == 240 // 15 + 1

    assert result["uneven"]["lease"] is None
    assert result["uneven"]["slept"] == [15, 15, 10]
