"""Forward maker shadow runner: registrar contract and read-only readout.

Guards: WeatherMakerShadowRunner registrar stays paper-only, S4U/Limited, BelowNormal, IgnoreNew respawn with a
  stop file, and the owner readout stays read-only (docs/operations/maker-shadow-runner.md, Forward runner on the
  capture host).
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from maker_core.shadow.admission import EMBARGO_WINDOWS, FULL

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


POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt", reason="real Windows PowerShell 5.1 readout")
@pytest.mark.parametrize(("scope", "expected"), [
    ({"git_commit": "c" * 40, "git_dirty": False, "git_error": None}, "; code cccccccccccc;"),
    ({"git_commit": "c" * 40, "git_dirty": True, "git_error": None}, "; code cccccccccccc DIRTY;"),
    ({"git_commit": None, "git_dirty": None, "git_error": "git_unavailable"}, "; code unbound (git_unavailable);"),
    ({}, "; code not recorded;"),
])
def test_readout_surfaces_the_live_tape_code_identity(tmp_path, scope, expected):
    tapes = tmp_path / "data" / "maker_shadow" / "tapes"
    tapes.mkdir(parents=True)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = [{"event": "opened", "sequence": 0, "recorded_at_utc": now.isoformat(), "scope": {"mode": "x", **scope}},
            {"event": "universe", "sequence": 1, "recorded_at_utc": now.isoformat()}]
    (tapes / f"{now.date().isoformat()}-r1.tape.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(READOUT), "-RepoRoot", str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout and ", last record: universe" in result.stdout, result.stdout
    through = max(end for _, end, _, _ in EMBARGO_WINDOWS)
    closed = ", ".join(f"{a}..{b}" for a, b, scope, _ in EMBARGO_WINDOWS if scope == FULL)
    assert f"; 88a scoring embargoed through {through} UTC; parity outcome-blind, never {closed}" in result.stdout


def test_readout_embargo_dates_are_not_hard_coded():
    text = READOUT.read_text(encoding="utf-8")
    for start, end, _, _ in EMBARGO_WINDOWS:
        assert start not in text and end not in text
    assert r"src\maker_core\shadow\admission.py" in text
