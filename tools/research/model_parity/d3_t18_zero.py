"""D3 deep dive on the T18 family: zero-parameter form d3-z1 (rung x captured v2 Gaussian), sensitivities,
paired diagnostics and before-stratum power planning. Development only; POST-HOC; sizing, never evidence.

Registered in C:\\swarm\\registry.jsonl (agent d3) before the first score:
  d3-z1, d3-z1s60, d3-z1cov, d3-z1f, d3-pairs, d3-plan1 (texts in C:\\swarm\\out\\d3\\rules.json).
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.d3_t18_zero
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import logsumexp

from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3
from tools.research.model_parity import t5_nbh_latest as t5
from tools.research.model_parity import t18_emos as t

OUT = Path(r"C:\swarm\out\d3")
LADDER = Path(r"C:\swarm\out\ladder")
REG = Path(r"C:\swarm\registry.jsonl")
G = t.G
FROM, BEFORE = t.FROM, t.BEFORE
GROUPS = dict(t.GROUPS)
GROUPS.update({"13-14": (13, 14), "15-16": (15, 16)})
IDS = ("d3-z1", "d3-z1s60", "d3-z1cov", "d3-z1f", "d3-pairs", "d3-plan1")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def check_registry():
    rows = [json.loads(x) for x in REG.read_text(encoding="utf-8").splitlines() if x.strip()]
    reg = {r["id"]: r for r in rows if r.get("agent") == "d3"}
    for i in IDS:
        assert hashlib.sha256(reg[i]["text"].encode("utf-8")).hexdigest() == reg[i]["sha256"], i
    return {i: reg[i]["time_local"] for i in IDS}


def rise_dict():
    rr = pd.read_parquet(Path(r"C:\swarm\out\t18\rise_table.parquet"))
    rise = {}
    for (st, mo, H), g in rr.groupby(["station", "month", "hour"]):
        base, p = t3.smooth_pmf(g.rise.to_numpy())
        vals = base + np.arange(len(p))
        neg = vals < 0
        p0 = p[neg].sum()
        p = p[~neg].copy(); base = max(base, 0)
        p[0] += p0
        v = np.zeros(G)
        hi = min(len(p), G - base)
        v[base:base + hi] = p[:hi]
        rise[(st, mo, H)] = v / v.sum()
    return rise


def prior_for(s, R, rise):
    prior = np.full((len(s), G), np.nan)
    ok = np.isfinite(R).copy()
    for i, (st, mo, H) in enumerate(zip(s.station, s.month, s.local_hour)):
        if ok[i] and (st, mo, int(H)) in rise:
            prior[i] = rise[(st, mo, int(H))]
        else:
            ok[i] = False
    return prior, ok


def v2_pit(s, lag_min=0):
    cap = pd.to_datetime(s.captured_at_utc, utc=True, format="ISO8601")
    av = pd.to_datetime(s.v2_available_at, utc=True, format="ISO8601", errors="coerce") + pd.Timedelta(minutes=lag_min)
    use = (s.v2_mean.notna() & s.v2_stddev.notna() & av.notna() & (av <= cap)).to_numpy()
    h.assert_point_in_time(av[use], cap[use])
    mu = np.where(use, s.v2_mean.to_numpy(float), np.nan)
    sd = np.where(use, np.maximum(s.v2_stddev.to_numpy(float), 1.0), np.nan)
    return mu, sd, use


def z_pmf(R, prior, cov, mu, sd):
    """Zero-parameter rung x v2 likelihood. Rows with no v2 keep the rung pmf."""
    pm = np.full((len(R), G), np.nan)
    e = np.arange(G, dtype=float)
    idx = np.flatnonzero(cov)
    P = prior[idx]
    lp = np.log(np.where(P > 0, P, 1e-300))
    m = np.where(np.isfinite(mu[idx]), np.maximum(mu[idx], R[idx]), np.nan)
    sg = sd[idx]
    has = np.isfinite(m)
    z = np.zeros_like(lp)
    z[has] = (R[idx][has, None] + e[None, :] - m[has, None]) / sg[has, None]
    lg = lp - 0.5 * z * z
    pm[idx] = np.exp(lg - logsumexp(lg, axis=1, keepdims=True))
    return pm


def to_bands_R(s, bands, pm, cov, R):
    s2 = s.copy()
    s2["R"] = R
    return t.to_bands(s2, bands, pm, cov)


def mg1_candidate(snaps, bands, d):
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
    h.assert_point_in_time(v2av[ok], cap[ok])
    offs, nb = d.offsets, snaps.n_bands.to_numpy()
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    for i in np.flatnonzero(ok.to_numpy()):
        mu = float(snaps.v2_mean.iat[i]); sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
        B = math.floor(float(snaps.floor.iat[i]) + .5)
        o, n = offs[i], nb[i]
        p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() > 0:
            p_out[o:o + n] = p / p.sum()
    cov = ~np.isnan(p_out)
    return bands.loc[cov, ["row_key", "band_index"]].assign(p=p_out[cov])


def snap_brier(cand, d):
    pc, use, _ = h._candidate_vector(cand, d, False)
    return np.add.reduceat((pc - d.y) ** 2, d.offsets) / d.snaps.n_bands.to_numpy()


def paired_tables(B, pairs, d):
    W = np.load(Path(r"C:\swarm\cache\W.npy"))
    keys = [tuple(k) for k in json.loads(Path(r"C:\swarm\cache\W_keys.json").read_text())]
    kidx = {k: i for i, k in enumerate(keys)}
    sn = d.snaps
    f = pd.DataFrame({"date": sn.date.to_numpy(), "market": sn.market.to_numpy(),
                      "stratum": sn.stratum.to_numpy(), "lh": sn.local_hour.to_numpy()})
    for k, v in B.items():
        f[k] = v
    out = {}
    for g, (lo, hi) in GROUPS.items():
        out[g] = {}
        for st in (FROM, BEFORE):
            msk = (f.lh >= lo) & (f.lh <= hi) & (f.stratum == st)
            c = f[msk].groupby(["date", "market"], sort=True)[list(B)].mean().reset_index()
            ix = np.array([kidx[(dd, mk)] for dd, mk in zip(c.date, c.market)])
            sub = W[:, ix]
            res = {}
            for x, z in pairs:
                dv = (c[x] - c[z]).to_numpy()
                bo = (sub @ dv) / sub.sum(1)
                pm = c.assign(dv=dv).groupby("market").dv.mean()
                res[f"{x} - {z}"] = {"est": float(dv.mean()), "ci95": np.quantile(bo, [.025, .975]).tolist(),
                                     "markets_neg": int((pm < 0).sum()), "markets": int(len(pm))}
            out[g][st] = res
    return out


def plan(dz, d, groups=("00-16", "17-23")):
    """Fixed-market date-clustered power on BEFORE-stratum cells (d3-plan1)."""
    rng = np.random.default_rng(20261004)
    sn = d.snaps
    f = pd.DataFrame({"date": sn.date.to_numpy(), "market": sn.market.to_numpy(),
                      "stratum": sn.stratum.to_numpy(), "lh": sn.local_hour.to_numpy(), "dv": dz})
    res = {}
    for g in groups:
        lo, hi = GROUPS[g]
        c = f[(f.lh >= lo) & (f.lh <= hi) & (f.stratum == BEFORE)].groupby(["date", "market"]).dv.mean().reset_index()
        est = float(c.dv.mean())
        dates = sorted(c.date.unique())
        mk = sorted(c.market.unique())
        # market-cluster floor of the crossed estimand: SE from market means only
        mm = c.groupby("market").dv.mean()
        se_mkt = float(mm.std(ddof=1) / math.sqrt(len(mm)))
        effects = {"half_before": abs(est) / 2, "81a_C1": 0.006672, "full_before": abs(est)}
        tab = {}
        for ename, e in effects.items():
            cc = c.copy()
            cc["dv"] = cc.dv - est - e   # keep market structure, re-centre to -e
            by_date = {dd: gg for dd, gg in cc.groupby("date")}
            row = {}
            for N in (20, 30, 45, 60, 90):
                p_int = 0; p_joint = 0; sims = 2000
                for _ in range(sims):
                    pick = rng.choice(dates, size=N, replace=True)
                    parts = [by_date[x] for x in pick]
                    S = np.array([p.dv.sum() for p in parts]); n = np.array([len(p) for p in parts])
                    tot = n.sum(); m_ = S.sum() / tot
                    se = math.sqrt(N / (N - 1) * ((S - n * m_) ** 2).sum()) / tot
                    ok = (m_ + 1.959964 * se) < 0
                    allc = pd.concat(parts)
                    neg = int((allc.groupby("market").dv.mean() < 0).sum())
                    p_int += ok; p_joint += ok and neg >= 8
                row[N] = {"interval": p_int / sims, "joint_8of11": p_joint / sims}
            tab[ename] = {"effect": e, "power": row}
        res[g] = {"before_estimate": est, "n_dates": len(dates), "n_markets": len(mk),
                  "per_market_before": mm.round(5).to_dict(),
                  "market_cluster_se": se_mkt, "crossed_mde80_floor_unlimited_dates": 2.8016 * se_mkt,
                  "plan": tab}
    return res


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    regt = check_registry()
    OUT.mkdir(parents=True, exist_ok=True)
    log("inputs")
    s, bands, prior, src, meta = t.build_inputs()
    d = h.data()
    rise = rise_dict()
    R = s.R.to_numpy(float)
    cov = s.covered.to_numpy()
    mu, sd, use = v2_pit(s)
    # d3-z1
    pz = z_pmf(R, prior, cov, mu, sd)
    cands = {"d3-z1": t.to_bands(s, bands, pz, cov)}
    # d3-z1s60
    m60 = t3.load_metar(60)
    today60 = t3.pit_asof(s, m60, "today")
    R60 = today60["cummax"].reindex(s.row_key).to_numpy(float)
    pr60, cov60 = prior_for(s, R60, rise)
    mu60, sd60, use60 = v2_pit(s, 60)
    cands["d3-z1s60"] = to_bands_R(s, bands, z_pmf(R60, pr60, cov60, mu60, sd60), cov60, R60)
    # d3-z1cov
    dates = sorted(s.date.unique())
    drop = set(dates[::5])
    dm = s.date.isin(drop).to_numpy()
    muc = np.where(dm, np.nan, mu); sdc = np.where(dm, np.nan, sd)
    cands["d3-z1cov"] = t.to_bands(s, bands, z_pmf(R, prior, cov, muc, sdc), cov)
    # d3-z1f
    Rf = np.floor(s.floor.to_numpy(float) + 0.5)
    prf, covf = prior_for(s, Rf, rise)
    cands["d3-z1f"] = to_bands_R(s, bands, z_pmf(Rf, prf, covf, mu, sd), covf, Rf)
    # comparators
    run = json.loads(Path(r"C:\swarm\out\t18\t18_run.json").read_text(encoding="utf-8"))
    ctl = json.loads(Path(r"C:\swarm\out\t18\t18_controls.json").read_text(encoding="utf-8"))
    ch = run["chosen"]
    th1 = np.r_[run["theta_r1"]["a"], [run["theta_r1"][f"b_{k}"] for k in ch], np.log(run["theta_r1"]["sigma"])]
    thc1 = np.r_[ctl["theta_c1"]["a"], ctl["theta_c1"]["b_v2_mean"], np.log(ctl["theta_c1"]["sigma"])]
    mall = t.Model(s, prior, src, cov)
    p1 = np.full((len(s), G), np.nan); pc1 = p1.copy(); prr = p1.copy()
    p1[cov] = mall.pmf(th1, ch); pc1[cov] = mall.pmf(thc1, ["v2_mean"]); prr[cov] = prior[cov]
    comp = {"t18-r1": t.to_bands(s, bands, p1, cov), "t18-c1": t.to_bands(s, bands, pc1, cov),
            "t3-r3": t.to_bands(s, bands, prr, cov)}
    snaps_h, bands_h = h.candidate_inputs()
    comp["mg1"] = mg1_candidate(snaps_h, bands_h, d)
    # scores
    results = {}
    names = {"d3-z1": "d3_z1_rung_x_v2_zero", "d3-z1s60": "d3_z1s60_lag60", "d3-z1cov": "d3_z1cov_v2_drop_1in5",
             "d3-z1f": "d3_z1f_floor_anchor"}
    for k, nm in names.items():
        res = h.score(cands[k], name=nm)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"d3 leakage suspect {nm} {res['leakage_suspect_groups']}\n")
            raise SystemExit("LEAKAGE SUSPECT " + nm)
        h.save(res, OUT)
        (OUT / f"{nm}.md").write_text(h.markdown(res), encoding="utf-8")
        results[k] = res
        print(h.markdown(res), flush=True)
    # paired
    Bz = {k: snap_brier(v, d) for k, v in {**cands, **comp}.items()}
    Bz["served"] = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
    sv = np.load(LADDER / "snapb_served.npy")
    align = float(np.max(np.abs(sv - Bz["served"])))
    assert align < 1e-12, align
    Bz["ladder-r1"] = np.load(LADDER / "snapb_ladder-r1.npy")
    Bz["ladder-r2"] = np.load(LADDER / "snapb_ladder-r2.npy")
    pairs = [("d3-z1", "served"), ("d3-z1", "t3-r3"), ("d3-z1", "t18-r1"), ("d3-z1", "t18-c1"), ("d3-z1", "mg1"),
             ("d3-z1", "ladder-r1"), ("d3-z1", "ladder-r2"), ("d3-z1s60", "d3-z1"), ("d3-z1cov", "d3-z1"),
             ("d3-z1f", "d3-z1"), ("d3-z1f", "served"), ("mg1", "served"), ("t18-r1", "served")]
    pt = paired_tables(Bz, pairs, d)
    log("plan")
    pl = plan(Bz["d3-z1"] - Bz["served"], d)
    # coverage facts
    hr = s.local_hour.to_numpy()
    covf_ = {"z1_cov": float(cov.mean()), "z1_v2_used": float((cov & use).mean()),
             "z1_cov_00_16": float(cov[hr <= 16].mean()), "z1_cov_17_23": float(cov[hr >= 17].mean()),
             "z1s60_cov": float(cov60.mean()), "z1s60_v2_used": float((cov60 & use60).mean()),
             "z1cov_dates_dropped": sorted(drop), "z1f_cov": float(covf.mean()),
             "anchor_R_vs_floorbucket": {
                 "both": int((np.isfinite(R) & np.isfinite(Rf)).sum()),
                 "equal": int((np.isfinite(R) & np.isfinite(Rf) & (R == Rf)).sum()),
                 "floor_gt_R": int((np.isfinite(R) & np.isfinite(Rf) & (Rf > R)).sum()),
                 "floor_lt_R": int((np.isfinite(R) & np.isfinite(Rf) & (Rf < R)).sum())}}
    out = {"agent": "d3", "HARNESS_SHA256": h.harness_sha256(), "registered": regt, "served_alignment_maxabs": align,
           "coverage": covf_, "classes": {k: results[k]["classes"] for k in results},
           "tables": {k: {g: {st: h.table_lookup(results[k], g, st, "all_row") for st in (FROM, BEFORE)}
                          for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")} for k in results},
           "tail": {k: results[k]["tail"] for k in results},
           "paired": pt, "plan": pl}
    (OUT / "d3_run.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
