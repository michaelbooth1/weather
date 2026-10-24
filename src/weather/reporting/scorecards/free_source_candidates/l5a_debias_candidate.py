"""L5 arm A candidate 1: walk-forward per-market debias of the captured NBM v2 mean and NWS grid high.

Pre-registered (``docs/research/l5-hot-day-centre-preregistration-2026-10-24.md``). Fit, per fold on its
training snapshots at local 07-12 only: for market m and product p in {v2_mean (MG-1 usable),
nws_grid_high_raw}, b[m, p] = mean(p - y) over m's training snapshots where p is present, kept only when they
span >= 5 training dates (else b = 0). Serve, 07-12: mu = mean over present p of (p - b[m, p]); v2 must be
usable (else no prediction, as MG-1); outside 07-12 = MG-1. Sigma, floor and availability are MG-1's.
"""
import numpy as np

from weather.reporting.scorecards.free_source_candidates import l5_centre as C

NAME = "l5a_debias_v2_nws"
PRODUCTS = ("v2_mean", "nws_grid_high_raw")


def _products(s):
    usable = C.v2_usable(s)
    return {"v2_mean": np.where(usable, C.num(s, "v2_mean"), np.nan),
            "nws_grid_high_raw": C.num(s, "nws_grid_high_raw")}


def fit(train):
    s = train["snapshots"].reset_index(drop=True)
    y = C.target(train)
    w = C.in_window(s) & np.isfinite(y)
    prods = _products(s)
    markets = s.market.astype(str).to_numpy()
    dates = s.date.astype(str).to_numpy()
    bias = {}
    for m in np.unique(markets):
        for p, v in prods.items():
            sel = w & (markets == m) & np.isfinite(v)
            if len(set(dates[sel])) >= C.MIN_DAYS:
                bias[(m, p)] = float(np.mean(v[sel] - y[sel]))
    return {"bias": bias, "provenance": {"rule": NAME, "cells": len(bias)}}


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    prods = _products(s)
    markets = s.market.astype(str).to_numpy()
    cols = []
    for p, v in prods.items():
        b = np.array([state["bias"].get((m, p), 0.0) for m in markets])
        cols.append(v - b)
    stack = np.vstack(cols)
    with np.errstate(invalid="ignore"):
        mu = np.where(np.isfinite(stack).any(axis=0), np.nanmean(np.where(np.isfinite(stack), stack, np.nan), axis=0),
                      np.nan)
    mu = np.where(np.isfinite(prods["v2_mean"]), mu, np.nan)
    return C.serve(s, bands, mu)
