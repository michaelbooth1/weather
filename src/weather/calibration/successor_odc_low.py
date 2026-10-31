r"""Lane L3 successor batch C1: R-ODC low_so_far on the season-matched L6 incumbent, Oct-Dec LOYO. History only.

Rule: ``docs/research/successor-batch-2026-10-30/proposal.md`` on ``claude/successor-batch-20261030`` (sha pinned
below), section 2 C1. The incumbent is exactly the SM-L6 LOYO arm (``season_matched_l6``: OWN HGB fitted on Oct-Dec
of the other four years, MG-2 l6_stack with the frozen coefficients). The arm adds ``low`` (running min of the
WU-proxy temperature since local midnight, usable at valid + 10 min, min with ``t``) and ``t_minus_low``. Nothing
else changes. Also the outcome-free redundancy screen against RATE-0712 (rise rate since NOAA sunrise; row 81).
Nothing dated 2026 is read. Research only; output outside the repository, write-once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from weather.calibration import cool_season_audit as cs
from weather.calibration import season_matched_l6 as sm

RULE_SHA256 = "ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458"
EXTRA = ("low", "t_minus_low")
SR_MAX_AGE_MIN = 75
REDUNDANT_RHO = 0.80


class SuccessorError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sunrise_utc(date_str, lat, lon):
    """NOAA solar-calculator sunrise (zenith 90.833 deg) as a UTC pandas Timestamp."""
    import pandas as pd

    d = pd.Timestamp(date_str)
    n = d.dayofyear
    g = 2 * math.pi / 365.0 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                    - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl))
    if not -1 <= cos_ha <= 1:
        return pd.NaT
    ha = math.degrees(math.acos(cos_ha))
    minutes = 720 - 4 * (lon + ha) - eqt
    return (d + pd.Timedelta(minutes=minutes)).tz_localize("UTC")


def add_low(frame, research_root):
    """``low``, ``t_minus_low`` and ``rate_0712`` columns for rows with station/local_date/hour/t (index kept)."""
    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as l6

    obs, sel, _ = l6.load(research_root)
    out = pd.DataFrame(index=frame.index, columns=["low", "rate_0712"], dtype=float)
    for icao in l6.stations(sel):
        idx = frame.index[frame.station == icao]
        if len(idx) == 0:
            continue
        m = sel[icao]
        tz = m["timezone"]
        g, _ = l6.market_series(obs, icao, tz)
        g = g.copy()
        g["rmin"] = g.groupby("local_date").temp.cummin()
        f = frame.loc[idx]
        loc = pd.to_datetime(f.local_date) + pd.to_timedelta(f.hour.astype(int), unit="h") + pd.Timedelta(minutes=30)
        t_utc = loc.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
        q = pd.DataFrame({"t_utc": t_utc, "local_date": f.local_date.astype(str)}, index=idx).dropna()
        left = q.reset_index().sort_values("t_utc")
        right = g[["avail", "local_date", "rmin"]].sort_values("avail")
        mm = pd.merge_asof(left, right, left_on="t_utc", right_on="avail", by="local_date",
                           direction="backward").set_index("index")
        out.loc[mm.index, "low"] = mm.rmin.to_numpy(float)
        # RATE-0712: (t - T_sr) / hours since sunrise; T_sr = latest obs valid at or before sunrise, <= 75 min old
        sr = {d: sunrise_utc(d, m["lat"], m["lon"]) for d in q.local_date.unique()}
        sq = pd.DataFrame({"sr": [sr[d] for d in q.local_date]}, index=q.index).dropna()
        sl = sq.reset_index().sort_values("sr")
        sl["sr"] = sl.sr.astype("datetime64[ns, UTC]")
        gv = g[["valid_utc", "temp"]].sort_values("valid_utc")
        gv["valid_utc"] = gv.valid_utc.astype("datetime64[ns, UTC]")
        ms = pd.merge_asof(sl, gv, left_on="sr", right_on="valid_utc", direction="backward",
                           tolerance=pd.Timedelta(minutes=SR_MAX_AGE_MIN)).set_index("index")
        dh = (q.loc[ms.index, "t_utc"].astype("datetime64[ns, UTC]") - ms.sr).dt.total_seconds() / 3600.0
        tt = frame.loc[ms.index, "t"].to_numpy(float)
        rate = np.where(dh.to_numpy(float) > 0, (tt - ms.temp.to_numpy(float)) / dh.to_numpy(float), np.nan)
        out.loc[ms.index, "rate_0712"] = rate
    res = frame.copy()
    res["low"] = np.fmin(out.low.to_numpy(float), res.t.to_numpy(float))
    res["t_minus_low"] = res.t - res.low
    res["rate_0712"] = out.rate_0712.to_numpy(float)
    return res


def daily_stats(dates, diff):
    import numpy as np
    import pandas as pd

    s = pd.Series(diff).groupby(np.asarray(dates)).mean().sort_index()
    x = s.to_numpy(float)
    n = len(x)
    sd = float(x.std(ddof=1))
    lag1 = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    nb = n // 3
    b = x[: nb * 3].reshape(nb, 3).mean(1)
    se_iid = sd / math.sqrt(n)
    se_b3 = float(b.std(ddof=1) / math.sqrt(nb))
    return {"n_dates": n, "mean": float(x.mean()), "sigma_d": sd, "lag1": lag1, "se_iid": se_iid,
            "se_block3": se_b3, "block3_ratio": se_b3 / se_iid, "vif_ar1": (1 + lag1) / (1 - lag1)}


def run(*, research_root, nbm_corpus, mg2_coefficients, rule, out_path):
    import numpy as np
    from scipy.stats import spearmanr

    from weather.calibration import upstream_obs_screen as l6
    from weather.model import mg_serve_core as core

    got = _sha(rule)
    if got != RULE_SHA256:
        raise SuccessorError(f"rule sha {got} != {RULE_SHA256}")
    cs._pin(nbm_corpus, sm.NBM_CORPUS_SHA256, "NBM corpus")
    cs._pin(mg2_coefficients, cs.MG2_COEF_SHA256, "MG-2 coefficients")
    coef = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    train, prov = sm.training_rows(research_root)
    train = add_low(train, research_root)
    rows, _ = cs.l6_rows(research_root, nbm_corpus)
    rows = rows[rows.month.isin(sm.TRAIN_MONTHS)].reset_index(drop=True)
    rows = add_low(rows, research_root)
    cols = list(l6.OWN) + list(EXTRA)
    n_inc, n_arm = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
    for y in cs.YEARS:
        te = (rows.year == y).to_numpy()
        tr = train[train.year != y]
        n_inc[te] = core.l6_own_nowcast(sm.fit_state(tr, {"fold": y}), rows[te])
        model = l6.make_model(cols).fit(tr[cols].to_numpy(float), tr.y.to_numpy(float))
        n_arm[te] = rows[te].r.to_numpy(float) + model.predict(rows[te][cols].to_numpy(float))
    p_inc, base, _ = sm.stack_brier(rows, n_inc, coef)
    p_arm, _, _ = sm.stack_brier(rows, n_arm, coef)
    ok = np.isfinite(p_inc) & np.isfinite(p_arm)
    f = rows[ok].reset_index(drop=True)
    d = (p_arm - p_inc)[ok]
    dates = f.local_date.astype(str).to_numpy()
    control = sm.tables(rows, p_inc, base)["oct_dec"]["pooled"]
    point, lo, hi = l6.cluster_ci(d, dates)
    per_year = {str(y): l6.cluster_ci(d[f.year.to_numpy() == y], dates[f.year.to_numpy() == y]) for y in cs.YEARS}
    per_month = {str(mo): l6.cluster_ci(d[f.month.to_numpy() == mo], dates[f.month.to_numpy() == mo])
                 for mo in sm.TRAIN_MONTHS}
    per_hour = {str(h): l6.cluster_ci(d[f.hour.to_numpy() == h], dates[f.hour.to_numpy() == h])
                for h in cs.HOURS_0712}
    worse = [k for k, v in {**per_year, **per_month}.items() if v[1] > 0]
    scr = f[["t_minus_low", "rate_0712"]].dropna()
    rho = float(spearmanr(scr.t_minus_low, scr.rate_0712).correlation)
    redundant = abs(rho) >= REDUNDANT_RHO
    verdict = "PASS" if (hi < 0 and not worse and not redundant) else "DROP"
    payload = {
        "label": "successor batch C1: R-ODC low_so_far on SM-L6, LOYO Oct-Dec 2021-25 07-12, history only",
        "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__), "verdict": verdict,
        "pooled_delta_brier_arm_minus_incumbent": {"point": point, "ci95": [lo, hi]},
        "per_year": per_year, "per_month": per_month, "per_hour": per_hour, "ci_worse_cells": worse,
        "sizing": daily_stats(dates, d),
        "redundancy_screen": {"spearman_t_minus_low_vs_rate_0712": rho, "n": int(len(scr)),
                              "threshold": REDUNDANT_RHO, "redundant": redundant},
        "control_incumbent_vs_mg1_pooled": control,
        "control_expected_sm_l6_loyo_sha256": cs.SM_LOYO_SHA256,
        "rows_scored": int(ok.sum()), "train_rows": int(len(train)),
        "low_coverage_rows": float(np.isfinite(rows.low).mean()),
        "inputs": dict(prov, nbm_corpus_sha256=sm.NBM_CORPUS_SHA256, coef_sha256=cs.MG2_COEF_SHA256)}
    cs._write_once(out_path, payload)
    return payload


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m weather.calibration.successor_odc_low")
    for flag in ("--research-root", "--nbm-corpus", "--mg2-coefficients", "--rule", "--out"):
        p.add_argument(flag, required=True)
    a = p.parse_args(argv)
    out = run(research_root=a.research_root, nbm_corpus=a.nbm_corpus, mg2_coefficients=a.mg2_coefficients,
              rule=a.rule, out_path=a.out)
    print(json.dumps({k: out[k] for k in ("verdict", "pooled_delta_brier_arm_minus_incumbent", "ci_worse_cells",
                                          "sizing", "redundancy_screen", "control_incumbent_vs_mg1_pooled")},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
