# Registers WeatherForwardArrivalCheck (R20 section 2, master ruling 2026-11-01): the capture-host check that
# yesterday's B and L6_G forward inputs reached the workstation and that its receipts beacon is alive.
#
# Master-agent scheduled-task authority (OPERATIONS_AGENT_ROLE section 4); register only after the R20 head has
# landed, on the dedicated capture host, from a clean checkout at -ExpectedSourceTip, with -WhatIf first.
# `-WhatIf` prints the exact task definition and touches nothing (no host check, no Scheduler call), so a reviewer
# can run it anywhere.
#
# Triggers: 07:45, 11:45 and 18:05 local (New-WeatherLocalDailyTrigger: unzoned, so they follow DST). The action
# is forward_input_arrival_check.ps1 -LastDate <date> (silent after it). S4U/Limited, IgnoreNew, a 5-minute limit
# and no StartWhenAvailable: a missed slot is not caught up; the next slot checks the same date.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = "",
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    # Host-local folder behind the xfer share's in\forward-receipts (the beacon's target).
    [Parameter(Mandatory = $true)][string]$ReceiptsRoot,
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$LastDate = "2026-12-16"
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an advanced script's param()
# defaults under `powershell -File`; derive the default here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathRooted($ReceiptsRoot) -or $ReceiptsRoot -match '["\r\n]' -or
    -not [IO.Path]::IsPathRooted($RepoRoot) -or $RepoRoot -match '["\r\n]') {
    throw 'absolute -RepoRoot and -ReceiptsRoot without quotes or newlines are required'
}

function Assert-ForwardArrivalRegistrationSource {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Tip)
    $head = ([string](git -C $Root rev-parse HEAD)).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -cne $Tip) { throw 'Reviewed source tip mismatch' }
    $tracked = @(git -C $Root status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $tracked.Count -ne 0) { throw 'Source must be clean (tracked changes present)' }
}
. (Join-Path $PSScriptRoot 'scheduled_task_local_trigger.ps1')
. (Join-Path $PSScriptRoot 'scheduled_task_test_guard.ps1')
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskName = 'WeatherForwardArrivalCheck'
$triggerTimes = @('07:45', '11:45', '18:05')
$timeLimit = 'PT5M'
$exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tokens = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
    (Join-Path $PSScriptRoot 'forward_input_arrival_check.ps1'), '-RepoRoot', $RepoRoot,
    '-ReceiptsRoot', $ReceiptsRoot, '-LastDate', $LastDate)

if (-not $PSCmdlet.ShouldProcess($taskName, 'Register-ScheduledTask (master-agent, after landing)')) {
    [ordered]@{
        task_name = $taskName; execute = $exe; arguments = $tokens; working_directory = $sourceRoot
        triggers_local_daily = $triggerTimes; principal = "$env:USERNAME S4U Limited"
        execution_time_limit = $timeLimit; multiple_instances = 'IgnoreNew'; start_when_available = $false
        expected_source_tip = $ExpectedSourceTip; registered = $false
    } | ConvertTo-Json -Compress
    return
}

Assert-WeatherScheduledTaskTestIsolation -Command @('Register-ScheduledTask', 'Get-ScheduledTask', 'Disable-ScheduledTask')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $sourceRoot
if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'Registration is restricted to the dedicated capture host'
}
Assert-ForwardArrivalRegistrationSource -Root $sourceRoot -Tip $ExpectedSourceTip

. (Join-Path $PSScriptRoot 'training_window_contract.ps1')
$argsText = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
$action = New-ScheduledTaskAction -Execute $exe -Argument $argsText -WorkingDirectory $sourceRoot
$triggers = @(foreach ($at in $triggerTimes) { New-WeatherLocalDailyTrigger -At $at })
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
$null = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal `
    -Settings $settings -Force
$actual = Get-ScheduledTask -TaskName $taskName
$boundaries = @($actual.Triggers | ForEach-Object { [string]$_.StartBoundary })
$triggersOk = @($actual.Triggers).Count -eq $triggerTimes.Count
for ($i = 0; $triggersOk -and $i -lt $triggerTimes.Count; $i++) {
    $triggersOk = (Test-WeatherLocalDailyStartBoundary -StartBoundary $boundaries[$i] -At $triggerTimes[$i]) -and
        $actual.Triggers[$i].DaysInterval -eq 1
}
if (@($actual.Actions).Count -ne 1 -or $actual.Actions[0].Execute -cne $exe -or
    $actual.Actions[0].Arguments -cne $argsText -or $actual.Actions[0].WorkingDirectory -cne $sourceRoot -or
    $actual.Principal.LogonType -ne 'S4U' -or $actual.Principal.RunLevel -ne 'Limited' -or
    $actual.Settings.StartWhenAvailable -or $actual.Settings.MultipleInstances -ne 'IgnoreNew' -or
    $actual.Settings.ExecutionTimeLimit -ne $timeLimit -or -not $triggersOk) {
    Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    throw 'Scheduled-task readback mismatch; the task was disabled; inspect registration'
}
$actual
