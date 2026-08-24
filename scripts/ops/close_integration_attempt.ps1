# Safely abandon an attempt whose wrapper crashed or whose operator has chosen
# not to continue. Exact attempt tasks are disabled first; only then is an
# immutable FAIL receipt emitted so a replacement attempt can reference it.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Invoke-WeatherClosureGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $rows = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Could not resolve $Label while classifying the attempt for closure."
    }
    return ([string]$rows[0]).Trim()
}

function Read-WeatherClosureQuietReport {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $attempt = $AttemptContract.Manifest
    $reportPath = [string]$attempt.evidence.quiet_merge_report
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        return $null
    }
    $reportSha256 = Get-WeatherIntegrationFileSha256 -Path $reportPath
    $report = Read-WeatherIntegrationSharedJson -Path $reportPath
    $originUrlProperty = $attempt.baseline.PSObject.Properties["origin_url"]
    if ([string]$report.schema -ne "quiet_window_merge_report_v0.2" -or
        [string]$report.branch -ne [string]$attempt.branch_ref -or
        [string]$report.expected_tip -ne [string]$attempt.expected_tip -or
        [string]$report.expected_baseline -ne [string]$attempt.baseline.master -or
        ($null -ne $originUrlProperty -and
            [string]$report.origin_url -cne [string]$originUrlProperty.Value) -or
        (-not [string]::IsNullOrWhiteSpace([string]$report.baseline_commit) -and
            [string]$report.baseline_commit -ne [string]$attempt.baseline.master) -or
        (-not [string]::IsNullOrWhiteSpace([string]$report.resolved_branch_tip) -and
            [string]$report.resolved_branch_tip -ne [string]$attempt.expected_tip) -or
        (-not [string]::IsNullOrWhiteSpace([string]$report.pre_merge_commit) -and
            [string]$report.pre_merge_commit -notmatch '^[0-9a-f]{40}$') -or
        (-not [string]::IsNullOrWhiteSpace([string]$report.merge_commit) -and
            [string]$report.merge_commit -notmatch '^[0-9a-f]{40}$')) {
        throw "Canonical quiet-merge evidence exists but is malformed or not bound to this attempt; closure is unsafe: $reportPath"
    }
    return [pscustomobject]@{
        Path = Resolve-WeatherIntegrationPath -Path $reportPath
        Sha256 = $reportSha256
        Payload = $report
        PublicationProved = (
            [bool]$report.ok -and
            [string]$report.stage -eq "pushed" -and
            [bool]$report.publication_acknowledged -and
            [bool]$report.documentation_transaction_recorded -and
            [string]$report.baseline_commit -eq [string]$attempt.baseline.master -and
            [string]$report.resolved_branch_tip -eq [string]$attempt.expected_tip -and
            [string]$report.merge_commit -match '^[0-9a-f]{40}$'
        )
        RecoveredMergeProved = (
            [bool]$report.ok -and
            [string]$report.stage -in @("pushed", "merged_unpushed") -and
            [bool]$report.capture_recovery_proved -and
            (-not [bool]$report.execution_tape_recovery_required -or
                [bool]$report.execution_tape_recovery_proved) -and
            [string]$report.baseline_commit -eq [string]$attempt.baseline.master -and
            [string]$report.resolved_branch_tip -eq [string]$attempt.expected_tip -and
            [string]$report.merge_commit -match '^[0-9a-f]{40}$'
        )
    }
}

