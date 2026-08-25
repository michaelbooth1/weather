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
    [switch]$RequireLiveSdkContract,
    [switch]$RequirePreparationAuthorization,
    [string]$PreparationIntentPath = "",
    [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
    [string]$ExpectedPreparationIntentSha256 = "",
    [switch]$PreflightOnly,
    [string]$PreflightResultPath = "",
    [string]$CreatorPreflightPlanPath = "",
    [ValidatePattern("^$|^[0-9a-fA-F]{64}$")]
    [string]$ExpectedCreatorPreflightPlanSha256 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
. (Join-Path $PSScriptRoot "integration_attempt_preparation_contract.ps1")

function Invoke-WeatherGitLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $query = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments $Arguments `
        -Label "integration-attempt creator Git"
    return ((@($query.StdoutLines) | ForEach-Object { [string]$_ }) `
        -join [Environment]::NewLine).Trim()
}

function Get-WeatherIntegrationCreatorLocalState {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$SuiteWorktreeRoot,
        [Parameter(Mandatory = $true)][string]$TopicBranch,
        [string]$RemoteTrackingRef = ""
    )

    $productionBranchBefore = Invoke-WeatherGitLine `
        -Root $RepositoryRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    $refNames = @(
        "HEAD", "refs/heads/master", "refs/remotes/origin/master"
    )
    if (-not [string]::IsNullOrWhiteSpace($RemoteTrackingRef)) {
        $refNames += $RemoteTrackingRef
    }
    $refRows = @((Invoke-WeatherGitLine `
        -Root $RepositoryRoot `
        -Arguments (@("rev-parse") + $refNames)) -split "`r?`n")
    $productionBranchAfter = Invoke-WeatherGitLine `
        -Root $RepositoryRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    if ($productionBranchBefore -cne $productionBranchAfter -or
        $refRows.Count -ne $refNames.Count -or
        @($refRows | Where-Object { $_ -cnotmatch '^[0-9a-fA-F]{40}$' }).Count -ne 0) {
        throw "Production Git changed while the creator sampled its local ref tuple."
    }

    $worktreeBranchBefore = Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("branch", "--show-current")
    $worktreeTip = (Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
    $worktreeStatus = Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("status", "--porcelain")
    $testFiles = @(
        ConvertTo-WeatherIntegrationTrackedPytestInventory -Rows @(
            (Invoke-WeatherGitLine `
                -Root $SuiteWorktreeRoot `
                -Arguments @("ls-files", "--", "tests")) -split "`r?`n"
        )
    )
    $sourceRows = @(
        (Invoke-WeatherGitLine `
            -Root $SuiteWorktreeRoot `
            -Arguments @("ls-files", "--", "*.py", "*.ps1")) -split "`r?`n"
    )
    $pythonFiles = @($sourceRows |
        ForEach-Object { ([string]$_).Replace("\", "/") } |
        Where-Object { $_ -match '(?i)\.py$' } |
        Sort-Object -Unique)
    $powerShellFiles = @($sourceRows |
        ForEach-Object { ([string]$_).Replace("\", "/") } |
        Where-Object { $_ -match '(?i)\.ps1$' } |
        Sort-Object -Unique)
    $trackedWorktree = Get-WeatherIntegrationTrackedWorktreeFingerprint `
        -WorktreeRoot $SuiteWorktreeRoot `
        -ExpectedHead $worktreeTip `
        -Phase "integration-attempt creator tracked inputs"
    $worktreeBranchAfter = Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("branch", "--show-current")
    Assert-WeatherIntegrationNoIgnoredImportArtifacts `
        -WorktreeRoot $SuiteWorktreeRoot `
        -Phase "integration-attempt creator" | Out-Null
    $closingWorktreeTip = (Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("rev-parse", "HEAD")).ToLowerInvariant()
    $closingWorktreeStatus = Invoke-WeatherGitLine `
        -Root $SuiteWorktreeRoot -Arguments @("status", "--porcelain")
    $closingProductionRefRows = @((Invoke-WeatherGitLine `
        -Root $RepositoryRoot `
        -Arguments (@("rev-parse") + $refNames)) -split "`r?`n")
    $closingProductionBranch = Invoke-WeatherGitLine `
        -Root $RepositoryRoot `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
    if ($worktreeBranchBefore -cne $worktreeBranchAfter -or
        $worktreeTip -cne $closingWorktreeTip -or
        $worktreeStatus -cne $closingWorktreeStatus) {
        throw "Suite worktree branch changed while the creator sampled its local tuple."
    }
    if ($productionBranchBefore -cne $closingProductionBranch -or
        $closingProductionRefRows.Count -ne $refNames.Count -or
        ($refRows -join "`n") -cne ($closingProductionRefRows -join "`n")) {
        throw "Production Git ref tuple changed while the creator sampled its worktree/inventory generation."
    }
    if ($productionBranchAfter -cne "master" -or
        $worktreeBranchAfter -cne $TopicBranch -or
        -not [string]::IsNullOrWhiteSpace($worktreeStatus) -or
        $testFiles.Count -le 0 -or $pythonFiles.Count -le 0 -or
        $powerShellFiles.Count -le 0) {
        throw "Creator local Git tuple is not an exact clean master/topic state."
    }

    return [pscustomobject][ordered]@{
        ProductionBranch = $closingProductionBranch
        Head = ([string]$refRows[0]).ToLowerInvariant()
        Master = ([string]$refRows[1]).ToLowerInvariant()
        OriginMaster = ([string]$refRows[2]).ToLowerInvariant()
        TopicTip = if ($refRows.Count -eq 4) {
            ([string]$refRows[3]).ToLowerInvariant()
        } else { "" }
        WorktreeBranch = $worktreeBranchAfter
        WorktreeHead = $worktreeTip
        WorktreeStatus = $worktreeStatus
        TestFileCount = $testFiles.Count
        TestInventorySha256 = Get-WeatherIntegrationInventorySha256 -Paths $testFiles
        PythonFileCount = $pythonFiles.Count
        PythonInventorySha256 = Get-WeatherIntegrationInventorySha256 -Paths $pythonFiles
        PowerShellFileCount = $powerShellFiles.Count
        PowerShellInventorySha256 = `
            Get-WeatherIntegrationInventorySha256 -Paths $powerShellFiles
        TrackedWorktreeSchema = [string]$trackedWorktree.schema_version
        TrackedWorktreeSha256 = [string]$trackedWorktree.content_sha256
        TrackedWorktreeFileCount = [int]$trackedWorktree.file_count
        TrackedWorktreeTotalBytes = [long]$trackedWorktree.total_bytes
        TrackedWorktreeLfsFileCount = [int]$trackedWorktree.lfs_file_count
    }
}

function Assert-WeatherIntegrationCreatorLocalStateUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Initial,
        [Parameter(Mandatory = $true)][object]$Final,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    foreach ($name in @(
        "ProductionBranch", "Head", "Master", "OriginMaster", "TopicTip",
        "WorktreeBranch", "WorktreeHead", "WorktreeStatus", "TestFileCount",
        "TestInventorySha256", "PythonFileCount", "PythonInventorySha256",
        "PowerShellFileCount", "PowerShellInventorySha256",
        "TrackedWorktreeSchema", "TrackedWorktreeSha256",
        "TrackedWorktreeFileCount", "TrackedWorktreeTotalBytes",
        "TrackedWorktreeLfsFileCount"
    )) {
        if ([string]$Initial.$name -cne [string]$Final.$name) {
            throw "$Phase local Git/worktree generation changed at field $name."
        }
    }
    return $Final
}

function Get-WeatherIntegrationCreatorLiveRefTuple {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$OriginUrl,
        [Parameter(Mandatory = $true)][string]$TopicBranch,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-fA-F]{40}$")]
        [string]$ExpectedMasterTip,
        [ValidatePattern("^$|^[0-9a-fA-F]{40}$")]
        [string]$ExpectedTopicTip = "",
        [switch]$AllowMissingTopic,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $topicRef = "refs/heads/$TopicBranch"
    $wantedRefs = @("refs/heads/master", $topicRef)
    $query = Invoke-WeatherIntegrationCanonicalLsRemote `
        -Root $RepositoryRoot `
        -ExpectedUrl $OriginUrl `
        -RemoteRefs $wantedRefs `
        -Label "$Phase canonical live-ref tuple"
    $rows = @($query.StdoutLines)
    $masterTip = Resolve-WeatherIntegrationRemoteTipRows `
        -Rows $rows -ExpectedRemoteRef "refs/heads/master"
    $topicTip = Resolve-WeatherIntegrationRemoteTipRows `
        -Rows $rows -ExpectedRemoteRef $topicRef `
        -AllowMissing:$AllowMissingTopic
    $expectedRowCount = if ($null -eq $topicTip) { 1 } else { 2 }
    if ($rows.Count -ne $expectedRowCount -or
        $masterTip -cne $ExpectedMasterTip.ToLowerInvariant() -or
        (-not [string]::IsNullOrWhiteSpace($ExpectedTopicTip) -and
            [string]$topicTip -cne $ExpectedTopicTip.ToLowerInvariant())) {
        throw "$Phase canonical live topic/master tuple differs from the creator boundary."
    }
    return [pscustomobject][ordered]@{
        OriginUrl = $OriginUrl
        MasterTip = $masterTip
        TopicRef = $topicRef
        TopicPresent = ($null -ne $topicTip)
        TopicTip = if ($null -eq $topicTip) { "" } else { [string]$topicTip }
    }
}

function Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged {
    param(
        [Parameter(Mandatory = $true)][object]$Initial,
        [Parameter(Mandatory = $true)][object]$Final,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    foreach ($name in @(
        "OriginUrl", "MasterTip", "TopicRef", "TopicPresent", "TopicTip"
    )) {
        if ([string]$Initial.$name -cne [string]$Final.$name) {
            throw "$Phase canonical live-ref tuple changed at field $name."
        }
    }
    return $Final
}

$RepoRoot = Resolve-WeatherIntegrationPath -Path $RepoRoot
$WorktreeRoot = Resolve-WeatherIntegrationPath -Path $WorktreeRoot
$AttemptRoot = Resolve-WeatherIntegrationPath -Path $AttemptRoot
$ExpectedTip = $ExpectedTip.ToLowerInvariant()

if ($AttemptId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
    throw "AttemptId must contain 1-48 safe task-name characters."
}
if ($BranchRef -cnotmatch
        '^origin/(?<topic>[A-Za-z0-9][A-Za-z0-9._/-]{0,192})$') {
    throw "BranchRef must be an exact origin/<topic> remote-tracking ref."
}
if ([string]$Matches.topic -cin @("master", "main")) {
    throw "BranchRef must name an origin topic branch, never a production branch."
}
$topicBranch = Get-WeatherIntegrationTopicBranchName -BranchRef $BranchRef
if ($ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedTip must be a full 40-character commit id."
}
if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required; a frozen attempt may only bind a reviewed tip."
}
if (-not $RequirePreparationAuthorization) {
    throw "Every newly created integration attempt must use the composite preparation authorization transaction."
}
if (-not [string]::IsNullOrWhiteSpace($AdditionalPythonPath)) {
    throw "AdditionalPythonPath is unsupported for integration attempts because external Python content is not frozen by the manifest."
}
if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    throw "Repository root is missing: $RepoRoot"
}
if (-not (Test-Path -LiteralPath $WorktreeRoot -PathType Container)) {
    throw "Suite worktree is missing: $WorktreeRoot"
}
Assert-WeatherIntegrationGitControlSafety `
    -RepositoryRoots @($RepoRoot, $WorktreeRoot)
$originUrl = Get-WeatherIntegrationCanonicalOriginUrl -Root $RepoRoot
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

$SuiteAtLocal = Assert-WeatherIntegrationLocalScheduleTime `
    -Value $SuiteAtLocal `
    -Label "SuiteAtLocal"
$MergeAtLocal = Assert-WeatherIntegrationLocalScheduleTime `
    -Value $MergeAtLocal `
    -Label "MergeAtLocal"
$scheduleEvidence = Get-WeatherIntegrationScheduleEvidence `
    -SuiteAtLocal $SuiteAtLocal -MergeAtLocal $MergeAtLocal
Assert-WeatherIntegrationCanonicalAttemptRoot `
    -RepositoryRoot $RepoRoot `
    -AttemptRoot $AttemptRoot `
    -AttemptId $AttemptId `
    -SuiteAtLocal $SuiteAtLocal | Out-Null
$preparationRoot = Resolve-WeatherIntegrationPath -Path ($AttemptRoot + ".preparation")
$canonicalCreatorPreflightPlanPath = Resolve-WeatherIntegrationPath -Path (
    Join-Path $preparationRoot "creator-preflight-plan.json"
)
if ($PreflightOnly) {
    if ([string]::IsNullOrWhiteSpace($PreflightResultPath)) {
        throw "PreflightOnly requires the canonical immutable PreflightResultPath."
    }
    $PreflightResultPath = Resolve-WeatherIntegrationPath -Path $PreflightResultPath
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $PreflightResultPath `
            -Right $canonicalCreatorPreflightPlanPath)) {
        throw "PreflightResultPath must be the canonical creator preflight plan path."
    }
    if (-not [string]::IsNullOrWhiteSpace($CreatorPreflightPlanPath) -or
        -not [string]::IsNullOrWhiteSpace(
            $ExpectedCreatorPreflightPlanSha256
        )) {
        throw "PreflightOnly may create a plan but may not consume a prior plan binding."
    }
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $RepoRoot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -SuiteAtLocal $SuiteAtLocal `
        -RequirePreparationRoot | Out-Null
    if (Test-Path -LiteralPath $PreflightResultPath) {
        throw "Creator preflight plan already exists and will not be replaced: $PreflightResultPath"
    }
}
else {
    if (-not [string]::IsNullOrWhiteSpace($PreflightResultPath)) {
        throw "PreflightResultPath is valid only with PreflightOnly."
    }
    if ([string]::IsNullOrWhiteSpace($CreatorPreflightPlanPath) -or
        [string]::IsNullOrWhiteSpace(
            $ExpectedCreatorPreflightPlanSha256
        )) {
        throw "Immutable attempt creation requires the exact creator preflight plan path and SHA-256."
    }
    $CreatorPreflightPlanPath = Resolve-WeatherIntegrationPath `
        -Path $CreatorPreflightPlanPath
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $CreatorPreflightPlanPath `
            -Right $canonicalCreatorPreflightPlanPath)) {
        throw "CreatorPreflightPlanPath must be the canonical creator preflight plan path."
    }
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
if ((Get-WeatherIntegrationLocalElapsedSeconds `
        -StartLocal $SuiteAtLocal -EndLocal $MergeAtLocal `
        -StartLabel "SuiteAtLocal" -EndLabel "MergeAtLocal") -lt 1800) {
    throw "The merge trigger must be at least 30 minutes after the suite trigger."
}

$repairOf = $null
$priorTip = $null
$priorManifestContract = $null
$priorClaimPath = $null
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
    $priorReceiptSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $resolvedRepairReceipt -MaximumBytes 2097152 -ContentType Json
    $priorReceipt = $priorReceiptSnapshot.Payload
    if ([string]$priorReceipt.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema) {
        throw "RepairOfReceiptPath must be the predecessor's immutable closure receipt."
    }
    if ([string]$priorReceipt.status -ne "FAIL") {
        throw "A repair attempt must point at a FAIL receipt; prior evidence is never replaced."
    }
    $priorManifestContract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath ([string]$priorReceipt.manifest_path) `
        -ExpectedSha256 ([string]$priorReceipt.manifest_sha256)
    $currentClosure = Assert-WeatherIntegrationCurrentFailClosure `
        -AttemptContract $priorManifestContract
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedRepairReceipt -Right ([string]$currentClosure.Suite.ReceiptPath)) -or
        [string]$currentClosure.Suite.ReceiptSha256 -ne
            [string]$priorReceiptSnapshot.Sha256 -or
        [string]$currentClosure.Merge.ReceiptSha256 -ne
            [string]$currentClosure.Suite.ReceiptSha256) {
        throw "Repair authority is not the predecessor's current exact Disabled closure."
    }
    $priorDispatchPath = [string]$priorManifestContract.Manifest.evidence.recovery_dispatch
    $priorDispatchSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $priorDispatchPath -MaximumBytes 2097152 -ContentType Json
    $priorDispatch = $priorDispatchSnapshot.Payload
    $priorDispatchSha256 = [string]$priorDispatchSnapshot.Sha256
    if ([string]$priorDispatch.schema -ne $script:WeatherIntegrationAttemptRecoveryDispatchSchema -or
        [string]$priorDispatch.status -ne "READY_FOR_SUCCESSOR_REVIEW" -or
        [string]$priorDispatch.repair_class -ne $RepairClass -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$priorDispatch.closure_receipt_path) -Right $resolvedRepairReceipt) -or
        [string]$priorDispatch.closure_receipt_sha256 -ne [string]$priorReceiptSnapshot.Sha256) {
        throw "The predecessor recovery dispatch does not authorize this repair class and closure receipt."
    }
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
    $priorClaimPath = Join-Path $priorManifestContract.AttemptRoot "successor-claim.json"
    if (Test-Path -LiteralPath $priorClaimPath) {
        throw "The predecessor FAIL receipt already has a successor claim and cannot authorize another attempt: $priorClaimPath"
    }
    $repairOf = [ordered]@{
        receipt_path = $resolvedRepairReceipt
        receipt_sha256 = [string]$priorReceiptSnapshot.Sha256
        receipt_schema = [string]$priorReceipt.schema
        prior_attempt_id = [string]$priorReceipt.attempt_id
        claim_path = $priorClaimPath
        dispatch_path = $priorDispatchPath
        dispatch_sha256 = $priorDispatchSha256
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

$creatorRemoteTrackingRef = if ($PreflightOnly) { "" } else { $BranchRef }
$initialCreatorState = Get-WeatherIntegrationCreatorLocalState `
    -RepositoryRoot $RepoRoot `
    -SuiteWorktreeRoot $WorktreeRoot `
    -TopicBranch $topicBranch `
    -RemoteTrackingRef $creatorRemoteTrackingRef
$worktreeTip = [string]$initialCreatorState.WorktreeHead
$branchTip = [string]$initialCreatorState.TopicTip
if ($worktreeTip -ne $ExpectedTip -or
    (-not $PreflightOnly -and $branchTip -ne $ExpectedTip)) {
    throw "Attempt identity mismatch. worktree=$worktreeTip branch=$branchTip expected=$ExpectedTip"
}
$expectedTestFileCount = [int]$initialCreatorState.TestFileCount
$expectedTestInventorySha256 = [string]$initialCreatorState.TestInventorySha256
$expectedPythonFileCount = [int]$initialCreatorState.PythonFileCount
$expectedPythonInventorySha256 = [string]$initialCreatorState.PythonInventorySha256
$expectedPowerShellFileCount = [int]$initialCreatorState.PowerShellFileCount
$expectedPowerShellInventorySha256 = `
    [string]$initialCreatorState.PowerShellInventorySha256
$expectedTrackedWorktreeSchema = [string]$initialCreatorState.TrackedWorktreeSchema
$expectedTrackedWorktreeSha256 = [string]$initialCreatorState.TrackedWorktreeSha256
$expectedTrackedWorktreeFileCount = [int]$initialCreatorState.TrackedWorktreeFileCount
$expectedTrackedWorktreeTotalBytes = [long]$initialCreatorState.TrackedWorktreeTotalBytes
$expectedTrackedWorktreeLfsFileCount = `
    [int]$initialCreatorState.TrackedWorktreeLfsFileCount
if ($expectedTestFileCount -le 0) {
    throw "The exact suite worktree contains no pytest files to freeze."
}
$maxFilesPerChunk = 20
$expectedChunkCount = [int][math]::Ceiling($expectedTestFileCount / [double]$maxFilesPerChunk)

if ($RepairClass -ne "initial") {
    $priorAncestorQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $RepoRoot `
        -Arguments @("merge-base", "--is-ancestor", $priorTip, $ExpectedTip) `
        -AllowedExitCodes @(0, 1) `
        -Label "repair-tip ancestry query"
    $priorIsAncestor = ([int]$priorAncestorQuery.ExitCode -eq 0)
    $changeRows = @(
        (Invoke-WeatherGitLine -Root $RepoRoot -Arguments @("diff", "--name-status", $priorTip, $ExpectedTip)) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    Assert-WeatherIntegrationRepairTipPolicy `
        -PriorTip $priorTip `
        -ExpectedTip $ExpectedTip `
        -PriorIsAncestor $priorIsAncestor `
        -RepairClass $RepairClass `
        -ChangeRows $changeRows | Out-Null
}

$masterTip = [string]$initialCreatorState.Master
$originMasterTip = [string]$initialCreatorState.OriginMaster
$productionHead = [string]$initialCreatorState.Head
$productionBranch = [string]$initialCreatorState.ProductionBranch
if ($masterTip -ne $originMasterTip) {
    throw "Production master and origin/master must be reconciled before freezing a new attempt."
}
if ($productionBranch -ne "master" -or $productionHead -ne $masterTip) {
    throw "The production working tree must have exact master checked out before freezing an attempt."
}
$baselineAncestorQuery = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $RepoRoot `
    -Arguments @("merge-base", "--is-ancestor", $masterTip, $ExpectedTip) `
    -AllowedExitCodes @(0, 1) `
    -Label "creator baseline ancestry query"
if ([int]$baselineAncestorQuery.ExitCode -ne 0) {
    throw "The reviewed attempt tip must contain the exact production baseline $masterTip."
}
$baselineTestRows = @(
    (Invoke-WeatherGitLine `
        -Root $RepoRoot `
        -Arguments @("ls-tree", "-r", "--name-only", $masterTip, "--", "tests")) -split "`r?`n"
)
$candidateTestRows = @(
    (Invoke-WeatherGitLine `
        -Root $RepoRoot `
        -Arguments @("ls-tree", "-r", "--name-only", $ExpectedTip, "--", "tests")) -split "`r?`n"
)
$candidateTestFiles = @(
    Assert-WeatherIntegrationCandidateTestInventory `
        -BaselinePaths $baselineTestRows `
        -CandidatePaths $candidateTestRows
)
if ($candidateTestFiles.Count -ne $expectedTestFileCount -or
    (Get-WeatherIntegrationInventorySha256 -Paths $candidateTestFiles) -cne
        $expectedTestInventorySha256) {
    throw "Candidate commit and exact worktree pytest inventories disagree."
}
$candidateSourceRows = @(
    (Invoke-WeatherGitLine `
        -Root $RepoRoot `
        -Arguments @(
            "ls-tree", "-r", "--name-only", $ExpectedTip,
            "--", "*.py", "*.ps1"
        )) -split "`r?`n"
)
$candidatePythonFiles = @($candidateSourceRows |
    ForEach-Object { ([string]$_).Replace("\", "/") } |
    Where-Object { $_ -match '(?i)\.py$' } |
    Sort-Object -Unique)
$candidatePowerShellFiles = @($candidateSourceRows |
    ForEach-Object { ([string]$_).Replace("\", "/") } |
    Where-Object { $_ -match '(?i)\.ps1$' } |
    Sort-Object -Unique)
if ($candidatePythonFiles.Count -ne $expectedPythonFileCount -or
    (Get-WeatherIntegrationInventorySha256 -Paths $candidatePythonFiles) -cne
        $expectedPythonInventorySha256 -or
    $candidatePowerShellFiles.Count -ne $expectedPowerShellFileCount -or
    (Get-WeatherIntegrationInventorySha256 -Paths $candidatePowerShellFiles) -cne
        $expectedPowerShellInventorySha256) {
    throw "Candidate commit and exact worktree syntax inventories disagree."
}
$liveSdkSensitivePaths = @(
    (Invoke-WeatherGitLine `
        -Root $RepoRoot `
        -Arguments @("diff", "--name-only", $masterTip, $ExpectedTip)) -split "`r?`n" |
        ForEach-Object { ([string]$_).Replace("\", "/") } |
        Where-Object {
            $_ -match '^src/weather/market/' -or
            $_ -match '^src/weather/operations/international_live' -or
            $_ -match '^scripts/ops/international_live' -or
            $_ -match '^tests/(?:market|operations)/test_(?:mm_|international_live)'
        }
)
if ($liveSdkSensitivePaths.Count -gt 0 -and -not $RequireLiveSdkContract) {
    throw "Live/MM-path integration requires RequireLiveSdkContract; affected paths: $($liveSdkSensitivePaths -join ', ')"
}
$suiteTaskName = "WeatherIntegrationSuite_$AttemptId"
$mergeTaskName = "WeatherIntegrationMerge_$AttemptId"
$manifestPath = Join-Path $AttemptRoot "manifest.json"
$boundedSuitePath = Join-Path $RepoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
$boundedSuiteSha256 = Get-WeatherIntegrationFileSha256 -Path $boundedSuitePath
$preparationAuthorizationRecord = $null
if ($RequirePreparationAuthorization) {
    if ([string]::IsNullOrWhiteSpace($PreparationIntentPath) -or
        [string]::IsNullOrWhiteSpace($ExpectedPreparationIntentSha256)) {
        throw "Preparation authorization requires the exact preparation intent path and SHA-256."
    }
    $resolvedPreparationIntentPath = Resolve-WeatherIntegrationPath -Path $PreparationIntentPath
    $expectedPreparationIntentPath = Resolve-WeatherIntegrationPath -Path (
        Join-Path ($AttemptRoot + ".preparation") "preparation-intent.json"
    )
    $preparationIntentSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $resolvedPreparationIntentPath -MaximumBytes 65536 -ContentType Json
    if (-not (Test-WeatherIntegrationPathEqual `
            -Left $resolvedPreparationIntentPath -Right $expectedPreparationIntentPath) -or
        [string]$preparationIntentSnapshot.Sha256 -ne
            $ExpectedPreparationIntentSha256.ToLowerInvariant()) {
        throw "Preparation authorization does not bind the canonical immutable preparation intent."
    }
    $preparationIntent = $preparationIntentSnapshot.Payload
    Assert-WeatherIntegrationRequiredProperties `
        -Object $preparationIntent `
        -Names @(
            "schema", "status", "attempt_id", "attempt_root", "repo_root",
            "worktree_root", "branch_ref", "expected_tip", "qualification"
        ) `
        -Label "Integration preparation intent"
    if ([string]$preparationIntent.schema -ne
            "weather_integration_attempt_preparation_intent_v1" -or
        [string]$preparationIntent.status -ne "PREPARED" -or
        [string]$preparationIntent.attempt_id -ne $AttemptId -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$preparationIntent.attempt_root) -Right $AttemptRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$preparationIntent.repo_root) -Right $RepoRoot) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$preparationIntent.worktree_root) -Right $WorktreeRoot) -or
        [string]$preparationIntent.branch_ref -cne $BranchRef -or
        [string]$preparationIntent.expected_tip -ne $ExpectedTip) {
        throw "Preparation intent does not bind the exact creator identity."
    }
    $intentCreatorPlanProperty =
        $preparationIntent.qualification.PSObject.Properties[
            "creator_preflight_plan_path"
        ]
    if ($null -eq $intentCreatorPlanProperty -or
        [string]::IsNullOrWhiteSpace(
            [string]$intentCreatorPlanProperty.Value
        ) -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$intentCreatorPlanProperty.Value) `
            -Right $canonicalCreatorPreflightPlanPath)) {
        throw "Preparation intent does not predeclare the canonical creator preflight plan."
    }
    $prearmingQualification = `
        Assert-WeatherIntegrationPrearmingQualificationEvidence `
            -PreparationIntentPath $resolvedPreparationIntentPath `
            -ExpectedPreparationIntentSha256 $ExpectedPreparationIntentSha256 `
            -AttemptRoot $AttemptRoot `
            -AttemptId $AttemptId `
            -RepoRoot $RepoRoot `
            -WorktreeRoot $WorktreeRoot `
            -BranchRef $BranchRef `
            -ExpectedTip $ExpectedTip `
            -BoundedSuitePath $boundedSuitePath `
            -ExpectedBoundedSuiteSha256 $boundedSuiteSha256 `
            -ExpectedTestFileCount $expectedTestFileCount `
            -ExpectedChunkCount $expectedChunkCount `
            -ExpectedTestInventorySha256 $expectedTestInventorySha256 `
            -ExpectedPythonFileCount $expectedPythonFileCount `
            -ExpectedPythonInventorySha256 $expectedPythonInventorySha256 `
            -ExpectedPowerShellFileCount $expectedPowerShellFileCount `
            -ExpectedPowerShellInventorySha256 $expectedPowerShellInventorySha256 `
            -ExpectedTrackedWorktreeSchema $expectedTrackedWorktreeSchema `
            -ExpectedTrackedWorktreeSha256 $expectedTrackedWorktreeSha256 `
            -ExpectedTrackedWorktreeFileCount $expectedTrackedWorktreeFileCount `
            -ExpectedTrackedWorktreeTotalBytes $expectedTrackedWorktreeTotalBytes `
            -ExpectedTrackedWorktreeLfsFileCount $expectedTrackedWorktreeLfsFileCount `
            -RequireLiveSdkContract ([bool]$RequireLiveSdkContract) `
            -RequireLiveWorktreeImport `
            -AllowMissing:$PreflightOnly
    $authorizationPlan = Get-WeatherIntegrationPreparationAuthorizationPlan `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -ManifestPath $manifestPath `
        -ExpectedTip $ExpectedTip `
        -PreparationIntentPath $resolvedPreparationIntentPath `
        -PreparationIntentSha256 $ExpectedPreparationIntentSha256 `
        -SuiteTaskName $suiteTaskName `
        -MergeTaskName $mergeTaskName
    if (Test-Path -LiteralPath $authorizationPlan.Path) {
        throw "Preparation execution authorization already exists before final readiness: $($authorizationPlan.Path)"
    }
    $preparationAuthorizationRecord = [ordered]@{
        required = $true
        execution_authorization_path = $authorizationPlan.Path
        execution_authorization_sha256 = $authorizationPlan.Sha256
        preparation_intent_path = $resolvedPreparationIntentPath
        preparation_intent_sha256 = $ExpectedPreparationIntentSha256.ToLowerInvariant()
        prearming_qualification_path = [string]$prearmingQualification.Path
        prearming_qualification_sha256 = if ([bool]$prearmingQualification.Present) {
            [string]$prearmingQualification.Sha256
        }
        else { $null }
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($PreparationIntentPath) -or
    -not [string]::IsNullOrWhiteSpace($ExpectedPreparationIntentSha256)) {
    throw "Preparation intent binding is valid only with RequirePreparationAuthorization."
}
$orchestrationPaths = [ordered]@{
    contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_contract.ps1"
    preparation_contract = Join-Path $RepoRoot "scripts\ops\integration_attempt_preparation_contract.ps1"
    remote_git = Join-Path $RepoRoot "scripts\ops\integration_attempt_remote_git.ps1"
    attempt_creator = Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1"
    attempt_registrar = Join-Path $RepoRoot "scripts\ops\register_integration_attempt.ps1"
    attempt_activator = Join-Path $RepoRoot "scripts\ops\activate_integration_attempt.ps1"
    attempt_closer = Join-Path $RepoRoot "scripts\ops\close_integration_attempt.ps1"
    bounded_suite = $boundedSuitePath
    attempt_suite = Join-Path $RepoRoot "scripts\ops\integration_attempt_suite.ps1"
    attempt_merge = Join-Path $RepoRoot "scripts\ops\integration_attempt_merge.ps1"
    attempt_success_gate = Join-Path $RepoRoot "scripts\ops\assert_integration_attempt_success.ps1"
    attempt_recovery_dispatch = Join-Path $RepoRoot "scripts\ops\dispatch_integration_attempt_recovery.ps1"
    boot_recovery = Join-Path $RepoRoot "scripts\ops\boot_recovery.ps1"
    register_boot_recovery = Join-Path $RepoRoot "scripts\ops\register_boot_recovery.ps1"
    quiet_merge = Join-Path $RepoRoot "scripts\ops\quiet_window_merge.ps1"
    quiet_merge_preflight = Join-Path $RepoRoot "scripts\ops\integration_attempt_quiet_merge_preflight.ps1"
    token_contract = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
    job_containment = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
    workload_admission = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
    roll_verdict = Join-Path $RepoRoot "scripts\ops\roll_verdict.ps1"
}
$orchestration = [ordered]@{}
foreach ($name in $orchestrationPaths.Keys) {
    $path = [string]$orchestrationPaths[$name]
    $orchestration[$name] = [ordered]@{
        path = $path
        sha256 = Get-WeatherIntegrationFileSha256 -Path $path
    }
}

