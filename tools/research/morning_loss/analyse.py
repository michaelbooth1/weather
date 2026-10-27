"""L5 morning-loss diagnosis: decomposition, concentration, regimes, timing (pre-declared plan C:\\t\\l5\\plan.md).

Development research only (layout dates <= 2026-09-29, scored by the dev scorecard's default folds). Offline.
Uses the dev scorecard's Table, fold scheme and crossed bootstrap weights so every number sits on the kit's
population. Writes one JSON result and prints a compact summary.

    python tools/research/morning_loss/analyse.py --layout C:\\swarm\\v3layout \\
        --regimes C:\\t\\l5\\regimes.parquet --out C:\\t\\l5\\result.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

W_LO, W_HI = 7, 12
TOP_FRAC = 0.10
ARRIVE_TOL = 1.5
LEAD_N = 2.0
FLAGS = ("R1_frontal", "R2_cloud", "R3_precip", "R4_low_gap", "R5_revision", "R6_tendency")
PRODUCTS = ("c_served", "v2_p50", "v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high", "high_so_far",
            "c_mg1")


# ----------------------------------------------------------------------------- band geometry

class Geometry:
    def __init__(self, table):
        b = table.bands
        self.kind = b.kind.to_numpy()
        self.low = b.low.to_numpy(float)
        self.high = b.high.to_numpy(float)
        width = np.where(self.kind == "eq", self.high - self.low + 1, np.nan)
        cnt = pd.DataFrame({"s": table.band_snap, "w": width}).dropna().value_counts().reset_index()
        cnt = cnt.sort_values(["s", "count", "w"], ascending=[True, False, True]).drop_duplicates("s")
        snap_w = pd.Series(2.0, index=range(len(table.snaps)))
        snap_w[cnt.s.to_numpy()] = cnt.w.to_numpy()
        snap_w = snap_w.to_numpy()
        self.w = snap_w[table.band_snap]
        self.rep = np.where(self.kind == "eq", (self.low + self.high) / 2,
                            np.where(self.kind == "lte", self.high - (self.w - 1) / 2, self.low + (self.w - 1) / 2))
        # continuous edges for integer-degree semantics
        self.lo_edge = np.where(self.kind == "lte", -np.inf, self.low - 0.5)
        self.hi_edge = np.where(self.kind == "gte", np.inf, self.high + 0.5)
        self.t = table

    def norm(self, p):
        tot = np.add.reduceat(p, self.t.offsets)
        return p / np.where(tot > 0, tot, 1.0)[self.t.band_snap]

    def centre_sd(self, p):
        q = self.norm(p)
        c = np.add.reduceat(q * self.rep, self.t.offsets)
        v = np.add.reduceat(q * (self.rep - c[self.t.band_snap]) ** 2, self.t.offsets)
        return c, np.sqrt(np.maximum(v, 0))

    def shift(self, p, delta, snaps):
        """Translate each listed snapshot's band pmf by delta degrees; floor-mask; renormalise."""
        t = self.t
        out = p.copy()
        for s, d in zip(snaps, delta[snaps]):
            a, n = t.offsets[s], t.n[s]
            sl = slice(a, a + n)
            kind, low, high, w = self.kind[sl], self.low[sl], self.high[sl], int(self.w[a])
            q = p[sl] / max(p[sl].sum(), 1e-300)
            lo_int = np.where(kind == "lte", high - w + 1, low).astype(int)
            hi_int = np.where(kind == "gte", low + w - 1, high).astype(int)
            g0, g1 = int(lo_int.min()) - 40, int(hi_int.max()) + 40
            grid = np.zeros(g1 - g0 + 1)
            for m, l, h in zip(q, lo_int, hi_int):
                grid[l - g0:h - g0 + 1] += m / (h - l + 1)
            knots = np.concatenate([[g0 - 0.5], np.arange(g0, g1 + 1) + 0.5])
            cdf = np.concatenate([[0.0], np.cumsum(grid)])

            def F(x):
                return np.interp(np.asarray(x, float) - d, knots, cdf, left=0.0, right=1.0)

            lo_e, hi_e = self.lo_edge[sl], self.hi_edge[sl]
            new = np.where(np.isinf(hi_e), 1.0, F(np.where(np.isinf(hi_e), 0, hi_e))) - \
                np.where(np.isinf(lo_e), 0.0, F(np.where(np.isinf(lo_e), 0, lo_e)))
            new = np.maximum(new, 0)
            new[t.impossible[sl]] = 0.0
            tot = new.sum()
            out[sl] = new / tot if tot > 0 else p[sl]
        return out


