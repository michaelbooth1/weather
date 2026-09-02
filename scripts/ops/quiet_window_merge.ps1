# Merge a validated topic branch into master during the quiet window, verifying that the
# capture fleet survives the code roll BEFORE anything is published.
#
#   .\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... `
#       [-ExpectedTip <full-commit-sha>] [-ExpectedBaseline <full-master-sha>] `
#       [-Force] [-DryRun] [-OwnerApprovedException <one-time-token>]
#
# The incident-bound -ProductionBaselineReconciliation mode has a separate
# exact L/T/source/self contract documented in docs/ops/streak-soak.md. It is
# not a generic local-behind-origin escape hatch.
#
# Why this exists: merging a branch that touches modules the capture loops have imported
# makes the supervisors readopt the new code (STALE_CODE restart). If that code is bad,
# capture dies. Doing the merge locally first, proving capture recovers, and only then
# publishing means a bad merge is undone by resetting to the exact pre-merge commit with nothing
# published and no history to rewrite.
#
# Refuses to run outside 01:00-04:00 without -Force: a roll inside the 12:00-18:00 graded
# window can cost the streak day. See docs/ops/streak-soak.md.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [string]$ExpectedTip = "",
    [string]$ExpectedBaseline = "",
    [switch]$ProductionBaselineReconciliation,
    [string]$ExpectedLocalBaseline = "",
    [string]$ExpectedPublishedTarget = "",
    [string]$ExpectedSourceTip = "",
    [string]$ExpectedSourceTree = "",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$AttemptReportPath = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$OwnerApprovedException = "",
    [switch]$Force,
    [switch]$DryRun,
    [int]$SettleSeconds = 300,
    [ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200
)

