# Registers the market-making daily-roll ensure supervisor as a Windows
# Scheduled Task.
#
# Layering: the existing WeatherMarketMakingDailyRoll task still creates the
# daily paper-live-forward run at 19:30 local time. This supervisor runs the
# short-lived `ensure` command every minute and at logon; it starts only after
# the configured local start time unless a same-day run already exists, then
# restarts dead, idle, or superseded-code loops through the launcher's bounded
# backoff/budget guard.
#
# Run from the repo root:  .\scripts\ops\register_market_making_daily_roll_supervisor.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMarketMakingDailyRollSupervisor",
    [int]$EnsureEveryMinutes = 1,
    [string]$Timezone = "America/Toronto",
    [string]$StartAfterLocalTime = "19:30",
    [string]$BudgetUsdc = "500",
    [string]$Mode = "paper-live-forward",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.market_making_daily_roll ensure --timezone $Timezone --start-after-local-time $StartAfterLocalTime --budget-usdc $BudgetUsdc --mode $Mode --markets $Markets --interval-seconds $IntervalSeconds"

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
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Description "Keeps the paper-live-forward market-making daily-roll loop current and alive (python -m weather.operations.market_making_daily_roll ensure)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': market-making daily-roll ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
