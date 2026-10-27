"""R-V clarification RV-C1: R-V re-decided against the served arms (synthetic frames, no outcome join).

Guards: clarification_rv_c1.md (sha db11d8d2...) - the Oct-Dec fetch window is runtimes 09-30..12-31 of 2021-25 and
refuses any other year; the two MOS corpora merge on (station, model, runtime, ftime) and a differing duplicate is
a conflict (equal or both-NaN duplicates are not); in read (a) each fold drops the held-out year's rows, P3d_N_fwd
is served through the served state's shell, the tier-2 refit and the V-off builder on the candidate's serving
path both equal the served state on every scored row and fail on a perturbed state; in read (b) SM_H is exactly the
SM-H run's arm (V off reproduces its rows) and SM_HV appends v_gap last; key identity and reproduction fail on a
missing, extra or differing row; foreign inputs refuse before any fit.
"""
import hashlib
import importlib
from datetime import datetime, timezone
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

NOTE = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/rv/clarification_rv_c1.md"
MARKETS = ("atlanta", "nyc")
BUCKETS = {m: list(range(30, 100)) for m in MARKETS}


def _frame(n_days=12, years=(2021, 2022, 2023, 2024), hour=13, seed=0):
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
                    "market": market, "hour": hour, "target_date": f"{year}-11-{3 + d:02d}", "year": year,
                    "y": float(y), "F": F, "fh": fh, "x_high_so_far": F, "x_current_temp": F - 1.0,
                    "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.0, "doy_cos": 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)),
                    "k_max": k_max, "k_gap": k_max - fh, "k_tcdc": float(rng.uniform(0, 100)), "k_miss": 0.0,
                    "v_gap": float(rng.normal(0, 2)) if d % 5 else float("nan")})
    frame = pd.DataFrame(rows)
    centre = lambda day: min(prm.SM_H_CENTRES, key=lambda c: abs(  # noqa: E731
        (pd.Timestamp(f"2001-{c[5:10]}") - pd.Timestamp(f"2001-{day[5:10]}")).days))
    frame["centre"] = frame["target_date"].map(centre)
    frame["season"] = frame["centre"].map(prm.season_of)
    return frame


def _served(frame):
    """A served-state stand-in: the SM-H state layout with hours[13] = the forward entry on every row."""
    base, _ = prm.sm_h_build_state(frame, BUCKETS, hours=(13,), markets=MARKETS)
    return dict(base, extra_hgb=[], hours={13: prm.fwd_hour_entry(frame, MARKETS)})


def test_clarification_sha_is_recorded_in_code():
    assert hashlib.sha256(NOTE.read_bytes()).hexdigest() == prm.RV_C1_SHA256


def test_octdec_fetch_window_is_history_only():
    assert prm.rv_c1_fetch_windows([2021, 2025]) == [(2021, "2021-09-30T00:00Z", "2021-12-31T23:59Z"),
                                                     (2025, "2025-09-30T00:00Z", "2025-12-31T23:59Z")]
    for year in (2020, 2026):
        with pytest.raises(prm.PooledModelError, match="2021-25 only"):
            prm.rv_c1_fetch_windows([year])


def test_corpus_merge_unions_and_flags_only_differing_duplicates():
    t = lambda h: datetime(2023, 9, 30, h, tzinfo=timezone.utc)  # noqa: E731
    first = {("KATL", "GFS"): {(t(0), t(23)): 90.0, (t(6), t(23)): float("nan")}}
    second = {("KATL", "GFS"): {(t(0), t(23)): 90.0, (t(6), t(23)): float("nan"), (t(12), t(23)): 91.0},
              ("KJFK", "NAM"): {(t(0), t(23)): 80.0}}
    table, conflicts = prm.rv_c1_merge_tables(first, second)
    assert not conflicts and len(table[("KATL", "GFS")]) == 3 and table[("KJFK", "NAM")][(t(0), t(23))] == 80.0
    _, conflicts = prm.rv_c1_merge_tables(first, {("KATL", "GFS"): {(t(0), t(23)): 89.0}})
    assert len(conflicts) == 1 and conflicts[0][4:] == [90.0, 89.0]


