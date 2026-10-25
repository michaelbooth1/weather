r"""MG-2 afternoon arm P3d_N: lane L2's pooled residual model served from a frozen state (research only).

The pick (``C:\t\mg2\pick_result.json``, pick rule deb3eae3) put P3d_N in the MG-2 slot from 13:00. This
module serves it on captured inputs only: the anchor is the captured NBM 07Z ``v2_mean`` (``usable_v2_mean``:
finite mean and stddev, available at or before capture), the floor and ``high_so_far`` are the METAR-only
running max (rule C1), and ``current_temp`` is the latest captured METAR row at or before h:00 (L3's
``observations_at_cutoff``).

The serve math is a copy of L2's ``pooled_residual_model`` at d914ae21b (``MeanModel.features`` /
``predict``, the scale model, ``predictive_distribution``, ``feature_model.smoothed_dist``). It runs on a
frozen state file (schema ``mg2_p3d_n_state/1``, agreed with L2) and never imports L2's module. The copy is
pinned by the control check (exact reproduction of ``dev_P3d_N.jsonl`` on the replayed dev rows) and by a
golden test.

Two serve-time hooks are declared by the state and fixed by L2's Clarification 3 before D0:

* ``conversion``: high_so_far and current_temp to WU whole degrees F. Disabled in the dev fit. When enabled,
  serving refuses unless ``rule_id`` is in :data:`CONVERSION_RULES` (``wu_whole_f_tgroup:half_up``, L2
  Clarification 3 (c): round-half-up of the exact 32 + 9t/50, t the T-group tenths of a degree C).
* ``late_report``: ``last_in_hour`` (dev: the last replay snapshot captured in [h:00, h+1:00), rows observed at
  or before h:00) or ``receipt_by`` (rows observed at or before h:00 present in the latest target-date
  snapshot captured at or before h:00 + ``grace_minutes``; receipt time is capture time).

Outside serving, capture and release; refuses a production importer and the capture host.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

STATE_SCHEMA = "mg2_p3d_n_state/1"
ARM = "P3d_N"
STATE_FILE = "p3d_n_state.pkl"
STATE_SIDECAR = "p3d_n_state.json"
FIT_KINDS = ("dev", "forward")
LATE_REPORT_RULES = ("last_in_hour", "receipt_by")
STATE_KEYS = ("schema", "arm", "fit_kind", "markets", "centres", "season_of", "coords", "buckets", "constants",
              "conversion", "late_report", "hours", "provenance")
MEAN_KEYS = ("bias", "bias_by", "bias_global", "normal", "normal_by_market", "normal_global", "x_columns", "ols",
             "hgb", "doy", "market_id")
LEVEL_COLUMNS = ("high_so_far", "current_temp", "live_reading_temp")  # L2's order
UPSTREAM = {"module": "weather.calibration.pooled_residual_model", "commit": "d914ae21b"}

TGROUP_GRID_TOLERANCE = 1e-6  # |temp_native - (32 + 9t/50)| allowed when recovering the T-group tenths t


def tgroup_tenths(value_f):
    """The integer T-group tenths of a degree C behind a METAR ``temp_native`` (°F = C * 1.8 + 32).

    Refuses a value that is not on the tenths-of-°C grid (it was not derived from a METAR temperature group).
    """
    from fractions import Fraction

    x = float(value_f)
    if not math.isfinite(x):
        raise P3dNRefused(f"non-finite METAR temperature {value_f!r}")
    t = round((x - 32.0) * 50.0 / 9.0)
    if abs(float(Fraction(32) + Fraction(9 * t, 50)) - x) > TGROUP_GRID_TOLERANCE:
        raise P3dNRefused(f"METAR temperature {value_f!r} F is not on the T-group tenths-of-C grid")
    return int(t)


def wu_whole_f_tgroup_half_up(value_f):
    """L2 Clarification 3 (c): round-half-up of the exact 32 + 9t/50 °F (t = T-group tenths °C), as an int.

    Exact rational arithmetic: floor(F + 1/2) on a ``Fraction``, so a .5 tie always goes up (also below 0 °F).
    """
    from fractions import Fraction

    exact = Fraction(32) + Fraction(9 * tgroup_tenths(value_f), 50)
    return int(math.floor(exact + Fraction(1, 2)))


# Serve-time WU whole-degree conversion rules, by id (L2's Clarification 3, rule fa4257df). An enabled
# conversion with an unknown id refuses.
CONVERSION_RULES = {"wu_whole_f_tgroup:half_up": wu_whole_f_tgroup_half_up}

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


class P3dNRefused(RuntimeError):
    """The state, an input or a hook cannot serve P3d_N under the rule."""


def _refuse_production_import():
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.mg2_p3d_n is research-only; imported from {name}")
        frame = frame.f_back
    from weather.calibration import r0_ols_floor_challenger  # noqa: F401  (its import refuses on the capture host)


_refuse_production_import()


# ----------------------------------------------------------------------------- state

def state_problems(state):
    """Schema problems of a state dict (empty when it is a valid ``mg2_p3d_n_state/1``)."""
    problems = []
    if not isinstance(state, dict):
        return ["state is not a dict"]
    for key in STATE_KEYS:
        if key not in state:
            problems.append(f"missing:{key}")
    if problems:
        return problems
    if state["schema"] != STATE_SCHEMA:
        problems.append("schema")
    if state["arm"] != ARM:
        problems.append("arm")
    if state["fit_kind"] not in FIT_KINDS:
        problems.append("fit_kind")
    conv = state["conversion"] or {}
    if not isinstance(conv.get("enabled"), bool):
        problems.append("conversion.enabled")
    late = state["late_report"] or {}
    if late.get("rule") not in LATE_REPORT_RULES:
        problems.append("late_report.rule")
    elif late["rule"] == "receipt_by" and not isinstance(late.get("grace_minutes"), int):
        problems.append("late_report.grace_minutes")
    for market in state["markets"]:
        if market not in state["coords"] or market not in state["buckets"]:
            problems.append(f"market:{market}")
    levels = list(state["constants"].get("levels") or [])
    if [c for c in LEVEL_COLUMNS if c in levels] != levels:
        problems.append("constants.levels")
    for hour, entry in state["hours"].items():
        if not isinstance(hour, int):
            problems.append(f"hour_key:{hour!r}")
        for key in ("mean", "scale", "z", "train_y"):
            if key not in entry:
                problems.append(f"hours.{hour}.{key}")
        for key in MEAN_KEYS:
            if key not in (entry.get("mean") or {}):
                problems.append(f"hours.{hour}.mean.{key}")
    return problems


def write_state(state, out_dir):
    """Write ``p3d_n_state.pkl`` (pickle protocol 4) and its sidecar; returns the bound sha256 (file bytes)."""
    problems = state_problems(state)
    if problems:
        raise P3dNRefused(f"state does not match {STATE_SCHEMA}: {problems}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / STATE_FILE
    if path.exists():
        raise P3dNRefused(f"refusing to overwrite {path}")
    blob = pickle.dumps(state, protocol=4)
    path.write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    (out / STATE_SIDECAR).write_text(json.dumps({**state["provenance"], "fit_kind": state["fit_kind"],
                                                 "schema": STATE_SCHEMA, "state_sha256": sha},
                                                indent=1, sort_keys=True, default=str), encoding="utf-8")
    return sha


def load_state(path, expected_sha, *, forward):
    """The frozen state, refused unless its file sha256 is ``expected_sha`` (checked before unpickling).

    ``forward``: a dev fit (``fit_kind`` "dev") is the control-check fit only and is never served forward.
    """
    if not expected_sha or expected_sha == "PENDING":
        raise P3dNRefused("the P3d_N state sha is PENDING (L2's Clarification 3 refit is not frozen)")
    blob = Path(path).read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    if sha != expected_sha:
        raise P3dNRefused(f"P3d_N state sha {sha} != bound {expected_sha}")
    state = pickle.loads(blob)  # noqa: S301 - our own frozen file, sha-verified above
    problems = state_problems(state)
    if problems:
        raise P3dNRefused(f"state does not match {STATE_SCHEMA}: {problems}")
    if forward and state["fit_kind"] != "forward":
        raise P3dNRefused("a dev P3d_N fit is for the control check only and is never served forward")
    return state


# ----------------------------------------------------------------------------- hooks

def convert_observation(value, state):
    """Serve-time conversion of a METAR-derived high_so_far / current_temp (state ``conversion``)."""
    conv = state["conversion"]
    if not conv["enabled"]:
        return value
    rule = CONVERSION_RULES.get(conv.get("rule_id"))
    if rule is None:
        raise P3dNRefused(f"conversion rule {conv.get('rule_id')!r} is not implemented (L2 Clarification 3 pending)")
    return None if value is None else rule(value)


def nearest_centre(target_date, centres):
    """The centre whose month-day is closest to ``target_date``'s (L2's ``nearest_centre``)."""
    d = date.fromisoformat(str(target_date)[:10])
    ref = date(2001, d.month, d.day)
    return min(centres, key=lambda c: abs((date(2001, int(c[5:7]), int(c[8:10])) - ref).days))


def smoothed_dist(buckets, support, alpha=0.10):
    """``feature_model.smoothed_dist``, copied."""
    from collections import Counter

    counts = Counter(int(b) for b in buckets)
    denominator = len(buckets) + alpha * len(support)
    return {s: (counts.get(s, 0) + alpha) / denominator for s in support}


# ----------------------------------------------------------------------------- serve math (L2 d914ae21b)

def _features(mean, levels, row):
    """``MeanModel.features`` on one row (``row``: the pooled-frame scalars)."""
    import numpy as np

    b = mean["bias"].get((row["market"], row[mean["bias_by"]]), mean["bias_global"])
    n = mean["normal"].get((row["market"], row["centre"]),
                           mean["normal_by_market"].get(row["market"], mean["normal_global"]))
    bias, normal = np.array([b]), np.array([n])
    fh = np.array([row["fh"]], dtype=float)
    mu0 = np.where(np.isfinite(fh), fh + bias, normal)
    g = np.array([row["F"]], dtype=float) - mu0
    g = np.where(np.isfinite(g), g, 0.0)
    cols = [np.array([row[c]], dtype=float) for c in mean["x_columns"]]
    for level in levels:
        cols.append(np.array([row[f"x_{level}"]], dtype=float) - mu0)
    cols += [g, np.maximum(g, 0.0), mu0 - normal, np.array([row["lat"]], float), np.array([row["lon"]], float),
             np.array([row["elev"]], float), normal, bias]
    if mean["doy"]:
        cols += [np.array([row["doy_sin"]], float), np.array([row["doy_cos"]], float)]
    if mean["market_id"]:
        cols.append(np.array([row["market_code"]], float))
    return np.column_stack(cols), mu0, g


def predictive_distribution(yhat, s, floor, z, bucket_space, p_clim, constants):
    """L2's ``predictive_distribution``, copied: kernel-smoothed errors, floor-censored, climatology mix."""
    import numpy as np
    from scipy.special import ndtr

    from weather.units import round_half_up

    lo = math.floor(yhat + s * (float(np.min(z)) - 1.5))
    hi = math.ceil(yhat + s * (float(np.max(z)) + 1.5))
    ks = np.arange(lo, hi + 1)
    edges = np.append(ks - 0.5, hi + 0.5)
    t = (edges - yhat) / s
    cdf = ndtr((t[:, None] - z[None, :]) / constants["kernel_bandwidth"]).mean(axis=1)
    mass = np.diff(cdf)
    mass = mass / mass.sum()
    dist = {int(k): float(m) for k, m in zip(ks, mass)}
    if floor is not None and math.isfinite(floor):
        fb = int(round_half_up(floor))
        below = sum(v for k, v in dist.items() if k < fb)
        dist = {k: v for k, v in dist.items() if k >= fb}
        dist[fb] = dist.get(fb, 0.0) + below
    mix = constants["floor_mix_clim"]
    out = {k: (1.0 - mix) * v for k, v in dist.items()}
    for k, v in p_clim.items():
        out[int(k)] = out.get(int(k), 0.0) + mix * float(v)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


