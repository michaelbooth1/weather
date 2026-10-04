"""R-PIT-T4: PIT/leakage refuter for the T4 obs-trend nowcast (model-parity swarm v2, development only).

Reuses the T4 module (no re-implementation of the rule, no new registered rules). Diagnostics only:
  A. Availability shifted +1 h and +2 h (EXTRA_LAG_MIN = 50 / 110 on top of A-IEM's +10 min), history
     grid and snapshots alike, exactly as t4-d1 did at +30 min. Scores t4-r1 and t4-r3 (w = 0.8 fixed).
  B. Serve-only shift +1 h (history fitted at +10 min, snapshots at +60 min): the case where the model
     was fitted assuming a 10-min feed but the real feed is an hour late.
  C. Availability cross-check against production's own capture: the candidate's METAR running max M at
     each covered snapshot vs the captured floor (max of guidance_physical_floor, high_so_far,
     trusted_current_max). Where M > captured floor the candidate "knew" a higher running max than
     production had captured at that moment. r3 is re-scored on the two sub-populations.
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-pit-t4_refute   (module name has a
dash, so run it as a script: <repo python> tools\\research\\model_parity\\r-pit-t4_refute.py)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t4_obs_trend_nowcast as t4  # noqa: E402

OUT = Path(r"C:\swarm\out\refute-pit-t4")
STOP = Path(r"C:\swarm\STOP")
W_FIXED = 0.8


def stop_check():
    if STOP.exists():
        sys.exit("STOP present")


def classes(res):
    out = {}
    for g, c in res["classes"].items():
        k = c.get("conditions", {})
        out[g] = {"class": c["class"], "from": k.get("strata_estimates", {}).get("from_20260823"),
                  "before": k.get("strata_estimates", {}).get("before_20260823"),
                  "ci_from": h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]["ci95"]
                  if h.table_lookup(res, g, "from_20260823", "all_row").get("status") != "NO_DATA" else None,
                  "markets_negative_from": k.get("markets_negative_from")}
    return out


def build_and_score(tag, lag_extra, serve_only=False):
    """Build r1 and r3 (w fixed) under an extra availability lag; return results + features."""
    stop_check()
    t4.EXTRA_LAG_MIN = lag_extra
    orig_hg = t4.history_grid
    if serve_only:
        def hg(*a, **k):
            saved = t4.EXTRA_LAG_MIN
            t4.EXTRA_LAG_MIN = 0
            try:
                return orig_hg(*a, **k)
            finally:
                t4.EXTRA_LAG_MIN = saved
        t4.history_grid = hg
    try:
        t0 = time.time()
        snaps, bands, feat, preds, _ = t4.build({"t4-r1": t4.LEVELS_FULL})
    finally:
        t4.history_grid = orig_hg
        t4.EXTRA_LAG_MIN = 0
    c1, cov = t4.candidates(snaps, bands, feat, preds)["t4-r1"]
    ps = bands.set_index(["row_key", "band_index"]).p_served
    sp = ps.reindex(pd.MultiIndex.from_frame(c1[["row_key", "band_index"]])).to_numpy()
    c3 = c1.assign(p=W_FIXED * c1.p.to_numpy() + (1 - W_FIXED) * sp)
    r1 = h.score(c1, name=f"rpit_t4_r1_{tag}")
    r3 = h.score(c3, name=f"rpit_t4_r3_{tag}")
    for r in (r1, r3):
        h.save(r, OUT)
        assert r["rows_with_target_after_2026_09_29"] == 0
        assert r["max_target_date"] <= "2026-09-29"
    print(f"[{tag}] built+scored in {time.time() - t0:.0f}s; r1 reasons {r1['reason_counts']}; "
          f"suspects r1={r1['leakage_suspect_groups']} r3={r3['leakage_suspect_groups']}", flush=True)
    return {"r1": classes(r1), "r3": classes(r3), "reasons_r1": r1["reason_counts"],
            "leakage_suspects": {"r1": r1["leakage_suspect_groups"], "r3": r3["leakage_suspect_groups"]},
            "coverage_by_block": pd.Series(cov).groupby(snaps.block.to_numpy()).mean().to_dict()}, \
        (snaps, bands, feat, c1, c3, cov)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"HARNESS_SHA256": h.harness_sha256(), "development": True, "w_fixed": W_FIXED}

    # Baseline (lag +10 only) to reproduce T4 and to build the availability cross-check.
    base, (snaps, bands, feat, c1, c3, cov) = build_and_score("lag10_repro", 0)
    summary["lag10_repro"] = base

    # C. candidate running max vs production's captured floor
    M = feat.runmax.to_numpy(float)
    fl = snaps.floor.to_numpy(float)
    hsf = snaps.high_so_far.to_numpy(float)
    tcm = snaps.trusted_current_max.to_numpy(float)
    gpf = snaps.guidance_physical_floor.to_numpy(float)
    covered = cov & np.isfinite(fl)
    diff = M - fl
    tab = {}
    blocks = snaps.block.to_numpy()
    for b in ["00-05", "06-09", "10-12", "13-16", "17-23", "all"]:
        sel = covered if b == "all" else covered & (blocks == b)
        d = diff[sel]
        tab[b] = {"covered_snapshots": int(sel.sum()),
                  "share_M_gt_floor_by_1F_or_more": float((d >= 1).mean()),
                  "share_M_gt_floor_by_2F_or_more": float((d >= 2).mean()),
                  "share_M_above_floor_bucket": float((M[sel] > np.floor(fl[sel] + .5)).mean()),
                  "share_M_lt_floor_by_1F_or_more": float((d <= -1).mean()),
                  "mean_M_minus_floor": float(d.mean()),
                  "share_hsf_missing": float(np.isnan(hsf[sel]).mean()),
                  "share_tcm_missing": float(np.isnan(tcm[sel]).mean()),
                  "share_M_gt_max(hsf,tcm)_by_1F": float((M[sel] - np.fmax(hsf[sel], tcm[sel]) >= 1).mean())}
    summary["running_max_vs_captured_floor"] = tab
    # r3 split: snapshots where M <= captured floor bucket vs M > captured floor bucket
    gt = covered & (M > np.floor(fl + .5))
    le = covered & ~(M > np.floor(fl + .5))
    keys_gt = set(snaps.row_key.to_numpy()[gt])
    keys_le = set(snaps.row_key.to_numpy()[le])
    r3_le = h.score(c3, name="rpit_t4_r3_M_le_floor", where=lambda s: s.row_key.isin(keys_le))
    r3_gt = h.score(c3, name="rpit_t4_r3_M_gt_floor", where=lambda s: s.row_key.isin(keys_gt))
    h.save(r3_le, OUT)
    h.save(r3_gt, OUT)
    summary["r3_split_M_le_floor"] = {"snapshots": r3_le["scored_snapshots"], **classes(r3_le)}
    summary["r3_split_M_gt_floor"] = {"snapshots": r3_gt["scored_snapshots"], **classes(r3_gt)}
    print("split done", flush=True)

    # A. +1 h and +2 h, train and serve alike
    for tag, extra in (("lag60", 50), ("lag120", 110)):
        res, _ = build_and_score(tag, extra)
        summary[tag] = res
    # B. serve-only +1 h
    res, _ = build_and_score("lag60_serve_only", 50, serve_only=True)
    summary["lag60_serve_only"] = res

    (OUT / "rpit_t4_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    for tag in ("lag10_repro", "lag60", "lag120", "lag60_serve_only"):
        print(f"\n== {tag} ==")
        for rule in ("r1", "r3"):
            for g in ("10-12", "13-16", "17-23", "00-16"):
                c = summary[tag][rule][g]
                print(f"  {rule} {g}: {c['class']} from {c['from']:+.6f} ci {c['ci_from']} before {c['before']:+.6f} "
                      f"mkts {c['markets_negative_from']}")
    print("\n== r3 split ==")
    for k in ("r3_split_M_le_floor", "r3_split_M_gt_floor"):
        print(k, summary[k]["snapshots"])
        for g in ("13-16", "17-23", "00-16"):
            c = summary[k][g]
            print(f"  {g}: {c['class']} from {c['from']} ci {c['ci_from']} before {c['before']} mkts {c['markets_negative_from']}")
    print("\n== M vs captured floor ==")
    print(json.dumps(tab, indent=1))


if __name__ == "__main__":
    main()
