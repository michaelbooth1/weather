"""Probability and crossed-cluster estimators, independent of production data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

import numpy as np
import pandas as pd
from scipy.special import ndtr


@dataclass(frozen=True)
class Band:
    kind: str
    low: int
    high: int

    @property
    def edges(self):
        return (
            -math.inf if self.kind == "lte" else self.low - 0.5,
            math.inf if self.kind == "gte" else self.high + 0.5,
        )

    def contains(self, bucket):
        return ((self.kind == "lte" or bucket >= self.low)
                and (self.kind == "gte" or bucket <= self.high))


def validate_bands(bands):
    """Reject incomplete/overlapping supports rather than normalizing them away."""
    if len(bands) < 2 or bands[0].kind != "lte" or bands[-1].kind != "gte":
        raise ValueError("bands must cover both infinite tails")
    if any(b.kind not in {"lte", "eq", "gte"} or b.low > b.high for b in bands):
        raise ValueError("invalid band")
    if any(a.edges[1] != b.edges[0] for a, b in zip(bands, bands[1:])):
        raise ValueError("bands have a gap or overlap")


def quantile_cdf(x, quantiles, mean, std):
    """Linear quantile CDF; normal tails scaled to meet p10 and p90 exactly.

    Equal quantiles represent atoms; use the right-continuous CDF. Temperature
    integration edges are half degrees, matching canonical floor(value + .5).
    """
    q = np.asarray(quantiles, dtype=float)
    p = np.array([.10, .25, .50, .75, .90])
    if q.shape != (5,) or not np.isfinite(q).all() or (np.diff(q) < 0).any():
        raise ValueError("five finite nondecreasing quantiles required")
    if not np.isfinite(mean) or not np.isfinite(std) or std <= 0:
        raise ValueError("finite mean and positive stddev required")
    x = np.asarray(x, dtype=float)
    result = np.interp(x, q, p)
    left = x < q[0]
    right = x > q[-1]
    left_scale = ndtr((q[0] - mean) / std)
    right_scale = ndtr((mean - q[-1]) / std)
    if left_scale <= 0 or right_scale <= 0:
        raise ValueError("normal tail underflow")
    result = np.where(left, .1 * ndtr((x - mean) / std) / left_scale, result)
    result = np.where(right, 1 - .1 * ndtr((mean - x) / std) / right_scale, result)
    return np.clip(result, 0, 1)


def band_probabilities(bands, quantiles, mean, std, floor=None):
    validate_bands(bands)
    edges = [bands[0].edges[0]] + [band.edges[1] for band in bands]
    probabilities = np.diff(quantile_cdf(edges, quantiles, mean, std))
    if floor is not None:
        bucket = math.floor(float(floor) + .5)
        impossible = [b.kind != "gte" and b.high < bucket for b in bands]
        probabilities[np.array(impossible)] = 0
    total = probabilities.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("no probability remains after floor")
    return probabilities / total


def empirical_probabilities(bands, point, errors):
    """Empirical error kernel; caller supplies only earlier-date residuals."""
    validate_bands(bands)
    errors = np.asarray(errors, dtype=float)
    if len(errors) == 0 or not np.isfinite(errors).all() or not np.isfinite(point):
        raise ValueError("finite point and earlier-date errors required")
    buckets = np.floor(point + errors + .5)
    counts = np.array([sum(b.contains(x) for x in buckets) for b in bands], float)
    return counts / len(errors)


def peak_time(times, maxima, *, envelope=False):
    """Frozen rule: first printed max equal to the final available printed max.

    envelope=True is the separately labelled nonmonotonic-series sensitivity.
    Missing values never create a peak; timestamps must be ordered and aware.
    """
    pairs = [(t, float(v)) for t, v in zip(times, maxima)
             if v is not None and math.isfinite(float(v))]
    if not pairs:
        return None
    if any(t.tzinfo is None for t, _ in pairs):
        raise ValueError("timezone-aware peak timestamps required")
    if any(a[0] > b[0] for a, b in zip(pairs, pairs[1:])):
        raise ValueError("peak timestamps out of order")
    final = max(v for _, v in pairs) if envelope else pairs[-1][1]
    return next(t for t, v in pairs if math.isclose(v, final, abs_tol=1e-8))


def crossed_weights(dates, markets, draws=2000, seed=20260921):
    """Pigeonhole bootstrap: independent multinomial date and market counts."""
    _, di = np.unique(dates, return_inverse=True)
    _, mi = np.unique(markets, return_inverse=True)
    d, m = di.max() + 1, mi.max() + 1
    rng = np.random.default_rng(seed)
    wd = rng.multinomial(d, np.full(d, 1 / d), size=draws)
    wm = rng.multinomial(m, np.full(m, 1 / m), size=draws)
    return wd[:, di] * wm[:, mi]


def summary(frame, numerator, denominator=None, *, null=0., alternative=None,
            draws=2000, seed=20260921):
    """Equal market-day estimand, percentile CI, shifted-bootstrap sensitivity.

    Collapse repeats within date/market before resampling. Ratios are ratios of
    means. MDE80 and power use the centered bootstrap error distribution, two
    sided 5% descriptive thresholds; they are not confirmatory alpha spending.
    Power is for an explicitly supplied effect, never the observed effect.
    """
    columns = [numerator] + ([denominator] if denominator else [])
    cells = frame.groupby(["date", "market"], observed=True)[columns].mean().dropna()
    support = {"market_days": len(cells),
               "date_clusters": cells.index.get_level_values(0).nunique(),
               "market_clusters": cells.index.get_level_values(1).nunique()}
    if not len(cells):
        return {**support, "status": "NO_DATA", "estimate": None}
    a = cells[numerator].to_numpy(float)
    b = cells[denominator].to_numpy(float) if denominator else np.ones(len(a))
    estimate = a.sum() / b.sum() if b.sum() > 0 else math.nan
    if support["date_clusters"] < 2 or support["market_clusters"] < 2:
        return {**support, "status": "INSUFFICIENT_CLUSTERS", "estimate": estimate,
                "ci95": None, "mde80": None, "power": None}
    w = crossed_weights(cells.index.get_level_values(0), cells.index.get_level_values(1), draws, seed)
    num, den = w @ a, w @ b
    valid = den > 0
    boot = num[valid] / den[valid]
    if len(boot) < .95 * draws or not np.isfinite(estimate):
        return {**support, "status": "UNSTABLE_DENOMINATOR", "estimate": None}
    lo, hi = np.quantile(boot, [.025, .975])
    error = boot - estimate
    critical = float(np.quantile(np.abs(error), .95))
    def power(effect):
        return float(np.mean(np.abs(error + effect) > critical))
    low, high = 0., max(critical * 10, 1e-10)
    for _ in range(50):
        mid = (low + high) / 2
        if power(mid) >= .8:
            high = mid
        else:
            low = mid
    return {**support, "status": "DESCRIPTIVE", "estimate": float(estimate),
            "ci95": [float(lo), float(hi)], "mde80": high,
            "alternative_effect": alternative,
            "power": power(alternative) if alternative is not None else None,
            "null": null, "distinguishable_from_null": bool(lo > null or hi < null),
            "valid_draws": len(boot)}
