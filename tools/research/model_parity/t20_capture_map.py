"""T20 serveability / capture mapper: descriptive latency facts from the 111h table (development).

No candidate is scored here (no registry entry needed): this only describes what production
captured at each snapshot (fetch ages, availability ages, null rates, snapshot cadence) and
infers which HRRR run Open-Meteo was serving behind the captured ``hrrr_high`` by matching it
against Open-Meteo Single-Runs HRRR 06/12/18Z full-day maxima. Target dates <= 2026-09-29 only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(r"C:\swarm\cache\snapshots.parquet")
SINGLERUNS = Path(r"C:\swarm\data\singleruns\singleruns_long.parquet")
OUT = Path(r"C:\swarm\out\t20")
TZ = {
    "KATL": "America/New_York", "KLGA": "America/New_York", "KMIA": "America/New_York",
    "KORD": "America/Chicago", "KAUS": "America/Chicago", "KDAL": "America/Chicago",
    "KHOU": "America/Chicago", "KBKF": "America/Denver", "KSEA": "America/Los_Angeles",
    "KSFO": "America/Los_Angeles", "KLAX": "America/Los_Angeles",
}


def q(series, qs=(0.1, 0.5, 0.9)):
    s = pd.Series(series).dropna()
    return {f"p{int(x*100)}": (round(float(s.quantile(x)), 3) if len(s) else None) for x in qs} | {"n": int(len(s))}


def main():
    s = pd.read_parquet(CACHE)
    s["target_date"] = pd.to_datetime(s["target_date"]).dt.date
    assert (pd.to_datetime(s["target_date"].astype(str)) >= "2026-09-30").sum() == 0
    cap = pd.to_datetime(s["captured_at_utc"], utc=True)
    out = {"rows": int(len(s)), "rows_ge_20260930": 0}

    # snapshot cadence per market-day
    s = s.assign(_cap=cap).sort_values(["market", "target_date", "_cap"])
    gap = s.groupby(["market", "target_date"])["_cap"].diff().dt.total_seconds() / 60
    out["snapshot_gap_min_by_block"] = {b: q(gap[s["block"] == b]) for b in sorted(s["block"].unique())}
    out["snapshots_per_market_day"] = q(s.groupby(["market", "target_date"]).size())

    def age_min(col):
        t = pd.to_datetime(s[col], utc=True, errors="coerce")
        return (s["_cap"] - t).dt.total_seconds() / 60

    out["hrrr_fetch_age_min_by_block"] = {b: q(age_min("hrrr_fetched_at")[s["block"] == b]) for b in sorted(s["block"].unique())}
    out["nws_grid_update_age_min_by_block"] = {b: q(age_min("nws_grid_updated_at")[s["block"] == b]) for b in sorted(s["block"].unique())}
    out["nws_grid_fetch_age_min"] = q(age_min("nws_grid_fetched_at"))
    out["v2_age_h_by_block"] = {b: q(s.loc[s["block"] == b, "v2_age_hours"]) for b in sorted(s["block"].unique())}
    v2_avail_lag = (pd.to_datetime(s["v2_available_at"], utc=True) - pd.to_datetime(s["v2_issued_at"], utc=True)).dt.total_seconds() / 60
    out["v2_issue_to_available_min"] = q(v2_avail_lag)
    out["v2_available_basis"] = s["v2_available_basis"].value_counts().to_dict()
    out["v1_period_counts"] = s["v1_period"].value_counts().to_dict()

    nulls = {}
    for c in ["high_so_far", "trusted_current_max", "guidance_physical_floor", "hrrr_high", "nws_grid_high",
              "forecast_high", "nbm_prob_tmax_mean", "v2_mean"]:
        nulls[c] = {b: round(float(s.loc[s["block"] == b, c].isna().mean()), 4) for b in sorted(s["block"].unique())}
    out["null_rate_by_block"] = nulls
    both = s[["high_so_far", "guidance_physical_floor"]].dropna()
    out["floor_minus_high_so_far"] = q(both["guidance_physical_floor"] - both["high_so_far"], (0.01, 0.5, 0.99))
    out["floor_ge_high_so_far_share"] = round(float((both["guidance_physical_floor"] >= both["high_so_far"] - 1e-9).mean()), 4)

    # ---- HRRR run behind captured hrrr_high ----
    r = pd.read_parquet(SINGLERUNS)
    r = r[r["model"] == "ncep_hrrr_conus"].copy()
    r = r[r["run_utc"].dt.hour.isin([6, 12, 18])]  # 48 h runs cover a whole local day
    recs = []
    for st, tz in TZ.items():
        rs = r[r["station"] == st].copy()
        rs["local_date"] = rs["valid_utc"].dt.tz_convert(tz).dt.date
        g = rs.groupby(["run_utc", "local_date"])["temperature_2m"].agg(["max", "count"]).reset_index()
        g = g[g["count"] >= 18]  # local day mostly covered
        g["station"] = st
        recs.append(g)
    runmax = pd.concat(recs)
    snap = s[["station", "target_date", "hrrr_high", "hrrr_fetched_at", "_cap", "block"]].dropna(subset=["hrrr_high", "hrrr_fetched_at"]).copy()
    snap["fetched"] = pd.to_datetime(snap["hrrr_fetched_at"], utc=True)
    m = snap.reset_index().merge(runmax, left_on=["station", "target_date"], right_on=["station", "local_date"], how="inner")
    m["absdiff"] = (m["hrrr_high"] - m["max"]).abs()
    m["run_age_h"] = (m["fetched"] - m["run_utc"]).dt.total_seconds() / 3600
    m = m[(m["run_age_h"] > -24) & (m["run_age_h"] < 30)]
    best = m.sort_values("absdiff").groupby("index").head(2)
    first = best.groupby("index").nth(0).set_index("index")
    second = best.groupby("index").nth(1).set_index("index")
    clear = first.join(second[["absdiff"]], rsuffix="_2nd")
    clear = clear[(clear["absdiff"] <= 0.15) & (clear["absdiff_2nd"] > 0.5) & (clear["station"] != "KSFO")]
    out["hrrr_match"] = {
        "snapshots_with_unique_match": int(len(clear)),
        "matched_run_age_at_fetch_h": q(clear["run_age_h"], (0.01, 0.05, 0.1, 0.5, 0.9)),
        "share_matched_run_in_future_of_fetch": round(float((clear["run_age_h"] < 0).mean()), 4),
        "note": "KSFO excluded (Single-Runs grid point differs from AWS, a-hrrr-aws). Only 06/12/18Z runs "
                "are in the Single-Runs set, so a match to e.g. 12Z means Open-Meteo served 12Z (or an hourly "
                "run with the same day max). The minimum matched age is the effective publication delay.",
    }
    # per run: earliest fetch at which it was matched
    first_seen = clear.groupby(["station", "run_utc"])["run_age_h"].min()
    out["hrrr_first_seen_age_h_per_run"] = q(first_seen, (0.05, 0.1, 0.25, 0.5, 0.9))
    (OUT / "t20_capture_facts.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
