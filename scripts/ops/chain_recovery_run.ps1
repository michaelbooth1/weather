<#
.SYNOPSIS
    Resume the daily refresh chain from a named step, outside the graded window.

.DESCRIPTION
    The chain hard-stops at the settled-day barrier when any dependency blocks, and
    everything after the barrier simply never runs. On 2026-07-27 a single transient WU
    timeout on one market stopped it at step 20 of 43, losing promotion_refresh,
    daily_learning and market_beating_objective_scoreboard for the day.

    Once the blocking condition is cleared, those steps are recoverable by resuming --
    but the resume is a multi-hour, memory-hungry run, and memory pressure during
    12:00-18:00 local is the top cause of capture gaps, which is what costs streak days.
    So this refuses to start inside the graded window rather than trusting the operator
    (or a scheduled trigger) to have picked a safe time.

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

.PARAMETER Force
    Run even inside the graded window. Only for a deliberate operator decision.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ResumeFrom,
    [Parameter(Mandatory = $true)][string]$TargetDate,
    [switch]$Refetch,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$logDir = Join-Path $repo "data\ops\chain_recovery"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "recovery-$stamp.log"
$errLog = Join-Path $logDir "recovery-$stamp.err"
$statusOut = Join-Path $logDir "last_run.json"

function Write-Status($state, $detail, $exit) {
    $payload = [ordered]@{
        state        = $state
        detail       = $detail
        exit_code    = $exit
        resume_from  = $ResumeFrom
        target_date  = $TargetDate
        refetch      = [bool]$Refetch
        started_at   = $script:startedAt
        finished_at  = (Get-Date).ToString("o")
        log          = $log
    }
    Set-Content -Path $statusOut -Value ($payload | ConvertTo-Json -Depth 4) -Encoding utf8
}

$script:startedAt = (Get-Date).ToString("o")
$hour = (Get-Date).Hour
if ($hour -ge 12 -and $hour -lt 18 -and -not $Force) {
    $msg = "refusing to start inside the graded window (12:00-18:00); a heavy chain here risks a capture gap and a streak day"
    Write-Status "REFUSED" $msg 0
    Write-Host "REFUSED: $msg"
    exit 0
}

$python = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Status "ERROR" "python not found at $python" 1; exit 1 }

$chainArgs = @(
    "-m", "weather.operations.daily_refresh", "run",
    "--resume-from-step", $ResumeFrom,
    "--backtest-root", (Join-Path $repo "data\backtest"),
    "--snapshots-root", (Join-Path $repo "data\snapshots"),
    "--settled-analysis-target-date", $TargetDate
)
if ($Refetch) { $chainArgs += "--wu-settlement-restore-refetch" }

Write-Host "resuming chain from '$ResumeFrom' for $TargetDate$(if ($Refetch) { ' (refetch)' })"
Write-Host "log: $log"

# Start-Process rather than a direct call: redirecting a native executable's stderr
# inside PowerShell 5.1 wraps each line in a NativeCommandError and trips
# $ErrorActionPreference='Stop' even on a clean exit 0 (this killed a merge mid-run
# on 2026-07-25). Separate redirected files avoid the wrapper entirely.
$proc = Start-Process -FilePath $python -ArgumentList $chainArgs -WorkingDirectory $repo `
    -NoNewWindow -PassThru -Wait -RedirectStandardOutput $log -RedirectStandardError $errLog
$exit = $proc.ExitCode

if ($exit -eq 0) {
    Write-Status "OK" "chain resumed and completed" $exit
    Write-Host "OK: chain completed (exit 0)"
}
else {
    # Exit 2 is the standing pre-release gate result, not breakage: the readiness gate
    # correctly reports that no release pointer exists yet. Naming it here keeps the
    # morning read honest instead of alarming.
    $detail = if ($exit -eq 2) { "chain ran; exit 2 = readiness gates BLOCK, expected pre-release" }
    else { "chain exited $exit - read $log" }
    Write-Status "CHECK" $detail $exit
    Write-Host "CHECK: $detail"
}
exit 0
