# Registers the snapshot-loop supervisor as a Windows Scheduled Task
# (ROADMAP item 16: documented OS supervisor for always-on capture).
#
# Layering: Task Scheduler runs the short-lived `--ensure` check every
# 10 minutes (and at logon); `--ensure` keeps exactly one healthy detached
# loop alive across silent deaths, hangs (stale heartbeat with a live PID),
# and reboots. To deploy new code, run `snapshot_tracker --restart` or
# `--stop` (the next ensure tick restarts it fresh). To stop collection on
# purpose, disable this task AND run `--stop` (the pause flag keeps the
# process alive; disabling only the task leaves the loop running).
#
# Run from the repo root:  .\scripts\register_snapshot_supervisor.ps1
# The task runs as the current user, only while logged on (no credentials
# stored). Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "WeatherSnapshotLoopSupervisor",
    [int]$EnsureEveryMinutes = 10
)

# pythonw.exe: the windowless interpreter. With python.exe an interactive
# scheduled task flashes a console window on every 10-minute ensure tick.
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m src.snapshot_tracker --ensure" `
    -WorkingDirectory $RepoRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EnsureEveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Description "Keeps the weather snapshot capture loop alive (python -m src.snapshot_tracker --ensure). Registered by scripts/register_snapshot_supervisor.ps1." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': --ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
