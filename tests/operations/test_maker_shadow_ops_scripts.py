"""Forward maker shadow runner: registrar contract and read-only readout.

Guards: WeatherMakerShadowRunner registrar stays paper-only, S4U/Limited, BelowNormal, IgnoreNew respawn with a
  stop file, and the owner readout stays read-only (docs/operations/maker-shadow-runner.md, Forward runner on the
  capture host).
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REGISTRAR = ROOT / "scripts" / "ops" / "register_maker_shadow_runner.ps1"
READOUT = ROOT / "scripts" / "ops" / "maker_shadow_readout.ps1"


def test_registrar_runs_only_the_paper_shadow_module_with_a_stop_file():
    text = REGISTRAR.read_text(encoding="utf-8")
    assert "'-m weather.market.maker_shadow run --config \"{0}\" --stop-file \"{1}\"'" in text
    assert r"venv\Scripts\pythonw.exe" in text
    assert '$TaskName = "WeatherMakerShadowRunner"' in text
    # Refuses a config that could point the guard at a real wallet book.
    assert '"shadow-maker"' in text and '"wallet_book"' in text and '"campaigns"' in text
    assert "guard_latch init" in text
    for forbidden in ("score", "--offline-fixture", ".env", "credential", "Credential", "private_key"):
        assert forbidden not in text.split("$arguments =", 1)[1].split("\n", 1)[0]


def test_registrar_contract_is_unattended_low_priority_and_respawn_only():
    text = REGISTRAR.read_text(encoding="utf-8")
    assert "-MultipleInstances IgnoreNew" in text
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in text
    assert "-Priority 7" in text and "$registered.Settings.Priority -ne 7" in text
    assert "-RepetitionInterval (New-TimeSpan -Minutes 5)" in text and '-ne "PT5M"' in text
    assert "-LogonType S4U -RunLevel Limited" in text
    assert "SupportsShouldProcess = $true" in text and "$PSCmdlet.ShouldProcess(" in text
    assert text.index("$PSCmdlet.ShouldProcess(") < text.index("Register-ScheduledTask ")


def test_readout_is_read_only():
    text = READOUT.read_text(encoding="utf-8")
    commands = set(re.findall(r"\b([A-Z][a-z]+-[A-Z][A-Za-z]+)\b", text))
    assert commands <= {"Split-Path", "Join-Path", "Get-CimInstance", "Where-Object", "Test-Path", "Get-ChildItem",
                         "ForEach-Object", "Sort-Object", "Get-Content", "ConvertFrom-Json", "New-Object"}, commands
    assert "[IO.FileAccess]::Read" in text and "[IO.FileShare]::ReadWrite" in text
    for forbidden in ("python", "maker_evidence", "Register-", "Start-", "Stop-", "Remove-", "Set-", "Out-File",
                      "WriteAll", "workload_admission"):
        assert forbidden not in text.replace("Name='python.exe' OR Name='pythonw.exe'", "").replace(
            r"-m\s+weather\.market\.maker_shadow\s+run", ""), forbidden
