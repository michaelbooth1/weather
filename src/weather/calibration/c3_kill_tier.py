r"""C3 kill tier: frozen 110b T+1 fair value against 88a two-sided mids (lane L16; rule DRAFT, not frozen).

Rule: the reviewed DRAFT ``docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-DRAFT.md`` (sha256
cd4d814f...) as amended by ``c3-t1-fair-value-kill-tier-REVISION-1-2026-10-31.md`` (master D1, approved with
revisions) and ``c3-t1-fair-value-kill-tier-REVISION-2-2026-10-31.md`` (deciding bounds use the wider of the
date-clustered and block-3 intervals) and ``c3-t1-fair-value-kill-tier-REVISION-3-2026-10-31.md`` (the w gate, step 5,
too); the shas and this file's are pinned by master in a ``pending`` ledger row before any computation.
Kill-only: the outcomes are KILL (at edge size), NOT KILLED, INCONCLUSIVE and DESCRIPTIVE (power at edge size
below 0.5: reported only, cannot drop A1); VOID when a control fails. No outcome is a pass, an edge claim or a
promotion.

Inputs are the outputs of the frozen scorer (``codex/t1-fair-value-scorer-20260927`` @ ``FROZEN_SCORER_COMMIT``)
run separately from its own clean worktree; this driver never imports or edits that code. It reads only the
``report.json`` rows it is given, after refusals R1-R5, and writes only into a new ``--out`` directory.

    python -m weather.calibration.c3_kill_tier --report <run1>\report.json --report-repeat <run2>\report.json
        --bundle-pair <buildA>\<day> <buildB>\<day> [...one per UTC day] --scorer-worktree <clean d937b34 tree>
        --row80-receipt <row 80 look receipt> --out <new dir>

Exit 0 = result written; 2 = refused (nothing written); 7 = VOID (a control failed; a VOID receipt is written).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from weather.paths import REPO_ROOT

SCHEMA = "c3_kill_tier/1"
FROZEN_SCORER_COMMIT = "d937b34ab1d50cd4b8e35e80901184f7f0f82a9f"
BUCKETS_COMMIT = "bf03a8d4104327913b0b4062f3eb2ad8a7a7e9c9"  # Amendment 3 buckets: reported only, run separately
RULE_PATH = "docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-DRAFT.md"
RULE_REVIEWED_SHA256 = "cd4d814f4144a5e0a72d7632f413d000174d2cade4c4ce8d50f0ee5f6f76b5f6"   # master D1 reviewed this
REVISION_PATH = "docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-REVISION-1-2026-10-31.md"
REVISION_2_PATH = "docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-REVISION-2-2026-10-31.md"
REVISION_3_PATH = "docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-REVISION-3-2026-10-31.md"
# Date-gate trace (code read only, REVISION-1 section 3): the frozen builder and scorer at FROZEN_SCORER_COMMIT have
# no 09-30..10-15 gate (src/maker_core/shadow and EMBARGO_WINDOWS do not exist there), so no override is applied.
DATE_GATE_TRACE = dict(commit=FROZEN_SCORER_COMMIT, embargo_gate_found=False, override_applied=False)
TARGET_START, TARGET_END = date(2026, 9, 25), date(2026, 10, 8)    # R1
DAY_START, DAY_END = date(2026, 9, 23), date(2026, 10, 7)          # R2, UTC bundle days
EXCLUDED_CELLS = (("austin", "2026-10-03"),)                       # R3, export manifest C7
ROW80_RECEIPT_SHA256 = "a91915e52cbbfebf12ab650d4ae07d95082415727c767120f52f757fd4e8feda"  # R4: row 80 look receipt.json, pinned by master 2026-10-31 (C3 GO)

EPS = 1e-4
GAP_DAYS = 1
W_GRID = np.arange(101) / 100.0
PLACEBO_SEEDS = tuple(20260921 + j for j in range(20))
BOOT_B = 2000
BOOT_SEED = 20261024
BLOCK_LEN = 3        # REVISION-2: circular moving blocks of 3 consecutive (ordered, present) dates, same B and seed
BH_Q = 0.10
MEAN_W_MIN = 0.05
MIN_DATES = 10
MIN_EVENT_HOURS = 200
# Edge size (REVISION-1 section 1; exhaustion register section 6, L15 815e642c3): a signal correlated rho with the
# market residual cuts a calibrated market's squared error by rho^2, so a 5% Brier gain needs rho >= sqrt(0.05).
EDGE_GAIN = 0.05
DELTA_EDGE = math.sqrt(EDGE_GAIN)   # 0.2236
Z95 = 1.959963984540054
POWER_MIN = 0.5
REPRO_TOL = 1e-12
KILL_LEAD = 1
KILL_SOURCES = ("nbp", "fallback")
BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))

# Accepted as proposed by master D1 (2026-10-31); still pre-freeze until the ledger row pins this file.
BURN_IN_DATES = 4          # OP1 (the forward test uses 7)
MIN_MARKETS = 5            # OP3 (the frozen scorer's UNDERPOWERED rule is 10)
KILL_SCOPE = ("accepted D1: a KILL at edge size drops A1 as a solo arm and keeps A2 and A3, by dated clarification "
              "before the forward freeze")   # OP2, recorded only
AUSTIN_OPTION = "a"        # OP4: Austin 10-03 may sit inside whole segments; any selected Austin 10-03 row refuses
PROVISIONAL = {"OP1_burn_in_dates": BURN_IN_DATES, "OP2_kill_scope": KILL_SCOPE, "OP3_min_markets": MIN_MARKETS,
               "OP4_austin_option": AUSTIN_OPTION}

# K3 synthetic panel (fixed before freeze). Built-in market ids only; no real price or label enters.
K3 = dict(seed=20261031, null_seed=20261101, n_dates=14, n_bands=6, alpha=1.0, m_noise=0.8, c_noise=0.4,
          hours_utc=(16, 17, 18, 19, 20, 21),
          markets=("toronto", "nyc", "atlanta", "chicago", "dallas", "denver", "houston", "miami"))

EXIT_OK, EXIT_REFUSED, EXIT_VOID = 0, 2, 7
KILL, NOT_KILLED, INCONCLUSIVE, VOID = "KILL", "NOT KILLED", "INCONCLUSIVE", "VOID"
DESCRIPTIVE = "DESCRIPTIVE"


class Refused(Exception):
    """A refusal: exit 2, nothing written."""


class Void(Exception):
    """A control failed: exit 7, VOID receipt."""

    def __init__(self, control, detail):
        super().__init__(f"{control} failed")
        self.control, self.detail = control, detail


def _mb():
    # Imported unchanged and lazily, so no refusal depends on its import-time side effects.
    from weather.calibration import market_blend
    return market_blend


def _timezones():
    # Built-in specs only (lazy: after the refusals). All panel markets are North American and no DST
    # transition falls inside 09-24..10-08, but the local hour is still taken from each market's own zone.
    from weather.market.market_registry import BUILTIN_SPECS
    return {spec.id: ZoneInfo(spec.timezone) for spec in BUILTIN_SPECS}


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------------- panel arrays

class Flat:
    """Band-level arrays (m, c, y, snap) and snapshot-level metadata for selected event-hours."""

    def __init__(self, m, c, y, snap, dates, markets, hours, leads, sources, captured):
        self.m, self.c, self.y = (np.asarray(a, float) for a in (m, c, y))
        self.snap = np.asarray(snap, int)
        self.date, self.market = np.asarray(dates, str), np.asarray(markets, str)
        self.hour, self.lead = np.asarray(hours, int), np.asarray(leads, int)
        self.source, self.captured = np.asarray(sources, str), np.asarray(captured, str)
        self.n = len(self.date)
        order = np.argsort(self.snap, kind="stable")
        self.bands = np.split(order, np.cumsum(np.bincount(self.snap, minlength=self.n))[:-1]) if self.n else []

    def subset(self, keep):
        keep = np.asarray(keep, bool)
        new = np.full(self.n, -1)
        new[keep] = np.arange(int(keep.sum()))
        band = keep[self.snap]
        return Flat(self.m[band], self.c[band], self.y[band], new[self.snap[band]], self.date[keep],
                    self.market[keep], self.hour[keep], self.lead[keep], self.source[keep], self.captured[keep])


def flatten(rows):
    tzs = _timezones()
    m, c, y, snap, meta = [], [], [], [], defaultdict(list)
    for i, row in enumerate(rows):
        at = datetime.fromisoformat(row["captured_at"])
        if at.tzinfo is None or row["market_id"] not in tzs:
            raise Refused(f"row {i}: naive captured_at or unregistered market")
        meta["dates"].append(row["target_date"])
        meta["markets"].append(row["market_id"])
        meta["hours"].append(at.astimezone(tzs[row["market_id"]]).hour)
        meta["leads"].append(int(row["lead"]))
        meta["sources"].append(row["source"])
        meta["captured"].append(at.astimezone(timezone.utc).isoformat())
        for band in row["bands"]:
            m.append(float(band["mid"]))
            c.append(float(band["probability"]))
            y.append(float(band["observed_yes"]))
            snap.append(i)
    return Flat(m, c, y, snap, **meta)


def renormalise(flat, v):
    """Clip to [EPS, 1 - EPS], then scale each snapshot to the market's own mass sum(m)."""
    v = np.clip(v, EPS, 1.0 - EPS)
    s_m = np.bincount(flat.snap, weights=flat.m, minlength=flat.n)
    s_v = np.bincount(flat.snap, weights=v, minlength=flat.n)
    return v * (s_m / s_v)[flat.snap]


