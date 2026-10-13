# Run a short, read-only production execution-tape capture and prove that it
# produced usable evidence without degrading the three capture loops. The child
# is assigned to a kill-on-close Job before resume, so stopping this wrapper
# cannot leave a websocket producer behind.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-fA-F]{40}$")]
    [string]$RequiredAncestor,
    [ValidateRange(60, 3600)]
    [int]$DurationSeconds = 780,
    [ValidateRange(1.0, 99.0)]
    [double]$StartCommitPercent = 64.0,
    [ValidateRange(1.0, 99.0)]
    [double]$AbortCommitPercent = 66.0,
    [ValidateRange(32, 1024)]
    [int]$MaxWorkingSetMB = 256,
    [string]$ReportPath = "",
    [string]$HistoryPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$RequiredAncestor = $RequiredAncestor.ToLowerInvariant()
if (-not $ReportPath) {
    $ReportPath = Join-Path $RepoRoot "data\alerts\execution_tape_probe_last.json"
}
if (-not $HistoryPath) {
    $HistoryPath = Join-Path $RepoRoot "data\alerts\execution_tape_probe_history.jsonl"
}
$ReportPath = [IO.Path]::GetFullPath($ReportPath)
$HistoryPath = [IO.Path]::GetFullPath($HistoryPath)
if ($StartCommitPercent -ge $AbortCommitPercent) {
    throw "StartCommitPercent must be lower than AbortCommitPercent"
}

$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
$statusPath = Join-Path $RepoRoot "data\snapshots\execution_tape_status.json"
$snapshotStatusPath = Join-Path $RepoRoot "data\snapshots\loop_status.json"
foreach ($required in @($python, $jobScript, $workloadLeaseScript, $snapshotStatusPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required probe dependency is missing: $required"
    }
}
. $jobScript
. $workloadLeaseScript

function Get-CommitPercent {
    $limit = (Get-Counter "\Memory\Commit Limit").CounterSamples[0].CookedValue
    $used = (Get-Counter "\Memory\Committed Bytes").CounterSamples[0].CookedValue
    if ($limit -le 0 -or $used -lt 0) { throw "invalid Windows commit counters" }
    return [math]::Round(100.0 * $used / $limit, 2)
}

function ConvertTo-StatusInstant {
    # Parses a status timestamp as an absolute instant. Windows PowerShell 5.1
    # ConvertFrom-Json leaves ISO-8601 strings as strings; the loops write them
    # with their UTC offset, so DateTimeOffset.Parse keeps the instant exact even
    # across the DST fall-back hour (a wall-clock [datetime] cast does not).
    # Offset-less strings are taken as UTC. Unparseable or empty input is $null.
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [datetimeoffset]) { return $Value }
    if ($Value -is [datetime]) { return [datetimeoffset]$Value }
    if (-not [string]$Value) { return $null }
    try {
        return [datetimeoffset]::Parse(
            [string]$Value,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal
        )
    }
    catch { return $null }
}

function Get-HealthyCaptureWorkerCount {
    # Ages are differences of UTC instants (ConvertTo-StatusInstant), never of
    # local wall-clock times: on the 2026-11-01 fall-back night the repeated
    # 01:00-02:00 hour falls inside the probe window.
    param([datetimeoffset]$Now = [datetimeoffset]::UtcNow)
    $snapshotRoot = Join-Path $RepoRoot "data\snapshots"
    $specs = @(
        # The snapshot loop refreshes last_heartbeat every 60 s of its idle
        # sleep (SLEEP_HEARTBEAT_SECONDS), so a healthy heartbeat is about 60 s
        # old plus preflight/bookkeeping time. The heartbeat is liveness only;
        # iteration progress is proved separately by Get-SnapshotIterationProof
        # from last_completed_iteration_at.
        # Fail-safe exception: the inline capture path (stale-code debounce,
        # missing fingerprint, or a capture_fn override) writes the heartbeat at
        # market start and again only after the in-process capture returns, with
        # no batch timeout. An inline market capture longer than about 300 s
        # therefore fails this check and the probe; that is deliberate
        # (fail-closed), not a false negative to tune away.
        @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 300 },
        @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180 },
        @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180 }
    )
    $healthy = 0
    foreach ($spec in $specs) {
        try {
            $status = Get-Content -LiteralPath (Join-Path $snapshotRoot $spec.Status) -Raw |
                ConvertFrom-Json
            $lock = Get-Content -LiteralPath (Join-Path $snapshotRoot $spec.Lock) -Raw |
                ConvertFrom-Json
            $pidValue = [int]$status.pid
            $heartbeat = ConvertTo-StatusInstant $status.last_heartbeat
            if ($null -eq $heartbeat) { continue }
            $ageSeconds = ($Now - $heartbeat).TotalSeconds
            $alive = $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
            if (
                $pidValue -gt 0 -and [int]$lock.pid -eq $pidValue -and $alive -and
                $ageSeconds -ge 0 -and $ageSeconds -le [double]$spec.MaxAge
            ) {
                $healthy++
            }
        }
        catch { }
    }
    return $healthy
}

