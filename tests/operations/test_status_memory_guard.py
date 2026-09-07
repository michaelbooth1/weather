from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "status.ps1"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_memory_guard_evidence_validates_freshness_and_warning_threshold(tmp_path):
    baseline = {
        "checked_at": "2026-09-07T10:00:00-04:00",
        "commit_percent": 88.4,
        "warn_percent": 85,
        "act_percent": 92,
    }
    cases = [
        ("high", baseline),
        ("boundary", {**baseline, "commit_percent": 85}),
        ("ok", {**baseline, "commit_percent": 60}),
        ("stale", {**baseline, "checked_at": "2026-09-07T09:50:00-04:00"}),
        ("future", {**baseline, "checked_at": "2026-09-07T10:02:00-04:00"}),
        ("missing-field", {"checked_at": baseline["checked_at"]}),
        ("invalid-percent", {**baseline, "commit_percent": 101}),
        ("boolean-percent", {**baseline, "commit_percent": True}),
        ("invalid-thresholds", {**baseline, "warn_percent": 95}),
        ("zero-threshold", {**baseline, "warn_percent": 0}),
    ]
    for name, payload in cases:
        (tmp_path / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "malformed.json").write_text("{broken", encoding="utf-8")
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_STATUS_SCRIPT, [ref]$tokens, [ref]$errors
)
if (@($errors).Count) { throw 'status script did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-StatusMemoryGuardEvidence'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'memory guard function missing' }
Invoke-Expression $functionAst.Extent.Text
$names = @('high', 'boundary', 'ok', 'stale', 'future', 'missing-field',
    'invalid-percent', 'boolean-percent', 'invalid-thresholds', 'zero-threshold',
    'malformed', 'absent')
$results = @($names | ForEach-Object {
    $result = Get-StatusMemoryGuardEvidence -Path (Join-Path $env:WEATHER_GUARD_CASES "$_.json") `
        -Now ([datetimeoffset]'2026-09-07T10:01:00-04:00')
    [pscustomobject]@{ name = $_; result = $result }
})
$results | ConvertTo-Json -Depth 4 -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "WEATHER_STATUS_SCRIPT": str(SCRIPT), "WEATHER_GUARD_CASES": str(tmp_path)},
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    rows = {row["name"]: row["result"] for row in json.loads(completed.stdout)}
    assert rows["high"]["status"] == "HIGH_COMMIT"
    assert rows["high"]["commit_percent"] == 88.4
    assert rows["high"]["age_seconds"] == 60
    assert rows["boundary"]["status"] == "HIGH_COMMIT"
    assert rows["ok"]["status"] == "OK"
    for name in rows.keys() - {"high", "boundary", "ok"}:
        assert rows[name]["status"] == "UNKNOWN", name


def test_status_exposes_memory_guard_in_both_outputs():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert 'memory_guard = $memoryGuardState' in text
    assert 'HIGH COMMIT:' in text
    assert 'MEMORY GUARD UNKNOWN:' in text
    assert '  COMMIT    :' in text
