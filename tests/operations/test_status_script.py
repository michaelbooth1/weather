import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


def test_status_paths_are_derived_from_the_invoked_checkout_and_user_profile() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert (
        "[string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))"
        in text
    )
    assert "$repo = [IO.Path]::GetFullPath($RepoRoot)" in text
    assert 'Join-Path $env:USERPROFILE "ops\\mirror_status.json"' in text
    assert "C:\\Users\\micha" not in text


def test_unpushed_guidance_is_guarded_by_quiet_reconciliation_evidence() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    evidence_scan = text.index("function Get-WeatherQuietPushGuidanceState")
    incident_gate = text.index(
        "if ([bool]$quietPushGuidance.IncidentBoundReconciliation)",
        evidence_scan,
    )
    ambiguous_gate = text.index(
        "elseif ([bool]$quietPushGuidance.EvidenceAmbiguous)", incident_gate
    )
    ordinary_guidance = text.index(
        '$warns.Add("$unpushed commit(s) unpushed (run WeatherOneShotPush)")',
        ambiguous_gate,
    )

    assert evidence_scan < incident_gate < ambiguous_gate < ordinary_guidance
    assert text.count("unpushed (run WeatherOneShotPush)") == 1
    assert "WeatherOneShotPush must not be invoked again" in text[
        incident_gate:ambiguous_gate
    ]
    assert "WeatherOneShotPush is forbidden pending reviewed reconciliation" in text[
        ambiguous_gate:ordinary_guidance
    ]
    assert 'Schema = "quiet_window_merge_in_progress_v0.1"' in text
    assert 'Schema = "quiet_window_merge_report_v0.2"' in text
    assert 'operationMode -ceq "production_baseline_reconciliation_v0.1"' in text


