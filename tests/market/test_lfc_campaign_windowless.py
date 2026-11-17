"""Native windowless launcher with only inert scripts and synthetic releases.

Guards: B058-7 GUI-subsystem launch, exact release binding and child-tree teardown.
No Scheduler, venue, reader, credential, toast or campaign root is accessed.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from weather.market.lfc_recording_io import file_sha
from weather.paths import REPO_ROOT
from tests.native_child_environment import clean_native_environment


def fixture(tmp_path, body):
    root = tmp_path / 'fixture pin'
    ops = root / 'scripts' / 'ops'
    ops.mkdir(parents=True)
    launcher = ops / 'lfc_campaign_windowless.py'
    shutil.copyfile(REPO_ROOT / 'scripts/ops/lfc_campaign_windowless.py', launcher)
    text = launcher.read_text()
    declaration = "STATUS_ROOT = Path(r'C:\\t\\pilot\\status\\control')"
    assert text.count(declaration) == 1
    launcher.write_text(text.replace(declaration, 'STATUS_ROOT = Path(' + repr(str(tmp_path / 'public-status')) + ')'))
    text = launcher.read_text()
    launcher.write_text(text.replace("PRIVATE_LOG_ROOT = Path.home() / '.weather-lfc-20261009' / 'diagnostics'",
        'PRIVATE_LOG_ROOT = Path(' + repr(str(tmp_path / 'private-log')) + ')'))
    (ops / 'lfc_campaign_task.ps1').write_text(body)
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    row = {'schema_version': 'lfc_campaign_release_v0.1', 'task_name': 'WeatherLFCCampaign',
        'root': str(root), 'windowless': {'python': str(pythonw), 'sha256': file_sha(pythonw),
                                        'launcher_sha256': file_sha(launcher)}}
    release = tmp_path / 'release.json'
    release.write_text(json.dumps(row))
    return pythonw, launcher, release, row


def argv(pythonw, launcher, release):
    return [str(pythonw), '-I', str(launcher), '--release', str(release), '--release-sha256', file_sha(release)]


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='Windows GUI-subsystem process')
@pytest.mark.parametrize('changed', ['python', 'launcher', 'root', 'environment', 'receipt_hash'])
def test_windowless_binding_refuses_before_any_wrapper_executes(tmp_path, changed):
    marker = tmp_path / 'must-not-exist'
    pythonw, launcher, release, row = fixture(tmp_path, f"Set-Content -LiteralPath '{marker}' -Value 'ran'")
    if changed == 'python': row['windowless']['sha256'] = 'f' * 64
    if changed == 'launcher': row['windowless']['launcher_sha256'] = 'f' * 64
    if changed == 'root': row['root'] = str(tmp_path / 'different')
    release.write_text(json.dumps(row))
    command = argv(pythonw, launcher, release)
    env = clean_native_environment()
    if changed == 'environment': env['PYTHONPATH'] = 'forbidden-override'
    if changed == 'receipt_hash': command[-1] = 'f' * 64
    child = subprocess.run(command, env=env, timeout=15)
    assert child.returncode == 1 and not marker.exists()
    logs = list((tmp_path / 'public-status').glob('*-launcher-refusals-*.jsonl'))
    assert len(logs) == 1
    rows = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['state'] == 'REFUSED' and rows[0]['exit_code'] == 1
    text = json.dumps(rows)
    assert not any(value in text for value in ('forbidden-override', str(tmp_path), 'release.json', 'pythonw.exe'))
    assert rows[0]['variable_names'] == (['PYTHONPATH'] if changed == 'environment' else [])


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='native kill-on-close job')
def test_killing_windowless_parent_tears_down_its_wrapper_and_grandchild(tmp_path):
    marker = tmp_path / 'owned-pids.json'
    sleeper = tmp_path / 'inert-sleeper.py'
    sleeper.write_text('import time; time.sleep(60)')
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    body = f"""$child=Start-Process -FilePath '{pythonw}' -ArgumentList '"{sleeper}"' -PassThru -WindowStyle Hidden
@{{wrapper=$PID;grandchild=$child.Id}} | ConvertTo-Json -Compress | Set-Content -LiteralPath '{marker}'
Start-Sleep -Seconds 60
"""
    pythonw, launcher, release, _ = fixture(tmp_path, body)
    child = subprocess.Popen(argv(pythonw, launcher, release), env=clean_native_environment())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    from ctypes import wintypes
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD), wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handles = []
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline: time.sleep(.05)
        assert marker.exists() and child.poll() is None
        pids = json.loads(marker.read_text())
        for pid in pids.values():
            handle = kernel.OpenProcess(0x100000 | 1, False, pid)
            assert handle
            handles.append(handle)
        child.kill()
        child.wait(timeout=5)
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
    finally:
        if child.poll() is None: child.kill()
        child.wait(timeout=5)
        for handle in handles:
            if kernel.WaitForSingleObject(handle, 0) != 0: kernel.TerminateProcess(handle, 1)
            kernel.CloseHandle(handle)


def test_private_stderr_rotation_retains_safe_frames_and_hashes_unsafe_text(tmp_path, monkeypatch):
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location('fixture_windowless', REPO_ROOT / 'scripts/ops/lfc_campaign_windowless.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'LOG_BYTES', 1)
    raw = b'  File "C:\\private\\lfc_pair_inventory.py", line 73, in held_inventory\nValueError: token=do-not-store\n'
    module.retain_stderr(io.BytesIO(raw), tmp_path)
    files = list(tmp_path.glob('campaign-child-stderr*.jsonl'))
    assert len(files) == 2
    rows = [json.loads(line) for p in files for line in p.read_bytes().splitlines()]
    assert sum(row['bytes'] for row in rows) == len(raw)
    assert any(row.get('safe_frame', {}).get('function') == 'held_inventory' for row in rows)
    assert any(row.get('exception_type') == 'ValueError' for row in rows)
    assert b'do-not-store' not in b''.join(p.read_bytes() for p in files)
    assert b'private' not in b''.join(p.read_bytes() for p in files)


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='Windows GUI-subsystem process')
def test_windowless_child_stderr_reaches_private_log_with_exit_code(tmp_path):
    pythonw, launcher, release, _ = fixture(tmp_path, "[Console]::Error.WriteLine('ValueError: synthetic-private'); exit 7")
    child = subprocess.run(argv(pythonw, launcher, release), env=clean_native_environment(), timeout=15)
    assert child.returncode == 7
    rows = [json.loads(line) for p in (tmp_path / 'private-log').glob('*.jsonl') for line in p.read_bytes().splitlines()]
    assert rows and any(row.get('exception_type') == 'ValueError' for row in rows)
    assert 'synthetic-private' not in json.dumps(rows)
