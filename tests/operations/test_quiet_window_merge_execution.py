"""Execution twins for the ordinary path of scripts/ops/quiet_window_merge.ps1.

The substring gates in test_quiet_window_merge_script.py read the script as
text. These twins run the real script under Windows PowerShell 5.1, the way
production launches it (``powershell.exe -File``), against a disposable fixture
repository whose ``origin`` is a bare repository under ``tmp_path``.

Isolation contract (asserted inside every twin, not assumed):

* The fixture repository's ``scripts/ops/workload_admission.ps1`` is a stub. The
  merge script dot-sources it in place of the real admission script, so its
  functions shadow, in the script's own scope, every host-reaching command the
  ordinary path can call: the workload lease, ``Get-Date``/``Start-Sleep`` (a
  logical clock), ``git`` (logged, then the real Git on the fixture), the
  ``WeatherOneShotPush`` Scheduler reads and start, and a deny-list of Scheduler,
  CIM and process cmdlets that record and throw if reached. The stub logs how
  each shadowed name resolves; the twins assert every one is the stub.
* ``roll_verdict.ps1`` in the fixture repository is a stub with a scripted exit.
* ``venv\\Scripts\\python.exe`` is replaced by a fake that serves the capture
  recovery checker from a scripted plan and the documentation transaction.
* The only edits to the script under test are three literal bindings that name
  the production host (the reviewed task-XML hash, the push principal SID and
  the venv interpreter path). Everything else is the reviewed bytes.
* Real production paths (this checkout's ``data/alerts`` and lease lock, the
  capture host's checkout and push log) are fingerprinted before and after each
  run and must be unchanged.
"""

from __future__ import annotations

import dataclasses
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
REAL_GIT = shutil.which("git.exe") or shutil.which("git")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None or REAL_GIT is None,
    reason="quiet-window merge execution twins require Windows PowerShell 5.1 and Git",
)

BRANCH_NAME = "codex/twin-feature"
BRANCH = f"origin/{BRANCH_NAME}"
# A later, unreviewed commit on the same branch. Twins move origin's branch to it
# to model a push that landed after review.
LATER_REF = "twin-later"
GENERATED_CONFIG = ("config/locations.json", "config/location_market_events.json")
MOCK_TASK_XML = "<Task>quiet-window-merge-execution-twin</Task>"
REVIEWED_TASK_XML_SHA256 = (
    "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
)
REVIEWED_PUSH_SID = (
    '$expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"'
)
VENV_PYTHON = '$py = Join-Path $repo "venv\\Scripts\\python.exe"'
PUSH_ARGUMENTS = (
    r"/c git -C c:\Users\micha\Desktop\github\weather push origin master > "
    r"C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
)
# Every name the stub must own. Calls to the deny-listed half record and throw.
SHADOWED = (
    "Enter-WeatherHeavyWorkloadLease",
    "Exit-WeatherHeavyWorkloadLease",
    "Get-Date",
    "Start-Sleep",
    "git",
    "Get-ScheduledTask",
    "Export-ScheduledTask",
    "Start-ScheduledTask",
)
FORBIDDEN = (
    "Stop-ScheduledTask",
    "Enable-ScheduledTask",
    "Disable-ScheduledTask",
    "Register-ScheduledTask",
    "Unregister-ScheduledTask",
    "Set-ScheduledTask",
    "New-ScheduledTask",
    "New-ScheduledTaskAction",
    "New-ScheduledTaskTrigger",
    "Get-ScheduledTaskInfo",
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
    REPO_ROOT / "data" / "alerts" / "documentation_transaction_pending.json",
    REPO_ROOT / "data" / "logs" / "heavy_workload.lock",
    PRODUCTION_CHECKOUT / "data" / "alerts" / "quiet_window_merge_last.json",
    PRODUCTION_CHECKOUT / "data" / "alerts" / "quiet_window_merge_history.jsonl",
    PRODUCTION_CHECKOUT / "data" / "alerts" / "quiet_window_merge_in_progress.json",
    PRODUCTION_CHECKOUT / "data" / "logs" / "heavy_workload.lock",
    Path(r"C:\Users\micha\ops\logs\push-oneshot.log"),
)


# --------------------------------------------------------------------------
# fixture construction
# --------------------------------------------------------------------------


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    assert REAL_GIT is not None
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    return _run([REAL_GIT, *arguments], cwd=repo, env=env, check=check)