def placebo_s(flat, s, seed):
    """Calibration-matched placebo disagreement: within (market, lead, local hour), a fixed-seed derangement of
    the target dates; snapshot k of a date takes donor snapshot min(k, n - 1). Bands are aligned by descending
    mid rank (the donor ladder may differ); unmatched bands get 0. No label enters."""
    groups = {}
    for i in range(flat.n):
        key = (str(flat.market[i]), int(flat.lead[i]), int(flat.hour[i]))
        groups.setdefault(key, {}).setdefault(str(flat.date[i]), []).append(i)
    rng = np.random.default_rng(seed)
    out, donor, unshuffled = np.zeros(len(s)), np.full(flat.n, -1), 0
    for key in sorted(groups):
        by_date = groups[key]
        for snaps in by_date.values():
            snaps.sort(key=lambda i: (flat.captured[i], i))
        ds = sorted(by_date)
        if len(ds) < 2:
            unshuffled += sum(len(v) for v in by_date.values())
            continue
        perm = _mb().derangement(len(ds), rng)
        for a, d in enumerate(ds):
            donors = by_date[ds[perm[a]]]
            for k, i in enumerate(by_date[d]):
                j = donors[min(k, len(donors) - 1)]
                donor[i] = j
                oi = flat.bands[i][np.argsort(-flat.m[flat.bands[i]], kind="stable")]
                oj = flat.bands[j][np.argsort(-flat.m[flat.bands[j]], kind="stable")]
                r = min(len(oi), len(oj))
                out[oi[:r]] = s[oj[:r]]
    return out, donor, unshuffled


