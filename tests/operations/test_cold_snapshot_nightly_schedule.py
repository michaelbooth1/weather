"""The 91a nightly cold-snapshot schedule: 06:50-09:00 America/Toronto (owner, 2026-10-05).

Guards: the move of WeatherColdSnapshotNightly out of the 01:00-04:00 quiet window. The scheduled
entrypoint must refuse outside 06:50-09:00 and any start with under 90 minutes left without creating
or consuming an attempt; one attempt per local date keeps working; a deadline must end in a
resolvable child receipt (soft stop before a new batch, child stop before the wrapper hard stop);
the registration must register and read back a 06:50 trigger. Real scripts run under Windows
PowerShell 5.1 against disposable fixtures; only the clock, the child and the Scheduler cmdlets are
stubbed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.operations import cold_snapshot_nightly as nightly
from weather.paths import repo_path

pytestmark = pytest.mark.spawns

TORONTO = ZoneInfo("America/Toronto")
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")
windows_only = pytest.mark.skipif(os.name != "nt", reason="real Windows PowerShell 5.1 orchestration")


# --------------------------------------------------------------------------- child window and soft stop


@pytest.mark.parametrize(("hhmm", "inside"), [
    ("00:30", False), ("04:44", False), ("06:49", False), ("06:50", True), ("07:30", True),
    ("08:59", True), ("09:00", False), ("12:00", False),
])
def test_child_window_is_0650_to_0900(hhmm, inside):
    hour, minute = map(int, hhmm.split(":"))
    assert nightly.in_window(datetime(2026, 10, 7, hour, minute, tzinfo=TORONTO)) is inside


def test_soft_stop_leaves_a_full_batch_of_time_before_the_child_deadline():
    deadline = datetime(2026, 10, 7, 12, 57, 45, tzinfo=timezone.utc)
    reserve = nightly.SOFT_STOP_RESERVE_SECONDS
    assert nightly.soft_stop_reached(deadline - timedelta(seconds=reserve - 1), deadline)
    assert not nightly.soft_stop_reached(deadline - timedelta(seconds=reserve), deadline)
    # One batch is at most MAX_BATCH_BYTES; at the 2026-10-02 rate (21.3 GB in 73 min) it needs
    # about 3.5 minutes, so the reserve covers it with margin.
    rate = 21.3e9 / (73 * 60)
    assert nightly.cold.MAX_BATCH_BYTES / rate * 2 < reserve


def test_the_run_loop_stops_at_the_soft_deadline_as_a_pass_not_a_failure():
    """The soft stop breaks before a new batch and still reaches status PASS (like the byte budget)."""
    import inspect
    source = inspect.getsource(nightly.run)
    assert source.count("soft_stop_reached(datetime.now(timezone.utc), deadline)") == 2
    assert 'receipt["stopped_at_soft_deadline"] = True' in source
    assert source.index("stopped_at_soft_deadline") < source.index('receipt["status"] = "PASS"')


# --------------------------------------------------------------------------- scheduled entrypoint (execution)


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60)


@pytest.fixture
def entry(tmp_path):
    root = tmp_path / "src"
    scripts = root / "scripts/ops"
    scripts.mkdir(parents=True)
    for name in ("windows_kill_on_close_job.ps1", "training_window_contract.ps1"):
        shutil.copy2(repo_path("scripts/ops", name), scripts / name)
    # The stub child records the arguments it was launched with and exits 0.
    (scripts / "cold_snapshot_compression_run.ps1").write_text(
        "param([Parameter(ValueFromRemainingArguments=$true)]$Rest)\n"
        "$out = $Rest[[Array]::IndexOf($Rest, '-OutputRoot') + 1]\n"
        "Set-Content -LiteralPath (Join-Path $env:NIGHTLY_FIXTURE_LOG 'child.json') "
        "-Value (@{ output = $out; args = @($Rest) } | ConvertTo-Json -Compress)\n"
        "exit 0\n", encoding="utf-8")
    production = tmp_path / "production"
    (production / "scratch/cold_snapshot_compression").mkdir(parents=True)
    log = tmp_path / "log"
    log.mkdir()
    return root, production, log


def run_entry(entry, local_clock: str):
    root, production, log = entry
    script = repo_path("scripts/ops/cold_snapshot_nightly_run.ps1").read_text(encoding="utf-8-sig")
    before = "$now = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)"
    assert script.count(before) == 1
    script = script.replace(before, f"$now = [DateTime]::SpecifyKind([DateTime]'{local_clock}', [DateTimeKind]::Unspecified)")
    path = root / "scripts/ops/cold_snapshot_nightly_run.ps1"
    path.write_text(script, encoding="utf-8")
    request = production / "request.json"
    request.write_text("{}", encoding="utf-8")
    env = {**os.environ, "NIGHTLY_FIXTURE_LOG": str(log)}
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path),
         "-ProductionRepoRoot", str(production), "-RequestPath", str(request),
         "-RequestSha256", hashlib.sha256(request.read_bytes()).hexdigest(), "-ExpectedSourceTip", "a" * 40],
        cwd=root, capture_output=True, text=True, timeout=120, env=env)
    child = log / "child.json"
    return result.returncode, result.stdout + result.stderr, (json.loads(child.read_text(encoding="utf-8-sig"))
                                                               if child.exists() else None)


@windows_only
@pytest.mark.parametrize("clock", ["2026-10-07T00:30:00", "2026-10-07T04:00:00", "2026-10-07T06:49:00",
                                   "2026-10-07T09:00:00", "2026-10-07T12:00:00"])
def test_entrypoint_refuses_outside_0650_0900_without_an_attempt(entry, clock):
    code, text, child = run_entry(entry, clock)
    assert code != 0 and "06:50-09:00" in text and child is None
    assert list((entry[1] / "scratch/cold_snapshot_compression").iterdir()) == []


@windows_only
@pytest.mark.parametrize("clock", ["2026-10-07T07:31:00", "2026-10-07T08:45:00"])
def test_entrypoint_refuses_a_start_with_under_90_minutes_left(entry, clock):
    code, text, child = run_entry(entry, clock)
    assert code != 0 and "after 07:30" in text and child is None
    assert list((entry[1] / "scratch/cold_snapshot_compression").iterdir()) == []


@windows_only
@pytest.mark.parametrize("clock", ["2026-10-07T06:50:00", "2026-10-07T07:30:00"])
def test_entrypoint_launches_a_dated_nightly_attempt_inside_the_window(entry, clock):
    code, text, child = run_entry(entry, clock)
    assert code == 0, text
    name = Path(child["output"]).name
    assert name.startswith("nightly-20261007-") and Path(child["output"]).parent.name == "cold_snapshot_compression"
    assert "-Nightly" in child["args"]


@windows_only
def test_one_attempt_per_local_date_survives_the_new_time(entry):
    parent = entry[1] / "scratch/cold_snapshot_compression"
    prior = parent / "nightly-20261007-043000000000Z"  # e.g. tonight's 00:30 run under the old schedule
    prior.mkdir()
    (prior / "wrapper-result.json").write_text(json.dumps(
        {"status": "PASS", "teardown_proved": True, "hard_stop": False}), encoding="utf-8")
    code, text, child = run_entry(entry, "2026-10-07T06:50:00")
    assert code != 0 and "already consumed this local date" in text and child is None
    code, text, child = run_entry(entry, "2026-10-08T06:50:00")
    assert code == 0, text
    assert Path(child["output"]).name.startswith("nightly-20261008-")


# --------------------------------------------------------------------------- registration (execution, stubbed Scheduler)


SCHEDULER_STUBS = r"""
$global:Registered = $null
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
function New-ScheduledTaskTrigger { param([switch]$Daily, $At)
    $at = if ($env:REG_FIXTURE_READBACK_AT) { $env:REG_FIXTURE_READBACK_AT } else { $At }
    [pscustomobject]@{ RequestedAt = $At; StartBoundary = ('2026-10-07T' + $at + ':00'); DaysInterval = 1 } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel)
    [pscustomobject]@{ LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskSettingsSet { param($ExecutionTimeLimit, $MultipleInstances)
    [pscustomobject]@{ StartWhenAvailable = $false; MultipleInstances = $MultipleInstances;
        ExecutionTimeLimit = [Xml.XmlConvert]::ToString([TimeSpan]$ExecutionTimeLimit) } }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, [switch]$Force)
    $global:Registered = [pscustomobject]@{ Actions = @($Action); Triggers = @($Trigger);
        Principal = $Principal; Settings = $Settings }
    Set-Content -LiteralPath $env:REG_FIXTURE_OUT -Value ([pscustomobject]@{ task = $TaskName;
        at = $Trigger.RequestedAt; limit = $Settings.ExecutionTimeLimit } | ConvertTo-Json -Compress) }
