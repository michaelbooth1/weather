"""R-STAT-T5: statistics refuter for T5 (t5-r1 NBH latest cycle). Development only.

Independent recomputation of the T5 LEAD conditions from the cache (own floor mask, own Brier, own cell
means), intervals from W plus own bootstraps (crossed seed 2, date-cluster, market-cluster), per-market
and per-week checks, leave-one-market/week-out, availability-vs-outcome association, forking paths from
the registry, and paired marginal value over the remaining-rise rung t3-r3 (and T1 in 17-23).

The candidate probabilities are rebuilt with the hunter's own builder (t5_nbh_latest.build_candidate);
the PIT refuter owns the input re-derivation. Everything downstream of the probabilities is independent.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r_stat_t5_refute
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, binomtest, t as tdist

from tools.research.model_parity import harness as h
from tools.research.model_parity import t5_nbh_latest as t5

OUT = Path(r"C:\swarm\out\refute-stat-t5")
CACHE = Path(r"C:\swarm\cache")
T3_CAND = Path(r"C:\swarm\out\refute-stat-t3\cand_r3.parquet")
T1_SNAP = Path(r"C:\swarm\out\refute-stat-t1\snap_scored.parquet")
GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
          ("00-16", 0, 16), ("all", 0, 23))
FROM, BEFORE = "from_20260823", "before_20260823"


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ independent scoring

def load_base():
    snaps = pd.read_parquet(CACHE / "snapshots.parquet",
                            columns=["row_key", "date", "market", "stratum", "local_hour", "n_bands", "floor"])
    bands = pd.read_parquet(CACHE / "bands.parquet",
                            columns=["row_key", "band_index", "kind", "low", "high", "p_served",
                                     "p_market_yes", "is_winner", "floor_impossible"])
    assert snaps.date.max() <= "2026-09-29" and len(snaps) == 110807
    n = snaps.n_bands.to_numpy()
    offs = np.concatenate([[0], np.cumsum(n)[:-1]])
    assert (bands.row_key.to_numpy()[offs] == snaps.row_key.to_numpy()).all()
    bsnap = np.repeat(np.arange(len(snaps)), n)
    # own floor mask (81a form) and agreement with the cached flag
    F = snaps.floor.to_numpy(float)[bsnap]
    bucket = np.floor(F + .5)
    own_imp = np.where(np.isfinite(F), (bands.kind.to_numpy() != "gte") & (bands.high.to_numpy(float) < bucket),
                       False)
    agree = float((own_imp == bands.floor_impossible.to_numpy(bool)).mean())
    return snaps, bands, offs, bsnap, own_imp, agree


def cand_brier(cand, snaps, bands, offs, bsnap, own_imp):
    """Per-snapshot Brier of a candidate frame with served fallback (all-row), own implementation."""
    pos = pd.Series(np.arange(len(snaps)), index=snaps.row_key).reindex(cand.row_key.to_numpy()).to_numpy()
    assert not np.isnan(pos).any()
    pos = pos.astype(int)
    pc = np.full(len(bands), np.nan)
    pc[offs[pos] + cand.band_index.to_numpy(int)] = cand.p.to_numpy(float)
    given = ~np.isnan(pc)
    ng = np.bincount(bsnap, weights=given, minlength=len(snaps))
    nb = snaps.n_bands.to_numpy()
    assert not ((ng > 0) & (ng < nb)).any()
    prov = (ng == nb) & snaps.floor.notna().to_numpy()
    pc = np.where(given & own_imp, 0.0, pc)
    tot = np.bincount(bsnap, weights=np.where(given, pc, 0.0), minlength=len(snaps))
    use = prov & (tot > 0)
    pp = np.where(use[bsnap], pc / np.where(tot > 0, tot, 1.0)[bsnap], bands.p_served.to_numpy(float))
    y = bands.is_winner.to_numpy(float)
    se = (pp - y) ** 2
    return np.add.reduceat(se, offs) / nb, use, pp


def cells_of(frame, cols):
    return frame.groupby(["date", "market"], sort=True)[cols].mean().reset_index()


# ------------------------------------------------------------------ bootstraps

def own_weights(keys, draws=2000, seed=777):
    """Crossed date x market multinomial weights (independent seed), date-only, market-only."""
    rng = np.random.default_rng(seed)
    dates = sorted({k[0] for k in keys})
    mkts = sorted({k[1] for k in keys})
    di = np.array([dates.index(k[0]) for k in keys])
    mi = np.array([mkts.index(k[1]) for k in keys])
    cd = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), size=draws).astype(float)
    cm = rng.multinomial(len(mkts), np.full(len(mkts), 1 / len(mkts)), size=draws).astype(float)
    return {"crossed_seed777": cd[:, di] * cm[:, mi], "date_cluster": cd[:, di], "market_cluster": cm[:, mi]}


def boot_ci(w, idx, a):
    sub = w[:, idx]
    den = sub.sum(1)
    est = np.divide(sub @ a, den, out=np.full(len(den), np.nan), where=den > 0)
    est = est[np.isfinite(est)]
    return [float(np.quantile(est, .025)), float(np.quantile(est, .975))], float(est.std())


# ------------------------------------------------------------------ main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"agent": "r-stat-t5", "development": True, "HARNESS_SHA256": h.harness_sha256()}
    snaps, bands, offs, bsnap, own_imp, agree = load_base()
    res["floor_mask_agreement_with_harness"] = agree
    res["rows_after_20260929"] = int((snaps.date > "2026-09-29").sum())
    log("base loaded; floor agreement", agree)

    # rebuild T5 r1 with the hunter's builder (probabilities only)
    s, cb = t5.snapshot_frame()
    idx_nbh = t5.load_nbh()
    cand, ages, mus, reasons = t5.build_candidate(idx_nbh, s, cb, None)
    cand.to_parquet(OUT / "cand_t5_r1.parquet")
    res["t5_reasons"] = reasons
    log("t5 candidate rebuilt", reasons)
    hs = h.score(cand, name="t5_r1_refute_rebuild")
    res["harness_rebuild_classes"] = {g: hs["classes"][g]["class"] for g in hs["classes"]}
    res["harness_rebuild_from_est"] = {g: h.table_lookup(hs, g, FROM, "all_row")["candidate_minus_served"]["estimate"]
                                       for g, _, _ in GROUPS}

    b5, use5, pp5 = cand_brier(cand, snaps, bands, offs, bsnap, own_imp)
    y = bands.is_winner.to_numpy(float)
    served = np.add.reduceat((bands.p_served.to_numpy(float) - y) ** 2, offs) / snaps.n_bands.to_numpy()
    mkt = np.add.reduceat((bands.p_market_yes.to_numpy(float) - y) ** 2, offs) / snaps.n_bands.to_numpy()
    fr = snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    fr["served"], fr["mkt"], fr["t5"], fr["cov5"] = served, mkt, b5, use5.astype(float)
    fr["age"], fr["mu"] = ages, mus
    fr["B"] = np.floor(snaps.floor.to_numpy(float) + .5)
    # collapse indicator: NBH remaining max below the floor bucket by >= 1 (mass forced onto floor band)
    fr["collapse"] = (fr.mu + 1 <= fr.B).astype(float)

    # T3 r3 (remaining-rise rung) with served fallback
    if T3_CAND.exists():
        c3 = pd.read_parquet(T3_CAND)
        b3, use3, _ = cand_brier(c3, snaps, bands, offs, bsnap, own_imp)
        fr["t3"], fr["cov3"] = b3, use3.astype(float)
    # T1 r2 per-snapshot Brier from its stat refuter (verified against T1's reported estimate below)
    if T1_SNAP.exists():
        t1 = pd.read_parquet(T1_SNAP, columns=["row_key", "cand"])
        fr = fr.merge(t1.rename(columns={"cand": "t1"}), on="row_key", how="left")

    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text(encoding="utf-8"))]
    kidx = {k: i for i, k in enumerate(keys)}
    ow = own_weights(keys)
    n_reg = sum(1 for _ in open(r"C:\swarm\registry.jsonl", encoding="utf-8"))
    z_bonf = float(norm.ppf(1 - 0.025 / n_reg))
    res["registry_rules_at_run"] = n_reg
    res["bonferroni_z"] = z_bonf
    fr["week"] = pd.to_datetime(fr.date).dt.strftime("%G-W%V")

    def stat(sub, a_col, b_col, with_market=True):
        c = cells_of(sub, list(dict.fromkeys([a_col, b_col, "served", "mkt"])))
        idx = np.array([kidx[(d, m)] for d, m in zip(c.date, c.market)])
        dl = (c[a_col] - c[b_col]).to_numpy(float)
        est = float(dl.mean())
        ciW, sdW = boot_ci(W, idx, dl)
        out = {"estimate": est, "cells": int(len(c)), "ci_W": ciW, "sd_W": sdW}
        for k, w in ow.items():
            out["ci_" + k], out["sd_" + k] = boot_ci(w, idx, dl)
        out["ci_bonferroni_normal"] = [est - z_bonf * sdW, est + z_bonf * sdW]
        pm = c.assign(dl=dl).groupby("market").dl.mean()
        out["per_market"] = {k: float(v) for k, v in pm.items()}
        out["markets_negative"] = int((pm < 0).sum())
        out["sign_test_p_one_sided"] = float(binomtest(int((pm < 0).sum()), len(pm), .5, "greater").pvalue)
        tt = pm.mean() / (pm.std(ddof=1) / math.sqrt(len(pm)))
        out["market_t"] = float(tt)
        out["market_t_ci95"] = [float(pm.mean() - tdist.ppf(.975, len(pm) - 1) * pm.std(ddof=1) / math.sqrt(len(pm))),
                                float(pm.mean() + tdist.ppf(.975, len(pm) - 1) * pm.std(ddof=1) / math.sqrt(len(pm)))]
        # leave one market out (estimate, W interval upper, markets negative)
        lomo = {}
        for m in pm.index:
            keep = (c.market != m).to_numpy()
            ci, _ = boot_ci(W, idx[keep], dl[keep])
            pmk = pm.drop(m)
            lomo[m] = {"est": float(dl[keep].mean()), "ci_W": ci, "neg": int((pmk < 0).sum()), "of": len(pmk)}
        out["leave_one_market_out"] = lomo
        wk = c.assign(dl=dl, week=pd.to_datetime(c.date).dt.strftime("%G-W%V"))
        out["per_week"] = {k: {"delta": float(g.dl.mean()), "cells": int(len(g))} for k, g in wk.groupby("week")}
        lowo = {}
        for w_ in sorted(wk.week.unique()):
            keep = (wk.week != w_).to_numpy()
            ci, _ = boot_ci(W, idx[keep], dl[keep])
            lowo[w_] = {"est": float(dl[keep].mean()), "ci_W": ci}
        out["leave_one_week_out"] = lowo
        # concentration: share of the summed negative cell delta in the top market / top week
        tot = dl.sum()
        out["top_market_share_of_sum"] = float(pm.mul(c.groupby("market").size()).min() / tot) if tot < 0 else None
        out["top_week_share_of_sum"] = float(wk.groupby("week").dl.sum().min() / tot) if tot < 0 else None
        if with_market:
            out["served_minus_market"] = float((c.served - c.mkt).mean())
        return out

    blocks = {}
    for g, lo, hi in GROUPS:
        gm = fr.local_hour.between(lo, hi)
        blk = {}
        for st in (FROM, BEFORE):
            sub = fr[gm & (fr.stratum == st)]
            blk[st] = stat(sub, "t5", "served")
        f = blk[FROM]
        gap = f["served_minus_market"]
        conds = {"interval_excludes_0_W": f["ci_W"][1] < 0,
                 "interval_excludes_0_crossed_seed777": f["ci_crossed_seed777"][1] < 0,
                 "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * gap,
                 "both_strata_negative": f["estimate"] < 0 and blk[BEFORE]["estimate"] < 0,
                 "markets_ge_8": f["markets_negative"] >= 8,
                 "lomo_all_keep_interval": all(v["ci_W"][1] < 0 for v in f["leave_one_market_out"].values()),
                 "lomo_all_keep_markets_ge_8_of_10": all(v["neg"] >= 8 for v in f["leave_one_market_out"].values()),
                 "lowo_all_keep_interval": all(v["ci_W"][1] < 0 for v in f["leave_one_week_out"].values()),
                 "bonferroni_excludes_0": f["ci_bonferroni_normal"][1] < 0}
        blk["conditions"] = {k: bool(v) for k, v in conds.items()}
        blk["lead_independent"] = bool(conds["interval_excludes_0_W"] and conds["size"]
                                       and conds["both_strata_negative"] and conds["markets_ge_8"])
        # availability-vs-outcome: covered vs fallback snapshots (from stratum)
        sub = fr[gm & (fr.stratum == FROM)]
        blk["coverage_from"] = float(sub.cov5.mean())
        blk["served_minus_market_covered"] = float((sub.served - sub.mkt)[sub.cov5 == 1].mean())
        blk["served_minus_market_fallback"] = float((sub.served - sub.mkt)[sub.cov5 == 0].mean()) if (sub.cov5 == 0).any() else None
        # delta by cycle-age tercile (covered rows, snapshot level, from stratum)
        cv = sub[sub.cov5 == 1].copy()
        if len(cv) > 30:
            cv["tq"] = pd.qcut(cv.age, 3, labels=["young", "mid", "old"], duplicates="drop")
            blk["delta_by_age_tercile"] = {str(k): {"delta": float((g_.t5 - g_.served).mean()),
                                                    "age_med_h": float(g_.age.median()), "n": int(len(g_))}
                                           for k, g_ in cv.groupby("tq", observed=True)}
            blk["corr_age_delta"] = float(np.corrcoef(cv.age, cv.t5 - cv.served)[0, 1])
        # collapse decomposition (from stratum)
        blk["collapse_share_from"] = float(sub.collapse.mean())
        dsum = (sub.t5 - sub.served)
        blk["delta_collapse_rows_mean"] = float(dsum[sub.collapse == 1].mean()) if (sub.collapse == 1).any() else None
        blk["delta_noncollapse_rows_mean"] = float(dsum[sub.collapse == 0].mean())
        blk["share_of_delta_from_collapse_rows"] = float(dsum[sub.collapse == 1].sum() / dsum.sum()) if dsum.sum() != 0 else None
        # paired marginal value over t3-r3 and t1-r2
        for other in ("t3", "t1"):
            if other in fr:
                pb = {}
                for st in (FROM, BEFORE):
                    sub2 = fr[gm & (fr.stratum == st)]
                    pb[st] = stat(sub2, "t5", other, with_market=False)
                    pb[st + "_other_minus_served"] = float(cells_of(sub2, [other, "served"]).pipe(
                        lambda c: (c[other] - c.served).mean()))
                blk["paired_vs_" + other] = pb
        blocks[g] = blk
        log(g, "independent LEAD", blk["lead_independent"], {k: v for k, v in blk["conditions"].items()})
    res["blocks"] = blocks

    # restricted collapse-free check: T5 on non-collapse snapshots only (others served), 17-23 and 00-16
    nc = fr.copy()
    nc["t5nc"] = np.where(nc.collapse == 1, nc.served, nc.t5)
    res["noncollapse_only"] = {}
    for g, lo, hi in GROUPS:
        gm = nc.local_hour.between(lo, hi)
        res["noncollapse_only"][g] = {st: {k: v for k, v in stat(nc[gm & (nc.stratum == st)], "t5nc", "served").items()
                                           if k in ("estimate", "ci_W", "markets_negative")} for st in (FROM, BEFORE)}
    # sanity: T3 / T1 standalone from-stratum estimates (to verify the reused files)
    chk = {}
    for other in ("t3", "t1"):
        if other in fr:
            chk[other] = {g: float(cells_of(fr[fr.local_hour.between(lo, hi) & (fr.stratum == FROM)],
                                            [other, "served"]).pipe(lambda c: (c[other] - c.served).mean()))
                          for g, lo, hi in GROUPS}
    res["reused_candidate_check_from_all_row"] = chk
    (OUT / "result_stats.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    fr.drop(columns=["row_key"]).to_parquet(OUT / "snap_scored.parquet")
    log("done")


if __name__ == "__main__":
    main()
