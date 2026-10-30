"""Lane L13 HRRR keepalive replacement registrar (tools/research/register_hrrr_keepalive_task.ps1).

Runs the real registrar in Windows PowerShell with the Scheduler cmdlets stubbed; nothing registers or unregisters a
real task.

Guards: the -WhatIf plan never reaches the Scheduler, the task shape the coordinator asked for (15-minute
repetition, StartWhenAvailable off, PT2M, IgnoreNew, the pinned launcher), and the replacement only of a Disabled
keepalive with the old keepalive.cmd action.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from weather.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell registrar")

SCRIPT = REPO_ROOT / "tools/research/register_hrrr_keepalive_task.ps1"
# Fake names: no real task can match even if a stub failed (the harness refuses that case anyway).
OLD = "pytest-l13-fake-old-keepalive-do-not-create"
NEW = "pytest-l13-fake-new-keepalive-do-not-create"
# ScheduledTasks is a CDXML module whose commands are functions: if the registrar's first New-ScheduledTask* call
# autoloads it, its import replaces global stubs of the same name and the REAL Scheduler runs (it did once, 2026-10-30).
# So the harness imports the module first, defines the stubs over it, forces any autoload, and refuses to run the
# registrar unless every Scheduler mutator still resolves to a harness function. Task names are fake as a second guard.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$global:mutations = @()
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($TaskName -eq $env:OLD_NAME -and $env:OLD_STATE -ne 'absent') {
        return [pscustomobject]@{ TaskName = $TaskName; State = $env:OLD_STATE;
            Actions = @([pscustomobject]@{ Execute = 'cmd.exe'; Arguments = $env:OLD_ARGS }) }
    }
    if ($TaskName -eq $env:NEW_NAME -and $env:NEW_EXISTS -eq '1') { return [pscustomobject]@{ TaskName = $TaskName } }
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
    launcher = tmp_path / "wt" / "tools" / "research" / "hrrr_forward_recorder_launch.ps1"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"# fixture launcher\r\nexit 0\r\n")
    return tmp_path / "wt", hashlib.sha256(launcher.read_bytes()).hexdigest()


def run(tmp_path, *, whatif=True, old_state="Disabled", old_args="/c C:\\t\\l13\\recorder_keepalive.cmd",
        new_exists=False, sha=None, **extra):
    wt, real_sha = _worktree(tmp_path)
    params = {"Worktree": str(wt), "WorkingDirectory": str(tmp_path), "ExpectedLauncherSha256": sha or real_sha,
              "Start": "2026-10-31T09:15:00", "TaskName": NEW, "OldTaskName": OLD, **extra}
    env = {**os.environ, "REGISTRAR": str(SCRIPT), "REGISTRAR_PARAMS": json.dumps(params), "WHATIF": "1" if whatif else "0",
           "OLD_NAME": OLD, "NEW_NAME": NEW, "OLD_STATE": old_state, "OLD_ARGS": old_args,
           "NEW_EXISTS": "1" if new_exists else "0"}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", HARNESS], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    payload["mutations"] = payload["mutations"] or []
    if isinstance(payload["mutations"], str):
        payload["mutations"] = [payload["mutations"]]
    return payload, real_sha


@pytest.mark.spawns
def test_whatif_prints_the_requested_shape_and_never_reaches_the_scheduler(tmp_path):
    payload, sha = run(tmp_path)
    assert payload["error"] == "" and payload["mutations"] == []
    out = payload["output"]
    assert f"Task name        : {NEW}" in out
    assert "RepetitionInterval PT15M" in out and "RepetitionDuration ''" in out
    assert "StartWhenAvailable False" in out and "ExecutionTimeLimit PT2M" in out and "MultipleInstances IgnoreNew" in out
    assert "LogonType Interactive, RunLevel Limited" in out
    assert "hrrr_forward_recorder_launch.ps1" in out and f"Launcher sha256  : {sha}" in out
    assert any(l.startswith("StartBoundary") and "2026-10-31T" in l for l in out.splitlines())  # serialized in UTC
    assert f"WhatIf: would unregister '{OLD}'" in out


@pytest.mark.spawns
def test_without_whatif_registers_the_new_task_then_unregisters_the_disabled_one(tmp_path):
    payload, _ = run(tmp_path, whatif=False)
    assert payload["error"] == ""
    assert payload["mutations"] == [f"register:{NEW}", f"unregister:{OLD}"]


@pytest.mark.spawns
def test_absent_old_task_only_registers(tmp_path):
    payload, _ = run(tmp_path, whatif=False, old_state="absent")
    assert payload["error"] == "" and payload["mutations"] == [f"register:{NEW}"]
    assert "absent; nothing to unregister" in payload["output"]


@pytest.mark.spawns
@pytest.mark.parametrize("case,message", [
    ("old_enabled", "not Disabled"),
    ("old_other_action", "not the keepalive"),
    ("new_exists", "task already exists"),
    ("launcher_changed", "!= expected"),
    ("no_expected_sha", "pass -ExpectedLauncherSha256"),
    ("interval_too_short", "below 5"),
])
def test_refuses_and_changes_nothing(tmp_path, case, message):
    kwargs = {"whatif": False}
    if case == "old_enabled":
        kwargs["old_state"] = "Ready"
    elif case == "old_other_action":
        kwargs["old_args"] = "/c something_else.cmd"
    elif case == "new_exists":
        kwargs["new_exists"] = True
    elif case == "launcher_changed":
        kwargs["sha"] = "0" * 64
    elif case == "no_expected_sha":
        kwargs["sha"] = " "
    elif case == "interval_too_short":
        kwargs["IntervalMinutes"] = 1
    payload, _ = run(tmp_path, **kwargs)
    assert message in payload["error"] and payload["mutations"] == []


@pytest.mark.spawns
def test_registrar_refuses_the_real_scheduler_under_weather_task_test(tmp_path):
    # Third guard: with WEATHER_TASK_TEST=1 the registrar itself refuses when a mutator is the real ScheduledTasks
    # command. The probe stubs nothing; the fake names and the guard mean nothing can reach the Scheduler.
    wt, sha = _worktree(tmp_path)
    cmd = (f"$env:WEATHER_TASK_TEST = '1'; try {{ & '{SCRIPT}' -Worktree '{wt}' -WorkingDirectory '{tmp_path}' "
           f"-ExpectedLauncherSha256 {sha} -TaskName '{NEW}' -OldTaskName '{OLD}' }} "
           "catch { 'REFUSED: ' + $_.Exception.Message }")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert "REFUSED: WEATHER_TASK_TEST=1" in result.stdout, result.stdout + result.stderr
