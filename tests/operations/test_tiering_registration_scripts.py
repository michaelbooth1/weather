from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"


def _text(name: str) -> str:
    return (OPS / name).read_text(encoding="utf-8-sig")


def test_projection_tiering_registration_is_exact_bounded_and_no_catchup() -> None:
    text = _text("register_clob_tiering.ps1")

    assert 'Join-Path $RepoRoot "scripts\\ops\\clob_tiering_run.ps1"' in text
    assert '[ValidateSet("05:00")][string]$At = "05:00"' in text
    assert "$maxRuntimeSeconds = 1800" in text
    assert '"-MaxRuntimeSeconds", ([string]$maxRuntimeSeconds)' in text
    assert '$executionTimeLimit = "PT31M"' in text
    assert "New-TimeSpan -Minutes 31" in text
    assert "-WakeToRun" in text
    assert "\n    -StartWhenAvailable `" not in text
    _assert_exact_readback(text, at="05:00", status_name="clob_tiering")


def test_raw_tiering_registration_is_exact_bounded_and_no_catchup() -> None:
    text = _text("register_clob_raw_tape_tiering.ps1")

    assert 'Join-Path $RepoRoot "scripts\\ops\\clob_raw_tape_tiering_run.ps1"' in text
    assert '[ValidateSet("06:00")][string]$At = "06:00"' in text
    assert "$maxRuntimeSeconds = 2400" in text
    assert "$limit = 150" in text
    assert '"-MaxRuntimeSeconds", ([string]$maxRuntimeSeconds)' in text
    assert '"-Limit", ([string]$limit)' in text
    assert '$executionTimeLimit = "PT41M"' in text
    assert "New-TimeSpan -Minutes 41" in text
    assert "-WakeToRun" in text
    assert "\n    -StartWhenAvailable `" not in text
    _assert_exact_readback(text, at="06:00", status_name="clob_raw_tape_tiering")


def _assert_exact_readback(text: str, *, at: str, status_name: str) -> None:
    assert "$matches.Count -ne 1" in text
    assert '$registeredActions[0].Arguments -cne $arguments' in text
    assert '$registeredActions[0].WorkingDirectory -ine $RepoRoot' in text
    assert "$registeredTriggers.Count -ne 1" in text
    assert 'CimClass.CimClassName -ne "MSFT_TaskDailyTrigger"' in text
    assert "$registeredTriggers[0].DaysInterval -ne 1" in text
    assert "$registeredTriggers[0].Repetition.Interval" in text
    assert "$registeredTime -ne $At" in text
    assert "$registered.Settings.ExecutionTimeLimit" in text
    assert "[bool]$registered.Settings.StartWhenAvailable" in text
    assert "[bool]$registered.Settings.DisallowStartIfOnBatteries" in text
    assert "Settings.AllowStartIfOnBatteries" not in text
    assert "-not [bool]$registered.Settings.WakeToRun" in text
    assert '[string]$registered.Principal.LogonType -ne "S4U"' in text
    assert '[string]$registered.Principal.RunLevel -ne "Limited"' in text
    assert f'daily at $At local' in text
    assert f"data\\logs\\{status_name}_task_status.json" in text
    assert at in text


@pytest.mark.parametrize(
    "name",
    ("register_clob_tiering.ps1", "register_clob_raw_tape_tiering.ps1"),
)
def test_tiering_registrar_powershell_syntax(name: str) -> None:
    path = OPS / name
    command = (
        "$tokens=$null;$errors=$null;"
        "[void][Management.Automation.Language.Parser]::ParseFile("
        f"'{path}',[ref]$tokens,[ref]$errors);"
        "if(@($errors).Count){$errors|% Message;exit 1}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
