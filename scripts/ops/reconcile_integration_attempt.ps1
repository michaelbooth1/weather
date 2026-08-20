# Reviewed terminal reconciliation for an attempt that reached production but
# could not finish its original post-publication proof. This never upgrades the
# immutable merge receipt to PASS and never authorizes downstream work.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedMergeReceiptSha256,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Notes = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

function Invoke-WeatherReconciliationGitLine {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = @(& git -C $Root @Arguments)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) {
        throw "git -C $Root $($Arguments -join ' ') failed."
    }
    return ([string]$output[-1]).Trim().ToLowerInvariant()
}

if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required for MERGED_UNVERIFIED reconciliation."
}
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$reconciliationPath = [string]$manifest.evidence.reconciliation_receipt
if (Test-Path -LiteralPath $reconciliationPath) {
    throw "Immutable reconciliation receipt already exists and will not be replaced: $reconciliationPath"
}
$mergeContract = Assert-WeatherIntegrationMergedUnverifiedReceipt `
    -AttemptContract $contract `
    -ExpectedReceiptSha256 $ExpectedMergeReceiptSha256
$mergeReceipt = $mergeContract.Receipt
$repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository virtual-environment interpreter is missing: $python"
}

$productionHead = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "HEAD")
$masterTip = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "master")
$originMaster = Invoke-WeatherReconciliationGitLine -Root $repoRoot -Arguments @("rev-parse", "origin/master")
if ($productionHead -ne $masterTip -or $masterTip -ne $originMaster) {
    throw "Reconciliation requires exact checked-out production master equal to origin/master."
}
& git -C $repoRoot merge-base --is-ancestor ([string]$mergeReceipt.production_head) $masterTip
if ($LASTEXITCODE -ne 0) {
    throw "The published integration commit is not in current master history."
}
& git -C $repoRoot merge-base --is-ancestor ([string]$manifest.expected_tip) $masterTip
if ($LASTEXITCODE -ne 0) {
    throw "The frozen source tip is not in current master history."
}

$captureOutput = @(& $python -m weather.operations.capture_recovery_check --repo-root $repoRoot --json)
$captureExitCode = $LASTEXITCODE
$capture = (($captureOutput -join "`n") | ConvertFrom-Json)
$unhealthyWorkers = @($capture.workers | Where-Object { -not [bool]$_.ok })
if ($captureExitCode -ne 0 -or -not [bool]$capture.ok -or
    @($capture.workers).Count -ne 3 -or $unhealthyWorkers.Count -ne 0) {
    throw "Current capture state is not healthy for all three workers; MERGED_UNVERIFIED remains unreconciled."
}

$taskEvidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)
$missingHistoricalProofs = @(
    foreach ($proofName in @(
        "origin_master_verified",
        "source_tip_integrated",
        "capture_recovery_proved",
        "documentation_transaction_recorded"
    )) {
        if (-not [bool]$mergeReceipt.$proofName) { $proofName }
    }
)
$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptReconciliationReceiptSchema
    status = "MERGED_RECONCILED"
    reconciled_at_local = (Get-Date).ToString("o")
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    merge_receipt_path = $mergeContract.ReceiptPath
    merge_receipt_sha256 = $mergeContract.ReceiptSha256
    historical_merge_status = "MERGED_UNVERIFIED"
    missing_historical_proofs = $missingHistoricalProofs
    historical_proof_upgraded = $false
    downstream_authorized = $false
    review_reference = $ReviewReference
    notes = $Notes
    current_proofs = [ordered]@{
        checked_out_master_equals_origin = $true
        published_integration_commit_in_history = $true
        frozen_source_tip_in_history = $true
        capture_recovery_current = $true
        production_head = $productionHead
        origin_master = $originMaster
        capture = $capture
    }
    tasks = @($taskEvidence)
    scripts = [ordered]@{
        reconciliation = [ordered]@{
            path = $PSCommandPath
            sha256 = Get-WeatherIntegrationFileSha256 -Path $PSCommandPath
        }
        contract = [ordered]@{
            path = Join-Path $PSScriptRoot "integration_attempt_contract.ps1"
            sha256 = Get-WeatherIntegrationFileSha256 -Path (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")
        }
    }
    safety = [ordered]@{
        authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $reconciliationPath -Payload $receipt
Write-Host "Reconciled attempt $($manifest.attempt_id) as non-authorizing MERGED_RECONCILED evidence."
Write-Host "The immutable MERGED_UNVERIFIED receipt remains unchanged and downstream work remains blocked."