def mg1_vector(table, geo):
    s = table.snaps
    mu = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = np.maximum(pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float), 1.0)
    mu_b, sd_b = mu[table.band_snap], sd[table.band_snap]
    hi = np.where(np.isinf(geo.hi_edge), 1.0, norm.cdf((np.where(np.isinf(geo.hi_edge), 0, geo.hi_edge) - mu_b) / sd_b))
    lo = np.where(np.isinf(geo.lo_edge), 0.0, norm.cdf((np.where(np.isinf(geo.lo_edge), 0, geo.lo_edge) - mu_b) / sd_b))
    p = np.maximum(hi - lo, 0)
    ok = np.isfinite(mu_b) & np.isfinite(sd_b)
    frame = pd.DataFrame({"row_key": table.bands.row_key.to_numpy()[ok],
                          "band_index": table.bands.band_index.to_numpy()[ok], "p": p[ok]})
    vec, reasons = table.candidate_vector(frame)
    return vec, reasons


# ----------------------------------------------------------------------------- bootstrap helpers

def ci(boot):
    b = np.asarray(boot, float)
    b = b[np.isfinite(b)]
    return [float(x) for x in np.quantile(b, [.025, .975])] if len(b) else [None, None]


def ci_level(boot, level):
    b = np.asarray(boot, float)
    b = b[np.isfinite(b)]
    a = (1 - level) / 2
    return [float(x) for x in np.quantile(b, [a, 1 - a])] if len(b) else [None, None]


