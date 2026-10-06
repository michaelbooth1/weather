"""R-STAT-T6: statistics refuter for T6 (t6-r2 / t6-r3 NBS latest cycle). Development only.

Candidate probabilities are rebuilt with the hunter's own builders (t6_nbs_latest, t6_nbs_controls,
t3_baselines); the PIT refuter owns input re-derivation. Everything downstream of the probabilities is
independent of the harness score(): own floor mask, own Brier, own (date, market) cell means, intervals
from W plus own crossed / date-only / market-only bootstraps, per-market / per-week signs, leave-one-out,
availability-vs-outcome association, mode decomposition (TXN / REM / REM0), forking paths, paired
marginal value over t3-r3 and over the no-source control t6-c1 and the captured-NBM control t6-c2.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-stat-t6_refute   (use runpy)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, binomtest, t as tdist

from tools.research.model_parity import harness as h
from tools.research.model_parity import t6_nbs_latest as t6
from tools.research.model_parity import t6_nbs_controls as t6c
from tools.research.model_parity import t3_baselines as t3
from tools.research.model_parity.r_stat_t5_refute import load_base, cand_brier, own_weights, boot_ci, cells_of

OUT = Path(r"C:\swarm\out\refute-stat-t6")
CACHE = Path(r"C:\swarm\cache")
GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
          ("00-16", 0, 16), ("all", 0, 23))
FROM, BEFORE = "from_20260823", "before_20260823"


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stop()
    res = {"agent": "r-stat-t6", "development": True, "HARNESS_SHA256": h.harness_sha256()}
    snaps, bands, offs, bsnap, own_imp, agree = load_base()
    res["floor_mask_agreement_with_harness"] = agree
    res["rows_after_20260929"] = int((snaps.date > "2026-09-29").sum())
    log("base", agree)

    cycles, info = t6.load_cycles()
    s, cb = t6.snapshot_frame()
    assert (s.row_key.to_numpy() == snaps.row_key.to_numpy()).all()
    params, _ = t6.fit_r3(cycles)
    res["r3_params"] = {k: list(v) for k, v in params.items()}
    stop()
    cands = {}
    cands["r2"], modes, ages = t6.build_candidate("r2", cycles, s, cb, None)
    cands["r3"], _, _ = t6.build_candidate("r2", cycles, s, cb, params)
    snaps_full, _ = h.candidate_inputs()
    ctl, _ = t6c.build_controls(cycles, s, cb, snaps_full)
    cands["c1"], cands["c2"] = ctl["t6-c1"], ctl["t6-c2"]
    t3c, _ = t3.build()
    cands["t3"] = t3c["t3-r3"]
    log("candidates rebuilt")
    stop()

    y = bands.is_winner.to_numpy(float)
    nb = snaps.n_bands.to_numpy()
    fr = snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    fr["served"] = np.add.reduceat((bands.p_served.to_numpy(float) - y) ** 2, offs) / nb
    fr["mkt"] = np.add.reduceat((bands.p_market_yes.to_numpy(float) - y) ** 2, offs) / nb
    for k, c in cands.items():
        b, use, _ = cand_brier(c, snaps, bands, offs, bsnap, own_imp)
        fr[k], fr["cov_" + k] = b, use.astype(float)
    fr["mode"], fr["age"] = modes, ages
    # REM0-free variant of r2 (REM0 rows -> served): how much of 17-23 is the REM0 collapse
    fr["r2_noREM0"] = np.where(fr["mode"] == "REM0", fr.served, fr.r2)
    # TXN-only-changed variant: r2 on TXN rows only
    fr["r2_TXNonly"] = np.where(fr["mode"] == "TXN", fr.r2, fr.served)
    fr["r2_REMonly"] = np.where(fr["mode"] == "REM", fr.r2, fr.served)
    fr["week"] = pd.to_datetime(fr.date).dt.strftime("%G-W%V")

    # harness cross-check of my own scoring
    hchk = {}
    for k, nm in (("r2", "t6_r2_nbs"), ("r3", "t6_r3_nbs")):
        j = json.loads((Path(r"C:\swarm\out\t6") / f"{nm}.score.json").read_text(encoding="utf-8"))
        hchk[k] = j.get("classes", {}).get("17-23", {}).get("class")
    res["hunter_saved_classes_17_23"] = hchk

    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text(encoding="utf-8"))]
    kidx = {k: i for i, k in enumerate(keys)}
    ow = own_weights(keys)
    reg = [json.loads(x) for x in open(r"C:\swarm\registry.jsonl", encoding="utf-8") if x.strip()]
    n_reg = len(reg)
    z_bonf = float(norm.ppf(1 - 0.025 / n_reg))
    res["registry_rules_at_run"] = n_reg
    res["t6_registry"] = [{"id": r["id"], "time_local": r["time_local"]} for r in reg if r["agent"] == "t6"]
    res["bonferroni_z"] = z_bonf

    def stat(sub, a, b, full=True):
        c = cells_of(sub, list(dict.fromkeys([a, b, "served", "mkt"])))
        idx = np.array([kidx[(d, m)] for d, m in zip(c.date, c.market)])
        dl = (c[a] - c[b]).to_numpy(float)
        est = float(dl.mean())
        ciW, sdW = boot_ci(W, idx, dl)
        out = {"estimate": est, "cells": int(len(c)), "ci_W": ciW}
        pm = c.assign(dl=dl).groupby("market").dl.mean()
        out["markets_negative"] = int((pm < 0).sum())
        out["per_market"] = {k: round(float(v), 6) for k, v in pm.items()}
        if not full:
            return out
        for k, w in ow.items():
            out["ci_" + k], _ = boot_ci(w, idx, dl)
        out["ci_bonferroni_normal"] = [est - z_bonf * sdW, est + z_bonf * sdW]
        out["sign_test_p"] = float(binomtest(int((pm < 0).sum()), len(pm), .5, "greater").pvalue)
        se = pm.std(ddof=1) / math.sqrt(len(pm))
        q = tdist.ppf(.975, len(pm) - 1)
        out["market_t_ci95"] = [float(pm.mean() - q * se), float(pm.mean() + q * se)]
        lomo = {}
        for m in pm.index:
            keep = (c.market != m).to_numpy()
            ci, _ = boot_ci(W, idx[keep], dl[keep])
            lomo[m] = {"est": float(dl[keep].mean()), "ci_W": ci, "neg": int((pm.drop(m) < 0).sum())}
        out["leave_one_market_out"] = lomo
        wk = c.assign(dl=dl, week=pd.to_datetime(c.date).dt.strftime("%G-W%V"))
        out["per_week"] = {k: round(float(g.dl.mean()), 6) for k, g in wk.groupby("week")}
        lowo = {}
        for w_ in sorted(wk.week.unique()):
            keep = (wk.week != w_).to_numpy()
            ci, _ = boot_ci(W, idx[keep], dl[keep])
            lowo[w_] = {"est": float(dl[keep].mean()), "ci_W": ci}
        out["leave_one_week_out"] = lowo
        tot = dl.sum()
        msum = c.assign(dl=dl).groupby("market").dl.sum()
        out["top_market_share_of_sum"] = float(msum.min() / tot) if tot < 0 else None
        out["top_week_share_of_sum"] = float(wk.groupby("week").dl.sum().min() / tot) if tot < 0 else None
        out["served_minus_market"] = float((c.served - c.mkt).mean())
        return out

    blocks = {}
    for cand in ("r2", "r3"):
        for g, lo, hi in GROUPS:
            stop()
            gm = fr.local_hour.between(lo, hi)
            blk = {st: stat(fr[gm & (fr.stratum == st)], cand, "served") for st in (FROM, BEFORE)}
            f = blk[FROM]
            gap = f["served_minus_market"]
            conds = {"interval_excludes_0_W": f["ci_W"][1] < 0,
                     "interval_excludes_0_crossed_seed777": f["ci_crossed_seed777"][1] < 0,
                     "interval_excludes_0_market_cluster": f["ci_market_cluster"][1] < 0,
                     "interval_excludes_0_date_cluster": f["ci_date_cluster"][1] < 0,
                     "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * gap,
                     "both_strata_negative": f["estimate"] < 0 and blk[BEFORE]["estimate"] < 0,
                     "markets_ge_8": f["markets_negative"] >= 8,
                     "lomo_all_keep_interval": all(v["ci_W"][1] < 0 for v in f["leave_one_market_out"].values()),
                     "lomo_all_keep_markets_ge_8": all(v["neg"] >= 8 for v in f["leave_one_market_out"].values()),
                     "lowo_all_keep_interval": all(v["ci_W"][1] < 0 for v in f["leave_one_week_out"].values()),
                     "bonferroni_excludes_0": f["ci_bonferroni_normal"][1] < 0}
            blk["conditions"] = {k: bool(v) for k, v in conds.items()}
            blk["lead_independent"] = bool(conds["interval_excludes_0_W"] and conds["size"]
                                           and conds["both_strata_negative"] and conds["markets_ge_8"])
            sub = fr[gm & (fr.stratum == FROM)]
            cov = sub["cov_" + cand]
            blk["coverage_from"] = float(cov.mean())
            blk["gap_covered"] = float((sub.served - sub.mkt)[cov == 1].mean())
            blk["gap_fallback"] = float((sub.served - sub.mkt)[cov == 0].mean()) if (cov == 0).any() else None
            cv = sub[cov == 1].copy()
            if len(cv) > 30 and cv.age.nunique() > 3:
                cv["tq"] = pd.qcut(cv.age, 3, labels=["young", "mid", "old"], duplicates="drop")
                blk["delta_by_age_tercile"] = {str(k): {"delta": float((g_[cand] - g_.served).mean()),
                                                        "age_med_h": float(g_.age.median()), "n": int(len(g_))}
                                               for k, g_ in cv.groupby("tq", observed=True)}
            dd = sub[cand] - sub.served
            blk["mode_decomp_from"] = {m: {"n": int((sub["mode"] == m).sum()),
                                           "share_of_delta_sum": float(dd[sub["mode"] == m].sum() / dd.sum())
                                           if dd.sum() != 0 else None,
                                           "mean_delta": float(dd[sub["mode"] == m].mean()) if (sub["mode"] == m).any() else None}
                                       for m in ("TXN", "REM", "REM0", "NONE")}
            if cand == "r2":
                pb = {}
                for other in ("t3", "c1", "c2"):
                    pb[other] = {st: stat(fr[gm & (fr.stratum == st)], "r2", other, full=(st == FROM))
                                 for st in (FROM, BEFORE)}
                for var in ("r2_noREM0", "r2_TXNonly", "r2_REMonly", "c1", "c2", "t3"):
                    pb[var + "_vs_served"] = {st: stat(fr[gm & (fr.stratum == st)], var, "served", full=False)
                                              for st in (FROM, BEFORE)}
                blk["paired"] = pb
            if cand == "r3":
                blk["paired"] = {o: {st: stat(fr[gm & (fr.stratum == st)], "r3", o, full=False)
                                     for st in (FROM, BEFORE)} for o in ("t3", "c1", "r2")}
            blocks[f"{cand}|{g}"] = blk
            log(cand, g, "est", round(f["estimate"], 5), f["ci_W"], "LEAD", blk["lead_independent"],
                {k: v for k, v in blk["conditions"].items() if not v})
    res["blocks"] = blocks
    (OUT / "result_stats.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    fr.drop(columns=["row_key"]).to_parquet(OUT / "snap_scored.parquet")
    log("done")


if __name__ == "__main__":
    main()
