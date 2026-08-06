# Registers the standalone CLOB order-book tiering job as a Windows Scheduled Task.
#
# Compresses each settled market-day's `order_books_long.csv` to `.csv.gz` (~23x)
# and deletes the verified source. This is also step ~13 of the daily refresh
# chain; running it here as well is deliberate redundancy, not duplication. The
# job is idempotent -- a market-day already tiered is classified `already_tiered`
# and skipped -- so whichever runs first simply leaves nothing for the other.
#
# The chain has now failed to reach step 13 twice, for two unrelated reasons
# (memory admission 2026-07-18, a single transient capture error 2026-08-04).
# Each time raw tapes accumulated at ~18.7 GB/day until free space threatened
# capture. Disk headroom must not be a downstream consequence of chain health.
# See scripts/ops/clob_tiering_run.ps1 for the full rationale.
#
# 05:00 local is chosen because it is inside the 00:30-09:00 heavy-work window,
# after the 01:00 training window and 04:30 mirror have finished, and well clear
# of the 12:00-18:00 graded capture window. The runner refuses that window
# anyway.
#
# Run from the repo root:  .\scripts\ops\register_clob_tiering.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherClobTiering",
    [string]$At = "05:00"
)

$script = Join-Path $RepoRoot "scripts\ops\clob_tiering_run.ps1"
if (-not (Test-Path $script)) {
    throw "tiering runner not found at $script"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`""

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

# StartWhenAvailable matters here: a missed run means a full day of raw tapes
# retained, so catching up late is strictly better than skipping.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 90) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# S4U so the job survives an unattended reboot with no interactive logon, and so
# it does not depend on a console session -- matching the capture fleet.
#
# Bare username, matching how the capture supervisors are registered. Do NOT
# qualify it with $env:USERDOMAIN: on this host that is "WORKGROUP", not the
# machine name, and Register-ScheduledTask fails with "No mapping between
# account names and security IDs was done."
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
    -Description "Compresses settled CLOB order_books_long.csv to .csv.gz and deletes verified sources, independently of the daily refresh chain. Prevents the ~18.7 GB/day retention leak seen when the chain defers before its own tiering step (2026-07-18, 2026-08-04)." `
    -Force | Out-Null

# Register-ScheduledTask surfaces some failures as non-terminating CIM errors,
# so the success message below would otherwise print after a failed
# registration. Prove the task exists before claiming it does.
$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $registered) {
    throw "registration did not take effect -- '$TaskName' does not exist after Register-ScheduledTask"
}

Write-Host "Registered scheduled task '$TaskName': daily at $At local."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Task-level status: data\logs\clob_tiering_task_status.json"
