"""Native launcher tests; all files/processes belong to disposable fixtures.

The real wrapper and native Job/lease helpers run in a temporary Git repository.
Only the fixture clock, fixture host assignment and mutex namespace change.
The outer workstation-heavy wrapper still owns the real workstation mutex/Job.
A tiny child isolates launcher behavior; archive byte preservation has separate tests.
"""

import ctypes
import hashlib
import json
import os
import re
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
p.add_argument('command', choices=['stage', 'transfer'])
for key in ('production-repo-root', 'request', 'request-sha256', 'output-root', 'source-git-sha'):
    p.add_argument('--' + key)
a = p.parse_args()
assert Path(__file__).stem == ('production_cold_archive_transfer' if a.command == 'transfer' else 'production_cold_archive_stage_cli')
out = Path(a.output_root)
assert os.environ['WEATHER_PRODUCTION_ARCHIVE_SOURCE_ROOT'] == str(Path.cwd())
assert int(os.environ['WEATHER_PRODUCTION_ARCHIVE_OWNER_PID']) > 0
assert os.environ['WEATHER_PRODUCTION_ARCHIVE_DEADLINE_UTC']
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
          'request_sha256': a.request_sha256, 'deleted_files': 0, 'reclaimed_bytes': 0,
          'cleanup_eligible': False, 'source_retained': True, 'upload_performed': False,
          'logical_source_bytes': 4096, 'source_file_count': 1, 'chunk_id': 'chunk-00000',
          'core_receipt_sha256': 'a' * 64,
          'execution_host_id': json.loads(Path('config/international_live_execution_host.json').read_text())['dedicated_capture_execution_host_id']}
if mode == 'malformed_receipt': result.pop('core_receipt_sha256')
if mode == 'claim_upload': result['upload_performed'] = True
if a.command == 'transfer':
    result.pop('core_receipt_sha256', None)
    result.pop('logical_source_bytes')
    result.pop('source_file_count')
    result.update(upload_performed=True, independent_download=True, archive_id='archive-fixture',
                  ciphertext_bytes=6144, crypt_receipt_sha256='b' * 64, transport_receipt_sha256='c' * 64)
    if mode.startswith('missing_'): result.pop(mode.removeprefix('missing_'))
    if mode == 'false_independent_download': result['independent_download'] = False
    if mode == 'false_upload': result['upload_performed'] = False
    if mode == 'claim_deletion': result['deleted_files'] = 1
    if mode == 'claim_reclaim': result['reclaimed_bytes'] = 4096
    if mode == 'claim_cleanup': result['cleanup_eligible'] = True
    if mode == 'malformed_hash': result['crypt_receipt_sha256'] = 'not-a-sha256'
    if mode == 'string_ciphertext_bytes': result['ciphertext_bytes'] = '6144'
    if mode == 'string_independent_download': result['independent_download'] = 'True'
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
    admission = admission.replace("Global\\WeatherProjectHeavyWorkloadV1", "Local\\ArchiveFixture-" + uuid.uuid4().hex)
    admission += "\nfunction Get-WeatherHeavyWorkloadPolicyWindow { return 'fixture-clock-only' }\n"
    (scripts / "workload_admission.ps1").write_text(admission, encoding="utf-8")
    wrapper = repo_path("scripts/ops/production_cold_archive_run.ps1").read_text(encoding="utf-8-sig")
    fixture_clock = getattr(request, "param", None)
    wrapper = replace_once(wrapper,
        "$localNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)",
        ("$localNow = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddDays(1).AddHours(1), [DateTimeKind]::Unspecified)"
         if fixture_clock is None else f"$localNow = [DateTime]::SpecifyKind([DateTime]'{fixture_clock}', [DateTimeKind]::Unspecified)"))
    wrapper = replace_once(wrapper, "$deadline = [DateTime]::UtcNow.AddSeconds(",
        "$windowEnd = [DateTime]::UtcNow.AddHours(1)\n$deadline = [DateTime]::UtcNow.AddSeconds(")
    wrapper = replace_once(wrapper, "try {\n    # Identity, time and live lease",
        "try {\n    $deadline = [DateTime]::UtcNow.AddSeconds(4)\n    # Identity, time and live lease")
    wrapper_path = scripts / "production_cold_archive_run.ps1"
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
    (package / "production_cold_archive_stage_cli.py").write_text(CHILD)
    (package / "production_cold_archive_transfer.py").write_text(CHILD)
    (source / "tracked.txt").write_text("original")
    (source / ".gitignore").write_text("__pycache__/\n")
    command("git", "init", str(source))
    command("git", "-C", str(source), "add", ".")
    command("git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgSign=false", "commit", "-m", "Isolated launcher fixture")
    head = command("git", "-C", str(source), "rev-parse", "HEAD")
    return source, production, wrapper_path, head


def launch(wrapper_fixture, mode, operation=None):
    source, production, wrapper, head = wrapper_fixture
    request = production / "request.json"
    request.write_text(json.dumps({"mode": mode}))
    output_dir = "production_cold_archive_transfer" if operation == "transfer" else "production_cold_archive"
    output = production / "scratch" / output_dir / "attempt"
    arguments = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(wrapper), "-ProductionRepoRoot", str(production), "-RequestPath", str(request),
                 "-RequestSha256", hashlib.sha256(request.read_bytes()).hexdigest(), "-OutputRoot", str(output),
                 "-ExpectedSourceTip", head]
    if operation is not None:
        arguments.extend(["-Operation", operation])
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
    ("failure", False), ("wrong_binding", False), ("source_drift", False), ("request_drift", False), ("hang", False),
    ("malformed_receipt", False), ("claim_upload", False)])
