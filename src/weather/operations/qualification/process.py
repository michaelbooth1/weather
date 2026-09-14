"""Bounded off-host subprocesses with retained output and explicit cleanup.

Windows delegates to the trusted native Job controller. Linux uses a private
session, a subreaper and /proc descendant accounting; Linux memory limits are
monitored, not represented as a Windows-style aggregate allocation limit.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time

from .records import checked_root, decode, integer, require


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def clean_environment(*, scratch, executable_paths, extra=None):
    """Allowlist, rather than subtracting guessed secret variable names."""
    scratch = checked_root(scratch)
    env = {name: value for name, value in os.environ.items()
           if name.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT", "LANG", "LC_ALL"}}
    env.update({"PATH": os.pathsep.join(dict.fromkeys(str(Path(p).parent) for p in executable_paths)),
                "HOME": str(scratch), "USERPROFILE": str(scratch), "APPDATA": str(scratch),
                "LOCALAPPDATA": str(scratch), "TEMP": str(scratch), "TMP": str(scratch), "TMPDIR": str(scratch),
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "WEATHER_INTEGRATION_TEST_OFFLINE": "1", "TZ": "UTC"})
    for key, value in (extra or {}).items():
        require(key in {"WEATHER_QUALIFICATION_JOURNAL", "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT",
                        "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"}, "unsupported candidate environment override")
        require(type(value) is str, "candidate environment value must be text")
        env[key] = value
    return env


def _linux_processes():
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text()
            values = raw[raw.rfind(")") + 2:].split()
            # stat field 3 starts at index 0: parent=4, pgrp=5, start=22, RSS=24.
            result[int(entry.name)] = (int(values[1]), int(values[2]), int(values[19]),
                                       values[0], int(values[21]) * os.sysconf("SC_PAGE_SIZE"))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            # An unreadable unrelated process is not an owned-process omission:
            # ancestry cannot be proved, so the process monitor refuses.
            raise RuntimeError("Linux process inventory is incomplete") from None
    return result


def _descendants(inventory, parent):
    owned = set()
    changed = True
    while changed:
        changed = False
        for pid, item in inventory.items():
            if pid != parent and pid not in owned and (item[0] == parent or item[0] in owned):
                owned.add(pid)
                changed = True
    return owned


def linux_run(argv, *, cwd, env, transcript, seconds, teardown_seconds, memory_bytes, output_bytes, minimum_disk_bytes):
    require(os.name == "posix" and Path("/proc/self/stat").exists(), "native Linux /proc required")
    integer(seconds, minimum=1, maximum=1200)
    integer(teardown_seconds, minimum=1, maximum=120)
    integer(memory_bytes, minimum=16 * 1024**2, maximum=16 * 1024**3)
    integer(output_bytes, minimum=1, maximum=128 * 1024**2)
    integer(minimum_disk_bytes)
    require(Path(argv[0]).is_absolute(), "absolute child executable required")
    # One serial, otherwise child-free producer owns all descendants. Subreaping
    # prevents double-fork/setsid children from escaping teardown attribution.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    require(libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0 and
            libc.prctl(36, 1, 0, 0, 0) == 0, "Linux child subreaper unavailable")
    process, native_exit, failure = None, None, None
    start = time.monotonic()
    started_at = utc()
    peak, samples, max_gap, count, minimum_disk = 0, 0, 0, 0, 2**63 - 1
    output = None
    teardown = False
    try:
        require(not _descendants(_linux_processes(), os.getpid()), "producer has a preexisting descendant")
        minimum_disk = min(shutil.disk_usage(cwd).free, shutil.disk_usage(Path(transcript).parent).free)
        require(minimum_disk >= minimum_disk_bytes, "off-host disk reserve refused")
        output = Path(transcript).open("xb", buffering=0)
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        os.set_blocking(process.stdout.fileno(), False)
        last, eof = time.monotonic(), False
        while True:
            now = time.monotonic()
            gap = int((now - last) * 1000)
            max_gap = max(max_gap, gap)
            require(gap <= 1000, "Linux monitor missed its one-second deadline")
            require(now - start < seconds, "candidate execution deadline exceeded")
            last = now
            inventory = _linux_processes()
            owned = _descendants(inventory, os.getpid())
            sampled = sum(inventory[pid][4] for pid in owned) + inventory[os.getpid()][4]
            peak = max(peak, sampled)
            samples += 1
            require(sampled <= memory_bytes and len(owned) <= 64, "Linux process resource envelope exceeded")
            minimum_disk = min(minimum_disk, shutil.disk_usage(cwd).free, shutil.disk_usage(Path(transcript).parent).free)
            require(minimum_disk >= minimum_disk_bytes, "off-host disk reserve crossed")
            if not eof and select.select([process.stdout], [], [], 0)[0]:
                block = os.read(process.stdout.fileno(), 65536)
                eof = block == b""
                if block:
                    retained = block[:max(0, output_bytes - count)]
                    output.write(retained)
                    count += len(block)
                    require(count <= output_bytes, "candidate output cap exceeded")
            # WNOWAIT preserves the parent's PID until all descendants are gone.
            status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if status is not None:
                native_exit = status.si_status if status.si_code == os.CLD_EXITED else -status.si_status
                if eof:
                    require(native_exit == 0, "candidate returned a nonzero native exit")
                    break
                # A descendant can retain the pipe; cleanup terminates it and
                # drains the pipe under the same absolute teardown bound.
                if any(pid != process.pid for pid in owned):
                    break
            time.sleep(0.01)
    except Exception as exc:
        failure = str(exc)
    finally:
        if process is not None:
            edge = min(start + seconds + teardown_seconds, time.monotonic() + teardown_seconds)
            try:
                while True:
                    inventory = _linux_processes()
                    owned = _descendants(inventory, os.getpid())
                    for pid in owned:
                        if inventory[pid][3] != "Z":
                            descriptor = None
                            try:
                                descriptor = os.pidfd_open(pid)
                                current = _linux_processes().get(pid)
                                if current is not None and current[2] == inventory[pid][2]:
                                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            finally:
                                if descriptor is not None:
                                    os.close(descriptor)
                    while True:
                        try:
                            pid, status = os.waitpid(-1, os.WNOHANG)
                        except ChildProcessError:
                            break
                        if pid == 0:
                            break
                        if pid == process.pid:
                            process.returncode = os.waitstatus_to_exitcode(status)
                    if not _descendants(_linux_processes(), os.getpid()):
                        teardown = True
                        break
                    require(time.monotonic() < edge, "Linux descendant teardown exceeded deadline")
                    time.sleep(0.01)
                while True:
                    require(time.monotonic() < edge, "Linux output EOF exceeded teardown deadline")
                    try:
                        block = os.read(process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        time.sleep(0.01)
                        continue
                    if not block:
                        break
                    output.write(block[:max(0, output_bytes - count)])
                    count += len(block)
                    require(count <= output_bytes, "candidate output cap exceeded during teardown")
            except Exception as exc:
                failure = str(exc)
            finally:
                process.stdout.close()
        if output is not None:
            try:
                output.flush()
                os.fsync(output.fileno())
            except OSError as exc:
                failure = str(exc)
            finally:
                output.close()
        if libc.prctl(36, previous.value, 0, 0, 0) != 0:
            failure = "failed to restore Linux subreaper setting"
    return {"completed": failure is None and teardown and native_exit == 0, "failure": failure,
            "exit_code": native_exit, "teardown_proved": teardown,
            "elapsed_ms": int((time.monotonic() - start) * 1000), "peak_working_set_bytes": peak,
            "maximum_sample_gap_ms": max_gap, "resource_samples": samples, "minimum_disk_bytes": minimum_disk,
            "started_at": started_at, "completed_at": utc()}


def windows_run(argv, *, powershell, dispatcher, cwd, env, transcript, seconds, teardown_seconds,
                memory_bytes, output_bytes, minimum_disk_bytes, scratch):
    require(os.name == "nt", "native Windows required")
    request = {"schema": "qualification_process_request_v2", "executable": str(argv[0]), "arguments": list(argv[1:]),
               "working_directory": str(cwd), "transcript": str(transcript), "deadline_utc":
               datetime.fromtimestamp(time.time() + seconds + teardown_seconds, timezone.utc).isoformat().replace("+00:00", "Z"),
               "maximum_seconds": seconds, "teardown_seconds": teardown_seconds,
               "commit_bytes": memory_bytes, "working_set_bytes": memory_bytes, "maximum_output_bytes": output_bytes,
               "volumes": sorted({str(Path(cwd).anchor), str(Path(transcript).anchor)}),
               "minimum_disk_bytes": minimum_disk_bytes}
    raw = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(raw) <= 16384, "native Windows request exceeds bound")
    request_path, result_path = Path(scratch) / "native-request.json", Path(scratch) / "native-result.json"
    with request_path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    started = utc()
    outer_start = time.monotonic()
    # The parent is a serial hosted CI job. The dispatcher encloses itself and
    # every candidate descendant before launching any candidate bytes.
    parent_env = {**env, "GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}
    command = [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(dispatcher),
               "-RequestPath", str(request_path), "-RequestSha256", hashlib.sha256(raw).hexdigest(),
               "-ResultPath", str(result_path)]
    with (Path(scratch) / "controller.log").open("xb") as output:
        child = subprocess.run(command, cwd=cwd, env=parent_env, stdin=subprocess.DEVNULL,
                               stdout=output, stderr=subprocess.STDOUT,
                               timeout=seconds + teardown_seconds + 30, check=False)
    require(result_path.is_file(), 'native Windows controller produced no result')
    raw = result_path.read_bytes()
    require(len(raw) <= 16384, "native result exceeds metadata bound")
    result = decode(raw)
    require(child.returncode == 0 and result.get("completed") is True, "native Windows controller refused")
    return {**result, "started_at": started, "completed_at": utc(), "elapsed_ms": int((time.monotonic() - outer_start) * 1000)}
