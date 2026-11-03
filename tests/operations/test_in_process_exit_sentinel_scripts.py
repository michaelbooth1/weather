"""In-process script calls whose exit code is read never trust a stale $LASTEXITCODE.

Guards: suite_gated_quiet_merge.ps1 and adopt_execution_tape_after_merge.ps1 treat an in-process child that returns without an exit code as a failure (9009 sentinel), and adoption requires the attempt gate's JSON `authorized` to be true (exit-default-fail review, 2026-10-22).

``& script.ps1`` runs in-process: a child that returns without ``exit`` leaves
``$LASTEXITCODE`` at whatever the last native command set, usually a passing
``git`` call (0). Both callers now seed ``$global:LASTEXITCODE = 9009`` first.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
WINDOWS_POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None,
    reason="the in-process exit-code contract is Windows PowerShell 5.1 behaviour",
)

TIP = "a" * 40
MANIFEST_SHA = "b" * 64
RECEIPT_SHA = "c" * 64
MERGE_TASK = "WeatherIntegrationMerge-test"


def _powershell_file(script: Path, *arguments: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    assert WINDOWS_POWERSHELL is not None
    return subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), *arguments],
        capture_output=True, text=True, env=env, cwd=cwd, timeout=120, check=False,
    )


# ------------------------------------------------------------- adoption gate
# Cmdlet shadows: functions win over cmdlets in command lookup. The merge task
# is a completed, hash-bound integration-attempt merge.
ADOPT_WRAPPER = r"""
function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    [pscustomobject]@{ TaskName = $TaskName; State = 'Ready'; Actions = @([pscustomobject]@{
        Arguments = ('-File integration_attempt_merge.ps1 -ManifestPath "{0}" -ExpectedManifestSha256 {1}' -f
            $env:ADOPT_MANIFEST, $env:ADOPT_MANIFEST_SHA) }) } }
function global:Get-ScheduledTaskInfo { [CmdletBinding()] param([string]$TaskName)
    [pscustomobject]@{ LastRunTime = Get-Date; LastTaskResult = 0 } }
