<#
.SYNOPSIS
    Resume the daily refresh chain from a named step in the heavy-work window.

.DESCRIPTION
    The chain hard-stops at the settled-day barrier when any dependency blocks, and
    everything after the barrier simply never runs. On 2026-07-27 a single transient WU
    timeout on one market stopped it at step 20 of 43, losing promotion_refresh,
    daily_learning and market_beating_objective_scoreboard for the day.

    Once the blocking condition is cleared, those steps are recoverable by resuming --
    but the resume is a multi-hour, memory-hungry run, and memory pressure during
    protected host time is the top cause of capture gaps, which is what costs streak
    days. So this accepts ad-hoc work only from 00:30 through 09:00 local, using the
    repository-owned load policy rather than a duplicated hour check.

    Resuming from a step re-runs that step and everything after it. Steps before it keep
    their previously recorded results, so resume from the step that actually failed, not
    from the barrier that reported it -- the barrier reads the earlier step's persisted
    artifact and will just block again on the stale BLOCK.

.PARAMETER ResumeFrom
    Chain step to resume from, e.g. public_wu_settlement_restore.

.PARAMETER TargetDate
    Settled-analysis target date (yyyy-MM-dd). The chain normally targets yesterday.

.PARAMETER Refetch
    Force the WU settlement restore to fetch the target day even when the store
    believes there is nothing to fetch.

    Needed whenever the restore already failed on this date with a status code the
    classifier calls permanent. `write_fetch_error` stamps such a row
    `treated_as_source_unavailable`, `unavailable_dates()` collects it, and
    `missing_dates()` subtracts it -- so the plain resume finds an empty range and
    silently fetches nothing. `recover_unavailable_errors()` does not undo it either,
    because `failure_class_for_error_row` returns the *stored* class rather than
    re-deriving it. On 2026-08-06 all 12 stations 404'd inside an 8-minute window
    (the same URLs served 200 minutes later), which poisoned 2026-08-05 fleet-wide.
    This switch passes --wu-settlement-restore-refetch, which takes the target range
    unconditionally instead of via missing_ranges().

.PARAMETER StopAfter
    End after this exact daily-refresh step. The Python orchestrator records a
    bounded-recovery receipt and suppresses downstream readiness, stage
    publication, evidence triggering, and daily-progress writes. Use this for
    one-purpose repairs such as settlement backfill.

.PARAMETER Force
    Retained for action compatibility. It does not bypass the repository host
    load policy: ad-hoc recovery remains restricted to 00:30-09:00 local.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ResumeFrom,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$TargetDate,
    [switch]$Refetch,
    [string]$StopAfter = '',
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$backtestRoot = Join-Path $repo "data\backtest"
$logDir = Join-Path $repo "data\ops\chain_recovery"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$stamp = "$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')-$PID"
$log = Join-Path $logDir "recovery-$stamp.log"
$errLog = Join-Path $logDir "recovery-$stamp.err"
$repairLog = Join-Path $logDir "lock-repair-$stamp.json"
$repairErrLog = Join-Path $logDir "lock-repair-$stamp.err"
$postRepairLog = Join-Path $logDir "post-lock-repair-$stamp.json"
$postRepairErrLog = Join-Path $logDir "post-lock-repair-$stamp.err"
$refreshStatus = if ($StopAfter) {
    Join-Path $logDir "refresh-$stamp.json"
} else {
    Join-Path $backtestRoot "daily_refresh_status.json"
}
$refreshReport = if ($StopAfter) {
    Join-Path $logDir "refresh-$stamp.md"
} else {
    Join-Path $backtestRoot "daily_refresh_report.md"
}
$statusOut = Join-Path $logDir "last_run.json"

