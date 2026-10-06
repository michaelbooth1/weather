"""T14 cloud conditioner on remaining rise (model-parity swarm v2, development only).

Rules t14-r1..r5 are registered in C:\\swarm\\registry.jsonl before the first score.

Remaining rise R = final METAR hourly-row max (rounded tmpf, non-COR, routine+SPECI, local date)
minus the PIT running max M at time t. Climatology of R is fitted on IEM METAR history with local
dates <= 2026-07-31 only (months 7-10 of 2024, 2025 and July 2026), by station x target-month window
x local hour (quarter-hour grid) x deficit bin (M - current) x sky class. The same state function
is used for the history grid and for live snapshots (train/serve parity).

Sky class from the latest PIT METAR (available = valid + 10 min, COR excluded):
  0 = clear/few (CLR, SKC, NSC, FEW or no layer), 1 = SCT, 2 = BKN/OVC/VV.
  "all" = max cover over all reported layers; "low" = max cover over layers with base <= 10,000 ft.
GOES variant (r5): cloud_frac_3x3 (ABI-L2-ACMC) from the latest scene with available_utc =
max(scene end, S3 LastModified) <= t and scan start >= t - 75 min; <0.25 -> 0, 0.25-0.75 -> 1,
>0.75 -> 2 (thresholds fixed a priori); tables are the METAR all-layer tables (no fit on GOES).

PIT: no market or label column is read (h.candidate_inputs is allow-listed); every external row is
checked with h.assert_point_in_time. Run: cd C:\\pt\\swarm; <repo python> -m
tools.research.model_parity.t14_cloud_conditioner
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
GOES = Path(r"C:\swarm\data\goes\goes_acm_station_hour.jsonl")
OUT = Path(r"C:\swarm\out\t14")
STOP = Path(r"C:\swarm\STOP")
HIST_END = "2026-07-31"
MIN_DAYS = 40
RMAX = 40
TZ = {"KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
      "KAUS": "America/Chicago", "KDAL": "America/Chicago", "KHOU": "America/Chicago",
      "KORD": "America/Chicago", "KBKF": "America/Denver", "KLAX": "America/Los_Angeles",
      "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
COVER = {"CLR": 0, "SKC": 0, "NSC": 0, "FEW": 0, "SCT": 1, "BKN": 2, "OVC": 2, "VV": 2}
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
US = 1_000_000


def us(x) -> np.ndarray:
    x = pd.to_datetime(pd.Series(x).reset_index(drop=True), utc=True, format="ISO8601")
    return ((x - EPOCH) // pd.Timedelta(microseconds=1)).to_numpy(dtype=np.int64)


def sky_class(m: pd.DataFrame, low_only: bool) -> np.ndarray:
    out = np.zeros(len(m), dtype=int)
    for i in range(1, 5):
        c = m[f"skyc{i}"].astype(str).str.strip().map(COVER).fillna(0).to_numpy().astype(int)
        if low_only:
            lv = m[f"skyl{i}"].to_numpy()
            c = np.where(np.isfinite(lv) & (lv <= 10000), c, 0)
        out = np.maximum(out, c)
    return out


def load_station(st: str) -> pd.DataFrame:
    m = pd.read_parquet(METAR / f"{st}.parquet")
    m = m[(~m.is_cor) & m.tmpf.notna()].copy()
    m["local_date"] = m.local_date.astype(str)
    assert (m.local_date <= "2026-09-29").all()
    m["t"] = np.round(m.tmpf.to_numpy()).astype(int)
    m = m.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").reset_index(drop=True)
    m["cmax"] = m.groupby("local_date").t.cummax()
    m["sky_all"] = sky_class(m, False)
    m["sky_low"] = sky_class(m, True)
    return m


def dbin(d):
    return np.select([d <= 0, d <= 2, d <= 5], [0, 1, 2], 3)


def state(m: pd.DataFrame, tq: np.ndarray, dates: np.ndarray):
    """PIT state at times tq (us since epoch) for target local dates."""
    avail = us(m.available_utc)
    idx = np.searchsorted(avail, tq, side="right") - 1
    ok = idx >= 0
    idc = np.where(ok, idx, 0)
    ok &= m.local_date.to_numpy()[idc] == dates
    M = np.where(ok, m.cmax.to_numpy()[idc], -999)
    T = np.where(ok, m.t.to_numpy()[idc], -999)
    return dict(ok=ok, M=M, db=dbin(M - T), sa=m.sky_all.to_numpy()[idc], sl=m.sky_low.to_numpy()[idc],
                av=avail[idc])


def history(st: str, m: pd.DataFrame) -> pd.DataFrame:
    hist = m[m.local_date <= HIST_END]
    fin = hist.groupby("local_date").t.max()
    fin = fin[hist.groupby("local_date").size() >= 18]
    days = pd.to_datetime(fin.index)
    days = days[days.month.isin([7, 8, 9, 10])]
    recs = []
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            loc = (days + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(TZ[st], nonexistent="shift_forward",
                                                                          ambiguous="NaT")
            keep = ~loc.isna()
            ds = np.array([d.strftime("%Y-%m-%d") for d in days[keep]])
            s = state(m, us(pd.Series(loc[keep].tz_convert("UTC"))), ds)
            ok = s["ok"]
            R = fin.reindex(ds).to_numpy() - s["M"]
            recs.append(pd.DataFrame({"date": ds[ok], "month": days[keep].month[ok], "hour": hh, "db": s["db"][ok],
                                      "sa": s["sa"][ok], "sl": s["sl"][ok], "R": R[ok]}))
    df = pd.concat(recs, ignore_index=True)
    assert (df.date <= HIST_END).all()
    df["R"] = df.R.clip(0, RMAX).astype(int)
    return df


class Tables:
    """Distributions of R keyed by (tmonth, level, hour, db[, cls]) for one sky column."""

    def __init__(self, df: pd.DataFrame, col: str):
        self.d = {}
        for tm, months in ((8, (7, 8, 9)), (9, (8, 9, 10))):
            sub = df[df.month.isin(months)]
            for keys, lvl in ((["hour", "db", col], 3), (["hour", "db"], 2), (["hour"], 1)):
                for k, g in sub.groupby(keys):
                    k = k if isinstance(k, tuple) else (k,)
                    p = np.bincount(g.R.to_numpy(), minlength=RMAX + 1).astype(float)
                    self.d[(tm, lvl) + tuple(int(x) for x in k)] = (p / p.sum(), g.date.nunique())

    def get(self, tm, hour, db, cls):
        """(conditioned dist, its level, unconditioned dist at (hour, db) or backoff)."""
        base = None
        for lvl, key in ((2, (tm, 2, hour, db)), (1, (tm, 1, hour))):
            v = self.d.get(key)
            if v is not None and v[1] >= MIN_DAYS:
                base = v[0]
                break
        if cls is not None:
            v = self.d.get((tm, 3, hour, db, cls))
            if v is not None and v[1] >= MIN_DAYS and base is not None:
                return v[0], 3, base
        return base, (0 if base is None else 2), base


def band_mass(C: np.ndarray, M: np.ndarray, kind: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Band masses from per-band-row CDF arrays C (n x RMAX+1) of R, running max M."""
    n = len(M)
    rows = np.arange(n)

    def cdf(v):  # P(final <= v)
        j = (v - M).astype(int)
        val = C[rows, np.clip(j, 0, RMAX)]
        return np.where(j < 0, 0.0, val)

    eq = cdf(hi) - cdf(lo - 1)
    lte = cdf(lo)
    gte = 1.0 - cdf(lo - 1)
    return np.clip(np.where(kind == "eq", eq, np.where(kind == "lte", lte, gte)), 0.0, None)


