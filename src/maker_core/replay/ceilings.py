"""Clarification 2 operational ceilings: three rehearsed calibration dates, a fixed rule, host limits.

Each calibration date gets its own score-free full-pipeline rehearsal (a fresh
process, so peak memory is per date). A rehearsal keeps only input bytes, records,
engine events, decisions plus spans, report bytes, runtime and peak memory above the
interpreter's pre-input baseline, never a score, fill, reward or hurdle value.
Each ceiling is the largest per-date value x 15 (fourteen quote dates plus settlement),
rounded up to the next power of two in its natural unit; the rounding is the only
headroom (up to 2x). The memory ceiling adds the unmultiplied baseline. A ceiling above
its host limit makes the scored run not executable on this host; nothing is sampled
or truncated. Under the 4 h runtime limit (largest power of two within it: 8,192 s) each
date's rehearsal must finish in at most ~546 s; under the memory limit each must peak at
most ~546 MiB above the baseline (8 GiB power of two plus the baseline within 70% of 16 GiB).
"""
from __future__ import annotations

import math
import os
import sys
import time

from maker_core.replay.bundle import BundleError, HOST_MAX_BYTES, HOST_MAX_SECONDS, HOST_RAM_BYTES
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.engine import MAX_ENGINE_EVENTS

FORMAT = "maker_core.replay.ceiling_measurement.v3"
REHEARSAL_FORMAT = "maker_core.replay.rehearsal.v2"
RULE = "clarification_2_max_of_three_dates_x15_next_power_of_two_plus_baseline_host_limited"
MULTIPLIER = 15
MAX_COMMIT_PERCENT = 70.0
# Multiplied quantities, each in the unit of the ceiling it derives.
MULTIPLIED = ("input_bytes", "records", "engine_events", "decisions_spans", "report_bytes", "runtime_seconds",
              "peak_memory_above_baseline_bytes")
MEASURED = (*MULTIPLIED, "baseline_memory_bytes")
# Host limits named by Clarification 2: memory, input and report bytes at most 70% of 16 GiB,
# runtime at most 4 h, and every count by the tooling's 2^31 representation limit.
HOST_LIMITS = dict(memory_bytes=HOST_MAX_BYTES, runtime_seconds=int(HOST_MAX_SECONDS),
                   input_bytes=HOST_MAX_BYTES, report_bytes=HOST_MAX_BYTES, records=MAX_ENGINE_EVENTS,
                   engine_events=MAX_ENGINE_EVENTS, decisions_spans=MAX_ENGINE_EVENTS)
HOST = dict(ram_bytes=HOST_RAM_BYTES, max_commit_percent=MAX_COMMIT_PERCENT, max_seconds=HOST_MAX_SECONDS)
NOT_EXECUTABLE = "not executable on this host"


def next_power_of_two(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BundleError("invalid_measurement_value")
    return 1 if value <= 1 else 2 ** math.ceil(math.log2(value))


def derive(per_date):
    """Apply the rule to {date: measured}; ``executable`` is False when any host limit binds."""
    if (not isinstance(per_date, dict) or sorted(per_date) != [d.isoformat() for d in CALIBRATION_DATES]
            or any(not isinstance(m, dict) or set(m) != set(MEASURED) for m in per_date.values())):
        raise BundleError("incomplete_ceiling_measurement")
    largest = {name: max(m[name] for m in per_date.values()) for name in MEASURED}
    rule = {name: next_power_of_two(largest[name] * MULTIPLIER) for name in MULTIPLIED}
    ceilings = {k: v for k, v in rule.items() if k != "peak_memory_above_baseline_bytes"}
    ceilings["memory_bytes"] = rule["peak_memory_above_baseline_bytes"] + int(largest["baseline_memory_bytes"])
    binding = sorted(name for name, limit in HOST_LIMITS.items() if ceilings[name] > limit)
    return dict(rule=RULE, multiplier=MULTIPLIER, host=HOST, host_limits=HOST_LIMITS, largest=largest,
                ceilings=ceilings, host_limit_binding=binding, executable=not binding,
                verdict=NOT_EXECUTABLE if binding else "executable on this host")


def run_limits(derived):
    """CLI/engine ceilings bound by a manifest; refuse when a host limit binds."""
    if not derived.get("executable"):
        raise BundleError("not_executable_on_host:" + ",".join(derived.get("host_limit_binding", ()))
                          + " (" + NOT_EXECUTABLE + ")")
    c = derived["ceilings"]
    return dict(max_input_bytes=c["input_bytes"], max_records=c["records"], max_seconds=float(c["runtime_seconds"]),
                max_events=c["engine_events"], max_outputs=c["decisions_spans"],
                max_output_bytes=c["report_bytes"], max_memory_bytes=c["memory_bytes"])


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


def window_preflight(now, max_seconds):
    """Operational refusal before any score unless the whole ceiling fits 00:30-09:00 Toronto."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo("America/Toronto"))
    opens = datetime.combine(local.date(), datetime.min.time(), local.tzinfo) + timedelta(minutes=30)
    closes = datetime.combine(local.date(), datetime.min.time(), local.tzinfo) + timedelta(hours=9)
    if not opens <= local or local + timedelta(seconds=max_seconds) > closes:
        raise BundleError("scored_run_must_fit_admitted_window_00_30_09_00")


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
