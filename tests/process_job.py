"""Kill-on-close Windows Job containment for test-owned child processes.

Guards: no raw parent-PID tree kill in tests (master ruling 2026-11-01, lane L33). A
parent-PID walk (the tree switch of the Windows task-kill tool) also kills any unrelated long-lived process whose
parent has exited and whose stale ``ParentProcessId`` matches the PID being killed;
that most likely killed every workstation forward recorder at once on 2026-11-01.

:class:`KillOnCloseJob` is the Python twin of ``scripts/ops/windows_kill_on_close_job.ps1``:
the child is created suspended, assigned to a Job with
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` and only then resumed, so it and every
descendant are Job members from their first instruction. :meth:`KillOnCloseJob.terminate`
ends exactly the Job's members, and closing the Job (or the test process dying) does
the same. No process outside the Job is ever touched, whatever its parent PID says.

Standard library only (``ctypes``); the Windows API is loaded lazily so importing this
module is harmless off Windows.
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Any

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _BasicLimitInformation(ctypes.Structure):
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


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _BasicAccountingInformation(ctypes.Structure):
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


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


_KERNEL32: Any = None


def _kernel32() -> Any:
    global _KERNEL32
    if _KERNEL32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.CreateJobObjectW.restype = handle
        k.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, dword]
        k.SetInformationJobObject.restype = boolean
        k.QueryInformationJobObject.argtypes = [
            handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.POINTER(dword)]
        k.QueryInformationJobObject.restype = boolean
        k.AssignProcessToJobObject.argtypes = [handle, handle]
        k.AssignProcessToJobObject.restype = boolean
        k.TerminateJobObject.argtypes = [handle, ctypes.c_uint]
        k.TerminateJobObject.restype = boolean
        k.OpenProcess.argtypes = [dword, boolean, dword]
        k.OpenProcess.restype = handle
        k.OpenThread.argtypes = [dword, boolean, dword]
        k.OpenThread.restype = handle
        k.ResumeThread.argtypes = [handle]
        k.ResumeThread.restype = dword
        k.CreateToolhelp32Snapshot.argtypes = [dword, dword]
        k.CreateToolhelp32Snapshot.restype = handle
        k.Thread32First.argtypes = [handle, ctypes.POINTER(_ThreadEntry32)]
        k.Thread32First.restype = boolean
        k.Thread32Next.argtypes = [handle, ctypes.POINTER(_ThreadEntry32)]
        k.Thread32Next.restype = boolean
        k.CloseHandle.argtypes = [handle]
        k.CloseHandle.restype = boolean
        _KERNEL32 = k
    return _KERNEL32


def _fail(what: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), what)


def _resume_suspended_process(pid: int) -> None:
    """Resume every thread of a process created with ``CREATE_SUSPENDED``."""
    k = _kernel32()
    snapshot = k.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        raise _fail("CreateToolhelp32Snapshot failed")
    resumed = 0
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        more = k.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = k.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if not thread:
                    raise _fail("OpenThread failed")
                try:
                    if k.ResumeThread(thread) == 0xFFFFFFFF:
                        raise _fail("ResumeThread failed")
                    resumed += 1
                finally:
                    k.CloseHandle(thread)
            more = k.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    if resumed == 0:
        raise RuntimeError(f"no thread found to resume for suspended pid {pid}")


class KillOnCloseJob:
    """A kill-on-close Job owning test-started children and all their descendants."""

    def __init__(self) -> None:
        k = _kernel32()
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            raise _fail("CreateJobObject failed")
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = _fail("SetInformationJobObject(KILL_ON_JOB_CLOSE) failed")
            k.CloseHandle(handle)
            raise error
        self._handle: int | None = handle

    def _require_handle(self) -> int:
        if self._handle is None:
            raise ValueError("KillOnCloseJob is closed")
        return self._handle

    def popen(self, args: Any, **kwargs: Any) -> subprocess.Popen:
        """``subprocess.Popen`` whose child is a Job member before it runs any code."""
        job = self._require_handle()
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_SUSPENDED
        process = subprocess.Popen(args, **kwargs)
        k = _kernel32()
        try:
            # The child is suspended and Popen holds its handle, so its PID cannot
            # be reused before this OpenProcess.
            target = k.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid)
            if not target:
                raise _fail("OpenProcess for Job assignment failed")
            try:
                if not k.AssignProcessToJobObject(job, target):
                    raise _fail("AssignProcessToJobObject before resume failed")
            finally:
                k.CloseHandle(target)
            _resume_suspended_process(process.pid)
        except BaseException:
            process.kill()
            process.wait(timeout=30)
            raise
        return process

    def active_process_count(self) -> int:
        info = _BasicAccountingInformation()
        returned = wintypes.DWORD()
        if not _kernel32().QueryInformationJobObject(
            self._require_handle(), _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned),
        ):
            raise _fail("QueryInformationJobObject(accounting) failed")
        return int(info.ActiveProcesses)

    def terminate(self, timeout: float = 10.0, exit_code: int = 1) -> None:
        """Terminate every Job member and wait until the Job has none left."""
        if not _kernel32().TerminateJobObject(self._require_handle(), exit_code):
            raise _fail("TerminateJobObject failed")
        deadline = time.monotonic() + timeout
        while self.active_process_count():
            if time.monotonic() >= deadline:
                raise TimeoutError("Job members did not reach zero active processes")
            time.sleep(0.01)

    def close(self) -> None:
        """Close the Job handle; any member still running is terminated by Windows."""
        handle, self._handle = self._handle, None
        if handle is not None:
            _kernel32().CloseHandle(handle)

    def __enter__(self) -> "KillOnCloseJob":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def terminate_job_and_wait(
    job: KillOnCloseJob, process: subprocess.Popen, *, timeout: float = 60.0
) -> None:
    """Kill ``process`` and its descendants through their Job only, then reap ``process``.

    The Job is terminated even when ``process`` has already exited, because its
    descendants may still be running.
    """
    job.terminate(timeout=timeout)
    process.wait(timeout=timeout)
