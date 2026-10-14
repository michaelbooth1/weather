"""Failing-first DST tests for capture-day grading (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-H1 (graded 12:00-18:00 window
taken from the first capture's fixed UTC offset), DST-H2 (00:00-08:00 early-hour coverage
computed on the wall clock) and DST-M1 (live ``latest_age`` on the wall clock); earlier record:
full-audit-2026-09-18 time-units F4a/F4b.

Each test pins the correct behaviour and is ``xfail(strict=True, raises=AssertionError)``
while the defect is on master (a broken precondition raises ``RuntimeError``); the fixing
change must remove the marker.
"""

from __future__ import annotations

import csv
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.backtesting.settlement_ledger import material_coverage_gap_rows
from weather.collection.collection_health import (
    CAPTURE_CLOCK_TZ,
    coverage_summary,
    early_hour_coverage_summary,
    graded_window_zone,
    live_coverage_summary,
    parse_times,
)

TORONTO = ZoneInfo("America/Toronto")
NEW_YORK = ZoneInfo("America/New_York")
REPO = Path(__file__).resolve().parents[2]


def _capture_strings(start_utc, end_utc, step_minutes=10):
    """Capture stamps as the snapshot writer records ``captured_at_local``:
    ISO strings carrying the Toronto offset valid at each instant."""

    out = []
    current = start_utc
    while current <= end_utc:
        out.append(current.astimezone(TORONTO).isoformat())
        current += timedelta(minutes=step_minutes)
    return out


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


def _toronto_utc(year, month, day, hour, minute, fold=0):
    return datetime(year, month, day, hour, minute, tzinfo=TORONTO, fold=fold).astimezone(timezone.utc)


@pytest.mark.parametrize(
    ("day", "stop", "clean"),
    [
        # Fall-back day: covered to 18:05 EST is clean; stopping at 17:35 EST is not.
        (date(2026, 11, 1), (18, 5), True),
        (date(2026, 11, 1), (17, 35), False),
        # Spring-forward day: the first stamp is -05:00 but the window is 12:00-18:00 EDT.
        (date(2027, 3, 14), (18, 5), True),
        (date(2027, 3, 14), (17, 35), False),
        # Ordinary-day controls (daylight and standard time): the window is unchanged.
        (date(2026, 7, 15), (18, 5), True),
        (date(2026, 7, 15), (17, 35), False),
        (date(2026, 1, 15), (18, 5), True),
        (date(2026, 1, 15), (17, 35), False),
    ],
)
def test_graded_window_follows_the_capture_clock(day, stop, clean):
    start = _toronto_utc(day.year, day.month, day.day, 0, 5)
    end = _toronto_utc(day.year, day.month, day.day, *stop)

    summary = coverage_summary(parse_times(_capture_strings(start, end)), 10, target_date=day)

    assert summary["covers_afternoon"] is clean
    assert summary["clean"] is clean


@pytest.mark.parametrize("day", [date(2026, 11, 1), date(2026, 7, 15)])
def test_late_gap_is_inside_and_morning_gap_outside_the_graded_window(day):
    every = _capture_strings(
        _toronto_utc(day.year, day.month, day.day, 0, 5),
        _toronto_utc(day.year, day.month, day.day, 18, 5),
    )
    late_gap = [value for value in every if not ("T17:05" <= value[10:16] <= "T17:45")]
    morning_gap = [value for value in every if not ("T10:35" <= value[10:16] <= "T11:25")]

    late = coverage_summary(parse_times(late_gap), 10, target_date=day)
    morning = coverage_summary(parse_times(morning_gap), 10, target_date=day)

    # 16:55 -> 17:55 local is inside 12:00-18:00; 10:25 -> 11:35 local is not.
    # On 11-01 the defect's 11:00-17:00 EST window inverts both verdicts.
    assert late["clean"] is False
    assert [gap["gap_minutes"] for gap in late["gaps"]] == [60.0]
    assert morning["clean"] is True
    assert morning["gaps"] == []


def test_non_capture_clock_offsets_keep_their_own_window():
    # Stamps in a fixed offset that is not the capture clock's keep the window
    # in that offset (12:00-18:00 UTC here), as before.
    day = date(2026, 11, 1)
    start = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)
    stamps = [start + timedelta(minutes=10 * i) for i in range(6 * 18)]  # to 17:55Z

    short = coverage_summary(stamps, 10, target_date=day)
    full = coverage_summary(stamps + [datetime(2026, 11, 1, 18, 5, tzinfo=timezone.utc)], 10, target_date=day)

    assert short["covers_afternoon"] is False
    assert full["covers_afternoon"] is True
    assert full["clean"] is True


def _toronto_stamp(day, hour, minute):
    return datetime.fromisoformat(_toronto_utc(day.year, day.month, day.day, hour, minute).astimezone(TORONTO).isoformat())


