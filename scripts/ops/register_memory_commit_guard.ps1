# Registers the commit-charge watchdog as a Windows Scheduled Task.
#
# Run from the repo root:  .\scripts\ops\register_memory_commit_guard.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMemoryCommitGuard",
    [int]$IntervalMinutes = 5
)

$script = Join-Path $RepoRoot "scripts\ops\memory_commit_guard.ps1"
if (-not (Test-Path $script)) {
    throw "guard script not found at $script"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`"" `
    -WorkingDirectory $RepoRoot

# Single once trigger with indefinite repetition. The duration is blanked to
# "" after registration (the schema's "infinite"); a bounded duration would
# silently stop the guard when the window ended.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 1)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Warns below 1.5 GiB available physical RAM and at 85% commit; kills runaway ad-hoc python jobs (>8GB private) at 92% commit. Never touches -m weather.* processes." `
    -Force | Out-Null

# Make the repetition indefinite (empty duration = repeat forever).
$registered = Get-ScheduledTask -TaskName $TaskName
$registered.Triggers[0].Repetition.Duration = ""
$registered | Set-ScheduledTask | Out-Null

Write-Host "Registered scheduled task '$TaskName': every $IntervalMinutes minutes."
Write-Host "Log: data\logs\memory_commit_guard.log; status: data\logs\memory_commit_guard_status.json"
