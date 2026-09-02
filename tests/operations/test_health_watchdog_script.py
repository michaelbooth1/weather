from __future__ import annotations

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
