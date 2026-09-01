<#
.SYNOPSIS
    Register one bounded one-date settlement attempt and one receipt-driven retry.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TargetDate,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')]
    [string]$AttemptId,
    [Parameter(Mandatory = $true)][string]$PrimaryAtLocal,
    [Parameter(Mandatory = $true)][string]$RetryAtLocal,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$primaryScript = (Resolve-Path -LiteralPath (
    Join-Path $RepoRoot 'scripts\ops\settlement_backfill_one.ps1'
) -ErrorAction Stop).Path
$retryScript = (Resolve-Path -LiteralPath (
    Join-Path $RepoRoot 'scripts\ops\settlement_backfill_retry_one.ps1'
) -ErrorAction Stop).Path
$contractScript = (Resolve-Path -LiteralPath (
    Join-Path $RepoRoot 'scripts\ops\training_window_contract.ps1'
) -ErrorAction Stop).Path
. $contractScript

function Parse-LocalTime([string]$Value, [string]$Label) {
    $parsed = [datetime]::MinValue
    $ok = [datetime]::TryParseExact(
        $Value,
        'yyyy-MM-ddTHH:mm:ss',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsed
    )
    if (-not $ok) { throw "$Label must use yyyy-MM-ddTHH:mm:ss local wall time" }
    return $parsed
}

$primaryAt = Parse-LocalTime $PrimaryAtLocal 'PrimaryAtLocal'
$retryAt = Parse-LocalTime $RetryAtLocal 'RetryAtLocal'
if ($primaryAt -le (Get-Date) -or $retryAt -le $primaryAt) {
    throw 'primary and retry triggers must be ordered future times'
}
if (($retryAt - $primaryAt).TotalMinutes -lt 30) {
    throw 'retry must be at least 30 minutes after the primary'
}
foreach ($row in @(
    @{ Label = 'primary'; Value = $primaryAt },
    @{ Label = 'retry'; Value = $retryAt }
)) {
    $minute = $row.Value.Hour * 60 + $row.Value.Minute
    if ($minute -lt 30 -or $minute -ge 9 * 60) {
        throw "$($row.Label) trigger must be inside 00:30-09:00"
    }
}

$dateToken = $TargetDate.Replace('-', '')
$primaryTaskName = "WeatherSettlementBackfill${dateToken}_$AttemptId"
$retryTaskName = "WeatherSettlementBackfillRetry${dateToken}_$AttemptId"
$sameDateTasks = @(
    Get-ScheduledTask -ErrorAction Stop |
        Where-Object {
            [string]$_.TaskName -match (
                '^WeatherSettlementBackfill(?:Retry)?' +
                [regex]::Escape($dateToken) + '_'
            )
        }
)
$now = Get-Date
$conflictingTasks = @(
    $sameDateTasks | Where-Object {
        if ([string]$_.State -eq 'Running') { return $true }
        $info = $_ | Get-ScheduledTaskInfo
        return $info.NextRunTime -gt $now
    }
)
if ($conflictingTasks.Count -gt 0) {
    throw "refusing an overlapping task pair for target date $TargetDate"
}
foreach ($taskName in @($primaryTaskName, $retryTaskName)) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        throw "refusing to replace existing task $taskName"
    }
}

$powerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$primaryTokens = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $primaryScript,
    '-TargetDate', $TargetDate,
    '-Refetch',
    '-RepoRoot', $RepoRoot
)
$retryTokens = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $retryScript,
    '-TargetDate', $TargetDate,
    '-PrimaryTaskName', $primaryTaskName,
    '-RepoRoot', $RepoRoot
)
$primaryArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $primaryTokens
$retryArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $retryTokens
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8 -Minutes 30) `
    -MultipleInstances IgnoreNew -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$primaryAction = New-ScheduledTaskAction `
    -Execute $powerShell -Argument $primaryArguments -WorkingDirectory $RepoRoot
$retryAction = New-ScheduledTaskAction `
    -Execute $powerShell -Argument $retryArguments -WorkingDirectory $RepoRoot
$primaryTrigger = New-ScheduledTaskTrigger -Once -At $primaryAt
$retryTrigger = New-ScheduledTaskTrigger -Once -At $retryAt

Register-ScheduledTask -TaskName $primaryTaskName -Action $primaryAction `
    -Trigger $primaryTrigger -Settings $settings -Principal $principal `
    -Description "One-date bounded settlement backfill for $TargetDate; no late catch-up." |
    Out-Null
try {
    Register-ScheduledTask -TaskName $retryTaskName -Action $retryAction `
        -Trigger $retryTrigger -Settings $settings -Principal $principal `
        -Description "One receipt-driven retry for settlement backfill $TargetDate; no loop or late catch-up." |
        Out-Null
}
catch {
    Disable-ScheduledTask -TaskName $primaryTaskName -ErrorAction SilentlyContinue |
        Out-Null
    throw
}

function Assert-TaskBinding {
    param(
        [string]$TaskName,
        [string]$ExpectedArguments,
        [datetime]$ExpectedAt
    )
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $actions = @($task.Actions)
    $triggers = @($task.Triggers)
    $valid = (
        [string]$task.State -ceq 'Ready' -and
        [string]$task.Principal.LogonType -ceq 'S4U' -and
        [string]$task.Principal.RunLevel -ceq 'Limited' -and
        $actions.Count -eq 1 -and
        [string]$actions[0].Execute -ieq $powerShell -and
        [string]$actions[0].Arguments -ceq $ExpectedArguments -and
        [IO.Path]::GetFullPath([string]$actions[0].WorkingDirectory) -ieq $RepoRoot -and
        $triggers.Count -eq 1 -and
        [datetime]$triggers[0].StartBoundary -eq $ExpectedAt -and
        -not [bool]$task.Settings.StartWhenAvailable -and
        [bool]$task.Settings.WakeToRun -and
        [string]$task.Settings.ExecutionTimeLimit -ceq 'PT8H30M' -and
        [int]$task.Settings.RestartCount -eq 0 -and
        [string]$task.Settings.MultipleInstances -ceq 'IgnoreNew'
    )
    if (-not $valid) { throw "task readback mismatch: $TaskName" }
}

try {
    Assert-TaskBinding $primaryTaskName $primaryArguments $primaryAt
    Assert-TaskBinding $retryTaskName $retryArguments $retryAt
}
catch {
    Disable-ScheduledTask -TaskName $primaryTaskName -ErrorAction SilentlyContinue |
        Out-Null
    Disable-ScheduledTask -TaskName $retryTaskName -ErrorAction SilentlyContinue |
        Out-Null
    throw
}

[pscustomobject]@{
    target_date = $TargetDate
    primary_task = $primaryTaskName
    primary_at_local = $primaryAt.ToString('s')
    retry_task = $retryTaskName
    retry_at_local = $retryAt.ToString('s')
    start_when_available = $false
    retry_loop = $false
} | ConvertTo-Json -Depth 4
