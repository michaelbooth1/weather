"""MG-3 serve path: the frozen P3d_H states with their HRRR extras, the 07-12 blend, and the hour table.

Guards: MG3-DC-1 s2.1 (the hour table, :mod:`weather.model.mg3_arms`), L2's frozen-state rule
(``rule_mg3_p3dh_state.md`` s2, P3d_H serve math), the SM-H served-state binding note
(``binding_sm_h_state.md``, sha256 6507946e...), train/serve feature parity, the effective WU print cutoff, and
MG-2's serve path (:mod:`weather.model.mg_serve_core`), which is reused unchanged.

The module is pure serving code. It imports only the standard library, numpy, scipy, ``weather.paths``,
``weather.units``, the serve core and the hour table, and it names no research module, not even in text. Its
copies of research-side functions are pinned equal to their sources by ``tests/model/test_mg3_serve_parity.py``.

Refusal contract: nothing here falls back.

* Every :class:`~weather.model.mg3_arms.Mg3ArmError` becomes a :class:`Mg3ServeError`.
* Any sha256 mismatch, a missing binding field, or a state, weights file or L6 partner that disagrees with the
  binding raises :class:`Mg3ServeError`.
* A snapshot whose arm produced no distribution is reported with source ``"none"``. Another arm's output is
  never substituted.

What the binding must carry (read, never defaulted). Its ``schema`` must be ``mg3_release_binding/2``; any other
schema refuses (master ruling (A), 2026-10-27):

* ``states["07-12"]``: ``sha256`` and ``point_rule`` (``"rn1"``);
* ``states["SM-H 13-15"]``: ``sha256``, ``hours`` and ``excluded_markets`` (and ``point_rule`` ``"nearest"``);
* ``rn1``: ``land_sha256``, ``default_index`` and ``index`` (the RN-1 land point rule);
* ``weights_sha256``: the 07-12 blend weights;
* ``l6_partner``: ``state_sha256`` (the L6 own-model state), ``part_sha256`` (MG-2's l6_stack part) and
  ``nowcasts_sha256`` (the partner nowcasts the weights were fitted against).

There is no CLI, and nothing here writes a file.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.model import mg3_arms
from weather.model import mg_serve_core as core

MG3_STATE_SCHEMA = "mg3_p3d_h_state/1"
P3DH_ARM = "P3d_H"
P3DH_EXTRA = ("k_max", "k_gap", "k_tcdc")
BLOCK_0712 = "07-12"
BINDING_SCHEMA = "mg3_release_binding/2"
SM_H_BLOCK = mg3_arms.SM_H_STATE_BLOCK

# The frozen SM-H served state (L2, binding_sm_h_state.md). Refused on any mismatch.
SM_H_STATE_SHA256 = "b6bc242a8c2b679069a4090b8912eea3b80af160b6bc228424c846fb3b87a477"
SM_H_CONTROL_SHA256 = "5a106a0dbbb6226101c3bc7782023b62e826e8c26062b3d7fdcc3370475c79be"
SM_H_NOTE_SHA256 = "6507946e185fb4ba1a76e1c5022f14a38d981a3904fd8aaf16ac65837df74cab"

# HRRR extras, exactly as the states were fitted (R-K raw path; R-R adds the RN-1 point rule at 07-12).
HRRR_VARIABLES = {"TMP": "TMP:2 m above ground", "TCDC": "TCDC:entire atmosphere"}
HRRR_VALID_END_LOCAL = 17
HRRR_MARGIN_S = 10 * 60
HRRR_TMP_RANGE_F = (-60.0, 130.0)

L6_SUPPORT = 80  # integer bands from half-up(floor); the last is open above


class Mg3ServeError(ValueError):
    """The MG-3 serve path refuses: a binding, state, weights or input does not match what is bound."""


def _sha256_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(Path(path).read_bytes())


def check_binding_schema(binding):
    """Refuse any binding whose ``schema`` is not :data:`BINDING_SCHEMA`."""
    schema = binding.get("schema") if isinstance(binding, dict) else None
    if schema != BINDING_SCHEMA:
        raise Mg3ServeError(f"MG-3 binding schema {schema!r} != {BINDING_SCHEMA!r}; refusing")


def _need(mapping, key, where):
    if not isinstance(mapping, dict) or key not in mapping or mapping[key] in (None, ""):
        raise Mg3ServeError(f"the MG-3 binding has no {where}{key!r}; refusing (no default)")
    return mapping[key]


# ----------------------------------------------------------------------------- frozen P3d_H states

def load_p3dh_state(path, expected_sha256, *, block, hours):
    """A frozen ``mg3_p3d_h_state/1`` state, unpickled only after its file sha256 equals ``expected_sha256``.

    It must be the P3d_H arm of ``block`` with exactly ``hours`` and the extra HGB columns (k_max, k_gap, k_tcdc)
    in that order, at the state level and in every hour, and no extra OLS column.
    """
    import pickle

    blob = Path(path).read_bytes()
    digest = _sha256_bytes(blob)
    if digest != expected_sha256:
        raise Mg3ServeError(f"MG-3 state {path}: sha256 {digest} != bound {expected_sha256}")
    state = pickle.loads(blob)
    if not isinstance(state, dict) or state.get("schema") != MG3_STATE_SCHEMA or state.get("arm") != P3DH_ARM:
        raise Mg3ServeError(f"MG-3 state {path}: schema or arm is not {MG3_STATE_SCHEMA} / {P3DH_ARM}")
    if state.get("block") != block:
        raise Mg3ServeError(f"MG-3 state {path}: block {state.get('block')!r} != {block!r}")
    if tuple(state.get("extra_hgb") or ()) != P3DH_EXTRA:
        raise Mg3ServeError(f"MG-3 state {path}: extra_hgb {state.get('extra_hgb')} != {list(P3DH_EXTRA)}")
    if tuple(sorted(int(h) for h in state.get("hours") or {})) != tuple(hours):
        raise Mg3ServeError(f"MG-3 state {path}: hours {sorted(state.get('hours') or {})} != {list(hours)}")
    for h, entry in state["hours"].items():
        mean = entry.get("mean") or {}
        if tuple(mean.get("extra_hgb") or ()) != P3DH_EXTRA or mean.get("extra_ols"):
            raise Mg3ServeError(f"MG-3 state {path}: hour {h} columns differ from the state's extra_hgb")
    return state


def load_sm_h_state(state_dir, *, state_sha256=None, control_sha256=None, note_sha256=None):
    """The frozen SM-H served state (13-15) from L2's state directory, refused on any sha mismatch.

    The expected shas default to this module's bound constants (read at call time).

    ``control.json`` must hash to ``control_sha256`` and PASS every check; it and the ``p3d_h_state.json``
    sidecar must both name ``state_sha256`` and ``note_sha256``; the pickle must hash to ``state_sha256``; the
    state must read raw temperatures (no conversion), as fitted.
    """
    state_sha256 = SM_H_STATE_SHA256 if state_sha256 is None else state_sha256
    control_sha256 = SM_H_CONTROL_SHA256 if control_sha256 is None else control_sha256
    note_sha256 = SM_H_NOTE_SHA256 if note_sha256 is None else note_sha256
    d = Path(state_dir)
    control_path = d / "control.json"
    got = _sha256_file(control_path)
    if got != control_sha256:
        raise Mg3ServeError(f"SM-H control {control_path}: sha256 {got} != bound {control_sha256}")
    control = json.loads(control_path.read_text(encoding="utf-8"))
    checks = control.get("checks") or {}
    if control.get("pass") is not True or not checks or not all(
            isinstance(c, dict) and c.get("pass") is True for c in checks.values()):
        raise Mg3ServeError(f"SM-H control {control_path} does not PASS every check")
    sidecar = json.loads((d / "p3d_h_state.json").read_text(encoding="utf-8"))
    for name, doc in (("control", control), ("sidecar", sidecar)):
        if doc.get("state_sha256") != state_sha256 or doc.get("note_sha256") != note_sha256:
            raise Mg3ServeError(f"SM-H {name}: state or note sha256 differs from the bound values")
        if doc.get("block") != SM_H_BLOCK:
            raise Mg3ServeError(f"SM-H {name}: block {doc.get('block')!r} != {SM_H_BLOCK!r}")
    state = load_p3dh_state(d / "p3d_h_state.pkl", state_sha256, block=SM_H_BLOCK, hours=mg3_arms.SM_H_HOURS)
    if (state.get("conversion") or {}).get("enabled") is not False:
        raise Mg3ServeError("SM-H state: conversion must be disabled (raw high_so_far and current_temp, as fitted)")
    return state


# ----------------------------------------------------------------------------- HRRR extras (train/serve parity)

def rn1_point_map(binding, icaos):
    """{icao: block3x3 index} by the binding's RN-1 land point rule (stations not named take ``default_index``)."""
    check_binding_schema(binding)
    rn1 = _need(binding, "rn1", "")
    default = int(_need(rn1, "default_index", "rn1."))
    index = _need(rn1, "index", "rn1.")
    if not isinstance(index, dict):
        raise Mg3ServeError(f"rn1.index must be a map of station -> index, got {index!r}")
    out = {icao: int(index.get(icao, default)) for icao in icaos}
    if not all(0 <= v <= 8 for v in out.values()):
        raise Mg3ServeError(f"rn1 indices must be 0-8: {out}")
    return out


