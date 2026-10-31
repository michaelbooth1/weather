r"""Lane L17 ledger row 95: Oct-Dec history LOYO batch W1 / X13 / X18 / X20 on the SM-L6 incumbent. History only.

Rule ``docs/research/p5-screens-2026-10-31/rule_octdec_loyo_batch.md`` (Amendment A2, sha pinned below). The
incumbent A0 and its strict nesting are row 92's (``permarket_octdec``): the SM-L6 OWN HGB fitted on Oct-Dec of
the other four years, the frozen MG-2 l6_stack, Gaussian integer-bucket Brier floored at the observed running max.
Every lever parameter for held-out year Y is fitted only on inner predictions of the years X != Y (fits outside
{X, Y}). Arms (K = 4): W1 day-specific width from ln max(|n - v|, 0.25); X13 overnight lows; X18 R-G trajectory
columns at 07-12; X20 the same at 13-14 on the unstacked A0' (S1 conditional). Statistic: date-cluster bootstrap
(B 10,000, seed 20261024), one-sided p, BH q 0.10 over K = 4, a calibration-matched placebo (J = 20 derangements)
netted per draw. Verdicts: "SCREEN" or "KILL at edge size"; UNTESTABLE and VOID are non-verdicts. Planted controls
are built in memory only, labelled CONTROL, never candidates. Nothing dated 2026 is read; no network; output only
below ``--out`` (under ``C:/t/l17/octdec``), write-once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

RULE_SHA256 = "0a1be8b0a6e6c0826cebc1b4c1df09b1f0907848fbb0993745d765de0066ddf5"
OUT_ROOT = Path("C:/t/l17/octdec")
DATE_MIN, DATE_MAX = "2021-01-01", "2025-12-31"
LAST_LOCAL = date(2025, 12, 31)
ARMS = ("W1", "X13", "X18", "X20")
K = len(ARMS)
BH_Q = 0.10
BOOT_DRAWS = 10_000
BOOT_SEED = 20261024
PLACEBO_J = 20
PLACEBO_SEED0 = 20260921
PLANT_SEED = 20261031
GAMMA_GRID = tuple(round(0.05 * i, 2) for i in range(21))
Z_FLOOR = 0.25
LOGMULT_MAX = 0.02
P0_RHO_MIN = 0.05
P0_MAX_OPPOSITE_YEARS = 1
COVERAGE_MIN = 0.90
X20_HOURS = (13, 14)
X20_MIN_ROWS = 10_000
X20_MIN_DATES = 300
X20_S_FINITE_MIN = 0.90
NEG_IDENTICAL_TOL = 1e-9
W1_NEG_MIN_ZERO_FOLDS = 4
X13_COLUMNS = ("low_so_far_minus_mu", "low_prev_evening_minus_mu")
RG_FEATURES = ("t_trend3", "t_trend3_miss", "t_amp", "t_path_gap")
VERDICT_SCREEN = "SCREEN"
VERDICT_KILL = "KILL at edge size"


class OctDecBatchError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- guards

def check_out_dir(out):
    """``out`` must sit strictly below OUT_ROOT and must not exist yet (write-once run directory)."""
    root = OUT_ROOT.resolve()
    path = Path(out).resolve()
    if path == root or root not in path.parents:
        raise OctDecBatchError(f"--out {path} is not strictly below {root}")
    if path.exists():
        raise OctDecBatchError(f"--out {path} already exists (write-once)")
    return path


def check_dates(dates, what):
    """Refuse any local date outside 2021-01-01..2025-12-31."""
    bad = sorted({str(d)[:10] for d in dates if not (DATE_MIN <= str(d)[:10] <= DATE_MAX)})
    if bad:
        raise OctDecBatchError(f"{what}: {len(bad)} date(s) outside {DATE_MIN}..{DATE_MAX}, first {bad[0]}")


def _write(out_dir, name, payload):
    from weather.calibration import cool_season_audit as cs

    return cs._write_once(Path(out_dir) / name, payload)


# ----------------------------------------------------------------------------- nesting

def inner_pairs(years):
    return [frozenset((x, y)) for i, x in enumerate(years) for y in years[i + 1:]]


def inner_train_years(years, pair):
    """Training years of the inner fit for ``pair`` = {X, Y}: every year outside the pair."""
    return tuple(y for y in years if y not in pair)


def fold_fit_mu(year, y_out, inner_mu, n_rows):
    """Fit-row centre for held-out year Y: rows of year X != Y take the inner prediction from the {X, Y} fit."""
    import numpy as np

    out = np.full(n_rows, np.nan)
    for pair, mu in inner_mu.items():
        if y_out not in pair:
            continue
        (x,) = tuple(pair - {y_out})
        sel = year == x
        out[sel] = mu[sel]
    return out


# ----------------------------------------------------------------------------- incumbent

def a0(frame, n, coef, stacked):
    """(mu, sigma, ok): the SM-L6 stack (07-12) or the unstacked OWN nowcast A0' (13-14)."""
    import numpy as np

    from weather.calibration import permarket_octdec as pmo

    if stacked:
        return pmo.stack_mu(frame, n, coef)
    s = frame.s.to_numpy(float)
    return np.asarray(n, float).copy(), np.maximum(s, 1.0), np.isfinite(n) & np.isfinite(s)


def brier(mu, sig, R, dmax):
    from weather.calibration import permarket_octdec as pmo

    return pmo.brier(mu, sig, R, dmax)


# ----------------------------------------------------------------------------- centre arms (X13 / X18 / X20)

