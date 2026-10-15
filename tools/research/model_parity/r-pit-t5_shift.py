"""R-PIT-T5 refuter (model-parity swarm v2, development only). No new rules registered.

Re-scores registered candidate t5-r1 (imported unchanged from t5_nbh_latest) with every NBH object's
availability shifted +0/+60/+120 min after its S3 LastModified, plus two labelled diagnostics:
  diag_collapse_1723: pure floor collapse (all mass on the floor band) on the rows t5-r1 covers
                      in 17-23, served elsewhere -> is the 17-23 effect NBH skill or the T1/T2 mechanism?
  diag_r1_only_0016 : t5-r1 restricted to 00-16 rows (17-23 served) for a clean 00-16 read.
Run: cd C:\pt\swarm; <repo python> tools\research\model_parity\r-pit-t5_shift.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h
from tools.research.model_parity import t5_nbh_latest as t5

OUT = Path(r"C:\swarm\out\refute-pit-t5")
GROUPS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")


def brief(res):
    o = {}
    for g in GROUPS:
        c = res["classes"][g]
        t = h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]
        tb = h.table_lookup(res, g, "before_20260823", "all_row")["candidate_minus_served"]
        o[g] = {"class": c["class"], "from_est": t["estimate"], "from_ci95": t["ci95"],
                "before_est": tb["estimate"], "markets_neg": c.get("markets_negative", c.get("markets"))}
    return o


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s, bands = t5.snapshot_frame()
    assert (s.date <= "2026-09-29").all()
    results = {"HARNESS_SHA256": h.harness_sha256()}
    stats = {}
    for lag in (0, 60, 120):
        idx = t5.load_nbh(extra_lag_min=lag)
        cand, ages, mus, reasons = t5.build_candidate(idx, s, bands, None)
        res = h.score(cand, name=f"rpit_t5_r1_plus{lag}")
        assert not res.get("leakage_suspect_groups"), res.get("leakage_suspect_groups")
        h.save(res, OUT)
        results[f"plus{lag}"] = {"reasons": reasons, "summary": brief(res),
                                 "median_age_h": pd.Series(ages).groupby(s.block.values).median().round(2).to_dict()}
        print(lag, json.dumps(results[f"plus{lag}"]["summary"]), flush=True)
        if lag == 0:
            base_cand, base_mus = cand, mus
    # diagnostics on the +0 coverage
    blk = s.block.to_numpy()
    covered_rows = set(base_cand.row_key.unique())
    # how often NBH remaining max is below the floor in 17-23
    F = s.floor.to_numpy(float)
    B = np.floor(F + .5)
    m1723 = (blk == "17-23") & np.isfinite(base_mus)
    stats["share_17_23_mu_below_B"] = float(np.mean(base_mus[m1723] < B[m1723]))
    stats["share_17_23_mu_below_B_minus2"] = float(np.mean(base_mus[m1723] < B[m1723] - 2))
    for b in ("00-05", "06-09", "10-12", "13-16"):
        mm = (blk == b) & np.isfinite(base_mus)
        stats[f"share_{b}_mu_below_B"] = float(np.mean(base_mus[mm] < B[mm]))
    # pure collapse candidate in 17-23 (same covered rows)
    rk1723 = set(s.row_key[(blk == "17-23")]) & covered_rows
    bb = bands[bands.row_key.isin(rk1723)].merge(s[["row_key", "floor"]], on="row_key")
    Bb = np.floor(bb.floor.to_numpy(float) + .5)
    kind, lo, hi = bb.kind.to_numpy(), bb.low.to_numpy(float), bb.high.to_numpy(float)
    inb = ((kind == "lte") & (Bb <= hi)) | ((kind == "gte") & (Bb >= lo)) | ((kind != "lte") & (kind != "gte") & (Bb >= lo) & (Bb <= hi))
    bb["p"] = inb.astype(float)
    ok = bb.groupby("row_key").p.transform("sum") > 0
    coll = bb.loc[ok, ["row_key", "band_index", "p"]]
    res = h.score(coll, name="rpit_t5_diag_collapse_1723")
    h.save(res, OUT)
    results["diag_collapse_1723"] = {"summary": brief(res), "rows": int(coll.row_key.nunique())}
    # r1 restricted to 17-23 (same rows) for the side-by-side
    r1_1723 = base_cand[base_cand.row_key.isin(set(coll.row_key))]
    res = h.score(r1_1723, name="rpit_t5_r1_only_1723_samerows")
    h.save(res, OUT)
    results["r1_only_1723_samerows"] = {"summary": brief(res)}
    # r1 restricted to 00-16
    rk0016 = set(s.row_key[np.isin(blk, ["00-05", "06-09", "10-12", "13-16"])])
    res = h.score(base_cand[base_cand.row_key.isin(rk0016)], name="rpit_t5_r1_only_0016")
    h.save(res, OUT)
    results["r1_only_0016"] = {"summary": brief(res)}
    results["stats"] = stats
    (OUT / "rpit_t5_results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: results[k] for k in ("diag_collapse_1723", "r1_only_1723_samerows", "stats")}, default=str))


if __name__ == "__main__":
    main()
