# Attended exact-request cold snapshot compression. All source files retained.
# Source may be a clean reviewed worktree; production capture source is untouched.
param(
    [Parameter(Mandatory = $true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$minute = $localNow.Hour * 60 + $localNow.Minute
if ($minute -lt 30 -or $minute -ge 540) {
    throw 'REFUSED: cold snapshot compression is restricted to 00:30-09:00 America/Toronto'
}
if ($minute -ge 285 -and $minute -lt 405) {
    throw 'REFUSED: 04:45-06:45 is reserved for the existing scheduled tiering jobs'
}
# Reserve teardown time before the protected boundary, even for late starts.
$windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddHours(9), $zone)
if ($minute -lt 285) {
    $windowEnd = [TimeZoneInfo]::ConvertTimeToUtc($localNow.Date.AddMinutes(285), $zone)
}
$deadline = [DateTime]::UtcNow.AddSeconds(600)
if ($deadline -gt $windowEnd.AddSeconds(-15)) { $deadline = $windowEnd.AddSeconds(-15) }
if (($deadline - [DateTime]::UtcNow).TotalSeconds -lt 30) {
    throw 'REFUSED: insufficient time for a bounded child and teardown'
}

foreach ($path in @($ProductionRepoRoot, $RequestPath, $OutputRoot)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '["\r\n]' -or
        [IO.Path]::GetFullPath($path).TrimEnd('\') -cne $path.TrimEnd('\')) {
        throw 'absolute normalized paths without quotes or newlines are required'
    }
}

function Assert-CacheEvidenceAncestors {
    param([string]$Path)
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw 'evidence ancestors must be ordinary directories without reparse points'
            }
        }
        $current = Split-Path -Parent $current
    }
}

