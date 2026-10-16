"""R-PIT-T10: PIT/leakage refuter for T10 (ECMWF IFS). Development only. No new rules registered.

Re-runs registered rule t10-r2 (and control t10-c1 for the paired increment) through the harness with the IFS
availability shifted by +0, +60 and +120 minutes beyond the measured per-object S3 LastModified, in two forms:
  frozen : b, s fitted once at +0 (as T10 shipped), applied to the shifted availability
  refit  : b, s refitted on the history with the same shifted availability (rule text applied consistently)
Imports T10's own functions unchanged (t10_ecmwf_ifs.py), so this is a re-run, not a re-implementation.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r_pit_t10_shift
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from tools.research.model_parity import harness as h
from tools.research.model_parity import t10_ecmwf_ifs as t10

OUT = Path(r"C:\swarm\out\refute-pit-t10")
BLKS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    s, bands = t10.snapshot_frame()
    base_idx = t10.load_ifs("measured", 0)
    base_params, _ = t10.fit(base_idx)
    d = h.data()
    out = {"HARNESS_SHA256": h.harness_sha256(), "base_params_r2": base_params["r2"], "runs": {}}
    for lag in (0, 60, 120):
        if Path(r"C:\swarm\STOP").exists():
            sys.exit("STOP present")
        idx = t10.load_ifs("measured", lag)
        p_refit, _ = t10.fit(idx)
        forms = {"frozen": base_params, "refit": p_refit} if lag else {"frozen": base_params}
        for form, params in forms.items():
            tag = f"lag{lag}_{form}"
            cand, cov, ages, _, reasons = t10.build(idx, s, bands, "mix", params["r2"], None)
            c1, _, _, _, _ = t10.build(idx, s, bands, "mix", params["c1"], "c1", cov)
            res = h.score(cand, name=f"rpit_t10_r2_{tag}")
            assert res["rows_with_target_after_2026_09_29"] == 0
            if res.get("leakage_suspect_groups"):
                Path(r"C:\swarm\STOP").write_text(f"r-pit-t10 leakage suspect {tag} {res['leakage_suspect_groups']}\n")
                sys.exit("leakage")
            h.save(res, OUT)
            fr = {"r2": h._candidate_vector(cand, d, False)[0], "c1": h._candidate_vector(c1, d, False)[0]}
            pr = t10.paired(d, fr, [("r2", "c1")])["r2 - c1"]
            rec = {"params_r2": params["r2"], "reasons": reasons,
                   "coverage": float(cov.mean()),
                   "median_age_h": {b: float(np.nanmedian(ages[s.block.to_numpy() == b])) for b in t10.BLOCKS},
                   "blocks": {}}
            for g in BLKS:
                t = h.table_lookup(res, g, t10.FROM, "all_row")
                tb = h.table_lookup(res, g, t10.BEFORE, "all_row")
                cs = t["candidate_minus_served"]
                pm = t.get("per_market_delta") or {}
                vals = [v.get("estimate", v) if isinstance(v, dict) else v for v in pm.values()]
                rec["blocks"][g] = {"class": res["classes"].get(g, {}).get("class"),
                                    "from": cs["estimate"], "ci95": cs["ci95"],
                                    "before": tb["candidate_minus_served"]["estimate"],
                                    "mkts_neg": int(sum(1 for v in vals if v is not None and v < 0)),
                                    "r2_minus_c1_from": pr[f"{g}|{t10.FROM}"]["estimate"],
                                    "r2_minus_c1_ci95": pr[f"{g}|{t10.FROM}"]["ci95"]}
            out["runs"][tag] = rec
            print(tag, f"cov={rec['coverage']:.4f}")
            for g, v in rec["blocks"].items():
                print(f"  {g:6s} {v['class']:5s} from {v['from']:+.6f} [{v['ci95'][0]:+.6f},{v['ci95'][1]:+.6f}] "
                      f"before {v['before']:+.6f} neg {v['mkts_neg']}/11  r2-c1 {v['r2_minus_c1_from']:+.6f} "
                      f"[{v['r2_minus_c1_ci95'][0]:+.6f},{v['r2_minus_c1_ci95'][1]:+.6f}]", flush=True)
    (OUT / "shift_results.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
