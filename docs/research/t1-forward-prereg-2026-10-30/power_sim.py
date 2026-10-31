"""T+1 prereg (f) power by simulation, with the futility path and deciding interval exactly as applied (rev 7).

No data is read. Daily d is a stationary Gaussian AR(1) with lag-1 rho, marginal sd sigma*k and mean -delta
(negative = blend better). Per path over N scored dates:
- futility, applied after the fact along the date-ordered path: z_j = mean_j / (s_j * sqrt(1.78) / sqrt(j));
  stop if z_7 > 3.143 (HARM), z_14 > 0.5, z_21 > 0, z_31 > -0.5 (looks at or beyond N are skipped);
- final (if not stopped): PASS iff mean_N + 1.96 * s_N * sqrt(VIF_look) / sqrt(N) < 0,
  VIF_look = max(1.78, (1+r)/(1-r)), r = lag-1 autocorrelation of the N accrued d.
Power = P(PASS). Usage: python power_sim.py OUT.json
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

RHO, DELTA, SIGMA, VIF_FLOOR = 0.28, 0.030, 0.085, 1.78
LOOKS = ((7, 3.143), (14, 0.5), (21, 0.0), (31, -0.5))
PATHS, SEED = 100_000, 20261030


def paths(n, k, rng):
    sd = SIGMA * k
    e = rng.standard_normal((PATHS, n)) * sd * math.sqrt(1 - RHO ** 2)
    x = np.empty((PATHS, n))
    x[:, 0] = rng.standard_normal(PATHS) * sd
    for t in range(1, n):
        x[:, t] = RHO * x[:, t - 1] + e[:, t]
    return x - DELTA


def power(n, k, seed=SEED):
    rng = np.random.default_rng(seed + n)
    x = paths(n, k, rng)
    alive = np.ones(PATHS, bool)
    stops = {}
    for j, bound in LOOKS:
        if j >= n:
            continue
        m, s = x[:, :j].mean(1), x[:, :j].std(1, ddof=1)
        z = m / (s * math.sqrt(VIF_FLOOR) / math.sqrt(j))
        hit = alive & (z > bound)
        stops[str(j)] = float(hit.mean())
        alive &= ~hit
    m, s = x.mean(1), x.std(1, ddof=1)
    xc = x - m[:, None]
    r = (xc[:, :-1] * xc[:, 1:]).sum(1) / (xc ** 2).sum(1)
    vif = np.maximum(VIF_FLOOR, (1 + r) / (1 - r))
    upper = m + 1.96 * s * np.sqrt(vif) / math.sqrt(n)
    return {"n": n, "k": k, "power": float((alive & (upper < 0)).mean()),
            "power_no_futility": float((upper < 0).mean()), "stopped": float((~alive).mean()), "stops": stops,
            "median_vif_look": float(np.median(vif))}


def main(out):
    res = {"rho": RHO, "delta": DELTA, "sigma_d": SIGMA, "vif_floor": VIF_FLOOR, "looks": LOOKS, "paths": PATHS,
           "seed": SEED, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "grid": []}
    for k in (1.0, 1.07):
        n = 63
        while True:
            row = power(n, k)
            res["grid"].append(row)
            if row["power"] >= 0.5:
                break
            n += 1
        res[f"n_min_power_0p5_k{k}"] = n
    res["at_63"] = [power(63, k) for k in (1.0, 1.07)]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({key: v for key, v in res.items() if key != "grid"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
