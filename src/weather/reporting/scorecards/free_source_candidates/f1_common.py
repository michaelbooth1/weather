"""Shared fit/predict for the F1 screen and its t3-r3 control (see ``remaining_rise``)."""
from __future__ import annotations

import pandas as pd

from weather.reporting.scorecards.free_source_candidates import remaining_rise as rr
from weather.sources.free_screens import common

_CACHE = {}


def tz_by_station():
    return {s.icao: s.timezone for s in common.us_stations()}


def inputs(spec):
    key = spec.name if spec else "control"
    if key in _CACHE:
        return _CACHE[key]
    tz = tz_by_station()
    metar, shas = rr.load_metar(sorted(tz))
    hf = None
    provenance = {"metar_sha256": shas}
    if spec is not None:
        path = rr.research_root() / "iem_onemin" / "onemin.parquet"
        onemin = pd.read_parquet(path)
        provenance["onemin_sha256"] = rr.file_sha(path)
        hf = rr.hf_series(onemin, tz, spec)
    table = rr.fit_table(metar, tz, hf)
    provenance["table_sha256"] = rr.table_digest(table)
    provenance["table_cells"] = len(table)
    _CACHE[key] = (metar, hf, table, provenance)
    return _CACHE[key]


def fit(train, spec):
    """The table is fixed from history <= 2026-07-31 (before every development date), so every fold
    gets the same state; ``train`` (fold labels) is never read."""
    metar, hf, table, provenance = inputs(spec)
    return {"table": table, "metar": metar, "hf": hf, "provenance": provenance}


def predict(state, snaps, bands):
    return rr.predict_frame(state["table"], snaps, bands, state["metar"], state["hf"])
