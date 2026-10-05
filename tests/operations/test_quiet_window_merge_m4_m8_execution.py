"""Execution twins for the Swarm L M4-b publication proof and the M8 settle shadow.

Guards: quiet_window_merge.ps1 ordinary publication records a fail-closed
WeatherOneShotPush terminal proof under ordinary_* fields that status.ps1 never
treats as reconciliation-incident evidence (OD M4 condition 2), and the M8
event-settle shadow only logs: the real readoption wait stays exactly
SettleSeconds (OD M8, PILOT_FIRST shadow-only).

The twins run the real script under Windows PowerShell 5.1 ``-File`` from a
different working directory, against a disposable fixture repository whose
``origin`` is a bare repository under ``tmp_path``. The fixture's
``scripts/ops/workload_admission.ps1`` is a stub that the merge script
dot-sources, so its functions shadow every host-reaching command in the script's
own scope: the lease, a logical clock (``Get-Date``/``Start-Sleep``), ``git``,
the WeatherOneShotPush Scheduler reads, start and run information, and a
deny-list of Scheduler, CIM and process cmdlets that record and throw. Each twin
asserts every shadowed name resolved to the stub and that real production paths
were not touched. The only edits to the script under test are the three
host-bound literals (reviewed task-XML hash, push SID, venv interpreter).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
STATUS_SCRIPT = REPO_ROOT / "scripts" / "ops" / "status.ps1"
REAL_GIT = shutil.which("git.exe") or shutil.which("git")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or WINDOWS_POWERSHELL is None or REAL_GIT is None,
        reason="quiet-window merge execution twins require Windows PowerShell 5.1 and Git",
    ),
]

BRANCH_NAME = "codex/m4-m8-twin-feature"
BRANCH = f"origin/{BRANCH_NAME}"
MOCK_TASK_XML = "<Task>quiet-window-merge-m4-m8-twin</Task>"
REVIEWED_TASK_XML_SHA256 = "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
REVIEWED_PUSH_SID = '$expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"'
VENV_PYTHON = '$py = Join-Path $repo "venv\\Scripts\\python.exe"'
PUSH_ARGUMENTS = (
    r"/c git -C c:\Users\micha\Desktop\github\weather push origin master > "
    r"C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
)
PRE_LAST_RUN = "2026-10-03T03:00:00"
WORKERS = (
    ("snapshot_tracker", "loop_status.json", 4100),
    ("market_microstructure", "clob_loop_status.json", 4101),
    ("observation_trigger", "observation_trigger_status.json", 4102),
)
INITIAL_HEARTBEAT = "2026-10-04T00:00:00+00:00"
NEW_FIELDS = (
    "ordinary_publication_proof",
    "ordinary_push_task_terminal_ok",
    "ordinary_push_task_terminal_detail",
    "ordinary_push_task_pre_last_run_time",
    "ordinary_push_task_last_run_time",
    "ordinary_push_task_last_task_result",
    "ordinary_push_task_state",
    "settle_shadow",
)
SHADOWED = (
    "Enter-WeatherHeavyWorkloadLease",
    "Exit-WeatherHeavyWorkloadLease",
    "Get-Date",
    "Start-Sleep",
    "git",
    "Get-ScheduledTask",
    "Export-ScheduledTask",
    "Start-ScheduledTask",
    "Get-ScheduledTaskInfo",
)
FORBIDDEN = (
    "Stop-ScheduledTask",
    "Enable-ScheduledTask",
    "Disable-ScheduledTask",
    "Register-ScheduledTask",
    "Unregister-ScheduledTask",
    "Set-ScheduledTask",
    "New-ScheduledTask",
    "Get-CimInstance",
    "Invoke-CimMethod",
    "Get-Process",
    "Stop-Process",
    "Restart-Computer",
    "Stop-Computer",
)
PRODUCTION_CHECKOUT = Path(r"C:\Users\micha\Desktop\github\weather")
REAL_GUARDED_PATHS = (
    REPO_ROOT / "data" / "alerts" / "quiet_window_merge_last.json",
    REPO_ROOT / "data" / "alerts" / "quiet_window_merge_history.jsonl",
    REPO_ROOT / "data" / "alerts" / "quiet_window_merge_in_progress.json",
    REPO_ROOT / "data" / "logs" / "heavy_workload.lock",
    PRODUCTION_CHECKOUT / "data" / "alerts" / "quiet_window_merge_last.json",
    PRODUCTION_CHECKOUT / "data" / "alerts" / "quiet_window_merge_history.jsonl",
    PRODUCTION_CHECKOUT / "data" / "logs" / "heavy_workload.lock",
    Path(r"C:\Users\micha\ops\logs\push-oneshot.log"),
)


def _run(arguments: list[str], *, cwd: Path, env: dict[str, str] | None = None,
         check: bool = True, timeout: float = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    assert REAL_GIT is not None
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    return _run([REAL_GIT, *arguments], cwd=repo, env=env)


def _rev(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", revision).stdout.strip().lower()


def _configure(repo: Path) -> None:
    for key, value in (
        ("user.name", "Quiet Merge M4 M8 Twin"),
        ("user.email", "quiet-merge-m4-m8-twin@example.invalid"),
        ("commit.gpgSign", "false"),
        ("core.autocrlf", "false"),
        ("gc.auto", "0"),
    ):
        _git(repo, "config", key, value)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _stub_admission_text() -> str:
    forbidden = "\n".join(
        f"function {name} {{ QwmTwinLog 'forbidden.log' '{name}'; "
        f"throw 'twin: {name} is not reachable from a quiet-window merge twin' }}"
        for name in FORBIDDEN
    )
    resolution_names = ", ".join(f'"{name}"' for name in (*SHADOWED, *FORBIDDEN))
    return r'''# Quiet-window merge M4/M8 execution-twin stub (fixture only; never production).
if (-not $env:QWM_TWIN_LOG_DIR) { throw "quiet-window merge twin stub loaded outside its harness" }
$script:QwmTwinNow = [datetime]$env:QWM_TWIN_NOW
$script:QwmTwinSleptMs = 0
# Windows PowerShell 5.1 emits a JSON array as one object; enumerate it explicitly.
$script:QwmTwinStatusPlan = @(($env:QWM_TWIN_STATUS_PLAN | ConvertFrom-Json) | ForEach-Object { $_ })
$script:QwmTwinStatusApplied = 0
$script:QwmTwinTaskState = "Ready"
$script:QwmTwinLastRunTime = [datetime]$env:QWM_TWIN_PRE_LAST_RUN
$script:QwmTwinLastTaskResult = [long]0

function QwmTwinLog([string]$Name, [string]$Line) {
    [IO.File]::AppendAllText((Join-Path $env:QWM_TWIN_LOG_DIR $Name), $Line + [Environment]::NewLine)
}

function QwmTwinApplyStatusPlan {
    foreach ($entry in @($script:QwmTwinStatusPlan)) {
        if ($null -eq $entry -or $null -eq $entry.name -or
            [int]$entry.at_ms -gt $script:QwmTwinSleptMs) { continue }
        $marker = "{0}@{1}" -f $entry.name, $entry.at_ms
        $appliedPath = Join-Path $env:QWM_TWIN_LOG_DIR "status-applied.log"
        if ((Test-Path -LiteralPath $appliedPath) -and
            (@(Get-Content -LiteralPath $appliedPath) -ccontains $marker)) { continue }
        $path = Join-Path $env:QWM_TWIN_REPO ("data\snapshots\" + [string]$entry.file)
        $payload = [IO.File]::ReadAllText($path) | ConvertFrom-Json
        if ($null -ne $entry.pid) { $payload.pid = [int]$entry.pid }
        if ($null -ne $entry.fingerprint) { $payload.runtime_identity.source_fingerprint = [string]$entry.fingerprint }
        if ($null -ne $entry.heartbeat) { $payload.last_heartbeat = [string]$entry.heartbeat }
        [IO.File]::WriteAllText($path, ($payload | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
        QwmTwinLog "status-applied.log" $marker
    }
}

function Enter-WeatherHeavyWorkloadLease {
    param([string]$RepoRoot, [string]$Workload, [string]$OwnerApprovedException)
    QwmTwinLog "lease.log" ("enter`t{0}" -f $Workload)
    return [PSCustomObject]@{ twin_lease = $true }
}

function Exit-WeatherHeavyWorkloadLease {
    param($Lease)
    QwmTwinLog "lease.log" "exit"
}

function Get-Date {
    param([string]$Format)
    if ($PSBoundParameters.ContainsKey("Format")) { return $script:QwmTwinNow.ToString($Format) }
    return $script:QwmTwinNow
}

function Start-Sleep {
    param([int]$Seconds, [int]$Milliseconds)
    $ms = if ($PSBoundParameters.ContainsKey("Milliseconds")) { $Milliseconds } else { $Seconds * 1000 }
    $script:QwmTwinNow = $script:QwmTwinNow.AddMilliseconds($ms)
    $script:QwmTwinSleptMs += $ms
    QwmTwinLog "sleep.log" ([string]$ms)
    QwmTwinApplyStatusPlan
}

function git {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$GitArguments)
    $tokens = @(foreach ($argument in $GitArguments) {
            if ($argument -is [array]) { foreach ($nested in $argument) { [string]$nested } }
            else { [string]$argument }
        })
    QwmTwinLog "git.log" ($tokens -join "`t")
    if ($tokens -ccontains "push") {
        QwmTwinLog "forbidden.log" "git push from the merge script"
        throw "twin: the merge script itself must never push"
    }
    & $env:QWM_TWIN_REAL_GIT @tokens
}

function Get-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    QwmTwinLog "scheduler.log" ("Get-ScheduledTask`t{0}" -f $TaskName)
    if ($TaskName -cne "WeatherOneShotPush") { return $null }
    return [PSCustomObject]@{
        TaskPath = "\"
        State = $script:QwmTwinTaskState
        Settings = [PSCustomObject]@{
            Enabled = $true; MultipleInstances = "IgnoreNew"
            ExecutionTimeLimit = "PT15M"; StartWhenAvailable = $false
        }
        Principal = [PSCustomObject]@{ UserId = "micha"; LogonType = "Interactive"; RunLevel = "Limited" }
        Actions = @([PSCustomObject]@{
                Execute = "cmd.exe"; Arguments = $env:QWM_TWIN_PUSH_ARGUMENTS
                WorkingDirectory = $env:QWM_TWIN_REPO
            })
        Triggers = @()
    }
}

function Export-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    QwmTwinLog "scheduler.log" ("Export-ScheduledTask`t{0}" -f $TaskName)
    return $env:QWM_TWIN_TASK_XML
}

function Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    QwmTwinLog "taskinfo.log" ("{0}`t{1}" -f $TaskName, $TaskPath)
    if ($TaskName -cne "WeatherOneShotPush" -or $TaskPath -cne "\") {
        QwmTwinLog "forbidden.log" ("Get-ScheduledTaskInfo " + $TaskName)
        throw "twin: unexpected task info read $TaskName"
    }
    if ($env:QWM_TWIN_TASK_MODE -ceq "unreadable") { throw "twin: task info unavailable" }
    return [PSCustomObject]@{
        LastRunTime = $script:QwmTwinLastRunTime
        LastTaskResult = $script:QwmTwinLastTaskResult
    }
}

function Start-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    QwmTwinLog "push.log" $TaskName
    if ($TaskName -cne "WeatherOneShotPush") {
        QwmTwinLog "forbidden.log" ("Start-ScheduledTask " + $TaskName)
        throw "twin: unexpected task start $TaskName"
    }
    & $env:QWM_TWIN_REAL_GIT -C $env:QWM_TWIN_REPO push --quiet origin master
    if ($LASTEXITCODE -ne 0) { throw "twin one-shot push failed" }
    switch ($env:QWM_TWIN_TASK_MODE) {
        "ok" { $script:QwmTwinLastRunTime = $script:QwmTwinNow.AddSeconds(1); $script:QwmTwinLastTaskResult = 0 }
        "nonzero" { $script:QwmTwinLastRunTime = $script:QwmTwinNow.AddSeconds(1); $script:QwmTwinLastTaskResult = 1 }
        "running" { $script:QwmTwinLastRunTime = $script:QwmTwinNow.AddSeconds(1); $script:QwmTwinTaskState = "Running" }
        default { }
    }
}

''' + forbidden + r'''

foreach ($name in @(''' + resolution_names + r''')) {
    $command = Get-Command -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
    $file = if ($command -and $command.CommandType -eq "Function") { [string]$command.ScriptBlock.File } else { "" }
    QwmTwinLog "resolution.log" ("{0}`t{1}`t{2}" -f $name, [string]$command.CommandType, $file)
}
QwmTwinLog "resolution.log" ("loaded`t{0}" -f $PSCommandPath)
'''


STUB_ROLL_VERDICT = r'''# Quiet-window merge M4/M8 twin roll verdict stub (fixture only).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][string]$JsonOut,
    [string]$Base = ""
)
$ErrorActionPreference = "Stop"
if (-not $env:QWM_TWIN_LOG_DIR) { throw "roll verdict stub loaded outside its harness" }
$exitCode = [int]$env:QWM_TWIN_ROLL_EXIT
$verdict = switch ($exitCode) { 0 { "ROLL-FREE" } 3 { "ROLL-SENSITIVE" } default { "UNDECIDABLE" } }
$payload = [ordered]@{ verdict = $verdict; branch = $Branch; files = @() }
[IO.File]::WriteAllText($JsonOut, ($payload | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
exit $exitCode
'''


FAKE_PYTHON = r'''from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

log_dir = Path(os.environ["QWM_TWIN_LOG_DIR"])
repo_dir = Path(os.environ["QWM_TWIN_REPO"])
args = sys.argv[1:]
module = args[args.index("-m") + 1] if "-m" in args else ""
with (log_dir / "python.log").open("a", encoding="utf-8") as handle:
    handle.write("\t".join(args) + "\n")

if module == "weather.operations.capture_recovery_check":
    counter = log_dir / "capture-count.txt"
    call = (int(counter.read_text(encoding="ascii")) if counter.exists() else 0) + 1
    counter.write_text(str(call), encoding="ascii")
    workers = []
    for name, file_name in json.loads(os.environ["QWM_TWIN_WORKER_FILES"]):
        status = json.loads((repo_dir / "data" / "snapshots" / file_name).read_text(encoding="utf-8-sig"))
        workers.append({
            "name": name,
            "ok": True,
            "reasons": [],
            "pid": status["pid"],
            "last_heartbeat": status["last_heartbeat"],
            "recorded_source_fingerprint": status["runtime_identity"]["source_fingerprint"],
        })
    print(json.dumps({"ok": True, "workers": workers}))
    raise SystemExit(0)

if module == "weather.operations.documentation_transaction":
    repo = Path(args[args.index("--repo-root") + 1])
    tip = args[args.index("--integration-tip") + 1]
    branch = args[args.index("--branch") + 1]
    expected_tip = args[args.index("--expected-tip") + 1]
    payload = {
        "schema_version": "documentation_transaction_pending_v0.1",
        "status": "PENDING",
        "latest_integration_tip": tip,
        "integrations": [{"integration_tip": tip, "branch": branch, "expected_tip": expected_tip}],
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    pending = repo / "data" / "alerts" / "documentation_transaction_pending.json"
    snapshot = repo / "data" / "alerts" / "documentation_transactions" / f"pending-{digest}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    pending.write_bytes(encoded)
    snapshot.write_bytes(encoded)
    print(json.dumps({**payload, "pending_sha256": digest}))
    raise SystemExit(0)

print(f"unexpected fake Python invocation: {args!r}", file=sys.stderr)
raise SystemExit(97)
'''


@dataclass(frozen=True)
class Template:
    root: Path
    baseline: str
    reviewed_tip: str


@dataclass(frozen=True)
class Fixture:
    root: Path
    origin: Path
    repo: Path
    script: Path
    logs: Path
    elsewhere: Path
    launcher: Path
    baseline: str
    reviewed_tip: str


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)
    return _rev(repo, "HEAD")


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Template:
    root = tmp_path_factory.mktemp("qwm-m4m8").resolve()
    seed = root / "seed"
    seed.mkdir()
    _git(seed, "init", "--quiet", "--initial-branch=master")
    _configure(seed)
    (seed / ".gitignore").write_text("data/\n", encoding="ascii")
    for relative in ("config/locations.json", "config/location_market_events.json"):
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{\n  "generated": "' + relative.encode() + b'"\n}\n')
    (seed / "src").mkdir()
    (seed / "src" / "app.py").write_text("VALUE = 1\n", encoding="ascii")
    ops = seed / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / "workload_admission.ps1").write_text(_stub_admission_text(), encoding="utf-8", newline="\r\n")
    (ops / "roll_verdict.ps1").write_text(STUB_ROLL_VERDICT, encoding="utf-8", newline="\r\n")
    baseline = _commit_all(seed, "fixture baseline")
    _git(seed, "checkout", "--quiet", "-b", BRANCH_NAME)
    (seed / "src" / "feature.py").write_text("REVIEWED = True\n", encoding="ascii")
    reviewed_tip = _commit_all(seed, "reviewed feature")
    _git(seed, "checkout", "--quiet", "master")
    origin = root / "origin.git"
    _git(root, "clone", "--quiet", "--bare", str(seed), str(origin))
    repo = root / "w"
    _git(root, "clone", "--quiet", "-c", "core.autocrlf=false", str(origin), str(repo))
    _configure(repo)
    return Template(root=root, baseline=baseline, reviewed_tip=reviewed_tip)


def _adapted_script(launcher: Path, source: str | None = None) -> str:
    text = SCRIPT.read_text(encoding="utf-8") if source is None else source
    replacements = {
        REVIEWED_TASK_XML_SHA256: hashlib.sha256(MOCK_TASK_XML.encode()).hexdigest(),
        REVIEWED_PUSH_SID: "$expectedPushSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
        VENV_PYTHON: f"$py = {_ps_quote(str(launcher))}",
    }
    for needle, replacement in replacements.items():
        assert text.count(needle) >= 1, f"host binding moved: {needle}"
        text = text.replace(needle, replacement)
    return text


def _write_status_files(repo: Path) -> None:
    snapshots = repo / "data" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    for name, file_name, pid in WORKERS:
        payload = {
            "pid": pid,
            "last_heartbeat": INITIAL_HEARTBEAT,
            "runtime_identity": {"source_fingerprint": f"fp-{name}-before"},
        }
        (snapshots / file_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture
def fx(template: Template, tmp_path: Path) -> Fixture:
    root = tmp_path.resolve()
    origin = root / "o.git"
    repo = root / "w"
    shutil.copytree(template.root / "origin.git", origin)
    shutil.copytree(template.root / "w", repo)
    _git(repo, "remote", "set-url", "origin", str(origin))
    (repo / "data" / "alerts").mkdir(parents=True)
    _write_status_files(repo)
    logs = root / "logs"
    logs.mkdir()
    elsewhere = root / "cwd"
    elsewhere.mkdir()
    fake = root / "fake_python.py"
    fake.write_text(FAKE_PYTHON, encoding="utf-8")
    launcher = root / "fake_python.cmd"
    launcher.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\nexit /b %ERRORLEVEL%\n', encoding="ascii")
    script = repo / "scripts" / "ops" / "quiet_window_merge.ps1"
    script.write_text(_adapted_script(launcher), encoding="utf-8", newline="")
    with (repo / ".git" / "info" / "exclude").open("a", encoding="ascii") as handle:
        handle.write("/scripts/ops/quiet_window_merge.ps1\n")
    assert not _git(repo, "status", "--porcelain").stdout.strip()
    return Fixture(
        root=root, origin=origin, repo=repo, script=script, logs=logs, elsewhere=elsewhere,
        launcher=launcher, baseline=template.baseline, reviewed_tip=template.reviewed_tip,
    )


def _real_state() -> dict[str, Any]:
    state: dict[str, Any] = {}
    for path in REAL_GUARDED_PATHS:
        try:
            stat = path.stat()
            state[str(path)] = (True, stat.st_size, stat.st_mtime_ns)
        except OSError:
            state[str(path)] = (False, None, None)
    return state


@dataclass(frozen=True)
class Outcome:
    returncode: int
    stdout: str
    stderr: str
    report: dict[str, Any]


def _lines(fx: Fixture, name: str) -> list[str]:
    path = fx.logs / name
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _assert_isolated(fx: Fixture) -> None:
    assert _lines(fx, "forbidden.log") == []
    stub = str(fx.repo / "scripts" / "ops" / "workload_admission.ps1").lower()
    resolved = {}
    for line in _lines(fx, "resolution.log"):
        name, *rest = line.split("\t")
        resolved[name] = rest
    assert resolved.pop("loaded")[0].lower() == stub
    assert set(resolved) == {*SHADOWED, *FORBIDDEN}
    for name, (command_type, source) in resolved.items():
        assert command_type == "Function" and source.lower() == stub, name


def _invoke(
    fx: Fixture,
    *,
    now: str = "2026-10-04T05:30:00",
    roll_exit: int = 0,
    settle_seconds: int = 0,
    task_mode: str = "ok",
    status_plan: list[dict[str, Any]] | None = None,
    script: Path | None = None,
) -> Outcome:
    assert WINDOWS_POWERSHELL is not None and REAL_GIT is not None
    arguments = [
        "-Branch", BRANCH, "-ExpectedTip", fx.reviewed_tip, "-RepoRoot", str(fx.repo),
        "-SettleSeconds", str(settle_seconds), "-RollbackRecoverySeconds", "60",
    ]
    command = [
        WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(script or fx.script), *arguments,
    ]
    env = {
        **os.environ,
        "QWM_TWIN_LOG_DIR": str(fx.logs),
        "QWM_TWIN_NOW": now,
        "QWM_TWIN_REAL_GIT": REAL_GIT,
        "QWM_TWIN_REPO": str(fx.repo),
        "QWM_TWIN_TASK_XML": MOCK_TASK_XML,
        "QWM_TWIN_PUSH_ARGUMENTS": PUSH_ARGUMENTS,
        "QWM_TWIN_ROLL_EXIT": str(roll_exit),
        "QWM_TWIN_TASK_MODE": task_mode,
        "QWM_TWIN_PRE_LAST_RUN": PRE_LAST_RUN,
        "QWM_TWIN_STATUS_PLAN": json.dumps(status_plan or []),
        "QWM_TWIN_WORKER_FILES": json.dumps([[name, file_name] for name, file_name, _ in WORKERS]),
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    before = _real_state()
    # Launched like production (-File) but from an unrelated working directory.
    result = _run(command, cwd=fx.elsewhere, env=env, check=False, timeout=240)
    assert _real_state() == before, "a twin touched a real production path"
    _assert_isolated(fx)
    report_path = fx.repo / "data" / "alerts" / "quiet_window_merge_last.json"
    assert report_path.exists(), result.stdout + result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    return Outcome(result.returncode, result.stdout, result.stderr, report)


def _assert_pushed(fx: Fixture, outcome: Outcome) -> None:
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert outcome.report["stage"] == "pushed" and outcome.report["ok"] is True
    assert outcome.report["publication_acknowledged"] is True
    assert _rev(fx.origin, "refs/heads/master") == _rev(fx.repo, "HEAD") == outcome.report["merge_commit"]
    assert _lines(fx, "push.log") == ["WeatherOneShotPush"]
    # The reconciliation-only fields stay exactly as an ordinary merge always wrote them.
    assert outcome.report["push_terminal_proved"] is False
    assert outcome.report["push_run_observed"] is False
    assert outcome.report["push_terminal_proved_at"] is None
    assert outcome.report["operation_mode"] == "ordinary_synchronized_merge_v0.1"


def _settle_sleeps_ms(fx: Fixture) -> list[int]:
    """Sleeps taken before the publication loop's first 10 s poll (the settle)."""

    sleeps = [int(value) for value in _lines(fx, "sleep.log")]
    first_publication_poll = sleeps.index(10000)
    return sleeps[:first_publication_poll]


