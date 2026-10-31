"""Concurrent workstation heavy slots for workstation_heavy.ps1 and workload_admission.ps1.

Guards: HOST_LOAD_POLICY "Workstation focused runs, FIFO queue and xdist" heavy-slot rules (master
ruling 2026-10-24, lane W2) - at most -SlotCount (default 3) concurrent workstation_offline_v1 jobs;
each admission needs available physical memory >= the floor (default 6 GB) and commit charge <= the
ceiling (default 90 %); an older wrapper holding the legacy lease occupies slot 1 and is counted; a
portable live stage excludes every slot in both orders; a dead slot holder is reclaimed only by the
legacy stale-ACTIVE rules; capture-colocated admission keeps the single serial lease. PG-NEST-1: the
exclusive barrier owner is recorded (pid plus start time) and logged by exclusive waiters; only a live
descendant of that recorded holder is admitted at once without a ticket, and a dead or reused holder pid
grants nothing, also when the owner cannot delete its record at release (it is marked released).

Every process here uses a fixture-local mutex name and state path, never the host's real lease.
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
LEGACY_MUTEX = "Global\\WeatherProjectHeavyWorkloadV1"
QUEUE_TIMEOUT_EXIT_CODE = 75
GIB = 1024**3
pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or shutil.which("powershell") is None,
        reason="Windows PowerShell wrapper",
    ),
]

TEST_OVERRIDES = r"""
# TEST-ONLY HOST-GLOBAL STATE, MEMORY, RESIDUAL-SCAN AND WINDOW OVERRIDES
function Get-WeatherHeavyWorkloadPoisonPath {
    param([switch]$CreateIfMissing)
    Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.test-heavy-workload.poison'
}
function Get-WeatherActiveWorkstationHeavyProcess {
    param($ProcessSnapshot, $TaskObservation, $DecisionLog)
    if ($env:WEATHER_TEST_RESIDUAL_PID) {
        [PSCustomObject]@{ ProcessId = [int]$env:WEATHER_TEST_RESIDUAL_PID; Name = 'python.exe' }
    }
}
function Get-WeatherWorkstationMemoryReading {
    $available = if ($env:WEATHER_TEST_AVAILABLE_BYTES) { [long]$env:WEATHER_TEST_AVAILABLE_BYTES } else { 16GB }
    $commit = if ($env:WEATHER_TEST_COMMIT_PERCENT) { [double]$env:WEATHER_TEST_COMMIT_PERCENT } else { 40.0 }
    [PSCustomObject]@{ TotalPhysicalBytes = 32GB; AvailablePhysicalBytes = $available; CommitPercent = $commit }
}
function Get-WeatherWorkstationLogicalProcessorCount {
    if ($env:WEATHER_TEST_LOGICAL_CPUS) { [int]$env:WEATHER_TEST_LOGICAL_CPUS } else { 12 }
}
if ($env:WEATHER_TEST_CAPTURE_WINDOW_OPEN -eq '1') {
    function Get-WeatherHeavyWorkloadPolicyWindow { param($Now, [switch]$AllowStageAWindow, $OwnerApprovedException) 'agent_heavy' }
}
"""


WRAPPER_CLOSURE = ("workstation_heavy.ps1", "workload_admission.ps1", "windows_kill_on_close_job.ps1")
# The last commit before workstation slots: what older wrapper copies in other worktrees run.
PRE_SLOT_COMMIT = "57cfdfe726eb83d074059a3ddefa4df7d13b936c"


def _install(
    repo: Path,
    *,
    mutex: str | None = None,
    state_path: Path | None = None,
    sources: dict[str, str] | None = None,
) -> str:
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    for name in WRAPPER_CLOSURE:
        text = sources[name] if sources else (REPO_ROOT / "scripts" / "ops" / name).read_text(encoding="utf-8-sig")
        (ops / name).write_text(text, encoding="utf-8")
    admission = ops / "workload_admission.ps1"
    text = admission.read_text(encoding="utf-8-sig")
    assert text.count(LEGACY_MUTEX) >= 1
    mutex = mutex or "Local\\WeatherSlotFixture-" + uuid.uuid4().hex
    overrides = TEST_OVERRIDES
    if state_path is not None:
        # Several fixture checkouts share one host-global state file, as worktrees do.
        overrides += (
            "function Get-WeatherHeavyWorkloadPoisonPath {\n"
            f"    param([switch]$CreateIfMissing)\n    '{state_path}'\n}}\n"
        )
    admission.write_text(text.replace(LEGACY_MUTEX, mutex) + overrides, encoding="utf-8")
    return mutex


def _pre_slot_sources() -> dict[str, str]:
    sources = {}
    for name in WRAPPER_CLOSURE:
        shown = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{PRE_SLOT_COMMIT}:scripts/ops/{name}"],
            capture_output=True, check=False,
        )
        if shown.returncode != 0:
            pytest.skip("the pre-slot commit is not in this clone's history")
        sources[name] = shown.stdout.decode("utf-8-sig")
    assert "Enter-WeatherWorkstationHeavySlotLease" not in sources["workload_admission.ps1"]
    return sources


def _write_assignment(repo: Path, *, capture_identity: bool) -> None:
    config = repo / "config"
    config.mkdir(parents=True, exist_ok=True)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$hostId = Get-WeatherExecutionHostId
$record = [ordered]@{
    active_portable_execution_host_id = $(if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') { $null } else { $hostId })
    active_portable_execution_principal_id = $(if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') { $null } else { Get-WeatherExecutionPrincipalId })
    assignment_status = $(if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') { 'UNASSIGNED' } else { 'ASSIGNED' })
    dedicated_capture_execution_host_id = $(if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') { $hostId } else { 'f' * 64 })
    reassignment_requires_new_production_tip = $true
    schema_version = 'international_live_execution_host_assignment_v0.1'
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


def _env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("WEATHER_TEST_")}
    env.pop("WEATHER_WORKSTATION_WRAPPER_SLOT", None)
    env.update(overrides)
    return env


def _admission(repo: Path, body: str, **env: str) -> subprocess.CompletedProcess[str]:
    script = f"$ErrorActionPreference = 'Stop'\n. '{repo / 'scripts/ops/workload_admission.ps1'}'\n" + body
    return subprocess.run(
        [*POWERSHELL, "-Command", script], capture_output=True, text=True, check=False, timeout=180, env=_env(**env)
    )


SLOT_ENTER = "Enter-WeatherWorkstationHeavySlotLease -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-{name}'"
LEGACY_ENTER = (
    "Enter-WeatherHeavyWorkloadLease -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-{name}' "
    "-ExecutionHostProfile 'workstation_offline_v1'"
)
PORTABLE_ENTER = (
    "Enter-WeatherHeavyWorkloadLease -RepoRoot '{repo}' -Workload 'InternationalLive-stage0-{name}-0123456789ab' "
    "-ExecutionHostProfile 'portable_execution_v1' -ExpectedExecutionHostId (Get-WeatherExecutionHostId)"
)
CAPTURE_ENTER = "Enter-WeatherHeavyWorkloadLease -RepoRoot '{repo}' -Workload '{name}'"
EXCLUSIVE_ENTER = (
    "Enter-WeatherWorkstationHeavyExclusiveLease -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-pregate-{name}' "
    "-PollMilliseconds 100 -ReportSeconds 1"
)


class Holder:
    """A PowerShell process that holds one lease until its release file appears."""

    def __init__(self, repo: Path, enter: str, name: str, **env: str) -> None:
        self.release = repo / f"release-{name}.flag"
        script = f"""
