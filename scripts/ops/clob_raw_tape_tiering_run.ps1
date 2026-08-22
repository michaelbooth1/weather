# Compresses the canonical closed-day CLOB order_books.jsonl tape, independently of the chain.
#
# WHY THIS EXISTS.
# `clob_tiering_run.ps1` compresses the order_books_long.csv PROJECTION and deliberately
# leaves the raw tape alone -- "the raw order_books.jsonl stays as canonical evidence".
# That is the right call for a projection tier, but it leaves the largest single artifact
# on the host uncompressed. Measured 2026-08-10: 708 files / 133.47 GB of retained raw
# tape, gzipping 10.97x on a real settled day (nyc 2026-08-09,
# 308,109,123 -> 28,078,865). Free space was 151.4 GB falling ~10.7 GB/day -- about 14
# days -- with the lock date in the same week. If the disk fills, capture dies.
#
# THIS IS NOT A RETENTION CHANGE. The gzip payload is verified byte-identical to the
# source (sha256 + line count over the decompressed stream) before the source is removed,
# and `weather.market.order_book_tape` reads order_books.jsonl.gz as a CANONICAL
# representation, ranked above every CSV projection. The same bytes are stored smaller.
#
# ORDER MATTERS: run the PROJECTION tier first. A market-day that still has an
# uncompressed order_books_long.csv is one `closed_day_projection_tiering` has not
# finished with -- it rebuilds parity FROM the raw tape and blocks on
# `canonical_order_books_jsonl_missing`. The module refuses such days
# (`blocked_projection_tier_pending`); this ordering makes that refusal rare rather than
# routine.
#
# Run from the repo root:
#   .\scripts\ops\clob_raw_tape_tiering_run.ps1 -PlanOnly    # report candidates, change nothing
#   .\scripts\ops\clob_raw_tape_tiering_run.ps1 -Limit 10    # compress at most 10, delete verified
#   .\scripts\ops\clob_raw_tape_tiering_run.ps1              # compress all eligible

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$SettledBefore = "",
    [int]$Limit = 0,
    [ValidateRange(60, 7200)][int]$MaxRuntimeSeconds = 2400,
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

$statusPath = Join-Path $RepoRoot "data\logs\clob_raw_tape_tiering_task_status.json"
$historyPath = Join-Path $RepoRoot "data\logs\clob_raw_tape_tiering_task_history.jsonl"
$statusDir = Split-Path -Parent $statusPath
if (-not (Test-Path $statusDir)) {
    New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
}

function Write-TaskStatus {
    param([hashtable]$Payload)
    $Payload["schema_version"] = "clob_raw_tape_tiering_task_status_v0.1"
    $Payload["written_at_utc"] = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $json = ($Payload | ConvertTo-Json -Depth 6)
    $temporary = "$statusPath.$PID.tmp"
    [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $statusPath -Force
    Add-Content -LiteralPath $historyPath -Value ($Payload | ConvertTo-Json -Depth 6 -Compress) -Encoding utf8
}

# Decompress-and-verify is heavier than the projection tier -- it reads every
# source twice -- so the complete 00:30-09:00 heavy-work policy applies.
$now = Get-Date
$localMinute = ($now.Hour * 60) + $now.Minute
if ($localMinute -ge (9 * 60) -or $localMinute -lt 30) {
    Write-Host "REFUSED: outside the 00:30-09:00 heavy-work window; -Forced cannot bypass host policy."
    Write-TaskStatus @{ status = "REFUSED_CAPTURE_WINDOW"; local_time = $now.ToString("s") }
    exit 0
}

$freeBefore = (Get-PSDrive C).Free

$outJson = Join-Path $RepoRoot "data\backtest\clob_raw_tape_tiering.json"
$outReport = Join-Path $RepoRoot "data\backtest\clob_raw_tape_tiering_report.md"

$mode = "apply"
if ($PlanOnly) { $mode = "plan" }

$arguments = @("-m", "weather.operations.clob_raw_tape_tiering", $mode)
if (-not $PlanOnly) {
    $arguments += "--delete-source"
    if ($Limit -gt 0) { $arguments += @("--limit", "$Limit") }
}
if ($SettledBefore) { $arguments += @("--settled-before", $SettledBefore) }
$arguments += @("--out", $outJson, "--report", $outReport)

$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "clob_raw_tape_tiering"
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

# Touching .Handle forces .NET to cache the process handle. Without it, $proc.ExitCode
# reads back $null after the process exits and a clean run is recorded as FAILED.
$null = $proc.Handle

# Capture outranks this job.
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
Write-Host ("clob raw tape tiering {0}: exit={1} elapsed={2:N1}s reclaimed={3} GB free={4:N1} GB" -f $mode, $exitCode, $sw.Elapsed.TotalSeconds, $reclaimedGb, ($freeAfter / 1GB))
}
finally {
    if ($job) { $job.Dispose() }
    if ($proc) { $proc.Dispose() }
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
}
exit $exitCode
