from pathlib import Path

from weather.market.market_registry import all_specs


REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    return (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8")


def test_settlement_backfill_uses_exact_terminal_step_and_no_bare_lock_guard():
    text = _script("settlement_backfill_one.ps1")

    assert "'-StopAfter', 'market_day_labels_finalize'" in text
    assert "if (Test-Path $lock)" not in text
    assert "$source -ne 'daily_summary'" in text
    assert "authoritative daily_summary settlement" in text
    assert "weather.market.market_registry" in text
    assert "m.all_specs()" in text
    assert "observedModule -eq $expectedModule" in text
    assert "foreach ($marketId in $expectedMarketIds)" in text
    assert "expected_market_ids" in text
    assert "expected_market_count" in text
    assert "missing_ledger_markets" in text
    assert "Get-ChildItem -Path (Join-Path $RepoRoot 'data\\settlements')" not in text
    assert "target_date_present_substring" in text
    assert "Test-RowSettled" in text


def test_authoritative_market_registry_ids_are_nonempty_unique_and_path_safe():
    ids = [spec.id for spec in all_specs()]

    assert ids
    assert len(ids) == len(set(ids))
    assert all(value and value.replace("-", "").isalnum() for value in ids)


def test_chain_recovery_repairs_locks_canonically_and_validates_bounded_receipt():
    text = _script("chain_recovery_run.ps1")

    assert '$repairArgs = @(\n    "repair-stale-locks"' in text
    assert "Get-WeatherHeavyWorkloadPolicyWindow" in text
    assert "Force cannot bypass host load policy" in text
    assert ".Date.AddHours(9)" in text
    assert "$remainingMilliseconds -le 0" in text
    assert "return 75" in text
    assert "Test-ProcessIsSelfOrAncestor" in text
    assert 'workloadLeaseMode = "inherited_ancestor"' in text
    assert "Exit-WeatherHeavyWorkloadLease" in text
    assert "New-WeatherKillOnCloseJob" in text
    assert "Start-WeatherProcessInJob" in text
    assert "$resumeRows.Count -eq 1" in text
    assert "$stopRows.Count -eq 1" in text
    assert "canonical cleanup or physical lock-absence verification failed" in text
    assert "lock_release_verified" in text
    assert "$exit -ne 75 -and (Get-Date) -lt $script:hardStopLocal" in text
    assert 'postLockCleanupStatus = "SKIPPED_HARD_DEADLINE"' in text
    assert "if ($exit -eq 0) { $exit = 75 }" in text
    assert "Test-Path -LiteralPath $dailyLockPath" in text
    assert "Test-Path -LiteralPath $longJobLockPath" in text
    assert '"--stop-after-step", $StopAfter' in text
    assert "$refresh.bounded_recovery" in text
    assert "$bounded.terminal_step_status -eq 'ok'" in text
    assert "exit $exit" in text
