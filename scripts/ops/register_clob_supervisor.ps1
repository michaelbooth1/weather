# Registers the fast Polymarket CLOB book-loop supervisor as a Windows
# Scheduled Task (ROADMAP item 37: always-on market microstructure capture).
#
# Layering: Task Scheduler runs the short-lived `market_microstructure ensure`
# check every minute and at logon. `ensure` keeps exactly one detached CLOB
# loop alive across silent deaths, stale-heartbeat hangs, and reboots. The loop
# itself captures books every 30-60 seconds, switching to the configured fast
# cadence near close or after large top-of-book midpoint moves.
#
# Run from the repo root:  .\scripts\register_clob_supervisor.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "WeatherClobBookLoopSupervisor",
    [int]$EnsureEveryMinutes = 1,
    [string]$Market = "all",
    [int]$IntervalSeconds = 60,
    [int]$FastIntervalSeconds = 15
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m src.market_microstructure ensure --market $Market --interval-seconds $IntervalSeconds --fast-interval-seconds $FastIntervalSeconds"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EnsureEveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Description "Keeps the Polymarket CLOB book capture loop alive (python -m src.market_microstructure ensure). Registered by scripts/register_clob_supervisor.ps1." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': CLOB --ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
