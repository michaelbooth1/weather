"""Lane L2 SM-H: season-matched P3d_H at 13-15 vs MG-2's frozen P3d_N (synthetic frames, no outcome join).

Guards: the SM-H pre-registration (rule_sm_h.md sha fca2bb11...) - CS-1's Brier form (label outside the support
costs 1); HRRR selections kept only for 2021-25 Oct-Dec local dates; the LOYO arms score exactly as the rung
LOYO fits them and the frozen comparator scores the identical rows; rows without observations leave every arm;
the comparator control reproduces CS-1 part1a per hour (mean and row count, 1e-9); every bound input refuses a
foreign sha before anything is fitted; missing record files refuse.
"""
import hashlib
import importlib
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


def _frame(n_days=31, years=(2021, 2022, 2023, 2024), markets=("atlanta", "nyc"), hour=13, seed=0):
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
                    "target_date": f"{year}-11-{1 + d % 30:02d}", "year": year, "y": float(y), "F": float(F),
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
    kept = frame.drop(index=3).reset_index(drop=True)
    ref = prm.rung_loyo(kept, buckets, (13,), arms={"P3d_N_fix": False, "P3d_H": prm.RK_ARMS["P3d_H"]})
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
