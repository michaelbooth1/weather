# L13: register the HRRR forward recorder logon task (owner yes relayed by the coordinator, 2026-10-27).
# Run with -WhatIf first: it prints the full definition and asks Register-ScheduledTask for its WhatIf.
#
# Shape: AtLogOn trigger for the current user (2 min delay), Interactive / Limited, MultipleInstances
# IgnoreNew, StartWhenAvailable off, no repetition. The action runs hrrr_forward_recorder_launch.ps1,
# which starts the recorder through WMI exactly as on_death.ps1 does and exits within about a minute.
# The recorder is not in the task's process tree, so the task's ExecutionTimeLimit (10 min, for the
# launcher only) never stops it. The recorder's own single-instance lock prevents a double run.
#
# Scope: recorder only. The sampler and watchdog are not registered (forensic aids, started by hand
# when master asks). The Disabled "L13 HRRR forward recorder keepalive" task is not read, changed or
# deleted by this script; the new task supersedes it.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L13 HRRR forward recorder (logon)',
    [string]$Worktree = 'C:\wt\l13'
)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Worktree 'tools\research\hrrr_forward_recorder_launch.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "launcher missing: $launcher" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
$user = "$env:USERDOMAIN\$env:USERNAME"
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory 'C:\t\l13'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT2M'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $false
$description = 'L13 research: start the HRRR forward shadow recorder at logon (WMI-detached; STOP file C:\t\l13\hrrr_forward\STOP). Owner yes 2026-10-27.'

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Trigger          : AtLogOn ($user), Delay $($trigger.Delay), no repetition"
Write-Output "Action           : powershell.exe $argument (working dir C:\t\l13)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority), DisallowStartIfOnBatteries $($settings.DisallowStartIfOnBatteries), StopIfGoingOnBatteries $($settings.StopIfGoingOnBatteries)"
Write-Output "Launcher sha256  : $((Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLower())"
Write-Output "Keepalive task   : left as is (not read, changed or deleted)"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description $description | Out-Null
    $t = Get-ScheduledTask -TaskName $TaskName
    Write-Output "Registered: state $($t.State)"
} else {
    # Register-ScheduledTask has no -WhatIf; build the same in-memory task object and print it instead.
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description $description
    Write-Output '--- WhatIf: task object that would be registered (nothing registered) ---'
    Write-Output ($task.Actions | Select-Object Execute, Arguments, WorkingDirectory | Format-List | Out-String).Trim()
    Write-Output ($task.Triggers | Select-Object @{n = 'Type'; e = { $_.CimClass.CimClassName } }, UserId, Delay, Enabled | Format-List | Out-String).Trim()
    Write-Output ($task.Principal | Select-Object UserId, LogonType, RunLevel | Format-List | Out-String).Trim()
    Write-Output ($task.Settings | Select-Object MultipleInstances, StartWhenAvailable, ExecutionTimeLimit, Priority, DisallowStartIfOnBatteries, StopIfGoingOnBatteries, RestartCount | Format-List | Out-String).Trim()
}
