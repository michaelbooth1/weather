"""T21: independent re-implementation of T6 (NBS latest cycle) from the registered rule text only.

Registered rules re-implemented (no new rules): t6-r1, t6-r2, t6-r3, t6-d1, t6-c1, t6-c2
(C:\\swarm\\registry.jsonl, 2026-10-04 01:12:20 / 01:25:53). Written WITHOUT reading T6's code.
Development only. Run from C:\\pt\\swarm with the repo interpreter:
    python -m tools.research.model_parity.t21_t6_reimpl
"""
from __future__ import annotations

import bisect
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.special import ndtr

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t21")
NBS_S3 = Path(r"C:\swarm\data\nbs\nbs_tidy.parquet")
NBS_IEM = Path(r"C:\swarm\data\iem\mos\mos_NBS.parquet")
METAR_DIR = Path(r"C:\swarm\data\iem\metar")
TZ = {"atlanta": "America/New_York", "miami": "America/New_York", "nyc": "America/New_York",
      "chicago": "America/Chicago", "austin": "America/Chicago", "dallas": "America/Chicago",
      "houston": "America/Chicago", "denver": "America/Denver", "los-angeles": "America/Los_Angeles",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
UTC = timezone.utc
HIST_START, HIST_END = date(2026, 5, 1), date(2026, 7, 31)


def stop_check():
    if Path(r"C:\swarm\STOP").exists():
        raise SystemExit("C:\\swarm\\STOP exists")


# ----------------------------------------------------------------------------- cycle store

class Store:
    """Per-station NBS cycles with point-in-time lookups (availability = S3 LastModified + lag)."""

    def __init__(self, df, lag_minutes=0):
        # df columns: station, cycle_utc, available_utc, field, valid_utc, value (TXN/XND/TMP/TSD)
        lag = pd.Timedelta(minutes=lag_minutes)
        df = df[df.available_utc.notna()].copy()
        df["avail"] = df.available_utc + lag
        self.st = {}
        for station, g in df.groupby("station"):
            cyc = g.groupby("cycle_utc").avail.min().sort_values()
            # latest cycle_utc among cycles with avail <= t
            av = tx_k(cyc)
            cy = [pd.Timestamp(x).to_pydatetime() for x in cyc.index]
            cmax, best = [], None
            for c in cy:
                best = c if best is None or c > best else best
                cmax.append(best)
            # TXN rows valid at 00Z (daytime max), keyed (cycle, valid)
            tx = g[(g.field == "TXN") & (g.valid_utc.dt.hour == 0)]
            xn = g[(g.field == "XND") & (g.valid_utc.dt.hour == 0)]
            xnd = {(a, b): v for a, b, v in zip(tx_k(xn.cycle_utc), tx_k(xn.valid_utc), xn.value)}
            txn = {}
            by_valid = defaultdict(list)
            for c, v, val, a in zip(tx_k(tx.cycle_utc), tx_k(tx.valid_utc), tx.value, tx_k(tx.avail)):
                txn[(c, v)] = (float(val), float(xnd.get((c, v), np.nan)))
                by_valid[v].append((a, c))
            txn_valid = {v: _cummax_index(lst) for v, lst in by_valid.items()}
            tm = g[g.field == "TMP"]
            ts = g[g.field == "TSD"]
            tsd = {(a, b): v for a, b, v in zip(tx_k(ts.cycle_utc), tx_k(ts.valid_utc), ts.value)}
            tmp_valid = defaultdict(list)
            tmpv = {}
            for c, v, val, a in zip(tx_k(tm.cycle_utc), tx_k(tm.valid_utc), tm.value, tx_k(tm.avail)):
                tmpv[(c, v)] = (float(val), float(tsd.get((c, v), np.nan)))
                tmp_valid[v].append((a, c))
            tmp_valid = {v: _cummax_index(lst) for v, lst in tmp_valid.items()}
            self.st[station] = dict(av=av, cmax=cmax, txn=txn, txn_valid=txn_valid,
                                    tmpv=tmpv, tmp_valid=tmp_valid, cycles=set(cy))

    def latest(self, station, t):
        s = self.st.get(station)
        if s is None:
            return None
        i = bisect.bisect_right(s["av"], t)
        return s["cmax"][i - 1] if i else None

    @staticmethod
    def _lookup(index, t):
        if index is None:
            return None
        av, cm = index
        i = bisect.bisect_right(av, t)
        return cm[i - 1] if i else None

    def select(self, station, t, d_local, end_utc):
        """Returns dict(mode, mu, sigma, cycle, r1=(mu, sigma)|None)."""
        s = self.st.get(station)
        out = {"mode": "ABSENT", "r1": None}
        if s is None:
            return out
        v00 = datetime(d_local.year, d_local.month, d_local.day, tzinfo=UTC) + timedelta(days=1)
        c1 = self._lookup(s["txn_valid"].get(v00), t)
        if c1 is not None:
            txn, xnd = s["txn"][(c1, v00)]
            out["r1"] = (txn, xnd, c1)
        c = self.latest(station, t)
        if c is None:
            return out
        out["cycle"] = c
        if (c, v00) in s["txn"]:
            txn, xnd = s["txn"][(c, v00)]
            out.update(mode="TXN", mu=txn, sig_raw=xnd)
            return out
        # REM: 3-hourly valid times v in (t, end_utc]
        v = datetime(t.year, t.month, t.day, tzinfo=UTC)
        v = v + timedelta(hours=3 * (t.hour // 3))
        while v <= t:
            v += timedelta(hours=3)
        vals = []
        n_v = 0
        while v <= end_utc:
            n_v += 1
            cc = self._lookup(s["tmp_valid"].get(v), t)
            if cc is not None:
                vals.append((s["tmpv"][(cc, v)], v))
            v += timedelta(hours=3)
        if n_v == 0:
            out.update(mode="REM0")
            return out
        if not vals:
            out.update(mode="REM_NODATA")
            return out
        best = max(vals, key=lambda x: (x[0][0], -x[1].timestamp()))  # max TMP, earliest on ties
        out.update(mode="REM", mu=best[0][0], sig_raw=best[0][1])
        return out


def tx_k(series):
    return [pd.Timestamp(x).to_pydatetime() for x in series]


def _cummax_index(lst):
    lst.sort()
    av, cm, best = [], [], None
    for a, c in lst:
        best = c if best is None or c > best else best
        av.append(a)
        cm.append(best)
    return av, cm


# ----------------------------------------------------------------------------- loaders

def load_s3_nbs():
    d = pd.read_parquet(NBS_S3, columns=["station", "field", "value", "cycle_utc", "valid_utc",
                                         "available_utc"])
    return d[d.field.isin(["TXN", "XND", "TMP", "TSD"])].reset_index(drop=True)


def load_iem_nbs():
    n = pd.read_parquet(NBS_IEM, columns=["station", "runtime", "ftime", "tmp", "tsd", "txn", "xnd",
                                          "available_utc"])
    n = n.rename(columns={"runtime": "cycle_utc", "ftime": "valid_utc"})
    parts = []
    for f, col in (("TMP", "tmp"), ("TSD", "tsd"), ("TXN", "txn"), ("XND", "xnd")):
        x = n[["station", "cycle_utc", "valid_utc", "available_utc", col]].dropna(subset=[col])
        parts.append(x.rename(columns={col: "value"}).assign(field=f))
    return pd.concat(parts, ignore_index=True)


def load_metar(station):
    m = pd.read_parquet(METAR_DIR / f"{station}.parquet",
                        columns=["tmpf", "report_type", "valid_utc", "is_cor", "metar"])
    m = m[(~m.is_cor) & m.tmpf.notna() & m.report_type.isin(["routine", "speci"])]
    m = m[~m.metar.fillna("").str.contains(" COR ")]
    m = m.assign(t=np.floor(m.tmpf.to_numpy() + 0.5))
    return m.sort_values("valid_utc")


# ----------------------------------------------------------------------------- distribution

def band_probs(kinds, lows, highs, B, mu, sigma):
    """P(H in band), H = max(B, X), X ~ N(mu, sigma) integer-discretised. mu=None: X=-inf."""
    def cdf(x):  # P(H <= x), x integer array
        x = np.asarray(x, float)
        if mu is None:
            return (x >= B).astype(float)
        return np.where(x < B, 0.0, ndtr((x + 0.5 - mu) / sigma))
    out = np.empty(len(kinds))
    for i, (k, lo, hi) in enumerate(zip(kinds, lows, highs)):
        if k == "lte":
            out[i] = cdf(hi)
        elif k == "gte":
            out[i] = 1.0 - cdf(lo - 1)
        else:
            out[i] = cdf(hi) - cdf(lo - 1)
    return np.clip(out, 0.0, None)


# ----------------------------------------------------------------------------- selection pass

def snapshot_frame():
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    assert set(snaps.unit.dropna().unique()) <= {"F"}, snaps.unit.unique()
    t = pd.to_datetime(snaps.captured_at_utc, utc=True)
    snaps = snaps.assign(t=[x.to_pydatetime() for x in t])
    return snaps, bands


def end_of_local_day(d_local, market):
    tz = ZoneInfo(TZ[market])
    return datetime.combine(d_local + timedelta(days=1), datetime.min.time(), tz).astimezone(UTC)


def select_all(snaps, store):
    rows = []
    for st, mk, ds, t in zip(snaps.station, snaps.market, snaps.date, snaps.t):
        d_local = date.fromisoformat(str(ds)[:10])
        sel = store.select(st, t, d_local, end_of_local_day(d_local, mk))
        if "cycle" in sel:
            # rule 1 assertion on the chosen cycle's availability
            pass
        rows.append(sel)
    return rows


def build(snaps, bands, sels, which, bs=None, v2=None):
    """which in r1, r2, r3, c1, c2. Returns candidate frame and mode counts."""
    off = np.concatenate([[0], np.cumsum(snaps.n_bands.to_numpy())[:-1]])
    kinds, lows, highs = bands.kind.to_numpy(), bands.low.to_numpy(), bands.high.to_numpy()
    floor = snaps.floor.to_numpy(float)
    keys, idx, ps = [], [], []
    modes = defaultdict(int)
    for i, sel in enumerate(sels):
        if not np.isfinite(floor[i]):
            modes["no_floor"] += 1
            continue
        B = math.floor(floor[i] + 0.5)
        mode = sel["mode"]
        mu = sig = None
        if which == "r1":
            if sel["r1"] is None:
                modes["absent"] += 1
                continue
            mu, sig = sel["r1"][0], max(sel["r1"][1], 1.0)
            mode = "TXN"
        else:
            if mode in ("ABSENT", "REM_NODATA"):
                modes[mode] += 1
                continue
            if mode == "TXN":
                if which == "c1":
                    modes["TXN_fallback"] += 1
                    continue
                if which == "c2":
                    m, s, ok = v2[i]
                    if not ok:
                        modes["TXN_no_v2"] += 1
                        continue
                    mu, sig = m, max(s, 1.0)
                else:
                    mu, sig = sel["mu"], max(sel["sig_raw"], 1.0)
            elif mode == "REM":
                if which == "c1":
                    mu = None
                else:
                    mu, sig = sel["mu"], max(sel["sig_raw"], 1.0)
            # REM0 -> mu None
            if which == "r3" and mu is not None:
                b, s = bs[mode]
                mu, sig = mu + b, max(s * sig, 1.0)
        a, n = off[i], snaps.n_bands.iat[i]
        p = band_probs(kinds[a:a + n], lows[a:a + n], highs[a:a + n], B, mu, sig)
        keys.extend([snaps.row_key.iat[i]] * n)
        idx.extend(range(n))
        ps.extend(p.tolist())
        modes[mode] += 1
    cand = pd.DataFrame({"row_key": keys, "band_index": idx, "p": ps})
    return cand, dict(modes)


# ----------------------------------------------------------------------------- r3 history fit

def fit_history(lag_minutes=0):
    iem = load_iem_nbs()
    iem = iem[(iem.cycle_utc.dt.date >= HIST_START - timedelta(days=3)) & (iem.cycle_utc.dt.date <= HIST_END)
              & iem.cycle_utc.dt.hour.isin([0, 6, 12, 18])]  # rule text: IEM NBS 00/06/12/18Z
    s3 = load_s3_nbs()
    s3 = s3[s3.cycle_utc.dt.date <= HIST_END]
    # S3 parts take precedence where the same cycle exists in both
    s3_cycles = set(zip(s3.station, s3.cycle_utc))
    iem = iem[[(a, b) not in s3_cycles for a, b in zip(iem.station, iem.cycle_utc)]]
    n_iem_no_avail = int(iem.available_utc.isna().groupby([iem.station, iem.cycle_utc]).any().sum())
    store = Store(pd.concat([iem, s3], ignore_index=True), lag_minutes)
    stations = {"KATL": "atlanta", "KMIA": "miami", "KLGA": "nyc", "KORD": "chicago", "KAUS": "austin",
                "KDAL": "dallas", "KHOU": "houston", "KBKF": "denver", "KLAX": "los-angeles",
                "KSFO": "san-francisco", "KSEA": "seattle"}
    res = {"TXN": [], "REM": []}
    for st, mk in stations.items():
        m = load_metar(st)
        tz = ZoneInfo(TZ[mk])
        vt = [x.to_pydatetime() for x in m.valid_utc]
        tv = m.t.to_numpy()
        d = HIST_START
        while d <= HIST_END:
            start = datetime.combine(d, datetime.min.time(), tz).astimezone(UTC)
            end = end_of_local_day(d, mk)
            i0, i1 = bisect.bisect_right(vt, start - timedelta(microseconds=1)), bisect.bisect_right(vt, end)
            # local day D rows: valid in [start, end)
            i1_excl = bisect.bisect_left(vt, end)
            if i1_excl > i0:
                daymax = float(tv[i0:i1_excl].max())
                for hr in range(24):
                    t = (datetime(d.year, d.month, d.day, hr, tzinfo=tz)).astimezone(UTC)
                    sel = store.select(st, t, d, end)
                    if sel["mode"] == "TXN":
                        res["TXN"].append((daymax - sel["mu"], max(sel["sig_raw"], 1.0)))
                    elif sel["mode"] == "REM":
                        j0 = bisect.bisect_right(vt, t)
                        if i1 > j0:
                            rem = float(tv[j0:i1].max())
                            res["REM"].append((rem - sel["mu"], max(sel["sig_raw"], 1.0)))
            d += timedelta(days=1)
    bs, info = {}, {"iem_cycles_without_availability_excluded": n_iem_no_avail}
    for mode, lst in res.items():
        r = np.array([x[0] for x in lst])
        s = np.array([x[1] for x in lst])
        b = float(np.median(r))
        sc = float(np.sqrt(np.mean(((r - b) / s) ** 2)))
        bs[mode] = (b, sc)
        info[mode] = {"b": b, "s": sc, "n": int(len(r))}
    return bs, info


# ----------------------------------------------------------------------------- paired helper

def paired(cand_a, cand_b, groups=("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"),
           strata=("from_20260823", "before_20260823")):
    d = h.data()
    pa, _, _ = h._candidate_vector(cand_a, d, False)
    pb, _, _ = h._candidate_vector(cand_b, d, False)
    sa = h._snapshot_mean(d, (pa - d.y) ** 2)
    sb = h._snapshot_mean(d, (pb - d.y) ** 2)
    fr = d.snaps[["date", "market", "stratum", "local_hour"]].assign(delta=sa - sb)
    out = {}
    for g in groups:
        gm = h._group_mask(fr, g)
        for s in strata:
            sub = fr[gm & (fr.stratum == s).to_numpy()]
            cells = sub.groupby(["date", "market"], sort=True).delta.mean().reset_index()
            idx = np.array([d.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
            iv = h.interval(idx, cells.delta.to_numpy())
            pm = cells.groupby("market").delta.mean()
            out[f"{g}|{s}"] = {"estimate": iv["estimate"], "ci95": iv["ci95"],
                               "markets_neg": int((pm < 0).sum()), "markets_pos": int((pm > 0).sum())}
    return out


# ----------------------------------------------------------------------------- main

def pit_check(snaps, sels, store_lagless):
    """Full rule-1 re-check: every chosen cycle's availability <= captured_at_utc."""
    n = 0
    for st, t, sel in zip(snaps.station, snaps.t, sels):
        for c in ([sel["cycle"]] if "cycle" in sel else []) + ([sel["r1"][2]] if sel["r1"] else []):
            s = store_lagless.st[st]
            # availability of cycle c
            av = s["cycle_avail"][c]
            h.assert_point_in_time(av, t)
            n += 1
    return n


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    stop_check()
    snaps, bands = snapshot_frame()
    s3 = load_s3_nbs()
    assert s3.cycle_utc.max() < pd.Timestamp("2026-09-30", tz="UTC")
    results = {"HARNESS_SHA256": h.harness_sha256(), "development": True}
    stores = {0: Store(s3, 0), 60: Store(s3, 60)}
    # cycle availability map for the PIT re-check
    cav = s3.groupby(["station", "cycle_utc"]).available_utc.min()
    for st in stores[0].st:
        stores[0].st[st]["cycle_avail"] = {k[1].to_pydatetime(): v.to_pydatetime()
                                           for k, v in cav.items() if k[0] == st}
    sels = select_all(snaps, stores[0])
    results["pit_assert_count"] = pit_check(snaps, sels, stores[0])
    sels60 = select_all(snaps, stores[60])
    print("selection done", round(time.time() - t0, 1), flush=True)

    stop_check()
    bs, fitinfo = fit_history(0)
    results["r3_fit"] = fitinfo
    print("fit", fitinfo, flush=True)

    # c2: captured v2 values, PIT asserted
    v2 = []
    for m, s, av, t in zip(snaps.v2_mean, snaps.v2_stddev, snaps.v2_available_at, snaps.t):
        ok = m is not None and not pd.isna(m) and s is not None and not pd.isna(s) and av is not None \
            and not pd.isna(av)
        if ok:
            avt = pd.Timestamp(av).to_pydatetime()
            ok = avt <= t
            if ok:
                h.assert_point_in_time(avt, t)
        v2.append((float(m) if ok else None, float(s) if ok else None, ok))

    cands = {}
    specs = [("t21_r1", "r1", sels, None), ("t21_r2", "r2", sels, None), ("t21_r3", "r3", sels, bs),
             ("t21_d1_r2_lag60", "r2", sels60, None), ("t21_d1_r3_lag60", "r3", sels60, bs),
             ("t21_c1", "c1", sels, None), ("t21_c2", "c2", sels, None)]
    summary = {}
    for name, which, sl, b in specs:
        stop_check()
        cand, modes = build(snaps, bands, sl, which, bs=b, v2=v2)
        cands[name] = cand
        res = h.score(cand, name=name)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res.get("leakage_suspect_groups"):
            Path(r"C:\swarm\STOP").write_text(f"t21: leakage suspect {name} {res['leakage_suspect_groups']}\n")
            raise SystemExit("leakage suspect")
        h.save(res, OUT)
        (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
        row = {"modes": modes, "reason_counts": res["reason_counts"], "classes": {}, "from": {}, "before": {}}
        for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"):
            row["classes"][g] = res["classes"][g]["class"]
            for sk, s in (("from", "from_20260823"), ("before", "before_20260823")):
                t = h.table_lookup(res, g, s, "all_row")
                row[sk][g] = {"delta": t["candidate_minus_served"]["estimate"],
                              "ci95": t["candidate_minus_served"]["ci95"],
                              "cand_minus_market": t["candidate_minus_market"]["estimate"],
                              "cmm_ci95": t["candidate_minus_market"]["ci95"],
                              "gap_closed": t["gap_closed_share"]["estimate"],
                              "neg": t["markets_negative"], "pos": t["markets_positive"]}
        row["tail"] = {k: v for k, v in res["tail"].items()} if isinstance(res["tail"], dict) else res["tail"]
        summary[name] = row
        print(name, modes, {g: (round(row["from"][g]["delta"], 4), row["classes"][g]) for g in row["from"]},
              flush=True)
    results["candidates"] = summary
    stop_check()
    results["paired"] = {
        "r2_minus_c1": paired(cands["t21_r2"], cands["t21_c1"]),
        "r2_minus_c2": paired(cands["t21_r2"], cands["t21_c2"]),
        "r3_minus_r2": paired(cands["t21_r3"], cands["t21_r2"]),
    }
    results["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "t21_run.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("done", results["runtime_s"])


if __name__ == "__main__":
    main()
