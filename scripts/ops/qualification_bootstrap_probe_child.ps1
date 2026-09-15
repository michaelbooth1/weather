# Fixed nested worker. Its parent has already verified and locked this adapter's
# complete closure, acquired adopted B's lease and assigned the outer Job.
param(
    [Parameter(Mandatory=$true)][string]$EnvelopePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedEnvelopeSha256,
    [Parameter(Mandatory=$true)][int]$ParentPid,
    [Parameter(Mandatory=$true)][Int64]$ParentCreationUtcTicks
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($EnvelopePath))
$raw=[IO.File]::ReadAllBytes($EnvelopePath)
if($raw.Length -lt 1 -or $raw.Length -gt 2097152) { throw 'Bootstrap envelope exceeds bound' }
$sha=[Security.Cryptography.SHA256]::Create()
try {$actual=-join($sha.ComputeHash($raw) | ForEach-Object {$_.ToString('x2')})} finally {$sha.Dispose()}
if($actual -cne $ExpectedEnvelopeSha256) { throw 'Bootstrap envelope changed' }
$value=[Text.UTF8Encoding]::new($false,$true).GetString($raw) | ConvertFrom-Json
$repo=[IO.Path]::GetFullPath([string]$value.repo_root)
$parent=Get-Process -Id $ParentPid -ErrorAction Stop
try {if($parent.StartTime.ToUniversalTime().Ticks -ne $ParentCreationUtcTicks) { throw 'Bootstrap parent generation differs' }} finally {$parent.Dispose()}
$self=Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
if([int]$self.ParentProcessId -ne $ParentPid) { throw 'Bootstrap worker is not the direct reviewed child' }
$claim=[IO.File]::ReadAllText((Join-Path $root 'probe-use.json')) | ConvertFrom-Json
if($claim.envelope_sha256 -cne $ExpectedEnvelopeSha256 -or $claim.parent_pid -ne $ParentPid -or
    $claim.parent_creation_utc_ticks -ne $ParentCreationUtcTicks) { throw 'Bootstrap single-use claim differs' }
. (Join-Path $repo 'scripts/ops/workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_bootstrap_probe_contract.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$value=ConvertFrom-WeatherExactJson -Text ([Text.UTF8Encoding]::new($false,$true).GetString($raw))
$deadline=Assert-WeatherBootstrapProbeWindow $value
$profile=Read-WeatherBootstrapProbeReference $root $value.environment
$limits=$value.limits
foreach($name in @('commit_bytes','working_set_bytes','scratch_bytes','read_bytes','teardown_seconds')) {
    $number=$limits.PSObject.Properties[$name].Value
    if($number -is [bool] -or ($number -isnot [int] -and $number -isnot [long]) -or $number -le 0) { throw 'Invalid bootstrap native limit' }
}
if($limits.commit_bytes -gt 536870912 -or $limits.working_set_bytes -gt $limits.commit_bytes -or
    $limits.scratch_bytes -gt 67108864 -or $limits.read_bytes -gt 2147483648 -or
    $limits.teardown_seconds -lt 10 -or $limits.teardown_seconds -gt 60) { throw 'Bootstrap native cap exceeds policy' }
$work=Join-Path $root 'probe-work'
Set-WeatherBootstrapProbeEnvironment $profile $work
$capture=@(Get-WeatherBootstrapProbeCaptureBindings -ProductionRoot $repo)
$nativeEnvelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$limits.commit_bytes,64)
try {
    $seconds=[int][Math]::Floor(($deadline-[DateTimeOffset]::UtcNow).TotalSeconds)-[int]$limits.teardown_seconds-10
    if($seconds -lt 1 -or $seconds -gt 480) { throw 'No bounded bootstrap execution budget remains' }
    $python=Join-Path $profile.tools.python.root $profile.tools.python.path
    $tokens=@('-I','-S','-B',(Join-Path $PSScriptRoot 'qualification_bootstrap_probe_control.py'),$EnvelopePath,$ExpectedEnvelopeSha256)
    $native=Invoke-WeatherQualificationProcess -Envelope $nativeEnvelope -Executable $python -Tokens $tokens `
        -WorkingDirectory ([IO.Path]::GetFullPath([string]$value.control.root)) -Transcript (Join-Path $work 'native.log') `
        -DeadlineUtc $deadline.AddSeconds(-5) -MaximumSeconds $seconds -TeardownSeconds ([int]$limits.teardown_seconds) `
        -CommitBytes ([UInt64]$limits.commit_bytes) -WorkingSetBytes ([UInt64]$limits.working_set_bytes) `
        -MaximumOutputBytes 2097152 -VolumePaths @($repo,$root) -MinimumDiskBytes 53687091200 `
        -ReservedScratchBytes ([UInt64]$limits.scratch_bytes) -MaximumReadBytes ([UInt64]$limits.read_bytes) `
        -ResourceMode capture_s4u -ProductionRoot $repo -CaptureBindings $capture
    Write-WeatherBootstrapProbeRecord (Join-Path $work 'native-result.json') ([ordered]@{
        schema='qualification_bootstrap_probe_native_result_v1';envelope_sha256=$ExpectedEnvelopeSha256;native=$native;integration_eligible=$false
        native_read_bytes=[UInt64]$nativeEnvelope.Snapshot().ReadBytes})
    if(-not $native.completed -or -not $native.teardown_proved) { exit 1 }
} finally {$nativeEnvelope.Dispose()}
