"""Collection health: detect gaps and coverage problems in snapshot tapes so we
know which captured market-days are clean enough to trust in the backtest.

A day is only useful for settlement-scored evaluation if it was captured
continuously across the afternoon warming window. This module reports, per day:
capture count vs expected, the largest gap, every gap beyond tolerance, the
covered local-hour range, and a clean verdict.

CLI:
  python -m src.collection_health [folder ...] [--interval-minutes 10] [--tolerance 1.5]
  python -m src.collection_health --live --strict [folder ...]
"""
import argparse
import csv
import json
import sys
from datetime import datetime, time as dt_time
from pathlib import Path

try:
    from market_config import date_from_event_slug
except ImportError:  # pragma: no cover - package/module execution fallback
    from .market_config import date_from_event_slug

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


def local_window(target_date, tzinfo=None):
    return (
        datetime.combine(target_date, dt_time(AFTERNOON_START_HOUR, tzinfo=tzinfo)),
        datetime.combine(target_date, dt_time(AFTERNOON_END_HOUR, tzinfo=tzinfo)),
    )


def live_coverage_summary(times, interval_minutes, tolerance=1.5, as_of=None, target_date=None):
    """Collection health for an in-progress market day.

    Completed-day labeling should use coverage_summary(), which is deliberately
    strict. This helper avoids marking a morning live tape partial merely
    because the 12:00-18:00 settlement-decisive window has not happened yet.
    """
    times = sorted(times)
    as_of = as_of or datetime.now(times[-1].tzinfo if times else None)
    tzinfo = as_of.tzinfo or (times[-1].tzinfo if times else None)
    target_date = target_date or (times[0].date() if times else as_of.date())
    window_start, window_end = local_window(target_date, tzinfo)
    freshness_limit = interval_minutes * tolerance

    if not times:
        if as_of >= window_end:
            return {
                "state": "PARTIAL",
                "action_required": True,
                "clean": False,
                "n": 0,
                "reason": "no captures before window close",
                "window_start": window_start,
                "window_end": window_end,
            }
        if as_of >= window_start:
            return {
                "state": "AT_RISK",
                "action_required": True,
                "clean": False,
                "n": 0,
                "reason": "no captures after window start",
                "window_start": window_start,
                "window_end": window_end,
            }
        return {
            "state": "PENDING",
            "action_required": False,
            "clean": False,
            "n": 0,
            "reason": "no captures yet; afternoon window has not started",
            "window_start": window_start,
            "window_end": window_end,
        }

    final_summary = coverage_summary(times, interval_minutes, tolerance)
    final_summary.update({
        "window_start": window_start,
        "window_end": window_end,
    })
    if as_of >= window_end:
        final_summary["state"] = "CLEAN" if final_summary["clean"] else "PARTIAL"
        final_summary["action_required"] = not final_summary["clean"]
        return final_summary

    latest = times[-1]
    latest_age = (as_of - latest).total_seconds() / 60.0
    gaps = final_summary.get("gaps") or []
    reasons = []
    if gaps:
        reasons.append(final_summary["reason"])
    if latest_age > freshness_limit:
        reasons.append(f"latest capture is {latest_age:.0f} min old")
    if as_of >= window_start and times[0] > window_start:
        reasons.append(f"first capture after window start ({times[0]:%H:%M})")

    if reasons:
        final_summary["state"] = "AT_RISK"
        final_summary["action_required"] = True
        final_summary["reason"] = "; ".join(reasons)
    else:
        final_summary["state"] = "COLLECTING"
        final_summary["action_required"] = False
        final_summary["reason"] = (
            f"capture cadence healthy; afternoon window closes at {window_end:%H:%M}"
        )
    final_summary["latest_age_minutes"] = latest_age
    return final_summary


def folder_target_date(folder):
    return date_from_event_slug(Path(folder).name)


def summarize_folder(folder, interval_minutes=10.0, tolerance=1.5, live=False, as_of=None):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    times = snapshot_times(tape) if tape.exists() else []
    target_date = folder_target_date(folder)
    summary = (
        live_coverage_summary(times, interval_minutes, tolerance, as_of=as_of, target_date=target_date)
        if live
        else coverage_summary(times, interval_minutes, tolerance)
    )
    summary["event_slug"] = folder.name
    summary["folder"] = str(folder)
    summary["tape_path"] = str(tape)
    return summary


def serialize_summary(summary):
    out = {}
    for key, value in summary.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif key == "gaps":
            out[key] = [
                {
                    "after": item.get("after").isoformat() if isinstance(item.get("after"), datetime) else item.get("after"),
                    "before": item.get("before").isoformat() if isinstance(item.get("before"), datetime) else item.get("before"),
                    "gap_minutes": item.get("gap_minutes"),
                }
                for item in value
            ]
        else:
            out[key] = value
    return out


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
    parser.add_argument("--live", action="store_true", help="Evaluate as an in-progress live market day.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any tape needs attention.")
    args = parser.parse_args()

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    summaries = []
    any_attention = False
    for folder in folders:
        folder_path = Path(folder)
        tape = folder_path / "snapshots_long.csv"
        if not tape.exists():
            continue
        summary = summarize_folder(folder_path, args.interval_minutes, args.tolerance, live=args.live)
        summaries.append(summary)
        if summary.get("action_required", not summary.get("clean")):
            any_attention = True

    if args.json:
        print(json.dumps([serialize_summary(item) for item in summaries], indent=2, sort_keys=True))
        if args.strict and any_attention:
            sys.exit(2)
        return

    for summary in summaries:
        name = summary["event_slug"]
        if summary["n"] == 0:
            flag = summary.get("state") or "EMPTY"
            print(f"[{flag}] {name}: no captures -> {summary['reason']}")
            continue
        flag = summary.get("state") or ("CLEAN" if summary["clean"] else "CHECK")
        print(f"[{flag}] {name}: {summary['n']} snapshots "
              f"{summary['first']:%H:%M}-{summary['last']:%H:%M}, "
              f"capture {summary['capture_ratio'] * 100:.0f}% of expected, "
              f"max gap {summary['max_gap_minutes']:.0f} min -> {summary['reason']}")
        for g in summary.get("gaps") or []:
            print(f"         gap {g['gap_minutes']:.0f} min: {g['after']:%H:%M} -> {g['before']:%H:%M}")
    if any_attention:
        print("\nSome days are not clean; treat their backtest contributions with caution.")
    if args.strict and any_attention:
        sys.exit(2)


if __name__ == "__main__":
    main()
