"""MG serve core: the pure serve-time functions MG-2 and MG-3 share, importable on the capture host.

Prerequisite b.0 of L2's MG-3 design (master, 2026-10-26). The research modules these functions come
from refuse to import on the dedicated capture host by design, and further serve parts sit behind those
modules' guards. This module holds one implementation of each serve function, so that a host serve path
never needs a research import.

This module names no research module, not even in text, which keeps the repository's text-based
no-importer ratchets exact (L8 ratchet fix, 2026-10-27). Each moved function's source is named where it is
pinned: by the parity tests below and by ``KNOWN_COPIES`` in ``tests/operations/test_mg_serve_core_host_import.py``.

Stage A (this file) is new code only. The research modules are NOT rewired yet. Until MG-2/B's forward
window closes (master ruling D1, 2026-10-26), each moved function is pinned equal to its source by:

* exact-equality tests (C1, ``tests/model/test_mg_serve_core_parity.py``);
* frozen-state tests (C2, ``tests/model/test_mg_serve_core_state_parity.py``).

The bodies are copies of those sources. The only differences are:

* the exception class (:class:`ServeCoreError`);
* explicit parameters where a source read a research-module constant (``floor_fields``, ``switch_hour``).

Import contract (pinned by ``tests/operations/test_mg_serve_core_host_import.py``):

* allowed: stdlib, numpy, scipy, pandas, ``weather.units``, ``weather.paths``;
* never: any research (calibration or reporting) module, and nothing with a host guard.

The frozen L6 own-model state (master ruling D2 (i)) is served by :func:`load_l6_own_state` and
:func:`l6_own_nowcast`. It is fitted once by the offline L6 own-state fitter and is sha-bound; no serve
path refits it, and it is not part of MG-2's binding.

There is no CLI, and nothing here writes a file.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import CONFIG_ROOT


class ServeCoreError(ValueError):
    """A serve-core input violates the contract (the research callers re-raise their own types)."""


# ----------------------------------------------------------------------------- constants (prm, l3)

R0_MARKETS = (
    "atlanta", "austin", "chicago", "dallas", "denver", "houston",
    "los-angeles", "miami", "nyc", "san-francisco", "seattle",
)
AUG_SEP_CENTRES = ("2026-08-08", "2026-08-23", "2026-09-07", "2026-09-22")
FLOOR_MIX_CLIM = 0.02
KERNEL_BANDWIDTH = 0.25
MIN_SCALE = 0.5
WU_ROUNDING_CANDIDATES = ("half_up", "half_even", "half_down", "floor", "ceil")

L6_MARKET_LAT_MIN = 10
L6_MAX_AGE_MIN = 90
_COVER = {"CLR": 0.0, "SKC": 0.0, "NCD": 0.0, "NSC": 0.0, "FEW": .25, "SCT": .5, "BKN": .75, "OVC": 1.0, "VV": 1.0}

SWITCH_HOUR = 13  # the MG-2 rule's switch hour (fixed)
POST = "p3d_n"  # MG-2's post-switch half
EPS = 1e-4  # the pre-registered log pool's epsilon
V2_LOOKBACK = timedelta(hours=24)  # the v2 NBM bulletin lookback

_CAPTURED_LOCAL = None
_METAR_TIME = None


# ----------------------------------------------------------------------------- captured METAR (l3)

def metar_observation_instant(row, tz):
    """Observation instant of a captured METAR row: the raw DDHHMMZ group, else ``datetime``.

    The v3 parser's ``datetime`` is AWC's nominal report hour (a :52 report reads as the
    next hour), so the raw group is preferred (AGENT_CONTEXT, metar-parser-v4 semantics).
    """
    import re

    global _METAR_TIME
    if _METAR_TIME is None:
        _METAR_TIME = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")
    nominal = row.get("datetime")
    nominal_dt = datetime.fromisoformat(nominal) if nominal else None
    match = _METAR_TIME.search(str(row.get("raw") or ""))
    if match and nominal_dt is not None:
        day, hour, minute = (int(g) for g in match.groups())
        anchor = nominal_dt.astimezone(timezone.utc)
        best = None
        for shift in (-1, 0, 1):  # the DD group may sit in the previous or next UTC month day
            base = (anchor + timedelta(days=shift)).replace(hour=0, minute=0, second=0, microsecond=0)
            if base.day != day:
                continue
            cand = base.replace(hour=hour, minute=minute)
            if best is None or abs(cand - anchor) < abs(best - anchor):
                best = cand
        if best is not None and abs(best - anchor) <= timedelta(hours=3):
            return best.astimezone(tz), "raw_ddhhmmz"
    if nominal_dt is not None:
        return nominal_dt.astimezone(tz), "nominal_datetime"
    return None, "missing"


def observations_at_cutoff(rows, target_date, cutoff_hour, tz):
    """(current_temp, high_so_far, n) from METAR rows of ``target_date`` observed at or before h:00.

    Same semantics as the trainer's ``build_historical_feature_record``: rows of the local
    target date with observation minute <= cutoff_hour * 60; current = the latest such row.
    """
    from datetime import time

    cutoff = datetime.combine(target_date, time(int(cutoff_hour), 0), tzinfo=tz)
    kept = {}
    for row in rows or []:
        temp = row.get("temp_native")
        if temp is None:
            continue
        instant, _ = metar_observation_instant(row, tz)
        if instant is None or instant.date() != target_date or instant > cutoff:
            continue
        kept[instant] = float(temp)  # one value per observation instant (corrections overwrite)
    if not kept:
        return None, None, 0
    latest = max(kept)
    return kept[latest], max(kept.values()), len(kept)


def event_folders(replay_root):
    """(slug, target date, folder) for each replay event folder."""
    import re

    pattern = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d+)-(\d{4})$")
    months = {m: i for i, m in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september",
         "october", "november", "december"), start=1)}
    for folder in sorted(Path(replay_root, "snapshots").iterdir()):
        match = pattern.match(folder.name)
        if not match:
            continue
        slug, month, day, year = match.groups()
        yield slug, date(int(year), months[month], int(day)), folder


def parse_captured_metar(raw, anchor_utc):
    """One captured METAR row -> the fields lane L6's IEM extract carries (None when unparseable).

    Observation instant from the raw DDHHMMZ group (nearest to ``anchor_utc``); temperature and dewpoint from the
    T-group when present, else the body (IEM ``dwpf`` follows the T-group; pick rule clarification 2 erratum); wind,
    cover and ceiling as ``iem_upstream`` (cover = max layer, ceiling = lowest BKN/OVC/VV base).
    """
    import re

    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", raw or "")
    if not m:
        return None
    day, hh, mm = (int(g) for g in m.groups())
    valid = None
    for shift in (-1, 0, 1):
        base = (anchor_utc + timedelta(days=shift)).replace(hour=0, minute=0, second=0, microsecond=0)
        if base.day == day:
            cand = base.replace(hour=hh, minute=mm)
            if valid is None or abs(cand - anchor_utc) < abs(valid - anchor_utc):
                valid = cand
    if valid is None:
        return None

    def c2f(c):
        return c * 9.0 / 5.0 + 32.0

    body = re.search(r"\s(M?\d{2})/(M?\d{2})?(?=\s)", raw)
    tg = re.search(r"\bT([01])(\d{3})([01])(\d{3})\b", raw)
    temp = dwpf = None
    if body:
        temp = c2f(int(body.group(1).replace("M", "-")))
        dwpf = c2f(int(body.group(2).replace("M", "-"))) if body.group(2) else None
    if tg:
        temp = c2f((-1 if tg.group(1) == "1" else 1) * int(tg.group(2)) / 10.0)
        dwpf = c2f((-1 if tg.group(3) == "1" else 1) * int(tg.group(4)) / 10.0)
    w = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G\d{2,3})?KT\b", raw)
    drct = sknt = None
    if w:
        drct = None if w.group(1) == "VRB" else float(w.group(1))
        sknt = float(w.group(2))
    covers, ceiling = [], None
    for k in re.finditer(r"\b(FEW|SCT|BKN|OVC|VV)(\d{3})|\b(CLR|SKC|NCD|NSC)\b", raw):
        if k.group(3):
            covers.append(0.0)
            continue
        covers.append(_COVER[k.group(1)])
        if k.group(1) in ("BKN", "OVC", "VV") and ceiling is None:
            ceiling = int(k.group(2)) * 100.0
    return {"valid": valid, "temp": temp, "dwpf": dwpf, "drct": drct, "sknt": sknt,
            "cover": max(covers) if covers else None, "ceiling_ft": ceiling,
            "is_cor": " COR " in f" {raw} "}


def json_value_after(line, key, start=0):
    """Decode the JSON value that follows ``"key":`` at or after ``start`` (``l3._json_value_after``)."""
    at = line.find(f'"{key}":', start)
    if at < 0:
        return None, -1
    pos = at + len(key) + 3
    while line[pos] == " ":
        pos += 1
    value, end = json.JSONDecoder().raw_decode(line, pos)
    return value, end


def captured_rows(line, station):
    """The captured ``sources.metar.data.rows`` of one replay line (``l3._captured_rows``)."""
    start = line.find('"sources":')
    if start < 0:
        return []
    metar_at = line.find('"metar":', start)
    if metar_at < 0:
        return []
    section, _ = json_value_after(line, "metar", start)
    rows = ((section or {}).get("data") or {}).get("rows") or []
    return [r for r in rows if str(r.get("station_id") or station) == station]


def l6_captured_features(snapshot_rows, captured, tz, station_code, prev_dmax):
    """L6 OWN features at each snapshot from that snapshot's own captured METAR rows (L6's semantics).
    """
    import numpy as np
    import pandas as pd

    lag = timedelta(minutes=L6_MARKET_LAT_MIN)
    out = []
    for key, cap_utc, local_date in snapshot_rows:
        rows = [r for r in captured.get(key, []) if not r["is_cor"] and r["temp"] is not None]
        usable = sorted((r for r in rows if r["valid"] + lag <= cap_utc), key=lambda r: r["valid"])

        def asof(t):
            cand = [r for r in usable if r["valid"] + lag <= t]
            if not cand or (t - cand[-1]["valid"]) > timedelta(minutes=L6_MAX_AGE_MIN):
                return None
            return cand[-1]

        now, ago = asof(cap_utc), asof(cap_utc - timedelta(hours=3))
        same_day = [r["temp"] for r in usable if r["valid"].astimezone(tz).date().isoformat() == local_date]
        loc = cap_utc.astimezone(tz)
        nan = float("nan")
        t = now["temp"] if now else nan
        td = now["dwpf"] if now and now["dwpf"] is not None else nan
        r_ = float(np.fmax(max(same_day) if same_day else nan, t))
        drct = now["drct"] if now and now["drct"] is not None else nan
        sknt = now["sknt"] if now and now["sknt"] is not None else nan
        calm = sknt == 0
        u = 0.0 if calm else -sknt * math.sin(math.radians(drct))
        v = 0.0 if calm else -sknt * math.cos(math.radians(drct))
        cover = now["cover"] if now and now["cover"] is not None else nan
        ceil = now["ceiling_ft"] if now else None
        log_ceiling = (math.log10(max(ceil, 100.0)) if ceil is not None
                       else (math.log10(30000.0) if math.isfinite(cover) else nan))
        prev = prev_dmax.get(local_date, nan)
        out.append({"row_key": key, "hour_f": loc.hour + loc.minute / 60.0, "doy": loc.timetuple().tm_yday,
                    "station_code": station_code, "t": t, "td": td, "r": r_, "t_minus_r": t - r_,
                    "tend3": (t - ago["temp"]) if ago else nan,
                    "td_tend3": (td - ago["dwpf"]) if ago and ago["dwpf"] is not None else nan,
                    "u": u, "v": v, "spd": sknt, "cover": cover, "log_ceiling": log_ceiling,
                    "prev_dmax": prev, "prev_minus_t": prev - t})
    return pd.DataFrame(out)


def routine_dmax(rows, tz, local_date, min_routine=20):
    """Half-up max of a day's routine (modal-minute), non-COR rows; None below ``min_routine`` rows.
    """
    day = [r for r in rows if not r["is_cor"] and r["temp"] is not None
           and r["valid"].astimezone(tz).date().isoformat() == local_date]
    if not day:
        return None
    modal = Counter(r["valid"].minute for r in day).most_common(1)[0][0]
    routine = [r["temp"] for r in day if r["valid"].minute == modal]
    if len(routine) < min_routine:
        return None
    return float(math.floor(max(routine) + 0.5))


# ----------------------------------------------------------------------------- frozen L6 own model (master D2 (i))

L6_OWN_COLUMNS = ("hour_f", "doy", "station_code", "t", "td", "r", "t_minus_r", "tend3", "td_tend3", "u", "v",
                  "spd", "cover", "log_ceiling", "prev_dmax", "prev_minus_t")  # the L6 OWN columns
L6_STATE_SCHEMA = "l6_own_state/1"


def load_l6_own_state(path, expected_sha256):
    """The frozen L6 own-model state, unpickled only after its file sha256 equals ``expected_sha256``.

    The state is fitted once by the offline L6 own-state fitter. No serve path refits it.
    """
    import hashlib
    import pickle

    blob = Path(path).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != expected_sha256:
        raise ServeCoreError(f"L6 own state {path}: sha256 {digest} != bound {expected_sha256}")
    state = pickle.loads(blob)
    if state.get("schema") != L6_STATE_SCHEMA or tuple(state.get("columns") or ()) != L6_OWN_COLUMNS:
        raise ServeCoreError(f"L6 own state {path}: schema or columns do not match {L6_STATE_SCHEMA}")
    return state


def l6_own_nowcast(state, features):
    """L6 ``n_own`` = r + the frozen model's prediction on the OWN columns of ``features`` (a DataFrame)."""
    import numpy as np

    X = features[list(L6_OWN_COLUMNS)].to_numpy(float)
    return features["r"].to_numpy(float) + np.asarray(state["model"].predict(X), float)


