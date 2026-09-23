from __future__ import annotations

from datetime import datetime, timezone
import math


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat()


def parse_datetime(value, *, default_tz=timezone.utc) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None and default_tz is not None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed


def age_seconds(now: datetime, value, *, default_tz=timezone.utc) -> float | None:
    parsed = parse_datetime(value, default_tz=default_tz)
    if parsed is None:
        return None
    if now.tzinfo is None and parsed.tzinfo is not None:
        now = now.replace(tzinfo=parsed.tzinfo)
    elif now.tzinfo is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return (now - parsed).total_seconds()


def age_minutes(now: datetime, value, *, default_tz=timezone.utc) -> float | None:
    seconds = age_seconds(now, value, default_tz=default_tz)
    return seconds / 60.0 if seconds is not None else None


def evidence_age_seconds(now, *, timestamp=None, reported_age=None, reported_at=None,
                         clock_skew_seconds=0.0, consistency_seconds=1.0):
    """Validate time evidence before treating it as fresh.

    Missing evidence remains unknown. Invalid or future timestamps cannot be
    rescued by a supplied age. When both are present, their ages must agree
    within the explicit rounding tolerance; the older value wins. A captured
    age is first advanced from its own observation time to ``now``. Clock skew
    is zero by default, so negative evidence is never silently made current.
    """
    if not math.isfinite(clock_skew_seconds) or clock_skew_seconds < 0:
        return None
    if not math.isfinite(consistency_seconds) or consistency_seconds < 0:
        return None
    ages = []
    if timestamp is not None:
        parsed_now = parse_datetime(now)
        if parsed_now is None:
            return None
        seconds = age_seconds(parsed_now, timestamp)
        if seconds is None or seconds < -clock_skew_seconds:
            return None
        ages.append(max(0.0, seconds))
    if reported_age is not None:
        if isinstance(reported_age, bool):
            return None
        try:
            seconds = float(reported_age)
        except (ValueError, TypeError, OverflowError):
            return None
        if not math.isfinite(seconds) or seconds < -clock_skew_seconds:
            return None
        seconds = max(0.0, seconds)
        if reported_at is not None:
            elapsed = evidence_age_seconds(now, timestamp=reported_at,
                                           clock_skew_seconds=clock_skew_seconds)
            if elapsed is None:
                return None
            seconds += elapsed
        ages.append(seconds)
    if not ages or max(ages) - min(ages) > consistency_seconds:
        return None
    return max(ages)