cmd.exe /c exit 0  # a stale success, as an earlier native command would leave it
& $env:ADOPT_SCRIPT @args
exit $LASTEXITCODE
"""

# Stand-in for assert_integration_attempt_success.ps1, which signals success by
# returning after its last native command (exit 0) and printing the proof JSON.
ATTEMPT_GATE_STUB = r"""
param([string]$ManifestPath, [string]$ExpectedManifestSha256, [string]$ExpectedMergeReceiptSha256)
$mode = $env:ADOPT_GATE_MODE
$authorized = switch ($mode) { 'unauthorized' { $false } 'authorized-string' { 'true' } default { $true } }
if ($mode -ne 'noexit') { cmd.exe /c exit 0 }
[pscustomobject]@{
    authorized = $authorized
    source_tip = if ($mode -eq 'other-tip') { 'd' * 40 } else { $env:ADOPT_TIP }
    merge_task_name = $env:ADOPT_TASK
} | ConvertTo-Json
"""


@pytest.fixture()
def adopt(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    (repo / "venv" / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (repo / "venv" / "Scripts" / name).write_bytes(b"")
    (repo / "scripts" / "ops").mkdir(parents=True)
    (repo / "scripts" / "ops" / "assert_integration_attempt_success.ps1").write_text(
        ATTEMPT_GATE_STUB, encoding="utf-8"
    )
    manifest = tmp_path / "attempt" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text("{}", encoding="utf-8")
    wrapper = tmp_path / "adopt_wrapper.ps1"
    wrapper.write_text(ADOPT_WRAPPER, encoding="utf-8")
    return {"repo": repo, "manifest": manifest, "wrapper": wrapper, "cwd": tmp_path}


def _adopt(adopt: dict[str, Path], gate_mode: str) -> tuple[int, dict[str, object]]:
    env = {
        **os.environ,
        "ADOPT_SCRIPT": str(OPS / "adopt_execution_tape_after_merge.ps1"),
        "ADOPT_MANIFEST": str(adopt["manifest"]),
        "ADOPT_MANIFEST_SHA": MANIFEST_SHA,
        "ADOPT_GATE_MODE": gate_mode,
        "ADOPT_TIP": TIP,
        "ADOPT_TASK": MERGE_TASK,
    }
    result = _powershell_file(
        adopt["wrapper"],
        "-ExpectedTip", TIP, "-MergeTaskName", MERGE_TASK, "-RepoRoot", str(adopt["repo"]),
        "-AttemptManifestPath", str(adopt["manifest"]),
        "-ExpectedManifestSha256", MANIFEST_SHA, "-ExpectedMergeReceiptSha256", RECEIPT_SHA,
        env=env, cwd=adopt["cwd"],
    )
    payload = json.loads(result.stdout)
    return result.returncode, payload


@pytest.mark.spawns
@pytest.mark.parametrize(
    ("gate_mode", "reason"),
    [
        ("unauthorized", "immutable integration-attempt success proof is not authorized"),
        ("authorized-string", "immutable integration-attempt success proof is not authorized"),
        ("noexit", "immutable integration-attempt success proof failed"),
        # Control: an authorized, fresh proof passes both checks and is refused
        # only by the next one, because the stub names another source tip.
        ("other-tip", "ExpectedTip does not equal the hash-bound integration-attempt source tip"),
    ],
)
def test_adoption_requires_an_authorized_proof_and_a_fresh_exit_code(
    adopt: dict[str, Path], gate_mode: str, reason: str
) -> None:
    returncode, payload = _adopt(adopt, gate_mode)

    assert returncode == 1, payload
    assert payload["adopted"] is False
    assert payload["reason"] == reason
    assert payload["cleanup"] is None  # nothing was enabled, so nothing to tear down


# ------------------------------------------------------------- suite gate tail
# Runs the real statements of suite_gated_quiet_merge.ps1 from `Set-StrictMode
# -Off` to the end (the in-process merge call and its exit) against a stub.
SUITE_GATE_TAIL_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:SGQ_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'suite gate does not parse' }
$top = @($ast.EndBlock.Statements)
$start = -1
for ($i = 0; $i -lt $top.Count; $i++) { if ($top[$i].Extent.Text -ceq 'Set-StrictMode -Off') { $start = $i } }
if ($start -lt 0) { throw 'Set-StrictMode -Off not found' }
$mergeScript = $env:SGQ_MERGE_STUB
$mergeArgs = @{}
cmd.exe /c exit 0  # a stale success, as the gate's earlier git calls leave it
foreach ($statement in $top[$start..($top.Count - 1)]) { Invoke-Expression $statement.Extent.Text }
throw 'suite gate tail returned without exit'
"""

MERGE_STUB = r"""
$mode = $env:SGQ_MERGE_MODE
if ($mode -eq 'noexit') { 'stub merge returned without an exit code'; return }
exit ([int]$mode)
"""


@pytest.mark.spawns
@pytest.mark.parametrize(("mode", "expected"), [("noexit", 1), ("3", 3), ("0", 0)])
def test_suite_gate_treats_a_merge_without_exit_code_as_failure(tmp_path: Path, mode: str, expected: int) -> None:
    harness = tmp_path / "sgq_tail.ps1"
    harness.write_text(SUITE_GATE_TAIL_HARNESS, encoding="utf-8")
    stub = tmp_path / "merge_stub.ps1"
    stub.write_text(MERGE_STUB, encoding="utf-8")
    env = {
        **os.environ,
        "SGQ_SCRIPT": str(OPS / "suite_gated_quiet_merge.ps1"),
        "SGQ_MERGE_STUB": str(stub),
        "SGQ_MERGE_MODE": mode,
    }

    result = _powershell_file(harness, env=env, cwd=tmp_path)

    assert result.returncode == expected, result.stdout + result.stderr
    if mode == "noexit":
        assert "QUIET MERGE RETURNED NO EXIT CODE" in result.stdout, result.stdout
