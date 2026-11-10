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
import time
from datetime import timedelta
from functools import cache
from pathlib import Path

from weather.backtesting.low_ask.contracts import CITIES, FIRST, local_cut, timezone_fingerprint

SEED = 20261110
ALPHA = .0125
EFFECTS = (.9490, .7490, .6741, .5000)  # Intended ten-share city-day dollars.
ARMS = list(itertools.product((0, .22, .5), (0, .25, .5), (0, .25), ("spread", "clustered")))
N, M = 75, 12
ASK, FEE, RESERVE = .8, .05 * .8 * .2, .01
PER_SHARE_COST = ASK + FEE + RESERVE
COST = 5 * PER_SHARE_COST


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
    resamples = len(weights[0])
    hi_index = min(resamples-1, math.ceil((1-ALPHA)*resamples)-1)
    for weight, values in ((weights[0], panels.mean(axis=2)), (weights[1], panels.mean(axis=2)),
                           (weights[2], panels.reshape(len(panels), N*M))):
        draws = values @ weight.T - mean[:, None]
        pvalue = (1+(draws >= mean[:, None]-1e-10).sum(axis=1))/(resamples+1)
        high = np.partition(draws, hi_index, axis=1)[:, hi_index]
        result &= (mean-high > 1e-10) & (pvalue <= ALPHA)
    return result


def cash_mask(rng, available):
    """Outcome-independent nominal cash-lock stress, not a live-profit replay.

    Five-share nominal cost is locked 1 day (.9) or 3 days (.1), in actual
    UTC/city/cut order. Refund the nominal debit at release, so the null mask
    cannot select on earlier profit. Actual trial cash/P&L locks are enforced
    separately by core.py. This calibration family is explicitly conditional
    on this nominal-liquidity model, not all possible cash paths. It is not a
    uniform bound on the effects of realized losses on available cash.
    """
    import heapq
    np, _, _ = libraries()
    count = len(available)
    cash = np.full(count, 300.0)
    shares = np.zeros((count, N, M), dtype=np.float64)
    cities = sorted(CITIES)
    slots = sorted((local_cut(FIRST+timedelta(days=d), CITIES[city][0], h).timestamp()+30, city, h, d, j)
                   for d in range(N) for j, city in enumerate(cities) for h in (17, 18))
    pending, times = {}, []
    for at, _, _, d, j in slots:
        while times and times[0] <= at:
            release = heapq.heappop(times)
            cash += pending.pop(release)
        filled = available[:, d, j] & (cash+1e-10 >= COST)
        cash -= COST*filled
        shares[:, d, j] += 5*filled
        delay3 = rng.random(count) < .1
        for delay, mask in ((1, filled & ~delay3), (3, filled & delay3)):
            release = at + delay*86400
            if release not in pending:
                pending[release] = np.zeros(count)
                heapq.heappush(times, release)
            pending[release] += COST*mask
    return shares


def synthetic_panels(rng, count, arm, effect=0.0):
    """Gaussian-copula bounded cash flows; both cuts share one venue outcome.

    At the completeness floor, seven dates are missing and six additional
    city-days are missing on six distinct retained dates: exactly 810 city-days
    with two slots, 68 dates with >=11 covered cities, before cash stress.
    Clustered missingness puts three of those seven dates in one calendar block.
    Nominal paid cash is 0/1 per share, with no reward/mark-to-market proxy.
    """
    np, ndtr, _ = libraries()
    phi, common, persistent, mechanism = arm
    innovations = (math.sqrt(common)*rng.standard_normal((count, N, 1))
                   + math.sqrt(1-common)*rng.standard_normal((count, N, M)))
    latent = innovations.copy()
    for d in range(1, N):
        latent[:, d] = phi*latent[:, d-1] + math.sqrt(1-phi*phi)*innovations[:, d]
    latent = (math.sqrt(1-persistent)*latent
              + math.sqrt(persistent)*rng.standard_normal((count, 1, M)))
    available = np.ones((count, N, M), dtype=bool)
    for b in range(count):
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
    shares = cash_mask(rng, available)
    # 90% of intended shares at the completeness floor. Effect is already
    # expressed per scheduled ten-share city-day, not per filled share.
    probability = PER_SHARE_COST + effect/9
    if not 0 < probability < 1:
        raise ValueError("synthetic effect outside bounded payout family")
    panels = shares*((ndtr(latent) < probability)-PER_SHARE_COST)
    both = (shares == 10).sum(axis=(1, 2))
    adequate = ((shares == 10).sum(axis=2) >= 11).sum(axis=1)
    return panels, (both >= 810) & (adequate >= 68)


