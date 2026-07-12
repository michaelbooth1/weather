"""Guardrails for long replay/refresh jobs that share the active-day host."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("long_job_guard")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_STATE_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard_status.json"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard.lock"
ACTIVE_ENV_VAR = "WEATHER_LONG_JOB_GUARD_ACTIVE"
DEFAULT_CHILD_OUTPUT_TAIL_CHARS = 4000


class LongJobBusy(RuntimeError):
    """Raised when another guarded long job is already active."""


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def touch_long_job_guard(state_path=DEFAULT_STATE_PATH, *, progress=None):
    """Refresh a running long-job guard heartbeat without taking the lock."""
    state_path = Path(state_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated": False, "reason": "state_unavailable"}
    if state.get("status") != "running" or not state.get("active"):
        return {"updated": False, "reason": "not_running"}
    now = utc_iso()
    state["updated_at_utc"] = now
    started = _parse_utc(state.get("started_at_utc"))
    current = _parse_utc(now)
    if started and current:
        state["duration_seconds"] = round((current - started).total_seconds(), 3)
    if progress is not None:
        state["progress"] = progress
        state["last_progress_at_utc"] = now
    write_json(state_path, state)
    return {"updated": True, "state_path": str(state_path)}


def _lock_payload(job_name):
    return {
        "schema_version": SCHEMA_VERSION,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": utc_iso(),
    }


def process_is_running(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information | synchronize,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_is_running(pid):
    return process_is_running(pid)


def _read_lock_detail(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path)}


def _lock_owner_is_active(detail):
    if isinstance(detail, dict) and "pid" in detail:
        return _process_is_running(detail.get("pid"))
    return True


def acquire_long_job_lock(path, job_name, force=False, audit=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    audit = audit if isinstance(audit, dict) else {}
    audit.update({
        "instrumented": True,
        "kind": "long_job_guard_lock",
        "path": str(path),
        "guard_enabled": True,
        "nested": False,
        "force_requested": bool(force),
        "forced_lock_acquisition_count": int(bool(force)),
        "forced_lock_repair_count": 0,
        "stale_lock_detected_count": 0,
        "stale_lock_repair_count": 0,
        "acquired": False,
    })
    if force:
        try:
            path.unlink()
            audit["forced_lock_repair_count"] += 1
        except FileNotFoundError:
            pass
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        detail = _read_lock_detail(path)
        if not _lock_owner_is_active(detail):
            audit["stale_lock_detected_count"] += 1
            try:
                path.unlink()
                audit["stale_lock_repair_count"] += 1
            except FileNotFoundError:
                pass
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                detail = _read_lock_detail(path)
                raise LongJobBusy(f"long job already active: {detail}") from exc
        else:
            raise LongJobBusy(f"long job already active: {detail}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(_lock_payload(job_name), handle, sort_keys=True)
    audit["acquired"] = True
    return path


def release_long_job_lock(path):
    if not path:
        return
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def _lower_memory_priority(priority):
    """Bias Windows page replacement against this process (best effort).

    CPU priority alone did not protect the collection loops on 2026-07-03: a
    7 GB replay at below-normal CPU still forced the trackers' pages out and a
    10-minute capture sweep thrashed to ~85 minutes. Memory priority tells the
    memory manager to evict THIS process's pages before normal-priority ones.
    """
    import ctypes

    MEMORY_PRIORITY_LOW = 2
    MEMORY_PRIORITY_BELOW_NORMAL = 4
    memory_priority = (
        MEMORY_PRIORITY_LOW if priority == "idle" else MEMORY_PRIORITY_BELOW_NORMAL
    )

    class MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
        _fields_ = [("MemoryPriority", ctypes.c_ulong)]

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    kernel32.SetProcessInformation.restype = ctypes.c_int
    ProcessMemoryPriority = 0
    info = MEMORY_PRIORITY_INFORMATION(memory_priority)
    ok = kernel32.SetProcessInformation(
        kernel32.GetCurrentProcess(),
        ProcessMemoryPriority,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        raise OSError("SetProcessInformation(ProcessMemoryPriority) returned 0")
    return {"applied": True, "memory_priority": memory_priority}


def set_process_working_set_limit(pid, *, max_bytes=None, min_bytes=None):
    """Best-effort Windows working-set cap for an already spawned child.

    The process still owns its virtual memory; this limits resident working set
    pressure so a replay child can be paged without pinning the daily-refresh
    parent or collection loops.
    """
    if not max_bytes or int(max_bytes) <= 0:
        return {"requested": False, "applied": False, "reason": "no_limit"}
    if os.name != "nt":
        return {"requested": True, "applied": False, "reason": "non_windows"}
    try:
        import ctypes

        PROCESS_SET_QUOTA = 0x0100
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        QUOTA_LIMITS_HARDWS_MAX_ENABLE = 0x00000004
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.SetProcessWorkingSetSizeEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint32,
        )
        kernel32.SetProcessWorkingSetSizeEx.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            int(pid),
        )
        if not handle:
            raise OSError("OpenProcess returned 0")
        try:
            max_value = int(max_bytes)
            min_value = int(min_bytes) if min_bytes and int(min_bytes) > 0 else min(64 * 1024 * 1024, max_value)
            ok = kernel32.SetProcessWorkingSetSizeEx(
                handle,
                ctypes.c_size_t(min_value),
                ctypes.c_size_t(max_value),
                QUOTA_LIMITS_HARDWS_MAX_ENABLE,
            )
            if not ok:
                raise OSError("SetProcessWorkingSetSizeEx returned 0")
        finally:
            kernel32.CloseHandle(handle)
        return {
            "requested": True,
            "applied": True,
            "pid": int(pid),
            "min_bytes": min_value,
            "max_bytes": max_value,
            "method": "SetProcessWorkingSetSizeEx",
        }
    except Exception as exc:  # noqa: BLE001 - cap is best-effort
        return {
            "requested": True,
            "applied": False,
            "pid": int(pid),
            "max_bytes": int(max_bytes),
            "error": f"{type(exc).__name__}: {exc}",
        }


class _WindowsJobObject:
    """Own a fail-closed Windows Job Object for one subprocess tree."""

    def __init__(self, *, memory_limit_bytes=None):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = None
        self._closed = False

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._extended_info_type = JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        self._accounting_info_type = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            self._raise_last_error("CreateJobObjectW")
        self._handle = handle
        try:
            self.memory_limit = self._configure_limits(memory_limit_bytes)
        except BaseException:
            self.close()
            raise

    def _raise_last_error(self, operation):
        error = self._ctypes.get_last_error()
        raise OSError(error, f"{operation} failed: {self._ctypes.FormatError(error)}")

    def _configure_limits(self, memory_limit_bytes):
        ctypes = self._ctypes
        info = self._extended_info_type()
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        requested = bool(memory_limit_bytes and int(memory_limit_bytes) > 0)
        if requested:
            maximum = int(memory_limit_bytes)
            flags |= (
                JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | JOB_OBJECT_LIMIT_JOB_MEMORY
            )
            info.ProcessMemoryLimit = maximum
            info.JobMemoryLimit = maximum
        info.BasicLimitInformation.LimitFlags = flags
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            self._raise_last_error("SetInformationJobObject")
        return {
            "requested": requested,
            "applied": requested,
            "max_bytes": int(memory_limit_bytes) if requested else None,
            "method": "windows_job_object_job_and_process_memory",
            "scope": "process_tree",
            "working_set_cap": False,
            "job_commit_cap": requested,
            "kill_on_close": True,
        }

    def assign(self, process_handle):
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            self._raise_last_error("AssignProcessToJobObject")

    def terminate(self, exit_code=1):
        if self._closed or not self._handle:
            return False
        if not self._kernel32.TerminateJobObject(self._handle, int(exit_code)):
            self._raise_last_error("TerminateJobObject")
        return True

    def accounting(self):
        ctypes = self._ctypes
        returned = self._wintypes.DWORD()
        accounting = self._accounting_info_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            1,  # JobObjectBasicAccountingInformation
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject(accounting)")
        extended = self._extended_info_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(extended),
            ctypes.sizeof(extended),
            ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject(limits)")
        return {
            "total_processes": int(accounting.TotalProcesses),
            "active_processes": int(accounting.ActiveProcesses),
            "terminated_processes": int(accounting.TotalTerminatedProcesses),
            "peak_process_memory_bytes": int(extended.PeakProcessMemoryUsed),
            "peak_job_memory_bytes": int(extended.PeakJobMemoryUsed),
        }

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _resume_suspended_windows_process(pid):
    """Resume every initial thread after the process has joined its Job Object."""

    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPTHREAD = 0x00000004
    THREAD_SUSPEND_RESUME = 0x0002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(THREADENTRY32))
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(THREADENTRY32))
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise OSError(error, f"CreateToolhelp32Snapshot failed: {ctypes.FormatError(error)}")
    resumed = 0
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        found = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while found:
            if int(entry.th32OwnerProcessID) == int(pid):
                thread = kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread:
                    try:
                        previous_count = kernel32.ResumeThread(thread)
                        if previous_count != 0xFFFFFFFF:
                            resumed += 1
                    finally:
                        kernel32.CloseHandle(thread)
            found = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    if resumed <= 0:
        raise OSError(f"no suspended thread found for pid {pid}")
    return {"resumed_thread_count": resumed, "method": "ResumeThread"}


def _posix_group_exists(process_group_id):
    try:
        os.killpg(int(process_group_id), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_posix_process_group(process_group_id, *, reason, force=False):
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(int(process_group_id), sig)
        return {
            "triggered": True,
            "reason": reason,
            "method": "os.killpg",
            "signal": sig.name,
            "process_group_id": int(process_group_id),
            "tree_termination_requested": True,
        }
    except ProcessLookupError:
        return {
            "triggered": False,
            "reason": reason,
            "method": "os.killpg",
            "process_group_id": int(process_group_id),
            "tree_termination_requested": False,
            "detail": "process_group_already_exited",
        }
    except Exception as exc:  # noqa: BLE001 - termination metadata must survive
        return {
            "triggered": False,
            "reason": reason,
            "method": "os.killpg",
            "process_group_id": int(process_group_id),
            "tree_termination_requested": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _finish_posix_process_group(process_group_id, termination, *, grace_seconds=0.5):
    """Ensure no descendant survives a prior TERM or root-process exit."""

    if not _posix_group_exists(process_group_id):
        termination["tree_terminated"] = True
        return termination
    if not termination.get("triggered"):
        termination = _terminate_posix_process_group(
            process_group_id,
            reason="descendant_cleanup",
        )
    deadline = time.time() + max(0.0, float(grace_seconds))
    while time.time() < deadline and _posix_group_exists(process_group_id):
        time.sleep(0.02)
    if _posix_group_exists(process_group_id):
        termination["escalation"] = _terminate_posix_process_group(
            process_group_id,
            reason=f"{termination.get('reason') or 'cleanup'}_escalation",
            force=True,
        )
        deadline = time.time() + max(0.0, float(grace_seconds))
        while time.time() < deadline and _posix_group_exists(process_group_id):
            time.sleep(0.02)
    termination["tree_terminated"] = not _posix_group_exists(process_group_id)
    return termination


def run_isolated_subprocess(
    command,
    *,
    timeout_seconds=None,
    working_set_max_bytes=None,
    cwd=None,
    env=None,
    output_tail_chars=DEFAULT_CHILD_OUTPUT_TAIL_CHARS,
):
    """Run a heavy command inside a memory-bounded, killable process tree.

    Windows launches the root suspended, assigns it to a Job Object, and only
    then resumes it.  That ordering is essential for venv/store launchers: the
    real interpreter descendants inherit the Job Object before they can exist.
    POSIX launches a new session and terminates only that process group.
    """
    started = time.time()
    command_row = [str(item) for item in command]
    process = None
    job = None
    stdout = ""
    stderr = ""
    timed_out = False
    runner_error = None
    termination = {
        "triggered": False,
        "reason": "not_required",
        "tree_termination_requested": False,
    }
    if working_set_max_bytes and int(working_set_max_bytes) > 0:
        working_set = {
            "requested": True,
            "applied": False,
            "max_bytes": int(working_set_max_bytes),
        }
    else:
        working_set = {"requested": False, "applied": False, "reason": "no_limit"}
    containment = {
        "requested": True,
        "status": "PENDING",
        "platform": "windows" if os.name == "nt" else "posix",
        "process_tree_contained": False,
        "root_created_suspended": False,
        "assigned_before_resume": False,
        "kill_on_container_close": False,
        "memory_limit": working_set,
    }

    popen_kwargs = {
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "env": env,
    }
    try:
        if os.name == "nt":
            job = _WindowsJobObject(memory_limit_bytes=working_set_max_bytes)
            working_set = job.memory_limit
            containment.update({
                "method": "windows_job_object",
                "root_created_suspended": True,
                "kill_on_container_close": True,
                "memory_limit": working_set,
            })
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            popen_kwargs["start_new_session"] = True
            containment.update({
                "method": "posix_process_group",
                "kill_on_container_close": False,
            })
            if working_set["requested"]:
                working_set.update({
                    "reason": "non_windows",
                    "scope": "not_applied",
                })
        process = subprocess.Popen(command_row, **popen_kwargs)
        if os.name == "nt":
            job.assign(process._handle)  # noqa: SLF001 - Win32 handle is required for Job assignment
            resume = _resume_suspended_windows_process(process.pid)
            containment.update({
                "status": "PASS",
                "process_tree_contained": True,
                "assigned_before_resume": True,
                "resume": resume,
                "root_pid": process.pid,
            })
        else:
            containment.update({
                "status": "PASS",
                "process_tree_contained": True,
                "assigned_before_resume": True,
                "process_group_id": process.pid,
                "root_pid": process.pid,
            })
    except Exception as exc:  # noqa: BLE001 - return fail-closed setup evidence
        containment.update({
            "status": "BLOCK",
            "process_tree_contained": False,
            "error": f"{type(exc).__name__}: {exc}",
        })
        if process is not None:
            try:
                if job is not None:
                    job.terminate(exit_code=125)
                    termination = {
                        "triggered": True,
                        "reason": "containment_setup_failure",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": True,
                    }
                else:
                    process.kill()
                    termination = {
                        "triggered": True,
                        "reason": "containment_setup_failure",
                        "method": "Popen.kill_suspended_root",
                        "tree_termination_requested": True,
                    }
            except Exception as termination_exc:  # noqa: BLE001
                termination["error"] = f"{type(termination_exc).__name__}: {termination_exc}"
            try:
                stdout, stderr = process.communicate(timeout=5)
            except Exception:  # noqa: BLE001 - process never ran user code while suspended
                stdout = stderr = ""
        if job is not None:
            job.close()
        tail = max(0, int(output_tail_chars or 0))
        return {
            "command": command_row,
            "pid": process.pid if process is not None else None,
            "returncode": process.returncode if process is not None else None,
            "timed_out": False,
            "stdout": (stdout or "")[-tail:] if tail else "",
            "stderr": (stderr or "")[-tail:] if tail else "",
            "duration_seconds": round(time.time() - started, 3),
            "working_set_limit": working_set,
            "containment": containment,
            "termination": termination,
            "runner_error": containment["error"],
        }

    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if job is not None:
                try:
                    job.terminate(exit_code=124)
                    termination = {
                        "triggered": True,
                        "reason": "timeout",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": True,
                    }
                except Exception as exc:  # noqa: BLE001
                    termination = {
                        "triggered": False,
                        "reason": "timeout",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            else:
                termination = _terminate_posix_process_group(process.pid, reason="timeout")
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if job is not None:
                    process.kill()
                else:
                    escalation = _terminate_posix_process_group(
                        process.pid,
                        reason="timeout_escalation",
                        force=True,
                    )
                    termination["escalation"] = escalation
                stdout, stderr = process.communicate(timeout=5)
        except BaseException as exc:
            if job is not None:
                try:
                    job.terminate(exit_code=125)
                    termination = {
                        "triggered": True,
                        "reason": "runner_error",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": True,
                    }
                except Exception as termination_exc:  # noqa: BLE001
                    termination = {
                        "triggered": False,
                        "reason": "runner_error",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": False,
                        "error": f"{type(termination_exc).__name__}: {termination_exc}",
                    }
            else:
                termination = _terminate_posix_process_group(process.pid, reason="runner_error")
            try:
                stdout, stderr = process.communicate(timeout=5)
            except Exception:  # noqa: BLE001 - preserve the original runner exception
                stdout = stderr = ""
            if not isinstance(exc, Exception):
                raise
            runner_error = f"{type(exc).__name__}: {exc}"

        if job is not None:
            try:
                accounting = job.accounting()
                quiescence_deadline = time.time() + 0.5
                while accounting.get("active_processes", 0) > 0 and time.time() < quiescence_deadline:
                    time.sleep(0.02)
                    accounting = job.accounting()
                containment["accounting"] = accounting
                if accounting.get("active_processes", 0) > 0 and not termination.get("triggered"):
                    job.terminate(exit_code=0)
                    termination = {
                        "triggered": True,
                        "reason": "descendant_cleanup",
                        "method": "TerminateJobObject",
                        "tree_termination_requested": True,
                        "active_processes_before_termination": accounting["active_processes"],
                    }
                termination["tree_scope"] = "windows_job_object"
                termination["tree_terminated"] = (
                    accounting.get("active_processes", 0) == 0
                    or bool(termination.get("triggered"))
                )
            except Exception as exc:  # noqa: BLE001 - close still enforces kill-on-close
                containment["accounting_error"] = f"{type(exc).__name__}: {exc}"
                termination["tree_terminated_on_container_close"] = True
        else:
            termination = _finish_posix_process_group(process.pid, termination)
            termination["tree_scope"] = "posix_process_group"
    finally:
        if job is not None:
            job.close()

    tail = max(0, int(output_tail_chars or 0))
    return {
        "command": command_row,
        "pid": process.pid,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-tail:] if tail else "",
        "stderr": (stderr or "")[-tail:] if tail else "",
        "duration_seconds": round(time.time() - started, 3),
        "working_set_limit": working_set,
        "containment": containment,
        "termination": termination,
        "runner_error": runner_error,
    }


def lower_process_priority(priority="below_normal"):
    """Best-effort process throttling for local long jobs.

    This deliberately avoids external dependencies. On Windows it uses
    SetPriorityClass plus a lowered memory priority; on POSIX it increases the
    nice value. Failure is reported in the guard status and does not abort the
    job.
    """
    priority = (priority or "normal").lower()
    if priority in {"normal", "none", "off"}:
        return {"requested": priority, "applied": False, "reason": "normal_priority"}
    try:
        if os.name == "nt":
            import ctypes

            classes = {
                "idle": 0x00000040,
                "below_normal": 0x00004000,
            }
            priority_class = classes.get(priority, classes["below_normal"])
            kernel32 = ctypes.windll.kernel32
            # Without these declarations ctypes truncates the pseudo-handle to
            # a 32-bit int on 64-bit Windows and SetPriorityClass rejects it.
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            kernel32.SetPriorityClass.restype = ctypes.c_int
            handle = kernel32.GetCurrentProcess()
            ok = kernel32.SetPriorityClass(handle, priority_class)
            if not ok:
                raise OSError("SetPriorityClass returned 0")
            try:
                memory_result = _lower_memory_priority(priority)
            except Exception as exc:  # noqa: BLE001 - memory bias is best-effort
                memory_result = {
                    "applied": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            return {
                "requested": priority,
                "applied": True,
                "method": "SetPriorityClass",
                "memory_priority": memory_result,
            }
        increment = 10 if priority == "idle" else 5
        new_nice = os.nice(increment)
        return {
            "requested": priority,
            "applied": True,
            "method": "os.nice",
            "nice": new_nice,
        }
    except Exception as exc:  # noqa: BLE001 - throttling is best-effort
        return {
            "requested": priority,
            "applied": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@contextlib.contextmanager
def long_job_guard(
    job_name,
    *,
    state_path=DEFAULT_STATE_PATH,
    lock_path=DEFAULT_LOCK_PATH,
    priority="below_normal",
    enabled=True,
    force_lock=False,
):
    """Serialize and throttle expensive replay/refresh jobs.

    Nested calls in the same process tree are treated as already guarded. This
    lets `daily_refresh` guard the whole pipeline while `promotion_refresh`
    remains guarded when invoked directly.
    """
    if not enabled:
        yield {
            "enabled": False,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
            "lock_acquisition": {
                "instrumented": True,
                "kind": "long_job_guard_lock",
                "path": str(lock_path),
                "guard_enabled": False,
                "nested": False,
                "force_requested": bool(force_lock),
                "forced_lock_acquisition_count": int(bool(force_lock)),
                "forced_lock_repair_count": 0,
                "stale_lock_detected_count": 0,
                "stale_lock_repair_count": 0,
                "acquired": False,
            },
        }
        return
    if os.environ.get(ACTIVE_ENV_VAR):
        yield {
            "enabled": True,
            "nested": True,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
            "lock_acquisition": {
                "instrumented": True,
                "kind": "long_job_guard_lock",
                "path": str(lock_path),
                "guard_enabled": True,
                "nested": True,
                "force_requested": bool(force_lock),
                "forced_lock_acquisition_count": int(bool(force_lock)),
                "forced_lock_repair_count": 0,
                "stale_lock_detected_count": 0,
                "stale_lock_repair_count": 0,
                "acquired": False,
            },
        }
        return

    lock_audit = {}
    lock = acquire_long_job_lock(
        lock_path,
        job_name,
        force=force_lock,
        audit=lock_audit,
    )
    previous_env = os.environ.get(ACTIVE_ENV_VAR)
    os.environ[ACTIVE_ENV_VAR] = str(os.getpid())
    start_monotonic = time.time()
    started_wall = utc_iso()
    priority_result = lower_process_priority(priority)
    write_json(state_path, {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "active": True,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": started_wall,
        "updated_at_utc": started_wall,
        "duration_seconds": 0.0,
        "priority": priority_result,
    })
    try:
        yield {
            "enabled": True,
            "nested": False,
            "state_path": str(state_path),
            "lock_path": str(lock_path),
            "priority": priority_result,
            "lock_acquisition": lock_audit,
        }
    except Exception as exc:
        write_json(state_path, {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "active": False,
            "job_name": job_name,
            "pid": os.getpid(),
            "started_at_utc": started_wall,
            "updated_at_utc": utc_iso(),
            "duration_seconds": round(time.time() - start_monotonic, 3),
            "priority": priority_result,
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise
    finally:
        if previous_env is None:
            os.environ.pop(ACTIVE_ENV_VAR, None)
        else:
            os.environ[ACTIVE_ENV_VAR] = previous_env
        release_long_job_lock(lock)
        if Path(state_path).exists():
            try:
                state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                state = {}
            if state.get("status") == "running":
                state.update({
                    "status": "complete",
                    "active": False,
                    "updated_at_utc": utc_iso(),
                    "duration_seconds": round(time.time() - start_monotonic, 3),
                })
                write_json(state_path, state)