def hrrr_message_key(cycle, fh):
    """The AWS object key of one HRRR surface file (the corpus manifest ``key``)."""
    return f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{int(fh):02d}.grib2"


def hrrr_raw_path(selection, messages, *, icao, tz, local_date, hour, point=None):
    """One snapshot's raw HRRR path, exactly as the states' training columns were built.

    ``selection`` is the snapshot's cycle selection (``cycle_utc``, ``fhs``, ``latest_available_utc``,
    ``snapshot_utc``). ``messages`` are the manifest records of that cycle (``cycle_utc``, ``fh``, ``key``,
    ``idx_record``, ``points``). ``point``: None reads each message's ``nearest`` value; a {icao: block index} map
    reads ``block3x3[index]`` (RN-1), and a station absent from it is a miss.

    Effective cutoff: the snapshot instant is ``hour``:00 local. A cycle counts only when its latest message was
    available at least 10 minutes before it, and every valid time lies in [snapshot, 17:00 local]. Anything else
    is a miss with a reason, never a later cycle. -> {k_max, k_tcdc, k_miss, reason}.
    """
    tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    target = date.fromisoformat(str(local_date)[:10])
    snapshot = datetime.combine(target, time(int(hour), 0), tzinfo=tz)
    window_end = datetime.combine(target, time(HRRR_VALID_END_LOCAL, 0), tzinfo=tz)
    entry = {"k_max": float("nan"), "k_tcdc": float("nan"), "k_miss": 1.0, "reason": None}
    if selection is None:
        entry["reason"] = "no_selection"
        return entry
    fhs = list(selection.get("fhs") or [])
    if point is not None and icao not in point:
        entry["reason"] = "no_land_cell"
        return entry
    if datetime.fromisoformat(selection["snapshot_utc"]) != snapshot:
        entry["reason"] = "snapshot_mismatch"
        return entry
    if selection.get("cycle_utc") is None or not fhs:
        entry["reason"] = "no_cycle"
        return entry
    cycle = datetime.fromisoformat(selection["cycle_utc"])
    latest = selection.get("latest_available_utc")
    if latest is None or datetime.fromisoformat(latest) + timedelta(seconds=HRRR_MARGIN_S) > snapshot:
        entry["reason"] = "pit_violation"
        return entry
    valid = [cycle + timedelta(hours=int(fh)) for fh in fhs]
    if min(valid) < snapshot or max(valid) > window_end:
        entry["reason"] = "window_violation"
        return entry
    values, mismatched = {}, set()
    for m in messages or ():
        record = str(m.get("idx_record") or "")
        var = next((v for v, prefix in HRRR_VARIABLES.items() if record.startswith(prefix + ":")), None)
        if var is None:
            continue
        m_cycle, fh = datetime.fromisoformat(m["cycle_utc"]), int(m["fh"])
        key = (m_cycle, fh, var)
        if m.get("key") != hrrr_message_key(m_cycle, fh) or record != f"{HRRR_VARIABLES[var]}:{fh} hour fcst:":
            mismatched.add(key)
            continue
        cell = (m.get("points") or {}).get(icao) or {}
        if point is None:
            value = cell.get("nearest")
        else:
            block = cell.get("block3x3")
            value = block[point[icao]] if isinstance(block, list) and len(block) == 9 else None
        if key in values and values[key] != value:  # a duplicate message that disagrees at this station
            mismatched.add(key)
            continue
        values.setdefault(key, value)
    tmp, tcdc = [], []
    for fh in fhs:
        for var, sink in (("TMP", tmp), ("TCDC", tcdc)):
            k = (cycle, int(fh), var)
            if k in mismatched:
                entry["reason"] = "identity_mismatch"
            v = values.get(k)
            sink.append(float("nan") if v is None else float(v))
    if entry["reason"] == "identity_mismatch":
        return entry
    if not all(math.isfinite(v) for v in tmp + tcdc):
        entry["reason"] = "message_absent"
        return entry
    tmp_f = [(v - 273.15) * 9.0 / 5.0 + 32.0 for v in tmp]
    if min(tmp_f) < HRRR_TMP_RANGE_F[0] or max(tmp_f) > HRRR_TMP_RANGE_F[1]:
        entry["reason"] = "tmp_out_of_range"
        return entry
    entry.update(k_max=max(tmp_f), k_tcdc=sum(tcdc) / len(tcdc), k_miss=0.0)
    return entry


