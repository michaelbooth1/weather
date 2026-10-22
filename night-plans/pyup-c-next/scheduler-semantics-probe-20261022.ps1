# SCHEDULER SEMANTICS PROBE (2026-10-22): what does Disable-ScheduledTask do to a task instance that is running?
# Master runs this by hand after 18:00 on the capture host. It registers ONE throwaway task, and touches no other.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <this file>      (elevated console recommended, see below)
#
# Steps
#   0. Refuse if \WeatherProbe\ already holds any task or the unique name exists anywhere.
#   1. Register \WeatherProbe\WeatherSchedulerSemanticsProbe-<stamp>-<pid>: no trigger; action
#      powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Sleep -Seconds 120; # <name>"
#      (the trailing comment tags the process so it can be found by command line); ExecutionTimeLimit 5 min;
#      MultipleInstances IgnoreNew; no StartWhenAvailable.
#   2. Start it; wait (bounded, -RunningWaitSeconds) for State Running.
#   3. Disable-ScheduledTask it while it runs.
#   4. Read back State, Settings.Enabled, LastTaskResult and the tagged process count at +0 s, +5 s and +30 s.
#   5. Stop-ScheduledTask it; read back at +0 s and +5 s.
#   6. finally: Unregister-ScheduledTask -Confirm:$false; verify it is gone; check that no other task's
#      Settings.Enabled changed; $Host.SetShouldExit + exit inside the finally (docs/development.md: a stopped
#      PS 5.1 -File script otherwise exits 0).
#
# Principal choice: the current user, LogonType Interactive, RunLevel Limited. Interactive needs no stored
# password and no S4U grant, and the Enabled-versus-State behaviour under test is a property of the task
# definition and the Task Scheduler service, not of the logon type. Pass -LogonType S4U to mirror the production
# supervisors exactly (S4U usually needs an elevated console to register). The task itself never runs elevated.
# The session should be elevated anyway: creating the \WeatherProbe\ folder can need it, and a non-elevated
# Get-ScheduledTask hides S4U tasks, which weakens the "no other task changed" check. The empty \WeatherProbe\
# folder is left behind (removing a folder needs the COM API; an empty folder is harmless and step 0 accepts it).
#
# Exit codes: 0 = probe completed and cleaned up; 1 = probe failed but cleaned up; 2 = refused before registering;
# 3 = cleanup could not prove the task is gone (inspect \WeatherProbe\ by hand).
[CmdletBinding()]
param(
    [ValidateSet('Interactive', 'S4U')][string]$LogonType = 'Interactive',
    [ValidateRange(5, 120)][int]$RunningWaitSeconds = 60
)
$ErrorActionPreference = 'Stop'
$TaskPath = '\WeatherProbe\'
$TaskName = 'WeatherSchedulerSemanticsProbe-{0}-{1}' -f (Get-Date -Format 'yyyyMMddHHmmss'), $PID
$Tag = "# $TaskName"
$Rows = [Collections.Generic.List[string]]::new()
$Notes = [Collections.Generic.List[string]]::new()
$Registered = $false
$ExitCode = 1
$T0 = $null

function Assert-ProbeIdentity {
    # Every mutating call below uses exactly these two variables; re-assert them before each one.
    if ($TaskPath -cne '\WeatherProbe\' -or $TaskName -cnotmatch '^WeatherSchedulerSemanticsProbe-\d{14}-\d+$') {
        throw "probe identity changed: $TaskPath$TaskName" }
}
function Get-ProbeTask {
    $all = @(Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ceq $TaskName })
    if ($all.Count -gt 1) { throw "more than one task named $TaskPath$TaskName" }
    if ($all.Count -eq 1) { return $all[0] }
    return $null
}
function Get-ProbeProcessCount {
    @(Get-CimInstance -ClassName Win32_Process -Filter "Name='powershell.exe'" | Where-Object { "$($_.CommandLine)".Contains($Tag) }).Count
}
function Add-Readback([string]$Step) {
    $t = Get-ProbeTask
    $off = if ($T0) { '{0,6:n1}' -f ((Get-Date) - $T0).TotalSeconds } else { '     -' }
    if ($t) {
        if ($t.TaskName -cne $TaskName -or $t.TaskPath -cne $TaskPath) { throw "readback returned another task: $($t.TaskPath)$($t.TaskName)" }
        $i = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
        $row = 'PROBE | {0,-22} | t+{1}s | State={2,-8} | Enabled={3,-5} | LastTaskResult=0x{4:X8} | instance_procs={5}' -f $Step, $off, $t.State, $t.Settings.Enabled, [uint32]$i.LastTaskResult, (Get-ProbeProcessCount)
    } else {
        $row = 'PROBE | {0,-22} | t+{1}s | State={2,-8} | Enabled={3,-5} | LastTaskResult={4,-10} | instance_procs={5}' -f $Step, $off, '<gone>', '-', '-', (Get-ProbeProcessCount)
    }
    $Rows.Add($row)
    [Console]::Out.WriteLine($row)
}
function Get-OtherTaskEnabledMap {
    $m = @{}
    foreach ($x in @(Get-ScheduledTask -ErrorAction SilentlyContinue)) {
        $full = "$($x.TaskPath)$($x.TaskName)"
        if ($full -ceq "$TaskPath$TaskName") { continue }
        $m[$full] = [string]$x.Settings.Enabled }
    return $m
}

$isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
[Console]::Out.WriteLine("PROBE-CONTEXT | host=$env:COMPUTERNAME | user=$env:USERNAME | elevated=$isElevated | logon=$LogonType | task=$TaskPath$TaskName")
[Console]::Out.WriteLine('PROBE | step                   | offset from Disable | State | Settings.Enabled | LastTaskResult | tagged powershell processes')
$before = $null
try {
    # 0. refusals
    Assert-ProbeIdentity
    $existing = @(Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue)
    if ($existing.Count) { $ExitCode = 2; throw "REFUSED: $TaskPath already holds $($existing.Count) task(s): $(($existing | ForEach-Object TaskName) -join ', ')" }
    if (@(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue).Count) { $ExitCode = 2; throw "REFUSED: a task named $TaskName already exists" }
    $before = Get-OtherTaskEnabledMap

    # 1. register (no trigger)
    $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action = New-ScheduledTaskAction -Execute $exe -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Sleep -Seconds 120; {0}"' -f $Tag)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType $LogonType -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Assert-ProbeIdentity
    $reg = Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action -Principal $principal -Settings $settings -Description 'Throwaway Scheduler semantics probe; removed by the same script.'
    $Registered = $true
    if ($reg.TaskName -cne $TaskName -or $reg.TaskPath -cne $TaskPath) { throw "register returned $($reg.TaskPath)$($reg.TaskName)" }
    Add-Readback 'registered'

    # 2. start, bounded wait for Running
    Assert-ProbeIdentity
    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $w0 = Get-Date
    while ([string](Get-ProbeTask).State -ne 'Running' -and ((Get-Date) - $w0).TotalSeconds -lt $RunningWaitSeconds) { Start-Sleep -Milliseconds 500 }
    if ([string](Get-ProbeTask).State -ne 'Running') { throw "task did not reach Running within $RunningWaitSeconds s" }
    Add-Readback 'running'

    # 3. disable while running; 4. read back at +0, +5, +30 s
    Assert-ProbeIdentity
    $dis = Disable-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $T0 = Get-Date
    if ($dis.TaskName -cne $TaskName -or $dis.TaskPath -cne $TaskPath) { throw "disable returned $($dis.TaskPath)$($dis.TaskName)" }
    Add-Readback 'disabled+0'
    $afterDisable = Get-ProbeTask
    $Notes.Add(('RESULT | disable_while_running | State={0} | Settings.Enabled={1} | instance_alive={2}' -f $afterDisable.State, $afterDisable.Settings.Enabled, ((Get-ProbeProcessCount) -gt 0)))
    while (((Get-Date) - $T0).TotalSeconds -lt 5) { Start-Sleep -Milliseconds 200 }
    Add-Readback 'disabled+5'
    while (((Get-Date) - $T0).TotalSeconds -lt 30) { Start-Sleep -Milliseconds 200 }
    Add-Readback 'disabled+30'
    $d30 = Get-ProbeTask
    $Notes.Add(('RESULT | disabled+30s | State={0} | Settings.Enabled={1} | instance_alive={2}' -f $d30.State, $d30.Settings.Enabled, ((Get-ProbeProcessCount) -gt 0)))

    # 5. stop; read back
    Assert-ProbeIdentity
    Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    $s0 = Get-Date
    Add-Readback 'stopped+0'
    while (((Get-Date) - $s0).TotalSeconds -lt 5) { Start-Sleep -Milliseconds 200 }
    Add-Readback 'stopped+5'
    $st = Get-ProbeTask
    $Notes.Add(('RESULT | after_stop | State={0} | Settings.Enabled={1} | instance_alive={2}' -f $st.State, $st.Settings.Enabled, ((Get-ProbeProcessCount) -gt 0)))
    $ExitCode = 0
}
catch {
    $msg = $_.Exception.Message
    if ($msg -notlike 'REFUSED*') { $msg = "ERROR: $msg" }
    $Notes.Add("PROBE-ERROR | $msg")
    if ($ExitCode -ne 2) { $ExitCode = 1 }
}
finally {
    # 6. cleanup: only ever our exact task; always attempted if anything may have been registered
    $gone = $true; $goneKnown = $false
    try {
        if ($ExitCode -ne 2) {
            Assert-ProbeIdentity
            if (Get-ProbeTask) {
                Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
            }
            $gone = -not (Get-ProbeTask); $goneKnown = $true
            Add-Readback 'unregistered'
            $Notes.Add("CLEANUP | unregister $TaskPath$TaskName | gone=$gone | instance_procs_left=$(Get-ProbeProcessCount) (a leftover ends by itself within 120 s)")
        }
    }
    catch { if (-not $goneKnown) { $gone = $false }; $Notes.Add("CLEANUP-ERROR | $($_.Exception.Message)") }   # a throw after the gone read-back keeps it
    # The other-tasks compare is a separate report: its error never turns a confirmed unregister into exit 3
    try {
        if ($ExitCode -ne 2 -and $null -ne $before) {
            $after = Get-OtherTaskEnabledMap
            $changed = @($before.Keys | Where-Object { $after.ContainsKey($_) -and $after[$_] -ne $before[$_] })
            $vanished = @($before.Keys | Where-Object { -not $after.ContainsKey($_) })
            $Notes.Add("OTHER-TASKS | compared=$($before.Count) | enabled_changed=$($changed.Count) [$($changed -join ', ')] | vanished=$($vanished.Count) [$($vanished -join ', ')]")
        }
    }
    catch { $Notes.Add("OTHER-TASKS-ERROR | compare not completed: $($_.Exception.Message) (reported separately; the exit code follows gone=$gone only)") }
    if (-not $gone) { $ExitCode = 3 }
    foreach ($n in $Notes) { [Console]::Out.WriteLine($n) }
    [Console]::Out.WriteLine("PROBE-SUMMARY | exit=$ExitCode | registered=$Registered | gone=$gone | task=$TaskPath$TaskName")
    $Host.SetShouldExit($ExitCode)
    exit $ExitCode
}