def placebo_candidates(flat, c, seeds=PLACEBO_SEEDS):
    s = c - flat.m
    cands, unshuffled = [], []
    for seed in seeds:
        sp, _, u = placebo_s(flat, s, seed)
        cands.append(renormalise(flat, flat.m + sp))
        unshuffled.append(u)
    return cands, unshuffled


# ----------------------------------------------------------------------------- P0

def rho(S):
    S = np.asarray(S, float)
    n, sx, sy, sxx, syy, sxy = np.moveaxis(S, -1, 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cov = sxy - sx * sy / n
        return cov / np.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n))


def sums_by_date(flat, c):
    """Per target date sufficient sums (n, s, e, ss, ee, se) with s = c - m, e = y - m."""
    dates = np.unique(flat.date)
    di = np.searchsorted(dates, flat.date)[flat.snap]
    s, e = c - flat.m, flat.y - flat.m
    cols = (np.ones_like(s), s, e, s * s, e * e, s * e)
    return dates, np.stack([np.bincount(di, weights=w, minlength=len(dates)) for w in cols], axis=1)


def boot_counts(n_dates, b=BOOT_B, seed=BOOT_SEED):
    idx = np.random.default_rng(seed).integers(n_dates, size=(b, n_dates))
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)


def block_counts(n_dates, b=BOOT_B, seed=BOOT_SEED, length=BLOCK_LEN):
    """Circular moving-block bootstrap: ceil(n / length) blocks of `length` consecutive dates (wrapping), truncated
    to n, as per-date counts. Circular, so every date has equal expected weight (DWL row 84)."""
    k = -(-n_dates // length)
    starts = np.random.default_rng(seed).integers(n_dates, size=(b, k))
    idx = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)


def interval(draws_dc, draws_b3):
    """Both intervals, and the wider of them (lower = min, upper = max; SE = max) for every deciding bound."""
    dc, b3 = _quantiles(draws_dc), _quantiles(draws_b3)
    lo = None if dc[0] is None or b3[0] is None else min(dc[0], b3[0])
    hi = None if dc[1] is None or b3[1] is None else max(dc[1], b3[1])
    sd, sb = _se(draws_dc), _se(draws_b3)
    return dict(ci95_date_clustered=dc, ci95_block3=b3, ci95_wider=[lo, hi], se_date_clustered=sd, se_block3=sb,
                se_wider=None if sd is None or sb is None else max(sd, sb))


def _se(draws):
    ok = np.isfinite(draws)
    return float(np.std(draws[ok], ddof=1)) if ok.sum() > 1 else None


def power_at(edge, se):
    """P(upper 95% bound < edge | true effect 0), normal approximation: Phi(edge / se - 1.96)."""
    if se is None or not math.isfinite(se) or se <= 0:
        return None
    return 0.5 * (1.0 + math.erf((edge / se - Z95) / math.sqrt(2.0)))


def _quantiles(draws):
    ok = np.isfinite(draws)
    return [float(q) for q in np.quantile(draws[ok], [0.025, 0.975])] if ok.any() else [None, None]


