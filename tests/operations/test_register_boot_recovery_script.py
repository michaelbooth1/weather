from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "register_boot_recovery.ps1"


def test_boot_recovery_starts_without_delay_and_validates_exact_registration() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "New-ScheduledTaskTrigger -AtStartup" in text
    assert '.Delay = "PT2M"' not in text
    assert "-StartWhenAvailable" in text
    assert "-LogonType S4U" in text
    assert '[string]$ExpectedScriptSha256 = ""' in text
    assert '" -ExpectedSelfSha256 $ExpectedScriptSha256"' in text
    assert "Get-FileHash -LiteralPath $script" in text
    assert 'CimClass.CimClassName -ceq "MSFT_TaskBootTrigger"' in text
    assert '[string]$registeredTriggers[0].Delay -eq ""' in text
    assert "the task was disabled" in text
