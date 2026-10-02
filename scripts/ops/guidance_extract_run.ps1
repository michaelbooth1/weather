# Mission 111h: admitted, bounded, read-only NBM v2 guidance extract. Never registers a task.
# Code runs from a clean reviewed worktree of the mission branch; parser v2 runs from a clean
# detached worktree of 2e17ce0eb. Production capture source and data are only read; the sole
# write is a new output directory under data\exports.
param(
    [Parameter(Mandatory = $true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [Parameter(Mandatory = $true)][string]$ParserWorktree,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$From = '2026-08-01',
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$To = '2026-09-29',
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 7200,
    [ValidateRange(1073741824, 549755813888)][long]$MaxInputBytes = 171798691840,
    [ValidateRange(1048576, 17179869184)][long]$MaxFileBytes = 4294967296
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$minute = $localNow.Hour * 60 + $localNow.Minute
if ($minute -lt 30 -or $minute -ge 540) { throw 'REFUSED: restricted to 00:30-09:00 America/Toronto' }
$windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddHours(9), $zone)
$deadline = [DateTime]::UtcNow.AddSeconds($MaxRuntimeSeconds)
if ($deadline -gt $windowEnd.AddSeconds(-60)) { $deadline = $windowEnd.AddSeconds(-60) }
$childSeconds = [int][Math]::Floor(($deadline - [DateTime]::UtcNow).TotalSeconds) - 30
if ($childSeconds -lt 60) { throw 'REFUSED: insufficient time for a bounded child and teardown' }

foreach ($path in @($ProductionRepoRoot, $ParserWorktree, $OutputRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($path).TrimEnd('\') -cne $path.TrimEnd('\')) {
        throw 'absolute normalized paths without quotes or newlines are required'
    }
}
$exportsRoot = Join-Path $ProductionRepoRoot 'data\exports'
if (-not $OutputRoot.StartsWith($exportsRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'output must be a new directory under production data\exports'
}
if (Test-Path -LiteralPath $OutputRoot) { throw 'spent output directory: choose a new one' }
if ((Get-PSDrive C).Free -lt 50GB) { throw 'REFUSED: less than 50 GiB free' }
$memoryPath = Join-Path $ProductionRepoRoot 'data\logs\memory_commit_guard_status.json'
$memory = Get-Content -LiteralPath $memoryPath -Raw | ConvertFrom-Json
if (((Get-Date) - (Get-Item -LiteralPath $memoryPath).LastWriteTime).TotalMinutes -gt 5 -or
    $null -eq $memory.commit_percent -or [double]$memory.commit_percent -ge 70) {
    throw 'REFUSED: memory evidence blocks admission'
}

$tip = [string](git -C $sourceRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip) { throw 'source tip mismatch' }
$dirty = @(git -C $sourceRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'source worktree must be clean' }
$parserHead = [string](git -C $ParserWorktree rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or -not $parserHead.Trim().StartsWith('2e17ce0eb')) { throw 'parser worktree is not 2e17ce0eb' }
$parserDirty = @(git -C $ParserWorktree status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $parserDirty.Count -ne 0) { throw 'parser worktree must be clean' }

. (Join-Path $sourceRoot 'scripts\ops\workload_admission.ps1')
. (Join-Path $sourceRoot 'scripts\ops\windows_kill_on_close_job.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
$hostIdentity = Get-WeatherExecutionHostId
if ($hostIdentity -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'this runner is restricted to the assigned dedicated capture host'
}
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production project interpreter missing' }

# The production venv may carry an editable path to the production checkout. Run with -P -B and
# PYTHONPATH=<source>\src, and prove the extractor resolves under that tree before any read.
$pinnedSrc = [IO.Path]::GetFullPath((Join-Path $sourceRoot 'src')).TrimEnd('\') + '\'
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
try {
    $ErrorActionPreference = 'Continue'
    $probe = @(& $python -P -B -c 'import weather.reporting.research.guidance_extract as m; print(m.__file__)' 2>&1 |
        ForEach-Object { "$_" })
    $probeCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $resolved = if ($probe.Count) { $probe[-1].Trim() } else { '' }
    $resolvedFull = try { [IO.Path]::GetFullPath($resolved) } catch { '' }
    if ($probeCode -ne 0 -or -not $resolvedFull -or
        -not $resolvedFull.StartsWith($pinnedSrc, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("extractor does not resolve under {0}: {1}" -f $pinnedSrc, ($probe -join ' '))
    }
}
finally { $env:PYTHONPATH = $oldPythonPath }

$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'guidance_extract_111h' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }
$job = $null
$child = $null
try {
    $tokens = @('-P', '-B', '-m', 'weather.reporting.research.guidance_extract',
        '--data-root', (Join-Path $ProductionRepoRoot 'data'), '--out', $OutputRoot,
        '--from', $From, '--to', $To, '--parser-worktree', $ParserWorktree, '--parser-python', $python,
        '--max-input-bytes', [string]$MaxInputBytes, '--max-file-bytes', [string]$MaxFileBytes,
        '--max-runtime-seconds', [string]$childSeconds)
    $env:PYTHONPATH = $pinnedSrc.TrimEnd('\')
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $sourceRoot
    $null = $child.Handle
    while (-not $child.WaitForExit(1000)) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'guidance extract deadline exceeded' }
    }
    if ($child.ExitCode -ne 0) { throw "guidance extract failed or incomplete: exit $($child.ExitCode)" }
    Write-Output ("guidance extract complete: {0}" -f $OutputRoot)
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    # Teardown must complete before the shared lease is released.
    try { if ($job) { $job.TerminateAndWait(5000) } }
    finally {
        if ($child) { $child.Dispose() }
        if ($job) { $job.Dispose() }
    }
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