def hash_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        handle.write("\n")


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
    if not (0 <= args.arm_start < len(ARMS) and 1 <= args.arm_count <= 6):
        parser.error("bounded arm chunk required")
    if not args.out.is_absolute():
        parser.error("absolute synthetic output root required")
    np, _, _ = libraries()
    import scipy
    args.out.mkdir(parents=True, exist_ok=True)
    binding = {"code_sha256": hash_bytes(Path(__file__)),
               "inference_sha256": hash_bytes(Path(__file__).with_name("low_ask") / "inference.py"),
               "contracts_sha256": hash_bytes(Path(__file__).with_name("low_ask") / "contracts.py"),
               "timezone_sha256": timezone_fingerprint(), "numpy_version": np.__version__,
               "scipy_version": scipy.__version__,
               "null_n": args.null_simulations, "power_n": args.power_simulations,
               "resamples": 20_000, "seed": SEED, "alpha": ALPHA}
    tail = .05/len(ARMS)  # Simultaneous one-sided 95% across validation arms.
    if args.phase == "summarize":
        reports = [json.loads((args.out/f"validate-{i:02d}.json").read_text()) for i in range(len(ARMS))]
        if any(r["binding"] != binding for r in reports):
            raise ValueError("calibration binding drift")
        if any(r["critical_value"] != reports[0]["critical_value"] or r["arm_index"] != i
               for i, r in enumerate(reports)):
            raise ValueError("calibration arm/critical-value drift")
        sized = all(r["size_upper"] <= ALPHA for r in reports)
        powered = all(r["planning_power_lower"] >= .8 for r in reports)
        write_new(args.out / "CALIBRATION_RECEIPT.json", {
            "schema_version": "low_ask_calibration_v1",
            "status": "CALIBRATED" if sized and powered else "SCREEN_ONLY", "binding": binding,
            "critical_value": reports[0]["critical_value"], "size_upper": max(r["size_upper"] for r in reports),
            "power_lower": min(r["planning_power_lower"] for r in reports),
            "arms": [{"path": f"validate-{i:02d}.json", "sha256": hash_bytes(args.out/f"validate-{i:02d}.json")}
                     for i in range(len(ARMS))]})
        return 0
    critical = None
    if args.phase == "validate":
        fits = [json.loads((args.out/f"train-{i:02d}.json").read_text()) for i in range(len(ARMS))]
        if any(r["binding"] != binding for r in fits):
            raise ValueError("training binding drift")
        critical = max(2.241402727604947, *(r["critical_candidate"] for r in fits))
    weights = bootstrap_weights() if args.phase == "validate" else None
    for arm_index in range(args.arm_start, min(len(ARMS), args.arm_start+args.arm_count)):
        arm = ARMS[arm_index]
        # Training, validation and power use disjoint predetermined RNG streams.
        stream = 0 if args.phase == "train" else 1
        rng = np.random.default_rng(np.random.SeedSequence([SEED, arm_index, stream]))
        statistics = []
        for start in range(0, args.null_simulations, 128):
            budget()
            panels, _ = synthetic_panels(rng, min(128, args.null_simulations-start), arm)
            mean, scale, _ = scales(panels)
            degenerate = np.where(mean > 0, np.inf, np.where(mean < 0, -np.inf, 0.0))
            statistics.extend(np.divide(mean, scale, out=degenerate, where=scale > 0).tolist())
        report = {"schema_version": "low_ask_calibration_v1", "binding": binding, "arm_index": arm_index, "arm": arm}
        if args.phase == "train":
            # Select at .005, leaving safety room before independent .0125 validation.
            report["critical_candidate"] = float(np.quantile(statistics, .995, method="higher"))
        else:
            exceed = sum(t > critical for t in statistics)
            report.update(critical_value=critical, null_exceedances=exceed,
                          size_upper=upper_error(exceed, args.null_simulations, tail=tail), power=[])
            for effect_index, effect in enumerate(EFFECTS):
                rng = np.random.default_rng(np.random.SeedSequence([SEED, arm_index, 2, effect_index]))
                successes, sufficient = 0, 0
                for start in range(0, args.power_simulations, 32):
                    budget()
                    panels, coverage = synthetic_panels(rng, min(32, args.power_simulations-start), arm, effect)
                    success = bootstrap_success(panels, critical, weights) & coverage
                    successes += int(success.sum())
                    sufficient += int(coverage.sum())
                power_tail = .05/(len(ARMS)*len(EFFECTS))
                bound = lower_power(successes, args.power_simulations, tail=power_tail)
                report["power"].append({"intended_city_day_effect": effect, "successes": successes,
                                        "coverage_sufficient": sufficient, "lower": bound})
                if effect == .6741:
                    report["planning_power_lower"] = bound
        write_new(args.out / f"{args.phase}-{arm_index:02d}.json", report)
        print(json.dumps({"phase": args.phase, "arm": arm_index, "status": "SYNTHETIC_RECEIPT_WRITTEN"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
