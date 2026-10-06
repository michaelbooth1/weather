"""R-PIT-T2: PIT/leakage refuter re-run of T2 (t2_remaining_rise) under shifted METAR availability.

Development only. Imports the hunter's module unchanged and the shared harness; registers no rule.
Outputs go to C:\\swarm\\out\\refute-pit-t2 (never into the hunter's directory).

Modes (env T2_LAG_MIN, read by the hunter's module at import):
  both-shift  : the hunter's own switch: history grid AND live snapshots use valid + LAG_MIN.
  live-only   : history grid at the manifest basis (+10 min), live snapshots at valid + LAG_MIN.
                This is the stricter refuter case: the fitted table assumes the manifest basis while the
                serving-time observation arrives late.

Run: cd C:\\pt\\swarm; set T2_LAG_MIN=60; <repo python> -m tools.research.model_parity.r_pit_t2_rerun [live-only]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t2_remaining_rise as t2

OUT = Path(r"C:\swarm\out\refute-pit-t2")
LAG = t2.LAG_MIN
MODE = sys.argv[1] if len(sys.argv) > 1 else "both-shift"


def load_station_lag(st: str, lag: int) -> pd.DataFrame:
    m = pd.read_parquet(t2.METAR / f"{st}.parquet")
    m = m[(~m.is_cor) & m.tmpf.notna()].copy()
    m["available_utc"] = m.valid_utc + pd.Timedelta(minutes=lag)
    assert ((m.available_utc - m.valid_utc) >= pd.Timedelta(minutes=10)).all()
    m["t"] = np.round(m.tmpf.to_numpy()).astype(int)
    m["local_date"] = m.local_date.astype(str)
    m = m.sort_values("valid_utc").drop_duplicates("valid_utc", keep="last").reset_index(drop=True)
    m["cmax"] = m.groupby("local_date").t.cummax()
    return m


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    hist_lag = 10 if MODE == "live-only" else LAG
    stations_live, tables = {}, {}
    for st in t2.TZ:
        m_hist = load_station_lag(st, hist_lag)
        tables[st] = t2.cell_dists(t2.history_table(st, m_hist))
        stations_live[st] = m_hist if hist_lag == LAG else load_station_lag(st, LAG)
    snaps = snaps.copy()
    snaps["tmonth"] = snaps.date.str[5:7].astype(int)
    feats = []
    for st, g in snaps.groupby("station"):
        ok, M, T, db, sb, av = t2.state(stations_live[st], g.captured_at_utc, g.date.to_numpy())
        cap = t2.us(g.captured_at_utc)
        assert (av[ok] <= cap[ok]).all()
        feats.append(pd.DataFrame({"ok": ok, "M": M, "T": T, "db": db, "sb": sb, "av": av, "cap": cap}, index=g.index))
    snaps = snaps.join(pd.concat(feats).loc[snaps.index])
    # rule-1 guard on EVERY covered snapshot's latest row (the hunter sampled 2,000)
    h.assert_point_in_time(t2.EPOCH + pd.to_timedelta(snaps.av[snaps.ok].to_numpy(), unit="us"),
                           snaps.captured_at_utc[snaps.ok])
    # availability-shift bookkeeping: minutes between latest METAR availability and capture
    slack_min = (snaps.cap[snaps.ok] - snaps.av[snaps.ok]) / 60_000_000
    bands = bands.merge(snaps[["row_key", "station", "tmonth", "local_hour", "ok", "M", "db", "sb"]], on="row_key")
    bands = bands.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    p1 = np.full(len(bands), np.nan)
    lvls = {}
    for rk, g in bands.groupby("row_key", sort=False):
        r0 = g.iloc[0]
        if not r0.ok:
            continue
        pR, lvl = t2.lookup(tables[r0.station], int(r0.tmonth), int(r0.local_hour), int(r0.db), int(r0.sb))
        lvls[lvl] = lvls.get(lvl, 0) + 1
        if pR is None:
            continue
        p1[g.index] = t2.band_probs(pR, int(r0.M), g.kind.to_numpy(), g.low.to_numpy(), g.high.to_numpy())
    cov = ~np.isnan(p1)
    name = f"rpit_t2_r1_{MODE.replace('-', '_')}_lag{LAG}"
    c = bands.loc[cov, ["row_key", "band_index"]].assign(p=p1[cov])
    tot = c.groupby("row_key").p.transform("sum")
    c = c[tot > 0]
    res = h.score(c, name=name)
    h.save(res, OUT)
    (OUT / f"{name}.md").write_text(h.markdown(res), encoding="utf-8")
    print(h.markdown(res))
    summary = {"name": name, "mode": MODE, "live_lag_min": LAG, "hist_lag_min": hist_lag,
               "HARNESS_SHA256": h.harness_sha256(), "covered_snapshots": int(snaps.ok.sum()),
               "total_snapshots": int(len(snaps)), "backoff_levels": {str(k): v for k, v in lvls.items()},
               "slack_minutes_quantiles": {q: float(np.quantile(slack_min, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
               "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
               "from_all_row": {g: h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]
                                for g in ("13-16", "17-23", "00-16", "all")},
               "leakage_suspect_groups": res["leakage_suspect_groups"],
               "rows_after_20260929": res["rows_with_target_after_2026_09_29"]}
    (OUT / f"{name}.summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("name", "covered_snapshots", "classes", "slack_minutes_quantiles")}, default=float))


if __name__ == "__main__":
    main()
