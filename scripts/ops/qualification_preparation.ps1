# Complete reviewed split preparation from the currently adopted B controller.
# Imported records are data; the fixed native child proves the frozen B copy
# before any Scheduler action may point at it.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'qualification_durable_json.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_arming_contract.ps1')

function Invoke-WeatherQualificationPreparation {
    param([Parameter(Mandatory = $true)]$State)
    . (Join-Path $PSScriptRoot 'workload_admission.ps1')
    . (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
    . (Join-Path $PSScriptRoot 'qualification_process.ps1')
    $contract=$State.Contract; $m=$contract.Manifest
    if (-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $m.repo_root 'scripts/ops'))) {
        throw 'Preparation must execute currently adopted B, before trusting the copied controller'
    }
    $assignment=Get-WeatherExecutionHostAssignment -RepoRoot ([string]$m.repo_root)
    if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id -or
        (Get-WeatherExecutionHostId) -cne [string]$State.Plan.host_id -or
        (Get-WeatherExecutionPrincipalId) -cne [string]$State.Plan.principal_id) { throw 'Preparation host/principal differs' }
    $now=Get-Date
    if ($now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30)) { throw 'Preparation is outside capture-host heavy admission' }
    $maximum=$State.Measurements.phases.metadata.maximum; $seconds=[int]$maximum.seconds
    if ($seconds -le 5 -or $seconds -gt 120 -or $seconds -gt [int]$State.Policy.host.metadata_seconds -or
        [UInt64]$maximum.commit_bytes -gt [UInt64]$State.Policy.host.audit_commit_bytes -or
        [UInt64]$maximum.working_set_bytes -gt [UInt64]$State.Policy.host.audit_working_set_bytes) { throw 'Preparation exceeds reviewed metadata envelope' }
    $deadline=[DateTimeOffset]::UtcNow.AddSeconds($seconds)
    if ($deadline -gt [DateTimeOffset]::new($now.Date.AddHours(9))) { throw 'Preparation cannot finish in admission' }
    $directory=Join-Path $contract.AttemptRoot 'prepare-work'
    if (Test-Path -LiteralPath $directory) { throw 'Preparation namespace is spent' }
    $lease=$null; $envelope=$null; $zero=$true
    try {
        $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot ([string]$m.repo_root) -Workload ('SplitPrepare-'+$m.attempt_id)
        if ($null -eq $lease) { throw 'Shared heavy-workload lease is occupied' }
        Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'split preparation' | Out-Null
        [void][IO.Directory]::CreateDirectory($directory)
        $capture=@(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
        $request=[ordered]@{manifest_path=$contract.ManifestPath;manifest_sha256=$contract.ManifestSha256;purpose='prepare'
            deadline=$deadline.AddSeconds(-4).ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",[Globalization.CultureInfo]::InvariantCulture)}
        Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'request.json') -Payload $request
        $ref=Get-WeatherQualificationReference -Root $directory -Name 'request.json'
        Set-WeatherQualificationOfflineEnvironment -Profile $State.Profile -Scratch $directory
        $envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$maximum.commit_bytes,64); $zero=$false
        $python=Join-Path $State.Profile.tools.python.root $State.Profile.tools.python.path
        # Deliberately invoke adopted B in the production checkout here. The
        # candidate-provided control copy is checked by this B child first.
        $tokens=@('-I','-S','-B',(Join-Path $PSScriptRoot 'qualification_arm_control.py'),(Join-Path $directory 'request.json'),[string]$ref.sha256)
        $native=Invoke-WeatherQualificationProcess -Envelope $envelope -Executable $python -Tokens $tokens `
            -WorkingDirectory ([string]$m.repo_root) -Transcript (Join-Path $directory 'native.log') `
            -DeadlineUtc $deadline -MaximumSeconds ($seconds-3) -TeardownSeconds 3 `
            -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) `
            -MaximumOutputBytes 2097152 -VolumePaths @([string]$m.repo_root,$directory) `
            -MinimumDiskBytes ([UInt64]$State.Policy.host.minimum_disk_bytes) -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
            -ResourceMode capture_s4u -ProductionRoot ([string]$m.repo_root) -CaptureBindings $capture
        Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
        $snapshot=$envelope.Snapshot(); $zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
        if (-not $zero) { throw 'Preparation child tree did not drain' }
        $proof=Read-WeatherQualificationReference -Root $directory -Reference (Get-WeatherQualificationReference -Root $directory -Name 'proof.json')
        Assert-WeatherQualificationArmingProof -State $State -Proof $proof -Native $native -Preparation
        Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase 'preparation completion' | Out-Null
        Assert-WeatherQualificationCapture -ProductionRoot ([string]$m.repo_root) -Bindings $capture
        if ([DateTimeOffset]::UtcNow -gt $deadline) { throw 'Preparation exceeded its absolute native deadline' }
        Write-WeatherQualificationImmutableJson -Path (Join-Path $contract.AttemptRoot 'preparation-receipt.json') -Payload ([ordered]@{
            schema='weather_integration_attempt_preparation_receipt_v2'; status='PREPARED'; manifest_sha256=$contract.ManifestSha256
            attempt_id=$m.attempt_id; proof=(Get-WeatherQualificationReference -Root $contract.AttemptRoot -Name 'prepare-work/proof.json')
            native=(Get-WeatherQualificationReference -Root $contract.AttemptRoot -Name 'prepare-work/native.json')
            integration_eligible=$false })
    }
    finally {
        if ($envelope) {
            try {$snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID} catch {$zero=$false}
            if (-not $zero -and $lease) {Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease}
            $envelope.Dispose()
        }
        if ($lease -and $zero) {Exit-WeatherHeavyWorkloadLease -Lease $lease}
    }
}

function Assert-WeatherQualificationPreparation {
    param([Parameter(Mandatory = $true)]$AttemptContract)
    $state=Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    $root=$AttemptContract.AttemptRoot
    $receipt=Read-WeatherQualificationReference -Root $root -Reference (Get-WeatherQualificationReference -Root $root -Name 'preparation-receipt.json')
    Assert-WeatherQualificationFields -Value $receipt -Names @('schema','status','manifest_sha256','attempt_id','proof','native','integration_eligible')
    if ([string]$receipt.schema -cne 'weather_integration_attempt_preparation_receipt_v2' -or [string]$receipt.status -cne 'PREPARED' -or
        [string]$receipt.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or [string]$receipt.attempt_id -cne [string]$AttemptContract.Manifest.attempt_id -or
        [string]$receipt.proof.path -cne 'prepare-work/proof.json' -or [string]$receipt.native.path -cne 'prepare-work/native.json' -or
        $receipt.integration_eligible -isnot [bool] -or $receipt.integration_eligible) {throw 'Copied control source lacks preparation proof'}
    $proof=Read-WeatherQualificationReference -Root $root -Reference $receipt.proof
    $native=Read-WeatherQualificationReference -Root $root -Reference $receipt.native
    Assert-WeatherQualificationArmingProof -State $state -Proof $proof -Native $native -Preparation
    return $receipt
}
