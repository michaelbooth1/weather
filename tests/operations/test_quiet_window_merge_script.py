import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_quiet_merge_can_bind_a_reviewed_exact_tip() -> None:
    script = _script_text()

    assert '[string]$ExpectedTip = ""' in script
    assert '[string]$ExpectedBaseline = ""' in script
    assert "$RepoRoot = (Split-Path -Parent" in script
    assert "$repo = (Resolve-Path -LiteralPath $RepoRoot" in script
    assert "ExpectedTip must be a full 40-character hexadecimal commit SHA" in script
    assert "$verdictRef = $ExpectedTip" in script
    assert "if ($resolvedBranchTip -ne $ExpectedTip)" in script
    assert "$mergeTarget = $resolvedBranchTip" in script
    assert "& git merge --no-commit --no-ff $mergeTarget" in script


def test_owner_protected_window_exception_is_dated_and_exactly_bound() -> None:
    script = _script_text()

    assert '[string]$OwnerApprovedException = ""' in script
    assert "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" in script
    assert "71f7e46690e822a498f80412c11d550bcee949d2" in script
    assert "9d54f94760855a5f91ac603f3f14b02ba06ae239" in script
    assert "3e2de64fb02e98e3016c71163bd7b297cf72488bbdfa593b38b237441f396389" in script
    assert 'ToString("yyyy-MM-dd") -cne "2026-08-23"' in script
    assert '$Branch -cne "origin/codex/live-readiness-closure-20260823"' in script
    assert "-not $Force" in script
    assert "git -C $repo merge-base --is-ancestor $authorizedRoot $ExpectedTip" in script
    assert "-not $ownerProtectedWindowException" in script
    assert '-OwnerApprovedException $OwnerApprovedException' in script
    assert 'Join-Path $repo "scripts\\ops\\workload_admission.ps1"' in script
    assert "owner-approved workload admission source changed" in script


def test_quiet_merge_serializes_before_git_mutation_and_rechecks_baseline() -> None:
    script = _script_text()

    lease = script.index("Enter-WeatherHeavyWorkloadLease")
    drift_commit = script.index('Note "committing $($dirtyTracked.Count)')
    merge = script.index("& git merge --no-commit --no-ff $mergeTarget")
    assert lease < drift_commit < merge
    assert "ExpectedBaseline must be a full 40-character hexadecimal commit SHA" in script
    assert "production baseline moved" in script
    assert "production working tree must have master checked out" in script
    assert "expected_baseline = $ExpectedBaseline" in script


def test_exact_tip_guard_precedes_any_automatic_commit_or_merge() -> None:
    script = _script_text()

    guard = script.index("if ($resolvedBranchTip -ne $ExpectedTip)")
    automatic_commit = script.index('Note "committing $($dirtyTracked.Count)')
    merge = script.index("& git merge --no-commit --no-ff $mergeTarget")

    assert guard < automatic_commit < merge


def test_quiet_merge_accepts_only_the_two_fleet_generated_config_paths() -> None:
    script = _script_text()

    match = re.search(r"\$autoRefreshed = @\((.*?)\)\n\$dirtyTracked", script, re.DOTALL)
    assert match is not None
    assert re.findall(r'"([^"]+)"', match.group(1)) == [
        "config/locations.json",
        "config/location_market_events.json",
    ]
    assert "fleet-generated drift set" in script
    assert 'git commit -m "ops: preserve fleet-generated drift' in script


def test_generated_drift_commit_survives_outer_task_log_redirection() -> None:
    script = _script_text()

    helper = script.index("function Invoke-GitAllowingNativeStderr")
    stage = script.index(
        "$gitAddExit = Invoke-GitAllowingNativeStderr { & git add -- $autoRefreshed }"
    )
    commit = script.index("$gitCommitExit = Invoke-GitAllowingNativeStderr")
    merge = script.index("& git merge --no-commit --no-ff $mergeTarget")

    assert '$ErrorActionPreference = "Continue"' in script[helper:stage]
    assert "$ErrorActionPreference = $previousErrorActionPreference" in script[helper:stage]
    assert "failed to stage fleet-generated drift (git exit $gitAddExit)" in script
    assert "failed to commit fleet-generated drift (git exit $gitCommitExit)" in script
    assert helper < stage < commit < merge


def test_quiet_merge_records_expected_and_resolved_tip() -> None:
    script = _script_text()

    assert "expected_tip = $ExpectedTip" in script
    assert "resolved_branch_tip = $resolvedBranchTip" in script


