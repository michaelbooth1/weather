"""T16 settlement mechanics vs F2 venue labels (model-parity swarm v2, development only).

Rules t16-r1 / t16-r2 (control) / t16-r3 (diagnostic) are registered in C:\\swarm\\registry.jsonl
(2026-10-04T01:08:16 local). The settled quantity is modelled as F2's RS_ct (routine+SPECI, T-group
tenths C -> hundredths F exactly, round half up), which F2 measured equal to the venue winner band on
626/626 market-days. History labels (truth use only) are RS_ct over local dates <= 2026-07-31.

State at time t uses non-COR METAR/SPECI rows with available = valid + 10 min <= t (rule 1), and
the SAME state function builds the history grid and the live snapshot state (train/serve parity).
New information versus T2: the sub-degree headroom H between the raw (unrounded) T-group running
max and the next half-up rounding boundary.

No market or label column enters a candidate. Run:
  cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t16_settlement_mechanics
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

METAR = Path(r"C:\swarm\data\iem\metar")
LABELS = Path(r"C:\swarm\labels\venue_labels.parquet")
OUT = Path(r"C:\swarm\out\t16")
HIST_END = "2026-07-31"
MIN_DAYS = 40
RMAX = 40
LAG_MIN = int(os.environ.get("T16_LAG_MIN", "10"))
TZ = {"KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
      "KAUS": "America/Chicago", "KDAL": "America/Chicago", "KHOU": "America/Chicago",
      "KORD": "America/Chicago", "KBKF": "America/Denver", "KLAX": "America/Los_Angeles",
      "KSEA": "America/Los_Angeles", "KSFO": "America/Los_Angeles"}
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        raise SystemExit("C:\\swarm\\STOP exists")


def us(x) -> np.ndarray:
    x = pd.to_datetime(pd.Series(x).reset_index(drop=True), utc=True, format="ISO8601")
    return ((x - EPOCH) // pd.Timedelta(microseconds=1)).to_numpy(dtype=np.int64)


def rhu(f100):
    return np.floor((f100 + 50) / 100.0)


def load_station(st):
    """Returns (state_rows, label_by_date). state rows: non-COR; labels: COR kept, MADISHF twins dropped."""
    m = pd.read_parquet(METAR / f"{st}.parquet",
                        columns=["valid_utc", "available_utc", "report_type", "is_cor", "tmpf", "tgroup_c",
                                 "main_temp_c", "metar", "local_date"])
    m["local_date"] = m.local_date.astype(str)
    m = m[m.local_date <= "2026-09-29"].copy()
    m["madis"] = m.metar.str.contains("MADISHF", na=False)
    m = m.sort_values(["valid_utc", "report_type", "madis"]).drop_duplicates(["valid_utc", "report_type"], keep="first")
    tenths = np.round(m.tgroup_c.to_numpy() * 10)
    f100 = tenths * 18 + 3200
    cw100 = m.main_temp_c.to_numpy() * 180 + 3200
    m["f100"] = np.where(np.isfinite(f100), f100, cw100)
    m = m[np.isfinite(m.f100)].copy()
    m["f"] = rhu(m.f100.to_numpy()).astype(int)
    # labels (truth only, includes COR as the venue does)
    lab = m.groupby("local_date").agg(label=("f", "max"), n=("f", "size"))
    # state rows (rule 1: COR excluded, availability valid + LAG)
    s = m[~m.is_cor].copy()
    if LAG_MIN != 10:
        s["available_utc"] = s.valid_utc + pd.Timedelta(minutes=LAG_MIN)
    assert ((s.available_utc - s.valid_utc) >= pd.Timedelta(minutes=10)).all()
    s = s.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").reset_index(drop=True)
    s["cmax100"] = s.groupby("local_date").f100.cummax()
    return s, lab


def dbin(d):
    return np.select([d <= 0, d <= 2, d <= 5], [0, 1, 2], 3)


def sbin(s):
    out = np.select([s <= -2, s <= 1], [0, 1], 2)
    return np.where(np.isnan(s), 3, out)


def hbin(H):
    return np.select([H <= 33, H <= 66], [0, 1], 2)


def state(m, t_utc, dates):
    avail = us(m.available_utc)
    valid = us(m.valid_utc)
    tq = us(t_utc)
    idx = np.searchsorted(avail, tq, side="right") - 1
    ok = idx >= 0
    idc = np.where(ok, idx, 0)
    ok &= m.local_date.to_numpy()[idc] == dates
    c100 = m.cmax100.to_numpy()[idc]
    M = np.where(ok, rhu(c100), -999).astype(int)
    H = np.where(ok, (100 * M + 50) - c100, 0)
    T = np.where(ok, m.f.to_numpy()[idc], -999)
    vlat = valid[idc]
    i2 = np.searchsorted(valid, vlat - 110 * 60 * 1_000_000, side="right") - 1
    i2c = np.where(i2 >= 0, i2, 0)
    gap = vlat - valid[i2c]
    slope = np.where((i2 >= 0) & (gap <= 4 * 3600 * 1_000_000), T - m.f.to_numpy()[i2c], np.nan).astype(float)
    return ok, M, T, dbin(M - T), sbin(slope), hbin(H), H, avail[idc]


def history_table(st, m, lab):
    lab = lab[(lab.index <= HIST_END) & (lab.n >= 18)]
    days = pd.to_datetime(lab.index)
    days = days[days.month.isin([7, 8, 9, 10])]
    recs = []
    for hh in range(24):
        for mm in (0, 15, 30, 45):
            loc = (days + pd.Timedelta(hours=hh, minutes=mm)).tz_localize(TZ[st], nonexistent="shift_forward",
                                                                          ambiguous="NaT")
            keep = ~loc.isna()
            utc = loc[keep].tz_convert("UTC")
            ds = np.array([d.strftime("%Y-%m-%d") for d in days[keep]])
            ok, M, T, db, sb, hb, H, _ = state(m, pd.Series(utc), ds)
            R = lab.label.reindex(ds).to_numpy() - M
            recs.append(pd.DataFrame({"date": ds[ok], "month": days[keep].month[ok], "hour": hh,
                                      "db": db[ok], "sb": sb[ok], "hb": hb[ok], "R": R[ok]}))
    df = pd.concat(recs, ignore_index=True)
    assert (df.date <= HIST_END).all()
    df["R"] = df.R.clip(0, RMAX).astype(int)
    return df


def cell_dists(df):
    out = {}
    for tm, months in ((8, (7, 8, 9)), (9, (8, 9, 10))):
        sub = df[df.month.isin(months)]
        for keys, lvl in ((["hour", "db", "sb", "hb"], 4), (["hour", "db", "sb"], 3), (["hour", "db"], 2),
                          (["hour"], 1)):
            for k, g in sub.groupby(keys):
                k = k if isinstance(k, tuple) else (k,)
                p = np.bincount(g.R.to_numpy(), minlength=RMAX + 1).astype(float)
                out[(tm, lvl) + tuple(int(x) for x in k)] = (p / p.sum(), g.date.nunique())
    return out


def lookup(cd, tm, hour, db, sb, hb, use_hb):
    chain = []
    if use_hb and sb != 3:
        chain.append((4, (tm, 4, hour, db, sb, hb)))
    if sb != 3:
        chain.append((3, (tm, 3, hour, db, sb)))
    chain += [(2, (tm, 2, hour, db)), (1, (tm, 1, hour))]
    for lvl, key in chain:
        v = cd.get(key)
        if v is not None and v[1] >= MIN_DAYS:
            return v[0], lvl
    v = cd.get((tm, 1, hour))
    return (v[0], 1) if v is not None else (None, 0)


def band_probs(pR, M, kinds, lows, highs, shift=0):
    v = M + np.arange(RMAX + 1) + shift
    out = np.zeros(len(kinds))
    for i, (k, lo, hi) in enumerate(zip(kinds, lows, highs)):
        sel = (v >= lo) & (v <= hi) if k == "eq" else (v <= lo if k == "lte" else v >= lo)
        out[i] = pR[sel].sum()
    return out


def main():
    stop_check()
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    stations, tables, diag = {}, {}, {}
    for st in TZ:
        s, lab = load_station(st)
        stations[st] = s
        df = history_table(st, s, lab)
        tables[st] = cell_dists(df)
        diag[st] = {"hist_days": int(df.date.nunique()), "hist_first": df.date.min(), "hist_last": df.date.max()}
    stop_check()
    snaps = snaps.copy()
    snaps["tmonth"] = snaps.date.str[5:7].astype(int)
    feats = []
    for st, g in snaps.groupby("station"):
        ok, M, T, db, sb, hb, H, av = state(stations[st], g.captured_at_utc, g.date.to_numpy())
        cap = us(g.captured_at_utc)
        assert (av[ok] <= cap[ok]).all()
        feats.append(pd.DataFrame({"ok": ok, "M": M, "db": db, "sb": sb, "hb": hb, "H": H, "av": av}, index=g.index))
    snaps = snaps.join(pd.concat(feats))
    for _, r in snaps[snaps.ok].sample(2000, random_state=16).iterrows():
        h.assert_point_in_time(EPOCH + pd.Timedelta(microseconds=int(r.av)), r.captured_at_utc)

    b = bands.merge(snaps[["row_key", "station", "tmonth", "local_hour", "ok", "M", "db", "sb", "hb"]], on="row_key")
    b = b.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    p1, p2, p3 = (np.full(len(b), np.nan) for _ in range(3))
    lv1, lv2 = {}, {}
    starts = np.flatnonzero(np.r_[True, b.row_key.to_numpy()[1:] != b.row_key.to_numpy()[:-1]])
    ends = np.r_[starts[1:], len(b)]
    kinds, lows, highs = b.kind.to_numpy(), b.low.to_numpy(), b.high.to_numpy()
    okv, stv, tmv, hrv = b.ok.to_numpy(), b.station.to_numpy(), b.tmonth.to_numpy(), b.local_hour.to_numpy()
    Mv, dbv, sbv, hbv = b.M.to_numpy(), b.db.to_numpy(), b.sb.to_numpy(), b.hb.to_numpy()
    for a, e in zip(starts, ends):
        if not okv[a]:
            continue
        args = (tables[stv[a]], int(tmv[a]), int(hrv[a]), int(dbv[a]), int(sbv[a]), int(hbv[a]))
        pa, la = lookup(*args, use_hb=True)
        pb, lb = lookup(*args, use_hb=False)
        lv1[la] = lv1.get(la, 0) + 1
        lv2[lb] = lv2.get(lb, 0) + 1
        if pa is None:
            continue
        sl = slice(a, e)
        p1[sl] = band_probs(pa, int(Mv[a]), kinds[sl], lows[sl], highs[sl])
        p2[sl] = band_probs(pb, int(Mv[a]), kinds[sl], lows[sl], highs[sl])
        p3[sl] = band_probs(pa, int(Mv[a]), kinds[sl], lows[sl], highs[sl], shift=1)
    stop_check()
    results = {}
    variants = (("t16_r1_headroom", p1), ("t16_r2_control_noheadroom", p2), ("t16_r3_diag_truemax_shift", p3))
    if LAG_MIN != 10:
        variants = ((f"t16_r1s{LAG_MIN}_headroom_lag{LAG_MIN}", p1),)
    for name, p in variants:
        cov = ~np.isnan(p)
        c = b.loc[cov, ["row_key", "band_index"]].assign(p=p[cov])
        c = c[c.groupby("row_key").p.transform("sum") > 0]
        res = h.score(c, name=name)
        h.save(res, OUT)
        results[name] = res
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        print(h.markdown(res))
    # headroom diagnostics on the live table (state only; no label)
    hd = snaps[snaps.ok].groupby("hb").size().to_dict()
    json.dump({"diag": diag, "levels_r1": {str(k): v for k, v in lv1.items()},
               "levels_r2": {str(k): v for k, v in lv2.items()}, "live_hb_counts": {str(k): int(v) for k, v in hd.items()},
               "covered_snapshots": int(snaps.ok.sum()), "total_snapshots": int(len(snaps)), "lag_min": LAG_MIN,
               "HARNESS_SHA256": h.harness_sha256()},
              open(OUT / f"t16_diag_lag{LAG_MIN}.json", "w"), indent=1, default=str)
    # keep per-band candidate vectors for the paired r1-r2 contrast
    np.savez_compressed(OUT / f"t16_probs_lag{LAG_MIN}.npz", row_key=b.row_key.to_numpy().astype(str),
                        band_index=b.band_index.to_numpy(), p1=p1, p2=p2, p3=p3)
    print(json.dumps({"HARNESS_SHA256": h.harness_sha256(), "lv1": lv1, "lv2": lv2}))


if __name__ == "__main__":
    main()
