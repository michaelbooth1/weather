"""T18 hunter: small EMOS over the best three sources (model-parity swarm v2, development only).

Registered rules (C:\\swarm\\registry.jsonl, agent t18; text in C:\\swarm\\out\\t18\\rules.json):
  t18-r1  rung x guidance likelihood: P(H = R+e) ~ p0(e) * exp(-0.5*((R+e-m)/sigma)^2),
          p0 = t3-r3 remaining-rise pmf (history <= 2026-07-31), m = mu_rr + a + sum_k b_k (max(S_k,R) - mu_rr),
          sigma = exp(c); <= 3 sources chosen by greedy forward selection on BEFORE-stratum training NLL.
  t18-c0  no-source control: m = mu_rr + a.
Fit: before stratum only (target dates 2026-08-01..08-22), label = IEM METAR daily hourly-row max (no winner).
EF 5 training-score check first. One coefficient set at every hour (rule 8: no hour gate).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t18_emos
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp

from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3
from tools.research.model_parity import t5_nbh_latest as t5

OUT = Path(r"C:\swarm\out\t18")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
CACHE = Path(r"C:\swarm\cache")
G = 41                      # rise grid e = 0..40 F
BEFORE, FROM = "before_20260823", "from_20260823"
POOL = ["v2_mean", "hrrr_high", "nws_grid_high", "forecast_high", "nbh_rem"]
MIN_GAIN = 0.001            # nats per training snapshot (registered)
MAX_SOURCES = 3
P_CLIP = 1e-9               # NLL clip for observed values outside the smoothed support (same for every model)
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def registered():
    rows = [json.loads(x) for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    reg = {r["id"]: r for r in rows if r.get("agent") == "t18"}
    for rid in ("t18-r1", "t18-c0"):
        assert hashlib.sha256(reg[rid]["text"].encode("utf-8")).hexdigest() == reg[rid]["sha256"], rid
    return reg


# ----------------------------------------------------------------------------- inputs

def build_inputs():
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    assert (snaps.unit == "F").all(), snaps.unit.unique()
    s = snaps.copy()
    s["month"] = s.date.str[5:7].astype(int)
    m = t3.load_metar()
    d = t3.daily(m)
    rr_path = OUT / "rise_table.parquet"
    if rr_path.exists():
        rr = pd.read_parquet(rr_path)
    else:
        rr = t3.remaining_rise_table(m, d)
        rr.to_parquet(rr_path)
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
    today = t3.pit_asof(s, m, "today")
    s["R"] = today["cummax"].reindex(s.row_key).to_numpy()
    prior = np.full((len(s), G), np.nan)
    ok = s.R.notna().to_numpy().copy()
    for i, (st, mo, H) in enumerate(zip(s.station, s.month, s.local_hour)):
        if ok[i] and (st, mo, int(H)) in rise:
            prior[i] = rise[(st, mo, int(H))]
        else:
            ok[i] = False
    s["covered"] = ok
    # label (fit only): IEM METAR complete-day hourly-row max
    lab = d.set_index(["station", "local_date"]).dmax
    s["Y"] = [lab.get((st, dt), np.nan) for st, dt in zip(s.station, s.date)]

    # sources, point in time (rule 1)
    cap = pd.to_datetime(s.captured_at_utc, utc=True)
    def pit(col, avail_col):
        av = pd.to_datetime(s[avail_col], utc=True, errors="coerce")
        use = s[col].notna() & av.notna() & (av <= cap)
        h.assert_point_in_time(av[use], cap[use])
        return np.where(use, s[col].to_numpy(float), np.nan), int(use.sum())
    src, src_n = {}, {}
    src["v2_mean"], src_n["v2_mean"] = pit("v2_mean", "v2_available_at")
    src["hrrr_high"], src_n["hrrr_high"] = pit("hrrr_high", "hrrr_fetched_at")
    src["nws_grid_high"], src_n["nws_grid_high"] = pit("nws_grid_high", "nws_grid_fetched_at")
    src["forecast_high"] = s.forecast_high.to_numpy(float)   # served model's own output at t
    src_n["forecast_high"] = int(np.isfinite(src["forecast_high"]).sum())
    s5, b5 = t5.snapshot_frame()
    assert (s5.row_key.to_numpy() == s.row_key.to_numpy()).all()
    idx = t5.load_nbh()
    _, _, mus, reasons = t5.build_candidate(idx, s5, b5)    # asserts PIT (S3 LastModified <= t)
    src["nbh_rem"] = mus
    src_n["nbh_rem"] = int(np.isfinite(mus).sum())
    meta = {"rise_cells": len(rise), "covered": int(ok.sum()), "source_rows_pit": src_n,
            "nbh_reasons": reasons,
            "nbh_tidy_sha256": hashlib.sha256((Path(r"C:\swarm\data\nbh\nbh_tidy.parquet")).read_bytes()).hexdigest()}
    return s, bands, prior, src, meta


# ----------------------------------------------------------------------------- model

class Model:
    def __init__(self, s, prior, src, rows):
        self.R = s.R.to_numpy(float)[rows]
        P = prior[rows]
        self.logp0 = np.log(np.where(P > 0, P, 1e-300))
        self.e = np.arange(G, dtype=float)
        self.murr = self.R + P @ self.e
        self.X = {k: (lambda v: np.where(np.isfinite(v), np.maximum(v, self.R) - self.murr, 0.0))(src[k][rows])
                  for k in src}

    def logpost(self, theta, keys):
        a, c = theta[0], theta[-1]
        mm = self.murr + a
        for b, k in zip(theta[1:-1], keys):
            mm = mm + b * self.X[k]
        sig = np.exp(c)
        z = (self.R[:, None] + self.e[None, :] - mm[:, None]) / sig
        lg = self.logp0 - 0.5 * z * z
        return lg - logsumexp(lg, axis=1, keepdims=True)

    def pmf(self, theta, keys):
        return np.exp(self.logpost(theta, keys))


def nll_rows(pm, eobs):
    p = pm[np.arange(len(eobs)), eobs]
    return -np.log(np.maximum(p, P_CLIP))


def fit(model, eobs, keys, start=None):
    k = len(keys)
    x0 = np.r_[0.0, np.zeros(k), np.log(3.0)] if start is None else start
    f = lambda th: float(nll_rows(model.pmf(th, keys), eobs).mean())
    r = minimize(f, x0, method="L-BFGS-B")
    return r.x, float(r.fun), bool(r.success)


# ----------------------------------------------------------------------------- bands

def to_bands(s, bands, pm_full, cov):
    n = s.n_bands.to_numpy()
    off = np.r_[0, np.cumsum(n)[:-1]]
    assert (bands.row_key.to_numpy()[off] == s.row_key.to_numpy()).all()
    sob = np.repeat(np.arange(len(s)), n)
    cum = np.concatenate([np.zeros((len(s), 1)), np.cumsum(np.nan_to_num(pm_full), axis=1)], axis=1)
    R = np.nan_to_num(s.R.to_numpy(float))[sob]
    kind = bands.kind.to_numpy()
    lo = np.where(kind == "lte", -10**6, bands.low.to_numpy(float))
    hi = np.where(kind == "gte", 10**6, bands.high.to_numpy(float))
    a = np.clip(lo - R, 0, G).astype(int)
    b = np.clip(hi - R + 1, 0, G).astype(int)
    p = cum[sob, b] - cum[sob, a]
    keep = cov[sob]
    out = bands.loc[keep, ["row_key", "band_index"]].copy()
    out["p"] = np.clip(p[keep], 0, None)
    return out


# ----------------------------------------------------------------------------- paired marginal

def paired(cands, names, pairs=None):
    """Paired cell-mean deltas using the harness's own floored candidate vector (same rows, same floor)."""
    d = h.data()
    y = d.bands.is_winner.to_numpy(float)
    sn = d.snaps
    f = sn[["date", "market", "stratum", "local_hour"]].copy()
    for nm in names:
        pc, use, _ = h._candidate_vector(cands[nm], d, False)
        f[nm] = np.add.reduceat((pc - y) ** 2, d.offsets) / sn.n_bands.to_numpy()
    f["served"] = np.add.reduceat((d.p_served - y) ** 2, d.offsets) / sn.n_bands.to_numpy()
    W = np.load(CACHE / "W.npy")
    keys = [tuple(k) for k in json.loads((CACHE / "W_keys.json").read_text())]
    kidx = {k: i for i, k in enumerate(keys)}
    pairs = pairs or [("t18-r1", "t3-r3"), ("t18-r1", "t18-c0"), ("t18-c0", "t3-r3"), ("t18-r1", "served")]
    out = {}
    for g, (lo, hi) in GROUPS.items():
        out[g] = {}
        for stratum in (FROM, BEFORE):
            msk = f.local_hour.between(lo, hi) & (f.stratum == stratum)
            c = f[msk].groupby(["date", "market"], sort=True)[names + ["served"]].mean().reset_index()
            ix = np.array([kidx[(dd, mk)] for dd, mk in zip(c.date, c.market)])
            sub = W[:, ix]
            res = {}
            for x, z in pairs:
                dv = (c[x] - c[z]).to_numpy()
                bo = (sub @ dv) / sub.sum(1)
                pm = c.assign(dv=dv).groupby("market").dv.mean()
                res[f"{x} - {z}"] = {"est": float(dv.mean()), "ci95": np.quantile(bo, [.025, .975]).tolist(),
                                     "markets_neg": int((pm < 0).sum()), "markets": int(len(pm))}
            out[g][stratum] = res
    return out


