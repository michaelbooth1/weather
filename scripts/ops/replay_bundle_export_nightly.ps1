# Export yesterday's sealed UTC evidence as one all-city bundle v0.2 without touching capture or Scheduler.
# The registrar pins this wrapper's hash and the v0.2 exporter's module-closure hash (not a Git tip),
# so unrelated master commits do not stop the export. Active intervals are manifest-only.
# Panel export gate (owner decision 3): every UTC day 2026-09-30..2026-10-15 is refused with exit code 3
# (PANEL_GATED) before any lease, path check, Python launch or output. There is no override; exporting a
# panel day after signature needs a reviewed change to this wrapper and its pinned hash.
# Thread pins (owner decision 2): the child gets OPENBLAS/OMP/MKL/NUMEXPR_NUM_THREADS=1 in its environment;
# the exporter only verifies them and refuses otherwise.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSelfSha256,
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})?$')][string]$Day = '',
    [ValidateSet('night', 'calibration')][string]$Kind = 'night'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$PanelGateExitCode = 3

function Test-ReplayExportPanelGated {
    # A UTC calendar day is gated when [day 00:00Z, day+1 00:00Z) lies inside [2026-09-30 00:00Z, 2026-10-16 00:00Z).
    param([datetime]$UtcDay)
    $first = [DateTime]::new(2026, 9, 30, 0, 0, 0, [DateTimeKind]::Utc)
    $end = [DateTime]::new(2026, 10, 16, 0, 0, 0, [DateTimeKind]::Utc)
    return ($UtcDay.Date -ge $first -and $UtcDay.Date.AddDays(1) -le $end)
}

function Set-ReplayExportChildThreadPins {
    # Process scope of this wrapper only; Start-WeatherProcessInJob passes no environment block, so the child
    # inherits exactly these values, which OpenBLAS reads once at load.
    foreach ($name in @('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')) {
        [Environment]::SetEnvironmentVariable($name, '1', 'Process')
    }
}

function Get-ReplayExportDeadline {
    param([datetime]$NowUtc)
    $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
    $local = [TimeZoneInfo]::ConvertTimeFromUtc($NowUtc, $zone)
    $minute = $local.Hour * 60 + $local.Minute
    # A subset of the heavy lane, reserving teardown before the 05:00 jobs.
    if ($minute -lt 30 -or $minute -ge 294) {
        throw 'REFUSED: nightly export starts only 00:30-04:54 America/Toronto'
    }
    $boundary = [TimeZoneInfo]::ConvertTimeToUtc($local.Date.AddMinutes(295), $zone)
    # 45 minutes of export plus 30 seconds of Python/Job startup, never past 04:54:45.
    $deadline = $NowUtc.AddSeconds(2730)
    if ($deadline -gt $boundary.AddSeconds(-15)) { $deadline = $boundary.AddSeconds(-15) }
    return $deadline
}

function Assert-ReplayExportPath {
    param([string]$Path)
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($Path).TrimEnd('\') -cne $Path.TrimEnd('\')) {
        throw 'absolute normalized paths without quotes or newlines required'
    }
    $part = $Path
    while ($part) {
        if (Test-Path -LiteralPath $part) {
            $item = Get-Item -LiteralPath $part -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'ordinary non-reparse directories required'
            }
        }
        $part = Split-Path -Parent $part
    }
}

function Assert-ReplayExportSource {
    # The exporter itself refuses unless its loaded module closure hashes to ExpectedModuleSha256.
    $hash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $ExpectedSelfSha256) { throw 'nightly wrapper hash mismatch' }
}

