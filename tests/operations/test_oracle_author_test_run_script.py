"""Native fixture tests for scripts/ops/oracle_author_test_run.ps1.

Guards: owner ruling I-6 (2026-10-12) — the clean-room oracle author's quick unit tests run only
00:30-09:00 under the shared lease (HOST_LOAD_POLICY rules 1, 2 and 7), inside the H1 cut, from an
isolated interpreter that cannot import the production clone, in a kill-on-close Job, with an
explicit deleted --basetemp and a receipt.

The real wrapper, lease and Job helpers run against a disposable production root. Only the fixture
clock, the timeout unit, the disk floor, the lease mutex namespace and the lease policy window
change. A stub ``pytest`` package in a fixture venv records what the child saw.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import venv

import pytest

from weather.paths import repo_path


pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt", reason="real Windows PowerShell/Job/lease orchestration"),
]

ADMITTED = "2026-10-13T10:00:00Z"        # 06:00 Toronto (EDT)

# The child's environment is allowlisted, so the stub finds its control files next to the venv.
STUB_PYTEST = r'''
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main(args):
    mode = (ROOT / "mode.txt").read_text().strip() if (ROOT / "mode.txt").exists() else "pass"
    basetemp = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--basetemp=")))
    basetemp.mkdir()
    (basetemp / "used.txt").write_text("x")
    import weather
    record = dict(argv=list(args), isolated=sys.flags.isolated, no_site=sys.flags.no_site,
                  dont_write_bytecode=bool(sys.dont_write_bytecode), path=list(sys.path), env=dict(os.environ),
                  cwd=os.getcwd(), weather=weather.__file__, basetemp=str(basetemp))
    with open(ROOT / "record.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    if mode == "fail":
        return 1
    if mode == "write_cut":
        Path("planted.txt").write_text("leak")
        return 0
    if mode == "hang":
        import subprocess
        child = subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time; time.sleep(300)"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        (ROOT / "hang.json").write_text(json.dumps(dict(pid=child.pid, worker_pid=os.getpid())))
        time.sleep(300)
    return 0
'''

HOLDER = r'''
. '{admission}'
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot '{repo}' -Workload fixture_holder
if ($null -eq $lease) {{ Write-Output 'BLOCKED'; exit 3 }}
Write-Output 'ACQUIRED'
[Console]::Out.Flush()
while (-not (Test-Path -LiteralPath '{release}')) {{ Start-Sleep -Milliseconds 100 }}
Exit-WeatherHeavyWorkloadLease -Lease $lease
'''


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def fx(tmp_path):
    repo, cut, logs, oracle = tmp_path / "production", tmp_path / "cut", tmp_path / "logs", tmp_path / "oracle-venv"
    ops = repo / "scripts/ops"
    ops.mkdir(parents=True)
    for name in ("windows_kill_on_close_job.ps1", "memory_guard_status_reader.ps1"):
        shutil.copy2(repo_path("scripts/ops") / name, ops)
    mutex = "Local\\OracleAuthorTestFixture-" + uuid.uuid4().hex
    admission = repo_path("scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    admission = admission.replace("Global\\WeatherProjectHeavyWorkloadV1", mutex)
    admission += "\nfunction Get-WeatherHeavyWorkloadPolicyWindow { return 'fixture-clock-only' }\n"
    write(ops / "workload_admission.ps1", admission)
    script = repo_path("scripts/ops/oracle_author_test_run.ps1").read_text(encoding="utf-8-sig")
    script = replace_once(script, "function Get-OracleTestUtcNow { return [DateTime]::UtcNow }",
        "function Get-OracleTestUtcNow { return [DateTime]::Parse($env:FIXTURE_UTC_NOW).ToUniversalTime() }")
    script = replace_once(script, "$TimeoutUnitSeconds = 60", "$TimeoutUnitSeconds = [int]$env:FIXTURE_TIMEOUT_UNIT")
    script = replace_once(script, "$MinFreeBytes = 53687091200", "$MinFreeBytes = 1")
    write(ops / "oracle_author_test_run.ps1", script)
    # A production-looking package the child must never see.
    write(repo / "src/weather/__init__.py", "raise ImportError('production weather imported')\n")
    set_memory(repo, 10)

    venv.EnvBuilder(with_pip=False).create(oracle)
    write(oracle / "Lib/site-packages/pytest/__init__.py", STUB_PYTEST)

    write(cut / "H1-manifest.json", json.dumps({"cut": "fixture"}))
    write(cut / "oracle-repo/tests/test_alpha.py", "def test_one():\n    assert True\n")
    write(cut / "oracle-repo/tests/test_beta.py", "def test_two():\n    assert True\n")
    write(cut / "oracle-repo/src/weather/__init__.py", "ORACLE = True\n")
    return dict(repo=repo, cut=cut, logs=logs, oracle=oracle, mutex=mutex, tmp=tmp_path,
                python=oracle / "Scripts/python.exe",
                manifest_sha=hashlib.sha256((cut / "H1-manifest.json").read_bytes()).hexdigest())


def set_memory(repo, percent):
    write(repo / "data/logs/memory_commit_guard_status.json", json.dumps({"commit_percent": percent}))


def run(fx, tests="tests/test_alpha.py", *, now=ADMITTED, mode="pass", unit=60, timeout=180, **params):
    (fx["oracle"] / "mode.txt").write_text(mode)
    params.setdefault("PythonPath", fx["python"])
    params.setdefault("ForbiddenRoot", str(fx["tmp"] / "worktrees"))
    arguments = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                 str(fx["repo"] / "scripts/ops/oracle_author_test_run.ps1"), "-CutDir", str(fx["cut"]),
                 "-LogDir", str(fx["logs"]), "-TestPath", tests]
    for name, item in params.items():
        arguments += ["-" + name] if item is True else ["-" + name, str(item)]
    env = {**os.environ, "FIXTURE_UTC_NOW": now, "FIXTURE_TIMEOUT_UNIT": str(unit),
           # Operator variables that must never reach the child.
           "ORACLE_FIXTURE_SECRET": "operator-only", "PYTHONPATH": str(fx["repo"] / "src"),
           "PYTEST_ADDOPTS": "-p fixture_evil_plugin", "PYTEST_PLUGINS": "fixture_evil_plugin"}
    before = set(fx["logs"].glob("*.receipt.json")) if fx["logs"].exists() else set()
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, env=env, cwd=fx["tmp"])
    after = set(fx["logs"].glob("*.receipt.json")) if fx["logs"].exists() else set()
    new = sorted(after - before)
    receipt = json.loads(new[0].read_text(encoding="utf-8")) if len(new) == 1 else None
    return result.returncode, result.stdout + result.stderr, receipt


def records(fx):
    path = fx["oracle"] / "record.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def lease_is_free(fx):
    lock = fx["repo"] / "data/logs/heavy_workload.lock"
    with open(lock, "r+b"):        # the owner holds it with FileShare.Read only
        return True


def alive(pid):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259                              # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def inside(child, parent):
    child, parent = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
    return child == parent or child.startswith(parent + os.sep)


def test_isolated_leased_run_passes_with_basetemp_receipt_and_release(fx):
    code, log, receipt = run(fx, "tests/test_alpha.py;tests/test_beta.py::test_two", ExpectedManifestSha256=fx["manifest_sha"],
                             Verbosity="verbose", FailFast=True, Keyword="one or two", Durations=5)
    assert code == 0, log
    [child] = records(fx)
    repo_dir = fx["cut"] / "oracle-repo"
    argv = child["argv"]
    assert argv[:2] == ["-p", "no:cacheprovider"]
    assert f"--rootdir={repo_dir}" in argv and f"--confcutdir={repo_dir}" in argv
    assert argv[-2:] == ["tests/test_alpha.py", "tests/test_beta.py::test_two"]
    assert {"-v", "-x", "--durations=5", "--tb=short"} <= set(argv) and argv[argv.index("-k") + 1] == "one or two"
    # Isolated, site-free, bytecode-free; nothing from the production root on sys.path or imported.
    assert child["isolated"] == 1 and child["no_site"] == 1 and child["dont_write_bytecode"]
    assert not any(inside(p, fx["repo"]) for p in child["path"])
    assert inside(child["weather"], repo_dir / "src")
    assert os.path.normcase(child["cwd"]) == os.path.normcase(str(repo_dir))
    # Allowlisted environment: no operator variables, autoload off, temp and home in the run scratch.
    env = {k.upper(): v for k, v in child["env"].items()}
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    for name in ("ORACLE_FIXTURE_SECRET", "PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "FIXTURE_UTC_NOW", "PSMODULEPATH"):
        assert name not in env, name
    assert inside(env["TEMP"], fx["logs"]) and inside(env["USERPROFILE"], fx["logs"])
    # --basetemp was fresh, outside the cut, and deleted afterwards.
    assert inside(child["basetemp"], fx["logs"]) and not Path(child["basetemp"]).exists()
    assert not list(fx["logs"].glob("*.scratch"))
    assert not list(fx["cut"].rglob("__pycache__"))
    assert receipt["status"] == "PASSED" and receipt["exit_code"] == 0
    assert receipt["cut_manifest"]["sha256"] == fx["manifest_sha"]
    assert receipt["lease"]["released"] is True and receipt["lease"]["workload"].startswith("oracle_author_tests_")
    assert receipt["scratch_deleted"] is True and receipt["run_as"] == "operator"
    assert receipt["timeout_seconds"] == 900 and receipt["pytest"]["hard_stop"] is False
    assert receipt["cut_fingerprint_before"]["sha256"] == receipt["cut_fingerprint_after"]["sha256"]
    assert receipt["probe"]["guarded"]["maker_core"] is None
    assert set(receipt["durations_seconds"]) >= {"probe", "pytest", "fingerprint_before", "fingerprint_after", "total"}
    assert lease_is_free(fx)


def test_failed_tests_pass_their_exit_code_through(fx):
    code, log, receipt = run(fx, mode="fail")
    assert code == 1, log
    assert receipt["status"] == "FAILED" and receipt["lease"]["released"] is True
    assert lease_is_free(fx)


@pytest.mark.parametrize("now, window", [
    ("2026-10-13T16:30:00Z", "protected_graded_1200_1800"),       # 12:30 Toronto
    ("2026-10-13T23:00:00Z", "protected_near_close_1800_0030"),   # 19:00
    ("2026-10-13T04:10:00Z", "protected_near_close_1800_0030"),   # 00:10
    ("2026-10-13T13:30:00Z", "outside_0030_0900"),                # 09:30
])
def test_protected_and_outside_windows_are_refused(fx, now, window):
    code, log, receipt = run(fx, now=now)
    assert code == 64, log
    assert receipt["status"] == "REFUSED" and receipt["window"] == window and receipt["lease"] is None
    assert not records(fx)


def test_too_little_time_before_0855_is_refused_and_the_budget_is_capped(fx):
    code, log, receipt = run(fx, now="2026-10-13T12:54:30Z")      # 08:54:30
    assert code == 64 and "08:55" in receipt["reason"], log
    code, log, receipt = run(fx, now="2026-10-13T12:50:00Z")      # 08:50 leaves 300 s of the 900 s default
    assert code == 0, log
    assert receipt["timeout_seconds"] == 300


@pytest.mark.parametrize("bad", [
    "../outside.py",
    "tests/../../H1-manifest.json",
    "tests\\..\\test_alpha.py",
    "./tests/test_alpha.py",
    "tests/missing.py",
    "tests/test_alpha.py::-p",
    "\\\\server\\share\\t.py",
    "OUTSIDE",
])
def test_test_paths_must_stay_inside_the_cut_repository(fx, bad):
    if bad == "OUTSIDE":
        outside = fx["tmp"] / "elsewhere/test_x.py"
        write(outside, "def test_x():\n    pass\n")
        bad = str(outside)
    code, log, receipt = run(fx, bad)
    assert code == 64, log
    assert receipt["status"] == "REFUSED" and receipt["lease"] is None
    assert not records(fx)


def test_absolute_test_path_inside_the_cut_is_relativized(fx):
    code, log, _ = run(fx, str(fx["cut"] / "oracle-repo/tests/test_alpha.py") + "::test_one")
    assert code == 0, log
    assert records(fx)[0]["argv"][-1] == "tests/test_alpha.py::test_one"


@pytest.mark.parametrize("where", ["production", "cut", "forbidden"])
def test_interpreter_must_be_a_dedicated_venv_outside_every_clone(fx, where):
    params = {}
    if where == "forbidden":
        params["ForbiddenRoot"] = f"{fx['tmp'] / 'worktrees'};{fx['oracle']}"
        python = fx["python"]
    else:
        python = (fx["repo"] if where == "production" else fx["cut"]) / "venv/Scripts/python.exe"
        python.parent.mkdir(parents=True)
        shutil.copy2(fx["python"], python)
    code, log, receipt = run(fx, PythonPath=python, **params)
    assert code == 64, log
    assert "interpreter" in receipt["reason"] and not records(fx)


def test_hard_timeout_kills_the_child_tree_and_releases_the_lease(fx):
    code, log, receipt = run(fx, mode="hang", unit=3, TimeoutMinutes=1)
    assert code == 124, log
    assert receipt["status"] == "TIMED_OUT" and receipt["pytest"]["hard_stop"] is True
    hang = json.loads((fx["oracle"] / "hang.json").read_text())
    deadline = time.monotonic() + 10
    while (alive(hang["pid"]) or alive(hang["worker_pid"])) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not alive(hang["pid"]) and not alive(hang["worker_pid"])
    assert receipt["lease"]["released"] is True and receipt["scratch_deleted"] is True
    assert lease_is_free(fx)


def test_a_run_that_writes_into_the_cut_is_cut_modified(fx):
    code, log, receipt = run(fx, mode="write_cut")
    assert code == 65, log
    assert receipt["status"] == "CUT_MODIFIED"
    assert receipt["cut_changes"]["added"] == ["oracle-repo\\planted.txt"]


def test_a_junction_inside_the_cut_is_refused(fx):
    target = fx["tmp"] / "elsewhere"
    target.mkdir()
    link = fx["cut"] / "oracle-repo/linked"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    assert made.returncode == 0, made.stdout + made.stderr
    code, log, receipt = run(fx)
    assert code == 64, log
    assert "reparse" in receipt["reason"] and receipt["lease"] is None and not records(fx)


def test_manifest_binding_mismatch_is_refused(fx):
    code, log, receipt = run(fx, ExpectedManifestSha256="0" * 64)
    assert code == 64, log
    assert receipt["cut_manifest"]["sha256"] == fx["manifest_sha"] and not records(fx)


def test_memory_pressure_is_refused_before_the_lease(fx):
    set_memory(fx["repo"], 75)
    code, log, receipt = run(fx)
    assert code == 64, log
    assert "memory" in receipt["reason"] and receipt["lease"] is None


def test_a_busy_lease_is_reported_and_runs_nothing(fx):
    holder, release = fx["tmp"] / "holder.ps1", fx["tmp"] / "release.flag"
    write(holder, HOLDER.format(admission=fx["repo"] / "scripts/ops/workload_admission.ps1", repo=fx["repo"], release=release))
    process = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-File", str(holder)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert process.stdout.readline().strip() == "ACQUIRED"
        code, log, receipt = run(fx)
        assert code == 75, log
        assert receipt["status"] == "LEASE_BUSY" and not records(fx)
    finally:
        release.write_text("go")
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
