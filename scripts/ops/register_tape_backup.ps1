# Registers the irreplaceable tape backup and restore-drill job as a Windows
# Scheduled Task.
#
# The task is intentionally all-in-one: export current tapes, run a restore
# drill, then write the backup status artifacts consumed by fleet observability.
#
# Run from the repo root:  .\scripts\ops\register_tape_backup.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherTapeBackupAndRestoreDrill",
    [string]$At = "02:15",
    [string]$BackupRoot = (Join-Path $RepoRoot "data\tape_backups"),
    [switch]$VerifyChecksums = $true
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.tape_backup run --backup-root `"$BackupRoot`""
if ($VerifyChecksums) {
    $arguments = "$arguments --verify-checksums"
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
    -Description "Exports irreplaceable weather-market tapes, runs a restore drill, and refreshes tape backup status." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At, backup root $BackupRoot."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
