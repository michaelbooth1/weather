import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
REMOTE_GIT = REPO_ROOT / "scripts" / "ops" / "integration_attempt_remote_git.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _powershell_executable() -> str:
    for candidate in ("powershell.exe", "powershell", "pwsh"):
        executable = shutil.which(candidate)
        if executable is not None:
            return executable
    pytest.skip("PowerShell is unavailable on this CI host")


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
    assert '-Arguments @("merge", "--no-commit", "--no-ff", $mergeTarget)' in script


def test_quiet_merge_pins_git_and_offline_mode_cannot_mutate() -> None:
    script = _script_text()

    assert "Get-WeatherIntegrationGitExecutablePath" in script
    assert '-Phase "quiet-window merge entry"' in script
    assert "$gitCommands.Count -ne 1" not in script
    assert "[IO.FileAttributes]::ReparsePoint" in script
    assert re.search(
        r"(?i)&\s*(?:git(?:\.exe)?|\$gitExecutable)\b", script
    ) is None
    assert "Invoke-GitAllowingNativeStderr" not in script
    assert "function Assert-WeatherQuietGitArguments" in script
    assert "function Invoke-WeatherQuietGit" in script
    helper = script[
        script.index("function Invoke-WeatherQuietGit") :
        script.index("$offlineQualification =")
    ]
    assert "Invoke-WeatherIntegrationBoundedProcess `" in helper
    assert "-ExpectedExecutableSha256 $script:quietGitExecutableSha256" in helper
    assert "-TimeoutSeconds $TimeoutSeconds" in helper
    assert "-AllowedExitCodes @(0..255)" in helper
    assert "-RemoveEnvironmentVariables" in helper
    assert 'GIT_CONFIG_NOSYSTEM = "1"' in helper
    assert 'GIT_CONFIG_GLOBAL = "NUL"' in helper
    assert 'GIT_CONFIG_SYSTEM = "NUL"' in helper
    assert 'GIT_NO_REPLACE_OBJECTS = "1"' in helper
    assert 'GIT_TERMINAL_PROMPT = "0"' in helper
    assert '"core.hooksPath=NUL"' in helper
    assert '"core.attributesFile=NUL"' in helper
    assert '"commit.gpgSign=false"' in helper
    assert '"merge.verifySignatures=false"' in helper
    assert '"merge.autoStash=false"' in helper
    assert '"submodule.recurse=false"' in helper
    assert '"fetch.recurseSubmodules=false"' in helper
    assert '"protocol.allow=never"' in helper
    assert '"diff.external="' in helper
    assert '"credential.helper="' in helper
    assert '"--no-pager", "-C", $repo' in helper
    assert '"filter.lfs.process=$quotedGitLfs filter-process"' in helper
    assert "$script:quietGitConfigPin.Stream.CanRead" in helper
    assert "$script:quietGitInfoAttributesPath" in helper
    assert "$script:quietGitForbiddenControlPaths" in helper
    assert "commondir" in script
    assert "objects\\info\\alternates" in script
    assert "info\\grafts" in script
    assert "Assert-WeatherIntegrationSafeRepositoryGitConfiguration" in helper
    lines = script.splitlines()
    for index, line in enumerate(lines[:-1]):
        if "-ExpectedGitExecutable $gitExecutable" in line:
            assert "-ExpectedGitExecutableSha256" in lines[index + 1]
    grammar = script[
        script.index("function Assert-WeatherQuietGitArguments") :
        script.index("function Invoke-WeatherQuietGit")
    ]
    for command in (
        '"rev-parse"',
        '"status"',
        '"symbolic-ref"',
        '"merge-base"',
        '"check-ref-format"',
        '"diff"',
        '"reset"',
        '"add"',
        '"commit"',
        '"merge"',
    ):
        assert command in grammar
    assert "$Arguments.Count -ne 4" in grammar
    assert "unsupported quiet-window Git command" in grammar
    offline = script[script.index('if ($offlineQualification -ceq "1")') :]
    refusal = offline.index("if (-not $DryRun.IsPresent)")
    root_binding = offline.index("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT")
    assert refusal < root_binding
    assert "refuses every non-DryRun quiet merge" in offline