# --------------------------------------------------------------------------
# M4-b: WeatherOneShotPush terminal proof on the ordinary path
# --------------------------------------------------------------------------


def test_exec_ordinary_publication_proves_the_push_task_terminal_success(fx: Fixture) -> None:
    outcome = _invoke(fx, task_mode="ok")

    _assert_pushed(fx, outcome)
    report = outcome.report
    assert report["ordinary_push_task_terminal_ok"] is True
    assert report["ordinary_publication_proof"] == "tracking_ref+task_terminal"
    assert report["ordinary_push_task_state"] == "Ready"
    assert report["ordinary_push_task_last_task_result"] == 0
    assert report["ordinary_push_task_pre_last_run_time"].startswith(PRE_LAST_RUN)
    assert report["ordinary_push_task_last_run_time"] > report["ordinary_push_task_pre_last_run_time"]
    assert report["ordinary_push_task_terminal_detail"] == "Ready with a new LastRunTime and LastTaskResult 0"
    # One exact read before the start and one after the tracking-ref acknowledgement.
    assert _lines(fx, "taskinfo.log") == ["WeatherOneShotPush\t\\"] * 2
    history = (fx.repo / "data" / "alerts" / "quiet_window_merge_history.jsonl").read_text(encoding="utf-8")
    assert json.loads(history.splitlines()[-1])["ordinary_push_task_terminal_ok"] is True