$ErrorActionPreference = "Stop"
$ExpectedSelfSha256 = $ExpectedSelfSha256.Trim().ToLowerInvariant()
if ($ExpectedSelfSha256) {
    if ($ExpectedSelfSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "ExpectedSelfSha256 must be a full SHA256"
    }
    $actualSelfSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualSelfSha256 -ne $ExpectedSelfSha256) {
        throw "quiet-window merge script changed after its caller froze the launch contract"
    }
}
$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$py = Join-Path $repo "venv\Scripts\python.exe"
if ($OwnerApprovedException) {
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        (Get-Date).ToString("yyyy-MM-dd") -cne "2026-08-23"
    ) {
        throw "owner-approved protected-window exception is invalid or expired"
    }
    $workloadLeaseScript = Join-Path $PSScriptRoot "workload_admission.ps1"
    $expectedWorkloadLeaseSha256 =
        "3e2de64fb02e98e3016c71163bd7b297cf72488bbdfa593b38b237441f396389"
    $actualWorkloadLeaseSha256 =
        (Get-FileHash -LiteralPath $workloadLeaseScript -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualWorkloadLeaseSha256 -cne $expectedWorkloadLeaseSha256) {
        throw "owner-approved workload admission source changed"
    }
}
else {
    $workloadLeaseScript = Join-Path $repo "scripts\ops\workload_admission.ps1"
}
if ($ProductionBaselineReconciliation.IsPresent) {
    $expectedAdoptedWorkloadAdmissionSha256 =
        "cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105"
    $actualAdoptedWorkloadAdmissionSha256 =
        (Get-FileHash -LiteralPath $workloadLeaseScript -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualAdoptedWorkloadAdmissionSha256 -cne $expectedAdoptedWorkloadAdmissionSha256) {
        throw "production-baseline reconciliation requires the exact adopted workload_admission.ps1 bytes"
    }
}
. $workloadLeaseScript
$reportPath = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$historyPath = Join-Path $repo "data\alerts\quiet_window_merge_history.jsonl"
$activeMarkerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
$log = New-Object System.Collections.Generic.List[string]
$resolvedBranchTip = $null
$mergeTarget = $Branch
$mergeCommit = $null
$baselineCommit = $null
$preMerge = $null
$rollbackContentSha256 = [ordered]@{}
$captureRecoveryProved = $false
$reconciliationStagedSafetyCaptureRecoveryProved = $false
$reconciliationStagedSafetyCaptureRecoveryAt = $null
$reconciliationPrePushCaptureRecoveryProved = $false
$reconciliationPrePushCaptureRecoveryAt = $null
$executionTapeRecoveryRequired = $false
$executionTapeReadoptionExpected = $false
$executionTapeRolledButInactiveSkipped = $false
$executionTapeRecoveryProved = $false
$executionTapeSourceBefore = $null
$publicationAcknowledged = $false
$documentationTransactionRecorded = $false
$documentationTransactionPendingSha256 = $null
$documentationTransactionSnapshotPath = $null
$documentedMarkerSha256 = $null
$activeMarkerOwned = $false
$productionBaselineReconciliationMode = $ProductionBaselineReconciliation.IsPresent
$reconciliationModeName = if ($productionBaselineReconciliationMode) {
    "production_baseline_reconciliation_v0.1"
}
else { "ordinary_synchronized_merge_v0.1" }
$reconciliationActualPreMerge = $null
$reconciliationBootGuardCommit = $null
$reconciliationSafetyTip = $null
$reconciliationSafetyTree = $null
$reconciliationSnapshotRoot = $null
$reconciliationSnapshotManifestPath = $null
$reconciliationSnapshotManifestSha256 = $null
$reconciliationSnapshotPaths = [ordered]@{}
$reconciliationSourceRoot = $null
$reconciliationSourceTree = $null
$reconciliationPostCommitMarkerArmed = $false
$rollVerdictExitCode = $null
$rollVerdictJsonSha256 = $null
$rollVerdictExplicitBase = $null
$rollVerdictExplicitBranch = $null
$publicationInvoked = $false
$reconciliationMarkerSha256 = $null
$reconciliationRollVerdictPath = $null
$reconciliationRollVerdictTranscriptPath = $null
$reconciliationRollVerdictTranscriptSha256 = $null
$reconciliationRollVerdictReadable = $false
$reconciliationDependencySha256 = [ordered]@{}
$oneShotPushStartCount = 0
$oneShotPushPreLastRunTime = $null
$oneShotPushObservedLastRunTime = $null
$oneShotPushLastTaskResult = $null
$oneShotPushRuntimeState = $null
$oneShotPushTerminalProved = $false
$oneShotPushRunObserved = $false
$oneShotPushStopAttempted = $false
$oneShotPushStopCount = 0
$oneShotPushStopExhausted = $false
$oneShotPushStartIssuedAt = $null
$oneShotPushContainmentDeadline = $null
$pushContainmentDeadline = $null
$pushContainmentStopAt = $null
$oneShotPushTerminalProvedAt = $null
$oneShotPushContainmentBreached = $false
$pushStartRpcRequestId = $null
$pushStartRpcRequestSha256 = $null
$pushStartRpcDeadlineUtc = $null
$pushStartRpcTimedOut = $false
$pushStartError = $null
$pushStopRpcRequestId = $null
$pushStopRpcRequestSha256 = $null
$pushStopRpcDeadlineUtc = $null
$pushStopRpcTimedOut = $false
$reconciliationOwnedChildInitialized = $false
$reconciliationOwnedChildJobScript = $null
$reconciliationSchedulerRpcScript = $null
$reconciliationSchedulerRpcSha256 = $null
$reconciliationPowerShellExecutable = $null
$reconciliationChildTerminationMilliseconds = 5000
$reconciliationChildBoundaryReserveSeconds = 8
$reconciliationCommitInvocationStarted = $false
$reconciliationRollbackStarted = $false
if ($productionBaselineReconciliationMode) {
    $reconciliationDependencySha256["scripts/ops/workload_admission.ps1@local_baseline"] =
        $actualAdoptedWorkloadAdmissionSha256
}
function Note($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    $log.Add($line); Write-Output $line
}
function Fail($m) {
    Note "ABORT: $m"
    Save-Report -ok $false -stage "abort" -detail $m
    exit 1
}
function Save-Report($ok, $stage, $detail) {
    $record = [ordered]@{
        schema = "quiet_window_merge_report_v0.2"
        ts = (Get-Date).ToString("o"); repo_root = $repo; branch = $Branch; ok = $ok
        operation_mode = $reconciliationModeName
        expected_tip = $ExpectedTip; expected_baseline = $ExpectedBaseline
        expected_local_baseline = $ExpectedLocalBaseline
        expected_published_target = $ExpectedPublishedTarget
        expected_source_tip = $ExpectedSourceTip
        expected_source_tree = $ExpectedSourceTree
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $preMerge
        reconciliation_actual_pre_merge_commit = $reconciliationActualPreMerge
        reconciliation_boot_guard_commit = $reconciliationBootGuardCommit
        reconciliation_safety_tip = $reconciliationSafetyTip
        reconciliation_safety_tree = $reconciliationSafetyTree
        reconciliation_source_root = $reconciliationSourceRoot
        reconciliation_source_tree = $reconciliationSourceTree
        reconciliation_entry_sha256 = $ExpectedSelfSha256
        reconciliation_snapshot_root = $reconciliationSnapshotRoot
        reconciliation_snapshot_manifest_path = $reconciliationSnapshotManifestPath
        reconciliation_snapshot_manifest_sha256 = $reconciliationSnapshotManifestSha256
        reconciliation_snapshot_paths = $reconciliationSnapshotPaths
        reconciliation_dependency_sha256 = $reconciliationDependencySha256
        roll_verdict_exit_code = $rollVerdictExitCode
        roll_verdict_explicit_base = $rollVerdictExplicitBase
        roll_verdict_explicit_branch = $rollVerdictExplicitBranch
        roll_verdict_json_sha256 = $rollVerdictJsonSha256
        roll_verdict_transcript_sha256 = $reconciliationRollVerdictTranscriptSha256
        rollback_content_sha256 = $rollbackContentSha256
        reconciliation_config_content_sha256 = $rollbackContentSha256
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        reconciliation_staged_safety_capture_recovery_proved = $reconciliationStagedSafetyCaptureRecoveryProved
        reconciliation_staged_safety_capture_recovery_at = $reconciliationStagedSafetyCaptureRecoveryAt
        reconciliation_pre_push_capture_recovery_proved = $reconciliationPrePushCaptureRecoveryProved
        reconciliation_pre_push_capture_recovery_at = $reconciliationPrePushCaptureRecoveryAt
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        push_invocation_attempted = $publicationInvoked
        push_pre_last_run_time = $oneShotPushPreLastRunTime
        push_observed_last_run_time = $oneShotPushObservedLastRunTime
        push_last_task_result = $oneShotPushLastTaskResult
        push_runtime_state = $oneShotPushRuntimeState
        push_terminal_proved = $oneShotPushTerminalProved
        push_run_observed = $oneShotPushRunObserved
        push_stop_attempted = $oneShotPushStopAttempted
        push_stop_count = $oneShotPushStopCount
        push_stop_exhausted = $oneShotPushStopExhausted
        push_start_issued_at = $oneShotPushStartIssuedAt
        push_containment_deadline = $oneShotPushContainmentDeadline
        push_terminal_proved_at = $oneShotPushTerminalProvedAt
        push_containment_breached = $oneShotPushContainmentBreached
        push_start_rpc_request_id = $pushStartRpcRequestId
        push_start_rpc_request_sha256 = $pushStartRpcRequestSha256
        push_start_rpc_deadline_utc = $pushStartRpcDeadlineUtc
        push_start_rpc_timed_out = $pushStartRpcTimedOut
        push_stop_rpc_request_id = $pushStopRpcRequestId
        push_stop_rpc_request_sha256 = $pushStopRpcRequestSha256
        push_stop_rpc_deadline_utc = $pushStopRpcDeadlineUtc
        push_stop_rpc_timed_out = $pushStopRpcTimedOut
        publication_acknowledged = $publicationAcknowledged
        stage = $stage; detail = $detail; log = @($log)
    }
    $json = $record | ConvertTo-Json -Depth 8
    $reportPersisted = $false
    $attemptReportPersisted = $false
    $attemptReportExpectedSha256 = $null
    # An integration attempt supplies its own unused evidence path. Create it
    # in one same-directory rename before touching the mutable compatibility
    # slots, so a parent killed immediately after this child returns still has
    # an exact attempt-local report. File.Move is exclusive: an immutable
    # report is never overwritten by a retry or a different attempt.
    if ($AttemptReportPath) {
        $attemptParent = Split-Path -Parent $AttemptReportPath
        $attemptLeaf = Split-Path -Leaf $AttemptReportPath
        $attemptTemp = Join-Path $attemptParent (".{0}.{1}.tmp" -f $attemptLeaf, [guid]::NewGuid().ToString("N"))
        try {
            $reportBytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
            $reportSha = [Security.Cryptography.SHA256]::Create()
            try {
                $attemptReportExpectedSha256 = ([BitConverter]::ToString(
                        $reportSha.ComputeHash($reportBytes)
                    ) -replace '-', '').ToLowerInvariant()
            }
            finally { $reportSha.Dispose() }
            [IO.File]::WriteAllText(
                $attemptTemp,
                $json,
                (New-Object System.Text.UTF8Encoding($false))
            )
            [IO.File]::Move($attemptTemp, $AttemptReportPath)
            if (-not (Test-Path -LiteralPath $AttemptReportPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $AttemptReportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                    $attemptReportExpectedSha256) {
                throw "attempt-local immutable quiet-merge report failed its post-create hash proof"
            }
            $attemptReportPersisted = $true
            $reportPersisted = $true
        }
        finally {
            if (Test-Path -LiteralPath $attemptTemp) {
                Remove-Item -LiteralPath $attemptTemp -Force -ErrorAction SilentlyContinue
            }
        }
    }
    try {
        $json | Set-Content -Path $reportPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    # $reportPath is a single most-recent slot, so a later run ERASES an earlier one. On
    # 2026-08-01 three scheduled merges aborted at 01:15/01:50/02:25 (the config-drift trap)
    # and a manual re-run at 02:55 succeeded and overwrote all three -- leaving no on-disk
    # trace of the failures at all, only the task exit codes. That is exactly how the aborts
    # were later mis-read as a cosmetic exit code. Append every outcome so history survives.
    try {
        ($record | ConvertTo-Json -Depth 8 -Compress) | Add-Content -Path $historyPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    if ($AttemptReportPath -and -not $attemptReportPersisted) {
        throw "attempt-local immutable quiet-window terminal report could not be persisted"
    }
    if (-not $reportPersisted) {
        throw "quiet-window terminal report could not be persisted"
    }
    # Retire the durable marker only after a terminal report proves publication
    # or an exact baseline restoration. Merged-unpushed and unproven rollback
    # states retain it so boot/status/reconciliation cannot lose the recovery
    # target merely because a failure report was written.
    $markerCanRetire = if ($productionBaselineReconciliationMode) {
        ($stage -eq "pushed" -and $publicationAcknowledged) -or
            $stage -eq "rolled_back"
    }
    else {
        ($stage -eq "pushed" -and $publicationAcknowledged) -or
            $stage -eq "rolled_back" -or
            $stage -eq "abort" -or
            $stage -eq "dry_run"
    }
    if ($activeMarkerOwned -and $markerCanRetire) {
        if ($productionBaselineReconciliationMode) {
            if ($reconciliationMarkerSha256 -notmatch '^[0-9a-f]{64}$' -or
                -not (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ne
                    $reconciliationMarkerSha256) {
                throw "production-baseline reconciliation marker changed before compare-and-retire"
            }
            if ($stage -eq "pushed" -and (-not $publicationAcknowledged -or
                -not $publicationInvoked -or -not $oneShotPushTerminalProved -or
                -not $oneShotPushRunObserved)) {
                throw "production-baseline reconciliation publication is not acknowledged before marker retirement"
            }
        }
        if ($AttemptReportPath -and
            (-not (Test-Path -LiteralPath $AttemptReportPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $AttemptReportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                    $attemptReportExpectedSha256)) {
            throw "attempt-local immutable report changed before active-marker retirement"
        }
        Remove-Item -LiteralPath $activeMarkerPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $activeMarkerPath) {
            throw "active quiet-merge marker still exists after terminal retirement"
        }
    }
}

# A scheduled caller may redirect this script's complete output to a task log.
# In Windows PowerShell 5.1 that turns native stderr into PowerShell error records;
# with the script-wide Stop preference, a harmless git warning can terminate the
# wrapper before we inspect git's actual exit code. Scope Continue to the native
# call, then restore Stop immediately. This does not hide a git failure: callers
# must still check the returned process exit code.
function Invoke-GitAllowingNativeStderr {
    param([Parameter(Mandatory = $true)][scriptblock]$Action)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Action
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Write-QuietMergeMarker {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [string]$ExpectedCurrentSha256 = ""
    )

    $markerPreMerge = if ($productionBaselineReconciliationMode -and
        -not $reconciliationPostCommitMarkerArmed) {
        $reconciliationBootGuardCommit
    }
    else { $preMerge }
    $marker = [ordered]@{
        schema = "quiet_window_merge_in_progress_v0.1"
        updated_at = (Get-Date).ToString("o")
        repo_root = $repo
        phase = $Phase
        operation_mode = $reconciliationModeName
        branch = $Branch
        expected_tip = $ExpectedTip
        expected_baseline = $ExpectedBaseline
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $markerPreMerge
        reconciliation_actual_pre_merge_commit = $reconciliationActualPreMerge
        reconciliation_boot_guard_commit = $reconciliationBootGuardCommit
        reconciliation_safety_tip = $reconciliationSafetyTip
        reconciliation_safety_tree = $reconciliationSafetyTree
        reconciliation_local_baseline = $ExpectedLocalBaseline
        reconciliation_published_target = $ExpectedPublishedTarget
        reconciliation_source_tip = $ExpectedSourceTip
        reconciliation_source_tree = $reconciliationSourceTree
        reconciliation_entry_sha256 = $ExpectedSelfSha256
        reconciliation_snapshot_manifest_path = $reconciliationSnapshotManifestPath
        reconciliation_snapshot_manifest_sha256 = $reconciliationSnapshotManifestSha256
        reconciliation_snapshot_paths = $reconciliationSnapshotPaths
        reconciliation_dependency_sha256 = $reconciliationDependencySha256
        roll_verdict_exit_code = $rollVerdictExitCode
        roll_verdict_explicit_base = $rollVerdictExplicitBase
        roll_verdict_explicit_branch = $rollVerdictExplicitBranch
        roll_verdict_json_sha256 = $rollVerdictJsonSha256
        roll_verdict_transcript_sha256 = $reconciliationRollVerdictTranscriptSha256
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        reconciliation_staged_safety_capture_recovery_proved = $reconciliationStagedSafetyCaptureRecoveryProved
        reconciliation_staged_safety_capture_recovery_at = $reconciliationStagedSafetyCaptureRecoveryAt
        reconciliation_pre_push_capture_recovery_proved = $reconciliationPrePushCaptureRecoveryProved
        reconciliation_pre_push_capture_recovery_at = $reconciliationPrePushCaptureRecoveryAt
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        push_invocation_attempted = $publicationInvoked
        push_pre_last_run_time = $oneShotPushPreLastRunTime
        push_observed_last_run_time = $oneShotPushObservedLastRunTime
        push_last_task_result = $oneShotPushLastTaskResult
        push_runtime_state = $oneShotPushRuntimeState
        push_terminal_proved = $oneShotPushTerminalProved
        push_run_observed = $oneShotPushRunObserved
        push_stop_attempted = $oneShotPushStopAttempted
        push_stop_count = $oneShotPushStopCount
        push_stop_exhausted = $oneShotPushStopExhausted
        push_start_issued_at = $oneShotPushStartIssuedAt
        push_containment_deadline = $oneShotPushContainmentDeadline
        push_terminal_proved_at = $oneShotPushTerminalProvedAt
        push_containment_breached = $oneShotPushContainmentBreached
        push_start_rpc_request_id = $pushStartRpcRequestId
        push_start_rpc_request_sha256 = $pushStartRpcRequestSha256
        push_start_rpc_deadline_utc = $pushStartRpcDeadlineUtc
        push_start_rpc_timed_out = $pushStartRpcTimedOut
        push_stop_rpc_request_id = $pushStopRpcRequestId
        push_stop_rpc_request_sha256 = $pushStopRpcRequestSha256
        push_stop_rpc_deadline_utc = $pushStopRpcDeadlineUtc
        push_stop_rpc_timed_out = $pushStopRpcTimedOut
        publication_acknowledged = $publicationAcknowledged
        auto_refreshed_paths = @(
            "config/locations.json",
            "config/location_market_events.json"
        )
        auto_refreshed_sha256 = $rollbackContentSha256
        reconciliation_config_content_sha256 = $rollbackContentSha256
    }
    if ($productionBaselineReconciliationMode) {
        if ($reconciliationPostCommitMarkerArmed) {
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
        }
        $allowedPreCommitPhases = @(
            "reconciliation_preparing",
            "reconciliation_prepared",
            "reconciliation_merge_uncommitted",
            "reconciliation_capture_recovered_uncommitted"
        )
        $allowedPostCommitPhases = @(
            "merge_committed_unpublished",
            "documented_unpublished",
            "published"
        )
        $configHashMapValid = $true
        $configHashMap = $marker.reconciliation_config_content_sha256
        if ($null -eq $configHashMap -or
            @($configHashMap.Keys).Count -ne $reconciliationExpectedConfigBlobs.Count) {
            $configHashMapValid = $false
        }
        foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
            if ($null -eq $configHashMap -or -not $configHashMap.Contains($relativePath)) {
                $configHashMapValid = $false
                continue
            }
            $contentSha256 = [string]$configHashMap[$relativePath]
            if ($contentSha256 -notmatch '^[0-9a-f]{64}$' -or
                $contentSha256 -cne [string]$rollbackContentSha256[$relativePath]) {
                $configHashMapValid = $false
            }
        }
        $commonIdentityValid = (
            [string]$marker.operation_mode -ceq "production_baseline_reconciliation_v0.1" -and
            [string]$marker.baseline_commit -ceq $ExpectedLocalBaseline -and
            [string]$marker.expected_baseline -ceq $ExpectedLocalBaseline -and
            [string]$marker.expected_tip -ceq $ExpectedSourceTip -and
            [string]$marker.resolved_branch_tip -ceq $ExpectedSourceTip -and
            [string]$marker.reconciliation_boot_guard_commit -ceq $ExpectedPublishedTarget -and
            [string]$marker.reconciliation_source_tip -ceq $ExpectedSourceTip -and
            [string]$marker.reconciliation_safety_tip -ceq $ExpectedSourceTip -and
            [string]$marker.reconciliation_safety_tree -ceq $ExpectedSourceTree -and
            [string]$marker.reconciliation_snapshot_manifest_sha256 -match '^[0-9a-f]{64}$' -and
            $configHashMapValid
        )
        $preCommitIdentityValid = (
            $allowedPreCommitPhases -contains $Phase -and
            -not $reconciliationPostCommitMarkerArmed -and
            [string]$marker.pre_merge_commit -ceq $ExpectedPublishedTarget -and
            -not $marker.merge_commit -and
            $marker.push_invocation_attempted -ne $true -and
            $marker.publication_acknowledged -ne $true
        )
        $postCommitIdentityValid = (
            $allowedPostCommitPhases -contains $Phase -and
            $reconciliationPostCommitMarkerArmed -and
            [string]$marker.pre_merge_commit -ceq $reconciliationActualPreMerge -and
            [string]$marker.merge_commit -match '^[0-9a-f]{40}$' -and
            $marker.capture_recovery_proved -eq $true -and
            $marker.reconciliation_staged_safety_capture_recovery_proved -eq $true -and
            [datetimeoffset]::Parse([string]$marker.reconciliation_staged_safety_capture_recovery_at) -le
                [datetimeoffset]::Parse([string]$marker.updated_at) -and
            ($marker.execution_tape_recovery_required -ne $true -or
                $marker.execution_tape_recovery_proved -eq $true)
        )
        $documentationIdentityValid = if ($Phase -in @("documented_unpublished", "published")) {
            $marker.documentation_transaction_recorded -eq $true -and
                [string]$marker.documentation_transaction_pending_sha256 -match '^[0-9a-f]{64}$' -and
                [string]$marker.documentation_transaction_snapshot_path -ceq
                    "data/alerts/documentation_transactions/pending-$($marker.documentation_transaction_pending_sha256).json"
        }
        else { $true }
        $phaseEvidenceValid = switch ($Phase) {
            "merge_committed_unpublished" {
                $marker.documentation_transaction_recorded -ne $true -and
                    -not $marker.documentation_transaction_pending_sha256 -and
                    -not $marker.documentation_transaction_snapshot_path
            }
            "documented_unpublished" { $marker.documentation_transaction_recorded -eq $true }
            "published" { $marker.documentation_transaction_recorded -eq $true }
            default { $true }
        }
        $pushRuntimeIdentityValid = if ($Phase -eq "published") {
            try {
                [string]$marker.push_runtime_state -ceq "Ready" -and
                    [datetimeoffset]::Parse([string]$marker.push_observed_last_run_time) -gt
                        [datetimeoffset]::Parse([string]$marker.push_pre_last_run_time) -and
                    [long]$marker.push_last_task_result -eq 0 -and
                    [int]$marker.push_stop_count -ge 0 -and
                    $marker.push_stop_exhausted -ne $true -and
                    [datetimeoffset]::Parse([string]$marker.push_start_issued_at) -lt
                        [datetimeoffset]::Parse([string]$marker.push_containment_deadline) -and
                    [datetimeoffset]::Parse([string]$marker.push_terminal_proved_at) -lt
                        [datetimeoffset]::Parse([string]$marker.push_containment_deadline) -and
                    [datetimeoffset]::Parse([string]$marker.push_terminal_proved_at) -lt
                        [datetimeoffset]::Parse([string]$marker.push_containment_deadline).Date.AddHours(4) -and
                    $marker.push_containment_breached -ne $true
            }
            catch { $false }
        }
        else { $true }
        $publicationIdentityValid = if ($Phase -eq "published") {
            $marker.push_invocation_attempted -eq $true -and
                $marker.reconciliation_pre_push_capture_recovery_proved -eq $true -and
                [datetimeoffset]::Parse([string]$marker.reconciliation_pre_push_capture_recovery_at) -le
                    [datetimeoffset]::Parse([string]$marker.push_start_issued_at) -and
                [string]$marker.push_start_rpc_request_id -match '^[0-9a-f]{32}$' -and
                [string]$marker.push_start_rpc_request_sha256 -match '^[0-9a-f]{64}$' -and
                [datetimeoffset]::Parse([string]$marker.push_start_rpc_deadline_utc) -gt
                    [datetimeoffset]::Parse([string]$marker.push_start_issued_at) -and
                $marker.push_start_rpc_timed_out -ne $true -and
                [string]::IsNullOrEmpty([string]$pushStartError) -and
                $marker.push_stop_rpc_timed_out -ne $true -and
                $marker.push_terminal_proved -eq $true -and
                $marker.push_run_observed -eq $true -and
                $pushRuntimeIdentityValid -and
                $marker.publication_acknowledged -eq $true
        }
        else { $marker.publication_acknowledged -ne $true }
        if (-not $commonIdentityValid -or
            -not ($preCommitIdentityValid -or $postCommitIdentityValid) -or
            -not $documentationIdentityValid -or
            -not $phaseEvidenceValid -or
            -not $publicationIdentityValid) {
            throw "refusing to write a structurally unsafe production-baseline reconciliation marker"
        }
    }
    $parent = Split-Path -Parent $activeMarkerPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $leaf = Split-Path -Leaf $activeMarkerPath
    $temp = Join-Path $parent (".{0}.{1}.tmp" -f $leaf, [guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent (".{0}.{1}.bak" -f $leaf, [guid]::NewGuid().ToString("N"))
    $replacementVerified = $false
    try {
        $markerJson = $marker | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText(
            $temp,
            $markerJson,
            (New-Object System.Text.UTF8Encoding($false))
        )
        if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
            if ($productionBaselineReconciliationMode -or $ExpectedCurrentSha256) {
                if ($ExpectedCurrentSha256 -notmatch '^[0-9a-f]{64}$' -or
                    (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ne
                        $ExpectedCurrentSha256.ToLowerInvariant()) {
                    throw "active quiet-merge marker changed before atomic replacement"
                }
            }
            [IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)
        }
        else {
            if ($ExpectedCurrentSha256) {
                throw "active quiet-merge marker disappeared before atomic replacement"
            }
            [IO.File]::Move($temp, $activeMarkerPath)
        }
        $writtenRaw = [IO.File]::ReadAllText($activeMarkerPath, [Text.Encoding]::UTF8)
        $writtenMarker = $writtenRaw | ConvertFrom-Json
        if ($writtenRaw -cne $markerJson -or
            [string]$writtenMarker.schema -cne "quiet_window_merge_in_progress_v0.1" -or
            [string]$writtenMarker.phase -cne $Phase) {
            throw "active quiet-merge marker failed atomic write/readback identity proof"
        }
        if ($productionBaselineReconciliationMode) {
            $script:reconciliationMarkerSha256 =
                (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        }
        $replacementVerified = $true
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        # Once File.Replace crosses the rename boundary, the new marker can be
        # fully active even if a later readback/hash check throws. Retain the
        # old byte-exact backup until the replacement is completely verified;
        # callers then preserve an old-or-new boot-safe marker rather than
        # falsely claiming the prior marker necessarily remained active.
        if ($replacementVerified) {
            Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-ReconciliationMarker {
    param([Parameter(Mandatory = $true)][string]$Phase)

    Write-QuietMergeMarker -Phase $Phase -ExpectedCurrentSha256 $reconciliationMarkerSha256
    if ($reconciliationMarkerSha256 -notmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ne
            $reconciliationMarkerSha256) {
        throw "production-baseline reconciliation marker hash/readback proof failed"
    }
}

function Get-ReconciliationSha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Assert-ReconciliationSchedulerRpcBytes {
    $expected = [string]$reconciliationSchedulerRpcSha256
    if ($expected -notmatch '^[0-9a-f]{64}$' -or
        -not (Test-Path -LiteralPath $reconciliationSchedulerRpcScript -PathType Leaf)) {
        throw "Scheduler RPC helper does not have a frozen safety-tip identity"
    }
    $actual = (
        Get-FileHash -LiteralPath $reconciliationSchedulerRpcScript `
            -Algorithm SHA256 -ErrorAction Stop
    ).Hash.ToLowerInvariant()
    if ($actual -cne $expected) {
        throw "Scheduler RPC helper changed after its safety-tip proof"
    }
}

function Invoke-ReconciliationOwnedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Tokens,
        [Parameter(Mandatory = $true)][ValidateRange(1, 1200)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][datetimeoffset]$DeadlineUtc,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not $reconciliationOwnedChildInitialized) {
        throw "kill-on-close child runtime is not initialized"
    }
    $job = $null
    $process = $null
    $completed = $false
    $exitCode = $null
    $cleanupError = $null
    $cleanupDeadlineUtc = $DeadlineUtc.AddMilliseconds(
        $reconciliationChildTerminationMilliseconds
    )
    try {
        $remainingBeforeLaunch = [int64][Math]::Floor(
            ($DeadlineUtc - [datetimeoffset]::UtcNow).TotalMilliseconds
        )
        if ($remainingBeforeLaunch -le 0) {
            throw [TimeoutException]::new("$Label absolute deadline closed before child launch")
        }
        $job = New-WeatherKillOnCloseJob
        $argumentString = ConvertTo-WeatherWindowsArgumentString -Tokens $Tokens
        $process = Start-WeatherProcessInJob `
            -Job $job -FilePath $FilePath -ArgumentString $argumentString `
            -WorkingDirectory $repo
        # Recompute immediately before the blocking wait. Marker journaling or
        # process creation may have consumed part of the original relative
        # budget; neither can extend the immutable UTC request boundary.
        $remainingAtWait = [int64][Math]::Floor(
            ($DeadlineUtc - [datetimeoffset]::UtcNow).TotalMilliseconds
        )
        $waitMilliseconds = [int][Math]::Min(
            [int64]$TimeoutSeconds * 1000,
            [Math]::Max([int64]0, $remainingAtWait)
        )
        if ($waitMilliseconds -gt 0) {
            $completed = $process.WaitForExit($waitMilliseconds)
        }
        if ($completed) { $exitCode = [int]$process.ExitCode }
    }
    finally {
        if ($null -ne $job) {
            try {
                # Always close the complete helper tree, even after the root
                # exits normally. A helper-created descendant is never allowed
                # to outlive the owning RPC boundary. Clamp proof time to the
                # separate cleanup deadline; the identity factory leaves a
                # further margin before PT15M/04:00 for bounded result parsing.
                $remainingCleanupMilliseconds = [int64][Math]::Floor(
                    ($cleanupDeadlineUtc - [datetimeoffset]::UtcNow).TotalMilliseconds
                )
                $cleanupWaitMilliseconds = [int][Math]::Min(
                    [int64]$reconciliationChildTerminationMilliseconds,
                    [Math]::Max([int64]0, $remainingCleanupMilliseconds)
                )
                $job.TerminateAndWait($cleanupWaitMilliseconds)
                if ([datetimeoffset]::UtcNow -gt $cleanupDeadlineUtc) {
                    throw [TimeoutException]::new(
                        "$Label child-tree proof crossed its cleanup deadline"
                    )
                }
            }
            catch { $cleanupError = $_.Exception.Message }
            finally { $job.Dispose() }
        }
        if ($null -ne $process) { $process.Dispose() }
    }
    if ($cleanupError) {
        throw "$Label child-tree termination could not be proved: $cleanupError"
    }
    if (-not $completed) {
        throw [TimeoutException]::new("$Label reached its absolute UTC/wall-clock deadline; helper tree terminated")
    }
    return [PSCustomObject]@{ exit_code = $exitCode }
}

function New-ReconciliationSchedulerRpcIdentity {
    param(
        [Parameter(Mandatory = $true)][datetime]$LogicalBoundary,
        [Parameter(Mandatory = $true)][ValidateRange(1, 300)][int]$MaximumSeconds
    )

    $logicalNow = Get-Date
    # Five seconds are available for TerminateAndWait proof and a further
    # three seconds remain for bounded result parsing before the logical
    # containment boundary. The helper receives the shorter request deadline.
    $remaining = [int][Math]::Floor(($LogicalBoundary - $logicalNow).TotalSeconds) -
        $reconciliationChildBoundaryReserveSeconds
    $allowed = [Math]::Min($MaximumSeconds, $remaining)
    if ($allowed -lt 1) {
        throw "no Scheduler RPC budget remains before the absolute containment boundary"
    }
    $deadline = [datetimeoffset]::UtcNow.AddSeconds($allowed)
    return [PSCustomObject]@{
        request_id = [guid]::NewGuid().ToString("N")
        deadline = $deadline
        deadline_utc = $deadline.UtcDateTime.ToString(
            "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",
            [Globalization.CultureInfo]::InvariantCulture
        )
        timeout_seconds = [int]$allowed
    }
}

function Invoke-ReconciliationSchedulerRpc {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("ReadExecutionTapeTask", "ReadPushSnapshot", "StartPush", "StopPush")]
        [string]$Operation,
        [Parameter(Mandatory = $true)][object]$Identity,
        [string]$MarkerSha256 = "",
        [ValidateRange(0, 2)][int]$StopOrdinal = 0
    )

    $payload = [ordered]@{
        schema = "production_baseline_scheduler_rpc_request_v0.1"
        request_id = [string]$Identity.request_id
        operation = $Operation
        deadline_utc = [string]$Identity.deadline_utc
        repo_root = $repo
    }
    if ($Operation -ne "ReadExecutionTapeTask") {
        $payload.task_xml_sha256 = "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    }
    if ($Operation -in @("StartPush", "StopPush")) {
        if ($MarkerSha256 -notmatch '^[0-9a-f]{64}$') {
            throw "$Operation requires the exact active-marker SHA256"
        }
        $payload.marker_path = $activeMarkerPath
        $payload.marker_sha256 = $MarkerSha256
    }
    if ($Operation -eq "StopPush") {
        if ($StopOrdinal -notin @(1, 2)) { throw "StopPush requires ordinal one or two" }
        $payload.stop_ordinal = $StopOrdinal
    }
    $requestJson = $payload | ConvertTo-Json -Depth 5 -Compress
    $requestBytes = (New-Object System.Text.UTF8Encoding($false, $true)).GetBytes($requestJson)
    $requestBase64 = [Convert]::ToBase64String($requestBytes)
    $requestSha256 = Get-ReconciliationSha256Hex -Bytes $requestBytes
    if ($Operation -eq "StartPush") { $script:pushStartRpcRequestSha256 = $requestSha256 }
    if ($Operation -eq "StopPush") { $script:pushStopRpcRequestSha256 = $requestSha256 }

    $resultPath = Join-Path ([IO.Path]::GetFullPath([IO.Path]::GetTempPath())) (
        "weather-production-baseline-scheduler-rpc-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    try {
        Assert-ReconciliationSchedulerRpcBytes
        $processResult = Invoke-ReconciliationOwnedProcess `
            -FilePath $reconciliationPowerShellExecutable `
            -Tokens @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $reconciliationSchedulerRpcScript,
                "-Operation", $Operation,
                "-RequestBase64", $requestBase64,
                "-ResultPath", $resultPath
            ) `
            -TimeoutSeconds ([int]$Identity.timeout_seconds) `
            -DeadlineUtc ([datetimeoffset]$Identity.deadline) `
            -Label "Scheduler RPC $Operation"
        if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
            throw "Scheduler RPC $Operation returned without an exclusive result"
        }
        $resultItem = Get-Item -LiteralPath $resultPath -ErrorAction Stop
        if ($resultItem.Length -le 0 -or $resultItem.Length -gt 131072) {
            throw "Scheduler RPC $Operation result is outside the fixed byte bound"
        }
        $resultBytes = [IO.File]::ReadAllBytes($resultPath)
        $resultRaw = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($resultBytes)
        $result = $resultRaw | ConvertFrom-Json -ErrorAction Stop
        if ([string]$result.schema -cne "production_baseline_scheduler_rpc_result_v0.1" -or
            [string]$result.request_id -cne [string]$Identity.request_id -or
            [string]$result.operation -cne $Operation -or
            [int]$processResult.exit_code -ne 0 -or $result.ok -ne $true) {
            $boundedError = [string]$result.error_message
            if ($boundedError.Length -gt 512) { $boundedError = $boundedError.Substring(0, 512) }
            throw "Scheduler RPC $Operation failed closed: $boundedError"
        }
        $completedAt = [datetimeoffset]::Parse([string]$result.completed_at_utc)
        if ($completedAt -gt [datetimeoffset]$Identity.deadline) {
            throw "Scheduler RPC $Operation completed after its request deadline"
        }
        $result | Add-Member -NotePropertyName request_sha256 -NotePropertyValue $requestSha256
        return $result
    }
    finally {
        Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-ReconciliationSchedulerReadIdentity {
    $now = Get-Date
    $logicalBoundary = $now.Date.AddHours(4)
    if ($null -ne $pushContainmentDeadline -and
        [datetime]$pushContainmentDeadline -lt $logicalBoundary) {
        $logicalBoundary = [datetime]$pushContainmentDeadline
    }
    if ($null -ne $pushContainmentStopAt -and
        $oneShotPushStopCount -eq 0 -and
        [datetime]$pushContainmentStopAt -lt $logicalBoundary) {
        # Before the first containment claim, every Scheduler read must leave
        # the complete Stop reserve untouched.  At/after the reserve edge the
        # identity calculation fails closed, and the drain catch below claims
        # Stop instead of launching another potentially hung read helper.
        $logicalBoundary = [datetime]$pushContainmentStopAt
    }
    return New-ReconciliationSchedulerRpcIdentity `
        -LogicalBoundary $logicalBoundary -MaximumSeconds 15
}

function Assert-ReconciliationPushSnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$Snapshot,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Ready", "Running", "Queued")][string[]]$AllowedStates
    )

    $required = @(
        "schema", "request_id", "operation", "ok", "completed_at_utc",
        "task_name", "task_path", "match_count", "state", "task_xml_base64",
        "task_xml_sha256", "enabled", "principal_user_id",
        "principal_logon_type", "principal_run_level", "action_execute",
        "action_arguments", "action_working_directory", "trigger_count",
        "multiple_instances", "execution_time_limit", "start_when_available",
        "last_run_time", "last_task_result", "request_sha256"
    )
    $actual = @($Snapshot.PSObject.Properties.Name)
    if (@($required | Where-Object { $actual -cnotcontains $_ }).Count -ne 0 -or
        @($actual | Where-Object { $required -cnotcontains $_ }).Count -ne 0) {
        throw "WeatherOneShotPush structured snapshot has an unexpected shape"
    }
    try { $taskXmlBytes = [Convert]::FromBase64String([string]$Snapshot.task_xml_base64) }
    catch { throw "WeatherOneShotPush XML evidence is not base64" }
    if ($taskXmlBytes.Length -le 0 -or $taskXmlBytes.Length -gt 65536 -or
        (Get-ReconciliationSha256Hex -Bytes $taskXmlBytes) -cne
            "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05" -or
        [string]$Snapshot.task_xml_sha256 -cne
            "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05") {
        throw "WeatherOneShotPush XML evidence does not match the reviewed definition"
    }
    $expectedWorkingDirectory = [IO.Path]::GetFullPath($repo).TrimEnd('\')
    $actualWorkingDirectory = try {
        [IO.Path]::GetFullPath([string]$Snapshot.action_working_directory).TrimEnd('\')
    }
    catch { "" }
    $expectedArguments = "/c git -C $repo push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
    $expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try { $currentSid = [string]$currentIdentity.User.Value }
    finally { $currentIdentity.Dispose() }
    if ([string]$Snapshot.operation -cne "ReadPushSnapshot" -or
        [int]$Snapshot.match_count -ne 1 -or
        [string]$Snapshot.task_name -cne "WeatherOneShotPush" -or
        [string]$Snapshot.task_path -cne "\" -or
        $AllowedStates -cnotcontains [string]$Snapshot.state -or
        $Snapshot.enabled -ne $true -or
        [string]$Snapshot.principal_user_id -ine "micha" -or
        $currentSid -cne $expectedPushSid -or
        [string]$Snapshot.principal_logon_type -cne "Interactive" -or
        [string]$Snapshot.principal_run_level -cne "Limited" -or
        [string]$Snapshot.action_execute -ine "cmd.exe" -or
        [string]$Snapshot.action_arguments -ine $expectedArguments -or
        $actualWorkingDirectory -ine $expectedWorkingDirectory -or
        [int]$Snapshot.trigger_count -ne 0 -or
        [string]$Snapshot.multiple_instances -cne "IgnoreNew" -or
        [string]$Snapshot.execution_time_limit -cne "PT15M" -or
        $Snapshot.start_when_available -ne $false) {
        throw "WeatherOneShotPush structured snapshot failed independent parent validation"
    }
    try {
        $Snapshot | Add-Member -NotePropertyName parsed_last_run_time `
            -NotePropertyValue ([datetime]$Snapshot.last_run_time)
        $Snapshot | Add-Member -NotePropertyName parsed_last_task_result `
            -NotePropertyValue ([long]$Snapshot.last_task_result)
    }
    catch { throw "WeatherOneShotPush runtime evidence is malformed" }
    return $Snapshot
}

function Get-ReconciliationPushSnapshot {
    param(
        [ValidateSet("Ready", "Running", "Queued")]
        [string[]]$AllowedStates = @("Ready", "Running", "Queued")
    )

    $identity = Get-ReconciliationSchedulerReadIdentity
    $snapshot = Invoke-ReconciliationSchedulerRpc `
        -Operation "ReadPushSnapshot" -Identity $identity
    return Assert-ReconciliationPushSnapshot -Snapshot $snapshot -AllowedStates $AllowedStates
}

function Test-ExecutionTapeActive {
    if (-not $productionBaselineReconciliationMode) {
        # Preserve the ordinary synchronized-merge contract exactly. Its
        # Scheduler access is outside the incident-bound reconciliation path
        # and therefore does not depend on the safety-tip child runtime.
        $task = Get-ScheduledTask `
            -TaskName "WeatherExecutionTapeSupervisor" `
            -ErrorAction SilentlyContinue
        if ($task -and [string]$task.State -ne "Disabled") { return $true }
        $statusPath = Join-Path $repo "data\snapshots\execution_tape_status.json"
        $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
        if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) { return $true }
        if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
            try {
                $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
                if ([string]$status.state -eq "STOPPED" -or [int]$status.pid -le 0) {
                    return $false
                }
                return $null -ne (
                    Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue
                )
            }
            catch { return $false }
        }
        return $false
    }

    # The Scheduler read is killable and bounded. Any unavailable or malformed
    # read is treated as active so incomplete evidence can never skip a required
    # execution-tape recovery proof.
    try {
        $identity = Get-ReconciliationSchedulerReadIdentity
        $task = Invoke-ReconciliationSchedulerRpc `
            -Operation "ReadExecutionTapeTask" -Identity $identity
        $required = @(
            "schema", "request_id", "operation", "ok", "completed_at_utc",
            "task_name", "task_path", "match_count", "state", "request_sha256"
        )
        $actual = @($task.PSObject.Properties.Name)
        if (@($required | Where-Object { $actual -cnotcontains $_ }).Count -ne 0 -or
            @($actual | Where-Object { $required -cnotcontains $_ }).Count -ne 0 -or
            [string]$task.operation -cne "ReadExecutionTapeTask" -or
            [int]$task.match_count -ne 1 -or
            [string]$task.task_name -cne "WeatherExecutionTapeSupervisor" -or
            [string]$task.task_path -cne "\") {
            throw "execution-tape task evidence failed independent validation"
        }
        if ([string]$task.state -cne "Disabled") { return $true }
    }
    catch {
        Note "execution-tape task read failed closed as active: $($_.Exception.Message)"
        return $true
    }
    $statusPath = Join-Path $repo "data\snapshots\execution_tape_status.json"
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) { return $true }
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ([string]$status.state -eq "STOPPED" -or [int]$status.pid -le 0) {
                return $false
            }
            return $null -ne (Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue)
        }
        catch { return $false }
    }
    return $false
}

function Assert-OneShotPushTask {
    param(
        [ValidateSet("Ready", "Running", "Queued")]
        [string[]]$AllowedStates = @("Ready"),
        [switch]$Quiet,
        [switch]$PassThru
    )

    if (-not $productionBaselineReconciliationMode) {
        # Keep the ordinary path's established direct task attestation and
        # return shape. Only the one-time reconciliation mode is required to
        # cross the killable child-RPC seam.
        try {
            $pushTasks = @(
                Get-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop
            )
        }
        catch {
            throw "WeatherOneShotPush is unavailable: $($_.Exception.Message)"
        }
        if ($pushTasks.Count -ne 1) {
            throw "WeatherOneShotPush must resolve to exactly one scheduled task; found $($pushTasks.Count)"
        }
        $pushTask = $pushTasks[0]
        $expectedPushTaskXmlSha256 =
            "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
        try {
            $pushTaskXml = [string](Export-ScheduledTask `
                    -TaskName "WeatherOneShotPush" -TaskPath "\" -ErrorAction Stop)
            $pushTaskSha = [Security.Cryptography.SHA256]::Create()
            try {
                $actualPushTaskXmlSha256 = ([BitConverter]::ToString(
                        $pushTaskSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pushTaskXml))
                    ) -replace '-', '').ToLowerInvariant()
            }
            finally { $pushTaskSha.Dispose() }
        }
        catch {
            throw "WeatherOneShotPush definition could not be hash-verified: $($_.Exception.Message)"
        }
        if ($actualPushTaskXmlSha256 -ne $expectedPushTaskXmlSha256) {
            throw "WeatherOneShotPush task XML changed from the reviewed trigger/settings/action contract"
        }
        $pushActions = @($pushTask.Actions)
        $pushTriggers = @($pushTask.Triggers)
        $expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
        $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $expectedWorkingDirectory = [IO.Path]::GetFullPath($repo).TrimEnd('\')
        $actualWorkingDirectory = try {
            [IO.Path]::GetFullPath([string]$pushActions[0].WorkingDirectory).TrimEnd('\')
        }
        catch { "" }
        $expectedPushArguments =
            '/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1'
        $pushTaskBound = (
            [string]$pushTask.TaskPath -ceq "\" -and
            $AllowedStates -ccontains [string]$pushTask.State -and
            $pushTask.Settings.Enabled -eq $true -and
            [string]$pushTask.Principal.UserId -ieq "micha" -and
            $currentSid -ceq $expectedPushSid -and
            [string]$pushTask.Principal.LogonType -ceq "Interactive" -and
            [string]$pushTask.Principal.RunLevel -ceq "Limited" -and
            $pushTriggers.Count -eq 0 -and
            [string]$pushTask.Settings.MultipleInstances -ceq "IgnoreNew" -and
            [string]$pushTask.Settings.ExecutionTimeLimit -ceq "PT15M" -and
            $pushTask.Settings.StartWhenAvailable -eq $false -and
            $pushActions.Count -eq 1 -and
            [string]$pushActions[0].Execute -ieq "cmd.exe" -and
            [string]$pushActions[0].Arguments -ieq $expectedPushArguments -and
            $actualWorkingDirectory -ieq $expectedWorkingDirectory
        )
        if (-not $pushTaskBound) {
            throw "WeatherOneShotPush is not exactly bound to the enabled current-user Interactive/Limited git-push contract"
        }
        if (-not $Quiet) { Note "WeatherOneShotPush exact publication binding passed" }
        if ($PassThru) { return $pushTask }
        return
    }

    $snapshot = Get-ReconciliationPushSnapshot -AllowedStates $AllowedStates
    if (-not $Quiet) { Note "WeatherOneShotPush exact bounded publication binding passed" }
    if ($PassThru) { return $snapshot }
}

function Get-ReconciliationOneShotPushTaskInfo {
    $snapshot = Get-ReconciliationPushSnapshot
    return [PSCustomObject]@{
        last_run_time = [datetime]$snapshot.parsed_last_run_time
        last_task_result = [long]$snapshot.parsed_last_task_result
    }
}

function Get-ReconciliationOneShotPushState {
    return Get-ReconciliationPushSnapshot
}

function Get-ReconciliationPublicationAck {
    param([Parameter(Mandatory = $true)][datetime]$Boundary)

    if ((Get-Date) -ge $Boundary) {
        throw "absolute publication boundary closed before acknowledgement"
    }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $localRows = @(& git -C $repo rev-parse HEAD master origin/master)
        $localExit = $LASTEXITCODE
        try {
            $remoteResult = Invoke-ReconciliationBoundedGit -Arguments @(
                "ls-remote", "--exit-code", "--refs",
                $reconciliationCanonicalOrigin, "refs/heads/master"
            ) -LogicalBoundary $Boundary
            $remoteRows = @($remoteResult.stdout)
            $remoteExit = [int]$remoteResult.exit_code
        }
        catch {
            $remoteRows = @()
            $remoteExit = -1
            Note "bounded canonical publication acknowledgement failed: $($_.Exception.Message)"
        }
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ((Get-Date) -ge $Boundary) {
        throw "absolute publication boundary closed during acknowledgement"
    }
    $remoteParts = if ($remoteRows.Count -eq 1) {
        @(([string]$remoteRows[0]).Trim() -split '\s+')
    }
    else { @() }
    $localExact = $localExit -eq 0 -and $localRows.Count -eq 3 -and
        @($localRows | Where-Object {
                ([string]$_).Trim().ToLowerInvariant() -cne $mergeCommit
            }).Count -eq 0
    $localStillUnpublished = $localExit -eq 0 -and $localRows.Count -eq 3 -and
        ([string]$localRows[0]).Trim().ToLowerInvariant() -ceq $mergeCommit -and
        ([string]$localRows[1]).Trim().ToLowerInvariant() -ceq $mergeCommit -and
        ([string]$localRows[2]).Trim().ToLowerInvariant() -ceq
            $reconciliationPublishedTarget
    $remoteExact = $remoteExit -eq 0 -and $remoteParts.Count -eq 2 -and
        $remoteParts[0].ToLowerInvariant() -ceq $mergeCommit -and
        $remoteParts[1] -ceq "refs/heads/master"
    $remoteStillTarget = $remoteExit -eq 0 -and $remoteParts.Count -eq 2 -and
        $remoteParts[0].ToLowerInvariant() -ceq $reconciliationPublishedTarget -and
        $remoteParts[1] -ceq "refs/heads/master"
    return [PSCustomObject]@{
        local_exact = $localExact
        local_still_unpublished = $localStillUnpublished
        remote_exact = $remoteExact
        remote_still_target = $remoteStillTarget
        local_exit = $localExit
        remote_exit = $remoteExit
    }
}

function Assert-ReconciliationMutationResult {
    param(
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][ValidateSet("StartPush", "StopPush")][string]$Operation,
        [ValidateRange(0, 2)][int]$StopOrdinal = 0
    )

    if ([string]$Result.operation -cne $Operation -or
        [string]$Result.task_name -cne "WeatherOneShotPush" -or
        [string]$Result.task_path -cne "\" -or
        [string]$Result.task_xml_sha256 -cne
            "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05" -or
        $Result.mutation_authority_claimed -ne $true -or
        $Result.mutation_dispatched -ne $true -or
        [string]$Result.pre_state -notin @("Ready", "Running", "Queued") -or
        [string]$Result.request_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "$Operation result failed independent parent validation"
    }
    if ($Operation -eq "StopPush" -and [int]$Result.stop_ordinal -ne $StopOrdinal) {
        throw "StopPush result ordinal does not match the journaled request"
    }
    try {
        $null = [datetime]$Result.pre_last_run_time
        $null = [long]$Result.pre_last_task_result
    }
    catch { throw "$Operation pre-mutation runtime evidence is malformed" }
}

function Invoke-ReconciliationOneShotPushTask {
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][string]$MarkerSha256
    )

    if ($oneShotPushStartCount -ne 0) {
        throw "WeatherOneShotPush has already been invoked by this process"
    }
    $script:oneShotPushStartCount++
    $result = Invoke-ReconciliationSchedulerRpc `
        -Operation "StartPush" -Identity $Identity -MarkerSha256 $MarkerSha256
    Assert-ReconciliationMutationResult -Result $result -Operation "StartPush"
}

function Invoke-ReconciliationOneShotPushStop {
    param(
        [Parameter(Mandatory = $true)][object]$Identity,
        [Parameter(Mandatory = $true)][string]$MarkerSha256,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2)][int]$StopOrdinal
    )

    if (-not $publicationInvoked -or $oneShotPushStartCount -ne 1 -or
        -not $oneShotPushStopAttempted -or $oneShotPushStopCount -lt 1) {
        throw "WeatherOneShotPush containment stop is not bound to the sole attempted invocation"
    }
    $result = Invoke-ReconciliationSchedulerRpc `
        -Operation "StopPush" -Identity $Identity -MarkerSha256 $MarkerSha256 `
        -StopOrdinal $StopOrdinal
    Assert-ReconciliationMutationResult `
        -Result $result -Operation "StopPush" -StopOrdinal $StopOrdinal
}

function Request-ReconciliationOneShotPushContainment {
    param([Parameter(Mandatory = $true)][datetime]$LogicalBoundary)

    if ($oneShotPushStopExhausted -or
        $oneShotPushStopCount -ge $reconciliationPushStopAttemptLimit) {
        if (-not $oneShotPushStopExhausted) {
            $script:oneShotPushStopExhausted = $true
            try { Write-ReconciliationMarker -Phase "documented_unpublished" }
            catch {
                Note "containment-stop exhaustion marker update failed; attempted marker and lease remain authoritative: $($_.Exception.Message)"
            }
            Note "WeatherOneShotPush containment stop attempt limit exhausted; no further Scheduler mutation, retaining lease for terminal/manual intervention"
        }
        return
    }

    try {
        $stopIdentity = New-ReconciliationSchedulerRpcIdentity `
            -LogicalBoundary $LogicalBoundary -MaximumSeconds 20
    }
    catch {
        # No mutation claim exists yet, so do not misreport a Stop attempt or
        # write a post-boundary marker.  Exhaust the authority locally and keep
        # the lease/drain alive until exact terminal proof or the absolute
        # report-only boundary path records conservative containment evidence.
        $script:oneShotPushStopExhausted = $true
        Note "WeatherOneShotPush containment Stop identity/budget was unavailable; no Stop helper was launched and the lease remains held until terminal proof or the absolute boundary: $($_.Exception.Message)"
        return
    }
    $script:oneShotPushStopAttempted = $true
    $script:oneShotPushStopCount++
    $script:pushStopRpcRequestId = [string]$stopIdentity.request_id
    $script:pushStopRpcDeadlineUtc = [string]$stopIdentity.deadline_utc
    try {
        Write-ReconciliationMarker -Phase "documented_unpublished"
        $stopMarkerSha256 = $reconciliationMarkerSha256
    }
    catch {
        $script:oneShotPushStopExhausted = $true
        Note "containment-attempt marker update failed; no Stop helper was launched: $($_.Exception.Message)"
        return
    }
    try {
        Invoke-ReconciliationOneShotPushStop `
            -Identity $stopIdentity -MarkerSha256 $stopMarkerSha256 `
            -StopOrdinal $oneShotPushStopCount
        Note "WeatherOneShotPush reached its containment deadline; exact singleton task stop requested through the bounded helper (attempt $oneShotPushStopCount)"
    }
    catch {
        if ($_.Exception -is [TimeoutException]) { $script:pushStopRpcTimedOut = $true }
        # A thrown/lost Stop response is itself ambiguous. Never retry a
        # mutating RPC; retain terminal non-PASS evidence instead.
        $script:oneShotPushStopExhausted = $true
        try { Write-ReconciliationMarker -Phase "documented_unpublished" }
        catch { Note "ambiguous Stop marker update also failed: $($_.Exception.Message)" }
        Note "WeatherOneShotPush containment Stop became uncertain; no further Scheduler mutation is allowed: $($_.Exception.Message)"
    }
}

if ($AttemptReportPath) {
    if (-not [IO.Path]::IsPathRooted($AttemptReportPath)) {
        throw "AttemptReportPath must be an absolute path"
    }
    $AttemptReportPath = [IO.Path]::GetFullPath($AttemptReportPath)
    $attemptReportParent = Split-Path -Parent $AttemptReportPath
    if (-not (Test-Path -LiteralPath $attemptReportParent -PathType Container)) {
        throw "AttemptReportPath parent directory does not exist: $attemptReportParent"
    }
    if (Test-Path -LiteralPath $AttemptReportPath) {
        throw "AttemptReportPath is immutable and already exists: $AttemptReportPath"
    }
    if ($AttemptReportPath -ieq $reportPath -or $AttemptReportPath -ieq $historyPath) {
        throw "AttemptReportPath must not reuse a mutable quiet-merge report path"
    }
}

$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
if ($ExpectedTip -and $ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
$ExpectedBaseline = $ExpectedBaseline.Trim().ToLowerInvariant()
if ($ExpectedBaseline -and $ExpectedBaseline -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedBaseline must be a full 40-character hexadecimal commit SHA"
}
$ExpectedLocalBaseline = $ExpectedLocalBaseline.Trim().ToLowerInvariant()
$ExpectedPublishedTarget = $ExpectedPublishedTarget.Trim().ToLowerInvariant()
$ExpectedSourceTip = $ExpectedSourceTip.Trim().ToLowerInvariant()
$ExpectedSourceTree = $ExpectedSourceTree.Trim().ToLowerInvariant()

$reconciliationLocalBaseline = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
$reconciliationPublishedTarget = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
$reconciliationReviewedParent = "a24cf0f41bf0b321c5c813820594c56198a58d1a"
$reconciliationLocalTree = "5281cd8ebff233e576a0b21d138a892c8c6c956c"
$reconciliationPublishedTree = "6df5bac16d8c780c35b4601941eaca1137ea7070"
$reconciliationCanonicalOrigin = "https://github.com/michaelbooth1/weather.git"
$reconciliationPushRuntimeLimit = [Xml.XmlConvert]::ToTimeSpan("PT15M")
$reconciliationPushTerminalReserve = [timespan]::FromMinutes(1)
$reconciliationPushStopAttemptLimit = 2
$reconciliationExpectedConfigBlobs = [ordered]@{
    "config/locations.json" = "dcc595e2a0cbe73e8d4d67a30aab4def1176ee06"
    "config/location_market_events.json" = "189151516a47166f69c64ad0b9612466614a7fbb"
}

function Stop-Reconciliation {
    param(
        [Parameter(Mandatory = $true)][string]$Detail,
        [string]$Stage = "abort",
        [ValidateRange(1, 4)][int]$ExitCode = 1,
        [bool]$Ok = $false
    )

    Note "RECONCILIATION NO-GO: $Detail"
    if (-not $DryRun) {
        Save-Report -ok $Ok -stage $Stage -detail $Detail
    }
    exit $ExitCode
}

function Assert-ReconciliationPublicationTimeBudget {
    param([Parameter(Mandatory = $true)][datetime]$Now)

    $windowEnd = $Now.Date.AddHours(4)
    if ($Now.Add($reconciliationPushRuntimeLimit).Add($reconciliationPushTerminalReserve) -ge
        $windowEnd) {
        throw "insufficient quiet-window time remains for the bounded task run plus terminal/stop reserve"
    }
    return $windowEnd
}

function Assert-ReconciliationQuietWindowOpen {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [switch]$RequirePublicationBudget
    )

    $now = Get-Date
    $windowStart = $now.Date.AddHours(1)
    $windowEnd = $now.Date.AddHours(4)
    if ($now -lt $windowStart -or $now -ge $windowEnd) {
        throw "01:00-04:00 quiet-window boundary is closed at $Stage"
    }
    if ($RequirePublicationBudget) {
        $null = Assert-ReconciliationPublicationTimeBudget -Now $now
    }
    return $windowEnd
}

function Start-ReconciliationBoundedPollSleep {
    param(
        [Parameter(Mandatory = $true)][datetime]$Boundary,
        [ValidateRange(1, 10)][int]$MaximumSeconds = 10
    )

    $now = Get-Date
    $next = $now.AddSeconds($MaximumSeconds)
    if ($Boundary -lt $next) { $next = $Boundary }
    $milliseconds = [int][Math]::Floor(($next - $now).TotalMilliseconds)
    if ($milliseconds -gt 0) { Start-Sleep -Milliseconds $milliseconds }
}

function Stop-ReconciliationAtAbsolutePublicationBoundary {
    $script:oneShotPushContainmentBreached = $true
    # Never begin another marker reproof/replacement after the hard boundary.
    # The earlier attempted marker already spends Start authority and is the
    # conservative durable truth if terminal acknowledgement cannot finish.
    Stop-Reconciliation `
        -Detail "PT15M/04:00 absolute publication boundary reached without exact terminal acknowledgement; invocation spent and publication state unknown" `
        -Stage "publication_state_uncertain" -ExitCode 3 -Ok $true
}

function Invoke-ReconciliationBoundedGit {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [ValidateRange(1, 120)][int]$TimeoutSeconds = 30,
        [datetime]$LogicalBoundary = [datetime]::MinValue
    )

    if (-not $reconciliationOwnedChildInitialized) {
        throw "kill-on-close child runtime is not initialized for bounded Git"
    }
    if ($LogicalBoundary -eq [datetime]::MinValue) {
        $logicalNow = Get-Date
        $LogicalBoundary = $logicalNow.Date.AddHours(4)
    }
    $identity = New-ReconciliationSchedulerRpcIdentity `
        -LogicalBoundary $LogicalBoundary -MaximumSeconds $TimeoutSeconds
    $gitCommands = @(Get-Command -Name "git.exe" -CommandType Application -ErrorAction SilentlyContinue)
    if ($gitCommands.Count -eq 0) {
        $gitCommands = @(Get-Command -Name "git" -CommandType Application -ErrorAction Stop)
    }
    $gitExecutable = [string]$gitCommands[0].Source
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $token = [guid]::NewGuid().ToString("N")
    $resultPath = Join-Path $tempRoot "weather-reconciliation-git-$token.json"
    $request = [ordered]@{
        schema = "production_baseline_bounded_git_request_v0.1"
        git = $gitExecutable
        arguments = @($Arguments)
    } | ConvertTo-Json -Depth 4 -Compress
    $requestBase64 = [Convert]::ToBase64String(
        (New-Object Text.UTF8Encoding($false, $true)).GetBytes($request)
    )
    $resultPathBase64 = [Convert]::ToBase64String(
        (New-Object Text.UTF8Encoding($false, $true)).GetBytes($resultPath)
    )
    # The child receives only canonical base64 literals embedded in an encoded
    # script. It writes bounded structured output because the suspended-before-
    # assignment Job launcher deliberately does not inherit redirect handles.
    $childCommand = @"
`$ErrorActionPreference = 'Stop'
`$utf8 = New-Object Text.UTF8Encoding(`$false, `$true)
`$request = `$utf8.GetString([Convert]::FromBase64String('$requestBase64')) | ConvertFrom-Json -ErrorAction Stop
`$resultPath = `$utf8.GetString([Convert]::FromBase64String('$resultPathBase64'))
`$rows = @(& ([string]`$request.git) @(`$request.arguments) 2>`$null)
`$gitExit = `$LASTEXITCODE
`$payload = [ordered]@{ schema = 'production_baseline_bounded_git_result_v0.1'; exit_code = [int]`$gitExit; stdout = @(`$rows | ForEach-Object { [string]`$_ }) } | ConvertTo-Json -Depth 4 -Compress
`$bytes = `$utf8.GetBytes(`$payload)
`$stream = [IO.FileStream]::new(`$resultPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { `$stream.Write(`$bytes, 0, `$bytes.Length); `$stream.Flush(`$true) } finally { `$stream.Dispose() }
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childCommand))
    try {
        $processResult = Invoke-ReconciliationOwnedProcess `
            -FilePath $reconciliationPowerShellExecutable `
            -Tokens @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", $encodedCommand
            ) `
            -TimeoutSeconds ([int]$identity.timeout_seconds) `
            -DeadlineUtc ([datetimeoffset]$identity.deadline) `
            -Label "bounded canonical Git read"
        if ([int]$processResult.exit_code -ne 0 -or
            -not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
            throw "bounded git child returned no exact result"
        }
        $resultItem = Get-Item -LiteralPath $resultPath -ErrorAction Stop
        if ($resultItem.Length -le 0 -or $resultItem.Length -gt 131072) {
            throw "bounded git result is outside the fixed byte bound"
        }
        $result = [IO.File]::ReadAllText($resultPath, [Text.Encoding]::UTF8) |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$result.schema -cne "production_baseline_bounded_git_result_v0.1") {
            throw "bounded git result schema is invalid"
        }
        return [PSCustomObject]@{
            exit_code = [int]$result.exit_code
            stdout = @($result.stdout | ForEach-Object { [string]$_ })
        }
    }
    finally {
        Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-ReconciliationGitValue {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$GitArgs
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $value = @(& git -C $Root @GitArgs)
        $gitExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($gitExit -ne 0 -or $value.Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$value[0])) {
        throw "git $($GitArgs -join ' ') did not return exactly one value in $Root"
    }
    return ([string]$value[0]).Trim()
}

function Assert-ReconciliationCanonicalOrigin {
    param([Parameter(Mandatory = $true)][string]$Root)

    $fetchUrl = Get-ReconciliationGitValue -Root $Root -GitArgs @("remote", "get-url", "origin")
    $pushUrl = Get-ReconciliationGitValue -Root $Root -GitArgs @("remote", "get-url", "--push", "origin")
    $pushUrlOverride = @(& git -C $Root config --get-all remote.origin.pushurl 2>$null)
    $pushRefOverride = @(& git -C $Root config --get-all remote.origin.push 2>$null)
    $urlRewrites = @(& git -C $Root config --get-regexp '^url\..*\.(insteadof|pushinsteadof)$' 2>$null)
    if ($fetchUrl -cne $reconciliationCanonicalOrigin -or
        $pushUrl -cne $reconciliationCanonicalOrigin -or
        $pushUrlOverride.Count -ne 0 -or $pushRefOverride.Count -ne 0 -or
        $urlRewrites.Count -ne 0) {
        throw "origin fetch/push identity is not the exact canonical no-rewrite contract in $Root"
    }
}

function Assert-ReconciliationRemotePublishedTarget {
    $remoteResult = Invoke-ReconciliationBoundedGit -Arguments @(
        "ls-remote", "--exit-code", "--refs",
        $reconciliationCanonicalOrigin, "refs/heads/master"
    )
    $remoteRows = @($remoteResult.stdout)
    $remoteExit = [int]$remoteResult.exit_code
    $remoteParts = if ($remoteRows.Count -eq 1) {
        @(([string]$remoteRows[0]).Trim() -split '\s+')
    }
    else { @() }
    if ($remoteExit -ne 0 -or $remoteParts.Count -ne 2 -or
        $remoteParts[0].ToLowerInvariant() -cne $reconciliationPublishedTarget -or
        $remoteParts[1] -cne "refs/heads/master") {
        throw "canonical remote master is not the exact frozen published target"
    }
}

function Assert-ReconciliationSourceWorktree {
    $sourceRoot = Get-ReconciliationGitValue -Root $PSScriptRoot -GitArgs @("rev-parse", "--show-toplevel")
    $sourceRoot = [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\')
    if ($sourceRoot -ieq [IO.Path]::GetFullPath($repo).TrimEnd('\')) {
        throw "reconciliation entry script must run from a separate isolated source worktree"
    }
    Assert-ReconciliationCanonicalOrigin -Root $sourceRoot
    $sourceStatus = @(& git --no-optional-locks -C $sourceRoot status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0 -or $sourceStatus.Count -ne 0) {
        throw "reconciliation source worktree must be exactly clean"
    }
    $sourceHead = (Get-ReconciliationGitValue -Root $sourceRoot -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant()
    $sourceTree = (Get-ReconciliationGitValue -Root $sourceRoot -GitArgs @("rev-parse", "HEAD^{tree}")).ToLowerInvariant()
    if ($sourceHead -cne $ExpectedSourceTip -or $sourceTree -cne $ExpectedSourceTree) {
        throw "isolated source worktree tip/tree does not match the frozen reconciliation contract"
    }
    & git -C $sourceRoot merge-base --is-ancestor $reconciliationReviewedParent $sourceHead 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "reconciliation safety tip does not descend from the exact reviewed parent"
    }
    & git -C $sourceRoot merge-base --is-ancestor $reconciliationPublishedTarget $sourceHead 2>$null
    if ($LASTEXITCODE -ne 0 -or $sourceHead -ceq $reconciliationPublishedTarget -or
        (Get-ReconciliationGitValue -Root $sourceRoot -GitArgs @(
                "merge-base", $reconciliationPublishedTarget, $sourceHead
            )).ToLowerInvariant() -cne $reconciliationPublishedTarget) {
        throw "reconciliation safety tip is not a strict descendant of the frozen published target"
    }
    $sourceSafetyDependencies = @(
        "scripts/ops/quiet_window_merge.ps1",
        "scripts/ops/production_baseline_scheduler_rpc.ps1",
        "scripts/ops/windows_kill_on_close_job.ps1",
        "scripts/ops/status.ps1",
        "scripts/ops/health_watchdog.ps1"
    )
    foreach ($relativePath in $sourceSafetyDependencies) {
        $trackedBlob = (Get-ReconciliationGitValue -Root $sourceRoot -GitArgs @(
                "rev-parse", "$sourceHead`:$relativePath"
            )).ToLowerInvariant()
        $diskBlob = (Get-ReconciliationGitValue -Root $sourceRoot -GitArgs @(
                "hash-object", "--", $relativePath
            )).ToLowerInvariant()
        $absolutePath = Join-Path $sourceRoot ($relativePath -replace '/', '\')
        if ($trackedBlob -cne $diskBlob -or
            -not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "safety-tip dependency is not the exact tracked blob: $relativePath"
        }
        $dependencySha256 = (
            Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256 -ErrorAction Stop
        ).Hash.ToLowerInvariant()
        $script:reconciliationDependencySha256["$relativePath@safety_tip"] = $dependencySha256
        if ($relativePath -ceq "scripts/ops/quiet_window_merge.ps1" -and
            $dependencySha256 -cne $ExpectedSelfSha256) {
            throw "entry script is not the SHA256-pinned safety-tip blob"
        }
    }
    return [PSCustomObject]@{ root = $sourceRoot; head = $sourceHead; tree = $sourceTree }
}

function Get-ReconciliationStatusRows {
    param([Parameter(Mandatory = $true)][string]$Root)
    $rows = @(& git --no-optional-locks -C $Root status --porcelain=v1 --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw "git status failed in $Root" }
    return @($rows | ForEach-Object { [string]$_ })
}

function Assert-ReconciliationExactDirtyConfig {
    param([Parameter(Mandatory = $true)][string]$Root)

    $rows = @(Get-ReconciliationStatusRows -Root $Root)
    $expectedRows = @(
        " M config/location_market_events.json",
        " M config/locations.json"
    )
    if ($rows.Count -ne $expectedRows.Count -or
        @($rows | Where-Object { $expectedRows -cnotcontains $_ }).Count -ne 0 -or
        @($expectedRows | Where-Object { $rows -cnotcontains $_ }).Count -ne 0) {
        throw "production status must contain exactly the two unstaged modified generated-config paths"
    }
}

function Assert-ReconciliationProductionIdentity {
    Assert-ReconciliationCanonicalOrigin -Root $repo
    $head = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant()
    $master = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "master^{commit}")).ToLowerInvariant()
    $originMaster = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "origin/master^{commit}")).ToLowerInvariant()
    $branch = Get-ReconciliationGitValue -Root $repo -GitArgs @("symbolic-ref", "--quiet", "--short", "HEAD")
    if ($branch -cne "master" -or $head -cne $reconciliationLocalBaseline -or
        $master -cne $reconciliationLocalBaseline -or
        $originMaster -cne $reconciliationPublishedTarget) {
        throw "production master/origin identity is not the exact authorized local-baseline/published-target topology"
    }
    if ((Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "$head^{tree}")).ToLowerInvariant() -cne
        $reconciliationLocalTree -or
        (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "$originMaster^{tree}")).ToLowerInvariant() -cne
        $reconciliationPublishedTree) {
        throw "production endpoint tree identity changed"
    }
    $productionSafetyTip = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
            "rev-parse", "$ExpectedSourceTip^{commit}"
        )).ToLowerInvariant()
    $productionSafetyTree = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
            "rev-parse", "$ExpectedSourceTip^{tree}"
        )).ToLowerInvariant()
    if ($productionSafetyTip -cne $ExpectedSourceTip -or
        $productionSafetyTree -cne $ExpectedSourceTree) {
        throw "production object database does not contain the exact frozen safety tip/tree"
    }
    & git -C $repo merge-base --is-ancestor $reconciliationPublishedTarget $ExpectedSourceTip 2>$null
    if ($LASTEXITCODE -ne 0 -or $ExpectedSourceTip -ceq $reconciliationPublishedTarget -or
        (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "merge-base", $reconciliationPublishedTarget, $ExpectedSourceTip
            )).ToLowerInvariant() -cne $reconciliationPublishedTarget) {
        throw "production object database does not prove the frozen safety tip is a strict descendant of T"
    }
    & git -C $repo merge-base --is-ancestor $reconciliationReviewedParent $ExpectedSourceTip 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "production object database does not prove the frozen safety tip descends from the reviewed parent"
    }
    & git -C $repo merge-base --is-ancestor $reconciliationLocalBaseline $reconciliationPublishedTarget 2>$null
    if ($LASTEXITCODE -ne 0 -or
        (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "merge-base", $reconciliationLocalBaseline, $reconciliationPublishedTarget
            )).ToLowerInvariant() -cne $reconciliationLocalBaseline) {
        throw "published target is not a strict descendant of the exact local baseline"
    }
    $guardParents = @((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-list", "--parents", "-n", "1", $reconciliationPublishedTarget
            )) -split '\s+')
    $guardChanges = @(& git -C $repo diff --name-only $reconciliationLocalBaseline $reconciliationPublishedTarget)
    $adoptedBootWouldTrustGuardAsConfigChild = (
        $guardParents.Count -eq 2 -and
        $guardParents[0].ToLowerInvariant() -ceq $reconciliationPublishedTarget -and
        $guardParents[1].ToLowerInvariant() -ceq $reconciliationLocalBaseline -and
        $guardChanges.Count -gt 0 -and
        @($guardChanges | Where-Object { $reconciliationExpectedConfigBlobs.Keys -cnotcontains $_ }).Count -eq 0
    )
    if ($adoptedBootWouldTrustGuardAsConfigChild) {
        throw "published target unexpectedly satisfies adopted boot's hard-reset premerge predicate"
    }
    foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
        $localBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-parse", "$reconciliationLocalBaseline`:$relativePath"
            )).ToLowerInvariant()
        $publishedBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-parse", "$reconciliationPublishedTarget`:$relativePath"
            )).ToLowerInvariant()
        if ($localBlob -cne [string]$reconciliationExpectedConfigBlobs[$relativePath] -or
            $publishedBlob -cne $localBlob) {
            throw "tracked endpoint config blob identity changed for $relativePath"
        }
    }
    Assert-ReconciliationExactDirtyConfig -Root $repo
    $markerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        throw "a prior quiet-window marker exists; this one-time mode has no generic resume path"
    }
    $mergeHeadPath = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "--git-path", "MERGE_HEAD"))
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) { $mergeHeadPath = Join-Path $repo $mergeHeadPath }
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        throw "a merge is already in progress"
    }
}