$ErrorActionPreference = 'Stop'
. '{repo / "scripts/ops/workload_admission.ps1"}'
$lease = {enter.format(repo=repo, name=name)}
if ($null -eq $lease) {{ Write-Output 'BUSY'; exit 3 }}
Write-Output ('ACQUIRED {{0}}' -f [int]$lease.WorkstationSlotId)
[Console]::Out.Flush()
$deadline = [DateTime]::UtcNow.AddSeconds(150)
while (-not (Test-Path -LiteralPath '{self.release}') -and [DateTime]::UtcNow -lt $deadline) {{
    Start-Sleep -Milliseconds 50
}}
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
"""
        self.process = subprocess.Popen(
            [*POWERSHELL, "-Command", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(**env)
        )
        assert self.process.stdout is not None
        line = self.process.stdout.readline().strip()
        if not line.startswith("ACQUIRED "):
            self.process.kill()
            raise AssertionError((line, self.process.stderr.read() if self.process.stderr else ""))
        self.slot = int(line.split()[1])

    def stop(self) -> None:
        self.release.write_text("go", encoding="utf-8")
        try:
            assert self.process.wait(timeout=60) == 0, self.process.stderr.read() if self.process.stderr else ""
        finally:
            if self.process.poll() is None:
                self.process.kill()


@pytest.fixture
def holders():
    started: list[Holder] = []
    yield started
    for holder in started:
        holder.release.write_text("go", encoding="utf-8")
    for holder in started:
        try:
            holder.process.wait(timeout=60)
        finally:
            if holder.process.poll() is None:
                holder.process.kill()


def _child_test(repo: Path, name: str, record: Path) -> Path:
    path = repo / f"test_child_{name}.py"
    path.write_text(
        "from pathlib import Path\n\n"
        "def test_child():\n"
        f"    with Path({str(record)!r}).open('a', encoding='utf-8') as handle:\n"
        f"        handle.write({name!r} + '\\n')\n",
        encoding="utf-8",
    )
    return path


def _wrapper_argv(repo: Path, test_file: Path, *extra: str) -> list[str]:
    arguments = ["-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider", "--basetemp", str(repo / "bt" / test_file.stem)]
    encoded = base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")
    return [
        *POWERSHELL, "-File", str(repo / "scripts/ops/workstation_heavy.ps1"), "-Kind", "pytest",
        "-PythonPath", sys.executable, "-ArgumentsBase64", encoded, "-RepoRoot", str(repo), *extra,
    ]


def _run_wrapper(repo: Path, name: str, *extra: str, **env: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    sentinel = repo / f"ran-{name}.txt"
    result = subprocess.run(
        _wrapper_argv(repo, _child_test(repo, name, sentinel), *extra),
        capture_output=True, text=True, check=False, timeout=240, env=_env(**env),
    )
    return result, sentinel


def _events(repo: Path) -> list[dict]:
    path = repo / "data" / "logs" / "heavy_workload_queue.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _recovery_outcomes(repo: Path) -> list[tuple[str, int | None]]:
    path = repo / "data" / "logs" / "heavy_workload_recovery.jsonl"
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [(record["outcome"], record.get("workstation_slot_id")) for record in records]


def _wait_for(predicate, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition not reached before the deadline")


def _slot_marker(repo: Path, slot: int) -> Path:
    return repo / (".test-heavy-workload.poison" if slot == 1 else f".test-heavy-workload.slot{slot}.poison")


def _write_marker(repo: Path, slot: int, *, pid: int, start: str, state: str = "ACTIVE", boot: int = 1) -> Path:
    path = _slot_marker(repo, slot)
    path.write_text(
        json.dumps(
            {
                "boot_session_id": boot,
                "execution_host_profile": "workstation_offline_v1",
                "owner_process_start_utc": start,
                "pid": pid,
                "schema_version": "weather_heavy_workload_state_v1",
                "state": state,
                "state_changed_at_utc": "2026-10-24T00:00:01.0000000Z",
                "workload": f"WorkstationOffline-pytest-dead-slot{slot}",
            }
        ),
        encoding="utf-8",
    )
    return path


def _dead_pid() -> int:
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)
    return int(dead.stdout.strip())


def test_three_slots_admit_three_jobs_and_refuse_or_queue_the_fourth(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    for name in ("a", "b", "c"):
        holders.append(Holder(repo, SLOT_ENTER, name))
    # Fresh extra slots first, the legacy slot last, so an older wrapper keeps its chance.
    assert [holder.slot for holder in holders] == [2, 3, 1]
    for slot in (1, 2, 3):
        assert _slot_marker(repo, slot).exists()
    owner = json.loads((repo / "data/logs/heavy_workload.slot2.lock").read_text(encoding="utf-8"))
    assert owner["workstation_slot_id"] == 2
    assert owner["host_global_mutex"].endswith(".Slot2")

    direct, sentinel = _run_wrapper(repo, "direct")
    assert direct.returncode == 1
    assert "blocked by another heavy or portable live lease (slots_full)" in direct.stderr
    assert not sentinel.exists()

    timed_out, sentinel = _run_wrapper(repo, "late", "-Queue", "-QueueTimeoutSeconds", "2", "-QueuePollMilliseconds", "200")
    assert timed_out.returncode == QUEUE_TIMEOUT_EXIT_CODE, timed_out.stderr
    assert not sentinel.exists()
    give_up = [e for e in _events(repo) if e["event"] == "give_up"]
    assert len(give_up) == 1 and give_up[0]["slot_refusal"] == "slots_full"
    assert sorted(h["slot_id"] for h in give_up[0]["slot_holders"]) == [1, 2, 3]

    # A queued fourth job starts in the slot that frees, and the log records it.
    sentinel = repo / "ran-queued.txt"
    queued = subprocess.Popen(
        _wrapper_argv(
            repo, _child_test(repo, "queued", sentinel), "-Queue", "-QueuePollMilliseconds", "100",
            "-QueueReportSeconds", "1",
        ),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(),
    )
    try:
        _wait_for(lambda: any(e["event"] == "wait" and e["pid"] == queued.pid for e in _events(repo)))
        assert queued.poll() is None and not sentinel.exists()
        holders[1].stop()  # frees slot 3
        out, err = queued.communicate(timeout=180)
    finally:
        if queued.poll() is None:
            queued.kill()
    assert queued.returncode == 0, err
    assert "workstation-heavy: admitted to slot 3 of 3" in out
    assert sentinel.read_text(encoding="utf-8").split() == ["queued"]
    mine = [e for e in _events(repo) if e["pid"] == queued.pid]
    start = next(e for e in mine if e["event"] == "start")
    finish = next(e for e in mine if e["event"] == "finish")
    assert (start["slot_id"], start["slot_count"], start["busy_slots_at_admission"]) == (3, 3, [1, 2])
    assert (finish["slot_id"], finish["exit_code"]) == (3, 0)
    assert any(e["event"] == "wait" and e["slot_refusal"] == "slots_full" for e in mine)


def test_slot_count_is_a_parameter_and_one_slot_is_the_serial_lease(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    holders.append(Holder(repo, SLOT_ENTER, "only"))
    assert holders[0].slot == 2
    serial, sentinel = _run_wrapper(repo, "serial", "-SlotCount", "1")
    assert serial.returncode == 1
    assert "(slots_full)" in serial.stderr and not sentinel.exists()
    wide, sentinel = _run_wrapper(repo, "wide", "-SlotCount", "2")
    assert wide.returncode == 0, wide.stderr
    assert "admitted to slot 1 of 2" in wide.stdout and sentinel.exists()


@pytest.mark.parametrize(
    ("extra", "env", "admitted", "reason"),
    (
        ((), {"WEATHER_TEST_AVAILABLE_BYTES": str(6 * GIB - 1)}, False, "available_memory_below_floor"),
        ((), {"WEATHER_TEST_AVAILABLE_BYTES": str(6 * GIB)}, True, ""),
        (("-MinAvailableMemoryGB", "2"), {"WEATHER_TEST_AVAILABLE_BYTES": str(3 * GIB)}, True, ""),
        (("-MinAvailableMemoryGB", "4"), {"WEATHER_TEST_AVAILABLE_BYTES": str(3 * GIB)}, False, "available_memory_below_floor"),
        ((), {"WEATHER_TEST_COMMIT_PERCENT": "90.1"}, False, "commit_charge_above_ceiling"),
        ((), {"WEATHER_TEST_COMMIT_PERCENT": "90"}, True, ""),
        (("-MaxCommitPercent", "50"), {"WEATHER_TEST_COMMIT_PERCENT": "60"}, False, "commit_charge_above_ceiling"),
    ),
)
def test_memory_guard_refuses_below_the_floor_and_above_the_commit_ceiling(
    workstation: Path, extra: tuple[str, ...], env: dict[str, str], admitted: bool, reason: str
) -> None:
    result, sentinel = _run_wrapper(workstation, "guard", *extra, **env)
    if admitted:
        assert result.returncode == 0, result.stderr
        assert sentinel.exists()
    else:
        assert result.returncode == 1
        assert f"blocked by another heavy or portable live lease ({reason})" in result.stderr
        assert not sentinel.exists()
        assert not any(workstation.glob(".test-heavy-workload*.poison"))


def test_memory_guard_holds_a_queued_job_until_memory_returns(workstation: Path) -> None:
    result, sentinel = _run_wrapper(
        workstation, "starved", "-Queue", "-QueueTimeoutSeconds", "2", "-QueuePollMilliseconds", "200",
        WEATHER_TEST_AVAILABLE_BYTES=str(GIB),
    )
    assert result.returncode == QUEUE_TIMEOUT_EXIT_CODE
    assert not sentinel.exists()
    give_up = next(e for e in _events(workstation) if e["event"] == "give_up")
    assert give_up["slot_refusal"] == "available_memory_below_floor"


def test_an_older_wrappers_legacy_lease_counts_as_one_slot(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    # The legacy lease exactly as older wrapper copies take it: slot 1, no slot parameter.
    holders.append(Holder(repo, LEGACY_ENTER, "old"))
    assert holders[0].slot == 1
    assert json.loads((repo / "data/logs/heavy_workload.lock").read_text(encoding="utf-8"))["workstation_slot_id"] == 1
    holders.append(Holder(repo, SLOT_ENTER, "new-a"))
    holders.append(Holder(repo, SLOT_ENTER, "new-b"))
    assert [holder.slot for holder in holders] == [1, 2, 3]
    full, sentinel = _run_wrapper(repo, "fourth")
    assert full.returncode == 1 and "(slots_full)" in full.stderr and not sentinel.exists()

    # The other direction: once new wrappers hold the legacy slot, an older wrapper is refused.
    holders[0].stop()
    holders.append(Holder(repo, SLOT_ENTER, "new-c"))
    assert holders[-1].slot == 1
    old_again = _admission(repo, f"$lease = {LEGACY_ENTER.format(repo=repo, name='old2')}\nif ($null -eq $lease) {{ 'BUSY' }} else {{ 'ACQUIRED' }}\n")
    assert old_again.returncode == 0, old_again.stderr
    assert old_again.stdout.strip() == "BUSY"


def test_a_queued_slot_waiter_passes_an_older_waiter_only_through_an_extra_slot(workstation: Path) -> None:
    repo = workstation
    queue = repo / "heavy_workload_queue_v1"
    queue.mkdir()
    # An older wrapper's ticket (no slot_aware field) owned by this live test process.
    start = _admission(repo, f"[Diagnostics.Process]::GetProcessById({os.getpid()}).StartTime.ToUniversalTime().ToString('o')\n")
    assert start.returncode == 0, start.stderr
    (queue / f"ticket-{1:012d}.json").write_text(
        json.dumps(
            {
                "schema_version": "weather_heavy_workload_queue_ticket_v1",
                "ticket": 1,
                "pid": os.getpid(),
                "owner_process_start_utc": start.stdout.strip(),
                "enqueued_at_utc": "2026-10-24T00:00:00.0000000Z",
                "workload": "WorkstationOffline-pytest-older",
                "repo_root": str(repo),
            }
        ),
        encoding="utf-8",
    )
    passed, sentinel = _run_wrapper(repo, "passer", "-Queue", "-QueuePollMilliseconds", "100", "-QueueTimeoutSeconds", "60")
    assert passed.returncode == 0, passed.stderr
    assert "admitted to slot 2 of 3" in passed.stdout and sentinel.exists()
    start_event = next(e for e in _events(repo) if e["event"] == "start")
    assert (start_event["position"], start_event["slot_id"]) == (2, 2)

    # With one slot the only slot is the legacy one, so the waiter stays behind the older ticket.
    held, sentinel = _run_wrapper(
        repo, "behind", "-Queue", "-SlotCount", "1", "-QueuePollMilliseconds", "100", "-QueueTimeoutSeconds", "2"
    )
    assert held.returncode == QUEUE_TIMEOUT_EXIT_CODE and not sentinel.exists()
    give_up = [e for e in _events(repo) if e["event"] == "give_up"]
    assert give_up[-1]["slot_refusal"] == "legacy_slot_left_to_older_waiter"


def test_portable_live_stage_and_slots_exclude_each_other_in_both_orders(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    live = Holder(repo, PORTABLE_ENTER, "live")
    holders.append(live)
    assert live.slot == 1
    blocked, sentinel = _run_wrapper(repo, "during-live")
    assert blocked.returncode == 1
    assert "(portable_live_stage)" in blocked.stderr and not sentinel.exists()
    live.stop()

    holders.append(Holder(repo, SLOT_ENTER, "heavy"))
    assert holders[-1].slot == 2
    contender = _admission(repo, f"$lease = {PORTABLE_ENTER.format(repo=repo, name='late')}\nif ($null -eq $lease) {{ 'BUSY' }} else {{ 'ACQUIRED' }}\n")
    assert contender.returncode == 0, contender.stderr
    assert contender.stdout.strip() == "BUSY"
    assert not (repo / ".test-heavy-workload.poison").exists()


def test_a_dead_slot_holder_is_reclaimed_only_by_the_legacy_stale_rules(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    holders.append(Holder(repo, LEGACY_ENTER, "old"))  # slot 1 busy, so slot 2 is the only candidate
    marker = _write_marker(repo, 2, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z")

    residual, sentinel = _run_wrapper(repo, "residual", "-SlotCount", "2", WEATHER_TEST_RESIDUAL_PID="4242")
    assert residual.returncode == 1
    assert "(free_slots_not_recoverable)" in residual.stderr and not sentinel.exists()
    assert marker.exists()
    assert _recovery_outcomes(repo) == [("refused_residual_processes", 2)]

    # An owner that is still alive is never reclaimed, whatever the mutex says.
    alive = _admission(repo, f"[Diagnostics.Process]::GetProcessById({os.getpid()}).StartTime.ToUniversalTime().ToString('o')\n")
    _write_marker(repo, 2, pid=os.getpid(), start=alive.stdout.strip())
    owner_alive, sentinel = _run_wrapper(repo, "alive", "-SlotCount", "2")
    assert owner_alive.returncode == 1 and not sentinel.exists()
    assert _recovery_outcomes(repo)[-1] == ("refused_owner_alive", 2)

    _write_marker(repo, 2, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z")
    recovered, sentinel = _run_wrapper(repo, "recovered", "-SlotCount", "2")
    assert recovered.returncode == 0, recovered.stderr
    assert "admitted to slot 2 of 2" in recovered.stdout and sentinel.exists()
    assert _recovery_outcomes(repo)[-1] == ("recovered", 2)
    assert not _slot_marker(repo, 2).exists()


def test_a_fresh_slot_is_preferred_over_a_dead_holders_slot(workstation: Path) -> None:
    repo = workstation
    marker = _write_marker(repo, 2, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z")
    result, sentinel = _run_wrapper(repo, "fresh", WEATHER_TEST_RESIDUAL_PID="4242")
    assert result.returncode == 0, result.stderr
    assert "admitted to slot 3 of 3" in result.stdout and sentinel.exists()
    assert marker.exists() and _recovery_outcomes(repo) == []


def test_a_dead_slot_owners_pending_teardown_blocks_every_admission(workstation: Path) -> None:
    repo = workstation
    _write_marker(repo, 3, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z", state="TEARDOWN_PENDING")
    expected = "teardown is pending; a proved reboot and explicit poison recovery are required (slot 3)"
    for extra in ((), ("-Queue", "-QueuePollMilliseconds", "100")):
        result, sentinel = _run_wrapper(repo, "poisoned", *extra)
        assert result.returncode == 1, extra
        assert expected in result.stderr, extra
        assert not sentinel.exists()
    for enter in (LEGACY_ENTER, PORTABLE_ENTER):
        refused = _admission(repo, enter.format(repo=repo, name="poisoned") + "\n")
        assert refused.returncode != 0 and expected in refused.stderr
    # Recovery names the slot and still demands a different boot session.
    boot = _admission(repo, "Get-WeatherBootSessionId\n")
    _write_marker(repo, 3, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z", state="TEARDOWN_PENDING", boot=int(boot.stdout))
    clear = _admission(repo, "Clear-WeatherHeavyWorkloadPoison -SlotId 3 -Confirmation 'I_HAVE_VERIFIED_NO_RESIDUAL_WEATHER_WORKLOAD_PROCESSES'\n")
    assert clear.returncode != 0 and "a different Windows boot session is required" in clear.stderr
    assert _slot_marker(repo, 3).exists()


def test_nested_callers_prove_the_exported_slot_is_held(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    holders.append(Holder(repo, SLOT_ENTER, "outer"))
    assert holders[0].slot == 2
    probe = "$r = Test-WeatherWorkstationWrapperSlotHeld\n'{0}:{1}' -f $r.SlotId, $r.Held\n"
    assert _admission(repo, probe, WEATHER_WORKSTATION_WRAPPER_SLOT="2").stdout.strip() == "2:True"
    assert _admission(repo, probe, WEATHER_WORKSTATION_WRAPPER_SLOT="3").stdout.strip() == "3:False"
    assert _admission(repo, probe).stdout.strip() == "1:False"
    invalid = _admission(repo, probe, WEATHER_WORKSTATION_WRAPPER_SLOT="9")
    assert invalid.returncode != 0 and "not a workstation slot id" in invalid.stderr


def test_capture_host_path_stays_one_serial_lease(capture_host: Path, holders: list[Holder]) -> None:
    repo = capture_host
    window = {"WEATHER_TEST_CAPTURE_WINDOW_OPEN": "1"}
    holders.append(Holder(repo, CAPTURE_ENTER, "capture_holder", **window))
    assert holders[0].slot == 1
    record = json.loads((repo / "data/logs/heavy_workload.lock").read_text(encoding="utf-8"))
    assert record["execution_host_profile"] == "capture_colocated_v1"
    assert "workstation_slot_id" not in record
    assert not record["host_global_mutex"].endswith(tuple(f".Slot{n}" for n in range(2, 9)))

    contender = _admission(
        repo, f"$lease = {CAPTURE_ENTER.format(repo=repo, name='second')}\nif ($null -eq $lease) {{ 'BUSY' }} else {{ 'ACQUIRED' }}\n", **window
    )
    assert contender.returncode == 0, contender.stderr
    assert contender.stdout.strip() == "BUSY"
    extra = _admission(repo, CAPTURE_ENTER.format(repo=repo, name="slot2") + " -WorkstationSlotId 2\n", **window)
    assert extra.returncode != 0
    assert "only workstation-offline admission may take an extra workstation slot" in extra.stderr

    for body in (
        SLOT_ENTER.format(repo=repo, name="cap") + "\n",
        EXCLUSIVE_ENTER.format(repo=repo, name="cap") + "\n",
        f"Enter-WeatherHeavyWorkloadLeaseQueued -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-1'\n",
    ):
        refused = _admission(repo, body, **window)
        assert refused.returncode != 0
        assert "forbidden on the dedicated capture host" in refused.stderr
    wrapper, sentinel = _run_wrapper(repo, "cap", **window)
    assert wrapper.returncode == 1 and "forbidden on the dedicated capture host" in wrapper.stderr
    assert not sentinel.exists()
    assert not list((repo / "data" / "logs").glob("heavy_workload.slot*.lock"))
    assert not list(repo.glob(".test-heavy-workload*.poison"))
    assert not (repo / "heavy_workload_queue_v1").exists()


LEASE_STATE_JSON = "Get-WeatherHeavyWorkloadLeaseState -RepoRoot '{repo}' | ConvertTo-Json -Compress -Depth 5\n"


def _process_start(pid: int, repo: Path) -> str:
    result = _admission(repo, f"[Diagnostics.Process]::GetProcessById({pid}).StartTime.ToUniversalTime().ToString('o')\n")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_lease_state_and_holder_summary_see_every_busy_workstation_slot(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    # A dead holder's leftover slot file widens nothing by itself.
    _write_marker(repo, 5, pid=_dead_pid(), start="2026-10-24T00:00:00.0000000Z")
    idle = json.loads(_admission(repo, LEASE_STATE_JSON.format(repo=repo)).stdout)
    assert (idle["Active"], idle["BusySlotCount"], idle["Owner"]) == (False, 0, None)

    holders.append(Holder(repo, SLOT_ENTER, "two"))
    holders.append(Holder(repo, SLOT_ENTER, "three"))
    assert [holder.slot for holder in holders] == [2, 3]
    # A live owner known only from the host-global state file (another checkout's slot lock).
    _write_marker(repo, 4, pid=os.getpid(), start=_process_start(os.getpid(), repo))
    state = json.loads(_admission(repo, LEASE_STATE_JSON.format(repo=repo)).stdout)
    assert state["Active"] is True
    assert state["Path"].endswith("heavy_workload.lock")
    assert state["BusySlotCount"] == 3
    assert [(s["SlotId"], s["Source"]) for s in state["Slots"]] == [(2, "repo_lock"), (3, "repo_lock"), (4, "host_state")]
    assert state["Slots"][0]["Workload"] == "WorkstationOffline-pytest-two"
    assert isinstance(state["Slots"][0]["Pid"], int) and state["Slots"][0]["Pid"] > 0
    assert (state["Owner"]["workload"], state["Owner"]["workstation_slot_id"]) == ("WorkstationOffline-pytest-two", 2)

    summary = _admission(repo, f"Get-WeatherHeavyWorkloadHolderSummary -RepoRoot '{repo}' | ConvertTo-Json -Compress\n")
    assert json.loads(summary.stdout) == {
        "workload": "WorkstationOffline-pytest-two",
        "pid": state["Slots"][0]["Pid"],
        "execution_host_profile": "workstation_offline_v1",
        "state": "ACTIVE",
        "slot_id": 2,
    }


def test_capture_host_lease_state_is_byte_identical_to_the_pre_slot_helper(tmp_path: Path, holders: list[Holder]) -> None:
    sources = _pre_slot_sources()
    old_repo, new_repo = tmp_path / "old", tmp_path / "new"
    mutex = "Local\\WeatherSlotFixture-" + uuid.uuid4().hex
    for repo, src in ((old_repo, sources), (new_repo, None)):
        repo.mkdir()
        _install(repo, mutex=mutex, sources=src)
        _write_assignment(repo, capture_identity=True)

    def outputs(label: str) -> tuple[str, str]:
        rendered = []
        for repo in (old_repo, new_repo):
            # Both helpers read the same checkout's lock, so only the code differs.
            result = _admission(repo, LEASE_STATE_JSON.format(repo=new_repo))
            assert result.returncode == 0, (label, result.stderr)
            rendered.append(result.stdout)
        return rendered[0], rendered[1]

    old, new = outputs("absent")
    assert new == old and json.loads(new) == {"Active": False, "Path": str(new_repo / "data/logs/heavy_workload.lock"), "Owner": None}
    # Slot files on the capture host (which never writes them) still change nothing.
    (new_repo / "data" / "logs").mkdir(parents=True, exist_ok=True)
    (new_repo / "data/logs/heavy_workload.slot2.lock").write_text("{}", encoding="utf-8")
    _write_marker(new_repo, 3, pid=os.getpid(), start=_process_start(os.getpid(), new_repo))
    holders.append(Holder(new_repo, CAPTURE_ENTER, "capture_holder", WEATHER_TEST_CAPTURE_WINDOW_OPEN="1"))
    old, new = outputs("held")
    assert new == old
    assert json.loads(new)["Active"] is True and "Slots" not in json.loads(new)
    holders[0].stop()
    old, new = outputs("released")
    assert new == old and json.loads(new)["Active"] is False


def _release_child(repo: Path, name: str, started: Path, release: Path) -> Path:
    path = repo / f"test_hold_{name}.py"
    path.write_text(
        "import time\nfrom pathlib import Path\n\n"
        "def test_hold():\n"
        f"    Path({str(started)!r}).write_text('started', encoding='utf-8')\n"
        "    deadline = time.monotonic() + 150\n"
        f"    while not Path({str(release)!r}).exists() and time.monotonic() < deadline:\n"
        "        time.sleep(0.05)\n",
        encoding="utf-8",
    )
    return path


def test_pre_slot_wrapper_bytes_interoperate_with_slot_wrappers(tmp_path: Path, holders: list[Holder]) -> None:
    sources = _pre_slot_sources()
    old_repo, new_repo = tmp_path / "old", tmp_path / "new"
    mutex = "Local\\WeatherSlotFixture-" + uuid.uuid4().hex
    shared_state = tmp_path / "host-global-heavy-workload.poison"
    for repo, src in ((old_repo, sources), (new_repo, None)):
        repo.mkdir()
        _install(repo, mutex=mutex, state_path=shared_state, sources=src)
        _write_assignment(repo, capture_identity=False)

    # 1. The pre-slot wrapper takes the legacy lease; slot wrappers count it as slot 1.
    started, release = tmp_path / "old-started.txt", tmp_path / "old-release.flag"
    old_job = subprocess.Popen(
        _wrapper_argv(old_repo, _release_child(old_repo, "old", started, release)),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(),
    )
    try:
        _wait_for(lambda: started.exists() or old_job.poll() is not None)
        assert old_job.poll() is None, old_job.communicate()
        holders.append(Holder(new_repo, SLOT_ENTER, "two"))
        holders.append(Holder(new_repo, SLOT_ENTER, "three"))
        assert [holder.slot for holder in holders] == [2, 3]
        full, sentinel = _run_wrapper(new_repo, "fourth")
        assert full.returncode == 1 and "(slots_full)" in full.stderr and not sentinel.exists()

        # Slots 2-3 busy in this checkout, slot 1 busy from the other checkout's legacy lease.
        state = json.loads(_admission(new_repo, LEASE_STATE_JSON.format(repo=new_repo)).stdout)
        assert state["Active"] is True and state["BusySlotCount"] == 3
        assert [(s["SlotId"], s["Source"]) for s in state["Slots"]] == [(1, "host_state"), (2, "repo_lock"), (3, "repo_lock")]
        assert state["Slots"][0]["Workload"].startswith("WorkstationOffline-pytest-")
        # The old checkout's own helper still sees only its slot-1 lock, as before.
        old_state = json.loads(_admission(old_repo, LEASE_STATE_JSON.format(repo=old_repo)).stdout)
        assert old_state["Active"] is True and "Slots" not in old_state
    finally:
        release.write_text("go", encoding="utf-8")
        out, err = old_job.communicate(timeout=180)
    assert old_job.returncode == 0, err
    assert "1 passed" in out

    # 2. Once slot wrappers hold the legacy slot too, the pre-slot wrapper is refused.
    holders.append(Holder(new_repo, SLOT_ENTER, "one"))
    assert holders[-1].slot == 1
    refused, sentinel = _run_wrapper(old_repo, "old-refused")
    assert refused.returncode == 1
    assert "blocked by another heavy or portable live lease" in refused.stderr and not sentinel.exists()


class ExclusiveHolder:
    """A pre-gate stand-in that waits for, then holds, the exclusive workstation lease."""

    def __init__(self, repo: Path, name: str, inherited_slot: int = 0, child: str = "") -> None:
        self.release = repo / f"release-{name}.flag"
        # A child script runs as this holder's own descendant once it holds the lease.
        child_ps = ""
        if child:
            child_path = repo / f"child-{name}.ps1"
            child_path.write_text(child, encoding="utf-8")
            child_ps = (
                "$ErrorActionPreference = 'Continue'\n"
                f"& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '{child_path}' *> '{child_path}.log'\n"
                "$childExit = $LASTEXITCODE\n$ErrorActionPreference = 'Stop'\n"
                "Write-Output ('CHILD_DONE {0}' -f $childExit)\n[Console]::Out.Flush()\n"
            )
        inherited = f" -InheritedSlotId {inherited_slot}" if inherited_slot else ""
        exit_ps = (
            "Exit-WeatherWorkstationHeavyExclusiveHold -Hold $lease"
            if inherited_slot
            else "Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null\nExit-WeatherHeavyWorkloadLease -Lease $lease"
        )
        script = f"""
