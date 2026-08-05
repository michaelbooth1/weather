# Registers the incremental model-versus-market skill tracker.
#
# This script only registers the task. It does not run the initial backfill.
# Complete the explicit backfill in the 00:30-09:00 quiet window first; the
# scheduled refresh fails closed when its checkpoint is absent.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherModelMarketSkillTracker",
    [string]$At = "13:00"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "venv pythonw not found at $python -- create the repository venv first."
}

$arguments = "-m weather.reporting.scorecards.model_market_skill_tracker refresh"
$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Incrementally appends promotion-countable model-versus-market skill revisions." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
