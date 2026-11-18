"""Dev-scorecard candidate: lane L6's own-obs stack on nowcasts built from the captured METAR rows.

MG-2 pick rule clarification 2 (e). The nowcasts come from ``r0_ols_floor_challenger l6-captured``
(env ``L6_CAPTURED_NOWCASTS``); the stack itself is L6's ``l6_stack`` fit and predict, unchanged. Only the
nowcast table it reads is swapped for the duration of each call, so L6's own candidate can be scored
alongside it in the same run.
"""
import os
from pathlib import Path

import pandas as pd

from weather.reporting.scorecards.free_source_candidates import l6_stack, remaining_rise as rr

NAME = "l6_own_stack_captured"
_TABLE = {}


def _captured():
    if "n" not in _TABLE:
        path = Path(os.environ["L6_CAPTURED_NOWCASTS"])
        _TABLE["n"] = (pd.read_parquet(path).set_index("row_key"), rr.file_sha(path))
    return _TABLE["n"]


def _swapped(fn, *args):
    saved = l6_stack._CACHE.get("n")
    l6_stack._CACHE["n"] = _captured()
    try:
        return fn(*args)
    finally:
        if saved is None:
            l6_stack._CACHE.pop("n", None)
        else:
            l6_stack._CACHE["n"] = saved


def fit(train):
    return _swapped(l6_stack.fit, train, "n_own", NAME)


def predict(state, snaps, bands):
    return _swapped(l6_stack.predict, state, snaps, bands)
