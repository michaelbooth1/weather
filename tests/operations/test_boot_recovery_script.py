from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "boot_recovery.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_boot_recovery_uses_git_resolved_merge_head_and_exact_orig_head_fallback() -> None:
    script = _script_text()

    assert "git rev-parse --git-path MERGE_HEAD" in script
    assert "git rev-parse --verify ORIG_HEAD" in script
    assert "git reset --hard $origHead" in script
    assert 'reset --hard HEAD instead' not in script
    assert "$mergeHeadStillExists" in script


def test_boot_recovery_can_be_hash_frozen_for_first_landing() -> None:
    script = _script_text()

    assert '[string]$ExpectedSelfSha256 = ""' in script
    assert "Get-FileHash -LiteralPath $PSCommandPath" in script
    assert "Boot-recovery script changed after its task action was frozen" in script


def test_boot_recovery_reconciles_the_durable_quiet_merge_marker() -> None:
    script = _script_text()

    assert '"quiet_window_merge_in_progress.json"' in script
    assert '"quiet_window_merge_in_progress_v0.1"' in script
    assert "$marker.baseline_commit" in script
    assert "$marker.pre_merge_commit" in script
    assert "$marker.capture_recovery_proved" in script
    assert "$marker.execution_tape_recovery_required" in script
    assert "$marker.execution_tape_recovery_proved" in script


def test_unverified_merge_restores_remote_baseline_and_generated_config_bytes() -> None:
    script = _script_text()

    guarded_recovery = script.index(
        'FOUND AN UNVERIFIED GUARDED MERGE (phase=$mergeMarkerPhase) - removing target tree'
    )
    abort = script.index("& git merge --abort | Out-Null", guarded_recovery)
    reset_pre_merge = script.index("& git reset --hard $preMerge | Out-Null", guarded_recovery)
    reset_baseline = script.index("& git reset --mixed $baseline | Out-Null", abort)
    verify_hash = script.index("Get-FileHash -LiteralPath $absolute -Algorithm SHA256")
    clear_marker = script.index(
        "Remove-Item -LiteralPath $mergeMarkerPath -Force -ErrorAction SilentlyContinue"
    )

    assert abort < reset_baseline
    assert reset_pre_merge < reset_baseline < verify_hash < clear_marker
    assert "$unexpectedDirty.Count -eq 0" in script
    assert "$hashMismatch.Count -eq 0" in script
    assert "preserving marker and refusing baseline reset" in script


def test_recovery_proved_commit_is_preserved_for_explicit_reconciliation() -> None:
    script = _script_text()

    assert "$committedRecoveryProved" in script
    assert '"merge_committed_unpublished"' in script
    assert '"documented_unpublished"' in script
    assert '"published"' in script
    assert "$expectedTip -match '^[0-9a-f]{40}$'" in script
    assert "$resolvedTip -eq $expectedTip" in script
    assert "git merge-base --is-ancestor $baseline $preMerge" in script
    assert "git rev-list --parents -n 1 $preMerge" in script
    assert "$preMergeParentParts.Count -eq 2" in script
    assert "git rev-list --parents -n 1 $markerMergeCommit" in script
    assert "$mergeParentParts.Count -eq 3" in script
    assert "$mergeParentParts[1] -eq $preMerge" in script
    assert "$mergeParentParts[2] -eq $resolvedTip" in script
    assert "$phaseEvidenceValid" in script
    assert "$documentationIdentityValid" in script
    assert "documentation_transaction_pending_sha256" in script
    assert "documentation_transaction_snapshot_path" in script
    assert "$documentationSnapshotHashValid" in script
    assert 'schema_version -eq "documentation_transaction_pending_v0.1"' in script
    assert "$matchingDocumentationEntries.Count -eq 1" in script
    documentation_proof = script[
        script.index("$documentationPendingSha256 =") : script.index("$phaseEvidenceValid")
    ]
    assert "documentation_transaction_pending.json" not in documentation_proof
    assert "$fullHead -eq $markerMergeCommit" in script
    assert "$mergeReconciliationRequired = $true" in script
    assert "explicit reconciliation required" in script
    assert "Start-ScheduledTask" not in script
    assert "git push" not in script


def test_remote_movement_never_leaves_unverified_target_code_on_disk() -> None:
    script = _script_text()

    remove_target = script.index(
        'FOUND AN UNVERIFIED GUARDED MERGE (phase=$mergeMarkerPhase) - removing target tree'
    )
    abort = script.index("& git merge --abort | Out-Null", remove_target)
    remote_guard = script.index("elseif ($originMaster -ne $baseline)", abort)

    assert remove_target < abort < remote_guard
    assert "unverified target tree removed to $preMerge" in script
    assert "preserving marker and refusing baseline reset" in script


def test_boot_event_exposes_recovery_failure_and_reconciliation_states() -> None:
    script = _script_text()

    assert "interrupted_merge_recovery_failed = $mergeRecoveryFailed" in script
    assert "merge_reconciliation_required = $mergeReconciliationRequired" in script
    assert "merge_marker_phase = $mergeMarkerPhase" in script
    assert "merge_rollback_target = $mergeRollbackTarget" in script
    assert (
        "if ($mergeRecoveryFailed -or $mergeReconciliationRequired -or "
        "$gitLockRecoveryRequired) { exit 3 }"
    ) in script