function Assert-ReconciliationDependencyBytes {
    param([ValidateSet("local_baseline", "published_target")][string]$Stage)

    $expected = [ordered]@{
        "scripts/ops/boot_recovery.ps1" = "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
        "scripts/ops/roll_verdict.ps1" = "3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881"
        "scripts/ops/workload_admission.ps1" = if ($Stage -eq "local_baseline") {
            "cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105"
        } else { "4117eb901d292952473c57425434593bed414fa2ed2fecee301fe56e8f893306" }
        "src/weather/operations/capture_recovery_check.py" = "814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895"
        "src/weather/operations/documentation_transaction.py" = "057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9"
        "src/weather/operations/execution_tape_supervisor.py" = "1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f"
    }
    foreach ($relativePath in $expected.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "required $Stage dependency is missing: $relativePath"
        }
        $actual = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        if ($actual -cne [string]$expected[$relativePath]) {
            throw "required $Stage dependency bytes changed: $relativePath"
        }
        $script:reconciliationDependencySha256["$relativePath@$Stage"] = $actual
    }
    if ($Stage -eq "published_target") {
        foreach ($relativePath in @(
                "scripts/ops/quiet_window_merge.ps1",
                "scripts/ops/production_baseline_scheduler_rpc.ps1",
                "scripts/ops/windows_kill_on_close_job.ps1",
                "scripts/ops/status.ps1",
                "scripts/ops/health_watchdog.ps1"
            )) {
            $expectedSafetySha = [string]$reconciliationDependencySha256["$relativePath@safety_tip"]
            $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
            if ($expectedSafetySha -notmatch '^[0-9a-f]{64}$' -or
                -not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $expectedSafetySha) {
                throw "adopted safety dependency bytes changed: $relativePath"
            }
            $script:reconciliationDependencySha256["$relativePath@$Stage"] = $expectedSafetySha
        }
    }
}