def test_quiet_shared_git_helpers_bind_identity_and_reject_execution_redirects() -> None:
    remote = REMOTE_GIT.read_text(encoding="utf-8")

    assert '[string]$ExpectedGitExecutableSha256 = ""' in remote
    assert "-ExpectedExecutableSha256 $ExpectedGitExecutableSha256" in remote
    assert "$job.TerminateAndWaitForEmpty(5000)" in remote
    assert "$process.ReadStandardOutputBytes($MaxOutputBytes)" in remote
    assert "$process.ReadStandardErrorBytes($MaxOutputBytes)" in remote
    argument_encoder = remote[
        remote.index("function ConvertTo-WeatherIntegrationProcessArgumentString") :
        remote.index("function ConvertFrom-WeatherIntegrationRetainedOutput")
    ]
    assert "((2 * $backslashCount) + 1)" in argument_encoder
    assert "(2 * $backslashCount)" in argument_encoder
    assert "$argumentString.Length -gt 30000" in argument_encoder
    assert "may not contain a double quote" not in argument_encoder
    assert "may not end in a backslash" not in argument_encoder
    assert '$credentialOverrides = @(' in remote
    assert '"-c", "credential.helper=",' in remote
    assert '"-c", "credential.helper=$([string]$remoteSafety.CredentialHelper)"' in remote
    assert 'GIT_CONFIG_NOSYSTEM = "1"' in remote
    assert 'GIT_CONFIG_GLOBAL = "NUL"' in remote
    for redirect in (
        "include(if)?\\..*",
        "extensions\\.(worktreeconfig|partialclone|objectformat|refstorage)",
        "alternaterefscommand",
        "pager\\..*",
        "merge\\..*\\.driver",
        "filter\\..*\\.(clean|smudge|process|required)",
        "diff\\.external",
        "submodule\\.recurse",
        "remote\\..*\\.(promisor|partialclonefilter)",
    ):
        assert redirect in remote
    for environment_name in (
        '"GIT_ATTR_SOURCE"',
        '"GIT_ALLOW_PROTOCOL"',
        '"GIT_LITERAL_PATHSPECS"',
    ):
        assert environment_name in remote
    assert "$_ -match '^GIT_' -or $_ -match '^GCM_'" in remote


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
    owner_query = script[
        script.index("$ownerAncestorResult = Invoke-WeatherQuietGit") :
        script.index("$ownerAncestorExit", script.index("$ownerAncestorResult"))
    ]
    assert '"merge-base", "--is-ancestor", $authorizedRoot, $ExpectedTip' in owner_query
    assert "-not $ownerProtectedWindowException" in script
    assert '-OwnerApprovedException $OwnerApprovedException' in script
    assert 'Join-Path $repo "scripts\\ops\\workload_admission.ps1"' in script
    assert "owner-approved workload admission source changed" in script


def test_quiet_merge_serializes_before_git_mutation_and_rechecks_baseline() -> None:
    script = _script_text()

    lease = script.index("Enter-WeatherHeavyWorkloadLease")
    drift_commit = script.index('Note "committing $($dirtyTracked.Count)')
    merge = script.index('$mergeResult = Invoke-WeatherQuietGit `')
    assert lease < drift_commit < merge
    assert "ExpectedBaseline must be a full 40-character hexadecimal commit SHA" in script
    assert "production baseline moved" in script
    assert "production working tree must have master checked out" in script
    assert "expected_baseline = $ExpectedBaseline" in script


def test_exact_tip_guard_precedes_any_automatic_commit_or_merge() -> None:
    script = _script_text()

    guard = script.index("if ($resolvedBranchTip -ne $ExpectedTip)")
    automatic_commit = script.index('Note "committing $($dirtyTracked.Count)')
    merge = script.index('$mergeResult = Invoke-WeatherQuietGit `')

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
    assert '"commit", "-m",' in script
    assert '"ops: preserve fleet-generated drift' in script


