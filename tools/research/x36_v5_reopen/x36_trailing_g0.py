"""Lane L47, K row 112, G0 (descriptive, no model): does a trailing-W bias correction of the raw NBP 07Z mean
cut MAE and mean error against the WU high on 2026-01-15..05-26? Rule: rule_x36_trailing_final.md.

Reads only the already-fetched 2026 corpus and WU labels through x36_v5's window-refusing loaders, and the
2021-25 L9 corpus for the training-era baseline. Light; run directly with the sha recorded first.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x36_v5 as base  # noqa: E402

EVAL_FIRST = date(2026, 1, 15)
WINDOWS = (7, 14)
CLIP = 3.0


def run(corpus, repo, train_corpus, out):
    import numpy as np

    out = Path(out)
    if out.exists():
        raise base.X36Error(f"refusing to overwrite {out}")
    ps = base.pairs(base.load_corpus(corpus, True), base.window_labels(repo))
    tp = base.pairs(base.load_corpus(train_corpus, False), base.load_labels(repo, set(base.TRAIN_YEARS), lambda d: True))
    b_train = {}
    for m in {p["m"] for p in tp}:
        xs = [p["x"] for p in tp if p["m"] == m]
        b_train[m] = sum(xs) / len(xs)
    by_m = defaultdict(list)
    for p in ps:
        by_m[p["m"]].append(p)
    rows = []
    for m, lst in by_m.items():
        lst.sort(key=lambda p: p["d"])
        for i, p in enumerate(lst):
            if date.fromisoformat(p["d"]) < EVAL_FIRST:
                continue
            r = {"m": m, "d": p["d"], "err_raw": p["x"], "err_seas": p["x"] - b_train[m]}
            ok = True
            for w in WINDOWS:
                prev = lst[max(0, i - w):i]
                if len(prev) < w:
                    ok = False
                    break
                b = float(np.clip(sum(q["x"] for q in prev) / w, -CLIP, CLIP))
                r[f"err_t{w}"] = p["x"] - b
            if ok:
                rows.append(r)
    arms = ["raw", "seas"] + [f"t{w}" for w in WINDOWS]
    dates = [r["d"] for r in rows]

    def cell(sel):
        res = {}
        for a in arms:
            e = [r[f"err_{a}"] for r in sel]
            res[a] = {"mae": float(np.mean(np.abs(e))), "me": float(np.mean(e)), "n": len(e)}
        return res

    groups = defaultdict(list)
    for r in rows:
        groups[f"{r['m']}|{r['d'][:7]}"].append(r)
        groups[r["m"]].append(r)
        groups[f"pooled|{r['d'][:7]}"].append(r)
    deltas = {}
    for w in WINDOWS:
        for ref in ("raw", "seas"):
            d = [abs(r[f"err_t{w}"]) - abs(r[f"err_{ref}"]) for r in rows]
            deltas[f"dMAE_t{w}_minus_{ref}"] = base.boot(d, dates)
    passing = [w for w in WINDOWS if deltas[f"dMAE_t{w}_minus_raw"]["mean"] < 0
               and deltas[f"dMAE_t{w}_minus_raw"]["hi"] < 0]
    res = {"schema": "l47_x36_trailing_g0/1", "module_sha256": base.sha256_file(__file__),
           "base_module_sha256": base.sha256_file(base.__file__), "corpus_sha256": base.sha256_file(corpus),
           "train_corpus_sha256": base.sha256_file(train_corpus), "eval_first": str(EVAL_FIRST),
           "n_rows": len(rows), "b_train_all_season": b_train, "pooled": cell(rows), "deltas": deltas,
           "cells": {k: cell(v) for k, v in sorted(groups.items())},
           "g0": {"pass": bool(passing), "windows_passing": passing}}
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(res["g0"]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="x36_trailing_g0")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--train-corpus", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    run(a.corpus, a.repo, a.train_corpus, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
