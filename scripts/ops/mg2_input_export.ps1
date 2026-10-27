# MG-2 daily input export (binding plan section 9.3): one read-only, outcome-free bundle per target date.
#
# Runs on the dedicated capture host only, inside 00:30-09:00 America/Toronto, under the shared workload
# lease. It wraps `python -m weather.calibration.mg2_input_export`, which opens only the section 9.1 inputs
# (CreateFileW with read/write/delete sharing, each read as the bounded byte range [0, size at open)) and
# writes only under the declared output directory <repo>\data\exports\mg2-inputs:
#   <D>\ (the bundle, published by an atomic rename from .<D>.partial), <D>.SHA256SUMS, and this wrapper's
#   run receipt and captured child output under _runs\.
# The workstation pulls <D>\ over the share master picks (`mg2_inputs pull --share-root`).
#
# This wrapper never passes --coverage-counts: the opt-in coverage reads need master's ruling for each use
# and are run by hand, never by the scheduled task. Registration: register_mg2_input_export.ps1 (owner's yes
# first). Expected cost: a few minutes and well under 1 GB of memory (every source is streamed).
[CmdletBinding()]
param(
    [string]$ProductionRepoRoot = "",
    # Target date D; default: yesterday on the America/Toronto clock (the 04:15 run on D+1).
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})?$')][string]$Date = "",
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 3600,
    # Print the resolved plan (date, paths, child arguments) as JSON and stop before any host check, lease,
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
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
if (-not $Date) { $Date = $localNow.Date.AddDays(-1).ToString('yyyy-MM-dd') }
$dataRoot = Join-Path $ProductionRepoRoot 'data'
$outRoot = Join-Path $dataRoot 'exports\mg2-inputs'
$bundle = Join-Path $outRoot $Date
$staging = Join-Path $outRoot (".{0}.partial" -f $Date)
$ready = Join-Path $bundle 'manifest.json.sha256'
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
$childTokens = @('-P', '-B', '-m', 'weather.calibration.mg2_input_export',
    '--date', $Date, '--data-root', $dataRoot, '--out', $outRoot)

if ($PlanOnly) {
    [ordered]@{
        target_date = $Date; production_repo_root = $ProductionRepoRoot; source_root = $sourceRoot
        data_root = $dataRoot; out_root = $outRoot; bundle = $bundle; python = $python
        child_arguments = $childTokens; already_exported = (Test-Path -LiteralPath $ready -PathType Leaf)
        max_runtime_seconds = $MaxRuntimeSeconds
    } | ConvertTo-Json -Compress
    return
}

# The 07:00 retry (and any later manual start) is a no-op once the date's bundle is published.
if (Test-Path -LiteralPath $ready -PathType Leaf) {
    Write-Output ("mg2 input export: {0} already exported; nothing to do" -f $Date)
    exit 0
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
if ((Get-PSDrive C).Free -lt 5GB) { throw 'REFUSED: less than 5 GiB free' }
$memoryPath = Join-Path $dataRoot 'logs\memory_commit_guard_status.json'
. (Join-Path $PSScriptRoot 'memory_guard_status_reader.ps1')
$memoryRead = Read-WeatherMemoryGuardStatus -Path $memoryPath
$memory = $memoryRead.row
if (((Get-Date) - $memoryRead.last_write_time).TotalMinutes -gt 5 -or
    $null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70) {
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
# PYTHONPATH=<source>\src, and prove the exporter resolves under that tree before any read.
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $sourceRoot 'src')).TrimEnd('\') + '\'
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
try {
    $ErrorActionPreference = 'Continue'
    $probe = @(& $python -P -B -c 'import weather.calibration.mg2_input_export as m; print(m.__file__)' 2>&1 |
        ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $resolved = if ($probe.Count) { $probe[-1].Trim() } else { '' }
    $resolvedFull = try { [IO.Path]::GetFullPath($resolved) } catch { '' }
    if ($probeCode -ne 0 -or -not $resolvedFull -or
        -not $resolvedFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("exporter does not resolve under {0}: {1}" -f $pinnedSrc, ($probe -join ' '))
    }
}
finally { $env:PYTHONPATH = $oldPythonPath }

$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'mg2_input_export' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }
$job = $null
$child = $null
$capture = $null
$exitCode = $null
$staleStaging = $false
$runs = Join-Path $outRoot '_runs'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$receiptPath = Join-Path $runs ("{0}-{1}.json" -f $Date, $stamp)
try {
    # Under the lease no other exporter runs, so a staging folder left by a killed earlier run of this
    # date is this exporter's own unpublished output: remove exactly that folder and nothing else.
    $staleStaging = Test-Path -LiteralPath $staging
    if ($staleStaging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    $null = New-Item -ItemType Directory -Force -Path $runs
    $capture = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $runs ("{0}-{1}.stdout.log" -f $Date, $stamp)),
        (Join-Path $runs ("{0}-{1}.stderr.log" -f $Date, $stamp)), 1048576)
    $env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens) `
        -WorkingDirectory $sourceRoot -OutputCapture $capture
    $null = $child.Handle
    while (-not $child.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'mg2 input export deadline exceeded' }
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
                [ordered]@{
                    schema = 'mg2_input_export_run/1'; target_date = $Date; exit_code = $exitCode
                    stale_staging_removed = [bool]$staleStaging; published = (Test-Path -LiteralPath $ready)
                    finished_utc = [DateTime]::UtcNow.ToString('o'); source_root = $sourceRoot
                } | ConvertTo-Json -Compress | Set-Content -LiteralPath $receiptPath -Encoding ASCII
            }
        }
        finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
    }
}
# 0 exported; 2 refused (date, path, link, forbidden field); 3 incomplete or a rewritable file too fresh.
if ($exitCode -ne 0) { throw ("mg2 input export {0} failed or incomplete: exit {1}" -f $Date, $exitCode) }
Write-Output ("mg2 input export complete: {0}" -f $bundle)
