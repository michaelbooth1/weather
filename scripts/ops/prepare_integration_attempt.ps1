# Publish one exact reviewed topic tip, create its immutable v2 attempt, register
# the two canonical one-shots, and prove the complete attempt is still ready.
# Run this entry point only in the user's interactive credential context and
# only with explicit authority for its topic push, disabled Scheduler
# registration, and the later activation of that exact task pair.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$AttemptRoot,
    [Parameter(Mandatory = $true)][string]$AttemptId,
    [Parameter(Mandatory = $true)][string]$BranchRef,
    [Parameter(Mandatory = $true)][string]$WorktreeRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$ExpectedTip,
    [Parameter(Mandatory = $true)][datetime]$SuiteAtLocal,
    [Parameter(Mandatory = $true)][datetime]$MergeAtLocal,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [ValidateSet("initial", "retry_unchanged", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
    [string]$RepairClass = "initial",
    [string]$RepairOfReceiptPath = "",
    [switch]$RequireLiveSdkContract,
    [Parameter(Mandatory = $true)]
    [ValidateSet("AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION")]
    [string]$PublicationConfirmation,
    [Parameter(Mandatory = $true)]
    [ValidateSet("AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION")]
    [string]$SchedulerConfirmation,
    [Parameter(Mandatory = $true)]
    [ValidateSet("AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION")]
    [string]$ActivationConfirmation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PublicationConfirmation -cne
        "AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION") {
    throw "PublicationConfirmation must use the exact case-sensitive authorization literal."
}
if ($SchedulerConfirmation -cne
        "AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION") {
    throw "SchedulerConfirmation must use the exact case-sensitive authorization literal."
}
if ($ActivationConfirmation -cne
        "AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION") {
    throw "ActivationConfirmation must use the exact case-sensitive authorization literal."
}

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_quiet_merge_preflight.ps1")
. (Join-Path $PSScriptRoot "training_window_contract.ps1")
. (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1")

function Invoke-WeatherPreparationGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments $Arguments -Label $Label
    $rows = @($query.StdoutLines)
    if ($rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Could not resolve $Label."
    }
    return ([string]$rows[0]).Trim()
}

function Get-WeatherPreparationRemoteTip {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$OriginUrl,
        [Parameter(Mandatory = $true)][string]$RemoteRef,
        [switch]$AllowMissing
    )

    return Get-WeatherIntegrationCanonicalRemoteTip `
        -Root $Root -ExpectedUrl $OriginUrl -RemoteRef $RemoteRef `
        -AllowMissing:$AllowMissing -Label "exact canonical origin ref query"
}

function Get-WeatherPrearmingRunObservation {
    param(
        [Parameter(Mandatory = $true)][object]$ChildResult,
        [Parameter(Mandatory = $true)][string]$Mode,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 1000000)][int]$ExpectedTestFileCount,
        [Parameter(Mandatory = $true)]
        [ValidateRange(0, 100000)][int]$ExpectedChunkCount,
        [Parameter(Mandatory = $true)][datetimeoffset]$StartedAt,
        [Parameter(Mandatory = $true)][datetimeoffset]$CompletedAt
    )

    $resolvedLogPath = Resolve-WeatherIntegrationPath -Path $LogPath
    $logSha256 = $null
    $verdict = $null
    $weatherImportPath = $null
    $weatherImportSha256 = $null
    $testResults = $null
    $evidenceValidationError = $null
    if (Test-Path -LiteralPath $resolvedLogPath -PathType Leaf) {
        $logSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $resolvedLogPath -MaximumBytes 67108864 -ContentType Text
        $logSha256 = [string]$logSnapshot.Sha256
        $logText = [string]$logSnapshot.Text
        $verdictMatches = [regex]::Matches(
            $logText,
            '(?m)^.*?  (?<verdict>VERDICT: .+?)\r?$'
        )
        if ($verdictMatches.Count -eq 1) {
            $verdict = [string]$verdictMatches[0].Groups["verdict"].Value
        }
        else {
            $evidenceValidationError = (
                "Expected exactly one terminal verdict; found " +
                "$($verdictMatches.Count)."
            )
        }
        $importMatches = [regex]::Matches(
            $logText,
            '(?m)^.*?  weather_import=(?<path>.+?) weather_import_sha256=(?<sha>[0-9a-f]{64})\r?$'
        )
        if ($importMatches.Count -eq 1) {
            $weatherImportPath = [string]$importMatches[0].Groups["path"].Value
            $weatherImportSha256 = [string]$importMatches[0].Groups["sha"].Value
        }
        else {
            $importError = "Expected exactly one weather import binding; found $($importMatches.Count)."
            $evidenceValidationError = if ($null -eq $evidenceValidationError) {
                $importError
            } else { "$evidenceValidationError $importError" }
        }
        try {
            $effectiveTestFileCount = $ExpectedTestFileCount
            $effectiveChunkCount = $ExpectedChunkCount
            if ($effectiveTestFileCount -eq 0 -or $effectiveChunkCount -eq 0) {
                if ($effectiveTestFileCount -ne 0 -or $effectiveChunkCount -ne 0) {
                    throw "Expected suite plan must provide both counts or derive both from the immutable log."
                }
                $declaredPlan = Get-WeatherIntegrationSuiteLogDeclaredPlan `
                    -Path $resolvedLogPath -EvidenceSnapshot $logSnapshot
                $effectiveTestFileCount = [int]$declaredPlan.Files
                $effectiveChunkCount = [int]$declaredPlan.Chunks
            }
            $testResults = Get-WeatherIntegrationSuiteEvidenceSummary `
                -Path $resolvedLogPath `
                -ExpectedChunkCount $effectiveChunkCount `
                -ExpectedPlannedFiles $effectiveTestFileCount `
                -EvidenceSnapshot $logSnapshot `
                -RequireRuntimeFingerprint
        }
        catch {
            $summaryError = [string]$_.Exception.Message
            $evidenceValidationError = if ($null -eq $evidenceValidationError) {
                $summaryError
            } else { "$evidenceValidationError $summaryError" }
            if ($evidenceValidationError.Length -gt 1024) {
                $evidenceValidationError = $evidenceValidationError.Substring(0, 1024)
            }
        }
    }
    else { $evidenceValidationError = "Required bounded-suite log is missing." }
    return [ordered]@{
        mode = $Mode
        log_path = $resolvedLogPath
        log_sha256 = $logSha256
        exit_code = [int]$ChildResult.ExitCode
        verdict = $verdict
        weather_import_path = $weatherImportPath
        weather_import_sha256 = $weatherImportSha256
        test_results = $testResults
        evidence_validation_error = $evidenceValidationError
        started_at_local = $StartedAt.ToString("o")
        completed_at_local = $CompletedAt.ToString("o")
        duration_seconds = [math]::Round(($CompletedAt - $StartedAt).TotalSeconds, 3)
    }
}

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$WorktreeRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
$AttemptRoot = Resolve-WeatherIntegrationPath -Path $AttemptRoot
$ExpectedTip = $ExpectedTip.ToLowerInvariant()
$preparationRoot = Resolve-WeatherIntegrationPath -Path ($AttemptRoot + ".preparation")
$intentPath = Join-Path $preparationRoot "preparation-intent.json"
$resultPath = Join-Path $preparationRoot "preparation-receipt.json"
$readinessResultPath = Join-Path $preparationRoot "readiness-receipt.json"
$qualificationReceiptPath = Join-Path $preparationRoot "prearming-qualification-receipt.json"
$qualificationPreflightLogPath = Join-Path $preparationRoot "prearming-integration-preflight.log"
$qualificationFullSuiteLogPath = Join-Path $preparationRoot "prearming-full-suite.log"
$creatorPreflightPlanPath = Join-Path $preparationRoot "creator-preflight-plan.json"
$stage = "validate_identity"
$status = "FAIL"
$failure = $null
$intent = $null
$intentSha256 = $null
$manifestPath = Join-Path $AttemptRoot "manifest.json"
$manifestSha256 = $null
$remoteTipBefore = $null
$remoteTipAfter = $null
$trackingTip = $null
$remoteLookupCompleted = $false
$pushAttempted = $false
$pushPerformed = $false
$failureStage = $null
$closureRequired = $false
$closureAttempted = $false
$closureStatus = "NOT_REQUIRED"
$closureReceiptPath = $null
$closureReceiptSha256 = $null
$closureFailure = $null
$failureReceiptWritten = $false
$preparationMutex = $null
$originUrl = $null
$qualificationReceiptSha256 = $null
$qualificationStatus = "NOT_RUN"
$creatorPreflightStatus = "NOT_RUN"
$creatorPreflightPlanSha256 = $null
$primaryError = $null

