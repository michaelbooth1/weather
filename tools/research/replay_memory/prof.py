"""Phase-sampled peak memory: pack_cli.rehearse (official path) or an N-day scored-style comparison run.

Exam tree (or a prototype copy of its maker_core) first on PYTHONPATH. Windows only. ``--mode rehearse`` runs
pack_cli.rehearse on one calibration-date bundle and prints its measured dict; ``--mode multi`` runs the same
pipeline (load_days, maintenance windows, comparison_report, report_bytes) on 1-15 bundles of any dates and also
records the report JSON/Markdown SHA-256. A sampler thread records the largest current commit/working set per phase;
it uses its own ctypes definition because ceilings.process_memory() leaks a ctypes class per call. ``--trace`` adds
tracemalloc snapshots (slow; inflates RSS). Replay work: heavy under the host load policy.
Report: docs/roadmap/agent-report-2026-10-03-replay-memory.md.
"""
import argparse, gc, json, sys, threading, time, tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from maker_core.replay import ceilings, pack_cli
from maker_core.replay import engine as eng, report as rep

phase = ["import"]
peaks = {}
stop = False


import ctypes
from ctypes import wintypes


class _C(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_k, _p = ctypes.windll.kernel32, ctypes.windll.psapi
_k.GetCurrentProcess.restype = wintypes.HANDLE
_GPMI = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_C), wintypes.DWORD)(("GetProcessMemoryInfo", _p))


def _mem():
    c = _C(); c.cb = ctypes.sizeof(c)
    _GPMI(_k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return max(c.WorkingSetSize, c.PagefileUsage)


def sampler():
    while not stop:
        cur = _mem()
        key = phase[0]
        if cur > peaks.get(key, 0):
            peaks[key] = cur
        time.sleep(0.05)


def label(name, fn):
    def wrapped(*a, **k):
        prev = phase[0]
        phase[0] = name(a, k) if callable(name) else name
        try:
            return fn(*a, **k)
        finally:
            phase[0] = prev
    return wrapped


SNAPS = []


def snap(tag, args):
    if args.trace:
        gc.collect()
        s = tracemalloc.take_snapshot().filter_traces([tracemalloc.Filter(False, tracemalloc.__file__)])
        top = s.statistics("lineno")[:args.top]
        cur, peak = tracemalloc.get_traced_memory()
        SNAPS.append(dict(tag=tag, traced_current=cur, traced_peak=peak,
                          top=[(str(t.traceback[0]), t.size, t.count) for t in top]))
        tracemalloc.reset_peak()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("rehearse", "multi"), required=True)
    p.add_argument("--bundle", action="append", type=Path, required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--trace", action="store_true")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    global stop
    if a.trace:
        tracemalloc.start(1)
    orig_run = eng.ReplayEngine.run

    def run(self):
        prev = phase[0]
        phase[0] = f"run:{self.config.policy}:{self.config.fill_bound}"
        try:
            r = orig_run(self)
            snap(phase[0] + ":end", a)
            return r
        finally:
            phase[0] = prev
    eng.ReplayEngine.run = run
    rep.score = label("score", rep.score)
    rep.pull_efficiency = label("pull_efficiency", rep.pull_efficiency)
    rep.cluster_intervals = label("cluster_intervals", rep.cluster_intervals)
    rep.coverage_report = label("coverage_report", rep.coverage_report)
    rep.quote_presence = label("quote_presence", rep.quote_presence)
    orig_rb = rep.report_bytes

    def report_bytes(report):
        snap("before_report_bytes", a)
        phase[0] = "report_bytes"
        out = orig_rb(report)
        snap("after_report_bytes", a)
        return out
    rep.report_bytes = report_bytes
    import maker_core.replay.pack_io as pio
    pio.load_bundle = label("load", pio.load_bundle)
    threading.Thread(target=sampler, daemon=True).start()
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    t0 = time.monotonic()
    if a.mode == "rehearse":
        phase[0] = "rehearse"
        measured, detail = pack_cli.rehearse(a.bundle, a.calibration, now=now)
    else:
        from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits
        from maker_core.replay.execution_manifest import FROZEN_CONFIG
        from maker_core.replay.pack_io import deadline, load_days, read_json
        from maker_core.replay.engine import ReplayConfig, collect_stats, MAX_ENGINE_EVENTS
        baseline = ceilings.process_memory()[1]
        check = deadline(HOST_MAX_SECONDS * 4)
        cal, _ = read_json(a.calibration)
        bundles = load_days(a.bundle, Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS), lambda: None, now=now)
        snap("after_load", a)
        config = ReplayConfig(**FROZEN_CONFIG, hazard_per_minute=float(cal["hazard_per_minute"]),
                              max_events=MAX_ENGINE_EVENTS, max_outputs=MAX_ENGINE_EVENTS)
        phase[0] = "report_other"
        with collect_stats() as passes:
            report = rep.comparison_report(pack_cli._maintenance(bundles), config, check=lambda: None)
            raw, md = rep.report_bytes(report)
        import hashlib
        measured = dict(report_bytes=len(raw) + len(md), report_sha256=hashlib.sha256(raw).hexdigest(),
                        md_sha256=hashlib.sha256(md).hexdigest(), passes=passes,
                        peak_memory_above_baseline_bytes=ceilings.process_memory()[1] - baseline,
                        baseline_memory_bytes=baseline, records=sum(len(b.records) for b in bundles))
        del report, raw, md
    stop = True
    time.sleep(0.1)
    out = dict(mode=a.mode, days=len(a.bundle), seconds=round(time.monotonic() - t0, 1), measured=measured,
               phase_peak_current_bytes=peaks, snapshots=SNAPS)
    a.out.write_text(json.dumps(out, indent=1, default=str))
    m = measured
    print(json.dumps(dict(days=len(a.bundle), seconds=out["seconds"],
                          peak_above_baseline_MiB=round(m["peak_memory_above_baseline_bytes"] / 2**20, 1),
                          baseline_MiB=round(m["baseline_memory_bytes"] / 2**20, 1),
                          phase_MiB={k: round(v / 2**20) for k, v in peaks.items()})))


if __name__ == "__main__":
    main()
