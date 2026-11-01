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
        if ($lease.kind -eq 'repo_lock') {
            $dir = Join-Path $scenario.repo_root 'data\logs'
            $record = [ordered]@{
                schema_version = 'weather_heavy_workload_lease_v3'
                workload = 'WorkstationOffline-pytest-1'
                pid = [int]$lease.pid
                owner_process_creation_time_token = 'win32-filetime:{0}' -f $born.ToFileTimeUtc()
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
        [IO.File]::WriteAllText((Join-Path $dir ([string]$lease.file)), $body)
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


def _scenario(tmp_path: Path, name: str, *, now: str, commit: float, processes, **extra) -> dict:
    repo_root = tmp_path / name
    repo_root.mkdir()
    return {
        "name": name,
        "repo_root": str(repo_root),
        "now_parts": [int(part) for part in now.replace("T", "-").replace(":", "-").split("-")[:5]],
        "os": extra.pop("os", None) or _os(commit),
        "processes": processes,
        "task_name": EVIDENCE_TASK,
        "task_state": extra.pop("task_state", None),
        "expected_host_id": extra.pop("expected_host_id", None),
        "leases": extra.pop("leases", []),
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
    for row in rows:
        # No swallowed PowerShell error and no internal failure logged by the guard itself.
        assert row["errors"] == [], (row["name"], row["errors"])
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
                "night_pair",
                now="2026-11-01T02:00:00",
                commit=50.0,
                processes=leased + other_tree,
                leases=repo_lock,
            ),
        ],
    )

    for name in ("repo_lock", "host_state"):
        admitted = outcome[name]
        assert admitted["stopped"] == [], name
        assert admitted["status"]["agent_heavy_workload_count"] == 1, name
        assert admitted["status"]["agent_heavy_admitted_workload_count"] == 1, name
        assert admitted["status"]["action"] == "none", name

    for name in ("stale", "teardown", "unleased"):
        reaped = outcome[name]
        assert set(reaped["stopped"]) == {7_300_003, 7_300_005, 7_300_007}, name
        assert reaped["status"]["agent_heavy_admitted_workload_count"] == 0, name

    # Only the unleased sibling dies; the admitted wrapper and its pytest child survive.
    mixed = outcome["mixed"]
    assert mixed["stopped"] == [7_300_009]
    assert mixed["status"]["action"] == "killed_agent_member_pid_7300009"
    assert "unadmitted member of a leased tool tree" in mixed["log"]

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
    assert "the lease owner is spared" in leased["log"]

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
    leases = [_lock(suite + 7, age=90), _lock(train + 3, age=60, file="heavy_workload.slot2.lock")]
    outcome = _run(
        tmp_path,
        [
            _scenario(
                tmp_path, "night", now="2026-11-01T02:00:00", commit=50.0, processes=bounded + training, leases=leases
            ),
            _scenario(tmp_path, "settlement", now="2026-11-01T14:00:00", commit=50.0, processes=settlement),
        ],
    )

    night = outcome["night"]
    assert night["stopped"] == []
    assert night["status"]["agent_heavy_workload_count"] == 2
    assert night["status"]["agent_heavy_admitted_workload_count"] == 2
    # daily_refresh (run and status alike) is not on the heavy list.
    settlement_row = outcome["settlement"]
    assert settlement_row["stopped"] == []
    assert settlement_row["status"]["agent_heavy_workload_count"] == 0


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
        {"kind": "repo_lock", "file": "heavy_workload.lock", "pid": 1, "age_minutes": 1, "raw": '{"schema_version": "we'}
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
