"""T3 baselines board (model-parity swarm v2, development only).

Three registered ladder rungs, all built from PIT METAR (IEM asos.py, A-IEM-1 manifest) and history
local dates <= 2026-07-31 only. No market input, no label input; the harness applies the rule-4 floor.

  t3-r1 climatology     : station x target-month distribution of the daily hourly-row max (history).
  t3-r2 persistence     : yesterday's PIT hourly-row max +/- station-month day-to-day spread (history).
  t3-r3 floor+rise      : PIT running hourly-row max today + station x month x local-hour remaining-rise
                          distribution (history).

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.t3_baselines
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

OUT = Path(r"C:\swarm\out\t3")
METAR = Path(r"C:\swarm\data\iem\metar")
REGISTRY = Path(r"C:\swarm\registry.jsonl")
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text(encoding="utf-8"))["stations"]
HIST_END = "2026-07-31"
MIN_ROUTINE = 20          # a complete day needs >= 20 routine rows (fixed a priori)
KERNEL_SD = 1.0           # integer smoothing kernel, deg F (fixed a priori)
HIST_CUTOFF_MIN = 30      # history running max taken at local H:30 (fixed a priori)

RULE_IDS = ["t3-r1", "t3-r2", "t3-r3"]


def registered():
    rows = [json.loads(x) for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    reg = {r["id"]: r for r in rows if r.get("agent") == "t3"}
    for rid in RULE_IDS:
        r = reg[rid]
        assert hashlib.sha256(r["text"].encode("utf-8")).hexdigest() == r["sha256"], rid
    return reg


def half_up(x):
    return np.floor(np.asarray(x, float) + 0.5)


def load_metar(extra_lag_min=0):
    frames = []
    for st in STATIONS:
        m = pd.read_parquet(METAR / f"{st}.parquet")
        m = m[(m.report_type == "routine") & (~m.is_cor)].copy()
        tf = np.where(m.tgroup_c.notna(), m.tgroup_c * 1.8 + 32, m.main_temp_c * 1.8 + 32)
        m["temp_f"] = half_up(tf)
        m = m[np.isfinite(m.temp_f)]
        m["available_utc"] = m.available_utc + pd.Timedelta(minutes=extra_lag_min)
        m["local_date"] = m.local_date.astype(str)
        assert (m.local_date <= "2026-09-29").all()
        frames.append(m[["station", "valid_utc", "available_utc", "local_date", "temp_f"]])
    return pd.concat(frames, ignore_index=True)


def daily(m):
    d = m.groupby(["station", "local_date"]).agg(dmax=("temp_f", "max"), n=("temp_f", "size")).reset_index()
    d = d[d.n >= MIN_ROUTINE]
    d["month"] = d.local_date.str[5:7].astype(int)
    return d


def disc_gauss(sd, half=6):
    k = np.arange(-half, half + 1)
    w = np.exp(-0.5 * (k / sd) ** 2)
    return k, w / w.sum()


def smooth_pmf(values, sd=KERNEL_SD):
    """Empirical integer pmf convolved with a discrete Gaussian. Returns (base, probs)."""
    v = np.asarray(values, int)
    lo, hi = v.min(), v.max()
    counts = np.bincount(v - lo, minlength=hi - lo + 1).astype(float)
    k, w = disc_gauss(sd)
    p = np.convolve(counts, w)
    return lo + k[0], p / p.sum()


def normal_pmf(center, sd, half=25):
    from math import erf
    ks = np.arange(-half, half + 1)
    cdf = lambda x: 0.5 * (1 + np.vectorize(erf)(x / (sd * math.sqrt(2))))
    p = cdf(ks + 0.5) - cdf(ks - 0.5)
    return int(center) - half, p / p.sum()


def band_probs(base, pmf, bands_rows):
    """bands_rows: arrays kind, low, high for one snapshot."""
    cum = np.concatenate([[0.0], np.cumsum(pmf)])
    n = len(pmf)
    def mass(a, b):  # inclusive integer range [a, b]
        i = int(np.clip(a - base, 0, n)); j = int(np.clip(b - base + 1, 0, n))
        return max(cum[j] - cum[i], 0.0)
    out = []
    for kind, lo, hi in bands_rows:
        if kind == "lte":
            out.append(mass(-10**6, hi))
        elif kind == "gte":
            out.append(mass(lo, 10**6))
        else:
            out.append(mass(lo, hi))
    return np.array(out)


def pit_asof(snaps, m, which):
    """Running max / count of routine rows of local date (target or target-1) available <= t."""
    s = snaps[["row_key", "station", "date", "captured_at_utc"]].copy()
    s["t"] = pd.to_datetime(s.captured_at_utc, utc=True).astype("datetime64[us, UTC]")
    if which == "yday":
        s["qdate"] = (pd.to_datetime(s.date) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    else:
        s["qdate"] = s.date
    mm = m[m.local_date >= "2026-07-25"].sort_values(["station", "local_date", "available_utc"]).copy()
    mm["cummax"] = mm.groupby(["station", "local_date"]).temp_f.cummax()
    mm["cumn"] = mm.groupby(["station", "local_date"]).cumcount() + 1
    mm["key"] = mm.station + "|" + mm.local_date
    s["key"] = s.station + "|" + s.qdate
    s = s.sort_values("t")
    mm = mm.sort_values("available_utc")
    j = pd.merge_asof(s, mm[["key", "available_utc", "cummax", "cumn"]], left_on="t",
                      right_on="available_utc", by="key", direction="backward")
    ok = j.available_utc.notna()
    h.assert_point_in_time(j.available_utc[ok], j.t[ok])      # rule 1
    return j.set_index("row_key")[["cummax", "cumn", "available_utc"]]


def remaining_rise_table(m, d):
    """History (<= HIST_END) remaining rise E = dmax - runmax(rows available <= local H:30)."""
    hist = m[m.local_date <= HIST_END]
    full = d[d.local_date <= HIST_END].set_index(["station", "local_date"])
    rows = []
    for (st, ld), g in hist.groupby(["station", "local_date"]):
        if (st, ld) not in full.index:
            continue
        tz = ZoneInfo(STATIONS[st]["tzname"])
        dmax = full.loc[(st, ld), "dmax"]
        y, mo, dd = map(int, ld.split("-"))
        av = g.available_utc.dt.tz_convert(None).to_numpy().astype("datetime64[us]")
        tf = g.temp_f.to_numpy()
        for H in range(24):
            cut = datetime(y, mo, dd, H, HIST_CUTOFF_MIN, tzinfo=tz).astimezone(ZoneInfo("UTC"))
            sel = av <= np.datetime64(cut.replace(tzinfo=None), "us")
            if sel.any():
                rows.append((st, mo, H, int(dmax - tf[sel].max())))
    return pd.DataFrame(rows, columns=["station", "month", "hour", "rise"])


def build(extra_lag_min=0):
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    m = load_metar(extra_lag_min)
    d = daily(m)
    hist = d[d.local_date <= HIST_END]
    snaps = snaps.copy()
    snaps["month"] = snaps.date.str[5:7].astype(int)

    # r1 climatology pmfs
    clim = {(st, mo): smooth_pmf(g.dmax.to_numpy()) for (st, mo), g in hist.groupby(["station", "month"])}
    clim_n = {f"{st}-{mo}": int(len(g)) for (st, mo), g in hist.groupby(["station", "month"])}

    # r2 persistence spread: sd of dmax(d) - dmax(d-1), history, station x month of d
    hd = hist.copy()
    hd["prev"] = (pd.to_datetime(hd.local_date) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    pairs = hd.merge(hist[["station", "local_date", "dmax"]].rename(columns={"local_date": "prev", "dmax": "pmax"}),
                     on=["station", "prev"])
    pairs["dd"] = pairs.dmax - pairs.pmax
    spread = {(st, mo): float(g.dd.std(ddof=1)) for (st, mo), g in pairs.groupby(["station", "month"])}
    spread_n = {f"{st}-{mo}": int(len(g)) for (st, mo), g in pairs.groupby(["station", "month"])}

    # r3 remaining-rise pmfs
    rr = remaining_rise_table(m, d)
    rise = {}
    for (st, mo, H), g in rr.groupby(["station", "month", "hour"]):
        base, p = smooth_pmf(g.rise.to_numpy())
        # fold negative rise onto 0 (rise >= 0 by construction)
        vals = base + np.arange(len(p))
        neg = vals < 0
        p0 = p[neg].sum()
        p = p[~neg]; base = max(base, 0)
        p[0] += p0
        rise[(st, mo, H)] = (base, p, len(g))

    yday = pit_asof(snaps, m, "yday")
    today = pit_asof(snaps, m, "today")

    bkind = bands.kind.to_numpy(); blo = bands.low.to_numpy(); bhi = bands.high.to_numpy()
    starts = np.r_[0, np.flatnonzero(bands.row_key.to_numpy()[1:] != bands.row_key.to_numpy()[:-1]) + 1]
    keys = bands.row_key.to_numpy()[starts]
    ends = np.r_[starts[1:], len(bands)]
    sidx = snaps.set_index("row_key")

    out = {r: [] for r in RULE_IDS}
    cov = {r: {"covered": 0, "absent": 0} for r in RULE_IDS}
    for k, a, b in zip(keys, starts, ends):
        sn = sidx.loc[k]
        st, mo, H = sn.station, int(sn.month), int(sn.local_hour)
        br = list(zip(bkind[a:b], blo[a:b], bhi[a:b]))
        # r1
        base, p = clim[(st, mo)]
        out["t3-r1"].append(band_probs(base, p, br)); cov["t3-r1"]["covered"] += 1
        # r2
        y = yday.loc[k]
        if pd.notna(y["cummax"]) and y["cumn"] >= MIN_ROUTINE:
            base, p = normal_pmf(y["cummax"], spread[(st, mo)])
            out["t3-r2"].append(band_probs(base, p, br)); cov["t3-r2"]["covered"] += 1
        else:
            out["t3-r2"].append(None); cov["t3-r2"]["absent"] += 1
        # r3
        t = today.loc[k]
        if pd.notna(t["cummax"]) and (st, mo, H) in rise:
            rb, rp, _ = rise[(st, mo, H)]
            out["t3-r3"].append(band_probs(int(t["cummax"]) + rb, rp, br)); cov["t3-r3"]["covered"] += 1
        else:
            out["t3-r3"].append(None); cov["t3-r3"]["absent"] += 1

    cands = {}
    for r in RULE_IDS:
        rk, bi, pp = [], [], []
        for k, a, b, v in zip(keys, starts, ends, out[r]):
            if v is None:
                continue
            rk.extend([k] * (b - a)); bi.extend(range(b - a)); pp.extend(v.tolist())
        cands[r] = pd.DataFrame({"row_key": rk, "band_index": bi, "p": pp})
    meta = {"clim_n_days": clim_n, "persistence_sd": {f"{a}-{b}": v for (a, b), v in spread.items()},
            "persistence_pairs": spread_n,
            "rise_cells": len(rise), "rise_min_n": int(min(v[2] for v in rise.values())),
            "coverage": cov, "metar_rows_routine_noncor": int(len(m))}
    return cands, meta


def main_sensitivity():
    reg = registered()
    assert "t3-r3s" in reg or json.loads  # registered before scoring (checked below)
    rows = [json.loads(x) for x in REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(r["id"] == "t3-r3s" and r["agent"] == "t3" for r in rows)
    cands, meta = build(extra_lag_min=60)
    res = h.score(cands["t3-r3"], name="t3_r3s_floor_plus_rise_lag60")
    assert res["rows_with_target_after_2026_09_29"] == 0
    h.save(res, OUT)
    (OUT / "t3_r3s_floor_plus_rise_lag60.md").write_text(h.markdown(res), encoding="utf-8")
    (OUT / "meta_lag60.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(h.markdown(res))


def main():
    reg = registered()
    OUT.mkdir(parents=True, exist_ok=True)
    cands, meta = build()
    results = {}
    names = {"t3-r1": "t3_r1_climatology", "t3-r2": "t3_r2_persistence", "t3-r3": "t3_r3_floor_plus_rise"}
    for r in RULE_IDS:
        res = h.score(cands[r], name=names[r])
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            print("LEAKAGE SUSPECT", r, res["leakage_suspect_groups"])
        h.save(res, OUT)
        (OUT / f"{names[r]}.md").write_text(h.markdown(res), encoding="utf-8")
        results[r] = res
        print(h.markdown(res))
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta)[:2000])
    print("HARNESS_SHA256", h.harness_sha256())


if __name__ == "__main__":
    main_sensitivity() if "--sens" in sys.argv else main()
