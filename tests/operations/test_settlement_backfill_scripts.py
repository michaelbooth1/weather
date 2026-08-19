from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    return (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8")


def test_settlement_backfill_uses_exact_terminal_step_and_no_bare_lock_guard():
    text = _script("settlement_backfill_one.ps1")

    assert "'-StopAfter', 'market_day_labels_finalize'" in text
    assert "if (Test-Path $lock)" not in text
    assert "target_date_present_substring" in text
    assert "Test-RowSettled" in text


def test_chain_recovery_repairs_locks_canonically_and_validates_bounded_receipt():
    text = _script("chain_recovery_run.ps1")

    assert '$repairArgs = @(\n    "repair-stale-locks"' in text
    assert "Get-WeatherHeavyWorkloadPolicyWindow" in text
    assert "Force cannot bypass host load policy" in text
    assert "Test-ProcessIsSelfOrAncestor" in text
    assert 'workloadLeaseMode = "inherited_ancestor"' in text
    assert "Exit-WeatherHeavyWorkloadLease" in text
    assert "New-WeatherKillOnCloseJob" in text
    assert "Start-WeatherProcessInJob" in text
    assert "$resumeRows.Count -eq 1" in text
    assert "$stopRows.Count -eq 1" in text
    assert '"--stop-after-step", $StopAfter' in text
    assert "$refresh.bounded_recovery" in text
    assert "$bounded.terminal_step_status -eq 'ok'" in text
    assert "exit $exit" in text
