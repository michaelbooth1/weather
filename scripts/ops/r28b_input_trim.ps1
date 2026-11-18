# Row-28b forward inputs: the (a) as-of-capture trim of published MG-2 bundles (one-shot; master-run weekly).
#
# Runs on the dedicated capture host only, inside 00:30-09:00 America/Toronto and not before 07:30 (after the
# 04:15 MG-2 export and its 07:00 retry), under the shared workload lease. Master starts it detached, once per
# weekly batch (master 2026-11-04, Q5). There is NO scheduled task and this file registers nothing.
# It wraps `python -m weather.calibration.r28b_input_trim`, which reads only the published
# <repo>\data\exports\mg2-inputs\<D>\ bundles and writes only under <repo>\data\exports\r28b-inputs:
#   <D>\ (published by an atomic rename from .<D>.partial), <D>.SHA256SUMS, _holes\<D>.json (a named hole), and
#   this wrapper's run receipt and captured child output under _runs\.
# The child prints one JSON line per date (status, trimmed manifest sha or hole sha). Master logs each trimmed
# manifest sha with the host timestamp the same day; the workstation verifier checks against that logged sha.
# Dates outside 2026-12-17..2027-01-30, and any run before 2026-12-21, are refused by the module.
# Expected cost: well under a minute and well under 1 GB of memory (published bundles are streamed line by line).
[CmdletBinding()]
param(
    [string]$ProductionRepoRoot = "",
    # Local target dates D of one weekly batch: yyyy-MM-dd, comma-separated, at most 7 (one string, so that it
    # binds the same way under powershell -File).
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})(,\d{4}-\d{2}-\d{2}){0,6}$')][string]$Date = "",
    [ValidateRange(60, 3600)][int]$MaxRuntimeSeconds = 900,
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
if (-not $Date) { throw 'one weekly batch: -Date with 1 to 7 comma-separated dates is required' }
$Dates = @($Date -split ',')
$ProductionRepoRoot = [IO.Path]::GetFullPath($ProductionRepoRoot).TrimEnd('\')
$dataRoot = Join-Path $ProductionRepoRoot 'data'
$inRoot = Join-Path $dataRoot 'exports\mg2-inputs'
$outRoot = Join-Path $dataRoot 'exports\r28b-inputs'
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
$childTokens = @('-P', '-B', '-m', 'weather.calibration.r28b_input_trim')
foreach ($d in $Dates) { $childTokens += @('--date', $d) }
$childTokens += @('--source-root', $inRoot, '--out', $outRoot)

if ($PlanOnly) {
    [ordered]@{
        dates = @($Dates); production_repo_root = $ProductionRepoRoot; source_root = $sourceRoot
        mg2_inputs_root = $inRoot; out_root = $outRoot; python = $python; child_arguments = $childTokens
        max_runtime_seconds = $MaxRuntimeSeconds; not_before_local = '07:30'; window_end_local = '09:00'
    } | ConvertTo-Json -Compress
    return
}

$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$minute = $localNow.Hour * 60 + $localNow.Minute
if ($minute -lt 450 -or $minute -ge 540) {
    throw 'REFUSED: restricted to 07:30-09:00 America/Toronto (inside 00:30-09:00, after the 04:15 and 07:00 exports)'
}
$windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddHours(9), $zone)
$deadline = [DateTime]::UtcNow.AddSeconds($MaxRuntimeSeconds)
if ($deadline -gt $windowEnd.AddSeconds(-60)) { $deadline = $windowEnd.AddSeconds(-60) }
if (($deadline - [DateTime]::UtcNow).TotalSeconds -lt 120) {
    throw 'REFUSED: insufficient time for a bounded child and teardown'
}
if (-not (Test-Path -LiteralPath $inRoot -PathType Container)) {
    throw ("REFUSED: no published MG-2 export root at {0}" -f $inRoot)
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

# Run with -P -B and PYTHONPATH=<source>\src, and prove the module resolves under that tree before any read.
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $sourceRoot 'src')).TrimEnd('\') + '\'
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
try {
    $ErrorActionPreference = 'Continue'
    $probe = @(& $python -P -B -c 'import weather.calibration.r28b_input_trim as m; print(m.__file__)' 2>&1 |
        ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $resolved = if ($probe.Count) { $probe[-1].Trim() } else { '' }
    $resolvedFull = try { [IO.Path]::GetFullPath($resolved) } catch { '' }
    if ($probeCode -ne 0 -or -not $resolvedFull -or
        -not $resolvedFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("trim module does not resolve under {0}: {1}" -f $pinnedSrc, ($probe -join ' '))
    }
}
finally { $env:PYTHONPATH = $oldPythonPath }

$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'r28b_input_trim' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }
$job = $null
$child = $null
$capture = $null
$exitCode = $null
$staleStaging = @()
$runs = Join-Path $outRoot '_runs'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$receiptPath = Join-Path $runs ("{0}-{1}.json" -f $Dates[0], $stamp)
$stdoutPath = Join-Path $runs ("{0}-{1}.stdout.log" -f $Dates[0], $stamp)
try {
    # Under the lease no other trim runs, so a staging folder left by a killed earlier run of one of these dates
    # is this module's own unpublished output: remove exactly that folder and nothing else.
    foreach ($d in $Dates) {
        $staging = Join-Path $outRoot (".{0}.partial" -f $d)
        if (Test-Path -LiteralPath $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
            $staleStaging += $d
        }
    }
    $null = New-Item -ItemType Directory -Force -Path $runs
    $capture = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        $stdoutPath, (Join-Path $runs ("{0}-{1}.stderr.log" -f $Dates[0], $stamp)), 1048576)
    $env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens) `
        -WorkingDirectory $sourceRoot -OutputCapture $capture
    $null = $child.Handle
    while (-not $child.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'r28b input trim deadline exceeded' }
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
                    schema = 'r28b_input_trim_run/1'; dates = @($Dates); exit_code = $exitCode
                    stale_staging_removed = @($staleStaging); stdout_log = $stdoutPath
                    finished_utc = [DateTime]::UtcNow.ToString('o'); source_root = $sourceRoot
                } | ConvertTo-Json -Compress | Set-Content -LiteralPath $receiptPath -Encoding ASCII
            }
        }
        finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
    }
}
# The child's per-date JSON lines (statuses and shas only) for master's log.
if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
    Get-Content -LiteralPath $stdoutPath | Where-Object { $_ -like '{*' } | ForEach-Object { Write-Output $_ }
}
# 0 trimmed; 2 refused; 3 not ready (before a date's deadline); 4 a named hole was recorded or already stands.
if ($exitCode -ne 0) { throw ("r28b input trim failed, incomplete or holed: exit {0}" -f $exitCode) }
Write-Output ("r28b input trim complete: {0}" -f ($Dates -join ','))
