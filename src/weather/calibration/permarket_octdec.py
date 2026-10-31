r"""Lane L3 ledger row 92: X36's per-market additive centre shift on the SM-L6 incumbent, Oct-Dec LOYO. History only.

Rule ``docs/research/permarket-octdec-2026-10-30/rule_rm_octdec.md`` on ``claude/successor-batch-20261030`` (sha
pinned below). The incumbent is exactly C1's (ledger row 85): the SM-L6 OWN HGB fitted on Oct-Dec of the other four
years, MG-2 l6_stack with the frozen coefficients, Gaussian integer-bucket Brier floored at R. The arm adds one
additive shift s_m(Y) in deg F per market to the stack centre, fitted strictly nested (inner predictions from fits
outside {X, Y}) over the grid -4.0..+4.0 step 0.1 (ties to 0). Controls: C1 reproduction, s = 0 identity, a planted
+-2 deg F Austin bias, training score. Nothing dated 2026 is read. Research only; output outside the repository,
write-once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from weather.calibration import cool_season_audit as cs
from weather.calibration import season_matched_l6 as sm
from weather.calibration import successor_odc_low as c1

RULE_SHA256 = "9e494ff9bcd71160e3c2bc8cf1a2d2f767cf675103493c846e4809b95e44b9b8"
C1_RECEIPT_SHA256 = "c881a5bba59c36f6dd409b055910ee2ba83a36833735ca679bd8475c053dbe14"
C1_CONTROL_ESTIMATE = -0.005245663923351247
C1_CONTROL_ROWS = 24381
CONTROL_TOL = 1e-12
GRID = tuple(round(-4.0 + 0.1 * i, 1) for i in range(81))
REOPEN_SHIFT_F = 1.0
REOPEN_MIN_FOLDS = 3
PLANT_MARKET = "austin"
PLANT_F = 2.0
PLANT_BAND = 0.5


class PerMarketError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stack_mu(frame, n, coef):
    """The SM-L6 stack centre, width and ok mask exactly as ``season_matched_l6.stack_brier`` builds them."""
    import numpy as np

    v, s = frame.v.to_numpy(float), frame.s.to_numpy(float)
    hours = frame.hour.to_numpy(int)
    mu = v.copy()
    for h, (a, b, _) in coef.items():
        sel = (hours == int(h)) & np.isfinite(n) & np.isfinite(v)
        mu[sel] = v[sel] + a + b * (n[sel] - v[sel])
    ok = np.isfinite(v) & np.isfinite(s) & np.isfinite(n)
    return mu, np.maximum(s, 1.0), ok


def brier(mu, sig, R, dmax):
    from weather.calibration import rz_hrrr_spread as rz

    return rz.bucket_brier(mu, sig, R, dmax)


def fit_shift(mu, sig, R, dmax, grid=GRID):
    """Grid minimiser of the mean Brier of mu + s (ties: the s closest to 0), and the mean Brier at s and at 0."""
    import numpy as np

    if len(mu) == 0:
        return 0.0, float("nan"), float("nan")
    means = np.array([float(np.mean(brier(mu + g, sig, R, dmax))) for g in grid])
    best = means.min()
    tied = [g for g, v in zip(grid, means) if v == best]
    s = min(tied, key=lambda g: (abs(g), g))
    return float(s), float(best), float(means[list(grid).index(0.0)])


def reopen_condition(shifts):
    """R1: some market has |s_m(Y)| > 1.0 deg F with one sign in at least 3 of the 5 folds."""
    hits = {}
    for market, by_year in shifts.items():
        pos = sum(1 for v in by_year.values() if v > REOPEN_SHIFT_F)
        neg = sum(1 for v in by_year.values() if v < -REOPEN_SHIFT_F)
        if max(pos, neg) >= REOPEN_MIN_FOLDS:
            hits[market] = {"folds_above": pos, "folds_below": neg}
    return bool(hits), hits


def nested_shifts(rows, inner_mu, sig, ok, years, plant=None):
    """s_m(Y) per market and held-out year from the inner predictions, plus the training-score check."""
    import numpy as np

    markets = rows.market.astype(str).to_numpy()
    year = rows.year.to_numpy(int)
    R, dmax = rows.r.to_numpy(float), rows.dmax.to_numpy(float)
    shifts, train_check = {}, []
    for m in sorted(set(markets)):
        shifts[m] = {}
        for y in years:
            parts = []
            for x in years:
                if x == y:
                    continue
                sel = ok & (markets == m) & (year == x)
                mu_x = inner_mu[frozenset((x, y))][sel]
                if plant is not None and m == plant[0]:
                    mu_x = mu_x + plant[1]
                parts.append((mu_x, sig[sel], R[sel], dmax[sel]))
            cat = [np.concatenate([p[i] for p in parts]) for i in range(4)]
            s, at_s, at_0 = fit_shift(*cat)
            shifts[m][str(y)] = s
            train_check.append(bool(not (at_s > at_0)))
    return shifts, all(train_check)


def apply_shifts(rows, mu, shifts, plant=None):
    import numpy as np

    out = mu.copy()
    markets = rows.market.astype(str).to_numpy()
    year = rows.year.to_numpy(int)
    if plant is not None:
        out = out + np.where(markets == plant[0], plant[1], 0.0)
    for m, by_year in shifts.items():
        for y, s in by_year.items():
            out[(markets == m) & (year == int(y))] += s
    return out


def gate(rows, d, mask):
    import numpy as np

    from weather.calibration import upstream_obs_screen as l6

    f = rows[mask].reset_index(drop=True)
    dd = d[mask]
    dates = f.local_date.astype(str).to_numpy()
    point, lo, hi = l6.cluster_ci(dd, dates)
    per = {}
    for name, col, keys in (("year", "year", cs.YEARS), ("month", "month", sm.TRAIN_MONTHS),
                            ("hour", "hour", cs.HOURS_0712)):
        vals = f[col].to_numpy(int)
        per[name] = {str(k): l6.cluster_ci(dd[vals == k], dates[vals == k]) for k in keys if (vals == k).any()}
    mk = f.market.astype(str).to_numpy()
    per["market"] = {m: l6.cluster_ci(dd[mk == m], dates[mk == m]) for m in sorted(set(mk))}
    worse = [f"{n}:{k}" for n in ("year", "month") for k, v in per[n].items() if v[1] > 0]
    return {"point": point, "ci95": [lo, hi], "ci_worse_cells": worse, "per": per,
            "sizing": c1.daily_stats(dates, dd), "n_rows": int(mask.sum()), "n_dates": int(len(set(dates))),
            "pass": bool(hi < 0 and not worse)}


def run(*, research_root, nbm_corpus, mg2_coefficients, rule, c1_receipt, out_path):
    import numpy as np

    from weather.model import mg_serve_core as core

    got = _sha(rule)
    if got != RULE_SHA256:
        raise PerMarketError(f"rule sha {got} != {RULE_SHA256}")
    cs._pin(nbm_corpus, sm.NBM_CORPUS_SHA256, "NBM corpus")
    cs._pin(mg2_coefficients, cs.MG2_COEF_SHA256, "MG-2 coefficients")
    cs._pin(c1_receipt, C1_RECEIPT_SHA256, "C1 receipt")
    coef = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    train, prov = sm.training_rows(research_root)
    rows, _ = cs.l6_rows(research_root, nbm_corpus)
    rows = rows[rows.month.isin(sm.TRAIN_MONTHS)].reset_index(drop=True)
    years = tuple(cs.YEARS)
    R, dmax = rows.r.to_numpy(float), rows.dmax.to_numpy(float)
    # outer (A0) and inner fits
    n_out = np.full(len(rows), np.nan)
    for y in years:
        te = (rows.year == y).to_numpy()
        n_out[te] = core.l6_own_nowcast(sm.fit_state(train[train.year != y], {"fold": y}), rows[te])
    mu0, sig, ok = stack_mu(rows, n_out, coef)
    inner_mu = {}
    for i, x in enumerate(years):
        for y in years[i + 1:]:
            st = sm.fit_state(train[~train.year.isin((x, y))], {"inner": [x, y]})
            n_in = np.full(len(rows), np.nan)
            te = rows.year.isin((x, y)).to_numpy()
            n_in[te] = core.l6_own_nowcast(st, rows[te])
            mu_in, _, ok_in = stack_mu(rows, n_in, coef)
            inner_mu[frozenset((x, y))] = mu_in
            ok = ok & (ok_in | ~te)
    # control C-a: reproduction of C1's incumbent vs MG-1
    p_inc, base, _ = sm.stack_brier(rows, n_out, coef)
    control = sm.tables(rows, p_inc, base)["oct_dec"]["pooled"]
    c1r = json.loads(Path(c1_receipt).read_text(encoding="utf-8"))["control_incumbent_vs_mg1_pooled"]
    ca = {"estimate": control["estimate"], "n_rows": control["n_rows"], "c1_estimate": c1r["estimate"],
          "abs_diff": abs(control["estimate"] - C1_CONTROL_ESTIMATE)}
    ca["pass"] = bool(ca["abs_diff"] <= CONTROL_TOL and control["n_rows"] == C1_CONTROL_ROWS
                      and c1r["estimate"] == C1_CONTROL_ESTIMATE)
    b0 = np.full(len(rows), np.nan)
    b0[ok] = brier(mu0[ok], sig[ok], R[ok], dmax[ok])
    # control C-b: identity
    zero = {m: {str(y): 0.0 for y in years} for m in sorted(set(rows.market.astype(str)))}
    mz = apply_shifts(rows, mu0, zero)
    cb = {"max_abs_diff": float(np.nanmax(np.abs(brier(mz[ok], sig[ok], R[ok], dmax[ok]) - b0[ok])))}
    cb["pass"] = cb["max_abs_diff"] == 0.0
    # control C-c: planted Austin bias, both signs
    am = (rows.market.astype(str) == PLANT_MARKET).to_numpy() & ok
    cc = {}
    sub = rows[am].reset_index(drop=True)
    sub_mu = {k: v[am] for k, v in inner_mu.items()}
    nat, _ = nested_shifts(sub, sub_mu, sig[am], np.ones(am.sum(), bool), years)
    nat = nat[PLANT_MARKET]
    for label, delta, lo_b, hi_b in (("plant_minus2", -PLANT_F, PLANT_F - PLANT_BAND, PLANT_F + PLANT_BAND),
                                     ("plant_plus2", PLANT_F, -PLANT_F - PLANT_BAND, -PLANT_F + PLANT_BAND)):
        sh, _ = nested_shifts(sub, sub_mu, sig[am], np.ones(am.sum(), bool), years, plant=(PLANT_MARKET, delta))
        sa = sh[PLANT_MARKET]
        moved = {y: round(sa[y] - nat[y], 1) for y in sa}
        planted = apply_shifts(rows, mu0, {}, plant=(PLANT_MARKET, delta))
        shifted = apply_shifts(rows, mu0, {PLANT_MARKET: sa}, plant=(PLANT_MARKET, delta))
        d = np.full(len(rows), np.nan)
        d[am] = brier(shifted[am], sig[am], R[am], dmax[am]) - brier(planted[am], sig[am], R[am], dmax[am])
        g = gate(rows, d, am)
        in_band = all(lo_b <= v <= hi_b for v in moved.values())
        cc[label] = {"shifts": sa, "unplanted_shifts": nat, "moved": moved, "band": [lo_b, hi_b],
                     "in_band": in_band, "delta": g["point"],
                     "ci95": g["ci95"], "pass": bool(in_band and (label != "plant_minus2" or g["ci95"][1] < 0))}
    cc["pass"] = all(v["pass"] for v in cc.values())
    controls = {"C_a_reproduction": ca, "C_b_identity": cb, "C_c_planted": cc}
    if not (ca["pass"] and cb["pass"] and cc["pass"]):
        payload = {"verdict": "VOID", "controls": controls, "rule_sha256": RULE_SHA256,
                   "module_sha256": _sha(__file__)}
        cs._write_once(out_path, payload)
        raise PerMarketError(f"VOID: a control failed {json.dumps(controls, default=str)[:400]}")
    # the rung
    shifts, train_ok = nested_shifts(rows, inner_mu, sig, ok, years)
    controls["C_d_training_score"] = {"pass": train_ok}
    r1, hits = reopen_condition(shifts)
    mua = apply_shifts(rows, mu0, shifts)
    d = np.full(len(rows), np.nan)
    d[ok] = brier(mua[ok], sig[ok], R[ok], dmax[ok]) - b0[ok]
    g = gate(rows, d, ok)
    verdict = "PASS" if (r1 and g["pass"]) else "KILL"
    payload = {
        "label": "ledger row 92: X36 per-market centre shift on SM-L6, nested LOYO Oct-Dec 2021-25 07-12, history only",
        "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__), "verdict": verdict,
        "R1_reopen_condition": {"met": r1, "markets": hits, "threshold_f": REOPEN_SHIFT_F,
                                "min_folds": REOPEN_MIN_FOLDS},
        "R2_gate1": g, "shifts_f": shifts, "controls": controls, "rows_scored": int(ok.sum()),
        "train_rows": int(len(train)), "grid": [GRID[0], GRID[-1], len(GRID)],
        "inputs": dict(prov, nbm_corpus_sha256=sm.NBM_CORPUS_SHA256, coef_sha256=cs.MG2_COEF_SHA256,
                       c1_receipt_sha256=C1_RECEIPT_SHA256)}
    cs._write_once(out_path, payload)
    return payload


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m weather.calibration.permarket_octdec")
    for flag in ("--research-root", "--nbm-corpus", "--mg2-coefficients", "--rule", "--c1-receipt", "--out"):
        p.add_argument(flag, required=True)
    a = p.parse_args(argv)
    out = run(research_root=a.research_root, nbm_corpus=a.nbm_corpus, mg2_coefficients=a.mg2_coefficients,
              rule=a.rule, c1_receipt=a.c1_receipt, out_path=a.out)
    print(json.dumps({k: out[k] for k in ("verdict", "R1_reopen_condition", "shifts_f", "controls")},
                     indent=1, default=str))
    print(json.dumps({k: out["R2_gate1"][k] for k in ("point", "ci95", "ci_worse_cells", "n_rows", "n_dates")},
                     default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
