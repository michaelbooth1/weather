"""Canonical supported time window for fixed International live sessions."""

from __future__ import annotations

from datetime import date, datetime, time as wall_time, timedelta, timezone
from zoneinfo import ZoneInfo


LIVE_WINDOW_TIMEZONE = ZoneInfo("America/Toronto")
LIVE_WINDOW_START = wall_time(0, 30)
LIVE_WINDOW_END = wall_time(9, 0)
LIVE_WINDOW_CLEANUP_RESERVE_SECONDS = 20


def execution_window_is_supported(
    start: datetime,
    stop: datetime,
    *,
    target_date: date | str,
) -> bool:
    """Return whether execution plus its full cleanup reserve stays supported."""

    try:
        target = (
            target_date
            if type(target_date) is date
            else date.fromisoformat(str(target_date))
        )
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or stop.tzinfo is None
            or stop.utcoffset() is None
            or not start.astimezone(timezone.utc) < stop.astimezone(timezone.utc)
        ):
            return False
        local_start = start.astimezone(LIVE_WINDOW_TIMEZONE)
        local_stop = stop.astimezone(LIVE_WINDOW_TIMEZONE)
        local_contained_end = (
            stop + timedelta(seconds=LIVE_WINDOW_CLEANUP_RESERVE_SECONDS)
        ).astimezone(LIVE_WINDOW_TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        local_start.date() == target
        and local_stop.date() == target
        and local_contained_end.date() == target
        and local_start.time() >= LIVE_WINDOW_START
        and local_contained_end.time() <= LIVE_WINDOW_END
    )