def p0(flat, c, placebos):
    dates, sc = sums_by_date(flat, c)
    spl = [sums_by_date(flat, cp)[1] for cp in placebos]
    rc, rp = float(rho(sc.sum(axis=0))), [float(rho(s.sum(axis=0))) for s in spl]

    def delta_draws(counts):
        return rho(counts @ sc) - np.mean([rho(counts @ s) for s in spl], axis=0)

    def p_of(draws):
        return (1 + int(np.sum(~(draws > 0)))) / (len(draws) + 1)   # an undefined draw counts against the signal

    draws, draws_b3 = delta_draws(boot_counts(len(dates))), delta_draws(block_counts(len(dates)))
    iv = interval(draws, draws_b3)
    ci, se = iv["ci95_wider"], iv["se_wider"]
    result = dict(dates=int(len(dates)), entries=int(len(c)), rho_c=rc, rho_placebo=rp,
                  rho_placebo_mean=float(np.mean(rp)), delta=rc - float(np.mean(rp)), delta_ci95=ci,
                  delta_ci95_date_clustered=iv["ci95_date_clustered"], delta_ci95_block3=iv["ci95_block3"],
                  se_delta_date_clustered=iv["se_date_clustered"], se_delta_block3=iv["se_block3"],
                  p_one_sided=max(p_of(draws), p_of(draws_b3)), p_one_sided_date_clustered=p_of(draws),
                  p_one_sided_block3=p_of(draws_b3), valid_replicates=int(np.isfinite(draws).sum()),
                  valid_replicates_block3=int(np.isfinite(draws_b3).sum()),
                  delta_edge=DELTA_EDGE, se_delta=se, vif=None if se is None else float(len(c) * se * se),
                  power_at_edge=power_at(DELTA_EDGE, se),
                  edge_excluded=bool(ci[1] is not None and ci[1] < DELTA_EDGE))
    return result, (dates, sc, spl)


def bh(pvals, q=BH_Q):
    p = np.asarray(pvals, float)
    order = np.argsort(p, kind="stable")
    passed = p[order] <= q * np.arange(1, len(p) + 1) / len(p)
    k = int(np.max(np.nonzero(passed)[0])) + 1 if passed.any() else 0
    reject = np.zeros(len(p), bool)
    reject[order[:k]] = True
    return reject.tolist()


# ----------------------------------------------------------------------------- w

def cells_of(flat):
    keys = sorted(set(zip(flat.date.tolist(), flat.market.tolist())))
    index = {k: i for i, k in enumerate(keys)}
    return keys, np.array([index[k] for k in zip(flat.date.tolist(), flat.market.tolist())], int)


def cell_brier(flat, g, snap_cell, n_cells):
    """The frozen scorer's aggregation: band mean, then hour mean within (target date, market)."""
    per_snap = (np.bincount(flat.snap, weights=(g - flat.y) ** 2, minlength=flat.n)
                / np.bincount(flat.snap, minlength=flat.n))
    return (np.bincount(snap_cell, weights=per_snap, minlength=n_cells)
            / np.bincount(snap_cell, minlength=n_cells))


def _no_impossible(flat):
    return np.zeros(len(flat.m), bool)   # T+1: no target-day observation, so no band is impossible


def grid_values(flat, c, snap_cell, n_cells):
    mb, imp = _mb(), _no_impossible(flat)
    return np.stack([cell_brier(flat, mb.pool(flat.m, c, w, imp, flat.snap, flat.n), snap_cell, n_cells)
                     for w in W_GRID])


def walk(values, keys, dates):
    scored = dates[BURN_IN_DATES:]
    wf = _mb().walk_forward_w(values, [k[0] for k in keys], [k[1] for k in keys], scored,
                              gap_days=GAP_DAYS, w_grid=W_GRID)
    wi = {d: int(np.argmin(np.abs(W_GRID - w))) for d, (w, _) in wf.items()}
    blend = np.array([values[wi[d], i] if d in wi else np.nan for i, (d, _) in enumerate(keys)])
    return wf, blend


def paired(diff, cell_dates, scored):
    sel = np.isin(cell_dates, scored)
    di = np.searchsorted(scored, cell_dates[sel])
    ds = np.bincount(di, weights=diff[sel], minlength=len(scored))
    nc = np.bincount(di, minlength=len(scored)).astype(float)
    draws = [(k @ ds) / (k @ nc) for k in (boot_counts(len(scored)), block_counts(len(scored)))]
    iv = interval(*draws)
    # ci95 is the date-clustered interval, reported; every deciding use (steps 5 and 6, power) takes ci95_wider.
    return dict(estimate=float(ds.sum() / nc.sum()), ci95=iv["ci95_date_clustered"], **iv)


