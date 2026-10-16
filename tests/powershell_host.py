"""One long-lived Windows PowerShell host for tests that evaluate script logic.

Starting ``powershell.exe`` costs a few hundred milliseconds per call, and a test that
re-runs the same ``Add-Type`` (for example the strict JSON validator in ``status.ps1``)
pays the C# compile again in every child. Tests that only *evaluate* PowerShell
functions or script fragments -- they parse a script, define its functions and print a
JSON result -- do not need a new process for that. They can share one host process per
pytest process and get a fresh runspace per call.

Use this only where process semantics are NOT under test. Exit codes of real scripts,
kill-on-close jobs, timeouts, mutexes and the workload lease, scheduled-task behaviour,
``-File`` startup and anything that inspects its own process must keep a real child
(``subprocess``). Each converted call site says why it qualifies.

Contract of :func:`run_command` (mirrors ``subprocess.run([... '-Command', script])``):

* Every call gets a brand-new runspace from ``InitialSessionState.CreateDefault()``:
  functions, variables, ``global:`` overrides, preference variables, strict mode and
  imported modules never leak between calls.
* The process environment is set to exactly ``env`` (or the caller's ``os.environ``)
  for the call and restored afterwards; the working directory (both the PowerShell
  location and the .NET process directory) is ``cwd`` (or the caller's cwd) and is
  restored afterwards.
* Pipeline output is formatted through ``Out-String -Stream`` and ``Write-Host`` /
  warnings are interleaved into ``stdout`` in emission order; error records go to
  ``stderr``. An uncaught terminating error returns 1; otherwise the code is 1 only
  when the last statement failed (``$?``), as with ``-Command``. A hosted runspace
  swallows ``exit N``, so a script that stops early (``exit`` or a top-level
  ``return``) returns 255 with an explanatory ``stderr``: call sites that depend on an
  exit code must keep a real child.
* Process-wide .NET state is shared: an ``Add-Type`` type compiled by one call is
  visible to the next. Scripts that guard ``Add-Type`` with ``-as [type]`` (as the
  ops scripts do) are unaffected; never convert a test whose assertion depends on a
  type being absent.
* A call that exceeds ``timeout`` kills the host's whole process tree, raises
  :class:`subprocess.TimeoutExpired`, and the next call starts a new host.

Set ``WEATHER_TEST_POWERSHELL_HOST=0`` to run every call as a real child process
instead (same signature, same result type) -- the escape hatch for debugging and for
proving that a converted test passes identically both ways.
"""

from __future__ import annotations

import atexit
import base64
import os
import queue
import secrets
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path


POWERSHELL_EXECUTABLE = "powershell.exe"
DISABLE_ENVIRONMENT_VARIABLE = "WEATHER_TEST_POWERSHELL_HOST"
_NONCE_VARIABLE = "WEATHER_TEST_PSHOST_NONCE"
_LAUNCH_MODULE_PATH_VARIABLE = "WEATHER_TEST_PSHOST_LAUNCH_PSMODULEPATH"

