r"""Lane L3 dev-window sensitivity candidates for the dev scorecard (``--candidate-module`` contract).

Development evidence only. Each module below exposes ``NAME``, ``fit(train)`` and
``predict(state, snaps, bands)`` and is fitted by ``dev_scorecard_data.module_predictions`` on each
scored walk-forward fold's training pool only (dates before the fold, gap 1): a date is never fitted
and scored by the same fit (dev_rule.md clarification 3).

- ``ols_floor_devfit`` (arm A, dev-fitted): OLS of the settlement bucket on forecast_high (2026 Previous
  Runs, lead 1), high_so_far (L8 ``running_max_since_midnight``) and current_temp, per (market, cutoff
  hour); Normal(mu, residual sd) on integers, hard floor at the observed high, as ``ols_floor``.
- ``ols_floor_nbm_devfit`` (arm A', dev-fitted): the same plus the NBM mean MG-1 uses (layout
  ``v2_mean``, only when available at capture) as a fourth regressor.
- ``intercept_twin``: MG-1 (``r-t5-inc-c1``) with mu = v2_mean + a_h at local hours 07-12, a_h the
  training mean of (settled band centre - v2_mean) per hour (>= 200 snapshots), no observation
  information; lane L6's stack (``l6_stack``) with the slope fixed at 0. Elsewhere MG-1 exactly.

Features come from L3's ``dev-emit`` ``dev_features.jsonl`` (env ``L3_DEV_FEATURES``), one record per
(market, target date, cutoff hour), built from captured replay inputs only. A snapshot whose local hour
precedes its cutoff hour, or with a missing feature, gets no prediction (served fallback).
Refuses to import on the capture host.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from weather.calibration.r0_ols_floor_challenger import (
    FEATURES,
    bucket_grid,
    discretised_normal,
    floor_of,
    ols_fit,
    ols_predict,
    refuse_production_import,
)

refuse_production_import()

MIN_TRAIN = 30
NBM_FEATURE = "nbm_mean"
_CACHE = {}


def features_path():
    value = os.environ.get("L3_DEV_FEATURES")
    if not value:
        raise RuntimeError("L3_DEV_FEATURES must name L3's dev_features.jsonl")
    return Path(value)


def dev_features():
    path = features_path()
    if path not in _CACHE:
        table = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rec = json.loads(line)
                    table[(rec["market"], rec["target_date"], int(rec["hour"]))] = rec
        _CACHE[path] = table
    return _CACHE[path]


def usable_v2_mean(snaps):
    import numpy as np
    import pandas as pd

    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, errors="coerce")
    mu = pd.to_numeric(snaps.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(snaps.v2_stddev, errors="coerce").to_numpy(float)
    ok = np.isfinite(mu) & np.isfinite(sd) & (avail <= cap).fillna(False).to_numpy()
    return np.where(ok, mu, np.nan)


def snapshot_records(snaps, with_nbm):
    """[(row_key, market, cutoff_hour, record | None)] for the frame's snapshots."""
    table = dev_features()
    nbm = usable_v2_mean(snaps)
    out = []
    for i, row in enumerate(snaps.itertuples(index=False)):
        try:
            hour = int(str(row.cutoff_hour))
        except ValueError:
            out.append((row.row_key, row.market, None, None))
            continue
        rec = table.get((row.market, str(row.target_date)[:10], hour))
        if rec is None or int(row.local_hour) < hour:
            out.append((row.row_key, row.market, hour, None))
            continue
        record = {"forecast_high": rec.get("pit_forecast_high"), "high_so_far": rec.get("high_so_far_l8"),
                  "current_temp": rec.get("current_temp")}
        if with_nbm:
            record[NBM_FEATURE] = None if not math.isfinite(nbm[i]) else float(nbm[i])
        if any(v is None for v in record.values()):
            record = None
        out.append((row.row_key, row.market, hour, record))
    return out


def _features(with_nbm):
    return tuple(FEATURES) + ((NBM_FEATURE,) if with_nbm else ())


def fit_ols(train, with_nbm):
    labels = train["labels"].set_index("row_key").settlement_bucket
    feats = _features(with_nbm)
    groups = {}
    for key, market, hour, record in snapshot_records(train["snapshots"], with_nbm):
        y = labels.get(key)
        if record is None or y is None or y != y:
            continue
        groups.setdefault((market, hour), []).append(([float(record[f]) for f in feats], float(y)))
    fits = {}
    for group, rows in groups.items():
        if len(rows) < MIN_TRAIN:
            continue
        xs, ys = [r[0] for r in rows], [r[1] for r in rows]
        beta, sd = ols_fit(xs, ys)
        fits[group] = {"beta": beta, "sd": sd, "n": len(rows), "y_lo": min(ys), "y_hi": max(ys)}
    return {"fits": fits, "features": feats, "with_nbm": with_nbm,
            "provenance": {"features_sha256": _sha256(features_path()), "features": list(feats),
                           "groups_fitted": len(fits)}}


def _sha256(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def band_frame(dists, bands):
    """Integer-degree distributions {row_key: {k: p}} onto the layout bands (as distribution_predictions)."""
    import numpy as np
    import pandas as pd

    b = bands[bands.row_key.isin(set(dists))]
    probs = []
    for rk, kind, low, high in zip(b.row_key, b.kind, b.low, b.high):
        d = dists[rk]
        if kind == "lte":
            probs.append(sum(p for k, p in d.items() if k <= high))
        elif kind == "gte":
            probs.append(sum(p for k, p in d.items() if k >= low))
        else:
            probs.append(sum(p for k, p in d.items() if low <= k <= high))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                         "p": np.asarray(probs, float)})


def predict_ols(state, snaps, bands):
    dists = {}
    for key, market, hour, record in snapshot_records(snaps, state["with_nbm"]):
        fit = state["fits"].get((market, hour))
        if record is None or fit is None:
            continue
        mu = ols_predict(fit["beta"], [float(record[f]) for f in state["features"]])
        floor = floor_of(record)
        support = list(range(int(math.floor(min(fit["y_lo"], mu))) - 15, int(math.ceil(max(fit["y_hi"], mu))) + 16))
        lo, hi = bucket_grid(support, floor)
        dists[key] = discretised_normal(mu, fit["sd"], lo, hi, floor)
    return band_frame(dists, bands)


INTERCEPT_HOURS = (7, 8, 9, 10, 11, 12)
INTERCEPT_MIN_N = 200


def fit_intercept(train):
    import numpy as np

    from weather.reporting.scorecards.free_source_candidates import l6_stack

    s = train["snapshots"].reset_index(drop=True)
    y = l6_stack.targets(train).reindex(s.row_key).to_numpy(float)
    v2 = l6_stack._usable_v2(s)
    hours = s.local_hour.to_numpy(int)
    coef = {}
    for h in INTERCEPT_HOURS:
        sel = (hours == h) & np.isfinite(y) & np.isfinite(v2)
        if sel.sum() < INTERCEPT_MIN_N:
            continue
        coef[h] = (float((y[sel] - v2[sel]).mean()), int(sel.sum()))
    return {"coef": coef, "provenance": {"rule": "l3_intercept_twin", "coef": {str(h): v for h, v in coef.items()}}}


def predict_intercept(state, snaps, bands):
    import pandas as pd

    from weather.reporting.scorecards.free_source_candidates import mg1

    s = snaps.reset_index(drop=True)
    v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    hours = s.local_hour.to_numpy(int)
    mu = v2.copy()
    for h, (a, _) in state["coef"].items():
        sel = hours == h
        mu[sel] = v2[sel] + a
    return mg1.predict(s.assign(v2_mean=mu), bands, None)