@pytest.mark.parametrize(
    ("task_mode", "detail_prefix", "info_reads", "proof_sleeps"),
    (
        ("nonzero", "terminal with LastTaskResult 1", 2, 0),
        ("unreadable", "pre-start task info unreadable: twin: task info unavailable", 1, 0),
        ("stale", "task not yet terminal for this start (state Ready)", 13, 11),
        ("running", "task not yet terminal for this start (state Running)", 13, 11),
    ),
    ids=("nonzero-result", "info-unreadable", "last-run-not-advanced", "still-running"),
)
def test_exec_unproved_push_terminal_fails_closed_without_changing_publication(
    fx: Fixture, task_mode: str, detail_prefix: str, info_reads: int, proof_sleeps: int
) -> None:
    outcome = _invoke(fx, task_mode=task_mode)

    # Publication is still acknowledged by the tracking ref exactly as before ...
    _assert_pushed(fx, outcome)
    # ... but the terminal proof is false, never assumed, and says why.
    assert outcome.report["ordinary_push_task_terminal_ok"] is False
    assert outcome.report["ordinary_publication_proof"] == "tracking_ref"
    assert outcome.report["ordinary_push_task_terminal_detail"] == detail_prefix
    assert "WARNING: tracking ref acknowledged" in outcome.stdout
    assert len(_lines(fx, "taskinfo.log")) == info_reads
    # The proof poll is bounded: at most 11 extra 5 s waits after the acknowledgement.
    assert _lines(fx, "sleep.log").count("5000") == proof_sleeps


