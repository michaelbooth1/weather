"""R-STAT-T7: statistics refuter for T7 (MOS/NBE consensus). Development only. No new rules.

Independently rebuilds t7-r1, t7-r2 and t7-c1 band probabilities from T7's saved per-snapshot
consensus values (consensus_eval.parquet) and fitted params (t7_meta.json), scores them WITHOUT
h.score (own Brier, own cells), and computes:
  - W-based intervals (reproduction) and independent bootstraps (date-cluster, market-cluster,
    own crossed weights, seed 4242), leave-one-market-out, leave-one-week-out, per-week signs;
  - paired r1-c1 and r2-c1 intervals (W);
  - availability-vs-outcome association;
  - multiplicity adjustment over the registry.
Run from C:\\pt\\swarm with the repo venv.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import erf  # noqa: F401  (fallback below if missing)

CACHE = Path(r"C:\swarm\cache")
T7 = Path(r"C:\swarm\out\t7")
OUT = Path(r"C:\swarm\out\refute-stat-t7")
BLOCKS = [("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
          ("00-16", 0, 16), ("all", 0, 23)]
STRATA = ["before_20260823", "from_20260823"]


def ncdf(x):
    return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    b = pd.read_parquet(CACHE / "bands.parquet")
    s = pd.read_parquet(CACHE / "snapshots.parquet")
    assert (s.date > "2026-09-29").sum() == 0
    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text())]
    kidx = {k: i for i, k in enumerate(keys)}
    ev = pd.read_parquet(T7 / "consensus_eval.parquet").set_index("row_key")
    meta = json.loads((T7 / "t7_meta.json").read_text())["meta"]

    # order bands as harness does: snapshots order, band_index
    s = s.reset_index(drop=True)
    pos = pd.Series(np.arange(len(s)), index=s.row_key)
    b = b.assign(sp=pos.reindex(b.row_key).to_numpy()).sort_values(["sp", "band_index"]).reset_index(drop=True)
    sp = b.sp.to_numpy(int)
    y = b.is_winner.to_numpy(float)
    ps = b.p_served.to_numpy(float)
    pm = b.p_market_yes.to_numpy(float)
    hour = s.local_hour.to_numpy(int)[sp]
    lo, hi, kind = b.low.to_numpy(float), b.high.to_numpy(float), b.kind.to_numpy()
    imp = b.floor_impossible.to_numpy(bool)
    has_floor = s.floor.notna().to_numpy()
    nb = np.bincount(sp, minlength=len(s))

    def gauss(mu_snap, b_h, s_h, max_floor):
        mu = mu_snap[sp] + b_h[hour]
        sd = s_h[hour]
        up = np.where(kind == "gte", np.inf, hi + 0.5)
        dn = np.where(kind == "lte", -np.inf, lo - 0.5)
        cu = np.where(np.isinf(up), 1.0, ncdf((np.where(np.isinf(up), 0, up) - mu) / sd))
        cd = np.where(np.isinf(dn), 0.0, ncdf((np.where(np.isinf(dn), 0, dn) - mu) / sd))
        p = np.clip(cu - cd, 0, None)
        if max_floor:
            # first floor-possible band per snapshot gets cu
            poss = ~imp
            first = np.zeros(len(p), bool)
            cs = np.cumsum(poss)
            start = np.r_[0, np.cumsum(nb)[:-1]]
            before = cs - poss  # cumulative count of possible bands before this row (global)
            first = poss & (before == (cs[start] - poss[start])[sp])
            p = np.where(first, cu, p)
        p = np.where(imp, 0.0, p)
        p = np.where(np.isnan(mu), np.nan, p)
        tot = np.bincount(sp, weights=np.nan_to_num(p), minlength=len(s))
        ok_snap = np.isfinite(mu_snap) & has_floor & (tot > 0)
        pc = np.where(ok_snap[sp], np.nan_to_num(p) / np.where(tot > 0, tot, 1)[sp], ps)
        return pc, ok_snap

    def par(v, k):
        pr = meta[v]["params"]
        return np.array([pr[str(hh)][k] for hh in range(24)], float)

    R = ev.reindex(s.row_key).R.to_numpy(float)
    C = ev.reindex(s.row_key).C.to_numpy(float)
    cap = pd.to_datetime(s.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(s.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    v2 = s.v2_mean.where(s.v2_mean.notna() & v2av.notna() & (v2av <= cap)).to_numpy(float)
    cands = {
        "r2": gauss(R, par("r2", "b2"), par("r2", "s2"), True),
        "r1": gauss(C, par("r1", "b1"), par("r1", "s1"), False),
        "c1": gauss(v2, par("r1", "b1"), par("r1", "s1"), False),
        # DIAGNOSTIC ONLY (not a rule, no class): c1 centre + r2's X = max(floor, Y) mechanism
        "c1m": gauss(v2, par("r1", "b1"), par("r1", "s1"), True),
    }
    start = np.r_[0, np.cumsum(nb)[:-1]]
    smean = lambda v: np.add.reduceat(v, start) / nb
    frame = s[["row_key", "market", "date", "stratum", "local_hour"]].copy()
    frame["served"] = smean((ps - y) ** 2)
    frame["mkt"] = smean((pm - y) ** 2)
    for k, (pc, ok) in cands.items():
        frame[k] = smean((pc - y) ** 2)
        frame[k + "_cov"] = ok
    d0 = pd.to_datetime(frame.date)
    frame["week"] = ((d0 - pd.Timestamp("2026-08-01")).dt.days // 7).astype(int)

    rng = np.random.default_rng(4242)
    dates = sorted(frame.date.unique())
    markets = sorted(frame.market.unique())
    B = 2000
    wd = rng.exponential(size=(B, len(dates)))  # Bayesian bootstrap weights (independent method)
    wm = rng.exponential(size=(B, len(markets)))
    di = {d: i for i, d in enumerate(dates)}
    mi = {m: i for i, m in enumerate(markets)}

    def cells(sub, col):
        c = sub.groupby(["date", "market"], sort=True)[["served", "mkt", col]].mean().reset_index()
        return c

    def stats(sub, col, other="served"):
        c = sub.groupby(["date", "market"], sort=True)[["served", "mkt", "r1", "r2", "c1", "c1m"]].mean().reset_index()
        dlt = (c[col] - c[other]).to_numpy()
        gap = (c.served - c.mkt).to_numpy()
        idx = np.array([kidx[(a, m)] for a, m in zip(c.date, c.market)])
        sw = W[:, idx]
        bw = (sw @ dlt) / sw.sum(1)
        ix_d = np.array([di[a] for a in c.date]); ix_m = np.array([mi[m] for m in c.market])
        wdd = wd[:, ix_d]; wmm = wm[:, ix_m]
        bd = (wdd @ dlt) / wdd.sum(1)
        bm = (wmm @ dlt) / wmm.sum(1)
        wx = wdd * wmm  # own crossed (product) weights
        bx = (wx @ dlt) / wx.sum(1)
        pm_ = c.assign(dl=dlt).groupby("market").dl.mean()
        pw = c.assign(dl=dlt, wk=((pd.to_datetime(c.date) - pd.Timestamp("2026-08-01")).dt.days // 7)).groupby("wk").dl.mean()
        lomo = {m: float(dlt[c.market.to_numpy() != m].mean()) for m in markets}
        wk = ((pd.to_datetime(c.date) - pd.Timestamp("2026-08-01")).dt.days // 7).to_numpy()
        lowo = {int(w): float(dlt[wk != w].mean()) for w in np.unique(wk)}
        q = lambda a: [float(np.quantile(a, .025)), float(np.quantile(a, .975))]
        se = float(np.std(bw))
        return {"est": float(dlt.mean()), "gap": float(gap.mean()), "n_cells": int(len(c)),
                "W_ci": q(bw), "W_frac_ge0": float((bw >= 0).mean()), "W_se": se,
                "z": float(dlt.mean() / se) if se > 0 else None,
                "date_bb_ci": q(bd), "market_bb_ci": q(bm), "crossed_bb_ci": q(bx),
                "per_market": {k: float(v) for k, v in pm_.items()},
                "mk_neg": int((pm_ < 0).sum()), "per_week": {int(k): float(v) for k, v in pw.items()},
                "wk_neg": int((pw < 0).sum()), "wk_n": int(len(pw)),
                "lomo_max": float(max(lomo.values())), "lomo_argmax": max(lomo, key=lomo.get),
                "lowo_max": float(max(lowo.values())), "lowo_argmax": int(max(lowo, key=lowo.get)),
                "top_market_share": float(pm_.min() / pm_.sum()) if pm_.sum() != 0 else None}

    res = {}
    for g, l, h_ in BLOCKS:
        for st in STRATA + ["pooled"]:
            sub = frame[frame.local_hour.between(l, h_)]
            if st != "pooled":
                sub = sub[sub.stratum == st]
            for col, other in [("r2", "served"), ("r1", "served"), ("c1", "served"), ("r1", "c1"), ("r2", "c1"), ("c1m", "served"), ("r2", "c1m")]:
                res[f"{col}-{other}|{g}|{st}"] = stats(sub, col, other)
    # availability vs outcome: covered vs uncovered served-market gap & served Brier (r2 / r4-like proxy nR)
    av = {}
    nR = ev.reindex(s.row_key).nR.to_numpy()
    frame["nR"] = nR
    for g, l, h_ in BLOCKS:
        sub = frame[frame.local_hour.between(l, h_) & (frame.stratum == "from_20260823")]
        out = {}
        for lab, m in [("r2_cov", sub.r2_cov), ("r2_uncov", ~sub.r2_cov), ("nR5", sub.nR == 5),
                       ("nR3", sub.nR == 3), ("nR1", sub.nR == 1)]:
            ss = sub[m]
            out[lab] = {"snaps": int(len(ss)), "served": float(ss.served.mean()) if len(ss) else None,
                        "mkt": float(ss.mkt.mean()) if len(ss) else None,
                        "delta_r2": float((ss.r2 - ss.served).mean()) if len(ss) else None}
        av[g] = out
    # coverage by market-day vs outcome: uncovered share per cell vs served-mkt gap (Spearman)
    cc = frame.groupby(["date", "market"]).agg(unc=("r2_cov", lambda x: 1 - x.mean()),
                                               gap=("served", "mean"), mk=("mkt", "mean")).reset_index()
    cc["g"] = cc.gap - cc.mk
    av["cell_spearman_uncovered_vs_gap"] = float(cc[["unc", "g"]].corr(method="spearman").iloc[0, 1])
    av["cells_with_any_uncovered"] = int((cc.unc > 0).sum())
    # harness reproduction
    harn = {}
    for v in ["r1", "r2", "c1"]:
        sc = json.loads((T7 / f"t7_{v}.score.json").read_text())
        tabs = sc["tables"]
        for t in tabs:
            if t.get("population") == "all_row" and t.get("stratum") == "from_20260823":
                harn[f"{v}|{t['group']}"] = t["candidate_minus_served"]["estimate"]
    (OUT / "stats.json").write_text(json.dumps({"res": res, "availability": av, "harness_from": harn}, indent=1, default=str))
    for g, *_ in BLOCKS:
        for v in ["r2", "r1", "c1"]:
            r = res[f"{v}-served|{g}|from_20260823"]
            print(v, g, round(r["est"], 6), "harness", round(harn.get(f"{v}|{g}", float('nan')), 6),
                  [round(x, 4) for x in r["W_ci"]], "date", [round(x, 4) for x in r["date_bb_ci"]],
                  "mkt", [round(x, 4) for x in r["market_bb_ci"]], "x", [round(x, 4) for x in r["crossed_bb_ci"]],
                  "mk-", r["mk_neg"], "wk-", f"{r['wk_neg']}/{r['wk_n']}", "lomo_max", round(r["lomo_max"], 4),
                  r["lomo_argmax"], "lowo_max", round(r["lowo_max"], 4), "z", round(r["z"], 2))
    for g, *_ in BLOCKS:
        for pair in ["r1-c1", "r2-c1", "c1m-served", "r2-c1m"]:
            r = res[f"{pair}|{g}|from_20260823"]
            rb = res[f"{pair}|{g}|before_20260823"]
            print(pair, g, round(r["est"], 5), [round(x, 5) for x in r["W_ci"]], "before", round(rb["est"], 5),
                  "mk-", r["mk_neg"])
    print(json.dumps(av, indent=1))


if __name__ == "__main__":
    main()
