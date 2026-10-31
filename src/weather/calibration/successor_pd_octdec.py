r"""Successor batch C2 (lane L3): R-PD at local hours 00-06 on Oct-Dec 2021-25 history. Research only.

Rule: ``docs/research/successor-batch-2026-10-30/proposal.md`` section 2 / C2 (sha256 pinned below) and
DEV_WINDOW_LEDGER row 86. The arm and the incumbent are ``predawn_0006`` gate 1 unchanged (L6 own-obs HGB stacked
on the NBM mean, against the MG-1 analogue = the NBM mean, sigma = max(NBM sd, 1)); only ``LOYO_MONTHS`` changes.

Order, one invocation, one run:
1. Positive control: the unchanged gate-1 loop on Aug-Sep must reproduce gate 1's pooled 00-06 estimate
   (``CONTROL_ESTIMATE``, abs tol 1e-9). On failure the run stops (HOLD), no Oct-Dec number is computed.
2. Oct-Dec (10, 11, 12): the same loop. PASS iff the pooled 00-06 dates-paired upper 95% < 0 and no year and no
   month has a CI entirely > 0. Otherwise DROP.
3. Size class (row 86): MDE80_dev = 2.802 sigma_d sqrt(VIF) / sqrt(N_DEV) / brier_base, VIF = max(1,
   (1 + rho1) / (1 - rho1), block3^2) from the per-date dR of step 2, N_DEV = 43 (R-PD gate 2's date count).
   |estimate| < MDE80_dev / 2 is SUB-MDE (waits in the pool); otherwise AT-OR-ABOVE.

Inputs: IEM METAR (``data/research/upstream_obs``) and NOAA NBM text corpora only; no Open-Meteo-derived reader.
Nothing dated after 2026-09-29 is read (``predawn_0006.load_nbm_with_sd`` and ``upstream_obs_screen`` refuse).
Outputs must sit outside the repository and are written once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

RULE_SHA256 = "ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458"
CONTROL_MONTHS = (8, 9)
CONTROL_ESTIMATE = -0.004722492619806772
CONTROL_TOL = 1e-9
OCTDEC_MONTHS = (10, 11, 12)
N_DEV = 43
Z80 = 2.802


class SuccessorC2Error(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def loyo(research_root, nbm_corpora, months):
    """predawn_0006 gate 1's loop with ``LOYO_MONTHS = months``; returns (hist, b_arm, b_base, rows, prov)."""
    import numpy as np

    from weather.calibration import predawn_0006 as pd6
    from weather.calibration import upstream_obs_screen as l6

    saved = pd6.LOYO_MONTHS
    pd6.LOYO_MONTHS = tuple(months)
    try:
        nbm = pd6.load_nbm_with_sd(nbm_corpora)
        hist, prov = pd6.build_history(research_root, nbm)
    finally:
        pd6.LOYO_MONTHS = saved
    cols = list(l6.OWN)
    X, target = hist[cols].to_numpy(float), hist.y.to_numpy(float)
    year = hist.year.to_numpy(int)
    years = sorted(set(int(y) for y in year))
    if tuple(years) != pd6.LOYO_YEARS:
        raise SuccessorC2Error(f"history years {years} != {pd6.LOYO_YEARS}")
    fitted = {}

    def model_without(excluded):
        key = tuple(sorted(excluded))
        if key not in fitted:
            tr = ~np.isin(year, key)
            fitted[key] = l6.make_model(cols).fit(X[tr], target[tr])
        return fitted[key]

    R, v, s = hist.r.to_numpy(float), hist.v.to_numpy(float), hist.s.to_numpy(float)
    dmax, hours = hist.dmax.to_numpy(float), hist.hour.to_numpy(int)
    sigma = np.maximum(s, 1.0)
    has_v = np.isfinite(v) & np.isfinite(s)
    mu_arm = np.full(len(hist), np.nan)
    for Y in years:
        te = year == Y
        n_outer = R[te] + model_without({Y}).predict(X[te])
        n_inner = np.full(len(hist), np.nan)
        for Xy in years:
            if Xy == Y:
                continue
            m = year == Xy
            n_inner[m] = R[m] + model_without({Xy, Y}).predict(X[m])
        tr = ~te & has_v
        coef = pd6.stack_fit(np.where(tr, dmax - v, np.nan), np.where(tr, n_inner - v, np.nan), hours)
        mu_arm[te] = pd6.stack_mu(v[te], n_outer, hours[te], coef)
    rows = has_v
    b_arm = np.full(len(hist), np.nan)
    b_base = np.full(len(hist), np.nan)
    b_arm[rows] = pd6.bucket_brier(mu_arm[rows], sigma[rows], R[rows], dmax[rows])
    b_base[rows] = pd6.bucket_brier(v[rows], sigma[rows], R[rows], dmax[rows])
    return hist, b_arm, b_base, rows, dict(prov, hgb_fits=len(fitted))