# --------------------------------------------------------------------------
# M4-b: the new fields are never reconciliation-incident evidence in status.ps1
# --------------------------------------------------------------------------


STATUS_INCIDENT_PROBE = r'''
param([string]$StatusScript, [string]$MarkerPath)
$ErrorActionPreference = "Stop"
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($StatusScript, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw "status.ps1 does not parse" }
$wanted = @("Test-ReconciliationIncidentFieldPopulated", "Get-ReconciliationIncidentSignals")
$definitions = @($ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $wanted -ccontains $node.Name
        }, $true))
if ($definitions.Count -ne 2) { throw "expected exactly the two incident functions; found $($definitions.Count)" }
foreach ($definition in $definitions) { . ([scriptblock]::Create($definition.Extent.Text)) }
$results = [ordered]@{}
foreach ($case in @((Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json).PSObject.Properties)) {
    $results[$case.Name] = @(Get-ReconciliationIncidentSignals -Marker $case.Value)
}
$results | ConvertTo-Json -Depth 4 -Compress
'''


def test_status_raises_no_reconciliation_incident_for_the_new_ordinary_fields(fx: Fixture) -> None:
    outcome = _invoke(fx, task_mode="ok")
    _assert_pushed(fx, outcome)
    report = outcome.report
    for field in NEW_FIELDS:
        assert field in report
        assert not field.startswith("reconciliation_")
    ordinary_fields = {field: report[field] for field in NEW_FIELDS}
    assert ordinary_fields["ordinary_push_task_terminal_ok"] is True
    cases = {
        # The exact report this run wrote, every field populated as an ordinary merge populates it.
        "actual_report": report,
        # A minimal ordinary marker carrying only the new, fully populated fields.
        "ordinary_marker": {"operation_mode": "ordinary_synchronized_merge_v0.1", **ordinary_fields},
        # Positive control: the extraction really evaluates status.ps1's list.
        "control_push_terminal_proved": {"operation_mode": "ordinary_synchronized_merge_v0.1",
                                         "push_terminal_proved": True},
    }
    markers = fx.root / "markers.json"
    markers.write_text(json.dumps(cases), encoding="utf-8")
    probe = fx.root / "status_incident_probe.ps1"
    probe.write_text(STATUS_INCIDENT_PROBE, encoding="utf-8")
    assert WINDOWS_POWERSHELL is not None
    result = _run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(probe), "-StatusScript", str(STATUS_SCRIPT), "-MarkerPath", str(markers)],
        cwd=fx.elsewhere,
    )
    signals = json.loads(result.stdout)
    assert signals["control_push_terminal_proved"] == ["push_terminal_proved"]
    assert signals["ordinary_marker"] == []
    assert not set(NEW_FIELDS) & set(signals["actual_report"])


