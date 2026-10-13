"""T10 hunter: ECMWF IFS (open data, oper 00/12Z) latest available run (model-parity swarm v2, development only).

Rules (registered in C:\\swarm\\registry.jsonl before any score; text in RULES):
  t10-r1  latest IFS run, remaining-hours max over 2t (3-hourly instantaneous) UNION mx2t3 (3-h window max)
          windows fully inside the remaining interval; Gaussian with per-block RMS spread fitted on history
          (local dates 2026-07-25..07-31, runs before 08-01); bias 0. H = max(B, X).
  t10-r2  t10-r1 with per-block median bias b and spread s fitted on the same history.
  t10-r3  undersampled variant: 2t samples only (no mx2t3), per-block b, s fitted on the same history.
Controls (attribution only):
  t10-c1  NO-SOURCE control: same Gaussian form, centre = harness floor F + per-block b, spread s, fitted on the
          same history with the PIT METAR running max as anchor. r2 - c1 isolates the IFS values from the
          floor-anchored remaining-rise family (T1/T2/T3/T4/T15/T16).
  t10-c2  captured NBM v2_mean control: mu = v2_mean, sigma = max(v2_stddev, 1) where v2_available_at <=
          captured_at_utc (r-t5-inc-c1 form). r2 - c2 isolates IFS against what production already captures.
Diagnostics: t10-d1 (r2 with availability = conservative max(run+8h, LastModified), and +60 min stress).

Point in time: an IFS run enters snapshot t only if max per-object S3 LastModified over that station's run
(A-ECMWF values.parquet, available_utc_measured) <= captured_at_utc; asserted via h.assert_point_in_time.
No market input, no labels; floor = harness rule-4 floor; served fallback; no hour gate.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t10_ecmwf_ifs
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
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\t10")
ECM = Path(r"C:\swarm\data\ecmwf\values.parquet")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
REG = Path(r"C:\swarm\registry.jsonl")
HIST_START, HIST_END = "2026-07-25", "2026-07-31"
HIST_RUN_CUT = pd.Timestamp("2026-08-01T00:00Z")
SIG_MIN = 1.0
H3 = 3 * 3600 * 10**9
BLOCKS = {"00-05": range(0, 6), "06-09": range(6, 10), "10-12": range(10, 13), "13-16": range(13, 17),
          "17-23": range(17, 24)}
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}

_COMMON = ("At snapshot t (market station, local target date D, E = local midnight ending D) the eligible "
           "ECMWF IFS open-data oper runs (00Z/12Z, AWS ecmwf-forecasts, A-ECMWF values.parquet, bilinear 2 m "
           "temperature at the station converted K->F) are those whose station-run max per-object S3 "
           "LastModified <= captured_at_utc; the latest eligible run is used. ")
RULES = {
    "t10-r1": "T10-r1 IFS latest run, remaining-hours max. " + _COMMON +
              "Remaining set = 2t values with valid time in (t, E] UNION mx2t3 values whose 3-h window "
              "[v-3h, v] lies inside [t, E]; if that set is empty (< 3 h left, no synoptic hour), the mx2t3 "
              "window with the smallest end > t. mu = max of the set (3-hourly undersampling of 2t is "
              "covered by mx2t3; mx2t3 is a model continuous max, not an hourly-row max). X ~ Normal(mu, "
              "sigma_blk) integer-discretised; H = max(B, X), B = floor(F+0.5), F = harness rule-4 floor. "
              "sigma_blk = max(1, RMS of R) per local-hour block of t, R = (max rounded tmpf of IEM METAR "
              "routine non-COR rows of D valid in (t, E]) - mu, on simulated snapshots at local hh:00/hh:30 "
              "of local dates 2026-07-25..07-31 using only runs with run time < 2026-08-01 and the same PIT "
              "selection. Bias 0. Run must carry valid times up to E. Else served fallback. No hour gate.",
    "t10-r2": "T10-r2 = t10-r1 with per-block bias: mu' = mu + b_blk, sigma = max(1, s_blk), b = median R, "
              "s = sqrt(mean((R-b)^2)), same history fit (local dates 07-25..07-31, runs < 08-01). No gate.",
    "t10-r3": "T10-r3 undersampled IFS: as t10-r2 but the remaining set is 2t values only with valid time in "
              "(t, E] (if empty, the first 2t value after t); b, s refitted on the same history in this form. "
              "Measures the 3-hourly undersampling cost. No gate.",
    "t10-c1": "T10-c1 CONTROL (attribution only, no IFS values): X ~ Normal(F + b_blk, max(1, s_blk)), H = "
              "max(B, X); b, s fitted per block on the same history snapshots with R = remaining METAR max - "
              "PIT METAR running max (routine non-COR rows of D with valid+10min <= t, rounded). Covers "
              "exactly the rows t10-r2 covers. Paired with t10-r1/r2/r3 to isolate the IFS information.",
    "t10-c2": "T10-c2 CONTROL (attribution only): captured NBM v2_mean, sigma = max(v2_stddev, 1), H = max(B, "
              "X), only where v2_available_at <= captured_at_utc, restricted to rows t10-r2 covers "
              "(r-t5-inc-c1 form). Paired with t10-r2 to isolate IFS against already-captured guidance.",
    "t10-d1": "T10-d1 DIAGNOSTIC (not a candidate): t10-r2 (frozen b, s) with availability = conservative "
              "max(run+8h, LastModified), and with LastModified + 60 min. PIT stress only.",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def register():
    have = set()
    if REG.exists():
        for line in REG.read_text(encoding="utf-8").splitlines():
            try:
                have.add(json.loads(line)["id"])
            except Exception:
                pass
    for rid, text in RULES.items():
        if rid in have:
            continue
        rec = {"id": rid, "agent": "t10", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(REG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


# ----------------------------------------------------------------------------- IFS loading

def _ns(x):
    return pd.to_datetime(x).dt.as_unit("ns").astype("int64").to_numpy()


def load_ifs(avail="measured", extra_lag_min=0):
    d = pd.read_parquet(ECM)
    d = d[d.usable].copy()
    d["F"] = (d.bilinear_K - 273.15) * 9 / 5 + 32
    col = {"measured": "available_utc_measured", "conservative": "available_utc_conservative"}[avail]
    out = {}
    for st, g in d.groupby("station"):
        runs = []
        for run, gr in g.groupby("run_utc"):
            av = pd.Timestamp(gr[col].max(), tz="UTC") + pd.Timedelta(minutes=extra_lag_min)
            t2 = gr[gr.param == "2t"].sort_values("valid_utc")
            mx = gr[gr.param == "mx2t3"].sort_values("valid_utc")
            runs.append({"run": pd.Timestamp(run, tz="UTC"), "avail": av,
                         "v2": _ns(t2.valid_utc), "f2": t2.F.to_numpy(),
                         "ve": _ns(mx.valid_utc), "vs": _ns(mx.window_start_utc), "fm": mx.F.to_numpy()})
        out[st] = Station(sorted(runs, key=lambda r: r["run"]))
    return out


class Station:
    def __init__(self, runs):
        self.r = runs
        self.avail = np.array([x["avail"].value for x in runs], dtype=np.int64)
        self.run = np.array([x["run"].value for x in runs], dtype=np.int64)

    def subset_before(self, cut):
        return Station([x for x in self.r if x["run"] < cut])

    def latest(self, t):
        ok = np.flatnonzero(self.avail <= t)
        if not len(ok):
            return None
        return self.r[ok[np.argmax(self.run[ok])]]

    def remaining(self, t, end, mode):
        x = self.latest(t)
        if x is None:
            return None
        if not len(x["v2"]) or x["v2"].max() < end:
            return None
        if mode == "mix":
            m2 = (x["v2"] > t) & (x["v2"] <= end)
            mm = (x["vs"] >= t) & (x["ve"] <= end)
            vals = np.r_[x["f2"][m2], x["fm"][mm]]
            if not len(vals):
                c = np.flatnonzero(x["ve"] > t)
                if not len(c):
                    return None
                vals = np.array([x["fm"][c[np.argmin(x["ve"][c])]]])
        else:
            m2 = (x["v2"] > t) & (x["v2"] <= end)
            vals = x["f2"][m2]
            if not len(vals):
                c = np.flatnonzero(x["v2"] > t)
                if not len(c):
                    return None
                vals = np.array([x["f2"][c[0]]])
        return float(vals.max()), x


def band_probs(kind, low, high, B, mu, sig):
    kind = np.asarray(kind)
    low = np.asarray(low, float)
    high = np.asarray(high, float)
    cdf = lambda z: ndtr((z - mu) / sig)
    up = np.where(kind == "gte", np.inf, high + .5)
    lo = np.where((kind == "lte") | (low <= B), -np.inf, low - .5)
    possible = (kind == "gte") | (high >= B)
    return np.clip(np.where(possible, cdf(up) - cdf(lo), 0.0), 0.0, None)


def block_of(hr):
    for b, r in BLOCKS.items():
        if hr in r:
            return b


# ----------------------------------------------------------------------------- snapshots

def snapshot_frame():
    snaps, bands = h.candidate_inputs()
    s = snaps[["row_key", "market", "station", "date", "stratum", "local_hour", "block",
               "captured_at_utc", "captured_at_local", "floor", "n_bands", "v2_mean", "v2_stddev",
               "v2_available_at"]].copy()
    assert (s.date <= "2026-09-29").all()
    cu = pd.to_datetime(s.captured_at_utc, utc=True)
    s["t_ns"] = cu.dt.as_unit("ns").astype("int64")
    off = s.captured_at_local.str[-6:]
    sign = np.where(off.str[0] == "-", -1, 1)
    off_min = sign * (off.str[1:3].astype(int) * 60 + off.str[4:6].astype(int))
    dnext = pd.to_datetime(s.date) + pd.Timedelta(days=1)
    s["end_ns"] = (dnext - pd.to_timedelta(off_min, unit="m")).dt.as_unit("ns").astype("int64")
    return s, bands


def build(idx, s, bands, mode, params, control=None, restrict=None):
    """mode 'mix'|'2t'; control None|'c1'|'c2'. params: block -> (b, sig). restrict: bool mask of snaps."""
    offs = np.concatenate([[0], np.cumsum(s.n_bands.to_numpy())[:-1]]).astype(int)
    assert (bands.row_key.to_numpy()[offs] == s.row_key.to_numpy()).all(), "band/snapshot misalignment"
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    p_out = np.full(len(bands), np.nan)
    covered = np.zeros(len(s), bool)
    ages = np.full(len(s), np.nan)
    mus = np.full(len(s), np.nan)
    av_list, cap_list = [], []
    reasons = defaultdict(int)
    v2m = s.v2_mean.to_numpy(float)
    v2s = s.v2_stddev.to_numpy(float)
    v2a = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    v2ok = (v2a.notna() & (v2a.dt.as_unit("ns").astype("int64") <= s.t_ns) & np.isfinite(v2m)).to_numpy()
    cache = {}
    recs = s[["station", "t_ns", "end_ns", "floor", "n_bands", "local_hour"]].to_numpy()
    for i, (st, t, end, F, n, lh) in enumerate(recs):
        if restrict is not None and not restrict[i]:
            reasons["outside_restrict"] += 1
            continue
        si = idx.get(st)
        if si is None:
            reasons["no_station"] += 1
            continue
        if F is None or not np.isfinite(F):
            reasons["no_floor"] += 1
            continue
        key = (st, int(t) // 60_000_000_000, int(end))
        if key not in cache:
            cache[key] = si.remaining(int(t), int(end), mode)
        r = cache[key]
        if r is None:
            reasons["no_run_or_short_horizon"] += 1
            continue
        mu, x = r
        b, sig = params[block_of(int(lh))]
        if control == "c1":
            mu = float(F) + b
        elif control == "c2":
            if not v2ok[i]:
                reasons["no_v2"] += 1
                continue
            mu, sig = v2m[i], max(v2s[i] if np.isfinite(v2s[i]) else SIG_MIN, SIG_MIN)
        else:
            mu = mu + b
        sig = max(sig, SIG_MIN)
        B = math.floor(float(F) + .5)
        o = offs[i]
        p = band_probs(kinds[o:o + n], lows[o:o + n], highs[o:o + n], B, mu, sig)
        if p.sum() <= 0:
            reasons["zero_mass"] += 1
            continue
        p_out[o:o + n] = p / p.sum()
        covered[i] = True
        ages[i] = (int(t) - x["run"].value) / 3.6e12
        mus[i] = mu
        av_list.append(x["avail"])
        cap_list.append(pd.Timestamp(int(t), tz="UTC"))
        reasons["covered"] += 1
    h.assert_point_in_time(av_list, cap_list)
    if control == "c2":
        h.assert_point_in_time(list(v2a[covered & v2ok]), list(pd.to_datetime(s.t_ns[covered & v2ok], utc=True)))
    cm = ~np.isnan(p_out)
    cand = bands.loc[cm, ["row_key", "band_index"]].copy()
    cand["p"] = p_out[cm]
    return cand, covered, ages, mus, dict(reasons)


# ----------------------------------------------------------------------------- history fit

def fit(idx):
    """Residuals on history (local dates 07-25..07-31, runs < 08-01) for mix, 2t and the c1 anchor."""
    res = {k: defaultdict(list) for k in ("mix", "2t", "c1")}
    for f in sorted(METAR_DIR.glob("K*.parquet")):
        st = f.stem
        if st not in idx:
            continue
        si = idx[st].subset_before(HIST_RUN_CUT)
        assert (si.run < HIST_RUN_CUT.value).all()
        m = pd.read_parquet(f, columns=["tmpf", "valid_utc", "available_utc", "local_date", "local_time",
                                        "is_cor", "report_type"])
        m = m[(~m.is_cor) & m.tmpf.notna() & (m.report_type == "routine")]
        m["ld"] = m.local_date.astype(str)
        m = m[(m.ld >= HIST_START) & (m.ld <= HIST_END)]
        m["tr"] = np.floor(m.tmpf + .5)
        for ld, g in m.groupby("ld"):
            if len(g) < 18:
                continue
            o = g.local_time.iloc[0][-5:]
            off_min = (-1 if o[0] == "-" else 1) * (int(o[1:3]) * 60 + int(o[3:5]))
            d0 = pd.Timestamp(ld, tz="UTC") - pd.Timedelta(minutes=off_min)
            end = (d0 + pd.Timedelta(days=1)).value
            vt = g.valid_utc.dt.as_unit("ns").astype("int64").to_numpy()
            at = g.available_utc.dt.as_unit("ns").astype("int64").to_numpy()
            tt = g.tr.to_numpy()
            for k in range(48):
                t = (d0 + pd.Timedelta(minutes=30 * k)).value
                rem = tt[vt > t]
                if not len(rem):
                    continue
                b = block_of(k // 2)
                past = tt[at <= t]
                for mode in ("mix", "2t"):
                    r = si.remaining(t, end, mode)
                    if r is None:
                        continue
                    assert r[1]["avail"].value <= t
                    res[mode][b].append(rem.max() - r[0])
                    if mode == "mix" and len(past):
                        res["c1"][b].append(rem.max() - past.max())
    params, stats = {}, {}
    for k in res:
        params[k], stats[k] = {}, {}
        for b in BLOCKS:
            r = np.array(res[k][b], float)
            assert len(r) >= 50, f"thin history {k} {b}: {len(r)}"
            med = float(np.median(r))
            stats[k][b] = {"n": int(len(r)), "median": med, "mean": float(r.mean()),
                           "rms": float(np.sqrt(np.mean(r ** 2))),
                           "sd_about_median": float(np.sqrt(np.mean((r - med) ** 2)))}
            params[k][b] = (med, stats[k][b]["sd_about_median"])
    r1 = {b: (0.0, stats["mix"][b]["rms"]) for b in BLOCKS}
    return {"r1": r1, "r2": params["mix"], "r3": params["2t"], "c1": params["c1"]}, stats


# ----------------------------------------------------------------------------- summaries

def summarize(res):
    out = {}
    for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
        out[g] = {"class": res["classes"].get(g, {}).get("class")}
        for st in (BEFORE, FROM, "pooled"):
            for pop in ("all_row", "matched"):
                try:
                    t = h.table_lookup(res, g, st, pop)
                except Exception:
                    continue
                if not t or t.get("status") == "NO_DATA":
                    continue
                cs, cm = t.get("candidate_minus_served", {}), t.get("candidate_minus_market", {})
                pm = t.get("per_market_delta") or {}
                vals = [v.get("estimate", v) if isinstance(v, dict) else v for v in pm.values()] \
                    if isinstance(pm, dict) else []
                rt = t.get("ratio_candidate_to_market") or {}
                out[g][f"{st}|{pop}"] = {
                    "cand_minus_served": cs.get("estimate"), "cms_ci95": cs.get("ci95"),
                    "cand_minus_market": cm.get("estimate"), "cmm_ci95": cm.get("ci95"),
                    "ratio": rt.get("estimate"), "ratio_interpretable": rt.get("interpretable"),
                    "markets_neg": int(sum(1 for v in vals if v is not None and v < 0)),
                    "markets_n": len(vals),
                }
    return out


def paired(d, frames, pairs):
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    for k, pc in frames.items():
        fr[k] = h._snapshot_mean(d, (pc - d.y) ** 2)
    out = {}
    for a, b in pairs:
        res = {}
        for g, (lo, hi) in GROUPS.items():
            for stt in (BEFORE, FROM, "pooled"):
                m = fr.local_hour.between(lo, hi)
                if stt != "pooled":
                    m &= fr.stratum == stt
                c = fr[m].groupby(["date", "market"], sort=True)[[a, b]].mean().reset_index()
                ix = np.array([d.key_index[(x, y)] for x, y in zip(c.date, c.market)])
                diff = (c[a] - c[b]).to_numpy()
                iv = h.interval(ix, diff)
                pm = c.assign(dd=diff).groupby("market").dd.mean()
                res[f"{g}|{stt}"] = {"estimate": iv["estimate"], "ci95": iv["ci95"],
                                     "markets_negative": int((pm < 0).sum()),
                                     "markets_positive": int((pm > 0).sum()), "market_days": int(len(c))}
        out[f"{a} - {b}"] = res
    return out


def main():
    stop_check()
    OUT.mkdir(parents=True, exist_ok=True)
    register()
    log("HARNESS", h.harness_sha256())
    s, bands = snapshot_frame()
    idx = load_ifs("measured")
    log("IFS loaded", {k: len(v.r) for k, v in idx.items()})
    lags = [(x["avail"] - x["run"]).total_seconds() / 3600 for v in idx.values() for x in v.r]
    params, fstats = fit(idx)
    log("fit", json.dumps(params))
    results = {"HARNESS_SHA256": h.harness_sha256(), "fit_params": params, "fit_stats": fstats,
               "measured_lag_h": {"min": min(lags), "max": max(lags), "mean": float(np.mean(lags))}}
    cands, covs = {}, {}
    specs = [("t10-r1", "mix", "r1", None), ("t10-r2", "mix", "r2", None), ("t10-r3", "2t", "r3", None)]
    for rid, mode, pk, ctl in specs:
        cands[rid], covs[rid], ages, mus, reasons = build(idx, s, bands, mode, params[pk], ctl)
        results.setdefault("build", {})[rid] = {
            "reasons": reasons,
            "coverage_by_block": pd.Series(covs[rid]).groupby(s.block.to_numpy()).mean().round(4).to_dict(),
            "median_run_age_h_by_block": pd.Series(ages).groupby(s.block.to_numpy()).median().round(2).to_dict()}
    restrict = covs["t10-r2"]
    for rid, pk, ctl in (("t10-c1", "c1", "c1"), ("t10-c2", "r2", "c2")):
        cands[rid], covs[rid], _, _, reasons = build(idx, s, bands, "mix", params[pk], ctl, restrict)
        results["build"][rid] = {"reasons": reasons}
    names = {"t10-r1": "t10_r1_ifs_mix", "t10-r2": "t10_r2_ifs_mix_cal", "t10-r3": "t10_r3_ifs_2t_only",
             "t10-c1": "t10_c1_nosource_control", "t10-c2": "t10_c2_v2mean_control"}
    for rid, nm in names.items():
        stop_check()
        res = h.score(cands[rid], name=nm)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res.get("leakage_suspect_groups"):
            Path(r"C:\swarm\STOP").write_text(f"t10 leakage suspect {rid} {res['leakage_suspect_groups']}\n")
            sys.exit("leakage")
        h.save(res, OUT)
        (OUT / f"{nm}.md").write_text(h.markdown(res), encoding="utf-8")
        results[rid] = {"classes": {g: v["class"] for g, v in res["classes"].items()},
                        "summary": summarize(res), "tail": res.get("tail"),
                        "reason_counts": res.get("reason_counts")}
        log(rid, results[rid]["classes"])
    # diagnostics d1
    for tag, av, lag in (("cons", "conservative", 0), ("lag60", "measured", 60)):
        stop_check()
        idd = load_ifs(av, lag)
        c, _, _, _, reasons = build(idd, s, bands, "mix", params["r2"], None)
        res = h.score(c, name=f"t10_d1_r2_{tag}")
        assert not res.get("leakage_suspect_groups")
        h.save(res, OUT)
        results[f"t10-d1-{tag}"] = {"classes": {g: v["class"] for g, v in res["classes"].items()},
                                    "summary": summarize(res), "reasons": reasons}
        log(tag, results[f"t10-d1-{tag}"]["classes"])
    # paired marginals
    d = h.data()
    t3c, _ = t3.build()
    cands["t3-r3"] = t3c["t3-r3"]
    frames = {k: h._candidate_vector(c, d, False)[0] for k, c in cands.items()}
    frames["served"] = d.p_served
    pairs = [("t10-r1", "t3-r3"), ("t10-r2", "t3-r3"), ("t10-r3", "t3-r3"), ("t10-r2", "t10-c1"),
             ("t10-r1", "t10-c1"), ("t10-r2", "t10-c2"), ("t10-r2", "t10-r3"), ("t10-c1", "t3-r3"),
             ("t10-r2", "served")]
    results["paired"] = paired(d, frames, pairs)
    (OUT / "raw_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    for k, v in results["paired"].items():
        print("==", k)
        for g in GROUPS:
            r, rb = v[f"{g}|{FROM}"], v[f"{g}|{BEFORE}"]
            print(f"  {g:6s} from {r['estimate']:+.6f} [{r['ci95'][0]:+.6f},{r['ci95'][1]:+.6f}] "
                  f"{r['markets_negative']}-/{r['markets_positive']}+  before {rb['estimate']:+.6f}")
    log("done")


if __name__ == "__main__":
    main()