function Assert-WeatherClosureTasksQuiescent {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object[]]$DisableEvidence
    )

    $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    $intentContract = if (Test-Path -LiteralPath $intentPath -PathType Leaf) {
        Assert-WeatherIntegrationRegistrationIntent -AttemptContract $AttemptContract
    }
    else { $null }
    $attempt = $AttemptContract.Manifest
    # One successful complete Scheduler inventory is the absence proof for
    # both exact root tasks. A targeted SilentlyContinue lookup cannot
    # distinguish deletion from Scheduler/service failure.
    $schedulerSnapshot = @(Get-WeatherIntegrationScheduledTaskSnapshot)
    foreach ($spec in @(
        [pscustomobject]@{ Role = "suite"; Name = [string]$attempt.schedule.suite_task_name },
        [pscustomobject]@{ Role = "merge"; Name = [string]$attempt.schedule.merge_task_name }
    )) {
        $prior = @($DisableEvidence | Where-Object {
            [string]$_.task_name -eq [string]$spec.Name
        })
        if ($prior.Count -ne 1) {
            throw "Task-disable evidence is incomplete for exact attempt task: $($spec.Name)"
        }
        $matches = @($schedulerSnapshot | Where-Object {
            [string]$_.TaskName -ieq [string]$spec.Name -and
            [string]$_.TaskPath -ieq "\"
        })
        if (-not [bool]$prior[0].exists) {
            if ($matches.Count -ne 0) {
                throw "Attempt task appeared after the disable pass; closure refuses the race: $($spec.Name)"
            }
            continue
        }
        if ($matches.Count -ne 1) {
            throw "Attempt task no longer resolves exactly once after disable: $($spec.Name)"
        }
        $postDisableTask = $matches[0]
        if ($null -ne $intentContract) {
            Assert-WeatherIntegrationScheduledTaskObject `
                -Task $postDisableTask `
                -BindingEvidence $intentContract.Intent `
                -Role ([string]$spec.Role) | Out-Null
        }
        else {
            # Legacy attempts may predate the first-write intent. The disable
            # helper immediately above already rebound their action/principal
            # to the immutable registration receipt; this final complete
            # snapshot closes only the Ready -> Running state race.
            $postDisableTask = $matches[0]
        }
        if ([string]$postDisableTask.State -ne "Disabled") {
            # Disabling does not terminate an already-started instance. Refuse
            # to freeze ABANDONED evidence while an exact suite/merge action is
            # still Running (or in any other nonterminal state).
            throw "Attempt task is not terminal and Disabled after the disable pass: $($spec.Name) state=$($postDisableTask.State)"
        }
    }
}

function Assert-WeatherClosureNonIntegratedState {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $attempt = $AttemptContract.Manifest
    $root = Resolve-WeatherIntegrationPath -Path ([string]$attempt.repo_root)
    Assert-WeatherIntegrationOriginIdentity `
        -AttemptContract $AttemptContract `
        -Phase "retry-authorizing closure" | Out-Null
    $markerPath = Join-Path $root "data\alerts\quiet_window_merge_in_progress.json"
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        throw "This attempt has an active interrupted quiet-merge marker. Run boot/merge recovery to a terminal report before closure."
    }
    $mergeHeadPathOutput = @(& git -C $root rev-parse --git-path MERGE_HEAD)
    if ($LASTEXITCODE -ne 0 -or $mergeHeadPathOutput.Count -ne 1) {
        throw "Could not resolve MERGE_HEAD while classifying the attempt for closure."
    }
    $mergeHeadPath = ([string]$mergeHeadPathOutput[0]).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $root $mergeHeadPath
    }
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        throw "Production has an in-progress merge; ordinary FAIL closure is unsafe."
    }

    $originUrlProperty = $attempt.baseline.PSObject.Properties["origin_url"]
    $fetchRemote = if ($null -ne $originUrlProperty -and
        -not [string]::IsNullOrWhiteSpace([string]$originUrlProperty.Value)) {
        [string]$originUrlProperty.Value
    }
    else { "origin" }
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $root `
        -Arguments @(
            "fetch", "--no-tags", $fetchRemote,
            "refs/heads/master:refs/remotes/origin/master"
        ) `
        -Label "retry-authorizing closure origin/master refresh" | Out-Null

    $productionBranch = Invoke-WeatherClosureGitLine `
        -Root $root -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "the checked-out production branch"
    $headTip = (Invoke-WeatherClosureGitLine -Root $root -Arguments @("rev-parse", "HEAD") -Label "production HEAD").ToLowerInvariant()
    $masterTip = (Invoke-WeatherClosureGitLine -Root $root -Arguments @("rev-parse", "master") -Label "local master").ToLowerInvariant()
    $originMasterTip = (Invoke-WeatherClosureGitLine -Root $root -Arguments @("rev-parse", "origin/master") -Label "origin/master").ToLowerInvariant()
    & git -C $root merge-base --is-ancestor ([string]$attempt.expected_tip) $masterTip
    $masterAncestryExit = $LASTEXITCODE
    & git -C $root merge-base --is-ancestor ([string]$attempt.expected_tip) $originMasterTip
    $originAncestryExit = $LASTEXITCODE
    if ($masterAncestryExit -notin @(0, 1) -or $originAncestryExit -notin @(0, 1)) {
        throw "Could not classify source-tip ancestry while closing the attempt."
    }
    if ($productionBranch -ne "master" -or
        $headTip -ne [string]$attempt.baseline.master -or
        $masterTip -ne [string]$attempt.baseline.master -or
        $originMasterTip -ne [string]$attempt.baseline.origin_master -or
        $masterAncestryExit -eq 0 -or $originAncestryExit -eq 0) {
        throw "Production Git is no longer at this attempt's frozen baseline, so ordinary FAIL closure cannot prove that no integration mutation survived. branch=$productionBranch HEAD=$headTip master=$masterTip origin/master=$originMasterTip"
    }
    return [pscustomobject]@{
        Branch = $productionBranch
        Head = $headTip
        Master = $masterTip
        OriginMaster = $originMasterTip
        SourceInMaster = $false
        SourceInOrigin = $false
    }
}

if ([string]::IsNullOrWhiteSpace($Reason) -or [string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "Reason and ReviewReference are required to close an immutable attempt."
}
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$closurePath = [string]$manifest.evidence.closure_receipt
if (Test-Path -LiteralPath $closurePath) {
    throw "Immutable closure receipt already exists and will not be replaced: $closurePath"
}
$reconciliationPath = [string]$manifest.evidence.reconciliation_receipt
if (Test-Path -LiteralPath $reconciliationPath -PathType Leaf) {
    throw "A reconciliation receipt already terminally classified this attempt; closure cannot create a conflicting ABANDONED receipt."
}

$closureRepoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$terminalMutex = Enter-WeatherIntegrationControlMutex `
    -RepositoryRoot $closureRepoRoot `
    -LockLeaf "integration_attempt_terminal.lock" `
    -Owner "close_integration_attempt:$($manifest.attempt_id)"
if ($null -eq $terminalMutex) {
    throw "Another close/reconciliation owns the integration-attempt terminal mutex."
}
$productionMutationMutex = $null
try {
    if (Test-Path -LiteralPath $closurePath) {
        throw "Immutable closure receipt appeared before terminal-mutex acquisition and will not be replaced: $closurePath"
    }
    if (Test-Path -LiteralPath $reconciliationPath -PathType Leaf) {
        throw "A reconciliation receipt appeared before terminal-mutex acquisition; closure cannot create a conflicting ABANDONED receipt."
    }
    # quiet_window_merge owns this same OS-held file while it can mutate Git.
    # Closure is lightweight and therefore takes the mutex directly without
    # claiming heavy-work admission; it holds it through the immutable receipt.
    $productionMutationMutex = Enter-WeatherIntegrationControlMutex `
        -RepositoryRoot $closureRepoRoot `
        -LockLeaf "heavy_workload.lock" `
        -Owner "close_integration_attempt:$($manifest.attempt_id)"
    if ($null -eq $productionMutationMutex) {
        throw "A guarded merge or other production mutation owns the shared workload mutex; closure refuses to race it."
    }

$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
    $mergeReceipt = Read-WeatherIntegrationSharedJson -Path $mergeReceiptPath
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ([string]$mergeReceipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$mergeReceipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$mergeReceipt.manifest_path) -Right $contract.ManifestPath) -or
        [string]$mergeReceipt.manifest_sha256 -ne [string]$contract.ManifestSha256 -or
        [string]$mergeReceipt.source_tip -ne [string]$manifest.expected_tip -or
        [string]$mergeReceipt.branch_ref -ne [string]$manifest.branch_ref -or
        ($null -ne $originUrlProperty -and
            [string]$mergeReceipt.origin_url -cne [string]$originUrlProperty.Value) -or
        [string]$mergeReceipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$mergeReceipt.safety.credential_value_access_authorized -or
        [bool]$mergeReceipt.safety.live_exchange_mutation_authorized) {
        throw "Merge receipt exists but is malformed or not bound to this attempt; closure is unsafe."
    }
    if ([string]$mergeReceipt.status -in @("PASS", "MERGED_UNVERIFIED")) {
        throw "An attempt that reached production cannot be abandoned or retried."
    }
    if ([string]$mergeReceipt.status -ne "FAIL") {
        throw "Merge receipt has an unsupported terminal status; closure is unsafe."
    }
}

