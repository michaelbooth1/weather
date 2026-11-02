"""Execution twins for the memory commit guard's substring gates.

`test_memory_commit_guard_script.py` mostly asserts that `memory_commit_guard.ps1` *contains* text.
That pattern hid an inert kill path for 27 days (EF §10g, HWGTW Pattern 1). These tests run the
whole, unmodified script in a Windows PowerShell child against a synthetic process table: the
OS-facing cmdlets (`Get-CimInstance`, `Get-Process`, `Stop-Process`, `Get-ScheduledTask`,
`Get-Date`, `Get-ItemPropertyValue`) are shadowed by functions in the caller's scope, so nothing on
the host is inspected or terminated, and every file the guard writes lands under `tmp_path`.

Synthetic PIDs are odd numbers above 7,000,000; Windows PIDs are multiples of four, so a stub can
never name a real process.

Guards: EF §10g (inert kill path hidden by substring tests), EF §8d (orphaned refresh child), EF §8u (agent
  heavy trees) - executed against the unmodified memory_commit_guard.ps1.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "memory_commit_guard.ps1"
pytestmark = [pytest.mark.spawns, pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="runs the real memory guard under Windows PowerShell",
)]

GONE = 7_999_999  # a parent PID absent from every synthetic table
EVIDENCE_TASK = "WeatherEveningEvidenceRefresh"
GIB = 1024**3
MIB = 1024**2

# Runs every scenario in one PowerShell process. Each scenario sets the stub state, invokes the
# guard script with `&` (a child scope, so the caller's functions shadow the cmdlets), and
# reports what the stubs observed plus the files the guard wrote.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
$scenarios = Get-Content -LiteralPath $env:GUARD_SCENARIOS -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-Date {
    param([string]$Format)
    if ($Format) { return $global:FakeNow.ToString($Format) }
    return $global:FakeNow
}
function Get-ItemPropertyValue {
    param($LiteralPath, $Name, $ErrorAction)
    $global:Calls.Add('Get-ItemPropertyValue')
    return '00000000-1111-2222-3333-444444444444'
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $global:Calls.Add("Get-CimInstance:$ClassName")
    if ($ClassName -eq 'Win32_OperatingSystem') { return $global:FakeOs }
    $live = @($global:FakeRows | Where-Object { -not $global:Stopped.Contains([int]$_.ProcessId) })
    if (-not $Filter) { return $live }
    if ($Filter -match '^ProcessId = (\d+)$') {
        $wanted = [int]$Matches[1]
        return $live | Where-Object { [int]$_.ProcessId -eq $wanted } | Select-Object -First 1
    }
    if ($Filter -eq "Name like 'python%'") {
        return $live | Where-Object { ([string]$_.Name) -like 'python*' }
    }
    throw "unexpected Win32_Process filter: $Filter"
}
function Get-Process {
    param($Id, $ErrorAction)
    $live = @($global:FakeRuntime | Where-Object { -not $global:Stopped.Contains([int]$_.Id) })
    if ($null -eq $Id) { return $live }
    return $live | Where-Object { [int]$_.Id -eq [int]$Id } | Select-Object -First 1
}
function Stop-Process {
    param($Id, [switch]$Force, $Confirm, $ErrorAction)
    $global:Stopped.Add([int]$Id)
}
# A scenario with fail_state_write makes the guard-state rename fail, as a full disk
# or a denied ACL would; every other Move-Item is the real cmdlet.
function Move-Item {
    param($LiteralPath, $Destination, [switch]$Force, $ErrorAction)
    if ($global:FailStateWrite -and ([string]$Destination).EndsWith('memory_commit_guard_state.json')) {
        throw 'synthetic: the guard state cannot be written'
    }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force -ErrorAction Stop
}
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($global:FakeTaskState -and $TaskName -eq $global:FakeTaskName) {
        return [pscustomobject]@{ TaskName = $TaskName; State = $global:FakeTaskState }
    }
    return $null
}

$results = foreach ($scenario in $scenarios) {
    $n = @($scenario.now_parts | ForEach-Object { [int]$_ })
    $global:FakeNow = New-Object DateTime ($n[0], $n[1], $n[2], $n[3], $n[4], 0, [DateTimeKind]::Local)
    $global:FakeOs = [pscustomobject]@{
        TotalVirtualMemorySize = [uint64]$scenario.os.total_kb
        FreeVirtualMemory = [uint64]$scenario.os.free_kb
        FreePhysicalMemory = [uint64]$scenario.os.free_physical_kb
    }
    $global:FakeTaskName = $scenario.task_name
    $global:FakeTaskState = $scenario.task_state
    $global:Stopped = New-Object System.Collections.Generic.List[int]
    $global:Calls = New-Object System.Collections.Generic.List[string]
    $global:FakeRows = @(foreach ($p in $scenario.processes) {
        [pscustomobject]@{
            ProcessId = [uint32]$p.pid
            ParentProcessId = [uint32]$p.ppid
            Name = [string]$p.name
            CommandLine = [string]$p.cmd
            ExecutablePath = [string]$p.exe
            CreationDate = $global:FakeNow.AddMinutes(-[double]$p.age_minutes)
            ReadTransferCount = [uint64]0
        }
    })
    # Lease records exactly as workload_admission.ps1 writes them: the repo lock under
    # <repo>\data\logs and the host-global state file under the (synthetic) state root.
    $stateRoot = Join-Path $scenario.repo_root 'host_state'
    foreach ($lease in @($scenario.leases)) {
        if ($null -eq $lease) { continue }
        $born = $global:FakeNow.AddMinutes(-[double]$lease.age_minutes).ToUniversalTime()
        if ($lease.kind -eq 'integration_mutex') {
            # integration_attempt_contract.ps1 writes this into heavy_workload.lock and
            # only disposes the handle on exit; the record stays.
            $dir = Join-Path $scenario.repo_root 'data\logs'
            $record = [ordered]@{
                schema = 'weather_integration_control_mutex_v1'
                owner = 'close_integration_attempt'
                pid = [int]$lease.pid
                acquired_at = $born.ToString('o')
            }
        }
        elseif ($lease.kind -eq 'repo_lock') {
            $dir = Join-Path $scenario.repo_root 'data\logs'
            $record = [ordered]@{
                schema_version = 'weather_heavy_workload_lease_v3'
                workload = 'WorkstationOffline-pytest-1'
                pid = [int]$lease.pid
                owner_process_creation_time_token = 'win32-filetime:{0}' -f $born.ToFileTimeUtc()
            }
            if ($null -ne $lease.host_id) { $record['execution_host_id'] = [string]$lease.host_id }
            # policy_window as Get-WeatherHeavyWorkloadPolicyWindow or the profile sets it.
            if ($null -ne $lease.window) {
                $record['policy_window'] = [string]$lease.window
                $record['execution_host_profile'] = if ([string]$lease.window -eq 'workstation_offline') { 'workstation_offline_v1' } else { 'capture_colocated_v1' }
            }
        }
        else {
            $dir = $stateRoot
            $record = [ordered]@{
                schema_version = 'weather_heavy_workload_state_v1'
                state = [string]$lease.state
                workload = 'WorkstationOffline-pytest-1'
                execution_host_profile = 'workstation_offline_v1'
                pid = [int]$lease.pid
                owner_process_start_utc = $born.ToString('o')
                boot_session_id = 1
                state_changed_at_utc = $born.ToString('o')
            }
        }
        New-Item -ItemType Directory -Force $dir | Out-Null
        # A raw body stands for a record caught mid-write or damaged.
        $body = if ($null -ne $lease.raw) { [string]$lease.raw } else { $record | ConvertTo-Json -Compress }
        $leasePath = Join-Path $dir ([string]$lease.file)
        [IO.File]::WriteAllText($leasePath, $body)
        # Last write on the fake clock: at acquisition unless the scenario says otherwise.
        $writtenAgo = if ($null -ne $lease.mtime_age_seconds) { [double]$lease.mtime_age_seconds } else { 60.0 * [double]$lease.age_minutes }
        [IO.File]::SetLastWriteTimeUtc($leasePath, $global:FakeNow.AddSeconds(-$writtenAgo).ToUniversalTime())
    }
    # The guard's memory from an earlier run: owners named by synthetic pid get the
    # creation instant of that row on the fake clock.
    if ($null -ne $scenario.prior_state) {
        $prior = $scenario.prior_state
        $logsDir = Join-Path $scenario.repo_root 'data\logs'
        New-Item -ItemType Directory -Force $logsDir | Out-Null
        $trees = @(foreach ($ownerId in @($prior.owners)) {
            if ($null -eq $ownerId) { continue }
            $row = $global:FakeRows | Where-Object { [int]$_.ProcessId -eq [int]$ownerId } | Select-Object -First 1
            [ordered]@{ pid = [int]$ownerId; creation_utc_ticks = $row.CreationDate.ToUniversalTime().Ticks }
        })
        $stateRecord = [ordered]@{
            schema_version = 'memory_commit_guard_state_v1'
            updated_at_utc = $global:FakeNow.AddSeconds(-[double]$prior.age_seconds).ToUniversalTime().ToString('o')
            lease_records_unreadable_streak = [int]$prior.unreadable_streak
            lease_owner_trees = $trees
        }
        # A raw body stands for a damaged state file.
        $stateBody = if ($null -ne $prior.raw) { [string]$prior.raw } else { ConvertTo-Json -InputObject $stateRecord -Depth 4 }
        [IO.File]::WriteAllText((Join-Path $logsDir 'memory_commit_guard_state.json'), $stateBody)
    }
    $global:FailStateWrite = [bool]$scenario.fail_state_write
    # lock_state holds the state file open with no sharing for the whole run, so the
    # guard can neither read nor replace it.
    $stateLock = $null
    if ($scenario.lock_state) {
        $stateLock = [IO.File]::Open((Join-Path $scenario.repo_root 'data\logs\memory_commit_guard_state.json'), 'Open', 'Read', 'None')
    }
    $global:FakeRuntime = @(foreach ($p in $scenario.processes) {
        [pscustomobject]@{
            Id = [int]$p.pid
            Name = [string]$p.name
            PrivateMemorySize64 = [long]$p.private_bytes
            WorkingSet64 = [long]$p.private_bytes
        }
    })
    # Never let a scenario read the host's real %ProgramData% lease state.
    $arguments = @{ RepoRoot = $scenario.repo_root; HeavyWorkloadStateRoot = $stateRoot }
    if ($scenario.expected_host_id) { $arguments['ExpectedExecutionHostId'] = $scenario.expected_host_id }
    # Production runs the guard via -File under the default Continue preference, where a
    # statement-terminating error is swallowed (EF §10g). Mirror that, then surface every error.
    $ErrorActionPreference = 'Continue'
    $Error.Clear()
    $output = @(& $env:GUARD_SCRIPT @arguments | ForEach-Object { [string]$_ })
    $scriptErrors = @($Error | ForEach-Object { [string]$_ })
    if ($null -ne $stateLock) { $stateLock.Dispose() }
    $global:FailStateWrite = $false
    $ErrorActionPreference = 'Stop'
    $logs = Join-Path $scenario.repo_root 'data\logs'
    $statusPath = Join-Path $logs 'memory_commit_guard_status.json'
    $historyPath = Join-Path $logs 'memory_commit_guard_history.jsonl'
    $logPath = Join-Path $logs 'memory_commit_guard.log'
    [pscustomobject]@{
        name = $scenario.name
        stopped = @($global:Stopped)
        calls = @($global:Calls)
        output = $output
        errors = $scriptErrors
        logs_dir_exists = [bool](Test-Path -LiteralPath $logs)
        status = if (Test-Path -LiteralPath $statusPath) { Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json } else { $null }
        history = if (Test-Path -LiteralPath $historyPath) { [string](Get-Content -LiteralPath $historyPath -Raw) } else { '' }
        log = if (Test-Path -LiteralPath $logPath) { [string](Get-Content -LiteralPath $logPath -Raw) } else { '' }
        state = if (Test-Path -LiteralPath (Join-Path $logs 'memory_commit_guard_state.json')) { Get-Content -LiteralPath (Join-Path $logs 'memory_commit_guard_state.json') -Raw | ConvertFrom-Json } else { $null }
    }
}
ConvertTo-Json -InputObject @($results) -Depth 6 -Compress
"""


def _proc(pid, name, cmd, *, age, private=50 * MIB, ppid=GONE, exe=""):
    return {
        "pid": pid,
        "ppid": ppid,
        "name": name,
        "cmd": cmd,
        "exe": exe,
        "age_minutes": age,
        "private_bytes": private,
    }


def _os(commit_percent: float, *, free_physical_mib: int = 4096) -> dict:
    total_kb = 64_000_000
    return {
        "total_kb": total_kb,
        "free_kb": int(total_kb * (100.0 - commit_percent) / 100.0),
        "free_physical_kb": free_physical_mib * 1024,
    }


# The harness's stubbed MachineGuid, hashed exactly as Get-MemoryGuardExecutionHostId does.
STUB_MACHINE_GUID = "00000000-1111-2222-3333-444444444444"
GUARD_HOST_ID = hashlib.sha256(b"international_live_execution_host_v2\x00" + STUB_MACHINE_GUID.encode()).hexdigest()
OTHER_HOST_ID = "a" * 64