def test_generated_drift_commit_is_bounded_and_checks_exact_exit() -> None:
    script = _script_text()

    helper = script.index("function Invoke-WeatherQuietGit")
    stage = script.index("$gitAddResult = Invoke-WeatherQuietGit")
    commit = script.index("$gitCommitResult = Invoke-WeatherQuietGit")
    merge = script.index('$mergeResult = Invoke-WeatherQuietGit `')

    assert "-AllowedExitCodes @(0..255)" in script[helper:stage]
    assert "$gitAddExit = [int]$gitAddResult.ExitCode" in script
    assert "$gitCommitExit = [int]$gitCommitResult.ExitCode" in script
    assert "bounded generated-drift staging failed" in script
    assert "bounded generated-drift commit failed" in script
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
    fetch_contract_start = script.index("$gitFetchExit = 0")
    fetch = script.index("Invoke-WeatherIntegrationBoundedRemoteGit `", fetch_contract_start)
    git_add = script.index("$gitAddResult = Invoke-WeatherQuietGit")
    fetch_contract = script[fetch_contract_start:git_add]

    assert validation_call < fetch < git_add
    assert "Production quiet merge requires Branch in exact origin/<topic> form" in fetch_contract
    assert "-RemoteRef $topicRemoteRef" in fetch_contract
    assert '-RemoteRef "refs/heads/master"' in fetch_contract
    assert "$liveTopicTip -ne $ExpectedTip" in fetch_contract
    assert "$liveMasterTip -ne $ExpectedBaseline" in fetch_contract
    assert '"+${topicRemoteRef}:${topicTrackingRef}"' in fetch_contract
    assert '"+refs/heads/master:refs/remotes/origin/master"' in fetch_contract
    assert '-Arguments @("fetch", $fetchRemote, "--prune")' not in fetch_contract
    assert '-Arguments @("fetch", "origin", "--prune")' not in fetch_contract
    assert "no mutation may continue from a stale tracking ref" in script
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

    assert '-Arguments @("rev-parse", "HEAD")' in proof
    assert '-Arguments @("rev-parse", "master")' in proof
    assert '-Arguments @("rev-parse", "origin/master")' in proof
    assert 'phase -ne "documented_unpublished"' in proof
    assert "$documentedMarkerSha256" in proof
    assert "$finalMarkerSnapshot = Read-WeatherQuietRetainedSnapshot" in proof
    assert "[string]$finalMarkerSnapshot.Sha256 -cne $documentedMarkerSha256" in proof
    assert "$finalMarker = $finalMarkerSnapshot.Payload" in proof
    assert "documentation_transaction_pending_sha256" in proof
    assert "$finalDocumentationPendingSnapshot = Read-WeatherQuietRetainedSnapshot" in proof
    assert "$finalDocumentationSnapshot = Read-WeatherQuietRetainedSnapshot" in proof
    assert "[string]$finalDocumentationSnapshot.Sha256 -cne" in proof
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
    assert '-Label "post-push origin/master tracking query"' in script


def test_publication_ack_wait_has_wall_monotonic_and_child_bounds() -> None:
    script = _script_text()
    start = script.index("$publicationDeadline = [datetimeoffset]::UtcNow.AddSeconds(180)")
    end = script.index("if (-not $pushed)", start)
    wait = script[start:end]

    assert "$publicationStopwatch = [Diagnostics.Stopwatch]::StartNew()" in wait
    assert "$publicationStopwatch.Elapsed.TotalSeconds -lt 180.0" in wait
    assert "$publicationWallTimeRemaining" in wait
    assert "$publicationMonotonicTimeRemaining" in wait
    assert '-Label "post-push origin/master tracking query" `' in wait
    assert "-TimeoutSeconds 5" in wait
    assert "$publicationStopwatch.Stop()" in wait


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

    reset = script.index('-Label "guarded merge rollback hard-reset fallback"')
    rollback_wait = script.index("$rollbackDeadline = [datetimeoffset]::UtcNow.AddSeconds")
    monotonic = script.index(
        "$rollbackStopwatch = [Diagnostics.Stopwatch]::StartNew()", rollback_wait
    )
    rollback_proof = script.index(
        'Note "every affected producer re-adopted the rollback and satisfies its exact recovery contract"'
    )
    rolled_back = script.index("Save-Report -ok $RecoveredOk -stage $RecoveredStage")

    assert "[ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200" in script
    assert '[ValidateSet("rolled_back", "dry_run")][string]$RecoveredStage = "rolled_back"' in script
    assert "[bool]$RecoveredOk = $false" in script
    assert 'Save-Report -ok $false -stage "rollback_recovery_failed"' in script
    assert "$rollbackStopwatch.Elapsed.TotalSeconds -lt" in script
    assert "[double]$RollbackRecoverySeconds" in script
    assert "while ($rollbackWallTimeRemaining -and $rollbackMonotonicTimeRemaining)" in script
    assert "$rollbackStopwatch.Stop()" in script
    assert reset < rollback_wait < monotonic < rollback_proof < rolled_back


