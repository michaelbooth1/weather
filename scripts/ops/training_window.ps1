# Single-host training window: stop capture, run nightly retrain, restore capture.
#
# The capture-resource admission gate (correctly) refuses heavy work while the
# snapshot/CLOB/observation-trigger loops are active, and this dedicated host
# captures 24/7 — so on one machine the learning loop can only run inside a
# deliberate, bounded window where capture is stopped and then guaranteed to
# come back. Slot: 01:00 local, hard child cap 3h, so capture is restored
# before the 03:00-05:00 predawn frontier on warm-cache nights and by ~04:05
# worst-case. A separate dead-man task (register script) re-enables capture at
# 04:15 unconditionally in case this process dies mid-window.
#
# Every day that uses a window has a deliberate capture gap and is therefore
# NOT a clean day for item-321 Phase 2 proofs. That is honest and intended:
# clean-day streaks are collected on nights where the window skips or after
# the learning loop earns a second host.
#
# Modes:
#   (default)     full window: preflight -> stop -> retrain -> restore
#   -RestoreOnly  idempotent capture restore (used by the dead-man task)
#   -DryRun       preflight + plan only; never touches capture

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [double]$MaxCommitPercent = 70.0,
    [long]$MinFreeDiskBytes = 60GB,
    [double]$CaptureStopTimeoutSeconds = 90.0,
    [double]$ChildTimeoutMinutes = 180.0,
    [switch]$RestoreOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$logDir = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logPath = Join-Path $logDir "training_window.log"
$statusPath = Join-Path $logDir "training_window_status.json"

$supervisorTasks = @(
    "WeatherSnapshotLoopSupervisor",
    "WeatherClobBookLoopSupervisor",
    "WeatherObservationTriggerSupervisor"
)

function Write-WindowLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

function Write-WindowStatus([string]$Phase, [string]$Outcome) {
    @{
        updated_at = (Get-Date -Format "o")
        phase = $Phase
        outcome = $Outcome
    } | ConvertTo-Json | Out-File -FilePath $statusPath -Encoding utf8
}

function Restore-Capture {
    # Idempotent: enabling an enabled task and ensuring a healthy loop are no-ops.
    foreach ($task in $supervisorTasks) {
        schtasks /change /tn $task /enable | Out-Null
        Write-WindowLog "RESTORE" "enabled $task"
    }
    & $python -m weather.collection.snapshot_tracker --ensure | Out-Null
    & $python -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15 | Out-Null
    & $python -m weather.operations.observation_trigger ensure --market all --interval-seconds 60 --stale-after-seconds 180 | Out-Null
    Write-WindowLog "RESTORE" "ensure verbs issued for all three loops"
}

function Wait-CaptureStopped([double]$TimeoutSeconds) {
    # Reuse the canonical read-only gate instead of trusting process names or
    # stale status PIDs. In no-live-capture mode it passes only after all three
    # workers are actually inactive.
    $deadline = [datetime]::UtcNow.AddSeconds([math]::Max(1.0, $TimeoutSeconds))
    do {
        & $python -m weather.operations.capture_resource_gate `
            --workload training_window_stop_confirmation `
            --capture-mode no_live_capture `
            --min-free-memory-bytes 0 `
            --min-free-disk-bytes 0 `
            --no-write `
            --fail-on-block | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 2
    } while ([datetime]::UtcNow -lt $deadline)
    return $false
}

Set-Location $RepoRoot

if ($RestoreOnly) {
    Write-WindowLog "INFO" "restore-only invocation (dead-man or manual)"
    Restore-Capture
    Write-WindowStatus "restore_only" "capture_restored"
    exit 0
}

