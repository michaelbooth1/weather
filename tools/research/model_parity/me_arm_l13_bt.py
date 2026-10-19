"""Model-edge screen arm L13-BT (lever 5 open stage 9, screened for lever 13): bucket-transition prior
re-pointed on the observed station high at the cutoff, as a STAGE-LEVEL approximation.

Development screen only (dates <= 2026-09-29). Serving (`model_distribution.py`
`distribution_bucket_transition_stage`) blends the bucket-transition prior into the score
distribution with weight `bucket_transition_blend_weight`; since WU was disabled the prior's input
(the WU cutoff-aligned high) is empty, so the stage is a no-op. Lever 5 (`model-edge-lever5-2026-10-19.md`
section 3.2) measured that re-pointing it on the captured `high_so_far` activates it on 13.3% of dev
snapshots with weight 0.012-0.0588.

This arm applies the stage's own prior and weight (serving code, constants unchanged, prior-year
climatology from the workstation's `data/wunderground` copy; the serving cache drops every row of the
target year) to the FINAL served band vector: p = (1 - w) * p_served + w * P_prior(band). That is an
approximation: serving blends before the floors, lock-ins and calibration, so the final-vector effect
needs the host replay (lever 5 section 3.4). Rows where the prior is inactive (w = 0) are omitted
(served fallback). Zero fitted parameters.
"""
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

NAME = "l13_bucket_transition_stage"
FAMILY = "serving_stage_bucket_transition"
READS_NBM_GUIDANCE = False
INPUTS = ("high_so_far", "cutoff_hour")
CLIMATOLOGY_DATA_ROOT = Path(r"C:\Users\Michael\Documents\github\weather\data")


def _models():
    import weather.paths
    weather.paths.DATA_ROOT = CLIMATOLOGY_DATA_ROOT
    from weather.model.model_distribution_constants import BUCKET_TRANSITION_MIN_SAMPLE
    from weather.model.toronto_model import TorontoHighTempModel
    cache = {}

    def get(market):
        if market not in cache:
            cache[market] = TorontoHighTempModel(market_id=market)
        return cache[market]
    return get, BUCKET_TRANSITION_MIN_SAMPLE


def _prior(model, high, cutoff, min_sample):
    model.cutoff_aligned_wu_history_max_native = lambda history, ch, _v=float(high): _v
    model.effective_intraday_cutoff_hour = lambda now, rws, _c=int(cutoff): _c
    try:
        bt = model.bucket_transition_model({}, datetime(2000, 1, 1, int(cutoff), 0), min_sample_size=min_sample)
    finally:
        del model.cutoff_aligned_wu_history_max_native
        del model.effective_intraday_cutoff_hour
    probs = bt.get("probabilities") or {}
    weight = model.bucket_transition_blend_weight(bt) if probs else 0.0
    return {int(k): float(v) for k, v in probs.items()}, float(weight)


def build(snaps, bands):
    get, min_sample = _models()
    hs = pd.to_numeric(snaps.high_so_far, errors="coerce").to_numpy(float)
    ch = pd.to_numeric(snaps.cutoff_hour, errors="coerce").to_numpy(float)
    n = snaps.n_bands.to_numpy().astype(int)
    offsets = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
    kind, low, high = bands.kind.to_numpy(), bands.low.to_numpy(float), bands.high.to_numpy(float)
    ps = bands.p_served.to_numpy(float)
    memo = {}
    idx_parts, p_parts = [], []
    markets = snaps.market.astype(str).to_numpy()
    dates = snaps.date.astype(str).to_numpy()
    order = np.lexsort((dates, markets))
    current = None
    for i in order:
        if np.isnan(hs[i]) or np.isnan(ch[i]):
            continue
        model = get(markets[i])
        if current != (markets[i], dates[i]):
            model.set_target_date(date.fromisoformat(dates[i]))
            current = (markets[i], dates[i])
        key = (markets[i], dates[i], int(ch[i]), model.round_half_up(float(hs[i])))
        if key not in memo:
            memo[key] = _prior(model, hs[i], ch[i], min_sample)
        probs, w = memo[key]
        if w <= 0 or not probs:
            continue
        sl = slice(offsets[i], offsets[i] + n[i])
        ks = np.array(sorted(probs), float)
        pv = np.array([probs[int(k)] for k in ks], float)
        pv = pv / pv.sum()
        lo = np.where(kind[sl] == "lte", -np.inf, low[sl])
        hi = np.where(kind[sl] == "gte", np.inf, high[sl])
        pb = ((ks[None, :] >= lo[:, None]) & (ks[None, :] <= hi[:, None])).astype(float) @ pv
        idx_parts.append(np.arange(offsets[i], offsets[i] + n[i]))
        p_parts.append((1.0 - w) * ps[sl] + w * pb)
    if not idx_parts:
        return pd.DataFrame({"row_key": [], "band_index": [], "p": []})
    idx = np.concatenate(idx_parts)
    out = bands.iloc[idx][["row_key", "band_index"]].copy()
    out["p"] = np.concatenate(p_parts)
    return out.reset_index(drop=True)