def test_merge_stays_uncommitted_until_all_required_recovery_proofs_pass() -> None:
    script = _script_text()

    merge = script.index('$mergeResult = Invoke-WeatherQuietGit `')
    core_proof = script.index("$captureRecoveryProved = $true")
    tape_proof = script.index(
        "if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }"
    )
    commit = script.index('"Merge $Branch into master"')

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
    assert '-Arguments @("reset", "--mixed", $baselineCommit)' in script
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
    git_add = script.index("$gitAddResult = Invoke-WeatherQuietGit")
    source_before = script.index(
        "$executionTapeSourceBefore = [string]$executionBefore.recorded_source_fingerprint"
    )
    prepared = script.index('Write-QuietMergeMarker -Phase "prepared"')
    merge = script.index('$mergeResult = Invoke-WeatherQuietGit `')

    assert first_preparing < git_add < source_before < prepared < merge
    assert "both fleet-generated config files must exist before merge preparation" in script


def test_attempt_report_is_exclusive_atomic_and_written_before_mutable_slots() -> None:
    script = _script_text()

    assert '[string]$AttemptReportPath = ""' in script
    assert "AttemptReportPath must be an absolute path" in script
    assert "AttemptReportPath is immutable and already exists" in script
    exclusive_create = script.index("$attemptSnapshot = Write-WeatherQuietImmutableJson")
    latest = script.index("$json | Set-Content -Path $reportPath")
    assert exclusive_create < latest
    immutable_writer = script[
        script.index("function Write-WeatherQuietImmutableJson") :
        script.index("$quietPinnedScripts =")
    ]
    assert "[IO.FileMode]::CreateNew" in immutable_writer
    assert "[IO.FileAccess]::ReadWrite" in immutable_writer
    assert "[IO.FileShare]::Read" in immutable_writer
    assert "$stream.Flush($true)" in immutable_writer
    assert "same-handle hash, text, or JSON readback disagrees" in immutable_writer
    assert 'schema = "quiet_window_merge_report_v0.2"' in script
    assert "publication_acknowledged = $publicationAcknowledged" in script
    assert "authoritative_attempt_report" in script
    assert 'compatibility_outputs_authority = "DIAGNOSTIC_ONLY"' in script
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


def test_active_marker_updates_are_durable_transactional_and_same_buffer_verified() -> None:
    script = _script_text()
    marker = script[
        script.index("function Write-QuietMergeMarker") :
        script.index("function Test-ExecutionTapeActive")
    ]

    assert "[IO.FileMode]::CreateNew" in marker
    assert "[IO.FileOptions]::WriteThrough" in marker
    assert "$tempStream.Flush($true)" in marker
    assert "ConvertFrom-WeatherQuietStrictUtf8Bytes" in marker
    assert "Get-WeatherQuietBytesSha256 -Bytes $tempReadback" in marker
    assert "Read-WeatherQuietRetainedSnapshot" in marker
    assert "[IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)" in marker
    assert "Active-marker transaction backup differs from the prior marker" in marker
    assert "-ErrorAction SilentlyContinue" not in marker


def test_active_marker_transaction_rejects_out_of_band_generation_change(
    tmp_path: Path,
) -> None:
    script = _script_text()
    helper_source = script[
        script.index("function Assert-WeatherQuietMergeRegularPathAncestry") :
        script.index("$quietPinnedScripts =")
    ]
    marker_source = script[
        script.index("function Write-QuietMergeMarker") :
        script.index("function Test-ExecutionTapeActive")
    ]
    harness_path = tmp_path / "quiet-marker-harness.ps1"
    harness_path.write_text(helper_source + "\n" + marker_source, encoding="utf-8")
    marker_root = tmp_path / "repo"
    env = os.environ.copy()
    env["WEATHER_QUIET_MARKER_HARNESS"] = str(harness_path)
    env["WEATHER_QUIET_MARKER_ROOT"] = str(marker_root)
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_QUIET_MARKER_HARNESS
$repo = [IO.Path]::GetFullPath($env:WEATHER_QUIET_MARKER_ROOT)
$alerts = Join-Path $repo 'data\alerts'
[void][IO.Directory]::CreateDirectory($alerts)
$activeMarkerPath = Join-Path $alerts 'quiet_window_merge_in_progress.json'
$Branch = 'origin/candidate'
$ExpectedTip = ('1' * 40) -join ''
$ExpectedBaseline = ('2' * 40) -join ''
$ExpectedOriginUrl = 'https://github.com/example/weather.git'
$resolvedBranchTip = $ExpectedTip
$baselineCommit = $ExpectedBaseline
$preMerge = $ExpectedBaseline
$mergeCommit = $null
$captureRecoveryProved = $false
$executionTapeRecoveryRequired = $false
$executionTapeReadoptionExpected = $false
$executionTapeRolledButInactiveSkipped = $false
$executionTapeRecoveryProved = $false
$executionTapeSourceBefore = $null
$documentationTransactionRecorded = $false
$documentationTransactionPendingSha256 = $null
$documentationTransactionSnapshotPath = $null
$publicationAcknowledged = $false
$rollbackContentSha256 = [ordered]@{}
$script:quietActiveMarkerSha256 = $null
Write-QuietMergeMarker -Phase 'preparing'
$first = Read-WeatherQuietRetainedSnapshot `
    -Path $activeMarkerPath -Label first -Json
Write-QuietMergeMarker -Phase 'prepared'
$second = Read-WeatherQuietRetainedSnapshot `
    -Path $activeMarkerPath -Label second -Json