try {
    if ($AttemptId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
        throw "AttemptId must contain 1-48 safe task-name characters."
    }
    if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
        throw "ReviewReference is required."
    }
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        throw "Repository root is missing: $RepoRoot"
    }
    if (-not (Test-Path -LiteralPath $WorktreeRoot -PathType Container)) {
        throw "Suite worktree is missing: $WorktreeRoot"
    }
    Assert-WeatherIntegrationGitControlSafety `
        -RepositoryRoots @($RepoRoot, $WorktreeRoot)
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $RepoRoot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -SuiteAtLocal $SuiteAtLocal | Out-Null
    $attemptParent = Split-Path -Parent $AttemptRoot
    if (-not (Test-Path -LiteralPath $attemptParent -PathType Container)) {
        throw "AttemptRoot parent directory does not exist: $attemptParent"
    }
    if (Test-Path -LiteralPath $AttemptRoot) {
        throw "AttemptRoot already exists and will not be reused: $AttemptRoot"
    }
    if (Test-Path -LiteralPath $preparationRoot) {
        throw "Preparation evidence root already exists and will not be reused: $preparationRoot"
    }
    New-Item -ItemType Directory -Path $preparationRoot -ErrorAction Stop | Out-Null
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $SuiteAtLocal -RequirePreparationRoot | Out-Null

    # This is deliberately the first operational gate. No remote publication
    # is attempted unless both triggers are credible and suite retains >=10m.
    $stage = "validate_schedule"
    $schedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $SuiteAtLocal `
        -MergeAtLocal $MergeAtLocal `
        -Now (Get-WeatherIntegrationScheduleLocalNow) `
        -MinimumLeadMinutes 10
    $qualificationWindow = Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal $schedule.suite_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow)
    $plannedQualificationFeasibility = `
        Assert-WeatherIntegrationPrearmingScheduleFeasibility `
            -SuiteAtLocal $schedule.suite_at_local `
            -MergeAtLocal $schedule.merge_at_local

    $stage = "acquire_global_preparation_lock"
    $preparationMutex = Enter-WeatherIntegrationPreparationMutex `
        -RepositoryRoot $RepoRoot
    $stage = "validate_active_attempt_collision"
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -AttemptId $AttemptId `
        -RepositoryRoot $RepoRoot

    $stage = "validate_local_topic"
    if (Test-WeatherIntegrationPathEqual -Left $RepoRoot -Right $WorktreeRoot) {
        throw "The suite worktree must be isolated from the production repository."
    }
    $topicBranch = Get-WeatherIntegrationTopicBranchName -BranchRef $BranchRef
    Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("check-ref-format", "--branch", $topicBranch) `
        -Label "preparation topic-branch format query" | Out-Null
    $currentWorktreeBranch = Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("branch", "--show-current") `
        -Label "the suite worktree branch"
    if ($currentWorktreeBranch -cne $topicBranch) {
        throw "Suite worktree branch does not match BranchRef."
    }
    $worktreeTip = (Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("rev-parse", "HEAD") `
        -Label "the suite worktree tip").ToLowerInvariant()
    $worktreeDirtyQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
        -Label "preparation clean-worktree query"
    $worktreeDirty = @($worktreeDirtyQuery.StdoutLines)
    if ($worktreeTip -ne $ExpectedTip -or
        $worktreeDirty.Count -ne 0) {
        throw "Suite worktree must be clean at the exact reviewed tip."
    }
    $preparationTrackedWorktree = `
        Get-WeatherIntegrationTrackedWorktreeFingerprint `
            -WorktreeRoot $WorktreeRoot `
            -ExpectedHead $ExpectedTip `
            -Phase "preparation creator-authority tracked inputs"
    $registered = $false
    $worktreeListQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot -Arguments @("worktree", "list", "--porcelain") `
        -Label "preparation registered-worktree query"
    $worktreeRows = @($worktreeListQuery.StdoutLines)
    foreach ($row in $worktreeRows) {
        if ([string]$row -like "worktree *") {
            $candidate = ([string]$row).Substring("worktree ".Length)
            if (Test-WeatherIntegrationPathEqual -Left $candidate -Right $WorktreeRoot) {
                $registered = $true
                break
            }
        }
    }
    if (-not $registered) {
        throw "Suite worktree is not registered under the production repository."
    }

    $stage = "validate_repair_authority"
    $repairReceiptPath = $null
    $repairReceiptSha256 = $null
    if ($RepairClass -eq "initial") {
        if (-not [string]::IsNullOrWhiteSpace($RepairOfReceiptPath)) {
            throw "An initial preparation may not bind a repair receipt."
        }
    }
    else {
        if ([string]::IsNullOrWhiteSpace($RepairOfReceiptPath)) {
            throw "A successor preparation must bind its predecessor closure receipt."
        }
        $repairReceiptPath = Resolve-WeatherIntegrationPath -Path $RepairOfReceiptPath
        $repairReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $repairReceiptPath -MaximumBytes 2097152 -ContentType Json
        $repairReceipt = $repairReceiptSnapshot.Payload
        $repairReceiptSha256 = [string]$repairReceiptSnapshot.Sha256
        if ([string]$repairReceipt.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
            [string]$repairReceipt.status -ne "FAIL") {
            throw "RepairOfReceiptPath must be an immutable closure FAIL receipt."
        }
        $priorContract = Assert-WeatherIntegrationAttemptManifest `
            -ManifestPath ([string]$repairReceipt.manifest_path) `
            -ExpectedSha256 ([string]$repairReceipt.manifest_sha256)
        $currentClosure = Assert-WeatherIntegrationCurrentFailClosure `
            -AttemptContract $priorContract
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left $repairReceiptPath -Right ([string]$currentClosure.Suite.ReceiptPath)) -or
            [string]$currentClosure.Suite.ReceiptSha256 -ne $repairReceiptSha256 -or
            [string]$currentClosure.Merge.ReceiptSha256 -ne $repairReceiptSha256) {
            throw "Repair authority is not the predecessor's current exact Disabled closure."
        }
        $dispatchPath = [string]$priorContract.Manifest.evidence.recovery_dispatch
        $dispatch = (Read-WeatherIntegrationEvidenceSnapshot -Path $dispatchPath -MaximumBytes 2097152 -ContentType Json).Payload
        if ([string]$dispatch.schema -ne $script:WeatherIntegrationAttemptRecoveryDispatchSchema -or
            [string]$dispatch.status -ne "READY_FOR_SUCCESSOR_REVIEW" -or
            [string]$dispatch.repair_class -ne $RepairClass -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$dispatch.closure_receipt_path) -Right $repairReceiptPath) -or
            [string]$dispatch.closure_receipt_sha256 -ne $repairReceiptSha256) {
            throw "Predecessor recovery dispatch does not authorize this repair."
        }
        $priorClaimPath = Join-Path $priorContract.AttemptRoot "successor-claim.json"
        if (Test-Path -LiteralPath $priorClaimPath) {
            throw "Predecessor closure already has a successor claim."
        }
    }

    $stage = "validate_production_baseline"
    $originUrl = Get-WeatherIntegrationCanonicalOriginUrl -Root $RepoRoot
    $worktreeOriginUrl = Get-WeatherIntegrationCanonicalOriginUrl `
        -Root $WorktreeRoot
    if ($worktreeOriginUrl -cne $originUrl) {
        throw "Production and suite worktree origin URLs do not identify the same repository."
    }
    $productionBranch = Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "the production branch"
    $productionHead = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "HEAD") `
        -Label "production HEAD").ToLowerInvariant()
    $masterTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "master") `
        -Label "local master").ToLowerInvariant()
    $liveMasterTip = Get-WeatherPreparationRemoteTip `
        -Root $RepoRoot -OriginUrl $originUrl -RemoteRef "refs/heads/master"
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $RepoRoot `
        -Arguments @(
            "fetch", "--no-tags", $originUrl,
            "refs/heads/master:refs/remotes/origin/master"
        ) `
        -Label "live exact origin/master refresh" | Out-Null
    $originMasterTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "origin/master") `
        -Label "origin/master").ToLowerInvariant()
    if ($productionBranch -ne "master" -or $productionHead -ne $masterTip -or
        $masterTip -ne $originMasterTip -or $masterTip -ne $liveMasterTip) {
        throw "Production must match the live exact origin master before topic publication."
    }
    $baselineAncestorQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("merge-base", "--is-ancestor", $masterTip, $ExpectedTip) `
        -AllowedExitCodes @(0, 1) `
        -Label "preparation baseline ancestry query"
    if ([int]$baselineAncestorQuery.ExitCode -ne 0) {
        throw "Reviewed topic tip does not contain the exact production baseline."
    }
    if ($ExpectedTip -eq $masterTip) {
        throw "Reviewed topic tip is already the production baseline and cannot form a fresh integration attempt."
    }

    $stage = "validate_quiet_merge_preconditions"
    $quietMergePreflight = Assert-WeatherIntegrationQuietMergePreconditions `
        -RepositoryRoot $RepoRoot

    $stage = "freeze_preparation_intent"
    $scriptPaths = [ordered]@{
        preparer = $PSCommandPath
        readiness = Join-Path $RepoRoot "scripts\ops\assert_integration_attempt_ready.ps1"
        contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_contract.ps1"
        remote_git = Join-Path $RepoRoot "scripts\ops\integration_attempt_remote_git.ps1"
        preparation_contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_preparation_contract.ps1"
        quiet_merge_preflight = Join-Path $RepoRoot "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
        creator = Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1"
        registrar = Join-Path $RepoRoot "scripts\ops\register_integration_attempt.ps1"
        activator = Join-Path $RepoRoot "scripts\ops\activate_integration_attempt.ps1"
        closer = Join-Path $RepoRoot "scripts\ops\close_integration_attempt.ps1"
        bounded_suite = Join-Path $RepoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
        token_contract = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
        job_containment = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
        workload_admission = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
    }
    $scriptBindings = [ordered]@{}
    foreach ($name in $scriptPaths.Keys) {
        $path = Resolve-WeatherIntegrationPath -Path ([string]$scriptPaths[$name])
        $scriptBindings[$name] = [ordered]@{
            path = $path
            sha256 = Get-WeatherIntegrationFileSha256 -Path $path
        }
    }
    $remoteRef = "refs/heads/$topicBranch"
    $exactRefspec = "${ExpectedTip}:$remoteRef"
    $intent = [ordered]@{
        schema = "weather_integration_attempt_preparation_intent_v1"
        status = "PREPARED"
        created_at_local = (Get-Date).ToString("o")
        attempt_id = $AttemptId
        attempt_root = $AttemptRoot
        preparation_root = $preparationRoot
        repo_root = $RepoRoot
        worktree_root = $WorktreeRoot
        branch_ref = $BranchRef
        topic_branch = $topicBranch
        expected_tip = $ExpectedTip
        production_baseline = $masterTip
        quiet_merge_preflight = $quietMergePreflight
        schedule = [ordered]@{
            checked_at_local = $schedule.checked_at_local.ToString("o")
            suite_at_local = $schedule.suite_at_local.ToString("o")
            suite_at_utc = [string]$schedule.suite_at_utc
            merge_at_local = $schedule.merge_at_local.ToString("o")
            merge_at_utc = [string]$schedule.merge_at_utc
            time_zone = $schedule.time_zone
            minimum_lead_minutes = [int]$schedule.minimum_lead_minutes
        }
        publication = [ordered]@{
            remote = "origin"
            origin_url = $originUrl
            remote_ref = $remoteRef
            exact_non_force_refspec = $exactRefspec
            confirmation = $PublicationConfirmation
        }
        authorization = [ordered]@{
            review_reference = $ReviewReference
            repair_class = $RepairClass
            repair_of_receipt_path = $repairReceiptPath
            repair_of_receipt_sha256 = $repairReceiptSha256
            scheduler_confirmation = $SchedulerConfirmation
            activation_confirmation = $ActivationConfirmation
        }
        qualification = [ordered]@{
            required = $true
            creator_preflight_plan_path = $creatorPreflightPlanPath
            receipt_path = $qualificationReceiptPath
            integration_preflight_log_path = $qualificationPreflightLogPath
            full_suite_log_path = $qualificationFullSuiteLogPath
            bounded_suite_path = [string]$scriptBindings.bounded_suite.path
            bounded_suite_sha256 = [string]$scriptBindings.bounded_suite.sha256
            require_live_sdk_contract = [bool]$RequireLiveSdkContract
            rerun_at_suite_trigger = $true
            planning_ceiling_seconds = [int]$plannedQualificationFeasibility.planning_ceiling_seconds
            safety_margin_seconds = [int]$plannedQualificationFeasibility.safety_margin_seconds
            launch_grace_seconds = [int]$plannedQualificationFeasibility.launch_grace_seconds
        }
        scripts = $scriptBindings
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequirePreparationRoot | Out-Null
    Write-WeatherIntegrationImmutableJson -Path $intentPath -Payload $intent
    $intentSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $intentPath -MaximumBytes 65536 -ContentType Json
    $intentSha256 = [string]$intentSnapshot.Sha256

    $creatorPath = [string]$scriptBindings.creator.path
    $creatorArguments = @(
        "-RepoRoot", $RepoRoot,
        "-AttemptRoot", $AttemptRoot,
        "-AttemptId", $AttemptId,
        "-BranchRef", $BranchRef,
        "-WorktreeRoot", $WorktreeRoot,
        "-ExpectedTip", $ExpectedTip,
        "-SuiteAtLocal", $schedule.suite_at_local.ToString("o"),
        "-MergeAtLocal", $schedule.merge_at_local.ToString("o"),
        "-ReviewReference", $ReviewReference,
        "-RepairClass", $RepairClass,
        "-RequirePreparationAuthorization",
        "-PreparationIntentPath", $intentPath,
        "-ExpectedPreparationIntentSha256", $intentSha256
    )
    if (-not [string]::IsNullOrWhiteSpace($RepairOfReceiptPath)) {
        $creatorArguments += @("-RepairOfReceiptPath", $RepairOfReceiptPath)
    }
    if ($RequireLiveSdkContract) {
        $creatorArguments += "-RequireLiveSdkContract"
    }
    $creatorPreflightAuthorizationPlan =
        Get-WeatherIntegrationPreparationAuthorizationPlan `
            -AttemptRoot $AttemptRoot `
            -AttemptId $AttemptId `
            -ManifestPath $manifestPath `
            -ExpectedTip $ExpectedTip `
            -PreparationIntentPath $intentPath `
            -PreparationIntentSha256 $intentSha256 `
            -SuiteTaskName "WeatherIntegrationSuite_$AttemptId" `
            -MergeTaskName "WeatherIntegrationMerge_$AttemptId"

    # Run the canonical creator's complete locally knowable validation path
    # before publication. Even this non-publishing child is assigned before
    # resume to its own kill-on-close Job and fresh hard stop. Its exact result
    # crosses the process boundary only through the predeclared create-only
    # evidence path, never through stdout. The ordinary creator later consumes
    # that exact retained hash and revalidates every mutable premise before the
    # manifest and predecessor claim are frozen.
    $stage = "creator_preflight_before_publication"
    $creatorPreflightStatus = "RUNNING"
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $RepoRoot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -SuiteAtLocal $schedule.suite_at_local `
        -RequirePreparationRoot | Out-Null
    $creatorPreflightChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $creatorPath `
        -ExpectedSha256 ([string]$scriptBindings.creator.sha256) `
        -Arguments @(
            $creatorArguments + @(
                "-PreflightOnly",
                "-PreflightResultPath", $creatorPreflightPlanPath
            )
        ) `
        -Label "integration attempt creator preflight" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
    if ($creatorPreflightChild.ExitCode -ne 0) {
        $creatorPreflightStatus = "FAIL"
        $creatorPreflightDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $creatorPreflightChild
        throw "Creator preflight rejected the attempt before publication with exit $($creatorPreflightChild.ExitCode): $creatorPreflightDiagnostic"
    }
    $creatorPreflightStatus = "VALIDATING_EVIDENCE"
    $creatorPreflightSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $creatorPreflightPlanPath -MaximumBytes 65536 -ContentType Json
    $creatorPreflightBinding = Assert-WeatherIntegrationCreatorPreflightPlan `
        -EvidenceSnapshot $creatorPreflightSnapshot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -RepositoryRoot $RepoRoot `
        -WorktreeRoot $WorktreeRoot `
        -BranchRef $BranchRef `
        -ExpectedTip $ExpectedTip `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -ProductionBaseline $masterTip `
        -OriginUrl $originUrl `
        -RepairClass $RepairClass `
        -RequireLiveSdkContract ([bool]$RequireLiveSdkContract) `
        -PreparationIntentPath $intentPath `
        -ExpectedPreparationIntentSha256 $intentSha256 `
        -ExpectedPreparationAuthorizationSha256 (
            [string]$creatorPreflightAuthorizationPlan.Sha256
        ) `
        -CreatorPath $creatorPath `
        -ExpectedCreatorSha256 ([string]$scriptBindings.creator.sha256) `
        -PreparationContractPath (
            [string]$scriptBindings.preparation_contract.path
        ) `
        -ExpectedPreparationContractSha256 (
            [string]$scriptBindings.preparation_contract.sha256
        ) `
        -ExpectedTrackedWorktreeSchema (
            [string]$preparationTrackedWorktree.schema_version
        ) `
        -ExpectedTrackedWorktreeSha256 (
            [string]$preparationTrackedWorktree.content_sha256
        ) `
        -ExpectedTrackedWorktreeFileCount (
            [int]$preparationTrackedWorktree.file_count
        ) `
        -ExpectedTrackedWorktreeTotalBytes (
            [long]$preparationTrackedWorktree.total_bytes
        ) `
        -ExpectedTrackedWorktreeLfsFileCount (
            [int]$preparationTrackedWorktree.lfs_file_count
        )
    $creatorPreflightPlan = $creatorPreflightBinding.Plan
    $creatorPreflightPlanSha256 = [string]$creatorPreflightBinding.Sha256
    $creatorArguments += @(
        "-CreatorPreflightPlanPath", $creatorPreflightPlanPath,
        "-ExpectedCreatorPreflightPlanSha256", $creatorPreflightPlanSha256
    )
    $creatorPreflightStatus = "PASS"

    $stage = "publish_exact_topic"
    # The credible-window assertion above must remain before this boundary.
    # This exact refspec is intentionally non-force and carries no movable lhs.
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $RepoRoot -ExpectedUrl $originUrl `
        -Phase "pre-publication production repository" | Out-Null
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $WorktreeRoot -ExpectedUrl $originUrl `
        -Phase "pre-publication suite worktree" | Out-Null
    $remoteTipBefore = Get-WeatherPreparationRemoteTip `
        -Root $WorktreeRoot -OriginUrl $originUrl `
        -RemoteRef $remoteRef -AllowMissing
    $remoteLookupCompleted = $true
    # Network/validation latency consumes the original lead. Reassert after
    # the live lookup and immediately before the only push boundary.
    $publicationSchedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow) `
        -MinimumLeadMinutes 10
    $qualificationWindow = Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal $schedule.suite_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow)
    if ($PublicationConfirmation -cne
            "AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION") {
        throw "Exact topic publication confirmation is absent."
    }
    if ($remoteTipBefore -ne $ExpectedTip) {
        $pushAttempted = $true
        Invoke-WeatherIntegrationBoundedRemoteGit `
            -Root $WorktreeRoot `
            -Arguments @("push", $originUrl, $exactRefspec) `
            -TimeoutSeconds 180 `
            -Label "exact reviewed topic publication" | Out-Null
        $pushPerformed = $true
    }
    $remoteTipAfter = Get-WeatherPreparationRemoteTip `
        -Root $WorktreeRoot -OriginUrl $originUrl -RemoteRef $remoteRef
    if ($remoteTipAfter -ne $ExpectedTip) {
        throw "Live origin did not acknowledge the exact reviewed topic tip."
    }

    $stage = "refresh_remote_tracking_ref"
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $RepoRoot -ExpectedUrl $originUrl `
        -Phase "post-publication remote-tracking refresh" | Out-Null
    $fetchRefspec = "${remoteRef}:refs/remotes/origin/$topicBranch"
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $RepoRoot `
        -Arguments @("fetch", "--no-tags", $originUrl, $fetchRefspec) `
        -Label "exact topic remote-tracking refresh" | Out-Null
    $trackingTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", $BranchRef) `
        -Label "the refreshed remote-tracking topic ref").ToLowerInvariant()
    if ($trackingTip -ne $ExpectedTip) {
        throw "Refreshed remote-tracking topic ref does not match the exact reviewed tip."
    }

    # Qualify the exact published tip before an immutable attempt directory or
    # Scheduler task exists. The scheduled suite deliberately repeats both
    # runs later so this evidence proves deterministic readiness while the
    # overnight rerun remains an independent environment-drift check.
    $qualificationWindow = Assert-WeatherIntegrationPrearmingQualificationWindow `
        -SuiteAtLocal $schedule.suite_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow)
    $qualificationStartedAt = [DateTimeOffset]::Now
    $qualificationRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()
    $qualificationRuns = [ordered]@{
        integration_preflight = $null
        full_suite = $null
    }
    $qualificationReceipt = [ordered]@{
        schema = $script:WeatherIntegrationAttemptPrearmingQualificationSchema
        status = "RUNNING"
        attempt_id = $AttemptId
        repo_root = $RepoRoot
        worktree_root = $WorktreeRoot
        branch_ref = $BranchRef
        expected_tip = $ExpectedTip
        started_at_local = $qualificationStartedAt.ToString("o")
        completed_at_local = $null
        duration_seconds = $null
        creator_preflight = [ordered]@{
            path = $creatorPreflightPlanPath
            sha256 = $creatorPreflightPlanSha256
        }
        bounded_suite = [ordered]@{
            path = [string]$scriptBindings.bounded_suite.path
            sha256 = [string]$scriptBindings.bounded_suite.sha256
        }
        require_live_sdk_contract = [bool]$RequireLiveSdkContract
        expected_test_file_count = [int]$creatorPreflightPlan.expected_test_file_count
        max_files_per_chunk = 20
        expected_chunk_count = [int]$creatorPreflightPlan.expected_chunk_count
        expected_test_inventory_sha256 = `
            [string]$creatorPreflightPlan.expected_test_inventory_sha256
        expected_python_file_count = `
            [int]$creatorPreflightPlan.expected_python_file_count
        expected_python_inventory_sha256 = `
            [string]$creatorPreflightPlan.expected_python_inventory_sha256
        expected_powershell_file_count = `
            [int]$creatorPreflightPlan.expected_powershell_file_count
        expected_powershell_inventory_sha256 = `
            [string]$creatorPreflightPlan.expected_powershell_inventory_sha256
        expected_tracked_worktree_schema = `
            [string]$creatorPreflightPlan.expected_tracked_worktree_schema
        expected_tracked_worktree_sha256 = `
            [string]$creatorPreflightPlan.expected_tracked_worktree_sha256
        expected_tracked_worktree_file_count = `
            [int]$creatorPreflightPlan.expected_tracked_worktree_file_count
        expected_tracked_worktree_total_bytes = `
            [long]$creatorPreflightPlan.expected_tracked_worktree_total_bytes
        expected_tracked_worktree_lfs_file_count = `
            [int]$creatorPreflightPlan.expected_tracked_worktree_lfs_file_count
        expected_python_environment_schema = $null
        expected_python_environment_sha256 = $null
        expected_python_environment_distributions = $null
        expected_python_environment_files = $null
        expected_python_environment_bytes = $null
        expected_toolchain_schema = $null
        expected_toolchain_sha256 = $null
        runs = $qualificationRuns
        feasibility = $null
        failure = $null
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    $boundedArguments = @(
        "-RepoRoot", $RepoRoot,
        "-WorktreeRoot", $WorktreeRoot,
        "-ExpectedTip", $ExpectedTip,
        "-BranchRef", $BranchRef,
        "-MaxFilesPerChunk", "20"
    )
    if ($RequireLiveSdkContract) {
        $boundedArguments += "-RequireLiveSdkContract"
    }
    $qualificationHardStop = [datetime]$qualificationWindow.hard_stop_local
    $qualificationScheduleTimeZone = Get-WeatherIntegrationScheduleTimeZone
    $qualificationPreflightNow = Get-WeatherIntegrationScheduleLocalNow
    $qualificationPreflightWallRemainingSeconds =
        Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $qualificationPreflightNow `
            -EndLocal $qualificationHardStop `
            -StartLabel "pre-arming preflight current time" `
            -EndLabel "pre-arming qualification hard stop" `
            -TimeZone $qualificationScheduleTimeZone
    $qualificationPreflightRemainingSeconds = [int][math]::Floor(
        [math]::Min(
            [double]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds -
                [double]$qualificationRuntimeStopwatch.Elapsed.TotalSeconds,
            [double]$qualificationPreflightWallRemainingSeconds
        )
    )
    if ($qualificationPreflightRemainingSeconds -lt
            [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds) {
        throw "Pre-arming qualification has no bounded shared runtime remaining."
    }

    $stage = "prearming_integration_preflight"
    $qualificationStatus = "PREFLIGHT_RUNNING"
    $prearmingPreflightStartedAt = [DateTimeOffset]::Now
    $prearmingPreflightChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath ([string]$scriptBindings.bounded_suite.path) `
        -ExpectedSha256 ([string]$scriptBindings.bounded_suite.sha256) `
        -Arguments @(
            $boundedArguments + @(
                "-LogPath", $qualificationPreflightLogPath,
                "-IntegrationPreflight",
                "-MaxRuntimeSeconds", [string]$qualificationPreflightRemainingSeconds
            )
        ) `
        -Label "pre-arming integration preflight" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop $qualificationHardStop
    $prearmingPreflightCompletedAt = [DateTimeOffset]::Now
    $qualificationRuns.integration_preflight = `
        Get-WeatherPrearmingRunObservation `
            -ChildResult $prearmingPreflightChild `
            -Mode "integration_preflight" `
            -LogPath $qualificationPreflightLogPath `
            -ExpectedTestFileCount 0 `
            -ExpectedChunkCount 0 `
            -StartedAt $prearmingPreflightStartedAt `
            -CompletedAt $prearmingPreflightCompletedAt
    $expectedPreflightVerdict = `
        "VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized"
    if ($prearmingPreflightChild.ExitCode -ne 0 -or
        $null -ne $qualificationRuns.integration_preflight.evidence_validation_error -or
        $null -eq $qualificationRuns.integration_preflight.test_results -or
        [string]$qualificationRuns.integration_preflight.verdict -cne
            $expectedPreflightVerdict) {
        $qualificationStatus = "FAIL"
        $qualificationReceipt.status = "FAIL"
        $qualificationFailedAt = [DateTimeOffset]::Now
        $qualificationReceipt.completed_at_local = $qualificationFailedAt.ToString("o")
        $qualificationReceipt.duration_seconds = [math]::Round(
            [double]$qualificationRuntimeStopwatch.Elapsed.TotalSeconds,
            3
        )
        $qualificationReceipt.failure = "Exact integration preflight did not PASS."
        Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequirePreparationRoot | Out-Null
        Write-WeatherIntegrationImmutableJson `
            -Path $qualificationReceiptPath -Payload $qualificationReceipt
        $qualificationReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $qualificationReceiptPath -MaximumBytes 2097152 -ContentType Json
        $qualificationReceiptSha256 = [string]$qualificationReceiptSnapshot.Sha256
        $prearmingDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $prearmingPreflightChild
        throw "Pre-arming integration preflight rejected the exact tip: $prearmingDiagnostic"
    }

    $stage = "prearming_full_suite"
    $qualificationStatus = "FULL_SUITE_RUNNING"
    $qualificationFullSuiteNow = Get-WeatherIntegrationScheduleLocalNow
    $qualificationFullSuiteWallRemainingSeconds =
        Get-WeatherIntegrationLocalElapsedSeconds `
            -StartLocal $qualificationFullSuiteNow `
            -EndLocal $qualificationHardStop `
            -StartLabel "pre-arming full suite current time" `
            -EndLabel "pre-arming qualification hard stop" `
            -TimeZone $qualificationScheduleTimeZone
    $qualificationFullSuiteRemainingSeconds = [int][math]::Floor(
        [math]::Min(
            [double]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds -
                [double]$qualificationRuntimeStopwatch.Elapsed.TotalSeconds,
            [double]$qualificationFullSuiteWallRemainingSeconds
        )
    )
    if ($qualificationFullSuiteRemainingSeconds -lt
            [int]$script:WeatherIntegrationSuiteMinimumPhaseRuntimeSeconds) {
        throw "Pre-arming full suite has no bounded shared runtime remaining."
    }
    $prearmingFullSuiteStartedAt = [DateTimeOffset]::Now
    $prearmingFullSuiteChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath ([string]$scriptBindings.bounded_suite.path) `
        -ExpectedSha256 ([string]$scriptBindings.bounded_suite.sha256) `
        -Arguments @(
            $boundedArguments + @(
                "-LogPath", $qualificationFullSuiteLogPath,
                "-MaxRuntimeSeconds", [string]$qualificationFullSuiteRemainingSeconds
            )
        ) `
        -Label "pre-arming full bounded suite" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop $qualificationHardStop
    $prearmingFullSuiteCompletedAt = [DateTimeOffset]::Now
    $qualificationRuns.full_suite = Get-WeatherPrearmingRunObservation `
        -ChildResult $prearmingFullSuiteChild `
        -Mode "full_suite" `
        -LogPath $qualificationFullSuiteLogPath `
        -ExpectedTestFileCount ([int]$creatorPreflightPlan.expected_test_file_count) `
        -ExpectedChunkCount ([int]$creatorPreflightPlan.expected_chunk_count) `
        -StartedAt $prearmingFullSuiteStartedAt `
        -CompletedAt $prearmingFullSuiteCompletedAt
    $expectedFullSuiteVerdict = (
        "VERDICT: ALL CHUNKS PASSED (" +
        "$($creatorPreflightPlan.expected_chunk_count)/" +
        "$($creatorPreflightPlan.expected_chunk_count)); " +
        "exact tip eligible for separate reviewed merge"
    )
    if ($prearmingFullSuiteChild.ExitCode -ne 0 -or
        $null -ne $qualificationRuns.full_suite.evidence_validation_error -or
        $null -eq $qualificationRuns.full_suite.test_results -or
        [string]$qualificationRuns.full_suite.verdict -cne
            $expectedFullSuiteVerdict) {
        $qualificationStatus = "FAIL"
        $qualificationReceipt.status = "FAIL"
        $qualificationFailedAt = [DateTimeOffset]::Now
        $qualificationReceipt.completed_at_local = $qualificationFailedAt.ToString("o")
        $qualificationReceipt.duration_seconds = [math]::Round(
            [double]$qualificationRuntimeStopwatch.Elapsed.TotalSeconds,
            3
        )
        $qualificationReceipt.failure = "Exact full bounded suite did not PASS."
        Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequirePreparationRoot | Out-Null
        Write-WeatherIntegrationImmutableJson `
            -Path $qualificationReceiptPath -Payload $qualificationReceipt
        $qualificationReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $qualificationReceiptPath -MaximumBytes 2097152 -ContentType Json
        $qualificationReceiptSha256 = [string]$qualificationReceiptSnapshot.Sha256
        $fullSuiteDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $prearmingFullSuiteChild
        throw "Pre-arming full bounded suite rejected the exact tip: $fullSuiteDiagnostic"
    }

    $stage = "freeze_prearming_qualification"
    $qualificationStatus = "PASS"
    foreach ($name in @(
        "python_environment_schema", "python_environment_sha256",
        "python_environment_distributions", "python_environment_files",
        "python_environment_bytes", "toolchain_schema",
        "toolchain_sha256"
    )) {
        if ([string]$qualificationRuns.integration_preflight.test_results.$name -cne
                [string]$qualificationRuns.full_suite.test_results.$name) {
            throw "Pre-arming runs used different Python environment field $name."
        }
    }
    $qualificationReceipt.expected_python_environment_schema =
        [string]$qualificationRuns.full_suite.test_results.python_environment_schema
    $qualificationReceipt.expected_python_environment_sha256 =
        [string]$qualificationRuns.full_suite.test_results.python_environment_sha256
    $qualificationReceipt.expected_python_environment_distributions =
        [int]$qualificationRuns.full_suite.test_results.python_environment_distributions
    $qualificationReceipt.expected_python_environment_files =
        [int]$qualificationRuns.full_suite.test_results.python_environment_files
    $qualificationReceipt.expected_python_environment_bytes =
        [long]$qualificationRuns.full_suite.test_results.python_environment_bytes
    $qualificationReceipt.expected_toolchain_schema =
        [string]$qualificationRuns.full_suite.test_results.toolchain_schema
    $qualificationReceipt.expected_toolchain_sha256 =
        [string]$qualificationRuns.full_suite.test_results.toolchain_sha256
    $qualificationReceipt.status = "PASS"
    $qualificationCompletedAt = [DateTimeOffset]::Now
    $qualificationReceipt.completed_at_local = $qualificationCompletedAt.ToString("o")
    $qualificationReceipt.duration_seconds = [math]::Round(
        [double]$qualificationRuntimeStopwatch.Elapsed.TotalSeconds,
        3
    )
    if ([double]$qualificationReceipt.duration_seconds -gt
            [double]$script:WeatherIntegrationBoundedSuiteMaximumRuntimeSeconds) {
        throw "Pre-arming qualification exceeded the shared bounded-suite runtime ceiling."
    }
    $qualificationReceipt.feasibility = `
        Assert-WeatherIntegrationPrearmingScheduleFeasibility `
            -SuiteAtLocal $schedule.suite_at_local `
            -MergeAtLocal $schedule.merge_at_local `
            -MeasuredDurationSeconds ([double]$qualificationReceipt.duration_seconds)
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequirePreparationRoot | Out-Null
    Write-WeatherIntegrationImmutableJson `
        -Path $qualificationReceiptPath -Payload $qualificationReceipt
    $qualificationReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $qualificationReceiptPath -MaximumBytes 2097152 -ContentType Json
    $qualificationReceiptSha256 = [string]$qualificationReceiptSnapshot.Sha256
    $qualificationEvidence = `
        Assert-WeatherIntegrationPrearmingQualificationEvidence `
            -PreparationIntentPath $intentPath `
            -ExpectedPreparationIntentSha256 $intentSha256 `
            -AttemptRoot $AttemptRoot `
            -AttemptId $AttemptId `
            -RepoRoot $RepoRoot `
            -WorktreeRoot $WorktreeRoot `
            -BranchRef $BranchRef `
            -ExpectedTip $ExpectedTip `
            -BoundedSuitePath ([string]$scriptBindings.bounded_suite.path) `
            -ExpectedBoundedSuiteSha256 ([string]$scriptBindings.bounded_suite.sha256) `
            -ExpectedTestFileCount ([int]$creatorPreflightPlan.expected_test_file_count) `
            -ExpectedChunkCount ([int]$creatorPreflightPlan.expected_chunk_count) `
            -ExpectedTestInventorySha256 (
                [string]$creatorPreflightPlan.expected_test_inventory_sha256
            ) `
            -ExpectedPythonFileCount (
                [int]$creatorPreflightPlan.expected_python_file_count
            ) `
            -ExpectedPythonInventorySha256 (
                [string]$creatorPreflightPlan.expected_python_inventory_sha256
            ) `
            -ExpectedPowerShellFileCount (
                [int]$creatorPreflightPlan.expected_powershell_file_count
            ) `
            -ExpectedPowerShellInventorySha256 (
                [string]$creatorPreflightPlan.expected_powershell_inventory_sha256
            ) `
            -ExpectedTrackedWorktreeSchema (
                [string]$creatorPreflightPlan.expected_tracked_worktree_schema
            ) `
            -ExpectedTrackedWorktreeSha256 (
                [string]$creatorPreflightPlan.expected_tracked_worktree_sha256
            ) `
            -ExpectedTrackedWorktreeFileCount (
                [int]$creatorPreflightPlan.expected_tracked_worktree_file_count
            ) `
            -ExpectedTrackedWorktreeTotalBytes (
                [long]$creatorPreflightPlan.expected_tracked_worktree_total_bytes
            ) `
            -ExpectedTrackedWorktreeLfsFileCount (
                [int]$creatorPreflightPlan.expected_tracked_worktree_lfs_file_count
            ) `
            -RequireLiveSdkContract ([bool]$RequireLiveSdkContract) `
            -ExpectedReceiptSha256 $qualificationReceiptSha256 `
            -RequireLiveWorktreeImport
    if (-not [bool]$qualificationEvidence.Present) {
        throw "Pre-arming qualification did not leave exact immutable PASS evidence."
    }

    $stage = "revalidate_exact_state_after_qualification"
    foreach ($bindingName in $scriptBindings.Keys) {
        $binding = $scriptBindings[$bindingName]
        if ((Get-WeatherIntegrationFileSha256 -Path ([string]$binding.path)) -ne
                [string]$binding.sha256) {
            throw "Preparation helper changed during qualification: $bindingName"
        }
    }
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $RepoRoot -ExpectedUrl $originUrl `
        -Phase "post-qualification production repository" | Out-Null
    Assert-WeatherIntegrationCanonicalOriginUrl `
        -Root $WorktreeRoot -ExpectedUrl $originUrl `
        -Phase "post-qualification suite worktree" | Out-Null
    $postQualificationRemoteTip = Get-WeatherPreparationRemoteTip `
        -Root $WorktreeRoot -OriginUrl $originUrl -RemoteRef $remoteRef
    $postQualificationMasterTip = Get-WeatherPreparationRemoteTip `
        -Root $RepoRoot -OriginUrl $originUrl -RemoteRef "refs/heads/master"
    if ($postQualificationRemoteTip -ne $ExpectedTip -or
        $postQualificationMasterTip -ne $masterTip) {
        throw "Live topic or master changed during pre-arming qualification."
    }
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $RepoRoot `
        -Arguments @("fetch", "--no-tags", $originUrl, $fetchRefspec) `
        -Label "post-qualification exact topic refresh" | Out-Null
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $RepoRoot `
        -Arguments @(
            "fetch", "--no-tags", $originUrl,
            "refs/heads/master:refs/remotes/origin/master"
        ) `
        -Label "post-qualification exact master refresh" | Out-Null
    $postQualificationTrackingTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", $BranchRef) `
        -Label "post-qualification remote-tracking topic").ToLowerInvariant()
    $postQualificationOriginMaster = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "origin/master") `
        -Label "post-qualification origin/master").ToLowerInvariant()
    $postQualificationProductionHead = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "HEAD") `
        -Label "post-qualification production HEAD").ToLowerInvariant()
    $postQualificationProductionBranch = Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "post-qualification production branch"
    $postQualificationWorktreeTip = (Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("rev-parse", "HEAD") `
        -Label "post-qualification worktree tip").ToLowerInvariant()
    $postQualificationWorktreeBranch = Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("branch", "--show-current") `
        -Label "post-qualification worktree branch"
    $postQualificationDirtyQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $WorktreeRoot -Arguments @("status", "--porcelain") `
        -Label "post-qualification clean-worktree query"
    $postQualificationWorktreeDirty = @($postQualificationDirtyQuery.StdoutLines)
    if ($postQualificationTrackingTip -ne $ExpectedTip -or
        $postQualificationOriginMaster -ne $masterTip -or
        $postQualificationProductionHead -ne $masterTip -or
        $postQualificationProductionBranch -ne "master" -or
        $postQualificationWorktreeTip -ne $ExpectedTip -or
        $postQualificationWorktreeBranch -cne $topicBranch -or
        $postQualificationWorktreeDirty.Count -ne 0) {
        throw "Repository baseline or exact suite worktree changed during qualification."
    }
    $postQualificationTrackedWorktree = `
        Get-WeatherIntegrationTrackedWorktreeFingerprint `
            -WorktreeRoot $WorktreeRoot `
            -ExpectedHead $ExpectedTip `
            -Phase "post-qualification tracked inputs"
    if ([string]$postQualificationTrackedWorktree.content_sha256 -cne
            [string]$creatorPreflightPlan.expected_tracked_worktree_sha256 -or
        [int]$postQualificationTrackedWorktree.file_count -ne
            [int]$creatorPreflightPlan.expected_tracked_worktree_file_count -or
        [long]$postQualificationTrackedWorktree.total_bytes -ne
            [long]$creatorPreflightPlan.expected_tracked_worktree_total_bytes -or
        [int]$postQualificationTrackedWorktree.lfs_file_count -ne
            [int]$creatorPreflightPlan.expected_tracked_worktree_lfs_file_count) {
        throw "Tracked working inputs changed during pre-arming qualification."
    }
    $postQualificationQuietMergePreflight = `
        Assert-WeatherIntegrationQuietMergePreconditions -RepositoryRoot $RepoRoot
    if ([string]$postQualificationQuietMergePreflight.one_shot_push_task_xml_sha256 -ne
        [string]$quietMergePreflight.one_shot_push_task_xml_sha256) {
        throw "Quiet-merge prerequisites changed during qualification."
    }

    # Qualification can consume most of an admitted window. Reassert that the
    # future trigger still retains the complete preparation reserve before any
    # immutable attempt or Scheduler state is created.
    $stage = "revalidate_schedule_after_qualification"
    $qualificationSchedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow) `
        -MinimumLeadMinutes 10

    $stage = "create_immutable_attempt"
    # From this boundary the child may have frozen a manifest even if its
    # process later returns nonzero or the file becomes unreadable. Closure is
    # permanently required; absence is unproved state, never no-mutation proof.
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequirePreparationRoot | Out-Null
    $closureRequired = $true
    $creatorChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $creatorPath `
        -ExpectedSha256 ([string]$scriptBindings.creator.sha256) `
        -Arguments $creatorArguments `
        -Label "integration attempt creator" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
    if ($creatorChild.ExitCode -ne 0) {
        $creatorDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $creatorChild
        throw "Immutable integration attempt creation failed with exit $($creatorChild.ExitCode): $creatorDiagnostic"
    }
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequireAttemptRoot -RequirePreparationRoot | Out-Null
    $manifestSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $manifestPath -MaximumBytes 1048576 -ContentType Json
    $manifestSha256 = [string]$manifestSnapshot.Sha256

    $stage = "register_exact_tasks"
    $registrarPath = [string]$scriptBindings.registrar.path
    # Attempt creation can be slow. Never arm Scheduler from a window whose
    # ten-minute preparation reserve has already been consumed.
    $registrationSchedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -Now (Get-WeatherIntegrationScheduleLocalNow) `
        -MinimumLeadMinutes 10
    if ($SchedulerConfirmation -cne
            "AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION") {
        throw "Disabled integration-task registration confirmation is absent."
    }
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequireAttemptRoot -RequirePreparationRoot | Out-Null
    $registrarChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $registrarPath `
        -ExpectedSha256 ([string]$scriptBindings.registrar.sha256) `
        -Arguments @(
            "-RepoRoot", $RepoRoot,
            "-ManifestPath", $manifestPath,
            "-ExpectedManifestSha256", $manifestSha256,
            "-MinimumSuiteLeadMinutes", "10",
            "-SchedulerConfirmation", $SchedulerConfirmation,
            "-StageDisabled"
        ) `
        -Label "integration attempt registrar" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
    if ($registrarChild.ExitCode -ne 0) {
        $registrarDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $registrarChild
        throw "Exact integration task registration failed with exit $($registrarChild.ExitCode): $registrarDiagnostic"
    }

    $stage = "assert_final_readiness"
    $readinessPath = [string]$scriptBindings.readiness.path
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequireAttemptRoot -RequirePreparationRoot | Out-Null
    $readinessChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $readinessPath `
        -ExpectedSha256 ([string]$scriptBindings.readiness.sha256) `
        -Arguments @(
            "-ManifestPath", $manifestPath,
            "-ExpectedManifestSha256", $manifestSha256,
            "-PreparationIntentPath", $intentPath,
            "-ExpectedPreparationIntentSha256", $intentSha256,
            "-PublicationCheckedAtLocal", $publicationSchedule.checked_at_local.ToString("o"),
            "-RegistrationCheckedAtLocal", $registrationSchedule.checked_at_local.ToString("o"),
            "-ResultPath", $readinessResultPath,
            "-StagedDisabled"
        ) `
        -Label "integration attempt readiness assertion" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
    $readinessOutput = @($readinessChild.Output)
    if ($readinessChild.ExitCode -ne 0) {
        $readinessDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $readinessChild
        throw "Final integration readiness assertion failed with exit $($readinessChild.ExitCode): $readinessDiagnostic"
    }
    $readinessResultSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $readinessResultPath -MaximumBytes 2097152 -ContentType Json
    $readinessResult = $readinessResultSnapshot.Payload
    if ([string]$readinessResult.schema -ne "weather_integration_attempt_readiness_receipt_v1" -or
        [string]$readinessResult.status -ne "PASS" -or
        [string]$readinessResult.manifest_sha256 -ne $manifestSha256 -or
        [string]$readinessResult.preparation_intent_sha256 -ne $intentSha256) {
        throw "Final readiness assertion did not leave the exact durable PASS receipt."
    }

    $stage = "activate_exact_tasks"
    if ($ActivationConfirmation -cne
            "AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION") {
        throw "Exact integration-task activation confirmation is absent."
    }
    $readinessReceiptSha256 = [string]$readinessResultSnapshot.Sha256
    $activatorPath = [string]$scriptBindings.activator.path
    Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $schedule.suite_at_local -RequireAttemptRoot -RequirePreparationRoot | Out-Null
    $activatorChild = Invoke-WeatherIntegrationContainedPowerShellChild `
        -ScriptPath $activatorPath `
        -ExpectedSha256 ([string]$scriptBindings.activator.sha256) `
        -Arguments @(
            "-ManifestPath", $manifestPath,
            "-ExpectedManifestSha256", $manifestSha256,
            "-PreparationIntentPath", $intentPath,
            "-ExpectedPreparationIntentSha256", $intentSha256,
            "-ReadinessReceiptPath", $readinessResultPath,
            "-ExpectedReadinessReceiptSha256", $readinessReceiptSha256,
            "-ResultPath", $resultPath,
            "-ActivationConfirmation", $ActivationConfirmation
        ) `
        -Label "integration attempt activator" `
        -WorkingDirectory $RepoRoot `
        -OutputDirectory $preparationRoot `
        -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
    if ($activatorChild.ExitCode -ne 0) {
        $activatorDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $activatorChild
        throw "Exact integration task activation failed with exit $($activatorChild.ExitCode): $activatorDiagnostic"
    }
    $activationReceipt = (Read-WeatherIntegrationEvidenceSnapshot -Path $resultPath -MaximumBytes 2097152 -ContentType Json).Payload
    if ([string]$activationReceipt.schema -ne
            "weather_integration_attempt_preparation_receipt_v1" -or
        [string]$activationReceipt.status -ne "PASS" -or
        [string]$activationReceipt.stage -ne "READY" -or
        [string]$activationReceipt.manifest_sha256 -ne $manifestSha256 -or
        [string]$activationReceipt.preparation_intent_sha256 -ne $intentSha256 -or
        [string]$activationReceipt.readiness_receipt_sha256 -ne
            $readinessReceiptSha256) {
        throw "Activator did not leave the exact durable final preparation PASS receipt."
    }
    $activationContract = Assert-WeatherIntegrationActivationReceipt `
        -AttemptContract (Assert-WeatherIntegrationAttemptManifest `
            -ManifestPath $manifestPath -ExpectedSha256 $manifestSha256)
    if (-not [bool]$activationContract.Required -or
        -not [bool]$activationContract.Present) {
        throw "Final preparation receipt did not prove exact post-enable activation."
    }
    $stage = "release_global_preparation_lock"
    try {
        $preparationMutex.Dispose()
        $preparationMutex = $null
    }
    catch {
        throw "Global preparation lock release failed: $($_.Exception.Message)"
    }
    $status = "PASS"
}
catch {
    $primaryError = $_
    $failure = $_.Exception.Message
    $failureStage = $stage
    if ($closureRequired -and
        (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        $closureAttempted = $true
        $closureReceiptPath = Resolve-WeatherIntegrationPath `
            -Path (Join-Path $AttemptRoot "closure-receipt.json")
        try {
            if ([string]::IsNullOrWhiteSpace([string]$manifestSha256)) {
                $manifestSha256 = Get-WeatherIntegrationFileSha256 -Path $manifestPath
            }
            $failedAttempt = Assert-WeatherIntegrationAttemptManifest `
                -ManifestPath $manifestPath -ExpectedSha256 $manifestSha256
            $closureReceiptPath = Resolve-WeatherIntegrationPath `
                -Path ([string]$failedAttempt.Manifest.evidence.closure_receipt)
            $closerPath = [string]$failedAttempt.Manifest.orchestration.attempt_closer.path
            if ((Get-WeatherIntegrationFileSha256 -Path $closerPath) -ne
                [string]$failedAttempt.Manifest.orchestration.attempt_closer.sha256) {
                throw "Canonical closer does not match the failed manifest binding."
            }
            $closureReason = "Preparation failed at stage ${failureStage}: $failure"
            $closureChild = Invoke-WeatherIntegrationContainedPowerShellChild `
                -ScriptPath $closerPath `
                -ExpectedSha256 (
                    [string]$failedAttempt.Manifest.orchestration.attempt_closer.sha256
                ) `
                -Arguments @(
                    "-ManifestPath", $manifestPath,
                    "-ExpectedManifestSha256", $manifestSha256,
                    "-Reason", $closureReason,
                    "-ReviewReference", $ReviewReference
                ) `
                -Label "integration attempt closer" `
                -WorkingDirectory $RepoRoot `
                -OutputDirectory $preparationRoot `
                -HardStop (Get-WeatherIntegrationPreparationMutationHardStop)
            $closureOutput = @($closureChild.Output)
            if ($closureChild.ExitCode -ne 0) {
                $closureDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
                    -ChildResult $closureChild
                throw "Canonical close failed with exit $($closureChild.ExitCode): $closureDiagnostic"
            }
            # The closer's process exit is not the proof. Re-read the exact
            # closure through the canonical current-state validator, which
            # binds one complete Scheduler snapshot to both receipt rows.
            $currentClosure = Assert-WeatherIntegrationCurrentFailClosure `
                -AttemptContract $failedAttempt
            $closureReceipt = $currentClosure.Suite.Receipt
            $closureReceiptSha256 = [string]$currentClosure.Suite.ReceiptSha256
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$currentClosure.Suite.ReceiptPath) `
                    -Right $closureReceiptPath) -or
                [string]$currentClosure.Merge.ReceiptSha256 -ne
                    $closureReceiptSha256 -or
                [string]$closureReceipt.reason -ne $closureReason -or
                [string]$closureReceipt.review_reference -ne $ReviewReference) {
                throw "Canonical closure receipt does not prove exact task terminality."
            }
            $closureStatus = "PROVED"
        }
        catch {
            $closureFailure = $_.Exception.Message
            if (Test-Path -LiteralPath $closureReceiptPath -PathType Leaf) {
                try {
                    $closureReceiptSha256 = Get-WeatherIntegrationFileSha256 `
                        -Path $closureReceiptPath
                }
                catch {
                    $closureFailure = "$closureFailure; closure receipt hash failed: $($_.Exception.Message)"
                }
            }
            $closureStatus = "FAILED"
            $failure = "$failure; canonical closure failed: $closureFailure"
        }
    }
    elseif ($closureRequired) {
        $closureStatus = "FAILED"
        $closureFailure = "Manifest creation began but the canonical manifest is missing or unreadable; exact task terminality cannot be proved."
        $failure = "$failure; canonical closure failed: $closureFailure"
    }
}
finally {
    if ($null -ne $preparationMutex) {
        try {
            $preparationMutex.Dispose()
            $preparationMutex = $null
        }
        catch {
            $mutexCleanupFailure =
                "global preparation lock cleanup failed: $($_.Exception.Message)"
            if ([string]::IsNullOrWhiteSpace([string]$failure)) {
                $failure = $mutexCleanupFailure
                $failureStage = "release_global_preparation_lock"
            }
            else { $failure = "$failure; $mutexCleanupFailure" }
            if ($null -ne $primaryError) {
                $primaryError.Exception.Data["weather_cleanup_failure"] =
                    $mutexCleanupFailure
            }
            $status = "FAIL"
        }
    }
    if ($status -ne "PASS" -and -not (Test-Path -LiteralPath $resultPath)) {
        try {
            $failureReceipt = [ordered]@{
                schema = "weather_integration_attempt_preparation_receipt_v1"
                status = "FAIL"
                stage = $stage
                checked_at_local = (Get-Date).ToString("o")
                attempt_id = $AttemptId
                preparation_intent_path = $intentPath
                preparation_intent_sha256 = $intentSha256
                manifest_path = $manifestPath
                manifest_sha256 = $manifestSha256
                branch_ref = $BranchRef
                expected_tip = $ExpectedTip
                publication = [ordered]@{
                    remote_lookup_completed = $remoteLookupCompleted
                    push_attempted = $pushAttempted
                    push_performed = $pushPerformed
                    remote_tip_before = $remoteTipBefore
                    remote_tip_after = $remoteTipAfter
                    remote_tracking_tip = $trackingTip
                }
                creator_preflight = [ordered]@{
                    status = $creatorPreflightStatus
                    plan_path = $creatorPreflightPlanPath
                    plan_sha256 = $creatorPreflightPlanSha256
                }
                prearming_qualification = [ordered]@{
                    status = $qualificationStatus
                    receipt_path = $qualificationReceiptPath
                    receipt_sha256 = $qualificationReceiptSha256
                    integration_preflight_log_path = $qualificationPreflightLogPath
                    full_suite_log_path = $qualificationFullSuiteLogPath
                }
                closure = [ordered]@{
                    required = $closureRequired
                    attempted = $closureAttempted
                    status = $closureStatus
                    receipt_path = $closureReceiptPath
                    receipt_sha256 = $closureReceiptSha256
                    failure = $closureFailure
                }
                failure = $failure
                safety = [ordered]@{
                    authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
                    credential_value_access_authorized = $false
                    live_exchange_mutation_authorized = $false
                }
            }
            Write-WeatherIntegrationImmutableJson -Path $resultPath -Payload $failureReceipt
            $failureReceiptWritten = $true
        }
        catch {
            $failure = "$failure; immutable preparation FAIL receipt could not be written: $($_.Exception.Message)"
        }
    }
}

if ($status -ne "PASS") {
    $reportedStage = if ([string]::IsNullOrWhiteSpace([string]$failureStage)) {
        $stage
    }
    else { $failureStage }
    Write-Host "Integration attempt preparation failed at stage '$reportedStage'."
    if ($closureStatus -eq "FAILED") {
        Write-Host "Canonical closure failed; exact task terminality is unproved."
    }
    if ($failureReceiptWritten) {
        Write-Host "Immutable preparation evidence: $resultPath"
    }
    elseif (Test-Path -LiteralPath $resultPath -PathType Leaf) {
        Write-Host "A conflicting immutable preparation result exists and could not be replaced: $resultPath"
    }
    else {
        Write-Host "Immutable preparation FAIL evidence could not be written."
    }
    exit 1
}

$finalReceipt = Read-WeatherIntegrationSharedJson -Path $resultPath
$finalReceipt | ConvertTo-Json -Depth 10 -Compress
exit 0
