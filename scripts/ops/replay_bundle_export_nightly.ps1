# Export yesterday's sealed UTC evidence as one all-city bundle v0.2 without touching capture or Scheduler.
# The registrar pins this wrapper's hash and the v0.2 exporter's module-closure hash (not a Git tip),
# so unrelated master commits do not stop the export. Active intervals are manifest-only.
# Panel export gate (owner decision 3): every UTC day 2026-09-30..2026-10-15 is refused with exit code 3
# (PANEL_GATED) before any lease, path check, Python launch or output. There is no override; exporting a
# panel day after signature needs a reviewed change to this wrapper and its pinned hash.
# Thread pins (owner decision 2): the child gets OPENBLAS/OMP/MKL/NUMEXPR_NUM_THREADS=1 in its environment;
# the exporter only verifies them and refuses otherwise.
# Two trees that never mix (P-v2 NB1): -DeployRoot is the exact-tip code tree that owns this wrapper (its src is the
# child's only PYTHONPATH, proved by a __file__ probe); -ProductionRoot supplies the venv interpreter (run -P -B),
# the memory guard status, the lease helpers and the host assignment.
# Job-level limits (P-v2 NB2): the venv python.exe is a redirector, so the 2 GiB commit ceiling and BelowNormal
# priority are Job limits over every member, and the summed working set of every member is polled.
# Admission (P-v2 M2): available physical memory must be at least -MinAvailableMiB immediately before the launch;
# otherwise the export refuses at once, never waits.
[CmdletBinding()]
param(
    [string]$DeployRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$ProductionRoot,
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSelfSha256,
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})?$')][string]$Day = '',
    [ValidateSet('night', 'calibration')][string]$Kind = 'night',
    [Parameter(Mandatory = $true)][ValidateRange(512, 65536)][int]$MinAvailableMiB
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$PanelGateExitCode = 3
$JobMemoryLimitBytes = 2GB
$WorkingSetLimitBytes = 2GB
$ProbeModules = @('weather.market.maker_replay_night_v02', 'maker_core.replay.export_gate',
    'maker_core.replay.v2.writer', 'maker_core.replay.v2.threads')

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

function Test-ReplayExportPathInside {
    param([string]$Path, [string]$Root)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return ($full -ieq $base -or $full.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase))
}

function Assert-ReplayExportAdmission {
    # Read immediately before each launch; a shortfall refuses, it never waits for memory to free up.
    param([int]$MinimumMiB, [UInt64]$AvailableMiB)
    if ($AvailableMiB -lt [UInt64]$MinimumMiB) {
        throw "REFUSED: available physical memory $AvailableMiB MiB is below -MinAvailableMiB $MinimumMiB; not waiting"
    }
}

function Invoke-ReplayExportImportProbe {
    # Proves, in a Job with the same limits, that every exporter module loads from the deploy src.
    param([string]$Python, [string]$Src, [string]$WorkingDirectory, [string[]]$Modules)
    $names = ($Modules | ForEach-Object { "'$_'" }) -join ','
    $code = ('import importlib,os,sys;root=os.path.normcase(os.path.realpath(sys.argv[1]))+os.sep;' +
        "bad=[n for n in ($names,) if not os.path.normcase(os.path.realpath(importlib.import_module(n).__file__))" +
        '.startswith(root)];sys.exit(3 if bad else 0)')
    $probeJob = New-ReplayExportLimitedJob -JobMemoryLimitBytes $JobMemoryLimitBytes -ProcessMemoryLimitBytes $JobMemoryLimitBytes
    $probe = $null
    try {
        $probe = $probeJob.StartAssigned($Python,
            (ConvertTo-WeatherWindowsArgumentString -Tokens @('-P', '-B', '-c', $code, $Src)), $WorkingDirectory)
        if (-not $probe.WaitForExit(120000)) { throw 'module-path probe timed out' }
        $probe.WaitForExit()
        if ($probe.ExitCode -ne 0) { throw "module-path probe failed: exit $($probe.ExitCode); a module loads outside $Src" }
    }
    finally {
        try { $probeJob.TerminateAndWait(5000) }
        finally {
            if ($probe) { $probe.Dispose() }
            $probeJob.Dispose()
        }
    }
}

function Get-ReplayExportJobWorkingSet {
    param($Job)
    $total = [UInt64]0
    foreach ($id in $Job.ProcessIds()) {
        $process = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($process) { $total += [UInt64]$process.WorkingSet64; $process.Dispose() }
    }
    return $total
}

function Assert-ReplayExportSource {
    # The exporter itself refuses unless its loaded module closure hashes to ExpectedModuleSha256.
    $hash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $ExpectedSelfSha256) { throw 'nightly wrapper hash mismatch' }
}