$quietReportContract = Read-WeatherClosureQuietReport -AttemptContract $contract
if ($null -ne $quietReportContract -and [bool]$quietReportContract.RecoveredMergeProved) {
    throw "Durable recovery evidence proves this attempt created a recovered integration commit. Do not close or retry it; use reviewed resume/reconciliation with quiet-report SHA256 $($quietReportContract.Sha256)."
}
$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$activeMarkerPath = Join-Path $repoRoot "data\alerts\quiet_window_merge_in_progress.json"
$activeMarker = $null
if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
    $activeMarker = Read-WeatherIntegrationSharedJson -Path $activeMarkerPath
    $originUrlProperty = $manifest.baseline.PSObject.Properties["origin_url"]
    if ([string]$activeMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        [string]$activeMarker.branch -ne [string]$manifest.branch_ref -or
        [string]$activeMarker.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$activeMarker.expected_baseline -ne [string]$manifest.baseline.master -or
        ($null -ne $originUrlProperty -and
            [string]$activeMarker.origin_url -cne [string]$originUrlProperty.Value)) {
        throw "A different or malformed quiet-merge recovery marker is active; closure cannot race it."
    }
}
# A missing terminal report is not evidence that a hard-killed integration
# left no Git mutation. Always classify current production Git.
$initialGitProof = Assert-WeatherClosureNonIntegratedState -AttemptContract $contract
$sourceInMaster = [bool]$initialGitProof.SourceInMaster
$sourceInOrigin = [bool]$initialGitProof.SourceInOrigin
$masterTip = [string]$initialGitProof.Master
$originMasterTip = [string]$initialGitProof.OriginMaster
$taskEvidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)
Assert-WeatherClosureTasksQuiescent `
    -AttemptContract $contract `
    -DisableEvidence $taskEvidence

