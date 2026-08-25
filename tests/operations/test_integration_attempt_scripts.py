import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
SCRIPTS = {
    name: OPS / name
    for name in (
        "integration_attempt_contract.ps1",
        "integration_attempt_remote_git.ps1",
        "integration_attempt_preparation_contract.ps1",
        "prepare_integration_attempt.ps1",
        "assert_integration_attempt_ready.ps1",
        "new_integration_attempt.ps1",
        "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1",
        "register_integration_attempt.ps1",
        "close_integration_attempt.ps1",
        "retire_integration_attempt_tasks.ps1",
        "retire_legacy_integration_bootstrap_task.ps1",
        "dispatch_integration_attempt_recovery.ps1",
        "assert_integration_attempt_success.ps1",
        "reconcile_integration_attempt.ps1",
    )
}
PARSE_SCRIPTS = tuple(SCRIPTS.values()) + tuple(
    OPS / name
    for name in (
        "bounded_worktree_test_suite.ps1",
        "adopt_execution_tape_after_merge.ps1",
        "integration_attempt_quiet_merge_preflight.ps1",
        "one_shot_guarded_launcher.ps1",
        "one_shot_readiness.ps1",
        "write_one_shot_active_manifest.ps1",
        "resolve_one_shot_active_manifest.ps1",
        "recover_one_shot_registry_activation.ps1",
        "compact_one_shot_registry.ps1",
        "reconcile_one_shot_registry_debris.ps1",
        "quiet_window_merge.ps1",
        "status.ps1",
    )
)


def _text(name: str) -> str:
    return SCRIPTS[name].read_text(encoding="utf-8-sig")


def test_control_mutex_cleanup_preserves_primary_and_fails_closed_on_success() -> None:
    contract = _text("integration_attempt_contract.ps1")
    readiness = _text("assert_integration_attempt_ready.ps1")
    activation = (OPS / "activate_integration_attempt.ps1").read_text(
        encoding="utf-8-sig"
    )
    registrar = _text("register_integration_attempt.ps1")
    closer = _text("close_integration_attempt.ps1")
    reconciler = _text("reconcile_integration_attempt.ps1")
    preparer = _text("prepare_integration_attempt.ps1")

    assert "[Management.Automation.ErrorRecord]$PrimaryError" in contract
    assert 'Exception.Data["weather_cleanup_failure"]' in contract
    assert "throw $cleanupMessage" in contract
    for entrypoint in (readiness, activation, registrar, closer, reconciler):
        assert "$primaryError = $_" in entrypoint
        assert "-PrimaryError $primaryError" in entrypoint
    assert closer.count("Exit-WeatherIntegrationControlMutex `") == 2
    assert reconciler.count("Exit-WeatherIntegrationControlMutex `") == 2
    assert '$stage = "release_global_preparation_lock"' in preparer
    assert '$primaryError.Exception.Data["weather_cleanup_failure"]' in preparer
    assert preparer.index('$stage = "release_global_preparation_lock"') < preparer.rindex(
        '$status = "PASS"'
    )


def test_every_attempt_scheduler_mutation_has_the_offline_boundary() -> None:
    mutations = (
        ("register_integration_attempt.ps1", "Register-ScheduledTask"),
        ("activate_integration_attempt.ps1", "Enable-ScheduledTask"),
        ("integration_attempt_merge.ps1", "Stop-ScheduledTask"),
        ("reconcile_integration_attempt.ps1", "Start-ScheduledTask"),
        ("retire_legacy_integration_bootstrap_task.ps1", "Disable-ScheduledTask"),
        ("quiet_window_merge.ps1", "Start-ScheduledTask"),
        ("adopt_execution_tape_after_merge.ps1", "Disable-ScheduledTask"),
        ("adopt_execution_tape_after_merge.ps1", "Enable-ScheduledTask"),
        ("adopt_execution_tape_after_merge.ps1", "Start-ScheduledTask"),
    )
    for name, command_name in mutations:
        script = (OPS / name).read_text(encoding="utf-8-sig")
        command_sites = list(
            re.finditer(rf"(?m)^[ \t]*{re.escape(command_name)}(?:\s|`)", script)
        )
        assert command_sites, f"{name} has no {command_name} mutation to guard"
        assert script.count(f'-CommandName "{command_name}"') == len(command_sites)
        for site in command_sites:
            immediate_prefix = script[max(0, site.start() - 400) : site.start()]
            assert "Assert-WeatherIntegrationSchedulerMutationAllowed" in immediate_prefix
            assert f'-CommandName "{command_name}"' in immediate_prefix

    contract = _text("integration_attempt_contract.ps1")
    contract_disable_sites = list(
        re.finditer(r"(?m)^[ \t]*Disable-ScheduledTask(?:\s|`)", contract)
    )
    assert len(contract_disable_sites) == 2
    guarded_disable = contract.index(
        '-CommandName "Disable-ScheduledTask"', contract.index("function Disable-Weather")
    )
    assert guarded_disable < contract_disable_sites[0].start()
    assert contract_disable_sites[1].start() - guarded_disable < 700

    registrar = _text("register_integration_attempt.ps1")
    assert '[ValidateSet("AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION")]' in registrar
    assert "[string]$SchedulerConfirmation" in registrar
    confirmation_gate = registrar.index("if ($SchedulerConfirmation -cne")
    contract_source = registrar.index('integration_attempt_contract.ps1")')
    assert confirmation_gate < contract_source


