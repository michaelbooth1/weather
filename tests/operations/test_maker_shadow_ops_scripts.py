"""Forward maker shadow runner: registrar contract and read-only readout.

Guards: WeatherMakerShadowRunner registrar stays paper-only, S4U/Limited, BelowNormal, IgnoreNew respawn with a
  stop file, and the owner readout stays read-only (docs/operations/maker-shadow-runner.md, Forward runner on the
  capture host). Each script is also executed: the registrar only with -WhatIf on a fake root, the readout on a
  fake temp root that is fingerprinted unchanged.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

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


# --------------------------------------------------------------------------- execution (behaviour) tests
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None, reason="requires Windows PowerShell"
)
# Never a real task name: the registrar runs only under -WhatIf here, and even a slip could not touch the
# production WeatherMakerShadowRunner task.
TEST_TASK_NAME = "WeatherMakerShadowRunnerPytestWhatIfOnly"


def _run_ps1(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    # Real powershell.exe -File child: exit codes and ShouldProcess/-WhatIf binding are under test.
    return subprocess.run(
        [WINDOWS_POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), *args],
        capture_output=True, text=True, timeout=180, check=False, cwd=str(cwd),
    )


def _fake_registrar_root(tmp_path: Path, guard: dict) -> Path:
    root = tmp_path / "repo"
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    shadow = root / "data" / "maker_shadow"
    shadow.mkdir(parents=True)
    latch = tmp_path / "latch"
    latch.mkdir()
    config = {"schema_version": "weather.maker_shadow_config.v0.1", "guard": {"latch_dir": str(latch), **guard}}
    (shadow / "shadow_config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _tree_fingerprint(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_registrar_whatif_validates_the_config_and_registers_nothing(tmp_path):
    root = _fake_registrar_root(tmp_path, {"policy": {"campaign_id": "shadow-maker"}})
    before = _tree_fingerprint(tmp_path)
    result = _run_ps1(REGISTRAR, "-RepoRoot", str(root), "-TaskName", TEST_TASK_NAME, "-WhatIf", cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "What if" in result.stdout and TEST_TASK_NAME in result.stdout, result.stdout
    assert "Registered" not in result.stdout
    assert _tree_fingerprint(tmp_path) == before


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
@pytest.mark.parametrize(
    ("guard", "message"),
    [
        ({"policy": {"campaign_id": "shadow-maker"}, "wallet_book": "x"}, "must not name a wallet book"),
        ({"policy": {"campaign_id": "shadow-maker"}, "campaigns": []}, "must not name a wallet book"),
        ({"policy": {"campaign_id": "live-maker"}}, "must name the paper campaign"),
    ],
    ids=["wallet-book", "campaigns", "non-paper-campaign"],
)
def test_registrar_refuses_a_non_paper_config_before_registration(tmp_path, guard, message):
    root = _fake_registrar_root(tmp_path, guard)
    result = _run_ps1(REGISTRAR, "-RepoRoot", str(root), "-TaskName", TEST_TASK_NAME, "-WhatIf", cwd=tmp_path)
    assert result.returncode != 0
    assert message in result.stdout + result.stderr, result.stdout + result.stderr
    assert "What if" not in result.stdout


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_readout_reports_a_fake_root_and_writes_nothing(tmp_path):
    root = tmp_path / "repo"
    shadow = root / "data" / "maker_shadow"
    tapes = shadow / "tapes"
    scores = shadow / "scores"
    tapes.mkdir(parents=True)
    scores.mkdir()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    (tapes / "2026-01-01-r1.tape.jsonl").write_text("{}\n", encoding="utf-8")
    (tapes / "2026-01-01-r1.seal.json").write_text(json.dumps({"records": 5, "bytes": 10}), encoding="utf-8")
    (tapes / f"{today}-r1.tape.jsonl").write_text("{}\n", encoding="utf-8")
    (tapes / f"{today}-r1.seal.json").write_text(json.dumps({"records": 7, "bytes": 100}), encoding="utf-8")
    minute = {
        "event": "minute", "sequence": 2, "recorded_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "conditions": [{"band": "a"}, {"band": "b", "unevaluated": True}],
        "paper": {"print_gaps": ["g"]}, "guard": {"action": "allow"},
    }
    (tapes / f"{today}-r2.tape.jsonl").write_text(
        json.dumps({"event": "start", "sequence": 0}) + "\n" + json.dumps(minute) + "\n", encoding="utf-8"
    )
    for day, status in (("2025-12-31", "PASS"), ("2026-01-01", "PASS"), ("2026-01-02", "FAIL")):
        (scores / f"{day}.json").write_text(json.dumps({"agreement": {"status": status}}), encoding="utf-8")
    (shadow / "STOP").write_text("", encoding="utf-8")
    before = _tree_fingerprint(tmp_path)

    result = _run_ps1(READOUT, "-RepoRoot", str(root), "-ParityStartUtc", "2026-01-01", cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    line = result.stdout.strip()
    assert line.startswith("shadow: process "), line
    assert "sealed days 2 since 2026-01-01" in line
    assert "last minute: 2 bands, 1 unevaluated, 1 print gaps, guard allow" in line
    assert "rows today 10 (" in line  # 7 sealed + sequence 2 + 1 of the open tape
    assert "parity-days PASS since 2026-01-01: 1" in line
    assert "[STOP file present]" in line
    assert _tree_fingerprint(tmp_path) == before


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_readout_on_an_empty_root_reports_nothing_sealed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    result = _run_ps1(READOUT, "-RepoRoot", str(root), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    line = result.stdout.strip()
    assert "sealed days 0 since none; last tick none (n/a)" in line
    assert "parity clock not started" in line
    assert not any(root.iterdir())