function Write-Status($state, $detail, $exit) {
    $payload = [ordered]@{
        state        = $state
        detail       = $detail
        exit_code    = $exit
        resume_from  = $ResumeFrom
        target_date  = $TargetDate
        refetch      = [bool]$Refetch
        stop_after   = $StopAfter
        started_at   = $script:startedAt
        finished_at  = (Get-Date).ToString("o")
        log          = $log
        error_log    = $errLog
        lock_repair  = $repairLog
        post_lock_repair = $postRepairLog
        refresh_status = $refreshStatus
        refresh_report = $refreshReport
        hard_stop_local = if ($script:hardStopLocal) { $script:hardStopLocal.ToString("o") } else { $null }
        child_exit_code = $script:childExitCode
        lock_release_verified = [bool]$script:lockReleaseVerified
        post_lock_cleanup_status = $script:postLockCleanupStatus
        post_lock_cleanup_detail = $script:postLockCleanupDetail
        workload_lease_mode = $script:workloadLeaseMode
        workload_lease_owner_pid = $script:workloadLeaseOwnerPid
    }
    Set-Content -Path $statusOut -Value ($payload | ConvertTo-Json -Depth 4) -Encoding utf8
}

$script:startedAt = (Get-Date).ToString("o")
$script:workloadLeaseMode = "none"
$script:workloadLeaseOwnerPid = $null
$script:hardStopLocal = $null
$script:childExitCode = $null
$script:lockReleaseVerified = $false
$script:postLockCleanupStatus = "NOT_RUN"
$script:postLockCleanupDetail = ""
$admissionScript = Join-Path $repo "scripts\ops\workload_admission.ps1"
$jobScript = Join-Path $repo "scripts\ops\windows_kill_on_close_job.ps1"
$tokenScript = Join-Path $repo "scripts\ops\training_window_contract.ps1"
foreach ($requiredScript in @($admissionScript, $jobScript, $tokenScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        Write-Status "ERROR" "required recovery helper not found at $requiredScript" 1
        exit 1
    }
}
. $admissionScript
. $jobScript
. $tokenScript
$policyWindow = Get-WeatherHeavyWorkloadPolicyWindow
if ($policyWindow -ne "agent_heavy") {
    $msg = "refusing ad-hoc chain recovery outside the repository 00:30-09:00 heavy-work window; Force cannot bypass host load policy"
    Write-Status "REFUSED" $msg 2
    Write-Host "REFUSED: $msg"
    exit 2
}
$script:hardStopLocal = (Get-Date).Date.AddHours(9)

$python = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Status "ERROR" "python not found at $python" 1; exit 1 }

function Test-ProcessIsSelfOrAncestor {
    param(
        [Parameter(Mandatory = $true)][int]$CandidatePid,
        [int]$MaximumDepth = 6
    )
    $nextPid = [int]$PID
    for ($depth = 0; $depth -le $MaximumDepth -and $nextPid -gt 0; $depth++) {
        if ($nextPid -eq $CandidatePid) { return $true }
        try {
            $rows = @(Get-CimInstance Win32_Process -Filter "ProcessId = $nextPid" -ErrorAction Stop)
        }
        catch { return $false }
        if ($rows.Count -ne 1) { return $false }
        $nextPid = [int]$rows[0].ParentProcessId
    }
    return $false
}

function Invoke-ContainedDailyRefreshPython {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$StandardOutputPath,
        [Parameter(Mandatory = $true)][string]$StandardErrorPath,
        [Parameter(Mandatory = $true)][datetime]$HardStopLocal
    )
    # The assigned Python process redirects itself before runpy enters the
    # module. It is created suspended, assigned to a KILL_ON_JOB_CLOSE Job,
    # and only then resumed; direct use therefore cannot orphan descendants.
    $launcher = "import runpy,sys;sys.stdout=open(sys.argv[1],'w',encoding='utf-8');sys.stderr=open(sys.argv[2],'w',encoding='utf-8');sys.argv=['weather.operations.daily_refresh']+sys.argv[3:];runpy.run_module('weather.operations.daily_refresh',run_name='__main__')"
    $tokens = @("-c", $launcher, $StandardOutputPath, $StandardErrorPath) + $Arguments
    $argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
    $job = $null
    $process = $null
    try {
        $job = New-WeatherKillOnCloseJob
        $process = Start-WeatherProcessInJob `
            -Job $job `
            -FilePath $python `
            -ArgumentString $argumentString `
            -WorkingDirectory $repo
        while ($true) {
            $process.Refresh()
            if ($process.HasExited) { break }
            $remainingMilliseconds = [math]::Floor(
                ($HardStopLocal - (Get-Date)).TotalMilliseconds
            )
            if ($remainingMilliseconds -le 0) {
                $job.Dispose()
                $job = $null
                $process.WaitForExit()
                return 75
            }
            $waitMilliseconds = [int][math]::Max(
                1,
                [math]::Min(250, $remainingMilliseconds)
            )
            [void]$process.WaitForExit($waitMilliseconds)
        }
        $process.WaitForExit()
        return [int]$process.ExitCode
    }
    finally {
        if ($job) { $job.Dispose() }
        if ($process) { $process.Dispose() }
    }
}