if (-not $Day) { $Day = [DateTime]::UtcNow.Date.AddDays(-1).ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) }
$parsedDay = [DateTime]::ParseExact($Day, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
if (Test-ReplayExportPanelGated -UtcDay $parsedDay) {
    # First refusal: before the window, paths, self-hash, lease, Python or any output.
    [Console]::Error.WriteLine("REFUSED: PANEL_GATED $Day is in the maker-replay-v2-v1 panel window; no export before signature")
    exit $PanelGateExitCode
}
$deadline = Get-ReplayExportDeadline -NowUtc ([DateTime]::UtcNow)
foreach ($path in @($DeployRoot, $ProductionRoot, $DataRoot, $ReleaseRoot, $OutputRoot)) { Assert-ReplayExportPath $path }
$ownRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
if ($ownRoot -ine $DeployRoot.TrimEnd('\')) { throw 'DeployRoot must own the invoked wrapper' }
if ((Test-ReplayExportPathInside $DeployRoot $ProductionRoot) -or (Test-ReplayExportPathInside $ProductionRoot $DeployRoot)) {
    throw 'DeployRoot and ProductionRoot must be disjoint trees'
}
if ((Test-ReplayExportPathInside $OutputRoot $DeployRoot) -or (Test-ReplayExportPathInside $DeployRoot $OutputRoot)) {
    throw 'output must be disjoint from the deploy tree'
}
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
$python = Join-Path $ProductionRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production interpreter missing' }
$deploySrc = Join-Path $DeployRoot 'src'
if (-not (Test-Path -LiteralPath (Join-Path $deploySrc 'maker_core\replay\export_gate.py') -PathType Leaf)) {
    throw 'deploy tree has no gated exporter source'
}
. (Join-Path $ProductionRoot 'scripts\ops\workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'replay_export_limited_job.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $ProductionRoot
$hostId = Get-WeatherExecutionHostId
if ($hostId -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'nightly wrapper requires the assigned capture host'
}
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRoot -Workload 'replay_bundle_export_nightly' `
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
    $memoryPath = Join-Path $ProductionRoot 'data\logs\memory_commit_guard_status.json'
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
    $tokens = @('-P', '-B', '-m', 'weather.market.maker_replay_night_v02', $Kind, '--day', $Day,
        '--data-root', $DataRoot, '--release-root', $ReleaseRoot, '--out', $OutputRoot,
        '--expected-module-sha256', $ExpectedModuleSha256, '--max-seconds', [string]$budget)
    # The child (and the probe) inherit these; this PowerShell process runs no Python of its own.
    Set-ReplayExportChildThreadPins
    $env:PYTHONPATH = $deploySrc
    Invoke-ReplayExportImportProbe -Python $python -Src $deploySrc -WorkingDirectory $DeployRoot -Modules $ProbeModules
    $available = [Weather.Operations.ReplayExportLimitedJob]::AvailablePhysicalMiB()
    Assert-ReplayExportAdmission -MinimumMiB $MinAvailableMiB -AvailableMiB $available
    $job = New-ReplayExportLimitedJob -JobMemoryLimitBytes $JobMemoryLimitBytes -ProcessMemoryLimitBytes $JobMemoryLimitBytes
    $child = $job.StartAssigned($python, (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens), $DeployRoot)
    $null = $child.Handle
    $peakWorkingSet = [UInt64]0
    while (-not $child.HasExited) {
        if ($job.MemoryLimitHit) { break }
        $workingSet = Get-ReplayExportJobWorkingSet -Job $job
        if ($workingSet -gt $peakWorkingSet) { $peakWorkingSet = $workingSet }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'nightly child deadline reached' }
        if ($workingSet -ge $WorkingSetLimitBytes) { throw 'nightly Job working-set ceiling reached' }
        Start-Sleep -Milliseconds 250
        $child.Refresh()
    }
    $child.WaitForExit()
    Write-Output (ConvertTo-Json -Compress @{ day = $Day; kind = $Kind; available_mib_at_launch = $available;
        min_available_mib = $MinAvailableMiB; peak_job_memory_bytes = $job.PeakJobMemoryUsed;
        peak_job_working_set_bytes = $peakWorkingSet; memory_limit_hit = $job.MemoryLimitHit;
        memory_limit_kind = $job.MemoryLimitKind; memory_limit_pid = $job.MemoryLimitProcessId;
        exit_code = $child.ExitCode })
    if ($job.MemoryLimitHit) {
        throw "nightly Job memory ceiling reached: $($job.MemoryLimitKind) in pid $($job.MemoryLimitProcessId)"
    }
    if ($null -eq $child.ExitCode -or $child.ExitCode -ne 0) { throw 'nightly exporter refused; inspect retained output' }
    $exitCode = 0
}
finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
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