[IO.File]::WriteAllText(
    $activeMarkerPath,
    '{"schema":"tampered"}',
    (New-Object Text.UTF8Encoding($false, $true))
)
$tamperRejected = $false
try { Write-QuietMergeMarker -Phase 'merge_uncommitted' }
catch {
    $tamperRejected = $_.Exception.Message -like `
        '*changed outside its owned transaction*'
}
[ordered]@{
    first_phase = [string]$first.Payload.phase
    second_phase = [string]$second.Payload.phase
    generations_differ = [string]$first.Sha256 -cne [string]$second.Sha256
    script_hash_matches_second = `
        [string]$script:quietActiveMarkerSha256 -ceq [string]$second.Sha256
    tamper_rejected = $tamperRejected
    debris_count = @(
        Get-ChildItem -LiteralPath $alerts -Force -File |
            Where-Object { $_.Name -match '^\.quiet_window_merge_in_progress\.json\..*\.(tmp|bak)$' }
    ).Count
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "first_phase": "preparing",
        "second_phase": "prepared",
        "generations_differ": True,
        "script_hash_matches_second": True,
        "tamper_rejected": True,
        "debris_count": 0,
    }


def test_quiet_merge_can_bind_its_own_frozen_bytes_and_serializes_roll_verdict() -> None:
    script = _script_text()

    assert '[string]$ExpectedSelfSha256 = ""' in script
    assert '-Path $PSCommandPath `' in script
    assert '$quietPinnedScripts.Add($selfPin)' in script
    lease = script.index("$workloadLease = Enter-WeatherHeavyWorkloadLease")
    verdict = script.index("$rollVerdictResult = Invoke-WeatherIntegrationBoundedProcess")
    assert lease < verdict
    verdict_child = script[verdict : script.index("$rollFree =", verdict)]
    assert "-Executable $powerShellExecutable" in verdict_child
    assert "-ExpectedExecutableSha256 ([string]$powerShellExecutablePin.Sha256)" in verdict_child
    assert '"-File", $rollVerdictPin.Path' in verdict_child
    assert '"-ExpectedGitExecutableSha256", $script:quietGitExecutableSha256' in verdict_child
    assert '"-ExpectedRemoteGitSha256", ([string]$remoteGitPin.Sha256)' in verdict_child
    assert '"-ExpectedJobContainmentSha256", ([string]$jobContainmentPin.Sha256)' in verdict_child
    assert "-TimeoutSeconds 120" in verdict_child
    assert "-AllowedExitCodes @(0, 1, 2, 3)" in verdict_child
    assert "Get-WeatherIntegrationBlockedGitEnvironmentNames" in verdict_child
    assert 'GIT_CONFIG_GLOBAL = "NUL"' not in verdict_child
    assert "$verdictExitCode = [int]$rollVerdictResult.ExitCode" in verdict_child
    assert "[IO.FileMode]::CreateNew" in script
    assert "$verdictSharedReadStream" in script
    assert "$verdictFrozenReadStream" in script
    assert "[IO.FileShare]::ReadWrite" in script
    assert "[IO.FileShare]::Read" in script
    assert "roll-verdict retained byte count changed while reading" in script
    assert "roll-verdict retained JSON SHA256" in script
    assert "roll-verdict cleanup target changed identity" in script
    assert '$verdictProcessingFailure.Exception.Data[' in script
    assert '"weather_cleanup_failure"' in script
    assert "original roll-verdict failure" in script
    assert "Remove-Item -LiteralPath $verdictJsonPath `" in script
    assert "-ErrorAction SilentlyContinue" not in script[
        script.index("$verdictJsonPath =") : script.index(
            "# Gate the auxiliary producer exactly"
        )
    ]