function Get-ScheduledTask { param($TaskName) $global:Registered }
"""


@pytest.fixture
def registration(tmp_path):
    root = tmp_path / "src"
    scripts = root / "scripts/ops"
    scripts.mkdir(parents=True)
    shutil.copy2(repo_path("scripts/ops/training_window_contract.ps1"), scripts / "training_window_contract.ps1")
    (scripts / "workload_admission.ps1").write_text(
        "function Get-WeatherExecutionHostAssignment { param($RepoRoot) "
        "[pscustomobject]@{ dedicated_capture_execution_host_id = 'fixture-host' } }\n"
        "function Get-WeatherExecutionHostId { 'fixture-host' }\n", encoding="utf-8")
    shutil.copy2(repo_path("scripts/ops/register_cold_snapshot_nightly.ps1"), scripts / "register_cold_snapshot_nightly.ps1")
    (root / ".gitignore").write_text("", encoding="utf-8")
    _git("init", "-q", cwd=root)
    _git("add", ".", cwd=root)
    _git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgSign=false",
         "commit", "-q", "-m", "fixture", cwd=root)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    (tmp_path / "stubs.ps1").write_text(SCHEDULER_STUBS, encoding="utf-8")
    return root, head, request, tmp_path


def run_registration(registration, readback_at=None):
    root, head, request, tmp = registration
    out = tmp / "registered.json"
    env = {**os.environ, "REG_FIXTURE_OUT": str(out)}
    env.pop("REG_FIXTURE_READBACK_AT", None)
    if readback_at:
        env["REG_FIXTURE_READBACK_AT"] = readback_at
    command = (f". '{tmp / 'stubs.ps1'}'; & '{root / 'scripts/ops/register_cold_snapshot_nightly.ps1'}' "
               f"-ProductionRepoRoot '{tmp / 'production'}' -RequestPath '{request}' "
               f"-RequestSha256 {hashlib.sha256(request.read_bytes()).hexdigest()} -ExpectedSourceTip {head}")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
                            cwd=root, capture_output=True, text=True, timeout=120, env=env)
    return result.returncode, result.stdout + result.stderr, (json.loads(out.read_text(encoding="utf-8-sig"))
                                                               if out.exists() else None)


@windows_only
def test_registration_registers_and_reads_back_a_0650_trigger(registration):
    code, text, registered = run_registration(registration)
    assert code == 0, text
    assert registered == {"task": "WeatherColdSnapshotNightly", "at": "06:50", "limit": "PT2H20M"}


@windows_only
def test_registration_readback_rejects_the_old_0030_trigger(registration):
    """Mutant: a Scheduler readback still at 00:30 must fail the registration check."""
    code, text, _registered = run_registration(registration, readback_at="00:30")
    assert code != 0 and "readback mismatch" in text
