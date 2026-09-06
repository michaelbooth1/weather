from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "ops" / "health_watchdog.ps1"
)
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("explicit_root", [False, True])
def test_watchdog_native_subprocess_keeps_real_alerts_and_selected_root(
    tmp_path: Path, explicit_root: bool
) -> None:
    source_root = tmp_path / "watchdog checkout"
    runtime_root = tmp_path / "runtime checkout" if explicit_root else source_root
    watchdog = source_root / "scripts" / "ops" / "health_watchdog.ps1"
    watchdog.parent.mkdir(parents=True)
    watchdog.write_bytes(SCRIPT.read_bytes())
    status_script = runtime_root / "scripts" / "ops" / "status.ps1"
    status_script.parent.mkdir(parents=True, exist_ok=True)
    status_script.write_text(
        "param([Parameter(Mandatory=$true)][string]$RepoRoot, [switch]$Json)\n"
        "if ($RepoRoot -ne (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) { exit 7 }\n"
        "@{verdict='ATTENTION'; flags=@('disk filling at fixture rate'); warns=@(); "
        "streak=@{days=2;target=14;today='fixture capture'}; "
        "reconciliation_publication=@{classification='ordinary'}} | ConvertTo-Json -Depth 4\n"
        "exit 2\n",
        encoding="utf-8",
    )
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(watchdog),
        "-ExpectedSelfSha256", hashlib.sha256(watchdog.read_bytes()).hexdigest(),
    ]
    if explicit_root:
        command.extend(["-RepoRoot", str(runtime_root)])
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0, result.stderr
    latest = json.loads(
        (runtime_root / "data" / "alerts" / "host_health_latest.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert latest["today"] == "fixture capture"
    assert latest["streak"] == "2/14"
    assert latest["top_severity"] == "HIGH"
    alert = latest["alerts"][0]
    assert alert["flag"] == "disk filling at fixture rate"
    assert alert["class"] == "capacity"
    assert "00:30-09:00" in alert["act"]
    assert "shared lease" in alert["act"]
    assert "BLIND" not in (runtime_root / "data" / "alerts" / "MORNING_BRIEFING.md").read_text()
    if explicit_root:
        assert not (source_root / "data").exists()


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("expected_hash", ["0" * 64, "invalid"])
def test_watchdog_rejects_changed_source_before_writing_alerts(
    tmp_path: Path, expected_hash: str
) -> None:
    script = tmp_path / "health_watchdog.ps1"
    script.write_bytes(SCRIPT.read_bytes())
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
            "-RepoRoot", str(tmp_path), "-ExpectedSelfSha256", expected_hash,
        ],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode != 0
    assert not (tmp_path / "data").exists()


def test_watchdog_carries_structured_reconciliation_publication_state() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'if ($text -match "^RECONCILIATION_PUBLICATION_")' in text
    assert 'return "reconciliation_publication"' in text
    assert '"reconciliation_publication" { "HIGH" }' in text
    assert "reconciliation_publication = $status.reconciliation_publication" in text
    assert "do not manually invoke or retry WeatherOneShotPush" in text


@WINDOWS_POWERSHELL_REQUIRED
def test_watchdog_never_turns_reconciliation_state_into_resume_advice() -> None:
    env = {**os.environ, "WEATHER_WATCHDOG_SCRIPT": str(SCRIPT)}
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_WATCHDOG_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'health watchdog script did not parse' }
foreach ($name in @('Get-FlagClass', 'Get-FlagAction')) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing function $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$flags = @(
    'RECONCILIATION_PUBLICATION_GUARDED_PRE_DISPATCH: owner',
    'RECONCILIATION_PUBLICATION_ATTEMPTED_UNACKNOWLEDGED: uncertain',
    'RECONCILIATION_PUBLICATION_EVIDENCE_INVALID: preserve',
    'RECONCILIATION_PUBLICATION_RELATED_TASK_STATE: preserve',
    'ordinary scheduled job failed'
)
$rows = @($flags | ForEach-Object {
    $class = Get-FlagClass $_
    [pscustomobject]@{
        flag = $_
        class = $class
        action = Get-FlagAction $class
    }
})
$rows | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    for row in rows[:4]:
        assert row["class"] == "reconciliation_publication"
        assert "do not manually invoke or retry WeatherOneShotPush" in row["action"]
        assert "next scheduled run" not in row["action"]
        assert "resume" not in row["action"]
    assert rows[4]["class"] == "scheduled_job"
    assert "resume in the quiet window" in rows[4]["action"]
