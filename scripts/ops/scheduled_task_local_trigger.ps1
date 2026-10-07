# Local wall-clock daily Scheduler triggers (DST audit 2026-10-07, finding DST-C1).
#
# Dot-source only. `New-ScheduledTaskTrigger -Daily -At` stores StartBoundary as a
# UTC instant ("...Z" in memory; Task Scheduler saves it with the registering
# day's fixed offset, e.g. "-04:00"). A zoned boundary pins a fixed UTC instant,
# so a task registered in daylight time fires one hour earlier on the local
# clock after the fall-back (2026-11-01) and one hour later after spring-forward.
# An unzoned boundary ("yyyy-MM-ddTHH:mm:ss") is local time: the task follows the
# wall clock across both transitions ("Synchronize across time zones" off).
#
# Every daily registrar under scripts/ops builds its trigger with
# New-WeatherLocalDailyTrigger and reads it back with
# Test-WeatherLocalDailyStartBoundary, which refuses any zoned boundary.
# `tests/operations/test_scheduled_task_local_daily_triggers.py` ratchets both.
# Interval triggers (-Once -RepetitionInterval) and run-specific one-shots are
# exact instants by design and are not built here.

function ConvertTo-WeatherLocalStartBoundary {
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
        [string]$At
    )
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $time = [TimeSpan]::ParseExact($At, 'hh\:mm', $culture)
    return (Get-Date).Date.Add($time).ToString('yyyy-MM-ddTHH:mm:ss', $culture)
}

function New-WeatherLocalDailyTrigger {
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
        [string]$At
    )
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    $trigger.StartBoundary = ConvertTo-WeatherLocalStartBoundary -At $At
    if (-not (Test-WeatherLocalDailyStartBoundary -StartBoundary ([string]$trigger.StartBoundary) -At $At)) {
        throw "daily trigger for $At did not keep a local (unzoned) StartBoundary: $($trigger.StartBoundary)"
    }
    return $trigger
}

function Test-WeatherLocalDailyStartBoundary {
    # True only for an unzoned local boundary at exactly $At. A "Z" or "+hh:mm"/"-hh:mm"
    # suffix is a fixed UTC instant and is refused even when its wall time matches:
    # ([datetime]'2026-10-01T00:30:00-04:00').ToString('HH:mm') reads "00:30" in EDT
    # and would hide the DST-C1 defect from a [datetime] read-back.
    param(
        [AllowEmptyString()][AllowNull()][string]$StartBoundary,
        [Parameter(Mandatory = $true)][string]$At
    )
    if ([string]::IsNullOrWhiteSpace($StartBoundary)) { return $false }
    $match = [regex]::Match($StartBoundary, '^\d{4}-\d{2}-\d{2}T(?<hm>\d{2}:\d{2}):00$')
    return ($match.Success -and $match.Groups['hm'].Value -ceq $At)
}
