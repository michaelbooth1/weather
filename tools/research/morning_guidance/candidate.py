"""Pure frozen C1/C2 weather-only distributions; no outcome or market input."""
from __future__ import annotations

import math
import numpy as np

from tools.research.missing_information.extract import finite
from tools.research.missing_information.methods import Band, band_probabilities, validate_bands


def candidates(bands, served, features):
    """Return C1, C2, eligibility reason; preserve exact fallback values."""
    bands = [Band(**b) if isinstance(b, dict) else b for b in bands]
    validate_bands(bands)
    p = np.asarray(served, dtype=float)
    if (p.shape != (len(bands),) or not np.isfinite(p).all() or (p < 0).any()
            or (p > 1).any() or abs(p.sum() - 1) > .005):
        raise ValueError("invalid captured served vector")
    def fallback(reason):
        return p.copy(), p.copy(), reason
    f = features
    q = [finite(f.get(f"nbm_prob_tmax_p{v}")) for v in (10, 25, 50, 75, 90)]
    mean, std = finite(f.get("nbm_prob_tmax_mean")), finite(f.get("nbm_prob_tmax_stddev"))
    if any(v is None for v in q + [mean, std]) or std <= 0:
        return fallback("incomplete_or_invalid_nbm")
    if any(a > b for a, b in zip(q, q[1:])):
        return fallback("unordered_quantiles")
    if f.get("nbm_prob_tmax_physical_valid_flag") != 1 or f.get("nbm_prob_tmax_impossible_flag") == 1:
        return fallback("not_recorded_valid")
    floors = [finite(f.get(k)) for k in ("guidance_physical_floor", "high_so_far", "trusted_current_max")]
    floors = [v for v in floors if v is not None]
    if not floors:
        return fallback("missing_captured_floor")
    floor = max(floors)
    try:
        c1 = band_probabilities(bands, q, mean, std, floor=floor)
    except ValueError:
        return fallback("invalid_cdf_or_zero_surviving_mass")
    c2 = .5 * p + .5 * c1
    impossible = np.array([b.kind != "gte" and b.high < math.floor(floor + .5) for b in bands])
    c2[impossible] = 0
    if c2.sum() <= 0:
        return fallback("zero_pool_mass")
    c2 /= c2.sum()
    return c1, c2, "eligible"
