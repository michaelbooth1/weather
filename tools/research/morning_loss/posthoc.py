"""L5 POST-HOC descriptives (not in the pre-declared plan; labelled post-hoc in every report).

(a) shift-operator sanity: centre of the shifted served vector vs the market centre;
(b) served-minus-market centre gap by within-market tercile of the market centre (heat level, ex ante);
(c) centre drift 00 -> 08 h for served and market;
(d) MAE to market centre / outcome of simple captured-product blends, bias-corrected walk-forward-free
    (in-sample, descriptive only).
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import analyse as A  # noqa: E402
from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402


def main(layout_root):
    start, end = data.check_range("2026-08-01", "2026-09-29")
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    t = sc.Table(layout, scored)
    geo = A.Geometry(t)
    hour = t.local_hour
    inW = (hour >= 7) & (hour <= 12)
    y = layout.labels.set_index("row_key").reindex(t.snaps.row_key).settlement_high.to_numpy(float)
    c_s, _ = geo.centre_sd(t.p_served)
    c_m, _ = geo.centre_sd(t.p_market)
    out = {}
    wsn = np.flatnonzero(inW)
    sh = geo.shift(t.p_served, c_m - c_s, wsn)
    c_sh, _ = geo.centre_sd(sh)
    out["a_shift_sanity_mae_shifted_to_market"] = float(np.mean(np.abs(c_sh[wsn] - c_m[wsn])))
    out["a_shift_sanity_mae_served_to_market"] = float(np.mean(np.abs(c_s[wsn] - c_m[wsn])))
    df = pd.DataFrame({"cell": t.cell, "m": t.markets, "h": hour, "cs": c_s, "cm": c_m, "y": y})
    cw = df[inW].groupby("cell").agg(m=("m", "first"), cs=("cs", "mean"), cm=("cm", "mean"), y=("y", "first"))
    cw["terc"] = cw.groupby("m").cm.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=[1, 2, 3]))
    cw["gap"] = cw.cm - cw.cs
    cw["bias_s"] = cw.cs - cw.y
    cw["bias_m"] = cw.cm - cw.y
    out["b_gap_by_heat_tercile"] = cw.groupby("terc", observed=True)[["gap", "bias_s", "bias_m"]].mean().round(3).to_dict()
    out["b_gap_by_market_tercile"] = {m: g.groupby("terc", observed=True).gap.mean().round(2).to_dict()
                                      for m, g in cw.groupby("m")}
    hm = df[hour <= 12].groupby(["cell", "h"])[["cs", "cm"]].mean().unstack("h")
    out["c_drift_00_to_08"] = {"served": float((hm.cs[8] - hm.cs[0]).mean()),
                               "market": float((hm.cm[8] - hm.cm[0]).mean()),
                               "served_08_to_12": float((hm.cs[12] - hm.cs[8]).mean()),
                               "market_08_to_12": float((hm.cm[12] - hm.cm[8]).mean())}
    prods = {c: pd.to_numeric(t.snaps[c], errors="coerce").to_numpy(float)
             for c in ("v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high")}
    pf = pd.DataFrame({"cell": t.cell, "cm": c_m, "y": y, **prods})[inW].groupby("cell").mean()
    pf["blend_nws_v2"] = (pf.nws_grid_high_raw + pf.v2_mean) / 2
    pf["blend_all4"] = pf[["v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high"]].mean(axis=1)
    rows = {}
    for c in ("v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high", "blend_nws_v2", "blend_all4"):
        v = pf[c]
        bias = float((v - pf.y).mean())
        rows[c] = {"mae_to_market": float((v - pf.cm).abs().mean()), "mae_to_outcome": float((v - pf.y).abs().mean()),
                   "bias": bias, "mae_to_outcome_debiased_insample": float((v - bias - pf.y).abs().mean())}
    rows["market_centre"] = {"mae_to_outcome": float((pf.cm - pf.y).abs().mean()), "bias": float((pf.cm - pf.y).mean())}
    out["d_products_W_insample"] = rows
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