# ----------------------------------------------------------------------------- v2 NBM selection

def parse_time(value):
    """An aware UTC datetime from an ISO string, else None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def iso(value):
    return value.isoformat() if value else None


def finite(value):
    """A finite float, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def cycle_time(cycle_key):
    """The UTC issue time of an NBM ``source:YYYYMMDDTHHZ`` cycle key, else None."""
    try:
        return datetime.strptime(str(cycle_key).split(":", 1)[1], "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    except (IndexError, ValueError):
        return None


def availability(row):
    """(first availability instant, basis field) of a payload manifest row."""
    for field in ("response_received_at", "fetched_at", "first_seen_at", "captured_at_utc"):
        value = parse_time(row.get(field))
        if value is not None:
            return value, field
    return None, None


def select_v2(bulletins, parsed, station, target, captured, lookback=V2_LOOKBACK):
    """Newest bulletin available at capture holding today's maximum.

    ``bulletins``: {digest: {"issue", "available_at", "available_basis", "cycle_key", "status"}};
    ``parsed``: {(digest, station, target): parser result}.
    """
    candidates, skipped = [], Counter()
    for digest, entry in bulletins.items():
        issue = entry["issue"]
        if issue is None or issue > captured or captured - issue > lookback:
            continue
        if entry["available_at"] is None or entry["available_at"] > captured:
            skipped["after_capture"] += 1
            continue
        if entry.get("status") != "parsed":
            skipped[entry.get("status") or "unparsed"] += 1
            continue
        result = parsed.get((digest, station, target))
        if result is None:
            continue
        issued = parse_time(result.get("issued_at")) or issue
        if issued > captured:
            skipped["issued_after_capture"] += 1
            continue
        candidates.append((issued, entry["available_at"], digest, entry, result))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    out = {"v2_candidates": len(candidates), "v2_skipped": dict(skipped),
           "v2_newest_cycle_key": candidates[0][3]["cycle_key"] if candidates else None,
           "v2_newest_reason": (candidates[0][4].get("reason") if candidates and not candidates[0][4].get("available")
                                else None)}
    for issued, seen, digest, entry, result in candidates:
        if result.get("available"):
            pct = result.get("percentiles") or {}
            valid = parse_time(result.get("valid_time_utc"))
            return {**out, "v2_status": "available", "v2_reason": None,
                    "v2_cycle_key": entry["cycle_key"], "v2_payload_hash": digest,
                    "v2_issued_at": iso(issued), "v2_valid_time_utc": iso(valid),
                    "v2_available_at": iso(seen), "v2_available_basis": entry["available_basis"],
                    "v2_age_hours": round((captured - issued).total_seconds() / 3600, 4),
                    "v2_forecast_hour": result.get("forecast_hour"),
                    "v2_period_kind": result.get("period_kind"),
                    **{f"v2_p{p}": finite(pct.get(str(p))) for p in (10, 25, 50, 75, 90)},
                    "v2_mean": finite(result.get("mean_native")),
                    "v2_stddev": finite(result.get("stddev_native"))}
    reason = out["v2_newest_reason"] or ("no_bulletin_available_at_capture" if not candidates else "unavailable")
    return {**out, "v2_status": "unavailable", "v2_reason": reason}


def usable_v2_mean(snaps):
    """v2_mean where mean and stddev are finite and available at or before capture, else NaN.
    """
    import numpy as np
    import pandas as pd

    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, errors="coerce")
    mu = pd.to_numeric(snaps.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(snaps.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(mu) & np.isfinite(sd) & (avail <= cap).fillna(False).to_numpy()
    return np.where(ok, mu, np.nan)


# ----------------------------------------------------------------------------- P3d_N arm (prm)

def season_of(centre):
    month = str(centre)[5:7]
    if month in ("08", "09"):
        return "aug_sep"
    return "oct_dec" if month in ("10", "11", "12") else "jan_jul"


def station_coordinates(markets=R0_MARKETS, path=None):
    """{market: (lat, lon, elevation_m)} from ``config/locations.json`` (``prm.station_coordinates``)."""
    payload = json.loads(Path(path or CONFIG_ROOT / "locations.json").read_text(encoding="utf-8"))
    by_id = {row.get("id"): row for row in payload.get("locations", [])}
    out = {}
    for market in markets:
        coords = (by_id.get(market) or {}).get("coordinates") or {}
        if not all(key in coords for key in ("lat", "lon", "elevation_m")):
            raise ServeCoreError(f"no station coordinates for {market}")
        out[market] = (float(coords["lat"]), float(coords["lon"]), float(coords["elevation_m"]))
    return out


def nearest_centre(target_date, centres=AUG_SEP_CENTRES):
    """The centre whose month-day is closest to ``target_date``'s (``prm.nearest_centre``)."""
    d = date.fromisoformat(str(target_date)[:10])
    ref = date(2001, d.month, d.day)
    return min(centres, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days))


def smoothed_dist(buckets, support, alpha=0.10):
    """``feature_model.smoothed_dist`` (pinned equal by C1; the training module is not edited)."""
    counts = Counter(int(b) for b in buckets)
    denominator = len(buckets) + alpha * len(support)
    return {
        s: (counts.get(s, 0) + alpha) / denominator
        for s in support
    }


def predictive_distribution(yhat, s, floor, z, bucket_space, p_clim):
    """Kernel-smoothed standardised errors, floor-censored, 2% climatology mix (``prm.predictive_distribution``)."""
    import numpy as np
    from scipy.special import ndtr

    lo = math.floor(yhat + s * (float(np.min(z)) - 1.5))
    hi = math.ceil(yhat + s * (float(np.max(z)) + 1.5))
    ks = np.arange(lo, hi + 1)
    edges = np.append(ks - 0.5, hi + 0.5)
    t = (edges - yhat) / s
    cdf = ndtr((t[:, None] - z[None, :]) / KERNEL_BANDWIDTH).mean(axis=1)
    mass = np.diff(cdf)
    mass = mass / mass.sum()
    dist = {int(k): float(m) for k, m in zip(ks, mass)}
    if floor is not None and math.isfinite(floor):
        from weather.units import round_half_up

        fb = int(round_half_up(floor))
        below = sum(v for k, v in dist.items() if k < fb)
        dist = {k: v for k, v in dist.items() if k >= fb}
        dist[fb] = dist.get(fb, 0.0) + below
    out = {k: (1.0 - FLOOR_MIX_CLIM) * v for k, v in dist.items()}
    for k, v in p_clim.items():
        out[int(k)] = out.get(int(k), 0.0) + FLOOR_MIX_CLIM * float(v)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def exact_tgroup_f(value_f):
    """The exact Fahrenheit value of a T-group reading given as a float in degrees F (``prm.exact_tgroup_f``).

    The T-group carries tenths of a degree C; 32 + 9 * tenths / 50 is recovered without float error.
    """
    from fractions import Fraction

    tenths = round((float(value_f) - 32.0) * 50.0 / 9.0)
    return Fraction(32) + Fraction(9 * tenths, 50)


def round_candidate(exact, rule):
    """Whole degrees from an exact Fraction under one rounding rule (``prm.round_candidate``)."""
    lo = math.floor(exact)
    frac = exact - lo
    if rule == "floor":
        return int(lo)
    if rule == "ceil":
        return int(math.ceil(exact))
    if frac * 2 != 1:
        return int(lo + (1 if frac * 2 > 1 else 0))
    if rule == "half_up":
        return int(lo + 1)
    if rule == "half_down":
        return int(lo)
    if rule == "half_even":
        return int(lo if lo % 2 == 0 else lo + 1)
    raise ServeCoreError(f"unknown rounding rule {rule}")


def wu_whole_f(value_f, rule="half_up"):
    """Serve-time conversion of a METAR T-group Fahrenheit value to WU's whole degrees (``prm.wu_whole_f``)."""
    if value_f is None:
        return None
    try:
        if not math.isfinite(float(value_f)):
            return None
    except (TypeError, ValueError):
        return None
    return float(round_candidate(exact_tgroup_f(value_f), rule))


def state_features(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean):
    """Serve math from the frozen state only: (X row, mu0, g, F) (``prm.state_features``)."""
    import numpy as np

    mean = state["hours"][int(hour)]["mean"]
    centre = min(state["centres"], key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10]))
                                                      - date(2001, target_date.month, target_date.day)).days))
    season = state["season_of"][centre[5:7]]
    bias = mean["bias"].get((market, season), mean["bias_global"])
    normal = mean["normal"].get((market, centre), mean["normal_by_market"].get(market, mean["normal_global"]))
    if state["conversion"]["enabled"]:
        high_so_far = wu_whole_f(high_so_far, state["conversion"]["rule_id"].split(":")[-1])
        current_temp = wu_whole_f(current_temp, state["conversion"]["rule_id"].split(":")[-1])
    mu0 = nbm_mean + bias if nbm_mean is not None and math.isfinite(nbm_mean) else normal
    g = high_so_far - mu0
    lat, lon, elev = state["coords"][market]
    doy = target_date.timetuple().tm_yday
    levels = {"high_so_far": high_so_far, "current_temp": current_temp}
    cols = [levels[name] - mu0 for name in state["constants"]["levels"]]
    cols += [g, max(g, 0.0), mu0 - normal, lat, lon, elev, normal, bias]
    if mean["doy"]:
        cols += [math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25)]
    return np.asarray([cols], dtype=float), mu0, g, high_so_far


