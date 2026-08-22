<#
.SYNOPSIS
    Back-fill settlement for exactly ONE date, with fail-closed guards.

.DESCRIPTION
    The settlement chain died at step 4 from 2026-08-04 to 2026-08-08, leaving
    2026-08-05..07 unsettled. Each chain run settles only yesterday, so those dates
    need explicit resumes and will never heal themselves.

    ONE date per invocation, deliberately. Looping three multi-hour, memory-hungry
    resumes unattended converts one failure into three, and each resume re-runs its
    step and everything after it.

    Fail-closed guards, checked BEFORE anything heavy starts:
      1. the benign-capture-race fix must actually be on disk. Without it the resume
         dies at public_wu_settlement_restore exactly as the daily chain has been.
      2. canonical lock diagnostics repair only a verified-stale owner and refuse
         a live or unverifiable owner. File existence and PID alone are not ownership.
      3. the repository 00:30-09:00 heavy-work window is enforced by
         chain_recovery_run.ps1, which this delegates to rather than reimplementing.
      4. the daily refresh exits normally immediately after
         market_day_labels_finalize, so Python finally blocks release both locks.

    EXIT 0 IS NOT EVIDENCE OF A SETTLED DATE. Dates poisoned by the 404 outage are
    stamped treated_as_source_unavailable, and a resume without -Refetch subtracts
    them, fetches nothing, and exits 0. So this verifies the outcome afterwards
    instead of trusting the exit code.

.PARAMETER TargetDate
    yyyy-MM-dd. One date. No ranges.

.PARAMETER Refetch
    REQUIRED for 2026-08-05 and 2026-08-06, which carry
    treated_as_source_unavailable=true from the advertising-key 404s.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$TargetDate,
    [switch]$Refetch,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
Set-Location -LiteralPath $RepoRoot

$parsedTarget = [datetime]::MinValue
$validTarget = [datetime]::TryParseExact(
    $TargetDate,
    'yyyy-MM-dd',
    [System.Globalization.CultureInfo]::InvariantCulture,
    [System.Globalization.DateTimeStyles]::None,
    [ref]$parsedTarget
)
if (-not $validTarget) {
    throw "TargetDate must be a real calendar date in yyyy-MM-dd form"
}

$stamp = "$(Get-Date -Format 'yyyyMMddTHHmmssfff')-$PID"
$logDir = Join-Path $RepoRoot 'data\alerts'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$resultPath = Join-Path $logDir "settlement_backfill_$TargetDate.json"
$registryOut = Join-Path $logDir "settlement_backfill_market_registry_$TargetDate-$stamp.json"
$registryErr = Join-Path $logDir "settlement_backfill_market_registry_$TargetDate-$stamp.err"

function Emit($state, $detail, $extra) {
    $payload = [ordered]@{
        target_date = $TargetDate
        state       = $state
        detail      = $detail
        refetch     = [bool]$Refetch
        at_local    = (Get-Date).ToString('s')
    }
    if ($extra) { foreach ($k in $extra.Keys) { $payload[$k] = $extra[$k] } }
    $payload | ConvertTo-Json -Depth 6 | Out-File -FilePath $resultPath -Encoding utf8
    "[$state] $TargetDate - $detail"
}

# --- Guard 1: the chain fix must be on disk -------------------------------------
$lifetime = Join-Path $RepoRoot 'src\weather\operations\windows_process_lifetime.py'
if (-not (Select-String -Path $lifetime -Pattern 'no_unexplained_capture_failures' -Quiet)) {
    Emit 'REFUSED' 'benign-capture-race fix is not on disk; the resume would die at step 4 exactly as the daily chain does' $null
    exit 2
}