def serve_distribution(state, *, market, target_date, hour, nbm_mean, high_so_far, current_temp):
    """P3d_N's integer-bucket distribution for one snapshot; None when the hour has no fit.

    ``high_so_far`` and ``current_temp`` are the captured METAR values; the state's conversion hook is
    applied here, before the anchor gap, the features and the floor.
    """
    import numpy as np

    entry = state["hours"].get(int(hour))
    if entry is None:
        return None
    high_so_far = convert_observation(high_so_far, state)
    current_temp = convert_observation(current_temp, state)
    tdate = date.fromisoformat(str(target_date)[:10])
    doy = tdate.timetuple().tm_yday
    centre = nearest_centre(tdate, state["centres"])
    lat, lon, elev = state["coords"][market]
    row = {"market": market, "centre": centre, "season": state["season_of"][centre[5:7]], "hour": int(hour),
           "F": float(high_so_far), "fh": float(nbm_mean), "lat": lat, "lon": lon, "elev": elev,
           "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
           "x_high_so_far": float(high_so_far), "x_current_temp": float(current_temp),
           "market_code": float(state["markets"].index(market))}
    mean = entry["mean"]
    X, mu0, g = _features(mean, state["constants"]["levels"], row)
    design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
    yhat = mu0 + design @ mean["ols"] + mean["hgb"].predict(X)
    gap = np.nan_to_num(yhat - np.array([row["F"]], dtype=float), nan=0.0)
    s = max(state["constants"]["min_scale"],
            float(entry["scale"].predict(np.column_stack([X, gap]))[0]) * math.sqrt(math.pi / 2))
    p_clim = smoothed_dist(entry["train_y"][market], state["buckets"][market], alpha=state["constants"]["clim_alpha"])
    return predictive_distribution(float(yhat[0]), s, row["F"], entry["z"], state["buckets"][market], p_clim,
                                   state["constants"])