if ($PreflightOnly) {
    # The preparer runs this exact canonical validation path before its only
    # publication boundary. BranchRef is intentionally revalidated by the
    # ordinary creator after the exact topic is published and fetched; every
    # other locally knowable rejection is proved before publication. The
    # contained child writes its result to the predeclared create-only path;
    # stdout is deliberately not an evidence transport.
    $preflightLiveBefore = Get-WeatherIntegrationCreatorLiveRefTuple `
        -RepositoryRoot $RepoRoot `
        -OriginUrl $originUrl `
        -TopicBranch $topicBranch `
        -ExpectedMasterTip $masterTip `
        -AllowMissingTopic `
        -Phase "Creator preflight publication boundary opening observation"
    $finalCreatorState = Get-WeatherIntegrationCreatorLocalState `
        -RepositoryRoot $RepoRoot `
        -SuiteWorktreeRoot $WorktreeRoot `
        -TopicBranch $topicBranch
    $preflightLiveAtWrite = Get-WeatherIntegrationCreatorLiveRefTuple `
        -RepositoryRoot $RepoRoot `
        -OriginUrl $originUrl `
        -TopicBranch $topicBranch `
        -ExpectedMasterTip $masterTip `
        -AllowMissingTopic `
        -Phase "Creator preflight publication boundary closing observation"
    Assert-WeatherIntegrationCreatorLocalStateUnchanged `
        -Initial $initialCreatorState `
        -Final $finalCreatorState `
        -Phase "Creator preflight publication boundary" | Out-Null
    Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged `
        -Initial $preflightLiveBefore `
        -Final $preflightLiveAtWrite `
        -Phase "Creator preflight publication boundary" | Out-Null
    $creatorPreflightPlan = [ordered]@{
        schema = $script:WeatherIntegrationCreatorPreflightPlanSchema
        status = "PREFLIGHT_READY"
        created_at_local = (Get-Date).ToString("o")
        attempt_id = $AttemptId
        attempt_root = $AttemptRoot
        preparation_root = $preparationRoot
        preflight_plan_path = $PreflightResultPath
        repo_root = $RepoRoot
        worktree_root = $WorktreeRoot
        branch_ref = $BranchRef
        expected_tip = $ExpectedTip
        suite_at_local = $SuiteAtLocal.ToString("o")
        suite_at_utc = [string]$scheduleEvidence.suite_at_utc
        merge_at_local = $MergeAtLocal.ToString("o")
        merge_at_utc = [string]$scheduleEvidence.merge_at_utc
        schedule_time_zone = $scheduleEvidence.time_zone
        production_baseline = $masterTip
        origin_url = $originUrl
        expected_test_file_count = $expectedTestFileCount
        expected_chunk_count = $expectedChunkCount
        expected_test_inventory_sha256 = $expectedTestInventorySha256
        expected_python_file_count = $expectedPythonFileCount
        expected_python_inventory_sha256 = $expectedPythonInventorySha256
        expected_powershell_file_count = $expectedPowerShellFileCount
        expected_powershell_inventory_sha256 = $expectedPowerShellInventorySha256
        expected_tracked_worktree_schema = $expectedTrackedWorktreeSchema
        expected_tracked_worktree_sha256 = $expectedTrackedWorktreeSha256
        expected_tracked_worktree_file_count = $expectedTrackedWorktreeFileCount
        expected_tracked_worktree_total_bytes = $expectedTrackedWorktreeTotalBytes
        expected_tracked_worktree_lfs_file_count = `
            $expectedTrackedWorktreeLfsFileCount
        repair_class = $RepairClass
        require_live_sdk_contract = [bool]$RequireLiveSdkContract
        creator = [ordered]@{
            path = [string]$orchestration.attempt_creator.path
            sha256 = [string]$orchestration.attempt_creator.sha256
        }
        preparation_contract = [ordered]@{
            path = [string]$orchestration.preparation_contract.path
            sha256 = [string]$orchestration.preparation_contract.sha256
        }
        preparation = [ordered]@{
            intent_path = $resolvedPreparationIntentPath
            intent_sha256 = $ExpectedPreparationIntentSha256.ToLowerInvariant()
            execution_authorization_sha256 = [string]$authorizationPlan.Sha256
        }
        prearming_qualification_required = $true
        prearming_qualification_present = [bool]$prearmingQualification.Present
        safety = [ordered]@{
            authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
            credential_value_access_authorized = $false
            live_exchange_mutation_authorized = $false
        }
    }
    $preflightWriteBoundaryState = Get-WeatherIntegrationCreatorLocalState `
        -RepositoryRoot $RepoRoot `
        -SuiteWorktreeRoot $WorktreeRoot `
        -TopicBranch $topicBranch
    Assert-WeatherIntegrationCreatorLocalStateUnchanged `
        -Initial $initialCreatorState `
        -Final $preflightWriteBoundaryState `
        -Phase "Creator preflight immutable-write boundary" | Out-Null
    $preflightLiveWriteBoundary = Get-WeatherIntegrationCreatorLiveRefTuple `
        -RepositoryRoot $RepoRoot `
        -OriginUrl $originUrl `
        -TopicBranch $topicBranch `
        -ExpectedMasterTip $masterTip `
        -AllowMissingTopic `
        -Phase "Creator preflight immutable-write immediate observation"
    Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged `
        -Initial $preflightLiveBefore `
        -Final $preflightLiveWriteBoundary `
        -Phase "Creator preflight immutable-write immediate boundary" | Out-Null
    Assert-WeatherIntegrationCanonicalAttemptRoot `
        -RepositoryRoot $RepoRoot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -SuiteAtLocal $SuiteAtLocal `
        -RequirePreparationRoot | Out-Null
    Write-WeatherIntegrationImmutableJson `
        -Path $PreflightResultPath -Payload $creatorPreflightPlan
    $creatorPreflightSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path $PreflightResultPath -MaximumBytes 65536 -ContentType Json
    Assert-WeatherIntegrationCreatorPreflightPlan `
        -EvidenceSnapshot $creatorPreflightSnapshot `
        -AttemptRoot $AttemptRoot `
        -AttemptId $AttemptId `
        -RepositoryRoot $RepoRoot `
        -WorktreeRoot $WorktreeRoot `
        -BranchRef $BranchRef `
        -ExpectedTip $ExpectedTip `
        -SuiteAtLocal $SuiteAtLocal `
        -MergeAtLocal $MergeAtLocal `
        -ProductionBaseline $masterTip `
        -OriginUrl $originUrl `
        -RepairClass $RepairClass `
        -RequireLiveSdkContract ([bool]$RequireLiveSdkContract) `
        -PreparationIntentPath $resolvedPreparationIntentPath `
        -ExpectedPreparationIntentSha256 $ExpectedPreparationIntentSha256 `
        -ExpectedPreparationAuthorizationSha256 $authorizationPlan.Sha256 `
        -CreatorPath ([string]$orchestration.attempt_creator.path) `
        -ExpectedCreatorSha256 ([string]$orchestration.attempt_creator.sha256) `
        -PreparationContractPath ([string]$orchestration.preparation_contract.path) `
        -ExpectedPreparationContractSha256 (
            [string]$orchestration.preparation_contract.sha256
        ) `
        -ExpectedTestFileCount $expectedTestFileCount `
        -ExpectedChunkCount $expectedChunkCount `
        -ExpectedTestInventorySha256 $expectedTestInventorySha256 `
        -ExpectedPythonFileCount $expectedPythonFileCount `
        -ExpectedPythonInventorySha256 $expectedPythonInventorySha256 `
        -ExpectedPowerShellFileCount $expectedPowerShellFileCount `
        -ExpectedPowerShellInventorySha256 $expectedPowerShellInventorySha256 `
        -ExpectedTrackedWorktreeSchema $expectedTrackedWorktreeSchema `
        -ExpectedTrackedWorktreeSha256 $expectedTrackedWorktreeSha256 `
        -ExpectedTrackedWorktreeFileCount $expectedTrackedWorktreeFileCount `
        -ExpectedTrackedWorktreeTotalBytes $expectedTrackedWorktreeTotalBytes `
        -ExpectedTrackedWorktreeLfsFileCount $expectedTrackedWorktreeLfsFileCount |
        Out-Null
    $preflightPostWriteState = Get-WeatherIntegrationCreatorLocalState `
        -RepositoryRoot $RepoRoot `
        -SuiteWorktreeRoot $WorktreeRoot `
        -TopicBranch $topicBranch
    $preflightLiveAfterWrite = Get-WeatherIntegrationCreatorLiveRefTuple `
        -RepositoryRoot $RepoRoot `
        -OriginUrl $originUrl `
        -TopicBranch $topicBranch `
        -ExpectedMasterTip $masterTip `
        -AllowMissingTopic `
        -Phase "Creator preflight immutable-write closing observation"
    Assert-WeatherIntegrationCreatorLocalStateUnchanged `
        -Initial $initialCreatorState `
        -Final $preflightPostWriteState `
        -Phase "Creator preflight immutable-write boundary" | Out-Null
    Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged `
        -Initial $preflightLiveBefore `
        -Final $preflightLiveAfterWrite `
        -Phase "Creator preflight immutable-write boundary" | Out-Null
    Write-Host "Creator preflight plan: $PreflightResultPath"
    Write-Host "Creator preflight plan SHA256: $($creatorPreflightSnapshot.Sha256)"
    return
}

$creatorPreflightSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
    -Path $CreatorPreflightPlanPath -MaximumBytes 65536 -ContentType Json
if ([string]$creatorPreflightSnapshot.Sha256 -cne
        $ExpectedCreatorPreflightPlanSha256.ToLowerInvariant()) {
    throw "Creator preflight plan changed after the preparer retained its exact bytes."
}
$creatorPreflightBinding = Assert-WeatherIntegrationCreatorPreflightPlan `
    -EvidenceSnapshot $creatorPreflightSnapshot `
    -AttemptRoot $AttemptRoot `
    -AttemptId $AttemptId `
    -RepositoryRoot $RepoRoot `
    -WorktreeRoot $WorktreeRoot `
    -BranchRef $BranchRef `
    -ExpectedTip $ExpectedTip `
    -SuiteAtLocal $SuiteAtLocal `
    -MergeAtLocal $MergeAtLocal `
    -ProductionBaseline $masterTip `
    -OriginUrl $originUrl `
    -RepairClass $RepairClass `
    -RequireLiveSdkContract ([bool]$RequireLiveSdkContract) `
    -PreparationIntentPath $resolvedPreparationIntentPath `
    -ExpectedPreparationIntentSha256 $ExpectedPreparationIntentSha256 `
    -ExpectedPreparationAuthorizationSha256 $authorizationPlan.Sha256 `
    -CreatorPath ([string]$orchestration.attempt_creator.path) `
    -ExpectedCreatorSha256 ([string]$orchestration.attempt_creator.sha256) `
    -PreparationContractPath ([string]$orchestration.preparation_contract.path) `
    -ExpectedPreparationContractSha256 (
        [string]$orchestration.preparation_contract.sha256
    ) `
    -ExpectedTestFileCount $expectedTestFileCount `
    -ExpectedChunkCount $expectedChunkCount `
    -ExpectedTestInventorySha256 $expectedTestInventorySha256 `
    -ExpectedPythonFileCount $expectedPythonFileCount `
    -ExpectedPythonInventorySha256 $expectedPythonInventorySha256 `
    -ExpectedPowerShellFileCount $expectedPowerShellFileCount `
    -ExpectedPowerShellInventorySha256 $expectedPowerShellInventorySha256 `
    -ExpectedTrackedWorktreeSchema $expectedTrackedWorktreeSchema `
    -ExpectedTrackedWorktreeSha256 $expectedTrackedWorktreeSha256 `
    -ExpectedTrackedWorktreeFileCount $expectedTrackedWorktreeFileCount `
    -ExpectedTrackedWorktreeTotalBytes $expectedTrackedWorktreeTotalBytes `
    -ExpectedTrackedWorktreeLfsFileCount $expectedTrackedWorktreeLfsFileCount
$preparationAuthorizationRecord["creator_preflight_plan_path"] =
    [string]$creatorPreflightBinding.Path
$preparationAuthorizationRecord["creator_preflight_plan_sha256"] =
    [string]$creatorPreflightBinding.Sha256

$finalCreatorState = Get-WeatherIntegrationCreatorLocalState `
    -RepositoryRoot $RepoRoot `
    -SuiteWorktreeRoot $WorktreeRoot `
    -TopicBranch $topicBranch `
    -RemoteTrackingRef $BranchRef
Assert-WeatherIntegrationCreatorLocalStateUnchanged `
    -Initial $initialCreatorState `
    -Final $finalCreatorState `
    -Phase "Attempt manifest creation boundary" | Out-Null
