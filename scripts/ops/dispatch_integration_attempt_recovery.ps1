# Turn one closed integration attempt into a single, reviewed, machine-readable
# recovery instruction. This script never edits source, creates a successor,
# touches Task Scheduler, or starts work. The successor creator separately
# consumes the closure receipt and atomically claims it.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedManifestSha256,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedClosureReceiptSha256,
    [Parameter(Mandatory = $true)]
    [ValidateSet("transient_host", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
    [string]$FailureClass,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Notes = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "integration_attempt_contract.ps1")

if ([string]::IsNullOrWhiteSpace($ReviewReference)) {
    throw "ReviewReference is required; recovery classification must be reviewed."
}

$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $ManifestPath `
    -ExpectedSha256 $ExpectedManifestSha256
$manifest = $contract.Manifest
$orchestrationDrift = New-Object System.Collections.Generic.List[object]
foreach ($binding in @($manifest.orchestration.PSObject.Properties)) {
    $record = $binding.Value
    $actualSha256 = $null
    try { $actualSha256 = Get-WeatherIntegrationFileSha256 -Path ([string]$record.path) }
    catch { }
    if ($actualSha256 -ne [string]$record.sha256) {
        $orchestrationDrift.Add([ordered]@{
            name = [string]$binding.Name
            path = [string]$record.path
            expected_sha256 = [string]$record.sha256
            actual_sha256 = $actualSha256
        })
    }
}
if ($orchestrationDrift.Count -ne 0 -and $FailureClass -ne "orchestration_wrapper") {
    throw "Frozen orchestration drift exists; recovery must classify and review it as orchestration_wrapper."
}
$dispatchPath = [string]$manifest.evidence.recovery_dispatch
if (Test-Path -LiteralPath $dispatchPath) {
    throw "Immutable recovery dispatch already exists and will not be replaced: $dispatchPath"
}

$mergeReceiptPath = [string]$manifest.evidence.merge_receipt
if (Test-Path -LiteralPath $mergeReceiptPath -PathType Leaf) {
    $mergeReceipt = Read-WeatherIntegrationSharedJson -Path $mergeReceiptPath
    if ([string]$mergeReceipt.status -eq "PASS") {
        throw "A successfully merged attempt does not permit recovery dispatch."
    }
}

$closurePath = [string]$manifest.evidence.closure_receipt
$actualClosureSha256 = Get-WeatherIntegrationFileSha256 -Path $closurePath
if ($actualClosureSha256 -ne $ExpectedClosureReceiptSha256.ToLowerInvariant()) {
    throw "Closure receipt hash mismatch. Expected $ExpectedClosureReceiptSha256; got $actualClosureSha256"
}
$closure = Read-WeatherIntegrationSharedJson -Path $closurePath
if ([string]$closure.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
    [string]$closure.status -ne "FAIL" -or
    [string]$closure.attempt_id -ne [string]$manifest.attempt_id -or
    -not (Test-WeatherIntegrationPathEqual -Left ([string]$closure.manifest_path) -Right $contract.ManifestPath) -or
    [string]$closure.manifest_sha256 -ne [string]$contract.ManifestSha256) {
    throw "Closure receipt does not bind this exact failed attempt."
}
$unsafeTasks = @($closure.tasks | Where-Object { [bool]$_.exists -and -not [bool]$_.disabled })
if ($unsafeTasks.Count -ne 0) {
    throw "Closure receipt does not prove every existing attempt task was disabled."
}

$claimPath = Join-Path $contract.AttemptRoot "successor-claim.json"
if (Test-Path -LiteralPath $claimPath) {
    throw "This failed attempt already authorized a successor: $claimPath"
}

$repairClass = switch ($FailureClass) {
    "transient_host" { "retry_unchanged" }
    "schema_registry" { "schema_registry" }
    "ownership_metadata" { "ownership_metadata" }
    "orchestration_wrapper" { "orchestration_wrapper" }
    "manual_reviewed_change" { "manual_reviewed_change" }
}
if ($repairClass -eq "retry_unchanged" -and
    [string]$manifest.authorization.repair_class -eq "retry_unchanged") {
    throw "A transient dispatch cannot authorize a consecutive unchanged retry."
}

$dispatch = [ordered]@{
    schema = $script:WeatherIntegrationAttemptRecoveryDispatchSchema
    status = "READY_FOR_SUCCESSOR_REVIEW"
    dispatched_at_local = (Get-Date).ToString("o")
    attempt_id = [string]$manifest.attempt_id
    manifest_path = $contract.ManifestPath
    manifest_sha256 = $contract.ManifestSha256
    closure_receipt_path = $closurePath
    closure_receipt_sha256 = $actualClosureSha256
    failure_class = $FailureClass
    repair_class = $repairClass
    review_reference = $ReviewReference
    notes = $Notes
    orchestration_drift = @($orchestrationDrift | ForEach-Object { $_ })
    successor = [ordered]@{
        predecessor_claim_path = $claimPath
        expected_tip_rule = if ($repairClass -eq "retry_unchanged") { "EXACT_SAME_COMMIT" } else { "DESCENDANT_WITH_REVIEWED_CHANGE" }
        prior_expected_tip = [string]$manifest.expected_tip
        source_change_required = ($repairClass -ne "retry_unchanged")
        allowed_path_patterns = @(Get-WeatherIntegrationRepairAllowedPatterns -RepairClass $repairClass)
        repair_of_receipt_path = $closurePath
        repair_of_receipt_sha256 = $actualClosureSha256
    }
    automatic_source_edit_authorized = $false
    scheduler_change_authorized = $false
    credential_value_read = $false
    live_exchange_mutation_attempted = $false
}
Write-WeatherIntegrationImmutableJson -Path $dispatchPath -Payload $dispatch

$dispatch | ConvertTo-Json -Depth 10
exit 0
