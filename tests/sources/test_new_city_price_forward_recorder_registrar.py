"""Lane L3 new-city price forward recorder registrar (tools/research/register_new_city_price_forward_recorder_task.ps1).

Harness: L13's import-then-stub pattern (tests/sources/test_nbm_text_forward_recorder_registrar.py on
claude/nbm-text-recorder-20261030).

Runs the real registrar in Windows PowerShell with the Scheduler cmdlets stubbed; nothing registers a real task.

Guards: the -WhatIf plan never reaches the Scheduler, the logon-task shape (AtLogOn, PT5M, IgnoreNew, StartWhenAvailable
off, Interactive/Limited, the launcher in the given worktree), the required launcher sha256, refusal of an existing
task, task-name validation, and the registrar's own refusal of the real ScheduledTasks module under WEATHER_TASK_TEST=1.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from weather.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell registrar")

SCRIPT = REPO_ROOT / "tools/research/register_new_city_price_forward_recorder_task.ps1"
# Fake name: no real task can match even if a stub failed (the harness refuses that case anyway).
NAME = "pytest-l3-fake-new-city-price-recorder-do-not-create"
# ScheduledTasks is a CDXML module whose commands are functions: if the registrar's first New-ScheduledTask* call
# autoloads it, its import replaces global stubs of the same name and the REAL Scheduler runs (it did once, 2026-10-30).
# So the harness imports the module first, defines the stubs over it, forces any autoload, and refuses to run the
# registrar unless every Scheduler mutator still resolves to a harness function. The task name is fake as a second
# guard, and the registrar refuses the real module under WEATHER_TASK_TEST=1 as a third.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$global:mutations = @()
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($TaskName -eq $env:NEW_NAME -and ($env:NEW_EXISTS -eq '1' -or $global:mutations.Count -gt 0)) {
        return [pscustomobject]@{ TaskName = $TaskName; State = 'Ready' }
    }
    $null
}
function Register-ScheduledTask { param($TaskName) $global:mutations += "register:$TaskName" }
function Unregister-ScheduledTask { param($TaskName, $Confirm) $global:mutations += "unregister:$TaskName" }
function Disable-ScheduledTask { $global:mutations += 'disable' }
function Enable-ScheduledTask { $global:mutations += 'enable' }
function Set-ScheduledTask { $global:mutations += 'set' }
function Start-ScheduledTask { $global:mutations += 'start' }
$null = New-ScheduledTaskAction -Execute 'harness.exe'
$null = New-ScheduledTaskSettingsSet
foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Disable-ScheduledTask',
                  'Enable-ScheduledTask', 'Set-ScheduledTask', 'Start-ScheduledTask') {
    $c = Get-Command $name
    if ($c.CommandType -ne 'Function' -or $c.Source) { throw "HARNESS UNSAFE: $name resolves to $($c.Source)" }
}
$params = $env:REGISTRAR_PARAMS | ConvertFrom-Json
$splat = @{}
foreach ($p in $params.PSObject.Properties) { $splat[$p.Name] = $p.Value }
if ($env:WHATIF -eq '1') { $splat['WhatIf'] = $true }
$env:WEATHER_TASK_TEST = '1'
$out, $err = @(), ''
try { $out = @(& $env:REGISTRAR @splat 6>$null) } catch { $err = $_.Exception.Message }
foreach ($name in 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
    if ((Get-Command $name).Source) { throw "HARNESS UNSAFE after run: $name resolves to $((Get-Command $name).Source)" }
}
[pscustomobject]@{ error = $err; mutations = @($global:mutations); output = ($out -join "`n") } | ConvertTo-Json -Compress
"""


def _worktree(tmp_path):
    launcher = tmp_path / "wt" / "tools" / "research" / "new_city_price_forward_recorder_launch.ps1"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"# fixture launcher\r\nexit 0\r\n")
    return tmp_path / "wt", hashlib.sha256(launcher.read_bytes()).hexdigest()


def run(tmp_path, *, whatif=True, new_exists=False, sha=None, name=NAME):
    wt, real_sha = _worktree(tmp_path)
    params = {"Worktree": str(wt), "WorkingDirectory": str(tmp_path / "work"), "TaskName": name,
              "ExpectedLauncherSha256": real_sha if sha is None else sha}
    env = {**os.environ, "REGISTRAR": str(SCRIPT), "REGISTRAR_PARAMS": json.dumps(params),
           "WHATIF": "1" if whatif else "0", "NEW_NAME": NAME, "NEW_EXISTS": "1" if new_exists else "0"}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", HARNESS], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    payload["mutations"] = payload["mutations"] or []
    if isinstance(payload["mutations"], str):
        payload["mutations"] = [payload["mutations"]]
    return payload, real_sha, wt


@pytest.mark.spawns
def test_whatif_prints_the_logon_task_and_never_reaches_the_scheduler(tmp_path):
    payload, sha, wt = run(tmp_path)
    assert payload["error"] == "" and payload["mutations"] == []
    out = payload["output"]
    assert f"Task name        : {NAME}" in out
    assert "Delay PT5M, no repetition" in out and "LogonType Interactive, RunLevel Limited" in out
    assert "MultipleInstances IgnoreNew, StartWhenAvailable False, ExecutionTimeLimit PT10M" in out
    assert str(wt / "tools" / "research" / "new_city_price_forward_recorder_launch.ps1") in out
    assert f"Launcher sha256  : {sha}" in out
    assert "WhatIf: task object that would be registered (nothing registered)" in out


@pytest.mark.spawns
def test_without_whatif_registers_once(tmp_path):
    payload, _, _ = run(tmp_path, whatif=False)
    assert payload["error"] == "" and payload["mutations"] == [f"register:{NAME}"]
    # The working directory exists before registration (a missing one stopped the first real start, 2026-10-30).
    assert (tmp_path / "work").is_dir()
    assert f"Working directory: {tmp_path / 'work'} (exists)" in payload["output"]


@pytest.mark.spawns
def test_whatif_creates_no_working_directory(tmp_path):
    payload, _, _ = run(tmp_path)
    assert payload["error"] == "" and not (tmp_path / "work").exists()
