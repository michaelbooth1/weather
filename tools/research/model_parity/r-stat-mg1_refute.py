"""R-STAT-MG1: statistics refuter for MG-1 (r-t5-inc-c1 / ladder r2 over r1) and t3-r3 at 13-16 (+ POST-HOC 15-16).

Diagnostics registered before scoring: r-stat-mg1-d1, -d2, -d3 (C:\\swarm\\registry.jsonl). Development only.
Independent of harness.score(): own MG-1 re-implementation, own floor mask, own Brier, own cell aggregation;
the harness is used only to load the hash-verified cache (labels, W, keys).
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-stat-mg1_refute.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import ndtr

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402

if Path(r"C:\swarm\STOP").exists():
    sys.exit("STOP present")
OUT = Path(r"C:\swarm\out\r-stat-mg1")
LAD = Path(r"C:\swarm\out\ladder")
FROM, BEFORE = "from_20260823", "before_20260823"
RNG_SEED = 20261004
NDRAW = 2000

d = h.data()
S = d.snaps
B = d.bands
assert S.date.max() <= "2026-09-29" and B.date.max() <= "2026-09-29"
n_after = int((S.date > "2026-09-29").sum())
nb = S.n_bands.to_numpy()
offs = d.offsets
y = B.is_winner.to_numpy(float)
kind = B.kind.to_numpy()
low = B.low.to_numpy(float)
high = B.high.to_numpy(float)
p_served = B.p_served.to_numpy(float)
p_market = B.p_market_yes.to_numpy(float)
bsnap = d.band_snap


def snap_mean(v):
    return np.add.reduceat(v, offs) / nb


# ---------------------------------------------------------------- own floor mask (81a): non-gte band with high < bucket
floor = S.floor.to_numpy(float)
has_floor = np.isfinite(floor)
bucket = np.where(has_floor, np.floor(np.where(has_floor, floor, 0) + .5), np.nan)
imposs = (kind != "gte") & (high < bucket[bsnap])
assert (imposs == d.impossible).all(), "own floor mask disagrees with cache floor_impossible"


def apply_floor(p, covered_snap):
    """covered_snap: snapshot bool. Returns band probs with floor+renorm on covered, served elsewhere."""
    p = np.where(np.isnan(p), 0.0, p)
    p = np.where(imposs, 0.0, p)
    tot = np.bincount(bsnap, weights=p, minlength=len(S))
    use = covered_snap & has_floor & (tot > 0)
    scale = np.where(use & (np.abs(tot - 1) > 1e-12), tot, 1.0)
    return np.where(use[bsnap], p / scale[bsnap], p_served), use


served_b = snap_mean((p_served - y) ** 2)
market_b = snap_mean((p_market - y) ** 2)

# ---------------------------------------------------------------- MG-1 from registry text
cap = pd.to_datetime(S.captured_at_utc, utc=True, format="ISO8601")
v2av = pd.to_datetime(S.v2_available_at, utc=True, format="ISO8601", errors="coerce")
v2iss = pd.to_datetime(S.v2_issued_at, utc=True, format="ISO8601", errors="coerce")
mu = S.v2_mean.to_numpy(float)
sd = S.v2_stddev.to_numpy(float)
ok = (np.isfinite(mu) & np.isfinite(sd) & v2av.notna().to_numpy() & (v2av <= cap).fillna(False).to_numpy()
      & has_floor)
mu_b, sig_b, B_b = mu[bsnap], np.maximum(sd, 1.0)[bsnap], bucket[bsnap]
okb = ok[bsnap]
with np.errstate(invalid="ignore"):
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B_b), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B_b)
    pm = np.where(possible, ndtr((up - mu_b) / sig_b) - ndtr((lo - mu_b) / sig_b), 0.0)
pm = np.where(okb, np.clip(pm, 0, None), np.nan)
p_mg1, use_mg1 = apply_floor(pm, ok)
mg1_b = snap_mean((p_mg1 - y) ** 2)

lad = {k: np.load(LAD / f"snapb_{k}.npy") for k in ("served", "ladder-r1", "ladder-r2", "mg1-c1-alone")}
repro = {"mg1_vs_ladder_mg1_c1_alone_maxabs": float(np.max(np.abs(mg1_b - lad["mg1-c1-alone"]))),
         "served_vs_ladder_served_maxabs": float(np.max(np.abs(served_b - lad["served"]))),
         "mg1_coverage_snapshots": int(use_mg1.sum()), "mg1_coverage_share": float(use_mg1.mean())}
print("repro", repro, flush=True)
r1_b, r2_b = lad["ladder-r1"], lad["ladder-r2"]

# ---------------------------------------------------------------- t3-r3 from refute-stat-t3 frame
c3 = pd.read_parquet(r"C:\swarm\out\refute-stat-t3\cand_r3.parquet")
pos = d.snap_pos.reindex(c3.row_key.to_numpy()).to_numpy().astype(int)
p3 = np.full(len(B), np.nan)
p3[offs[pos] + c3.band_index.to_numpy(int)] = c3.p.to_numpy(float)
cov3 = np.bincount(bsnap, weights=~np.isnan(p3), minlength=len(S)) == nb
p_t3, use_t3 = apply_floor(p3, cov3)
t3_b = snap_mean((p_t3 - y) ** 2)

# ---------------------------------------------------------------- cells / bootstraps
LH = S.local_hour.to_numpy()
STR = S.stratum.to_numpy()
G = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-14": (13, 14), "15-16": (15, 16),
     "13-16": (13, 16), "17-23": (17, 23), "00-16": (0, 16), "all": (0, 23)}
W = d.w
dates_all = sorted(S.date.unique())
markets_all = sorted(S.market.unique())
rng = np.random.default_rng(RNG_SEED)
DATE_DRAWS = rng.multinomial(len(dates_all), [1 / len(dates_all)] * len(dates_all), size=NDRAW)
MKT_DRAWS = rng.multinomial(len(markets_all), [1 / len(markets_all)] * len(markets_all), size=NDRAW)
dpos = {x: i for i, x in enumerate(dates_all)}
mpos = {x: i for i, x in enumerate(markets_all)}
week = pd.to_datetime(pd.Series(dates_all)).dt.isocalendar().week.to_numpy()
wk_of = dict(zip(dates_all, week))


def cells(group, stratum, cols, mask=None):
    lo_, hi_ = G[group]
    m = (LH >= lo_) & (LH <= hi_)
    if stratum != "pooled":
        m &= STR == stratum
    if mask is not None:
        m &= mask
    f = pd.DataFrame({"date": S.date.to_numpy()[m], "market": S.market.to_numpy()[m],
                      **{k: v[m] for k, v in cols.items()}})
    return f.groupby(["date", "market"], sort=True).mean().reset_index()


def boot_q(boot):
    return [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))]


def battery(a, b, group, stratum=FROM, mask=None, full=True):
    c = cells(group, stratum, {"a": a, "b": b, "s": served_b, "m": market_b}, mask)
    dl = (c.a - c.b).to_numpy()
    est = float(dl.mean())
    idx = np.array([d.key_index[(x, z)] for x, z in zip(c.date, c.market)])
    wb = W[:, idx]
    bw = (wb @ dl) / wb.sum(1)
    out = {"estimate": est, "n_cells": int(len(c)), "W_ci95": boot_q(bw), "W_sd": float(bw.std(ddof=1))}
    gap = float((c.s - c.m).mean())
    out["served_minus_market"] = gap
    out["gap_closed_share"] = -est / gap if gap else None
    pmk = c.assign(dl=dl).groupby("market").dl.mean()
    out["markets_negative"] = int((pmk < 0).sum())
    out["markets_n"] = int(len(pmk))
    out["per_market"] = {k: round(float(v), 6) for k, v in pmk.items()}
    if not full:
        return out
    di = np.array([dpos[x] for x in c.date])
    mi = np.array([mpos[x] for x in c.market])
    wd = DATE_DRAWS[:, di].astype(float)
    wm = MKT_DRAWS[:, mi].astype(float)
    bd = (wd @ dl) / np.where(wd.sum(1) > 0, wd.sum(1), np.nan)
    bm = (wm @ dl) / np.where(wm.sum(1) > 0, wm.sum(1), np.nan)
    out["date_only_ci95"] = boot_q(bd[np.isfinite(bd)])
    out["market_only_ci95"] = boot_q(bm[np.isfinite(bm)])
    lomo = {}
    for mk in sorted(set(c.market)):
        keep = (c.market != mk).to_numpy()
        wb2 = W[:, idx[keep]]
        b2 = (wb2 @ dl[keep]) / wb2.sum(1)
        lomo[mk] = {"estimate": float(dl[keep].mean()), "W_ci95": boot_q(b2)}
    out["lomo"] = lomo
    out["lomo_range"] = [min(v["estimate"] for v in lomo.values()), max(v["estimate"] for v in lomo.values())]
    out["lomo_ci_includes_0"] = sorted(k for k, v in lomo.items() if v["W_ci95"][1] >= 0)
    lowo = {}
    wks = np.array([wk_of[x] for x in c.date])
    for wk in sorted(set(wks)):
        keep = wks != wk
        wb2 = W[:, idx[keep]]
        b2 = (wb2 @ dl[keep]) / wb2.sum(1)
        lowo[int(wk)] = {"estimate": float(dl[keep].mean()), "W_ci95": boot_q(b2), "dropped_cells": int((~keep).sum())}
    out["lowo"] = lowo
    out["lowo_range"] = [min(v["estimate"] for v in lowo.values()), max(v["estimate"] for v in lowo.values())]
    out["lowo_ci_includes_0"] = sorted(k for k, v in lowo.items() if v["W_ci95"][1] >= 0)
    t = stats.ttest_1samp(pmk.to_numpy(), 0.0)
    out["market_t"] = {"t": float(t.statistic), "p_two_sided": float(t.pvalue), "df": int(len(pmk) - 1)}
    # one-week / one-market dominance: share of the effect carried by the single largest contributor
    out["max_single_market_share"] = float((pmk.min() * len(pmk)) / (pmk.sum())) if pmk.sum() < 0 else None
    out["z_W"] = est / out["W_sd"]
    return out


def strata(a, b, group, mask=None):
    return {st: battery(a, b, group, st, mask, full=False)["estimate"] for st in (BEFORE, FROM, "pooled")}


# multiplicity
reg_lines = sum(1 for _ in open(r"C:\swarm\registry.jsonl", encoding="utf-8"))
M_SYN = 134 * 7
M_NOW = reg_lines * 7
z_bonf = {"134x7": float(stats.norm.isf(0.025 / M_SYN)), f"{reg_lines}x7": float(stats.norm.isf(0.025 / M_NOW)),
          "two_sided_134x7": float(stats.norm.isf(0.05 / 2 / M_SYN))}


def mult(bt, k_family=1):
    z = bt["z_W"]
    p1 = float(stats.norm.cdf(z))  # one-sided p for "candidate better"
    return {"z": z, "p_one_sided_normal": p1, "bonferroni_134x7_pass": p1 < 0.025 / M_SYN,
            f"bonferroni_{reg_lines}x7_pass": p1 < 0.025 / M_NOW,
            "holm_best_case_rank_note": "Holm's first step equals Bonferroni; a test passes Holm only if it passes at "
                                        "alpha/(m-k+1) after k-1 smaller p-values, so with m=938 Holm differs from "
                                        "Bonferroni by < 1% of the threshold unless hundreds of tests rank ahead.",
            "holm_pass_if_all_synthesis_passers_rank_ahead": p1 < 0.025 / (M_SYN - 6),
            "within_family_holm_alpha": 0.025 / k_family, "within_family_pass": p1 < 0.025 / k_family}


res = {"agent": "r-stat-mg1", "HARNESS_SHA256": h.harness_sha256(), "development": True,
       "rows_after_0929": n_after, "reproduction": repro, "registry_lines": reg_lines, "z_bonferroni": z_bonf}

# ---------------------------------------------------------------- d1: MG-1
MG_BLOCKS = ["00-05", "06-09", "10-12", "00-16"]
CTX = ["13-14", "15-16", "13-16", "17-23", "all"]
d1 = {}
for name, a, b in (("mg1_minus_served", mg1_b, served_b), ("r2_minus_r1", r2_b, r1_b)):
    d1[name] = {}
    for g in MG_BLOCKS + CTX:
        bt = battery(a, b, g)
        bt["strata"] = strata(a, b, g)
        bt["multiplicity"] = mult(bt, k_family=len(MG_BLOCKS))
        d1[name][g] = bt
        print(name, g, round(bt["estimate"], 5), [round(x, 5) for x in bt["W_ci95"]], bt["markets_negative"],
              "date", [round(x, 5) for x in bt["date_only_ci95"]], "mkt", [round(x, 5) for x in bt["market_only_ci95"]],
              "lomo", [round(x, 5) for x in bt["lomo_range"]], bt["lomo_ci_includes_0"],
              "lowo", [round(x, 5) for x in bt["lowo_range"]], bt["lowo_ci_includes_0"],
              "z", round(bt["z_W"], 2), "t", round(bt["market_t"]["t"], 2), flush=True)
res["d1"] = d1
# ---------------------------------------------------------------- d3: t3-r3
d3 = {}
for name, a, b in (("t3r3_minus_served", t3_b, served_b), ("t3r3_minus_r2", t3_b, r2_b),
                   ("t3r3_minus_r1", t3_b, r1_b)):
    d3[name] = {}
    for g in ["13-16", "13-14", "15-16", "17-23", "00-16"]:
        bt = battery(a, b, g)
        bt["strata"] = strata(a, b, g)
        bt["multiplicity"] = mult(bt, k_family=1)
        bt["post_hoc_slice"] = g in ("13-14", "15-16")
        d3[name][g] = bt
        print(name, g, round(bt["estimate"], 5), [round(x, 5) for x in bt["W_ci95"]], bt["markets_negative"],
              "date", [round(x, 5) for x in bt["date_only_ci95"]], "mkt", [round(x, 5) for x in bt["market_only_ci95"]],
              "lomo", [round(x, 5) for x in bt["lomo_range"]], bt["lomo_ci_includes_0"],
              "lowo", [round(x, 5) for x in bt["lowo_range"]], bt["lowo_ci_includes_0"],
              "z", round(bt["z_W"], 2), flush=True)
res["d3"] = d3
# r2 at 15-16 and 13-16 vs market (to check SYNTHESIS residual claim)
res["r2_minus_market"] = {g: battery(r2_b, market_b, g, full=False) for g in ["13-16", "15-16", "00-16"]}
res["mg1_minus_r1_1516"] = battery(r2_b, r1_b, "15-16", full=False)

# ---------------------------------------------------------------- d2: availability / staleness vs outcome
age_iss = ((cap - v2iss).dt.total_seconds() / 3600).to_numpy()
age_av = ((cap - v2av).dt.total_seconds() / 3600).to_numpy()
validd = pd.to_datetime(S.v2_valid_time_utc, utc=True, errors="coerce")
sh = S.settlement_high.to_numpy(float)
abs_err = np.abs(sh - mu)
excess = served_b - market_b
delta = mg1_b - served_b
d2 = {"fallback_reasons": {}, "by_block": {}}
nofl = ~has_floor
d2["fallback_reasons"] = {"no_floor": int(nofl.sum()), "v2_missing": int((~np.isfinite(mu)).sum()),
                          "v2_after_capture": int(((v2av > cap).fillna(False)).sum()),
                          "covered": int(use_mg1.sum())}
for g in MG_BLOCKS + ["13-16", "15-16", "17-23"]:
    lo_, hi_ = G[g]
    m = (LH >= lo_) & (LH <= hi_) & (STR == FROM)
    mm = m & use_mg1
    q = lambda v: [round(float(x), 2) for x in np.nanquantile(v, [.1, .5, .9])]
    blk = {"snapshots": int(m.sum()), "coverage": float(use_mg1[m].mean()),
           "age_since_issue_h_q10_50_90": q(age_iss[mm]), "age_since_available_h_q10_50_90": q(age_av[mm])}
    # valid-time date relative to target date (indexing check)
    vd = (validd[mm].dt.tz_convert("UTC").dt.normalize() - pd.to_datetime(S.date[mm]).dt.tz_localize("UTC")).dt.days
    blk["valid_time_utc_date_minus_target_days"] = {int(k): int(v) for k, v in vd.value_counts().items()}
    # association: staleness vs served excess, vs MG-1 delta, vs |settle - v2_mean|
    blk["spearman_age_vs_served_excess"] = float(stats.spearmanr(age_iss[mm], excess[mm]).statistic)
    blk["spearman_age_vs_mg1_delta"] = float(stats.spearmanr(age_iss[mm], delta[mm]).statistic)
    blk["spearman_age_vs_abs_err"] = float(stats.spearmanr(age_iss[mm], abs_err[mm]).statistic)
    terc = pd.qcut(pd.Series(age_iss[mm]).rank(method="first"), 3, labels=["fresh", "mid", "stale"]).to_numpy()
    tt = {}
    for lab in ("fresh", "mid", "stale"):
        sel = np.zeros(len(S), bool)
        sel[np.flatnonzero(mm)[terc == lab]] = True
        bt = battery(mg1_b, served_b, g, FROM, sel, full=False)
        tt[lab] = {"age_h_median": float(np.median(age_iss[sel])), "mg1_minus_served": bt["estimate"],
                   "W_ci95": bt["W_ci95"], "markets_negative": bt["markets_negative"],
                   "served_minus_market": bt["served_minus_market"],
                   "abs_err_v2_mean": float(np.nanmean(abs_err[sel]))}
    blk["by_staleness_tercile"] = tt
    # cell level: fallback share vs served excess
    c = cells(g, FROM, {"fb": (~use_mg1).astype(float), "ex": excess, "dl": delta})
    blk["cell_spearman_fallback_vs_excess"] = (float(stats.spearmanr(c.fb, c.ex).statistic)
                                               if c.fb.nunique() > 1 else None)
    blk["cell_spearman_fallback_vs_delta"] = (float(stats.spearmanr(c.fb, c.dl).statistic)
                                              if c.fb.nunique() > 1 else None)
    blk["cells_with_any_fallback"] = int((c.fb > 0).sum())
    d2["by_block"][g] = blk
    print("d2", g, json.dumps({k: v for k, v in blk.items() if k != "by_staleness_tercile"})[:400], flush=True)
    print("   terciles", {k: (round(v["age_h_median"], 1), round(v["mg1_minus_served"], 4), v["markets_negative"])
                          for k, v in tt.items()}, flush=True)
# fallback vs outcome at snapshot level, all hours from stratum
fm = STR == FROM
d2["fallback_snapshot_served_excess_mean"] = {"fallback": float(excess[fm & ~use_mg1].mean()),
                                              "covered": float(excess[fm & use_mg1].mean()),
                                              "n_fallback": int((fm & ~use_mg1).sum())}
res["d2"] = d2


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


(OUT / "stats.json").write_text(json.dumps(clean(res), indent=1), encoding="utf-8")
print("done", flush=True)
