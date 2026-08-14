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
    assert "suite log predates the task run" in text
    assert "suite log run boundary does not correlate to LastRunTime" in text


def test_suite_gate_rejects_partial_or_failed_receipts_before_merge() -> None:
    text = _script_text()

    refusal = text.index('if ($runLines -match "CHUNK\\(S\\) FAILED|SMOKE PASSED|PREFLIGHT PASSED")')
    exact_pass = text.index("VERDICT: ALL CHUNKS PASSED")
    invoke = text.index("& $mergeScript -Branch $Branch")

    assert refusal < exact_pass < invoke
    assert "suite log does not end in the exact full-suite pass verdict" in text
    assert "-ExpectedTip $ExpectedTip" in text


def test_suite_gate_never_merges_or_pushes_directly() -> None:
    text = _script_text().lower()

    assert "git merge" not in text
    assert "git push" not in text
    assert "quiet_window_merge.ps1" in text
