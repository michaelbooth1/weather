"""Read-only disclosure count for the maker clock supporting-trigger fix (branch
claude/mrv2-fix-clock-supporting-triggers-20261007).

Question: for each allowed UTC bundle day and event, how much extra ``new_high`` pull does the fixed
clock (supporting METAR/SWOB/WU-current triggers pull) carry that the old clock (WU-history triggers
only) did not?

Input: exactly the file the exporter reads, ``snapshots/observation_triggers.jsonl`` (or its ``.gz``
variant; rotated siblings are refused because ``maker_plugin_sources.Sources.triggers`` never reads
them). Rows are flattened from ``trigger_context.triggers`` as the exporter does.

Reserved window UTC 2026-09-30..2026-10-15:
- every reserved ``--date`` is refused before any file is opened;
- a row is dated (detection UTC day and target date) before anything about it is counted; a row whose
  detection day or target is reserved, or which cannot be dated, contributes to NO output field;
- an over-long line is skipped without aborting and without being counted anywhere.
Nothing is written except the JSON result on stdout or a new ``--out`` file.

Per (bundle UTC day d, event), the clock sees every trigger row of that event detected at or before
the end of d (as ``Sources.keep`` does), so rows from d-1 are read for that purpose only.

Fields per cell:
- ``new_only_detection_minutes``: distinct detection minutes on day d with a ``new_high`` under NEW
  and none under OLD. This counts pull onsets, not pulled time.
- ``first_new_high_utc_new`` / ``first_new_high_utc_old``: the first pull instant each clock sees.
- ``added_pulled_event_minutes``: a ``new_high`` never expires, so the event is pulled under NEW from
  its first pull onward. The added pulled time inside day d is from max(first NEW pull, start of d)
  to min(first OLD pull, clock failure, end of d). It is an UPPER bound because band close is not
  known here. ``--conditions {slug: open band count}`` turns it into ``added_pulled_condition_minutes``.
- ``clock_unavailable``: the runner discards the whole clock of an event-minute when ``observe``
  raises. A row whose detection time cannot be parsed raises at every minute of d, including
  minutes before that row was detected, so the cell is ``"all_day"`` and counts no added pull. An
  unparseable ``observed_at`` (a bare ``HH:MM`` included; live producers write ISO with an offset)
  no longer raises: the clock skips that row only (``clock.observed_time``, OD37), so it adds no pull
  and makes nothing unavailable. A row that fails later in ``observe`` makes the clock unavailable
  from its detection time; added pull stops there. If that detection time is at or before the start
  of d (a row from d-1), the runner loses the whole of d, so the cell is ``"all_day"`` too.

Fidelity limit: the numbers hold only for a well-formed trigger file. The exporter treats one
malformed or non-object line anywhere in the file as a corrupt ``triggers`` source, which makes every
event's clock unavailable on every bundle day; this counter drops such lines by design (custody) and
still reports pulls. The exporter's own ``triggers`` coverage/error fields are authoritative.

The OLD clock is the fixed clock restricted to ``wu_history_high_increased``/``wu_history`` rows: the
old code dropped every other row before any event, and kept every other filter. A test pins that
equivalence against a literal copy of the old loop.

Usage (repository root, project interpreter)::

    python -B -m tools.research.maker_clock_trigger_disclosure \
        --triggers data/snapshots/observation_triggers.jsonl --date 2026-09-27 --date 2026-09-28
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import gzip
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from weather.market.maker_plugin.clock import DECIDING_TRIGGER, WeatherInformationClock
from weather.market.maker_plugin.inputs import event_identity, records, timestamp

RESERVED_FIRST = date(2026, 9, 30)
RESERVED_LAST = date(2026, 10, 15)
MAX_LINE_BYTES = 4 * 1024 * 1024
LIVE_NAMES = ("observation_triggers.jsonl", "observation_triggers.jsonl.gz")
CLOCK_ERRORS = (ValueError, KeyError, TypeError, ArithmeticError)


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
    if _reserved(day):
        raise Refused("reserved_window_day_refused")
    return day


def _reserved(day):
    return RESERVED_FIRST <= day <= RESERVED_LAST


def _row_day(row):
    """(detection UTC day, target day), or None when the row cannot be dated."""
    try:
        detected = timestamp(row["current_captured_at_utc"]).date()
        target = date.fromisoformat(row["target_date"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return detected, target


def _lines(path):
    """Lines of at most MAX_LINE_BYTES; a longer line is consumed and dropped, never returned."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as handle:
        while True:
            line = handle.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES:
                while line and not line.endswith(b"\n"):
                    line = handle.readline(MAX_LINE_BYTES + 1)
                continue
            yield line


