"""T5 hunter: NBM NBH hourly text bulletin, latest available cycle (model-parity swarm v2, development only).

Rules (registered in C:\\swarm\\registry.jsonl before any score; text in RULES):
  t5-r1  NBH latest cycle, remaining-hours max: mu = max hourly TMP over valid hours v in (t, end of local
         target day], each v from the latest available NBH cycle carrying it (the latest cycle first);
         sigma = max(TSD at the argmax hour, 1). X ~ N(mu, sigma) integer-discretised; final H = max(B, X),
         B = floor bucket of the harness rule-4 floor. Zero fitted parameters.
  t5-r2  t5-r1 with per-local-hour-block bias b and sigma scale s fitted on history only: NBH cycles issued
         before 2026-08-01 (S3, 2026-07-25..07-31) against METAR (routine, non-COR, rounded tmpf) local dates
         2026-07-25..07-31; residual = max obs valid in (t, end] - mu.
  t5-d1  DIAGNOSTIC: r1 and r2 (frozen b, s) with every NBH object treated as available 60 min after its S3
         LastModified (PIT stress).

Point in time: an NBH cycle enters a snapshot only if its per-object S3 LastModified (A-NBH MANIFEST,
column available_utc of nbh_tidy.parquet) <= captured_at_utc; asserted with h.assert_point_in_time for
every covered snapshot. No market input, no labels, floor = harness rule-4 floor, served fallback for
uncovered rows. No hour gate (rule 8): every rule is applied at all local hours.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t5_nbh_latest
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t5")
NBH = Path(r"C:\swarm\data\nbh\nbh_tidy.parquet")
NBH_MANIFEST = Path(r"C:\swarm\data\nbh\MANIFEST.json")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
HIST_START, HIST_END = "2026-07-25", "2026-07-31"
HIST_CYCLE_CUT = pd.Timestamp("2026-08-01T00:00Z")
SIG_MIN = 1.0
BLOCKS = {"00-05": range(0, 6), "06-09": range(6, 10), "10-12": range(10, 13), "13-16": range(13, 17),
          "17-23": range(17, 24)}

RULES = {
    "t5-r1": "T5-r1 NBH latest cycle, remaining-hours max (hourly-row settlement shape). At snapshot t "
             "(market station, local target date D, end E = local midnight ending D), NBM NBH text-bulletin "
             "cycles (S3 blend_nbhtx, A-NBH nbh_tidy.parquet) are eligible only if S3 LastModified <= "
             "captured_at_utc. For every hourly valid time v in (t, E], take TMP and TSD from the latest "
             "eligible cycle carrying v (the latest eligible cycle carries all v within its 25 h horizon). "
             "mu = max TMP over those v, sigma = max(TSD at the argmax v, 1). X ~ Normal(mu, sigma) "
             "discretised on integers (mass on [k-0.5, k+0.5)); final H = max(B, X) with B = floor(F+0.5), "
             "F = harness rule-4 floor; band probability = P(H in band). No eligible cycle or some v "
             "uncovered -> served fallback. Zero fitted parameters. Applied at all local hours (no gate).",
    "t5-r2": "T5-r2 = t5-r1 with per-local-hour-block (00-05, 06-09, 10-12, 13-16, 17-23 of t) bias b and "
             "sigma scale s: mu' = mu + b, sigma' = max(s*sigma, 1). Fitted on history only: NBH cycles with "
             "cycle_utc < 2026-08-01 (S3 2026-07-25..07-31), same PIT cycle selection, simulated snapshots "
             "at local hh:00 and hh:30 of local dates 2026-07-25..2026-07-31; residual R = max of rounded "
             "tmpf over IEM METAR routine non-COR rows of D valid in (t, E] minus mu; b = median R, "
             "s = sqrt(mean(((R-b)/sigma)^2)). Applied at all local hours (no gate).",
    "t5-d1": "T5-d1 DIAGNOSTIC (not a new candidate): t5-r1 and t5-r2 (frozen b, s) with every NBH object "
             "treated as available 60 minutes after its S3 LastModified. PIT stress only.",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- NBH loading

def load_nbh(extra_lag_min=0):
    d = pd.read_parquet(NBH, columns=["station", "field", "value", "cycle_utc", "valid_utc", "available_utc"],
                        filters=[("field", "in", ["TMP", "TSD"])])
    assert d.available_utc.notna().all(), "NBH rows without LastModified"
    d["available_utc"] = d.available_utc + pd.Timedelta(minutes=extra_lag_min)
    piv = d.pivot_table(index=["station", "cycle_utc", "valid_utc"], columns="field", values="value",
                        aggfunc="first").reset_index()
    av = d.groupby(["station", "cycle_utc"]).available_utc.first().rename("available_utc").reset_index()
    piv = piv.merge(av, on=["station", "cycle_utc"])
    out = {}
    for st, g in piv.groupby("station"):
        cyc = []
        for c, gc in g.groupby("cycle_utc"):
            gc = gc.sort_values("valid_utc")
            gc = gc[gc.TMP.notna()]
            cyc.append({"cycle": pd.Timestamp(c), "avail": pd.Timestamp(gc.available_utc.iloc[0]),
                        "v": gc.valid_utc.dt.as_unit("ns").astype("int64").to_numpy(),
                        "tmp": gc.TMP.to_numpy(float),
                        "tsd": gc.TSD.to_numpy(float) if "TSD" in gc else np.full(len(gc), np.nan)})
        out[st] = StationIndex(sorted(cyc, key=lambda x: x["cycle"]))
    return out


class StationIndex:
    def __init__(self, cycles):
        self.c = cycles
        self.avail = np.array([x["avail"].value for x in cycles], dtype=np.int64)
        self.cyc = np.array([x["cycle"].value for x in cycles], dtype=np.int64)

    def subset_before(self, cut):
        return StationIndex([x for x in self.c if x["cycle"] < cut])

    def remaining(self, t, end):
        """(mu, sigma_raw, latest_cycle, n_cycles_used) or None."""
        ok = np.flatnonzero(self.avail <= t)
        if not len(ok):
            return None
        order = ok[np.argsort(-self.cyc[ok])]
        first = self.c[order[0]]
        hours = np.arange(((t // 3600_000_000_000) + 1) * 3600_000_000_000, end + 1, 3600_000_000_000,
                          dtype=np.int64)
        if not len(hours):
            return None
        need = set(hours.tolist())
        vals = {}
        used = 0
        for i in order[:6]:
            x = self.c[i]
            hit = False
            for v, tm, sd in zip(x["v"], x["tmp"], x["tsd"]):
                if v in need and v not in vals:
                    vals[v] = (tm, sd)
                    hit = True
            used += hit
            if len(vals) == len(need):
                break
        if len(vals) < len(need):
            return None
        vmax = max(vals, key=lambda v: (vals[v][0], -v))
        mu, sd = vals[vmax]
        return float(mu), float(sd) if np.isfinite(sd) else np.nan, first, used


def band_probs(kind, low, high, B, mu, sig):
    """P(H in band), H = max(B, X), X ~ N(mu, sig) integer-discretised (same form as t6)."""
    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    cdf = lambda x: ndtr((x - mu) / sig)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, cdf(up) - cdf(lo), 0.0)
    return np.clip(p, 0.0, None)


def block_of(hr):
    for b, r in BLOCKS.items():
        if hr in r:
            return b


# ----------------------------------------------------------------------------- snapshots

def snapshot_frame():
    snaps, bands = h.candidate_inputs()
    s = snaps[["row_key", "market", "station", "date", "stratum", "local_hour", "block",
               "captured_at_utc", "captured_at_local", "floor", "n_bands"]].copy()
    assert (s.date <= "2026-09-29").all()
    cu = pd.to_datetime(s.captured_at_utc, utc=True)
    s["t_ns"] = cu.dt.as_unit("ns").astype("int64")
    off = s.captured_at_local.str[-6:]
    sign = np.where(off.str[0] == "-", -1, 1)
    off_min = sign * (off.str[1:3].astype(int) * 60 + off.str[4:6].astype(int))
    dnext = pd.to_datetime(s.date) + pd.Timedelta(days=1)
    s["end_ns"] = (dnext - pd.to_timedelta(off_min, unit="m")).dt.as_unit("ns").astype("int64")
    return s, bands


def build_candidate(idx, s, bands, params=None):
    offs = np.concatenate([[0], np.cumsum(s.n_bands.to_numpy())[:-1]]).astype(int)
    assert len(bands) == int(s.n_bands.sum())
    assert (bands.row_key.to_numpy()[offs] == s.row_key.to_numpy()).all(), "band/snapshot misalignment"
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    ages = np.full(len(s), np.nan)
    mus = np.full(len(s), np.nan)
    av_list, cap_list = [], []
    reasons = defaultdict(int)
    cache = {}
    recs = s[["station", "t_ns", "end_ns", "floor", "n_bands", "local_hour"]].to_numpy()
    for i, (st, t, end, F, n, lh) in enumerate(recs):
        si = idx.get(st)
        if si is None:
            reasons["no_station"] += 1
            continue
        if F is None or not np.isfinite(F):
            reasons["no_floor"] += 1
            continue
        key = (st, int(t) // 60_000_000_000, int(end))
        if key not in cache:
            cache[key] = si.remaining(int(t), int(end))
        r = cache[key]
        if r is None:
            reasons["no_cycle_or_uncovered_hours"] += 1
            continue
        mu, sd, c, used = r
        sig = max(sd if np.isfinite(sd) else SIG_MIN, SIG_MIN)
        if params is not None:
            b, sc = params[block_of(int(lh))]
            mu, sig = mu + b, max(sc * sig, SIG_MIN)
        B = math.floor(float(F) + .5)
        o = offs[i]
        p = band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() <= 0:
            reasons["zero_mass"] += 1
            continue
        p_out[o:o + n] = p / p.sum()
        ages[i] = (int(t) - c["cycle"].value) / 3.6e12
        mus[i] = mu
        av_list.append(c["avail"])
        cap_list.append(pd.Timestamp(int(t), tz="UTC"))
        reasons["covered"] += 1
    # rule 1: every covered snapshot's latest cycle (and, by construction, every older cycle it falls
    # back to, which has avail <= t by the eligibility filter) was available at or before t.
    h.assert_point_in_time(av_list, cap_list)
    covered = ~np.isnan(p_out)
    cand = bands.loc[covered, ["row_key", "band_index"]].copy()
    cand["p"] = p_out[covered]
    return cand, ages, mus, dict(reasons)


# ----------------------------------------------------------------------------- history fit (r2)

def fit_r2(idx):
    resid = defaultdict(list)
    sigs = defaultdict(list)
    for f in sorted(METAR_DIR.glob("K*.parquet")):
        st = f.stem
        if st not in idx:
            continue
        si = idx[st].subset_before(HIST_CYCLE_CUT)
        assert (si.cyc < HIST_CYCLE_CUT.value).all()
        m = pd.read_parquet(f, columns=["tmpf", "valid_utc", "local_date", "local_time", "is_cor",
                                        "report_type"])
        m = m[(~m.is_cor) & m.tmpf.notna() & (m.report_type == "routine")]
        m["ld"] = m.local_date.astype(str)
        m = m[(m.ld >= HIST_START) & (m.ld <= HIST_END)]
        m["t"] = np.floor(m.tmpf + .5)
        for ld, g in m.groupby("ld"):
            if len(g) < 18:
                continue
            o = g.local_time.iloc[0][-5:]
            off_min = (-1 if o[0] == "-" else 1) * (int(o[1:3]) * 60 + int(o[3:5]))
            d0 = pd.Timestamp(ld, tz="UTC") - pd.Timedelta(minutes=off_min)
            end = (d0 + pd.Timedelta(days=1)).value
            vt = g.valid_utc.dt.as_unit("ns").astype("int64").to_numpy()
            tt = g.t.to_numpy()
            for k in range(48):
                t = (d0 + pd.Timedelta(minutes=30 * k)).value
                r = si.remaining(t, end)
                if r is None:
                    continue
                mu, sd, c, _ = r
                assert c["avail"].value <= t
                rem = tt[vt > t]
                if not len(rem):
                    continue
                b = block_of(k // 2)
                resid[b].append(rem.max() - mu)
                sigs[b].append(max(sd if np.isfinite(sd) else SIG_MIN, SIG_MIN))
    params, stats = {}, {}
    for b in BLOCKS:
        r, sg = np.array(resid[b]), np.array(sigs[b])
        assert len(r) >= 50, f"thin history for {b}: {len(r)}"
        bb = float(np.median(r))
        sc = float(np.sqrt(np.mean(((r - bb) / sg) ** 2)))
        params[b] = (bb, sc)
        stats[b] = {"n": int(len(r)), "bias_median": bb, "sigma_scale": sc, "resid_mean": float(r.mean()),
                    "resid_sd": float(r.std()), "mean_tsd": float(sg.mean())}
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
        rec = {"id": rid, "agent": "t5", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(reg, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def summarize(res):
    out = {}
    for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
        out[g] = {"class": res["classes"].get(g, {}).get("class") if g in res["classes"] else None}
        for st in ("before_20260823", "from_20260823"):
            for pop in ("all_row", "matched"):
                try:
                    t = h.table_lookup(res, g, st, pop)
                except Exception:
                    continue
                if not t or t.get("status") == "NO_DATA":
                    continue
                cs, cm = t.get("candidate_minus_served", {}), t.get("candidate_minus_market", {})
                pm = t.get("per_market_delta") or {}
                vals = list(pm.values()) if isinstance(pm, dict) else []
                vals = [v.get("estimate", v) if isinstance(v, dict) else v for v in vals]
                out[g][f"{st}|{pop}"] = {
                    "cand_minus_served": cs.get("estimate"), "cms_ci95": cs.get("ci95"),
                    "cand_minus_market": cm.get("estimate"), "cmm_ci95": cm.get("ci95"),
                    "ratio": (t.get("ratio_candidate_to_market") or {}).get("estimate"),
                    "gap_closed_share": (t.get("gap_closed_share") or {}).get("estimate")
                    if isinstance(t.get("gap_closed_share"), dict) else t.get("gap_closed_share"),
                    "markets_neg": int(sum(1 for v in vals if v is not None and v < 0)),
                    "markets_n": len(vals),
                }
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    register(["t5-r1", "t5-r2", "t5-d1"])
    log("HARNESS", h.harness_sha256())
    s, bands = snapshot_frame()
    idx = load_nbh()
    log("NBH loaded", {k: len(v.c) for k, v in idx.items()})
    params, fit_stats = fit_r2(idx)
    log("r2 fit (history <= 07-31)", fit_stats)
    results = {"fit_r2": fit_stats, "HARNESS_SHA256": h.harness_sha256()}
    for name, prm in (("t5_r1_nbh_latest", None), ("t5_r2_nbh_latest_histcal", params)):
        cand, ages, mus, reasons = build_candidate(idx, s, bands, prm)
        res = h.score(cand, name=name)
        assert not res.get("leakage_suspect_groups"), f"LEAKAGE TRIPWIRE {res.get('leakage_suspect_groups')}"
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        cov = pd.DataFrame({"block": s.block, "stratum": s.stratum, "age": ages, "covd": ~np.isnan(ages)})
        results[name] = {
            "reasons": reasons,
            "coverage_by_block": cov.groupby("block").covd.mean().round(4).to_dict(),
            "median_cycle_age_h_by_block": cov.groupby("block").age.median().round(2).to_dict(),
            "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
            "summary": summarize(res),
            "tail": res.get("tail"),
        }
        log(name, results[name]["classes"])
    # d1 PIT stress
    idx60 = load_nbh(extra_lag_min=60)
    for name, prm in (("t5_d1_r1_lag60", None), ("t5_d1_r2_lag60", params)):
        cand, ages, mus, reasons = build_candidate(idx60, s, bands, prm)
        res = h.score(cand, name=name)
        assert not res.get("leakage_suspect_groups")
        h.save(res, OUT)
        results[name] = {"reasons": reasons, "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                         "summary": summarize(res)}
        log(name, results[name]["classes"])
    (OUT / "raw_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
