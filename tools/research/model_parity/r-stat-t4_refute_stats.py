"""r-stat-t4: statistics refuter for the T4 obs-trend nowcast (model-parity swarm v2, development only).

Independent scoring. This script reads C:\\swarm\\cache (snapshots.parquet, bands.parquet, W.npy, W_keys.json)
directly and never calls harness.score / harness.interval / harness._candidate_vector. The hunter's module
(t4_obs_trend_nowcast) is imported only to regenerate the candidate frames under test (its feature code is
the object being refuted, not the scoring). The rule-4 floor mask, renormalisation, served fallback, cell
means, W intervals, LEAD classification, per-market / per-week / leave-one-out, multiplicity and
availability-vs-outcome checks are all re-implemented here.

Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-stat-t4_refute_stats.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import t4_obs_trend_nowcast as t4  # noqa: E402  (candidate code only)

STOP = Path(r"C:\swarm\STOP")
CACHE = Path(r"C:\swarm\cache")
OUT = Path(r"C:\swarm\out\refute-stat-t4")
REG = Path(r"C:\swarm\registry.jsonl")
LEAD_LINE, GAP_SHARE, MIN_MKTS = -0.0133, 0.05, 8
BLOCKS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}
STRATA = ("before_20260823", "from_20260823")
W_REPORTED = 0.8


def check_stop():
    if STOP.exists():
        sys.exit("STOP present")


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ raw cache, independent of the harness
check_stop()
OUT.mkdir(parents=True, exist_ok=True)
snaps = pd.read_parquet(CACHE / "snapshots.parquet")
bands = pd.read_parquet(CACHE / "bands.parquet")
W = np.load(CACHE / "W.npy")
keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text(encoding="utf-8"))]
kidx = {k: i for i, k in enumerate(keys)}
assert W.shape == (2000, 626) and len(keys) == 626
assert snaps.date.max() <= "2026-09-29" and bands.date.max() <= "2026-09-29"
n_after = int((snaps.date > "2026-09-29").sum())
assert n_after == 0
N = len(snaps)
n_bands = snaps.n_bands.to_numpy()
offsets = np.concatenate([[0], np.cumsum(n_bands)[:-1]])
assert (bands.row_key.to_numpy()[offsets] == snaps.row_key.to_numpy()).all()
band_snap = np.repeat(np.arange(N), n_bands)
snap_pos = pd.Series(np.arange(N), index=snaps.row_key)
y = bands.is_winner.to_numpy(float)
p_served = bands.p_served.to_numpy(float)
p_market = bands.p_market_yes.to_numpy(float)
se_s = (p_served - y) ** 2
se_m = (p_market - y) ** 2
tail = (se_s > se_m) & (np.abs(p_served - p_market) >= 0.30)

# rule-4 floor, re-derived from the captured features
fl = snaps[["guidance_physical_floor", "high_so_far", "trusted_current_max"]].astype(float).max(axis=1)
has_floor = fl.notna().to_numpy()
bucket = np.floor(fl.to_numpy(float) + 0.5)
my_imp = (bands.kind.to_numpy() != "gte") & (bands.high.to_numpy(float) < bucket[band_snap]) & has_floor[band_snap]
imp_agree = bool((my_imp == bands.floor_impossible.to_numpy(bool)).all())
log("floor mask agrees with cached column:", imp_agree)

W_facts = {"row_sum_min": float(W.sum(1).min()), "row_sum_max": float(W.sum(1).max()),
           "col_mean_min": float(W.mean(0).min()), "col_mean_max": float(W.mean(0).max()),
           "zero_share": float((W == 0).mean())}
log("W facts", W_facts)


def snap_mean(v):
    return np.add.reduceat(v, offsets) / n_bands


frame = snaps[["row_key", "date", "market", "station", "stratum", "local_hour"]].copy()
frame["served"] = snap_mean(se_s)
frame["mkt"] = snap_mean(se_m)
frame["week"] = pd.to_datetime(frame.date).dt.strftime("%G-W%V")


def apply_candidate(cand):
    """Floor mask + renormalise + served fallback; returns per-snapshot candidate Brier and use mask."""
    pc = np.full(len(bands), np.nan)
    pos = snap_pos.reindex(cand.row_key.to_numpy()).to_numpy()
    assert not np.isnan(pos).any()
    pos = pos.astype(int)
    pc[offsets[pos] + cand.band_index.to_numpy(int)] = cand.p.to_numpy(float)
    given = ~np.isnan(pc)
    n_given = np.bincount(band_snap, weights=given, minlength=N)
    provided = n_given == n_bands
    assert ((n_given == 0) | provided).all(), "partial snapshots"
    assert (pc[given] >= 0).all()
    pc = np.where(given & my_imp, 0.0, pc)
    total = np.bincount(band_snap, weights=np.where(given, pc, 0.0), minlength=N)
    use = provided & has_floor & (total > 0)
    scale = np.where(total > 0, total, 1.0)
    pcf = np.where(use[band_snap], pc / scale[band_snap], p_served)
    se_c = (pcf - y) ** 2
    return snap_mean(se_c), use, se_c


def cells_for(mask, col_a, col_b=None):
    g = frame[mask].groupby(["date", "market"], sort=True)
    a = g[col_a].mean()
    idx = np.array([kidx[k] for k in a.index])
    return a, idx


def w_interval(idx, a, b=None):
    a = np.asarray(a, float)
    b = np.ones(len(a)) if b is None else np.asarray(b, float)
    sub = W[:, idx]
    num, den = sub @ a, sub @ b
    boot = np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)
    fin = boot[np.isfinite(boot)]
    est = float(a.sum() / b.sum())
    sd = float(fin.std(ddof=1))
    return {"estimate": est, "ci95": np.quantile(fin, [.025, .975]).tolist(),
            "ci999": np.quantile(fin, [.0005, .9995]).tolist(),
            "boot_sd": sd, "z": est / sd if sd > 0 else float("nan"),
            "share_draws_ge_0": float((fin >= 0).mean()), "n_cells": int(len(a))}


def date_boot(cells, draws=2000, seed=424242):
    """Independent check: dates-only cluster bootstrap (different resampling scheme and seed)."""
    rng = np.random.default_rng(seed)
    df = cells.reset_index()
    dates = df.date.unique()
    per_date = df.groupby("date")[cells.name].agg(["sum", "size"])
    s, n = per_date["sum"].to_numpy(), per_date["size"].to_numpy(float)
    pick = rng.integers(0, len(dates), size=(draws, len(dates)))
    est = s[pick].sum(1) / n[pick].sum(1)
    return np.quantile(est, [.025, .975]).tolist()


def market_boot(cells, draws=2000, seed=777):
    """Markets-only cluster bootstrap (11 clusters: coarse, reported for completeness)."""
    rng = np.random.default_rng(seed)
    df = cells.reset_index()
    per = df.groupby("market")[cells.name].agg(["sum", "size"])
    s, n = per["sum"].to_numpy(), per["size"].to_numpy(float)
    pick = rng.integers(0, len(s), size=(draws, len(s)))
    est = s[pick].sum(1) / n[pick].sum(1)
    return np.quantile(est, [.025, .975]).tolist()


def group_mask(block, stratum=None):
    lo, hi = BLOCKS[block]
    m = frame.local_hour.between(lo, hi).to_numpy().copy()
    if stratum:
        m = m & (frame.stratum == stratum).to_numpy()
    return m


def analyse(name, cand_c, use):
    """Full independent table for one candidate: per block x stratum all-row + matched, LEAD classes."""
    frame["cand"] = cand_c
    frame["delta"] = frame.cand - frame.served
    frame["cm"] = frame.cand - frame.mkt
    frame["gap"] = frame.served - frame.mkt
    frame["use"] = use
    res = {"name": name, "tables": {}, "classes": {}, "per_market": {}, "per_week": {}, "loo_market": {},
           "loo_week": {}, "alt_boot": {}, "matched": {}, "tail": {}, "concentration": {}}
    for block in BLOCKS:
        est = {}
        for st in STRATA:
            m = group_mask(block, st)
            a, idx = cells_for(m, "delta")
            iv = w_interval(idx, a.to_numpy())
            cm, _ = cells_for(m, "cm")
            gap, _ = cells_for(m, "gap")
            ivcm = w_interval(idx, cm.to_numpy())
            ivgap = w_interval(idx, gap.to_numpy())
            mk = a.groupby(level="market").mean()
            closed = w_interval(idx, -a.to_numpy(), gap.to_numpy())
            res["tables"][f"{block}|{st}"] = {
                "cand_minus_served": iv, "cand_minus_market": ivcm, "served_minus_market": ivgap,
                "gap_closed": {"estimate": closed["estimate"], "ci95": closed["ci95"]},
                "market_brier": float(frame.loc[m].groupby(["date", "market"]).mkt.mean().mean()),
                "markets_negative": int((mk < 0).sum()), "markets_positive": int((mk > 0).sum()),
                "n_snapshots": int(m.sum()), "n_cells": int(len(a)),
                "fallback_share": float((~frame.use[m]).mean())}
            est[st] = iv
            # matched (selected on availability)
            mm = m & use
            am, idxm = cells_for(mm, "delta")
            res["matched"][f"{block}|{st}"] = w_interval(idxm, am.to_numpy())["estimate"]
            if st == "from_20260823":
                res["per_market"][block] = {k: float(v) for k, v in mk.items()}
                wk = a.groupby(frame.loc[m].groupby(["date", "market"]).week.first()).mean()
                res["per_week"][block] = {k: float(v) for k, v in wk.items()}
                res["alt_boot"][block] = {"dates_only_ci95": date_boot(a), "markets_only_ci95": market_boot(a)}
                # concentration: share of the summed cell delta carried by top market / week / single cell
                tot = a.sum()
                share_mkt = (a.groupby(level="market").sum() / tot).sort_values(ascending=False)
                wsum = a.groupby(frame.loc[m].groupby(["date", "market"]).week.first()).sum() / tot
                share_wk = wsum.sort_values(ascending=False)
                share_cell = (a / tot).sort_values(ascending=False)
                dmean = a.groupby(level="date").mean()
                res["concentration"][block] = {
                    "top_market": [share_mkt.index[0], float(share_mkt.iloc[0])],
                    "top_week": [share_wk.index[0], float(share_wk.iloc[0])],
                    "top_cell": [list(share_cell.index[0]), float(share_cell.iloc[0])],
                    "dates_negative": int((dmean < 0).sum()), "dates_total": int(len(dmean)),
                    "cells_negative": int((a < 0).sum()), "cells_zero": int((a == 0).sum()),
                    "cells_total": int(len(a))}
                # leave-one-market-out and leave-one-week-out W intervals (restricted to remaining cells)
                loo = {}
                for mkt in sorted(mk.index):
                    keep = a.index.get_level_values("market") != mkt
                    ivl = w_interval(idx[keep], a.to_numpy()[keep])
                    gl = w_interval(idx[keep], gap.to_numpy()[keep])["estimate"]
                    mk_l = a[keep].groupby(level="market").mean()
                    loo[mkt] = {"estimate": ivl["estimate"], "ci95": ivl["ci95"],
                                "size_ok": bool(ivl["estimate"] <= LEAD_LINE or ivl["estimate"] <= -GAP_SHARE * gl),
                                "markets_negative": int((mk_l < 0).sum())}
                res["loo_market"][block] = loo
                loo = {}
                wk_of_cell = frame.loc[m].groupby(["date", "market"]).week.first()
                for wname in sorted(wk.index):
                    keep = (wk_of_cell != wname).to_numpy()
                    ivl = w_interval(idx[keep], a.to_numpy()[keep])
                    gl = w_interval(idx[keep], gap.to_numpy()[keep])["estimate"]
                    loo[wname] = {"estimate": ivl["estimate"], "ci95": ivl["ci95"],
                                  "size_ok": bool(ivl["estimate"] <= LEAD_LINE or ivl["estimate"] <= -GAP_SHARE * gl)}
                res["loo_week"][block] = loo
        f = res["tables"][f"{block}|from_20260823"]
        b = res["tables"][f"{block}|before_20260823"]
        e, hi = f["cand_minus_served"]["estimate"], f["cand_minus_served"]["ci95"][1]
        gapf = f["served_minus_market"]["estimate"]
        conds = {"interval_excludes_0": bool(hi < 0),
                 "size": bool(e <= LEAD_LINE or e <= -GAP_SHARE * gapf),
                 "both_strata_negative": bool(e < 0 and b["cand_minus_served"]["estimate"] < 0),
                 "markets_ge_8_negative": bool(f["markets_negative"] >= MIN_MKTS)}
        res["classes"][block] = {"class": "LEAD" if all(conds.values()) else ("WEAK" if e < 0 else "OTHER"),
                                 **conds}
    return res


def tail_removed(se_c, mask):
    sel = mask[band_snap] & tail
    b = bands.loc[sel, ["date", "market"]].copy()
    b["excess"] = (se_s - se_m)[sel]
    b["improve"] = (se_s - se_c)[sel]
    c = b.groupby(["date", "market"]).sum()
    idx = np.array([kidx[k] for k in c.index])
    iv = w_interval(idx, c.improve.to_numpy(), c.excess.to_numpy())
    return {"estimate": iv["estimate"], "ci95": iv["ci95"], "tail_rows": int(sel.sum())}


# ------------------------------------------------------------------ rebuild the candidates under test
check_stop()
t0 = datetime.now()
log("building T4 candidates via the hunter's feature code ...")
s_, b_, feat, preds, fit_info = t4.build({"t4-r1": t4.LEVELS_FULL, "t4-r2": t4.LEVELS_T2})
cands = t4.candidates(s_, b_, feat, preds)
log("built in", datetime.now() - t0)
assert (s_.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
cand1, cov1 = cands["t4-r1"]
cand2, cov2 = cands["t4-r2"]
ps = b_.set_index(["row_key", "band_index"]).p_served
served_on_c1 = ps.reindex(pd.MultiIndex.from_frame(cand1[["row_key", "band_index"]])).to_numpy()
assert np.isfinite(served_on_c1).all()

# ------------------------------------------------------------------ independent w tuning (before stratum, pooled)
c1_brier, use1, se1 = apply_candidate(cand1)
before_all = group_mask("all", "before_20260823")
tune = {}
for w in [round(0.1 * k, 1) for k in range(1, 10)]:
    cw = cand1.assign(p=w * cand1.p.to_numpy() + (1 - w) * served_on_c1)
    cb, _, _ = apply_candidate(cw)
    frame["tmp"] = cb
    tune[w] = float(frame[before_all].groupby(["date", "market"]).tmp.mean().mean())
w_best = min(tune, key=tune.get)
log("independent tuning:", tune, "best", w_best)

cand3 = cand1.assign(p=W_REPORTED * cand1.p.to_numpy() + (1 - W_REPORTED) * served_on_c1)
results = {}
for name, cand in (("t4-r1", cand1), ("t4-r2", cand2), ("t4-r3", cand3)):
    check_stop()
    cb, use, se_c = apply_candidate(cand)
    r = analyse(name, cb, use)
    r["reason_counts"] = {"candidate": int(use.sum()), "fallback": int((~use).sum())}
    for block in ("13-16", "17-23", "10-12"):
        for st in STRATA:
            r["tail"][f"{block}|{st}"] = tail_removed(se_c, group_mask(block, st))
    results[name] = r
    log(name, {b: r["classes"][b]["class"] for b in BLOCKS})

# ------------------------------------------------------------------ availability vs outcome
check_stop()
frame["cov"] = cov1
avail = {}
for block in ("00-05", "06-09", "10-12", "13-16", "17-23"):
    for st in STRATA + ("pooled",):
        m = group_mask(block, None if st == "pooled" else st)
        sub = frame[m]
        g = sub.groupby("cov")[["served", "mkt"]].mean()
        gap_c = float((sub.served - sub.mkt)[sub["cov"]].mean()) if sub["cov"].any() else None
        gap_u = float((sub.served - sub.mkt)[~sub["cov"]].mean()) if (~sub["cov"]).any() else None
        # cluster (date) bootstrap on the covered-minus-uncovered gap difference
        ci = None
        if (~sub["cov"]).sum() >= 30 and sub["cov"].sum() >= 30:
            rng = np.random.default_rng(99)
            dsum = sub.assign(gap=sub.served - sub.mkt).groupby(["date", "cov"]).gap.agg(["sum", "size"]).unstack("cov")
            dsum = dsum.fillna(0.0)
            dates = dsum.index.to_numpy()
            est = []
            for _ in range(2000):
                pick = rng.integers(0, len(dates), len(dates))
                d = dsum.iloc[pick]
                a_c = d[("sum", True)].sum() / max(d[("size", True)].sum(), 1)
                a_u = d[("sum", False)].sum() / max(d[("size", False)].sum(), 1)
                est.append(a_c - a_u)
            ci = np.quantile(est, [.025, .975]).tolist()
        avail[f"{block}|{st}"] = {"n_cov": int(sub["cov"].sum()), "n_uncov": int((~sub["cov"]).sum()),
                                  "coverage": float(sub["cov"].mean()),
                                  "served_brier_cov": float(g.loc[True, "served"]) if True in g.index else None,
                                  "served_brier_uncov": float(g.loc[False, "served"]) if False in g.index else None,
                                  "gap_cov": gap_c, "gap_uncov": gap_u,
                                  "gap_cov_minus_uncov_ci95_dateboot": ci}
cov_by_hour = frame[frame.local_hour <= 5].groupby("local_hour")["cov"].mean().to_dict()
cov_by_market_0005 = frame[frame.local_hour <= 5].groupby("market")["cov"].mean().to_dict()
# is non-coverage in 00-05 associated with the winner being above the floor (i.e. with outcome)?
win_hi = bands.assign(win_hi=(bands.is_winner == 1) & (bands.high.astype(float) > bands.floor.astype(float)))
win_hi = win_hi.groupby("row_key").win_hi.any()
frame["win_above_floor"] = win_hi.reindex(frame.row_key).to_numpy()
m0005 = frame.local_hour <= 5
assoc = frame[m0005].groupby("cov").win_above_floor.mean().to_dict()

# ------------------------------------------------------------------ multiplicity from the registry
reg = [json.loads(l) for l in REG.read_text(encoding="utf-8").splitlines() if l.strip()]
is_ctrl = lambda r: any(k in r["text"] for k in ("CONTROL", "control", "sensitivity", "Sensitivity", "diagnostic"))
n_total = len(reg)
n_cand = sum(not is_ctrl(r) for r in reg)
n_agents = len({r["agent"] for r in reg})
t4_rows = [r["id"] for r in reg if r["agent"] == "t4"]
multiplicity = {"registry_lines": n_total, "candidate_rules": n_cand, "controls_or_sensitivities": n_total - n_cand,
                "agents_registered": n_agents, "t4_rules": t4_rows,
                "t4_registered_before_first_score": None,
                "blocks_classified_per_rule": 7,
                "tests_candidate_rules_x_blocks": n_cand * 7, "tests_all_lines_x_blocks": n_total * 7,
                "r3_w_grid_points": 9,
                "note": "registry read at run time; the synthesis denominator is the final count"}
# registration before first score: compare registry time with the first score file mtime
reg_t4 = [r for r in reg if r["agent"] == "t4" and r["id"] in ("t4-r1", "t4-r2", "t4-r3")]
first_score = datetime.fromtimestamp(Path(r"C:\swarm\out\t4\t4_r1.score.json").stat().st_mtime)
multiplicity["t4_registered_before_first_score"] = bool(
    max(datetime.fromisoformat(r["time_local"]) for r in reg_t4) < first_score)
multiplicity["t4_registry_times"] = [r["time_local"] for r in reg_t4]
multiplicity["first_t4_score_mtime"] = first_score.isoformat(timespec="seconds")

from math import erf, sqrt  # noqa: E402


def norm_sf(z):
    return 0.5 * (1 - erf(z / sqrt(2)))


def bonf_ok(iv, m):
    p1 = norm_sf(-iv["z"])  # one-sided P(delta >= 0)
    return {"z": iv["z"], "p_one_sided_normal": p1, "bonferroni_m": m, "survives_bonferroni": bool(p1 * m < 0.05),
            "ci999_excludes_0": bool(iv["ci999"][1] < 0), "share_draws_ge_0": iv["share_draws_ge_0"]}


mult_tests = {}
for name, r in results.items():
    for block in BLOCKS:
        if r["classes"][block]["class"] == "LEAD":
            iv = r["tables"][f"{block}|from_20260823"]["cand_minus_served"]
            mult_tests[f"{name}|{block}"] = {"m_candidate_rules_x_blocks": bonf_ok(iv, n_cand * 7),
                                             "m_all_lines_x_blocks": bonf_ok(iv, n_total * 7)}

out = {"agent": "r-stat-t4", "lens": "statistics refuter", "development": True,
       "time_local": datetime.now().isoformat(timespec="seconds"),
       "rows_after_2026_09_29": n_after, "floor_mask_agrees_with_cache": imp_agree, "W_facts": W_facts,
       "independent_w_tuning_before_pooled": {str(k): v for k, v in tune.items()}, "independent_w_best": w_best,
       "reported_w": W_REPORTED,
       "results": results, "availability_vs_outcome": avail, "coverage_by_hour_00_05": cov_by_hour,
       "coverage_by_market_00_05": cov_by_market_0005,
       "win_above_floor_by_coverage_00_05": {str(k): v for k, v in assoc.items()},
       "multiplicity": multiplicity, "multiplicity_tests_on_leads": mult_tests,
       "harness_sha256_reported_by_hunter": "8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74"}
(OUT / "refute_stat_t4.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
log("written", OUT / "refute_stat_t4.json")