function Get-SnapshotIterationProof {
    # Snapshot liveness and progress proof for the bounded probe.
    #
    # last_heartbeat is liveness only: the loop also writes it every 60 s of the
    # idle sleep, so an advancing heartbeat no longer proves that an iteration
    # ran. Progress is last_completed_iteration_at, which the loop sets only when
    # a capture iteration completes (snapshot_tracker.finalize_iteration_error_state).
    #
    # Window sizing. Iteration starts are at most one interval apart (the sleep
    # is capped at interval minus elapsed and is only ever shortened), and a
    # batch ends by its fleet budget, so on a healthy loop two consecutive
    # completions are at most interval + fleet budget (+ preflight/bookkeeping
    # slack) apart: 600 + 540 + 120 = 1260 s at production defaults. The default
    # 780 s probe is shorter than that, so requiring an advance would fail a
    # healthy loop by construction (a short batch followed by a long one). The
    # proof therefore requires, at the end of the probe:
    #   * heartbeat age <= 300 s: a wedged loop stops beating, and 300 s is five
    #     60 s sleep cadences, well above the healthy ~60 s plus bookkeeping;
    #   * last_completed_iteration_at age <= interval + fleet budget + 120 s.
    # Once the probe has run for at least that bound the age check already
    # implies an advance; the advance is then also required explicitly.
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After,
        [Parameter(Mandatory = $true)][datetimeoffset]$BeforeReadUtc,
        [Parameter(Mandatory = $true)][datetimeoffset]$AfterReadUtc
    )

    $heartbeatMaxAgeSeconds = 300.0
    $completionSlackSeconds = 120.0
    $reasons = @()
    $heartbeat = ConvertTo-StatusInstant $After.last_heartbeat
    $completedBefore = ConvertTo-StatusInstant $Before.last_completed_iteration_at
    $completedAfter = ConvertTo-StatusInstant $After.last_completed_iteration_at
    $intervalSeconds = 0.0
    $fleetBudgetSeconds = 0.0
    try { $intervalSeconds = 60.0 * [double]$After.interval_minutes } catch { $intervalSeconds = 0.0 }
    try { $fleetBudgetSeconds = [double]$After.capture_execution.fleet_budget_seconds } catch { $fleetBudgetSeconds = 0.0 }
    $boundKnown = ($intervalSeconds -gt 0 -and $fleetBudgetSeconds -gt 0)
    if ($intervalSeconds -le 0) { $reasons += "snapshot status has no positive interval_minutes" }
    if ($fleetBudgetSeconds -le 0) { $reasons += "snapshot status has no positive capture_execution.fleet_budget_seconds" }
    $completionBoundSeconds = $intervalSeconds + $fleetBudgetSeconds + $completionSlackSeconds
    $elapsedSeconds = ($AfterReadUtc - $BeforeReadUtc).TotalSeconds

    $heartbeatAge = $null
    if ($null -eq $heartbeat) {
        $reasons += "snapshot last_heartbeat is missing or unparseable"
    }
    else {
        $heartbeatAge = ($AfterReadUtc - $heartbeat).TotalSeconds
        if ($heartbeatAge -lt 0 -or $heartbeatAge -gt $heartbeatMaxAgeSeconds) {
            $reasons += [string]::Format(
                [Globalization.CultureInfo]::InvariantCulture,
                "snapshot heartbeat age {0:F1}s is outside 0..{1}s", $heartbeatAge, $heartbeatMaxAgeSeconds)
        }
    }
    $completedAge = $null
    if ($null -eq $completedAfter) {
        $reasons += "snapshot last_completed_iteration_at is missing or unparseable"
    }
    else {
        $completedAge = ($AfterReadUtc - $completedAfter).TotalSeconds
        if ($completedAge -lt 0 -or ($boundKnown -and $completedAge -gt $completionBoundSeconds)) {
            $reasons += [string]::Format(
                [Globalization.CultureInfo]::InvariantCulture,
                "snapshot last completed iteration age {0:F1}s is outside 0..{1}s", $completedAge, $completionBoundSeconds)
        }
    }
    $advanced = (
        $null -ne $completedAfter -and
        ($null -eq $completedBefore -or $completedAfter -gt $completedBefore)
    )
    $advanceRequired = ($boundKnown -and $elapsedSeconds -ge $completionBoundSeconds)
    if ($advanceRequired -and -not $advanced) {
        $reasons += "snapshot last_completed_iteration_at did not advance during probe"
    }
    $completedBeforeText = $null
    if ($null -ne $completedBefore) { $completedBeforeText = $completedBefore.ToString("o") }
    $completedAfterText = $null
    if ($null -ne $completedAfter) { $completedAfterText = $completedAfter.ToString("o") }
    return [pscustomobject][ordered]@{
        # Fail closed: an unknown completion bound is never ok, independently
        # of the reason list (the completion-age check is skipped without it).
        ok = ($boundKnown -and @($reasons).Count -eq 0)
        reasons = @($reasons)
        heartbeat_age_seconds = $heartbeatAge
        heartbeat_max_age_seconds = $heartbeatMaxAgeSeconds
        completed_iteration_before = $completedBeforeText
        completed_iteration_after = $completedAfterText
        completed_iteration_age_seconds = $completedAge
        completion_bound_seconds = $completionBoundSeconds
        probe_elapsed_seconds = $elapsedSeconds
        advance_required = $advanceRequired
        advanced = $advanced
    }
}

