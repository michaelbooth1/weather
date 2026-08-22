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

    $rows = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$rows[0])) {
        throw "Could not resolve $Label."
    }
    return ([string]$rows[0]).Trim()
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$mergeContract = Assert-WeatherIntegrationMergeReceipt `
    -AttemptContract $contract `
    -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
$manifest = $contract.Manifest
$receipt = $mergeContract.Receipt
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
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository virtual-environment interpreter is missing: $python"
}
$documentationPendingSha256 = ([string]$quietReport.documentation_transaction_pending_sha256).ToLowerInvariant()
$documentationSnapshotRelative = ([string]$quietReport.documentation_transaction_snapshot_path).Replace('\', '/')
$expectedDocumentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$documentationPendingSha256.json"
$documentationSnapshotPath = Join-Path $repoRoot ($documentationSnapshotRelative -replace '/', '\')
if ($documentationPendingSha256 -notmatch '^[0-9a-f]{64}$' -or
    $documentationSnapshotRelative -cne $expectedDocumentationSnapshotRelative -or
    (Get-WeatherIntegrationFileSha256 -Path $documentationSnapshotPath) -ne
        $documentationPendingSha256) {
    throw "Downstream authority requires the exact immutable documentation transaction snapshot."
}
$documentationSnapshot = Read-WeatherIntegrationSharedJson -Path $documentationSnapshotPath
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

$productionBranch = Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD") `
    -Label "the checked-out production branch"
$headTip = (Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-parse", "HEAD") -Label "production HEAD").ToLowerInvariant()
$masterTip = (Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-parse", "master") -Label "local master").ToLowerInvariant()
$originMasterTip = (Invoke-WeatherDownstreamGitLine `
    -Root $repoRoot -Arguments @("rev-parse", "origin/master") -Label "origin/master").ToLowerInvariant()
if ($productionBranch -ne "master" -or $headTip -ne $masterTip -or
    $masterTip -ne $originMasterTip) {
    throw "Downstream authority requires checked-out branch master with HEAD == master == origin/master. branch=$productionBranch HEAD=$headTip master=$masterTip origin/master=$originMasterTip"
}
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
& git -C $repoRoot merge-base --is-ancestor ([string]$receipt.production_head) $masterTip
if ($LASTEXITCODE -ne 0) {
    throw "The receipt's published integration tip is not in current master history."
}
& git -C $repoRoot merge-base --is-ancestor ([string]$manifest.expected_tip) $masterTip
if ($LASTEXITCODE -ne 0) {
    throw "Frozen source tip is no longer an ancestor of current master."
}

$captureOutput = @(& $python -m weather.operations.capture_recovery_check --repo-root $repoRoot --json)
$captureExitCode = $LASTEXITCODE
$capture = (($captureOutput -join "`n") | ConvertFrom-Json)
if ($captureExitCode -ne 0 -or -not [bool]$capture.ok -or @($capture.workers).Count -ne 3 -or
    @($capture.workers | Where-Object { -not [bool]$_.ok }).Count -ne 0) {
    throw "Current capture recovery proof is not healthy for all three workers."
}

[pscustomobject]@{
    authorized = $true
    attempt_id = [string]$manifest.attempt_id
    source_tip = [string]$manifest.expected_tip
    merge_task_name = [string]$manifest.schedule.merge_task_name
    integration_tip = $masterTip
    manifest_sha256 = $contract.ManifestSha256
    merge_receipt_sha256 = $mergeContract.ReceiptSha256
    quiet_merge_report_sha256 = $mergeContract.QuietReportSha256
    capture_workers = @($capture.workers).Count
    safety_authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
    credential_value_access_authorized = $false
    live_exchange_mutation_authorized = $false
} | ConvertTo-Json -Depth 5
