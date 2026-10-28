# L13: register the GEFS 06Z forward recorder logon task (needs the owner's yes in the coordinator's chat).
# Run with -WhatIf first: it prints the full definition and the task object; nothing is registered.
#
# Shape (as the HRRR forward recorder's): AtLogOn trigger for the current user (3 min delay), Interactive / Limited,
# MultipleInstances IgnoreNew, StartWhenAvailable off, no repetition. The action runs gefs_forward_recorder_launch.ps1,
# which starts the recorder through WMI and exits within about a minute. The recorder is not in the task's process
# tree, so the task's ExecutionTimeLimit (10 min, for the launcher only) never stops it; the recorder's own lock
# prevents a double run. Stop: New-Item C:\t\l6g\forward\gefs\STOP.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L13 GEFS forward recorder (logon)',
    [string]$Worktree = 'C:\wt\l13g'
)
$ErrorActionPreference = 'Stop'
$launcher = Join-Path $Worktree 'tools\research\gefs_forward_recorder_launch.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "launcher missing: $launcher" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
$user = "$env:USERDOMAIN\$env:USERNAME"
$workDir = 'C:\t\l6g\forward\gefs'
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT3M'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $false
$description = 'L13 research: start the GEFS 06Z forward recorder for L6_G at logon (WMI-detached; STOP file C:\t\l6g\forward\gefs\STOP).'

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Trigger          : AtLogOn ($user), Delay $($trigger.Delay), no repetition"
Write-Output "Action           : powershell.exe $argument (working dir $workDir)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority), DisallowStartIfOnBatteries $($settings.DisallowStartIfOnBatteries), StopIfGoingOnBatteries $($settings.StopIfGoingOnBatteries)"
Write-Output "Launcher sha256  : $((Get-FileHash -Algorithm SHA256 -LiteralPath $launcher).Hash.ToLower())"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    if (-not (Test-Path -LiteralPath $workDir)) { New-Item -ItemType Directory -Force $workDir | Out-Null }
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