$ErrorActionPreference = 'Stop'
. '{repo / "scripts/ops/workload_admission.ps1"}'
Write-Output 'WAITING'
[Console]::Out.Flush()
$lease = {EXCLUSIVE_ENTER.format(repo=repo, name=name)}{inherited}
if ($null -eq $lease) {{ Write-Output 'TIMEOUT'; exit 3 }}
Write-Output 'ACQUIRED'
[Console]::Out.Flush()
{child_ps}$deadline = [DateTime]::UtcNow.AddSeconds(150)
while (-not (Test-Path -LiteralPath '{self.release}') -and [DateTime]::UtcNow -lt $deadline) {{
    Start-Sleep -Milliseconds 50
}}
{exit_ps}
"""
        self.process = subprocess.Popen(
            [*POWERSHELL, "-Command", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env()
        )
        assert self.process.stdout is not None
        assert self.process.stdout.readline().strip() == "WAITING"

    def acquired(self) -> None:
        assert self.process.stdout is not None
        line = ""
        while line != "ACQUIRED":
            line = self.process.stdout.readline()
            assert line, self.process.stderr.read() if self.process.stderr else ""
            # Queue event lines go to the same stdout.
            line = line.strip()
            assert line == "ACQUIRED" or line.startswith("heavy-workload queue: "), line

    def child_done(self) -> int:
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            assert line, self.process.stderr.read() if self.process.stderr else ""
            line = line.strip()
            if line.startswith("CHILD_DONE"):
                return int(line.split()[1])
            assert line.startswith("heavy-workload queue: "), line

    def stop(self) -> None:
        self.release.write_text("go", encoding="utf-8")
        try:
            assert self.process.wait(timeout=60) == 0, self.process.stderr.read() if self.process.stderr else ""
        finally:
            if self.process.poll() is None:
                self.process.kill()


def _probe_lease(repo: Path, enter: str, name: str) -> str:
    result = _admission(repo, f"$lease = {enter.format(repo=repo, name=name)}\nif ($null -eq $lease) {{ 'BUSY' }} else {{ 'ACQUIRED' }}\n")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_pregate_is_exclusive_drains_every_slot_and_blocks_new_jobs(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    holders.append(Holder(repo, SLOT_ENTER, "two"))
    holders.append(Holder(repo, SLOT_ENTER, "three"))
    pregate = ExclusiveHolder(repo, "drain")
    try:
        # Waiting: it keeps every slot that frees, so nobody, old or new, slips in.
        _wait_for(lambda: any(e["event"] == "wait" and e.get("exclusive") for e in _events(repo)))
        wait = next(e for e in _events(repo) if e["event"] == "wait" and e.get("exclusive"))
        assert (wait["slot_refusal"], wait["busy_slots"]) == ("draining_slots", [2, 3])
        refused, sentinel = _run_wrapper(repo, "during-drain")
        assert refused.returncode == 1 and "(exclusive_pending)" in refused.stderr and not sentinel.exists()
        queued, sentinel = _run_wrapper(
            repo, "behind-drain", "-Queue", "-QueueTimeoutSeconds", "2", "-QueuePollMilliseconds", "100"
        )
        assert queued.returncode == QUEUE_TIMEOUT_EXIT_CODE and not sentinel.exists()
        assert [e for e in _events(repo) if e["event"] == "give_up"][-1]["slot_refusal"] == "earlier_slot_aware_waiter"
        assert _probe_lease(repo, LEGACY_ENTER, "old") == "BUSY"
        assert _probe_lease(repo, PORTABLE_ENTER, "live") == "BUSY"

        holders[0].stop()
        time.sleep(0.5)
        assert pregate.process.poll() is None
        holders[1].stop()
        pregate.acquired()  # only once every slot is free

        start = next(e for e in _events(repo) if e["event"] == "start" and e.get("exclusive"))
        assert start["slot_id"] == "all"
        owner = json.loads((repo / "data/logs/heavy_workload.lock").read_text(encoding="utf-8"))
        assert owner["workload"] == "WorkstationOffline-pytest-pregate-drain"
        state = json.loads(_admission(repo, LEASE_STATE_JSON.format(repo=repo)).stdout)
        assert state["Active"] is True and state["Owner"]["workload"] == "WorkstationOffline-pytest-pregate-drain"
        held, sentinel = _run_wrapper(repo, "during-pregate")
        assert held.returncode == 1 and "(exclusive_pending)" in held.stderr and not sentinel.exists()
        assert _probe_lease(repo, LEGACY_ENTER, "old2") == "BUSY"
    finally:
        pregate.stop()
    after, sentinel = _run_wrapper(repo, "after-pregate")
    assert after.returncode == 0, after.stderr
    assert sentinel.exists()


def test_a_nested_pregate_takes_every_other_slot(workstation: Path, holders: list[Holder]) -> None:
    repo = workstation
    holders.append(Holder(repo, SLOT_ENTER, "outer"))
    assert holders[0].slot == 2
    nested = ExclusiveHolder(repo, "nested", inherited_slot=2)
    try:
        nested.acquired()
        refused, sentinel = _run_wrapper(repo, "beside-nested")
        assert refused.returncode == 1 and "(exclusive_pending)" in refused.stderr and not sentinel.exists()
        assert _probe_lease(repo, LEGACY_ENTER, "old") == "BUSY"
    finally:
        nested.stop()
    beside, sentinel = _run_wrapper(repo, "after-nested")
    assert beside.returncode == 0, beside.stderr


def _env_child(repo: Path, name: str, record: Path) -> Path:
    path = repo / f"test_env_{name}.py"
    path.write_text(
        "import json, os\nfrom pathlib import Path\n\n"
        "def test_env():\n"
        f"    Path({str(record)!r}).write_text(json.dumps({{k: os.environ.get(k) for k in "
        "('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("cpus", "extra", "caller", "expected"),
    (
        ("16", (), {}, {"OMP_NUM_THREADS": "5", "MKL_NUM_THREADS": "5", "OPENBLAS_NUM_THREADS": "5"}),
        ("16", ("-SlotCount", "2"), {}, {"OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "8", "OPENBLAS_NUM_THREADS": "8"}),
        ("2", (), {}, {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}),
        (
            "16",
            (),
            {"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "64", "OPENBLAS_NUM_THREADS": "abc"},
            {"OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "5", "OPENBLAS_NUM_THREADS": "5"},
        ),
    ),
)
def test_wrapper_jobs_get_a_per_slot_thread_cap_callers_may_only_lower(
    workstation: Path, cpus: str, extra: tuple[str, ...], caller: dict[str, str], expected: dict[str, str]
) -> None:
    repo = workstation
    record = repo / "env.json"
    env = _env(WEATHER_TEST_LOGICAL_CPUS=cpus, **caller)
    result = subprocess.run(
        _wrapper_argv(repo, _env_child(repo, "cap", record), "-Queue", "-QueuePollMilliseconds", "100", *extra),
        capture_output=True, text=True, check=False, timeout=240, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(record.read_text(encoding="utf-8")) == expected
    finish = next(e for e in _events(repo) if e["event"] == "finish")
    cap = int(cpus) // (int(extra[1]) if extra else 3) or 1
    assert finish["thread_cap"] == {"cap": cap, "logical_processors": int(cpus), "values": {k: int(v) for k, v in expected.items()}}
    assert f"workstation-heavy: thread cap {cap} of {cpus} logical processors" in result.stdout


# ---------------------------------------------------------------- PG-NEST-1: exclusive re-entrancy
HOLDER_RECORD = Path("heavy_workload_queue_v1") / "exclusive_holder_v1.json"

DESCENDANT_ENTER = r"""
$ErrorActionPreference = 'Stop'
. '{admission}'
{prelude}
$clock = [Diagnostics.Stopwatch]::StartNew()
$hold = Enter-WeatherWorkstationHeavyExclusiveLease -RepoRoot '{repo}' -Workload 'WorkstationOffline-pytest-pregate-child' `
    -TimeoutSeconds {timeout} -PollMilliseconds 100 -ReportSeconds 1 -InheritedSlotId {slot}
$result = [ordered]@{{ granted = ($null -ne $hold); seconds = $clock.Elapsed.TotalSeconds; pid = $PID }}
if ($null -ne $hold) {{
    $result.inherited = [bool]$hold.InheritedFromExclusiveHolder
    $result.holder_pid = $hold.ExclusiveHolderPid
    $result.holder_start = $hold.ExclusiveHolderStartUtc
    $result.ticket = $hold.QueueTicket
    $result.mutexes = @($hold.ExtraSlotMutexes).Count + [int]($null -ne $hold.ExclusiveMutex)
    Exit-WeatherWorkstationHeavyExclusiveHold -Hold $hold
}}
[IO.File]::WriteAllText('{out}', ($result | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
"""


def _descendant(repo: Path, out: Path, *, slot: int, timeout: int = 3, prelude: str = "") -> str:
    return DESCENDANT_ENTER.format(
        admission=repo / "scripts/ops/workload_admission.ps1", repo=repo, out=out, slot=slot, timeout=timeout,
        prelude=prelude,
    )


@pytest.mark.parametrize("slot", (1, 0), ids=("nested-pregate-shape", "direct-pregate-shape"))
def test_a_descendant_of_the_exclusive_holder_is_admitted_at_once_without_a_ticket(workstation: Path, slot: int) -> None:
    repo = workstation
    out = repo / f"descendant-{slot}.json"
    pregate = ExclusiveHolder(repo, f"outer{slot}", child=_descendant(repo, out, slot=slot))
    try:
        pregate.acquired()
        record = json.loads((repo / HOLDER_RECORD).read_text(encoding="utf-8"))
        assert (record["pid"], record["phase"]) == (pregate.process.pid, "held")
        assert record["owner_process_start_utc"] == _process_start(pregate.process.pid, repo)
        assert pregate.child_done() == 0, (repo / f"child-outer{slot}.ps1.log").read_text(errors="replace")
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["granted"] and result["inherited"]
        assert (result["holder_pid"], result["holder_start"]) == (pregate.process.pid, record["owner_process_start_utc"])
        assert result["ticket"] is None and result["mutexes"] == 0
        child_events = [e for e in _events(repo) if e["pid"] == result["pid"]]
        assert [e["event"] for e in child_events] == ["start"]
        assert child_events[0]["lease_mode"] == "inherited_from_exclusive_holder"
        assert child_events[0]["exclusive_holder_pid"] == pregate.process.pid
        # The empty hold released nothing: the outer pre-gate still excludes everyone.
        assert _probe_lease(repo, LEGACY_ENTER, "old") == "BUSY"
    finally:
        pregate.stop()
    assert not (repo / HOLDER_RECORD).exists()


def test_the_chunk_12_shape_fails_fast_instead_of_waiting_out_its_timeout(workstation: Path) -> None:
    # Regression for the 2026-10-27 hang: a pre-gate test drove a nested pre-gate
    # (inherited slot 1) under the outer exclusive pre-gate, which could never
    # take the barrier and waited out its whole timeout. Bounded at 3 s here.
    repo = workstation
    out = repo / "chunk12.json"
    pregate = ExclusiveHolder(repo, "chunk12", child=_descendant(repo, out, slot=1, timeout=3))
    try:
        pregate.acquired()
        assert pregate.child_done() == 0
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["granted"], "the nested exclusive caller waited out its timeout under its own ancestor"
        assert result["seconds"] < 2.5
    finally:
        pregate.stop()


def test_an_unrelated_exclusive_caller_still_queues_and_logs_the_recorded_holder(workstation: Path) -> None:
    repo = workstation
    pregate = ExclusiveHolder(repo, "outer")
    try:
        pregate.acquired()
        result = _admission(
            repo,
            f"$lease = {EXCLUSIVE_ENTER.format(repo=repo, name='sibling')} -TimeoutSeconds 2 -InheritedSlotId 1\n"
            "if ($null -eq $lease) { 'BUSY' } else { 'ACQUIRED' }\n",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "BUSY"
        sibling = [e for e in _events(repo) if e["workload"] == "WorkstationOffline-pytest-pregate-sibling"]
        assert sibling[0]["event"] == "enqueue" and sibling[0]["ticket"] > 0
        give_up = next(e for e in sibling if e["event"] == "give_up")
        assert give_up["slot_refusal"] == "another_exclusive_caller"
        # Item (a): the exclusive waiter names the barrier owner, not null.
        assert give_up["holder"]["pid"] == pregate.process.pid
        assert give_up["holder"]["owner_process_start_utc"] == _process_start(pregate.process.pid, repo)
        assert give_up["holder"]["state"] == "EXCLUSIVE_HELD"
        assert all(e["holder"] is not None for e in sibling if e["event"] == "wait")
    finally:
        pregate.stop()


FORGE_START = r"""
$path = Join-Path '{repo}' 'heavy_workload_queue_v1\exclusive_holder_v1.json'
$record = [IO.File]::ReadAllText($path) | ConvertFrom-Json
$record.owner_process_start_utc = '2000-01-01T00:00:00.0000000Z'
[IO.File]::WriteAllText($path, ($record | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
"""


def test_a_holder_record_whose_start_time_does_not_match_grants_a_real_descendant_nothing(workstation: Path) -> None:
    repo = workstation
    out = repo / "forged.json"
    child = _descendant(repo, out, slot=1, timeout=2, prelude=FORGE_START.format(repo=repo))
    pregate = ExclusiveHolder(repo, "forged", child=child)
    try:
        pregate.acquired()
        assert pregate.child_done() == 0
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["granted"] is False
        child_events = [e for e in _events(repo) if e["pid"] == result["pid"]]
        assert child_events[0]["event"] == "enqueue" and child_events[-1]["event"] == "give_up"
    finally:
        pregate.stop()


FIND_WITH_SNAPSHOT = r"""
$path = Join-Path '{repo}' 'heavy_workload_queue_v1\exclusive_holder_v1.json'
$record = [IO.File]::ReadAllText($path) | ConvertFrom-Json
$now = [DateTime]::Now
$parent = [int]$record.pid
$parentCreated = $now.AddHours(-1)
switch ('{case}') {{
    'live_ancestor_control' {{ }}
    'dead_pid' {{ $parent = {dead}; $record.pid = $parent }}
    'reused_pid_wrong_start' {{ $record.owner_process_start_utc = '2000-01-01T00:00:00.0000000Z' }}
    'reused_pid_younger_parent' {{ $parentCreated = $now.AddHours(1) }}
    'other_boot_session' {{ $record.boot_session_id = [int]$record.boot_session_id + 1 }}
    'still_draining' {{ $record.phase = 'draining' }}
    'not_an_ancestor' {{ $parent = {dead} }}
}}
[IO.File]::WriteAllText($path, ($record | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
$snapshot = @(
    [PSCustomObject]@{{ ProcessId = $PID; ParentProcessId = $parent; CreationDate = $now }},
    [PSCustomObject]@{{ ProcessId = $parent; ParentProcessId = 0; CreationDate = $parentCreated }}
)
$found = Find-WeatherHeavyWorkloadExclusiveHolderAncestor -ProcessSnapshot $snapshot
if ($null -eq $found) {{ 'NONE' }} else {{ 'FOUND {{0}}' -f $found.pid }}
"""


@pytest.mark.parametrize(
    "case",
    (
        "live_ancestor_control",
        "dead_pid",
        "reused_pid_wrong_start",
        "reused_pid_younger_parent",
        "other_boot_session",
        "still_draining",
        "not_an_ancestor",
    ),
)
def test_only_a_live_ancestor_matched_by_pid_and_start_time_is_the_holder(workstation: Path, case: str) -> None:
    repo = workstation
    pregate = ExclusiveHolder(repo, "outer")
    try:
        pregate.acquired()
        result = _admission(repo, FIND_WITH_SNAPSHOT.format(repo=repo, case=case, dead=_dead_pid()))
        assert result.returncode == 0, result.stderr
        expected = f"FOUND {pregate.process.pid}" if case == "live_ancestor_control" else "NONE"
        assert result.stdout.strip() == expected
    finally:
        pregate.stop()


def test_a_record_left_by_a_released_barrier_grants_nothing(workstation: Path) -> None:
    # The owner (this pytest process) is a live ancestor with the right start time,
    # but nobody holds the barrier: the record is stale whatever it says.
    repo = workstation
    (repo / HOLDER_RECORD).parent.mkdir(parents=True, exist_ok=True)
    boot = _admission(repo, "Get-WeatherBootSessionId\n")
    assert boot.returncode == 0, boot.stderr
    (repo / HOLDER_RECORD).write_text(
        json.dumps(
            {
                "schema_version": "weather_heavy_workload_exclusive_holder_v1",
                "pid": os.getpid(),
                "owner_process_start_utc": _process_start(os.getpid(), repo),
                "boot_session_id": int(boot.stdout.strip()),
                "workload": "WorkstationOffline-pytest-pregate-gone",
                "ticket": 1,
                "phase": "held",
                "inherited_slot_id": 0,
                "recorded_at_utc": "2026-10-27T00:00:00.0000000Z",
            }
        ),
        encoding="utf-8",
    )
    found = _admission(repo, "$found = Find-WeatherHeavyWorkloadExclusiveHolderAncestor\nif ($null -eq $found) { 'NONE' } else { 'FOUND' }\n")
    assert found.returncode == 0, found.stderr
    assert found.stdout.strip() == "NONE"
    # And the ordinary path is unchanged: the caller takes the free lease itself.
    assert _probe_lease(repo, EXCLUSIVE_ENTER + " -TimeoutSeconds 5", "after-stale").splitlines()[-1] == "ACQUIRED"


UNDELETABLE_HOLDER_RECORD = r"""
# TEST-ONLY: THE HOLDER RECORD FILE CANNOT BE DELETED
function Remove-WeatherHeavyWorkloadExclusiveHolderFile { param([string]$Path) throw 'simulated delete failure' }
"""

RELEASE_THEN_REOWN = r"""
$ErrorActionPreference = 'Stop'
. '{admission}'
$lease = {enter} -TimeoutSeconds 30
if ($null -eq $lease) {{ exit 3 }}
Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null
Exit-WeatherHeavyWorkloadLease -Lease $lease
$path = Join-Path '{repo}' 'heavy_workload_queue_v1\exclusive_holder_v1.json'
$left = [IO.File]::ReadAllText($path) | ConvertFrom-Json
if ('{case}' -ceq 'warn_only_control') {{
    # What the record looked like before this fix: still "held", naming this live process.
    $left.phase = 'held'
    [IO.File]::WriteAllText($path, ($left | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
}}
# A new owner takes the barrier but has not written its own record yet.
$barrier = [Threading.Mutex]::new($false, (Get-WeatherHeavyWorkloadExclusiveMutexName))
if (-not $barrier.WaitOne(0, $false)) {{ exit 4 }}
$probe = Join-Path '{repo}' 'descendant-probe.ps1'
[IO.File]::WriteAllText($probe, @'
$ErrorActionPreference = 'Stop'
. '{admission}'
$found = Find-WeatherHeavyWorkloadExclusiveHolderAncestor
if ($null -eq $found) {{ 'NONE' }} else {{ 'FOUND {{0}}' -f $found.pid }}
'@)
$ErrorActionPreference = 'Continue'
$answer = & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $probe
$ErrorActionPreference = 'Stop'
$barrier.ReleaseMutex()
[IO.File]::WriteAllText('{out}', ([ordered]@{{ pid = $PID; phase = [string]$left.phase; answer = [string]$answer }} |
    ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
"""


@pytest.mark.parametrize("case", ("released_on_delete_failure", "warn_only_control"))
def test_a_record_that_could_not_be_removed_is_marked_released_and_grants_nothing(workstation: Path, case: str) -> None:
    # PG-NEST-1 residual: if the owner cannot delete its record at release, the
    # record must not keep vouching for the barrier once a new owner takes it
    # but has not yet written its own record. The control shows the window is real.
    repo = workstation
    admission = repo / "scripts/ops/workload_admission.ps1"
    admission.write_text(admission.read_text(encoding="utf-8") + UNDELETABLE_HOLDER_RECORD, encoding="utf-8")
    out = repo / "residual.json"
    script = RELEASE_THEN_REOWN.format(
        admission=admission, enter=EXCLUSIVE_ENTER.format(repo=repo, name="residual"), repo=repo, case=case, out=out
    )
    result = subprocess.run(
        [*POWERSHELL, "-Command", script], capture_output=True, text=True, check=False, timeout=180, env=_env()
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(out.read_text(encoding="utf-8"))
    if case == "released_on_delete_failure":
        assert "marked released" in result.stderr + result.stdout
        assert outcome["phase"] == "released"
        assert outcome["answer"] == "NONE"
    else:
        assert outcome["answer"] == f"FOUND {outcome['pid']}"
