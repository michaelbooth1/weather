"""Dev-scorecard candidate L4: per-station, per-hour inverse-MSE blend of NBM v2, GFS, ECMWF IFS and ICON.

Pre-registered in docs/research/forecast-blend-l4-preregistration-2026-10-24.md (rule text and sha256 fixed
before any result). Members per snapshot: NBM v2 mean (captured, usable when v2_available_at <= t) and the
Open-Meteo Previous Runs day-1 highs of gfs_seamless, ecmwf_ifs025 and icon_seamless for the station-local
date (point in time: issued before the day starts). Fit, per fold on its training snapshots only:
target y = centre of the settled band (eq: (low + high) / 2; lte: high; gte: low); per station and member a
mean bias b = mean(m - y); per station x local hour h a weight w_m proportional to 1 / mean((m - b - y)^2)
over training snapshots at hours h-1..h+1 (circular), members with < 20 such snapshots dropped. Serve:
mu = sum w_m (m - b_m) / sum w_m over available members, with MG-1's sigma and floor; covered only where
MG-1 covers (v2 usable), so the increment over MG-1 is the blend's alone.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import mg1, remaining_rise as rr

NAME = "l4_blend_invmse"
MEMBERS = ("gfs_seamless", "ecmwf_ifs025", "icon_seamless")
MIN_N = 20
_CACHE = {}


def day1():
    if "day1" not in _CACHE:
        path = rr.research_root() / "openmeteo_previous_runs" / "day1_highs.parquet"
        frame = pd.read_parquet(path)
        if (frame.local_date > rr.OBS_LAST).any():
            raise AssertionError("day-1 high after 2026-09-29")
        _CACHE["day1"] = (frame.pivot_table(index=["station", "local_date"], columns="model", values="high_f"),
                          rr.file_sha(path))
    return _CACHE["day1"]


def member_matrix(snaps):
    s = snaps.reset_index(drop=True)
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    v2 = np.where((avail <= t).fillna(False).to_numpy(), v2, np.nan)
    table, _ = day1()
    idx = pd.MultiIndex.from_arrays([s.station.astype(str), s.date.astype(str)])
    cols = {"nbm_v2_mean": v2}
    for m in MEMBERS:
        cols[m] = table[m].reindex(idx).to_numpy(float) if m in table else np.full(len(s), np.nan)
    return pd.DataFrame(cols)


def targets(train):
    lab = train["labels"].set_index("row_key").winner
    b = train["bands"]
    win = b[b.band_index.to_numpy(int) == lab.reindex(b.row_key).to_numpy()]
    centre = np.where(win.kind == "lte", win.high, np.where(win.kind == "gte", win.low, (win.low + win.high) / 2.0))
    return pd.Series(centre.astype(float), index=win.row_key.to_numpy())


def fit(train):
    s = train["snapshots"].reset_index(drop=True)
    y = targets(train).reindex(s.row_key).to_numpy(float)
    m = member_matrix(s)
    st = s.station.astype(str).to_numpy()
    hours = s.local_hour.to_numpy(int)
    bias, weights = {}, {}
    for station in np.unique(st):
        sel = st == station
        for col in m.columns:
            err = m[col].to_numpy(float)[sel] - y[sel]
            err = err[np.isfinite(err)]
            if len(err) >= MIN_N:
                bias[(station, col)] = float(err.mean())
        for h in range(24):
            near = sel & np.isin(hours, [(h - 1) % 24, h, (h + 1) % 24])
            w = {}
            for col in m.columns:
                if (station, col) not in bias:
                    continue
                e = m[col].to_numpy(float)[near] - bias[(station, col)] - y[near]
                e = e[np.isfinite(e)]
                if len(e) >= MIN_N:
                    w[col] = 1.0 / max(float(np.mean(e ** 2)), 1e-6)
            if w:
                weights[(station, h)] = w
    return {"bias": bias, "weights": weights,
            "provenance": {"rule": NAME, "day1_sha256": day1()[1], "cells": len(weights)}}


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    m = member_matrix(s)
    mu = np.full(len(s), np.nan)
    st = s.station.astype(str).to_numpy()
    hours = s.local_hour.to_numpy(int)
    mm, ci = m.to_numpy(float), {c: k for k, c in enumerate(m.columns)}
    for i in range(len(s)):
        if not np.isfinite(mm[i, 0]):
            continue
        w = state["weights"].get((st[i], int(hours[i])))
        if not w:
            continue
        num = den = 0.0
        for col, wt in w.items():
            v = mm[i, ci[col]]
            if np.isfinite(v):
                num += wt * (v - state["bias"][(st[i], col)])
                den += wt
        if den > 0:
            mu[i] = num / den
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    return mg1.predict(s.assign(v2_mean=np.where(np.isfinite(mu), mu, v2)), bands, None)
