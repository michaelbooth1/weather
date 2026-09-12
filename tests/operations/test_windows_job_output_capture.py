"""Real native pipe, inheritance, and Job lifecycle tests; no Scheduler writes."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/ops/windows_kill_on_close_job.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows output and Job contract")

PRELUDE = r"""
$ErrorActionPreference = 'Stop'
. $env:R1B_HELPER
$job = New-WeatherKillOnCloseJob
$output = $null
$child = $null
$exitCode = $null
$failure = $null
$timedOut = $false
$treeGone = $false
try {
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $env:R1B_TEMP 'stdout.bin'), (Join-Path $env:R1B_TEMP 'stderr.bin'), 4096
    )
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens @(
        '-u', (Join-Path $env:R1B_TEMP 'child script.py')
    )
    $child = Start-WeatherProcessInJob -Job $job -FilePath $env:R1B_PYTHON `
        -ArgumentString $arguments -WorkingDirectory $env:R1B_TEMP -OutputCapture $output
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not $child.HasExited) {
        $output.Drain()
        if ($watch.ElapsedMilliseconds -ge 3000) { $timedOut = $true; break }
        Start-Sleep -Milliseconds 10
        $child.Refresh()
    }
    if (-not $timedOut) { $child.WaitForExit(); $exitCode = $child.ExitCode }
} catch { $failure = $_.Exception.Message }
finally {
    try {
        $job.TerminateAndWait(5000)
        $treeGone = $true
        if ($output) { $output.Complete(2000) }
    } finally {
        $job.Dispose()
        if ($child) { $child.Dispose() }
        if ($output) { $output.Dispose() }
    }
}
[pscustomobject]@{
    exit_code = $exitCode; failure = $failure; timed_out = $timedOut; tree_gone = $treeGone
    completed = if ($output) { $output.Completed } else { $false }
    stdout_seen = if ($output) { $output.StdoutBytesSeen } else { $null }
    stderr_seen = if ($output) { $output.StderrBytesSeen } else { $null }
    stdout_retained = if ($output) { $output.StdoutBytesRetained } else { $null }
    stderr_retained = if ($output) { $output.StderrBytesRetained } else { $null }
    stdout_truncated = if ($output) { $output.StdoutTruncated } else { $false }
    stderr_truncated = if ($output) { $output.StderrTruncated } else { $false }
} | ConvertTo-Json -Compress
"""


def _environment(tmp_path: Path) -> dict[str, str]:
    return {**os.environ, "R1B_HELPER": str(HELPER), "R1B_TEMP": str(tmp_path),
            "R1B_PYTHON": sys.executable}


def _run(tmp_path: Path, script: str, *, env=None) -> dict:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script], cwd=ROOT, env=env or _environment(tmp_path),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("size,code", [(0, 0), (123, 17), (350000, 9)])
def test_output_is_drained_and_retained_without_newline_or_unbounded_growth(tmp_path, size, code):
    (tmp_path / "child script.py").write_text(
        f"import os\nos.write(1, b'o' * {size})\nos.write(2, b'e' * {size + 7})\nos._exit({code})\n"
    )
    result = _run(tmp_path, PRELUDE)
    assert result["failure"] is None
    assert result["exit_code"] == code
    assert result["tree_gone"] and result["completed"] and not result["timed_out"]
    for stream, byte, count in (("stdout", b"o", size), ("stderr", b"e", size + 7)):
        assert result[f"{stream}_seen"] == count
        assert result[f"{stream}_retained"] == min(count, 4096)
        assert result[f"{stream}_truncated"] is (count > 4096)
        assert (tmp_path / f"{stream}.bin").read_bytes() == byte * min(count, 4096)


def test_timeout_kills_writer_and_preserves_partial_stderr(tmp_path):
    (tmp_path / "child script.py").write_text(
        "import os,time\nos.write(2, b'failure before phase logger')\ntime.sleep(120)\n"
    )
    result = _run(tmp_path, PRELUDE)
    assert result["failure"] is None
    assert result["timed_out"] and result["tree_gone"] and result["completed"]
    assert result["exit_code"] is None
    assert (tmp_path / "stderr.bin").read_bytes() == b"failure before phase logger"


def test_missing_executable_keeps_empty_files_and_closes_all_pipe_writers(tmp_path):
    env = _environment(tmp_path)
    env["R1B_PYTHON"] = str(tmp_path / "missing program.exe")
    result = _run(tmp_path, PRELUDE, env=env)
    assert "CreateProcess" in result["failure"]
    assert result["tree_gone"] and result["completed"]
    assert result["stdout_seen"] == result["stderr_seen"] == 0


@pytest.mark.parametrize("bad", ["existing", "same", "relative", "missing_parent", "too_small", "too_large"])
def test_bad_output_targets_and_limits_reject_before_child_start(tmp_path, bad):
    marker = tmp_path / "stdout.bin"
    marker.write_bytes(b"existing evidence")
    result = _run(tmp_path, r"""
$ErrorActionPreference = 'Stop'
. $env:R1B_HELPER
$out = Join-Path $env:R1B_TEMP 'new.bin'
$err = Join-Path $env:R1B_TEMP 'stderr.bin'
$limit = 4096
switch ($env:R1B_BAD) {
    'existing' { $out = Join-Path $env:R1B_TEMP 'stdout.bin' }
    'same' { $err = $out }
    'relative' { $out = 'relative.bin' }
    'missing_parent' { $out = Join-Path $env:R1B_TEMP 'missing/new.bin' }
    'too_small' { $limit = 1023 }
    'too_large' { $limit = 8388609 }
}
try {
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new($out, $err, $limit)
    $output.Dispose()
    throw 'Invalid output capture accepted'
} catch {
    if ($_.Exception.Message -eq 'Invalid output capture accepted') { throw }
    @{ rejected = $true } | ConvertTo-Json -Compress
}
""", env={**_environment(tmp_path), "R1B_BAD": bad})
    assert result == {"rejected": True}
    assert marker.read_bytes() == b"existing evidence"


def test_output_handles_do_not_accumulate_across_failed_launches(tmp_path):
    result = _run(tmp_path, r"""
$ErrorActionPreference = 'Stop'
. $env:R1B_HELPER
function Attempt([int]$index) {
    $job = New-WeatherKillOnCloseJob
    $output = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new(
        (Join-Path $env:R1B_TEMP ('out' + $index)), (Join-Path $env:R1B_TEMP ('err' + $index)), 4096)
    try {
        try { $null = Start-WeatherProcessInJob -Job $job -FilePath (Join-Path $env:R1B_TEMP 'missing.exe') -ArgumentString 'x' -WorkingDirectory $env:R1B_TEMP -OutputCapture $output }
        catch { if ($_.Exception.Message -notlike '*CreateProcess*') { throw } }
        $job.TerminateAndWait(1000)
        $output.Complete(1000)
    } finally { $job.Dispose(); $output.Dispose() }
}
Attempt 0
[GC]::Collect(); [GC]::WaitForPendingFinalizers()
$before = [Diagnostics.Process]::GetCurrentProcess().HandleCount
foreach ($index in 1..30) { Attempt $index }
[GC]::Collect(); [GC]::WaitForPendingFinalizers()
$after = [Diagnostics.Process]::GetCurrentProcess().HandleCount
@{ before = $before; after = $after } | ConvertTo-Json -Compress
""")
    assert result["after"] <= result["before"] + 3


def test_restricted_handle_list_excludes_an_ambient_inheritable_event(tmp_path):
    (tmp_path / "child script.py").write_text(
        "import ctypes,os\nk=ctypes.WinDLL('kernel32',use_last_error=True)\n"
        "k.SetEvent.argtypes=[ctypes.c_void_p]\n"
        "result=k.SetEvent(int(os.environ['R1B_EVENT']))\n"
        "os.write(1,str(result).encode())\n"
    )
    preamble = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class R1BHandle {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool SetHandleInformation(IntPtr handle, UInt32 mask, UInt32 flags);
}
'@
$ambient = [Threading.EventWaitHandle]::new($false, [Threading.EventResetMode]::ManualReset)
$raw = $ambient.SafeWaitHandle.DangerousGetHandle()
if (-not [R1BHandle]::SetHandleInformation($raw, 1, 1)) { throw 'Fixture handle not inheritable' }
$env:R1B_EVENT = $raw.ToInt64().ToString()
"""
    # The normal capture result is suppressed; assert the ambient event itself.
    script = preamble + "try {\n$null = & {\n" + PRELUDE + r"""
}
@{ signaled = $ambient.WaitOne(0) } | ConvertTo-Json -Compress
} finally { $ambient.Dispose() }
"""
    assert _run(tmp_path, script) == {"signaled": False}
    assert (tmp_path / "stdout.bin").read_bytes() == b"0"


def test_launcher_death_kills_child_and_grandchild_with_redirected_output(tmp_path):
    (tmp_path / "child script.py").write_text(
        "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],"
        "creationflags=subprocess.CREATE_NO_WINDOW)\n"
        "Path('descendants.json').write_text(json.dumps([os.getpid(),p.pid]))\n"
        "os.write(2,b'partial before parent death')\ntime.sleep(120)\n"
    )
    wrapper = PRELUDE.replace("3000", "120000")
    process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", wrapper], cwd=ROOT, env=_environment(tmp_path),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handles = []
    try:
        deadline = time.monotonic() + 15
        marker = tmp_path / "descendants.json"
        stderr = tmp_path / "stderr.bin"
        while not (marker.exists() and stderr.exists() and stderr.stat().st_size):
            assert process.poll() is None, process.communicate(timeout=5)
            assert time.monotonic() < deadline
            time.sleep(0.05)
        for pid in json.loads(marker.read_text()):
            handle = kernel.OpenProcess(0x00100000, False, pid)
            assert handle
            handles.append(handle)
            assert kernel.WaitForSingleObject(handle, 0) == 258
        process.kill()
        process.communicate(timeout=10)
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 5000) == 0
        assert stderr.read_bytes() == b"partial before parent death"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        for handle in handles:
            kernel.CloseHandle(handle)
