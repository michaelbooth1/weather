"""T13 neighbour-station running maxima / spatial anomaly (model-parity swarm v2, development only).

Rules t13-r1, t13-r2, t13-r3, t13-c1 (and sensitivity t13-r1s60) are registered in
C:\\swarm\\registry.jsonl before the first score.

Hypothesis: when nearby ASOS/AWOS stations (<= 50 km, closest 6, a-iem-3 manifest) already show a
running max above the market station's running max M, the market station still has rise to come.

State at time t (one function, shared by the history grid and the live snapshots):
  market station: non-COR METAR/SPECI rows (a-iem-1), available = valid + 10 min <= t, local date
  = target date -> running max M, current T, deficit bin db = bin(M - T).
  neighbour k: non-COR rows with tmpf, available_utc_min (= valid + 10 min) <= t, local date (in the
  market station's time zone) = target date -> running max N_k, latest temperature C_k (valid within
  90 min of t).
  A  = median_k (N_k - M) over neighbours with a running max (>= 2 needed)
  Ac = median_k (C_k - T) over neighbours with a current temperature (>= 2 needed)
  Bins: terciles of A (resp. Ac) per station x local hour, fitted on history <= 2026-07-31.
History: local dates 2026-05-01..2026-07-31 (neighbour archive starts 05-01), quarter-hour grid,
final F = max rounded tmpf of the market station over the local date (>= 18 rows), R = F - M.
Cells pool local hours h-1..h+1; a cell needs >= MIN_DAYS distinct days.

PIT: no market or label column is read (h.candidate_inputs is allow-listed); every external row
used is checked against captured_at_utc (vectorised assert + h.assert_point_in_time on samples).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t13_neighbour_anomaly
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
NBR = Path(r"C:\swarm\data\iem\neighbours\neighbours_metar.parquet")
OUT = Path(r"C:\swarm\out\t13")
STOP = Path(r"C:\swarm\STOP")
HIST_START, HIST_END = "2026-05-01", "2026-07-31"
MIN_DAYS = 25
RMAX = 40
CUR_MAX_AGE_MIN = 90
LAG_MIN = int(os.environ.get("T13_LAG_MIN", "10"))  # 10 = manifest basis; 60 = registered sensitivity
TZ = {"KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
      "KAUS": "America/Chicago", "KDAL": "America/Chicago", "KHOU": "America/Chicago",
      "KORD": "America/Chicago", "KBKF": "America/Denver", "KLAX": "America/Los_Angeles",
      "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
US = 1_000_000


def us(x) -> np.ndarray:
    x = pd.to_datetime(pd.Series(x).reset_index(drop=True), utc=True, format="ISO8601")
    return ((x - EPOCH) // pd.Timedelta(microseconds=1)).to_numpy(dtype=np.int64)


def dbin(d):
    return np.select([d <= 0, d <= 2, d <= 5], [0, 1, 2], 3)


def load_station(st: str) -> pd.DataFrame:
    m = pd.read_parquet(METAR / f"{st}.parquet")
    m = m[(~m.is_cor) & m.tmpf.notna()].copy()
    m["available_utc"] = m.valid_utc + pd.Timedelta(minutes=LAG_MIN)
    m["local_date"] = m.local_date.astype(str)
    assert (m.local_date <= "2026-09-29").all()
    m["t"] = np.round(m.tmpf.to_numpy()).astype(int)
    m = m.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").reset_index(drop=True)
    m["cmax"] = m.groupby("local_date").t.cummax()
    m["av"] = us(m.available_utc)
    return m


def load_neighbours(st: str, nb: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    sub = nb[(nb.market_station == st) & (~nb.is_cor) & nb.tmpf.notna()]
    for sid, g in sub.groupby("neighbour_sid"):
        g = g.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").copy()
        g["available"] = g.valid_utc + pd.Timedelta(minutes=LAG_MIN)
        assert ((g.available - g.valid_utc) >= pd.Timedelta(minutes=10)).all()
        g["local_date"] = g.valid_utc.dt.tz_convert(TZ[st]).dt.strftime("%Y-%m-%d")
        assert (g.local_date <= "2026-09-29").all()
        g["t"] = np.round(g.tmpf.to_numpy()).astype(int)
        g["cmax"] = g.groupby("local_date").t.cummax()
        g["av"] = us(g.available)
        g["vu"] = us(g.valid_utc)
        out.append(g.reset_index(drop=True))
    return out


def state(m: pd.DataFrame, nbrs: list[pd.DataFrame], tq: np.ndarray, dates: np.ndarray):
    """PIT state at times tq (us since epoch) for target local dates."""
    idx = np.searchsorted(m.av.to_numpy(), tq, side="right") - 1
    ok = idx >= 0
    idc = np.where(ok, idx, 0)
    ok &= m.local_date.to_numpy()[idc] == dates
    M = np.where(ok, m.cmax.to_numpy()[idc], -999)
    T = np.where(ok, m.t.to_numpy()[idc], -999)
    av_used = np.where(ok, m.av.to_numpy()[idc], 0)
    NA = np.full((len(nbrs), len(tq)), np.nan)
    NC = np.full((len(nbrs), len(tq)), np.nan)
    for k, g in enumerate(nbrs):
        j = np.searchsorted(g.av.to_numpy(), tq, side="right") - 1
        okk = j >= 0
        jc = np.where(okk, j, 0)
        okk &= g.local_date.to_numpy()[jc] == dates
        av_used = np.where(okk, np.maximum(av_used, g.av.to_numpy()[jc]), av_used)
        NA[k] = np.where(okk, g.cmax.to_numpy()[jc], np.nan)
        fresh = okk & ((tq - g.vu.to_numpy()[jc]) <= CUR_MAX_AGE_MIN * 60 * US)
        NC[k] = np.where(fresh, g.t.to_numpy()[jc], np.nan)
    nA = np.isfinite(NA).sum(0)
    nC = np.isfinite(NC).sum(0)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            A = np.nanmedian(NA, axis=0) - M
            Ac = np.nanmedian(NC, axis=0) - T
    A = np.where(ok & (nA >= 2), A, np.nan)
    Ac = np.where(ok & (nC >= 2), Ac, np.nan)
    return dict(ok=ok, M=M, T=T, db=dbin(M - T), A=A, Ac=Ac, nA=nA, av=av_used)


def history(st: str, m: pd.DataFrame, nbrs) -> pd.DataFrame:
    hist = m[(m.local_date >= HIST_START) & (m.local_date <= HIST_END)]
    fin = hist.groupby("local_date").t.max()
    fin = fin[hist.groupby("local_date").size() >= 18]
    days = pd.to_datetime(fin.index)
    recs = []
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            loc = (days + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(TZ[st], nonexistent="shift_forward",
                                                                          ambiguous="NaT")
            keep = ~loc.isna()
            ds = np.array([d.strftime("%Y-%m-%d") for d in days[keep]])
            s = state(m, nbrs, us(pd.Series(loc[keep].tz_convert("UTC"))), ds)
            ok = s["ok"]
            R = fin.reindex(ds).to_numpy() - s["M"]
            recs.append(pd.DataFrame({"date": ds[ok], "hour": hh, "db": s["db"][ok], "A": s["A"][ok],
                                      "Ac": s["Ac"][ok], "R": R[ok]}))
    df = pd.concat(recs, ignore_index=True)
    assert (df.date <= HIST_END).all() and (df.date >= HIST_START).all()
    df["R"] = df.R.clip(0, RMAX).astype(int)
    return df


def tercile_edges(df: pd.DataFrame, col: str) -> dict:
    """Per local hour (pooled h-1..h+1) tercile edges of col, history only."""
    e = {}
    for hh in range(24):
        hs = [(hh - 1) % 24, hh, (hh + 1) % 24]
        v = df.loc[df.hour.isin(hs), col].dropna().to_numpy()
        e[hh] = (np.quantile(v, 1 / 3), np.quantile(v, 2 / 3)) if len(v) >= 30 else None
    return e


def tbin(v, hours, edges):
    out = np.full(len(v), -1)
    for i, (x, hh) in enumerate(zip(v, hours)):
        ed = edges.get(int(hh))
        if ed is None or not np.isfinite(x):
            continue
        out[i] = 0 if x < ed[0] else (1 if x <= ed[1] else 2)
    return out


class Tables:
    """P(R) by (hour window, db[, cls]) for one station."""

    def __init__(self, df: pd.DataFrame, clscol: str | None):
        self.d = {}
        for hh in range(24):
            hs = [(hh - 1) % 24, hh, (hh + 1) % 24]
            sub = df[df.hour.isin(hs)]
            for k, g in sub.groupby("db"):
                self.d[(hh, int(k), None)] = self._dist(g)
            if clscol:
                for (k, c), g in sub[sub[clscol] >= 0].groupby(["db", clscol]):
                    self.d[(hh, int(k), int(c))] = self._dist(g)

    @staticmethod
    def _dist(g):
        p = np.bincount(g.R.to_numpy(), minlength=RMAX + 1)[: RMAX + 1].astype(float)
        return p / p.sum(), g.date.nunique()

    def get(self, hh, db, cls):
        v = self.d.get((hh, db, cls))
        return v[0] if v is not None and v[1] >= MIN_DAYS else None


def band_mass(C, M, kind, lo, hi):
    n = len(M)
    rows = np.arange(n)

    def cdf(v):
        j = (v - M).astype(int)
        val = C[rows, np.clip(j, 0, RMAX)]
        return np.where(j < 0, 0.0, val)

    eq = cdf(hi) - cdf(lo - 1)
    lte = cdf(lo)
    gte = 1.0 - cdf(lo - 1)
    return np.clip(np.where(kind == "eq", eq, np.where(kind == "lte", lte, gte)), 0.0, None)


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
            msk = fr.local_hour.between(a, b) & ((fr.stratum == s) if s != "pooled" else True)
            cells = fr[msk].groupby(["date", "market"])["diff"].mean().reset_index()
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
    sfx = "" if LAG_MIN == 10 else f"_s{LAG_MIN}"
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    snaps = snaps.reset_index(drop=True)
    tq_all = us(snaps.captured_at_utc)
    nb = pd.read_parquet(NBR)
    assert (nb.valid_utc < pd.Timestamp("2026-09-30", tz="UTC")).all()
    n = len(snaps)
    feat = {k: np.zeros(n, dtype=float) for k in ("M", "T", "db", "A", "Ac", "nA", "av")}
    feat["ok"] = np.zeros(n, bool)
    tabs, edges, diag = {}, {}, {}
    for st in TZ:
        m = load_station(st)
        nbrs = load_neighbours(st, nb)
        df = history(st, m, nbrs)
        eA, eC = tercile_edges(df, "A"), tercile_edges(df, "Ac")
        df["bA"] = tbin(df.A.to_numpy(), df.hour.to_numpy(), eA)
        df["bC"] = tbin(df.Ac.to_numpy(), df.hour.to_numpy(), eC)
        tabs[st] = {"A": Tables(df, "bA"), "C": Tables(df, "bC")}
        edges[st] = (eA, eC)
        # history diagnostic: mean R by A tercile in 10-16 local
        dd = df[df.hour.between(10, 16)]
        diag[st] = {"neighbours": len(nbrs), "hist_days": int(df.date.nunique()),
                    "hist_A_cov": float(df.A.notna().mean()),
                    "meanR_by_Atercile_10_16": dd[dd.bA >= 0].groupby("bA").R.mean().round(3).to_dict(),
                    "meanR_by_Actercile_10_16": dd[dd.bC >= 0].groupby("bC").R.mean().round(3).to_dict()}
        sel = (snaps.station == st).to_numpy()
        s = state(m, nbrs, tq_all[sel], snaps.date.to_numpy()[sel])
        for k in feat:
            feat[k][sel] = s[k]
        print(st, diag[st], flush=True)
    for k, v in feat.items():
        snaps[k] = v
    snaps["db"] = snaps.db.astype(int)
    okm = snaps.ok.to_numpy()
    assert (feat["av"][okm] <= tq_all[okm]).all(), "PIT violation"
    for _, r in snaps[snaps.ok].sample(3000, random_state=13).iterrows():
        h.assert_point_in_time(EPOCH + pd.Timedelta(microseconds=int(r.av)), r.captured_at_utc)
    hrs = snaps.local_hour.to_numpy()
    bA = np.full(n, -1)
    bC = np.full(n, -1)
    for st in TZ:
        sel = (snaps.station == st).to_numpy()
        bA[sel] = tbin(snaps.A.to_numpy()[sel], hrs[sel], edges[st][0])
        bC[sel] = tbin(snaps.Ac.to_numpy()[sel], hrs[sel], edges[st][1])
    snaps["bA"], snaps["bC"] = bA, bC

    Cb = np.full((n, RMAX + 1), np.nan)
    CA = np.full((n, RMAX + 1), np.nan)
    CC = np.full((n, RMAX + 1), np.nan)
    for i, r in enumerate(snaps.itertuples()):
        if not r.ok:
            continue
        ta = tabs[r.station]["A"]
        base = ta.get(r.local_hour, r.db, None)
        if base is None:
            continue
        Cb[i] = np.cumsum(base)
        if r.bA >= 0:
            pa = ta.get(r.local_hour, r.db, int(r.bA))
            if pa is not None:
                CA[i] = np.cumsum(pa)
        if r.bC >= 0:
            pc = tabs[r.station]["C"].get(r.local_hour, r.db, int(r.bC))
            if pc is not None:
                CC[i] = np.cumsum(pc)
    bands = bands.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    pos = pd.Index(snaps.row_key).get_indexer(bands.row_key)
    assert (pos >= 0).all()
    M = snaps.M.to_numpy()[pos].astype(int)
    kind, lo, hi = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    ps = bands.p_served.to_numpy()
    mb = band_mass(np.nan_to_num(Cb[pos]), M, kind, lo, hi)
    mA = band_mass(np.nan_to_num(CA[pos]), M, kind, lo, hi)
    mC = band_mass(np.nan_to_num(CC[pos]), M, kind, lo, hi)
    covA = ~np.isnan(CA[pos][:, 0])
    covC = ~np.isnan(CC[pos][:, 0])
    out = {}

    def run(name, p, cov):
        c = bands.loc[cov, ["row_key", "band_index"]].assign(p=p[cov])
        tot = c.groupby("row_key").p.transform("sum")
        c = c[tot > 0]
        res = h.score(c, name=name)
        if res.get("leakage_suspect_groups"):
            STOP.write_text(f"t13 leakage tripwire {name}: {res['leakage_suspect_groups']}\n")
            print("LEAKAGE TRIPWIRE", name)
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        out[name] = res
        print(name, json.dumps(res["classes"], default=str)[:1200], flush=True)

    ratioA = np.where(mb > 1e-9, mA / np.maximum(mb, 1e-9), 1.0)
    run(f"t13_r1{sfx}_served_nbr_runmax_tilt", ps * ratioA, covA)
    if LAG_MIN == 10:
        run("t13_r2_nbr_runmax_nowcast", mA, covA)
        run("t13_c1_nonbr_nowcast_control", mb, covA)
        ratioC = np.where(mb > 1e-9, mC / np.maximum(mb, 1e-9), 1.0)
        run("t13_r3_served_nbr_current_tilt", ps * ratioC, covC)
        mg = paired(bands, mA, mb, covA)
        json.dump({"HARNESS_SHA256": h.harness_sha256(), "development": True,
                   "note": "paired r2 - c1 Brier difference on identical covered rows (all-row)",
                   "tables": mg}, open(OUT / "t13_marginal_r2_minus_c1.json", "w"), indent=1)
        print("marginal r2-c1", json.dumps(mg)[:3000])
        cov = {"snapshots": n, "metar_state_ok": int(snaps.ok.sum()),
               "A_ok": int(np.isfinite(snaps.A).sum()), "Ac_ok": int(np.isfinite(snaps.Ac).sum()),
               "covered_r1_snaps": int(snaps.row_key.isin(bands.row_key[covA]).sum()),
               "covered_r3_snaps": int(snaps.row_key.isin(bands.row_key[covC]).sum()),
               "covered_r1_by_block": snaps[snaps.row_key.isin(bands.row_key[covA])].block.value_counts().to_dict(),
               "snaps_by_block": snaps.block.value_counts().to_dict(),
               "bA_live": pd.Series(bA).value_counts().to_dict(),
               "A_mean_by_block": snaps.groupby("block").A.mean().round(3).to_dict()}
        json.dump({"diag": diag, "coverage": cov, "HARNESS_SHA256": h.harness_sha256()},
                  open(OUT / "t13_diag.json", "w"), indent=1, default=str)
        print(json.dumps(cov, default=str))


if __name__ == "__main__":
    main()
