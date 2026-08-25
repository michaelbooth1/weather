# Enable a composite-prepared integration attempt only after its exact,
# manifest-bound preparation PASS authorization exists. This script does not
# start either task and carries no credential or exchange authority.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][string]$PreparationIntentPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPreparationIntentSha256,
    [Parameter(Mandatory = $true)][string]$ReadinessReceiptPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedReadinessReceiptSha256,
    [Parameter(Mandatory = $true)][string]$ResultPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_quiet_merge_preflight.ps1")

$status = "FAIL"
$stage = "validate_inputs"
$failure = $null
$contract = $null
$authorization = $null
$passReceipt = $null
$terminalMutex = $null
$taskEvidence = New-Object System.Collections.Generic.List[object]
$disableEvidence = @()

try {
    $contract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath $ManifestPath `
        -ExpectedSha256 $ExpectedManifestSha256
    Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract
    $manifest = $contract.Manifest
    $terminalMutex = Enter-WeatherIntegrationControlMutex `
        -RepositoryRoot ([string]$manifest.repo_root) `
        -LockLeaf "integration_attempt_terminal.lock" `
        -Owner "activate_integration_attempt:$($manifest.attempt_id)"
    if ($null -eq $terminalMutex) {
        throw "Another registrar/close/reconciliation owns the integration-attempt terminal mutex."
    }
    Assert-WeatherIntegrationAttemptNotTerminal `
        -AttemptContract $contract -Operation "Integration-attempt activation"
    $expectedPreparationRoot = Resolve-WeatherIntegrationPath -Path (
        $contract.AttemptRoot + ".preparation"
    )
    $resolvedIntentPath = Resolve-WeatherIntegrationPath -Path $PreparationIntentPath
    $resolvedReadinessReceiptPath = Resolve-WeatherIntegrationPath -Path $ReadinessReceiptPath
    $resolvedResultPath = Resolve-WeatherIntegrationPath -Path $ResultPath
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedIntentPath `
            -Right (Join-Path $expectedPreparationRoot "preparation-intent.json")) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedReadinessReceiptPath `
            -Right (Join-Path $expectedPreparationRoot "readiness-receipt.json")) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedResultPath `
            -Right (Join-Path $expectedPreparationRoot "preparation-receipt.json"))) {
        throw "Activation evidence paths are not canonical for this exact attempt."
    }
    if (Test-Path -LiteralPath $resolvedResultPath) {
        throw "Immutable activation receipt already exists and will not be replaced: $resolvedResultPath"
    }
    if ((Get-WeatherIntegrationFileSha256 -Path $resolvedIntentPath) -ne
            $ExpectedPreparationIntentSha256.ToLowerInvariant()) {
        throw "Activation preparation-intent hash mismatch."
    }
    if ((Get-WeatherIntegrationFileSha256 -Path $resolvedReadinessReceiptPath) -ne
            $ExpectedReadinessReceiptSha256.ToLowerInvariant()) {
        throw "Activation readiness-receipt hash mismatch."
    }
    $readinessReceipt = Read-WeatherIntegrationSharedJson -Path $resolvedReadinessReceiptPath
    if ([string]$readinessReceipt.schema -ne
            "weather_integration_attempt_readiness_receipt_v1" -or
        [string]$readinessReceipt.status -ne "PASS" -or
        [string]$readinessReceipt.stage -ne "READY" -or
        [string]$readinessReceipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$readinessReceipt.manifest_path) `
            -Right $contract.ManifestPath) -or
        [string]$readinessReceipt.manifest_sha256 -ne $contract.ManifestSha256 -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$readinessReceipt.preparation_intent_path) `
            -Right $resolvedIntentPath) -or
        [string]$readinessReceipt.preparation_intent_sha256 -ne
            $ExpectedPreparationIntentSha256.ToLowerInvariant() -or
        [string]$readinessReceipt.remote.origin_url -cne
            [string]$manifest.baseline.origin_url) {
        throw "Activation requires the exact immutable preparation READY receipt."
    }
    $authorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $contract
    if (-not [bool]$authorization.Required -or -not [bool]$authorization.Present) {
        throw "Activation requires the exact manifest-bound preparation PASS authorization."
    }
    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $contract -RequirePass
    $stagedProperty = $registration.Receipt.PSObject.Properties["staged_disabled"]
    if ($null -eq $stagedProperty -or $stagedProperty.Value -isnot [bool] -or
        -not [bool]$stagedProperty.Value) {
        throw "Activation requires a PASS registration receipt proving disabled staging."
    }

    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) -Label "suite_at_local"
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.merge_at_local) -Label "merge_at_local"
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suiteAt -MergeAtLocal $mergeAt `
        -Now (Get-Date) -MinimumLeadMinutes 5 | Out-Null

    $stage = "revalidate_mutable_readiness"
    $activationNow = [DateTimeOffset]::Now
    $readinessCheckedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$readinessReceipt.checked_at_local) `
        -Label "readiness checked_at_local"
    if ($readinessCheckedAt -gt $activationNow -or
        ($activationNow - $readinessCheckedAt) -gt
            [TimeSpan]::FromMinutes(2)) {
        throw "Readiness receipt is older than the two-minute activation transaction boundary."
    }
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    Assert-WeatherIntegrationOriginIdentity `
        -AttemptContract $contract -Phase "integration activation" | Out-Null
    $topicBranch = Get-WeatherIntegrationTopicBranchName `
        -BranchRef ([string]$manifest.branch_ref)
    $topicRemoteRef = "refs/heads/$topicBranch"
    $liveTopicTip = Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $repoRoot -ExpectedUrl ([string]$manifest.baseline.origin_url) `
        -RemoteRef $topicRemoteRef `
        -Label "activation live canonical origin topic query"
    if ($liveTopicTip -ne [string]$manifest.expected_tip) {
        throw "Live origin topic changed after final readiness."
    }
    $liveMasterTip = Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $repoRoot -ExpectedUrl ([string]$manifest.baseline.origin_url) `
        -RemoteRef "refs/heads/master" `
        -Label "activation live canonical origin/master query"
    if ($liveMasterTip -ne [string]$manifest.baseline.master) {
        throw "Live origin master changed after final readiness."
    }
    Assert-WeatherIntegrationGitBaseline `
        -AttemptContract $contract -Phase "integration activation" | Out-Null
    $registeredWorktree = $false
    $worktreeRows = @(& git -C $repoRoot worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Activation could not enumerate registered worktrees."
    }
    foreach ($worktreeRow in $worktreeRows) {
        if ([string]$worktreeRow -like "worktree *" -and
            (Test-WeatherIntegrationPathEqual `
                -Left ([string]$worktreeRow).Substring("worktree ".Length) `
                -Right ([string]$manifest.worktree_root))) {
            $registeredWorktree = $true
            break
        }
    }
    $worktreeTipRows = @(& git -C ([string]$manifest.worktree_root) `
        rev-parse HEAD)
    $worktreeTipExit = $LASTEXITCODE
    $worktreeStatusRows = @(& git -C ([string]$manifest.worktree_root) `
        status --porcelain)
    $worktreeStatusExit = $LASTEXITCODE
    if (-not $registeredWorktree -or $worktreeTipRows.Count -ne 1 -or
        ([string]$worktreeTipRows[0]).Trim().ToLowerInvariant() -ne
            [string]$manifest.expected_tip -or
        $worktreeStatusRows.Count -ne 0 -or
        $worktreeTipExit -ne 0 -or $worktreeStatusExit -ne 0) {
        throw "Suite worktree changed after final readiness."
    }
    $currentQuietPreflight = Assert-WeatherIntegrationQuietMergePreconditions `
        -RepositoryRoot $repoRoot
    if ([string]$currentQuietPreflight.one_shot_push_task_xml_sha256 -ne
        [string]$readinessReceipt.quiet_merge_preflight.one_shot_push_task_xml_sha256) {
        throw "Quiet-merge prerequisites changed after final readiness."
    }

    foreach ($runtimePath in @(
        [string]$manifest.evidence.preflight_log,
        [string]$manifest.evidence.full_suite_log,
        [string]$manifest.evidence.suite_receipt,
        [string]$manifest.evidence.merge_receipt,
        [string]$manifest.evidence.quiet_merge_report,
        [string]$manifest.evidence.closure_receipt,
        [string]$manifest.evidence.recovery_dispatch,
        [string]$manifest.evidence.reconciliation_receipt
    )) {
        if (Test-Path -LiteralPath $runtimePath) {
            throw "Runtime or terminal evidence exists before activation: $runtimePath"
        }
    }

    $stage = "validate_disabled_bindings"
    foreach ($role in @("suite", "merge")) {
        $binding = Assert-WeatherIntegrationScheduledTaskBinding `
            -AttemptContract $contract -Role $role `
            -BindingEvidence $registration.Intent -IncludeTaskInfo
        if ([string]$binding.Task.State -ne "Disabled" -or
            [bool]$binding.Task.Settings.Enabled) {
            throw "$role task is not exactly staged Disabled at activation."
        }
        $roleAt = if ($role -eq "suite") { $suiteAt } else { $mergeAt }
        if ($null -ne $binding.Info -and
            [datetime]$binding.Info.LastRunTime -ge $roleAt.Date) {
            throw "$role task already ran on its frozen trigger date."
        }
    }

    $stage = "activation_boundary"
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suiteAt -MergeAtLocal $mergeAt `
        -Now (Get-Date) -MinimumLeadMinutes 5 | Out-Null
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suiteAt -MergeAtLocal $mergeAt `
        -AttemptId ([string]$manifest.attempt_id) `
        -RepositoryRoot $repoRoot

    # Merge is enabled first because it remains fail-closed on a missing suite
    # PASS receipt. The five-minute reserve makes the two local mutations a
    # bounded activation transaction, and the execution authorization already
    # exists before either task can become runnable.
    $stage = "enable_merge"
    Enable-ScheduledTask `
        -TaskName ([string]$manifest.schedule.merge_task_name) `
        -TaskPath "\" -ErrorAction Stop | Out-Null
    $stage = "enable_suite"
    Enable-ScheduledTask `
        -TaskName ([string]$manifest.schedule.suite_task_name) `
        -TaskPath "\" -ErrorAction Stop | Out-Null

    $stage = "reattest_enabled_bindings"
    foreach ($role in @("suite", "merge")) {
        $binding = Assert-WeatherIntegrationScheduledTaskBinding `
            -AttemptContract $contract -Role $role `
            -BindingEvidence $registration.Intent -IncludeTaskInfo
        if ([string]$binding.Task.State -ne "Ready" -or
            -not [bool]$binding.Task.Settings.Enabled) {
            throw "$role task did not become exactly enabled and Ready."
        }
        $roleAt = if ($role -eq "suite") { $suiteAt } else { $mergeAt }
        if ($null -eq $binding.Info -or $null -eq $binding.Info.NextRunTime -or
            [datetime]$binding.Info.NextRunTime -ne $roleAt) {
            throw "$role task NextRunTime does not equal its exact frozen trigger."
        }
        $taskEvidence.Add([ordered]@{
            role = $role
            task_name = [string]$binding.Task.TaskName
            task_path = [string]$binding.Task.TaskPath
            state = [string]$binding.Task.State
            enabled = [bool]$binding.Task.Settings.Enabled
            trigger_at_local = $roleAt.ToString("o")
            next_run_time = ([datetime]$binding.Info.NextRunTime).ToString("o")
            last_run_time = ([datetime]$binding.Info.LastRunTime).ToString("o")
            last_task_result = [int]$binding.Info.LastTaskResult
        })
    }
    $stage = "write_activation_receipt"
    $passReceipt = [ordered]@{
        schema = "weather_integration_attempt_preparation_receipt_v1"
        status = "PASS"
        stage = "READY"
        activated_at_local = (Get-Date).ToString("o")
        attempt_id = [string]$manifest.attempt_id
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        preparation_intent_path = $resolvedIntentPath
        preparation_intent_sha256 = $ExpectedPreparationIntentSha256.ToLowerInvariant()
        branch_ref = [string]$manifest.branch_ref
        expected_tip = [string]$manifest.expected_tip
        origin_url = [string]$manifest.baseline.origin_url
        readiness_receipt_path = $resolvedReadinessReceiptPath
        readiness_receipt_sha256 = $ExpectedReadinessReceiptSha256.ToLowerInvariant()
        execution_authorization_path = [string]$authorization.Path
        execution_authorization_sha256 = [string]$authorization.Sha256
        tasks = @($taskEvidence | ForEach-Object { $_ })
        rollback_tasks = @()
        failure = $null
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson `
        -Path $resolvedResultPath -Payload $passReceipt
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
    if ($null -ne $contract) {
        try {
            $disableEvidence = @(
                Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract
            )
            if (@($disableEvidence | Where-Object {
                    [bool]$_.exists -and -not [bool]$_.disabled
                }).Count -gt 0) {
                throw "Exact attempt tasks were not both disabled."
            }
        }
        catch {
            $failure = "$failure; activation rollback failed: $($_.Exception.Message)"
        }
    }
}
finally {
    Exit-WeatherIntegrationControlMutex -Mutex $terminalMutex
}

if ($status -ne "PASS") {
    Write-Host "Integration activation failed at stage '$stage'."
    exit 1
}

$passReceipt | ConvertTo-Json -Depth 10 -Compress
exit 0
