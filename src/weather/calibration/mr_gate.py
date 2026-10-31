r"""MR gate: does a live candidate predict the MARKET's error? (lane L3, 2026-10-30; rule ``RULE_SHA256``).

Rule ``docs/research/mr-gate-2026-10-30/rule_mr.md`` (sha256 ``37cb46be…``, approved unchanged by master via the
coordinator 2026-10-30; dev-window ledger rows 74-76). Development evidence only: the dev scorecard's default
folds through L11's ``market_blend`` machinery, imported unchanged (layout dates 2026-08-01..2026-09-29, burn-in
08-01..08-14, scored 08-15..09-29; nothing later is read).

Per candidate, in its own hour block and on the snapshots the candidate covers:

- **P0**: pooled Pearson rho between the candidate's disagreement with the market ``s = c - m`` and the market's
  error ``e = y - m`` over (snapshot x band) entries; date-clustered bootstrap (``P0_DRAWS`` draws, seed
  ``P0_SEED``). A date-deranged placebo vector (``market_blend.placebo_vector``) gives the same statistic.
  PASS iff the lower bound > 0 and the placebo interval covers 0.
- **w**: ``market_blend``'s walk-forward log pool fitted on the block (pooled Brier, dates <= d - 2, burn-in
  included). PASS iff mean w >= ``W_MIN``, blend R date-clustered upper < 1, paired blend - placebo Brier upper
  < 0 and paired blend - floor-only Brier upper < 0 (the scorecard's date-clustered weights).
- **Verdict**: PASS = P0 PASS and w PASS; otherwise KILL. A win against MG-1 or served alone does not count.

Controls run first and refuse the whole run (``market_blend.ControlFailed``, exit 7): served R 1.774 / 1.526,
MG-1 07-12 excess 0.0120, and the w = 0 identity (MG-1 and every candidate). Candidate files are sha-pinned.
The receipt records the git HEAD and dirty flag of this module's worktree; a dirty tree refuses.

    python -m weather.calibration.loyo_screen mr-gate --layout C:\swarm\v3layout --out C:\t\l3\mr\run1
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from weather.calibration import loyo_screen as ls

SCHEMA = "mr_gate/1"
GATE = "MR"
RULE_SHA256 = "37cb46be8d8ddb272ac69638d71de8d023eddff2384e0a6824e00a18417f34ac"
P0_DRAWS = 2000
P0_SEED = 20261024
W_MIN = 0.05
TRAINED_THROUGH = "2025-12-31"
BLOCKS = {"07-12": (7, 12), "13-16": (13, 16), "00-23": (0, 23),  # 00-23: the MR sweep w gate (rule 85f8192c)
          "00-06": (0, 6)}  # 00-06: the R-Q B spread P0 w gate (rule 844c2eb5, ledger row 88)
# Rows 75 and 76: the frozen P3d_H dev emits (ledger row 38 reproduced them byte-identically from the states).
CANDIDATES = {
    "R-R": {"block": "07-12", "ledger_row": 75, "state_sha256_prefix": "e9276477",
            "default_path": r"C:\t\l2\rungr\emit\dev_P3d_H.jsonl",
            "sha256": "a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d"},
    "R-K": {"block": "13-16", "ledger_row": 76, "state_sha256_prefix": "e891d884",
            "default_path": r"C:\t\l2\rungk\emit\dev_P3d_H.jsonl",
            "sha256": "e5195945cd8a24db178cd8b85e0af8914c95321b581a65897e8cac59eb451da1"},
}


class GateError(ls.ScreenError):
    pass


# ----------------------------------------------------------------------------- pure statistics

def _rho(n, sx, sy, sxx, syy, sxy):
    cov = sxy - sx * sy / n
    vx, vy = sxx - sx * sx / n, syy - sy * sy / n
    with np.errstate(invalid="ignore", divide="ignore"):
        return cov / np.sqrt(vx * vy)


def residual_rho(c, m, y, dates, draws=P0_DRAWS, seed=P0_SEED):
    """rho(c - m, y - m) over entries, with a date-clustered bootstrap (dates resampled with replacement)."""
    c, m, y = (np.asarray(v, float) for v in (c, m, y))
    s, e = c - m, y - m
    if not len(s):
        raise GateError("P0 has no entries")
    uniq, inv = np.unique(np.asarray(dates).astype(str), return_inverse=True)
    stats = np.stack([np.bincount(inv, weights=w, minlength=len(uniq))
                      for w in (np.ones_like(s), s, e, s * s, e * e, s * e)])
    point = float(_rho(*stats.sum(axis=1)))
    rng = np.random.default_rng(seed)
    counts = np.stack([np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))
                       for _ in range(draws)])
    boot = _rho(*(counts @ stats.T).T)
    fin = boot[np.isfinite(boot)]
    ci = np.quantile(fin, [0.025, 0.975]).tolist() if len(fin) else [None, None]
    return {"rho": point, "ci95": ci, "n_entries": int(len(s)), "n_dates": int(len(uniq)), "draws": draws,
            "seed": seed, "valid_draws": int(len(fin))}


def paired_diff(table, a, b, mask):
    """Mean over (date, market) cells of per-snapshot ``a - b`` with the table's date-clustered and crossed
    bootstrap weights (the scorecard's own draws)."""
    idx, ca = table.cells(np.asarray(a, float), mask)
    _, cb = table.cells(np.asarray(b, float), mask)
    if not len(idx):
        return None
    d = ca - cb
    out = {"estimate": float(d.mean()), "n_cells": int(len(idx))}
    for key, w in (("ci95_date", table.w_date), ("ci95_crossed", table.w)):
        wi = w[:, idx]
        den = wi.sum(axis=1)
        boot = np.divide(wi @ d, den, out=np.full(len(den), np.nan), where=den > 0)
        fin = boot[np.isfinite(boot)]
        out[key] = np.quantile(fin, [0.025, 0.975]).tolist() if len(fin) else [None, None]
    return out


def _upper_below(ci, bound):
    return ci is not None and ci[1] is not None and ci[1] < bound


def p0_pass(p0, placebo):
    lo_ok = p0["ci95"][0] is not None and p0["ci95"][0] > 0
    pl = placebo["ci95"]
    covers = pl[0] is not None and pl[0] <= 0 <= pl[1]
    return bool(lo_ok and covers)


def w_checks(wbar, blend_row, d_placebo, d_floor):
    return {"mean_w_at_least_0.05": bool(wbar >= W_MIN),
            "blend_R_date_upper_below_1": _upper_below(blend_row and blend_row.get("ci95_date"), 1.0),
            "blend_minus_placebo_date_upper_below_0": _upper_below(d_placebo and d_placebo.get("ci95_date"), 0.0),
            "blend_minus_floor_only_date_upper_below_0": _upper_below(d_floor and d_floor.get("ci95_date"), 0.0)}


def verdict_line(name, p0, p0_ok, wbar, checks, blend_row, d_placebo, d_floor):
    ok = p0_ok and all(checks.values())

    def ci(c):
        return "n/a" if not c or c[0] is None else f"[{c[0]:+.5f}, {c[1]:+.5f}]"

    r = blend_row or {}
    return ok, (f"{'PASS' if ok else 'KILL'}: {name} P0 rho {p0['rho']:+.4f} {ci(p0['ci95'])}; w {wbar:.3f}; "
                f"blend R {r.get('R', float('nan')):.4f} {ci(r.get('ci95_date'))}; "
                f"blend-placebo {d_placebo['estimate']:+.5f} {ci(d_placebo['ci95_date'])}; "
                f"blend-floor {d_floor['estimate']:+.5f} {ci(d_floor['ci95_date'])}")


# ----------------------------------------------------------------------------- one candidate

def gate_candidate(name, block, fit_t, score_t, p_fit, cov_fit, p_placebo_fit=None):
    """P0 and the w gate for one candidate vector on the fit table (burn-in + scored) and score table.

    ``p_placebo_fit`` replaces the c-deranged placebo (the MR sweep passes the disagreement placebo c_pl,0)."""
    from weather.calibration import market_blend as mb

    lo, hi = BLOCKS[block]
    cov_fit = np.asarray(cov_fit, bool)
    cov_score = mb.restrict_snap(fit_t, score_t, cov_fit)
    fit_mask = mb.hour_mask(fit_t, lo, hi) & cov_fit
    score_mask = mb.hour_mask(score_t, lo, hi) & cov_score
    if not score_mask.any():
        raise GateError(f"{name}: no covered snapshot in block {block}")
    p_score = mb.restrict(fit_t, score_t, p_fit)
    pm = score_t.p_market
    if p_placebo_fit is None:
        p_pl_fit, pl_meta = mb.placebo_vector(fit_t, p_fit)
    else:
        p_pl_fit, pl_meta = np.asarray(p_placebo_fit, float), {"supplied": True}
    p_pl = mb.restrict(fit_t, score_t, p_pl_fit)

    band = score_mask[score_t.band_snap]
    dates = score_t.snaps.date.astype(str).to_numpy()[score_t.band_snap]
    p0 = residual_rho(p_score[band], pm[band], score_t.y[band], dates[band])
    p0_pl = residual_rho(p_pl[band], pm[band], score_t.y[band], dates[band])
    p0_ok = p0_pass(p0, p0_pl)

    cell_dates = [k[0] for k in fit_t.keys]
    cell_markets = [k[1] for k in fit_t.keys]
    scored = sorted({k[0] for k in score_t.keys})
    args = (score_t.impossible, score_t.band_snap, len(score_t.snaps))
    hours = range(lo, hi + 1)

    def walk(p_fit_vec):
        grid = mb.grid_cell_values(fit_t, fit_t.p_market, p_fit_vec, {block: fit_mask})
        wf = mb.walk_forward_w(grid[block][0], cell_dates, cell_markets, scored)
        return {d: v[0] for d, v in wf.items()}, {d: v[1] for d, v in wf.items()}

    w_by_date, n_fit = walk(p_fit)
    w_pl, _ = walk(p_pl_fit)
    blend = mb.pool(pm, p_score, mb.w_per_band(score_t, w_by_date, hours), *args)
    blend_pl = mb.pool(pm, p_pl, mb.w_per_band(score_t, w_pl, hours), *args)
    floor = mb.pool(pm, pm, 0.0, *args, force_floor=True)
    mb_b, mb_l = score_t.brier(pm), score_t.log_score(pm)
    bb, bp, bf = score_t.brier(blend), score_t.brier(blend_pl), score_t.brier(floor)
    blend_row = mb.stats(score_t, bb, score_t.log_score(blend), mb_b, mb_l, score_mask, True)
    placebo_row = mb.stats(score_t, bp, score_t.log_score(blend_pl), mb_b, mb_l, score_mask, True)
    floor_row = mb.stats(score_t, bf, score_t.log_score(floor), mb_b, mb_l, score_mask, True)
    d_placebo = paired_diff(score_t, bb, bp, score_mask)
    d_floor = paired_diff(score_t, bb, bf, score_mask)
    w_sum, w_pl_sum = mb.w_summary(w_by_date), mb.w_summary(w_pl)
    checks = w_checks(w_sum["mean"], blend_row, d_placebo, d_floor)
    ok, line = verdict_line(name, p0, p0_ok, w_sum["mean"], checks, blend_row, d_placebo, d_floor)
    per_hour = {}
    for h in hours:
        hm = score_mask & (score_t.local_hour == h)
        if hm.any():
            per_hour[f"h{h:02d}"] = {"blend": mb.stats(score_t, bb, score_t.log_score(blend), mb_b, mb_l, hm, True),
                                     "blend_minus_floor_only": paired_diff(score_t, bb, bf, hm)}
    per_date = {}
    for key, diff in (("blend_minus_floor_only", bb - bf), ("blend_minus_placebo", bb - bp)):
        idx, vals = score_t.cells(diff, score_mask)
        for i, v in zip(idx, vals):
            per_date.setdefault(score_t.keys[i][0], {}).setdefault(key, []).append(float(v))
    per_date = {d: {k: {"cell_mean": float(np.mean(v)), "n_cells": len(v)} for k, v in x.items()}
                for d, x in sorted(per_date.items())}
    return {"gate": GATE, "candidate": name, "block": block, "verdict": "PASS" if ok else "KILL", "line": line,
            "per_date": per_date,
            "p0": {"statistic": "pearson rho(c - m, y - m)", "candidate": p0, "placebo": p0_pl, "pass": p0_ok},
            "w": {"summary": w_sum, "w_by_date": w_by_date, "n_fit_cells": n_fit, "checks": checks,
                  "pass": all(checks.values()), "placebo_summary": w_pl_sum, "placebo_w_by_date": w_pl,
                  "placebo_meta": pl_meta},
            "rows": {"blend_vs_market": blend_row, "placebo_vs_market": placebo_row,
                     "floor_only_vs_market": floor_row, "blend_minus_placebo": d_placebo,
                     "blend_minus_floor_only": d_floor},
            "per_hour": per_hour,
            "coverage": {"block_snapshots": int(mb.hour_mask(score_t, lo, hi).sum()),
                         "covered_block_snapshots": int(score_mask.sum()),
                         "covered_share": float(score_mask.sum() / max(1, mb.hour_mask(score_t, lo, hi).sum()))}}


# ----------------------------------------------------------------------------- tables and the parent controls

def build_tables(layout):
    """The dev scorecard layout, default folds, burn-in + scored fit table and scored table (as market_blend)."""
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas as la

    la.screen_input_path(layout, "layout")
    start, end = data.check_range(*mb.RANGE)
    lay = data.load_layout(layout, data.DEV_FIRST, end)
    folds = data.make_folds(lay.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    burn = [d for d in sorted({str(x) for x in lay.snaps.date.astype(str)}) if d <= mb.BURN_IN[1]]
    if not burn or burn[-1] >= scored[0] or scored[-1] > ls.LAST_ALLOWED.isoformat():
        raise GateError("burn-in must precede the scored dates, and nothing may be scored after 2026-09-29")
    return lay, folds, burn, scored, sc.Table(lay, burn + scored), sc.Table(lay, scored)


def market_controls(fit_t, score_t):
    """Served R, MG-1 07-12 excess and the w = 0 identity on MG-1; refuses (ControlFailed) on any miss."""
    from weather.calibration import gap_to_market_atlas as gta
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import loss_atlas as la

    controls = {"served": la.positive_control(score_t)}
    w0712 = mb.hour_mask(score_t, 7, 12)
    p_mg1_fit, _, _ = gta.vector_and_coverage(fit_t, la.mg1_frame(fit_t))
    p_mg1 = mb.restrict(fit_t, score_t, p_mg1_fit)
    excess = float(score_t.cells(score_t.brier(p_mg1) - score_t.brier(score_t.p_market), w0712)[1].mean())
    controls["mg1"] = {"excess_over_market_07_12": excess, "expected": mb.MG1_EXCESS_0712,
                       "verdict": "PASS" if round(excess, 4) == mb.MG1_EXCESS_0712 else "FAIL"}
    controls["w0_identity_mg1"] = mb.w0_identity(score_t, p_mg1)
    failed = [k for k, v in controls.items() if v["verdict"] != "PASS"]
    if failed:
        raise mb.ControlFailed(f"refused: controls failed {failed}")
    return controls


# ----------------------------------------------------------------------------- the run

def _check_candidate_file(name, path):
    spec = CANDIDATES[name]
    sha = ls.sha256_file(path)
    if sha != spec["sha256"]:
        raise GateError(f"{name}: {path} sha256 {sha} is not the pinned dev emit {spec['sha256']}")
    return sha


def run(*, layout, out_dir, candidates=None, allow_dirty=False):
    """Controls first (refuse on any miss), then each candidate; writes ``mr_gate.json`` (never overwrites)."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import gap_to_market_atlas as gta
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    candidates = dict(candidates or {n: s["default_path"] for n, s in CANDIDATES.items()})
    unknown = sorted(set(candidates) - set(CANDIDATES))
    if unknown:
        raise GateError(f"no rule row for candidates {unknown}; known {sorted(CANDIDATES)}")
    out = Path(out_dir)
    if (out / "mr_gate.json").exists():
        raise GateError(f"refusing to overwrite {out / 'mr_gate.json'}")
    shas = {n: _check_candidate_file(n, p) for n, p in candidates.items()}

    lay, folds, burn, scored, fit_t, score_t = build_tables(layout)
    controls = market_controls(fit_t, score_t)

    loaded, results = {}, {}
    for name, path in candidates.items():
        p_fit, cov_fit, meta = gta.load_candidate(str(path), TRAINED_THROUGH, lay, folds, fit_t)
        p_score, _, _ = gta.load_candidate(str(path), TRAINED_THROUGH, lay, folds, score_t)
        same = bool(np.array_equal(mb.restrict(fit_t, score_t, p_fit), p_score))
        controls[f"w0_identity_{name}"] = mb.w0_identity(score_t, p_score)
        controls[f"fit_equals_score_vector_{name}"] = {"equal": same, "verdict": "PASS" if same else "FAIL"}
        loaded[name] = (p_fit, cov_fit, meta)
    failed = [k for k, v in controls.items() if v["verdict"] != "PASS"]
    if failed:
        raise mb.ControlFailed(f"refused: candidate controls failed {failed}")
    for name, (p_fit, cov_fit, meta) in loaded.items():
        res = gate_candidate(name, CANDIDATES[name]["block"], fit_t, score_t, p_fit, cov_fit)
        res.update(ledger_row=CANDIDATES[name]["ledger_row"], source=str(candidates[name]),
                   source_sha256=shas[name], load_meta=meta)
        results[name] = res

    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "code": code,
               "evidence_class": "development (dev window, provisional)",
               "module_sha256": {"mr_gate": ls.sha256_file(__file__), "market_blend": ls.sha256_file(mb.__file__),
                                 "gap_to_market_atlas": ls.sha256_file(gta.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "n_market_days": len(score_t.keys)},
               "constants": {"p0_draws": P0_DRAWS, "p0_seed": P0_SEED, "w_min": W_MIN, "eps": mb.EPS,
                             "gap_days": mb.GAP_DAYS, "placebo_seed": mb.PLACEBO_SEED,
                             "scorecard_draws": sc.DRAWS, "scorecard_seed": sc.SEED},
               "controls": controls, "results": results,
               "lines": [results[n]["line"] for n in results]}
    out.mkdir(parents=True, exist_ok=True)
    clean = sc._clean(receipt) if hasattr(sc, "_clean") else receipt
    (out / "mr_gate.json").write_text(json.dumps(clean, indent=1, sort_keys=True, default=_default),
                                      encoding="utf-8")
    return receipt


def _default(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    raise TypeError(type(x))
