"""Lane L5 hot-day centre lever: shared inputs for the ``l5_*_candidate.py`` dev-scorecard modules.

Research only (development dates <= 2026-09-29). Pre-registration:
``docs/research/l5-hot-day-centre-preregistration-2026-10-24.md`` (sha256 recorded there and in the result).
Nothing in capture, serving or trading imports this; it reads the layout columns handed to fit/predict plus
two L5 research tables under ``L5_ROOT`` (default ``C:\\t\\l5\\inputs``) built by
``tools/research/morning_loss/extract_regimes.py`` from the captured replay inputs.

Every candidate keeps MG-1's sigma, floor and availability rule and changes only mu inside 07-12 local, so
its paired increment over the MG-1 control is the centre change alone; outside 07-12 it equals MG-1.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import mg1

DEFAULT_ROOT = r"C:\t\l5\inputs"
OBS_LAST = "2026-09-29"
W_LO, W_HI = 7, 12
MIN_DAYS = 5
OBS_LAG_MIN = 10
_CACHE = {}


def root():
    return Path(os.environ.get("L5_ROOT", DEFAULT_ROOT))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tables():
    if "t" not in _CACHE:
        obs_p, reg_p = root() / "obs_hourly.parquet", root() / "regimes_all.parquet"
        obs, reg = pd.read_parquet(obs_p), pd.read_parquet(reg_p)
        if (obs.date > OBS_LAST).any() or (reg.date > OBS_LAST).any():
            raise AssertionError("L5 input dated after 2026-09-29")
        obs = obs.assign(t_utc=pd.to_datetime(obs.label_time, utc=True))
        _CACHE["t"] = (obs, reg.set_index(["market", "date"]).fc_min_00_08,
                       {"obs_hourly_sha256": file_sha(obs_p), "regimes_all_sha256": file_sha(reg_p)})
    return _CACHE["t"]


def num(snaps, col):
    return pd.to_numeric(snaps[col], errors="coerce").to_numpy(float)


def v2_usable(snaps):
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(snaps.captured_at_utc, utc=True)
    return np.isfinite(num(snaps, "v2_mean")) & (avail <= t).fillna(False).to_numpy()


def in_window(snaps):
    h = snaps.local_hour.to_numpy(int)
    return (h >= W_LO) & (h <= W_HI)


def overnight_low_anomaly(snaps):
    """PIT: min METAR temp over on-date rows labelled 01..08 with label_time + 10 min <= captured_at_utc,
    minus the Open-Meteo forecast 00-08 minimum from the first on-date capture. NaN when either is missing."""
    obs, fc_min, _ = tables()
    s = snaps.reset_index(drop=True)
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    o = obs[(obs.label_hour >= 1) & (obs.label_hour <= 8)]
    groups = {k: g for k, g in o.groupby(["market", "date"])}
    out = np.full(len(s), np.nan)
    lag = pd.Timedelta(minutes=OBS_LAG_MIN)
    for i, (m, d, ti) in enumerate(zip(s.market.astype(str), s.date.astype(str), t)):
        g = groups.get((m, d))
        f = fc_min.get((m, d), np.nan)
        if g is None or not np.isfinite(f):
            continue
        seen = g.temp_f.to_numpy(float)[(g.t_utc + lag <= ti).to_numpy()]
        if len(seen):
            out[i] = float(seen.min()) - float(f)
    return out


def target(train):
    """y = settled degree (layout ``settlement_bucket``), per training snapshot."""
    lab = train["labels"].set_index("row_key").settlement_bucket
    return lab.reindex(train["snapshots"].row_key).to_numpy(float)


def serve(snaps, bands, mu_window):
    """MG-1 with mu replaced inside 07-12 where ``mu_window`` is finite."""
    s = snaps.reset_index(drop=True)
    v2 = num(s, "v2_mean")
    mu = np.where(in_window(s) & np.isfinite(mu_window), mu_window, v2)
    return mg1.predict(s.assign(v2_mean=mu), bands, None)
