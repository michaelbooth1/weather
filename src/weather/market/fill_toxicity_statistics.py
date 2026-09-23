"""Frozen ratio estimators, date bootstrap and conservative decision gates."""

from __future__ import annotations

import random
import statistics

from weather.market import execution_tape_markout as baseline


# Each row is additive and records one date-market's sufficient statistics.
FIELDS = ("exposure", "loss", "reward_many", "reward_single", "filled_shares",
          "tail_shares", "fills", "tail_fills", "signed_markout", "net_loss", "band_days")


def zero():
    return dict.fromkeys(FIELDS, 0.0)


def add(target, values, weight=1):
    for name in FIELDS:
        target[name] += values.get(name, 0) * weight


def ratio(numerator, denominator):
    return numerator / denominator if denominator > 0 else None


def point(total, inside, outside):
    loss_in = ratio(inside["loss"], inside["exposure"])
    loss_out = ratio(outside["loss"], outside["exposure"])
    days = total["band_days"]
    result = {
        "CR": ratio(loss_in, loss_out) if loss_in is not None and loss_out is not None else None,
        "adverse_per_share_minute_inside": loss_in,
        "adverse_per_share_minute_outside": loss_out,
        "tail_rate_share_inside": ratio(inside["tail_shares"], inside["filled_shares"]),
        "tail_rate_share_outside": ratio(outside["tail_shares"], outside["filled_shares"]),
        "tail_rate_fill_inside": ratio(inside["tail_fills"], inside["fills"]),
        "tail_rate_fill_outside": ratio(outside["tail_fills"], outside["fills"]),
        "net_pull_per_band_day": ratio(inside["net_loss"] - inside["reward_many"], days),
        "net_pull_k_half": ratio(inside["net_loss"] - .5 * inside["reward_many"], days),
        "net_pull_single": ratio(inside["net_loss"] - inside["reward_single"], days),
        "net_after_pull_per_band_day": ratio(
            total["reward_many"] - inside["reward_many"] - total["net_loss"] + inside["net_loss"], days),
    }
    return result


def interval(values):
    values = sorted(values)
    return [baseline.percentile(values, .05), baseline.percentile(values, .95)] if values else None


def reward_point(total, inside, outside):
    return {"R": ratio(total["reward_many"], total["filled_shares"]),
            "R_single": ratio(total["reward_single"], total["filled_shares"])}


def summarize(rows, key, *, replicates=baseline.DEFAULT_BOOTSTRAP_REPLICATES, crossed=False, reward_only=False):
    """Rows: ((date, market), total, inside, outside). No iid trade resampling."""
    dates = sorted({identity[0] for identity, *_ in rows})
    markets = sorted({identity[1] for identity, *_ in rows})

    def aggregate(date_weights=None, market_weights=None):
        totals = [zero(), zero(), zero()]
        for (day, market), *parts in rows:
            weight = (date_weights.get(day, 0) if date_weights is not None else 1)
            weight *= market_weights.get(market, 0) if market_weights is not None else 1
            for result, part in zip(totals, parts):
                add(result, part, weight)
        return totals

    totals = aggregate()
    estimator = reward_point if reward_only else point
    estimate = estimator(*totals)
    draws = {name: [] for name in estimate}
    rng = random.Random(f"{baseline.DEFAULT_SEED}:{key}")
    if len(dates) >= 2 and (not crossed or len(markets) >= 2):
        # Vectorized, bounded batches. einsum without optimization uses no BLAS
        # worker pool; Python does not loop over every market-day in every draw.
        import numpy as np

        di = {value: i for i, value in enumerate(dates)}
        mi = {value: i for i, value in enumerate(markets)}
        matrix = np.asarray([[part[field] for part in parts for field in FIELDS]
                             for _, *parts in rows], dtype=float)
        row_dates = np.asarray([di[identity[0]] for identity, *_ in rows])
        row_markets = np.asarray([mi[identity[1]] for identity, *_ in rows])
        for first in range(0, replicates, 128):
            count = min(128, replicates - first)
            dw = np.zeros((count, len(dates)))
            mw = np.ones((count, len(markets)))
            for draw in range(count):
                for _ in dates:
                    dw[draw, rng.randrange(len(dates))] += 1
                if crossed:
                    mw[draw] = 0
                    for _ in markets:
                        mw[draw, rng.randrange(len(markets))] += 1
            weights = dw[:, row_dates] * mw[:, row_markets]
            aggregated = np.einsum("ij,jk->ik", weights, matrix, optimize=False)
            for row in aggregated:
                parts = [dict(zip(FIELDS, row[at:at + len(FIELDS)])) for at in range(0, len(row), len(FIELDS))]
                values = estimator(*parts)
                for name, value in values.items():
                    if value is not None:
                        draws[name].append(float(value))
    intervals = {name: interval(values) for name, values in draws.items()}
    return {"point": estimate, "interval_90": intervals,
            "valid_bootstrap_replicates": {name: len(values) for name, values in draws.items()},
            "date_clusters": len(dates), "market_clusters": len(markets), "market_days": len(rows),
            "interval_flag": baseline.UNDERPOWERED if len(dates) < baseline.MIN_DATE_CLUSTERS else "",
            "cluster": "crossed_date_market" if crossed else "date",
            "sufficient_statistics": dict(zip(("total", "inside", "outside"), totals))}


