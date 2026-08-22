from pathlib import Path
import json
import os
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"


def _text(name: str) -> str:
    return (OPS / name).read_text(encoding="utf-8-sig")


def test_immutable_suite_rejects_ambient_imports_and_rechecks_final_identity() -> None:
    suite = _text("integration_attempt_suite.ps1")
    bounded = _text("bounded_worktree_test_suite.ps1")

    assert "AdditionalPythonPath is unsupported for immutable integration attempts" in suite
    assert "Assert-WeatherIntegrationAttemptTaskBinding" in suite
    assert '-Role "suite"' in suite
    assert 'State -ne "Running"' in suite
    assert 'Assert-WeatherAttemptSuiteWorktreeState -Phase "full-suite completion"' in suite
    assert 'Assert-WeatherIntegrationOrchestrationFiles -AttemptContract $contract' in suite

    # The compatibility runner still supports reviewed diagnostics outside an
    # immutable attempt, but its merge-eligible verdict gets a final recheck.
    assert "$AdditionalPythonPath.Split([IO.Path]::PathSeparator)" in bounded
    assert "exact branch/worktree identity changed while the suite was running" in bounded
    assert "suite worktree changed while the suite was running" in bounded
    assert "tracked pytest inventory changed while the suite was running" in bounded
    assert "@(Compare-Object -ReferenceObject" in bounded
    assert bounded.index("final exact-tip, clean-worktree, and test-inventory recheck passed") < bounded.index(
        "VERDICT: ALL CHUNKS PASSED"
    )


