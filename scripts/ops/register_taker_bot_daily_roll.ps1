# Registers the daily paper taker-bot rollover launcher as a Windows
# Scheduled Task.
#
# The task is short-lived: it computes the local target date, starts a detached
# paper taker-bot loop for that date, records the child PID, and exits. Because
# the taker-bot run id includes the target date, each new local day gets a fresh
# run folder and budget.
#
# Run from the repo root:  .\scripts\ops\register_taker_bot_daily_roll.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherTakerBotDailyRoll",
    [string]$At = "00:05",
    [string]$Timezone = "America/Toronto",
    [string]$BudgetUsdc = "100",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [string[]]$Config = @()
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.taker_bot_daily_roll start --timezone $Timezone --budget-usdc $BudgetUsdc --markets $Markets --interval-seconds $IntervalSeconds"
foreach ($item in $Config) {
    $arguments += " --config $item"
}

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
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Starts the active-day paper taker-bot run with a fresh daily budget (python -m weather.operations.taker_bot_daily_roll start)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At ($Timezone), $BudgetUsdc USDC, markets=$Markets."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
