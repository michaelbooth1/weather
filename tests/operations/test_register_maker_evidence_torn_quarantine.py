"""Torn-journal quarantine Stage 2 registrar and its checked-in task XML.

Guards: owner yes 2026-11-02 for one startup task (L54 design section 4 and 11). The canonical
definition is scripts/ops/tasks/WeatherMakerEvidenceTornQuarantine.xml: boot trigger, no delay,
every minute for 15 minutes, IgnoreNew, no StartWhenAvailable, 5-minute limit, current-user
S4U/Limited, one action running the Stage 1 script with -Apply and nothing else. -WhatIf prints
that exact XML and touches nothing. The non-WhatIf path refuses off the capture host before any
Scheduler call, and the readback rejects every drift from the definition.
Runbook: docs/operations/passive-maker-evidence-capture.md (torn-journal quarantine at boot).

No case touches the real Task Scheduler. Every PowerShell run goes through a wrapper that
replaces each ScheduledTasks cmdlet the registrar could reach with a global stub that records
the call and throws (the stub pattern of test_maker_evidence_torn_quarantine_script.py). The
readback check is cut out of the registrar by the PowerShell AST and fed plain objects.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
REGISTRAR = OPS / "register_maker_evidence_torn_quarantine.ps1"
TEMPLATE = OPS / "tasks" / "WeatherMakerEvidenceTornQuarantine.xml"
STAGE1 = OPS / "maker_evidence_torn_quarantine.ps1"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
TOKENS = {"__WEATHER_USER_ID__": 1, "__WEATHER_REPO_ROOT__": 2, "__WEATHER_POWERSHELL__": 1}
POWERSHELL = shutil.which("powershell.exe")
windows_only = pytest.mark.skipif(os.name != "nt" or POWERSHELL is None,
                                  reason="Windows PowerShell 5.1 required")
pytestmark = [pytest.mark.spawns, windows_only]

SCHEDULER_CMDLETS = ("Register-ScheduledTask", "Get-ScheduledTask", "Export-ScheduledTask",
                     "Disable-ScheduledTask", "Enable-ScheduledTask", "Unregister-ScheduledTask",
                     "Set-ScheduledTask", "Start-ScheduledTask", "Stop-ScheduledTask",
                     "Get-ScheduledTaskInfo")
WRAPPER = "Import-Module ScheduledTasks\n" + "".join(
    f"function global:{name} {{ Add-Content -LiteralPath $env:FAKE_CALLS -Value '{name}'; "
    f"throw 'UNEXPECTED_SCHEDULER_CALL {name}' }}\n" for name in SCHEDULER_CMDLETS
) + "& $env:FAKE_SCRIPT @args\nexit $LASTEXITCODE\n"


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
    wrapper = tmp_path / "wrapper.ps1"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    calls = tmp_path / "scheduler_calls.txt"
    env = {**os.environ, "FAKE_SCRIPT": str(script), "FAKE_CALLS": str(calls)}
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(wrapper), *args], capture_output=True, text=True, env=env,
                            timeout=120, check=False)
    return result, (calls.read_text(encoding="utf-8").split() if calls.exists() else [])


def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "prod repo & co"
    (repo / "scripts" / "ops" / "tasks").mkdir(parents=True)
    for source in (REGISTRAR, STAGE1):
        shutil.copyfile(source, repo / "scripts" / "ops" / source.name)
    shutil.copyfile(TEMPLATE, repo / "scripts" / "ops" / "tasks" / TEMPLATE.name)
    return repo


def snapshot(base: Path) -> dict[str, str]:
    return {p.relative_to(base).as_posix(): sha256(p) for p in sorted(base.rglob("*")) if p.is_file()}


def test_checked_in_xml_is_the_reviewed_task_contract():
    raw = TEMPLATE.read_bytes()
    assert raw.isascii() and b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("ascii")
    for token, count in TOKENS.items():
        assert text.count(token) == count, token
    assert text.count("__WEATHER_") == sum(TOKENS.values())
    assert "C:\\" not in text and os.environ.get("USERNAME", "Michael") not in text
    task = ET.fromstring(raw.replace(b'encoding="UTF-16"', b'encoding="UTF-8"'))

    def one(path: str) -> str:
        found = task.findall(path, NS)
        assert len(found) == 1, path
        return (found[0].text or "").strip()

    assert one("t:RegistrationInfo/t:URI") == "\\WeatherMakerEvidenceTornQuarantine"
    triggers = task.find("t:Triggers", NS)
    assert [child.tag.split("}")[1] for child in triggers] == ["BootTrigger"]
    boot = triggers[0]
    assert boot.find("t:Delay", NS) is None and boot.find("t:StartBoundary", NS) is None
    assert one("t:Triggers/t:BootTrigger/t:Enabled") == "true"
    assert one("t:Triggers/t:BootTrigger/t:Repetition/t:Interval") == "PT1M"
    assert one("t:Triggers/t:BootTrigger/t:Repetition/t:Duration") == "PT15M"
    assert one("t:Triggers/t:BootTrigger/t:Repetition/t:StopAtDurationEnd") == "false"
    assert one("t:Principals/t:Principal/t:UserId") == "__WEATHER_USER_ID__"
    assert one("t:Principals/t:Principal/t:LogonType") == "S4U"
    assert one("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"
    settings = {child.tag.split("}")[1]: (child.text or "").strip() for child in task.find("t:Settings", NS)}
    assert settings == {
        "MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false", "AllowHardTerminate": "true", "StartWhenAvailable": "false",
        "RunOnlyIfNetworkAvailable": "false", "IdleSettings": "", "AllowStartOnDemand": "true",
        "Enabled": "true", "Hidden": "false", "RunOnlyIfIdle": "false", "WakeToRun": "false",
        "ExecutionTimeLimit": "PT5M", "Priority": "7",
    }
    assert len(task.findall("t:Actions/t:Exec", NS)) == 1 and task.find("t:Actions/t:ComHandler", NS) is None
    assert one("t:Actions/t:Exec/t:Command") == "__WEATHER_POWERSHELL__"
    assert one("t:Actions/t:Exec/t:Arguments") == (
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File '
        '"__WEATHER_REPO_ROOT__\\scripts\\ops\\maker_evidence_torn_quarantine.ps1" -Apply')
    assert one("t:Actions/t:Exec/t:WorkingDirectory") == "__WEATHER_REPO_ROOT__"


def test_whatif_prints_the_exact_xml_and_touches_nothing(tmp_path):
    repo = fixture_repo(tmp_path)
    before = snapshot(tmp_path)
    script = repo / "scripts" / "ops" / REGISTRAR.name
    result, calls = run_registrar(tmp_path, script, "-ExpectedSourceTip", "a" * 40,
                                  "-ExpectedScriptSha256", sha256(STAGE1), "-WhatIf")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == []
    assert snapshot(tmp_path) == {**before, "wrapper.ps1": sha256(tmp_path / "wrapper.ps1")}
    lines = result.stdout.splitlines()
    plan = json.loads(next(line for line in lines if line.startswith("{")))
    printed = result.stdout[result.stdout.index("<?xml"):]
    expected = render(repo)
    assert printed.strip() == expected.strip()
    assert "&amp; co" in printed and "__WEATHER_" not in printed
    assert plan["registered"] is False and plan["task_name"] == "WeatherMakerEvidenceTornQuarantine"
    assert plan["task_path"] == "\\" and plan["repo_root"] == str(repo)
    assert plan["user_id"] == os.environ["USERNAME"]
    assert plan["planned_action"].startswith(
        "Register-ScheduledTask -TaskName WeatherMakerEvidenceTornQuarantine -TaskPath \\ -Xml")
    assert plan["template_sha256"] == sha256(TEMPLATE)
    assert plan["quarantine_script_sha256"] == sha256(STAGE1)
    assert plan["task_xml_sha256_utf8"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    assert plan["expected_source_tip"] == "a" * 40


def test_both_modes_refuse_a_stage1_script_hash_mismatch(tmp_path):
    repo = fixture_repo(tmp_path)
    script = repo / "scripts" / "ops" / REGISTRAR.name
    for extra in (["-WhatIf"], []):
        result, calls = run_registrar(tmp_path, script, "-ExpectedSourceTip", "a" * 40,
                                      "-ExpectedScriptSha256", "0" * 64, *extra)
        assert result.returncode != 0
        assert "not ExpectedScriptSha256" in result.stderr + result.stdout
        assert "<?xml" not in result.stdout and calls == []


def test_registration_refuses_before_any_scheduler_call_off_the_capture_host(tmp_path):
    # Real registrar in this checkout, real pin, impossible tip: the workstation and CI fail the host
    # check; the capture host itself fails the tip check. Either way no Scheduler cmdlet is reached.
    result, calls = run_registrar(tmp_path, REGISTRAR, "-ExpectedSourceTip", "a" * 40,
                                  "-ExpectedScriptSha256", sha256(STAGE1))
    assert result.returncode != 0
    output = result.stderr + result.stdout
    assert ("restricted to the dedicated capture host" in output) or ("Reviewed source tip mismatch" in output), output
    assert calls == [] and "UNEXPECTED_SCHEDULER_CALL" not in output


READBACK = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:REG_PATH, [ref]$null, [ref]$null)
foreach ($name in 'ConvertTo-TornQuarantineTaskXml', 'Test-TornQuarantineTaskReadback') {
    $fn = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq $name }, $true))
    if ($fn.Count -ne 1) { throw "function $name not found" }
    . ([scriptblock]::Create($fn[0].Extent.Text))
}
$template = [IO.File]::ReadAllText($env:TEMPLATE_PATH)
$text = ConvertTo-TornQuarantineTaskXml -Template $template -UserId 'svc' -RepoRoot 'D:\prod' -PowerShell 'C:\ps.exe'
$definition = [xml]$text
function New-Fake {
    [pscustomobject]@{ TaskPath = '\'
        Principal = [pscustomobject]@{ UserId = 'SVC'; LogonType = 'S4U'; RunLevel = 'Limited' }
        Actions = @([pscustomobject]@{ Execute = 'c:\PS.exe'; WorkingDirectory = 'd:\prod'
            Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "D:\prod\scripts\ops\maker_evidence_torn_quarantine.ps1" -Apply' })
        Triggers = @([pscustomobject]@{ CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskBootTrigger' }
            Enabled = $true; Delay = $null
            Repetition = [pscustomobject]@{ Interval = 'PT1M'; Duration = 'PT15M'; StopAtDurationEnd = $false } })
        Settings = [pscustomobject]@{ Enabled = $true; MultipleInstances = 'IgnoreNew'; StartWhenAvailable = $false
            ExecutionTimeLimit = 'PT5M'; DisallowStartIfOnBatteries = $false; StopIfGoingOnBatteries = $false
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
    arguments = { $f.Actions[0].Arguments += ' -MaxFiles 1' }
    workdir = { $f.Actions[0].WorkingDirectory = 'D:\elsewhere' }
    logon_trigger = { $f.Triggers[0].CimClass.CimClassName = 'MSFT_TaskLogonTrigger' }
    two_triggers = { $f.Triggers = @($f.Triggers[0], $f.Triggers[0]) }
    trigger_off = { $f.Triggers[0].Enabled = $false }
    delay = { $f.Triggers[0].Delay = 'PT2M' }
    interval = { $f.Triggers[0].Repetition.Interval = 'PT5M' }
    duration = { $f.Triggers[0].Repetition.Duration = '' }
    stop_at_end = { $f.Triggers[0].Repetition.StopAtDurationEnd = $true }
    parallel = { $f.Settings.MultipleInstances = 'Parallel' }
    start_when_available = { $f.Settings.StartWhenAvailable = $true }
    limit = { $f.Settings.ExecutionTimeLimit = 'PT72H' }
    battery = { $f.Settings.StopIfGoingOnBatteries = $true }
    idle = { $f.Settings.RunOnlyIfIdle = $true }
    wake = { $f.Settings.WakeToRun = $true }
    hard_terminate = { $f.Settings.AllowHardTerminate = $false }
    priority = { $f.Settings.Priority = 4 }
}
$out = [ordered]@{}
foreach ($key in $mutations.Keys) {
    $f = New-Fake
    . $mutations[$key]
    $out[$key] = @(Test-TornQuarantineTaskReadback -Task @($f) -Definition $definition)
}
$out['two_tasks'] = @(Test-TornQuarantineTaskReadback -Task @((New-Fake), (New-Fake)) -Definition $definition)
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
    try { $null = ConvertTo-TornQuarantineTaskXml -Template $c[0] -UserId $c[1] -RepoRoot $c[2] -PowerShell 'C:\ps.exe'; $refusals[$key] = '' }
    catch { $refusals[$key] = $_.Exception.Message }
}
@{ readback = $out; refusals = $refusals } | ConvertTo-Json -Compress -Depth 4
"""


