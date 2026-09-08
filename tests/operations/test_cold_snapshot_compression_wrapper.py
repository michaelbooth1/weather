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
p.add_argument('--verify-retained', action='store_true')
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
          'owner_approved_exception': os.environ.get('WEATHER_COLD_SNAPSHOT_COMPRESSION_OWNER_APPROVED_EXCEPTION', ''),
          'request_sha256': a.request_sha256, 'apply': a.apply, 'deleted_files': 0, 'reclaimed_bytes': 0, 'cleanup_eligible': False,
          'execution_host_id': json.loads(Path('config/international_live_execution_host.json').read_text())['dedicated_capture_execution_host_id']}
if a.verify_retained:
    result.update(verify_retained=mode != 'wrong_verify', source_files_changed=1 if mode == 'verify_write' else 0,
                  verified_reclaimed_bytes=123)
    if mode == 'verify_reclaim': result['reclaimed_bytes'] = 1
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
def wrapper_fixture(tmp_path, request):
    source = tmp_path / "source checkout"
    production = tmp_path / "fixture production"
    scripts = source / "scripts/ops"
    scripts.mkdir(parents=True)
    production.mkdir()
    venv.EnvBuilder(with_pip=False).create(production / "venv")
    for name in ("windows_kill_on_close_job.ps1", "training_window_contract.ps1"):
        shutil.copy2(repo_path("scripts/ops", name), scripts / name)
    admission = repo_path("scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    admission = admission.replace("Global\\WeatherProjectHeavyWorkloadV1", "Local\\ColdSnapshotFixture-" + uuid.uuid4().hex)
    admission += "\nfunction Get-WeatherHeavyWorkloadPolicyWindow { return 'fixture-clock-only' }\n"
    (scripts / "workload_admission.ps1").write_text(admission, encoding="utf-8")
    wrapper = repo_path("scripts/ops/cold_snapshot_compression_run.ps1").read_text(encoding="utf-8-sig")
    fixture_clock = getattr(request, "param", None)
    wrapper = replace_once(wrapper,
        "$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)",
        ("$localNow = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddDays(1).AddHours(1), [DateTimeKind]::Unspecified)"
         if fixture_clock is None else f"$localNow = [DateTime]::SpecifyKind([DateTime]'{fixture_clock}', [DateTimeKind]::Unspecified)"))
    wrapper = replace_once(wrapper, "$deadline = [DateTime]::UtcNow.AddSeconds(",
        "$windowEnd = [DateTime]::UtcNow.AddHours(1)\n$deadline = [DateTime]::UtcNow.AddSeconds(")
    wrapper = replace_once(wrapper, "try {\n    # Identity, time and live lease",
        "try {\n    $deadline = [DateTime]::UtcNow.AddSeconds(4)\n    # Identity, time and live lease")
    wrapper_path = scripts / "cold_snapshot_compression_run.ps1"
    wrapper_path.write_text(wrapper, encoding="utf-8")
    assignment = json.loads(repo_path("config/international_live_execution_host.json").read_text())
    assignment.update(dedicated_capture_execution_host_id=assignment["active_portable_execution_host_id"],
                      active_portable_execution_host_id=None, active_portable_execution_principal_id=None,
                      assignment_status="UNASSIGNED")
    (source / "config").mkdir()
    (source / "config/international_live_execution_host.json").write_text(json.dumps(assignment))
    (production / "config").mkdir()
    (production / "config/international_live_execution_host.json").write_text(json.dumps(assignment))
    package = source / "src/weather/operations"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "cold_snapshot_compression.py").write_text(CHILD)
    (source / "tracked.txt").write_text("original")
    (source / ".gitignore").write_text("__pycache__/\n")
    command("git", "init", str(source))
    command("git", "-C", str(source), "add", ".")
    command("git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-m", "Isolated launcher fixture")
    head = command("git", "-C", str(source), "rev-parse", "HEAD")
    return source, production, wrapper_path, head


def launch(wrapper_fixture, mode, *, apply=False, verify=False, plan_receipt=None, exception=""):
    source, production, wrapper, head = wrapper_fixture
    request = production / "request.json"
    request.write_text(json.dumps({"mode": mode}))
    output = production / "scratch/cold_snapshot_compression" / ("apply" if plan_receipt else "attempt")
    arguments = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(wrapper), "-ProductionRepoRoot", str(production), "-RequestPath", str(request),
                 "-RequestSha256", hashlib.sha256(request.read_bytes()).hexdigest(), "-OutputRoot", str(output),
                 "-ExpectedSourceTip", head]
    if exception: arguments += ["-OwnerApprovedException", exception]
    if apply: arguments.append("-Apply")
    if verify: arguments.append("-VerifyRetained")
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


@pytest.mark.parametrize("apply", [False, True])
def test_wrapper_passes_explicit_apply_without_archive_or_delete_authority(wrapper_fixture, apply):
    process, output = launch(wrapper_fixture, "success", apply=apply)
    code, log = finish(process)
    assert code == 0, log
    receipt = json.loads((output / "wrapper-result.json").read_text())
    assert receipt["apply"] is apply and receipt["cleanup_eligible"] is False


@pytest.mark.parametrize("wrapper_fixture,exception,success", [
    ("2026-09-08T12:00:00", "OWNER_APPROVED_STORAGE_RECOVERY_20260908", True),
    ("2026-09-08T12:00:00", "", False),
    ("2026-09-08T12:00:00", "wrong-token", False),
    ("2026-09-08T18:00:00", "OWNER_APPROVED_STORAGE_RECOVERY_20260908", False),
    ("2026-09-09T12:00:00", "OWNER_APPROVED_STORAGE_RECOVERY_20260908", False),
], indirect=["wrapper_fixture"])
def test_dated_storage_exception_is_explicit_and_expires(wrapper_fixture, exception, success):
    process, output = launch(wrapper_fixture, "success", exception=exception)
    code, log = finish(process)
    assert (code == 0) is success, log
    if success:
        receipt = json.loads((output / "wrapper-result.json").read_text())
        assert receipt["owner_approved_exception"] == exception
        assert receipt["teardown_proved"] is True
        child = json.loads((output / "result.json").read_text())
        assert child["owner_approved_exception"] == exception
    else:
        assert not output.exists(), log



@pytest.mark.parametrize("mode,success", [
    ("success", True), ("wrong_verify", False), ("verify_write", False), ("verify_reclaim", False),
])
def test_wrapper_binds_read_only_verification_and_prior_savings(wrapper_fixture, mode, success):
    process, output = launch(wrapper_fixture, mode, verify=True)
    code, log = finish(process)
    assert (code == 0) is success, log
    receipt = json.loads((output / "wrapper-result.json").read_text())
    assert receipt["teardown_proved"] is True
    if success:
        assert receipt["verify_retained"] is True and receipt["apply"] is False
        assert receipt["reclaimed_bytes"] == receipt["source_files_changed"] == 0
        assert receipt["verified_reclaimed_bytes"] == 123


def test_wrapper_refuses_verification_combined_with_apply_before_attempt_creation(wrapper_fixture):
    process, output = launch(wrapper_fixture, "success", apply=True, verify=True)
    code, log = finish(process)
    assert code != 0 and not output.exists(), log
