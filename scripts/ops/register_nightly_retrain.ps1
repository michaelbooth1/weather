# Registers the nightly retrain -> validate -> promote decision refresh.
#
# Run from the repo root:  .\scripts\register_nightly_retrain.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherNightlyRetrainValidatePromote",
    [string]$At = "03:30",
    [switch]$FailOnBlock = $false
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m src.nightly_retrain run"
if ($FailOnBlock) {
    $arguments = "$arguments --fail-on-block"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs nightly weather-market retraining, validation, and promotion decision refresh." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
