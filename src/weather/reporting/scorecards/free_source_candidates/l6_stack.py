r"""Lane L6: MG-1 recentred on a history-trained observation nowcast, stacked per local hour (07-12).

Pre-declared in C:\t\l6\rule.md (sha256 in docs/research/free-source-screens-2026-10-23.md § L6).
Inputs: ``<research root>/upstream_obs/screen/nowcasts.parquet`` (row_key, n_own, n_up), built by
``weather.calibration.upstream_obs_screen serve`` from observations only (models fitted on Aug-Sep
2021-2025; features as of each snapshot's captured_at_utc).

Fit, per walk-forward fold on its training snapshots only, for each local hour h in 07..12, over
snapshots where MG-1 is usable and the nowcast N exists: z = y - v2_mean, x = N - v2_mean, with
y = centre of the settled band (eq: (low + high) / 2; lte: high; gte: low); OLS z = a + b x with b
clipped to [0, 1] (a refitted as mean(z - b x) when clipped); needs >= 200 snapshots, else hour h keeps
MG-1. Serve: mu = v2_mean + a + b (N - v2_mean); sigma = max(v2_stddev, 1); floor and band mapping as
MG-1. Hours outside 07-12, or snapshots without N, are MG-1 exactly.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import mg1, remaining_rise as rr

HOURS = (7, 8, 9, 10, 11, 12)
MIN_N = 200
_CACHE = {}


def nowcast_path():
    default = Path(r"C:\Users\Michael\Documents\github\weather\data\research\upstream_obs\screen\nowcasts.parquet")
    return Path(os.environ.get("L6_NOWCASTS", default))


def nowcasts():
    if "n" not in _CACHE:
        path = nowcast_path()
        _CACHE["n"] = (pd.read_parquet(path).set_index("row_key"), rr.file_sha(path))
    return _CACHE["n"]


def targets(train):
    lab = train["labels"].set_index("row_key").winner
    b = train["bands"]
    win = b[b.band_index.to_numpy(int) == lab.reindex(b.row_key).to_numpy()]
    centre = np.where(win.kind == "lte", win.high, np.where(win.kind == "gte", win.low, (win.low + win.high) / 2.0))
    return pd.Series(centre.astype(float), index=win.row_key.to_numpy())


def _usable_v2(s):
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(v2) & np.isfinite(sd) & (avail <= t).fillna(False).to_numpy()
    return np.where(ok, v2, np.nan)


def fit(train, column, name):
    s = train["snapshots"].reset_index(drop=True)
    y = targets(train).reindex(s.row_key).to_numpy(float)
    table, sha = nowcasts()
    n = table[column].reindex(s.row_key).to_numpy(float)
    v2 = _usable_v2(s)
    hours = s.local_hour.to_numpy(int)
    coef = {}
    for h in HOURS:
        sel = (hours == h) & np.isfinite(y) & np.isfinite(n) & np.isfinite(v2)
        if sel.sum() < MIN_N:
            continue
        z, x = y[sel] - v2[sel], n[sel] - v2[sel]
        xc = x - x.mean()
        b = float((xc * (z - z.mean())).sum() / max((xc ** 2).sum(), 1e-9))
        b = min(max(b, 0.0), 1.0)
        a = float((z - b * x).mean())
        coef[h] = (a, b, int(sel.sum()))
    return {"coef": coef, "column": column,
            "provenance": {"rule": name, "nowcasts_sha256": sha, "column": column,
                           "coef": {str(h): v for h, v in coef.items()}}}


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    table, _ = nowcasts()
    n = table[state["column"]].reindex(s.row_key).to_numpy(float)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    hours = s.local_hour.to_numpy(int)
    mu = v2.copy()
    for h, (a, b, _) in state["coef"].items():
        sel = (hours == h) & np.isfinite(n) & np.isfinite(v2)
        mu[sel] = v2[sel] + a + b * (n[sel] - v2[sel])
    return mg1.predict(s.assign(v2_mean=mu), bands, None)
