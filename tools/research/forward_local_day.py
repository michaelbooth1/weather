"""Lane L13: timezone-aware local-day bucketing for the forward recorders (ECMWF ENS, ECCC GEM).

The recorders store UTC times only; this module assigns rows to the market's local settlement day with ``zoneinfo``,
so a DST change (for example 2026-11-01 in the US and Canada) gives a 25-hour day, and a spring change gives a 23-hour
day, never a fixed UTC offset. Research / shadow only; nothing imports it outside lane L13 tools and tests.

Rules:

* A local day ``D`` is ``[local midnight of D, local midnight of D+1)`` converted to UTC.
* An instantaneous value (``start_utc == end_utc``) belongs to the day containing its time.
* A window value (maximum over ``(start_utc, end_utc]``) belongs to ``D`` only when the whole window lies inside ``D``.
  A window that crosses local midnight belongs to neither day; it is reported as an edge window for both, never mixed
  into either day's maximum.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc

# market id -> IANA timezone (weather.market.market_registry; a test checks them)
MARKET_TZ = {
    "toronto": "America/Toronto",
    "nyc": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "austin": "America/Chicago",
    "chicago": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "denver": "America/Denver",
    "los-angeles": "America/Los_Angeles",
    "san-francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
}


def _utc(t):
    if isinstance(t, str):
        t = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"naive datetime {t!r}")
    return t.astimezone(UTC)


def local_day_bounds(day, tz):
    """UTC [start, end) of local calendar day ``day`` in ``tz`` (23, 24 or 25 hours long across DST)."""
    z = ZoneInfo(tz) if isinstance(tz, str) else tz
    start = dt.datetime.combine(day, dt.time(0), tzinfo=z).astimezone(UTC)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), tzinfo=z).astimezone(UTC)
    return start, end


def window_local_day(start_utc, end_utc, tz):
    """Local day of a value: an instant (start == end) or a window (start, end]. ``None`` when it crosses midnight.

    Returns ``(local_date or None, start_local, end_local)``; the local times carry their UTC offset.
    """
    z = ZoneInfo(tz) if isinstance(tz, str) else tz
    s, e = _utc(start_utc), _utc(end_utc)
    if e < s:
        raise ValueError("window ends before it starts")
    sl, el = s.astimezone(z), e.astimezone(z)
    if s == e:
        return sl.date(), sl, el
    # (s, e] lies inside day D when D's local midnight <= s and e <= the next local midnight.
    day = sl.date()
    _, d_end = local_day_bounds(day, z)
    return (day if e <= d_end else None), sl, el


def local_fields(start_utc, end_utc, tz):
    """Fields to add to a recorded row: local date (or None), local window bounds with offsets, the midnight flag."""
    day, sl, el = window_local_day(start_utc, end_utc, tz)
    return {"tz": str(tz), "local_date": day.isoformat() if day else None,
            "window_start_local": sl.isoformat(), "window_end_local": el.isoformat(),
            "straddles_local_midnight": day is None}


def daily_max(rows, tz):
    """Per local day: maximum of the values that lie wholly inside the day, plus coverage and edge windows.

    ``rows``: iterables of dicts with ``start_utc``, ``end_utc`` (ISO or aware datetimes) and ``value``.
    Coverage counts window hours for window rows and distinct instants for instantaneous rows, so a consumer can
    require full coverage (``covered_hours == day_hours``) of a 23/24/25-hour day.
    """
    z = ZoneInfo(tz) if isinstance(tz, str) else tz
    days = defaultdict(lambda: {"max": None, "covered_hours": 0.0, "instants": set(), "edge_max": None, "edges": 0})
    for r in rows:
        s, e = _utc(r["start_utc"]), _utc(r["end_utc"])
        v = float(r["value"])
        day, sl, el = window_local_day(s, e, z)
        if day is None:
            for d in {sl.date(), el.date()}:
                b = days[d]
                b["edges"] += 1
                b["edge_max"] = v if b["edge_max"] is None else max(b["edge_max"], v)
            continue
        b = days[day]
        b["max"] = v if b["max"] is None else max(b["max"], v)
        if s == e:
            b["instants"].add(s)
        else:
            b["covered_hours"] += (e - s).total_seconds() / 3600.0
    out = {}
    for d, b in sorted(days.items()):
        start, end = local_day_bounds(d, z)
        out[d.isoformat()] = {"max": b["max"], "day_hours": (end - start).total_seconds() / 3600.0,
                              "covered_hours": b["covered_hours"], "instants": len(b["instants"]),
                              "edge_windows": b["edges"], "edge_max": b["edge_max"],
                              "day_start_utc": start.isoformat(), "day_end_utc": end.isoformat()}
    return out