function Read-ExecutionStatus {
    if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) { return $null }
    try { return Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json }
    catch { return $null }
}

function Get-StatusCounter {
    param($Status, [Parameter(Mandatory = $true)][string]$Name)

    if ($null -eq $Status) { return [int64]0 }
    $property = $Status.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) { return [int64]0 }
    return [int64]$property.Value
}

function Test-ConnectedSeedSet {
    param($Status)

    if ($null -eq $Status -or [string]$Status.state -ne "CONNECTED") { return $false }
    $expectedCount = [int]$Status.active_market_day_count
    $activeRows = @($Status.active_market_days)
    if ($expectedCount -le 0 -or $activeRows.Count -ne $expectedCount) { return $false }
    foreach ($row in $activeRows) {
        if (
            [string]$row.connection_state -ne "CONNECTED" -or
            -not [string]$row.market_id -or
            -not [string]$row.target_date -or
            -not [string]$row.event_slug
        ) {
            return $false
        }
    }
    return $true
}

function Write-ProbeRecord {
    param([Parameter(Mandatory = $true)]$Record)

    $parent = Split-Path -Parent $ReportPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $json = $Record | ConvertTo-Json -Depth 8
    $json | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    ($Record | ConvertTo-Json -Depth 8 -Compress) |
        Add-Content -LiteralPath $HistoryPath -Encoding UTF8
}