_RUNNER_SOURCE = r"""
using System;
using System.Collections.Generic;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Runtime.InteropServices;
using System.Text;

namespace Weather.Tests
{
    public static class SharedPowerShellHostRunner
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr GetStdHandle(int handle);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetHandleInformation(IntPtr handle, int mask, int flags);

        // Requests arrive on stdin; a grandchild that inherited it could swallow one.
        public static void ProtectStandardInput()
        {
            if (!SetHandleInformation(GetStdHandle(-10), 1, 0))
            {
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            }
        }

        private static string FormatError(ErrorRecord record)
        {
            var text = new StringBuilder();
            text.Append(record.ToString());
            if (record.InvocationInfo != null && !string.IsNullOrEmpty(record.InvocationInfo.PositionMessage))
            {
                text.Append("\n").Append(record.InvocationInfo.PositionMessage);
            }
            text.Append("\n    + CategoryInfo          : ").Append(record.CategoryInfo.ToString());
            text.Append("\n    + FullyQualifiedErrorId : ").Append(record.FullyQualifiedErrorId);
            text.Append("\n");
            return text.ToString();
        }

        public static object[] Run(string script, string location)
        {
            var stdout = new StringBuilder();
            var stderr = new StringBuilder();
            var gate = new object();
            int code = 0;
            var state = InitialSessionState.CreateDefault();
            state.ExecutionPolicy = Microsoft.PowerShell.ExecutionPolicy.Bypass;
            using (var runspace = RunspaceFactory.CreateRunspace(state))
            {
                runspace.Open();
                using (var shell = PowerShell.Create())
                {
                    shell.Runspace = runspace;
                    shell.AddCommand("Set-Location").AddParameter("LiteralPath", location);
                    shell.Invoke();
                    shell.Commands.Clear();
                    if (shell.HadErrors)
                    {
                        foreach (var record in shell.Streams.Error) { stderr.Append(FormatError(record)); }
                        return new object[] { 1, stdout.ToString(), stderr.ToString() };
                    }
                    shell.Streams.ClearStreams();

                    var output = new PSDataCollection<PSObject>();
                    output.DataAdded += (sender, args) =>
                    {
                        lock (gate) { stdout.Append(Convert.ToString(output[args.Index].BaseObject)).Append("\n"); }
                    };
                    shell.Streams.Information.DataAdded += (sender, args) =>
                    {
                        var record = shell.Streams.Information[args.Index];
                        var hostMessage = record.MessageData as HostInformationMessage;
                        lock (gate)
                        {
                            if (hostMessage != null)
                            {
                                stdout.Append(hostMessage.Message);
                                if (hostMessage.NoNewLine != true) { stdout.Append("\n"); }
                            }
                            else
                            {
                                stdout.Append(Convert.ToString(record.MessageData)).Append("\n");
                            }
                        }
                    };
                    shell.Streams.Warning.DataAdded += (sender, args) =>
                    {
                        lock (gate) { stdout.Append("WARNING: ").Append(shell.Streams.Warning[args.Index].Message).Append("\n"); }
                    };
                    shell.Streams.Error.DataAdded += (sender, args) =>
                    {
                        lock (gate) { stderr.Append(FormatError(shell.Streams.Error[args.Index])); }
                    };

                    shell.AddScript(
                        script + "\n$global:WeatherSharedHostLastStatus = $?\n$global:WeatherSharedHostCompleted = $true\n",
                        false);
                    shell.AddCommand("Out-String").AddParameter("Stream", true);
                    try
                    {
                        shell.Invoke(null, output);
                    }
                    catch (RuntimeException failure)
                    {
                        lock (gate) { stderr.Append(FormatError(failure.ErrorRecord)); }
                        code = 1;
                    }

                    if (code == 0)
                    {
                        var session = runspace.SessionStateProxy;
                        object completed = session.GetVariable("WeatherSharedHostCompleted");
                        object lastStatus = session.GetVariable("WeatherSharedHostLastStatus");
                        if (!(completed is bool && (bool)completed))
                        {
                            // A hosted runspace swallows `exit N` (and a top-level `return`):
                            // the code is unknowable here, so fail loudly instead of guessing.
                            lock (gate)
                            {
                                stderr.Append("shared PowerShell host: the script stopped before its end ")
                                    .Append("(exit or top-level return); its exit code is unavailable, ")
                                    .Append("so this call site must use a real powershell.exe child\n");
                            }
                            code = 255;
                        }
                        else if (lastStatus is bool && !(bool)lastStatus)
                        {
                            code = 1;
                        }
                    }
                }
            }
            return new object[] { code, stdout.ToString(), stderr.ToString() };
        }
    }
}
"""

