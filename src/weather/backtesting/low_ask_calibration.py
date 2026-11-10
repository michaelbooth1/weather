"""Synthetic-only pre-freeze calibration; no market/data input or network path.

Full runs require reviewed workstation-heavy module admission. The unattended
LOW-ASK-1 process never imports numpy/scipy or this research implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import stat
import time
from datetime import timedelta
from functools import cache
from pathlib import Path

from weather.backtesting.low_ask.contracts import CITIES, FIRST, local_cut, timezone_fingerprint
from weather.backtesting.low_ask.inference import PLANNING_DATE_SD

SEED = 20261110
ALPHA = .0125
EFFECTS = (.9490, .7490, .6741, .5000)  # Intended ten-share city-day dollars.
ARMS = list(itertools.product((0, .22, .5), (0, .25, .5), (0, .25), ("spread", "clustered")))
SUPPORTS = (810, 900, 825)
POWER_ARMS = [dict(phi=p, common=c, persistent=v, mechanism=m, support=s, ask=.8)
              for s in SUPPORTS for p, c, v, m in ARMS]
# Four strongest dependence arms: maximum phi/common, both persistent shares
# and both missingness mechanisms. High-ask additions are null-only stresses.
SIZE_ARMS = POWER_ARMS + [dict(phi=.5, common=.5, persistent=v, mechanism=m, support=s, ask=.93)
                          for s in SUPPORTS for v in (0, .25) for m in ("spread", "clustered")]
TRAIN_QUANTILE = .9925
PLANNING_ARM_DATE_SD = 1.63  # Master's alternative date-SD planning proxy.
N, M = 75, 12
ASK, FEE, RESERVE = .8, .05 * .8 * .2, .01
PER_SHARE_COST = ASK + FEE + RESERVE
COST = 5 * PER_SHARE_COST


def is_planning_arm(arm):
    return (arm["phi"], arm["common"], arm["persistent"], arm["support"], arm["ask"]) == (.22, .5, 0, 810, .8)


@cache
def libraries():
    # Cap native allocation before imports; never increase inherited caps.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    import numpy as np
    from scipy.special import ndtr
    from scipy.stats import beta
    return np, ndtr, beta


def upper_error(k, n, *, tail):
    _, _, beta = libraries()
    return 1.0 if k == n else float(beta.ppf(1-tail, k+1, n-k))


def lower_power(k, n, *, tail):
    _, _, beta = libraries()
    return 0.0 if k == 0 else float(beta.ppf(tail, k, n-k+1))


def scales(panels):
    """Vectorized exact robust_scale formula; checked against final-look code."""
    np, _, _ = libraries()
    daily = panels.mean(axis=2)
    mean = daily.mean(axis=1)
    centered = daily - mean[:, None]
    iid = np.sqrt((centered**2).sum(axis=1)/(N*(N-1)))
    block = sum(np.roll(daily, -j, axis=1) for j in range(3))/3
    block_se = np.sqrt(3*((block-mean[:, None])**2).sum(axis=1)/(N*N))
    city = panels.mean(axis=1)
    city_se = np.sqrt(((city-mean[:, None])**2).sum(axis=1)/(M*(M-1)))
    variance = (centered**2).sum(axis=1)/N
    for lag in range(1, 4):
        variance += 2*(1-lag/4)*(centered[:, lag:]*centered[:, :-lag]).sum(axis=1)/N
    lrv = np.sqrt(np.maximum(0, variance)/N)
    scale = np.maximum.reduce([iid, block_se, city_se, lrv])
    return mean, scale, lrv


def bootstrap_weights(resamples=20_000):
    """Match inference.interval's interleaved random.Random draws exactly."""
    np, _, _ = libraries()
    rng = random.Random(SEED)
    dates = np.zeros((resamples, N), dtype=np.float64)
    blocks = np.zeros_like(dates)
    cities = np.zeros((resamples, M), dtype=np.float64)
    for r in range(resamples):
        for _ in range(N):
            dates[r, rng.randrange(N)] += 1
        for _ in range(N//3):
            start = rng.randrange(N)
            for j in range(3):
                blocks[r, (start+j) % N] += 1
        for _ in range(M):
            cities[r, rng.randrange(M)] += 1
    crossed = (blocks[:, :, None]*cities[:, None, :]).reshape(resamples, N*M)/(N*M)
    return dates/N, blocks/N, crossed


def bootstrap_components(panels, weights):
    """Per-bootstrap bounds/p-values, also tested against scalar inference."""
    np, _, _ = libraries()
    means = panels.mean(axis=(1, 2))
    resamples = len(weights[0])
    lo_index = max(0, math.ceil(ALPHA*resamples)-1)
    hi_index = min(resamples-1, math.ceil((1-ALPHA)*resamples)-1)
    result = {}
    for name, weight, values in (("date", weights[0], panels.mean(axis=2)),
                                 ("block3", weights[1], panels.mean(axis=2)),
                                 ("crossed_city_block3", weights[2], panels.reshape(len(panels), N*M))):
        draws = values @ weight.T - means[:, None]
        pvalue = (1+(draws >= means[:, None]).sum(axis=1))/(resamples+1)
        bounds = np.partition(draws, (lo_index, hi_index), axis=1)
        result[name] = {"lower": means-bounds[:, hi_index], "upper": means-bounds[:, lo_index], "pvalue": pvalue}
    return result


def bootstrap_success(panels, critical, weights):
    """Conservative full local verdict, including all final bootstrap gates.

    A small epsilon makes floating-point boundary differences conservative
    relative to the scalar final implementation. Family Holm is conditional
    on the frozen external claimant package; it is never fabricated here.
    """
    np, _, _ = libraries()
    mean, scale, lrv = scales(panels)
    result = (mean > .25+1e-10) & (mean-critical*scale > 1e-10)
    result &= mean - 2.241402727604947*lrv > 1e-10
    # An analytic failure cannot be rescued by a bootstrap. Avoid its allocation.
    indices = np.flatnonzero(result)
    if len(indices):
        for component in bootstrap_components(panels[indices], weights).values():
            result[indices] &= (component["lower"] > 1e-10) & (component["pvalue"] <= ALPHA)
    return result


@cache
def execution_slots():
    cities = sorted(CITIES)
    return sorted((local_cut(FIRST+timedelta(days=d), CITIES[city][0], h).timestamp()+30, city, h, d, j, k)
                  for d in range(N) for j, city in enumerate(cities) for k, h in enumerate((17, 18)))


@cache
def execution_groups():
    groups = []
    for at, rows in itertools.groupby(execution_slots(), key=lambda row: row[0]):
        rows = list(rows)  # Already ordered by city/cut at this UTC instant.
        groups.append((at, tuple(r[3] for r in rows), tuple(r[4] for r in rows), tuple(r[5] for r in rows)))
    return groups


def realized_cash(available, outcomes, delay3, *, ask):
    """Generated-outcome counterpart of core.simulate's cash/locked accounting.

    Resolve before same-instant fills in UTC/city/cut order. Permanent losses,
    retained gains, all-in debit at fill, actual 0/5 payout at release. No reset,
    refund proxy, re-centring or capital injection. Only total capital binds.
    """
    import heapq
    np, _, _ = libraries()
    count = len(available)
    # These two frozen asks have exact integer-microdollar all-in costs.
    # Integer accounting matches Decimal core boundaries without float epsilon.
    if ask not in (.8, .93):
        raise ValueError("unregistered synthetic ask")
    unit = 1_000_000
    cash = np.full(count, 300*unit, dtype=np.int64)
    locked = np.zeros(count, dtype=np.int64)
    peak_locked = np.zeros(count, dtype=np.int64)
    blocked = np.zeros(count, dtype=np.int64)
    shares = np.zeros((count, N, M), dtype=np.float64)
    cost = 4_090_000 if ask == .8 else 4_716_275
    pending, times = {}, []

    def settle(at):
        nonlocal cash, locked
        while times and times[0] <= at:
            release = heapq.heappop(times)
            debit, payout = pending.pop(release)
            cash += payout
            locked -= debit

    for at, days, cities, cuts in execution_groups():
        settle(at)
        candidates = available[:, days, cities]
        capacity = np.maximum(0, np.minimum(cash, 300*unit-locked)//cost)
        # Equal costs and no same-instant settlement within this group make
        # the eligible prefix exactly the scalar UTC/city/cut fill sequence.
        filled = candidates & (candidates.cumsum(axis=1) <= capacity[:, None])
        counts = filled.sum(axis=1)
        blocked += candidates.sum(axis=1)-counts
        cash -= cost*counts
        locked += cost*counts
        peak_locked = np.maximum(peak_locked, locked)
        shares[:, days, cities] += 5*filled
        delayed = delay3[:, days, cities, cuts]
        for delay, mask in ((1, filled & ~delayed), (3, filled & delayed)):
            release = at + delay*86400
            if release not in pending:
                pending[release] = (np.zeros(count, dtype=np.int64), np.zeros(count, dtype=np.int64))
                heapq.heappush(times, release)
            pending[release][0][:] += cost*mask.sum(axis=1)
            pending[release][1][:] += 5*unit*(outcomes[:, days, cities]*mask).sum(axis=1)
    settle(float("inf"))
    return shares, {"cash_cap_slots": blocked, "binding": blocked > 0,
                    "peak_locked": peak_locked/unit, "ending_cash": cash/unit}


def fixed_city_offsets():
    """Deterministic fixed-city probit offsets, zero mean and unit variance."""
    np, _, _ = libraries()
    from scipy.special import ndtri
    offsets = ndtri((np.arange(M)+.5)/M)
    offsets -= offsets.mean()
    return offsets/np.sqrt((offsets**2).mean())


def city_survival(probability, persistent):
    """A common probit threshold preserves the fixed 12-city marginal mean.

    Centring latent offsets alone is insufficient after a nonlinear CDF. Solve
    the common threshold so their fixed-city survival average is exactly the
    declared marginal. This is predeclared generation, never data re-centring.
    Realized cash drift and its dependence on the fill mask remain untouched.
    """
    np, ndtr, _ = libraries()
    if persistent == 0:
        return np.full(M, probability)
    offsets = math.sqrt(persistent)*fixed_city_offsets()
    low, high = -12.0, 12.0
    for _ in range(60):
        middle = (low+high)/2
        if ndtr((middle-offsets)/math.sqrt(1-persistent)).mean() < probability:
            low = middle
        else:
            high = middle
    return ndtr(((low+high)/2-offsets)/math.sqrt(1-persistent))


def synthetic_panels(rng, count, arm, effect=0.0):
    """Fixed-city Gaussian copula, actual cash feedback and declared supports.

    The 810 floor removes seven dates and six more city-days; 900 removes none,
    825 removes Chicago on every date. Capital blocks preserve input adequacy.
    Both cuts share a binary venue outcome; no reward/mark-to-market proxy.
    """
    np, ndtr, _ = libraries()
    phi, common, persistent, mechanism = (arm[k] for k in ("phi", "common", "persistent", "mechanism"))
    innovations = (math.sqrt(common)*rng.standard_normal((count, N, 1))
                   + math.sqrt(1-common)*rng.standard_normal((count, N, M)))
    latent = innovations.copy()
    for d in range(1, N):
        latent[:, d] = phi*latent[:, d-1] + math.sqrt(1-phi*phi)*innovations[:, d]
    available = np.ones((count, N, M), dtype=bool)
    for b in range(count):
        if arm["support"] == 900:
            continue
        if arm["support"] == 825:
            available[b, :, sorted(CITIES).index("chicago")] = False
            continue
        if mechanism == "spread":
            absent = rng.choice(N, 7, replace=False)
        else:
            start = int(rng.integers(N-2))
            block = np.arange(start, start+3)
            remaining = np.setdiff1d(np.arange(N), block)
            absent = np.concatenate([block, rng.choice(remaining, 4, replace=False)])
        available[b, absent] = False
        retained = np.setdiff1d(np.arange(N), absent)
        for d in rng.choice(retained, 6, replace=False):
            available[b, d, int(rng.integers(M))] = False
    # Same seeded random streams across all four effects, including delays.
    # The intended-unit effect is before cash rationing, never normalized back
    # up after losses. Ask-.93's declared rounded null survival is .9433.
    probability = (.818 if arm["ask"] == .8 else .9433) + effect/(10*arm["support"]/900)
    if not 0 < probability < 1:
        raise ValueError("synthetic effect outside bounded payout family")
    outcomes = ndtr(latent) < city_survival(probability, persistent)[None, None, :]
    delay3 = rng.random((count, N, M, 2)) < .1
    shares, diagnostics = realized_cash(available, outcomes, delay3, ask=arm["ask"])
    cost = arm["ask"]+.05*arm["ask"]*(1-arm["ask"])+.01
    panels = shares*(outcomes-cost)
    # Capital blocks retain full executable-input validation (MASTER B3).
    both = available.sum(axis=(1, 2))
    adequate = (available.sum(axis=2) >= 11).sum(axis=1)
    diagnostics.update(executable_city_days=both, adequate_dates=adequate,
                       date_sd=panels.mean(axis=2).std(axis=1, ddof=1), policy_mean=panels.mean(axis=(1, 2)))
    return panels, (both >= 810) & (adequate >= 68), diagnostics


def output_root(path):
    """Constrain every read/write to this task, refusing traversal/reparse paths."""
    root = Path(r"C:\t\codex\T093")
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(root):
        raise ValueError("output must stay under C:\\t\\codex\\T093")
    root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("output must stay under C:\\t\\codex\\T093")
    for component in (path, *path.parents):
        if component.exists() and getattr(component.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("T093 output path cannot contain a reparse point")
    return resolved


def hash_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        handle.write("\n")


def collect_diagnostics(total, diagnostics):
    """Streaming summaries; panels/outcomes are never written."""
    total["panels"] += len(diagnostics["binding"])
    total["cash_cap_slots"] += int(diagnostics["cash_cap_slots"].sum())
    total["binding_panels"] += int(diagnostics["binding"].sum())
    total["peak_locked"] = max(total["peak_locked"], float(diagnostics["peak_locked"].max()))
    total["ending_cash_sum"] += float(diagnostics["ending_cash"].sum())
    total["date_sd_sum"] += float(diagnostics["date_sd"].sum())
    total["policy_mean_sum"] += float(diagnostics["policy_mean"].sum())


def empty_diagnostics():
    return dict(panels=0, cash_cap_slots=0, binding_panels=0, peak_locked=0.0,
                ending_cash_sum=0.0, date_sd_sum=0.0, policy_mean_sum=0.0)


def finish_diagnostics(total):
    n = total["panels"]
    sd = total["date_sd_sum"]/n
    return {"panels": n, "cash_cap_slots": total["cash_cap_slots"],
            "cash_cap_slots_per_panel": total["cash_cap_slots"]/n,
            "binding_panels": total["binding_panels"], "binding_probability": total["binding_panels"]/n,
            "peak_locked": total["peak_locked"], "mean_ending_cash": total["ending_cash_sum"]/n,
            "mean_date_sd": sd, "realized_to_planning_sd_ratio": sd/PLANNING_DATE_SD,
            "mean_policy_net_city_day": total["policy_mean_sum"]/n,
            "realized_to_planning_arm_sd_ratio": sd/PLANNING_ARM_DATE_SD}


def summarize_reports(reports):
    """Size over every stress; power eligibility only over two planning cells."""
    if len(reports) != len(SIZE_ARMS):
        raise ValueError("incomplete calibration arms")
    if any([cell["intended_city_day_effect"] for cell in r["power"]] !=
           (list(EFFECTS) if r["arm"]["ask"] == .8 else []) for r in reports):
        raise ValueError("incomplete diagnostic power cells")
    planning = [r for r in reports if is_planning_arm(r["arm"])]
    if len(planning) != 2:
        raise ValueError("incomplete planning arms")
    size_upper = max(r["size_upper"] for r in reports)
    power_lower = min(r["planning_power_lower"] for r in planning)
    return {"status": "CALIBRATED" if size_upper <= ALPHA and power_lower >= .8 else "SCREEN_ONLY",
            "size_upper": size_upper, "power_lower": power_lower,
            "power_scope": "phi=.22/common=.5/persistent=0/support=810/ask=.8; both mechanisms",
            "planning_arm_indices": [r["arm_index"] for r in planning],
            "size_cells": [dict(arm_index=r["arm_index"], arm=r["arm"], size_upper=r["size_upper"],
                                diagnostics=r["null_diagnostics"]) for r in reports],
            "power_cells": [dict(arm_index=r["arm_index"], arm=r["arm"], **cell)
                            for r in reports for cell in r["power"]],
            "decision": "No retuning after independent validation; a planning power failure goes to owner."}


def main(argv=None):
    parser = argparse.ArgumentParser(description="LOW-ASK-1 synthetic-only calibration; reviewed heavy wrapper required")
    parser.add_argument("phase", choices=("train", "validate", "summarize"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm-start", type=int, default=0)
    parser.add_argument("--arm-count", type=int, default=1)
    parser.add_argument("--null-simulations", type=int, default=20_000)
    parser.add_argument("--power-simulations", type=int, default=2000)
    args = parser.parse_args(argv)
    deadline = time.monotonic()+18*60

    def budget():
        if time.monotonic() >= deadline:
            raise RuntimeError("synthetic chunk deadline; retain complete arm receipts and resume next arm")
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("reviewed workstation-heavy admission required")
    if args.null_simulations < 20_000 or args.power_simulations < 2000:
        parser.error("minimum calibration replication count")
    if not (0 <= args.arm_start < len(SIZE_ARMS) and 1 <= args.arm_count <= (6 if args.phase == "train" else 3)):
        parser.error("bounded arm chunk required")
    try:
        args.out = output_root(args.out)
    except ValueError as error:
        parser.error(str(error))
    np, _, _ = libraries()
    import scipy
    args.out.mkdir(parents=True, exist_ok=True)
    binding = {"code_sha256": hash_bytes(Path(__file__)),
               "inference_sha256": hash_bytes(Path(__file__).with_name("low_ask") / "inference.py"),
               "contracts_sha256": hash_bytes(Path(__file__).with_name("low_ask") / "contracts.py"),
               "timezone_sha256": timezone_fingerprint(), "numpy_version": np.__version__,
               "scipy_version": scipy.__version__,
               "null_n": args.null_simulations, "power_n": args.power_simulations,
               "resamples": 20_000, "seed": SEED, "alpha": ALPHA,
               "training_quantile": TRAIN_QUANTILE, "size_arm_count": len(SIZE_ARMS),
               "power_arm_count": len(POWER_ARMS), "supports": list(SUPPORTS),
               "fixed_city_offsets": fixed_city_offsets().tolist()}
    tail = .05/len(SIZE_ARMS)  # Simultaneous one-sided 95% across all stresses.
    if args.phase == "summarize":
        reports = [json.loads((args.out/f"validate-{i:03d}.json").read_text()) for i in range(len(SIZE_ARMS))]
        if any(r["binding"] != binding for r in reports):
            raise ValueError("calibration binding drift")
        if any(r["critical_value"] != reports[0]["critical_value"] or r["arm_index"] != i or r["arm"] != SIZE_ARMS[i]
               for i, r in enumerate(reports)):
            raise ValueError("calibration arm/critical-value drift")
        write_new(args.out / "CALIBRATION_RECEIPT.json", {
            "schema_version": "low_ask_calibration_v1",
            **summarize_reports(reports), "binding": binding,
            "critical_value": reports[0]["critical_value"],
            "arms": [{"path": f"validate-{i:03d}.json", "sha256": hash_bytes(args.out/f"validate-{i:03d}.json")}
                     for i in range(len(SIZE_ARMS))]})
        return 0
    critical = None
    if args.phase == "validate":
        fits = [json.loads((args.out/f"train-{i:03d}.json").read_text()) for i in range(len(SIZE_ARMS))]
        if any(r["binding"] != binding for r in fits):
            raise ValueError("training binding drift")
        if any(r["arm_index"] != i or r["arm"] != SIZE_ARMS[i] for i, r in enumerate(fits)):
            raise ValueError("training arm drift")
        critical = max(2.241402727604947, *(r["critical_candidate"] for r in fits))
        if not math.isfinite(critical):
            raise ValueError("nonfinite critical value; report to master without retuning")
    weights = bootstrap_weights() if args.phase == "validate" else None
    for arm_index in range(args.arm_start, min(len(SIZE_ARMS), args.arm_start+args.arm_count)):
        arm = SIZE_ARMS[arm_index]
        # Training, validation and power use disjoint predetermined RNG streams.
        stream = 0 if args.phase == "train" else 1
        rng = np.random.default_rng(np.random.SeedSequence([SEED, arm_index, stream]))
        statistics = []
        null_diagnostics = empty_diagnostics()
        for start in range(0, args.null_simulations, 128):
            budget()
            panels, _, diagnostics = synthetic_panels(rng, min(128, args.null_simulations-start), arm)
            collect_diagnostics(null_diagnostics, diagnostics)
            mean, scale, _ = scales(panels)
            degenerate = np.where(mean > 0, np.inf, np.where(mean < 0, -np.inf, 0.0))
            statistics.extend(np.divide(mean, scale, out=degenerate, where=scale > 0).tolist())
        report = {"schema_version": "low_ask_calibration_v1", "binding": binding, "arm_index": arm_index, "arm": arm,
                  "null_diagnostics": finish_diagnostics(null_diagnostics)}
        if args.phase == "train":
            report["critical_candidate"] = float(np.quantile(statistics, TRAIN_QUANTILE, method="higher"))
        else:
            exceed = sum(t > critical for t in statistics)
            report.update(critical_value=critical, null_exceedances=exceed,
                          size_upper=upper_error(exceed, args.null_simulations, tail=tail), power=[])
            for effect in EFFECTS if arm["ask"] == .8 else ():
                # Common random numbers across effects; no stream reuse with nulls.
                rng = np.random.default_rng(np.random.SeedSequence([SEED, arm_index, 2]))
                successes, sufficient = 0, 0
                power_diagnostics = empty_diagnostics()
                for start in range(0, args.power_simulations, 32):
                    budget()
                    panels, coverage, diagnostics = synthetic_panels(rng, min(32, args.power_simulations-start), arm, effect)
                    collect_diagnostics(power_diagnostics, diagnostics)
                    success = bootstrap_success(panels, critical, weights) & coverage
                    successes += int(success.sum())
                    sufficient += int(coverage.sum())
                planning_gate = is_planning_arm(arm) and effect == .6741
                power_tail = .05/2 if planning_gate else .05/(len(POWER_ARMS)*len(EFFECTS))
                bound = lower_power(successes, args.power_simulations, tail=power_tail)
                report["power"].append({"intended_city_day_effect": effect, "successes": successes,
                                        "coverage_sufficient": sufficient, "estimate": successes/args.power_simulations,
                                        "lower": bound, "mc_tail": power_tail, "planning_gate": planning_gate,
                                        "diagnostics": finish_diagnostics(power_diagnostics)})
                if effect == .6741:
                    report["planning_power_lower"] = bound
        write_new(args.out / f"{args.phase}-{arm_index:03d}.json", report)
        print(json.dumps({"phase": args.phase, "arm": arm_index, "status": "SYNTHETIC_RECEIPT_WRITTEN"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