def _write_host_assignment(repo_root: Path, host: str) -> None:
    """config/international_live_execution_host.json naming the guard's host as `host`."""
    if host == "none":
        return
    if host == "workstation":
        active, dedicated = GUARD_HOST_ID, OTHER_HOST_ID
    elif host == "capture":
        active, dedicated = OTHER_HOST_ID, GUARD_HOST_ID
    elif host == "other":
        active, dedicated = "b" * 64, OTHER_HOST_ID
    else:
        raise ValueError(host)
    (repo_root / "config").mkdir()
    (repo_root / "config" / "international_live_execution_host.json").write_text(
        json.dumps(
            {
                "active_portable_execution_host_id": active,
                "active_portable_execution_principal_id": "c" * 64,
                "assignment_status": "ASSIGNED",
                "dedicated_capture_execution_host_id": dedicated,
                "reassignment_requires_new_production_tip": True,
                "schema_version": "international_live_execution_host_assignment_v0.1",
            }
        ),
        encoding="utf-8",
    )


def _scenario(tmp_path: Path, name: str, *, now: str, commit: float, processes, **extra) -> dict:
    repo_root = tmp_path / name
    repo_root.mkdir()
    # By default the guard runs on the assigned non-capture (workstation) host, where a
    # workstation_offline lease has no time window; "capture", "other" and "none" test the rest.
    _write_host_assignment(repo_root, extra.pop("host", "workstation"))
    return {
        "name": name,
        "repo_root": str(repo_root),
        "now_parts": [int(part) for part in now.replace("T", "-").replace(":", "-").split("-")[:5]],
        "os": extra.pop("os", None) or _os(commit),
        "processes": processes,
        "task_name": EVIDENCE_TASK,
        "task_state": extra.pop("task_state", None),
        "expected_host_id": extra.pop("expected_host_id", None),
        "prior_state": extra.pop("prior_state", None),
        "fail_state_write": extra.pop("fail_state_write", False),
        "lock_state": extra.pop("lock_state", False),
        # A repo lock defaults to the workstation_offline profile (no time window) taken on
        # this host, as workstation_heavy.ps1 writes it; scenarios name agent_heavy or
        # stage_a, or another execution_host_id, explicitly.
        "leases": [
            {"window": "workstation_offline", "host_id": GUARD_HOST_ID, **lease} if lease.get("kind") == "repo_lock" else lease
            for lease in extra.pop("leases", [])
        ],
    }


def _run(tmp_path: Path, scenarios: list[dict]) -> dict[str, dict]:
    spec = tmp_path / "scenarios.json"
    spec.write_text(json.dumps(scenarios), encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", HARNESS],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "GUARD_SCRIPT": str(SCRIPT), "GUARD_SCENARIOS": str(spec)},
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {s["name"] for s in scenarios}
    expects_error_log = {
        s["name"]
        for s in scenarios
        if s.get("fail_state_write") or s.get("lock_state") or (s.get("prior_state") or {}).get("raw")
    }
    for row in rows:
        # No swallowed PowerShell error and no internal failure logged by the guard itself
        # (a scenario that breaks the guard state on purpose expects its ERROR line).
        assert row["errors"] == [], (row["name"], row["errors"])
        if row["name"] not in expects_error_log:
            assert "[ERROR]" not in row["log"], (row["name"], row["log"])
    return by_name


def test_exec_critical_commit_kills_largest_ungoverned_python_even_while_warning(tmp_path: Path) -> None:
    """Twin of test_memory_guard_warning_cannot_disable_the_critical_action_path (EF §10g)."""
    adhoc_cmd = r'"C:\Python\python.exe" -c "import secret_analysis; secret_analysis.run()"'
    table = [
        _proc(7_000_101, "explorer.exe", "explorer.exe", age=600),
        _proc(7_000_001, "python.exe", adhoc_cmd, age=60, private=9 * GIB, ppid=7_000_101),
        _proc(7_000_003, "python.exe", r'"C:\Python\python.exe" -c "pass"', age=60, private=1 * GIB, ppid=7_000_101),
        _proc(
            7_000_002,
            "pythonw.exe",
            r"C:\repo\venv\Scripts\pythonw.exe -m weather.collection.snapshot_loop",
            age=60,
            private=20 * GIB,
            ppid=7_000_101,
        ),
    ]
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "critical", now="2026-09-19T14:00:00", commit=95.0, processes=table),
            _scenario(tmp_path, "warning_only", now="2026-09-19T14:00:00", commit=90.0, processes=table),
        ],
    )

    critical = outcome["critical"]
    assert critical["stopped"] == [7_000_001]
    assert critical["status"]["memory_warning"] is True
    assert critical["status"]["action"] == "killed_python_pid_7000001"
    # Event history is preserved but never carries a raw command line
    # (twin of test_memory_guard_preserves_event_history_without_raw_commands).
    history = [json.loads(line) for line in critical["history"].splitlines() if line.strip()]
    assert [h["actions"] for h in history] == [["killed_python_pid_7000001"]]
    assert "secret_analysis" not in critical["history"]

    warning_only = outcome["warning_only"]
    assert warning_only["stopped"] == []
    assert warning_only["status"]["memory_warning"] is True
    assert warning_only["status"]["action"] == "none"


def test_exec_orphaned_evidence_refresh_is_reaped_only_inside_protected_window(tmp_path: Path) -> None:
    """Twin of test_memory_guard_reaps_only_unowned_evidence_refresh_inside_protected_window."""
    evidence = (
        r"C:\repo\venv\Scripts\pythonw.exe -m weather.operations.daily_refresh run --stage evidence "
        f"--scheduler-task-name {EVIDENCE_TASK} --repo-root C:\\repo"
    )
    settlement = evidence.replace(EVIDENCE_TASK, "WeatherDailySettlementPromotionRefresh")
    table = [
        _proc(7_000_009, "powershell.exe", "powershell.exe -File daily_refresh.ps1", age=11),
        _proc(7_000_011, "pythonw.exe", evidence, age=10, private=6 * GIB, ppid=7_000_010),
        _proc(7_000_010, "pythonw.exe", evidence, age=10, private=40 * MIB, ppid=7_000_009),
        _proc(7_000_013, "pythonw.exe", evidence, age=1, private=3 * GIB, ppid=7_000_009),
        _proc(7_000_015, "pythonw.exe", settlement, age=10, private=5 * GIB, ppid=7_000_009),
    ]
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "unowned", now="2026-09-19T13:00:00", commit=50.0, processes=table, task_state="Ready"),
            _scenario(tmp_path, "owned", now="2026-09-19T13:00:00", commit=50.0, processes=table, task_state="Running"),
            _scenario(tmp_path, "after_window", now="2026-09-19T18:00:00", commit=50.0, processes=table, task_state="Ready"),
            _scenario(tmp_path, "before_window", now="2026-09-19T11:59:00", commit=50.0, processes=table, task_state="Ready"),
        ],
    )

    # Largest private bytes first (child before its launcher shim); the young and
    # differently-owned refreshes survive.
    assert outcome["unowned"]["stopped"] == [7_000_011, 7_000_010]
    assert outcome["unowned"]["status"]["action"] == (
        "killed_orphaned_evidence_pid_7000011,killed_orphaned_evidence_pid_7000010"
    )
    for name in ("owned", "after_window", "before_window"):
        assert outcome[name]["stopped"] == [], name
        assert outcome[name]["status"]["action"] == "none", name


def test_exec_agent_heavy_tree_is_killed_children_first_outside_host_window(tmp_path: Path) -> None:
    """Twin of test_memory_guard_attributes_and_reaps_codex_heavy_tool_trees."""
    first_tree = [
        _proc(7_000_201, "claude.exe", "claude.exe", age=120),
        _proc(7_000_203, "powershell.exe", "powershell.exe -Command python -m pytest -q", age=50, ppid=7_000_201),
        _proc(7_000_205, "python.exe", r"C:\venv\python.exe -m pytest -q", age=50, private=500 * MIB, ppid=7_000_203),
        _proc(7_000_207, "python.exe", r'C:\venv\python.exe -c "pass"', age=49, ppid=7_000_205),
    ]
    second_tree = [
        _proc(7_000_301, "codex.exe", "codex.exe", age=120),
        _proc(7_000_303, "powershell.exe", "powershell.exe -Command python -m compileall src", age=40, ppid=7_000_301),
        _proc(7_000_305, "python.exe", r"C:\venv\python.exe -m compileall src", age=40, ppid=7_000_303),
    ]
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "daytime", now="2026-09-19T14:00:00", commit=50.0, processes=first_tree),
            _scenario(tmp_path, "night_one", now="2026-09-19T02:00:00", commit=50.0, processes=first_tree),
            _scenario(
                tmp_path, "night_two", now="2026-09-19T02:00:00", commit=50.0, processes=first_tree + second_tree
            ),
        ],
    )

    daytime = outcome["daytime"]
    assert daytime["stopped"] == [7_000_207, 7_000_205, 7_000_203]
    assert 7_000_201 not in daytime["stopped"]
    assert daytime["status"]["agent_heavy_window_allowed"] is False
    assert daytime["status"]["action"] == "killed_agent_tree_pid_7000203"
    assert "outside the 00:30-09:00 host window" in daytime["log"]

    night_one = outcome["night_one"]
    assert night_one["stopped"] == []
    assert night_one["status"]["agent_heavy_window_allowed"] is True
    assert night_one["status"]["agent_heavy_workload_count"] == 1

    # Inside the window only one tool tree is retained: the older one.
    night_two = outcome["night_two"]
    assert night_two["stopped"] == [7_000_305, 7_000_303]
    assert night_two["status"]["agent_heavy_workload_count"] == 2
    assert "concurrency exceeds 1" in night_two["log"]


def test_exec_low_physical_ram_only_warns_with_top_working_sets(tmp_path: Path) -> None:
    """Twin of test_memory_guard_warns_below_1_5_gib_with_top_working_sets."""
    table = [
        _proc(7_000_401, "explorer.exe", "explorer.exe", age=600),
        _proc(7_000_403, "python.exe", r'C:\Python\python.exe -c "pass"', age=5, private=9 * GIB, ppid=7_000_401),
    ]
    outcome = _run(
        tmp_path,
        [
            _scenario(
                tmp_path,
                "low_ram",
                now="2026-09-19T14:00:00",
                commit=50.0,
                processes=table,
                os=_os(50.0, free_physical_mib=1000),
            ),
            _scenario(
                tmp_path,
                "enough_ram",
                now="2026-09-19T14:00:00",
                commit=50.0,
                processes=table,
                os=_os(50.0, free_physical_mib=1600),
            ),
        ],
    )

    low = outcome["low_ram"]
    assert low["stopped"] == []
    assert low["status"]["physical_warning"] is True
    assert low["status"]["physical_warn_below_mb"] == 1536
    assert "top working set: python.exe(pid 7000403)=9216MB" in low["log"]
    assert outcome["enough_ram"]["status"]["physical_warning"] is False


def test_exec_guard_skips_before_any_side_effect_on_a_foreign_host(tmp_path: Path) -> None:
    """Twin of test_memory_guard_and_registrar_are_exact_capture_host_bound_before_side_effects."""
    table = [_proc(7_000_501, "python.exe", r'C:\Python\python.exe -c "x"', age=60, private=9 * GIB)]
    outcome = _run(
        tmp_path,
        [
            _scenario(
                tmp_path,
                "foreign",
                now="2026-09-19T14:00:00",
                commit=99.0,
                processes=table,
                expected_host_id="f" * 64,
            ),
        ],
    )

    foreign = outcome["foreign"]
    assert foreign["output"] == ["SKIPPED: memory commit guard is restricted to its registered dedicated capture host"]
    assert foreign["calls"] == ["Get-ItemPropertyValue"]
    assert foreign["stopped"] == []
    assert foreign["logs_dir_exists"] is False


# ---- Claude Code process shapes and lease admission (state review 2026-11-01 item 17) ----
#
# Real Claude Code shapes on Windows, observed 2026-11-01:
#   Bash tool:       claude.exe -> bash.exe -c "source <snapshot> ... eval '<command>'" -> bash.exe -> child
#   PowerShell tool: claude.exe -> cmd.exe /d /s /c "chcp 65001 & powershell.exe ... -Command
#                    $__claudeCodeScript = $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT ..." -> powershell.exe -> child
# The PowerShell tool's script text never reaches a command line, so every child must be
# classified by its own command line.

ADMISSION = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
CLAUDE = r"C:\Users\u\AppData\Local\Claude-Data\claude-code\claude.exe --output-format stream-json"
GIT_BASH = (
    r'"C:\Program Files\Git\bin\bash.exe" -c "source /c/Users/u/.claude/shell-snapshots/snapshot-bash-1.sh '
    r"2>/dev/null || true && export TEMP='C:\Users\u\AppData\Local\Temp' && eval '{command}'" + '"'
)
INNER_BASH = r'"C:\Program Files\Git\usr\bin\bash.exe" -c "{command}"'
CMD_LAUNCHER = (
    r'C:\WINDOWS\System32\cmd.exe /d /s /c ""C:\WINDOWS\System32\chcp.com" 65001 >nul & '
    r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive '
    r'-ExecutionPolicy Bypass -Command "$__claudeCodeScript = $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT""'
)
HIDDEN_PS = (
    r'"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive '
    r'-ExecutionPolicy Bypass -Command "$__claudeCodeScript = $env:CLAUDE_CODE_SHELL_LAUNCHER_SCRIPT"'
)
VENV_PY = r"C:\repo\venv\Scripts\python.exe"
WRAPPER = (
    r"powershell -NoProfile -File C:\wt\x\scripts\ops\workstation_heavy.ps1 -Kind pytest "
    r"-PythonPath C:\repo\venv\Scripts\python.exe -ArgumentsBase64 LW0gcHl0ZXN0 -RepoRoot C:\wt\x -Queue"
)


