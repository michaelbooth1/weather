"""Single-look fixed-population endpoint and conservative resampling envelope.

This is never called by coverage/accrual. Calibration is a separate pre-freeze
synthetic obligation; absent its frozen receipt, evaluate returns DESCRIBE.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta
from statistics import NormalDist

from .contracts import CITIES, DATE_COUNT, FIRST, LAST, number, require

ALPHA = 0.0125
FLOOR = 0.25
SEED = 20261110
RESAMPLES = 20_000
BLOCK = 3
PLANNING_DATE_SD = 1.4346
# Outward slack on the bounded dollar panel, confined to incomplete-payout proofs.
PAYOUT_SLACK = 1e-10
BOOTSTRAPS = ("date", "block3", "crossed_city_block3")


def panel_from_ledger(ledger: dict, *, optimistic_unknowns=False) -> list[list[float]]:
    cities = sorted(CITIES)
    n = (LAST - FIRST).days + 1
    days = {(FIRST + timedelta(days=i)).isoformat(): i for i in range(n)}
    matrix = [[0.0] * len(cities) for _ in range(n)]
    for row in ledger["decisions"]:
        if row["status"] not in {"filled", "resolved"}:
            continue
        net = number(row["conservative_net"])
        if optimistic_unknowns and row["status"] == "filled":
            net += number(row["shares"])
        matrix[days[row["target_date"]]][cities.index(row["city"])] += float(net)
    return matrix


def lrv_standard_error(daily: list[float]) -> float:
    n = len(daily)
    mean = sum(daily) / n
    centered = [v - mean for v in daily]
    variance = sum(v*v for v in centered) / n
    for lag in range(1, 4):
        covariance = sum(centered[i]*centered[i-lag] for i in range(lag, n)) / n
        variance += 2 * (1 - lag/4) * covariance
    return math.sqrt(max(0.0, variance) / n)


def robust_scale(matrix: list[list[float]]) -> float:
    """Analytic scale shared with synthetic critical-value calibration.

    Max of iid date, lag-3 LRV, circular block-3 date and persistent-city
    standard errors. The final bootstrap envelope can only widen this bound.
    """
    n, m = len(matrix), len(matrix[0])
    daily = [sum(row) / m for row in matrix]
    mean = sum(daily) / n
    iid = math.sqrt(sum((v-mean)**2 for v in daily) / (n*(n-1)))
    block_means = [sum(daily[(i+j) % n] for j in range(BLOCK))/BLOCK for i in range(n)]
    block = math.sqrt(BLOCK * sum((v-mean)**2 for v in block_means) / (n*n))
    city_means = [sum(matrix[i][j] for i in range(n))/n for j in range(m)]
    city = math.sqrt(sum((v-mean)**2 for v in city_means) / (m*(m-1)))
    return max(iid, block, city, lrv_standard_error(daily))


def interval(matrix: list[list[float]], *, critical: float | None, resamples=RESAMPLES,
             population_days=DATE_COUNT, payout_min_mean: float | None = None) -> dict:
    """Resample a declared population; evaluate always uses the restart dates.

    Historical N75 calibration witnesses explicitly supply population_days=75.
    They do not certify the N68 restart or enter its final evaluate path.
    """
    require(resamples >= 100, "resamples")
    n, m = len(matrix), len(matrix[0])
    require(n == population_days and n >= 20 and m == 12 and all(len(row) == m for row in matrix), "primary_population")
    require(all(math.isfinite(v) and -10.225 <= v <= 10 for row in matrix for v in row), "panel_bounds")
    mean = sum(map(sum, matrix)) / (n*m)
    daily = [sum(row)/m for row in matrix]
    rng = random.Random(SEED)
    distributions = {"date": [], "block3": [], "crossed_city_block3": []}
    for _ in range(resamples):
        dates = [rng.randrange(n) for _ in range(n)]
        distributions["date"].append(sum(daily[i] for i in dates)/n - mean)
        # Draw enough circular blocks, then truncate to exactly n dates. N68
        # needs a final two-date partial block; dividing 66 draws by 68 biases
        # even a constant panel and silently changes the test statistic.
        block_dates = [(start+j) % n for start in (rng.randrange(n) for _ in range(math.ceil(n/BLOCK)))
                       for j in range(BLOCK)][:n]
        distributions["block3"].append(sum(daily[i] for i in block_dates)/n - mean)
        city_weights = [0] * m
        for _ in range(m):
            city_weights[rng.randrange(m)] += 1
        weighted_daily = [sum(v*w for v, w in zip(row, city_weights))/m for row in matrix]
        distributions["crossed_city_block3"].append(sum(weighted_daily[i] for i in block_dates)/n - mean)
    intervals, pvalues = {}, {}
    for name, draws in distributions.items():
        draws.sort()
        lo = draws[max(0, math.ceil(ALPHA*resamples)-1)]
        hi = draws[min(resamples-1, math.ceil((1-ALPHA)*resamples)-1)]
        intervals[name] = [mean-hi, mean-lo]
        pvalues[name] = (1+sum(d >= mean for d in draws))/(resamples+1)
    scale = robust_scale(matrix)
    normal_critical = NormalDist().inv_cdf(1-ALPHA)
    lrv = lrv_standard_error(daily)
    daily_variance = sum((v-mean)**2 for v in daily)/(n-1)
    effective_dates = min(n, max(1.0, daily_variance/(lrv*lrv))) if lrv > 0 and daily_variance > 0 else None
    intervals["lag3_lrv"] = [mean-normal_critical*lrv, mean+normal_critical*lrv]
    pvalues["lag3_lrv"] = 1-NormalDist().cdf(mean/lrv) if lrv else (0.0 if mean > 0 else 1.0)
    if critical is not None:
        require(math.isfinite(critical) and critical >= normal_critical, "critical_value")
        intervals["calibrated_envelope"] = [mean-critical*scale, mean+critical*scale]
        # A conservative two-point p-value: valid only under the frozen
        # calibration family. It cannot claim a smaller p than local alpha.
        pvalues["calibrated_envelope"] = ALPHA if mean > critical*scale else 1.0
    else:
        pvalues["calibrated_envelope"] = 1.0
    result = {"mean": mean, "portfolio_dollars_per_date": mean*m,
            "lower": min(v[0] for v in intervals.values()),
            "upper": max(v[1] for v in intervals.values()),
            "pvalue": max(pvalues.values()), "pvalues": pvalues, "intervals": intervals, "robust_scale": scale,
            "lag3_effective_dates_diagnostic": effective_dates,
            "date_sd_diagnostic": math.sqrt(daily_variance),
            "realized_to_planning_sd_ratio": math.sqrt(daily_variance)/PLANNING_DATE_SD,
            "dates": n, "city_days": n*m}
    if payout_min_mean is not None:
        # This pass uses the all-upper panel. Each resampled mean is at
        # least its counterpart for any possible completion of these fills.
        cutoff = 2*payout_min_mean - mean - PAYOUT_SLACK
        result["bootstrap_pvalue_upper"] = max(
            (1+sum(d >= cutoff for d in draws))/(resamples+1)
            for draws in distributions.values()
        )
    return result


def payout_bounds(low, high, low_stats, high_stats, critical):
    """Outer bounds for all simultaneous payouts to the held shares.

    The cell box includes fractional/void payouts and every feasible assignment
    to a shared event/token. Relaxing the venue's cross-token constraints can
    cost decisiveness. Certifying a result on this larger box is sufficient.
    """
    n, m = len(low), len(low[0])
    middle = [[(a+b)/2 for a, b in zip(lrow, hrow)] for lrow, hrow in zip(low, high)]
    radius = [[(b-a)/2 for a, b in zip(lrow, hrow)] for lrow, hrow in zip(low, high)]
    date_radius = [sum(row)/m for row in radius]
    city_radius = [sum(row[j] for row in radius)/n for j in range(m)]
    # Each scale is a seminorm. For a perturbation within the radius, the
    # iid, circular-block and lag-3 Bartlett date scales are bounded by
    # 2*||date_radius||/n (Bartlett absolute kernel weights sum to four).
    movement = max(2*math.sqrt(sum(v*v for v in date_radius))/n,
                   math.sqrt(sum(v*v for v in city_radius)/(m*(m-1))))
    center_scale = robust_scale(middle)
    scale_min, scale_max = max(0., center_scale-movement), center_scale+movement
    lo, hi = low_stats["mean"], high_stats["mean"]
    shift = 2*(hi-lo)
    # Every draw has nonnegative sampling weights. Its basic bound
    # 2*mean - sampled_mean lies between B(high)-shift and B(low)+shift.
    # Interval quantiles preserve these pointwise inequalities.
    li, ui = low_stats["intervals"], high_stats["intervals"]
    lower_min = min(lo-critical*scale_max, *(ui[k][0]-shift for k in BOOTSTRAPS))
    lower_max = min(hi-critical*scale_min, *(li[k][0]+shift for k in BOOTSTRAPS))
    upper_min = max(lo+critical*scale_min, *(ui[k][1]-shift for k in BOOTSTRAPS))
    upper_max = max(hi+critical*scale_max, *(li[k][1]+shift for k in BOOTSTRAPS))
    p_upper = (max(ALPHA, high_stats["bootstrap_pvalue_upper"])
               if lo > critical*scale_max + PAYOUT_SLACK else 1.0)
    return {"lower_min": lower_min-PAYOUT_SLACK, "lower_max": lower_max+PAYOUT_SLACK,
            "upper_min": upper_min-PAYOUT_SLACK, "upper_max": upper_max+PAYOUT_SLACK,
            "pvalue_upper": p_upper}


def payout_robust_verdict(bounds, low_mean, high_mean, family_ok):
    """Issue an economic classification only when it holds throughout the box."""
    if low_mean > FLOOR+PAYOUT_SLACK and bounds["lower_min"] > 0 and bounds["pvalue_upper"] <= ALPHA and family_ok:
        return "SUCCESS"
    if bounds["upper_max"] <= 0:
        return "KILL_POSITIVE_PROFIT"
    if bounds["upper_min"] > 0 and bounds["upper_max"] < FLOOR:
        return "KILL_ECONOMIC_MINIMUM"
    if bounds["upper_min"] >= FLOOR and (high_mean+PAYOUT_SLACK <= FLOOR or bounds["lower_max"] <= 0):
        return "NOT_KILLED"
    return "DESCRIBE"


def holm_pass(pvalues: dict[str, float], expected: list[str]) -> bool:
    require(2 <= len(expected) <= 4 and set(pvalues) == set(expected) and "LOW-ASK-1" in pvalues, "family_claimants")
    require(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in pvalues.values()), "family_pvalue")
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    for index, (trial, p) in enumerate(ordered):
        if p > 0.05/(len(ordered)-index):
            return False
        if trial == "LOW-ASK-1":
            return True
    return False


def completeness(ledger: dict) -> dict:
    groups = {}
    for row in ledger["decisions"]:
        groups.setdefault((row["target_date"], row["city"]), []).append(row)
    good, filled, executable = {}, 0, 0
    by_city = {city: 0 for city in CITIES}
    by_date = {(FIRST+timedelta(days=i)).isoformat(): 0 for i in range((LAST-FIRST).days+1)}
    for (day, city), slots in groups.items():
        both_filled = len(slots) == 2 and all(r["status"] in {"filled", "resolved"} for r in slots)
        filled += both_filled
        by_city[city] += int(both_filled)
        by_date[day] += int(both_filled)
        adequate = len(slots) == 2 and all(r["status"] in {"filled", "resolved"}
                                         or (r["status"] == "skip" and r.get("reason") in
                                             {"cash_cap", "market_cap", "depth_reuse"}) for r in slots)
        executable += adequate
        good[day] = good.get(day, 0) + adequate
    return {"adequate_dates": sum(v >= 11 for v in good.values()), "both_filled_city_days": filled,
            "both_executable_city_days": executable,
            "both_filled_by_city": by_city, "both_filled_by_date": by_date,
            "captured_city_counts_by_date": {day: good.get(day, 0) for day in by_date},
            "scheduled_slots": DATE_COUNT*len(CITIES)*2,
            "filled_slots": sum(row["status"] in {"filled", "resolved"} for row in ledger["decisions"])}


def evaluate(ledger: dict, *, calibration: dict, family_pvalues: dict,
             claimants: list[str], resamples=RESAMPLES) -> dict:
    calibrated = calibration["status"] == "CALIBRATED"
    critical = float(calibration["critical_value"]) if calibrated else None
    low_panel = panel_from_ledger(ledger)
    result = interval(low_panel, critical=critical, resamples=resamples)
    coverage = completeness(ledger)
    gates = (calibrated and coverage["adequate_dates"] >= 68 and coverage["both_executable_city_days"] >= 810
             and ledger["doubtful_fills"] == 0)
    family = dict(family_pvalues)
    require("LOW-ASK-1" not in family, "own_pvalue_not_external")
    def family_check(stats):
        family["LOW-ASK-1"] = stats["pvalue"] if gates else 1.0
        return holm_pass(family, claimants)

    family_pass = family_check(result)

    def verdict(stats, family_ok):
        if not gates:
            return "DESCRIBE"
        if stats["mean"] > FLOOR and stats["lower"] > 0 and stats["pvalue"] <= ALPHA and family_ok:
            return "SUCCESS"
        if stats["upper"] <= 0:
            return "KILL_POSITIVE_PROFIT"
        if stats["upper"] < FLOOR:
            return "KILL_ECONOMIC_MINIMUM"
        return "NOT_KILLED"

    decision = verdict(result, family_pass)
    if ledger["unresolved"]:
        high_panel = panel_from_ledger(ledger, optimistic_unknowns=True)
        upper = interval(high_panel, critical=critical, resamples=resamples, payout_min_mean=result["mean"])
        result["unknown_payout_upper_panel"] = upper
        if gates:
            bounds = payout_bounds(low_panel, high_panel, result, upper, critical)
            result["unknown_payout_bounds"] = bounds
            result["all_zero_payout_pvalue"] = result["pvalue"]
            family_pass = family_check({"pvalue": bounds["pvalue_upper"]})
            decision = payout_robust_verdict(bounds, result["mean"], upper["mean"], family_pass)
            if decision != "DESCRIBE":
                result["pvalue"] = bounds["pvalue_upper"]
    if decision == "DESCRIBE":
        # An ineligible/unreconciled trial must not lend a small, invalid
        # diagnostic p-value to another claimant through the family Holm gate.
        result["diagnostic_pvalue"] = result["pvalue"]
        result["pvalue"] = 1.0
        family["LOW-ASK-1"] = 1.0
        family_pass = holm_pass(family, claimants)
    return dict(result, **coverage, verdict=decision, family_holm_pass=family_pass,
                unresolved=ledger["unresolved"], doubtful_fills=ledger["doubtful_fills"],
                calibration_status=calibration["status"])