def _rev(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", revision).stdout.strip().lower()


def _blob(repo: Path, revision: str) -> bytes:
    assert REAL_GIT is not None
    return subprocess.run(
        [REAL_GIT, "cat-file", "blob", revision], cwd=repo, capture_output=True, check=True
    ).stdout


def _move_branch_after_review(fx: Fixture) -> None:
    _git(fx.origin, "update-ref", f"refs/heads/{BRANCH_NAME}", fx.later_tip)


def _configure(repo: Path) -> None:
    for key, value in (
        ("user.name", "Quiet Merge Execution Twin"),
        ("user.email", "quiet-merge-twin@example.invalid"),
        ("commit.gpgSign", "false"),
        ("core.autocrlf", "false"),
        ("gc.auto", "0"),
        ("advice.detachedHead", "false"),
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
    return r'''# Quiet-window merge execution-twin stub (fixture only; never production).
# quiet_window_merge.ps1 dot-sources this file in place of the real workload
# admission script, so every function below shadows the same-named command in
# the merge script's own scope.
if (-not $env:QWM_TWIN_LOG_DIR) {
    throw "quiet-window merge twin stub loaded outside its harness"
}
$script:QwmTwinNow = [datetime]$env:QWM_TWIN_NOW

function QwmTwinLog([string]$Name, [string]$Line) {
    [IO.File]::AppendAllText(
        (Join-Path $env:QWM_TWIN_LOG_DIR $Name),
        $Line + [Environment]::NewLine
    )
}

function Enter-WeatherHeavyWorkloadLease {
    param([string]$RepoRoot, [string]$Workload, [string]$OwnerApprovedException)
    QwmTwinLog "lease.log" ("enter`t{0}`t{1}" -f $RepoRoot, $Workload)
    return [PSCustomObject]@{ twin_lease = $true }
}

function Exit-WeatherHeavyWorkloadLease {
    param($Lease)
    QwmTwinLog "lease.log" "exit"
}

function Get-Date {
    param([string]$Format)
    if ($PSBoundParameters.ContainsKey("Format")) {
        return $script:QwmTwinNow.ToString($Format)
    }
    return $script:QwmTwinNow
}

function Start-Sleep {
    param([int]$Seconds, [int]$Milliseconds)
    $ms = if ($PSBoundParameters.ContainsKey("Milliseconds")) { $Milliseconds } else { $Seconds * 1000 }
    $script:QwmTwinNow = $script:QwmTwinNow.AddMilliseconds($ms)
    QwmTwinLog "sleep.log" ([string]$ms)
}

function git {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$GitArguments)
    $tokens = @(
        foreach ($argument in $GitArguments) {
            if ($argument -is [array]) { foreach ($nested in $argument) { [string]$nested } }
            else { [string]$argument }
        }
    )
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
        State = "Ready"
        Settings = [PSCustomObject]@{
            Enabled = $true
            MultipleInstances = "IgnoreNew"
            ExecutionTimeLimit = "PT15M"
            StartWhenAvailable = $false
        }
        Principal = [PSCustomObject]@{
            UserId = "micha"
            LogonType = "Interactive"
            RunLevel = "Limited"
        }
        Actions = @([PSCustomObject]@{
            Execute = "cmd.exe"
            Arguments = $env:QWM_TWIN_PUSH_ARGUMENTS
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

function Start-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    QwmTwinLog "push.log" $TaskName
    if ($TaskName -cne "WeatherOneShotPush") {
        QwmTwinLog "forbidden.log" ("Start-ScheduledTask " + $TaskName)
        throw "twin: unexpected task start $TaskName"
    }
    if ($env:QWM_TWIN_PUSH_MODE -ceq "push") {
        & $env:QWM_TWIN_REAL_GIT -C $env:QWM_TWIN_REPO push --quiet origin master
        if ($LASTEXITCODE -ne 0) { throw "twin one-shot push failed" }
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


STUB_ROLL_VERDICT = r'''# Quiet-window merge execution-twin roll verdict stub (fixture only).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][string]$JsonOut,
    [string]$Base = ""
)
$ErrorActionPreference = "Stop"
if (-not $env:QWM_TWIN_LOG_DIR) { throw "roll verdict stub loaded outside its harness" }
[IO.File]::AppendAllText(
    (Join-Path $env:QWM_TWIN_LOG_DIR "roll.log"),
    ($Branch + [Environment]::NewLine)
)
$exitCode = [int]$env:QWM_TWIN_ROLL_EXIT
$verdict = switch ($exitCode) {
    0 { "ROLL-FREE" }
    2 { "ROLL-FREE-IF-DORMANT" }
    3 { "ROLL-SENSITIVE" }
    default { "UNDECIDABLE" }
}
$payload = [ordered]@{ verdict = $verdict; branch = $Branch; files = @() }
[IO.File]::WriteAllText($JsonOut, ($payload | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Write-Output "twin roll_verdict exit=$exitCode"
exit $exitCode
'''


FAKE_PYTHON = r'''from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

log_dir = Path(os.environ["QWM_TWIN_LOG_DIR"])
args = sys.argv[1:]
module = args[args.index("-m") + 1] if "-m" in args else ""
with (log_dir / "python.log").open("a", encoding="utf-8") as handle:
    handle.write("\t".join(args) + "\n")

if module == "weather.operations.capture_recovery_check":
    counter = log_dir / "capture-count.txt"
    call = (int(counter.read_text(encoding="ascii")) if counter.exists() else 0) + 1
    counter.write_text(str(call), encoding="ascii")
    plan = os.environ["QWM_TWIN_CAPTURE_PLAN"].split(",")
    ok = plan[min(call, len(plan)) - 1] == "ok"
    workers = [
        {
            "name": name,
            "ok": ok,
            "reasons": [] if ok else ["twin_injected_unhealthy"],
            "pid": 4100 + index,
            "last_heartbeat": "2026-10-04T00:00:00+00:00",
            "recorded_source_fingerprint": f"twin-{name}",
        }
        for index, name in enumerate(("snapshot", "clob", "observation"))
    ]
    print(json.dumps({"ok": ok, "workers": workers}))
    raise SystemExit(0 if ok else 3)

if module == "weather.operations.documentation_transaction":
    repo = Path(args[args.index("--repo-root") + 1])
    tip = args[args.index("--integration-tip") + 1]
    branch = args[args.index("--branch") + 1]
    expected_tip = args[args.index("--expected-tip") + 1]
    payload = {
        "schema_version": "documentation_transaction_pending_v0.1",
        "status": "PENDING",
        "latest_integration_tip": tip,
        "integrations": [
            {"integration_tip": tip, "branch": branch, "expected_tip": expected_tip}
        ],
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
    later_tip: str


@dataclass(frozen=True)
class Fixture:
    root: Path
    origin: Path
    repo: Path
    script: Path
    logs: Path
    elsewhere: Path
    fake_python: Path
    baseline: str
    reviewed_tip: str
    later_tip: str


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)
    return _rev(repo, "HEAD")


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Template:
    """Build origin.git and a production-shaped clone once per module."""

    root = tmp_path_factory.mktemp("qwm-template").resolve()
    seed = root / "seed"
    seed.mkdir()
    _git(seed, "init", "--quiet", "--initial-branch=master")
    _configure(seed)
    (seed / ".gitignore").write_text("data/\n", encoding="ascii")
    for relative in GENERATED_CONFIG:
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
    _git(seed, "checkout", "--quiet", "-b", LATER_REF)
    (seed / "src" / "feature.py").write_text("REVIEWED = True\nLATER = True\n", encoding="ascii")
    later_tip = _commit_all(seed, "later unreviewed push to the same branch")
    _git(seed, "checkout", "--quiet", "master")

    origin = root / "origin.git"
    _git(root, "clone", "--quiet", "--bare", str(seed), str(origin))
    repo = root / "w"
    _git(root, "clone", "--quiet", "-c", "core.autocrlf=false", str(origin), str(repo))
    _configure(repo)
    assert _rev(repo, "HEAD") == baseline
    assert _rev(repo, BRANCH) == reviewed_tip
    assert _rev(repo, f"origin/{LATER_REF}") == later_tip
    return Template(root=root, baseline=baseline, reviewed_tip=reviewed_tip, later_tip=later_tip)


def _adapted_script(fake_python: Path, source: str | None = None) -> str:
    text = SCRIPT.read_text(encoding="utf-8") if source is None else source
    replacements = {
        REVIEWED_TASK_XML_SHA256: hashlib.sha256(MOCK_TASK_XML.encode()).hexdigest(),
        REVIEWED_PUSH_SID: (
            "$expectedPushSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value"
        ),
        VENV_PYTHON: f"$py = {_ps_quote(str(fake_python))}",
    }
    for needle, replacement in replacements.items():
        # The reviewed XML hash also appears in the incident-only mode; the
        # ordinary path reads the first, and every copy names the same task.
        assert text.count(needle) >= 1, f"host binding moved: {needle}"
        text = text.replace(needle, replacement)
    return text


@pytest.fixture
def fx(template: Template, tmp_path: Path) -> Fixture:
    # Short directory names keep the fixture well inside Windows MAX_PATH.
    root = tmp_path.resolve()
    origin = root / "o.git"
    repo = root / "w"
    shutil.copytree(template.root / "origin.git", origin)
    shutil.copytree(template.root / "w", repo)
    _git(repo, "remote", "set-url", "origin", str(origin))
    (repo / "data" / "alerts").mkdir(parents=True)
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
        root=root,
        origin=origin,
        repo=repo,
        script=script,
        logs=logs,
        elsewhere=elsewhere,
        fake_python=launcher,
        baseline=template.baseline,
        reviewed_tip=template.reviewed_tip,
        later_tip=template.later_tip,
    )


# --------------------------------------------------------------------------
# invocation and observation
# --------------------------------------------------------------------------


def _real_state() -> dict[str, Any]:
    state: dict[str, Any] = {}
    for path in REAL_GUARDED_PATHS:
        try:
            stat = path.stat()
            state[str(path)] = (True, stat.st_size, stat.st_mtime_ns)
        except OSError:
            state[str(path)] = (False, None, None)
    state["checkout_head"] = _rev(REPO_ROOT, "HEAD")
    merge_head = _git(REPO_ROOT, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip()
    merge_head_path = Path(merge_head)
    if not merge_head_path.is_absolute():
        merge_head_path = REPO_ROOT / merge_head_path
    state["checkout_merge_head"] = merge_head_path.exists()
    return state


@dataclass(frozen=True)
class Outcome:
    returncode: int
    stdout: str
    stderr: str
    report: dict[str, Any] | None


def _invoke(
    fx: Fixture,
    *,
    now: str,
    roll_exit: int = 3,
    capture_plan: str = "ok",
    expected_tip: str | None = "reviewed",
    expected_baseline: str | None = None,
    repo_root: bool = True,
    launch: str = "file",
    script: Path | None = None,
    push_mode: str = "push",
) -> Outcome:
    assert WINDOWS_POWERSHELL is not None and REAL_GIT is not None
    target = script or fx.script
    arguments = ["-Branch", BRANCH]
    if expected_tip is not None:
        tip = fx.reviewed_tip if expected_tip == "reviewed" else expected_tip
        arguments += ["-ExpectedTip", tip]
    if expected_baseline is not None:
        arguments += ["-ExpectedBaseline", expected_baseline]
    if repo_root:
        arguments += ["-RepoRoot", str(fx.repo)]
    arguments += ["-SettleSeconds", "0", "-RollbackRecoverySeconds", "60"]
    command = [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    if launch == "file":
        command += ["-File", str(target), *arguments]
    else:
        operator = {"call": "&", "dot_source": "."}[launch]
        rendered = " ".join(_ps_quote(item) if not item.startswith("-") else item for item in arguments)
        command += ["-Command", f"{operator} {_ps_quote(str(target))} {rendered}; exit $LASTEXITCODE"]
    env = {
        **os.environ,
        "QWM_TWIN_LOG_DIR": str(fx.logs),
        "QWM_TWIN_NOW": now,
        "QWM_TWIN_REAL_GIT": REAL_GIT,
        "QWM_TWIN_REPO": str(fx.repo),
        "QWM_TWIN_TASK_XML": MOCK_TASK_XML,
        "QWM_TWIN_PUSH_ARGUMENTS": PUSH_ARGUMENTS,
        "QWM_TWIN_PUSH_MODE": push_mode,
        "QWM_TWIN_ROLL_EXIT": str(roll_exit),
        "QWM_TWIN_CAPTURE_PLAN": capture_plan,
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    before = _real_state()
    result = _run(command, cwd=fx.elsewhere, env=env, check=False, timeout=180)
    assert _real_state() == before, "a twin touched a real production path"
    report_path = fx.repo / "data" / "alerts" / "quiet_window_merge_last.json"
    report = json.loads(report_path.read_text(encoding="utf-8-sig")) if report_path.exists() else None
    _assert_isolated(fx)
    return Outcome(result.returncode, result.stdout, result.stderr, report)


def _lines(fx: Fixture, name: str) -> list[str]:
    path = fx.logs / name
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _assert_isolated(fx: Fixture) -> None:
    """Every reachable host command resolved to the stub and none was denied."""

    assert _lines(fx, "forbidden.log") == []
    resolution = _lines(fx, "resolution.log")
    if not resolution:
        return  # the script refused before loading the stub (parameter binding)
    stub = str(fx.repo / "scripts" / "ops" / "workload_admission.ps1")
    resolved = {}
    for line in resolution:
        name, *rest = line.split("\t")
        resolved[name] = rest
    assert resolved.pop("loaded")[0].lower() == stub.lower()
    assert set(resolved) == {*SHADOWED, *FORBIDDEN}
    for name, (command_type, source) in resolved.items():
        assert command_type == "Function", name
        assert source.lower() == stub.lower(), name


def _origin_master(fx: Fixture) -> str:
    return _rev(fx.origin, "refs/heads/master")


def _marker_path(fx: Fixture) -> Path:
    return fx.repo / "data" / "alerts" / "quiet_window_merge_in_progress.json"


def _tracked_dirty(fx: Fixture) -> list[str]:
    status = _git(fx.repo, "status", "--porcelain").stdout.splitlines()
    return sorted(line[3:] for line in status if line and not line.startswith("??"))


def _assert_untouched(fx: Fixture, outcome: Outcome) -> None:
    """Nothing merged, committed or published; the push stub never ran."""

    assert _rev(fx.repo, "HEAD") == fx.baseline, outcome.stdout
    assert _rev(fx.repo, "origin/master") == fx.baseline
    assert _origin_master(fx) == fx.baseline
    assert _lines(fx, "push.log") == []
    assert not (fx.repo / ".git" / "MERGE_HEAD").exists()
    assert not _marker_path(fx).exists()


def _write_drift(fx: Fixture, relative: str) -> bytes:
    path = fx.repo / relative
    payload = b'{\r\n  "regenerated": "' + relative.encode() + b'",\r\n  "crlf": true\r\n}\r\n'
    path.write_bytes(payload)
    return payload


# --------------------------------------------------------------------------
# (1) window refusals
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "roll_exit", "reason", "lease_taken"),
    (
        ("2026-10-04T13:00:00", 0, "inside the 12:00-18:00 graded capture window", False),
        ("2026-10-04T19:00:00", 0, "inside the 18:00-00:30 protected near-close window", False),
        ("2026-10-04T00:15:00", 0, "inside the 18:00-00:30 protected near-close window", False),
        ("2026-10-04T00:45:00", 3, "roll-sensitive branch outside the 01:00-04:00 quiet window", True),
        ("2026-10-04T04:00:00", 3, "roll-sensitive branch outside the 01:00-04:00 quiet window", True),
        ("2026-10-04T05:00:00", 3, "roll-sensitive branch outside the 01:00-04:00 quiet window", True),
        ("2026-10-04T05:00:00", 2, "roll-sensitive branch outside the 01:00-04:00 quiet window", True),
        ("2026-10-04T05:00:00", 1, "roll-sensitive branch outside the 01:00-04:00 quiet window", True),
    ),
    ids=("graded-roll-free", "near-close-roll-free", "after-midnight-roll-free",
         "sensitive-0045", "sensitive-0400", "sensitive-0500", "dormant-0500", "undecidable-0500"),
)
def test_exec_refuses_outside_its_window_before_any_git_mutation(
    fx: Fixture, now: str, roll_exit: int, reason: str, lease_taken: bool
) -> None:
    outcome = _invoke(fx, now=now, roll_exit=roll_exit)

    assert outcome.returncode == 1, outcome.stdout + outcome.stderr
    assert outcome.report is not None
    assert outcome.report["stage"] == "abort" and outcome.report["ok"] is False
    assert reason in outcome.report["detail"]
    _assert_untouched(fx, outcome)
    assert _lines(fx, "python.log") == []  # capture never probed, nothing merged
    git_calls = _lines(fx, "git.log")
    assert not any(call.split("\t")[0] in {"fetch", "merge", "commit", "add", "reset"} for call in git_calls)
    if lease_taken:
        # The roll verdict is asked under the lease, for the exact reviewed tip.
        assert _lines(fx, "lease.log") == [f"enter\t{fx.repo}\tquiet_window_merge", "exit"]
        assert _lines(fx, "roll.log") == [fx.reviewed_tip]
    else:
        # The broad host windows refuse before the lease or any classification.
        assert _lines(fx, "lease.log") == []
        assert _lines(fx, "roll.log") == []


# --------------------------------------------------------------------------
# (2) roll-free passes outside 01:00-04:00, (6) healthy capture publishes once
# --------------------------------------------------------------------------


def _assert_published(fx: Fixture, outcome: Outcome, *, first_parent: str) -> str:
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert outcome.report is not None
    assert outcome.report["stage"] == "pushed" and outcome.report["ok"] is True
    assert outcome.report["publication_acknowledged"] is True
    assert outcome.report["capture_recovery_proved"] is True
    merge = _rev(fx.repo, "HEAD")
    assert _origin_master(fx) == merge
    assert _rev(fx.repo, "origin/master") == merge
    assert outcome.report["merge_commit"] == merge
    parents = _git(fx.repo, "rev-list", "--parents", "-n", "1", merge).stdout.split()
    assert parents == [merge, first_parent, fx.reviewed_tip]
    assert outcome.report["expected_tip"] == fx.reviewed_tip
    assert outcome.report["resolved_branch_tip"] == fx.reviewed_tip
    # Published exactly once, only through the credential-bearing task, and the
    # script's own Git traffic never pushed.
    assert _lines(fx, "push.log") == ["WeatherOneShotPush"]
    assert not any("push" in call.split("\t") for call in _lines(fx, "git.log"))
    assert _lines(fx, "lease.log") == [f"enter\t{fx.repo}\tquiet_window_merge", "exit"]
    assert not _marker_path(fx).exists()
    assert not (fx.repo / ".git" / "MERGE_HEAD").exists()
    assert outcome.report["documentation_transaction_recorded"] is True
    pending = json.loads(
        (fx.repo / "data" / "alerts" / "documentation_transaction_pending.json").read_text(encoding="utf-8")
    )
    assert pending["latest_integration_tip"] == merge
    return merge


def test_exec_roll_free_branch_publishes_outside_the_quiet_window(fx: Fixture) -> None:
    outcome = _invoke(fx, now="2026-10-04T05:30:00", roll_exit=0)

    _assert_published(fx, outcome, first_parent=fx.baseline)
    assert "roll-free branch: 01:00-04:00 not required" in outcome.stdout
    assert _lines(fx, "roll.log") == [fx.reviewed_tip]


def test_exec_healthy_capture_publishes_the_merge_exactly_once(fx: Fixture) -> None:
    outcome = _invoke(fx, now="2026-10-04T01:30:00", roll_exit=3, capture_plan="ok")

    merge = _assert_published(fx, outcome, first_parent=fx.baseline)
    assert _tracked_dirty(fx) == []
    # capture before, after the staged roll, and again at the publication boundary
    assert _lines(fx, "capture-count.txt") == ["3"]
    # Publication is the last step: no Git mutation follows the push hand-off.
    git_calls = _lines(fx, "git.log")
    commit_at = max(i for i, call in enumerate(git_calls) if call.startswith("commit\t"))
    assert all(
        call.split("\t")[0] in {"rev-parse", "symbolic-ref"} for call in git_calls[commit_at + 1 :]
    )
    assert _git(fx.repo, "log", "-1", "--format=%s", merge).stdout.strip() == f"Merge {BRANCH} into master"


# --------------------------------------------------------------------------
# (3) exact-tip binding
# --------------------------------------------------------------------------


def test_exec_exact_tip_mismatch_refuses_before_drift_commit_or_merge(fx: Fixture) -> None:
    drift = _write_drift(fx, "config/locations.json")

    # The branch moved past the reviewed tip; the caller still names the reviewed one.
    _move_branch_after_review(fx)
    outcome = _invoke(fx, now="2026-10-04T01:30:00")

    assert outcome.returncode == 1
    assert outcome.report is not None and outcome.report["stage"] == "abort"
    assert outcome.report["detail"] == (
        f"branch tip moved: {BRANCH} resolves to {fx.later_tip}, expected reviewed tip {fx.reviewed_tip}"
    )
    assert outcome.report["expected_tip"] == fx.reviewed_tip
    assert outcome.report["resolved_branch_tip"] == fx.later_tip
    _assert_untouched(fx, outcome)
    # The generated drift was neither committed nor rewritten.
    assert (fx.repo / "config" / "locations.json").read_bytes() == drift
    assert _tracked_dirty(fx) == ["config/locations.json"]
    assert _lines(fx, "python.log") == []


def test_exec_legacy_caller_freezes_the_observed_tip_and_refuses_when_fetch_moves_it(
    fx: Fixture,
) -> None:
    # No -ExpectedTip: the script must freeze the locally observed tip before
    # classifying it, then refuse when its own fetch moves the branch.
    _move_branch_after_review(fx)
    assert _rev(fx.repo, BRANCH) == fx.reviewed_tip

    outcome = _invoke(fx, now="2026-10-04T01:30:00", expected_tip=None)

    assert outcome.returncode == 1
    assert _lines(fx, "roll.log") == [fx.reviewed_tip]
    assert outcome.report is not None
    assert outcome.report["detail"] == (
        f"branch tip moved: {BRANCH} resolves to {fx.later_tip}, expected reviewed tip {fx.reviewed_tip}"
    )
    _assert_untouched(fx, outcome)


def test_exec_malformed_expected_tip_refuses_before_the_lease(fx: Fixture) -> None:
    outcome = _invoke(fx, now="2026-10-04T01:30:00", expected_tip=fx.reviewed_tip[:12])

    assert outcome.returncode == 1
    assert outcome.report is not None
    assert outcome.report["detail"] == "ExpectedTip must be a full 40-character hexadecimal commit SHA"
    _assert_untouched(fx, outcome)
    assert _lines(fx, "lease.log") == [] and _lines(fx, "roll.log") == []


# --------------------------------------------------------------------------
# (4) fleet-generated drift allowlist
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drifted",
    (
        ("config/locations.json",),
        ("config/location_market_events.json",),
        GENERATED_CONFIG,
    ),
    ids=("locations", "market-events", "both"),
)
def test_exec_allowlisted_generated_drift_is_committed_then_merged(
    fx: Fixture, drifted: tuple[str, ...]
) -> None:
    payloads = {relative: _write_drift(fx, relative) for relative in drifted}

    outcome = _invoke(fx, now="2026-10-04T01:30:00")

    drift_commit = _rev(fx.repo, "HEAD^1")
    merge = _assert_published(fx, outcome, first_parent=drift_commit)
    assert _rev(fx.repo, f"{drift_commit}^") == fx.baseline
    assert _git(fx.repo, "log", "-1", "--format=%s", drift_commit).stdout.strip() == (
        "ops: preserve fleet-generated drift (pre-merge, automated)"
    )
    changed = _git(fx.repo, "diff", "--name-only", fx.baseline, drift_commit).stdout.split()
    assert sorted(changed) == sorted(drifted)
    for relative, payload in payloads.items():
        assert _blob(fx.repo, f"{merge}:{relative}") == payload
    assert outcome.report is not None and outcome.report["pre_merge_commit"] == drift_commit
    assert outcome.report["baseline_commit"] == fx.baseline


@pytest.mark.parametrize(
    "relative",
    ("src/app.py", "config/other_generated.json", ".gitignore"),
    ids=("source", "other-config", "dotfile"),
)
def test_exec_drift_outside_the_allowlist_refuses_without_losing_work(
    fx: Fixture, relative: str
) -> None:
    path = fx.repo / relative
    if not path.exists():
        path.write_text("{}\n", encoding="ascii")
        _git(fx.repo, "add", relative)
        _git(fx.repo, "commit", "--quiet", "-m", "fixture: track a non-generated config")
        _git(fx.repo, "push", "--quiet", "origin", "master")
        fx = dataclasses.replace(fx, baseline=_rev(fx.repo, "HEAD"))
    work = b"operator work in progress\r\n"
    path.write_bytes(work)
    allowlisted = _write_drift(fx, "config/locations.json")

    outcome = _invoke(fx, now="2026-10-04T01:30:00")

    assert outcome.returncode == 1
    assert outcome.report is not None and outcome.report["stage"] == "abort"
    assert "tracked files are modified outside the fleet-generated drift set" in outcome.report["detail"]
    assert relative in outcome.report["detail"]
    _assert_untouched(fx, outcome)
    assert path.read_bytes() == work
    assert (fx.repo / "config" / "locations.json").read_bytes() == allowlisted
    assert _tracked_dirty(fx) == sorted([relative, "config/locations.json"])


# --------------------------------------------------------------------------
# (5) unhealthy post-merge capture rolls back and publishes nothing
# --------------------------------------------------------------------------


def test_exec_unhealthy_capture_rolls_back_to_the_exact_pre_merge_commit(fx: Fixture) -> None:
    # Healthy before; unhealthy after the staged roll; healthy again on rollback.
    outcome = _invoke(fx, now="2026-10-04T01:30:00", capture_plan="ok,fail,ok")

    assert outcome.returncode == 2, outcome.stdout + outcome.stderr
    assert outcome.report is not None
    assert outcome.report["stage"] == "rolled_back" and outcome.report["ok"] is False
    assert "twin_injected_unhealthy" in outcome.report["detail"]
    assert outcome.report["pre_merge_commit"] == fx.baseline
    assert outcome.report["merge_commit"] is None
    assert outcome.report["capture_recovery_proved"] is False
    assert outcome.report["publication_acknowledged"] is False
    # Exact pre-merge commit, clean tree, no staged merge, nothing published.
    _assert_untouched(fx, outcome)
    assert _tracked_dirty(fx) == []
    assert not (fx.repo / "src" / "feature.py").exists()
    assert _lines(fx, "capture-count.txt") == ["3"]
    # The merge was staged (so the roll really happened) and then aborted.
    git_calls = [call.split("\t") for call in _lines(fx, "git.log")]
    merges = [call for call in git_calls if call[0] == "merge"]
    assert merges == [["merge", "--no-commit", "--no-ff", fx.reviewed_tip], ["merge", "--abort"]]
    assert not any(call[0] == "commit" for call in git_calls)


def test_exec_unproven_rollback_recovery_keeps_the_marker_and_publishes_nothing(fx: Fixture) -> None:
    drift = _write_drift(fx, "config/location_market_events.json")

    outcome = _invoke(fx, now="2026-10-04T01:30:00", capture_plan="ok,fail")

    assert outcome.returncode == 4
    assert outcome.report is not None and outcome.report["stage"] == "rollback_recovery_failed"
    assert "rollback recovery unproven" in outcome.report["detail"]
    # Git is still restored to the synchronized baseline with the generated
    # bytes preserved as allowlisted drift; recovery is merely unproven, so the
    # crash marker stays for WeatherBootRecovery and nothing is published.
    assert _rev(fx.repo, "HEAD") == fx.baseline
    assert _origin_master(fx) == fx.baseline and _lines(fx, "push.log") == []
    assert (fx.repo / "config" / "location_market_events.json").read_bytes() == drift
    assert _tracked_dirty(fx) == ["config/location_market_events.json"]
    marker = json.loads(_marker_path(fx).read_text(encoding="utf-8-sig"))
    assert marker["phase"] == "merge_uncommitted"
    assert marker["expected_tip"] == fx.reviewed_tip
    assert marker["expected_baseline"] == fx.baseline
    assert marker["baseline_commit"] == fx.baseline
    assert marker["merge_commit"] is None
    # Sleeps are logical; the 60 s recovery budget was spent in 15 s polls.
    assert set(_lines(fx, "sleep.log")) == {"0", "15000"}


# --------------------------------------------------------------------------
# (7) repository-root binding under Windows PowerShell 5.1
# --------------------------------------------------------------------------


@pytest.mark.parametrize("launch", ("file", "call", "dot_source"))
def test_exec_default_repo_root_binds_the_scripts_own_checkout(fx: Fixture, launch: str) -> None:
    # Production launches `powershell.exe -File <repo>\scripts\ops\quiet_window_merge.ps1
    # -Branch ... -ExpectedTip ...` without -RepoRoot from another directory. On
    # 2026-10-04 that died in parameter binding: $PSScriptRoot is empty inside a
    # 5.1 param() default when the script is run with -File.
    outcome = _invoke(fx, now="2026-10-04T05:30:00", roll_exit=0, repo_root=False, launch=launch)

    assert "Cannot bind argument to parameter 'Path'" not in outcome.stdout + outcome.stderr
    _assert_published(fx, outcome, first_parent=fx.baseline)
    assert outcome.report is not None
    assert Path(outcome.report["repo_root"]) == fx.repo
    assert _lines(fx, "resolution.log")[-1].split("\t")[1].lower() == str(
        fx.repo / "scripts" / "ops" / "workload_admission.ps1"
    ).lower()


def test_exec_explicit_repo_root_takes_precedence_over_the_script_location(fx: Fixture) -> None:
    # A reviewed copy outside any checkout (an integration attempt's frozen
    # helper) must operate on the -RepoRoot it is given, not on its own parent.
    detached = fx.root / "bin" / "scripts" / "ops" / "quiet_window_merge.ps1"
    detached.parent.mkdir(parents=True)
    detached.write_bytes(fx.script.read_bytes())

    outcome = _invoke(fx, now="2026-10-04T05:30:00", roll_exit=0, script=detached)

    _assert_published(fx, outcome, first_parent=fx.baseline)
    assert outcome.report is not None and Path(outcome.report["repo_root"]) == fx.repo
    assert not (fx.root / "bin" / "data").exists()
