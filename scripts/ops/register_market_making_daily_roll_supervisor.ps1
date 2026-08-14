# Registers the market-making daily-roll ensure supervisor as a Windows
# Scheduled Task.
#
# Layering: the existing WeatherMarketMakingDailyRoll task still creates the
# daily paper-live-forward run at 07:05 local time. This supervisor runs the
# short-lived `ensure` command every minute and at logon; it starts only after
# the configured local launch window. A healthy same-day run may continue after
# the window, but dead, idle, or superseded-code loops are not restarted after
# the evidence cutoff.
#
# Run from the repo root:  .\scripts\ops\register_market_making_daily_roll_supervisor.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMarketMakingDailyRollSupervisor",
    [int]$EnsureEveryMinutes = 1,
    [string]$Timezone = "America/Toronto",
    [string]$StartAfterLocalTime = "07:05",
    [string]$StartNoLaterThanLocalTime = "20:00",
    [string]$BudgetUsdc = "500",
    [string]$Mode = "paper-live-forward",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [double]$QuoteSize = 20.0,
    [double]$MaxBandNotional = 25.0,
    [double]$MaxEventNotional = 25.0
)

$wrapper = Join-Path $RepoRoot "scripts\ops\market_making_daily_roll_task.ps1"
if (-not (Test-Path $wrapper)) {
    throw "daily-roll task wrapper not found at $wrapper"
}

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`" -Verb ensure -RepoRoot `"$RepoRoot`" -Timezone $Timezone -StartAfterLocalTime $StartAfterLocalTime -StartNoLaterThanLocalTime $StartNoLaterThanLocalTime -BudgetUsdc $BudgetUsdc -Mode $Mode -Markets $Markets -IntervalSeconds $IntervalSeconds -QuoteSize $QuoteSize -MaxBandNotional $MaxBandNotional -MaxEventNotional $MaxEventNotional"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
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
    -Description "Keeps the paper-live-forward market-making daily-roll loop current during its configured evidence launch window (python -m weather.operations.market_making_daily_roll ensure)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': market-making daily-roll ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
