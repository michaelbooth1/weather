"""Clarification 2 operational ceilings: one measured calibration day, a fixed rule, host caps.

The measurement is resource-only: bytes, records, engine events, decision/span
counts, peak memory and runtime. It never carries a score, fill, reward or hurdle
value. Each ceiling is ``measurement x 15 x 4`` rounded up to a power of two in the
ceiling's own unit, then compared with the 16 GB host cap. A binding host cap makes
the scored run not executable here; the panel is never sampled or truncated to fit.
"""
from __future__ import annotations

import math
import os
import sys
import time
from datetime import date

from maker_core.replay.bundle import BundleError, HOST_MAX_BYTES, HOST_MAX_SECONDS, HOST_RAM_BYTES
from maker_core.replay.engine import MAX_ENGINE_EVENTS

FORMAT = "maker_core.replay.ceiling_measurement.v1"
RULE = "clarification_2_measurement_x15_x4_next_power_of_two_host_capped"
MEASUREMENT_DATE = date(2026, 9, 27)
MULTIPLIER = 15 * 4
MAX_COMMIT_PERCENT = 70.0
# The unit of each field is the unit of the ceiling it derives.
MEASURED = ("input_bytes", "records", "engine_events", "decisions_spans", "peak_memory_bytes", "runtime_seconds")
HOST_CAPS = dict(input_bytes=HOST_MAX_BYTES, records=MAX_ENGINE_EVENTS, engine_events=MAX_ENGINE_EVENTS,
                 decisions_spans=MAX_ENGINE_EVENTS, peak_memory_bytes=HOST_MAX_BYTES,
                 runtime_seconds=int(HOST_MAX_SECONDS))
HOST = dict(ram_bytes=HOST_RAM_BYTES, max_commit_percent=MAX_COMMIT_PERCENT, max_seconds=HOST_MAX_SECONDS)


def next_power_of_two(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BundleError("invalid_measurement_value")
    return 1 if value <= 1 else 2 ** math.ceil(math.log2(value))


def derive(measured):
    """Apply the rule; ``executable`` is False when any host cap binds below it."""
    if not isinstance(measured, dict) or set(measured) != set(MEASURED):
        raise BundleError("incomplete_ceiling_measurement")
    rule = {name: next_power_of_two(measured[name] * MULTIPLIER) for name in MEASURED}
    binding = sorted(name for name in MEASURED if rule[name] > HOST_CAPS[name])
    return dict(rule=RULE, multiplier=MULTIPLIER, host=HOST, host_caps=HOST_CAPS, rule_values=rule,
                host_cap_binding=binding, executable=not binding, ceilings=None if binding else rule)


def run_limits(derived):
    """CLI/engine ceilings bound by a manifest; refuse when the host cap binds."""
    if not derived.get("executable"):
        raise BundleError("not_executable_on_host:" + ",".join(derived.get("host_cap_binding", ())))
    c = derived["ceilings"]
    return dict(max_input_bytes=c["input_bytes"], max_records=c["records"], max_seconds=float(c["runtime_seconds"]),
                max_events=c["engine_events"], max_outputs=c["decisions_spans"],
                max_memory_bytes=c["peak_memory_bytes"])


def _windows_process_memory():
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("process_memory_unavailable")
    return (max(counters.WorkingSetSize, counters.PagefileUsage),
            max(counters.PeakWorkingSetSize, counters.PeakPagefileUsage))


def process_memory():
    """(current, peak) bytes: the larger of working set and private commit on Windows."""
    if os.name == "nt":
        return _windows_process_memory()
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    try:
        with open("/proc/self/statm", "rb") as handle:
            current = int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        current = peak
    return current, peak


def commit_percent():
    """System commit charge as a percentage of the commit limit, or None if unmeasurable."""
    if os.name == "nt":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = Status()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) or not status.ullTotalPageFile:
            return None
        return 100.0 * (status.ullTotalPageFile - status.ullAvailPageFile) / status.ullTotalPageFile
    try:
        values = {}
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("CommitLimit:", "Committed_AS:")):
                    key, value, *_ = line.split()
                    values[key.rstrip(":")] = int(value)
        return 100.0 * values["Committed_AS"] / values["CommitLimit"] if values.get("CommitLimit") else None
    except (OSError, ValueError, KeyError):
        return None


def host_preflight(*, commit=None):
    """Operational refusal before any score: an unmeasurable or high commit charge."""
    value = (commit or commit_percent)()
    if value is None or not math.isfinite(value) or not 0 <= value < MAX_COMMIT_PERCENT:
        raise BundleError("host_commit_charge_not_below_70_percent")
    return value


def guarded(check, max_memory_bytes, *, memory=None, clock=time.monotonic, interval=0.25):
    """Wrap a deadline check with a sampled process-memory ceiling."""
    last = [None]

    def wrapped():
        check()
        now = clock()
        if last[0] is None or now - last[0] >= interval:
            last[0] = now
            if (memory or process_memory)()[0] > max_memory_bytes:
                raise BundleError("memory_ceiling")
    return wrapped
