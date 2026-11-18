# MG-1 input backfill (R11 Head 1): one outcome-free MG-2-format bundle per target date 2026-10-15..10-27.
#
# Runs on the dedicated capture host only, inside 00:30-09:00 America/Toronto, under the shared workload
# lease, by hand (no scheduled task). It wraps `python -m tools.research.mg1_input_backfill`, which swaps
# only the date gate (inside try/finally) and calls the UNCHANGED weather.calibration.mg2_input_export with
# coverage counts always off. It writes only under <repo>\data\exports\mg1-inputs:
#   <D>\ (published by the exporter's atomic rename from .<D>.partial), <D>.SHA256SUMS,
#   <D>.mg1_backfill_receipt.json (the backfill sidecar), and this wrapper's run receipt and captured
#   child output under _runs\.
# The workstation copies <D>\ and the sidecar over the share master picks
# (`python -m weather.calibration.mg1_layout stage --share-root <share>`); the share root is always a
# parameter there and is never written by this wrapper.
#
# Guards copied from mg2_input_export.ps1: host identity, 00:30-09:00, lease (refused on $null),
# kill-on-close child job, PYTHONPATH pin proof, at least 5 GiB free; memory freshness uses the UTC helper
# Get-WeatherMemoryGuardStatusAgeMinutes. -Mode Precheck runs the metadata-only precheck (opens no input).
[CmdletBinding()]
param(
    [string]$ProductionRepoRoot = "",
    # Target dates (comma-separated or repeated); default every date 2026-10-15..2026-10-27.
    [string[]]$Date = @(),
    [ValidateSet('Precheck', 'Export')][string]$Mode = 'Export',
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 5400,
    # Print the resolved plan (dates, paths, child arguments) as JSON and stop before any host check, lease,
    # read or write.
    [switch]$PlanOnly
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an advanced script's param()
# defaults under `powershell -File`; derive the default here. An explicit -ProductionRepoRoot always wins.
if (-not $ProductionRepoRoot) {
    $ProductionRepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not [IO.Path]::IsPathRooted($ProductionRepoRoot) -or $ProductionRepoRoot -match '["\r\n]') {
    throw 'an absolute -ProductionRepoRoot without quotes or newlines is required'
}
$ProductionRepoRoot = [IO.Path]::GetFullPath($ProductionRepoRoot).TrimEnd('\')

$first = [DateTime]::ParseExact('2026-10-15', 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$last = [DateTime]::ParseExact('2026-10-27', 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$dates = @($Date | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if (-not $dates.Count) {
    $dates = @(0..(($last - $first).Days) | ForEach-Object { $first.AddDays($_).ToString('yyyy-MM-dd') })
}
foreach ($d in $dates) {
    if ($d -notmatch '^\d{4}-\d{2}-\d{2}$') { throw ("REFUSED: {0} is not a yyyy-MM-dd date" -f $d) }
    $parsed = [DateTime]::ParseExact($d, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($parsed -lt $first -or $parsed -gt $last) {
        throw ("REFUSED: {0} is outside the backfill span 2026-10-15..2026-10-27" -f $d)
    }
}

$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$dataRoot = Join-Path $ProductionRepoRoot 'data'
$outRoot = Join-Path $dataRoot 'exports\mg1-inputs'
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
$childTokens = @('-P', '-B', '-m', 'tools.research.mg1_input_backfill', $Mode.ToLowerInvariant())
foreach ($d in $dates) { $childTokens += @('--date', $d) }
$childTokens += @('--data-root', $dataRoot, '--out', $outRoot)

if ($PlanOnly) {
    [ordered]@{
        mode = $Mode; target_dates = $dates; production_repo_root = $ProductionRepoRoot
        source_root = $sourceRoot; data_root = $dataRoot; out_root = $outRoot; python = $python
        child_arguments = $childTokens; max_runtime_seconds = $MaxRuntimeSeconds
    } | ConvertTo-Json -Compress
    return
}

$minute = $localNow.Hour * 60 + $localNow.Minute
if ($minute -lt 30 -or $minute -ge 540) { throw 'REFUSED: restricted to 00:30-09:00 America/Toronto' }
$windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddHours(9), $zone)
$deadline = [DateTime]::UtcNow.AddSeconds($MaxRuntimeSeconds)
if ($deadline -gt $windowEnd.AddSeconds(-60)) { $deadline = $windowEnd.AddSeconds(-60) }
if (($deadline - [DateTime]::UtcNow).TotalSeconds -lt 120) {
    throw 'REFUSED: insufficient time for a bounded child and teardown'
}
if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'snapshots') -PathType Container)) {
    throw ("REFUSED: data root {0} has no snapshots folder" -f $dataRoot)
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production project interpreter missing' }
$outDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($outRoot))
if ($outDrive.AvailableFreeSpace -lt 5GB) { throw 'REFUSED: less than 5 GiB free on the output volume' }
$memoryPath = Join-Path $dataRoot 'logs\memory_commit_guard_status.json'
. (Join-Path $PSScriptRoot 'memory_guard_status_reader.ps1')
$memoryRead = Read-WeatherMemoryGuardStatus -Path $memoryPath
$memory = $memoryRead.row
# UTC on both sides; the helper returns +Infinity (refuse) for missing or unreadable evidence.
if ((Get-WeatherMemoryGuardStatusAgeMinutes -Read $memoryRead) -gt 5 -or
    $null -eq $memory -or $null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70) {
    throw 'REFUSED: memory evidence blocks admission'
}

. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
$hostIdentity = Get-WeatherExecutionHostId
if ($hostIdentity -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'this runner is restricted to the assigned dedicated capture host'
}

# The production venv may carry an editable path to another checkout. Run with -P -B and
# PYTHONPATH=<source>;<source>\src (tools.research needs the root; weather needs src), and prove both the
# backfill tool and the unchanged exporter resolve under this source tree before any read.
$pinnedRoot = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\') + '\'
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $sourceRoot 'src')).TrimEnd('\') + '\'
$pinnedPath = '{0};{1}' -f $pinnedRoot.TrimEnd('\'), $pinnedSrc.TrimEnd('\')
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedPath
try {
    $ErrorActionPreference = 'Continue'
    $probe = @(& $python -P -B -c 'import tools.research.mg1_input_backfill as b, weather.calibration.mg2_input_export as m; print(b.__file__); print(m.__file__)' 2>&1 |
        ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $resolvedTool = if ($probe.Count -ge 2) { $probe[-2].Trim() } else { '' }
    $resolvedExporter = if ($probe.Count -ge 1) { $probe[-1].Trim() } else { '' }
    $toolFull = try { [IO.Path]::GetFullPath($resolvedTool) } catch { '' }
    $exporterFull = try { [IO.Path]::GetFullPath($resolvedExporter) } catch { '' }
    if ($probeCode -ne 0 -or -not $toolFull -or -not $exporterFull -or
        -not $toolFull.StartsWith((Join-Path $pinnedRoot 'tools\research\'), [StringComparison]::OrdinalIgnoreCase) -or
        -not $exporterFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("backfill or exporter does not resolve under {0}: {1}" -f $pinnedRoot, ($probe -join ' '))
    }
}
finally { $env:PYTHONPATH = $oldPythonPath }

$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'mg1_input_backfill' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }
$job = $null
$child = $null
$capture = $null
$exitCode = $null
$removedStaging = @()
$runs = Join-Path $outRoot '_runs'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$receiptPath = Join-Path $runs ("backfill-{0}-{1}.json" -f $Mode.ToLowerInvariant(), $stamp)
try {
    if ($Mode -eq 'Export') {
        # Under the lease no other exporter runs, so a staging folder left by a killed earlier run of a
        # chosen date is this tool's own unpublished output: remove exactly that folder and nothing else.
        foreach ($d in $dates) {
            $staging = Join-Path $outRoot (".{0}.partial" -f $d)
            if (Test-Path -LiteralPath $staging) {
                Remove-Item -LiteralPath $staging -Recurse -Force
                $removedStaging += $d
            }
        }
    }
    $null = New-Item -ItemType Directory -Force -Path $runs
    $capture = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $runs ("backfill-{0}-{1}.stdout.log" -f $Mode.ToLowerInvariant(), $stamp)),
        (Join-Path $runs ("backfill-{0}-{1}.stderr.log" -f $Mode.ToLowerInvariant(), $stamp)), 1048576)
    $env:PYTHONPATH = $pinnedPath
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens) `
        -WorkingDirectory $sourceRoot -OutputCapture $capture
    $null = $child.Handle
    while (-not $child.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'mg1 input backfill deadline exceeded' }
    }
    $exitCode = $child.ExitCode
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    # Teardown must complete before the shared lease is released.
    try { if ($job) { $job.TerminateAndWait(5000) } }
    finally {
        if ($child) { $child.Dispose() }
        if ($capture) { $capture.Dispose() }
        if ($job) { $job.Dispose() }
        try {
            if (Test-Path -LiteralPath $runs -PathType Container) {
                $published = @($dates | Where-Object {
                    Test-Path -LiteralPath (Join-Path $outRoot ("{0}.mg1_backfill_receipt.json" -f $_)) -PathType Leaf
                })
                [ordered]@{
                    schema = 'mg1_input_backfill_run/1'; mode = $Mode; target_dates = $dates
                    exit_code = $exitCode; stale_staging_removed = $removedStaging; receipts_present = $published
                    finished_utc = [DateTime]::UtcNow.ToString('o'); source_root = $sourceRoot
                } | ConvertTo-Json -Compress | Set-Content -LiteralPath $receiptPath -Encoding ASCII
            }
        }
        finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
    }
}
# 0 done; 2 refused (date, gate, path, link, partial outputs); 3 incomplete or a rewritable file too fresh.
if ($exitCode -ne 0) { throw ("mg1 input backfill {0} failed or incomplete: exit {1}" -f $Mode, $exitCode) }
Write-Output ("mg1 input backfill {0} complete: {1}" -f $Mode, $outRoot)
