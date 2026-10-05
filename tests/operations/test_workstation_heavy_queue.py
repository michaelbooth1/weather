"""FIFO queue for workstation_heavy.ps1 and the PowerShell side of the focused-run exemption.

Guards: HOST_LOAD_POLICY "Workstation focused runs, FIFO queue and xdist" (owner decision 2026-10-04,
P3) — -Queue admits waiters strictly in ticket order, reaps dead tickets, exits 75 on timeout and
logs every wait; without -Queue a busy lease is still refused at once; on the dedicated capture-host
identity nothing changes (no queue state, no exemption, same windows).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass")
QUEUE_TIMEOUT_EXIT_CODE = 75
pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or shutil.which("powershell") is None,
        reason="Windows PowerShell wrapper",
    ),
]


def _install(repo_root: Path) -> Path:
    """Copy the wrapper closure with a fixture-local mutex and state root."""

    ops = repo_root / "scripts" / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    for name in ("workstation_heavy.ps1", "workload_admission.ps1", "windows_kill_on_close_job.ps1"):
        shutil.copyfile(REPO_ROOT / "scripts" / "ops" / name, ops / name)
    hooks = repo_root / ".codex" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / ".codex/hooks/pre_tool_use_host_load.py", hooks / "pre_tool_use_host_load.py")
    admission = ops / "workload_admission.ps1"
    text = admission.read_text(encoding="utf-8-sig")
    assert text.count("Global\\WeatherProjectHeavyWorkloadV1") >= 1
    text = text.replace("Global\\WeatherProjectHeavyWorkloadV1", "Local\\WeatherQueueFixture-" + uuid.uuid4().hex)
    text += (
        "\n# TEST-ONLY HOST-GLOBAL STATE OVERRIDE\n"
        "function Get-WeatherHeavyWorkloadPoisonPath {\n"
        "    param([switch]$CreateIfMissing)\n"
        "    Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.test-heavy-workload.poison'\n"
        "}\n"
        "function Get-WeatherActiveWorkstationHeavyProcess { @() }\n"
    )
    admission.write_text(text, encoding="utf-8")
    return ops


def _write_assignment(repo_root: Path, *, capture_identity: bool) -> None:
    config = repo_root / "config"
    config.mkdir(parents=True, exist_ok=True)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$hostId = Get-WeatherExecutionHostId
if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') {
    $record = [ordered]@{
        active_portable_execution_host_id = $null
        active_portable_execution_principal_id = $null
        assignment_status = 'UNASSIGNED'
        dedicated_capture_execution_host_id = $hostId
        reassignment_requires_new_production_tip = $true
        schema_version = 'international_live_execution_host_assignment_v0.1'
    }
}
else {
    $record = [ordered]@{
        active_portable_execution_host_id = $hostId
        active_portable_execution_principal_id = Get-WeatherExecutionPrincipalId
        assignment_status = 'ASSIGNED'
        dedicated_capture_execution_host_id = ('f' * 64)
        reassignment_requires_new_production_tip = $true
        schema_version = 'international_live_execution_host_assignment_v0.1'
    }
}
[IO.File]::WriteAllText($env:WEATHER_ASSIGNMENT_PATH, ($record | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new($false))
"""
    env = {
        **os.environ,
        "WEATHER_LEASE_SCRIPT": str(REPO_ROOT / "scripts/ops/workload_admission.ps1"),
        "WEATHER_ASSIGNMENT_PATH": str(config / "international_live_execution_host.json"),
        "WEATHER_CAPTURE_IDENTITY": "1" if capture_identity else "0",
    }
    result = subprocess.run([*POWERSHELL, "-Command", script], capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def workstation(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _install(repo)
    _write_assignment(repo, capture_identity=False)
    return repo


@pytest.fixture
def capture_host(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _install(repo)
    _write_assignment(repo, capture_identity=True)
    return repo


def _child_test(repo: Path, name: str, record: Path) -> Path:
    path = repo / f"test_child_{name}.py"
    path.write_text(
        "import time\nfrom pathlib import Path\n\n"
        "def test_child():\n"
        "    time.sleep(0.3)\n"
        f"    with Path({str(record)!r}).open('a', encoding='utf-8') as handle:\n"
        f"        handle.write({name!r} + '\\n')\n",
        encoding="utf-8",
    )
    return path


def _wrapper_argv(repo: Path, test_file: Path, *extra: str) -> list[str]:
    arguments = ["-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider", "--basetemp", str(repo / "bt" / test_file.stem)]
    encoded = base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")
    return [
        *POWERSHELL,
        "-File",
        str(repo / "scripts/ops/workstation_heavy.ps1"),
        "-Kind",
        "pytest",
        "-PythonPath",
        sys.executable,
        "-ArgumentsBase64",
        encoded,
        "-RepoRoot",
        str(repo),
        *extra,
    ]


def _start_holder(repo: Path, release: Path) -> subprocess.Popen[str]:
    script = f"""
$ErrorActionPreference = 'Stop'
. '{repo / "scripts/ops/workload_admission.ps1"}'
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{repo}' `
    -Workload 'WorkstationOffline-pytest-holder' -ExecutionHostProfile 'workstation_offline_v1'
if ($null -eq $lease) {{ Write-Output 'BUSY'; exit 3 }}
Write-Output 'ACQUIRED'
[Console]::Out.Flush()
$deadline = [DateTime]::UtcNow.AddSeconds(120)
while (-not (Test-Path -LiteralPath '{release}') -and [DateTime]::UtcNow -lt $deadline) {{
    Start-Sleep -Milliseconds 100
}}
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
"""
    holder = subprocess.Popen([*POWERSHELL, "-Command", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert holder.stdout is not None
    line = holder.stdout.readline().strip()
    assert line == "ACQUIRED", (line, holder.stderr.read() if holder.poll() is not None else "")
    return holder


def _events(repo: Path) -> list[dict]:
    path = repo / "data" / "logs" / "heavy_workload_queue.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _wait_for(predicate, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition not reached before the deadline")


def _queue_tickets(repo: Path) -> list[str]:
    root = repo / "heavy_workload_queue_v1"
    return sorted(path.name for path in root.glob("ticket-*.json")) if root.exists() else []


def test_three_waiters_are_admitted_strictly_in_ticket_order(workstation: Path) -> None:
    repo = workstation
    order = repo / "order.txt"
    release = repo / "release.flag"
    holder = _start_holder(repo, release)
    waiters: dict[str, subprocess.Popen[str]] = {}
    try:
        # The earliest waiter polls slowest: only strict ticket order makes A win the free lease.
        for name, poll in (("A", "1500"), ("B", "700"), ("C", "100")):
            waiters[name] = subprocess.Popen(
                _wrapper_argv(repo, _child_test(repo, name, order), "-Queue", "-QueuePollMilliseconds", poll),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid = waiters[name].pid
            _wait_for(lambda: any(e["event"] == "enqueue" and e["pid"] == pid for e in _events(repo)))
        assert _queue_tickets(repo) == [f"ticket-{n:012d}.json" for n in (1, 2, 3)]
        release.write_text("go", encoding="utf-8")
        results = {name: process.communicate(timeout=180) for name, process in waiters.items()}
    finally:
        release.write_text("go", encoding="utf-8")
        for process in waiters.values():
            if process.poll() is None:
                process.kill()
        holder.wait(timeout=30)
    for name, process in waiters.items():
        assert process.returncode == 0, (name, results[name][1])
        assert "1 passed" in results[name][0]
    assert order.read_text(encoding="utf-8").split() == ["A", "B", "C"]

    events = _events(repo)
    ticket_of = {name: next(e["ticket"] for e in events if e["event"] == "enqueue" and e["pid"] == p.pid) for name, p in waiters.items()}
    assert ticket_of == {"A": 1, "B": 2, "C": 3}
    enqueues = [e for e in events if e["event"] == "enqueue"]
    assert [(e["ticket"], e["position"]) for e in enqueues] == [(1, 1), (2, 2), (3, 3)]
    for event in enqueues:
        assert event["holder"]["workload"] == "WorkstationOffline-pytest-holder"
        assert event["holder"]["execution_host_profile"] == "workstation_offline_v1"
        assert event["timeout_seconds"] == 14400
        assert event["schema_version"] == "weather_heavy_workload_queue_event_v1"
    starts = [e for e in events if e["event"] == "start"]
    assert [(e["ticket"], e["position"]) for e in starts] == [(1, 1), (2, 1), (3, 1)]
    finishes = [e for e in events if e["event"] == "finish"]
    assert sorted((e["ticket"], e["exit_code"]) for e in finishes) == [(1, 0), (2, 0), (3, 0)]
    c_positions = [e["position"] for e in events if e["ticket"] == 3 and e["event"] in {"enqueue", "wait", "start"}]
    assert c_positions[0] == 3 and c_positions[-1] == 1
    assert 2 in c_positions and c_positions.index(2) < len(c_positions) - 1
    assert c_positions == sorted(c_positions, reverse=True)
    for ticket in (1, 2, 3):
        waited = [e["waited_seconds"] for e in events if e["ticket"] == ticket and e["event"] != "finish"]
        assert waited == sorted(waited)
    assert "heavy-workload queue: enqueue ticket 3 position 3" in results["C"][0]
    assert _queue_tickets(repo) == []


def test_stale_tickets_from_dead_or_reused_pids_are_reaped(workstation: Path) -> None:
    repo = workstation
    queue = repo / "heavy_workload_queue_v1"
    queue.mkdir()
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)
    dead_pid = int(dead.stdout.strip())

    def ticket(number: int, pid: int, start: str) -> None:
        (queue / f"ticket-{number:012d}.json").write_text(
            json.dumps(
                {
                    "schema_version": "weather_heavy_workload_queue_ticket_v1",
                    "ticket": number,
                    "pid": pid,
                    "owner_process_start_utc": start,
                    "enqueued_at_utc": "2026-10-04T00:00:00.0000000Z",
                    "workload": "WorkstationOffline-pytest-stale",
                    "repo_root": str(repo),
                }
            ),
            encoding="utf-8",
        )

    ticket(1, dead_pid, "2026-10-04T00:00:00.0000000Z")
    ticket(2, os.getpid(), "2000-01-01T00:00:00.0000000Z")
    unreadable = queue / f"ticket-{3:012d}.json"
    unreadable.write_text("{partial", encoding="utf-8")
    old = time.time() - 120
    os.utime(unreadable, (old, old))
    order = repo / "order.txt"
    result = subprocess.run(
        _wrapper_argv(repo, _child_test(repo, "solo", order), "-Queue", "-QueuePollMilliseconds", "100"),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert order.read_text(encoding="utf-8").split() == ["solo"]
    events = _events(repo)
    enqueue = next(e for e in events if e["event"] == "enqueue")
    assert (enqueue["ticket"], enqueue["position"]) == (4, 4)
    reaped = sorted((e["reaped_ticket"], e["reason"]) for e in events if e["event"] == "reaped")
    assert reaped == [(1, "owner_exited"), (2, "owner_pid_reused"), (3, "unreadable")]
    assert [(e["ticket"], e["position"]) for e in events if e["event"] == "start"] == [(4, 1)]
    assert _queue_tickets(repo) == []


def test_a_fresh_unreadable_ticket_is_not_reaped_within_its_grace(workstation: Path) -> None:
    repo = workstation
    queue = repo / "heavy_workload_queue_v1"
    queue.mkdir()
    (queue / f"ticket-{1:012d}.json").write_text("", encoding="utf-8")
    sentinel = repo / "never.txt"
    result = subprocess.run(
        _wrapper_argv(
            repo, _child_test(repo, "late", sentinel), "-Queue", "-QueueTimeoutSeconds", "2", "-QueuePollMilliseconds", "200"
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == QUEUE_TIMEOUT_EXIT_CODE, result.stderr
    assert not sentinel.exists()
    assert _queue_tickets(repo) == [f"ticket-{1:012d}.json"]
    assert [e["event"] for e in _events(repo)][-1] == "give_up"


def test_queue_timeout_exits_75_without_starting_the_child(workstation: Path) -> None:
    repo = workstation
    release = repo / "release.flag"
    sentinel = repo / "never.txt"
    holder = _start_holder(repo, release)
    try:
        started = time.monotonic()
        result = subprocess.run(
            _wrapper_argv(
                repo,
                _child_test(repo, "timeout", sentinel),
                "-Queue",
                "-QueueTimeoutSeconds",
                "2",
                "-QueuePollMilliseconds",
                "200",
                "-QueueReportSeconds",
                "1",
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        elapsed = time.monotonic() - started
    finally:
        release.write_text("go", encoding="utf-8")
        holder.wait(timeout=30)
    assert result.returncode == QUEUE_TIMEOUT_EXIT_CODE
    assert "queue wait timed out after 2 s; nothing was started" in result.stderr
    assert elapsed >= 2
    assert not sentinel.exists()
    events = _events(repo)
    assert [e["event"] for e in events][0] == "enqueue"
    give_up = [e for e in events if e["event"] == "give_up"]
    assert len(give_up) == 1
    assert give_up[0]["ticket"] == 1 and give_up[0]["position"] == 1
    assert give_up[0]["waited_seconds"] >= 2
    assert give_up[0]["timeout_seconds"] == 2
    assert give_up[0]["holder"]["workload"] == "WorkstationOffline-pytest-holder"
    assert any(e["event"] == "wait" for e in events)
    assert not any(e["event"] in {"start", "finish"} for e in events)
    assert _queue_tickets(repo) == []


def test_without_queue_a_busy_lease_is_still_refused_at_once(workstation: Path) -> None:
    repo = workstation
    release = repo / "release.flag"
    sentinel = repo / "never.txt"
    holder = _start_holder(repo, release)
    try:
        result = subprocess.run(
            _wrapper_argv(repo, _child_test(repo, "direct", sentinel)),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    finally:
        release.write_text("go", encoding="utf-8")
        holder.wait(timeout=30)
    assert result.returncode == 1
    assert "blocked by another heavy or portable live lease" in result.stderr
    assert "heavy-workload queue" not in result.stdout
    assert not sentinel.exists()
    assert not (repo / "heavy_workload_queue_v1").exists()
    assert _events(repo) == []


def _admission(repo: Path, body: str) -> subprocess.CompletedProcess[str]:
    script = f"$ErrorActionPreference = 'Stop'\n. '{repo / 'scripts/ops/workload_admission.ps1'}'\n" + body
    return subprocess.run([*POWERSHELL, "-Command", script], capture_output=True, text=True, check=False, timeout=120)


def _exemption(repo: Path, arguments: list[str]) -> dict:
    encoded = base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")
    result = _admission(
        repo,
        "$arguments = @([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("
        f"'{encoded}')) | ConvertFrom-Json)\n"
        f"Test-WeatherWorkstationFocusedPytestExemption -RepoRoot '{repo}' -PythonPath '{sys.executable}' "
        f"-Arguments $arguments -WorkingDirectory '{repo}' | ConvertTo-Json -Compress\n",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_workload_admission_recognises_the_focused_exemption_on_the_workstation(workstation: Path) -> None:
    repo = workstation
    plain = repo / "tests" / "test_plain.py"
    plain.parent.mkdir()
    plain.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    serial = repo / "tests" / "test_ps.py"
    serial.write_text("import subprocess\nSHELL = 'powershell'\n", encoding="utf-8")
    many = []
    for index in range(26):
        path = repo / "tests" / f"test_n{index:02d}.py"
        path.write_text("def test_ok():\n    pass\n", encoding="utf-8")
        many.append(str(path))
    assert _exemption(repo, [str(plain), "-q", "--basetemp", "bt"]) == {
        "Exempt": True,
        "Reason": "focused run of 1 non-serial test file(s)",
    }
    assert _exemption(repo, [str(plain), str(serial), "--basetemp", "bt"]) == {
        "Exempt": False,
        "Reason": "test_ps.py starts PowerShell (serial until the marker exists)",
    }
    assert _exemption(repo, [*many, "--basetemp", "bt"]) == {
        "Exempt": False,
        "Reason": "26 test files exceed the 25-file focused-run limit",
    }
    assert _exemption(repo, [*many[:25], "--basetemp", "bt"])["Exempt"] is True
    assert _exemption(repo, ["tests", "--basetemp", "bt"]) == {
        "Exempt": False,
        "Reason": "target 'tests' is not a test file; directories and globs cannot be bounded",
    }
    (repo / ".test-heavy-workload.poison").write_text(
        json.dumps({"execution_host_profile": "portable_execution_v1"}), encoding="utf-8"
    )
    assert _exemption(repo, [str(plain), "--basetemp", "bt"]) == {
        "Exempt": False,
        "Reason": "a portable live stage holds the host-global mutex",
    }


def test_capture_host_identity_is_unchanged(capture_host: Path) -> None:
    repo = capture_host
    plain = repo / "test_plain.py"
    plain.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    sentinel = repo / "never.txt"

    # No focused-run exemption, before any file is classified.
    assert _exemption(repo, [str(plain), "--basetemp", "bt"]) == {
        "Exempt": False,
        "Reason": (
            "the dedicated capture host has no focused-run exemption; use the bounded suite "
            "inside the 00:30-09:00 window"
        ),
    }

    # The workstation wrapper is refused with and without -Queue, and no queue state appears.
    for extra in ((), ("-Queue",)):
        result = subprocess.run(
            _wrapper_argv(repo, _child_test(repo, "cap", sentinel), *extra),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 1, extra
        assert "workstation-offline admission is forbidden on the dedicated capture host" in result.stderr
    assert not sentinel.exists()
    assert not (repo / "heavy_workload_queue_v1").exists()
    assert not (repo / ".test-heavy-workload.poison").exists()
    assert _events(repo) == []

    # The capture timetable is the same: 00:30-09:00 agent window, explicit Stage-A only, nothing else.
    windows = _admission(
        repo,
        "$day = [datetime]'2026-10-04'\n"
        "foreach ($m in @(29, 30, 539, 540, 570, 714, 715, 720, 1080, 1439)) {\n"
        "  $plain = Get-WeatherHeavyWorkloadPolicyWindow -Now $day.AddMinutes($m)\n"
        "  $stage = Get-WeatherHeavyWorkloadPolicyWindow -Now $day.AddMinutes($m) -AllowStageAWindow\n"
        "  Write-Output ('{0}={1}/{2}' -f $m, $plain, $stage)\n"
        "}\n",
    )
    assert windows.returncode == 0, windows.stderr
    assert windows.stdout.split() == [
        "29=/",
        "30=agent_heavy/agent_heavy",
        "539=agent_heavy/agent_heavy",
        "540=/",
        "570=/stage_a",
        "714=/stage_a",
        "715=/",
        "720=/",
        "1080=/",
        "1439=/",
    ]

    # The queue entry point refuses the capture identity before writing a ticket.
    queued = _admission(
        repo,
        f"Enter-WeatherHeavyWorkloadLeaseQueued -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-1'\n",
    )
    assert queued.returncode != 0
    assert "forbidden on the dedicated capture host" in queued.stderr
    assert not (repo / "heavy_workload_queue_v1").exists()
