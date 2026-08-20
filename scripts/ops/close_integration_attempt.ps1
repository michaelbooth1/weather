# Safely abandon an attempt whose wrapper crashed or whose operator has chosen
# not to continue. Exact attempt tasks are disabled first; only then is an
# immutable FAIL receipt emitted so a replacement attempt can reference it.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$ReviewReference
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

if ([string]::IsNullOrWhiteSpace($Reason) -or [string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "Reason and ReviewReference are required to close an immutable attempt."
}
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$closurePath = [string]$manifest.evidence.closure_receipt
if (Test-Path -LiteralPath $closurePath) {
    throw "Immutable closure receipt already exists and will not be replaced: $closurePath"
}

$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
    $mergeReceipt = Read-WeatherIntegrationSharedJson -Path $mergeReceiptPath
    if ([string]$mergeReceipt.status -in @("PASS", "MERGED_UNVERIFIED")) {
        throw "An attempt that reached production cannot be abandoned or retried."
    }
}

$taskEvidence = @(Disable-WeatherIntegrationAttemptTasks -AttemptContract $contract)

$existingEvidence = New-Object System.Collections.Generic.List[object]
foreach ($path in @(
    [string]$manifest.evidence.registration_receipt,
    [string]$manifest.evidence.preflight_log,
    [string]$manifest.evidence.full_suite_log,
    [string]$manifest.evidence.suite_receipt,
    [string]$manifest.evidence.quiet_merge_report,
    [string]$manifest.evidence.merge_receipt
)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $existingEvidence.Add([ordered]@{
            path = Resolve-WeatherIntegrationPath -Path $path
            sha256 = Get-WeatherIntegrationFileSha256 -Path $path
        })
    }
}

$receipt = [ordered]@{
    schema = $script:WeatherIntegrationAttemptClosureReceiptSchema
    status = "FAIL"
    classification = "ABANDONED"
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    expected_tip = [string]$manifest.expected_tip
    closed_at_local = (Get-Date).ToString("o")
    reason = $Reason
    review_reference = $ReviewReference
    tasks = @($taskEvidence | ForEach-Object { $_ })
    preserved_evidence = @($existingEvidence | ForEach-Object { $_ })
    safety = [ordered]@{
        authority = "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY"
        credential_value_access_authorized = $false
        live_exchange_mutation_authorized = $false
    }
}
Write-WeatherIntegrationImmutableJson -Path $closurePath -Payload $receipt

Write-Host "Closed integration attempt $($manifest.attempt_id). Exact tasks are disabled and evidence is frozen."
Write-Host "A replacement attempt may bind this FAIL receipt: $closurePath"