@pytest.mark.parametrize(
    ("day", "after", "before", "label"),
    [
        # 16:20 -> 17:10 EST touches the 14:00-17:00 EST peak window.
        (date(2026, 11, 1), (16, 20), (17, 10), "peak_heating_window"),
        # 17:05 -> 17:55 EST is in the settlement window, after the peak.
        (date(2026, 11, 1), (17, 5), (17, 55), "settlement_window"),
        # 11:00 -> 11:59 EST is before the settlement window.
        (date(2026, 11, 1), (11, 0), (11, 59), "outside_settlement_window"),
        # Ordinary-day controls.
        (date(2026, 7, 15), (16, 20), (17, 10), "peak_heating_window"),
        (date(2026, 7, 15), (17, 5), (17, 55), "settlement_window"),
        (date(2026, 7, 15), (11, 0), (11, 59), "outside_settlement_window"),
    ],
)
def test_ledger_gap_window_labels_follow_the_capture_clock(day, after, before, label):
    coverage = {
        "first": _toronto_stamp(day, 0, 5),
        "gaps": [{"after": _toronto_stamp(day, *after), "before": _toronto_stamp(day, *before), "gap_minutes": 50.0}],
    }

    rows = material_coverage_gap_rows(coverage, target_date=day)

    assert [row["window"] for row in rows] == [label]


def _load_streak_status():
    spec = importlib.util.spec_from_file_location(
        "streak_status_dst_h1", REPO / "scripts" / "ops" / "streak_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("day", "stop", "verdict"),
    [
        # Loop stopped at 17:35 EST; at 18:30 EST 18:00 is uncovered.
        (date(2026, 11, 1), (17, 35), "AT_RISK"),
        (date(2026, 11, 1), (18, 5), "clean"),
        # Ordinary-day controls.
        (date(2026, 7, 15), (17, 35), "AT_RISK"),
        (date(2026, 7, 15), (18, 5), "clean"),
    ],
)
def test_streak_today_window_follows_the_toronto_clock(tmp_path, monkeypatch, day, stop, verdict):
    streak = _load_streak_status()
    monkeypatch.setattr(streak, "SNAPS", tmp_path)
    folder = streak.toronto_folder_for(day)
    folder.mkdir(parents=True)
    strings = _capture_strings(
        _toronto_utc(day.year, day.month, day.day, 0, 5),
        _toronto_utc(day.year, day.month, day.day, *stop),
    )
    with (folder / "snapshots_wide.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["captured_at_local"])
        writer.writerows([value] for value in strings)

    now = _toronto_utc(day.year, day.month, day.day, 18, 30).astimezone(TORONTO)
    out = streak.today_capture_health(day, now_override=now)

    assert out["verdict"] == verdict, out["reason"]
    assert out["window_covered"] is (verdict == "clean")


def _ny_utc(year, month, day, hour, minute, fold=0):
    return datetime(year, month, day, hour, minute, tzinfo=NEW_YORK, fold=fold).astimezone(timezone.utc)


@pytest.mark.parametrize(
    ("last", "as_of", "age", "state"),
    [
        # Healthy through the repeated hour: last 01:20 EST, read at 01:25 EST.
        (_ny_utc(2026, 11, 1, 1, 20, fold=1), _ny_utc(2026, 11, 1, 1, 25, fold=1), 5.0, "COLLECTING"),
        # Loop died at 01:00 EST; at 01:30 EST the latest capture is 30 minutes old.
        (_ny_utc(2026, 11, 1, 1, 0, fold=1), _ny_utc(2026, 11, 1, 1, 30, fold=1), 30.0, "AT_RISK"),
        # Spring-forward: 01:50 EST -> 03:00 EDT is ten real minutes (defect: 70).
        (_ny_utc(2027, 3, 14, 1, 50), _ny_utc(2027, 3, 14, 3, 0), 10.0, "COLLECTING"),
        # Ordinary-day controls.
        (_ny_utc(2026, 7, 15, 1, 20), _ny_utc(2026, 7, 15, 1, 25), 5.0, "COLLECTING"),
        (_ny_utc(2026, 7, 15, 1, 0), _ny_utc(2026, 7, 15, 1, 30), 30.0, "AT_RISK"),
    ],
)
def test_live_latest_age_is_elapsed_time_across_dst(last, as_of, age, state):
    day = last.astimezone(NEW_YORK).date()
    current, times = _ny_utc(day.year, day.month, day.day, 0, 0), []
    while current <= last:
        times.append(current.astimezone(NEW_YORK))  # as summarize_folder passes them
        current += timedelta(minutes=10)

    summary = live_coverage_summary(times, 10, as_of=as_of.astimezone(NEW_YORK), target_date=day)

    assert summary["latest_age_minutes"] == pytest.approx(age)
    assert summary["state"] == state, summary["reason"]


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
    # captures; 43 exist). Before the instant-ordered gap fix (branch
    # claude/dst-h1-m1-m2-utc-20261011) it also read 01:50 EST -> 03:00 EDT as a
    # 70-minute gap; the minimum-count defect still fails the status assertion.
    assert summary["gap_count"] == 0, summary["reason"]
    assert summary["status"] == "PASS", summary["reason"]
    assert summary["counts_toward_early_hour_evidence"] is True


# --- Gap arithmetic on instants (follow-up to DST-H1, defender MF-1) -------------------

DST_ZONES = (
    ZoneInfo("America/Toronto"),
    ZoneInfo("America/New_York"),
    ZoneInfo("America/Chicago"),
    ZoneInfo("America/Denver"),
    ZoneInfo("America/Los_Angeles"),
)


def _zone_cadence(zone, day, stop_hour, skip_est_minutes=()):
    """Every 10 real minutes from local 00:00 to ``stop_hour``:00, in ``zone``,
    leaving out the second-pass (standard-time) 01:mm captures listed."""

    current = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc)
    stop = datetime(day.year, day.month, day.day, stop_hour, tzinfo=zone).astimezone(timezone.utc)
    out = []
    while current <= stop:
        local = current.astimezone(zone)
        second_pass = local.hour == 1 and local.fold == 1
        if not (second_pass and local.minute in skip_est_minutes):
            out.append(local)
        current += timedelta(minutes=10)
    return out


