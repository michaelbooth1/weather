# L13: replace the Disabled HRRR keepalive task with a 15-minute launcher task. Run with -WhatIf first; registering
# needs the owner's yes relayed by the coordinator. Drafted 2026-10-30 on claude/hrrr-keepalive-launcher-20261030.
#
# Why: the old "L13 HRRR forward recorder keepalive" (cmd.exe /c C:\t\l13\recorder_keepalive.cmd, every 10 min,
# StartWhenAvailable on) failed its three relaunches because it started the recorder without --wait-lock-seconds:
# the new process exited while the dying one still held the single-instance lock. It is Disabled.
#
# New task shape: a time trigger repeating every 15 min with no end, MultipleInstances IgnoreNew, StartWhenAvailable
# off (no catch-up burst after sleep or logoff), ExecutionTimeLimit PT2M, Interactive / Limited for the current user.
# The action runs hrrr_forward_recorder_launch.ps1 from the pinned worktree, the launcher the logon task already
# uses: it refuses on the STOP file (C:\t\l13\hrrr_forward\STOP) or a code blob that is not pinned, no-ops when the
# PID in recorder.pid is alive with a recorder command line, and otherwise starts the recorder detached through WMI
# with --wait-lock-seconds 120 and a line in C:\t\l13\recorder_pid_log.txt. The recorder is not in the task's process
# tree, so the 2-minute limit stops only the launcher.
#
# The registrar refuses unless the launcher's sha256 equals -ExpectedLauncherSha256, the new task does not exist yet,
# and the old task is absent or Disabled with its keepalive.cmd action. It then registers the new task and
# unregisters the old one in the same run. The logon task and the running recorder are not touched.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L13 HRRR forward recorder keepalive (launcher)',
    [string]$OldTaskName = 'L13 HRRR forward recorder keepalive',
    [string]$Worktree = 'C:\wt\l13',
    [string]$WorkingDirectory = 'C:\t\l13',
    [string]$ExpectedLauncherSha256 = '',
    [int]$IntervalMinutes = 15,
    [datetime]$Start = [datetime]::MinValue
)
$ErrorActionPreference = 'Stop'
# Test guard (incident 2026-10-30: a stubbed test reached the real Scheduler after module autoload replaced the stubs).
# Under WEATHER_TASK_TEST=1 refuse before anything else unless every Scheduler command is a non-module function stub.
if ($env:WEATHER_TASK_TEST -eq '1') {
    foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
        $c = Get-Command $name
        if ($c.Source) { throw "WEATHER_TASK_TEST=1 and $name is the real $($c.Source) command; refusing" }
    }
}
$launcher = Join-Path $Worktree 'tools\research\hrrr_forward_recorder_launch.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "launcher missing: $launcher" }
# Get-FileHash honours -WhatIf and would return nothing under it, so hash directly.
$sha = [Security.Cryptography.SHA256]::Create()
$launcherSha = (($sha.ComputeHash([IO.File]::ReadAllBytes($launcher)) | ForEach-Object { $_.ToString('x2') }) -join '')
if (-not $ExpectedLauncherSha256.Trim()) { throw "pass -ExpectedLauncherSha256 (the launcher's sha256 is $launcherSha)" }
if ($launcherSha -ne $ExpectedLauncherSha256.ToLower()) { throw "launcher sha256 $launcherSha != expected $ExpectedLauncherSha256" }
if ($IntervalMinutes -lt 5) { throw "IntervalMinutes $IntervalMinutes is below 5" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
$old = Get-ScheduledTask -TaskName $OldTaskName -ErrorAction SilentlyContinue
if ($old) {
    if ("$($old.State)" -ne 'Disabled') { throw "old task '$OldTaskName' is $($old.State), not Disabled; not replacing it" }
    $oldAction = (@($old.Actions) | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join '; '
    if ($oldAction -notlike '*recorder_keepalive.cmd*') { throw "old task '$OldTaskName' action is '$oldAction'; not the keepalive" }
}
if ($Start -eq [datetime]::MinValue) {
    $now = Get-Date
    $Start = $now.Date.AddMinutes([math]::Ceiling(($now - $now.Date).TotalMinutes / $IntervalMinutes) * $IntervalMinutes)
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $WorkingDirectory
$trigger = New-ScheduledTaskTrigger -Once -At $Start -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $false
$description = "L13 research: every $IntervalMinutes min run the HRRR forward recorder launcher (no-op while the recorder is alive; WMI-detached start with --wait-lock-seconds 120; STOP file C:\t\l13\hrrr_forward\STOP). Replaces '$OldTaskName'."

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Trigger          : Once at $($Start.ToString('s')) local, RepetitionInterval $($trigger.Repetition.Interval), RepetitionDuration '$($trigger.Repetition.Duration)' (empty = no end)"
Write-Output "Action           : powershell.exe $argument (working dir $WorkingDirectory)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority), DisallowStartIfOnBatteries $($settings.DisallowStartIfOnBatteries), StopIfGoingOnBatteries $($settings.StopIfGoingOnBatteries)"
Write-Output "Launcher sha256  : $launcherSha (matches expected)"
if ($old) { Write-Output "Old task         : '$OldTaskName' state $($old.State), action $oldAction -> unregister after the new task registers" }
else { Write-Output "Old task         : '$OldTaskName' absent; nothing to unregister" }

if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description $description | Out-Null
    Write-Output "Registered: $TaskName"
} else {
    # Register-ScheduledTask has no -WhatIf; build the same in-memory task object and print it instead.
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description $description
    Write-Output '--- WhatIf: task object that would be registered (nothing registered) ---'
    Write-Output ($task.Actions | Select-Object Execute, Arguments, WorkingDirectory | Format-List | Out-String).Trim()
    Write-Output ($task.Triggers | Select-Object @{n = 'Type'; e = { $_.CimClass.CimClassName } }, StartBoundary, Enabled, @{n = 'RepetitionInterval'; e = { $_.Repetition.Interval } }, @{n = 'RepetitionDuration'; e = { $_.Repetition.Duration } }, @{n = 'StopAtDurationEnd'; e = { $_.Repetition.StopAtDurationEnd } } | Format-List | Out-String).Trim()
    Write-Output ($task.Principal | Select-Object UserId, LogonType, RunLevel | Format-List | Out-String).Trim()
    Write-Output ($task.Settings | Select-Object MultipleInstances, StartWhenAvailable, ExecutionTimeLimit, Priority, DisallowStartIfOnBatteries, StopIfGoingOnBatteries, RestartCount | Format-List | Out-String).Trim()
}
if ($old) {
    if ($PSCmdlet.ShouldProcess($OldTaskName, 'Unregister-ScheduledTask (Disabled keepalive)')) {
        Unregister-ScheduledTask -TaskName $OldTaskName -Confirm:$false
        Write-Output "Unregistered: $OldTaskName"
    } else {
        Write-Output "WhatIf: would unregister '$OldTaskName' (nothing unregistered)"
    }
}