def test_recovery_proof_covers_exact_capture_fleet_and_loaded_source_identity() -> None:
    script = _script_text()

    assert "weather.operations.capture_recovery_check" in script
    assert "@($before.workers).Count -ne 3" in script
    assert "@($after.workers).Count -ne 3" in script
    assert "$beforeWorker in @($before.workers)" in script
    assert "$workerReadopted" in script
    assert "[int]$afterWorker.pid -ne [int]$beforeWorker.pid" in script
    assert "recorded_source_fingerprint" in script
    assert "readopted but heartbeat did not advance" in script
    assert "if (-not $workerReadopted) { continue }" in script
    assert "Get-CimInstance Win32_Process" not in script


def test_publish_uses_only_the_credential_bearing_scheduled_task() -> None:
    script = _script_text()

    assert "Start-ScheduledTask -TaskName WeatherOneShotPush" in script


def test_push_task_is_exactly_bound_before_any_git_mutation() -> None:
    script = _script_text()

    validation_call = script.index("Assert-OneShotPushTask", script.index("# ---- preconditions ----"))
    fetch = script.index("& git fetch origin --prune")
    git_add = script.index("& git add -- $autoRefreshed")

    assert validation_call < fetch < git_add
    assert '$pushTasks.Count -ne 1' in script
    assert "Export-ScheduledTask" in script
    assert "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05" in script
    assert "task XML changed from the reviewed trigger/settings/action contract" in script
    assert '[string]$pushTask.TaskPath -ceq "\\"' in script
    assert '[string]$pushTask.State -ceq "Ready"' in script
    assert "$pushTask.Settings.Enabled -eq $true" in script
    assert '[string]$pushTask.Principal.UserId -ieq "micha"' in script
    assert '[string]$pushTask.Principal.LogonType -ceq "Interactive"' in script
    assert '[string]$pushTask.Principal.RunLevel -ceq "Limited"' in script
    assert '$pushActions.Count -eq 1' in script
    assert '[string]$pushActions[0].Execute -ieq "cmd.exe"' in script
    assert "push-oneshot.log 2>&1" in script
    assert "$actualWorkingDirectory -ieq $expectedWorkingDirectory" in script


def test_push_task_is_revalidated_after_commit_without_retiring_recovery_marker() -> None:
    script = _script_text()

    commit = script.index('Write-QuietMergeMarker -Phase "merge_committed_unpublished"')
    second_gate = script.index("try { Assert-OneShotPushTask }", commit)
    start = script.index("Start-ScheduledTask -TaskName WeatherOneShotPush", second_gate)
    failure = script[second_gate:start]

    assert commit < second_gate < start
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in failure
    assert "Fail " not in failure


def test_publication_boundary_reproves_git_marker_documentation_and_capture() -> None:
    script = _script_text()

    boundary = script.index("$prePublicationFailure = $null")
    second_push_gate = script.index("try { Assert-OneShotPushTask }", boundary)
    proof = script[boundary:second_push_gate]

    assert "git rev-parse HEAD" in proof
    assert "git rev-parse master" in proof
    assert "git rev-parse origin/master" in proof
    assert 'phase -ne "documented_unpublished"' in proof
    assert "$documentedMarkerSha256" in proof
    assert "$finalMarkerShaBefore -ne $documentedMarkerSha256" in proof
    assert "$finalMarkerShaAfter -ne $documentedMarkerSha256" in proof
    assert "[IO.File]::ReadAllText($activeMarkerPath, [Text.Encoding]::UTF8)" in proof
    assert "documentation_transaction_pending_sha256" in proof
    assert "Get-FileHash -LiteralPath $finalDocumentationSnapshotPath" in proof
    assert "$finalCapture = Get-CaptureState" in proof
    assert "$finalExecutionTape = Get-ExecutionTapeState" in proof
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in proof


def test_documentation_transaction_is_bound_before_publication() -> None:
    script = _script_text()

    begin = script.index('"-m", "weather.operations.documentation_transaction"')
    push = script.index("Start-ScheduledTask -TaskName WeatherOneShotPush")
    assert begin < push
    assert '"--integration-tip", $mergeCommit' in script
    assert '"--branch", $Branch' in script
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script
    assert "documentation_transaction_recorded = $documentationTransactionRecorded" in script
    assert "documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256" in script
    assert "documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath" in script
    assert "execution_tape_readoption_expected = $executionTapeReadoptionExpected" in script
    assert "documentation_transaction_pending.json" in script
    assert "pending-$pendingSha256.json" in script
    assert script.index("$documentationTransactionRecorded = $true") < push
    assert "merge_commit = $mergeCommit" in script
    assert "& git push" not in script.lower()
    assert "git rev-parse origin/master" in script


