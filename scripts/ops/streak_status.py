#!/usr/bin/env python3
"""Toronto code-soak STREAK status -- the single most important operational check.

Answers, in one command: how many CONTIGUOUS `complete`-grade Toronto days do we
have (the gate to release #1), and is TODAY on track to grade `complete`?

Authoritative source is the settlement ledger, NOT market_day_labels.csv (that CSV
is a lagging promotion artifact -- it can show an older date while the ledger already
carries a newer grade). See docs/ops/streak-soak.md.

Grade rule (mirrors src/weather/collection/collection_health.py):
  * afternoon material window = 12:00-18:00 local (AFTERNOON_START/END_HOUR)
  * a "gap" = consecutive snapshot captures spaced > interval * 1.5 apart
    (snapshot loop interval = 10 min -> 15 min threshold)
  * a day is clean only if it has captures spanning 12:00->18:00 with no in-window gap
  * streak eligibility counts quality_grade in {complete, manual_override}

Pure stdlib, zero imports from the weather package: it can never roll a capture loop
and runs even if the package is mid-refactor.

Usage:
  python scripts/ops/streak_status.py            # human report
  python scripts/ops/streak_status.py --json      # machine-readable
  python scripts/ops/streak_status.py --monitor    # exit 3 + alert if TODAY at risk
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "data" / "settlements" / "toronto" / "ledger.jsonl"
LABELS = REPO / "data" / "backtest" / "market_day_labels.csv"
SNAPS = REPO / "data" / "snapshots"

COMPLETE_GRADES = {"complete", "manual_override"}
TARGET_STREAK = 14
AFTERNOON_START_HOUR = 12
AFTERNOON_END_HOUR = 18
SNAPSHOT_INTERVAL_MIN = 10.0
GAP_TOLERANCE = 1.5
GAP_LIMIT_MIN = SNAPSHOT_INTERVAL_MIN * GAP_TOLERANCE  # 15 min

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def collapse_ledger_grades(path: Path) -> dict[str, str]:
    """date -> latest-written quality_grade (append-only ledger, last line wins)."""
    grades: dict[str, str] = {}
    if not path.exists():
        return grades
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            date = row.get("target_date")
            grade = row.get("quality_grade")
            if date and grade:
                grades[str(date)] = str(grade)
    return grades


def contiguous_complete_run(grades: dict[str, str]) -> tuple[list[str], str | None]:
    """Return (dates_in_run oldest->newest, most_recent_settled_date)."""
    if not grades:
        return [], None
    dates = sorted(grades)
    latest = dates[-1]
    run: list[str] = []
    for date in reversed(dates):
        if grades[date] in COMPLETE_GRADES:
            run.append(date)
        else:
            break
    run.reverse()
    return run, latest


def labels_latest_toronto_date(path: Path) -> str | None:
    if not path.exists():
        return None
    latest = None
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("market_id") == "toronto":
                    d = row.get("target_date")
                    if d and (latest is None or d > latest):
                        latest = d
    except OSError:
        return None
    return latest


def toronto_folder_for(date: dt.date) -> Path:
    slug = f"highest-temperature-in-toronto-on-{MONTHS[date.month - 1]}-{date.day}-{date.year}"
    return SNAPS / slug


def _parse_local(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def today_capture_health(today: dt.date) -> dict:
    """Live read of today's afternoon (12:00-18:00) snapshot cadence."""
    folder = toronto_folder_for(today)
    wide = folder / "snapshots_wide.csv"
    out: dict = {"date": today.isoformat(), "folder_exists": folder.exists(),
                 "captures": 0, "window_gaps": [], "max_window_gap_min": 0.0,
                 "window_covered": False, "verdict": "unknown", "reason": ""}
    if not wide.exists():
        out["reason"] = "no snapshots_wide.csv yet"
        return out
    times: list[dt.datetime] = []
    try:
        with wide.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                t = _parse_local(row.get("captured_at_local", ""))
                if t is not None:
                    times.append(t)
    except OSError as exc:
        out["reason"] = f"read error: {exc}"
        return out
    times.sort()
    out["captures"] = len(times)
    if not times:
        out["reason"] = "no captures parsed"
        return out

    tz = times[0].tzinfo
    ws = dt.datetime.combine(today, dt.time(AFTERNOON_START_HOUR), tzinfo=tz)
    we = dt.datetime.combine(today, dt.time(AFTERNOON_END_HOUR), tzinfo=tz)
    now = dt.datetime.now(tz)

    # window times with the nearest before/after boundary capture (mirrors grader)
    inside = [t for t in times if ws <= t <= we]
    before = max((t for t in times if t < ws), default=None)
    after = min((t for t in times if t > we), default=None)
    if before is not None and (not inside or inside[0] > ws):
        inside.insert(0, before)
    if after is not None and (not inside or inside[-1] < we):
        inside.append(after)

    gaps = []
    for a, b in zip(inside, inside[1:]):
        gap = (b - a).total_seconds() / 60.0
        if gap > GAP_LIMIT_MIN:
            gaps.append({"after": a.strftime("%H:%M"), "before": b.strftime("%H:%M"),
                         "gap_min": round(gap, 1)})
    out["window_gaps"] = gaps
    out["max_window_gap_min"] = max((g["gap_min"] for g in gaps), default=0.0)
    out["window_covered"] = bool(times[0] <= ws and times[-1] >= we)

    if gaps:
        out["verdict"] = "AT_RISK"
        out["reason"] = (f"{len(gaps)} in-window gap(s), max {out['max_window_gap_min']:.0f} min "
                         f"(>15 min dooms the day to partial)")
    elif now < we:
        covered_so_far = min(now, we)
        out["verdict"] = "on_track"
        out["reason"] = (f"clean so far; window covered through {covered_so_far:%H:%M}, "
                         f"closes 18:00")
    elif not out["window_covered"]:
        out["verdict"] = "AT_RISK"
        out["reason"] = "afternoon window not fully covered (12:00->18:00)"
    else:
        out["verdict"] = "clean"
        out["reason"] = "no in-window gaps; 12:00-18:00 covered"
    return out


