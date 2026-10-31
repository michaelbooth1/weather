from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utc_now(value=None, *, parser=None) -> datetime:
    """UTC clock, optionally using a caller's established input parser."""
    parsed = parser(value) if parser is not None else parse_datetime(value)
    if parsed is None:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


_MAX_PROVIDER_OFFSET_SECONDS = 86400


def _offset_seconds(value) -> int | None:
    """Whole-second offset from a provider scalar, or None when unusable.

    Accepts ints, floats and numeric strings ('-14400', -14400.0). Booleans,
    non-numeric text, NaN, infinities and offsets of a day or more are None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if abs(seconds) >= _MAX_PROVIDER_OFFSET_SECONDS:
        return None
    return seconds


def _labels_are_fixed_offset(labels) -> bool:
    """True when naive labels never repeat and step uniformly.

    A fixed-offset series is contiguous in UTC, so it neither repeats nor skips
    a label at a DST change; true wall-clock labels do one or the other. Any
    gap in the labels therefore also reads as not fixed-offset.
    """
    if len(set(labels)) != len(labels):
        return False
    steps = {later - earlier for earlier, later in zip(labels, labels[1:])}
    return len(steps) <= 1


def _label_sequence(times) -> list:
    if times is None or isinstance(times, (str, bytes, bytearray, dict)):
        return []
    try:
        return list(times)
    except Exception:  # provider input: never raise from the live loop
        return []


def _parse_label(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:  # provider input: an unusable label is skipped, not raised
        return None


def provider_hourly_local_times(times, zone, utc_offset_seconds=None) -> list[datetime | None]:
    """Aware ``zone``-local datetimes for a provider's hourly time labels.

    Open-Meteo returns naive labels plus one scalar ``utc_offset_seconds`` per
    response: the zone's offset when the request was served, applied to every
    label. Across a DST change those labels are fixed-offset, not wall-clock,
    so ``label.replace(tzinfo=zone)`` is one hour off on the far side. Such
    labels are read as ``label - offset`` in UTC and converted to ``zone``.

    If the labels instead repeat, skip or gap (true wall-clock labels), or the
    offset is missing or unusable, they keep the zone-local reading, with the
    second occurrence of a repeated label marked ``fold=1``. Labels with an
    explicit offset are converted. Unparseable labels yield ``None``. Where the
    offset matches the zone's (no DST change in play), the result equals the
    plain zone-local reading. Bad provider input never raises: every failing
    conversion falls back to the zone-local reading.
    """
    parsed = [_parse_label(raw) for raw in _label_sequence(times)]
    naive = [value for value in parsed if value is not None and value.tzinfo is None]
    offset = _offset_seconds(utc_offset_seconds)
    fixed_offset = offset is not None and _labels_are_fixed_offset(naive)
    result: list[datetime | None] = []
    seen: set[datetime] = set()
    for value in parsed:
        if value is None:
            result.append(None)
            continue
        if value.tzinfo is not None:
            try:
                result.append(value.astimezone(zone))
            except (OverflowError, ValueError):
                result.append(value.replace(tzinfo=zone))
            continue
        fold = 1 if value in seen else 0
        seen.add(value)
        zone_local = value.replace(tzinfo=zone, fold=fold)
        if fixed_offset:
            try:
                instant = (value - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)
                result.append(instant.astimezone(zone))
            except (OverflowError, ValueError):
                result.append(zone_local)
        else:
            result.append(zone_local)
    return result