def w_gate(flat, c, placebos):
    keys, snap_cell = cells_of(flat)
    n_cells = len(keys)
    cell_dates = np.array([k[0] for k in keys])
    dates = sorted(set(cell_dates.tolist()))
    scored = np.array(dates[BURN_IN_DATES:])
    if not len(scored):
        return dict(holds=False, reason="no_scored_dates", scored_dates=0), []
    mb, imp = _mb(), _no_impossible(flat)
    values = grid_values(flat, c, snap_cell, n_cells)
    market = cell_brier(flat, flat.m, snap_cell, n_cells)
    floor = cell_brier(flat, mb.pool(flat.m, flat.m, 0.0, imp, flat.snap, flat.n, force_floor=True),
                       snap_cell, n_cells)
    wf, blend = walk(values, keys, dates)
    placebo = np.mean([walk(grid_values(flat, cp, snap_cell, n_cells), keys, dates)[1] for cp in placebos], axis=0)
    sel = np.isin(cell_dates, scored)
    mean_w = float(np.mean([wf[d][0] for d in scored]))
    vs_placebo = paired(blend - placebo, cell_dates, scored)
    vs_floor = paired(blend - floor, cell_dates, scored)
    # REVISION-3: step 5 uses the wider (date-clustered vs block-3) upper bound of each interval.
    holds = bool(mean_w >= MEAN_W_MIN and vs_placebo["ci95_wider"][1] is not None and vs_placebo["ci95_wider"][1] < 0
                 and vs_floor["ci95_wider"][1] is not None and vs_floor["ci95_wider"][1] < 0)
    vs_market = paired(blend - market, cell_dates, scored)
    edge_gain = EDGE_GAIN * float(market[sel].mean())   # the edge-size Brier gain on the scored cells
    lo = vs_market["ci95_wider"][0]
    rows = [dict(kind="brier_sums", date=str(d), w=wf[d][0], fit_cells=wf[d][1], cells=int((cell_dates == d).sum()),
                 blend=float(blend[cell_dates == d].sum()), market=float(market[cell_dates == d].sum()),
                 placebo=float(placebo[cell_dates == d].sum()), floor_only=float(floor[cell_dates == d].sum()))
            for d in scored]
    return dict(holds=holds, mean_w=mean_w, scored_dates=int(len(scored)), burn_in_dates=dates[:BURN_IN_DATES],
                w_by_date={str(d): wf[d][0] for d in scored}, blend_minus_placebo=vs_placebo,
                blend_minus_floor_only=vs_floor, blend_minus_market=vs_market,
                market_brier_mean=float(market[sel].mean()), edge_gain=edge_gain,
                # KILL at edge size: the gain (market - blend) has upper 95% bound below the edge gain.
                edge_excluded=bool(lo is not None and lo > -edge_gain),
                power_at_edge_reported=power_at(edge_gain, vs_market["se_wider"]),
                brier_ratio_blend_over_market=float(blend[sel].sum() / market[sel].sum()),
                w0_values_equal_market=bool(np.array_equal(values[0], market)),
                floor_only_equals_market=bool(np.array_equal(floor, market))), rows


# ----------------------------------------------------------------------------- gate

def coverage(flat):
    d, m = len(set(flat.date.tolist())), len(set(flat.market.tolist()))
    return dict(dates=d, markets=m, event_hours=int(flat.n),
                ok=bool(d >= MIN_DATES and m >= MIN_MARKETS and flat.n >= MIN_EVENT_HOURS))


def decide(coverage_ok, p0r, wr):
    """REVISION-1 order. Returns (outcome, step). Only an excluded edge-size effect kills; P0 not holding alone is
    INCONCLUSIVE; power at edge size below POWER_MIN makes the whole read DESCRIPTIVE (it cannot drop A1)."""
    if not coverage_ok:
        return INCONCLUSIVE, "coverage_floor"
    power = p0r.get("power_at_edge")
    if power is None or power < POWER_MIN:
        return DESCRIPTIVE, "power_at_edge_below_min"
    if p0r["edge_excluded"]:
        return KILL, "p0_delta_upper_below_delta_edge"
    if not p0r["holds"]:
        return INCONCLUSIVE, "p0_not_held_underpowered_for_information"
    if wr["holds"]:
        return NOT_KILLED, "p0_and_w_hold"
    if wr.get("edge_excluded"):
        return KILL, "w_gain_upper_below_edge_gain"
    return INCONCLUSIVE, "w_not_held_edge_not_excluded"


def gate(flat, c):
    cov = coverage(flat)
    placebos, unshuffled = placebo_candidates(flat, c)
    p0r, (dates, sc, spl) = p0(flat, c, placebos)
    reject = bh([p0r["p_one_sided"]])[0]
    lo = p0r["delta_ci95"][0]
    p0r.update(bh_reject=reject, holds=bool(reject and lo is not None and lo > 0), placebo_unshuffled=unshuffled)
    wr, wrows = w_gate(flat, c, placebos)
    rows = [dict(kind="p0_sums", arm=arm, date=str(d), **dict(zip(("n", "s", "e", "ss", "ee", "se"), map(float, r))))
            for arm, s in (("c", sc), *((f"placebo_{seed}", x) for seed, x in zip(PLACEBO_SEEDS, spl)))
            for d, r in zip(dates, s)]
    outcome, step = decide(cov["ok"], p0r, wr)
    return dict(coverage=cov, p0=p0r, w=wr, outcome=outcome, decided_by=step), rows + wrows