# --- Guard 2: discover the exact fleet from the canonical current-repo registry --
# Runtime settlement directories are evidence locations, not market authority. A
# missing directory must become an explicit missing-ledger failure rather than
# silently shrinking the denominator.
$python = Join-Path $RepoRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Emit 'REFUSED' "project interpreter is absent at $python" @{
        market_registry_discovery = $registryOut
    }
    exit 2
}
$registryCode = "import json,weather.market.market_registry as m;print(json.dumps({'schema_version':'settlement_backfill_market_registry_discovery_v0.1','module_file':m.__file__,'market_ids':sorted(s.id for s in m.all_specs())}))"
$registryProcess = Start-Process -FilePath $python `
    -ArgumentList @('-c', $registryCode) `
    -WorkingDirectory $RepoRoot `
    -NoNewWindow -PassThru -Wait `
    -RedirectStandardOutput $registryOut `
    -RedirectStandardError $registryErr
if ($registryProcess.ExitCode -ne 0) {
    Emit 'REFUSED' "authoritative market-registry discovery exited $($registryProcess.ExitCode)" @{
        market_registry_discovery = $registryOut
        market_registry_error = $registryErr
    }
    exit 2
}
try {
    $registry = Get-Content -LiteralPath $registryOut -Raw | ConvertFrom-Json
    $observedModule = (Resolve-Path -LiteralPath ([string]$registry.module_file) -ErrorAction Stop).Path
    $expectedModule = (Resolve-Path -LiteralPath (Join-Path $RepoRoot 'src\weather\market\market_registry.py') -ErrorAction Stop).Path
    $rawMarketIds = @($registry.market_ids)
    $expectedMarketIds = @(
        $rawMarketIds |
            ForEach-Object { ([string]$_).Trim() } |
            Sort-Object
    )
    $uniqueMarketIds = @($expectedMarketIds | Sort-Object -Unique)
    $registryValid = (
        $registry.schema_version -eq 'settlement_backfill_market_registry_discovery_v0.1' -and
        $observedModule -eq $expectedModule -and
        $expectedMarketIds.Count -gt 0 -and
        $uniqueMarketIds.Count -eq $expectedMarketIds.Count -and
        @($expectedMarketIds | Where-Object { $_ -notmatch '^[a-z0-9][a-z0-9-]*$' }).Count -eq 0
    )
}
catch {
    $registryValid = $false
    $expectedMarketIds = @()
}
if (-not $registryValid) {
    Emit 'REFUSED' 'authoritative market-registry discovery was empty, invalid, duplicated, or imported from another checkout' @{
        market_registry_discovery = $registryOut
        expected_market_ids = $expectedMarketIds
        expected_market_count = $expectedMarketIds.Count
    }
    exit 2
}
$missingLedgerMarketsBefore = @(
    $expectedMarketIds | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $RepoRoot "data\settlements\$_\ledger.jsonl") -PathType Leaf)
    }
)

function Get-SharedLineCount {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0 }
    $count = 0
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        try { while ($null -ne $reader.ReadLine()) { $count += 1 } }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
    return $count
}

# --- Baseline, captured before the run so the outcome check means something ------
$ledger = Join-Path $RepoRoot 'data\settlements\toronto\ledger.jsonl'
$ledgerBefore = Get-SharedLineCount -Path $ledger

"backfill $TargetDate starting (refetch=$($Refetch.IsPresent)); ledger rows before = $ledgerBefore"

# --- Run. chain_recovery_run.ps1 owns the 12:00-18:00 refusal -------------------
$chainArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $RepoRoot 'scripts\ops\chain_recovery_run.ps1'),
    '-ResumeFrom', 'public_wu_settlement_restore',
    '-TargetDate', $TargetDate,
    '-StopAfter', 'market_day_labels_finalize'
)
if ($Refetch) { $chainArgs += '-Refetch' }

& powershell.exe @chainArgs
$chainExit = $LASTEXITCODE

if ($chainExit -ne 0) {
    Emit 'CHAIN_FAILED' "chain_recovery_run exited $chainExit; do NOT start the next date" @{
        chain_exit_code = $chainExit
        expected_market_ids = $expectedMarketIds
        expected_market_count = $expectedMarketIds.Count
        missing_ledger_markets = $missingLedgerMarketsBefore
        market_registry_discovery = $registryOut
    }
    exit 1
}

# --- Verify the OUTCOME, not the exit code --------------------------------------
# A date STRING appearing in the ledger is NOT settlement. An unsettled day is still
# WRITTEN to the ledger, as a row carrying settlement_source='none' and
# settlement_high=null -- so the old presence check reported SETTLED on precisely the
# failure it exists to catch. On 2026-08-11 it stamped SETTLED for 2026-08-06 while
# recording ledger_grew=false in the same artifact, and the identical presence check
# also returns true for 08-08 and 08-10, neither of which is settled.
#
# Verify the CONTENT of the target date's newest row, in EVERY market ledger, so the
# check can say what it actually counted rather than that it found a substring.

function Get-TargetRow {
    param([string]$LedgerPath, [string]$Date)
    if (-not (Test-Path $LedgerPath)) { return $null }
    $row = $null
    # Share ReadWrite explicitly. [System.IO.File]::ReadLines() opens with FileShare.Read, which
    # BLOCKS WRITERS -- on 2026-08-11 a read loop over the 12 ledgers using it collided with the
    # chain's market_day_labels_finalize and failed that step with
    # "[Errno 13] Permission denied: data\settlements\austin\ledger.jsonl". A diagnostic read must
    # never be able to fail a production write.
    $stream = [System.IO.File]::Open(
        $LedgerPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        try {
            while ($null -ne ($line = $reader.ReadLine())) {
                if ($line -notlike "*$Date*") { continue }
                try { $obj = $line | ConvertFrom-Json } catch { continue }
                # Revisions append, so the LAST matching row is the live verdict.
                if ($obj.target_date -eq $Date) { $row = $obj }
            }
        }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
    return $row
}

function Test-RowSettled {
    param($Row)
    if ($null -eq $Row) { return $false }
    $source = "$($Row.settlement_source)".Trim().ToLowerInvariant()
    if ($source -ne 'daily_summary') { return $false }
    $settlementHigh = 0.0
    $parsed = [double]::TryParse(
        "$($Row.settlement_high)",
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$settlementHigh
    )
    return (
        $parsed -and
        -not [double]::IsNaN($settlementHigh) -and
        -not [double]::IsInfinity($settlementHigh)
    )
}

$ledgerAfter = Get-SharedLineCount -Path $ledger
$ledgerGrew = $ledgerAfter -gt $ledgerBefore
$missingLedgerMarkets = @(
    $expectedMarketIds | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $RepoRoot "data\settlements\$_\ledger.jsonl") -PathType Leaf)
    }
)

$settledMarkets = @()
$unsettledMarkets = @()
foreach ($marketId in $expectedMarketIds) {
    $row = Get-TargetRow `
        -LedgerPath (Join-Path $RepoRoot "data\settlements\$marketId\ledger.jsonl") `
        -Date $TargetDate
    if (Test-RowSettled -Row $row) { $settledMarkets += $marketId }
    else { $unsettledMarkets += $marketId }
}
$marketTotal = $expectedMarketIds.Count
$datePresent = $null -ne (Get-TargetRow -LedgerPath $ledger -Date $TargetDate)

$extra = @{
    chain_exit_code    = $chainExit
    ledger_rows_before = $ledgerBefore
    ledger_rows_after  = $ledgerAfter
    ledger_grew        = $ledgerGrew
    markets_settled    = $settledMarkets.Count
    markets_total      = $marketTotal
    markets_unsettled  = $unsettledMarkets
    expected_market_ids = $expectedMarketIds
    expected_market_count = $expectedMarketIds.Count
    missing_ledger_markets = $missingLedgerMarkets
    missing_ledger_markets_before = $missingLedgerMarketsBefore
    market_registry_discovery = $registryOut
    # Kept ONLY to show that the old signal is worthless on its own: it is true for
    # every unsettled date too. Never branch on it.
    target_date_present_substring = $datePresent
}

if ($settledMarkets.Count -eq 0) {
    Emit 'SILENT_NOOP' "chain exited 0 but $TargetDate has authoritative daily_summary settlement in 0 of $marketTotal market ledgers; the ledger grew by $($ledgerAfter - $ledgerBefore) row(s). Either the heavy step was deferred (check the run's admission blockers for host_commit_above_limit) or this is the treated_as_source_unavailable trap -- re-run with -Refetch when host commit is under 70%." $extra
    exit 1
}
if ($settledMarkets.Count -lt $marketTotal) {
    Emit 'PARTIAL' "only $($settledMarkets.Count) of $marketTotal markets settled for $TargetDate; still unsettled: $($unsettledMarkets -join ', '). Do NOT start the next date." $extra
    exit 1
}

Emit 'SETTLED' "$($settledMarkets.Count) of $marketTotal markets carry authoritative daily_summary settlement for $TargetDate; ledger grew by $($ledgerAfter - $ledgerBefore) row(s). Re-run streak.ps1 and confirm Toronto did not regrade before starting the next date." $extra
exit 0
