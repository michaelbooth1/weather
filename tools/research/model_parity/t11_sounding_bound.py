"""T11 hunter: 12Z sounding mixed-layer max-T bound (development only).

Rules t11-r1..r4 (text in RULES below, registered in C:\swarm\registry.jsonl before scoring).
Inputs: A-Soundings soundings_summary.csv.gz (IEM RAOB, availability = valid + 60 min stated basis),
A-IEM-1 METAR parquet (fit target on local dates 2026-05-01..2026-07-31 only).
No market inputs, no labels; the harness applies the floor and served fallback.
Run: cd C:\pt\swarm; <repo python> -m tools.research.model_parity.t11_sounding_bound [fit|score]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SND = Path(r"C:\swarm\data\soundings")
METAR = Path(r"C:\swarm\data\iem\metar")
OUT = Path(r"C:\swarm\out\t11")
FIT_START, FIT_END = "2026-05-01", "2026-07-31"
MARKET_STATION = {"atlanta": "KATL", "austin": "KAUS", "chicago": "KORD", "dallas": "KDAL",
                  "denver": "KBKF", "houston": "KHOU", "los-angeles": "KLAX", "miami": "KMIA",
                  "nyc": "KLGA", "san-francisco": "KSFO", "seattle": "KSEA"}
MIN_FIT_DAYS = 30
EXCLUDED_RAOB = {"KEDW"}


def raob_order():
    man = json.loads((SND / "MANIFEST.json").read_text(encoding="utf-8"))
    return {st: [c["raob"] for c in cands if c["raob"] not in EXCLUDED_RAOB]
            for st, cands in man["market_to_raob"].items()}


def soundings():
    d = pd.read_csv(SND / "soundings_summary.csv.gz")
    d["valid_utc"] = pd.to_datetime(d["valid_utc"], utc=True)
    d["available_utc"] = pd.to_datetime(d["available_utc_basis"], utc=True)
    d["udate"] = d["valid_utc"].dt.strftime("%Y-%m-%d")
    # nominal synoptic soundings only (specials at odd hours dropped)
    d = d[(d.valid_utc.dt.minute == 0) & d.valid_utc.dt.hour.isin([12, 18])]
    assert (d.udate <= "2026-09-29").all()
    return d


def station_sounding(snd, station, hour, order):
    """One row per UTC date: first RAOB in candidate order with a nominal `hour`Z sounding."""
    sub = snd[(snd.valid_utc.dt.hour == hour) & snd.raob.isin(order)].copy()
    sub["rank"] = sub.raob.map({r: i for i, r in enumerate(order)})
    sub = sub.dropna(subset=["t850_adiab_sfc_f"]).sort_values(["udate", "rank"])
    return sub.drop_duplicates("udate").set_index("udate")


def metar_daily_max(station):
    m = pd.read_parquet(METAR / f"{station}.parquet")
    m = m[~m.is_cor & m.tmpf.notna()]
    m["local_date"] = m.local_date.astype(str)
    g = m.groupby("local_date").agg(ymax=("tmpf", "max"), n=("tmpf", "size"))
    return g[g.n >= 20].ymax.round()


def fit(predictor):
    """Residual quantiles per market x synoptic hour on local dates 2026-05-01..07-31 only."""
    snd, order = soundings(), raob_order()
    out = {}
    for mk, st in MARKET_STATION.items():
        y = metar_daily_max(st)
        for hour in (12, 18):
            s = station_sounding(snd, st, hour, order[st])
            j = s.join(y, how="inner")      # UTC date of 12Z/18Z == local date for US stations
            j = j[(j.index >= FIT_START) & (j.index <= FIT_END)]
            r = (j.ymax - j[predictor]).dropna()
            out[(mk, hour)] = {"n": int(r.size),
                               **{f"q{q}": float(np.quantile(r, q / 1000)) if r.size else None
                                  for q in (10, 25, 975, 990, 500, 250, 750)}}
    return out


def fit_report():
    rows = []
    for pred in ("t850_adiab_sfc_f", "max_theta_low300_at_sfc_f", "t925_adiab_sfc_f"):
        f = fit(pred)
        for (mk, hour), v in f.items():
            rows.append({"predictor": pred, "market": mk, "hour": hour, **v})
    df = pd.DataFrame(rows)
    df["iqr"] = df.q750 - df.q250
    df["w98"] = df.q990 - df.q10
    return df


RULES = {
    "t11-r1": ("T11-r1 sounding upper bound, 12Z only, q0.99. For market m and local target date D take the nominal 12Z RAOB "
               "valid on UTC date D from the first station in A-Soundings MANIFEST market_to_raob[m] (candidate order, KEDW excluded) "
               "that has a 12Z sounding with t850_adiab_sfc_f; X = t850_adiab_sfc_f (850 hPa T descended dry-adiabatically to RAOB "
               "surface pressure, degF). Available at valid+60 min (13:00Z, A-Soundings stated basis); used only at snapshots with "
               "captured_at_utc >= available (h.assert_point_in_time). Per market residual R = METAR daily max (local date, routine+SPECI, "
               "non-COR, >=20 rows, round(max tmpf)) - X, fitted on local dates 2026-05-01..2026-07-31 with the same station choice; "
               "needs >=30 fit days else no candidate. U = X + quantile_0.99(R). Candidate: p=0 on every band with low > U, renormalise "
               "p_served; harness floor; zero mass, no sounding or no fit -> served fallback. No market input, no labels."),
    "t11-r2": ("T11-r2 = t11-r1 plus lower bound L = X + quantile_0.01(R): also p=0 on every band with high < L; renormalise; "
               "same availability, fit window, fallback."),
    "t11-r3": ("T11-r3 = t11-r2 with tighter quantiles 0.975 (upper) / 0.025 (lower)."),
    "t11-r4": ("T11-r4 = t11-r2 (q0.99/q0.01, X = t850_adiab_sfc_f), but when no candidate RAOB has a 12Z sounding on UTC date D, "
               "use the nominal 18Z sounding on D (first in candidate order), available 19:00Z, with residual quantiles fitted "
               "separately for 18Z on 2026-05-01..07-31 (>=30 fit days)."),
    "t11-r5": ("T11-r5 = t11-r2 (12Z only, q0.99/q0.01) with X = t925_adiab_sfc_f (925 hPa T descended dry-adiabatically), the "
               "predictor with the narrowest median 1-99% residual width on the 2026-05-01..07-31 fit window (selected on history only)."),
}
VARIANTS = {  # rule -> (predictor, q_hi, q_lo or None, allow 18Z)
    "t11-r1": ("t850_adiab_sfc_f", "q990", None, False),
    "t11-r2": ("t850_adiab_sfc_f", "q990", "q10", False),
    "t11-r3": ("t850_adiab_sfc_f", "q975", "q25", False),
    "t11-r4": ("t850_adiab_sfc_f", "q990", "q10", True),
    "t11-r5": ("t925_adiab_sfc_f", "q990", "q10", False),
}


def bounds_table(rule, avail_shift_h=0.0):
    """Per (market, date): U, L, available_utc. Inputs are soundings + history-fitted quantiles only."""
    pred, qh, ql, allow18 = VARIANTS[rule]
    snd, order, f = soundings(), raob_order(), fit(pred)
    rows = []
    for mk, st in MARKET_STATION.items():
        s12 = station_sounding(snd, st, 12, order[st])
        s18 = station_sounding(snd, st, 18, order[st]) if allow18 else None
        dates = pd.date_range("2026-08-01", "2026-09-29").strftime("%Y-%m-%d")
        for d in dates:
            src = None
            if d in s12.index and f[(mk, 12)]["n"] >= MIN_FIT_DAYS:
                src, hour = s12.loc[d], 12
            elif allow18 and d in s18.index and f[(mk, 18)]["n"] >= MIN_FIT_DAYS:
                src, hour = s18.loc[d], 18
            if src is None or pd.isna(src[pred]):
                continue
            q = f[(mk, hour)]
            rows.append({"market": mk, "date": d, "raob": src.raob, "hour": hour, "x": float(src[pred]),
                         "U": float(src[pred]) + q[qh],
                         "L": (float(src[pred]) + q[ql]) if ql else -np.inf,
                         "available_utc": src.available_utc + pd.Timedelta(hours=avail_shift_h)})
    return pd.DataFrame(rows)


def candidate(rule, avail_shift_h=0.0):
    from tools.research.model_parity import harness as h
    snaps, bands = h.candidate_inputs()
    bt = bounds_table(rule, avail_shift_h)
    sn = snaps[["row_key", "market", "date", "captured_at_utc"]].merge(bt, on=["market", "date"], how="inner")
    cap = pd.to_datetime(sn.captured_at_utc, utc=True)
    sn = sn[cap >= sn.available_utc].copy()
    for a, c in zip(sn.available_utc, sn.captured_at_utc):     # rule 1 asserts on every joined value
        h.assert_point_in_time(a, c)
    assert (sn.date <= "2026-09-29").all()
    b = bands.merge(sn[["row_key", "U", "L"]], on="row_key", how="inner")
    keep = ~((b.low > b.U) | (b.high < b.L))
    # lte band: low is its upper edge too (low == high); gte band: high == low; rule uses low>U / high<L
    b["p"] = np.where(keep, b.p_served, 0.0)
    tot = b.groupby("row_key").p.transform("sum")
    b["cut"] = np.where(keep, 0.0, b.p_served)
    b = b[tot > 0].copy()
    b["p"] = b.p / tot[tot > 0]
    return b[["row_key", "band_index", "p"]], bt, sn


def main_score():
    from tools.research.model_parity import harness as h
    summary = {}
    for rule in VARIANTS:
        cand, bt, sn = candidate(rule)
        res = h.score(cand, name=f"t11_{rule.replace('-', '_')}")
        h.save(res, OUT)
        (OUT / f"{rule}.md").write_text(h.markdown(res), encoding="utf-8")
        summary[rule] = {"bound_days": int(len(bt)), "covered_snapshots": int(cand.row_key.nunique()),
                         "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                         "leakage_suspect_groups": res.get("leakage_suspect_groups")}
        print(rule, json.dumps(summary[rule]))
    (OUT / "summary_scores.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "score"
    if mode == "fit":
        df = fit_report()
        pd.set_option("display.width", 250)
        print(df.round(2).to_string())
        print(df[df.hour == 12].groupby("predictor")[["iqr", "w98"]].median())
    elif mode == "score":
        main_score()
