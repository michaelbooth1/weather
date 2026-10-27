"""Lane L2 SM-H: season-matched P3d_H at 13-15 vs MG-2's frozen P3d_N (synthetic frames, no outcome join).

Guards: the SM-H pre-registration (rule_sm_h.md sha fca2bb11...) - CS-1's Brier form (label outside the support
costs 1); HRRR selections kept only for 2021-25 Oct-Dec local dates; the LOYO arms score exactly as the rung
LOYO fits them and the frozen comparator scores the identical rows; rows without observations leave every arm;
the comparator control reproduces CS-1 part1a per hour (mean and row count, 1e-9); every bound input refuses a
foreign sha before anything is fitted; missing record files refuse. C10-sel (rule_c10_sel.md sha 8c59c1b6...) and
SMH-1 (b3007803...): each P3d_N_fwd fold drops the held-out year's rows and is served through the served state's
shell; tier-2 parity uses the all-years refit on every scored row and fails on any difference; SM_N reproduces
the SM-H rows on identical keys; SMH-1 is VOID on a VOID C10 run or on differing keys and binds the SM-H rows.
"""
import hashlib
import importlib
import json
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

from weather.calibration import feature_model as fm

RULE = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/mg3/rule_sm_h.md"


def _frame(n_days=30, years=(2021, 2022, 2023, 2024), markets=("atlanta", "nyc"), hour=13, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for market in markets:
        for year in years:
            for d in range(n_days):
                fh = 60.0 + rng.normal(0, 4)
                y = round(fh + rng.normal(0, 3))
                F = y - abs(round(rng.normal(0, 2)))
                k_max = fh + rng.normal(0, 2)
                rows.append({
                    "market": market, "centre": "2026-11-09", "season": "fall", "hour": hour,
                    "target_date": f"{year}-11-{1 + d:02d}", "year": year, "y": float(y), "F": float(F),
                    "fh": fh, "x_high_so_far": float(F), "x_current_temp": float(F) - 1.0,
                    "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.0, "doy_cos": 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)),
                    "k_max": k_max, "k_gap": k_max - fh, "k_tcdc": float(rng.uniform(0, 100)), "k_miss": 0.0,
                })
    return pd.DataFrame(rows)


def test_rule_sha_is_recorded_in_code():
    assert hashlib.sha256(RULE.read_bytes()).hexdigest() == prm.SM_H_RULE_SHA256


def test_arms_are_the_registered_specs():
    assert prm.SM_H_ARMS["SM_H"] == prm.RK_ARMS["P3d_H"]
    assert prm.SM_H_ARMS["SM_N"] is False
    assert prm.SM_H_HOURS == (13, 14, 15)
    assert prm.SM_H_PAIRS[0] == ("SM_H", "P3d_N")


def test_brier_is_cs1_form():
    dist = {60: 0.25, 61: 0.5, 62: 0.25}
    assert prm.sm_h_brier(dist, 61) == pytest.approx(fm.brier_score(dist, 61), abs=1e-15)
    assert prm.sm_h_brier(dist, 70) == pytest.approx(fm.brier_score(dist, 70) + 1.0, abs=1e-15)


def test_day_filter_keeps_only_history_oct_dec():
    assert prm.sm_h_day_filter("2021-10-03")
    assert prm.sm_h_day_filter("2025-12-16")
    assert not prm.sm_h_day_filter("2025-09-29")
    assert not prm.sm_h_day_filter("2026-10-10")
    assert not prm.sm_h_day_filter("2020-11-01")


def test_rows_match_the_rung_fit_and_score_the_frozen_arm_on_identical_rows(monkeypatch):
    frame = _frame()
    frame.loc[3, "x_current_temp"] = np.nan  # no observation: out of every arm
    buckets = {m: list(range(30, 100)) for m in ("atlanta", "nyc")}
    seen = []

    def frozen(state, row):
        seen.append((row["market"], str(row["target_date"])[:10], int(row["hour"])))
        return {int(row["y"]): 0.5, int(row["y"]) + 1: 0.5}

    monkeypatch.setattr(prm, "sm_h_frozen_dist", frozen)
    rows, excluded = prm.sm_h_rows(frame, buckets, state=None, hours=(13,))
    assert excluded == 1
    assert len(rows) == len(frame) - 1 == len(seen)
    assert all(r["P3d_N_brier"] == pytest.approx(0.5) for r in rows)
    # the excluded row still trains the other years' folds, exactly as in the rung LOYO
    ref = prm.rung_loyo(frame, buckets, (13,), arms={"P3d_N_fix": False, "P3d_H": prm.RK_ARMS["P3d_H"]})
    key = lambda r: (r["year"], r["market"], r["date"])  # noqa: E731
    by = {key(r): r for r in ref}
    for r in rows:
        assert r["SM_N_log"] == by[key(r)]["P3d_N_fix_log"]
        assert r["SM_H_log"] == by[key(r)]["P3d_H_log"]


def _part1a(values, n=3):
    return {"p3d_n_1316": {"periods": {"oct_dec": {"by": {
        f"h{h:02d}": {"brier_part": v, "n_rows": n} for h, v in zip((13, 14, 15), values)}}}}}


def test_control_reproduces_part1a_mean_and_count():
    rows = [{"hour": h, "P3d_N_brier": b} for h in (13, 14, 15) for b in (0.2, 0.4, 0.6)]
    assert prm.sm_h_control(rows, _part1a((0.4, 0.4, 0.4)))["pass"]
    assert not prm.sm_h_control(rows, _part1a((0.4, 0.4, 0.4 + 2e-9)))["pass"]
    assert not prm.sm_h_control(rows, _part1a((0.4, 0.4, 0.4), n=4))["pass"]


def test_frame_refuses_missing_records(tmp_path):
    with pytest.raises(prm.PooledModelError, match="records missing"):
        prm.sm_h_frame(tmp_path)


def test_loyo_refuses_a_foreign_input_before_any_fit(tmp_path):
    for name in ("nbm.jsonl", "state.pkl", "part1a.json"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="NBM corpus"):
        prm.sm_h_loyo(records_root=tmp_path, nbm_train_corpus=tmp_path / "nbm.jsonl", hrrr_corpus=tmp_path,
                      p3d_n_state=tmp_path / "state.pkl", part1a=tmp_path / "part1a.json", out_dir=tmp_path / "out")
    assert not list((tmp_path / "out").iterdir())
    (tmp_path / "out" / "x").write_text("1", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="non-empty"):
        prm.sm_h_loyo(records_root=tmp_path, nbm_train_corpus=tmp_path / "nbm.jsonl", hrrr_corpus=tmp_path,
                      p3d_n_state=tmp_path / "state.pkl", part1a=tmp_path / "part1a.json", out_dir=tmp_path / "out")


# ---------------------------------------------------------------- C10-sel and SMH-1 (comparator = served P3d_N)

C10_RULE = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/c10/rule_c10_sel.md"
SMH1 = Path(__file__).resolve().parents[2] / "docs/research/l2-pooled-residual-2026-10-24/mg3/clarification_sm_h_1.md"


def test_c10_and_smh1_shas_are_recorded_in_code():
    assert hashlib.sha256(C10_RULE.read_bytes()).hexdigest() == prm.C10_RULE_SHA256
    assert hashlib.sha256(SMH1.read_bytes()).hexdigest() == prm.SM_H_CLARIFICATION_1_SHA256


def _count_serve(state, row):
    """Fake serve: the mass on the label encodes how many training labels the state's hour entry holds."""
    n = sum(len(v) for v in state["hours"][int(row["hour"])]["train_y"].values())
    p = n / 10000.0
    return {int(row["y"]): p, int(row["y"]) + 1: 1.0 - p}


def test_c10_rows_fold_drops_the_held_out_year_and_parity_uses_the_all_years_refit():
    oct_frame = _frame()
    fwd_frame = pd.concat([_frame(seed=1).assign(target_date=lambda f: f["target_date"].str.replace("-11-", "-08-")),
                           oct_frame], ignore_index=True)
    oct_frame.loc[5, "x_current_temp"] = np.nan
    buckets = {m: list(range(30, 100)) for m in ("atlanta", "nyc")}
    markets = ("atlanta", "nyc")
    n_all = len(fwd_frame)
    served = {"hours": {13: {"train_y": {"atlanta": [0] * n_all}}}}
    dev = {"hours": {13: {"train_y": {"atlanta": []}}}}
    rows, excluded, parity = prm.c10_rows(oct_frame, fwd_frame, buckets, served, dev, hours=(13,), markets=markets,
                                          serve=_count_serve)
    assert excluded == 1 and len(rows) == len(oct_frame) - 1
    assert parity["pass"] and parity["max_abs"] == 0.0 and parity["rows"] == len(rows)
    per_year = fwd_frame.groupby("year").size()
    for r in rows:
        p = (n_all - per_year[r["year"]]) / 10000.0
        assert r["P3d_N_fwd_brier"] == pytest.approx(prm.sm_h_brier({r["y"]: p, r["y"] + 1: 1 - p}, r["y"]))
        assert r["P3d_N_dev_brier"] == pytest.approx(2.0)
    ref = prm.rung_loyo(oct_frame, buckets, (13,), arms={"P3d_N_fix": False})
    by = {(r["year"], r["market"], r["date"]): r for r in ref}
    assert all(r["SM_N_log"] == by[(r["year"], r["market"], r["date"])]["P3d_N_fix_log"] for r in rows)


def test_c10_parity_fails_when_the_served_state_differs():
    oct_frame = _frame()
    buckets = {m: list(range(30, 100)) for m in ("atlanta", "nyc")}
    served = {"hours": {13: {"train_y": {"atlanta": [0] * 7}}}}
    _, _, parity = prm.c10_rows(oct_frame, oct_frame, buckets, served, served, hours=(13,),
                                markets=("atlanta", "nyc"), serve=_count_serve)
    assert not parity["pass"]


def test_sm_n_reproduction_needs_identical_keys_and_scores():
    rows = [{"hour": 13, "year": 2021, "market": "nyc", "date": "2021-11-01", "SM_N_brier": 0.3},
            {"hour": 16, "year": 2021, "market": "nyc", "date": "2021-11-01", "SM_N_brier": 0.1}]
    ref = [{"hour": 13, "year": 2021, "market": "nyc", "date": "2021-11-01", "SM_N_brier": 0.3}]
    assert prm.c10_sm_n_reproduction(rows, ref)["pass"]
    assert not prm.c10_sm_n_reproduction(rows, [dict(ref[0], SM_N_brier=0.3 + 1e-9)])["pass"]
    assert not prm.c10_sm_n_reproduction(rows, ref + [dict(ref[0], market="atlanta")])["pass"]


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _redecide_inputs(tmp_path, stopped=None, drop=False):
    keys = [(h, y, m, f"{y}-11-0{d}") for h in (13, 14, 15) for y in (2021, 2022) for m in ("nyc", "atlanta")
            for d in (1, 2, 3)]
    smh = [{"hour": h, "year": y, "market": m, "date": d, "SM_H_brier": 0.4, "SM_H_log": 1.0} for h, y, m, d in keys]
    fwd = [{"hour": h, "year": y, "market": m, "date": d, "P3d_N_fwd_brier": 0.5, "P3d_N_fwd_log": 1.2}
           for h, y, m, d in (keys[1:] if drop else keys)]
    c10 = tmp_path / "c10"
    c10.mkdir()
    _write(c10 / "fwd_rows.jsonl", fwd)
    _write(tmp_path / "smh.jsonl", smh)
    checks = {k: {"pass": True} for k in ("1_inputs", "3_tier2_parity", "4_row_identity", "5_sm_n_reproduction")}
    audit = {"rule_sha256": prm.C10_RULE_SHA256, "checks": checks, "stopped_at": stopped,
             "outputs": {"fwd_rows": hashlib.sha256((c10 / "fwd_rows.jsonl").read_bytes()).hexdigest()}}
    (c10 / "c10_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    sha = hashlib.sha256((tmp_path / "smh.jsonl").read_bytes()).hexdigest()
    return tmp_path / "smh.jsonl", c10 / "c10_audit.json", sha


def test_redecide_selects_on_the_upper_bound(tmp_path):
    smh, audit, sha = _redecide_inputs(tmp_path)
    out = prm.sm_h_redecide(smh_rows=smh, c10_audit=audit, out_dir=tmp_path / "out", expected_smh_rows=sha)
    assert out["decision"]["selected"] == "SM_H" and out["decision"]["estimate"] == pytest.approx(-0.1)
    assert (tmp_path / "out" / "smh1_audit.json").exists()


def test_redecide_is_void_on_a_void_c10_run_or_different_keys(tmp_path):
    (tmp_path / "a").mkdir()
    smh, audit, sha = _redecide_inputs(tmp_path / "a", stopped="checks VOID")
    out = prm.sm_h_redecide(smh_rows=smh, c10_audit=audit, out_dir=tmp_path / "a" / "out", expected_smh_rows=sha)
    assert out["stopped_at"] and "decision" not in out
    (tmp_path / "b").mkdir()
    smh, audit, sha = _redecide_inputs(tmp_path / "b", drop=True)
    out = prm.sm_h_redecide(smh_rows=smh, c10_audit=audit, out_dir=tmp_path / "b" / "out", expected_smh_rows=sha)
    assert out["stopped_at"].startswith("keys differ") and "decision" not in out
    with pytest.raises(prm.PooledModelError, match="SM-H rows"):
        prm.sm_h_redecide(smh_rows=smh, c10_audit=audit, out_dir=tmp_path / "b" / "out2")


def test_c10_refuses_a_foreign_input_before_any_fit(tmp_path):
    for name in ("nbm.jsonl", "fwd.pkl", "dev.pkl", "part1a.json", "smh.jsonl"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="NBM corpus"):
        prm.c10_sel(records_root=tmp_path, nbm_train_corpus=tmp_path / "nbm.jsonl", fwd_state=tmp_path / "fwd.pkl",
                    dev_state=tmp_path / "dev.pkl", part1a=tmp_path / "part1a.json", smh_rows=tmp_path / "smh.jsonl",
                    out_dir=tmp_path / "out")