function Invoke-ReconciliationRollVerdict {
    $verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"
    $verdictJsonPath = Join-Path ([IO.Path]::GetTempPath()) (
        "weather-production-baseline-roll-{0}.json" -f [guid]::NewGuid().ToString("N")
    )
    $logicalNow = Get-Date
    $rollIdentity = New-ReconciliationSchedulerRpcIdentity `
        -LogicalBoundary $logicalNow.Date.AddHours(4) -MaximumSeconds 120
    $rollProcess = Invoke-ReconciliationOwnedProcess `
        -FilePath $reconciliationPowerShellExecutable `
        -Tokens @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $verdictScript,
            "-Base", $reconciliationLocalBaseline,
            "-Branch", $ExpectedSourceTip,
            "-JsonOut", $verdictJsonPath
        ) `
        -TimeoutSeconds ([int]$rollIdentity.timeout_seconds) `
        -DeadlineUtc ([datetimeoffset]$rollIdentity.deadline) `
        -Label "canonical roll verdict L-to-S"
    $rollVerdictExitCode = [int]$rollProcess.exit_code
    $exitCode = $rollVerdictExitCode
    $output = @(
        "kill-on-close roll_verdict completed exit=$exitCode base=$reconciliationLocalBaseline branch=$ExpectedSourceTip"
    )

    $readable = $false
    $payload = $null
    $jsonRaw = $null
    $jsonBytes = $null
    $jsonSha = $null
    if (Test-Path -LiteralPath $verdictJsonPath -PathType Leaf) {
        try {
            $jsonBytes = [IO.File]::ReadAllBytes($verdictJsonPath)
            $jsonRaw = [IO.File]::ReadAllText($verdictJsonPath, [Text.Encoding]::UTF8)
            $jsonSha = (Get-FileHash -LiteralPath $verdictJsonPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
            $payload = $jsonRaw | ConvertFrom-Json
            $generatedAt = [datetimeoffset]::Parse([string]$payload.generated_at)
            $expectedShortBase = Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-parse", "--short", $reconciliationLocalBaseline
            )
            $verdictMatchesExit = switch ($exitCode) {
                0 { [string]$payload.verdict -ceq "ROLL-FREE" }
                2 { [string]$payload.verdict -ceq "ROLL-FREE-IF-DORMANT" }
                3 { [string]$payload.verdict -ceq "ROLL-SENSITIVE" }
                default { $false }
            }
            $incompleteClosureProblems = @($payload.problems | Where-Object {
                    [string]$_ -match '(?i)(missing closure evidence|unreadable closure evidence|no source_scope_files|stale|dormant|tombstone)'
                })
            $observedAt = (Get-Date).ToUniversalTime()
            $verdictAgeMinutes = ($observedAt - $generatedAt.UtcDateTime).TotalMinutes
            $readable = (
                $verdictMatchesExit -and
                [string]$payload.branch -ceq $ExpectedSourceTip -and
                [string]$payload.base_ref -ceq $reconciliationLocalBaseline -and
                [string]$payload.base_sha -ceq $expectedShortBase -and
                @($payload.closures_used).Count -gt 0 -and
                $incompleteClosureProblems.Count -eq 0 -and
                $verdictAgeMinutes -ge 0 -and $verdictAgeMinutes -le 5
            )
        }
        catch { $readable = $false }
    }
    Remove-Item -LiteralPath $verdictJsonPath -Force -ErrorAction SilentlyContinue
    $rollVerdictReadable = $readable
    $rollFree = ($rollVerdictExitCode -eq 0 -and $rollVerdictReadable)
    return [PSCustomObject]@{
        exit_code = $exitCode
        readable = $readable
        payload = $payload
        json_raw = $jsonRaw
        json_bytes = $jsonBytes
        json_sha256 = $jsonSha
        transcript = ($output -join "`r`n")
    }
}

$reconciliationPythonExitCode = $null
function Invoke-ReconciliationPython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $logicalNow = Get-Date
    $identity = New-ReconciliationSchedulerRpcIdentity `
        -LogicalBoundary $logicalNow.Date.AddHours(4) -MaximumSeconds 120
    $token = [guid]::NewGuid().ToString("N")
    $resultPath = Join-Path ([IO.Path]::GetFullPath([IO.Path]::GetTempPath())) (
        "weather-reconciliation-python-$token.json"
    )
    $request = [ordered]@{
        schema = "production_baseline_bounded_python_request_v0.1"
        executable = $py
        arguments = @($Arguments)
    } | ConvertTo-Json -Depth 4 -Compress
    $utf8 = New-Object Text.UTF8Encoding($false, $true)
    $requestBase64 = [Convert]::ToBase64String($utf8.GetBytes($request))
    $resultPathBase64 = [Convert]::ToBase64String($utf8.GetBytes($resultPath))
    $childCommand = @"
`$ErrorActionPreference = 'Continue'
`$utf8 = New-Object Text.UTF8Encoding(`$false, `$true)
`$request = `$utf8.GetString([Convert]::FromBase64String('$requestBase64')) | ConvertFrom-Json -ErrorAction Stop
`$resultPath = `$utf8.GetString([Convert]::FromBase64String('$resultPathBase64'))
`$rows = @(& ([string]`$request.executable) @(`$request.arguments))
`$childExit = `$LASTEXITCODE
`$payload = [ordered]@{ schema = 'production_baseline_bounded_python_result_v0.1'; exit_code = [int]`$childExit; stdout = @(`$rows | ForEach-Object { [string]`$_ }) } | ConvertTo-Json -Depth 4 -Compress
`$bytes = `$utf8.GetBytes(`$payload)
`$stream = [IO.FileStream]::new(`$resultPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { `$stream.Write(`$bytes, 0, `$bytes.Length); `$stream.Flush(`$true) } finally { `$stream.Dispose() }
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childCommand))
    try {
        $processResult = Invoke-ReconciliationOwnedProcess `
            -FilePath $reconciliationPowerShellExecutable `
            -Tokens @(
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-EncodedCommand", $encodedCommand
            ) `
            -TimeoutSeconds ([int]$identity.timeout_seconds) `
            -DeadlineUtc ([datetimeoffset]$identity.deadline) `
            -Label "bounded reconciliation Python"
        if ([int]$processResult.exit_code -ne 0 -or
            -not (Test-Path -LiteralPath $resultPath -PathType Leaf)) {
            throw "bounded reconciliation Python returned no exact result"
        }
        $resultItem = Get-Item -LiteralPath $resultPath -ErrorAction Stop
        if ($resultItem.Length -le 0 -or $resultItem.Length -gt 1048576) {
            throw "bounded reconciliation Python result is outside the fixed byte bound"
        }
        $result = [IO.File]::ReadAllText($resultPath, [Text.Encoding]::UTF8) |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$result.schema -cne "production_baseline_bounded_python_result_v0.1") {
            throw "bounded reconciliation Python result schema is invalid"
        }
        $script:reconciliationPythonExitCode = [int]$result.exit_code
        @($result.stdout) | ForEach-Object { [string]$_ } | Write-Output
    }
    finally {
        Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    }
}

function Get-ReconciliationCaptureState {
    try {
        $raw = @(Invoke-ReconciliationPython -Arguments @(
                "-m", "weather.operations.capture_recovery_check",
                "--repo-root", $repo, "--json"
            ))
        $exitCode = $reconciliationPythonExitCode
        $state = (($raw -join "`n") | ConvertFrom-Json)
        if ($exitCode -ne 0) { $state.ok = $false }
        return $state
    }
    catch { return [PSCustomObject]@{ ok = $false; workers = @(); error = $_.Exception.Message } }
}

function Get-ReconciliationExecutionState {
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    try {
        $raw = @(Invoke-ReconciliationPython -Arguments @(
                "-m", "weather.operations.execution_tape_supervisor",
                "status", "--stale-after-seconds", "180"
            ))
        $exitCode = $reconciliationPythonExitCode
        $payload = (($raw -join "`n") | ConvertFrom-Json)
        $health = $payload.health
        $status = $payload.status
        $writerLock = Get-Content -LiteralPath $writerLockPath -Raw -ErrorAction Stop | ConvertFrom-Json
        $ok = (
            $exitCode -eq 0 -and
            @("RUNNING", "DEGRADED") -contains [string]$health.state -and
            $health.pid_alive -eq $true -and
            $health.runtime_identity_matches_current -eq $true -and
            [string]$health.evidence_integrity -ceq "PASS" -and
            [string]$status.state -ceq "CONNECTED" -and
            [string]$status.market -ceq "all" -and
            [string]$status.runner -ceq "managed_execution_tape" -and
            $status.managed_process.verified_at_capture -eq $true -and
            [int]$status.pid -gt 0 -and
            [int]$status.pid -eq [int]$status.managed_process.pid -and
            [int]$status.pid -eq [int]$writerLock.pid -and
            [int]$status.pid -eq [int]$writerLock.managed_process.pid -and
            [string]$status.managed_process.creation_time_token -cne "" -and
            [string]$status.managed_process.creation_time_token -ceq
                [string]$writerLock.managed_process.creation_time_token
        )
        return [PSCustomObject]@{
            ok = $ok
            source = [string]$status.runtime_identity.source_fingerprint
            heartbeat = if ($status.last_heartbeat) { [string]$status.last_heartbeat } else { [string]$status.updated_at_utc }
        }
    }
    catch { return [PSCustomObject]@{ ok = $false; source = $null; heartbeat = $null } }
}

function Test-ReconciliationCaptureProof {
    $capture = Get-ReconciliationCaptureState
    $coreOk = $capture.ok -eq $true -and @($capture.workers).Count -eq 3 -and
        @($capture.workers | Where-Object { $_.ok -ne $true }).Count -eq 0
    $execution = $null
    $executionOk = $true
    if ($executionTapeRecoveryRequired) {
        $execution = Get-ReconciliationExecutionState
        $executionOk = $execution.ok -eq $true
    }
    return [PSCustomObject]@{ ok = ($coreOk -and $executionOk); capture = $capture; execution = $execution }
}

function Get-ReconciliationRawConfigEvidence {
    param([Parameter(Mandatory = $true)][string]$Root)

    $evidence = [ordered]@{}
    foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
        $absolutePath = Join-Path $Root ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf)) {
            throw "required generated config is missing: $relativePath"
        }
        $item = Get-Item -LiteralPath $absolutePath -ErrorAction Stop
        $evidence[$relativePath] = [ordered]@{
            sha256 = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
            length = [long]$item.Length
        }
    }
    return $evidence
}

