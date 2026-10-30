# L13: register the recorder keepalive task (needs the owner's yes in the coordinator's chat; decision 6).
# Run with -WhatIf first: it prints the full definition and the task object; nothing is registered.
#
# Shape: a time trigger repeating every 15 min with no end, MultipleInstances IgnoreNew, StartWhenAvailable off (no
# catch-up burst after sleep or logoff), ExecutionTimeLimit PT14M, Interactive / Limited for the current user. The
# action runs tools\research\recorder_keepalive.ps1 from the pinned worktree: for each workstation forward recorder it
# checks the PID file and CommandLine, and runs that recorder's own pinned launcher (sha256-checked) when it is down.
# Recorders with a STOP file are never restarted, and HRRR is check-only (its own keepalive task restarts it). The
# recorders start WMI-detached, outside the task's process tree, so the time limit stops only the keepalive.
# Stop: New-Item C:\t\recorder_keepalive\STOP. -ExpectedLauncherSha256 (the keepalive script's sha256) is required.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L13 recorder keepalive (15 min)',
    [string]$Worktree = 'C:\wt\l13rk',
    [string]$WorkingDirectory = 'C:\t\recorder_keepalive',
    [string]$ExpectedLauncherSha256 = '',
    [int]$IntervalMinutes = 15,
    [datetime]$Start = [datetime]::MinValue
)
$ErrorActionPreference = 'Stop'
# Test guard (incident 2026-10-30, docs/research/hrrr-keepalive-launcher-2026-10-30.md on the keepalive branch): under
# WEATHER_TASK_TEST=1 refuse before anything else unless every Scheduler command is a non-module function stub.
if ($env:WEATHER_TASK_TEST -eq '1') {
    foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
        $c = Get-Command $name
        if ($c.Source) { throw "WEATHER_TASK_TEST=1 and $name is the real $($c.Source) command; refusing" }
    }
}
# Task names cannot hold a path separator or other reserved characters: Register-ScheduledTask fails on them with
# 0x80070057 ("00/12/18Z" did, 2026-10-30), which a stubbed test cannot see. Refuse them up front.
if (-not $TaskName -or $TaskName -ne $TaskName.Trim() -or $TaskName -match '[\\/:*?"<>|\p{Cc}]') {
    throw "invalid task name '$TaskName': no / \ : * ? `" < > | or control characters, no leading or trailing spaces"
}
$launcher = Join-Path $Worktree 'tools\research\recorder_keepalive.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "launcher missing: $launcher" }
# Get-FileHash honours -WhatIf and would return nothing under it, so hash directly.
$sha = [Security.Cryptography.SHA256]::Create()
$launcherSha = (($sha.ComputeHash([IO.File]::ReadAllBytes($launcher)) | ForEach-Object { $_.ToString('x2') }) -join '')
if (-not $ExpectedLauncherSha256.Trim()) { throw "pass -ExpectedLauncherSha256 (launcher sha256 is $launcherSha)" }
if ($launcherSha -ne $ExpectedLauncherSha256.Trim().ToLower()) {
    throw "launcher sha256 $launcherSha != expected $($ExpectedLauncherSha256.Trim().ToLower())"
}
if ($IntervalMinutes -lt 5) { throw "IntervalMinutes $IntervalMinutes is below 5" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
if ($Start -eq [datetime]::MinValue) {
    $now = Get-Date
    $Start = $now.Date.AddMinutes([math]::Ceiling(($now - $now.Date).TotalMinutes / $IntervalMinutes) * $IntervalMinutes)
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$workDir = $WorkingDirectory
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -Once -At $Start -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 14) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $false
$description = "L13 research: every $IntervalMinutes min check the workstation forward recorders and run the pinned launcher of any that is down (STOP files honoured; HRRR check-only). Log $workDir\keepalive_<yyyyMM>.jsonl; stop with $workDir\STOP."

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Trigger          : Once at $($Start.ToString('s')) local, RepetitionInterval $($trigger.Repetition.Interval), RepetitionDuration '$($trigger.Repetition.Duration)' (empty = no end)"
Write-Output "Action           : powershell.exe $argument (working dir $workDir)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority), DisallowStartIfOnBatteries $($settings.DisallowStartIfOnBatteries), StopIfGoingOnBatteries $($settings.StopIfGoingOnBatteries)"
Write-Output "Launcher sha256  : $launcherSha"
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
    Write-Output ($task.Triggers | Select-Object @{n = 'Type'; e = { $_.CimClass.CimClassName } }, StartBoundary, Enabled, @{n = 'RepetitionInterval'; e = { $_.Repetition.Interval } }, @{n = 'RepetitionDuration'; e = { $_.Repetition.Duration } } | Format-List | Out-String).Trim()
    Write-Output ($task.Principal | Select-Object UserId, LogonType, RunLevel | Format-List | Out-String).Trim()
    Write-Output ($task.Settings | Select-Object MultipleInstances, StartWhenAvailable, ExecutionTimeLimit, Priority, DisallowStartIfOnBatteries, StopIfGoingOnBatteries, RestartCount | Format-List | Out-String).Trim()
}
