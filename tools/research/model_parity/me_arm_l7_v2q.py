"""Model-edge screen arm L7-V2Q (lever 7): captured NBM v2 QUANTILES read as a distribution.

Development screen only (dates <= 2026-09-29). The v2 registry tested the captured v2 values only as
Normal(v2_mean, max(v2_stddev, 1)) (r-t5-inc-c1 / MG-1 family); the captured v2 percentiles
v2_p10..v2_p90 were never read by any registered rule. This arm reads them, zero fitted parameters:

- Quantile knots q = 0.10, 0.25, 0.50, 0.75, 0.90 at v2_p10..v2_p90 (degrees, native unit). Tails are
  extended to q = 0.01 / 0.99 with the normal-quantile ratio of the outer segment
  (x01 = p10 - (p25 - p10) * 1.72076, x99 = p90 + (p90 - p75) * 1.72076) and the last 1% is spread
  uniformly over one more segment of the same length on each side.
- Minimum width: if p90 - p10 < 2 * 1.28155 (the width of a sigma = 1 normal), every knot is scaled about
  p50 to that width (the same sigma >= 1 guard MG-1 uses).
- X has the piecewise-linear CDF through the knots; mass on integer k is P(k - 0.5 <= X < k + 0.5).
- H = max(B, X) with B = floor_bucket (the harness rule-4 floor bucket, captured inputs only), exactly
  the r-t5-inc-c1 form; band probability = P(H in band).
- Only where v2_available_at <= captured_at_utc and all five quantiles exist; otherwise the row is
  omitted (served fallback).
"""
import numpy as np
import pandas as pd

NAME = "l7_v2_quantile_read"
FAMILY = "nbm_guidance_band"
READS_NBM_GUIDANCE = True
INPUTS = ("v2_p10", "v2_p25", "v2_p50", "v2_p75", "v2_p90", "v2_available_at")

Q = np.array([0.0, 0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99, 1.0])
TAIL = 1.72076          # (z(0.99) - z(0.90)) / (z(0.90) - z(0.75)) for a normal
MIN_WIDTH = 2 * 1.28155


def _knots(p10, p25, p50, p75, p90):
    width = p90 - p10
    if width < MIN_WIDTH:
        scale = MIN_WIDTH / width if width > 0 else None
        if scale is None:
            p10, p25, p75, p90 = p50 - 1.28155, p50 - 0.67449, p50 + 0.67449, p50 + 1.28155
        else:
            p10, p25, p75, p90 = (p50 + (x - p50) * scale for x in (p10, p25, p75, p90))
    x01 = p10 - max(p25 - p10, 1e-6) * TAIL
    x99 = p90 + max(p90 - p75, 1e-6) * TAIL
    x00 = x01 - (p10 - x01 if p10 > x01 else 1.0)
    x100 = x99 + (x99 - p90 if x99 > p90 else 1.0)
    x = np.array([x00, x01, p10, p25, p50, p75, p90, x99, x100], float)
    return np.maximum.accumulate(x + np.arange(len(x)) * 1e-9)


def _cdf(x_knots, v):
    return np.interp(v, x_knots, Q, left=0.0, right=1.0)


def build(snaps, bands):
    cols = ["v2_p10", "v2_p25", "v2_p50", "v2_p75", "v2_p90"]
    qv = snaps[cols].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, errors="coerce")
    fb = pd.to_numeric(snaps.floor_bucket, errors="coerce").to_numpy(float)
    ok = (~np.isnan(qv).any(axis=1) & avail.notna().to_numpy() & cap.notna().to_numpy()
          & (avail <= cap).to_numpy())
    n = snaps.n_bands.to_numpy().astype(int)
    offsets = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
    kind = bands.kind.to_numpy()
    low = bands.low.to_numpy(float)
    high = bands.high.to_numpy(float)
    out_p = []
    for i in np.flatnonzero(ok):
        xk = _knots(*qv[i])
        sl = slice(offsets[i], offsets[i] + n[i])
        k_lo, k_hi = kind[sl], (low[sl], high[sl])
        b = fb[i]
        lo_edge = np.where(k_lo == "lte", -np.inf, k_hi[0] - 0.5)
        hi_edge = np.where(k_lo == "gte", np.inf, k_hi[1] + 0.5)
        if np.isnan(b):
            p = _cdf(xk, hi_edge) - _cdf(xk, lo_edge)
        else:
            # H = max(B, X): mass of X below B + 0.5 collapses onto bucket B
            below = _cdf(xk, b + 0.5)
            upper = np.maximum(hi_edge, b + 0.5)
            lower = np.maximum(lo_edge, b + 0.5)
            holds_b = (lo_edge < b) & (hi_edge > b)
            p = np.where(hi_edge < b, 0.0,
                         np.where(holds_b, below + (_cdf(xk, upper) - _cdf(xk, b + 0.5)),
                                  _cdf(xk, upper) - _cdf(xk, lower)))
        out_p.append(np.clip(p, 0.0, None))
    idx = np.concatenate([np.arange(offsets[i], offsets[i] + n[i]) for i in np.flatnonzero(ok)]) \
        if ok.any() else np.array([], int)
    out = bands.iloc[idx][["row_key", "band_index"]].copy()
    out["p"] = np.concatenate(out_p) if out_p else np.array([], float)
    return out.reset_index(drop=True)