# --------------------------------------------------------------------------
# M8: the settle shadow only logs; the real wait is exactly SettleSeconds
# --------------------------------------------------------------------------


def test_exec_settle_shadow_logs_a_floor_exit_but_the_real_wait_stays_300s(fx: Fixture) -> None:
    outcome = _invoke(fx, settle_seconds=300, roll_exit=0)

    _assert_pushed(fx, outcome)
    # The real wait: exactly 300 s of sleep, in 5 s poll steps, before the after-capture.
    assert _settle_sleeps_ms(fx) == [5000] * 60
    assert sum(_settle_sleeps_ms(fx)) == 300_000
    shadow = outcome.report["settle_shadow"]
    assert shadow["binding"] is False
    assert shadow["schema"] == "quiet_window_merge_settle_shadow_v0.1"
    assert shadow["real_wait_seconds"] == 300
    assert shadow["floor_seconds"] == 150 and shadow["poll_seconds"] == 5
    assert shadow["roll_free"] is True
    assert shadow["polls"] == 60 and shadow["probe_errors"] == 0
    # No worker readopted (roll-free): the event rule would stop at the PT2M-based floor.
    assert shadow["outcome"] == "would_exit_early"
    assert shadow["would_exit_seconds"] == 150 and shadow["would_save_seconds"] == 150
    assert all(worker["first_change_seconds"] is None for worker in shadow["workers"].values())
    assert shadow["after_ok"] is True
    assert "settle shadow (non-binding, real wait unchanged)" in outcome.stdout


