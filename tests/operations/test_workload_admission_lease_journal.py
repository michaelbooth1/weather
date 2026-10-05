"""Execution tests for the heavy-workload lease journal in workload_admission.ps1.

Guards: Swarm L M4-c (OD M4 condition 3) - the lease journal records the owner's
process creation identity and not only its PID (RF "A live PID proves..."),
fails open so a journal error never changes admission (EF 8u), and rotates by
rename, never deletion (EF 8e).

Every case dot-sources the real script under Windows PowerShell 5.1 ``-File``
from an unrelated working directory against a ``tmp_path`` repository root. No
case takes the host-global workload mutex or touches a real lease file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ADMISSION = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
JOURNAL = Path("data") / "logs" / "heavy_workload_journal.jsonl"
REAL_LEASE_PATHS = (
    REPO_ROOT / "data" / "logs" / "heavy_workload.lock",
    REPO_ROOT / "data" / "logs" / "heavy_workload_journal.jsonl",
)

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or WINDOWS_POWERSHELL is None,
        reason="the lease journal is exercised under Windows PowerShell 5.1",
    ),
]


def _real_state() -> dict[str, tuple[bool, int | None, int | None]]:
    state = {}
    for path in REAL_LEASE_PATHS:
        try:
            stat = path.stat()
            state[str(path)] = (True, stat.st_size, stat.st_mtime_ns)
        except OSError:
            state[str(path)] = (False, None, None)
    return state


def _run_driver(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    assert WINDOWS_POWERSHELL is not None
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        "param([string]$Admission, [string]$Root)\n"
        '$ErrorActionPreference = "Stop"\n'
        ". $Admission\n" + body,
        encoding="utf-8",
    )
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir(exist_ok=True)
    before = _real_state()
    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver), "-Admission", str(ADMISSION), "-Root", str(tmp_path / "repo")],
        cwd=elsewhere, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=120,
    )
    assert _real_state() == before, "a journal test touched the real lease or journal"
    return result


def _journal(tmp_path: Path) -> list[dict]:
    path = tmp_path / "repo" / JOURNAL
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_journal_records_pid_and_process_creation_identity(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    result = _run_driver(tmp_path, r'''
$acquired = [DateTime]::UtcNow.AddSeconds(-30).ToString("o")
Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "acquired" -Workload "quiet_window_merge" `
    -ExecutionHostProfile "capture_colocated_v1" -PolicyWindow "heavy_window" -AcquiredAtUtc $acquired
Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "released" -Workload "quiet_window_merge" `
    -ExecutionHostProfile "capture_colocated_v1" -AcquiredAtUtc $acquired
$me = [Diagnostics.Process]::GetCurrentProcess()
Write-Output ("IDENTITY {0} {1}" -f $PID, $me.StartTime.ToUniversalTime().ToString("o"))
''')
    assert result.returncode == 0, result.stdout + result.stderr
    identity = next(line for line in result.stdout.splitlines() if line.startswith("IDENTITY "))
    _, pid, creation = identity.split(" ")
    acquired, released = _journal(tmp_path)
    for record in (acquired, released):
        assert record["schema_version"] == "weather_heavy_workload_lease_journal_v1"
        assert record["pid"] == int(pid)
        assert record["process_creation_utc"] == creation
        assert record["workload"] == "quiet_window_merge"
        assert record["execution_host_profile"] == "capture_colocated_v1"
    assert acquired["event"] == "acquired" and acquired["policy_window"] == "heavy_window"
    assert released["event"] == "released"
    assert released["acquired_at_utc"] == acquired["acquired_at_utc"]
    assert 29 <= released["held_seconds"] <= 120


@pytest.mark.parametrize("blocker", ("logs_is_a_file", "warning_preference_stop"))
def test_journal_fails_open_and_never_throws_into_admission(tmp_path: Path, blocker: str) -> None:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    if blocker == "logs_is_a_file":
        # data\logs cannot be created, so the append must fail.
        (root / "data" / "logs").write_text("not a directory", encoding="ascii")
        prefix = ""
    else:
        (root / "data" / "logs").mkdir()
        (root / JOURNAL).mkdir()  # the journal path is a directory: append fails
        prefix = '$WarningPreference = "Stop"\n'
    result = _run_driver(tmp_path, prefix + r'''
foreach ($event in @("acquired", "busy", "refused_window", "released", "release_failed")) {
    Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event $event -Workload "w"
}
Write-Output "ADMISSION-CONTINUED"
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ADMISSION-CONTINUED" in result.stdout


def test_journal_rotates_by_rename_and_never_deletes_history(tmp_path: Path) -> None:
    logs = tmp_path / "repo" / "data" / "logs"
    logs.mkdir(parents=True)
    old = b'{"event":"acquired","history":"must survive"}\n' * 4
    (logs / "heavy_workload_journal.jsonl").write_bytes(old)
    result = _run_driver(tmp_path, r'''
Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "acquired" -Workload "w" -MaxBytes 64
Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "released" -Workload "w" -MaxBytes 4096
''')
    assert result.returncode == 0, result.stdout + result.stderr
    archives = sorted(logs.glob("heavy_workload_journal.*.jsonl"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == old
    assert [record["event"] for record in _journal(tmp_path)] == ["acquired", "released"]


def test_busy_records_are_rate_limited_but_lifecycle_records_are_not(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    result = _run_driver(tmp_path, r'''
1..5 | ForEach-Object { Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "busy" -Workload "w" }
Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "busy" -Workload "other"
1..2 | ForEach-Object { Write-WeatherHeavyWorkloadLeaseJournal -RepoRoot $Root -Event "acquired" -Workload "w" }
''')
    assert result.returncode == 0, result.stdout + result.stderr
    events = [(record["event"], record["workload"]) for record in _journal(tmp_path)]
    assert events == [("busy", "w"), ("busy", "other"), ("acquired", "w"), ("acquired", "w")]


def test_window_refusal_is_journaled_and_still_refuses(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    # A 13:00 logical clock is outside every capture-colocated window.
    result = _run_driver(tmp_path, r'''
function Get-Date { param([string]$Format) $now = [datetime]"2026-10-05T13:00:00"; if ($Format) { $now.ToString($Format) } else { $now } }
try {
    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $Root -Workload "quiet_window_merge"
    Write-Output "UNEXPECTED-LEASE"
}
catch { Write-Output ("REFUSED " + $_.Exception.Message) }
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNEXPECTED-LEASE" not in result.stdout
    assert "REFUSED heavy workload 'quiet_window_merge' is outside the 00:30-09:00 window" in result.stdout
    (record,) = _journal(tmp_path)
    assert record["event"] == "refused_window"
    assert record["workload"] == "quiet_window_merge"
    assert record["execution_host_profile"] == "capture_colocated_v1"


@pytest.mark.parametrize("dispose_fails", (False, True), ids=("released", "release-failed"))
def test_exit_journals_the_release_outcome_without_changing_it(tmp_path: Path, dispose_fails: bool) -> None:
    (tmp_path / "repo").mkdir()
    stream = (
        '$stream = [PSCustomObject]@{}; $stream | Add-Member -MemberType ScriptMethod -Name Dispose '
        '-Value { throw "twin dispose failure" }'
        if dispose_fails
        else '$stream = [IO.File]::Open((Join-Path $Root "lease.lock"), "OpenOrCreate", "ReadWrite", "Read")'
    )
    result = _run_driver(tmp_path, stream + r'''
$lease = [PSCustomObject]@{
    Path = (Join-Path $Root "lease.lock"); Workload = "quiet_window_merge"
    JournalRepoRoot = $Root; AcquiredAtUtc = [DateTime]::UtcNow.AddSeconds(-5).ToString("o")
    Stream = $stream; Mutex = $null; MutexOwned = $false
    ExecutionHostProfile = "capture_colocated_v1"
}
try { Exit-WeatherHeavyWorkloadLease -Lease $lease; Write-Output "EXIT-OK" }
catch { Write-Output ("EXIT-THREW " + $_.Exception.Message) }
''')
    assert result.returncode == 0, result.stdout + result.stderr
    (record,) = _journal(tmp_path)
    if dispose_fails:
        assert "EXIT-THREW" in result.stdout and "twin dispose failure" in result.stdout
        assert record["event"] == "release_failed"
    else:
        assert "EXIT-OK" in result.stdout
        assert record["event"] == "released"
        assert record["held_seconds"] >= 4
    assert record["workload"] == "quiet_window_merge"


def test_lease_acquisition_and_busy_paths_call_the_journal(tmp_path: Path) -> None:
    # The mutex-owning acquisition path is exercised by the serial lease tests;
    # here the AST proves each admission exit writes exactly its journal event.
    assert WINDOWS_POWERSHELL is not None
    probe = r'''
param([string]$Admission)
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Admission, [ref]$tokens, [ref]$errors)
$result = [ordered]@{}
foreach ($name in @("Enter-WeatherHeavyWorkloadLease", "Exit-WeatherHeavyWorkloadLease")) {
    $function = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name }, $true)
    $calls = @($function.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq "Write-WeatherHeavyWorkloadLeaseJournal" }, $true))
    $result[$name] = @($calls | ForEach-Object { $_.Extent.Text -replace '\s+', ' ' })
}
$result | ConvertTo-Json -Compress
'''
    script = tmp_path / "lease_journal_ast_probe.ps1"
    script.write_text(probe, encoding="utf-8")
    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-Admission", str(ADMISSION)],
        cwd=tmp_path, text=True, capture_output=True, check=True, timeout=60,
    )
    calls = json.loads(result.stdout)
    enter = calls["Enter-WeatherHeavyWorkloadLease"]
    assert sum('-Event "acquired"' in call for call in enter) == 1
    assert sum('-Event "busy"' in call for call in enter) == 2
    assert sum('-Event "refused_window"' in call for call in enter) == 1
    assert len(calls["Exit-WeatherHeavyWorkloadLease"]) == 1
    assert '"released"' in calls["Exit-WeatherHeavyWorkloadLease"][0]
    assert '"release_failed"' in calls["Exit-WeatherHeavyWorkloadLease"][0]