function New-ReconciliationRawSnapshot {
    param(
        [Parameter(Mandatory = $true)][object]$RollEvidence,
        [Parameter(Mandatory = $true)][object]$RawEvidence
    )

    $snapshotId = "{0}-{1}" -f (Get-Date -Format "yyyyMMddTHHmmssfff"), [guid]::NewGuid().ToString("N")
    $snapshotRoot = Join-Path $repo "data\alerts\production_baseline_reconciliation\$snapshotId"
    if (Test-Path -LiteralPath $snapshotRoot) { throw "snapshot destination already exists" }
    New-Item -ItemType Directory -Path $snapshotRoot -ErrorAction Stop | Out-Null
    $paths = [ordered]@{}
    $configContentSha256 = [ordered]@{}
    foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
        $sourcePath = Join-Path $repo ($relativePath -replace '/', '\')
        $snapshotRelative = "raw/$relativePath"
        $snapshotPath = Join-Path $snapshotRoot ($snapshotRelative -replace '/', '\')
        New-Item -ItemType Directory -Path (Split-Path -Parent $snapshotPath) -Force -ErrorAction Stop | Out-Null
        [IO.File]::WriteAllBytes($snapshotPath, [IO.File]::ReadAllBytes($sourcePath))
        $snapshotHash = (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        $snapshotLength = (Get-Item -LiteralPath $snapshotPath -ErrorAction Stop).Length
        if ($snapshotHash -cne [string]$RawEvidence[$relativePath].sha256 -or
            $snapshotLength -ne [long]$RawEvidence[$relativePath].length) {
            throw "raw snapshot readback changed bytes for $relativePath"
        }
        $paths[$relativePath] = [ordered]@{
            snapshot_path = ($snapshotPath.Substring($repo.Length).TrimStart('\') -replace '\\', '/')
            sha256 = $snapshotHash
            length = [long]$snapshotLength
        }
        $configContentSha256[$relativePath] = $snapshotHash
    }
    $rollTranscriptPath = Join-Path $snapshotRoot "roll-verdict-output.txt"
    [IO.File]::WriteAllText(
        $rollTranscriptPath,
        [string]$RollEvidence.transcript,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $rollTranscriptSha = (Get-FileHash -LiteralPath $rollTranscriptPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    $rollJsonRelative = $null
    if ($null -ne $RollEvidence.json_bytes) {
        $rollJsonPath = Join-Path $snapshotRoot "roll-verdict.json"
        [IO.File]::WriteAllBytes($rollJsonPath, [byte[]]$RollEvidence.json_bytes)
        if ((Get-FileHash -LiteralPath $rollJsonPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
            [string]$RollEvidence.json_sha256) {
            throw "roll-verdict JSON snapshot hash changed"
        }
        $rollJsonRelative = ($rollJsonPath.Substring($repo.Length).TrimStart('\') -replace '\\', '/')
    }
    $manifest = [ordered]@{
        schema = "production_baseline_reconciliation_snapshot_v0.1"
        created_at = (Get-Date).ToString("o")
        local_baseline = $reconciliationLocalBaseline
        published_target = $reconciliationPublishedTarget
        source_tip = $ExpectedSourceTip
        source_tree = $ExpectedSourceTree
        safety_tip = $ExpectedSourceTip
        safety_tree = $ExpectedSourceTree
        entry_sha256 = $ExpectedSelfSha256
        config = $paths
        reconciliation_config_content_sha256 = $configContentSha256
        roll_verdict = [ordered]@{
            explicit_base = $reconciliationLocalBaseline
            explicit_branch = $ExpectedSourceTip
            exit_code = [int]$RollEvidence.exit_code
            readable = [bool]$RollEvidence.readable
            json_path = $rollJsonRelative
            json_sha256 = $RollEvidence.json_sha256
            transcript_path = ($rollTranscriptPath.Substring($repo.Length).TrimStart('\') -replace '\\', '/')
            transcript_sha256 = $rollTranscriptSha
        }
        dependency_sha256 = $reconciliationDependencySha256
    }
    $manifestPath = Join-Path $snapshotRoot "manifest.json"
    $manifestTemp = Join-Path $snapshotRoot (".manifest.{0}.tmp" -f [guid]::NewGuid().ToString("N"))
    [IO.File]::WriteAllText(
        $manifestTemp,
        ($manifest | ConvertTo-Json -Depth 10),
        (New-Object System.Text.UTF8Encoding($false))
    )
    [IO.File]::Move($manifestTemp, $manifestPath)
    $manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    return [PSCustomObject]@{
        root = $snapshotRoot
        manifest_path = ($manifestPath.Substring($repo.Length).TrimStart('\') -replace '\\', '/')
        manifest_sha256 = $manifestSha
        paths = $paths
        roll_transcript_path = ($rollTranscriptPath.Substring($repo.Length).TrimStart('\') -replace '\\', '/')
        roll_transcript_sha256 = $rollTranscriptSha
        roll_json_path = $rollJsonRelative
    }
}

function Assert-ReconciliationSnapshot {
    if ($reconciliationSnapshotManifestSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "raw snapshot manifest identity was not established"
    }
    $manifestPath = Join-Path $repo ($reconciliationSnapshotManifestPath -replace '/', '\')
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
            $reconciliationSnapshotManifestSha256) {
        throw "raw snapshot manifest changed"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop | ConvertFrom-Json
    if ([string]$manifest.schema -cne "production_baseline_reconciliation_snapshot_v0.1" -or
        ([string]$manifest.local_baseline).ToLowerInvariant() -cne $reconciliationLocalBaseline -or
        ([string]$manifest.published_target).ToLowerInvariant() -cne $reconciliationPublishedTarget -or
        ([string]$manifest.source_tip).ToLowerInvariant() -cne $ExpectedSourceTip -or
        ([string]$manifest.source_tree).ToLowerInvariant() -cne $ExpectedSourceTree -or
        ([string]$manifest.safety_tip).ToLowerInvariant() -cne $ExpectedSourceTip -or
        ([string]$manifest.safety_tree).ToLowerInvariant() -cne $ExpectedSourceTree -or
        ([string]$manifest.entry_sha256).ToLowerInvariant() -cne $ExpectedSelfSha256 -or
        ([string]$manifest.roll_verdict.explicit_base).ToLowerInvariant() -cne $reconciliationLocalBaseline -or
        ([string]$manifest.roll_verdict.explicit_branch).ToLowerInvariant() -cne $ExpectedSourceTip -or
        [int]$manifest.roll_verdict.exit_code -ne [int]$rollVerdictExitCode) {
        throw "raw snapshot manifest immutable identities changed"
    }
    $manifestConfigHashes = @($manifest.reconciliation_config_content_sha256.PSObject.Properties)
    if ($manifestConfigHashes.Count -ne $reconciliationExpectedConfigBlobs.Count) {
        throw "raw snapshot manifest config hash map is incomplete"
    }
    foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
        $manifestHashProperty = $manifest.reconciliation_config_content_sha256.PSObject.Properties[$relativePath]
        if ($null -eq $manifestHashProperty -or
            [string]$manifestHashProperty.Value -cne [string]$rollbackContentSha256[$relativePath]) {
            throw "raw snapshot manifest config hash changed for $relativePath"
        }
    }
    $transcriptPath = Join-Path $repo ([string]$manifest.roll_verdict.transcript_path -replace '/', '\')
    if (-not (Test-Path -LiteralPath $transcriptPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $transcriptPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
            ([string]$manifest.roll_verdict.transcript_sha256).ToLowerInvariant()) {
        throw "roll-verdict transcript snapshot changed"
    }
    if ([string]$manifest.roll_verdict.json_path) {
        $rollJsonPath = Join-Path $repo ([string]$manifest.roll_verdict.json_path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $rollJsonPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $rollJsonPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                ([string]$manifest.roll_verdict.json_sha256).ToLowerInvariant()) {
            throw "roll-verdict JSON snapshot changed"
        }
    }
    foreach ($relativePath in $reconciliationSnapshotPaths.Keys) {
        $snapshot = $reconciliationSnapshotPaths[$relativePath]
        $snapshotPath = Join-Path $repo ([string]$snapshot.snapshot_path -replace '/', '\')
        $livePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $snapshotPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                [string]$snapshot.sha256 -or
            (Get-Item -LiteralPath $snapshotPath).Length -ne [long]$snapshot.length -or
            (Get-FileHash -LiteralPath $livePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                [string]$snapshot.sha256 -or
            (Get-Item -LiteralPath $livePath).Length -ne [long]$snapshot.length) {
            throw "raw snapshot/live byte proof failed for $relativePath"
        }
    }
}

function Assert-ReconciliationConfigCommit {
    param([Parameter(Mandatory = $true)][string]$Commit)

    $row = @((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-list", "--parents", "-n", "1", $Commit
            )) -split '\s+')
    $changes = @(& git -C $repo diff --name-only $reconciliationLocalBaseline $Commit)
    if ($LASTEXITCODE -ne 0 -or $row.Count -ne 2 -or
        $row[0].ToLowerInvariant() -cne $Commit.ToLowerInvariant() -or
        $row[1].ToLowerInvariant() -cne $reconciliationLocalBaseline -or
        $changes.Count -ne $reconciliationExpectedConfigBlobs.Count -or
        @($changes | Where-Object { $reconciliationExpectedConfigBlobs.Keys -cnotcontains $_ }).Count -ne 0) {
        throw "temporary config commit is not an exact one-parent config-only child of the local baseline"
    }
    Assert-ReconciliationSnapshot
    foreach ($relativePath in $reconciliationSnapshotPaths.Keys) {
        $commitBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-parse", "$Commit`:$relativePath"
            )).ToLowerInvariant()
        $indexBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @("hash-object", "--", $relativePath)).ToLowerInvariant()
        if ($commitBlob -cne $indexBlob) {
            throw "temporary config commit blob does not match filtered live bytes for $relativePath"
        }
    }
}

function Assert-ReconciliationMergeCommit {
    param([Parameter(Mandatory = $true)][string]$Commit)

    $row = @((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-list", "--parents", "-n", "1", $Commit
            )) -split '\s+')
    if ($row.Count -ne 3 -or $row[0].ToLowerInvariant() -cne $Commit -or
        $row[1].ToLowerInvariant() -cne $reconciliationActualPreMerge -or
        $row[2].ToLowerInvariant() -cne $ExpectedSourceTip) {
        throw "synthetic reconciliation merge does not have exact ordered parents [config-child,safety-tip]"
    }
    Assert-ReconciliationConfigCommit -Commit $reconciliationActualPreMerge
    $changes = @(& git -C $repo diff --name-only $ExpectedSourceTip $Commit)
    if ($LASTEXITCODE -ne 0 -or $changes.Count -ne $reconciliationExpectedConfigBlobs.Count -or
        @($changes | Where-Object { $reconciliationExpectedConfigBlobs.Keys -cnotcontains $_ }).Count -ne 0) {
        throw "synthetic merge tree differs from the safety tip outside the two exact configs"
    }
    foreach ($relativePath in $reconciliationSnapshotPaths.Keys) {
        $mergeBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "$Commit`:$relativePath")).ToLowerInvariant()
        $configBlob = (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                "rev-parse", "$reconciliationActualPreMerge`:$relativePath"
            )).ToLowerInvariant()
        if ($mergeBlob -cne $configBlob) {
            throw "synthetic merge did not preserve the exact config commit blob for $relativePath"
        }
    }
    if (@(Get-ReconciliationStatusRows -Root $repo).Count -ne 0) {
        throw "synthetic merge worktree is not clean"
    }
    & git -C $repo merge-base --is-ancestor $reconciliationPublishedTarget $Commit 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "synthetic merge is not a non-force descendant of the frozen published target"
    }
    Assert-ReconciliationSnapshot
}

function Invoke-ReconciliationDryRun {
    $tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $dryRoot = Join-Path $tempBase ("weather-reconciliation-dryrun-{0}" -f [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Path $dryRoot -ErrorAction Stop | Out-Null
        $dryRepo = Join-Path $dryRoot "repo"
        & git clone --quiet --no-checkout --shared $repo $dryRepo
        if ($LASTEXITCODE -ne 0) { throw "temporary shared clone failed" }
        & git -C $dryRepo fetch --quiet $repo "+refs/remotes/origin/master:refs/remotes/reconciliation/published"
        if ($LASTEXITCODE -ne 0) { throw "temporary clone could not import the published target ref" }
        if ((Get-ReconciliationGitValue -Root $dryRepo -GitArgs @(
                    "rev-parse", "$ExpectedSourceTip^{commit}"
                )).ToLowerInvariant() -cne $ExpectedSourceTip) {
            throw "temporary clone could not resolve the frozen safety tip"
        }
        & git -C $dryRepo checkout --quiet --detach $reconciliationLocalBaseline
        if ($LASTEXITCODE -ne 0) { throw "temporary clone could not check out the local baseline" }
        & git -C $dryRepo config user.name "Weather Reconciliation Dry Run"
        & git -C $dryRepo config user.email "weather-reconciliation-dry-run@invalid.local"
        foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
            $sourcePath = Join-Path $repo ($relativePath -replace '/', '\')
            $destinationPath = Join-Path $dryRepo ($relativePath -replace '/', '\')
            [IO.File]::WriteAllBytes($destinationPath, [IO.File]::ReadAllBytes($sourcePath))
        }
        $dryConfigPaths = @($reconciliationExpectedConfigBlobs.Keys)
        & git -C $dryRepo add -- $dryConfigPaths
        if ($LASTEXITCODE -ne 0) { throw "temporary config staging failed" }
        & git -C $dryRepo commit --quiet -m "dry-run: preserve exact production config bytes"
        if ($LASTEXITCODE -ne 0) { throw "temporary config commit failed" }
        $dryConfigCommit = (Get-ReconciliationGitValue -Root $dryRepo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant()
        & git -C $dryRepo merge --quiet --no-ff --no-edit $ExpectedSourceTip
        if ($LASTEXITCODE -ne 0) { throw "temporary synthetic merge failed or conflicted" }
        $dryMerge = (Get-ReconciliationGitValue -Root $dryRepo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant()
        $parents = @((Get-ReconciliationGitValue -Root $dryRepo -GitArgs @(
                    "rev-list", "--parents", "-n", "1", $dryMerge
                )) -split '\s+')
        if ($parents.Count -ne 3 -or $parents[1].ToLowerInvariant() -cne $dryConfigCommit -or
            $parents[2].ToLowerInvariant() -cne $ExpectedSourceTip) {
            throw "temporary synthetic merge parents are not [config-child,safety-tip]"
        }
        $dryConfigChanges = @(& git -C $dryRepo diff --name-only $reconciliationLocalBaseline $dryConfigCommit)
        $dryTargetChanges = @(& git -C $dryRepo diff --name-only $ExpectedSourceTip $dryMerge)
        if ($dryConfigChanges.Count -ne 2 -or $dryTargetChanges.Count -ne 2 -or
            @($dryConfigChanges | Where-Object { $reconciliationExpectedConfigBlobs.Keys -cnotcontains $_ }).Count -ne 0 -or
            @($dryTargetChanges | Where-Object { $reconciliationExpectedConfigBlobs.Keys -cnotcontains $_ }).Count -ne 0) {
            throw "temporary synthetic tree changed paths outside the exact generated-config set"
        }
        foreach ($relativePath in $reconciliationExpectedConfigBlobs.Keys) {
            $sourceHash = (Get-FileHash -LiteralPath (Join-Path $repo ($relativePath -replace '/', '\')) -Algorithm SHA256).Hash
            $dryHash = (Get-FileHash -LiteralPath (Join-Path $dryRepo ($relativePath -replace '/', '\')) -Algorithm SHA256).Hash
            $dryMergeBlob = Get-ReconciliationGitValue -Root $dryRepo -GitArgs @("rev-parse", "$dryMerge`:$relativePath")
            $dryConfigBlob = Get-ReconciliationGitValue -Root $dryRepo -GitArgs @("rev-parse", "$dryConfigCommit`:$relativePath")
            if ($sourceHash -cne $dryHash -or $dryMergeBlob -cne $dryConfigBlob) {
                throw "temporary synthetic merge changed raw or committed config bytes for $relativePath"
            }
        }
        Note "DRY RUN PASS: isolated temporary merge proved exact [config-child,safety-tip] topology and bytes; production Git, configs, evidence, capture, documentation, and Scheduler were not mutated"
    }
    finally {
        if (Test-Path -LiteralPath $dryRoot) {
            $resolvedDryRoot = [IO.Path]::GetFullPath($dryRoot)
            if (-not $resolvedDryRoot.StartsWith($tempBase + '\', [StringComparison]::OrdinalIgnoreCase) -or
                [IO.Path]::GetFileName($resolvedDryRoot) -notlike 'weather-reconciliation-dryrun-*') {
                throw "refusing unsafe dry-run cleanup target"
            }
            Remove-Item -LiteralPath $resolvedDryRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-ReconciliationRollbackAndProve {
    param([Parameter(Mandatory = $true)][string]$Reason)

    Note "special reconciliation rollback requested before commit invocation: $Reason"
    $mergeHeadPath = Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "--git-path", "MERGE_HEAD")
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) { $mergeHeadPath = Join-Path $repo $mergeHeadPath }
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        $abortExit = Invoke-GitAllowingNativeStderr { & git -C $repo merge --abort | Out-Null }
        if ($abortExit -ne 0 -or (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf)) {
            Stop-Reconciliation `
                -Detail "merge --abort failed; sentinel marker and recoverable Git state preserved; original=$Reason" `
                -Stage "rollback_recovery_failed" -ExitCode 4
        }
    }
    $head = (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant()
    if ($head -ne $reconciliationLocalBaseline) {
        try { Assert-ReconciliationConfigCommit -Commit $head }
        catch {
            Stop-Reconciliation `
                -Detail "rollback HEAD is neither L nor the exact config-only child; preserving state; original=$Reason" `
                -Stage "rollback_recovery_failed" -ExitCode 4
        }
    }
    # Run this even when HEAD is already L: a failed git add can leave only a
    # partial index mutation. The mixed reset clears that index state while
    # preserving the two snapshotted generated files byte-for-byte.
    $mixedExit = Invoke-GitAllowingNativeStderr {
        & git -C $repo reset --mixed $reconciliationLocalBaseline | Out-Null
    }
    if ($mixedExit -ne 0) {
        Stop-Reconciliation `
            -Detail "mixed reset to the exact local baseline failed; preserving marker; original=$Reason" `
            -Stage "rollback_recovery_failed" -ExitCode 4
    }
    try {
        if ((Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant() -cne
            $reconciliationLocalBaseline) { throw "HEAD is not the local baseline" }
        Assert-ReconciliationExactDirtyConfig -Root $repo
        Assert-ReconciliationSnapshot
    }
    catch {
        Stop-Reconciliation `
            -Detail "special rollback could not prove exact baseline/raw-byte state: $($_.Exception.Message); original=$Reason" `
            -Stage "rollback_recovery_failed" -ExitCode 4
    }
    $rollbackNow = Get-Date
    $deadline = $rollbackNow.AddSeconds($RollbackRecoverySeconds)
    $quietWindowEnd = $rollbackNow.Date.AddHours(4)
    if ($quietWindowEnd -lt $deadline) { $deadline = $quietWindowEnd }
    do {
        $proof = Test-ReconciliationCaptureProof
        if ($proof.ok) { break }
        $sleepNow = Get-Date
        if ($sleepNow -lt $deadline) {
            $sleepMilliseconds = [int][Math]::Floor(
                ([Math]::Min(15, ($deadline - $sleepNow).TotalSeconds)) * 1000
            )
            if ($sleepMilliseconds -gt 0) {
                Start-Sleep -Milliseconds $sleepMilliseconds
            }
        }
    } while ((Get-Date) -lt $deadline)
    if (-not $proof.ok) {
        Stop-Reconciliation `
            -Detail "special rollback restored Git/bytes but affected-producer recovery is unproved; marker preserved; original=$Reason" `
            -Stage "rollback_recovery_failed" -ExitCode 4
    }
    $script:captureRecoveryProved = $true
    if ($executionTapeRecoveryRequired) { $script:executionTapeRecoveryProved = $true }
    Save-Report -ok $false -stage "rolled_back" -detail "$Reason; exact L/raw bytes and producer recovery proved; no publication"
    exit 2
}

$specialInputsProvided = @(
    $ExpectedLocalBaseline,
    $ExpectedPublishedTarget,
    $ExpectedSourceTip,
    $ExpectedSourceTree
) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
if (-not $productionBaselineReconciliationMode -and $specialInputsProvided.Count -gt 0) {
    Fail "production-baseline reconciliation inputs require -ProductionBaselineReconciliation"
}

if ($productionBaselineReconciliationMode) {
    if ($ExpectedLocalBaseline -notmatch '^[0-9a-f]{40}$' -or
        $ExpectedPublishedTarget -notmatch '^[0-9a-f]{40}$' -or
        $ExpectedSourceTip -notmatch '^[0-9a-f]{40}$' -or
        $ExpectedSourceTree -notmatch '^[0-9a-f]{40}$' -or
        $ExpectedSelfSha256 -notmatch '^[0-9a-f]{64}$') {
        Stop-Reconciliation -Detail "special mode requires full hexadecimal L/T/source/self identities"
    }
    if ($Branch -cne $ExpectedSourceTip -or
        $ExpectedTip -cne $ExpectedSourceTip -or
        $ExpectedBaseline -cne $reconciliationLocalBaseline -or
        $ExpectedLocalBaseline -cne $reconciliationLocalBaseline -or
        $ExpectedPublishedTarget -cne $reconciliationPublishedTarget) {
        Stop-Reconciliation -Detail "special mode requires exact Branch/Tip/L/T plus full frozen source tip/tree/self SHA identities"
    }
    if ($Force -or $OwnerApprovedException -or $AttemptReportPath) {
        Stop-Reconciliation -Detail "production-baseline reconciliation forbids Force, owner exceptions, and generic integration-attempt report routing"
    }
    $reconciliationSafetyTip = $ExpectedSourceTip
    $reconciliationSafetyTree = $ExpectedSourceTree
    $ExpectedBaseline = $ExpectedLocalBaseline
    $ExpectedTip = $ExpectedSourceTip
    try { $null = Assert-ReconciliationQuietWindowOpen -Stage "entry" }
    catch { Stop-Reconciliation -Detail $_.Exception.Message }
    if (-not $DryRun) {
        try { $null = Assert-ReconciliationPublicationTimeBudget -Now (Get-Date) }
        catch {
            Stop-Reconciliation -Detail "publication time budget is already impossible before mutation: $($_.Exception.Message)"
        }
    }

    try {
        $sourceIdentity = Assert-ReconciliationSourceWorktree
        $reconciliationSourceRoot = [string]$sourceIdentity.root
        $reconciliationSourceTree = [string]$sourceIdentity.tree
        $reconciliationOwnedChildJobScript = Join-Path `
            $reconciliationSourceRoot "scripts\ops\windows_kill_on_close_job.ps1"
        $reconciliationSchedulerRpcScript = Join-Path `
            $reconciliationSourceRoot "scripts\ops\production_baseline_scheduler_rpc.ps1"
        foreach ($binding in @(
                [PSCustomObject]@{
                    path = $reconciliationOwnedChildJobScript
                    key = "scripts/ops/windows_kill_on_close_job.ps1@safety_tip"
                },
                [PSCustomObject]@{
                    path = $reconciliationSchedulerRpcScript
                    key = "scripts/ops/production_baseline_scheduler_rpc.ps1@safety_tip"
                }
            )) {
            if (-not (Test-Path -LiteralPath $binding.path -PathType Leaf) -or
                (Get-FileHash -LiteralPath $binding.path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    [string]$reconciliationDependencySha256[[string]$binding.key]) {
                throw "owned-child dependency changed before binding: $($binding.key)"
            }
        }
        $reconciliationSchedulerRpcSha256 = [string]$reconciliationDependencySha256[
            "scripts/ops/production_baseline_scheduler_rpc.ps1@safety_tip"
        ]
        . $reconciliationOwnedChildJobScript
        foreach ($commandName in @(
                "New-WeatherKillOnCloseJob",
                "Start-WeatherProcessInJob",
                "ConvertTo-WeatherWindowsArgumentString"
            )) {
            if (-not (Get-Command -Name $commandName -CommandType Function -ErrorAction SilentlyContinue)) {
                throw "owned-child runtime did not define $commandName"
            }
        }
        $reconciliationPowerShellExecutable = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        if (-not (Test-Path -LiteralPath $reconciliationPowerShellExecutable -PathType Leaf)) {
            throw "current PowerShell executable could not be bound"
        }
        $reconciliationOwnedChildInitialized = $true
        Assert-ReconciliationProductionIdentity
        Assert-ReconciliationRemotePublishedTarget
        Assert-ReconciliationDependencyBytes -Stage "local_baseline"
        Assert-OneShotPushTask
    }
    catch {
        Stop-Reconciliation -Detail "pre-lease immutable-input/preflight proof failed: $($_.Exception.Message)"
    }

    if ($DryRun) {
        try {
            # A lease writes a durable diagnostic record even after releasing
            # its OS handle. Dry-run has no production mutation to serialize,
            # so perform two complete read-only identity passes instead and
            # leave even data/logs/heavy_workload.lock byte-for-byte untouched.
            $sourceIdentity = Assert-ReconciliationSourceWorktree
            $reconciliationSourceRoot = [string]$sourceIdentity.root
            $reconciliationSourceTree = [string]$sourceIdentity.tree
            Assert-ReconciliationProductionIdentity
            Assert-ReconciliationRemotePublishedTarget
            Assert-ReconciliationDependencyBytes -Stage "local_baseline"
            Assert-OneShotPushTask

            $rollEvidence = Invoke-ReconciliationRollVerdict
            $rollVerdictExitCode = [int]$rollEvidence.exit_code
            $rollVerdictExplicitBase = $reconciliationLocalBaseline
            $rollVerdictExplicitBranch = $ExpectedSourceTip
            $rollVerdictJsonSha256 = [string]$rollEvidence.json_sha256
            $reconciliationRollVerdictReadable = [bool]$rollEvidence.readable
            $executionTapeActive = Test-ExecutionTapeActive
            $executionTapeReadoptionExpected = $false
            if ($reconciliationRollVerdictReadable) {
                $executionTapeReadoptionExpected = @(
                    $rollEvidence.payload.files | Where-Object {
                        $_.rolls -eq $true -and @($_.closures) -contains "execution_tape"
                    }
                ).Count -gt 0
            }
            $executionTapeRecoveryRequired = (
                $executionTapeReadoptionExpected -and $executionTapeActive
            ) -or ($executionTapeActive -and -not $reconciliationRollVerdictReadable)
            $executionTapeRolledButInactiveSkipped =
                $executionTapeReadoptionExpected -and -not $executionTapeActive
            $beforeProof = Test-ReconciliationCaptureProof
            if (-not $beforeProof.ok) {
                throw "exact three-worker/required-execution recovery proof is unhealthy before dry run"
            }
            Invoke-ReconciliationDryRun
            exit 0
        }
        catch {
            Stop-Reconciliation -Detail "no-mutation dry-run proof failed: $($_.Exception.Message)"
        }
    }

    $workloadLease = Enter-WeatherHeavyWorkloadLease `
        -RepoRoot $repo `
        -Workload "production_baseline_reconciliation" `
        -OwnerApprovedException ""
    if ($null -eq $workloadLease) {
        Stop-Reconciliation -Detail "another heavyweight host workload owns data/logs/heavy_workload.lock"
    }
    try {
        try {
            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "post-lease preflight" -RequirePublicationBudget
            # Recheck every mutable input after acquiring the host-global lease.
            $sourceIdentity = Assert-ReconciliationSourceWorktree
            $reconciliationSourceRoot = [string]$sourceIdentity.root
            $reconciliationSourceTree = [string]$sourceIdentity.tree
            Assert-ReconciliationProductionIdentity
            Assert-ReconciliationRemotePublishedTarget
            Assert-ReconciliationDependencyBytes -Stage "local_baseline"
            Assert-OneShotPushTask

            $rollEvidence = Invoke-ReconciliationRollVerdict
            $rollVerdictExitCode = [int]$rollEvidence.exit_code
            $rollVerdictExplicitBase = $reconciliationLocalBaseline
            $rollVerdictExplicitBranch = $ExpectedSourceTip
            $rollVerdictJsonSha256 = [string]$rollEvidence.json_sha256
            $reconciliationRollVerdictReadable = [bool]$rollEvidence.readable
            Note "explicit roll verdict L->S exit=$rollVerdictExitCode readable=$reconciliationRollVerdictReadable; special mode remains quiet-window-only"

            $executionTapeActive = Test-ExecutionTapeActive
            $executionTapeReadoptionExpected = $false
            if ($reconciliationRollVerdictReadable) {
                $executionTapeReadoptionExpected = @(
                    $rollEvidence.payload.files | Where-Object {
                        $_.rolls -eq $true -and @($_.closures) -contains "execution_tape"
                    }
                ).Count -gt 0
            }
            $executionTapeRecoveryRequired = (
                $executionTapeReadoptionExpected -and $executionTapeActive
            ) -or ($executionTapeActive -and -not $reconciliationRollVerdictReadable)
            $executionTapeRolledButInactiveSkipped = $executionTapeReadoptionExpected -and -not $executionTapeActive

            $beforeProof = Test-ReconciliationCaptureProof
            if (-not $beforeProof.ok) {
                throw "exact three-worker/required-execution recovery proof is unhealthy before mutation"
            }
            if ($executionTapeRecoveryRequired) {
                $executionTapeSourceBefore = [string]$beforeProof.execution.source
            }

            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "raw snapshot" -RequirePublicationBudget
            $rawEvidence = Get-ReconciliationRawConfigEvidence -Root $repo
            $snapshot = New-ReconciliationRawSnapshot -RollEvidence $rollEvidence -RawEvidence $rawEvidence
            $reconciliationSnapshotRoot = [string]$snapshot.root
            $reconciliationSnapshotManifestPath = [string]$snapshot.manifest_path
            $reconciliationSnapshotManifestSha256 = [string]$snapshot.manifest_sha256
            $reconciliationSnapshotPaths = $snapshot.paths
            $reconciliationRollVerdictPath = [string]$snapshot.roll_json_path
            $reconciliationRollVerdictTranscriptPath = [string]$snapshot.roll_transcript_path
            $reconciliationRollVerdictTranscriptSha256 = [string]$snapshot.roll_transcript_sha256
            foreach ($relativePath in $rawEvidence.Keys) {
                $rollbackContentSha256[$relativePath] = [string]$rawEvidence[$relativePath].sha256
            }
            Assert-ReconciliationSnapshot

            $baselineCommit = $ExpectedLocalBaseline
            $resolvedBranchTip = $ExpectedSourceTip
            $mergeTarget = $ExpectedSourceTip
            $preMerge = $reconciliationLocalBaseline
            $reconciliationActualPreMerge = $reconciliationLocalBaseline
            $reconciliationBootGuardCommit = $reconciliationPublishedTarget
            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "preparing marker" -RequirePublicationBudget
            Write-ReconciliationMarker -Phase "reconciliation_preparing"
            $activeMarkerOwned = $true

            $configPaths = @($reconciliationExpectedConfigBlobs.Keys)
            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "config staging" -RequirePublicationBudget
            $configAddExit = Invoke-GitAllowingNativeStderr { & git -C $repo add -- $configPaths }
            if ($configAddExit -ne 0) {
                Invoke-ReconciliationRollbackAndProve -Reason "staging the exact raw configs failed"
            }
            $stagedPaths = @(& git -C $repo diff --cached --name-only)
            if ($LASTEXITCODE -ne 0 -or $stagedPaths.Count -ne 2 -or
                @($stagedPaths | Where-Object { $configPaths -cnotcontains $_ }).Count -ne 0) {
                Invoke-ReconciliationRollbackAndProve -Reason "the config index contains anything other than the exact two paths"
            }
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "config commit" -RequirePublicationBudget
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason $_.Exception.Message
            }
            $configCommitExit = Invoke-GitAllowingNativeStderr {
                & git -C $repo commit -m "ops: preserve exact production-generated config baseline" | Out-Null
            }
            if ($configCommitExit -ne 0) {
                Invoke-ReconciliationRollbackAndProve -Reason "the temporary config commit failed or was ambiguous"
            }
            $reconciliationActualPreMerge = (
                Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")
            ).ToLowerInvariant()
            $preMerge = $reconciliationActualPreMerge
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "prepared marker" -RequirePublicationBudget
                Assert-ReconciliationConfigCommit -Commit $reconciliationActualPreMerge
                Write-ReconciliationMarker -Phase "reconciliation_prepared"
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason "config-child or prepared-marker proof failed: $($_.Exception.Message)"
            }

            # The marker is already durable/read back with the T sentinel before
            # MERGE_HEAD can exist. Every failure before commit uses the special
            # abort+mixed-reset path; no hard-reset fallback is present here.
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "synthetic merge staging" -RequirePublicationBudget
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason $_.Exception.Message
            }
            $mergeExit = Invoke-GitAllowingNativeStderr {
                & git -C $repo merge --no-commit --no-ff $ExpectedSourceTip | Out-Null
            }
            if ($mergeExit -ne 0) {
                Invoke-ReconciliationRollbackAndProve -Reason "synthetic no-commit merge failed or conflicted (git exit $mergeExit)"
            }
            $mergeHeadPath = Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "--git-path", "MERGE_HEAD")
            if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) { $mergeHeadPath = Join-Path $repo $mergeHeadPath }
            if (-not (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant() -cne
                    $reconciliationActualPreMerge -or
                @(& git -C $repo diff --name-only --diff-filter=U).Count -ne 0) {
                Invoke-ReconciliationRollbackAndProve -Reason "staged synthetic merge identity/conflict proof failed"
            }
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "staged synthetic merge marker" -RequirePublicationBudget
                Assert-ReconciliationDependencyBytes -Stage "published_target"
                Assert-ReconciliationSnapshot
                Write-ReconciliationMarker -Phase "reconciliation_merge_uncommitted"
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason "staged target/dependency/marker proof failed: $($_.Exception.Message)"
            }

            Note "synthetic target staged but uncommitted; waiting ${SettleSeconds}s for exact affected-producer readoption"
            $settleStartedAt = Get-Date
            $settleBoundary = $settleStartedAt.Date.AddHours(4)
            if ($SettleSeconds -lt 0 -or
                $settleStartedAt.AddSeconds($SettleSeconds) -ge $settleBoundary) {
                Invoke-ReconciliationRollbackAndProve `
                    -Reason "the staged-safety settle interval cannot complete inside 01:00-04:00"
            }
            Start-Sleep -Seconds $SettleSeconds
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "post-settle staged-safety proof" -RequirePublicationBudget
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason $_.Exception.Message
            }
            $afterProof = Test-ReconciliationCaptureProof
            if (-not $afterProof.ok) {
                Invoke-ReconciliationRollbackAndProve -Reason "capture or required execution-tape recovery failed on staged target"
            }
            if ($executionTapeRecoveryRequired -and $executionTapeReadoptionExpected -and
                [string]$afterProof.execution.source -ceq [string]$executionTapeSourceBefore) {
                Invoke-ReconciliationRollbackAndProve -Reason "execution-tape closure rolled but source fingerprint did not change"
            }
            $captureRecoveryProved = $true
            $reconciliationStagedSafetyCaptureRecoveryProved = $true
            $reconciliationStagedSafetyCaptureRecoveryAt = (Get-Date).ToString("o")
            if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "staged-safety recovered marker" -RequirePublicationBudget
                Write-ReconciliationMarker -Phase "reconciliation_capture_recovered_uncommitted"
                Assert-ReconciliationSnapshot
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason "recovered-uncommitted marker/snapshot proof failed: $($_.Exception.Message)"
            }

            # This monotonic boundary is deliberately set before invoking Git.
            # From here on, no automated rollback is allowed: a nonzero commit
            # result can be an already-created M with MERGE_HEAD removed.
            try {
                $null = Assert-ReconciliationQuietWindowOpen `
                    -Stage "synthetic merge commit" -RequirePublicationBudget
            }
            catch {
                Invoke-ReconciliationRollbackAndProve -Reason $_.Exception.Message
            }
            $reconciliationCommitInvocationStarted = $true
            $mergeCommitExit = Invoke-GitAllowingNativeStderr {
                & git -C $repo commit -m "Merge published production baseline with preserved generated config" | Out-Null
            }
            if ($mergeCommitExit -ne 0) {
                Stop-Reconciliation `
                    -Detail "merge commit invocation returned $mergeCommitExit; sentinel marker and exact Git state preserved for review" `
                    -Stage "commit_ambiguous" -ExitCode 4
            }
            try { $null = Assert-ReconciliationQuietWindowOpen -Stage "post-merge commit" }
            catch {
                Stop-Reconciliation `
                    -Detail "synthetic merge commit crossed the 04:00 boundary; sentinel marker and exact Git state preserved" `
                    -Stage "commit_ambiguous" -ExitCode 4
            }
            $candidateMergeCommit = (
                Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")
            ).ToLowerInvariant()
            try {
                Assert-ReconciliationMergeCommit -Commit $candidateMergeCommit
            }
            catch {
                Stop-Reconciliation `
                    -Detail "post-commit topology/tree/raw-byte proof failed; sentinel marker and commit preserved: $($_.Exception.Message)" `
                    -Stage "commit_ambiguous" -ExitCode 4
            }
            $mergeCommit = $candidateMergeCommit
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            $reconciliationPostCommitMarkerArmed = $true
            try { Write-ReconciliationMarker -Phase "merge_committed_unpublished" }
            catch {
                Stop-Reconciliation `
                    -Detail "atomic postcommit marker cutover failed; an old-or-new boot-safe marker, any replacement backup, and M are preserved for hash review" `
                    -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
            }
            Note "exact synthetic merge $mergeCommit committed and atomically bound to adopted boot recovery; not published"
        }
        catch {
            $unexpectedFailure = $_.Exception.Message
            if ($activeMarkerOwned -and -not $reconciliationCommitInvocationStarted -and
                -not $reconciliationRollbackStarted) {
                $reconciliationRollbackStarted = $true
                try {
                    Invoke-ReconciliationRollbackAndProve `
                        -Reason "unexpected pre-commit reconciliation failure: $unexpectedFailure"
                }
                catch {
                    Stop-Reconciliation `
                        -Detail "unexpected pre-commit rollback failure; marker/Git state preserved: $($_.Exception.Message); original=$unexpectedFailure" `
                        -Stage "rollback_recovery_failed" -ExitCode 4
                }
            }
            if ($activeMarkerOwned) {
                Stop-Reconciliation `
                    -Detail "unexpected post-commit-or-rollback reconciliation failure; state preserved: $unexpectedFailure" `
                    -Stage "reconciliation_state_preserved" -ExitCode 4
            }
            Stop-Reconciliation -Detail "special pre-mutation proof failed: $unexpectedFailure"
        }

        # Documentation begins only after M and the boot-valid postcommit marker
        # exist. Any ambiguity below preserves both for reviewed reconciliation.
        try {
            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "documentation transaction" -RequirePublicationBudget
        }
        catch {
            Stop-Reconciliation `
                -Detail "quiet-window boundary closed before documentation; M and boot-valid marker preserved" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }
        $documentationArgs = @(
            "-m", "weather.operations.documentation_transaction",
            "--repo-root", $repo,
            "begin",
            "--integration-tip", $mergeCommit,
            "--branch", $Branch,
            "--expected-tip", $ExpectedTip
        )
        $previousDocumentationPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $documentationOutput = @(
                Invoke-ReconciliationPython -Arguments $documentationArgs
            )
            $documentationExit = $reconciliationPythonExitCode
        }
        finally { $ErrorActionPreference = $previousDocumentationPreference }
        if ($documentationExit -ne 0) {
            Stop-Reconciliation `
                -Detail "documentation transaction failed or was ambiguous for $mergeCommit; M preserved" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }
        try {
            $null = Assert-ReconciliationQuietWindowOpen `
                -Stage "documentation marker" -RequirePublicationBudget
            $documentationPayload = (($documentationOutput -join "`n") | ConvertFrom-Json)
            $pendingSha256 = ([string]$documentationPayload.pending_sha256).ToLowerInvariant()
            $matchingEntry = @($documentationPayload.integrations | Where-Object {
                    ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
                    [string]$_.branch -ceq $Branch -and
                    ([string]$_.expected_tip).ToLowerInvariant() -eq $ExpectedTip
                })
            $pendingPath = Join-Path $repo "data\alerts\documentation_transaction_pending.json"
            $snapshotRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
            $documentationPath = Join-Path $repo ($snapshotRelative -replace '/', '\')
            $documentationSnapshot = Get-Content -LiteralPath $documentationPath -Raw -ErrorAction Stop | ConvertFrom-Json
            $snapshotEntries = @($documentationSnapshot.integrations | Where-Object {
                    ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
                    [string]$_.branch -ceq $Branch -and
                    ([string]$_.expected_tip).ToLowerInvariant() -eq $ExpectedTip
                })
            if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or $matchingEntry.Count -ne 1 -or
                [string]$documentationSnapshot.schema_version -cne "documentation_transaction_pending_v0.1" -or
                [string]$documentationSnapshot.status -cne "PENDING" -or
                ([string]$documentationSnapshot.latest_integration_tip).ToLowerInvariant() -ne $mergeCommit -or
                $snapshotEntries.Count -ne 1 -or
                (Get-FileHash -LiteralPath $pendingPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pendingSha256 -or
                (Get-FileHash -LiteralPath $documentationPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pendingSha256) {
                throw "documentation pending state/snapshot does not exactly bind M/S"
            }
            $documentationTransactionPendingSha256 = $pendingSha256
            $documentationTransactionSnapshotPath = $snapshotRelative
            $documentationTransactionRecorded = $true
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            Write-ReconciliationMarker -Phase "documented_unpublished"
            $documentedMarkerSha256 = $reconciliationMarkerSha256
        }
        catch {
            Stop-Reconciliation `
                -Detail "documentation succeeded without exact boot-valid marker identity; M preserved: $($_.Exception.Message)" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }

        # Final immutable-boundary revalidation. origin/master must still be T;
        # no generic {L,M} allowance applies to this intentionally divergent run.
        try {
            $reconciliationHour = (Get-Date).Hour + ((Get-Date).Minute / 60.0)
            if (-not ($reconciliationHour -ge 1 -and $reconciliationHour -lt 4)) {
                throw "quiet window ended before publication"
            }
            $sourceIdentity = Assert-ReconciliationSourceWorktree
            Assert-ReconciliationCanonicalOrigin -Root $repo
            Assert-ReconciliationRemotePublishedTarget
            if ((Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "HEAD^{commit}")).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "master^{commit}")).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @("rev-parse", "origin/master^{commit}")).ToLowerInvariant() -cne
                    $reconciliationPublishedTarget) {
                throw "HEAD/master/origin moved before publication"
            }
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            Assert-ReconciliationDependencyBytes -Stage "published_target"
            Assert-ReconciliationSnapshot
            $documentationPath = Join-Path $repo ($documentationTransactionSnapshotPath -replace '/', '\')
            if ((Get-FileHash -LiteralPath $documentationPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
                $documentationTransactionPendingSha256) {
                throw "immutable documentation snapshot changed before publication"
            }
            if ((Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
                $documentedMarkerSha256) {
                throw "documented marker changed before publication"
            }
            $finalProof = Test-ReconciliationCaptureProof
            if (-not $finalProof.ok) { throw "affected-producer recovery no longer passes" }
            Assert-OneShotPushTask
        }
        catch {
            Stop-Reconciliation `
                -Detail "final publication-boundary proof failed; M preserved: $($_.Exception.Message)" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }

        if ($publicationInvoked) {
            Stop-Reconciliation `
                -Detail "the one authorized WeatherOneShotPush invocation is already spent" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }
        $pushPreStartAt = Get-Date
        try {
            $quietWindowEnd = Assert-ReconciliationPublicationTimeBudget -Now $pushPreStartAt
            $null = Assert-OneShotPushTask -PassThru
            $pushPreInfo = Get-ReconciliationOneShotPushTaskInfo
            $oneShotPushPreLastRunTime = $pushPreInfo.last_run_time.ToString("o")
            # Task readback is an external boundary. Reprove the captured
            # production bytes after it and before spending the sole
            # authorization in the attempted marker.
            Assert-ReconciliationSnapshot
        }
        catch {
            Stop-Reconciliation `
                -Detail "WeatherOneShotPush runtime baseline could not be frozen; task not started: $($_.Exception.Message)" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }
        $publicationInvoked = $true
        try {
            # This atomic marker replacement spends the one-shot authorization
            # before task start. Failure invokes no Scheduler operation; an
            # old or conservatively attempted boot-safe marker remains and any
            # retry requires review rather than assuming the invocation is free.
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            Write-ReconciliationMarker -Phase "documented_unpublished"
            $documentedMarkerSha256 = $reconciliationMarkerSha256
            $sourceIdentity = Assert-ReconciliationSourceWorktree
            Assert-ReconciliationCanonicalOrigin -Root $repo
            Assert-ReconciliationRemotePublishedTarget
            if ((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "origin/master^{commit}"
                    )).ToLowerInvariant() -cne $reconciliationPublishedTarget) {
                throw "origin/master moved after the push-attempt marker was armed"
            }
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            Assert-ReconciliationDependencyBytes -Stage "published_target"
            Assert-ReconciliationSnapshot
            if ((Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
                $documentedMarkerSha256) {
                throw "push-attempt marker changed during final revalidation"
            }
            $null = Assert-OneShotPushTask -PassThru
            $pushPreStartRecheck = Get-ReconciliationOneShotPushTaskInfo
            if ($pushPreStartRecheck.last_run_time -ne $pushPreInfo.last_run_time -or
                $pushPreStartRecheck.last_task_result -ne $pushPreInfo.last_task_result) {
                throw "WeatherOneShotPush runtime changed after its prestart snapshot"
            }
            $lastProof = Test-ReconciliationCaptureProof
            if (-not $lastProof.ok) { throw "recovery failed after push-attempt marker was armed" }
            $reconciliationPrePushCaptureRecoveryProved = $true
            $reconciliationPrePushCaptureRecoveryAt = (Get-Date).ToString("o")
            $pushStartIssuedAt = Get-Date
            $quietWindowEnd = Assert-ReconciliationPublicationTimeBudget -Now $pushStartIssuedAt
            $pushContainmentDeadline = $pushStartIssuedAt.Add($reconciliationPushRuntimeLimit)
            if ($quietWindowEnd -lt $pushContainmentDeadline) {
                $pushContainmentDeadline = $quietWindowEnd
            }
            $pushContainmentStopAt = $pushContainmentDeadline.AddSeconds(-30)
            $oneShotPushStartIssuedAt = $pushStartIssuedAt.ToString("o")
            $oneShotPushContainmentDeadline = $pushContainmentDeadline.ToString("o")
            # Persist the exact on-demand containment clock before Start. The
            # task's XML PT15M limit does not constrain an on-demand invocation.
            Write-ReconciliationMarker -Phase "documented_unpublished"
            $documentedMarkerSha256 = $reconciliationMarkerSha256
            $null = Assert-OneShotPushTask -PassThru
            $pushImmediateInfo = Get-ReconciliationOneShotPushTaskInfo
            if ($pushImmediateInfo.last_run_time -ne $pushPreInfo.last_run_time -or
                $pushImmediateInfo.last_task_result -ne $pushPreInfo.last_task_result) {
                throw "WeatherOneShotPush runtime changed at the immediate start boundary"
            }
            # Reprove the exact non-force publication endpoints after capture
            # and Scheduler reads, immediately before creating the journaled
            # Start identity. The helper independently re-attests the task once
            # more at its own mutation boundary.
            Assert-ReconciliationCanonicalOrigin -Root $repo
            Assert-ReconciliationRemotePublishedTarget
            if ((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "HEAD^{commit}"
                    )).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "master^{commit}"
                    )).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "origin/master^{commit}"
                    )).ToLowerInvariant() -cne $reconciliationPublishedTarget) {
                throw "HEAD/master/origin moved at the final Start boundary"
            }
            Assert-ReconciliationSnapshot
            $pushImmediateAt = Get-Date
            if ($pushImmediateAt -ge $pushContainmentDeadline -or
                $pushImmediateAt -ge $quietWindowEnd) {
                throw "quiet-window containment clock elapsed while arming the task start"
            }
            $pushStartIdentity = New-ReconciliationSchedulerRpcIdentity `
                -LogicalBoundary $pushContainmentDeadline -MaximumSeconds 20
            $pushStartRpcRequestId = [string]$pushStartIdentity.request_id
            $pushStartRpcDeadlineUtc = [string]$pushStartIdentity.deadline_utc
            # This final atomic marker replacement journals the exact helper
            # identity immediately before its sole Start invocation.
            Write-ReconciliationMarker -Phase "documented_unpublished"
            $documentedMarkerSha256 = $reconciliationMarkerSha256
            Assert-ReconciliationCanonicalOrigin -Root $repo
            Assert-ReconciliationRemotePublishedTarget
            if ((Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "HEAD^{commit}"
                    )).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "master^{commit}"
                    )).ToLowerInvariant() -cne $mergeCommit -or
                (Get-ReconciliationGitValue -Root $repo -GitArgs @(
                        "rev-parse", "origin/master^{commit}"
                    )).ToLowerInvariant() -cne $reconciliationPublishedTarget -or
                (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $documentedMarkerSha256) {
                throw "journaled Start boundary changed before helper launch"
            }
        }
        catch {
            Stop-Reconciliation `
                -Detail "push-attempt marker/prestart proof failed; the task was not started and M is preserved: $($_.Exception.Message)" `
                -Stage "reconciliation_merged_unpublished" -ExitCode 3 -Ok $true
        }

        Note "all reconciliation gates passed; invoking WeatherOneShotPush exactly once for $mergeCommit"
        $pushStartError = $null
        try {
            Invoke-ReconciliationOneShotPushTask `
                -Identity $pushStartIdentity -MarkerSha256 $documentedMarkerSha256
        }
        catch {
            # The bounded helper can lose its response after Scheduler accepts
            # Start. The attempted marker is already durable, so this authority
            # is permanently spent and can never be retried.
            if ($_.Exception -is [TimeoutException]) { $pushStartRpcTimedOut = $true }
            $pushStartError = $_.Exception.Message
            try { Write-ReconciliationMarker -Phase "documented_unpublished" }
            catch { Note "ambiguous Start marker update also failed: $($_.Exception.Message)" }
            Note "WeatherOneShotPush Start became uncertain after the journaled sole attempt; draining without retry"
        }
        $pushRunObserved = $false
        $pushTerminalProved = $false
        $pushReadySignature = $null
        $pushReadyAgreementCount = 0
        $pushDeadlineWarningWritten = $false
        $pushTerminalInfo = $null
        while (-not $pushTerminalProved) {
            $pushPollAt = Get-Date
            if ($pushPollAt -ge $pushContainmentDeadline) {
                Stop-ReconciliationAtAbsolutePublicationBoundary
            }
            $pushTask = $null
            $pushState = $null
            $pushInfo = $null
            try {
                $pushTask = Get-ReconciliationOneShotPushState
                $pushState = [string]$pushTask.State
                $pushInfo = Get-ReconciliationOneShotPushTaskInfo
                $pushPollAt = Get-Date
                if ($pushPollAt -ge $pushContainmentDeadline) {
                    Stop-ReconciliationAtAbsolutePublicationBoundary
                }
            }
            catch {
                $pushPollAt = Get-Date
                if ($pushPollAt -ge $pushContainmentDeadline) {
                    Stop-ReconciliationAtAbsolutePublicationBoundary
                }
                if ($pushPollAt -ge $pushContainmentStopAt -and
                    $pushPollAt -lt $pushContainmentDeadline) {
                    Request-ReconciliationOneShotPushContainment -LogicalBoundary $pushContainmentDeadline
                }
                if (-not $pushDeadlineWarningWritten -and
                    $pushPollAt -ge $pushContainmentStopAt) {
                    Note "publication drain reached its pre-PT15M Stop reserve without exact task readback; bounded Stop is attempted at most once"
                    $pushDeadlineWarningWritten = $true
                }
                $nextBoundary = if ($pushPollAt -lt $pushContainmentStopAt) {
                    $pushContainmentStopAt
                }
                else { $pushContainmentDeadline }
                Start-ReconciliationBoundedPollSleep -Boundary $nextBoundary -MaximumSeconds 2
                continue
            }
            $oneShotPushRuntimeState = $pushState
            $oneShotPushObservedLastRunTime = $pushInfo.last_run_time.ToString("o")
            $oneShotPushLastTaskResult = [long]$pushInfo.last_task_result
            $newLastRun = $pushInfo.last_run_time -gt $pushPreInfo.last_run_time -and
                $pushInfo.last_run_time -ge $pushStartIssuedAt.AddSeconds(-2)
            if ($pushState -in @("Running", "Queued") -or $newLastRun) {
                $pushRunObserved = $true
            }
            $containmentRequestedThisPoll = $false
            if ($pushPollAt -ge $pushContainmentStopAt -and
                $pushPollAt -lt $pushContainmentDeadline -and $oneShotPushStopCount -eq 0) {
                # An asynchronous on-demand dispatch can still look Ready with
                # unchanged LastRunTime. Stop the cached exact task once at the
                # boundary even in that state before treating no-run as final.
                Request-ReconciliationOneShotPushContainment -LogicalBoundary $pushContainmentDeadline
                $containmentRequestedThisPoll = $true
            }
            if ($pushPollAt -ge $pushContainmentStopAt -and
                $pushState -in @("Running", "Queued")) {
                # Pre-start Ready + unchanged runtime + zero triggers +
                # IgnoreNew and the exclusive operator contract bind this sole
                # active singleton to the attempted invocation.
                if (-not $containmentRequestedThisPoll) {
                    Request-ReconciliationOneShotPushContainment -LogicalBoundary $pushContainmentDeadline
                }
                $nextBoundary = $pushContainmentDeadline
                Start-ReconciliationBoundedPollSleep -Boundary $nextBoundary -MaximumSeconds 2
                continue
            }
            $readyCanTerminal = $pushState -ceq "Ready" -and (
                ($pushRunObserved -and $newLastRun) -or
                $oneShotPushStopAttempted
            )
            if ($readyCanTerminal) {
                $signature = "{0}|{1}" -f $pushInfo.last_run_time.Ticks,
                    [long]$pushInfo.last_task_result
                if ($signature -ceq $pushReadySignature) {
                    $pushReadyAgreementCount++
                }
                else {
                    $pushReadySignature = $signature
                    $pushReadyAgreementCount = 1
                }
                if ($pushReadyAgreementCount -ge 2) {
                    try {
                        $pushTerminalTask = Assert-OneShotPushTask -Quiet -PassThru
                        $pushTerminalCandidate = Get-ReconciliationOneShotPushTaskInfo
                        if ([string]$pushTerminalTask.State -cne "Ready" -or
                            $pushTerminalCandidate.last_run_time -ne $pushInfo.last_run_time -or
                            $pushTerminalCandidate.last_task_result -ne $pushInfo.last_task_result) {
                            throw "terminal task state/info changed during final confirmation"
                        }
                        $pushTerminalInfo = $pushTerminalCandidate
                        $oneShotPushRuntimeState = "Ready"
                        $oneShotPushObservedLastRunTime = $pushTerminalCandidate.last_run_time.ToString("o")
                        $oneShotPushLastTaskResult = [long]$pushTerminalCandidate.last_task_result
                        $pushTerminalProvedAt = Get-Date
                        $oneShotPushTerminalProvedAt = $pushTerminalProvedAt.ToString("o")
                        if ($pushTerminalProvedAt -ge $pushContainmentDeadline) {
                            $oneShotPushContainmentBreached = $true
                        }
                        $pushTerminalProved = $true
                        break
                    }
                    catch {
                        $pushReadySignature = $null
                        $pushReadyAgreementCount = 0
                    }
                }
            }
            else {
                $pushReadySignature = $null
                $pushReadyAgreementCount = 0
            }
            if (-not $pushDeadlineWarningWritten -and
                $pushPollAt -ge $pushContainmentStopAt) {
                Note "publication drain reached its pre-PT15M containment reserve; exact terminal proof remains bounded by PT15M"
                $pushDeadlineWarningWritten = $true
            }
            $nextBoundary = if ($pushPollAt -lt $pushContainmentStopAt) {
                $pushContainmentStopAt
            }
            else { $pushContainmentDeadline }
            Start-ReconciliationBoundedPollSleep -Boundary $nextBoundary -MaximumSeconds 10
        }
        $oneShotPushRunObserved = [bool]$pushRunObserved
        $oneShotPushTerminalProved = $true
        try {
            $publicationAck = Get-ReconciliationPublicationAck `
                -Boundary $pushContainmentDeadline
        }
        catch {
            Note "terminal publication acknowledgement did not complete inside the absolute boundary: $($_.Exception.Message)"
            Stop-ReconciliationAtAbsolutePublicationBoundary
        }
        try {
            # Add the terminal runtime evidence to the still boot-valid,
            # attempted marker before classifying remote publication.
            Write-ReconciliationMarker -Phase "documented_unpublished"
        }
        catch {
            Stop-Reconciliation `
                -Detail "WeatherOneShotPush reached terminal Ready but runtime evidence could not be atomically journaled; publication state preserved for review" `
                -Stage "publication_state_uncertain" -ExitCode 3 -Ok $true
        }
        if (-not ($pushRunObserved -and
            [long]$oneShotPushLastTaskResult -eq 0 -and
            -not $pushStartRpcTimedOut -and
            [string]::IsNullOrEmpty([string]$pushStartError) -and
            -not $pushStopRpcTimedOut -and
            -not $oneShotPushStopExhausted -and
            -not $oneShotPushContainmentBreached -and
            $publicationAck.local_exact -and $publicationAck.remote_exact)) {
            $terminalDetail = if ($publicationAck.local_still_unpublished -and
                $publicationAck.remote_still_target) {
                "WeatherOneShotPush terminal run did not publish M"
            }
            else {
                "WeatherOneShotPush terminal run left unreachable, moved, or mixed local/remote refs"
            }
            if ($pushStartError) { $terminalDetail += "; start_error=$pushStartError" }
            if ($oneShotPushContainmentBreached) {
                $terminalDetail += "; 04:00 containment/terminal-proof boundary was breached"
            }
            $terminalStage = if (-not $oneShotPushContainmentBreached -and
                $publicationAck.local_still_unpublished -and
                $publicationAck.remote_still_target) {
                "reconciliation_merged_unpublished"
            }
            else { "publication_state_uncertain" }
            Stop-Reconciliation `
                -Detail "$terminalDetail; invocation spent, M and marker preserved" `
                -Stage $terminalStage -ExitCode 3 -Ok $true
        }
        $publicationAcknowledged = $true
        try {
            Assert-OneShotPushTask -Quiet
            $publishedTaskInfo = Get-ReconciliationOneShotPushTaskInfo
            if ($publishedTaskInfo.last_run_time -ne $pushTerminalInfo.last_run_time -or
                $publishedTaskInfo.last_task_result -ne $pushTerminalInfo.last_task_result) {
                throw "WeatherOneShotPush runtime changed after terminal acknowledgement"
            }
            Assert-ReconciliationMergeCommit -Commit $mergeCommit
            Write-ReconciliationMarker -Phase "published"
        }
        catch {
            Stop-Reconciliation `
                -Detail "origin acknowledged M but published marker could not be atomically advanced; preserving evidence" `
                -Stage "published_marker_ambiguous" -ExitCode 3 -Ok $true
        }
        Note "production-baseline reconciliation published exact M=$mergeCommit via the sole authorized task invocation"
        Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (synthetic [config-child,safety-tip] via WeatherOneShotPush)"
        exit 0
    }
    finally { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
}

$ownerProtectedWindowException = $false
if ($OwnerApprovedException) {
    $authorizedRoot = "71f7e46690e822a498f80412c11d550bcee949d2"
    $authorizedBaseline = "9d54f94760855a5f91ac603f3f14b02ba06ae239"
    $ownerAncestorExit = 1
    if ($ExpectedTip -match '^[0-9a-f]{40}$') {
        & git -C $repo merge-base --is-ancestor $authorizedRoot $ExpectedTip
        $ownerAncestorExit = $LASTEXITCODE
    }
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        -not $Force -or
        (Get-Date).ToString("yyyy-MM-dd") -cne "2026-08-23" -or
        $Branch -cne "origin/codex/live-readiness-closure-20260823" -or
        $ExpectedBaseline -cne $authorizedBaseline -or
        $ownerAncestorExit -ne 0
    ) {
        Fail "owner-approved protected-window exception is invalid, unbound, or expired"
    }
    $ownerProtectedWindowException = $true
    Note "one-time repository-owner protected-window exception accepted for exact branch lineage and baseline"
}

# The broad host windows do not depend on the roll verdict. Refuse them before
# taking the shared lease, then serialize the verdict and every subsequent Git,
# recovery, documentation, and publication decision under that one OS handle.
$h = (Get-Date).Hour + ((Get-Date).Minute / 60.0)
if (-not $ownerProtectedWindowException -and $h -ge 12 -and $h -lt 18) {
    Fail "inside the 12:00-18:00 graded capture window - never merge here"
}
if (-not $ownerProtectedWindowException -and ($h -ge 18 -or $h -lt 0.5)) {
    Fail ("inside the 18:00-00:30 protected near-close window (now {0:N2}) - no heavy work here" -f $h)
}
$workloadLease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $repo `
    -Workload "quiet_window_merge" `
    -OwnerApprovedException $OwnerApprovedException
if ($null -eq $workloadLease) { Fail "another heavyweight host workload owns data/logs/heavy_workload.lock" }
try {

# ---- window guard, proportional to the branch's actual roll verdict ----
# This used to demand 01:00-04:00 for EVERY branch, including branches that cannot roll
# anything. That is a guard against a risk the branch does not carry, and it was the real
# reason the merge queue backed up: 25 unmerged branches queued for three hours a night,
# most of them roll-free. A guard that costs more than the risk it prevents gets worked
# around, and then it protects nothing.
#
# So ask first. roll_verdict.ps1 derives the answer from the live closures rather than by
# hand -- exit 0 roll-free, 2 roll-free-only-while-a-loop-stays-dormant, 3 roll-sensitive,
# 1 undecidable. Anything that is not a clean 0 is treated as roll-sensitive: the cost of a
# wrong "free" is a streak day, the cost of a wrong "sensitive" is waiting until 01:00.
$verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"
$rollFree = $false
$rollVerdictReadable = $false
$executionTapeActive = Test-ExecutionTapeActive
if (-not $ExpectedTip) {
    # Classify the exact already-fetched object. A later fetch that moves the
    # branch then fails the equality check instead of borrowing this verdict.
    $preVerdictCommitRef = "{0}^{{commit}}" -f $Branch
    $preVerdictBranchTip = @(& git -C $repo rev-parse --verify $preVerdictCommitRef)
    if ($LASTEXITCODE -ne 0 -or $preVerdictBranchTip.Count -ne 1 -or
        ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant() -notmatch '^[0-9a-f]{40}$') {
        Fail "branch is not locally resolvable before roll classification: $Branch"
    }
    $ExpectedTip = ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant()
    Note "observed branch tip frozen before roll classification: $Branch -> $ExpectedTip"
}
$verdictRef = $ExpectedTip
if (Test-Path -LiteralPath $verdictScript) {
    $verdictJsonPath = Join-Path ([IO.Path]::GetTempPath()) ("weather-roll-verdict-{0}.json" -f [guid]::NewGuid().ToString("N"))
    try {
        & $verdictScript -Branch $verdictRef -JsonOut $verdictJsonPath |
            ForEach-Object { Note "roll_verdict: $_" }
        $verdictExitCode = $LASTEXITCODE
        $rollFree = ($verdictExitCode -eq 0)
        if (Test-Path -LiteralPath $verdictJsonPath -PathType Leaf) {
            try {
                $verdictPayload = Get-Content -LiteralPath $verdictJsonPath -Raw | ConvertFrom-Json
                $rollVerdictReadable = $true
                $executionTapeReadoptionExpected = @(
                    $verdictPayload.files |
                        Where-Object {
                            $_.rolls -eq $true -and
                            @($_.closures) -contains "execution_tape"
                        }
                ).Count -gt 0
            }
            catch {
                Note "WARNING: roll-verdict JSON was unreadable; any active execution tape will be gated conservatively"
            }
        }
        Note ("roll verdict exit {0} -> {1}" -f $verdictExitCode, $(if ($rollFree) { "ROLL-FREE" } else { "treated as ROLL-SENSITIVE" }))
    }
    finally {
        Remove-Item -LiteralPath $verdictJsonPath -Force -ErrorAction SilentlyContinue
    }
}
else { Note "roll_verdict.ps1 not found - treating branch as ROLL-SENSITIVE" }

# Gate the auxiliary producer exactly when its live closure rolls. If the
# mechanical verdict could not emit its structured closure proof, fail safe by
# gating an active producer; do not start or enable a disabled inactive task.
$executionTapeRecoveryRequired = ($executionTapeReadoptionExpected -and $executionTapeActive) -or
    ($executionTapeActive -and -not $rollVerdictReadable)
$executionTapeRolledButInactiveSkipped = $executionTapeReadoptionExpected -and -not $executionTapeActive
if ($executionTapeRecoveryRequired) {
    Note ("execution-tape recovery proof required ({0})" -f $(if ($executionTapeReadoptionExpected) { "closure rolls" } else { "active producer with unreadable closure verdict" }))
}
elseif ($executionTapeRolledButInactiveSkipped) {
    Note "execution-tape closure was listed but the optional producer is held inactive; leaving it disabled and skipping recovery proof"
}

if (-not $rollFree -and -not $Force -and -not ($h -ge 1 -and $h -lt 4)) {
    Fail ("roll-sensitive branch outside the 01:00-04:00 quiet window (now {0:N2}); use -Force only if you are certain a capture roll is safe right now" -f $h)
}
if ($rollFree) { Note ("roll-free branch: 01:00-04:00 not required (now {0:N2})" -f $h) }

# ---- preconditions ----
Set-Location $repo
# Never start on top of a merge that is already in progress. WeatherBootRecovery cleans one
# up after a power loss, but if that has not run yet the tree still holds unreviewed merged
# code, and merging again on top of it would bury the problem instead of surfacing it.
if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
    $priorMarkerReason = "a prior quiet-window merge marker still exists - let WeatherBootRecovery reconcile it before another merge"
    Note "ABORT: $priorMarkerReason"
    if ($AttemptReportPath) {
        # A stronger post-commit crash marker may belong to this same attempt.
        # Do not poison its still-unused immutable report path with a weaker
        # retry-time abort; the parent/reconciler must inspect the marker.
        throw $priorMarkerReason
    }
    Save-Report -ok $false -stage "abort" -detail $priorMarkerReason
    exit 1
}
$existingMergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
if (-not [IO.Path]::IsPathRooted($existingMergeHeadPath)) {
    $existingMergeHeadPath = Join-Path $repo $existingMergeHeadPath
}
if (Test-Path -LiteralPath $existingMergeHeadPath -PathType Leaf) {
    Fail "a merge is already in progress (.git/MERGE_HEAD exists) - resolve or abort it first; see data/alerts/boot_events.jsonl for an interrupted-merge record"
}
try { Assert-OneShotPushTask }
catch { Fail $_.Exception.Message }
# WeatherLocationConfigRefresh rewrites the two config files every 6 hours, including once
# just before this window. Refusing that generated drift would make this tool abort on an
# otherwise normal production tree. The guard exists so a rollback cannot destroy WORK;
# these two files are fleet-regenerated state, not authored work. Commit them rather than
# ignore them, which both cleans the tree and preserves the drift, and only then take the
# rollback point. Keep this list exact: no other dirty tracked path may pass automatically.
$autoRefreshed = @(
    "config/locations.json",
    "config/location_market_events.json"
)
$dirtyTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
$unexpected = @($dirtyTracked | Where-Object {
        $p = ($_ -replace '^..\s*', '').Trim()
        $autoRefreshed -notcontains $p
    })
if ($unexpected.Count -gt 0) {
    Fail "tracked files are modified outside the fleet-generated drift set; commit or stash first so rollback cannot lose work:`n$($unexpected -join "`n")"
}

# This runs S4U in session 0, which cannot reach the credential vault, so fetch can fail
# exactly the way push does. That is survivable -- the local refs are what we merge -- but
# it means merging whatever copy of the branch was last fetched, so say so rather than
# letting a stale merge look like a fresh one.
$gitFetchExit = Invoke-GitAllowingNativeStderr { & git fetch origin --prune | Out-Null }
if ($gitFetchExit -ne 0) { Note "WARNING: git fetch failed (no credential vault under S4U?); merging the last-fetched copy of $Branch" }
$branchCommitRef = "{0}^{{commit}}" -f $Branch
$branchVerifyExit = Invoke-GitAllowingNativeStderr { & git rev-parse --verify $branchCommitRef | Out-Null }
if ($branchVerifyExit -ne 0) { Fail "branch not found: $Branch" }
$resolvedBranchTip = (& git rev-parse $branchCommitRef).Trim().ToLowerInvariant()
if ($resolvedBranchTip -ne $ExpectedTip) {
    Fail "branch tip moved: $Branch resolves to $resolvedBranchTip, expected reviewed tip $ExpectedTip"
}
Note "exact-tip binding passed: $Branch -> $resolvedBranchTip"
# Merge the immutable object, not the movable ref, even for an interactive
# caller that omitted ExpectedTip. A later ref update cannot change the tree.
$mergeTarget = $resolvedBranchTip
$head = (& git rev-parse HEAD).Trim()
$originMaster = (& git rev-parse origin/master).Trim()
$currentBranchOutput = @(& git symbolic-ref --quiet --short HEAD)
$currentBranchExit = $LASTEXITCODE
$currentBranch = if ($currentBranchOutput.Count -eq 0) { "" } else { ([string]$currentBranchOutput[-1]).Trim() }
if ($currentBranchExit -ne 0 -or $currentBranch -ne "master") {
    Fail "production working tree must have master checked out; current branch is $currentBranch"
}
if ($head -ne $originMaster) { Fail "local master ($head) != origin/master ($originMaster); reconcile first" }
if ($ExpectedBaseline -and ($head.ToLowerInvariant() -ne $ExpectedBaseline -or
    $originMaster.ToLowerInvariant() -ne $ExpectedBaseline)) {
    Fail "production baseline moved: master=$head origin/master=$originMaster expected=$ExpectedBaseline"
}
$baselineCommit = $head.ToLowerInvariant()
if (-not $ExpectedBaseline) {
    # Direct/manual callers historically omitted the frozen baseline. Once the
    # synchronized local/remote identity is proved under the workload lease,
    # bind that observed baseline into every crash marker and terminal report.
    $ExpectedBaseline = $baselineCommit
    Note "observed synchronized baseline bound for crash recovery: $ExpectedBaseline"
}
foreach ($relativePath in $autoRefreshed) {
    $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
    if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
        $rollbackContentSha256[$relativePath] = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
if ($rollbackContentSha256.Count -ne $autoRefreshed.Count) {
    Fail "both fleet-generated config files must exist before merge preparation"
}

function Restore-PreparedBaseline {
    $resetExit = Invoke-GitAllowingNativeStderr {
        & git reset --mixed $baselineCommit | Out-Null
    }
    $actualHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $tracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    $unexpectedPaths = @($tracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    return [PSCustomObject]@{
        ok = ($resetExit -eq 0 -and $actualHead -eq $baselineCommit -and
            $unexpectedPaths.Count -eq 0 -and $contentMismatch.Count -eq 0)
        git_exit = $resetExit
        actual_head = $actualHead
        unexpected_paths = @($unexpectedPaths)
        content_mismatch = @($contentMismatch)
    }
}

function Stop-AfterPreparationFailure {
    param([Parameter(Mandatory = $true)][string]$Reason)

    $restored = Restore-PreparedBaseline
    if (-not $restored.ok) {
        $detail = "pre-merge failure could not restore successor-resumable baseline $baselineCommit; git_exit=$($restored.git_exit) head=$($restored.actual_head) unexpected_dirty=$(@($restored.unexpected_paths).Count) content_mismatch=$(@($restored.content_mismatch) -join ','); original=$Reason"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }
    Note "ABORT: $Reason; synchronized baseline restored with generated config preserved as allowlisted drift"
    Save-Report -ok $false -stage "abort" -detail $Reason
    exit 1
}

# Journal before the optional generated-config commit. A hard kill after git
# add or commit but before the later prepared-phase update can then restore the
# synchronized baseline with the exact pre-recorded config bytes intact.
$preMerge = $baselineCommit
try {
    Write-QuietMergeMarker -Phase "preparing"
    $activeMarkerOwned = $true
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge preparation marker could not be created"
}

if ($dirtyTracked.Count -gt 0) {
    Note "committing $($dirtyTracked.Count) fleet-generated drift file(s) so the merge starts clean"
    $gitAddExit = Invoke-GitAllowingNativeStderr { & git add -- $autoRefreshed }
    if ($gitAddExit -ne 0) { Stop-AfterPreparationFailure "failed to stage fleet-generated drift (git exit $gitAddExit)" }
    $gitCommitExit = Invoke-GitAllowingNativeStderr {
        & git commit -m "ops: preserve fleet-generated drift (pre-merge, automated)" | Out-Null
    }
    if ($gitCommitExit -ne 0) { Stop-AfterPreparationFailure "failed to commit fleet-generated drift (git exit $gitCommitExit)" }
}
# Take the immediate rollback point after the drift commit. Failure first
# restores this exact tree, then mixed-resets the original baseline so the
# generated contents survive as allowlisted working-tree drift.
$preMerge = (& git rev-parse HEAD).Trim()
try {
    # Refresh the preparation journal with the exact temporary config commit,
    # but do not call it prepared until the pre-roll producer identities below
    # are durable too. In particular, an active execution tape needs its old
    # source fingerprint recorded before a staged merge can touch the tree.
    Write-QuietMergeMarker -Phase "preparing"
}
catch {
    # If the optional generated-drift commit succeeded but its crash marker
    # could not be persisted, restore synchronized master while retaining the
    # generated contents as the same two allowlisted working-tree changes.
    Stop-AfterPreparationFailure "durable quiet-merge crash marker could not be created"
}
# NEVER redirect a native command's stderr here (no *>$null, no 2>&1). Under
# $ErrorActionPreference='Stop', PowerShell 5.1 wraps each redirected stderr line in a
# NativeCommandError and terminates -- and git writes routine notices to stderr, so a
# harmless "CRLF will be replaced by LF" warning killed a dry run mid-merge and left the
# tree in a half-merged state (2026-07-25). Send stdout to Out-Null and let stderr print.
Note "pre-merge HEAD $preMerge; merging $Branch ($($resolvedBranchTip.Substring(0, 12)))"

# ---- capture baseline (what we will require to still be true afterwards) ----
# Command lines are hidden for S4U-owned processes, and one fresh snapshot heartbeat says
# nothing about the CLOB or observation workers. The checker validates all three workers'
# status + writer-lock PID, process liveness, heartbeat freshness, and loaded-source
# fingerprint against the current tree. That is the same recovery contract supervisors own.
function Get-CaptureState {
    try {
        $raw = @(& $py -m weather.operations.capture_recovery_check --repo-root $repo --json)
        $exitCode = $LASTEXITCODE
        $state = (($raw -join "`n") | ConvertFrom-Json)
        if ($exitCode -ne 0) { $state.ok = $false }
        return $state
    }
    catch {
        return [PSCustomObject]@{ ok = $false; workers = @(); error = $_.Exception.Message }
    }
}

function Get-ExecutionTapeState {
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    try {
        $raw = @(& $py -m weather.operations.execution_tape_supervisor status --stale-after-seconds 180)
        $exitCode = $LASTEXITCODE
        $payload = (($raw -join "`n") | ConvertFrom-Json)
        $health = $payload.health
        $status = $payload.status
        $reasons = New-Object System.Collections.Generic.List[string]
        if ($exitCode -ne 0) { $reasons.Add("status_exit_$exitCode") }
        if (@("RUNNING", "DEGRADED") -notcontains [string]$health.state) {
            $reasons.Add("health_$([string]$health.state)")
        }
        if ($health.pid_alive -ne $true) { $reasons.Add("pid_not_alive") }
        if ($health.runtime_identity_matches_current -ne $true) { $reasons.Add("runtime_identity_stale") }
        if ([string]$health.evidence_integrity -ne "PASS") { $reasons.Add("evidence_integrity_$([string]$health.evidence_integrity)") }
        if ([string]$status.state -ne "CONNECTED") { $reasons.Add("capture_$([string]$status.state)") }
        if ([string]$status.market -ne "all" -or [string]$status.runner -ne "managed_execution_tape") {
            $reasons.Add("managed_scope_mismatch")
        }
        if ($status.managed_process.verified_at_capture -ne $true) {
            $reasons.Add("managed_process_unverified")
        }
        if (-not (Test-Path -LiteralPath $writerLockPath -PathType Leaf)) {
            $reasons.Add("writer_lock_missing")
            $writerLock = $null
        }
        else {
            $writerLock = Get-Content -LiteralPath $writerLockPath -Raw | ConvertFrom-Json
            if ([int]$status.pid -le 0 -or
                [int]$status.pid -ne [int]$status.managed_process.pid -or
                [int]$status.pid -ne [int]$writerLock.pid -or
                [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
                [string]$status.managed_process.creation_time_token -cne
                    [string]$writerLock.managed_process.creation_time_token) {
                $reasons.Add("writer_identity_mismatch")
            }
        }
        $lastHeartbeat = if ($status.last_heartbeat) {
            [string]$status.last_heartbeat
        }
        else {
            [string]$status.updated_at_utc
        }
        return [PSCustomObject]@{
            ok = ($reasons.Count -eq 0)
            pid = [int]$status.pid
            last_heartbeat = $lastHeartbeat
            recorded_source_fingerprint = [string]$status.runtime_identity.source_fingerprint
            reasons = @($reasons)
            health = $health
            status = $status
            writer_lock = $writerLock
        }
    }
    catch {
        return [PSCustomObject]@{
            ok = $false
            pid = 0
            last_heartbeat = $null
            recorded_source_fingerprint = $null
            reasons = @($_.Exception.Message)
            health = $null
            status = $null
            writer_lock = $null
        }
    }
}

function Invoke-RollbackAndProve {
    param(
        [Parameter(Mandatory = $true)][string[]]$Reasons,
        [ValidateSet("rolled_back", "dry_run")][string]$RecoveredStage = "rolled_back",
        [bool]$RecoveredOk = $false,
        [ValidateSet(0, 2)][int]$RecoveredExitCode = 2
    )

    $primaryDetail = ($Reasons | Where-Object { $_ }) -join "; "
    if (-not $primaryDetail) { $primaryDetail = "guarded merge did not complete" }
    Note "merge will not be committed: $primaryDetail"

    $mergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    $restoreExit = 0
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        $restoreExit = Invoke-GitAllowingNativeStderr { & git merge --abort | Out-Null }
    }
    else {
        # A successful explicit commit removes MERGE_HEAD. This path is used
        # only if a later structural check on that unpublished commit failed.
        $restoreExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }
    if ($restoreExit -ne 0) {
        $restoreExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }

    $restoredHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $remainingMergeHead = Test-Path -LiteralPath $mergeHeadPath -PathType Leaf
    $remainingTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    if ($restoreExit -ne 0 -or $restoredHead -ne $preMerge.ToLowerInvariant() -or
        $remainingMergeHead -or $remainingTracked.Count -ne 0) {
        $detail = "merge rollback could not restore exact pre-merge tree $preMerge; git_exit=$restoreExit head=$restoredHead merge_head=$remainingMergeHead dirty=$($remainingTracked.Count); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    # The automatic generated-config commit is a temporary merge preparation,
    # not a new production baseline. Move master back to the originally
    # synchronized commit with a mixed reset so the exact generated contents
    # survive as the same two allowlisted working-tree changes. A successor can
    # then re-run without first reconciling an unpublished local commit.
    if ($preMerge.ToLowerInvariant() -ne $baselineCommit.ToLowerInvariant()) {
        $baselineResetExit = Invoke-GitAllowingNativeStderr {
            & git reset --mixed $baselineCommit | Out-Null
        }
        if ($baselineResetExit -ne 0) {
            $detail = "merge rollback reached $preMerge but could not restore synchronized baseline $baselineCommit; git_exit=$baselineResetExit; original=$primaryDetail"
            Note $detail
            Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
            exit 4
        }
    }
    $finalRollbackHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $finalTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    $unexpectedRollbackPaths = @($finalTracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    if ($finalRollbackHead -ne $baselineCommit.ToLowerInvariant() -or
        $unexpectedRollbackPaths.Count -ne 0 -or $contentMismatch.Count -ne 0) {
        $detail = "merge rollback did not leave a successor-resumable baseline; expected_head=$baselineCommit actual_head=$finalRollbackHead unexpected_dirty=$($unexpectedRollbackPaths.Count) content_mismatch=$($contentMismatch -join ','); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "rolled back to synchronized baseline $baselineCommit with generated config preserved as allowlisted drift; nothing was pushed. Waiting up to ${RollbackRecoverySeconds}s for every affected producer to re-adopt the rollback..."
    $rollbackDeadline = (Get-Date).AddSeconds($RollbackRecoverySeconds)
    do {
        $rollbackState = Get-CaptureState
        $rollbackCoreOk = $rollbackState.ok -and @($rollbackState.workers).Count -eq 3
        $rollbackExecutionState = $null
        $rollbackExecutionOk = $true
        if ($executionTapeRecoveryRequired) {
            $rollbackExecutionState = Get-ExecutionTapeState
            $rollbackExecutionOk = $rollbackExecutionState.ok -and
                [string]$rollbackExecutionState.recorded_source_fingerprint -ceq
                    [string]$executionBefore.recorded_source_fingerprint
        }
        if ($rollbackCoreOk -and $rollbackExecutionOk) { break }
        if ((Get-Date) -lt $rollbackDeadline) { Start-Sleep -Seconds 15 }
    } while ((Get-Date) -lt $rollbackDeadline)

    if (-not $rollbackCoreOk -or -not $rollbackExecutionOk) {
        $rollbackWhy = @(
            $rollbackState.workers |
                Where-Object { -not $_.ok } |
                ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }
        )
        if ($rollbackState.error) { $rollbackWhy += [string]$rollbackState.error }
        if ($executionTapeRecoveryRequired -and -not $rollbackExecutionOk) {
            $rollbackWhy += "execution_tape=$(@($rollbackExecutionState.reasons) -join ','); expected_source=$($executionBefore.recorded_source_fingerprint); actual_source=$($rollbackExecutionState.recorded_source_fingerprint)"
        }
        if ($rollbackWhy.Count -eq 0) { $rollbackWhy += "recovery contract unreadable" }
        $detail = "merge recovery failed: $primaryDetail; rollback recovery unproven: $($rollbackWhy -join '; ')"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "every affected producer re-adopted the rollback and satisfies its exact recovery contract"
    Save-Report -ok $RecoveredOk -stage $RecoveredStage -detail $primaryDetail
    exit $RecoveredExitCode
}

$before = Get-CaptureState
Note "capture before: ok=$($before.ok), workers=$(@($before.workers).Count)"
if (-not $before.ok -or @($before.workers).Count -ne 3) {
    $detail = @($before.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }) -join "; "
    if (-not $detail) { $detail = [string]$before.error }
    Stop-AfterPreparationFailure "capture recovery contract is not healthy before merge: $detail"
}
$executionBefore = $null
if ($executionTapeRecoveryRequired) {
    $executionBefore = Get-ExecutionTapeState
    Note "execution tape before: ok=$($executionBefore.ok), pid=$($executionBefore.pid), source=$($executionBefore.recorded_source_fingerprint)"
    if (-not $executionBefore.ok) {
        Stop-AfterPreparationFailure "execution-tape recovery contract is not healthy before merge: $(@($executionBefore.reasons) -join ',')"
    }
    $executionTapeSourceBefore = [string]$executionBefore.recorded_source_fingerprint
}
try {
    Write-QuietMergeMarker -Phase "prepared"
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge marker could not bind the pre-roll recovery identities"
}

if ($DryRun) {
    $dryMergeExit = Invoke-GitAllowingNativeStderr { & git merge --no-commit --no-ff $mergeTarget | Out-Null }
    $conflicts = @(& git diff --name-only --diff-filter=U | Where-Object { $_ })
    # Always unwind: leaving a half-merged tree changes loop-loaded modules on disk and
    # provokes a STALE_CODE readoption roll. `merge --abort` restores the pre-merge state
    # including uncommitted config drift. At this point tracked drift has already been
    # committed, so a hard reset to the exact pre-merge point is a safe fallback.
    $dryAbortExit = Invoke-GitAllowingNativeStderr { & git merge --abort | Out-Null }
    if ($dryAbortExit -ne 0) {
        $dryAbortExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }
    if ($dryAbortExit -ne 0 -or (& git rev-parse HEAD).Trim() -ne $preMerge) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore $preMerge"
        exit 4
    }
    $dryRestore = Restore-PreparedBaseline
    if (-not $dryRestore.ok) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore synchronized baseline $baselineCommit with generated bytes intact"
        exit 4
    }
    Note "DRY RUN: conflicts=$($conflicts.Count)"
    # Staging the dry merge exposed target bytes to the same supervisors as a
    # real merge. Do not retire its marker merely because Git was restored;
    # prove every affected producer has re-adopted the rollback first.
    $dryRunOk = $dryMergeExit -eq 0
    $dryRunExitCode = if ($dryRunOk) { 0 } else { 2 }
    Invoke-RollbackAndProve `
        -Reasons @("dry-run merge_exit=$dryMergeExit conflicts=$($conflicts.Count)") `
        -RecoveredStage "dry_run" `
        -RecoveredOk $dryRunOk `
        -RecoveredExitCode $dryRunExitCode
}

# ---- stage locally without committing (this triggers the readoption roll) ----
# MERGE_HEAD is the durable crash marker. Keep it present through the complete
# recovery proof so WeatherBootRecovery can always abort an interrupted,
# unverified roll after power loss. Only a successful proof earns the explicit
# merge commit below.
$mergeCommitted = $false
try {
    $mergeExit = Invoke-GitAllowingNativeStderr {
        & git merge --no-commit --no-ff $mergeTarget | Out-Null
    }
    if ($mergeExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("merge failed or conflicted (git exit $mergeExit)")
    }
    $mergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    if (-not (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        (& git rev-parse HEAD).Trim() -ne $preMerge) {
        Invoke-RollbackAndProve -Reasons @("no-commit merge did not preserve MERGE_HEAD and the exact pre-merge HEAD")
    }
    Write-QuietMergeMarker -Phase "merge_uncommitted"
    Note "merge staged with MERGE_HEAD preserved (NOT committed or pushed)"

    # ---- wait for every affected producer to readopt, then prove recovery ----
    Note "waiting ${SettleSeconds}s for supervisors to readopt the new code..."
    Start-Sleep -Seconds $SettleSeconds
    $after = Get-CaptureState
    Note "capture after: ok=$($after.ok), workers=$(@($after.workers).Count)"

    $ok = $true
    $why = @()
    if (-not $after.ok -or @($after.workers).Count -ne 3) {
        $ok = $false
        $why += @($after.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" })
        if ($after.error) { $why += [string]$after.error }
    }
    foreach ($beforeWorker in @($before.workers)) {
        $afterWorker = @($after.workers | Where-Object { $_.name -eq $beforeWorker.name }) | Select-Object -First 1
        if (-not $afterWorker) {
            $ok = $false; $why += "$($beforeWorker.name) missing after merge"; continue
        }
        # The snapshot worker normally heartbeats once per roughly ten-minute cycle, longer
        # than the default five-minute settle. Requiring every healthy worker to advance here
        # made a CLOB-only roll depend on where the unrelated snapshot sleep happened to fall.
        # The recovery checker above still requires every worker to be fresh, live, locked by
        # the matching PID, and loaded from the current tree. Require heartbeat advancement in
        # addition when this worker actually readopted (PID or recorded source identity changed).
        $workerReadopted = (
            [int]$afterWorker.pid -ne [int]$beforeWorker.pid -or
            [string]$afterWorker.recorded_source_fingerprint -ne [string]$beforeWorker.recorded_source_fingerprint
        )
        if (-not $workerReadopted) { continue }
        try {
            if ([datetime]$afterWorker.last_heartbeat -le [datetime]$beforeWorker.last_heartbeat) {
                $ok = $false
                $why += "$($beforeWorker.name) readopted but heartbeat did not advance ($($beforeWorker.last_heartbeat) -> $($afterWorker.last_heartbeat))"
            }
        }
        catch { $ok = $false; $why += "$($beforeWorker.name) readoption heartbeat comparison failed" }
    }

    $executionAfter = $null
    if ($executionTapeRecoveryRequired) {
        $executionAfter = Get-ExecutionTapeState
        Note "execution tape after: ok=$($executionAfter.ok), pid=$($executionAfter.pid), source=$($executionAfter.recorded_source_fingerprint)"
        if (-not $executionAfter.ok) {
            $ok = $false
            $why += "execution_tape=$(@($executionAfter.reasons) -join ',')"
        }
        if ($executionTapeReadoptionExpected) {
            if ([string]$executionAfter.recorded_source_fingerprint -ceq
                [string]$executionBefore.recorded_source_fingerprint) {
                $ok = $false
                $why += "execution_tape closure rolled but loaded-source fingerprint did not change"
            }
            try {
                if ([datetime]$executionAfter.last_heartbeat -le [datetime]$executionBefore.last_heartbeat) {
                    $ok = $false
                    $why += "execution_tape readopted but heartbeat did not advance ($($executionBefore.last_heartbeat) -> $($executionAfter.last_heartbeat))"
                }
            }
            catch {
                $ok = $false
                $why += "execution_tape readoption heartbeat comparison failed"
            }
        }
    }

    if (-not $ok) {
        Invoke-RollbackAndProve -Reasons $why
    }
    $captureRecoveryProved = $true
    if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }
    Write-QuietMergeMarker -Phase "capture_recovered_uncommitted"

    # Recovery is proved while MERGE_HEAD still makes the operation boot-
    # recoverable. Commit only now, then verify the exact two-parent identity.
    $mergeCommitExit = Invoke-GitAllowingNativeStderr {
        & git commit -m "Merge $Branch into master" | Out-Null
    }
    if ($mergeCommitExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("recovery passed but explicit merge commit failed (git exit $mergeCommitExit)")
    }
    $candidateMergeCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $firstParent = (& git rev-parse "$candidateMergeCommit^1").Trim().ToLowerInvariant()
    $secondParent = (& git rev-parse "$candidateMergeCommit^2").Trim().ToLowerInvariant()
    if ((Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        $firstParent -ne $preMerge.ToLowerInvariant() -or
        $secondParent -ne $resolvedBranchTip.ToLowerInvariant()) {
        Invoke-RollbackAndProve -Reasons @("explicit merge commit did not bind the exact pre-merge and reviewed-tip parents")
    }
    $mergeCommit = $candidateMergeCommit
    Write-QuietMergeMarker -Phase "merge_committed_unpublished"
    $mergeCommitted = $true
    Note "recovery-proved merge committed locally as $mergeCommit (NOT pushed yet)"
}
catch {
    if (-not $mergeCommitted) {
        Invoke-RollbackAndProve -Reasons @("unexpected pre-commit failure: $($_.Exception.GetType().Name)")
    }
    throw
}

# ---- bind the post-integration documentation transaction before publication ----
# The documentation closeout cannot truthfully finish until the exact merge and live recovery
# exist. Record that debt now, before publication, so a missing morning closeout is visible in
# status and a later transaction can cover the exact pending-state hash. Stacked overnight
# merges append to the same bounded transaction.
$documentationArgs = @(
    "-m", "weather.operations.documentation_transaction",
    "--repo-root", $repo,
    "begin",
    "--integration-tip", $mergeCommit,
    "--branch", $Branch
)
if ($ExpectedTip) { $documentationArgs += @("--expected-tip", $ExpectedTip) }
$previousDocumentationErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $documentationOutput = & $py @documentationArgs
    $documentationExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousDocumentationErrorPreference
}
if ($documentationExit -ne 0) {
    Note "documentation transaction could not be recorded: $($documentationOutput -join ' ')"
    # `begin` atomically updates a shared pending transaction and then its
    # content-addressed snapshot. A nonzero child can therefore be ambiguous
    # about whether that durable mutation happened. Without a compensating
    # transaction it is unsafe to delete the merge it may now reference.
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction begin failed or was ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
try {
    $documentationPayload = (($documentationOutput -join "`n") | ConvertFrom-Json)
    $pendingSha256 = ([string]$documentationPayload.pending_sha256).ToLowerInvariant()
    $matchingDocumentationEntry = @(
        $documentationPayload.integrations |
            Where-Object {
                ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
                [string]$_.branch -ceq $Branch
            }
    ) | Select-Object -First 1
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        ([string]$documentationPayload.latest_integration_tip).ToLowerInvariant() -ne $mergeCommit -or
        $null -eq $matchingDocumentationEntry -or
        ($ExpectedTip -and ([string]$matchingDocumentationEntry.expected_tip).ToLowerInvariant() -ne $ExpectedTip)) {
        throw "documentation transaction output did not bind the exact integration"
    }
    $documentationPendingPath = Join-Path $repo "data\alerts\documentation_transaction_pending.json"
    $documentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    $documentationSnapshotPath = Join-Path $repo ($documentationSnapshotRelative -replace '/', '\')
    if (-not (Test-Path -LiteralPath $documentationPendingPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $documentationSnapshotPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $documentationPendingPath -Algorithm SHA256).Hash -ine $pendingSha256 -or
        (Get-FileHash -LiteralPath $documentationSnapshotPath -Algorithm SHA256).Hash -ine $pendingSha256) {
        throw "documentation transaction pending state and immutable snapshot do not match"
    }
    $documentationTransactionPendingSha256 = $pendingSha256
    $documentationTransactionSnapshotPath = $documentationSnapshotRelative
    $documentationTransactionRecorded = $true
}
catch {
    Note "documentation transaction returned success without exact durable identity: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction identity is ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
Note "documentation transaction recorded for $mergeCommit"
try {
    Write-QuietMergeMarker -Phase "documented_unpublished"
    $documentedMarkerSha256 = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}
catch {
    # The pending documentation transaction now names this merge. Preserve both
    # and the prior merge_committed_unpublished marker for reviewed, idempotent
    # reconciliation; resetting would create an orphan transaction.
    Note "documentation succeeded but its durable merge marker could not be updated; preserving local merge for reviewed resume"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation marker update failed for local commit $mergeCommit; reviewed resume required"
    exit 3
}

# ---- only now publish, through the credential-bearing scheduled task ----
# Interactive git push is forbidden on this host. The scheduled task owns the credential
# context, and origin/master is the acknowledgement that the immutable merge commit landed.
$prePublicationFailure = $null
try {
    $finalHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $finalMaster = (& git rev-parse master).Trim().ToLowerInvariant()
    $finalOriginMaster = (& git rev-parse origin/master).Trim().ToLowerInvariant()
    $finalBranch = (& git symbolic-ref --quiet --short HEAD).Trim()
    $finalMergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($finalMergeHeadPath)) {
        $finalMergeHeadPath = Join-Path $repo $finalMergeHeadPath
    }
    if ($finalBranch -ne "master" -or $finalHead -ne $mergeCommit -or
        $finalMaster -ne $mergeCommit -or
        $finalOriginMaster -notin @($baselineCommit, $mergeCommit) -or
        (Test-Path -LiteralPath $finalMergeHeadPath -PathType Leaf)) {
        throw "Git identity changed after recovery proof"
    }

    $finalMarkerShaBefore = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if (-not $documentedMarkerSha256 -or $finalMarkerShaBefore -ne $documentedMarkerSha256) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalMarkerRaw = [IO.File]::ReadAllText($activeMarkerPath, [Text.Encoding]::UTF8)
    $finalMarker = $finalMarkerRaw | ConvertFrom-Json
    $finalMarkerShaAfter = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($finalMarkerShaAfter -ne $documentedMarkerSha256) {
        throw "durable merge/documentation marker changed while it was being verified"
    }
    if ([string]$finalMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        [string]$finalMarker.phase -ne "documented_unpublished" -or
        ([string]$finalMarker.merge_commit).ToLowerInvariant() -ne $mergeCommit -or
        ([string]$finalMarker.baseline_commit).ToLowerInvariant() -ne $baselineCommit -or
        ([string]$finalMarker.resolved_branch_tip).ToLowerInvariant() -ne $resolvedBranchTip -or
        $finalMarker.documentation_transaction_recorded -ne $true -or
        ([string]$finalMarker.documentation_transaction_pending_sha256).ToLowerInvariant() -ne
            $documentationTransactionPendingSha256 -or
        [string]$finalMarker.documentation_transaction_snapshot_path -cne
            $documentationTransactionSnapshotPath -or
        $finalMarker.publication_acknowledged -eq $true) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalDocumentationSnapshotPath = Join-Path $repo (
        $documentationTransactionSnapshotPath -replace '/', '\'
    )
    if (-not (Test-Path -LiteralPath $finalDocumentationSnapshotPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $finalDocumentationSnapshotPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $documentationTransactionPendingSha256) {
        throw "immutable documentation transaction snapshot changed before publication"
    }

    $finalCapture = Get-CaptureState
    if (-not $finalCapture.ok -or @($finalCapture.workers).Count -ne 3) {
        throw "exact three-worker capture recovery no longer passes"
    }
    if ($executionTapeRecoveryRequired) {
        $finalExecutionTape = Get-ExecutionTapeState
        if (-not $finalExecutionTape.ok) {
            throw "execution-tape recovery no longer passes: $(@($finalExecutionTape.reasons) -join ',')"
        }
    }
}
catch {
    $prePublicationFailure = $_.Exception.Message
}
if ($prePublicationFailure) {
    Note "publication boundary proof failed: $prePublicationFailure"
    Save-Report -ok $true -stage "merged_unpushed" -detail "publication boundary proof failed; commit $mergeCommit is local: $prePublicationFailure"
    exit 3
}
try { Assert-OneShotPushTask }
catch {
    Note "WeatherOneShotPush changed after its pre-mutation check: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task binding changed before publication; commit $mergeCommit is local"
    exit 3
}
Note "capture healthy after the roll; handing $mergeCommit to WeatherOneShotPush"
try { Start-ScheduledTask -TaskName WeatherOneShotPush -ErrorAction Stop }
catch {
    Note "could not start WeatherOneShotPush: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task start failed; commit $mergeCommit is local"
    exit 3
}
$pushed = $false
for ($i = 0; $i -lt 18; $i++) {
    Start-Sleep -Seconds 10
    if ((& git rev-parse origin/master).Trim() -eq $mergeCommit) { $pushed = $true; break }
}
if (-not $pushed) {
    Note "WeatherOneShotPush did not publish within 3 min. Merge is committed locally and capture is healthy."
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task did not acknowledge commit $mergeCommit"
    exit 3
}
$publicationAcknowledged = $true
try {
    Write-QuietMergeMarker -Phase "published"
}
catch {
    # The remote acknowledgement plus the attempt-local terminal report below
    # are authoritative. If that report also fails, the previous durable
    # documented_unpublished marker remains for Git-backed reconciliation.
    Note "WARNING: publication succeeded but the durable marker phase could not be advanced"
}
Note "pushed $mergeCommit via WeatherOneShotPush"
Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (via WeatherOneShotPush)"
exit 0
}
finally { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