def test_merge_writes_attempt_report_directly_and_recovery_is_non_authorizing() -> None:
    merge = _text("integration_attempt_merge.ps1")
    reconcile = _text("reconcile_integration_attempt.ps1")
    close = _text("close_integration_attempt.ps1")

    assert '"-AttemptReportPath", $AttemptReportPath' in merge
    assert "-AttemptReportPath $attemptQuietReportPath" in merge
    assert "quiet_window_merge_report_v0.2" in merge
    assert "execution_tape_recovery_required" in merge
    assert "publication_acknowledged" in merge
    assert "Write-WeatherIntegrationImmutableJson -Path $attemptQuietReportPath" not in merge

    assert "ExpectedMergeReceiptSha256" in reconcile
    assert "ExpectedQuietMergeReportSha256" in reconcile
    assert "ExpectedActiveMarkerSha256" in reconcile
    assert '"documented_unpublished", "published"' in reconcile
    assert "failed_merge_receipt" in reconcile
    assert 'stage -ne "merged_unpushed"' in reconcile
    assert "ResumePublication" in reconcile
    assert '"merge_committed_unpublished"' in reconcile
    assert "weather.operations.documentation_transaction" in reconcile
    assert 'Start-ScheduledTask -TaskName "WeatherOneShotPush"' in reconcile
    assert "exact two-parent merge" in reconcile
    assert "execution_tape_supervisor status" in reconcile
    assert "Assert-WeatherReconciliationOneShotPushTask" in reconcile
    assert "enabled current-user Interactive/Limited git-push contract" in reconcile
    assert "supporting_active_marker_sha256" in reconcile
    assert "unique subset of the two generated-config drifts" in reconcile
    assert "Generated-config drift content does not match" not in reconcile
    assert "documentation_transaction_pending_sha256" in reconcile
    assert "documentation_transaction_snapshot_path" in reconcile
    assert "HEAD == master == origin/master == the hash-bound merge_commit" in reconcile
    assert "active_marker_raw" in reconcile
    assert "historical_proof_upgraded = $false" in reconcile
    assert "downstream_authorized = $false" in reconcile
    assert "registrationIntentSha256" in reconcile
    assert "[IO.File]::ReadAllBytes($markerPath)" in reconcile
    assert "execution_tape_readoption_expected" in reconcile
    assert "repo_root = [string]$marker.repo_root" in reconcile
    assert "Assert-WeatherReconciliationResumeEvidenceBoundary" in reconcile
    assert "Hash-bound immutable publication report changed" in reconcile
    assert "Current active marker changed" in reconcile
    assert "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05" in reconcile
    assert "Export-ScheduledTask" in reconcile
    assert "$pushTask.Triggers | Where-Object { $null -ne $_ }" in reconcile
    assert "Assert-WeatherReconciliationPriorMarkerAbortReport" in reconcile
    assert "supporting_prior_marker_abort_sha256" in reconcile
    published_selection = reconcile.index("$publishedIntegrationCommit = if")
    active_selection = reconcile.index("$null -ne $activeMarkerContract", published_selection)
    merge_selection = reconcile.index("$null -ne $mergeReceipt", active_selection)
    assert published_selection < active_selection < merge_selection

    assert "Get-WeatherIntegrationRegistrationIntentPath" in close
    assert "quiet_window_merge_in_progress.json" in close
    assert "Durable recovery evidence proves this attempt created a recovered integration commit" in close
    assert "Do not close or retry it" in close
    # Even if the parent and child died before writing terminal evidence,
    # ordinary closure must prove the source is absent at the frozen baseline.
    assert "if ($null -ne $quietReportContract -or $null -ne $activeMarker)" not in close
    assert close.count("merge-base --is-ancestor ([string]$attempt.expected_tip)") == 2
    assert "A missing terminal report is not evidence" in close
    assert "Assert-WeatherClosureTasksQuiescent" in close
    assert "post_disable_proof" in close
    assert "merge_head_absent = $true" in close
    assert close.count("Assert-WeatherClosureNonIntegratedState -AttemptContract $contract") == 2
    assert 'stage -in @(\"pushed\", \"merged_unpushed\")' in close
    disable_index = close.index("$taskEvidence = @(Disable-WeatherIntegrationAttemptTasks")
    quiescent_index = close.index("Assert-WeatherClosureTasksQuiescent", disable_index)
    post_git_index = close.index(
        "$postDisableGitProof = Assert-WeatherClosureNonIntegratedState", quiescent_index
    )
    receipt_index = close.index("Write-WeatherIntegrationImmutableJson -Path $closurePath")
    assert disable_index < quiescent_index < post_git_index < receipt_index
    assert "$postDisableQuietReport = Read-WeatherClosureQuietReport" in close
    assert "Merge evidence appeared or changed during task shutdown" in close
    assert "reconciliation receipt already terminally classified" in close
    assert "closure receipt already terminally abandoned" in reconcile
    assert 'LockLeaf "integration_attempt_terminal.lock"' in close
    assert 'LockLeaf "heavy_workload.lock"' in close
    assert 'LockLeaf "integration_attempt_terminal.lock"' in reconcile
    mutex_index = close.index("$terminalMutex = Enter-WeatherIntegrationControlMutex")
    repeated_terminal_check = close.index(
        "A reconciliation receipt appeared before terminal-mutex acquisition", mutex_index
    )
    shared_git_mutex = close.index('LockLeaf "heavy_workload.lock"', repeated_terminal_check)
    assert mutex_index < repeated_terminal_check < shared_git_mutex < disable_index
    reconcile_terminal_mutex = reconcile.index(
        '-Owner "reconcile_integration_attempt:$($manifest.attempt_id)"'
    )
    reconcile_shared_mutex = reconcile.index(
        'LockLeaf "heavy_workload.lock"', reconcile_terminal_mutex
    )
    reconcile_classification = reconcile.index("$reconciliationPath =", reconcile_shared_mutex)
    reconcile_final_head = reconcile.index("$productionHead = Invoke-WeatherReconciliationGitLine", reconcile_classification)
    reconcile_receipt = reconcile.index(
        "Write-WeatherIntegrationImmutableJson -Path $reconciliationPath", reconcile_final_head
    )
    reconcile_mutex_release = reconcile.index(
        "Exit-WeatherIntegrationControlMutex -Mutex $reconciliationGitMutex",
        reconcile_receipt,
    )
    assert (
        reconcile_terminal_mutex
        < reconcile_shared_mutex
        < reconcile_classification
        < reconcile_final_head
        < reconcile_receipt
        < reconcile_mutex_release
    )
    assert "Get-WeatherHeavyWorkloadPolicyWindow" in reconcile
    assert "Enter-WeatherHeavyWorkloadLease" not in reconcile

    contract = _text("integration_attempt_contract.ps1")
    registrar = _text("register_integration_attempt.ps1")
    suite = _text("integration_attempt_suite.ps1")
    assert "Enter-WeatherIntegrationControlMutex" in contract
    assert 'LockLeaf "integration_attempt_terminal.lock"' in registrar
    assert registrar.index('LockLeaf "integration_attempt_terminal.lock"') < registrar.index(
        "Write-WeatherIntegrationImmutableJson -Path $registrationIntentPath"
    )
    assert "Assert-WeatherIntegrationAttemptNotTerminal" in registrar
    assert "Assert-WeatherIntegrationAttemptNotTerminal" in suite
    assert "Assert-WeatherIntegrationAttemptNotTerminal" in merge

    # A post-commit journal with no child report must outrank a generic FAIL
    # receipt; otherwise marker-only recovery becomes unreachable.
    assert "Get-WeatherIntegrationRecoverableActiveMarker" in merge
    assert "Withholding generic FAIL receipt" in merge
    assert "if ($null -eq $deferredMergeReceiptMarker -and" in merge
    assert "preserveQuietReportForReconciliation" in merge
    exact_report_head = merge.index(
        "([string]$quietReport.merge_commit).ToLowerInvariant() -eq $productionHead"
    )
    merged_unverified = merge.index('$status = "MERGED_UNVERIFIED"', exact_report_head)
    receipt_write = merge.index(
        "Write-WeatherIntegrationImmutableJson -Path $mergeReceiptPath", merged_unverified
    )
    assert exact_report_head < merged_unverified < receipt_write
    assert "the only exact publication evidence; reconcile that report" in merge