def decision(primary):
    if primary["date_clusters"] < baseline.MIN_DATE_CLUSTERS:
        return {"verdict": "INCONCLUSIVE", "reason": "UNDERPOWERED"}
    cr = primary["interval_90"]["CR"]
    net = primary["interval_90"]["net_pull_per_band_day"]
    if cr and net and cr[0] >= 2 and net[0] > 0:
        return {"verdict": "PULL_SUPPORTED", "reason": "both_frozen_lower_bounds_pass"}
    if cr and cr[1] <= 1.5:
        return {"verdict": "PULL_NOT_THE_LEVER", "reason": "CR_upper_bound_at_most_1.5"}
    return {"verdict": "INCONCLUSIVE", "reason": "frozen_thresholds_not_met"}


def kill_decision(sets):
    eligible = [(row["point"]["net_pull_per_band_day"], name, row)
                for name, row in sets.items() if row["point"]["net_pull_per_band_day"] is not None]
    if not eligible:
        return {"verdict": "INCONCLUSIVE", "selected_set": None}
    # Stable lexical ties; tied point estimates do not change the selection criterion.
    _, selected, row = max(eligible, key=lambda item: (item[0], item[1]))
    upper = row["interval_90"]["net_after_pull_per_band_day"]
    allowed = row["date_clusters"] >= baseline.MIN_DATE_CLUSTERS
    return {"verdict": "KILL" if allowed and upper and upper[1] < 0 else "INCONCLUSIVE",
            "selected_set": selected, "interval_90": upper,
            "selection": "highest_point_net_pull_per_band_day_of_seven"}


def latency_summary(by_date, key, *, replicates=baseline.DEFAULT_BOOTSTRAP_REPLICATES):
    dates = sorted(by_date)
    values = [value for day in dates for value in by_date[day]]
    rng = random.Random(f"{baseline.DEFAULT_SEED}:{key}")
    draws = []
    if len(dates) >= 2:
        for _ in range(replicates):
            sample = [dates[rng.randrange(len(dates))] for _ in dates]
            draws.append(statistics.median(value for day in sample for value in by_date[day]))
    bounds = interval(draws)
    return {"median_fraction": statistics.median(values) if values else None,
            "interval_90": bounds, "date_clusters": len(dates), "events": len(values),
            "interval_flag": baseline.UNDERPOWERED if len(dates) < baseline.MIN_DATE_CLUSTERS else "",
            "reactive_pull_useless": bool(len(dates) >= baseline.MIN_DATE_CLUSTERS and bounds and bounds[0] >= .70)}