def goes_class(snaps: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    g = pd.read_json(GOES, lines=True)
    g = g[g.cloud_frac_3x3.notna() & (g.n_valid_3x3 > 0)].copy()
    g["av"] = us(g.available_utc)
    g["ss"] = us(g.scene_start_utc)
    g = g.sort_values(["station", "av"])
    cls = np.full(len(snaps), -1)
    avs = np.zeros(len(snaps), dtype=np.int64)
    for st, s in snaps.groupby("station"):
        gs = g[g.station == st]
        if gs.empty:
            continue
        tq = us(s.captured_at_utc)
        i = np.searchsorted(gs.av.to_numpy(), tq, side="right") - 1
        ok = i >= 0
        ic = np.where(ok, i, 0)
        ok &= (tq - gs.ss.to_numpy()[ic]) <= 75 * 60 * US
        f = gs.cloud_frac_3x3.to_numpy()[ic]
        c = np.select([f < 0.25, f <= 0.75], [0, 1], 2)
        pos = snaps.index.get_indexer(s.index)
        cls[pos] = np.where(ok, c, -1)
        avs[pos] = gs.av.to_numpy()[ic]
    return cls, avs


GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23),
          ("00-16", 0, 16), ("all", 0, 23))


def paired(bands, pa, pb, cov):
    """Paired Brier difference (a - b) per block x stratum, using harness scoring internals."""
    d = h.data()
    se = []
    for p in (pa, pb):
        c = bands.loc[cov, ["row_key", "band_index"]].assign(p=p[cov])
        c = c[c.groupby("row_key").p.transform("sum") > 0]
        pc, _, _ = h._candidate_vector(c, d, False)
        se.append(h._snapshot_mean(d, (pc - d.y) ** 2))
    fr = d.snaps[["date", "market", "stratum", "local_hour"]].copy()
    fr["diff"] = se[0] - se[1]
    res = {}
    for g, a, b in GROUPS:
        for s in ("before_20260823", "from_20260823", "pooled"):
            m = fr.local_hour.between(a, b) & ((fr.stratum == s) if s != "pooled" else True)
            cells = fr[m].groupby(["date", "market"])["diff"].mean().reset_index()
            idx = np.array([d.key_index[(x, y)] for x, y in zip(cells.date, cells.market)])
            iv = h.interval(idx, cells["diff"].to_numpy())
            pm = cells.groupby("market")["diff"].mean()
            res[f"{g}|{s}"] = {"estimate": iv["estimate"], "ci95": iv["ci95"],
                               "markets_negative": int((pm < 0).sum()), "markets": int(len(pm))}
    return res


