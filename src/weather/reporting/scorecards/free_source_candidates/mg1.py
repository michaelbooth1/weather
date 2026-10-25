"""MG-1 (registered ``r-t5-inc-c1``, EF 10h/10j) and the F4 per-member recentring of it.

MG-1, verbatim rule: if captured v2_mean, v2_stddev and v2_available_at exist and v2_available_at <=
captured_at_utc, mu = v2_mean, sigma = max(v2_stddev, 1); X ~ Normal(mu, sigma) discretised on
integers; H = max(B, X), B = floor(F + 0.5), F = the rule-4 floor; band probability = P(H in band)
(``t5_nbh_latest.band_probs``); otherwise no prediction (served fallback).

F4 (per captured Open-Meteo member m, zero parameters): identical except mu = (v2_mean + high_m) / 2,
where high_m is that member's captured ``day_model_highs`` value at the same snapshot. Where the member
is missing the snapshot keeps MG-1, so the increment over MG-1 is the member's alone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import ndtr

from weather.reporting.scorecards.free_source_candidates import remaining_rise as rr
from weather.sources.free_screens import captured_openmeteo

_CACHE = {}


def band_probs(kind, low, high, B, mu, sig):
    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, ndtr((up - mu) / sig) - ndtr((lo - mu) / sig), 0.0)
    return np.clip(p, 0.0, None)


def members():
    if "members" not in _CACHE:
        path, manifest = captured_openmeteo.extract(rr.replay_inbox(), rr.research_root(),
                                                    log=lambda m: print(m, flush=True))
        _CACHE["members"] = (pd.read_parquet(path), manifest)
    return _CACHE["members"]


def predict(snaps, bands, member=None):
    s = snaps.reset_index(drop=True)
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    mu = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & (avail <= t).fillna(False).to_numpy()
    if member is not None:
        frame, _ = members()
        hm = frame.set_index("row_key")[member].reindex(s.row_key).to_numpy(float) if member in frame else \
            np.full(len(s), np.nan)
        mu = np.where(np.isfinite(hm), (mu + hm) / 2.0, mu)
    floor = pd.to_numeric(s["floor"], errors="coerce").to_numpy(float)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    grouped = {k: g for k, g in bands.groupby("row_key", sort=False)}
    rk, bi, pp = [], [], []
    for i in np.flatnonzero(ok):
        key = s.row_key.iloc[i]
        g = grouped.get(key)
        if g is None:
            continue
        p = band_probs(g.kind.to_numpy(), g.low.to_numpy(), g.high.to_numpy(), B[i], mu[i], max(sd[i], 1.0))
        rk.extend([key] * len(g))
        bi.extend(g.band_index.to_numpy(int).tolist())
        pp.extend(p.tolist())
    return pd.DataFrame({"row_key": rk, "band_index": np.asarray(bi, int), "p": np.asarray(pp, float)})


def provenance(member=None):
    if member is None:
        return {"rule": "r-t5-inc-c1 (MG-1)", "inputs": "layout v2_mean/v2_stddev/v2_available_at/floor"}
    _, manifest = members()
    return {"rule": f"MG-1 recentred on (v2_mean + {member}) / 2", "members_sha256": manifest["sha256"],
            "member_fill": manifest["fill"].get(member), "inbox_sha256sums": manifest["inbox_sha256sums"]}
