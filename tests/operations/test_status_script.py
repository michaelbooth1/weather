import json
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"
HEALTH_WATCHDOG = (
    Path(__file__).resolve().parents[2] / "scripts" / "ops" / "health_watchdog.ps1"
)


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
    assert '"AWAITING_SUCCESSOR"' in text
    assert '"SUCCESSOR_UNPUBLISHED"' in text
    assert '"SUCCESSOR_UNREGISTERED"' in text
    assert '"SUCCESSOR_PREPARATION_INCOMPLETE"' in text
    assert '"SUCCESSOR_PREPARATION_FAILED"' in text
    assert '"SUCCESSOR_WINDOW_MISSED"' in text
    assert '"SUCCESSOR_ARMED"' in text
    assert '"MERGED_UNVERIFIED"' in text
    assert "no successor is armed" in text
    assert "Get-WeatherIntegrationSuccessorReadiness" in text
    assert 'publication_required = $_.publication_required' in text
    assert 'unattended_ready = $_.unattended_ready' in text
    assert 'next_action = $_.next_action' in text
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
$closed = Get-WeatherIntegrationAttemptState -ClosureStatus FAIL
$recovery = Get-WeatherIntegrationAttemptState -DispatchStatus READY_FOR_SUCCESSOR_REVIEW
$unpublished = Get-WeatherIntegrationAttemptState -ClaimStatus CLAIMED -SuccessorReadiness PUBLICATION_REQUIRED
$unregistered = Get-WeatherIntegrationAttemptState -ClaimStatus CLAIMED -SuccessorReadiness UNREGISTERED
$windowMissed = Get-WeatherIntegrationAttemptState -ClaimStatus CLAIMED -SuccessorReadiness WINDOW_MISSED
$armed = Get-WeatherIntegrationAttemptState -ClaimStatus CLAIMED -SuccessorReadiness ARMED
$merged = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED
$reconciled = Get-WeatherIntegrationAttemptState -MergeReceiptStatus MERGED_UNVERIFIED -ReconciliationStatus MERGED_RECONCILED
$cases = @(
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $failed -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $closed -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $recovery -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -RecoveryDispatch dispatch.json
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $unpublished -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $unregistered -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $windowMissed -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $armed -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false -SuccessorAttemptId b
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $merged -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $true -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State $reconciled -TaskState Disabled -EvidenceIsFresh $false -SuiteTriggerMissed $false
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $true -SuiteTriggerMissed $false -MergeReceiptMissingAfterTrigger $true
    Get-WeatherIntegrationAttemptAlertDisposition -AttemptId a -State ACTIVE_OR_ARMED -TaskState Ready -EvidenceIsFresh $false -SuiteTriggerMissed $false -SuiteRanWithoutReceipt $true -MergeReceiptMissingAfterTrigger $true
)
[pscustomobject]@{
    states = @($failed, $closed, $recovery, $unpublished, $unregistered, $windowMissed, $armed, $merged, $reconciled)
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
            "CLOSED_NEEDS_DISPATCH",
            "AWAITING_SUCCESSOR",
            "SUCCESSOR_UNPUBLISHED",
            "SUCCESSOR_UNREGISTERED",
            "SUCCESSOR_WINDOW_MISSED",
            "SUCCESSOR_ARMED",
            "MERGED_UNVERIFIED",
            "MERGED_RECONCILED",
        ],
        "severities": [
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "FLAG",
            "WARN",
            "FLAG",
            "WARN",
            "NONE",
            "FLAG",
            "FLAG",
            "FLAG",
        ],
    }


