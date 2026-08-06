# Compresses settled CLOB order-book long tapes, independently of the daily chain.
#
# WHY THIS EXISTS AS ITS OWN JOB.
# `clob_order_book_tiering` is step ~13 of the ~45-step daily refresh. When the
# chain defers early, the step never runs and every settled market-day keeps a
# raw `order_books_long.csv` instead of its ~23x smaller `.csv.gz`. That is
# ~1.56 GB per market-day x 12 markets = ~18.7 GB/day of pure waste, and it has
# now happened twice for two unrelated reasons:
#
#   2026-07-18  chain deferred on memory admission (maker_paper_score)
#   2026-08-04  chain deferred on `capture_loop_not_fresh` -- the snapshot loop
#               reported consecutive_errors=1, which is enough to defer step 7
#               (`taker_finalization_watchdog`) and everything after it
#
# Both times disk headroom fell far enough to threaten capture, which is the
# project's #1 operational objective. Disk safety must not depend on chain
# health, so this runs on its own trigger. It is idempotent and additive: the
# underlying tool re-checks 2h writer quiescence, verifies sha256 and line
# counts, and deletes a source only after its cleanup preflight PASSes. The raw
# `order_books.jsonl` stays as canonical evidence -- only the CSV projection is
# compressed.
#
# SPLIT MARKET-DAYS ARE STRUCTURALLY SAFE. Some days hold a plain
# `order_books_long.csv` AND an `order_books_long.csv.gz` covering *disjoint*
# halves of the day; there the plain file is not redundant and deleting it
# silently truncates the day. Such a day can never become a candidate here,
# because a candidate is by definition a day with no gz, and `apply` re-checks
# `gzip_path.exists()` before compressing. They surface as
# `already_tiered_source_present` and are left untouched.
#
# Run from the repo root:
#   .\scripts\ops\clob_tiering_run.ps1              # apply, delete verified sources
#   .\scripts\ops\clob_tiering_run.ps1 -PlanOnly    # report candidates, change nothing

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$SettledBefore = "",
    [int]$Limit = 0,
    [switch]$PlanOnly,
    [switch]$Forced
)

$ErrorActionPreference = "Stop"

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run from the repo with its venv created."
}

$statusPath = Join-Path $RepoRoot "data\logs\clob_tiering_task_status.json"
$statusDir = Split-Path -Parent $statusPath
if (-not (Test-Path $statusDir)) {
    New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
}

function Write-TaskStatus {
    param([hashtable]$Payload)
    $Payload["schema_version"] = "clob_tiering_task_status_v0.1"
    $Payload["written_at_utc"] = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    ($Payload | ConvertTo-Json -Depth 6) | Out-File -FilePath $statusPath -Encoding utf8
}

# The 12:00-18:00 graded capture window is what the Toronto streak is measured
# on. Compressing ~30 GB is heavy sustained I/O, so it never runs inside that
# window on a normal trigger. 05:00 is the intended slot.
$now = Get-Date
if ((-not $Forced) -and $now.Hour -ge 12 -and $now.Hour -lt 18) {
    Write-Host "REFUSED: inside the 12:00-18:00 graded capture window. Re-run with -Forced only if you accept the streak risk."
    Write-TaskStatus @{ status = "REFUSED_CAPTURE_WINDOW"; local_time = $now.ToString("s") }
    exit 0
}

$freeBefore = (Get-PSDrive C).Free

$outJson = Join-Path $RepoRoot "data\backtest\clob_order_book_tiering.json"
$outReport = Join-Path $RepoRoot "data\backtest\clob_order_book_tiering_report.md"

$mode = "apply"
if ($PlanOnly) { $mode = "plan" }

$arguments = @("-m", "weather.operations.clob_order_book_tiering", $mode)
if (-not $PlanOnly) {
    $arguments += "--delete-source"
    if ($Limit -gt 0) { $arguments += @("--limit", "$Limit") }
}
if ($SettledBefore) { $arguments += @("--settled-before", $SettledBefore) }
$arguments += @("--out", $outJson, "--report", $outReport)

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $RepoRoot -NoNewWindow -PassThru

# Touching .Handle forces .NET to cache the process handle. Without it,
# $proc.ExitCode reads back $null after the process exits and a clean run gets
# recorded as FAILED -- observed on the first plan run of this script.
$null = $proc.Handle

# Capture outranks this job. BelowNormal keeps the compression off the capture
# loops' CPU; failing to set it is not fatal, the job is still worth running.
try { $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal } catch { }

$proc.WaitForExit()
$sw.Stop()

$exitCode = $proc.ExitCode
if ($null -eq $exitCode) {
    # Never report success we cannot prove.
    $exitCode = 1
}
$freeAfter = (Get-PSDrive C).Free

Write-TaskStatus @{
    status            = $(if ($exitCode -eq 0) { "OK" } else { "FAILED" })
    mode              = $mode
    exit_code         = $exitCode
    duration_seconds  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    free_before_bytes = $freeBefore
    free_after_bytes  = $freeAfter
    reclaimed_bytes   = ($freeAfter - $freeBefore)
    report_path       = $outReport
    local_time        = $now.ToString("s")
}

$reclaimedGb = [math]::Round(($freeAfter - $freeBefore) / 1GB, 2)
Write-Host ("clob tiering {0}: exit={1} elapsed={2:N1}s reclaimed={3} GB free={4:N1} GB" -f $mode, $exitCode, $sw.Elapsed.TotalSeconds, $reclaimedGb, ($freeAfter / 1GB))

exit $exitCode
