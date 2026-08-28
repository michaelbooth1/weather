# Registers the commit-charge watchdog as a Windows Scheduled Task.
#
# Run from the repo root:  .\scripts\ops\register_memory_commit_guard.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMemoryCommitGuard",
    [int]$IntervalMinutes = 1
)

$script = Join-Path $RepoRoot "scripts\ops\memory_commit_guard.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "guard script not found at $script"
}
$hostIdentityScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
if (-not (Test-Path -LiteralPath $hostIdentityScript -PathType Leaf)) {
    throw "capture-host identity helper is missing: $hostIdentityScript"
}
. $hostIdentityScript
$registrarExecutionHostId = Get-WeatherExecutionHostId
$registrarAssignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
if (
    $registrarExecutionHostId -cne
        [string]$registrarAssignment.dedicated_capture_execution_host_id
) {
    throw "memory commit guard may be registered only on the tracked dedicated capture host"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`" -ExpectedExecutionHostId $registrarExecutionHostId" `
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

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Every minute, blocks concurrent/out-of-window Codex heavy tool trees; warns below 1.5 GiB RAM or at 85% commit; terminates eligible >8 GiB jobs at 92%." `
    -Force | Out-Null

# Make the repetition indefinite (empty duration = repeat forever).
$registered = Get-ScheduledTask -TaskName $TaskName
$registered.Triggers[0].Repetition.Duration = ""
$registered | Set-ScheduledTask | Out-Null

Write-Host "Registered scheduled task '$TaskName': every $IntervalMinutes minutes."
Write-Host "Log: data\logs\memory_commit_guard.log; status: data\logs\memory_commit_guard_status.json"