New-Item -ItemType Directory -Path $AttemptRoot -ErrorAction Stop | Out-Null
Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $SuiteAtLocal -RequireAttemptRoot -RequirePreparationRoot | Out-Null
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
        origin_url = $originUrl
    }
    authorization = [ordered]@{
        review_reference = $ReviewReference
        repair_class = $RepairClass
        repair_of = $repairOf
        preparation = $preparationAuthorizationRecord
    }
    schedule = [ordered]@{
        suite_at_local = $SuiteAtLocal.ToString("o")
        suite_at_utc = [string]$scheduleEvidence.suite_at_utc
        merge_at_local = $MergeAtLocal.ToString("o")
        merge_at_utc = [string]$scheduleEvidence.merge_at_utc
        time_zone = $scheduleEvidence.time_zone
        suite_task_name = $suiteTaskName
        merge_task_name = $mergeTaskName
    }
    suite = [ordered]@{
        additional_python_path = $AdditionalPythonPath
        require_live_sdk_contract = [bool]$RequireLiveSdkContract
        expected_test_file_count = $expectedTestFileCount
        max_files_per_chunk = $maxFilesPerChunk
        expected_chunk_count = $expectedChunkCount
        expected_test_inventory_sha256 = $expectedTestInventorySha256
        expected_python_file_count = $expectedPythonFileCount
        expected_python_inventory_sha256 = $expectedPythonInventorySha256
        expected_powershell_file_count = $expectedPowerShellFileCount
        expected_powershell_inventory_sha256 = $expectedPowerShellInventorySha256
        expected_tracked_worktree_schema = $expectedTrackedWorktreeSchema
        expected_tracked_worktree_sha256 = $expectedTrackedWorktreeSha256
        expected_tracked_worktree_file_count = $expectedTrackedWorktreeFileCount
        expected_tracked_worktree_total_bytes = $expectedTrackedWorktreeTotalBytes
        expected_tracked_worktree_lfs_file_count = `
            $expectedTrackedWorktreeLfsFileCount
        expected_python_environment_schema =
            [string]$prearmingQualification.Receipt.expected_python_environment_schema
        expected_python_environment_sha256 =
            [string]$prearmingQualification.Receipt.expected_python_environment_sha256
        expected_python_environment_distributions =
            [int]$prearmingQualification.Receipt.expected_python_environment_distributions
        expected_python_environment_files =
            [int]$prearmingQualification.Receipt.expected_python_environment_files
        expected_python_environment_bytes =
            [long]$prearmingQualification.Receipt.expected_python_environment_bytes
        expected_toolchain_schema =
            [string]$prearmingQualification.Receipt.expected_toolchain_schema
        expected_toolchain_sha256 =
            [string]$prearmingQualification.Receipt.expected_toolchain_sha256
        prearming_measured_duration_seconds = `
            [double]$prearmingQualification.Receipt.feasibility.measured_duration_seconds
        prearming_planning_ceiling_seconds = `
            [int]$prearmingQualification.Receipt.feasibility.planning_ceiling_seconds
        prearming_safety_margin_seconds = `
            [int]$prearmingQualification.Receipt.feasibility.safety_margin_seconds
        prearming_required_runtime_seconds = `
            [int]$prearmingQualification.Receipt.feasibility.required_runtime_seconds
        prearming_launch_grace_seconds = `
            [int]$prearmingQualification.Receipt.feasibility.launch_grace_seconds
        prearming_required_schedule_seconds = `
            [int]$prearmingQualification.Receipt.feasibility.required_schedule_seconds
        bounded_suite_max_runtime_seconds =
            [int]$prearmingQualification.Receipt.feasibility.bounded_suite_max_runtime_seconds
        suite_wrapper_teardown_allowance_seconds =
            [int]$prearmingQualification.Receipt.feasibility.suite_wrapper_teardown_allowance_seconds
        suite_task_execution_time_limit_seconds =
            [int]$prearmingQualification.Receipt.feasibility.suite_task_execution_time_limit_seconds
    }
    orchestration = $orchestration
    evidence = [ordered]@{
        preflight_log = Join-Path $AttemptRoot "preflight.log"
        full_suite_log = Join-Path $AttemptRoot "full-suite.log"
        suite_receipt = Join-Path $AttemptRoot "suite-receipt.json"
        merge_receipt = Join-Path $AttemptRoot "merge-receipt.json"
        quiet_merge_report = Join-Path $AttemptRoot "quiet-merge-report.json"
        registration_intent = Join-Path $AttemptRoot "registration-intent.json"
        registration_receipt = Join-Path $AttemptRoot "registration-receipt.json"
        closure_receipt = Join-Path $AttemptRoot "closure-receipt.json"
        recovery_dispatch = Join-Path $AttemptRoot "recovery-dispatch.json"
        reconciliation_receipt = Join-Path $AttemptRoot "reconciliation-receipt.json"
    }
}

$manifestLiveBefore = Get-WeatherIntegrationCreatorLiveRefTuple `
    -RepositoryRoot $RepoRoot `
    -OriginUrl $originUrl `
    -TopicBranch $topicBranch `
    -ExpectedMasterTip $masterTip `
    -ExpectedTopicTip $ExpectedTip `
    -Phase "Attempt manifest immutable-write opening observation"
$manifestWriteBoundaryState = Get-WeatherIntegrationCreatorLocalState `
    -RepositoryRoot $RepoRoot `
    -SuiteWorktreeRoot $WorktreeRoot `
    -TopicBranch $topicBranch `
    -RemoteTrackingRef $BranchRef
$manifestLiveAtWrite = Get-WeatherIntegrationCreatorLiveRefTuple `
    -RepositoryRoot $RepoRoot `
    -OriginUrl $originUrl `
    -TopicBranch $topicBranch `
    -ExpectedMasterTip $masterTip `
    -ExpectedTopicTip $ExpectedTip `
    -Phase "Attempt manifest immutable-write closing observation"
Assert-WeatherIntegrationCreatorLocalStateUnchanged `
    -Initial $initialCreatorState `
    -Final $manifestWriteBoundaryState `
    -Phase "Attempt manifest immutable-write boundary" | Out-Null
Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged `
    -Initial $manifestLiveBefore `
    -Final $manifestLiveAtWrite `
    -Phase "Attempt manifest immutable-write boundary" | Out-Null
Assert-WeatherIntegrationCanonicalAttemptRoot -RepositoryRoot $RepoRoot -AttemptRoot $AttemptRoot -AttemptId $AttemptId -SuiteAtLocal $SuiteAtLocal -RequireAttemptRoot -RequirePreparationRoot | Out-Null
Write-WeatherIntegrationImmutableJson -Path $manifestPath -Payload $manifest
$manifestSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $manifestPath -MaximumBytes 1048576 -ContentType Json
$manifestSha256 = [string]$manifestSnapshot.Sha256
$manifestPostWriteState = Get-WeatherIntegrationCreatorLocalState `
    -RepositoryRoot $RepoRoot `
    -SuiteWorktreeRoot $WorktreeRoot `
    -TopicBranch $topicBranch `
    -RemoteTrackingRef $BranchRef
$manifestLiveAfterWrite = Get-WeatherIntegrationCreatorLiveRefTuple `
    -RepositoryRoot $RepoRoot `
    -OriginUrl $originUrl `
    -TopicBranch $topicBranch `
    -ExpectedMasterTip $masterTip `
    -ExpectedTopicTip $ExpectedTip `
    -Phase "Attempt manifest post-write observation"
Assert-WeatherIntegrationCreatorLocalStateUnchanged `
    -Initial $initialCreatorState `
    -Final $manifestPostWriteState `
    -Phase "Attempt manifest post-write boundary" | Out-Null
Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged `
    -Initial $manifestLiveBefore `
    -Final $manifestLiveAfterWrite `
    -Phase "Attempt manifest post-write boundary" | Out-Null

if ($null -ne $priorClaimPath) {
    Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $priorManifestContract | Out-Null
    $successorClaim = [ordered]@{
        schema = $script:WeatherIntegrationAttemptSuccessorClaimSchema
        status = "CLAIMED"
        claimed_at_local = (Get-Date).ToString("o")
        predecessor_attempt_id = [string]$priorManifestContract.Manifest.attempt_id
        predecessor_receipt_path = [string]$repairOf.receipt_path
        predecessor_receipt_sha256 = [string]$repairOf.receipt_sha256
        recovery_dispatch_path = [string]$repairOf.dispatch_path
        recovery_dispatch_sha256 = [string]$repairOf.dispatch_sha256
        successor_attempt_id = $AttemptId
        successor_manifest_path = $manifestPath
        successor_manifest_sha256 = $manifestSha256
        successor_expected_tip = $ExpectedTip
        repair_class = $RepairClass
        review_reference = $ReviewReference
    }
    try {
        Assert-WeatherIntegrationRuntimeEvidenceNamespace -AttemptContract $priorManifestContract | Out-Null
        Write-WeatherIntegrationImmutableJson -Path $priorClaimPath -Payload $successorClaim
    }
    catch {
        throw "Successor claim failed after manifest creation. The unclaimed manifest is not registrable and must be reviewed: $($_.Exception.Message)"
    }
    Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath $manifestPath `
        -ExpectedSha256 $manifestSha256 | Out-Null
}

Write-Host "Created immutable integration attempt: $AttemptId"
Write-Host "Manifest: $manifestPath"
Write-Host "Manifest SHA256: $manifestSha256"
Write-Host "Suite task: $suiteTaskName at $($SuiteAtLocal.ToString('o'))"
Write-Host "Merge task: $mergeTaskName at $($MergeAtLocal.ToString('o'))"
Write-Host "The attempt is frozen; any repair must create a new attempt id and bind this attempt's FAIL receipt."
