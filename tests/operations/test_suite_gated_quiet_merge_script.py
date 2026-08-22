from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "suite_gated_quiet_merge.ps1"
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_suite_gate_binds_task_action_result_log_and_exact_tip() -> None:
    text = _script_text()

    assert "[string]$ExpectedTip" in text
    assert "[string]$SuiteTaskName" in text
    assert "[string]$SuiteLogPath" in text
    assert "suite task is still running" in text
    assert "suite task did not run on the current local day" in text
    assert "LastTaskResult -ne 0" in text
    assert "bounded_worktree_test_suite.ps1" in text
    assert "$tipPattern" in text
    assert "$branchPattern" in text
    assert "$logPattern" in text
    assert "$worktreePattern" in text
    assert "suite log predates the task run" in text
    assert "suite log run boundary does not correlate to LastRunTime" in text
    assert "suite-gate script changed after task freeze" in text
    assert "quiet-window merge wrapper changed after task freeze" in text
    assert "production baseline or checked-out master changed after suite freeze" in text
    assert "suite task principal or fail-closed settings changed after freeze" in text
    assert "suite task trigger changed after freeze" in text
    assert "suite task definition changed after freeze" in text
    assert "suite task executable or working directory changed after freeze" in text


def test_suite_gate_rejects_partial_or_failed_receipts_before_merge() -> None:
    text = _script_text()

    refusal = text.index('if ($runLines -match "CHUNK\\(S\\) FAILED|SMOKE PASSED|PREFLIGHT PASSED")')
    exact_pass = text.index("VERDICT: ALL CHUNKS PASSED")
    invoke = text.index("& $mergeScript @mergeArgs")

    assert refusal < exact_pass < invoke
    assert "suite log does not end in the exact full-suite pass verdict" in text
    assert "ExpectedTip = $ExpectedTip" in text
    assert 'Groups["passed"].Value -ne [int]$verdictMatch.Groups["planned"].Value' in text


def test_suite_gate_never_merges_or_pushes_directly() -> None:
    text = _script_text().lower()

    assert "git merge" not in text
    assert "git push" not in text
    assert "quiet_window_merge.ps1" in text


def test_suite_gate_can_bootstrap_a_hash_bound_fixed_merge_wrapper() -> None:
    text = _script_text()

    assert '[string]$QuietMergeScriptPath = ""' in text
    assert '[string]$ExpectedGateSha256 = ""' in text
    assert '[string]$ExpectedQuietMergeSha256 = ""' in text
    assert '[string]$ExpectedSuiteTaskXmlSha256 = ""' in text
    assert '[string]$AttemptReportPath = ""' in text
    assert '[string]$ExpectedSuiteAtLocal = ""' in text
    assert '[ValidateRange(0, 120)][int]$SuiteRunningWaitMinutes = 0' in text
    assert "$mergeArgs.ExpectedBaseline = $ExpectedBaseline" in text
    assert "$mergeArgs.AttemptReportPath = $AttemptReportPath" in text
    assert "$mergeArgs.ExpectedSelfSha256 = $ExpectedQuietMergeSha256" in text
    assert "attempt-specific quiet-merge report already exists" in text
    assert "Export-ScheduledTask" in text


def test_suite_gate_can_wait_boundedly_for_running_suite_and_rebinds_it() -> None:
    text = _script_text()

    assert "$suiteWaitDeadline = (Get-Date).AddMinutes($SuiteRunningWaitMinutes)" in text
    assert "Start-Sleep -Seconds 15" in text
    assert "suite task remained running past the bounded wait" in text
    assert "suite task identity changed while waiting" in text
    assert "$postWaitSuiteTaskXmlSha256 -ne $ExpectedSuiteTaskXmlSha256" in text
    assert "$postWaitWorktreeTip" in text
    assert "$postWaitWorktreeDirty.Count -ne 0" in text
    assert text.index("$postWaitWorktreeTip") < text.index(
        "if (-not (Test-Path -LiteralPath $SuiteLogPath"
    )


def test_suite_gate_invokes_quiet_merge_with_named_splatting() -> None:
    text = _script_text()

    assert "$mergeArgs = @{" in text
    assert "Branch = $Branch" in text
    assert "ExpectedTip = $ExpectedTip" in text
    assert "RepoRoot = $repo" in text
    assert "SettleSeconds = $SettleSeconds" in text
    assert "& $mergeScript @mergeArgs" in text
    assert '$mergeArgs = @(\n' not in text
