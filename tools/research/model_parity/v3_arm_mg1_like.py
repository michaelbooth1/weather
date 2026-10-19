"""HARNESS v3 control arm: an MG-1-LIKE v2 guidance read (re-implemented; MG-1 itself is untouched).

Normal(v2_mean, max(v2_stddev, 1)) integrated over each band's half-degree edges, only where the v2
value was available at or before the snapshot. Rows without it are omitted (served fallback).
Used for controls on development dates only; it is not the signed MG-1 vector.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

NAME = "mg1_like_v2_read"
FAMILY = "nbm_guidance_band"
READS_NBM_GUIDANCE = True
INPUTS = ("v2_mean", "v2_stddev", "v2_available_at")


def build(snaps, bands):
    mean = pd.to_numeric(snaps.v2_mean, errors="coerce")
    sd = pd.to_numeric(snaps.v2_stddev, errors="coerce").clip(lower=1.0)
    avail = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, errors="coerce")
    ok = (mean.notna() & sd.notna() & avail.notna() & cap.notna() & (avail <= cap)).to_numpy()
    n = snaps.n_bands.to_numpy().astype(int)
    keep = np.repeat(ok, n)
    mu, sig = np.repeat(mean.to_numpy(float), n), np.repeat(sd.to_numpy(float), n)
    kind = bands.kind.to_numpy()
    lo = np.where(kind == "lte", -np.inf, bands.low.to_numpy(float) - 0.5)
    hi = np.where(kind == "gte", np.inf, bands.high.to_numpy(float) + 0.5)
    p = norm.cdf((hi - mu) / sig) - norm.cdf((lo - mu) / sig)
    out = bands.loc[keep, ["row_key", "band_index"]].copy()
    out["p"] = p[keep]
    return out.reset_index(drop=True)
