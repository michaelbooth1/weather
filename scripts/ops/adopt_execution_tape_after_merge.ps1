# Re-arm the read-only public execution-tape producer only after an exact,
# successful guarded merge. Any failed post-start proof stops the exact managed
# worker through its supervisor and disables the recurring task again.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$MergeTaskName,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$SupervisorTaskName = "WeatherExecutionTapeSupervisor",
    [int]$StaleAfterSeconds = 180
)

$ErrorActionPreference = "Stop"
$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$pythonw = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
$expectedArguments = "-m weather.operations.execution_tape_supervisor ensure --market all --stale-after-seconds $StaleAfterSeconds"
$enabledByThisRun = $false

function Refuse-Adoption {
    param([Parameter(Mandatory = $true)][string]$Reason)

    $cleanup = $null
    if ($script:enabledByThisRun) {
        try {
            $cleanupOutput = & $script:python -m weather.operations.execution_tape_supervisor stop 2>&1
            $cleanup = [PSCustomObject]@{
                exit_code = $LASTEXITCODE
                output = (@($cleanupOutput) -join "`n")
            }
        }
        catch {
            $cleanup = [PSCustomObject]@{ exit_code = 1; output = $_.Exception.Message }
        }
        Disable-ScheduledTask -TaskName $script:SupervisorTaskName -ErrorAction SilentlyContinue | Out-Null
    }
    Write-Output ([PSCustomObject]@{
            adopted = $false
            reason = $Reason
            cleanup = $cleanup
        } | ConvertTo-Json -Depth 8)
    exit 1
}

if ($ExpectedTip -notmatch "^[0-9a-f]{40}$") {
    Refuse-Adoption "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    Refuse-Adoption "repository virtual-environment interpreters are missing"
}

$mergeTask = Get-ScheduledTask -TaskName $MergeTaskName -ErrorAction SilentlyContinue
$mergeInfo = Get-ScheduledTaskInfo -TaskName $MergeTaskName -ErrorAction SilentlyContinue
if ($null -eq $mergeTask -or $null -eq $mergeInfo) {
    Refuse-Adoption "guarded merge task is unavailable"
}
if ([string]$mergeTask.State -eq "Running") {
    Refuse-Adoption "guarded merge task is still running"
}
if ([datetime]$mergeInfo.LastRunTime -lt (Get-Date).Date -or
    [int]$mergeInfo.LastTaskResult -ne 0) {
    Refuse-Adoption "guarded merge did not complete successfully on the current local day"
}
$mergeActions = @($mergeTask.Actions)
if ($mergeActions.Count -ne 1 -or
    [string]$mergeActions[0].Arguments -notlike "*suite_gated_quiet_merge.ps1*") {
    Refuse-Adoption "merge task is not bound to the suite-gated quiet-window wrapper"
}
$tipPattern = "(?i)(?:^|\s)-ExpectedTip\s+" + [regex]::Escape($ExpectedTip) + "(?:\s|$)"
if ([string]$mergeActions[0].Arguments -notmatch $tipPattern) {
    Refuse-Adoption "merge task is not bound to ExpectedTip"
}

& git -C $RepoRoot merge-base --is-ancestor $ExpectedTip master 2>$null
if ($LASTEXITCODE -ne 0) {
    Refuse-Adoption "ExpectedTip is not in local master history"
}
$masterTip = (& git -C $RepoRoot rev-parse master 2>$null).Trim().ToLowerInvariant()
$originTip = (& git -C $RepoRoot rev-parse origin/master 2>$null).Trim().ToLowerInvariant()
if (-not $masterTip -or $masterTip -ne $originTip) {
    Refuse-Adoption "local master and origin/master are not exact"
}

$captureOutput = & $python -m weather.operations.capture_recovery_check --json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $captureOutput) {
    Refuse-Adoption "core capture recovery proof failed"
}
$capture = $captureOutput | ConvertFrom-Json
if ($capture.ok -ne $true -or @($capture.workers).Count -ne 3 -or
    @($capture.workers | Where-Object { $_.ok -ne $true }).Count -ne 0) {
    Refuse-Adoption "core capture is not healthy for all three workers"
}

