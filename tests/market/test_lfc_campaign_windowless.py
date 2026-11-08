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
    env = dict(os.environ)
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
    child = subprocess.Popen(argv(pythonw, launcher, release))
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
