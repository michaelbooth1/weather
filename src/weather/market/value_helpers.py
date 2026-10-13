"""Policy-independent scalar and UTC value interpretation."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from weather.time import utc_now

def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_present(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def age_seconds(timestamp, now):
    parsed = parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())
