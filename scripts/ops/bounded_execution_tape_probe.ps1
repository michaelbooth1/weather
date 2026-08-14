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

function Get-HealthyCaptureWorkerCount {
    $snapshotRoot = Join-Path $RepoRoot "data\snapshots"
    $specs = @(
        # Snapshot intentionally sleeps for nearly ten minutes between cycles.
        # Admit a complete normal cycle while remaining below the 15-minute
        # streak gap limit; the probe separately requires this heartbeat to
        # advance across its 13-minute end-to-end run. A ten-minute run was
        # shorter than observed healthy cycles and could fail by construction.
        @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720 },
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
            $ageSeconds = ((Get-Date) - [datetime]$status.last_heartbeat).TotalSeconds
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
    schema_version = "execution_tape_bounded_probe_v0.2"
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
    $heartbeatBefore = [datetime](
        (Get-Content -LiteralPath $snapshotStatusPath -Raw | ConvertFrom-Json).last_heartbeat
    )
    $record.capture_workers_before = $workersBefore
    $record.snapshot_heartbeat_before = $heartbeatBefore.ToString("o")
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
    $heartbeatAfter = [datetime](
        (Get-Content -LiteralPath $snapshotStatusPath -Raw | ConvertFrom-Json).last_heartbeat
    )
    $record.capture_workers_after = $workersAfter
    $record.snapshot_heartbeat_after = $heartbeatAfter.ToString("o")
    if ($workersAfter -ne 3) { throw "capture worker health degraded during probe" }
    if ($heartbeatAfter -le $heartbeatBefore) { throw "snapshot heartbeat did not advance during probe" }

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
