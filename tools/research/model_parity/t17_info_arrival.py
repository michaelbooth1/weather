"""T17 market information-arrival study (model-parity swarm v2, development only).

The market is the OBJECT of study only; no market field ever enters a candidate (rule 2).

Part A (t17-d1, registered DIAGNOSTIC): event-centred step test (F3 method, extended) of per-snapshot
market Brier, served Brier, excess (served - market) and market movement (sum |dp_market| vs the
previous snapshot) around five kinds of information event:
  METAR  routine METAR valid times (IEM, non-COR); informative = set a new running max for the day
  NBH    NBH cycle S3 LastModified (A-NBH); informative = |change of max TMP over the target-day hours
         still ahead (same hour set, new vs previous cycle)| >= 1 F
  HRRR   production arrival of a changed hrrr_high (hrrr_fetched_at of the first snapshot carrying it)
  NBMV2  captured NBM v2 cycle switch at v2_available_at; informative = |d v2_mean| >= 1 F
  NWS    nws_grid_updated_at switch; informative = |d nws_grid_high_raw| >= 1 F
Event windows are located with events after t: SCOREBOARD ONLY, never a candidate input.

Part B (t17-r1, registered candidate): METAR fast floor (zero-parameter), plus control t17-c0
(served + harness floor), and paired marginals vs t17-c0 and vs the t3-r3 rung.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t17_info_arrival
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t17")
METAR = Path(r"C:\swarm\data\iem\metar")
NBH = Path(r"C:\swarm\data\nbh\nbh_tidy.parquet")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text(encoding="utf-8"))["stations"]
STOP = Path(r"C:\swarm\STOP")
MIN = np.timedelta64(1, "m")
STRATA = ("before_20260823", "from_20260823")
GROUPS = h.BLOCKS + (("00-16", 0, 16), ("all", 0, 23))


def check_stop():
    if STOP.exists():
        raise SystemExit("STOP present")


def registered(ids):
    rows = [json.loads(x) for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    reg = {r["id"]: r for r in rows if r.get("agent") == "t17"}
    for rid in ids:
        r = reg[rid]
        assert hashlib.sha256(r["text"].encode("utf-8")).hexdigest() == r["sha256"], rid
    return reg


def naive(series):
    return pd.to_datetime(pd.Series(series), utc=True, format="ISO8601").dt.tz_localize(None) \
        .dt.as_unit("us").to_numpy()


def half_up(x):
    return np.floor(np.asarray(x, float) + 0.5)


def load_metar(station):
    m = pd.read_parquet(METAR / f"{station}.parquet",
                        columns=["report_type", "valid_utc", "available_utc", "local_date", "is_cor",
                                 "tgroup_c", "main_temp_c"])
    m = m[~m.is_cor].copy()
    m["temp_f"] = half_up(np.where(m.tgroup_c.notna(), m.tgroup_c * 1.8 + 32, m.main_temp_c * 1.8 + 32))
    m = m[np.isfinite(m.temp_f)].sort_values("valid_utc").reset_index(drop=True)
    m["local_date"] = m.local_date.astype(str)
    return m


# ----------------------------------------------------------------------------- events

def metar_events():
    rows = []
    for st in STATIONS:
        m = load_metar(st)
        prev = m.groupby("local_date").temp_f.transform(lambda s: s.cummax().shift())
        r = m[m.report_type == "routine"].copy()
        pv = prev[r.index]
        r["cls"] = np.where(pv.isna(), "na", np.where(r.temp_f > pv, "inf", "uninf"))
        rows.append(pd.DataFrame({"station": st, "date": r.local_date, "time": naive(r.valid_utc), "cls": r.cls}))
    return pd.concat(rows, ignore_index=True)


def nbh_events(dates):
    n = pd.read_parquet(NBH, columns=["station", "field", "value", "cycle_utc", "valid_utc", "available_utc"])
    n = n[n.field == "TMP"].copy()
    n["value"] = pd.to_numeric(n.value, errors="coerce")
    rows = []
    for st, g in n.groupby("station"):
        tz = ZoneInfo(STATIONS[st]["tzname"])
        g = g.assign(ld=g.valid_utc.dt.tz_convert(tz).dt.strftime("%Y-%m-%d"))
        cycles = g.drop_duplicates("cycle_utc")[["cycle_utc", "available_utc"]].sort_values("cycle_utc")
        by_cycle = {c: x for c, x in g.groupby("cycle_utc")}
        prev = None
        for c, lm in zip(cycles.cycle_utc, cycles.available_utc):
            cur = by_cycle[c]
            if prev is not None:
                for ld in sorted(set(cur.ld) & dates):
                    a = cur[(cur.ld == ld) & (cur.valid_utc > lm)].set_index("valid_utc").value
                    b = prev[(prev.ld == ld)].set_index("valid_utc").value
                    common = a.index.intersection(b.index)
                    if len(common) == 0:
                        continue
                    dlt = a[common].max() - b[common].max()
                    rows.append({"station": st, "date": ld, "time": lm, "cls": "inf" if abs(dlt) >= 1 else "uninf"})
            prev = cur
    e = pd.DataFrame(rows)
    e["time"] = naive(e.time)
    return e


def captured_events(snaps, value_col, switch_col, time_col):
    s = snaps.sort_values(["market", "date", "captured_at_utc"])
    g = s.groupby(["market", "date"], sort=False)
    sw = (g[switch_col].shift() != s[switch_col]) & g[switch_col].shift().notna() & s[switch_col].notna()
    dv = (s[value_col] - g[value_col].shift()).abs()
    e = s[sw & s[time_col].notna()]
    out = pd.DataFrame({"station": e.station.to_numpy(), "date": e.date.to_numpy(),
                        "time": naive(e[time_col]),
                        "cls": np.where(dv[sw & s[time_col].notna()].to_numpy() >= 1, "inf", "uninf")})
    return out.drop_duplicates(["station", "date", "time"])


# ----------------------------------------------------------------------------- step statistics

def attach(S, ev, shift_min=0):
    """x = t - V for the earliest event V > t-30 min of the same station-date (window [-30,30))."""
    x = np.full(len(S), np.nan)
    cls = np.full(len(S), "", dtype=object)
    eid = np.full(len(S), -1, dtype=np.int64)
    ev = ev.assign(time=ev.time + np.timedelta64(shift_min, "m")).sort_values("time").reset_index(drop=True)
    ev["eid"] = np.arange(len(ev))
    groups = {k: g for k, g in ev.groupby(["station", "date"])}
    for k, gi in S.groupby(["station", "date"]).indices.items():
        g = groups.get(k)
        if g is None:
            continue
        v = g.time.to_numpy()
        t = S.t.to_numpy()[gi]
        q = np.searchsorted(v, t - 30 * MIN, side="right")
        okq = q < len(v)
        qq = np.minimum(q, len(v) - 1)
        xx = (t - v[qq]) / MIN
        ok = okq & (xx >= -30) & (xx < 30)
        x[gi[ok]] = xx[ok]
        cls[gi[ok]] = g.cls.to_numpy()[qq[ok]]
        eid[gi[ok]] = g.eid.to_numpy()[qq[ok]]
    return x, cls, eid


def cell_sums(S, col, x, eid, mask, after, before=(-20, 0)):
    f = pd.DataFrame({"date": S.date.to_numpy(), "market": S.market.to_numpy(), "v": S[col].to_numpy(),
                      "x": x, "eid": eid})[mask & ~np.isnan(x) & S[col].notna().to_numpy()]
    if not len(f):
        return None
    f["r"] = f.v - f.groupby("eid").v.transform("mean")
    aft = ((f.x >= after[0]) & (f.x < after[1])).to_numpy()
    bef = ((f.x >= before[0]) & (f.x < before[1])).to_numpy()
    f = f.assign(a=np.where(aft, f.r, 0.0), na=aft.astype(float), b=np.where(bef, f.r, 0.0), nb=bef.astype(float))
    return f.groupby(["date", "market"])[["a", "na", "b", "nb"]].sum()


def boot_step(c, d):
    idx = np.array([d.key_index[k] for k in c.index])
    w = d.w[:, idx]
    one = np.ones((1, len(c)))
    with np.errstate(invalid="ignore", divide="ignore"):
        f = lambda ww: (ww @ c.a.to_numpy()) / (ww @ c.na.to_numpy()) - (ww @ c.b.to_numpy()) / (ww @ c.nb.to_numpy())
        return float(f(one)[0]), f(w)


def q95(b):
    b = b[np.isfinite(b)]
    return [float(x) for x in np.quantile(b, [.025, .975])] if len(b) else [None, None]


def step_table(S, d, ev, after, cols):
    xr, cr, er = attach(S, ev)
    xp, cp, ep = attach(S, ev, 30)
    out = {}
    hours = S.local_hour.to_numpy()
    strata = S.stratum.to_numpy()
    for gname, lo, hi in GROUPS:
        for stt in STRATA:
            base = (hours >= lo) & (hours <= hi) & (strata == stt)
            for col in cols:
                res = {}
                parts = {}
                for lab, m in (("all", np.ones(len(S), bool)), ("inf", cr == "inf"), ("uninf", cr == "uninf")):
                    c = cell_sums(S, col, xr, er, base & m, after)
                    if c is None or c.na.sum() == 0 or c.nb.sum() == 0:
                        continue
                    pt, bt = boot_step(c, d)
                    parts[lab] = (c, pt, bt)
                    res[lab] = {"step": pt, "ci95": q95(bt), "events": int(len(np.unique(er[base & m & (er >= 0)]))),
                                "snaps_after": int(c.na.sum()), "snaps_before": int(c.nb.sum())}
                cpl = cell_sums(S, col, xp, ep, base, after)
                if cpl is not None and cpl.na.sum() > 0 and cpl.nb.sum() > 0 and "all" in parts:
                    pp, bp = boot_step(cpl, d)
                    res["placebo"] = {"step": pp, "ci95": q95(bp)}
                    # real - placebo on common cells
                    ca = parts["all"][0]
                    j = ca.join(cpl, lsuffix="", rsuffix="_p", how="inner")
                    if len(j):
                        pr, br = boot_step(j[["a", "na", "b", "nb"]], d)
                        pq, bq = boot_step(j[["a_p", "na_p", "b_p", "nb_p"]].set_axis(["a", "na", "b", "nb"], axis=1), d)
                        res["real_minus_placebo"] = {"est": pr - pq, "ci95": q95(br - bq)}
                if "inf" in parts and "uninf" in parts:
                    ci_, cu = parts["inf"][0], parts["uninf"][0]
                    j = ci_.join(cu, lsuffix="_i", rsuffix="_u", how="inner")
                    j = j[(j.na_i > 0) & (j.nb_i > 0) & (j.na_u > 0) & (j.nb_u > 0)]
                    if len(j) >= 5:
                        pi_, bi_ = boot_step(j[["a_i", "na_i", "b_i", "nb_i"]].set_axis(["a", "na", "b", "nb"], axis=1), d)
                        pu, bu = boot_step(j[["a_u", "na_u", "b_u", "nb_u"]].set_axis(["a", "na", "b", "nb"], axis=1), d)
                        res["did_inf_minus_uninf"] = {"est": pi_ - pu, "ci95": q95(bi_ - bu), "cells": int(len(j))}
                # per-market sign of the all-event step
                if "all" in parts:
                    ca = parts["all"][0].reset_index()
                    pm = ca.groupby("market").apply(
                        lambda g: g.a.sum() / g.na.sum() - g.b.sum() / g.nb.sum()
                        if g.na.sum() > 0 and g.nb.sum() > 0 else np.nan, include_groups=False)
                    res["per_market_step"] = {k: float(v) for k, v in pm.items()}
                    res["markets_negative"] = int((pm < 0).sum())
                out[f"{gname}|{stt}|{col}"] = res
    return out


def onset_curve(S, d, ev, cols=("c_market", "c_served", "mv_market")):
    """2-min binned residual curve around informative events; drop fractions with W intervals."""
    x, cls, eid = attach(S, ev)
    res = {}
    for stt in STRATA:
        for gname, lo, hi in (("all", 0, 23), ("10-16", 10, 16), ("13-16", 13, 16)):
            base = (S.stratum.to_numpy() == stt) & S.local_hour.between(lo, hi).to_numpy() & (cls == "inf")
            for col in cols:
                f = pd.DataFrame({"date": S.date.to_numpy(), "market": S.market.to_numpy(),
                                  "v": S[col].to_numpy(), "x": x, "eid": eid})[base & ~np.isnan(x)]
                f = f[f.v.notna()]
                f["r"] = f.v - f.groupby("eid").v.transform("mean")
                f["bin"] = np.floor(f.x / 2) * 2
                curve = f.groupby("bin").r.agg(["mean", "size"])
                # drop share before IEM availability: (M[0,10) - M[-20,0)) / (M[15,30) - M[-20,0))
                def sums(lo_, hi_):
                    m = (f.x >= lo_) & (f.x < hi_)
                    return f.assign(a=np.where(m, f.r, 0.0), n=m.astype(float)).groupby(["date", "market"])[["a", "n"]].sum()
                pre, early, post = sums(-20, 0), sums(0, 10), sums(15, 30)
                c = pre.join(early, rsuffix="_e").join(post, rsuffix="_p")
                c = c[(c.n > 0) & (c.n_e > 0) & (c.n_p > 0)]
                idx = np.array([d.key_index[k] for k in c.index])
                w = d.w[:, idx]
                def frac(ww):
                    with np.errstate(invalid="ignore", divide="ignore"):
                        mp = (ww @ c.a.to_numpy()) / (ww @ c.n.to_numpy())
                        me = (ww @ c.a_e.to_numpy()) / (ww @ c.n_e.to_numpy())
                        mq = (ww @ c.a_p.to_numpy()) / (ww @ c.n_p.to_numpy())
                        return me - mp, mq - mp
                one = np.ones((1, len(c)))
                e1, t1 = frac(one)
                eb, tb = frac(w)
                res[f"{stt}|{gname}|{col}"] = {
                    "curve_2min": {str(int(k)): [float(v["mean"]), int(v["size"])] for k, v in curve.iterrows()},
                    "change_0_10_vs_pre": {"est": float(e1[0]), "ci95": q95(eb)},
                    "change_15_30_vs_pre": {"est": float(t1[0]), "ci95": q95(tb)},
                    "share_of_drop_in_0_10": {"est": float(e1[0] / t1[0]) if t1[0] != 0 else None,
                                              "ci95": q95(eb / tb)},
                    "events": int(len(np.unique(eid[base & (eid >= 0)])))}
    return res


# ----------------------------------------------------------------------------- candidate r1

def metar_runmax(snaps):
    out = np.full(len(snaps), np.nan)
    for st, gi in snaps.groupby("station").indices.items():
        m = load_metar(st)
        m = m.sort_values("available_utc").reset_index(drop=True)
        m["runmax"] = m.groupby("local_date").temp_f.cummax()
        avail = naive(m.available_utc)
        t = naive(snaps.captured_at_utc.to_numpy()[gi])
        i = np.searchsorted(avail, t, side="right") - 1
        ok = i >= 0
        ii = np.where(ok, i, 0)
        same = ok & (m.local_date.to_numpy()[ii] == snaps.date.to_numpy()[gi])
        h.assert_point_in_time(m.available_utc.to_numpy()[ii][same], snaps.captured_at_utc.to_numpy()[gi][same])
        # local_date running max at the latest available report: need the max over that date's reports
        # available <= t; cummax in available order within local_date gives exactly that.
        out[gi[same]] = m.runmax.to_numpy()[ii][same]
    return out


def build_r1(snaps, bands):
    R = metar_runmax(snaps)
    rmap = pd.Series(R, index=snaps.row_key)
    rb = rmap.reindex(bands.row_key.to_numpy()).to_numpy()
    hi = np.where(bands.kind.to_numpy() == "gte", np.inf, bands.high.to_numpy(float))
    p = bands.p_served.to_numpy(float).copy()
    p[~np.isnan(rb) & (hi < rb)] = 0.0
    cand = bands[["row_key", "band_index"]].assign(p=p)
    covered = ~np.isnan(rb)
    cand = cand[covered]
    tot = cand.groupby("row_key").p.transform("sum")
    cand = cand[tot > 0].assign(p=lambda f: f.p / f.groupby("row_key").p.transform("sum"))
    changed = int(((~np.isnan(rb)) & (hi < rb) & (bands.p_served.to_numpy() > 0)).sum())
    return cand, {"snapshots_with_metar_today": int(np.isfinite(R).sum()), "band_rows_zeroed_with_mass": changed,
                  "served_mass_removed_total": float(bands.p_served.to_numpy()[(~np.isnan(rb)) & (hi < rb)].sum())}


def paired(d, cand_a, cand_b):
    """Paired all-row Brier difference a - b per group x stratum (harness floor + fallback for both)."""
    pa, ua, _ = h._candidate_vector(cand_a, d, False)
    pb, ub, _ = h._candidate_vector(cand_b, d, False)
    sa = h._snapshot_mean(d, (pa - d.y) ** 2)
    sb = h._snapshot_mean(d, (pb - d.y) ** 2)
    fr = d.snaps[["date", "market", "stratum", "local_hour"]].assign(delta=sa - sb)
    out = {}
    for g, lo, hi in GROUPS:
        for stt in STRATA + ("pooled",):
            m = fr.local_hour.between(lo, hi) & ((fr.stratum == stt) if stt != "pooled" else True)
            c = fr[m].groupby(["date", "market"]).delta.mean().reset_index()
            idx = np.array([d.key_index[(a, b)] for a, b in zip(c.date, c.market)])
            r = h.interval(idx, c.delta.to_numpy())
            pm = c.groupby("market").delta.mean()
            out[f"{g}|{stt}"] = {"est": r["estimate"], "ci95": r["ci95"],
                                 "markets_negative": int((pm < 0).sum()), "markets_positive": int((pm > 0).sum())}
    return out


def main():
    check_stop()
    registered(["t17-r1", "t17-d1", "t17-c0"])
    OUT.mkdir(parents=True, exist_ok=True)
    d = h.data()
    assert (d.snaps.date <= h.LAST_TARGET_DATE).all()
    rows_after = int((d.snaps.date > h.LAST_TARGET_DATE).sum())
    snaps, bands = h.candidate_inputs()
    assert (snaps.row_key.to_numpy() == d.snaps.row_key.to_numpy()).all()

    # ---------------- scoreboard frame (market + labels, never fed to a candidate)
    S = d.snaps[["row_key", "market", "date", "stratum", "local_hour", "block"]].copy()
    S["station"] = snaps.station.to_numpy()
    S["t"] = naive(snaps.captured_at_utc)
    S["c_market"] = h._snapshot_mean(d, d.se_market)
    S["c_served"] = h._snapshot_mean(d, d.se_served)
    S["excess"] = S.c_served - S.c_market
    # market movement: sum |p_market(t) - p_market(prev snapshot, same market-day)| over bands
    pm = pd.DataFrame({"rk": d.bands.row_key.to_numpy(), "bi": d.bands.band_index.to_numpy(), "p": d.p_market})
    order = S.sort_values(["market", "date", "t"]).index.to_numpy()
    prev_rk = pd.Series(S.row_key.to_numpy()[order]).groupby(
        [S.market.to_numpy()[order], S.date.to_numpy()[order]]).shift()
    prev_map = pd.Series(prev_rk.to_numpy(), index=S.row_key.to_numpy()[order])
    pm["prev_rk"] = prev_map.reindex(pm.rk.to_numpy()).to_numpy()
    pidx = pd.Series(pm.p.to_numpy(), index=pd.MultiIndex.from_arrays([pm.rk, pm.bi]))
    pm["p_prev"] = pidx.reindex(pd.MultiIndex.from_arrays([pm.prev_rk, pm.bi])).to_numpy()
    mv = pm.assign(a=(pm.p - pm.p_prev).abs()).groupby("rk", sort=False).a.sum(min_count=1)
    S["mv_market"] = mv.reindex(S.row_key.to_numpy()).to_numpy()
    S.loc[pd.isna(prev_map.reindex(S.row_key.to_numpy()).to_numpy()), "mv_market"] = np.nan

    check_stop()
    dates = set(S.date.unique())
    events = {
        "METAR": (metar_events(), (5, 25)),
        "NBH": (nbh_events(dates), (0, 20)),
        "HRRR": (captured_events(snaps, "hrrr_high", "hrrr_high", "hrrr_fetched_at"), (0, 20)),
        "NBMV2": (captured_events(snaps, "v2_mean", "v2_cycle_key", "v2_available_at"), (0, 20)),
        "NWS": (captured_events(snaps, "nws_grid_high_raw", "nws_grid_updated_at", "nws_grid_updated_at"), (0, 20)),
    }
    ev_counts = {}
    for k, (ev, _) in events.items():
        evd = ev[ev.date.isin(dates)]
        ev_counts[k] = {"events": int(len(evd)), "by_cls": evd.cls.value_counts().to_dict(),
                        "minute_of_hour_median": float(np.median(
                            pd.to_datetime(evd.time).dt.minute)) if len(evd) else None}
    print("events", json.dumps(ev_counts))
    steps = {}
    cols = ["c_market", "c_served", "excess", "mv_market"]
    for k, (ev, after) in events.items():
        check_stop()
        steps[k] = step_table(S, d, ev[ev.date.isin(dates)], after, cols)
        print("done", k, flush=True)
    onset = onset_curve(S, d, events["METAR"][0][lambda e: e.date.isin(dates)])
    # also a METAR step with a [10,30) after-window (strictly after IEM availability) for the record
    steps["METAR_after10"] = step_table(S, d, events["METAR"][0][lambda e: e.date.isin(dates)], (10, 30),
                                        ["c_market", "c_served", "excess"])
    (OUT / "t17_d1_steps.json").write_text(json.dumps({"event_counts": ev_counts, "steps": steps,
                                                       "onset": onset}, indent=1, default=str), encoding="utf-8")

    # ---------------- candidate r1, control c0, marginals
    check_stop()
    cand, meta = build_r1(snaps, bands)
    r1 = h.score(cand, name="t17_r1_metar_fast_floor")
    assert r1["rows_with_target_after_2026_09_29"] == 0
    if r1["leakage_suspect_groups"]:
        (Path(r"C:\swarm\STOP")).write_text("t17: harness leakage suspect " + str(r1["leakage_suspect_groups"]))
        raise SystemExit("leakage suspect")
    h.save(r1, OUT)
    (OUT / "t17_r1_metar_fast_floor.md").write_text(h.markdown(r1), encoding="utf-8")
    c0c = h.served_candidate()
    c0 = h.score(c0c, name="t17_c0_served_floor_control")
    h.save(c0, OUT)
    marg = {"r1_minus_c0": paired(d, cand, c0c)}
    check_stop()
    try:
        from tools.research.model_parity import t3_baselines as t3
        t3c, _ = t3.build()
        marg["r1_minus_t3r3"] = paired(d, cand, t3c["t3-r3"])
        marg["c0_minus_t3r3"] = paired(d, c0c, t3c["t3-r3"])
    except Exception as exc:  # report, do not hide
        marg["t3r3_error"] = repr(exc)
    (OUT / "t17_marginals.json").write_text(json.dumps(marg, indent=1), encoding="utf-8")
    res = {"agent": "t17", "HARNESS_SHA256": h.harness_sha256(), "rows_with_target_after_2026_09_29": rows_after,
           "r1_meta": meta, "r1_classes": {g: r1["classes"][g]["class"] for g in r1["classes"]},
           "c0_classes": {g: c0["classes"][g]["class"] for g in c0["classes"]},
           "time_local": datetime.now().isoformat(timespec="seconds")}
    (OUT / "run_meta.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(h.markdown(r1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
