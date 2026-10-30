# Lane L2: register the MG-2 / Rule B-1 forward input pull+receive task on the WORKSTATION (binding plan section 9.7).
# DRAFT: registration needs the owner's yes through the coordinator. Run with -WhatIf first: it prints the full
# definition and the task object; nothing is registered.
#
# Action: tools\research\mg2_forward_inputs_daily.ps1 from the pinned worktree (default C:\wt\mg2-forward-pinned,
# detached at a commit whose mg2_inputs.py, mg2_input_allowlist.py and mg2_composite.py are the B binding blobs, and
# `git worktree lock`ed; the launcher refuses any run where they differ). -Build adds the separable layout-build stage
# to the action (off by default).
# Triggers: local wall-clock daily at 06:30, then hourly 07:30 .. 22:30, and 23:00 (New-WeatherLocalDailyTrigger,
# unzoned, so they follow the clock across the 2026-11-01 fall-back). Why: the host exports D at 04:15 on D+1 with one
# retry at 07:00; the receiver's deadline is 23:59 workstation local on D+1, and the first run on D+2 records the
# date's late/missing line. A not_ready, refused or quarantined result stops that run; the next trigger is the only
# retry.
# Principal: current user, Interactive / Limited (as the L6_G daily task): the share \\192.168.1.247\mg2-inputs is
# reached with the workstation's stored credential, which an S4U session cannot use. Neither script handles a
# credential. The task runs only while the user is logged on.
# MultipleInstances IgnoreNew; StartWhenAvailable on (a slot missed while asleep runs at wake; mg2_inputs' own
# deadline keeps it point-in-time); ExecutionTimeLimit 4 h (a queued build can wait). Stop: New-Item
# C:\t\mg2\forward\task\STOP.
# -ExpectedLauncherSha256 is required: the registrar refuses unless the launcher on disk is exactly the one reviewed.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L2 MG-2 forward input pull+receive',
    [string]$Worktree = 'C:\wt\mg2-forward-pinned',
    [string]$WorkingDirectory = 'C:\t\mg2\forward\task',
    [string]$ExpectedLauncherSha256 = '',
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
# Test guard (incident 2026-10-30): under WEATHER_TASK_TEST=1 refuse before anything else unless every Scheduler
# command is a non-module function stub.
if ($env:WEATHER_TASK_TEST -eq '1') {
    foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
        $c = Get-Command $name
        if ($c.CommandType -ne 'Function' -or $c.Source) { throw "WEATHER_TASK_TEST=1 and $name is the real $($c.Source) command; refusing" }
    }
}
# Task-name validation: a plain name only (no path separators or wildcard/reserved characters, no leading or
# trailing space), so the name can never address a task folder or another task.
if ([string]::IsNullOrWhiteSpace($TaskName) -or $TaskName -ne $TaskName.Trim() -or $TaskName.Length -gt 200 -or
    $TaskName.IndexOfAny([char[]]'/\:*?"<>|') -ge 0) {
    throw "invalid task name: '$TaskName' (no / \ : * ? `" < > | and no leading/trailing space)"
}
$opsDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\ops'
. (Join-Path $opsDir 'scheduled_task_local_trigger.ps1')
$launcher = Join-Path $Worktree 'tools\research\mg2_forward_inputs_daily.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "launcher missing: $launcher" }
# Get-FileHash honours -WhatIf and would return nothing under it, so hash directly.
$sha = [Security.Cryptography.SHA256]::Create()
$launcherSha = (($sha.ComputeHash([IO.File]::ReadAllBytes($launcher)) | ForEach-Object { $_.ToString('x2') }) -join '')
if (-not $ExpectedLauncherSha256.Trim()) { throw "pass -ExpectedLauncherSha256 (launcher sha256 is $launcherSha)" }
if ($launcherSha -ne $ExpectedLauncherSha256.Trim().ToLower()) {
    throw "launcher sha256 $launcherSha != expected $($ExpectedLauncherSha256.Trim().ToLower())"
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
$user = "$env:USERDOMAIN\$env:USERNAME"
$workDir = $WorkingDirectory
$triggerTimes = @('06:30', '07:30', '08:30', '09:30', '10:30', '11:30', '12:30', '13:30', '14:30', '15:30', '16:30', '17:30', '18:30', '19:30', '20:30', '21:30', '22:30', '23:00')
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -Worktree `"$Worktree`" -LogRoot `"$workDir`""
if ($Build) { $argument += ' -Build' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $workDir
$triggers = @(foreach ($at in $triggerTimes) { New-WeatherLocalDailyTrigger -At $at })
foreach ($i in 0..($triggerTimes.Count - 1)) {
    if (-not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$triggers[$i].StartBoundary) -At $triggerTimes[$i])) {
        throw "trigger $($triggerTimes[$i]) is not an unzoned local boundary"
    }
}
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $true
$description = "L2 research: MG-2 / Rule B-1 forward input pull+receive (binding plan 9.7); ledger C:\t\mg2\forward\input_receipts.jsonl; logs $workDir\logs; STOP file $workDir\STOP."

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Triggers         : daily (local, unzoned) at $($triggerTimes -join ', ')"
Write-Output "Action           : powershell.exe $argument (working dir $workDir)"
Write-Output "Build stage      : $([bool]$Build)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority)"
Write-Output "Launcher sha256  : $launcherSha"
$head = try { $ErrorActionPreference = 'Continue'; [string](& git -C $Worktree rev-parse HEAD 2>$null) } catch { '' } finally { $ErrorActionPreference = 'Stop' }
Write-Output "Worktree HEAD    : $head"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    # The task's working directory must exist before the first start, or the task cannot start at all.
    [void][IO.Directory]::CreateDirectory($workDir)
    if (-not (Test-Path -LiteralPath $workDir -PathType Container)) { throw "could not create working directory $workDir" }
    Write-Output "Working directory: $workDir (exists)"
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal `
        -Settings $settings -Description $description | Out-Null
    $t = Get-ScheduledTask -TaskName $TaskName
    foreach ($tr in @($t.Triggers)) {
        if ($tr -and $tr.StartBoundary -and -not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$tr.StartBoundary) -At ([string]$tr.StartBoundary).Substring(11, 5))) {
            throw "registered trigger has a zoned StartBoundary: $($tr.StartBoundary)"
        }
    }
    Write-Output "Registered: state $($t.State)"
} else {
    # Register-ScheduledTask has no -WhatIf; build the same in-memory task object and print it instead.
    $task = New-ScheduledTask -Action $action -Trigger $triggers -Principal $principal -Settings $settings `
        -Description $description
    Write-Output '--- WhatIf: task object that would be registered (nothing registered) ---'
    Write-Output ($task.Actions | Select-Object Execute, Arguments, WorkingDirectory | Format-List | Out-String).Trim()
    Write-Output ($task.Triggers | Select-Object @{n = 'Type'; e = { $_.CimClass.CimClassName } }, StartBoundary, Enabled | Format-List | Out-String).Trim()
    Write-Output ($task.Principal | Select-Object UserId, LogonType, RunLevel | Format-List | Out-String).Trim()
    Write-Output ($task.Settings | Select-Object MultipleInstances, StartWhenAvailable, ExecutionTimeLimit, Priority, DisallowStartIfOnBatteries, StopIfGoingOnBatteries | Format-List | Out-String).Trim()
}
