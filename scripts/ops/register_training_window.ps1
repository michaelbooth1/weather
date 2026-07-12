# Registers the nightly single-host training window plus its dead-man restore.
#
# WeatherTrainingWindow        01:00 daily: stop capture -> nightly retrain -> restore
# WeatherTrainingWindowRestore 04:15 daily: unconditional idempotent capture restore
#
# Run from the repo root:  .\scripts\ops\register_training_window.ps1
# Re-running replaces the existing tasks.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$WindowTaskName = "WeatherTrainingWindow",
    [string]$RestoreTaskName = "WeatherTrainingWindowRestore",
    [string]$WindowAt = "01:00",
    [string]$RestoreAt = "04:15"
)

$script = Join-Path $RepoRoot "scripts\ops\training_window.ps1"
if (-not (Test-Path $script)) {
    throw "training window script not found at $script"
}

$windowAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`"" `
    -WorkingDirectory $RepoRoot

$windowTrigger = New-ScheduledTaskTrigger -Daily -At $WindowAt

# Time limit must exceed the 3h child cap plus stop/restore overhead so the
# scheduler never kills the process before its finally-block restores capture.
$windowSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3 -Minutes 45) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $WindowTaskName `
    -Action $windowAction `
    -Trigger $windowTrigger `
    -Settings $windowSettings `
    -Description "Single-host training window: stops capture loops, runs nightly retrain (3h cap), restores capture. Skips on unhealthy commit/disk." `
    -Force | Out-Null

$restoreAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`" -RestoreOnly" `
    -WorkingDirectory $RepoRoot

$restoreTrigger = New-ScheduledTaskTrigger -Daily -At $RestoreAt

$restoreSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $RestoreTaskName `
    -Action $restoreAction `
    -Trigger $restoreTrigger `
    -Settings $restoreSettings `
    -Description "Dead-man backstop: unconditionally re-enables capture supervisors and ensures all loops after the training window." `
    -Force | Out-Null

Write-Host "Registered '$WindowTaskName' daily at $WindowAt and '$RestoreTaskName' daily at $RestoreAt."