# ----------------------------------------------------------------------------- main

def main():
    reg = registered()
    OUT.mkdir(parents=True, exist_ok=True)
    log("inputs")
    s, bands, prior, src, meta = build_inputs()
    cov = s.covered.to_numpy()
    tr = cov & (s.stratum == BEFORE).to_numpy() & s.Y.notna().to_numpy()
    eobs = (s.Y.to_numpy()[tr] - s.R.to_numpy()[tr]).astype(int)
    assert (eobs >= 0).all(), "label below PIT running max"
    eobs = np.minimum(eobs, G - 1)
    assert (s.date[tr] <= "2026-08-22").all()
    log("train rows", int(tr.sum()))
    mtr = Model(s, prior, src, tr)
    # rung NLL (sigma -> infinity)
    rung_nll = float(nll_rows(np.exp(mtr.logp0 - logsumexp(mtr.logp0, axis=1, keepdims=True)), eobs).mean())
    th0, nll0, ok0 = fit(mtr, eobs, [])
    log("c0", th0, nll0, "rung", rung_nll)
    screen = {}
    for k in POOL:
        th, nl, okk = fit(mtr, eobs, [k], np.r_[th0[0], 0.0, th0[-1]])
        screen[k] = {"theta": th.tolist(), "train_nll": nl, "gain_vs_c0": nll0 - nl, "ok": okk,
                     "train_coverage": float(np.isfinite(src[k][tr]).mean())}
        log("single", k, round(nll0 - nl, 5), th)
    chosen, cur_nll, cur_th, steps = [], nll0, th0, []
    while len(chosen) < MAX_SOURCES:
        best = None
        for k in POOL:
            if k in chosen:
                continue
            st = np.r_[cur_th[:-1], 0.0, cur_th[-1]]
            th, nl, okk = fit(mtr, eobs, chosen + [k], st)
            if best is None or nl < best[1]:
                best = (k, nl, th)
        steps.append({"candidate": best[0], "train_nll": best[1], "gain": cur_nll - best[1]})
        if cur_nll - best[1] < MIN_GAIN:
            break
        chosen.append(best[0]); cur_nll = best[1]; cur_th = best[2]
        log("chose", best[0], round(steps[-1]["gain"], 5))
    th1 = cur_th
    # training-score check (EF 5), NLL part, and per-block training NLL
    pm_tr1 = mtr.pmf(th1, chosen); pm_tr0 = mtr.pmf(th0, [])
    hr = s.local_hour.to_numpy()[tr]
    rung_rows = nll_rows(np.exp(mtr.logp0 - logsumexp(mtr.logp0, axis=1, keepdims=True)), eobs)
    blk_nll = {}
    for g, (lo, hi) in GROUPS.items():
        mk = (hr >= lo) & (hr <= hi)
        blk_nll[g] = {"rung": float(rung_rows[mk].mean()), "c0": float(nll_rows(pm_tr0, eobs)[mk].mean()),
                      "r1": float(nll_rows(pm_tr1, eobs)[mk].mean()), "n": int(mk.sum())}
    # full-table pmfs
    mall = Model(s, prior, src, cov)
    pm1 = np.full((len(s), G), np.nan); pm0 = pm1.copy(); pmr = pm1.copy()
    pm1[cov] = mall.pmf(th1, chosen)
    pm0[cov] = mall.pmf(th0, [])
    pmr[cov] = prior[cov]
    cands = {"t18-r1": to_bands(s, bands, pm1, cov), "t18-c0": to_bands(s, bands, pm0, cov),
             "t3-r3": to_bands(s, bands, pmr, cov)}
    names = {"t18-r1": "t18_r1_emos", "t18-c0": "t18_c0_nosource", "t3-r3": "t18_rung_t3r3_rebuilt"}
    results = {}
    for k, nm in names.items():
        res = h.score(cands[k], name=nm)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            (Path(r"C:\swarm\STOP")).write_text(f"t18 leakage suspect {nm} {res['leakage_suspect_groups']}\n")
            raise SystemExit("LEAKAGE SUSPECT " + nm)
        h.save(res, OUT)
        (OUT / f"{nm}.md").write_text(h.markdown(res), encoding="utf-8")
        results[k] = res
        print(h.markdown(res))
    pr = paired(cands, list(names))
    # source effect sizes in deg F: mean |m - mu_rr| contribution by block (descriptive)
    contrib = {}
    for g, (lo, hi) in GROUPS.items():
        mk = (s.local_hour.to_numpy()[cov] >= lo) & (s.local_hour.to_numpy()[cov] <= hi)
        sh = sum(b * mall.X[k] for b, k in zip(th1[1:-1], chosen)) if chosen else np.zeros(cov.sum())
        contrib[g] = {"mean_abs_source_shift_F": float(np.abs(sh[mk]).mean()),
                      "mean_E_rise_r1": float((pm1[cov][mk] @ np.arange(G)).mean()),
                      "mean_E_rise_rung": float((prior[cov][mk] @ np.arange(G)).mean())}
    run = {"HARNESS_SHA256": h.harness_sha256(), "meta": meta, "train_rows": int(tr.sum()),
           "train_dates": [s.date[tr].min(), s.date[tr].max()],
           "train_nll": {"rung_t3r3": rung_nll, "c0": nll0, "r1": cur_nll}, "train_nll_by_block": blk_nll,
           "theta_c0": {"a": th0[0], "sigma": float(np.exp(th0[-1]))},
           "theta_r1": {"a": th1[0], **{f"b_{k}": float(b) for k, b in zip(chosen, th1[1:-1])},
                        "sigma": float(np.exp(th1[-1]))},
           "chosen": chosen, "selection_steps": steps, "single_source_screen": screen,
           "paired": pr, "shift_by_block": contrib,
           "classes": {k: results[k]["classes"] for k in results}}
    (OUT / "t18_run.json").write_text(json.dumps(run, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("train_nll", "theta_c0", "theta_r1", "chosen", "selection_steps")},
                     indent=1, default=float))
    log("done")


if __name__ == "__main__":
    main()
