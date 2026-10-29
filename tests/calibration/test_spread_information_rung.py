"""Lane L15 rung R-S: the NBM TXNSD spread modulation on P3d_N_fix.

Guards: L15 pre-registered rule (C:/t/l15/rule_rs.md, sha 70908316...) - the modulation is a monotone,
mean-zero (training-centred) scale multiplier clipped to [1/2, 2]; beta = 0 reproduces P3d_N_fix exactly; the
anchor, the floor censoring, probability mass and the climatology mix are unchanged; the trailing anomaly uses
strictly earlier bulletins only; the beta search re-scores its candidates exactly and breaks ties to the
smallest beta; nothing dated after 2026-09-29 is accepted; fail-closed import off the capture host.
"""
import importlib
import json
import math

import numpy as np
import pandas as pd
import pytest

try:
    rs = importlib.import_module("weather.calibration.spread_information_rung")
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise


def test_trailing_baseline_uses_only_earlier_days_and_needs_five():
    logsd = {f"2023-08-{d:02d}": math.log(2.0) for d in range(1, 11)}
    logsd["2023-08-11"] = math.log(8.0)  # the target day itself must never enter its own baseline
    assert rs.trailing_baseline(logsd, "2023-08-11") == pytest.approx(math.log(2.0))
    assert rs.trailing_baseline(logsd, "2023-08-05") is None  # only 4 earlier days
    assert rs.trailing_baseline(logsd, "2023-08-06") == pytest.approx(math.log(2.0))
    far = {"2023-07-01": 1.0, "2023-07-02": 1.0, "2023-07-03": 1.0, "2023-07-04": 1.0, "2023-07-05": 1.0}
    assert rs.trailing_baseline(far, "2023-08-11") is None  # outside the 14-day window


def test_anomaly_zero_when_missing_or_below_one():
    assert rs.spread_anomaly(None, 0.5) == 0.0
    assert rs.spread_anomaly(3.0, None) == 0.0
    assert rs.spread_anomaly(0.5, 0.0) == 0.0
    assert rs.spread_anomaly(float("nan"), 0.0) == 0.0
    assert rs.spread_anomaly(4.0, math.log(2.0)) == pytest.approx(math.log(2.0))


def test_modulation_is_centred_monotone_and_clipped():
    x = np.array([-1.0, -0.2, 0.0, 0.3, 2.0])
    xbar = float(x.mean())
    m = rs.modulation(x, xbar, 0.5)
    assert np.all(np.diff(m) >= 0)
    assert float(np.mean(rs.modulation(np.array([-0.1, 0.0, 0.1]), 0.0, 1.0))) == pytest.approx(0.0)
    assert float(rs.modulation(10.0, 0.0, 1.5)) == pytest.approx(math.log(2.0))
    assert float(rs.modulation(-10.0, 0.0, 1.5)) == pytest.approx(-math.log(2.0))
    assert np.all(rs.modulation(x, xbar, 0.0) == 0.0)
    assert float(rs.modulated_scale(0.6, -10.0, 0.0, 1.0)) == prm.MIN_SCALE
    assert rs.RS_BETA_GRID[0] == 0.0 and rs.RS_BETA_GRID[-1] == 1.5 and len(rs.RS_BETA_GRID) == 31


def _row(z, yhat=70.3, s=2.1, F=66.0, actual=71, x=0.3, xbar=0.05):
    buckets = list(range(55, 90))
    p_clim = {b: 1.0 / len(buckets) for b in buckets}
    return {"yhat": yhat, "s": s, "F": F, "z": z, "buckets": buckets, "p_clim": p_clim, "actual": actual,
            "x": x, "xbar": xbar, "table": rs.KernelTable(z), "market": "atlanta", "date": "2023-08-20"}


def test_fast_brier_matches_the_exact_predictive_distribution():
    rng = np.random.default_rng(3)
    z = rng.standard_t(5, size=400)
    for yhat, s, F, actual in ((70.3, 2.1, 66.0, 71), (80.0, 0.5, 80.4, 80), (60.0, 4.0, 40.0, 90), (75.0, 1.3, 79.0, 79)):
        row = _row(z, yhat, s, F, actual)
        exact = rs.exact_brier(row, s)
        fast = rs.fast_brier(yhat, s, F, row["table"], row["p_clim"], actual)
        assert abs(exact - fast) < 1e-6


