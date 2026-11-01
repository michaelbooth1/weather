"""Count overlapping reanalysis raw chunks and duplicate hours per market (item 340, duplicate chunks).

Read-only and stdlib only. For each market it lists exactly ``<root>/<icao>/raw`` and its ``year=YYYY``
subdirectories (by explicit paths, no wider recursion) and reports, as JSON counts:

- from file names alone: chunk files, overlapping file pairs, the days covered by two or more chunks (by year)
  and the merged overlap spans;
- with ``--read-labels`` (needs ``--max-end-date``): the hourly labels of every file whose named range ends on or
  before that date, keyed by UTC instant (naive label minus the response's ``utc_offset_seconds``), giving the
  duplicate hours and the local label dates that hold one. Files ending later are skipped unread.

It never reads, keeps or prints a value array; only ``hourly.time`` and ``utc_offset_seconds`` are used.

Usage (host: inside the heavy-work lease, morning slot):
    python tools/research/reanalysis_chunk_overlap_census.py --root <reanalysis root> \\
        [--markets kord,klga,...] [--read-labels --max-end-date YYYY-MM-DD] [--out <json path>]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "reanalysis_chunk_overlap_census_v1"
DEFAULT_MARKETS = ("cyyz", "katl", "kaus", "kbkf", "kdal", "khou", "klax", "klga", "kmia", "kord", "ksea", "ksfo")
MAX_SPANS = 50


def named_range(stem):
    """``(start, end)`` from a ``<start>_<end>`` stem, or None."""
    try:
        start_text, end_text = stem.split("_", 1)
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError:
        return None
    return (start, end) if start <= end else None


def list_chunk_files(market_raw):
    """``*.json`` files in ``market_raw/year=*`` only: two explicit directory listings, no recursion."""
    files = []
    if not market_raw.is_dir():
        return files
    with os.scandir(market_raw) as years:
        year_dirs = sorted(entry.path for entry in years if entry.is_dir() and entry.name.startswith("year="))
    for year_dir in year_dirs:
        with os.scandir(year_dir) as entries:
            files.extend(Path(entry.path) for entry in entries if entry.is_file() and entry.name.endswith(".json"))
    return sorted(files)


def _days(start, end):
    return [start + timedelta(days=step) for step in range((end - start).days + 1)]


def _spans(days):
    spans = []
    for day in sorted(days):
        if spans and day == spans[-1][1] + timedelta(days=1):
            spans[-1][1] = day
        else:
            spans.append([day, day])
    return [[start.isoformat(), end.isoformat(), (end - start).days + 1] for start, end in spans]


def name_census(files):
    ranges = []
    unnamed = 0
    for path in files:
        parsed = named_range(path.stem)
        if parsed is None:
            unnamed += 1
        else:
            ranges.append(parsed)
    ranges.sort()
    pairs = 0
    involved = set()
    for i, (_start, end) in enumerate(ranges):
        for j in range(i + 1, len(ranges)):
            if ranges[j][0] > end:
                break
            pairs += 1
            involved.update((i, j))
    cover = Counter(day for start, end in ranges for day in _days(start, end))
    overlap_days = [day for day, count in cover.items() if count >= 2]
    spans = _spans(overlap_days)
    return {
        "chunk_files": len(files),
        "unnamed_files": unnamed,
        "first_range_start": ranges[0][0].isoformat() if ranges else None,
        "last_range_end": max(end for _start, end in ranges).isoformat() if ranges else None,
        "overlapping_file_pairs": pairs,
        "files_in_an_overlap": len(involved),
        "overlap_day_count": len(overlap_days),
        "overlap_days_by_year": dict(sorted(Counter(str(day.year) for day in overlap_days).items())),
        "max_chunks_on_one_day": max(cover.values()) if cover else 0,
        "overlap_span_count": len(spans),
        "overlap_spans": spans[:MAX_SPANS],
    }


def response_offset(payload):
    value = payload.get("utc_offset_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value != int(value) or abs(value) >= 86400:
        return None
    return int(value)


def utc_key(label, offset):
    """``(UTC instant, label date)`` for one label, or None when it cannot be placed."""
    try:
        parsed = datetime.fromisoformat(str(label).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None), parsed.date()
    if offset is None:
        return None
    return parsed - timedelta(seconds=offset), parsed.date()


def label_census(files, max_end):
    seen = {}
    duplicate_hours = 0
    duplicate_dates = set()
    read = skipped_after = unreadable = unplaced = 0
    for path in files:
        parsed = named_range(path.stem)
        if parsed is None or parsed[1] > max_end:
            skipped_after += 1
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            labels = list((payload.get("hourly") or {}).get("time") or [])
        except (OSError, ValueError, AttributeError, TypeError):
            unreadable += 1
            continue
        read += 1
        offset = response_offset(payload)
        for label in labels:
            key = utc_key(label, offset) if label else None
            if key is None:
                unplaced += 1
                continue
            instant, label_date = key
            if instant in seen:
                duplicate_hours += 1
                duplicate_dates.add(seen[instant])
            else:
                seen[instant] = label_date
        del payload, labels
    return {
        "files_read": read,
        "files_skipped_unnamed_or_after_max_end": skipped_after,
        "files_unreadable": unreadable,
        "labels_unplaced": unplaced,
        "distinct_utc_hours": len(seen),
        "duplicate_hours": duplicate_hours,
        "duplicate_label_day_count": len(duplicate_dates),
        "duplicate_label_days_by_year": dict(sorted(Counter(str(day.year) for day in duplicate_dates).items())),
    }


def census(root, markets, *, read_labels=False, max_end=None):
    root = Path(root)
    result = {"schema": SCHEMA, "read_labels": read_labels,
              "max_end_date": max_end.isoformat() if max_end else None, "markets": {}}
    for icao in markets:
        files = list_chunk_files(root / icao / "raw")
        row = name_census(files)
        if read_labels:
            row["labels"] = label_census(files, max_end)
        result["markets"][icao] = row
    rows = result["markets"].values()
    result["totals"] = {
        key: sum(row[key] for row in rows)
        for key in ("chunk_files", "overlapping_file_pairs", "overlap_day_count")
    }
    if read_labels:
        result["totals"]["duplicate_hours"] = sum(row["labels"]["duplicate_hours"] for row in rows)
        result["totals"]["duplicate_label_day_count"] = sum(row["labels"]["duplicate_label_day_count"] for row in rows)
    return result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="The reanalysis root holding <icao>/raw (always a parameter).")
    parser.add_argument("--markets", default=",".join(DEFAULT_MARKETS), help="Comma-separated ICAO directory names.")
    parser.add_argument("--read-labels", action="store_true", help="Also read hourly labels (needs --max-end-date).")
    parser.add_argument("--max-end-date", default="", help="Read labels only from files ending on or before this date.")
    parser.add_argument("--out", default="", help="Also write the JSON here.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.read_labels and not args.max_end_date:
        print("--read-labels needs --max-end-date", file=sys.stderr)
        return 2
    max_end = date.fromisoformat(args.max_end_date) if args.max_end_date else None
    markets = [item.strip().lower() for item in args.markets.split(",") if item.strip()]
    result = census(args.root, markets, read_labels=args.read_labels, max_end=max_end)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
