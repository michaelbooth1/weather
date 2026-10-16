"""T7 hunter: MOS/NBE consensus (MAV/MET/MEX/LAV + NBE from the IEM MOS archive). Development only.

Rules t7-r1..r5 are registered in C:\\swarm\\registry.jsonl (agent t7). Run from C:\\pt\\swarm:
    <repo python> -m tools.research.model_parity.t7_mos_consensus

Point in time: a MOS run enters a snapshot only if its available_utc (NBE: measured S3 LastModified;
MAV/MET/MEX/LAV: manifest-documented fixed lags) <= captured_at_utc; asserted with
h.assert_point_in_time on every chosen run. Truth (IEM METAR) is used only for the history fit
(local dates 2026-06-01..2026-07-31), never as a candidate input. No market input, no label input.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

MOS = Path(r"C:\swarm\data\iem\mos")
METAR = Path(r"C:\swarm\data\iem\metar")
OUT = Path(r"C:\swarm\out\t7")
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text(encoding="utf-8"))["stations"]
FIT_START, FIT_END = "2026-06-01", "2026-07-31"
MODELS = {"MAV": ("GFS", "n_x"), "MET": ("NAM", "n_x"), "MEX": ("MEX", "n_x"),
          "LAV": ("LAV", None), "NBE": ("NBE", "txn")}
MEASURED = {"NBE"}
NS_H = 3_600_000_000_000
SMIN = 0.5


def load_runs(extra_lag_h=0.0):
    """runs[model][station] = list of dicts sorted by available_utc (ns)."""
    runs = {}
    for name, (fname, xcol) in MODELS.items():
        d = pd.read_parquet(MOS / f"mos_{fname}.parquet")
        d = d[d.available_utc.notna()]
        avail = d.available_utc
        if name not in MEASURED and extra_lag_h:
            avail = avail + pd.Timedelta(hours=extra_lag_h)
        d = d.assign(av=avail.dt.as_unit("ns").astype("int64"), rt=d.runtime.dt.as_unit("ns").astype("int64"),
                     ft=d.ftime.dt.as_unit("ns").astype("int64"))
        runs[name] = {}
        for st, g in d.groupby("station"):
            lst = []
            for (rt, av), r in g.groupby(["rt", "av"], sort=True):
                r = r.sort_values("ft")
                tm = r.tmp.to_numpy(float)
                ok = ~np.isnan(tm)
                rec = {"rt": rt, "av": av, "ft": r.ft.to_numpy()[ok], "tmp": tm[ok], "nx": {}}
                if xcol:
                    xr = r[r[xcol].notna()]
                    rec["nx"] = dict(zip(xr.ft.to_numpy(), xr[xcol].to_numpy(float)))
                lst.append(rec)
            lst.sort(key=lambda z: z["av"])
            runs[name][st] = (np.array([z["av"] for z in lst]), lst)
    return runs


def day_bounds(station, date):
    tz = ZoneInfo(STATIONS[station]["tzname"])
    d0 = datetime.fromisoformat(date).replace(tzinfo=tz)
    start = pd.Timestamp(d0).value
    end = pd.Timestamp(d0 + timedelta(days=1)).value
    peak = pd.Timestamp(d0 + timedelta(hours=15)).value
    l10 = pd.Timestamp(d0 + timedelta(hours=10)).value
    l18 = pd.Timestamp(d0 + timedelta(hours=18)).value
    nx_ft = pd.Timestamp(date, tz="UTC").value + 24 * NS_H
    return start, end, peak, l10, l18, nx_ft


def model_values(runs, models, station, date, t_ns, used=None):
    """Return (day_max dict, rem_max dict) per model, using the latest usable run carrying the value."""
    start, end, peak, l10, l18, nx_ft = day_bounds(station, date)
    rt_min = pd.Timestamp(date, tz="UTC").value - 3 * 24 * NS_H
    day, rem = {}, {}
    for m in models:
        if station not in runs[m]:
            continue
        avs, lst = runs[m][station]
        k = int(np.searchsorted(avs, t_ns, side="right"))
        got_day = got_rem = False
        for j in range(k - 1, -1, -1):
            r = lst[j]
            if r["rt"] < rt_min or (got_day and got_rem):
                break
            ft, tm = r["ft"], r["tmp"]
            # day max
            if not got_day:
                if m == "LAV":
                    sel = (ft >= start) & (ft < end)
                    cov = (ft >= l10) & (ft <= l18)
                    if cov.sum() >= 9:
                        day[m] = float(tm[sel].max()); got_day = True
                        if used is not None: used.append(r["av"])
                elif nx_ft in r["nx"]:
                    day[m] = r["nx"][nx_ft]; got_day = True
                    if used is not None: used.append(r["av"])
            # remaining-hours max
            if not got_rem:
                sel = (ft > t_ns) & (ft <= end)
                vals = list(tm[sel])
                if m != "LAV" and peak > t_ns and nx_ft in r["nx"]:
                    vals.append(r["nx"][nx_ft])
                if vals:
                    rem[m] = float(max(vals)); got_rem = True
                    if used is not None: used.append(r["av"])
    return day, rem


# ---------------------------------------------------------------- history fit
def metar_truth():
    out = {}
    for st in STATIONS:
        m = pd.read_parquet(METAR / f"{st}.parquet")
        m = m[(~m.is_cor) & m.tmpf.notna()]
        m = m[(m.local_date.astype(str) >= "2026-05-25") & (m.local_date.astype(str) <= "2026-08-01")]
        out[st] = m.assign(t=np.round(m.tmpf.to_numpy()), v=m.valid_utc.dt.as_unit("ns").astype("int64"),
                           ld=m.local_date.astype(str))[["ld", "v", "t"]]
    return out


def fit(runs, models, truth):
    rows = []
    for st in STATIONS:
        tz = ZoneInfo(STATIONS[st]["tzname"])
        tr = truth[st]
        for date in pd.date_range(FIT_START, FIT_END).strftime("%Y-%m-%d"):
            td = tr[tr.ld == date]
            if len(td) < 18:
                continue
            dmax = td.t.max()
            for hh in range(24):
                t = pd.Timestamp(datetime.fromisoformat(date).replace(tzinfo=tz) + timedelta(hours=hh, minutes=30))
                t_ns = t.value
                day, rem = model_values(runs, models, st, date, t_ns)
                after = td[td.v > t_ns - 10 * 60 * 1_000_000_000]
                rows.append({"st": st, "date": date, "h": hh,
                             "C": np.mean(list(day.values())) if day else np.nan,
                             "R": np.mean(list(rem.values())) if rem else np.nan,
                             "dmax": dmax, "yrem": after.t.max() if len(after) else np.nan})
    f = pd.DataFrame(rows)
    f["e1"] = f.dmax - f.C
    f["e2"] = f.yrem - f.R
    par = {}
    for hh, g in f.groupby("h"):
        e1, e2 = g.e1.dropna(), g.e2.dropna()
        par[int(hh)] = {"b1": float(e1.mean()), "s1": float(max(e1.std(), SMIN)), "n1": int(len(e1)),
                        "b2": float(e2.mean()), "s2": float(max(e2.std(), SMIN)), "n2": int(len(e2))}
    return par, f


# ---------------------------------------------------------------- band probabilities
def _cdf(x):
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / math.sqrt(2.0)))


def band_probs(b, mu, s, max_floor):
    """b: band frame of one snapshot (ordered). Gaussian band masses; if max_floor, X = max(floor, Y)."""
    lo = b["low"].to_numpy(float); hi = b["high"].to_numpy(float); kind = b["kind"].to_numpy()
    up = np.where(kind == "gte", np.inf, hi + 0.5)
    dn = np.where(kind == "lte", -np.inf, lo - 0.5)
    cu = np.where(np.isinf(up), 1.0, _cdf((up - mu) / s))
    cd = np.where(np.isinf(dn), 0.0, _cdf((dn - mu) / s))
    p = np.clip(cu - cd, 0.0, None)
    if max_floor:
        imp = b["floor_impossible"].to_numpy(bool)
        poss = np.flatnonzero(~imp)
        if len(poss) == 0:
            return None
        j = poss[0]
        p[imp] = 0.0
        p[j] = cu[j]
    return p


def build(runs, models, par, snaps, bands, check_pit):
    snaps = snaps.assign(t_ns=pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601").dt.as_unit("ns").astype("int64"))
    av_used, cap_used = [], []
    rec = {}
    for (st, date), g in snaps.groupby(["station", "date"]):
        for r in g.itertuples(index=False):
            used = []
            day, rem = model_values(runs, models, st, date, r.t_ns, used)
            if used:
                av_used.append(max(used)); cap_used.append(r.t_ns)
            rec[r.row_key] = (np.mean(list(day.values())) if day else np.nan, len(day),
                              np.mean(list(rem.values())) if rem else np.nan, len(rem), r.local_hour,
                              np.std(list(day.values())) if len(day) > 1 else np.nan)
    if check_pit:  # rule 1 on every snapshot: the latest-available run used must be <= captured_at_utc
        h.assert_point_in_time(pd.to_datetime(np.array(av_used), utc=True), pd.to_datetime(np.array(cap_used), utc=True))
    return rec


def candidates(rec, par, bands, which):
    out = []
    bands = bands.sort_values(["row_key", "band_index"])
    for rk, b in bands.groupby("row_key", sort=False):
        C, nC, R, nR, hh, _ = rec[rk]
        pp = par[int(hh)]
        if which == "r1":
            if nC == 0:
                continue
            p = band_probs(b, C + pp["b1"], pp["s1"], False)
        else:
            if nR == 0:
                continue
            p = band_probs(b, R + pp["b2"], pp["s2"], True)
        if p is None or p.sum() <= 0:
            continue
        out.append(pd.DataFrame({"row_key": rk, "band_index": b.band_index.to_numpy(), "p": p}))
    return pd.concat(out, ignore_index=True)


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date > "2026-09-29").sum() == 0
    truth = metar_truth()
    all5 = list(MODELS)
    variants = {"r1": (0.0, all5), "r2": (0.0, all5), "r3": (2.0, all5), "r4": (0.0, ["NBE"])}
    results, meta = {}, {}
    cache = {}
    for v, (lag, models) in variants.items():
        key = (lag, tuple(models))
        if key not in cache:
            runs = load_runs(lag)
            par, fitf = fit(runs, models, truth)
            rec = build(runs, models, par, snaps, bands, check_pit=True)
            cache[key] = (par, rec, fitf)
        par, rec, fitf = cache[key]
        cand = candidates(rec, par, bands, "r1" if v == "r1" else "r2")
        meta[v] = {"lag_extra_h": lag, "models": models, "params": par,
                   "covered_snapshots": int(cand.row_key.nunique()),
                   "n_models_hist": pd.Series([x[1 if v == "r1" else 3] for x in rec.values()]).value_counts().sort_index().to_dict()}
        if v == "r2":
            r2cand = cand
        res = h.score(cand, name=f"t7_{v}")
        h.save(res, OUT)
        results[v] = res
        print(h.markdown(res)); sys.stdout.flush()
        if v == "r2":
            ftab = fitf.groupby("h")[["e1", "e2"]].agg(["mean", "std", "count"])
            ftab.to_csv(OUT / "fit_residuals_by_hour.csv")
            pd.DataFrame([(k,) + tuple(x) for k, x in rec.items()],
                         columns=["row_key", "C", "nC", "R", "nR", "local_hour", "sdC"]).to_parquet(OUT / "consensus_eval.parquet")
    # r5 pool
    m = bands[["row_key", "band_index", "p_served"]].merge(r2cand, on=["row_key", "band_index"], how="inner")
    m["p"] = 0.5 * m.p_served + 0.5 * m.p
    res = h.score(m[["row_key", "band_index", "p"]], name="t7_r5")
    h.save(res, OUT)
    results["r5"] = res
    print(h.markdown(res))
    meta["r5"] = {"covered_snapshots": int(m.row_key.nunique())}
    summ = {}
    for v, res in results.items():
        summ[v] = {"classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                   "leakage_suspect_groups": res.get("leakage_suspect_groups")}
    (OUT / "t7_meta.json").write_text(json.dumps({"meta": meta, "summary": summ,
                                                   "HARNESS_SHA256": h.harness_sha256()}, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str))


if __name__ == "__main__":
    main()
