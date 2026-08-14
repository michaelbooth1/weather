from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_recurring_maker_tasks_share_repo_owned_paper_wrapper() -> None:
    wrapper = (ROOT / "scripts" / "ops" / "market_making_daily_roll_task.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert 'if ($Mode -ne "paper-live-forward")' in wrapper
    assert '"quote_size=$QuoteSize"' in wrapper
    assert '"max_band_notional=$MaxBandNotional"' in wrapper
    assert '"max_event_notional=$MaxEventNotional"' in wrapper
    assert "BelowNormal" in wrapper
    for name in (
        "register_market_making_daily_roll.ps1",
        "register_market_making_daily_roll_supervisor.ps1",
    ):
        text = (ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "market_making_daily_roll_task.ps1" in text
        assert '"powershell.exe"' in text


def test_merge_queue_requires_full_sha_approval_and_passes_expected_tip() -> None:
    text = (ROOT / "scripts" / "ops" / "merge_queue_driver.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "weather_exact_tip_merge_queue_v1" in text
    assert "^[0-9a-f]{40}$" in text
    assert "if (-not [bool]$entry.approved)" in text
    assert "Validate every entry before allowing the first merge" in text
    assert "& powershell.exe -NoProfile -NonInteractive" in text
    assert "-Branch $branch -ExpectedTip $expectedTip" in text
    assert "later entries were not attempted" in text
    assert "git push" not in text.lower()


def test_bundle_packager_requires_exact_tip_clean_tree_and_full_suite() -> None:
    text = (ROOT / "scripts" / "ops" / "package_exact_tip_bundle.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "ValidatePattern('^[0-9a-fA-F]{40}$')" in text
    assert "$taskInfo.LastRunTime -lt $EarliestSuiteRun" in text
    assert "VERDICT: ALL CHUNKS PASSED" in text
    assert "$worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip" in text
    assert "status --porcelain" in text
    assert "includes_external_credentials = $false" in text
