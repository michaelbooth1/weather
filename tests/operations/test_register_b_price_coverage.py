"""R19 daily B-1 coverage-count task: registrar and its checked-in task XML.

Guards: owner yes 2026-11-05 ("approve recommendations", DECISION_LOG) to register the R19 daily
b_price_coverage task. The canonical definition is scripts/ops/tasks/WeatherBPriceCoverage.xml: one
unzoned daily CalendarTrigger at 04:35 local, IgnoreNew, no StartWhenAvailable, PT10M limit,
current-user S4U/Limited, one action running b_price_coverage.ps1 in its catch-up default with
-MaxRuntimeSeconds 540 and nothing else. The slot sits after the 04:15 WeatherMg2InputExport and before
the 04:45-06:45 tiering reserve (OPERATIONS_DESIGN "B-1 coverage counts"). -WhatIf prints that exact XML
and touches nothing. The non-WhatIf path refuses off the capture host before any Scheduler call, and the
readback rejects every drift from the definition.

No case touches the real Task Scheduler. Every registrar run goes through a wrapper that starts with
tests/scheduler_stubs.py's prologue (WEATHER_TASK_TEST plus a breakpoint ledger) and replaces each
ScheduledTasks cmdlet with a global stub that records the call and throws (the pattern of
test_register_maker_evidence_torn_quarantine.py). The readback check is cut out of the registrar by the
PowerShell AST and fed plain objects.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from tests import scheduler_stubs

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
REGISTRAR = OPS / "register_b_price_coverage.ps1"
TEMPLATE = OPS / "tasks" / "WeatherBPriceCoverage.xml"
COVERAGE = OPS / "b_price_coverage.ps1"
LOCAL_TRIGGER = OPS / "scheduled_task_local_trigger.ps1"
TEST_GUARD = OPS / "scheduled_task_test_guard.ps1"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
TOKENS = {"__WEATHER_USER_ID__": 1, "__WEATHER_REPO_ROOT__": 2, "__WEATHER_POWERSHELL__": 1}
ARGUMENTS = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File '
             '"__WEATHER_REPO_ROOT__\\scripts\\ops\\b_price_coverage.ps1" -MaxRuntimeSeconds 540')
POWERSHELL = shutil.which("powershell.exe")
windows_only = pytest.mark.skipif(os.name != "nt" or POWERSHELL is None,
                                  reason="Windows PowerShell 5.1 required")
pytestmark = [pytest.mark.spawns]

STUBS = "".join(
    f"function global:{name} {{ Add-Content -LiteralPath $env:FAKE_CALLS -Value '{name}'; "
    f"throw 'UNEXPECTED_SCHEDULER_CALL {name}' }}\n" for name in scheduler_stubs.SCHEDULER_COMMANDS
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def powershell_exe() -> str:
    return os.path.join(os.environ["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def render(root: Path) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    for token, value in (("__WEATHER_USER_ID__", os.environ["USERNAME"]),
                         ("__WEATHER_REPO_ROOT__", str(root)),
                         ("__WEATHER_POWERSHELL__", powershell_exe())):
        text = text.replace(token, escape(value))
    return text


def run_registrar(tmp_path: Path, script: Path, *args: str):
    ledger = tmp_path / "scheduler_ledger.jsonl"
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(scheduler_stubs.prologue(ledger) + STUBS + "& $env:FAKE_SCRIPT @args\nexit $LASTEXITCODE\n",
                       encoding="utf-8")
    calls = tmp_path / "scheduler_calls.txt"
    env = {**os.environ, "FAKE_SCRIPT": str(script), "FAKE_CALLS": str(calls)}
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(wrapper), *args], capture_output=True, text=True, env=env,
                            timeout=120, check=False)
    scheduler_stubs.assert_only_stubs_invoked(ledger, set())
    return result, (calls.read_text(encoding="utf-8").split() if calls.exists() else [])


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "prod repo & co"
    (repo / "scripts" / "ops" / "tasks").mkdir(parents=True)
    for source in (REGISTRAR, COVERAGE, LOCAL_TRIGGER, TEST_GUARD):
        shutil.copyfile(source, repo / "scripts" / "ops" / source.name)
    shutil.copyfile(TEMPLATE, repo / "scripts" / "ops" / "tasks" / TEMPLATE.name)
    return repo


def snapshot(base: Path) -> dict[str, str]:
    return {p.relative_to(base).as_posix(): sha256(p) for p in sorted(base.rglob("*")) if p.is_file()}


def parsed_task() -> ET.Element:
    return ET.fromstring(TEMPLATE.read_bytes().replace(b'encoding="UTF-16"', b'encoding="UTF-8"'))


def minutes(hhmm: str) -> int:
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def test_checked_in_xml_is_the_reviewed_task_contract():
    raw = TEMPLATE.read_bytes()
    assert raw.isascii() and b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("ascii")
    for token, count in TOKENS.items():
        assert text.count(token) == count, token
    assert text.count("__WEATHER_") == sum(TOKENS.values())
    assert "C:\\" not in text and "<UserId>__WEATHER_USER_ID__</UserId>" in text
    task = parsed_task()

    def one(path: str) -> str:
        found = task.findall(path, NS)
        assert len(found) == 1, path
        return (found[0].text or "").strip()

    assert one("t:RegistrationInfo/t:URI") == "\\WeatherBPriceCoverage"
    triggers = task.find("t:Triggers", NS)
    assert [child.tag.split("}")[1] for child in triggers] == ["CalendarTrigger"]
    calendar = triggers[0]
    assert [child.tag.split("}")[1] for child in calendar] == ["StartBoundary", "Enabled", "ScheduleByDay"]
    # Unzoned local wall time (DST-C1): no Z and no +/-hh:mm suffix.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T04:35:00", one("t:Triggers/t:CalendarTrigger/t:StartBoundary"))
    assert one("t:Triggers/t:CalendarTrigger/t:Enabled") == "true"
    assert one("t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval") == "1"
    assert one("t:Principals/t:Principal/t:UserId") == "__WEATHER_USER_ID__"
    assert one("t:Principals/t:Principal/t:LogonType") == "S4U"
    assert one("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"
    settings = {child.tag.split("}")[1]: (child.text or "").strip() for child in task.find("t:Settings", NS)}
    assert settings == {
        "MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false", "AllowHardTerminate": "true", "StartWhenAvailable": "false",
        "RunOnlyIfNetworkAvailable": "false", "IdleSettings": "", "AllowStartOnDemand": "true",
        "Enabled": "true", "Hidden": "false", "RunOnlyIfIdle": "false", "WakeToRun": "false",
        "ExecutionTimeLimit": "PT10M", "Priority": "7",
    }
    assert len(task.findall("t:Actions/t:Exec", NS)) == 1 and task.find("t:Actions/t:ComHandler", NS) is None
    assert one("t:Actions/t:Exec/t:Command") == "__WEATHER_POWERSHELL__"
    # Catch-up default: no -Date, no -PlanOnly, no -ProductionRepoRoot override.
    assert one("t:Actions/t:Exec/t:Arguments") == ARGUMENTS
    assert one("t:Actions/t:Exec/t:WorkingDirectory") == "__WEATHER_REPO_ROOT__"


def test_slot_fits_between_the_mg2_export_and_the_tiering_reserve():
    task = parsed_task()
    start = minutes(task.find("t:Triggers/t:CalendarTrigger/t:StartBoundary", NS).text[11:16])
    limit = re.fullmatch(r"PT(\d+)M", task.find("t:Settings/t:ExecutionTimeLimit", NS).text)
    scheduler_end = start + int(limit.group(1))
    runtime = int(re.search(r"-MaxRuntimeSeconds (\d+)$", ARGUMENTS).group(1))
    # The wrapper's own deadline and its 5 s job teardown come before the Scheduler backstop.
    assert start * 60 + runtime + 30 <= scheduler_end * 60
    # The wrapper accepts the value (ValidateRange(60, 7200)) and still keeps 120 s for a child.
    assert "[ValidateRange(60, 7200)][int]$MaxRuntimeSeconds" in COVERAGE.read_text(encoding="utf-8")
    assert 120 <= runtime <= 7200
    # Inside the 00:30-09:00 heavy window, after the 01:00-04:00 quiet merge window.
    assert minutes("04:00") <= start and scheduler_end <= minutes("09:00")
    # After WeatherMg2InputExport's first trigger (read from its registrar, not restated).
    mg2 = (OPS / "register_mg2_input_export.ps1").read_text(encoding="utf-8")
    mg2_times = re.search(r"\$triggerTimes = @\('(\d\d:\d\d)', '(\d\d:\d\d)'\)", mg2).groups()
    assert mg2_times == ("04:15", "07:00")
    assert start >= minutes(mg2_times[0]) + 15 and scheduler_end <= minutes(mg2_times[1])
    # The tiering reserve, the merge blackout, the cold-snapshot nightly and the r28b trim window.
    for begin, end in (("04:45", "06:45"), ("05:45", "06:08"), ("06:50", "09:00"), ("07:30", "09:00")):
        assert scheduler_end <= minutes(begin) or start >= minutes(end), (begin, end)


@windows_only
def test_whatif_prints_the_exact_xml_and_touches_nothing(tmp_path):
    repo = fixture_repo(tmp_path)
    before = snapshot(tmp_path)
    script = repo / "scripts" / "ops" / REGISTRAR.name
    result, calls = run_registrar(tmp_path, script, "-ExpectedSourceTip", "a" * 40,
                                  "-ExpectedScriptSha256", sha256(COVERAGE), "-WhatIf")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == []
    assert snapshot(tmp_path) == {**before, "wrapper.ps1": sha256(tmp_path / "wrapper.ps1")}
    lines = result.stdout.splitlines()
    plan = json.loads(next(line for line in lines if line.startswith("{")))
    printed = result.stdout[result.stdout.index("<?xml"):]
    expected = render(repo)
    assert printed.strip() == expected.strip()
    assert "&amp; co" in printed and "__WEATHER_" not in printed
    assert plan["registered"] is False and plan["task_name"] == "WeatherBPriceCoverage"
    assert plan["task_path"] == "\\" and plan["repo_root"] == str(repo)
    assert plan["user_id"] == os.environ["USERNAME"]
    assert plan["planned_action"].startswith(
        "Register-ScheduledTask -TaskName WeatherBPriceCoverage -TaskPath \\ -Xml")
    assert plan["trigger_local_daily"] == "04:35" and plan["execution_time_limit"] == "PT10M"
    assert plan["max_runtime_seconds"] == 540
    assert plan["template_sha256"] == sha256(TEMPLATE)
    assert plan["coverage_script_sha256"] == sha256(COVERAGE)
    assert plan["task_xml_sha256_utf8"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert plan["expected_source_tip"] == "a" * 40


@windows_only
def test_both_modes_refuse_a_pin_mismatch(tmp_path):
    repo = fixture_repo(tmp_path)
    script = repo / "scripts" / "ops" / REGISTRAR.name
    for extra in (["-WhatIf"], []):
        result, calls = run_registrar(tmp_path, script, "-ExpectedSourceTip", "a" * 40,
                                      "-ExpectedScriptSha256", "0" * 64, *extra)
        assert result.returncode != 0
        assert "not ExpectedScriptSha256" in result.stderr + result.stdout
        assert "<?xml" not in result.stdout and calls == []


@windows_only
def test_registration_refuses_before_any_scheduler_call_off_the_capture_host(tmp_path):
    # Real registrar in this checkout, real pin, impossible tip: the workstation and CI fail the host
    # check; the capture host itself fails the tip check. Either way no Scheduler cmdlet is reached.
    result, calls = run_registrar(tmp_path, REGISTRAR, "-ExpectedSourceTip", "a" * 40,
                                  "-ExpectedScriptSha256", sha256(COVERAGE))
    assert result.returncode != 0
    output = result.stderr + result.stdout
    assert ("restricted to the dedicated capture host" in output) or ("Reviewed source tip mismatch" in output), output
    assert calls == [] and "UNEXPECTED_SCHEDULER_CALL" not in output


@windows_only
def test_the_action_binds_to_the_catch_up_default(tmp_path):
    # The exact argument tail of the task action, plus -PlanOnly, binds against the real wrapper: catch-up,
    # the 540 s cap and the repository root derived from the script's own path. -PlanOnly stops before any
    # host check, lease, read or write.
    repo = fixture_repo(tmp_path)
    before = snapshot(tmp_path)
    script = repo / "scripts" / "ops" / COVERAGE.name
    tail = ARGUMENTS.split('b_price_coverage.ps1" ', 1)[1].split()
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script), *tail, "-PlanOnly"], capture_output=True, text=True,
                            timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout.strip().splitlines()[-1])
    assert plan["target_date"] == "catch-up" and plan["max_runtime_seconds"] == 540
    assert plan["production_repo_root"] == str(repo)
    assert plan["child_arguments"][-1] == "--catch-up" and "--date" not in plan["child_arguments"]
    assert snapshot(tmp_path) == before


READBACK = r"""
$ErrorActionPreference = 'Stop'
. $env:LOCAL_TRIGGER_PATH
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:REG_PATH, [ref]$null, [ref]$null)
foreach ($name in 'ConvertTo-BPriceCoverageTaskXml', 'Test-BPriceCoverageTaskReadback') {
    $fn = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq $name }, $true))
    if ($fn.Count -ne 1) { throw "function $name not found" }
    . ([scriptblock]::Create($fn[0].Extent.Text))
}
$template = [IO.File]::ReadAllText($env:TEMPLATE_PATH)
$text = ConvertTo-BPriceCoverageTaskXml -Template $template -UserId 'svc' -RepoRoot 'D:\prod' -PowerShell 'C:\ps.exe'
$definition = [xml]$text
$boundary = [string]$definition.Task.Triggers.CalendarTrigger.StartBoundary
function New-Fake {
    [pscustomobject]@{ TaskPath = '\'
        Principal = [pscustomobject]@{ UserId = 'SVC'; LogonType = 'S4U'; RunLevel = 'Limited' }
        Actions = @([pscustomobject]@{ Execute = 'c:\PS.exe'; WorkingDirectory = 'd:\prod'
            Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "D:\prod\scripts\ops\b_price_coverage.ps1" -MaxRuntimeSeconds 540' })
        Triggers = @([pscustomobject]@{ CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskDailyTrigger' }
            Enabled = $true; DaysInterval = 1; StartBoundary = $boundary; EndBoundary = $null; RandomDelay = $null
            Repetition = [pscustomobject]@{ Interval = $null; Duration = $null; StopAtDurationEnd = $false } })
        Settings = [pscustomobject]@{ Enabled = $true; MultipleInstances = 'IgnoreNew'; StartWhenAvailable = $false
            ExecutionTimeLimit = 'PT10M'; DisallowStartIfOnBatteries = $false; StopIfGoingOnBatteries = $false
            RunOnlyIfIdle = $false; RunOnlyIfNetworkAvailable = $false; WakeToRun = $false; Hidden = $false
            AllowHardTerminate = $true; Priority = 7 } }
}
$mutations = [ordered]@{
    exact = { }
    path = { $f.TaskPath = '\Other\' }
    disabled = { $f.Settings.Enabled = $false }
    user = { $f.Principal.UserId = 'other' }
    interactive = { $f.Principal.LogonType = 'Interactive' }
    highest = { $f.Principal.RunLevel = 'Highest' }
    two_actions = { $f.Actions = @($f.Actions[0], $f.Actions[0]) }
    executable = { $f.Actions[0].Execute = 'C:\pwsh.exe' }
    arguments = { $f.Actions[0].Arguments += ' -Date 2026-11-04' }
    workdir = { $f.Actions[0].WorkingDirectory = 'D:\elsewhere' }
    weekly_trigger = { $f.Triggers[0].CimClass.CimClassName = 'MSFT_TaskWeeklyTrigger' }
    two_triggers = { $f.Triggers = @($f.Triggers[0], $f.Triggers[0]) }
    trigger_off = { $f.Triggers[0].Enabled = $false }
    days_interval = { $f.Triggers[0].DaysInterval = 2 }
    zoned_same_boundary = { $f.Triggers[0].StartBoundary = $boundary + '-05:00' }
    other_date = { $f.Triggers[0].StartBoundary = '2027-01-01T04:35:00' }
    end_boundary = { $f.Triggers[0].EndBoundary = '2026-12-13T00:00:00' }
    random_delay = { $f.Triggers[0].RandomDelay = 'PT5M' }
    repetition = { $f.Triggers[0].Repetition.Interval = 'PT1H' }
    parallel = { $f.Settings.MultipleInstances = 'Parallel' }
    start_when_available = { $f.Settings.StartWhenAvailable = $true }
    limit = { $f.Settings.ExecutionTimeLimit = 'PT72H' }
    battery_start = { $f.Settings.DisallowStartIfOnBatteries = $true }
    battery_stop = { $f.Settings.StopIfGoingOnBatteries = $true }
    idle = { $f.Settings.RunOnlyIfIdle = $true }
    network = { $f.Settings.RunOnlyIfNetworkAvailable = $true }
    wake = { $f.Settings.WakeToRun = $true }
    hidden = { $f.Settings.Hidden = $true }
    hard_terminate = { $f.Settings.AllowHardTerminate = $false }
    priority = { $f.Settings.Priority = 4 }
}
$out = [ordered]@{}
foreach ($key in $mutations.Keys) {
    $f = New-Fake
    . $mutations[$key]
    $out[$key] = @(Test-BPriceCoverageTaskReadback -Task @($f) -Definition $definition -At '04:35')
}
$out['two_tasks'] = @(Test-BPriceCoverageTaskReadback -Task @((New-Fake), (New-Fake)) -Definition $definition -At '04:35')
$out['other_time'] = @(Test-BPriceCoverageTaskReadback -Task @((New-Fake)) -Definition $definition -At '04:36')
$refusals = [ordered]@{}
$cases = [ordered]@{
    missing_token = @($template.Replace('__WEATHER_POWERSHELL__', 'x'), 'svc', 'D:\prod')
    extra_token = @(($template + '__WEATHER_USER_ID__'), 'svc', 'D:\prod')
    unknown_token = @(($template + '__WEATHER_OTHER__'), 'svc', 'D:\prod')
    quoted_root = @($template, 'svc', 'D:\pr"od')
    relative_root = @($template, 'svc', 'prod')
    domain_user = @($template, 'HOST\svc', 'D:\prod')
}
foreach ($key in $cases.Keys) {
    $c = $cases[$key]
    try { $null = ConvertTo-BPriceCoverageTaskXml -Template $c[0] -UserId $c[1] -RepoRoot $c[2] -PowerShell 'C:\ps.exe'; $refusals[$key] = '' }
    catch { $refusals[$key] = $_.Exception.Message }
}
@{ readback = $out; refusals = $refusals } | ConvertTo-Json -Compress -Depth 4
"""


@windows_only
def test_readback_rejects_every_drift_and_rendering_refuses_bad_inputs(tmp_path):
    env = {**os.environ, "REG_PATH": str(REGISTRAR), "TEMPLATE_PATH": str(TEMPLATE),
           "LOCAL_TRIGGER_PATH": str(LOCAL_TRIGGER)}
    probe = tmp_path / "readback.ps1"
    probe.write_text(READBACK, encoding="utf-8")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(probe)], capture_output=True, text=True, env=env, timeout=120,
                            check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    readback = payload["readback"]
    assert readback.pop("exact") == []
    expected = {
        "path": ["task path"], "disabled": ["enabled"], "user": ["principal user"],
        "interactive": ["principal logon type S4U"], "highest": ["principal run level Limited"],
        "two_actions": ["one action"], "executable": ["action executable"], "arguments": ["action arguments"],
        "workdir": ["action working directory"], "weekly_trigger": ["daily trigger"],
        "two_triggers": ["one trigger"], "trigger_off": ["trigger enabled"], "days_interval": ["every day"],
        "zoned_same_boundary": ["local unzoned start 04:35", "start boundary as defined"],
        "other_date": ["start boundary as defined"], "end_boundary": ["no end boundary"],
        "random_delay": ["no random delay"], "repetition": ["no repetition"],
        "parallel": ["IgnoreNew"], "start_when_available": ["no StartWhenAvailable"],
        "limit": ["execution time limit PT10M"], "battery_start": ["starts on batteries"],
        "battery_stop": ["keeps running on batteries"], "idle": ["not idle gated"],
        "network": ["not network gated"], "wake": ["no wake"], "hidden": ["not hidden"],
        "hard_terminate": ["hard terminate allowed"], "priority": ["priority 7"],
        "two_tasks": ["expected exactly one task, found 2"], "other_time": ["local unzoned start 04:36"],
    }
    assert readback == expected
    refusals = payload["refusals"]
    assert "__WEATHER_POWERSHELL__ exactly 1" in refusals["missing_token"]
    assert "__WEATHER_USER_ID__ exactly 1" in refusals["extra_token"]
    assert "unknown placeholder" in refusals["unknown_token"]
    assert "not an absolute path" in refusals["quoted_root"]
    assert "not an absolute path" in refusals["relative_root"]
    assert "bare current user name" in refusals["domain_user"]
