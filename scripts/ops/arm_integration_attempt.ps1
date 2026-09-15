# Finalize only an already registered, otherwise inert split attempt.
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
. (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_arming_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_durable_json.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$contract = Assert-WeatherIntegrationAttemptManifest -ManifestPath $ManifestPath -ExpectedSha256 $ExpectedManifestSha256
if ((Get-WeatherIntegrationPrerequisite -AttemptContract $contract).Version -cne 'v2') { throw 'Arming is only defined for split v2' }
$state = Read-WeatherQualificationHostAttempt -ManifestPath $ManifestPath -ExpectedManifestSha256 $ExpectedManifestSha256
$m = $contract.Manifest
if (-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $m.control.root 'scripts/ops'))) { throw 'Arming must run from adopted frozen B' }
Assert-WeatherQualificationOrchestration -AttemptContract $contract
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot ([string]$m.control.root)
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id -or
    (Get-WeatherExecutionHostId) -cne [string]$state.Plan.host_id -or (Get-WeatherExecutionPrincipalId) -cne [string]$state.Plan.principal_id) {
    throw 'Arming host/principal is not the reviewed capture installation'
}
$terminal = Enter-WeatherIntegrationControlMutex -RepositoryRoot ([string]$m.repo_root) -LockLeaf 'integration_attempt_terminal.lock' -Owner ('arm:' + $m.attempt_id)
if ($null -eq $terminal) { throw 'Integration terminal mutex is occupied' }
$lease, $envelope = $null, $null
$zero = $true
try {
    Assert-WeatherIntegrationAttemptNotTerminal -AttemptContract $contract -Operation 'split arming'
    $registration = Assert-WeatherIntegrationRegistrationReceipt -AttemptContract $contract -RequirePass
    foreach ($role in @('host', 'merge')) {
        $bound = Assert-WeatherIntegrationScheduledTaskBinding -AttemptContract $contract -Role $role -BindingEvidence $registration.Intent
        if ([string]$bound.Task.State -cne 'Ready') { throw 'Arming requires both exact registered tasks to remain Ready' }
    }
    if ([DateTimeOffset]::Now -ge [DateTimeOffset]::Parse([string]$m.schedule.host_at_local).AddMinutes(-1)) { throw 'Arming missed the pre-trigger reserve' }
    foreach ($name in @('arming-receipt.json', 'arm-work', 'host-claim.json', 'merge-invocation.json')) {
        if (Test-Path -LiteralPath (Join-Path $contract.AttemptRoot $name)) { throw 'Arming namespace already spent or execution started' }
    }
    $now = Get-Date
    if ($now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30)) { throw 'Arming verification is outside capture-host heavy-work admission' }
    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot ([string]$m.repo_root) -Workload ('SplitArm-' + $m.attempt_id)
    if ($null -eq $lease) { throw 'Shared heavy-workload lease is occupied' }
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'split arming' | Out-Null
    $maximum = $state.Measurements.phases.metadata.maximum
    $seconds = [int]$maximum.seconds
    if ($seconds -le 5 -or $seconds -gt 120 -or $seconds -gt [int]$state.Policy.host.metadata_seconds -or
        [UInt64]$maximum.commit_bytes -gt [UInt64]$state.Policy.host.audit_commit_bytes -or
        [UInt64]$maximum.working_set_bytes -gt [UInt64]$state.Policy.host.audit_working_set_bytes) { throw 'Arming exceeds reviewed metadata budget' }
    $directory = Join-Path $contract.AttemptRoot 'arm-work'
    [void][IO.Directory]::CreateDirectory($directory)
    $capture = @(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($seconds)
    $admissionEnd = [DateTimeOffset]::new((Get-Date).Date.AddHours(9))
    $triggerReserve = [DateTimeOffset]::Parse([string]$m.schedule.host_at_local).AddMinutes(-1)
    if ($deadline -gt $admissionEnd -or $deadline -gt $triggerReserve) { throw 'Arming cannot finish before admission or trigger reserve' }
    $request = [ordered]@{ manifest_path=$contract.ManifestPath; manifest_sha256=$contract.ManifestSha256; purpose='arm'
        deadline=$deadline.AddSeconds(-4).ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", [Globalization.CultureInfo]::InvariantCulture) }
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'request.json') -Payload $request
    $ref = Get-WeatherQualificationReference -Root $directory -Name 'request.json'
    Set-WeatherQualificationOfflineEnvironment -Profile $state.Profile -Scratch $directory
    $envelope = [Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$maximum.commit_bytes, 64)
    $zero = $false
    $python = Join-Path $state.Profile.tools.python.root $state.Profile.tools.python.path
    $tokens = @('-I', '-S', '-B', (Join-Path $m.control.root 'scripts/ops/qualification_arm_control.py'), (Join-Path $directory 'request.json'), [string]$ref.sha256)
    $native = Invoke-WeatherQualificationProcess -Envelope $envelope -Executable $python -Tokens $tokens `
        -WorkingDirectory ([string]$m.control.root) -Transcript (Join-Path $directory 'native.log') `
        -DeadlineUtc $deadline -MaximumSeconds ($seconds - 3) -TeardownSeconds 3 `
        -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) `
        -MaximumOutputBytes 2097152 -VolumePaths @([string]$m.repo_root, $directory) `
        -MinimumDiskBytes ([UInt64]$state.Policy.host.minimum_disk_bytes) -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
        -ResourceMode capture_s4u -ProductionRoot ([string]$m.repo_root) -CaptureBindings $capture
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
    $snapshot = $envelope.Snapshot(); $zero = $snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
    if (-not $zero) { throw 'Arming native child tree did not drain' }
    $proofRef = Get-WeatherQualificationReference -Root $contract.AttemptRoot -Name 'arm-work/proof.json'
    $proof = Read-WeatherQualificationReference -Root $contract.AttemptRoot -Reference $proofRef
    Assert-WeatherQualificationArmingProof -State $state -Proof $proof -Native $native
    $registration = Assert-WeatherIntegrationRegistrationReceipt -AttemptContract $contract -RequirePass
    Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'arming publication' | Out-Null
    Assert-WeatherQualificationCapture -ProductionRoot ([string]$m.repo_root) -Bindings $capture
    $completed = [DateTimeOffset]::UtcNow
    if (($completed - [DateTimeOffset]::Parse([string]$proof.validated_at)).TotalSeconds -gt 5 -or $completed -gt $deadline) { throw 'Arming proof expired before publication' }
    Write-WeatherQualificationImmutableJson -Path (Join-Path $contract.AttemptRoot 'arming-receipt.json') -Payload ([ordered]@{
        schema='weather_integration_attempt_arming_receipt_v2'; status='ARMED'; manifest_sha256=$contract.ManifestSha256; attempt_id=$m.attempt_id
        registration_receipt_sha256=$registration.ReceiptSha256; registration_intent_sha256=$registration.IntentSha256
        proof=$proofRef; native=(Get-WeatherQualificationReference -Root $contract.AttemptRoot -Name 'arm-work/native.json')
        completed_at=$completed.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", [Globalization.CultureInfo]::InvariantCulture)
        host_id=$state.Plan.host_id; principal_id=$state.Plan.principal_id; integration_eligible=$false })
    Assert-WeatherQualificationArming -AttemptContract $contract | Out-Null
}
finally {
    if ($envelope) {
        try { $snapshot=$envelope.Snapshot(); $zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID } catch { $zero=$false }
        if (-not $zero -and $lease) { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
        $envelope.Dispose()
    }
    if ($lease -and $zero) { Exit-WeatherHeavyWorkloadLease -Lease $lease }
    Exit-WeatherIntegrationControlMutex -Mutex $terminal
}
Write-Host 'Split attempt armed; host acceptance and guarded merge remain separately required.'