def test_quiet_merge_pins_every_powershell_dependency_across_use() -> None:
    script = _script_text()

    for parameter in (
        "ExpectedRemoteGitSha256",
        "ExpectedJobContainmentSha256",
        "ExpectedWorkloadAdmissionSha256",
        "ExpectedQuietMergePreflightSha256",
        "ExpectedRollVerdictSha256",
        "ExpectedGitExecutableSha256",
        "ExpectedGitLfsExecutableSha256",
        "ExpectedPythonExecutableSha256",
    ):
        assert f"[string]${parameter}" in script
    pin_helper = script[
        script.index("function Assert-WeatherQuietMergeRegularPathAncestry") :
        script.index("$quietPinnedScripts =")
    ]
    assert "[IO.FileAttributes]::ReparsePoint" in pin_helper
    assert pin_helper.count("Assert-WeatherQuietMergeRegularPathAncestry") >= 3
    assert "[IO.FileShare]::Read" in pin_helper
    assert "$sha.ComputeHash($stream)" in pin_helper
    assert "changed after its immutable dependency binding was frozen" in pin_helper
    for pin in (
        "$jobContainmentPin",
        "$powerShellExecutablePin",
        "$selfPin",
        "$remoteGitPin",
        "$gitExecutablePin",
        "$gitLfsExecutablePin",
        "$pythonExecutablePin",
        "$workloadAdmissionPin",
        "$quietPreflightPin",
        "$rollVerdictPin",
    ):
        assert f"$quietPinnedScripts.Add({pin})" in script
    invocation = script.index("$rollVerdictResult = Invoke-WeatherIntegrationBoundedProcess")
    retained_cleanup = script.index("$pin.Stream.Dispose()", invocation)
    assert invocation < retained_cleanup
    assert '"-GitExecutable", $gitExecutable' in script[invocation:retained_cleanup]
    assert "Get-WeatherIntegrationGitLfsExecutablePath" in script
    assert '-GitExecutable $gitExecutable' in script
    assert '"core.hooksPath=NUL"' in script
    assert "$quietGitConfigPin" in script
    assert "repository-local info/attributes" in script


def test_quiet_python_children_are_contained_and_stage_bound() -> None:
    script = _script_text()

    assert "function Invoke-WeatherQuietPythonJson" in script
    assert "Invoke-WeatherIntegrationBoundedProcess" in script
    assert "-ExpectedExecutableSha256 $pythonExecutableSha256" in script
    assert '@("-P", "-B") + $Arguments' in script
    assert "PYTHONPYCACHEPREFIX" in script
    assert "PYTHONDONTWRITEBYTECODE = \"1\"" in script
    assert "PYTHONSAFEPATH = \"1\"" in script
    assert "WEATHER_INTEGRATION_GIT_EXECUTABLE = $gitExecutable" in script
    assert "Assert-WeatherQuietPythonExecutionIdentity" in script
    assert "Get-WeatherQuietLoadedSourceFingerprint" in script
    assert "loaded-source fingerprint does not match the retained stage bytes" in script
    assert "Get-WeatherQuietGitStageObservation" in script
    assert "Assert-WeatherQuietGitStageUnchanged" in script
    assert "StdoutSha256" in script
    assert "python_stage_proofs = @($quietPythonStageProofs)" in script
    assert "& $py" not in script
    assert "& $python" not in script


def test_quiet_python_stage_rejects_hidden_or_mutable_worktree_authority() -> None:
    script = _script_text()

    assert '@("ls-files", "--stage", "-z")' in script
    assert '@("ls-files", "-v", "-z")' in script
    assert 'tag -ceq "S"' in script
    assert "skip-worktree or assume-unchanged" in script
    assert "Get-WeatherQuietTrackedContentFingerprint" in script
    assert "tracked working bytes exceed the 1 GiB bound" in script
    assert "[IO.FileShare]::Read" in script
    assert "tracked_content_sha256" in script
    assert "lfs_identity_sha256" in script
    assert 'lfsKind = "hydrated"' in script
    assert '[string]$lfs.Kind -ceq "-"' in script
    assert '"cat-file", "blob", [string]$index.Blob' in script
    assert '$workingSha -cne $lfsOid' in script
    assert '$length -ne $parsedLfsSize' in script
    assert "LFS worktree bytes do not match the index pointer" in script
    assert '-Executable $gitLfsExecutable' in script
    assert '-ExpectedExecutableSha256 ([string]$gitLfsExecutablePin.Sha256)' in script
    assert '@("ls-files", "--long")' in script


