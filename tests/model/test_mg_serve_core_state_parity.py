"""C2: P3d_N serve parity on frozen states, three implementations, exact.

Guards: plan C:\\t\\l3\\neutral\\plan.md (sha 83707862...) section (c) C2, and master ruling D2 (iii) of 2026-10-26.
There are two P3d_N serve copies: the MG-2-bound ``mg2_p3d_n.serve_distribution`` (the reference) and
``pooled_residual_model.state_distribution``. If they differ at all, the core move stops. The core's
``state_distribution`` must equal ``pooled_residual_model.state_distribution`` exactly.

The grid is deterministic: every market and fitted hour of the state, three target dates, and T-group high_so_far
values at -6, -3, -1, 0, +1, +3 and +6 F around the hour's market normal. current_temp sits 0 or 2 F below it, and
nbm_mean is finite or NaN. Distributions are compared key-for-key with float equality and no tolerance.

States:

* the golden synthetic state (as ``tests/calibration/test_mg2_p3d_n.py`` builds it);
* L2's frozen forward state (conversion on), when present and only at its bound sha;
* the MG-2 dev control state (conversion off), when present and only at its bound sha.

The pickles are local runtime evidence (fits on pre-cutoff data). No outcome is read.
"""
from __future__ import annotations

import hashlib
import math
import pickle
from datetime import date
from pathlib import Path

import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.model import mg_serve_core as core

p3 = import_or_skip_on_capture_host("weather.calibration.mg2_p3d_n")
prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")

FORWARD_STATE = Path(r"C:\t\l2\forward\state\p3d_n_state.pkl")
FORWARD_STATE_SHA = "c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780"  # L2 Clarification 3
DEV_STATE = Path(r"C:\t\mg2\p3d_n_ctl\state\p3d_n_state.pkl")
DEV_STATE_SHA = "dff5d7975fa7a18278f8e500e4e0bcdd768c5d05dc4caf8b8e08332dad1a6574"  # MG-2 dev control state
TARGET_DATES = (date(2026, 8, 15), date(2026, 9, 20), date(2026, 11, 2))
OFFSETS = (-6, -3, -1, 0, 1, 3, 6)


def _tgroup(value_f):
    """The T-group grid value (32 + 9t/50) nearest ``value_f``."""
    return 32 + 9 * round((value_f - 32) * 50 / 9) / 50


def _golden_state():
    from tests.calibration.test_mg2_p3d_n import _fit_pooled

    frame = p3.golden_frame()
    fits = {}
    for hour in p3.GOLDEN_HOURS:
        train = frame[frame.hour == hour].reset_index(drop=True)
        fits[(hour, None)] = {"fit": _fit_pooled(train),
                              "train_y": {m: [int(v) for v in train.loc[train.market == m, "y"]]
                                          for m in train.market.unique()}}
    return p3.state_from_fits(
        fits, {m: list(range(60, 111)) for m in p3.GOLDEN_MARKETS}, frame_columns=set(frame.columns),
        markets=p3.GOLDEN_MARKETS, centres=p3.GOLDEN_CENTRES, season_of={f"{m:02d}": "aug_sep" for m in range(1, 13)},
        coords={m: (30.0 + i, -90.0 - 5 * i, 100.0 * i) for i, m in enumerate(p3.GOLDEN_MARKETS)}, fit_kind="dev",
        provenance={"commit": "test"})


def _load(path, sha):
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    assert digest == sha, f"{path} sha {digest} is not the bound state"
    return pickle.loads(blob)


def _grid(state):
    for hour in sorted(state["hours"]):
        mean = state["hours"][hour]["mean"]
        for market in state["markets"]:
            normal = mean["normal_by_market"].get(market, mean["normal_global"])
            for target in TARGET_DATES:
                for off in OFFSETS:
                    hs = _tgroup(normal + off)
                    for drop in (0, 2):
                        for nbm in (normal + 1.3, float("nan")):
                            yield {"hour": hour, "market": market, "target_date": target, "high_so_far": hs,
                                   "current_temp": _tgroup(hs - drop), "nbm_mean": nbm}


def _diff(a, b):
    if a is None or b is None:
        return "one side is None"
    if set(a) != set(b):
        return f"keys differ: {sorted(set(a) ^ set(b))}"
    bad = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
    return f"{len(bad)} buckets differ, max |dp| {max(abs(x - y) for x, y in bad.values()):.3e}" if bad else None


def _check(state):
    n = 0
    for case in _grid(state):
        hour = case.pop("hour")
        ref = p3.serve_distribution(state, hour=hour, **case)
        old = prm.state_distribution(state, hour, **case)
        new = core.state_distribution(state, hour, **case)
        assert _diff(new, old) is None, (hour, case, _diff(new, old))
        assert _diff(ref, old) is None, ("MG-2 bound copy != prm.state_distribution: STOP", hour, case, _diff(ref, old))
        n += 1
    assert n > 0
    return n


def test_state_parity_on_the_golden_state():
    state = _golden_state()
    assert not any(e["mean"]["x_columns"] or e["mean"]["market_id"] for e in state["hours"].values())
    assert _check(state) == len(p3.GOLDEN_HOURS) * len(p3.GOLDEN_MARKETS) * len(TARGET_DATES) * len(OFFSETS) * 4
    conv = dict(state, conversion={"enabled": True, "rule_id": "wu_whole_f_tgroup:half_up", "rule": "test"})
    _check(conv)


@pytest.mark.skipif(not FORWARD_STATE.exists(), reason="L2's frozen forward state is local runtime evidence")
def test_state_parity_on_the_frozen_forward_state():
    state = _load(FORWARD_STATE, FORWARD_STATE_SHA)
    assert state["conversion"]["enabled"]
    _check(state)


@pytest.mark.skipif(not DEV_STATE.exists(), reason="the MG-2 dev control state is local runtime evidence")
def test_state_parity_on_the_dev_control_state():
    state = _load(DEV_STATE, DEV_STATE_SHA)
    _check(state)


def test_the_states_constants_are_the_cores():
    """``state_distribution`` reads the kernel and mix constants from the module; the states must agree."""
    for path, sha in ((FORWARD_STATE, FORWARD_STATE_SHA), (DEV_STATE, DEV_STATE_SHA)):
        if not path.exists():
            continue
        c = _load(path, sha)["constants"]
        assert (c["kernel_bandwidth"], c["floor_mix_clim"], c["min_scale"]) == (
            core.KERNEL_BANDWIDTH, core.FLOOR_MIX_CLIM, core.MIN_SCALE)
    assert math.isclose(core.FLOOR_MIX_CLIM, 0.02)
