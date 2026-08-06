from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_mm_execution_capture.ps1"
)


def test_registration_is_fail_closed_on_the_three_narrowing_contracts():
    text = SCRIPT.read_text(encoding="utf-8")

    for value in (
        "--retention-mode",
        "executions-only",
        "--lock-scope",
        "execution-tape",
        "--host-policy-mode",
        "pause-training-window",
    ):
        assert value in text
    assert "weather.market.mm_execution_capture --help" in text
    assert "unsafe maker tape producer" in text
    assert "WeatherClobEnrichmentLoop" in text


def test_registration_is_below_normal_and_never_starts_the_task():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "-Priority 6" in text
    assert "Start-ScheduledTask" not in text
    assert "--retention-mode executions-only --lock-scope execution-tape" in text
    assert '"--host-policy-mode pause-training-window"' in text
