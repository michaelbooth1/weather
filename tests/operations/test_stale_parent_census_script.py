"""Execution and safety tests for the read-only stale-parent census.

The unmodified `scripts/ops/stale_parent_census.ps1` runs in a Windows PowerShell child against a
synthetic process table: `Get-CimInstance` is shadowed by a function in the caller's scope (the same
technique as test_memory_commit_guard_execution.py), so no host process is inspected.

Synthetic PIDs are odd numbers above 7,000,000; Windows PIDs are multiples of four, so a stub can
never name a real process.

Guards: design docs/research/recorder-live-parent-design-2026-11-01 section 4.2 (a read-only census
that classifies a parent as live only if it exists AND was created no later than the child).
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
SCRIPT = REPO_ROOT / "scripts" / "ops" / "stale_parent_census.ps1"

GONE = 7_999_999  # a parent PID absent from every synthetic table

HARNESS = r"""
$ErrorActionPreference = 'Stop'
$spec = Get-Content -LiteralPath $env:CENSUS_SPEC -Raw -Encoding UTF8 | ConvertFrom-Json
$global:Calls = New-Object System.Collections.Generic.List[string]
$now = New-Object DateTime (2026, 11, 1, 12, 0, 0, [DateTimeKind]::Utc)
$global:FakeRows = @(foreach ($p in $spec.processes) {
    [pscustomobject]@{
        ProcessId = [uint32]$p.pid
        ParentProcessId = [uint32]$p.ppid
        Name = [string]$p.name
        CommandLine = [string]$p.cmd
        CreationDate = $now.AddMinutes(-[double]$p.age_minutes).ToLocalTime()
    }
})
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $global:Calls.Add("Get-CimInstance:${ClassName}:${Filter}")
    if ($ClassName -ne 'Win32_Process') { throw "unexpected class $ClassName" }
    return $global:FakeRows
}
$arguments = @{}
if ($spec.out_file) { $arguments['OutFile'] = $spec.out_file }
if ($spec.patterns_json) { $arguments['WorkerPatternsJson'] = $spec.patterns_json }
$text = (& $env:CENSUS_SCRIPT @arguments | Out-String)
[pscustomobject]@{ calls = @($global:Calls); stdout = $text } | ConvertTo-Json -Depth 4 -Compress
"""


def _proc(pid, ppid, name, cmd, age):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "age_minutes": age}


def _run(tmp_path: Path, processes, **extra) -> dict:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"processes": processes, **extra}), encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", HARNESS],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "CENSUS_SCRIPT": str(SCRIPT), "CENSUS_SPEC": str(spec_path)},
    )
    assert result.returncode == 0, result.stderr
    outer = json.loads(result.stdout)
    outer["report"] = json.loads(outer["stdout"])
    return outer


PY = r"C:\repo\venv\Scripts\pythonw.exe"
REC = r"C:\wt\l13\tools\research\hrrr_forward_recorder.py"

# A table with one worker per parent outcome, plus decoys that must not be counted.
TABLE = [
    _proc(7_000_001, 0, "services.exe", "", 5000),
    # maker shadow: live parent (scheduler host created long before the worker)
    _proc(7_000_003, 7_000_001, "svchost.exe", r"C:\Windows\system32\svchost.exe -k netsvcs", 4000),
    _proc(7_000_005, 7_000_003, "python.exe",
          rf"{PY} -m weather.market.maker_shadow run --config c.json --stop-file STOP", 60),
    # CLOB loop: the ensure parent has exited (pid absent)
    _proc(7_000_007, GONE, "pythonw.exe",
          rf"{PY} -m weather.market.market_microstructure loop --market all --interval-seconds 5", 90),
    # observation loop: its ppid now names an unrelated process created AFTER the child
    _proc(7_000_009, 7_000_011, "pythonw.exe",
          rf"{PY} -m weather.operations.observation_trigger loop --market all", 120),
    _proc(7_000_011, 7_000_001, "node.exe", "node unrelated.js", 5),
    # WS recorder chain: cmd wrapper under a dead WMI host; redirector and interpreter under live parents
    _proc(7_000_013, 7_000_015, "cmd.exe", rf'cmd.exe /c ""venv\python.exe" {REC} 1>>stdout.log"', 30),
    _proc(7_000_017, 7_000_013, "python.exe", rf"venv\python.exe {REC}", 30),
    # execution tape producer, live parent
    _proc(7_000_019, 7_000_003, "pythonw.exe",
          rf"{PY} -m weather.operations.execution_tape_supervisor run --market all", 45),
    # decoys: ensure interpreters, a hot-capture child, an evidence dry run, a launcher, a hidden row
    _proc(7_000_021, 7_000_003, "pythonw.exe", rf"{PY} -m weather.operations.observation_trigger ensure", 1),
    _proc(7_000_023, 7_000_003, "pythonw.exe", rf"{PY} -m weather.operations.thin_ensure --ensure --loop clob", 1),
    _proc(7_000_025, 7_000_007, "python.exe",
          rf"{PY} -m weather.market.market_microstructure loop --expected-runtime-fingerprint x", 1),
    _proc(7_000_027, 7_000_003, "python.exe", rf"{PY} -m weather.market.maker_evidence_capture --dry-run", 1),
    _proc(7_000_029, 7_000_003, "powershell.exe", r"powershell -File hrrr_forward_recorder_launch.ps1", 1),
    _proc(7_000_031, 7_000_003, "pythonw.exe", "", 10),
]


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None,
                    reason="runs the real census under Windows PowerShell")
def test_census_classifies_live_dead_and_reused_parents(tmp_path: Path) -> None:
    out_file = tmp_path / "census.json"
    result = _run(tmp_path, TABLE, out_file=str(out_file))
    report = result["report"]
    assert result["calls"] == ["Get-CimInstance:Win32_Process:"]
    assert report["schema"] == "weather.stale_parent_census.v1"
    assert report["read_only"] is True
    assert report["patterns_source"] == "default"
    assert json.loads(out_file.read_text(encoding="utf-8")) == report

    by_pid = {row["pid"]: row for row in report["workers"]}
    assert set(by_pid) == {7_000_005, 7_000_007, 7_000_009, 7_000_013, 7_000_017, 7_000_019}

    live = by_pid[7_000_005]
    assert (live["worker"], live["parent_status"], live["parent_alive"]) == ("maker_shadow", "live", True)
    assert live["parent_created_before_child"] is True
    assert live["parent"]["name"] == "svchost.exe"
    assert live["chain_exposed_link"] is None  # chain reaches services.exe with ppid 0

    dead = by_pid[7_000_007]
    assert (dead["worker"], dead["parent_status"], dead["parent_alive"]) == ("clob_book_loop", "dead", False)
    assert dead["parent_exists"] is False and dead["parent"] is None
    assert dead["parent_created_before_child"] is None
    assert dead["chain_exposed_link"]["depth"] == 0

    reused = by_pid[7_000_009]
    assert reused["worker"] == "observation_trigger_loop"
    assert (reused["parent_status"], reused["parent_alive"], reused["parent_exists"]) == ("reused", False, True)
    assert reused["parent_created_before_child"] is False
    assert reused["parent"]["name"] == "node.exe"

    # The recorder interpreter's own parent is live, but its chain is exposed one link up.
    interp = by_pid[7_000_017]
    assert (interp["worker"], interp["parent_status"]) == ("ws_forward_recorder", "live")
    assert interp["chain_exposed_link"] == {
        "pid": 7_000_013, "name": "cmd.exe", "parent_pid": 7_000_015, "parent_status": "dead", "depth": 1,
    }
    assert by_pid[7_000_013]["parent_status"] == "dead"
    assert by_pid[7_000_019]["worker"] == "execution_tape_supervisor"

    summary = report["summary"]
    assert summary["processes_scanned"] == len(TABLE)
    assert (summary["parent_live"], summary["parent_dead"], summary["parent_reused"]) == (3, 2, 1)
    assert summary["chain_exposed"] == 4
    assert summary["python_rows_without_command_line"] == 1
    assert [row["parent_pid"] for row in summary["stale_parent_pids"]] == [7_000_011, 7_000_015, GONE]
    assert summary["by_worker"]["ws_forward_recorder"]["processes"] == 2
    assert summary["by_worker"]["snapshot_loop"]["processes"] == 0


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None,
                    reason="runs the real census under Windows PowerShell")
def test_census_patterns_are_a_parameter(tmp_path: Path) -> None:
    patterns = json.dumps({"only_node": {"match": r"unrelated\.js"}})
    tables = TABLE + [_proc(7_000_033, GONE, "node.exe", "node other.js", 3)]
    report = _run(tmp_path, tables, patterns_json=patterns)["report"]
    assert report["patterns_source"] == "json"
    # node.exe is outside the default image filter, so nothing matches.
    assert report["workers"] == []
    assert list(report["summary"]["by_worker"]) == ["only_node"]


_FORBIDDEN = re.compile(
    r"Stop-Process|taskkill|tskill|\.Kill\(|TerminateProcess|wmic|Invoke-CimMethod|Invoke-WmiMethod|"
    r"Remove-CimInstance|Set-CimInstance|schtasks|Register-ScheduledTask|Unregister-ScheduledTask|"
    r"Set-ScheduledTask|Enable-ScheduledTask|Disable-ScheduledTask|Start-ScheduledTask|Stop-ScheduledTask|"
    r"New-ScheduledTask|Schedule\.Service|Start-Process|Set-Content|Add-Content|Out-File|New-Item|"
    r"Remove-Item|Move-Item|Copy-Item|Set-ItemProperty|Restart-|Stop-Service|Set-Service",
    re.IGNORECASE,
)


def test_census_script_has_no_kill_scheduler_or_write_cmdlets() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")
    assert _FORBIDDEN.findall(source) == []
    # The only write is the optional -OutFile.
    assert source.count("WriteAllText") == 1
    assert "[IO.File]::WriteAllText([IO.Path]::GetFullPath($OutFile)" in source