# The Ready -> Running transition can race the first Git proof. Disabling a
# task does not stop an instance that already began, so only freeze ABANDONED
# after exact tasks are terminal+Disabled and the full marker/MERGE_HEAD/Git
# classification is immediately re-proved.
$postDisableGitProof = Assert-WeatherClosureNonIntegratedState -AttemptContract $contract
$postDisableQuietReport = Read-WeatherClosureQuietReport -AttemptContract $contract
if ($null -ne $postDisableQuietReport -and [bool]$postDisableQuietReport.RecoveredMergeProved) {
    throw "Recovered integration evidence appeared during task shutdown; closure refuses to classify the attempt ABANDONED."
}

# A task that was already starting can also emit terminal evidence after the
# first read. Re-read the canonical merge receipt immediately before closure.
if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
    $postDisableMergeReceipt = Read-WeatherIntegrationSharedJson -Path $mergeReceiptPath
    if ([string]$postDisableMergeReceipt.status -ne "FAIL" -or
        [string]$postDisableMergeReceipt.attempt_id -ne [string]$manifest.attempt_id -or
        [string]$postDisableMergeReceipt.manifest_sha256 -ne [string]$contract.ManifestSha256) {
        throw "Merge evidence appeared or changed during task shutdown; closure refuses to classify the attempt ABANDONED."
    }
}

$existingEvidence = New-Object System.Collections.Generic.List[object]
foreach ($path in @(
    (Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $contract),
    [string]$manifest.evidence.registration_receipt,
    [string]$manifest.evidence.preflight_log,
    [string]$manifest.evidence.full_suite_log,
    [string]$manifest.evidence.suite_receipt,
    [string]$manifest.evidence.quiet_merge_report,
    [string]$manifest.evidence.merge_receipt
)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $existingEvidence.Add([ordered]@{
            path = Resolve-WeatherIntegrationPath -Path $path
            sha256 = Get-WeatherIntegrationFileSha256 -Path $path
        })
    }
}
$registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $contract
$registrationReceiptPath = Resolve-WeatherIntegrationPath -Path ([string]$manifest.evidence.registration_receipt)
$registrationIntentSha256 = if (Test-Path -LiteralPath $registrationIntentPath -PathType Leaf) {
    Get-WeatherIntegrationFileSha256 -Path $registrationIntentPath
}
else { $null }
$registrationReceiptSha256 = if (Test-Path -LiteralPath $registrationReceiptPath -PathType Leaf) {
    Get-WeatherIntegrationFileSha256 -Path $registrationReceiptPath
}
else { $null }

$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptClosureReceiptSchema
    status = "FAIL"
    classification = "ABANDONED"
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    expected_tip = [string]$manifest.expected_tip
    closed_at_local = (Get-Date).ToString("o")
    reason = $Reason
    review_reference = $ReviewReference
    tasks = @($taskEvidence | ForEach-Object { $_ })
    post_disable_proof = [ordered]@{
        tasks_terminal_and_disabled = $true
        merge_head_absent = $true
        checked_out_branch = [string]$postDisableGitProof.Branch
        head = [string]$postDisableGitProof.Head
        master = [string]$postDisableGitProof.Master
        origin_master = [string]$postDisableGitProof.OriginMaster
        source_in_master = [bool]$postDisableGitProof.SourceInMaster
        source_in_origin = [bool]$postDisableGitProof.SourceInOrigin
    }
    registration_evidence = [ordered]@{
        registration_intent_path = $registrationIntentPath
        registration_intent_sha256 = $registrationIntentSha256
        registration_receipt_path = $registrationReceiptPath
        registration_receipt_sha256 = $registrationReceiptSha256
    }
    preserved_evidence = @($existingEvidence | ForEach-Object { $_ })
    safety = [ordered]@{
        authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $closurePath -Payload $receipt
}
finally {
    Exit-WeatherIntegrationControlMutex -Mutex $productionMutationMutex
    Exit-WeatherIntegrationControlMutex -Mutex $terminalMutex
}

Write-Host "Closed integration attempt $($manifest.attempt_id). Exact tasks are disabled and evidence is frozen."
Write-Host "A replacement attempt may bind this FAIL receipt: $closurePath"
