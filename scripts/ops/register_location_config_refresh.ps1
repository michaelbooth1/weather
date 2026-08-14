# Registers the location event-metadata config refresh as a Windows Scheduled Task.
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

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Regenerates config/location_market_events.json from live Polymarket every 6h so collection loops hold current+upcoming market events and CLOB tokens (prevents the stale-config capture gap seen 2026-06-29)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': every 6h (00:00/06:00/12:00/18:00 local)."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