def test_offline_scheduler_boundary_allows_only_direct_function_mock() -> None:
    env = os.environ.copy()
    env["WEATHER_INTEGRATION_TEST_OFFLINE"] = "1"
    env["WEATHER_REMOTE_GIT_HELPER"] = str(
        OPS / "integration_attempt_remote_git.ps1"
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT_HELPER
$realRefused = $false
try {
    Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandName 'Start-ScheduledTask' -Phase 'real command test'
}
catch {
    $realRefused =
        ($_.Exception.Message -like '*refuses actual Scheduler mutation*offline*')
}
function Start-ScheduledTask { param([string]$TaskName) }
Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName 'Start-ScheduledTask' -Phase 'function mock test'
Remove-Item Function:\Start-ScheduledTask -Force
Set-Alias -Name Start-ScheduledTask -Value Get-Date -Force
$aliasRefused = $false
try {
    Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandName 'Start-ScheduledTask' -Phase 'alias test'
}
catch {
    $aliasRefused =
        ($_.Exception.Message -like '*refuses actual Scheduler mutation*offline*')
}
if (-not $realRefused -or -not $aliasRefused) {
    throw 'offline Scheduler boundary accepted a real command or alias'
}
'OK'
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_attempt_manifest_freezes_evidence_not_the_entire_night() -> None:
    contract = _text("integration_attempt_contract.ps1")
    creator = _text("new_integration_attempt.ps1")

    assert "weather_integration_attempt_manifest_v1" in contract
    assert "Immutable evidence already exists and will not be replaced" in contract
    assert "AttemptRoot already exists" in creator
    assert "A repair attempt must bind the immutable failed receipt" in creator
    assert 'priorReceipt.status -ne "FAIL"' in creator
    assert "prior_attempt_id" in creator
    assert "review_reference" in creator
    assert "repair_class" in creator
    assert "RepairClass $RepairClass does not authorize changed path" in contract
    assert "Assert-WeatherIntegrationRepairTipPolicy" in creator
    assert "schema_registry_data" in contract
    assert "module-ownership-map" in contract
    assert "manual_reviewed_change" in creator
    assert "retry_unchanged" in creator
    assert "An unchanged retry may not follow another unchanged retry" in creator
    assert "ExpectedTip -ne $PriorTip" in contract
    assert "merge-base --is-ancestor $masterTip $ExpectedTip" in creator
    assert "production working tree must have exact master checked out" in creator
    assert "already has a successor claim" in creator
    assert "successor-claim.json" in creator
    assert "recovery_dispatch" in creator
    assert "reconciliation_receipt" in creator
    assert "suite_at_local" in creator
    assert "merge_at_local" in creator
    assert "expected_test_file_count" in creator
    assert "max_files_per_chunk" in creator
    assert "expected_chunk_count" in creator
    assert '@("ls-files", "--", "tests")' in creator
    assert "quiet_merge_report" in creator
    assert "git reset" not in creator.lower()
    assert "git push" not in creator.lower()

    closer = _text("close_integration_attempt.ps1")
    assert "Disable-WeatherIntegrationAttemptTasks" in closer
    assert "An attempt that reached production cannot be abandoned or retried" in closer
    assert "training_window_contract.ps1" not in closer
    assert "weather_integration_attempt_closure_receipt_v1" in contract
    assert 'Reason = "suite task is still running"' in contract
    assert "Disable-ScheduledTask" in contract
    assert "immutable registration receipt" in contract
    assert "registeredAction.arguments" in contract
    assert 'Principal.LogonType -ne "S4U"' in contract


def test_attempt_suite_runs_ratchets_before_full_suite_and_freezes_receipt() -> None:
    bounded = (OPS / "bounded_worktree_test_suite.ps1").read_text(
        encoding="utf-8-sig"
    )
    suite = _text("integration_attempt_suite.ps1")

    assert "IntegrationPreflight" in bounded
    assert "tests/operations/test_schema_registry.py" in bounded
    assert "tests/operations/test_module_size_audit.py" in bounded
    assert "tests/operations/test_import_architecture.py" in bounded
    assert "VERDICT: INTEGRATION PREFLIGHT PASSED" in bounded
    assert suite.index("-IntegrationPreflight") < suite.index('Phase "full suite"')
    assert "full suite was not started" in suite
    assert "Start-WeatherProcessInJob" not in suite
    assert "Invoke-WeatherIntegrationContainedPowerShellChild" in suite
    assert "manifest.orchestration.bounded_suite.sha256" in suite
    assert "-HardStop $hardStop" in suite
    worktree_state = suite[
        suite.index("function Assert-WeatherAttemptSuiteWorktreeState") :
        suite.index("$contract = Assert-WeatherIntegrationAttemptManifest")
    ]
    assert worktree_state.count("Invoke-WeatherIntegrationCheckedLocalGit") == 12
    assert "& git" not in worktree_state
    assert 'Arguments @("status", "--porcelain")' in worktree_state
    assert 'Arguments @("ls-files", "--", "tests")' in worktree_state
    assert "initial wrapper boundary" in worktree_state
    assert "closing wrapper boundary" in worktree_state
    assert "suite worktree/ref/test tuple changed" in worktree_state
    assert "Python/PowerShell source tuple changed" in worktree_state
    assert suite.count("Assert-WeatherIntegrationGitBaseline") == 3
    assert "weather_integration_attempt_suite_receipt_v1" in (
        _text("integration_attempt_contract.ps1")
    )
    assert "Write-WeatherIntegrationImmutableJson -Path $suiteReceiptPath" in suite
    assert "Get-WeatherIntegrationLogVerdict" in suite
    assert "Assert-WeatherIntegrationFullSuiteVerdict" in suite
    assert "Assert-WeatherIntegrationFullSuiteLogPlan" in suite
    assert "Get-WeatherAttemptLogVerdict" not in suite
    assert "git merge" not in suite.lower()
    assert "git push" not in suite.lower()


def test_creator_sandwiches_immutable_writes_with_live_and_local_ref_tuples() -> None:
    creator = _text("new_integration_attempt.ps1")

    assert "function Get-WeatherIntegrationCreatorLiveRefTuple" in creator
    assert "Invoke-WeatherIntegrationCanonicalLsRemote" in creator
    assert 'RemoteRefs $wantedRefs' in creator
    assert "function Assert-WeatherIntegrationCreatorLiveRefTupleUnchanged" in creator
    assert creator.count("Get-WeatherIntegrationCreatorLiveRefTuple `") >= 6
    assert creator.count("Get-WeatherIntegrationCreatorLocalState `") >= 7
    preflight_write = creator.index(
        "Write-WeatherIntegrationImmutableJson `\n        -Path $PreflightResultPath"
    )
    assert creator.index("$preflightLiveAtWrite", 0, preflight_write) < preflight_write
    assert creator.index("$preflightLiveAfterWrite", preflight_write) > preflight_write
    manifest_write = creator.index(
        "Write-WeatherIntegrationImmutableJson -Path $manifestPath"
    )
    assert creator.index("$manifestLiveAtWrite", 0, manifest_write) < manifest_write
    assert creator.index("$manifestLiveAfterWrite", manifest_write) > manifest_write

    for frozen_helper in (
        "training_window_contract.ps1",
        "windows_kill_on_close_job.ps1",
        "workload_admission.ps1",
        "roll_verdict.ps1",
        "boot_recovery.ps1",
        "register_boot_recovery.ps1",
    ):
        assert frozen_helper in _text("new_integration_attempt.ps1")
        assert frozen_helper in _text("integration_attempt_contract.ps1")


def test_attempt_merge_consumes_exact_receipts_and_preserves_quiet_merge() -> None:
    merge = _text("integration_attempt_merge.ps1")
    downstream = _text("assert_integration_attempt_success.ps1")
    activator = _text("activate_integration_attempt.ps1")

    suite_gate = merge.index("Assert-WeatherIntegrationSuiteReceipt")
    task_gate = merge.index("Assert-WeatherIntegrationSuiteTask")
    quiet_merge = merge.index("$quietMergeExitCode = Invoke-WeatherQuietMergeChild")
    assert suite_gate < quiet_merge
    assert task_gate < quiet_merge
    assert "Suite task arguments are not exactly bound" in merge
    assert "quiet_window_merge.ps1" in merge
    assert 'stage -ne "pushed"' in merge
    assert merge.count("authoritative_attempt_report") >= 4
    assert merge.count("compatibility_outputs_authority") >= 4
    assert '"DIAGNOSTIC_ONLY"' in merge
    assert "Assert-WeatherIntegrationQuietReportBooleanContract" in merge
    assert "property must be a JSON boolean" in merge
    assert merge.count("-not $requiresAttemptReportAuthority -or") >= 3
    assert "documentation transaction recorded" not in merge.lower()
    assert "quietReport.documentation_transaction_recorded" in merge
    assert "merge-base --is-ancestor" in merge
    assert "capture_recovery_check" in merge
    assert "Invoke-WeatherIntegrationBoundedProcess" in merge
    assert "Invoke-WeatherIntegrationPostPublicationCaptureProbe" in merge
    assert "Get-WeatherIntegrationPublishedProbeTuple" in merge
    assert "Get-WeatherIntegrationPublishedSourceFingerprint" in merge
    assert "Get-WeatherIntegrationPublishedLoadedSourceFingerprint" in merge
    assert "@(& $python -m weather.operations.capture_recovery_check" not in merge
    assert "-ExpectedExecutableSha256 $ExpectedPythonSha256" in merge
    assert "-ExpectedPath $GitExecutable" in merge
    assert "$gitHash.ComputeHash($gitIdentityStream)" in merge
    assert "Post-publication Git executable changed after suite qualification" in merge
    assert 'PYTHONPYCACHEPREFIX = $cacheRoot' in merge
    assert 'PYTHONDONTWRITEBYTECODE = "1"' in merge
    assert 'PYTHONSAFEPATH = "1"' in merge
    assert "loaded-source fingerprint does not" in merge
    assert '@("ls-files", "--stage", "-z", "--")' in merge
    assert '@("ls-files", "-v", "-z", "--")' in merge
    assert "skip-worktree or assume-unchanged" in merge
    assert "& git" not in merge
    assert merge.count("Invoke-WeatherIntegrationCheckedLocalGit") >= 4
    assert "& git" not in activator
    assert activator.count("Invoke-WeatherIntegrationCheckedLocalGit") == 3
    assert '@("worktree", "list", "--porcelain")' in activator
    assert '@("rev-parse", "--verify", "HEAD^{commit}")' in activator
    assert '@("status", "--porcelain")' in activator
    quiet_child = merge[
        merge.index("function Invoke-WeatherQuietMergeChild") :
        merge.index("function Get-WeatherIntegrationRecoverableActiveMarker")
    ]
    assert "[IO.FileShare]::Read" in quiet_child
    assert "$scriptHash.ComputeHash($scriptStream)" in quiet_child
    assert "$job.TerminateAndWaitForEmpty(5000)" in quiet_child
    assert "$scriptStream.Dispose()" in quiet_child
    wait_exit = quiet_child.index("$process.WaitForExit()")
    observed_exit = quiet_child.index(
        "$observedChildExitCode = [int]$process.ExitCode", wait_exit
    )
    post_exit_drain = quiet_child.index(
        "$job.TerminateAndWaitForEmpty(5000)", observed_exit
    )
    assert wait_exit < observed_exit < post_exit_drain
    assert 'Data["weather_observed_child_exit_code"]' in quiet_child
    assert 'Data["weather_post_exit_failure"]' in quiet_child
    assert "$outerRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in quiet_child
    assert "$outerRuntimeStopwatch.Elapsed.TotalSeconds" in quiet_child
    assert "Wait-WeatherIntegrationSuiteTerminal" in merge
    assert "Get-WeatherIntegrationSuiteWaitDecision" in merge
    wait_region = merge[
        merge.index("function Wait-WeatherIntegrationSuiteTerminal") :
        merge.index("function Assert-WeatherIntegrationMergeTask")
    ]
    assert "$waitRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in wait_region
    assert "$waitRuntimeStopwatch.Elapsed.TotalSeconds" in wait_region
    assert "$stopRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in wait_region
    assert "$stopRuntimeStopwatch.Elapsed.TotalSeconds -lt 120" in wait_region
    assert '"-ExpectedBaseline", $ExpectedBaseline' in merge
    for dependency_argument in (
        "-ExpectedRemoteGitSha256",
        "-ExpectedJobContainmentSha256",
        "-ExpectedWorkloadAdmissionSha256",
        "-ExpectedQuietMergePreflightSha256",
        "-ExpectedRollVerdictSha256",
        "-ExpectedGitExecutableSha256",
        "-ExpectedGitLfsExecutableSha256",
        "-ExpectedPythonExecutableSha256",
    ):
        assert dependency_argument in quiet_child
    assert '"remote_git", "job_containment", "workload_admission"' in merge
    assert '"quiet_merge_preflight", "roll_verdict"' in merge
    assert '"git_executable"' in merge
    assert '"git_lfs_executable"' in merge
    assert '"python_executable"' in merge
    assert '"powershell_executable"' in merge
    assert "python_environment_post_path" in merge
    assert "toolchain_post_path" in merge
    assert "integration_toolchain_fingerprint_v1" in merge
    assert "qualifiedGitPath" in merge
    assert "Read-WeatherIntegrationEvidenceSnapshot" in merge
    assert "Qualified Python interpreter path" in merge
    assert "strict v2 quiet merge lacks one complete frozen dependency/toolchain" in merge.lower()
    assert "python_stage_proofs" in merge
    assert "tracked_content_sha256" in merge
    assert "lfs_identity_sha256" in merge
    assert "capture_execution" in merge
    assert "git_executable_sha256" in merge
    assert "loaded_source_total_bytes" in merge
    assert "$powerShellHash.ComputeHash($powerShellStream)" in quiet_child
    assert "$powerShellStream.Dispose()" in quiet_child
    assert "expected_baseline -ne [string]$manifest.baseline.master" in merge
    assert merge.count("Assert-WeatherIntegrationGitBaseline") == 2
    assert merge.count("Assert-WeatherIntegrationOrchestrationFiles") == 2
    assert "suiteDeadlineStopEvidence" in merge
    assert "Stop-ScheduledTask -TaskName $taskName" in merge
    assert "suitePassExitGraceEvidence" in merge
    assert "suite_pass_exit_grace" in merge
    assert "suiteStaleSchedulerResultEvidence" in merge
    assert "suite_stale_scheduler_result" in merge
    assert 'task.State -notin @("Ready", "Disabled")' in merge
    assert 'binding.Task.State -notin @("Ready", "Disabled")' in merge
    assert 'binding.Task.State -in @("Ready", "Disabled")' in merge
    assert "staleTerminalResult" in merge
    assert 'status = "MERGED_UNVERIFIED"' in merge
    assert "Write-WeatherIntegrationImmutableJson -Path $attemptQuietReportPath" not in merge
    assert '"-AttemptReportPath", $AttemptReportPath' in merge
    assert "-AttemptReportPath $attemptQuietReportPath" in merge
    assert "Write-WeatherIntegrationImmutableJson -Path $mergeReceiptPath" in merge
    assert "git push" not in merge.lower()

    assert "ExpectedMergeReceiptSha256" in downstream
    assert "Assert-WeatherIntegrationMergeReceipt" in downstream
    assert "Assert-WeatherIntegrationSuiteReceipt" in downstream
    assert "function Get-WeatherDownstreamLocalGitTuple" in downstream
    assert "function Get-WeatherDownstreamLiveMasterTip" in downstream
    assert "Assert-WeatherIntegrationSafeGitEnvironment" in downstream
    assert "Get-WeatherIntegrationCanonicalRemoteTip" in downstream
    assert "Historical v1 manifests" in downstream
    assert downstream.count("Get-WeatherDownstreamLocalGitTuple `") == 3
    assert downstream.count("Get-WeatherDownstreamLiveMasterTip `") == 2
    assert "HEAD == master == origin/master == canonical live master" in downstream
    assert "$frozenProductionTip" in downstream
    assert "published integration tip is not in current master history" in downstream
    assert "Invoke-WeatherIntegrationBoundedProcess" in downstream
    assert "-ExpectedExecutableSha256 $expectedPythonExecutableSha256" in downstream
    assert "python_environment_post_path" in downstream
    assert "PYTHONNOUSERSITE = \"1\"" in downstream
    assert "-RemoveEnvironmentVariables $capturePythonControls" in downstream
    assert downstream.count("Assert-WeatherIntegrationNoIgnoredImportArtifacts") == 3
    assert "capture.execution_identity.module_path" in downstream
    assert 'source_scope -cne "loaded_modules"' in downstream
    assert 'git_commit -cne $frozenProductionTip.Substring(0, 12)' in downstream
    initial_tuple = downstream.index("$initialGit = Get-WeatherDownstreamLocalGitTuple")
    ancestry = downstream.index('-Label "published integration ancestry query"')
    capture = downstream.index("$captureResult = Invoke-WeatherIntegrationBoundedProcess")
    final_tuple = downstream.index("$finalGit = Get-WeatherDownstreamLocalGitTuple")
    final_live = downstream.index("$finalLiveMaster = Get-WeatherDownstreamLiveMasterTip")
    closing_tuple = downstream.index("$closingGit = Get-WeatherDownstreamLocalGitTuple")
    authority = downstream.index("authorized = $true")
    assert (
        initial_tuple
        < ancestry
        < capture
        < final_tuple
        < final_live
        < closing_tuple
        < authority
    )
    tuple_helper = downstream[
        downstream.index("function Get-WeatherDownstreamLocalGitTuple") :
        downstream.index("function Get-WeatherDownstreamLiveMasterTip")
    ]
    assert tuple_helper.count('"refs/remotes/origin/master"') == 2
    assert tuple_helper.count('@("status", "--porcelain")') == 2
    assert "local branch/ref tuple changed while it was sampled" in tuple_helper
    assert "tracked-worktree state changed while it was sampled" in tuple_helper


def test_successful_attempt_task_retirement_is_exact_reviewed_and_non_live() -> None:
    retirement = _text("retire_integration_attempt_tasks.ps1")
    contract = _text("integration_attempt_contract.ps1")

    assert "ExpectedManifestSha256" in retirement
    assert "ExpectedMergeReceiptSha256" in retirement
    assert "Assert-WeatherIntegrationMergeReceipt" in retirement
    assert "Assert-WeatherIntegrationSuiteReceipt" in retirement
    assert retirement.count("Assert-WeatherIntegrationRetirementTask") >= 5
    assert 'State -notin @("Ready", "Disabled")' in retirement
    assert "LastTaskResult -ne 0" in retirement
    assert "RETIRE_EXACT_TERMINAL_INTEGRATION_TASKS" in contract
    assert "PreflightOnly" in retirement
    assert retirement.index("if ($PreflightOnly.IsPresent)") < retirement.index(
        "Disable-WeatherIntegrationAttemptTasks"
    )
    assert 'LockLeaf "integration_attempt_terminal.lock"' in retirement
    assert "$primaryError = $_" in retirement
    assert "-PrimaryError $primaryError" in retirement
    assert "Disable-WeatherIntegrationAttemptTasks" in retirement
    assert "task-retirement-receipt.json" in retirement
    assert "Write-WeatherIntegrationImmutableJson" in retirement
    assert "Assert-WeatherIntegrationTaskRetirementReceipt" in retirement
    assert "Assert-WeatherIntegrationTaskRetirementReceipt" in contract
    assert "Assert-WeatherIntegrationFailClosureReceipt" in contract
    assert "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" in retirement
    assert "credential_value_access_authorized = $false" in retirement
    assert "live_exchange_mutation_authorized = $false" in retirement
    assert "Start-ScheduledTask" not in retirement
    assert "Unregister-ScheduledTask" not in retirement

    legacy = _text("retire_legacy_integration_bootstrap_task.ps1")
    assert "ExpectedTaskXmlSha256" in legacy
    assert "ExpectedLastRunTime" in legacy
    assert "ExpectedLastTaskResult" in legacy
    assert "Export-ScheduledTask" in contract
    assert "Get-WeatherIntegrationScheduledTaskSnapshot" in legacy
    assert "RETIRE_EXACT_EXPIRED_LEGACY_INTEGRATION_TASK" in contract
    assert "PreflightOnly" in legacy
    assert legacy.index("if ($PreflightOnly.IsPresent)") < legacy.index(
        "Disable-ScheduledTask"
    )
    assert 'LockLeaf "integration_attempt_terminal.lock"' in legacy
    assert "weather_legacy_integration_bootstrap_task_retirement_v1" in contract
    assert "Write-WeatherIntegrationImmutableJson" in legacy
    assert "Assert-WeatherLegacyBootstrapRetirementReceipt" in legacy
    assert "Assert-WeatherLegacyBootstrapRetirementReceipt" in contract
    assert "Start-ScheduledTask" not in legacy
    assert "Unregister-ScheduledTask" not in legacy


def test_attempt_registrar_is_unique_unattended_and_does_not_start_work() -> None:
    registrar = _text("register_integration_attempt.ps1")

    assert "Attempt task already exists and will not be replaced" in registrar
    assert "Register the fail-closed consumer first" in registrar
    assert "-LogonType S4U" in registrar
    assert "-RunLevel Limited" in registrar
    assert "-Principal $principal" in registrar
    assert "-Once -At $suiteAt" in registrar
    assert "-Once -At $mergeAt" in registrar
    assert "StartWhenAvailable" not in registrar
    assert "downstream_tasks_created = $false" in registrar
    assert "Start-ScheduledTask" not in registrar
    assert "Unregister-ScheduledTask" not in registrar
    assert r"C:\Users\micha" not in registrar
    assert "New-TimeSpan -Hours 4" in registrar
    assert "bounded_suite_max_runtime_seconds" in registrar
    assert "suite_wrapper_teardown_allowance_seconds" in registrar
    assert "suite_task_execution_time_limit_seconds" in registrar
    assert "New-TimeSpan -Seconds $taskLimitSeconds" in registrar
    assert "Manifest suite task runtime limit is absent, unbounded, or inconsistent" in registrar
    assert "Get-WeatherIntegrationCanonicalWindowsIdentity" in registrar
    assert "Assert-WeatherIntegrationCanonicalWindowsIdentityBinding" in registrar
    assert registrar.count("Assert-WeatherIntegrationRegistrarPrincipalUnchanged") == 4
    assert "-UserId ([string]$canonicalPrincipal.user_id)" in registrar
    assert "-UserId $env:USERNAME" not in registrar
    for identity_key in (
        "sid",
        "account_name",
        "authority",
        "machine_name",
        "user_domain_name",
    ):
        assert f"{identity_key} = [string]$canonicalPrincipal.{identity_key}" in registrar
    for ambient_name in ("USERNAME", "USERDOMAIN", "COMPUTERNAME"):
        assert f'Name = "{ambient_name}"' in registrar
    first_identity = registrar.index(
        "Assert-WeatherIntegrationRegistrarPrincipalUnchanged `",
        registrar.index('Phase "merge-task disabled registration boundary"'),
    )
    assert registrar.count("Assert-WeatherIntegrationCurrentAuthorityTuple `") == 3
    first_authority = registrar.index(
        'Phase "merge-task disabled registration boundary"'
    )
    first_mutation = registrar.index("Register-ScheduledTask `")
    second_authority = registrar.index(
        'Phase "suite-task disabled registration boundary"'
    )
    second_mutation = registrar.index("Register-ScheduledTask `", first_mutation + 1)
    final_authority = registrar.index(
        'Phase "final disabled-registration receipt boundary"'
    )
    assert (
        first_authority
        < first_identity
        < first_mutation
        < second_authority
        < second_mutation
        < final_authority
    )


def test_attempt_receipts_label_static_safety_as_authority_not_observed_outcome() -> None:
    attempt_text = "\n".join(path.read_text(encoding="utf-8-sig") for path in SCRIPTS.values())

    assert "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" in attempt_text
    assert "credential_value_access_authorized" in attempt_text
    assert "live_exchange_mutation_authorized" in attempt_text
    assert "credential_value_read" not in attempt_text
    assert "live_exchange_mutation_attempted" not in attempt_text


def test_recovery_dispatch_is_reviewed_non_mutating_and_single_use() -> None:
    dispatch = _text("dispatch_integration_attempt_recovery.ps1")

    assert "ExpectedClosureReceiptSha256" in dispatch
    assert "READY_FOR_SUCCESSOR_REVIEW" in dispatch
    assert "automatic_source_edit_authorized = $false" in dispatch
    assert "scheduler_change_authorized = $false" in dispatch
    assert "orchestration_drift" in dispatch
    assert "orchestration_wrapper or an explicitly manual_reviewed_change" in dispatch
    assert 'FailureClass -notin @("orchestration_wrapper", "manual_reviewed_change")' in dispatch
    assert "Assert-WeatherIntegrationOrchestrationFiles" not in dispatch
    assert "Write-WeatherIntegrationImmutableJson -Path $dispatchPath" in dispatch
    assert "Register-ScheduledTask" not in dispatch
    assert "Start-ScheduledTask" not in dispatch
    assert "git commit" not in dispatch.lower()


def test_orchestration_repair_scope_excludes_governing_policy_documents() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$patterns = @(Get-WeatherIntegrationRepairAllowedPatterns -RepairClass orchestration_wrapper)
$paths = @(
    'docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md',
    'docs/operations/OPERATIONS_DESIGN.md',
    'docs/ops/streak-soak.md',
    'docs/operations/reserved-confirmation-window.md',
    'docs/operations/HOST_LOAD_POLICY.md',
    'docs/operations/DELEGATION_CONTRACT.md',
    'docs/operations/STATE_OF_PLAY.md',
    'scripts/ops/integration_attempt_merge.ps1',
    'scripts/ops/prepare_integration_attempt.ps1',
    'scripts/ops/reconcile_integration_attempt.ps1',
    'scripts/ops/workload_admission.ps1',
    'scripts/ops/status.ps1',
    'tests/operations/test_status_script.py',
    'tests/operations/test_integration_attempt_preparation_scripts.py',
    'tests/operations/test_one_shot_readiness_script.py'
)
@($paths | ForEach-Object {
    $path = $_
    [pscustomobject]@{
        path = $path
        allowed = @($patterns | Where-Object { $path -match $_ }).Count -gt 0
    }
}) | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    allowed = {row["path"]: row["allowed"] for row in json.loads(result.stdout)}
    assert allowed == {
        "docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md": True,
        "docs/operations/OPERATIONS_DESIGN.md": True,
        "docs/ops/streak-soak.md": True,
        "docs/operations/reserved-confirmation-window.md": False,
        "docs/operations/HOST_LOAD_POLICY.md": False,
        "docs/operations/DELEGATION_CONTRACT.md": False,
        "docs/operations/STATE_OF_PLAY.md": False,
        "scripts/ops/integration_attempt_merge.ps1": True,
        "scripts/ops/prepare_integration_attempt.ps1": True,
        "scripts/ops/reconcile_integration_attempt.ps1": True,
        "scripts/ops/workload_admission.ps1": False,
        "scripts/ops/status.ps1": False,
        "tests/operations/test_status_script.py": True,
        "tests/operations/test_integration_attempt_preparation_scripts.py": True,
        "tests/operations/test_one_shot_readiness_script.py": False,
    }


def test_recovery_dispatch_writes_one_hash_bound_successor_instruction(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    zeros = "0" * 40
    orchestration_files = {
        "contract": OPS / "integration_attempt_contract.ps1",
        "attempt_creator": OPS / "new_integration_attempt.ps1",
        "attempt_registrar": OPS / "register_integration_attempt.ps1",
        "attempt_closer": OPS / "close_integration_attempt.ps1",
        "bounded_suite": OPS / "bounded_worktree_test_suite.ps1",
        "attempt_suite": OPS / "integration_attempt_suite.ps1",
        "attempt_merge": OPS / "integration_attempt_merge.ps1",
        "attempt_success_gate": OPS / "assert_integration_attempt_success.ps1",
        "attempt_recovery_dispatch": OPS
        / "dispatch_integration_attempt_recovery.ps1",
        "quiet_merge": OPS / "quiet_window_merge.ps1",
        "token_contract": OPS / "training_window_contract.ps1",
        "job_containment": OPS / "windows_kill_on_close_job.ps1",
        "workload_admission": OPS / "workload_admission.ps1",
        "roll_verdict": OPS / "roll_verdict.ps1",
        "boot_recovery": OPS / "boot_recovery.ps1",
        "register_boot_recovery": OPS / "register_boot_recovery.ps1",
    }
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "dispatch-test",
        "attempt_root": str(attempt_root),
        "repo_root": str(ROOT),
        "worktree_root": str(worktree_root),
        "branch_ref": "origin/codex/dispatch-test",
        "expected_tip": "1" * 40,
        "authorization": {
            "review_reference": "initial-review",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_dispatch-test",
            "merge_task_name": "WeatherIntegrationMerge_dispatch-test",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "orchestration": {
            name: {
                "path": str(path),
                "sha256": (
                    "0" * 64
                    if name == "token_contract"
                    else hashlib.sha256(path.read_bytes()).hexdigest()
                ),
            }
            for name, path in orchestration_files.items()
        },
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
            "reconciliation_receipt": str(attempt_root / "reconciliation-receipt.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    closure_path = attempt_root / "closure-receipt.json"
    closure = {
        "schema": "weather_integration_attempt_closure_receipt_v1",
        "status": "FAIL",
        "attempt_id": "dispatch-test",
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "tasks": [],
    }
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPTS["dispatch_integration_attempt_recovery.ps1"]),
        "-ManifestPath",
        str(manifest_path),
        "-ExpectedManifestSha256",
        manifest_hash,
        "-ExpectedClosureReceiptSha256",
        closure_hash,
        "-FailureClass",
        "schema_registry",
        "-ReviewReference",
        "review-329",
    ]
    wrong_class = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert wrong_class.returncode != 0
    assert "orchestration_wrapper or an explicitly manual_reviewed_change" in wrong_class.stderr

    command[command.index("schema_registry")] = "manual_reviewed_change"
    created = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    payload = json.loads(created.stdout)
    assert payload["status"] == "READY_FOR_SUCCESSOR_REVIEW"
    assert payload["repair_class"] == "manual_reviewed_change"
    assert [row["name"] for row in payload["orchestration_drift"]] == [
        "token_contract"
    ]
    assert payload["closure_receipt_sha256"] == closure_hash
    assert payload["automatic_source_edit_authorized"] is False
    assert payload["scheduler_change_authorized"] is False

    refused = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "already exists" in refused.stderr.lower()


def test_closer_uses_registration_receipt_when_orchestration_helpers_drift(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt"
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    repo_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    subprocess.run(
        ["git", "init", "-b", "master"], cwd=repo_root, check=True, capture_output=True
    )
    (repo_root / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=repo_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Integration Test",
            "-c",
            "user.email=integration@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_NAME": "Integration Test",
            "GIT_AUTHOR_EMAIL": "integration@example.invalid",
            "GIT_COMMITTER_NAME": "Integration Test",
            "GIT_COMMITTER_EMAIL": "integration@example.invalid",
        }
    )
    expected_tip = subprocess.run(
        ["git", "commit-tree", tree, "-p", baseline],
        cwd=repo_root,
        env=commit_env,
        input="reviewed source tip\n",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/master", baseline],
        cwd=repo_root,
        check=True,
    )
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "close-test",
        "attempt_root": str(attempt_root),
        "repo_root": str(repo_root),
        "worktree_root": str(worktree_root),
        "branch_ref": "origin/codex/close-test",
        "expected_tip": expected_tip,
        "authorization": {
            "review_reference": "initial-review",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_close-test",
            "merge_task_name": "WeatherIntegrationMerge_close-test",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": baseline, "origin_master": baseline},
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
            "reconciliation_receipt": str(attempt_root / "reconciliation-receipt.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    executable = str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    registration_path = attempt_root / "registration-receipt.json"
    registration = {
        "schema": "weather_integration_attempt_registration_receipt_v1",
        "status": "PASS",
        "attempt_id": "close-test",
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "principal": {
            "user_id": "integration-test",
            "logon_type": "S4U",
            "run_level": "Limited",
        },
        "suite": {
            "task_name": "WeatherIntegrationSuite_close-test",
            "registered": False,
            "executable": executable,
            "arguments": "frozen-suite-arguments",
            "working_directory": str(repo_root),
        },
        "merge": {
            "task_name": "WeatherIntegrationMerge_close-test",
            "registered": True,
            "executable": executable,
            "arguments": "frozen-merge-arguments",
            "working_directory": str(repo_root),
        },
    }
    registration_path.write_text(json.dumps(registration), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_ATTEMPT_CLOSE": str(SCRIPTS["close_integration_attempt.ps1"]),
            "WEATHER_ATTEMPT_MANIFEST": str(manifest_path),
            "WEATHER_ATTEMPT_MANIFEST_HASH": manifest_hash,
            "WEATHER_ATTEMPT_EXE": executable,
            "WEATHER_ATTEMPT_ROOT": str(repo_root),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$global:mockTasks = @{
    'WeatherIntegrationSuite_close-test' = [pscustomobject]@{
        TaskName = 'WeatherIntegrationSuite_close-test'
        TaskPath = '\'
        State = 'Ready'
        Actions = @([pscustomobject]@{ Execute = $env:WEATHER_ATTEMPT_EXE; Arguments = 'frozen-suite-arguments'; WorkingDirectory = $env:WEATHER_ATTEMPT_ROOT })
        Principal = [pscustomobject]@{ UserId = 'integration-test'; LogonType = 'S4U'; RunLevel = 'Limited' }
    }
    'WeatherIntegrationMerge_close-test' = [pscustomobject]@{
        TaskName = 'WeatherIntegrationMerge_close-test'
        TaskPath = '\'
        State = 'Ready'
        Actions = @([pscustomobject]@{ Execute = $env:WEATHER_ATTEMPT_EXE; Arguments = 'frozen-merge-arguments'; WorkingDirectory = $env:WEATHER_ATTEMPT_ROOT })
        Principal = [pscustomobject]@{ UserId = 'integration-test'; LogonType = 'S4U'; RunLevel = 'Limited' }
    }
}
function Get-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    if ([string]::IsNullOrWhiteSpace($TaskName)) {
        return @($global:mockTasks.Values)
    }
    return $global:mockTasks[$TaskName]
}
function Disable-ScheduledTask { param([string]$TaskName, [string]$TaskPath, $ErrorAction); $global:mockTasks[$TaskName].State = 'Disabled'; return $global:mockTasks[$TaskName] }
function Get-ScheduledTaskInfo { param([string]$TaskName, [string]$TaskPath, $ErrorAction); return [pscustomobject]@{ LastRunTime = [datetime]'2026-08-21T00:30:00'; LastTaskResult = 1 } }
& $env:WEATHER_ATTEMPT_CLOSE `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedManifestSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH `
    -Reason 'reviewed failure' `
    -ReviewReference 'review-close'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    closure = json.loads((attempt_root / "closure-receipt.json").read_text(encoding="utf-8-sig"))
    assert closure["status"] == "FAIL"
    assert [task["disabled"] for task in closure["tasks"]] == [True, True]
    assert closure["tasks"][0]["registration_receipt_disagreed"] is True
    assert closure["tasks"][1]["registration_receipt_disagreed"] is False


def test_close_final_task_snapshot_fails_on_scheduler_error_or_appeared_task() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CLOSE"] = str(SCRIPTS["close_integration_attempt.ps1"])
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_ATTEMPT_CLOSE, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'close script did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-WeatherClosureTasksQuiescent'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing closure task-quiescence function' }
Invoke-Expression $functionAst.Extent.Text
function Get-WeatherIntegrationRegistrationIntentPath {
    return 'Z:\definitely-missing-intent.json'
}
$contract = [pscustomobject]@{
    Manifest = [pscustomobject]@{
        schedule = [pscustomobject]@{
            suite_task_name = 'WeatherIntegrationSuite_a'
            merge_task_name = 'WeatherIntegrationMerge_a'
        }
    }
}
$evidence = @(
    [pscustomobject]@{ task_name = 'WeatherIntegrationSuite_a'; exists = $false; disabled = $false },
    [pscustomobject]@{ task_name = 'WeatherIntegrationMerge_a'; exists = $false; disabled = $false }
)
function Get-WeatherIntegrationScheduledTaskSnapshot {
    throw 'synthetic Scheduler enumeration failure'
}
$schedulerFailureBlocked = $false
try {
    Assert-WeatherClosureTasksQuiescent `
        -AttemptContract $contract -DisableEvidence $evidence
}
catch { $schedulerFailureBlocked = $_.Exception.Message -like '*synthetic Scheduler*' }
function Get-WeatherIntegrationScheduledTaskSnapshot {
    return @([pscustomobject]@{
        TaskName = 'weatherintegrationsuite_A'
        TaskPath = '\'
        State = 'Ready'
    })
}
$appearedTaskBlocked = $false
try {
    Assert-WeatherClosureTasksQuiescent `
        -AttemptContract $contract -DisableEvidence $evidence
}
catch { $appearedTaskBlocked = $_.Exception.Message -like '*appeared after*' }
if (-not $schedulerFailureBlocked -or -not $appearedTaskBlocked) {
    throw 'closure task snapshot accepted unproved absence'
}
'OK'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_execution_tape_adoption_accepts_only_hash_bound_attempt_receipts() -> None:
    adoption = (OPS / "adopt_execution_tape_after_merge.ps1").read_text(
        encoding="utf-8-sig"
    )
    downstream = _text("assert_integration_attempt_success.ps1")

    assert "AttemptManifestPath" in adoption
    assert "ExpectedManifestSha256" in adoption
    assert "ExpectedMergeReceiptSha256" in adoption
    assert "assert_integration_attempt_success.ps1" in adoption
    assert "suite_gated_quiet_merge.ps1" in adoption  # legacy path remains supported
    assert "python_executable_sha256 = $expectedPythonExecutableSha256" in downstream
    assert '[string]$_.kind -ceq "launcher"' in downstream
    assert "-Right $pythonw" in downstream
    assert "pythonw_executable_sha256 = $expectedPythonwExecutableSha256" in downstream
    assert 'python_binding_authority = if (' in downstream
    assert "IMMUTABLE_FULL_SUITE_ENVIRONMENT" in downstream
    assert "Get-WeatherAdoptionPythonBinding" in adoption
    assert "expectedQualifiedPythonSha256" in adoption
    assert adoption.count("Invoke-WeatherAdoptionPythonJson") >= 5
    assert "Invoke-WeatherIntegrationBoundedProcess" in adoption
    assert "-ExpectedExecutableSha256 ([string]$PythonBinding.Sha256)" in adoption
    assert "Assert-WeatherAdoptionPythonExecutionIdentity" in adoption
    assert "Get-WeatherAdoptionLoadedSourceFingerprint" in adoption
    assert "Get-WeatherAdoptionGitTuple" in adoption
    assert "Assert-WeatherAdoptionGitTupleUnchanged" in adoption
    assert "PYTHONPYCACHEPREFIX = $cacheRoot" in adoption
    assert "PYTHONDONTWRITEBYTECODE = \"1\"" in adoption
    assert "Get-WeatherIntegrationBlockedGitEnvironmentNames" in adoption
    for direct in (
        "& $attemptGate",
        "& $gatePath",
        "& $python",
        "& $pythonw",
        "& $script:python",
        "& git",
    ):
        assert direct not in adoption

    gate = adoption[
        adoption.index("function Invoke-WeatherAdoptionAttemptSuccessGate") :
        adoption.index("function Get-WeatherAdoptionLiveMaster")
    ]
    assert "Invoke-WeatherIntegrationContainedPowerShellChild" in gate
    assert "-ExpectedSha256 ([string]$gateRecord.sha256)" in gate
    assert "$child.ScriptSha256 -cne [string]$gateRecord.sha256" in gate
    assert '"WINDOWS_JOB_KILL_ON_CLOSE_RETAINED_OUTPUT"' in gate
    assert "[string]$child.Stderr" in gate
    assert "[string]$child.Stdout | ConvertFrom-Json -ErrorAction Stop" in gate
    assert "($actual -join \"`n\") -cne ($required -join \"`n\")" in gate
    assert '"weather_gate_dependency_cleanup_failure"' in gate
    for dependency in ('"contract"', '"remote_git"', '"job_containment"'):
        assert dependency in gate
    assert "WeatherIntegrationAttemptLegacyManifestSchema" in gate
    assert "Legacy manifests predate the remote_git hash field" in gate

    binding = adoption[
        adoption.index("function Get-WeatherAdoptionPythonBinding") :
        adoption.index("function Close-WeatherAdoptionExecutableBinding")
    ]
    assert "[IO.FileShare]::Read" in binding
    assert "Stream = $stream" in binding
    assert "-Path $pythonw -ExpectedSha256 $expectedQualifiedPythonwSha256" in adoption
    assert "execute_sha256 = [string]$script:adoptionPythonwBinding.Sha256" in adoption

    refusal = adoption[
        adoption.index("function Refuse-Adoption") :
        adoption.index("# Convert unexpected parser")
    ]
    guard = refusal.index("if ($script:adoptionRefusalInProgress)")
    armed = refusal.index("$script:adoptionRefusalInProgress = $true")
    disable_guard = refusal.index('-CommandName "Disable-ScheduledTask"')
    disable = refusal.index("Disable-ScheduledTask `")
    stop = refusal.index('"weather.operations.execution_tape_supervisor", "stop"')
    assert guard < armed < disable_guard < disable < stop
    assert "exit 1" in refusal[guard:armed]

    enable_guard = adoption.index('-CommandName "Enable-ScheduledTask"')
    enabled_flag = adoption.index("$script:enabledByThisRun = $true", enable_guard)
    enable = adoption.index("Enable-ScheduledTask `", enabled_flag)
    assert enable_guard < enabled_flag < enable

    writer = adoption[
        adoption.index("$writerLockPath =") : adoption.index("$captureAfterRun =")
    ]
    assert "Read-WeatherIntegrationEvidenceSnapshot" in writer
    assert "-ContentType Json" in writer
    assert "$writerLockSnapshot.Payload" in writer
    assert "$writerLock -is [System.Array]" in writer
    for pid in (
        "$status.pid",
        "$status.managed_process.pid",
        "$writerLock.pid",
        "$writerLock.managed_process.pid",
    ):
        assert f"[int]{pid} -le 0" in writer
    assert "creation_time_token -cne" in writer
    assert "writer_lock_sha256 = [string]$writerLockSnapshot.Sha256" in adoption

    live = adoption[
        adoption.index("function Get-WeatherAdoptionLiveMaster") :
        adoption.index("function Get-WeatherAdoptionSupervisorTaskBinding")
    ]
    assert "Get-WeatherIntegrationCanonicalRemoteTip" in live
    assert "-ExpectedUrl $script:canonicalOriginUrl" in live
    assert "-ExpectedGitExecutable $script:adoptionGitExecutable" in live
    assert adoption.index("$initialLiveMaster = Get-WeatherAdoptionLiveMaster") < (
        adoption.index("$finalLiveMaster = Get-WeatherAdoptionLiveMaster")
    )
    assert "canonical live master changed during execution-tape adoption" in adoption
    for label in (
        "initial supervisor",
        "enabled supervisor",
        "immediate pre-start supervisor",
        "completed supervisor",
        "final supervisor",
    ):
        assert label in adoption
    assert adoption.count("Assert-WeatherAdoptionSupervisorBindingUnchanged") >= 5


def test_execution_tape_adoption_cleanup_preserves_primary_reason() -> None:
    env = os.environ.copy()
    env["WEATHER_INTEGRATION_TEST_OFFLINE"] = "1"
    script = rf"""
$ErrorActionPreference = 'Stop'
$path = {json.dumps(str(OPS / 'adopt_execution_tape_after_merge.ps1'))}
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $path, [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) {{ throw 'adoption parser errors' }}
$functionAst = @($ast.FindAll({{
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Refuse-Adoption'
}}, $true))
if ($functionAst.Count -ne 1) {{ throw 'Refuse-Adoption function not unique' }}
Invoke-Expression $functionAst[0].Extent.Text
$script:enabledByThisRun = $true
$script:adoptionRefusalInProgress = $false
$script:adoptionPythonBinding = [pscustomobject]@{{
    Path = 'synthetic-python.exe'
    Sha256 = ('a' * 64)
    Authority = 'TEST'
}}
$script:adoptionPythonwBinding = [pscustomobject]@{{
    Path = 'synthetic-pythonw.exe'
    Sha256 = ('c' * 64)
    Authority = 'TEST'
}}
$script:adoptionSupervisorBinding = $null
$script:adoptionExpectedCommit = ('b' * 40)
$script:RepoRoot = [IO.Path]::GetFullPath('.')
$script:SupervisorTaskName = 'SyntheticSupervisor'
function Invoke-WeatherAdoptionPythonJson {{
    param(
        $PythonBinding, $RepositoryRoot, $Arguments, $ModuleRelativePath,
        $ExpectedCommit, $Label, $TimeoutSeconds, $AllowedExitCodes
    )
    throw 'synthetic contained-stop failure'
}}
function Assert-WeatherIntegrationSchedulerMutationAllowed {{
    param($CommandName, $Phase)
}}
function Disable-ScheduledTask {{
    param($TaskName, $TaskPath, $ErrorAction)
    throw 'synthetic Scheduler cleanup failure'
}}
function Close-WeatherAdoptionExecutableBinding {{ param($Binding, $Label) }}
function Get-ScheduledTask {{ param($TaskName, $ErrorAction) }}
Refuse-Adoption 'PRIMARY_ADOPTION_FAILURE'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["adopted"] is False
    assert payload["reason"] == "PRIMARY_ADOPTION_FAILURE"
    assert payload["cleanup"]["stopped"] is False
    assert [row["phase"] for row in payload["cleanup"]["failures"]] == [
        "disable_supervisor_task",
        "managed_stop",
    ]


def test_merged_unverified_reconciliation_is_immutable_and_non_authorizing() -> None:
    contract = _text("integration_attempt_contract.ps1")
    reconciler = _text("reconcile_integration_attempt.ps1")
    success_gate = _text("assert_integration_attempt_success.ps1")

    assert "weather_integration_attempt_reconciliation_receipt_v1" in contract
    assert "Assert-WeatherIntegrationMergedUnverifiedReceipt" in contract
    assert 'status -ne "MERGED_UNVERIFIED"' in contract
    assert "Disable-WeatherIntegrationAttemptTasks" in reconciler
    assert "MERGED_RECONCILED" in reconciler
    assert "historical_proof_upgraded = $false" in reconciler
    assert "downstream_authorized = $false" in reconciler
    assert "Current capture state is not healthy for all three workers" in reconciler
    assert "Write-WeatherIntegrationImmutableJson -Path $reconciliationPath" in reconciler
    assert "ExpectedMergeReceiptSha256" in reconciler
    assert "& git" not in reconciler
    assert "& $Python" not in reconciler
    assert "& $python" not in reconciler
    assert "& $cleanupPython" not in reconciler
    assert "Get-WeatherReconciliationPythonBinding" in reconciler
    assert "IMMUTABLE_FULL_SUITE_ENVIRONMENT" in reconciler
    assert "Invoke-WeatherIntegrationBoundedProcess" in reconciler
    assert "-ExpectedExecutableSha256 ([string]$PythonBinding.Sha256)" in reconciler
    assert "Start-WeatherProcessInJob" not in reconciler
    assert "Assert-WeatherReconciliationPythonExecutionIdentity" in reconciler
    assert "Get-WeatherReconciliationLoadedSourceFingerprint" in reconciler
    assert "Assert-WeatherReconciliationPythonGitTupleUnchanged" in reconciler
    assert "python_executions = @(" in reconciler
    assert "stdout_sha256 = [string]$result.StdoutSha256" in reconciler
    assert "stderr_sha256 = [string]$result.StderrSha256" in reconciler
    assert reconciler.count("Invoke-WeatherIntegrationCheckedLocalGit") >= 9
    assert reconciler.count("authoritative_attempt_report") >= 4
    assert reconciler.count("compatibility_outputs_authority") >= 2
    assert "reconciliation quiet-merge report" in reconciler
    assert 'Join-Path $cacheRoot "cache-entry"' not in reconciler
    assert 'Join-Path $cacheRoot "cache-entry"' not in _text(
        "integration_attempt_merge.ps1"
    )
    marker_writer = reconciler[
        reconciler.index("function Write-WeatherReconciliationActiveMarker") :
        reconciler.index("function Assert-WeatherReconciliationOneShotPushTask")
    ]
    assert "[IO.FileMode]::CreateNew" in marker_writer
    assert "[IO.FileShare]::None" in marker_writer
    assert "$tempStream.Flush($true)" in marker_writer
    assert "[IO.File]::Replace($temp, $markerPath, $backup, $true)" in marker_writer
    assert "active-marker transaction backup" in marker_writer
    assert "transaction readback does not equal the exact retained bytes" in marker_writer
    assert 'Data["weather_cleanup_failure"]' in marker_writer
    assert "SilentlyContinue" not in marker_writer
    assert marker_writer.index("[IO.FileMode]::CreateNew") < marker_writer.index(
        "$tempStream.Flush($true)"
    ) < marker_writer.index("[IO.File]::Replace") < marker_writer.index(
        "$updatedSnapshot = Read-WeatherIntegrationEvidenceSnapshot"
    )
    assert "MERGED_RECONCILED" not in success_gate
    assert 'receipt.status -ne "PASS"' in contract
    assert "receipt.attempt_id" in contract
    assert "receipt.manifest_path" in contract


def test_manifest_contract_accepts_canonical_paths_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    attempt_root = tmp_path / "attempt-001"
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "worktree"
    attempt_root.mkdir()
    repo_root.mkdir()
    worktree_root.mkdir()
    manifest_path = attempt_root / "manifest.json"
    zeros = "0" * 40
    manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "attempt-001",
        "attempt_root": str(attempt_root),
        "repo_root": str(repo_root),
        "worktree_root": str(worktree_root),
        "branch_ref": "origin/codex/example",
        "expected_tip": "1" * 40,
        "authorization": {"review_reference": "test-review", "repair_class": "initial"},
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_attempt-001",
            "merge_task_name": "WeatherIntegrationMerge_attempt-001",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": {
            "preflight_log": str(attempt_root / "preflight.log"),
            "full_suite_log": str(attempt_root / "full-suite.log"),
            "suite_receipt": str(attempt_root / "suite-receipt.json"),
            "merge_receipt": str(attempt_root / "merge-receipt.json"),
            "quiet_merge_report": str(attempt_root / "quiet-merge-report.json"),
            "registration_receipt": str(attempt_root / "registration-receipt.json"),
            "closure_receipt": str(attempt_root / "closure-receipt.json"),
            "recovery_dispatch": str(attempt_root / "recovery-dispatch.json"),
            "reconciliation_receipt": str(attempt_root / "reconciliation-receipt.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_MANIFEST"] = str(manifest_path)
    env["WEATHER_ATTEMPT_MANIFEST_HASH"] = manifest_hash
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$contract = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH
$overwriteRefused = $false
try {
    Write-WeatherIntegrationImmutableJson `
        -Path $env:WEATHER_ATTEMPT_MANIFEST `
        -Payload ([ordered]@{ replaced = $true })
}
catch {
    $overwriteRefused = $_.Exception.Message -like '*will not be replaced*'
}
[pscustomobject]@{
    attempt_id = [string]$contract.Manifest.attempt_id
    overwrite_refused = $overwriteRefused
} | ConvertTo-Json -Compress
"""
    accepted = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout) == {
        "attempt_id": "attempt-001",
        "overwrite_refused": True,
    }

    manifest["branch_ref"] = "codex/example"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bare_ref_env = env.copy()
    bare_ref_env["WEATHER_ATTEMPT_MANIFEST_HASH"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    bare_ref_rejected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=bare_ref_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert bare_ref_rejected.returncode != 0
    assert "branch ref is missing or unsafe" in bare_ref_rejected.stderr.lower()

    manifest["branch_ref"] = "origin/codex/tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "manifest hash mismatch" in rejected.stderr.lower()


def test_immutable_writer_allows_exactly_one_concurrent_claim(tmp_path: Path) -> None:
    target = tmp_path / "claim.json"
    base_env = os.environ.copy()
    base_env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    base_env["WEATHER_ATTEMPT_TARGET"] = str(target)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
Write-WeatherIntegrationImmutableJson `
    -Path $env:WEATHER_ATTEMPT_TARGET `
    -Payload ([ordered]@{ writer = $env:WEATHER_ATTEMPT_WRITER })
"""
    processes = []
    for writer in ("one", "two"):
        env = base_env.copy()
        env["WEATHER_ATTEMPT_WRITER"] = writer
        processes.append(
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    results = [process.communicate(timeout=30) for process in processes]
    returncodes = [process.returncode for process in processes]
    assert returncodes.count(0) == 1, results
    assert sum(code != 0 for code in returncodes) == 1, results
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in {"one", "two"}


def test_immutable_writer_ignores_stale_pid_temp_and_still_refuses_destination(
    tmp_path: Path,
) -> None:
    target = tmp_path / "claim.json"
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    env["WEATHER_ATTEMPT_TARGET"] = str(target)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$legacyTemp = '{0}.{1}.tmp' -f $env:WEATHER_ATTEMPT_TARGET, $PID
[IO.File]::WriteAllText($legacyTemp, 'foreign stale debris')
Write-WeatherIntegrationImmutableJson `
    -Path $env:WEATHER_ATTEMPT_TARGET `
    -Payload ([ordered]@{ writer = 'first' })
$overwriteRefused = $false
try {
    Write-WeatherIntegrationImmutableJson `
        -Path $env:WEATHER_ATTEMPT_TARGET `
        -Payload ([ordered]@{ writer = 'second' })
}
catch {
    $overwriteRefused = $_.Exception.Message -like '*will not be replaced*'
}
[pscustomobject]@{
    stale_temp_survived = Test-Path -LiteralPath $legacyTemp -PathType Leaf
    overwrite_refused = $overwriteRefused
    writer = [string](
        (Get-Content -LiteralPath $env:WEATHER_ATTEMPT_TARGET -Raw |
            ConvertFrom-Json).writer
    )
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "stale_temp_survived": True,
        "overwrite_refused": True,
        "writer": "first",
    }


def test_immutable_writer_bounds_depth_verifies_bytes_and_preserves_primary_cleanup_error(
    tmp_path: Path,
) -> None:
    contract = SCRIPTS["integration_attempt_contract.ps1"].read_text(
        encoding="utf-8-sig"
    )
    assert "Assert-WeatherIntegrationJsonPayloadDepth" in contract
    assert "ConvertTo-Json -Depth 100 -ErrorAction Stop" in contract
    assert "$publishedSnapshot = Read-WeatherIntegrationEvidenceSnapshot" in contract
    assert "publishedSnapshot.Sha256 -cne $expectedSha256" in contract
    assert 'Exception.Data["immutable_json_cleanup_failure"]' in contract
    assert "throw $primaryError" in contract

    target = tmp_path / "cleanup.json"
    deep_target = tmp_path / "deep.json"
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_ATTEMPT_CONTRACT": str(
                SCRIPTS["integration_attempt_contract.ps1"]
            ),
            "WEATHER_ATTEMPT_TARGET": str(target),
            "WEATHER_DEEP_TARGET": str(deep_target),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$payload = [ordered]@{ leaf = 1 }
foreach ($index in 1..65) { $payload = [ordered]@{ child = $payload } }
$depthRejected = $false
try { Write-WeatherIntegrationImmutableJson -Path $env:WEATHER_DEEP_TARGET -Payload $payload }
catch { $depthRejected = $_.Exception.Message -like '*supported depth*' }

$script:getItemCalls = 0
function Get-Item {
    [CmdletBinding(DefaultParameterSetName='Path')]
    param(
        [Parameter(ParameterSetName='LiteralPath')][string[]]$LiteralPath,
        [switch]$Force,
        [System.Management.Automation.ActionPreference]$ErrorAction
    )
    $script:getItemCalls += 1
    if ($script:getItemCalls -eq 2) { throw 'PRIMARY_WRITE_PROOF' }
    Microsoft.PowerShell.Management\Get-Item @PSBoundParameters
}
function Remove-Item { throw 'CLEANUP_FAILURE' }
$caught = $null
try {
    Write-WeatherIntegrationImmutableJson `
        -Path $env:WEATHER_ATTEMPT_TARGET -Payload ([ordered]@{ value = 1 })
}
catch { $caught = $_ }
$debris = @(Microsoft.PowerShell.Management\Get-ChildItem `
    -LiteralPath (Split-Path -Parent $env:WEATHER_ATTEMPT_TARGET) `
    -Filter '.cleanup.json.*.tmp')
foreach ($item in $debris) {
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $item.FullName -Force
}
[pscustomobject]@{
    depth_rejected = $depthRejected
    deep_destination_absent = -not (Test-Path -LiteralPath $env:WEATHER_DEEP_TARGET)
    primary_preserved = $caught.Exception.Message -like '*PRIMARY_WRITE_PROOF*'
    cleanup_attached = [string]$caught.Exception.Data['immutable_json_cleanup_failure'] `
        -like '*CLEANUP_FAILURE*'
    cleanup_message_attached = [string]$caught.ErrorDetails.Message `
        -like '*PRIMARY_WRITE_PROOF*Cleanup also failed*CLEANUP_FAILURE*'
} | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "depth_rejected": True,
        "deep_destination_absent": True,
        "primary_preserved": True,
        "cleanup_attached": True,
        "cleanup_message_attached": True,
    }


def test_suite_wait_decision_bounds_running_pass_from_receipt_completion() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$today = [datetime]'2026-08-21T00:00:00'
$deadline = [datetime]'2026-08-21T03:40:00'
$cases = @(
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $false -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $false -Now $deadline -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1).AddMinutes(5) -Deadline $deadline -PassReceiptCompletedAt $today.AddHours(1).AddMinutes(5)
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1).AddMinutes(6) -Deadline $deadline -PassReceiptCompletedAt $today.AddHours(1).AddMinutes(5)
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1).AddMinutes(7) -Deadline $deadline -PassReceiptCompletedAt $today.AddHours(1).AddMinutes(5)
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $deadline -Deadline $deadline -PassReceiptCompletedAt $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Running -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $deadline.AddSeconds(120) -Deadline $deadline -PassReceiptCompletedAt $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Disabled -LastRunTime $today.AddDays(-1) -LastTaskResult 267011 -ReceiptExists $false -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 0 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 267009 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 267011 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Queued -LastRunTime $today.AddMinutes(30) -LastTaskResult 0 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Queued -LastRunTime $today.AddMinutes(30) -LastTaskResult 0 -ReceiptExists $true -ReceiptStatus PASS -Now $deadline -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Unknown -LastRunTime $today.AddDays(-1) -LastTaskResult 267011 -ReceiptExists $false -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Unknown -LastRunTime $today.AddDays(-1) -LastTaskResult 267011 -ReceiptExists $false -Now $deadline -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 1 -ReceiptExists $true -ReceiptStatus PASS -Now $today.AddHours(1) -Deadline $deadline
    Get-WeatherIntegrationSuiteWaitDecision -TaskState Ready -LastRunTime $today.AddMinutes(30) -LastTaskResult 1 -ReceiptExists $true -ReceiptStatus FAIL -Now $today.AddHours(1) -Deadline $deadline
)
@($cases | ForEach-Object { [string]$_.Action }) | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "WAIT",
        "STOP",
        "WAIT",
        "WAIT",
        "STOP",
        "WAIT",
        "STOP",
        "FAIL",
        "READY",
        "READY",
        "READY",
        "WAIT",
        "STOP",
        "WAIT",
        "STOP",
        "FAIL",
        "FAIL",
    ]


def test_suite_receipt_offset_timestamp_flows_into_merge_wait_as_local_time() -> None:
    merge_script = SCRIPTS["integration_attempt_merge.ps1"].read_text(
        encoding="utf-8-sig"
    )
    assert "$validatedPassReceipt.CompletedAtLocal" in merge_script
    assert ").LocalDateTime" in merge_script

    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$completed = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
    -Value '2026-08-24T03:04:05.1234567-04:00' `
    -Label 'suite receipt completed_at_local'
$local = $completed.LocalDateTime
if ($local -ne [datetime]'2026-08-24T03:04:05.1234567') {
    throw 'Suite receipt timestamp did not retain its local wall clock.'
}
'OK'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_log_verdict_helper_executes_and_rejects_false_chunk_ratios(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "suite.log"
    log_path.write_text(
        "2026-08-21 00:30:00  planned chunks=2 files=40 max_files=20\n"
        "2026-08-21 00:45:00  VERDICT: ALL CHUNKS PASSED (2/2); "
        "exact tip eligible for separate reviewed merge\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    env["WEATHER_ATTEMPT_LOG"] = str(log_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$verdict = Get-WeatherIntegrationLogVerdict -Path $env:WEATHER_ATTEMPT_LOG
$chunks = Assert-WeatherIntegrationFullSuiteVerdict -Verdict $verdict -ExpectedChunkCount 2
$plan = Assert-WeatherIntegrationFullSuiteLogPlan `
    -Path $env:WEATHER_ATTEMPT_LOG `
    -ExpectedTestFileCount 40 `
    -ExpectedMaxFilesPerChunk 20 `
    -ExpectedChunkCount 2
$mismatchRejected = $false
try {
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict '2026-08-21 00:45:00  VERDICT: ALL CHUNKS PASSED (1/2); exact tip eligible for separate reviewed merge' | Out-Null
}
catch { $mismatchRejected = $_.Exception.Message -like '*invalid chunk ratio*' }
$zeroRejected = $false
try {
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict '2026-08-21 00:45:00  VERDICT: ALL CHUNKS PASSED (0/0); exact tip eligible for separate reviewed merge' | Out-Null
}
catch { $zeroRejected = $_.Exception.Message -like '*invalid chunk ratio*' }
$prefixedRejected = $false
try {
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict 'JUNK 2026-08-21 00:45:00  VERDICT: ALL CHUNKS PASSED (2/2); exact tip eligible for separate reviewed merge' `
        -ExpectedChunkCount 2 | Out-Null
}
catch { $prefixedRejected = $_.Exception.Message -like '*exact PASS verdict*' }
$preflightAccepted = $true
try {
    Assert-WeatherIntegrationPreflightVerdict `
        -Verdict '2026-08-21 00:31:00  VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized'
}
catch { $preflightAccepted = $false }
$prefixedPreflightRejected = $false
try {
    Assert-WeatherIntegrationPreflightVerdict `
        -Verdict 'JUNK VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized'
}
catch { $prefixedPreflightRejected = $_.Exception.Message -like '*exact PASS verdict*' }
[pscustomobject]@{
    verdict = $verdict
    chunks = $chunks
    planned_files = $plan.Files
    mismatch_rejected = $mismatchRejected
    zero_rejected = $zeroRejected
    prefixed_rejected = $prefixedRejected
    preflight_accepted = $preflightAccepted
    prefixed_preflight_rejected = $prefixedPreflightRejected
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["chunks"] == 2
    assert payload["planned_files"] == 40
    assert payload["verdict"].endswith(
        "VERDICT: ALL CHUNKS PASSED (2/2); "
        "exact tip eligible for separate reviewed merge"
    )
    assert payload["mismatch_rejected"] is True
    assert payload["zero_rejected"] is True
    assert payload["prefixed_rejected"] is True
    assert payload["preflight_accepted"] is True
    assert payload["prefixed_preflight_rejected"] is True


def test_schedule_helper_rejects_invalid_and_ambiguous_eastern_times() -> None:
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(
        SCRIPTS["integration_attempt_contract.ps1"]
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$valid = Assert-WeatherIntegrationLocalScheduleTime `
    -Value ([datetime]'2026-08-21T01:30:00') -Label valid -TimeZone $zone
$invalidRejected = $false
try {
    Assert-WeatherIntegrationLocalScheduleTime `
        -Value ([datetime]'2027-03-14T02:30:00') -Label invalid -TimeZone $zone | Out-Null
}
catch { $invalidRejected = $_.Exception.Message -like '*daylight-saving gap*' }
$ambiguousRejected = $false
try {
    Assert-WeatherIntegrationLocalScheduleTime `
        -Value ([datetime]'2026-11-01T01:30:00') -Label ambiguous -TimeZone $zone | Out-Null
}
catch { $ambiguousRejected = $_.Exception.Message -like '*ambiguous daylight-saving hour*' }
$utcRejected = $false
try {
    ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value '2026-08-21T04:35:00.0000000Z' -Label utc | Out-Null
}
catch { $utcRejected = $_.Exception.Message -like '*must not carry a UTC marker*' }
$offsetRejected = $false
try {
    ConvertFrom-WeatherIntegrationLocalTimestamp `
        -Value '2026-08-21T00:35:00.0000000-04:00' -Label offset | Out-Null
}
catch { $offsetRejected = $_.Exception.Message -like '*must not carry a UTC marker*' }
$directUtcRejected = $false
try {
    Assert-WeatherIntegrationLocalScheduleTime `
        -Value ([datetime]::SpecifyKind([datetime]'2026-08-21T04:35:00', [DateTimeKind]::Utc)) `
        -Label directUtc -TimeZone $zone | Out-Null
}
catch { $directUtcRejected = $_.Exception.Message -like '*without a UTC marker*' }
[pscustomobject]@{
    valid = $valid.ToString('o')
    invalid_rejected = $invalidRejected
    ambiguous_rejected = $ambiguousRejected
    utc_rejected = $utcRejected
    offset_rejected = $offsetRejected
    direct_utc_rejected = $directUtcRejected
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "valid": "2026-08-21T01:30:00.0000000",
        "invalid_rejected": True,
        "ambiguous_rejected": True,
        "utc_rejected": True,
        "offset_rejected": True,
        "direct_utc_rejected": True,
    }


def test_git_baseline_gate_detects_production_advance(tmp_path: Path) -> None:
    repo_root = tmp_path / "baseline-repo"
    subprocess.run(
        ["git", "init", "--initial-branch=master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Integration Test"],
        check=True,
    )
    marker = repo_root / "marker.txt"
    marker.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "marker.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "master"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "update-ref",
            "refs/remotes/origin/master",
            baseline,
        ],
        check=True,
    )
    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_REPO"] = str(repo_root)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$master = (& git -C $env:WEATHER_ATTEMPT_REPO rev-parse master).Trim().ToLowerInvariant()
$origin = (& git -C $env:WEATHER_ATTEMPT_REPO rev-parse origin/master).Trim().ToLowerInvariant()
$contract = [pscustomobject]@{
    Manifest = [pscustomobject]@{
        repo_root = $env:WEATHER_ATTEMPT_REPO
        baseline = [pscustomobject]@{ master = $master; origin_master = $origin }
    }
}
$pass = Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase test
$contract.Manifest.baseline.master = ('0' * 40)
$failed = $false
try { Assert-WeatherIntegrationGitBaseline -AttemptContract $contract -Phase test | Out-Null }
catch { $failed = $_.Exception.Message -like '*baseline changed after attempt freeze*' }
[pscustomobject]@{ pass = ($pass.Master -eq $master); rejected_advance = $failed } | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"pass": True, "rejected_advance": True}


def test_repair_manifest_requires_exact_single_successor_claim(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    prior_root = tmp_path / "prior"
    current_root = tmp_path / "current"
    prior_worktree = tmp_path / "prior-worktree"
    current_worktree = tmp_path / "current-worktree"
    for path in (repo_root, prior_root, current_root, prior_worktree, current_worktree):
        path.mkdir()

    zeros = "0" * 40
    prior_tip = "1" * 40

    def evidence(root: Path) -> dict[str, str]:
        return {
            "preflight_log": str(root / "preflight.log"),
            "full_suite_log": str(root / "full-suite.log"),
            "suite_receipt": str(root / "suite-receipt.json"),
            "merge_receipt": str(root / "merge-receipt.json"),
            "quiet_merge_report": str(root / "quiet-merge-report.json"),
            "registration_receipt": str(root / "registration-receipt.json"),
            "closure_receipt": str(root / "closure-receipt.json"),
            "recovery_dispatch": str(root / "recovery-dispatch.json"),
            "reconciliation_receipt": str(root / "reconciliation-receipt.json"),
        }

    prior_manifest_path = prior_root / "manifest.json"
    prior_manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "prior",
        "attempt_root": str(prior_root),
        "repo_root": str(repo_root),
        "worktree_root": str(prior_worktree),
        "branch_ref": "origin/codex/prior",
        "expected_tip": prior_tip,
        "authorization": {
            "review_reference": "review-prior",
            "repair_class": "initial",
            "repair_of": None,
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_prior",
            "merge_task_name": "WeatherIntegrationMerge_prior",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": evidence(prior_root),
    }
    prior_manifest_path.write_text(json.dumps(prior_manifest), encoding="utf-8")
    prior_manifest_hash = hashlib.sha256(prior_manifest_path.read_bytes()).hexdigest()

    closure_path = prior_root / "closure-receipt.json"
    closure = {
        "schema": "weather_integration_attempt_closure_receipt_v1",
        "status": "FAIL",
        "attempt_id": "prior",
        "manifest_path": str(prior_manifest_path),
        "manifest_sha256": prior_manifest_hash,
    }
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()

    dispatch_path = prior_root / "recovery-dispatch.json"
    dispatch = {
        "schema": "weather_integration_attempt_recovery_dispatch_v1",
        "status": "READY_FOR_SUCCESSOR_REVIEW",
        "repair_class": "retry_unchanged",
        "closure_receipt_path": str(closure_path),
        "closure_receipt_sha256": closure_hash,
    }
    dispatch_path.write_text(json.dumps(dispatch), encoding="utf-8")
    dispatch_hash = hashlib.sha256(dispatch_path.read_bytes()).hexdigest()

    claim_path = prior_root / "successor-claim.json"
    current_manifest_path = current_root / "manifest.json"
    current_manifest = {
        "schema": "weather_integration_attempt_manifest_v1",
        "attempt_id": "current",
        "attempt_root": str(current_root),
        "repo_root": str(repo_root),
        "worktree_root": str(current_worktree),
        "branch_ref": "origin/codex/prior",
        "expected_tip": prior_tip,
        "authorization": {
            "review_reference": "review-current",
            "repair_class": "retry_unchanged",
            "repair_of": {
                "receipt_path": str(closure_path),
                "receipt_sha256": closure_hash,
                "receipt_schema": "weather_integration_attempt_closure_receipt_v1",
                "prior_attempt_id": "prior",
                "claim_path": str(claim_path),
                "dispatch_path": str(dispatch_path),
                "dispatch_sha256": dispatch_hash,
            },
        },
        "schedule": {
            "suite_at_local": "2026-08-21T00:30:00",
            "merge_at_local": "2026-08-21T01:00:00",
            "suite_task_name": "WeatherIntegrationSuite_current",
            "merge_task_name": "WeatherIntegrationMerge_current",
        },
        "suite": {
            "additional_python_path": "",
            "require_live_sdk_contract": False,
            "expected_test_file_count": 40,
            "max_files_per_chunk": 20,
            "expected_chunk_count": 2,
        },
        "baseline": {"master": zeros, "origin_master": zeros},
        "evidence": evidence(current_root),
    }
    current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    current_manifest_hash = hashlib.sha256(current_manifest_path.read_bytes()).hexdigest()
    claim = {
        "schema": "weather_integration_attempt_successor_claim_v1",
        "status": "CLAIMED",
        "predecessor_receipt_path": str(closure_path),
        "predecessor_receipt_sha256": closure_hash,
        "recovery_dispatch_path": str(dispatch_path),
        "recovery_dispatch_sha256": dispatch_hash,
        "successor_manifest_path": str(current_manifest_path),
        "successor_manifest_sha256": current_manifest_hash,
        "successor_attempt_id": "current",
        "successor_expected_tip": prior_tip,
        "repair_class": "retry_unchanged",
    }
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    env = os.environ.copy()
    env["WEATHER_ATTEMPT_CONTRACT"] = str(SCRIPTS["integration_attempt_contract.ps1"])
    env["WEATHER_ATTEMPT_MANIFEST"] = str(current_manifest_path)
    env["WEATHER_ATTEMPT_MANIFEST_HASH"] = current_manifest_hash
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$result = Assert-WeatherIntegrationAttemptManifest `
    -ManifestPath $env:WEATHER_ATTEMPT_MANIFEST `
    -ExpectedSha256 $env:WEATHER_ATTEMPT_MANIFEST_HASH
Assert-WeatherIntegrationRepairClaim -AttemptContract $result
[string]$result.Manifest.attempt_id
"""
    accepted = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "current"

    claim["successor_expected_tip"] = "2" * 40
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    rejected = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "successor claim does not bind" in rejected.stderr.lower()


def test_repair_tip_policy_rejects_equal_tree_commit_and_claim_write_is_atomic(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "candidate-worktree"
    attempt_parent = tmp_path / "attempts"
    repo_root.mkdir()
    attempt_parent.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=master", str(repo_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Integration Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "remote",
            "add",
            "origin",
            "https://github.com/example/weather.git",
        ],
        check=True,
    )
    temp_ops = repo_root / "scripts" / "ops"
    temp_ops.mkdir(parents=True)
    required = (
        "integration_attempt_contract.ps1",
        "integration_attempt_remote_git.ps1",
        "new_integration_attempt.ps1",
        "register_integration_attempt.ps1",
        "close_integration_attempt.ps1",
        "bounded_worktree_test_suite.ps1",
        "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1",
        "activate_integration_attempt.ps1",
        "integration_attempt_quiet_merge_preflight.ps1",
        "assert_integration_attempt_success.ps1",
        "dispatch_integration_attempt_recovery.ps1",
        "quiet_window_merge.ps1",
        "training_window_contract.ps1",
        "windows_kill_on_close_job.ps1",
        "workload_admission.ps1",
        "roll_verdict.ps1",
        "boot_recovery.ps1",
        "register_boot_recovery.ps1",
    )
    for name in required:
        shutil.copy2(OPS / name, temp_ops / name)
    temp_tests = repo_root / "tests"
    temp_tests.mkdir()
    (temp_tests / "test_example.py").write_text(
        "def test_example():\n    assert True\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "scripts", "tests"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "update-ref",
            "refs/remotes/origin/master",
            baseline,
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "update-ref",
            "refs/remotes/origin/candidate",
            baseline,
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "candidate", baseline],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", str(worktree_root), "candidate"],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        ["git", "-C", str(worktree_root), "commit", "--allow-empty", "-m", "empty"],
        check=True,
        capture_output=True,
        text=True,
    )
    empty_tip = subprocess.run(
        ["git", "-C", str(worktree_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    baseline_tree = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{baseline}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    empty_tree = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{empty_tip}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert baseline_tree == empty_tree

    claim_root = tmp_path / "claim-root"
    claim_root.mkdir()
    claim_path = claim_root / "successor-claim.json"
    env = os.environ.copy()
    env.update(
        {
            "WEATHER_ATTEMPT_CONTRACT": str(SCRIPTS["integration_attempt_contract.ps1"]),
            "WEATHER_PRIOR_TIP": baseline,
            "WEATHER_EMPTY_TIP": empty_tip,
            "WEATHER_CLAIM_PATH": str(claim_path),
        }
    )
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ATTEMPT_CONTRACT
$equalTreeRejected = $false
try {
    Assert-WeatherIntegrationRepairTipPolicy `
        -PriorTip $env:WEATHER_PRIOR_TIP `
        -ExpectedTip $env:WEATHER_EMPTY_TIP `
        -PriorIsAncestor $true `
        -RepairClass retry_unchanged `
        -ChangeRows @() | Out-Null
}
catch {
    $equalTreeRejected = $_.Exception.Message -like '*exact same commit id*'
}
Assert-WeatherIntegrationRepairTipPolicy `
    -PriorTip $env:WEATHER_PRIOR_TIP `
    -ExpectedTip $env:WEATHER_PRIOR_TIP `
    -PriorIsAncestor $true `
    -RepairClass retry_unchanged `
    -ChangeRows @() | Out-Null
Write-WeatherIntegrationImmutableJson `
    -Path $env:WEATHER_CLAIM_PATH `
    -Payload ([ordered]@{ successor_expected_tip = $env:WEATHER_PRIOR_TIP })
$secondClaimRefused = $false
try {
    Write-WeatherIntegrationImmutableJson `
        -Path $env:WEATHER_CLAIM_PATH `
        -Payload ([ordered]@{ successor_expected_tip = $env:WEATHER_EMPTY_TIP })
}
catch {
    $secondClaimRefused = $_.Exception.Message -like '*will not be replaced*'
}
[pscustomobject]@{
    equal_tree_rejected = $equalTreeRejected
    exact_retry_accepted = $true
    second_claim_refused = $secondClaimRefused
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "equal_tree_rejected": True,
        "exact_retry_accepted": True,
        "second_claim_refused": True,
    }
    assert json.loads(claim_path.read_text(encoding="utf-8")) == {
        "successor_expected_tip": baseline
    }


def test_integration_attempt_powershell_sources_parse_without_execution() -> None:
    env = os.environ.copy()
    env["WEATHER_INTEGRATION_ATTEMPT_SCRIPTS"] = os.pathsep.join(
        str(path) for path in PARSE_SCRIPTS
    )
    script = r"""
$ErrorActionPreference = 'Stop'
$paths = @($env:WEATHER_INTEGRATION_ATTEMPT_SCRIPTS.Split([IO.Path]::PathSeparator))
$allErrors = @()
$operatorParameters = @()
$operatorNames = @(
    'split', 'replace', 'match', 'notmatch', 'like', 'notlike', 'eq', 'ne',
    'gt', 'ge', 'lt', 'le', 'join', 'contains', 'notcontains', 'in', 'notin',
    'is', 'isnot', 'as', 'f', 'shl', 'shr', 'band', 'bor', 'bxor',
    'and', 'bnot', 'ccontains', 'ceq', 'cge', 'cgt', 'cin', 'cle', 'clike',
    'clt', 'cmatch', 'cne', 'cnotcontains', 'cnotin', 'cnotlike', 'cnotmatch',
    'creplace', 'csplit', 'icontains', 'ieq', 'ige', 'igt', 'iin', 'ile',
    'ilike', 'ilt', 'imatch', 'ine', 'inotcontains', 'inotin', 'inotlike',
    'inotmatch', 'ireplace', 'isplit', 'not', 'or', 'xor'
)
foreach ($path in $paths) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $path,
        [ref]$tokens,
        [ref]$errors
    )
    foreach ($item in @($errors)) {
        $allErrors += [pscustomobject]@{ path = $path; message = $item.Message }
    }
    $badParameters = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandParameterAst] -and
            $operatorNames -contains $node.ParameterName.ToLowerInvariant()
    }, $true))
    foreach ($item in $badParameters) {
        $operatorParameters += [pscustomobject]@{
            path = $path
            line = $item.Extent.StartLineNumber
            parameter = $item.ParameterName
        }
    }
}
$controlTokens = $null
$controlErrors = $null
$controlAst = [System.Management.Automation.Language.Parser]::ParseInput(
    'Read-Example -Path x -ireplace y',
    [ref]$controlTokens,
    [ref]$controlErrors
)
$controlHits = @($controlAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandParameterAst] -and
        $operatorNames -contains $node.ParameterName.ToLowerInvariant()
}, $true))
[pscustomobject]@{
    errors = $allErrors
    operator_parameters = $operatorParameters
    positive_control_parameters = @($controlHits | ForEach-Object { $_.ParameterName })
} | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert payload["operator_parameters"] == []
    assert payload["positive_control_parameters"] == ["ireplace"]
