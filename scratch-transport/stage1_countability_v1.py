"""Evening-fix Stage 1 step (ii): promotion_countable via the frozen TransferredLedger (L16, 2026-11-03).

Master's ruling (option A): the UNMODIFIED TransferredLedger from the c32629156 source archive (--src). Only
``countability()`` is called; ``labels()`` is never called. Output per (market, date) cell: the replay half,
the ``promotion_countable`` boolean (the scorer's own ``_truthy``) and the combined Clarification 1 s.2
verdict (``metadata_cells``). ``promotion_countable_reason`` is never emitted. Chain verification is reported
as PASS/FAIL plus the number of slugs verified (TransferredLedger raises on a FAIL).
Peak memory is measured in-process (Windows PeakWorkingSetSize via ctypes).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def peak_memory_bytes():
    counters = PMC()
    counters.cb = ctypes.sizeof(PMC)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    query = kernel32.K32GetProcessMemoryInfo
    query.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(PMC), ctypes.wintypes.DWORD]
    query.restype = ctypes.wintypes.BOOL
    if not query(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "K32GetProcessMemoryInfo failed")
    return {"peak_working_set": counters.PeakWorkingSetSize, "peak_pagefile": counters.PeakPagefileUsage}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--ledger-rows", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(f"refused: {out} exists", file=sys.stderr)
        return 2
    src = Path(args.src).resolve()
    sys.path.insert(0, str(src))
    import weather
    from weather.backtesting import evening_fix_scorer as scorer
    from weather.backtesting import evening_fix_transfer as transfer
    if not str(Path(weather.__file__).resolve()).startswith(str(src)):
        print("refused: weather not imported from --src", file=sys.stderr)
        return 2

    # Same order as the frozen _transfer_inputs (evening_fix_scorer.py:656-672), labels() excluded.
    rows_by_commit = transfer.load_replays({args.commit: args.replay})
    receipt = transfer.select_reproducing_commit(rows_by_commit)
    rows = rows_by_commit[receipt.commit]
    scorer.check_no_market(rows)
    try:
        ledger = transfer.TransferredLedger(args.ledger_rows, {r["event_slug"] for r in rows if r.get("event_slug")})
        verify = {"status": "PASS", "slugs_verified": len(ledger.verification)}
    except transfer.TransferRefused as exc:
        message = str(exc)
        code = "HASH_CHAIN_FAIL" if "hash chain" in message else "REFUSED"
        print(json.dumps({"verify": "FAIL", "code": code}), file=sys.stderr)   # message may name a slug only
        return 3
    countability = ledger.countability()
    promo = {slug: scorer._truthy(meta.get("promotion_countable")) for slug, meta in countability.items()}
    del countability, ledger

    slug_of = {}
    for row in rows:
        slug_of[(row["market_id"], row["target_date"])] = row.get("event_slug")
    stand_in = {slug: {"promotion_countable": True} for slug in slug_of.values()}
    replay_half = scorer.metadata_cells(rows, stand_in)
    combined = scorer.metadata_cells(rows, {slug: {"promotion_countable": value} for slug, value in promo.items()})
    cells = {}
    for key in sorted(combined):
        cells[f"{key[0]}|{key[1]}"] = {
            "replay_half_countable": bool(replay_half[key]["countable"]),
            "promotion_countable": bool(promo.get(slug_of.get(key), False)),
            "countable": bool(combined[key]["countable"]),
        }
    us_countable = Counter(key[1] for key, cell in combined.items()
                           if key[0] in scorer.US_MARKETS and cell["countable"])
    dates = [d.isoformat() for d in transfer.window_dates()]
    zero_dates = [d for d in dates if us_countable.get(d, 0) == 0]
    try:
        window = scorer.check_window_before_labels(rows, {s: {"promotion_countable": v} for s, v in promo.items()})
        window_stop = False
    except scorer.WindowStop:
        window, window_stop = None, True

    result = {
        "schema": "evening_fix_stage1_countability_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_file(__file__),
        "code_commit": receipt.commit,
        "replay_sha256": sha256_file(args.replay),
        "ledger_rows_sha256": sha256_file(args.ledger_rows),
        "verify_ledger_history": verify,
        "labels_called": False,
        "emitted_fields": ["replay_half_countable", "promotion_countable", "countable"],
        "cells": cells,
        "zero_countable_us11_dates": zero_dates,
        "window_from_metadata": window,
        "window_stop": window_stop,
        "slugs_promotion_countable_false": sum(1 for v in promo.values() if not v),
        "peak_memory_bytes": peak_memory_bytes(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"verify": verify, "zero_dates": zero_dates, "window": window, "window_stop": window_stop,
                      "promotion_false_slugs": result["slugs_promotion_countable_false"],
                      "peak_memory_bytes": result["peak_memory_bytes"], "out_sha256": sha256_file(out)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