$record = [ordered]@{
    schema_version = "execution_tape_bounded_probe_v0.3"
    started_at = (Get-Date).ToString("o")
    finished_at = $null
    ok = $false
    stage = "preflight"
    detail = $null
    repo_head = $null
    required_ancestor = $RequiredAncestor
    duration_seconds = $DurationSeconds
    child_exit_code = $null
    peak_working_set_mb = 0.0
    peak_commit_percent = 0.0
    connected_seed_set_proved = $false
    connected_seed_set_proved_at = $null
    baseline_trades = 0
    final_trades = 0
    new_trade_observations = 0
    baseline_integrity_counters = $null
    final_integrity_counters = $null
    capture_workers_before = 0
    capture_workers_after = 0
    snapshot_heartbeat_before = $null
    snapshot_heartbeat_after = $null
    snapshot_iteration_proof = $null
    status_path = $statusPath
}
$job = $null
$child = $null
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "bounded_execution_tape_probe"
if ($null -eq $workloadLease) {
    $record.stage = "blocked_workload_lease"
    $record.detail = "another heavyweight host workload owns data/logs/heavy_workload.lock"
    $record.finished_at = (Get-Date).ToString("o")
    Write-ProbeRecord $record
    Write-Error $record.detail -ErrorAction Continue
    exit 1
}