_HOST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$nonce = [Environment]::GetEnvironmentVariable('__NONCE__', 'Process')
$launchModulePath = [Environment]::GetEnvironmentVariable('__LAUNCH_MODULE_PATH__', 'Process')
[Environment]::SetEnvironmentVariable('__NONCE__', $null, 'Process')
[Environment]::SetEnvironmentVariable('__LAUNCH_MODULE_PATH__', $null, 'Process')
$hostModulePath = $env:PSModulePath
Add-Type -TypeDefinition $env:WEATHER_TEST_PSHOST_RUNNER -ReferencedAssemblies @(
    [System.Management.Automation.PSObject].Assembly.Location
)
[Environment]::SetEnvironmentVariable('WEATHER_TEST_PSHOST_RUNNER', $null, 'Process')
[Weather.Tests.SharedPowerShellHostRunner]::ProtectStandardInput()
$utf8 = [Text.UTF8Encoding]::new($false)
$reader = [IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$writer = [IO.StreamWriter]::new([Console]::OpenStandardOutput(), $utf8)
$writer.AutoFlush = $true
$baseline = @{}
foreach ($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {
    $baseline[[string]$entry.Key] = [string]$entry.Value
}
$baseDirectory = [Environment]::CurrentDirectory

function Set-ExactEnvironment([hashtable]$Target) {
    foreach ($name in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
        if (-not $Target.ContainsKey([string]$name)) {
            [Environment]::SetEnvironmentVariable([string]$name, $null, 'Process')
        }
    }
    foreach ($name in $Target.Keys) {
        [Environment]::SetEnvironmentVariable([string]$name, [string]$Target[$name], 'Process')
    }
}

$writer.WriteLine("$nonce READY")
# Request: "<id> <cwd> <environment> <script>", each field base64 UTF-8; the environment
# is NUL-separated NAME=value pairs. Response: "<nonce> <id> <code> <stdout> <stderr>".
while ($null -ne ($line = $reader.ReadLine())) {
    $fields = $line.Split(' ')
    $requestId = $fields[0]
    $result = $null
    try {
        $location = $utf8.GetString([Convert]::FromBase64String($fields[1]))
        $target = @{}
        foreach ($pair in $utf8.GetString([Convert]::FromBase64String($fields[2])).Split([char]0)) {
            if ($pair.Length -eq 0) { continue }
            $split = $pair.IndexOf('=', 1)
            $name = $pair.Substring(0, $split)
            $value = $pair.Substring($split + 1)
            if ($name -ieq 'PSModulePath' -and $value -ceq $launchModulePath) {
                $value = $hostModulePath
            }
            $target[$name] = $value
        }
        Set-ExactEnvironment $target
        [Environment]::CurrentDirectory = $location
        $script = $utf8.GetString([Convert]::FromBase64String($fields[3]))
        $result = [Weather.Tests.SharedPowerShellHostRunner]::Run($script, $location)
    }
    catch {
        $result = @(1, '', ('shared PowerShell host failed: ' + $_.Exception.ToString()))
    }
    finally {
        Set-ExactEnvironment $baseline
        [Environment]::CurrentDirectory = $baseDirectory
    }
    $writer.WriteLine((
        $nonce, $requestId, [int]$result[0],
        [Convert]::ToBase64String($utf8.GetBytes([string]$result[1])),
        [Convert]::ToBase64String($utf8.GetBytes([string]$result[2]))
    ) -join ' ')
}
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(text: str) -> str:
    return base64.b64decode(text).decode("utf-8")


def _encode_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class SharedPowerShellHost:
    """A single ``powershell.exe`` fed requests over stdin with a nonce sentinel."""

    def __init__(self, executable: str = POWERSHELL_EXECUTABLE) -> None:
        self._executable = executable
        self._process: subprocess.Popen[bytes] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._nonce = ""
        self._launch_module_path = ""
        self._next_id = 0
        self._lock = threading.Lock()

    def _start(self) -> None:
        self._nonce = "\x1eweather-pshost-" + secrets.token_hex(16)
        self._launch_module_path = os.environ.get("PSModulePath", "")
        env = dict(os.environ)
        env[_NONCE_VARIABLE] = self._nonce
        env[_LAUNCH_MODULE_PATH_VARIABLE] = self._launch_module_path
        env["WEATHER_TEST_PSHOST_RUNNER"] = _RUNNER_SOURCE
        host_script = _HOST_SCRIPT.replace("__NONCE__", _NONCE_VARIABLE).replace(
            "__LAUNCH_MODULE_PATH__", _LAUNCH_MODULE_PATH_VARIABLE
        )
        self._process = subprocess.Popen(
            [
                self._executable,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                _encode_command(host_script),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._lines = queue.Queue()
        threading.Thread(
            target=self._pump, args=(self._process, self._lines), daemon=True
        ).start()
        self._await(f"{self._nonce} READY", timeout=120, stray=None)

    @staticmethod
    def _pump(process: subprocess.Popen[bytes], lines: queue.Queue[str | None]) -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            lines.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        lines.put(None)

    def _await(self, prefix: str, *, timeout: float | None, stray: list[str] | None) -> str:
        while True:
            try:
                line = self._lines.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(prefix) from None
            if line is None:
                raise RuntimeError("shared PowerShell host exited unexpectedly")
            if line.startswith(prefix):
                return line[len(prefix):]
            if stray is not None:
                # A grandchild that inherited the host's stdout wrote here; a real
                # child process would have carried this text in its own stdout.
                stray.append(line)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            assert process.stdin is not None
            process.stdin.close()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            _kill_tree(process)

    def run(
        self,
        script: str,
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._start()
            assert self._process is not None and self._process.stdin is not None
            self._next_id += 1
            request_id = self._next_id
            environment = os.environ if env is None else env
            location = str(Path(cwd if cwd is not None else os.getcwd()).resolve())
            fields = (
                str(request_id),
                _b64(location),
                _b64("\0".join(f"{name}={value}" for name, value in environment.items())),
                _b64(script),
            )
            self._process.stdin.write((" ".join(fields) + "\n").encode("ascii"))
            self._process.stdin.flush()
            stray: list[str] = []
            try:
                reply = self._await(
                    f"{self._nonce} {request_id} ", timeout=timeout, stray=stray
                )
            except TimeoutError:
                process, self._process = self._process, None
                _kill_tree(process)
                raise subprocess.TimeoutExpired(
                    [self._executable, "-Command", script], timeout or 0
                ) from None
            code, stdout_b64, stderr_b64 = reply.split(" ")
            stdout = "".join(line + "\n" for line in stray) + _unb64(stdout_b64)
            return subprocess.CompletedProcess(
                [self._executable, "-NoProfile", "-NonInteractive", "-Command", script],
                int(code),
                stdout,
                _unb64(stderr_b64),
            )


_SHARED: SharedPowerShellHost | None = None


def shared_host() -> SharedPowerShellHost:
    global _SHARED
    if _SHARED is None:
        _SHARED = SharedPowerShellHost()
        atexit.register(_SHARED.close)
    return _SHARED


def run_command(
    script: str,
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Evaluate ``script`` like ``powershell.exe -NoProfile -NonInteractive -Command``."""

    if os.environ.get(DISABLE_ENVIRONMENT_VARIABLE, "1") == "0":
        return subprocess.run(
            [POWERSHELL_EXECUTABLE, "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            env=None if env is None else dict(env),
            cwd=cwd,
            timeout=timeout,
        )
    return shared_host().run(script, env=env, cwd=cwd, timeout=timeout)
