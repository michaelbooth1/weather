"""Dev-scorecard candidate F3: t3-r3 conditioned on the 12Z-sounding mixed-layer cap.

T_cap = the 850 hPa temperature (700 hPa at KDNR, whose surface is near 850 hPa) of the nearest
site's 12Z sounding on the station-local date, brought dry-adiabatically to the sounding's surface
pressure, in F. Gap g = T_cap - R (R = PIT METAR running max) is binned (-inf, 0], (0, 4], (4, 8],
(8, inf) and the t3-r3 remaining-rise pmf is looked up per (station, month, hour, bin), backing off
to the unconditioned t3-r3 cell when a bin has < 30 history days. The sounding counts only from
valid + 2 h (available 14:00Z), both in history and at serve. See remaining_rise.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import f1_common, remaining_rise as rr
from weather.sources.free_screens import iem_raob

NAME = "f3_sounding_cap_gap"
BIN_EDGES = (0.0, 4.0, 8.0)
KAPPA = 0.2857
_CACHE = {}


def caps():
    """DataFrame station, local_date, avail_utc, tcap_f for every 12Z sounding."""
    if "caps" in _CACHE:
        return _CACHE["caps"]
    path = rr.research_root() / iem_raob.SOURCE / "levels.parquet"
    lev = pd.read_parquet(path)
    lev = lev[lev.valid_utc.dt.hour == 12]
    rows = []
    for (site, valid), g in lev.groupby(["site", "valid_utc"]):
        g = g.dropna(subset=["pressure_mb"]).sort_values("pressure_mb", ascending=False)
        if g.empty:
            continue
        psfc = float(g.pressure_mb.iloc[0])
        ref = 700.0 if site == "KDNR" else 850.0
        hit = g[(g.pressure_mb - ref).abs() < 0.05].dropna(subset=["tmpc"])
        if hit.empty or psfc <= ref:
            continue
        theta = (float(hit.tmpc.iloc[0]) + 273.15) * (1000.0 / ref) ** KAPPA
        tk = theta * (psfc / 1000.0) ** KAPPA
        rows.append((site, valid, (tk - 273.15) * 1.8 + 32.0))
    frame = pd.DataFrame(rows, columns=["site", "valid_utc", "tcap_f"])
    site_of = {st: v[0] for st, v in iem_raob.nearest_sites().items()}
    out = []
    for st, site in site_of.items():
        f = frame[frame.site == site].copy()
        f["station"] = st
        # 12Z is morning in every US zone, so the UTC date of a 12Z sounding is the local date
        f["local_date"] = f.valid_utc.dt.strftime("%Y-%m-%d")
        f["avail_utc"] = f.valid_utc + pd.Timedelta(hours=iem_raob.AVAILABLE_AFTER_H)
        out.append(f[["station", "local_date", "avail_utc", "tcap_f"]])
    result = pd.concat(out, ignore_index=True).drop_duplicates(["station", "local_date"])
    if (result.local_date > rr.OBS_LAST).any():
        raise AssertionError("sounding after 2026-09-29")
    _CACHE["caps"] = (result, rr.file_sha(path))
    return _CACHE["caps"]


def cond(queries, r):
    frame, _ = caps()
    m = queries[["station", "local_date", "t"]].reset_index(drop=True).merge(
        frame, on=["station", "local_date"], how="left")
    t = pd.to_datetime(m.t, utc=True)
    ok = m.tcap_f.notna() & (m.avail_utc <= t) & np.isfinite(np.asarray(r, float))
    gap = m.tcap_f.to_numpy(float) - np.asarray(r, float)
    bins = np.digitize(gap, BIN_EDGES, right=True)
    return np.where(ok.to_numpy(), bins, -1)


def fit(train):
    metar, _, _, provenance = f1_common.inputs(None)
    if "table" not in _CACHE:
        _CACHE["table"] = rr.fit_table(metar, f1_common.tz_by_station(), None, cond=cond)
    table = _CACHE["table"]
    prov = dict(provenance, raob_levels_sha256=caps()[1], table_sha256=rr.table_digest(table),
                table_cells=len(table))
    return {"table": table, "metar": metar, "provenance": prov}


def predict(state, snaps, bands):
    return rr.predict_frame(state["table"], snaps, bands, state["metar"], None, cond=cond)
