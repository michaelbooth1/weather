param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)]
    [string]$AttemptRoot,
    [Parameter(Mandatory = $true)]
    [string]$AttemptId,
    [Parameter(Mandatory = $true)]
    [string]$BranchRef,
    [Parameter(Mandatory = $true)]
    [string]$WorktreeRoot,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedTip,
    [Parameter(Mandatory = $true)]
    [datetime]$SuiteAtLocal,
    [Parameter(Mandatory = $true)]
    [datetime]$MergeAtLocal,
    [Parameter(Mandatory = $true)]
    [string]$ReviewReference,
    [ValidateSet("initial", "retry_unchanged", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
    [string]$RepairClass = "initial",
    [string]$RepairOfReceiptPath,
    [string]$AdditionalPythonPath = "",
    [switch]$RequireLiveSdkContract
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Invoke-WeatherGitLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git -C $Root $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
}

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$WorktreeRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
$AttemptRoot = Resolve-WeatherIntegrationPath -Path $AttemptRoot
$ExpectedTip = $ExpectedTip.ToLowerInvariant()

if ($AttemptId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
    throw "AttemptId must contain 1-48 safe task-name characters."
}
if ($BranchRef -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$') {
    throw "BranchRef contains unsupported characters."
}
if ($ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedTip must be a full 40-character commit id."
}
if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required; a frozen attempt may only bind a reviewed tip."
}
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    throw "Repository root is missing: $RepoRoot"
}
if (-not (Test-Path -LiteralPath $WorktreeRoot -PathType Container)) {
    throw "Suite worktree is missing: $WorktreeRoot"
}
if (Test-WeatherIntegrationPathEqual -Left $RepoRoot -Right $WorktreeRoot) {
    throw "The suite worktree must be isolated from the production repository."
}
if (Test-Path -LiteralPath $AttemptRoot) {
    throw "AttemptRoot already exists. Every attempt requires a fresh evidence directory: $AttemptRoot"
}
$attemptParent = Split-Path -Parent $AttemptRoot
if (-not (Test-Path -LiteralPath $attemptParent -PathType Container)) {
    throw "AttemptRoot parent directory does not exist: $attemptParent"
}

$suiteTime = $SuiteAtLocal.TimeOfDay
$mergeTime = $MergeAtLocal.TimeOfDay
if ($SuiteAtLocal.Date -ne $MergeAtLocal.Date) {
    throw "SuiteAtLocal and MergeAtLocal must be on the same local calendar day."
}
if ($suiteTime -lt [TimeSpan]::FromMinutes(30) -or $suiteTime -ge [TimeSpan]::FromHours(9)) {
    throw "SuiteAtLocal must be in the admitted 00:30-09:00 local host window."
}
if ($mergeTime -lt [TimeSpan]::FromHours(1) -or $mergeTime -ge [TimeSpan]::FromMinutes(220)) {
    throw "MergeAtLocal must be in the guarded 01:00-03:40 quiet window."
}
if (($MergeAtLocal - $SuiteAtLocal) -lt [TimeSpan]::FromMinutes(30)) {
    throw "The merge trigger must be at least 30 minutes after the suite trigger."
}

