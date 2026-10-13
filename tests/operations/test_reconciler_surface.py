"""L5: the bounded suite runs the reconciler execution file only when a tip touches its surface.

Guards: owner decision 2026-10-06 (L5). A touched surface includes the file, an untouched
one skips it and the skip is logged, -IncludeReconciler forces it, and the predicate can
never silently go empty: a missing floor or test file throws, and the suite then includes
the file. Executes scripts/ops/reconciler_surface.ps1 and the suite's real selection block.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = REPO_ROOT / "scripts" / "ops" / "reconciler_surface.ps1"
SUITE = REPO_ROOT / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
RECONCILER = "tests/operations/test_production_baseline_reconciler_execution.py"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell 5.1"),
]

FIXTURE = {
    RECONCILER: 'from tests.ci_timing import x\nSCRIPT = ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"\n',
    "tests/ci_timing.py": "x = 1\n",
    "scripts/ops/quiet_window_merge.ps1": ". (Join-Path $PSScriptRoot 'helper.ps1')\n& python -m weather.operations.thing\n",
    "scripts/ops/helper.ps1": "'helper'\n",
    "scripts/ops/production_baseline_scheduler_rpc.ps1": "'rpc'\n",
    "scripts/ops/workload_admission.ps1": "'lease'\n",
    "scripts/ops/new_integration_attempt.ps1": "'attempt'\n",
    "scripts/ops/unrelated.ps1": "'unrelated'\n",
    "src/weather/operations/thing.py": "X = 1\n",
    "src/weather/operations/other.py": "X = 2\n",
}


def _fixture(tmp_path: Path, skip: tuple[str, ...] = ()) -> Path:
    tmp_path = tmp_path / "repo"
    for relative, text in FIXTURE.items():
        if relative in skip:
            continue
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _ps(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=120, env={**os.environ, **env})


def _surface(root: Path) -> subprocess.CompletedProcess:
    return _ps("$ErrorActionPreference='Stop'; . $env:LIB; "
               "Get-WeatherReconcilerSurface -Root $env:ROOT | ConvertTo-Json -Compress",
               {"LIB": str(LIBRARY), "ROOT": str(root)})


def _decision(root: Path, changed: list[str], force: bool = False) -> dict:
    result = _ps("$ErrorActionPreference='Stop'; . $env:LIB; "
                 "$parsed = $env:CHANGED | ConvertFrom-Json; $c = [string[]]@($parsed | ForEach-Object { $_ }); "
                 f"Get-WeatherReconcilerDecision -Root $env:ROOT -ChangedPaths $c {'-Force' if force else ''} "
                 "| ConvertTo-Json -Compress",
                 {"LIB": str(LIBRARY), "ROOT": str(root), "CHANGED": json.dumps(changed)})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_surface_is_derived_from_the_test_file_its_scripts_and_the_floor(tmp_path):
    result = _surface(_fixture(tmp_path))
    assert result.returncode == 0, result.stderr
    surface = set(json.loads(result.stdout))
    assert {RECONCILER, "tests/ci_timing.py", "scripts/ops/quiet_window_merge.ps1",
            "scripts/ops/helper.ps1",  # dot-sourced by a surface script
            "src/weather/operations/thing.py",  # launched with -m by a surface script
            "scripts/ops/production_baseline_scheduler_rpc.ps1", "scripts/ops/workload_admission.ps1",
            "scripts/ops/new_integration_attempt.ps1"} <= surface
    assert "scripts/ops/unrelated.ps1" not in surface
    assert "src/weather/operations/other.py" not in surface


def test_touch_includes_no_touch_excludes_and_force_includes(tmp_path):
    root = _fixture(tmp_path)
    touched = _decision(root, ["docs/x.md", "scripts/ops/helper.ps1"])
    assert touched["Include"] is True and touched["Touched"] == ["scripts/ops/helper.ps1"]
    untouched = _decision(root, ["scripts/ops/unrelated.ps1", "src/weather/operations/other.py"])
    assert untouched["Include"] is False and untouched["Reason"] == "no surface path changed"
    assert untouched["SurfaceCount"] >= 8
    assert _decision(root, [], force=True)["Include"] is True


@pytest.mark.parametrize("missing", [RECONCILER, "scripts/ops/workload_admission.ps1",
                                     "scripts/ops/new_integration_attempt.ps1"])
def test_the_predicate_never_silently_goes_empty(tmp_path, missing):
    result = _surface(_fixture(tmp_path, skip=(missing,)))
    assert result.returncode != 0
    assert "reconciler surface" in result.stderr


def test_real_repository_surface_covers_the_reconciler_dependencies():
    result = _surface(REPO_ROOT)
    assert result.returncode == 0, result.stderr
    surface = set(json.loads(result.stdout))
    assert {RECONCILER, "scripts/ops/quiet_window_merge.ps1", "scripts/ops/workload_admission.ps1",
            "scripts/ops/production_baseline_scheduler_rpc.ps1",
            "scripts/ops/integration_attempt_contract.ps1"} <= surface


# --- the suite's own selection block, executed with stubbed git and log ---------------

SELECTION_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:SUITE, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'suite parse failure' }
$blocks = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -like '*$testFiles -contains $reconcilerTestFile*'
}, $true))
if ($blocks.Count -ne 1) { throw 'missing unique reconciler selection block' }
$script:log = @()
function Write-SuiteLog { param([string]$Message) $script:log += $Message }
function Invoke-SuiteCheckedLocalGit { param($Root, $Arguments, $Label)
    $parsed = $env:CHANGED | ConvertFrom-Json
    [pscustomobject]@{ Rows = @($parsed | ForEach-Object { $_ }) } }
$WorktreeRoot = $env:ROOT
$ExpectedTip = 'b' * 40
$ReconcilerSurfaceBase = $env:BASE
$IncludeReconciler = [bool]$env:FORCE
$IntegrationPreflight = $false
$reconcilerTestFile = 'tests/operations/test_production_baseline_reconciler_execution.py'
$testFiles = @('tests/a/test_a.py', $reconcilerTestFile)
# Dot-source the block from a file beside a copy of the library, so $PSScriptRoot
# resolves exactly as it does inside the suite.
Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $env:SUITE) 'reconciler_surface.ps1') -Destination $env:HARNESS_DIR
$blockFile = Join-Path $env:HARNESS_DIR 'selection_block.ps1'
[IO.File]::WriteAllText($blockFile, $blocks[0].Extent.Text)
. $blockFile
[pscustomobject]@{ files = @($testFiles); log = @($script:log) } | ConvertTo-Json -Compress
"""