def test_successor_readiness_distinguishes_publication_registration_and_armed() -> None:
    env = os.environ.copy()
    env["WEATHER_STATUS_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-WeatherIntegrationSuccessorReadiness'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing successor readiness function' }
Invoke-Expression $functionAst.Extent.Text
$global:manifest = [pscustomobject]@{
    branch_ref = 'origin/codex/successor'
    expected_tip = ('a' * 40 -join '')
    schedule = [pscustomobject]@{
        suite_at_local = '2026-08-24T02:00:00'
        merge_at_local = '2026-08-24T03:00:00'
    }
    evidence = [pscustomobject]@{
        suite_receipt = [IO.Path]::Combine(
            [IO.Path]::GetTempPath(), 'weather-definitely-missing-suite-receipt.json'
        )
    }
}
$claim = [pscustomobject]@{
    successor_manifest_path = 'Z:\synthetic-manifest.json'
    successor_manifest_sha256 = ('b' * 64 -join '')
}
function Get-WeatherIntegrationValidatedEvidence {
    param($RepositoryRoot, $ManifestPath, $ExpectedManifestSha256, $Target)
    if ($Target -eq 'manifest') { return [pscustomobject]@{ Payload = $global:manifest } }
    return [pscustomobject]@{ Status = 'PASS' }
}
function git {
    $global:LASTEXITCODE = 0
    return ('a' * 40 -join '')
}
function Assert-WeatherIntegrationStatusTaskBindings {
    $task = [pscustomobject]@{ State = 'Ready'; Settings = [pscustomobject]@{ Enabled = $true } }
    return [pscustomobject]@{
        Suite = [pscustomobject]@{ Task = $task; Info = [pscustomobject]@{ NextRunTime = [datetime]'2026-08-24T02:00:00' } }
        Merge = [pscustomobject]@{ Task = $task; Info = [pscustomobject]@{ NextRunTime = [datetime]'2026-08-24T03:00:00' } }
    }
}
$global:preparationState = 'READY'
function Get-WeatherIntegrationPreparationReadiness {
    return [pscustomobject]@{
        State = $global:preparationState
        Detail = "synthetic $($global:preparationState) preparation"
    }
}
$armed = Get-WeatherIntegrationSuccessorReadiness `
    -RepositoryRoot 'Z:\repo' -SuccessorClaim $claim -Now ([datetime]'2026-08-24T01:00:00')
$global:preparationState = 'INCOMPLETE'
$crashedAfterRegistration = Get-WeatherIntegrationSuccessorReadiness `
    -RepositoryRoot 'Z:\repo' -SuccessorClaim $claim -Now ([datetime]'2026-08-24T01:00:00')
$global:preparationState = 'FAILED'
$preparationFailed = Get-WeatherIntegrationSuccessorReadiness `
    -RepositoryRoot 'Z:\repo' -SuccessorClaim $claim -Now ([datetime]'2026-08-24T01:00:00')
$global:preparationState = 'READY'
function Assert-WeatherIntegrationStatusTaskBindings { throw 'tasks absent' }
$unregistered = Get-WeatherIntegrationSuccessorReadiness `
    -RepositoryRoot 'Z:\repo' -SuccessorClaim $claim -Now ([datetime]'2026-08-24T01:00:00')
function git {
    $global:LASTEXITCODE = 0
    return ('c' * 40 -join '')
}
$unpublished = Get-WeatherIntegrationSuccessorReadiness `
    -RepositoryRoot 'Z:\repo' -SuccessorClaim $claim -Now ([datetime]'2026-08-24T01:00:00')
[pscustomobject]@{
    states = @(
        $armed.State,
        $crashedAfterRegistration.State,
        $preparationFailed.State,
        $unregistered.State,
        $unpublished.State
    )
    publication_required = @(
        [bool]$armed.PublicationRequired,
        [bool]$crashedAfterRegistration.PublicationRequired,
        [bool]$preparationFailed.PublicationRequired,
        [bool]$unregistered.PublicationRequired,
        [bool]$unpublished.PublicationRequired
    )
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
            "ARMED",
            "PREPARATION_INCOMPLETE",
            "PREPARATION_FAILED",
            "UNREGISTERED",
            "PUBLICATION_REQUIRED",
        ],
        "publication_required": [False, False, False, False, True],
    }


def test_preparation_disposition_and_current_arming_are_fail_closed() -> None:
    env = os.environ.copy()
    env["WEATHER_STATUS_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
foreach ($name in @(
    'Get-WeatherIntegrationPreparationDisposition',
    'Get-WeatherIntegrationPreparationPublicationState',
    'Get-WeatherIntegrationOrphanPreparationState',
    'Test-WeatherIntegrationCurrentAttemptArmed',
    'Test-WeatherIntegrationAttemptScheduleOverlap'
)) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$absent = Get-WeatherIntegrationPreparationDisposition `
    -NamespaceExists $false -IntentPresent $false -IntentValid $false `
    -ReceiptPresent $false -ReceiptValid $false
$crashed = Get-WeatherIntegrationPreparationDisposition `
    -NamespaceExists $true -IntentPresent $true -IntentValid $true `
    -ReceiptPresent $false -ReceiptValid $false
$failed = Get-WeatherIntegrationPreparationDisposition `
    -NamespaceExists $true -IntentPresent $true -IntentValid $true `
    -ReceiptPresent $true -ReceiptValid $true -ReceiptStatus FAIL
$ready = Get-WeatherIntegrationPreparationDisposition `
    -NamespaceExists $true -IntentPresent $true -IntentValid $true `
    -ReceiptPresent $true -ReceiptValid $true -ReceiptStatus PASS
$publicationAbsent = Get-WeatherIntegrationPreparationPublicationState `
    -RemoteLookupCompleted $true -RemoteTipBefore $null `
    -PushAttempted $false -PushPerformed $false -RemoteTipAfter $null `
    -ExpectedTip ('a' * 40 -join '')
$publicationPreexisting = Get-WeatherIntegrationPreparationPublicationState `
    -RemoteLookupCompleted $true -RemoteTipBefore ('a' * 40 -join '') `
    -PushAttempted $false -PushPerformed $false -RemoteTipAfter $null `
    -ExpectedTip ('a' * 40 -join '')
$publicationLostAck = Get-WeatherIntegrationPreparationPublicationState `
    -RemoteLookupCompleted $true -RemoteTipBefore $null `
    -PushAttempted $true -PushPerformed $false -RemoteTipAfter $null `
    -ExpectedTip ('a' * 40 -join '')
$noMutation = Get-WeatherIntegrationOrphanPreparationState `
    -ManifestExists $false -ClosureRequired $false -ClosureProved $false `
    -PublicationState $publicationAbsent
$publicationOnly = Get-WeatherIntegrationOrphanPreparationState `
    -ManifestExists $false -ClosureRequired $false -ClosureProved $false `
    -PublicationState $publicationPreexisting
$uncertain = Get-WeatherIntegrationOrphanPreparationState `
    -ManifestExists $false -ClosureRequired $false -ClosureProved $false `
    -PublicationState $publicationLostAck
$closureUnproved = Get-WeatherIntegrationOrphanPreparationState `
    -ManifestExists $true -ClosureRequired $true -ClosureProved $false `
    -PublicationState $publicationPreexisting
$base = @{
    AttemptState = 'ACTIVE_OR_ARMED'
    PreparationState = 'READY'
    TaskBindingsValid = $true
    SuiteTaskState = 'Ready'
    MergeTaskState = 'Ready'
    SuiteEnabled = $true
    MergeEnabled = $true
    SuiteNextRunTime = [datetime]'2026-08-25T00:40:00'
    MergeNextRunTime = [datetime]'2026-08-25T01:20:00'
    SuiteTriggerAt = [datetime]'2026-08-25T00:40:00'
    MergeTriggerAt = [datetime]'2026-08-25T01:20:00'
    Now = [datetime]'2026-08-25T00:30:00'
    SuiteTriggerMissed = $false
}
$armed = Test-WeatherIntegrationCurrentAttemptArmed @base
$base.TaskBindingsValid = $false
$bindingContradiction = Test-WeatherIntegrationCurrentAttemptArmed @base
$base.TaskBindingsValid = $true
$base.PreparationState = 'ABSENT'
$preparationContradiction = Test-WeatherIntegrationCurrentAttemptArmed @base
$base.PreparationState = 'READY'
$base.MergeNextRunTime = [datetime]'2026-08-25T01:25:00'
$nextRunContradiction = Test-WeatherIntegrationCurrentAttemptArmed @base
$overlap = Test-WeatherIntegrationAttemptScheduleOverlap `
    -FirstSuiteAt ([datetime]'2026-08-25T00:40:00') `
    -FirstMergeAt ([datetime]'2026-08-25T01:20:00') `
    -SecondSuiteAt ([datetime]'2026-08-25T01:10:00') `
    -SecondMergeAt ([datetime]'2026-08-25T02:00:00')
$separate = Test-WeatherIntegrationAttemptScheduleOverlap `
    -FirstSuiteAt ([datetime]'2026-08-25T00:40:00') `
    -FirstMergeAt ([datetime]'2026-08-25T01:20:00') `
    -SecondSuiteAt ([datetime]'2026-08-25T01:21:00') `
    -SecondMergeAt ([datetime]'2026-08-25T02:00:00')
[pscustomobject]@{
    dispositions = @($absent, $crashed, $failed, $ready)
    publication = @($publicationAbsent, $publicationPreexisting, $publicationLostAck)
    orphan = @($noMutation, $publicationOnly, $uncertain, $closureUnproved)
    armed = @(
        [bool]$armed,
        [bool]$bindingContradiction,
        [bool]$preparationContradiction,
        [bool]$nextRunContradiction
    )
    overlap = @([bool]$overlap, [bool]$separate)
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
        "dispositions": ["ABSENT", "INCOMPLETE", "FAILED", "READY"],
        "publication": ["ABSENT", "PROVED", "UNCERTAIN"],
        "orphan": [
            "PREPARATION_NO_MUTATION_HISTORY",
            "PUBLICATION_ONLY",
            "PREPARATION_FAILED",
            "CLOSURE_UNPROVED",
        ],
        "armed": [True, False, False, False],
        "overlap": [True, False],
    }


def test_orphan_preparation_failures_are_bounded_persistent_status() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'EndsWith(".preparation"' in text
    assert "Select-Object -First 129" in text
    assert "Select-Object -First 513" in text
    assert "LastWriteTimeUtc" in text
    assert "Descending = $true" in text
    assert "$candidates.Count -ge 257" in text
    assert "discovery exceeded its 256-namespace safety bound" in text
    assert '"PREPARATION_FAILED"' in text
    assert '"PUBLICATION_ONLY"' in text
    assert '"CLOSURE_UNPROVED"' in text
    assert '"PREPARATION_NO_MUTATION_HISTORY"' in text
    assert "is persistently blocked" in text
    assert "$observedIntegrationAttemptManifests.Contains($manifestPath)" in text
    assert "Read-WeatherStatusBoundedJsonEvidence" in text
    assert "Status evidence must be a bounded regular non-reparse file" in text
    assert "MaximumBytes = 1048576" in text
    assert "Get-Content -LiteralPath $receiptPath -Raw" not in text
    assert "attempt_creation_required = ($preparationState -eq \"PUBLICATION_ONLY\")" in text
    assert "publication_required = $false" in text
    assert "have overlapping exact armed schedules" in text


def test_orphan_discovery_keeps_newest_after_more_than_128_history_dirs(
    tmp_path: Path,
) -> None:
    for index in range(130):
        historical = tmp_path / f"historical-{index:03d}"
        historical.mkdir()
        os.utime(historical, (1_600_000_000 + index, 1_600_000_000 + index))
    current = tmp_path / "current-a1.preparation"
    current.mkdir()
    os.utime(current, (1_900_000_000, 1_900_000_000))
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_STATUS_SCRIPT": str(SCRIPT),
            "WEATHER_ATTEMPT_DISCOVERY_ROOT": str(tmp_path),
            "WEATHER_CURRENT_PREPARATION": str(current.resolve()),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-WeatherIntegrationPreparationDirectoryCandidates'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing bounded preparation discovery function' }