def test_read_a_folds_drop_the_held_out_year_and_both_parities_hold():
    frame = _frame()
    served = _served(frame)
    seen = []
    real = prm.fwd_hour_entry

    def spy(train, markets=prm.R0_MARKETS):
        seen.append(sorted(train["year"].unique()))
        return real(train, markets)

    rows, excluded, parity = prm.rv_c1_rows_a({"octdec": frame}, frame, served, hours=(13,), markets=MARKETS)
    assert excluded == {"octdec": 0} and len(rows["octdec"]) == len(frame)
    assert parity["tier2"]["pass"] and parity["v_off"]["pass"] and parity["rows"] == len(frame)
    assert parity["v_off"]["max_abs"] <= prm.RV_C1_PARITY_TOL
    assert any(r["P3d_V_fwd_brier"] != r["P3d_N_fwd_brier"] for r in rows["octdec"])
    prm.fwd_hour_entry = spy
    try:
        prm.rv_c1_rows_a({"octdec": frame[frame["year"] == 2022]}, frame, served, hours=(13,), markets=MARKETS)
    finally:
        prm.fwd_hour_entry = real
    assert seen == [[2021, 2022, 2023, 2024], [2021, 2023, 2024]]


def test_read_a_parity_fails_when_the_served_state_differs():
    frame = _frame()
    served = _served(frame)
    shifted = dict(served, hours={13: dict(served["hours"][13], z=np.asarray(served["hours"][13]["z"]) + 0.3)})
    _, _, parity = prm.rv_c1_rows_a({"octdec": frame}, frame, shifted, hours=(13,), markets=MARKETS)
    assert not parity["tier2"]["pass"] and not parity["v_off"]["pass"]


def test_read_b_sm_h_is_the_sm_h_run_arm_and_v_is_appended_last(monkeypatch):
    frame = _frame(n_days=15)
    monkeypatch.setattr(prm, "sm_h_frozen_dist", lambda state, row: {int(row["y"]): 1.0})
    ref, _ = prm.sm_h_rows(frame, BUCKETS, state=None, hours=(13,), arms={"SM_H": prm.SM_H_ARMS["SM_H"]})
    rows, excluded = prm.rv_c1_rows_b(frame, BUCKETS, hours=(13,))
    assert excluded == 0 and prm.RV_C1_SMHV_EXTRA == ("k_max", "k_gap", "k_tcdc", "v_gap")
    assert prm.rv_c1_reproduce(rows, ref, "SM_H", "SM_H_brier")["pass"]
    assert any(r["SM_HV_brier"] != r["SM_H_brier"] for r in rows)


def test_reproduce_and_keys_fail_on_missing_extra_or_differing_rows():
    rows = [{"hour": 13, "year": 2021, "market": "nyc", "date": f"2021-11-0{i}", "A_brier": 0.5} for i in range(1, 4)]
    ref = [dict(r, B=0.5) for r in rows]
    assert prm.rv_c1_reproduce(rows, ref, "A", "B")["pass"] and prm.rv_c1_keys(rows, ref)["pass"]
    assert not prm.rv_c1_reproduce(rows, [dict(ref[0], B=0.5 + 2e-12)] + ref[1:], "A", "B")["pass"]
    assert not prm.rv_c1_reproduce(rows[1:], ref, "A", "B")["pass"]
    assert prm.rv_c1_keys(rows + [dict(rows[0], date="2021-11-09")], ref)["extra"] == 1


def test_rv_c1_refuses_a_foreign_input_before_any_fit(tmp_path):
    for name in ("nbm.jsonl", "state.pkl", "a.jsonl", "b.jsonl", "c.jsonl", "d.jsonl"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    kwargs = dict(records_root=tmp_path, nbm_train_corpus=tmp_path / "nbm.jsonl", hrrr_corpus=tmp_path,
                  mos_augsep=tmp_path, mos_octdec=tmp_path, fwd_state=tmp_path / "state.pkl",
                  c10_rows_path=tmp_path / "a.jsonl", c10_fwd_rows=tmp_path / "b.jsonl",
                  smh_rows=tmp_path / "c.jsonl", rv_rows=tmp_path / "d.jsonl", out_dir=tmp_path / "out")
    with pytest.raises(prm.PooledModelError, match="NBM corpus"):
        prm.rv_c1(**kwargs)
    assert not list((tmp_path / "out").iterdir())