def test_quiet_python_shadow_guard_covers_root_tools_and_derived_roots_not_data() -> None:
    script = _script_text()

    assert '":(top,glob)*$_"' in script
    assert '":(top,glob)$_/**"' in script
    assert '$rootName -ine "data"' in script
    assert '"tools"' in script
    assert "quietPythonAuthorityRoots" in script
    assert "Test-WeatherQuietPythonAuthorityArtifact" in script
    assert "refuses ignored Python/native import or test-config artifacts" in script
    assert "refuses untracked Python/native import or test-config artifacts" in script


def test_quiet_shadow_classifier_rejects_root_and_tools_but_not_data() -> None:
    script = _script_text()
    helper = script[
        script.index("function Test-WeatherQuietPythonAuthorityArtifact") :
        script.index("function Get-WeatherQuietMergeHead")
    ]
    command = (
        '$script:quietPythonAuthorityRoots = '
        '@("app", "scripts", "src", "tests", "tools", "weather")\n'
        + helper
        + r"""
[ordered]@{
    root_python = Test-WeatherQuietPythonAuthorityArtifact -RelativePath 'json.py'
    root_native = Test-WeatherQuietPythonAuthorityArtifact -RelativePath 'shadow.pyd'
    tools_python = Test-WeatherQuietPythonAuthorityArtifact -RelativePath 'tools/json.py'
    data_python = Test-WeatherQuietPythonAuthorityArtifact -RelativePath 'data/json.py'
} | ConvertTo-Json -Compress
"""
    )
    result = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "root_python": True,
        "root_native": True,
        "tools_python": True,
        "data_python": False,
    }


def test_quiet_dependency_pin_rejects_tamper_and_denies_replacement(
    tmp_path: Path,
) -> None:
    script = _script_text()
    helper = script[
        script.index("function Assert-WeatherQuietMergeRegularPathAncestry") :
        script.index("$quietPinnedScripts =")
    ]
    dependency = tmp_path / "dependency.ps1"
    replacement = tmp_path / "replacement.ps1"
    dependency.write_text("'ORIGINAL'\n", encoding="utf-8")
    replacement.write_text("'REPLACEMENT'\n", encoding="utf-8")
    expected = hashlib.sha256(dependency.read_bytes()).hexdigest()
    command = helper + r"""
$pin = Open-WeatherQuietMergePinnedScript `
    -Path $env:WEATHER_DEPENDENCY_PATH `
    -ExpectedSha256 $env:WEATHER_DEPENDENCY_SHA256 `
    -Label 'test dependency'
$writeBlocked = $false
try { [IO.File]::WriteAllText($env:WEATHER_DEPENDENCY_PATH, 'TAMPER') }
catch { $writeBlocked = $true }
$replaceBlocked = $false
try {
    Move-Item -LiteralPath $env:WEATHER_REPLACEMENT_PATH `
        -Destination $env:WEATHER_DEPENDENCY_PATH -Force -ErrorAction Stop
}
catch { $replaceBlocked = $true }
if (-not $writeBlocked -or -not $replaceBlocked) {
    throw 'retained dependency handle allowed write or path replacement'
}
$pin.Stream.Dispose()
$wrongHashRejected = $false
try {
    Open-WeatherQuietMergePinnedScript `
        -Path $env:WEATHER_DEPENDENCY_PATH `
        -ExpectedSha256 ('0' * 64) -Label 'tampered dependency' | Out-Null
}
catch { $wrongHashRejected = $true }
if (-not $wrongHashRejected) { throw 'dependency hash tamper was accepted' }
'OK'
"""
    env = os.environ.copy()
    env.update(
        WEATHER_DEPENDENCY_PATH=str(dependency),
        WEATHER_REPLACEMENT_PATH=str(replacement),
        WEATHER_DEPENDENCY_SHA256=expected,
    )
    result = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_legacy_callers_bind_observed_synchronized_baseline_before_marker() -> None:
    script = _script_text()

    baseline = script.index("$baselineCommit = $head.ToLowerInvariant()")
    binding = script.index("$ExpectedBaseline = $baselineCommit", baseline)
    first_marker = script.index('Write-QuietMergeMarker -Phase "preparing"')
    assert baseline < binding < first_marker


