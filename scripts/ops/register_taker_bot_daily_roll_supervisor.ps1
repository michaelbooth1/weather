# Registers the taker-bot daily-roll ensure supervisor as a Windows
# Scheduled Task.
#
# Layering: the existing WeatherTakerBotDailyRoll task still creates the daily
# run at 00:05 local time. This supervisor runs the short-lived `ensure`
# command every minute and at logon; it starts only after the configured local
# start time unless a same-day run already exists, then restarts dead, idle, or
# superseded-code loops through the launcher's bounded backoff/budget guard.
#
# Run from the repo root:  .\scripts\ops\register_taker_bot_daily_roll_supervisor.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherTakerBotDailyRollSupervisor",
    [int]$EnsureEveryMinutes = 1,
    [string]$Timezone = "America/Toronto",
    [string]$StartAfterLocalTime = "00:05",
    [string]$BudgetUsdc = "100",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [string[]]$Config = @()
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.taker_bot_daily_roll ensure --timezone $Timezone --start-after-local-time $StartAfterLocalTime --budget-usdc $BudgetUsdc --markets $Markets --interval-seconds $IntervalSeconds"
foreach ($item in $Config) {
    $arguments += " --config $item"
}

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

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "Keeps the active-day paper taker-bot daily-roll loop current and alive (python -m weather.operations.taker_bot_daily_roll ensure)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': taker daily-roll ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
