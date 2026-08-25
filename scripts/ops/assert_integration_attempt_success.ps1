# Read-only downstream gate for a completed integration attempt. Callers must
# bind all three hashes in their own reviewed action; this script also rechecks
# current Git and capture state so a stale receipt cannot authorize work.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedMergeReceiptSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Invoke-WeatherDownstreamGitLine {
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

function Get-WeatherDownstreamLocalGitTuple {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $branchQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "$Label branch query"
    $tipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @(
            "rev-parse", "HEAD", "refs/heads/master",
            "refs/remotes/origin/master"
        ) `
        -Label "$Label ref-tuple query"
    $statusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments @("status", "--porcelain") `
        -Label "$Label tracked-worktree status query"
    $closingTipQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @(
            "rev-parse", "HEAD", "refs/heads/master",
            "refs/remotes/origin/master"
        ) `
        -Label "$Label closing ref-tuple query"
    $closingBranchQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root `
        -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
        -Label "$Label closing branch query"
    $closingStatusQuery = Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $Root -Arguments @("status", "--porcelain") `
        -Label "$Label closing tracked-worktree status query"
    $branchRows = @($branchQuery.StdoutLines)
    $tipRows = @($tipQuery.StdoutLines)
    $closingTipRows = @($closingTipQuery.StdoutLines)
    $closingBranchRows = @($closingBranchQuery.StdoutLines)
    $statusRows = @($statusQuery.StdoutLines | ForEach-Object { [string]$_ })
    $closingStatusRows = @(
        $closingStatusQuery.StdoutLines | ForEach-Object { [string]$_ }
    )
    if ($branchRows.Count -ne 1 -or $closingBranchRows.Count -ne 1 -or
        $tipRows.Count -ne 3 -or $closingTipRows.Count -ne 3 -or
        @($tipRows | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0 -or
        @($closingTipRows | Where-Object {
            ([string]$_).Trim() -cnotmatch '^[0-9a-fA-F]{40}$'
        }).Count -ne 0) {
        throw "$Label could not freeze one exact local branch/HEAD/master/origin tuple."
    }
    if (([string]$branchRows[0]).Trim() -cne
            ([string]$closingBranchRows[0]).Trim() -or
        (@($tipRows | ForEach-Object {
            ([string]$_).Trim().ToLowerInvariant()
        }) -join "`n") -cne
            (@($closingTipRows | ForEach-Object {
                ([string]$_).Trim().ToLowerInvariant()
             }) -join "`n")) {
        throw "$Label local branch/ref tuple changed while it was sampled."
    }
    if (($statusRows -join "`n") -cne ($closingStatusRows -join "`n")) {
        throw "$Label tracked-worktree state changed while it was sampled."
    }
    return [pscustomobject]@{
        Branch = ([string]$branchRows[0]).Trim()
        Head = ([string]$tipRows[0]).Trim().ToLowerInvariant()
        Master = ([string]$tipRows[1]).Trim().ToLowerInvariant()
        OriginMaster = ([string]$tipRows[2]).Trim().ToLowerInvariant()
        StatusLines = @($statusRows)
    }
}