def complete_rows(X):
    import numpy as np

    return np.isfinite(X).all(1)


def fit_centre(X, resid, hour, fit):
    """Per hour: no-intercept OLS of ``resid`` on the columns centred with fit-row means. Rows with any missing
    column are excluded from the fit; returns {h: (beta, means, n_fit)}."""
    import numpy as np

    out = {}
    full = complete_rows(X) & np.isfinite(resid)
    for h in sorted(set(hour[fit].tolist())):
        sel = fit & full & (hour == h)
        if sel.sum() <= X.shape[1]:
            out[int(h)] = (np.zeros(X.shape[1]), np.zeros(X.shape[1]), int(sel.sum()))
            continue
        means = X[sel].mean(0)
        beta = np.linalg.lstsq(X[sel] - means, resid[sel], rcond=None)[0]
        out[int(h)] = (beta, means, int(sel.sum()))
    return out


def centre_shift(X, hour, rows, params):
    """Additive centre change on ``rows``: (x - mean_fit)·beta per hour; 0 where a column is missing (A0 kept)."""
    import numpy as np

    delta = np.zeros(len(hour))
    full = complete_rows(X)
    for h, (beta, means, _) in params.items():
        sel = rows & full & (hour == h)
        delta[sel] = (X[sel] - means) @ beta
    return delta


def centre_arm(X_by_fold, ctx, zero=False):
    """Nested LOYO centre arm. ``X_by_fold[Y]`` is the column matrix used for fold Y (fit rows and test rows).
    Returns (mu_arm on test rows, params per fold, training-score check per fold)."""
    import numpy as np

    mu_arm = ctx["mu0"].copy()
    params, train_ok = {}, {}
    for y in ctx["years"]:
        X = X_by_fold[y]
        fit = ctx["ok"] & (ctx["year"] != y)
        test = ctx["ok"] & (ctx["year"] == y)
        mu_fit = ctx["mu_fit"][y]
        p = fit_centre(X, ctx["dmax"] - mu_fit, ctx["hour"], fit)
        if zero:
            p = {h: (np.zeros_like(b), m, n) for h, (b, m, n) in p.items()}
        params[y] = p
        mu_arm[test] = ctx["mu0"][test] + centre_shift(X, ctx["hour"], test, p)[test]
        shifted = mu_fit[fit] + centre_shift(X, ctx["hour"], fit, p)[fit]
        b1 = float(np.mean(brier(shifted, ctx["sig"][fit], ctx["R"][fit], ctx["dmax"][fit])))
        b0 = float(np.mean(brier(mu_fit[fit], ctx["sig"][fit], ctx["R"][fit], ctx["dmax"][fit])))
        train_ok[str(y)] = {"brier_lever": b1, "brier_zero": b0, "pass": bool(not (b1 > b0))}
    return mu_arm, params, train_ok


def betas(params):
    return {str(y): {str(h): [float(v) for v in b] for h, (b, _, _) in p.items()} for y, p in params.items()}


# ----------------------------------------------------------------------------- W1 width arm

def w1_z(n, v):
    import numpy as np

    return np.log(np.maximum(np.abs(np.asarray(n, float) - np.asarray(v, float)), Z_FLOOR))


def w1_sigma(sig, z, zbar, gamma):
    """sigma' = max(1, sigma·exp(gamma·(z - zbar))): the 1 deg F floor is never weakened."""
    import numpy as np

    return np.maximum(1.0, sig * np.exp(gamma * (z - zbar)))


def zbar_rows(markets, hour, z, fit):
    """Per-row mean of z over the fit rows of the same (market, hour); rows of an unseen cell get z itself."""
    import numpy as np
    import pandas as pd

    df = pd.DataFrame({"m": markets[fit], "h": hour[fit], "z": z[fit]})
    means = df.groupby(["m", "h"]).z.mean().to_dict()
    return np.array([means.get((m, h), zz) for m, h, zz in zip(markets, hour, z)], float)


def w1_arm(z_by_fold, ctx, zero=False):
    """Nested LOYO W1. ``z_by_fold[Y]`` carries the inner-fit z on fit rows and the outer z on test rows.
    gamma_h is the grid minimiser of the fit-row Brier (ties to the smallest); the LOGMULT guard sets gamma_h = 0
    when the fit-row mean ln(sigma'/sigma) of that hour exceeds 0.02 in magnitude."""
    import numpy as np

    sig_arm = ctx["sig"].copy()
    params, train_ok, zc_test = {}, {}, np.full(len(sig_arm), np.nan)
    for y in ctx["years"]:
        z = z_by_fold[y]
        fit = ctx["ok"] & (ctx["year"] != y)
        test = ctx["ok"] & (ctx["year"] == y)
        mu_fit = ctx["mu_fit"][y]
        zbar = zbar_rows(ctx["markets"], ctx["hour"], z, fit)
        zc_test[test] = (z - zbar)[test]
        hours = sorted(set(ctx["hour"][fit].tolist()))
        means = {}
        for g in GAMMA_GRID:
            sp = w1_sigma(ctx["sig"][fit], z[fit], zbar[fit], g)
            b = brier(mu_fit[fit], sp, ctx["R"][fit], ctx["dmax"][fit])
            for h in hours:
                means[(g, h)] = float(np.mean(b[ctx["hour"][fit] == h]))
        gam, guard = {}, {}
        for h in hours:
            best = min(means[(g, h)] for g in GAMMA_GRID)
            g_h = min(g for g in GAMMA_GRID if means[(g, h)] == best)
            fh = fit & (ctx["hour"] == h)
            lm = float(np.mean(np.log(w1_sigma(ctx["sig"][fh], z[fh], zbar[fh], g_h) / ctx["sig"][fh])))
            guard[str(h)] = {"gamma_fitted": g_h, "mean_log_multiplier": lm, "guarded": bool(abs(lm) > LOGMULT_MAX)}
            gam[h] = 0.0 if (zero or abs(lm) > LOGMULT_MAX) else g_h
        params[y] = {"gamma": {str(h): gam[h] for h in hours}, "logmult_guard": guard}
        for h in hours:
            th = test & (ctx["hour"] == h)
            sig_arm[th] = w1_sigma(ctx["sig"][th], z[th], zbar[th], gam[h])
        b1 = sum(means[(gam[h], h)] * int((fit & (ctx["hour"] == h)).sum()) for h in hours)
        b0 = sum(means[(0.0, h)] * int((fit & (ctx["hour"] == h)).sum()) for h in hours)
        train_ok[str(y)] = {"brier_lever_sum": b1, "brier_zero_sum": b0, "pass": bool(not (b1 > b0))}
    return sig_arm, params, train_ok, zc_test


