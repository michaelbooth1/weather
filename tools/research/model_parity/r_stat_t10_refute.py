"""R-STAT-T10: statistics refuter for T10 (ECMWF IFS latest run). Development only.

Rebuilds T10's candidates (t10-r1, r2, r3, c1, c2) with the hunter's own code (no new rules), rebuilds
t3-r3 with T3's code, and recomputes every interval INDEPENDENTLY from C:\\swarm\\cache\\W.npy (own
ratio-of-sums bootstrap, not h.interval), plus:
  - LEAD conditions per block (own implementation of DESIGN section 1),
  - per-market and per-stratum signs, leave-one-market-out and leave-one-week-out,
  - paired marginals vs t3-r3, c1 (no source) and c2 (captured v2_mean),
  - availability-vs-outcome association (coverage, run age, which run),
  - an alternative date-only / market-only cluster bootstrap for robustness.
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r_stat_t10_refute
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t10_ecmwf_ifs as t10
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\refute-stat-t10")
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}
W = np.load(r"C:\swarm\cache\W.npy")
KEYS = [tuple(k) for k in json.loads(Path(r"C:\swarm\cache\W_keys.json").read_text(encoding="utf-8"))]
KIX = {k: i for i, k in enumerate(KEYS)}
RNG = np.random.default_rng(424242)


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def boot_ci(idx, a):
    sub = W[:, idx]
    den = sub.sum(1)
    b = (sub @ a) / den
    return float(a.mean()), [float(x) for x in np.quantile(b, [.025, .975])]


def alt_ci(dates, markets, a, n=2000):
    """Independent check: date-only and market-only cluster bootstrap (own RNG)."""
    out = {}
    for name, lab in (("date_only", dates), ("market_only", markets)):
        u, inv = np.unique(lab, return_inverse=True)
        sums = np.bincount(inv, weights=a, minlength=len(u))
        cnt = np.bincount(inv, minlength=len(u)).astype(float)
        draws = RNG.multinomial(len(u), np.ones(len(u)) / len(u), size=n).astype(float)
        b = (draws @ sums) / (draws @ cnt)
        out[name] = [float(x) for x in np.quantile(b, [.025, .975])]
    return out


def cells(fr, cols, g, stratum):
    lo, hi = GROUPS[g]
    m = fr.local_hour.between(lo, hi)
    if stratum != "pooled":
        m &= fr.stratum == stratum
    return fr[m].groupby(["date", "market"], sort=True)[cols].mean().reset_index()


def paired(fr, a, b, g, stratum, extra=False):
    c = cells(fr, [a, b], g, stratum)
    idx = np.array([KIX[(x, y)] for x, y in zip(c.date, c.market)])
    diff = (c[a] - c[b]).to_numpy()
    est, ci = boot_ci(idx, diff)
    pm = c.assign(d=diff).groupby("market").d.mean()
    out = {"estimate": est, "ci95": ci, "mkt_neg": int((pm < 0).sum()), "mkt_pos": int((pm > 0).sum()),
           "n_cells": int(len(c))}
    if extra:
        out["alt"] = alt_ci(c.date.to_numpy(), c.market.to_numpy(), diff)
        out["per_market"] = {k: round(float(v), 5) for k, v in pm.items()}
        # leave one market out / one ISO week out
        lomo = {}
        for mk in pm.index:
            k = c.market != mk
            e, ci2 = boot_ci(idx[k.to_numpy()], diff[k.to_numpy()])
            lomo[mk] = [round(e, 5), [round(x, 5) for x in ci2]]
        out["leave_one_market_out"] = lomo
        wk = pd.to_datetime(c.date).dt.isocalendar().week.to_numpy()
        lowo, perweek = {}, {}
        for w in np.unique(wk):
            k = wk != w
            e, ci2 = boot_ci(idx[k], diff[k])
            lowo[int(w)] = [round(e, 5), [round(x, 5) for x in ci2]]
            perweek[int(w)] = [round(float(diff[~k].mean()), 5), int((~k).sum())]
        out["leave_one_week_out"] = lowo
        out["per_week"] = perweek
        out["max_single_market_share_of_sum"] = float((pm * c.groupby("market").size()).min() / diff.sum()) \
            if diff.sum() < 0 else None
    return out


def lead(fr, cand, g):
    f = paired(fr, cand, "served", g, FROM, extra=True)
    b = paired(fr, cand, "served", g, BEFORE)
    gap = cells(fr, ["served", "market"], g, FROM)
    gap_est = float((gap.served - gap.market).mean())
    conds = {"ci_excl_0": f["ci95"][1] < 0,
             "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * gap_est,
             "strata": f["estimate"] < 0 and b["estimate"] < 0,
             "markets": f["mkt_neg"] >= 8}
    cls = "LEAD" if all(conds.values()) else ("WEAK" if f["estimate"] < 0 else
                                              ("HARM" if f["ci95"][0] > 0 else "NULL"))
    return {"class": cls, "conds": conds, "from": f, "before": {k: b[k] for k in ("estimate", "ci95", "mkt_neg")},
            "gap_from": gap_est, "five_pct_bar": -0.05 * gap_est}


def main():
    stop()
    OUT.mkdir(parents=True, exist_ok=True)
    d = h.data()
    s, bands = t10.snapshot_frame()
    idx = t10.load_ifs("measured")
    params, _ = t10.fit(idx)
    print("params", json.dumps(params), flush=True)
    cands, covs, ages, mus = {}, {}, {}, {}
    for rid, mode, pk in (("r1", "mix", "r1"), ("r2", "mix", "r2"), ("r3", "2t", "r3")):
        cands[rid], covs[rid], ages[rid], mus[rid], _ = t10.build(idx, s, bands, mode, params[pk], None)
    cands["c1"], covs["c1"], _, _, _ = t10.build(idx, s, bands, "mix", params["c1"], "c1", covs["r2"])
    cands["c2"], covs["c2"], _, _, _ = t10.build(idx, s, bands, "mix", params["r2"], "c2", covs["r2"])
    stop()
    t3c, _ = t3.build()
    cands["t3r3"] = t3c["t3-r3"]
    try:
        ref = pd.read_parquet(r"C:\swarm\out\refute-stat-t3\cand_r3.parquet")
        mm = cands["t3r3"].merge(ref, on=["row_key", "band_index"], how="outer", suffixes=("", "_ref"))
        t3_check = {"rows": len(mm), "max_abs_diff": float((mm.p - mm.p_ref).abs().max())}
    except Exception as e:  # noqa
        t3_check = {"error": str(e)}
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    fr["served"] = h._snapshot_mean(d, d.se_served)
    fr["market"] = d.snaps.market.to_numpy()  # placeholder overwritten below
    fr = fr.rename(columns={"market": "mkt"})
    fr["market"] = fr["mkt"]
    fr["market_loss"] = h._snapshot_mean(d, d.se_market)
    for k, c in cands.items():
        pc = h._candidate_vector(c, d, False)[0]
        fr[k] = h._snapshot_mean(d, (pc - d.y) ** 2)
    fr = fr.drop(columns=["mkt"])
    fr2 = fr.rename(columns={"market_loss": "mloss"})

    def lead2(cand, g):
        f = fr2.copy()
        f["market_brier"] = f["mloss"]
        return f
    # restructure for gap computation
    fr3 = fr.copy()
    fr3 = fr3.rename(columns={"market_loss": "mb"})
    res = {"HARNESS_SHA256": h.harness_sha256(), "params": params, "t3_check": t3_check,
           "coverage": {k: float(v.mean()) for k, v in covs.items()}}

    def gapcells(g):
        lo, hi = GROUPS[g]
        m = fr3.local_hour.between(lo, hi) & (fr3.stratum == FROM)
        c = fr3[m].groupby(["date", "market"], sort=True)[["served", "mb"]].mean()
        return float((c.served - c.mb).mean())

    def lead_cls(cand, g):
        f = paired(fr3, cand, "served", g, FROM, extra=True)
        b = paired(fr3, cand, "served", g, BEFORE)
        gap = gapcells(g)
        conds = {"ci_excl_0": f["ci95"][1] < 0,
                 "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * gap,
                 "strata": f["estimate"] < 0 and b["estimate"] < 0,
                 "markets": f["mkt_neg"] >= 8}
        cls = "LEAD" if all(conds.values()) else ("WEAK" if f["estimate"] < 0 else
                                                  ("HARM" if f["ci95"][0] > 0 else "NULL"))
        return {"class": cls, "conds": conds, "from": f,
                "before": {k: b[k] for k in ("estimate", "ci95", "mkt_neg")}, "gap_from": gap}

    res["lead_vs_served"] = {c: {g: lead_cls(c, g) for g in GROUPS} for c in ("r1", "r2", "r3", "c1", "c2", "t3r3")}
    stop()
    pairs = [("r2", "t3r3"), ("r1", "t3r3"), ("r2", "c1"), ("c1", "t3r3"), ("r2", "c2"), ("r2", "r3")]
    res["paired"] = {}
    for a, b in pairs:
        res["paired"][f"{a}-{b}"] = {}
        for g in GROUPS:
            res["paired"][f"{a}-{b}"][g] = {
                "from": paired(fr3, a, b, g, FROM, extra=(g in ("13-16", "17-23", "00-16", "06-09"))),
                "before": paired(fr3, a, b, g, BEFORE)}
    # availability vs outcome association (r2)
    cov = covs["r2"]
    blk = d.snaps.block.to_numpy()
    assoc = {}
    for g in ("00-05", "06-09", "10-12", "13-16", "17-23"):
        m = blk == g
        assoc[g] = {"coverage": float(cov[m].mean()),
                    "served_brier_covered": float(fr3.served[m & cov].mean()),
                    "served_brier_fallback": float(fr3.served[m & ~cov].mean()) if (m & ~cov).any() else None,
                    "n_fallback": int((m & ~cov).sum())}
        a = ages["r2"]
        mm = m & cov
        dd = (fr3.r2 - fr3.served).to_numpy()
        q = np.nanmedian(a[mm])
        assoc[g]["delta_young_run"] = float(dd[mm & (a <= q)].mean())
        assoc[g]["delta_old_run"] = float(dd[mm & (a > q)].mean())
        assoc[g]["served_young_run"] = float(fr3.served[mm & (a <= q)].mean())
        assoc[g]["served_old_run"] = float(fr3.served[mm & (a > q)].mean())
        assoc[g]["median_age_h"] = float(q)
    # fallback by date: any dates with systematically missing runs?
    fb = pd.DataFrame({"date": d.snaps.date, "cov": cov}).groupby("date")["cov"].mean()
    assoc["dates_coverage_below_95pct"] = {k: round(float(v), 3) for k, v in fb[fb < .95].items()}
    res["availability_association"] = assoc
    # mu vs outcome sanity: r2 - c1 mean abs mu difference per block (is IFS moving the centre at all?)
    cm = covs["r2"]
    fl = d.snaps.floor.to_numpy(float)
    res["mu_minus_floor_by_block"] = pd.Series((mus["r2"] - fl)[cm]).groupby(blk[cm]).describe().round(2).to_dict()
    (OUT / "result_stats.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    # compact print
    for c in ("r1", "r2", "r3", "c1"):
        print("==", c, {g: v["class"] for g, v in res["lead_vs_served"][c].items()})
    for g in GROUPS:
        v = res["lead_vs_served"]["r2"][g]
        f = v["from"]
        print(f"r2 {g}: {f['estimate']:+.5f} {f['ci95']} neg {f['mkt_neg']} before {v['before']['estimate']:+.5f}"
              f" gap {v['gap_from']:.4f} conds {v['conds']}")
    for k, v in res["paired"].items():
        for g in GROUPS:
            f = v[g]["from"]
            print(f"{k:10s} {g}: {f['estimate']:+.5f} [{f['ci95'][0]:+.5f},{f['ci95'][1]:+.5f}] "
                  f"{f['mkt_neg']}-/{f['mkt_pos']}+ before {v[g]['before']['estimate']:+.5f}")
    print("t3_check", t3_check, flush=True)


if __name__ == "__main__":
    main()
