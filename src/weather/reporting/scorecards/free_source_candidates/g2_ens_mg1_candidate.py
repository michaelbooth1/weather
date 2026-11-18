"""Dev-scorecard candidate G2-a (00-12): MG-1 recentred halfway to the bias-adjusted ECMWF ENS mean.

mu = (v2_mean + ens_mean - b_station) / 2, sigma = max(v2_stddev, 1) (MG-1's). ens_mean = mean over the
51 members of each member's max of 2 m temperature at 18, 21 and 00 UTC for the target date (station
bilinear). b_station = median of (ens_mean - v2_mean) over the fold's training snapshots where both exist
(inputs only; labels are never read). Without ENS or b the snapshot keeps MG-1. See g2_ens and mg1.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import g2_ens, mg1

NAME = "g2_ens_mg1_half"


def _ens(snaps):
    return g2_ens.lookup(snaps.station, snaps.date, snaps.captured_at_utc)[0]


def _usable_v2(snaps):
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    t = pd.to_datetime(snaps.captured_at_utc, utc=True)
    v2 = pd.to_numeric(snaps.v2_mean, errors="coerce").to_numpy(float)
    return np.where((avail <= t).fillna(False).to_numpy(), v2, np.nan)


def fit(train):
    s = train["snapshots"].reset_index(drop=True)
    diff = _ens(s) - _usable_v2(s)
    frame = pd.DataFrame({"station": s.station.astype(str), "d": diff}).dropna()
    bias = frame.groupby("station").d.median().to_dict()
    return {"bias": bias, "provenance": {"rule": NAME, "ens_points_sha256": g2_ens.points()[1]}}


def predict(state, snaps, bands):
    s = snaps.reset_index(drop=True)
    ens = _ens(s)
    b = s.station.astype(str).map(state["bias"]).to_numpy(float)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    shifted = np.where(np.isfinite(ens) & np.isfinite(b), (v2 + ens - b) / 2.0, v2)
    return mg1.predict(s.assign(v2_mean=shifted), bands, None)