if (-not $Day) { $Day = [DateTime]::UtcNow.Date.AddDays(-1).ToString('yyyy-MM-dd') }
$parsedDay = [DateTime]::ParseExact($Day, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
if (Test-ReplayExportPanelGated -UtcDay $parsedDay) {
    # First refusal: before the window, paths, self-hash, lease, Python or any output.
    [Console]::Error.WriteLine("REFUSED: PANEL_GATED $Day is in the maker-replay-v2-v1 panel window; no export before signature")
    exit $PanelGateExitCode
}
$deadline = Get-ReplayExportDeadline -NowUtc ([DateTime]::UtcNow)
foreach ($path in @($RepoRoot, $DataRoot, $ReleaseRoot, $OutputRoot)) { Assert-ReplayExportPath $path }
$ownRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ($ownRoot -ine $RepoRoot) { throw 'RepoRoot must own the invoked wrapper' }
Assert-ReplayExportSource
foreach ($sourceRoot in @($DataRoot, $ReleaseRoot)) {
if ($OutputRoot -ieq $sourceRoot -or
    $OutputRoot.StartsWith($sourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $sourceRoot.StartsWith($OutputRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'output must be disjoint from the entire input data tree'
}
}
if ($parsedDay -ge [DateTime]::UtcNow.Date) { throw 'closed UTC day required' }
if (-not (Test-Path -LiteralPath $DataRoot -PathType Container) -or
    -not (Test-Path -LiteralPath (Split-Path -Parent $OutputRoot) -PathType Container)) {
    throw 'input and output parent must already exist'
}
$python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'project interpreter missing' }
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
$hostId = Get-WeatherExecutionHostId
if ($hostId -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'nightly wrapper requires the assigned capture host'
}
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload 'replay_bundle_export_nightly' `
    -ExpectedExecutionHostId $hostId
if ($null -eq $lease) { throw 'REFUSED: shared heavy-work lease busy; no late retry' }
$job = $null
$child = $null
$exitCode = 1
$teardownProved = $false
try {
    # Admission and a renewed deadline precede Python or output creation.
    $renewed = Get-ReplayExportDeadline -NowUtc ([DateTime]::UtcNow)
    if ($renewed -lt $deadline) { $deadline = $renewed }
    $memoryPath = Join-Path $RepoRoot 'data\logs\memory_commit_guard_status.json'
    $memoryInfo = Get-Item -LiteralPath $memoryPath
    if ($memoryInfo.Length -gt 1MB -or $memoryInfo.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddMinutes(-5)) {
        throw 'fresh bounded memory guard status required'
    }
    $memory = Get-Content -LiteralPath $memoryPath -Raw | ConvertFrom-Json
    if ($null -eq $memory.commit_percent -or [double]::IsNaN([double]$memory.commit_percent) -or
        [double]::IsInfinity([double]$memory.commit_percent) -or [double]$memory.commit_percent -ge 70 -or
        [double]$memory.commit_percent -lt 0) { throw 'commit charge must be measured below 70 percent' }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($OutputRoot))
    if ($drive.AvailableFreeSpace -lt 50GB) { throw '50 GiB free required for capture headroom' }
    $budget = [Math]::Floor(($deadline - [DateTime]::UtcNow).TotalSeconds) - 30
    if ($budget -lt 60) { throw 'deadline elapsed during admission' }
    if ($budget -gt 2700) { $budget = 2700 }
    $tokens = @('-B', '-m', 'weather.market.maker_replay_night_v02', $Kind, '--day', $Day,
        '--data-root', $DataRoot, '--release-root', $ReleaseRoot, '--out', $OutputRoot,
        '--expected-module-sha256', $ExpectedModuleSha256, '--max-seconds', [string]$budget)
    Set-ReplayExportChildThreadPins
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $RepoRoot
    $null = $child.Handle
    $child.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    while (-not $child.HasExited) {
        if ([DateTime]::UtcNow -ge $deadline -or $child.PrivateMemorySize64 -ge 2GB -or
            $child.WorkingSet64 -ge 2GB) { throw 'nightly child deadline or memory ceiling reached' }
        Start-Sleep -Milliseconds 250
        $child.Refresh()
    }
    $child.WaitForExit()
    if ($null -eq $child.ExitCode -or $child.ExitCode -ne 0) { throw 'nightly exporter refused; inspect retained output' }
    $exitCode = 0
}
finally {
    # Keep ownership until the complete Job is empty. An unproved teardown
    # poisons the lease rather than granting the next heavyweight admission.
    try {
        if ($job) { $job.TerminateAndWait(5000) }
        $teardownProved = $true
    }
    finally {
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
        if ($teardownProved) { Exit-WeatherHeavyWorkloadLease -Lease $lease }
        else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
    }
}
Assert-ReplayExportSource
exit $exitCode
