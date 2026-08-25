# Registers the commit-charge watchdog as a Windows Scheduled Task.
#
# Run from the repo root:  .\scripts\ops\register_memory_commit_guard.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMemoryCommitGuard",
    [int]$IntervalMinutes = 1
)

$schedulerBoundaryScript = Join-Path $PSScriptRoot "integration_attempt_remote_git.ps1"
if (-not (Test-Path -LiteralPath $schedulerBoundaryScript -PathType Leaf)) {
    throw "Scheduler mutation boundary helper is missing: $schedulerBoundaryScript"
}
$schedulerBoundaryPreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Stop"
    Remove-Item `
        -LiteralPath Function:\Assert-WeatherIntegrationSchedulerMutationAllowed `
        -Force -ErrorAction SilentlyContinue
    . $schedulerBoundaryScript
    $schedulerBoundaryCommand = Get-Command `
        Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandType Function -ErrorAction Stop
}
catch {
    throw "Scheduler mutation boundary helper could not be loaded from its canonical file."
}
finally {
    $ErrorActionPreference = $schedulerBoundaryPreviousErrorActionPreference
}
if ([string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ScriptBlock.File) -or
    -not [IO.Path]::GetFullPath(
        [string]$schedulerBoundaryCommand.ScriptBlock.File
    ).Equals(
        [IO.Path]::GetFullPath($schedulerBoundaryScript),
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ModuleName) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.Source)) {
    throw "Scheduler mutation boundary helper did not load from its canonical file."
}
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

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Register-ScheduledTask" -Phase "memory-commit guard registration"
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
Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Set-ScheduledTask" -Phase "memory-commit guard repetition update"
$registered | Set-ScheduledTask | Out-Null

Write-Host "Registered scheduled task '$TaskName': every $IntervalMinutes minutes."
Write-Host "Log: data\logs\memory_commit_guard.log; status: data\logs\memory_commit_guard_status.json"
