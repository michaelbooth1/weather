"""Read-only disclosure count for the maker clock supporting-trigger fix (branch
claude/mrv2-fix-clock-supporting-triggers-20261007).

Question: on allowed UTC days, how many condition-minutes carry a ``new_high`` pull under the fixed
clock (supporting METAR/SWOB/WU-current triggers pull) that the old clock (WU-history triggers only)
dropped?

Input is the captured observation-trigger log (``snapshots/observation_triggers.jsonl``, optionally
``.gz``), read line by line exactly as ``maker_plugin_sources.Sources.triggers`` flattens it. Nothing
is written except the JSON result on stdout (or ``--out``). Every day in the reserved panel window
UTC 2026-09-30..2026-10-15 is refused before any file is opened, and any trigger row detected on, or
targeting, a reserved day is dropped unread beyond its two date fields.

Unit of count: one ``new_high`` event per (event, detection minute) affects every open band of that
event identically, so the base count is event-minutes. ``--conditions`` (JSON ``{event_slug: n}``,
the number of open bands of that event) turns it into condition-minutes; without it they are null.

The OLD clock is the fixed clock restricted to ``wu_history_high_increased``/``wu_history`` rows: the
old code dropped every other row before any event, and kept every other filter. A test pins that
equivalence against a literal copy of the old loop.

Usage (repository root, project interpreter)::

    python -B -m tools.research.maker_clock_trigger_disclosure \
        --triggers data/snapshots/observation_triggers.jsonl --date 2026-09-27 --date 2026-09-28
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from weather.market.maker_plugin.clock import DECIDING_TRIGGER, WeatherInformationClock
from weather.market.maker_plugin.inputs import event_identity, timestamp

RESERVED_FIRST = date(2026, 9, 30)
RESERVED_LAST = date(2026, 10, 15)
MAX_LINE_BYTES = 4 * 1024 * 1024


class Refused(ValueError):
    pass


def allowed_day(text):
    """A canonical YYYY-MM-DD outside the reserved window, or a refusal (U6 export-gate pattern)."""
    if not isinstance(text, str):
        raise Refused("day_required")
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise Refused("noncanonical_day") from None
    if day.isoformat() != text:
        raise Refused("noncanonical_day")
    if RESERVED_FIRST <= day <= RESERVED_LAST:
        raise Refused("reserved_window_day_refused")
    return day


def _reserved(day):
    return RESERVED_FIRST <= day <= RESERVED_LAST


def _row_day(row):
    """(detected UTC day, target day) or None. Read before anything else in the row."""
    try:
        detected = timestamp(row["current_captured_at_utc"]).date()
        target = date.fromisoformat(row["target_date"])
    except (KeyError, TypeError, ValueError):
        return None
    return detected, target


def _lines(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as handle:
        for line in handle:
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("line_too_long")
            yield line


def trigger_rows(paths, days, skipped):
    """Flattened trigger rows detected on an allowed day in ``days``; reserved rows never yielded."""
    wanted = set(days)
    for path in paths:
        for line in _lines(path):
            if not line.strip():
                continue
            try:
                outer = json.loads(line)
            except ValueError:
                skipped["bad_json"] += 1
                continue
            if not isinstance(outer, dict):
                skipped["not_object"] += 1
                continue
            context = outer.get("trigger_context")
            items = context.get("triggers", [outer]) if isinstance(context, dict) else [outer]
            for row in items:
                if not isinstance(row, dict):
                    skipped["not_object"] += 1
                    continue
                when = _row_day(row)
                if when is None:
                    skipped["no_day"] += 1
                    continue
                detected, target = when
                if _reserved(detected) or _reserved(target):
                    continue
                if detected not in wanted:
                    continue
                yield detected, row


class _NoBands:
    """Bands that never decide: the count is about pulls only."""

    def bands(self, event_id, as_of):
        return defaultdict(lambda: (math.inf, math.inf))


def _new_high_minutes(row, *, old):
    """Detection minutes of ``new_high`` events for one row, or raise the clock's own error."""
    if old and (row.get("reason"), row.get("source")) != DECIDING_TRIGGER:
        return set()
    market = SimpleNamespace(event_id=row.get("event_slug"), condition_id=str(row.get("event_slug")),
                             close_at_utc=datetime.max.replace(tzinfo=timezone.utc))
    as_of = timestamp(row["current_captured_at_utc"])
    events = WeatherInformationClock(_NoBands(), triggers=[row]).observe((market,), as_of)
    return {e.detected_at_utc.replace(second=0, microsecond=0) for e in events if e.kind == "new_high"}


