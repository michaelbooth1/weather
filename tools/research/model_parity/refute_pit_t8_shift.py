"""R-PIT-T8 refuter: re-run T8 candidates with HRRR availability shifted +1 h and +2 h (development only).

No new rules are registered. Reuses t8_hrrr_latest functions unchanged (imported, not edited).
Variants per delay D in {3 (reproduction), 4 (+1 h), 5 (+2 h)}:
  frozen: parameters fitted by T8 at the design delay (3 h), as T8's own d1 diagnostic did;
  refit:  parameters re-fitted with the shifted availability (the fit's run selection also shifts).
Rules scored: t8-r1, t8-r2, t8-r3, t8-r4, t8-c1, t8-c2 (controls carry the same shifted coverage mask).
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.refute_pit_t8_shift
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from tools.research.model_parity import harness as h
from tools.research.model_parity import t8_hrrr_latest as t8
from tools.research.model_parity import t6_nbs_controls as t6c

OUT = Path(r"C:\swarm\out\refute-pit-t8")
STOP = Path(r"C:\swarm\STOP")
GROUPS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def brief(res):
    out = {}
    for g in GROUPS:
        c = res["classes"].get(g, {})
        t = h.table_lookup(res, g, "from_20260823", "all_row")
        tb = h.table_lookup(res, g, "before_20260823", "all_row")
        cs = t["candidate_minus_served"]
        pm = t.get("per_market_delta") or {}
        vals = [v.get("estimate", v) if isinstance(v, dict) else v for v in pm.values()]
        out[g] = {"class": c.get("class"), "from": cs.get("estimate"), "ci95": cs.get("ci95"),
                  "before": tb["candidate_minus_served"].get("estimate"),
                  "markets_neg": int(sum(1 for v in vals if v is not None and v < 0))}
    return out


def main():
    if STOP.exists():
        sys.exit("STOP present")
    OUT.mkdir(parents=True, exist_ok=True)
    log("HARNESS", h.harness_sha256())
    s, bands = t8.snapshot_frame()
    metar = t8.load_metar_fit()
    results = {"HARNESS_SHA256": h.harness_sha256(), "runs": {}}
    idx3 = t8.load_hrrr(3)
    params3, _ = t8.fit_all(idx3, metar)
    d = h.data()
    for delay in (3, 4, 5):
        if STOP.exists():
            sys.exit("STOP present")
        idx = idx3 if delay == 3 else t8.load_hrrr(delay)
        variants = [("frozen", params3)]
        if delay != 3:
            pr, fs = t8.fit_all(idx, metar)
            variants.append(("refit", pr))
            results.setdefault("refit_params", {})[delay] = {k: {str(kk): vv for kk, vv in v.items()}
                                                            for k, v in pr.items()}
        for vname, params in variants:
            frames = {}
            for rule in ("r1", "r2", "r3", "r4", "c1", "c2"):
                if vname == "refit" and rule == "r1":
                    continue  # r1 has no fitted parameters; identical to frozen
                prm = params.get("r2") if rule == "c2" else params.get(rule)
                cand, reasons = t8.build_candidate(rule, idx, s, bands, prm)   # asserts rule 1 inside
                name = f"rpit_t8_{rule}_d{delay}_{vname}"
                res = h.score(cand, name=name)
                assert res["rows_with_target_after_2026_09_29"] == 0
                if res.get("leakage_suspect_groups"):
                    STOP.write_text(f"refute-pit-t8 leakage suspect {name} {res['leakage_suspect_groups']}\n")
                    sys.exit("leakage suspect")
                h.save(res, OUT)
                results["runs"][name] = {"reasons": reasons, "blocks": brief(res)}
                frames[f"t8-{rule}"] = h._candidate_vector(cand, d, False)[0]
                b = results["runs"][name]["blocks"]
                log(name, {g: (b[g]["class"], round(b[g]["from"], 4)) for g in ("06-09", "17-23")})
            pairs = [("t8-r2", "t8-c2"), ("t8-r1", "t8-c1"), ("t8-r2", "t8-c1")]
            pairs = [p for p in pairs if p[0] in frames and p[1] in frames]
            if vname == "refit":
                pairs = [p for p in pairs if p[0] != "t8-r1"]
            pr_ = t6c.paired(d, frames, pairs)
            results["runs"][f"paired_d{delay}_{vname}"] = {
                k: {g: v[f"{g}|from_20260823"] for g in ("06-09", "13-16", "17-23", "00-16")}
                for k, v in pr_.items()}
    (OUT / "shift_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
