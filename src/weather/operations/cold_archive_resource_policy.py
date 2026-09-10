"""Archive-only memory policy; other capture workloads keep their own defaults."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import os

GIB = 1024**3
MAX_COMMIT_PERCENT = 80.0
START_COMMIT_PERCENT = 78.0
MIN_AVAILABLE_BYTES = 4 * GIB
START_SAMPLES = 5
START_SAMPLE_SECONDS = 2
MAX_ADMISSION_WAIT_SECONDS = 600
MEASUREMENT_API = "GetPerformanceInfo"


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
            "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
            "KernelNonpaged", "PageSize")
    ] + [(name, wintypes.DWORD) for name in ("HandleCount", "ProcessCount", "ThreadCount")]


def measurement_from_pages(*, committed, limit, physical, available, page_size):
    values = (committed, limit, physical, available, page_size)
    if (any(type(value) is not int or value < 0 for value in values)
            or limit <= 0 or physical <= 0 or page_size <= 0
            or committed > limit or available > physical):
        return None
    return {
        "api": MEASUREMENT_API,
        "commit_total_bytes": committed * page_size,
        "commit_limit_bytes": limit * page_size,
        "physical_total_bytes": physical * page_size,
        "available_memory_bytes": available * page_size,
        "host_commit_percent": 100.0 * committed / limit,
    }


def read_host_memory():
    """Read coherent system-wide values, unaffected by this process's commit cap."""
    if os.name != "nt":
        return None
    try:
        counters = _PerformanceInformation()
        counters.cb = ctypes.sizeof(counters)
        api = ctypes.WinDLL("psapi", use_last_error=True).GetPerformanceInfo
        api.argtypes = [ctypes.POINTER(_PerformanceInformation), wintypes.DWORD]
        api.restype = wintypes.BOOL
        if not api(ctypes.byref(counters), counters.cb):
            return None
        return measurement_from_pages(
            committed=int(counters.CommitTotal), limit=int(counters.CommitLimit),
            physical=int(counters.PhysicalTotal), available=int(counters.PhysicalAvailable),
            page_size=int(counters.PageSize))
    except (AttributeError, OSError, ValueError, OverflowError):
        return None


class AdmissionStartWindow:
    """Five consecutive good observations; the dispatcher owns two-second spacing."""

    def __init__(self):
        self.consecutive = 0

    def observe(self, admission):
        commit = admission.get("host_commit_percent")
        available = admission.get("available_memory_bytes")
        ready = (
            admission.get("status") == "PASS"
            and type(commit) in (int, float) and math.isfinite(commit)
            and 0 <= commit < START_COMMIT_PERCENT
            and type(available) is int and available >= MIN_AVAILABLE_BYTES
        )
        self.consecutive = self.consecutive + 1 if ready else 0
        return self.consecutive >= START_SAMPLES