def w1_p0(zc_test, ctx):
    """R-Z P0: pooled Spearman rho(z - zbar, |dmax - mu|) on the test rows >= 0.05, at most 1 opposite-sign year."""
    import numpy as np
    from scipy.stats import spearmanr

    ok = ctx["ok"] & np.isfinite(zc_test)
    a = np.abs(ctx["dmax"] - ctx["mu0"])
    rho = float(spearmanr(zc_test[ok], a[ok]).correlation)
    per = {}
    for y in ctx["years"]:
        sel = ok & (ctx["year"] == y)
        per[str(y)] = float(spearmanr(zc_test[sel], a[sel]).correlation) if sel.sum() > 2 else float("nan")
    opposite = sum(1 for v in per.values() if not (v > 0))
    return {"rho": rho, "per_year": per, "opposite_years": opposite, "rho_min": P0_RHO_MIN,
            "pass": bool(rho >= P0_RHO_MIN and opposite <= P0_MAX_OPPOSITE_YEARS)}


# ----------------------------------------------------------------------------- statistic

def _date_sums(d, dates):
    import pandas as pd

    per = pd.DataFrame({"d": d, "c": dates}).groupby("c").d.agg(["sum", "size"])
    return per.index.to_numpy(), per["sum"].to_numpy(float), per["size"].to_numpy(float)


def boot_indices(n_dates, draws=BOOT_DRAWS, seed=BOOT_SEED):
    """The same resampling as ``upstream_obs_screen.cluster_ci``(draws, seed)."""
    import numpy as np

    return np.random.default_rng(seed).integers(0, n_dates, size=(draws, n_dates))


def bootstrap(d, dates, placebos=(), draws=BOOT_DRAWS, seed=BOOT_SEED):
    """Mean, 95% CI and one-sided p = (1 + #{mean* >= 0})/(B + 1) of per-row d (date clusters); with placebos,
    d_net* = d* - d_pl,(b mod J)* on the same draw, and the d_net point is mean(d) - mean_j mean(d_pl,j)."""
    import numpy as np

    from weather.calibration import successor_odc_low as c1

    if any(len(dp) != len(d) for dp in placebos) or len(dates) != len(d):
        raise OctDecBatchError("placebo rows differ from the arm rows")
    keys, s, n = _date_sums(d, dates)
    idx = boot_indices(len(s), draws, seed)
    nb = n[idx].sum(1)
    boot = s[idx].sum(1) / nb
    point = float(s.sum() / n.sum())
    out = {"point": point, "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
           "p_one_sided": float((1 + int((boot >= 0).sum())) / (draws + 1)), "n_rows": int(len(d)),
           "n_dates": int(len(s))}
    if float(np.std(s / n)) > 0:
        daily = c1.daily_stats(dates, d)
        out["block3_ci95"] = [point - 1.96 * daily["se_block3"], point + 1.96 * daily["se_block3"]]
        out["daily_stats"] = daily
    else:  # a lever fitted to 0 everywhere: d is identically 0 and the daily statistics are undefined
        out["block3_ci95"] = [point, point]
        out["daily_stats"] = None
    if placebos:
        net = np.empty(draws)
        pl_points = []
        for j, dp in enumerate(placebos):
            kj, sj, nj = _date_sums(dp, dates)
            if not (np.array_equal(kj, keys) and np.array_equal(nj, n)):
                raise OctDecBatchError("placebo rows differ from the arm rows")
            pl_points.append(float(sj.sum() / nj.sum()))
            rows = np.arange(j, draws, len(placebos))
            net[rows] = boot[rows] - sj[idx[rows]].sum(1) / nb[rows]
        out["d_net"] = {"point": point - float(np.mean(pl_points)),
                        "ci95": [float(np.quantile(net, 0.025)), float(np.quantile(net, 0.975))],
                        "placebo_points": pl_points}
    return out


def bh_reject(pvals, q=BH_Q):
    """Benjamini-Hochberg step-up: {name: (adjusted q, reject)}."""
    names = sorted(pvals, key=lambda k: (pvals[k], k))
    m = len(names)
    adj, running = {}, 1.0
    for rank in range(m, 0, -1):
        name = names[rank - 1]
        running = min(running, pvals[name] * m / rank)
        adj[name] = running
    return {k: (float(adj[k]), bool(adj[k] <= q)) for k in pvals}


