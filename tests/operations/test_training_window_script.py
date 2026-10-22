import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from weather.operations.producer_provenance import (
    _windows_argv,
    decode_scheduler_action_arguments,
)


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "training_window.ps1"
REGISTER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_training_window.ps1"
)
CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "training_window_contract.ps1"
)
REGISTER_NIGHTLY = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_nightly_retrain.ps1"
)
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)
BASE_BINDING_NAMES = (
    "BaseRetrainTargetDate",
    "BaseRetrainParentReleaseId",
    "BaseRetrainTrainingAsOf",
    "BaseRetrainFeatureContractId",
    "BaseRetrainCorpusManifest",
    "BaseRetrainPitForecastCorpusManifest",
    "BaseRetrainCandidateDir",
    "BaseRetrainRuntimeId",
)


def test_training_window_uses_verified_no_live_capture_admission():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Wait-CaptureStopped" in text
    assert "--capture-mode no_live_capture" in text
    assert "--capture-resource-mode\", \"no_live_capture" in text
    assert "--capture-resource-min-free-memory-bytes\", \"0" in text
    assert "if (-not (Wait-CaptureStopped (Get-StopSecondsRemaining $stopDeadline)))" in text
    assert 'Test-Path -LiteralPath $python -PathType Leaf' in text


def test_training_window_restores_before_propagating_nightly_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "} finally {" in text
    assert "Restore-Capture" in text.split("} finally {", 1)[1]
    assert '$nightlyStatus -in @(\"blocked\", \"error\", \"missing\", \"unreadable\")' in text
    # The window's code is issued from inside the final finally (default-fail).
    assert text.rstrip().endswith("$Host.SetShouldExit($childExit)\n    exit $childExit\n}")


def test_training_window_carries_exact_delegated_scheduler_contract():
    registration = REGISTER.read_text(encoding="utf-8-sig")
    window = SCRIPT.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "Get-TrainingWindowTaskActionTokens" in contract
    assert "ConvertTo-ScheduledTaskArgumentString" in contract
    assert "ConvertTo-SchedulerArgumentContract" in contract
    assert "$windowActionTokens = @(Get-TrainingWindowTaskActionTokens" in registration
    assert "-Argument $windowActionArguments" in registration
    assert "-Execute $PowerShellExecutable" in registration
    assert "$scheduledActionTokens = @(Get-TrainingWindowTaskActionTokens" in window
    assert '"--scheduler-invocation-topology", "delegated_child"' in window
    assert '"--scheduler-task-name", $WindowTaskName' in window
    assert '"--scheduler-task-executable", $SchedulerTaskExecutable' in window
    assert '"--scheduler-task-action-arguments-b64", $schedulerActionArgumentsB64' in window
    assert '"--scheduler-process-executable", $python' in window
    assert '"--producer-sla-seconds", ([string]$producerSlaSeconds)' in window
    assert '"--schedule-local-time", $baseBindings.ScheduleLocalTime' in window
    assert '"--schedule-timezone", "America/Toronto"' in window
    for name in BASE_BINDING_NAMES:
        assert f"[string]${name}" in registration
        assert f"[string]${name}" in window
        assert f'"-{name}"' in contract
    for flag in (
        "--base-retrain-target-date",
        "--base-retrain-parent-release-id",
        "--base-retrain-training-as-of",
        "--base-retrain-feature-contract-id",
        "--base-retrain-corpus-manifest",
        "--base-retrain-pit-forecast-corpus-manifest",
        "--base-retrain-candidate-dir",
        "--base-retrain-runtime-id",
    ):
        assert f'"{flag}"' in window