def trigger_rows(path, days):
    """(detection day, row) for dated, non-reserved rows detected on a day in ``days`` or the day
    before each (the clock of bundle day d sees rows detected up to the end of d). Nothing about any
    other line is retained or counted."""
    wanted = set(days) | {d - timedelta(days=1) for d in days}
    for line in _lines(path):
        try:
            outer = json.loads(line)
        except (ValueError, RecursionError):  # A deeply nested line must not abort the run.
            continue
        if not isinstance(outer, dict):
            continue
        context = outer.get("trigger_context")
        items = context.get("triggers", [outer]) if isinstance(context, dict) else [outer]
        if not isinstance(items, list):
            continue
        for row in items:
            if not isinstance(row, dict):
                continue
            when = _row_day(row)
            if when is None or _reserved(when[0]) or _reserved(when[1]) or when[0] not in wanted:
                continue
            yield when[0], row


class _NoBands:
    """Bands that never decide: the count is about pulls only."""

    def bands(self, event_id, as_of):
        return defaultdict(lambda: (math.inf, math.inf))


def _market(slug):
    return SimpleNamespace(event_id=slug, condition_id=str(slug),
                           close_at_utc=datetime.max.replace(tzinfo=timezone.utc))


def _new_high_times(row, *, old):
    """Detection instants of ``new_high`` events for one row, or raise the clock's own error."""
    if old and (row.get("reason"), row.get("source")) != DECIDING_TRIGGER:
        return set()
    as_of = timestamp(row["current_captured_at_utc"])
    events = WeatherInformationClock(_NoBands(), triggers=[row]).observe((_market(row.get("event_slug")),), as_of)
    return {e.detected_at_utc for e in events if e.kind == "new_high"}


def _fails_every_minute(row):
    """True when ``observe`` raises for this row whatever ``as_of`` is: the records copy, or the
    detection parse that precedes every other filter. (A bad observed_at skips the row instead.)"""
    try:
        records([row])
        timestamp(row["current_captured_at_utc"])
    except CLOCK_ERRORS:
        return True
    return False


def _minutes(start, end):
    return max(0., (end - start).total_seconds() / 60.)


def cell(day, slug, kept, bands=None):
    start = datetime.combine(day, time(), timezone.utc)
    end = start + timedelta(days=1)
    try:
        market_id = event_identity(slug)[0].id
    except (ValueError, TypeError, AttributeError):
        market_id = "unregistered"
    out = {"day": day.isoformat(), "market_id": market_id, "event_slug": slug,
           "trigger_rows_detected_on_day": sum(1 for d, _ in kept if d == day),
           "clock_unavailable": None, "new_only_detection_minutes": 0,
           "first_new_high_utc_new": None, "first_new_high_utc_old": None,
           "added_pulled_event_minutes": 0., "conditions": bands, "added_pulled_condition_minutes": None}
    if any(_fails_every_minute(row) for _, row in kept):
        out["clock_unavailable"] = "all_day"
        return out
    new, old, failure = set(), set(), None
    for _, row in kept:
        try:
            row_new, row_old = _new_high_times(row, old=False), _new_high_times(row, old=True)
        except CLOCK_ERRORS:
            at = timestamp(row["current_captured_at_utc"])
            failure = at if failure is None else min(failure, at)
            continue
        new |= row_new
        old |= row_old
    if failure is not None:
        # A failure at or before the start of d (a d-1 row) makes observe raise at every minute of d.
        out["clock_unavailable"] = "all_day" if failure <= start else "from " + failure.isoformat()
        new = {t for t in new if t < failure}
        old = {t for t in old if t < failure}
    minute = lambda t: t.replace(second=0, microsecond=0)
    on_day = lambda times: {minute(t) for t in times if start <= t < end}
    out["new_only_detection_minutes"] = len(on_day(new) - on_day(old))
    first_new, first_old = min(new, default=None), min(old, default=None)
    out["first_new_high_utc_new"] = first_new and first_new.isoformat()
    out["first_new_high_utc_old"] = first_old and first_old.isoformat()
    if first_new is not None and (first_old is None or first_new < first_old):
        stop = min(t for t in (first_old, failure, end) if t is not None)
        out["added_pulled_event_minutes"] = round(_minutes(max(first_new, start), min(stop, end)), 6)
    if bands is not None:
        out["added_pulled_condition_minutes"] = round(out["added_pulled_event_minutes"] * int(bands), 6)
    return out