def build_report() -> dict:
    grades = collapse_ledger_grades(LEDGER)
    run, latest = contiguous_complete_run(grades)
    streak = len(run)
    recent = sorted(grades)[-14:]

    completes = sum(1 for d in recent if grades[d] in COMPLETE_GRADES)
    last8 = sorted(grades)[-8:]
    completes8 = sum(1 for d in last8 if grades[d] in COMPLETE_GRADES)

    lock_date = None
    if latest:
        latest_d = dt.date.fromisoformat(latest)
        lock_date = (latest_d + dt.timedelta(days=TARGET_STREAK - streak)).isoformat()

    labels_latest = labels_latest_toronto_date(LABELS)
    promotion_lag = bool(latest and labels_latest and labels_latest < latest)

    today = dt.date.today()
    today_settled = today.isoformat() in grades
    today_health = None if today_settled else today_capture_health(today)

    return {
        "streak_days": streak,
        "target": TARGET_STREAK,
        "streak_start": run[0] if run else None,
        "most_recent_settled": latest,
        "most_recent_grade": grades.get(latest) if latest else None,
        "projected_lock_date_if_all_clean": lock_date,
        "recent_tape": [{"date": d, "grade": grades[d]} for d in recent],
        "complete_rate_last14": f"{completes}/{len(recent)}",
        "complete_rate_last8": f"{completes8}/{len(last8)}",
        "promotion_lag": promotion_lag,
        "ledger_latest": latest,
        "labels_latest": labels_latest,
        "today_health": today_health,
    }


def print_human(rep: dict) -> None:
    bar = "=" * 60
    print(bar)
    print(f"  TORONTO CODE-SOAK STREAK: {rep['streak_days']} / {rep['target']} "
          f"contiguous complete days")
    print(bar)
    if rep["streak_start"]:
        print(f"  day 1        : {rep['streak_start']}")
    print(f"  most recent  : {rep['most_recent_settled']}  ({rep['most_recent_grade']})")
    if rep["streak_days"] < rep["target"]:
        print(f"  need         : {rep['target'] - rep['streak_days']} more clean days -> "
              f"lock ~{rep['projected_lock_date_if_all_clean']} IF every day is complete")
    else:
        print("  LOCKABLE: 14-day window is available -- run the PIT preselection.")
    print(f"  complete rate: {rep['complete_rate_last8']} (last 8), "
          f"{rep['complete_rate_last14']} (last 14)")
    print()
    print("  recent tape (newest last):")
    for row in rep["recent_tape"]:
        mark = "OK " if row["grade"] in COMPLETE_GRADES else "-- "
        print(f"    {mark}{row['date']}  {row['grade']}")
    print()
    th = rep["today_health"]
    if th is None:
        print("  TODAY: already settled in the ledger.")
    else:
        v = th["verdict"]
        tag = {"clean": "CLEAN", "on_track": "ON TRACK", "AT_RISK": "*** AT RISK ***",
               "unknown": "UNKNOWN"}.get(v, v)
        print(f"  TODAY ({th['date']}) capture: {tag}")
        print(f"    captures={th['captures']}  max in-window gap={th['max_window_gap_min']:.0f} min")
        print(f"    {th['reason']}")
        for g in th["window_gaps"]:
            print(f"      gap {g['gap_min']:.0f} min: {g['after']} -> {g['before']}")
    if rep["promotion_lag"]:
        print()
        print(f"  ! PROMOTION LAG: ledger latest {rep['ledger_latest']} but "
              f"labels.csv latest {rep['labels_latest']} -- run the daily chain to promote.")
    print(bar)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Toronto code-soak streak status")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--monitor", action="store_true",
                    help="exit 3 if TODAY is AT_RISK (for scheduled early-warning)")
    args = ap.parse_args(argv)

    rep = build_report()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_human(rep)

    if args.monitor:
        th = rep["today_health"]
        if th and th["verdict"] == "AT_RISK":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
