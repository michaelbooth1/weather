"""Execution twins for the daily-refresh wrapper's window, lease and child-tree substring gates.

`test_daily_refresh_script.py` asserts that `daily_refresh.ps1` *contains* the deadline arithmetic,
the lease calls and the kill-on-close Job calls. These tests run the unmodified wrapper, contract
and Job helper from a temporary repository root under Windows PowerShell:

- `workload_admission.ps1` is replaced by a recording stub (no host-global lease is touched);
- `Get-Date` is shadowed from the caller's scope so the wall clock is synthetic;
- the delegated child is a throwaway `weather.operations.daily_refresh` module run by a fresh
  `--without-pip` venv whose `pythonw.exe` cannot import the real package.

Nothing touches Task Scheduler, `data/`, or the real repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
pytestmark = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="runs the real daily-refresh wrapper and kill-on-close Job under Windows PowerShell",
)

LEASE_STUB = r"""
# TEST STUB: records lease calls instead of touching the host-global lease.
function Write-LeaseEvent([hashtable]$Event) {
    $path = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'lease_events.jsonl'
    Add-Content -LiteralPath $path -Value ($Event | ConvertTo-Json -Compress) -Encoding UTF8
}
function Enter-WeatherHeavyWorkloadLease {
    param([string]$RepoRoot, [string]$Workload, [switch]$AllowStageAWindow)
    Write-LeaseEvent @{ event = 'enter'; workload = $Workload; allow_stage_a = [bool]$AllowStageAWindow }
    $busy = Join-Path $RepoRoot 'lease.busy'
    if (Test-Path -LiteralPath $busy) { return $null }
    return [pscustomobject]@{ Workload = $Workload }
}
function Exit-WeatherHeavyWorkloadLease {
    param($Lease)
    Write-LeaseEvent @{ event = 'exit'; workload = [string]$Lease.Workload }
}
"""

FAKE_CHILD = r'''
import json
import pathlib
import subprocess
import sys
import time

root = pathlib.Path.cwd()
mode = json.loads((root / "child_mode.json").read_text(encoding="utf-8"))
(root / "child.started").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
if mode["kind"] == "exit":
    sys.exit(int(mode["code"]))
survivor = (
    "import pathlib, sys, time; time.sleep(4); "
    "pathlib.Path(sys.argv[1]).write_text('survived')"
)
grandchild = subprocess.Popen([sys.executable, "-c", survivor, str(root / "grandchild.survived")])
(root / "grandchild.started").write_text(str(grandchild.pid), encoding="utf-8")
time.sleep(4)
(root / "child.survived").write_text("survived", encoding="utf-8")
'''

# Shadows Get-Date with a synthetic clock; once `deadline.flag` exists under the repository
# root the clock jumps to the deadline time. Then invokes the real wrapper with `&`.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
$cases = Get-Content -LiteralPath $env:DR_CASES -Raw -Encoding UTF8 | ConvertFrom-Json
function New-FakeTime($parts) {
    $p = @($parts | ForEach-Object { [int]$_ })
    return New-Object DateTime (2026, 9, 19, $p[0], $p[1], 0, [DateTimeKind]::Local)
}
function Get-Date {
    if (Test-Path -LiteralPath $global:DeadlineFlag) { return $global:LaterTime }
    return $global:StartTime
}
$results = foreach ($case in $cases) {
    $global:StartTime = New-FakeTime $case.start
    $global:LaterTime = New-FakeTime $case.later
    $global:DeadlineFlag = Join-Path $case.repo_root 'grandchild.started'
    $wrapper = Join-Path $case.repo_root 'scripts\ops\daily_refresh.ps1'
    $global:LASTEXITCODE = $null
    $output = @(& $wrapper `
        -RepoRoot $case.repo_root `
        -Stage $case.stage `
        -SchedulerTaskName 'WeatherTestDailyRefresh' `
        -EvidenceTaskName 'WeatherEveningEvidenceRefresh' `
        -SchedulerTaskExecutable 'powershell.exe' `
        -ContinueOnError `
        -ProvenanceOnly | ForEach-Object { [string]$_ })
    [pscustomobject]@{ name = $case.name; exit_code = $LASTEXITCODE; output = $output }
}
ConvertTo-Json -InputObject @($results) -Depth 4 -Compress
"""


@pytest.fixture(scope="module")
def isolated_pythonw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    venv_root = tmp_path_factory.mktemp("dr-venv") / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv_root)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    pythonw = venv_root / "Scripts" / "pythonw.exe"
    assert pythonw.is_file()
    return venv_root


def _fake_repo(base: Path, name: str, venv_root: Path, child_mode: dict) -> Path:
    repo = base / name
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    for script in (
        "daily_refresh.ps1",
        "daily_refresh_contract.ps1",
        "training_window_contract.ps1",
        "windows_kill_on_close_job.ps1",
    ):
        shutil.copyfile(OPS / script, ops / script)
    (ops / "workload_admission.ps1").write_text(LEASE_STUB, encoding="utf-8")
    shutil.copytree(venv_root, repo / "venv")
    package = repo / "weather" / "operations"
    package.mkdir(parents=True)
    (repo / "weather" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "daily_refresh.py").write_text(FAKE_CHILD, encoding="utf-8")
    (repo / "child_mode.json").write_text(json.dumps(child_mode), encoding="utf-8")
    return repo


