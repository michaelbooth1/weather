"""R-PIT-T7 refuter: t7-c1 (Gaussian centred on captured NBM v2_mean, t7-r1 params) with the captured
NBM availability shifted +1 h / +2 h. Development only; refuter sensitivity of registered t7-c1, not a new rule.

For each market-day, the (v2_available_at, v2_mean) pairs seen in the captured table form the issue history;
at snapshot t the centre is the latest pair with v2_available_at + lag <= captured_at_utc (else served fallback).
lag = 0 must reproduce t7-c1 exactly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity.t7_mos_consensus import band_probs

OUT = Path(r"C:\swarm\out\refute-pit-t7")
T7 = Path(r"C:\swarm\out\t7")
BLOCKS = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def centres(snaps, lag_h):
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True, format="ISO8601")
    av = pd.to_datetime(snaps.v2_available_at, utc=True, format="ISO8601", errors="coerce")
    ok = snaps.v2_mean.notna() & av.notna() & (av <= cap)
    hist = pd.DataFrame({"market": snaps.market, "date": snaps.date, "av": av, "v": snaps.v2_mean})[ok]
    hist = hist.drop_duplicates(["market", "date", "av"]).sort_values("av")
    hist["av_eff"] = hist.av + pd.Timedelta(hours=lag_h)
    q = pd.DataFrame({"i": np.arange(len(snaps)), "market": snaps.market, "date": snaps.date, "cap": cap}).sort_values("cap")
    m = pd.merge_asof(q, hist[["market", "date", "av_eff", "v"]].sort_values("av_eff"), left_on="cap",
                      right_on="av_eff", by=["market", "date"], direction="backward")
    m = m.sort_values("i")
    good = m.v.notna().to_numpy()
    h.assert_point_in_time(m.av_eff[good], m.cap[good])  # shifted availability <= t
    return m.v.to_numpy(float)


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    par = {int(k): v for k, v in json.loads((T7 / "t7_meta.json").read_text())["meta"]["r1"]["params"].items()}
    snaps, bands = h.candidate_inputs()
    assert (snaps.date > "2026-09-29").sum() == 0
    bands = bands.sort_values(["row_key", "band_index"])
    groups = {rk: b for rk, b in bands.groupby("row_key", sort=False)}
    out_all = []
    for lag in (0.0, 1.0, 2.0):
        cen = centres(snaps, lag)
        out = []
        for rk, c, hh in zip(snaps.row_key, cen, snaps.local_hour):
            if not np.isfinite(c):
                continue
            b = groups[rk]
            p = band_probs(b, c + par[int(hh)]["b1"], par[int(hh)]["s1"], False)
            if p.sum() > 0:
                out.append(pd.DataFrame({"row_key": rk, "band_index": b.band_index.to_numpy(), "p": p}))
        res = h.score(pd.concat(out, ignore_index=True), name=f"refute_pit_t7_c1_lag{int(lag)}h")
        h.save(res, OUT)
        row = {}
        for g in BLOCKS:
            t = h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]
            tb = h.table_lookup(res, g, "before_20260823", "all_row")["candidate_minus_served"]
            row[g] = {"from": round(t["estimate"], 6), "ci95": [round(x, 6) for x in t["ci95"]],
                      "before": round(tb["estimate"], 6), "class": res["classes"][g]["class"]}
        s = {"name": res["name"], "lag_h": lag, "candidate_share": res.get("candidate_share"),
             "leakage_suspect_groups": res.get("leakage_suspect_groups"), "blocks": row,
             "HARNESS_SHA256": h.harness_sha256()}
        print(json.dumps(s), flush=True)
        out_all.append(s)
        (OUT / "c1_shift_results.json").write_text(json.dumps(out_all, indent=1))


if __name__ == "__main__":
    main()
