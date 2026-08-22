# Single-host training window: stop capture, run nightly retrain, restore capture.
#
# The capture-resource admission gate (correctly) refuses heavy work while the
# snapshot/CLOB/observation-trigger loops are active, and this dedicated host
# captures 24/7 — so on one machine the learning loop can only run inside a
# deliberate, bounded window where capture is stopped and then guaranteed to
# come back. Slot: 01:00 local, hard child cap 170m, so capture is restored
# before the 03:00-05:00 predawn frontier on warm-cache nights and by ~04:05
# worst-case. A separate dead-man task (register script) re-enables capture at
# 04:15 unconditionally in case this process dies mid-window.
#
# Every day that uses a window has a deliberate capture gap and is therefore
# NOT a clean day for item-321 Phase 2 proofs. That is honest and intended:
# clean-day streaks are collected on nights where the window skips or after
# the learning loop earns a second host.
#
# Modes:
#   (default)     full window: preflight -> stop -> retrain -> restore
#   -RestoreOnly  idempotent capture restore (used by the dead-man task)
#   -DryRun       preflight + plan only; never touches capture

[CmdletBinding(DefaultParameterSetName = "Full")]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidateSet("WeatherTrainingWindow")]
    [string]$WindowTaskName = "WeatherTrainingWindow",
    [string]$SchedulerTaskExecutable = "powershell.exe",
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')]
    [string]$RunAtLocal,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainTargetDate,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainParentReleaseId,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainTrainingAsOf,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainFeatureContractId,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainCorpusManifest,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainPitForecastCorpusManifest,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainCandidateDir,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$BaseRetrainRuntimeId,
    [double]$MaxCommitPercent = 70.0,
    [long]$MinFreeDiskBytes = 60GB,
    # A mid-flight snapshot fleet pass (12 markets, one isolated child each)
    # can take several minutes to drain after the stop verb; 90s aborted the
    # 2026-07-14 window with all loops mid-iteration. Worst case the retrain
    # starts by ~01:10 and its 170m cap ends by 04:00, ahead of the 04:15 dead-man.
    [ValidateRange(1, 600)][double]$CaptureStopTimeoutSeconds = 600.0,
    [ValidateRange(10, 170)][double]$ChildTimeoutMinutes = 170.0,
    [ValidateRange(30, 300)][double]$CaptureRecoveryTimeoutSeconds = 300.0,
    [Parameter(Mandatory = $true, ParameterSetName = "RestoreOnly")]
    [switch]$RestoreOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