def hrrr_extra_columns(entry, nbm_mean):
    """{k_max, k_gap, k_tcdc}: the raw path plus ``k_gap`` against the row's own NBM anchor; NaN on a miss."""
    if entry is None or entry["k_miss"]:
        return {"k_max": float("nan"), "k_gap": float("nan"), "k_tcdc": float("nan")}
    gap = entry["k_max"] - float(nbm_mean) if nbm_mean is not None and math.isfinite(float(nbm_mean)) else float("nan")
    return {"k_max": entry["k_max"], "k_gap": gap, "k_tcdc": entry["k_tcdc"]}


# ----------------------------------------------------------------------------- P3d_H serve math

def p3dh_X(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean, extra):
    """The frozen state's X row: the serve core's ``state_features`` plus ``extra_hgb`` in the state's order."""
    import numpy as np

    X, mu0, g, floor = core.state_features(state, hour, market=market, target_date=target_date,
                                           high_so_far=high_so_far, current_temp=current_temp, nbm_mean=nbm_mean)
    tail = np.asarray([[float(extra[c]) for c in state["extra_hgb"]]], dtype=float)
    return np.column_stack([X, tail]), mu0, g, floor


def p3dh_distribution(state, hour, *, market, target_date, high_so_far, current_temp, nbm_mean, extra):
    """P3d_H's integer-bucket distribution from a frozen ``mg3_p3d_h_state/1`` state (rule s2)."""
    import numpy as np

    X, mu0, g, floor = p3dh_X(state, hour, market=market, target_date=target_date, high_so_far=high_so_far,
                              current_temp=current_temp, nbm_mean=nbm_mean, extra=extra)
    entry = state["hours"][int(hour)]
    mean = entry["mean"]
    if mean.get("extra_ols"):
        raise Mg3ServeError("an MG-3 P3d_H state has no extra OLS columns")
    yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
    c = state["constants"]
    s = max(c["min_scale"],
            float(entry["scale"].predict(np.column_stack([X, [yhat - floor]]))[0]) * math.sqrt(math.pi / 2))
    p_clim = core.smoothed_dist(entry["train_y"][market], state["buckets"][market], alpha=c["clim_alpha"])
    return core.predictive_distribution(yhat, s, floor, entry["z"], state["buckets"][market], p_clim)


