"""T6 hunter: NBM NBS text bulletin, latest available cycle (model-parity swarm v2, development only).

Rules (registered in C:\\swarm\\registry.jsonl before any score; see RULES below):
  t6-r1  TXN mode only: latest available NBS cycle carrying the target day's TXN (12-h max ending
         00Z on D+1), X ~ N(TXN, max(XND,1)) integer-discretised; final H = max(floor bucket, X).
  t6-r2  latest available cycle: TXN mode if that cycle carries today's TXN, else REM mode:
         mu = max over remaining 3-hourly NBS TMP valid in (t, local midnight], each valid time taken
         from the latest available cycle carrying it; sigma = max(TSD at argmax, 1); no remaining
         valid time -> all mass on the floor-bucket band. Final H = max(floor bucket, X).
  t6-r3  t6-r2 with per-mode bias b and sigma scale s fitted on history local dates
         2026-05-01..2026-07-31 only (IEM NBS 00/06/12/18Z + S3 parts <= 07-31; truth = METAR
         hourly-row max, non-COR routine+SPECI, rounded tmpf).
  t6-d1  diagnostic: t6-r2 / t6-r3 with every NBS object treated as available 60 min after its
         S3 LastModified (PIT stress), parameters of r3 frozen.

Point in time: an NBS cycle enters a snapshot only if its S3 LastModified (A-NBH ledger, or the
A-IEM-2 S3 listing for IEM rows) <= captured_at_utc; rows without LastModified are excluded.
No market input, no labels; floor = harness rule-4 floor; served fallback for uncovered rows.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t6_nbs_latest
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t6")
PARTS = r"C:\swarm\data\nbs\parts\nbs_*.parquet"
LEDGER = Path(r"C:\swarm\data\nbh\ledger.jsonl")
NBS_MANIFEST = Path(r"C:\swarm\data\nbs\MANIFEST.json")
IEM_NBS = Path(r"C:\swarm\data\iem\mos\mos_NBS.parquet")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
HIST_START, HIST_END = "2026-05-01", "2026-07-31"
SIG_MIN = 1.0

RULES = {
    "t6-r1": "T6-r1 NBS TXN latest. At snapshot t (market station, local target date D), among NBM NBS "
             "text-bulletin cycles (S3 blend_nbstx, A-NBH parts; IEM mos NBS 00/06/12/18Z as fallback) "
             "whose S3 LastModified <= captured_at_utc, take the latest cycle_utc that carries a TXN row "
             "valid at (D+1) 00Z (the daytime max). X ~ Normal(TXN, max(XND,1)) discretised on integers "
             "(mass on [k-0.5,k+0.5)); final H = max(B, X) with B = floor(F+0.5), F = harness rule-4 floor; "
             "band probability = P(H in band). No such cycle -> served fallback. Zero fitted parameters.",
    "t6-r2": "T6-r2 NBS latest cycle, remaining-hours framing. C = latest cycle_utc with S3 LastModified <= "
             "captured_at_utc. If C carries a TXN valid (D+1) 00Z: X ~ Normal(TXN, max(XND,1)) (TXN mode). "
             "Else REM mode: for every 3-hourly valid time v in (t, end of local day D], take TMP (and TSD) "
             "from the latest available cycle carrying v; mu = max TMP, sigma = max(TSD at argmax, 1); "
             "X ~ Normal(mu, sigma) integer-discretised; if no v remains, X = -inf (all mass on the floor "
             "band). Final H = max(B, X), B = floor(F+0.5). Served fallback where no cycle is available. "
             "Zero fitted parameters.",
    "t6-r3": "T6-r3 = t6-r2 with per-mode (TXN, REM) bias b and sigma scale s: mu' = mu + b, sigma' = "
             "max(s*sigma, 1). Fitted on history local dates 2026-05-01..2026-07-31 only, simulated hourly "
             "snapshots on the hour, same PIT cycle selection (IEM NBS 00/06/12/18Z + A-NBH parts dated "
             "<= 07-31). TXN mode residual = METAR daily hourly-row max (non-COR routine+SPECI, rounded "
             "tmpf) - mu; REM mode residual = METAR max over rows valid in (t, end of day] - mu. b = median "
             "residual, s = sqrt(mean(((resid-b)/sigma)^2)). REM no-remaining case unchanged (collapse).",
    "t6-d1": "T6-d1 DIAGNOSTIC (not a new candidate): t6-r2 and t6-r3 (frozen b, s) with every NBS object "
             "treated as available 60 minutes after its S3 LastModified. PIT stress only.",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- NBS loading

def lastmodified_map():
    """(date 'YYYY-MM-DD', cycle int) -> S3 LastModified for blend_nbstx, from primary listings."""
    lm = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("product") == "nbs" and r.get("status") == "ok" and r.get("s3_last_modified"):
                lm[(r["date"], int(r["cycle"]))] = pd.Timestamp(r["s3_last_modified"])
    if NBS_MANIFEST.exists():
        m = json.loads(NBS_MANIFEST.read_text(encoding="utf-8"))
        for o in m.get("objects", []):
            if o.get("status") == "ok" and o.get("s3_last_modified"):
                k = o["key"]  # blend.YYYYMMDD/HH/text/...
                d, hh = k.split("/")[0][6:], int(k.split("/")[1])
                key = (f"{d[:4]}-{d[4:6]}-{d[6:]}", hh)
                lm.setdefault(key, pd.Timestamp(o["s3_last_modified"]))
    return lm


def load_cycles(extra_lag_min=0):
    """Return {station: list of cycle dicts} with TXN map and TMP rows, availability-stamped."""
    lm = lastmodified_map()
    cyc = defaultdict(dict)   # station -> cycle_utc -> dict
    n_parts, n_nolm = 0, 0
    for f in sorted(glob.glob(PARTS)):
        stem = Path(f).stem.split("_")  # nbs_YYYYMMDD_HH
        d, hh = stem[1], int(stem[2])
        key = (f"{d[:4]}-{d[4:6]}-{d[6:]}", hh)
        if key not in lm:
            n_nolm += 1
            continue
        avail = lm[key] + pd.Timedelta(minutes=extra_lag_min)
        p = pd.read_parquet(f, columns=["station", "field", "fhr", "value", "cycle_utc", "valid_utc"])
        p = p[p.field.isin(["TXN", "XND", "TMP", "TSD"])]
        n_parts += 1
        for st, g in p.groupby("station"):
            c = pd.Timestamp(g.cycle_utc.iloc[0])
            piv = g.pivot_table(index="valid_utc", columns="field", values="value", aggfunc="first")
            cyc[st][c] = {"cycle": c, "avail": avail, "src": "s3part", "piv": piv}
    # IEM fallback / history: only full-depth cycles 00/06/12/18Z with measured LastModified
    iem = pd.read_parquet(IEM_NBS, columns=["station", "runtime", "ftime", "tmp", "tsd", "txn", "xnd",
                                            "available_utc"])
    iem = iem[iem.runtime.dt.hour.isin([0, 6, 12, 18]) & iem.available_utc.notna()]
    n_iem = 0
    for (st, rt), g in iem.groupby(["station", "runtime"]):
        c = pd.Timestamp(rt)
        if c in cyc[st]:
            continue
        piv = pd.DataFrame({"TMP": g.tmp.to_numpy(float), "TSD": g.tsd.to_numpy(float),
                            "TXN": g.txn.to_numpy(float), "XND": g.xnd.to_numpy(float)},
                           index=pd.DatetimeIndex(g.ftime))
        cyc[st][c] = {"cycle": c, "avail": pd.Timestamp(g.available_utc.iloc[0]) +
                      pd.Timedelta(minutes=extra_lag_min), "src": "iem", "piv": piv}
        n_iem += 1
    out = {}
    for st, d in cyc.items():
        lst = sorted(d.values(), key=lambda x: x["cycle"])
        for x in lst:
            piv = x["piv"]
            txn = {}
            if "TXN" in piv:
                for v, row in piv[piv["TXN"].notna()].iterrows():
                    xnd = row.get("XND")
                    txn[pd.Timestamp(v)] = (float(row["TXN"]), float(xnd) if pd.notna(xnd) else np.nan)
            tmp = piv[piv["TMP"].notna()] if "TMP" in piv else piv.iloc[0:0]
            x["txn"] = txn
            x["tmp_v"] = np.array([pd.Timestamp(v).value for v in tmp.index], dtype=np.int64)
            x["tmp"] = tmp["TMP"].to_numpy(float) if len(tmp) else np.array([])
            x["tsd"] = (tmp["TSD"].to_numpy(float) if "TSD" in tmp else np.full(len(tmp), np.nan)) \
                if len(tmp) else np.array([])
            del x["piv"]
        out[st] = lst
    info = {"s3_parts_used": n_parts, "s3_parts_without_lastmodified_excluded": n_nolm,
            "iem_cycles_used": n_iem, "lastmodified_keys": len(lm)}
    return out, info


class StationIndex:
    """Fast PIT lookups per station."""

    def __init__(self, cycles):
        self.c = cycles
        self.avail = np.array([x["avail"].value for x in cycles], dtype=np.int64)
        self.cyc = np.array([x["cycle"].value for x in cycles], dtype=np.int64)
        # per valid time: list of (avail, cycle, tmp, tsd)
        self.byv = defaultdict(list)
        for x in cycles:
            for v, t, s in zip(x["tmp_v"], x["tmp"], x["tsd"]):
                self.byv[int(v)].append((x["avail"].value, x["cycle"].value, t, s))
        self.vs = np.array(sorted(self.byv), dtype=np.int64)

    def latest(self, t, need_txn_valid=None):
        ok = np.flatnonzero(self.avail <= t)
        if not len(ok):
            return None
        if need_txn_valid is None:
            return self.c[ok[np.argmax(self.cyc[ok])]]
        best = None
        for i in ok[np.argsort(-self.cyc[ok])]:
            if need_txn_valid in self.c[i]["txn"]:
                best = self.c[i]
                break
        return best

    def remaining(self, t, end):
        """max TMP over valid v in (t, end] using the latest available cycle carrying each v."""
        sel = self.vs[(self.vs > t) & (self.vs <= end)]
        best_mu, best_sd = -math.inf, np.nan
        for v in sel:
            cand = [r for r in self.byv[int(v)] if r[0] <= t]
            if not cand:
                continue
            r = max(cand, key=lambda r: r[1])
            if r[2] > best_mu:
                best_mu, best_sd = r[2], r[3]
        return best_mu, best_sd, len(sel)


# ----------------------------------------------------------------------------- distribution

def mode_params(si, t, d_next00, end, rule):
    """Return (mode, mu, sigma) or None. t, d_next00, end: int64 ns UTC."""
    tx = pd.Timestamp(d_next00, tz="UTC")
    if rule == "r1":
        c = si.latest(t, need_txn_valid=tx)
        if c is None:
            return None
        txn, xnd = c["txn"][tx]
        return ("TXN", txn, max(xnd if np.isfinite(xnd) else SIG_MIN, SIG_MIN), c)
    c = si.latest(t)
    if c is None:
        return None
    if tx in c["txn"]:
        txn, xnd = c["txn"][tx]
        return ("TXN", txn, max(xnd if np.isfinite(xnd) else SIG_MIN, SIG_MIN), c)
    mu, sd, nsel = si.remaining(t, end)
    if not np.isfinite(mu):
        return ("REM0", -math.inf, SIG_MIN, c) if nsel == 0 else None
    return ("REM", mu, max(sd if np.isfinite(sd) else SIG_MIN, SIG_MIN), c)


def band_probs(kind, low, high, B, mu, sig):
    """P(H in band) with H = max(B, X), X ~ N(mu, sig) integer-discretised. Vectorised per snapshot."""
    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    if not np.isfinite(mu):
        # X = -inf: P(X <= x) = 1 for every x > -inf (bug fixed 01:20: v1 returned 0 for finite x,
        # which put the REM0 mass on the gte band instead of the floor band, contrary to the rule text)
        cdf = lambda x: np.where(np.isneginf(x), 0.0, 1.0)
    else:
        cdf = lambda x: ndtr((x - mu) / sig)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, cdf(up) - cdf(lo), 0.0)
    return np.clip(p, 0.0, None)


# ----------------------------------------------------------------------------- snapshots

def snapshot_frame():
    snaps, bands = h.candidate_inputs()
    s = snaps[["row_key", "market", "station", "date", "stratum", "local_hour", "block",
               "captured_at_utc", "captured_at_local", "floor", "n_bands"]].copy()
    cu = pd.to_datetime(s.captured_at_utc, utc=True)
    s["t_ns"] = cu.dt.as_unit("ns").astype("int64")
    # local offset from captured_at_local
    off = s.captured_at_local.str[-6:]
    sign = np.where(off.str[0] == "-", -1, 1)
    off_min = sign * (off.str[1:3].astype(int) * 60 + off.str[4:6].astype(int))
    dnext = pd.to_datetime(s.date) + pd.Timedelta(days=1)
    s["end_ns"] = (dnext - pd.to_timedelta(off_min, unit="m")).dt.as_unit("ns").astype("int64")  # local midnight end (naive = UTC wall)
    s["dnext00_ns"] = pd.to_datetime(dnext).dt.tz_localize("UTC").dt.as_unit("ns").astype("int64")
    return s, bands


def build_candidate(rule, cycles, s, bands, params=None):
    idx = {st: StationIndex(c) for st, c in cycles.items()}
    offs = np.concatenate([[0], np.cumsum(s.n_bands.to_numpy())[:-1]]).astype(int)
    assert len(bands) == int(s.n_bands.sum())
    assert (bands.row_key.to_numpy()[offs] == s.row_key.to_numpy()).all(), "band/snapshot misalignment"
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    modes = np.full(len(s), "NONE", dtype=object)
    ages = np.full(len(s), np.nan)
    cache = {}
    recs = s[["station", "t_ns", "end_ns", "dnext00_ns", "floor", "n_bands"]].to_numpy()
    avail_checks_a, avail_checks_c = [], []
    for i, (st, t, end, dn, F, n) in enumerate(recs):
        si = idx.get(st)
        if si is None or F is None or not np.isfinite(F):
            continue
        k_av = int(np.searchsorted(np.sort(si.avail), t, side="right")) if False else None
        key = (st, int(t) // (60 * 10**9), int(dn), rule)  # minute resolution cache
        if key in cache:
            mp = cache[key]
        else:
            mp = mode_params(si, int(t), int(dn), int(end), rule)
            cache[key] = mp
        if mp is None:
            continue
        mode, mu, sig, c = mp
        if params is not None and mode in params:
            b, sc = params[mode]
            mu, sig = mu + b, max(sc * sig, SIG_MIN)
        B = math.floor(float(F) + .5)
        o = offs[i]
        p = band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() <= 0:
            continue
        p_out[o:o + n] = p / p.sum()
        modes[i] = mode
        ages[i] = (int(t) - c["cycle"].value) / 3.6e12
        if i % 50 == 0:
            avail_checks_a.append(c["avail"])
            avail_checks_c.append(pd.Timestamp(int(t), tz="UTC"))
    # rule 1 tripwire on a systematic sample (every 50th covered snapshot) + full check below
    if avail_checks_a:
        h.assert_point_in_time(avail_checks_a, avail_checks_c)
    covered = ~np.isnan(p_out)
    cand = bands.loc[covered, ["row_key", "band_index"]].copy()
    cand["p"] = p_out[covered]
    return cand, modes, ages


def full_pit_check(cycles, s, rule, params=None):
    """Re-derive the chosen cycle per covered snapshot and assert availability for all of them."""
    idx = {st: StationIndex(c) for st, c in cycles.items()}
    av, cap = [], []
    for st, t, dn, end in s[["station", "t_ns", "dnext00_ns", "end_ns"]].to_numpy():
        si = idx.get(st)
        if si is None:
            continue
        mp = mode_params(si, int(t), int(dn), int(end), rule)
        if mp is None:
            continue
        av.append(mp[3]["avail"])
        cap.append(pd.Timestamp(int(t), tz="UTC"))
    h.assert_point_in_time(av, cap)
    return len(av)


# ----------------------------------------------------------------------------- history fit (r3)

def metar_history():
    out = {}
    for f in sorted(METAR_DIR.glob("K*.parquet")):
        m = pd.read_parquet(f, columns=["station", "tmpf", "valid_utc", "local_date", "is_cor", "local_time"])
        m = m[(~m.is_cor) & m.tmpf.notna()]
        m["ld"] = m.local_date.astype(str)
        m = m[(m.ld >= HIST_START) & (m.ld <= HIST_END)]
        m["t"] = np.floor(m.tmpf + .5)
        out[f.stem] = m
    return out


def fit_r3(cycles):
    met = metar_history()
    # history cycles only: cycle date <= 2026-07-31 (no evaluation-window object used for fitting)
    hist_cut = pd.Timestamp("2026-08-01T00:00Z")
    resid = {"TXN": [], "REM": []}
    sig = {"TXN": [], "REM": []}
    for st, m in met.items():
        cl = [c for c in cycles.get(st, []) if c["cycle"] < hist_cut]
        if not cl:
            continue
        si = StationIndex(cl)
        off = m.local_time.str[-5:]
        for ld, g in m.groupby("ld"):
            o = g.local_time.iloc[0][-5:]
            sign = -1 if o[0] == "-" else 1
            off_min = sign * (int(o[1:3]) * 60 + int(o[3:5]))
            d0 = pd.Timestamp(ld, tz="UTC") - pd.Timedelta(minutes=off_min)
            end = d0 + pd.Timedelta(days=1)
            dn = pd.Timestamp(ld, tz="UTC") + pd.Timedelta(days=1)
            vt = g.valid_utc.dt.as_unit("ns").astype("int64").to_numpy()
            tt = g.t.to_numpy()
            if len(g) < 18:
                continue
            dmax = tt.max()
            for hr in range(24):
                t = d0 + pd.Timedelta(hours=hr)
                mp = mode_params(si, t.value, dn.value, end.value, "r2")
                if mp is None:
                    continue
                mode, mu, sg, _ = mp
                if mode == "TXN":
                    resid["TXN"].append(dmax - mu)
                    sig["TXN"].append(sg)
                elif mode == "REM":
                    rem = tt[vt > t.value]
                    if len(rem):
                        resid["REM"].append(rem.max() - mu)
                        sig["REM"].append(sg)
    params, stats = {}, {}
    for mode in ("TXN", "REM"):
        r, sgm = np.array(resid[mode]), np.array(sig[mode])
        if len(r) < 50:
            continue
        b = float(np.median(r))
        sc = float(np.sqrt(np.mean(((r - b) / sgm) ** 2)))
        params[mode] = (b, sc)
        stats[mode] = {"n_hourly_samples": int(len(r)), "bias_median": b, "sigma_scale": sc,
                       "resid_mean": float(r.mean()), "resid_sd": float(r.std()),
                       "mean_sigma": float(sgm.mean())}
    return params, stats


# ----------------------------------------------------------------------------- main

def register(ids):
    reg = Path(r"C:\swarm\registry.jsonl")
    have = set()
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["id"])
            except Exception:
                pass
    for rid in ids:
        if rid in have:
            continue
        text = RULES[rid]
        rec = {"id": rid, "agent": "t6", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(reg, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def summarize_result(res):
    rows = {}
    for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
        rows[g] = {}
        for st in ("before_20260823", "from_20260823", "pooled"):
            for pop in ("all_row", "matched"):
                try:
                    t = h.table_lookup(res, g, st, pop)
                except StopIteration:
                    continue
                if t.get("status") == "NO_DATA":
                    continue
                rows[g][f"{st}|{pop}"] = {
                    "cms": t["candidate_minus_served"]["estimate"],
                    "cms_ci": t["candidate_minus_served"]["ci95"],
                    "cmm": t["candidate_minus_market"]["estimate"],
                    "cmm_ci": t["candidate_minus_market"]["ci95"],
                    "ratio": t["ratio_candidate_to_market"],
                    "smm": t["served_minus_market"]["estimate"],
                    "markets_negative": t.get("markets_negative"),
                    "n_snap": t.get("snapshots"),
                }
    return rows


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    register(list(RULES))
    log("loading NBS cycles")
    cycles, info = load_cycles()
    log("cycles", info)
    s, bands = snapshot_frame()
    assert (s.date <= "2026-09-29").all()
    log("fitting r3 on history <= 07-31")
    params, fstats = fit_r3(cycles)
    log("r3 params", params)
    results = {}
    diag = {}
    for rid, rule, prm, cyc in (("t6-r1", "r1", None, cycles), ("t6-r2", "r2", None, cycles),
                                ("t6-r3", "r2", params, cycles)):
        if Path(r"C:\swarm\STOP").exists():
            sys.exit("STOP present")
        log("building", rid)
        cand, modes, ages = build_candidate(rule, cyc, s, bands, prm)
        npit = full_pit_check(cyc, s, rule)
        res = h.score(cand, name=rid.replace("-", "_") + "_nbs")
        h.save(res, OUT)
        results[rid] = res
        mc = pd.Series(modes).value_counts().to_dict()
        diag[rid] = {"modes": {k: int(v) for k, v in mc.items()},
                     "mode_by_block": pd.crosstab(s.block.to_numpy(), modes).to_dict(),
                     "median_cycle_age_h_by_block": pd.Series(ages).groupby(s.block.to_numpy()).median().to_dict(),
                     "pit_checked_snapshots": npit}
        log(rid, res["classes"]["17-23"]["class"], {g: res["classes"][g]["class"] for g in res["classes"]})
        print(h.markdown(res))
    # d1: +60 min availability stress
    log("d1 stress")
    cyc60, info60 = load_cycles(extra_lag_min=60)
    for rid, prm in (("t6-d1-r2", None), ("t6-d1-r3", params)):
        cand, modes, ages = build_candidate("r2", cyc60, s, bands, prm)
        res = h.score(cand, name=rid.replace("-", "_") + "_nbs_lag60")
        h.save(res, OUT)
        results[rid] = res
        log(rid, {g: res["classes"][g]["class"] for g in res["classes"]})
    summary = {rid: {"classes": {g: v["class"] for g, v in r["classes"].items()},
                     "reason_counts": r["reason_counts"], "candidate_share": r["candidate_share"],
                     "leakage_suspect_groups": r["leakage_suspect_groups"],
                     "tables": summarize_result(r),
                     "tail": [t for t in r["tail"] if t["stratum"] in ("from_20260823", "pooled")]}
               for rid, r in results.items()}
    out = {"agent": "t6", "HARNESS_SHA256": h.harness_sha256(), "load_info": info,
           "r3_params": {k: list(v) for k, v in params.items()}, "r3_fit_stats": fstats,
           "diagnostics": diag, "results": summary,
           "classes_full": {rid: r["classes"] for rid, r in results.items()}}
    (OUT / "t6_run.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
