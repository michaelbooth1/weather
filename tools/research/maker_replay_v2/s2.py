"""S2 for maker replay v2 W2: exporter peak memory vs output bytes on a fictional full capture day.

Called through ``tools.research.maker_replay_v2.run`` (the one admitted module), one measurement per
fresh process, serially, under ``scripts/ops/workstation_heavy.ps1``:

- ``s2-input`` writes the fictional sealed 88a day (``capture170``) and nothing else.
- ``s2`` runs one night export of it, the v0.2 exporter or the frozen v0.1 one as the baseline. Memory
  is read the way the nightly wrapper's 2 GiB ceiling reads it: the larger of working set and private
  commit, sampled every 50 ms and kept per exporter phase. The run records ``OPENBLAS_NUM_THREADS``
  and the CPU count, because numpy's OpenBLAS commits about 47 MiB per thread at import.
  ``--tracemalloc`` adds Python allocation totals per source file at the end of projection and at
  the end of the export (slower; its peak is not the measurement).
- ``books`` exports short windows at several book depths and fits book record bytes per level a side.

The export classes are wrapped only to read their accumulator sizes; nothing they write changes.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import tracemalloc
from types import SimpleNamespace
from typing import Iterator

from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS
from maker_core.replay.ceilings import process_memory

LATER = datetime(2026, 10, 4, tzinfo=timezone.utc)  # any instant after the fictional day has closed


def _probe():
    """``process_memory`` without its per-call ctypes class: that class and its cached ``POINTER`` type are never
    freed, so sampling it every 50 ms grows the process by about 5 KB a call and inflates what is measured."""
    if os.name != "nt":
        return lambda: process_memory()[0]
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    # Private library objects: ``windll``'s function objects are shared, and ``process_memory`` sets their argtypes.
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    handle = kernel32.GetCurrentProcess()

    def current():
        psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return max(counters.WorkingSetSize, counters.PagefileUsage)
    return current


class Sampler:
    """The larger of working set and private commit, every 50 ms, kept as a maximum per phase label."""

    def __init__(self):
        self.label, self.peaks, self.stopped = "start", {}, False
        self.current = _probe()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopped:
            current = self.current()
            self.peaks[self.label] = max(self.peaks.get(self.label, 0), current)
            time.sleep(0.05)

    def stop(self):
        self.stopped = True
        self.thread.join()
        return dict(self.peaks)


def s2_input(out, day: date, *, union, trades, book_depth, minutes):
    from tools.research.maker_replay_v2.capture170 import write
    started = time.perf_counter()
    info = write(out / "capture", day, union=union, trades=trades, book_depth=book_depth, minutes=minutes)
    size = sum(p.stat().st_size for p in (out / "capture").rglob("*") if p.is_file())
    return dict(measurement="S2-input", status="WRITTEN", input_bytes=size,
                seconds=round(time.perf_counter() - started, 1), **info)


def _night_args(day, source, out, max_output_bytes):
    return SimpleNamespace(day=day.isoformat(), data_root=source, out=out, release_root=None,
                           expected_module_sha256=None, max_input_bytes=16 * 1024**3,
                           max_output_bytes=max_output_bytes, max_seconds=HOST_MAX_SECONDS)


def _top(limit=15):
    stats = tracemalloc.take_snapshot().statistics("filename")
    out = []
    for stat in stats[:limit]:
        name = str(stat.traceback[0].filename).replace("\\", "/")
        out.append(dict(file=name.split("/src/")[-1].split("/Lib/")[-1], mib=round(stat.size / 2**20, 1),
                        blocks=stat.count))
    return out


def _accumulators(projection, sources):
    return dict(dedup_entries=len(projection.dedup), trade_skews=len(projection.trade_skews),
                tokens=len(projection.tokens), conditions=len(projection.conditions),
                book_minutes=sum(len(m) for m in projection.book_minutes.values()),
                writer_conditions=len(projection.writer.names),
                sources_cache_bytes=getattr(sources, "cache_bytes", None),
                sources_cached_events=len(getattr(sources, "cache", ())), memory_bytes=process_memory()[0])


def s2(day: date, source, out, *, form="v0.2", trace=False, max_output_bytes=HOST_MAX_BYTES):
    if trace:
        tracemalloc.start(1)
    sampler, probes, seen = Sampler(), {}, {}
    started = time.perf_counter()
    result = dict(measurement="S2", status="MEASURED", format=form, cpu_count=os.cpu_count(),
                  openblas_num_threads=os.environ.get("OPENBLAS_NUM_THREADS"),
                  memory_before_export_bytes=process_memory()[0], tracemalloc=trace)
    args = _night_args(day, source, out / "panel", max_output_bytes)
    if form == "v0.2":
        from weather.market import maker_replay_bundle_v02 as exporter
        from weather.market.maker_replay_night_v02 import export_day

        init, base = exporter.StreamingProjection.__init__, exporter.ReleaseSources

        def remember(self, *a, **k):
            init(self, *a, **k)
            seen["projection"] = self

        class Sources(base):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                seen["sources"] = self

        exporter.StreamingProjection.__init__, exporter.ReleaseSources = remember, Sources

        def phase(label):
            if label == "writing":
                probes["accumulators_at_end_of_projection"] = _accumulators(seen["projection"], seen.get("sources"))
            if trace and label in ("writing", "done"):
                probes["tracemalloc_" + label] = dict(
                    traced_peak_mib=round(tracemalloc.get_traced_memory()[1] / 2**20, 1), top=_top())
            sampler.label = label

        receipt = export_day(args, "panel", now=LATER, phase=phase)
        sampler.label = "receipt"
    else:
        from weather.market.maker_replay_night import export_day
        sampler.label = "v0.1_export"
        receipt = export_day(args, "panel", now=LATER)
    seconds = time.perf_counter() - started
    peak = process_memory()[1]
    result.update(seconds=round(seconds, 1), peak_memory_bytes=peak, peak_gib=round(peak / 2**30, 3),
                  peak_below_2_gib=peak < 2 * 1024**3, phase_peaks=sampler.stop(), probes=probes,
                  receipt={k: receipt.get(k) for k in ("status", "runtime_seconds", "peak_memory_bytes", "cities")})
    bundle = receipt["bundle"]
    if form == "v0.2":
        result["bundle"] = {k: bundle[k] for k in ("bytes", "records", "v01_records", "conditions",
                                                   "coverage_groups", "kinds", "v01_kinds", "v01_equivalent", "counts")}
        result["bundle"]["gib"] = round(bundle["bytes"] / 2**30, 3)
        return result
    # The v0.1 file is read per line only after the peak above was taken.
    size, count = Counter(), Counter()
    with (out / "panel" / day.isoformat() / "bundle" / "events.jsonl").open("rb") as handle:
        for line in handle:
            kind = json.loads(line)["kind"]
            size[kind] += len(line)
            count[kind] += 1
    result["bundle"] = dict(bytes=bundle["bytes"], gib=round(bundle["bytes"] / 2**30, 3), records=bundle["records"],
                            conditions=bundle["conditions"], counts=bundle["counts"],
                            v01_kinds={k: dict(bytes=size[k], records=count[k]) for k in sorted(count)})
    return result


def book_lines(bundle_dir: Path) -> Iterator[bytes]:
    """The book records of one exported bundle, as decoded JSON lines, for any bundle format.

    v0.1: the ``book`` rows of ``events.jsonl``; v0.2: ``book.jsonl``; v0.3: ``book.jsonl.gz`` inflated by the
    bounded v2 decoder (at most the manifest's declared decoded size). A measurement helper: the hash-checked
    admission path is ``bundle_v02.open_stream_bundle``.
    """
    from maker_core.replay.bundle import FORMAT as FORMAT_V01, MAX_LINE_BYTES
    from maker_core.replay.bundle_v02 import FORMAT_V02, FORMAT_V03
    from maker_core.replay.v2 import gzip_stream
    manifest = json.loads((bundle_dir / "bundle.json").read_bytes())
    form = manifest.get("format")
    if form == FORMAT_V01:
        with (bundle_dir / "events.jsonl").open("rb") as handle:
            yield from (line for line in handle if json.loads(line)["kind"] == "book")
    elif form == FORMAT_V02:
        with (bundle_dir / "book.jsonl").open("rb") as handle:
            yield from handle
    elif form == FORMAT_V03:
        entry = next((e for e in manifest["streams"] if e["path"] == "book.jsonl.gz"), None)
        if entry is None:
            return
        with (bundle_dir / entry["path"]).open("rb") as handle:
            chunks = iter(lambda: handle.read(gzip_stream.CHUNK_BYTES), b"")
            yield from gzip_stream.lines(gzip_stream.decode(chunks, entry["decoded_bytes"]), MAX_LINE_BYTES)
    else:
        raise ValueError(f"unsupported bundle format: {form!r}")


def books(day: date, out, *, depths, minutes, union, trades):
    """Book record bytes against levels a side: one short export per depth (v0.3 gzip by default, any
    format read through ``book_lines``), fitted by least squares on the decoded record bytes."""
    from tools.research.maker_replay_v2.capture170 import write
    from weather.market import maker_replay_bundle_v02 as exporter
    from weather.market.market_registry import BUILTIN_SPECS
    rows = []
    for depth in depths:
        root = out / f"depth{depth}"
        write(root / "capture", day, union=union, trades=trades, book_depth=depth, minutes=minutes)
        summary = exporter.export(SimpleNamespace(
            date=day.isoformat(), markets=[s.id for s in BUILTIN_SPECS], data_root=root / "capture",
            out=root / "bundle", max_seconds=HOST_MAX_SECONDS, max_input_bytes=16 * 1024**3,
            max_output_bytes=HOST_MAX_BYTES, max_records=HOST_MAX_RECORDS, carry_bundle=[], release_root=None,
            kinds=None), now=LATER)
        levels = records = 0
        for line in book_lines(root / "bundle"):
            book = json.loads(line)["payload"]
            levels += sum(len(book[side]) for side in ("yes_bids", "yes_asks", "no_bids", "no_asks")) / 4
            records += 1
        stream = summary["streams"]["book"]
        decoded = stream.get("decoded_bytes", stream["bytes"])  # record bytes: v0.3 stores them gzipped
        rows.append(dict(depth=depth, format=summary.get("format"), records=stream["records"], bytes=decoded,
                         stored_bytes=stream["bytes"], bytes_per_record=round(decoded / stream["records"], 1),
                         mean_levels_a_side=round(levels / records, 3)))
    xs, ys = [r["mean_levels_a_side"] for r in rows], [r["bytes_per_record"] for r in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return dict(measurement="S2-books", status="MEASURED", minutes=minutes, rows=rows,
                fit=dict(bytes_per_record_intercept=round(my - slope * mx, 1), bytes_per_level_a_side=round(slope, 2)))
