"""R-ODC serve-side low_so_far and dewpoint_c from captured METAR (pure, unbound; never served by itself).

The ONE implementation meant for both the forward dev frame and any later serve of the R-ODC columns
(low_so_far, dewpoint_c), built to the L8 pins (2026-10-29):

1. Source: the captured ``sources.metar.data`` dict only (``rows``, optional ``raw_payload``). No WU-current,
   station or any other fallback.
2. Instant: ``observed_running_max.metar_observation_local_time`` (AWC ``obsTime``, else the raw ``DDHHMMZ``
   group, never AWC's nominal hour), else the row's own ``obs_time``. A row with no dated instant is skipped
   (counted), never placed by its wall-clock time. Kept iff local date == D, instant <= h:00 and instant <= the
   snapshot's capture time ``now``.
3. Snapshot: ``choose_snapshot`` applies the state's late-report rule (``last_in_hour`` or ``receipt_by``) or
   ``as_of_capture``, as ``mg2_p3d_n.scan_replay`` / ``as_of_capture``.
4. low_so_far = wu_whole_f(min plausible temp_native, half_up); dewpoint_c = wu_whole_f(dewpoint_native of the
   latest kept row, half_up), ties last in row order. ``mg_serve_core.wu_whole_f`` is the serve T-group conversion.
   Native unit (whole degrees F for every built-in R-ODC market); the legacy name dewpoint_c is not Celsius.
5. Missing: dewpoint_c is None when the latest kept row has none (no earlier-row fallback, as in training);
   no kept row -> both None with ``reason`` "no_metar_row" (the caller refuses or falls back, like high_so_far).
6. Refusals (``check_bounds``): low_so_far non-increasing over the cutoff hours; low <= current temperature;
   low <= high_so_far.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta

from weather.model.feature_store import plausible_native_temperature, row_dewpoint_native, row_temp_native
from weather.model.mg_serve_core import wu_whole_f
from weather.model.observed_running_max import metar_observation_local_time, row_obs_time_local

SNAPSHOT_RULES = ("last_in_hour", "receipt_by", "as_of_capture")
TOL = 1e-9


class OdcMetarRefused(RuntimeError):
    pass


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def kept_rows(metar, *, target_date, tz, unit, cutoff_hour, now):
    """[(instant, row_index, temp | None, dewpoint | None)] of the METAR rows observed on ``target_date`` at or
    before ``cutoff_hour``:00 and at or before ``now``, sorted by instant then row order; plus skip counts."""
    if now is None or now.tzinfo is None:
        raise OdcMetarRefused("the capture time 'now' must be timezone-aware")
    metar = metar or {}
    raw_obs_times = {}
    for item in metar.get("raw_payload") or []:
        if isinstance(item, dict) and item.get("rawOb") and item.get("obsTime") is not None:
            raw_obs_times[str(item["rawOb"])] = item["obsTime"]
    cutoff = datetime.combine(target_date, time(int(cutoff_hour), 0), tzinfo=tz)
    now_local = now.astimezone(tz)
    out, skipped = [], {"undated": 0, "other_date": 0, "after_cutoff": 0, "after_capture": 0}
    for i, row in enumerate(metar.get("rows") or []):
        observed = metar_observation_local_time(row, tz, raw_obs_times) or row_obs_time_local(row, tz)
        if observed is None:
            skipped["undated"] += 1
            continue
        if observed.date() != target_date:
            skipped["other_date"] += 1
            continue
        if observed > cutoff:
            skipped["after_cutoff"] += 1
            continue
        if observed > now_local:
            skipped["after_capture"] += 1
            continue
        temp = _number(row_temp_native(row))
        if temp is not None and not plausible_native_temperature(temp, unit):
            temp = None
        out.append((observed, i, temp, _number(row_dewpoint_native(row))))
    out.sort(key=lambda r: (r[0], r[1]))
    return out, skipped


def odc_features(metar, *, target_date, tz, unit, cutoff_hour, now):
    """{"low_so_far", "dewpoint_c", "n_rows", "last_instant", "reason", "skipped"} for one snapshot."""
    rows, skipped = kept_rows(metar, target_date=target_date, tz=tz, unit=unit, cutoff_hour=cutoff_hour, now=now)
    temps = [r[2] for r in rows if r[2] is not None]
    if not rows or not temps:
        return {"low_so_far": None, "dewpoint_c": None, "n_rows": len(rows), "last_instant": None,
                "reason": "no_metar_row", "skipped": skipped}
    low = wu_whole_f(min(temps), "half_up")
    dew = wu_whole_f(rows[-1][3], "half_up") if rows[-1][3] is not None else None
    return {"low_so_far": low, "dewpoint_c": dew, "n_rows": len(rows), "last_instant": rows[-1][0].isoformat(),
            "reason": None, "skipped": skipped}


def choose_snapshot(captures, *, target_date, tz, cutoff_hour, rule, grace_minutes=0, at_local=None):
    """Index into ``captures`` (capture local datetimes, file order) of the snapshot used for ``cutoff_hour``.

    ``last_in_hour``: the last capture in file order in [h:00, h+1:00) on D; ``receipt_by``: the latest capture at
    or before h:00 + grace; ``as_of_capture``: the latest capture at or before ``at_local`` (ties: the later in
    file order). As ``mg2_p3d_n.scan_replay`` / ``as_of_capture`` on the replay index.
    None when no capture qualifies.
    """
    if rule not in SNAPSHOT_RULES:
        raise OdcMetarRefused(f"unknown snapshot rule {rule!r}")
    h = int(cutoff_hour)
    best = None
    for i, captured in enumerate(captures):
        local = captured.astimezone(tz)
        if local.date() != target_date:
            continue
        if rule == "last_in_hour":
            ok = local.hour == h
        elif rule == "receipt_by":
            ok = local <= datetime.combine(target_date, time(h, 0), tzinfo=tz) + timedelta(minutes=int(grace_minutes))
        else:
            if at_local is None or at_local.tzinfo is None:
                raise OdcMetarRefused("as_of_capture needs a timezone-aware at_local")
            ok = local <= at_local
        if ok and (best is None or rule == "last_in_hour" or local >= captures[best].astimezone(tz)):
            best = i
    return best


def check_bounds(by_hour):
    """Refuse (rule 6) unless, over ``{hour: {"low_so_far", "high_so_far", "current_temp"}}``, low_so_far is
    non-increasing in hour and never above that hour's high_so_far or current temperature. -> hours checked."""
    bad, previous = [], None
    for hour in sorted(by_hour):
        rec = by_hour[hour]
        low = _number(rec.get("low_so_far"))
        if low is None:
            continue
        if previous is not None and low > previous + TOL:
            bad.append((hour, "running_min", low, previous))
        for name in ("high_so_far", "current_temp"):
            other = _number(rec.get(name))
            if other is not None and low > other + TOL:
                bad.append((hour, name, low, other))
        previous = low
    if bad:
        raise OdcMetarRefused(f"{len(bad)} bound violations, e.g. {bad[:3]}")
    return len(by_hour)
