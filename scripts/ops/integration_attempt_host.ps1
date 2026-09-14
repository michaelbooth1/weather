# Execute only the explicit split host phase; historical full suites keep v1.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedManifestSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'integration_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
$state = Read-WeatherQualificationHostAttempt -ManifestPath $ManifestPath -ExpectedManifestSha256 $ExpectedManifestSha256
$contract, $m, $plan = $state.Contract, $state.Contract.Manifest, $state.Plan
if (-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $m.control.root 'scripts/ops'))) {
    throw 'Host entrypoint must execute the attempt-local adopted control copy'
}
Assert-WeatherQualificationControllerFiles -State $state
Assert-WeatherIntegrationAttemptNotTerminal -AttemptContract $contract -Operation 'split host acceptance'
Assert-WeatherIntegrationRepairClaim -AttemptContract $contract
. (Join-Path $PSScriptRoot 'qualification_host_identity.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$identity = Assert-WeatherQualificationS4UInvocation -AttemptContract $contract -Role host `
    -ExpectedHostId ([string]$plan.host_id) -ExpectedPrincipalId ([string]$plan.principal_id)
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot ([string]$m.control.root)
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) { throw 'Split host acceptance requires the dedicated capture installation' }
$now = [DateTimeOffset]::Now
if ($now.ToString('yyyy-MM-dd') -cne [string]$plan.local_day -or $now -lt [DateTimeOffset]::Parse([string]$plan.not_before) -or
    $now -ge [DateTimeOffset]::Parse([string]$plan.deadline) -or $now.Hour -ge 4 -or ($now.Hour -eq 0 -and $now.Minute -lt 30)) {
    throw 'Split host invocation missed its reviewed local admission window'
}
foreach ($name in @('host-receipt.json', 'host.log', 'host-claim.json', 'host-invocation.json')) {
    if (Test-Path -LiteralPath (Join-Path $contract.AttemptRoot $name)) { throw "Host attempt namespace is spent: $name" }
}
Write-WeatherIntegrationImmutableJson -Path (Join-Path $contract.AttemptRoot 'host-claim.json') -Payload ([ordered]@{
    schema = 'qualification_host_claim_v2'; manifest_sha256 = $contract.ManifestSha256; pid = $PID
    creation_utc_ticks = $identity.token.creation_utc_ticks; claimed_at = $now.ToUniversalTime().ToString('o') })
Write-WeatherIntegrationImmutableJson -Path (Join-Path $contract.AttemptRoot 'host-invocation.json') -Payload $identity
$invocationRef = Get-WeatherQualificationReference -Root $contract.AttemptRoot -Name 'host-invocation.json'
$lease, $envelope, $failure = $null, $null, $null
$status = 'FAIL'
$proofs = [ordered]@{}
$results = @{}
$before, $after = @(), @()
$zeroChildren = $false
try {
    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot ([string]$m.repo_root) -Workload ("SplitHost-" + [string]$m.attempt_id)
    if ($null -eq $lease) { throw 'Shared heavy-workload lease is occupied' }
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'split host start' | Out-Null
    $before = @(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
    $envelope = [Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$state.Policy.host.probe_commit_bytes, 64)
    foreach ($phase in @('probes', 'audit', 'metadata', 'teardown')) {
        $completed = Invoke-WeatherQualificationHostPhase -State $state -Envelope $envelope -Phase $phase -CaptureBindings $before
        $proofs[$phase] = $completed.NativeReference
        $results[$phase] = $completed.Result
    }
    $snapshot = $envelope.Snapshot(); $zeroChildren = $snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
    if (-not $zeroChildren) { throw 'Host controller still owns children after all phases' }
    $after = @(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
    if (($before | ConvertTo-Json -Compress) -cne ($after | ConvertTo-Json -Compress)) { throw 'Capture generation changed during qualification' }
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'split host completion' | Out-Null
    Assert-WeatherQualificationControllerFiles -State $state
    if ([DateTimeOffset]::UtcNow -gt [DateTimeOffset]::Parse([string]$plan.deadline)) { throw 'Host completion exceeded the absolute deadline' }
    $status = 'PASS'
}
catch { $failure = $_.Exception.Message }
try {
$probes = $null
$audit = $null
if ($results.ContainsKey('probes')) {
    $probes = [ordered]@{}
    foreach ($property in $results['probes'].probes.PSObject.Properties) {
        $ref = $property.Value
        $probes[$property.Name] = [ordered]@{ path = ('host-work/probes/' + [string]$ref.path); sha256 = $ref.sha256; size = $ref.size }
    }
}
if ($results.ContainsKey('audit') -and $null -ne $results['audit'].audit) {
    $auditPlan = Read-WeatherQualificationReference -Root $contract.AttemptRoot -Reference $plan.audit
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$auditPlan.receipt_root) -Right (Join-Path $contract.AttemptRoot 'audit-receipts'))) {
        $status = 'FAIL'; $failure = 'Noncanonical host audit receipt namespace'
    } else {
        $ref = $results['audit'].audit
        $audit = [ordered]@{ path = ('audit-receipts/' + [string]$ref.path); sha256 = $ref.sha256; size = $ref.size }
    }
}
if ([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse([string]$plan.deadline)) {
    $status = 'FAIL'; $failure = 'Host receipt publication missed its absolute deadline'
}
$receipt = [ordered]@{
    schema = 'weather_integration_attempt_host_receipt_v2'; status = $status; attempt_id = $m.attempt_id
    manifest_sha256 = $contract.ManifestSha256; host_plan_sha256 = $m.host.sha256
    registration_receipt_sha256 = $identity.registration_receipt_sha256; registration_intent_sha256 = $identity.registration_intent_sha256
    started_at = $now.ToUniversalTime().ToString('o'); completed_at = [DateTimeOffset]::UtcNow.ToString('o'); local_day = $plan.local_day
    invocation = $invocationRef; phases = $proofs; probes = $probes; audit = $audit
    configuration_sha256 = $plan.configuration.sha256; environment_sha256 = $plan.environment.sha256
    code_sha256 = $m.qualification.certificate.sha256; capture_before = $before; capture_after = $after
    teardown_proved = $zeroChildren; failure = $failure; integration_eligible = $false
}
Write-WeatherIntegrationImmutableJson -Path ([string]$m.evidence.host_receipt) -Payload $receipt
Write-WeatherIntegrationImmutableJson -Path ([string]$m.evidence.host_log) -Payload ([ordered]@{
    status = $status; manifest_sha256 = $contract.ManifestSha256; failure = $failure; integration_eligible = $false })
}
finally {
    if ($envelope) {
        try { $snapshot = $envelope.Snapshot(); $zeroChildren = $snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID } catch { $zeroChildren = $false }
        $envelope.Dispose()
    }
    if ($lease) {
        if ($zeroChildren) { Exit-WeatherHeavyWorkloadLease -Lease $lease }
        else {
            Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
            Write-WeatherIntegrationImmutableJson -Path (Join-Path $contract.AttemptRoot 'host-poison.json') -Payload ([ordered]@{
                schema = 'qualification_host_poison_v2'; manifest_sha256 = $contract.ManifestSha256; pid = $PID
                failure = 'Native zero-child teardown is unproved'; integration_eligible = $false })
        }
    }
}
if ($status -cne 'PASS') { Write-Error ("Split host attempt refused: " + $failure) -ErrorAction Continue; exit 1 }
Write-Host 'Split host proof completed; guarded integration remains separately required.'
exit 0
