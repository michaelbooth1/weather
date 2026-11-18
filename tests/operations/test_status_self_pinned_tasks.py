"""R35 self-pinned task check in status.ps1: Get-WeatherSelfPinnedTaskState hashes the -File of an action that pins
itself with -ExpectedSelfSha256 and classifies it. Fixtures only; the function is extracted from status.ps1 and run in
a real powershell.exe child, never against the host Scheduler.

Guards: master ruling R35 (2026-11-01) item 2 - PIN_MISMATCH and FILE_MISSING are FLAGs, an unparseable action is a
WARN, G5-owned watchdog actions (-ExpectedStatusScriptSha256) are skipped, quoted and bare -File both parse.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "scripts" / "ops" / "status.ps1"
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract"),
    pytest.mark.spawns,
]


def _classify(tmp_path: Path, cases: list[tuple[str, str]]) -> list[list[dict]]:
    """Run the extracted function once per (task, arguments) case in one child; one row list per case."""
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([{"task": t, "arguments": a} for t, a in cases]), encoding="utf-8")
    runner = tmp_path / "runner.ps1"
    runner.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$tokens=$null; $errors=$null\n"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{STATUS}',[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n"
        "$f=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and"
        " $n.Name -eq 'Get-WeatherSelfPinnedTaskState'},$true))\n"
        "if($f.Count -ne 1){throw 'missing function'}\n"
        "Invoke-Expression $f[0].Extent.Text\n"
        f"$cases = Get-Content -Raw -LiteralPath '{cases_path}' | ConvertFrom-Json\n"
        "$out = @(foreach ($c in $cases) { ,@(Get-WeatherSelfPinnedTaskState -TaskName $c.task -Arguments $c.arguments) })\n"
        "ConvertTo-Json -InputObject $out -Depth 4 -Compress\n",
        encoding="utf-8-sig")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(runner)], capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    # ConvertTo-Json collapses one-element arrays; normalize to a list of row lists.
    if len(cases) == 1 and not (isinstance(parsed, list) and parsed and isinstance(parsed[0], list)):
        parsed = [parsed]
    out = []
    for item in parsed:
        if item is None:
            out.append([])
        elif isinstance(item, dict):
            out.append([item])
        else:
            out.append(list(item))
    return out


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pinned(tmp_path):
    script = tmp_path / "boot recovery dir" / "boot_recovery.ps1"
    script.parent.mkdir()
    script.write_text("Write-Output 'fixture'\n", encoding="utf-8")
    bare = tmp_path / "journal" / "manual_order_journal.ps1"
    bare.parent.mkdir()
    bare.write_text("Write-Output 'journal'\n", encoding="utf-8")
    return script, bare


def test_quoted_and_bare_file_pins_that_match_are_pin_ok(tmp_path, pinned):
    script, bare = pinned
    rows = _classify(tmp_path, [
        ("WeatherBootRecovery", f'-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{script}" '
                                f"-ExpectedSelfSha256 {_sha(script).upper()}"),
        ("WeatherManualOrderJournal", f"-NoProfile -File {bare} -RepoRoot C:\\repo -ExpectedSelfSha256 {_sha(bare)} "
                                      f"-ExpectedModulesSha256 {'0' * 64}"),
    ])
    assert [r[0]["status"] for r in rows] == ["PIN_OK", "PIN_OK"]
    assert rows[0][0]["file"] == str(script) and rows[0][0]["expected_sha256"] == _sha(script)
    assert rows[1][0]["file"] == str(bare) and rows[1][0]["actual_sha256"] == _sha(bare)


def test_a_changed_file_is_pin_mismatch_and_a_missing_file_is_file_missing(tmp_path, pinned):
    script, _ = pinned
    expected = _sha(script)
    script.write_text("Write-Output 'landed change'\n", encoding="utf-8")
    missing = tmp_path / "gone.ps1"
    rows = _classify(tmp_path, [
        ("WeatherBootRecovery", f'-File "{script}" -ExpectedSelfSha256 {expected}'),
        ("WeatherBootRecovery", f'-File "{missing}" -ExpectedSelfSha256 {expected}'),
    ])
    assert rows[0][0]["status"] == "PIN_MISMATCH" and rows[0][0]["actual_sha256"] == _sha(script)
    assert rows[0][0]["detail"] == "pinned script no longer matches its registered SHA256"
    assert rows[1][0]["status"] == "FILE_MISSING" and rows[1][0]["detail"] == "pinned script is missing"


def test_unpinned_and_watchdog_actions_yield_no_rows(tmp_path, pinned):
    script, _ = pinned
    rows = _classify(tmp_path, [
        ("WeatherMg2InputExport", f'-File "{script}" -ProductionRepoRoot C:\\repo'),
        ("WeatherHostHealthWatchdog", f'-File "{script}" -ExpectedSelfSha256 {_sha(script)} '
                                      f'-StatusScriptPath "{script}" -ExpectedStatusScriptSha256 {_sha(script)}'),
        ("WeatherMakerShadowRunner", ""),
    ])
    assert rows == [[], [], []]


@pytest.mark.parametrize("arguments", [
    "-ExpectedSelfSha256 {sha}",
    '-File "{script}" -ExpectedSelfSha256 notahash',
    '-File "{script}" -File "{script}" -ExpectedSelfSha256 {sha}',
    "-File relative\\boot_recovery.ps1 -ExpectedSelfSha256 {sha}",
], ids=["no-file", "bad-hash", "two-files", "relative"])
def test_unparseable_actions_are_unknown(tmp_path, pinned, arguments):
    script, _ = pinned
    rows = _classify(tmp_path, [("WeatherBootRecovery", arguments.format(script=script, sha=_sha(script)))])
    assert len(rows[0]) == 1 and rows[0][0]["status"] == "UNKNOWN" and rows[0][0]["detail"]


def test_status_wires_rows_into_flags_warns_and_json():
    source = STATUS.read_text(encoding="utf-8-sig")
    g5 = source.index("# ---- deployed watchdog/status vs master")
    check = source.index("# ---- self-pinned task scripts (R35; read-only) ----")
    assert check > g5
    block = source[check:source.index("# ---- post-integration documentation transaction", check)]
    assert '"PIN_MISMATCH" { $flags.Add(' in block and '"FILE_MISSING" { $flags.Add(' in block
    assert '"UNKNOWN" { $warns.Add(' in block and 'catch { $warns.Add("self-pinned task check failed to run") }' in block
    assert '"Weather' not in block
    assert "self_pinned_tasks = @($selfPinnedTasks)" in source