def test_status_and_downstream_gate_validate_structure_and_checked_out_master() -> None:
    status = _text("status.ps1")
    downstream = _text("assert_integration_attempt_success.ps1")

    assert "Get-WeatherIntegrationValidatedEvidence" in status
    assert "Assert-WeatherIntegrationSuiteReceipt" in status
    assert "Assert-WeatherIntegrationMergeReceipt" in status
    assert "Assert-WeatherIntegrationMergedUnverifiedReceipt" in status
    assert "registration_intent" in status
    assert "embedded active-marker hash is invalid" in status
    assert 'publicationKind -eq "failed_merge_receipt"' in status
    assert "markerWasResumedBeforeDocumentation" in status
    assert "Publication-resume final marker" in status
    assert 'if ($ReconciliationStatus -eq "MERGED_RECONCILED")' in status
    assert "task-binding drift" in status
    assert "observedIntegrationAttemptManifests" in status
    assert "quiet_window_merge_in_progress.json" in status
    assert "STALE $quietMarkerDetail" in status
    assert "quiet-window merge committed locally but NOT pushed" in status
    assert '$flags.Add("quiet-window merge committed locally but NOT pushed' in status
    assert '-Target "suite"' in status  # race re-read is strictly revalidated

    assert 'productionBranch -ne "master"' in downstream
    assert "$headTip -ne $masterTip" in downstream
    assert "$masterTip -ne $originMasterTip" in downstream
    assert "quiet_window_merge_report_v0.2" in downstream
    assert "execution_tape_recovery_required" in downstream
    assert "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" in downstream
    assert "documentation_transaction_pending_sha256" in downstream
    assert "exact immutable documentation transaction snapshot" in downstream


def test_integration_preflight_includes_all_new_recovery_ratchets() -> None:
    bounded = _text("bounded_worktree_test_suite.ps1")

    for relative_path in (
        "tests/operations/test_integration_attempt_evidence_recovery_hardening.py",
        "tests/operations/test_integration_attempt_registration_safety.py",
        "tests/operations/test_boot_recovery_script.py",
    ):
        assert relative_path in bounded


def test_boot_recovery_uses_exact_worker_proof_for_the_primary_verdict() -> None:
    boot = _text("boot_recovery.ps1")

    proof = boot.index("function Test-BootExactCaptureRecovery")
    verdict = boot.index("$recovered = Test-BootExactCaptureRecovery", proof)
    retry = boot.index("-and -not $recovered", verdict)
    record = boot.index("capture_recovered = $recovered", retry)
    assert "weather.operations.capture_recovery_check" in boot[proof:verdict]
    assert "@($captureProof.workers).Count -eq 3" in boot[proof:verdict]
    assert "diagnostic only" in boot[verdict:record]
    assert "$recovered = ($loops -ge 3)" not in boot
    assert proof < verdict < retry < record


def test_equal_final_inventory_is_strict_mode_safe() -> None:
    probe = r"""
Set-StrictMode -Version Latest
$testFiles = @('tests/a.py', 'tests/b.py')
$finalTestFiles = @('tests/a.py', 'tests/b.py')
if ($finalTestFiles.Count -ne $testFiles.Count -or
    @(Compare-Object -ReferenceObject @($testFiles) -DifferenceObject @($finalTestFiles)).Count -ne 0) {
    throw 'identical inventories were classified as drift'
}
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_documentation_begin_is_idempotent_across_marker_write_kill() -> None:
    documentation = (
        ROOT / "src" / "weather" / "operations" / "documentation_transaction.py"
    ).read_text(encoding="utf-8")
    reconcile = _text("reconcile_integration_attempt.ps1")

    assert 'if not any(entry["integration_tip"] == integration_tip' in documentation
    assert "_atomic_json(paths[\"pending\"], pending)" in documentation
    assert "marker had not recorded it" not in reconcile  # marker false is not treated as absence
    assert "may have durably begun documentation" in reconcile
    assert "documentationPayload.pending_sha256" in reconcile
    assert "pending-$documentationPendingSha256.json" in reconcile


def test_changed_recovery_powershell_parses() -> None:
    names = [
        "integration_attempt_merge.ps1",
        "close_integration_attempt.ps1",
        "reconcile_integration_attempt.ps1",
        "status.ps1",
        "assert_integration_attempt_success.ps1",
        "integration_attempt_suite.ps1",
        "bounded_worktree_test_suite.ps1",
        "boot_recovery.ps1",
    ]
    env = os.environ.copy()
    env["WEATHER_RECOVERY_PS_FILES"] = json.dumps([str(OPS / name) for name in names])
    probe = r"""
$ErrorActionPreference = 'Stop'
$result = @()
foreach ($path in (ConvertFrom-Json $env:WEATHER_RECOVERY_PS_FILES)) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $path, [ref]$tokens, [ref]$errors
    )
    $result += [pscustomobject]@{
        path = $path
        errors = @($errors | ForEach-Object { $_.Message })
    }
}
$result | ConvertTo-Json -Depth 5 -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert all(row["errors"] == [] for row in payload), payload
