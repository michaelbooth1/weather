"""Workstation pre-gate: the host bounded suite's launch mode, replayed on a workstation.

Guards: workstation pre-gate reproduces the capture host's bounded-suite chunk plan and console-less chunk launch (PR #230 defect class: children launched console-less on the host only).

The pre-gate (``scripts/ops/workstation_pregate.ps1`` plus its driver) must run
every head bound for a host landing night in exactly the host suite's mode:

* the chunk plan equals the host suite's own planner on the same inventory;
* each pytest chunk owns a private, windowless console exactly as the host
  suite's ``Start-WeatherProcessInJob`` launch gives it, and a launch that
  shares the launcher's console is detected;
* a head with a failing test yields FAIL; the receipt's log SHA-256 matches the
  log; the detached worktree and per-chunk basetemps are removed.

The end-to-end tests run the real pre-gate and the real host suite against a
small fixture repository whose ``venv`` reuses this interpreter's packages, in
"inherited" lease mode (inside ``workstation_heavy.ps1``, or with this process
holding the host-global workstation mutex in CI).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell and Win32 consoles"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
PREGATE = OPS / "workstation_pregate.ps1"
DRIVER = OPS / "workstation_pregate_driver.ps1"
HOST_SUITE = OPS / "bounded_worktree_test_suite.ps1"
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
COPIED_SCRIPTS = (
    "bounded_worktree_test_suite.ps1",
    "workstation_pregate.ps1",
    "workstation_pregate_driver.ps1",
    "windows_kill_on_close_job.ps1",
    "workload_admission.ps1",
    "git_executable_identity.ps1",
    "training_window_contract.ps1",
    "integration_launch_diagnostics.ps1",
)
MUTEX_NAME = "Global\\WeatherProjectHeavyWorkloadV1"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_CONFIG_GLOBAL": "NUL", "GIT_CONFIG_NOSYSTEM": "1",
}

# Classifies the console a process was given. Used both as a pytest test inside
# the fixture repository (run by the pre-gate as a chunk) and as a bare child.
CONSOLE_PROBE = r'''
import ctypes, json, os, sys
from ctypes import wintypes

def _snapshot():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    entry = ENTRY(); entry.dwSize = ctypes.sizeof(ENTRY)
    table = {}
    ok = k.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
        ok = k.Process32NextW(snap, ctypes.byref(entry))
    k.CloseHandle(snap)
    return table

def classify():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetStdHandle.restype = wintypes.HANDLE
    k.GetStdHandle.argtypes = [wintypes.DWORD]
    k.GetFileType.argtypes = [wintypes.HANDLE]
    k.GetConsoleWindow.restype = wintypes.HWND
    pids = (wintypes.DWORD * 64)()
    count = k.GetConsoleProcessList(pids, 64)
    console = {int(pids[i]) for i in range(min(count, 64))}
    table = _snapshot()
    launcher, seen, pid = None, set(), os.getpid()
    while pid in table and pid not in seen:
        seen.add(pid)
        parent = table[pid][0]
        if parent in table and table[parent][1] in ("powershell.exe", "pwsh.exe"):
            launcher = parent
            break
        pid = parent
    def kind(code):
        handle = k.GetStdHandle(code)
        if not handle or handle == wintypes.HANDLE(-1).value:
            return "none"
        return {1: "disk", 2: "char", 3: "pipe"}.get(k.GetFileType(handle), "unknown")
    return {
        "has_console": count > 0,
        "console_window": bool(k.GetConsoleWindow()),
        "launcher_found": launcher is not None,
        "shares_launcher_console": launcher in console,
        "stdin": kind(0xFFFFFFF6),
        "stdout": kind(0xFFFFFFF5),
    }

PRIVATE_WINDOWLESS = {"has_console": True, "console_window": False, "launcher_found": True,
                      "shares_launcher_console": False, "stdin": "char", "stdout": "char"}
'''

FIXTURE_CONSOLE_TEST = CONSOLE_PROBE + r'''

def test_chunk_owns_a_private_windowless_console():
    observed = classify()
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(observed, handle)
    assert observed == PRIVATE_WINDOWLESS
'''


def _run(command, *, cwd=None, env=None, timeout=600):
    return subprocess.run(
        command, cwd=cwd, env=env, check=False, capture_output=True, text=True, timeout=timeout
    )


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    result = _run(["git", "-C", str(repo), *args], env=env, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class _HeldWorkstationMutex:
    """Hold the host-global workstation mutex unless workstation_heavy already does."""

    def __enter__(self):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32 = kernel32
        self.handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        assert self.handle, ctypes.get_last_error()
        self.owned = kernel32.WaitForSingleObject(self.handle, 0) in (0, 0x80)
        return self

    def __exit__(self, *exc):
        if self.owned:
            self.kernel32.ReleaseMutex(self.handle)
        self.kernel32.CloseHandle(self.handle)


def _fixture_repo(root: Path, probe_out: Path) -> dict[str, str]:
    repo = root / "repo"
    (repo / "scripts" / "ops").mkdir(parents=True)
    for name in COPIED_SCRIPTS:
        shutil.copyfile(OPS / name, repo / "scripts" / "ops" / name)
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / "src" / "weather" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_fixture_ok.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    (repo / "tests" / "test_fixture_console.py").write_text(
        f"OUT_PATH = {str(probe_out)!r}\n" + FIXTURE_CONSOLE_TEST, encoding="utf-8"
    )
    (repo / ".gitignore").write_text("venv/\ndata/\n", encoding="utf-8")
    venv = _run([sys.executable, "-m", "venv", "--without-pip", str(repo / "venv")], timeout=300)
    assert venv.returncode == 0, venv.stderr
    packages = [path for path in site.getsitepackages() if path.endswith("site-packages")]
    (repo / "venv" / "Lib" / "site-packages" / "zz_pregate_fixture.pth").write_text(
        "".join(f"import site; site.addsitedir({path!r})\n" for path in packages), encoding="utf-8"
    )
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "good")
    good = _git(repo, "rev-parse", "HEAD")
    (repo / "tests" / "test_fixture_fails.py").write_text(
        "def test_fails():\n    assert False, 'deliberate fixture failure'\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bad")
    bad = _git(repo, "rev-parse", "HEAD")
    return {"repo": str(repo), "good": good, "bad": bad}


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("pg")
    free = shutil.disk_usage(root).free
    if free < 55 * 1024**3:
        pytest.skip("the host suite's 50 GiB disk floor cannot be met on this volume")
    info = _fixture_repo(root, root / "probe.json")
    info["root"] = str(root)
    info["probe"] = str(root / "probe.json")
    return info


def _pregate(info: dict, head: str, label: str, base: str = "") -> tuple[subprocess.CompletedProcess, dict]:
    root = Path(info["root"])
    receipt = root / f"receipt-{label}.json"
    env = os.environ.copy()
    env["WEATHER_WORKSTATION_WRAPPER_ACTIVE"] = "1"
    command = [
        *POWERSHELL, "-File", str(Path(info["repo"]) / "scripts" / "ops" / "workstation_pregate.ps1"),
        "-Head", head, "-RepoRoot", info["repo"],
        "-OutputDirectory", str(root / f"out-{label}"),
        "-ReceiptPath", str(receipt),
        "-WorktreeParent", str(root / "wt"),
    ]
    if base:
        command += ["-Base", base]
    with _HeldWorkstationMutex():
        result = _run(command, cwd=root, env=env, timeout=900)
    assert receipt.is_file(), result.stdout + result.stderr
    return result, json.loads(receipt.read_text(encoding="utf-8"))


def _assert_clean(info: dict, receipt: dict) -> None:
    assert receipt["worktree_removed"] is True
    assert not Path(receipt["worktree"]).exists()
    assert receipt["worktree"] not in _git(Path(info["repo"]), "worktree", "list", "--porcelain")
    assert receipt["basetemp_removed"] is True
    log = Path(receipt["log_path"])
    assert hashlib.sha256(log.read_bytes()).hexdigest() == receipt["log_sha256"]


# ------------------------------------------------------------------ chunk plan
PLAN_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$pregateAst = [Management.Automation.Language.Parser]::ParseFile($env:PG_PREGATE, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'pre-gate parse failure' }
foreach ($name in @('Get-WorkstationPregateHostFunctions', 'Get-WorkstationPregateChunkPlan')) {
    $definition = @($pregateAst.FindAll({ param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name }, $true))
    if ($definition.Count -ne 1) { throw "missing $name" }
    Invoke-Expression $definition[0].Extent.Text
}
$hostAst = [Management.Automation.Language.Parser]::ParseFile($env:PG_HOST, [ref]$tokens, [ref]$errors)
foreach ($name in @('Read-SuiteFileTimingTable', 'Get-SuiteTimePackedChunks')) {
    $definition = @($hostAst.FindAll({ param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name }, $true))
    Invoke-Expression $definition[0].Extent.Text
}
$tracked = @(Get-Content -LiteralPath $env:PG_INVENTORY | ForEach-Object { [string]$_ })
$plan = Get-WorkstationPregateChunkPlan -TrackedPaths $tracked -TimingTablePath $env:PG_TABLE -HostSuitePath $env:PG_HOST
# The host suite's own selection and planning, as its main body performs them.
$testFiles = @($tracked | ForEach-Object { ([string]$_).Replace("\", "/") } |
    Where-Object { $_ -match '^tests/(?:.*/)?test_[^/]*\.py$' } | Sort-Object)
$hostChunks = Get-SuiteTimePackedChunks -TestFiles $testFiles -MaxFilesPerChunk 25 `
    -TimingTable (Read-SuiteFileTimingTable -Path $env:PG_TABLE)
ConvertTo-Json -Depth 6 -Compress -InputObject ([ordered]@{
    pregate = @($plan.Chunks | ForEach-Object { ,@($_) })
    host = @($hostChunks | ForEach-Object { ,@($_) })
    cap = $plan.MaxFilesPerChunk
    files = $plan.Files.Count
})
"""