def test_legacy_callers_freeze_observed_tip_before_merge_and_marker() -> None:
    script = _script_text()

    binding = script.index("$ExpectedTip = ([string]$preVerdictBranchTip[0])")
    assert '-Arguments @("rev-parse", "--verify", $preVerdictCommitRef)' in script
    verdict = script.index("$rollVerdictResult = Invoke-WeatherIntegrationBoundedProcess")
    fetch = script.index(
        "Invoke-WeatherIntegrationBoundedRemoteGit `", script.index("$gitFetchExit = 0")
    )
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


def test_fetch_and_every_merge_mutation_is_contained_and_checks_exit() -> None:
    script = _script_text()

    fetch_start = script.index("$gitFetchExit = 0")
    fetch = script.index("Invoke-WeatherIntegrationBoundedRemoteGit `", fetch_start)
    fetch_to_guard = script[fetch_start : script.index("$branchCommitRef", fetch)]
    assert "Get-WeatherIntegrationCanonicalRemoteTip" in fetch_to_guard
    assert "-RemoteRef $topicRemoteRef" in fetch_to_guard
    assert '-RemoteRef "refs/heads/master"' in fetch_to_guard
    assert "$liveTopicTip -ne $ExpectedTip" in fetch_to_guard
    assert "$liveMasterTip -ne $ExpectedBaseline" in fetch_to_guard
    assert '"+${topicRemoteRef}:${topicTrackingRef}"' in fetch_to_guard
    assert '"+refs/heads/master:refs/remotes/origin/master"' in fetch_to_guard
    assert '-Arguments @("fetch", $fetchRemote, "--prune")' not in fetch_to_guard
    assert '-Arguments @("fetch", "origin", "--prune")' not in fetch_to_guard
    assert "$gitFetchFailure = $_.Exception.Message" in script[fetch:]
    assert "$gitFetchExit = 1" in script[fetch:]
    assert "if ($gitFetchExit -ne 0)" in script
    assert "merging the last-fetched copy" not in script
    assert "$mergeResult = Invoke-WeatherQuietGit" in script
    assert "$mergeExit = [int]$mergeResult.ExitCode" in script
    assert "$mergeCommitResult = Invoke-WeatherQuietGit" in script
    assert "$mergeCommitExit = [int]$mergeCommitResult.ExitCode" in script
    assert "$dryRunExitCode = if ($dryRunOk) { 0 } else { 2 }" in script
    assert "-RecoveredExitCode $dryRunExitCode" in script
    dry_merge = script.index("$dryMergeResult = Invoke-WeatherQuietGit")
    dry_abort = script.index("$dryAbortResult = Invoke-WeatherQuietGit", dry_merge)
    dry_proof = script.index("Invoke-RollbackAndProve", dry_abort)
    assert dry_merge < dry_abort < dry_proof
    assert "dry-run bounded Git control failed" in script[dry_merge:dry_proof]
    assert "merge rollback control failed after its contained Git child was drained" in script
    assert "recovery_error=$($_.Exception.Message); original=$primaryDetail" in script


def test_every_production_fetch_cannot_accept_stale_origin_tracking_refs() -> None:
    script = _script_text()
    start = script.index("$gitFetchExit = 0")
    end = script.index("$branchCommitRef", start)
    contract = script[start:end]

    live_topic = contract.index("$liveTopicTip = Get-WeatherIntegrationCanonicalRemoteTip")
    live_master = contract.index("$liveMasterTip = Get-WeatherIntegrationCanonicalRemoteTip")
    explicit_fetch = contract.index('$topicFetchRefspec = "+${topicRemoteRef}:${topicTrackingRef}"')
    topic_guard = contract.index("if ($liveTopicTip -ne $ExpectedTip)")
    master_guard = contract.index("if ($liveMasterTip -ne $ExpectedBaseline)")

    assert topic_guard < live_master
    assert master_guard < explicit_fetch
    assert live_topic < topic_guard < live_master < master_guard < explicit_fetch
    assert 'fetch", $ExpectedOriginUrl, "--prune"' not in contract
    assert 'fetch", $ExpectedOriginUrl)' not in contract