def count(rows, conditions=None):
    conditions = conditions or {}
    cells = {}
    for day, row in rows:
        slug = row.get("event_slug")
        try:
            spec, _ = event_identity(slug)
            market_id = spec.id
        except (ValueError, TypeError, AttributeError):
            market_id = "unregistered"
        cell = cells.setdefault((day.isoformat(), market_id, str(slug)), {
            "rows": 0, "old": set(), "new": set(), "row_errors": Counter(), "reasons": Counter()})
        cell["rows"] += 1
        cell["reasons"][f"{row.get('source')}:{row.get('reason')}"] += 1
        try:
            new = _new_high_minutes(row, old=False)
            old = _new_high_minutes(row, old=True)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            # The plugin runner marks the whole event-minute's clock unavailable on this error.
            cell["row_errors"][f"{row.get('source')}:{type(exc).__name__}:{str(exc)[:60]}"] += 1
            continue
        cell["old"] |= old
        cell["new"] |= new
    out = []
    for (day, market_id, slug), cell in sorted(cells.items()):
        new_only = len(cell["new"] - cell["old"])
        bands = conditions.get(slug)
        out.append({
            "day": day, "market_id": market_id, "event_slug": slug, "trigger_rows": cell["rows"],
            "trigger_rows_by_source_reason": dict(sorted(cell["reasons"].items())),
            "old_new_high_event_minutes": len(cell["old"]),
            "new_new_high_event_minutes": len(cell["new"]),
            "new_only_event_minutes": new_only,
            "conditions": bands,
            "new_only_condition_minutes": None if bands is None else new_only * int(bands),
            "row_errors": dict(sorted(cell["row_errors"].items())),
        })
    return out


def summarize(cells):
    by_day = defaultdict(lambda: Counter())
    for cell in cells:
        total = by_day[cell["day"]]
        total["new_only_event_minutes"] += cell["new_only_event_minutes"]
        total["old_new_high_event_minutes"] += cell["old_new_high_event_minutes"]
        total["row_errors"] += sum(cell["row_errors"].values())
        if cell["new_only_condition_minutes"] is None:
            total["events_without_condition_count"] += 1
        else:
            total["new_only_condition_minutes"] += cell["new_only_condition_minutes"]
    return {day: dict(values) for day, values in sorted(by_day.items())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", action="append", required=True, help="allowed UTC day YYYY-MM-DD (repeat)")
    parser.add_argument("--triggers", action="append", required=True, type=Path,
                        help="observation_triggers.jsonl[.gz] (repeat for rotations)")
    parser.add_argument("--conditions", type=Path, help="JSON {event_slug: open band count}")
    parser.add_argument("--out", type=Path, help="write the JSON result here instead of stdout")
    args = parser.parse_args(argv)
    try:
        days = sorted({allowed_day(text) for text in args.date})  # First: before any file is opened.
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    conditions = json.loads(args.conditions.read_text(encoding="utf-8")) if args.conditions else None
    skipped = Counter()
    cells = count(trigger_rows(args.triggers, days, skipped), conditions)
    result = {"schema": "maker_clock_trigger_disclosure_v1", "days": [d.isoformat() for d in days],
              "reserved_window": [RESERVED_FIRST.isoformat(), RESERVED_LAST.isoformat()],
              "skipped_rows": dict(sorted(skipped.items())), "by_day": summarize(cells), "cells": cells}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        if args.out.exists():
            print("REFUSED: out_exists", file=sys.stderr)
            return 2
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
