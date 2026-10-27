"""R-V gate 2 (RV-G2a, RV-G2b): the dev reads' frozen candidates, serving, checks and controls (synthetic only).

Guards: clarification_rv_g2a.md (sha 3605333b...) and clarification_rv_g2b.md (sha d9275e5e...) are pinned in code
with the dev MOS manifest (e0c6caa3...); P3d_V_fwd is one all-years fit served through the served state's shell
and its V-off twin equals the served state on every row; SM_HV is SM-H's freeze path with v_gap appended last and
its V-off twin is SM_H unchanged; sm_h_build_state refuses extras that do not start with SM_H's own; the dev
``v_gap`` is the dev MOS day-max minus the captured anchor and the hook counts coverage per source; the dev input
checks STOP on coverage below 0.95, a mean shift above 1.5 F or no rows; control 2 VOIDs when a row went unchecked
or differs by more than 1e-9; control 4 VOIDs when the arms cover different snapshots; a foreign served state or
the wrong thread counts refuse before any fit.
"""
import hashlib
import importlib
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

RV = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/rv"
MARKETS = ("atlanta", "nyc")
BUCKETS = {m: list(range(30, 100)) for m in MARKETS}


def _frame(n_days=25, years=(2021, 2022, 2023, 2024), hour=13, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for market in MARKETS:
        for year in years:
            for d in range(n_days):
                fh = 60.0 + rng.normal(0, 4)
                y = round(fh + rng.normal(0, 3))
                F = float(y - abs(round(rng.normal(0, 2))))
                k_max = fh + rng.normal(0, 2)
                rows.append({
                    "market": market, "hour": hour, "target_date": f"{year}-11-{1 + d:02d}", "year": year,
                    "y": float(y), "F": F, "fh": fh, "x_high_so_far": F, "x_current_temp": F - 1.0,
                    "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.0, "doy_cos": 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)),
                    "k_max": k_max, "k_gap": k_max - fh, "k_tcdc": float(rng.uniform(0, 100)), "k_miss": 0.0,
                    "v_gap": float(y - fh + rng.normal(0, 0.5)) if d % 5 else float("nan")})
    frame = pd.DataFrame(rows)
    centre = lambda day: min(prm.SM_H_CENTRES, key=lambda c: abs(  # noqa: E731
        (pd.Timestamp(f"2001-{c[5:10]}") - pd.Timestamp(f"2001-{day[5:10]}")).days))
    frame["centre"] = frame["target_date"].map(centre)
    frame["season"] = frame["centre"].map(prm.season_of)
    return frame


def _served(frame):
    base, _ = prm.sm_h_build_state(frame, BUCKETS, hours=(13,), markets=MARKETS)
    return dict(base, extra_hgb=[], hours={13: prm.fwd_hour_entry(frame, MARKETS)})


def _one(frame, i):
    return frame.iloc[[i]].reset_index(drop=True)


def test_clarification_and_dev_manifest_shas_are_pinned():
    assert hashlib.sha256((RV / "clarification_rv_g2a.md").read_bytes()).hexdigest() == prm.RV_G2A_SHA256
    assert hashlib.sha256((RV / "clarification_rv_g2b.md").read_bytes()).hexdigest() == prm.RV_G2B_SHA256
    assert prm.RV_G2_MOS_DEV_SHA256 == "e0c6caa32169046ef099e6688dab20625ba00a3363a3a8adfa18a6611179eefd"
    assert prm.RV_G2_HOURS_A == (13, 14, 15, 16) and prm.RV_G2_HOURS_B == (13, 14, 15)
    assert prm.RV_G2_OUT_OF_DECISION_B == ("san-francisco",)
    assert prm.rv_fetch_windows([2026]) == [(2026, "2026-07-31T00:00Z", "2026-09-29T23:59Z")]


def test_read_a_v_off_equals_the_served_state_and_v_differs():
    frame = _frame()
    served = _served(frame)
    v_state, off = prm.rv_g2_freeze_a(frame, served, hours=(13,), markets=MARKETS)
    assert v_state["extra_hgb"] == ["v_gap"] and off["extra_hgb"] == []
    parity = {"rows": 0, "max_abs": 0.0}
    serve = prm.rv_g2_serve_a(served, v_state, off, parity)
    moved = 0.0
    for i in range(0, len(frame), 7):
        one = _one(frame, i)
        ref = serve("P3d_N_served", 13, one, one.at[0, "market"])
        moved = max(moved, prm.dist_max_abs(serve("P3d_V_fwd", 13, one, one.at[0, "market"]), ref))
    assert parity["rows"] == len(range(0, len(frame), 7))
    assert parity["max_abs"] <= prm.RV_G2_PARITY_TOL and moved > 1e-6
    assert prm.rv_g2_parity(parity, parity["rows"])["pass"]
    with pytest.raises(prm.PooledModelError, match="serves no arm"):
        serve("P3d_N_fix", 13, _one(frame, 0), "atlanta")


def test_read_b_smhv_appends_v_gap_last_and_v_off_is_sm_h():
    frame = _frame()
    smhv, off = prm.rv_g2_freeze_b(frame, BUCKETS, hours=(13,), markets=MARKETS)
    smh, _ = prm.sm_h_build_state(frame, BUCKETS, hours=(13,), markets=MARKETS)
    assert smhv["extra_hgb"] == ["k_max", "k_gap", "k_tcdc", "v_gap"] and off["extra_hgb"] == smh["extra_hgb"]
    parity = {"rows": 0, "max_abs": 0.0}
    serve = prm.rv_g2_serve_b(smh, smhv, off, parity)
    moved = 0.0
    for i in range(0, len(frame), 9):
        one = _one(frame, i)
        ref = serve("SM_H", 13, one, one.at[0, "market"])
        moved = max(moved, prm.dist_max_abs(serve("SM_HV", 13, one, one.at[0, "market"]), ref))
    assert parity["max_abs"] <= prm.RV_G2_PARITY_TOL and moved > 1e-6
    with pytest.raises(prm.PooledModelError, match="must start with"):
        prm.sm_h_build_state(frame, BUCKETS, hours=(13,), markets=MARKETS, extra_hgb=("v_gap",))


def test_v_off_parity_voids_on_an_unchecked_row_or_a_difference():
    assert not prm.rv_g2_parity({"rows": 3, "max_abs": 0.0}, 4)["pass"]
    assert not prm.rv_g2_parity({"rows": 4, "max_abs": 2e-9}, 4)["pass"]
    assert not prm.rv_g2_parity({"rows": 0, "max_abs": 0.0}, 0)["pass"]
    assert prm.rv_g2_parity({"rows": 4, "max_abs": 1e-12}, 4)["pass"]


def _dev_table(day, gfs, nam):
    ftime = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + pd.Timedelta(days=1)
    return {("KATL", "GFS"): {(datetime(day.year, day.month, day.day, 6, tzinfo=timezone.utc), ftime): gfs},
            ("KATL", "NAM"): {(datetime(day.year, day.month, day.day, 0, tzinfo=timezone.utc), ftime): nam}}


def test_dev_hook_takes_v_gap_against_the_captured_anchor_and_counts_coverage():
    day = date(2026, 9, 1)
    counts = defaultdict(int)
    hook = prm.rv_g2_v_hook(_dev_table(day, 90.0, 88.0), {"atlanta": "KATL"}, {"atlanta": "America/New_York"},
                            counts, extra=lambda *a: {"k_max": 1.0})
    values = hook("atlanta", day, 13, 85.0, {})
    assert values == {"v_gap": pytest.approx(4.0), "k_max": 1.0}
    assert counts["rows"] == 1 and counts["mos_x_finite"] == 1 and counts["src_GFS_finite"] == 1
    assert counts["src_NBE_finite"] == 0 and counts["v_gaps"] == [pytest.approx(4.0)]
    # one source only: mos_x needs two, so the row counts but carries no v_gap
    hook2 = prm.rv_g2_v_hook(_dev_table(day, 90.0, float("nan")), {"atlanta": "KATL"},
                             {"atlanta": "America/New_York"}, counts)
    assert np.isnan(hook2("atlanta", day, 13, 85.0, {})["v_gap"])
    assert counts["rows"] == 2 and counts["mos_x_finite"] == 1


def test_dev_input_checks_stop_on_coverage_shift_or_no_rows():
    ok = {"rows": 100, "mos_x_finite": 96, "v_gaps": [1.0] * 96}
    assert prm.rv_g2_dev_checks(ok, 0.2)["pass"]
    assert not prm.rv_g2_dev_checks(dict(ok, mos_x_finite=94), 0.2)["pass"]
    assert not prm.rv_g2_dev_checks(ok, -0.6)["pass"]
    assert not prm.rv_g2_dev_checks({}, 0.0)["pass"]


def test_key_identity_voids_when_the_arms_cover_different_snapshots():
    hours = np.array([13, 13, 14, 16, 17])
    markets = np.array(["atlanta", "nyc", "nyc", "atlanta", "nyc"])
    scope = (hours >= 13) & (hours <= 16)
    cov = np.array([True, True, False, True, True])
    keys = prm.rv_g2_keys(cov, cov.copy(), scope, markets, hours)
    assert keys["pass"] and keys["common"] == 3 and keys["by_hour"] == {"13": 2, "14": 0, "16": 1}
    other = cov.copy()
    other[2] = True
    assert not prm.rv_g2_keys(cov, other, scope, markets, hours)["pass"]
    other = cov.copy()
    other[4] = False  # outside scope: ignored
    assert prm.rv_g2_keys(cov, other, scope, markets, hours)["pass"]


def test_rv_g2_refuses_wrong_threads_or_a_foreign_served_state_before_any_fit(tmp_path, monkeypatch):
    fake = tmp_path / "state.pkl"
    fake.write_bytes(b"not the served state")
    kwargs = dict(records_root=tmp_path, layout=tmp_path, replay_root=tmp_path, nbm_train_corpus=fake,
                  hrrr_corpus=tmp_path, hrrr_dev_corpus=tmp_path, mos_augsep=tmp_path, mos_octdec=tmp_path,
                  mos_dev=tmp_path, fwd_state=fake, smh_state=fake)
    for name in prm.RV_C1A_THREADS:
        monkeypatch.setenv(name, "4")
    with pytest.raises(prm.PooledModelError, match="thread counts"):
        prm.rv_g2(out_dir=tmp_path / "out1", **kwargs)
    for name, value in prm.RV_C1A_THREADS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(prm, "forward_training_frame", lambda *a, **k: pytest.fail("fitted before the input check"))
    with pytest.raises(prm.PooledModelError, match="served P3d_N state"):
        prm.rv_g2(out_dir=tmp_path / "out2", **kwargs)