def _claude_bash(base: int, command: str, child_name: str, child_cmd: str, *, age: float = 30) -> list[dict]:
    """claude.exe -> bash.exe -> bash.exe -> child, with pids base+1, +3, +5, +7."""
    return [
        _proc(base + 1, "claude.exe", CLAUDE, age=age + 60),
        _proc(base + 3, "bash.exe", GIT_BASH.format(command=command), age=age + 1, ppid=base + 1),
        _proc(base + 5, "bash.exe", INNER_BASH.format(command=command), age=age + 1, ppid=base + 3),
        _proc(base + 7, child_name, child_cmd, age=age, ppid=base + 5),
    ]


def _claude_powershell(base: int, child_name: str, child_cmd: str, *, shell_cmd: str = HIDDEN_PS) -> list[dict]:
    """claude.exe -> cmd.exe -> powershell.exe (script text hidden) -> child."""
    return [
        _proc(base + 1, "claude.exe", CLAUDE, age=120),
        _proc(base + 3, "cmd.exe", CMD_LAUNCHER, age=31, ppid=base + 1),
        _proc(base + 5, "powershell.exe", shell_cmd, age=31, ppid=base + 3),
        _proc(base + 7, child_name, child_cmd, age=30, ppid=base + 5),
    ]


def test_exec_claude_bash_shape_heavy_children_are_reaped_outside_window(tmp_path: Path) -> None:
    replay = f"{VENV_PY} -m weather.backtesting.replay run --market all"
    isolated_script = f"{VENV_PY} -I C:\\scratch\\probe.py"
    table = (
        _claude_bash(7_100_000, "python -m weather.backtesting.replay run", "python.exe", replay)
        + _claude_bash(7_100_100, "python -I C:/scratch/probe.py", "python.exe", isolated_script)
        + _claude_bash(7_100_200, "find data -name x", "find.exe", r"C:\Program Files\Git\usr\bin\find.exe data -name x")
        + _claude_bash(7_100_300, "rg -n foo data/logs", "rg.exe", "rg -n foo data/logs")
        # Light work in the same shape is left alone.
        + _claude_bash(
            7_100_400,
            "python -m weather.operations.agent_docs_audit",
            "python.exe",
            f"{VENV_PY} -m weather.operations.agent_docs_audit",
        )
        + _claude_bash(7_100_500, "rg -n foo src", "rg.exe", r"rg -n foo C:\repo\src")
    )
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "daytime", now="2026-11-01T14:00:00", commit=50.0, processes=table),
            _scenario(tmp_path, "night", now="2026-11-01T02:00:00", commit=50.0, processes=table[:4]),
        ],
    )

    daytime = outcome["daytime"]
    for base in (7_100_000, 7_100_100, 7_100_200, 7_100_300):
        # The outer bash.exe is the tool root; the whole tree goes, children first.
        assert {base + 3, base + 5, base + 7} <= set(daytime["stopped"]), base
        assert daytime["stopped"].index(base + 7) < daytime["stopped"].index(base + 3), base
        assert base + 1 not in daytime["stopped"], base
    for base in (7_100_400, 7_100_500):
        assert not {base + 3, base + 5, base + 7} & set(daytime["stopped"]), base
    assert daytime["status"]["agent_heavy_workload_count"] == 4
    assert daytime["status"]["agent_heavy_admitted_workload_count"] == 0

    night = outcome["night"]
    assert night["stopped"] == []
    assert night["status"]["agent_heavy_workload_count"] == 1


def test_exec_claude_powershell_shape_children_are_judged_by_their_own_command_lines(tmp_path: Path) -> None:
    encoded_shell = r"powershell.exe -NoProfile -EncodedCommand SQBuAHYAbwBrAGUALQBTAG8AbQBlAHQAaABpAG4AZwA="
    file_shell = r"powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\u\AppData\Local\Temp\job.ps1"
    table = (
        _claude_powershell(7_200_000, "python.exe", f"{VENV_PY} -X utf8 C:\\scratch\\scan.py --all")
        + _claude_powershell(
            7_200_100,
            "python.exe",
            f'"{VENV_PY}" -B -m weather.calibration.mg2_composite build',
            shell_cmd=encoded_shell,
        )
        + _claude_powershell(7_200_200, "robocopy.exe", r"robocopy C:\repo\data D:\copy /E", shell_cmd=file_shell)
        + _claude_powershell(7_200_300, "python.exe", f"{VENV_PY} -m pytest -q tests/x.py", shell_cmd=encoded_shell)
        # A status-style weather CLI and a single-file copy are not heavy.
        + _claude_powershell(7_200_400, "python.exe", f"{VENV_PY} -m weather.operations.capture_recovery_check")
        + _claude_powershell(7_200_500, "robocopy.exe", r"robocopy C:\a C:\b one.txt")
    )
    outcome = _run(
        tmp_path,
        [_scenario(tmp_path, "daytime", now="2026-11-01T14:00:00", commit=50.0, processes=table)],
    )

    daytime = outcome["daytime"]
    for base in (7_200_000, 7_200_100, 7_200_200, 7_200_300):
        # cmd.exe (the direct child of claude.exe) is the tool root.
        assert {base + 3, base + 5, base + 7} <= set(daytime["stopped"]), base
        assert f"killed_agent_tree_pid_{base + 3}" in daytime["status"]["actions"], base
    for base in (7_200_400, 7_200_500):
        assert not {base + 3, base + 5, base + 7} & set(daytime["stopped"]), base
    assert daytime["status"]["agent_heavy_workload_count"] == 4


def test_exec_leased_work_stays_admitted_and_unleased_work_does_not(tmp_path: Path) -> None:
    pytest_child = f"{VENV_PY} -m pytest -q tests/operations/test_x.py --basetemp C:\\t\\bt"

    def leased_tree(base: int) -> list[dict]:
        # claude.exe -> bash.exe -> powershell workstation_heavy.ps1 (lease owner) -> python -m pytest
        return [
            _proc(base + 1, "claude.exe", CLAUDE, age=200),
            _proc(base + 3, "bash.exe", GIT_BASH.format(command="powershell -File x"), age=41, ppid=base + 1),
            _proc(base + 5, "powershell.exe", WRAPPER, age=40, ppid=base + 3),
            _proc(base + 7, "python.exe", pytest_child, age=39, ppid=base + 5),
        ]

    leased = leased_tree(7_300_000)
    repo_lock = [{"kind": "repo_lock", "file": "heavy_workload.slot2.lock", "pid": 7_300_005, "age_minutes": 40}]
    host_state = [
        {
            "kind": "host_state",
            "file": "heavy_workload_v1.slot3.poison",
            "pid": 7_300_005,
            "age_minutes": 40,
            "state": "ACTIVE",
        }
    ]
    # Same PID, different creation instant: the owner exited and the PID was reused.
    stale = [{"kind": "repo_lock", "file": "heavy_workload.lock", "pid": 7_300_005, "age_minutes": 90}]
    teardown = [dict(host_state[0], state="TEARDOWN_PENDING")]
    # An unleased inline job started from the same tool shell.
    sibling = [_proc(7_300_009, "python.exe", f'{VENV_PY} -c "import big; big.run()"', age=20, ppid=7_300_003)]
    other_tree = _claude_bash(7_300_100, "python -m pytest", "python.exe", f"{VENV_PY} -m pytest -q", age=60)

    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "repo_lock", now=day, commit=50.0, processes=leased, leases=repo_lock),
            _scenario(tmp_path, "host_state", now=day, commit=50.0, processes=leased, leases=host_state),
            _scenario(tmp_path, "stale", now=day, commit=50.0, processes=leased, leases=stale),
            _scenario(tmp_path, "teardown", now=day, commit=50.0, processes=leased, leases=teardown),
            _scenario(tmp_path, "unleased", now=day, commit=50.0, processes=leased),
            _scenario(tmp_path, "mixed", now=day, commit=50.0, processes=leased + sibling, leases=repo_lock),
            _scenario(
                tmp_path,
                "night_mixed",
                now="2026-11-01T02:00:00",
                commit=50.0,
                processes=leased + sibling + other_tree,
                leases=repo_lock,
            ),
            _scenario(
                tmp_path,
                "night_pair",
                now="2026-11-01T02:00:00",
                commit=50.0,
                processes=leased + other_tree,
                leases=repo_lock,
            ),
        ],
    )

    # A live owner in TEARDOWN_PENDING is still tearing its job down: admitted.
    for name in ("repo_lock", "host_state", "teardown"):
        admitted = outcome[name]
        assert admitted["stopped"] == [], name
        assert admitted["status"]["agent_heavy_workload_count"] == 1, name
        assert admitted["status"]["agent_heavy_admitted_workload_count"] == 1, name
        assert admitted["status"]["action"] == "none", name

    for name in ("stale", "unleased"):
        reaped = outcome[name]
        assert set(reaped["stopped"]) == {7_300_003, 7_300_005, 7_300_007}, name
        assert reaped["status"]["agent_heavy_admitted_workload_count"] == 0, name

    # Only the unleased sibling dies; the admitted wrapper and its pytest child survive.
    mixed = outcome["mixed"]
    assert mixed["stopped"] == [7_300_009]
    assert mixed["status"]["action"] == "killed_agent_member_pid_7300009"
    assert "unadmitted member of a leased tool tree" in mixed["log"]

    # A partly admitted leased tree holds one slot for its admitted work; its unadmitted
    # sibling competes for the rest and loses (no slot left), and so does the other tree.
    # The leased wrapper and its pytest child survive.
    night_mixed = outcome["night_mixed"]
    assert set(night_mixed["stopped"]) == {7_300_009, 7_300_103, 7_300_105, 7_300_107}
    assert "killed_agent_member_pid_7300009" in night_mixed["status"]["actions"]

    # Inside the window the admitted tree holds the single slot, so the unleased tree is
    # reaped although it is OLDER (the age-only rule would have kept it).
    night_pair = outcome["night_pair"]
    assert set(night_pair["stopped"]) == {7_300_103, 7_300_105, 7_300_107}
    assert night_pair["status"]["agent_heavy_workload_count"] == 2
    assert night_pair["status"]["agent_heavy_admitted_workload_count"] == 1


def _offline_modules() -> list[str]:
    text = ADMISSION.read_text(encoding="utf-8-sig")
    start = text.index("function Get-WeatherWorkstationOfflineModule")
    body = text[start : text.index("\n}\n", start)]
    modules = re.findall(r'"([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)"', body)
    assert len(modules) > 20
    return modules


def test_exec_every_workstation_offline_module_is_heavy_when_agent_rooted(tmp_path: Path) -> None:
    """The guard parses Get-WeatherWorkstationOfflineModule, so a module added there is covered."""
    modules = _offline_modules()
    table: list[dict] = []
    for index, module in enumerate(modules):
        base = 7_400_000 + 100 * index
        table += _claude_bash(base, f"python -m {module}", "python.exe", f"{VENV_PY} -m {module} run")
    outcome = _run(
        tmp_path,
        [_scenario(tmp_path, "daytime", now="2026-11-01T14:00:00", commit=50.0, processes=table)],
    )

    daytime = outcome["daytime"]
    assert daytime["status"]["agent_heavy_workload_count"] == len(modules)
    missed = [m for i, m in enumerate(modules) if 7_400_000 + 100 * i + 7 not in daytime["stopped"]]
    assert missed == []


# ---- L28 review fixes: a live lease owner is never killed with its tree ----

TRAINING_WINDOW = r"powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\weather\scripts\ops\training_window.ps1"
BOUNDED_SUITE = (
    r"powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
    r"C:\weather\scripts\ops\bounded_worktree_test_suite.ps1 -WorktreePath C:\wt\x"
)


CONHOST = r"\??\C:\WINDOWS\system32\conhost.exe 0xffffffff -ForceV1"


def _lock(pid: int, *, age: float, file: str = "heavy_workload.lock") -> dict:
    return {"kind": "repo_lock", "file": file, "pid": pid, "age_minutes": age}


def test_exec_budget_kill_on_a_leased_tree_spares_the_lease_owner(tmp_path: Path) -> None:
    """MAJOR 1: training_window re-enables capture in a finally; only the job below it may die."""
    base = 7_500_000
    training = [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "bash.exe", GIT_BASH.format(command="powershell -File training_window.ps1"), age=61, ppid=base + 1),
        _proc(base + 5, "powershell.exe", TRAINING_WINDOW, age=60, ppid=base + 3),
        _proc(
            base + 7,
            "python.exe",
            f"{VENV_PY} -m weather.operations.nightly_retrain --all",
            age=59,
            private=9 * GIB,
            ppid=base + 5,
        ),
    ]
    leases = [_lock(base + 5, age=60)]
    night = "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "leased", now=night, commit=50.0, processes=training, leases=leases),
            # Without the lease the old whole-tree budget kill still applies.
            _scenario(tmp_path, "unleased", now=night, commit=50.0, processes=training),
        ],
    )

    leased = outcome["leased"]
    assert leased["stopped"] == [base + 7]
    assert leased["status"]["actions"] == [f"killed_agent_member_pid_{base + 7}"]
    assert leased["status"]["agent_heavy_lease_owner_workload_count"] == 1
    assert "the owner is spared" in leased["log"]

    unleased = outcome["unleased"]
    assert set(unleased["stopped"]) == {base + 3, base + 5, base + 7}
    assert unleased["status"]["action"] == f"killed_agent_tree_pid_{base + 3}"


