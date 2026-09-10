# One-shot night controller. Each heavy child independently holds the shared lease.
param(
    [Parameter(Mandatory = $true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PlanSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [Parameter(Mandatory = $true)][ValidateSet('early','late')][string]$Segment,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check source before loading its helper code.
$tip = [string](git -C $sourceRoot rev-parse HEAD)
$dirty = @(git -C $sourceRoot status --porcelain)
if ($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip -or $dirty.Count -ne 0) {
    throw 'night source is not the exact clean reviewed tip'
}
. (Join-Path $PSScriptRoot 'storage_recovery_night_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
Assert-WeatherNightSource $sourceRoot $ExpectedSourceTip
$plan = Read-WeatherNightPlan $ProductionRepoRoot $sourceRoot $ExpectedSourceTip $PlanPath $PlanSha256
$times = Get-WeatherNightTimes $plan $Segment
$deadline = $times.End
$outputName = $Segment
if ($PreflightOnly) {
    if ([DateTime]::UtcNow -ge (Get-WeatherNightTimes $plan 'early').Start) { throw 'preflight must precede the night' }
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    $outputName = 'preflight'
}
elseif ([DateTime]::UtcNow -lt $times.Start -or [DateTime]::UtcNow -gt $times.Start.AddSeconds(60)) {
    throw 'night segment missed its exact one-minute start window'
}
$nightRoot = Join-Path $ProductionRepoRoot ('scratch\storage_recovery_nights\' + $plan.plan_id)
$outputRoot = Join-Path $nightRoot $outputName
Assert-WeatherNightDirectory $nightRoot
if (Test-Path -LiteralPath $outputRoot) { throw 'spent night segment namespace' }
$python = Join-Path $ProductionRepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'production interpreter missing' }
$job = $null
$process = $null
$teardown = $false
$exitCode = 1
$priorEnv = @{}
$envValues = @{
    PYTHONPATH = (Join-Path $sourceRoot 'src')
    WEATHER_STORAGE_RECOVERY_NIGHT_SOURCE_ROOT = $sourceRoot
    WEATHER_STORAGE_RECOVERY_NIGHT_OWNER_PID = [string]$PID
    WEATHER_STORAGE_RECOVERY_NIGHT_OWNER_TOKEN = ('win32-filetime:' + [Diagnostics.Process]::GetCurrentProcess().StartTime.ToFileTimeUtc())
    WEATHER_STORAGE_RECOVERY_NIGHT_DEADLINE_UTC = $deadline.ToString('o')
    WEATHER_STORAGE_RECOVERY_NIGHT_PREFLIGHT = [string][int][bool]$PreflightOnly
}
$receipt = [ordered]@{
    plan_sha256 = $PlanSha256; source_git_sha = $ExpectedSourceTip
    execution_host_id = $plan.execution_host_id; segment = $outputName
    started_at_utc = [DateTime]::UtcNow.ToString('o'); deadline_utc = $deadline.ToString('o')
    status = 'FAILED'; hard_stop = $false; teardown_proved = $false
    deleted_files = 0; cleanup_eligible = $false
}
try {
    $null = New-Item -ItemType Directory -Path $outputRoot
    foreach ($key in $envValues.Keys) {
        $priorEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $envValues[$key], 'Process')
    }
    $arguments = @('-m', 'weather.operations.storage_recovery_night',
        '--production-repo-root', $ProductionRepoRoot, '--plan', $PlanPath,
        '--plan-sha256', $PlanSha256, '--source-git-sha', $ExpectedSourceTip,
        '--output-root', $outputRoot, '--segment', $Segment)
    if ($PreflightOnly) { $arguments += '--preflight-only' }
    $job = New-WeatherKillOnCloseJob
    $launch = @{Job = $job; FilePath = $python; WorkingDirectory = $sourceRoot
                ArgumentString = (ConvertTo-WeatherWindowsArgumentString -Tokens $arguments)}
    $process = Start-WeatherProcessInJob @launch
    $null = $process.Handle
    $process.PriorityClass = [Diagnostics.ProcessPriorityClass]::BelowNormal
    while (-not $process.HasExited) {
        if ([DateTime]::UtcNow -ge $deadline -or
            $process.PrivateMemorySize64 -gt 256MB -or $process.WorkingSet64 -gt 256MB) {
            $receipt.hard_stop = $true
            throw 'night controller exceeded its absolute deadline or process-memory bound'
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $job.TerminateAndWait(5000)
    $teardown = $true
    if ($null -eq $exitCode -or $exitCode -ne 0) { throw 'night controller did not close successfully' }
    $resultPath = Join-Path $outputRoot 'result.json'
    $info = Get-Item -LiteralPath $resultPath -Force
    if ($info.Length -gt 2097152 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'invalid night result file'
    }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    $safe = @('TARGET_MET','WINDOW_COMPLETE','CANDIDATES_EXHAUSTED','RESOURCE_LIMITED','BUDGET_COMPLETE')
    if ($PreflightOnly) { $safe = @('PREFLIGHT_PASS') }
    if ($result.status -cnotin $safe -or $result.plan_sha256 -cne $PlanSha256 -or
        $result.source_git_sha -cne $ExpectedSourceTip -or $result.execution_host_id -cne $plan.execution_host_id -or
        $result.deleted_files -ne 0 -or $result.cleanup_eligible -ne $false) { throw 'night result binding mismatch' }
    if ($PreflightOnly -and ($result.source_payload_bytes_read -ne 0 -or $result.source_files_changed -ne 0)) {
        throw 'preflight changed or read source payloads'
    }
    Assert-WeatherNightSource $sourceRoot $ExpectedSourceTip
    $null = Read-WeatherNightPlan $ProductionRepoRoot $sourceRoot $ExpectedSourceTip $PlanPath $PlanSha256
    $receipt.child_result_sha256 = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt.child_status = $result.status
    $receipt.status = 'PASS'
    $exitCode = 0
}
catch {
    $receipt.error = $_.Exception.Message
    $receipt.status = 'FAILED'
    $exitCode = 1
}
finally {
    try {
        if ($job -and -not $teardown) { $job.TerminateAndWait(5000); $teardown = $true }
        if (-not $job) { $teardown = $true }
    }
    finally {
        $receipt.teardown_proved = $teardown
        if (-not $teardown) { $receipt.status = 'TEARDOWN_UNPROVED'; $exitCode = 1 }
        $receipt.completed_at_utc = [DateTime]::UtcNow.ToString('o')
        if ($job) { $job.Dispose() }
        if ($process) { $process.Dispose() }
        foreach ($key in $priorEnv.Keys) { [Environment]::SetEnvironmentVariable($key, $priorEnv[$key], 'Process') }
        if (Test-Path -LiteralPath $outputRoot -PathType Container) {
            Write-WeatherNightJson (Join-Path $outputRoot 'wrapper-result.json') $receipt
        }
    }
}
Write-Output ($receipt | ConvertTo-Json -Depth 8 -Compress)
exit $exitCode
