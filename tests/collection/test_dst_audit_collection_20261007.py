"""Failing-first DST tests for capture-day grading (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-H1 (graded 12:00-18:00 window
taken from the first capture's fixed UTC offset) and DST-H2 (00:00-08:00 early-hour coverage
computed on the wall clock); earlier record: full-audit-2026-09-18 time-units F4a/F4b.

Each test pins the correct behaviour and is ``xfail(strict=True, raises=AssertionError)``
while the defect is on master (a broken precondition raises ``RuntimeError``); the fixing
change must remove the marker.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from weather.collection.collection_health import (
    coverage_summary,
    early_hour_coverage_summary,
    parse_times,
)

TORONTO = ZoneInfo("America/Toronto")
NEW_YORK = ZoneInfo("America/New_York")


def _capture_strings(start_utc, end_utc, step_minutes=10):
    """Capture stamps as the snapshot writer records ``captured_at_local``:
    ISO strings carrying the Toronto offset valid at each instant."""

    out = []
    current = start_utc
    while current <= end_utc:
        out.append(current.astimezone(TORONTO).isoformat())
        current += timedelta(minutes=step_minutes)
    return out


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-H1")
def test_fall_back_day_graded_window_is_twelve_to_eighteen_standard_time():
    day = date(2026, 11, 1)
    # Captures every 10 minutes from 00:05 EDT until 17:35 EST, then the loop stops.
    start = datetime(2026, 11, 1, 0, 5, tzinfo=TORONTO).astimezone(timezone.utc)
    stop = datetime(2026, 11, 1, 17, 35, tzinfo=TORONTO).astimezone(timezone.utc)
    strings = _capture_strings(start, stop)
    if not (strings[0].endswith("-04:00") and strings[-1].endswith("-05:00")):
        raise RuntimeError("precondition: the stamps carry both offsets of the fall-back day")

    summary = coverage_summary(parse_times(strings), 10, target_date=day)

    # 17:35-18:00 EST of the graded window has no capture, so the day is not clean.
    # The defect builds the window from the first capture's -04:00 offset, i.e.
    # 11:00-17:00 EST, and grades the day clean.
    assert summary["covers_afternoon"] is False
    assert summary["clean"] is False


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-H2")
def test_spring_forward_day_complete_early_hour_cadence_is_countable():
    day = date(2027, 3, 14)
    # A healthy loop: one capture every 10 real minutes from local 00:00 EST to 08:10 EDT.
    start = datetime(2027, 3, 14, 0, 0, tzinfo=NEW_YORK).astimezone(timezone.utc)
    stop = datetime(2027, 3, 14, 8, 10, tzinfo=NEW_YORK).astimezone(timezone.utc)
    times = [datetime.fromisoformat(value) for value in _capture_strings(start, stop)]
    as_of = datetime(2027, 3, 14, 9, 0, tzinfo=NEW_YORK)

    summary = early_hour_coverage_summary(
        times, 10, target_date=day, as_of=as_of, native_tz=NEW_YORK
    )

    # The defect measures the 7-hour window as 480 wall minutes (minimum 48
    # captures; 43 exist) and reads 01:50 EST -> 03:00 EDT as a 70-minute gap.
    assert summary["gap_count"] == 0, summary["reason"]
    assert summary["status"] == "PASS", summary["reason"]
    assert summary["counts_toward_early_hour_evidence"] is True
