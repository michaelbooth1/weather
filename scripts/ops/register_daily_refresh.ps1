# Registers the split daily settlement/evidence refresh as Windows Scheduled Tasks.
#
# Stage A runs settlement truth through fleet observability at 09:30.
# Stage B runs evidence recomputation and learning when Stage A triggers it,
# with 14:00 and 17:00 fallback triggers guarded by the Stage-A manifest.
#
# Run from the repo root:  .\scripts\ops\register_daily_refresh.ps1
# Re-running replaces the existing tasks.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherDailySettlementPromotionRefresh",
    [string]$EvidenceTaskName = "WeatherEveningEvidenceRefresh",
    [string]$At = "09:30",
    [string[]]$EvidenceAt = @("14:00", "17:00"),
    [switch]$ContinueOnError = $true
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$baseArguments = "-m weather.operations.daily_refresh run --fail-on-variant-evidence-alert"
if ($ContinueOnError) {
    $baseArguments = "$baseArguments --continue-on-error"
}

$stageAArguments = "$baseArguments --stage settlement --evidence-task-name `"$EvidenceTaskName`""
$stageBArguments = "$baseArguments --stage evidence --status-out data\backtest\daily_refresh_evidence_status.json --report-out data\backtest\daily_refresh_evidence_report.md"

$stageAAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $stageAArguments `
    -WorkingDirectory $RepoRoot

$stageATrigger = New-ScheduledTaskTrigger -Daily -At $At

$stageASettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $stageAAction `
    -Trigger $stageATrigger `
    -Settings $stageASettings `
    -Description "Runs daily weather-market settlement truth through fleet observability (daily_refresh --stage settlement)." `
    -Force | Out-Null

$stageBAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $stageBArguments `
    -WorkingDirectory $RepoRoot

$stageBTriggers = @()
foreach ($time in $EvidenceAt) {
    $stageBTriggers += New-ScheduledTaskTrigger -Daily -At $time
}

$stageBSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $EvidenceTaskName `
    -Action $stageBAction `
    -Trigger $stageBTriggers `
    -Settings $stageBSettings `
    -Description "Runs daily weather-market evidence recomputation and learning when the Stage-A manifest is fresh (daily_refresh --stage evidence)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': settlement stage daily at $At."
Write-Host "Registered scheduled task '$EvidenceTaskName': evidence stage fallback at $($EvidenceAt -join ', ')."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Verify evidence with: Get-ScheduledTask -TaskName $EvidenceTaskName | Get-ScheduledTaskInfo"