def control_pass(stats):
    """A planted control PASSES on its own iff p <= q/K (the strictest BH step) and the Δ upper bound < 0."""
    return bool(stats["p_one_sided"] <= BH_Q / K and stats["ci95"][1] < 0)


# ----------------------------------------------------------------------------- placebo

def placebo_src(markets, hour, year, dates, seed):
    """Donor row per row: dates deranged (no fixed point) within (market, hour, year), so the donor keeps the
    row's fold role. ``market_blend.derangement``; one generator per seed, groups in sorted order."""
    import numpy as np
    import pandas as pd

    from weather.calibration import market_blend as mb

    df = pd.DataFrame({"i": np.arange(len(dates)), "m": markets, "h": hour, "y": year, "d": dates})
    if df.duplicated(["m", "h", "d"]).any():
        raise OctDecBatchError("placebo needs one row per (market, hour, date)")
    rng = np.random.default_rng(seed)
    src = np.arange(len(dates))
    for _, g in df.sort_values(["m", "h", "y", "d"], kind="mergesort").groupby(["m", "h", "y"], sort=True):
        rows = g.i.to_numpy()
        perm = mb.derangement(len(rows), rng)
        src[rows] = rows[perm]
    return src


# ----------------------------------------------------------------------------- columns

def _ns(values):
    import pandas as pd

    return pd.DatetimeIndex(values).tz_convert("UTC").as_unit("ns").asi8


def x13_columns(frame, obs_g_by_station, tz_by_station):
    """(low_so_far, low_prev_evening) per row from ``ols_floor_ladder.overnight_lows`` fed the pinned upstream
    market obs (non-corrected, temp, local minute of day), rows available at or before the query instant
    (local h:30, as ``history_queries``); ``overnight_lows`` then keeps minute_of_day <= h:00."""
    import numpy as np
    import pandas as pd

    from weather.calibration import ols_floor_ladder as lad

    low = np.full(len(frame), np.nan)
    prev = np.full(len(frame), np.nan)
    stats = {"rows": int(len(frame)), "no_temperature_before_cutoff": 0, "prev_evening_missing": 0}
    for station, idx in frame.groupby("station").indices.items():
        g = obs_g_by_station[station]
        tz = tz_by_station[station]
        local = g.valid_utc.dt.tz_convert(tz)
        minute = (local.dt.hour * 60 + local.dt.minute).to_numpy(int)
        temp = g.temp.to_numpy(float)
        avail = _ns(g.avail)
        by_day = {}
        for d, ii in pd.Series(g.local_date.to_numpy()).groupby(g.local_date.to_numpy()).indices.items():
            by_day[str(d)] = (minute[ii], temp[ii], avail[ii])
        sub = frame.iloc[idx]
        loc = pd.to_datetime(sub.local_date) + pd.to_timedelta(sub.hour, unit="h") + pd.Timedelta(minutes=30)
        t_loc = loc.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
        valid_t = t_loc.notna().to_numpy()
        t_ns = np.zeros(len(sub), np.int64)
        if valid_t.any():
            t_ns[valid_t] = _ns(t_loc[valid_t])
        for i, d, h, t, vt in zip(idx, sub.local_date.astype(str), sub.hour.astype(int), t_ns, valid_t):
            day = by_day.get(d)
            if day is None or not vt:
                stats["no_temperature_before_cutoff"] += 1
                continue
            keep = day[2] <= t
            rows = [{"minute_of_day": int(m), "temp_native": float(x)} for m, x in zip(day[0][keep], day[1][keep])]
            p = by_day.get((date.fromisoformat(d) - timedelta(days=1)).isoformat())
            prev_rows = [] if p is None else [{"minute_of_day": int(m), "temp_native": float(x)}
                                              for m, x in zip(p[0], p[1])]
            try:
                lo, pv = lad.overnight_lows(rows, d, h, prev_rows, None)
            except lad.LadderError:
                stats["no_temperature_before_cutoff"] += 1
                continue
            low[i] = lo
            if pv is None:
                stats["prev_evening_missing"] += 1
            else:
                prev[i] = pv
    return low, prev, stats


def rg_columns_for_fold(frame, iem, reports_tz, timezones, y_out):
    """R-G columns (``pooled_residual_model.rg_training_columns``, F = r, fh = v, h:00 cutoff) with the diurnal
    fraction re-estimated on the fold's own training years (years != Y). t_trend3 missing -> 0 with its indicator."""
    import numpy as np
    import pandas as pd

    from weather.calibration import cool_season_audit as cs
    from weather.calibration import pooled_residual_model as prm

    years = tuple(y for y in cs.YEARS if y != y_out)
    fracs = {m: prm.rg_diurnal_fraction(iem[m], reports_tz[m], years=years) for m in iem}
    rg = pd.DataFrame({"market": frame.market.astype(str).to_numpy(), "target_date": frame.local_date.astype(str)
                       .to_numpy(), "hour": frame.hour.astype(int).to_numpy(), "F": frame.r.to_numpy(float),
                       "fh": frame.v.to_numpy(float)})
    cols, stats = prm.rg_training_columns(rg, iem, fracs, timezones)
    X = cols[list(RG_FEATURES)].to_numpy(float)
    miss = X[:, 1] == 1.0
    X[miss, 0] = 0.0
    if tuple(prm.RG_FEATURES) != RG_FEATURES:
        raise OctDecBatchError("pooled_residual_model.RG_FEATURES changed")
    return X, stats


# ----------------------------------------------------------------------------- rows