def test_exec_non_shell_parent_of_a_lease_owner_is_admitted_between_children(tmp_path: Path) -> None:
    """MAJOR 2: python tools\\x.py or a git hook launching the leased wrapper is not unleased work."""
    tool = 7_600_000
    # claude.exe -> python tools\run_suite.py -> bounded suite (owner) with no chunk running yet.
    python_parent = [
        _proc(tool + 1, "claude.exe", CLAUDE, age=300),
        _proc(tool + 3, "python.exe", f"{VENV_PY} tools\\run_suite.py --all", age=30, ppid=tool + 1),
        _proc(tool + 5, "powershell.exe", BOUNDED_SUITE, age=29, ppid=tool + 3),
    ]
    hook = 7_600_100
    # claude.exe -> bash -> git.exe -> sh.exe hook -> python hook script -> leased wrapper.
    git_hook = [
        _proc(hook + 1, "claude.exe", CLAUDE, age=300),
        _proc(hook + 3, "bash.exe", GIT_BASH.format(command="git commit -m x"), age=12, ppid=hook + 1),
        _proc(hook + 5, "git.exe", "git commit -m x", age=12, ppid=hook + 3),
        _proc(hook + 7, "sh.exe", "/usr/bin/sh .git/hooks/pre-commit", age=12, ppid=hook + 5),
        _proc(hook + 9, "python.exe", f"{VENV_PY} scripts\\hooks\\pre_commit.py", age=11, ppid=hook + 7),
        _proc(hook + 11, "powershell.exe", WRAPPER, age=10, ppid=hook + 9),
    ]
    leases = [_lock(tool + 5, age=29), _lock(hook + 11, age=10, file="heavy_workload.slot2.lock")]
    # Over budget, the job below the owner dies and the parent and owner live.
    chunk = [
        _proc(tool + 7, "python.exe", f"{VENV_PY} -m pytest -q tests/a.py", age=5, private=9 * GIB, ppid=tool + 5)
    ]
    other = _claude_bash(7_600_200, "python -c x", "python.exe", f'{VENV_PY} -c "run()"', age=60)
    day, night = "2026-11-01T14:00:00", "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "day", now=day, commit=50.0, processes=python_parent + git_hook, leases=leases),
            _scenario(tmp_path, "night_pair", now=night, commit=50.0, processes=python_parent + other, leases=leases),
            _scenario(tmp_path, "budget", now=night, commit=50.0, processes=python_parent + chunk, leases=leases),
        ],
    )

    day_row = outcome["day"]
    assert day_row["stopped"] == []
    assert day_row["status"]["agent_heavy_workload_count"] == 2
    assert day_row["status"]["agent_heavy_admitted_workload_count"] == 2

    # The leased tree holds the slot; the older unleased tree is the one reaped.
    night_pair = outcome["night_pair"]
    assert set(night_pair["stopped"]) == {7_600_203, 7_600_205, 7_600_207}

    budget = outcome["budget"]
    assert budget["stopped"] == [tool + 7]
    assert budget["status"]["actions"] == [f"killed_agent_member_pid_{tool + 7}"]


def test_exec_capture_host_profiles_survive_the_guard(tmp_path: Path) -> None:
    """The bounded suite, the daily_refresh.ps1 settlement stage and training_window, as run on the host."""
    suite = 7_700_000
    bounded = [
        _proc(suite + 1, "claude.exe", CLAUDE, age=300),
        _proc(suite + 3, "cmd.exe", CMD_LAUNCHER, age=91, ppid=suite + 1),
        _proc(suite + 5, "powershell.exe", HIDDEN_PS, age=91, ppid=suite + 3),
        _proc(suite + 7, "powershell.exe", BOUNDED_SUITE, age=90, ppid=suite + 5),
        _proc(suite + 9, "python.exe", f"{VENV_PY} -m pytest -q -p no:cacheprovider tests/a.py", age=2, ppid=suite + 7),
    ]
    refresh = 7_700_100
    settlement = [
        _proc(refresh + 1, "claude.exe", CLAUDE, age=300),
        _proc(
            refresh + 3,
            "bash.exe",
            GIT_BASH.format(command="powershell -File scripts/ops/daily_refresh.ps1 -Stage settlement"),
            age=20,
            ppid=refresh + 1,
        ),
        _proc(
            refresh + 5,
            "powershell.exe",
            r"powershell.exe -NoProfile -File C:\weather\scripts\ops\daily_refresh.ps1 -Stage settlement",
            age=20,
            ppid=refresh + 3,
        ),
        _proc(
            refresh + 7,
            "python.exe",
            f"{VENV_PY} -m weather.operations.daily_refresh --stage settlement",
            age=19,
            ppid=refresh + 5,
        ),
        _proc(refresh + 9, "python.exe", f"{VENV_PY} -m weather.operations.daily_refresh status", age=1, ppid=refresh + 3),
    ]
    train = 7_700_200
    training = [
        _proc(train + 1, "claude.exe", CLAUDE, age=300),
        _proc(train + 3, "powershell.exe", TRAINING_WINDOW, age=60, ppid=train + 1),
        _proc(train + 5, "python.exe", f"{VENV_PY} -m weather.operations.nightly_retrain", age=59, ppid=train + 3),
    ]
    leases = [
        dict(_lock(suite + 7, age=90), window="agent_heavy"),
        dict(_lock(train + 3, age=60, file="heavy_workload.slot2.lock"), window="agent_heavy"),
    ]
    # daily_refresh.ps1 takes its own lease; the settlement stage may run in Stage-A.
    stage_a = [dict(_lock(refresh + 5, age=20), window="stage_a")]
    status_only = settlement[:2] + [settlement[4]]
    outcome = _run(
        tmp_path,
        [
            _scenario(
                tmp_path, "night", now="2026-11-01T02:00:00", commit=50.0, processes=bounded + training, leases=leases
            ),
            _scenario(tmp_path, "settlement", now="2026-11-01T14:00:00", commit=50.0, processes=settlement),
            _scenario(tmp_path, "status_only", now="2026-11-01T14:00:00", commit=50.0, processes=status_only),
            _scenario(
                tmp_path, "stage_a", now="2026-11-01T10:00:00", commit=50.0, processes=settlement, leases=stage_a
            ),
            _scenario(
                tmp_path, "stage_a_late", now="2026-11-01T12:30:00", commit=50.0, processes=settlement, leases=stage_a
            ),
        ],
    )

    night = outcome["night"]
    assert night["stopped"] == []
    assert night["status"]["agent_heavy_workload_count"] == 2
    assert night["status"]["agent_heavy_admitted_workload_count"] == 2
    # Review M3: python -m weather.operations.daily_refresh is heavy (master's shell rule
    # named it); an unleased agent run in the graded window is reaped, children first.
    settlement_row = outcome["settlement"]
    assert set(settlement_row["stopped"]) == {refresh + 3, refresh + 5, refresh + 7, refresh + 9}
    assert settlement_row["status"]["action"] == f"killed_agent_tree_pid_{refresh + 3}"
    # Its status reader alone is not heavy.
    assert outcome["status_only"]["stopped"] == []
    assert outcome["status_only"]["status"]["agent_heavy_workload_count"] == 0
    # Review M2: inside Stage-A the stage_a lease admits the run...
    stage_a_row = outcome["stage_a"]
    assert stage_a_row["stopped"] == []
    assert stage_a_row["status"]["agent_heavy_admitted_workload_count"] == 1
    # ...and past its 11:55 teardown deadline the python child dies; the owner is spared.
    late = outcome["stage_a_late"]
    assert late["stopped"] == [refresh + 7]
    assert late["status"]["actions"] == [f"killed_agent_member_pid_{refresh + 7}"]
    assert f"lease owner pid {refresh + 5} is past its policy window" in late["log"]
    assert "[CRITICAL]" in late["log"]


def test_exec_readers_repls_and_quoted_scanners_are_not_heavy(tmp_path: Path) -> None:
    """MINOR 3-5 false positives, all daytime and unleased: none may be killed."""
    absolute_repo = tmp_path / "absrepo"
    (absolute_repo / ".git").mkdir(parents=True)
    (absolute_repo / "data").mkdir()
    cases = [
        ("python.exe", f"{VENV_PY} -m weather.operations.daily_refresh status"),
        ("python.exe", f"{VENV_PY} -m weather.operations.replay_cache_retention --apply"),
        ("python.exe", f"{VENV_PY} -m weather.operations.nightly_retrain status"),
        ("python.exe", f"{VENV_PY} -m weather.reporting.capture_status"),
        ("python.exe", VENV_PY),  # interactive REPL / stdin server
        ("rg.exe", "rg -n data src"),
        ("rg.exe", 'rg "data quality" docs'),
        ("rg.exe", r"rg -n foo tests\fixtures\data"),
        ("rg.exe", r"rg foo data\logs\x.jsonl"),
        ("grep.exe", "grep -rn --exclude-dir=data foo src"),
        ("grep.exe", "grep -n foo data/a"),
        ("find.exe", r'C:\WINDOWS\system32\find.exe /c /v "" data\logs\x.jsonl'),
        ("find.exe", r"C:\Program Files\Git\usr\bin\find.exe data -maxdepth 1 -name x"),
        ("robocopy.exe", r"robocopy C:\weather\data D:\copy one.jsonl"),
        ("git.exe", "git commit -m 'find the data bug'"),
    ]
    table: list[dict] = []
    for index, (name, cmd) in enumerate(cases):
        table += _claude_bash(7_800_000 + 100 * index, cmd, name, cmd)
    # A long-lived Python MCP server started directly by claude.exe.
    table += [
        _proc(7_809_001, "claude.exe", CLAUDE, age=300),
        _proc(7_809_003, "python.exe", f'"{VENV_PY}"', age=200, ppid=7_809_001),
    ]
    heavy = [
        ("rg.exe", r"rg -e foo data"),
        ("rg.exe", f"rg -n foo {absolute_repo / 'data'}"),
        ("grep.exe", "grep -rn foo data/logs"),
    ]
    heavy_table: list[dict] = []
    for index, (name, cmd) in enumerate(heavy):
        heavy_table += _claude_bash(7_810_000 + 100 * index, cmd, name, cmd)
    outcome = _run(
        tmp_path,
        [_scenario(tmp_path, "daytime", now="2026-11-01T14:00:00", commit=50.0, processes=table + heavy_table)],
    )

    daytime = outcome["daytime"]
    light_pids = {row["pid"] for row in table}
    assert not light_pids & set(daytime["stopped"])
    for index in range(len(heavy)):
        assert 7_810_000 + 100 * index + 7 in daytime["stopped"], heavy[index]
    assert daytime["status"]["agent_heavy_workload_count"] == len(heavy)


def test_exec_unreadable_lease_record_skips_window_kills(tmp_path: Path) -> None:
    """MINOR 6: fail toward sparing when a lease file exists but cannot be parsed."""
    unleased = _claude_bash(7_900_000, "python -m pytest", "python.exe", f"{VENV_PY} -m pytest -q", age=30)
    big = _claude_bash(7_900_100, "python -c x", "python.exe", f'{VENV_PY} -c "run()"', age=30)
    big[-1]["private_bytes"] = 9 * GIB
    torn = [
        {
            "kind": "repo_lock",
            "file": "heavy_workload.lock",
            "pid": 1,
            "age_minutes": 1,
            "mtime_age_seconds": 5,
            "raw": '{"schema_version": "we',
        }
    ]
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "torn", now=day, commit=50.0, processes=unleased, leases=torn),
            _scenario(tmp_path, "torn_budget", now=day, commit=50.0, processes=big, leases=torn),
        ],
    )

    torn_row = outcome["torn"]
    assert torn_row["stopped"] == []
    assert torn_row["status"]["agent_heavy_lease_records_unreadable"] is True
    assert "lease record(s) unreadable" in torn_row["log"]

    # The memory budget still acts, but on the heavy member only, never the whole tree.
    budget = outcome["torn_budget"]
    assert budget["stopped"] == [7_900_107]
    assert budget["status"]["actions"] == ["killed_agent_member_pid_7900107"]


