"""One-market timing pilot of ``weather.calibration.feature_model.main`` (retrain sizing r2).

Purpose: wall-clock and peak memory of one per-market season-coverage refit, nothing else.

Guards (all fail closed):
- reads come from ``--data-root`` / ``--artifacts-read-root`` (the main checkout), never written;
- every write the trainer makes (artifacts, reports) is redirected into ``--out-dir``; a write to any
  other path raises before the file is opened;
- the target date must be in 2026, so ``historical_target_cache`` drops every 2026 row (prior years only);
- trainer stdout (which contains leave-one-out scores) goes to a file in ``--out-dir``; this tool
  prints only timings, row counts and the extracted "Cutoff Hour ... (N days)" / "Loaded N" lines.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import ctypes
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path


def peak_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PeakWorkingSetSize)


def make_guarded_open(out_dir: Path):
    real_open = builtins.open
    out_dir = out_dir.resolve()

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            target = Path(file).resolve()
            if out_dir not in target.parents and target != out_dir:
                redirected = out_dir / "redirected" / target.name
                redirected.parent.mkdir(parents=True, exist_ok=True)
                return real_open(redirected, mode, *args, **kwargs)
        return real_open(file, mode, *args, **kwargs)

    return guarded_open


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--market", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--artifacts-read-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--skip-loo", action="store_true")
    args = parser.parse_args(argv)

    target_date = dt.date.fromisoformat(args.target_date)
    if target_date.year != 2026:
        raise SystemExit("target date must be in 2026 so every 2026 row is excluded from training")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_root = Path(args.data_root).resolve()
    artifacts_root = Path(args.artifacts_read_root).resolve()
    if out_dir.resolve() in (data_root, artifacts_root) or data_root in out_dir.resolve().parents:
        raise SystemExit("out dir must be outside the read roots")

    import weather.paths as paths

    paths.DATA_ROOT = data_root
    import weather.artifacts as artifacts

    artifacts.ARTIFACTS_ROOT = artifacts_root
    import weather.calibration.feature_model as fm
    import weather.calibration.feature_model_reports as fmr

    guarded = make_guarded_open(out_dir)
    fm.open = guarded
    fmr.open = guarded

    def scratch_artifact_path(filename):
        path = out_dir / "artifacts" / Path(filename).name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    fm.writable_artifact_path = scratch_artifact_path
    real_model = fm.TorontoHighTempModel

    def pinned_model(*a, **kw):
        kw.setdefault("target_date", target_date)
        return real_model(*a, **kw)

    fm.TorontoHighTempModel = pinned_model
    if args.skip_loo:
        fm.RUN_LOO = False

    log_path = out_dir / f"trainer_stdout_{args.market}.log"
    started = time.perf_counter()
    with open(log_path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        fm.main(market_id=args.market)
    elapsed = time.perf_counter() - started

    keep = re.compile(r"^(Loaded \d+ |Cutoff Hour \d\d:00 \(\d+ days\)|Training feature model)")
    with open(log_path, encoding="utf-8") as handle:
        structural = [line.rstrip() for line in handle if keep.match(line.strip())]
    written = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file())
    summary = {
        "market": args.market,
        "target_date": target_date.isoformat(),
        "run_loo": not args.skip_loo,
        "wall_clock_seconds": round(elapsed, 3),
        "peak_working_set_bytes": peak_working_set_bytes(),
        "cpu_count": os.cpu_count(),
        "structural_lines": structural,
        "files_written_under_out_dir": written,
    }
    (out_dir / f"summary_{args.market}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
