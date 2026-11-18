"""L5 arm B: centre from lane L1's full-year PIT corpus (Open-Meteo Previous Runs gfs_seamless day-1 high).

Pre-registered in the addendum of ``docs/research/l5-hot-day-centre-preregistration-2026-10-24.md``. Fixed
parameters fitted only on 2021-2025 corpus pairs (``corpus_pairs.parquet``, union id
621bcd8e...; labels = WU daily max bucket), so every dev fold is out of sample. At serve the regressor is
the same product for the target date (lane G's ``day1_highs.parquet``, gfs_seamless,
``temperature_2m_previous_day1`` max over the 24 local hours; issued before the day starts, so point in
time). Per market: y = a_m + c_m * gfs_d1 (OLS). Inside 07-12 only; elsewhere and when missing, MG-1.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import l5_centre as C
from weather.reporting.scorecards.free_source_candidates import remaining_rise as rr

UNION = "621bcd8ea82ceed397bcfbdfae1c80664d1cb73adba3e71b240fae34db529cdc"
_CACHE = {}


def pairs():
    if "p" not in _CACHE:
        path = C.root() / "corpus_pairs.parquet"
        df = pd.read_parquet(path)
        if (df.date > "2025-12-31").any():
            raise AssertionError("corpus pair after 2025")
        _CACHE["p"] = (df, C.file_sha(path))
    return _CACHE["p"]


def day1():
    if "d" not in _CACHE:
        path = rr.research_root() / "openmeteo_previous_runs" / "day1_highs.parquet"
        df = pd.read_parquet(path)
        if (df.local_date > C.OBS_LAST).any():
            raise AssertionError("day-1 high after 2026-09-29")
        df = df[df.model == "gfs_seamless"].set_index(["station", "local_date"]).high_f
        _CACHE["d"] = (df, C.file_sha(path))
    return _CACHE["d"]


def fit_coefs(months=None):
    df, sha = pairs()
    if months is not None:
        df = df[df.month.isin(months)]
    coefs = {}
    for m, g in df.groupby("market"):
        X = np.column_stack([np.ones(len(g)), g.gfs_d1.to_numpy(float)])
        coefs[m] = np.linalg.lstsq(X, g.y.to_numpy(float), rcond=None)[0].tolist()
    return {"coefs": coefs, "provenance": {"union_sha256": UNION, "pairs_sha256": sha, "day1_sha256": day1()[1],
                                           "months": months, "coefs": coefs}}


def corpus_mu(state, s):
    d1, _ = day1()
    g = d1.reindex(pd.MultiIndex.from_arrays([s.station.astype(str), s.date.astype(str)])).to_numpy(float)
    ab = np.array([state["coefs"].get(m, [np.nan, np.nan]) for m in s.market.astype(str)], float)
    return ab[:, 0] + ab[:, 1] * g
