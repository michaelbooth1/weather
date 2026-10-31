"""The L11 market blend: log pool identities, walk-forward w fitting, placebo shuffle and admission.

Guards: L11 pre-registration ``C:\\t\\l11\\rule.md`` (sha256 e29c9a84395d...; copy under
docs/research/market-blend-l11-2026-10-25/): w = 0 is the market exactly, the hard floor applies for w > 0,
mass is the market's own, w is fitted on dates <= d - 2 only, ties go to the smaller w; the placebo is a
date derangement within (market, hour); master pre-authorisation 2026-10-24 (a lane allowlists its own
offline research module in both mirrors with a pinning test); each blend vs the market only.
"""
import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

mb = import_or_skip_on_capture_host("weather.calibration.market_blend")

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.market_blend"
SOURCE = ROOT / "src/weather/calibration/market_blend.py"


def _two_snapshots():
    m = np.array([0.30, 0.50, 0.25, 0.10, 0.60, 0.35])        # market sums 1.05 and 1.05
    c = np.array([0.00, 0.70, 0.30, 0.00, 0.20, 0.80])        # candidate, floored zero in band 0 / 3
    imp = np.array([True, False, False, True, False, False])
    snap = np.repeat([0, 1], 3)
    return m, c, imp, snap


def test_w0_is_the_market_exactly_and_floor_only_applies_for_positive_w():
    m, c, imp, snap = _two_snapshots()
    assert np.array_equal(mb.pool(m, c, 0.0, imp, snap, 2), m)
    b = mb.pool(m, c, 0.01, imp, snap, 2)
    assert (b[imp] == 0).all()
    np.testing.assert_allclose(np.bincount(snap, weights=b), np.bincount(snap, weights=m))
    f = mb.pool(m, c, 0.0, imp, snap, 2, force_floor=True)
    assert (f[imp] == 0).all()
    np.testing.assert_allclose(f[~imp], m[~imp] * (1.05 / (1.05 - np.where(imp, m, 0).reshape(2, 3).sum(1)))
                               [snap][~imp])


def test_w1_is_the_floored_candidate_at_market_mass_and_eps_is_one_value():
    m, c, imp, snap = _two_snapshots()
    b = mb.pool(m, c, 1.0, imp, snap, 2)
    cand = np.where(imp, 0.0, np.maximum(c, mb.EPS))
    np.testing.assert_allclose(b, cand / np.bincount(snap, weights=cand)[snap] * 1.05)
    assert mb.EPS == 1e-4
    with pytest.raises(Exception):
        mb.pool(m, c, -0.1, imp, snap, 2)


def test_walk_forward_uses_dates_up_to_d_minus_2_and_ties_go_to_smaller_w():
    grid = np.array([0.0, 0.5, 1.0])
    dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
    # cell on 08-01 prefers w=1, on 08-02 strongly prefers w=0.5, on 08-03 prefers 0
    vals = np.array([[3.0, 0.0, 0.0], [2.0, -9.0, 5.0], [1.0, 5.0, 9.0]])
    wf = mb.walk_forward_w(vals, dates, ["a"] * 3, ["2026-08-03", "2026-08-04", "2026-08-05"], w_grid=grid)
    assert wf["2026-08-03"] == (1.0, 1)          # only 08-01 is <= d-2
    assert wf["2026-08-04"] == (0.5, 2)          # 08-01, 08-02
    assert wf["2026-08-05"][1] == 3
    tie = mb.walk_forward_w(np.array([[1.0], [1.0], [1.0]]), ["2026-08-01"], ["a"], ["2026-08-05"], w_grid=grid)
    assert tie["2026-08-05"] == (0.0, 1)
    none = mb.walk_forward_w(vals, dates, ["a"] * 3, ["2026-08-02"], w_grid=grid)
    assert none["2026-08-02"] == (0.0, 0)
    only_b = mb.walk_forward_w(vals, dates, ["a", "b", "a"], ["2026-08-05"], markets=("b",), w_grid=grid)
    assert only_b["2026-08-05"] == (0.5, 1)


def test_placebo_is_a_date_derangement_within_market_and_hour():
    rows = []
    for d in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"):
        for mk in ("a", "b"):
            for k in range(2 if d != "2026-08-02" else 1):
                rows.append({"date": d, "market": mk, "local_hour": 8, "captured_at_utc": f"{d}T12:0{k}:00Z",
                             "row_key": f"{d}|{mk}|{k}"})
    snaps = pd.DataFrame(rows)
    n = np.full(len(snaps), 3)
    t = SimpleNamespace(snaps=snaps, markets=snaps.market.to_numpy(), local_hour=snaps.local_hour.to_numpy(),
                        n=n, offsets=np.arange(len(snaps)) * 3, bands=np.zeros(3 * len(snaps)))
    p = np.arange(3 * len(snaps), dtype=float)
    q, meta = mb.placebo_vector(t, p)
    assert meta["same_date_donors"] == 0 and meta["unshuffled_snapshots"] == 0
    src = (q[::3] / 3).astype(int)
    assert (snaps.market.to_numpy()[src] == snaps.market.to_numpy()).all()
    assert (snaps.date.to_numpy()[src] != snaps.date.to_numpy()).all()
    q2, _ = mb.placebo_vector(t, p)
    assert np.array_equal(q, q2)


