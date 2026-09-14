"""Actual Windows Job, memory limit, output and parent-death fault tests."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows Job; portable evidence checks run on both platforms")
HELPER = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "windows_kill_on_close_job.ps1"


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def script(tmp_path, body):
    target = tmp_path / "native-fixture.ps1"
    target.write_text("$ErrorActionPreference = 'Stop'\n"
                      + "$python = " + ps_literal(sys.executable) + "\n"
                      + "$root = " + ps_literal(tmp_path) + "\n"
                      + ". " + ps_literal(HELPER) + "\n" + body, encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(target)]


def run(tmp_path, body, *, timeout=30):
    result = subprocess.run(script(tmp_path, body), cwd=tmp_path, capture_output=True, timeout=timeout, check=False)
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")
    return result.stdout.decode(errors="replace")


def test_native_pipe_captures_stdout_stderr_and_eof_stdin(tmp_path):
    (tmp_path / "child.py").write_text(
        "import sys\nassert sys.stdin.read() == ''\nprint('stdout fixture')\nprint('stderr fixture', file=sys.stderr)\n",
        encoding="utf-8")
    run(tmp_path, r'''
$job = [Weather.Operations.KillOnCloseJob]::CreateBounded(268435456, 8)
$child = $null
try {
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @('-u', (Join-Path $root 'child.py'))
    $child = $job.StartAssignedCaptured($python, $arguments, $root, (Join-Path $root 'output.log'), 1048576)
    if (-not $child.Process.WaitForExit(10000)) { throw 'native child timeout' }
    if ($child.Process.ExitCode -ne 0) { throw 'native child failed' }
    $job.TerminateAndWait(5000)
    if (-not $child.WaitForCapture(5000) -or $child.OutputExceeded -or $child.CaptureError) { throw 'capture incomplete' }
    $snapshot = $job.Snapshot()
    if ($snapshot.ActiveProcesses -ne 0 -or $snapshot.ProcessIds.Count -ne 0) { throw 'children remain' }
    if ($snapshot.CommitLimitBytes -ne 268435456 -or $snapshot.PeakCommitBytes -le 0) { throw 'missing native memory proof' }
} finally {
    $job.TerminateAndWait(5000)
    if ($child) { [void]$child.WaitForCapture(5000); $child.Dispose() }
    $job.Dispose()
}
''')
    output = (tmp_path / "output.log").read_text()
    assert "stdout fixture" in output and "stderr fixture" in output


def test_native_output_flood_never_grows_retained_log_past_cap(tmp_path):
    (tmp_path / "child.py").write_text("import os, time\nwhile True: os.write(1, b'x' * 8192)\n", encoding="utf-8")
    run(tmp_path, r'''
$job = [Weather.Operations.KillOnCloseJob]::CreateBounded(268435456, 8)
$child = $null
try {
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @('-u', (Join-Path $root 'child.py'))
    $child = $job.StartAssignedCaptured($python, $arguments, $root, (Join-Path $root 'output.log'), 4096)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while (-not $child.OutputExceeded -and $clock.Elapsed.TotalSeconds -lt 5) { Start-Sleep -Milliseconds 10 }
    if (-not $child.OutputExceeded) { throw 'output violation not observed' }
    $job.TerminateAndWait(5000)
    if (-not $child.WaitForCapture(5000)) { throw 'output pipe did not close' }
    if ($job.Snapshot().ProcessIds.Count -ne 0) { throw 'children survive output abort' }
} finally {
    $job.TerminateAndWait(5000)
    if ($child) { [void]$child.WaitForCapture(5000); $child.Dispose() }
    $job.Dispose()
}
''')
    assert (tmp_path / "output.log").stat().st_size == 4096


def test_native_job_denies_aggregate_commit_above_its_limit(tmp_path):
    (tmp_path / "child.py").write_text(
        "import ctypes\nk = ctypes.WinDLL('kernel32', use_last_error=True)\n"
        "k.VirtualAlloc.restype = ctypes.c_void_p\n"
        "value = k.VirtualAlloc(None, 268435456, 0x3000, 4)\n"
        "print('denied' if value is None else 'unexpected allocation', flush=True)\n"
        "raise SystemExit(0 if value is None else 3)\n", encoding="utf-8")
    run(tmp_path, r'''
$job = [Weather.Operations.KillOnCloseJob]::CreateBounded(67108864, 8)
$child = $null
try {
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @('-u', (Join-Path $root 'child.py'))
    $child = $job.StartAssignedCaptured($python, $arguments, $root, (Join-Path $root 'output.log'), 4096)
    if (-not $child.Process.WaitForExit(10000) -or $child.Process.ExitCode -ne 0) { throw 'allocation fixture failed' }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        $snapshot = $job.Snapshot()
        if ($snapshot.NativeLimitExceeded) { break }
        Start-Sleep -Milliseconds 10
    } while ($clock.Elapsed.TotalSeconds -lt 2)
    if (-not $snapshot.NativeLimitExceeded -or $snapshot.PeakCommitBytes -gt 67108864) { throw 'native cap proof absent' }
} finally {
    $job.TerminateAndWait(5000)
    if ($child) { [void]$child.WaitForCapture(5000); $child.Dispose() }
    $job.Dispose()
}
''')
    assert "denied" in (tmp_path / "output.log").read_text()


def alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        assert ctypes.get_last_error() in {87, 1168}
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def test_parent_death_kills_child_and_grandchild_in_native_job(tmp_path):
    (tmp_path / "child.py").write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path('grandchild.txt').write_text(str(child.pid))\ntime.sleep(60)\n", encoding="utf-8")
    body = r'''
$job = [Weather.Operations.KillOnCloseJob]::CreateBounded(268435456, 8)
$arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @('-u', (Join-Path $root 'child.py'))
$child = $job.StartAssignedCaptured($python, $arguments, $root, (Join-Path $root 'output.log'), 4096)
[IO.File]::WriteAllText((Join-Path $root 'child.txt'), [string]$child.Process.Id)
Start-Sleep -Seconds 60
'''
    wrapper = subprocess.Popen(script(tmp_path, body), cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    children = []
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / "grandchild.txt").exists() and time.monotonic() < deadline:
            assert wrapper.poll() is None, "native wrapper failed before parent-death fixture"
            time.sleep(0.02)
        for name in ("child.txt", "grandchild.txt"):
            children.append(int((tmp_path / name).read_text()))
        assert all(alive(pid) for pid in children)
        wrapper.terminate()
        wrapper.wait(timeout=5)
        deadline = time.monotonic() + 5
        while any(alive(pid) for pid in children) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(alive(pid) for pid in children), "native Job descendants survived wrapper death"
    finally:
        if wrapper.poll() is None:
            wrapper.terminate()
            wrapper.wait(timeout=5)