if ($RestoreOnly -and $DryRun) {
    throw "RestoreOnly and DryRun are mutually exclusive."
}
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$scriptPath = (Resolve-Path -LiteralPath $PSCommandPath -ErrorAction Stop).Path
$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
foreach ($requiredScript in @($contractScript, $workloadLeaseScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "training window helper not found at $requiredScript"
    }
}
. $contractScript
. $workloadLeaseScript
$baseBindings = $null
$boundRunAt = $null
if (-not $RestoreOnly) {
    $boundRunAt = Resolve-TrainingWindowRunAtLocal -RunAtLocal $RunAtLocal
    $RunAtLocal = $boundRunAt.ToString("yyyy-MM-ddTHH:mm:ss")
    $baseBindings = Resolve-TrainingWindowBaseRetrainBindings `
        -RepoRoot $RepoRoot `
        -ScheduleLocalTime "01:00" `
        -BaseRetrainTargetDate $BaseRetrainTargetDate `
        -BaseRetrainParentReleaseId $BaseRetrainParentReleaseId `
        -BaseRetrainTrainingAsOf $BaseRetrainTrainingAsOf `
        -BaseRetrainFeatureContractId $BaseRetrainFeatureContractId `
        -BaseRetrainCorpusManifest $BaseRetrainCorpusManifest `
        -BaseRetrainPitForecastCorpusManifest $BaseRetrainPitForecastCorpusManifest `
        -BaseRetrainCandidateDir $BaseRetrainCandidateDir `
        -BaseRetrainRuntimeId $BaseRetrainRuntimeId
}
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "project interpreter is missing: $python"
}
$python = (Resolve-Path -LiteralPath $python -ErrorAction Stop).Path
$scheduledActionTokens = @()
$expectedWindowActionArguments = ""
if (-not $RestoreOnly) {
    $scheduledActionTokens = @(Get-TrainingWindowTaskActionTokens `
        -RepoRoot $RepoRoot `
        -ScriptPath $scriptPath `
        -WindowTaskName $WindowTaskName `
        -SchedulerTaskExecutable $SchedulerTaskExecutable `
        -RunAtLocal $RunAtLocal `
        -BaseRetrainTargetDate $baseBindings.BaseRetrainTargetDate `
        -BaseRetrainParentReleaseId $baseBindings.BaseRetrainParentReleaseId `
        -BaseRetrainTrainingAsOf $baseBindings.BaseRetrainTrainingAsOf `
        -BaseRetrainFeatureContractId $baseBindings.BaseRetrainFeatureContractId `
        -BaseRetrainCorpusManifest $baseBindings.BaseRetrainCorpusManifest `
        -BaseRetrainPitForecastCorpusManifest $baseBindings.BaseRetrainPitForecastCorpusManifest `
        -BaseRetrainCandidateDir $baseBindings.BaseRetrainCandidateDir `
        -BaseRetrainRuntimeId $baseBindings.BaseRetrainRuntimeId)
    $expectedWindowActionArguments = ConvertTo-ScheduledTaskArgumentString `
        -Tokens $scheduledActionTokens
}
$logDir = Join-Path $RepoRoot "data\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logPath = Join-Path $logDir "training_window.log"
$statusPath = Join-Path $logDir "training_window_status.json"
$script:restoreOutcome = "NOT_RUN"
$script:captureRecoveryProof = $null

$supervisorTasks = @(
    "WeatherSnapshotLoopSupervisor",
    "WeatherClobBookLoopSupervisor",
    "WeatherObservationTriggerSupervisor"
)

function Write-WindowLog([string]$Level, [string]$Message) {
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Level, $Message
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

function Write-WindowStatus([string]$Phase, [string]$Outcome) {
    $payload = @{
        updated_at = (Get-Date -Format "o")
        phase = $Phase
        outcome = $Outcome
        restore_outcome = $script:restoreOutcome
        capture_recovery = $script:captureRecoveryProof
    }
    $temporary = "$statusPath.$PID.tmp"
    [IO.File]::WriteAllText(
        $temporary,
        ($payload | ConvertTo-Json -Depth 12) + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $statusPath -Force -ErrorAction Stop
}

function Restore-Capture {
    $script:restoreOutcome = "RUNNING"
    $script:captureRecoveryProof = $null
    $failures = New-Object System.Collections.Generic.List[string]
    # Idempotent, but every enable and ensure outcome is checked rather than
    # assuming that issuing a command restored capture.
    foreach ($task in $supervisorTasks) {
        try {
            Enable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
            $readback = Get-ScheduledTask -TaskName $task -ErrorAction Stop
            if ([string]$readback.State -eq "Disabled") {
                throw "task remains disabled after enable"
            }
            Write-WindowLog "RESTORE" "enabled $task (readback $($readback.State))"
        }
        catch { $failures.Add("enable_${task}:$($_.Exception.Message)") }
    }
    & $python -m weather.collection.snapshot_tracker --ensure | Out-Null
    if ($LASTEXITCODE -ne 0) { $failures.Add("snapshot_ensure_exit_$LASTEXITCODE") }
    & $python -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15 | Out-Null
    if ($LASTEXITCODE -ne 0) { $failures.Add("clob_ensure_exit_$LASTEXITCODE") }
    & $python -m weather.operations.observation_trigger ensure --market all --interval-seconds 60 --stale-after-seconds 180 | Out-Null
    if ($LASTEXITCODE -ne 0) { $failures.Add("observation_ensure_exit_$LASTEXITCODE") }
    if ($failures.Count -gt 0) {
        $script:restoreOutcome = "COMMAND_FAILED"
        throw "capture restore command failure(s): $($failures -join '; ')"
    }
    Write-WindowLog "RESTORE" "ensure verbs returned zero for all three loops"

    $deadline = [datetime]::UtcNow.AddSeconds($CaptureRecoveryTimeoutSeconds)
    $lastProof = $null
    do {
        try {
            $raw = @(& $python -m weather.operations.capture_recovery_check `
                --repo-root $RepoRoot --json)
            $checkExit = $LASTEXITCODE
            $lastProof = (($raw -join "`n") | ConvertFrom-Json)
            $workers = @($lastProof.workers)
            if ($checkExit -eq 0 -and [bool]$lastProof.ok -and
                $workers.Count -eq 3 -and
                @($workers | Where-Object { -not [bool]$_.ok }).Count -eq 0) {
                $script:captureRecoveryProof = $lastProof
                $script:restoreOutcome = "PASS"
                Write-WindowLog "RESTORE" "canonical capture recovery is PASS for 3/3 workers"
                return $lastProof
            }
        }
        catch {
            $lastProof = [pscustomobject]@{
                ok = $false
                workers = @()
                error = $_.Exception.Message
            }
        }
        if ([datetime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 5 }
    } while ([datetime]::UtcNow -lt $deadline)
    $script:captureRecoveryProof = $lastProof
    $script:restoreOutcome = "RECOVERY_UNPROVEN"
    throw "capture restore remained unproved after ${CaptureRecoveryTimeoutSeconds}s"
}

function Get-ActiveCaptureLoops {
    # Diagnostic only: name the loops the gate still sees as active so a stop
    # timeout is attributable. Writes the canonical gate JSON (normal rolling
    # artifact) and parses its loops array.
    $gatePath = Join-Path $RepoRoot "data\backtest\capture_resource_gate.json"
    & $python -m weather.operations.capture_resource_gate `
        --workload training_window_stop_diagnostic `
        --capture-mode no_live_capture `
        --min-free-memory-bytes 0 `
        --min-free-disk-bytes 0 | Out-Null
    try {
        $gate = Get-Content $gatePath -Raw | ConvertFrom-Json
        $names = @($gate.loops | Where-Object { $_.active } | ForEach-Object { $_.name })
        if ($names.Count -gt 0) { return ($names -join ",") }
        return "none_visible_at_diagnostic_time"
    } catch { return "diagnostic_unavailable" }
}

function Wait-CaptureStopped([double]$TimeoutSeconds) {
    # Reuse the canonical read-only gate instead of trusting process names or
    # stale status PIDs. In no-live-capture mode it passes only after all three
    # workers are actually inactive.
    $deadline = [datetime]::UtcNow.AddSeconds([math]::Max(1.0, $TimeoutSeconds))
    do {
        & $python -m weather.operations.capture_resource_gate `
            --workload training_window_stop_confirmation `
            --capture-mode no_live_capture `
            --min-free-memory-bytes 0 `
            --min-free-disk-bytes 0 `
            --no-write `
            --fail-on-block | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 2
    } while ([datetime]::UtcNow -lt $deadline)
    return $false
}

function Assert-CaptureStoppedForTraining {
    foreach ($task in $supervisorTasks) {
        $taskState = Get-ScheduledTask -TaskName $task -ErrorAction Stop
        if ([string]$taskState.State -ne "Disabled") {
            throw "capture supervisor is not disabled before retrain: $task=$($taskState.State)"
        }
    }
    & $python -m weather.operations.capture_resource_gate `
        --workload training_window_pre_child_confirmation `
        --capture-mode no_live_capture `
        --min-free-memory-bytes 0 `
        --min-free-disk-bytes 0 `
        --no-write `
        --fail-on-block | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "canonical no-live-capture gate blocked immediately before retrain"
    }
}

Set-Location $RepoRoot

if ($RestoreOnly) {
    Write-WindowLog "INFO" "restore-only invocation (dead-man or manual)"
    try {
        Restore-Capture | Out-Null
        Write-WindowStatus "restore_only" "capture_recovery_pass"
        exit 0
    }
    catch {
        Write-WindowLog "ERROR" "restore-only failed: $($_.Exception.Message)"
        Write-WindowStatus "restore_only" "capture_recovery_failed"
        exit 1
    }
}

# Run-specific bindings may execute only at their reviewed 01:00 occurrence.
# Refuse before admission, lease acquisition, or capture mutation.
$windowSkewSeconds = [math]::Abs(((Get-Date) - $boundRunAt).TotalSeconds)
$taskMatches = @(Get-ScheduledTask -TaskName $WindowTaskName -ErrorAction SilentlyContinue)
$taskTrigger = if ($taskMatches.Count -eq 1) { @($taskMatches[0].Triggers) } else { @() }
$taskActions = if ($taskMatches.Count -eq 1) { @($taskMatches[0].Actions) } else { @() }
$taskIsExactOneShot = (
    $taskMatches.Count -eq 1 -and
    [string]$taskMatches[0].TaskPath -eq "\" -and
    [string]$taskMatches[0].State -eq "Running" -and
    $taskActions.Count -eq 1 -and
    [string]$taskActions[0].Execute -ieq $SchedulerTaskExecutable -and
    [string]$taskActions[0].Arguments -ceq $expectedWindowActionArguments -and
    [string]$taskActions[0].WorkingDirectory -ieq $RepoRoot -and
    $taskTrigger.Count -eq 1 -and
    [string]$taskTrigger[0].CimClass.CimClassName -eq "MSFT_TaskTimeTrigger" -and
    [bool]$taskTrigger[0].Enabled -and
    [string]::IsNullOrWhiteSpace([string]$taskTrigger[0].Repetition.Interval) -and
    -not [bool]$taskMatches[0].Settings.StartWhenAvailable -and
    [string]$taskMatches[0].Settings.ExecutionTimeLimit -eq "PT3H45M" -and
    [string]$taskMatches[0].Settings.MultipleInstances -eq "IgnoreNew" -and
    [bool]$taskMatches[0].Settings.Hidden -and
    [bool]$taskMatches[0].Settings.WakeToRun -and
    -not [bool]$taskMatches[0].Settings.DisallowStartIfOnBatteries -and
    -not [bool]$taskMatches[0].Settings.StopIfGoingOnBatteries -and
    [string]$taskMatches[0].Principal.UserId -ieq $env:USERNAME -and
    [string]$taskMatches[0].Principal.LogonType -eq "S4U" -and
    [string]$taskMatches[0].Principal.RunLevel -eq "Limited" -and
    ([datetime]$taskTrigger[0].StartBoundary) -eq $boundRunAt
)
if ($windowSkewSeconds -gt 120 -or -not $taskIsExactOneShot) {
    $reason = "bound window skew ${windowSkewSeconds}s; exact one-shot=$taskIsExactOneShot"
    Write-WindowLog "REFUSE" $reason
    Write-WindowStatus "preflight" "refused_outside_bound_one_shot"
    exit 75
}

# ---- Preflight: never start a window on an unhealthy host ----
$os = Get-CimInstance Win32_OperatingSystem
$commitPercent = 100.0 * ($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / $os.TotalVirtualMemorySize
$freeDisk = (Get-PSDrive C).Free
$skipReasons = @()
if ($commitPercent -gt $MaxCommitPercent) { $skipReasons += "commit at $([math]::Round($commitPercent,1))% > $MaxCommitPercent%" }
if ($freeDisk -lt $MinFreeDiskBytes) { $skipReasons += "free disk $([math]::Round($freeDisk/1GB,1))GB < $([math]::Round($MinFreeDiskBytes/1GB,0))GB" }

if ($skipReasons.Count -gt 0) {
    Write-WindowLog "SKIP" ("window skipped: " + ($skipReasons -join "; ") + " (capture untouched)")
    Write-WindowStatus "preflight" ("skipped: " + ($skipReasons -join "; "))
    exit 0
}

if ($DryRun) {
    Write-WindowLog "INFO" "dry-run: preflight PASS (commit $([math]::Round($commitPercent,1))%, disk $([math]::Round($freeDisk/1GB,1))GB free); would stop and verify capture inactive (cap ${CaptureStopTimeoutSeconds}s), run retrain in no-live-capture mode (cap ${ChildTimeoutMinutes}m), restore"
    Write-WindowStatus "dry_run" "preflight_pass"
    exit 0
}

$childExit = -1
$nightlyStatus = "not_run"
$nightlyAdmission = "not_run"
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot -Workload "training_window"
if ($null -eq $workloadLease) {
    Write-WindowStatus "skipped" "heavy_workload_lease_busy"
    Write-WindowLog "SKIP" "another heavyweight host workload owns data/logs/heavy_workload.lock; Git and capture remain untouched"
    exit 0
}
try {
    Write-WindowLog "INFO" "window opening: commit $([math]::Round($commitPercent,1))%, disk $([math]::Round($freeDisk/1GB,1))GB free"
    Write-WindowStatus "opening" "in_progress"

# ---- Commit scheduled location-config drift so clean-source gates can pass ----
# WeatherLocationConfigRefresh regenerates the two config JSONs at 00:00, one
# hour before this window; an uncommitted diff makes the nightly clean-source
# gate (and therefore immutable release construction) fail closed. Only these
# two generated files are ever auto-committed, and only after JSON validation;
# any other dirt is logged and left for the operator.
$autoCommitPaths = @("config/location_market_events.json", "config/locations.json")
$dirtyPaths = @(git -C $RepoRoot status --porcelain |
    Where-Object { $_ } |
    ForEach-Object { ($_.Substring(3).Trim('"') -replace '\\', '/') })
if ($dirtyPaths.Count -gt 0) {
    $unexpected = @($dirtyPaths | Where-Object { $autoCommitPaths -notcontains $_ })
    if ($unexpected.Count -gt 0) {
        Write-WindowLog "CONFIG" "worktree has non-config changes ($($unexpected -join ', ')); not auto-committing; clean-source gates will fail closed"
    } else {
        $jsonValid = $true
        foreach ($rel in $dirtyPaths) {
            & $python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" (Join-Path $RepoRoot $rel)
            if ($LASTEXITCODE -ne 0) { $jsonValid = $false }
        }
        if ($jsonValid) {
            git -C $RepoRoot add -- $autoCommitPaths 2>$null
            git -C $RepoRoot commit -m "config: scheduled location refresh drift (training-window auto-commit)" | Out-Null
            Write-WindowLog "CONFIG" "committed scheduled location-config drift ($($dirtyPaths -join ', '))"
        } else {
            Write-WindowLog "CONFIG" "location-config drift failed JSON validation; leaving uncommitted; clean-source gates will fail closed"
        }
    }
}

    if (Test-Path -LiteralPath $baseBindings.BaseRetrainCandidateDir) {
        throw "BaseRetrainCandidateDir appeared before capture stop: $($baseBindings.BaseRetrainCandidateDir)"
    }
    # ---- Stop capture cleanly: supervisors first so nothing revives mid-window ----
    foreach ($task in $supervisorTasks) {
        Disable-ScheduledTask -TaskName $task -ErrorAction Stop | Out-Null
        $disabledTask = Get-ScheduledTask -TaskName $task -ErrorAction Stop
        if ([string]$disabledTask.State -ne "Disabled") {
            throw "capture supervisor did not disable: $task=$($disabledTask.State)"
        }
        Write-WindowLog "STOP" "disabled $task (exact readback)"
    }
    & $python -m weather.collection.snapshot_tracker --stop | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "snapshot stop exited $LASTEXITCODE" }
    & $python -m weather.market.market_microstructure stop | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "CLOB stop exited $LASTEXITCODE" }
    & $python -m weather.operations.observation_trigger stop | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "observation-trigger stop exited $LASTEXITCODE" }
    Write-WindowLog "STOP" "stop verbs issued for all three loops"
    if (-not (Wait-CaptureStopped $CaptureStopTimeoutSeconds)) {
        $childExit = 9001
        $stillActive = Get-ActiveCaptureLoops
        Write-WindowLog "ERROR" "capture did not become fully inactive within ${CaptureStopTimeoutSeconds}s (still active: $stillActive); retrain not started"
        throw "capture stop verification timed out"
    }
    Write-WindowLog "STOP" "canonical gate confirms all three capture loops inactive"
    Assert-CaptureStoppedForTraining

    # ---- Run the retrain child under a hard timeout ----
    Write-WindowStatus "retrain" "running"
    $schedulerActionArgumentsB64 = ConvertTo-SchedulerArgumentContract `
        -Tokens $scheduledActionTokens
    $schedulerCorrelationSeconds = [int][math]::Ceiling($CaptureStopTimeoutSeconds + 300.0)
    # Leave five minutes for Python to publish a terminal status before the
    # outer Job containment cap. The 170m max plus 10m stop and 5m recovery
    # bounds preserve margin before the daily 04:15 dead-man.
    $producerSlaSeconds = [int][math]::Floor(($ChildTimeoutMinutes * 60.0) - 300.0)
    Write-WindowLog "RETRAIN" "starting nightly_retrain (cap ${ChildTimeoutMinutes}m; delegated scheduler task $WindowTaskName)"
    $childArgs = @(
        "-m", "weather.operations.nightly_retrain", "run",
        "--fail-on-daily-learning-blocker",
        "--capture-resource-mode", "no_live_capture",
        "--capture-resource-min-free-memory-bytes", "0",
        "--scheduler-invocation-topology", "delegated_child",
        "--scheduler-task-name", $WindowTaskName,
        "--scheduler-task-executable", $SchedulerTaskExecutable,
        "--scheduler-task-working-directory", $RepoRoot,
        "--scheduler-task-action-arguments-b64", $schedulerActionArgumentsB64,
        "--scheduler-process-executable", $python,
        "--scheduler-correlation-seconds", ([string]$schedulerCorrelationSeconds),
        "--producer-sla-seconds", ([string]$producerSlaSeconds),
        "--schedule-local-time", $baseBindings.ScheduleLocalTime,
        "--schedule-timezone", "America/Toronto",
        "--run-at-local", $RunAtLocal,
        "--base-retrain-target-date", $baseBindings.BaseRetrainTargetDate,
        "--base-retrain-parent-release-id", $baseBindings.BaseRetrainParentReleaseId,
        "--base-retrain-training-as-of", $baseBindings.BaseRetrainTrainingAsOf,
        "--base-retrain-feature-contract-id", $baseBindings.BaseRetrainFeatureContractId,
        "--base-retrain-corpus-manifest", $baseBindings.BaseRetrainCorpusManifest,
        "--base-retrain-pit-forecast-corpus-manifest", $baseBindings.BaseRetrainPitForecastCorpusManifest,
        "--base-retrain-candidate-dir", $baseBindings.BaseRetrainCandidateDir,
        "--base-retrain-runtime-id", $baseBindings.BaseRetrainRuntimeId
    )
    # ---- Self-disarming first-inactive-release bootstrap ----
    # Armed only while ALL hold: a reviewed staged candidate-independent PIT
    # source exists, the release store is absent/empty, and no active pointer
    # exists. Once release #1 exists the same window falls back to the ordinary
    # research invocation instead of wedging on an invalid bootstrap request.
    $pitSourceRoot = Join-Path $RepoRoot "data\analysis\point_in_time\production_source_2026-07-16"
    $pitCorpus = Join-Path $pitSourceRoot "preselection-source.parquet"
    $pitManifest = Join-Path $pitSourceRoot "preselection-source-manifest.json"
    $pitReplay = Join-Path $pitSourceRoot "replay_manifest.json"
    $pitReceipt = Join-Path $pitSourceRoot "staging-receipt.json"
    $pitLedgerRoot = Join-Path $RepoRoot "data\settlements"
    $releasesRoot = Join-Path $RepoRoot "artifacts\releases"
    $activePointer = Join-Path $releasesRoot "current_release.json"
    $releaseStoreEmpty = (-not (Test-Path $releasesRoot)) -or
        (@(Get-ChildItem $releasesRoot -Force -ErrorAction SilentlyContinue).Count -eq 0)
    $pitReceiptValid = $false
    if ((Test-Path -LiteralPath $pitCorpus -PathType Leaf) -and
        (Test-Path -LiteralPath $pitManifest -PathType Leaf) -and
        (Test-Path -LiteralPath $pitReplay -PathType Leaf) -and
        (Test-Path -LiteralPath $pitReceipt -PathType Leaf)) {
        & $python -m weather.operations.point_in_time_staging_receipt verify `
            --receipt $pitReceipt `
            --corpus $pitCorpus `
            --manifest $pitManifest `
            --replay-manifest $pitReplay `
            --ledger-root $pitLedgerRoot
        $pitReceiptValid = ($LASTEXITCODE -eq 0)
        if (-not $pitReceiptValid) {
            Write-WindowLog "RETRAIN" "staged PIT source receipt is stale or mismatched; production bootstrap refused"
        }
    } elseif ((Test-Path -LiteralPath $pitCorpus) -or
        (Test-Path -LiteralPath $pitManifest) -or
        (Test-Path -LiteralPath $pitReplay)) {
        Write-WindowLog "RETRAIN" "staged PIT source is incomplete or unreceipted; production bootstrap refused"
    }
    if ($pitReceiptValid -and
        $releaseStoreEmpty -and (-not (Test-Path $activePointer))) {
        $childArgs += @(
            "--release-candidate-mode", "production",
            "--bootstrap-first-inactive-release",
            "--point-in-time-source-corpus", $pitCorpus,
            "--point-in-time-source-manifest", $pitManifest,
            "--point-in-time-source-replay-manifest", $pitReplay,
            "--point-in-time-source-receipt", $pitReceipt
        )
        Write-WindowLog "RETRAIN" "receipted staged PIT source + empty release store: production mode with first-inactive-release bootstrap"
    }
    Assert-CaptureStoppedForTraining
    $childArgumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $childArgs
    $child = Start-Process -FilePath $python `
        -ArgumentList $childArgumentString `
        -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden
    $completed = $child.WaitForExit([int]($ChildTimeoutMinutes * 60 * 1000))
    if (-not $completed) {
        Write-WindowLog "RETRAIN" "cap reached; killing child tree pid $($child.Id)"
        taskkill /PID $child.Id /T /F | Out-Null
        $childExit = 9999
    } else {
        $childExit = $child.ExitCode
        Write-WindowLog "RETRAIN" "nightly_retrain exited $childExit"
    }
    $nightlyStatusPath = Join-Path $RepoRoot "data\backtest\nightly_retrain_status.json"
    if (Test-Path $nightlyStatusPath) {
        try {
            $nightlyPayload = Get-Content $nightlyStatusPath -Raw | ConvertFrom-Json
            $nightlyStatus = [string]$nightlyPayload.status
            $nightlyAdmission = [string]$nightlyPayload.capture_resource_admission.decision
        } catch {
            $nightlyStatus = "unreadable"
        }
    } else {
        $nightlyStatus = "missing"
    }
    Write-WindowLog "RETRAIN" "nightly status $nightlyStatus; capture admission $nightlyAdmission; child exit $childExit"
    if ($childExit -eq 0 -and $nightlyStatus -in @("blocked", "error", "missing", "unreadable")) {
        $childExit = 2
        Write-WindowLog "RETRAIN" "promoting non-success nightly status to window exit $childExit"
    }
} finally {
    # ---- Restore capture no matter what happened above ----
    try {
        Write-WindowStatus "restore" "in_progress"
        Restore-Capture | Out-Null
        Write-WindowStatus "closed" "nightly_${nightlyStatus}_admission_${nightlyAdmission}_exit_$childExit"
        Write-WindowLog "INFO" "window closed (nightly $nightlyStatus, admission $nightlyAdmission, exit $childExit); capture recovery 3/3 PASS"
    }
    catch {
        $childExit = 9002
        Write-WindowLog "ERROR" "capture restoration failed: $($_.Exception.Message)"
        Write-WindowStatus "restore_failed" "capture_recovery_unproved_exit_$childExit"
    }
    finally { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
}
exit $childExit
