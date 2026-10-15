"""PL-1 reader: ``read(family, as_of_utc, purpose, days=...)`` with embargo and per-basis PIT policy.

- Every requested UTC day is checked against the embargo windows **before** any file is opened
  (:func:`weather.evidence.embargo.check_read`): a ``full`` day refuses every purpose; an
  ``outcome`` or MG-1 reserved day refuses ``outcome_join`` and candidates and allows
  ``capture_check``.
- A row whose own ``event_date`` is refused for the purpose is dropped and counted.
- Rows first seen after ``as_of_utc`` are invisible to every purpose.
- For ``candidate=<name>`` (point-in-time) reads: ``archive_proxy`` and ``stitched_no_issue`` rows
  are refused; ``provider_stamp`` / ``s3_lastmodified`` rows become visible only at
  ``provider_time + pit_margin_seconds`` and carry ``pit_tag=HISTORICAL_FIRST_AVAILABILITY_UNPROVEN``;
  without a declared margin they stay invisible. ``live_receipt`` rows use ``first_seen_utc``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from weather.evidence.embargo import CANDIDATE, check_read, parse_purpose, read_refusal
from weather.evidence.envelope import PIT_REFUSED_BASES, PIT_UNPROVEN_TAG, STAMPED_BASES, parse_utc
from weather.evidence.journal import NAME_RE, iter_segment_rows, segment_dirs


@dataclass
class ReadResult:
    rows: list = field(default_factory=list)
    hidden: Counter = field(default_factory=Counter)


def _visible_time(row):
    return row.get("first_seen_utc") or row.get("captured_at_utc")


def read(family, as_of_utc, purpose, *, days, root, kinds=("row",), pit_margin_seconds=None) -> ReadResult:
    if not NAME_RE.match(str(family)):
        raise ValueError("invalid family id")
    kind, _ = parse_purpose(purpose)
    as_of = parse_utc(as_of_utc)
    days = sorted({str(day) for day in days})
    for day in days:
        check_read(day, purpose)
    margin = None if pit_margin_seconds is None else timedelta(seconds=float(pit_margin_seconds))
    result = ReadResult()
    family_root = Path(root) / family
    for day in days:
        for segment in segment_dirs(family_root / day):
            for _, row in iter_segment_rows(segment):
                if row.get("kind") not in kinds:
                    continue
                seen = _visible_time(row)
                if seen is None or parse_utc(seen) > as_of:
                    result.hidden["after_as_of"] += 1
                    continue
                event_date = row.get("event_date")
                if event_date and read_refusal(event_date, purpose):
                    result.hidden["embargoed_event_date"] += 1
                    continue
                if kind == CANDIDATE and row.get("kind") == "row":
                    basis = row.get("availability_basis")
                    if basis in PIT_REFUSED_BASES:
                        result.hidden["basis_refused_for_pit"] += 1
                        continue
                    if basis in STAMPED_BASES:
                        stamp = row.get("provider_time")
                        if margin is None or not stamp:
                            result.hidden["stamped_without_declared_margin"] += 1
                            continue
                        if parse_utc(stamp) + margin > as_of:
                            result.hidden["stamp_plus_margin_after_as_of"] += 1
                            continue
                        row = {**row, "pit_tag": PIT_UNPROVEN_TAG}
                result.rows.append(row)
    return result