@pytest.mark.parametrize("zone", DST_ZONES, ids=lambda zone: zone.key)
def test_fall_back_day_complete_early_hour_cadence_passes(zone):
    day = date(2026, 11, 1)
    times = _zone_cadence(zone, day, 8)
    if not any(value.fold == 1 and value.hour == 1 for value in times):
        raise RuntimeError("precondition: the cadence crosses the repeated hour")

    summary = early_hour_coverage_summary(
        times, 10, target_date=day, as_of=datetime(2026, 11, 1, 9, 0, tzinfo=zone), native_tz=zone
    )

    assert summary["gap_count"] == 0, summary["reason"]
    assert summary["status"] == "PASS", summary["reason"]
    assert summary["counts_toward_early_hour_evidence"] is True


@pytest.mark.parametrize("zone", DST_ZONES, ids=lambda zone: zone.key)
def test_fall_back_day_early_hour_outage_in_the_repeated_hour_blocks(zone):
    day = date(2026, 11, 1)
    # 01:50 daylight -> 01:30 standard is a 40-minute outage; on the wall clock
    # it reads -20 minutes, and a wall-clock sort interleaves it away.
    times = _zone_cadence(zone, day, 8, skip_est_minutes=(0, 10, 20))

    summary = early_hour_coverage_summary(
        times, 10, target_date=day, as_of=datetime(2026, 11, 1, 9, 0, tzinfo=zone), native_tz=zone
    )

    assert summary["status"] == "BLOCK", summary["reason"]
    assert summary["gap_count"] == 1, summary["reason"]
    assert summary["max_gap_minutes"] == pytest.approx(40.0)


@pytest.mark.parametrize(
    ("skip", "gap_minutes"),
    [((), []), ((0, 10, 20), [40.0])],
    ids=["complete", "outage"],
)
def test_undated_coverage_gaps_are_instant_ordered_on_the_fall_back_day(skip, gap_minutes):
    # Without a target date every capture is a gap candidate, including the repeated hour.
    times = _zone_cadence(TORONTO, date(2026, 11, 1), 18, skip_est_minutes=skip)

    summary = coverage_summary(times, 10)

    assert [gap["gap_minutes"] for gap in summary["gaps"]] == gap_minutes
    assert summary["span_minutes"] == pytest.approx(19 * 60.0)


PANAMA = ZoneInfo("America/Panama")


@pytest.mark.parametrize(("stop", "covered"), [((17, 35), False), ((18, 5), True)])
def test_coincident_fixed_offset_is_not_read_as_the_capture_clock(stop, covered):
    # America/Panama is -05:00 all year. On 2027-03-14 its early stamps match
    # Toronto's EST offset, but from 03:00 EDT they do not, so the stamps are
    # not the capture clock and keep their own 12:00-18:00 -05:00 window.
    day = date(2027, 3, 14)
    start = datetime(2027, 3, 14, 0, 5, tzinfo=PANAMA).astimezone(timezone.utc)
    end = datetime(2027, 3, 14, *stop, tzinfo=PANAMA).astimezone(timezone.utc)
    strings = []
    current = start
    while current <= end:
        strings.append(current.astimezone(PANAMA).isoformat())
        current += timedelta(minutes=10)
    stamps = parse_times(strings)

    summary = coverage_summary(stamps, 10, target_date=day)

    assert graded_window_zone(stamps) is stamps[0].tzinfo
    assert summary["covers_afternoon"] is covered
    assert summary["clean"] is covered


def test_capture_clock_stamps_are_read_as_the_capture_clock():
    day = date(2026, 11, 1)
    stamps = parse_times(_capture_strings(_toronto_utc(2026, 11, 1, 0, 5), _toronto_utc(2026, 11, 1, 18, 5)))

    assert graded_window_zone(stamps) is CAPTURE_CLOCK_TZ
    assert graded_window_zone([]) is None
    # An explicit zone overrides the inference: 12:00-18:00 Honolulu is not covered.
    utc_window = coverage_summary(stamps, 10, target_date=day, window_tz=ZoneInfo("Pacific/Honolulu"))
    assert utc_window["covers_afternoon"] is False