Invoke-Expression $functionAst.Extent.Text
$result = Get-WeatherIntegrationPreparationDirectoryCandidates `
    -Root $env:WEATHER_ATTEMPT_DISCOVERY_ROOT
$paths = @($result.Directories | ForEach-Object { [IO.Path]::GetFullPath($_.FullName) })
if (-not [bool]$result.Truncated -or
    $paths -inotcontains [IO.Path]::GetFullPath($env:WEATHER_CURRENT_PREPARATION)) {
    throw 'newest preparation namespace was omitted behind historical directories'
}
'OK'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_active_one_shot_registry_survives_task_deletion_until_resolution() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'data\\one_shot_readiness\\active' in text
    assert '$allManifestFiles = @($registryChildren' in text
    assert "one_shot_registry_activation.json" in text
    assert "one_shot_registry_activation_intent.json" in text
    assert "one_shot_registry_activation_recovery.json" in text
    assert "one_shot_registry.lock" in text
    assert "one_shot_registry_index" in text
    assert "$indexChildHardLimit = 8192" in text
    assert "$indexMetadataBudgetBytes = 64MB" in text
    assert "one_shot_registry_index_path = $oneShotRegistryIndexRoot" in text
    assert '"weather_one_shot_registry_activation_v1"' in text
    assert '$oneShotRegistryState = "NEVER_ACTIVATED"' in text
    assert "$sortedUnresolvedManifestFiles + $sortedResolvedManifestFiles" in text
    assert "$registryCompactionWarningCount = 192" in text
    assert "$registryManifestHardLimit = 256" in text
    assert "8-manifest / 64-MiB validation budget" in text
    assert "Read-WeatherStatusBoundedJsonEvidence" in text
    assert '"weather_one_shot_readiness_manifest_v0.4"' in text
    assert '-Mode InspectAuto' in text
    assert "ACTIVE ONE-SHOT REGISTRY BLOCKED" in text
    assert '"weather_one_shot_readiness_resolution_v1"' in text
    assert '@("TERMINAL", "SUPERSEDED")' in text
    assert "REVIEWED_CREATE_ONLY_ONE_SHOT_RESOLUTION_NO_SCHEDULER_MUTATION" in text
    assert "successor_manifest_sha256" in text
    assert "$observedOneShotReadinessManifests.Contains" in text
    assert "$oneShotRegistrySchedulerSnapshot" in text
    assert '$liveTerminal = ([string]$resolvedTasks[0].State -eq "Disabled")' in text
    assert "$registryMetadataBudgetBytes = 8MB" in text
    assert "$resolutionPropertyNames" in text
    assert "$terminalProofPropertyNames" in text
    assert "Get-WeatherOneShotActiveManifestFileIdentity" in text
    successor_identity = text.index(
        "$successorIdentity = Get-WeatherOneShotActiveManifestFileIdentity"
    )
    successor_read = text.index(
        "$successorItem = Get-Item -LiteralPath $successorPath", successor_identity
    )
    assert successor_identity < successor_read


def test_compacted_supersession_graph_requires_exact_successor_and_rejects_cycles(
) -> None:
    env = os.environ.copy()
    env["WEATHER_STATUS_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'status script did not parse' }
$edgeLoops = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.ForEachStatementAst] -and
        $node.Extent.Text -like (
            '*compacted supersession edge has no exact live or compacted successor*'
        )
}, $true))
$graphLoops = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.ForEachStatementAst] -and
        $node.Extent.Text -like '*compacted supersession graph contains a cycle*'
}, $true))
if ($edgeLoops.Count -ne 1 -or $graphLoops.Count -ne 1) {
    throw 'could not isolate exact compacted-supersession production loops'
}
$edgeLoopText = [string]$edgeLoops[0].Extent.Text
$graphLoopText = [string]$graphLoops[0].Extent.Text

function Invoke-CompactedSupersessionCase {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Missing', 'Cycle', 'Live', 'Compacted', 'Long')]
        [string]$Mode
    )

    $taskName = 'WeatherSyntheticGraph'
    $aSha = ('a' * 64) -join ''
    $bSha = ('b' * 64) -join ''
    $aResolutionSha = ('c' * 64) -join ''
    $bResolutionSha = ('d' * 64) -join ''
    $aKey = "$taskName|$aSha"
    $bKey = "$taskName|$bSha"
    $aManifestPath = [IO.Path]::GetFullPath(
        "C:\synthetic\$taskName.$aSha.manifest.json"
    )
    $bManifestPath = [IO.Path]::GetFullPath(
        "C:\synthetic\$taskName.$bSha.manifest.json"
    )
    $aResolutionPath = [IO.Path]::GetFullPath(
        "C:\synthetic\$taskName.$aSha.resolution.json"
    )
    $bResolutionPath = [IO.Path]::GetFullPath(
        "C:\synthetic\$taskName.$bSha.resolution.json"
    )

    $flags = New-Object System.Collections.Generic.List[string]
    $manifestIndexEvents = @{
        $aKey = [pscustomobject]@{
            manifest_path = $aManifestPath
            manifest_sha256 = $aSha
        }
    }
    $resolutionIndexEvents = @{
        $aKey = [pscustomobject]@{
            resolution_path = $aResolutionPath
            resolution_sha256 = $aResolutionSha
        }
    }
    $activeManifestKeys = @{}
    $activeResolutionKeys = @{}
    $compactionReceipts = @{
        $aKey = [pscustomobject]@{
            task_name = $taskName
            task_path = '\'
            manifest_path = $aManifestPath
            manifest_sha256 = $aSha
            resolution_path = $aResolutionPath
            resolution_sha256 = $aResolutionSha
            resolution_status = 'SUPERSEDED'
            successor_manifest_path = $bManifestPath
            successor_manifest_sha256 = $bSha
        }
    }

    if ($Mode -in @('Cycle', 'Live', 'Compacted')) {
        $manifestIndexEvents[$bKey] = [pscustomobject]@{
            manifest_path = $bManifestPath
            manifest_sha256 = $bSha
        }
    }
    if ($Mode -eq 'Live') {
        $activeManifestKeys[$bKey] = [pscustomobject]@{}
    }
    elseif ($Mode -in @('Cycle', 'Compacted')) {
        $resolutionIndexEvents[$bKey] = [pscustomobject]@{
            resolution_path = $bResolutionPath
            resolution_sha256 = $bResolutionSha
        }
        $bStatus = if ($Mode -eq 'Cycle') { 'SUPERSEDED' } else { 'TERMINAL' }
        $compactionReceipts[$bKey] = [pscustomobject]@{
            task_name = $taskName
            task_path = '\'
            manifest_path = $bManifestPath
            manifest_sha256 = $bSha
            resolution_path = $bResolutionPath
            resolution_sha256 = $bResolutionSha
            resolution_status = $bStatus
            successor_manifest_path = $aManifestPath
            successor_manifest_sha256 = $aSha
        }
    }
    elseif ($Mode -eq 'Long') {
        $manifestIndexEvents[$bKey] = [pscustomobject]@{
            manifest_path = $bManifestPath
            manifest_sha256 = $bSha
        }
        $priorKey = $bKey
        $priorManifestPath = $bManifestPath
        $priorManifestSha = $bSha
        $priorResolutionPath = $bResolutionPath
        for ($index = 1; $index -le 300; $index++) {
            $resolutionIndexEvents[$priorKey] = [pscustomobject]@{
                resolution_path = $priorResolutionPath
                resolution_sha256 = $bResolutionSha
            }
            $nextSha = ([int]$index).ToString('x').PadLeft(64, '0')
            $nextKey = "$taskName|$nextSha"
            $nextManifestPath = [IO.Path]::GetFullPath(
                "C:\synthetic\$taskName.$nextSha.manifest.json"
            )
            $compactionReceipts[$priorKey] = [pscustomobject]@{
                task_name = $taskName
                task_path = '\'
                manifest_path = $priorManifestPath
                manifest_sha256 = $priorManifestSha
                resolution_path = $priorResolutionPath
                resolution_sha256 = $bResolutionSha
                resolution_status = 'SUPERSEDED'
                successor_manifest_path = $nextManifestPath
                successor_manifest_sha256 = $nextSha
            }
            $manifestIndexEvents[$nextKey] = [pscustomobject]@{
                manifest_path = $nextManifestPath
                manifest_sha256 = $nextSha
            }
            if ($index -eq 300) {
                $activeManifestKeys[$nextKey] = [pscustomobject]@{}
            }
            else {
                $priorKey = $nextKey
                $priorManifestPath = $nextManifestPath
                $priorManifestSha = $nextSha
                $priorResolutionPath = [IO.Path]::GetFullPath(
                    "C:\synthetic\$taskName.$nextSha.resolution.json"
                )
            }
        }
    }

    Invoke-Expression $edgeLoopText
    $completedCompactionGraphNodes = @{}
    Invoke-Expression $graphLoopText
    return @($flags)
}

[pscustomobject]@{
    missing = @(Invoke-CompactedSupersessionCase -Mode Missing)
    cycle = @(Invoke-CompactedSupersessionCase -Mode Cycle)
    live = @(Invoke-CompactedSupersessionCase -Mode Live)
    compacted = @(Invoke-CompactedSupersessionCase -Mode Compacted)
    long = @(Invoke-CompactedSupersessionCase -Mode Long)
} | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert any(
        "has no exact live or compacted successor" in flag
        for flag in payload["missing"]
    )
    assert any("contains a cycle" in flag for flag in payload["cycle"])
    assert payload["live"] == []
    assert payload["compacted"] == []
    assert payload["long"] == []


def test_registry_activation_marker_survives_whole_data_tree_deletion() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    marker_assignment = text.index("$oneShotRegistryActivationPath = Join-Path $repo")
    marker_block = text[marker_assignment : marker_assignment + 700]
    assert '"one_shot_registry_activation.json"' in marker_block
    assert '"one_shot_registry_activation_intent.json"' in marker_block
    assert '"one_shot_registry_activation_recovery.json"' in marker_block
    assert '"data\\one_shot_registry_activation.json"' not in marker_block
    assert "-not $oneShotRegistryIntentExists" in text
    assert '$oneShotRegistryState = "ACTIVATION_MISMATCH"' in text
    assert "-ErrorAction Stop" in text[marker_assignment : marker_assignment + 700]


def test_protected_one_shot_gate_is_independent_of_trigger_shape() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    start = text.index("$readinessBindingRequired = (")
    binding_gate = text[start : text.index("if ($readinessBindingPartial", start)]
    assert '$name -like "WeatherSettlementBackfill*"' in binding_gate
    assert "$oneShot" not in binding_gate
    assert "$ti.NextRunTime" not in binding_gate
    assert "Settings.Enabled" not in binding_gate
    assert "readinessPayload.task_name" in text
    assert "readinessPayload.task_path" in text
    assert "readinessPayload.manifest_path" in text
    assert "readinessPayload.manifest_sha256" in text


def test_deferred_live_origin_check_cannot_claim_unattended_readiness() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'LiveOriginRevalidation = "DEFERRED"' in text
    assert (
        '[string]$currentLocalReadiness.LiveOriginRevalidation -eq "PASS"' in text
    )
    assert "live_origin_revalidation = $_.live_origin_revalidation" in text


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


def test_documentation_transaction_flags_at_action_lead_and_names_overdue() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "weather.operations.documentation_transaction" in text
    assert 'state -eq "INVALID"' in text
    assert 'state -eq "PENDING"' in text
    assert "Get-WeatherDocumentationTransactionDisposition" in text
    assert "DOCUMENTATION TRANSACTION ACTION REQUIRED" in text
    assert "DOCUMENTATION TRANSACTION OVERDUE" in text
    assert "DOCUMENTATION TRANSACTION PENDING" in text
    assert "documentation = $documentationTransaction" in text


def test_documentation_transaction_disposition_is_deterministic() -> None:
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
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-WeatherDocumentationTransactionDisposition'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing documentation disposition function' }
Invoke-Expression $functionAst.Extent.Text
$base = [ordered]@{
    overdue = $false
    action_required = $false
    action_required_at_local = '2026-08-24T07:00:00-04:00'
    action_lead_minutes = 120
    due_at_local = '2026-08-24T09:00:00-04:00'
    integration_count = 1
    pending_sha256 = ('a' * 64 -join '')
}
$pending = Get-WeatherDocumentationTransactionDisposition -Transaction ([pscustomobject]$base)
$base.action_required = $true
$action = Get-WeatherDocumentationTransactionDisposition -Transaction ([pscustomobject]$base)
$base.overdue = $true
$overdue = Get-WeatherDocumentationTransactionDisposition -Transaction ([pscustomobject]$base)
[pscustomobject]@{
    severities = @($pending.Severity, $action.Severity, $overdue.Severity)
    details = @($pending.Detail, $action.Detail, $overdue.Detail)
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
    payload = json.loads(result.stdout)
    assert payload["severities"] == ["WARN", "FLAG", "FLAG"]
    assert payload["details"][0].startswith("DOCUMENTATION TRANSACTION PENDING:")
    assert payload["details"][1].startswith(
        "DOCUMENTATION TRANSACTION ACTION REQUIRED:"
    )
    assert payload["details"][2].startswith("DOCUMENTATION TRANSACTION OVERDUE:")


def test_health_watchdog_classifies_documentation_deadline_flags_as_high() -> None:
    text = HEALTH_WATCHDOG.read_text(encoding="utf-8-sig")

    assert 'return "documentation"' in text
    assert 'documentation = "NOW - finish and publish' in text
    assert '"documentation" { "HIGH" }' in text


def test_status_revalidates_bound_future_one_shots_before_their_trigger() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "one_shot_readiness.ps1" in text
    assert "-ReadinessManifestPath" in text
    assert "-ExpectedReadinessManifestSha256" in text
    assert "-Mode Inspect" in text
    assert 'name -like "WeatherSettlementBackfill*"' in text
    assert "armed one-shot lacks its complete readiness manifest/hash binding" in text
    assert "ARMED ONE-SHOT BLOCKED BEFORE RUN" in text
    assert "one_shot_readiness =" in text
    assert 'Write-Output "  ONE-SHOTS :"' in text


def test_disabled_bound_one_shot_cannot_hide_a_deleted_anchor() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$st -eq "Disabled" -and' in text
    assert "$disabledExpectedLeaf" in text
    assert "$canonicalOneShotManifestRegistry" in text
    assert "disabled one-shot lost its exact canonical readiness anchor" in text
    assert "DISABLED_READINESS_ANCHOR_MISSING_OR_NONCANONICAL" in text


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


def test_terminal_chain_interruption_cannot_be_reported_as_running_without_live_child_proof() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    terminal_branch = "if ($chain -and [bool]$chain.terminal -and $chainInterruption)"
    running_branch = "elseif ($chainRuntimeProcessProved)"
    assert terminal_branch in text
    assert running_branch in text
    assert text.index(terminal_branch) < text.index(running_branch)
    assert '"INTERRUPTED/{0} at {1}" -f $interruptionStatus, $chainStepName' in text
    assert '"STOPPED_AT_DEADLINE/RESUMABLE at $chainStepName"' in text
    assert '$interruptionStatus -eq "RESUMABLE" -and $chainTaskResult -eq "0x4B"' in text
    assert '"RUNNING NOW: $chainStepName"' in text
    assert "Get-CimInstance Win32_Process -Filter" in text
    assert '"weather.operations.daily_refresh_step_child"' in text
    assert '"--step {0}" -f $chainStepName' in text
    assert '"INTERRUPTED/UNPROVED at $chainStepName"' in text
    assert "daily chain interrupted/resumable" in text


def test_one_shot_resolution_matches_scheduler_identity_case_insensitively() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "[string]$_.TaskName -ieq $registeredTaskName" in text
    assert "[string]$_.TaskPath -ieq $registeredTaskPath" in text
    assert "[string]$_.TaskName -ceq $registeredTaskName" not in text
    assert "[string]$_.TaskPath -ceq $registeredTaskPath" not in text


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
