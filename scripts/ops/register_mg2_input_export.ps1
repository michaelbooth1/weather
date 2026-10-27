# Registers WeatherMg2InputExport (MG-2 binding plan section 9.3): the daily capture-host input export.
#
# NOT REGISTERED by default. Registration needs the owner's explicit yes; run it only on the dedicated capture
# host, from a clean checkout at the reviewed tip, by the production agent. `-WhatIf` prints the exact task
# definition and touches nothing (no host check, no Scheduler call), so a reviewer can run it anywhere.
#
# Triggers: 04:15 local on D+1 (after the export cut and the 01:00-04:00 quiet window, inside 00:30-09:00)
# and the single retry at 07:00, which the wrapper turns into a no-op once the date's bundle is published.
# No StartWhenAvailable: a missed run never catches up later. The action never passes --coverage-counts.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProductionRepoRoot = "",
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an advanced script's param()
# defaults under `powershell -File`; derive the default here. An explicit -ProductionRepoRoot always wins.
if (-not $ProductionRepoRoot) {
    $ProductionRepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'

# The reviewed tip must be checked out with no tracked change. Untracked files do not block: the production tree
# carries a permanent untracked venv-cp3110\ (master, 2026-10-27).
function Assert-Mg2RegistrationSource {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Tip)
    $head = ([string](git -C $Root rev-parse HEAD)).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -cne $Tip) { throw 'Reviewed source tip mismatch' }
    $tracked = @(git -C $Root status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $tracked.Count -ne 0) { throw 'Source must be clean (tracked changes present)' }
}
. (Join-Path $PSScriptRoot 'scheduled_task_local_trigger.ps1')
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskName = 'WeatherMg2InputExport'
$triggerTimes = @('04:15', '07:00')
$timeLimit = 'PT1H15M'
$exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tokens = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
    (Join-Path $PSScriptRoot 'mg2_input_export.ps1'), '-ProductionRepoRoot', $ProductionRepoRoot)

if (-not $PSCmdlet.ShouldProcess($taskName, 'Register-ScheduledTask (owner approval required)')) {
    [ordered]@{
        task_name = $taskName; execute = $exe; arguments = $tokens; working_directory = $sourceRoot
        triggers_local_daily = $triggerTimes; principal = "$env:USERNAME S4U Limited"
        execution_time_limit = $timeLimit; multiple_instances = 'IgnoreNew'; start_when_available = $false
        expected_source_tip = $ExpectedSourceTip; registered = $false
    } | ConvertTo-Json -Compress
    return
}

. (Join-Path $PSScriptRoot 'workload_admission.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'Registration is restricted to the dedicated capture host'
}
Assert-Mg2RegistrationSource -Root $sourceRoot -Tip $ExpectedSourceTip

. (Join-Path $PSScriptRoot 'training_window_contract.ps1')
$argsText = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
$action = New-ScheduledTaskAction -Execute $exe -Argument $argsText -WorkingDirectory $sourceRoot
$triggers = @(foreach ($at in $triggerTimes) { New-WeatherLocalDailyTrigger -At $at })
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 75) -MultipleInstances IgnoreNew
$null = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal `
    -Settings $settings -Force
$actual = Get-ScheduledTask -TaskName $taskName
$boundaries = @($actual.Triggers | ForEach-Object { [string]$_.StartBoundary })
$triggersOk = $actual.Triggers.Count -eq $triggerTimes.Count
for ($i = 0; $triggersOk -and $i -lt $triggerTimes.Count; $i++) {
    $triggersOk = (Test-WeatherLocalDailyStartBoundary -StartBoundary $boundaries[$i] -At $triggerTimes[$i]) -and
        $actual.Triggers[$i].DaysInterval -eq 1
}
if ($actual.Actions.Count -ne 1 -or $actual.Actions[0].Execute -cne $exe -or
    $actual.Actions[0].Arguments -cne $argsText -or $actual.Actions[0].WorkingDirectory -cne $sourceRoot -or
    $actual.Actions[0].Arguments -match 'coverage' -or
    $actual.Principal.LogonType -ne 'S4U' -or $actual.Principal.RunLevel -ne 'Limited' -or
    $actual.Settings.StartWhenAvailable -or $actual.Settings.MultipleInstances -ne 'IgnoreNew' -or
    $actual.Settings.ExecutionTimeLimit -ne $timeLimit -or -not $triggersOk) {
    throw 'Scheduled-task readback mismatch; inspect registration'
}
$actual
