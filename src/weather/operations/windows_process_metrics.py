"""Stable Win32 process memory and I/O sampler types."""

from __future__ import annotations

import os


# This sampler runs every 0.2 seconds while a bounded child is alive. Defining
# ctypes structures inside the hot function creates new POINTER classes on
# every sample; ctypes retains those classes in its process-wide pointer cache.
_WINDOWS_PROCESS_MEMORY_API = None
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _WindowsProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class _WindowsProcessIoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessIoCounters.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_WindowsProcessIoCounters),
    )
    kernel32.GetProcessIoCounters.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_WindowsProcessMemoryCountersEx),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    _WINDOWS_PROCESS_MEMORY_API = (
        ctypes,
        kernel32,
        psapi,
        _WindowsProcessMemoryCountersEx,
        _WindowsProcessIoCounters,
    )


def windows_process_memory_metrics(pid):
    """Return bounded memory and I/O counters without growing ctypes caches."""

    if _WINDOWS_PROCESS_MEMORY_API is None:
        return None
    ctypes, kernel32, psapi, memory_counters_type, io_counters_type = (
        _WINDOWS_PROCESS_MEMORY_API
    )
    process_query_limited_information = 0x1000
    process_vm_read = 0x0010
    handle = kernel32.OpenProcess(
        process_query_limited_information | process_vm_read,
        False,
        int(pid),
    )
    if not handle:
        return None
    try:
        counters = memory_counters_type()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        row = {
            "pid": int(pid),
            "working_set_bytes": int(counters.WorkingSetSize),
            "private_bytes": int(counters.PrivateUsage),
        }
        io_counters = io_counters_type()
        if kernel32.GetProcessIoCounters(handle, ctypes.byref(io_counters)):
            row.update({
                "read_operation_count": int(io_counters.ReadOperationCount),
                "write_operation_count": int(io_counters.WriteOperationCount),
                "read_bytes": int(io_counters.ReadTransferCount),
                "write_bytes": int(io_counters.WriteTransferCount),
            })
        return row
    finally:
        kernel32.CloseHandle(handle)
