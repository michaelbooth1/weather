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
    [ValidateSet("05:00")][string]$At = "05:00"
)

$ErrorActionPreference = "Stop"
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
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$script = Join-Path $RepoRoot "scripts\ops\clob_tiering_run.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "tiering runner not found at $script"
}
$script = (Resolve-Path -LiteralPath $script).Path
$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
if (-not (Test-Path -LiteralPath $contractScript -PathType Leaf)) {
    throw "argument contract not found at $contractScript"
}
. $contractScript
$powerShell = [string](
    Get-Command powershell.exe -CommandType Application -ErrorAction Stop
).Source
$maxRuntimeSeconds = 1800
$executionTimeLimit = "PT31M"
$actionTokens = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", $script,
    "-RepoRoot", $RepoRoot,
    "-MaxRuntimeSeconds", ([string]$maxRuntimeSeconds)
)
$arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $actionTokens

$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

# Catch-up is deliberately disabled. A missed 05:00 run must remain visible;
# starting it later can overlap the 09:30 Stage-A chain or a protected window.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 31) `
    -WakeToRun `
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

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Register-ScheduledTask" -Phase "CLOB tiering registration"
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Compresses settled CLOB order_books_long.csv to .csv.gz and deletes verified sources, independently of the daily refresh chain. Prevents the ~18.7 GB/day retention leak seen when the chain defers before its own tiering step (2026-07-18, 2026-08-04)." `
    -Force | Out-Null

# Read back the complete load-bearing task contract before claiming success.
$matches = @(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
if ($matches.Count -ne 1) {
    throw "registration readback expected one '$TaskName' task, found $($matches.Count)"
}
$registered = $matches[0]
$registeredActions = @($registered.Actions)
$registeredTriggers = @($registered.Triggers)
$registeredTime = $null
try { $registeredTime = ([datetime]$registeredTriggers[0].StartBoundary).ToString("HH:mm") }
catch { }
if ([string]$registered.TaskPath -ne "\" -or
    [string]$registered.State -eq "Disabled" -or
    $registeredActions.Count -ne 1 -or
    [string]$registeredActions[0].Execute -ine $powerShell -or
    [string]$registeredActions[0].Arguments -cne $arguments -or
    [string]$registeredActions[0].WorkingDirectory -ine $RepoRoot -or
    $registeredTriggers.Count -ne 1 -or
    [string]$registeredTriggers[0].CimClass.CimClassName -ne "MSFT_TaskDailyTrigger" -or
    [int]$registeredTriggers[0].DaysInterval -ne 1 -or
    -not [bool]$registeredTriggers[0].Enabled -or
    -not [string]::IsNullOrWhiteSpace([string]$registeredTriggers[0].Repetition.Interval) -or
    $registeredTime -ne $At -or
    [string]$registered.Settings.ExecutionTimeLimit -ne $executionTimeLimit -or
    [bool]$registered.Settings.StartWhenAvailable -or
    -not [bool]$registered.Settings.WakeToRun -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    -not [bool]$registered.Settings.Hidden -or
    [bool]$registered.Settings.DisallowStartIfOnBatteries -or
    [bool]$registered.Settings.StopIfGoingOnBatteries -or
    [string]$registered.Principal.UserId -ine $env:USERNAME -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited") {
    throw "registration readback does not match the exact bounded 05:00 tiering contract"
}

Write-Host "Registered scheduled task '$TaskName': daily at $At local, max ${maxRuntimeSeconds}s, task limit $executionTimeLimit, no late catch-up."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Task-level status: data\logs\clob_tiering_task_status.json"