def rows_at_hours(research_root, nbm_corpus, hours):
    """Local copy of ``cool_season_audit.l6_rows`` with ``hours`` in place of HOURS_0712 (X20's 13-14 rows)."""
    import numpy as np
    import pandas as pd

    from weather.calibration import cool_season_audit as cs
    from weather.calibration import rz_hrrr_spread as rz
    from weather.calibration import upstream_obs_screen as l6

    obs, sel, prov = l6.load(research_root)
    if prov["obs_sha256"] != rz.OBS_SHA256:
        raise OctDecBatchError(f"L6 obs sha {prov['obs_sha256']} != {rz.OBS_SHA256}")
    nbm = rz.load_nbm_with_sd([nbm_corpus])
    frames = []
    for code, icao in enumerate(l6.stations(sel)):
        m = sel[icao]
        g, dmax = l6.market_series(obs, icao, m["timezone"])
        dates = [d for d in dmax.index if DATE_MIN <= d <= DATE_MAX and int(d[5:7]) >= 8]
        q = rz.history_queries(dates, m["timezone"], hours)
        f = l6.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["station"], f["local_date"], f["hour"] = icao, q.local_date, q.hour
        f["market"] = m["market"]
        f["dmax"] = q.local_date.map(dmax).to_numpy(float)
        got = [rz.nbm_at(nbm, m["market"], d, int(h), m["timezone"]) for d, h in zip(q.local_date, q.hour)]
        f["v"] = [x[0] for x in got]
        f["s"] = [x[1] for x in got]
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out = out[np.isfinite(out.r) & np.isfinite(out.t) & np.isfinite(out.dmax)].reset_index(drop=True)
    out = out[~out.station.isin(cs.EXCLUDED_STATIONS)].reset_index(drop=True)
    out["year"] = out.local_date.str[:4].astype(int)
    out["month"] = out.local_date.str[5:7].astype(int)
    check_dates(out.local_date, f"rows at hours {tuple(hours)}")
    return out, prov


def _ctx(frame, n_out, inner_n, coef, stacked, years):
    """Arrays shared by every arm on one frame: A0, the ok mask (outer and every inner fit finite) and the
    per-fold fit-row centre."""
    import numpy as np

    mu0, sig, ok = a0(frame, n_out, coef, stacked)
    year = frame.year.to_numpy(int)
    inner_mu = {}
    for pair, n_in in inner_n.items():
        mu_in, _, ok_in = a0(frame, n_in, coef, stacked)
        inner_mu[pair] = mu_in
        te = np.isin(year, tuple(pair))
        ok = ok & (ok_in | ~te)
    mu_fit = {y: fold_fit_mu(year, y, inner_mu, len(frame)) for y in years}
    n_fit = {y: fold_fit_mu(year, y, inner_n, len(frame)) for y in years}
    return {"frame": frame, "mu0": mu0, "sig": sig, "ok": ok, "year": year, "years": years,
            "hour": frame.hour.to_numpy(int), "markets": frame.market.astype(str).to_numpy(),
            "dates": frame.local_date.astype(str).to_numpy(), "R": frame.r.to_numpy(float),
            "dmax": frame.dmax.to_numpy(float), "v": frame.v.to_numpy(float), "n_out": np.asarray(n_out, float),
            "mu_fit": mu_fit, "n_fit": n_fit}


def per_fold_ref(year, years, fit_vec, outer):
    """Per-fold vector: ``fit_vec[Y]`` on rows of years != Y (inner fits), ``outer`` on year-Y (test) rows."""
    import numpy as np

    out = {}
    for y in years:
        v = np.asarray(fit_vec[y], float).copy()
        v[year == y] = np.asarray(outer, float)[year == y]
        out[y] = v
    return out


# ----------------------------------------------------------------------------- run

