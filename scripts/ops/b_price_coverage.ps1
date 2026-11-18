# B-1 coverage counts (master ruling R19, B-1 Clarification 4): one integers-only sidecar per exported date.
#
# Runs on the dedicated capture host only, inside 00:30-09:00 America/Toronto, under the shared workload
# lease, after the date's MG-2 input bundle is published. It wraps `python -m tools.research.b_price_coverage`
# (tools/research, not src: master ruling R19 option b, the R11 Head 1 pattern), which re-reads each
# market's snapshots_long.csv through the exporter's bounded reader (rows at or before the export cut only),
# counts per snapshot [rows, rows with an admitted capture-time price], records whether its re-projection
# reproduces the bundle's snapshots_long sha256, and writes create-only under
# <repo>\data\exports\mg2-inputs\_b_coverage: <D>.json and <D>.SHA256SUMS (the published marker, last). No price
# value is written. This wrapper's run receipt and captured child output go to _b_coverage\_runs\.
# The workstation logs each sidecar over the share master picks (`b_drop_list log --share-root`).
#
# Default: catch up every published date from 2026-10-29 that has no sidecar yet. Registration needs the
# owner's yes first; nothing here registers a task. Expected cost: a few minutes, well under 1 GB.
#
# Guards as in mg1_input_backfill.ps1: host identity, 00:30-09:00, lease (refused on $null), kill-on-close
# child job, PYTHONPATH pin proof for the tool AND the exporter, at least 5 GiB free on the output volume;
# memory freshness uses the UTC helper Get-WeatherMemoryGuardStatusAgeMinutes.
[CmdletBinding()]
param(
    [string]$ProductionRepoRoot = "",
    # One target date D; default: every published date with no sidecar (--catch-up).
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})?$')][string]$Date = "",
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 3600,
    # Print the resolved plan (paths, child arguments) as JSON and stop before any host check, lease, read or
    # write.
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
$dataRoot = Join-Path $ProductionRepoRoot 'data'
$outRoot = Join-Path $dataRoot 'exports\mg2-inputs'
$coverageRoot = Join-Path $outRoot '_b_coverage'
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
$childTokens = @('-P', '-B', '-m', 'tools.research.b_price_coverage', '--data-root', $dataRoot, '--out', $outRoot)
if ($Date) { $childTokens += @('--date', $Date) } else { $childTokens += @('--catch-up') }
$label = if ($Date) { $Date } else { 'catch-up' }

if ($PlanOnly) {
    [ordered]@{
        target_date = $label; production_repo_root = $ProductionRepoRoot; source_root = $sourceRoot
        data_root = $dataRoot; out_root = $outRoot; coverage_root = $coverageRoot; python = $python
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
if (-not (Test-Path -LiteralPath $outRoot -PathType Container)) {
    throw ("REFUSED: no MG-2 input exports under {0}" -f $outRoot)
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production project interpreter missing' }
$outDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($outRoot))
if ($outDrive.AvailableFreeSpace -lt 5GB) { throw 'REFUSED: less than 5 GiB free on the output volume' }
$memoryPath = Join-Path $dataRoot 'logs\memory_commit_guard_status.json'
. (Join-Path $PSScriptRoot 'memory_guard_status_reader.ps1')
$memoryRead = Read-WeatherMemoryGuardStatus -Path $memoryPath
$memory = $memoryRead.row
# Freshness is UTC on both sides (Get-WeatherMemoryGuardStatusAgeMinutes), never the local clock.
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
# counts tool and the unchanged exporter resolve under this source tree before any read.
$pinnedRoot = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\') + '\'
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $sourceRoot 'src')).TrimEnd('\') + '\'
$pinnedTool = Join-Path $pinnedRoot 'tools\research\'
$pinnedPath = '{0};{1}' -f $pinnedRoot.TrimEnd('\'), $pinnedSrc.TrimEnd('\')
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedPath
try {
    $ErrorActionPreference = 'Continue'
    $probeScript = 'import tools.research.b_price_coverage as b, weather.calibration.mg2_input_export as m; ' +
        'print(b.__file__); print(m.__file__)'
    $probe = @(& $python -P -B -c $probeScript 2>&1 | ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $resolvedTool = if ($probe.Count -ge 2) { $probe[-2].Trim() } else { '' }
    $resolvedExporter = if ($probe.Count -ge 1) { $probe[-1].Trim() } else { '' }
    $toolFull = try { [IO.Path]::GetFullPath($resolvedTool) } catch { '' }
    $exporterFull = try { [IO.Path]::GetFullPath($resolvedExporter) } catch { '' }
    if ($probeCode -ne 0 -or -not $toolFull -or -not $exporterFull -or
        -not $toolFull.StartsWith($pinnedTool, [StringComparison]::OrdinalIgnoreCase) -or
        -not $exporterFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("counts tool or exporter does not resolve under {0}: {1}" -f $pinnedRoot, ($probe -join ' '))
    }
}
finally { $env:PYTHONPATH = $oldPythonPath }

$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'b_price_coverage' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }
$job = $null
$child = $null
$capture = $null
$exitCode = $null
$runs = Join-Path $coverageRoot '_runs'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$receiptPath = Join-Path $runs ("{0}-{1}.json" -f $label, $stamp)
try {
    $null = New-Item -ItemType Directory -Force -Path $runs
    $capture = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $runs ("{0}-{1}.stdout.log" -f $label, $stamp)),
        (Join-Path $runs ("{0}-{1}.stderr.log" -f $label, $stamp)), 1048576)
    $env:PYTHONPATH = $pinnedPath
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens) `
        -WorkingDirectory $sourceRoot -OutputCapture $capture
    $null = $child.Handle
    while (-not $child.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'b price coverage deadline exceeded' }
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
                    schema = 'b_price_coverage_run/1'; target_date = $label; exit_code = $exitCode
                    finished_utc = [DateTime]::UtcNow.ToString('o'); source_root = $sourceRoot
                } | ConvertTo-Json -Compress | Set-Content -LiteralPath $receiptPath -Encoding ASCII
            }
        }
        finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
    }
}
# 0 counted (or nothing to do); 2 refused; 3 a rewritable source too fresh (rerun later); 4 a sidecar was
# written with match false (the source no longer reproduces the bundle: master rules before any verdict).
if ($exitCode -eq 4) { throw ("b price coverage {0}: a sidecar records match false; master rules" -f $label) }
if ($exitCode -ne 0) { throw ("b price coverage {0} failed or incomplete: exit {1}" -f $label, $exitCode) }
Write-Output ("b price coverage complete: {0}" -f $coverageRoot)
