import json
import os
import subprocess
from pathlib import Path

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
    assert "if (-not (Wait-CaptureStopped $CaptureStopTimeoutSeconds))" in text
    assert 'Test-Path -LiteralPath $python -PathType Leaf' in text


def test_training_window_restores_before_propagating_nightly_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "} finally {" in text
    assert "Restore-Capture" in text.split("} finally {", 1)[1]
    assert '$nightlyStatus -in @(\"blocked\", \"error\", \"missing\", \"unreadable\")' in text
    assert text.rstrip().endswith("exit $childExit")


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

    assert "New-ScheduledTaskTrigger -Once -At $runAt" in direct
    assert "New-ScheduledTaskTrigger -Once -At $runAt" in registration
    assert "New-ScheduledTaskTrigger -Daily -At $RestoreAt" in registration
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
    stop_cap_seconds = 600
    recovery_cap_seconds = 300
    deadman_seconds_after_0100 = 195 * 60
    scheduler_limit_seconds = 225 * 60
    assert producer_sla_seconds < child_cap_seconds
    assert stop_cap_seconds + child_cap_seconds + recovery_cap_seconds < deadman_seconds_after_0100
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