def ratio(w, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    point = float(a.sum() / b.sum())
    den = w @ b
    boot = np.divide(w @ a, den, out=np.full(len(den), np.nan), where=den != 0)
    return {"estimate": point, "ci95": ci(boot)}


def top_mask(E, weights=None):
    """Top TOP_FRAC of (weighted) cells by E; unweighted = ceil(10%)."""
    order = np.argsort(-E, kind="stable")
    if weights is None:
        k = int(math.ceil(TOP_FRAC * len(E)))
        m = np.zeros(len(E), bool)
        m[order[:k]] = True
        return m
    cw = np.cumsum(weights[order])
    total = cw[-1]
    k = int(np.searchsorted(cw, TOP_FRAC * total) + 1)
    m = np.zeros(len(E), bool)
    m[order[:k]] = True
    return m


# ----------------------------------------------------------------------------- main analysis

def cell_mean(table, values, mask):
    idx, v = table.cells(values, mask)
    full = np.full(len(table.keys), np.nan)
    full[idx] = v
    return full


def run(layout_root, regimes_path):
    start, end = data.check_range("2026-08-01", "2026-09-29")
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    t = sc.Table(layout, scored)
    geo = Geometry(t)
    W = t.w
    hour = t.local_hour
    minute = pd.to_datetime(t.snaps.captured_at_local.str.slice(0, 19)).dt.minute.to_numpy()
    tod = hour + minute / 60.0
    inW = (hour >= W_LO) & (hour <= W_HI)
    labels = layout.labels.set_index("row_key").reindex(t.snaps.row_key)
    y_high = labels.settlement_high.to_numpy(float)

    p_s, p_m = t.p_served, t.p_market
    b_s, b_m = t.brier(p_s), t.brier(p_m)
    c_s, sd_s = geo.centre_sd(p_s)
    c_m, sd_m = geo.centre_sd(p_m)
    p_mg, mg_reasons = mg1_vector(t, geo)
    b_mg = t.brier(p_mg)
    c_mg, sd_mg = geo.centre_sd(p_mg)

    wsn = np.flatnonzero(inW)
    p_s_shift = geo.shift(p_s, c_m - c_s, wsn)
    p_m_shift = geo.shift(p_m, c_s - c_m, wsn)
    p_mg_shift = geo.shift(p_mg, c_m - c_mg, wsn)
    p_m_shift_mg = geo.shift(p_m, c_mg - c_m, wsn)
    b_s_sh, b_m_sh = t.brier(p_s_shift), t.brier(p_m_shift)
    b_mg_sh, b_m_sh_mg = t.brier(p_mg_shift), t.brier(p_m_shift_mg)

    def cm_(v, mask=inW):
        return cell_mean(t, v, mask)

    keys = t.keys
    res = {"population": {"n_dates": len(scored), "n_market_days": len(keys), "n_W_snapshots": int(inW.sum()),
                          "first_date": scored[0], "last_date": scored[-1]},
           "mg1_coverage": mg_reasons}

    # ---- Analysis 1: decomposition
    def decomposition(bm, bm_sh, bmk_sh):
        E = cm_(bm - b_m)
        cA = cm_(bm - bm_sh)           # centre part (ordering A)
        sB = cm_(bm - bmk_sh)          # shape part (ordering B)
        cB = E - sB
        sh = (cA + cB) / 2
        out = {"total_excess_mean": float(np.nanmean(E)),
               "centre_share_A": ratio(W, cA, E), "centre_share_B": ratio(W, cB, E),
               "centre_share_shapley": ratio(W, sh, E)}
        return out, E

    dec_s, E = decomposition(b_s, b_s_sh, b_m_sh)
    dec_mg, E_mg = decomposition(b_mg, b_mg_sh, b_m_sh_mg)
    ycells = cm_(y_high)
    sup = {}
    for name, c, sd in (("served", c_s, sd_s), ("market", c_m, sd_m), ("mg1", c_mg, sd_mg)):
        z2 = ((y_high - c) / np.maximum(sd, 0.25)) ** 2
        sup[name] = {"mae_centre_to_outcome": ratio(W, cm_(np.abs(c - y_high)), np.ones(len(keys))),
                     "bias_centre_minus_outcome": ratio(W, cm_(c - y_high), np.ones(len(keys))),
                     "mean_sd": ratio(W, cm_(sd), np.ones(len(keys))),
                     "mean_z2": ratio(W, cm_(z2), np.ones(len(keys)))}
    sup["sd_ratio_served_over_market"] = ratio(W, cm_(sd_s), cm_(sd_m))
    dec_s["supporting"] = sup
    # per hour
    per_hour = {}
    for h in range(W_LO, W_HI + 1):
        mh = hour == h
        Eh = cm_(b_s - b_m, mh)
        ok = np.isfinite(Eh)
        cAh = cm_(b_s - b_s_sh, mh)
        cBh = Eh - cm_(b_s - b_m_sh, mh)
        Wh = W[:, ok]
        per_hour[h] = {"n_cells": int(ok.sum()), "excess": ratio(Wh, Eh[ok], np.ones(ok.sum())),
                       "R_served_market": ratio(Wh, cm_(b_s, mh)[ok], cm_(b_m, mh)[ok]),
                       "centre_share_shapley": ratio(Wh, ((cAh + cBh) / 2)[ok], Eh[ok]),
                       "mae_served": float(np.nanmean(cm_(np.abs(c_s - y_high), mh))),
                       "mae_market": float(np.nanmean(cm_(np.abs(c_m - y_high), mh)))}
    dec_s["per_hour"] = per_hour
    markets = np.array([k[1] for k in keys])
    dates = np.array([k[0] for k in keys])
    per_market = {}
    for mk in sorted(set(markets)):
        sel = markets == mk
        Wm = W[:, sel]
        cA_ = cm_(b_s - b_s_sh)[sel]
        cB_ = E[sel] - cm_(b_s - b_m_sh)[sel]
        per_market[mk] = {"excess": ratio(Wm, E[sel], np.ones(sel.sum())),
                          "R_served_market": ratio(Wm, cm_(b_s)[sel], cm_(b_m)[sel]),
                          "centre_share_shapley": ratio(Wm, (cA_ + cB_) / 2, E[sel]),
                          "excess_mg1": ratio(Wm, E_mg[sel], np.ones(sel.sum()))}
    dec_s["per_market"] = per_market
    res["analysis1_served"] = dec_s
    res["analysis1_mg1"] = dec_mg

    # ---- regimes per cell
    reg = pd.read_parquet(regimes_path).set_index(["date", "market"])
    reg = reg.reindex(pd.MultiIndex.from_tuples(keys))
    # R5 forecast revision from layout columns (first snapshot of the day vs last <= 12:59)
    rev_parts = []
    snaps = t.snaps.assign(_cell=t.cell, _tod=tod)
    for col in ("hrrr_high", "nws_grid_high_raw", "v2_p50"):
        v = pd.to_numeric(snaps[col], errors="coerce")
        g = snaps.assign(_v=v).dropna(subset=["_v"])
        first = g.sort_values("_tod").groupby("_cell")._v.first()
        lastm = g[g.local_hour <= 12].sort_values("_tod").groupby("_cell")._v.last()
        rev_parts.append((lastm - first).reindex(range(len(keys))).to_numpy(float))
    rev = np.nanmean(np.vstack(rev_parts), axis=0)
    reg["revision"] = rev
    reg["R5_revision"] = np.abs(rev) >= 2
    flags = {f: reg[f].fillna(False).to_numpy(bool) for f in FLAGS}
    avail = {"R4_low_gap": reg.overnight_low_gap.notna().to_numpy(),
             "R6_tendency": reg.tendency_anomaly.notna().to_numpy(),
             "R5_revision": np.isfinite(rev)}

    # ---- Analysis 2 + 3 with per-draw recomputed decile
    def concentration_and_regimes(Ex, label):
        top = top_mask(Ex)
        pos = np.maximum(Ex, 0)
        out = {"k_top": int(top.sum()), "share_total": float(Ex[top].sum() / Ex.sum()),
               "share_positive": float(pos[top].sum() / pos.sum())}
        boots = {"share_total": [], "share_positive": []}
        fr_boot = {f: [] for f in FLAGS}
        for b in range(W.shape[0]):
            wb = W[b].astype(float)
            sel = wb > 0
            tb = np.zeros(len(Ex), bool)
            tb[np.flatnonzero(sel)] = top_mask(Ex[sel], wb[sel])
            boots["share_total"].append((wb * Ex)[tb].sum() / (wb * Ex).sum())
            boots["share_positive"].append((wb * pos)[tb].sum() / (wb * pos).sum())
            for f in FLAGS:
                a = avail.get(f, np.ones(len(Ex), bool))
                num = (wb * flags[f] * a)[tb].sum() / max((wb * a)[tb].sum(), 1e-12)
                den = (wb * flags[f] * a).sum() / max((wb * a).sum(), 1e-12)
                fr_boot[f].append(num / den if den > 0 else np.nan)
        out["share_total"] = {"estimate": out["share_total"], "ci95": ci(boots["share_total"])}
        out["share_positive"] = {"estimate": out["share_positive"], "ci95": ci(boots["share_positive"])}
        out["top_market_composition"] = pd.Series(markets[top]).value_counts().to_dict()
        out["top_dates_n"] = int(len(set(dates[top])))
        regs = {}
        for f in FLAGS:
            a = avail.get(f, np.ones(len(Ex), bool))
            ft, fa = flags[f][top & a].mean(), flags[f][a].mean()
            # market-stratified expected count
            base = pd.Series(flags[f][a]).groupby(markets[a]).mean()
            expected = sum(base.get(m, 0) for m in markets[top & a])
            fl_top = top & a & flags[f]
            regs[f] = {"freq_top": float(ft), "freq_all": float(fa), "FR": float(ft / fa) if fa > 0 else None,
                       "FR_ci95": ci(fr_boot[f]), "FR_ci_bonferroni": ci_level(fr_boot[f], 1 - 0.05 / len(FLAGS)),
                       "n_top_flagged": int(fl_top.sum()), "n_markets_top_flagged": int(len(set(markets[fl_top]))),
                       "observed_top_flagged": int(fl_top.sum()), "market_stratified_expected": float(expected),
                       "mean_E_flag1": float(np.nanmean(Ex[a & flags[f]])) if (a & flags[f]).any() else None,
                       "mean_E_flag0": float(np.nanmean(Ex[a & ~flags[f]])) if (a & ~flags[f]).any() else None,
                       "share_of_top_excess": float(Ex[fl_top].sum() / Ex[top].sum())}
            lo = regs[f]["FR_ci95"][0]
            sig = (lo is not None and lo > 1.0 and regs[f]["n_top_flagged"] >= 10
                   and regs[f]["n_markets_top_flagged"] >= 3)
            blo = regs[f]["FR_ci_bonferroni"][0]
            regs[f]["verdict"] = ("STRONG_SIGNAL" if sig and blo is not None and blo > 1.0 else
                                  "SIGNAL" if sig else "NO_SIGNAL")
        cont = {}
        for col in ("max_dir_change", "max_dew_drop", "low_ceiling_frac", "overnight_low_gap", "revision",
                    "tendency_anomaly", "fc_low_cloud_06_12", "fc_precip_00_15"):
            v = reg[col].to_numpy(float)
            okv = np.isfinite(v)
            cont[col] = {"mean_top": float(np.nanmean(v[top])), "mean_all": float(np.nanmean(v)),
                         "mean_abs_top": float(np.nanmean(np.abs(v[top]))), "mean_abs_all": float(np.nanmean(np.abs(v))),
                         "n": int(okv.sum())}
        out["regimes"] = regs
        out["continuous"] = cont
        return out, top

    conc, top = concentration_and_regimes(E, "served")
    conc_mg, top_mg = concentration_and_regimes(E_mg, "mg1")

    # list of top-decile market-days
    cs_cell, cm_cell, cmg_cell = cm_(c_s), cm_(c_m), cm_(c_mg)
    listing = []
    for i in np.flatnonzero(top)[np.argsort(-E[top])]:
        listing.append({"date": dates[i], "market": markets[i], "E": float(E[i]), "E_mg1": float(E_mg[i]),
                        "y": float(ycells[i]), "c_served_W": float(cs_cell[i]), "c_market_W": float(cm_cell[i]),
                        "c_mg1_W": float(cmg_cell[i]), "revision": float(rev[i]) if np.isfinite(rev[i]) else None,
                        **{f: bool(flags[f][i]) for f in FLAGS},
                        "overnight_low_gap": _f(reg.overnight_low_gap.iloc[i]),
                        "tendency_anomaly": _f(reg.tendency_anomaly.iloc[i]),
                        "low_ceiling_frac": _f(reg.low_ceiling_frac.iloc[i])})
    conc["top_list"] = listing
    res["analysis2_3_served"] = conc
    res["analysis2_3_mg1"] = conc_mg
    res["overlap_top_served_mg1"] = int((top & top_mg).sum())

    # ---- Analysis 4: timing
    t16 = hour <= 16
    snap_df = pd.DataFrame({"cell": t.cell, "tod": tod, "cs": c_s, "cm": c_m, "y": y_high})[t16]
    snap_df = snap_df.sort_values(["cell", "tod"])

    def arrival(g, col):
        ok = (np.abs(g[col].to_numpy() - g.y.to_numpy()) <= ARRIVE_TOL)[::-1]
        good_suffix = np.logical_and.accumulate(ok)[::-1]
        if not good_suffix[-1]:
            return 17.0
        first = np.argmax(good_suffix)
        return float(g.tod.to_numpy()[first])

    arr = snap_df.groupby("cell").apply(lambda g: pd.Series({"A_s": arrival(g, "cs"), "A_m": arrival(g, "cm")}))
    arr = arr.reindex(range(len(keys)))
    lead = (arr.A_s - arr.A_m).to_numpy(float)
    lead_boot_top, lead_boot_all = [], []
    for b in range(W.shape[0]):
        wb = W[b].astype(float)
        sel = wb > 0
        tb = np.zeros(len(E), bool)
        tb[np.flatnonzero(sel)] = top_mask(E[sel], wb[sel])
        lead_boot_top.append((wb * lead)[tb].sum() / wb[tb].sum())
        lead_boot_all.append((wb * lead).sum() / wb.sum())
    timing = {"tolerance_F": ARRIVE_TOL, "N_hours": LEAD_N,
              "top": {"mean_lead_h": float(lead[top].mean()), "ci95": ci(lead_boot_top),
                      "median_lead_h": float(np.median(lead[top])),
                      "mean_A_served": float(arr.A_s[top].mean()), "mean_A_market": float(arr.A_m[top].mean()),
                      "frac_market_first": float((lead[top] > 0).mean()),
                      "frac_served_never_by_17": float((arr.A_s[top] >= 17).mean()),
                      "frac_market_never_by_17": float((arr.A_m[top] >= 17).mean())},
              "all": {"mean_lead_h": float(lead.mean()), "ci95": ci(lead_boot_all),
                      "median_lead_h": float(np.median(lead)),
                      "mean_A_served": float(arr.A_s.mean()), "mean_A_market": float(arr.A_m.mean()),
                      "frac_market_first": float((lead > 0).mean())}}
    lo = timing["top"]["ci95"][0]
    timing["verdict"] = ("SIGNAL" if timing["top"]["mean_lead_h"] >= LEAD_N and lo is not None and lo > 0
                         else "NO_SIGNAL")
    # hourly curves and catch-up
    snap_df["h"] = np.floor(snap_df.tod).astype(int)
    hm = snap_df.groupby(["cell", "h"])[["cs", "cm", "y"]].mean().reset_index()
    curves = {}
    for name, msk in (("top", top), ("all", np.ones(len(E), bool))):
        sub = hm[hm.cell.isin(np.flatnonzero(msk))]
        g = sub.assign(es=(sub.cs - sub.y).abs(), em=(sub.cm - sub.y).abs(),
                       gap=(sub.cm - sub.cs)).groupby("h")[["es", "em", "gap"]].mean()
        curves[name] = {int(h): {"mae_served": float(r.es), "mae_market": float(r.em),
                                 "mean_market_minus_served": float(r.gap)} for h, r in g.iterrows()}
    piv_s = hm.pivot(index="cell", columns="h", values="cs")
    piv_m = hm.pivot(index="cell", columns="h", values="cm")
    catch = {}
    for name, msk in (("top", top), ("all", np.ones(len(E), bool))):
        cells_ = [c for c in np.flatnonzero(msk) if c in piv_s.index]
        S, M = piv_s.loc[cells_], piv_m.loc[cells_]
        catch[name] = {}
        for k in range(0, 7):
            g_s, d_s, g_m, d_m = [], [], [], []
            for h in range(W_LO, W_HI + 1):
                h2 = h + 1 + k
                if h2 > 16 or h not in S or h2 not in S:
                    continue
                gap = (M[h] - S[h]).to_numpy()
                ds = (S[h2] - S[h]).to_numpy()
                dm = (M[h2] - M[h]).to_numpy()
                ok = np.isfinite(gap) & np.isfinite(ds) & np.isfinite(dm)
                g_s += list(gap[ok]); d_s += list(ds[ok]); d_m += list(dm[ok])
            g_s, d_s, d_m = map(np.asarray, (g_s, d_s, d_m))
            catch[name][k] = {"served_catchup_to_market": float((g_s * d_s).sum() / (g_s ** 2).sum()),
                              "market_catchup_to_served": float((-g_s * d_m).sum() / (g_s ** 2).sum()),
                              "n": int(len(g_s))}
    timing["hourly_curves"] = curves
    timing["catchup"] = catch
    res["analysis4_timing"] = timing

    # ---- Analysis 5: what the market centre tracks (W snapshots)
    prod = {"c_served": c_s, "c_mg1": c_mg}
    for col in ("v2_p50", "v2_mean", "nws_grid_high_raw", "hrrr_high", "forecast_high", "high_so_far"):
        prod[col] = pd.to_numeric(t.snaps[col], errors="coerce").to_numpy(float)
    tracks = {}
    for name, msk in (("all", np.ones(len(E), bool)), ("top", top)):
        tracks[name] = {}
        for pn in PRODUCTS:
            v = prod[pn]
            ok = inW & np.isfinite(v)
            to_m = cell_mean(t, np.abs(v - c_m), ok)
            to_y = cell_mean(t, np.abs(v - y_high), ok)
            bias = cell_mean(t, v - y_high, ok)
            sel = msk & np.isfinite(to_m)
            tracks[name][pn] = {"mae_to_market_centre": float(to_m[sel].mean()), "mae_to_outcome": float(to_y[sel].mean()),
                                "bias_to_outcome": float(bias[sel].mean()), "n_cells": int(sel.sum())}
        mm = cm_(np.abs(c_m - y_high))
        tracks[name]["market_centre"] = {"mae_to_outcome": float(mm[msk].mean()),
                                         "bias_to_outcome": float(cm_(c_m - y_high)[msk].mean())}
    # residual market-minus-served centre on top days by flag
    gapc = cm_cell - cs_cell
    resid = {f: {"top_flag1_mean_gap": float(np.nanmean(gapc[top & flags[f]])) if (top & flags[f]).any() else None,
                 "top_flag0_mean_gap": float(np.nanmean(gapc[top & ~flags[f]])) if (top & ~flags[f]).any() else None}
             for f in FLAGS}
    res["analysis5_tracking"] = {"products": tracks, "market_minus_served_gap_by_flag_top": resid,
                                 "signed_gap_top_mean": float(np.nanmean(gapc[top])),
                                 "abs_gap_top_mean": float(np.nanmean(np.abs(gapc[top]))),
                                 "abs_gap_all_mean": float(np.nanmean(np.abs(gapc)))}
    return res


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--layout", required=True)
    p.add_argument("--regimes", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    res = run(a.layout, a.regimes)
    res["plan_sha256"] = hashlib.sha256(Path(r"C:\t\l5\plan.md").read_bytes()).hexdigest()
    body = sc.canonical_bytes(res)
    Path(a.out).write_bytes(body)
    print(hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    main()
