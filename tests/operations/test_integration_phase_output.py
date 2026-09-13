"""Native invocation of the actual phase function against isolated failed children."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts/ops"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native integration phase contract")


@pytest.mark.parametrize("mode,preflight", [
    ("early_worktree_error", False), ("parse_error", False), ("parameter_error", False),
    ("explicit_exit", False), ("explicit_exit", True), ("deadline", False), ("late_start", False),
    ("monotonic_expired", False), ("launch_failure", False),
])
def test_phase_preserves_early_errors_and_truthful_lifecycle(tmp_path: Path, mode, preflight):
    child = tmp_path / "fixture child.ps1"
    source = {
        "parse_error": "param(\n",
        "parameter_error": "[CmdletBinding()]param([string]$Different)\nthrow 'must not execute'\n",
        "explicit_exit": "[Console]::Out.Write('early stdout'); [Console]::Error.Write('partial stderr'); exit 23\n",
        "deadline": "[Console]::Error.Write('stderr before timeout'); Start-Sleep -Seconds 120\n",
        "late_start": "throw 'must not execute'\n",
    }
    child.write_text(source.get(mode, "throw 'unused'\n"), encoding="utf-8")
    env = {
        **os.environ, "R1P_OPS": str(OPS), "R1P_TEMP": str(tmp_path), "R1P_MODE": mode,
        "R1P_CHILD": str(child), "R1P_PREFLIGHT": str(int(preflight)),
    }
    script = r"""
$ErrorActionPreference = 'Stop'
. (Join-Path $env:R1P_OPS 'windows_kill_on_close_job.ps1')
. (Join-Path $env:R1P_OPS 'integration_launch_diagnostics.ps1')
. (Join-Path $env:R1P_OPS 'integration_attempt_contract.ps1')
. (Join-Path $env:R1P_OPS 'training_window_contract.ps1')
$tokens = $null
$errors = $null
$source = Join-Path $env:R1P_OPS 'integration_attempt_suite.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$phaseFunction = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Invoke-WeatherAttemptSuitePhase'
}, $false))
if ($phaseFunction.Count -ne 1) { throw 'Phase function missing or ambiguous' }
Invoke-Expression $phaseFunction[0].Extent.Text
$manifest = [pscustomobject]@{
    attempt_id = 'isolated-phase'; repo_root = $env:R1P_TEMP
    worktree_root = Join-Path $env:R1P_TEMP 'missing-worktree'
    expected_tip = 'a' * 40; branch_ref = 'codex/phase-fixture'
    suite = [pscustomobject]@{ max_files_per_chunk = 20; additional_python_path = ''; require_live_sdk_contract = $false }
}
$suiteLaunchState = [pscustomobject]@{
    full_suite_started = $false
    output_records = New-Object System.Collections.Generic.List[object]
}
$powerShellExecutable = Join-Path $PSHOME 'powershell.exe'
if ($env:R1P_MODE -eq 'launch_failure') { $powerShellExecutable = Join-Path $env:R1P_TEMP 'missing.exe' }
$boundedSuiteScript = if ($env:R1P_MODE -eq 'early_worktree_error') {
    Join-Path $env:R1P_OPS 'bounded_worktree_test_suite.ps1'
} else { $env:R1P_CHILD }
$hardStop = (Get-Date).AddSeconds(30)
if ($env:R1P_MODE -eq 'deadline') { $hardStop = (Get-Date).AddSeconds(12) }
if ($env:R1P_MODE -eq 'late_start') { $hardStop = (Get-Date).AddSeconds(7) }
$suiteDeadlineBudgetMilliseconds = ($hardStop - (Get-Date)).TotalMilliseconds
if ($env:R1P_MODE -eq 'monotonic_expired') { $suiteDeadlineBudgetMilliseconds = 7000 }
$suiteDeadlineClock = [Diagnostics.Stopwatch]::StartNew()
$launchJournal = New-WeatherLaunchDiagnostics -Path (Join-Path $env:R1P_TEMP 'outer.jsonl') `
    -Operation fixture -ScriptPath $source -Binding @{ attempt_id = 'isolated-phase' }
$exitCode = $null
$failure = $null
$watch = [Diagnostics.Stopwatch]::StartNew()
try {
    $exitCode = Invoke-WeatherAttemptSuitePhase -Phase 'fixture' `
        -LogPath (Join-Path $env:R1P_TEMP 'phase.log') `
        -IntegrationPreflight:($env:R1P_PREFLIGHT -eq '1')
} catch { $failure = $_ }
finally { Close-WeatherLaunchDiagnostics -Journal $launchJournal -Status FAIL -Failure $failure }
[pscustomobject]@{
    exit_code = $exitCode
    failure = if ($failure) { $failure.Exception.Message } else { $null }
    full_suite_started = $suiteLaunchState.full_suite_started
    output = @($suiteLaunchState.output_records | ForEach-Object { $_ })
    elapsed_ms = $watch.ElapsedMilliseconds
} | ConvertTo-Json -Depth 8 -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    journal = [json.loads(line) for line in (tmp_path / "outer.jsonl").read_text().splitlines()]
    events = [entry["event"] for entry in journal]
    assert not (tmp_path / "phase.log").exists()
    if mode in {"late_start", "monotonic_expired"}:
        assert payload["full_suite_started"] is False
        assert payload["output"] == []
        assert "no payload budget" in payload["failure"]
        assert events == ["WRAPPER_ENTERED", "WRAPPER_EXIT"]
        assert not (tmp_path / "phase.log.stdout.log").exists()
        return
    assert payload["full_suite_started"] is (not preflight and mode != "launch_failure")
    if mode == "launch_failure":
        assert events == ["WRAPPER_ENTERED", "CHILD_INTENT", "CHILD_OUTPUT", "WRAPPER_EXIT"]
    else:
        assert events[:3] == ["WRAPPER_ENTERED", "CHILD_INTENT", "CHILD_STARTED"]
    assert events[-2:] == ["CHILD_OUTPUT", "WRAPPER_EXIT"]
    assert len(payload["output"]) == 1
    output = payload["output"][0]
    assert output["teardown_proved"] is True
    assert output["drain_completed"] is True
    for stream in ("stdout", "stderr"):
        data = (tmp_path / f"phase.log.{stream}.log").read_bytes()
        record = output[stream]
        assert Path(record["path"]) == tmp_path / f"phase.log.{stream}.log"
        assert record["sha256"] == hashlib.sha256(data).hexdigest()
        assert record["bytes_seen"] == record["bytes_retained"] == len(data)
        assert record["truncated"] is False
    stderr = (tmp_path / "phase.log.stderr.log").read_bytes()
    if mode == "launch_failure":
        assert "CreateProcess" in payload["failure"]
        assert payload["exit_code"] is None
        assert stderr == b""
        return
    assert stderr
    if mode == "deadline":
        assert payload["exit_code"] is None
        assert "teardown boundary reserve" in payload["failure"]
        assert "CHILD_EXIT" not in events
        assert payload["elapsed_ms"] < 12000
        assert stderr == b"stderr before timeout"
    else:
        assert payload["failure"] is None
        assert payload["exit_code"] != 0
        assert "CHILD_EXIT" in events
    if mode == "explicit_exit":
        assert payload["exit_code"] == 23
        assert stderr == b"partial stderr"
        assert (tmp_path / "phase.log.stdout.log").read_bytes() == b"early stdout"
    assert (tmp_path / "phase.log.bootstrap.jsonl").exists() is (mode == "early_worktree_error")
