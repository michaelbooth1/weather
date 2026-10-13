"""T18 attribution control t18-c1 (rung x v2_mean only) and PIT sensitivity t18-r1s (+60 min on captured sources).

Both registered in C:\swarm\registry.jsonl before this script's first score. Development only.
Run: cd C:\pt\swarm; <repo python> -m tools.research.model_parity.t18_controls
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t18_emos as t

REG_IDS = ("t18-c1", "t18-r1s")


def main():
    rows = [json.loads(x) for x in t.REGISTRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert all(any(r["id"] == i and r["agent"] == "t18" for r in rows) for i in REG_IDS)
    run = json.loads((t.OUT / "t18_run.json").read_text(encoding="utf-8"))
    chosen = run["chosen"]
    th1 = np.r_[run["theta_r1"]["a"], [run["theta_r1"][f"b_{k}"] for k in chosen], np.log(run["theta_r1"]["sigma"])]
    s, bands, prior, src, meta = t.build_inputs()
    cov = s.covered.to_numpy()
    tr = cov & (s.stratum == t.BEFORE).to_numpy() & s.Y.notna().to_numpy()
    eobs = np.minimum((s.Y.to_numpy()[tr] - s.R.to_numpy()[tr]).astype(int), t.G - 1)
    mtr = t.Model(s, prior, src, tr)
    th0, nll0, _ = t.fit(mtr, eobs, [])
    thc1, nllc1, ok = t.fit(mtr, eobs, ["v2_mean"], np.r_[th0[0], 0.0, th0[-1]])
    t.log("c1", thc1, nllc1, ok)
    # r1s: sources shifted +60 min
    cap = pd.to_datetime(s.captured_at_utc, utc=True)
    lag = pd.Timedelta(minutes=60)
    src_s = dict(src)
    for col, av in (("v2_mean", "v2_available_at"), ("hrrr_high", "hrrr_fetched_at")):
        a = pd.to_datetime(s[av], utc=True, errors="coerce") + lag
        use = np.isfinite(src[col]) & (a <= cap).to_numpy()
        h.assert_point_in_time(a[use], cap[use])
        src_s[col] = np.where(use, src[col], np.nan)
    src_s["forecast_high"] = np.full(len(s), np.nan)
    lost = {k: int(np.isfinite(src[k]).sum() - np.isfinite(src_s[k]).sum()) for k in chosen}
    mall = t.Model(s, prior, src, cov)
    malls = t.Model(s, prior, src_s, cov)
    G = t.G
    pmr1 = np.full((len(s), G), np.nan); pmc1 = pmr1.copy(); pms = pmr1.copy(); pmr = pmr1.copy()
    pmr1[cov] = mall.pmf(th1, chosen)
    pmc1[cov] = mall.pmf(thc1, ["v2_mean"])
    pms[cov] = malls.pmf(th1, chosen)
    pmr[cov] = prior[cov]
    cands = {"t18-r1": t.to_bands(s, bands, pmr1, cov), "t18-c1": t.to_bands(s, bands, pmc1, cov),
             "t18-r1s": t.to_bands(s, bands, pms, cov), "t3-r3": t.to_bands(s, bands, pmr, cov)}
    names = {"t18-c1": "t18_c1_rung_x_v2", "t18-r1s": "t18_r1s_sources_lag60"}
    out = {"HARNESS_SHA256": h.harness_sha256(), "theta_c1": {"a": thc1[0], "b_v2_mean": thc1[1],
           "sigma": float(np.exp(thc1[2]))}, "train_nll_c1": nllc1, "r1s_source_rows_lost": lost, "classes": {}}
    for k, nm in names.items():
        res = h.score(cands[k], name=nm)
        assert res["rows_with_target_after_2026_09_29"] == 0
        if res["leakage_suspect_groups"]:
            raise SystemExit("LEAKAGE SUSPECT " + nm)
        h.save(res, t.OUT)
        (t.OUT / f"{nm}.md").write_text(h.markdown(res), encoding="utf-8")
        out["classes"][k] = res["classes"]
        print(h.markdown(res))
    out["paired"] = t.paired(cands, list(cands), [("t18-r1", "t18-c1"), ("t18-c1", "t3-r3"),
                                                  ("t18-r1s", "t18-r1"), ("t18-r1s", "t3-r3")])
    (t.OUT / "t18_controls.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    t.log("done")


if __name__ == "__main__":
    main()