def _case(repo: Path, name: str, stage: str, start: tuple[int, int], later: tuple[int, int] | None = None) -> dict:
    return {
        "name": name,
        "repo_root": str(repo),
        "stage": stage,
        "start": list(start),
        "later": list(later or start),
    }


def _run(tmp_path: Path, cases: list[dict], timeout: int = 120) -> dict[str, dict]:
    spec = tmp_path / "cases.json"
    spec.write_text(json.dumps(cases), encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["DR_CASES"] = str(spec)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", HARNESS],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    return {row["name"]: row for row in rows}


def _lease_events(repo: Path) -> list[dict]:
    path = repo / "lease_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def test_exec_daily_refresh_refuses_outside_its_window_before_lease_or_child(
    tmp_path: Path, isolated_pythonw: Path
) -> None:
    """Twin of test_daily_refresh_is_serialized_and_cannot_cross_the_graded_window (admission half)."""
    exit_mode = {"kind": "exit", "code": 3}
    repos = {
        name: _fake_repo(tmp_path, name, isolated_pythonw, exit_mode)
        for name in (
            "evidence_at_deadline",
            "evidence_before_0030",
            "settlement_at_deadline",
            "lease_busy",
            "settlement_admitted",
        )
    }
    (repos["lease_busy"] / "lease.busy").write_text("busy", encoding="utf-8")
    outcome = _run(
        tmp_path,
        [
            _case(repos["evidence_at_deadline"], "evidence_at_deadline", "evidence", (9, 0)),
            _case(repos["evidence_before_0030"], "evidence_before_0030", "evidence", (0, 29)),
            _case(repos["settlement_at_deadline"], "settlement_at_deadline", "settlement", (11, 55)),
            _case(repos["lease_busy"], "lease_busy", "evidence", (2, 0)),
            _case(repos["settlement_admitted"], "settlement_admitted", "settlement", (11, 54)),
        ],
    )

    for name, stage, label in (
        ("evidence_at_deadline", "evidence", "00:30-09:00"),
        ("evidence_before_0030", "evidence", "00:30-09:00"),
        ("settlement_at_deadline", "settlement", "00:30-11:55"),
    ):
        row = outcome[name]
        assert row["exit_code"] == 75, row
        assert row["output"] == [f"REFUSED: daily refresh stage '{stage}' cannot run outside {label}"]
        assert _lease_events(repos[name]) == [], name
        assert not (repos[name] / "child.started").exists(), name

    busy = outcome["lease_busy"]
    assert busy["exit_code"] == 76
    assert busy["output"] == ["REFUSED: another heavyweight host workload owns data/logs/heavy_workload.lock"]
    assert _lease_events(repos["lease_busy"]) == [
        {"event": "enter", "workload": "daily_refresh_evidence", "allow_stage_a": False}
    ]
    assert not (repos["lease_busy"] / "child.started").exists()

    # Inside the window the child runs under the lease, its exit code propagates, and the
    # lease is released; only the settlement stage may use the Stage-A window.
    admitted = outcome["settlement_admitted"]
    assert admitted["exit_code"] == 3
    assert _lease_events(repos["settlement_admitted"]) == [
        {"event": "enter", "workload": "daily_refresh_settlement", "allow_stage_a": True},
        {"event": "exit", "workload": "daily_refresh_settlement"},
    ]
    child_argv = json.loads((repos["settlement_admitted"] / "child.started").read_text(encoding="utf-8"))
    assert child_argv[:2] == ["run", "--fail-on-variant-evidence-alert"]
    assert "--scheduler-task-name" in child_argv


def test_exec_daily_refresh_deadline_tears_down_the_whole_child_tree(
    tmp_path: Path, isolated_pythonw: Path
) -> None:
    """Twin of test_daily_refresh_child_tree_is_owned_by_a_kill_on_close_job and the teardown half
    of test_daily_refresh_is_serialized_and_cannot_cross_the_graded_window (EF §8d)."""
    repo = _fake_repo(tmp_path, "evidence_deadline", isolated_pythonw, {"kind": "tree"})
    started = time.monotonic()
    outcome = _run(tmp_path, [_case(repo, "evidence_deadline", "evidence", (8, 59), (9, 0))])
    row = outcome["evidence_deadline"]

    assert row["exit_code"] == 75, row
    assert row["output"] == ["STOPPED: daily refresh stage 'evidence' reached its 09:00 teardown deadline"]
    assert (repo / "grandchild.started").exists()
    assert _lease_events(repo) == [
        {"event": "enter", "workload": "daily_refresh_evidence", "allow_stage_a": False},
        {"event": "exit", "workload": "daily_refresh_evidence"},
    ]
    # Both the child and the grandchild would write their marker 4 s after starting; give them
    # well past that and prove neither survived the Job close.
    time.sleep(max(0.0, 6.0 - (time.monotonic() - started)))
    assert not (repo / "child.survived").exists()
    assert not (repo / "grandchild.survived").exists()
