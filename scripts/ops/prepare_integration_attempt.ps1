# Publish one exact reviewed topic tip, create its immutable v1 attempt, register
# the two canonical one-shots, and prove the complete attempt is still ready.
# Run this entry point only in the user's interactive credential context and
# only with explicit authority for its topic push and Scheduler registration.

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
    [switch]$RequireLiveSdkContract
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_quiet_merge_preflight.ps1")

function Invoke-WeatherPreparationGitLine {
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

function Get-WeatherPreparationRemoteTip {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RemoteRef,
        [switch]$AllowMissing
    )

    $rows = @(& git -C $Root ls-remote --heads origin $RemoteRef)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not query the exact origin ref."
    }
    return Resolve-WeatherIntegrationRemoteTipRows `
        -Rows $rows -ExpectedRemoteRef $RemoteRef -AllowMissing:$AllowMissing
}

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$WorktreeRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
$AttemptRoot = Resolve-WeatherIntegrationPath -Path $AttemptRoot
$ExpectedTip = $ExpectedTip.ToLowerInvariant()
$preparationRoot = Resolve-WeatherIntegrationPath -Path ($AttemptRoot + ".preparation")
$intentPath = Join-Path $preparationRoot "preparation-intent.json"
$resultPath = Join-Path $preparationRoot "preparation-receipt.json"
$readinessResultPath = Join-Path $preparationRoot "readiness-receipt.json"
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

    # This is deliberately the first operational gate. No remote publication
    # is attempted unless both triggers are credible and suite retains >=10m.
    $stage = "validate_schedule"
    $schedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $SuiteAtLocal `
        -MergeAtLocal $MergeAtLocal `
        -Now (Get-Date) `
        -MinimumLeadMinutes 10

    $stage = "acquire_global_preparation_lock"
    $preparationMutex = Enter-WeatherIntegrationPreparationMutex `
        -RepositoryRoot $RepoRoot
    $stage = "validate_active_attempt_collision"
    Assert-WeatherIntegrationNoActiveAttemptCollision `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -AttemptId $AttemptId

    $stage = "validate_local_topic"
    if (-not (Test-Path -LiteralPath $WorktreeRoot -PathType Container)) {
        throw "Suite worktree is missing: $WorktreeRoot"
    }
    if (Test-WeatherIntegrationPathEqual -Left $RepoRoot -Right $WorktreeRoot) {
        throw "The suite worktree must be isolated from the production repository."
    }
    $topicBranch = Get-WeatherIntegrationTopicBranchName -BranchRef $BranchRef
    & git -C $RepoRoot check-ref-format --branch $topicBranch | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BranchRef does not contain a valid Git topic branch."
    }
    $currentWorktreeBranch = Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("branch", "--show-current") `
        -Label "the suite worktree branch"
    if ($currentWorktreeBranch -cne $topicBranch) {
        throw "Suite worktree branch does not match BranchRef."
    }
    $worktreeTip = (Invoke-WeatherPreparationGitLine `
        -Root $WorktreeRoot -Arguments @("rev-parse", "HEAD") `
        -Label "the suite worktree tip").ToLowerInvariant()
    $worktreeDirty = @(& git -C $WorktreeRoot status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $worktreeTip -ne $ExpectedTip -or
        $worktreeDirty.Count -ne 0) {
        throw "Suite worktree must be clean at the exact reviewed tip."
    }
    $registered = $false
    $worktreeRows = @(& git -C $RepoRoot worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not enumerate registered worktrees."
    }
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
        $repairReceipt = Read-WeatherIntegrationSharedJson -Path $repairReceiptPath
        $repairReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $repairReceiptPath
        if ([string]$repairReceipt.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
            [string]$repairReceipt.status -ne "FAIL") {
            throw "RepairOfReceiptPath must be an immutable closure FAIL receipt."
        }
        $priorContract = Assert-WeatherIntegrationAttemptManifest `
            -ManifestPath ([string]$repairReceipt.manifest_path) `
            -ExpectedSha256 ([string]$repairReceipt.manifest_sha256)
        $dispatchPath = [string]$priorContract.Manifest.evidence.recovery_dispatch
        $dispatch = Read-WeatherIntegrationSharedJson -Path $dispatchPath
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
        -Root $RepoRoot -RemoteRef "refs/heads/master"
    & git -C $RepoRoot fetch --no-tags origin `
        "refs/heads/master:refs/remotes/origin/master"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not refresh origin/master from the live exact master ref."
    }
    $originMasterTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", "origin/master") `
        -Label "origin/master").ToLowerInvariant()
    if ($productionBranch -ne "master" -or $productionHead -ne $masterTip -or
        $masterTip -ne $originMasterTip -or $masterTip -ne $liveMasterTip) {
        throw "Production must match the live exact origin master before topic publication."
    }
    & git -C $RepoRoot merge-base --is-ancestor $masterTip $ExpectedTip
    if ($LASTEXITCODE -ne 0) {
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
        preparation_contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_preparation_contract.ps1"
        quiet_merge_preflight = Join-Path $RepoRoot "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
        creator = Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1"
        registrar = Join-Path $RepoRoot "scripts\ops\register_integration_attempt.ps1"
        activator = Join-Path $RepoRoot "scripts\ops\activate_integration_attempt.ps1"
        closer = Join-Path $RepoRoot "scripts\ops\close_integration_attempt.ps1"
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
            merge_at_local = $schedule.merge_at_local.ToString("o")
            minimum_lead_minutes = [int]$schedule.minimum_lead_minutes
        }
        publication = [ordered]@{
            remote = "origin"
            remote_ref = $remoteRef
            exact_non_force_refspec = $exactRefspec
        }
        authorization = [ordered]@{
            review_reference = $ReviewReference
            repair_class = $RepairClass
            repair_of_receipt_path = $repairReceiptPath
            repair_of_receipt_sha256 = $repairReceiptSha256
        }
        scripts = $scriptBindings
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    Write-WeatherIntegrationImmutableJson -Path $intentPath -Payload $intent
    $intentSha256 = Get-WeatherIntegrationFileSha256 -Path $intentPath

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

    # Run the canonical creator's complete locally knowable validation path
    # before publication. The ordinary creator is invoked again after fetch,
    # so BranchRef and every mutable local premise are revalidated before the
    # manifest and predecessor claim are frozen.
    $stage = "creator_preflight_before_publication"
    $creatorPreflightChild = Invoke-WeatherIntegrationPowerShellChild `
        -ScriptPath $creatorPath `
        -ExpectedSha256 ([string]$scriptBindings.creator.sha256) `
        -Arguments @($creatorArguments + "-PreflightOnly") `
        -Label "integration attempt creator preflight"
    if ($creatorPreflightChild.ExitCode -ne 0) {
        $creatorPreflightDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $creatorPreflightChild
        throw "Creator preflight rejected the attempt before publication with exit $($creatorPreflightChild.ExitCode): $creatorPreflightDiagnostic"
    }
    $creatorPreflightRows = @($creatorPreflightChild.Output | Where-Object {
        -not [string]::IsNullOrWhiteSpace([string]$_)
    })
    if ($creatorPreflightRows.Count -lt 1) {
        throw "Creator preflight returned no exact plan evidence."
    }
    try {
        $creatorPreflightPlan = [string]$creatorPreflightRows[-1] | ConvertFrom-Json
    }
    catch {
        throw "Creator preflight returned unreadable plan evidence."
    }
    if ([string]$creatorPreflightPlan.status -ne "PREFLIGHT_READY" -or
        [string]$creatorPreflightPlan.attempt_id -ne $AttemptId -or
        [string]$creatorPreflightPlan.expected_tip -ne $ExpectedTip -or
        [string]$creatorPreflightPlan.production_baseline -ne $masterTip -or
        [int]$creatorPreflightPlan.expected_test_file_count -le 0) {
        throw "Creator preflight plan did not bind the exact prepared attempt."
    }

    $stage = "publish_exact_topic"
    # The credible-window assertion above must remain before this boundary.
    # This exact refspec is intentionally non-force and carries no movable lhs.
    $remoteTipBefore = Get-WeatherPreparationRemoteTip `
        -Root $WorktreeRoot -RemoteRef $remoteRef -AllowMissing
    $remoteLookupCompleted = $true
    # Network/validation latency consumes the original lead. Reassert after
    # the live lookup and immediately before the only push boundary.
    $publicationSchedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -Now (Get-Date) `
        -MinimumLeadMinutes 10
    if ($remoteTipBefore -ne $ExpectedTip) {
        $pushAttempted = $true
        & git -C $WorktreeRoot push origin $exactRefspec
        if ($LASTEXITCODE -ne 0) {
            throw "Exact reviewed topic publication failed in the interactive credential context."
        }
        $pushPerformed = $true
    }
    $remoteTipAfter = Get-WeatherPreparationRemoteTip `
        -Root $WorktreeRoot -RemoteRef $remoteRef
    if ($remoteTipAfter -ne $ExpectedTip) {
        throw "Live origin did not acknowledge the exact reviewed topic tip."
    }

    $stage = "refresh_remote_tracking_ref"
    $fetchRefspec = "${remoteRef}:refs/remotes/origin/$topicBranch"
    & git -C $RepoRoot fetch --no-tags origin $fetchRefspec
    if ($LASTEXITCODE -ne 0) {
        throw "Could not refresh the exact local remote-tracking topic ref."
    }
    $trackingTip = (Invoke-WeatherPreparationGitLine `
        -Root $RepoRoot -Arguments @("rev-parse", $BranchRef) `
        -Label "the refreshed remote-tracking topic ref").ToLowerInvariant()
    if ($trackingTip -ne $ExpectedTip) {
        throw "Refreshed remote-tracking topic ref does not match the exact reviewed tip."
    }

    $stage = "create_immutable_attempt"
    # From this boundary the child may have frozen a manifest even if its
    # process later returns nonzero or the file becomes unreadable. Closure is
    # permanently required; absence is unproved state, never no-mutation proof.
    $closureRequired = $true
    $creatorChild = Invoke-WeatherIntegrationPowerShellChild `
        -ScriptPath $creatorPath `
        -ExpectedSha256 ([string]$scriptBindings.creator.sha256) `
        -Arguments $creatorArguments `
        -Label "integration attempt creator"
    if ($creatorChild.ExitCode -ne 0) {
        $creatorDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $creatorChild
        throw "Immutable integration attempt creation failed with exit $($creatorChild.ExitCode): $creatorDiagnostic"
    }
    $manifestSha256 = Get-WeatherIntegrationFileSha256 -Path $manifestPath

    $stage = "register_exact_tasks"
    $registrarPath = [string]$scriptBindings.registrar.path
    # Attempt creation can be slow. Never arm Scheduler from a window whose
    # ten-minute preparation reserve has already been consumed.
    $registrationSchedule = Assert-WeatherIntegrationPreparationSchedule `
        -SuiteAtLocal $schedule.suite_at_local `
        -MergeAtLocal $schedule.merge_at_local `
        -Now (Get-Date) `
        -MinimumLeadMinutes 10
    $registrarChild = Invoke-WeatherIntegrationPowerShellChild `
        -ScriptPath $registrarPath `
        -ExpectedSha256 ([string]$scriptBindings.registrar.sha256) `
        -Arguments @(
            "-RepoRoot", $RepoRoot,
            "-ManifestPath", $manifestPath,
            "-ExpectedManifestSha256", $manifestSha256,
            "-MinimumSuiteLeadMinutes", "10",
            "-StageDisabled"
        ) `
        -Label "integration attempt registrar"
    if ($registrarChild.ExitCode -ne 0) {
        $registrarDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $registrarChild
        throw "Exact integration task registration failed with exit $($registrarChild.ExitCode): $registrarDiagnostic"
    }

    $stage = "assert_final_readiness"
    $readinessPath = [string]$scriptBindings.readiness.path
    $readinessChild = Invoke-WeatherIntegrationPowerShellChild `
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
        -Label "integration attempt readiness assertion"
    $readinessOutput = @($readinessChild.Output)
    if ($readinessChild.ExitCode -ne 0) {
        $readinessDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $readinessChild
        throw "Final integration readiness assertion failed with exit $($readinessChild.ExitCode): $readinessDiagnostic"
    }
    $readinessResult = Read-WeatherIntegrationSharedJson -Path $readinessResultPath
    if ([string]$readinessResult.schema -ne "weather_integration_attempt_readiness_receipt_v1" -or
        [string]$readinessResult.status -ne "PASS" -or
        [string]$readinessResult.manifest_sha256 -ne $manifestSha256 -or
        [string]$readinessResult.preparation_intent_sha256 -ne $intentSha256) {
        throw "Final readiness assertion did not leave the exact durable PASS receipt."
    }

    $stage = "activate_exact_tasks"
    $readinessReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $readinessResultPath
    $activatorPath = [string]$scriptBindings.activator.path
    $activatorChild = Invoke-WeatherIntegrationPowerShellChild `
        -ScriptPath $activatorPath `
        -ExpectedSha256 ([string]$scriptBindings.activator.sha256) `
        -Arguments @(
            "-ManifestPath", $manifestPath,
            "-ExpectedManifestSha256", $manifestSha256,
            "-PreparationIntentPath", $intentPath,
            "-ExpectedPreparationIntentSha256", $intentSha256,
            "-ReadinessReceiptPath", $readinessResultPath,
            "-ExpectedReadinessReceiptSha256", $readinessReceiptSha256,
            "-ResultPath", $resultPath
        ) `
        -Label "integration attempt activator"
    if ($activatorChild.ExitCode -ne 0) {
        $activatorDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
            -ChildResult $activatorChild
        throw "Exact integration task activation failed with exit $($activatorChild.ExitCode): $activatorDiagnostic"
    }
    $activationReceipt = Read-WeatherIntegrationSharedJson -Path $resultPath
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
    $status = "PASS"
}
catch {
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
            $closureChild = Invoke-WeatherIntegrationPowerShellChild `
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
                -Label "integration attempt closer"
            $closureOutput = @($closureChild.Output)
            if ($closureChild.ExitCode -ne 0) {
                $closureDiagnostic = Get-WeatherIntegrationChildDiagnosticExcerpt `
                    -ChildResult $closureChild
                throw "Canonical close failed with exit $($closureChild.ExitCode): $closureDiagnostic"
            }
            $closureReceipt = Read-WeatherIntegrationSharedJson -Path $closureReceiptPath
            $closureReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $closureReceiptPath
            if ([string]$closureReceipt.schema -ne
                    $script:WeatherIntegrationAttemptClosureReceiptSchema -or
                [string]$closureReceipt.status -ne "FAIL" -or
                [string]$closureReceipt.classification -ne "ABANDONED" -or
                [string]$closureReceipt.attempt_id -ne $AttemptId -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$closureReceipt.manifest_path) -Right $manifestPath) -or
                [string]$closureReceipt.manifest_sha256 -ne $manifestSha256 -or
                [string]$closureReceipt.expected_tip -ne $ExpectedTip -or
                [string]$closureReceipt.reason -ne $closureReason -or
                [string]$closureReceipt.review_reference -ne $ReviewReference -or
                @($closureReceipt.tasks).Count -ne 2 -or
                @($closureReceipt.tasks | ForEach-Object {
                    [string]$_.task_name
                } | Sort-Object -Unique).Count -ne 2 -or
                @($closureReceipt.tasks | Where-Object {
                    [string]$_.task_name -notin @(
                        [string]$failedAttempt.Manifest.schedule.suite_task_name,
                        [string]$failedAttempt.Manifest.schedule.merge_task_name
                    )
                }).Count -ne 0 -or
                @($closureReceipt.tasks | Where-Object {
                    [bool]$_.exists -and -not [bool]$_.disabled
                }).Count -ne 0 -or
                -not [bool]$closureReceipt.post_disable_proof.tasks_terminal_and_disabled) {
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
    if ($null -ne $preparationMutex) {
        $preparationMutex.Dispose()
        $preparationMutex = $null
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
