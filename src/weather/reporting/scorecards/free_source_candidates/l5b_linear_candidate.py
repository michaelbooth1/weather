"""L5 arm A candidate 2: forecast-only linear regression of the settled high on captured forecasts.

Pre-registered (``docs/research/l5-hot-day-centre-preregistration-2026-10-24.md``). Linear in levels, so it
can predict above the training range (the tree-extrapolation test). Fit, per fold on its training snapshots at
local 07-12 with every regressor present: y = a[m] + b1 v2_mean + b2 nws_grid_high_raw + b3 hrrr_high
+ b4 forecast_high + b5 overnight_low_anomaly, ordinary least squares with one intercept per market (a market
with no training row gets the mean intercept). Serve, 07-12, all regressors present and v2 usable: mu = the
fitted value; otherwise MG-1's mu. Outside 07-12 = MG-1. Sigma, floor and availability are MG-1's.
"""
import numpy as np

from weather.reporting.scorecards.free_source_candidates import l5_centre as C

NAME = "l5b_linear_forecasts_lowanom"
REGRESSORS = ("v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high", "overnight_low_anomaly")


def _x(s):
    usable = C.v2_usable(s)
    cols = {"v2_mean": np.where(usable, C.num(s, "v2_mean"), np.nan)}
    for c in REGRESSORS[1:4]:
        cols[c] = C.num(s, c)
    cols["overnight_low_anomaly"] = C.overnight_low_anomaly(s)
    return np.column_stack([cols[c] for c in REGRESSORS])


def fit(train):
    s = train["snapshots"].reset_index(drop=True)
    y = C.target(train)
    X = _x(s)
    ok = C.in_window(s) & np.isfinite(y) & np.isfinite(X).all(axis=1)
    markets = s.market.astype(str).to_numpy()[ok]
    mk = sorted(set(markets))
    D = np.column_stack([(markets == m).astype(float) for m in mk] + [X[ok]])
    coef, *_ = np.linalg.lstsq(D, y[ok], rcond=None)
    intercepts = dict(zip(mk, coef[:len(mk)].tolist()))
    return {"intercepts": intercepts, "beta": coef[len(mk):].tolist(), "y_max": {m: float(y[ok][markets == m].max())
                                                                              for m in mk},
            "provenance": {"rule": NAME, "regressors": list(REGRESSORS), "n_train": int(ok.sum()),
                           "beta": coef[len(mk):].tolist(), "inputs": C.tables()[2]}}


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    X = _x(s)
    markets = s.market.astype(str).to_numpy()
    mean_a = float(np.mean(list(state["intercepts"].values())))
    a = np.array([state["intercepts"].get(m, mean_a) for m in markets])
    mu = a + X @ np.asarray(state["beta"])
    mu = np.where(np.isfinite(X).all(axis=1), mu, np.nan)
    return C.serve(s, bands, mu)