def count(rows, days, conditions=None):
    conditions = conditions or {}
    by_slug = defaultdict(list)
    for detected, row in rows:
        by_slug[str(row.get("event_slug"))].append((detected, row))
    cells = []
    for day in sorted(days):
        for slug in sorted(by_slug):
            kept = [(d, r) for d, r in by_slug[slug] if d <= day]
            if any(d == day for d, _ in kept):
                cells.append(cell(day, slug, kept, conditions.get(slug)))
    return cells


def summarize(cells):
    by_day = {}
    for item in cells:
        total = by_day.setdefault(item["day"], {
            "events": 0, "events_clock_unavailable_all_day": 0, "events_clock_unavailable_partly": 0,
            "events_with_added_pull": 0, "new_only_detection_minutes": 0, "added_pulled_event_minutes": 0.,
            "added_pulled_condition_minutes": 0., "events_without_condition_count": 0})
        total["events"] += 1
        if item["clock_unavailable"] == "all_day":
            total["events_clock_unavailable_all_day"] += 1
        elif item["clock_unavailable"]:
            total["events_clock_unavailable_partly"] += 1
        total["events_with_added_pull"] += item["added_pulled_event_minutes"] > 0
        total["new_only_detection_minutes"] += item["new_only_detection_minutes"]
        total["added_pulled_event_minutes"] += item["added_pulled_event_minutes"]
        if item["added_pulled_condition_minutes"] is None:
            total["events_without_condition_count"] += 1
        else:
            total["added_pulled_condition_minutes"] += item["added_pulled_condition_minutes"]
    return dict(sorted(by_day.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", action="append", required=True, help="allowed UTC day YYYY-MM-DD (repeat)")
    parser.add_argument("--triggers", required=True, type=Path,
                        help="the live snapshots/observation_triggers.jsonl[.gz] the exporter reads")
    parser.add_argument("--conditions", type=Path, help="JSON {event_slug: open band count}")
    parser.add_argument("--out", type=Path, help="write the JSON result here (a new file) instead of stdout")
    args = parser.parse_args(argv)
    try:
        days = sorted({allowed_day(text) for text in args.date})  # First: before any file is opened.
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    if args.triggers.name not in LIVE_NAMES:
        print("REFUSED: not_the_live_trigger_file", file=sys.stderr)
        return 2
    if args.out and args.out.exists():
        print("REFUSED: out_exists", file=sys.stderr)
        return 2
    conditions = json.loads(args.conditions.read_text(encoding="utf-8")) if args.conditions else None
    cells = count(trigger_rows(args.triggers, days), days, conditions)
    result = {"schema": "maker_clock_trigger_disclosure_v2", "days": [d.isoformat() for d in days],
              "reserved_window": [RESERVED_FIRST.isoformat(), RESERVED_LAST.isoformat()],
              "by_day": summarize(cells), "cells": cells}
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
