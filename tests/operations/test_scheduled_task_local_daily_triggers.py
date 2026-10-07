"""Daily Scheduler triggers follow local wall-clock time across DST (DST-C1, OD28).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md finding DST-C1 and the
re-registration runbook in docs/operations/OPERATIONS_DESIGN.md.
``New-ScheduledTaskTrigger -Daily -At`` stores a zoned StartBoundary ("...Z" in
memory, a fixed "-04:00" once Task Scheduler saves it). A zoned boundary is a
fixed UTC instant, so after 2026-11-01 every daily task would fire one hour
early on the local clock. Every daily registrar must build its trigger through
``New-WeatherLocalDailyTrigger`` (an unzoned, local boundary) and read it back
through ``Test-WeatherLocalDailyStartBoundary`` (which refuses any zone suffix).

The Windows cases run the repository's own PowerShell in a child whose local
time zone is pinned to Eastern. Nothing is registered: triggers are built in
memory and a Task Scheduler definition is created with ``NewTask`` and only
serialized, never saved.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
HELPER = OPS / "scheduled_task_local_trigger.ps1"
POWERSHELL = ("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command")

# Every registrar that owns a daily (calendar) trigger, with the local times it
# must produce from its literal defaults. Adding a daily registrar means adding it here.
DAILY_REGISTRARS = {
    "register_clob_raw_tape_tiering.ps1": ["06:00"],
    "register_clob_tiering.ps1": ["05:00"],
    "register_cold_snapshot_nightly.ps1": ["06:50"],
    "register_daily_refresh.ps1": ["09:30", "00:35"],
    "register_exchange_economics_refresh.ps1": ["06:50"],
    "register_location_config_refresh.ps1": ["00:00", "06:00", "12:00", "18:00"],
    "register_training_window.ps1": ["04:15"],
}

ZONED = re.compile(r"(Z|[+-]\d\d:\d\d)$")

WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="requires Windows PowerShell",
)

# Pins TimeZoneInfo.Local to the capture host's zone for this child only.
PIN_EASTERN = r"""
$ErrorActionPreference = 'Stop'
$staticFlags = [Reflection.BindingFlags]'NonPublic,Static'
$instanceFlags = [Reflection.BindingFlags]'NonPublic,Instance'
$cache = [TimeZoneInfo].GetField('s_cachedData', $staticFlags).GetValue($null)
$cache.GetType().GetField('m_localTimeZone', $instanceFlags).SetValue(
    $cache, [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time'))
$oneYear = $cache.GetType().GetField('m_oneYearLocalFromUtc', $instanceFlags)
if ($oneYear) { $oneYear.SetValue($cache, $null) }
if ([TimeZoneInfo]::Local.Id -ne 'Eastern Standard Time') { throw 'time zone pin failed' }
$tokens = $null
$errors = $null
"""


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _code(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _run(script: str, env_extra: dict[str, str] | None = None) -> dict:
    env = os.environ.copy()
    env.update(env_extra or {})
    result = subprocess.run(
        [*POWERSHELL, PIN_EASTERN + script],
        capture_output=True, text=True, check=False, env=env, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell harness failed: {result.stderr.strip() or result.stdout.strip()}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


# --------------------------------------------------------------------------- static ratchets (all platforms)


def test_no_ops_script_builds_a_daily_trigger_outside_the_local_helper():
    offenders = []
    for path in sorted(OPS.rglob("*.ps1")):
        if path == HELPER:
            continue
        code = _code(_source(path))
        for match in re.finditer(r"New-ScheduledTaskTrigger\b[^\n]*", code):
            if re.search(r"-Daily\b|-Weekly\b|-Monthly\b", match.group(0)):
                offenders.append(f"{path.name}: {match.group(0).strip()}")
    assert offenders == [], "daily triggers must use New-WeatherLocalDailyTrigger: " + "; ".join(offenders)


def test_daily_registrar_inventory_is_exact_and_reads_back_without_a_zone():
    users = {
        path.name
        for path in OPS.glob("*.ps1")
        if path != HELPER and "New-WeatherLocalDailyTrigger" in _code(_source(path))
    }
    assert users == set(DAILY_REGISTRARS)
    for name in DAILY_REGISTRARS:
        code = _code(_source(OPS / name))
        assert '"scheduled_task_local_trigger.ps1")' in code or "'scheduled_task_local_trigger.ps1')" in code, name
        assert "Test-WeatherLocalDailyStartBoundary" in code, name
        # The [datetime] cast converts a zoned boundary to local time and hides the
        # fixed offset ("2026-10-01T00:30:00-04:00" reads "00:30"); it is not a read-back.
        assert not re.search(r"StartBoundary\)\.ToString\(", code), name


# --------------------------------------------------------------------------- Windows execution


HELPER_PROBE = r"""
. $env:HELPER_PATH
$trigger = New-WeatherLocalDailyTrigger -At '00:30'
$svc = New-Object -ComObject Schedule.Service
$svc.Connect()
$definition = $svc.NewTask(0)
$comTrigger = $definition.Triggers.Create(2)
$comTrigger.StartBoundary = [string]$trigger.StartBoundary
$comTrigger.DaysInterval = 1
$comAction = $definition.Actions.Create(0)
$comAction.Path = 'cmd.exe'
$xml = [xml]$definition.XmlText
$cases = [ordered]@{}
foreach ($value in @('2026-10-07T00:30:00', '2026-10-01T00:30:00-04:00', '2026-10-07T04:30:00Z',
        '2026-10-07T00:30:00+00:00', '2026-10-07T00:31:00', '', '2026-10-07T00:30:00.000')) {
    $cases[$value] = [bool](Test-WeatherLocalDailyStartBoundary -StartBoundary $value -At '00:30')
}
$bad = $false
try { $null = New-WeatherLocalDailyTrigger -At '9:30' } catch { $bad = $true }
$plain = New-ScheduledTaskTrigger -Daily -At '00:30'
[pscustomobject]@{
    zone = [TimeZoneInfo]::Local.Id
    class = [string]$trigger.CimClass.CimClassName
    days_interval = [int]$trigger.DaysInterval
    start_boundary = [string]$trigger.StartBoundary
    expected = (Get-Date).Date.AddMinutes(30).ToString('yyyy-MM-ddTHH:mm:ss')
    xml_start_boundary = [string]$xml.Task.Triggers.CalendarTrigger.StartBoundary
    cases = $cases
    malformed_refused = $bad
    plain_cmdlet_boundary = [string]$plain.StartBoundary
} | ConvertTo-Json -Compress -Depth 4
"""


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_helper_builds_an_unzoned_local_daily_boundary_and_refuses_zoned_readback():
    payload = _run(HELPER_PROBE, {"HELPER_PATH": str(HELPER)})

    assert payload["zone"] == "Eastern Standard Time"
    assert payload["class"] == "MSFT_TaskDailyTrigger"
    assert payload["days_interval"] == 1
    assert payload["start_boundary"] == payload["expected"]
    assert not ZONED.search(payload["start_boundary"])
    # The Task Scheduler definition keeps the boundary unzoned (local time).
    assert payload["xml_start_boundary"] == payload["start_boundary"]
    assert payload["cases"] == {
        "2026-10-07T00:30:00": True,
        "2026-10-01T00:30:00-04:00": False,
        "2026-10-07T04:30:00Z": False,
        "2026-10-07T00:30:00+00:00": False,
        "2026-10-07T00:31:00": False,
        "": False,
        "2026-10-07T00:30:00.000": False,
    }
    assert payload["malformed_refused"] is True
    # Control: the bare cmdlet is zoned, which is the DST-C1 defect this helper removes.
    assert ZONED.search(payload["plain_cmdlet_boundary"])


REGISTRAR_PROBE = r"""
. $env:HELPER_PATH
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:REGISTRAR_PATH, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw "parse errors in $env:REGISTRAR_PATH" }
if ($ast.ParamBlock) {
    foreach ($parameter in $ast.ParamBlock.Parameters) {
        if ($parameter.DefaultValue -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
            Set-Variable -Name $parameter.Name.VariablePath.UserPath -Value $parameter.DefaultValue.Value
        }
    }
}
# Literal script-scope assignments a trigger call may reference (e.g. $triggerTimes).
foreach ($assignment in @($ast.EndBlock.Statements | Where-Object {
        $_ -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left.Extent.Text -eq '$triggerTimes' })) {
    Invoke-Expression $assignment.Extent.Text
}
$commands = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -eq 'New-WeatherLocalDailyTrigger'
}, $true))
if ($commands.Count -eq 0) { throw "no daily trigger in $env:REGISTRAR_PATH" }
$rows = foreach ($command in $commands) {
    $loop = $command.Parent
    while ($loop -and -not ($loop -is [System.Management.Automation.Language.ForEachStatementAst])) { $loop = $loop.Parent }
    if ($loop) {
        foreach ($item in (Invoke-Expression $loop.Condition.Extent.Text)) {
            Set-Variable -Name $loop.Variable.VariablePath.UserPath -Value $item
            $trigger = Invoke-Expression $command.Extent.Text
            [pscustomobject]@{ start_boundary = [string]$trigger.StartBoundary; class = [string]$trigger.CimClass.CimClassName }
        }
    } else {
        $trigger = Invoke-Expression $command.Extent.Text
        [pscustomobject]@{ start_boundary = [string]$trigger.StartBoundary; class = [string]$trigger.CimClass.CimClassName }
    }
}
[pscustomobject]@{ rows = @($rows) } | ConvertTo-Json -Compress -Depth 4
"""


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("registrar", sorted(DAILY_REGISTRARS))
def test_every_daily_registrar_emits_unzoned_local_boundaries(registrar):
    payload = _run(REGISTRAR_PROBE, {"HELPER_PATH": str(HELPER), "REGISTRAR_PATH": str(OPS / registrar)})
    rows = payload["rows"]
    assert isinstance(rows, list) and rows, payload

    zoned = [row["start_boundary"] for row in rows if ZONED.search(row["start_boundary"])]
    assert zoned == [], f"{registrar}: zoned daily StartBoundary {zoned}"
    assert {row["class"] for row in rows} == {"MSFT_TaskDailyTrigger"}
    assert [row["start_boundary"][11:16] for row in rows] == DAILY_REGISTRARS[registrar]
