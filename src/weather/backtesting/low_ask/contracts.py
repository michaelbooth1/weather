"""Frozen strategy constants and strict, value-safe input validation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

UTC = timezone.utc
FIRST = date(2026, 11, 17)
LAST = date(2027, 1, 30)
FREEZE_BEFORE = datetime(2026, 11, 17, 5, tzinfo=UTC)
LOOK = datetime(2027, 2, 9, 23, tzinfo=UTC)
CITIES = {
    "atlanta": ("America/New_York", "KATL", "F"),
    "austin": ("America/Chicago", "KAUS", "F"),
    "chicago": ("America/Chicago", "KORD", "F"),
    "dallas": ("America/Chicago", "KDAL", "F"),
    "denver": ("America/Denver", "KDEN", "F"),
    "houston": ("America/Chicago", "KHOU", "F"),
    "los-angeles": ("America/Los_Angeles", "KLAX", "F"),
    "miami": ("America/New_York", "KMIA", "F"),
    "nyc": ("America/New_York", "KLGA", "F"),
    "san-francisco": ("America/Los_Angeles", "KSFO", "F"),
    "seattle": ("America/Los_Angeles", "KSEA", "F"),
    "toronto": ("America/Toronto", "CYYZ", "C"),
}
SHARES = Decimal(5)
CAPS = {"total": "300", "order": "15.80", "band": "19.60", "band_day": "30"}
ROLES = ("events", "observations", "books", "heartbeats", "resolutions", "integrity")
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ROWS = 200_000


class Refusal(ValueError):
    """A constant reason code; never include untrusted values in the message."""


def require(condition: bool, code: str = "invalid_input") -> None:
    if not condition:
        raise Refusal(code)


def exact(row: dict, fields: str) -> None:
    require(isinstance(row, dict) and set(row) == set(fields.split()), "fields")


def number(value) -> Decimal:
    require(isinstance(value, (str, int)) and not isinstance(value, bool), "decimal_type")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise Refusal("decimal") from None
    require(result.is_finite() and abs(result) <= Decimal("1e12"), "decimal_range")
    return result


def instant(value: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "utc_clock")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, TypeError):
        raise Refusal("utc_clock") from None
    require(result.utcoffset() == timedelta(0), "utc_clock")
    return result


def iso(value: datetime) -> str:
    require(value.tzinfo is not None, "aware_clock")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def local_cut(day: date, zone: str, hour: int) -> datetime:
    require(hour in (17, 18), "cut")
    return datetime.combine(day, time(hour), ZoneInfo(zone)).astimezone(UTC)


def trial_day(value: str) -> date:
    try:
        day = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise Refusal("target_date") from None
    require(FIRST <= day <= LAST, "date_scope")
    return day


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def json_bytes(data: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_field")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, "json_number"))
    except (ValueError, UnicodeError, TypeError):
        raise Refusal("json") from None


def sha(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "sha256")
    return value


def identity(row: dict) -> tuple[str, date]:
    require(row.get("city") in CITIES and row.get("family") == "lowest", "event_scope")
    return row["city"], trial_day(row.get("target_date"))


def schedule(as_of: datetime):
    for i in range((LAST - FIRST).days + 1):
        day = FIRST + timedelta(days=i)
        for city, (zone, _, _) in CITIES.items():
            for hour in (17, 18):
                cut = local_cut(day, zone, hour)
                if cut <= as_of:
                    yield city, day, hour, cut


def timezone_fingerprint() -> str:
    """Bind effective timezone behaviour for every trial wall hour and fold."""
    clocks = []
    for zone in sorted({v[0] for v in CITIES.values()}):
        for i in range((LAST - FIRST).days + 1):
            day = FIRST + timedelta(days=i)
            for hour in range(24):
                for fold in (0, 1):
                    local = datetime.combine(day, time(hour), ZoneInfo(zone)).replace(fold=fold)
                    clocks.append([zone, day.isoformat(), hour, fold, iso(local)])
    return digest(canonical(clocks))