# ----------------------------------------------------------------------------- captured inputs

# The two input paths (rule §8 C4). ``last_in_hour`` is PRIMARY for the MG-2 vs MG-1 gate (symmetric: both are
# scored on the same snapshot rows) and is the dev/pick semantics. ``as_of_capture`` is PRIMARY for every
# comparison against the market (blend R, edge reads, the formal edge test): each row reads only the latest
# replay snapshot captured at or before the row's own capture time, so no METAR row received after that
# snapshot can enter. It is never computed on a dev row.
INPUT_MODES = ("last_in_hour", "as_of_capture")
ASOF_ARM = "p3d_n_asof_capture"

# Rule §8 C5: P3d_N covers a target date only if its month-day lies in the training coverage (L2 Clarification 3
# (a), 08-01..12-16 inclusive); outside it the afternoon slot falls back to MG-1, logged per row.
TRAINING_COVERAGE = ("08-01", "12-16")


def in_training_coverage(target_date):
    md = str(target_date)[5:10]
    return TRAINING_COVERAGE[0] <= md <= TRAINING_COVERAGE[1]


_CAPTURED_LOCAL = None


def _replay_index(folder, target_date, tz):
    """[(capture local datetime, byte offset, size)] of the target date's replay snapshots, in file order."""
    import re

    global _CAPTURED_LOCAL
    if _CAPTURED_LOCAL is None:
        _CAPTURED_LOCAL = re.compile(r'"captured_at_local":\s*"([^"]+)"')
    index = []
    with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
        offset = 0
        for line in handle:
            match = _CAPTURED_LOCAL.search(line[:4096].decode("utf-8", "replace"))
            if match:
                local = datetime.fromisoformat(match.group(1)).astimezone(tz)
                if local.date() == target_date:
                    index.append((local, offset, len(line)))
            offset += len(line)
    return index


