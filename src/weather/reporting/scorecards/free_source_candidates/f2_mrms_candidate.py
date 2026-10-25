"""Dev-scorecard candidate F2: t3-r3 conditioned on an MRMS echo flag within 25 km.

Bin 1 if the newest sampled MRMS composite-reflectivity slot with valid + 5 min <= t and valid >=
t - 40 min has max >= 35 dBZ within 25 km of the station; bin 0 if that slot is below 35 dBZ; no bin
(unconditioned t3-r3 cell) if there is no such slot. See remaining_rise and weather.sources.free_screens.mrms.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import f1_common, remaining_rise as rr
from weather.sources.free_screens import mrms

NAME = "f2_mrms_echo25"
THRESHOLD_DBZ = 35.0
WINDOW_MIN = 40
_CACHE = {}


def refl():
    if "refl" not in _CACHE:
        path = rr.research_root() / mrms.SOURCE / "station_refl.parquet"
        frame = pd.read_parquet(path)
        frame["avail_utc"] = (frame.valid_utc + pd.Timedelta(minutes=mrms.LATENCY_MIN)).astype("datetime64[us, UTC]")
        frame = frame.dropna(subset=["max_dbz_25km"]).sort_values("avail_utc")
        if (frame.valid_utc.dt.strftime("%Y-%m-%d") > "2026-09-30").any():
            raise AssertionError("MRMS row after the development window")
        _CACHE["refl"] = (frame, rr.file_sha(path))
    return _CACHE["refl"]


def cond(queries, r):
    frame, _ = refl()
    q = queries[["station", "t"]].reset_index(drop=True).copy()
    q["pos"] = np.arange(len(q))
    q["t"] = pd.to_datetime(q.t, utc=True).astype("datetime64[us, UTC]")
    j = pd.merge_asof(q.sort_values("t"), frame[["station", "avail_utc", "valid_utc", "max_dbz_25km"]],
                      left_on="t", right_on="avail_utc", by="station", direction="backward").sort_values("pos")
    fresh = j.valid_utc.notna() & (j.valid_utc >= j.t - pd.Timedelta(minutes=WINDOW_MIN))
    if (j.avail_utc[fresh] > j.t[fresh]).any():
        raise AssertionError("point-in-time violation in MRMS lookup")
    return np.where(fresh.to_numpy(), (j.max_dbz_25km.to_numpy(float) >= THRESHOLD_DBZ).astype(int), -1)


def fit(train):
    metar, _, _, provenance = f1_common.inputs(None)
    if "table" not in _CACHE:
        _CACHE["table"] = rr.fit_table(metar, f1_common.tz_by_station(), None, cond=cond)
    table = _CACHE["table"]
    prov = dict(provenance, mrms_sha256=refl()[1], table_sha256=rr.table_digest(table), table_cells=len(table))
    return {"table": table, "metar": metar, "provenance": prov}


def predict(state, snaps, bands):
    return rr.predict_frame(state["table"], snaps, bands, state["metar"], None, cond=cond)
