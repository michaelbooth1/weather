# Registers periodic model-market disagreement audit analysis as a Windows Scheduled Task.
#
# The task reads data/backtest/model_market_disagreement_audit.jsonl and writes:
#   data/backtest/model_market_disagreement_analysis.json
#   data/backtest/model_market_disagreement_analysis.md
#
# Run from the repo root:
#   .\scripts\ops\register_model_market_disagreement_analysis.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherModelMarketDisagreementAnalysis",
    [int]$EveryMinutes = 30
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m weather.reporting.candidate_lifecycle.model_market_disagreement_analysis" `
    -WorkingDirectory $RepoRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Description "Periodically analyzes saved weather model-market disagreement audit snapshots." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': every $EveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
