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


def test_execution_tape_registrar_is_public_only_and_low_priority() -> None:
    text = (ROOT / "scripts" / "ops" / "register_execution_tape_supervisor.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "weather.operations.execution_tape_supervisor ensure" in text
    assert "--market all" in text
    assert "-Priority 7" in text
    assert "public execution-tape" in text
    for forbidden in ("credential", "private-key", "api-key", "wallet", "live-order"):
        assert f"--{forbidden}" not in text.lower()


def test_execution_tape_post_merge_adoption_is_exact_and_fail_closed() -> None:
    text = (ROOT / "scripts" / "ops" / "adopt_execution_tape_after_merge.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "suite_gated_quiet_merge.ps1" in text
    assert "merge-base --is-ancestor $ExpectedTip master" in text
    assert "$masterTip -ne $originTip" in text
    assert "capture_recovery_check --json" in text
    assert 'LogonType -ne "S4U"' in text
    assert 'RunLevel -ne "Limited"' in text
    assert "Settings.Priority -ne 7" in text
    assert 'State -ne "Disabled"' in text
    assert "$enabledByThisRun = $true" in text
    assert "would not restore the reviewed held state" in text
    assert "Enable-ScheduledTask -TaskName $SupervisorTaskName" in text
    assert "Start-ScheduledTask -TaskName $SupervisorTaskName" in text
    assert "execution_tape_supervisor stop" in text
    assert "Disable-ScheduledTask -TaskName $script:SupervisorTaskName" in text
    assert "trap {" in text
    assert "unexpected adoption failure" in text
    assert "runtime_identity_matches_current" in text
    assert "status.managed_process.pid" in text
    assert "writerLock.managed_process.pid" in text
    assert "price_path_evidence_usable" in text


def test_overnight_chain_audit_is_exact_read_only_and_fail_closed() -> None:
    text = (
        ROOT / "scripts" / "ops" / "audit_overnight_integration_chain.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "Stage01Tip" in text
    assert "ExecutionTapeTip" in text
    assert "AuditScriptTip" in text
    assert "AuditScriptSha256" in text
    assert "Get-FileHash -LiteralPath $PSCommandPath" in text
    assert '"refs/remotes/origin/$AuditScriptBranch"' in text
    assert "Set-Location -LiteralPath $RepoRoot" in text
    assert "production_python_imports" in text
    assert "capture_recovery_check `\n        --repo-root $RepoRoot --json" in text
    assert "VERDICT: ALL CHUNKS PASSED" in text
    assert "merge-base --is-ancestor $tip master" in text
    assert "runtime_identity_matches_current" in text
    assert ".execution_tape_status.json.writer.lock" in text
    assert "WeatherEveningEvidenceRefresh" in text
    assert "WeatherOneShotPush" in text
    assert "Disable-ScheduledTask -TaskName $AuditTaskName" in text
    for forbidden in (
        "Start-ScheduledTask",
        "Enable-ScheduledTask",
        "Register-ScheduledTask",
        "git merge",
        "git push",
        "execution_tape_supervisor ensure",
    ):
        assert forbidden not in text


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
