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
      2. no other chain run may hold the daily-refresh lock.
      3. the 12:00-18:00 graded window refusal is enforced by chain_recovery_run.ps1,
         which this delegates to rather than reimplementing.

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
    [Parameter(Mandatory = $true)][string]$TargetDate,
    [switch]$Refetch,
    [string]$RepoRoot = 'C:\Users\micha\Desktop\github\weather'
)

$ErrorActionPreference = 'Stop'
Set-Location $RepoRoot

$stamp = (Get-Date).ToString('yyyyMMddTHHmmss')
$logDir = Join-Path $RepoRoot 'data\alerts'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
$resultPath = Join-Path $logDir "settlement_backfill_$TargetDate.json"

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

# --- Guard 2: no other chain run in flight ---------------------------------------
$lock = Join-Path $RepoRoot 'data\backtest\daily_refresh.lock'
if (Test-Path $lock) {
    Emit 'REFUSED' "daily_refresh.lock is held; another chain run is in flight. Refusing rather than contending for memory on a 16 GB capture host." $null
    exit 2
}

# --- Baseline, captured before the run so the outcome check means something ------
$ledger = Join-Path $RepoRoot 'data\settlements\toronto\ledger.jsonl'
$ledgerBefore = if (Test-Path $ledger) { (Get-Content $ledger).Count } else { 0 }

"backfill $TargetDate starting (refetch=$($Refetch.IsPresent)); ledger rows before = $ledgerBefore"

# --- Run. chain_recovery_run.ps1 owns the 12:00-18:00 refusal -------------------
$chainArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $RepoRoot 'scripts\ops\chain_recovery_run.ps1'),
    '-ResumeFrom', 'public_wu_settlement_restore',
    '-TargetDate', $TargetDate
)
if ($Refetch) { $chainArgs += '-Refetch' }

& powershell.exe @chainArgs
$chainExit = $LASTEXITCODE

# --- Verify the OUTCOME, not the exit code --------------------------------------
$ledgerAfter = if (Test-Path $ledger) { (Get-Content $ledger).Count } else { 0 }
$ledgerGrew = $ledgerAfter -gt $ledgerBefore

$settled = $false
if (Test-Path $ledger) {
    $settled = [bool](Select-String -Path $ledger -Pattern ([regex]::Escape($TargetDate)) -Quiet)
}

$extra = @{
    chain_exit_code   = $chainExit
    ledger_rows_before = $ledgerBefore
    ledger_rows_after  = $ledgerAfter
    ledger_grew        = $ledgerGrew
    target_in_ledger   = $settled
}

if ($chainExit -ne 0) {
    Emit 'CHAIN_FAILED' "chain_recovery_run exited $chainExit; do NOT start the next date" $extra
    exit 1
}
if (-not $settled) {
    Emit 'SILENT_NOOP' 'chain exited 0 but the target date is still absent from the ledger. This is the treated_as_source_unavailable trap: re-run with -Refetch.' $extra
    exit 1
}

Emit 'SETTLED' "target date present in the ledger; ledger grew by $($ledgerAfter - $ledgerBefore) row(s). Re-run streak.ps1 and confirm Toronto did not regrade before starting the next date." $extra
exit 0
