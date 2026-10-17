"""The single process-memory probe on maker replay v2 paths (CONSOLIDATED row 13, binding: DECISION_LOG 2026-10-15).

The frozen v0.1 probe (``maker_core.replay.ceilings.process_memory``) defines a ``ctypes.Structure`` and a ``POINTER``
type on every call; CPython 3.11 keeps both in ``ctypes._pointer_type_cache`` for ever (about 7 KB a call, B-risks
"The ceilings memory leak"), and it rewrites ``argtypes`` on the process-wide ``ctypes.windll.psapi`` function. That
file is frozen (the v1 hashed set) and stays untouched; v2 code reads memory here instead:

- ``_Counters`` is defined once at module level, and one buffer is reused;
- the Windows libraries are private ``ctypes.WinDLL`` handles created once, so the shared ``ctypes.windll`` function
  objects (and their ``argtypes``) are never touched (B-defender D11);
- ``counters()`` returns the raw working-set and pagefile fields; ``process_memory()`` returns (current, peak) as
  the frozen probe does: the larger of working set and private commit on Windows, and on POSIX ``/proc/self/statm``
  and ``ru_maxrss`` (KiB on Linux, bytes on macOS; peak RSS only, so the two platforms' numbers are not comparable).

No other module under ``maker_core/replay/v2`` or ``tools/research/maker_replay_v2`` probes process memory
(``tests/maker_core/test_replay_v2_host.py`` holds that ratchet).
"""
from __future__ import annotations

import ctypes
import os
import sys


class _Counters(ctypes.Structure):
    """PROCESS_MEMORY_COUNTERS."""
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_POINTER = ctypes.POINTER(_Counters)  # created once; the per-call POINTER is what the frozen probe leaks
_state = {}


def _windows():
    """(GetProcessMemoryInfo, process handle, buffer), built once on private library handles."""
    if not _state:
        from ctypes import wintypes
        kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, _POINTER, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        buffer = _Counters()
        buffer.cb = ctypes.sizeof(_Counters)
        _state.update(kernel32=kernel32, psapi=psapi, handle=kernel32.GetCurrentProcess(), buffer=buffer)
    return _state


def counters():
    """Windows only: {working_set, peak_working_set, pagefile, peak_pagefile} bytes of this process."""
    if os.name != "nt":
        raise OSError("process_memory_counters_windows_only")
    state = _windows()
    buffer = state["buffer"]
    if not state["psapi"].GetProcessMemoryInfo(state["handle"], ctypes.byref(buffer), buffer.cb):
        raise OSError("process_memory_unavailable")
    return dict(working_set=buffer.WorkingSetSize, peak_working_set=buffer.PeakWorkingSetSize,
                pagefile=buffer.PagefileUsage, peak_pagefile=buffer.PeakPagefileUsage)


def process_memory():
    """(current, peak) bytes: the larger of working set and private commit on Windows (the frozen probe's rule)."""
    if os.name == "nt":
        c = counters()
        return max(c["working_set"], c["pagefile"]), max(c["peak_working_set"], c["peak_pagefile"])
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    try:
        with open("/proc/self/statm", "rb") as handle:
            current = int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        current = peak
    return current, peak
