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
