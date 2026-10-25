"""ECMWF ENS station-point helpers for the G2 screen (reads only ``ecmwf_ens/points.parquet``).

The table is written in the research venv by ``weather.sources.free_screens.ecmwf_ens`` (eccodes);
this module needs only pandas. For a query at UTC time t on station-local target date D, the ENS value
is the newest 00Z run with available_utc (run + 9 h) <= t that carries D: the same-day run once it is
available, otherwise the previous day's run (its +42..48 h steps).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import remaining_rise as rr

_CACHE = {}


def points():
    if "points" not in _CACHE:
        path = rr.research_root() / "ecmwf_ens" / "points.parquet"
        frame = pd.read_parquet(path)
        frame = frame[frame.n_members >= 40].copy()
        if (frame.target_date > rr.OBS_LAST).any():
            raise AssertionError("ENS target date after 2026-09-29")
        frame["available_utc"] = pd.to_datetime(frame.available_utc, utc=True).astype("datetime64[us, UTC]")
        _CACHE["points"] = (frame.sort_values("available_utc"), rr.file_sha(path))
    return _CACHE["points"]


def lookup(stations, local_dates, times):
    """-> (ens_mean_f, ens_sd_f) arrays aligned with the inputs; NaN when no run is available."""
    frame, _ = points()
    q = pd.DataFrame({"station": np.asarray(stations, str), "target_date": np.asarray(local_dates, str),
                      "t": pd.to_datetime(pd.Series(times), utc=True).astype("datetime64[us, UTC]").to_numpy()})
    q["pos"] = np.arange(len(q))
    q["key"] = q.station + "|" + q.target_date
    f = frame.assign(key=frame.station + "|" + frame.target_date)[["key", "available_utc", "ens_mean_f", "ens_sd_f"]]
    j = pd.merge_asof(q.sort_values("t"), f, left_on="t", right_on="available_utc", by="key",
                      direction="backward").sort_values("pos")
    ok = j.available_utc.notna()
    if (j.available_utc[ok] > j.t[ok]).any():
        raise AssertionError("point-in-time violation in ENS lookup")
    return j.ens_mean_f.to_numpy(float), j.ens_sd_f.to_numpy(float)
