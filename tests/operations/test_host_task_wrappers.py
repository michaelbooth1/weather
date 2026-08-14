from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_recurring_registration_sources_preserve_unattended_s4u() -> None:
    registrars = {
        path: path.read_text(encoding="utf-8-sig")
        for path in (ROOT / "scripts" / "ops").glob("register_*.ps1")
    }
    scheduled_registrars = {
        path: text
        for path, text in registrars.items()
        if "Register-ScheduledTask" in text
    }

    assert scheduled_registrars
    for path, text in scheduled_registrars.items():
        assert "$principal = New-ScheduledTaskPrincipal" in text
        assert "-UserId $env:USERNAME" in text
        assert "-LogonType S4U" in text
        assert "-RunLevel Limited" in text
        assert "-Principal $principal" in text, path.name
        assert "only while logged on" not in text, path.name
        assert r"C:\Users\micha" not in text, path.name


def test_location_refresh_revalidates_target_date_before_success() -> None:
    text = (ROOT / "scripts" / "ops" / "refresh_location_config.ps1").read_text(
        encoding="utf-8-sig"
    )

    refresh = '"weather.operations.location_config_refresh"'
    validation = '"weather.operations.event_metadata_validation"'
    assert text.index(refresh) < text.index(validation)
    assert '$targetDate = (Get-Date).ToString("yyyy-MM-dd")' in text
    assert 'if ([string]$validation.target_date -ne $targetDate' in text
    assert '[string]$validation.status -ne "PASS"' in text
    assert "--no-live-fetch" not in text


def test_recurring_maker_tasks_share_repo_owned_paper_wrapper() -> None:
    wrapper = (ROOT / "scripts" / "ops" / "market_making_daily_roll_task.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert 'if ($Mode -ne "paper-live-forward")' in wrapper
    assert '"quote_size=$QuoteSize"' in wrapper
    assert '"max_band_notional=$MaxBandNotional"' in wrapper
    assert '"max_event_notional=$MaxEventNotional"' in wrapper
    assert '[string]$StartNoLaterThanLocalTime = "20:00"' in wrapper
    assert '"--start-no-later-than-local-time", $StartNoLaterThanLocalTime' in wrapper
    assert "BelowNormal" in wrapper
    for name in (
        "register_market_making_daily_roll.ps1",
        "register_market_making_daily_roll_supervisor.ps1",
    ):
        text = (ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        assert "market_making_daily_roll_task.ps1" in text
        assert '"powershell.exe"' in text
        if name == "register_market_making_daily_roll_supervisor.ps1":
            assert '[string]$StartNoLaterThanLocalTime = "20:00"' in text
            assert "-StartNoLaterThanLocalTime $StartNoLaterThanLocalTime" in text


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
