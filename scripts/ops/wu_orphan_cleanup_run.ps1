# Manual admitted WU orphan plan/preflight/apply. Never registers a task.
[CmdletBinding()]
param(
    [ValidateSet('plan', 'preflight', 'apply')][string]$Command = 'plan',
    [string]$RepoRoot = "",
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$ApprovedManifest = '',
    [string]$ManifestSha256 = '',
    [ValidateRange(1, 10000)][int]$MaxEntries = 10000,
    [ValidateRange(1, 1073741824)][long]$MaxBytes = 1GB,
    [ValidateRange(1, 1800)][int]$MaxRuntimeSeconds = 300
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an
# advanced script's param() defaults under `powershell -File`; derive the default
# here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$now = Get-Date
if ($now.TimeOfDay.TotalMinutes -lt 30 -or $now.Hour -ge 9) { throw 'Outside 00:30-09:00' }
if ((Get-PSDrive C).Free -lt 50GB) { throw 'Less than 50 GiB free' }
$memoryPath = Join-Path $RepoRoot 'data/logs/memory_commit_guard_status.json'
. (Join-Path $PSScriptRoot 'memory_guard_status_reader.ps1')
$memoryRead = Read-WeatherMemoryGuardStatus -Path $memoryPath
$memory = $memoryRead.row
if (((Get-Date) - $memoryRead.last_write_time).TotalMinutes -gt 5 -or
    $null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70) { throw 'Memory evidence blocks admission' }
if ($Command -ne 'plan' -and (-not $ApprovedManifest -or $ManifestSha256 -cnotmatch '^[a-f0-9]{64}$')) {
    throw 'Exact reviewed manifest and SHA256 are required'
}
$tokens = @('-B', '-m', 'weather.operations.wu_orphan_cleanup', $Command,
    '--root', (Join-Path $RepoRoot 'data'), '--output', $OutputRoot,
    '--max-entries', [string]$MaxEntries, '--max-bytes', [string]$MaxBytes,
    '--max-seconds', [string]$MaxRuntimeSeconds)
if ($Command -ne 'plan') { $tokens += @('--manifest', $ApprovedManifest, '--manifest-sha256', $ManifestSha256) }
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload 'wu_atomic_orphans'
if ($null -eq $lease) { throw 'Heavy workload lease busy' }
$job = $null
$child = $null
try {
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath (Join-Path $RepoRoot 'venv/Scripts/python.exe') -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $RepoRoot
    $null = $child.Handle
    $deadline = @($now.Date.AddHours(9), $now.AddSeconds($MaxRuntimeSeconds)) | Sort-Object | Select-Object -First 1
    while (-not $child.WaitForExit(1000)) {
        if ((Get-Date) -ge $deadline) { throw 'WU orphan command deadline exceeded' }
    }
    if ($child.ExitCode -ne 0) { throw "WU orphan command failed: $($child.ExitCode)" }
} finally {
    # Keep the shared lease until the complete child tree has been torn down.
    try { if ($job) { $job.TerminateAndWait(5000) } }
    finally {
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
    }
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
