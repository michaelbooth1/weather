"""Collection health: detect gaps and coverage problems in snapshot tapes so we
know which captured market-days are clean enough to trust in the backtest.

A day is only useful for settlement-scored evaluation if it was captured
continuously across the afternoon warming window. This module reports, per day:
capture count vs expected, the largest gap, every gap beyond tolerance, the
covered local-hour range, and a clean verdict.

CLI:
  python -m src.collection_health [folder ...] [--interval-minutes 10] [--tolerance 1.5]
"""
import argparse
import csv
from datetime import datetime
from pathlib import Path

DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
# Settlement-decisive window: a clean day should span at least this local range.
AFTERNOON_START_HOUR = 12
AFTERNOON_END_HOUR = 18


def parse_times(iso_strings):
    times = []
    for s in iso_strings:
        if not s:
            continue
        try:
            times.append(datetime.fromisoformat(str(s)))
        except ValueError:
            continue
    return sorted(times)


def detect_gaps(times, interval_minutes, tolerance=1.5):
    """Consecutive captures spaced more than tolerance x the interval apart."""
    limit = interval_minutes * tolerance
    gaps = []
    for a, b in zip(times, times[1:]):
        gap_min = (b - a).total_seconds() / 60.0
        if gap_min > limit:
            gaps.append({"after": a, "before": b, "gap_minutes": gap_min})
    return gaps


def coverage_summary(times, interval_minutes, tolerance=1.5):
    times = sorted(times)
    n = len(times)
    if n == 0:
        return {"n": 0, "clean": False, "reason": "no captures"}
    span_min = (times[-1] - times[0]).total_seconds() / 60.0
    expected = int(span_min // interval_minutes) + 1 if span_min > 0 else 1
    gaps = detect_gaps(times, interval_minutes, tolerance)
    max_gap = max((g["gap_minutes"] for g in gaps), default=interval_minutes if n > 1 else 0.0)
    first, last = times[0], times[-1]
    covers_afternoon = first.hour <= AFTERNOON_START_HOUR and last.hour >= AFTERNOON_END_HOUR
    clean = n >= 2 and not gaps and covers_afternoon
    reasons = []
    if n < 2:
        reasons.append("too few captures")
    if gaps:
        reasons.append(f"{len(gaps)} gap(s), max {max_gap:.0f} min")
    if not covers_afternoon:
        reasons.append(
            f"afternoon window not fully covered (captured {first:%H:%M}-{last:%H:%M})")
    return {
        "n": n,
        "first": first,
        "last": last,
        "span_minutes": span_min,
        "expected": expected,
        "capture_ratio": n / expected if expected else 0.0,
        "max_gap_minutes": max_gap,
        "gaps": gaps,
        "covers_afternoon": covers_afternoon,
        "clean": clean,
        "reason": "; ".join(reasons) if reasons else "ok",
    }


def snapshot_times(tape_path):
    """Unique capture timestamps (one per snapshot) from a snapshots_long.csv."""
    seen, times = set(), []
    with open(tape_path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = row.get("snapshot_id")
            ts = row.get("captured_at_local")
            if sid and sid not in seen and ts:
                seen.add(sid)
                times.append(ts)
    return parse_times(times)


def main():
    parser = argparse.ArgumentParser(description="Report snapshot-collection health and gaps.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    args = parser.parse_args()

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    any_unclean = False
    for folder in folders:
        tape = Path(folder) / "snapshots_long.csv"
        if not tape.exists():
            continue
        cov = coverage_summary(snapshot_times(tape), args.interval_minutes, args.tolerance)
        name = Path(folder).name
        if cov["n"] == 0:
            print(f"[EMPTY] {name}: no captures")
            any_unclean = True
            continue
        flag = "CLEAN" if cov["clean"] else "CHECK"
        if not cov["clean"]:
            any_unclean = True
        print(f"[{flag}] {name}: {cov['n']} snapshots "
              f"{cov['first']:%H:%M}-{cov['last']:%H:%M}, "
              f"capture {cov['capture_ratio'] * 100:.0f}% of expected, "
              f"max gap {cov['max_gap_minutes']:.0f} min -> {cov['reason']}")
        for g in cov["gaps"]:
            print(f"         gap {g['gap_minutes']:.0f} min: {g['after']:%H:%M} -> {g['before']:%H:%M}")
    if any_unclean:
        print("\nSome days are not clean; treat their backtest contributions with caution.")


if __name__ == "__main__":
    main()