@WINDOWS_POWERSHELL_REQUIRED
def test_quiet_push_guidance_classifies_special_and_malformed_evidence(
    tmp_path: Path,
) -> None:
    normal_marker = tmp_path / "normal-marker.json"
    normal_report = tmp_path / "normal-report.json"
    special_marker = tmp_path / "special-marker.json"
    malformed_report = tmp_path / "malformed-report.json"
    unknown_report = tmp_path / "unknown-report.json"
    normal_marker.write_text(
        json.dumps(
            {
                "schema": "quiet_window_merge_in_progress_v0.1",
                "updated_at": "2026-09-01T01:30:00-04:00",
                "phase": "prepared",
                "expected_tip": "0" * 40,
                "expected_baseline": "1" * 40,
            }
        ),
        encoding="utf-8",
    )
    normal_report.write_text(
        json.dumps(
            {
                "schema": "quiet_window_merge_report_v0.2",
                "ts": "2026-09-01T01:31:00-04:00",
                "stage": "dry_run",
                "branch": "origin/example",
                "expected_tip": "0" * 40,
                "expected_baseline": "1" * 40,
            }
        ),
        encoding="utf-8",
    )
    special_marker.write_text(
        json.dumps(
            {
                "schema": "quiet_window_merge_in_progress_v0.1",
                "updated_at": "2026-09-01T01:32:00-04:00",
                "phase": "documented_unpublished",
                "expected_tip": "0" * 40,
                "expected_baseline": "1" * 40,
                "operation_mode": "production_baseline_reconciliation_v0.1",
            }
        ),
        encoding="utf-8",
    )
    malformed_report.write_text("{", encoding="utf-8")
    unknown_report.write_text(
        json.dumps(
            {
                "schema": "quiet_window_merge_report_v0.2",
                "ts": "2026-09-01T01:33:00-04:00",
                "stage": "merged_unpushed",
                "branch": "origin/example",
                "expected_tip": "0" * 40,
                "expected_baseline": "1" * 40,
                "operation_mode": "future_incident_mode",
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "WEATHER_STATUS_SCRIPT": str(SCRIPT),
        "WEATHER_MISSING_MARKER": str(tmp_path / "missing-marker.json"),
        "WEATHER_NORMAL_MARKER": str(normal_marker),
        "WEATHER_NORMAL_REPORT": str(normal_report),
        "WEATHER_SPECIAL_MARKER": str(special_marker),
        "WEATHER_MALFORMED_REPORT": str(malformed_report),
        "WEATHER_UNKNOWN_REPORT": str(unknown_report),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-WeatherQuietPushGuidanceState'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing quiet push guidance function' }
Invoke-Expression $functionAst.Extent.Text
$ordinary = Get-WeatherQuietPushGuidanceState `
    -ActiveMarkerPath $env:WEATHER_NORMAL_MARKER `
    -LastReportPath $env:WEATHER_NORMAL_REPORT
$special = Get-WeatherQuietPushGuidanceState `
    -ActiveMarkerPath $env:WEATHER_SPECIAL_MARKER `
    -LastReportPath $env:WEATHER_NORMAL_REPORT
$malformed = Get-WeatherQuietPushGuidanceState `
    -ActiveMarkerPath $env:WEATHER_MISSING_MARKER `
    -LastReportPath $env:WEATHER_MALFORMED_REPORT
$unknown = Get-WeatherQuietPushGuidanceState `
    -ActiveMarkerPath $env:WEATHER_MISSING_MARKER `
    -LastReportPath $env:WEATHER_UNKNOWN_REPORT
[pscustomobject]@{
    ordinary_incident = [bool]$ordinary.IncidentBoundReconciliation
    ordinary_ambiguous = [bool]$ordinary.EvidenceAmbiguous
    special_incident = [bool]$special.IncidentBoundReconciliation
    special_ambiguous = [bool]$special.EvidenceAmbiguous
    malformed_incident = [bool]$malformed.IncidentBoundReconciliation
    malformed_ambiguous = [bool]$malformed.EvidenceAmbiguous
    unknown_incident = [bool]$unknown.IncidentBoundReconciliation
    unknown_ambiguous = [bool]$unknown.EvidenceAmbiguous
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "ordinary_incident": False,
        "ordinary_ambiguous": False,
        "special_incident": True,
        "special_ambiguous": False,
        "malformed_incident": False,
        "malformed_ambiguous": True,
        "unknown_incident": False,
        "unknown_ambiguous": True,
    }


def test_rearmed_one_shot_does_not_reuse_prior_failure_as_current_flag():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$Trigger.PSObject.Properties["CimClass"]' in text
    assert '$cimClassProperty.Value.PSObject.Properties["CimClassName"]' in text
    assert "$Trigger.CimClass.CimClassName" not in text
    assert '$Trigger.PSObject.Properties["Repetition"]' in text
    assert '$repetitionProperty.Value.PSObject.Properties["Interval"]' in text
    assert "-not $_.Repetition.Interval" not in text
    assert text.count("Test-WeatherOneShotTrigger -Trigger $_") == 2
    assert "$oneShot -and $ti.NextRunTime" in text
    assert '([datetime]$ti.NextRunTime) -gt (Get-Date)' in text
    assert "is re-armed for" in text
    assert "$ok = $true" in text


def test_running_task_does_not_report_its_stale_last_result_as_current_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$st -eq "Running"' in text
    assert "LastTaskResult is a completed-run field" in text
    assert 'if (-not $ok -and $st -eq "Running") { $ok = $true }' in text


def test_stage_a_protected_window_teardown_is_an_expected_task_result():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherDailySettlementPromotionRefresh" = @("0x2", "0x4B")' in text
    assert "kill-on-close Job tore down the delegated child tree" in text
    assert "workload lease is the ownership signal" in text
    assert '$chainTaskResult -eq "0x4B"' in text
    assert "protected-window deadline; durable terminal status verified" in text


def test_capture_alert_flags_only_the_current_local_capture_day():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date" in text
    assert "-not $historicalCaptureDay -and $ageH -lt 24" in text
    assert "capture alert raised today" in text


def test_disabled_on_demand_success_is_not_an_unexpected_disable():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$noTriggers = ($null -eq $_.Triggers)" in text
    assert "$onDemandCompleted = ($noTriggers -and $res -eq \"0x0\"" in text
    assert "completed an on-demand run" in text


def test_exact_tip_merge_is_spent_only_when_tip_is_integrated() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$integratedExactTipMerge = $false" in text
    assert '$actionArguments -like "*quiet_window_merge.ps1*"' in text
    assert '$actionArguments -like "*suite_gated_quiet_merge.ps1*"' in text
    assert '$actionArguments -like "*integration_attempt_merge.ps1*"' in text
    assert "weather_integration_attempt_manifest_v1" in text
    assert "$isQuietMergeAction -and" in text
    assert "-ExpectedTip\\s+([0-9a-f]{40})" in text
    assert "merge-base --is-ancestor $integratedExactTip HEAD" in text
    assert "$integratedExactTipMerge = ($LASTEXITCODE -eq 0)" in text
    assert "retained as spent exact-tip merge evidence" in text
    assert (
        "-not $ok -and $integratedExactTipMerge -and $oneShot -and "
        "-not $ti.NextRunTime"
    ) in text
    assert "but exact tip $integratedExactTip is already in production history" in text


def test_integration_attempt_recovery_states_are_operator_visible() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$integrationAttemptState" in text
    assert '"FAILED_NEEDS_CLOSE"' in text
    assert '"CLOSED_NEEDS_DISPATCH"' in text
    assert '"RECOVERY_READY"' in text
    assert '"SUCCESSOR_CLAIMED"' in text
    assert '"MERGED_UNVERIFIED"' in text
    assert "recovery is ready for an active agent" in text
    assert "$attemptEvidenceAgeHours" in text
    assert "$attemptEvidenceIsFresh" in text
    assert 'evidence_age_hours = $_.evidence_age_hours' in text
    assert 'task_state = $_.task_state' in text
    assert 'suite_task_state = $_.suite_task_state' in text
    assert "$suiteObservation = Get-WeatherIntegrationSuiteObservation" in text
    assert "$suiteReceiptStatus = [string]$suiteObservation.ReceiptStatus" in text
    assert "$suiteObservation.ReceiptUnreadable" in text
    assert "$mergeObservation = Get-WeatherIntegrationMergeObservation" in text
    assert "$attemptMissedSuite = [bool]$suiteObservation.TriggerMissed" in text
    assert "Test-WeatherIntegrationSuiteTriggerMissed" in text
    assert "suite_ran_without_receipt" in text
    assert "merge_receipt_missing_after_trigger" in text
    assert "-SuiteRanWithoutReceipt ([bool]$suiteObservation.RanWithoutReceipt)" in text
    assert "-MergeReceiptMissingAfterTrigger ([bool]$mergeObservation.ReceiptMissingAfterTrigger)" in text
    assert "unreadable or does not match its task-bound hash" in text
    assert "missed its suite trigger and has no receipt" in text
    assert "integration_attempts =" in text
    assert 'Write-Output "  ATTEMPTS  :"' in text


@WINDOWS_POWERSHELL_REQUIRED
def test_integration_attempt_alert_lifecycle_executes_without_running_status() -> None:
    env = os.environ.copy()
    env["WEATHER_STATUS_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherIntegrationAttemptState',
    'Get-WeatherIntegrationAttemptAlertDisposition'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$failed = Get-WeatherIntegrationAttemptState -SuiteReceiptStatus FAIL
$recovery = Get-WeatherIntegrationAttemptState -DispatchStatus READY_FOR_SUCCESSOR_REVIEW
$merged = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED
$reconciled = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED -ReconciliationStatus MERGED_RECONCILED
$cases = @(
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $recovery -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false -RecoveryDispatch dispatch.json
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State SUCCESSOR_CLAIMED -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $merged -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -MergeReceiptMissingAfterTrigger $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true -MergeReceiptMissingAfterTrigger $true
)
[pscustomobject]@{
    states = @($failed, $recovery, $merged, $reconciled)
    severities = @($cases | ForEach-Object { [string]$_.Severity })
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "states": [
            "FAILED_NEEDS_CLOSE",
            "RECOVERY_READY",
            "MERGED_UNVERIFIED",
            "MERGED_RECONCILED",
        ],
        "severities": [
            "FLAG",
            "WARN",
            "FLAG",
            "FLAG",
            "FLAG",
            "NONE",
            "FLAG",
            "WARN",
            "NONE",
            "FLAG",
            "FLAG",
            "WARN",
        ],
    }


@WINDOWS_POWERSHELL_REQUIRED
def test_attempt_observation_distinguishes_running_interrupted_and_missed(
    tmp_path: Path,
) -> None:
    preflight = tmp_path / "preflight.log"
    preflight.write_text("started\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_STATUS_SCRIPT": str(SCRIPT),
            "WEATHER_PREFLIGHT": str(preflight),
            "WEATHER_MISSING_PREFLIGHT": str(tmp_path / "missing.log"),
            "WEATHER_SUITE_RECEIPT": str(tmp_path / "suite-receipt.json"),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherIntegrationSuiteRuntimeState',
    'Test-WeatherIntegrationSuiteTriggerMissed',
    'Get-WeatherIntegrationSuiteObservation',
    'Get-WeatherIntegrationMergeObservation'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$global:suiteState = 'Running'
$global:lastRun = [datetime]'2026-08-21T00:35:00'
function Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    return [pscustomobject]@{ TaskName = $TaskName; State = $global:suiteState }
}
function Get-ScheduledTaskInfo {
    param([string]$TaskName, $ErrorAction)
    return [pscustomobject]@{ LastRunTime = $global:lastRun; LastTaskResult = 267009 }
}
$suiteAt = [datetime]'2026-08-21T00:35:00'
$now = [datetime]'2026-08-21T00:45:00'
$manifest = [pscustomobject]@{
    schedule = [pscustomobject]@{
        suite_at_local = $suiteAt.ToString('o')
        merge_at_local = $suiteAt.AddMinutes(30).ToString('o')
        suite_task_name = 'WeatherIntegrationSuite_a'
    }
    evidence = [pscustomobject]@{
        preflight_log = $env:WEATHER_MISSING_PREFLIGHT
        suite_receipt = $env:WEATHER_SUITE_RECEIPT
    }
}
$running = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
$global:suiteState = 'Ready'
$global:lastRun = [datetime]'1999-11-30T00:00:00'
$manifest.evidence.preflight_log = $env:WEATHER_PREFLIGHT
$preflight = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
Set-Content -LiteralPath $env:WEATHER_SUITE_RECEIPT -Value '{"status":"PASS"}'
$receiptAppeared = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
Set-Content -LiteralPath $env:WEATHER_SUITE_RECEIPT -Value '{'
$unreadableReceipt = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
Remove-Item -LiteralPath $env:WEATHER_SUITE_RECEIPT
$global:suiteState = 'Disabled'
$manifest.evidence.preflight_log = $env:WEATHER_MISSING_PREFLIGHT
$missing = Get-WeatherIntegrationSuiteObservation -AttemptManifest $manifest -Now $now
$withinGrace = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $suiteAt.AddMinutes(4)
$global:suiteState = 'Ready'
$global:lastRun = $null
$nullLastRun = Get-WeatherIntegrationSuiteObservation `
    -AttemptManifest $manifest -Now $now
$mergeAt = $suiteAt.AddMinutes(30)
$mergeRunning = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Running -Now $mergeAt.AddMinutes(10)
$mergeWithinGrace = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(4)
$mergeMissed = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(5)
$mergeReceipt = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Ready -Now $mergeAt.AddMinutes(10) `
    -MergeReceiptStatus FAIL
$mergeClosed = Get-WeatherIntegrationMergeObservation `
    -AttemptManifest $manifest -TaskState Disabled -Now $mergeAt.AddMinutes(10) `
    -ClosureStatus FAIL
[pscustomobject]@{
    running_now = [bool]$running.Running
    running_started = [bool]$running.Started
    running_missed = [bool]$running.TriggerMissed
    running_without_receipt = [bool]$running.RanWithoutReceipt
    preflight_started = [bool]$preflight.Started
    preflight_missed = [bool]$preflight.TriggerMissed
    preflight_ran_without_receipt = [bool]$preflight.RanWithoutReceipt
    fresh_receipt_ran_without_receipt = [bool]$receiptAppeared.RanWithoutReceipt
    fresh_receipt_status = [string]$receiptAppeared.ReceiptStatus
    unreadable_receipt_flagged = [bool]$unreadableReceipt.ReceiptUnreadable
    unreadable_receipt_ran_without_receipt = [bool]$unreadableReceipt.RanWithoutReceipt
    disabled_started = [bool]$missing.Started
    disabled_missed = [bool]$missing.TriggerMissed
    grace_missed = [bool]$withinGrace.TriggerMissed
    null_last_run = $nullLastRun.LastRunTime
    null_last_run_missed = [bool]$nullLastRun.TriggerMissed
    merge_running_missing = [bool]$mergeRunning.ReceiptMissingAfterTrigger
    merge_grace_missing = [bool]$mergeWithinGrace.ReceiptMissingAfterTrigger
    merge_missed = [bool]$mergeMissed.ReceiptMissingAfterTrigger
    merge_receipt_missing = [bool]$mergeReceipt.ReceiptMissingAfterTrigger
    merge_closed_missing = [bool]$mergeClosed.ReceiptMissingAfterTrigger
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "running_now": True,
        "running_started": True,
        "running_missed": False,
        "running_without_receipt": False,
        "preflight_started": True,
        "preflight_missed": False,
        "preflight_ran_without_receipt": True,
        "fresh_receipt_ran_without_receipt": False,
        "fresh_receipt_status": "PASS",
        "unreadable_receipt_flagged": True,
        "unreadable_receipt_ran_without_receipt": True,
        "disabled_started": False,
        "disabled_missed": True,
        "grace_missed": False,
        "null_last_run": None,
        "null_last_run_missed": True,
        "merge_running_missing": False,
        "merge_grace_missing": False,
        "merge_missed": True,
        "merge_receipt_missing": False,
        "merge_closed_missing": False,
    }


def test_only_active_scheduled_interactive_tasks_count_as_reboot_exposure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$scheduledWorkRemains = (-not $noTriggers" in text
    assert '$st -ne "Disabled"' in text
    assert "$scheduledWorkRemains)" in text


def test_status_flags_notify_only_windows_update_policy():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$windowsUpdateAuOptions -eq 2" in text
    assert "policy-forced to notify-only" in text
    assert "unattended_updates_blocked = ($windowsUpdateAuOptions -eq 2)" in text


def test_operator_held_evidence_refresh_keeps_one_honest_warning():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherEveningEvidenceRefresh"' in text
    assert "$evidenceRefreshHeld = $true" in text
    assert "is operator-held DISABLED" in text


def test_quiet_merge_recovery_interval_cannot_overlap_sensitive_driver():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$oneShot -and $ti.NextRunTime -and $isQuietMergeAction" in text
    assert "-SettleSeconds\\s+(\\d+)" in text
    assert "-RollbackRecoverySeconds\\s+(\\d+)" in text
    assert "$settleSeconds + 240" in text
    assert "$settleSeconds + $rollbackRecoverySeconds + 60" in text
    assert "[math]::Max($successProtectionSeconds, $rollbackProtectionSeconds)" in text
    assert '$actionArguments -like "*integration_attempt_merge.ps1*"' in text
    assert "Date.AddHours(5)" in text
    assert "$sensitiveDriverNextRun -ge $mergeTask.at" in text
    assert "the driver can publish unverified local master" in text


def test_status_flags_unproven_rollback_recovery_separately() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$qw.stage -eq "rollback_recovery_failed"' in text
    assert "rollback recovery is UNPROVEN" in text
    assert '$qw.stage -eq "rolled_back"' in text


def test_documentation_transaction_warns_before_deadline_and_flags_after_it() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.documentation_transaction" in text
    assert 'state -eq "INVALID"' in text
    assert 'state -eq "PENDING"' in text
    assert "DOCUMENTATION TRANSACTION DUE" in text
    assert "if ([bool]$documentationTransaction.overdue)" in text
    assert "$flags.Add($detail)" in text
    assert "$warns.Add($detail)" in text
    assert "documentation = $documentationTransaction" in text


def test_settlement_scan_seeks_from_end_instead_of_rescanning_each_ledger():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.settlement_hole_check" in text
    assert "--window-days $windowDays --tail-lines 400 --json" in text
    assert "Get-Content -LiteralPath $ledger -Tail 400" not in text


def test_legacy_unbound_merge_drivers_are_intentionally_held() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherMergeQueueDriver", "WeatherMergeSensitiveDriver", "WeatherSuite0969a"' in text
    assert '$st -ne "Disabled"' in text


def test_training_hold_is_default_and_reenable_warning_requires_exact_bounded_action() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherTrainingWindowReenable*"' in text
    assert "$trainingReenableDeadline = $trainingReenableNow.AddHours(30)" in text
    assert '[string]$candidate.TaskPath -ne "\\"' in text
    assert "$candidateActions.Count -ne 1" in text
    assert "$candidateTriggers.Count -ne 1" in text
    assert 'Join-Path $PSHOME "powershell.exe"' in text
    assert "Enable-ScheduledTask -TaskName 'WeatherTrainingWindow'" in text
    assert "Disable-ScheduledTask -TaskName '$([string]$candidate.TaskName)'" in text
    assert '[string]$candidateAction.Arguments -cne $expectedArguments' in text
    assert '"WeatherTrainingWindow"' in text
    assert "held DISABLED by the opt-in maintenance policy" in text
    assert "automatic re-enable is armed" in text


def test_optional_chain_readiness_is_safe_for_strict_mode_callers() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$chain.PSObject.Properties["production_readiness"]' in text
    assert '$chain.PSObject.Properties["summary"]' in text
    assert '$value.PSObject.Properties["status"]' in text
    assert '$f.PSObject.Properties["result"]' in text
    assert '$fResult.PSObject.Properties["reason"]' in text
    assert '$f.PSObject.Properties["error"]' in text
    assert "$f.result.reason" not in text
    assert "if ($chain -and $chain.production_readiness)" not in text


def test_status_reports_only_an_os_held_heavy_workload_lease() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "Get-WeatherHeavyWorkloadLeaseState" in text
    assert "heavy workload lease active" in text


def test_status_uses_durable_tiering_status_not_scheduler_zero() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "clob_tiering_task_status.json" in text
    assert "clob_raw_tape_tiering_task_status.json" in text
    assert "SKIPPED_WORKLOAD_LEASE_BUSY" in text
    assert "Task Scheduler 0x0 does not prove reclaim" in text
    assert "tiering  = $tieringState" in text


def test_status_snapshot_fallback_matches_the_twelve_minute_capture_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"snapshot_tracker"      = @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720.0 }' in text
    assert '"market_microstructure" = @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180.0 }' in text
    assert '"observation_trigger"   = @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180.0 }' in text


def test_status_surfaces_optional_capture_error_state_without_assuming_one_schema() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$runtimeStatus.PSObject.Properties["consecutive_errors"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_error"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_clean_iteration"]' in text
    assert '$runtimeStatus.PSObject.Properties["last_clean_iteration_at"]' in text
    assert "capture loop ERRORING" in text
    assert "process/heartbeat liveness alone is not a clean iteration" in text
    assert "capture_runtime = $captureRuntimeState" in text
    assert "current_runtime_identity" not in text


def test_status_fails_closed_on_unsynchronized_windows_clock() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'ProviderName = "Microsoft-Windows-Time-Service"' in text
    assert "Id = 35, 37" in text
    assert 'Get-Service -Name W32Time' in text
    assert "$clockQueryExit = $LASTEXITCODE" in text
    assert "Last Successful Sync Time:" in text
    assert "[datetime]::TryParse" in text
    assert "$clockLastSync = $liveSync" in text
    assert 'if ($clockQueryExit -ne 0 -or -not $sourceMatch.Success)' in text
    assert 'Leap Indicator:\\s*3' in text
    assert 'Source:\\s*Local CMOS Clock' in text
    assert "system clock is not synchronized" in text
    assert 'Write-Output ("  CLOCK     : {0}"' in text


def test_clock_event_fallback_cannot_skip_live_w32tm_sampling() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    event_query = text.index("$syncEvent = Get-WinEvent")
    event_catch = text.index("catch { }", event_query)
    live_query = text.index(
        'if ($clockService -and $clockService.Status -eq "Running")',
        event_catch,
    )
    assert event_query < event_catch < live_query
    assert "absence of an event must not\n# skip w32tm" in text


def test_only_exact_superseded_nonfixed_bootstrap_pair_is_expected_disabled() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherIntegrationRecoveryBootstrapSuite0822"' in text
    assert '"WeatherIntegrationRecoveryBootstrapMerge0822"' in text
    assert '"WeatherIntegrationRecoveryBootstrapSuiteFixed0822"' not in text
    assert '"WeatherIntegrationRecoveryBootstrapMergeFixed0822"' not in text
    assert '$isExpectedDisabled = ($st -eq "Disabled" -and $expDisabled -contains $name)' in text
    assert "-and -not $isExpectedDisabled" in text
    assert '$st -eq "Disabled" -and $expDisabled -notcontains $name' in text
    assert "$mustRemainDisabled" in text
    assert '$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapSuite0822")' in text
    assert '$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapMerge0822")' in text
    assert '$mustRemainDisabled.Contains([string]$name) -and $st -ne "Disabled"' in text
    assert "is superseded and must never be re-enabled" in text
    assert "Get-WeatherFixedBootstrapScheduleState" not in text


def test_failed_disabled_one_shot_reports_the_run_not_the_terminal_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$name spent one-shot FAILED $res" in text
    assert "verify its artifact" in text
    assert "(Get-Date).AddHours(-24)" in text


def test_complete_overnight_audit_receipt_replaces_stale_verify_artifact_flag() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"*audit_overnight_integration_chain.ps1*"' in text
    assert "-ReportPath\\s+" in text
    assert '"overnight_integration_chain_audit_v1"' in text
    assert "$candidateAuditReceipt.complete -eq $true" in text
    assert "$knownRetainedGapOnly" in text
    assert "complete audit remains BLOCK only for retained execution-tape gaps" in text
    assert "complete audit verdict is BLOCK" in text


def test_codex_wake_receipt_is_authoritative_over_scheduler_result() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-WeatherCodexWakeReceiptState" in text
    assert '"live_overnight_codex_wake_receipt_v0.2"' in text
    assert '"live_night_salvage_wake_receipt_v0.1"' in text
    assert "overnight-audits|night-salvage" in text
    assert "Get-FileHash -LiteralPath $state.runner_path -Algorithm SHA256" in text
    assert "$propagatesChildExit" in text
    assert "LASTEXITCODE" in text
    assert "receiptStarted.LocalDateTime" in text
    assert 'secret_values_read' in text
    assert 'live_mutation_attempted_by_wrapper' in text
    assert 'authenticated_spawn_smoke' in text
    assert 'integration_already_complete' in text
    assert 'integration_recovered_by_bounded_codex' in text
    assert 'preintegration_ready_no_agent' in text
    assert 'preintegration_recovered_by_codex' in text
    assert 'morning_closeout_completed' in text
    assert 'live_wake_receipt_correction_v0.1' in text
    assert 'bounded_codex_completed_without_integration' in text
    assert 'original_receipt_sha256' in text
    assert 'last_message_sha256' in text
    assert '$correctionCreated -ge $receiptFinished' in text
    assert 'correction_applied' in text
    assert '[double]$receipt.commit_percent_after -lt 60' in text
    assert "completed without its authoritative wake receipt" in text
    assert "authoritative wake receipt is invalid" in text
    assert "authoritative wake receipt is FAIL" in text
    assert "authoritative wake receipt is PASS" in text
    assert "overnight_wakes =" in text


def test_disk_alarm_distinguishes_a_short_burst_from_multi_day_burn() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$cut48 = (Get-Date).AddHours(-48)" in text
    assert "$diskDelta48" in text
    assert "$diskDaysLeft48" in text
    assert "disk 24h burst is" in text
    assert "keep tiering armed and treat the short window as a burst" in text
    assert "delta_48h_gb_per_day" in text


def test_status_monitors_execution_tape_only_after_it_is_armed() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '$executionTapeState.armed = [string]$executionTapeTask.State -ne "Disabled"' in text
    assert '"execution_tape_status.json"' in text
    assert '".execution_tape_status.json.writer.lock"' in text
    assert '"execution_tape_supervisor_status.json"' in text
    assert '$executionAge -le 180' in text
    assert 'public execution-tape evidence integrity is BLOCKED_EVIDENCE_LOSS' in text
    assert 'execution_tape = $executionTapeState' in text
