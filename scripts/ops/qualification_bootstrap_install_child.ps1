# Fixed resource monitor between adopted B's outer Job and the temporary
# guarded primitive. The outer parent holds B's lease and all source locks.
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
if($raw.Length -lt 1 -or $raw.Length -gt 2097152) {throw 'Installation envelope exceeds bound'}
$sha=[Security.Cryptography.SHA256]::Create()
try {$actual=-join($sha.ComputeHash($raw) | ForEach-Object {$_.ToString('x2')})} finally {$sha.Dispose()}
if($actual -cne $ExpectedEnvelopeSha256) {throw 'Installation envelope changed'}
$value=[Text.UTF8Encoding]::new($false,$true).GetString($raw) | ConvertFrom-Json
if($value.schema -cne 'qualification_bootstrap_install_envelope_v1') {throw 'Not a first-landing envelope'}
$parent=Get-Process -Id $ParentPid -ErrorAction Stop
try {if($parent.StartTime.ToUniversalTime().Ticks -ne $ParentCreationUtcTicks) {throw 'Installation parent generation differs'}}
finally {$parent.Dispose()}
$self=Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
if([int]$self.ParentProcessId -ne $ParentPid) {throw 'Installation monitor is not the direct reviewed child'}
. (Join-Path $value.baseline_control.root 'scripts/ops/workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_bootstrap_install_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_identity.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$value=Read-WeatherBootstrapInstallEnvelope $EnvelopePath $ExpectedEnvelopeSha256
$deadline=Assert-WeatherBootstrapInstallWindow $value
$claim=Read-WeatherBootstrapProbeReference $root (Get-WeatherBootstrapProbeReference $root 'install-use.json')
if($claim.envelope_sha256 -cne $ExpectedEnvelopeSha256 -or $claim.parent_pid -ne $ParentPid -or
    $claim.parent_creation_utc_ticks -ne $ParentCreationUtcTicks) {throw 'Installation single-use claim differs'}
$work=Join-Path $root 'install-work'
$identity=Get-WeatherQualificationCurrentLogon
Write-WeatherBootstrapProbeRecord (Join-Path $work 'monitor.json') ([ordered]@{
    schema='qualification_bootstrap_install_monitor_v1';envelope_sha256=$ExpectedEnvelopeSha256
    pid=$PID;creation_utc_ticks=$identity.creation_utc_ticks;parent_pid=$ParentPid;parent_creation_utc_ticks=$ParentCreationUtcTicks})
$profile=Read-WeatherBootstrapProbeReference $root $value.environment
$closure=Read-WeatherBootstrapProbeReference $root $value.control.closure
$quietPin=@($closure.files | Where-Object path -CEQ 'scripts/ops/quiet_window_merge.ps1')
if($quietPin.Count -ne 1) {throw 'Guarded primitive is not independently pinned'}
Set-WeatherBootstrapProbeEnvironment $profile $work
$capture=@(Get-WeatherBootstrapProbeCaptureBindings $value.repo_root)
$limits=$value.limits
$nativeEnvelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$limits.commit_bytes,64)
try {
    $childDeadline=$deadline.AddSeconds(-[int]$limits.teardown_seconds-10)
    $seconds=[int][Math]::Floor(($childDeadline-[DateTimeOffset]::UtcNow).TotalSeconds)-[int]$limits.teardown_seconds
    if($seconds -lt 1 -or $seconds -gt 2700) {throw 'No guarded installation execution reserve'}
    $powershell=Join-Path $profile.tools.powershell.root $profile.tools.powershell.path
    $tokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        (Join-Path $value.control.root 'scripts/ops/quiet_window_merge.ps1'),
        '-Branch',[string]$value.branch_ref,'-ExpectedTip',[string]$value.source.commit,'-ExpectedBaseline',[string]$value.baseline,
        '-RepoRoot',[string]$value.repo_root,'-AttemptReportPath',(Join-Path $work 'quiet-report.json'),
        '-ExpectedSelfSha256',[string]$quietPin[0].sha256,'-BootstrapEnvelopePath',$EnvelopePath,
        '-BootstrapEnvelopeSha256',$ExpectedEnvelopeSha256)
    # PID continuity is intentionally delegated to the guarded recovery checks
    # during the roll. Memory, disk, reads, output and the full child tree stay
    # continuously enforced by this monitor through commit and publication.
    $native=Invoke-WeatherQualificationProcess -Envelope $nativeEnvelope -Executable $powershell -Tokens $tokens `
        -WorkingDirectory $value.control.root -Transcript (Join-Path $work 'guarded.log') `
        -DeadlineUtc $childDeadline -MaximumSeconds $seconds -TeardownSeconds ([int]$limits.teardown_seconds) `
        -CommitBytes ([UInt64]$limits.commit_bytes) -WorkingSetBytes ([UInt64]$limits.working_set_bytes) `
        -MaximumOutputBytes 8388608 -VolumePaths @($value.repo_root,$root) -MinimumDiskBytes 53687091200 `
        -ReservedScratchBytes ([UInt64]$limits.scratch_bytes) -MaximumReadBytes ([UInt64]$limits.read_bytes) `
        -ResourceMode capture_s4u -ProductionRoot $value.repo_root -CaptureBindings $capture -GuardedCaptureReadoption
    Write-WeatherBootstrapProbeRecord (Join-Path $work 'native-result.json') ([ordered]@{
        schema='qualification_bootstrap_install_native_result_v1';envelope_sha256=$ExpectedEnvelopeSha256
        native=$native;native_read_bytes=[UInt64]$nativeEnvelope.Snapshot().ReadBytes})
    if(-not $native.completed -or -not $native.teardown_proved) {exit 1}
} finally {$nativeEnvelope.Dispose()}