def _read_snapshot(folder, start, size):
    with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
        handle.seek(start)
        return json.loads(handle.read(size))


def _observations(snapshot, target_date, hour, tz, unit, local):
    """current_temp, high_so_far and row count from one replay snapshot: rows observed at or before h:00 only."""
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.model import observed_running_max

    metar = (((snapshot.get("sources") or {}).get("metar") or {}).get("data")) or {}
    current, _, n = l3.observations_at_cutoff(metar.get("rows"), target_date, hour, tz)
    high, _ = observed_running_max.running_max_since_midnight(
        {}, metar, target_date=target_date, tz=tz, unit=unit, cutoff_hour=hour, now=local, metar_only=True)
    return {"replay_snapshot_id": snapshot.get("snapshot_id"), "replay_captured_at_local": local.isoformat(),
            "current_temp": current, "high_so_far": high, "n_rows": n}


def scan_replay(folder, target_date, tz, hours, unit, late_report):
    """Per cutoff hour h, METAR inputs from one replay snapshot of ``target_date`` (the state's late-report rule).

    ``last_in_hour``: the last snapshot captured in [h:00, h+1:00) (L2's ``scan_replay_n``);
    ``receipt_by``: the latest snapshot captured at or before h:00 + grace. Either way only rows observed at or
    before h:00 count (``observations_at_cutoff``; ``running_max_since_midnight`` with ``metar_only=True``).
    """
    rule = late_report["rule"]
    if rule not in LATE_REPORT_RULES:
        raise P3dNRefused(f"unknown late-report rule {rule!r}")
    grace = timedelta(minutes=int(late_report.get("grace_minutes") or 0))
    chosen = {}
    for local, offset, size in _replay_index(folder, target_date, tz):
        if rule == "last_in_hour":
            if local.hour in hours:
                chosen[local.hour] = (local, offset, size)
        else:
            for h in hours:
                deadline = datetime.combine(target_date, time(int(h), 0), tzinfo=tz) + grace
                if local <= deadline and (h not in chosen or local >= chosen[h][0]):
                    chosen[h] = (local, offset, size)
    return {hour: _observations(_read_snapshot(folder, start, size), target_date, hour, tz, unit, local)
            for hour, (local, start, size) in sorted(chosen.items())}


def as_of_capture(index, at_local):
    """The index entry of the latest snapshot captured at or before ``at_local`` (None when there is none)."""
    best = None
    for entry in index:
        if entry[0] <= at_local and (best is None or entry[0] >= best[0]):
            best = entry
    return best