def test_exec_settle_shadow_records_the_first_readoption_with_an_advanced_heartbeat(fx: Fixture) -> None:
    plan = [
        # observation_trigger restarts at 60 s but its heartbeat only advances at 240 s.
        {"at_ms": 60_000, "name": "observation_trigger", "file": "observation_trigger_status.json",
         "pid": 5102, "fingerprint": "fp-observation_trigger-after", "heartbeat": None},
        {"at_ms": 240_000, "name": "observation_trigger", "file": "observation_trigger_status.json",
         "pid": None, "fingerprint": None, "heartbeat": "2026-10-04T05:34:00+00:00"},
        # market_microstructure readopts cleanly at 200 s.
        {"at_ms": 200_000, "name": "market_microstructure", "file": "clob_loop_status.json",
         "pid": 5101, "fingerprint": "fp-market_microstructure-after",
         "heartbeat": "2026-10-04T05:33:20+00:00"},
    ]
    outcome = _invoke(fx, now="2026-10-04T01:30:00", roll_exit=3, settle_seconds=300, status_plan=plan)

    _assert_pushed(fx, outcome)
    assert sum(_settle_sleeps_ms(fx)) == 300_000
    shadow = outcome.report["settle_shadow"]
    observation = shadow["workers"]["observation_trigger"]
    assert observation["first_change_seconds"] == 60
    assert observation["first_change_pid"] == 5102
    assert observation["fingerprint_changed"] is True
    assert observation["readopted_seconds"] == 240
    clob = shadow["workers"]["market_microstructure"]
    assert clob["first_change_seconds"] == 200 and clob["readopted_seconds"] == 200
    assert shadow["workers"]["snapshot_tracker"]["first_change_seconds"] is None
    assert shadow["outcome"] == "would_exit_early"
    assert shadow["would_exit_seconds"] == 240 and shadow["would_save_seconds"] == 60
    assert shadow["roll_free"] is False


