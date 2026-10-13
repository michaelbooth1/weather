"""F2 venue-rule labels (model-parity swarm v2, development only).

One row per market-day of the 111h extract (626 market-days, targets 2026-08-01..2026-09-29).
Labels are derived from IEM METAR/SPECI (C:\\swarm\\data\\iem\\metar) and compared with the
extract's winner band (and settlement_high). 1-minute ASOS (C:\\swarm\\data\\iem\\onemin) is used as
truth only: it is NOT point in time and is never a candidate input (DESIGN rule 1).

This is a LABEL agent. Nothing here is a candidate; winner/settlement_high are read only to measure
label disagreement, never to build a forecast.

Variants (report sets):
  R  : routine (hourly) METARs only
  RS : routine + SPECI
Conversions (per observation, then daily max; rounding is monotone so the order does not matter):
  cw : body whole-degree C -> F, F = round_half_up(C * 9/5 + 32)  (C*18 is even, so no .5 ties)
  ct : T-group tenths C -> F, F = round_half_up(C * 9/5 + 32) computed exactly in integer
       hundredths (F100 = tenths*18 + 3200; F = floor((F100 + 50) / 100)); ties at .5 F occur when
       the tenths value is = 25 mod 50 (e.g. 32.5 C = 90.5 F -> 91). Missing T-group falls back to
       cw for that observation (counted). Round-half-even sensitivity is reported.
  im : round_half_up(IEM tmpf) - diagnostic of the IEM-served value.
Day definition: local clock date (as WU displays) - primary; local STANDARD time day (NWS
climate-report convention) as a diagnostic for RS/ct only.
Dedup: rows at the same (valid_utc, report_type) - prefer the non-'MADISHF' (augmented) row; COR
reports are KEPT for labels (a venue shows the corrected report); they remain excluded from
candidate inputs by rule 1, which does not apply to labels.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

METAR_DIR = r"C:\swarm\data\iem\metar"
ONEMIN_DIR = r"C:\swarm\data\iem\onemin"
CACHE = r"C:\swarm\cache"
STATIONS = r"C:\swarm\stations.json"
OUT_LABELS = r"C:\swarm\labels\venue_labels.parquet"
OUT_DIR = r"C:\swarm\out\f2"
LAST = "2026-09-29"


def stop_check():
    if os.path.exists(r"C:\swarm\STOP"):
        print("STOP present; exiting")
        sys.exit(2)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rhu_from_hundredths(f100):
    """round half up for integer hundredths of F (works for negatives too: floor)."""
    return np.floor((f100 + 50) / 100.0)


def rhe_from_hundredths(f100):
    q, r = np.divmod(f100, 100)
    out = q.astype(float)
    out = np.where(r > 50, q + 1, out)
    out = np.where((r == 50) & (q % 2 == 1), q + 1, out)
    return out


def market_days():
    s = pd.read_parquet(os.path.join(CACHE, "snapshots.parquet"),
                        columns=["market", "station", "date", "stratum", "settlement_high", "winner",
                                 "row_key", "captured_at_utc"])
    assert (s["date"] <= LAST).all(), "rows after 2026-09-29 in cache"
    md = (s.sort_values("captured_at_utc").groupby(["market", "date"])
          .agg(station=("station", "first"), stratum=("stratum", "first"),
               settlement_high=("settlement_high", "first"), winner_band=("winner", "first"),
               last_row_key=("row_key", "last"), n_settle=("settlement_high", "nunique"),
               n_winner=("winner", "nunique"))
          .reset_index())
    assert md.n_settle.max() == 1 and md.n_winner.max() == 1
    b = pd.read_parquet(os.path.join(CACHE, "bands.parquet"),
                        columns=["row_key", "band_index", "kind", "low", "high", "market", "date"])
    # band-set consistency across snapshots of a market-day
    sig = (b.sort_values(["row_key", "band_index"]).groupby(["market", "date", "row_key"])
           .apply(lambda g: tuple(zip(g.kind, g.low, g.high)), include_groups=False))
    nsig = sig.groupby(level=[0, 1]).nunique()
    bl = b[b.row_key.isin(md.last_row_key)]
    bands = {k: g.sort_values("band_index")[["band_index", "kind", "low", "high"]].to_numpy().tolist()
             for k, g in bl.groupby(["market", "date"])}
    md["band_sets_seen"] = [int(nsig.loc[(m, d)]) for m, d in zip(md.market, md.date)]
    return md, bands


def band_of(value, bandlist):
    if value is None or not np.isfinite(value):
        return -1
    for idx, kind, low, high in bandlist:
        if kind == "lte" and value <= high:
            return int(idx)
        if kind == "gte" and value >= low:
            return int(idx)
        if kind == "eq" and low <= value <= high:
            return int(idx)
    return -1


def load_metar(station, tzname):
    m = pd.read_parquet(os.path.join(METAR_DIR, f"{station}.parquet"),
                        columns=["valid_utc", "report_type", "is_cor", "tmpf", "tgroup_c",
                                 "main_temp_c", "metar", "local_date"])
    m["local_date"] = m["local_date"].astype(str)
    m = m[(m.local_date >= "2026-07-31") & (m.local_date <= LAST)].copy()
    m["madis"] = m.metar.str.contains("MADISHF", na=False)
    m = m.sort_values(["valid_utc", "report_type", "madis"])
    ndup = int(m.duplicated(["valid_utc", "report_type"]).sum())
    m = m.drop_duplicates(["valid_utc", "report_type"], keep="first")
    # local standard date
    tz = ZoneInfo(tzname)
    std_off = dt.datetime(2026, 1, 15, tzinfo=tz).utcoffset()
    m["lst_date"] = (m.valid_utc.dt.tz_convert(None) + std_off).dt.date.astype(str)
    tenths = np.round(m.tgroup_c.to_numpy() * 10)
    ct100 = tenths * 18 + 3200
    cw = rhu_from_hundredths(m.main_temp_c.to_numpy() * 180 + 3200)
    ct = rhu_from_hundredths(ct100)
    cte = rhe_from_hundredths(np.where(np.isfinite(ct100), ct100, 0).astype(np.int64))
    m["f_cw"] = cw
    m["f_ct"] = np.where(np.isfinite(ct), ct, cw)
    m["f_ct_even"] = np.where(np.isfinite(ct100), cte, cw)
    m["ct_fallback"] = ~np.isfinite(ct) & np.isfinite(cw)
    m["ct_tie"] = np.isfinite(ct100) & (np.mod(np.where(np.isfinite(ct100), ct100, 0), 100) == 50)
    m["f_im"] = np.floor(m.tmpf.to_numpy() + 0.5)
    m["f_ct_raw"] = ct100 / 100.0  # unrounded T-group F
    return m, ndup


def day_stats(m, date_col):
    out = {}
    for variant, sel in (("R", m.report_type == "routine"), ("RS", m.report_type.isin(["routine", "speci"])),
                         ("RSnc", m.report_type.isin(["routine", "speci"]) & ~m.is_cor)):
        g = m[sel].groupby(date_col)
        agg = g.agg(**{f"{variant}_cw": ("f_cw", "max"), f"{variant}_ct": ("f_ct", "max"),
                       f"{variant}_ct_even": ("f_ct_even", "max"), f"{variant}_im": ("f_im", "max"),
                       f"{variant}_ct_raw_max": ("f_ct_raw", "max"),
                       f"{variant}_n": ("f_cw", "count")})
        out[variant] = agg
    return pd.concat(out.values(), axis=1)


def main():
    stop_check()
    st = json.load(open(STATIONS))["stations"]
    md, bands = market_days()
    print("market-days", len(md), "band sets >1:", int((md.band_sets_seen > 1).sum()))
    rows = []
    audit = {"dedup_dropped": {}, "ct_fallback_rows": {}, "ct_tie_rows": {}, "cor_rows": {}, "speci_rows": {}}
    per_station = {}
    for station in sorted(md.station.unique()):
        m, ndup = load_metar(station, st[station]["tzname"])
        audit["dedup_dropped"][station] = ndup
        audit["ct_fallback_rows"][station] = int(m.ct_fallback.sum())
        audit["ct_tie_rows"][station] = int(m.ct_tie.sum())
        audit["cor_rows"][station] = int(m.is_cor.sum())
        audit["speci_rows"][station] = int((m.report_type == "speci").sum())
        clock = day_stats(m, "local_date")
        lst = day_stats(m, "lst_date")[["RS_ct", "R_ct", "RS_n"]].add_prefix("lst_")
        nc = m.groupby("local_date").is_cor.sum().rename("n_cor")
        per_station[station] = pd.concat([clock, lst, nc], axis=1)
        # 1-minute truth
        o = pd.read_parquet(os.path.join(ONEMIN_DIR, f"{station}.parquet"))
        if len(o):
            o["local_date"] = o["local_date"].astype(str)
            o = o[o.local_date <= LAST]
            om = o.groupby("local_date").agg(onemin_max_f=("tmpf", "max"), onemin_minutes=("tmpf", "count"))
        else:
            om = pd.DataFrame(columns=["onemin_max_f", "onemin_minutes"])
        per_station[station] = per_station[station].join(om, how="left")
    cov = pd.read_csv(os.path.join(ONEMIN_DIR, "coverage_station_day.csv"), dtype={"local_date": str})
    cov = cov.set_index(["icao", "local_date"])
    for r in md.itertuples(index=False):
        d = per_station[r.station]
        rec = {"market": r.market, "station": r.station, "date": r.date, "stratum": r.stratum,
               "settlement_high": r.settlement_high, "winner_band": int(r.winner_band),
               "band_sets_seen": r.band_sets_seen}
        bl = bands[(r.market, r.date)]
        wb = [x for x in bl if int(x[0]) == int(r.winner_band)][0]
        rec.update(winner_kind=wb[1], winner_low=wb[2], winner_high=wb[3])
        rec["settlement_band"] = band_of(r.settlement_high, bl)
        if r.date in d.index:
            row = d.loc[r.date]
            for k, v in row.items():
                rec[k] = float(v) if pd.notna(v) else np.nan
        if (r.station, r.date) in cov.index:
            c = cov.loc[(r.station, r.date)]
            rec["onemin_coverage_frac"] = float(c.coverage_frac)
            rec["onemin_minutes_10_18"] = float(c.minutes_valid_10_18_local)
            rec["onemin_max_gap_min"] = float(c.max_gap_min)
        for lab in ["R_cw", "R_ct", "R_im", "RS_cw", "RS_ct", "RS_im", "R_ct_even", "RS_ct_even", "RSnc_ct",
                    "lst_RS_ct", "lst_R_ct", "onemin_max_f"]:
            v = rec.get(lab, np.nan)
            rec[f"{lab}_band"] = band_of(v, bl)
        rows.append(rec)
    df = pd.DataFrame(rows)
    df["onemin_full"] = (df.get("onemin_coverage_frac", np.nan) >= 0.9) & (df.get("onemin_minutes_10_18", 0) >= 456)
    df["metar_full"] = df["R_n"] >= 22
    assert (df.date <= LAST).all()
    os.makedirs(os.path.dirname(OUT_LABELS), exist_ok=True)
    df.to_parquet(OUT_LABELS, index=False)
    audit["n_market_days"] = len(df)
    audit["rows_after_0929"] = int((df.date > LAST).sum())
    audit["labels_sha256"] = sha(OUT_LABELS)
    audit["inputs"] = {f"metar/{s}.parquet": sha(os.path.join(METAR_DIR, f"{s}.parquet")) for s in sorted(md.station.unique())}
    audit["inputs"].update({f"onemin/{s}.parquet": sha(os.path.join(ONEMIN_DIR, f"{s}.parquet")) for s in sorted(md.station.unique())})
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(audit, open(os.path.join(OUT_DIR, "audit.json"), "w"), indent=1)
    print(json.dumps({k: audit[k] for k in ("n_market_days", "rows_after_0929", "labels_sha256")}))
    return df


def summarize(df):
    labs = ["R_cw", "R_ct", "R_im", "RS_cw", "RS_ct", "RS_im", "R_ct_even", "RS_ct_even", "RSnc_ct", "lst_RS_ct", "lst_R_ct"]
    res = {"pooled": {}, "per_market": {}, "per_stratum": {}}

    def stats(sub, lab):
        ok = sub[f"{lab}_band"] >= 0
        s = sub[ok]
        n = int(len(s))
        band_dis = int((s[f"{lab}_band"] != s.winner_band).sum())
        val_dis = int((s[lab] != s.settlement_high).sum())
        diff = (s[lab] - s.settlement_high)
        return {"n": n, "missing": int((~ok).sum()), "band_disagree": band_dis,
                "band_disagree_rate": round(band_dis / n, 4) if n else None,
                "value_disagree": val_dis, "value_disagree_rate": round(val_dis / n, 4) if n else None,
                "label_above": int((diff > 0).sum()), "label_below": int((diff < 0).sum()),
                "mean_diff": round(float(diff.mean()), 3) if n else None}

    for lab in labs:
        res["pooled"][lab] = stats(df, lab)
        res["per_market"][lab] = {m: stats(g, lab) for m, g in df.groupby("market")}
        res["per_stratum"][lab] = {k: stats(g, lab) for k, g in df.groupby("stratum")}
    om = df[df.onemin_full.fillna(False)]
    res["onemin_full"] = stats(om, "onemin_max_f")
    res["onemin_full_per_market"] = {m: stats(g, "onemin_max_f") for m, g in om.groupby("market")}
    res["onemin_any"] = stats(df[df.onemin_max_f.notna()], "onemin_max_f")
    # truth vs hourly-row label (on full 1-min days)
    t = om[om.RS_ct.notna()]
    res["onemin_vs_RS_ct"] = {"n": int(len(t)),
                              "value_diff_counts": {str(int(k)): int(v) for k, v in (t.onemin_max_f - t.RS_ct).value_counts().sort_index().items()},
                              "band_differs": int((t.onemin_max_f_band != t.RS_ct_band).sum())}
    t2 = om[om.R_ct.notna()]
    res["onemin_vs_R_ct"] = {"n": int(len(t2)),
                             "value_diff_counts": {str(int(k)): int(v) for k, v in (t2.onemin_max_f - t2.R_ct).value_counts().sort_index().items()},
                             "band_differs": int((t2.onemin_max_f_band != t2.R_ct_band).sum())}
    res["settlement_high_vs_winner_band_mismatch"] = int((df.settlement_band != df.winner_band).sum())
    res["band_sets_varying_market_days"] = int((df.band_sets_seen > 1).sum())
    res["metar_partial_days"] = int((~df.metar_full).sum())
    res["speci_raises_max_days"] = int((df.RS_ct > df.R_ct).sum())
    res["speci_changes_band_days"] = int((df.RS_ct_band != df.R_ct_band).sum())
    res["ct_vs_cw_value_differs_RS"] = int((df.RS_ct != df.RS_cw).sum())
    res["ct_vs_cw_band_differs_RS"] = int((df.RS_ct_band != df.RS_cw_band).sum())
    res["ct_even_vs_ct_value_differs_RS"] = int((df.RS_ct_even != df.RS_ct).sum())
    res["lst_vs_clock_band_differs_RS_ct"] = int((df.lst_RS_ct_band != df.RS_ct_band).sum())
    return res


if __name__ == "__main__":
    df = main()
    res = summarize(df)
    json.dump(res, open(os.path.join(OUT_DIR, "result.json"), "w"), indent=1)
    print(json.dumps(res["pooled"], indent=0)[:3000])
