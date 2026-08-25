# Registers the fast observation-triggered recompute supervisor as a Windows
# Scheduled Task.
#
# Task Scheduler runs the short-lived `observation_trigger ensure` check every
# minute and at logon. `ensure` keeps exactly one detached watcher alive. The
# watcher polls low-cost observation sources and forces tagged recomputes when
# settlement-relevant source state changes.
#
# Run from the repo root:  .\scripts\ops\register_observation_trigger_supervisor.ps1
# The S4U principal runs without an interactive logon. Re-running replaces the
# existing task and must preserve unattended reboot recovery.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherObservationTriggerSupervisor",
    [int]$EnsureEveryMinutes = 1,
    [string]$Market = "all",
    [int]$IntervalSeconds = 60,
    [int]$StaleAfterSeconds = 180
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
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.observation_trigger ensure --market $Market --interval-seconds $IntervalSeconds --stale-after-seconds $StaleAfterSeconds"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EnsureEveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Register-ScheduledTask" -Phase "observation-trigger supervisor registration"
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "Keeps the observation-triggered recompute watcher alive (python -m weather.operations.observation_trigger ensure)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': observation trigger --ensure every $EnsureEveryMinutes min + at logon."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
