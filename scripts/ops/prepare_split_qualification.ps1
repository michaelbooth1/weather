# Prepare only inert Q or a manifest draft from adopted B. No Scheduler, arming,
# source mutation, dependency install or publication of an adoption result.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedRequestSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedHostId,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedPrincipalId
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'integration_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$path=Resolve-WeatherIntegrationPath -Path $RequestPath
$root=Split-Path -Parent $path
$ref=Get-WeatherQualificationReference -Root $root -Name (Split-Path -Leaf $path)
if($ref.sha256 -cne $ExpectedRequestSha256){throw 'Reviewed planning request changed'}
$request=Read-WeatherQualificationReference -Root $root -Reference $ref
Assert-WeatherQualificationFields -Value $request -Names @('schema','operation','repo_root','candidate','qualification','environment','maximum','metadata','deadline')
if([string]$request.schema -cne 'qualification_planning_request_v2' -or [string]$request.operation -cnotin @('configuration','draft','measurement-draft')){throw 'Unknown planning operation'}
$repo=Resolve-WeatherIntegrationPath -Path $request.repo_root
if(-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $repo 'scripts/ops'))){throw 'Planning must execute the currently adopted B controller'}
foreach($sourceRoot in @($repo,[IO.Path]::GetFullPath([string]$request.candidate))) {
    $prefix=$sourceRoot.TrimEnd('\','/')+'\'
    if($root.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        $sourceRoot.StartsWith($root.TrimEnd('\','/')+'\',[StringComparison]::OrdinalIgnoreCase) -or
        (Test-WeatherIntegrationPathEqual -Left $root -Right $sourceRoot)){throw 'Planning evidence overlaps a source checkout'}
}
$assignment=Get-WeatherExecutionHostAssignment -RepoRoot $repo
if((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id -or
    (Get-WeatherExecutionHostId) -cne $ExpectedHostId -or (Get-WeatherExecutionPrincipalId) -cne $ExpectedPrincipalId){throw 'Planning host/principal differs'}
$now=Get-Date
if($now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30)){throw 'Planning is outside capture-host heavy admission'}
$deadline=[DateTimeOffset]::Parse([string]$request.deadline)
$remaining=($deadline-[DateTimeOffset]::UtcNow).TotalSeconds
if($remaining -le 5 -or $remaining -gt 120 -or $deadline -gt [DateTimeOffset]::new($now.Date.AddHours(9))){throw 'Planning requires a bounded absolute deadline inside admission'}
$profile=Read-WeatherQualificationReference -Root $root -Reference $request.environment
$policy=Read-WeatherQualificationReference -Root $request.qualification.root -Reference $request.qualification.policy
$review=Read-WeatherQualificationReference -Root $request.qualification.root -Reference $request.qualification.review
Assert-WeatherQualificationNativeToolPins -Profile $profile -Policy $policy -Review $review -GraphRoot $request.qualification.root
$namespace=Join-Path $root ($request.operation+'-native')
if(Test-Path -LiteralPath $namespace){throw 'Planning operation namespace is spent'}
$lease=$null;$envelope=$null;$zero=$true
try {
    $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload ('SplitPlan-'+$request.operation)
    if($null -eq $lease){throw 'Shared heavy-workload lease is occupied'}
    [void][IO.Directory]::CreateDirectory($namespace)
    $capture=@(Get-WeatherQualificationCaptureBindings -ProductionRoot $repo)
    Set-WeatherQualificationOfflineEnvironment -Profile $profile -Scratch $namespace
    $envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(2147483648,64);$zero=$false
    $python=Join-Path $profile.tools.python.root $profile.tools.python.path
    $tokens=@('-I','-S','-B',(Join-Path $PSScriptRoot 'qualification_plan_control.py'),$path,$ExpectedRequestSha256)
    $remaining=[int][Math]::Floor(($deadline-[DateTimeOffset]::UtcNow).TotalSeconds)
    if($remaining -le 4){throw 'Planning budget elapsed before native launch'}
    $native=Invoke-WeatherQualificationProcess -Envelope $envelope -Executable $python -Tokens $tokens -WorkingDirectory $repo `
        -Transcript (Join-Path $namespace 'native.log') -DeadlineUtc $deadline -MaximumSeconds ($remaining-3) -TeardownSeconds 3 `
        -CommitBytes 2147483648 -WorkingSetBytes 1610612736 -MaximumOutputBytes 2097152 -VolumePaths @($repo,$root) `
        -MinimumDiskBytes 53687091200 -ReservedScratchBytes ([UInt64]$request.maximum.staged_bytes) `
        -ResourceMode capture_s4u -ProductionRoot $repo -CaptureBindings $capture
    Write-WeatherQualificationImmutableJson -Path (Join-Path $namespace 'native.json') -Payload $native
    $snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
    if(-not $zero -or -not $native.completed -or -not $native.teardown_proved){throw 'Planning did not complete with zero children'}
    $result=Read-WeatherQualificationReference -Root $root -Reference (Get-WeatherQualificationReference -Root $root -Name ($request.operation+'-planning.json'))
    if([string]$result.schema -cne 'qualification_planning_result_v2' -or [string]$result.request_sha256 -cne $ExpectedRequestSha256 -or
        $result.native_parent_completion_required -isnot [bool] -or -not $result.native_parent_completion_required -or
        $result.integration_eligible -isnot [bool] -or $result.integration_eligible){throw 'Planning output binding differs'}
    Assert-WeatherQualificationCapture -ProductionRoot $repo -Bindings $capture
    $result | ConvertTo-Json -Depth 20
}
finally {
    if($envelope){
        try{$snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID}catch{$zero=$false}
        if(-not $zero -and $lease){Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease};$envelope.Dispose()
    }
    if($lease -and $zero){Exit-WeatherHeavyWorkloadLease -Lease $lease}
}
