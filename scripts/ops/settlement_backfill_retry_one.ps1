<#
.SYNOPSIS
    Retry one failed or missed one-date settlement backfill exactly once.

.DESCRIPTION
    This is a receipt-driven successor, not a loop. It skips an already settled
    date, refuses ambiguous primary evidence, and otherwise invokes the canonical
    settlement_backfill_one.ps1 once. The inner recovery path still owns the
    heavy-work window, workload lease, Job containment, 09:00 hard stop, lock
    repair, and all-market outcome verification.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$TargetDate,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^WeatherSettlementBackfill\d{8}_[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')]
    [string]$PrimaryTaskName,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')]
    [string]$AttemptId,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$parsedTarget = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
    $TargetDate,
    'yyyy-MM-dd',
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::None,
    [ref]$parsedTarget
)) {
    throw 'TargetDate must be a real calendar date in yyyy-MM-dd form'
}
$dateToken = $TargetDate.Replace('-', '')
$expectedPrimaryTaskName = "WeatherSettlementBackfill${dateToken}_$AttemptId"
if ($PrimaryTaskName -cne $expectedPrimaryTaskName) {
    throw 'PrimaryTaskName does not match TargetDate and AttemptId'
}
$alerts = Join-Path $RepoRoot 'data\alerts'
if (-not (Test-Path -LiteralPath $alerts -PathType Container)) {
    New-Item -ItemType Directory -Path $alerts -Force | Out-Null
}
$primaryReceiptPath = Join-Path $alerts "settlement_backfill_${TargetDate}_$AttemptId.json"
$retryReceiptPath = Join-Path $alerts "settlement_backfill_retry_${TargetDate}_$AttemptId.json"
$backfillScript = Join-Path $RepoRoot 'scripts\ops\settlement_backfill_one.ps1'
$contractScript = Join-Path $RepoRoot 'scripts\ops\training_window_contract.ps1'