def test_chunk_plan_equals_the_host_suite_plan_for_the_real_inventory(tmp_path):
    rows = _git(REPO_ROOT, "ls-files", "--", "tests").splitlines()
    inventory = tmp_path / "inventory.txt"
    inventory.write_text("\n".join(rows + ["tests/operations/test_zz_new_unlisted_file.py"]), encoding="utf-8")
    env = {
        **os.environ,
        "PG_PREGATE": str(PREGATE),
        "PG_HOST": str(HOST_SUITE),
        "PG_INVENTORY": str(inventory),
        "PG_TABLE": str(REPO_ROOT / "tests" / "bounded_suite_file_timings.json"),
    }
    result = _run([*POWERSHELL, "-Command", PLAN_HARNESS], cwd=REPO_ROOT, env=env, timeout=180)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cap"] == 25
    assert payload["pregate"] == payload["host"]
    assert len(payload["pregate"]) == -(-payload["files"] // 25)
    assert all(1 <= len(chunk) <= 25 for chunk in payload["pregate"])


# ------------------------------------------------------------------ console attachment
LAUNCH_HARNESS = r"""
$ErrorActionPreference = 'Stop'
. $env:PG_JOB
$python = $env:PG_PYTHON
$results = [ordered]@{}
foreach ($mode in @('host', 'console_attached_mutant')) {
    $out = Join-Path $env:PG_TMP "$mode.json"
    $job = New-WeatherKillOnCloseJob
    $arguments = "-I -S `"$env:PG_PROBE`" `"$out`""
    if ($mode -eq 'host') {
        $child = Start-WeatherProcessInJob -Job $job -FilePath $python -ArgumentString $arguments -WorkingDirectory $env:PG_TMP
    } else {
        $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $python -ArgumentString $arguments -WorkingDirectory $env:PG_TMP
    }
    if (-not $child.WaitForExit(60000)) { throw "$mode probe hung" }
    $job.Dispose()
    $results[$mode] = Get-Content -LiteralPath $out -Raw | ConvertFrom-Json
}
ConvertTo-Json -Depth 4 -Compress -InputObject $results
"""

HOST_CHUNK_CALL = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:PG_HOST, [ref]$tokens, [ref]$errors)
$chunk = @($ast.FindAll({ param($node)
    if ($node -isnot [Management.Automation.Language.TryStatementAst]) { return $false }
    return @($node.Body.Statements | Where-Object {
        $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left -is [Management.Automation.Language.VariableExpressionAst] -and
        $_.Left.VariablePath.UserPath -ceq 'child' }).Count -eq 1 }, $true))
