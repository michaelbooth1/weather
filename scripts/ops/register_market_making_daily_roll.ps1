# Registers the daily paper market-making rollover launcher as a Windows
# Scheduled Task.
#
# The task is intentionally short-lived: it computes the local target date,
# starts a detached paper-live-forward market-making process with the default
# budget/settings, records the child PID, and exits. The launcher classifies
# evidence mode at start time, so delayed post-window runs are non-countable.
#
# Run from the repo root:  .\scripts\ops\register_market_making_daily_roll.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMarketMakingDailyRoll",
    [string]$At = "07:05",
    [string]$Timezone = "America/Toronto",
    [string]$BudgetUsdc = "500",
    [string]$Mode = "paper-live-forward",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [double]$QuoteSize = 20.0,
    [double]$MaxBandNotional = 25.0,
    [double]$MaxEventNotional = 25.0,
    [switch]$EnableMarketHarvestCompanion
)

$wrapper = Join-Path $RepoRoot "scripts\ops\market_making_daily_roll_task.ps1"
if (-not (Test-Path $wrapper)) {
    throw "daily-roll task wrapper not found at $wrapper"
}

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`" -Verb start -RepoRoot `"$RepoRoot`" -Timezone $Timezone -BudgetUsdc $BudgetUsdc -Mode $Mode -Markets $Markets -IntervalSeconds $IntervalSeconds -QuoteSize $QuoteSize -MaxBandNotional $MaxBandNotional -MaxEventNotional $MaxEventNotional"
if ($EnableMarketHarvestCompanion) {
    $arguments += " -EnableMarketHarvestCompanion"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Starts the active-day paper-live-forward market-making run before the evidence cutoff (python -m weather.operations.market_making_daily_roll start)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At ($Timezone), $Mode, $BudgetUsdc USDC, markets=$Markets."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
