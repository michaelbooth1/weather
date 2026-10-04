"""D1 deep dive on family T5 (NBH latest cycle, remaining-hours max). Development only.

Registry ids (appended before the first score): d1-t5-plan1 (planning diagnostic), d1-t5-s1 (capture
sensitivity diagnostic), d1-t5-pc1 (POST-HOC combined candidate, sizing only, never evidence).
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\d1_t5_prereg.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t5_nbh_latest as t5  # noqa: E402

OUT = Path(r"C:\swarm\out\d1")
OUT.mkdir(parents=True, exist_ok=True)
STOP = Path(r"C:\swarm\STOP")
if STOP.exists():
    sys.exit("STOP present")
BEFORE, FROM = "before_20260823", "from_20260823"
DRAWS, SEED, ALPHA = 2000, 20261004, 0.025
G = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "13-14": (13, 14),
     "15-16": (15, 16), "17-23": (17, 23), "00-16": (0, 16), "all": (0, 23)}

d = h.data()
s, bands = t5.snapshot_frame()
assert (d.snaps.row_key.to_numpy() == s.row_key.to_numpy()).all()
assert (d.snaps.date.to_numpy() <= "2026-09-29").all()
NB = d.snaps.n_bands.to_numpy()
LH = d.snaps.local_hour.to_numpy()
STR = d.snaps.stratum.to_numpy()
served_b = np.add.reduceat(d.se_served, d.offsets) / NB
market_b = np.add.reduceat(d.se_market, d.offsets) / NB


def snap_brier(cand):
    pc, use, _ = h._candidate_vector(cand, d, False)
    return np.add.reduceat((pc - d.y) ** 2, d.offsets) / NB, pc, use


def build_c1():
    snaps, _ = h.candidate_inputs()
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    v2av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = (snaps.v2_mean.notna() & snaps.v2_stddev.notna() & v2av.notna() & (v2av <= cap) & snaps.floor.notna())
    h.assert_point_in_time(v2av[ok], cap[ok])
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    for i in np.flatnonzero(ok.to_numpy()):
        mu = float(snaps.v2_mean.iat[i])
        sig = max(float(snaps.v2_stddev.iat[i]), t5.SIG_MIN)
        B = math.floor(float(snaps.floor.iat[i]) + .5)
        o, n = d.offsets[i], NB[i]
        p = t5.band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() > 0:
            p_out[o:o + n] = p / p.sum()
    return p_out


def cand_from(p_out):
    cov = ~np.isnan(p_out)
    return bands.loc[cov, ["row_key", "band_index"]].assign(p=p_out[cov])


def p_of(cand):
    out = np.full(len(bands), np.nan)
    pos = pd.Series(np.arange(len(bands)), index=pd.MultiIndex.from_arrays([bands.row_key, bands.band_index]))
    out[pos.loc[list(zip(cand.row_key, cand.band_index))].to_numpy()] = cand.p.to_numpy()
    return out


def cells(vals, group, stratum):
    lo, hi = G[group]
    m = (LH >= lo) & (LH <= hi)
    if stratum != "pooled":
        m &= STR == stratum
    f = pd.DataFrame({"date": d.snaps.date[m].to_numpy(), "market": d.snaps.market[m].to_numpy(),
                      **{k: v[m] for k, v in vals.items()}})
    c = f.groupby(["date", "market"], sort=True).mean().reset_index()
    idx = np.array([d.key_index[(x, y)] for x, y in zip(c.date, c.market)])
    return c, idx


def paired(a, b, group, stratum=FROM):
    c, idx = cells({"a": a, "b": b}, group, stratum)
    dl = (c.a - c.b).to_numpy()
    iv = h.interval(idx, dl)
    pm = c.assign(dl=dl).groupby("market").dl.mean()
    return {"estimate": round(iv["estimate"], 6), "ci95": [round(x, 6) for x in iv["ci95"]],
            "mkts_neg": int((pm < 0).sum()), "mkts": int(len(pm))}


def ptab(a, b, groups=("00-05", "06-09", "10-12", "13-14", "15-16", "13-16", "17-23", "00-16", "all")):
    return {g: {"from": paired(a, b, g, FROM), "before": paired(a, b, g, BEFORE)["estimate"]} for g in groups}


def summ(res):
    out = {}
    for g in res["classes"]:
        t = h.table_lookup(res, g, FROM, "all_row")
        out[g] = {"class": res["classes"][g]["class"],
                  "cs": [round(t["candidate_minus_served"]["estimate"], 6)] +
                        [round(x, 6) for x in t["candidate_minus_served"]["ci95"]],
                  "cm": [round(t["candidate_minus_market"]["estimate"], 6)] +
                        [round(x, 6) for x in t["candidate_minus_market"]["ci95"]],
                  "gap_closed": t.get("gap_closed_share")}
    return out


R = {"HARNESS_SHA256": h.harness_sha256(), "development": True, "rows_after_20260929": 0,
     "registry_ids": ["d1-t5-plan1", "d1-t5-s1", "d1-t5-pc1"]}

# ---------------------------------------------------------------- base candidates
idx0 = t5.load_nbh()
cand_t5, ages, mus, reasons = t5.build_candidate(idx0, s, bands)
t5_b, p_t5, use_t5 = snap_brier(cand_t5)
p_c1 = build_c1()
c1_b, _, use_c1 = snap_brier(cand_from(p_c1))
r2_b = np.load(r"C:\swarm\out\ladder\snapb_ladder-r2.npy")
assert r2_b.shape == served_b.shape
R["reproduce"] = {"t5_00-16": paired(t5_b, served_b, "00-16"), "t5_17-23": paired(t5_b, served_b, "17-23"),
                  "c1_00-16": paired(c1_b, served_b, "00-16"), "t5_minus_c1_00-16": paired(t5_b, c1_b, "00-16"),
                  "coverage_t5": float(use_t5.mean()), "coverage_c1": float(use_c1.mean()), "reasons_t5": reasons}
print(json.dumps(R["reproduce"]), flush=True)
R["t5_minus_served"] = ptab(t5_b, served_b)
R["t5_minus_c1"] = ptab(t5_b, c1_b)
R["t5_minus_ladder_r2"] = ptab(t5_b, r2_b)

# ---------------------------------------------------------------- d1-t5-pc1 POST-HOC pool
if STOP.exists():
    sys.exit("STOP present")
pool = np.where(np.isnan(p_t5), p_c1, np.where(np.isnan(p_c1), p_t5, 0.5 * p_t5 + 0.5 * p_c1))
pool_res = h.score(cand_from(pool), name="d1_t5_pc1_pool")
assert not pool_res.get("leakage_suspect_groups"), pool_res.get("leakage_suspect_groups")
h.save(pool_res, OUT)
pool_b, _, _ = snap_brier(cand_from(pool))
R["pc1"] = {"vs_served": summ(pool_res), "minus_c1": ptab(pool_b, c1_b), "minus_ladder_r2": ptab(pool_b, r2_b)}
print("pc1", json.dumps(R["pc1"]["minus_c1"]["00-16"]), flush=True)

MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
# ---------------------------------------------------------------- d1-t5-s1 capture sensitivity
if MODE == "full" and STOP.exists():
    sys.exit("STOP present")
all_cycles = sorted({x["cycle"] for si in idx0.values() for x in si.c})
rng = np.random.default_rng(SEED)
u = dict(zip(all_cycles, rng.random(len(all_cycles))))


def subset(index, keep):
    return {st: t5.StationIndex([x for x in si.c if keep(x["cycle"])]) for st, si in index.items()}


variants = {} if MODE != "full" else {
    "drop10": subset(idx0, lambda c: u[c] >= .10),
    "drop25": subset(idx0, lambda c: u[c] >= .25),
    "drop50": subset(idx0, lambda c: u[c] >= .50),
    "every3h": subset(idx0, lambda c: c.hour % 3 == 0),
    "every6h": subset(idx0, lambda c: c.hour % 6 == 0),
    "lag60_drop25": subset(t5.load_nbh(extra_lag_min=60), lambda c: u[c] >= .25),
}
R["s1"] = {}
for name, ix in (variants.items() if MODE == "full" else []):
    if STOP.exists():
        sys.exit("STOP present")
    cand, ag, _, rs = t5.build_candidate(ix, s, bands)
    res = h.score(cand, name=f"d1_t5_s1_{name}")
    assert not res.get("leakage_suspect_groups"), res.get("leakage_suspect_groups")
    h.save(res, OUT)
    vb, _, use = snap_brier(cand)
    R["s1"][name] = {"coverage": float(use.mean()), "reasons": rs,
                     "median_age_h_00_16": float(np.nanmedian(ag[LH <= 16])),
                     "vs_served": summ(res),
                     "minus_c1": {g: paired(vb, c1_b, g) for g in ("00-16", "13-16", "17-23")}}
    print(name, R["s1"][name]["coverage"], json.dumps(R["s1"][name]["vs_served"]["00-16"]),
          json.dumps(R["s1"][name]["minus_c1"]["00-16"]), flush=True)

# ---------------------------------------------------------------- d1-t5-plan1 power (BEFORE only)
if STOP.exists():
    sys.exit("STOP present")


def plan(vals, group, effects, ns, joint_ns):
    c, idx = cells(vals, group, BEFORE)
    c["delta"] = c.a - c.b
    dates, mkts = sorted(c.date.unique()), sorted(c.market.unique())
    di = c.date.map({x: k for k, x in enumerate(dates)}).to_numpy()
    mi = c.market.map({x: k for k, x in enumerate(mkts)}).to_numpy()
    y = c.delta.to_numpy()
    rg = np.random.default_rng(SEED)
    hv = h.interval(idx, y, effect=0.0075)
    out = {"before_estimate": float(y.mean()), "dates": len(dates), "market_days": int(len(c)),
           "harness_crossed_before": {"ci95": hv["ci95"], "mde80": hv["mde80"]},
           "per_market_before": c.groupby("market").delta.mean().round(5).to_dict(), "fixed": {}, "crossed": {}}

    def errs(n, mode):
        e = np.empty(DRAWS)
        for b in range(DRAWS):
            wd = np.ones(len(dates)) if n is None else rg.multinomial(n, np.full(len(dates), 1 / len(dates)))
            wm = np.ones(len(mkts)) if mode == "fixed" else rg.multinomial(len(mkts), np.full(len(mkts), 1 / len(mkts)))
            w = wd[di] * wm[mi]
            e[b] = (w * y).sum() / w.sum() if w.sum() > 0 else np.nan
        e = e[np.isfinite(e)]
        return e - e.mean()

    for mode in ("fixed", "crossed"):
        for n in ns + ([None] if mode == "crossed" else []):
            e = errs(n, mode)
            q = np.quantile(e, ALPHA)
            out[mode]["inf" if n is None else str(n)] = {
                "mde80": float(np.quantile(e, 0.8) - q),
                **{f"power@{ef:.5f}": float(np.mean(e - ef < q)) for ef in effects}}
    ybar = y.mean()
    rj = np.random.default_rng(SEED + 1)
    out["fixed_joint_8of11"] = {}
    for n in joint_ns:
        tot = np.empty(DRAWS)
        pm = np.empty((DRAWS, len(mkts)))
        for b in range(DRAWS):
            w = rj.multinomial(n, np.full(len(dates), 1 / len(dates)))[di].astype(float)
            tot[b] = (w * y).sum() / w.sum()
            num, den = np.bincount(mi, w * y, len(mkts)), np.bincount(mi, w, len(mkts))
            pm[b] = np.divide(num, den, out=np.full(len(mkts), np.nan), where=den > 0)
        err = tot - tot.mean()
        q = np.quantile(err, ALPHA)
        out["fixed_joint_8of11"][str(n)] = {
            f"{ef:.5f}": {"interval": float((err - ef < q).mean()),
                          "joint": float(((err - ef < q) & ((np.nan_to_num(pm - ybar - ef, nan=1.0) < 0).sum(1) >= 8)).mean())}
            for ef in effects}
    return out


NS, JN = [20, 30, 45, 60, 90], [30, 45, 60, 90]
dev_vs = -float(cells({"a": t5_b, "b": served_b}, "00-16", BEFORE)[0].pipe(lambda c: (c.a - c.b).mean()))
R["plan"] = {} if MODE != "full" else {
    "t5_minus_served_00-16": plan({"a": t5_b, "b": served_b}, "00-16", [dev_vs / 2, 0.006672, dev_vs], NS, JN),
    "t5_minus_c1_00-16": plan({"a": t5_b, "b": c1_b}, "00-16", [0.0015, 0.003, 0.006672], NS, JN),
    "t5_minus_served_17-23": plan({"a": t5_b, "b": served_b}, "17-23", [0.0133, 0.016], [20, 45], [20, 45]),
    "t5_minus_c1_13-16": plan({"a": t5_b, "b": c1_b}, "13-16", [0.0035, 0.0071], [20, 45, 90], [45, 90]),
}
if MODE != "full":
    R = {"HARNESS_SHA256": R["HARNESS_SHA256"], "registry_ids": ["d1-t5-plan2"], "development": True,
         "plan2": {"pc1_minus_c1_00-16": plan({"a": pool_b, "b": c1_b}, "00-16", [0.00072, 0.00135, 0.0027], NS, JN),
                   "pc1_minus_c1_13-14": plan({"a": pool_b, "b": c1_b}, "13-14", [0.002, 0.0039], [20, 45, 90], [45, 90])}}
    (OUT / "d1_plan2.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    sys.exit(0)
R["plan"]["effects_note"] = {"t5_vs_served_00-16_before_full": dev_vs, "half": dev_vs / 2,
                             "t5_minus_c1_00-16_before": "+0.0044 (wrong sign): no planning effect exists"}
(OUT / "d1_results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
print("done", flush=True)
