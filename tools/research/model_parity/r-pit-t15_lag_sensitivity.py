"""R-PIT-T15: PIT/leakage refuter sensitivity for T15 (development only; no new registered rules).

Re-runs the registered t15-r1/r2/r3 procedures (imported unchanged from t15_diurnal_projection) with
the METAR availability lag shifted from valid+10 min to valid+70 min (+1 h) and valid+130 min (+2 h),
and with temperature variants (tmpf as served by IEM; integer-rounded T-group F; body-integer C -> F).
For the Normal rule the registered sigma procedure is re-run under each perturbation (refit on the
before stratum), and a stress variant keeps the original 0-lag sigmas fixed.
Also checks the METAR running max at t against production-captured high_so_far/trusted_current_max.

Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-pit-t15_lag_sensitivity
(module name has a hyphen, so run via runpy: python -c "import runpy; runpy.run_path(...)")
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h
from tools.research.model_parity import t15_diurnal_projection as t15

OUT = Path(r"C:\swarm\out\refute-pit-t15")
ORIG_LOAD = t15.load_metar
BLOCKS = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all"]


def make_loader(lag_min=0, temp="tmpf"):
    def load(station):
        m = pd.read_parquet(t15.METAR / f"{station}.parquet",
                            columns=["tmpf", "tgroup_f", "main_temp_c", "valid_utc", "available_utc",
                                     "local_time", "local_date", "is_cor"])
        if temp == "tgroup_round":
            m["tmpf"] = np.where(m.tgroup_f.notna(), np.round(m.tgroup_f), np.round(m.tmpf))
        elif temp == "body_int":
            m["tmpf"] = np.where(m.main_temp_c.notna(), np.round(m.main_temp_c * 1.8 + 32), np.nan)
        m = m[~m.is_cor & m.tmpf.notna()].copy()
        m["available_utc"] = m["available_utc"] + pd.Timedelta(minutes=lag_min)
        m["local_date"] = m.local_date.astype(str)
        lt = m.local_time.astype(str)
        m["bin"] = lt.str[11:13].astype(int) * 2 + (lt.str[14:16].astype(int) >= 30).astype(int)
        return m[["tmpf", "valid_utc", "available_utc", "local_time", "local_date", "is_cor", "bin"]] \
            .sort_values("valid_utc").reset_index(drop=True)
    return load


def summarize(res):
    out = {}
    for g in BLOCKS:
        t = h.table_lookup(res, g, "from_20260823", "all_row")
        tb = h.table_lookup(res, g, "before_20260823", "all_row")
        cs = t["candidate_minus_served"]
        pm = t["per_market_delta"]
        vals = list(pm.values()) if isinstance(pm, dict) else [x.get("delta") if isinstance(x, dict) else x for x in pm]
        out[g] = {"from": [round(cs["estimate"], 5)] + [round(x, 5) for x in cs["ci95"]],
                  "before": round(tb["candidate_minus_served"]["estimate"], 5),
                  "cand_minus_market_from": round(t["candidate_minus_market"]["estimate"], 5),
                  "mkts_neg": int(sum(1 for v in vals if v is not None and v < 0)),
                  "class": res["classes"].get(g, {}).get("class")}
    return out


def run_variant(snaps, bands, lab, lag, temp, fixed_sigma=None):
    t15.load_metar = make_loader(lag, temp)
    try:
        feats, _ = t15.obs_features(snaps)
    finally:
        t15.load_metar = ORIG_LOAD
    results = {}
    for rid, (gcol, mode) in t15.RULES.items():
        if rid == "t15-r4":
            continue
        f = t15.projection(snaps, feats, gcol)
        cov = f.P.notna()
        sig = None
        sigd = None
        if mode == "normal":
            fb = f[cov & (f.stratum == "before_20260823")].copy()
            fb["y"] = lab.reindex(fb.row_key.to_numpy()).to_numpy()
            fb = fb[fb.y.notna()]
            sig_block = fb.groupby("block").apply(lambda x: float(np.sqrt(np.mean((x.y - x.P) ** 2))))
            if fixed_sigma is not None:
                sig_block = pd.Series(fixed_sigma)
            sigd = sig_block.round(3).to_dict()
            sig = pd.Series(f.block.map(sig_block).to_numpy(), index=f.row_key.to_numpy())[cov.to_numpy()]
        P_by_key = pd.Series(f.P.to_numpy(), index=f.row_key.to_numpy())[cov.to_numpy()]
        cand = t15.candidates(bands, P_by_key, mode, sig)
        name = f"rpit_{rid.replace('-', '_')}_lag{lag}_{temp}" + ("_fixsig" if fixed_sigma else "")
        res = h.score(cand, name=name)
        h.save(res, OUT)
        results[rid] = {"coverage": int(cov.sum()), "sigma": sigd, "blocks": summarize(res),
                        "leakage_suspect_groups": res.get("leakage_suspect_groups"),
                        "harness": res.get("HARNESS_SHA256") or h.harness_sha256()}
        print(name, json.dumps(results[rid]["blocks"]["17-23"]), sigd, flush=True)
    return results, feats


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps, bands = h.candidate_inputs()
    assert (snaps.date > "2026-09-29").sum() == 0
    lab = t15.before_labels()
    allres = {"HARNESS_SHA256": h.harness_sha256(), "variants": {}}
    base, feats0 = run_variant(snaps, bands, lab, 0, "tmpf")
    allres["variants"]["lag0_tmpf"] = base
    sig0 = base["t15-r2"]["sigma"]
    # captured-floor cross-check (production-captured at t vs METAR running max at t)
    f = snaps[["row_key", "block", "high_so_far", "trusted_current_max", "local_hour"]].merge(feats0, on="row_key")
    cap = np.fmax(f.high_so_far.to_numpy(float), f.trusted_current_max.to_numpy(float))
    d = f.mmax.to_numpy() - cap
    ok = ~np.isnan(d)
    chk = {}
    for b in ["00-05", "06-09", "10-12", "13-16", "17-23"]:
        s = ok & (f.block.to_numpy() == b)
        chk[b] = {"n": int(s.sum()), "mean_metar_minus_captured": round(float(np.mean(d[s])), 3),
                  "share_metar_gt_captured_ge1F": round(float(np.mean(d[s] >= 1)), 4),
                  "share_metar_gt_captured_ge2F": round(float(np.mean(d[s] >= 2)), 4)}
    allres["captured_vs_metar_runmax"] = chk
    print(json.dumps(chk), flush=True)
    for lag in (60, 120):
        r, _ = run_variant(snaps, bands, lab, lag, "tmpf")
        allres["variants"][f"lag{lag}_tmpf"] = r
        r, _ = run_variant(snaps, bands, lab, lag, "tmpf", fixed_sigma=sig0)
        allres["variants"][f"lag{lag}_tmpf_fixsig0"] = {"t15-r2": r["t15-r2"]}
    for temp in ("tgroup_round", "body_int"):
        r, _ = run_variant(snaps, bands, lab, 0, temp)
        allres["variants"][f"lag0_{temp}"] = r
    (OUT / "rpit_t15_sensitivity.json").write_text(json.dumps(allres, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