def scan_replay_as_of(folder, target_date, tz, hour, at_local, unit, index=None):
    """METAR inputs for cutoff ``hour`` as a process at ``at_local`` would see them (no receipt look-ahead).

    Only the latest snapshot captured at or before ``at_local`` is read, so a row first received in a later
    snapshot cannot enter; within it only rows observed at or before h:00 count.
    """
    index = _replay_index(folder, target_date, tz) if index is None else index
    entry = as_of_capture(index, at_local)
    if entry is None:
        return None
    local, start, size = entry
    return _observations(_read_snapshot(folder, start, size), target_date, hour, tz, unit, local)


def emit_rows(state, snaps, replay_root, first, last, markets=None, inputs="last_in_hour"):
    """[(market, snapshot_id, target_date, row_key, distribution)] in L2's emission order, plus stats.

    Row gate as L2's ``dev_emit_n_distributions`` (cutoff hour in the intraday set, local hour >= cutoff, a
    usable captured NBM mean, a replay observation with high_so_far and current_temp), plus the rule C5
    training-coverage gate (rows outside it are logged per row in ``coverage_fallback`` and fall to MG-1).
    ``inputs``: ``last_in_hour`` (the state's late-report rule) or ``as_of_capture`` (rule C4; refuses dev dates).
    """
    from zoneinfo import ZoneInfo

    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS

    if inputs not in INPUT_MODES:
        raise P3dNRefused(f"unknown input mode {inputs!r}")
    if inputs == "as_of_capture" and first <= DEV_LAST:
        raise P3dNRefused("the as-of-capture arm is never computed on a dev row (<= 2026-09-29)")
    hours = {int(h) for h in INTRADAY_CUTOFF_HOURS}
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    rows, stats = [], {}
    for market in (markets or state["markets"]):
        spec = spec_for_id(market)
        tz = ZoneInfo(spec.timezone)
        obs, folders, indexes, cache = {}, {}, {}, {}
        for slug, target, folder in l3._event_folders(replay_root):
            if slug != market or not (first <= target <= last):
                continue
            folders[target.isoformat()] = (target, folder)
            if inputs == "last_in_hour":
                for hour, rec in scan_replay(folder, target, tz, hours, spec.display_unit,
                                             state["late_report"]).items():
                    obs[(target.isoformat(), hour)] = rec
        m = stats.setdefault(market, {"emitted": 0, "outside_cutoff_hours": 0, "local_hour_before_cutoff": 0,
                                      "outside_training_coverage": 0, "coverage_fallback": [],
                                      "no_usable_nbm": 0, "no_replay_observation": 0, "missing_metar_feature": 0,
                                      "no_fit_for_hour": 0, "replay_hours": 0, "inputs": inputs})
        m["replay_hours"] = len(obs) if inputs == "last_in_hour" else len(folders)
        for row in snaps[snaps.market == market].itertuples(index=False):
            try:
                hour = int(str(row.cutoff_hour))
            except ValueError:
                hour = None
            if hour not in hours:
                m["outside_cutoff_hours"] += 1
                continue
            if int(row.local_hour) < hour:
                m["local_hour_before_cutoff"] += 1
                continue
            key = (str(row.target_date)[:10], hour)
            if not in_training_coverage(key[0]):
                m["outside_training_coverage"] += 1
                m["coverage_fallback"].append(getattr(row, "row_key", None) or row.snapshot_id)
                continue
            nbm = float(row.nbm_usable)
            if not math.isfinite(nbm):
                m["no_usable_nbm"] += 1
                continue
            if inputs == "last_in_hour":
                rec = obs.get(key)
            else:
                rec = None
                if key[0] in folders:
                    target, folder = folders[key[0]]
                    if key[0] not in indexes:
                        indexes[key[0]] = _replay_index(folder, target, tz)
                    at_local = pd.Timestamp(row.captured_at_utc).tz_convert("UTC").to_pydatetime().astimezone(tz)
                    entry = as_of_capture(indexes[key[0]], at_local)
                    if entry is not None:
                        ck = (key[0], entry[1], hour)
                        if ck not in cache:
                            cache[ck] = _observations(_read_snapshot(folder, entry[1], entry[2]), target, hour, tz,
                                                      spec.display_unit, entry[0])
                        rec = cache[ck]
            if rec is None:
                m["no_replay_observation"] += 1
                continue
            if rec["high_so_far"] is None or rec["current_temp"] is None:
                m["missing_metar_feature"] += 1
                continue
            dist = serve_distribution(state, market=market, target_date=key[0], hour=hour, nbm_mean=nbm,
                                      high_so_far=rec["high_so_far"], current_temp=rec["current_temp"])
            if dist is None:
                m["no_fit_for_hour"] += 1
                continue
            rows.append((market, row.snapshot_id, key[0], getattr(row, "row_key", None), dist))
            m["emitted"] += 1
    return rows, stats