def k1(flat, c):
    """w = 0 is the market exactly and the floor-only blend equals m (no band is impossible at T+1)."""
    mb, imp = _mb(), _no_impossible(flat)
    g0 = mb.pool(flat.m, c, 0.0, imp, flat.snap, flat.n)
    gf = mb.pool(flat.m, flat.m, 0.0, imp, flat.snap, flat.n, force_floor=True)
    keys, snap_cell = cells_of(flat)
    ratio = float(cell_brier(flat, g0, snap_cell, len(keys)).sum() / cell_brier(flat, flat.m, snap_cell, len(keys)).sum())
    diff, floor_diff = float(np.abs(g0 - flat.m).max()), float(np.abs(gf - flat.m).max())
    return dict(max_abs_diff=diff, brier_ratio=ratio, floor_only_max_abs_diff=floor_diff,
                passed=bool(diff == 0.0 and ratio == 1.0 and floor_diff == 0.0))


def _p0_beside(flat):
    if flat.n == 0:
        return None
    placebos, unshuffled = placebo_candidates(flat, flat.c)
    result, _ = p0(flat, flat.c, placebos)
    return dict(result, placebo_unshuffled=unshuffled, coverage=coverage(flat))


def evaluate(rows):
    """K1, then the killing gate on lead 1 pooled (plain NBP + fallback), then the reported-beside strata."""
    every = flatten(rows)
    kill = every.subset((every.lead == KILL_LEAD) & np.isin(every.source, KILL_SOURCES))
    k1r = k1(kill, kill.c)
    if not k1r["passed"]:
        raise Void("K1", k1r)
    result, lines = gate(kill, kill.c)
    if not (result["w"].get("w0_values_equal_market", True) and result["w"].get("floor_only_equals_market", True)):
        raise Void("K1", result["w"])
    keys, snap_cell = cells_of(kill)
    beside = dict(
        nbp_only_lead_1=_p0_beside(every.subset((every.lead == 1) & (every.source == "nbp"))),
        lead_2=_p0_beside(every.subset(every.lead == 2)),
        blocks={name: _p0_beside(kill.subset((kill.hour >= lo) & (kill.hour <= hi))) for name, lo, hi in BLOCKS},
        markets={mk: _p0_beside(kill.subset(kill.market == mk)) for mk in sorted(set(kill.market.tolist()))},
        brier_ratio_c_over_m=float(cell_brier(kill, kill.c, snap_cell, len(keys)).sum()
                                   / cell_brier(kill, kill.m, snap_cell, len(keys)).sum()))
    return dict(result, k1=k1r, beside=beside), lines


# ----------------------------------------------------------------------------- K2 and K3

def rederive_tables(rows):
    """Re-derive the frozen tables' Brier estimates: cell = mean over hours of band-mean squared error."""
    def estimate(sub):
        grouped = defaultdict(list)
        for r in sub:
            grouped[(r["target_date"], r["market_id"])].append(r)
        if not grouped:
            return None
        losses = np.array([np.mean([[np.mean([(b[k] - b["observed_yes"]) ** 2 for b in h["bands"]])
                                     for k in ("probability", "mid")] for h in grouped[cell]], axis=0)
                           for cell in sorted(grouped)])
        return dict(provider=float(losses[:, 0].mean()), mid=float(losses[:, 1].mean()),
                    provider_minus_mid=float((losses[:, 0] - losses[:, 1]).mean()))
    out = {f"{s}_lead_{lead}": estimate([r for r in rows if r["source"] == s and r["lead"] == lead])
           for s in ("nbp", "fallback") for lead in (1, 2)}
    out["pooled_descriptive"] = estimate(rows)
    return out


def check_tables(rows, tables):
    mine, worst = rederive_tables(rows), 0.0
    for name, est in mine.items():
        brier = tables[name]["brier"]
        if est is None or brier is None:
            if (est is None) != (brier is None):
                raise Void("K2c", {"table": name, "reason": "presence_mismatch"})
            continue
        for key, value in est.items():
            frozen = brier[key]["estimate"]
            gap = math.inf if frozen is None else abs(value - frozen)
            worst = max(worst, gap)
            if not gap <= REPRO_TOL:
                raise Void("K2c", {"table": name, "key": key, "rederived": value, "frozen": frozen})
    return dict(max_abs_gap=worst, tolerance=REPRO_TOL, passed=True)


def _bundle_json(path):
    path = Path(path)
    return path / "bundle.json" if path.is_dir() else path


def check_bundles(pairs, report):
    """K2(a): each UTC day built twice gives byte-identical bundle.json; together they are the report's exports."""
    shas = []
    for first, second in pairs:
        a, b = (sha256_bytes(_bundle_json(p).read_bytes()) for p in (first, second))
        if a != b:
            raise Void("K2a", {"first": str(first), "second": str(second), "sha256": [a, b]})
        shas.append(a)
    exported = sorted(str(e["hashes"]["bundle.json"]).removeprefix("sha256:") for e in report["exports"])
    if sorted(shas) != exported:
        raise Void("K2a", {"reason": "bundle_pairs_do_not_match_report_exports", "pairs": sorted(shas),
                           "exports": exported})
    return dict(bundles=len(shas), sha256=sorted(shas), passed=True)