def test_readback_rejects_every_drift_and_rendering_refuses_bad_inputs(tmp_path):
    env = {**os.environ, "REG_PATH": str(REGISTRAR), "TEMPLATE_PATH": str(TEMPLATE)}
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
        "path": "task path", "disabled": "enabled", "user": "principal user",
        "interactive": "principal logon type S4U", "highest": "principal run level Limited",
        "two_actions": "one action", "executable": "action executable", "arguments": "action arguments",
        "workdir": "action working directory", "logon_trigger": "boot trigger", "two_triggers": "one trigger",
        "trigger_off": "trigger enabled", "delay": "no trigger delay", "interval": "repetition interval PT1M",
        "duration": "repetition duration PT15M", "stop_at_end": "repetition does not stop at duration end",
        "parallel": "IgnoreNew", "start_when_available": "no StartWhenAvailable",
        "limit": "execution time limit PT5M", "battery": "runs on batteries", "idle": "not idle or network gated",
        "wake": "no wake, not hidden", "hard_terminate": "hard terminate allowed", "priority": "priority 7",
    }
    assert {key: value for key, value in readback.items() if key != "two_tasks"} == {
        key: [problem] for key, problem in expected.items()}
    assert readback["two_tasks"] == ["expected exactly one task, found 2"]
    refusals = payload["refusals"]
    assert "__WEATHER_POWERSHELL__ exactly 1" in refusals["missing_token"]
    assert "__WEATHER_USER_ID__ exactly 1" in refusals["extra_token"]
    assert "unknown placeholder" in refusals["unknown_token"]
    assert "not an absolute path" in refusals["quoted_root"]
    assert "not an absolute path" in refusals["relative_root"]
    assert "bare current user name" in refusals["domain_user"]