# Scheduled bounded wrappers already hold the same OS-backed lease. Accept that
# lease only when its recorded live owner is this process or a bounded ancestor;
# otherwise acquire our own handle. This makes direct recovery safe without
# deadlocking the reviewed outer wrapper topology.
$ownedWorkloadLease = $null
$leaseState = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $repo
if ($leaseState.Active) {
    $candidateOwnerPid = 0
    try { $candidateOwnerPid = [int]$leaseState.Owner.pid } catch { }
    $inherited = (
        $candidateOwnerPid -gt 0 -and
        (Test-ProcessIsSelfOrAncestor -CandidatePid $candidateOwnerPid)
    )
    if (-not $inherited) {
        $detail = "another heavyweight workload owns the shared lease; refusing chain recovery"
        Write-Status "REFUSED" $detail 3
        Write-Host "REFUSED: $detail"
        exit 3
    }
    $script:workloadLeaseMode = "inherited_ancestor"
    $script:workloadLeaseOwnerPid = $candidateOwnerPid
}
else {
    $ownedWorkloadLease = Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $repo `
        -Workload "chain_recovery_$TargetDate"
    if ($null -eq $ownedWorkloadLease) {
        $detail = "shared heavy-workload lease was acquired by another process during admission"
        Write-Status "REFUSED" $detail 3
        Write-Host "REFUSED: $detail"
        exit 3
    }
    $script:workloadLeaseMode = "owned"
    $script:workloadLeaseOwnerPid = $PID
}

# Repair only locks whose canonical diagnostics prove that their original
# owner is gone. This replaces file-existence inference, which refused stale
# locks and mistook a reused PID for the original owner. An active or unreadable
# owner remains a hard refusal; the subsequent run also acquires both locks
# atomically, so a race after this audit still fails closed.
try {
$repairArgs = @(
    "repair-stale-locks",
    "--backtest-root", $backtestRoot,
    "--snapshots-root", (Join-Path $repo "data\snapshots"),
    "--status-out", (Join-Path $backtestRoot "daily_refresh_status.json"),
    "--report-out", (Join-Path $backtestRoot "daily_refresh_report.md"),
    "--lock-path", (Join-Path $backtestRoot "daily_refresh.lock"),
    "--long-job-lock", (Join-Path $backtestRoot "long_job_guard.lock"),
    "--long-job-state", (Join-Path $backtestRoot "long_job_guard_status.json"),
    "--settled-analysis-target-date", $TargetDate,
    "--resume-from-step", $ResumeFrom
)
$repairExit = Invoke-ContainedDailyRefreshPython `
    -Arguments $repairArgs `
    -StandardOutputPath $repairLog `
    -StandardErrorPath $repairErrLog `
    -HardStopLocal $script:hardStopLocal
if ($repairExit -ne 0) {
    $detail = "canonical stale-lock repair failed with exit $repairExit; refusing recovery run"
    Write-Status "ERROR" $detail 1
    Write-Host "ERROR: $detail"
    exit 1
}
try {
    $repair = Get-Content -Raw -Path $repairLog | ConvertFrom-Json
}
catch {
    $detail = "canonical stale-lock repair did not emit readable JSON; refusing recovery run"
    Write-Status "ERROR" $detail 1
    Write-Host "ERROR: $detail"
    exit 1
}
$blockingLocks = @()
foreach ($row in @($repair.daily_refresh_lock, $repair.long_job_lock)) {
    if ($null -ne $row -and $row.exists -and -not $row.removed) {
        $blockingLocks += "$($row.kind):pid=$($row.pid):owner_running=$($row.owner_running):read_status=$($row.read_status)"
    }
}
if ($blockingLocks.Count -gt 0) {
    $detail = "canonical ownership check found a live or unverifiable lock: $($blockingLocks -join '; ')"
    Write-Status "REFUSED" $detail 3
    Write-Host "REFUSED: $detail"
    exit 3
}
if (
    $repair.long_job_state.active -and
    -not $repair.long_job_state.stale -and
    -not $repair.long_job_state.cleared
) {
    $detail = "canonical ownership check found a live or unverifiable long-job owner pid=$($repair.long_job_state.pid)"
    Write-Status "REFUSED" $detail 3
    Write-Host "REFUSED: $detail"
    exit 3
}

$chainArgs = @(
    "run",
    "--resume-from-step", $ResumeFrom,
    "--backtest-root", $backtestRoot,
    "--snapshots-root", (Join-Path $repo "data\snapshots"),
    "--status-out", $refreshStatus,
    "--report-out", $refreshReport,
    "--settled-analysis-target-date", $TargetDate
)
if ($Refetch) { $chainArgs += "--wu-settlement-restore-refetch" }
if ($StopAfter) { $chainArgs += @("--stop-after-step", $StopAfter) }

Write-Host "resuming chain from '$ResumeFrom' for $TargetDate$(if ($Refetch) { ' (refetch)' })"
Write-Host "log: $log"

# The contained launcher also keeps stdout/stderr away from PowerShell 5.1's
# NativeCommandError promotion while preserving a kill-on-close child tree.
$exit = Invoke-ContainedDailyRefreshPython `
    -Arguments $chainArgs `
    -StandardOutputPath $log `
    -StandardErrorPath $errLog `
    -HardStopLocal $script:hardStopLocal
$script:childExitCode = $exit

# After any normal child exit, re-run canonical ownership-aware cleanup while
# time remains. Preserve an original nonzero outcome, but require both lock
# paths absent before success. Exit 75 already means the Job was torn down at
# the absolute deadline, so cleanup is explicitly deferred to the next preflight.
if ($exit -ne 75 -and (Get-Date) -lt $script:hardStopLocal) {
    $postRepairArgs = @(
        "repair-stale-locks",
        "--backtest-root", $backtestRoot,
        "--snapshots-root", (Join-Path $repo "data\snapshots"),
        "--status-out", $refreshStatus,
        "--report-out", $refreshReport,
        "--lock-path", (Join-Path $backtestRoot "daily_refresh.lock"),
        "--long-job-lock", (Join-Path $backtestRoot "long_job_guard.lock"),
        "--long-job-state", (Join-Path $backtestRoot "long_job_guard_status.json"),
        "--settled-analysis-target-date", $TargetDate,
        "--resume-from-step", $ResumeFrom
    )
    $postRepairExit = Invoke-ContainedDailyRefreshPython `
        -Arguments $postRepairArgs `
        -StandardOutputPath $postRepairLog `
        -StandardErrorPath $postRepairErrLog `
        -HardStopLocal $script:hardStopLocal
    if ($postRepairExit -eq 0) {
        try {
            $postRepair = Get-Content -Raw -Path $postRepairLog | ConvertFrom-Json
        }
        catch { $postRepair = $null }
        if ($null -ne $postRepair) {
            $postLockBlockers = @(
                @($postRepair.daily_refresh_lock, $postRepair.long_job_lock) |
                    Where-Object { $_.exists -and -not $_.removed }
            )
            $dailyLockPath = Join-Path $backtestRoot "daily_refresh.lock"
            $longJobLockPath = Join-Path $backtestRoot "long_job_guard.lock"
            $postStateBlocked = (
                $postRepair.long_job_state.active -and
                -not $postRepair.long_job_state.stale -and
                -not $postRepair.long_job_state.cleared
            )
            $script:lockReleaseVerified = (
                $postLockBlockers.Count -eq 0 -and
                -not (Test-Path -LiteralPath $dailyLockPath) -and
                -not (Test-Path -LiteralPath $longJobLockPath) -and
                -not $postStateBlocked
            )
        }
    }
    if ($script:lockReleaseVerified) {
        $script:postLockCleanupStatus = "PASS"
        $script:postLockCleanupDetail = "canonical cleanup completed and both lock paths are absent"
    }
    elseif ($postRepairExit -eq 75) {
        $script:postLockCleanupStatus = "SKIPPED_HARD_DEADLINE"
        $script:postLockCleanupDetail = "09:00 hard stop reached during post-child cleanup"
        if ($exit -eq 0) { $exit = 75 }
    }
    else {
        $script:postLockCleanupStatus = "FAIL"
        $script:postLockCleanupDetail = "canonical cleanup or physical lock-absence verification failed"
        if ($exit -eq 0) { $exit = 1 }
    }
}
else {
    $script:postLockCleanupStatus = "SKIPPED_HARD_DEADLINE"
    $script:postLockCleanupDetail = "child reached, or returned after, the 09:00 hard stop"
    if ($exit -eq 0) { $exit = 75 }
}

if ($StopAfter -and $exit -eq 0) {
    try {
        $refresh = Get-Content -Raw -Path $refreshStatus | ConvertFrom-Json
        $bounded = $refresh.bounded_recovery
        $stepStatuses = @($bounded.step_statuses)
        $resumeRows = @($stepStatuses | Where-Object { $_.name -eq $ResumeFrom -and $_.status -eq 'ok' })
        $stopRows = @($stepStatuses | Where-Object { $_.name -eq $StopAfter -and $_.status -eq 'ok' })
        $boundedPass = (
            $refresh.terminal -eq $true -and
            $refresh.config.settled_analysis_target_date -eq $TargetDate -and
            $bounded.status -eq 'PASS' -and
            $bounded.resume_from_step -eq $ResumeFrom -and
            $bounded.stop_after_step -eq $StopAfter -and
            $bounded.terminal_step_status -eq 'ok' -and
            $resumeRows.Count -eq 1 -and
            $stopRows.Count -eq 1
        )
    }
    catch {
        $boundedPass = $false
    }
    if (-not $boundedPass) {
        $exit = 1
        Write-Status "ERROR" "bounded recovery receipt is missing or does not match the requested target/resume/stop contract" $exit
        Write-Host "ERROR: bounded recovery receipt validation failed"
        exit $exit
    }
}

if ($exit -eq 0) {
    $detail = if ($StopAfter) { "bounded chain completed through $StopAfter" } else { "chain resumed and completed" }
    Write-Status "OK" $detail $exit
    Write-Host "OK: $detail (exit 0)"
}
else {
    # Exit 2 is the standing pre-release gate result, not breakage: the readiness gate
    # correctly reports that no release pointer exists yet. Naming it here keeps the
    # morning read honest instead of alarming.
    $detail = if ($exit -eq 2 -and -not $StopAfter) { "chain ran; exit 2 = readiness gates BLOCK, expected pre-release" }
    elseif ($exit -eq 2) { "bounded chain exited 2; inspect the bounded refresh status because readiness was suppressed" }
    else { "chain exited $exit - read $log" }
    Write-Status "CHECK" $detail $exit
    Write-Host "CHECK: $detail"
}
}
finally {
    if ($null -ne $ownedWorkloadLease) {
        Exit-WeatherHeavyWorkloadLease -Lease $ownedWorkloadLease
    }
}
exit $exit