$calls = @($chunk[0].FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true) |
    ForEach-Object { $_.GetCommandName() } | Where-Object { $_ -like 'Start-Weather*' })
ConvertTo-Json -Compress -InputObject @{ chunks = $chunk.Count; calls = @($calls) }
"""


def _probe_script(tmp_path: Path) -> Path:
    script = tmp_path / "console_probe_child.py"
    script.write_text(
        CONSOLE_PROBE + "\nwith open(sys.argv[1], 'w', encoding='utf-8') as h:\n    json.dump(classify(), h)\n",
        encoding="utf-8",
    )
    return script


def _launch_probe(tmp_path: Path) -> dict:
    env = {
        **os.environ,
        "PG_JOB": str(OPS / "windows_kill_on_close_job.ps1"),
        "PG_PYTHON": sys.executable,
        "PG_PROBE": str(_probe_script(tmp_path)),
        "PG_TMP": str(tmp_path),
    }
    result = _run([*POWERSHELL, "-Command", LAUNCH_HARNESS], cwd=tmp_path, env=env, timeout=180)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_host_chunk_launch_gives_a_private_console_and_the_attached_mutant_is_detected(tmp_path):
    host = _run([*POWERSHELL, "-Command", HOST_CHUNK_CALL], cwd=REPO_ROOT,
                env={**os.environ, "PG_HOST": str(HOST_SUITE)}, timeout=60)
    assert host.returncode == 0, host.stderr
    assert json.loads(host.stdout) == {"chunks": 1, "calls": ["Start-WeatherProcessInJob"]}

    namespace: dict = {}
    exec(CONSOLE_PROBE, namespace)  # noqa: S102 - the probe's own expected classification
    observed = _launch_probe(tmp_path)
    assert observed["host"] == namespace["PRIVATE_WINDOWLESS"]
    mutant = observed["console_attached_mutant"]
    assert mutant["shares_launcher_console"] is True
    assert mutant != namespace["PRIVATE_WINDOWLESS"]


# ------------------------------------------------------------------ end to end
def test_pregate_passes_a_good_head_in_host_console_mode_and_cleans_up(fixture_repo, tmp_path):
    result, receipt = _pregate(fixture_repo, fixture_repo["good"], "good")
    assert receipt["verdict"] == "PASS", (receipt["failure_reasons"], result.stdout, result.stderr)
    assert result.returncode == 0
    assert receipt["schema"] == "weather.workstation_pregate_receipt.v1"
    assert receipt["head"] == fixture_repo["good"]
    assert receipt["lease_mode"] == "inherited_from_workstation_heavy"
    assert receipt["launch_mode"]["scheduled_task_registered"] is False
    assert receipt["chunk_plan"] == [["tests/test_fixture_console.py", "tests/test_fixture_ok.py"]]
    assert [(c["ordinal"], c["files"], c["logged_files"], c["exit_code"]) for c in receipt["chunks"]] == [
        (1, 2, 2, 0)
    ]
    assert len(receipt["skipped_host_checks"]) == 5
    _assert_clean(fixture_repo, receipt)
    log = Path(receipt["log_path"]).read_text(encoding="utf-8")
    assert "VERDICT: ALL CHUNKS PASSED (1/1)" in log
    assert "preflight admission: SKIPPED on workstation" in log
    # The chunk the pre-gate ran saw the same console as a host-launched child.
    chunk_console = json.loads(Path(fixture_repo["probe"]).read_text(encoding="utf-8"))
    assert chunk_console == _launch_probe(tmp_path)["host"]


def test_pregate_fails_a_head_whose_tests_fail(fixture_repo):
    result, receipt = _pregate(fixture_repo, fixture_repo["bad"], "bad", base=fixture_repo["good"])
    assert result.returncode == 1
    assert receipt["verdict"] == "FAIL"
    assert receipt["base_is_ancestor"] is True
    assert receipt["chunks"][0]["exit_code"] == 1
    assert "chunk 1 exited 1" in receipt["failure_reasons"]
    assert any(name.endswith("::test_fails") for name in receipt["failed_tests"])
    _assert_clean(fixture_repo, receipt)


def test_pregate_rejects_a_base_that_is_not_an_ancestor(fixture_repo):
    result, receipt = _pregate(fixture_repo, fixture_repo["good"], "base", base=fixture_repo["bad"])
    assert result.returncode == 1
    assert receipt["verdict"] == "FAIL"
    assert receipt["base_is_ancestor"] is False
    assert receipt["log_sha256"] is None


def test_pregate_detects_a_console_attached_chunk_launch_mutant(fixture_repo):
    suite = Path(fixture_repo["repo"]) / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"
    original = suite.read_bytes()
    text = original.decode("utf-8")
    needle = "$child = Start-WeatherProcessInJob `"
    assert text.count(needle) == 1
    suite.write_bytes(text.replace(needle, "$child = Start-WeatherInteractiveProcessInJob `").encode("utf-8"))
    try:
        result, receipt = _pregate(fixture_repo, fixture_repo["good"], "mutant")
    finally:
        suite.write_bytes(original)
    assert result.returncode == 1
    assert receipt["verdict"] == "FAIL"
    assert "chunk 1 exited 1" in receipt["failure_reasons"]
    assert any(name.endswith("::test_chunk_owns_a_private_windowless_console") for name in receipt["failed_tests"])
    observed = json.loads(Path(fixture_repo["probe"]).read_text(encoding="utf-8"))
    assert observed["shares_launcher_console"] is True
    _assert_clean(fixture_repo, receipt)


def test_driver_refuses_a_drifted_host_suite(tmp_path):
    ops = tmp_path / "scripts" / "ops"
    ops.mkdir(parents=True)
    shutil.copyfile(DRIVER, ops / DRIVER.name)
    text = HOST_SUITE.read_text(encoding="utf-8-sig")
    drifted = text.replace("00:30-09:00 heavy-work window", "00:30-09:00 window")
    assert drifted != text
    (ops / HOST_SUITE.name).write_text(drifted, encoding="utf-8")
    result = _run([
        *POWERSHELL, "-File", str(ops / DRIVER.name),
        "-RepoRoot", str(tmp_path), "-WorktreeRoot", str(tmp_path), "-ExpectedTip", "0" * 40,
        "-LogPath", str(tmp_path / "suite.log"), "-GitExecutablePath", "C:\\x\\git.exe",
        "-ExpectedGitExecutableSha256", "0" * 64, "-ExpectedGitExecutableFileVersion", "1",
    ], cwd=tmp_path, timeout=60)
    assert result.returncode != 0
    assert "pre-gate rule 'window' matched 0" in result.stderr
    assert not (tmp_path / "suite.log").exists()
