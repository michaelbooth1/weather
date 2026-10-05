"""R-PIT-T6: PIT/leakage refuter for T6 (NBS latest cycle). Development only; registers no rules.

Re-runs t6-r1/r2/r3 and controls t6-c1/c2 through the harness with every NBS object's availability
shifted +0 / +60 / +120 minutes after its measured S3 LastModified (r3 parameters frozen at the +0 fit,
which uses only history <= 2026-07-31). Imports the hunter's code unchanged.
Run: cd C:\\pt\\swarm; <repo python> tools\\research\\model_parity\\r-pit-t6_shift.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h  # noqa: E402
from tools.research.model_parity import t6_nbs_latest as t6  # noqa: E402
from tools.research.model_parity import t6_nbs_controls as t6c  # noqa: E402

OUT = Path(r"C:\swarm\out\refute-pit-t6")
GROUPS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


def brief(res):
    o = {}
    for g in GROUPS:
        t = h.table_lookup(res, g, "from_20260823", "all_row")
        tb = h.table_lookup(res, g, "before_20260823", "all_row")
        c = t["candidate_minus_served"]
        o[g] = {"class": res["classes"][g]["class"], "est": c["estimate"], "ci95": c["ci95"],
                "before": tb["candidate_minus_served"]["estimate"],
                "mkts_neg": t.get("markets_negative")}
    return o


def main():
    stop()
    OUT.mkdir(parents=True, exist_ok=True)
    assert h.harness_sha256() == "8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74"
    s, bands = t6.snapshot_frame()
    snaps_full, _ = h.candidate_inputs()
    assert (snaps_full.row_key.to_numpy() == s.row_key.to_numpy()).all()
    assert (s.date <= "2026-09-29").all()
    cyc0, _ = t6.load_cycles(0)
    params, _ = t6.fit_r3(cyc0)
    print("r3 params (frozen)", params, flush=True)
    summary = {"HARNESS_SHA256": h.harness_sha256(), "r3_params": {k: list(v) for k, v in params.items()},
               "runs": {}}
    for lag in (0, 60, 120):
        stop()
        cyc = cyc0 if lag == 0 else t6.load_cycles(lag)[0]
        cands = {}
        for rid, rule, prm in (("t6-r1", "r1", None), ("t6-r2", "r2", None), ("t6-r3", "r2", params)):
            cand, modes, ages = t6.build_candidate(rule, cyc, s, bands, prm)
            npit = t6.full_pit_check(cyc, s, rule)
            cands[rid] = (cand, modes, ages, npit)
        ctl, cmodes = t6c.build_controls(cyc, s, bands, snaps_full)
        cands["t6-c1"] = (ctl["t6-c1"], cmodes, None, None)
        cands["t6-c2"] = (ctl["t6-c2"], cmodes, None, None)
        for rid, (cand, modes, ages, npit) in cands.items():
            res = h.score(cand, name=f"rpit_t6_{rid.replace('-', '_')}_plus{lag}")
            assert res["rows_with_target_after_2026_09_29"] == 0
            if res["leakage_suspect_groups"]:
                Path(r"C:\swarm\STOP").write_text(f"r-pit-t6 leakage suspect {rid} {res['leakage_suspect_groups']}\n")
                sys.exit("leakage suspect")
            h.save(res, OUT)
            rec = {"tables": brief(res), "covered_snapshots": int(cand.row_key.nunique()),
                   "modes": {k: int(v) for k, v in pd.Series(modes).value_counts().items()},
                   "pit_checked": npit}
            if ages is not None:
                rec["median_age_h_by_block"] = pd.Series(ages).groupby(s.block.to_numpy()).median().round(2).to_dict()
            summary["runs"][f"{rid}|+{lag}"] = rec
            print(lag, rid, {g: (v["class"], round(v["est"], 5), v["mkts_neg"]) for g, v in rec["tables"].items()},
                  flush=True)
    (OUT / "rpit_t6_shift.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