# ----------------------------------------------------------------------------- 07-12 blend

def l6_part_coefficients(part, expected_sha256):
    """MG-2's ``l6_stack`` part: its canonical-JSON sha256 must equal the bound one. -> {hour: (a, b)}."""
    sha = _sha256_bytes(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    if sha != expected_sha256:
        raise Mg3ServeError(f"l6_stack part sha256 {sha} != bound {expected_sha256}")
    return {int(h): (float(v[0]), float(v[1])) for h, v in part["coef"].items()}


def l6_band_distribution(mu, sigma, floor):
    """Normal(mu, sigma) on integer bands from half-up(floor) for ``L6_SUPPORT`` bands, the last open above,
    renormalised (all mass on the floor band if none is left). -> {bucket: p} without zero entries."""
    from scipy.special import ndtr

    B = math.floor(float(floor) + 0.5)
    probs = []
    for i in range(L6_SUPPORT):
        k = B + i
        lower = float(ndtr((k - 0.5 - mu) / sigma))
        upper = 1.0 if i == L6_SUPPORT - 1 else float(ndtr((k + 0.5 - mu) / sigma))
        probs.append(max(upper - lower, 0.0))
    total = sum(probs)
    if not total > 0:
        return {int(B): 1.0}
    return {int(B + i): p / total for i, p in enumerate(probs) if p / total > 0.0}


def l6_distribution(coef, hour, *, v, s, floor, nowcast):
    """The L6 partner: Normal(v + a_h + b_h (N - v), max(s, 1)) floored at half-up(F); with no finite N it is the
    MG-1 analogue Normal(v, max(s, 1)), exactly as the partner was scored when the weights were fitted."""
    if not all(x is not None and math.isfinite(float(x)) for x in (v, s, floor)):
        return None
    a, b = coef[int(hour)]
    mu = float(v)
    if nowcast is not None and math.isfinite(float(nowcast)):
        mu = float(v) + a + b * (float(nowcast) - float(v))
    return l6_band_distribution(mu, max(float(s), 1.0), float(floor))


def mix(p, q, w):
    """w p + (1 - w) q over the union of buckets."""
    return {k: w * p.get(k, 0.0) + (1.0 - w) * q.get(k, 0.0) for k in sorted(set(p) | set(q))}


def bind_blend_weights(binding, weights_path):
    """The 07-12 blend weights the binding names, verified against it. -> {hour: w}.

    The file must hash to ``weights_sha256`` and agree with its ``.sha256`` sidecar; it must PASS every check
    (a ``checks`` block, or a single ``control`` block) with nothing stopped; and it must have been fitted against
    the binding's ``l6_partner``: ``inputs.l6_part`` equals ``part_sha256`` and the partner nowcasts
    (``inputs.season_nowcasts`` when present, else ``inputs.nowcasts``) equal ``nowcasts_sha256``.
    """
    check_binding_schema(binding)
    sha = _need(binding, "weights_sha256", "")
    partner = _need(binding, "l6_partner", "")
    part_sha = _need(partner, "part_sha256", "l6_partner.")
    nowcasts_sha = _need(partner, "nowcasts_sha256", "l6_partner.")
    got = _sha256_file(weights_path)
    if got != sha:
        raise Mg3ServeError(f"blend weights {weights_path}: sha256 {got} != bound {sha}")
    side_path = Path(str(weights_path) + ".sha256")
    side = side_path.read_text(encoding="utf-8").split() if side_path.exists() else []
    if not side or side[0] != sha:
        raise Mg3ServeError("blend weights .sha256 sidecar is missing or disagrees")
    w = json.loads(Path(weights_path).read_text(encoding="utf-8"))
    if "checks" in w:
        checks = w.get("checks") or {}
        ok = bool(checks) and not w.get("stopped_at") and all(
            isinstance(c, dict) and c.get("pass") is True for c in checks.values())
    elif "control" in w:
        ok = isinstance(w["control"], dict) and w["control"].get("pass") is True
    else:
        ok = False
    if not ok:
        raise Mg3ServeError("blend weights do not PASS their checks")
    inputs = w.get("inputs") or {}
    fitted_nowcasts = inputs.get("season_nowcasts", inputs.get("nowcasts"))
    if inputs.get("l6_part") != part_sha or fitted_nowcasts != nowcasts_sha:
        raise Mg3ServeError("blend weights were not fitted against the binding's l6_partner")
    weights = {int(str(k).lstrip("h")): float(v) for k, v in (w.get("weights") or {}).items()}
    if tuple(sorted(weights)) != mg3_arms.BLEND_HOURS or not all(0.0 <= x <= 1.0 for x in weights.values()):
        raise Mg3ServeError(f"blend weights hours or values invalid: {weights}")
    return weights


# ----------------------------------------------------------------------------- the served bundle

class Mg3Serve:
    """Everything MG-3 serves beyond MG-2, loaded once and verified against the binding."""

    def __init__(self, binding, state_0712, sm_h_state, weights, l6_state, l6_coef):
        self.binding = binding
        self.state_0712 = state_0712
        self.sm_h_state = sm_h_state
        self.weights = weights
        self.l6_state = l6_state
        self.l6_coef = l6_coef


def load_serve(binding, *, state_0712_path, sm_h_dir, weights_path, l6_state_path, l6_part):
    """Load and verify every MG-3 serve part against ``binding``; refuse on any mismatch or missing field."""
    check_binding_schema(binding)
    states = _need(binding, "states", "")
    b0712 = _need(states, BLOCK_0712, "states.")
    bsmh = _need(states, SM_H_BLOCK, "states.")
    if _need(b0712, "point_rule", "states['07-12'].") != "rn1":
        raise Mg3ServeError("the 07-12 state must be bound with the RN-1 point rule")
    if bsmh.get("point_rule", "nearest") != "nearest":
        raise Mg3ServeError("the SM-H state is served with the nearest-cell point rule, as fitted")
    sm_h_sha = _need(bsmh, "sha256", f"states[{SM_H_BLOCK!r}].")
    if sm_h_sha != SM_H_STATE_SHA256:
        raise Mg3ServeError(f"the binding's SM-H sha256 {sm_h_sha} != the frozen served state {SM_H_STATE_SHA256}")
    mg3_arms_check(binding)
    state_0712 = load_p3dh_state(state_0712_path, _need(b0712, "sha256", "states['07-12']."),
                                 block=BLOCK_0712, hours=mg3_arms.BLEND_HOURS)
    land = (state_0712.get("point_rule") or {}).get("land_sha256")
    if land != _need(_need(binding, "rn1", ""), "land_sha256", "rn1."):
        raise Mg3ServeError(f"the 07-12 state's land file {land} != the binding's RN-1 land file")
    sm_h_state = load_sm_h_state(sm_h_dir, state_sha256=sm_h_sha)
    weights = bind_blend_weights(binding, weights_path)
    partner = _need(binding, "l6_partner", "")
    try:
        l6_state = core.load_l6_own_state(l6_state_path, _need(partner, "state_sha256", "l6_partner."))
    except core.ServeCoreError as exc:
        raise Mg3ServeError(str(exc)) from exc
    l6_coef = l6_part_coefficients(l6_part, partner["part_sha256"])
    if not set(mg3_arms.BLEND_HOURS) <= set(l6_coef):
        raise Mg3ServeError("the l6_stack part has no coefficients for every 07-12 hour")
    return Mg3Serve(binding, state_0712, sm_h_state, weights, l6_state, l6_coef)


def mg3_arms_check(binding):
    """The binding's SM-H block must be readable by the hour table (every Mg3ArmError refuses)."""
    serve_arm(binding, "atlanta", mg3_arms.SM_H_HOURS[0])


def serve_arm(binding, market, hour):
    """The arm MG-3 serves for ``market`` at local ``hour``; an unreadable binding refuses, never defaults."""
    check_binding_schema(binding)
    try:
        return mg3_arms.mg3_hour_arm(binding, market, hour)
    except mg3_arms.Mg3ArmError as exc:
        raise Mg3ServeError(f"MG-3 hour table refused: {exc}") from exc


def arm_distribution(serve, arm, *, market, hour, target_date, high_so_far, current_temp, nbm_mean, extra,
                     mg1=None, l6_nowcast=None):
    """One snapshot's distribution for an MG-3-owned arm; None when its inputs are missing (never a fallback).

    ``extra`` is :func:`hrrr_extra_columns` of the snapshot (NaN on a miss, as fitted). ``mg1`` is the MG-1
    analogue inputs ``(v, s, F)`` the 07-12 L6 partner needs; ``l6_nowcast`` the partner's own nowcast N.
    """
    inputs = dict(market=market, target_date=target_date, high_so_far=high_so_far, current_temp=current_temp,
                  nbm_mean=nbm_mean, extra=extra)
    if high_so_far is None or current_temp is None:
        return None
    if arm == mg3_arms.ARM_SM_H:
        return p3dh_distribution(serve.sm_h_state, hour, **inputs)
    if arm == mg3_arms.ARM_BLEND_0712:
        if mg1 is None:
            return None
        v, s, floor = mg1
        l6 = l6_distribution(serve.l6_coef, hour, v=v, s=s, floor=floor, nowcast=l6_nowcast)
        if l6 is None:
            return None
        return mix(p3dh_distribution(serve.state_0712, hour, **inputs), l6, serve.weights[int(hour)])
    raise Mg3ServeError(f"arm {arm!r} is not served by MG-3's own parts")


def compose_mg3(binding, snaps, bands, mg2_frame, mg2_source, mg3_dists):
    """Per snapshot: the arm the hour table names. MG-2's rows come from the serve core's composed MG-2 frame,
    unchanged; MG-3's arms come from ``mg3_dists`` ({arm: {row_key: distribution}}) through the core's band map.

    ``snaps`` needs ``row_key``, ``market`` and ``local_hour``. A snapshot whose arm has no output gets source
    ``"none"`` and no rows; no other arm is substituted. -> (frame, {row_key: source}).
    """
    import pandas as pd

    arms, source = {}, {}
    for rk, market, hour in zip(snaps.row_key, snaps.market, snaps.local_hour):
        arms[rk] = serve_arm(binding, market, int(hour))
    mg2_keys = {rk for rk, a in arms.items() if a == mg3_arms.ARM_MG2}
    parts = [mg2_frame[mg2_frame.row_key.isin(mg2_keys)]]
    for rk in mg2_keys:
        src = mg2_source.get(rk, "none")
        source[rk] = f"{mg3_arms.ARM_MG2}:{src}" if src != "none" else "none"
    for arm in (mg3_arms.ARM_BLEND_0712, mg3_arms.ARM_SM_H):
        keys = [rk for rk, a in arms.items() if a == arm]
        dists = {rk: mg3_dists.get(arm, {}).get(rk) for rk in keys}
        have = {rk: d for rk, d in dists.items() if d}
        if have:
            parts.append(core.distribution_band_frame(have, bands))
        for rk in keys:
            source[rk] = arm if rk in have else "none"
    frame = pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(
        not p.empty for p in parts) else mg2_frame.iloc[0:0]
    return frame.sort_values(["row_key", "band_index"]).reset_index(drop=True), source