def _softmax_band(z, floor=0.001):
    p = np.exp(z - z.max())
    return floor + (1.0 - floor * len(z)) * p / p.sum()


def synthetic_rows(params=K3):
    """Synthetic T+1 panel: p_true ~ Dirichlet per event, one y draw per event, m and c independently blurred."""
    rng = np.random.default_rng(params["seed"])
    rows, nb = [], params["n_bands"]
    for i in range(params["n_dates"]):
        target = TARGET_START + timedelta(days=i)
        for market in params["markets"]:
            p_true = rng.dirichlet(np.full(nb, params["alpha"]))
            y = np.eye(nb)[rng.choice(nb, p=p_true)]
            for hour in params["hours_utc"]:
                m = _softmax_band(np.log(p_true) + rng.normal(0, params["m_noise"], nb))
                c = _softmax_band(np.log(p_true) + rng.normal(0, params["c_noise"], nb))
                at = datetime(target.year, target.month, target.day, hour, tzinfo=timezone.utc) - timedelta(days=1)
                rows.append(dict(event_id=f"synthetic-{market}-{target}", market_id=market,
                                 target_date=target.isoformat(), lead=1, source="nbp", captured_at=at.isoformat(),
                                 bands=[dict(condition_id=f"b{k}", probability=float(c[k]), stdev=0.0,
                                             mid=float(m[k]), inputs_hash="synthetic", observed_yes=int(y[k]))
                                        for k in range(nb)]))
    return rows


def k3_arms(params=K3):
    flat = flatten(synthetic_rows(params))
    positive = flat.c
    negation = renormalise(flat, flat.m - (positive - flat.m))
    null_s, _, _ = placebo_s(flat, positive - flat.m, params["null_seed"])
    return flat, {"positive": positive, "negation": negation, "null": renormalise(flat, flat.m + null_s)}


def run_k3(params=K3):
    flat, arms = k3_arms(params)
    out = {name: gate(flat, c)[0] for name, c in arms.items()}
    neg_hi = out["negation"]["p0"]["delta_ci95"][1]
    null_lo, null_hi = out["null"]["p0"]["delta_ci95"]
    checks = dict(positive_not_killed=out["positive"]["outcome"] == NOT_KILLED,
                  negation_delta_upper_below_zero=neg_hi is not None and neg_hi < 0,
                  negation_killed=out["negation"]["outcome"] == KILL
                  and out["negation"]["decided_by"] == "p0_delta_upper_below_delta_edge",
                  null_delta_interval_covers_zero=null_lo is not None and null_lo <= 0 <= null_hi)
    summary = {name: dict(outcome=g["outcome"], decided_by=g["decided_by"], delta=g["p0"]["delta"],
                          delta_ci95=g["p0"]["delta_ci95"], power_at_edge=g["p0"]["power_at_edge"],
                          p_one_sided=g["p0"]["p_one_sided"], mean_w=g["w"].get("mean_w"), w_holds=g["w"]["holds"])
               for name, g in out.items()}
    return dict(params={k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()},
                arms=summary, checks=checks, passed=all(checks.values()))


# ----------------------------------------------------------------------------- refusals

def _git(path, *args):
    try:
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refused(f"R5: git failed in {path}: {exc}") from exc


def check_out_dir(out, inputs):
    out = Path(out).resolve()
    if out.exists() or not out.parent.is_dir():
        raise Refused("new --out directory required (it must not exist; its parent must)")
    for src in inputs:
        src = Path(src).resolve()
        if out == src or out.is_relative_to(src) or src.is_relative_to(out):
            raise Refused(f"--out overlaps an input: {src}")
    return out


def check_row80(path, pinned=None):
    pinned = ROW80_RECEIPT_SHA256 if pinned is None else pinned
    if path is None:
        raise Refused("R4: the row 80 look receipt is required")
    if pinned is None:
        raise Refused("R4: the row 80 look receipt sha256 is not pinned in this driver")
    digest = sha256_bytes(Path(path).read_bytes())
    if digest != pinned:
        raise Refused(f"R4: row 80 receipt sha256 {digest} is not the recorded {pinned}")
    return dict(path=str(path), sha256=digest)


def check_tree(path, commit):
    head = _git(path, "rev-parse", "HEAD").strip()
    dirty = _git(path, "status", "--porcelain", "--untracked-files=all").strip()
    if commit is not None and head != commit:
        raise Refused(f"R5: {path} is at {head}, not {commit}")
    if dirty:
        raise Refused(f"R5: {path} is dirty")
    return dict(path=str(path), head=head, dirty=False)


