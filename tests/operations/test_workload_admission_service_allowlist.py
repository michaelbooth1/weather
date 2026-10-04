"""Stale ACTIVE-marker recovery around allowlisted read-only S4U services.

An S4U scheduled task's Python processes have command lines a non-elevated
session cannot read. The residual scan must exclude only processes proved to be
the running instance of an allowlisted task, and keep refusing every other
unreadable Python process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
POWERSHELL = (
    "powershell",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
)
WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell",
)

# Shared PowerShell fixture: a verified wallet-reader task instance (engine PID
# 9001 plus its venv-redirector child 9002) and builders for variants.
FIXTURE = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$taskStart = [datetime]::new(2026, 10, 2, 20, 13, 53, [DateTimeKind]::Utc)
function New-ReaderObservation {
    param(
        [string]$Arguments = '-m weather.market.wallet_reader serve --bind 10.0.0.1 --allow 10.0.0.2 --port 8765',
        [string]$Execute = 'C:\repo\venv\Scripts\python.exe',
        [string]$LogonType = 'S4U',
        [string]$State = 'Running',
        [int[]]$EnginePids = @(9001),
        [string]$TaskName = 'WeatherWalletReader',
        [string]$Service = 'wallet_reader'
    )
    [pscustomobject]@{
        Service = $Service
        TaskPath = '\'
        TaskName = $TaskName
        State = $State
        LogonType = $LogonType
        Actions = @([pscustomobject]@{ Execute = $Execute; Arguments = $Arguments })
        LastRunTimeUtc = $taskStart
        EnginePids = $EnginePids
    }
}
function New-Row {
    param([int]$ProcessId, [int]$ParentProcessId, [double]$OffsetSeconds,
        [string]$Name = 'python.exe', [string]$CommandLine = $null)
    [pscustomobject]@{
        ProcessId = $ProcessId
        ParentProcessId = $ParentProcessId
        Name = $Name
        CommandLine = $CommandLine
        CreationDate = $taskStart.AddSeconds($OffsetSeconds).ToLocalTime()
    }
}
$readerRows = @(
    (New-Row -ProcessId 9001 -ParentProcessId 800 -OffsetSeconds 0.16),
    (New-Row -ProcessId 9002 -ParentProcessId 9001 -OffsetSeconds 0.30)
)
$unknownRow = New-Row -ProcessId 9100 -ParentProcessId 4 -OffsetSeconds 5
function Get-Detected {
    param([object[]]$Rows, [object[]]$Observations)
    if ($PSBoundParameters.ContainsKey('Observations')) {
        $found = @(Get-WeatherActiveWorkstationHeavyProcess -ProcessSnapshot $Rows `
            -TaskObservation $Observations)
    }
    else {
        $found = @(Get-WeatherActiveWorkstationHeavyProcess -ProcessSnapshot $Rows)
    }
    (@($found | ForEach-Object { [int]$_.ProcessId } | Sort-Object)) -join ','
}
"""


