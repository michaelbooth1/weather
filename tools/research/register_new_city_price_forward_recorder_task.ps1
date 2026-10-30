# L3: register the new-city price forward recorder logon task (DRAFT) (needs the owner's yes in the coordinator's chat).
# Run with -WhatIf first: it prints the full definition and the task object; nothing is registered.
#
# Shape (as the ENS, ECCC and GEFS forward recorders'): AtLogOn trigger for the current user (5 min delay),
# Interactive / Limited, MultipleInstances IgnoreNew, StartWhenAvailable off, no repetition. The action runs
# new_city_price_forward_recorder_launch.ps1, which starts the recorder through WMI and exits within about a minute. The
# recorder is not in the task's process tree, so the task's ExecutionTimeLimit (10 min, for the launcher only) never
# stops it; the recorder's own lock prevents a double run. Stop: New-Item C:\t\new_city_prices\forward\STOP.
# -ExpectedLauncherSha256 is required: the registrar refuses unless the launcher on disk is exactly the one reviewed.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'L3 new-city price forward recorder (logon)',
    [string]$Worktree = 'C:\wt\l3newcity',
    [string]$WorkingDirectory = 'C:\t\new_city_prices\forward',
    [string]$ExpectedLauncherSha256 = ''
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
# Task-name validation: a plain name only (no path separators or wildcard/reserved characters, no leading or
# trailing space), so the name can never address a task folder or another task.
if ([string]::IsNullOrWhiteSpace($TaskName) -or $TaskName -ne $TaskName.Trim() -or $TaskName.Length -gt 200 -or
    $TaskName.IndexOfAny([char[]]'/\:*?"<>|') -ge 0) {
    throw "invalid task name: '$TaskName' (no / \ : * ? `" < > | and no leading/trailing space)"
}
$launcher = Join-Path $Worktree 'tools\research\new_city_price_forward_recorder_launch.ps1'
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
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT5M'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$settings.StartWhenAvailable = $false
$description = "L3 research: start the new-city price forward recorder at logon (WMI-detached; STOP file $workDir\STOP)."

Write-Output "Task name        : $TaskName"
Write-Output "Principal        : $user, LogonType Interactive, RunLevel Limited"
Write-Output "Trigger          : AtLogOn ($user), Delay $($trigger.Delay), no repetition"
Write-Output "Action           : powershell.exe $argument (working dir $workDir)"
Write-Output "Settings         : MultipleInstances $($settings.MultipleInstances), StartWhenAvailable $($settings.StartWhenAvailable), ExecutionTimeLimit $($settings.ExecutionTimeLimit), Priority $($settings.Priority), DisallowStartIfOnBatteries $($settings.DisallowStartIfOnBatteries), StopIfGoingOnBatteries $($settings.StopIfGoingOnBatteries)"
Write-Output "Launcher sha256  : $launcherSha"
if ($PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask')) {
    # The task's working directory must exist before the first logon start, or the task cannot start at all.
    [void][IO.Directory]::CreateDirectory($workDir)
    if (-not (Test-Path -LiteralPath $workDir -PathType Container)) { throw "could not create working directory $workDir" }
    Write-Output "Working directory: $workDir (exists)"
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
