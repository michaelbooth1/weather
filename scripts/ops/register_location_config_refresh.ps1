# Registers the location event-metadata config refresh and target-date
# validation as a Windows Scheduled Task.
#
# Regenerates config/location_market_events.json from live Polymarket every ~6h so
# the collection loops always hold the current + upcoming daily-market events and
# CLOB token maps. A stale config is what caused the 2026-06-29 capture gap: the
# config had not been refreshed since 2026-06-27 and lacked the june-29 events, so
# the loops resolved 0 tokens and wrote nothing for the new market day.
#
# Run from the repo root:  .\scripts\ops\register_location_config_refresh.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherLocationConfigRefresh"
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
$script = Join-Path $RepoRoot "scripts\ops\refresh_location_config.ps1"
if (-not (Test-Path $script)) {
    throw "refresh script not found at $script"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`""

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

# Refresh four times daily (every 6h) so the generated config never approaches the
# 36h staleness threshold and newly-published market days are picked up within 6h
# regardless of when Polymarket publishes them.
$trigger = @(
    (New-ScheduledTaskTrigger -Daily -At "00:00"),
    (New-ScheduledTaskTrigger -Daily -At "06:00"),
    (New-ScheduledTaskTrigger -Daily -At "12:00"),
    (New-ScheduledTaskTrigger -Daily -At "18:00")
)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Register-ScheduledTask" -Phase "location-config refresh registration"
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Regenerates config/location_market_events.json from live Polymarket every 6h, then independently validates today's built-in markets against live Gamma before task success." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': every 6h (00:00/06:00/12:00/18:00 local)."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
