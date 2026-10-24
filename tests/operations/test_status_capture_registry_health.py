"""status.ps1 reports capture-registry health with the same acceptance rule as roll_verdict.ps1.

Guards: docs/operations/DATA_LAYER_V2_CONTRACT.md "Roll closures" (data layer v2 S1, owner answer
to show registry health in status): an unreadable or malformed platform.roll_closures makes every
roll verdict UNDECIDABLE, so status must say so, and must accept exactly what roll_verdict accepts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS = REPO_ROOT / "scripts" / "ops" / "status.ps1"
REGISTRY = REPO_ROOT / "config" / "capture_families.json"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell"),
]

# Loads only Get-CaptureRegistryHealth from the shipped script with the PowerShell parser and
# evaluates every case in one strict-mode child.
RUNNER = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CRH_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'status.ps1 does not parse' }
$definition = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Get-CaptureRegistryHealth'
}, $true))
if ($definition.Count -ne 1) { throw 'missing unique Get-CaptureRegistryHealth' }
Invoke-Expression $definition[0].Extent.Text
$cases = Get-Content -LiteralPath $env:CRH_CASES -Raw | ConvertFrom-Json
$results = @()
foreach ($case in $cases) {
    $health = Get-CaptureRegistryHealth -RepoRoot ([string]$case.repo)
    $results += [pscustomobject]@{ id = [string]$case.id; ok = $health.ok; closures = @($health.closures); error = $health.error }
}
ConvertTo-Json -InputObject @($results) -Depth 4 | Set-Content -LiteralPath $env:CRH_RESULTS -Encoding utf8
"""


def _registry(mutate=None) -> str:
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if mutate:
        mutate(doc)
    return json.dumps(doc)


CASES = {
    "current": _registry(),
    "missing_file": None,
    "not_json": "{not json",
    "no_platform": _registry(lambda d: d.pop("platform")),
    "no_roll_closures": _registry(lambda d: d["platform"].pop("roll_closures")),
    "empty_closures": _registry(lambda d: d["platform"].update(roll_closures=[])),
    "escaping_path": _registry(lambda d: d["platform"]["roll_closures"][1].update(status_path="data/../x.json")),
    "unknown_arming": _registry(lambda d: d["platform"]["roll_closures"][4].update(arming="sometimes")),
    "row_without_arming": _registry(lambda d: d["platform"]["roll_closures"][0].pop("arming")),
    "optional_without_task": _registry(lambda d: d["platform"]["roll_closures"][4].pop("task")),
    "optional_empty_task": _registry(lambda d: d["platform"]["roll_closures"][4].update(task="")),
}


def test_registry_health_accepts_the_current_registry_and_names_every_broken_shape(tmp_path: Path) -> None:
    payload = []
    for case_id, text in CASES.items():
        repo = tmp_path / case_id
        (repo / "config").mkdir(parents=True)
        if text is not None:
            (repo / "config" / "capture_families.json").write_text(text, encoding="utf-8")
        payload.append({"id": case_id, "repo": str(repo)})
    (tmp_path / "cases.json").write_text(json.dumps(payload), encoding="utf-8")
    env = dict(
        os.environ, CRH_SCRIPT=str(STATUS), CRH_CASES=str(tmp_path / "cases.json"),
        CRH_RESULTS=str(tmp_path / "out.json"),
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", RUNNER],
        env=env, check=True, capture_output=True, timeout=300,
    )
    results = {row["id"]: row for row in json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))}

    current = results.pop("current")
    expected_ids = [row["id"] for row in json.loads(REGISTRY.read_text(encoding="utf-8"))["platform"]["roll_closures"]]
    assert (current["ok"], current["closures"], current["error"]) == (True, expected_ids, None)
    assert set(results) == set(CASES) - {"current"}
    for case_id, row in results.items():
        assert row["ok"] is False, case_id
        assert row["closures"] == [], case_id
        assert row["error"], case_id
    assert results["escaping_path"]["error"] == "malformed roll_closures row: data/../x.json"
    assert results["no_platform"]["error"] == "no platform block"
    assert results["empty_closures"]["error"] == "no roll_closures rows"