def test_exec_settle_shadow_caps_at_the_real_wait_when_readoption_is_unproved(fx: Fixture) -> None:
    plan = [
        {"at_ms": 30_000, "name": "snapshot_tracker", "file": "loop_status.json",
         "pid": None, "fingerprint": "fp-snapshot_tracker-after", "heartbeat": None},
    ]
    # The fingerprint changed but the heartbeat never advanced: the real check
    # requires heartbeat advancement for a readopted worker, so roll back; the
    # shadow must likewise never claim an early exit.
    outcome = _invoke(fx, now="2026-10-04T01:30:00", roll_exit=3, settle_seconds=40, status_plan=plan)

    assert outcome.report["stage"] == "rolled_back", outcome.stdout + outcome.stderr
    assert _lines(fx, "push.log") == []
    sleeps = [int(value) for value in _lines(fx, "sleep.log")]
    assert sleeps[:8] == [5000] * 8
    shadow = outcome.report["settle_shadow"]
    assert shadow["outcome"] == "readoption_not_observed_by_cap"
    assert shadow["would_exit_seconds"] == 40 and shadow["would_save_seconds"] == 0
    assert shadow["workers"]["snapshot_tracker"]["first_change_seconds"] == 30
    assert shadow["workers"]["snapshot_tracker"]["readopted_seconds"] is None


