# Registers the bounded raw CLOB tape tiering job as a Windows Scheduled Task.
#
# The canonical runner owns the shared heavy-work lease and a kill-on-close Job.
# This registrar fixes the task to 06:00, a 2400-second child-tree bound, a
# 150-item batch, and a PT41M scheduler limit. StartWhenAvailable is deliberately
# false so a missed run cannot drift into Stage A or a protected host window.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherClobRawTapeTiering",
    [ValidateSet("06:00")][string]$At = "06:00"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$script = Join-Path $RepoRoot "scripts\ops\clob_raw_tape_tiering_run.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "raw tiering runner not found at $script"
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
$maxRuntimeSeconds = 2400
$limit = 150
$executionTimeLimit = "PT41M"
$actionTokens = @(
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy", "Bypass",
    "-File", $script,
    "-RepoRoot", $RepoRoot,
    "-MaxRuntimeSeconds", ([string]$maxRuntimeSeconds),
    "-Limit", ([string]$limit)
)
$arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $actionTokens

$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 41) `
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
    -Description "Tiers a bounded batch of raw CLOB tapes through the canonical contained runner, independently of the daily refresh chain." `
    -Force | Out-Null

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
    throw "registration readback does not match the exact bounded 06:00 raw-tiering contract"
}

Write-Host "Registered scheduled task '$TaskName': daily at $At local, limit $limit, max ${maxRuntimeSeconds}s, task limit $executionTimeLimit, no late catch-up."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Task-level status: data\logs\clob_raw_tape_tiering_task_status.json"