$repairOf = $null
$priorTip = $null
$priorManifestContract = $null
if ($RepairClass -eq "initial") {
    if (-not [string]::IsNullOrWhiteSpace($RepairOfReceiptPath)) {
        throw "An initial attempt may not claim a repair receipt."
    }
}
else {
    if ([string]::IsNullOrWhiteSpace($RepairOfReceiptPath)) {
        throw "A repair attempt must bind the immutable failed receipt it replaces."
    }
    $resolvedRepairReceipt = Resolve-WeatherIntegrationPath -Path $RepairOfReceiptPath
    $priorReceipt = Read-WeatherIntegrationSharedJson -Path $resolvedRepairReceipt
    $acceptedSchemas = @(
        $script:WeatherIntegrationAttemptSuiteReceiptSchema,
        $script:WeatherIntegrationAttemptMergeReceiptSchema,
        $script:WeatherIntegrationAttemptRegistrationReceiptSchema,
        $script:WeatherIntegrationAttemptClosureReceiptSchema
    )
    if ($acceptedSchemas -notcontains [string]$priorReceipt.schema) {
        throw "RepairOfReceiptPath is not an integration-attempt suite or merge receipt."
    }
    if ([string]$priorReceipt.status -ne "FAIL") {
        throw "A repair attempt must point at a FAIL receipt; prior evidence is never replaced."
    }
    $priorManifestContract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath ([string]$priorReceipt.manifest_path) `
        -ExpectedSha256 ([string]$priorReceipt.manifest_sha256)
    $priorExpectedTipProperty = $priorReceipt.PSObject.Properties["expected_tip"]
    $priorSourceTipProperty = $priorReceipt.PSObject.Properties["source_tip"]
    if ($null -ne $priorExpectedTipProperty -and
        [string]$priorExpectedTipProperty.Value -match '^[0-9a-f]{40}$') {
        $priorTip = [string]$priorExpectedTipProperty.Value
    }
    elseif ($null -ne $priorSourceTipProperty -and
        [string]$priorSourceTipProperty.Value -match '^[0-9a-f]{40}$') {
        $priorTip = [string]$priorSourceTipProperty.Value
    }
    else {
        $priorTip = [string]$priorManifestContract.Manifest.expected_tip
    }
    if ($RepairClass -eq "retry_unchanged" -and
        [string]$priorManifestContract.Manifest.authorization.repair_class -eq "retry_unchanged") {
        throw "An unchanged retry may not follow another unchanged retry; diagnose or repair before spending another attempt."
    }
    $repairOf = [ordered]@{
        receipt_path = $resolvedRepairReceipt
        receipt_sha256 = Get-WeatherIntegrationFileSha256 -Path $resolvedRepairReceipt
        receipt_schema = [string]$priorReceipt.schema
        prior_attempt_id = [string]$priorReceipt.attempt_id
    }
}

$registeredWorktrees = Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("worktree", "list", "--porcelain")
$registered = $false
foreach ($line in ($registeredWorktrees -split "`r?`n")) {
    if ($line -like "worktree *") {
        $listedRoot = $line.Substring("worktree ".Length)
        if (Test-WeatherIntegrationPathEqual -Left $listedRoot -Right $WorktreeRoot) {
            $registered = $true
            break
        }
    }
}
if (-not $registered) {
    throw "Suite worktree is not registered under the selected repository: $WorktreeRoot"
}

$worktreeTip = (Invoke-WeatherGitLine -Root $WorktreeRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
$branchTip = (Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("rev-parse", $BranchRef)).ToLowerInvariant()
if ($worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip) {
    throw "Attempt identity mismatch. worktree=$worktreeTip branch=$branchTip expected=$ExpectedTip"
}
$worktreeStatus = Invoke-WeatherGitLine -Root $WorktreeRoot -Arguments @("status", "--porcelain")
if (-not [string]::IsNullOrWhiteSpace($worktreeStatus)) {
    throw "Suite worktree must be clean before an attempt is frozen."
}

if ($RepairClass -ne "initial") {
    $changeRows = @(
        (Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("diff", "--name-status", $priorTip, $ExpectedTip)) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($RepairClass -eq "retry_unchanged" -and $changeRows.Count -ne 0) {
        throw "retry_unchanged requires the exact same source tip as the failed attempt."
    }
    if ($RepairClass -ne "retry_unchanged" -and $changeRows.Count -eq 0) {
        throw "Repair attempt does not contain a change from prior tip $priorTip."
    }
    $changedPaths = New-Object System.Collections.Generic.List[string]
    foreach ($row in $changeRows) {
        $columns = @($row -split "`t")
        $changeKind = [string]$columns[0]
        if ($RepairClass -ne "manual_reviewed_change" -and $changeKind -notmatch '^[AM]$') {
            throw "Bounded repair classes permit only added or modified files; got $changeKind."
        }
        foreach ($path in @($columns | Select-Object -Skip 1)) {
            $changedPaths.Add(([string]$path).Replace("\", "/"))
        }
    }

    $allowedPatterns = switch ($RepairClass) {
        "retry_unchanged" { @() }
        "schema_registry" {
            @(
                '^src/weather/schema_registry_data\.py$',
                '^src/weather/schema_registry_recent_data\.py$',
                '^src/weather/schema_registry_types\.py$'
            )
        }
        "ownership_metadata" {
            @(
                '^docs/operations/module-ownership-map\.md$',
                '^tests/operations/test_module_size_audit\.py$'
            )
        }
        "orchestration_wrapper" {
            @(
                '^scripts/ops/[^/]+\.ps1$',
                '^tests/operations/test_(integration_attempt_scripts|bounded_worktree_test_suite_script|suite_gated_quiet_merge_script|quiet_window_merge_script|host_task_wrappers)\.py$',
                '^docs/(operations|ops)/[^/]+\.md$',
                '^(AGENTS\.md|scripts/ops/AGENTS\.md|tests/AGENTS\.md|docs/AGENTS\.md)$'
            )
        }
        "manual_reviewed_change" { @('^.+$') }
        default { throw "Unsupported repair class: $RepairClass" }
    }
    foreach ($path in $changedPaths) {
        $matchingPolicies = @($allowedPatterns | Where-Object { $path -match $_ })
        if ($matchingPolicies.Count -eq 0) {
            throw "RepairClass $RepairClass does not authorize changed path: $path"
        }
    }
}

$masterTip = (Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("rev-parse", "master")).ToLowerInvariant()
$originMasterTip = (Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("rev-parse", "origin/master")).ToLowerInvariant()
if ($masterTip -ne $originMasterTip) {
    throw "Production master and origin/master must be reconciled before freezing a new attempt."
}
$suiteTaskName = "WeatherIntegrationSuite_$AttemptId"
$mergeTaskName = "WeatherIntegrationMerge_$AttemptId"
$orchestrationPaths = [ordered]@{
    contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_contract.ps1"
    attempt_creator = Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1"
    attempt_registrar = Join-Path $RepoRoot "scripts\ops\register_integration_attempt.ps1"
    attempt_closer = Join-Path $RepoRoot "scripts\ops\close_integration_attempt.ps1"
    bounded_suite = Join-Path $RepoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
    attempt_suite = Join-Path $RepoRoot "scripts\ops\integration_attempt_suite.ps1"
    attempt_merge = Join-Path $RepoRoot "scripts\ops\integration_attempt_merge.ps1"
    attempt_success_gate = Join-Path $RepoRoot "scripts\ops\assert_integration_attempt_success.ps1"
    quiet_merge = Join-Path $RepoRoot "scripts\ops\quiet_window_merge.ps1"
}
$orchestration = [ordered]@{}
foreach ($name in $orchestrationPaths.Keys) {
    $path = [string]$orchestrationPaths[$name]
    $orchestration[$name] = [ordered]@{
        path = $path
        sha256 = Get-WeatherIntegrationFileSha256 -Path $path
    }
}

New-Item -ItemType Directory -Path $AttemptRoot -ErrorAction Stop | Out-Null
$manifestPath = Join-Path $AttemptRoot "manifest.json"
$manifest = [ordered]@{
    schema = $script:WeatherIntegrationAttemptManifestSchema
    attempt_id = $AttemptId
    created_at_local = (Get-Date).ToString("o")
    attempt_root = $AttemptRoot
    repo_root = $RepoRoot
    worktree_root = $WorktreeRoot
    branch_ref = $BranchRef
    expected_tip = $ExpectedTip
    baseline = [ordered]@{
        master = $masterTip
        origin_master = $originMasterTip
    }
    authorization = [ordered]@{
        review_reference = $ReviewReference
        repair_class = $RepairClass
        repair_of = $repairOf
    }
    schedule = [ordered]@{
        suite_at_local = $SuiteAtLocal.ToString("o")
        merge_at_local = $MergeAtLocal.ToString("o")
        suite_task_name = $suiteTaskName
        merge_task_name = $mergeTaskName
    }
    suite = [ordered]@{
        additional_python_path = $AdditionalPythonPath
        require_live_sdk_contract = [bool]$RequireLiveSdkContract
    }
    orchestration = $orchestration
    evidence = [ordered]@{
        preflight_log = Join-Path $AttemptRoot "preflight.log"
        full_suite_log = Join-Path $AttemptRoot "full-suite.log"
        suite_receipt = Join-Path $AttemptRoot "suite-receipt.json"
        merge_receipt = Join-Path $AttemptRoot "merge-receipt.json"
        quiet_merge_report = Join-Path $AttemptRoot "quiet-merge-report.json"
        registration_receipt = Join-Path $AttemptRoot "registration-receipt.json"
        closure_receipt = Join-Path $AttemptRoot "closure-receipt.json"
    }
}

Write-WeatherIntegrationImmutableJson -Path $manifestPath -Payload $manifest
$manifestSha256 = Get-WeatherIntegrationFileSha256 -Path $manifestPath

Write-Host "Created immutable integration attempt: $AttemptId"
Write-Host "Manifest: $manifestPath"
Write-Host "Manifest SHA256: $manifestSha256"
Write-Host "Suite task: $suiteTaskName at $($SuiteAtLocal.ToString('o'))"
Write-Host "Merge task: $mergeTaskName at $($MergeAtLocal.ToString('o'))"
Write-Host "The attempt is frozen; any repair must create a new attempt id and bind this attempt's FAIL receipt."
