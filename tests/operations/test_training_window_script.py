from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "training_window.ps1"


def test_training_window_uses_verified_no_live_capture_admission():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Wait-CaptureStopped" in text
    assert "--capture-mode no_live_capture" in text
    assert "--capture-resource-mode\", \"no_live_capture" in text
    assert "--capture-resource-min-free-memory-bytes\", \"0" in text
    assert "if (-not (Wait-CaptureStopped $CaptureStopTimeoutSeconds))" in text


def test_training_window_restores_before_propagating_nightly_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "} finally {" in text
    assert "Restore-Capture" in text.split("} finally {", 1)[1]
    assert '$nightlyStatus -in @(\"blocked\", \"error\", \"missing\", \"unreadable\")' in text
    assert text.rstrip().endswith("exit $childExit")
