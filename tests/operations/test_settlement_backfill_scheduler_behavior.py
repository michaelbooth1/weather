from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
REGISTRAR = OPS / "register_settlement_backfill_attempt.ps1"
RETRY = OPS / "settlement_backfill_retry_one.ps1"
WATCHDOG = OPS / "health_watchdog.ps1"
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell.exe") is None,
    reason="requires Windows PowerShell",
)
TARGET_DATE = "2026-08-30"
ATTEMPT_ID = "testcase"
PRIMARY_TASK = "WeatherSettlementBackfill20260830_testcase"


def _run_powershell(
    script: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env or {})
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _prepare_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    shutil.copyfile(
        OPS / "training_window_contract.ps1",
        ops / "training_window_contract.ps1",
    )
    shutil.copyfile(RETRY, ops / "settlement_backfill_retry_one.ps1")
    (ops / "settlement_backfill_one.ps1").write_text(
        r"""
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$TargetDate,
    [switch]$Refetch,
    [Parameter(Mandatory = $true)][string]$AttemptId,
    [Parameter(Mandatory = $true)][string]$PrimaryTaskName,
    [Parameter(Mandatory = $true)][string]$RepoRoot
)
$counterPath = Join-Path $RepoRoot 'retry-call-count.txt'
$count = 0
if (Test-Path -LiteralPath $counterPath -PathType Leaf) {
    $count = [int](Get-Content -LiteralPath $counterPath -Raw)
}
[IO.File]::WriteAllText($counterPath, [string]($count + 1))
$mode = [string]$env:WEATHER_FAKE_BACKFILL_MODE
$state = if ($mode -eq 'failure') { 'PARTIAL' } else { 'SETTLED' }
$settled = if ($mode -eq 'invalid_settled') { 1 } elseif ($mode -eq 'failure') { 1 } else { 2 }
$unsettled = @()
if ($settled -ne 2) { $unsettled = @('beta') }
$receipt = [ordered]@{
    schema_version = 'settlement_backfill_receipt_v0.2'
    target_date = $TargetDate
    attempt_id = $AttemptId
    primary_task_name = $PrimaryTaskName
    attempt_started_at_local = (Get-Date).ToString('o')
    state = $state
    refetch = [bool]$Refetch
    expected_market_count = 2
    expected_market_ids = @('alpha', 'beta')
    markets_total = 2
    markets_settled = $settled
    markets_unsettled = $unsettled
    missing_ledger_markets = @()
    at_local = (Get-Date).ToString('o')
}
$alerts = Join-Path $RepoRoot 'data\alerts'
New-Item -ItemType Directory -Path $alerts -Force | Out-Null
$receiptPath = Join-Path $alerts "settlement_backfill_${TargetDate}_$AttemptId.json"
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8
if ($mode -eq 'failure') { exit 1 }
exit 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


@WINDOWS_POWERSHELL_REQUIRED
def test_settlement_registrar_mocked_pair_lifecycle(tmp_path: Path) -> None:
    repo = _prepare_fake_repo(tmp_path)
    harness = r"""
$ErrorActionPreference = 'Stop'
$global:mockTasks = @{}
$global:registerCalls = 0
$global:disableCalls = New-Object System.Collections.Generic.List[string]
$global:scenario = 'success'

function Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    if ($PSBoundParameters.ContainsKey('TaskName')) {
        if ($global:mockTasks.ContainsKey($TaskName)) {
            return $global:mockTasks[$TaskName]
        }
        return $null
    }
    return @($global:mockTasks.Values)
}
function Get-ScheduledTaskInfo {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process { return $InputObject.Info }
}
function New-ScheduledTaskPrincipal {
    param($UserId, $LogonType, $RunLevel)
    return [pscustomobject]@{
        UserId = [string]$UserId
        LogonType = [string]$LogonType
        RunLevel = [string]$RunLevel
    }
}
function New-ScheduledTaskSettingsSet {
    param(
        $ExecutionTimeLimit,
        $MultipleInstances,
        [switch]$WakeToRun,
        [switch]$AllowStartIfOnBatteries,
        [switch]$DontStopIfGoingOnBatteries
    )
    return [pscustomobject]@{
        StartWhenAvailable = $false
        WakeToRun = [bool]$WakeToRun
        ExecutionTimeLimit = 'PT8H30M'
        RestartCount = 0
        MultipleInstances = [string]$MultipleInstances
    }
}
function New-ScheduledTaskAction {
    param($Execute, $Argument, $WorkingDirectory)
    return [pscustomobject]@{
        Execute = [string]$Execute
        Arguments = [string]$Argument
        WorkingDirectory = [string]$WorkingDirectory
    }
}
function New-ScheduledTaskTrigger {
    param([switch]$Once, [datetime]$At)
    return [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Enabled = $true
        StartBoundary = $At
        Repetition = [pscustomobject]@{ Interval = ''; Duration = '' }
    }
}
function Register-ScheduledTask {
    param($TaskName, $Action, $Trigger, $Settings, $Principal, $Description)
    $global:registerCalls += 1
    if ($global:scenario -eq 'register_failure' -and $TaskName -like '*Retry*') {
        throw 'mock retry registration failure'
    }
    $task = [pscustomobject]@{
        TaskName = [string]$TaskName
        TaskPath = '\'
        State = 'Ready'
        Principal = $Principal
        Actions = @($Action)
        Triggers = @($Trigger)
        Settings = $Settings
        Info = [pscustomobject]@{ NextRunTime = [datetime]$Trigger.StartBoundary }
    }
    if ($global:scenario -eq 'readback_mismatch' -and $TaskName -like '*Retry*') {
        $task.Actions[0].Arguments += ' -Injected'
    }
    $global:mockTasks[$TaskName] = $task
    return $task
}
function Disable-ScheduledTask {
    param($TaskName, $ErrorAction)
    if (-not $global:mockTasks.ContainsKey($TaskName)) {
        throw "mock task absent: $TaskName"
    }
    $global:mockTasks[$TaskName].State = 'Disabled'
    $global:disableCalls.Add([string]$TaskName)
    return $global:mockTasks[$TaskName]
}
function Reset-Mocks([string]$Scenario) {
    $global:mockTasks = @{}
    $global:registerCalls = 0
    $global:disableCalls = New-Object System.Collections.Generic.List[string]
    $global:scenario = $Scenario
}
function Invoke-Registrar(
    [string]$AttemptId,
    [bool]$ExpectFailure,
    [string]$TargetDate = '2026-08-30'
) {
    $primaryAt = (Get-Date).Date.AddDays(2).AddMinutes(30)
    $retryAt = $primaryAt.AddMinutes(30)
    $failed = $false
    try {
        & $env:WEATHER_TEST_REGISTRAR `
            -TargetDate $TargetDate `
            -AttemptId $AttemptId `
            -PrimaryAtLocal $primaryAt.ToString('yyyy-MM-ddTHH:mm:ss') `
            -RetryAtLocal $retryAt.ToString('yyyy-MM-ddTHH:mm:ss') `
            -RepoRoot $env:WEATHER_TEST_REPO | Out-Null
    }
    catch { $failed = $true }
    if ($failed -ne $ExpectFailure) {
        throw "unexpected registrar failure state for ${AttemptId}: $failed"
    }
}

Reset-Mocks 'success'
Invoke-Registrar 'success' $false
if ($global:registerCalls -ne 2 -or $global:mockTasks.Count -ne 2) {
    throw 'successful registrar did not create exactly one pair'
}
foreach ($task in $global:mockTasks.Values) {
    if ($task.State -ne 'Ready' -or
        $task.Principal.LogonType -ne 'S4U' -or
        $task.Principal.RunLevel -ne 'Limited' -or
        $task.Settings.StartWhenAvailable -or
        -not $task.Settings.WakeToRun -or
        $task.Settings.RestartCount -ne 0 -or
        $task.Settings.MultipleInstances -ne 'IgnoreNew') {
        throw 'successful registrar emitted an inexact task binding'
    }
}

Reset-Mocks 'register_failure'
Invoke-Registrar 'registrationfail' $true
$primary = $global:mockTasks['WeatherSettlementBackfill20260830_registrationfail']
if ($null -eq $primary -or $primary.State -ne 'Disabled' -or $global:disableCalls.Count -ne 1) {
    throw 'failed second-task registration did not prove the primary Disabled'
}

Reset-Mocks 'readback_mismatch'
Invoke-Registrar 'readbackfail' $true
if ($global:mockTasks.Count -ne 2 -or
    @($global:mockTasks.Values | Where-Object { $_.State -ne 'Disabled' }).Count -ne 0 -or
    $global:disableCalls.Count -ne 2) {
    throw 'readback mismatch did not prove both tasks Disabled'
}

Reset-Mocks 'success'
$global:mockTasks['WeatherSettlementBackfill20260830_queued'] = [pscustomobject]@{
    TaskName = 'WeatherSettlementBackfill20260830_queued'
    State = 'Queued'
    Info = [pscustomobject]@{ NextRunTime = [datetime]::MinValue }
}
Invoke-Registrar 'blocked' $true
if ($global:registerCalls -ne 0) { throw 'ambiguous active pair was not refused' }

Reset-Mocks 'success'
$global:mockTasks['WeatherSettlementBackfill20260830_disabledold'] = [pscustomobject]@{
    TaskName = 'WeatherSettlementBackfill20260830_disabledold'
    State = 'Disabled'
    Info = [pscustomobject]@{ NextRunTime = (Get-Date).AddDays(1) }
}
$global:mockTasks['WeatherSettlementBackfillRetry20260830_readyold'] = [pscustomobject]@{
    TaskName = 'WeatherSettlementBackfillRetry20260830_readyold'
    State = 'Ready'
    Info = [pscustomobject]@{ NextRunTime = (Get-Date).AddDays(-1) }
}
Invoke-Registrar 'afterhistory' $false
if ($global:registerCalls -ne 2) { throw 'inert history froze a later reviewed pair' }

Reset-Mocks 'success'
Invoke-Registrar 'invaliddate' $true '2026-02-31'
if ($global:registerCalls -ne 0) { throw 'invalid calendar date reached Scheduler mutation' }

Reset-Mocks 'success'
$lockDir = Join-Path $env:WEATHER_TEST_REPO 'data\logs'
New-Item -ItemType Directory -Path $lockDir -Force | Out-Null
$lockPath = Join-Path $lockDir 'settlement_backfill_registration_20260830.lock'
$held = [IO.File]::Open(
    $lockPath,
    [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
try { Invoke-Registrar 'concurrent' $true }
finally { $held.Dispose() }
if ($global:registerCalls -ne 0) { throw 'concurrent registrar passed the target-date mutex' }

'PASS'
"""
    result = _run_powershell(
        harness,
        cwd=repo,
        extra_env={
            "WEATHER_TEST_REGISTRAR": str(REGISTRAR),
            "WEATHER_TEST_REPO": str(repo),
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def _primary_receipt(*, state: str, started_at: datetime) -> dict[str, object]:
    return {
        "schema_version": "settlement_backfill_receipt_v0.2",
        "target_date": TARGET_DATE,
        "attempt_id": ATTEMPT_ID,
        "primary_task_name": PRIMARY_TASK,
        "attempt_started_at_local": started_at.astimezone().isoformat(),
        "state": state,
        "refetch": True,
        "expected_market_count": 2,
        "expected_market_ids": ["alpha", "beta"],
        "markets_total": 2,
        "markets_settled": 2 if state == "SETTLED" else 1,
        "markets_unsettled": [] if state == "SETTLED" else ["beta"],
        "missing_ledger_markets": [],
        "at_local": datetime.now().astimezone().isoformat(),
    }


def _run_retry(
    repo: Path,
    *,
    task_state: str,
    last_run: datetime,
    next_run: datetime,
    fake_mode: str,
) -> subprocess.CompletedProcess[str]:
    harness = r"""
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $env:WEATHER_TEST_REPO).Path
. (Join-Path $root 'scripts\ops\training_window_contract.ps1')
$backfill = Join-Path $root 'scripts\ops\settlement_backfill_one.ps1'
$tokens = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $backfill,
    '-TargetDate', '2026-08-30',
    '-Refetch',
    '-AttemptId', 'testcase',
    '-PrimaryTaskName', 'WeatherSettlementBackfill20260830_testcase',
    '-RepoRoot', $root
)
$arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
$global:mockTask = [pscustomobject]@{
    TaskName = 'WeatherSettlementBackfill20260830_testcase'
    State = [string]$env:WEATHER_TEST_TASK_STATE
    Actions = @([pscustomobject]@{
        Execute = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        Arguments = $arguments
        WorkingDirectory = $root
    })
}
$global:mockInfo = [pscustomobject]@{
    LastRunTime = [datetime]$env:WEATHER_TEST_LAST_RUN
    NextRunTime = [datetime]$env:WEATHER_TEST_NEXT_RUN
}
function Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    if ($TaskName -eq $global:mockTask.TaskName) { return $global:mockTask }
    return $null
}
function Get-ScheduledTaskInfo {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process { return $global:mockInfo }
}
& $env:WEATHER_TEST_RETRY `
    -TargetDate '2026-08-30' `
    -PrimaryTaskName 'WeatherSettlementBackfill20260830_testcase' `
    -AttemptId 'testcase' `
    -RepoRoot $root
exit $LASTEXITCODE
"""
    return _run_powershell(
        harness,
        cwd=repo,
        extra_env={
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_RETRY": str(RETRY),
            "WEATHER_TEST_TASK_STATE": task_state,
            "WEATHER_TEST_LAST_RUN": last_run.astimezone().isoformat(),
            "WEATHER_TEST_NEXT_RUN": next_run.astimezone().isoformat(),
            "WEATHER_FAKE_BACKFILL_MODE": fake_mode,
        },
    )


def _retry_call_count(repo: Path) -> int:
    path = repo / "retry-call-count.txt"
    return int(path.read_text(encoding="utf-8")) if path.exists() else 0


def _retry_state(repo: Path) -> str:
    path = (
        repo
        / "data"
        / "alerts"
        / "settlement_backfill_retry_2026-08-30_testcase.json"
    )
    return str(json.loads(path.read_text(encoding="utf-8-sig"))["state"])


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize(
    ("mode", "expected_exit", "expected_state"),
    [
        ("success", 0, "SETTLED"),
        ("failure", 1, "RETRY_FAILED"),
        ("invalid_settled", 1, "RETRY_FAILED"),
    ],
)
def test_settlement_retry_invokes_fake_wrapper_exactly_once(
    tmp_path: Path,
    mode: str,
    expected_exit: int,
    expected_state: str,
) -> None:
    repo = _prepare_fake_repo(tmp_path)
    never = datetime(1999, 11, 30).astimezone()
    result = _run_retry(
        repo,
        task_state="Ready",
        last_run=never,
        next_run=never,
        fake_mode=mode,
    )

    assert result.returncode == expected_exit, result.stderr
    assert _retry_call_count(repo) == 1
    assert _retry_state(repo) == expected_state


@WINDOWS_POWERSHELL_REQUIRED
def test_settlement_retry_skips_fresh_bound_all_market_receipt(tmp_path: Path) -> None:
    repo = _prepare_fake_repo(tmp_path)
    now = datetime.now().astimezone()
    last_run = now - timedelta(minutes=2)
    receipt_path = (
        repo / "data" / "alerts" / "settlement_backfill_2026-08-30_testcase.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(_primary_receipt(state="SETTLED", started_at=now - timedelta(minutes=1))),
        encoding="utf-8",
    )
    result = _run_retry(
        repo,
        task_state="Ready",
        last_run=last_run,
        next_run=last_run,
        fake_mode="success",
    )

    assert result.returncode == 0, result.stderr
    assert _retry_call_count(repo) == 0
    assert _retry_state(repo) == "SKIPPED_ALREADY_SETTLED"


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize(
    ("task_state", "last_run_delta", "next_run_delta", "receipt_age", "expected_exit", "expected_state"),
    [
        ("Running", 2, -2, None, 3, "REFUSED_PRIMARY_RUNNING"),
        ("Ready", 1, -1, 10, 2, "REFUSED"),
        ("Ready", None, 10, None, 2, "REFUSED"),
    ],
)
def test_settlement_retry_refuses_running_stale_or_still_due_primary(
    tmp_path: Path,
    task_state: str,
    last_run_delta: int | None,
    next_run_delta: int,
    receipt_age: int | None,
    expected_exit: int,
    expected_state: str,
) -> None:
    repo = _prepare_fake_repo(tmp_path)
    now = datetime.now().astimezone()
    never = datetime(1999, 11, 30).astimezone()
    last_run = never if last_run_delta is None else now - timedelta(minutes=last_run_delta)
    next_run = now + timedelta(minutes=next_run_delta)
    if receipt_age is not None:
        receipt_path = (
            repo / "data" / "alerts" / "settlement_backfill_2026-08-30_testcase.json"
        )
        receipt_path.parent.mkdir(parents=True)
        old = now - timedelta(minutes=receipt_age)
        receipt_path.write_text(
            json.dumps(_primary_receipt(state="PARTIAL", started_at=old)),
            encoding="utf-8",
        )
        timestamp = old.timestamp()
        os.utime(receipt_path, (timestamp, timestamp))
    result = _run_retry(
        repo,
        task_state=task_state,
        last_run=last_run,
        next_run=next_run,
        fake_mode="success",
    )

    assert result.returncode == expected_exit, result.stderr
    assert _retry_call_count(repo) == 0
    assert _retry_state(repo) == expected_state


def _write_fake_status(repo: Path, *, payload: str, exit_code: int) -> None:
    status = repo / "scripts" / "ops" / "status.ps1"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(
        f"""
[CmdletBinding()]
param([switch]$Json, [string]$RepoRoot)
[IO.File]::WriteAllText((Join-Path $RepoRoot 'status-repo-root.txt'), $RepoRoot)
Write-Output @'
{payload}
'@
exit {exit_code}
""".strip()
        + "\n",
        encoding="utf-8",
    )


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize(
    ("payload", "child_exit", "expected_exit", "expect_blind"),
    [
        ("{}", 7, 0, True),
        (
            json.dumps(
                {
                    "verdict": "ATTENTION",
                    "flags": ["SETTLEMENT HOLE (2 days)"],
                    "warns": [],
                    "streak": None,
                }
            ),
            2,
            2,
            False,
        ),
    ],
)
def test_health_watchdog_uses_bound_root_and_preserves_blind_contract(
    tmp_path: Path,
    payload: str,
    child_exit: int,
    expected_exit: int,
    expect_blind: bool,
) -> None:
    repo = tmp_path / "watchdog-repo"
    _write_fake_status(repo, payload=payload, exit_code=child_exit)
    result = _run_powershell(
        (
            "& $env:WEATHER_TEST_WATCHDOG -RepoRoot $env:WEATHER_TEST_REPO; "
            "exit $LASTEXITCODE"
        ),
        cwd=repo,
        extra_env={
            "WEATHER_TEST_WATCHDOG": str(WATCHDOG),
            "WEATHER_TEST_REPO": str(repo),
        },
    )

    assert result.returncode == expected_exit, result.stderr
    latest = json.loads(
        (repo / "data" / "alerts" / "host_health_latest.json").read_text(
            encoding="utf-8-sig"
        )
    )
    flags = [str(row["flag"]) for row in latest["alerts"]]
    observed_root = Path(
        (repo / "status-repo-root.txt").read_text(encoding="utf-8")
    )
    assert observed_root.resolve() == repo.resolve()
    assert any("BLIND" in flag for flag in flags) is expect_blind
    if expect_blind:
        assert any(f"exit {child_exit}" in flag for flag in flags)
