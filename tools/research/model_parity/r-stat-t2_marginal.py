"""R-STAT-T2 part 2: paired marginal gain of t2-r1 over the t3-r3 rung (floor + remaining rise),
scored on identical rows with the same floor, intervals from W.npy. Also a per-date coverage audit.
Development only; registers nothing (both candidates are already registered rules).

Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-stat-t2_marginal.py
(requires r-stat-t2_refute.py to have saved t2_r1_p_unfloored.npy first)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t3_baselines as t3  # noqa: E402

OUT = Path(r"C:\swarm\out\refute-stat-t2")
CACHE = Path(r"C:\swarm\cache")
FROM, BEFORE = "from_20260823", "before_20260823"
BLOCKS = {"13-16": (13, 16), "17-23": (17, 23), "00-16": (0, 16), "all": (0, 23)}


def floored_vector(p_un, full_b, full_s):
    n = full_s.n_bands.to_numpy()
    sob = np.repeat(np.arange(len(full_s)), n)
    given = ~np.isnan(p_un)
    n_given = np.bincount(sob, weights=given, minlength=len(full_s))
    provided = n_given == n
    has_floor = full_s.floor.notna().to_numpy()
    pc = np.where(given, p_un, 0.0)
    pc[full_b.floor_impossible.to_numpy(bool)] = 0.0
    tot = np.bincount(sob, weights=pc, minlength=len(full_s))
    use = provided & has_floor & (tot > 0)
    pc = np.where(use[sob], pc / np.where(tot > 0, tot, 1.0)[sob], full_b.p_served.to_numpy(float))
    return pc, use


def main():
    full_b = pd.read_parquet(CACHE / "bands.parquet")
    full_s = pd.read_parquet(CACHE / "snapshots.parquet")
    n = full_s.n_bands.to_numpy()
    off = np.concatenate([[0], np.cumsum(n)[:-1]])
    y = full_b.is_winner.to_numpy(float)
    p2_un = np.load(OUT / "t2_r1_p_unfloored.npy")
    cands, meta = t3.build()
    c3 = cands["t3-r3"]
    pos = pd.Series(np.arange(len(full_s)), index=full_s.row_key).reindex(c3.row_key.to_numpy()).to_numpy().astype(int)
    p3_un = np.full(len(full_b), np.nan)
    p3_un[off[pos] + c3.band_index.to_numpy(int)] = c3.p.to_numpy(float)
    pc2, use2 = floored_vector(p2_un, full_b, full_s)
    pc3, use3 = floored_vector(p3_un, full_b, full_s)
    smean = lambda v: np.add.reduceat(v, off) / n
    f = full_s[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    f["served"] = smean((full_b.p_served.to_numpy(float) - y) ** 2)
    f["t2"] = smean((pc2 - y) ** 2)
    f["t3"] = smean((pc3 - y) ** 2)
    f["use2"], f["use3"] = use2, use3
    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text())]
    kidx = {k: i for i, k in enumerate(keys)}
    out = {"t3_r3_coverage": meta["coverage"]["t3-r3"], "t2_covered": int(use2.sum()), "t3_covered": int(use3.sum()),
           "both_covered": int((use2 & use3).sum())}
    for blk, (lo, hi) in BLOCKS.items():
        res = {}
        for stratum in (FROM, BEFORE):
            m = f.local_hour.between(lo, hi) & (f.stratum == stratum)
            c = f[m].groupby(["date", "market"], sort=True)[["served", "t2", "t3"]].mean().reset_index()
            idx = np.array([kidx[(d, mk)] for d, mk in zip(c.date, c.market)])
            sub = W[:, idx]
            def ci(a):
                b = (sub @ a) / sub.sum(1)
                return [float(a.mean()), *np.quantile(b, [.025, .975]).tolist()]
            d23 = (c.t2 - c.t3).to_numpy()
            pm = c.assign(d=d23).groupby("market").d.mean()
            res[stratum] = {"t2_minus_served": ci((c.t2 - c.served).to_numpy()),
                            "t3_minus_served": ci((c.t3 - c.served).to_numpy()),
                            "t2_minus_t3_paired": ci(d23),
                            "t2_minus_t3_markets_negative": int((pm < 0).sum()),
                            "t2_minus_t3_per_market": pm.round(6).to_dict(),
                            "market_days": int(len(c))}
        out[blk] = res
    # per-date coverage audit for the from stratum 17-23 and 13-16
    aud = {}
    for blk, (lo, hi) in (("17-23", (17, 23)), ("13-16", (13, 16))):
        m = f.local_hour.between(lo, hi) & (f.stratum == FROM)
        g = f[m].groupby("date").agg(n=("use2", "size"), cov=("use2", "mean"))
        aud[blk] = {"dates_with_coverage_below_0.9": g[g["cov"] < .9]["cov"].round(3).to_dict(),
                    "min_date_coverage": float(g["cov"].min()), "mean_date_coverage": float(g["cov"].mean())}
        gm = f[m].groupby("market").use2.mean()
        aud[blk]["per_market_coverage"] = gm.round(3).to_dict()
    out["coverage_audit_from"] = aud
    (OUT / "marginal_vs_t3r3.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