def test_exec_foreign_and_stale_lease_records_neither_admit_nor_disable_kills(tmp_path: Path) -> None:
    """Re-review MAJOR 1: the integration mutex record, an empty file and an old torn file."""
    unleased = _claude_bash(7_910_000, "python -m pytest", "python.exe", f"{VENV_PY} -m pytest -q", age=30)
    pytest_child = f"{VENV_PY} -m pytest -q tests/operations/test_x.py"
    wrapper_tree = [
        _proc(7_910_101, "claude.exe", CLAUDE, age=200),
        _proc(7_910_103, "bash.exe", GIT_BASH.format(command="powershell -File x"), age=41, ppid=7_910_101),
        _proc(7_910_105, "powershell.exe", WRAPPER, age=40, ppid=7_910_103),
        _proc(7_910_107, "python.exe", pytest_child, age=39, ppid=7_910_105),
    ]
    mutex_dead = [{"kind": "integration_mutex", "file": "heavy_workload.lock", "pid": GONE, "age_minutes": 300}]
    empty_old = [{"kind": "repo_lock", "file": "heavy_workload.lock", "pid": 1, "age_minutes": 120, "raw": ""}]
    torn_old = [
        {
            "kind": "repo_lock",
            "file": "heavy_workload.slot2.lock",
            "pid": 1,
            "age_minutes": 10,
            "raw": '{"schema_version": "we',
        }
    ]
    empty_fresh = [dict(empty_old[0], mtime_age_seconds=3)]
    # The mutex writer itself is alive and older than the record: it is a live owner.
    mutex_live = [{"kind": "integration_mutex", "file": "heavy_workload.lock", "pid": 7_910_105, "age_minutes": 40}]
    # Same PID, but that process started after the record was written: PID reuse.
    mutex_reused = [dict(mutex_live[0], mtime_age_seconds=3600)]
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "mutex_dead", now=day, commit=50.0, processes=unleased, leases=mutex_dead),
            _scenario(tmp_path, "empty_old", now=day, commit=50.0, processes=unleased, leases=empty_old),
            _scenario(tmp_path, "torn_old", now=day, commit=50.0, processes=unleased, leases=torn_old),
            _scenario(tmp_path, "empty_fresh", now=day, commit=50.0, processes=unleased, leases=empty_fresh),
            _scenario(
                tmp_path, "mutex_live", now="2026-11-01T02:00:00", commit=50.0, processes=wrapper_tree, leases=mutex_live
            ),
            _scenario(tmp_path, "mutex_live_day", now=day, commit=50.0, processes=wrapper_tree, leases=mutex_live),
            _scenario(tmp_path, "mutex_reused", now=day, commit=50.0, processes=wrapper_tree, leases=mutex_reused),
        ],
    )

    for name in ("mutex_dead", "empty_old", "torn_old"):
        row = outcome[name]
        assert set(row["stopped"]) == {7_910_003, 7_910_005, 7_910_007}, name
        assert row["status"]["agent_heavy_lease_records_unreadable"] is False, name
        assert "unreadable" not in row["log"], name

    # An empty file written seconds ago may be an acquisition mid-write: spare this tick.
    fresh = outcome["empty_fresh"]
    assert fresh["stopped"] == []
    assert fresh["status"]["agent_heavy_lease_records_unreadable"] is True

    live = outcome["mutex_live"]
    assert live["stopped"] == []
    assert live["status"]["agent_heavy_admitted_workload_count"] == 1

    # The mutex record has no policy_window: it admits inside 00:30-09:05 only. In the
    # day its heavy child is stopped and the owner alone is spared (review M2).
    live_day = outcome["mutex_live_day"]
    assert live_day["stopped"] == [7_910_107]
    assert live_day["status"]["agent_heavy_admitted_workload_count"] == 0
    assert "lease owner pid 7910105 is past its policy window" in live_day["log"]

    reused = outcome["mutex_reused"]
    assert set(reused["stopped"]) == {7_910_103, 7_910_105, 7_910_107}
    assert reused["status"]["agent_heavy_admitted_workload_count"] == 0


def test_exec_budget_kill_on_a_leased_tree_stops_the_real_hog_not_a_heavy_chunk(tmp_path: Path) -> None:
    """Re-review MAJOR 2 / finding 7: the largest subtree off the spine dies, whatever it is."""
    base = 7_920_000
    tree = [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "bash.exe", GIT_BASH.format(command="powershell -File training_window.ps1"), age=61, ppid=base + 1),
        _proc(base + 5, "powershell.exe", TRAINING_WINDOW, age=60, ppid=base + 3),
        _proc(base + 7, "python.exe", f"{VENV_PY} -m weather.operations.nightly_retrain --all", age=59, ppid=base + 5),
        # Not a heavy process by command line, but it holds the memory.
        _proc(base + 9, "node.exe", r"node C:\scratch\big.js", age=30, private=9 * GIB, ppid=base + 3),
    ]
    outcome = _run(
        tmp_path,
        [
            _scenario(
                tmp_path,
                "night",
                now="2026-11-01T02:00:00",
                commit=50.0,
                processes=tree,
                leases=[_lock(base + 5, age=60)],
            )
        ],
    )

    night = outcome["night"]
    assert night["stopped"] == [base + 9]
    assert night["status"]["actions"] == [f"killed_agent_member_pid_{base + 9}"]
    assert "the owner is spared" in night["log"]


def test_exec_commit_emergency_spares_lease_owners_and_their_parents(tmp_path: Path) -> None:
    """Re-review MAJOR 2: at 92%+ commit a leased agent tree loses a branch, never the owner."""
    base = 7_930_000
    # claude.exe -> training_window (owner) -> node.exe hog (not heavy, so no budget kill first).
    leased = [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "powershell.exe", TRAINING_WINDOW, age=60, ppid=base + 1),
        _proc(base + 5, "node.exe", r"node C:\scratch\big.js", age=30, private=9 * GIB, ppid=base + 3),
        _proc(base + 7, "conhost.exe", CONHOST, age=60, private=5 * MIB, ppid=base + 3),
    ]
    parent = 7_930_100
    # claude.exe -> python tools\run_suite.py (9 GiB) -> bounded suite (owner).
    python_parent = [
        _proc(parent + 1, "claude.exe", CLAUDE, age=300),
        _proc(parent + 3, "python.exe", f"{VENV_PY} tools\\run_suite.py --all", age=30, private=9 * GIB, ppid=parent + 1),
        _proc(parent + 5, "powershell.exe", BOUNDED_SUITE, age=29, ppid=parent + 3),
    ]
    night = "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "leased", now=night, commit=95.0, processes=leased, leases=[_lock(base + 3, age=60)]),
            _scenario(tmp_path, "unleased", now=night, commit=95.0, processes=leased),
            _scenario(
                tmp_path,
                "python_parent",
                now=night,
                commit=95.0,
                processes=python_parent,
                leases=[_lock(parent + 5, age=29)],
            ),
            _scenario(tmp_path, "python_unleased", now=night, commit=95.0, processes=python_parent),
            _scenario(
                tmp_path,
                "python_detached",
                now=night,
                commit=95.0,
                processes=[dict(row, ppid=GONE) if row["pid"] == parent + 3 else row for row in python_parent[1:]],
                leases=[_lock(parent + 5, age=29)],
            ),
        ],
    )

    leased_row = outcome["leased"]
    assert leased_row["stopped"] == [base + 5]
    assert leased_row["status"]["actions"] == [f"killed_agent_branch_pid_{base + 5}"]

    # Without a lease the whole agent tree is still the emergency target.
    unleased_row = outcome["unleased"]
    assert base + 5 in unleased_row["stopped"]
    assert unleased_row["status"]["actions"] == [f"killed_agent_tree_pid_{base + 1}"]

    # Re-review N1: the 9 GiB parent that launched the owner is stopped alone; the owner
    # (orphaned) is not. The budget rule reaches it first, as a heavy script python.
    python_row = outcome["python_parent"]
    assert python_row["stopped"] == [parent + 3]
    assert python_row["status"]["actions"] == [f"killed_agent_ancestor_pid_{parent + 3}"]
    assert "its subtree is left running" in python_row["log"]

    # Outside any agent tree only the 92% rule sees it: still the single process.
    detached_row = outcome["python_detached"]
    assert detached_row["stopped"] == [parent + 3]
    assert detached_row["status"]["actions"] == [f"killed_python_ancestor_pid_{parent + 3}"]

    # Without the lease the same python is the emergency target.
    python_unleased = outcome["python_unleased"]
    assert parent + 3 in python_unleased["stopped"]


def test_exec_console_hosts_and_capture_children_are_never_lease_branch_targets(tmp_path: Path) -> None:
    """Re-review N2/N3: a conhost kill would end the owner's console; capture children are kept."""
    base = 7_940_000
    retrain = f"{VENV_PY} -m weather.operations.nightly_retrain --all"
    # The owner itself holds the memory; its console host and a small job hang off it.
    owner_hog = [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "bash.exe", GIT_BASH.format(command="powershell -File training_window.ps1"), age=61, ppid=base + 1),
        _proc(base + 5, "powershell.exe", TRAINING_WINDOW, age=60, private=9 * GIB, ppid=base + 3),
        _proc(base + 7, "conhost.exe", CONHOST, age=60, private=5 * MIB, ppid=base + 5),
        _proc(base + 9, "python.exe", f'{VENV_PY} -c "run()"', age=10, ppid=base + 5),
    ]
    capture = 7_940_100
    # A 7 GiB capture child restored by training_window, a 1.5 GiB stray, a small retrain.
    with_capture = [
        _proc(capture + 1, "claude.exe", CLAUDE, age=300),
        _proc(capture + 3, "bash.exe", GIT_BASH.format(command="powershell -File training_window.ps1"), age=61, ppid=capture + 1),
        _proc(capture + 5, "powershell.exe", TRAINING_WINDOW, age=60, ppid=capture + 3),
        _proc(capture + 7, "python.exe", retrain, age=59, ppid=capture + 5),
        _proc(capture + 9, "node.exe", r"node C:\scratch\big.js", age=30, private=1536 * MIB, ppid=capture + 3),
        _proc(
            capture + 11,
            "pythonw.exe",
            f"{VENV_PY} -m weather.collection.snapshot_tracker --ensure",
            age=5,
            private=7 * GIB,
            ppid=capture + 5,
        ),
        _proc(capture + 13, "conhost.exe", CONHOST, age=60, private=5 * MIB, ppid=capture + 3),
    ]
    night = "2026-11-01T02:00:00"
    owner_lease = [_lock(base + 5, age=60)]
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "owner_hog", now=night, commit=50.0, processes=owner_hog, leases=owner_lease),
            _scenario(tmp_path, "owner_hog_critical", now=night, commit=95.0, processes=owner_hog, leases=owner_lease),
            _scenario(
                tmp_path,
                "with_capture",
                now=night,
                commit=50.0,
                processes=with_capture,
                leases=[_lock(capture + 5, age=60)],
            ),
        ],
    )

    # Nothing off the spine could bring the tree under budget and the hog is the owner:
    # CRITICAL, nothing stopped (neither the conhost nor the small job is sacrificed).
    for name in ("owner_hog", "owner_hog_critical"):
        row = outcome[name]
        assert row["stopped"] == [], name
        assert "spared" in row["log"], name

    # The governed capture child is not eligible below the budget; the stray is enough.
    captured = outcome["with_capture"]
    assert captured["stopped"] == [capture + 9]
    assert captured["status"]["actions"] == [f"killed_agent_member_pid_{capture + 9}"]


# ---- L28 review of d3cb1b460 (L46): M1-M3, m4-m7 and nits, each lease vs no lease ----


def _wrapper_tree(base: int, *, child_cmd: str = f"{VENV_PY} -m pytest -q tests/a.py", private: int = 50 * MIB) -> list[dict]:
    """claude.exe -> bash.exe -> workstation_heavy.ps1 (lease owner, base+5) -> child."""
    return [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "bash.exe", GIT_BASH.format(command="powershell -File x"), age=41, ppid=base + 1),
        _proc(base + 5, "powershell.exe", WRAPPER, age=40, ppid=base + 3),
        _proc(base + 7, "python.exe", child_cmd, age=39, private=private, ppid=base + 5),
    ]


RELEASED = '{"schema_version":"weather_heavy_workload_lease_released_v1","workload":"x","released_at":"2026-11-01T13:00:00Z"}'


def test_exec_admitted_work_past_its_policy_window_is_stopped_and_the_owner_spared(tmp_path: Path) -> None:
    """M2/m1: an agent_heavy lease admits until 09:00 exactly; then its heavy work dies, the owner lives."""
    base = 7_950_000
    tree = _wrapper_tree(base)
    agent_heavy = [dict(_lock(base + 5, age=40), window="agent_heavy")]
    parent = 7_950_100
    # claude.exe -> python tools\run_suite.py (heavy) -> bounded suite (owner) -> chunk.
    python_parent = [
        _proc(parent + 1, "claude.exe", CLAUDE, age=300),
        _proc(parent + 3, "python.exe", f"{VENV_PY} tools\\run_suite.py --all", age=30, ppid=parent + 1),
        _proc(parent + 5, "powershell.exe", BOUNDED_SUITE, age=29, ppid=parent + 3),
        _proc(parent + 7, "python.exe", f"{VENV_PY} -m pytest -q tests/a.py", age=2, ppid=parent + 5),
    ]
    parent_lease = [dict(_lock(parent + 5, age=29), window="agent_heavy")]
    late, grace, nine = "2026-11-01T09:10:00", "2026-11-01T08:59:00", "2026-11-01T09:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "late", now=late, commit=50.0, processes=tree, leases=agent_heavy),
            _scenario(tmp_path, "grace", now=grace, commit=50.0, processes=tree, leases=agent_heavy),
            _scenario(tmp_path, "grace_unleased", now=nine, commit=50.0, processes=tree),
            _scenario(tmp_path, "nine", now=nine, commit=50.0, processes=tree, leases=agent_heavy),
            _scenario(tmp_path, "parent_late", now=late, commit=50.0, processes=python_parent, leases=parent_lease),
            _scenario(tmp_path, "parent_unleased", now=late, commit=50.0, processes=python_parent),
            _scenario(tmp_path, "workstation", now=late, commit=50.0, processes=tree, leases=[_lock(base + 5, age=40)]),
        ],
    )

    late_row = outcome["late"]
    assert late_row["stopped"] == [base + 7]
    assert late_row["status"]["actions"] == [f"killed_agent_member_pid_{base + 7}"]
    assert late_row["status"]["agent_heavy_admitted_workload_count"] == 0
    assert f"lease owner pid {base + 5} is past its policy window" in late_row["log"]
    assert "[CRITICAL]" in late_row["log"]

    # Review m1: no teardown grace past the guard's own 09:00 edge; 08:59 still admits.
    assert outcome["grace"]["stopped"] == []
    assert outcome["grace"]["status"]["agent_heavy_admitted_workload_count"] == 1
    assert outcome["nine"]["stopped"] == [base + 7]
    assert set(outcome["grace_unleased"]["stopped"]) == {base + 3, base + 5, base + 7}

    # A heavy owner ancestor is stopped alone; the owner is orphaned, its chunk stopped.
    parent_row = outcome["parent_late"]
    assert set(parent_row["stopped"]) == {parent + 3, parent + 7}
    assert f"killed_agent_ancestor_pid_{parent + 3}" in parent_row["status"]["actions"]
    assert f"killed_agent_member_pid_{parent + 7}" in parent_row["status"]["actions"]
    assert set(outcome["parent_unleased"]["stopped"]) == {parent + 3, parent + 5, parent + 7}

    # The workstation_offline profile has no time window.
    assert outcome["workstation"]["stopped"] == []


