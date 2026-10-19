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


def components_from_table(table):
    """Two-way method-of-moments components from a balanced D x M table of cell deltas (2026-10-20).

    var_e = MS_resid, var_a = (MS_date - MS_resid) / M, var_b = (MS_market - MS_resid) / D, each
    clamped at 0. An alternative to ``components_from_entry`` when the cells themselves are at hand."""
    x = np.asarray(table, float)
    d, m = x.shape
    grand = x.mean()
    rows, cols = x.mean(axis=1), x.mean(axis=0)
    ms_d = m * ((rows - grand) ** 2).sum() / (d - 1)
    ms_m = d * ((cols - grand) ** 2).sum() / (m - 1)
    ms_e = ((x - rows[:, None] - cols[None, :] + grand) ** 2).sum() / ((d - 1) * (m - 1))
    return {"dev_estimate": float(grand), "dev_dates": d, "dev_markets": m, "method": "two-way MoM",
            "var_date": max(0.0, (ms_d - ms_e) / m), "var_market": max(0.0, (ms_m - ms_e) / d),
            "var_resid": float(ms_e)}


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


# ----------------------------------------------------------------------------- NO-GO clause and interim
# Added 2026-10-20. Outcome-free: means and (K x K) crossed covariance components are inputs.

Z975 = 1.959963984540054


def mom_cov(table):
    """Two-way MoM covariance components of a balanced (D, M, K) table: (Sigma_date, Sigma_market,
    Sigma_resid), each projected onto the PSD cone."""
    x = np.asarray(table, float)
    d, m, k = x.shape
    g = x.mean(axis=(0, 1))
    r = x.mean(axis=1) - g
    c = x.mean(axis=0) - g
    e = x - x.mean(axis=1)[:, None, :] - x.mean(axis=0)[None, :, :] + g
    ms_d = m * np.einsum("di,dj->ij", r, r) / (d - 1)
    ms_m = d * np.einsum("mi,mj->ij", c, c) / (m - 1)
    ms_e = np.einsum("dmi,dmj->ij", e, e) / ((d - 1) * (m - 1))

    def psd(a):
        w, v = np.linalg.eigh((a + a.T) / 2)
        return (v * np.clip(w, 0, None)) @ v.T
    return psd((ms_d - ms_e) / m), psd((ms_m - ms_e) / d), psd(ms_e)


def _draw(rng, sims, dates, markets, sd, sm, se):
    k = sd.shape[0]
    a = rng.multivariate_normal(np.zeros(k), sd, size=(sims, dates))
    b = rng.multivariate_normal(np.zeros(k), sm, size=(sims, markets))
    e = rng.multivariate_normal(np.zeros(k), se, size=(sims, dates, markets))
    return a[:, :, None, :] + b[:, None, :, :] + e


def batch_mean_se(x):
    """Grand mean and two-way MoM crossed SE for x of shape (S, D, M, K)."""
    s, d, m, k = x.shape
    g = x.mean(axis=(1, 2))
    rows, cols = x.mean(axis=2), x.mean(axis=1)
    ms_d = m * ((rows - g[:, None]) ** 2).sum(axis=1) / (d - 1)
    ms_m = d * ((cols - g[:, None]) ** 2).sum(axis=1) / (m - 1)
    resid = x - rows[:, :, None] - cols[:, None] + g[:, None, None]
    ms_e = (resid ** 2).sum(axis=(1, 2)) / ((d - 1) * (m - 1))
    return g, np.sqrt(np.maximum(ms_d + ms_m - ms_e, ms_e) / (d * m))


def simulate_nogo(r_means, e2_mean, comps, dates, markets, sims=20000, lb_bar=1.05, e2_bar=-0.005,
                  seed=20261020, chunk=1000):
    """P(NO-GO) for one arm. Variables 0..K-1 are the 00-16 blocks' R (influence scale, so a
    variable's simulated mean shifts R); variable K is E2 = Brier_blend / Brier_market - 1.

    NO-GO (verbatim rule): the lower bound of R is above 1.05 in every 00-16 block, AND the E2
    upper bound is above -0.5% of market Brier."""
    sd, sm, se = comps
    rng = np.random.default_rng(seed)
    r_means = np.asarray(r_means, float)
    hits = {"clause_R_all_blocks": 0, "clause_E2": 0, "nogo": 0}
    done = 0
    while done < sims:
        n = min(chunk, sims - done)
        g, s = batch_mean_se(_draw(rng, n, dates, markets, sd, sm, se))
        lower = r_means[None, :] + g[:, :-1] - Z975 * s[:, :-1]
        upper_e2 = e2_mean + g[:, -1] + Z975 * s[:, -1]
        c1 = (lower > lb_bar).all(axis=1)
        c2 = upper_e2 > e2_bar
        hits["clause_R_all_blocks"] += int(c1.sum())
        hits["clause_E2"] += int(c2.sum())
        hits["nogo"] += int((c1 & c2).sum())
        done += n
    return {k: v / sims for k, v in hits.items()} | {"sims": sims, "dates": dates, "markets": markets}


def simulate_interim(effect, comps, interim_dates, final_dates, markets, futility_z, sims=20000,
                     seed=20261020, chunk=1000):
    """Non-binding futility interim on a univariate crossed statistic whose positive mean is HARM
    (e.g. arm - served Brier, or R - 1). Z = -mean / SE; futility if Z_interim < futility_z;
    GO if Z_final > 1.96. Interim = the first ``interim_dates`` dates, same markets."""
    sd, sm, se = (np.atleast_2d(c) for c in comps)
    rng = np.random.default_rng(seed)
    fut = go = go_kept = 0
    done = 0
    while done < sims:
        n = min(chunk, sims - done)
        x = effect + _draw(rng, n, final_dates, markets, sd, sm, se)
        gi, si = batch_mean_se(x[:, :interim_dates])
        gf, sf = batch_mean_se(x)
        zi, zf = -gi[:, 0] / si[:, 0], -gf[:, 0] / sf[:, 0]
        f = zi < futility_z
        gg = zf > Z975
        fut += int(f.sum())
        go += int(gg.sum())
        go_kept += int((gg & ~f).sum())
        done += n
    return {"p_futility_at_interim": fut / sims, "p_go_final_ignoring_interim": go / sims,
            "p_go_final_if_futility_obeyed": go_kept / sims, "power_cost": (go - go_kept) / sims,
            "sims": sims, "interim_dates": interim_dates, "final_dates": final_dates, "markets": markets,
            "futility_z": futility_z}


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
