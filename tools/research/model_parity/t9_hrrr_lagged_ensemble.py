"""T9 hunter: HRRR time-lagged ensemble (last K available Single-Runs HRRR runs). Development only.

Rules t9-r1..t9-r4, t9-r1s and controls t9-c1, t9-c2 are registered in C:\\swarm\\registry.jsonl
(agent t9) before the first score. Run from C:\\pt\\swarm:
    <repo python> -m tools.research.model_parity.t9_hrrr_lagged_ensemble

Point in time: a HRRR run enters snapshot t only if run_utc + 3 h (A-SingleRuns availability column
available_utc_conservative; P0/AWS LastModified shows +52..67 min, Open-Meteo meta +91..95 min) <= the
snapshot captured_at_utc, asserted with h.assert_point_in_time on every member used. Truth (IEM METAR
routine hourly rows, COR excluded, half-up F) is used only to fit b_h/s_h on local dates
2026-07-25..2026-08-22 (history + before stratum), never as a candidate input. No market input, no label
input; the harness applies the rule-4 floor and the served fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\t9")
SR = Path(r"C:\swarm\data\singleruns\singleruns_long.parquet")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text(encoding="utf-8"))["stations"]
FIT_START, FIT_END = "2026-07-25", "2026-08-22"   # history + before stratum only (rule 3/7)
NS_H = 3_600_000_000_000
SMIN = 0.5
LOOKBACK_H = 24
FROM, BEFORE = "from_20260823", "before_20260823"
GROUPS = {"00-05": (0, 5), "06-09": (6, 9), "10-12": (10, 12), "13-16": (13, 16), "17-23": (17, 23),
          "00-16": (0, 16), "all": (0, 23)}

COMMON = ("Common to t9 rules: HRRR = Open-Meteo Single-Runs ncep_hrrr_conus temperature_2m (degF) at the "
          "station point, runs 06/09/12/15/18/21Z (A-SingleRuns MANIFEST); a run is available at run_utc + 3 h "
          "and enters snapshot t only if available <= captured_at_utc (asserted). Local day D of the snapshot "
          "station = [start, end) in the station tz. Remaining-hours max of a run = max temperature_2m over "
          "valid hours v with t < v <= end and v > start (valid hour v stands for the routine METAR at about "
          "v-9 min); a run is a usable member only if run_utc >= t - 24 h and it has non-null values for every "
          "such v. Members = the last K usable runs by run time. Candidate X = max(F, Y), Y ~ Normal(mu + b_h, "
          "sigma): bands below the harness floor get 0, the first possible band gets P(Y < its upper edge), "
          "higher bands get Gaussian band masses (integer bands, +-0.5 edges); harness rule-4 floor mask and "
          "renormalisation; snapshots without a usable member fall back to served. b_h, s_h = mean and sd "
          "(floored at 0.5 F) of e = Yrem_truth - mu by snapshot local hour h, fitted on synthetic snapshots at "
          "local H:30 for local dates 2026-07-25..2026-08-22 only, Yrem_truth = max of routine METAR hourly rows "
          "(IEM, COR excluded, T-group tenths -> F half-up) of local day D not yet available at t (available = "
          "valid + 10 min). No market or label input. Scored by the harness (served-fallback all-row primary).")

RULES = {
    "t9-r1": "T9-r1 HRRR lagged-ensemble MEAN, K=4: mu = equal-weight mean of the K=4 members' remaining-hours "
             "max; sigma = s_h (hour-specific residual sd, ensemble spread unused). " + COMMON,
    "t9-r2": "T9-r2 HRRR lagged-ensemble MEAN + SPREAD, K=4: mu as t9-r1; sigma = sqrt(s0_h^2 + sd_ens^2) with "
             "sd_ens = sample sd (ddof=1) of the members' remaining-hours max (0 if one member) and s0_h^2 = "
             "max(var_h(e) - mean_h(sd_ens^2), 0.25) fitted on the same fit set (no other parameter). " + COMMON,
    "t9-r3": "T9-r3 CONTROL single latest HRRR run (K=1): mu = remaining-hours max of the latest usable run, "
             "sigma = its own s_h. Paired with r1/r2 to isolate the time-lagged ensemble increment. " + COMMON,
    "t9-r4": "T9-r4 sensitivity K=3: identical to t9-r1 with K=3 members. " + COMMON,
    "t9-r1s": "T9-r1s PIT sensitivity of t9-r1 (same rule, not a new hypothesis): every HRRR run availability "
              "delayed by a further 2 h (run_utc + 5 h) in both the fit and the serve-time member selection. " + COMMON,
    "t9-c1": "T9-c1 NO-SOURCE CONTROL (attribution only): same X = max(F, Y) Gaussian machinery and the same "
             "covered snapshots as t9-r1 (served fallback where t9-r1 has no member), but mu = F (the harness "
             "floor, captured) and b_h, s_h fitted as mean/sd of Yrem_truth - runmax_t (PIT METAR running max at "
             "local H:30) on the same fit dates; no HRRR value. Isolates HRRR information from the remaining-hours "
             "floor/collapse mechanism (T1/T2/T3 family).",
    "t9-c2": "T9-c2 CAPTURED-HRRR CONTROL (attribution only): mu = the snapshot's captured hrrr_high (production's "
             "Open-Meteo HRRR day high; used only where hrrr_fetched_at <= captured_at_utc) in the same X = max(F, "
             "Y) form, b_h, s_h = mean/sd of Yrem_truth - hrrr_high by local hour on BEFORE-stratum snapshots "
             "(Yrem_truth from IEM METAR rows not available at captured_at_utc); scored on the same covered "
             "snapshots as t9-r1. Isolates the new Single-Runs lagged ensemble from what production captures.",
}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def register():
    have = {json.loads(x)["id"] for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()}
    for rid, text in RULES.items():
        if rid in have:
            continue
        rec = {"id": rid, "agent": "t9", "text": text,
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
               "time_local": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with open(REGISTRY, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")


def check_registered():
    rows = [json.loads(x) for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    reg = {r["id"]: r for r in rows if r.get("agent") == "t9"}
    for rid, text in RULES.items():
        assert rid in reg and reg[rid]["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest(), rid


# ------------------------------------------------------------------ HRRR runs
def load_runs(extra_lag_h=0.0):
    d = pd.read_parquet(SR)
    d = d[(d.model == "ncep_hrrr_conus") & d.temperature_2m.notna()]
    d = d.assign(av=(d.available_utc_conservative + pd.Timedelta(hours=extra_lag_h)).dt.as_unit("ns").astype("int64"),
                 rt=d.run_utc.dt.as_unit("ns").astype("int64"), vt=d.valid_utc.dt.as_unit("ns").astype("int64"))
    runs = {}
    for st, g in d.groupby("station"):
        lst = []
        for (rt, av), r in g.groupby(["rt", "av"], sort=True):
            r = r.sort_values("vt")
            lst.append((rt, av, r.vt.to_numpy(), r.temperature_2m.to_numpy(float)))
        lst.sort(key=lambda z: z[0])
        runs[st] = (np.array([z[1] for z in lst]), lst)
    return runs


_BOUNDS = {}


def bounds(st, date):
    k = (st, date)
    if k not in _BOUNDS:
        tz = ZoneInfo(STATIONS[st]["tzname"])
        d0 = datetime.fromisoformat(date).replace(tzinfo=tz)
        _BOUNDS[k] = (pd.Timestamp(d0).value, pd.Timestamp(d0 + timedelta(days=1)).value)
    return _BOUNDS[k]


def members(runs, st, date, t_ns, kmax, used=None):
    """Remaining-hours maxima of the last kmax usable runs (newest first)."""
    if st not in runs:
        return []
    start, end = bounds(st, date)
    avs, lst = runs[st]
    k = int(np.searchsorted(avs, t_ns, side="right"))  # avs monotone in run time (constant delay)
    lo_v = max(t_ns, start)
    need = np.arange(((lo_v // NS_H) + 1) * NS_H, end + 1, NS_H)
    out = []
    for j in range(k - 1, -1, -1):
        rt, av, vt, tm = lst[j]
        if rt < t_ns - LOOKBACK_H * NS_H or len(out) >= kmax:
            break
        if not len(need):
            break
        i = np.searchsorted(vt, need)
        if (i >= len(vt)).any() or not (vt[np.minimum(i, len(vt) - 1)] == need).all():
            continue
        out.append(float(tm[i].max()))
        if used is not None:
            used.append(av)
    return out


# ------------------------------------------------------------------ fit
def fit_frame(runs, m, kmax_list):
    rows = []
    days = pd.date_range(FIT_START, FIT_END).strftime("%Y-%m-%d")
    for st in STATIONS:
        tz = ZoneInfo(STATIONS[st]["tzname"])
        ms = m[m.station == st]
        for date in days:
            td = ms[ms.local_date == date]
            if len(td) < t3.MIN_ROUTINE:
                continue
            av = td.available_utc.dt.as_unit("ns").astype("int64").to_numpy()
            tf = td.temp_f.to_numpy()
            for hh in range(24):
                t_ns = pd.Timestamp(datetime.fromisoformat(date).replace(tzinfo=tz) + timedelta(hours=hh, minutes=30)).value
                after = tf[av > t_ns]
                before = tf[av <= t_ns]
                if not len(after):
                    continue
                rec = {"st": st, "date": date, "h": hh, "yrem": float(after.max()),
                       "runmax": float(before.max()) if len(before) else np.nan}
                for K in kmax_list:
                    mem = members(runs, st, date, t_ns, K)
                    rec[f"mu{K}"] = np.mean(mem) if mem else np.nan
                    rec[f"sd{K}"] = np.std(mem, ddof=1) if len(mem) > 1 else (0.0 if mem else np.nan)
                    rec[f"n{K}"] = len(mem)
                rows.append(rec)
    return pd.DataFrame(rows)


def params(f, mucol, sdcol=None):
    par = {}
    for hh, g in f.groupby("h"):
        e = (g.yrem - g[mucol]).dropna()
        p = {"b": float(e.mean()), "s": float(max(e.std(), SMIN)), "n": int(len(e))}
        if sdcol is not None:
            gg = g[g[mucol].notna()]
            ms2 = float((gg[sdcol] ** 2).mean())
            p["s0"] = float(math.sqrt(max(e.var() - ms2, 0.25)))
            p["mean_sd_ens"] = float(gg[sdcol].mean())
        par[int(hh)] = p
    return par


# ------------------------------------------------------------------ band probabilities (vectorised)
def _cdf(x):
    from scipy.special import ndtr  # noqa
    return ndtr(x)


def cand_from(snap_mu, snap_sig, snaps, bands, offs):
    """snap_mu/snap_sig: arrays over snapshots (nan = not covered). X = max(F, Y)."""
    n = snaps.n_bands.to_numpy()
    sob = np.repeat(np.arange(len(snaps)), n)
    mu = snap_mu[sob]; sg = snap_sig[sob]
    kind = bands.kind.to_numpy(); lo = bands.low.to_numpy(float); hi = bands.high.to_numpy(float)
    up = np.where(kind == "gte", np.inf, hi + 0.5)
    dn = np.where(kind == "lte", -np.inf, lo - 0.5)
    with np.errstate(invalid="ignore", divide="ignore"):
        cu = np.where(np.isinf(up), 1.0, _cdf((up - mu) / sg))
        cd = np.where(np.isinf(dn), 0.0, _cdf((dn - mu) / sg))
    p = np.clip(cu - cd, 0.0, None)
    imp = bands.floor_impossible.to_numpy(bool)
    bi = bands.band_index.to_numpy(int)
    prev_imp = np.r_[True, imp[:-1]]
    first_poss = (~imp) & ((bi == 0) | prev_imp)
    p = np.where(imp, 0.0, np.where(first_poss, cu, p))
    keep = np.isfinite(snap_mu)[sob]
    out = bands.loc[keep, ["row_key", "band_index"]].assign(p=p[keep])
    tot = out.groupby("row_key").p.transform("sum")
    return out[tot > 0].reset_index(drop=True)


def serve_members(runs, snaps, kmax, check_pit=True):
    t_ns = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601").dt.as_unit("ns").astype("int64").to_numpy()
    mu = np.full(len(snaps), np.nan); sd = np.full(len(snaps), np.nan); nm = np.zeros(len(snaps), int)
    av_used, cap_used = [], []
    for i, (st, date, t) in enumerate(zip(snaps.station.to_numpy(), snaps.date.to_numpy(), t_ns)):
        used = []
        mem = members(runs, st, date, int(t), kmax, used)
        if mem:
            mu[i] = np.mean(mem); sd[i] = np.std(mem, ddof=1) if len(mem) > 1 else 0.0; nm[i] = len(mem)
            av_used.extend(used); cap_used.extend([int(t)] * len(used))
    if check_pit:
        h.assert_point_in_time(pd.to_datetime(np.array(av_used), utc=True), pd.to_datetime(np.array(cap_used), utc=True))
    return mu, sd, nm, len(av_used)


# ------------------------------------------------------------------ paired marginals
def floored(cand, d):
    pc, use, _ = h._candidate_vector(cand, d, False)
    return pc, use


def paired(d, frame_cols, a, b, label):
    """a, b: names in frame_cols (per-snapshot SE means). Paired a - b, W intervals."""
    f = frame_cols
    out = {}
    for g, (lo, hi) in GROUPS.items():
        out[g] = {}
        for stratum in (FROM, BEFORE):
            m = f.local_hour.between(lo, hi) & (f.stratum == stratum)
            c = f[m].groupby(["date", "market"], sort=True)[[a, b]].mean().reset_index()
            idx = np.array([d.key_index[(x, y)] for x, y in zip(c.date, c.market)])
            delta = (c[a] - c[b]).to_numpy()
            iv = h.interval(idx, delta)
            pm = c.assign(dd=delta).groupby("market").dd.mean()
            out[g][stratum] = {"estimate": iv["estimate"], "ci95": iv["ci95"],
                               "markets_negative": int((pm < 0).sum()), "markets": int(len(pm))}
    return {"pair": f"{a} - {b}", "label": label, "tables": out}


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    register()
    check_registered()
    snaps, bands = h.candidate_inputs()
    assert (snaps.date > "2026-09-29").sum() == 0
    bands = bands.reset_index(drop=True)
    offs = np.concatenate([[0], np.cumsum(snaps.n_bands.to_numpy())[:-1]])
    assert (bands.row_key.to_numpy()[offs] == snaps.row_key.to_numpy()).all()
    m = t3.load_metar()
    m = m[(m.local_date >= "2026-07-24") & (m.local_date <= FIT_END)]
    meta = {"HARNESS_SHA256": h.harness_sha256()}
    cands = {}
    for lag in (0.0, 2.0):
        runs = load_runs(lag)
        log("runs loaded lag", lag)
        f = fit_frame(runs, m, [1, 3, 4])
        f.to_parquet(OUT / f"fit_frame_lag{int(lag)}.parquet")
        log("fit frame", len(f))
        p4 = params(f, "mu4", "sd4")
        if lag == 0.0:
            p1 = params(f, "mu1"); p3 = params(f, "mu3")
            f["rm"] = f.runmax
            pc1 = params(f, "rm")
            meta.update(params_r1=p4, params_k1=p1, params_k3=p3, params_c1=pc1,
                        fit_rows=int(len(f)), fit_rows_with_k4=int(f.mu4.notna().sum()),
                        fit_mean_members_k4=float(f.n4.mean()))
            hh = snaps.local_hour.to_numpy()
            mu4, sd4, n4, nused = serve_members(runs, snaps, 4)
            mu3, _, n3, _ = serve_members(runs, snaps, 3)
            mu1, _, n1, _ = serve_members(runs, snaps, 1)
            meta["pit_members_asserted"] = nused
            meta["serve_member_counts_k4"] = pd.Series(n4).value_counts().sort_index().to_dict()
            b = lambda P, k: np.array([P[int(x)][k] for x in hh])
            cands["t9-r1"] = cand_from(mu4 + b(p4, "b"), b(p4, "s"), snaps, bands, offs)
            sig2 = np.sqrt(b(p4, "s0") ** 2 + np.nan_to_num(sd4) ** 2)
            cands["t9-r2"] = cand_from(mu4 + b(p4, "b"), sig2, snaps, bands, offs)
            cands["t9-r3"] = cand_from(mu1 + b(p1, "b"), b(p1, "s"), snaps, bands, offs)
            cands["t9-r4"] = cand_from(mu3 + b(p3, "b"), b(p3, "s"), snaps, bands, offs)
            cov = np.isfinite(mu4)
            F = snaps.floor.to_numpy(float)
            cands["t9-c1"] = cand_from(np.where(cov, F + b(pc1, "b"), np.nan), b(pc1, "s"), snaps, bands, offs)
            # c2 captured hrrr_high, fit on before-stratum snapshots
            cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
            fa = pd.to_datetime(snaps.hrrr_fetched_at, utc=True, format="ISO8601", errors="coerce")
            ok2 = (snaps.hrrr_high.notna() & fa.notna() & (fa <= cap)).to_numpy()
            h.assert_point_in_time(fa[ok2], cap[ok2])
            hb = snaps[ok2 & (snaps.stratum == BEFORE).to_numpy()][["station", "date", "local_hour", "captured_at_utc", "hrrr_high"]]
            mm = t3.load_metar()
            mm = mm[(mm.local_date >= "2026-08-01") & (mm.local_date <= FIT_END)]
            mm = mm.assign(av=mm.available_utc.dt.as_unit("ns").astype("int64"))
            grp = {k: (g.av.to_numpy(), g.temp_f.to_numpy()) for k, g in mm.groupby(["station", "local_date"])}
            tns = pd.to_datetime(hb.captured_at_utc, utc=True, format="ISO8601").dt.as_unit("ns").astype("int64").to_numpy()
            yr = []
            for st, dt, t in zip(hb.station, hb.date, tns):
                av, tf = grp.get((st, dt), (np.array([]), np.array([])))
                a = tf[av > t]
                yr.append(a.max() if len(a) else np.nan)
            hb = hb.assign(yrem=yr, h=hb.local_hour)
            pc2 = params(hb, "hrrr_high")
            meta["params_c2"] = pc2
            mu_c2 = np.where(cov & ok2, snaps.hrrr_high.to_numpy(float) + b(pc2, "b"), np.nan)
            cands["t9-c2"] = cand_from(mu_c2, b(pc2, "s"), snaps, bands, offs)
        else:
            mu4s, _, _, _ = serve_members(runs, snaps, 4)
            hh = snaps.local_hour.to_numpy()
            b = lambda P, k: np.array([P[int(x)][k] for x in hh])
            meta["params_r1s"] = p4
            cands["t9-r1s"] = cand_from(mu4s + b(p4, "b"), b(p4, "s"), snaps, bands, offs)
    results = {}
    for name, c in cands.items():
        res = h.score(c, name=name.replace("-", "_"))
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"t9 leakage tripwire {name} {res['leakage_suspect_groups']}\n")
            sys.exit("leakage tripwire")
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        results[name] = res
        log(name, {g: res["classes"][g]["class"] for g in res["classes"]})
    # paired marginals, identical floor/fallback through the harness builder
    d = h.data()
    t3c, _ = t3.build()
    allc = dict(cands)
    allc["t3-r3"] = t3c["t3-r3"]
    fr = d.snaps[["row_key", "date", "market", "stratum", "local_hour"]].copy()
    fr["served"] = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
    for name, c in allc.items():
        pc, use = floored(c, d)
        fr[name] = np.add.reduceat((pc - d.y) ** 2, d.offsets) / d.snaps.n_bands.to_numpy()
    pairs = [("t9-r1", "t3-r3", "marginal over the t3-r3 floor+remaining-rise rung"),
             ("t9-r2", "t3-r3", "marginal over the t3-r3 rung"),
             ("t9-r1", "t9-c1", "HRRR information over the no-source control (same coverage, same form)"),
             ("t9-r2", "t9-c1", "HRRR+spread over the no-source control"),
             ("t9-r1", "t9-r3", "lagged ensemble mean over the latest single run"),
             ("t9-r2", "t9-r1", "spread term over the mean-only ensemble"),
             ("t9-r1", "t9-c2", "Single-Runs lagged ensemble over production's captured hrrr_high"),
             ("t9-c1", "t3-r3", "no-source control vs t3-r3 rung")]
    meta["paired"] = [paired(d, fr, a, b, lab) for a, b, lab in pairs]
    meta["classes"] = {n: {g: r["classes"][g]["class"] for g in r["classes"]} for n, r in results.items()}
    meta["candidate_share"] = {n: r["candidate_share"] for n, r in results.items()}
    (OUT / "t9_meta.json").write_text(json.dumps(meta, indent=1, default=float), encoding="utf-8")
    for pr in meta["paired"]:
        log(pr["pair"], {g: (round(v[FROM]["estimate"], 5), [round(x, 5) for x in v[FROM]["ci95"]],
                             v[FROM]["markets_negative"], round(v[BEFORE]["estimate"], 5))
                         for g, v in pr["tables"].items()})


if __name__ == "__main__":
    main()
