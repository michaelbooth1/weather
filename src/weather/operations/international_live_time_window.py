"""Canonical supported time window for fixed International live sessions."""

from __future__ import annotations

from datetime import date, datetime, time as wall_time, timedelta, timezone
from zoneinfo import ZoneInfo


LIVE_WINDOW_TIMEZONE = ZoneInfo("America/Toronto")
LIVE_WINDOW_START = wall_time(0, 30)
LIVE_WINDOW_END = wall_time(9, 0)
LIVE_WINDOW_CLEANUP_RESERVE_SECONDS = 20
PORTABLE_MAX_TARGET_DATE_OFFSET_DAYS = 1


def portable_target_date_is_supported_at(
    moment: datetime,
    *,
    target_date: date | str,
    market_timezone: str | ZoneInfo,
) -> bool:
    """Return whether a target is current or next in the market calendar."""

    try:
        target = (
            target_date
            if type(target_date) is date
            else date.fromisoformat(str(target_date))
        )
        calendar_timezone = (
            market_timezone
            if isinstance(market_timezone, ZoneInfo)
            else ZoneInfo(str(market_timezone))
        )
        if moment.tzinfo is None or moment.utcoffset() is None:
            return False
        local_date = moment.astimezone(calendar_timezone).date()
        next_local_date = local_date + timedelta(
            days=PORTABLE_MAX_TARGET_DATE_OFFSET_DAYS
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return target in {local_date, next_local_date}


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


def portable_execution_window_is_supported(
    start: datetime,
    stop: datetime,
    *,
    target_date: date | str,
    market_timezone: str | ZoneInfo,
) -> bool:
    """Return whether a portable session is on-day or one-day-ahead.

    Portable execution may target the selected market's current local date or
    its immediately following local date.  Execution and the complete cleanup
    reserve must remain within one market-local execution calendar date.
    """

    try:
        target = (
            target_date
            if type(target_date) is date
            else date.fromisoformat(str(target_date))
        )
        calendar_timezone = (
            market_timezone
            if isinstance(market_timezone, ZoneInfo)
            else ZoneInfo(str(market_timezone))
        )
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or stop.tzinfo is None
            or stop.utcoffset() is None
            or not start.astimezone(timezone.utc) < stop.astimezone(timezone.utc)
        ):
            return False
        local_start = start.astimezone(calendar_timezone)
        local_stop = stop.astimezone(calendar_timezone)
        local_contained_end = (
            stop + timedelta(seconds=LIVE_WINDOW_CLEANUP_RESERVE_SECONDS)
        ).astimezone(calendar_timezone)
        execution_date = local_start.date()
        next_execution_date = execution_date + timedelta(
            days=PORTABLE_MAX_TARGET_DATE_OFFSET_DAYS
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (
        local_stop.date() == execution_date
        and local_contained_end.date() == execution_date
        and target in {execution_date, next_execution_date}
    )
