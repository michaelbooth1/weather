# Re-sets only the calendar (daily/weekly) triggers of ONE existing scheduled task to
# local wall-clock StartBoundaries (DST audit 2026-10-07, DST-C1; owner decision OD28).
#
# For tasks with no repository registrar (WeatherStalenessSweep,
# WeatherStreakCaptureMonitor), or when a registrar cannot be re-run with known
# parameters. The task's action, principal, settings, non-calendar triggers and
# each trigger's repetition (interval and duration) are left exactly as they are:
# only the zone suffix of each calendar StartBoundary is removed, keeping the
# literal wall-clock date and time that was registered.
#
# A host task saved in daylight time reads e.g. "2026-09-30T08:10:00-04:00"; its
# literal wall time (08:10) is the intended local time, and the result is
# "2026-09-30T08:10:00". A "Z" boundary is refused: its literal time is UTC, not
# the intended wall time.
#
# -ExpectedAt lists the intended local HH:mm of every calendar trigger in trigger
# order, so a wrong task or a surprising trigger is refused before anything changes.
# Without -Apply it prints the plan and changes nothing. Production operator only:
#   .\scripts\ops\reset_daily_trigger_local.ps1 -TaskName WeatherStalenessSweep -ExpectedAt 08:10
#   .\scripts\ops\reset_daily_trigger_local.ps1 -TaskName WeatherStalenessSweep -ExpectedAt 08:10 -Apply

param(
    [Parameter(Mandatory = $true)][ValidatePattern('^Weather[A-Za-z0-9_-]+$')][string]$TaskName,
    [Parameter(Mandatory = $true)][string[]]$ExpectedAt,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "scheduled_task_local_trigger.ps1")

$calendarClasses = @("MSFT_TaskDailyTrigger", "MSFT_TaskWeeklyTrigger")
$otherCalendarClasses = @("MSFT_TaskMonthlyTrigger", "MSFT_TaskMonthlyDOWTrigger")
foreach ($at in $ExpectedAt) {
    if ($at -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$') { throw "-ExpectedAt '$at' is not HH:mm" }
}

function Get-WeatherSingleTask([string]$Name) {
    $found = @(Get-ScheduledTask -TaskName $Name -ErrorAction Stop)
    if ($found.Count -ne 1) { throw "expected exactly one task named '$Name', found $($found.Count)" }
    return $found[0]
}

$task = Get-WeatherSingleTask $TaskName
$triggers = @($task.Triggers)
$calendarIndexes = @()
for ($i = 0; $i -lt $triggers.Count; $i++) {
    $class = [string]$triggers[$i].CimClass.CimClassName
    if ($otherCalendarClasses -contains $class) { throw "trigger $i of '$TaskName' is $class; not handled here" }
    if ($calendarClasses -contains $class) { $calendarIndexes += $i }
}
if ($calendarIndexes.Count -ne $ExpectedAt.Count) {
    throw "'$TaskName' has $($calendarIndexes.Count) calendar trigger(s); -ExpectedAt names $($ExpectedAt.Count)"
}

$rows = @()
$changes = 0
for ($k = 0; $k -lt $calendarIndexes.Count; $k++) {
    $trigger = $triggers[$calendarIndexes[$k]]
    $before = [string]$trigger.StartBoundary
    $match = [regex]::Match($before, '^(?<date>\d{4}-\d{2}-\d{2})T(?<hm>\d{2}:\d{2}):00(\.0+)?(?<zone>Z|[+-]\d{2}:\d{2})?$')
    if (-not $match.Success) { throw "trigger $($calendarIndexes[$k]) of '$TaskName' has an unreadable StartBoundary '$before'" }
    if ($match.Groups['zone'].Value -eq 'Z') {
        throw "trigger $($calendarIndexes[$k]) of '$TaskName' is a UTC ('Z') boundary '$before'; its literal time is not the wall time. Re-create it instead."
    }
    if ($match.Groups['hm'].Value -cne $ExpectedAt[$k]) {
        throw "trigger $($calendarIndexes[$k]) of '$TaskName' is registered at $($match.Groups['hm'].Value), not the expected $($ExpectedAt[$k])"
    }
    $after = "{0}T{1}:00" -f $match.Groups['date'].Value, $match.Groups['hm'].Value
    if ($after -cne $before) { $changes++ }
    $rows += [pscustomobject]@{
        index = $calendarIndexes[$k]
        class = [string]$trigger.CimClass.CimClassName
        before = $before
        after = $after
        repetition_interval = [string]$trigger.Repetition.Interval
        repetition_duration = [string]$trigger.Repetition.Duration
    }
    $trigger.StartBoundary = $after
}

$plan = [pscustomobject]@{ task = $TaskName; apply = [bool]$Apply; changes = $changes; triggers = $rows }
$plan | ConvertTo-Json -Compress -Depth 4 | Write-Output

if ($changes -eq 0) {
    Write-Host "'$TaskName': every calendar trigger is already local; nothing to change."
    exit 0
}
if (-not $Apply) {
    Write-Host "'$TaskName': dry run, nothing changed. Re-run with -Apply to set $changes trigger(s)."
    exit 0
}

Set-ScheduledTask -TaskName $TaskName -Trigger $triggers -ErrorAction Stop | Out-Null

$readback = Get-WeatherSingleTask $TaskName
$readTriggers = @($readback.Triggers)
if ($readTriggers.Count -ne $triggers.Count) { throw "'$TaskName' read back $($readTriggers.Count) trigger(s), expected $($triggers.Count)" }
for ($k = 0; $k -lt $rows.Count; $k++) {
    $row = $rows[$k]
    $t = $readTriggers[$row.index]
    if (-not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$t.StartBoundary) -At $ExpectedAt[$k])) {
        throw "trigger $($row.index) of '$TaskName' read back '$($t.StartBoundary)', not a local boundary"
    }
    if ([string]$t.Repetition.Interval -cne $row.repetition_interval -or [string]$t.Repetition.Duration -cne $row.repetition_duration) {
        throw "trigger $($row.index) of '$TaskName' changed its repetition on read-back"
    }
}
Write-Host "'$TaskName': $changes calendar trigger(s) now local; action, principal, settings and repetition unchanged."
exit 0
