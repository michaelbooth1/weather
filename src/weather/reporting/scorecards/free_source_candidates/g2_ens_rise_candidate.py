"""Dev-scorecard candidate G2-b (13-16): t3-r3 conditioned on the ECMWF ENS gap.

Gap g = ens_mean - R (R = PIT METAR running max; ens_mean as in g2_ens_mg1), binned (-inf, -4], (-4, 0],
(0, 4], (4, inf) F, fixed a priori; cells as F3 (>= 30 history days, else the unconditioned t3-r3 cell).
The ENS value is used only from run + 9 h, in history and at serve. See remaining_rise and g2_ens.
"""
import numpy as np

from weather.reporting.scorecards.free_source_candidates import f1_common, g2_ens, remaining_rise as rr

NAME = "g2_ens_gap_rise"
BIN_EDGES = (-4.0, 0.0, 4.0)
_CACHE = {}


def cond(queries, r):
    ens, _ = g2_ens.lookup(queries.station, queries.local_date, queries.t)
    gap = ens - np.asarray(r, float)
    return np.where(np.isfinite(gap), np.digitize(gap, BIN_EDGES, right=True), -1)


def fit(train):
    metar, _, _, provenance = f1_common.inputs(None)
    if "table" not in _CACHE:
        _CACHE["table"] = rr.fit_table(metar, f1_common.tz_by_station(), None, cond=cond)
    table = _CACHE["table"]
    return {"table": table, "metar": metar,
            "provenance": dict(provenance, ens_points_sha256=g2_ens.points()[1], table_sha256=rr.table_digest(table),
                               table_cells=len(table))}


def predict(state, snaps, bands):
    return rr.predict_frame(state["table"], snaps, bands, state["metar"], None, cond=cond)