def test_floor_and_mass_unchanged_by_modulation():
    from weather.units import round_half_up

    rng = np.random.default_rng(4)
    row = _row(rng.normal(size=300), F=69.6)
    fb = int(round_half_up(row["F"]))
    d0 = rs.exact_dist(row, row["s"])
    d1 = rs.exact_dist(row, float(rs.modulated_scale(row["s"], 0.9, 0.0, 1.5)))
    assert sum(d1.values()) == pytest.approx(1.0, abs=1e-12)
    assert sum(v for k, v in d1.items() if k < fb) == pytest.approx(sum(v for k, v in d0.items() if k < fb), abs=1e-15)
    assert rs.exact_dist(row, float(rs.modulated_scale(row["s"], 0.9, 0.0, 0.0))) == d0  # beta 0 is the arm


def test_select_beta_scores_exactly_and_ties_to_zero():
    rng = np.random.default_rng(5)
    z = rng.normal(size=300)
    rows = [_row(z, x=0.0, xbar=0.0, actual=int(70 + rng.integers(-3, 4))) for _ in range(5)]
    beta, exact, err = rs.select_beta(rows)
    assert beta == 0.0  # x == xbar everywhere: every beta ties, the smallest wins
    assert set(exact) >= {0.0} and err < 1e-6


def test_select_beta_picks_a_positive_beta_when_spread_is_informative():
    rng = np.random.default_rng(6)
    z = rng.normal(size=500)
    rows = []
    for i in range(160):
        wide = i % 2 == 0
        x = 0.5 if wide else -0.5
        err = rng.normal(0, 4.0 if wide else 1.0)
        rows.append(_row(z, yhat=70.0, s=2.0, F=40.0, actual=int(round(70.0 + err)), x=x, xbar=0.0))
    beta, exact, _ = rs.select_beta(rows)
    assert beta > 0.3
    assert exact[beta] < exact[0.0]


def _frame(markets=("atlanta", "nyc"), years=(2021, 2022, 2023, 2024), hour=9, n_days=14, seed=0):
    rng = np.random.default_rng(seed)
    rows, xs = [], []
    for market in markets:
        for year in years:
            for d in range(n_days):
                wide = d % 2 == 0
                fh = 80.0 + rng.normal(0, 3)
                y = round(fh + rng.normal(0, 4.0 if wide else 1.0))
                F = fh - 8.0
                rows.append({"market": market, "centre": "2026-08-23", "season": "aug_sep", "hour": hour,
                             "target_date": f"{year}-08-{10 + d:02d}", "year": year, "y": float(y), "F": F,
                             "fh": fh, "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.5, "doy_cos": 0.8,
                             "x_high_so_far": F, "x_current_temp": F - 1.0,
                             "market_code": float(prm.R0_MARKETS.index(market))})
                xs.append(0.4 if wide else -0.4)
    return pd.DataFrame(rows), np.array(xs)


def test_rs_loyo_beta_zero_reproduces_the_unmodulated_rung_rows():
    frame, x = _frame()
    buckets = {m: list(range(60, 105)) for m in ("atlanta", "nyc")}
    rows, betas, dev, diag = rs.rs_loyo(frame, x, buckets, (9,))
    ref = prm.rung_loyo(frame, buckets, (9,), arms={"P3d_N_fix": False})
    ref_b = {(r["market"], r["date"]): r["P3d_N_fix_brier"] for r in ref}
    assert len(rows) == len(ref_b)
    assert max(abs(r["P3d_N_fix_brier"] - ref_b[(r["market"], r["date"])]) for r in rows) < 1e-12
    for v in betas.values():
        assert v["inner_brier_beta"] <= v["inner_brier_beta0"] + 1e-12
    assert set(dev) == {9} and dev[9]["beta"] in rs.RS_BETA_GRID
    summary = rs.loyo_summary(rows, draws=50)
    assert "pooled|brier" in summary and summary["pooled|brier"]["n"] == len(rows)


def test_load_sd_table_refuses_rows_after_the_window(tmp_path):
    good = {"market_id": "atlanta", "target_date": "2026-09-29", "available": True, "mean": 90.0, "sd": 2.0,
            "cycle": "07", "last_modified": "2026-09-29T08:30:00Z"}
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(good) + "\n", encoding="utf-8")
    table, logsd = rs.load_sd_table(path)
    assert logsd["atlanta"]["2026-09-29"] == pytest.approx(math.log(2.0))
    path.write_text(json.dumps({**good, "target_date": "2026-09-30"}) + "\n", encoding="utf-8")
    with pytest.raises(rs.SpreadRungError):
        rs.load_sd_table(path)


def test_outputs_refused_inside_the_repository():
    from weather.paths import REPO_ROOT

    with pytest.raises(prm.PooledModelError):
        prm.require_output_outside_repo(REPO_ROOT / "data" / "x")