def test_real_wrapper_completion_binding_failure_and_child_tree_teardown(wrapper_fixture, mode, success):
    process, output = launch(wrapper_fixture, mode)
    code, log = finish(process)
    assert (code == 0) is success, log
    path = output / "wrapper-result.json"
    assert path.exists(), log
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    assert (receipt["status"] == "PASS") is success
    assert receipt["teardown_proved"] is True
    if mode in ("malformed_receipt", "claim_upload"):
        assert code == 1
        assert receipt["status"] == "FAILED"
        assert receipt.get("error")
    if success:
        assert receipt["child_result_sha256"] == hashlib.sha256((output / "result.json").read_bytes()).hexdigest()
        assert receipt["source_retained"] is True
        assert receipt["upload_performed"] is receipt["cleanup_eligible"] is False
        assert receipt["logical_source_bytes"] == 4096
        assert receipt["source_file_count"] == 1
        assert receipt["chunk_id"] == "chunk-00000"
        assert receipt["core_receipt_sha256"] == "a" * 64
    if mode == "hang": assert receipt["hard_stop"] is True
    descendant = output / "descendant.json"
    if mode in ("hang", "residual_success"):
        assert descendant.exists(), log
        for pid in json.loads(descendant.read_text()).values():
            assert observe_process_identity(pid)["state"] == "not_found"


@pytest.mark.parametrize("mode,success", [
    ("success", True), ("residual_success", True), ("failure", False),
    ("wrong_binding", False), ("source_drift", False), ("request_drift", False), ("hang", False),
    ("missing_chunk_id", False), ("missing_archive_id", False), ("missing_ciphertext_bytes", False),
    ("missing_crypt_receipt_sha256", False), ("missing_transport_receipt_sha256", False),
    ("missing_independent_download", False), ("false_independent_download", False),
    ("false_upload", False), ("claim_deletion", False), ("claim_reclaim", False), ("claim_cleanup", False),
    ("malformed_hash", False), ("string_ciphertext_bytes", False), ("string_independent_download", False),
])
def test_transfer_requires_verified_upload_and_download_and_retains_sources(wrapper_fixture, mode, success):
    process, output = launch(wrapper_fixture, mode, operation="transfer")
    code, log = finish(process)
    assert (code == 0) is success, log
    path = output / "wrapper-result.json"
    assert path.exists(), log
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    assert (receipt["status"] == "PASS") is success
    assert receipt["teardown_proved"] is True
    assert receipt["source_retained"] is True
    assert receipt["deleted_files"] == receipt["reclaimed_bytes"] == 0
    assert receipt["cleanup_eligible"] is False
    assert receipt["remote_side_effect_possible"] is True
    if success:
        assert receipt["upload_performed"] is receipt["independent_download"] is True
        assert receipt["upload_state"] == "VERIFIED"
        assert receipt["child_result_sha256"] == hashlib.sha256((output / "result.json").read_bytes()).hexdigest()
        assert receipt["chunk_id"] == "chunk-00000"
        assert receipt["archive_id"] == "archive-fixture"
        assert receipt["ciphertext_bytes"] == 6144
        assert receipt["crypt_receipt_sha256"] == "b" * 64
        assert receipt["transport_receipt_sha256"] == "c" * 64
    else:
        assert code == 1
        assert receipt["status"] == "FAILED"
        assert receipt["upload_performed"] is None
        assert receipt["upload_state"] == "UNKNOWN"
        assert receipt.get("error")
    if mode == "hang":
        assert receipt["hard_stop"] is True
    if mode in ("hang", "residual_success"):
        descendant = output / "descendant.json"
        assert descendant.exists(), log
        for pid in json.loads(descendant.read_text()).values():
            assert observe_process_identity(pid)["state"] == "not_found"


@pytest.mark.parametrize("wrapper_fixture", [
    "2026-09-09T00:29:00",
    "2026-09-09T04:45:00",
    "2026-09-09T06:44:00",
    "2026-09-09T09:00:00",
    "2026-09-09T12:00:00",
    "2026-09-09T18:00:00",
], indirect=True)
def test_protected_hours_and_scheduled_tiering_refuse_before_output(wrapper_fixture):
    process, output = launch(wrapper_fixture, "success")
    code, log = finish(process)
    assert code != 0, log
    assert not output.exists(), log
    assert "REFUSED:" in log


def test_busy_shared_fixture_lease_refuses_before_output(wrapper_fixture):
    source = wrapper_fixture[0]
    admission = (source / "scripts/ops/workload_admission.ps1").read_text()
    mutex_name = re.search(r"Local\\ArchiveFixture-[a-f0-9]+", admission).group()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.CreateMutexW(None, False, mutex_name)
    assert handle
    acquired = False
    try:
        assert kernel.WaitForSingleObject(handle, 0) == 0
        acquired = True
        process, output = launch(wrapper_fixture, "success")
        code, log = finish(process)
        assert code != 0, log
        assert not output.exists(), log
        assert "lease is busy" in log
    finally:
        if acquired:
            assert kernel.ReleaseMutex(handle)
        assert kernel.CloseHandle(handle)
