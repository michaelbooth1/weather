from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_quiet_merge_can_bind_a_reviewed_exact_tip() -> None:
    script = _script_text()

    assert '[string]$ExpectedTip = ""' in script
    assert "ExpectedTip must be a full 40-character hexadecimal commit SHA" in script
    assert "$verdictRef = $(if ($ExpectedTip) { $ExpectedTip } else { $Branch })" in script
    assert "if ($resolvedBranchTip -ne $ExpectedTip)" in script
    assert "$mergeTarget = $resolvedBranchTip" in script
    assert "& git merge --no-ff $mergeTarget" in script


def test_exact_tip_guard_precedes_any_automatic_commit_or_merge() -> None:
    script = _script_text()

    guard = script.index("if ($resolvedBranchTip -ne $ExpectedTip)")
    automatic_commit = script.index('Note "committing $($dirtyTracked.Count)')
    merge = script.index("& git merge --no-ff $mergeTarget")

    assert guard < automatic_commit < merge


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
    assert "heartbeat did not advance" in script
    assert "Get-CimInstance Win32_Process" not in script


def test_publish_uses_only_the_credential_bearing_scheduled_task() -> None:
    script = _script_text()

    assert "Start-ScheduledTask -TaskName WeatherOneShotPush" in script
    assert "& git push" not in script.lower()
    assert "git rev-parse origin/master" in script
