"""T8 hunter: HRRR latest available run via Open-Meteo Single-Runs (model-parity swarm v2, development only).

Rules (registered in C:\\swarm\\registry.jsonl before any score; text in RULES):
  t8-r1  HRRR latest available run, remaining-hours max, zero fitted parameters (sigma fixed a priori 2.0 F).
  t8-r2  t8-r1 with per-block bias/sigma fitted on METAR remaining-hours residuals, local dates
         2026-07-25..2026-08-22 (history + before stratum only).
  t8-r3  t8-r2 with a precipitation conditioner (HRRR remaining-hours max hourly precip >= 0.5 mm).
  t8-r4  t8-r2 with a cloud conditioner (HRRR mean cloud_cover over remaining hours >= 75%).
  t8-c1  CONTROL, no source: same form and fit, mu = PIT METAR running max (fit) / floor bucket (serve).
  t8-c2  CONTROL, captured production HRRR: mu = captured hrrr_high (hrrr_fetched_at <= captured_at_utc),
         sigma = t8-r2 block sigma, no bias.
  t8-d1  DIAGNOSTIC: t8-r1 / t8-r2 with availability run + 5 h (PIT stress, +2 h).

Point in time: an HRRR run enters a snapshot only if run_utc + 3 h (A-SingleRuns available_utc_design;
Open-Meteo meta.json sample showed ~1.5 h; AWS f00-f12 lands +52..67 min) <= captured_at_utc; asserted with
h.assert_point_in_time on every covered snapshot. No market input, no labels; floor = harness rule-4 floor
(B = floor(F + 0.5)); served fallback for uncovered rows. No hour gate: every rule applies at all hours.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t8_hrrr_latest
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t8")
SR = Path(r"C:\swarm\data\singleruns\singleruns_long.parquet")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
STOP = Path(r"C:\swarm\STOP")
FIT_START, FIT_END = "2026-07-25", "2026-08-22"
SIG_R1 = 2.0
SIG_MIN = 1.0
WET_MM = 0.5
CLOUDY_PCT = 75.0
MIN_CELL = 50
HOUR_NS = 3600_000_000_000
BLOCKS = {"00-05": range(0, 6), "06-09": range(6, 10), "10-12": range(10, 13), "13-16": range(13, 17),
          "17-23": range(17, 24)}

_COMMON = ("At snapshot t (market station, local target date D, E = local midnight ending D), Open-Meteo "
           "Single-Runs ncep_hrrr_conus runs (A-SingleRuns singleruns_long.parquet; runs 06/09/12/15/18/21Z) "
           "are eligible only if run_utc + 3 h <= captured_at_utc. For every hourly valid time v in (t, E], "
           "temperature_2m is taken from the latest eligible run carrying v (older eligible runs fill hours "
           "beyond the latest run's horizon; up to 6 runs). mu = max over those v. X ~ Normal(mu', sigma') "
           "discretised on integers (mass on [k-0.5, k+0.5)); final H = max(B, X), B = floor(F+0.5), F = "
           "harness rule-4 floor; band probability = P(H in band), renormalised. Any v uncovered or no "
           "eligible run -> served fallback. Applied at all local hours (no hour gate). ")
_FIT = ("Fit (no settlement/market input): simulated snapshots at local hh:00 and hh:30 of local dates "
        "2026-07-25..2026-08-22 (history + before stratum only), same PIT run selection; residual R = max of "
        "half-up-rounded T-group temperature (F) over IEM METAR routine+SPECI non-COR rows of D with valid "
        "time in (t, E] minus mu; per cell b = median R, s = sqrt(mean(((R-b))^2)); mu' = mu + b, "
        "sigma' = max(s, 1). ")
RULES = {
    "t8-r1": "T8-r1 HRRR latest available run, remaining-hours max, zero fitted parameters. " + _COMMON +
             "mu' = mu, sigma' = 2.0 F (fixed a priori).",
    "t8-r2": "T8-r2 HRRR latest run, remaining-hours max with per-block calibration. " + _COMMON + _FIT +
             "Cells = local-hour block of t (00-05, 06-09, 10-12, 13-16, 17-23).",
    "t8-r3": "T8-r3 HRRR latest run with precipitation conditioner (convection truncation). " + _COMMON + _FIT +
             "Cells = block x wet, wet = max HRRR hourly precipitation over the same remaining hours (same "
             "run selection) >= 0.5 mm; a cell with < 50 fit residuals uses its block's t8-r2 parameters.",
    "t8-r4": "T8-r4 HRRR latest run with cloud conditioner. " + _COMMON + _FIT +
             "Cells = block x cloudy, cloudy = mean HRRR cloud_cover over the same remaining hours >= 75%; a "
             "cell with < 50 fit residuals uses its block's t8-r2 parameters.",
    "t8-c1": "T8-c1 CONTROL (attribution only, no HRRR values): coverage mask identical to t8-r2 (same PIT "
             "HRRR eligibility, so the same rows fall back). mu = remaining-rise base: in the fit, the PIT "
             "METAR running max of D (rows available <= t, same rounding; snapshots without a row skipped); "
             "at serve, B. Same Normal/discretisation/max(B,X) form; per-block b, s fitted exactly as t8-r2 "
             "with that base in place of the HRRR max. Isolates HRRR values from the remaining-rise family.",
    "t8-c2": "T8-c2 CONTROL (attribution only): production's captured hrrr_high (Open-Meteo HRRR day high "
             "already in the table) as mu, only where hrrr_fetched_at <= captured_at_utc and on the t8-r2 "
             "coverage mask (same PIT Single-Runs eligibility, else served fallback); sigma = t8-r2 "
             "block sigma; no bias; X ~ N(mu, sigma) integer-discretised, H = max(B, X). Isolates the "
             "remaining-hours Single-Runs read against what production already captures.",
    "t8-d1": "T8-d1 DIAGNOSTIC (not a candidate): t8-r1 and t8-r2 (frozen parameters) with HRRR availability "
             "taken as run_utc + 5 h (PIT stress, +2 h over the design delay).",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def check_stop():
    if STOP.exists():
        sys.exit("STOP present: " + STOP.read_text(encoding="utf-8", errors="replace")[:200])


def register(ids):
    have = set()
    if REGISTRY.exists():
        for line in REGISTRY.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["id"])
            except Exception:
                pass
    for rid in ids:
        if rid in have:
            continue
        text = RULES[rid]
        rec = {"id": rid, "agent": "t8", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(REGISTRY, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def block_of(hr):
    for b, r in BLOCKS.items():
        if hr in r:
            return b


# ----------------------------------------------------------------------------- HRRR index

class StationIndex:
    def __init__(self, runs):
        self.r = sorted(runs, key=lambda x: x["run"])
        self.avail = np.array([x["avail"] for x in self.r], dtype=np.int64)
        self.run = np.array([x["run"] for x in self.r], dtype=np.int64)

    def remaining(self, t, end):
        ok = np.flatnonzero(self.avail <= t)
        if not len(ok):
            return None
        order = ok[np.argsort(-self.run[ok])]
        hours = np.arange(((t // HOUR_NS) + 1) * HOUR_NS, end + 1, HOUR_NS, dtype=np.int64)
        if not len(hours):
            return None
        need = set(hours.tolist())
        vals = {}
        for i in order[:6]:
            x = self.r[i]
            for v, tm, pr, cc in zip(x["v"], x["t"], x["p"], x["c"]):
                if v in need and v not in vals and np.isfinite(tm):
                    vals[v] = (tm, pr, cc)
            if len(vals) == len(need):
                break
        if len(vals) < len(need):
            return None
        arr = np.array([vals[v] for v in sorted(vals)], float)
        latest = self.r[order[0]]
        pmax = np.nanmax(arr[:, 1]) if np.isfinite(arr[:, 1]).any() else 0.0
        cmean = np.nanmean(arr[:, 2]) if np.isfinite(arr[:, 2]).any() else 0.0
        return {"mu": float(arr[:, 0].max()), "wet": bool(pmax >= WET_MM), "cloudy": bool(cmean >= CLOUDY_PCT),
                "run": latest["run"], "avail": latest["avail"], "age_h": (t - latest["run"]) / 3.6e12}


def load_hrrr(delay_h=3):
    d = pd.read_parquet(SR, columns=["station", "model", "run_utc", "valid_utc", "temperature_2m",
                                     "precipitation", "cloud_cover", "available_utc_design"])
    d = d[d.model == "ncep_hrrr_conus"].copy()
    # availability: design delay is run + 3 h; assert the manifest agrees, then apply the requested delay
    assert ((d.available_utc_design - d.run_utc) == pd.Timedelta(hours=3)).all()
    d["avail"] = d.run_utc + pd.Timedelta(hours=delay_h)
    out = {}
    for st, g in d.groupby("station"):
        runs = []
        for r, gr in g.groupby("run_utc"):
            gr = gr.sort_values("valid_utc")
            runs.append({"run": pd.Timestamp(r).value, "avail": pd.Timestamp(gr.avail.iloc[0]).value,
                         "v": gr.valid_utc.dt.as_unit("ns").astype("int64").to_numpy(),
                         "t": gr.temperature_2m.to_numpy(float), "p": gr.precipitation.to_numpy(float),
                         "c": gr.cloud_cover.to_numpy(float)})
        out[st] = StationIndex(runs)
    return out


# ----------------------------------------------------------------------------- probabilities

def band_probs(kind, low, high, B, mu, sig):
    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    cdf = lambda x: ndtr((x - mu) / sig)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    p = np.where(possible, cdf(up) - cdf(lo), 0.0)
    return np.clip(p, 0.0, None)


# ----------------------------------------------------------------------------- snapshots

def snapshot_frame():
    snaps, bands = h.candidate_inputs()
    s = snaps[["row_key", "market", "station", "date", "stratum", "local_hour", "block", "captured_at_utc",
               "captured_at_local", "floor", "n_bands", "hrrr_high", "hrrr_fetched_at"]].copy()
    assert (s.date <= "2026-09-29").all()
    cu = pd.to_datetime(s.captured_at_utc, utc=True)
    s["t_ns"] = cu.dt.as_unit("ns").astype("int64")
    off = s.captured_at_local.str[-6:]
    sign = np.where(off.str[0] == "-", -1, 1)
    off_min = sign * (off.str[1:3].astype(int) * 60 + off.str[4:6].astype(int))
    dnext = pd.to_datetime(s.date) + pd.Timedelta(days=1)
    s["end_ns"] = (dnext - pd.to_timedelta(off_min, unit="m")).dt.as_unit("ns").astype("int64")
    return s, bands


def param_for(rule, params, blk, info):
    if rule == "r1":
        return 0.0, SIG_R1
    if rule in ("r2", "c1"):
        return params[blk]
    flag = info["wet"] if rule == "r3" else info["cloudy"]
    return params.get((blk, flag), params[blk])


def build_candidate(rule, idx, s, bands, params=None, rows_out=None):
    offs = np.concatenate([[0], np.cumsum(s.n_bands.to_numpy())[:-1]]).astype(int)
    assert len(bands) == int(s.n_bands.sum())
    assert (bands.row_key.to_numpy()[offs] == s.row_key.to_numpy()).all(), "band/snapshot misalignment"
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    reasons = defaultdict(int)
    av_list, cap_list = [], []
    cache = {}
    info_rows = []
    hh = s.hrrr_high.to_numpy(float)
    hf = pd.to_datetime(s.hrrr_fetched_at, utc=True, errors="coerce")
    # missing fetch time -> year 2100, i.e. never available (excluded, not joined)
    hf_ns = hf.fillna(pd.Timestamp("2100-01-01", tz="UTC")).dt.as_unit("ns").astype("int64").to_numpy()
    recs = s[["station", "t_ns", "end_ns", "floor", "n_bands", "local_hour"]].to_numpy()
    for i, (st, t, end, F, n, lh) in enumerate(recs):
        si = idx.get(st)
        if si is None:
            reasons["no_station"] += 1
            info_rows.append(None)
            continue
        if F is None or not np.isfinite(F):
            reasons["no_floor"] += 1
            info_rows.append(None)
            continue
        key = (st, int(t) // 60_000_000_000, int(end))
        if key not in cache:
            cache[key] = si.remaining(int(t), int(end))
        info = cache[key]
        if info is None:
            reasons["no_run_or_uncovered_hours"] += 1
            info_rows.append(None)
            continue
        info_rows.append(info)
        B = math.floor(float(F) + .5)
        blk = block_of(int(lh))
        if rule == "c1":
            b, sig = params[blk]
            mu = B + b
        elif rule == "c2":
            if not (np.isfinite(hh[i]) and hf_ns[i] <= int(t)):
                reasons["no_captured_hrrr"] += 1
                continue
            mu = float(hh[i])
            sig = params[blk][1]
        else:
            b, sig = param_for(rule, params, blk, info)
            mu = info["mu"] + b
        sig = max(sig, SIG_MIN)
        o = offs[i]
        p = band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() <= 0:
            reasons["zero_mass"] += 1
            continue
        p_out[o:o + n] = p / p.sum()
        if rule == "c2":
            av_list.append(pd.Timestamp(int(hf_ns[i]), tz="UTC"))
        else:
            av_list.append(pd.Timestamp(int(info["avail"]), tz="UTC"))
        cap_list.append(pd.Timestamp(int(t), tz="UTC"))
        reasons["covered"] += 1
    h.assert_point_in_time(av_list, cap_list)       # rule 1 on every covered snapshot
    covered = ~np.isnan(p_out)
    cand = bands.loc[covered, ["row_key", "band_index"]].copy()
    cand["p"] = p_out[covered]
    if rows_out is not None:
        rows_out.extend(info_rows)
    return cand, dict(reasons)


# ----------------------------------------------------------------------------- fit

def load_metar_fit():
    out = {}
    for f in sorted(METAR_DIR.glob("K*.parquet")):
        m = pd.read_parquet(f, columns=["station", "valid_utc", "available_utc", "local_date", "local_time",
                                        "is_cor", "report_type", "tgroup_c", "main_temp_c"])
        m = m[(~m.is_cor) & m.report_type.isin(["routine", "speci"])].copy()
        m["ld"] = m.local_date.astype(str)
        m = m[(m.ld >= FIT_START) & (m.ld <= FIT_END)]
        tf = np.where(m.tgroup_c.notna(), m.tgroup_c * 1.8 + 32, m.main_temp_c * 1.8 + 32)
        m["tf"] = np.floor(tf + .5)
        m = m[np.isfinite(m.tf)]
        assert (m.ld <= "2026-08-22").all()
        out[f.stem] = m
    return out


def fit_all(idx, metar):
    """Residuals for HRRR (by block, wet, cloudy) and for the no-source base (by block)."""
    rec = []
    for st, m in metar.items():
        if st not in idx:
            continue
        si = idx[st]
        for ld, g in m.groupby("ld"):
            if (g.report_type == "routine").sum() < 18:
                continue
            o = g.local_time.iloc[0][-5:]
            off_min = (-1 if o[0] == "-" else 1) * (int(o[1:3]) * 60 + int(o[3:5]))
            d0 = pd.Timestamp(ld, tz="UTC") - pd.Timedelta(minutes=off_min)
            end = (d0 + pd.Timedelta(days=1)).value
            vt = g.valid_utc.dt.as_unit("ns").astype("int64").to_numpy()
            at = g.available_utc.dt.as_unit("ns").astype("int64").to_numpy()
            tt = g.tf.to_numpy()
            for k in range(48):
                t = (d0 + pd.Timedelta(minutes=30 * k)).value
                rem = tt[vt > t]
                if not len(rem):
                    continue
                info = si.remaining(t, end)
                if info is None:
                    continue
                assert info["avail"] <= t
                seen = tt[at <= t]
                base = float(seen.max()) if len(seen) else np.nan
                rec.append((block_of(k // 2), info["wet"], info["cloudy"], rem.max() - info["mu"],
                            rem.max() - base if np.isfinite(base) else np.nan, info["age_h"]))
    df = pd.DataFrame(rec, columns=["block", "wet", "cloudy", "R", "Rc", "age_h"])

    def cell(r):
        r = np.asarray(r, float)
        r = r[np.isfinite(r)]
        b = float(np.median(r))
        return b, max(float(np.sqrt(np.mean((r - b) ** 2))), SIG_MIN), int(len(r))

    p2, p3, p4, pc, stats = {}, {}, {}, {}, {}
    for blk in BLOCKS:
        g = df[df.block == blk]
        assert len(g) >= MIN_CELL, f"thin fit {blk}"
        b, s_, n = cell(g.R)
        p2[blk] = p3[blk] = p4[blk] = (b, s_)
        bc, sc, nc = cell(g.Rc)
        pc[blk] = (bc, sc)
        stats[blk] = {"r2": [b, s_, n], "c1": [bc, sc, nc]}
        for flag, pp, nm in (("wet", p3, "r3"), ("cloudy", p4, "r4")):
            for v in (False, True):
                gg = g[g[flag] == v]
                if len(gg) >= MIN_CELL:
                    bb, ss, nn = cell(gg.R)
                    pp[(blk, v)] = (bb, ss)
                    stats[blk][f"{nm}_{flag}={v}"] = [bb, ss, nn]
                else:
                    stats[blk][f"{nm}_{flag}={v}"] = ["fallback_to_block", int(len(gg))]
    stats["n_total"] = int(len(df))
    stats["wet_share"] = float(df.wet.mean())
    stats["cloudy_share"] = float(df.cloudy.mean())
    return {"r2": p2, "r3": p3, "r4": p4, "c1": pc}, stats


# ----------------------------------------------------------------------------- summary

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
                gc = t.get("gap_closed_share")
                out[g][f"{st}|{pop}"] = {
                    "cand_minus_served": cs.get("estimate"), "cms_ci95": cs.get("ci95"),
                    "cand_minus_market": cm.get("estimate"), "cmm_ci95": cm.get("ci95"),
                    "ratio": (t.get("ratio_candidate_to_market") or {}).get("estimate"),
                    "gap_closed_share": gc.get("estimate") if isinstance(gc, dict) else gc,
                    "markets_neg": int(sum(1 for v in vals if v is not None and v < 0)),
                    "markets_n": len(vals),
                }
    return out


def main():
    check_stop()
    OUT.mkdir(parents=True, exist_ok=True)
    register(list(RULES))
    log("HARNESS", h.harness_sha256())
    s, bands = snapshot_frame()
    idx = load_hrrr(3)
    log("HRRR runs", {k: len(v.r) for k, v in idx.items()})
    metar = load_metar_fit()
    params, fit_stats = fit_all(idx, metar)
    log("fit", json.dumps(fit_stats)[:1500])
    results = {"fit": fit_stats, "HARNESS_SHA256": h.harness_sha256(),
               "params": {k: {str(kk): vv for kk, vv in v.items()} for k, v in params.items()}}
    cands = {}
    infos = []
    for rule, name in (("r1", "t8_r1_hrrr_latest"), ("r2", "t8_r2_hrrr_latest_cal"),
                       ("r3", "t8_r3_hrrr_wet"), ("r4", "t8_r4_hrrr_cloudy"),
                       ("c1", "t8_c1_nosource_control"), ("c2", "t8_c2_captured_hrrr_control")):
        check_stop()
        prm = params.get("r2") if rule == "c2" else params.get(rule)
        cand, reasons = build_candidate(rule, idx, s, bands, prm, infos if rule == "r1" else None)
        cands[f"t8-{rule}"] = cand
        res = h.score(cand, name=name)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res.get("leakage_suspect_groups"):
            STOP.write_text(f"t8 leakage suspect {name} {res['leakage_suspect_groups']}\n")
            sys.exit("leakage suspect")
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        results[name] = {"reasons": reasons, "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                         "summary": summarize(res), "tail": res.get("tail")}
        log(name, results[name]["classes"])
    # coverage / age / conditioner prevalence
    ages = np.array([x["age_h"] if x else np.nan for x in infos])
    wet = np.array([x["wet"] if x else np.nan for x in infos], dtype=float)
    cl = np.array([x["cloudy"] if x else np.nan for x in infos], dtype=float)
    cov = pd.DataFrame({"block": s.block.to_numpy(), "stratum": s.stratum.to_numpy(), "age": ages,
                        "covd": ~np.isnan(ages), "wet": wet, "cloudy": cl})
    results["coverage_by_block"] = cov.groupby("block").covd.mean().round(4).to_dict()
    results["coverage_by_stratum"] = cov.groupby("stratum").covd.mean().round(4).to_dict()
    results["run_age_h_by_block"] = cov.groupby("block").age.describe()[["min", "50%", "max"]].round(2).to_dict()
    results["wet_share_by_block"] = cov.groupby("block").wet.mean().round(4).to_dict()
    results["cloudy_share_by_block"] = cov.groupby("block").cloudy.mean().round(4).to_dict()
    # PIT stress d1
    idx5 = load_hrrr(5)
    for rule, name in (("r1", "t8_d1_r1_avail5h"), ("r2", "t8_d1_r2_avail5h")):
        check_stop()
        cand, reasons = build_candidate(rule, idx5, s, bands, params.get(rule))
        res = h.score(cand, name=name)
        assert not res.get("leakage_suspect_groups")
        h.save(res, OUT)
        results[name] = {"reasons": reasons, "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                         "summary": summarize(res)}
        log(name, results[name]["classes"])
    # paired marginals: vs t3-r3 rung, vs no-source control, vs captured HRRR, conditioner increments
    from tools.research.model_parity import t3_baselines as t3
    from tools.research.model_parity import t6_nbs_controls as t6c
    t3c, _ = t3.build()
    cands["t3-r3"] = t3c["t3-r3"]
    d = h.data()
    frames = {k: h._candidate_vector(c, d, False)[0] for k, c in cands.items()}
    pairs = [("t8-r1", "t3-r3"), ("t8-r2", "t3-r3"), ("t8-r3", "t3-r3"), ("t8-r2", "t8-c1"),
             ("t8-r1", "t8-c1"), ("t8-c1", "t3-r3"), ("t8-r2", "t8-c2"), ("t8-r3", "t8-r2"),
             ("t8-r4", "t8-r2"), ("t8-r2", "t8-r1")]
    results["paired"] = t6c.paired(d, frames, pairs)
    (OUT / "raw_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    for k, v in results["paired"].items():
        print("==", k)
        for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
            r, rb = v[f"{g}|from_20260823"], v[f"{g}|before_20260823"]
            print(f"  {g:6s} from {r['estimate']:+.6f} [{r['ci95'][0]:+.6f},{r['ci95'][1]:+.6f}] "
                  f"{r['markets_negative']}/{r['markets_positive']}  before {rb['estimate']:+.6f}")
    log("done")


if __name__ == "__main__":
    main()
