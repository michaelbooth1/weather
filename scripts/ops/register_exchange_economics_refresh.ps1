# Registers the International exchange-economics snapshot refresh as a Windows Scheduled Task.
#
# The task fetches a content-bound snapshot from official Gamma/CLOB APIs before
# the daily settlement/report refresh. It does not accept the baseline.
#
# 06:50 local matches the live host registration (Swarm P audit F1, 2026-10-07):
# after the 04:45-06:45 tiering reservation, before the 09:30 Stage-A chain, and
# outside the 12:00-18:00 graded window. The trigger is local wall-clock time
# (no fixed UTC offset), so it stays at 06:50 across DST (DST-C1).
#
# The action runs the refresh helper with -File (never -Command) under the
# current-user S4U / Limited principal. The helper writes
# data\logs\exchange_economics_refresh_status.json on every run, so a nonzero
# task result is diagnosable from that file.
#
# Run from the repo root:  .\scripts\ops\register_exchange_economics_refresh.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = "",
    [string]$TaskName = "WeatherExchangeEconomicsSnapshotRefresh",
    [ValidateSet("06:50")][string]$At = "06:50"
)

$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults
# under `powershell -File`; derive the default here. An explicit -RepoRoot wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
. (Join-Path $PSScriptRoot "scheduled_task_local_trigger.ps1")

$script = Join-Path $RepoRoot "scripts\ops\refresh_exchange_economics_snapshot.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "refresh script not found at $script"
}
$script = (Resolve-Path -LiteralPath $script).Path
$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`""

$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-WeatherLocalDailyTrigger -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
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
    -Description "Fetches current International Polymarket per-condition exchange economics from official APIs; status in data\logs\exchange_economics_refresh_status.json." `
    -Force | Out-Null

# Read back the load-bearing contract before claiming success.
$registered = @(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
if ($registered.Count -ne 1) {
    throw "registration readback expected one '$TaskName' task, found $($registered.Count)"
}
$registeredActions = @($registered[0].Actions)
$registeredTriggers = @($registered[0].Triggers)
if ($registeredActions.Count -ne 1 -or
    [string]$registeredActions[0].Execute -ine $powerShell -or
    [string]$registeredActions[0].Arguments -cne $arguments -or
    [string]$registeredActions[0].WorkingDirectory -ine $RepoRoot -or
    $registeredTriggers.Count -ne 1 -or
    [int]$registeredTriggers[0].DaysInterval -ne 1 -or
    -not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$registeredTriggers[0].StartBoundary) -At $At) -or
    [string]$registered[0].Principal.LogonType -ne "S4U" -or
    [string]$registered[0].Principal.RunLevel -ne "Limited" -or
    [string]$registered[0].Settings.ExecutionTimeLimit -ne "PT5M" -or
    [string]$registered[0].Settings.MultipleInstances -ne "IgnoreNew") {
    throw "registration readback does not match the 06:50 local, -File, S4U/Limited economics contract"
}

Write-Host "Registered scheduled task '$TaskName': daily at $At local wall-clock time."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Run status: data\logs\exchange_economics_refresh_status.json"