def test_both_nightly_registrars_fail_early_on_all_base_bindings() -> None:
    direct = REGISTER_NIGHTLY.read_text(encoding="utf-8-sig")
    window = REGISTER.read_text(encoding="utf-8-sig")

    for text in (direct, window):
        for name in BASE_BINDING_NAMES:
            marker = f"[string]${name}"
            assert marker in text
            parameter = text.index(marker)
            assert "Mandatory = $true" in text[max(0, parameter - 90) : parameter]
    assert "--capture-resource-mode offline_host" in direct
    assert '--scheduler-invocation-topology direct' in direct
    assert '--schedule-local-time `"$scheduleLocalTime`"' in direct
    assert '--run-at-local `"$RunAtLocal`"' in direct
    assert "--no-fail-on-daily-learning-blocker" in direct
    assert "Production readiness served artifact role is empty or unsafe" in direct
    assert "^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$" in direct
    assert "Resolve-TrainingWindowBaseRetrainBindings" in window
    assert "$BaseRetrainTrainingAsOf = $BaseRetrainTrainingAsOf.Trim()" in direct
    assert "BaseRetrainTrainingAsOf = $BaseRetrainTrainingAsOf.Trim()" in CONTRACT.read_text(encoding="utf-8-sig")


def test_training_registration_is_opt_in_but_keeps_restore_armed():
    registration = REGISTER.read_text(encoding="utf-8-sig")

    assert "[switch]$EnableWindow" in registration
    assert "if (-not $EnableWindow)" in registration
    assert "Disable-ScheduledTask -TaskName $WindowTaskName" in registration
    assert "Disable-ScheduledTask -TaskName $RestoreTaskName" not in registration
    assert "Enable-ScheduledTask -TaskName $WindowTaskName" in registration
    assert "re-register with -EnableWindow" in registration
    assert 'Test-Path -LiteralPath $python -PathType Leaf' in registration


def test_training_tasks_are_run_specific_and_restore_is_proved() -> None:
    direct = REGISTER_NIGHTLY.read_text(encoding="utf-8-sig")
    registration = REGISTER.read_text(encoding="utf-8-sig")
    window = SCRIPT.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "New-ScheduledTaskTrigger -Once -At $runAt" in direct
    assert "New-ScheduledTaskTrigger -Once -At $runAt" in registration
    assert "New-WeatherLocalDailyTrigger -At $RestoreAt" in registration
    window_settings = registration.split("$windowSettings =", 1)[1].split(
        "$principal =", 1
    )[0]
    restore_settings = registration.split("$restoreSettings =", 1)[1].split(
        "Register-ScheduledTask", 1
    )[0]
    assert "StartWhenAvailable" not in window_settings
    assert "StartWhenAvailable" in restore_settings
    assert "MSFT_TaskTimeTrigger" in direct
    assert "MSFT_TaskTimeTrigger" in registration
    assert "MSFT_TaskDailyTrigger" in registration
    assert '[ValidateSet("WeatherNightlyRetrainValidatePromote")]' in direct
    assert '[ValidateSet("WeatherTrainingWindow")]' in registration
    assert '[ValidateSet("WeatherTrainingWindowRestore")]' in registration
    assert "New-TimeSpan -Hours 8 -Minutes 15" in direct
    assert 'ExecutionTimeLimit -ne "PT8H15M"' in direct
    assert "DisallowStartIfOnBatteries" in direct
    assert "DisallowStartIfOnBatteries" in registration
    assert "Direct nightly registration is unsupported" in direct
    assert direct.index("Direct nightly registration is unsupported") < direct.index(
        "$action = New-ScheduledTaskAction"
    )
    assert "windowSkewSeconds -gt 120" in window
    assert "refused_outside_bound_one_shot" in window
    assert "[ValidateRange(1, 600)]" in window
    assert "[ValidateRange(10, 170)]" in window
    assert "($ChildTimeoutMinutes * 60.0) - 300.0" in window
    assert '"--run-at-local", $RunAtLocal' in window
    assert "RestoreOnly and DryRun are mutually exclusive" in window
    assert "Enable-ScheduledTask -TaskName $task -ErrorAction Stop" in window
    assert "capture_recovery_check" in window
    assert "$workers.Count -eq 3" in window
    assert '$script:restoreOutcome = "PASS"' in window
    assert "$childExit = 9002" in window
    assert "Move-Item -LiteralPath $temporary -Destination $statusPath -Force" in window
    assert "Disable-ScheduledTask -TaskName $task -ErrorAction Stop" in window
    assert "Assert-CaptureStoppedForTraining" in window
    assert window.count("Assert-CaptureStoppedForTraining") >= 3
    assert '$taskActions[0].Arguments -ceq $expectedWindowActionArguments' in window
    assert "BaseRetrainCandidateDir must not already exist" in direct
    assert "BaseRetrainCandidateDir must not already exist" in contract
    assert window.index("Enter-WeatherHeavyWorkloadLease") < window.index(
        "git -C $RepoRoot commit"
    )
    assert "Git and capture remain untouched" in window
    child_cap_seconds = 170 * 60
    producer_sla_seconds = child_cap_seconds - 300
    # The ensure-run wait, stop verbs and stop confirmation share the one stop cap.
    stop_cap_seconds = 600
    recovery_cap_seconds = 300
    deadman_seconds_after_0100 = 195 * 60
    scheduler_limit_seconds = 225 * 60
    assert producer_sla_seconds < child_cap_seconds
    assert "$stopDeadline = (Get-WindowUtcNow).AddSeconds($CaptureStopTimeoutSeconds)" in window
    assert "Wait-SupervisorEnsureRunsEnded -StopDeadline $stopDeadline" in window
    assert "Wait-CaptureStopped (Get-StopSecondsRemaining $stopDeadline)" in window
    assert "Wait-CaptureStopped $CaptureStopTimeoutSeconds" not in window
    margin_seconds = deadman_seconds_after_0100 - (
        stop_cap_seconds + child_cap_seconds + recovery_cap_seconds
    )
    # 195 - (10 + 170 + 5) min: the margin the caps allowed before the ensure-run wait.
    assert margin_seconds >= 10 * 60
    assert deadman_seconds_after_0100 < scheduler_limit_seconds


