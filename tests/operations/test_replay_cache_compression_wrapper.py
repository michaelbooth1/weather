"""Native launcher tests; all files/processes belong to disposable fixtures.

The real wrapper and native Job/lease helpers run in a temporary Git repository.
Only the fixture clock, fixture host assignment and mutex namespace change.
The outer workstation-heavy wrapper still owns the real workstation mutex/Job.
A tiny child isolates launcher behavior; native compression has separate tests.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import venv

import pytest

from weather.paths import repo_path
from weather.operations.process_lock_identity import observe_process_identity


pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows PowerShell/Job/lease orchestration")

CHILD = '''
import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
for key in ('production-repo-root', 'request', 'request-sha256', 'output-root', 'source-git-sha',
            'plan-receipt', 'plan-receipt-sha256'): p.add_argument('--' + key)
p.add_argument('--apply', action='store_true')
a = p.parse_args()
out = Path(a.output_root)
mode = json.loads(Path(a.request).read_text())['mode']
if mode in ('hang', 'residual_success'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    (out / 'descendant.json').write_text(json.dumps({'pid': child.pid, 'worker_pid': os.getpid()}))
if mode == 'hang': time.sleep(300)
if mode == 'failure': raise SystemExit(7)
if mode == 'request_drift': Path(a.request).write_text('{}')
if mode == 'source_drift': Path('tracked.txt').write_text('changed')
result = {'status': 'PASS', 'source_git_sha': 'd' * 40 if mode == 'wrong_binding' else a.source_git_sha,
          'request_sha256': a.request_sha256, 'apply': a.apply, 'deleted_files': 0, 'reclaimed_bytes': 0}
(out / 'result.json').write_text(json.dumps(result))
'''


def command(*args, cwd=None):
    result = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def replace_once(text, before, after):
    assert text.count(before) == 1
    return text.replace(before, after)


@pytest.fixture
def wrapper_fixture(tmp_path):
    source = tmp_path / "source checkout"
    production = tmp_path / "fixture production"
    scripts = source / "scripts/ops"
    scripts.mkdir(parents=True)
    production.mkdir()
    venv.EnvBuilder(with_pip=False).create(production / "venv")
    for name in ("windows_kill_on_close_job.ps1", "training_window_contract.ps1"):
        shutil.copy2(repo_path("scripts/ops", name), scripts / name)
    admission = repo_path("scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    admission = admission.replace("Global\\WeatherProjectHeavyWorkloadV1", "Local\\CacheFixture-" + uuid.uuid4().hex)
    admission += "\nfunction Get-WeatherHeavyWorkloadPolicyWindow { return 'fixture-clock-only' }\n"
    (scripts / "workload_admission.ps1").write_text(admission, encoding="utf-8")
    wrapper = repo_path("scripts/ops/replay_cache_compression_run.ps1").read_text(encoding="utf-8-sig")
    wrapper = replace_once(wrapper,
        "$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)",
        "$localNow = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddDays(1).AddHours(1), [DateTimeKind]::Unspecified)")
    wrapper = replace_once(wrapper, "try {\n    # Identity, time and live lease",
        "try {\n    $deadline = [DateTime]::UtcNow.AddSeconds(4)\n    # Identity, time and live lease")
    wrapper_path = scripts / "replay_cache_compression_run.ps1"
    wrapper_path.write_text(wrapper, encoding="utf-8")
    assignment = json.loads(repo_path("config/international_live_execution_host.json").read_text())
    assignment.update(dedicated_capture_execution_host_id=assignment["active_portable_execution_host_id"],
                      active_portable_execution_host_id=None, active_portable_execution_principal_id=None,
                      assignment_status="UNASSIGNED")
    (source / "config").mkdir()
    (source / "config/international_live_execution_host.json").write_text(json.dumps(assignment))
    package = source / "src/weather/operations"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "replay_cache_compression.py").write_text(CHILD)
    (source / "tracked.txt").write_text("original")
    (source / ".gitignore").write_text("__pycache__/\n")
    command("git", "init", str(source))
    command("git", "-C", str(source), "add", ".")
    command("git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-m", "Isolated launcher fixture")
    head = command("git", "-C", str(source), "rev-parse", "HEAD")
    return source, production, wrapper_path, head


def launch(wrapper_fixture, mode, *, apply=False, plan_receipt=None):
    source, production, wrapper, head = wrapper_fixture
    request = production / "request.json"
    request.write_text(json.dumps({"mode": mode}))
    output = production / "scratch/storage_reclaim" / ("apply" if plan_receipt else "attempt")
    arguments = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(wrapper), "-ProductionRepoRoot", str(production), "-RequestPath", str(request),
                 "-RequestSha256", hashlib.sha256(request.read_bytes()).hexdigest(), "-OutputRoot", str(output),
                 "-ExpectedSourceTip", head]
    if apply: arguments.append("-Apply")
    if plan_receipt:
        arguments += ["-PlanReceiptPath", str(plan_receipt), "-PlanReceiptSha256",
                      hashlib.sha256(plan_receipt.read_bytes()).hexdigest()]
    process = subprocess.Popen(arguments, cwd=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process, output


def finish(process):
    try:
        stdout, stderr = process.communicate(timeout=35)
        return process.returncode, stdout + stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("mode,success", [("success", True), ("residual_success", True),
    ("failure", False), ("wrong_binding", False), ("source_drift", False), ("request_drift", False), ("hang", False)])
def test_real_wrapper_completion_binding_failure_and_child_tree_teardown(wrapper_fixture, mode, success):
    process, output = launch(wrapper_fixture, mode)
    code, log = finish(process)
    assert (code == 0) is success, log
    path = output / "wrapper-result.json"
    assert path.exists(), log
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    assert (receipt["status"] == "PASS") is success
    assert receipt["teardown_proved"] is True
    if success:
        assert receipt["child_result_sha256"] == hashlib.sha256((output / "result.json").read_bytes()).hexdigest()
    if mode == "hang": assert receipt["hard_stop"] is True
    descendant = output / "descendant.json"
    if mode in ("hang", "residual_success"):
        assert descendant.exists(), log
        for pid in json.loads(descendant.read_text()).values():
            assert observe_process_identity(pid)["state"] == "not_found"


def test_wrapper_refuses_apply_without_reviewed_plan_before_lease(wrapper_fixture):
    process, output = launch(wrapper_fixture, "success", apply=True)
    code, log = finish(process)
    assert code != 0 and "requires an exact reviewed plan" in log
    assert not output.exists()
    assert not (wrapper_fixture[1] / "data/logs/heavy_workload.lock").exists()


def test_wrapper_passes_exact_reviewed_plan_arguments_with_space_containing_paths(wrapper_fixture):
    process, plan = launch(wrapper_fixture, "success")
    code, log = finish(process)
    assert code == 0, log
    process, output = launch(wrapper_fixture, "success", apply=True, plan_receipt=plan / "wrapper-result.json")
    code, log = finish(process)
    assert code == 0, log
    receipt = json.loads((output / "wrapper-result.json").read_text())
    assert receipt["apply"] is True and receipt["status"] == "PASS"


@pytest.mark.parametrize("hour,reason", [(14, "restricted to 00:30-09:00"),
                                        (5, "reserved for the existing scheduled tiering jobs")])
def test_wrapper_refuses_protected_window_before_any_runtime_write(wrapper_fixture, hour, reason):
    wrapper = wrapper_fixture[2]
    source = wrapper.read_text()
    wrapper.write_text(replace_once(source, ".AddDays(1).AddHours(1)", f".AddDays(1).AddHours({hour})"))
    process, output = launch(wrapper_fixture, "success")
    code, log = finish(process)
    assert code != 0 and reason in log
    assert not output.exists()
    assert not (wrapper_fixture[1] / "data").exists()


def test_wrapper_refuses_wrong_windows_host_before_lease(wrapper_fixture):
    source, production, wrapper, _head = wrapper_fixture
    path = source / "config/international_live_execution_host.json"
    assignment = json.loads(path.read_text())
    assignment["dedicated_capture_execution_host_id"] = "0" * 64
    path.write_text(json.dumps(assignment))
    command("git", "-C", str(source), "add", "config/international_live_execution_host.json")
    command("git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-m", "Wrong-host negative fixture")
    head = command("git", "-C", str(source), "rev-parse", "HEAD")
    process, output = launch((source, production, wrapper, head), "success")
    code, log = finish(process)
    assert code != 0 and "restricted to the assigned dedicated capture host" in log
    assert not output.exists()
    assert not (production / "data").exists()


def test_wrapper_does_not_reuse_or_rewrite_a_spent_attempt(wrapper_fixture):
    process, output = launch(wrapper_fixture, "success")
    code, log = finish(process)
    assert code == 0, log
    original = {path.name: path.read_bytes() for path in output.iterdir()}
    process, output = launch(wrapper_fixture, "success")
    code, log = finish(process)
    assert code != 0 and "spent output attempt" in log
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original


def test_abrupt_wrapper_exit_kills_entire_owned_tree(wrapper_fixture):
    process, output = launch(wrapper_fixture, "hang")
    try:
        deadline = time.monotonic() + 20
        while not (output / "descendant.json").exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                code, log = finish(process)
                pytest.fail(f"fixture did not launch owned descendants: {code} {log}")
            time.sleep(0.05)
        pids = json.loads((output / "descendant.json").read_text())
        process.kill()  # Only the test-owned launcher; its Job must own the rest.
        finish(process)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(observe_process_identity(pid)["state"] != "not_found" for pid in pids.values()):
            time.sleep(0.05)
        assert all(observe_process_identity(pid)["state"] == "not_found" for pid in pids.values())
        assert not (output / "wrapper-result.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            finish(process)
