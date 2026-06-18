# Registers the daily settlement-to-promotion refresh as a Windows Scheduled Task.
#
# The task runs the full durable refresh chain:
# market_day_labels finalize -> promotion_refresh -> progress_audit ->
# disagreement_casebook -> fleet_observability.
#
# Run from the repo root:  .\scripts\register_daily_refresh.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherDailySettlementPromotionRefresh",
    [string]$At = "09:30",
    [switch]$ContinueOnError = $true
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.daily_refresh run"
if ($ContinueOnError) {
    $arguments = "$arguments --continue-on-error"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs the daily weather-market settlement/promotion/report refresh (python -m weather.operations.daily_refresh run)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
