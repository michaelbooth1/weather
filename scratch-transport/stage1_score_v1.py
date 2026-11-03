"""Evening-fix Stage 1 step (iii): join and score per the frozen plan, plus the Clarification 2 sensitivity.

L16, 2026-11-03. Uses only the replay commit's own code (--src = `git archive c32629156 src`).

1. The frozen scorer, unmodified: ``evening_fix_scorer.main`` in transfer mode with --no-market, the signed
   prereg, the decision log and the transferred ledger rows. Its output carries the primary, the
   Clarification 1 s.6 Denver-excluded sensitivity (evening_fix_scorer.py:518-523), the crossed estimate,
   the beside blocks, Toronto, SAFETY and H2 exactly as frozen. The window is its own
   check_window_before_labels window.
2. Clarification 2 s.2 sensitivity: the same frozen functions (_transfer_inputs, score_rows, build_cells,
   primary_block) rebuild the primary cells; the script checks they reproduce step 1's primary block
   exactly, then drops the whole Denver cells 2026-10-22, 2026-10-25 and 2026-10-28 and recomputes
   primary_block on US11 over the same window. Descriptive only; it decides nothing.

Writes into a new --out-dir: scorer_out.json, clar2_three_cell_sensitivity.json, SHA256SUMS. stdout carries
the outcome and aggregate statistics only (no label, no per-snapshot value). Peak memory is measured
in-process (K32GetProcessMemoryInfo).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

CLAR2_EXCLUDED = (("denver", "2026-10-22"), ("denver", "2026-10-25"), ("denver", "2026-10-28"))


class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]


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
    return {"peak_working_set": counters.PeakWorkingSetSize, "peak_private_commit": counters.PeakPagefileUsage}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ("--src", "--commit", "--replay", "--ledger-rows", "--prereg", "--decision-log", "--out-dir"):
        parser.add_argument(name, required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        print(f"refused: {out_dir} exists", file=sys.stderr)
        return 2
    src = Path(args.src).resolve()
    sys.path.insert(0, str(src))
    import weather
    from weather.backtesting import evening_fix_scorer as scorer
    if not str(Path(weather.__file__).resolve()).startswith(str(src)):
        print("refused: weather not imported from --src", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True)

    # 1. Frozen scorer, unmodified.
    scorer_out = out_dir / "scorer_out.json"
    frozen_argv = ["--replay", f"{args.commit}={args.replay}", "--prereg", args.prereg,
                   "--decision-log", args.decision_log, "--ledger-rows", args.ledger_rows,
                   "--no-market", "--out", str(scorer_out)]
    rc = scorer.main(frozen_argv)
    if rc != 0:
        print(json.dumps({"frozen_scorer_rc": rc}), file=sys.stderr)
        return rc
    frozen = json.loads(scorer_out.read_text(encoding="utf-8"))

    # 2. Clarification 2 sensitivity from the same frozen functions.
    ns = scorer.build_parser().parse_args(frozen_argv)
    rows, labels, window, _extra = scorer._transfer_inputs(ns, {args.commit: args.replay})
    if window != frozen["window_dates"]:
        print("refused: rebuilt window differs from the frozen run", file=sys.stderr)
        return 5
    dates = [date.fromisoformat(day) for day in window]
    scored = scorer.score_rows(rows, labels, use_market=False)
    primary = scorer.build_cells(scored, labels, scorer.PRIMARY_HOURS, scorer._delta)
    _, rebuilt = scorer.primary_block(primary, dates, scorer.US_MARKETS)
    if (rebuilt["estimate"], rebuilt["ci95"], rebuilt["markets_negative"], rebuilt["market_days"]) != (
            frozen["primary"]["estimate"], frozen["primary"]["ci95"],
            frozen["primary"]["markets_negative"], frozen["primary"]["market_days"]):
        print("refused: rebuilt primary block differs from the frozen run", file=sys.stderr)
        return 5
    window_days = set(window)
    excluded_status = {f"{m}|{d}": {"in_window": d in window_days,
                                    "countable": bool(primary.get((m, d), {}).get("countable"))}
                       for m, d in CLAR2_EXCLUDED}
    kept = {key: cell for key, cell in primary.items() if key not in CLAR2_EXCLUDED}
    _, block = scorer.primary_block(kept, dates, scorer.US_MARKETS)
    conditions = block["ci95"][1] is not None and block["ci95"][1] < 0 and block["markets_negative"] >= scorer.SIGN_MIN
    primary_est = frozen["primary"]["estimate"]
    clar2 = {
        "schema": "evening_fix_clar2_three_cell_sensitivity_v1",
        "clarification": "docs/research/evening-lockin-fix-scoring-clarification-2-2026-11-03.md "
                         "(634823a7261c00abbf9a90c1863641a278ce59423fc38c600a785ee8bb5bbe79)",
        "excluded_cells": excluded_status,
        "window_dates": window,
        **block,
        "conditions_1_2": conditions,
        "sign_disagrees_with_primary": (block["estimate"] is not None and primary_est is not None
                                        and (block["estimate"] < 0) != (primary_est < 0)),
        "decides_nothing": True,
        "rebuilt_primary_matches_frozen": True,
    }
    clar2_out = out_dir / "clar2_three_cell_sensitivity.json"
    with clar2_out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(clar2, handle, indent=2, sort_keys=True)
        handle.write("\n")
    receipt = {
        "schema": "evening_fix_stage1_score_receipt_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_file(__file__),
        "code_commit": args.commit,
        "inputs": {name: {"path": str(Path(p).resolve()), "sha256": sha256_file(p)} for name, p in (
            ("replay", args.replay), ("ledger_rows", args.ledger_rows), ("prereg", args.prereg),
            ("decision_log", args.decision_log))},
        "outputs": {p.name: sha256_file(p) for p in (scorer_out, clar2_out)},
        "peak_memory_bytes": peak_memory_bytes(),
    }
    receipt_path = out_dir / "receipt.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sums = "".join(f"{sha256_file(p)}  {p.name}\n" for p in (scorer_out, clar2_out, receipt_path))
    (out_dir / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
    summary = {
        "outcome": frozen["outcome"], "final": frozen["final"], "void_reasons": frozen["void_reasons"],
        "window_dates": window,
        "primary": {k: frozen["primary"][k] for k in ("estimate", "ci95", "markets_negative", "markets_n", "market_days")},
        "denver_excluded_sensitivity": {k: frozen["denver_excluded_sensitivity"][k] for k in (
            "estimate", "ci95", "markets_negative", "markets_n", "market_days", "conditions_1_2")},
        "clar2_three_cell_sensitivity": {k: clar2[k] for k in (
            "estimate", "ci95", "markets_negative", "markets_n", "market_days", "conditions_1_2",
            "sign_disagrees_with_primary", "excluded_cells")},
        "crossed": frozen["crossed"], "crossed_disagrees": frozen["crossed_disagrees"],
        "safety_fail": frozen["safety_fail"], "beside": frozen["beside"],
        "h2": frozen["h2_pre_lockin_floor_non_inferiority_00_16"],
        "peak_memory_bytes": receipt["peak_memory_bytes"],
        "sha256": {"scorer_out.json": receipt["outputs"]["scorer_out.json"],
                   "clar2_three_cell_sensitivity.json": receipt["outputs"]["clar2_three_cell_sensitivity.json"],
                   "receipt.json": sha256_file(receipt_path)},
    }
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