def state_distribution(state, hour, **inputs):
    """P3d_N's integer-bucket distribution from the frozen state (``prm.state_distribution``)."""
    import numpy as np

    X, mu0, g, floor = state_features(state, hour, **inputs)
    entry = state["hours"][int(hour)]
    mean = entry["mean"]
    design = np.array([[1.0, g, max(g, 0.0)]])
    yhat = float((mu0 + design @ mean["ols"] + mean["hgb"].predict(X))[0])
    c = state["constants"]
    s = max(c["min_scale"], float(entry["scale"].predict(np.column_stack([X, [yhat - floor]]))[0]) * math.sqrt(math.pi / 2))
    market = inputs["market"]
    p_clim = smoothed_dist(entry["train_y"][market], state["buckets"][market], alpha=c["clim_alpha"])
    return predictive_distribution(yhat, s, floor, entry["z"], state["buckets"][market], p_clim)


# ----------------------------------------------------------------------------- bands, floor, MG-1 fallback

def mg1_band_probs(kind, low, high, B, mu, sig):
    """MG-1 ``r-t5-inc-c1`` band probabilities (``free_source_candidates.mg1.band_probs``, verbatim)."""
    import numpy as np
    from scipy.special import ndtr

    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, ndtr((up - mu) / sig) - ndtr((lo - mu) / sig), 0.0)
    return np.clip(p, 0.0, None)


