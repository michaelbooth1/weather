"""Frozen crossed-cluster descriptive inference and half-effect planning."""
from __future__ import annotations

from datetime import date, timedelta
import numpy as np

from tools.research.missing_information.methods import crossed_weights

DRAWS = 2000
SEED = 20260921


def inference(point, boot, effect):
    boot = np.asarray(boot)
    boot = boot[np.isfinite(boot)]
    result = {"estimate": float(point), "ci95": np.quantile(boot, [.025, .975]).tolist(),
              "valid_draws": len(boot), "alternative_shift": effect, "power": None, "mde80": None}
    error = boot - point
    critical = float(np.quantile(np.abs(error), .95))
    if critical <= 1e-15:
        return {**result, "status": "DEGENERATE_EMPIRICAL_BOOTSTRAP"}
    result["power"] = float(np.mean(np.abs(error + effect) > critical))
    low, high = 0., critical * 10
    direction = -1 if effect < 0 else 1
    for _ in range(45):
        mid = (low + high) / 2
        if np.mean(np.abs(error + direction * mid) > critical) >= .8:
            high = mid
        else:
            low = mid
    return {**result, "mde80": float(high), "status": "DESCRIPTIVE"}


def summarize(cells, column, denominator=None, effect=-.0075):
    dates, markets = cells.date, cells.market
    w = crossed_weights(dates, markets, draws=DRAWS, seed=SEED)
    a = cells[column].to_numpy(float)
    b = cells[denominator].to_numpy(float) if denominator else np.ones(len(cells))
    point = a.sum() / b.sum()
    den = w @ b
    boot = np.divide(w @ a, den, out=np.full(DRAWS, np.nan), where=den > 0)
    return {"market_days": len(cells), "date_clusters": dates.nunique(),
            "market_clusters": markets.nunique(), **inference(point, boot, effect)}


def future_errors(cells, column, n):
    """Keep the market dimension fixed, even in the infinite-date limit."""
    table = cells.pivot(index="date", columns="market", values=column)
    x = table.fillna(0).to_numpy(float)
    mask = table.notna().to_numpy(float)
    d, m = x.shape
    rng = np.random.default_rng(SEED)
    wm = rng.multinomial(m, np.full(m, 1 / m), size=DRAWS)
    if n is None:
        num = wm @ x.sum(axis=0)
        den = wm @ mask.sum(axis=0)
    else:
        wd = rng.multinomial(n, np.full(d, 1 / d), size=DRAWS)
        num = np.sum((wd @ x) * wm, axis=1)
        den = np.sum((wd @ mask) * wm, axis=1)
    valid = den > 0
    if valid.sum() < .95 * DRAWS:
        raise ValueError("too many empty future crossed draws")
    return num[valid] / den[valid] - cells[column].mean()


def planning(cells, column, freeze_date):
    point = float(cells[column].mean())
    effect = max(0., -point) / 2
    base = {"half_development_effect": effect, "alpha_one_sided": .025,
            "target_power": .8, "date_clusters": cells.date.nunique(),
            "market_clusters": cells.market.nunique(), "market_days": len(cells),
            "new_dates": None, "end_date_at_full_accrual": None,
            "monte_carlo_se_at_80pct": float(np.sqrt(.8*.2/DRAWS))}
    if effect <= 0:
        return {**base, "status": "NONBENEFICIAL_DEVELOPMENT_EFFECT"}
    def power(n):
        error = future_errors(cells, column, n)
        critical = np.quantile(error, .025)
        return float(np.mean(error - effect < critical))
    floor_power = power(None)
    measured = {str(n): power(n) for n in range(2, 46)}
    first = next((int(n) for n, p in measured.items() if p >= .8), None)
    base.update(power_by_new_dates=measured, infinite_date_market_only_power=floor_power)
    if first is None and floor_power < .8:
        return {**base, "status": "MARKET_CLUSTER_FLOOR_LIMITED"}
    if first is None:
        last = 45
        for n in (60, 90, 120, 180, 270, 365, 730, 1460, 3650):
            measured[str(n)] = power(n)
            if measured[str(n)] >= .8:
                lo, hi = last, n
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    measured[str(mid)] = power(mid)
                    if measured[str(mid)] >= .8:
                        hi = mid
                    else:
                        lo = mid
                first = hi
                break
            last = n
    if first is None:
        return {**base, "status": "NOT_REACHED_THROUGH_3650_DATES"}
    return {**base, "status": "PLUG_IN_PLANNING_ONLY", "new_dates": first,
            "end_date_at_full_accrual": (date.fromisoformat(freeze_date) + timedelta(days=first)).isoformat(),
            "market_days_at_12_per_day": 12 * first}