def run(*, research_root, nbm_corpus, mg2_coefficients, rule, c1_receipt, out):
    import numpy as np
    from zoneinfo import ZoneInfo

    from weather.calibration import cool_season_audit as cs
    from weather.calibration import permarket_octdec as pmo
    from weather.calibration import pooled_residual_model as prm
    from weather.calibration import season_matched_l6 as sm
    from weather.calibration import upstream_obs_screen as l6
    from weather.model import mg_serve_core as core

    got = _sha(rule)
    if got != RULE_SHA256:
        raise OctDecBatchError(f"rule sha {got} != {RULE_SHA256}")
    out_dir = check_out_dir(out)
    cs._pin(nbm_corpus, sm.NBM_CORPUS_SHA256, "NBM corpus")
    cs._pin(mg2_coefficients, cs.MG2_COEF_SHA256, "MG-2 coefficients")
    cs._pin(c1_receipt, pmo.C1_RECEIPT_SHA256, "C1 receipt")
    out_dir.mkdir(parents=True, exist_ok=False)
    coef = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    years = tuple(cs.YEARS)

    train, prov = sm.training_rows(research_root)
    check_dates(train.local_date, "training rows")
    rows, _ = cs.l6_rows(research_root, nbm_corpus)
    rows = rows[rows.month.isin(sm.TRAIN_MONTHS)].reset_index(drop=True)
    check_dates(rows.local_date, "07-12 rows")
    late, _ = rows_at_hours(research_root, nbm_corpus, X20_HOURS)
    late = late[late.month.isin(sm.TRAIN_MONTHS)].reset_index(drop=True)

    # ---- columns (outcome-free) and S1 coverage, written before any Brier or residual
    obs, sel, _ = l6.load(research_root)
    tz_station = {icao: sel[icao]["timezone"] for icao in sel}
    g_station = {icao: l6.market_series(obs, icao, sel[icao]["timezone"])[0] for icao in sel}
    timezones = {sel[icao]["market"]: sel[icao]["timezone"] for icao in sel}
    markets = sorted(set(rows.market.astype(str)) | set(late.market.astype(str)))
    iem, _ = prm.rg_iem_reports(Path(research_root) / "upstream_obs" / "obs.parquet", markets, timezones,
                                last_local=LAST_LOCAL)
    for m in markets:
        if iem[m][0] and date.fromordinal(max(iem[m][2])) > LAST_LOCAL:
            raise OctDecBatchError(f"IEM reports after {LAST_LOCAL} for {m}")
    rtz = {m: ZoneInfo(timezones[m]) for m in markets}
    low, prev, x13_stats = x13_columns(rows, g_station, tz_station)
    x18 = {y: rg_columns_for_fold(rows, iem, rtz, timezones, y) for y in years}
    x20 = {y: rg_columns_for_fold(late, iem, rtz, timezones, y) for y in years}
    base07 = np.isfinite(rows.v.to_numpy(float)) & np.isfinite(rows.s.to_numpy(float))
    base13 = np.isfinite(late.s.to_numpy(float))
    yr07, yr13 = rows.year.to_numpy(int), late.year.to_numpy(int)

    def fold_cov(cols, yr, base):
        full = np.zeros(len(yr), bool)
        for y in years:
            full[yr == y] = complete_rows(cols[y][0])[yr == y]
        return float((full & base).sum() / max(int(base.sum()), 1)), int((base & ~full).sum())

    cov = {"W1": (float(base07.sum() / len(rows)), int((~base07).sum())),
           "X13": (float((np.isfinite(low) & np.isfinite(prev) & base07).sum() / max(int(base07.sum()), 1)),
                   int((base07 & ~(np.isfinite(low) & np.isfinite(prev))).sum())),
           "X18": fold_cov(x18, yr07, base07), "X20": fold_cov(x20, yr13, base13)}
    late_dates = int(late.local_date[base13].nunique())
    x20_block = {"rows": int(len(late)), "rows_s_finite": int(base13.sum()), "dates": late_dates,
                 "s_finite_fraction": float(base13.mean()) if len(late) else 0.0,
                 "min_rows": X20_MIN_ROWS, "min_dates": X20_MIN_DATES, "min_s_finite": X20_S_FINITE_MIN}
    x20_block["pass"] = bool(len(late) >= X20_MIN_ROWS and late_dates >= X20_MIN_DATES
                             and x20_block["s_finite_fraction"] >= X20_S_FINITE_MIN)
    testable = {a: bool(cov[a][0] >= COVERAGE_MIN) for a in ARMS}
    testable["X20"] = bool(testable["X20"] and x20_block["pass"])
    s1 = {"label": "ledger row 95 S1 coverage (outcome-free; before any Brier or residual)",
          "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__), "coverage_min": COVERAGE_MIN,
          "arms": {a: {"coverage": cov[a][0], "rows_lever_zero_missing_column": cov[a][1], "testable": testable[a]}
                   for a in ARMS},
          "x20_13_14_block": x20_block, "x13_adapter": x13_stats,
          "rg_stats": {"X18": {str(y): x18[y][1] for y in years}, "X20": {str(y): x20[y][1] for y in years}},
          "rows_07_12": int(len(rows)), "rows_13_14": int(len(late))}
    _write(out_dir, "s1_coverage.json", s1)

    # ---- the 15 shared HGB fits (5 outer, 10 inner), predicting both frames
    n_out = {"07": np.full(len(rows), np.nan), "13": np.full(len(late), np.nan)}
    for y in years:
        st = sm.fit_state(train[train.year != y], {"fold": y})
        for key, fr in (("07", rows), ("13", late)):
            te = (fr.year == y).to_numpy()
            if te.any():
                n_out[key][te] = core.l6_own_nowcast(st, fr[te])
    inner_n = {"07": {}, "13": {}}
    for pair in inner_pairs(years):
        tr_years = inner_train_years(years, pair)
        st = sm.fit_state(train[train.year.isin(tr_years)], {"inner": sorted(pair)})
        for key, fr in (("07", rows), ("13", late)):
            v = np.full(len(fr), np.nan)
            te = fr.year.isin(tuple(pair)).to_numpy()
            if te.any():
                v[te] = core.l6_own_nowcast(st, fr[te])
            inner_n[key][pair] = v
    c07 = _ctx(rows, n_out["07"], inner_n["07"], coef, True, years)
    c13 = _ctx(late, n_out["13"], inner_n["13"], coef, False, years)
    b0 = {}
    for key, c in (("07", c07), ("13", c13)):
        ok = c["ok"]
        b = np.full(len(ok), np.nan)
        b[ok] = brier(c["mu0"][ok], c["sig"][ok], c["R"][ok], c["dmax"][ok])
        b0[key] = b

    def d_of(c, key, mu=None, sig=None):
        ok = c["ok"]
        mu = c["mu0"] if mu is None else mu
        sig = c["sig"] if sig is None else sig
        return brier(mu[ok], sig[ok], c["R"][ok], c["dmax"][ok]) - b0[key][ok]

    # ---- per-fold signals
    mu_ref07 = per_fold_ref(c07["year"], years, c07["mu_fit"], c07["mu0"])
    n_ref07 = per_fold_ref(c07["year"], years, c07["n_fit"], c07["n_out"])
    X = {"X13": {y: np.column_stack([low - mu_ref07[y], prev - mu_ref07[y]]) for y in years},
         "X18": {y: x18[y][0] for y in years}, "X20": {y: x20[y][0] for y in years}}
    Z = {y: w1_z(n_ref07[y], c07["v"]) for y in years}

    # ---- controls (CONTROL-labelled, in memory only)
    controls = {}
    p_inc, base, _ = sm.stack_brier(rows, n_out["07"], coef)
    control = sm.tables(rows, p_inc, base)["oct_dec"]["pooled"]
    c1r = json.loads(Path(c1_receipt).read_text(encoding="utf-8"))["control_incumbent_vs_mg1_pooled"]
    ca = {"estimate": control["estimate"], "n_rows": control["n_rows"], "c1_estimate": c1r["estimate"],
          "abs_diff": abs(control["estimate"] - pmo.C1_CONTROL_ESTIMATE)}
    ca["pass"] = bool(ca["abs_diff"] <= pmo.CONTROL_TOL and control["n_rows"] == pmo.C1_CONTROL_ROWS
                      and c1r["estimate"] == pmo.C1_CONTROL_ESTIMATE and int(c07["ok"].sum()) == pmo.C1_CONTROL_ROWS)
    controls["C_a_reproduction"] = ca
    cb = {}
    mz, _, _ = centre_arm(X["X13"], c07, zero=True)
    cb["X13"] = float(np.max(np.abs(d_of(c07, "07", mu=mz)))) if c07["ok"].any() else 0.0
    mz, _, _ = centre_arm(X["X18"], c07, zero=True)
    cb["X18"] = float(np.max(np.abs(d_of(c07, "07", mu=mz)))) if c07["ok"].any() else 0.0
    if c13["ok"].any():
        mz, _, _ = centre_arm(X["X20"], c13, zero=True)
        cb["X20"] = float(np.max(np.abs(d_of(c13, "13", mu=mz))))
    sz, _, _, _ = w1_arm(Z, c07, zero=True)
    cb["W1"] = float(np.max(np.abs(d_of(c07, "07", sig=sz))))
    controls["C_b_identity"] = {"max_abs_diff": cb, "pass": all(v == 0.0 for v in cb.values())}

    rng = np.random.default_rng(PLANT_SEED)
    ok07 = c07["ok"]
    resid_ref = {y: c07["dmax"] - mu_ref07[y] for y in years}
    pooled = np.concatenate([resid_ref[y][ok07 & (c07["year"] != y)] for y in years])
    eps = rng.normal(0.0, float(np.std(pooled)), len(rows))
    plant = {y: (0.5 * resid_ref[y] + eps)[:, None] for y in years}
    mu_p, par_p, _ = centre_arm(plant, c07)
    mu_n, par_n, _ = centre_arm({y: -plant[y] for y in years}, c07)
    d_p, d_n = d_of(c07, "07", mu=mu_p), d_of(c07, "07", mu=mu_n)
    st_p = bootstrap(d_p, c07["dates"][ok07])
    opposite = all(np.all(np.sign(par_n[y][h][0]) == -np.sign(par_p[y][h][0])) and np.all(par_p[y][h][0] != 0)
                   for y in years for h in par_p[y])
    cc_centre = {"label": "CONTROL", "plus": {"stats": st_p, "betas": betas(par_p), "pass": control_pass(st_p)},
                 "minus": {"betas": betas(par_n), "beta_opposite_all_folds": bool(opposite),
                           "max_abs_d_diff": float(np.max(np.abs(d_n - d_p)))}}
    cc_centre["minus"]["pass"] = bool(opposite and cc_centre["minus"]["max_abs_d_diff"] <= NEG_IDENTICAL_TOL)
    cc_centre["pass"] = bool(cc_centre["plus"]["pass"] and cc_centre["minus"]["pass"])
    z_clean = np.concatenate([Z[y][ok07 & (c07["year"] != y)] for y in years])
    eps_z = rng.normal(0.0, float(np.std(z_clean)), len(rows))
    zp = {y: np.log(np.maximum(np.abs(resid_ref[y]), Z_FLOOR)) + eps_z for y in years}
    s_p, gp, _, zc_p = w1_arm(zp, c07)
    s_n, gn, _, _ = w1_arm({y: -zp[y] for y in years}, c07)
    p0_p = w1_p0(zc_p, c07)
    st_wp = bootstrap(d_of(c07, "07", sig=s_p), c07["dates"][ok07])
    st_wn = bootstrap(d_of(c07, "07", sig=s_n), c07["dates"][ok07])
    zero_folds = {h: sum(1 for y in years if gn[y]["gamma"].get(h, 0.0) == 0.0) for h in gn[years[0]]["gamma"]}
    cc_w1 = {"label": "CONTROL", "plus": {"p0": p0_p, "stats": st_wp, "gamma": {str(y): gp[y] for y in years},
                                          "pass": bool(p0_p["pass"] and control_pass(st_wp))},
             "minus": {"stats": st_wn, "gamma": {str(y): gn[y] for y in years}, "gamma_zero_folds": zero_folds,
                       "pass": bool(all(v >= W1_NEG_MIN_ZERO_FOLDS for v in zero_folds.values())
                                    and st_wn["ci95"][1] >= 0)}}
    cc_w1["pass"] = bool(cc_w1["plus"]["pass"] and cc_w1["minus"]["pass"])
    controls["C_c_planted"] = {"label": "CONTROL", "noise": "sd(eps) = sd of the pooled clean fit-row signal",
                               "centre": cc_centre, "W1": cc_w1,
                               "pass": bool(cc_centre["pass"] and cc_w1["pass"])}

    def void(reason):
        payload = {"verdict": "VOID", "reason": reason, "controls": controls, "rule_sha256": RULE_SHA256,
                   "module_sha256": _sha(__file__)}
        _write(out_dir, "octdec_loyo_batch_void.json", payload)
        raise OctDecBatchError(f"VOID: {reason}")

    if not (ca["pass"] and controls["C_b_identity"]["pass"] and controls["C_c_planted"]["pass"]):
        void("a control (C-a, C-b or C-c) failed")

    # ---- the four arms, each with J = 20 calibration-matched placebos
    srcs07 = [placebo_src(c07["markets"], c07["hour"], c07["year"], c07["dates"], PLACEBO_SEED0 + j)
              for j in range(PLACEBO_J)]
    srcs13 = [placebo_src(c13["markets"], c13["hour"], c13["year"], c13["dates"], PLACEBO_SEED0 + j)
              for j in range(PLACEBO_J)] if len(late) else []
    arms, train_checks, pvals = {}, {}, {}
    for arm in ARMS:
        c, key, srcs = (c13, "13", srcs13) if arm == "X20" else (c07, "07", srcs07)
        rec = {"testable": testable[arm], "coverage": cov[arm][0]}
        if not testable[arm] or not c["ok"].any():
            rec["status"] = "UNTESTABLE"
            pvals[arm] = 1.0
            arms[arm] = rec
            continue
        if arm == "W1":
            s_a, par, tr, zc = w1_arm(Z, c)
            rec["p0"] = w1_p0(zc, c)
            rec["params"] = {str(y): par[y] for y in years}
            d = d_of(c, key, sig=s_a)
            pl = [d_of(c, key, sig=w1_arm({y: Z[y][src] for y in years}, c)[0]) for src in srcs]
        else:
            mu_a, par, tr = centre_arm(X[arm], c)
            rec["betas"] = betas(par)
            d = d_of(c, key, mu=mu_a)
            pl = [d_of(c, key, mu=centre_arm({y: X[arm][y][src] for y in years}, c)[0]) for src in srcs]
        train_checks[arm] = tr
        rec["stats"] = bootstrap(d, c["dates"][c["ok"]], placebos=pl)
        full_d = np.full(len(c["ok"]), np.nan)
        full_d[c["ok"]] = d
        if np.any(d != 0):
            rec["cells"] = pmo.gate(c["frame"], full_d, c["ok"])
        else:  # the lever was fitted to 0 on every row; the daily statistics in gate() are undefined
            rec["cells"] = {"ci_worse_cells": [], "skipped": "d identically 0"}
        closed = arm == "W1" and not rec["p0"]["pass"]
        rec["status"] = "CLOSED_AT_P0" if closed else "TESTED"
        pvals[arm] = 1.0 if closed else rec["stats"]["p_one_sided"]
        arms[arm] = rec
    controls["C_d_training_score"] = {"by_arm": train_checks,
                                      "pass": all(f["pass"] for t in train_checks.values() for f in t.values())}
    if not controls["C_d_training_score"]["pass"]:
        void("C-d training score failed")
    bh = bh_reject(pvals)
    for arm in ARMS:
        rec = arms[arm]
        rec["p"], rec["bh_q"], rec["bh_reject"] = pvals[arm], bh[arm][0], bh[arm][1]
        if rec["status"] == "UNTESTABLE":
            rec["verdict"] = "UNTESTABLE"
            continue
        st = rec["stats"]
        rec["checks"] = {"p0": rec["status"] != "CLOSED_AT_P0", "bh_reject": bh[arm][1],
                         "delta_upper_lt_0": st["ci95"][1] < 0, "d_net_upper_lt_0": st["d_net"]["ci95"][1] < 0,
                         "no_worse_cells": not rec["cells"]["ci_worse_cells"]}
        rec["verdict"] = VERDICT_SCREEN if all(rec["checks"].values()) else VERDICT_KILL
    payload = {"label": "ledger row 95: Oct-Dec LOYO batch W1/X13/X18/X20 on SM-L6, history only",
               "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__),
               "verdicts": {a: arms[a]["verdict"] for a in ARMS}, "arms": arms, "controls": controls,
               "bh": {"q": BH_Q, "K": K}, "s1": s1["arms"], "rows_scored_07_12": int(c07["ok"].sum()),
               "rows_scored_13_14": int(c13["ok"].sum()), "train_rows": int(len(train)),
               "inputs": dict(prov, nbm_corpus_sha256=sm.NBM_CORPUS_SHA256, coef_sha256=cs.MG2_COEF_SHA256,
                              c1_receipt_sha256=pmo.C1_RECEIPT_SHA256, rg_obs_sha256=prm.RG_OBS_SHA256)}
    _write(out_dir, "octdec_loyo_batch.json", payload)
    return payload


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m weather.calibration.octdec_loyo_batch")
    for flag in ("--research-root", "--nbm-corpus", "--mg2-coefficients", "--rule", "--c1-receipt", "--out"):
        p.add_argument(flag, required=True)
    a = p.parse_args(argv)
    out = run(research_root=a.research_root, nbm_corpus=a.nbm_corpus, mg2_coefficients=a.mg2_coefficients,
              rule=a.rule, c1_receipt=a.c1_receipt, out=a.out)
    print(json.dumps({"verdicts": out["verdicts"], "controls_pass": {k: v.get("pass") for k, v in
                                                                     out["controls"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