def daily_stats(dates, markets, d):
    """Per-date dR (cell means, then date mean), sigma_d, lag-1 rho, block-3 SE ratio, AR(1)/block VIF."""
    import numpy as np
    import pandas as pd

    cell = pd.DataFrame({"date": dates, "market": markets, "d": d}).groupby(["date", "market"]).d.mean()
    per_date = cell.groupby(level=0).mean().sort_index()
    x = per_date.to_numpy(float)
    n = len(x)
    sd = float(x.std(ddof=1))
    xc = x - x.mean()
    rho1 = float((xc[1:] * xc[:-1]).sum() / (xc ** 2).sum()) if n > 2 else float("nan")
    nb = n // 3
    blocks = x[: nb * 3].reshape(nb, 3).mean(1)
    se_block = float(blocks.std(ddof=1) / math.sqrt(nb))
    se_iid = sd / math.sqrt(n)
    block3 = se_block / se_iid
    vif = max(1.0, (1 + rho1) / (1 - rho1), block3 ** 2)
    return per_date, {"n_dates": n, "mean_dR": float(x.mean()), "sigma_d": sd, "rho_lag1": rho1,
                      "block3_se_ratio": block3, "vif": vif}


def versions(nbm_corpora, months):
    """NBM product_version counts by (year, month, cycle) over the window, and versions per year."""
    counts, per_year = Counter(), {}
    for path in nbm_corpora:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            d = r["target_date"]
            if int(d[5:7]) not in months or d > "2025-12-31" or not r["available"]:
                continue
            counts[f"{d[:4]}-{d[5:7]}:{r['cycle']}:{r.get('product_version')}"] += 1
            per_year.setdefault(d[:4], set()).add(r.get("product_version"))
    return ({k: counts[k] for k in sorted(counts)},
            {y: sorted(v) for y, v in sorted(per_year.items())},
            sorted(y for y, v in per_year.items() if len(v) > 1))


