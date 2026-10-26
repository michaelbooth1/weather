"""Dev-scorecard candidate for rule R-PD gate 2: lane L6's own-obs stack at local hours 00-06.

The stack is L6's ``l6_stack`` fit and predict, unchanged in form (per-hour OLS, b clipped to [0, 1], >= 200 rows,
sigma = max(v2_stddev, 1), MG-1's floor and band mapping). Two things are swapped for the duration of each call:
the nowcast table (env ``PREDAWN_NOWCASTS``, built by ``weather.calibration.predawn_0006 serve`` on captured METAR)
and the stacked hours (00..06 instead of 07..12). Walk-forward is the scorecard's own contract.
"""
import os
from pathlib import Path

import pandas as pd

from weather.reporting.scorecards.free_source_candidates import l6_stack, remaining_rise as rr

NAME = "predawn_l6_own_stack_captured_0006"
HOURS = (0, 1, 2, 3, 4, 5, 6)
_TABLE = {}


def _table():
    if "n" not in _TABLE:
        path = Path(os.environ["PREDAWN_NOWCASTS"])
        _TABLE["n"] = (pd.read_parquet(path).set_index("row_key"), rr.file_sha(path))
    return _TABLE["n"]


def _swapped(fn, *args):
    saved_n, saved_hours = l6_stack._CACHE.get("n"), l6_stack.HOURS
    l6_stack._CACHE["n"] = _table()
    l6_stack.HOURS = HOURS
    try:
        return fn(*args)
    finally:
        l6_stack.HOURS = saved_hours
        if saved_n is None:
            l6_stack._CACHE.pop("n", None)
        else:
            l6_stack._CACHE["n"] = saved_n


def fit(train):
    return _swapped(l6_stack.fit, train, "n_own", NAME)


def predict(state, snaps, bands):
    return _swapped(l6_stack.predict, state, snaps, bands)
