"""Ad-hoc: decompose the Toronto 13-14h capture-hour model-vs-market loss.

Question: is the in-window 13-14h dip reach-shaped (model under-calls the
winning bucket), sharpness-shaped (model keeps too much mass on neighbors),
or an over-call (model too high on a bucket that loses)? Answer by slicing
replayed rows by signed settlement distance and comparing model vs market
probability, mean outcome, and Brier per slice.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath("src"))

from replay_backtest import run_replay_backtest  # noqa: E402

FOLDERS = [
    f"data/snapshots/highest-temperature-in-toronto-on-{d}"
    for d in [
        "may-27-2026", "may-28-2026", "may-30-2026", "may-31-2026",
        "june-1-2026", "june-2-2026", "june-3-2026", "june-4-2026",
        "june-5-2026", "june-6-2026", "june-7-2026", "june-8-2026",
        "june-9-2026", "june-10-2026", "june-11-2026",
    ]
]


def brier(rows, prob_key):
    if not rows:
        return None
    return sum((r[prob_key] - r["outcome"]) ** 2 for r in rows) / len(rows)


def mean(rows, key):
    if not rows:
        return None
    return sum(r[key] for r in rows) / len(rows)


def fmt(value):
    return f"{value:.4f}" if value is not None else "  -   "


def main():
    results = run_replay_backtest(FOLDERS, None, {}, None, write=False)
    rows = [r for r in results["all_rows"] if r["cutoff_hour"] in (13, 14)]
    print(f"13-14h Toronto rows: {len(rows)}")
    agg_m = brier(rows, "replayed_p")
    agg_k = brier(rows, "market_yes")
    print(f"aggregate  model {fmt(agg_m)}  market {fmt(agg_k)}  gap {fmt(agg_m - agg_k)}\n")

    # 1) Per signed settlement distance: distance 0 is the eventual winner band.
    print("By signed settlement distance (band bucket - settlement bucket):")
    print("  dist   n   modelBrier marketBrier   gap     E[model] E[market] E[outcome]")
    by_dist = defaultdict(list)
    for r in rows:
        d = r["settlement_distance"]
        d = max(-3, min(3, d)) if d is not None else None
        by_dist[d].append(r)
    for d in sorted(k for k in by_dist if k is not None):
        rs = by_dist[d]
        bm, bk = brier(rs, "replayed_p"), brier(rs, "market_yes")
        tag = f"{d:+d}" if abs(d) < 3 else f"{d:+d}+"
        print(f"  {tag:>4} {len(rs):4d}  {fmt(bm)}    {fmt(bk)}   {fmt(bm-bk)}  "
              f"{fmt(mean(rs,'replayed_p'))}  {fmt(mean(rs,'market_yes'))}  {fmt(mean(rs,'outcome'))}")

    # 2) Per bin type.
    print("\nBy bin type:")
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["bin_type"]].append(r)
    for t, rs in sorted(by_type.items()):
        bm, bk = brier(rs, "replayed_p"), brier(rs, "market_yes")
        print(f"  {t:>4} {len(rs):4d}  model {fmt(bm)}  market {fmt(bk)}  gap {fmt(bm-bk)}")

    # 3) Per day: which days drive the loss.
    print("\nBy day (model - market gap, sorted worst first):")
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["target_date"]].append(r)
    day_gaps = []
    for day, rs in by_day.items():
        bm, bk = brier(rs, "replayed_p"), brier(rs, "market_yes")
        day_gaps.append((bm - bk, day, len(rs), bm, bk, mean(rs, "outcome")))
    for gap, day, n, bm, bk, _ in sorted(day_gaps, reverse=True):
        print(f"  {day}  n={n:3d}  model {fmt(bm)}  market {fmt(bk)}  gap {fmt(gap)}")


if __name__ == "__main__":
    main()