def run(*, research_root, nbm_corpora, rule, out):
    import numpy as np

    from weather.calibration import pooled_residual_model as l2
    from weather.calibration import predawn_0006 as pd6
    from weather.calibration import upstream_obs_screen as l6

    out = l2.require_output_outside_repo(Path(out))
    if out.exists():
        raise SuccessorC2Error(f"refusing to overwrite {out} (one run per gate)")
    got = _sha(rule)
    if got != RULE_SHA256:
        raise SuccessorC2Error(f"rule sha {got} != pinned {RULE_SHA256}")
    payload = {"label": "Successor C2: R-PD 00-06 strictly nested LOYO Oct-Dec 2021-25 vs MG-1 analogue "
                        "(integer-F bucket Brier, METAR routine-max label as R-PD gate 1); history only, no edge claim",
               "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__),
               "predawn_0006_sha256": _sha(pd6.__file__), "l6_module_sha256": _sha(l6.__file__),
               "corpora": {str(p): _sha(p) for p in nbm_corpora}}

    # 1. positive control
    hist, b_arm, b_base, rows, prov = loyo(research_root, nbm_corpora, CONTROL_MONTHS)
    dates = hist.local_date.astype(str).to_numpy()
    markets = hist.market.astype(str).to_numpy()
    hours = hist.hour.to_numpy(int)
    ctl = pd6._cell_ratio(dates, markets, b_arm - b_base, b_base,
                          {"00-06": rows & (hours >= 0) & (hours <= 6)}, pd6.LOYO_SEED)["00-06"]
    control_ok = bool(abs(ctl["estimate"] - CONTROL_ESTIMATE) <= CONTROL_TOL)
    payload["control"] = {"months": list(CONTROL_MONTHS), "expected": CONTROL_ESTIMATE, "tol": CONTROL_TOL,
                          "got": ctl, "reproduced": control_ok, "hgb_fits": prov["hgb_fits"]}
    if not control_ok:
        payload.update(verdict="HOLD", reason="positive control did not reproduce gate 1")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        return payload

    # 2. Oct-Dec
    hist, b_arm, b_base, rows, prov = loyo(research_root, nbm_corpora, OCTDEC_MONTHS)
    dates = hist.local_date.astype(str).to_numpy()
    markets = hist.market.astype(str).to_numpy()
    hours = hist.hour.to_numpy(int)
    year = hist.year.to_numpy(int)
    month = hist.month.to_numpy(int)
    d = b_arm - b_base
    groups = {name: rows & (hours >= lo) & (hours <= hi) for name, lo, hi in pd6.STACK_GROUPS}
    pooled = pd6._cell_ratio(dates, markets, d, b_base, groups, pd6.LOYO_SEED)
    head = pooled["00-06"]
    per_year = {str(Y): pd6._cell_ratio(dates, markets, d, b_base, {"00-06": rows & (year == Y)},
                                        pd6.LOYO_SEED).get("00-06") for Y in sorted(set(year))}
    per_month = {str(M): pd6._cell_ratio(dates, markets, d, b_base, {"00-06": rows & (month == M)},
                                         pd6.LOYO_SEED).get("00-06") for M in OCTDEC_MONTHS}
    per_market = {m: pd6._cell_ratio(dates, markets, d, b_base, {"00-06": rows & (markets == m)},
                                     pd6.LOYO_SEED).get("00-06") for m in sorted(set(markets))}
    sel = rows & (hours >= 0) & (hours <= 6)
    _, stats = daily_stats(dates[sel], markets[sel], d[sel])
    worse_years = [k for k, v in per_year.items() if v and v["ci95"][0] is not None and v["ci95"][0] > 0]
    worse_months = [k for k, v in per_month.items() if v and v["ci95"][0] is not None and v["ci95"][0] > 0]
    upper_ok = bool(head["ci95"][1] is not None and head["ci95"][1] < 0)
    passed = bool(upper_ok and not worse_years and not worse_months)
    mde80 = Z80 * stats["sigma_d"] * math.sqrt(stats["vif"]) / math.sqrt(N_DEV) / head["brier_base"]
    size = None
    if passed:
        size = "SUB-MDE" if abs(head["estimate"]) < mde80 / 2 else "AT-OR-ABOVE"
    vcounts, vyears, mixed = versions(nbm_corpora, OCTDEC_MONTHS)
    payload.update(
        verdict="PASS" if passed else "DROP", size_class=size,
        reading={"pooled_upper_below_0": upper_ok, "years_ci_above_0": worse_years,
                 "months_ci_above_0": worse_months},
        dB=pooled, per_year_00_06=per_year, per_month_00_06=per_month, per_market_00_06=per_market,
        daily=stats, mde80_dev_relative=mde80, half_mde80_dev_relative=mde80 / 2, n_dev=N_DEV,
        nbm_versions={"counts": vcounts, "per_year": vyears, "years_with_boundary_inside_window": mixed},
        population={"history_rows": int(len(hist)), "scored_rows": int(rows.sum()),
                    "rows_without_nbm": int((~rows).sum()),
                    "nbm_cycle_counts": {str(k): int(c) for k, c in
                                         hist.nbm_cycle.fillna("none").value_counts().items()}},
        inputs=dict(prov, own=list(l6.OWN), hgb=l6.HGB_PARAMS),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, default=float), encoding="utf-8")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--research-root", required=True)
    ap.add_argument("--nbm-corpus", action="append", required=True)
    ap.add_argument("--rule", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    p = run(research_root=a.research_root, nbm_corpora=a.nbm_corpus, rule=a.rule, out=a.out)
    print(json.dumps({k: p.get(k) for k in ("verdict", "size_class")} | {"control": p["control"]["reproduced"]}))


if __name__ == "__main__":
    main()