def test_exec_released_lease_marker_admits_nothing(tmp_path: Path) -> None:
    """M2: Exit-WeatherHeavyWorkloadLease overwrites the record; the guard reads it as no lease."""
    base = 7_951_000
    tree = _wrapper_tree(base)
    released = [dict(_lock(base + 5, age=40), raw=RELEASED, mtime_age_seconds=2)]
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "released", now=day, commit=50.0, processes=tree, leases=released),
            _scenario(tmp_path, "held", now=day, commit=50.0, processes=tree, leases=[_lock(base + 5, age=40)]),
        ],
    )

    released_row = outcome["released"]
    assert set(released_row["stopped"]) == {base + 3, base + 5, base + 7}
    assert released_row["status"]["agent_heavy_lease_records_unreadable"] is False
    assert released_row["status"]["agent_heavy_admitted_workload_count"] == 0
    held = outcome["held"]
    assert held["stopped"] == []
    assert held["status"]["agent_heavy_admitted_workload_count"] == 1


def test_exec_commit_emergency_relieves_a_leased_agent_tree_branch_by_branch(tmp_path: Path) -> None:
    """M1: at 95% commit, off-spine subtrees go largest first until the tree is under budget."""
    base = 7_952_000
    tree = _wrapper_tree(base, private=512 * MIB) + [
        # Three non-heavy tool trees of the same claude.exe.
        _proc(base + 11, "node.exe", r"node C:\scratch\a.js", age=20, private=4608 * MIB, ppid=base + 1),
        _proc(base + 13, "node.exe", r"node C:\scratch\b.js", age=20, private=4096 * MIB, ppid=base + 1),
        _proc(base + 15, "node.exe", r"node C:\scratch\c.js", age=20, private=3584 * MIB, ppid=base + 1),
    ]
    night = "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "leased", now=night, commit=95.0, processes=tree, leases=[_lock(base + 5, age=40)]),
            _scenario(tmp_path, "unleased", now=night, commit=95.0, processes=tree),
        ],
    )

    leased = outcome["leased"]
    # 12.9 GiB -> 8.4 GiB -> 4.4 GiB: two branches, largest first; the spine and pytest live.
    assert leased["stopped"] == [base + 11, base + 13]
    assert leased["status"]["actions"] == [f"killed_agent_branch_pid_{base + 11}", f"killed_agent_branch_pid_{base + 13}"]

    unleased = outcome["unleased"]
    assert unleased["status"]["actions"] == [f"killed_agent_tree_pid_{base + 1}"]
    assert {base + 5, base + 7, base + 11, base + 13, base + 15} <= set(unleased["stopped"])


def _guard_heavy_modules() -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("$guardHeavyModules = @(")
    body = text[start : text.index(")", start + len("$guardHeavyModules = @("))]
    modules = re.findall(r"'([a-z0-9_.]+)'", body)
    assert "weather.backtesting.r0_paired_replay" in modules and len(modules) == 8
    return modules


def test_exec_shell_line_rule_counts_loops_and_heavy_modules(tmp_path: Path) -> None:
    """M3: master's shell-line rule on powershell/pwsh/cmd, with the reader exemption."""
    ps = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "

    def shell_tree(base: int, shell: str, line: str, *, child: tuple[str, str, float] | None = None) -> list[dict]:
        rows = [
            _proc(base + 1, "claude.exe", CLAUDE, age=300),
            _proc(base + 3, shell, line, age=30, ppid=base + 1),
        ]
        if child:
            rows.append(_proc(base + 5, child[0], child[1], age=child[2], ppid=base + 3))
        return rows

    loop = ps + '"foreach ($f in $files) { python -m pytest -q $f }"'
    heavy_cases = [
        ("powershell.exe", loop, None),
        # The loop's current child is three seconds old: inside the grace, but the root is not.
        ("powershell.exe", HIDDEN_PS, ("python.exe", f"{VENV_PY} -m pytest -q tests/a.py", 0.05)),
        ("powershell.exe", ps + '"python -m weather.backtesting.r0_paired_replay run"', None),
        ("pwsh.exe", "pwsh -NoProfile -Command Get-ChildItem -Recurse C:\\repo", None),
        ("cmd.exe", 'cmd.exe /d /s /c "python -m compileall -q src"', None),
    ]
    light_cases = [
        ("powershell.exe", ps + '"python -m weather.operations.daily_refresh status"', None),
        ("powershell.exe", ps + '"python -m weather.backtesting.replay --help"', None),
        ("powershell.exe", ps + '"python -m weather.operations.capture_recovery_check"', None),
        ("cmd.exe", 'cmd.exe /d /s /c "git status"', None),
    ]
    heavy_table: list[dict] = []
    for index, (shell, line, child) in enumerate(heavy_cases):
        heavy_table += shell_tree(7_953_000 + 100 * index, shell, line, child=child)
    light_table: list[dict] = []
    for index, (shell, line, child) in enumerate(light_cases):
        light_table += shell_tree(7_953_500 + 100 * index, shell, line, child=child)
    # Leased: claude -> bash -> workstation_heavy.ps1 (owner) -> powershell loop.
    leased = _wrapper_tree(7_953_900)[:3] + [
        _proc(7_953_907, "powershell.exe", loop, age=39, ppid=7_953_905),
    ]
    modules = _guard_heavy_modules()
    module_table: list[dict] = []
    for index, module in enumerate(modules):
        module_table += shell_tree(7_954_000 + 100 * index, "powershell.exe", ps + f'"python -m {module} run"')
        module_table += _claude_bash(7_955_000 + 100 * index, f"python -m {module}", "python.exe", f"{VENV_PY} -m {module} run")
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "day", now=day, commit=50.0, processes=heavy_table + light_table),
            _scenario(tmp_path, "leased", now=day, commit=50.0, processes=leased, leases=[_lock(7_953_905, age=40)]),
            _scenario(tmp_path, "unleased", now=day, commit=50.0, processes=leased),
            _scenario(tmp_path, "modules", now=day, commit=50.0, processes=module_table),
        ],
    )

    day_row = outcome["day"]
    for index in range(len(heavy_cases)):
        assert 7_953_000 + 100 * index + 3 in day_row["stopped"], heavy_cases[index]
    assert not {row["pid"] for row in light_table} & set(day_row["stopped"])
    assert day_row["status"]["agent_heavy_workload_count"] == len(heavy_cases)

    assert outcome["leased"]["stopped"] == []
    assert outcome["leased"]["status"]["agent_heavy_admitted_workload_count"] == 1
    assert set(outcome["unleased"]["stopped"]) == {7_953_903, 7_953_905, 7_953_907}

    module_row = outcome["modules"]
    assert module_row["status"]["agent_heavy_workload_count"] == 2 * len(modules)
    for index in range(len(modules)):
        assert 7_954_000 + 100 * index + 3 in module_row["stopped"], modules[index]
        assert 7_955_000 + 100 * index + 7 in module_row["stopped"], modules[index]


def test_exec_unquoted_python_path_with_spaces_is_parsed(tmp_path: Path) -> None:
    """m7: C:\\Program Files\\Python312\\python.exe -m pytest without quotes."""
    line = r"C:\Program Files\Python312\python.exe -m pytest -q tests/a.py"
    status_line = r"C:\Program Files\Python312\python.exe -m weather.operations.daily_refresh status"
    tree = _wrapper_tree(7_956_000, child_cmd=line)
    light = _claude_bash(7_956_100, "python status", "python.exe", status_line)
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "unleased", now=day, commit=50.0, processes=tree + light),
            _scenario(tmp_path, "leased", now=day, commit=50.0, processes=tree, leases=[_lock(7_956_005, age=40)]),
        ],
    )

    unleased = outcome["unleased"]
    assert set(unleased["stopped"]) == {7_956_003, 7_956_005, 7_956_007}
    assert unleased["status"]["agent_heavy_workload_count"] == 1
    assert outcome["leased"]["stopped"] == []


def test_exec_spine_single_kill_needs_a_hog_that_relieves_the_spine(tmp_path: Path) -> None:
    """m4: a spine hog too small to bring the spine under budget is a WARNING, not a kill."""
    base = 7_957_000

    def spine(bash_mib: int, parent_mib: int, owner_mib: int) -> list[dict]:
        # claude -> bash -> python tools\run_suite.py -> bounded suite (owner) -> chunk.
        return [
            _proc(base + 1, "claude.exe", CLAUDE, age=300),
            _proc(
                base + 3,
                "bash.exe",
                GIT_BASH.format(command="python tools/run_suite.py"),
                age=31,
                private=bash_mib * MIB,
                ppid=base + 1,
            ),
            _proc(
                base + 5,
                "python.exe",
                f"{VENV_PY} tools\\run_suite.py --all",
                age=30,
                private=parent_mib * MIB,
                ppid=base + 3,
            ),
            _proc(base + 7, "powershell.exe", BOUNDED_SUITE, age=29, private=owner_mib * MIB, ppid=base + 5),
            _proc(base + 9, "python.exe", f"{VENV_PY} -m pytest -q tests/a.py", age=2, ppid=base + 7),
        ]

    small = spine(4608, 4506, 4506)  # a 13.3 GiB spine: no single non-owner frees 5.3 GiB
    large = spine(64, 8704, 64)
    lease = [_lock(base + 7, age=29)]
    night = "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "small", now=night, commit=50.0, processes=small, leases=lease),
            _scenario(tmp_path, "small_unleased", now=night, commit=50.0, processes=small),
            _scenario(tmp_path, "large", now=night, commit=50.0, processes=large, leases=lease),
        ],
    )

    small_row = outcome["small"]
    assert small_row["stopped"] == []
    assert "cannot bring the" in small_row["log"]
    assert outcome["small_unleased"]["status"]["action"] == f"killed_agent_tree_pid_{base + 3}"

    large_row = outcome["large"]
    assert large_row["stopped"] == [base + 5]
    assert large_row["status"]["actions"] == [f"killed_agent_ancestor_pid_{base + 5}"]


def test_exec_tree_kills_leave_console_hosts_while_lease_state_is_uncertain(tmp_path: Path) -> None:
    """m5: with a torn lease record a heavy member's conhost child is left running."""
    base = 7_958_000
    tree = _claude_bash(base, "python -c x", "python.exe", f'{VENV_PY} -c "run()"', age=30)
    tree[-1]["private_bytes"] = 9 * GIB
    tree.append(_proc(base + 9, "conhost.exe", CONHOST, age=29, private=5 * MIB, ppid=base + 7))
    torn = [
        {
            "kind": "repo_lock",
            "file": "heavy_workload.lock",
            "pid": 1,
            "age_minutes": 1,
            "mtime_age_seconds": 5,
            "raw": '{"schema_version": "we',
        }
    ]
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "torn", now=day, commit=50.0, processes=tree, leases=torn),
            _scenario(tmp_path, "no_lease", now=day, commit=50.0, processes=tree),
        ],
    )

    torn_row = outcome["torn"]
    assert torn_row["stopped"] == [base + 7]
    assert f"left console host pid {base + 9} running" in torn_row["log"]
    assert set(outcome["no_lease"]["stopped"]) == {base + 3, base + 5, base + 7, base + 9}


def test_exec_unc_scanner_paths_are_never_probed(tmp_path: Path) -> None:
    """Nit: a UNC path is not a repository data path (no SMB probe inside the guard)."""
    absolute_repo = tmp_path / "absrepo"
    (absolute_repo / ".git").mkdir(parents=True)
    (absolute_repo / "data").mkdir()
    unc = _claude_bash(7_959_000, "rg", "rg.exe", r"rg -n foo \\server\share\repo\data")
    local = _claude_bash(7_959_100, "rg", "rg.exe", f"rg -n foo {absolute_repo / 'data'}")
    leased = _wrapper_tree(7_959_200, child_cmd=f"rg -n foo {absolute_repo / 'data'}")
    leased[-1]["name"] = "rg.exe"
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "day", now=day, commit=50.0, processes=unc + local),
            _scenario(tmp_path, "leased", now=day, commit=50.0, processes=leased, leases=[_lock(7_959_205, age=40)]),
        ],
    )

    day_row = outcome["day"]
    assert not {7_959_003, 7_959_005, 7_959_007} & set(day_row["stopped"])
    assert 7_959_107 in day_row["stopped"]
    assert outcome["leased"]["stopped"] == []


