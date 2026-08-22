"""Guardrails for long replay/refresh jobs that share the active-day host."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.operations.windows_process_lifetime import (
    WindowsProcessLifetimeTracker,
)
from weather.operations.windows_process_metrics import windows_process_memory_metrics
from weather.operations.process_lock_identity import (
    LOCK_OWNER_IDENTITY_FIELD,
    LockPathTransactionBusy,
    current_process_identity as _current_process_identity,
    lock_path_transaction,
    lock_owner_status as _lock_owner_status,
    observe_process_identity,
    remove_lock_payload_if_current,
)
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("long_job_guard")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_STATE_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard_status.json"
DEFAULT_LOCK_PATH = DEFAULT_BACKTEST_ROOT / "long_job_guard.lock"
ACTIVE_ENV_VAR = "WEATHER_LONG_JOB_GUARD_ACTIVE"
DEFAULT_CHILD_OUTPUT_TAIL_CHARS = 4000


class _BoundedPipeCapture:
    """Drain child pipes without retaining unbounded parent-process output."""

    def __init__(self, stdout, stderr, *, tail_bytes, max_bytes=None):
        self._lock = threading.Lock()
        self._tail_bytes = max(0, int(tail_bytes or 0))
        self._max_bytes = (
            int(max_bytes) if max_bytes is not None and int(max_bytes) > 0 else None
        )
        self._total_bytes = 0
        self._tails = {"stdout": bytearray(), "stderr": bytearray()}
        self._errors = []
        self._threads = []
        for name, stream in (("stdout", stdout), ("stderr", stderr)):
            thread = threading.Thread(
                target=self._drain,
                args=(name, stream),
                name=f"long-job-{name}-drain",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def _drain(self, name, stream):
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")
                with self._lock:
                    self._total_bytes += len(chunk)
                    if self._tail_bytes:
                        tail = self._tails[name]
                        tail.extend(chunk)
                        overflow = len(tail) - self._tail_bytes
                        if overflow > 0:
                            del tail[:overflow]
        except Exception as exc:  # noqa: BLE001 - report pipe failures fail closed
            with self._lock:
                self._errors.append(f"{name}: {type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                stream.close()

    def exceeded_limit(self):
        with self._lock:
            return bool(
                self._max_bytes is not None and self._total_bytes > self._max_bytes
            )

    def total_bytes(self):
        with self._lock:
            return int(self._total_bytes)

    def finish(self, *, timeout=5.0):
        deadline = time.time() + max(0.0, float(timeout))
        for thread in self._threads:
            thread.join(max(0.0, deadline - time.time()))
        alive = [thread.name for thread in self._threads if thread.is_alive()]
        with self._lock:
            stdout = bytes(self._tails["stdout"]).decode("utf-8", errors="replace")
            stderr = bytes(self._tails["stderr"]).decode("utf-8", errors="replace")
            errors = list(self._errors)
        if alive:
            errors.append(f"pipe drain did not reach EOF: {', '.join(alive)}")
        return stdout, stderr, "; ".join(errors) if errors else None


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


def normalize_progress_counters(progress):
    """Keep historical/resumed progress counters internally consistent."""
    if not isinstance(progress, dict):
        return progress
    normalized = dict(progress)
    try:
        completed = int(normalized.get("completed_step_count"))
        total = int(normalized.get("total_step_count"))
    except (TypeError, ValueError):
        return normalized
    if completed < 0 or total >= completed:
        return normalized
    normalized["total_step_count"] = completed
    normalized["progress_counter_repair"] = {
        "reason": "completed_step_count_exceeded_total_step_count",
        "original_total_step_count": total,
        "normalized_total_step_count": completed,
    }
    return normalized


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
        state["progress"] = normalize_progress_counters(progress)
        state["last_progress_at_utc"] = now
    write_json(state_path, state)
    return {"updated": True, "state_path": str(state_path)}


def _lock_payload(job_name):
    return {
        "schema_version": SCHEMA_VERSION,
        "job_name": job_name,
        "pid": os.getpid(),
        "started_at_utc": utc_iso(),
        LOCK_OWNER_IDENTITY_FIELD: current_process_identity(),
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


def lock_owner_status(detail, *, observe_fn=None):
    """Compatibility facade with a patchable observer for existing callers/tests."""

    return _lock_owner_status(
        detail,
        observe_fn=observe_fn or observe_process_identity,
    )


def current_process_identity():
    """Compatibility facade sharing the observer patched by existing tests."""

    observed = observe_process_identity(os.getpid())
    if observed:
        return {
            "pid": os.getpid(),
            "image_path": observed.get("image_path"),
            "creation_time_token": observed.get("creation_time_token"),
        }
    return _current_process_identity()


def _read_lock_detail(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(path)}


def acquire_long_job_lock(path, job_name, force=False, audit=None):
    try:
        with lock_path_transaction(path):
            return _acquire_long_job_lock_transaction(
                path,
                job_name,
                force=force,
                audit=audit,
            )
    except LockPathTransactionBusy as exc:
        if isinstance(audit, dict):
            audit["acquired"] = False
            audit["transaction_busy"] = True
        raise LongJobBusy(f"long-job lock pathname transaction busy: {path}") from exc


def _acquire_long_job_lock_transaction(path, job_name, force=False, audit=None):
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
        owner = lock_owner_status(detail)
        if not owner.get("active"):
            audit["stale_lock_detected_count"] += 1
            audit["stale_lock_reason"] = owner.get("stale_reason")
            audit["stale_lock_owner_observation"] = owner.get("observation")
            removal = remove_lock_payload_if_current(path, detail)
            if removal.get("removed"):
                audit["stale_lock_repair_count"] += 1
            else:
                detail = _read_lock_detail(path)
                raise LongJobBusy(
                    f"long-job lock instance changed during stale repair: {detail}"
                ) from exc
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
        with lock_path_transaction(path):
            detail = _read_lock_detail(Path(path))
            if detail.get("pid") != os.getpid():
                return
            stored = detail.get(LOCK_OWNER_IDENTITY_FIELD)
            if isinstance(stored, dict):
                current = current_process_identity()
                expected_token = stored.get("creation_time_token")
                current_token = current.get("creation_time_token")
                if expected_token and expected_token != current_token:
                    return
            remove_lock_payload_if_current(path, detail)
    except LockPathTransactionBusy:
        return


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

    def __init__(
        self,
        *,
        private_memory_limit_bytes=None,
        working_set_limit_bytes=None,
    ):
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

        class JOBOBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicInfo", JOBOBJECT_BASIC_ACCOUNTING_INFORMATION),
                ("IoInfo", IO_COUNTERS),
            ]

        self._extended_info_type = JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        self._accounting_info_type = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        self._accounting_and_io_info_type = (
            JOBOBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION
        )
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
            self.memory_limit = self._configure_limits(
                private_memory_limit_bytes=private_memory_limit_bytes,
                working_set_limit_bytes=working_set_limit_bytes,
            )
        except BaseException:
            self.close()
            raise

    def _raise_last_error(self, operation):
        error = self._ctypes.get_last_error()
        raise OSError(error, f"{operation} failed: {self._ctypes.FormatError(error)}")

    def _configure_limits(
        self,
        *,
        private_memory_limit_bytes,
        working_set_limit_bytes,
    ):
        ctypes = self._ctypes
        info = self._extended_info_type()
        JOB_OBJECT_LIMIT_WORKINGSET = 0x00000001
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        private_requested = bool(
            private_memory_limit_bytes and int(private_memory_limit_bytes) > 0
        )
        working_set_requested = bool(
            working_set_limit_bytes and int(working_set_limit_bytes) > 0
        )
        if private_requested:
            maximum = int(private_memory_limit_bytes)
            flags |= (
                JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | JOB_OBJECT_LIMIT_JOB_MEMORY
            )
            info.ProcessMemoryLimit = maximum
            info.JobMemoryLimit = maximum
        if working_set_requested:
            working_set_maximum = int(working_set_limit_bytes)
            flags |= JOB_OBJECT_LIMIT_WORKINGSET
            info.BasicLimitInformation.MinimumWorkingSetSize = min(
                64 * 1024 * 1024,
                working_set_maximum,
            )
            info.BasicLimitInformation.MaximumWorkingSetSize = working_set_maximum
        info.BasicLimitInformation.LimitFlags = flags
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        working_set_kernel_cap = working_set_requested and bool(ok)
        working_set_kernel_error = None
        if not ok and working_set_requested:
            # JOB_OBJECT_LIMIT_WORKINGSET requires a quota privilege that the
            # scheduled service account does not necessarily hold. Preserve
            # the hard private/job commit cap, then enforce the working-set
            # ceiling with the process-tree sampler below.
            error = ctypes.get_last_error()
            working_set_kernel_error = (
                f"OSError: [WinError {error}] {ctypes.FormatError(error)}"
            )
            info = self._extended_info_type()
            fallback_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if private_requested:
                fallback_flags |= (
                    JOB_OBJECT_LIMIT_PROCESS_MEMORY
                    | JOB_OBJECT_LIMIT_JOB_MEMORY
                )
                info.ProcessMemoryLimit = int(private_memory_limit_bytes)
                info.JobMemoryLimit = int(private_memory_limit_bytes)
            info.BasicLimitInformation.LimitFlags = fallback_flags
            ok = self._kernel32.SetInformationJobObject(
                self._handle,
                9,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
        if not ok:
            self._raise_last_error("SetInformationJobObject")
        return {
            # Keep these compatibility fields for existing callers that used
            # ``working_set_max_bytes`` as the single process-tree memory cap.
            "requested": private_requested or working_set_requested,
            "applied": private_requested or working_set_requested,
            "max_bytes": (
                int(private_memory_limit_bytes)
                if private_requested
                else int(working_set_limit_bytes)
                if working_set_requested
                else None
            ),
            "private_memory_max_bytes": (
                int(private_memory_limit_bytes) if private_requested else None
            ),
            "working_set_max_bytes": (
                int(working_set_limit_bytes) if working_set_requested else None
            ),
            "method": "windows_job_object_memory_and_working_set",
            "scope": "process_tree",
            "working_set_cap": working_set_requested,
            "working_set_kernel_cap": working_set_kernel_cap,
            "working_set_cap_method": (
                "windows_job_object"
                if working_set_kernel_cap
                else "sampled_process_tree_termination"
                if working_set_requested
                else None
            ),
            "working_set_kernel_error": working_set_kernel_error,
            "job_commit_cap": private_requested,
            "kill_on_close": True,
        }

    def assign(self, process_handle):
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            self._raise_last_error("AssignProcessToJobObject")

    def native_handle(self):
        return self._handle

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
        accounting_and_io = self._accounting_and_io_info_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            8,  # JobObjectBasicAndIoAccountingInformation
            ctypes.byref(accounting_and_io),
            ctypes.sizeof(accounting_and_io),
            ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject(io_accounting)")
        io_info = accounting_and_io.IoInfo
        return {
            "total_processes": int(accounting.TotalProcesses),
            "active_processes": int(accounting.ActiveProcesses),
            "terminated_processes": int(accounting.TotalTerminatedProcesses),
            "peak_process_memory_bytes": int(extended.PeakProcessMemoryUsed),
            "peak_job_memory_bytes": int(extended.PeakJobMemoryUsed),
            "read_operation_count": int(io_info.ReadOperationCount),
            "write_operation_count": int(io_info.WriteOperationCount),
            "other_operation_count": int(io_info.OtherOperationCount),
            "read_bytes": int(io_info.ReadTransferCount),
            "write_bytes": int(io_info.WriteTransferCount),
            "other_bytes": int(io_info.OtherTransferCount),
        }

    def process_ids(self, *, capacity=1024):
        """Return active process IDs assigned to this Job Object."""

        ctypes = self._ctypes
        returned = self._wintypes.DWORD()
        header_bytes = ctypes.sizeof(self._wintypes.DWORD) * 2
        buffer_size = header_bytes + ctypes.sizeof(ctypes.c_size_t) * int(capacity)
        buffer = ctypes.create_string_buffer(buffer_size)
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            3,  # JobObjectBasicProcessIdList
            buffer,
            buffer_size,
            ctypes.byref(returned),
        ):
            self._raise_last_error("QueryInformationJobObject(process_ids)")
        assigned = int.from_bytes(buffer.raw[0:4], "little")
        listed = int.from_bytes(buffer.raw[4:8], "little")
        count = min(assigned, listed, int(capacity))
        offset = header_bytes
        return [
            int.from_bytes(
                buffer.raw[
                    offset + index * ctypes.sizeof(ctypes.c_size_t) :
                    offset + (index + 1) * ctypes.sizeof(ctypes.c_size_t)
                ],
                "little",
            )
            for index in range(count)
        ]

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


def _posix_process_group_memory_metrics(process_group_id):
    rows = []
    proc_root = Path("/proc")
    if not proc_root.exists():
        return rows
    for child in proc_root.iterdir():
        if not child.name.isdigit():
            continue
        try:
            stat = (child / "stat").read_text(encoding="utf-8").split()
            if int(stat[4]) != int(process_group_id):
                continue
            status = (child / "status").read_text(encoding="utf-8").splitlines()
            io_lines = (child / "io").read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, IndexError):
            continue
        values = {}
        for line in status:
            if line.startswith(("VmRSS:", "VmData:")):
                key, value, *_units = line.split()
                values[key.rstrip(":")] = int(value) * 1024
        io_values = {}
        for line in io_lines:
            key, value = line.split(":", 1)
            io_values[key] = int(value.strip())
        rows.append({
            "pid": int(child.name),
            "working_set_bytes": values.get("VmRSS", 0),
            # VmData is the closest dependency-free Linux analogue available
            # here; the Windows production path reports exact PrivateUsage.
            "private_bytes": values.get("VmData", 0),
            "read_operation_count": io_values.get("syscr", 0),
            "write_operation_count": io_values.get("syscw", 0),
            "read_bytes": io_values.get("read_bytes", 0),
            "write_bytes": io_values.get("write_bytes", 0),
        })
    return rows


def _contained_process_memory_metrics(job, root_pid):
    try:
        if os.name == "nt" and job is not None:
            process_ids = set(job.process_ids())
            process_ids.add(int(root_pid))
            rows = [
                row
                for row in (
                    windows_process_memory_metrics(pid)
                    for pid in process_ids
                )
                if row is not None
            ]
        elif os.name != "nt":
            rows = _posix_process_group_memory_metrics(root_pid)
        else:
            rows = []
    except Exception as exc:  # noqa: BLE001 - sampling must not break containment
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "process_count": 0,
        }
    result = {
        "available": bool(rows),
        "process_count": len(rows),
        "working_set_bytes": sum(row["working_set_bytes"] for row in rows),
        "private_bytes": sum(row["private_bytes"] for row in rows),
        "read_operation_count": sum(row.get("read_operation_count", 0) for row in rows),
        "write_operation_count": sum(row.get("write_operation_count", 0) for row in rows),
        "read_bytes": sum(row.get("read_bytes", 0) for row in rows),
        "write_bytes": sum(row.get("write_bytes", 0) for row in rows),
        "processes": rows,
    }
    if os.name == "nt" and job is not None:
        try:
            accounting = job.accounting()
        except Exception as exc:  # noqa: BLE001 - caller fails closed when I/O is capped
            result.update({
                "io_accounting_available": False,
                "io_accounting_error": f"{type(exc).__name__}: {exc}",
            })
        else:
            result.update({
                "io_accounting_available": True,
                "io_accounting_source": "windows_job_object_lifetime",
                "read_operation_count": int(
                    accounting.get("read_operation_count") or 0
                ),
                "write_operation_count": int(
                    accounting.get("write_operation_count") or 0
                ),
                "read_bytes": int(accounting.get("read_bytes") or 0),
                "write_bytes": int(accounting.get("write_bytes") or 0),
            })
    else:
        result.update({
            "io_accounting_available": bool(rows),
            "io_accounting_source": "sampled_process_group",
        })
    return result


def run_isolated_subprocess(
    command,
    *,
    timeout_seconds=None,
    working_set_max_bytes=None,
    private_memory_max_bytes=None,
    cwd=None,
    env=None,
    output_tail_chars=DEFAULT_CHILD_OUTPUT_TAIL_CHARS,
    output_max_bytes=None,
    io_read_max_bytes=None,
    io_write_max_bytes=None,
    on_started=None,
    resource_sample_interval_seconds=0.2,
    resource_sampling_grace_seconds=1.0,
):
    """Run a heavy command inside a memory/I/O-bounded, killable process tree.

    Windows launches the root suspended, assigns it to a Job Object, and only
    then resumes it.  That ordering is essential for venv/store launchers: the
    real interpreter descendants inherit the Job Object before they can exist.
    POSIX launches a new session and terminates only that process group.
    """
    started = time.time()
    command_row = [str(item) for item in command]
    process = None
    job = None
    process_lifetime_tracker = None
    output_capture = None
    stdout = ""
    stderr = ""
    timed_out = False
    runner_error = None
    termination = {
        "triggered": False,
        "reason": "not_required",
        "tree_termination_requested": False,
    }
    # Backward compatibility: callers historically supplied the misleadingly
    # named working-set value as their only Job Object private-commit cap.
    # Keep that fail-closed behavior while also applying a real working-set cap.
    private_limit = (
        int(private_memory_max_bytes)
        if private_memory_max_bytes and int(private_memory_max_bytes) > 0
        else int(working_set_max_bytes)
        if working_set_max_bytes and int(working_set_max_bytes) > 0
        else None
    )
    working_set_limit = (
        int(working_set_max_bytes)
        if working_set_max_bytes and int(working_set_max_bytes) > 0
        else None
    )
    io_read_limit = (
        int(io_read_max_bytes) if io_read_max_bytes is not None else None
    )
    io_write_limit = (
        int(io_write_max_bytes) if io_write_max_bytes is not None else None
    )
    if io_read_limit is not None and io_read_limit < 0:
        raise ValueError("io_read_max_bytes must be non-negative")
    if io_write_limit is not None and io_write_limit < 0:
        raise ValueError("io_write_max_bytes must be non-negative")
    memory_limits = {
        "requested": bool(private_limit or working_set_limit),
        "applied": False,
        "max_bytes": private_limit or working_set_limit,
        "private_memory_max_bytes": private_limit,
        "working_set_max_bytes": working_set_limit,
        "job_commit_cap": False,
        "working_set_cap": False,
    }
    if not memory_limits["requested"]:
        memory_limits["reason"] = "no_limit"
    resource_peaks = {
        "sample_count": 0,
        "sampled_working_set_peak_bytes": 0,
        "working_set_peak_bytes": 0,
        "private_memory_peak_bytes": 0,
        "max_process_count": 0,
        "last_sample": {},
        "process_lifetime": {},
    }
    resource_io = {
        "read_operation_count": 0,
        "write_operation_count": 0,
        "read_bytes": 0,
        "write_bytes": 0,
        "source": "sampled_process_tree",
        "read_limit_bytes": io_read_limit,
        "write_limit_bytes": io_write_limit,
        "enforcement_requested": bool(
            io_read_limit is not None or io_write_limit is not None
        ),
    }
    resource_limit_exceeded = None
    memory_sampling_enforcement_required = False
    io_sampling_enforcement_required = bool(
        io_read_limit is not None or io_write_limit is not None
    )
    sampling_unavailable_started = None
    io_sampling_unavailable_started = None
    io_sample_count = 0
    io_lifetime_accounting_verified = False
    containment = {
        "requested": True,
        "status": "PENDING",
        "platform": "windows" if os.name == "nt" else "posix",
        "process_tree_contained": False,
        "root_created_suspended": False,
        "assigned_before_resume": False,
        "kill_on_container_close": False,
        "memory_limit": memory_limits,
    }

    popen_kwargs = {
        "text": False,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": cwd,
        "env": env,
    }
    try:
        if os.name == "nt":
            job = _WindowsJobObject(
                private_memory_limit_bytes=private_limit,
                working_set_limit_bytes=working_set_limit,
            )
            process_lifetime_tracker = WindowsProcessLifetimeTracker()
            process_lifetime_tracker.attach(job)
            memory_limits = job.memory_limit
            containment.update({
                "method": "windows_job_object",
                "root_created_suspended": True,
                "kill_on_container_close": True,
                "memory_limit": memory_limits,
            })
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            popen_kwargs["start_new_session"] = True
            containment.update({
                "method": "posix_process_group",
                "kill_on_container_close": False,
            })
            if memory_limits["requested"]:
                memory_limits.update({
                    "reason": "non_windows",
                    "scope": "not_applied",
                })
        process = subprocess.Popen(command_row, **popen_kwargs)
        output_capture = _BoundedPipeCapture(
            process.stdout,
            process.stderr,
            tail_bytes=output_tail_chars,
            max_bytes=output_max_bytes,
        )
        if os.name == "nt":
            job.assign(process._handle)  # noqa: SLF001 - Win32 handle is required for Job assignment
            process_lifetime_tracker.capture(job)
            if not process_lifetime_tracker.has_retained_process(
                process.pid
            ):
                raise RuntimeError(
                    "suspended root process handle was not retained"
                )
            containment.update({
                "status": "PENDING",
                "process_tree_contained": True,
                "assigned_before_resume": True,
                "root_pid": process.pid,
            })
            if on_started is not None:
                on_started({
                    "pid": process.pid,
                    "command": command_row,
                    "containment": dict(containment),
                    "memory_limits": dict(memory_limits),
                    "started_before_user_code": True,
                })
            resume = _resume_suspended_windows_process(process.pid)
            containment.update({"status": "PASS", "resume": resume})
            # JOB_OBJECT_LIMIT_WORKINGSET is per process. The declared budget
            # is for the entire child tree, so aggregate sampling remains
            # mandatory even when the kernel flag is available.
            memory_sampling_enforcement_required = bool(working_set_limit)
        else:
            containment.update({
                "status": "PASS",
                "process_tree_contained": True,
                "assigned_before_resume": True,
                "process_group_id": process.pid,
                "root_pid": process.pid,
            })
            if on_started is not None:
                on_started({
                    "pid": process.pid,
                    "command": command_row,
                    "containment": dict(containment),
                    "memory_limits": dict(memory_limits),
                    "started_before_user_code": False,
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
                process.wait(timeout=5)
            except Exception:  # noqa: BLE001 - process never ran user code while suspended
                pass
            if output_capture is not None:
                stdout, stderr, capture_error = output_capture.finish(timeout=5)
                if capture_error:
                    containment["output_capture_error"] = capture_error
        if process_lifetime_tracker is not None:
            process_lifetime_tracker.close()
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
            "working_set_limit": memory_limits,
            "resource_peaks": resource_peaks,
            "resource_io": resource_io,
            "resource_limit_exceeded": resource_limit_exceeded,
            "containment": containment,
            "termination": termination,
            "runner_error": containment["error"],
        }

    try:
        try:
            deadline = (
                started + float(timeout_seconds)
                if timeout_seconds is not None and float(timeout_seconds) > 0
                else None
            )
            sample_interval = max(0.02, float(resource_sample_interval_seconds or 0.2))
            while True:
                if process_lifetime_tracker is not None:
                    process_lifetime_tracker.capture(job)
                sample = _contained_process_memory_metrics(job, process.pid)
                io_sample_available = bool(
                    sample.get("available")
                    and sample.get("io_accounting_available", True)
                    and "read_bytes" in sample
                    and "write_bytes" in sample
                )
                if sample.get("available"):
                    sampling_unavailable_started = None
                    resource_peaks["sample_count"] += 1
                    resource_peaks["working_set_peak_bytes"] = max(
                        resource_peaks["working_set_peak_bytes"],
                        int(sample.get("working_set_bytes") or 0),
                    )
                    resource_peaks["sampled_working_set_peak_bytes"] = max(
                        resource_peaks["sampled_working_set_peak_bytes"],
                        int(sample.get("working_set_bytes") or 0),
                    )
                    resource_peaks["private_memory_peak_bytes"] = max(
                        resource_peaks["private_memory_peak_bytes"],
                        int(sample.get("private_bytes") or 0),
                    )
                    resource_peaks["max_process_count"] = max(
                        resource_peaks["max_process_count"],
                        int(sample.get("process_count") or 0),
                    )
                    resource_peaks["last_sample"] = sample
                    for metric in (
                        "read_operation_count",
                        "write_operation_count",
                        "read_bytes",
                        "write_bytes",
                    ):
                        resource_io[metric] = max(
                            int(resource_io.get(metric) or 0),
                            int(sample.get(metric) or 0),
                        )
                    if io_sample_available:
                        io_sample_count += 1
                    if (
                        working_set_limit
                        and int(sample.get("working_set_bytes") or 0) > working_set_limit
                    ):
                        resource_limit_exceeded = {
                            "resource": "working_set_bytes",
                            "observed_bytes": int(sample["working_set_bytes"]),
                            "limit_bytes": int(working_set_limit),
                            "sample": sample,
                        }
                    elif (
                        private_limit
                        and int(sample.get("private_bytes") or 0) > private_limit
                    ):
                        resource_limit_exceeded = {
                            "resource": "private_memory_bytes",
                            "observed_bytes": int(sample["private_bytes"]),
                            "limit_bytes": int(private_limit),
                            "sample": sample,
                        }
                    elif (
                        io_read_limit is not None
                        and io_sample_available
                        and int(sample.get("read_bytes") or 0) > io_read_limit
                    ):
                        resource_limit_exceeded = {
                            "resource": "io_read_bytes",
                            "observed_bytes": int(sample.get("read_bytes") or 0),
                            "limit_bytes": int(io_read_limit),
                            "sample": sample,
                            "detected_from": str(
                                sample.get("io_accounting_source")
                                or "sampled_process_tree"
                            ),
                        }
                    elif (
                        io_write_limit is not None
                        and io_sample_available
                        and int(sample.get("write_bytes") or 0) > io_write_limit
                    ):
                        resource_limit_exceeded = {
                            "resource": "io_write_bytes",
                            "observed_bytes": int(sample.get("write_bytes") or 0),
                            "limit_bytes": int(io_write_limit),
                            "sample": sample,
                            "detected_from": str(
                                sample.get("io_accounting_source")
                                or "sampled_process_tree"
                            ),
                        }
                elif sample.get("error"):
                    resource_peaks["last_sample"] = sample
                if memory_sampling_enforcement_required and not sample.get("available"):
                    if sampling_unavailable_started is None:
                        sampling_unavailable_started = time.time()
                    if (
                        time.time() - sampling_unavailable_started
                        >= max(0.1, float(resource_sampling_grace_seconds or 1.0))
                    ):
                        resource_limit_exceeded = {
                            "resource": "working_set_enforcement",
                            "limit_bytes": int(working_set_limit),
                            "reason": "process_tree_memory_sampling_unavailable",
                            "sample": sample,
                        }
                if io_sampling_enforcement_required and not io_sample_available:
                    if io_sampling_unavailable_started is None:
                        io_sampling_unavailable_started = time.time()
                    if (
                        resource_limit_exceeded is None
                        and time.time() - io_sampling_unavailable_started
                        >= max(0.1, float(resource_sampling_grace_seconds or 1.0))
                    ):
                        resource_limit_exceeded = {
                            "resource": "io_enforcement",
                            "read_limit_bytes": io_read_limit,
                            "write_limit_bytes": io_write_limit,
                            "reason": "process_tree_io_sampling_unavailable",
                            "sample": sample,
                        }
                else:
                    io_sampling_unavailable_started = None

                if (
                    output_capture is not None
                    and output_capture.exceeded_limit()
                    and resource_limit_exceeded is None
                ):
                    resource_limit_exceeded = {
                        "resource": "child_output_bytes",
                        "observed_bytes": output_capture.total_bytes(),
                        "limit_bytes": int(output_max_bytes),
                        "detected_from": "bounded_parent_pipe_capture",
                    }

                reason = None
                exit_code = None
                if resource_limit_exceeded:
                    reason = "resource_budget_exceeded"
                    exit_code = 137
                elif deadline is not None and time.time() >= deadline:
                    reason = "timeout"
                    exit_code = 124
                    timed_out = True

                if reason is not None:
                    if job is not None:
                        try:
                            job.terminate(exit_code=exit_code)
                            termination = {
                                "triggered": True,
                                "reason": reason,
                                "method": "TerminateJobObject",
                                "tree_termination_requested": True,
                            }
                        except Exception as exc:  # noqa: BLE001
                            termination = {
                                "triggered": False,
                                "reason": reason,
                                "method": "TerminateJobObject",
                                "tree_termination_requested": False,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                    else:
                        termination = _terminate_posix_process_group(
                            process.pid,
                            reason=reason,
                        )
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if job is not None:
                            process.kill()
                        else:
                            termination["escalation"] = _terminate_posix_process_group(
                                process.pid,
                                reason=f"{reason}_escalation",
                                force=True,
                            )
                        process.wait(timeout=5)
                    break

                remaining = deadline - time.time() if deadline is not None else None
                wait_seconds = (
                    min(sample_interval, max(0.02, remaining))
                    if remaining is not None
                    else sample_interval
                )
                try:
                    process.wait(timeout=wait_seconds)
                    break
                except subprocess.TimeoutExpired:
                    continue
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
                process.wait(timeout=5)
            except Exception:  # noqa: BLE001 - preserve the original runner exception
                pass
            if not isinstance(exc, Exception):
                raise
            runner_error = f"{type(exc).__name__}: {exc}"

        if output_capture is not None:
            stdout, stderr, capture_error = output_capture.finish(timeout=1)
            if capture_error and "did not reach EOF" in capture_error:
                if job is not None:
                    try:
                        job.terminate(exit_code=0)
                        termination = {
                            "triggered": True,
                            "reason": "descendant_cleanup",
                            "method": "TerminateJobObject",
                            "tree_termination_requested": True,
                        }
                    except Exception as exc:  # noqa: BLE001
                        capture_error = f"{capture_error}; {type(exc).__name__}: {exc}"
                else:
                    termination = _finish_posix_process_group(process.pid, termination)
                stdout, stderr, retry_error = output_capture.finish(timeout=5)
                capture_error = retry_error
            if capture_error:
                runner_error = runner_error or f"bounded output capture failed: {capture_error}"
            if output_capture.exceeded_limit() and resource_limit_exceeded is None:
                resource_limit_exceeded = {
                    "resource": "child_output_bytes",
                    "observed_bytes": output_capture.total_bytes(),
                    "limit_bytes": int(output_max_bytes),
                    "detected_from": "bounded_parent_pipe_capture_post_exit",
                }

        if (
            memory_sampling_enforcement_required
            and resource_peaks["sample_count"] == 0
            and resource_limit_exceeded is None
        ):
            runner_error = "working-set enforcement unavailable: no process-tree sample"
            containment.update({
                "status": "BLOCK",
                "error": runner_error,
                "working_set_enforcement": "unverified",
            })
        if job is not None:
            try:
                accounting = job.accounting()
                quiescence_deadline = time.time() + 0.5
                while (
                    accounting.get("active_processes", 0) > 0
                    and time.time() < quiescence_deadline
                ):
                    time.sleep(0.02)
                    accounting = job.accounting()
                if int(accounting.get("active_processes") or 0) > 0:
                    if not termination.get("triggered"):
                        job.terminate(exit_code=0)
                        termination = {
                            "triggered": True,
                            "reason": "descendant_cleanup",
                            "method": "TerminateJobObject",
                            "tree_termination_requested": True,
                            "active_processes_before_termination": int(
                                accounting["active_processes"]
                            ),
                        }
                    cleanup_deadline = time.time() + 5
                    while (
                        int(accounting.get("active_processes") or 0) > 0
                        and time.time() < cleanup_deadline
                    ):
                        time.sleep(0.02)
                        accounting = job.accounting()
                io_lifetime_accounting_verified = (
                    int(accounting.get("active_processes") or 0) == 0
                )
                if process_lifetime_tracker is not None:
                    lifetime = process_lifetime_tracker.finalize(accounting)
                    resource_peaks["process_lifetime"] = lifetime
                    accounting = dict(
                        lifetime.get("final_job_accounting") or accounting
                    )
                    if lifetime.get("status") == "PASS":
                        lifetime_working_set = int(
                            lifetime.get(
                                "lifetime_working_set_upper_bound_bytes"
                            )
                            or 0
                        )
                        resource_peaks["working_set_peak_bytes"] = max(
                            int(resource_peaks["working_set_peak_bytes"]),
                            lifetime_working_set,
                        )
                        resource_peaks["max_process_count"] = max(
                            int(resource_peaks["max_process_count"]),
                            int(lifetime.get("tracked_process_count") or 0),
                        )
                        if (
                            resource_limit_exceeded is None
                            and working_set_limit
                            and lifetime_working_set > working_set_limit
                        ):
                            resource_limit_exceeded = {
                                "resource": "working_set_bytes",
                                "observed_bytes": lifetime_working_set,
                                "limit_bytes": int(working_set_limit),
                                "detected_from": (
                                    "windows_terminal_process_lifetime_peaks"
                                ),
                            }
                    else:
                        runner_error = (
                            runner_error
                            or "Windows process-lifetime accounting failed"
                        )
                        containment.update({
                            "status": "BLOCK",
                            "error": runner_error,
                            "process_lifetime_accounting": "FAIL",
                        })
                containment["accounting"] = accounting
                resource_io.update({
                    "read_operation_count": int(accounting.get("read_operation_count") or 0),
                    "write_operation_count": int(accounting.get("write_operation_count") or 0),
                    "read_bytes": int(accounting.get("read_bytes") or 0),
                    "write_bytes": int(accounting.get("write_bytes") or 0),
                    "other_operation_count": int(accounting.get("other_operation_count") or 0),
                    "other_bytes": int(accounting.get("other_bytes") or 0),
                    "source": "windows_job_object_lifetime",
                })
                resource_peaks["private_memory_peak_bytes"] = max(
                    resource_peaks["private_memory_peak_bytes"],
                    int(accounting.get("peak_job_memory_bytes") or 0),
                )
                if (
                    resource_limit_exceeded is None
                    and io_read_limit is not None
                    and int(resource_io.get("read_bytes") or 0) > io_read_limit
                ):
                    resource_limit_exceeded = {
                        "resource": "io_read_bytes",
                        "observed_bytes": int(resource_io.get("read_bytes") or 0),
                        "limit_bytes": int(io_read_limit),
                        "detected_from": "windows_job_object_lifetime_post_exit",
                    }
                elif (
                    resource_limit_exceeded is None
                    and io_write_limit is not None
                    and int(resource_io.get("write_bytes") or 0) > io_write_limit
                ):
                    resource_limit_exceeded = {
                        "resource": "io_write_bytes",
                        "observed_bytes": int(resource_io.get("write_bytes") or 0),
                        "limit_bytes": int(io_write_limit),
                        "detected_from": "windows_job_object_lifetime_post_exit",
                    }
                if (
                    resource_limit_exceeded is not None
                    and str(resource_limit_exceeded.get("resource") or "").startswith("io_")
                    and not termination.get("triggered")
                ):
                    termination = {
                        "triggered": False,
                        "reason": "resource_budget_exceeded",
                        "method": "windows_job_object_lifetime_post_exit",
                        "tree_termination_requested": False,
                        "process_exited_over_limit": True,
                    }
                if (
                    resource_limit_exceeded is not None
                    and resource_limit_exceeded.get("detected_from")
                    == "windows_terminal_process_lifetime_peaks"
                    and not termination.get("triggered")
                ):
                    termination = {
                        "triggered": False,
                        "reason": "resource_budget_exceeded",
                        "method": (
                            "windows_terminal_process_lifetime_peaks"
                        ),
                        "tree_termination_requested": False,
                        "process_exited_over_limit": True,
                    }
                if (
                    resource_limit_exceeded is None
                    and private_limit
                    and process.returncode not in {None, 0}
                    and (
                        int(accounting.get("peak_job_memory_bytes") or 0)
                        >= int(private_limit * 0.9)
                        or "MemoryError" in (stderr or "")
                    )
                ):
                    resource_limit_exceeded = {
                        "resource": "private_memory_bytes",
                        "observed_bytes": int(
                            accounting.get("peak_job_memory_bytes") or 0
                        ),
                        "limit_bytes": int(private_limit),
                        "detected_from": (
                            "child_memory_error_under_windows_job_limit"
                            if "MemoryError" in (stderr or "")
                            else "windows_job_object_peak_after_nonzero_exit"
                        ),
                    }
                    if not termination.get("triggered"):
                        termination = {
                            "triggered": True,
                            "reason": "resource_budget_exceeded",
                            "method": "windows_job_object_limit",
                            "tree_termination_requested": False,
                            "process_exited_under_limit": True,
                        }
                termination["tree_scope"] = "windows_job_object"
                termination["tree_terminated"] = (
                    accounting.get("active_processes", 0) == 0
                    or bool(termination.get("triggered"))
                )
            except Exception as exc:  # noqa: BLE001 - close still enforces kill-on-close
                detail = f"{type(exc).__name__}: {exc}"
                containment.update({
                    "status": "BLOCK",
                    "accounting_error": detail,
                    "error": detail,
                })
                runner_error = (
                    runner_error
                    or f"Windows Job lifetime accounting failed: {detail}"
                )
                termination["tree_terminated_on_container_close"] = True
        else:
            termination = _finish_posix_process_group(process.pid, termination)
            termination["tree_scope"] = "posix_process_group"
        if (
            io_sampling_enforcement_required
            and io_sample_count == 0
            and not io_lifetime_accounting_verified
            and resource_limit_exceeded is None
        ):
            runner_error = (
                runner_error
                or "I/O enforcement unavailable: no contained process-tree sample "
                "or lifetime accounting"
            )
            containment.update({
                "status": "BLOCK",
                "error": runner_error,
                "io_enforcement": "unverified",
            })
    finally:
        if process_lifetime_tracker is not None:
            process_lifetime_tracker.close()
        if job is not None:
            job.close()

    memory_limits["working_set_enforcement_verified"] = bool(
        not working_set_limit
        or (
            resource_peaks["sample_count"] > 0
            and (
                os.name != "nt"
                or (
                    resource_peaks.get("process_lifetime") or {}
                ).get("status")
                == "PASS"
            )
        )
    )
    resource_io["enforcement_verified"] = bool(
        not io_sampling_enforcement_required
        or io_sample_count > 0
        or io_lifetime_accounting_verified
    )
    resource_io["sample_count"] = io_sample_count

    tail = max(0, int(output_tail_chars or 0))
    return {
        "command": command_row,
        "pid": process.pid,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-tail:] if tail else "",
        "stderr": (stderr or "")[-tail:] if tail else "",
        "duration_seconds": round(time.time() - started, 3),
        "working_set_limit": memory_limits,
        "resource_peaks": resource_peaks,
        "resource_io": resource_io,
        "resource_limit_exceeded": resource_limit_exceeded,
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
    owner_identity = current_process_identity()
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
        LOCK_OWNER_IDENTITY_FIELD: owner_identity,
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
            LOCK_OWNER_IDENTITY_FIELD: owner_identity,
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
