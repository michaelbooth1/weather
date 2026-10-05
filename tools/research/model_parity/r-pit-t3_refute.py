"""R-PIT-T3: PIT/leakage refuter for T3 t3-r3 (floor + remaining rise). Development only.

Re-runs t3-r3 through the harness with METAR availability shifted, using T3's own helper functions
unchanged (imported, not edited):
  - both-shift (as registered for t3-r3s): +60 and +120 min at serve time AND in the history table;
  - serve-only shift: history table at the registered +10 min basis, serve-time rows +60 / +120 min
    (the stricter test: does the lead need METARs fresher than the shift?);
  - +0 reproduction of the registered t3-r3 score.
Also: empirical availability check of the METAR running max against production's captured PIT
obs features (high_so_far / trusted_current_max), and local_hour vs captured_at_utc consistency.
No new rules: these are diagnostics of the registered rule.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-pit-t3_refute  (via runpy)
"""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3

OUT = Path(r"C:\swarm\out\r-pit-t3")
BLOCKS = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def rise_dict(rr):
    rise = {}
    for (st, mo, H), g in rr.groupby(["station", "month", "hour"]):
        base, p = t3.smooth_pmf(g.rise.to_numpy())
        vals = base + np.arange(len(p))
        neg = vals < 0
        p0 = p[neg].sum()
        p = p[~neg]; base = max(base, 0)
        p[0] += p0
        rise[(st, mo, H)] = (base, p, len(g))
    return rise


def r3_candidate(snaps, bands, rise, today):
    bkind = bands.kind.to_numpy(); blo = bands.low.to_numpy(); bhi = bands.high.to_numpy()
    rkeys = bands.row_key.to_numpy()
    starts = np.r_[0, np.flatnonzero(rkeys[1:] != rkeys[:-1]) + 1]
    ends = np.r_[starts[1:], len(bands)]
    sidx = snaps.set_index("row_key")
    rk, bi, pp = [], [], []
    for a, b in zip(starts, ends):
        k = rkeys[a]
        sn = sidx.loc[k]
        st, mo, H = sn.station, int(sn.month), int(sn.local_hour)
        t = today.loc[k]
        if pd.notna(t["cummax"]) and (st, mo, H) in rise:
            rb, rp, _ = rise[(st, mo, H)]
            v = t3.band_probs(int(t["cummax"]) + rb, rp, list(zip(bkind[a:b], blo[a:b], bhi[a:b])))
            rk.extend([k] * (b - a)); bi.extend(range(b - a)); pp.extend(v.tolist())
    return pd.DataFrame({"row_key": rk, "band_index": bi, "p": pp})


def summarise(res):
    out = {}
    for g in BLOCKS:
        t = h.table_lookup(res, g, "from_20260823", "all_row")
        tb = h.table_lookup(res, g, "before_20260823", "all_row")
        c = res["classes"][g]
        pm = t["per_market_delta"]
        neg = sum(1 for v in (pm.values() if isinstance(pm, dict) else pm) if (v if not isinstance(v, dict) else v.get("estimate", 0)) < 0)
        out[g] = {"class": c["class"], "from": t["candidate_minus_served"]["estimate"],
                  "from_ci": t["candidate_minus_served"]["ci95"],
                  "before": tb["candidate_minus_served"]["estimate"], "markets_neg": neg,
                  "cand_minus_market": t["candidate_minus_market"]["estimate"]}
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    snaps = snaps.copy()
    snaps["month"] = snaps.date.str[5:7].astype(int)
    report = {"HARNESS_SHA256": h.harness_sha256(), "runs": {}}

    m0 = t3.load_metar(0)
    d0 = t3.daily(m0)
    rise0 = rise_dict(t3.remaining_rise_table(m0, d0))
    today0 = t3.pit_asof(snaps, m0, "today")

    # local_hour consistency with captured_at_utc + station tz
    cap = pd.to_datetime(snaps.captured_at_utc, utc=True)
    lh = np.array([c.tz_convert(ZoneInfo(t3.STATIONS[s]["tzname"])).hour for c, s in zip(cap, snaps.station)])
    ld = np.array([c.tz_convert(ZoneInfo(t3.STATIONS[s]["tzname"])).strftime("%Y-%m-%d") for c, s in zip(cap, snaps.station)])
    report["local_hour_mismatch"] = int((lh != snaps.local_hour.to_numpy()).sum())
    report["local_date_ne_target"] = int((ld != snaps.date.to_numpy()).sum())

    # empirical availability: METAR running max (lag 10) vs production's captured PIT obs
    j = snaps.set_index("row_key")[["high_so_far", "trusted_current_max", "floor", "local_hour", "block", "stratum"]].join(today0)
    j = j[j["cummax"].notna()]
    obs = j[["high_so_far", "trusted_current_max"]].max(axis=1)
    diff = (j["cummax"] - obs)
    by = {}
    for blk, g in j.assign(diff=diff).groupby("block"):
        gd = g["diff"].dropna()
        by[blk] = {"n": int(len(gd)), "mean": float(gd.mean()), "share_metar_gt_obs_ge1": float((gd >= 1).mean()),
                   "share_metar_gt_obs_ge2": float((gd >= 2).mean()),
                   "share_metar_gt_floor_ge1": float(((g["cummax"] - g["floor"]) >= 1).mean())}
    report["metar_runmax_minus_captured_obs"] = by

    # same with serve-time lag +60: does the excess shrink? (a pure-lag signature)
    for L in (0, 60, 120):
        mL = t3.load_metar(L)
        todayL = t3.pit_asof(snaps, mL, "today")
        # serve-only: table at registered basis
        cand_s = r3_candidate(snaps, bands, rise0, todayL)
        res_s = h.score(cand_s, name=f"r3_serve_only_plus{L}")
        assert res_s["rows_with_target_after_2026_09_29"] == 0
        h.save(res_s, OUT)
        report["runs"][f"serve_only_+{L}"] = {"summary": summarise(res_s), "leak": res_s["leakage_suspect_groups"],
                                              "n_rows": int(cand_s.row_key.nunique())}
        if L:
            riseL = rise_dict(t3.remaining_rise_table(mL, t3.daily(mL)))
            cand_b = r3_candidate(snaps, bands, riseL, todayL)
            res_b = h.score(cand_b, name=f"r3_both_plus{L}")
            assert res_b["rows_with_target_after_2026_09_29"] == 0
            h.save(res_b, OUT)
            report["runs"][f"both_+{L}"] = {"summary": summarise(res_b), "leak": res_b["leakage_suspect_groups"],
                                            "n_rows": int(cand_b.row_key.nunique())}
        print(L, "done", flush=True)
    (OUT / "result.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
