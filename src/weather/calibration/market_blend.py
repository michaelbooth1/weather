r"""Walk-forward logarithmic opinion pool of the market and a candidate, scored against the market (L11).

Pre-registered in ``C:\t\l11\rule.md`` (sha256 ``RULE_SHA256``; copy in
``docs/research/market-blend-l11-2026-10-25/rule.md``). Development evidence only: the C dev scorecard
window through its own date guard (layout dates 2026-08-01..2026-09-29; nothing later, no 88a or panel data).

Pool, per snapshot over its band set: ``g = max(m, eps)^(1-w) * max(c, eps)^w`` (m the market vector exactly
as the scorecard scores it, c the candidate's scorecard vector), rule-4-impossible bands zeroed for w > 0
(the log-pool limit of the candidate's floored zeros), renormalised to the market's own mass ``sum(m)`` so
that w = 0 is the market exactly. w is fitted walk-forward by date on the grid 0.00..1.00: to score date d,
only dates <= d - 2 (the scorecard's one-day settlement gap), burn-in 08-01..08-14 included, minimising
the pooled Brier (sum of cell-mean Brier over the fit block; log score as the secondary objective).

Each blend is reported ONLY against the market (R = blend Brier / market Brier on identical cells, the
scorecard's date-clustered and crossed intervals); no candidate-minus-candidate deltas are formed. Controls
run first and refuse (exit 7) unless they reproduce: served R 1.774 / 1.526, MG-1 07-12 excess 0.0120, the L6
own-stack -0.0036243 (composite), and the w = 0 identity (blend == market, R == 1 exactly). A date-shuffled
placebo and the floor-only limit (w -> 0+) are reported beside the rows.

    python -m weather.calibration.market_blend --layout C:\swarm\v3layout --out-dir C:\t\l11\run1
        [--arm-a-refit <vectors> --arm-a-refit-sha256 <sha>]   # composite 13-16, only after the L3 refit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from weather.reporting.scorecards import loss_atlas as la  # refuses import on the capture host

la.refuse_production_import()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from weather.calibration import gap_to_market_atlas as gta  # noqa: E402
from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402

SCHEMA = "market_blend/1"
RULE_SHA256 = "e29c9a84395d7f4f5e9a0091da99ff970597c40faa7d4cc81aa034a373f8bb8c"
CLARIFICATION_1_SHA256 = "46e1fac20a4fed42ec1290c1d675dbf204dfba475ee756ee442b6f121d5a9de0"  # pre-13 / 13+ slots
# Item 5 (C:\t\l11\market_blend_rule_nbm0712.md): P3d_N at 07-12 in place of MG-1 + L6, run-2 machinery unchanged.
NBM0712_RULE_SHA256 = "94b1603a407dd66ccb6137468cc3e703e00f73024209997c3181e26ed8a07e84"
NBM0712_VECTORS_SHA256 = "721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec"
NBM0712_MG1_R = 1.0016629  # run 2's MG-1 07-12 primary R (rows 1ba4620a...), 7 dp
NBM0712_WINDOWS = (("h07", 7, 7), ("h08", 8, 8), ("h09", 9, 9), ("h10", 10, 10), ("h11", 11, 11),
                   ("h12", 12, 12), ("07-12", 7, 12))
EPS = 1e-4
W_GRID = np.arange(101) / 100.0
GAP_DAYS = 1
PLACEBO_SEED = 20260921
RANGE = ("2026-08-01", "2026-09-29")
BURN_IN = ("2026-08-01", "2026-08-14")
PRIMARY5 = gta.PRIMARY
FIT_BLOCKS = (("07-12", 7, 12), ("06-09", 6, 9), ("10-12", 10, 12), ("12-16", 12, 16), ("13-16", 13, 16))
PRIMARY_FIT = "07-12"
HOUR_FIT = {**{h: "07-12" for h in range(7, 13)}, **{h: "13-16" for h in range(13, 17)}}
W_POSITIVE = 0.05
PLACEBO_W_MAX = 0.05
PLACEBO_R_MIN = 0.999
MG1_EXCESS_0712 = 0.0120
L6_MINUS_MG1_0712 = gta.L6_MINUS_MG1_0712
COMPOSITE_SWITCH_HOUR = gta.COMPOSITE_SWITCH_HOUR
REFIT_MARKER = Path(r"C:\t\mg2\control_refit_armA.json")
LEAD1_ARM_A = "dev_l8_high_so_far_ols_floor"


class ControlFailed(data.Refused):
    exit_code = 7


# ----------------------------------------------------------------------------- pool and fit (pure)

def pool(m, c, w_band, impossible, band_snap, n_snaps, eps=EPS, force_floor=False):
    """The pre-registered log pool on flat band arrays; ``w_band`` is w per band (its snapshot's w).

    ``force_floor`` gives the floor-only control (the w -> 0+ limit: market, hard floor, same mass).
    """
    m = np.asarray(m, float)
    w_band = np.broadcast_to(np.asarray(w_band, float), m.shape)
    if (w_band < 0).any():
        raise data.Refused("refused: w must be >= 0")
    g = np.maximum(m, eps) ** (1.0 - w_band) * np.maximum(np.asarray(c, float), eps) ** w_band
    g = np.where(impossible & ((w_band > 0) | force_floor), 0.0, g)
    s_m = np.bincount(band_snap, weights=m, minlength=n_snaps)
    s_g = np.bincount(band_snap, weights=g, minlength=n_snaps)
    if (s_g <= 0).any():
        raise data.Refused("refused: a snapshot has zero pooled mass")
    return g * (s_m / s_g)[band_snap]


def grid_cell_values(table, p_market, p_cand, block_masks, w_grid=W_GRID):
    """{block: (brier [n_w, n_cells], log [n_w, n_cells])}, NaN where a cell has no snapshot in the block."""
    n_cells = len(table.keys)
    out = {name: (np.full((len(w_grid), n_cells), np.nan), np.full((len(w_grid), n_cells), np.nan))
           for name in block_masks}
    for k, w in enumerate(w_grid):
        blend = pool(p_market, p_cand, w, table.impossible, table.band_snap, len(table.snaps))
        b, lg = table.brier(blend), table.log_score(blend)
        for name, mask in block_masks.items():
            idx, cb = table.cells(b, mask)
            _, cl = table.cells(lg, mask)
            out[name][0][k, idx] = cb
            out[name][1][k, idx] = cl
    return out


def walk_forward_w(values, cell_dates, cell_markets, scored_dates, markets=None, gap_days=GAP_DAYS,
                   w_grid=W_GRID):
    """w per scored date: argmin over the grid of the summed cell values on dates <= d - (gap + 1).

    Ties go to the smaller w (``argmin`` returns the first). ``markets`` restricts the fitting cells.
    """
    cd = np.array([date.fromisoformat(d) for d in cell_dates])
    in_pool = np.ones(len(cd), bool) if markets is None else np.isin(np.asarray(cell_markets), list(markets))
    finite = np.isfinite(values).all(axis=0)
    out = {}
    for d in scored_dates:
        last = date.fromisoformat(d) - timedelta(days=gap_days + 1)
        sel = in_pool & finite & (cd <= last)
        if not sel.any():
            out[d] = (0.0, 0)
            continue
        obj = values[:, sel].sum(axis=1)
        out[d] = (float(w_grid[int(np.argmin(obj))]), int(sel.sum()))
    return out


def w_summary(w_by_date):
    w = np.array([v for v in w_by_date.values()], float)
    if not len(w):
        return {}
    keys = sorted(w_by_date)
    return {"mean": float(w.mean()), "median": float(np.median(w)), "min": float(w.min()), "max": float(w.max()),
            "first": float(w_by_date[keys[0]]), "last": float(w_by_date[keys[-1]]),
            "n_zero": int((w == 0).sum()), "n_dates": int(len(w)), "at_cap": int((w >= W_GRID[-1]).sum())}


def derangement(n, rng):
    if n < 2:
        return np.arange(n)
    while True:
        perm = rng.permutation(n)
        if not (perm == np.arange(n)).any():
            return perm


def placebo_vector(table, p, seed=PLACEBO_SEED):
    """Candidate vectors shuffled across dates within (market, local hour): a fixed-seed derangement of the
    dates; snapshot k of (d, market, hour) takes the vector of snapshot min(k, n-1) of the donor date."""
    s = table.snaps
    df = pd.DataFrame({"i": np.arange(len(s)), "d": s.date.astype(str).to_numpy(), "m": table.markets,
                       "h": table.local_hour, "t": s.captured_at_utc.astype(str).to_numpy(),
                       "k": s.row_key.astype(str).to_numpy()})
    df = df.sort_values(["m", "h", "d", "t", "k"], kind="mergesort").reset_index(drop=True)
    df["r"] = df.groupby(["m", "h", "d"], sort=False).cumcount()
    rng = np.random.default_rng(seed)
    src = np.arange(len(s))
    unshuffled = 0
    for _, g in df.groupby(["m", "h"], sort=True):
        ds = sorted(g.d.unique())
        if len(ds) < 2:
            unshuffled += len(g)
            continue
        perm = derangement(len(ds), rng)
        donor = dict(zip(ds, (ds[j] for j in perm)))
        first = g.groupby("d").i.apply(list).to_dict()
        for i, d, r in zip(g.i.to_numpy(), g.d.to_numpy(), g.r.to_numpy()):
            pool_ = first[donor[d]]
            src[i] = pool_[min(r, len(pool_) - 1)]
    if (table.n[src] != table.n).any():
        raise data.Refused("refused: placebo donor has a different band count")
    pos = np.repeat(table.offsets[src], table.n) + (np.arange(len(table.bands)) - np.repeat(table.offsets, table.n))
    return p[pos], {"seed": seed, "unshuffled_snapshots": int(unshuffled),
                    "same_date_donors": int((s.date.astype(str).to_numpy()[src] == s.date.astype(str).to_numpy()).sum())}


def restrict(fit_t, score_t, values):
    """Band-array ``values`` on ``fit_t`` restricted to the snapshots (and band order) of ``score_t``."""
    pos = fit_t.snap_pos.reindex(score_t.snaps.row_key.to_numpy()).to_numpy()
    if np.isnan(pos.astype(float)).any():
        raise data.LayoutError("score table snapshot missing from the fit table")
    pos = pos.astype(int)
    if (fit_t.n[pos] != score_t.n).any():
        raise data.LayoutError("band counts differ between fit and score tables")
    within = np.arange(len(score_t.bands)) - np.repeat(score_t.offsets, score_t.n)
    return np.asarray(values)[np.repeat(fit_t.offsets[pos], score_t.n) + within]


def w_per_band(table, w_by_date, hours=None, default=0.0):
    dates = table.snaps.date.astype(str).to_numpy()
    w = np.array([w_by_date.get(d, default) for d in dates], float)
    if hours is not None:
        w = np.where(np.isin(table.local_hour, list(hours)), w, 0.0)
    return w[table.band_snap]


def reading(wbar, row, m_floor_r, placebo_ok):
    """The pre-registered reading on the PRIMARY row (crossed interval decides)."""
    lo, hi = row["ci95_crossed"]
    if placebo_ok is False:
        return "NOT INTERPRETABLE (placebo failed)"
    if lo is not None and lo > 1:
        return "HARM: walk-forward blending hurts"
    if wbar < W_POSITIVE:
        return "NOTHING: w ~ 0, the model adds nothing to the market"
    if hi is not None and hi < 1 and row["R"] < m_floor_r:
        return "INFORMATION: w > 0 with blend R crossed upper CI < 1 (and below the floor-only control)"
    note = " (date-clustered upper CI < 1)" if row["ci95_date"][1] is not None and row["ci95_date"][1] < 1 else ""
    if hi is not None and hi < 1:
        return "INCONCLUSIVE: crossed upper CI < 1 but the blend does not beat the floor-only control" + note
    return "INCONCLUSIVE: w > 0 but no increment over the market demonstrated at this MDE" + note


# ----------------------------------------------------------------------------- scoring

def stats(table, cand_b, cand_l, market_b, market_l, mask, pooled):
    st = gta.cell_stats(table, cand_b, market_b, mask, pooled)
    if st is None:
        return None
    lg = gta.cell_stats(table, cand_l, market_l, mask, pooled)
    st["log_ratio"] = lg["R"]
    st["log_ratio_ci95_date"] = lg["ci95_date"]
    st["log_market"] = lg["brier_market"]
    st["log_candidate"] = lg["brier_candidate"]
    if pooled:
        st["log_ratio_ci95_crossed"] = lg["ci95_crossed"]
    return st


def pools(table):
    return [("ALL", None), ("PRIMARY5", PRIMARY5)] + [(mk, (mk,)) for mk in sorted(set(table.markets))]


def hour_mask(table, lo, hi, members=None):
    mask = (table.local_hour >= lo) & (table.local_hour <= hi)
    if members is not None:
        mask &= np.isin(table.markets, list(members))
    return mask


def score_candidate(name, fit_t, score_t, p_fit, blocks, placebo=True):
    """Fit every pre-registered w path on ``fit_t`` and score the blends on ``score_t`` vs the market."""
    scored = sorted({k[0] for k in score_t.keys})
    cell_dates = [k[0] for k in fit_t.keys]
    cell_markets = [k[1] for k in fit_t.keys]
    masks = {b: hour_mask(fit_t, lo, hi) for b, lo, hi in FIT_BLOCKS if b in blocks}
    grid = grid_cell_values(fit_t, fit_t.p_market, p_fit, masks)
    fits = {}
    for b in masks:
        for obj, k in (("brier", 0), ("log", 1)):
            if obj == "log" and b != PRIMARY_FIT:
                continue
            wf = walk_forward_w(grid[b][k], cell_dates, cell_markets, scored)
            fits[f"{b}/{obj}/ALL"] = {"block": b, "objective": obj, "pool": "ALL",
                                       "w_by_date": {d: v[0] for d, v in wf.items()},
                                       "n_fit_cells": {d: v[1] for d, v in wf.items()}}
    if PRIMARY_FIT in masks:
        for mk in sorted(set(fit_t.markets)):
            wf = walk_forward_w(grid[PRIMARY_FIT][0], cell_dates, cell_markets, scored, markets=(mk,))
            fits[f"{PRIMARY_FIT}/brier/{mk}"] = {"block": PRIMARY_FIT, "objective": "brier", "pool": mk,
                                                  "w_by_date": {d: v[0] for d, v in wf.items()}}
    for f in fits.values():
        f["summary"] = w_summary(f["w_by_date"])

    p_score = restrict(fit_t, score_t, p_fit)
    pm = score_t.p_market
    mb, ml = score_t.brier(pm), score_t.log_score(pm)
    args = (score_t.impossible, score_t.band_snap, len(score_t.snaps))
    rows = []

    def add(fit_key, group, lo, hi, blend, pool_list, extra=None):
        b, lg = score_t.brier(blend), score_t.log_score(blend)
        for pool_name, members in pool_list:
            st = stats(score_t, b, lg, mb, ml, hour_mask(score_t, lo, hi, members),
                       members is None or len(members) > 1)
            if st is not None:
                st.update(candidate=name, fit=fit_key, pool=pool_name, group=group, **(extra or {}))
                rows.append(st)

    primary_pools = pools(score_t)
    agg_pools = primary_pools[:2]
    blends = {}
    for key, f in fits.items():
        if f["pool"] != "ALL":
            continue
        b = f["block"]
        lo, hi = next((lo, hi) for n, lo, hi in FIT_BLOCKS if n == b)
        blend = pool(pm, p_score, w_per_band(score_t, f["w_by_date"], range(lo, hi + 1)), *args)
        blends[key] = blend
        add(key, b, lo, hi, blend, primary_pools if key == f"{PRIMARY_FIT}/brier/ALL" else agg_pools)
    # per hour: h07..h12 on the primary w, h13..h16 on the 13-16 w (when that block is in scope)
    for h, b in HOUR_FIT.items():
        key = f"{b}/brier/ALL"
        if key in blends:
            add(key, f"h{h:02d}", h, h, blends[key], agg_pools)
    # per-market fits (descriptive): that market's own walk-forward w at 07-12
    for key, f in fits.items():
        if f["pool"] == "ALL":
            continue
        blend = pool(pm, p_score, w_per_band(score_t, f["w_by_date"], range(7, 13)), *args)
        add(key, PRIMARY_FIT, 7, 12, blend, [(f["pool"], (f["pool"],))], {"descriptive": True})

    out = {"fits": fits, "rows": rows}
    if placebo and PRIMARY_FIT in masks:
        p_pl_fit, pl_meta = placebo_vector(fit_t, p_fit)
        g_pl = grid_cell_values(fit_t, fit_t.p_market, p_pl_fit, {PRIMARY_FIT: masks[PRIMARY_FIT]})
        wf = walk_forward_w(g_pl[PRIMARY_FIT][0], cell_dates, cell_markets, scored)
        w_pl = {d: v[0] for d, v in wf.items()}
        p_pl = restrict(fit_t, score_t, p_pl_fit)
        blend = pool(pm, p_pl, w_per_band(score_t, w_pl, range(7, 13)), *args)
        st = stats(score_t, score_t.brier(blend), score_t.log_score(blend), mb, ml, hour_mask(score_t, 7, 12), True)
        summ = w_summary(w_pl)
        ok = bool(summ["mean"] <= PLACEBO_W_MAX and st["R"] >= PLACEBO_R_MIN)
        out["placebo"] = {"meta": pl_meta, "w_by_date": w_pl, "summary": summ, "row_ALL_07_12": st,
                          "thresholds": {"mean_w_max": PLACEBO_W_MAX, "R_min": PLACEBO_R_MIN},
                          "verdict": "PASS" if ok else "FAIL"}
    return out


def w0_identity(score_t, p_score):
    blend = pool(score_t.p_market, p_score, 0.0, score_t.impossible, score_t.band_snap, len(score_t.snaps))
    diff = float(np.abs(blend - score_t.p_market).max())
    mb = score_t.brier(score_t.p_market)
    _, c = score_t.cells(score_t.brier(blend), hour_mask(score_t, 0, 23))
    _, m = score_t.cells(mb, hour_mask(score_t, 0, 23))
    r = float(c.sum() / m.sum())
    return {"max_abs_diff": diff, "R_all_hours": r, "verdict": "PASS" if diff == 0.0 and r == 1.0 else "FAIL"}


def floor_only_rows(score_t):
    pm = score_t.p_market
    blend = pool(pm, pm, 0.0, score_t.impossible, score_t.band_snap, len(score_t.snaps), force_floor=True)
    b, lg = score_t.brier(blend), score_t.log_score(blend)
    mb, ml = score_t.brier(pm), score_t.log_score(pm)
    rows = []
    for g, lo, hi in FIT_BLOCKS:
        for pool_name, members in pools(score_t)[:2]:
            st = stats(score_t, b, lg, mb, ml, hour_mask(score_t, lo, hi, members), True)
            st.update(candidate="floor_only", pool=pool_name, group=g)
            rows.append(st)
    return rows


# ----------------------------------------------------------------------------- inputs

def l6_frame(layout, folds, burn_folds, module_path):
    spec = data.CandidateSpec("module", str(module_path))
    f_scored, meta = data.module_predictions(spec, layout, folds)
    f_burn, meta_b = data.module_predictions(spec, layout, burn_folds)
    if set(f_scored.row_key) & set(f_burn.row_key):
        raise data.WalkForwardError("burn-in and scored L6 predictions overlap")
    return pd.concat([f_scored, f_burn], ignore_index=True), {"scored": meta, "burn_in": meta_b,
                                                               "sha256": data.sha256_file(module_path)}


def pre13_captured(args, layout, folds, burn_folds, fit_t, p_mg1_fit):
    """Clarification 1: L6's own-obs stack on the captured-METAR nowcasts (module and nowcasts sha-pinned)."""
    for path, sha, label in ((args.pre13_module, args.pre13_module_sha256, "pre-13 module"),
                             (args.pre13_nowcasts, args.pre13_nowcasts_sha256, "pre-13 nowcasts")):
        actual = data.sha256_file(path) if path else None
        if not sha or actual != sha:
            raise data.Refused(f"refused: {label} sha256 {actual} != the clarification's {sha}")
    os.environ["L6_CAPTURED_NOWCASTS"] = str(args.pre13_nowcasts)
    frame, meta = l6_frame(layout, folds, burn_folds, args.pre13_module)
    p_fit, _, reasons = gta.vector_and_coverage(fit_t, frame)
    f0 = burn_folds[0].dates
    in_f0 = np.isin(fit_t.snaps.date.astype(str).to_numpy(), f0)[fit_t.band_snap]
    meta["burn_in_fold0_equals_mg1"] = bool(np.array_equal(p_fit[in_f0], p_mg1_fit[in_f0]))
    return p_fit, dict(meta, coverage=reasons, nowcasts=str(args.pre13_nowcasts),
                       nowcasts_sha256=args.pre13_nowcasts_sha256)


def check_nbm0712(path, sha):
    actual = data.sha256_file(path)
    if actual != sha or actual != NBM0712_VECTORS_SHA256:
        raise data.Refused(f"refused: NBM 07-12 vectors sha256 {actual} != the rule's {NBM0712_VECTORS_SHA256}")
    return actual


def check_arm_a_refit(path, sha, marker=REFIT_MARKER):
    if LEAD1_ARM_A in Path(path).name or "dev_l8" in str(path).lower():
        raise data.Refused("refused: the lead-1 arm A vectors are never used for a reported composite result")
    if not Path(marker).exists():
        raise data.Refused(f"refused: {marker} does not exist yet; the composite 13-16 part waits for the refit")
    actual = data.sha256_file(path)
    if not sha or actual != sha:
        raise data.Refused(f"refused: arm A refit sha256 {actual} != the clarification's {sha}")
    return actual


def run(args):
    la.screen_input_path(args.layout, "layout")
    start, end = data.check_range(*RANGE)
    layout = data.load_layout(args.layout, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    burn = [d for d in sorted({str(x) for x in layout.snaps.date.astype(str)}) if d <= BURN_IN[1]]
    if not burn or burn[-1] >= scored[0]:
        raise data.Refused("refused: burn-in dates must precede the scored dates")
    burn_folds = data.make_folds(layout.dates, data.parse_date(BURN_IN[0]), data.parse_date(BURN_IN[1]), 7, 1, 0)
    if any(d in scored for f in burn_folds for d in f.dates):
        raise data.Refused("refused: a burn-in fold overlaps the scored dates")
    fit_t = sc.Table(layout, burn + scored)
    score_t = sc.Table(layout, scored)

    controls = {"served": la.positive_control(score_t)}
    w0712 = hour_mask(score_t, 7, 12)
    mb = score_t.brier(score_t.p_market)
    p_mg1_fit, cov_mg1, mg1_reasons = gta.vector_and_coverage(fit_t, la.mg1_frame(fit_t))
    p_mg1 = restrict(fit_t, score_t, p_mg1_fit)
    p_mg1_direct, _ = score_t.candidate_vector(la.mg1_frame(score_t))
    if not np.array_equal(p_mg1, p_mg1_direct):
        raise ControlFailed("refused: MG-1 restricted from the fit table differs from the score table's vector")
    excess = float(score_t.cells(score_t.brier(p_mg1) - mb, w0712)[1].mean())
    controls["mg1"] = {"excess_over_market_07_12": excess, "expected": MG1_EXCESS_0712,
                       "verdict": "PASS" if round(excess, 4) == MG1_EXCESS_0712 else "FAIL"}
    controls["w0_identity_mg1"] = w0_identity(score_t, p_mg1)

    cands = {"mg1": (p_mg1_fit, [b for b, _, _ in FIT_BLOCKS])}
    meta = {"mg1": {"rule": "r-t5-inc-c1 (loss_atlas.mg1_frame)", "coverage_fit_table": mg1_reasons,
                    "coverage_07_12_score": float(restrict_snap(fit_t, score_t, cov_mg1)[w0712].mean())}}
    nbm = None
    if args.nbm0712_vectors:  # item 5: MG-1 controls + the P3d_N 07-12 candidate; no L6 / composite
        actual = check_nbm0712(args.nbm0712_vectors, args.nbm0712_sha256)
        p_n_fit, _, meta_n = gta.load_candidate(args.nbm0712_vectors, args.arm_a_trained_through, layout, folds,
                                                fit_t)
        p_n_score, cov_n, _ = gta.load_candidate(args.nbm0712_vectors, args.arm_a_trained_through, layout, folds,
                                                 score_t)
        same = bool(np.array_equal(restrict(fit_t, score_t, p_n_fit), p_n_score))
        controls["p3d_n_fit_equals_score_vector"] = {"equal": same, "verdict": "PASS" if same else "FAIL"}
        controls["w0_identity_p3d_n_0712"] = w0_identity(score_t, p_n_score)
        cands["p3d_n_0712"] = (p_n_fit, [b for b, lo, hi in FIT_BLOCKS if hi < COMPOSITE_SWITCH_HOUR])
        meta["p3d_n_0712"] = dict(meta_n, sha256=actual, folds=None,
                                  coverage_07_12_score=float(np.asarray(cov_n)[hour_mask(score_t, 7, 12)].mean()))
        nbm = (p_n_score, cov_n)
    if not args.mg1_only and not args.nbm0712_vectors:
        frame, l6_meta = l6_frame(layout, folds, burn_folds, args.l6_module)
        p_l6_fit, cov_l6, l6_reasons = gta.vector_and_coverage(fit_t, frame)
        p_l6 = restrict(fit_t, score_t, p_l6_fit)
        d = float(score_t.cells(score_t.brier(p_l6) - score_t.brier(p_mg1), w0712)[1].mean())
        controls["l6_own_stack"] = {"brier_minus_mg1_07_12": d, "expected": L6_MINUS_MG1_0712,
                                    "verdict": "PASS" if abs(d - L6_MINUS_MG1_0712) <= 1e-6 else "FAIL"}
        burn_mask = ~np.isin(fit_t.snaps.date.astype(str).to_numpy(), scored)
        f0 = burn_folds[0].dates
        in_f0 = np.isin(fit_t.snaps.date.astype(str).to_numpy(), f0)[fit_t.band_snap]
        l6_meta["burn_in_fold0_equals_mg1"] = bool(np.array_equal(p_l6_fit[in_f0], p_mg1_fit[in_f0]))
        l6_meta["burn_in_snapshots"] = int(burn_mask.sum())
        blocks = [b for b, lo, hi in FIT_BLOCKS if hi < COMPOSITE_SWITCH_HOUR]
        p_pre_fit, pre_name = p_l6_fit, "MG-1 + L6 own-obs stack"
        if args.pre13_module:
            p_pre_fit, pre_meta = pre13_captured(args, layout, folds, burn_folds, fit_t, p_mg1_fit)
            pre_name = f"MG-1 + L6 own-obs stack, captured-METAR re-spec ({pre_meta['nowcasts_sha256']})"
            meta["pre13_captured"] = pre_meta
        p_comp_fit = p_pre_fit
        comp_rule = f"local_hour < {COMPOSITE_SWITCH_HOUR}: {pre_name}; >= 13: pending the afternoon vectors"
        if args.arm_a_refit:
            sha = check_arm_a_refit(args.arm_a_refit, args.arm_a_refit_sha256)
            p_a_fit, cov_a, meta_a = gta.load_candidate(args.arm_a_refit, args.arm_a_trained_through, layout,
                                                        folds, fit_t)
            pre = (fit_t.local_hour < COMPOSITE_SWITCH_HOUR)[fit_t.band_snap]
            p_comp_fit = np.where(pre, p_pre_fit, p_a_fit)
            blocks = [b for b, _, _ in FIT_BLOCKS]
            comp_rule = (f"local_hour < {COMPOSITE_SWITCH_HOUR}: {pre_name}; >= "
                         f"{COMPOSITE_SWITCH_HOUR}: {Path(args.arm_a_refit).name} ({sha})")
            meta["arm_a_refit"] = dict(meta_a, sha256=sha)
        controls["w0_identity_composite"] = w0_identity(score_t, restrict(fit_t, score_t, p_comp_fit))
        cands["composite"] = (p_comp_fit, blocks)
        meta["l6_own_stack"] = dict(l6_meta, coverage=l6_reasons)
        meta["composite"] = {"rule": comp_rule, "blocks": blocks}
    failed = [k for k, v in controls.items() if v["verdict"] != "PASS"]
    if failed:
        raise ControlFailed(f"refused: controls failed {failed}: {json.dumps(sc._clean(controls))}")

    floor_rows = floor_only_rows(score_t)
    floor_r = {(r["pool"], r["group"]): r["R"] for r in floor_rows}
    results = {}
    for name, (p_fit, blocks) in cands.items():
        res = score_candidate(name, fit_t, score_t, p_fit, blocks)
        prim = next(r for r in res["rows"] if r["fit"] == f"{PRIMARY_FIT}/brier/ALL" and r["pool"] == "ALL"
                    and r["group"] == PRIMARY_FIT)
        if nbm is not None and name == "mg1":  # item 5 control, before the candidate is scored
            ok = round(prim["R"], 7) == NBM0712_MG1_R
            controls["mg1_run2_reproduces"] = {"R": prim["R"], "expected": NBM0712_MG1_R,
                                               "verdict": "PASS" if ok else "FAIL"}
            if not ok:
                raise ControlFailed(f"refused: MG-1 07-12 R {prim['R']} != run 2's {NBM0712_MG1_R}")
        wbar = res["fits"][f"{PRIMARY_FIT}/brier/ALL"]["summary"]["mean"]
        res["reading"] = {"primary_row": {k: prim[k] for k in ("R", "ci95_date", "ci95_crossed", "mde80_R",
                                                                "n_market_days", "n_dates", "log_ratio")},
                          "wbar": wbar, "floor_only_R": floor_r[("ALL", PRIMARY_FIT)],
                          "placebo": res.get("placebo", {}).get("verdict"),
                          "verdict": reading(wbar, prim, floor_r[("ALL", PRIMARY_FIT)],
                                             res.get("placebo", {}).get("verdict") == "PASS")}
        sec = [r for r in res["rows"] if r["fit"] == "13-16/brier/ALL" and r["group"] == "13-16"
               and r["pool"] in ("ALL", "PRIMARY5")]
        if sec:  # clarification 1: the same reading as a SECONDARY reading on the 13-16 row
            w1316 = res["fits"]["13-16/brier/ALL"]["summary"]["mean"]
            res["reading_13_16"] = {r["pool"]: {"R": r["R"], "ci95_crossed": r.get("ci95_crossed"),
                                                "ci95_date": r["ci95_date"], "wbar": w1316,
                                                "floor_only_R": floor_r[(r["pool"], "13-16")],
                                                "verdict": reading(w1316, r, floor_r[(r["pool"], "13-16")],
                                                                   res.get("placebo", {}).get("verdict") == "PASS")}
                                    for r in sec}
        results[name] = res

    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    extra = {}
    if nbm is not None:
        extra = {"nbm0712_rule_sha256": NBM0712_RULE_SHA256,
                 "descriptive_p3d_n_0712": {"label": "DESCRIPTIVE - P3d_N alone vs market, not for a decision",
                                            "rows": descriptive_rows(score_t, nbm[0], nbm[1], NBM0712_WINDOWS)}}
    return {**extra, "schema": SCHEMA, "rule_sha256": RULE_SHA256,
            "clarification_1_sha256": CLARIFICATION_1_SHA256 if args.pre13_module or args.arm_a_refit else None, "evidence_class": "development (dev window, provisional)",
            "code_sha256": code, "gap_atlas_code_sha256": hashlib.sha256(Path(gta.__file__).read_bytes()).hexdigest(),
            "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": layout.manifest_sha256,
            "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                           "n_scored_dates": len(scored), "n_market_days": len(score_t.keys),
                           "n_fit_dates": len(burn) + len(scored)},
            "constants": {"eps": EPS, "w_grid": [float(W_GRID[0]), float(W_GRID[-1]), len(W_GRID)],
                          "gap_days": GAP_DAYS, "draws": sc.DRAWS, "seed": sc.SEED, "mass": "market's own sum",
                          "objective_primary": "pooled cell-mean Brier", "objective_secondary": "log score"},
            "controls": controls, "floor_only": floor_rows, "candidates": meta, "results": results,
            "discipline": "each blend vs the market only; no candidate-minus-candidate deltas"}


DESCRIPTIVE_NOTE_SHA256 = "7928629405d812dd4642e39c1e02d7ff31542deabc10176f7c59147e9975332b"
DESCRIPTIVE_WINDOWS = (("h13", 13, 13), ("h14", 14, 14), ("h15", 15, 15), ("h16", 16, 16), ("13-16", 13, 16))


def descriptive_rows(score_t, p, cov, windows=DESCRIPTIVE_WINDOWS):
    """DESCRIPTIVE (not pre-registered for a decision): an unblended candidate and the floor-only control vs market."""
    pm = score_t.p_market
    floor = pool(pm, pm, 0.0, score_t.impossible, score_t.band_snap, len(score_t.snaps), force_floor=True)
    mb, ml = score_t.brier(pm), score_t.log_score(pm)
    vecs = {"candidate": (score_t.brier(p), score_t.log_score(p)),
            "floor_only": (score_t.brier(floor), score_t.log_score(floor))}
    rows = []
    for g, lo, hi in windows:
        for pool_name, members in pools(score_t)[:2]:
            mask = hour_mask(score_t, lo, hi, members)
            for name, (b, lg) in vecs.items():
                st = stats(score_t, b, lg, mb, ml, mask, True)
                st.update(candidate=name, pool=pool_name, group=g,
                          covered_share=float(cov[mask].mean()) if name == "candidate" else None)
                rows.append(st)
    return rows


def run_descriptive(args):
    la.screen_input_path(args.layout, "layout")
    actual = data.sha256_file(args.descriptive_vectors)
    if actual != args.descriptive_sha256:
        raise data.Refused(f"refused: descriptive vectors sha256 {actual} != {args.descriptive_sha256}")
    start, end = data.check_range(*RANGE)
    layout = data.load_layout(args.layout, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    score_t = sc.Table(layout, scored)
    controls = {"served": la.positive_control(score_t)}
    p, cov, meta = gta.load_candidate(args.descriptive_vectors, args.arm_a_trained_through, layout, folds, score_t)
    return {"schema": SCHEMA + "+descriptive", "label": "DESCRIPTIVE - not pre-registered for a decision",
            "note_sha256": DESCRIPTIVE_NOTE_SHA256, "vectors_sha256": actual, "controls": controls,
            "candidate": dict(meta, folds=None), "layout_manifest_sha256": layout.manifest_sha256,
            "population": {"scored_first": scored[0], "scored_last": scored[-1], "n_scored_dates": len(scored),
                           "n_market_days": len(score_t.keys)},
            "rows": descriptive_rows(score_t, p, cov)}


def render_descriptive(payload):
    L = ["# P3d_N alone vs the market, 13-16 (DESCRIPTIVE - not pre-registered for a decision)", "",
         f"Note `{payload['note_sha256']}`; vectors `{payload['vectors_sha256']}`; served control "
         f"{payload['controls']['served']['verdict']}. Scored {payload['population']['scored_first']}.."
         f"{payload['population']['scored_last']}.", "",
         "| Vector | Pool | Window | n md | R | crossed | date | log ratio | covered |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in payload["rows"]:
        cs = "" if r["covered_share"] is None else f"{r['covered_share']:.3f}"
        L.append(f"| {r['candidate']} | {r['pool']} | {r['group']} | {r['n_market_days']} | {_f(r['R'], 4)} | "
                 f"{_ci(r['ci95_crossed'], 4)} | {_ci(r['ci95_date'], 4)} | {_f(r['log_ratio'], 4)} | {cs} |")
    return "\n".join(L) + "\n"


def restrict_snap(fit_t, score_t, snap_values):
    pos = fit_t.snap_pos.reindex(score_t.snaps.row_key.to_numpy()).to_numpy().astype(int)
    return np.asarray(snap_values)[pos]


# ----------------------------------------------------------------------------- report

def _f(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{d}f}"


def _ci(ci, d=3):
    return f"[{_f(ci[0], d)}, {_f(ci[1], d)}]" if ci else "-"


def render(payload):
    ctl, pop = payload["controls"], payload["population"]
    L = ["# Market blend (L11): walk-forward log pool of market and candidate, vs the market", "",
         f"Rule `{payload['rule_sha256']}`. Development evidence only. Scored {pop['scored_first']}.."
         f"{pop['scored_last']} ({pop['n_scored_dates']} dates, {pop['n_market_days']} market-days); burn-in "
         f"{pop['burn_in_dates'][0]}..{pop['burn_in_dates'][-1]}. R = blend Brier / market Brier; brackets "
         "crossed [date-clustered] 95% (2,000 draws, seed 20260921).", "", "## Controls", ""]
    for k, v in ctl.items():
        L.append(f"- {k}: {v['verdict']} " + json.dumps({kk: vv for kk, vv in v.items()
                                                          if kk not in ("verdict", "ci95", "control")}))
    L += ["", "## Readings (PRIMARY: ALL, 07-12, pooled 07-12 Brier fit)", ""]
    for name, res in payload["results"].items():
        r = res["reading"]
        p = r["primary_row"]
        L.append(f"- **{name}**: R {_f(p['R'], 4)} crossed {_ci(p['ci95_crossed'], 4)} date {_ci(p['ci95_date'], 4)}; "
                 f"mean w {_f(r['wbar'], 3)}; floor-only R {_f(r['floor_only_R'], 4)}; placebo {r['placebo']}; "
                 f"MDE80 {_f(p['mde80_R'], 3)} -> {r['verdict']}")
        for pool_name, r2 in res.get("reading_13_16", {}).items():
            L.append(f"  - SECONDARY 13-16 {pool_name}: R {_f(r2['R'], 4)} crossed {_ci(r2['ci95_crossed'], 4)} date "
                     f"{_ci(r2['ci95_date'], 4)}; mean 13-16 w {_f(r2['wbar'], 3)}; floor-only R "
                     f"{_f(r2['floor_only_R'], 4)} -> {r2['verdict']}")
    L += ["", "## Rows (pooled fits)", "",
          "| Candidate | Fit | Pool | Group | n md | R | crossed | date | log ratio | MDE80 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, res in payload["results"].items():
        for r in res["rows"]:
            if r.get("descriptive") or (r["pool"] not in ("ALL", "PRIMARY5") and r["group"] != PRIMARY_FIT):
                continue
            L.append(f"| {name} | {r['fit']} | {r['pool']} | {r['group']} | {r['n_market_days']} | {_f(r['R'], 4)} | "
                     f"{_ci(r.get('ci95_crossed'))} | {_ci(r['ci95_date'])} | {_f(r['log_ratio'], 4)} | "
                     f"{_f(r['mde80_R'])} |")
    L += ["", "## Floor-only control (w -> 0+: market + hard floor, same mass, no candidate)", "",
          "| Pool | Block | R | crossed | date |", "| --- | --- | --- | --- | --- |"]
    for r in payload["floor_only"]:
        L.append(f"| {r['pool']} | {r['group']} | {_f(r['R'], 4)} | {_ci(r['ci95_crossed'], 4)} | {_ci(r['ci95_date'], 4)} |")
    L += ["", "## w paths", "", "| Candidate | Fit | mean | median | min | max | first | last | zeros |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, res in payload["results"].items():
        for key, f in res["fits"].items():
            s = f["summary"]
            L.append(f"| {name} | {key} | {_f(s['mean'], 3)} | {_f(s['median'], 2)} | {_f(s['min'], 2)} | "
                     f"{_f(s['max'], 2)} | {_f(s['first'], 2)} | {_f(s['last'], 2)} | {s['n_zero']}/{s['n_dates']} |")
        if "placebo" in res:
            pl = res["placebo"]
            s, r = pl["summary"], pl["row_ALL_07_12"]
            L.append(f"| {name} | PLACEBO 07-12 | {_f(s['mean'], 3)} | {_f(s['median'], 2)} | {_f(s['min'], 2)} | "
                     f"{_f(s['max'], 2)} | {_f(s['first'], 2)} | {_f(s['last'], 2)} | {s['n_zero']}/{s['n_dates']} |")
    L += ["", "Placebo: " + "; ".join(f"{n} {res['placebo']['verdict']} (R {_f(res['placebo']['row_ALL_07_12']['R'], 4)})"
                                      for n, res in payload["results"].items() if "placebo" in res)]
    if "descriptive_p3d_n_0712" in payload:
        d = payload["descriptive_p3d_n_0712"]
        L += ["", f"## {d['label']}", "", "| Vector | Pool | Window | n md | R | crossed | date | log ratio | covered |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in d["rows"]:
            cs = "" if r["covered_share"] is None else f"{r['covered_share']:.3f}"
            L.append(f"| {r['candidate']} | {r['pool']} | {r['group']} | {r['n_market_days']} | {_f(r['R'], 4)} | "
                     f"{_ci(r['ci95_crossed'], 4)} | {_ci(r['ci95_date'], 4)} | {_f(r['log_ratio'], 4)} | {cs} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.market_blend")
    ap.add_argument("--layout", required=True)
    ap.add_argument("--l6-module", default=str(gta.DEFAULT_L6_MODULE))
    ap.add_argument("--mg1-only", action="store_true")
    ap.add_argument("--pre13-module")
    ap.add_argument("--pre13-module-sha256")
    ap.add_argument("--pre13-nowcasts")
    ap.add_argument("--pre13-nowcasts-sha256")
    ap.add_argument("--arm-a-refit", help="afternoon (13:00+) vectors; clarification 1: P3d_N")
    ap.add_argument("--arm-a-refit-sha256")
    ap.add_argument("--arm-a-trained-through", default="2025-12-31")
    ap.add_argument("--descriptive-vectors", help="DESCRIPTIVE: an unblended candidate vs market at 13-16")
    ap.add_argument("--descriptive-sha256")
    ap.add_argument("--nbm0712-vectors", help="item 5: P3d_N at 07-12 in place of MG-1 + L6 (rule 94b1603a)")
    ap.add_argument("--nbm0712-sha256")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    if args.descriptive_vectors:
        try:
            payload = run_descriptive(args)
        except (data.Refused, data.LayoutError, data.LeakageError, data.WalkForwardError) as exc:
            print(str(exc), file=sys.stderr)
            return getattr(exc, "exit_code", 2)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1, default=str).encode("utf-8")
        (out / "p3d_n_descriptive.json").write_bytes(blob)
        (out / "p3d_n_descriptive.md").write_text(render_descriptive(payload), encoding="utf-8", newline="\n")
        print(json.dumps({"json": str(out / "p3d_n_descriptive.json"), "sha256": hashlib.sha256(blob).hexdigest()}))
        return 0
    try:
        payload = run(args)
    except (data.Refused, data.LayoutError, data.LeakageError, data.WalkForwardError) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1).encode("utf-8")
    path = out / "market_blend_rows.json"
    path.write_bytes(blob)
    (out / "market_blend.md").write_text(render(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"json": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                      "controls": {k: v["verdict"] for k, v in payload["controls"].items()},
                      "readings": {k: v["reading"]["verdict"] for k, v in payload["results"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