def jsonl_line(market, snapshot_id, target_date, dist):
    """One line in L2's ``dev_P3d_N.jsonl`` format (byte-identical when the distribution is)."""
    return json.dumps({"market": market, "snapshot_id": snapshot_id, "target_date": target_date,
                       "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n"


def compare_to_reference(rows, reference_path, tolerance):
    """Row-wise comparison with a reference P3d_N jsonl: same (market, snapshot_id) set, same buckets, |dp| <= tol."""
    ref = {}
    with open(reference_path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                r = json.loads(line)
                ref[(r["market"], r["snapshot_id"])] = r["distribution"]
    ours = {(m, sid): {str(b): p for b, p in d.items() if p > 0} for m, sid, _, _, d in rows}
    missing, extra = sorted(set(ref) - set(ours)), sorted(set(ours) - set(ref))
    worst, bucket_mismatch = 0.0, 0
    for key in set(ref) & set(ours):
        a, b = ref[key], ours[key]
        if set(a) != set(b):
            bucket_mismatch += 1
            continue
        for k in a:
            worst = max(worst, abs(float(a[k]) - float(b[k])))
    return {"reference_rows": len(ref), "rows": len(ours), "missing": len(missing), "extra": len(extra),
            "bucket_set_mismatch": bucket_mismatch, "max_abs": worst, "tolerance": tolerance,
            "pass": not missing and not extra and not bucket_mismatch and worst <= tolerance}


# ----------------------------------------------------------------------------- dev-fit export (control only)

def state_from_fits(fits, buckets, *, frame_columns, markets, centres, season_of, coords, fit_kind, provenance,
                    conversion=None, late_report=None):
    """A ``mg2_p3d_n_state/1`` dict from L2-shaped fits ({(hour, None): {"fit": {...}, "train_y": {...}}}).

    Duck-typed on L2's ``MeanModel`` attributes; L2's own exporter writes the same schema from its branch.
    """
    import numpy as np

    hours = {}
    for (hour, market), entry in sorted(fits.items(), key=lambda kv: kv[0][0]):
        if market is not None:
            raise P3dNRefused("P3d_N is one pooled fit per cutoff hour (no per-market fits)")
        mean = entry["fit"]["mean"]
        hours[int(hour)] = {
            "mean": {"bias": dict(mean.bias), "bias_by": mean.bias_by, "bias_global": mean.bias_global,
                     "normal": dict(mean.normal), "normal_by_market": dict(mean.normal_by_market),
                     "normal_global": mean.normal_global, "x_columns": list(mean.x_columns),
                     "ols": np.asarray(mean.ols, dtype=float), "hgb": mean.hgb, "doy": bool(mean.doy),
                     "market_id": bool(mean.market_id)},
            "scale": entry["fit"]["scale"], "z": np.asarray(entry["fit"]["z"], dtype=float),
            "train_y": {m: [int(v) for v in ys] for m, ys in entry["train_y"].items()}}
    return {"schema": STATE_SCHEMA, "arm": ARM, "fit_kind": fit_kind, "markets": list(markets),
            "centres": list(centres), "season_of": dict(season_of),
            "coords": {m: [float(x) for x in coords[m]] for m in markets},
            "buckets": {m: [int(b) for b in buckets[m]] for m in markets},
            "constants": {"floor_mix_clim": 0.02, "kernel_bandwidth": 0.25, "min_scale": 0.5, "clim_alpha": 0.10,
                          "levels": [c for c in LEVEL_COLUMNS if f"x_{c}" in frame_columns]},
            "conversion": conversion or {"enabled": False, "rule_id": None, "rule": None},
            "late_report": late_report or {"rule": "last_in_hour", "grace_minutes": None},
            "hours": hours, "provenance": dict(provenance)}


def _load_upstream(name, path, expected_sha):
    """Load one pinned upstream research module (L2 / L9 source at a recorded commit) under its package name."""
    import importlib.util

    blob = Path(path).read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    if sha != expected_sha:
        raise P3dNRefused(f"{name} source sha {sha} != pinned {expected_sha}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


UPSTREAM_SHA = {"pooled_residual_model": "c69aa8c49888615b59a50673ddb0dd94aa5551435406999ce41d3eef24d70341",
                "ols_floor_ladder": "6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e"}
DEV_FIRST, DEV_LAST = date(2026, 7, 30), date(2026, 9, 29)
CONTROL_TOLERANCE = 1e-12  # stated before the run: per-bucket |dp|; the byte-identical sha is reported too
SNAPSHOT_COLUMNS = ["row_key", "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour", "v2_mean",
                    "v2_stddev", "v2_available_at", "captured_at_utc"]


def control(*, upstream, ladder, records, nbm_train_corpus, layout, replay_root, reference, out):
    """Dev-fit control: L2's own dev fit, exported to the state schema, served by this module, compared.

    Pass: every reference row reproduced with the same bucket set and |dp| <= CONTROL_TOLERANCE. The
    exported state is ``fit_kind`` "dev": it is never bound (``load_state(forward=True)`` refuses it).
    """
    import platform

    import numpy
    import pandas as pd
    import scipy
    import sklearn

    from weather.market.market_registry import spec_for_id

    l9 = _load_upstream("weather.calibration.ols_floor_ladder", ladder, UPSTREAM_SHA["ols_floor_ladder"])
    prm = _load_upstream("weather.calibration.pooled_residual_model", upstream, UPSTREAM_SHA["pooled_residual_model"])
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise P3dNRefused(f"output directory {out} must be new or empty")
    markets = list(prm.R0_MARKETS)
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = prm.dev_training_frame(records, markets)
    if frame["year"].max() >= 2026:
        raise P3dNRefused("a dev training row is from 2026")
    frame, train_stats = prm.attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    fits = prm.dev_fits(frame, "P3d")
    provenance = {"commit": UPSTREAM["commit"], "module_sha256": UPSTREAM_SHA["pooled_residual_model"],
                  "training_rows": int(len(frame)), "train_years": sorted(int(y) for y in frame["year"].unique()),
                  "train_window": "aug_sep 2021-2025 (dev fit; control only)", "train_nbm": train_stats,
                  "inputs": {"nbm_train_corpus": hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest(),
                             "ols_floor_ladder": UPSTREAM_SHA["ols_floor_ladder"]},
                  "versions": {"python": platform.python_version(), "numpy": numpy.__version__,
                               "scipy": scipy.__version__, "sklearn": sklearn.__version__,
                               "pandas": pd.__version__}}
    state = state_from_fits(fits, buckets, frame_columns=set(frame.columns), markets=markets,
                            centres=prm.AUG_SEP_CENTRES,
                            season_of={f"{m:02d}": prm.season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
                            coords=prm.station_coordinates(markets), fit_kind="dev", provenance=provenance)
    sha = write_state(state, out / "state")
    state = load_state(out / "state" / STATE_FILE, sha, forward=False)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=SNAPSHOT_COLUMNS)
    if (pd.to_datetime(snaps.target_date).dt.date > DEV_LAST).any():
        raise P3dNRefused("layout holds a snapshot after 2026-09-29")
    rows, stats = emit_rows(state, snaps, replay_root, DEV_FIRST, DEV_LAST, markets)
    path = out / f"dev_{ARM}.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as writer:
        for market, sid, tdate, _rk, dist in rows:
            writer.write(jsonl_line(market, sid, tdate, dist))
    result = {"state_sha256_dev_never_bound": sha, "emit_stats": stats,
              "vector_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "reference_sha256": hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
              "comparison": compare_to_reference(rows, reference, CONTROL_TOLERANCE)}
    result["byte_identical"] = result["vector_sha256"] == result["reference_sha256"]
    # L2's reference was written in Windows text mode (CRLF); this emission writes LF. Same content otherwise.
    ref_lf = Path(reference).read_bytes().replace(b"\r\n", b"\n")
    result["byte_identical_lf_normalised"] = path.read_bytes() == ref_lf
    (out / "control.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return result


GOLDEN_MARKETS = ("atlanta", "denver", "seattle")
GOLDEN_HOURS = (13, 15)
GOLDEN_CENTRES = ("2026-08-08", "2026-08-23", "2026-09-07", "2026-09-22")


def golden_frame(seed=20261025):
    """A small synthetic pooled training frame (L2's ``pooled_frame`` columns after ``dev_training_frame``)."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    rows = []
    for mi, market in enumerate(GOLDEN_MARKETS):
        for hour in GOLDEN_HOURS:
            for year in (2022, 2023, 2024):
                for centre in GOLDEN_CENTRES:
                    for k in range(-7, 8, 2):
                        tdate = date(year, int(centre[5:7]), int(centre[8:10])) + timedelta(days=k)
                        y = float(round(80 + 4 * mi + rng.normal(0, 3)))
                        fh = y + rng.normal(0.5, 2.0) if rng.random() > 0.05 else float("nan")
                        hs = y - max(0.0, rng.normal(4 - (hour - 13), 2))
                        doy = tdate.timetuple().tm_yday
                        rows.append({"market": market, "centre": centre, "season": "aug_sep", "hour": hour,
                                     "target_date": tdate.isoformat(), "year": year, "y": y, "F": hs, "fh": fh,
                                     "lat": 30.0 + mi, "lon": -90.0 - 5 * mi, "elev": 100.0 * mi,
                                     "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                                     "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                                     "x_high_so_far": hs, "x_current_temp": hs - abs(rng.normal(1, 1)),
                                     "market_code": float(mi)})
    return pd.DataFrame(rows)


GOLDEN_CASES = tuple(
    {"market": m, "target_date": d, "hour": h, "nbm_mean": nbm, "high_so_far": hs, "current_temp": ct}
    for m, d, h, nbm, hs, ct in (
        ("atlanta", "2026-08-15", 13, 83.4, 78.2, 77.9), ("denver", "2026-09-02", 15, 86.0, 85.6, 85.6),
        ("seattle", "2026-09-28", 13, 90.1, 80.0, 79.1), ("atlanta", "2026-08-01", 15, 79.0, 81.3, 80.2),
        ("seattle", "2026-08-20", 15, 95.5, 70.4, 70.4)))


def golden(*, upstream, out):
    """Expected P3d_N distributions from L2's own code (``fit_pooled`` and its emit path) on the golden frame."""
    import numpy as np
    import pandas as pd

    prm = _load_upstream("weather.calibration.pooled_residual_model", upstream, UPSTREAM_SHA["pooled_residual_model"])
    from weather.calibration import feature_model as fm

    frame = golden_frame()
    buckets = {m: list(range(60, 111)) for m in GOLDEN_MARKETS}
    coords = {m: (30.0 + i, -90.0 - 5 * i, 100.0 * i) for i, m in enumerate(GOLDEN_MARKETS)}
    fits = {}
    for hour in GOLDEN_HOURS:
        train = frame[frame.hour == hour].reset_index(drop=True)
        fits[hour] = {"fit": prm.fit_pooled(train, market_id=False, doy=True, raw_columns=False),
                      "train_y": {m: [int(v) for v in train.loc[train.market == m, "y"]] for m in train.market.unique()}}
    cases = []
    for case in GOLDEN_CASES:
        market, key0, hour = case["market"], case["target_date"], case["hour"]
        tdate = date.fromisoformat(key0)
        doy = tdate.timetuple().tm_yday
        lat, lon, elev = coords[market]
        one = pd.DataFrame([{
            "market": market, "centre": prm.nearest_centre(key0, GOLDEN_CENTRES), "season": "aug_sep", "hour": hour,
            "target_date": key0, "year": tdate.year, "y": float("nan"), "F": float(case["high_so_far"]),
            "fh": float(case["nbm_mean"]), "lat": lat, "lon": lon, "elev": elev,
            "doy_sin": math.sin(2 * math.pi * doy / 365.25), "doy_cos": math.cos(2 * math.pi * doy / 365.25),
            "x_high_so_far": float(case["high_so_far"]), "x_current_temp": float(case["current_temp"]),
            "market_code": float(GOLDEN_MARKETS.index(market))}])
        fitted = fits[hour]["fit"]
        yhat, X = fitted["mean"].predict(one)
        gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
        s = max(prm.MIN_SCALE, float(fitted["scale"].predict(np.column_stack([X, gap]))[0]) * math.sqrt(math.pi / 2))
        p_clim = fm.smoothed_dist(fits[hour]["train_y"][market], buckets[market], alpha=0.10)
        dist = prm.predictive_distribution(float(yhat[0]), s, float(one.at[0, "F"]), fitted["z"], buckets[market],
                                           p_clim)
        cases.append({**case, "distribution": {str(k): v for k, v in dist.items()}})
    payload = {"upstream": UPSTREAM, "upstream_sha256": UPSTREAM_SHA["pooled_residual_model"], "cases": cases}
    Path(out).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return payload


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_p3d_n")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("golden", help="expected distributions from L2's own code on the synthetic frame")
    g.add_argument("--upstream", required=True)
    g.add_argument("--out", required=True)
    p = sub.add_parser("control", help="dev-fit control: reproduce L2's dev_P3d_N.jsonl (heavy)")
    for name in ("upstream", "ladder", "records", "nbm-train-corpus", "layout", "replay-root", "reference", "out"):
        p.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    if args.command == "golden":
        payload = golden(upstream=args.upstream, out=args.out)
        print(json.dumps({"cases": len(payload["cases"])}), flush=True)
        return 0
    try:
        result = control(upstream=args.upstream, ladder=args.ladder, records=args.records,
                         nbm_train_corpus=args.nbm_train_corpus, layout=args.layout, replay_root=args.replay_root,
                         reference=args.reference, out=args.out)
    except P3dNRefused as exc:
        print(json.dumps({"refused": str(exc)}), flush=True)
        return 2
    print(json.dumps({k: result[k] for k in ("comparison", "byte_identical", "byte_identical_lf_normalised", "vector_sha256")}, indent=1,
                     sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
