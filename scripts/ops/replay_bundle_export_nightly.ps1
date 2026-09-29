# Export yesterday's sealed UTC evidence without touching capture or Scheduler.
# Exact source tip + self hash are pinned by the registrar. 110r owns interval readers.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSelfSha256,
    [ValidatePattern('^(\d{4}-\d{2}-\d{2})?$')][string]$Day = '',
    [ValidateSet('05:00-08:00')][string]$ExcludeUtc = '05:00-08:00'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

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
    $deadline = $NowUtc.AddSeconds(330)
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
    $tip = [string](git -C $RepoRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip) { throw 'source tip mismatch' }
    $dirty = @(git -C $RepoRoot status --porcelain --untracked-files=normal -- src scripts/ops)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw 'export source must be clean' }
    $hash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $ExpectedSelfSha256) { throw 'nightly wrapper hash mismatch' }
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
if (-not $Day) { $Day = [DateTime]::UtcNow.Date.AddDays(-1).ToString('yyyy-MM-dd') }
$parsedDay = [DateTime]::ParseExact($Day, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
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
    $tokens = @('-B', '-m', 'weather.market.maker_plugin.replay_export', 'night', '--day', $Day,
        '--data-root', $DataRoot, '--release-root', $ReleaseRoot, '--out', $OutputRoot, '--exclude-utc', $ExcludeUtc)
    if ([DateTime]::UtcNow -ge $deadline) { throw 'deadline elapsed during admission' }
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
