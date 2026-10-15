"""roll_verdict.ps1 reads capture-closure evidence without crashing and fails closed.

Guards: the roll verdict contract (AGENTS.md; delegation contract section 3) -- missing or empty
closure evidence yields UNDECIDABLE (exit 1), never an exception and never ROLL-FREE.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "roll_verdict.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
STATUS_FILES = (
    "loop_supervisor_status.json",
    "clob_loop_supervisor_status.json",
    "observation_trigger_supervisor_status.json",
    "clob_enrichment_status.json",
)
# Inherited strict mode is the crash condition; the Get-ScheduledTask shadow keeps the
# execution-tape probe hermetic (functions win over cmdlets in command lookup).
STRICT_DRIVER = (
    "Set-StrictMode -Version Latest; "
    "function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName) }; "
    "& $env:RV_SCRIPT -Branch 'feature/x'; exit $LASTEXITCODE"
)


def test_execution_tape_closure_is_required_only_while_armed_or_active() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '[string]$executionTask.State -ne "Disabled"' in text
    assert '"data\\snapshots\\.execution_tape_status.json.writer.lock"' in text
    assert 'Get-OptionalPropertyValue -InputObject $executionWorker -Name "state"' in text
    assert '$statusFiles += "data\\snapshots\\execution_tape_supervisor_status.json"' in text


def test_sparse_retained_closure_status_is_safe_under_inherited_strict_mode() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-OptionalPropertyValue" in text
    for name in ("state", "ensure_status", "reason"):
        assert f'Get-OptionalPropertyValue -InputObject $doc -Name "{name}"' in text
    assert 'Get-OptionalPropertyValue -InputObject $identity -Name "source_scope_files"' in text
    assert "$doc.state" not in text
    assert "$doc.ensure_status" not in text
    assert "$doc.reason" not in text


@pytest.mark.spawns
@pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None,
    reason="Windows PowerShell 5.1 is required",
)
@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ({"state": "RUNNING", "runtime_identity": {}}, "(runtime identity empty or absent)"),
        ({"state": "RUNNING", "current_runtime_identity": {}, "runtime_identity": ""},
         "(runtime identity empty or absent)"),
        ({"state": "RUNNING", "runtime_identity": None}, "(runtime identity empty or absent)"),
        ({"state": "RUNNING"}, "(runtime identity empty or absent)"),
        ({}, "(runtime identity empty or absent)"),
        (None, "(empty document)"),
    ],
    ids=["empty-object", "all-empty", "null", "absent", "empty-doc", "json-null"],
)
def test_empty_or_absent_runtime_identity_is_undecidable_under_strict_mode(
    tmp_path: Path, document: object, reason: str
) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts" / "ops").mkdir(parents=True)
    snapshots = repo / "data" / "snapshots"
    snapshots.mkdir(parents=True)
    script = repo / "scripts" / "ops" / "roll_verdict.ps1"
    shutil.copyfile(SCRIPT, script)
    for name in STATUS_FILES:
        (snapshots / name).write_text(json.dumps(document), encoding="utf-8")

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", STRICT_DRIVER],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "RV_SCRIPT": str(script)},
    )

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "cannot be found" not in result.stderr
    assert result.stdout.splitlines()[0] == "UNDECIDABLE: no live closure evidence"
    assert "ROLL-FREE" not in result.stdout
    for name in STATUS_FILES:
        assert "data\\snapshots\\" + f"{name} {reason}" in result.stdout