@pytest.mark.parametrize(
    ("settle_seconds", "expected_sleeps", "expected_exit"),
    ((0, [0], 0), (7, [5000, 2000], 7)),
    ids=("zero", "below-floor"),
)
def test_exec_settle_shadow_never_exceeds_the_real_wait(
    fx: Fixture, settle_seconds: int, expected_sleeps: list[int], expected_exit: int
) -> None:
    outcome = _invoke(fx, settle_seconds=settle_seconds)

    _assert_pushed(fx, outcome)
    assert _settle_sleeps_ms(fx) == expected_sleeps
    shadow = outcome.report["settle_shadow"]
    assert shadow["would_exit_seconds"] == expected_exit
    assert shadow["would_save_seconds"] == 0
    assert shadow["outcome"] == "would_wait_full_cap"


def test_exec_a_mutant_that_lets_the_shadow_shorten_the_wait_is_detected(fx: Fixture) -> None:
    # Kill check for the settle invariant above: a script that ends the wait at
    # the shadow's floor must produce a settle shorter than SettleSeconds.
    source = SCRIPT.read_text(encoding="utf-8")
    needle = "} while ($settleSlept -lt $SettleSeconds)"
    assert source.count(needle) == 1
    mutant = fx.root / "mutant" / "scripts" / "ops" / "quiet_window_merge.ps1"
    mutant.parent.mkdir(parents=True)
    mutated = source.replace(
        needle, "} while ($settleSlept -lt [Math]::Min($SettleSeconds, $settleShadowFloorSeconds))"
    )
    mutant.write_text(_adapted_script(fx.launcher, mutated), encoding="utf-8", newline="")

    outcome = _invoke(fx, settle_seconds=300, script=mutant)

    assert outcome.returncode == 0
    assert sum(_settle_sleeps_ms(fx)) == 150_000 != 300_000