def _select(root: Path, changed: list[str], base: str = "a" * 40, force: bool = False) -> dict:
    harness_dir = root.parent / f"h{abs(hash((tuple(changed), base, force))) % 10**8}"
    harness_dir.mkdir(exist_ok=True)
    result = _ps(SELECTION_HARNESS, {"SUITE": str(SUITE), "ROOT": str(root), "CHANGED": json.dumps(changed),
                                     "BASE": base, "FORCE": "1" if force else "",
                                     "HARNESS_DIR": str(harness_dir)})
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    payload["files"] = [payload["files"]] if isinstance(payload["files"], str) else payload["files"]
    payload["log"] = [payload["log"]] if isinstance(payload["log"], str) else payload["log"]
    return payload


def test_suite_skips_an_untouched_reconciler_and_logs_the_skip(tmp_path):
    out = _select(_fixture(tmp_path), ["scripts/ops/unrelated.ps1"])
    assert RECONCILER not in out["files"] and "tests/a/test_a.py" in out["files"]
    assert any(line.startswith("reconciler: SKIPPED reason=no surface path changed") for line in out["log"])


def test_suite_includes_a_touched_forced_or_baseless_reconciler(tmp_path):
    root = _fixture(tmp_path)
    touched = _select(root, ["scripts/ops/helper.ps1"])
    assert RECONCILER in touched["files"] and "touched=scripts/ops/helper.ps1" in touched["log"][0]
    forced = _select(root, ["scripts/ops/unrelated.ps1"], force=True)
    assert RECONCILER in forced["files"] and "forced by -IncludeReconciler" in forced["log"][0]
    baseless = _select(root, ["scripts/ops/unrelated.ps1"], base="")
    assert RECONCILER in baseless["files"] and "no -ReconcilerSurfaceBase supplied" in baseless["log"][0]


def test_suite_fails_closed_when_the_predicate_cannot_be_evaluated(tmp_path):
    root = _fixture(tmp_path, skip=("scripts/ops/workload_admission.ps1",))
    out = _select(root, ["scripts/ops/unrelated.ps1"])
    assert RECONCILER in out["files"]
    assert "predicate unavailable" in out["log"][0]