def mg1_band_frame(snaps, bands, band_snap, floor_fields):
    """MG-1 on flat bands: the scorecard's MG-1 frame without the scorecard Table.

    ``bands`` are the Table's bands; ``band_snap`` maps each band to its row in ``snaps``. ``floor_fields`` is the
    scorecard's ``FLOOR_FIELDS``, used when ``snaps`` has no ``floor`` column.
    """
    import numpy as np
    import pandas as pd

    s = snaps
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce")
    mu = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = (np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & cap.notna().to_numpy()
          & (avail <= cap).fillna(False).to_numpy())
    if "floor" in s.columns:
        floor = pd.to_numeric(s["floor"], errors="coerce").to_numpy(float)
    else:
        floor = s[list(floor_fields)].apply(pd.to_numeric, errors="coerce").max(axis=1).to_numpy(float)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    sel = ok[band_snap]
    b = bands[sel]
    snap = band_snap[sel]
    p = mg1_band_probs(b.kind.to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float), B[snap], mu[snap],
                       np.maximum(sd[snap], 1.0))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int), "p": p})


def floor_B(snaps, floor_fields):
    """B = floor(F + 0.5) with F the rule-4 floor, the max of ``floor_fields``."""
    import numpy as np
    import pandas as pd

    F = snaps[list(floor_fields)].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    F = F.to_numpy(float)
    return np.where(np.isfinite(F), np.floor(F + 0.5), -np.inf)