def test_preparing_phase_recovers_an_exact_config_child_without_auxiliary_proof() -> None:
    script = _script_text()

    assert '$preparingPhase = $mergeMarkerPhase -eq "preparing"' in script
    assert "git rev-list --parents -n 1 $fullHead" in script
    assert "$preparingParentParts.Count -eq 2" in script
    assert "$preparingParentParts[1] -eq $baseline" in script
    assert "$markerExecutionRequired = $marker.execution_tape_recovery_required -eq $true" in script
    assert '[string]$marker.phase -ne "preparing"' in script


def test_rolled_back_marker_waits_for_canonical_exact_recovery_before_retirement() -> None:
    script = _script_text()

    proof = script.index("function Get-ExactRecoveryProof")
    retry = script.index("$markerProofAttemptLimit = if ($NoWait) { 1 } else { 21 }")
    remove = script.index(
        "Remove-Item -LiteralPath $mergeMarkerPath -Force -ErrorAction SilentlyContinue"
    )

    assert "weather.operations.capture_recovery_check" in script[proof:remove]
    assert "@($captureProof.workers).Count -eq 3" in script[proof:remove]
    assert "weather.operations.execution_tape_supervisor status" in script[proof:remove]
    assert '[string]$executionStatus.market -eq "all"' in script[proof:remove]
    assert '[string]$executionStatus.runner -eq "managed_execution_tape"' in script[proof:remove]
    assert proof < retry < remove
    assert "$currentMarkerSha256 -eq $mergeMarkerSha256" in script


def test_marker_identity_must_bind_master_and_exact_repository_before_mutation() -> None:
    script = _script_text()

    identity = script.index("$markerIdentityValid = (")
    refusal = script.index("refusing marker-driven Git mutation")
    guarded_mutation = script.index("FOUND AN UNVERIFIED GUARDED MERGE", refusal)

    assert "$onMaster -and" in script[identity:refusal]
    assert "$markerRepoValid -and" in script[identity:refusal]
    assert "$resolvedTip -eq $expectedTip" in script[identity:refusal]
    assert "$marker.expected_baseline" in script[identity:refusal]
    assert identity < refusal < guarded_mutation
    assert "$untrustedMergeHeadRecoveryRequired = $mergeHeadExists -and -not $markerReadable" in script


def test_corrupt_or_mismatched_marker_cannot_leave_merge_head_target_staged() -> None:
    script = _script_text()

    identity_refusal = script.index("refusing marker-driven Git mutation")
    untrusted_route = script.index("$untrustedMergeHeadRecoveryRequired = $true", identity_refusal)
    abort_block = script.index("if ($untrustedMergeHeadRecoveryRequired)", untrusted_route)
    abort = script.index("& git merge --abort | Out-Null", abort_block)

    assert identity_refusal < untrusted_route < abort_block < abort
    assert '"UNTRUSTED-MARKER"' in script[abort_block:abort]
    assert "Marker-derived refs are never trusted" in script[abort_block:abort]


def test_unmarked_merge_is_not_healed_until_exact_current_tree_recovery_passes() -> None:
    script = _script_text()

    unmarked = script.index("if ($untrustedMergeHeadRecoveryRequired)")
    pending = script.index("$unmarkedRecoveryPending = $true", unmarked)
    unmarked_git_block_end = script.index("$head = (& git rev-parse --short HEAD", pending)
    proof = script.index("if ($unmarkedRecoveryPending)", pending)
    healed = script.index("$mergeHealed = $true", proof)

    assert "$mergeHealed = $true" not in script[unmarked:unmarked_git_block_end]
    assert "Test-BootExecutionTapeActive" in script[proof:healed]
    assert "Get-ExactRecoveryProof" in script[proof:healed]
    assert "-RequireExecutionTape $unmarkedExecutionTapeRequired" in script[proof:healed]
    assert pending < proof < healed


def test_boot_recovery_reports_exact_stale_git_locks_without_deleting_them() -> None:
    script = _script_text()

    for relative_path in (
        '"index.lock"',
        '"HEAD.lock"',
        '"ORIG_HEAD.lock"',
        '"MERGE_HEAD.lock"',
        '"AUTO_MERGE.lock"',
        '"refs\\auto-merge.lock"',
        '"refs\\heads\\master.lock"',
        '"refs\\remotes\\origin\\master.lock"',
    ):
        assert relative_path in script
    assert "predates_boot" in script
    assert "git_lock_recovery_required = $gitLockRecoveryRequired" in script
    assert "preboot_git_locks" in script
    lock_detection = script[
        script.index("$knownGitLockPaths = @(") : script.index("$mergeHeadPath =")
    ]
    assert "Remove-Item" not in lock_detection
    assert (
        "if ($mergeRecoveryFailed -or $mergeReconciliationRequired -or "
        "$gitLockRecoveryRequired) { exit 3 }"
    ) in script


def test_boot_event_persistence_failure_is_never_reported_as_success() -> None:
    script = _script_text()

    persist = script.index("$bootRecordPersisted = $false")
    append = script.index("Add-Content -Path $logPath", persist)
    refusal = script.index("if (-not $bootRecordPersisted) { exit 4 }", append)

    assert persist < append < refusal
    assert "$bootRecordPersisted = $true" in script[append:refusal]
    assert "BOOT EVENT PERSISTENCE FAILED" in script[append:refusal]