def _run(script: str, env_extra: dict[str, str] | None = None) -> dict:
    env = {**os.environ, "WEATHER_LEASE_SCRIPT": str(LEASE_SCRIPT), **(env_extra or {})}
    result = subprocess.run(
        [*POWERSHELL, "-Command", FIXTURE + script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@WINDOWS_POWERSHELL
def test_allowlist_is_explicit_and_names_only_the_wallet_reader() -> None:
    result = _run(
        r"""
$definitions = @(Get-WeatherKnownReadOnlyServiceDefinition)
[pscustomobject]@{
    services = @($definitions | ForEach-Object { $_.Service })
    tasks = @($definitions | ForEach-Object { $_.TaskPath + $_.TaskName })
    logon = @($definitions | ForEach-Object { $_.LogonType })
} | ConvertTo-Json -Compress
"""
    )
    assert result == {
        "services": ["wallet_reader"],
        "tasks": ["\\WeatherWalletReader"],
        "logon": ["S4U"],
    }


@WINDOWS_POWERSHELL
def test_unreadable_processes_are_excluded_only_when_proved_allowlisted() -> None:
    result = _run(
        r"""
$reader = New-ReaderObservation
$grandchild = New-Row -ProcessId 9003 -ParentProcessId 9002 -OffsetSeconds 0.5
$nonPythonChild = New-Row -ProcessId 9004 -ParentProcessId 9001 -OffsetSeconds 0.5 -Name 'pytest.exe'
$readableChild = New-Row -ProcessId 9005 -ParentProcessId 9001 -OffsetSeconds 0.5 `
    -CommandLine 'python.exe -m pytest -q'
$staleChild = New-Row -ProcessId 9006 -ParentProcessId 9001 -OffsetSeconds -60
$log = [System.Collections.Generic.List[object]]::new()
$logged = @(Get-WeatherActiveWorkstationHeavyProcess -ProcessSnapshot ($readerRows + $unknownRow) `
    -TaskObservation @($reader) -DecisionLog $log)
[pscustomobject]@{
    reader_only = Get-Detected -Rows $readerRows -Observations @($reader)
    reader_and_unknown = Get-Detected -Rows ($readerRows + $unknownRow) -Observations @($reader)
    snapshot_without_observation = Get-Detected -Rows $readerRows
    no_running_instance = Get-Detected -Rows $readerRows -Observations @()
    tampered_arguments = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -Arguments '-m pytest -q')
    serve_prefix_only = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -Arguments '-m weather.market.wallet_reader served')
    relative_executable = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -Execute 'python.exe')
    wrong_image = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -Execute 'C:\repo\venv\Scripts\pytest.exe')
    wrong_logon = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -LogonType 'Password')
    not_running = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -State 'Ready')
    two_engines = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -EnginePids @(9001, 9002))
    unlisted_task = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -TaskName 'WeatherSomethingElse')
    unlisted_service = Get-Detected -Rows $readerRows -Observations @(
        New-ReaderObservation -Service 'pytest_runner')
    reused_engine_pid = Get-Detected -Rows @(
        (New-Row -ProcessId 9001 -ParentProcessId 800 -OffsetSeconds 3600),
        $readerRows[1]
    ) -Observations @($reader)
    grandchild = Get-Detected -Rows ($readerRows + $grandchild) -Observations @($reader)
    non_python_child = Get-Detected -Rows ($readerRows + $nonPythonChild) -Observations @($reader)
    readable_heavy_child = Get-Detected -Rows ($readerRows + $readableChild) -Observations @($reader)
    child_older_than_engine = Get-Detected -Rows ($readerRows + $staleChild) -Observations @($reader)
    logged_decisions = @($log | ForEach-Object { $_.decision })
    logged_residual = @($logged | ForEach-Object { $_.ProcessId })
} | ConvertTo-Json -Compress
"""
    )
    assert result == {
        "reader_only": "",
        "reader_and_unknown": "9100",
        "snapshot_without_observation": "9001,9002",
        "no_running_instance": "9001,9002",
        "tampered_arguments": "9001,9002",
        "serve_prefix_only": "9001,9002",
        "relative_executable": "9001,9002",
        "wrong_image": "9001,9002",
        "wrong_logon": "9001,9002",
        "not_running": "9001,9002",
        "two_engines": "9001,9002",
        "unlisted_task": "9001,9002",
        "unlisted_service": "9001,9002",
        "reused_engine_pid": "9001,9002",
        "grandchild": "9003",
        "non_python_child": "9004",
        "readable_heavy_child": "9005",
        "child_older_than_engine": "9006",
        "logged_decisions": [
            "service_verified",
            "excluded_allowlisted_service",
            "excluded_allowlisted_service",
            "residual_unreadable_python",
        ],
        "logged_residual": [9100],
    }


@WINDOWS_POWERSHELL
def test_unobservable_scheduler_excludes_nothing_and_is_logged() -> None:
    result = _run(
        r"""
function Get-WeatherProcessSnapshot { $readerRows }
function Get-WeatherScheduledTaskObservation { throw 'access denied' }
$log = [System.Collections.Generic.List[object]]::new()
$found = @(Get-WeatherActiveWorkstationHeavyProcess -DecisionLog $log)
[pscustomobject]@{
    residual = @($found | ForEach-Object { $_.ProcessId })
    first = $log[0].decision
    reason = $log[0].reason
} | ConvertTo-Json -Compress
"""
    )
    assert result["residual"] == [9001, 9002]
    assert result["first"] == "service_unverified"
    assert "access denied" in result["reason"]


def _outer_lease_owns_host_mutex() -> bool:
    if os.name != "nt":
        return False
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") == "1":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenMutexW(
        0x00100000, False, "Global\\WeatherProjectHeavyWorkloadV1"
    )
    if not handle:
        return False
    try:
        result = kernel32.WaitForSingleObject(handle, 0)
        if result in (0x00000000, 0x00000080):
            kernel32.ReleaseMutex(handle)
            return False
        return True
    finally:
        kernel32.CloseHandle(handle)


# Admission-level cases take the real host-global mutex, so (like the other
# admission tests) they skip inside an outer workstation or bounded-suite lease.
OUTER_LEASE = _outer_lease_owns_host_mutex()

ADMISSION = r"""
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    $env:WEATHER_TEST_POISON_PATH
}
$configRoot = Join-Path $env:WEATHER_LEASE_ROOT 'config'
New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
[IO.File]::WriteAllText(
    (Join-Path $configRoot 'international_live_execution_host.json'),
    ([ordered]@{
        active_portable_execution_host_id = Get-WeatherExecutionHostId
        active_portable_execution_principal_id = Get-WeatherExecutionPrincipalId
        assignment_status = 'ASSIGNED'
        dedicated_capture_execution_host_id = ('f' * 64)
        reassignment_requires_new_production_tip = $true
        schema_version = 'international_live_execution_host_assignment_v0.1'
    } | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false)
)
function Get-WeatherScheduledTaskObservation { New-ReaderObservation }
function Write-StaleMarker {
    [IO.File]::WriteAllText(
        $env:WEATHER_TEST_POISON_PATH,
        ([ordered]@{
            schema_version = 'weather_heavy_workload_state_v1'
            state = 'ACTIVE'
            workload = 'WorkstationOffline-pytest-stale-owner'
            execution_host_profile = 'workstation_offline_v1'
            pid = 2147483647
            owner_process_start_utc = '2000-01-01T00:00:00.0000000Z'
            boot_session_id = Get-WeatherBootSessionId
            state_changed_at_utc = '2000-01-01T00:00:00.0000000Z'
        } | ConvertTo-Json -Compress),
        [Text.UTF8Encoding]::new($false)
    )
}
function Invoke-Admission {
    $message = ''
    try {
        $lease = Enter-WeatherHeavyWorkloadLease `
            -RepoRoot $env:WEATHER_LEASE_ROOT `
            -Workload 'WorkstationOffline-pytest-recovery-probe' `
            -ExecutionHostProfile 'workstation_offline_v1' 3>$null
        if ($null -ne $lease) {
            Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
            Exit-WeatherHeavyWorkloadLease -Lease $lease
            $message = 'ADMITTED'
        }
        else { $message = 'HOST_MUTEX_BUSY' }
    }
    catch { $message = $_.Exception.Message }
    $message
}
function Read-RecoveryLog {
    $path = Join-Path $env:WEATHER_LEASE_ROOT 'data\logs\heavy_workload_recovery.jsonl'
    @(Get-Content -LiteralPath $path | ForEach-Object { $_ | ConvertFrom-Json })[-1]
}
"""


def _run_admission(tmp_path: Path, script: str) -> dict:
    return _run(
        ADMISSION + script,
        {
            "WEATHER_LEASE_ROOT": str(tmp_path),
            "WEATHER_TEST_POISON_PATH": str(tmp_path / "host-global.poison"),
        },
    )


@WINDOWS_POWERSHELL
@pytest.mark.skipif(OUTER_LEASE, reason="outer workstation lease owns mutex")
def test_stale_marker_is_recovered_when_only_the_reader_remains(tmp_path: Path) -> None:
    result = _run_admission(
        tmp_path,
        r"""
function Get-WeatherProcessSnapshot { $readerRows }
Write-StaleMarker
$message = Invoke-Admission
$entry = Read-RecoveryLog
[pscustomobject]@{
    message = $message
    marker_present = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
    outcome = $entry.outcome
    marker_pid = $entry.marker_pid
    decisions = @($entry.decisions | ForEach-Object { $_.decision })
    excluded = @($entry.decisions | Where-Object {
        $_.decision -ceq 'excluded_allowlisted_service' } | ForEach-Object { $_.pid })
    retry = Invoke-Admission
} | ConvertTo-Json -Compress
""",
    )
    assert "stale ACTIVE workload marker was recovered" in result["message"]
    assert result["marker_present"] is False
    assert result["outcome"] == "recovered"
    assert result["marker_pid"] == 2147483647
    assert result["decisions"] == [
        "service_verified",
        "excluded_allowlisted_service",
        "excluded_allowlisted_service",
    ]
    assert result["excluded"] == [9001, 9002]
    assert result["retry"] == "ADMITTED"


@WINDOWS_POWERSHELL
@pytest.mark.skipif(OUTER_LEASE, reason="outer workstation lease owns mutex")
def test_unknown_unreadable_python_still_refuses_recovery(tmp_path: Path) -> None:
    result = _run_admission(
        tmp_path,
        r"""
function Get-WeatherProcessSnapshot { $readerRows + $unknownRow }
Write-StaleMarker
$message = Invoke-Admission
$entry = Read-RecoveryLog
$preserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)
[pscustomobject]@{
    message = $message
    marker_present = $preserved
    outcome = $entry.outcome
    residual = @($entry.decisions | Where-Object {
        $_.decision -like 'residual_*' } | ForEach-Object { $_.pid })
} | ConvertTo-Json -Compress
""",
    )
    assert "residual heavy process(es): python.exe pid 9100" in result["message"]
    assert result["marker_present"] is True
    assert result["outcome"] == "refused_residual_processes"
    assert result["residual"] == [9100]


@WINDOWS_POWERSHELL
@pytest.mark.skipif(OUTER_LEASE, reason="outer workstation lease owns mutex")
def test_live_owner_still_refuses_recovery_with_the_reader_running(
    tmp_path: Path,
) -> None:
    result = _run_admission(
        tmp_path,
        r"""
function Get-WeatherProcessSnapshot { $readerRows }
New-WeatherHeavyWorkloadPoisonMarker `
    -Path $env:WEATHER_TEST_POISON_PATH `
    -Workload 'WorkstationOffline-pytest-owner-alive' `
    -ExecutionHostProfile 'workstation_offline_v1' `
    -State 'ACTIVE'
$message = Invoke-Admission
$entry = Read-RecoveryLog
$preserved = Test-Path -LiteralPath $env:WEATHER_TEST_POISON_PATH
[IO.File]::Delete($env:WEATHER_TEST_POISON_PATH)
[pscustomobject]@{
    message = $message
    marker_present = $preserved
    outcome = $entry.outcome
    marker_pid = $entry.marker_pid
    own_pid = $PID
} | ConvertTo-Json -Compress
""",
    )
    assert "owner process still exists" in result["message"]
    assert result["marker_present"] is True
    assert result["outcome"] == "refused_owner_alive"
    assert result["marker_pid"] == result["own_pid"]