def _guard_functions_probe(names: list[str], body: str) -> str:
    """Load named guard functions (and the probe source) via the parser, then run body."""
    quoted = ", ".join(f"'{name}'" for name in names)
    return (
        r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:GUARD_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'memory_commit_guard.ps1 does not parse' }
function Write-GuardLog([string]$Level, [string]$Message) { $script:guardLog.Add("[$Level] $Message") }
$script:guardLog = New-Object System.Collections.Generic.List[string]
foreach ($name in @("""
        + quoted
        + r""")) {
    $found = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
    if ($found.Count -ne 1) { throw "expected one function $name" }
    Invoke-Expression $found[0].Extent.Text
}
$probe = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$agentJobProbeSource' }, $true))
if ($probe.Count -ne 1) { throw 'expected one $agentJobProbeSource' }
Invoke-Expression $probe[0].Extent.Text
"""
        + body
    )


def _powershell_json(script: str) -> dict:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "GUARD_SCRIPT": str(SCRIPT)},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_lease_read_race_is_only_a_sharing_violation_or_a_vanished_file() -> None:
    """m6: an unreadable last-write time is a race only for these; anything else is an ERROR."""
    payload = _powershell_json(
        _guard_functions_probe(
            ["Test-AgentLeaseReadRace"],
            r"""
$sharing = New-Object System.IO.IOException('in use', [int]0x80070020)
$lock = New-Object System.IO.IOException('locked', [int]0x80070021)
$other = New-Object System.IO.IOException('disk', [int]0x8007001F)
[pscustomobject]@{
    not_found = Test-AgentLeaseReadRace (New-Object System.IO.FileNotFoundException('gone'))
    dir_not_found = Test-AgentLeaseReadRace (New-Object System.IO.DirectoryNotFoundException('gone'))
    sharing = Test-AgentLeaseReadRace $sharing
    lock = Test-AgentLeaseReadRace $lock
    wrapped = Test-AgentLeaseReadRace (New-Object System.Management.Automation.MethodInvocationException('x', $sharing))
    access = Test-AgentLeaseReadRace (New-Object System.UnauthorizedAccessException('denied'))
    other_io = Test-AgentLeaseReadRace $other
    none = Test-AgentLeaseReadRace $null
} | ConvertTo-Json -Compress
""",
        )
    )
    assert payload == {
        "not_found": True,
        "dir_not_found": True,
        "sharing": True,
        "lock": True,
        "wrapped": True,
        "access": False,
        "other_io": False,
        "none": False,
    }


def test_job_handle_probe_finds_an_owner_in_a_job_the_holder_holds() -> None:
    """m4: the probe answers 1 only when the holder holds a job handle containing the owner.

    Uses only processes this test starts (sleeping powershell children, killed in a
    finally) and a job this test creates; nothing else is opened or stopped.
    """
    payload = _powershell_json(
        _guard_functions_probe(
            ["Test-AgentHolderJobContainsOwner"],
            r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class L28JobFixture {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] public static extern IntPtr CreateJobObjectW(IntPtr a, string n);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool CloseHandle(IntPtr h);
}
'@
$sleeper = { Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 60' -WindowStyle Hidden -PassThru }
$inJob = & $sleeper
$outside = & $sleeper
$job = [IntPtr]::Zero
try {
    $job = [L28JobFixture]::CreateJobObjectW([IntPtr]::Zero, $null)
    if ($job -eq [IntPtr]::Zero) { throw 'CreateJobObject failed' }
    if (-not [L28JobFixture]::AssignProcessToJobObject($job, $inJob.Handle)) { throw 'AssignProcessToJobObject failed' }
    $row = { param($p) [pscustomobject]@{ ProcessId = [uint32]$p.Id } }
    [pscustomobject]@{
        holder_with_owner = Test-AgentHolderJobContainsOwner ([uint32]$PID) @(& $row $inJob)
        holder_without_owner = Test-AgentHolderJobContainsOwner ([uint32]$PID) @(& $row $outside)
        not_a_holder = Test-AgentHolderJobContainsOwner ([uint32]$outside.Id) @(& $row $inJob)
        no_owners = Test-AgentHolderJobContainsOwner ([uint32]$PID) @()
        gone_holder = Test-AgentHolderJobContainsOwner ([uint32]7999999) @(& $row $inJob)
        log = @($script:guardLog)
    } | ConvertTo-Json -Compress
}
finally {
    foreach ($p in @($inJob, $outside)) { try { if (-not $p.HasExited) { $p.Kill() } } catch { } }
    if ($job -ne [IntPtr]::Zero) { [void][L28JobFixture]::CloseHandle($job) }
}
""",
        )
    )
    assert payload["holder_with_owner"] == 1, payload
    assert payload["holder_without_owner"] == 0, payload
    assert payload["not_a_holder"] == 0, payload
    assert payload["no_owners"] == 0, payload
    assert payload["gone_holder"] == 0, payload
    assert payload["log"] == [], payload


def test_tree_kill_last_line_never_stops_a_live_owner_or_its_console_host() -> None:
    """m5: whatever the caller chose, Stop-VerifiedProcessTree skips owners and, while one
    lives or a record is unreadable, console hosts. Synthetic rows; Stop-Process is stubbed."""
    payload = _powershell_json(
        _guard_functions_probe(
            ["Get-ProcessTreeRows", "Test-GovernedWeatherProcess", "Test-AgentLeaseOwnerRow", "Stop-VerifiedProcessTree"],
            r"""
$born = (Get-Date).AddMinutes(-30)
function New-Row($id, $parent, $name, $cmd, $minutes) {
    [pscustomobject]@{ ProcessId = [uint32]$id; ParentProcessId = [uint32]$parent; Name = $name; CommandLine = $cmd; CreationDate = $born.AddMinutes($minutes) }
}
$rows = @(
    (New-Row 7960003 7960001 'bash.exe' 'bash -c x' 0),
    (New-Row 7960005 7960003 'powershell.exe' 'powershell -File workstation_heavy.ps1' 1),
    (New-Row 7960007 7960005 'conhost.exe' 'conhost.exe 0xffffffff -ForceV1' 1),
    (New-Row 7960009 7960005 'python.exe' 'python -m pytest -q' 2)
)
function Get-CimInstance { param($ClassName, $Filter, $ErrorAction)
    if ($Filter -match '^ProcessId = (\d+)$') { $w = [int]$Matches[1]; return $rows | Where-Object { [int]$_.ProcessId -eq $w } | Select-Object -First 1 }
    throw "unexpected filter $Filter" }
function Stop-Process { param($Id, [switch]$Force, $Confirm, $ErrorAction) $script:stopped.Add([int]$Id) }
function Invoke-Case([string]$Mode) {
    $script:stopped = New-Object System.Collections.Generic.List[int]
    $script:guardLog.Clear()
    $script:leaseOwners = @(); $script:liveLeaseOwnerRows = @(); $script:leaseRecordsUnreadable = $false
    if ($Mode -eq 'owner') {
        $script:leaseOwners = @([pscustomobject]@{ Pid = 7960005; CreationUtc = $rows[1].CreationDate.ToUniversalTime(); NotAfterUtc = $null; Window = 'agent_heavy' })
        $script:liveLeaseOwnerRows = @($rows[1])
    }
    if ($Mode -eq 'torn') { $script:leaseRecordsUnreadable = $true }
    $leaseOwners = $script:leaseOwners; $liveLeaseOwnerRows = $script:liveLeaseOwnerRows; $leaseRecordsUnreadable = $script:leaseRecordsUnreadable
    $ok = Stop-VerifiedProcessTree $rows[0] $rows 'probe' $true
    [pscustomobject]@{ ok = $ok; stopped = @($script:stopped | Sort-Object); log = @($script:guardLog) }
}
[pscustomobject]@{ owner = Invoke-Case 'owner'; torn = Invoke-Case 'torn'; none = Invoke-Case 'none' } | ConvertTo-Json -Compress -Depth 4
""",
        )
    )
    owner = payload["owner"]
    assert owner["ok"] is False
    assert owner["stopped"] == [7_960_003, 7_960_009]
    assert any("refusing to terminate heavy-workload lease owner pid 7960005" in line for line in owner["log"])
    assert any("left console host pid 7960007 running" in line for line in owner["log"])
    torn = payload["torn"]
    assert torn["stopped"] == [7_960_003, 7_960_005, 7_960_009]
    none = payload["none"]
    assert none["ok"] is True
    assert none["stopped"] == [7_960_003, 7_960_005, 7_960_007, 7_960_009]


# ---- L28 review of 1fe670753: B1, M1, M2, m1-m4 ----


def _host_state(pid: int, *, age: float, file: str = "heavy_workload_v1.poison") -> dict:
    return {"kind": "host_state", "file": file, "pid": pid, "age_minutes": age, "state": "ACTIVE"}


def test_exec_windowless_profiles_need_the_assigned_non_capture_host(tmp_path: Path) -> None:
    """B1: a daytime workstation_offline record admits only on the assigned workstation, for its own id."""
    base = 7_960_000
    tree = _wrapper_tree(base)
    lock = [_lock(base + 5, age=40)]
    day, night = "2026-11-01T14:00:00", "2026-11-01T02:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "workstation", now=day, commit=50.0, processes=tree, leases=lock),
            _scenario(tmp_path, "capture_assigned", now=day, commit=50.0, processes=tree, leases=lock, host="capture"),
            _scenario(
                tmp_path,
                "capture_registered",
                now=day,
                commit=50.0,
                processes=tree,
                leases=lock,
                expected_host_id=GUARD_HOST_ID,
            ),
            _scenario(
                tmp_path,
                "forged_record",
                now=day,
                commit=50.0,
                processes=tree,
                leases=[dict(_lock(base + 5, age=40), host_id=OTHER_HOST_ID)],
            ),
            _scenario(tmp_path, "unassigned_host", now=day, commit=50.0, processes=tree, leases=lock, host="other"),
            _scenario(tmp_path, "no_assignment", now=day, commit=50.0, processes=tree, leases=lock, host="none"),
            _scenario(tmp_path, "state_workstation", now=day, commit=50.0, processes=tree, leases=[_host_state(base + 5, age=40)]),
            _scenario(
                tmp_path,
                "state_capture",
                now=day,
                commit=50.0,
                processes=tree,
                leases=[_host_state(base + 5, age=40)],
                host="capture",
            ),
            _scenario(tmp_path, "capture_night", now=night, commit=50.0, processes=tree, leases=lock, host="capture"),
        ],
    )

    # The assigned non-capture host honours its own windowless records.
    for name in ("workstation", "state_workstation"):
        assert outcome[name]["stopped"] == [], name
        assert outcome[name]["status"]["agent_heavy_admitted_workload_count"] == 1, name
    # Anywhere else, or for a record naming another host, the agent_heavy window
    # applies: the daytime chunk dies, the owner is spared.
    for name in ("capture_assigned", "capture_registered", "forged_record", "unassigned_host", "no_assignment", "state_capture"):
        row = outcome[name]
        assert row["stopped"] == [base + 7], name
        assert row["status"]["actions"] == [f"killed_agent_member_pid_{base + 7}"], name
        assert row["status"]["agent_heavy_admitted_workload_count"] == 0, name
        assert "which this host does not honour" in row["log"], name
    assert "(registered capture host)" in outcome["capture_registered"]["log"]
    assert "(assigned capture host)" in outcome["capture_assigned"]["log"]
    # Inside 00:30-09:00 the same record still admits on the capture host.
    assert outcome["capture_night"]["stopped"] == []
    assert outcome["capture_night"]["status"]["agent_heavy_admitted_workload_count"] == 1