def check_rows(report):
    """R5 (code tip), R2 (bundle days), R1 (targets), R3 (excluded cells): metadata keys only."""
    if report.get("code_tip") != FROZEN_SCORER_COMMIT:
        raise Refused(f"R5: report code_tip {report.get('code_tip')!r} is not {FROZEN_SCORER_COMMIT}")
    for export in report["exports"]:
        if not DAY_START <= date.fromisoformat(export["day"]) <= DAY_END:
            raise Refused(f"R2: bundle day {export['day']} outside UTC {DAY_START}..{DAY_END}")
    rows = report["selected_hours"]
    for row in rows:
        if not TARGET_START <= date.fromisoformat(row["target_date"]) <= TARGET_END:
            raise Refused(f"R1: target {row['target_date']} outside {TARGET_START}..{TARGET_END}")
        if (row["market_id"], row["target_date"]) in EXCLUDED_CELLS:
            raise Refused(f"R3: excluded cell {row['market_id']} {row['target_date']} is in the selected rows")
    return rows


# ----------------------------------------------------------------------------- output

def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    return o


def write_out(out, result, lines=()):
    out.mkdir()
    with (out / "c3_result.json").open("xb") as fh:
        fh.write(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
    if lines:
        with (out / "c3_rows.jsonl").open("xb") as fh:
            for line in lines:
                fh.write(json.dumps(_clean(line), sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")


def _implementation():
    return {"c3_kill_tier.py": sha256_bytes(Path(__file__).read_bytes()),
            "market_blend.py": sha256_bytes(Path(_mb().__file__).read_bytes())}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.c3_kill_tier", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", type=Path, required=True, help="frozen scorer report.json (run 1)")
    ap.add_argument("--report-repeat", type=Path, required=True, help="frozen scorer report.json (run 2, K2b)")
    ap.add_argument("--bundle-pair", type=Path, nargs=2, action="append", required=True, metavar=("FIRST", "SECOND"))
    ap.add_argument("--scorer-worktree", type=Path, required=True, help=f"clean worktree at {FROZEN_SCORER_COMMIT}")
    ap.add_argument("--row80-receipt", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    inputs = [args.report, args.report_repeat, args.scorer_worktree,
              *(p for pair in args.bundle_pair for p in pair), *([args.row80_receipt] if args.row80_receipt else [])]
    try:   # Refusals first: nothing below this block runs, and nothing is written, if any refuses.
        out = check_out_dir(args.out, inputs)
        receipt = check_row80(args.row80_receipt)                         # R4, before any panel byte
        scorer_tree = check_tree(args.scorer_worktree, FROZEN_SCORER_COMMIT)   # R5
        driver_tree = check_tree(REPO_ROOT, None)                         # R5: the driver's own tree is clean
        report_bytes = args.report.read_bytes()
        report = json.loads(report_bytes)
        rows = check_rows(report)                                         # R5 code tip, R2, R1, R3
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"c3 kill tier refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    base = dict(schema=SCHEMA, rule=RULE_PATH, rule_reviewed_sha256=RULE_REVIEWED_SHA256,
                revisions=[REVISION_PATH, REVISION_2_PATH, REVISION_3_PATH],
                date_gate_trace=DATE_GATE_TRACE, provisional=PROVISIONAL, frozen_scorer_commit=FROZEN_SCORER_COMMIT,
                buckets_commit=BUCKETS_COMMIT, row80_receipt=receipt, scorer_tree=scorer_tree, driver_tree=driver_tree,
                report_sha256=sha256_bytes(report_bytes), implementation=_implementation(),
                constants=dict(eps=EPS, gap_days=GAP_DAYS, placebo_seeds=list(PLACEBO_SEEDS), boot_b=BOOT_B,
                               boot_seed=BOOT_SEED, bh_q=BH_Q, mean_w_min=MEAN_W_MIN, min_dates=MIN_DATES,
                               min_event_hours=MIN_EVENT_HOURS, kill_lead=KILL_LEAD, kill_sources=list(KILL_SOURCES),
                               edge_gain=EDGE_GAIN, delta_edge=DELTA_EDGE, power_min=POWER_MIN, block_len=BLOCK_LEN,
                               block_bootstrap="circular moving block, B and seed as the date-clustered one"))
    controls = {}
    try:
        if args.report_repeat.read_bytes() != report_bytes:
            raise Void("K2b", {"reason": "report.json runs are not byte-identical"})
        controls["K2b"] = dict(passed=True)
        controls["K2a"] = check_bundles(args.bundle_pair, report)
        controls["K2c"] = check_tables(rows, report["tables"])
        controls["K3"] = run_k3()
        if not controls["K3"]["passed"]:
            raise Void("K3", controls["K3"])
        result, lines = evaluate(rows)
    except Void as exc:
        write_out(out, dict(base, outcome=VOID, failed_control=exc.control, detail=exc.detail, controls=controls))
        print(f"c3 kill tier VOID: {exc.control}", file=sys.stderr)
        return EXIT_VOID
    except (Refused, OSError, KeyError, TypeError, ValueError) as exc:   # unreadable or malformed input: nothing written
        print(f"c3 kill tier refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    controls["K1"] = result.pop("k1")
    write_out(out, dict(base, outcome=result["outcome"], controls=controls, **result), lines)
    print(json.dumps({"outcome": result["outcome"], "coverage": result["coverage"]}, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
