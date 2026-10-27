"""Serve-time ``high_so_far`` with the trainer's definition: the running max since local 00:00.

The single implementation of the L8 parity definition (lane L8, 2026-10-24). Both the shadow serve
path (``ModelUtilsMixin.observed_running_max_since_midnight`` under L8's since-midnight
``high_so_far_shadow_variant``) and offline replays (lane L3's OLS + floor, MG-2) call
``running_max_since_midnight``; ``tests/model/test_high_so_far_parity_shadow.py`` pins it to the
trainer (``feature_store.build_historical_feature_record``) and to ``lockin_observed_rows``.

Definition: the maximum temperature over the captured METAR / station rows whose OBSERVATION instant
falls on the target local date at or before ``cutoff_hour``:00 (and at or before ``now`` when given).
The observation instant is the AWC payload ``obsTime`` when retained, else the raw ``DDHHMMZ`` group
anchored on ``report_time`` / ``datetime`` (never AWC's nominal hour), else a row ``obs_time``, else the
row's local ``local_time`` / ``time`` (no date check possible). So the previous day's 23:5x report that
AWC files as the ``00:00`` row is excluded. Implausible values are skipped. Pure: no model state.

Stable signature (do not change without re-pinning both callers)::

    running_max_since_midnight(station, metar, *, target_date, tz, unit, cutoff_hour, now=None)
        -> (max_value | None, first_minute_reaching_it | None)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from weather.model.feature_store import plausible_native_temperature, row_temp_native

METAR_OBSERVATION_GROUP_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")


def _minute_of_day(value):
    if not value:
        return None
    try:
        text = str(value)
        if "T" in text:
            text = text.split("T")[1]
        hour, minute = text.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError, IndexError):
        return None


def metar_observation_local_time(row, tz, raw_obs_times=None):
    """Local observation instant of a METAR row (``obsTime``, else the raw DDHHMMZ group), or None."""
    raw = row.get("raw")
    if not raw:
        return None
    obs_epoch = (raw_obs_times or {}).get(str(raw))
    if obs_epoch is not None:
        try:
            return datetime.fromtimestamp(float(obs_epoch), timezone.utc).astimezone(tz)
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    match = METAR_OBSERVATION_GROUP_RE.search(str(raw))
    report = row.get("report_time") or row.get("datetime")
    if not match or not report:
        return None
    try:
        report_dt = datetime.fromisoformat(str(report).replace("Z", "+00:00"))
    except ValueError:
        return None
    if report_dt.tzinfo is None:
        return None
    report_utc = report_dt.astimezone(timezone.utc)
    day, hour, minute = (int(part) for part in match.groups())
    for offset in (0, -1, -2, 1):
        candidate = report_utc + timedelta(days=offset)
        if candidate.day == day:
            return candidate.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(tz)
    return None


def row_obs_time_local(row, tz):
    value = row.get("obs_time")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(tz) if parsed.tzinfo is not None else None


def observed_target_date_rows(station, metar, *, target_date, tz, unit, now=None):
    """``[(minute_of_day, value)]`` observed on ``target_date`` (<= ``now``), sorted by minute.

    Row sets as in ``lockin_observed_rows``: the METAR rows, plus the station rows when the station
    surface is not METAR-sourced or the METAR rows are empty.
    """
    raw_obs_times = {}
    for item in (metar or {}).get("raw_payload") or []:
        if isinstance(item, dict) and item.get("rawOb") and item.get("obsTime") is not None:
            raw_obs_times[str(item["rawOb"])] = item["obsTime"]
    row_sets = [(metar or {}).get("rows") or []]
    station = station or {}
    station_source = station.get("station_observation_source") or station.get("source")
    if station_source not in (None, "metar") or not row_sets[0]:
        row_sets.append(station.get("rows") or [])
    now_minute = now.hour * 60 + now.minute if now is not None else None
    now_local = now.astimezone(tz) if now is not None and now.tzinfo else None
    out = []
    for rows in row_sets:
        for row in rows:
            value = row_temp_native(row)
            if value is None or not plausible_native_temperature(value, unit):
                continue
            observed = metar_observation_local_time(row, tz, raw_obs_times)
            if observed is None:
                observed = row_obs_time_local(row, tz)
            if observed is not None:
                if target_date is not None and observed.date() != target_date:
                    continue
                if now_local is not None and observed > now_local:
                    continue
                minute = observed.hour * 60 + observed.minute
            else:
                minute = _minute_of_day(row.get("local_time") or row.get("time"))
                if minute is None or (now_minute is not None and minute > now_minute):
                    continue
            out.append((minute, value))
    out.sort(key=lambda item: item[0])
    return out


def running_max_since_midnight(station, metar, *, target_date, tz, unit, cutoff_hour, now=None):
    """The trainer's ``high_so_far`` at ``cutoff_hour`` on captured rows: ``(max, first_minute)``.

    ``station`` / ``metar`` are the captured source ``data`` dicts (``rows``, optional
    ``raw_payload``); ``tz`` the market's zoneinfo; ``unit`` its native unit ("F" or "C").
    Returns ``(None, None)`` when no target-date row is observed by the cutoff.
    """
    cutoff_minute = int(cutoff_hour) * 60
    kept = [(m, v) for m, v in observed_target_date_rows(
        station, metar, target_date=target_date, tz=tz, unit=unit, now=now) if m <= cutoff_minute]
    if not kept:
        return None, None
    high = max(v for _, v in kept)
    return high, min(m for m, v in kept if v == high)
