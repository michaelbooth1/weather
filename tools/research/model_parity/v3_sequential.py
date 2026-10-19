"""HARNESS v3 H7: non-binding O'Brien-Fleming-type futility interim (outcome-free).

Z is the one-sided improvement statistic (positive = arm better). Under the design alternative
the drift is theta = z(1-alpha) + z(1-beta). Futility boundaries b_k for interim looks at
information fractions t_k < 1 spend beta with the Lan-DeMets O'Brien-Fleming-type function
beta(t) = 2 - 2 Phi(z(1-beta/2) / sqrt(t)), computed by numerical integration of the score
process S_k = Z_k sqrt(t_k). The final look keeps the fixed critical value z(1-alpha); because the
futility rule is NON-BINDING (ignoring it never inflates alpha), type-I error is preserved.

``boundaries`` is pure arithmetic on the prereg's planned looks; the single-shot scorer writes and
seals its output before any label or market join.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

SCHEMA = "harness_v3_futility_boundaries/1"
STEP = 0.02


def beta_spent(t, beta):
    return float(2 - 2 * norm.cdf(norm.ppf(1 - beta / 2) / math.sqrt(t)))


def boundaries(looks, alpha=0.025, beta=0.2):
    """Futility z-boundaries for interim information fractions; last look must be 1.0."""
    looks = [float(x) for x in looks]
    if not looks or looks[-1] != 1.0 or any(b <= a for a, b in zip(looks, looks[1:])) or looks[0] <= 0:
        raise ValueError("looks must increase strictly within (0, 1] and end at 1.0")
    theta = norm.ppf(1 - alpha) + norm.ppf(1 - beta)
    lo, hi = -10.0, 10.0 + theta
    grid = np.arange(lo, hi + STEP, STEP)                 # S-space grid
    dens = None
    out, prev_t, prev_spend = [], 0.0, 0.0
    for k, t in enumerate(looks):
        dt = t - prev_t
        if dens is None:
            dens = norm.pdf(grid, loc=theta * t, scale=math.sqrt(t)) * STEP
        else:
            kern = norm.pdf(grid[:, None] - grid[None, :], loc=theta * dt, scale=math.sqrt(dt)) * STEP
            dens = kern @ dens
        if t == 1.0:
            out.append({"look": k + 1, "information_fraction": t, "kind": "final",
                        "efficacy_z": float(norm.ppf(1 - alpha)), "futility_z": None,
                        "beta_spent_cumulative": beta})
            break
        target = beta_spent(t, beta) - prev_spend
        cum = np.cumsum(dens)
        j = int(np.searchsorted(cum, target))
        s_b = grid[min(j, len(grid) - 1)]
        b = s_b / math.sqrt(t)
        if k == 0:   # first look is closed form (2026-10-20): Z1 ~ N(theta sqrt(t), 1)
            b = float(theta * math.sqrt(t) + norm.ppf(target))
            s_b = b * math.sqrt(t)
        out.append({"look": k + 1, "information_fraction": t, "kind": "interim_futility_nonbinding",
                    "futility_z": float(b), "beta_spent_increment": float(target),
                    "beta_spent_cumulative": beta_spent(t, beta)})
        dens = np.where(grid >= s_b, dens, 0.0)          # continue only above the boundary
        prev_t, prev_spend = t, beta_spent(t, beta)
    return {"schema": SCHEMA, "alpha_one_sided": alpha, "beta": beta, "theta_drift": float(theta),
            "spending": "Lan-DeMets O'Brien-Fleming-type beta spending", "binding": False,
            "looks": out}


def interim_decision(bounds, look, z):
    """'FUTILITY_NONBINDING' if z falls below the look's boundary, else 'CONTINUE' (or final GO/NO-GO)."""
    row = next(r for r in bounds["looks"] if r["look"] == look)
    if row["kind"] == "final":
        return "GO" if z > row["efficacy_z"] else "NO-GO"
    return "FUTILITY_NONBINDING" if z < row["futility_z"] else "CONTINUE"
