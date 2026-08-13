from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"


def test_rearmed_one_shot_does_not_reuse_prior_failure_as_current_flag():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$oneShot -and $ti.NextRunTime" in text
    assert '([datetime]$ti.NextRunTime) -gt (Get-Date)' in text
    assert "is re-armed for" in text
    assert "$ok = $true" in text


def test_capture_alert_flags_only_the_current_local_capture_day():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date" in text
    assert "-not $historicalCaptureDay -and $ageH -lt 24" in text
    assert "capture alert raised today" in text


def test_disabled_on_demand_success_is_not_an_unexpected_disable():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$noTriggers = ($null -eq $_.Triggers)" in text
    assert "$onDemandCompleted = ($noTriggers -and $res -eq \"0x0\"" in text
    assert "completed an on-demand run" in text


def test_only_active_scheduled_interactive_tasks_count_as_reboot_exposure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$scheduledWorkRemains = (-not $noTriggers" in text
    assert '$st -ne "Disabled"' in text
    assert "$scheduledWorkRemains)" in text


def test_operator_held_evidence_refresh_keeps_one_honest_warning():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '"WeatherEveningEvidenceRefresh"' in text
    assert "$evidenceRefreshHeld = $true" in text
    assert "is operator-held DISABLED" in text


def test_quiet_merge_recovery_interval_cannot_overlap_sensitive_driver():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$actionArguments -like "*quiet_window_merge.ps1*"' in text
    assert "-SettleSeconds\\s+(\\d+)" in text
    assert "$settleSeconds + 240" in text
    assert "$sensitiveDriverNextRun -ge $mergeTask.at" in text
    assert "the driver can publish unverified local master" in text