try {
    # This proof is intentionally tied to the quiet window. A missed task must
    # fail, not catch up during the protected or graded capture windows.
    $now = Get-Date
    $hour = $now.Hour + ($now.Minute / 60.0)
    if ($hour -lt 1 -or $hour -ge 4) {
        throw ("probe must start inside the 01:00-04:00 quiet window (now {0:N2})" -f $hour)
    }

    $head = (& git -C $RepoRoot rev-parse HEAD).Trim().ToLowerInvariant()
    $originHead = (& git -C $RepoRoot rev-parse origin/master).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $head -ne $originHead) {
        throw "production HEAD must equal origin/master before the probe"
    }
    & git -C $RepoRoot merge-base --is-ancestor $RequiredAncestor $head
    if ($LASTEXITCODE -ne 0) {
        throw "required reviewed commit is not an ancestor of production HEAD"
    }
    $record.repo_head = $head

    $workersBefore = Get-HealthyCaptureWorkerCount
    $commitBefore = Get-CommitPercent
    $snapshotBefore = Get-Content -LiteralPath $snapshotStatusPath -Raw | ConvertFrom-Json
    $snapshotBeforeReadUtc = [datetimeoffset]::UtcNow
    $record.capture_workers_before = $workersBefore
    $record.snapshot_heartbeat_before = [string]$snapshotBefore.last_heartbeat
    $record.peak_commit_percent = $commitBefore
    if ($workersBefore -ne 3) { throw "expected three healthy capture workers before probe" }
    if ($commitBefore -gt $StartCommitPercent) {
        throw "host commit $commitBefore% exceeds start ceiling $StartCommitPercent%"
    }

    $baseline = Read-ExecutionStatus
    $baselineSession = if ($null -ne $baseline) { [string]$baseline.coordinator_session_id } else { "" }
    $baselineTrades = if ($null -ne $baseline -and $null -ne $baseline.last_counted) {
        [int64]$baseline.last_counted.trades_written
    } else { [int64]0 }
    $baselineIntegrity = [ordered]@{
        parse_rejections = Get-StatusCounter $baseline "parse_rejections"
        unrouted_trades = Get-StatusCounter $baseline "unrouted_trades"
        ambiguous_routes = Get-StatusCounter $baseline "ambiguous_routes"
    }
    $record.baseline_trades = $baselineTrades
    $record.baseline_integrity_counters = $baselineIntegrity

    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    $env:PYTHONUTF8 = "1"
    $pythonCode = "import threading; from weather.market.execution_tape_capture import run_live_capture; stop=threading.Event(); timer=threading.Timer($DurationSeconds, stop.set); timer.daemon=True; timer.start(); run_live_capture(shutdown_event=stop)"
    $argumentString = "-c `"$pythonCode`""
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob -Job $job -FilePath $python `
        -ArgumentString $argumentString -WorkingDirectory $RepoRoot
    $record.stage = "capture"

    while (-not $child.HasExited) {
        $child.Refresh()
        $workingSetMB = [math]::Round($child.WorkingSet64 / 1MB, 2)
        if ($workingSetMB -gt [double]$record.peak_working_set_mb) {
            $record.peak_working_set_mb = $workingSetMB
        }
        $commit = Get-CommitPercent
        if ($commit -gt [double]$record.peak_commit_percent) {
            $record.peak_commit_percent = $commit
        }
        if ($workingSetMB -gt $MaxWorkingSetMB) {
            throw "execution-tape child working set $workingSetMB MB exceeds $MaxWorkingSetMB MB"
        }
        if ($commit -gt $AbortCommitPercent) {
            throw "host commit $commit% exceeds abort ceiling $AbortCommitPercent%"
        }

        $status = Read-ExecutionStatus
        if (
            $null -ne $status -and
            [string]$status.coordinator_session_id -ne $baselineSession -and
            (Test-ConnectedSeedSet $status)
        ) {
            if (-not [bool]$record.connected_seed_set_proved) {
                $record.connected_seed_set_proved = $true
                $record.connected_seed_set_proved_at = (Get-Date).ToString("o")
            }
        }
        Start-Sleep -Seconds 2
    }

    $child.WaitForExit()
    $record.child_exit_code = $child.ExitCode
    if ($child.ExitCode -ne 0) { throw "execution-tape child exited $($child.ExitCode)" }

    $final = Read-ExecutionStatus
    if ($null -eq $final) { throw "execution-tape final status is unavailable" }
    $finalTrades = [int64]$final.last_counted.trades_written
    $finalIntegrity = [ordered]@{
        parse_rejections = Get-StatusCounter $final "parse_rejections"
        unrouted_trades = Get-StatusCounter $final "unrouted_trades"
        ambiguous_routes = Get-StatusCounter $final "ambiguous_routes"
    }
    $record.final_trades = $finalTrades
    $record.new_trade_observations = $finalTrades - $baselineTrades
    $record.final_integrity_counters = $finalIntegrity
    if (-not [bool]$record.connected_seed_set_proved) {
        throw "the complete active seed set was never observed connected"
    }
    if ([string]$final.state -ne "STOPPED" -or -not $final.capture_stopped_at_utc) {
        throw "capture did not stop cleanly with a durable STOPPED status"
    }
    if ([int64]$record.new_trade_observations -lt 1) {
        throw "bounded capture produced no new execution observations"
    }
    foreach ($name in @("parse_rejections", "unrouted_trades", "ambiguous_routes")) {
        if ([int64]$finalIntegrity[$name] -ne [int64]$baselineIntegrity[$name]) {
            throw "evidence-integrity counter increased: $name"
        }
    }

    $workersAfter = Get-HealthyCaptureWorkerCount
    $snapshotAfter = Get-Content -LiteralPath $snapshotStatusPath -Raw | ConvertFrom-Json
    $snapshotAfterReadUtc = [datetimeoffset]::UtcNow
    $record.capture_workers_after = $workersAfter
    $record.snapshot_heartbeat_after = [string]$snapshotAfter.last_heartbeat
    $snapshotProof = Get-SnapshotIterationProof -Before $snapshotBefore -After $snapshotAfter `
        -BeforeReadUtc $snapshotBeforeReadUtc -AfterReadUtc $snapshotAfterReadUtc
    $record.snapshot_iteration_proof = $snapshotProof
    if ($workersAfter -ne 3) { throw "capture worker health degraded during probe" }
    if (-not [bool]$snapshotProof.ok) {
        throw ("snapshot iteration proof failed during probe: " + (@($snapshotProof.reasons) -join "; "))
    }

    $record.ok = $true
    $record.stage = "proved"
    $record.detail = "new routed execution observations from a connected seed set with no new integrity errors"
}
catch {
    $record.ok = $false
    $record.stage = "failed"
    $record.detail = $_.Exception.Message
}
finally {
    if ($null -ne $job) { $job.Dispose() }
    if ($null -ne $child) { $child.Dispose() }
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
    $record.finished_at = (Get-Date).ToString("o")
    Write-ProbeRecord $record
}

if ($record.ok) {
    Write-Output ($record | ConvertTo-Json -Depth 8)
    exit 0
}
Write-Error "execution-tape bounded probe failed: $($record.detail)" -ErrorAction Continue
exit 1
