"""MG-3 serve path (weather.model.mg3_serve) on synthetic data only.

Guards: MG3-DC-1 s2.1 hour table and the SM-H binding note (binding_sm_h_state.md, 6507946e...); L2's frozen-state
rule s2 (P3d_H = the P3d_N serve math with extra_hgb appended); train/serve feature parity of the HRRR extras and
the effective WU print cutoff (a cycle not available 10 minutes before the snapshot is a miss, never used); the
07-12 blend and its L6 partner read only from the binding (RF-1 weights 891be564 with SM-L6 800072c7 is the
primary shape; a binding naming the frozen c7b8ebc0 weights serves exactly those); every Mg3ArmError and every
sha mismatch refuses, with no default and no fallback; SF at 13-15 serves MG-2's arm end-to-end through
mg_serve_core. Nothing here reads a real outcome; the real SM-H state is read (sha check only) when present.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.model import mg3_arms
from weather.model import mg3_serve as ms
from weather.model import mg_serve_core as core

MARKETS = ("atlanta", "san-francisco")
REAL_SM_H = Path("C:/t/l2/mg3/state_smh")

RF1_PARTNER = {"state_sha256": None, "part_sha256": "07a67425" + "0" * 56, "nowcasts_sha256": "714fa14e" + "0" * 56}
FROZEN_NOWCASTS = "3806687c" + "0" * 56


# ----------------------------------------------------------------------------- synthetic frozen states

def _models(width, seed):
    from sklearn.ensemble import HistGradientBoostingRegressor

    rng = np.random.default_rng(seed)
    X = rng.normal(size=(200, width))
    X[::7, -3:] = np.nan  # the fitted HGB saw HRRR misses as NaN
    hgb = HistGradientBoostingRegressor(max_iter=5, random_state=0).fit(X, rng.normal(size=200))
    Xs = np.column_stack([X, rng.normal(size=200)])
    scale = HistGradientBoostingRegressor(max_iter=5, random_state=0).fit(Xs, 1.0 + rng.random(200))
    return hgb, scale


def _state(block, hours, seed=0, **over):
    width = 2 + 8 + 2 + len(ms.P3DH_EXTRA)
    entries = {}
    for h in hours:
        hgb, scale = _models(width, seed + h)
        mean = {"bias": {}, "bias_global": 0.5, "normal": {}, "normal_by_market": {}, "normal_global": 70.0,
                "doy": True, "ols": np.array([0.1, 0.9, 0.05]), "hgb": hgb, "extra_hgb": list(ms.P3DH_EXTRA),
                "extra_ols": []}
        entries[h] = {"mean": mean, "scale": scale, "z": np.linspace(-2, 2, 21),
                      "train_y": {m: [68, 70, 71, 72, 74] for m in MARKETS}}
    state = {"schema": ms.MG3_STATE_SCHEMA, "arm": "P3d_H", "block": block, "markets": list(MARKETS),
             "centres": ["2026-10-10", "2026-10-25"], "season_of": {f"{m:02d}": "s" for m in range(1, 13)},
             "coords": {m: (33.6, -84.4, 300.0) for m in MARKETS},
             "buckets": {m: list(range(50, 95)) for m in MARKETS},
             "constants": {"min_scale": 0.5, "clim_alpha": 0.1, "levels": ["high_so_far", "current_temp"]},
             "conversion": {"enabled": False, "rule_id": None}, "extra_hgb": list(ms.P3DH_EXTRA),
             "point_rule": {"rule": "x", "land_sha256": "22069bee" + "0" * 56 if block == "07-12" else None},
             "hours": entries}
    state.update(over)
    return state


def _write(path, obj):
    blob = pickle.dumps(obj)
    Path(path).write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def sm_h_dir(tmp_path, monkeypatch):
    d = tmp_path / "state_smh"
    d.mkdir()
    sha = _write(d / "p3d_h_state.pkl", _state(ms.SM_H_BLOCK, (13, 14, 15)))
    note = "6507946e" + "1" * 56
    control = {"block": ms.SM_H_BLOCK, "pass": True, "state_sha256": sha, "note_sha256": note,
               "checks": {"1_inputs": {"pass": True}, "2_export_parity": {"pass": True}}}
    (d / "control.json").write_text(json.dumps(control), encoding="utf-8")
    (d / "p3d_h_state.json").write_text(json.dumps({"block": ms.SM_H_BLOCK, "state_sha256": sha,
                                                    "note_sha256": note}), encoding="utf-8")
    monkeypatch.setattr(ms, "SM_H_STATE_SHA256", sha)
    monkeypatch.setattr(ms, "SM_H_CONTROL_SHA256", _sha(d / "control.json"))
    monkeypatch.setattr(ms, "SM_H_NOTE_SHA256", note)
    return d


# ----------------------------------------------------------------------------- state loaders

def test_p3dh_state_refuses_any_sha_or_shape_mismatch(tmp_path):
    p = tmp_path / "s.pkl"
    sha = _write(p, _state("07-12", range(7, 13)))
    assert ms.load_p3dh_state(p, sha, block="07-12", hours=tuple(range(7, 13)))["block"] == "07-12"
    with pytest.raises(ms.Mg3ServeError, match="sha256"):
        ms.load_p3dh_state(p, "0" * 64, block="07-12", hours=tuple(range(7, 13)))
    with pytest.raises(ms.Mg3ServeError, match="block"):
        ms.load_p3dh_state(p, sha, block=ms.SM_H_BLOCK, hours=tuple(range(7, 13)))
    with pytest.raises(ms.Mg3ServeError, match="hours"):
        ms.load_p3dh_state(p, sha, block="07-12", hours=(13, 14, 15))
    for bad in ({"schema": "mg2_p3d_n_state/1"}, {"arm": "P3d_N"}, {"extra_hgb": ["k_gap", "k_max", "k_tcdc"]}):
        q = tmp_path / "bad.pkl"
        s = _write(q, _state("07-12", range(7, 13), **bad))
        with pytest.raises(ms.Mg3ServeError):
            ms.load_p3dh_state(q, s, block="07-12", hours=tuple(range(7, 13)))
    st = _state("07-12", range(7, 13))
    st["hours"][9]["mean"]["extra_ols"] = ["k_max"]
    s = _write(tmp_path / "ols.pkl", st)
    with pytest.raises(ms.Mg3ServeError, match="hour 9"):
        ms.load_p3dh_state(tmp_path / "ols.pkl", s, block="07-12", hours=tuple(range(7, 13)))


def test_sm_h_loader_binds_control_sidecar_note_and_state(sm_h_dir, monkeypatch):
    state = ms.load_sm_h_state(sm_h_dir)
    assert state["block"] == ms.SM_H_BLOCK and sorted(state["hours"]) == [13, 14, 15]
    with pytest.raises(ms.Mg3ServeError, match="sha256"):
        ms.load_sm_h_state(sm_h_dir, state_sha256="0" * 64)
    with pytest.raises(ms.Mg3ServeError, match="control"):
        ms.load_sm_h_state(sm_h_dir, control_sha256="0" * 64)
    with pytest.raises(ms.Mg3ServeError, match="note"):
        ms.load_sm_h_state(sm_h_dir, note_sha256="0" * 64)


@pytest.mark.parametrize("edit", ["control_fail", "check_fail", "sidecar_state", "sidecar_block", "conversion"])
def test_sm_h_loader_refuses_a_failed_or_inconsistent_bundle(sm_h_dir, monkeypatch, edit):
    control = json.loads((sm_h_dir / "control.json").read_text(encoding="utf-8"))
    sidecar = json.loads((sm_h_dir / "p3d_h_state.json").read_text(encoding="utf-8"))
    if edit == "control_fail":
        control["pass"] = False
    elif edit == "check_fail":
        control["checks"]["2_export_parity"]["pass"] = False
    elif edit == "sidecar_state":
        sidecar["state_sha256"] = "0" * 64
    elif edit == "sidecar_block":
        sidecar["block"] = "13-16"
    else:
        sha = _write(sm_h_dir / "p3d_h_state.pkl", _state(ms.SM_H_BLOCK, (13, 14, 15),
                                                          conversion={"enabled": True, "rule_id": "x:half_up"}))
        control["state_sha256"] = sidecar["state_sha256"] = sha
        monkeypatch.setattr(ms, "SM_H_STATE_SHA256", sha)
    (sm_h_dir / "control.json").write_text(json.dumps(control), encoding="utf-8")
    (sm_h_dir / "p3d_h_state.json").write_text(json.dumps(sidecar), encoding="utf-8")
    monkeypatch.setattr(ms, "SM_H_CONTROL_SHA256", _sha(sm_h_dir / "control.json"))
    with pytest.raises(ms.Mg3ServeError):
        ms.load_sm_h_state(sm_h_dir)


@pytest.mark.skipif(not (REAL_SM_H / "p3d_h_state.pkl").exists(), reason="the frozen SM-H state is WS-local")
def test_real_sm_h_state_loads_against_the_bound_shas_read_only():
    before = {p.name: p.stat().st_mtime_ns for p in REAL_SM_H.iterdir()}
    state = ms.load_sm_h_state(REAL_SM_H)
    assert ms.SM_H_STATE_SHA256.startswith("b6bc242a") and ms.SM_H_CONTROL_SHA256.startswith("5a106a0d")
    assert ms.SM_H_NOTE_SHA256.startswith("6507946e")
    assert tuple(state["extra_hgb"]) == ms.P3DH_EXTRA and sorted(state["hours"]) == [13, 14, 15]
    assert {p.name: p.stat().st_mtime_ns for p in REAL_SM_H.iterdir()} == before


# ----------------------------------------------------------------------------- HRRR extras and the cutoff

TZ = "America/New_York"
DAY = "2026-08-10"


def _selection(hour=10, cycle="2026-08-10T12:00:00+00:00", latest="2026-08-10T13:40:00+00:00", fhs=(2, 3)):
    snap = pd.Timestamp(f"{DAY} {hour:02d}:00", tz=TZ).tz_convert("UTC").isoformat()
    return {"cycle_utc": cycle, "fhs": list(fhs), "latest_available_utc": latest, "snapshot_utc": snap,
            "hour_local": hour, "local_date": DAY, "station": "KATL"}


def _messages(cycle="2026-08-10T12:00:00+00:00", fhs=(2, 3), tmp_k=(300.0, 301.0), tcdc=(20.0, 40.0)):
    from datetime import datetime

    c = datetime.fromisoformat(cycle)
    out = []
    for fh, tk, tc in zip(fhs, tmp_k, tcdc):
        for var, value in (("TMP", tk), ("TCDC", tc)):
            block = [value + i for i in range(9)]
            block[4] = value
            out.append({"cycle_utc": cycle, "fh": fh, "key": ms.hrrr_message_key(c, fh),
                        "idx_record": f"{ms.HRRR_VARIABLES[var]}:{fh} hour fcst:",
                        "points": {"KATL": {"nearest": value, "block3x3": block}}})
    return out


def _raw(selection, messages, point=None, hour=10):
    return ms.hrrr_raw_path(selection, messages, icao="KATL", tz=TZ, local_date=DAY, hour=hour, point=point)


def test_hrrr_extras_cover_a_cycle_available_before_the_cutoff():
    e = _raw(_selection(), _messages())
    assert e["k_miss"] == 0.0 and e["reason"] is None
    assert e["k_max"] == pytest.approx((301.0 - 273.15) * 9 / 5 + 32) and e["k_tcdc"] == pytest.approx(30.0)
    cols = ms.hrrr_extra_columns(e, 80.0)
    assert list(cols) == list(ms.P3DH_EXTRA) and cols["k_gap"] == pytest.approx(cols["k_max"] - 80.0)
    assert math.isnan(ms.hrrr_extra_columns(e, float("nan"))["k_gap"])


@pytest.mark.parametrize("selection,messages,reason", [
    # 10:00 EDT = 14:00Z; a latest message at 13:50:01Z is inside the 10-minute margin: not usable at the cutoff.
    (dict(latest="2026-08-10T13:50:01+00:00"), {}, "pit_violation"),
    (dict(latest=None), {}, "pit_violation"),
    (dict(cycle=None), {}, "no_cycle"),
    (dict(fhs=()), {}, "no_cycle"),
    (dict(fhs=(1, 2)), {}, "window_violation"),  # 13:00Z valid time is before the 14:00Z snapshot
    (dict(), dict(tmp_k=(300.0, float("nan"))), "message_absent"),
    (dict(), dict(tmp_k=(500.0, 300.0)), "tmp_out_of_range"),
])
def test_hrrr_extras_miss_is_nan_with_its_reason(selection, messages, reason):
    e = _raw(_selection(**selection), _messages(**messages))
    assert e["k_miss"] == 1.0 and e["reason"] == reason
    assert all(math.isnan(v) for v in ms.hrrr_extra_columns(e, 80.0).values())


def test_hrrr_extras_refuse_a_mismatched_message_identity_and_a_shifted_snapshot():
    msgs = _messages()
    msgs[0]["key"] = "hrrr.20260810/conus/hrrr.t11z.wrfsfcf02.grib2"
    assert _raw(_selection(), msgs)["reason"] == "identity_mismatch"
    assert _raw(_selection(hour=11), _messages(), hour=10)["reason"] == "snapshot_mismatch"
    assert _raw(None, _messages())["reason"] == "no_selection"


def test_rn1_point_rule_reads_the_bound_block_index():
    binding = {"rn1": {"land_sha256": "x", "default_index": 4, "index": {"KSFO": 3}}}
    assert ms.rn1_point_map(binding, ["KATL", "KSFO"]) == {"KATL": 4, "KSFO": 3}
    nearest = _raw(_selection(), _messages())
    centre = _raw(_selection(), _messages(), point={"KATL": 4})
    west = _raw(_selection(), _messages(), point={"KATL": 3})
    assert centre["k_max"] == nearest["k_max"] and west["k_max"] == pytest.approx(nearest["k_max"] + 3 * 9 / 5)
    assert _raw(_selection(), _messages(), point={"KSFO": 3})["reason"] == "no_land_cell"
    for bad in ({}, {"rn1": {"index": {}}}, {"rn1": {"default_index": 4}}):
        with pytest.raises(ms.Mg3ServeError):
            ms.rn1_point_map(bad, ["KATL"])


def test_p3dh_x_appends_the_extras_in_state_order_and_serves_a_miss_as_nan():
    st = _state("07-12", range(7, 13))
    kw = dict(market="atlanta", target_date=date(2026, 8, 10), high_so_far=74.0, current_temp=73.0, nbm_mean=80.0)
    base, *_ = core.state_features(st, 10, **kw)
    X, *_ = ms.p3dh_X(st, 10, extra={"k_tcdc": 3.0, "k_max": 1.0, "k_gap": 2.0}, **kw)
    assert X.shape == (1, base.shape[1] + 3) and np.array_equal(X[:, :-3], base)
    assert X[0, -3:].tolist() == [1.0, 2.0, 3.0]
    for extra in ({"k_max": 81.0, "k_gap": 1.0, "k_tcdc": 30.0}, ms.hrrr_extra_columns(None, 80.0)):
        d = ms.p3dh_distribution(st, 10, extra=extra, **kw)
        assert sum(d.values()) == pytest.approx(1.0) and min(d) >= 74


# ----------------------------------------------------------------------------- blend weights and L6 partner

def _weights_file(tmp_path, shape):
    w = {"weights": {f"h{h:02d}": 0.5 + 0.03 * (h - 7) for h in range(7, 13)},
         "inputs": {"l6_part": RF1_PARTNER["part_sha256"], "nowcasts": FROZEN_NOWCASTS}}
    if shape == "rf1":
        w["checks"] = {"1_control": {"pass": True}, "2_identity": {"pass": True}, "3_coverage": {"pass": True}}
        w["inputs"]["season_nowcasts"] = RF1_PARTNER["nowcasts_sha256"]
    else:
        w["control"] = {"pass": True}
    p = tmp_path / f"weights_{shape}.json"
    p.write_text(json.dumps(w), encoding="utf-8")
    sha = _sha(p)
    Path(str(p) + ".sha256").write_text(f"{sha}  {p.name}\n", encoding="utf-8")
    return p, sha


def _binding(weights_sha, partner):
    return {"weights_sha256": weights_sha, "l6_partner": dict(partner)}


def test_rf1_weights_bind_to_the_season_matched_partner(tmp_path):
    p, sha = _weights_file(tmp_path, "rf1")
    w = ms.bind_blend_weights(_binding(sha, RF1_PARTNER), p)
    assert sorted(w) == list(range(7, 13)) and w[7] == pytest.approx(0.5)
    # RF-1 weights were fitted against the season nowcasts: a binding naming the frozen nowcasts refuses.
    with pytest.raises(ms.Mg3ServeError, match="l6_partner"):
        ms.bind_blend_weights(_binding(sha, {**RF1_PARTNER, "nowcasts_sha256": FROZEN_NOWCASTS}), p)


def test_a_binding_naming_the_frozen_weights_serves_exactly_those(tmp_path):
    p, sha = _weights_file(tmp_path, "frozen")
    frozen_partner = {**RF1_PARTNER, "nowcasts_sha256": FROZEN_NOWCASTS}
    assert ms.bind_blend_weights(_binding(sha, frozen_partner), p)[12] == pytest.approx(0.65)
    with pytest.raises(ms.Mg3ServeError, match="l6_partner"):
        ms.bind_blend_weights(_binding(sha, RF1_PARTNER), p)
    rf1, rf1_sha = _weights_file(tmp_path, "rf1")
    with pytest.raises(ms.Mg3ServeError, match="sha256"):  # the binding names c7b8ebc0-shape weights, not RF-1's
        ms.bind_blend_weights(_binding(sha, RF1_PARTNER), rf1)


@pytest.mark.parametrize("drop", ["weights_sha256", "l6_partner", "part_sha256", "nowcasts_sha256"])
def test_blend_binding_fields_never_default(tmp_path, drop):
    p, sha = _weights_file(tmp_path, "rf1")
    b = _binding(sha, RF1_PARTNER)
    if drop in b:
        del b[drop]
    else:
        del b["l6_partner"][drop]
    with pytest.raises(ms.Mg3ServeError, match="no default"):
        ms.bind_blend_weights(b, p)


@pytest.mark.parametrize("edit", ["sidecar_missing", "sidecar_wrong", "check_fails", "stopped", "hours", "range"])
def test_blend_weights_refuse_a_failed_or_malformed_file(tmp_path, edit):
    p, sha = _weights_file(tmp_path, "rf1")
    w = json.loads(p.read_text(encoding="utf-8"))
    side = Path(str(p) + ".sha256")
    if edit == "sidecar_missing":
        side.unlink()
    elif edit == "sidecar_wrong":
        side.write_text("0" * 64, encoding="utf-8")
    else:
        if edit == "check_fails":
            w["checks"]["3_coverage"]["pass"] = False
        elif edit == "stopped":
            w["stopped_at"] = "2_identity"
        elif edit == "hours":
            del w["weights"]["h12"]
        else:
            w["weights"]["h07"] = 1.5
        p.write_text(json.dumps(w), encoding="utf-8")
        sha = _sha(p)
        side.write_text(sha, encoding="utf-8")
    with pytest.raises(ms.Mg3ServeError):
        ms.bind_blend_weights(_binding(sha, RF1_PARTNER), p)


def test_l6_partner_part_and_distribution():
    part = {"coef": {str(h): [0.2, 0.5] for h in range(7, 13)}}
    sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    coef = ms.l6_part_coefficients(part, sha)
    assert coef[9] == (0.2, 0.5)
    with pytest.raises(ms.Mg3ServeError):
        ms.l6_part_coefficients(part, "0" * 64)
    with_n = ms.l6_distribution(coef, 9, v=80.0, s=2.0, floor=75.4, nowcast=84.0)
    without = ms.l6_distribution(coef, 9, v=80.0, s=0.4, floor=75.4, nowcast=float("nan"))
    assert sum(with_n.values()) == pytest.approx(1.0) and min(with_n) == 75 and min(without) >= 75
    mean = lambda d: sum(k * p for k, p in d.items())  # noqa: E731
    assert mean(with_n) == pytest.approx(80.0 + 0.2 + 0.5 * 4.0, abs=0.05)
    assert without == ms.l6_band_distribution(80.0, 1.0, 75.4)  # sigma floored at 1, MG-1 analogue without N
    assert ms.l6_distribution(coef, 9, v=None, s=2.0, floor=75.0, nowcast=None) is None
    dead = ms.l6_band_distribution(20.0, 1.0, 75.0)
    assert dead == {75: 1.0}
    m = ms.mix({1: 0.5, 2: 0.5}, {2: 1.0}, 0.25)
    assert m == {1: 0.125, 2: 0.875}


# ----------------------------------------------------------------------------- the binding and the hour table

def _mg3_binding(weights_sha, partner, land="22069bee" + "0" * 56, **smh):
    block = {"sha256": ms.SM_H_STATE_SHA256, "point_rule": "nearest", "hours": [13, 14, 15],
             "excluded_markets": ["san-francisco"]}
    block.update(smh)
    return {"schema": "mg3_release_binding/1", "weights_sha256": weights_sha, "l6_partner": dict(partner),
            "rn1": {"land_sha256": land, "default_index": 4, "index": {"KSFO": 3}},
            "states": {"07-12": {"sha256": None, "point_rule": "rn1"}, ms.SM_H_BLOCK: block}}


def test_every_hour_table_refusal_refuses_the_serve():
    good = _mg3_binding("w", RF1_PARTNER)
    table = {h: ms.serve_arm(good, "atlanta", h) for h in range(24)}
    assert table == {**{h: mg3_arms.ARM_MG2 for h in range(24)},
                     **{h: mg3_arms.ARM_BLEND_0712 for h in range(7, 13)},
                     **{h: mg3_arms.ARM_SM_H for h in (13, 14, 15)}}
    assert [ms.serve_arm(good, "san-francisco", h) for h in (13, 14, 15)] == [mg3_arms.ARM_MG2] * 3
    bad_bindings = [{"states": {}}, {}, None, _mg3_binding("w", RF1_PARTNER, hours=[13, 14]),
                    _mg3_binding("w", RF1_PARTNER, excluded_markets="san-francisco")]
    no_excl = _mg3_binding("w", RF1_PARTNER)
    del no_excl["states"][ms.SM_H_BLOCK]["excluded_markets"]
    for b in bad_bindings + [no_excl]:
        for h in (3, 9, 14):
            with pytest.raises(ms.Mg3ServeError, match="hour table refused"):
                ms.serve_arm(b, "atlanta", h)
    for market, hour in (("atlanta", 24), ("atlanta", -1), ("atlanta", True), ("", 9), (None, 9)):
        with pytest.raises(ms.Mg3ServeError):
            ms.serve_arm(good, market, hour)


def _l6_state(tmp_path):
    from sklearn.linear_model import LinearRegression

    rng = np.random.default_rng(3)
    model = LinearRegression().fit(rng.normal(size=(50, len(core.L6_OWN_COLUMNS))), rng.normal(size=50))
    p = tmp_path / "l6_own_state.pkl"
    sha = _write(p, {"schema": core.L6_STATE_SCHEMA, "columns": list(core.L6_OWN_COLUMNS), "model": model})
    return p, sha


def _serve_files(tmp_path, shape):
    s0712 = tmp_path / "state_0712.pkl"
    sha0712 = _write(s0712, _state("07-12", range(7, 13), seed=50))
    weights, wsha = _weights_file(tmp_path, shape)
    l6p, l6sha = _l6_state(tmp_path)
    part = {"coef": {str(h): [0.1, 0.6] for h in range(7, 13)}}
    part_sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    nowcasts = RF1_PARTNER["nowcasts_sha256"] if shape == "rf1" else FROZEN_NOWCASTS
    w = json.loads(weights.read_text(encoding="utf-8"))
    w["inputs"]["l6_part"] = part_sha
    weights.write_text(json.dumps(w), encoding="utf-8")
    wsha = _sha(weights)
    Path(str(weights) + ".sha256").write_text(wsha, encoding="utf-8")
    partner = {"state_sha256": l6sha, "part_sha256": part_sha, "nowcasts_sha256": nowcasts}
    binding = _mg3_binding(wsha, partner)
    binding["states"]["07-12"]["sha256"] = sha0712
    return binding, dict(state_0712_path=s0712, weights_path=weights, l6_state_path=l6p, l6_part=part)


@pytest.mark.parametrize("shape", ["rf1", "frozen"])
def test_load_serve_reads_every_part_from_the_binding(tmp_path, sm_h_dir, shape):
    binding, files = _serve_files(tmp_path, shape)
    serve = ms.load_serve(binding, sm_h_dir=sm_h_dir, **files)
    assert serve.weights == ms.bind_blend_weights(binding, files["weights_path"])
    assert serve.sm_h_state["block"] == ms.SM_H_BLOCK and serve.state_0712["block"] == "07-12"
    assert sorted(serve.l6_coef) == list(range(7, 13))


@pytest.mark.parametrize("edit", ["state_0712_sha", "sm_h_sha", "point_rule", "land", "l6_state", "part",
                                  "no_partner", "no_states", "smh_point_rule", "smh_block"])
def test_load_serve_refuses_any_mismatch(tmp_path, sm_h_dir, edit):
    binding, files = _serve_files(tmp_path, "rf1")
    if edit == "state_0712_sha":
        binding["states"]["07-12"]["sha256"] = "0" * 64
    elif edit == "sm_h_sha":
        binding["states"][ms.SM_H_BLOCK]["sha256"] = "b6bc242a" + "0" * 56
    elif edit == "point_rule":
        binding["states"]["07-12"]["point_rule"] = "nearest"
    elif edit == "land":
        binding["rn1"]["land_sha256"] = "0" * 64
    elif edit == "l6_state":
        binding["l6_partner"]["state_sha256"] = "800072c7" + "0" * 56
    elif edit == "part":
        files["l6_part"] = {"coef": {str(h): [0.0, 0.0] for h in range(7, 13)}}
    elif edit == "no_partner":
        del binding["l6_partner"]
    elif edit == "no_states":
        del binding["states"]
    elif edit == "smh_point_rule":
        binding["states"][ms.SM_H_BLOCK]["point_rule"] = "rn1"
    else:
        del binding["states"][ms.SM_H_BLOCK]["excluded_markets"]
    with pytest.raises(ms.Mg3ServeError):
        ms.load_serve(binding, sm_h_dir=sm_h_dir, **files)


def test_blend_serves_w_p3dh_plus_one_minus_w_l6(tmp_path, sm_h_dir):
    binding, files = _serve_files(tmp_path, "rf1")
    serve = ms.load_serve(binding, sm_h_dir=sm_h_dir, **files)
    kw = dict(market="atlanta", target_date=date(2026, 8, 10), high_so_far=74.0, current_temp=73.0, nbm_mean=80.0,
              extra={"k_max": 81.0, "k_gap": 1.0, "k_tcdc": 30.0})
    got = ms.arm_distribution(serve, mg3_arms.ARM_BLEND_0712, hour=9, mg1=(80.0, 2.0, 74.0), l6_nowcast=82.0, **kw)
    p = ms.p3dh_distribution(serve.state_0712, 9, **kw)
    q = ms.l6_distribution(serve.l6_coef, 9, v=80.0, s=2.0, floor=74.0, nowcast=82.0)
    assert got == ms.mix(p, q, serve.weights[9]) and sum(got.values()) == pytest.approx(1.0)
    assert ms.arm_distribution(serve, mg3_arms.ARM_BLEND_0712, hour=9, mg1=None, **kw) is None
    assert ms.arm_distribution(serve, mg3_arms.ARM_SM_H, hour=14, **kw) == ms.p3dh_distribution(
        serve.sm_h_state, 14, **kw)
    with pytest.raises(ms.Mg3ServeError):
        ms.arm_distribution(serve, mg3_arms.ARM_MG2, hour=3, **kw)


# ----------------------------------------------------------------------------- SF end-to-end through mg_serve_core

FLOOR_FIELDS = ("high_so_far",)


def _snaps_bands(hours):
    snaps, bands = [], []
    for market in MARKETS:
        for h in hours:
            rk = f"{market}|2026-08-10|{h:02d}"
            snaps.append({"row_key": rk, "market": market, "local_hour": h, "high_so_far": 70.0 + h / 4})
            lo = 66
            bands.append({"row_key": rk, "band_index": 0, "kind": "lte", "low": lo, "high": lo})
            for j in range(1, 7):
                bands.append({"row_key": rk, "band_index": j, "kind": "eq", "low": lo + 2 * j - 1,
                              "high": lo + 2 * j})
            bands.append({"row_key": rk, "band_index": 7, "kind": "gte", "low": lo + 13, "high": lo + 13})
    return pd.DataFrame(snaps), pd.DataFrame(bands)


def _frame(snaps, bands, seed):
    rng = np.random.default_rng(seed)
    rows = []
    for rk in snaps.row_key:
        b = bands[bands.row_key == rk]
        p = rng.random(len(b))
        rows += [{"row_key": rk, "band_index": int(i), "p": float(x)} for i, x in zip(b.band_index, p / p.sum())]
    return pd.DataFrame(rows)


def test_sf_at_13_15_serves_mg2_end_to_end_through_the_serve_core(tmp_path, sm_h_dir):
    hours = list(range(24))
    snaps, bands = _snaps_bands(hours)
    pre, post, mg1 = _frame(snaps, bands, 1), _frame(snaps, bands, 2), _frame(snaps, bands, 3)
    mg2_frame, mg2_source = core.compose(snaps, bands, pre, post, mg1, FLOOR_FIELDS)
    binding, files = _serve_files(tmp_path, "rf1")
    serve = ms.load_serve(binding, sm_h_dir=sm_h_dir, **files)
    dists = {mg3_arms.ARM_SM_H: {}, mg3_arms.ARM_BLEND_0712: {}}
    for rk, market, h, F in zip(snaps.row_key, snaps.market, snaps.local_hour, snaps.high_so_far):
        arm = ms.serve_arm(binding, market, int(h))
        if arm == mg3_arms.ARM_MG2:
            continue
        kw = dict(market=market, hour=int(h), target_date=date(2026, 8, 10), high_so_far=F, current_temp=F - 1,
                  nbm_mean=80.0, extra=ms.hrrr_extra_columns(None, 80.0))
        dists[arm][rk] = ms.arm_distribution(serve, arm, mg1=(80.0, 2.0, F), l6_nowcast=81.0, **kw)
    frame, source = ms.compose_mg3(binding, snaps, bands, mg2_frame, mg2_source, dists)

    def rows(f, rk):
        return f[f.row_key == rk].reset_index(drop=True)

    for h in (13, 14, 15):
        sf, atl = f"san-francisco|2026-08-10|{h:02d}", f"atlanta|2026-08-10|{h:02d}"
        pd.testing.assert_frame_equal(rows(frame, sf), rows(mg2_frame, sf))
        assert source[sf] == f"{mg3_arms.ARM_MG2}:{mg2_source[sf]}"
        assert source[atl] == mg3_arms.ARM_SM_H and sf not in dists[mg3_arms.ARM_SM_H]
        want = core.distribution_band_frame({atl: dists[mg3_arms.ARM_SM_H][atl]}, bands)
        pd.testing.assert_frame_equal(rows(frame, atl), rows(want, atl))
    for market in MARKETS:
        for h in range(7, 13):
            assert source[f"{market}|2026-08-10|{h:02d}"] == mg3_arms.ARM_BLEND_0712
        for h in (*range(7), 16, *range(17, 24)):
            rk = f"{market}|2026-08-10|{h:02d}"
            pd.testing.assert_frame_equal(rows(frame, rk), rows(mg2_frame, rk))
            assert source[rk].startswith(mg3_arms.ARM_MG2)


def test_a_missing_mg3_arm_output_is_none_never_another_arm(tmp_path):
    snaps, bands = _snaps_bands([9, 14])
    pre, post, mg1 = _frame(snaps, bands, 1), _frame(snaps, bands, 2), _frame(snaps, bands, 3)
    mg2_frame, mg2_source = core.compose(snaps, bands, pre, post, mg1, FLOOR_FIELDS)
    binding = _mg3_binding("w", RF1_PARTNER)
    frame, source = ms.compose_mg3(binding, snaps, bands, mg2_frame, mg2_source, {})
    for rk in ("atlanta|2026-08-10|09", "atlanta|2026-08-10|14", "san-francisco|2026-08-10|09"):
        assert source[rk] == "none" and rk not in set(frame.row_key)
    sf = "san-francisco|2026-08-10|14"
    assert source[sf].startswith(mg3_arms.ARM_MG2) and sf in set(frame.row_key)
    with pytest.raises(ms.Mg3ServeError):
        ms.compose_mg3({"states": {}}, snaps, bands, mg2_frame, mg2_source, {})
