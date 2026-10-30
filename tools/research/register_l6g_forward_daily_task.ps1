# Lane L2: register the L6_G forward daily emission task on the WORKSTATION (owner's yes, 2026-10-30, relayed by the
# coordinator). Run with -WhatIf first: it prints the full definition and the task object; nothing is registered.
#
# Action: tools\research\l6g_forward_daily.ps1 from the pinned worktree (default C:\wt\l6g-daily-pinned, detached and
# `git worktree lock`ed; tools\research\l6g_forward_daily.ps1 there refuses any run whose emitter, look, frame, mg2_inputs or mg2_composite blob
# is not the pinned one). It emits each finished local date from 2026-10-31 that has no vectors yet.
# Triggers: local wall-clock daily at 07:30, 10:30, 13:30, 16:30, 19:30 and 22:30 (New-WeatherLocalDailyTrigger,
# unzoned, so they follow the clock across the 2026-11-01 fall-back). Why: the capture host publishes the MG-2 bundle
# for D at about 04:15 local on D+1, with its one retry at 07:00; the GEFS recorder's manifest for D is written at
# about 06:03 on D. 07:30 is the first slot after both; the later slots retry a late bundle and the last (22:30)
# still lands before the receiver's deadline (23:59 local on D+1), after which a date is late/missing and never
# emitted. Re-runs are no-ops for emitted dates.
# Principal: current user, Interactive / Limited, as the GEFS and MOSMIX forward-recorder tasks (it lives in
# tools\research, outside the scripts\ops S4U rule, for this reason): the share \\192.168.1.247\mg2-inputs is reached with the workstation's stored credential,
# which an S4U session cannot use (as the credential-vault tasks). The task runs only while the user is logged on.
# MultipleInstances IgnoreNew; StartWhenAvailable on (a slot missed while asleep runs at wake; the wrapper's own
# deadline rule keeps it point-in-time); ExecutionTimeLimit 4 h. Stop: New-Item C:\t\l6g\forward\STOP.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L2 L6_G forward daily emit',
    [string]$Worktree = 'C:\wt\l6g-daily-pinned'
)
$ErrorActionPreference = 'Stop'
$opsDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\ops'
. (Join-Path $opsDir 'scheduled_task_local_trigger.ps1')
$wrapper = Join-Path $Worktree 'tools\research\l6g_forward_daily.ps1'
if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) { throw "wrapper missing: $wrapper" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
$user = "$env:USERDOMAIN\$env:USERNAME"
$workDir = 'C:\t\l6g\forward'
$triggerTimes = @('07:30', '10:30', '13:30', '16:30', '19:30', '22:30')
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$wrapper`" -Worktree `"$Worktree`""
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
$description = 'L2 research: L6_G forward screen daily emission (prereg FROZEN 2026-10-30, D0 2026-10-31); logs C:\t\l6g\forward\logs; STOP file C:\t\l6g\forward\STOP.'

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Triggers         : daily (local, unzoned) at $($triggerTimes -join ', '); boundaries $(($triggers | ForEach-Object { $_.StartBoundary }) -join ', ')"
Write-Output "Action           : powershell.exe $argument (working dir $workDir)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority)"
$sha = [Security.Cryptography.SHA256]::Create().ComputeHash([IO.File]::ReadAllBytes($wrapper))  # Get-FileHash honours -WhatIf
Write-Output "Wrapper sha256   : $((($sha | ForEach-Object { $_.ToString('x2') }) -join ''))"
$head = try { $ErrorActionPreference = 'Continue'; [string](& git -C $Worktree rev-parse HEAD 2>$null) } catch { '' } finally { $ErrorActionPreference = 'Stop' }
Write-Output "Worktree HEAD    : $head"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    if (-not (Test-Path -LiteralPath $workDir)) { New-Item -ItemType Directory -Force $workDir | Out-Null }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal `
        -Settings $settings -Description $description | Out-Null
    $t = Get-ScheduledTask -TaskName $TaskName
    foreach ($tr in $t.Triggers) {
        if (-not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$tr.StartBoundary) -At ([string]$tr.StartBoundary).Substring(11, 5))) {
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
