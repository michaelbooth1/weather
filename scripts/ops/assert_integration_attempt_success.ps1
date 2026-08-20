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

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$mergeContract = Assert-WeatherIntegrationMergeReceipt `
    -AttemptContract $contract `
    -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
$manifest = $contract.Manifest
$receipt = $mergeContract.Receipt
$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository virtual-environment interpreter is missing: $python"
}

$masterTip = (& git -C $repoRoot rev-parse master).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0) { throw "Could not resolve local master." }
$originMasterTip = (& git -C $repoRoot rev-parse origin/master).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0) { throw "Could not resolve origin/master." }
if ($masterTip -ne $originMasterTip) {
    throw "Current master and origin/master are not exact."
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
    credential_value_read = $false
    live_exchange_mutation_attempted = $false
} | ConvertTo-Json -Depth 5
