"""R-STAT-T8: statistics refuter for T8 (HRRR latest run, Open-Meteo Single-Runs). Development only.

Rebuilds T8's candidates (t8-r1..r4, c1, c2, d1 at +5 h) with the hunter's own code (no new rules),
rebuilds t3-r3 with T3's code, and recomputes every interval INDEPENDENTLY from C:\\swarm\\cache\\W.npy
(own ratio-of-sums over market-day cells, not h.interval), plus:
  - LEAD conditions per block (own implementation of DESIGN section 1),
  - per-market / per-stratum signs, leave-one-market-out and leave-one-ISO-week-out,
  - date-only and market-only cluster bootstraps as an alternative interval,
  - paired marginals vs t3-r3 (rung), c1 (no source), c2 (captured hrrr_high), r1,
  - availability-vs-outcome association (coverage, run age, fallback served Brier).
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r_stat_t8_refute
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t8_hrrr_latest as t8
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\refute-stat-t8")
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}
W = np.load(r"C:\swarm\cache\W.npy")
KEYS = [tuple(k) for k in json.loads(Path(r"C:\swarm\cache\W_keys.json").read_text(encoding="utf-8"))]
KIX = {k: i for i, k in enumerate(KEYS)}
RNG = np.random.default_rng(880088)


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def boot_ci(idx, a):
    sub = W[:, idx]
    b = (sub @ a) / sub.sum(1)
    return float(a.mean()), [float(x) for x in np.quantile(b, [.025, .975])]


def alt_ci(dates, markets, a, n=2000):
    out = {}
    for name, lab in (("date_only", dates), ("market_only", markets)):
        u, inv = np.unique(lab, return_inverse=True)
        sums = np.bincount(inv, weights=a, minlength=len(u))
        cnt = np.bincount(inv, minlength=len(u)).astype(float)
        draws = RNG.multinomial(len(u), np.ones(len(u)) / len(u), size=n).astype(float)
        b = (draws @ sums) / (draws @ cnt)
        out[name] = [float(x) for x in np.quantile(b, [.025, .975])]
    return out


def cells(fr, cols, g, stratum, mask=None):
    lo, hi = GROUPS[g]
    m = fr.local_hour.between(lo, hi)
    if stratum != "pooled":
        m &= fr.stratum == stratum
    if mask is not None:
        m &= mask
    return fr[m].groupby(["date", "market"], sort=True)[cols].mean().reset_index()


def paired(fr, a, b, g, stratum, extra=False, mask=None):
    c = cells(fr, [a, b], g, stratum, mask)
    idx = np.array([KIX[(x, y)] for x, y in zip(c.date, c.market)])
    diff = (c[a] - c[b]).to_numpy()
    est, ci = boot_ci(idx, diff)
    pm = c.assign(d=diff).groupby("market").d.mean()
    out = {"estimate": est, "ci95": ci, "mkt_neg": int((pm < 0).sum()), "mkt_pos": int((pm > 0).sum()),
           "n_cells": int(len(c))}
    if extra:
        out["alt"] = alt_ci(c.date.to_numpy(), c.market.to_numpy(), diff)
        out["per_market"] = {k: round(float(v), 5) for k, v in pm.items()}
        lomo = {}
        for mk in pm.index:
            k = (c.market != mk).to_numpy()
            e, ci2 = boot_ci(idx[k], diff[k])
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
        tot = diff.sum()
        contrib = c.assign(d=diff).groupby("market").d.sum()
        out["largest_market_share_of_total"] = float(contrib.min() / tot) if tot < 0 else None
        out["largest_market"] = str(contrib.idxmin())
    return out


def main():
    stop()
    OUT.mkdir(parents=True, exist_ok=True)
    d = h.data()
    s, bands = t8.snapshot_frame()
    idx3 = t8.load_hrrr(3)
    metar = t8.load_metar_fit()
    params, fit_stats = t8.fit_all(idx3, metar)
    cands, infos = {}, []
    for rule in ("r1", "r2", "r3", "r4", "c1", "c2"):
        stop()
        prm = params.get("r2") if rule == "c2" else params.get(rule)
        cands[rule], _ = t8.build_candidate(rule, idx3, s, bands, prm, infos if rule == "r1" else None)
    idx5 = t8.load_hrrr(5)
    for rule in ("r1", "r2"):
        stop()
        cands["d1" + rule], _ = t8.build_candidate(rule, idx5, s, bands, params.get(rule))
    t3c, _ = t3.build()
    cands["t3r3"] = t3c["t3-r3"]
    try:
        ref = pd.read_parquet(r"C:\swarm\out\refute-stat-t3\cand_r3.parquet")
        mm = cands["t3r3"].merge(ref, on=["row_key", "band_index"], how="outer", suffixes=("", "_ref"))
        t3_check = {"rows": len(mm), "max_abs_diff": float((mm.p - mm.p_ref).abs().max())}
    except Exception as e:  # noqa
        t3_check = {"error": str(e)}
    stop()
    # independent snapshot-level Brier (not via h.score)
    y = d.y
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    fr["served"] = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
    fr["mb"] = np.add.reduceat(d.se_market, d.offsets) / d.snaps.n_bands.to_numpy()
    for k, c in cands.items():
        pc = h._candidate_vector(c, d, False)[0]
        fr[k] = np.add.reduceat((pc - y) ** 2, d.offsets) / d.snaps.n_bands.to_numpy()
    assert (fr.date <= "2026-09-29").all()

    def gap(g):
        c = cells(fr, ["served", "mb"], g, FROM)
        return float((c.served - c.mb).mean())

    def lead_cls(cand, g):
        f = paired(fr, cand, "served", g, FROM, extra=True)
        b = paired(fr, cand, "served", g, BEFORE)
        gp = gap(g)
        conds = {"ci_excl_0": f["ci95"][1] < 0,
                 "size": f["estimate"] <= -0.0133 or f["estimate"] <= -0.05 * gp,
                 "strata": f["estimate"] < 0 and b["estimate"] < 0,
                 "markets": f["mkt_neg"] >= 8}
        cls = "LEAD" if all(conds.values()) else ("WEAK" if f["estimate"] < 0 else
                                                  ("HARM" if f["ci95"][0] > 0 else "NULL"))
        return {"class": cls, "conds": conds, "from": f,
                "before": {k: b[k] for k in ("estimate", "ci95", "mkt_neg")}, "gap_from": gp}

    res = {"HARNESS_SHA256": h.harness_sha256(), "t3_check": t3_check, "fit_n": fit_stats.get("n_total")}
    res["lead_vs_served"] = {c: {g: lead_cls(c, g) for g in GROUPS} for c in cands}
    stop()
    pairs = [("r1", "t3r3"), ("r2", "t3r3"), ("r3", "t3r3"), ("r4", "t3r3"), ("r1", "c1"), ("r2", "c1"),
             ("c1", "t3r3"), ("r2", "c2"), ("r3", "c2"), ("r4", "c2"), ("c2", "t3r3"), ("r3", "r2"),
             ("r4", "r2"), ("r2", "r1"), ("d1r2", "c2"), ("d1r2", "t3r3")]
    res["paired"] = {}
    for a, b in pairs:
        res["paired"][f"{a}-{b}"] = {g: {"from": paired(fr, a, b, g, FROM,
                                                        extra=(g in ("06-09", "13-16", "17-23", "00-16"))),
                                         "before": paired(fr, a, b, g, BEFORE)} for g in GROUPS}
    # availability vs outcome association
    cov = np.array([x is not None for x in infos])
    ages = np.array([x["age_h"] if x else np.nan for x in infos])
    runhr = np.array([pd.Timestamp(int(x["run"]), tz="UTC").hour if x else -1 for x in infos])
    blk = d.snaps.block.to_numpy()
    assoc = {}
    for g in ("00-05", "06-09", "10-12", "13-16", "17-23"):
        m = blk == g
        a = {"coverage": float(cov[m].mean()), "n_fallback": int((m & ~cov).sum()),
             "served_brier_covered": float(fr.served[m & cov].mean()),
             "served_brier_fallback": float(fr.served[m & ~cov].mean()) if (m & ~cov).any() else None}
        mm_ = m & cov
        q = float(np.nanmedian(ages[mm_]))
        for rid in ("r1", "r2", "c2"):
            dd = (fr[rid] - fr.served).to_numpy()
            a[f"{rid}_delta_young"] = float(dd[mm_ & (ages <= q)].mean())
            a[f"{rid}_delta_old"] = float(dd[mm_ & (ages > q)].mean())
        a["served_young"] = float(fr.served[mm_ & (ages <= q)].mean())
        a["served_old"] = float(fr.served[mm_ & (ages > q)].mean())
        a["median_age_h"] = q
        dd = (fr["r2"] - fr.served).to_numpy()
        a["r2_delta_by_run_hour"] = {int(r): [round(float(dd[mm_ & (runhr == r)].mean()), 5),
                                              int((mm_ & (runhr == r)).sum())]
                                     for r in np.unique(runhr[mm_])}
        assoc[g] = a
    fb = pd.DataFrame({"date": d.snaps.date, "cov": cov}).groupby("date")["cov"].mean()
    assoc["dates_coverage_below_95pct"] = {k: round(float(v), 3) for k, v in fb[fb < .95].items()}
    res["availability_association"] = assoc
    (OUT / "result_stats.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    for c in cands:
        print("==", c, {g: v["class"] for g, v in res["lead_vs_served"][c].items()})
    for c, gs in (("r1", ("17-23", "06-09")), ("r2", ("06-09", "17-23")), ("r3", ("06-09",)), ("r4", ("06-09",)),
                  ("c1", ("17-23",)), ("c2", ("06-09",)), ("d1r1", ("17-23", "06-09")), ("d1r2", ("06-09",))):
        for g in gs:
            v = res["lead_vs_served"][c][g]
            f = v["from"]
            print(f"{c} {g}: {f['estimate']:+.5f} [{f['ci95'][0]:+.5f},{f['ci95'][1]:+.5f}] neg {f['mkt_neg']} "
                  f"before {v['before']['estimate']:+.5f} gap {v['gap_from']:.4f} {v['class']} {v['conds']} "
                  f"alt {f['alt']} bigmkt {f['largest_market']} {f['largest_market_share_of_total']}")
            print("   LOMO", f["leave_one_market_out"])
            print("   LOWO", f["leave_one_week_out"], "perweek", f["per_week"])
    for k, v in res["paired"].items():
        for g in GROUPS:
            f = v[g]["from"]
            print(f"{k:10s} {g}: {f['estimate']:+.5f} [{f['ci95'][0]:+.5f},{f['ci95'][1]:+.5f}] "
                  f"{f['mkt_neg']}-/{f['mkt_pos']}+ before {v[g]['before']['estimate']:+.5f}")
    print("assoc", json.dumps(assoc, default=str)[:4000])
    print("t3_check", t3_check, flush=True)


if __name__ == "__main__":
    main()
