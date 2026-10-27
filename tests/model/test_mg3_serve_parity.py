"""Train/serve parity: weather.model.mg3_serve against the research code the MG-3 states were fitted with.

Guards: train/serve feature parity (AGENTS.md model contract) for MG-3's P3d_H serve (rule_mg3_p3dh_state.md s2)
and its HRRR extras (R-K raw path, R-R RN-1 point rule, the 10-minute availability margin before the snapshot,
the 17:00 valid-window end). The serve copies must equal the research sources exactly on synthetic inputs, and on
L2's frozen states when they are present on this workstation (read-only). WS-only: the research module refuses the
capture host, so this module skips there; the synthetic tests in test_mg3_serve.py carry the coverage in CI.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest

from tests.host_guard import import_or_skip_on_capture_host
from tests.model.test_mg3_serve import _messages, _state
from weather.model import mg3_serve as ms

prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")

REAL = {"07-12": (Path("C:/t/l2/mg3/state_0712/p3d_h_state.pkl"),
                  "e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0", tuple(range(7, 13))),
        ms.SM_H_BLOCK: (Path("C:/t/l2/mg3/state_smh/p3d_h_state.pkl"), ms.SM_H_STATE_SHA256, (13, 14, 15))}
INPUTS = [dict(market="atlanta", target_date=date(2026, 8, 10), high_so_far=74.0, current_temp=73.0, nbm_mean=80.0),
          dict(market="atlanta", target_date=date(2025, 11, 20), high_so_far=55.0, current_temp=55.0, nbm_mean=None),
          dict(market="san-francisco", target_date=date(2026, 9, 1), high_so_far=63.2, current_temp=61.0,
               nbm_mean=66.5)]
EXTRAS = [{"k_max": 81.0, "k_gap": 1.0, "k_tcdc": 30.0}, {"k_max": math.nan, "k_gap": math.nan, "k_tcdc": math.nan}]


def _same(a, b):
    assert set(a) == set(b)
    assert all(abs(a[k] - b[k]) == 0.0 for k in a), max(abs(a[k] - b[k]) for k in a)


@pytest.mark.parametrize("block,hours", [("07-12", range(7, 13)), (ms.SM_H_BLOCK, (13, 14, 15))])
def test_p3dh_serve_equals_the_research_state_distribution_on_a_synthetic_state(block, hours):
    st = _state(block, tuple(hours), seed=11)
    for h in hours:
        for kw in INPUTS:
            for extra in EXTRAS:
                X, *_ = ms.p3dh_X(st, h, extra=extra, **kw)
                Xr, *_ = prm.mg3_state_X(st, h, extra=extra, **kw)
                np.testing.assert_array_equal(X, Xr)
                _same(ms.p3dh_distribution(st, h, extra=extra, **kw),
                      prm.mg3_state_distribution(st, h, extra=extra, **kw))


@pytest.mark.parametrize("block", sorted(REAL))
def test_p3dh_serve_equals_the_research_math_on_the_frozen_state(block):
    path, sha, hours = REAL[block]
    if not path.exists():
        pytest.skip(f"L2's frozen {block} state is WS-local")
    st = ms.load_p3dh_state(path, sha, block=block, hours=hours)
    for h in hours:
        for kw in INPUTS:
            for extra in EXTRAS:
                _same(ms.p3dh_distribution(st, h, extra=extra, **kw),
                      prm.mg3_state_distribution(st, h, extra=extra, **kw))


# ----------------------------------------------------------------------------- HRRR extras vs the training columns

def _corpus(tmp_path):
    """A small L13-shaped corpus: two stations, hour 10 on four days, each day a different case."""
    stations = {"KATL": {"market": "atlanta", "tz": "America/New_York"},
                "KSFO": {"market": "san-francisco", "tz": "America/Los_Angeles"}}
    (tmp_path / "stations.json").write_text(json.dumps(stations), encoding="utf-8")
    manifest, selections = [], []
    cases = {"2026-08-10": "covered", "2026-08-11": "pit", "2026-08-12": "window", "2026-08-13": "absent",
             "2026-08-14": "no_cycle"}
    for day, case in cases.items():
        for icao, tz, offset in (("KATL", "America/New_York", 4), ("KSFO", "America/Los_Angeles", 7)):
            snap_h = 10 + offset
            cycle = f"{day}T{snap_h - 2:02d}:00:00+00:00"
            fhs = (2, 3) if case != "window" else (1, 2)
            latest = f"{day}T{snap_h - 1:02d}:{51 if case == 'pit' else 40}:00+00:00"
            selections.append({"station": icao, "local_date": day, "hour_local": 10,
                               "snapshot_utc": f"{day}T{snap_h:02d}:00:00+00:00",
                               "cycle_utc": None if case == "no_cycle" else cycle, "fhs": [] if case == "no_cycle"
                               else list(fhs), "latest_available_utc": latest})
            if case == "no_cycle":
                continue
            msgs = _messages(cycle=cycle, fhs=fhs, tmp_k=(295.0 + offset, 296.5 + offset),
                             tcdc=(10.0 * offset, 5.0))
            for m in msgs:
                m["points"] = {icao: m["points"]["KATL"]}
                if case == "absent" and m["fh"] == fhs[-1] and m["idx_record"].startswith("TCDC"):
                    continue
                manifest.append(m)
    with open(tmp_path / "manifest.jsonl", "w", encoding="utf-8") as f:
        merged = {}
        for m in manifest:  # one manifest record per message, with both stations' points
            k = (m["cycle_utc"], m["fh"], m["idx_record"])
            merged.setdefault(k, {**m, "points": {}})["points"].update(m["points"])
        f.writelines(json.dumps(m) + "\n" for m in merged.values())
    with open(tmp_path / "selections.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(s) + "\n" for s in selections)
    return stations, list(merged.values()), selections


@pytest.mark.parametrize("point", [None, {"KATL": 4, "KSFO": 3}, {"KATL": 2}])
def test_hrrr_extras_equal_the_training_columns(tmp_path, point):
    stations, manifest, selections = _corpus(tmp_path)
    train, _ = prm.rk_hrrr_columns(tmp_path, ("atlanta", "san-francisco"), hours=(10,), point=point)
    reasons = set()
    for s in selections:
        market = stations[s["station"]]["market"]
        msgs = [m for m in manifest if m["cycle_utc"] == s["cycle_utc"]]
        got = ms.hrrr_raw_path(s, msgs, icao=s["station"], tz=stations[s["station"]]["tz"],
                               local_date=s["local_date"], hour=10, point=point)
        want = train[(market, s["local_date"], 10)]
        reasons.add(got["reason"])
        assert got["reason"] == want["reason"] and got["k_miss"] == want["k_miss"]
        for c in ("k_max", "k_tcdc"):
            assert (math.isnan(got[c]) and math.isnan(want[c])) or got[c] == want[c]
        for nbm in (80.0, math.nan, None):
            serve = ms.hrrr_extra_columns(got, nbm)
            fit = prm.rk_columns(want, nbm)
            for c in ms.P3DH_EXTRA:
                assert (math.isnan(serve[c]) and math.isnan(fit[c])) or serve[c] == fit[c]
    assert {"pit_violation", "window_violation", "message_absent", "no_cycle"} <= reasons
    assert None in reasons and (("no_land_cell" in reasons) == (point is not None and "KSFO" not in point))


def test_hrrr_constants_equal_the_fitted_rule():
    assert ms.HRRR_VARIABLES == prm.RK_VARIABLES and ms.HRRR_MARGIN_S == prm.RK_MARGIN_S
    assert ms.HRRR_VALID_END_LOCAL == prm.RK_VALID_END_LOCAL and ms.HRRR_TMP_RANGE_F == prm.RK_TMP_RANGE_F
    assert ms.P3DH_EXTRA == tuple(prm.RK_ARMS["P3d_H"]["extra_hgb"]) and ms.MG3_STATE_SCHEMA == prm.MG3_STATE_SCHEMA
    c = datetime.fromisoformat("2026-08-10T12:00:00+00:00")
    assert ms.hrrr_message_key(c, 3) == prm.rk_message_key(c, 3)