def test_training_window_refuses_hardcoded_staged_source_without_matching_receipt():
    window = SCRIPT.read_text(encoding="utf-8-sig")

    assert "production_source_2026-07-16" in window
    assert '$pitReceipt = Join-Path $pitSourceRoot "staging-receipt.json"' in window
    assert "weather.operations.point_in_time_staging_receipt verify" in window
    assert "$pitReceiptValid = ($LASTEXITCODE -eq 0)" in window
    assert "if ($pitReceiptValid -and" in window
    assert '"--point-in-time-source-receipt", $pitReceipt' in window
    assert "incomplete or unreceipted; production bootstrap refused" in window


def test_training_window_action_tokens_round_trip_with_windows_semantics():
    if os.name != "nt":
        return
    env = os.environ.copy()
    env["WEATHER_CONTRACT_SCRIPT"] = str(CONTRACT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_CONTRACT_SCRIPT
$common = @{
  RepoRoot = 'C:\Repo Root'
  ScriptPath = 'C:\Repo Root\scripts\ops\training_window.ps1'
  WindowTaskName = 'WeatherTrainingWindow'
  SchedulerTaskExecutable = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
}
$runAt = (Get-Date).Date.AddDays(1).AddHours(1).ToString('yyyy-MM-ddTHH:mm:ss')
$resolvedRunAt = Resolve-TrainingWindowRunAtLocal -RunAtLocal $runAt -RequireFuture
$tokens = @(Get-TrainingWindowTaskActionTokens @common `
  -RunAtLocal $runAt `
  -BaseRetrainTargetDate '2026-08-20' `
  -BaseRetrainParentReleaseId 'release-parent' `
  -BaseRetrainTrainingAsOf '2026-08-21T00:30:00-04:00' `
  -BaseRetrainFeatureContractId 'feature-contract' `
  -BaseRetrainCorpusManifest 'D:\corpus\manifest.json' `
  -BaseRetrainPitForecastCorpusManifest 'D:\pit\manifest.json' `
  -BaseRetrainCandidateDir 'D:\candidates\candidate-1' `
  -BaseRetrainRuntimeId 'runtime-reviewed')
$restoreTokens = @(Get-TrainingWindowTaskActionTokens @common -RestoreOnly)
[pscustomobject]@{
  arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
  contract = ConvertTo-SchedulerArgumentContract -Tokens $tokens
  tokens = $tokens
  restore_tokens = $restoreTokens
  resolved_run_at = $resolvedRunAt.ToString('HH:mm:ss')
} | ConvertTo-Json -Depth 4 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert _windows_argv(payload["arguments"]) == payload["tokens"]
    assert decode_scheduler_action_arguments(payload["contract"]) == payload["tokens"]
    assert "-BaseRetrainPitForecastCorpusManifest" in payload["tokens"]
    assert "-RunAtLocal" in payload["tokens"]
    as_of_index = payload["tokens"].index("-BaseRetrainTrainingAsOf")
    assert payload["tokens"][as_of_index + 1] == "2026-08-21T00:30:00-04:00"
    assert payload["restore_tokens"][-1] == "-RestoreOnly"
    assert "-BaseRetrainTargetDate" not in payload["restore_tokens"]
    assert payload["resolved_run_at"] == "01:00:00"


def test_training_as_of_strict_iso_is_preserved_and_natural_language_rejected():
    direct = REGISTER_NIGHTLY.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    strict = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    assert strict in direct
    assert strict in contract
    assert "$BaseRetrainTrainingAsOf = $BaseRetrainTrainingAsOf.Trim()" in direct
    assert "DateTimeOffset]::TryParse" in direct


@WINDOWS_POWERSHELL_REQUIRED
def test_training_binding_resolver_rejects_existing_candidate_and_natural_time(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    corpus = tmp_path / "corpus.json"
    pit = tmp_path / "pit.json"
    corpus.write_text("{}", encoding="utf-8")
    pit.write_text("{}", encoding="utf-8")
    existing = tmp_path / "candidate-existing"
    existing.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_CONTRACT_SCRIPT": str(CONTRACT),
            "WEATHER_TEST_REPO": str(repo),
            "WEATHER_TEST_CORPUS": str(corpus),
            "WEATHER_TEST_PIT": str(pit),
            "WEATHER_TEST_CANDIDATE": str(existing),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_CONTRACT_SCRIPT
function Invoke-Probe([string]$AsOf, [string]$Candidate) {
  try {
    Resolve-TrainingWindowBaseRetrainBindings `
      -RepoRoot $env:WEATHER_TEST_REPO -ScheduleLocalTime '01:00' `
      -BaseRetrainTargetDate '2026-08-20' -BaseRetrainParentReleaseId 'parent' `
      -BaseRetrainTrainingAsOf $AsOf -BaseRetrainFeatureContractId 'feature' `
      -BaseRetrainCorpusManifest $env:WEATHER_TEST_CORPUS `
      -BaseRetrainPitForecastCorpusManifest $env:WEATHER_TEST_PIT `
      -BaseRetrainCandidateDir $Candidate -BaseRetrainRuntimeId 'runtime' | Out-Null
    return 'accepted'
  } catch { return $_.Exception.Message }
}
[pscustomobject]@{
  existing = Invoke-Probe '2026-08-21T00:30:00-04:00' $env:WEATHER_TEST_CANDIDATE
  natural = Invoke-Probe 'August 21 2026 00:30' ($env:WEATHER_TEST_CANDIDATE + '-missing')
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "must not already exist" in payload["existing"]
    assert "ISO-8601" in payload["natural"]


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_supervisor_disable_and_enable_are_proved_by_settings_enabled_not_state() -> None:
    """A task with a running instance keeps State 'Running' after Disable-ScheduledTask.

    Guards the pyup C2 NO-GO of 2026-10-22: the real stop loop, pre-retrain assert and
    restore run against stubbed Scheduler cmdlets whose State never leaves 'Running'.
    """
    env = os.environ.copy()
    env["WEATHER_TRAINING_WINDOW_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_TRAINING_WINDOW_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw "parse error: $($errors[0].Message)" }
foreach ($name in @('Restore-Capture', 'Assert-CaptureStoppedForTraining')) {
    $fn = $ast.Find({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    . ([scriptblock]::Create($fn.Extent.Text))
}
$stopLoop = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.ForEachStatementAst] -and
    $n.Extent.Text -match 'Disable-ScheduledTask' }, $true)
$stopLoop = [scriptblock]::Create($stopLoop.Extent.Text)

$supervisorTasks = @('WeatherSnapshotLoopSupervisor', 'WeatherClobBookLoopSupervisor',
    'WeatherObservationTriggerSupervisor')
$RepoRoot = 'C:\not-used'
$CaptureRecoveryTimeoutSeconds = 5
function Write-WindowLog { param($Level, $Message) }
function Invoke-StubPython {
    $global:LASTEXITCODE = 0
    if ($args -contains 'weather.operations.capture_recovery_check') {
        '{"ok": true, "workers": [{"ok": true}, {"ok": true}, {"ok": true}]}'
    }
}
$python = 'Invoke-StubPython'
# Stubs only: State stays 'Running' whatever the cmdlet does, as on the host.
$global:tasks = @{}
foreach ($n in $supervisorTasks) {
    $global:tasks[$n] = [pscustomobject]@{ State = 'Running'; Settings = [pscustomobject]@{ Enabled = $true } }
}
$global:mutationTakes = $true
function Get-ScheduledTask { param([string]$TaskName, $ErrorAction) $global:tasks[$TaskName] }
function Disable-ScheduledTask { param([string]$TaskName, $ErrorAction)
    if ($global:mutationTakes) { $global:tasks[$TaskName].Settings.Enabled = $false }
    $global:tasks[$TaskName] }
function Enable-ScheduledTask { param([string]$TaskName, $ErrorAction)
    if ($global:mutationTakes) { $global:tasks[$TaskName].Settings.Enabled = $true }
    $global:tasks[$TaskName] }
function Invoke-Probe([scriptblock]$Body) {
    try { & $Body | Out-Null; return 'accepted' } catch { return $_.Exception.Message }
}
$result = [ordered]@{}
$result.stop_running = Invoke-Probe { . $stopLoop }
$result.assert_running = Invoke-Probe { Assert-CaptureStoppedForTraining }
$result.restore_running = Invoke-Probe { Restore-Capture }
$result.restore_outcome = $script:restoreOutcome
$global:mutationTakes = $false
$result.stop_ignored = Invoke-Probe { . $stopLoop }
$result.assert_enabled = Invoke-Probe { Assert-CaptureStoppedForTraining }
foreach ($t in $global:tasks.Values) { $t.Settings.Enabled = $false }
$result.restore_ignored = Invoke-Probe { Restore-Capture }
$result.states = (@($global:tasks.Values | ForEach-Object { $_.State } | Sort-Object -Unique) -join ',')
[pscustomobject]$result | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["states"] == "Running"
    assert payload["stop_running"] == "accepted"
    assert payload["assert_running"] == "accepted"
    assert payload["restore_running"] == "accepted"
    assert payload["restore_outcome"] == "PASS"
    assert payload["stop_ignored"] == (
        "capture supervisor did not disable: WeatherSnapshotLoopSupervisor=Running enabled=True"
    )
    assert payload["assert_enabled"] == (
        "capture supervisor is not disabled before retrain: "
        "WeatherSnapshotLoopSupervisor=Running enabled=True"
    )
    assert "enable_WeatherSnapshotLoopSupervisor:task remains disabled after enable" in (
        payload["restore_ignored"]
    )
    assert payload["restore_ignored"].count("task remains disabled after enable") == 3


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_stop_waits_for_in_flight_supervisor_ensure_runs_within_bounds() -> None:
    """A disable does not end an in-flight IgnoreNew ensure run, which could relaunch a loop.

    Guards the post-disable wait in training_window.ps1: each supervisor's run must leave
    'Running' within min(its ExecutionTimeLimit + 30 s, the shared stop deadline) of wall
    clock since the wait began; the stop steps get only what remains; and a live
    ExecutionTimeLimit the bound table does not cover fails closed before any disable.
    Get-WindowUtcNow and Start-Sleep are stubbed onto one fake clock, so the probes run
    without waiting; Get-ScheduledTask can charge latency to that clock.
    """
    env = os.environ.copy()
    env["WEATHER_TRAINING_WINDOW_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_TRAINING_WINDOW_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw "parse error: $($errors[0].Message)" }
foreach ($name in @('Wait-SupervisorEnsureRunsEnded', 'Assert-SupervisorEnsureRunLimits',
        'Get-StopSecondsRemaining', 'Assert-StopTimeRemaining')) {
    $fn = $ast.Find({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq $name }, $true)
    . ([scriptblock]::Create($fn.Extent.Text))
}
$bounds = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $n.Left.Extent.Text -eq '$supervisorEnsureRunBoundSeconds' }, $true)
. ([scriptblock]::Create($bounds.Extent.Text))
$supervisorTasks = @('WeatherSnapshotLoopSupervisor', 'WeatherClobBookLoopSupervisor',
    'WeatherObservationTriggerSupervisor')
$CaptureStopTimeoutSeconds = 600.0
$epoch = [datetime]'2026-10-22T05:00:00'
function Write-WindowLog { param($Level, $Message) }
# Stubs only: a fake clock that Start-Sleep and each Get-ScheduledTask call advance.
function Get-WindowUtcNow { $global:now }
function Start-Sleep { param([int]$Milliseconds)
    $global:now = $global:now.AddMilliseconds($Milliseconds) }
$global:limits = @{}
$global:latencyMs = 0
function Get-ScheduledTask { param([string]$TaskName, $ErrorAction)
    $global:now = $global:now.AddMilliseconds($global:latencyMs)
    $settings = [pscustomobject]@{ ExecutionTimeLimit = $global:limits[$TaskName] }
    if ($global:runningPolls[$TaskName] -gt 0) {
        $global:runningPolls[$TaskName]--
        return [pscustomobject]@{ State = 'Running'; Settings = $settings }
    }
    [pscustomobject]@{ State = 'Ready'; Settings = $settings } }
function Invoke-Probe([int]$Snapshot, [int]$Clob, [int]$Observation, [double]$Remaining = 600,
        [int]$LatencyMs = 0) {
    $global:now = $epoch
    $global:latencyMs = $LatencyMs
    $script:childExit = -1
    $global:runningPolls = @{
        WeatherSnapshotLoopSupervisor = $Snapshot
        WeatherClobBookLoopSupervisor = $Clob
        WeatherObservationTriggerSupervisor = $Observation
    }
    try {
        Wait-SupervisorEnsureRunsEnded -StopDeadline $epoch.AddSeconds($Remaining)
        $outcome = 'accepted'
    }
    catch { $outcome = $_.Exception.Message }
    [pscustomobject]@{
        outcome = $outcome
        elapsed = [math]::Round(($global:now - $epoch).TotalSeconds, 1)
        exit = $script:childExit
    }
}
function Invoke-LimitProbe([string]$Snapshot, [string]$Clob, [string]$Observation) {
    $global:now = $epoch
    $global:latencyMs = 0
    $global:runningPolls = @{}
    $global:limits = @{
        WeatherSnapshotLoopSupervisor = $Snapshot
        WeatherClobBookLoopSupervisor = $Clob
        WeatherObservationTriggerSupervisor = $Observation
    }
    try { Assert-SupervisorEnsureRunLimits; 'accepted' } catch { $_.Exception.Message }
}
function Invoke-DeadlineProbe([double]$OffsetSeconds) {
    $global:now = $epoch
    $script:childExit = -1
    try {
        Assert-StopTimeRemaining ($epoch.AddSeconds($OffsetSeconds)) 'CLOB stop'
        $outcome = 'accepted'
    }
    catch { $outcome = $_.Exception.Message }
    [pscustomobject]@{ outcome = $outcome; exit = $script:childExit }
}
[ordered]@{
    idle = Invoke-Probe 0 0 0
    snapshot_ends = Invoke-Probe 3 0 0
    snapshot_at_bound = Invoke-Probe 66 0 0
    snapshot_past_bound = Invoke-Probe 67 0 0
    clob_at_bound = Invoke-Probe 0 30 0
    clob_past_bound = Invoke-Probe 0 31 0
    observation_past_bound = Invoke-Probe 0 0 31
    shared_clock = Invoke-Probe 20 11 0
    latency_charged = Invoke-Probe 1000 0 0 600 400
    deadline_at_remaining = Invoke-Probe 20 0 0 100
    deadline_past_remaining = Invoke-Probe 21 0 0 100
    deadline_spent = Invoke-Probe 1 0 0 0
    limits_registered = Invoke-LimitProbe 'PT5M' 'PT2M' 'PT2M'
    limits_snapshot_longer = Invoke-LimitProbe 'PT5M1S' 'PT2M' 'PT2M'
    limits_clob_longer = Invoke-LimitProbe 'PT5M' 'PT3M' 'PT2M'
    limits_unlimited = Invoke-LimitProbe 'PT5M' 'PT2M' 'PT0S'
    limits_missing = Invoke-LimitProbe '' 'PT2M' 'PT2M'
    stop_time_left = Invoke-DeadlineProbe 30
    stop_time_spent = Invoke-DeadlineProbe 0
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["idle"] == {"outcome": "accepted", "elapsed": 0, "exit": -1}
    assert payload["snapshot_ends"] == {"outcome": "accepted", "elapsed": 15, "exit": -1}
    assert payload["snapshot_at_bound"] == {"outcome": "accepted", "elapsed": 330, "exit": -1}
    assert payload["snapshot_past_bound"] == {
        "outcome": "capture supervisor ensure run still Running 330s after disable "
        "(bound 330s): WeatherSnapshotLoopSupervisor",
        "elapsed": 330,
        "exit": -1,
    }
    assert payload["clob_at_bound"] == {"outcome": "accepted", "elapsed": 150, "exit": -1}
    assert payload["clob_past_bound"]["outcome"].endswith(
        "(bound 150s): WeatherClobBookLoopSupervisor"
    )
    assert payload["observation_past_bound"]["outcome"].endswith(
        "(bound 150s): WeatherObservationTriggerSupervisor"
    )
    # 100 s spent on the snapshot run count against the clob bound as well.
    assert payload["shared_clock"] == {
        "outcome": "capture supervisor ensure run still Running 150s after disable "
        "(bound 150s): WeatherClobBookLoopSupervisor",
        "elapsed": 150,
        "exit": -1,
    }
    # Scheduler-call latency is charged to the bound: wall clock, not a poll count.
    assert payload["latency_charged"]["outcome"].startswith(
        "capture supervisor ensure run still Running 330s after disable (bound 330s)"
    )
    assert 330 <= payload["latency_charged"]["elapsed"] <= 331
    # The shared stop deadline caps the wait below the per-task bound.
    assert payload["deadline_at_remaining"] == {"outcome": "accepted", "elapsed": 100, "exit": -1}
    assert payload["deadline_past_remaining"] == {
        "outcome": "capture stop deadline (600s) exhausted waiting 100s for the ensure run "
        "of WeatherSnapshotLoopSupervisor",
        "elapsed": 100,
        "exit": 9001,
    }
    assert payload["deadline_spent"]["exit"] == 9001
    assert payload["deadline_spent"]["elapsed"] == 0
    assert payload["limits_registered"] == "accepted"
    assert payload["limits_snapshot_longer"] == (
        "capture supervisor ExecutionTimeLimit 'PT5M1S' is not covered by its ensure-run "
        "bound 330s: WeatherSnapshotLoopSupervisor"
    )
    assert payload["limits_clob_longer"].endswith("bound 150s: WeatherClobBookLoopSupervisor")
    assert payload["limits_unlimited"].endswith(
        "bound 150s: WeatherObservationTriggerSupervisor"
    )
    assert payload["limits_missing"].endswith("bound 330s: WeatherSnapshotLoopSupervisor")
    assert payload["stop_time_left"] == {"outcome": "accepted", "exit": -1}
    assert payload["stop_time_spent"] == {
        "outcome": "capture stop deadline (600s) exhausted before CLOB stop",
        "exit": 9001,
    }
    window = SCRIPT.read_text(encoding="utf-8-sig")
    limits = window.index("    Assert-SupervisorEnsureRunLimits\n")
    deadline = window.index("    $stopDeadline = (Get-WindowUtcNow).AddSeconds(")
    first_disable = window.index("Disable-ScheduledTask -TaskName $task -ErrorAction Stop")
    call = window.index("    Wait-SupervisorEnsureRunsEnded -StopDeadline $stopDeadline\n")
    assert limits < deadline < first_disable < call
    stop_section = window[call : window.index("    Assert-CaptureStoppedForTraining\n")]
    for step, command in (
        ("snapshot stop", "snapshot_tracker --stop"),
        ("CLOB stop", "market_microstructure stop"),
        ("observation-trigger stop", "observation_trigger stop"),
        ("stop confirmation", "Wait-CaptureStopped (Get-StopSecondsRemaining $stopDeadline)"),
    ):
        guard = stop_section.index(f'Assert-StopTimeRemaining $stopDeadline "{step}"')
        assert guard < stop_section.index(command), step


def test_supervisor_ensure_run_bounds_match_registered_execution_time_limits() -> None:
    """Each bound in training_window.ps1 is its supervisor registrar's ExecutionTimeLimit + 30 s.

    Guards the ensure-run wait against a registrar limit change that the bound table misses.
    """
    window = SCRIPT.read_text(encoding="utf-8-sig")
    table = window.split("$supervisorEnsureRunBoundSeconds = @{", 1)[1].split("}", 1)[0]
    bounds = {
        name: int(value) for name, value in re.findall(r'"(Weather\w+)"\s*=\s*(\d+)', table)
    }
    registered = {}
    for registrar in (
        "register_snapshot_supervisor.ps1",
        "register_clob_supervisor.ps1",
        "register_observation_trigger_supervisor.ps1",
    ):
        text = (SCRIPT.parent / registrar).read_text(encoding="utf-8-sig")
        task_names = re.findall(r'\[string\]\$TaskName = "(Weather\w+)"', text)
        limits = re.findall(r"-ExecutionTimeLimit \(New-TimeSpan -Minutes (\d+)\)", text)
        assert len(task_names) == 1 and len(limits) == 1, registrar
        registered[task_names[0]] = int(limits[0]) * 60
    assert set(bounds) == set(registered) == {
        "WeatherSnapshotLoopSupervisor",
        "WeatherClobBookLoopSupervisor",
        "WeatherObservationTriggerSupervisor",
    }
    for name, limit_seconds in registered.items():
        assert bounds[name] == limit_seconds + 30, name
