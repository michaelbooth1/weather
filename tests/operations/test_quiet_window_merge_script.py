import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
SCHEDULER_RPC_SCRIPT = (
    REPO_ROOT / "scripts" / "ops" / "production_baseline_scheduler_rpc.ps1"
)

LOCAL_PRODUCTION_BASELINE = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
PUBLISHED_PRODUCTION_TARGET = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
REVIEWED_REPAIR_PARENT = "a24cf0f41bf0b321c5c813820594c56198a58d1a"
CANONICAL_ORIGIN_URL = "https://github.com/michaelbooth1/weather.git"
RECONCILIATION_CONFIG_PATHS = {
    "config/location_market_events.json",
    "config/locations.json",
}
RECONCILIATION_DEPENDENCY_SHA256 = {
    "workload_admission.ps1": (
        "4117eb901d292952473c57425434593bed414fa2ed2fecee301fe56e8f893306"
    ),
    "roll_verdict.ps1": (
        "3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881"
    ),
    "boot_recovery.ps1": (
        "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
    ),
    "capture_recovery_check.py": (
        "814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895"
    ),
    "documentation_transaction.py": (
        "057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9"
    ),
    "execution_tape_supervisor.py": (
        "1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f"
    ),
}
LOCAL_BASELINE_WORKLOAD_ADMISSION_SHA256 = (
    "cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105"
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _scheduler_rpc_text() -> str:
    return SCHEDULER_RPC_SCRIPT.read_text(encoding="utf-8")


def _param_block(script: str) -> str:
    start = script.index("param(")
    end = script.index("\n)", start)
    return script[start:end]


def _braced_block(script: str, marker: str, start: int = 0) -> str:
    """Return a PowerShell block while ignoring braces in strings/comments."""

    marker_at = script.index(marker, start)
    block_start = script.index("{", marker_at + len(marker))
    depth = 0
    quote: str | None = None
    comment = False
    index = block_start
    while index < len(script):
        char = script[index]
        if comment:
            if char in "\r\n":
                comment = False
            index += 1
            continue
        if quote == "'":
            if char == "'":
                if index + 1 < len(script) and script[index + 1] == "'":
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if quote == '"':
            if char == "`":
                index += 2
                continue
            if char == '"':
                quote = None
            index += 1
            continue
        if char == "#":
            comment = True
        elif char in "'\"":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script[block_start : index + 1]
        index += 1
    raise AssertionError(f"unterminated PowerShell block after {marker!r}")


def _function_blocks(script: str) -> dict[str, str]:
    return {
        match.group(1): _braced_block(script, match.group(0))
        for match in re.finditer(r"(?m)^function\s+([A-Za-z][A-Za-z0-9-]*)\s*\{", script)
    }


def _function_calls(script: str, function_name: str) -> list[int]:
    calls: list[int] = []
    for match in re.finditer(rf"\b{re.escape(function_name)}\b", script):
        line_start = script.rfind("\n", 0, match.start()) + 1
        prefix = script[line_start : match.start()]
        if re.search(r"\bfunction\s*$", prefix):
            continue
        calls.append(match.start())
    return calls


def _exact_literal_binding(script: str, parameter: str, literal: str) -> bool:
    direct = re.search(
        rf"\${re.escape(parameter)}\s+-c?ne\s+['\"]{literal}['\"]", script
    )
    if direct:
        return True
    constant_names = re.findall(
        rf"\$([A-Za-z][A-Za-z0-9]*)\s*=\s*['\"]{literal}['\"]", script
    )
    return any(
        re.search(
            rf"\${re.escape(parameter)}\s+-c?ne\s+\${re.escape(constant_name)}\b",
            script,
        )
        for constant_name in constant_names
    )


def _reconciliation_execution_block(script: str) -> str:
    marker = "if ($productionBaselineReconciliationMode)"
    search_from = 0
    while True:
        try:
            marker_at = script.index(marker, search_from)
        except ValueError as exc:
            raise AssertionError("special reconciliation execution block is absent") from exc
        block = _braced_block(script, marker, search_from)
        if (
            "Invoke-ReconciliationRollVerdict" in block
            and "New-ReconciliationRawSnapshot" in block
        ):
            return block
        search_from = marker_at + len(marker)


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
    scheduler_rpc = _scheduler_rpc_text()

    validation_call = script.index("Assert-OneShotPushTask", script.index("# ---- preconditions ----"))
    fetch = script.index("& git fetch origin --prune")
    git_add = script.index("& git add -- $autoRefreshed")

    assert validation_call < fetch < git_add
    assert '$pushTasks.Count -ne 1' in script
    assert "Export-ScheduledTask" in script
    assert "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05" in script
    assert "task XML changed from the reviewed trigger/settings/action contract" in script
    assert '[string]$pushTask.TaskPath -ceq "\\"' in script
    assert '[string[]]$AllowedStates = @("Ready")' in script
    assert "$AllowedStates -ccontains [string]$pushTask.State" in script
    assert "$pushTask.Settings.Enabled -eq $true" in script
    assert '[string]$pushTask.Principal.UserId -ieq "micha"' in script
    assert '[string]$pushTask.Principal.LogonType -ceq "Interactive"' in script
    assert '[string]$pushTask.Principal.RunLevel -ceq "Limited"' in script
    assert '$pushActions.Count -eq 1' in script
    assert '[string]$pushActions[0].Execute -ieq "cmd.exe"' in script
    assert "push-oneshot.log 2>&1" in script
    assert "$actualWorkingDirectory -ieq $expectedWorkingDirectory" in script

    # The ordinary synchronized path retains its established direct attestation,
    # while the incident-bound path crosses the bounded helper seam and then
    # independently validates the complete structured snapshot in the parent.
    task_guard = _braced_block(script, "function Assert-OneShotPushTask")
    ordinary_guard = _braced_block(
        task_guard, "if (-not $productionBaselineReconciliationMode)"
    )
    assert "Get-ScheduledTask" in ordinary_guard
    assert "Export-ScheduledTask" in ordinary_guard
    assert "Invoke-ReconciliationSchedulerRpc" not in ordinary_guard
    assert "Get-ReconciliationPushSnapshot" in task_guard[
        task_guard.index(ordinary_guard) + len(ordinary_guard) :
    ]

    helper_exact_task = _braced_block(scheduler_rpc, "function Get-ExactTask")
    helper_canonical_xml = _braced_block(
        scheduler_rpc, "function Get-CanonicalPushTaskXmlEvidence"
    )
    helper_static_guard = _braced_block(
        scheduler_rpc, "function Get-PushTaskStaticEvidence"
    )
    parent_snapshot_guard = _braced_block(
        script, "function Assert-ReconciliationPushSnapshot"
    )
    assert "$rows.Count -ne 1" in helper_exact_task
    canonical_xml_flat = re.sub(r"\s+", " ", helper_canonical_xml)
    assert "Export-ScheduledTask" in canonical_xml_flat
    assert "-TaskName $script:PushTaskName" in canonical_xml_flat
    assert "-TaskPath $script:FixedTaskPath" in canonical_xml_flat
    assert "Export-ScheduledTask -InputObject" not in helper_canonical_xml
    assert '$script:ReviewedPushTaskXmlSha256' in helper_canonical_xml
    for exact_evidence in (
        '$script:ExpectedPushSid',
        '$triggers.Count -ne 0',
        '[string]$Task.Settings.MultipleInstances -cne "IgnoreNew"',
        '[string]$Task.Settings.ExecutionTimeLimit -cne "PT15M"',
        '$Task.Settings.StartWhenAvailable -ne $false',
        '$actions.Count -ne 1',
    ):
        assert exact_evidence in helper_static_guard
    for independently_reproved in (
        "match_count",
        "task_xml_base64",
        "task_xml_sha256",
        "principal_user_id",
        "principal_logon_type",
        "principal_run_level",
        "action_execute",
        "action_arguments",
        "action_working_directory",
        "trigger_count",
        "multiple_instances",
        "execution_time_limit",
        "start_when_available",
        "last_run_time",
        "last_task_result",
    ):
        assert f'"{independently_reproved}"' in parent_snapshot_guard
    assert "failed independent parent validation" in parent_snapshot_guard


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
    special = _reconciliation_execution_block(script)

    # In the one-incident path, every documentation ambiguity after M is a
    # terminal evidence-preserving outcome. It must not enter either rollback
    # helper or reach the bounded publication RPC.
    begin_failure = special.index("if ($documentationExit -ne 0)")
    documentation_identity = special.index(
        "$documentationPayload = (($documentationOutput -join", begin_failure
    )
    begin_failure_path = special[begin_failure:documentation_identity]
    assert 'Stage "reconciliation_merged_unpublished"' in begin_failure_path
    assert "M preserved" in begin_failure_path
    assert "Invoke-ReconciliationRollbackAndProve" not in begin_failure_path

    marker_failure = special.index(
        'catch {\n            Stop-Reconciliation `', documentation_identity
    )
    publication = special.index("Invoke-ReconciliationOneShotPushTask", marker_failure)
    marker_failure_path = special[marker_failure:publication]
    assert "documentation succeeded without exact boot-valid marker identity" in (
        marker_failure_path
    )
    assert 'Stage "reconciliation_merged_unpublished"' in marker_failure_path
    assert "Invoke-ReconciliationRollbackAndProve" not in marker_failure_path

    # The ordinary synchronized path keeps its historical resumable behavior.
    special_end = script.index(special) + len(special)
    ordinary_begin = script.index("if ($documentationExit -ne 0)", special_end)
    ordinary_recorded = script.index(
        'Note "documentation transaction recorded', ordinary_begin
    )
    ordinary_marker_failure = script.index(
        'Note "documentation succeeded but its durable merge marker could not be updated',
        ordinary_recorded,
    )
    ordinary_publication = script.index(
        "Start-ScheduledTask -TaskName WeatherOneShotPush", ordinary_marker_failure
    )
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script[
        ordinary_begin:ordinary_recorded
    ]
    assert "Invoke-RollbackAndProve" not in script[
        ordinary_begin:ordinary_recorded
    ]
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script[
        ordinary_marker_failure:ordinary_publication
    ]


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
    core_proof = script.index("$captureRecoveryProved = $true", merge)
    tape_proof = script.index(
        "if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }",
        core_proof,
    )
    commit = script.index('& git commit -m "Merge $Branch into master"', tape_proof)

    assert "MERGE_HEAD is the durable crash marker" in script
    assert merge < core_proof < tape_proof < commit
    assert "explicit merge commit did not bind the exact pre-merge and reviewed-tip parents" in script

    special = _reconciliation_execution_block(script)
    special_merge = special.index(
        "git -C $repo merge --no-commit --no-ff $ExpectedSourceTip"
    )
    staged_recovery = special.index(
        "$reconciliationStagedSafetyCaptureRecoveryProved = $true", special_merge
    )
    recovered_marker = special.index(
        '-Phase "reconciliation_capture_recovered_uncommitted"', staged_recovery
    )
    commit_boundary = special.index(
        "$reconciliationCommitInvocationStarted = $true", recovered_marker
    )
    assert special_merge < staged_recovery < recovered_marker < commit_boundary


def test_execution_tape_is_gated_only_when_active_and_its_closure_rolls() -> None:
    script = _script_text()
    scheduler_rpc = _scheduler_rpc_text()

    assert "$executionTapeReadoptionExpected -and $executionTapeActive" in script
    assert "$executionTapeRolledButInactiveSkipped" in script
    assert "leaving it disabled and skipping recovery proof" in script
    assert "weather.operations.execution_tape_supervisor status" in script
    assert '"runtime_identity_stale"' in script
    assert "execution_tape closure rolled but loaded-source fingerprint did not change" in script
    assert "Enable-ScheduledTask" not in script

    tape_guard = _braced_block(script, "function Test-ExecutionTapeActive")
    ordinary_guard = _braced_block(
        tape_guard, "if (-not $productionBaselineReconciliationMode)"
    )
    assert "Get-ScheduledTask" in ordinary_guard
    assert "Invoke-ReconciliationSchedulerRpc" not in ordinary_guard
    reconciliation_guard = tape_guard[
        tape_guard.index(ordinary_guard) + len(ordinary_guard) :
    ]
    assert '-Operation "ReadExecutionTapeTask"' in reconciliation_guard
    assert "Get-ScheduledTask" not in reconciliation_guard
    assert "task evidence failed independent validation" in reconciliation_guard
    assert '"ReadExecutionTapeTask"' in scheduler_rpc


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
    report_writer = _braced_block(script, "function Save-Report")
    retirement_start = report_writer.index(
        "$markerCanRetire = if ($productionBaselineReconciliationMode)"
    )
    retirement_end = report_writer.index(
        "if ($activeMarkerOwned -and $markerCanRetire)", retirement_start
    )
    retirement = report_writer[retirement_start:retirement_end]
    assert '($stage -eq "pushed" -and $publicationAcknowledged)' in retirement
    assert '$stage -eq "rolled_back"' in retirement
    for nonterminal_stage in (
        "merged_unpushed",
        "reconciliation_merged_unpublished",
        "publication_state_uncertain",
        "rollback_recovery_failed",
        "commit_ambiguous",
    ):
        assert f'$stage -eq "{nonterminal_stage}"' not in retirement

    special_retirement_guard = report_writer[
        retirement_end : report_writer.index(
            "if ($AttemptReportPath -and", retirement_end
        )
    ]
    for required_proof in (
        "$publicationAcknowledged",
        "$publicationInvoked",
        "$oneShotPushTerminalProved",
        "$oneShotPushRunObserved",
    ):
        assert required_proof in special_retirement_guard


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


def test_production_baseline_reconciliation_is_a_narrow_exact_mode() -> None:
    script = _script_text()
    params = _param_block(script)

    assert "[switch]$ProductionBaselineReconciliation" in params
    assert '[string]$ExpectedLocalBaseline = ""' in params
    assert '[string]$ExpectedPublishedTarget = ""' in params
    assert '[string]$ExpectedSourceTip = ""' in params
    assert '[string]$ExpectedSourceTree = ""' in params
    assert '[string]$ExpectedSelfSha256 = ""' in params
    assert "production_baseline_reconciliation_v0.1" in script
    assert _exact_literal_binding(
        script, "ExpectedLocalBaseline", LOCAL_PRODUCTION_BASELINE
    )
    assert _exact_literal_binding(
        script, "ExpectedPublishedTarget", PUBLISHED_PRODUCTION_TARGET
    )

    for parameter in ("ExpectedSourceTip", "ExpectedSourceTree"):
        assert re.search(
            rf"\${parameter}\s+-notmatch\s+['\"]\^\[0-9a-f\]\{{40\}}\$['\"]",
            script,
        )
    assert re.search(
        r"\$ExpectedSelfSha256\s+-notmatch\s+['\"]\^\[0-9a-f\]\{64\}\$['\"]",
        script,
    )

    # The reviewed safety tip S is the exact merge/roll/boot-consumed tip. T
    # remains only the published target and deliberately rejected boot guard.
    assert re.search(
        r"\$Branch\s+-cne\s+\$ExpectedSourceTip", script
    )
    assert re.search(
        r"\$ExpectedTip\s+-cne\s+\$ExpectedSourceTip", script
    )
    assert re.search(
        r"\$ExpectedBaseline\s+-cne\s+\$reconciliationLocalBaseline", script
    )
    assert re.search(
        r"\$resolvedBranchTip\s*=\s*\$ExpectedSourceTip",
        script,
    )
    assert re.search(
        r"\$baselineCommit\s*=\s*\$(?:ExpectedLocalBaseline|"
        r"reconciliationLocalBaseline)",
        script,
    )

    special = _reconciliation_execution_block(script)
    assert re.search(r"if\s*\([^)]*\$Force", special)
    assert re.search(r"\$Force.{0,400}Stop-Reconciliation", special, re.DOTALL)
    compact = re.sub(r"\s+", " ", script)
    entry_gate = compact.index(
        'Assert-ReconciliationQuietWindowOpen -Stage "entry"'
    )
    assert entry_gate < compact.index(
        "$rollEvidence = Invoke-ReconciliationRollVerdict"
    )


def test_reconciliation_roll_verdict_is_explicit_and_fails_closed() -> None:
    script = _script_text()
    compact = re.sub(r"\s+", " ", script)
    special_roll = _braced_block(script, "function Invoke-ReconciliationRollVerdict")
    owned_process = _braced_block(script, "function Invoke-ReconciliationOwnedProcess")
    compact_roll = re.sub(r"\s+", " ", special_roll)
    assert "Invoke-ReconciliationOwnedProcess" in special_roll
    assert '"-File", $verdictScript' in compact_roll
    assert '"-Base", $reconciliationLocalBaseline' in compact_roll
    assert '"-Branch", $ExpectedSourceTip' in compact_roll
    assert '"-JsonOut", $verdictJsonPath' in compact_roll
    assert '-Label "canonical roll verdict L-to-S"' in compact_roll
    assert "& $verdictScript" not in special_roll
    assert "New-WeatherKillOnCloseJob" in owned_process
    assert "Start-WeatherProcessInJob" in owned_process
    assert "$remainingBeforeLaunch" in owned_process
    assert "$remainingAtWait" in owned_process
    assert "$process.WaitForExit($waitMilliseconds)" in owned_process
    assert "[datetimeoffset]$DeadlineUtc" in owned_process
    assert "$cleanupDeadlineUtc" in owned_process
    assert "$remainingCleanupMilliseconds" in owned_process
    assert "$cleanupWaitMilliseconds" in owned_process
    assert "$job.TerminateAndWait($cleanupWaitMilliseconds)" in owned_process
    assert "$reconciliationChildBoundaryReserveSeconds = 8" in script
    assert "if (-not $completed)" in owned_process
    assert "helper tree terminated" in owned_process
    assert re.search(
        r"\$rollVerdictExplicitBase\s*=\s*"
        r"\$(?:ExpectedLocalBaseline|reconciliationLocalBaseline)",
        script,
    )
    assert re.search(
        r"\$rollVerdictExplicitBranch\s*=\s*"
        r"\$ExpectedSourceTip",
        script,
    )
    assert "roll_verdict_explicit_base = $rollVerdictExplicitBase" in script
    assert "roll_verdict_explicit_branch = $rollVerdictExplicitBranch" in script
    assert re.search(
        r"\$rollVerdictExitCode\s*=\s*(?:\$LASTEXITCODE|"
        r"(?:\[int\])?\$[A-Za-z][A-Za-z0-9]*\.exit_code)",
        script,
    )
    assert "$payload.base_ref" in special_roll
    assert "$payload.branch" in special_roll
    assert "$payload.branch -ceq $ExpectedSourceTip" in special_roll
    assert "$payload.closures_used" in special_roll
    assert "$payload.generated_at" in special_roll
    for exit_code in (0, 2, 3):
        assert re.search(rf"(?m)^\s*{exit_code}\s*\{{", special_roll)
    assert "TotalMinutes" in special_roll
    assert "$verdictAgeMinutes -ge 0" in special_roll
    assert "-le 5" in special_roll
    special = _reconciliation_execution_block(script)
    assert "special mode remains quiet-window-only" in special
    assert "explicit roll verdict L->S" in special
    assert (
        "$executionTapeActive -and -not $reconciliationRollVerdictReadable"
        in re.sub(r"\s+", " ", special)
    )

    # Ordinary synchronized merges still use their frozen reviewed tip and do
    # not silently inherit the special mode's deliberately old base.
    assert "& $verdictScript -Branch $verdictRef -JsonOut $verdictJsonPath" in compact
    special_calls = _function_calls(script, "Invoke-ReconciliationRollVerdict")
    assert special_calls
    assert min(special_calls) < script.index("& git add -- $autoRefreshed")


def test_reconciliation_snapshots_only_exact_generated_paths_as_raw_bytes() -> None:
    script = _script_text()

    auto_refreshed = re.search(
        r"\$autoRefreshed = @\((.*?)\)\n\$dirtyTracked", script, re.DOTALL
    )
    assert auto_refreshed is not None
    assert set(re.findall(r'"([^\"]+)"', auto_refreshed.group(1))) == (
        RECONCILIATION_CONFIG_PATHS
    )
    assert "[IO.File]::ReadAllBytes" in script
    assert "[IO.File]::WriteAllBytes" in script
    assert "$reconciliationSnapshotPaths" in script
    assert "$reconciliationSnapshotManifestSha256" in script
    exact_dirty_guard = _braced_block(
        script, "function Assert-ReconciliationExactDirtyConfig"
    )
    assert '" M config/location_market_events.json"' in exact_dirty_guard
    assert '" M config/locations.json"' in exact_dirty_guard
    assert "$rows.Count -ne $expectedRows.Count" in exact_dirty_guard

    # A textual JSON round trip cannot preserve the production bytes. Require
    # a reusable raw-byte assertion that is called both before mutation and at
    # the final publication boundary.
    raw_snapshot = _braced_block(script, "function New-ReconciliationRawSnapshot")
    raw_guard = _braced_block(script, "function Assert-ReconciliationSnapshot")
    assert "[IO.File]::ReadAllBytes" in raw_snapshot
    assert "[IO.File]::WriteAllBytes" in raw_snapshot
    assert "Get-FileHash" in raw_snapshot
    assert "Get-FileHash" in raw_guard
    assert ".Length" in raw_guard
    assert "source_tip = $ExpectedSourceTip" in raw_snapshot
    assert "source_tree = $ExpectedSourceTree" in raw_snapshot
    assert "explicit_branch = $ExpectedSourceTip" in raw_snapshot
    assert (
        "reconciliation_config_content_sha256 = $configContentSha256"
        in raw_snapshot
    )
    for config_hash_field in (
        "auto_refreshed_sha256 = $rollbackContentSha256",
        "rollback_content_sha256 = $rollbackContentSha256",
        "reconciliation_config_content_sha256 = $rollbackContentSha256",
    ):
        assert config_hash_field in script
    special = _reconciliation_execution_block(script)
    snapshot_call = special.index("New-ReconciliationRawSnapshot")
    first_git_mutation = special.index("git -C $repo add --")
    push_attempt = special.index("$publicationInvoked = $true")
    push_call = special.index("Invoke-ReconciliationOneShotPushTask")
    assert snapshot_call < first_git_mutation
    prestart_task_info = special.index(
        "$pushPreInfo = Get-ReconciliationOneShotPushTaskInfo"
    )
    assert special.rfind("Assert-ReconciliationSnapshot", 0, push_attempt) > (
        prestart_task_info
    )
    assert special.rfind("Assert-ReconciliationSnapshot", 0, push_call) > (
        push_attempt
    )
    assert special.rfind("Assert-OneShotPushTask", 0, push_call) > push_attempt

    compact = re.sub(r"\s+", " ", script)
    unchanged_by_published_range = (
        "git diff --quiet $ExpectedLocalBaseline $ExpectedPublishedTarget -- "
        "$autoRefreshed" in compact
        or (
            re.search(
                r"\$(?:ExpectedLocalBaseline|reconciliationLocalBaseline)`:"
                r"\$relativePath",
                script,
            )
            and re.search(
                r"\$(?:ExpectedPublishedTarget|reconciliationPublishedTarget)`:"
                r"\$relativePath",
                script,
            )
        )
    )
    assert unchanged_by_published_range


def test_reconciliation_revalidates_source_origin_and_dependency_pins() -> None:
    script = _script_text()
    lower_script = script.lower()

    assert CANONICAL_ORIGIN_URL in script
    assert REVIEWED_REPAIR_PARENT in lower_script
    assert LOCAL_BASELINE_WORKLOAD_ADMISSION_SHA256 in lower_script
    for dependency, expected_sha256 in RECONCILIATION_DEPENDENCY_SHA256.items():
        assert dependency in script
        assert expected_sha256 in lower_script

    source_guard = _braced_block(script, "function Assert-ReconciliationSourceWorktree")
    origin_guard = _braced_block(script, "function Assert-ReconciliationCanonicalOrigin")
    remote_guard = _braced_block(
        script, "function Assert-ReconciliationRemotePublishedTarget"
    )
    production_guard = _braced_block(
        script, "function Assert-ReconciliationProductionIdentity"
    )
    dependency_guard = _braced_block(
        script, "function Assert-ReconciliationDependencyBytes"
    )
    rpc_dependency_guard = _braced_block(
        script, "function Assert-ReconciliationSchedulerRpcBytes"
    )
    rpc_parent = _braced_block(
        script, "function Invoke-ReconciliationSchedulerRpc"
    )
    assert "$ExpectedSourceTip" in source_guard
    assert "$ExpectedSourceTree" in source_guard
    assert "$ExpectedSelfSha256" in source_guard
    assert '"scripts/ops/quiet_window_merge.ps1"' in source_guard
    assert "$trackedBlob -cne $diskBlob" in source_guard
    assert "$dependencySha256 -cne $ExpectedSelfSha256" in source_guard
    assert "HEAD^{commit}" in source_guard
    assert "HEAD^{tree}" in source_guard
    assert "Assert-ReconciliationCanonicalOrigin" in source_guard
    assert "$reconciliationReviewedParent" in source_guard
    assert "$reconciliationPublishedTarget" in source_guard
    assert "merge-base --is-ancestor" in re.sub(r"\s+", " ", source_guard)
    assert "$sourceHead -ceq $reconciliationPublishedTarget" in source_guard
    assert '"remote", "get-url", "origin"' in origin_guard
    assert '"remote", "get-url", "--push", "origin"' in origin_guard
    assert "$reconciliationCanonicalOrigin" in origin_guard
    assert '"ls-remote", "--exit-code", "--refs"' in remote_guard
    assert "$reconciliationPublishedTarget" in remote_guard
    assert '"refs/heads/master"' in remote_guard
    assert "Assert-ReconciliationCanonicalOrigin" in production_guard
    assert "$ExpectedSourceTip" in production_guard
    assert "$ExpectedSourceTree" in production_guard
    assert "merge-base --is-ancestor" in re.sub(r"\s+", " ", production_guard)
    assert "Get-FileHash" in dependency_guard
    assert "$reconciliationSchedulerRpcSha256" in rpc_dependency_guard
    assert "Get-FileHash" in rpc_dependency_guard
    assert "$reconciliationSchedulerRpcScript" in rpc_dependency_guard
    assert (
        '$reconciliationSchedulerRpcSha256 = [string]$reconciliationDependencySha256['
        in script
    )
    assert '"scripts/ops/production_baseline_scheduler_rpc.ps1@safety_tip"' in script
    rpc_hash = rpc_parent.index("Assert-ReconciliationSchedulerRpcBytes")
    rpc_launch = rpc_parent.index("Invoke-ReconciliationOwnedProcess")
    assert rpc_hash < rpc_launch
    for safety_dependency in (
        "scripts/ops/quiet_window_merge.ps1",
        "scripts/ops/production_baseline_scheduler_rpc.ps1",
        "scripts/ops/windows_kill_on_close_job.ps1",
        "scripts/ops/status.ps1",
        "scripts/ops/health_watchdog.ps1",
    ):
        assert f'"{safety_dependency}"' in source_guard
        assert f'"{safety_dependency}"' in dependency_guard
    assert '"$relativePath@safety_tip"' in source_guard
    assert 'if ($Stage -eq "published_target")' in dependency_guard
    assert '"$relativePath@$Stage"' in dependency_guard
    for dependency, expected_sha256 in RECONCILIATION_DEPENDENCY_SHA256.items():
        assert dependency in dependency_guard
        assert expected_sha256 in dependency_guard.lower()

    special = _reconciliation_execution_block(script)
    first_git_mutation = special.index("git -C $repo add --")
    push_attempt = special.index("$publicationInvoked = $true")
    push_call = special.index("Invoke-ReconciliationOneShotPushTask")
    for function_name in (
        "Assert-ReconciliationSourceWorktree",
        "Assert-ReconciliationDependencyBytes",
    ):
        assert special.index(function_name) < first_git_mutation
        assert special.rfind(function_name, 0, push_call) > push_attempt
    assert special.index("Assert-ReconciliationProductionIdentity") < (
        first_git_mutation
    )
    assert special.rfind("Assert-ReconciliationCanonicalOrigin", 0, push_call) > (
        push_attempt
    )
    assert special.index("Assert-ReconciliationRemotePublishedTarget") < (
        first_git_mutation
    )
    assert special.rfind(
        "Assert-ReconciliationRemotePublishedTarget", 0, push_call
    ) > push_attempt


def test_reconciliation_marker_and_report_add_safety_fields_compatibly() -> None:
    script = _script_text()
    report_writer = _braced_block(script, "function Save-Report")
    marker_writer = _braced_block(script, "function Write-QuietMergeMarker")

    assert 'schema = "quiet_window_merge_report_v0.2"' in report_writer
    assert 'schema = "quiet_window_merge_in_progress_v0.1"' in marker_writer
    assert "rollback_content_sha256 = $rollbackContentSha256" in report_writer
    assert "auto_refreshed_sha256 = $rollbackContentSha256" in marker_writer
    for writer in (report_writer, marker_writer):
        for additive_field in (
            "reconciliation_safety_tip = $reconciliationSafetyTip",
            "reconciliation_safety_tree = $reconciliationSafetyTree",
            "reconciliation_config_content_sha256 = $rollbackContentSha256",
            "reconciliation_staged_safety_capture_recovery_proved = $reconciliationStagedSafetyCaptureRecoveryProved",
            "reconciliation_staged_safety_capture_recovery_at = $reconciliationStagedSafetyCaptureRecoveryAt",
            "reconciliation_pre_push_capture_recovery_proved = $reconciliationPrePushCaptureRecoveryProved",
            "reconciliation_pre_push_capture_recovery_at = $reconciliationPrePushCaptureRecoveryAt",
        ):
            assert additive_field in writer


def test_reconciliation_marker_cutover_is_boot_recovery_safe() -> None:
    script = _script_text()

    for field in (
        "operation_mode = $reconciliationModeName",
        "reconciliation_actual_pre_merge_commit = $reconciliationActualPreMerge",
        "reconciliation_local_baseline = $ExpectedLocalBaseline",
        "reconciliation_published_target = $ExpectedPublishedTarget",
        "reconciliation_source_tip = $ExpectedSourceTip",
        "reconciliation_safety_tip = $reconciliationSafetyTip",
        "reconciliation_safety_tree = $reconciliationSafetyTree",
        "reconciliation_snapshot_manifest_sha256 = $reconciliationSnapshotManifestSha256",
        "reconciliation_config_content_sha256 = $rollbackContentSha256",
        "reconciliation_staged_safety_capture_recovery_proved = $reconciliationStagedSafetyCaptureRecoveryProved",
        "reconciliation_staged_safety_capture_recovery_at = $reconciliationStagedSafetyCaptureRecoveryAt",
        "reconciliation_pre_push_capture_recovery_proved = $reconciliationPrePushCaptureRecoveryProved",
        "reconciliation_pre_push_capture_recovery_at = $reconciliationPrePushCaptureRecoveryAt",
    ):
        assert field in script
    assert re.search(
        r"reconciliation_source_tree\s*=\s*"
        r"\$(?:ExpectedSourceTree|reconciliationSourceTree)",
        script,
    )
    push_field = re.search(
        r"push_invocation_attempted\s*=\s*\$([A-Za-z][A-Za-z0-9]*)", script
    )
    assert push_field is not None

    for phase in (
        "reconciliation_preparing",
        "reconciliation_prepared",
        "reconciliation_merge_uncommitted",
        "reconciliation_capture_recovered_uncommitted",
    ):
        assert re.search(
            rf"(?:Write-QuietMergeMarker|Write-ReconciliationMarker)\s+"
            rf'-Phase\s+"{phase}"',
            script,
        )
    assert 'Write-QuietMergeMarker -Phase "preparing"' in script

    marker_writer = _braced_block(script, "function Write-QuietMergeMarker")
    assert "[string]$marker.expected_tip -ceq $ExpectedSourceTip" in marker_writer
    assert "[string]$marker.resolved_branch_tip -ceq $ExpectedSourceTip" in (
        marker_writer
    )
    assert (
        "[string]$marker.reconciliation_boot_guard_commit -ceq "
        "$ExpectedPublishedTarget"
    ) in re.sub(r"\s+", " ", marker_writer)

    # Before the exact merge M=[C,S] is proved, the legacy pre-merge field is a
    # refusal sentinel that the adopted 3361520 boot script cannot hard-reset.
    sentinel_match = re.search(
        r"(?:Write-QuietMergeMarker|Write-ReconciliationMarker)\s+"
        r'-Phase\s+"reconciliation_preparing"',
        script,
    )
    assert sentinel_match is not None
    sentinel = sentinel_match.start()
    assert re.search(
        r"\$baselineCommit\s*=\s*\$(?:ExpectedLocalBaseline|"
        r"reconciliationLocalBaseline)",
        script[:sentinel],
    )
    assert re.search(
        r"\$reconciliationBootGuardCommit\s*=\s*"
        r"\$(?:ExpectedPublishedTarget|reconciliationPublishedTarget)",
        script[:sentinel],
    )
    assert "$markerPreMerge = if ($productionBaselineReconciliationMode" in script
    assert "$reconciliationBootGuardCommit" in script[
        script.index("$markerPreMerge = if"):script.index("$marker = [ordered]@{")
    ]
    assert script.rfind("$reconciliationActualPreMerge = $null", 0, sentinel) >= 0

    # Only one atomic marker replacement may expose the boot-recognized
    # post-commit phase, after topology, recovery, and real C are all proved.
    topology_match = re.search(
        r"Assert-ReconciliationMergeCommit\s+-Commit\s+"
        r"\$(?:mergeCommit|candidateMergeCommit)",
        script[sentinel:],
    )
    assert topology_match is not None
    topology_proof = sentinel + topology_match.start()
    recovery_proof = script.rfind("$captureRecoveryProved = $true", 0, topology_proof)
    cutover_assignment = script.index(
        "$reconciliationPostCommitMarkerArmed = $true", topology_proof
    )
    cutover_marker = script.index(
        '-Phase "merge_committed_unpublished"',
        cutover_assignment,
    )
    assert recovery_proof < topology_proof < cutover_assignment < cutover_marker
    assert "[IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)" in script
    assert "marker hash/readback proof failed" in script

    for required_gate in (
        "$marker.capture_recovery_proved -eq $true",
        "$marker.reconciliation_staged_safety_capture_recovery_proved -eq $true",
        "$marker.reconciliation_pre_push_capture_recovery_proved -eq $true",
        "$marker.execution_tape_recovery_required -ne $true",
        "$marker.execution_tape_recovery_proved -eq $true",
        "$marker.documentation_transaction_recorded -eq $true",
        "$marker.push_invocation_attempted -eq $true",
        "$marker.publication_acknowledged -eq $true",
    ):
        assert required_gate in marker_writer


def test_reconciliation_rollback_never_uses_the_ordinary_hard_reset_path() -> None:
    script = _script_text()
    rollback = _braced_block(
        script, "function Invoke-ReconciliationRollbackAndProve"
    )
    assert "merge --abort" in rollback
    assert re.search(
        r"reset\s+--mixed\s+\$reconciliationLocalBaseline",
        rollback,
    )
    assert "Assert-ReconciliationExactDirtyConfig" in rollback
    assert "Assert-ReconciliationSnapshot" in rollback
    assert "Test-ReconciliationCaptureProof" in rollback
    assert "Invoke-RollbackAndProve" not in rollback
    for forbidden in (
        "& git reset --hard",
        "& git checkout",
        "& git stash",
        "& git rebase",
        "& git cherry-pick",
        "& git push --force",
    ):
        assert forbidden not in rollback

    # The old hard-reset rollback is intentionally retained for synchronized
    # ordinary merges, but special failures must be routed to the safe helper.
    assert "& git reset --hard $preMerge" in script
    assert len(
        _function_calls(script, "Invoke-ReconciliationRollbackAndProve")
    ) >= 1

    special = _reconciliation_execution_block(script)
    commit_boundary = special.index("$reconciliationCommitInvocationStarted = $true")
    guarded_catch_at = special.index(
        "if ($activeMarkerOwned -and -not $reconciliationCommitInvocationStarted",
        commit_boundary,
    )
    guarded_catch = _braced_block(
        special,
        "if ($activeMarkerOwned -and -not $reconciliationCommitInvocationStarted",
        commit_boundary,
    )
    guarded_catch_block_at = special.index("{", guarded_catch_at)
    guarded_catch_end = guarded_catch_block_at + len(guarded_catch)
    publication = special.index("Invoke-ReconciliationOneShotPushTask")
    assert "Invoke-ReconciliationRollbackAndProve" not in special[
        commit_boundary:guarded_catch_at
    ]
    assert "Invoke-ReconciliationRollbackAndProve" in guarded_catch
    assert "Invoke-ReconciliationRollbackAndProve" not in special[
        guarded_catch_end:publication
    ]


def test_reconciliation_separately_journals_staged_safety_and_pre_push_capture() -> None:
    script = _script_text()
    special = _reconciliation_execution_block(script)

    staged_call = special.index("$afterProof = Test-ReconciliationCaptureProof")
    staged_assignment = special.index(
        "$reconciliationStagedSafetyCaptureRecoveryProved = $true",
        staged_call,
    )
    staged_marker = special.index(
        '-Phase "reconciliation_capture_recovered_uncommitted"',
        staged_assignment,
    )
    merge_commit = special.index("$reconciliationCommitInvocationStarted = $true")
    assert staged_call < staged_assignment < staged_marker < merge_commit

    pre_push_call = special.index("$lastProof = Test-ReconciliationCaptureProof")
    pre_push_assignment = special.index(
        "$reconciliationPrePushCaptureRecoveryProved = $true",
        pre_push_call,
    )
    pre_push_marker = special.index(
        'Write-ReconciliationMarker -Phase "documented_unpublished"',
        pre_push_assignment,
    )
    push_start = special.index("Invoke-ReconciliationOneShotPushTask")
    assert pre_push_call < pre_push_assignment < pre_push_marker < push_start


def test_reconciliation_dry_run_exits_before_every_mutation() -> None:
    script = _script_text()
    special = _reconciliation_execution_block(script)
    dry_run_marker = next(
        (
            marker
            for marker in (
                "if ($DryRun)",
                "if ($productionBaselineReconciliationMode -and $DryRun)",
                "if ($DryRun -and $productionBaselineReconciliationMode)",
            )
            if marker in special
        ),
        None,
    )
    assert dry_run_marker is not None
    dry_run = _braced_block(special, dry_run_marker)

    dry_run_at = special.index(dry_run_marker)
    assert dry_run_at < special.index("New-ReconciliationRawSnapshot")
    assert dry_run_at < special.index("Enter-WeatherHeavyWorkloadLease")
    assert "exit 0" in dry_run or (
        "Stop-Reconciliation" in dry_run and 'Stage "dry_run"' in dry_run
    )
    preflight = special[:dry_run_at]
    assert "Assert-OneShotPushTask" in preflight
    assert "Assert-ReconciliationSourceWorktree" in preflight
    assert "Assert-ReconciliationProductionIdentity" in preflight
    assert "Assert-ReconciliationDependencyBytes" in preflight
    for forbidden in (
        "Write-QuietMergeMarker",
        "Write-ReconciliationMarker",
        "New-ReconciliationRawSnapshot",
        "documentation_transaction",
        "Start-ScheduledTask",
        "git add",
        "git commit",
        "git merge",
        "git reset",
        "git update-ref",
        "git checkout",
        "git stash",
    ):
        assert forbidden not in dry_run


def test_reconciliation_proves_exact_synthetic_parents_tree_and_bytes() -> None:
    script = _script_text()
    config_commit_guard = _braced_block(
        script, "function Assert-ReconciliationConfigCommit"
    )
    merge_guard = _braced_block(script, "function Assert-ReconciliationMergeCommit")

    assert '"rev-list", "--parents", "-n", "1", $Commit' in merge_guard
    assert "$row.Count -ne 3" in merge_guard
    assert "$row[1].ToLowerInvariant() -cne $reconciliationActualPreMerge" in (
        merge_guard
    )
    assert "$row[2].ToLowerInvariant() -cne $ExpectedSourceTip" in (
        merge_guard
    )
    assert "diff --name-only $ExpectedSourceTip $Commit" in re.sub(
        r"\s+", " ", merge_guard
    )
    assert "[config-child,safety-tip]" in merge_guard
    assert "$changes.Count -ne $reconciliationExpectedConfigBlobs.Count" in (
        merge_guard
    )
    assert '"rev-parse", "$Commit`:$relativePath"' in merge_guard
    assert (
        '"rev-parse", "$reconciliationActualPreMerge`:$relativePath"'
        in merge_guard
    )
    assert "$mergeBlob -cne $configBlob" in merge_guard
    assert "Assert-ReconciliationSnapshot" in merge_guard

    assert '"rev-list", "--parents", "-n", "1", $Commit' in config_commit_guard
    assert "$row.Count -ne 2" in config_commit_guard
    assert "$row[1].ToLowerInvariant() -cne $reconciliationLocalBaseline" in (
        config_commit_guard
    )
    assert '"hash-object", "--", $relativePath' in config_commit_guard
    assert "$commitBlob -cne $indexBlob" in config_commit_guard

    special = _reconciliation_execution_block(script)
    assert "git -C $repo merge --no-commit --no-ff $ExpectedSourceTip" in re.sub(
        r"\s+", " ", special
    )
    topology_match = re.search(
        r"Assert-ReconciliationMergeCommit\s+-Commit\s+"
        r"\$(?:mergeCommit|candidateMergeCommit)",
        special,
    )
    assert topology_match is not None
    topology = topology_match.start()
    postcommit_marker = special.index(
        '-Phase "merge_committed_unpublished"', topology
    )
    assert topology < postcommit_marker

    dry_run_guard = _braced_block(script, "function Invoke-ReconciliationDryRun")
    assert "merge --quiet --no-ff --no-edit $ExpectedSourceTip" in re.sub(
        r"\s+", " ", dry_run_guard
    )
    assert "$parents[2].ToLowerInvariant() -cne $ExpectedSourceTip" in (
        dry_run_guard
    )
    assert "diff --name-only $ExpectedSourceTip $dryMerge" in re.sub(
        r"\s+", " ", dry_run_guard
    )


def test_one_shot_task_contract_includes_nontriggering_runtime_settings() -> None:
    script = _script_text()
    scheduler_rpc = _scheduler_rpc_text()
    task_guard = _braced_block(script, "function Assert-OneShotPushTask")
    ordinary_guard = _braced_block(
        task_guard, "if (-not $productionBaselineReconciliationMode)"
    )
    helper_guard = _braced_block(
        scheduler_rpc, "function Get-PushTaskStaticEvidence"
    )
    canonical_xml = _braced_block(
        scheduler_rpc, "function Get-CanonicalPushTaskXmlEvidence"
    )
    fully_validated = _braced_block(
        scheduler_rpc, "function Get-FullyValidatedPushTask"
    )
    parent_guard = _braced_block(
        script, "function Assert-ReconciliationPushSnapshot"
    )

    assert (
        "$pushTriggers = @($pushTask.Triggers | Where-Object { $null -ne $_ })"
        in ordinary_guard
    )
    assert "$pushTriggers.Count -eq 0" in ordinary_guard
    assert '[string]$pushTask.Settings.MultipleInstances -ceq "IgnoreNew"' in (
        ordinary_guard
    )
    assert '[string]$pushTask.Settings.ExecutionTimeLimit -ceq "PT15M"' in (
        ordinary_guard
    )
    assert "$pushTask.Settings.StartWhenAvailable -eq $false" in ordinary_guard

    assert (
        "$triggers = @($Task.Triggers | Where-Object { $null -ne $_ })"
        in helper_guard
    )
    assert "$triggers.Count -ne 0" in helper_guard
    assert '[string]$Task.Settings.MultipleInstances -cne "IgnoreNew"' in (
        helper_guard
    )
    assert '[string]$Task.Settings.ExecutionTimeLimit -cne "PT15M"' in helper_guard
    assert "$Task.Settings.StartWhenAvailable -ne $false" in helper_guard
    assert '[string]$Snapshot.multiple_instances -cne "IgnoreNew"' in parent_guard
    assert '[string]$Snapshot.execution_time_limit -cne "PT15M"' in parent_guard
    assert "$Snapshot.start_when_available -ne $false" in parent_guard
    assert "trigger_count" in parent_guard

    assert "Export-ScheduledTask" in canonical_xml
    assert "-TaskName $script:PushTaskName" in canonical_xml
    assert "-TaskPath $script:FixedTaskPath" in canonical_xml
    assert "-InputObject" not in canonical_xml
    assert "[Text.Encoding]::UTF8.GetBytes($taskXml)" in canonical_xml
    assert "CanonicalXmlEvidence" in helper_guard
    assert "Get-CanonicalPushTaskXmlEvidence" in helper_guard
    first_export = fully_validated.index("Get-CanonicalPushTaskXmlEvidence")
    task_read = fully_validated.index("Get-ExactTask")
    structured_attestation = fully_validated.index("Get-PushTaskStaticEvidence")
    assert first_export < task_read < structured_attestation
    assert "changed during structured attestation" in helper_guard

    for forbidden_mutation in (
        "Register-ScheduledTask",
        "Set-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
    ):
        assert forbidden_mutation not in script
        assert forbidden_mutation not in scheduler_rpc


def test_push_attempt_is_durably_marked_before_the_only_task_start() -> None:
    script = _script_text()
    scheduler_rpc = _scheduler_rpc_text()
    task_start_literal = "Start-ScheduledTask -TaskName WeatherOneShotPush"

    # The sole direct task start belongs to the unchanged ordinary mode. The
    # reconciliation block has no in-process ScheduledTasks mutation at all.
    assert script.count(task_start_literal) == 1
    special = _reconciliation_execution_block(script)
    assert "Start-ScheduledTask" not in special
    assert "Stop-ScheduledTask" not in special
    assert scheduler_rpc.count("Start-ScheduledTask -InputObject $task") == 1
    assert "Start-ScheduledTask -TaskName" not in scheduler_rpc

    push_field = re.search(
        r"push_invocation_attempted\s*=\s*\$([A-Za-z][A-Za-z0-9]*)", script
    )
    assert push_field is not None
    push_variable = push_field.group(1)
    assert f"${push_variable} = $false" in script
    start_helper = _braced_block(
        script, "function Invoke-ReconciliationOneShotPushTask"
    )
    assert "$oneShotPushStartCount -ne 0" in start_helper
    assert "$script:oneShotPushStartCount++" in start_helper
    assert '-Operation "StartPush"' in start_helper
    assert "Invoke-ReconciliationSchedulerRpc" in start_helper
    assert "Assert-ReconciliationMutationResult" in start_helper

    task_start = special.index("Invoke-ReconciliationOneShotPushTask")
    attempted = special.rfind(f"${push_variable} = $true", 0, task_start)
    marker_matches = list(
        re.finditer(
            r"(?:Write-QuietMergeMarker|Write-ReconciliationMarker)\s+"
            r"-Phase\s+\"documented_unpublished\"",
            special[:task_start],
        )
    )
    durable_marker = marker_matches[-1].start() if marker_matches else -1
    assert attempted >= 0
    assert attempted < durable_marker < task_start

    between_attempt_and_start = special[attempted:task_start]
    start_request_id = between_attempt_and_start.index(
        "$pushStartRpcRequestId = [string]$pushStartIdentity.request_id"
    )
    start_deadline = between_attempt_and_start.index(
        "$pushStartRpcDeadlineUtc = [string]$pushStartIdentity.deadline_utc"
    )
    final_marker = between_attempt_and_start.rindex(
        'Write-ReconciliationMarker -Phase "documented_unpublished"'
    )
    assert start_request_id < start_deadline < final_marker
    assert "$documentedMarkerSha256 = $reconciliationMarkerSha256" in (
        between_attempt_and_start[final_marker:]
    )
    assert special.rfind("if ($publicationInvoked)", 0, attempted) >= 0

    switch_at = scheduler_rpc.index("$result = switch ($Operation)")
    rpc_start = _braced_block(scheduler_rpc, '"StartPush"', switch_at)
    marker_proofs = [
        match.start()
        for match in re.finditer("Assert-MutationMarker", rpc_start)
    ]
    mutation = rpc_start.index("Start-ScheduledTask -InputObject $task")
    assert len(marker_proofs) >= 3
    assert marker_proofs == sorted(marker_proofs)
    claim = rpc_start.index("Write-MutationAuthorityClaim")
    assert marker_proofs[-1] < claim < mutation
    assert "Assert-DeadlineOpen -Deadline $validated.deadline" in rpc_start[
        marker_proofs[-1]:claim
    ]
    assert "Assert-MutationMarker" not in rpc_start[claim:mutation]
    assert "Assert-DeadlineOpen" not in rpc_start[claim:mutation]


def test_publication_acknowledgement_reproves_exact_local_and_remote_tip() -> None:
    script = _script_text()
    special = _reconciliation_execution_block(script)
    ack_guard = _braced_block(script, "function Get-ReconciliationPublicationAck")
    task_start = special.index("Invoke-ReconciliationOneShotPushTask")
    acknowledged = special.index("$publicationAcknowledged = $true", task_start)
    acknowledgement = special[task_start:acknowledged]

    assert "Get-ReconciliationPublicationAck" in acknowledgement
    assert "git -C $repo rev-parse HEAD master origin/master" in ack_guard
    assert "Invoke-ReconciliationBoundedGit" in ack_guard
    assert (
        CANONICAL_ORIGIN_URL in ack_guard
        or "$reconciliationCanonicalOrigin" in ack_guard
    )
    assert "refs/heads/master" in ack_guard
    assert "$publicationAck.local_exact" in acknowledgement
    assert "$publicationAck.remote_exact" in acknowledgement
    assert "$oneShotPushTerminalProved = $true" in acknowledgement
    assert "$oneShotPushRunObserved = [bool]$pushRunObserved" in acknowledgement
    assert "Get-ReconciliationOneShotPushTaskInfo" in acknowledgement
    assert "Invoke-RollbackAndProve" not in special[task_start:]


def test_one_shot_runtime_is_bounded_and_terminally_rechecked() -> None:
    script = _script_text()
    scheduler_rpc = _scheduler_rpc_text()
    special = _reconciliation_execution_block(script)
    stop_helper = _braced_block(
        script, "function Invoke-ReconciliationOneShotPushStop"
    )
    containment = _braced_block(
        script, "function Request-ReconciliationOneShotPushContainment"
    )
    owned_process = _braced_block(script, "function Invoke-ReconciliationOwnedProcess")
    absolute_boundary = _braced_block(
        script, "function Stop-ReconciliationAtAbsolutePublicationBoundary"
    )
    bounded_sleep = _braced_block(
        script, "function Start-ReconciliationBoundedPollSleep"
    )

    assert '[Xml.XmlConvert]::ToTimeSpan("PT15M")' in script
    assert "Assert-ReconciliationPublicationTimeBudget -Now (Get-Date)" in special
    assert "Assert-ReconciliationPublicationTimeBudget -Now $pushStartIssuedAt" in special
    assert "$pushContainmentDeadline" in special
    assert "$pushContainmentStopAt = $pushContainmentDeadline.AddSeconds(-30)" in special
    assert "Start-ReconciliationBoundedPollSleep" in special
    assert "if ($Boundary -lt $next) { $next = $Boundary }" in bounded_sleep
    assert "Start-Sleep -Milliseconds $milliseconds" in bounded_sleep
    assert (
        "Request-ReconciliationOneShotPushContainment -LogicalBoundary "
        "$pushContainmentDeadline"
    ) in re.sub(r"\s+", " ", special)
    assert '-Operation "StopPush"' in stop_helper
    assert "Invoke-ReconciliationSchedulerRpc" in stop_helper
    assert "Assert-ReconciliationMutationResult" in stop_helper
    assert "$oneShotPushStopCount -eq 0" in special
    assert "$reconciliationPushStopAttemptLimit = 2" in script
    assert "$oneShotPushStopCount -ge $reconciliationPushStopAttemptLimit" in (
        containment
    )
    assert "$oneShotPushStopExhausted" in special
    assert "$pushTerminalTask.State -cne \"Ready\"" in special
    assert "$oneShotPushContainmentBreached" in special
    assert "-not $oneShotPushContainmentBreached" in special
    assert "Stop-ReconciliationAtAbsolutePublicationBoundary" in special
    assert 'Stage "publication_state_uncertain"' in absolute_boundary
    assert "PT15M/04:00 absolute publication boundary" in absolute_boundary

    # Every Scheduler read/start/stop helper and the canonical roll-verdict
    # process is owned by a kill-on-close Job. Normal exit and timeout both
    # terminate the complete child tree before the caller can continue.
    assert "$remainingBeforeLaunch" in owned_process
    assert "$remainingAtWait" in owned_process
    assert "$process.WaitForExit($waitMilliseconds)" in owned_process
    assert "$cleanupDeadlineUtc" in owned_process
    assert "$remainingCleanupMilliseconds" in owned_process
    assert "$cleanupWaitMilliseconds" in owned_process
    assert "$job.TerminateAndWait($cleanupWaitMilliseconds)" in owned_process
    assert owned_process.index("$job.TerminateAndWait($cleanupWaitMilliseconds)") < (
        owned_process.index("if (-not $completed)")
    )
    assert "child-tree termination could not be proved" in owned_process
    assert "helper tree terminated" in owned_process

    switch_at = scheduler_rpc.index("$result = switch ($Operation)")
    rpc_stop = _braced_block(scheduler_rpc, '"StopPush"', switch_at)
    assert scheduler_rpc.count("Stop-ScheduledTask -InputObject $task") == 1
    assert "Stop-ScheduledTask -TaskName" not in scheduler_rpc
    assert rpc_stop.count("Assert-MutationMarker") >= 3
    assert "Write-MutationAuthorityClaim" in rpc_stop
    assert "Assert-DeadlineOpen -Deadline $validated.deadline" in rpc_stop
    assert "stop_ordinal = [int]$validated.value.stop_ordinal" in rpc_stop

    # An uncertain/lost Stop is terminal and cannot consume the second ordinal.
    stop_rpc = containment.index("Invoke-ReconciliationOneShotPushStop")
    ambiguous_stop = containment[containment.index("catch {", stop_rpc) :]
    assert "$script:oneShotPushStopExhausted = $true" in ambiguous_stop
    assert "no further Scheduler mutation is allowed" in ambiguous_stop


def test_special_unexpected_precommit_failures_use_mixed_rollback() -> None:
    script = _script_text()
    special = _reconciliation_execution_block(script)

    assert "$reconciliationCommitInvocationStarted = $false" in script
    boundary = special.index("$reconciliationCommitInvocationStarted = $true")
    outer_catch = special.index(
        "if ($activeMarkerOwned -and -not $reconciliationCommitInvocationStarted",
        boundary,
    )
    rollback = special.index("Invoke-ReconciliationRollbackAndProve", outer_catch)
    assert boundary < outer_catch < rollback
    assert "reset --mixed $reconciliationLocalBaseline" in script
    assert "reset --hard $reconciliationLocalBaseline" not in special


def test_atomic_marker_backup_survives_failed_post_replace_verification() -> None:
    script = _script_text()
    marker_writer = _braced_block(script, "function Write-QuietMergeMarker")

    replace = marker_writer.index("[IO.File]::Replace")
    verified = marker_writer.index("$replacementVerified = $true", replace)
    conditional_cleanup = marker_writer.index("if ($replacementVerified)", verified)
    assert replace < verified < conditional_cleanup
    assert "Remove-Item -LiteralPath $backup" in marker_writer[conditional_cleanup:]
    assert "old-or-new boot-safe marker" in script


def test_special_status_probes_disable_optional_index_refresh() -> None:
    script = _script_text()

    assert script.count("git --no-optional-locks -C") >= 2


def test_status_uses_evidence_classification_and_never_offers_reconciliation_retry() -> None:
    status = (REPO_ROOT / "scripts" / "ops" / "status.ps1").read_text(
        encoding="utf-8-sig"
    )

    classifier_start = status.index(
        "function Get-WeatherReconciliationPublicationState"
    )
    classifier_end = status.index(
        "function Get-WeatherUnpushedPublicationGuidance", classifier_start
    )
    classifier = status[classifier_start:classifier_end]
    guidance = _braced_block(
        status, "function Get-WeatherUnpushedPublicationGuidance"
    )
    assert "production_baseline_reconciliation_v0.1" in classifier
    assert "ls-remote" in classifier
    assert '"refs/heads/master"' in classifier
    assert "marker or Git refs changed during status validation" in classifier
    assert 'manual_push_allowed = ($Classification -ceq "ordinary")' in classifier
    for classification in (
        "guarded_pre_dispatch",
        "attempted_unacknowledged",
        "acknowledged",
        "incident_evidence_invalid",
    ):
        assert f'"{classification}"' in classifier

    assert 'if ([string]$PublicationState.classification -ceq "ordinary")' in (
        guidance
    )
    assert '"$UnpushedCount commit(s) unpushed (run WeatherOneShotPush)"' in (
        guidance
    )
    for incident_flag in (
        "RECONCILIATION_PUBLICATION_GUARDED_PRE_DISPATCH",
        "RECONCILIATION_PUBLICATION_ATTEMPTED_UNACKNOWLEDGED",
        "RECONCILIATION_PUBLICATION_EVIDENCE_INVALID",
    ):
        assert incident_flag in guidance
    assert "manual WeatherOneShotPush invocation is forbidden" in guidance
    assert "WeatherOneShotPush retry is forbidden" in guidance
    assert "preserve the active marker and obtain reviewed recovery" in guidance

    # The removed boolean shortcut could classify stale cached evidence as an
    # incident. Guidance now receives only the full live-validated state.
    assert "quietPushGuidance.IncidentBoundReconciliation" not in status
    assert "Get-WeatherQuietPushGuidanceState" not in status
    assert "-PublicationState $reconciliationPublication" in status


def test_reconciliation_does_not_weaken_ordinary_synchronized_merges() -> None:
    script = _script_text()
    compact = re.sub(r"\s+", " ", script)

    assert "if ($head -ne $originMaster)" in script
    assert "$ExpectedBaseline = $baselineCommit" in script
    assert "$verdictRef = $ExpectedTip" in script
    assert "& $verdictScript -Branch $verdictRef -JsonOut $verdictJsonPath" in compact
    assert "& git merge --no-commit --no-ff $mergeTarget" in script
    assert "Invoke-RollbackAndProve" in script
    assert "& git reset --hard $preMerge" in script
    assert (
        "if (-not $rollFree -and -not $Force -and "
        "-not ($h -ge 1 -and $h -lt 4))"
    ) in compact
    assert 'Write-QuietMergeMarker -Phase "preparing"' in script
    assert 'Write-QuietMergeMarker -Phase "prepared"' in script


def test_generic_attempt_consumers_reject_one_shot_reconciliation_markers() -> None:
    for relative_path in (
        "scripts/ops/integration_attempt_merge.ps1",
        "scripts/ops/reconcile_integration_attempt.ps1",
        "scripts/ops/close_integration_attempt.ps1",
    ):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8-sig")
        assert "production_baseline_reconciliation_v0.1" in source
        assert re.search(
            r"operation_mode[^\n]*production_baseline_reconciliation_v0\.1",
            source,
        )
        assert re.search(r"(?i)(one-shot|cannot enter|cannot be closed)", source)
