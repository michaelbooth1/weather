"""Native outer Job and scheduler-contract fixtures; no real Scheduler mutation."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import venv

import pytest

from weather.paths import repo_path
from weather.operations.process_lock_identity import observe_process_identity

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows Job and PowerShell contract")
CHILD = '''
import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
for key in ('production-repo-root','plan','plan-sha256','source-git-sha','output-root','segment'):
    p.add_argument('--' + key)
p.add_argument('--preflight-only', action='store_true')
a = p.parse_args()
out = Path(a.output_root)
plan = json.loads(Path(a.plan).read_text())
mode = plan['fixture_mode']
# Prove the real PID+creation token and ancestry implementation on this process.
from weather.operations.storage_recovery_night_steps import runtime_owner
runtime_owner(Path.cwd(), plan['execution_host_id'])
if mode in ('hang','residual'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    (out / 'descendant.json').write_text(json.dumps({'pid': child.pid, 'worker_pid': os.getpid()}))
if mode == 'nested_hang':
    helper = str(Path.cwd() / 'scripts/ops/windows_kill_on_close_job.ps1').replace("'", "''")
    executable = sys.executable.replace("'", "''")
    directory = str(Path.cwd()).replace("'", "''")
    marker = str(out / 'nested-child.json').replace("'", "''")
    nested_script = out / 'nested.ps1'
    nested_script.write_text(
        ". '" + helper + "'\\n$job = New-WeatherKillOnCloseJob\\n"
        "$p = Start-WeatherProcessInJob -Job $job -FilePath '" + executable +
        "' -WorkingDirectory '" + directory +
        "' -ArgumentString '-c \\"import time; time.sleep(300)\\"'\\n"
        "@{pid=$p.Id} | ConvertTo-Json | Set-Content -LiteralPath '" + marker +
        "' -Encoding utf8\\nStart-Sleep -Seconds 300\\n")
    child = subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                              '-File',str(nested_script)], creationflags=subprocess.CREATE_NO_WINDOW)
    (out / 'descendant.json').write_text(json.dumps({'pid': child.pid, 'worker_pid': os.getpid()}))
if mode in ('hang','nested_hang'): time.sleep(300)
if mode == 'failure': raise SystemExit(7)
if mode == 'source_drift': Path('tracked.txt').write_text('changed')
if mode == 'plan_drift': Path(a.plan).write_text('{}')
result = {'status': 'PREFLIGHT_PASS' if a.preflight_only else 'CANDIDATES_EXHAUSTED',
          'source_git_sha': 'd' * 40 if mode == 'wrong_binding' else a.source_git_sha,
          'plan_sha256': a.plan_sha256, 'execution_host_id': plan['execution_host_id'],
          'deleted_files': 0, 'cleanup_eligible': False, 'source_payload_bytes_read': 0,
          'source_files_changed': 1 if mode == 'preflight_write' else 0}
(out / 'result.json').write_text(json.dumps(result))
'''


def command(*args, cwd=None):
    result = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


@pytest.fixture
def native_fixture(tmp_path):
    source, production = tmp_path / "source checkout", tmp_path / "fixture production"
    scripts = source / "scripts/ops"
    scripts.mkdir(parents=True)
    production.mkdir()
    venv.EnvBuilder(with_pip=False).create(production / "venv")
    for name in ("windows_kill_on_close_job.ps1", "workload_admission.ps1",
                 "storage_recovery_night_contract.ps1", "register_storage_recovery_night.ps1"):
        shutil.copy2(repo_path("scripts/ops", name), scripts / name)
    wrapper = repo_path("scripts/ops/storage_recovery_night_run.ps1").read_text(encoding="utf-8-sig")
    wrapper = wrapper.replace("try {\n    $null = New-Item", "try {\n    $deadline = [DateTime]::UtcNow.AddSeconds(6)\n    $null = New-Item")
    (scripts / "storage_recovery_night_run.ps1").write_text(wrapper, encoding="utf-8")
    assignment = json.loads(repo_path("config/international_live_execution_host.json").read_text())
    host = assignment["active_portable_execution_host_id"]
    assignment.update(dedicated_capture_execution_host_id=host, active_portable_execution_host_id=None,
                      active_portable_execution_principal_id=None, assignment_status="UNASSIGNED")
    (source / "config").mkdir()
    (source / "config/international_live_execution_host.json").write_text(json.dumps(assignment))
    # Actual identity/ancestry code is imported, with lightweight fixture stand-ins
    # only for unrelated inventory/evidence imports and repository path discovery.
    package = source / "src/weather"
    (package / "operations").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "operations/__init__.py").write_text("")
    (package / "paths.py").write_text("from pathlib import Path\nROOT=Path(__file__).resolve().parents[2]\nREPO_ROOT=ROOT\ndef repo_path(*parts): return ROOT.joinpath(*parts)\n")
    for name in ("execution_host.py",):
        shutil.copy2(repo_path("src/weather", name), package / name)
    for name in ("storage_recovery_night_steps.py", "windows_processes.py", "process_lock_identity.py"):
        shutil.copy2(repo_path("src/weather/operations", name), package / "operations" / name)
    (package / "operations/storage_recovery_night_contract.py").write_text('ENV="WEATHER_STORAGE_RECOVERY_NIGHT_"\n')
    for name in ("storage_recovery_night_evidence.py", "storage_recovery_inventory.py"):
        (package / "operations" / name).write_text("")
    (package / "operations/storage_recovery_night.py").write_text(CHILD)
    (source / "tracked.txt").write_text("original")
    (source / ".gitignore").write_text("__pycache__/\n")
    command("git", "init", str(source))
    command("git", "-C", str(source), "add", ".")
    command("git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-m", "Isolated night launcher fixture")
    head = command("git", "-C", str(source), "rev-parse", "HEAD")
    return source, production, head, host


@pytest.mark.parametrize("mode,passed", [
    ("success", True), ("residual", True), ("hang", False), ("nested_hang", False), ("failure", False),
    ("wrong_binding", False), ("source_drift", False), ("plan_drift", False), ("preflight_write", False),
])
def test_native_outer_wrapper_binds_preflight_and_contains_descendants(native_fixture, mode, passed):
    source, production, head, host = native_fixture
    now = datetime.now(timezone.utc)
    night = (now + timedelta(days=1)).date()
    # Native tests run on the reviewed Toronto workstation; retain its actual timezone.
    from zoneinfo import ZoneInfo
    expiry = datetime.combine(night, datetime.min.time(), ZoneInfo("America/Toronto")).replace(hour=9)
    plan = {"fixture_mode": mode, "night_date": night.isoformat(), "plan_id": "capacity-" + night.strftime("%Y%m%d") + "-fixture",
        "production_repo_root": str(production), "source_root": str(source), "source_git_sha": head,
        "execution_host_id": host, "approved_at_utc": now.isoformat(),
        "expires_at_utc": expiry.astimezone(timezone.utc).isoformat(), "allow_resource_recovery": True}
    path = production / "plan.json"
    path.write_text(json.dumps(plan))
    args = ["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
            "-File",str(source / "scripts/ops/storage_recovery_night_run.ps1"),
            "-ProductionRepoRoot",str(production),"-PlanPath",str(path),
            "-PlanSha256",hashlib.sha256(path.read_bytes()).hexdigest(),
            "-ExpectedSourceTip",head,"-Segment","early","-PreflightOnly"]
    process = subprocess.Popen(args, cwd=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=40)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    assert (process.returncode == 0) is passed, out + err
    output = production / "scratch/storage_recovery_nights" / plan["plan_id"] / "preflight"
    receipt = json.loads((output / "wrapper-result.json").read_text())
    assert (receipt["status"] == "PASS") is passed
    assert receipt["teardown_proved"] is True
    if mode in {"hang", "nested_hang"}:
        assert receipt["hard_stop"] is True
    if mode in {"residual", "hang", "nested_hang"}:
        for pid in json.loads((output / "descendant.json").read_text()).values():
            assert observe_process_identity(pid)["state"] == "not_found"
    if mode == "nested_hang":
        nested_pid = json.loads((output / "nested-child.json").read_text(encoding="utf-8-sig"))["pid"]
        assert observe_process_identity(nested_pid)["state"] == "not_found"


def test_all_night_powershell_sources_parse_without_execution():
    paths = [repo_path("scripts/ops", name) for name in (
        "storage_recovery_night_contract.ps1", "storage_recovery_night_run.ps1",
        "register_storage_recovery_night.ps1", "cold_snapshot_compression_run.ps1")]
    for path in paths:
        script = ("$tokens=$null; $errors=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile("
                  + "'" + str(path).replace("'", "''") + "',[ref]$tokens,[ref]$errors); "
                  "if ($errors.Count) { $errors | Out-String | Write-Output; exit 1 }")
        command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script)


SCHEDULER_MOCKS = r'''
$ErrorActionPreference = 'Stop'
$global:weatherNightStoredTask = $null
$global:weatherNightFixtureMode = '__MODE__'
$global:weatherNightRegistrationCalls = '__CALLS__'
function Get-ScheduledTask {
    param($TaskName, $TaskPath, $ErrorAction)
    if ($global:weatherNightFixtureMode -eq 'exists') { return [PSCustomObject]@{TaskName=$TaskName} }
    if ($global:weatherNightStoredTask) { return $global:weatherNightStoredTask }
}
function New-ScheduledTaskAction {
    param($Execute, $Argument, $WorkingDirectory)
    return [PSCustomObject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}
}
function New-ScheduledTaskTrigger {
    param([switch]$Once, [datetime]$At)
    return [PSCustomObject]@{StartBoundary=$At.ToString('o'); Enabled=$true
        CimClass=[PSCustomObject]@{CimClassName='MSFT_TaskTimeTrigger'}
        Repetition=[PSCustomObject]@{Interval=''}}
}
function New-ScheduledTaskSettingsSet {
    param($MultipleInstances,[switch]$Hidden,[timespan]$ExecutionTimeLimit,[switch]$WakeToRun,
          [switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries)
    return [PSCustomObject]@{MultipleInstances=$MultipleInstances;Hidden=[bool]$Hidden
        ExecutionTimeLimit=('PT' + [int]$ExecutionTimeLimit.TotalMinutes + 'M')
        StartWhenAvailable=$false;WakeToRun=[bool]$WakeToRun
        DisallowStartIfOnBatteries=(-not $AllowStartIfOnBatteries)
        StopIfGoingOnBatteries=(-not $DontStopIfGoingOnBatteries)}
}
function New-ScheduledTaskPrincipal {
    param($UserId,$LogonType,$RunLevel)
    return [PSCustomObject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}
}
function Register-ScheduledTask {
    param($TaskName,$TaskPath,$Action,$Trigger,$Settings,$Principal,$Description)
    Add-Content -LiteralPath $global:weatherNightRegistrationCalls -Value $TaskName
    if ($global:weatherNightFixtureMode -eq 'drift') { $Settings.StartWhenAvailable=$true }
    $global:weatherNightStoredTask = [PSCustomObject]@{TaskName=$TaskName;TaskPath=$TaskPath;State='Ready'
        Actions=@($Action);Triggers=@($Trigger);Settings=$Settings;Principal=$Principal}
}
function Export-ScheduledTask { param($TaskName,$TaskPath); return '<Task>fixture export</Task>' }
& '__REGISTRAR__' -ProductionRepoRoot '__PRODUCTION__' -PlanPath '__PLAN__' -PlanSha256 '__SHA__' -ExpectedSourceTip '__HEAD__' -PreflightOnly
'''


@pytest.mark.parametrize("mode,passed,calls", [("success", True, 1), ("exists", False, 0), ("drift", False, 1)])
def test_registrar_readback_refuses_reuse_and_settings_drift_without_real_scheduler(native_fixture, mode, passed, calls):
    source, production, head, host = native_fixture
    now = datetime.now(timezone.utc)
    night = (now + timedelta(days=1)).date()
    from zoneinfo import ZoneInfo
    expiry = datetime.combine(night, datetime.min.time(), ZoneInfo("America/Toronto")).replace(hour=9)
    plan = {"night_date": night.isoformat(), "plan_id": "capacity-" + night.strftime("%Y%m%d") + "-fixture",
        "production_repo_root": str(production), "source_root": str(source), "source_git_sha": head,
        "execution_host_id": host, "approved_at_utc": now.isoformat(),
        "expires_at_utc": expiry.astimezone(timezone.utc).isoformat(), "allow_resource_recovery": True}
    path = production / "plan.json"
    path.write_text(json.dumps(plan))
    calls_path = production / "calls.txt"
    replacements = {"__MODE__": mode, "__CALLS__": str(calls_path),
        "__REGISTRAR__": str(source / "scripts/ops/register_storage_recovery_night.ps1"),
        "__PRODUCTION__": str(production), "__PLAN__": str(path),
        "__SHA__": hashlib.sha256(path.read_bytes()).hexdigest(), "__HEAD__": head}
    script = SCHEDULER_MOCKS
    for key, value in replacements.items():
        script = script.replace(key, value.replace("'", "''"))
    harness = production / "harness.ps1"
    harness.write_text(script, encoding="utf-8")
    result = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
                             "-File",str(harness)], capture_output=True, text=True, timeout=40)
    assert (result.returncode == 0) is passed, result.stdout + result.stderr
    observed_calls = calls_path.read_text().splitlines() if calls_path.exists() else []
    assert len(observed_calls) == calls
    receipt = production / "scratch/storage_recovery_nights" / plan["plan_id"] / "registration-preflight/preflight-result.json"
    assert receipt.exists() is passed


@pytest.mark.parametrize("wrong_duration,passed,expected_calls", [(False, True, 2), (True, False, 1)])
def test_both_segments_accept_scheduler_normalized_durations_and_reject_changed_limits(
        native_fixture, wrong_duration, passed, expected_calls):
    source, production, head, host = native_fixture
    now = datetime.now(timezone.utc)
    night = (now + timedelta(days=1)).date()
    from zoneinfo import ZoneInfo
    expiry = datetime.combine(night, datetime.min.time(), ZoneInfo("America/Toronto")).replace(hour=9)
    plan = {"night_date": night.isoformat(), "plan_id": "capacity-" + night.strftime("%Y%m%d") + "-fixture",
        "production_repo_root": str(production), "source_root": str(source), "source_git_sha": head,
        "execution_host_id": host, "approved_at_utc": now.isoformat(),
        "expires_at_utc": expiry.astimezone(timezone.utc).isoformat(), "allow_resource_recovery": True}
    path = production / "plan.json"
    path.write_text(json.dumps(plan))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    night_root = production / "scratch/storage_recovery_nights" / plan["plan_id"]
    preflight = night_root / "preflight"
    preflight.mkdir(parents=True)
    result = preflight / "result.json"
    result.write_text("{}")
    (preflight / "wrapper-result.json").write_text(json.dumps({
        "status": "PASS", "child_status": "PREFLIGHT_PASS", "teardown_proved": True, "hard_stop": False,
        "plan_sha256": sha, "source_git_sha": head, "execution_host_id": host, "segment": "preflight",
        "deleted_files": 0, "cleanup_eligible": False, "started_at_utc": now.isoformat(),
        "child_result_sha256": hashlib.sha256(result.read_bytes()).hexdigest()}))
    registration = night_root / "registration-preflight"
    registration.mkdir()
    (registration / "preflight-result.json").write_text(json.dumps({
        "status": "PASS", "plan_sha256": sha, "source_git_sha": head,
        "task_name": "WeatherStorageRecovery-" + plan["plan_id"] + "-preflight",
        "task_xml_sha256": hashlib.sha256(b"<Task>fixture export</Task>").hexdigest()}))
    calls = production / "calls.txt"
    script = SCHEDULER_MOCKS.replace(" -PreflightOnly\n", "\n")
    script = script.replace("$global:weatherNightStoredTask = $null", "$global:weatherNightStoredTasks = @{}")
    script = script.replace(
        "if ($global:weatherNightStoredTask) { return $global:weatherNightStoredTask }",
        """if ($TaskName.EndsWith('-preflight')) {
        return [PSCustomObject]@{State='Ready';Principal=[PSCustomObject]@{
            UserId=$env:USERNAME;LogonType='S4U';RunLevel='Limited'}}
    }
    if ($global:weatherNightStoredTasks.ContainsKey($TaskName)) { return $global:weatherNightStoredTasks[$TaskName] }""")
    script = script.replace("$global:weatherNightStoredTask = [PSCustomObject]",
                            "$global:weatherNightStoredTasks[$TaskName] = [PSCustomObject]")
    script = script.replace("ExecutionTimeLimit=('PT' + [int]$ExecutionTimeLimit.TotalMinutes + 'M')",
                            "ExecutionTimeLimit=[Xml.XmlConvert]::ToString($ExecutionTimeLimit)")
    if wrong_duration:
        script = script.replace("ExecutionTimeLimit=[Xml.XmlConvert]::ToString($ExecutionTimeLimit)",
                                "ExecutionTimeLimit=[Xml.XmlConvert]::ToString($ExecutionTimeLimit.Add([TimeSpan]::FromMinutes(1)))")
    script = script.replace("function Export-ScheduledTask",
        "function Get-ScheduledTaskInfo { [CmdletBinding()]param([Parameter(ValueFromPipeline=$true)]$InputObject)\n"
        " return [PSCustomObject]@{LastTaskResult=0;LastRunTime=[DateTimeOffset]::Parse('__NOW__').LocalDateTime}\n}\n"
        "function Export-ScheduledTask")
    replacements = {"__MODE__": "success", "__CALLS__": str(calls), "__NOW__": now.isoformat(),
        "__REGISTRAR__": str(source / "scripts/ops/register_storage_recovery_night.ps1"),
        "__PRODUCTION__": str(production), "__PLAN__": str(path), "__SHA__": sha, "__HEAD__": head}
    for key, value in replacements.items():
        script = script.replace(key, value.replace("'", "''"))
    harness = production / "harness.ps1"
    harness.write_text(script, encoding="utf-8")
    observed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-File", str(harness)], capture_output=True, text=True, timeout=40)
    assert (observed.returncode == 0) is passed, observed.stdout + observed.stderr
    assert len(calls.read_text().splitlines()) == expected_calls
    for segment in ("early", "late"):
        receipt = night_root / "registration-segments" / (segment + "-result.json")
        assert receipt.exists() is passed
