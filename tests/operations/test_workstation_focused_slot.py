"""Second workstation lease slot: workstation_heavy.ps1 -FocusedSlot.

Guards: HOST_LOAD_POLICY "Second lease slot" (owner decision 2026-10-13) — on the assigned
non-capture workstation only, one focused pytest run may run beside the primary heavy lease in a
separate named-mutex slot; it never queues, exits 76 when the slot is busy, kills its whole
child tree on a hard sub-300 s overrun (exit 124) or on a live-session signal (exit 77), and is
refused before it starts on the capture identity, a non-focused shape, a live-session signal or
an unproved earlier slot teardown. The primary lease and its FIFO queue state are untouched.

Every mutex, marker and process here belongs to a disposable fixture: the wrapper closure is
copied with fixture-local mutex names, the host-global state root moves into the fixture, and
the live-process scan sees only processes tagged with a per-test token.
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

from weather.operations.process_lock_identity import observe_process_identity


REPO_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass")
BUSY, PREEMPTED, OVERRUN = 76, 77, 124
pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or shutil.which("powershell") is None,
        reason="Windows PowerShell wrapper",
    ),
]


def _install(repo: Path, token: str) -> dict[str, str]:
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    for name in (
        "workstation_heavy.ps1",
        "workload_admission.ps1",
        "windows_kill_on_close_job.ps1",
        "workstation_focused_slot.ps1",
    ):
        shutil.copyfile(REPO_ROOT / "scripts" / "ops" / name, ops / name)
    hooks = repo / ".codex" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / ".codex/hooks/pre_tool_use_host_load.py", hooks / "pre_tool_use_host_load.py")
    primary = "Local\\WeatherSlotFixturePrimary-" + uuid.uuid4().hex
    slot = "Local\\WeatherSlotFixtureSlot-" + uuid.uuid4().hex
    admission = ops / "workload_admission.ps1"
    text = admission.read_text(encoding="utf-8-sig")
    assert "Global\\WeatherProjectHeavyWorkloadV1" in text
    text = text.replace("Global\\WeatherProjectHeavyWorkloadV1", primary)
    text += (
        "\n# TEST-ONLY HOST-GLOBAL STATE AND PROCESS-SCAN OVERRIDES\n"
        "function Get-WeatherHeavyWorkloadPoisonPath {\n"
        "    param([switch]$CreateIfMissing)\n"
        "    Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.test-heavy-workload.poison'\n"
        "}\n"
        "function Get-WeatherActiveWorkstationHeavyProcess { @() }\n"
        "function Get-WeatherProcessSnapshot {\n"
        "    @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name, CommandLine, CreationDate |\n"
        f"        Where-Object {{ [string]$_.CommandLine -like '*{token}*' }})\n"
        "}\n"
    )
    admission.write_text(text, encoding="utf-8")
    helper = ops / "workstation_focused_slot.ps1"
    helper_text = helper.read_text(encoding="utf-8-sig")
    assert helper_text.count("Global\\WeatherProjectWorkstationFocusedSlotV1") == 1
    helper.write_text(helper_text.replace("Global\\WeatherProjectWorkstationFocusedSlotV1", slot), encoding="utf-8")
    return {"primary": primary, "slot": slot}


def _write_assignment(repo: Path, *, capture_identity: bool) -> None:
    config = repo / "config"
    config.mkdir(parents=True, exist_ok=True)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_LEASE_SCRIPT
$hostId = Get-WeatherExecutionHostId
$record = [ordered]@{
    active_portable_execution_host_id = $hostId
    active_portable_execution_principal_id = Get-WeatherExecutionPrincipalId
    assignment_status = 'ASSIGNED'
    dedicated_capture_execution_host_id = ('f' * 64)
    reassignment_requires_new_production_tip = $true
    schema_version = 'international_live_execution_host_assignment_v0.1'
}
if ($env:WEATHER_CAPTURE_IDENTITY -eq '1') {
    $record.active_portable_execution_host_id = $null
    $record.active_portable_execution_principal_id = $null
    $record.assignment_status = 'UNASSIGNED'
    $record.dedicated_capture_execution_host_id = $hostId
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


class Fixture:
    def __init__(self, repo: Path, token: str, names: dict[str, str]) -> None:
        self.repo, self.token, self.names = repo, token, names
        self.processes: list[subprocess.Popen[str]] = []

    def child_test(self, name: str, body: str) -> Path:
        path = self.repo / f"test_slot_{name}.py"
        path.write_text(body, encoding="utf-8")
        return path

    def argv(self, test_target: str, *extra: str, kind: str = "pytest", arguments: list[str] | None = None) -> list[str]:
        if arguments is None:
            arguments = ["-m", "pytest", test_target, "-q", "-p", "no:cacheprovider",
                         "--basetemp", str(self.repo / "bt" / uuid.uuid4().hex[:8])]
        encoded = base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")
        return [*POWERSHELL, "-File", str(self.repo / "scripts/ops/workstation_heavy.ps1"), "-Kind", kind,
                "-PythonPath", sys.executable, "-ArgumentsBase64", encoded, "-RepoRoot", str(self.repo), *extra]

    def run(self, argv: list[str], timeout: float = 180) -> tuple[subprocess.CompletedProcess[str], float]:
        started = time.monotonic()
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)
        return result, time.monotonic() - started

    def spawn(self, argv: list[str]) -> subprocess.Popen[str]:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        return process

    def hold_mutex(self, name: str) -> subprocess.Popen[str]:
        release = self.repo / f"release-{uuid.uuid4().hex[:8]}.flag"
        script = (
            f"$m = [Threading.Mutex]::new($false, '{name}'); if (-not $m.WaitOne(0)) {{ 'BUSY'; exit 3 }}\n"
            "'ACQUIRED'; [Console]::Out.Flush()\n"
            f"$d = [DateTime]::UtcNow.AddSeconds(120); while (-not (Test-Path -LiteralPath '{release}') "
            "-and [DateTime]::UtcNow -lt $d) { Start-Sleep -Milliseconds 100 }\n"
            "$m.ReleaseMutex(); $m.Dispose()\n"
        )
        holder = self.spawn([*POWERSHELL, "-Command", script])
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ACQUIRED"
        holder.release = release  # type: ignore[attr-defined]
        return holder

    def fake_live_process(self, module: str = "weather.operations.international_live_session_runner") -> subprocess.Popen[str]:
        # A tagged, harmless python process whose command line names a live module.
        return self.spawn([sys.executable, "-c", "import time; time.sleep(120)", module, self.token])

    def write_portable_state(self) -> None:
        (self.repo / ".test-heavy-workload.poison").write_text(json.dumps({
            "boot_session_id": 1, "execution_host_profile": "portable_execution_v1",
            "owner_process_start_utc": "2026-10-13T00:00:00.0000000Z", "pid": os.getpid(),
            "schema_version": "weather_heavy_workload_state_v1", "state": "ACTIVE",
            "state_changed_at_utc": "2026-10-13T00:00:01.0000000Z",
            "workload": "InternationalLive-stage0-fixture-000000000000",
        }), encoding="utf-8")

    def events(self) -> list[dict]:
        path = self.repo / "data" / "logs" / "heavy_workload_focused_slot.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def cleanup(self) -> None:
        for process in self.processes:
            release = getattr(process, "release", None)
            if release is not None:
                release.write_text("go", encoding="utf-8")
        for process in self.processes:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


@pytest.fixture
def slot(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    token = "slotfixture" + uuid.uuid4().hex
    names = _install(repo, token)
    _write_assignment(repo, capture_identity=False)
    fixture = Fixture(repo, token, names)
    yield fixture
    for process in fixture.processes:
        if getattr(process, "release", None) is None and process.poll() is None:
            process.kill()
    fixture.cleanup()


QUICK = "def test_quick():\n    pass\n"


def _hanging_tree(record: Path) -> str:
    # The child publishes the pid of a grandchild it owns, then hangs.
    return (
        "import json, os, subprocess, sys, time\nfrom pathlib import Path\n\n"
        "def test_hang():\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"    tmp = Path({str(record)!r} + '.tmp')\n"
        "    tmp.write_text(json.dumps({'grandchild': child.pid, 'pytest': os.getpid()}))\n"
        f"    os.replace(tmp, {str(record)!r})\n"
        "    time.sleep(300)\n"
    )


def _wait_for(path: Path, process: subprocess.Popen[str], timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert process.poll() is None, process.communicate()
        assert time.monotonic() < deadline, "the slot child never published its tree"
        time.sleep(0.05)


def _assert_tree_gone(record: Path) -> None:
    pids = json.loads(record.read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(observe_process_identity(p)["state"] != "not_found" for p in pids.values()):
        time.sleep(0.05)
    assert all(observe_process_identity(p)["state"] == "not_found" for p in pids.values()), pids


def test_slot_runs_beside_a_held_primary_lease_without_touching_the_queue(slot: Fixture) -> None:
    slot.hold_mutex(slot.names["primary"])
    result, _ = slot.run(slot.argv(str(slot.child_test("quick", QUICK)), "-FocusedSlot"))
    assert result.returncode == 0, result.stderr
    assert "1 passed" in result.stdout
    assert [(e["event"], e.get("outcome")) for e in slot.events()] == [("start", None), ("finish", "finish")]
    assert slot.events()[0]["timeout_seconds"] == 299
    assert not (slot.repo / "heavy_workload_queue_v1").exists()
    assert not (slot.repo / "data" / "logs" / "heavy_workload_queue.jsonl").exists()
    assert not (slot.repo / ".test-heavy-workload.poison").exists()


def test_child_does_not_inherit_the_primary_wrapper_marker(slot: Fixture) -> None:
    probe = slot.child_test("env", (
        "import os\n\ndef test_env():\n"
        "    assert os.environ.get('WEATHER_WORKSTATION_WRAPPER_ACTIVE') is None\n"
        "    assert os.environ['WEATHER_WORKSTATION_FOCUSED_SLOT_ACTIVE'] == '1'\n"
    ))
    env = {**os.environ, "WEATHER_WORKSTATION_WRAPPER_ACTIVE": "1"}
    result = subprocess.run(slot.argv(str(probe), "-FocusedSlot"), capture_output=True, text=True,
                            check=False, timeout=180, env=env)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_busy_slot_exits_76_without_starting(slot: Fixture) -> None:
    slot.hold_mutex(slot.names["slot"])
    sentinel = slot.repo / "never.txt"
    body = f"from pathlib import Path\n\ndef test_x():\n    Path({str(sentinel)!r}).write_text('ran')\n"
    result, _ = slot.run(slot.argv(str(slot.child_test("busy", body)), "-FocusedSlot"))
    assert result.returncode == BUSY, result.stderr
    assert "focused slot is busy; nothing was started" in result.stderr
    assert not sentinel.exists()
    assert [e["event"] for e in slot.events()] == ["busy"]


def test_overrun_kills_the_whole_child_tree_and_exits_124(slot: Fixture) -> None:
    record = slot.repo / "tree.json"
    process = slot.spawn(slot.argv(str(slot.child_test("overrun", _hanging_tree(record))),
                                   "-FocusedSlot", "-FocusedSlotTimeoutSeconds", "3"))
    _wait_for(record, process)
    stdout, stderr = process.communicate(timeout=60)
    assert process.returncode == OVERRUN, stdout + stderr
    assert "time limit of 3 s overrun; the child tree was killed" in stderr
    _assert_tree_gone(record)
    finish = slot.events()[-1]
    assert (finish["event"], finish["outcome"], finish["exit_code"]) == ("finish", "overrun", OVERRUN)


@pytest.mark.parametrize("signal", ["session_marker", "portable_state", "live_process"])
def test_a_live_signal_mid_run_preempts_and_kills_the_tree(slot: Fixture, signal: str) -> None:
    record = slot.repo / "tree.json"
    process = slot.spawn(slot.argv(str(slot.child_test("preempt", _hanging_tree(record))), "-FocusedSlot"))
    _wait_for(record, process)
    raised = time.monotonic()
    if signal == "session_marker":
        (slot.repo / "live_session_v1.active").write_text("session", encoding="utf-8")
    elif signal == "portable_state":
        slot.write_portable_state()
    else:
        slot.fake_live_process()
    stdout, stderr = process.communicate(timeout=60)
    assert process.returncode == PREEMPTED, stdout + stderr
    assert time.monotonic() - raised < 30
    assert "workstation focused slot pre-empted" in stderr
    _assert_tree_gone(record)
    assert slot.events()[-1]["outcome"] == "preempted"


@pytest.mark.parametrize("case,reason", [
    ("session_marker", "the live-session marker live_session_v1.active is present"),
    ("portable_state", "a portable live stage holds the host-global mutex"),
    ("live_process", "a live-session process is running"),
    ("pilot_process", "a live-session process is running"),
    ("slot_poison", "an earlier slot teardown was not proved"),
    ("queue", "-FocusedSlot cannot combine with -Queue"),
    ("no_basetemp", "a focused run needs an explicit --basetemp"),
    ("directory", "is not a test file; directories and globs cannot be bounded"),
    ("compileall", "the focused slot admits only pytest runs"),
])
def test_refusals_happen_before_anything_starts(slot: Fixture, case: str, reason: str) -> None:
    sentinel = slot.repo / "never.txt"
    target = str(slot.child_test("refused", f"from pathlib import Path\n\ndef test_x():\n    Path({str(sentinel)!r}).write_text('ran')\n"))
    extra: list[str] = ["-FocusedSlot"]
    arguments = None
    kind = "pytest"
    if case == "session_marker":
        (slot.repo / "live_session_v1.active").write_text("session", encoding="utf-8")
    elif case == "portable_state":
        slot.write_portable_state()
    elif case == "live_process":
        slot.fake_live_process()
    elif case == "pilot_process":
        slot.fake_live_process("weather.market.mm_live_pilot_cli")
    elif case == "slot_poison":
        (slot.repo / "workstation_focused_slot_v1.poison").write_text("{}", encoding="utf-8")
    elif case == "queue":
        extra.append("-Queue")
    elif case == "no_basetemp":
        arguments = ["-m", "pytest", target, "-q"]
    elif case == "directory":
        arguments = ["-m", "pytest", str(slot.repo), "-q", "--basetemp", str(slot.repo / "bt")]
    elif case == "compileall":
        kind = "compileall"
        arguments = ["-m", "compileall", "-q", str(slot.repo)]
    result, _ = slot.run(slot.argv(target, *extra, kind=kind, arguments=arguments))
    assert result.returncode == 1, result.stdout + result.stderr
    assert reason in result.stderr, result.stderr
    assert not sentinel.exists()
    assert not any(e["event"] == "start" for e in slot.events())


def test_capture_identity_is_refused_before_any_slot_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    token = "slotfixture" + uuid.uuid4().hex
    names = _install(repo, token)
    _write_assignment(repo, capture_identity=True)
    fixture = Fixture(repo, token, names)
    result, _ = fixture.run(fixture.argv(str(fixture.child_test("capture", QUICK)), "-FocusedSlot"))
    assert result.returncode == 1
    assert "workstation-offline admission is forbidden on the dedicated capture host" in result.stderr
    assert fixture.events() == []
    assert not (repo / "data").exists()
