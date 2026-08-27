from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
WRAPPERS = (
    "training_window.ps1",
    "quiet_window_merge.ps1",
    "bounded_worktree_test_suite.ps1",
    "bounded_execution_tape_probe.ps1",
    "clob_tiering_run.ps1",
    "clob_raw_tape_tiering_run.ps1",
    "daily_refresh.ps1",
)


def _inside_heavy_window() -> bool:
    now = datetime.now()
    minute = now.hour * 60 + now.minute
    return 30 <= minute < 9 * 60


def test_every_heavy_wrapper_uses_the_shared_lease() -> None:
    for name in WRAPPERS:
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "workload_admission.ps1" in text, name
        assert "Enter-WeatherHeavyWorkloadLease" in text, name
        assert "Exit-WeatherHeavyWorkloadLease" in text, name


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
@pytest.mark.skipif(not _inside_heavy_window(), reason="lease acquisition is policy-blocked now")
def test_lease_is_exclusive_and_recovers_when_owner_exits(tmp_path: Path) -> None:
    holder = tmp_path / "holder.ps1"
    holder.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload holder\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Start-Sleep -Seconds 2\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )
    contender = tmp_path / "contender.ps1"
    contender.write_text(
        f". '{LEASE_SCRIPT}'\n"
        f"$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload contender\n"
        "if ($null -eq $lease) { Write-Output 'BLOCKED'; exit 3 }\n"
        "Write-Output 'ACQUIRED'\n"
        "Exit-WeatherHeavyWorkloadLease -Lease $lease\n",
        encoding="utf-8",
    )

    owner = subprocess.Popen(
        ["powershell", "-NoProfile", "-File", str(holder)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert owner.stdout is not None
    assert owner.stdout.readline().strip() == "ACQUIRED"
    blocked = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 3
    assert blocked.stdout.strip() == "BLOCKED"
    assert owner.wait(timeout=10) == 0

    recovered = subprocess.run(
        ["powershell", "-NoProfile", "-File", str(contender)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert recovered.returncode == 0
    assert recovered.stdout.strip() == "ACQUIRED"


def test_forced_tiering_cannot_bypass_protected_host_window() -> None:
    for name in ("clob_tiering_run.ps1", "clob_raw_tape_tiering_run.ps1"):
        text = (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "$localMinute -ge (9 * 60) -or $localMinute -lt 30" in text
        assert "-Forced cannot bypass host policy" in text


def test_shared_lease_owns_the_heavy_window_and_exact_dated_exceptions() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert "$localMinute -ge 30 -and $localMinute -lt (9 * 60)" in text
    assert "$localMinute -ge (9 * 60 + 30)" in text
    assert "$localMinute -lt (11 * 60 + 55)" in text
    assert "AllowStageAWindow" in text
    assert "only the explicit Stage-A lane" in text
    assert "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" in text
    assert "owner_approved_merge_20260823" in text
    assert 'Workload -cne "quiet_window_merge"' in text
    assert 'ToString("yyyy-MM-dd") -cne "2026-08-23"' in text


def test_portable_profile_is_exactly_host_bound_and_live_workload_scoped() -> None:
    text = LEASE_SCRIPT.read_text(encoding="utf-8-sig")

    assert '"capture_colocated_v1"' in text
    assert '"portable_execution_v1"' in text
    assert '"portable_execution"' in text
    assert "Get-WeatherExecutionHostId" in text
    assert "Get-WeatherExecutionHostAssignment" in text
    assert "active_portable_execution_principal_id" in text
    assert "pre_tool_use_host_load.py" not in text
    assert "portable execution-host admission is forbidden" in text
    assert "capture-colocated International live admission is restricted" in text
    assert '"international_live_execution_host_v2`0$machineGuid"' in text
    assert "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography" in text
    assert '-Name "MachineGuid"' in text
    assert "$env:COMPUTERNAME" not in text
    assert "$env:USERNAME" not in text
    assert "InternationalLive-(?:stage0|stage1_cancel_all|stage1_dead_man)-" in text
    assert "portable execution-host identity does not match the sealed host binding" in text
    assert "portable execution-host admission cannot combine with Stage-A" in text
    assert '"Global\\WeatherProjectHeavyWorkloadV1"' in text
    assert 'schema_version = "weather_heavy_workload_lease_v2"' in text
    assert "[Threading.Mutex]::new" in text
    assert "AbandonedMutexException" in text
    assert "[Environment]::MachineName" in text


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows lease",
)
def test_portable_profile_admits_exact_bound_live_workload_at_any_time(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    env["WEATHER_LEASE_ROOT"] = str(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$hostId = Get-WeatherExecutionHostId
$principalId = Get-WeatherExecutionPrincipalId
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot | Out-Null
@{
    schema_version = 'international_live_execution_host_assignment_v0.1'
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    active_portable_execution_host_id = $hostId
    active_portable_execution_principal_id = $principalId
    reassignment_requires_new_production_tip = $true
} | ConvertTo-Json | Set-Content -LiteralPath (
    Join-Path $configRoot 'international_live_execution_host.json'
) -Encoding UTF8
$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $env:WEATHER_LEASE_ROOT `
    -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
    -ExecutionHostProfile 'portable_execution_v1' `
    -ExpectedExecutionHostId $hostId
if ($null -eq $lease) { throw 'portable lease was unexpectedly busy' }
try {
    $owner = Get-Content -LiteralPath $lease.Path -Raw | ConvertFrom-Json
    $wrongHostRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId ('0' * 64)
    }
    catch { $wrongHostRejected = $true }
    $wrongWorkloadRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'portable-test' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $wrongWorkloadRejected = $true }
    $stageARejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -AllowStageAWindow `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $stageARejected = $true }
    $ownerExceptionRejected = $false
    try {
        Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'InternationalLive-stage0-portable-test-0123456789ab' `
            -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823' `
            -ExecutionHostProfile 'portable_execution_v1' `
            -ExpectedExecutionHostId $hostId
    }
    catch { $ownerExceptionRejected = $true }
    [pscustomobject]@{
        acquired = $true
        policy_window = [string]$owner.policy_window
        profile = [string]$owner.execution_host_profile
        identity_matches = [string]$owner.execution_host_id -ceq $hostId
        wrong_host_rejected = $wrongHostRejected
        wrong_workload_rejected = $wrongWorkloadRejected
        stage_a_rejected = $stageARejected
        owner_exception_rejected = $ownerExceptionRejected
    } | ConvertTo-Json -Compress
}
finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"acquired":true,"policy_window":"portable_execution",'
        '"profile":"portable_execution_v1","identity_matches":true,'
        '"wrong_host_rejected":true,"wrong_workload_rejected":true,'
        '"stage_a_rejected":true,"owner_exception_rejected":true}'
    )


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
def test_policy_rejects_daytime_work_but_admits_explicit_stage_a() -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$denied = Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-08-14T10:00:00'
$stageA = Get-WeatherHeavyWorkloadPolicyWindow -Now '2026-08-14T10:00:00' `
    -AllowStageAWindow
[pscustomobject]@{ denied = $null -eq $denied; stage_a = $stageA } |
    ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"denied":true,"stage_a":"stage_a"}'


@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows lease")
def test_policy_accepts_only_the_exact_dated_owner_merge_exception() -> None:
    env = os.environ.copy()
    env["WEATHER_LEASE_SCRIPT"] = str(LEASE_SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$accepted = Get-WeatherHeavyWorkloadPolicyWindow `
    -Now '2026-08-23T19:00:00' `
    -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823'
$expired = $false
try {
    Get-WeatherHeavyWorkloadPolicyWindow `
        -Now '2026-08-24T00:31:00' `
        -OwnerApprovedException 'OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823'
}
catch { $expired = $true }
[pscustomobject]@{ accepted = $accepted; expired = $expired } |
    ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        '{"accepted":"owner_approved_merge_20260823","expired":true}'
    )
