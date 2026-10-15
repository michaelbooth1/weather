"""D3 d3-plan2: paired diagnostics and before-stratum power for the proposed pre-registered form RV-1
(= t18-c1 frozen constants). Registered in C:\\swarm\\registry.jsonl (agent d3) before running. Development only.
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.d3_plan2
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t3_baselines as t3
from tools.research.model_parity import t18_emos as t
from tools.research.model_parity import d3_t18_zero as z

OUT = Path(r"C:\swarm\out\d3")


def main():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")
    rows = [json.loads(x) for x in z.REG.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(r["id"] == "d3-plan2" and r["agent"] == "d3" for r in rows)
    s, bands, prior, src, meta = t.build_inputs()
    d = h.data()
    rise = z.rise_dict()
    ctl = json.loads(Path(r"C:\swarm\out\t18\t18_controls.json").read_text(encoding="utf-8"))
    th = np.r_[ctl["theta_c1"]["a"], ctl["theta_c1"]["b_v2_mean"], np.log(ctl["theta_c1"]["sigma"])]
    G = t.G

    def c1_cand(R, pr, cov, v2):
        s2 = s.copy(); s2["R"] = R
        m = t.Model(s2, pr, {"v2_mean": v2}, cov)
        pm = np.full((len(s), G), np.nan)
        pm[cov] = m.pmf(th, ["v2_mean"])
        return t.to_bands(s2, bands, pm, cov)

    R = s.R.to_numpy(float); cov = s.covered.to_numpy()
    cands = {"t18-c1": c1_cand(R, prior, cov, src["v2_mean"])}
    Rf = np.floor(s.floor.to_numpy(float) + 0.5)
    prf, covf = z.prior_for(s, Rf, rise)
    cands["c1-floor"] = c1_cand(Rf, prf, covf, src["v2_mean"])
    m60 = t3.load_metar(60)
    R60 = t3.pit_asof(s, m60, "today")["cummax"].reindex(s.row_key).to_numpy(float)
    pr60, cov60 = z.prior_for(s, R60, rise)
    mu60, _, _ = z.v2_pit(s, 60)
    cands["c1-lag60"] = c1_cand(R60, pr60, cov60, mu60)
    prr = np.full((len(s), G), np.nan); prr[cov] = prior[cov]
    cands["t3-r3"] = t.to_bands(s, bands, prr, cov)
    mu, sd, _ = z.v2_pit(s)
    cands["d3-z1"] = t.to_bands(s, bands, z.z_pmf(R, prior, cov, mu, sd), cov)
    snaps_h, bands_h = h.candidate_inputs()
    cands["mg1"] = z.mg1_candidate(snaps_h, bands_h, d)
    Bz = {k: z.snap_brier(v, d) for k, v in cands.items()}
    Bz["served"] = np.add.reduceat(d.se_served, d.offsets) / d.snaps.n_bands.to_numpy()
    Bz["ladder-r1"] = np.load(z.LADDER / "snapb_ladder-r1.npy")
    Bz["ladder-r2"] = np.load(z.LADDER / "snapb_ladder-r2.npy")
    pairs = [("t18-c1", "served"), ("t18-c1", "t3-r3"), ("t18-c1", "mg1"), ("t18-c1", "ladder-r1"),
             ("t18-c1", "ladder-r2"), ("d3-z1", "t18-c1"), ("c1-floor", "t18-c1"), ("c1-lag60", "t18-c1"),
             ("c1-lag60", "served"), ("c1-floor", "served")]
    pt = z.paired_tables(Bz, pairs, d)
    res = h.score(cands["t18-c1"], name="d3_rv1_t18c1_rescore")
    assert res["rows_with_target_after_2026_09_29"] == 0 and not res["leakage_suspect_groups"]
    h.save(res, OUT)
    tail = {g: res["tail"].get(g) for g in ("00-16", "17-23", "all")} if isinstance(res["tail"], dict) else res["tail"]
    pl = z.plan(Bz["t18-c1"] - Bz["served"], d)
    tabs = {g: {st: h.table_lookup(res, g, st, "all_row") for st in (z.FROM, z.BEFORE)}
            for g in ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")}
    out = {"agent": "d3", "HARNESS_SHA256": h.harness_sha256(), "theta_c1": ctl["theta_c1"],
           "coverage": {"c1": float(cov.mean()), "c1_floor": float(covf.mean()), "c1_lag60": float(cov60.mean())},
           "classes": res["classes"], "tables": tabs, "tail": tail, "paired": pt, "plan": pl}
    (OUT / "d3_plan2.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