# ---- Preflight: never start a window on an unhealthy host ----
$os = Get-CimInstance Win32_OperatingSystem
$commitPercent = 100.0 * ($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / $os.TotalVirtualMemorySize
$freeDisk = (Get-PSDrive C).Free
$skipReasons = @()
if ($commitPercent -gt $MaxCommitPercent) { $skipReasons += "commit at $([math]::Round($commitPercent,1))% > $MaxCommitPercent%" }
if ($freeDisk -lt $MinFreeDiskBytes) { $skipReasons += "free disk $([math]::Round($freeDisk/1GB,1))GB < $([math]::Round($MinFreeDiskBytes/1GB,0))GB" }

if ($skipReasons.Count -gt 0) {
    Write-WindowLog "SKIP" ("window skipped: " + ($skipReasons -join "; ") + " (capture untouched)")
    Write-WindowStatus "preflight" ("skipped: " + ($skipReasons -join "; "))
    exit 0
}

if ($DryRun) {
    Write-WindowLog "INFO" "dry-run: preflight PASS (commit $([math]::Round($commitPercent,1))%, disk $([math]::Round($freeDisk/1GB,1))GB free); would stop and verify capture inactive (cap ${CaptureStopTimeoutSeconds}s), run retrain in no-live-capture mode (cap ${ChildTimeoutMinutes}m), restore"
    Write-WindowStatus "dry_run" "preflight_pass"
    exit 0
}

Write-WindowLog "INFO" "window opening: commit $([math]::Round($commitPercent,1))%, disk $([math]::Round($freeDisk/1GB,1))GB free"
Write-WindowStatus "opening" "in_progress"

$childExit = -1
$nightlyStatus = "not_run"
$nightlyAdmission = "not_run"
try {
    # ---- Stop capture cleanly: supervisors first so nothing revives mid-window ----
    foreach ($task in $supervisorTasks) {
        schtasks /change /tn $task /disable | Out-Null
        Write-WindowLog "STOP" "disabled $task"
    }
    & $python -m weather.collection.snapshot_tracker --stop | Out-Null
    & $python -m weather.market.market_microstructure stop | Out-Null
    & $python -m weather.operations.observation_trigger stop | Out-Null
    Write-WindowLog "STOP" "stop verbs issued for all three loops"
    if (-not (Wait-CaptureStopped $CaptureStopTimeoutSeconds)) {
        $childExit = 9001
        Write-WindowLog "ERROR" "capture did not become fully inactive within ${CaptureStopTimeoutSeconds}s; retrain not started"
        throw "capture stop verification timed out"
    }
    Write-WindowLog "STOP" "canonical gate confirms all three capture loops inactive"

    # ---- Run the retrain child under a hard timeout ----
    Write-WindowStatus "retrain" "running"
    Write-WindowLog "RETRAIN" "starting nightly_retrain (cap ${ChildTimeoutMinutes}m)"
    $childArgs = @(
        "-m", "weather.operations.nightly_retrain", "run",
        "--fail-on-daily-learning-blocker",
        "--capture-resource-mode", "no_live_capture",
        "--capture-resource-min-free-memory-bytes", "0"
    )
    $child = Start-Process -FilePath $python `
        -ArgumentList $childArgs `
        -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden
    $completed = $child.WaitForExit([int]($ChildTimeoutMinutes * 60 * 1000))
    if (-not $completed) {
        Write-WindowLog "RETRAIN" "cap reached; killing child tree pid $($child.Id)"
        taskkill /PID $child.Id /T /F | Out-Null
        $childExit = 9999
    } else {
        $childExit = $child.ExitCode
        Write-WindowLog "RETRAIN" "nightly_retrain exited $childExit"
    }
    $nightlyStatusPath = Join-Path $RepoRoot "data\backtest\nightly_retrain_status.json"
    if (Test-Path $nightlyStatusPath) {
        try {
            $nightlyPayload = Get-Content $nightlyStatusPath -Raw | ConvertFrom-Json
            $nightlyStatus = [string]$nightlyPayload.status
            $nightlyAdmission = [string]$nightlyPayload.capture_resource_admission.decision
        } catch {
            $nightlyStatus = "unreadable"
        }
    } else {
        $nightlyStatus = "missing"
    }
    Write-WindowLog "RETRAIN" "nightly status $nightlyStatus; capture admission $nightlyAdmission; child exit $childExit"
    if ($childExit -eq 0 -and $nightlyStatus -in @("blocked", "error", "missing", "unreadable")) {
        $childExit = 2
        Write-WindowLog "RETRAIN" "promoting non-success nightly status to window exit $childExit"
    }
} finally {
    # ---- Restore capture no matter what happened above ----
    Write-WindowStatus "restore" "in_progress"
    Restore-Capture
    Write-WindowStatus "closed" "nightly_${nightlyStatus}_admission_${nightlyAdmission}_exit_$childExit"
    Write-WindowLog "INFO" "window closed (nightly $nightlyStatus, admission $nightlyAdmission, exit $childExit); capture restore issued"
}
exit $childExit