def distribution_band_frame(dists, bands):
    """{row_key: {bucket: p}} onto bands."""
    import numpy as np
    import pandas as pd

    b = bands[bands.row_key.isin(set(dists))]
    probs = []
    for rk, kind, low, high in zip(b.row_key, b.kind, b.low, b.high):
        d = dists[rk]
        if kind == "lte":
            probs.append(sum(p for k, p in d.items() if k <= high))
        elif kind == "gte":
            probs.append(sum(p for k, p in d.items() if k >= low))
        else:
            probs.append(sum(p for k, p in d.items() if low <= k <= high))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                         "p": np.asarray(probs, float)})


def compose(snaps, bands, pre, post, mg1, floor_fields, switch_hour=SWITCH_HOUR, post_label=POST):
    """Per snapshot: ``pre`` before ``switch_hour``, ``post`` from it; MG-1 where the half has nothing usable.

    A ``post`` row is usable only when it puts mass on a band the rule-4 floor allows. Returns (frame, source per
    row_key).
    """
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    hour = dict(zip(s.row_key, s.local_hour.astype(int)))
    B = dict(zip(s.row_key, floor_B(s, floor_fields)))
    kind = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.kind))
    high = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.high.astype(float)))

    def usable(frame):
        if frame.empty:
            return set()
        ok = [(kind[(r, i)] == "gte") or (high[(r, i)] >= B[r]) for r, i in zip(frame.row_key, frame.band_index)]
        mass = frame.p.to_numpy(float) * np.asarray(ok, bool)
        tot = pd.Series(mass).groupby(frame.row_key.to_numpy()).sum()
        return set(tot.index[tot.to_numpy() > 0])

    pre_keys = {k for k in set(pre.row_key) if hour.get(k, 99) < switch_hour}
    post_keys = {k for k in usable(post) if hour.get(k, -1) >= switch_hour}
    mg1_keys = set(mg1.row_key) - pre_keys - post_keys
    parts = [pre[pre.row_key.isin(pre_keys)], post[post.row_key.isin(post_keys)], mg1[mg1.row_key.isin(mg1_keys)]]
    frame = pd.concat(parts, ignore_index=True)
    source = {}
    for k in s.row_key:
        source[k] = ("pre" if k in pre_keys else post_label if k in post_keys else "mg1" if k in mg1_keys
                     else "none")
    return frame.sort_values(["row_key", "band_index"]).reset_index(drop=True), source


# ----------------------------------------------------------------------------- blend

def pool(m, c, w_band, impossible, band_snap, n_snaps, eps=EPS, force_floor=False):
    """The pre-registered log pool on flat band arrays; ``w_band`` is w per band.

    ``force_floor`` gives the floor-only control (the w -> 0+ limit: market, hard floor, same mass).
    """
    import numpy as np

    m = np.asarray(m, float)
    w_band = np.broadcast_to(np.asarray(w_band, float), m.shape)
    if (w_band < 0).any():
        raise ServeCoreError("refused: w must be >= 0")
    g = np.maximum(m, eps) ** (1.0 - w_band) * np.maximum(np.asarray(c, float), eps) ** w_band
    g = np.where(impossible & ((w_band > 0) | force_floor), 0.0, g)
    s_m = np.bincount(band_snap, weights=m, minlength=n_snaps)
    s_g = np.bincount(band_snap, weights=g, minlength=n_snaps)
    if (s_g <= 0).any():
        raise ServeCoreError("refused: a snapshot has zero pooled mass")
    return g * (s_m / s_g)[band_snap]