$outputParent = Join-Path $ProductionRepoRoot 'scratch\cold_snapshot_compression'
if (-not $OutputRoot.StartsWith($outputParent + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'output must be a new attempt under production scratch\cold_snapshot_compression'
}
if (Test-Path -LiteralPath $OutputRoot) { throw 'spent output attempt: use a new reviewed request' }
Assert-CacheEvidenceAncestors -Path (Split-Path -Parent $OutputRoot)
$requestInfo = Get-Item -LiteralPath $RequestPath
if ($requestInfo.Length -gt 131072 -or
    ($requestInfo.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'request is too large or is a reparse point'
}
if ((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RequestSha256) {
    throw 'request SHA-256 mismatch'
}
$tip = [string](git -C $sourceRoot rev-parse HEAD)
if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip) { throw 'source tip mismatch' }
$dirty = @(git -C $sourceRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) { throw 'source worktree must be clean' }

. (Join-Path $sourceRoot 'scripts\ops\workload_admission.ps1')
. (Join-Path $sourceRoot 'scripts\ops\windows_kill_on_close_job.ps1')
. (Join-Path $sourceRoot 'scripts\ops\training_window_contract.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
$hostIdentity = Get-WeatherExecutionHostId
if ($hostIdentity -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'this runner is restricted to the assigned dedicated capture host'
}
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production project interpreter missing' }
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $ProductionRepoRoot `
    -Workload 'cold_snapshot_compression' -ExpectedExecutionHostId $hostIdentity
if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }

$job = $null
$process = $null
$exitCode = 1
$teardownProved = $false
$oldPythonPath = $env:PYTHONPATH
$oldSource = $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_SOURCE_ROOT
$oldOwner = $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_OWNER_PID
$oldDeadline = $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_DEADLINE_UTC
$receipt = [ordered]@{
    source_git_sha = $ExpectedSourceTip; request_sha256 = $RequestSha256
    execution_host_id = $hostIdentity; apply = [bool]$Apply
    started_at_utc = [DateTime]::UtcNow.ToString('o'); status = 'FAILED'
    hard_stop = $false; teardown_proved = $false; deleted_files = 0; cleanup_eligible = $false
}
try {
    # Identity, time and live lease precede even create-only attempt evidence.
    $null = New-Item -ItemType Directory -Path $OutputRoot
    $env:PYTHONPATH = Join-Path $sourceRoot 'src'
    $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_SOURCE_ROOT = $sourceRoot
    $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_OWNER_PID = [string]$PID
    $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_DEADLINE_UTC = $deadline.ToString('o')
    $arguments = @('-m', 'weather.operations.cold_snapshot_compression',
        '--production-repo-root', $ProductionRepoRoot, '--request', $RequestPath,
        '--request-sha256', $RequestSha256, '--output-root', $OutputRoot,
        '--source-git-sha', $ExpectedSourceTip)
    if ($Apply) {
        $arguments += @('--apply')
    }
    $job = New-WeatherKillOnCloseJob
    $process = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString (ConvertTo-ScheduledTaskArgumentString -Tokens $arguments) `
        -WorkingDirectory $sourceRoot
    $null = $process.Handle
    $process.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    while (-not $process.HasExited) {
        if ([DateTime]::UtcNow -ge $deadline -or
            $process.PrivateMemorySize64 -gt 384MB -or $process.WorkingSet64 -gt 384MB) {
            $receipt.hard_stop = $true
            $receipt.error = 'child deadline or monitored process memory ceiling reached'
            break
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    if (-not $receipt.hard_stop) {
        $process.WaitForExit()
        $exitCode = $process.ExitCode
        if ($null -eq $exitCode) { $exitCode = 1 }
    }
    $job.TerminateAndWait(5000)
    $teardownProved = $true
    $resultPath = Join-Path $OutputRoot 'result.json'
    if ($exitCode -eq 0 -and -not $receipt.hard_stop -and (Test-Path -LiteralPath $resultPath)) {
        if ((Get-Item -LiteralPath $resultPath).Length -gt 2097152) { throw 'oversized child receipt' }
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ($result.status -cne 'PASS' -or $result.request_sha256 -cne $RequestSha256 -or
            $result.source_git_sha -cne $ExpectedSourceTip -or $result.apply -ne [bool]$Apply -or
            $result.deleted_files -ne 0 -or $result.cleanup_eligible -ne $false -or
            $result.execution_host_id -cne $hostIdentity) { throw 'child receipt binding mismatch' }
        $finalTip = [string](git -C $sourceRoot rev-parse HEAD)
        if ($LASTEXITCODE -ne 0 -or $finalTip.Trim() -cne $ExpectedSourceTip) { throw 'source tip changed during operation' }
        $finalDirty = @(git -C $sourceRoot status --porcelain)
        if ($LASTEXITCODE -ne 0 -or $finalDirty.Count -ne 0) { throw 'source worktree changed during operation' }
        if ((Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RequestSha256) {
            throw 'approved request changed during operation'
        }
        $receipt.child_result_sha256 = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $receipt.status = 'PASS'
        $receipt.reclaimed_bytes = $result.reclaimed_bytes
    }
    else {
        if (-not $receipt.Contains('error')) { $receipt.error = 'child did not produce PASS; retain attempt and inspect child receipts' }
        $exitCode = 1
    }
}
catch {
    $receipt.error = $_.Exception.Message
    $exitCode = 1
}
finally {
    try {
        if ($job -and -not $teardownProved) { $job.TerminateAndWait(5000); $teardownProved = $true }
        if (-not $job) { $teardownProved = $true }
    }
    finally {
        $receipt.teardown_proved = $teardownProved
        $receipt.completed_at_utc = [DateTime]::UtcNow.ToString('o')
        if (-not $teardownProved) { $receipt.status = 'TEARDOWN_UNPROVED'; $exitCode = 1 }
        if ($job) { $job.Dispose() }
        if ($process) { $process.Dispose() }
        $env:PYTHONPATH = $oldPythonPath
        $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_SOURCE_ROOT = $oldSource
        $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_OWNER_PID = $oldOwner
        $env:WEATHER_COLD_SNAPSHOT_COMPRESSION_DEADLINE_UTC = $oldDeadline
        if ($teardownProved) { Exit-WeatherHeavyWorkloadLease -Lease $lease }
        else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease }
        if (Test-Path -LiteralPath $OutputRoot -PathType Container) {
            Assert-CacheEvidenceAncestors -Path $OutputRoot
            $receiptPath = Join-Path $OutputRoot 'wrapper-result.json'
            $stream = [IO.File]::Open($receiptPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            try {
                $bytes = [Text.Encoding]::UTF8.GetBytes(($receipt | ConvertTo-Json -Depth 8) + [Environment]::NewLine)
                $stream.Write($bytes, 0, $bytes.Length)
                $stream.Flush($true)
            }
            finally { $stream.Dispose() }
        }
    }
}
Write-Output ($receipt | ConvertTo-Json -Depth 8 -Compress)
exit $exitCode
