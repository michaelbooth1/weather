"""T22 spare: independent re-implementation of T10 (ECMWF IFS latest run) from the REGISTERED rule text
(registry ids t10-r1, t10-r2, t10-r3, t10-c1, t10-c2, t10-d1). Written without reading
t10_ecmwf_ifs.py. No new rules. Development only.

Run from C:\\pt\\swarm:
    <repo python> -m tools.research.model_parity.t22_t10_reimpl
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t22")
ECMWF = Path(r"C:\swarm\data\ecmwf\values.parquet")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
TZ = {"KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
      "KAUS": "America/Chicago", "KDAL": "America/Chicago", "KHOU": "America/Chicago",
      "KORD": "America/Chicago", "KBKF": "America/Denver",
      "KLAX": "America/Los_Angeles", "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
BLOCKS = [("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23)]
HIST_DATES = [f"2026-07-{d:02d}" for d in range(25, 32)]
HIST_RUN_CUTOFF = pd.Timestamp("2026-08-01T00:00:00Z")
H3 = pd.Timedelta(hours=3)


def block_of(hour):
    for name, lo, hi in BLOCKS:
        if lo <= hour <= hi:
            return name
    raise ValueError(hour)


def rnd(x):
    return np.floor(np.asarray(x, float) + 0.5)


# ----------------------------------------------------------------------------- IFS runs

def load_ifs():
    v = pd.read_parquet(ECMWF)
    v = v[v.usable].copy()
    for c in ("valid_utc", "run_utc", "window_start_utc", "available_utc_measured",
              "available_utc_conservative"):
        v[c] = pd.to_datetime(v[c]).dt.tz_localize("UTC")
    v["F"] = (v.bilinear_K - 273.15) * 9.0 / 5.0 + 32.0
    # per station-run availability: max per-object LastModified over the station-run
    g = v.groupby(["station", "run_utc"])
    runs = g.agg(lm=("available_utc_measured", "max"), cons=("available_utc_conservative", "max"),
                 last_valid=("valid_utc", "max")).reset_index()
    # sanity: conservative = max(run+8h, LM)
    assert (runs.cons >= runs.run_utc + pd.Timedelta(hours=8)).all()
    store = {}
    for (st, run), grp in g:
        t2 = grp[grp.param == "2t"].sort_values("valid_utc")
        mx = grp[(grp.param == "mx2t3") & (grp.step >= 3)].sort_values("valid_utc")
        store[(st, run)] = dict(
            t2_valid=t2.valid_utc.to_numpy("datetime64[ns]").astype("int64"), t2_F=t2.F.to_numpy(),
            mx_end=mx.valid_utc.to_numpy("datetime64[ns]").astype("int64"),
            mx_start=mx.window_start_utc.to_numpy("datetime64[ns]").astype("int64"), mx_F=mx.F.to_numpy())
        a = store[(st, run)]
        assert np.all(a["mx_end"] - a["mx_start"] == H3.value), (st, run)
    return runs, store


def select_runs(runs, station, t_utc, avail_col, run_before=None):
    """Latest eligible run per snapshot: max run_utc among station runs with availability <= t."""
    r = runs[runs.station == station]
    if run_before is not None:
        r = r[r.run_utc < run_before]
    r = r.sort_values(avail_col)
    av = r[avail_col].to_numpy("datetime64[ns]").astype("int64")
    run_cm = np.maximum.accumulate(r.run_utc.to_numpy("datetime64[ns]").astype("int64"))
    t = np.asarray(t_utc, "int64")
    pos = np.searchsorted(av, t, side="right") - 1
    out = np.where(pos >= 0, run_cm[np.clip(pos, 0, None)], np.iinfo("int64").min)
    return out  # int64 ns or INT_MIN when none eligible


def remaining_mu(store, station, run_ns, t_ns, e_ns, form):
    """mu for each snapshot (arrays). form 'mix' (2t U mx2t3) or '2t'. NaN when not covered."""
    mu = np.full(len(t_ns), np.nan)
    for run in np.unique(run_ns):
        if run == np.iinfo("int64").min:
            continue
        sel = np.flatnonzero(run_ns == run)
        a = store[(station, pd.Timestamp(run, tz="UTC"))]
        t = t_ns[sel][:, None]
        e = e_ns[sel][:, None]
        last_valid = max(a["t2_valid"].max(), a["mx_end"].max())
        carries = e_ns[sel] <= last_valid
        v2, f2 = a["t2_valid"][None, :], a["t2_F"][None, :]
        in2 = (v2 > t) & (v2 <= e)
        m2 = np.where(in2, f2, -np.inf).max(axis=1)
        if form == "mix":
            ms, me, mf = a["mx_start"][None, :], a["mx_end"][None, :], a["mx_F"][None, :]
            inm = (ms >= t) & (me <= e)
            mm = np.where(inm, mf, -np.inf).max(axis=1)
            val = np.maximum(m2, mm)
            empty = ~np.isfinite(val)
            if empty.any():
                after = me > t  # mx2t3 window with the smallest end > t
                endv = np.where(after, me, np.iinfo("int64").max)
                k = endv.argmin(axis=1)
                ok = after[np.arange(len(sel)), k]
                fb = np.where(ok, a["mx_F"][k], np.nan)
                val = np.where(empty, fb, val)
        else:
            val = m2
            empty = ~np.isfinite(val)
            if empty.any():
                after = v2 > t  # first 2t value after t
                vv = np.where(after, v2, np.iinfo("int64").max)
                k = vv.argmin(axis=1)
                ok = after[np.arange(len(sel)), k]
                fb = np.where(ok, a["t2_F"][k], np.nan)
                val = np.where(empty, fb, val)
        val = np.where(carries & np.isfinite(val), val, np.nan)
        mu[sel] = val
    return mu


# ----------------------------------------------------------------------------- METAR history

def load_metar(station):
    m = pd.read_parquet(METAR_DIR / f"{station}.parquet")
    m = m[(m.report_type == "routine") & (~m.is_cor) & m.tmpf.notna()].copy()
    m = m[m.local_date.astype(str).isin(HIST_DATES)]
    m["Tr"] = rnd(m.tmpf)
    m["v_ns"] = m.valid_utc.dt.tz_convert("UTC").astype("datetime64[ns, UTC]").astype("int64")
    m["a_ns"] = m.available_utc.dt.tz_convert("UTC").astype("datetime64[ns, UTC]").astype("int64")
    assert (m.a_ns - m.v_ns >= pd.Timedelta(minutes=10).value).all()
    return m


def history_snapshots(runs, store, avail_col="lm"):
    rows = []
    for st, tzname in TZ.items():
        tz = ZoneInfo(tzname)
        met = load_metar(st)
        recs = []
        for d in HIST_DATES:
            day = pd.Timestamp(d)
            e_loc = pd.Timestamp(day + pd.Timedelta(days=1), tz=tz)  # local midnight ending D
            for hh in range(24):
                for mm in (0, 30):
                    t_loc = pd.Timestamp(day + pd.Timedelta(hours=hh, minutes=mm), tz=tz)
                    recs.append((d, hh, t_loc.tz_convert("UTC").value, e_loc.tz_convert("UTC").value))
        f = pd.DataFrame(recs, columns=["date", "hour", "t_ns", "e_ns"])
        f["station"] = st
        run = select_runs(runs, st, f.t_ns.to_numpy(), avail_col, run_before=HIST_RUN_CUTOFF)
        f["run_ns"] = run
        # PIT check on history: selected run's availability <= t
        okr = run != np.iinfo("int64").min
        if okr.any():
            rr = runs[runs.station == st].set_index(runs[runs.station == st].run_utc.astype("datetime64[ns, UTC]").astype("int64"))
            h.assert_point_in_time(rr.loc[run[okr], avail_col].to_numpy(),
                                   pd.to_datetime(f.t_ns[okr].to_numpy(), utc=True))
        tv = f.t_ns.to_numpy()
        ev = f.e_ns.to_numpy()
        f["mu_mix"] = remaining_mu(store, st, run, tv, ev, "mix")
        f["mu_2t"] = remaining_mu(store, st, run, tv, ev, "2t")
        rem, runmax = [], []
        for d, t, e in zip(f.date, tv, ev):
            md = met[met.local_date.astype(str) == d]
            r = md.Tr[(md.v_ns > t) & (md.v_ns <= e)]
            q = md.Tr[md.a_ns <= t]
            rem.append(r.max() if len(r) else np.nan)
            runmax.append(q.max() if len(q) else np.nan)
        f["rem_max"] = rem
        f["run_max"] = runmax
        rows.append(f)
    f = pd.concat(rows, ignore_index=True)
    f["block"] = [block_of(x) for x in f.hour]
    return f


def fit(hist):
    out = {}
    for name, _, _ in BLOCKS:
        b = hist[hist.block == name]
        res = {}
        r1 = (b.rem_max - b.mu_mix).dropna()
        res["r1"] = dict(n=int(len(r1)), b=0.0, s=float(max(1.0, math.sqrt((r1 ** 2).mean()))))
        bb = float(r1.median())
        res["r2"] = dict(n=int(len(r1)), b=bb, s=float(max(1.0, math.sqrt(((r1 - bb) ** 2).mean()))),
                         rms0=float(math.sqrt((r1 ** 2).mean())))
        r3 = (b.rem_max - b.mu_2t).dropna()
        b3 = float(r3.median())
        res["r3"] = dict(n=int(len(r3)), b=b3, s=float(max(1.0, math.sqrt(((r3 - b3) ** 2).mean()))))
        # c1: same history snapshots as r2 (mu_mix defined), anchor = PIT METAR running max
        c = b[b.mu_mix.notna()]
        rc = (c.rem_max - c.run_max).dropna()
        bc = float(rc.median())
        res["c1"] = dict(n=int(len(rc)), b=bc, s=float(max(1.0, math.sqrt(((rc - bc) ** 2).mean()))))
        out[name] = res
    return out


# ----------------------------------------------------------------------------- candidates

def band_probs(bands, snap_pos_of_band, mu, sig, B):
    """H = max(B, X), X ~ N(mu, sig) integer-discretised; band probabilities."""
    m = mu[snap_pos_of_band]
    s = sig[snap_pos_of_band]
    bb = B[snap_pos_of_band]

    def cdf(k):
        k = np.asarray(k, float)
        return np.where(k < bb, 0.0, ndtr((k + 0.5 - m) / s))

    kind = bands.kind.to_numpy()
    lo = bands.low.to_numpy(float)
    hi = bands.high.to_numpy(float)
    p = np.where(kind == "lte", cdf(hi),
                 np.where(kind == "gte", 1.0 - cdf(lo - 1), cdf(hi) - cdf(lo - 1)))
    return np.clip(p, 0.0, None)


def make_candidate(snaps, bands, bpos, mu, sig, B, covered):
    ok = covered & np.isfinite(mu) & np.isfinite(sig) & np.isfinite(B)
    p = band_probs(bands, bpos, np.where(ok, mu, 0.0), np.where(ok, sig, 1.0), np.where(ok, B, 0.0))
    keep = ok[bpos]
    return bands.loc[keep, ["row_key", "band_index"]].assign(p=p[keep]), ok


def per_snapshot_loss(cand):
    d = h.data()
    pc, use, _ = h._candidate_vector(cand, d, False)
    return h._snapshot_mean(d, (pc - d.y) ** 2), use


def paired(loss_a, loss_b, snaps, group_lo, group_hi, stratum):
    m = snaps.local_hour.between(group_lo, group_hi).to_numpy() & (snaps.stratum == stratum).to_numpy()
    f = pd.DataFrame({"date": snaps.date[m], "market": snaps.market[m], "d": (loss_a - loss_b)[m]})
    cells = f.groupby(["date", "market"], sort=True).d.mean().reset_index()
    d = h.data()
    idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
    iv = h.interval(idx, cells.d.to_numpy())
    pm = cells.groupby("market").d.mean()
    return {"estimate": iv["estimate"], "ci95": iv["ci95"], "mkts_neg": int((pm < 0).sum()),
            "mkts": int(len(pm))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not Path(r"C:\swarm\STOP").exists()
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    n_after = int((snaps.date > "2026-09-29").sum())
    runs, store = load_ifs()

    hist = history_snapshots(runs, store, "lm")
    fits = fit(hist)
    hist.to_parquet(OUT / "t22_history_snapshots.parquet")

    t_ns = pd.to_datetime(snaps.captured_at_utc, utc=True).astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    e_ns = np.empty(len(snaps), "int64")
    for st, tzname in TZ.items():
        tz = ZoneInfo(tzname)
        m = (snaps.station == st).to_numpy()
        e = [pd.Timestamp(pd.Timestamp(d) + pd.Timedelta(days=1), tz=tz).tz_convert("UTC").value
             for d in snaps.date[m]]
        e_ns[m] = e
    assert (e_ns > t_ns).all()
    blk = snaps.block.to_numpy()
    F = snaps.floor.to_numpy(float)
    B = np.floor(F + 0.5)
    pos = np.repeat(np.arange(len(snaps)), snaps.n_bands.to_numpy())
    assert len(pos) == len(bands) and (bands.row_key.to_numpy() == snaps.row_key.to_numpy()[pos]).all()

    def mus(avail_col):
        mix = np.full(len(snaps), np.nan)
        t2 = np.full(len(snaps), np.nan)
        runsel = np.full(len(snaps), np.iinfo("int64").min)
        for st in TZ:
            m = np.flatnonzero((snaps.station == st).to_numpy())
            r = select_runs(runs, st, t_ns[m], avail_col)
            runsel[m] = r
            mix[m] = remaining_mu(store, st, r, t_ns[m], e_ns[m], "mix")
            t2[m] = remaining_mu(store, st, r, t_ns[m], e_ns[m], "2t")
        okr = runsel != np.iinfo("int64").min
        # PIT assertion on every selected run (rule 1)
        key = runs.assign(rk=runs.station + "|" + runs.run_utc.astype("datetime64[ns, UTC]").astype("int64").astype(str)
                          ).set_index("rk")
        rk = snaps.station.to_numpy()[okr] + "|" + runsel[okr].astype(str)
        h.assert_point_in_time(key.loc[rk, avail_col].to_numpy(), snaps.captured_at_utc.to_numpy()[okr])
        age_h = np.where(okr, (t_ns - runsel) / 3.6e12, np.nan)
        return mix, t2, age_h

    mu_mix, mu_2t, age = mus("lm")

    def par(form, key):
        b = np.array([fits[x][key]["b"] for x in blk])
        s = np.array([fits[x][key]["s"] for x in blk])
        return b, s

    results, losses, covers = {}, {}, {}
    b1, s1 = par("mix", "r1")
    b2, s2 = par("mix", "r2")
    b3, s3 = par("2t", "r3")
    bc, sc = par("c1", "c1")
    base_cov = np.isfinite(F)
    specs = {}
    specs["t22_r1"] = (mu_mix + 0.0, s1, base_cov & np.isfinite(mu_mix))
    specs["t22_r2"] = (mu_mix + b2, s2, base_cov & np.isfinite(mu_mix))
    specs["t22_r3"] = (mu_2t + b3, s3, base_cov & np.isfinite(mu_2t))
    cov_r2 = specs["t22_r2"][2]
    specs["t22_c1"] = (F + bc, sc, cov_r2)
    v2m = snaps.v2_mean.to_numpy(float)
    v2s = snaps.v2_stddev.to_numpy(float)
    v2a = pd.to_datetime(snaps.v2_available_at, utc=True, errors="coerce")
    v2ok = v2a.notna().to_numpy() & np.isfinite(v2m) & np.isfinite(v2s)
    v2ok[v2ok] = (v2a[v2ok].astype("datetime64[ns, UTC]").astype("int64").to_numpy() <= t_ns[v2ok])
    if v2ok.any():
        h.assert_point_in_time(v2a[v2ok], snaps.captured_at_utc.to_numpy()[v2ok])
    specs["t22_c2"] = (v2m, np.maximum(np.nan_to_num(v2s, nan=1.0), 1.0), cov_r2 & v2ok)
    for name, (mu, sig, cov) in specs.items():
        cand, ok = make_candidate(snaps, bands, pos, mu, sig, B, cov)
        res = h.score(cand, name=name)
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        results[name] = res
        losses[name], _ = per_snapshot_loss(cand)
        covers[name] = ok
        print(name, {g: res["classes"][g]["class"] for g in res["classes"]}, res["leakage_suspect_groups"])
        if res["leakage_suspect_groups"]:
            Path(r"C:\swarm\STOP").write_text(f"t22 leakage suspect {name} {res['leakage_suspect_groups']}")
            raise SystemExit("leakage suspect")

    # d1 diagnostic: r2 frozen b, s with conservative availability and LM + 60 min
    runs_lag = runs.assign(lag60=runs.lm + pd.Timedelta(minutes=60))
    runs_bak = runs
    for name, col in (("t22_d1_cons", "cons"), ("t22_d1_lag60", "lag60")):
        runs = runs_lag
        mm, _, _ = mus(col)
        cand, ok = make_candidate(snaps, bands, pos, mm + b2, s2, B, base_cov & np.isfinite(mm))
        res = h.score(cand, name=name)
        h.save(res, OUT)
        results[name] = res
        print(name, {g: res["classes"][g]["class"] for g in res["classes"]})
    runs = runs_bak

    # paired increments (from stratum primary, before beside); all-row with served fallback
    served_loss = h._snapshot_mean(h.data(), h.data().se_served)
    groups = BLOCKS + [("00-16", 0, 16), ("all", 0, 23)]
    pairs = {}
    for a, b in (("t22_r2", "t22_c1"), ("t22_r2", "t22_c2"), ("t22_r2", "t22_r3"), ("t22_r1", "t22_r2"),
                 ("t22_c1", "t22_c2")):
        for g, lo, hi in groups:
            for st in ("from_20260823", "before_20260823"):
                pairs[f"{a}-{b}|{g}|{st}"] = paired(losses[a], losses[b], snaps, lo, hi, st)

    cov_by_block = {g: float(cov_r2[snaps.block.to_numpy() == g].mean()) for g, _, _ in BLOCKS}
    age_by_block = {g: float(np.nanmedian(age[(snaps.block.to_numpy() == g) & cov_r2])) for g, _, _ in BLOCKS}
    summary = {"fits": fits, "coverage_r2_by_block": cov_by_block, "covered_r2": int(cov_r2.sum()),
               "median_run_age_h_by_block": age_by_block, "rows_after_2026_09_29": n_after,
               "HARNESS_SHA256": h.harness_sha256(), "pairs": pairs,
               "classes": {k: {g: v["classes"][g]["class"] for g in v["classes"]} for k, v in results.items()},
               "hist_n": int(len(hist))}
    tabs = {}
    for k, v in results.items():
        for g, _, _ in groups:
            for st in ("from_20260823", "before_20260823"):
                t = h.table_lookup(v, g, st, "all_row")
                tabs[f"{k}|{g}|{st}"] = {"cs": t["candidate_minus_served"]["estimate"],
                                         "cs_ci": t["candidate_minus_served"]["ci95"],
                                         "cm": t["candidate_minus_market"]["estimate"],
                                         "cm_ci": t["candidate_minus_market"]["ci95"],
                                         "ratio": t["ratio_candidate_to_market"]["estimate"],
                                         "neg": t["markets_negative"]}
    summary["tables"] = tabs
    summary["tail"] = {k: [x for x in v["tail"] if x["stratum"] == "from_20260823"] for k, v in results.items()}
    (OUT / "t22_raw_results.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print(json.dumps(fits, indent=1))


if __name__ == "__main__":
    main()
