"""status.ps1 shows the 88a recorder's running-vs-disk code identity; the 88a-R restart refuses safely.

Guards: owner Q11 (DECISION_LOG 2026-10-15; DATA_LAYER_V2_PLAN.md section 9): new capture families
adopt code by explicit restart, with running-vs-disk code identity shown in status. The identity
compares each source_sha256 the recorder stamped at start with the file on disk (CURRENT, STALE,
UNKNOWN); restart_maker_evidence_capture.ps1 reuses that one function and refuses without a
readable status and a verified core recorder pid, never touching the Scheduler.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS = REPO_ROOT / "scripts" / "ops" / "status.ps1"
RESTART = REPO_ROOT / "scripts" / "ops" / "restart_maker_evidence_capture.ps1"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell"),
]

RUNNER = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MEC_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'status.ps1 does not parse' }
$definition = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Get-MakerEvidenceCodeIdentity'
}, $true))
if ($definition.Count -ne 1) { throw 'missing unique Get-MakerEvidenceCodeIdentity' }
Invoke-Expression $definition[0].Extent.Text
$cases = Get-Content -LiteralPath $env:MEC_CASES -Raw | ConvertFrom-Json
$results = @()
foreach ($case in $cases) {
    $source = if ($null -eq $case.source) { $null } else { $case.source }
    $identity = Get-MakerEvidenceCodeIdentity -RepoRoot ([string]$case.repo) -SourceSha256 $source
    $results += [pscustomobject]@{ id = [string]$case.id; state = $identity.state; modules = $identity.modules;
        stale = @($identity.stale); error = $identity.error }
}
ConvertTo-Json -InputObject @($results) -Depth 4 | Set-Content -LiteralPath $env:MEC_RESULTS -Encoding utf8
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_identity_is_current_stale_or_unknown_from_the_stamped_hashes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "weather" / "market").mkdir(parents=True)
    capture = repo / "src" / "weather" / "market" / "maker_evidence_capture.py"
    package = repo / "src" / "weather" / "market" / "__init__.py"
    capture.write_bytes(b"running = 1\n")
    package.write_bytes(b"")
    running = {"weather.market.maker_evidence_capture": _sha(b"running = 1\n"), "weather.market": _sha(b"")}
    cases = [
        {"id": "current", "repo": str(repo), "source": running},
        {"id": "stale", "repo": str(repo), "source": {**running, "weather.market.maker_evidence_capture": _sha(b"old\n")}},
        {"id": "missing", "repo": str(repo), "source": {**running, "weather.market.gone": _sha(b"x")}},
        {"id": "absent", "repo": str(repo), "source": None},
        {"id": "foreign", "repo": str(repo), "source": {"os.path": _sha(b"x")}},
    ]
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    env = dict(os.environ, MEC_SCRIPT=str(STATUS), MEC_CASES=str(tmp_path / "cases.json"),
               MEC_RESULTS=str(tmp_path / "out.json"))
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", RUNNER],
                   env=env, check=True, capture_output=True, timeout=300)
    results = {row["id"]: row for row in json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))}
    assert (results["current"]["state"], results["current"]["modules"], results["current"]["stale"]) == ("CURRENT", 2, [])
    assert (results["stale"]["state"], results["stale"]["stale"]) == ("STALE", ["weather.market.maker_evidence_capture"])
    assert results["missing"]["state"] == "STALE" and results["missing"]["stale"] == ["weather.market.gone (missing on disk)"]
    assert results["absent"]["state"] == "UNKNOWN" and results["absent"]["error"]
    assert results["foreign"]["state"] == "UNKNOWN" and "unexpected module name" in results["foreign"]["error"]


def test_status_reports_identity_in_json_and_warns_on_stale_code() -> None:
    text = STATUS.read_text(encoding="utf-8-sig")
    assert "maker_evidence_code = $makerEvidenceCode" in text
    assert 'MAKER_EVIDENCE_CODE: running 88a code differs from disk' in text


def test_restart_refuses_without_status_and_never_touches_the_scheduler(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts" / "ops").mkdir(parents=True)
    shutil.copyfile(STATUS, repo / "scripts" / "ops" / "status.ps1")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(RESTART),
         "-Apply", "-RepoRoot", str(repo)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 2, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["result"] == "REFUSED" and receipt["applied"] is False
    assert any(reason.startswith("status unreadable") for reason in receipt["refusals"])
    source = RESTART.read_text(encoding="utf-8-sig")
    for forbidden in ("Start-ScheduledTask", "Register-ScheduledTask", "Set-ScheduledTask",
                      "Unregister-ScheduledTask", "Disable-ScheduledTask"):
        assert forbidden not in source