def test_documentation_begin_or_marker_failure_preserves_the_bound_local_merge() -> None:
    script = _script_text()

    begin_failure = script.index("if ($documentationExit -ne 0)")
    documentation_recorded = script.index('Note "documentation transaction recorded')
    marker_failure = script.index(
        'Note "documentation succeeded but its durable merge marker could not be updated'
    )
    publication = script.index("Start-ScheduledTask -TaskName WeatherOneShotPush")

    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script[
        begin_failure:documentation_recorded
    ]
    assert "Invoke-RollbackAndProve" not in script[begin_failure:documentation_recorded]
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script[
        marker_failure:publication
    ]
    assert "Invoke-RollbackAndProve" not in script[marker_failure:publication]


def test_failed_merge_proves_rollback_readoption_before_reporting_rolled_back() -> None:
    script = _script_text()

    reset = script.index("& git reset --hard $preMerge")
    rollback_wait = script.index("$rollbackDeadline = (Get-Date).AddSeconds")
    rollback_proof = script.index(
        'Note "every affected producer re-adopted the rollback and satisfies its exact recovery contract"'
    )
    rolled_back = script.index("Save-Report -ok $RecoveredOk -stage $RecoveredStage")

    assert "[ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200" in script
    assert '[ValidateSet("rolled_back", "dry_run")][string]$RecoveredStage = "rolled_back"' in script
    assert "[bool]$RecoveredOk = $false" in script
    assert 'Save-Report -ok $false -stage "rollback_recovery_failed"' in script
    assert reset < rollback_wait < rollback_proof < rolled_back


def test_merge_stays_uncommitted_until_all_required_recovery_proofs_pass() -> None:
    script = _script_text()

    merge = script.index("& git merge --no-commit --no-ff $mergeTarget")
    core_proof = script.index("$captureRecoveryProved = $true")
    tape_proof = script.index(
        "if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }"
    )
    commit = script.index('& git commit -m "Merge $Branch into master"')

    assert "MERGE_HEAD is the durable crash marker" in script
    assert merge < core_proof < tape_proof < commit
    assert "explicit merge commit did not bind the exact pre-merge and reviewed-tip parents" in script


def test_execution_tape_is_gated_only_when_active_and_its_closure_rolls() -> None:
    script = _script_text()

    assert "$executionTapeReadoptionExpected -and $executionTapeActive" in script
    assert "$executionTapeRolledButInactiveSkipped" in script
    assert "leaving it disabled and skipping recovery proof" in script
    assert "weather.operations.execution_tape_supervisor status" in script
    assert '"runtime_identity_stale"' in script
    assert "execution_tape closure rolled but loaded-source fingerprint did not change" in script
    assert "Enable-ScheduledTask" not in script


def test_rollback_restores_synchronized_baseline_and_preserves_generated_bytes() -> None:
    script = _script_text()

    assert "baseline_commit = $baselineCommit" in script
    assert "pre_merge_commit = $preMerge" in script
    assert "rollback_content_sha256 = $rollbackContentSha256" in script
    assert "& git reset --mixed $baselineCommit" in script
    assert "generated config preserved as allowlisted drift" in script
    assert "successor-resumable baseline" in script
    assert "if ($dirtyTracked.Count -gt 0)" in script
    assert "if ($dirtyTracked.Count -gt 0 -and -not $DryRun)" not in script
    assert "$dryRestore = Restore-PreparedBaseline" in script
    assert '-RecoveredStage "dry_run"' in script
    assert "every affected producer re-adopted the rollback" in script


def test_preparation_is_journaled_before_config_mutation_and_prepared_binds_tape_identity() -> None:
    script = _script_text()

    first_preparing = script.index('Write-QuietMergeMarker -Phase "preparing"')
    git_add = script.index("& git add -- $autoRefreshed")
    source_before = script.index(
        "$executionTapeSourceBefore = [string]$executionBefore.recorded_source_fingerprint"
    )
    prepared = script.index('Write-QuietMergeMarker -Phase "prepared"')
    merge = script.index("& git merge --no-commit --no-ff $mergeTarget")

    assert first_preparing < git_add < source_before < prepared < merge
    assert "both fleet-generated config files must exist before merge preparation" in script


