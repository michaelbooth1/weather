"""HARNESS v3 H3: outcome-free power / MDE simulator for a crossed date x market design.

Cell model: delta[d, m] = effect + a_d + b_m + e_dm, a ~ N(0, var_date), b ~ N(0, var_market),
e ~ N(0, var_resid). Variance components come from an existing DEVELOPMENT score output (never
from labels here): a block's crossed, date-only and market-only bootstrap standard errors give

    r      = max(0, s_date^2 + s_market^2 - s_crossed^2)      (residual share of each SE^2)
    var_a  = D (s_date^2 - r),  var_b = M (s_market^2 - r),  var_e = D M r.

The simulated effect is ``--effect-fraction`` (default one half) of the development estimate.
Each simulated table is analysed with the two-way method-of-moments crossed variance
Var(mean) = (MS_date + MS_market - MS_resid) / (D M); GO when the 95% interval lies wholly on the
beneficial (negative) side. Both decision branches must be reachable; if the analytic MDE80 at the
planned design exceeds the bar, the verdict is UNTESTABLE.

Usage::

    python -m tools.research.model_parity.v3_power --stats C:\\swarm\\out\\r-stat-mg1\\stats.json \
        --key d1/mg1_minus_served/00-16 --dates 45 --markets 11 --bar 0.0133
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
from scipy.stats import norm

Z95 = float(norm.ppf(0.975))
Z80 = float(norm.ppf(0.80))


def _se_from_ci(ci):
    return (float(ci[1]) - float(ci[0])) / (2 * Z95)


def components_from_entry(entry, markets=None):
    """Variance components from one development stats entry (estimate, W_sd, date/market-only CIs)."""
    m = int(markets or entry.get("markets_n") or 11)
    d = max(2, int(round(int(entry["n_cells"]) / m)))
    s_c = float(entry.get("W_sd") or _se_from_ci(entry["W_ci95"]))
    s_d, s_m = _se_from_ci(entry["date_only_ci95"]), _se_from_ci(entry["market_only_ci95"])
    r = max(0.0, s_d ** 2 + s_m ** 2 - s_c ** 2)
    return {"dev_estimate": float(entry["estimate"]), "dev_dates": d, "dev_markets": m,
            "s_crossed": s_c, "s_date_only": s_d, "s_market_only": s_m,
            "var_date": max(0.0, d * (s_d ** 2 - r)), "var_market": max(0.0, m * (s_m ** 2 - r)),
            "var_resid": d * m * r}


def load_components(path, key, markets=None):
    with open(path, "rb") as stream:
        node = json.loads(stream.read().decode("utf-8"))
    for part in key.split("/"):
        node = node[part]
    out = components_from_entry(node, markets)
    out["source"] = {"path": str(path), "key": key}
    return out


def analytic_se(var_date, var_market, var_resid, dates, markets):
    return math.sqrt(var_date / dates + var_market / markets + var_resid / (dates * markets))


def crossed_se(table):
    """Method-of-moments SE of the grand mean of a balanced D x M table."""
    d, m = table.shape
    grand = table.mean()
    rows, cols = table.mean(axis=1), table.mean(axis=0)
    ms_d = m * ((rows - grand) ** 2).sum() / (d - 1)
    ms_m = d * ((cols - grand) ** 2).sum() / (m - 1)
    resid = table - rows[:, None] - cols[None, :] + grand
    ms_e = (resid ** 2).sum() / ((d - 1) * (m - 1))
    var = max(ms_d + ms_m - ms_e, ms_e) / (d * m)
    return math.sqrt(var)


def simulate(effect, var_date, var_market, var_resid, dates, markets, sims=2000, seed=20261019):
    rng = np.random.default_rng(seed)
    go = 0
    for _ in range(sims):
        t = (effect + rng.normal(0, math.sqrt(var_date), (dates, 1))
             + rng.normal(0, math.sqrt(var_market), (1, markets))
             + rng.normal(0, math.sqrt(var_resid), (dates, markets)))
        go += int((t.mean() + Z95 * crossed_se(t)) < 0)
    return go / sims


def plan(var_date, var_market, var_resid, dates, markets, dev_estimate, effect_fraction=0.5,
         bar=0.0133, sims=2000, seed=20261019):
    effect = effect_fraction * dev_estimate
    se = analytic_se(var_date, var_market, var_resid, dates, markets)
    mde80 = (Z95 + Z80) * se
    p_go_alt = simulate(effect, var_date, var_market, var_resid, dates, markets, sims, seed)
    p_go_null = simulate(0.0, var_date, var_market, var_resid, dates, markets, sims, seed + 1)
    reachable = {"GO": bool(p_go_alt > 0 or p_go_null > 0), "NO-GO": bool(p_go_alt < 1 or p_go_null < 1)}
    verdict = "UNTESTABLE" if mde80 > abs(bar) else "TESTABLE"
    return {"design": {"dates": dates, "markets": markets}, "simulated_effect": effect,
            "effect_fraction_of_dev": effect_fraction, "dev_estimate": dev_estimate,
            "components": {"var_date": var_date, "var_market": var_market, "var_resid": var_resid},
            "analytic_se": se, "mde80": mde80, "bar": abs(bar),
            "analytic_power": float(norm.cdf(abs(effect) / se - Z95)) if effect < 0 else None,
            "simulated_power_go_given_effect": p_go_alt, "simulated_go_given_null": p_go_null,
            "branches_reachable": reachable, "both_branches_reachable": all(reachable.values()),
            "verdict": verdict, "sims": sims, "seed": seed, "outcome_free": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stats", help="development stats JSON holding the variance-component entry")
    ap.add_argument("--key", help="slash path to the entry, e.g. d1/mg1_minus_served/00-16")
    ap.add_argument("--var-date", type=float)
    ap.add_argument("--var-market", type=float)
    ap.add_argument("--var-resid", type=float)
    ap.add_argument("--dev-estimate", type=float)
    ap.add_argument("--effect-fraction", type=float, default=0.5)
    ap.add_argument("--dates", type=int, required=True)
    ap.add_argument("--markets", type=int, default=11)
    ap.add_argument("--bar", type=float, default=0.0133)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261019)
    a = ap.parse_args(argv)
    comp = load_components(a.stats, a.key) if a.stats else {}
    get = lambda k, arg: arg if arg is not None else comp.get(k)
    vd, vm, ve = get("var_date", a.var_date), get("var_market", a.var_market), get("var_resid", a.var_resid)
    dev = get("dev_estimate", a.dev_estimate)
    if None in (vd, vm, ve, dev):
        ap.error("give --stats/--key or all of --var-date --var-market --var-resid --dev-estimate")
    out = plan(vd, vm, ve, a.dates, a.markets, dev, a.effect_fraction, a.bar, a.sims, a.seed)
    out["components_source"] = comp
    print(json.dumps(out, indent=1))
    print(out["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
