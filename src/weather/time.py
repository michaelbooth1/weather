from __future__ import annotations

from datetime import datetime, timezone


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
