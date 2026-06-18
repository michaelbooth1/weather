# Registers the daily paper market-making rollover launcher as a Windows
# Scheduled Task.
#
# The task is intentionally short-lived: it computes the local target date,
# starts a detached paper-live-forward market-making process with the default
# budget/settings, records the child PID, and exits. The launcher classifies
# evidence mode at start time, so delayed post-window runs are non-countable.
#
# Run from the repo root:  .\scripts\register_market_making_daily_roll.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMarketMakingDailyRoll",
    [string]$At = "19:30",
    [string]$Timezone = "America/Toronto",
    [string]$BudgetUsdc = "500",
    [string]$Mode = "paper-live-forward",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.market_making_daily_roll start --timezone $Timezone --budget-usdc $BudgetUsdc --mode $Mode --markets $Markets --interval-seconds $IntervalSeconds"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Starts the active-day paper-live-forward market-making run before the evidence cutoff (python -m weather.operations.market_making_daily_roll start)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At ($Timezone), $Mode, $BudgetUsdc USDC, markets=$Markets."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