def test_attempt_report_is_exclusive_atomic_and_written_before_mutable_slots() -> None:
    script = _script_text()

    assert '[string]$AttemptReportPath = ""' in script
    assert "AttemptReportPath must be an absolute path" in script
    assert "AttemptReportPath is immutable and already exists" in script
    exclusive_move = script.index("[IO.File]::Move($attemptTemp, $AttemptReportPath)")
    latest = script.index("$json | Set-Content -Path $reportPath")
    assert exclusive_move < latest
    assert 'schema = "quiet_window_merge_report_v0.2"' in script
    assert "publication_acknowledged = $publicationAcknowledged" in script
    assert "$attemptReportPersisted = $false" in script
    assert "$attemptReportExpectedSha256" in script
    assert "attempt-local immutable quiet-window terminal report could not be persisted" in script
    assert "attempt-local immutable report changed before active-marker retirement" in script
    assert "active quiet-merge marker still exists after terminal retirement" in script
    assert "Remove-Item -LiteralPath $activeMarkerPath -Force -ErrorAction Stop" in script
    retirement = re.search(r"\$markerCanRetire = \((.*?)\n    \)", script, re.DOTALL)
    assert retirement is not None
    assert '$stage -eq "merged_unpushed"' not in retirement.group(1)
    assert '$stage -eq "rollback_recovery_failed"' not in retirement.group(1)


def test_quiet_merge_can_bind_its_own_frozen_bytes_and_serializes_roll_verdict() -> None:
    script = _script_text()

    assert '[string]$ExpectedSelfSha256 = ""' in script
    assert "Get-FileHash -LiteralPath $PSCommandPath" in script
    lease = script.index("$workloadLease = Enter-WeatherHeavyWorkloadLease")
    verdict = script.index("& $verdictScript -Branch $verdictRef")
    assert lease < verdict


def test_legacy_callers_bind_observed_synchronized_baseline_before_marker() -> None:
    script = _script_text()

    baseline = script.index("$baselineCommit = $head.ToLowerInvariant()")
    binding = script.index("$ExpectedBaseline = $baselineCommit", baseline)
    first_marker = script.index('Write-QuietMergeMarker -Phase "preparing"')
    assert baseline < binding < first_marker


def test_legacy_callers_freeze_observed_tip_before_merge_and_marker() -> None:
    script = _script_text()

    binding = script.index("$ExpectedTip = ([string]$preVerdictBranchTip[0])")
    assert "& git -C $repo rev-parse --verify $preVerdictCommitRef" in script
    verdict = script.index("& $verdictScript -Branch $verdictRef")
    fetch = script.index("& git fetch origin --prune")
    equality = script.index("$resolvedBranchTip -ne $ExpectedTip", fetch)
    immutable_target = script.index("$mergeTarget = $resolvedBranchTip", equality)
    first_marker = script.index('Write-QuietMergeMarker -Phase "preparing"')
    assert binding < verdict < fetch < equality < immutable_target < first_marker


def test_attempt_retry_does_not_poison_report_path_when_crash_marker_exists() -> None:
    script = _script_text()

    marker_guard = script.index("if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf)")
    merge_head_guard = script.index("$existingMergeHeadPath =", marker_guard)
    guard = script[marker_guard:merge_head_guard]

    assert "if ($AttemptReportPath)" in guard
    assert "throw $priorMarkerReason" in guard
    assert guard.index("throw $priorMarkerReason") < guard.index(
        'Save-Report -ok $false -stage "abort"'
    )


def test_fetch_and_every_merge_mutation_tolerate_native_stderr_but_check_exit() -> None:
    script = _script_text()

    assert "$gitFetchExit = Invoke-GitAllowingNativeStderr" in script
    assert "if ($gitFetchExit -ne 0)" in script
    assert "$mergeExit = Invoke-GitAllowingNativeStderr" in script
    assert "$mergeCommitExit = Invoke-GitAllowingNativeStderr" in script
    assert "$dryRunExitCode = if ($dryRunOk) { 0 } else { 2 }" in script
    assert "-RecoveredExitCode $dryRunExitCode" in script
    dry_merge = script.index("$dryMergeExit = Invoke-GitAllowingNativeStderr")
    dry_abort = script.index("$dryAbortExit = Invoke-GitAllowingNativeStderr", dry_merge)
    dry_proof = script.index("Invoke-RollbackAndProve", dry_abort)
    assert dry_merge < dry_abort < dry_proof