function Emit-RetryReceipt {
    param([string]$State, [string]$Detail, [int]$ExitCode, $PrimaryReceipt)
    $payload = [ordered]@{
        schema_version = 'settlement_backfill_retry_receipt_v0.1'
        target_date = $TargetDate
        attempt_id = $AttemptId
        state = $State
        detail = $Detail
        exit_code = $ExitCode
        primary_task_name = $PrimaryTaskName
        primary_receipt_path = $primaryReceiptPath
        primary_receipt_state = if ($null -ne $PrimaryReceipt) {
            [string]$PrimaryReceipt.state
        } else { $null }
        at_local = (Get-Date).ToString('o')
    }
    $temporaryReceiptPath = "{0}.{1}.{2}.tmp" -f `
        $retryReceiptPath, $PID, ([guid]::NewGuid().ToString('N'))
    try {
        $payload | ConvertTo-Json -Depth 5 | Set-Content `
            -LiteralPath $temporaryReceiptPath -Encoding utf8
        Move-Item -LiteralPath $temporaryReceiptPath `
            -Destination $retryReceiptPath -Force -ErrorAction Stop
    }
    finally {
        if (Test-Path -LiteralPath $temporaryReceiptPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryReceiptPath -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Output "[$State] $TargetDate - $Detail"
}

if (-not (Test-Path -LiteralPath $backfillScript -PathType Leaf)) {
    Emit-RetryReceipt 'REFUSED' 'canonical one-date backfill script is absent' 2 $null
    exit 2
}
if (-not (Test-Path -LiteralPath $contractScript -PathType Leaf)) {
    Emit-RetryReceipt 'REFUSED' 'scheduled-task argument contract is absent' 2 $null
    exit 2
}
. $contractScript

$powerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$expectedPrimaryTokens = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $backfillScript,
    '-TargetDate', $TargetDate,
    '-Refetch',
    '-AttemptId', $AttemptId,
    '-PrimaryTaskName', $PrimaryTaskName,
    '-RepoRoot', $RepoRoot
)
$expectedPrimaryArguments = ConvertTo-ScheduledTaskArgumentString `
    -Tokens $expectedPrimaryTokens

$tasks = @(Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction SilentlyContinue)
if ($tasks.Count -ne 1) {
    Emit-RetryReceipt 'REFUSED' 'primary task identity is absent or ambiguous' 2 $null
    exit 2
}
$primaryTask = $tasks[0]
$primaryAction = @($primaryTask.Actions)
if (
    $primaryAction.Count -ne 1 -or
    [string]$primaryAction[0].Execute -ine $powerShell -or
    [string]$primaryAction[0].Arguments -cne $expectedPrimaryArguments -or
    [IO.Path]::GetFullPath([string]$primaryAction[0].WorkingDirectory) -ine $RepoRoot
) {
    Emit-RetryReceipt 'REFUSED' 'primary task action is not the exact target-date backfill' 2 $null
    exit 2
}
$primaryState = [string]$primaryTask.State
if ($primaryState -eq 'Running') {
    Emit-RetryReceipt 'REFUSED_PRIMARY_RUNNING' 'primary task still owns its attempt' 3 $null
    exit 3
}
if ($primaryState -notin @('Ready', 'Disabled')) {
    Emit-RetryReceipt 'REFUSED' "primary task state is ambiguous: $primaryState" 2 $null
    exit 2
}

$primaryInfo = $primaryTask | Get-ScheduledTaskInfo
$primaryRan = $primaryInfo.LastRunTime -gt [datetime]'2000-01-01'
if (-not $primaryRan -and $primaryInfo.NextRunTime -gt (Get-Date)) {
    Emit-RetryReceipt 'REFUSED' 'primary task is still due and cannot overlap its successor' 2 $null
    exit 2
}

function Test-PrimaryReceiptBinding {
    param($Receipt)
    return (
        $null -ne $Receipt -and
        [string]$Receipt.schema_version -ceq 'settlement_backfill_receipt_v0.2' -and
        [string]$Receipt.target_date -ceq $TargetDate -and
        [string]$Receipt.attempt_id -ceq $AttemptId -and
        [string]$Receipt.primary_task_name -ceq $PrimaryTaskName -and
        [bool]$Receipt.refetch
    )
}

function Test-ReceiptStartedAfter {
    param($Receipt, [datetime]$NotBefore)
    $started = [DateTimeOffset]::MinValue
    if (-not [DateTimeOffset]::TryParse(
        [string]$Receipt.attempt_started_at_local,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$started
    )) {
        return $false
    }
    return $started.LocalDateTime -ge $NotBefore.AddSeconds(-2)
}

function Test-AllMarketSettledReceipt {
    param($Receipt)
    if (-not (Test-PrimaryReceiptBinding -Receipt $Receipt)) { return $false }
    foreach ($field in @(
        'expected_market_count',
        'expected_market_ids',
        'markets_total',
        'markets_settled',
        'markets_unsettled',
        'missing_ledger_markets'
    )) {
        if ($null -eq $Receipt.PSObject.Properties[$field]) { return $false }
    }
    $expectedCount = 0
    $marketTotal = 0
    $marketsSettled = 0
    if (
        -not [int]::TryParse([string]$Receipt.expected_market_count, [ref]$expectedCount) -or
        -not [int]::TryParse([string]$Receipt.markets_total, [ref]$marketTotal) -or
        -not [int]::TryParse([string]$Receipt.markets_settled, [ref]$marketsSettled)
    ) {
        return $false
    }
    $marketIds = @($Receipt.expected_market_ids | ForEach-Object { ([string]$_).Trim() })
    $uniqueMarketIds = @($marketIds | Sort-Object -Unique)
    return (
        [string]$Receipt.state -ceq 'SETTLED' -and
        $expectedCount -gt 0 -and
        $marketTotal -eq $expectedCount -and
        $marketsSettled -eq $expectedCount -and
        $marketIds.Count -eq $expectedCount -and
        $uniqueMarketIds.Count -eq $expectedCount -and
        @($marketIds | Where-Object { $_ -notmatch '^[a-z0-9][a-z0-9-]*$' }).Count -eq 0 -and
        @($Receipt.markets_unsettled).Count -eq 0 -and
        @($Receipt.missing_ledger_markets).Count -eq 0
    )
}

$primaryReceipt = $null
if (Test-Path -LiteralPath $primaryReceiptPath -PathType Leaf) {
    try {
        $primaryReceipt = Get-Content -LiteralPath $primaryReceiptPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Emit-RetryReceipt 'REFUSED' 'primary receipt is unreadable' 2 $null
        exit 2
    }
    if (-not (Test-PrimaryReceiptBinding -Receipt $primaryReceipt)) {
        Emit-RetryReceipt 'REFUSED' 'primary receipt is not bound to this exact task attempt' 2 $primaryReceipt
        exit 2
    }
    if (-not $primaryRan) {
        Emit-RetryReceipt 'REFUSED' 'primary receipt exists without correlated task-run evidence' 2 $primaryReceipt
        exit 2
    }
    if (
        (Get-Item -LiteralPath $primaryReceiptPath).LastWriteTime -lt
            $primaryInfo.LastRunTime.AddSeconds(-2) -or
        -not (Test-ReceiptStartedAfter -Receipt $primaryReceipt -NotBefore $primaryInfo.LastRunTime)
    ) {
        Emit-RetryReceipt 'REFUSED' 'primary receipt predates this task attempt' 2 $primaryReceipt
        exit 2
    }
    if (Test-AllMarketSettledReceipt -Receipt $primaryReceipt) {
        Emit-RetryReceipt 'SKIPPED_ALREADY_SETTLED' 'primary attempt already proved all markets settled' 0 $primaryReceipt
        exit 0
    }
    $retryableStates = @('REFUSED', 'CHAIN_FAILED', 'SILENT_NOOP', 'PARTIAL')
    if ([string]$primaryReceipt.state -cnotin $retryableStates) {
        Emit-RetryReceipt 'REFUSED' 'primary receipt state is not retryable' 2 $primaryReceipt
        exit 2
    }
}
else {
    if ($primaryRan) {
        Emit-RetryReceipt 'REFUSED' 'primary task ran but emitted no receipt' 2 $null
        exit 2
    }
}

$retryStartedAt = Get-Date
& $powerShell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File $backfillScript -TargetDate $TargetDate -Refetch `
    -AttemptId $AttemptId -PrimaryTaskName $PrimaryTaskName -RepoRoot $RepoRoot
$backfillExit = [int]$LASTEXITCODE

$finalReceipt = $null
if (Test-Path -LiteralPath $primaryReceiptPath -PathType Leaf) {
    try {
        $finalReceipt = Get-Content -LiteralPath $primaryReceiptPath -Raw |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch { $finalReceipt = $null }
}
if (
    $backfillExit -eq 0 -and
    $null -ne $finalReceipt -and
    (Get-Item -LiteralPath $primaryReceiptPath).LastWriteTime -ge
        $retryStartedAt.AddSeconds(-2) -and
    (Test-ReceiptStartedAfter -Receipt $finalReceipt -NotBefore $retryStartedAt) -and
    (Test-AllMarketSettledReceipt -Receipt $finalReceipt)
) {
    Emit-RetryReceipt 'SETTLED' 'explicit retry proved all markets settled' 0 $finalReceipt
    exit 0
}

Emit-RetryReceipt 'RETRY_FAILED' "retry exited $backfillExit without a SETTLED receipt" 1 $finalReceipt
exit 1
