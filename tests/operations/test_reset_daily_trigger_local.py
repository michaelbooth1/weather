"""reset_daily_trigger_local.ps1 removes only the zone from calendar triggers (DST-C1, OD28).

Guards: the "DST re-registration (OD28)" runbook in docs/operations/OPERATIONS_DESIGN.md,
which uses this script for daily tasks with no repository registrar
(WeatherStalenessSweep, WeatherStreakCaptureMonitor). Get-ScheduledTask and
Set-ScheduledTask are replaced by in-process stubs: nothing is read from or written
to Task Scheduler.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "reset_daily_trigger_local.ps1"

pytestmark = [
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell"),
    pytest.mark.spawns,
]

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$fixture = Get-Content -LiteralPath $env:FIXTURE_PATH -Raw | ConvertFrom-Json
function New-FixtureTrigger($row) {
    [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = $row.class }
        StartBoundary = $row.start
        Repetition = [pscustomobject]@{ Interval = $row.interval; Duration = $row.duration }
    }
}
$global:FixtureTask = [pscustomobject]@{
    TaskName = $fixture.task
    Triggers = @($fixture.triggers | ForEach-Object { New-FixtureTrigger $_ })
}
$global:SetCalls = 0
function Get-ScheduledTask { param([string]$TaskName, $ErrorAction)
    if ($TaskName -ne $global:FixtureTask.TaskName) { throw "no task $TaskName" }
    return $global:FixtureTask
}
function Set-ScheduledTask { param([string]$TaskName, $Trigger, $ErrorAction)
    $global:SetCalls++
    $global:FixtureTask = [pscustomobject]@{ TaskName = $TaskName; Triggers = @($Trigger) }
    return $global:FixtureTask
}
$out = $null
$failure = $null
try {
    $arguments = @{ TaskName = $env:RESET_TASK; ExpectedAt = @($env:RESET_AT -split ',') }
    if ($env:RESET_APPLY -eq '1') { $arguments['Apply'] = $true }
    $out = & $env:RESET_SCRIPT @arguments 6>$null
} catch { $failure = [string]$_.Exception.Message }
[pscustomobject]@{
    failure = $failure
    set_calls = $global:SetCalls
    triggers = @($global:FixtureTask.Triggers | ForEach-Object {
        [pscustomobject]@{ start = [string]$_.StartBoundary; interval = [string]$_.Repetition.Interval; duration = [string]$_.Repetition.Duration } })
    plan = @($out | Where-Object { $_ -is [string] -and $_.StartsWith('{') }) -join ''
} | ConvertTo-Json -Compress -Depth 5
"""


def _run(tmp_path: Path, task: str, triggers: list[dict], expected_at: str, *, apply: bool) -> dict:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"task": task, "triggers": triggers}), encoding="utf-8")
    env = os.environ.copy()
    env.update(FIXTURE_PATH=str(fixture), RESET_SCRIPT=str(SCRIPT), RESET_TASK=task,
               RESET_AT=expected_at, RESET_APPLY="1" if apply else "0")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", HARNESS],
        capture_output=True, text=True, timeout=120, env=env, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _daily(start: str, interval: str = "", duration: str = "") -> dict:
    return {"class": "MSFT_TaskDailyTrigger", "start": start, "interval": interval, "duration": duration}


def test_staleness_sweep_zoned_0810_becomes_local_0810(tmp_path):
    payload = _run(tmp_path, "WeatherStalenessSweep", [_daily("2026-09-30T08:10:00-04:00")], "08:10", apply=True)
    assert payload["failure"] is None
    assert payload["set_calls"] == 1
    assert payload["triggers"][0]["start"] == "2026-09-30T08:10:00"


def test_streak_monitor_keeps_its_repetition_and_other_triggers(tmp_path):
    triggers = [
        {"class": "MSFT_TaskLogonTrigger", "start": "", "interval": "", "duration": ""},
        _daily("2026-08-01T12:00:00-04:00", "PT30M", "PT6H"),
    ]
    payload = _run(tmp_path, "WeatherStreakCaptureMonitor", triggers, "12:00", apply=True)
    assert payload["failure"] is None
    assert payload["triggers"][0] == {"start": "", "interval": "", "duration": ""}
    assert payload["triggers"][1] == {"start": "2026-08-01T12:00:00", "interval": "PT30M", "duration": "PT6H"}


def test_dry_run_changes_nothing_and_prints_the_plan(tmp_path):
    payload = _run(tmp_path, "WeatherStalenessSweep", [_daily("2026-09-30T08:10:00-04:00")], "08:10", apply=False)
    assert payload["failure"] is None
    assert payload["set_calls"] == 0
    plan = json.loads(payload["plan"])
    assert plan["changes"] == 1 and plan["triggers"][0]["after"] == "2026-09-30T08:10:00"


@pytest.mark.parametrize(
    ("triggers", "expected_at", "message"),
    [
        ([_daily("2026-09-30T08:10:00-04:00")], "07:10", "not the expected 07:10"),
        ([_daily("2026-09-30T12:10:00Z")], "08:10", "UTC ('Z') boundary"),
        ([_daily("2026-09-30T08:10:00-04:00")], "08:10,12:00", "-ExpectedAt names 2"),
        ([{"class": "MSFT_TaskMonthlyTrigger", "start": "2026-09-30T08:10:00-04:00", "interval": "", "duration": ""}],
         "08:10", "not handled here"),
    ],
)
def test_surprises_are_refused_before_anything_changes(tmp_path, triggers, expected_at, message):
    payload = _run(tmp_path, "WeatherStalenessSweep", triggers, expected_at, apply=True)
    assert payload["failure"] and message in payload["failure"], payload
    assert payload["set_calls"] == 0


def test_an_already_local_trigger_is_left_alone(tmp_path):
    payload = _run(tmp_path, "WeatherStalenessSweep", [_daily("2026-10-30T08:10:00")], "08:10", apply=True)
    assert payload["failure"] is None
    assert payload["set_calls"] == 0