def test_exec_heavy_shell_above_the_owner_is_not_admitted_and_its_orphan_stays_governed(tmp_path: Path) -> None:
    """m4 + M1: the heavy shell on the spine dies alone; the orphaned owner tree stays attributed."""
    base = 7_961_000
    heavy_shell = (
        r'powershell.exe -NoProfile -Command "python -m pytest tests/smoke.py; '
        r'powershell -File scripts\ops\workstation_heavy.ps1 -Kind pytest"'
    )
    owner, chunk = base + 7, base + 9
    tick1 = [
        _proc(base + 1, "claude.exe", CLAUDE, age=300),
        _proc(base + 3, "cmd.exe", CMD_LAUNCHER, age=42, ppid=base + 1),
        _proc(base + 5, "powershell.exe", heavy_shell, age=41, ppid=base + 3),
        _proc(owner, "powershell.exe", WRAPPER, age=40, ppid=base + 5),
        _proc(chunk, "python.exe", f"{VENV_PY} -m pytest -q tests/a.py", age=39, ppid=owner),
    ]
    # After tick 1 the heavy shell is gone; the owner's parent pid names nothing.
    orphan = [row for row in tick1 if row["pid"] in (owner, chunk)]
    day = "2026-11-01T14:00:00"
    workstation = [_lock(owner, age=40)]
    agent_heavy = [dict(_lock(owner, age=40), window="agent_heavy")]
    remembered = {"owners": [owner], "unreadable_streak": 0, "age_seconds": 60}
    big_chunk = [dict(orphan[0]), dict(orphan[1], private_bytes=9 * GIB)]
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "tick1", now=day, commit=50.0, processes=tick1, leases=workstation),
            _scenario(tmp_path, "orphan_admitted", now=day, commit=50.0, processes=orphan, leases=workstation, prior_state=remembered),
            _scenario(tmp_path, "orphan_late", now=day, commit=50.0, processes=orphan, leases=agent_heavy, prior_state=remembered),
            _scenario(tmp_path, "orphan_unremembered", now=day, commit=50.0, processes=orphan, leases=agent_heavy),
            _scenario(tmp_path, "orphan_budget", now=day, commit=50.0, processes=big_chunk, leases=workstation, prior_state=remembered),
            _scenario(tmp_path, "orphan_released", now=day, commit=50.0, processes=orphan, prior_state=remembered),
        ],
    )

    # m4: the in-window owner admits its chunk, not the heavy shell above it, which
    # is stopped alone (the owner is orphaned, never stopped) and the owner remembered.
    tick1_row = outcome["tick1"]
    assert tick1_row["stopped"] == [base + 5]
    assert tick1_row["status"]["actions"] == [f"killed_agent_ancestor_pid_{base + 5}"]
    assert [tree["pid"] for tree in tick1_row["state"]["lease_owner_trees"]] == [owner]

    # M1: the orphaned owner becomes its own tool root; its lease still admits...
    admitted = outcome["orphan_admitted"]
    assert admitted["stopped"] == []
    assert admitted["status"]["agent_heavy_orphaned_lease_tree_count"] == 1
    assert admitted["status"]["agent_heavy_admitted_workload_count"] == 1
    # ...a lease past its window no longer does, and the budget still applies...
    late = outcome["orphan_late"]
    assert late["stopped"] == [chunk]
    assert late["status"]["actions"] == [f"killed_agent_member_pid_{chunk}"]
    budget = outcome["orphan_budget"]
    assert budget["stopped"] == [chunk]
    assert budget["status"]["actions"] == [f"killed_agent_member_pid_{chunk}"]
    # ...where without the memory the orphan escaped every agent rule.
    assert outcome["orphan_unremembered"]["stopped"] == []
    assert outcome["orphan_unremembered"]["status"]["agent_heavy_workload_count"] == 0
    # A released lease ends the attribution and the memory.
    released = outcome["orphan_released"]
    assert released["stopped"] == []
    assert released["status"]["agent_heavy_orphaned_lease_tree_count"] == 0
    assert released["state"]["lease_owner_trees"] == []


def test_exec_lease_owner_past_the_hard_ceiling_is_stopped(tmp_path: Path) -> None:
    """M2: an owner growing in-process is spared below 97% / 2x budget and stopped above it."""
    base = 7_962_000

    def tree(owner_bytes: int, *, heavy_child: bool = True) -> list[dict]:
        rows = _wrapper_tree(base)
        rows[2] = dict(rows[2], private_bytes=owner_bytes)
        if not heavy_child:
            rows[3] = dict(rows[3], name="node.exe", cmd=r"node C:\scratch\idle.js")
        return rows

    lock = [_lock(base + 5, age=40)]
    night = "2026-11-01T02:00:00"
    owner_tree = {base + 5, base + 7}
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "budget_spared", now=night, commit=50.0, processes=tree(12 * GIB), leases=lock),
            _scenario(tmp_path, "budget_double", now=night, commit=50.0, processes=tree(17 * GIB), leases=lock),
            _scenario(tmp_path, "budget_ceiling", now=night, commit=97.5, processes=tree(12 * GIB), leases=lock),
            _scenario(tmp_path, "budget_unleased", now=night, commit=50.0, processes=tree(12 * GIB)),
            _scenario(
                tmp_path, "emergency_spared", now=night, commit=95.0, processes=tree(12 * GIB, heavy_child=False), leases=lock
            ),
            _scenario(
                tmp_path, "emergency_ceiling", now=night, commit=97.5, processes=tree(12 * GIB, heavy_child=False), leases=lock
            ),
            _scenario(
                tmp_path, "emergency_unleased", now=night, commit=95.0, processes=tree(12 * GIB, heavy_child=False)
            ),
        ],
    )

    spared = outcome["budget_spared"]
    assert spared["stopped"] == []
    assert "spared below the hard ceiling" in spared["log"]
    for name in ("budget_double", "budget_ceiling"):
        row = outcome[name]
        assert set(row["stopped"]) == owner_tree, name
        assert row["status"]["actions"] == [f"killed_lease_owner_pid_{base + 5}"], name
        assert "past the hard ceiling" in row["log"] and "[CRITICAL]" in row["log"], name
    # Unleased, the same tree goes whole below any ceiling, as on master.
    assert set(outcome["budget_unleased"]["stopped"]) == {base + 3, base + 5, base + 7}

    em_spared = outcome["emergency_spared"]
    assert em_spared["stopped"] == []
    assert "spared below the hard ceiling" in em_spared["log"]
    em_ceiling = outcome["emergency_ceiling"]
    assert set(em_ceiling["stopped"]) == owner_tree
    assert em_ceiling["status"]["actions"] == [f"killed_lease_owner_pid_{base + 5}"]
    # Unleased, master's commit emergency still takes the agent tree from its root (B2).
    em_unleased = outcome["emergency_unleased"]
    assert set(em_unleased["stopped"]) == {base + 1, base + 3, base + 5, base + 7}
    assert em_unleased["status"]["actions"] == [f"killed_agent_tree_pid_{base + 1}"]


def test_exec_unreadable_lease_records_stop_sparing_after_two_runs(tmp_path: Path) -> None:
    """m2/m3: a lock rewritten as garbage every minute cannot disable the window or budget rules."""
    unleased = _claude_bash(7_963_000, "python -m pytest", "python.exe", f"{VENV_PY} -m pytest -q", age=30)
    big = _claude_bash(7_963_100, "python -c x", "python.exe", f'{VENV_PY} -c "run()"', age=30)
    big[-1]["private_bytes"] = 9 * GIB
    torn = [
        {
            "kind": "repo_lock",
            "file": "heavy_workload.lock",
            "pid": 1,
            "age_minutes": 1,
            "mtime_age_seconds": 5,
            "raw": "",
        }
    ]

    def prior(streak: int, age: float = 60) -> dict:
        return {"owners": [], "unreadable_streak": streak, "age_seconds": age}

    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            _scenario(tmp_path, "second", now=day, commit=50.0, processes=unleased, leases=torn, prior_state=prior(1)),
            _scenario(tmp_path, "third", now=day, commit=50.0, processes=unleased, leases=torn, prior_state=prior(2)),
            _scenario(tmp_path, "stale_prior", now=day, commit=50.0, processes=unleased, leases=torn, prior_state=prior(5, 600)),
            _scenario(tmp_path, "budget_second", now=day, commit=50.0, processes=big, leases=torn, prior_state=prior(1)),
            _scenario(tmp_path, "budget_third", now=day, commit=50.0, processes=big, leases=torn, prior_state=prior(2)),
        ],
    )

    second = outcome["second"]
    assert second["stopped"] == []
    assert second["status"]["agent_heavy_lease_unreadable_streak"] == 2
    assert second["state"]["lease_records_unreadable_streak"] == 2
    # A stale memory restarts the count.
    assert outcome["stale_prior"]["stopped"] == []
    assert outcome["stale_prior"]["status"]["agent_heavy_lease_unreadable_streak"] == 1
    # From the third run in a row every rule applies again, as on master.
    third = outcome["third"]
    assert set(third["stopped"]) == {7_963_003, 7_963_005, 7_963_007}
    assert third["status"]["agent_heavy_lease_records_unreadable"] is False
    assert third["status"]["agent_heavy_lease_unreadable_streak"] == 3
    assert "for 3 runs in a row; no longer sparing" in third["log"]
    assert outcome["budget_second"]["stopped"] == [7_963_107]
    budget_third = outcome["budget_third"]
    assert set(budget_third["stopped"]) == {7_963_103, 7_963_105, 7_963_107}
    assert budget_third["status"]["actions"] == ["killed_agent_tree_pid_7963103"]


def test_exec_guard_state_failures_only_ever_spare(tmp_path: Path) -> None:
    """Delta (a): a state file that cannot be written or read never makes the guard kill more."""
    unleased = _claude_bash(7_964_000, "python -m pytest", "python.exe", f"{VENV_PY} -m pytest -q", age=30)
    torn = [
        {
            "kind": "repo_lock",
            "file": "heavy_workload.lock",
            "pid": 1,
            "age_minutes": 1,
            "mtime_age_seconds": 5,
            "raw": "",
        }
    ]

    def prior(streak: int, age: float = 60, **extra) -> dict:
        return {"owners": [], "unreadable_streak": streak, "age_seconds": age, **extra}

    # An orphaned owner tree (as in the m4/M1 test) whose lease is past its window.
    base = 7_964_100
    owner, chunk = base + 7, base + 9
    orphan = [
        _proc(owner, "powershell.exe", WRAPPER, age=40, ppid=base + 5),
        _proc(chunk, "python.exe", f"{VENV_PY} -m pytest -q tests/a.py", age=39, ppid=owner),
    ]
    late = [dict(_lock(owner, age=40), window="agent_heavy")]
    day = "2026-11-01T14:00:00"
    outcome = _run(
        tmp_path,
        [
            # Control: the third unreadable run in a row with a good memory kills.
            _scenario(tmp_path, "control", now=day, commit=50.0, processes=unleased, leases=torn, prior_state=prior(2)),
            _scenario(
                tmp_path, "write_fails", now=day, commit=50.0, processes=unleased, leases=torn,
                prior_state=prior(1), fail_state_write=True,
            ),
            # The run after a failed write finds the record from two runs ago.
            _scenario(tmp_path, "after_failed_write", now=day, commit=50.0, processes=unleased, leases=torn, prior_state=prior(2, 120)),
            _scenario(
                tmp_path, "read_locked", now=day, commit=50.0, processes=unleased, leases=torn,
                prior_state=prior(2), lock_state=True,
            ),
            _scenario(
                tmp_path, "read_invalid", now=day, commit=50.0, processes=unleased, leases=torn,
                prior_state=prior(2, raw="{not json"),
            ),
            # The remembered orphan set: kept from a record left by a failed write...
            _scenario(
                tmp_path, "orphan_after_failed_write", now=day, commit=50.0, processes=orphan, leases=late,
                prior_state={"owners": [owner], "unreadable_streak": 0, "age_seconds": 120},
            ),
            # ...and lost on an unreadable record, which only spares.
            _scenario(
                tmp_path, "orphan_read_locked", now=day, commit=50.0, processes=orphan, leases=late,
                prior_state={"owners": [owner], "unreadable_streak": 0, "age_seconds": 60}, lock_state=True,
            ),
        ],
    )

    control = outcome["control"]
    assert set(control["stopped"]) == {7_964_003, 7_964_005, 7_964_007}
    assert control["status"]["guard_state_read"] == "ok"
    assert control["status"]["guard_state_degraded"] is False
    assert control["status"]["guard_state_written"] is True

    # Write failure: logged as ERROR, status degraded, the previous record left as it was.
    failed = outcome["write_fails"]
    assert failed["stopped"] == []
    assert failed["errors"] == []
    assert failed["status"]["agent_heavy_lease_unreadable_streak"] == 2
    assert failed["status"]["guard_state_degraded"] is True
    assert failed["status"]["guard_state_written"] is False
    assert "[ERROR]" in failed["log"] and "could not be written" in failed["log"]
    assert failed["state"]["lease_records_unreadable_streak"] == 1
    # The next run does not carry that record's streak (it may be short of the truth
    # or past it), so the count restarts and the work is spared.
    after = outcome["after_failed_write"]
    assert after["stopped"] == []
    assert after["status"]["agent_heavy_lease_unreadable_streak"] == 1
    assert after["status"]["guard_state_read"] == "ok"
    assert after["status"]["guard_state_degraded"] is False

    # Read failures: empty memory, degraded, ERROR, nothing stopped.
    for name, read in (("read_locked", "unreadable"), ("read_invalid", "invalid")):
        row = outcome[name]
        assert row["stopped"] == [], name
        assert row["errors"] == [], name
        assert row["status"]["guard_state_read"] == read, name
        assert row["status"]["guard_state_degraded"] is True, name
        assert row["status"]["agent_heavy_lease_unreadable_streak"] == 1, name
        assert "[ERROR]" in row["log"] and f"is {read}" in row["log"], name
    # An unreadable record is left for the next run; a damaged one is replaced.
    assert outcome["read_locked"]["status"]["guard_state_written"] is False
    assert outcome["read_locked"]["state"]["lease_records_unreadable_streak"] == 2
    assert outcome["read_invalid"]["status"]["guard_state_written"] is True
    assert outcome["read_invalid"]["state"]["lease_records_unreadable_streak"] == 1

    # The orphan set survives a failed write for five minutes (the attribution is by
    # PID and creation instant, so it is still exact)...
    kept = outcome["orphan_after_failed_write"]
    assert kept["status"]["agent_heavy_orphaned_lease_tree_count"] == 1
    assert kept["stopped"] == [chunk]
    # ...and an unreadable record attributes nothing: the orphan is spared, not stopped.
    lost = outcome["orphan_read_locked"]
    assert lost["status"]["agent_heavy_orphaned_lease_tree_count"] == 0
    assert lost["stopped"] == []
