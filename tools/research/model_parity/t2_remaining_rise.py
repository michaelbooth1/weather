"""T2 remaining-rise climatology nowcast (model-parity swarm v2, development only).

Rules t2-r1/r2/r3 are registered in C:\\swarm\\registry.jsonl (00:43:30 local 2026-10-04).
History = IEM METAR/SPECI local dates <= 2026-07-31 (a-iem-1 manifest). The same state function
is used for the history grid and for the live snapshots (train/serve parity).

PIT: a METAR/SPECI row enters the state at time t only if available_utc (= valid + 10 min) <= t
and is_cor is False (asserted per snapshot via h.assert_point_in_time on the latest row used).
No market or label column is read; fitted tables use history <= 2026-07-31 only.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t2_remaining_rise
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
OUT = Path(r"C:\swarm\out\t2")
HIST_END = "2026-07-31"
MIN_DAYS = 40
TZ = {"KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
      "KAUS": "America/Chicago", "KDAL": "America/Chicago", "KHOU": "America/Chicago",
      "KORD": "America/Chicago", "KBKF": "America/Denver", "KLAX": "America/Los_Angeles",
      "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
RMAX = 40
LAG_MIN = int(os.environ.get("T2_LAG_MIN", "10"))   # 10 = manifest basis; 60 = registered sensitivity t2-r1s60


def load_station(st: str) -> pd.DataFrame:
    m = pd.read_parquet(METAR / f"{st}.parquet")
    m = m[(~m.is_cor) & m.tmpf.notna()].copy()
    if LAG_MIN != 10:
        m["available_utc"] = m.valid_utc + pd.Timedelta(minutes=LAG_MIN)
    assert ((m.available_utc - m.valid_utc) >= pd.Timedelta(minutes=10)).all()
    m["t"] = np.round(m.tmpf.to_numpy()).astype(int)
    m["local_date"] = m.local_date.astype(str)
    m = m.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").reset_index(drop=True)
    m["cmax"] = m.groupby("local_date").t.cummax()
    return m


EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def us(x) -> np.ndarray:
    """Microseconds since epoch for any tz-aware/ISO-string series."""
    x = pd.to_datetime(pd.Series(x).reset_index(drop=True), utc=True, format="ISO8601")
    return ((x - EPOCH) // pd.Timedelta(microseconds=1)).to_numpy(dtype=np.int64)


def dbin(d):
    return np.select([d <= 0, d <= 2, d <= 5], [0, 1, 2], 3)


def sbin(s):
    out = np.select([s <= -2, s <= 1], [0, 1], 2)
    return np.where(np.isnan(s), 3, out)


def state(m: pd.DataFrame, t_utc: pd.Series, dates: np.ndarray):
    """Vectorised PIT state at times t_utc (tz-aware UTC) for target local dates."""
    avail = us(m.available_utc)
    valid = us(m.valid_utc)
    tq = us(t_utc)
    idx = np.searchsorted(avail, tq, side="right") - 1
    ok = idx >= 0
    idc = np.where(ok, idx, 0)
    ok &= m.local_date.to_numpy()[idc] == dates
    M = np.where(ok, m.cmax.to_numpy()[idc], -999)
    T = np.where(ok, m.t.to_numpy()[idc], -999)
    vlat = valid[idc]
    i2 = np.searchsorted(valid, vlat - 110 * 60 * 1_000_000, side="right") - 1
    i2c = np.where(i2 >= 0, i2, 0)
    gap = vlat - valid[i2c]
    slope = np.where((i2 >= 0) & (gap <= 4 * 3600 * 1_000_000), T - m.t.to_numpy()[i2c], np.nan).astype(float)
    return ok, M, T, dbin(M - T), sbin(slope), avail[idc]


def history_table(st: str, m: pd.DataFrame) -> pd.DataFrame:
    hist = m[m.local_date <= HIST_END]
    fin = hist.groupby("local_date").t.max()
    nrows = hist.groupby("local_date").size()
    fin = fin[nrows >= 18]                     # require a reasonably complete day for the label
    days = pd.to_datetime(fin.index)
    days = days[days.month.isin([7, 8, 9, 10])]
    tz = TZ[st]
    recs = []
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            loc = (days + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(tz, nonexistent="shift_forward", ambiguous="NaT")
            keep = ~loc.isna()
            utc = loc[keep].tz_convert("UTC")
            ds = np.array([d.strftime("%Y-%m-%d") for d in days[keep]])
            ok, M, T, db, sb, _ = state(m, pd.Series(utc), ds)
            f = fin.reindex(ds).to_numpy()
            R = f - M
            recs.append(pd.DataFrame({"date": ds[ok], "month": days[keep].month[ok], "hour": hh,
                                      "db": db[ok], "sb": sb[ok], "R": R[ok]}))
    df = pd.concat(recs, ignore_index=True)
    assert (df.date <= HIST_END).all()
    df["R"] = df.R.clip(0, RMAX).astype(int)   # R<0 impossible by construction (labels from same rows)
    return df


def cell_dists(df: pd.DataFrame):
    """Return dicts keyed by (target_month, hour, db, sb) / (m,h,db) / (m,h): (probvec, ndays)."""
    out = {}
    for tm, months in ((8, (7, 8, 9)), (9, (8, 9, 10))):
        sub = df[df.month.isin(months)]
        for keys, lvl in ((["hour", "db", "sb"], 3), (["hour", "db"], 2), (["hour"], 1)):
            for k, g in sub.groupby(keys):
                k = k if isinstance(k, tuple) else (k,)
                nd = g.date.nunique()
                p = np.bincount(g.R.to_numpy(), minlength=RMAX + 1).astype(float)
                out[(tm, lvl) + tuple(int(x) for x in k)] = (p / p.sum(), nd)
    return out


def lookup(cd, tm, hour, db, sb):
    for lvl, key in ((3, (tm, 3, hour, db, sb)), (2, (tm, 2, hour, db)), (1, (tm, 1, hour))):
        v = cd.get(key)
        if v is not None and v[1] >= MIN_DAYS and (lvl != 3 or sb != 3):
            return v[0], lvl
    v = cd.get((tm, 1, hour))
    return (v[0], 1) if v is not None else (None, 0)


def band_probs(pR, M, kinds, lows, highs):
    v = M + np.arange(RMAX + 1)
    out = np.zeros(len(kinds))
    for i, (k, lo, hi) in enumerate(zip(kinds, lows, highs)):
        if k == "eq":
            sel = (v >= lo) & (v <= hi)
        elif k == "lte":
            sel = v <= lo
        else:
            sel = v >= lo
        out[i] = pR[sel].sum()
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    stations = {}
    tables = {}
    diag = {}
    for st in TZ:
        m = load_station(st)
        stations[st] = m
        df = history_table(st, m)
        tables[st] = cell_dists(df)
        diag[st] = {"hist_days": int(df.date.nunique()), "hist_first": df.date.min(), "hist_last": df.date.max(),
                    "grid_rows": int(len(df))}
    # live state per snapshot
    snaps = snaps.copy()
    snaps["tmonth"] = snaps.date.str[5:7].astype(int)
    feats = []
    for st, g in snaps.groupby("station"):
        ok, M, T, db, sb, av = state(stations[st], g.captured_at_utc, g.date.to_numpy())
        cap = us(g.captured_at_utc)
        assert (av[ok] <= cap[ok]).all()
        feats.append(pd.DataFrame({"row_key": g.row_key.to_numpy(), "ok": ok, "M": M, "T": T, "db": db, "sb": sb,
                                   "av": av, "cap": cap}, index=g.index))
    F = pd.concat(feats).loc[snaps.index]
    snaps = snaps.join(F.drop(columns="row_key"))
    # rule-1 harness assert on a sample of every covered snapshot's latest row
    for _, r in snaps[snaps.ok].sample(2000, random_state=1).iterrows():
        h.assert_point_in_time(EPOCH + pd.Timedelta(microseconds=int(r.av)), r.captured_at_utc)

    bands = bands.merge(snaps[["row_key", "station", "tmonth", "local_hour", "ok", "M", "db", "sb"]], on="row_key")
    bands = bands.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    p1 = np.full(len(bands), np.nan)
    p3 = np.full(len(bands), np.nan)
    lvls = {}
    for (rk), g in bands.groupby("row_key", sort=False):
        r0 = g.iloc[0]
        if not r0.ok:
            continue
        pR, lvl = lookup(tables[r0.station], int(r0.tmonth), int(r0.local_hour), int(r0.db), int(r0.sb))
        lvls[lvl] = lvls.get(lvl, 0) + 1
        if pR is None:
            continue
        bp = band_probs(pR, int(r0.M), g.kind.to_numpy(), g.low.to_numpy(), g.high.to_numpy())
        p1[g.index] = bp
        cdf = np.cumsum(pR)
        q = int(np.searchsorted(cdf, 0.995))
        cap = int(r0.M) + q
        lowest = np.where(g.kind.to_numpy() == "lte", -999, g.low.to_numpy())
        ps = g.p_served.to_numpy() * (lowest <= cap)
        p3[g.index] = ps
    ps = bands.p_served.to_numpy()
    p2 = ps * p1
    cov = ~np.isnan(p1)
    results = {}
    variants = (("t2_r1_nowcast", p1), ("t2_r2_served_x_nowcast", p2), ("t2_r3_served_cap995", p3))
    if LAG_MIN != 10:
        variants = ((f"t2_r1s{LAG_MIN}_nowcast_lag{LAG_MIN}", p1),)
    for name, p in variants:
        c = bands.loc[cov, ["row_key", "band_index"]].assign(p=p[cov])
        tot = c.groupby("row_key").p.transform("sum")
        c = c[tot > 0]
        res = h.score(c, name=name)
        h.save(res, OUT)
        results[name] = res
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        print(h.markdown(res))
    json.dump({"diag": diag, "backoff_levels": {str(k): v for k, v in lvls.items()},
               "covered_snapshots": int(snaps.ok.sum()), "total_snapshots": int(len(snaps))},
              open(OUT / f"t2_diag_lag{LAG_MIN}.json", "w"), indent=1, default=str)
    print(json.dumps({"HARNESS_SHA256": h.harness_sha256(), "levels": lvls, "covered": int(snaps.ok.sum())}))


if __name__ == "__main__":
    main()
