import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_quiet_merge_can_bind_a_reviewed_exact_tip() -> None:
    script = _script_text()

    assert '[string]$ExpectedTip = ""' in script
    assert "$RepoRoot = (Split-Path -Parent" in script
    assert "$repo = (Resolve-Path -LiteralPath $RepoRoot" in script
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
    merge = script.index("& git merge --no-ff $mergeTarget")

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


def test_documentation_transaction_is_bound_before_publication() -> None:
    script = _script_text()

    begin = script.index('"-m", "weather.operations.documentation_transaction"')
    push = script.index("Start-ScheduledTask -TaskName WeatherOneShotPush")
    assert begin < push
    assert '"--integration-tip", $mergeCommit' in script
    assert '"--branch", $Branch' in script
    assert 'Save-Report -ok $true -stage "merged_unpushed"' in script
    assert "& git push" not in script.lower()
    assert "git rev-parse origin/master" in script


def test_failed_merge_proves_rollback_readoption_before_reporting_rolled_back() -> None:
    script = _script_text()

    reset = script.index("& git reset --hard $preMerge")
    rollback_wait = script.index("$rollbackDeadline = (Get-Date).AddSeconds")
    rollback_proof = script.index(
        'Note "all three workers re-adopted the rollback and satisfy the capture recovery contract"'
    )
    rolled_back = script.index('Save-Report -ok $false -stage "rolled_back"')

    assert "[ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200" in script
    assert 'Save-Report -ok $false -stage "rollback_recovery_failed"' in script
    assert reset < rollback_wait < rollback_proof < rolled_back
