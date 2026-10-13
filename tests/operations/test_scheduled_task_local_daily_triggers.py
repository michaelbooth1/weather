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


# Directories never scanned: local runtime state, environments and VCS metadata.
SKIP_DIRS = {".git", "venv", ".venv", "data", "node_modules", "__pycache__", ".pytest_cache"}
# Python is scanned for schtasks/COM construction only outside tests (tests embed probes).
PYTHON_ROOTS = ("src", "scripts", "tools", "app")

# A repetition interval of one day or more on a -Once trigger is a daily trigger
# anchored to a fixed instant.
DAY_INTERVAL = re.compile(
    r"-RepetitionInterval\s+(?:"
    r"\(\s*New-TimeSpan\b[^)]*-Days\b"
    r"|\(\s*New-TimeSpan\b[^)]*-Hours\s+(?:2[4-9]|[3-9]\d|\d{3,})\b"
    r"|\(\s*\[timespan\]::FromDays\("
    r"|\(\s*\[timespan\]::FromHours\(\s*(?:2[4-9]|[3-9]\d|\d{3,})\b"
    r"|['\"]?P\d+D"
    r"|['\"]?PT(?:2[4-9]|[3-9]\d|\d{3,})H"
    r"|['\"]?\d+\.\d\d:\d\d(?::\d\d)?['\"]?"
    r")",
    re.IGNORECASE,
)
CALENDAR_SWITCH = re.compile(r"(?<![\w$])-(?:Daily|Weekly|Monthly)\b", re.IGNORECASE)
COM_CALENDAR = re.compile(r"\.Triggers\.Create\(\s*[2-5]\s*\)", re.IGNORECASE)
SCHTASKS_CALENDAR = re.compile(r"schtasks\b[^\n]*?/sc\s*['\"]?\s*(?:daily|weekly|monthly)\b", re.IGNORECASE)
SCHTASKS_LIST_CALENDAR = re.compile(r"['\"]/sc['\"]\s*,\s*['\"](?:daily|weekly|monthly)['\"]", re.IGNORECASE)
ZONED_XML = re.compile(r"<StartBoundary>[^<]*(?:Z|[+-]\d\d:\d\d)\s*</StartBoundary>", re.IGNORECASE)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _code(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _logical_powershell(text: str) -> str:
    """Comments removed and backtick continuations joined, so a split command is one line."""
    text = re.sub(r"<#.*?#>", " ", text, flags=re.DOTALL)
    text = _code(text)
    return re.sub(r"`[ \t]*\r?\n", " ", text)


def _powershell_offenses(text: str) -> list[str]:
    offenses = []
    for line in _logical_powershell(text).splitlines():
        for match in re.finditer(r"New-ScheduledTaskTrigger\b.*", line, re.IGNORECASE):
            command = match.group(0)
            if CALENDAR_SWITCH.search(command):
                offenses.append("calendar trigger: " + command.strip()[:160])
            elif re.search(r"-Once\b", command, re.IGNORECASE) and DAY_INTERVAL.search(command):
                offenses.append("-Once with a daily repetition: " + command.strip()[:160])
        if COM_CALENDAR.search(line):
            offenses.append("COM calendar trigger: " + line.strip()[:160])
        if SCHTASKS_CALENDAR.search(line):
            offenses.append("schtasks calendar trigger: " + line.strip()[:160])
    if ZONED_XML.search(text):
        offenses.append("zoned StartBoundary in task XML")
    return offenses


def _python_offenses(text: str) -> list[str]:
    offenses = []
    if COM_CALENDAR.search(text):
        offenses.append("COM calendar trigger")
    if SCHTASKS_CALENDAR.search(text) or SCHTASKS_LIST_CALENDAR.search(text):
        offenses.append("schtasks calendar trigger")
    if ZONED_XML.search(text):
        offenses.append("zoned StartBoundary in task XML")
    return offenses


def _walk(suffixes: tuple[str, ...], roots: tuple[Path, ...]) -> list[Path]:
    found = set()
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in suffixes:
                continue
            if SKIP_DIRS & set(path.relative_to(ROOT).parts) or not path.is_file():
                continue
            found.add(path)
    return sorted(found)


def _powershell_files() -> list[Path]:
    return _walk((".ps1", ".psm1"), (ROOT,))


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


def test_detector_catches_split_once_com_schtasks_and_xml_forms():
    caught = [
        "$t = New-ScheduledTaskTrigger -Daily -At '00:30'",
        "$t = New-ScheduledTaskTrigger `\n    -Daily `\n    -At $At",
        "$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 04:00",
        "$t = New-ScheduledTaskTrigger -Once -At $at `\n  -RepetitionInterval (New-TimeSpan -Days 1)",
        "$t = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Hours 24)",
        "$t = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval ([timespan]::FromDays(1))",
        "$t = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval '1.00:00:00'",
        "$t = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval 'P1D'",
        "$c = $definition.Triggers.Create(2)",
        "$c = $definition.Triggers.Create( 3 )",
        "schtasks /Create /TN WeatherX /SC DAILY /ST 00:30 /TR x.exe",
        "$x = '<CalendarTrigger><StartBoundary>2026-10-01T00:30:00-04:00</StartBoundary>'",
    ]
    for snippet in caught:
        assert _powershell_offenses(snippet), snippet
    allowed = [
        "$t = New-WeatherLocalDailyTrigger -At $At",
        "$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `\n"
        "  -RepetitionInterval (New-TimeSpan -Minutes 1) `\n  -RepetitionDuration (New-TimeSpan -Days 3650)",
        "$t = New-ScheduledTaskTrigger -Once -At $runAt",
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME",
        "$c = $definition.Triggers.Create(1)",
        "function New-ScheduledTaskTrigger { param([switch]$Daily, $At) }",
        "# New-ScheduledTaskTrigger -Daily -At 00:30 in a comment",
        "$x = '<StartBoundary>2026-10-07T06:50:00</StartBoundary>'",
    ]
    for snippet in allowed:
        assert _powershell_offenses(snippet) == [], snippet
    assert _python_offenses('subprocess.run(["schtasks", "/create", "/sc", "daily"])')
    assert _python_offenses('subprocess.run(["schtasks", "/run", "/tn", name])') == []


def test_no_script_anywhere_builds_a_zoned_or_fixed_instant_daily_trigger():
    # Whole repository, not only scripts/ops: PowerShell (backtick splits joined),
    # Python outside tests (schtasks, COM) and task XML.
    offenders = []
    for path in _powershell_files():
        if path == HELPER:
            continue
        offenders += [f"{path.relative_to(ROOT)}: {item}" for item in _powershell_offenses(_source(path))]
    for path in _walk((".py",), tuple(ROOT / name for name in PYTHON_ROOTS)):
        offenders += [f"{path.relative_to(ROOT)}: {item}" for item in _python_offenses(_source(path))]
    for path in _walk((".xml",), (ROOT,)):
        if ZONED_XML.search(_source(path)):
            offenders.append(f"{path.relative_to(ROOT)}: zoned StartBoundary in task XML")
    assert offenders == [], "daily triggers must use New-WeatherLocalDailyTrigger: " + "; ".join(offenders)


def test_daily_registrar_inventory_is_exact_and_reads_back_without_a_zone():
    users = {
        path
        for path in _powershell_files()
        if path != HELPER and "New-WeatherLocalDailyTrigger" in _code(_source(path))
    }
    assert users == {OPS / name for name in DAILY_REGISTRARS}
    for name in DAILY_REGISTRARS:
        code = _code(_source(OPS / name))
        assert '"scheduled_task_local_trigger.ps1")' in code or "'scheduled_task_local_trigger.ps1')" in code, name
        assert "Test-WeatherLocalDailyStartBoundary" in code, name
        # The [datetime] cast converts a zoned boundary to local time and hides the
        # fixed offset ("2026-10-01T00:30:00-04:00" reads "00:30"); it is not a read-back.
        assert not re.search(r"StartBoundary\)\.ToString\(", code), name


# --------------------------------------------------------------------------- Windows execution


AST_PROBE = r"""
# [string] drops Get-Content's PSPath note properties, which ConvertTo-Json would serialize.
$files = @(Get-Content -LiteralPath $env:AST_FILES_PATH -Encoding UTF8 | ForEach-Object { [string]$_ } | Where-Object { $_ })
$rows = foreach ($file in $files) {
    $parsed = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -ne 0) {
        [pscustomobject]@{ file = $file; line = 0; kind = 'parse_error'; detail = [string]$errors[0].Message; interval = '' }
        continue
    }
    $nodes = $parsed.FindAll({
        param($n)
        ($n -is [System.Management.Automation.Language.CommandAst] -and
            $n.GetCommandName() -eq 'New-ScheduledTaskTrigger') -or
        ($n -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and
            [string]$n.Member.Extent.Text -eq 'Create' -and $n.Expression.Extent.Text -match 'Triggers$')
    }, $true)
    foreach ($node in $nodes) {
        if ($node -is [System.Management.Automation.Language.CommandAst]) {
            $names = @()
            $interval = ''
            $elements = @($node.CommandElements)
            for ($i = 0; $i -lt $elements.Count; $i++) {
                if ($elements[$i] -is [System.Management.Automation.Language.CommandParameterAst]) {
                    $names += $elements[$i].ParameterName
                    if ($elements[$i].ParameterName -eq 'RepetitionInterval') {
                        if ($elements[$i].Argument) { $interval = $elements[$i].Argument.Extent.Text }
                        elseif ($i + 1 -lt $elements.Count) { $interval = $elements[$i + 1].Extent.Text }
                    }
                }
            }
            [pscustomobject]@{ file = $file; line = $node.Extent.StartLineNumber; kind = 'cmdlet'
                detail = (@($names) -join ','); interval = $interval }
        } else {
            [pscustomobject]@{ file = $file; line = $node.Extent.StartLineNumber; kind = 'com'
                detail = (@($node.Arguments | ForEach-Object { $_.Extent.Text }) -join ','); interval = '' }
        }
    }
}
[pscustomobject]@{ rows = @($rows) } | ConvertTo-Json -Compress -Depth 4
"""


def _ast_offenses(rows: list[dict]) -> list[str]:
    offenders = []
    for row in rows:
        where = f"{Path(row['file']).name}:{row['line']}"
        if row["kind"] == "parse_error":
            offenders.append(f"{where} does not parse: {row['detail']}")
        elif row["kind"] == "com" and re.fullmatch(r"\s*[2-5]\s*", row["detail"] or ""):
            offenders.append(f"{where} COM calendar trigger")
        elif row["kind"] == "cmdlet":
            names = {name.lower() for name in (row["detail"] or "").split(",") if name}
            if names & {"daily", "weekly", "monthly"}:
                if Path(row["file"]) != HELPER:
                    offenders.append(f"{where} calendar trigger")
            elif "once" in names and row["interval"] and DAY_INTERVAL.search("-RepetitionInterval " + row["interval"]):
                offenders.append(f"{where} -Once with a daily repetition")
    return offenders


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_powershell_ast_finds_no_calendar_trigger_outside_the_helper(tmp_path):
    # The real parser sees through backtick splits and also proves every script
    # parses. A planted file proves the probe is not blind.
    planted = tmp_path / "planted.ps1"
    planted.write_text(
        "$t = New-ScheduledTaskTrigger `\n    -Daily `\n    -At '00:30'\n"
        "$c = $def.Triggers.Create(2)\n"
        "$o = New-ScheduledTaskTrigger -Once -At $a `\n  -RepetitionInterval (New-TimeSpan -Days 1)\n",
        encoding="utf-8",
    )
    files = [str(path) for path in _powershell_files()] + [str(planted)]
    listing = tmp_path / "files.txt"
    listing.write_text("\n".join(files), encoding="utf-8")
    payload = _run(AST_PROBE, {"AST_FILES_PATH": str(listing)})
    rows = payload["rows"]
    offenders = _ast_offenses(rows)

    assert sorted(item for item in offenders if item.startswith("planted.ps1")) == [
        "planted.ps1:1 calendar trigger",
        "planted.ps1:4 COM calendar trigger",
        "planted.ps1:5 -Once with a daily repetition",
    ], offenders
    real = [item for item in offenders if not item.startswith("planted.ps1")]
    assert real == [], "; ".join(real)
    # The helper's own daily call is seen, so the probe is not filtering it away silently.
    assert any(Path(row["file"]) == HELPER and row["kind"] == "cmdlet" for row in rows)


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
