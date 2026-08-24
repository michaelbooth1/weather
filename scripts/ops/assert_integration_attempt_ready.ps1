# Final, fail-closed readiness assertion for a newly prepared v1 integration
# attempt. This script does not create or start tasks and does not mutate Git.

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
    [Parameter(Mandatory = $true)][datetime]$PublicationCheckedAtLocal,
    [Parameter(Mandatory = $true)][datetime]$RegistrationCheckedAtLocal,
    [Parameter(Mandatory = $true)][string]$ResultPath,
    [switch]$StagedDisabled
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_quiet_merge_preflight.ps1")

function Invoke-WeatherReadinessGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $rows = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Could not resolve $Label."
    }
    return ([string]$rows[0]).Trim()
}

$stage = "validate_paths"
$status = "FAIL"
$failure = $null
$intent = $null
$intentSha256 = $null
$contract = $null
$manifest = $null
$registration = $null
$remoteTip = $null
$liveMasterTip = $null
$topicBranch = $null
$taskEvidence = New-Object System.Collections.Generic.List[object]
$claimPath = $null
$claimSha256 = $null

try {
    $resolvedIntentPath = Resolve-WeatherIntegrationPath -Path $PreparationIntentPath
    $resolvedResultPath = Resolve-WeatherIntegrationPath -Path $ResultPath
    $expectedResultPath = Join-Path (Split-Path -Parent $resolvedIntentPath) "readiness-receipt.json"
    if (-not (Test-WeatherIntegrationPathEqual -Left $resolvedResultPath -Right $expectedResultPath)) {
        throw "ResultPath must be readiness-receipt.json beside the immutable preparation intent."
    }
    if (Test-Path -LiteralPath $resolvedResultPath) {
        throw "Immutable preparation result already exists and will not be replaced: $resolvedResultPath"
    }

    $stage = "validate_preparation_intent"
    $intentSha256 = Get-WeatherIntegrationFileSha256 -Path $resolvedIntentPath
    if ($intentSha256 -ne $ExpectedPreparationIntentSha256.ToLowerInvariant()) {
        throw "Preparation intent hash mismatch."
    }
    $intent = Read-WeatherIntegrationSharedJson -Path $resolvedIntentPath
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent `
        -Names @(
            "schema", "status", "attempt_id", "attempt_root", "preparation_root",
            "repo_root", "worktree_root", "branch_ref", "topic_branch",
            "expected_tip", "production_baseline", "schedule", "publication",
            "quiet_merge_preflight", "scripts", "authorization", "safety"
        ) `
        -Label "Integration preparation intent"
    if ([string]$intent.schema -ne "weather_integration_attempt_preparation_intent_v1" -or
        [string]$intent.status -ne "PREPARED") {
        throw "Preparation intent schema or status is unsupported."
    }
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.schedule `
        -Names @("checked_at_local", "suite_at_local", "merge_at_local", "minimum_lead_minutes") `
        -Label "Integration preparation schedule"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.publication `
        -Names @("remote", "remote_ref", "exact_non_force_refspec") `
        -Label "Integration preparation publication"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.authorization `
        -Names @(
            "review_reference", "repair_class", "repair_of_receipt_path",
            "repair_of_receipt_sha256"
        ) `
        -Label "Integration preparation authorization"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.safety `
        -Names @(
            "authority", "credential_value_access_authorized",
            "live_exchange_mutation_authorized"
        ) `
        -Label "Integration preparation safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $intent.safety `
        -Names @("credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Integration preparation safety boundary"
    $scheduleCheckedAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$intent.schedule.checked_at_local) `
        -Label "preparation schedule checked_at_local"
    $intentSuiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$intent.schedule.suite_at_local) `
        -Label "preparation schedule suite_at_local"
    $intentMergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$intent.schedule.merge_at_local) `
        -Label "preparation schedule merge_at_local"
    if ([int]$intent.schedule.minimum_lead_minutes -ne 10) {
        throw "Preparation intent does not bind the required ten-minute lead gate."
    }
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $intentSuiteAt `
        -MergeAtLocal $intentMergeAt `
        -Now $scheduleCheckedAt `
        -MinimumLeadMinutes 10 | Out-Null
    $publicationGate = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $intentSuiteAt `
        -MergeAtLocal $intentMergeAt `
        -Now $PublicationCheckedAtLocal `
        -MinimumLeadMinutes 10
    $registrationGate = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $intentSuiteAt `
        -MergeAtLocal $intentMergeAt `
        -Now $RegistrationCheckedAtLocal `
        -MinimumLeadMinutes 10
    if ($publicationGate.checked_at_local -lt $scheduleCheckedAt -or
        $registrationGate.checked_at_local -lt $publicationGate.checked_at_local) {
        throw "Preparation schedule gate timestamps are out of operational order."
    }

    $stage = "validate_manifest_and_claim"
    $contract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath $ManifestPath `
        -ExpectedSha256 $ExpectedManifestSha256
    $manifest = $contract.Manifest
    $authorizationPlan = Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $contract -AllowMissing
    if (-not $StagedDisabled -or -not [bool]$authorizationPlan.Required -or
        [bool]$authorizationPlan.Present) {
        throw "Composite readiness requires exact tasks staged disabled and no pre-existing execution authorization."
    }
    $expectedPreparationRoot = Resolve-WeatherIntegrationPath `
        -Path ($contract.AttemptRoot + ".preparation")
    $expectedIntentPath = Join-Path $expectedPreparationRoot "preparation-intent.json"
    if ([string]$manifest.attempt_id -ne [string]$intent.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left $resolvedIntentPath -Right $expectedIntentPath) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.repo_root) -Right ([string]$intent.repo_root)) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.worktree_root) -Right ([string]$intent.worktree_root)) -or
        [string]$manifest.branch_ref -cne [string]$intent.branch_ref -or
        [string]$manifest.expected_tip -cne [string]$intent.expected_tip -or
        [string]$manifest.schedule.suite_at_local -cne [string]$intent.schedule.suite_at_local -or
        [string]$manifest.schedule.merge_at_local -cne [string]$intent.schedule.merge_at_local -or
        [string]$manifest.baseline.master -cne [string]$intent.production_baseline -or
        -not (Test-WeatherIntegrationPathEqual -Left $contract.AttemptRoot -Right ([string]$intent.attempt_root)) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left $expectedPreparationRoot `
            -Right ([string]$intent.preparation_root)) -or
        [string]$manifest.authorization.review_reference -cne [string]$intent.authorization.review_reference -or
        [string]$manifest.authorization.repair_class -cne [string]$intent.authorization.repair_class) {
        throw "Manifest does not bind the immutable preparation intent."
    }
    if ([string]$intent.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$intent.safety.credential_value_access_authorized -or
        [bool]$intent.safety.live_exchange_mutation_authorized) {
        throw "Preparation intent violates the integration safety boundary."
    }
    $repairOfProperty = $manifest.authorization.PSObject.Properties["repair_of"]
    if ($null -ne $repairOfProperty -and $null -ne $repairOfProperty.Value) {
        # Assert-WeatherIntegrationAttemptManifest already calls this shared
        # semantic validator. Call it explicitly at the readiness boundary so
        # the claim cannot be reduced to mere file/hash existence here.
        Assert-WeatherIntegrationRepairClaim -AttemptContract $contract
        $claimPath = Resolve-WeatherIntegrationPath -Path ([string]$repairOfProperty.Value.claim_path)
        $claim = Read-WeatherIntegrationSharedJson -Path $claimPath
        if ([string]$claim.schema -ne $script:WeatherIntegrationAttemptSuccessorClaimSchema -or
            [string]$claim.status -ne "CLAIMED" -or
            [string]$claim.successor_attempt_id -ne [string]$manifest.attempt_id -or
            [string]$claim.successor_expected_tip -ne [string]$manifest.expected_tip -or
            [string]$claim.repair_class -ne [string]$manifest.authorization.repair_class -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$claim.successor_manifest_path) -Right $contract.ManifestPath) -or
            [string]$claim.successor_manifest_sha256 -ne $contract.ManifestSha256) {
            throw "Successor claim does not semantically bind this exact prepared attempt."
        }
        $claimSha256 = Get-WeatherIntegrationFileSha256 -Path $claimPath
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$intent.authorization.repair_of_receipt_path) `
                -Right ([string]$repairOfProperty.Value.receipt_path)) -or
            [string]$intent.authorization.repair_of_receipt_sha256 -ne
                [string]$repairOfProperty.Value.receipt_sha256) {
            throw "Preparation intent does not bind the successor's exact predecessor receipt."
        }
    }
    elseif (-not [string]::IsNullOrWhiteSpace(
            [string]$intent.authorization.repair_of_receipt_path
        ) -or -not [string]::IsNullOrWhiteSpace(
            [string]$intent.authorization.repair_of_receipt_sha256
        )) {
        throw "Initial preparation intent unexpectedly carries predecessor evidence."
    }

    $stage = "validate_preparation_scripts"
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $expectedScripts = [ordered]@{
        preparer = Join-Path $repoRoot "scripts\ops\prepare_integration_attempt.ps1"
        readiness = Join-Path $repoRoot "scripts\ops\assert_integration_attempt_ready.ps1"
        contract = Join-Path $repoRoot "scripts\ops\integration_attempt_contract.ps1"
        preparation_contract = Join-Path $repoRoot "scripts\ops\integration_attempt_preparation_contract.ps1"
        quiet_merge_preflight = Join-Path $repoRoot "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
        creator = Join-Path $repoRoot "scripts\ops\new_integration_attempt.ps1"
        registrar = Join-Path $repoRoot "scripts\ops\register_integration_attempt.ps1"
        activator = Join-Path $repoRoot "scripts\ops\activate_integration_attempt.ps1"
        closer = Join-Path $repoRoot "scripts\ops\close_integration_attempt.ps1"
    }
    foreach ($name in $expectedScripts.Keys) {
        $record = $intent.scripts.PSObject.Properties[[string]$name].Value
        $expectedPath = [string]$expectedScripts[$name]
        if ($null -eq $record -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$record.path) -Right $expectedPath) -or
            [string]$record.sha256 -ne (Get-WeatherIntegrationFileSha256 -Path $expectedPath)) {
            throw "Preparation script binding changed after intent freeze: $name"
        }
    }

    $stage = "validate_remote_topic"
    $topicBranch = Get-WeatherIntegrationTopicBranchName -BranchRef ([string]$manifest.branch_ref)
    if ($topicBranch -cne [string]$intent.topic_branch) {
        throw "Preparation intent topic branch disagrees with the manifest branch ref."
    }
    $remoteRef = "refs/heads/$topicBranch"
    $expectedRefspec = "$($manifest.expected_tip):$remoteRef"
    if ([string]$intent.publication.remote -ne "origin" -or
        [string]$intent.publication.remote_ref -cne $remoteRef -or
        [string]$intent.publication.exact_non_force_refspec -cne $expectedRefspec) {
        throw "Preparation publication intent does not bind the exact non-force topic refspec."
    }
    $remoteRows = @(& git -C $repoRoot ls-remote --heads origin $remoteRef)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query the live origin topic ref."
    }
    $remoteTip = Resolve-WeatherIntegrationRemoteTipRows `
        -Rows $remoteRows -ExpectedRemoteRef $remoteRef
    if ($remoteTip -ne [string]$manifest.expected_tip) {
        throw "Live origin topic tip does not match the immutable attempt."
    }
    $trackingTip = (Invoke-WeatherReadinessGitLine `
        -Root $repoRoot -Arguments @("rev-parse", [string]$manifest.branch_ref) `
        -Label "the refreshed remote-tracking topic ref").ToLowerInvariant()
    if ($trackingTip -ne [string]$manifest.expected_tip) {
        throw "Local remote-tracking topic ref does not match the live exact tip."
    }
    $liveMasterRows = @(& git -C $repoRoot ls-remote --heads origin "refs/heads/master")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query the live exact origin master ref."
    }
    $liveMasterTip = Resolve-WeatherIntegrationRemoteTipRows `
        -Rows $liveMasterRows -ExpectedRemoteRef "refs/heads/master"
    if ($liveMasterTip -ne [string]$manifest.baseline.master) {
        throw "Live origin master changed after the attempt baseline was frozen."
    }

    $stage = "validate_worktree_and_baseline"
    $baseline = Assert-WeatherIntegrationGitBaseline `
        -AttemptContract $contract -Phase "integration preparation readiness"
    $registered = $false
    $worktreeRows = @(& git -C $repoRoot worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not enumerate registered worktrees."
    }
    foreach ($row in $worktreeRows) {
        if ([string]$row -like "worktree *") {
            $candidate = ([string]$row).Substring("worktree ".Length)
            if (Test-WeatherIntegrationPathEqual `
                -Left $candidate -Right ([string]$manifest.worktree_root)) {
                $registered = $true
                break
            }
        }
    }
    if (-not $registered) {
        throw "The exact suite worktree is no longer registered."
    }
    $worktreeTip = (Invoke-WeatherReadinessGitLine `
        -Root ([string]$manifest.worktree_root) -Arguments @("rev-parse", "HEAD") `
        -Label "the suite worktree HEAD").ToLowerInvariant()
    $worktreeDirty = @(& git -C ([string]$manifest.worktree_root) status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $worktreeTip -ne [string]$manifest.expected_tip -or
        $worktreeDirty.Count -ne 0) {
        throw "The suite worktree is not clean at the exact immutable tip."
    }

    $stage = "validate_registration_evidence"
    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $contract -RequirePass
    Assert-WeatherIntegrationRequiredProperties `
        -Object $registration.Receipt `
        -Names @(
            "scheduler_boundary_checked_at_local",
            "minimum_suite_lead_minutes", "staged_disabled"
        ) `
        -Label "Prepared-attempt registration receipt"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $registration.Receipt -Names @("staged_disabled") `
        -Label "Prepared-attempt registration receipt"
    $schedulerBoundaryCheckedAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$registration.Receipt.scheduler_boundary_checked_at_local) `
        -Label "registration scheduler boundary"
    if (-not [bool]$registration.Receipt.staged_disabled -or
        [int]$registration.Receipt.minimum_suite_lead_minutes -ne 10 -or
        $schedulerBoundaryCheckedAt -lt $RegistrationCheckedAtLocal) {
        throw "Registration receipt does not prove disabled staging at the preparer's ten-minute Scheduler boundary."
    }
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $intentSuiteAt `
        -MergeAtLocal $intentMergeAt `
        -Now $schedulerBoundaryCheckedAt `
        -MinimumLeadMinutes 10 | Out-Null

    $stage = "validate_absent_runtime_evidence"
    foreach ($evidencePath in @(
        [string]$manifest.evidence.preflight_log,
        [string]$manifest.evidence.full_suite_log,
        [string]$manifest.evidence.suite_receipt,
        [string]$manifest.evidence.merge_receipt,
        [string]$manifest.evidence.quiet_merge_report,
        [string]$manifest.evidence.closure_receipt,
        [string]$manifest.evidence.recovery_dispatch,
        [string]$manifest.evidence.reconciliation_receipt
    )) {
        if (Test-Path -LiteralPath $evidencePath) {
            throw "Runtime or terminal evidence already exists; this attempt is not freshly armed: $evidencePath"
        }
    }

    $stage = "validate_future_task_bindings"
    $now = Get-Date
    $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.suite_at_local) -Label "suite_at_local"
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value ([string]$manifest.schedule.merge_at_local) -Label "merge_at_local"
    if ($suiteAt -le $now -or $mergeAt -le $now) {
        throw "Both exact integration task triggers must still be in the future."
    }
    foreach ($role in @("suite", "merge")) {
        $binding = Assert-WeatherIntegrationScheduledTaskBinding `
            -AttemptContract $contract `
            -Role $role `
            -BindingEvidence $registration.Intent `
            -IncludeTaskInfo
        if ([string]$binding.Task.State -ne "Disabled" -or
            [bool]$binding.Task.Settings.Enabled) {
            throw "$role task is not exactly staged Disabled."
        }
        $roleAt = if ($role -eq "suite") { $suiteAt } else { $mergeAt }
        if ($null -ne $binding.Info -and
            [datetime]$binding.Info.LastRunTime -ge $roleAt.Date) {
            throw "$role task already has a run on its frozen trigger date."
        }
        $nextRunProperty = if ($null -eq $binding.Info) {
            $null
        }
        else { $binding.Info.PSObject.Properties["NextRunTime"] }
        if ($null -ne $nextRunProperty -and $null -ne $nextRunProperty.Value -and
            [datetime]$nextRunProperty.Value -ne $roleAt) {
            throw "$role disabled task exposes a NextRunTime that differs from its exact bound trigger."
        }
        $taskEvidence.Add([ordered]@{
            role = $role
            task_name = [string]$binding.Task.TaskName
            state = [string]$binding.Task.State
            enabled = [bool]$binding.Task.Settings.Enabled
            trigger_at_local = $roleAt.ToString("o")
            next_run_time = if ($null -eq $nextRunProperty -or
                $null -eq $nextRunProperty.Value) { $null } else {
                ([datetime]$nextRunProperty.Value).ToString("o")
            }
            last_run_time = if ($null -eq $binding.Info) { $null } else {
                ([datetime]$binding.Info.LastRunTime).ToString("o")
            }
            last_task_result = if ($null -eq $binding.Info) { $null } else {
                [int]$binding.Info.LastTaskResult
            }
        })
    }

    $stage = "validate_final_schedule_reserve"
    $now = Get-Date
    Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $suiteAt `
        -MergeAtLocal $mergeAt `
        -Now $now `
        -MinimumLeadMinutes 5 | Out-Null

    $stage = "validate_final_schedule_collisions"
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $suiteAt `
        -MergeAtLocal $mergeAt `
        -AttemptId ([string]$manifest.attempt_id)

    $stage = "validate_final_quiet_merge_preconditions"
    $finalQuietMergePreflight = Assert-WeatherIntegrationQuietMergePreconditions `
        -RepositoryRoot $repoRoot
    if ([string]$finalQuietMergePreflight.one_shot_push_task_xml_sha256 -ne
            [string]$intent.quiet_merge_preflight.one_shot_push_task_xml_sha256) {
        throw "WeatherOneShotPush changed after the immutable preparation intent was frozen."
    }

    $stage = "write_ready_receipt"
    $receipt = [ordered]@{
        schema = "weather_integration_attempt_readiness_receipt_v1"
        status = "PASS"
        stage = "READY"
        checked_at_local = (Get-Date).ToString("o")
        attempt_id = [string]$manifest.attempt_id
        preparation_intent_path = $resolvedIntentPath
        preparation_intent_sha256 = $intentSha256
        manifest_path = $contract.ManifestPath
        manifest_sha256 = $contract.ManifestSha256
        branch_ref = [string]$manifest.branch_ref
        topic_branch = $topicBranch
        expected_tip = [string]$manifest.expected_tip
        schedule = [ordered]@{
            initial_checked_at_local = $scheduleCheckedAt.ToString("o")
            publication_checked_at_local = $publicationGate.checked_at_local.ToString("o")
            registration_checked_at_local = $registrationGate.checked_at_local.ToString("o")
            suite_at_local = $suiteAt.ToString("o")
            merge_at_local = $mergeAt.ToString("o")
            minimum_lead_minutes = 10
            minimum_final_reserve_minutes = 5
            readiness_checked_at_local = $now.ToString("o")
        }
        baseline = [ordered]@{
            branch = [string]$baseline.Branch
            head = [string]$baseline.Head
            master = [string]$baseline.Master
            origin_master = [string]$baseline.OriginMaster
        }
        worktree = [ordered]@{
            root = [string]$manifest.worktree_root
            registered = $registered
            clean = $true
            tip = $worktreeTip
        }
        remote = [ordered]@{
            name = "origin"
            ref = "refs/heads/$topicBranch"
            tip = $remoteTip
            remote_tracking_ref = [string]$manifest.branch_ref
            remote_tracking_tip = $trackingTip
            live_master_tip = $liveMasterTip
        }
        successor_claim = [ordered]@{
            required = ($null -ne $claimPath)
            path = $claimPath
            sha256 = $claimSha256
        }
        registration = [ordered]@{
            intent_path = $registration.IntentPath
            intent_sha256 = $registration.IntentSha256
            receipt_path = $registration.ReceiptPath
            receipt_sha256 = $registration.ReceiptSha256
        }
        execution_authorization = [ordered]@{
            path = [string]$authorizationPlan.Path
            sha256 = [string]$authorizationPlan.Sha256
            created_after_readiness = $true
        }
        tasks = @($taskEvidence | ForEach-Object { $_ })
        quiet_merge_preflight = $finalQuietMergePreflight
        failure = $null
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson -Path $resolvedResultPath -Payload $receipt
    # This exact manifest-bound PASS token is the only authorization the two
    # wrappers accept. It is created after every readiness check while both
    # Scheduler tasks are still disabled, so a process kill cannot expose an
    # unchecked runnable attempt.
    Write-WeatherIntegrationImmutableJson `
        -Path ([string]$authorizationPlan.Path) `
        -Payload $authorizationPlan.Payload
    $authorization = Assert-WeatherIntegrationPreparationExecutionAuthorization `
        -AttemptContract $contract
    if (-not [bool]$authorization.Present -or
        [string]$authorization.Sha256 -ne [string]$authorizationPlan.Sha256) {
        throw "Final execution authorization did not match the immutable readiness plan."
    }
    $status = "PASS"
}
catch {
    $failure = $_.Exception.Message
}

if ($status -ne "PASS") {
    Write-Host "Integration readiness failed at stage '$stage'."
    exit 1
}

$finalReceipt = Read-WeatherIntegrationSharedJson -Path $resolvedResultPath
if ([string]$finalReceipt.status -ne "PASS" -or
    [string]$finalReceipt.manifest_sha256 -ne $ExpectedManifestSha256.ToLowerInvariant()) {
    Write-Host "Integration readiness failed at stage 'verify_ready_receipt'."
    exit 1
}
$finalReceipt | ConvertTo-Json -Depth 10 -Compress
exit 0
