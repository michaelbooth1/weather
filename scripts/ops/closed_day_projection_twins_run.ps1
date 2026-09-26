# Manual admitted twin plan/proof/apply. Never registers a task.
[CmdletBinding()]
param(
    [ValidateSet('plan-twins', 'prove-twins', 'apply')][string]$Command = 'plan-twins',
    [string]$RepoRoot = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent),
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$ApprovedManifest = '',
    [string]$AsOfDate = (Get-Date -Format 'yyyy-MM-dd'),
    [ValidateRange(1, 1099511627776)][long]$MaxBytes = 1GB,
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 1800
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$now = Get-Date
if ($now.TimeOfDay.TotalMinutes -lt 30 -or $now.Hour -ge 9) { throw 'Outside 00:30-09:00' }
if ((Get-PSDrive C).Free -lt 50GB) { throw 'Less than 50 GiB free' }
$memoryPath = Join-Path $RepoRoot 'data/logs/memory_commit_guard_status.json'
$memory = Get-Content -LiteralPath $memoryPath -Raw | ConvertFrom-Json
if (((Get-Date) - (Get-Item -LiteralPath $memoryPath).LastWriteTime).TotalMinutes -gt 5 -or
    $null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70) { throw 'Memory evidence blocks admission' }
$tokens = @('-m', 'weather.operations.closed_day_projection_tiering', $Command,
    '--output-root', $OutputRoot, '--protected-root', (Join-Path $RepoRoot 'data'))
if ($Command -eq 'plan-twins') {
    $tokens += @('--snapshots-root', (Join-Path $RepoRoot 'data/snapshots'),
        '--as-of-date', $AsOfDate, '--max-bytes', [string]$MaxBytes)
} else {
    if (-not $ApprovedManifest) { throw 'ApprovedManifest is required' }
    $tokens += @('--approved-manifest', $ApprovedManifest)
}
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload 'closed_day_projection_twins'
if ($null -eq $lease) { throw 'Heavy workload lease busy' }
$job = $null
$child = $null
try {
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath (Join-Path $RepoRoot 'venv/Scripts/python.exe') -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $RepoRoot
    $null = $child.Handle
    $deadline = @($now.Date.AddHours(9), $now.AddSeconds($MaxRuntimeSeconds)) | Sort-Object | Select-Object -First 1
    while (-not $child.WaitForExit(1000)) {
        if ((Get-Date) -ge $deadline) { throw 'Twin command deadline exceeded' }
    }
    if ($child.ExitCode -ne 0) { throw "Twin command failed: $($child.ExitCode)" }
} finally {
    # Teardown must complete before the shared lease is released.
    try { if ($job) { $job.TerminateAndWait(5000) } }
    finally {
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
    }
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