function Get-WeatherDownstreamLiveMasterTip {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$OriginIdentity,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not [bool]$OriginIdentity.Legacy) {
        return Get-WeatherIntegrationCanonicalRemoteTip `
            -Root $Root `
            -ExpectedUrl ([string]$OriginIdentity.OriginUrl) `
            -RemoteRef "refs/heads/master" `
            -Label $Label
    }

    # Historical v1 manifests may predate the frozen canonical origin URL.
    # Keep them readable through the old exact `origin` identity, but retain
    # the bounded/no-prompt Git environment and exact one-ref parser. Every v2
    # manifest is rejected by Assert-WeatherIntegrationOriginIdentity if its
    # canonical URL is absent.
    $query = Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $Root `
        -Arguments @("ls-remote", "--heads", "origin", "refs/heads/master") `
        -Label "$Label legacy v1 query"
    $rows = @($query.StdoutLines)
    if ($rows.Count -ne 1) {
        throw "$Label legacy v1 query did not return exactly one master ref."
    }
    $columns = @(([string]$rows[0]).Trim() -split "`t")
    if ($columns.Count -ne 2 -or
        [string]$columns[0] -cnotmatch '^[0-9a-fA-F]{40}$' -or
        [string]$columns[1] -cne "refs/heads/master") {
        throw "$Label legacy v1 query returned malformed master evidence."
    }
    return ([string]$columns[0]).ToLowerInvariant()
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$originIdentity = Assert-WeatherIntegrationOriginIdentity `
    -AttemptContract $contract -Phase "downstream success gate"
$mergeContract = Assert-WeatherIntegrationMergeReceipt `
    -AttemptContract $contract `
    -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
$suiteContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $contract
$manifest = $contract.Manifest
$receipt = $mergeContract.Receipt
$suiteReceipt = $suiteContract.Receipt
if ([string]$suiteContract.ReceiptSha256 -cne
        [string]$receipt.suite_receipt_sha256) {
    throw "Downstream authority requires the exact canonically revalidated suite receipt."
}
$quietReport = $mergeContract.QuietReport
if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
    -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
    [string]$quietReport.branch -ne [string]$manifest.branch_ref -or
    [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
    [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
    [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
    [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
    [string]$quietReport.merge_commit -ne [string]$receipt.production_head -or
    -not [bool]$quietReport.capture_recovery_proved -or
    ([bool]$quietReport.execution_tape_recovery_required -and
        -not [bool]$quietReport.execution_tape_recovery_proved) -or
    -not [bool]$quietReport.documentation_transaction_recorded -or
    -not [bool]$quietReport.publication_acknowledged) {
    throw "Downstream authority requires the complete hash-bound quiet-merge publication and recovery proof."
}
$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$pythonw = Join-Path $repoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "Repository virtual-environment interpreter or Scheduler launcher is missing."
}
$expectedPythonExecutableSha256 = ""
$expectedPythonwExecutableSha256 = ""
if ([string]$manifest.schema -ceq $script:WeatherIntegrationAttemptManifestSchema) {
    $suiteResults = $suiteReceipt.logs.full_suite.test_results
    Assert-WeatherIntegrationCurrentQualifiedRuntimeFingerprints `
        -Summary $suiteResults -Expected $manifest.suite `
        -Label "downstream qualified runtime" | Out-Null
    $pythonEnvironmentSnapshot = Read-WeatherIntegrationEvidenceSnapshot `
        -Path ([string]$suiteResults.python_environment_post_path) `
        -MaximumBytes 16777216 -ContentType Json
    if ([string]$pythonEnvironmentSnapshot.Sha256 -cne
            [string]$manifest.suite.expected_python_environment_sha256 -or
        [string]$pythonEnvironmentSnapshot.Payload.schema_version -cne
            "python_environment_fingerprint_v2" -or
        [string]$pythonEnvironmentSnapshot.Payload.executable_sha256 -cnotmatch
            '^[0-9a-f]{64}$' -or
        -not (Test-WeatherIntegrationPathEqual `
            -Left ([string]$pythonEnvironmentSnapshot.Payload.executable) `
            -Right $python)) {
        throw "Downstream authority cannot bind the qualified repository Python interpreter."
    }
    $expectedPythonExecutableSha256 =
        [string]$pythonEnvironmentSnapshot.Payload.executable_sha256
    $pythonwRows = @($pythonEnvironmentSnapshot.Payload.runtime_files |
        Where-Object {
            [string]$_.kind -ceq "launcher" -and
            (Test-WeatherIntegrationPathEqual `
                -Left ([string]$_.path) -Right $pythonw)
        })
    if ($pythonwRows.Count -ne 1 -or
        [string]$pythonwRows[0].sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [long]$pythonwRows[0].length -le 0) {
        throw "Downstream authority cannot bind the qualified pythonw Scheduler launcher."
    }
    $expectedPythonwExecutableSha256 = [string]$pythonwRows[0].sha256
}
# Historical v1 attempts predate the runtime fingerprint. They remain
# structurally readable, but only v2 receives executable-hash authority here.
$documentationPendingSha256 = ([string]$quietReport.documentation_transaction_pending_sha256).ToLowerInvariant()
$documentationSnapshotRelative = ([string]$quietReport.documentation_transaction_snapshot_path).Replace('\', '/')
$expectedDocumentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$documentationPendingSha256.json"
$documentationSnapshotPath = Join-Path $repoRoot ($documentationSnapshotRelative -replace '/', '\')
if ($documentationPendingSha256 -notmatch '^[0-9a-f]{64}$' -or
    $documentationSnapshotRelative -cne $expectedDocumentationSnapshotRelative) {
    throw "Downstream authority requires the exact immutable documentation transaction snapshot."
}
$documentationEvidenceSnapshot = Read-WeatherIntegrationEvidenceSnapshot -Path $documentationSnapshotPath -MaximumBytes 2097152 -ContentType Json
if ([string]$documentationEvidenceSnapshot.Sha256 -ne $documentationPendingSha256) {
    throw "Downstream authority requires the exact immutable documentation transaction snapshot."
}
$documentationSnapshot = $documentationEvidenceSnapshot.Payload
$documentationMatches = @($documentationSnapshot.integrations | Where-Object {
    ([string]$_.integration_tip).ToLowerInvariant() -eq
        ([string]$quietReport.merge_commit).ToLowerInvariant() -and
    [string]$_.branch -ceq [string]$manifest.branch_ref -and
    ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$manifest.expected_tip
})
if ([string]$documentationSnapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
    [string]$documentationSnapshot.status -ne "PENDING" -or
    ([string]$documentationSnapshot.latest_integration_tip).ToLowerInvariant() -ne
        ([string]$quietReport.merge_commit).ToLowerInvariant() -or
    $documentationMatches.Count -ne 1) {
    throw "Downstream documentation transaction snapshot is not bound to the exact attempt."
}

$initialGit = Get-WeatherDownstreamLocalGitTuple `
    -Root $repoRoot -Label "downstream initial local Git observation"
$initialLiveMaster = Get-WeatherDownstreamLiveMasterTip `
    -Root $repoRoot -OriginIdentity $originIdentity `
    -Label "downstream initial live origin/master observation"
if ([string]$initialGit.Branch -cne "master" -or
    [string]$initialGit.Head -ne [string]$initialGit.Master -or
    [string]$initialGit.Master -ne [string]$initialGit.OriginMaster -or
    [string]$initialGit.Master -ne [string]$initialLiveMaster -or
    @($initialGit.StatusLines).Count -ne 0) {
    throw (
        "Downstream authority requires checked-out branch master with " +
        "HEAD == master == origin/master == canonical live master. " +
        "branch=$($initialGit.Branch) HEAD=$($initialGit.Head) " +
        "master=$($initialGit.Master) origin/master=$($initialGit.OriginMaster) " +
        "live=$initialLiveMaster"
    )
}
$frozenProductionTip = [string]$initialGit.Master
Assert-WeatherIntegrationNoIgnoredImportArtifacts `
    -WorktreeRoot $repoRoot `
    -Phase "downstream initial ignored import/control namespace"
$mergeFirstParent = (Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-parse", "$($receipt.production_head)^1") `
    -Label "published merge first parent").ToLowerInvariant()
$mergeSecondParent = (Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-parse", "$($receipt.production_head)^2") `
    -Label "published merge second parent").ToLowerInvariant()
$mergeParentLine = Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-list", "--parents", "-n", "1", [string]$receipt.production_head) `
    -Label "published merge parent list"
if (@($mergeParentLine -split '\s+' | Where-Object { $_ }).Count -ne 3 -or
    $mergeFirstParent -ne ([string]$quietReport.pre_merge_commit).ToLowerInvariant() -or
    $mergeSecondParent -ne [string]$manifest.expected_tip) {
    throw "Downstream authority requires the exact two-parent merge bound by the quiet report."
}
$mergeTipAncestry = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repoRoot `
    -Arguments @(
        "merge-base", "--is-ancestor", [string]$receipt.production_head,
        $frozenProductionTip
    ) `
    -AllowedExitCodes @(0, 1) `
    -Label "published integration ancestry query"
if ([int]$mergeTipAncestry.ExitCode -ne 0) {
    throw "The receipt's published integration tip is not in current master history."
}
$sourceTipAncestry = Invoke-WeatherIntegrationCheckedLocalGit `
    -Root $repoRoot `
    -Arguments @(
        "merge-base", "--is-ancestor", [string]$manifest.expected_tip,
        $frozenProductionTip
    ) `
    -AllowedExitCodes @(0, 1) `
    -Label "source-tip ancestry query"
if ([int]$sourceTipAncestry.ExitCode -ne 0) {
    throw "Frozen source tip is no longer an ancestor of current master."
}

$capturePythonEnvironment = @{
    PYTHONPATH = (Join-Path $repoRoot "src")
    PYTHONNOUSERSITE = "1"
    PYTHONSAFEPATH = "1"
    PYTHONPYCACHEPREFIX = ""
    PYTHONDONTWRITEBYTECODE = "1"
    PYTHONHASHSEED = "0"
    PYTHONUTF8 = "1"
    PYTHONIOENCODING = "utf-8"
}
$capturePythonControls = @(
    "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONHOME", "PYTHONPATH",
    "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONBREAKPOINT",
    "PYTHONOPTIMIZE", "PYTHONWARNINGS", "PYTHONINSPECT",
    "PYTHONSAFEPATH", "PYTHONCASEOK", "PYTHONEXECUTABLE",
    "PYTHONPLATLIBDIR", "PYTHONPYCACHEPREFIX",
    "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "PYTHONUTF8",
    "PYTHONIOENCODING", "PYTHONDEVMODE", "PYTHONMALLOC",
    "PYTHONPROFILEIMPORTTIME", "PYTHONTRACEMALLOC",
    "PYTHONFAULTHANDLER", "PYTHONCOERCECLOCALE",
    "PYTHONLEGACYWINDOWSSTDIO", "PYTHONLEGACYWINDOWSFSENCODING",
    "PYTHONWARNDEFAULTENCODING", "PYTHONINTMAXSTRDIGITS",
    "__PYVENV_LAUNCHER__", "COVERAGE_PROCESS_START"
)
$captureResult = Invoke-WeatherIntegrationBoundedProcess `
    -Executable $python `
    -ExpectedExecutableSha256 $expectedPythonExecutableSha256 `
    -Arguments @(
        "-m", "weather.operations.capture_recovery_check",
        "--repo-root", $repoRoot, "--json"
    ) `
    -WorkingDirectory $repoRoot `
    -TimeoutSeconds 90 `
    -Label "downstream current capture recovery proof" `
    -Environment $capturePythonEnvironment `
    -RemoveEnvironmentVariables $capturePythonControls `
    -MaxOutputBytes 1048576
try { $capture = ([string]$captureResult.Stdout | ConvertFrom-Json -ErrorAction Stop) }
catch { throw "Current capture recovery proof returned unreadable JSON." }
try {
    $captureRepoRoot = Resolve-WeatherIntegrationPath -Path ([string]$capture.repo_root)
    $captureModulePath = Resolve-WeatherIntegrationPath `
        -Path ([string]$capture.execution_identity.module_path)
    $runtimeIdentityRoot = Resolve-WeatherIntegrationPath `
        -Path ([string]$capture.execution_identity.runtime_identity.repo_root)
}
catch { throw "Current capture recovery proof has an invalid execution identity path." }
$expectedCaptureModule = Join-Path $repoRoot `
    "src\weather\operations\capture_recovery_check.py"
$runtimeIdentity = $capture.execution_identity.runtime_identity
$sourceScopeFiles = @($runtimeIdentity.source_scope_files | ForEach-Object {
    ([string]$_).Replace('\', '/')
})
if ([string]$capture.schema_version -cne "capture_recovery_check_v1" -or
    -not (Test-WeatherIntegrationPathEqual -Left $captureRepoRoot -Right $repoRoot) -or
    -not (Test-WeatherIntegrationPathEqual `
        -Left $captureModulePath -Right $expectedCaptureModule) -or
    -not (Test-WeatherIntegrationPathEqual `
        -Left $runtimeIdentityRoot -Right $repoRoot) -or
    [string]$runtimeIdentity.schema_version -cne "runtime_identity_v0.1" -or
    [string]$runtimeIdentity.identity_source -cne "git_filesystem" -or
    [string]$runtimeIdentity.source_scope -cne "loaded_modules" -or
    [string]$runtimeIdentity.git_branch -cne "master" -or
    [string]$runtimeIdentity.git_commit -cne $frozenProductionTip.Substring(0, 12) -or
    [string]$runtimeIdentity.source_fingerprint -cnotmatch '^[0-9a-f]{16}$' -or
    [int]$runtimeIdentity.source_file_count -ne $sourceScopeFiles.Count -or
    $sourceScopeFiles.Count -le 0 -or
    $sourceScopeFiles -cnotcontains
        "src/weather/operations/capture_recovery_check.py" -or
    @($sourceScopeFiles | Where-Object {
        [string]::IsNullOrWhiteSpace($_) -or $_ -match '(^|/)\.\.(/|$)' -or
        ($_ -cnotmatch '^(?:src/weather|app|weather)/' -and
         $_ -cnotin @("sitecustomize.py", "requirements.txt"))
    }).Count -ne 0 -or
    -not [bool]$capture.ok -or @($capture.workers).Count -ne 3 -or
    @($capture.workers | Where-Object { -not [bool]$_.ok }).Count -ne 0) {
    throw "Current capture recovery proof lacks one exact trusted execution identity or three-worker health proof."
}

# Capture health and Git identity belong to one authority generation. Re-read
# the complete local tuple and canonical live ref after the child exits; any
# transition during proof collection refuses authorization.
$finalGit = Get-WeatherDownstreamLocalGitTuple `
    -Root $repoRoot -Label "downstream final local Git observation"
Assert-WeatherIntegrationNoIgnoredImportArtifacts `
    -WorktreeRoot $repoRoot `
    -Phase "downstream final ignored import/control namespace"
$finalLiveMaster = Get-WeatherDownstreamLiveMasterTip `
    -Root $repoRoot -OriginIdentity $originIdentity `
    -Label "downstream final live origin/master observation"
Assert-WeatherIntegrationNoIgnoredImportArtifacts `
    -WorktreeRoot $repoRoot `
    -Phase "downstream closing ignored import/control namespace"
$closingGit = Get-WeatherDownstreamLocalGitTuple `
    -Root $repoRoot -Label "downstream closing local Git observation"
if ([string]$finalGit.Branch -cne [string]$initialGit.Branch -or
    [string]$finalGit.Head -ne [string]$initialGit.Head -or
    [string]$finalGit.Master -ne [string]$initialGit.Master -or
    [string]$finalGit.OriginMaster -ne [string]$initialGit.OriginMaster -or
    @($finalGit.StatusLines).Count -ne 0 -or
    [string]$finalLiveMaster -ne [string]$initialLiveMaster -or
    [string]$closingGit.Branch -cne [string]$finalGit.Branch -or
    [string]$closingGit.Head -ne [string]$finalGit.Head -or
    [string]$closingGit.Master -ne [string]$finalGit.Master -or
    [string]$closingGit.OriginMaster -ne [string]$finalGit.OriginMaster -or
    @($closingGit.StatusLines).Count -ne 0) {
    throw "Production Git or canonical live master changed during downstream proof collection."
}

[pscustomobject]@{
    authorized = $true
    attempt_id = [string]$manifest.attempt_id
    source_tip = [string]$manifest.expected_tip
    merge_task_name = [string]$manifest.schedule.merge_task_name
    integration_tip = $frozenProductionTip
    python_executable = $python
    python_executable_sha256 = $expectedPythonExecutableSha256
    pythonw_executable = $pythonw
    pythonw_executable_sha256 = $expectedPythonwExecutableSha256
    python_binding_authority = if (
        [string]::IsNullOrWhiteSpace($expectedPythonExecutableSha256)
    ) {
        "CURRENT_LEGACY_INTERPRETER"
    }
    else {
        "IMMUTABLE_FULL_SUITE_ENVIRONMENT"
    }
    manifest_sha256 = $contract.ManifestSha256
    merge_receipt_sha256 = $mergeContract.ReceiptSha256
    quiet_merge_report_sha256 = $mergeContract.QuietReportSha256
    canonical_origin_url = if ([bool]$originIdentity.Legacy) {
        ""
    }
    else { [string]$originIdentity.OriginUrl }
    canonical_origin_legacy = [bool]$originIdentity.Legacy
    capture_workers = @($capture.workers).Count
    final_local_git = [ordered]@{
        branch = [string]$closingGit.Branch
        head = [string]$closingGit.Head
        master = [string]$closingGit.Master
        origin_master = [string]$closingGit.OriginMaster
    }
    final_live_master = [string]$finalLiveMaster
    safety_authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
    credential_value_access_authorized = $false
    live_exchange_mutation_authorized = $false
} | ConvertTo-Json -Depth 5
