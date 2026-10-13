"""refute-pit-t18: availability-shift re-runs of t18-r1 (development only; no new rule registered).

Every input of t18-r1 is delayed by D in {0, 60, 120} min at serve time, with the fitted parameters FROZEN
(t18_run.json) and, as a second reading, REFIT on the before stratum under the same delay:
  * METAR rung R: IEM routine rows available at valid + 10 min + D (t3.load_metar(extra_lag_min=D)).
  * Captured sources (v2_mean, hrrr_high, forecast_high) taken AS OF t - D: the values of the latest
    snapshot of the same market and target date captured <= t - D (each of which was point in time
    there, availability stamp <= that capture), i.e. the stale value a D-late feed would show.
    No earlier snapshot -> imputed as mu_rr (term 0), the registered missing-value rule.
  * Variant "impute": instead of the stale value, a source enters only if stamp + D <= t, else mu_rr
    (forecast_high, stamped at t, never enters). This is T18's own r1s form extended to +120.
The prior p0 (history <= 2026-07-31) is unchanged (it is not a serve-time input).
Run: cd C:\\pt\\swarm; <repo python> -m tools.research.model_parity.r-pit-t18_shift  (module name via runpy)
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

OUT = Path(r"C:\swarm\out\refute-pit-t18")
SRC_COLS = {"v2_mean": "v2_available_at", "hrrr_high": "hrrr_fetched_at", "forecast_high": "captured_at_utc"}


def stale_sources(s, src, lag_min):
    """Source values as of t - lag from the latest earlier snapshot of the same market-day."""
    cap = pd.to_datetime(s.captured_at_utc, utc=True)
    left = pd.DataFrame({"i": np.arange(len(s)), "k": s.market + "|" + s.date,
                         "t": (cap - pd.Timedelta(minutes=lag_min)).astype("datetime64[us, UTC]")})
    right = pd.DataFrame({"j": np.arange(len(s)), "k": s.market + "|" + s.date,
                          "tc": cap.astype("datetime64[us, UTC]")})
    j = pd.merge_asof(left.sort_values("t"), right.sort_values("tc"), left_on="t", right_on="tc", by="k",
                      direction="backward").sort_values("i")
    jj = j.j.to_numpy()
    ok = ~np.isnan(jj)
    out, n = {}, {}
    for col, avc in SRC_COLS.items():
        v = np.full(len(s), np.nan)
        idx = jj[ok].astype(int)
        v[ok] = src[col][idx]
        av = pd.to_datetime(s[avc], utc=True, errors="coerce").dt.tz_convert(None).to_numpy("datetime64[ns]")
        avs = np.full(len(s), np.datetime64("NaT"), dtype="datetime64[ns]")
        avs[ok] = av[idx]
        use = np.isfinite(v) & ~np.isnat(avs)
        lim = (cap - pd.Timedelta(minutes=lag_min)).dt.tz_convert(None).to_numpy("datetime64[ns]")
        assert (avs[use] <= lim[use]).all(), col          # stamp <= t - lag for every value used
        h.assert_point_in_time(pd.Series(avs[use]).dt.tz_localize("UTC"), pd.Series(lim[use]).dt.tz_localize("UTC"))
        v[~use] = np.nan
        out[col] = v
        n[col] = int(use.sum())
    return out, n


def impute_sources(s, src, lag_min):
    cap = pd.to_datetime(s.captured_at_utc, utc=True)
    out, n = {}, {}
    for col, avc in SRC_COLS.items():
        if col == "forecast_high":
            out[col] = src[col] if lag_min == 0 else np.full(len(s), np.nan)
        else:
            a = pd.to_datetime(s[avc], utc=True, errors="coerce") + pd.Timedelta(minutes=lag_min)
            use = np.isfinite(src[col]) & (a <= cap).to_numpy()
            out[col] = np.where(use, src[col], np.nan)
        n[col] = int(np.isfinite(out[col]).sum())
    return out, n


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    run = json.loads((t.OUT / "t18_run.json").read_text(encoding="utf-8"))
    chosen = run["chosen"]
    th1 = np.r_[run["theta_r1"]["a"], [run["theta_r1"][f"b_{k}"] for k in chosen], np.log(run["theta_r1"]["sigma"])]
    lags = [int(x) for x in sys.argv[1:]] or [0, 60, 120]
    summary = {"HARNESS_SHA256": h.harness_sha256(), "chosen": chosen, "theta_r1_frozen": th1.tolist(), "runs": {}}
    orig = t3.load_metar
    for lag in lags:
        if Path(r"C:\swarm\STOP").exists():
            raise SystemExit("STOP")
        t3.load_metar = (lambda extra_lag_min=0, _l=lag: orig(extra_lag_min=_l))
        s, bands, prior, src, meta = t.build_inputs()
        t3.load_metar = orig
        cov = s.covered.to_numpy()
        variants = {"stale": stale_sources(s, src, lag), "impute": impute_sources(s, src, lag)}
        if lag == 0:
            variants = {"asis": ({k: src[k] for k in SRC_COLS}, {k: int(np.isfinite(src[k]).sum()) for k in SRC_COLS}),
                        **variants}
        tr = cov & (s.stratum == t.BEFORE).to_numpy() & s.Y.notna().to_numpy()
        eobs = np.minimum((s.Y.to_numpy()[tr] - s.R.to_numpy()[tr]).astype(int), t.G - 1)
        pmr = np.full((len(s), t.G), np.nan)
        pmr[cov] = prior[cov]
        cands = {"t3-r3": t.to_bands(s, bands, pmr, cov)}
        info = {"covered": int(cov.sum()), "source_rows": {}, "theta_refit": {}}
        for vn, (sv, n) in variants.items():
            info["source_rows"][vn] = n
            mall = t.Model(s, prior, sv, cov)
            pm = np.full((len(s), t.G), np.nan)
            pm[cov] = mall.pmf(th1, chosen)
            cands[f"r1_{vn}_frozen"] = t.to_bands(s, bands, pm, cov)
            if vn != "asis":
                mtr = t.Model(s, prior, sv, tr)
                thr, nll, ok = t.fit(mtr, eobs, chosen, th1)
                info["theta_refit"][vn] = {"theta": thr.tolist(), "train_nll": nll, "ok": ok}
                pm2 = np.full((len(s), t.G), np.nan)
                pm2[cov] = mall.pmf(thr, chosen)
                cands[f"r1_{vn}_refit"] = t.to_bands(s, bands, pm2, cov)
        res_all = {}
        for nm, c in cands.items():
            res = h.score(c, name=f"rpit18_{nm}_lag{lag}")
            assert res["rows_with_target_after_2026_09_29"] == 0
            if res["leakage_suspect_groups"]:
                Path(r"C:\swarm\STOP").write_text(f"refute-pit-t18 leakage suspect {nm} lag {lag}\n")
                raise SystemExit("LEAKAGE SUSPECT")
            h.save(res, OUT)
            res_all[nm] = res
            row = {}
            for g in ("00-05", "06-09", "10-12", "13-16", "00-16", "17-23", "all"):
                fr = h.table_lookup(res, g, "from_20260823", "all_row")["candidate_minus_served"]
                be = h.table_lookup(res, g, "before_20260823", "all_row")["candidate_minus_served"]
                row[g] = {"class": res["classes"][g]["class"] if isinstance(res["classes"][g], dict) else res["classes"][g],
                          "from": fr["estimate"], "from_ci95": fr["ci95"], "before": be["estimate"]}
            info.setdefault("scores", {})[nm] = row
            print(lag, nm, {g: (row[g]["class"], round(row[g]["from"], 5)) for g in ("00-16", "17-23")}, flush=True)
        pairs = [(k, "t3-r3") for k in cands if k != "t3-r3"]
        info["paired_vs_rung"] = {g: v for g, v in t.paired(cands, list(cands), pairs).items()
                                  if g in ("00-16", "17-23", "all", "06-09", "10-12", "13-16", "00-05")}
        summary["runs"][str(lag)] = info
        (OUT / "shift_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
