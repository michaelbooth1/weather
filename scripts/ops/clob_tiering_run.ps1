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
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 1800,
    [switch]$PlanOnly,
    [switch]$Forced
)

$ErrorActionPreference = "Stop"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
foreach ($required in @($workloadLeaseScript, $jobScript, $contractScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "missing helper: $required" }
}
. $workloadLeaseScript
. $jobScript
. $contractScript

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found at $python -- run from the repo with its venv created."
}

$statusPath = Join-Path $RepoRoot "data\logs\clob_tiering_task_status.json"
$historyPath = Join-Path $RepoRoot "data\logs\clob_tiering_task_history.jsonl"
$statusDir = Split-Path -Parent $statusPath
if (-not (Test-Path $statusDir)) {
    New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
}

function Write-TaskStatus {
    param([hashtable]$Payload)
    $Payload["schema_version"] = "clob_tiering_task_status_v0.1"
    $Payload["written_at_utc"] = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $json = ($Payload | ConvertTo-Json -Depth 6)
    $temporary = "$statusPath.$PID.tmp"
    [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $statusPath -Force
    Add-Content -LiteralPath $historyPath -Value ($Payload | ConvertTo-Json -Depth 6 -Compress) -Encoding utf8
}

# Compression is sustained heavy I/O, so the complete repository-owned host
# policy applies rather than only the graded-window subset. 05:00 is the
# intended slot inside 00:30-09:00.
$now = Get-Date
$localMinute = ($now.Hour * 60) + $now.Minute
if ($localMinute -ge (9 * 60) -or $localMinute -lt 30) {
    Write-Host "REFUSED: outside the 00:30-09:00 heavy-work window; -Forced cannot bypass host policy."
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

$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "clob_projection_tiering"
if ($null -eq $workloadLease) {
    Write-TaskStatus @{ status = "SKIPPED_WORKLOAD_LEASE_BUSY"; local_time = $now.ToString("s") }
    Write-Host "SKIPPED: another heavyweight host workload owns data/logs/heavy_workload.lock"
    exit 0
}
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$proc = $null
$job = $null
try {
$job = New-WeatherKillOnCloseJob
$argumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $arguments
$proc = Start-WeatherProcessInJob -Job $job -FilePath $python `
    -ArgumentString $argumentString -WorkingDirectory $RepoRoot

# Touching .Handle forces .NET to cache the process handle. Without it,
# $proc.ExitCode reads back $null after the process exits and a clean run gets
# recorded as FAILED -- observed on the first plan run of this script.
$null = $proc.Handle

# Capture outranks this job. BelowNormal keeps the compression off the capture
# loops' CPU; failing to set it is not fatal, the job is still worth running.
try { $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal } catch { }

$hardStop = (Get-Date).AddSeconds($MaxRuntimeSeconds)
while (-not $proc.HasExited -and (Get-Date) -lt $hardStop) {
    Start-Sleep -Seconds 2
    $proc.Refresh()
}
$hardStopped = -not $proc.HasExited
if ($hardStopped) {
    $job.Dispose()
    $job = $null
}
$proc.WaitForExit()
$sw.Stop()

$exitCode = $(if ($hardStopped) { 75 } else { $proc.ExitCode })
if ($null -eq $exitCode) {
    # Never report success we cannot prove.
    $exitCode = 1
}
$freeAfter = (Get-PSDrive C).Free

Write-TaskStatus @{
    status            = $(if ($hardStopped) { "HARD_STOPPED" } elseif ($exitCode -eq 0) { "OK" } else { "FAILED" })
    mode              = $mode
    exit_code         = $exitCode
    duration_seconds  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    free_before_bytes = $freeBefore
    free_after_bytes  = $freeAfter
    reclaimed_bytes   = ($freeAfter - $freeBefore)
    report_path       = $outReport
    hard_stop_reached = $hardStopped
    max_runtime_seconds = $MaxRuntimeSeconds
    local_time        = $now.ToString("s")
}

$reclaimedGb = [math]::Round(($freeAfter - $freeBefore) / 1GB, 2)
Write-Host ("clob tiering {0}: exit={1} elapsed={2:N1}s reclaimed={3} GB free={4:N1} GB" -f $mode, $exitCode, $sw.Elapsed.TotalSeconds, $reclaimedGb, ($freeAfter / 1GB))
}
finally {
    if ($job) { $job.Dispose() }
    if ($proc) { $proc.Dispose() }
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
}
exit $exitCode