def test_reading_rule_is_the_pre_registered_one():
    row = {"R": 0.98, "ci95_crossed": [0.96, 0.995], "ci95_date": [0.97, 0.99]}
    assert mb.reading(0.2, row, 0.999, True).startswith("INFORMATION")
    assert mb.reading(0.01, row, 0.999, True).startswith("NOTHING")
    assert mb.reading(0.2, row, 0.97, True).startswith("INCONCLUSIVE")
    assert mb.reading(0.2, dict(row, ci95_crossed=[0.95, 1.01]), 0.999, True).startswith("INCONCLUSIVE")
    assert mb.reading(0.2, dict(row, R=1.05, ci95_crossed=[1.01, 1.1]), 0.999, True).startswith("HARM")
    assert mb.reading(0.2, row, 0.999, False).startswith("NOT INTERPRETABLE")


def test_lead1_arm_a_and_missing_refit_marker_are_refused(tmp_path):
    vec = tmp_path / "armA_refit.jsonl"
    vec.write_text("{}\n", encoding="utf-8")
    with pytest.raises(mb.data.Refused, match="lead-1"):
        mb.check_arm_a_refit(str(tmp_path / "dev_l8_high_so_far_ols_floor.jsonl"), "x", tmp_path / "m.json")
    with pytest.raises(mb.data.Refused, match="does not exist"):
        mb.check_arm_a_refit(str(vec), "x", tmp_path / "missing.json")
    marker = tmp_path / "control_refit_armA.json"
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(mb.data.Refused, match="sha256"):
        mb.check_arm_a_refit(str(vec), "0" * 64, marker)
    assert mb.check_arm_a_refit(str(vec), mb.data.sha256_file(vec), marker) == mb.data.sha256_file(vec)


def test_constants_match_the_rule_and_no_cross_candidate_delta():
    assert mb.RULE_SHA256.startswith("e29c9a84395d")
    assert mb.W_GRID[0] == 0.0 and mb.W_GRID[-1] == 1.0 and len(mb.W_GRID) == 101
    assert mb.GAP_DAYS == 1 and mb.PRIMARY_FIT == "07-12"
    assert [b[0] for b in mb.FIT_BLOCKS] == ["07-12", "06-09", "10-12", "12-16", "13-16"]
    assert mb.BURN_IN == ("2026-08-01", "2026-08-14") and mb.RANGE[1] == "2026-09-29"
    text = SOURCE.read_text(encoding="utf-8")
    assert "p_l6_fit - p_" not in text and "p_mg1 - p_" not in text
    tree = ast.parse(text)
    assert any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
               and ast.unparse(n.value) == "la.refuse_production_import()" for n in tree.body)


def _hook():
    spec = importlib.util.spec_from_file_location("mb_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_admitted_once_in_both_mirrors_and_nothing_wider():
    # Mirror equality with Get-WeatherWorkstationOfflineModule is proved by executing it in
    # tests/operations/test_loss_atlas_admission.py; here the hook mirror pins this module.
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration.market"):
        assert near not in hook._OFFLINE_WEATHER_MODULES


def test_pre13_captured_refuses_unpinned_module_or_nowcasts(tmp_path):
    from types import SimpleNamespace

    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard_data as data

    mod, now = tmp_path / "m.py", tmp_path / "n.parquet"
    mod.write_text("x = 1\n")
    now.write_bytes(b"n")
    good = SimpleNamespace(pre13_module=str(mod), pre13_module_sha256=data.sha256_file(mod),
                           pre13_nowcasts=str(now), pre13_nowcasts_sha256="0" * 64)
    with pytest.raises(data.Refused, match="nowcasts"):
        mb.pre13_captured(good, None, None, None, None, None)
    bad = SimpleNamespace(**dict(vars(good), pre13_module_sha256=None))
    with pytest.raises(data.Refused, match="module"):
        mb.pre13_captured(bad, None, None, None, None, None)


def test_nbm0712_pins_the_rule_vectors_and_its_windows(tmp_path):
    from weather.reporting.scorecards import dev_scorecard_data as data

    f = tmp_path / "dev_P3d_N.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    with pytest.raises(data.Refused):
        mb.check_nbm0712(str(f), data.sha256_file(f))  # not the rule's vectors
    assert mb.NBM0712_VECTORS_SHA256.startswith("721ae2cd")
    assert [w for w, lo, hi in mb.NBM0712_WINDOWS if lo == hi] == [f"h{h:02d}" for h in range(7, 13)]
    assert [b for b, lo, hi in mb.FIT_BLOCKS if hi < mb.COMPOSITE_SWITCH_HOUR] == ["07-12", "06-09", "10-12"]
