"""R-PIT-T1: PIT/leakage refuter for the T1 decided-band collapse (model-parity swarm v2, development only).

Imports the hunter's module unchanged (t1_decided_band.py, sha256 4a6aa874...) and the F1 harness.
1. Reproduces the baseline t1-r2 score (must equal the hunter's -0.026412 in 17-23 from-stratum).
2. Re-scores t1-r2 with every METAR/SPECI row available +60 and +120 min later than the hunter's
   basis (valid + 10 min), i.e. valid + 70 and valid + 130 min, plus the hunter's own +50 (= valid + 60).
3. Re-runs the fit stage into the refuter's directory and compares X, N, H and q with the hunter's
   fit_params.json (fitting-window reproduction).
4. Programmatic rule checks: forbidden tokens in the hunter's source, obs-parquet PIT, METAR date
   bounds, fitted window, candidate columns.
Nothing here registers a rule. Output: C:\\swarm\\out\\refute-pit-t1\\.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\pt\swarm")
from tools.research.model_parity import harness as h            # noqa: E402
from tools.research.model_parity import t1_decided_band as t1   # noqa: E402

OUT = Path(r"C:\swarm\out\refute-pit-t1")
OUT.mkdir(parents=True, exist_ok=True)
T1_OUT = Path(r"C:\swarm\out\t1")
STOP = Path(r"C:\swarm\STOP")


def check_stop():
    if STOP.exists():
        raise SystemExit("STOP present: " + STOP.read_text(encoding="utf-8", errors="replace"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pick(res, group, stratum="from_20260823", pop="all_row"):
    t = h.table_lookup(res, group, stratum, pop)
    d = t["candidate_minus_served"]
    return {"estimate": d["estimate"], "ci95": d["ci95"], "markets_negative": t["markets_negative"],
            "markets_positive": t["markets_positive"], "cand_minus_market": t["candidate_minus_market"]["estimate"],
            "gap_closed": t["gap_closed_share"]["estimate"], "market_days": t["market_days"]}


def main():
    check_stop()
    report = {"agent": "r-pit-t1", "development": True, "HARNESS_SHA256": h.harness_sha256(),
              "t1_code_sha256": sha(r"C:\pt\swarm\tools\research\model_parity\t1_decided_band.py")}
    params = json.loads((T1_OUT / "fit_params.json").read_text(encoding="utf-8"))

    # ---- 4a. forbidden tokens in the hunter's source (rules 2/3)
    src = Path(t1.__file__).read_text(encoding="utf-8")
    tokens = ["winner", "settlement", "p_market", "best_bid", "best_ask", "market_mid", "is_winner", "data()", "d.y", "se_market"]
    found = {tok: [m.start() for m in re.finditer(re.escape(tok), src)] for tok in tokens}
    report["forbidden_tokens_in_source"] = {k: len(v) for k, v in found.items() if v}
    # context for any hit
    report["forbidden_token_context"] = {k: [src[max(0, p - 60):p + 60].replace("\n", " ") for p in v][:3]
                                         for k, v in found.items() if v}

    # ---- 4b. METAR date bounds and availability basis
    st = t1.stations()
    metar_facts = {}
    for s in st:
        m = pd.read_parquet(t1.METAR / f"{s}.parquet", columns=["valid_utc", "available_utc", "local_date", "is_cor", "report_type"])
        lag = ((m.available_utc - m.valid_utc).dt.total_seconds() / 60).round(3).unique().tolist()
        metar_facts[s] = {"rows": int(len(m)), "lag_minutes_unique": lag, "max_local_date": str(m.local_date.max()),
                          "rows_local_date_after_0929": int((m.local_date.astype(str) > "2026-09-29").sum()),
                          "rows_valid_utc_on_or_after_0930Z": int((m.valid_utc >= pd.Timestamp("2026-09-30", tz="UTC")).sum()),
                          "cor_rows": int(m.is_cor.sum())}
    report["metar_facts"] = metar_facts

    # ---- 4c. the hunter's obs parquet: every joined value available <= captured_at
    snaps, bands = h.candidate_inputs()
    assert (snaps.date <= "2026-09-29").all()
    report["snapshot_max_date"] = str(snaps.date.max())
    report["candidate_input_columns_snaps"] = sorted(snaps.columns)
    report["candidate_input_columns_bands"] = sorted(bands.columns)
    obs_h = pd.read_parquet(T1_OUT / "t1_obs_pit.parquet")
    report["hunter_obs_rows"] = int(len(obs_h))

    # ---- 1. reproduce the baseline (hunter's basis valid + 10 min)
    check_stop()
    obs0 = t1.snapshot_obs(snaps)
    same = obs0.merge(obs_h, on="row_key", suffixes=("", "_h"))
    report["obs_reproduction"] = {
        "rows": int(len(same)),
        "runmax_equal": bool(np.allclose(same.runmax.fillna(-999), same.runmax_h.fillna(-999))),
        "def_1_equal": bool(np.allclose(same.def_1.fillna(-999), same.def_1_h.fillna(-999))),
        "past_sunset_equal": bool((same.past_sunset == same.past_sunset_h).all())}
    # explicit PIT audit of the latest joined row per snapshot, with the freshest-row age distribution
    ages = []
    for s, g in snaps.groupby("station", sort=False):
        m = t1.load_metar(s)
        mm = m[~m.is_cor].reset_index(drop=True)
        avail = mm.available_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
        valid = mm.valid_utc.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
        t = pd.to_datetime(g.captured_at_utc, utc=True, format="ISO8601").dt.tz_localize(None).to_numpy()
        i = np.searchsorted(avail, t, side="right") - 1
        ok = i >= 0
        late = (avail[np.maximum(i, 0)] > t) & ok
        age_min = (t[ok] - valid[i[ok]]) / np.timedelta64(1, "m")
        ages.append(pd.DataFrame({"row_key": g.row_key.to_numpy()[ok], "age_min": age_min,
                                  "local_hour": g.local_hour.to_numpy()[ok]}))
        assert not late.any()
    ages = pd.concat(ages, ignore_index=True)
    report["latest_obs_age_minutes_17_23"] = {
        k: float(v) for k, v in ages[ages.local_hour >= 17].age_min.describe(percentiles=[.05, .25, .5, .75, .95]).items()}

    results = {}
    cand0, ncov0 = t1.build(snaps, bands, obs0, params, "r2")
    res0 = h.score(cand0, name="rpit_t1_r2_repro_lag10")
    h.save(res0, OUT)
    results["repro_lag10"] = {"covered": ncov0, "17-23": pick(res0, "17-23"), "13-16": pick(res0, "13-16"),
                              "17-23_before": pick(res0, "17-23", "before_20260823"),
                              "classes": {g: res0["classes"][g]["class"] for g in res0["classes"]},
                              "leakage_suspect_groups": res0["leakage_suspect_groups"],
                              "reason_counts": res0["reason_counts"],
                              "rows_after_0929": res0["rows_with_target_after_2026_09_29"]}
    hunter = json.load(open(T1_OUT / "t1_r2_decided_band.score.json", encoding="utf-8"))
    hp = pick(hunter, "17-23")
    results["repro_lag10"]["matches_hunter_17_23"] = bool(abs(hp["estimate"] - results["repro_lag10"]["17-23"]["estimate"]) < 1e-9)
    results["repro_lag10"]["hunter_17_23"] = hp
    print("baseline 17-23 from:", results["repro_lag10"]["17-23"], "match", results["repro_lag10"]["matches_hunter_17_23"])

    # ---- 2. availability shifts (+50 reproduces the hunter's lag60; +60 and +120 are the refuter's)
    for extra in (50, 60, 120):
        check_stop()
        obs = t1.snapshot_obs(snaps, extra_lag_min=extra)
        cand, ncov = t1.build(snaps, bands, obs, params, "r2")
        res = h.score(cand, name=f"rpit_t1_r2_avail_plus{extra}min")
        h.save(res, OUT)
        results[f"lag{10 + extra}"] = {"total_lag_min_after_valid": 10 + extra, "covered": ncov,
                                      "17-23": pick(res, "17-23"), "13-16": pick(res, "13-16"),
                                      "17-23_before": pick(res, "17-23", "before_20260823"),
                                      "00-16": pick(res, "00-16"),
                                      "classes": {g: res["classes"][g]["class"] for g in res["classes"]},
                                      "leakage_suspect_groups": res["leakage_suspect_groups"],
                                      "reason_counts": res["reason_counts"]}
        print(f"+{extra} (valid+{10 + extra}) 17-23 from:", results[f"lag{10 + extra}"]["17-23"],
              "classes", results[f"lag{10 + extra}"]["classes"])
    # also r3 (sunset-only) at +120 as the timing-free reference
    obs120 = t1.snapshot_obs(snaps, extra_lag_min=120)
    cand, ncov = t1.build(snaps, bands, obs120, params, "r3")
    res = h.score(cand, name="rpit_t1_r3_avail_plus120min")
    h.save(res, OUT)
    results["r3_lag130"] = {"covered": ncov, "17-23": pick(res, "17-23"),
                            "classes": {g: res["classes"][g]["class"] for g in res["classes"]}}
    report["scores"] = results

    # ---- 3. refit reproduction into the refuter's directory
    check_stop()
    t1.OUT = OUT / "refit"
    t1.OUT.mkdir(parents=True, exist_ok=True)
    refit = t1.fit()
    comp = {"X": (refit["X"], params["X"]), "N": (refit["N"], params["N"]), "H": (refit["H"], params["H"]),
            "n_points": (refit["n_points"], params["n_points"]),
            "q_equal": all(abs(refit["q"][k][j] - params["q"][k][j]) < 1e-12 for k in params["q"] for j in ("k1", "k2", "k3")),
            "fit_end": (refit["fit_end"], params["fit_end"])}
    report["refit"] = comp
    # fitting window evidence: max history date actually used
    P = t1.history_points()
    report["history_points"] = {"n": int(len(P)), "date_min": str(P.date.min()), "date_max": str(P.date.max()),
                                "dates_after_fit_end": int((P.date > t1.FIT_END).sum())}
    t1.OUT = T1_OUT
    (OUT / "result.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("metar_facts",)}, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