$supervisorTask = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction SilentlyContinue
if ($null -eq $supervisorTask) {
    Refuse-Adoption "execution-tape supervisor task is unavailable"
}
$actions = @($supervisorTask.Actions)
if ($actions.Count -ne 1 -or
    [IO.Path]::GetFullPath([string]$actions[0].Execute) -ine [IO.Path]::GetFullPath($pythonw) -or
    [string]$actions[0].Arguments -cne $expectedArguments -or
    [IO.Path]::GetFullPath([string]$actions[0].WorkingDirectory) -ine $RepoRoot) {
    Refuse-Adoption "execution-tape supervisor action is not exact"
}
if ([string]$supervisorTask.Principal.LogonType -ne "S4U" -or
    [string]$supervisorTask.Principal.RunLevel -ne "Limited" -or
    [int]$supervisorTask.Settings.Priority -ne 7) {
    Refuse-Adoption "execution-tape supervisor principal or priority is not exact"
}
if ([string]$supervisorTask.State -ne "Disabled") {
    Refuse-Adoption "execution-tape supervisor was not held Disabled before adoption"
}

$before = Get-ScheduledTaskInfo -TaskName $SupervisorTaskName
Enable-ScheduledTask -TaskName $SupervisorTaskName | Out-Null
$enabledByThisRun = $true
Start-ScheduledTask -TaskName $SupervisorTaskName
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Milliseconds 500
    $supervisorTask = Get-ScheduledTask -TaskName $SupervisorTaskName
    $after = Get-ScheduledTaskInfo -TaskName $SupervisorTaskName
    $completedThisRun = [datetime]$after.LastRunTime -gt [datetime]$before.LastRunTime
} while ((-not $completedThisRun -or [string]$supervisorTask.State -eq "Running") -and
    (Get-Date) -lt $deadline)
if (-not $completedThisRun -or [string]$supervisorTask.State -eq "Running" -or
    [int]$after.LastTaskResult -ne 0) {
    Refuse-Adoption "first supervised ensure did not complete successfully"
}

$healthOutput = & $python -m weather.operations.execution_tape_supervisor status `
    --stale-after-seconds $StaleAfterSeconds 2>$null
if ($LASTEXITCODE -ne 0 -or -not $healthOutput) {
    Refuse-Adoption "managed execution-tape status proof failed"
}
$healthPayload = $healthOutput | ConvertFrom-Json
$health = $healthPayload.health
$status = $healthPayload.status
$writerLockPath = Join-Path $RepoRoot "data\snapshots\.execution_tape_status.json.writer.lock"
if (-not (Test-Path -LiteralPath $writerLockPath -PathType Leaf)) {
    Refuse-Adoption "managed execution-tape writer lock is missing"
}
$writerLock = Get-Content -LiteralPath $writerLockPath -Raw | ConvertFrom-Json
if (@("RUNNING", "DEGRADED") -notcontains [string]$health.state -or
    $health.pid_alive -ne $true -or
    $health.runtime_identity_matches_current -ne $true -or
    [string]$health.evidence_integrity -ne "PASS" -or
    [string]$status.state -ne "CONNECTED" -or
    [string]$status.market -ne "all" -or
    [string]$status.runner -ne "managed_execution_tape" -or
    $status.managed_process.verified_at_capture -ne $true -or
    [int]$status.pid -ne [int]$status.managed_process.pid -or
    [int]$status.pid -ne [int]$writerLock.pid -or
    [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
    [string]$status.managed_process.creation_time_token -cne
        [string]$writerLock.managed_process.creation_time_token) {
    Refuse-Adoption "managed worker, status, lock, source, or evidence contract disagrees"
}

$captureAfterOutput = & $python -m weather.operations.capture_recovery_check --json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $captureAfterOutput -or
    ($captureAfterOutput | ConvertFrom-Json).ok -ne $true) {
    Refuse-Adoption "core capture did not remain healthy after adoption"
}

Write-Output ([PSCustomObject]@{
        adopted = $true
        expected_tip = $ExpectedTip
        master = $masterTip
        merge_task = $MergeTaskName
        supervisor_task = $SupervisorTaskName
        supervisor_result = ("0x{0:X}" -f [uint32]$after.LastTaskResult)
        state = $health.state
        capture_state = $status.state
        evidence_integrity = $health.evidence_integrity
        price_path_evidence_usable = $health.price_path_evidence_usable
        runtime_identity_matches_current = $health.runtime_identity_matches_current
        worker_pid = [int]$status.pid
        writer_lock_pid = [int]$writerLock.pid
        core_capture_workers = @($capture.workers).Count
    } | ConvertTo-Json -Depth 8)
exit 0
