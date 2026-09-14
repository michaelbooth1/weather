# Read arming evidence only; no Scheduler or Git mutation and no PASS upgrade.
Set-StrictMode -Version Latest

function Assert-WeatherQualificationArming {
    param([Parameter(Mandatory = $true)]$AttemptContract)
    . (Join-Path $PSScriptRoot 'workload_admission.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
    . (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')
    $state = Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    $root = $AttemptContract.AttemptRoot; $m = $AttemptContract.Manifest
    $ref = Get-WeatherQualificationReference -Root $root -Name 'arming-receipt.json'
    $receipt = Read-WeatherQualificationReference -Root $root -Reference $ref
    Assert-WeatherQualificationFields -Value $receipt -Names @('schema', 'status', 'manifest_sha256', 'attempt_id',
        'registration_receipt_sha256', 'registration_intent_sha256', 'proof', 'native', 'completed_at',
        'host_id', 'principal_id', 'integration_eligible')
    if ([string]$receipt.schema -cne 'weather_integration_attempt_arming_receipt_v2' -or [string]$receipt.status -cne 'ARMED' -or
        [string]$receipt.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or [string]$receipt.attempt_id -cne [string]$m.attempt_id -or
        $receipt.integration_eligible -isnot [bool] -or $receipt.integration_eligible -or
        [string]$receipt.host_id -cne [string]$state.Plan.host_id -or [string]$receipt.principal_id -cne [string]$state.Plan.principal_id -or
        [string]$receipt.registration_receipt_sha256 -cne (Get-WeatherIntegrationFileSha256 -Path ([string]$m.evidence.registration_receipt)) -or
        [string]$receipt.registration_intent_sha256 -cne (Get-WeatherIntegrationFileSha256 -Path ([string]$m.evidence.registration_intent)) -or
        [string]$receipt.proof.path -cne 'arm-work/proof.json' -or [string]$receipt.native.path -cne 'arm-work/native.json') {
        throw 'Split task has no exact immutable arming authority'
    }
    $proof = Read-WeatherQualificationReference -Root $root -Reference $receipt.proof
    $native = Read-WeatherQualificationReference -Root $root -Reference $receipt.native
    Assert-WeatherQualificationArmingProof -State $state -Proof $proof -Native $native
    $completed = ConvertFrom-WeatherIntegrationEvidenceTimestamp -Value ([string]$receipt.completed_at) -Label 'armed completed_at'
    $validated = ConvertFrom-WeatherIntegrationEvidenceTimestamp -Value ([string]$proof.validated_at) -Label 'arming validated_at'
    if ($completed -lt $validated -or ($completed - $validated).TotalSeconds -gt 5 -or $completed -gt [DateTimeOffset]::UtcNow -or
        [DateTimeOffset]::UtcNow -gt [DateTimeOffset]::Parse([string]$proof.latest_merge)) { throw 'Arming publication missed freshness or planned adoption expiry' }
    return $receipt
}

function Assert-WeatherQualificationArmingProof {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)]$Proof, [Parameter(Mandatory = $true)]$Native)
    $m, $p = $State.Contract.Manifest, $State.Plan
    Assert-WeatherQualificationFields -Value $Proof -Names @('schema', 'manifest_sha256', 'host_plan_sha256', 'configuration_sha256',
        'environment_sha256', 'certificate_sha256', 'import_sha256', 'validated_at', 'latest_merge', 'signature',
        'native_parent_completion_required', 'integration_eligible')
    $maximum = $State.Measurements.phases.metadata.maximum
    if ([string]$Proof.schema -cne 'qualification_arming_proof_v2' -or
        [string]$Proof.manifest_sha256 -cne $State.Contract.ManifestSha256 -or [string]$Proof.host_plan_sha256 -cne [string]$m.host.sha256 -or
        [string]$Proof.configuration_sha256 -cne [string]$p.configuration.sha256 -or [string]$Proof.environment_sha256 -cne [string]$p.environment.sha256 -or
        [string]$Proof.certificate_sha256 -cne [string]$m.qualification.certificate.sha256 -or [string]$Proof.import_sha256 -cne [string]$m.qualification.import.sha256 -or
        [string]$Proof.signature.certificate_sha256 -cne [string]$m.qualification.certificate.sha256 -or
        [string]$Proof.signature.verified_output_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $Proof.native_parent_completion_required -isnot [bool] -or $Proof.integration_eligible -isnot [bool] -or
        $Native.completed -isnot [bool] -or $Native.teardown_proved -isnot [bool] -or
        $Proof.native_parent_completion_required -ne $true -or $Proof.integration_eligible -ne $false -or
        $Native.completed -ne $true -or $Native.teardown_proved -ne $true -or $Native.exit_code -ne 0 -or $null -ne $Native.failure -or
        $Native.elapsed_ms -le 0 -or $Native.elapsed_ms -gt 1000 * [int]$maximum.seconds -or
        $Native.peak_private_bytes -gt [UInt64]$maximum.commit_bytes -or $Native.native_peak_commit_bytes -gt [UInt64]$maximum.commit_bytes -or
        $Native.peak_working_set_bytes -gt [UInt64]$maximum.working_set_bytes -or $Native.maximum_sample_gap_ms -gt 1000 -or
        $Native.resource_samples -lt 1 -or $Native.system_commit_basis_points -gt 6600 -or
        $Native.minimum_disk_bytes -lt [UInt64]$State.Policy.host.minimum_disk_bytes) { throw 'Arming native proof failed' }
}