def main():
    if STOP.exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    snaps = snaps.reset_index(drop=True)
    snaps["tmonth"] = snaps.date.str[5:7].astype(int)
    tq_all = us(snaps.captured_at_utc)
    st_tabs, diag = {}, {}
    feat = pd.DataFrame(index=snaps.index, columns=["ok", "M", "db", "sa", "sl", "av"])
    for st in TZ:
        m = load_station(st)
        df = history(st, m)
        st_tabs[st] = {"all": Tables(df, "sa"), "low": Tables(df, "sl")}
        diag[st] = {"hist_days": int(df.date.nunique()), "hist_last": df.date.max(),
                    "sky_all_share_hist": df.sa.value_counts(normalize=True).round(3).to_dict()}
        sel = (snaps.station == st).to_numpy()
        s = state(m, tq_all[sel], snaps.date.to_numpy()[sel])
        for k in feat.columns:
            feat.loc[sel, k] = s[k]
    snaps = snaps.join(feat.astype({"ok": bool, "M": int, "db": int, "sa": int, "sl": int, "av": np.int64}))
    assert (snaps.av[snaps.ok] <= tq_all[snaps.ok.to_numpy()]).all()
    for _, r in snaps[snaps.ok].sample(3000, random_state=14).iterrows():
        h.assert_point_in_time(EPOCH + pd.Timedelta(microseconds=int(r.av)), r.captured_at_utc)
    gcls, gav = goes_class(snaps)
    snaps["gc"] = gcls
    gok = snaps.gc >= 0
    for i in np.flatnonzero(gok.to_numpy())[::50]:
        h.assert_point_in_time(EPOCH + pd.Timedelta(microseconds=int(gav[i])), snaps.captured_at_utc.iloc[i])

    # per-snapshot distributions -> per-variant CDF arrays
    n = len(snaps)
    variants = {"all": "sa", "low": "sl", "goes": "gc"}
    Ccond = {v: np.full((n, RMAX + 1), np.nan) for v in variants}
    Cbase = np.full((n, RMAX + 1), np.nan)
    lvl3 = {v: np.zeros(n, bool) for v in variants}
    for i, r in enumerate(snaps.itertuples()):
        if not r.ok:
            continue
        tabs = st_tabs[r.station]
        for v, col in variants.items():
            cls = getattr(r, col)
            tab = tabs["low" if v == "low" else "all"]
            if v == "goes" and cls < 0:
                continue
            pc, lvl, pb = tab.get(r.tmonth, r.local_hour, r.db, int(cls))
            if pc is None:
                continue
            Ccond[v][i] = np.cumsum(pc)
            lvl3[v][i] = lvl == 3
            if v == "all":
                Cbase[i] = np.cumsum(pb)
    bands = bands.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    pos = pd.Index(snaps.row_key).get_indexer(bands.row_key)
    assert (pos >= 0).all()
    M = snaps.M.to_numpy()[pos]
    kind, lo, hi = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    ps = bands.p_served.to_numpy()
    mb = band_mass(np.nan_to_num(Cbase[pos]), M, kind, lo, hi)
    out = {}

    def run(name, p, cov):
        c = bands.loc[cov, ["row_key", "band_index"]].assign(p=p[cov])
        tot = c.groupby("row_key").p.transform("sum")
        c = c[tot > 0]
        res = h.score(c, name=name)
        if res.get("leakage_suspect_groups"):
            STOP.write_text(f"t14 leakage tripwire {name}: {res['leakage_suspect_groups']}\n")
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        out[name] = res
        print(name, json.dumps(res["classes"], default=str)[:1500])

    def tilt(v):
        mc = band_mass(np.nan_to_num(Ccond[v][pos]), M, kind, lo, hi)
        ratio = np.where(mb > 1e-9, mc / np.maximum(mb, 1e-9), 1.0)
        return ps * ratio, ~np.isnan(Ccond[v][pos][:, 0]) & lvl3[v][pos]

    covA = ~np.isnan(Ccond["all"][pos][:, 0])
    pA = band_mass(np.nan_to_num(Ccond["all"][pos]), M, kind, lo, hi)
    run("t14_r1_cloud_nowcast", pA, covA)
    run("t14_r2_served_x_cloud_nowcast", ps * pA, covA)
    run("t14_c1_nocloud_nowcast_control", mb, covA)
    out["marginal_r1_minus_c1"] = paired(bands, pA, mb, covA)
    print("marginal r1-c1", json.dumps(out["marginal_r1_minus_c1"])[:2500])
    json.dump({"HARNESS_SHA256": h.harness_sha256(), "development": True,
               "note": "paired r1 - c1 Brier difference on identical covered rows (all-row; uncovered rows are "
                       "served in both so contribute 0); harness _candidate_vector/interval reused",
               "tables": out["marginal_r1_minus_c1"]}, open(OUT / "t14_marginal_r1_minus_c1.json", "w"), indent=1)
    p3, c3 = tilt("all")
    run("t14_r3_served_cloud_tilt_all", p3, c3)
    p4, c4 = tilt("low")
    run("t14_r4_served_cloud_tilt_low", p4, c4)
    p5, c5 = tilt("goes")
    run("t14_r5_served_cloud_tilt_goes", p5, c5)
    cov = {"snapshots": n, "metar_state_ok": int(snaps.ok.sum()), "goes_cls_ok": int(gok.sum()),
           "lvl3_all": int(lvl3["all"].sum()), "lvl3_low": int(lvl3["low"].sum()), "lvl3_goes": int(lvl3["goes"].sum()),
           "sky_all_live": snaps.sa[snaps.ok].value_counts().to_dict(),
           "goes_live": snaps.gc[gok].value_counts().to_dict(),
           "agree_goes_metar_all": float((snaps.gc[gok & snaps.ok] == snaps.sa[gok & snaps.ok]).mean())}
    json.dump({"diag": diag, "coverage": cov, "HARNESS_SHA256": h.harness_sha256()},
              open(OUT / "t14_diag.json", "w"), indent=1, default=str)
    print(json.dumps(cov, default=str))


if __name__ == "__main__":
    main()
