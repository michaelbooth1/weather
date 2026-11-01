"""Market reliability by bin, US11 dev window: the single pre-registered run (lane L21, 2026-11-01).

Rule: README.md beside this file (DRAFT until master freezes it and pins this script's sha256).

Two modes, one of which must be named:

--synthetic-only
    Never opens labels.parquet. It reads only the snapshot, band and market files. Each file is
    sha-verified against the layout manifest, and only the named columns are read. It builds the real
    deciding population, draws synthetic labels, and runs steps 2-4 on those labels: the null and
    planted controls, the training-score check, and the realised-SE power projection on the null. Step 1
    (the positive control) needs labels and is reported as not run. No real Delta exists in this mode.

--real-run
    The single real run. It opens labels.parquet through the read-only dev_scorecard loaders. Steps run
    in this order, and a failure at any step writes UNTESTABLE plus that step's own numbers and stops:
      1. Positive control: served/market R 1.774 (all) and 1.526 (00-16), dev scorecard default folds,
         to 3 decimals.
      2. Synthetic null and planted controls.
      3. Training-score check.
      4. Realised widest-of-three SE per arm, with power Phi(0.2236 / SE - 1.96) >= 0.5 for every arm.
    No real Delta (point, interval or per arm) reaches stdout, the receipt or any file unless all four
    steps passed. Bootstrap draws are computed internally to get the SE and are discarded on failure.

The receipt holds:
- the layout manifest sha256, re-hashed before and after the run;
- every input sha;
- this script's sha256, the git tip, the seed and the draw counts.

Statistic (README section 4b, revision 1): residual r = y - m~ with m~ = p_market_yes / sum over the FULL
captured ladder; A1 g = m~ - ladder mean of m~; A3 g = q_beta - m~. Bins stay on the raw displayed price m.
The floor-impossible flag removes rows only from the scored sums and the bin tables (C1).

No network. Standard library plus numpy, pandas and pyarrow only. weather.reporting.scorecards modules
are imported read-only.

Usage:
    python run_reliability.py --layout C:\\swarm\\v3layout --out <receipt.json> --synthetic-only
    python run_reliability.py --layout C:\\swarm\\v3layout --out <receipt.json> --real-run --expect-sha <pinned>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow
import pyarrow.parquet as pq

# ----------------------------------------------------------------------------- frozen constants (README)
W_FIRST, W_LAST = date(2026, 8, 1), date(2026, 9, 29)          # O1: W57
EDGE = math.sqrt(0.05)                                         # D3, 0.2236
Z = 1.959963984540054
SEED = 20261024
B_DATE, B_BLOCK, B_CIRC, B_CROSSED = 10_000, 10_000, 2_000, 2_000
BLOCK_LEN = 3
BIN_EDGES = (0.02, 0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95)   # 11 bins, last closed at 1
N_BINS = len(BIN_EDGES) + 1
THIN_BIN_DATES = 30
BETA_GRID = np.round(np.arange(50, 251) / 100.0, 2)            # 0.50..2.50 step 0.01
BETA_ORDER = np.array(sorted(range(len(BETA_GRID)), key=lambda k: (abs(BETA_GRID[k] - 1.0), BETA_GRID[k])))
HOUR_BLOCKS = {"00-06": (0, 6), "07-12": (7, 12), "13-16": (13, 16), "17-23": (17, 23)}
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
POSITIVE_CONTROL = {"all": 1.774, "00-16": 1.526}
NULL_BETA = (0.90, 1.10)
PLANTED_BETA_TRUE, PLANTED_BETA = 1.5, (1.35, 1.65)
POWER_GATE = 0.5
ARMS = ("A1_linear", "A2_binned_lodo", "A3_power_lodo")
SNAP_COLS = ["row_key", "market", "date", "local_hour", "captured_at_local", "n_bands", *FLOOR_FIELDS]
BAND_COLS = ["row_key", "band_index", "kind", "high", "floor_impossible"]
MARKET_COLS = ["row_key", "band_index", "p_market_yes"]
LABELISH = {"winner", "settlement_high", "settlement_bucket", "settlement_source", "is_winner"}
CHUNK_ELEMS = 2_000_000


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def power_at_edge(se):
    return phi(EDGE / se - Z) if se > 0 else 0.0


# ----------------------------------------------------------------------------- inputs

class Untestable(Exception):
    def __init__(self, step, numbers):
        super().__init__(step)
        self.step, self.numbers = step, numbers


def read_inputs_synthetic(layout):
    """Snapshots, bands and market, sha-verified, named columns only. labels.parquet is never opened."""
    manifest = json.loads((layout / "manifest.json").read_text(encoding="utf-8"))
    shas, frames = {}, {}
    for name, cols in (("inputs_snapshots.parquet", SNAP_COLS), ("inputs_bands.parquet", BAND_COLS),
                       ("market.parquet", MARKET_COLS)):
        entry = manifest["files"][name]
        late = [d for d in entry["dates"] if date.fromisoformat(d) > W_LAST]
        if late:
            raise SystemExit(f"refused: {name} declares dates after {W_LAST}; not opened")
        shas[name] = sha256_file(layout / name)
        if shas[name] != entry["sha256"]:
            raise SystemExit(f"{name} does not match its manifest sha256")
        assert not set(cols) & LABELISH
        frames[name] = pq.read_table(layout / name, columns=cols).to_pandas()
    shas["labels.parquet"] = {"manifest_sha256": manifest["files"]["labels.parquet"]["sha256"],
                              "opened": False}
    return frames["inputs_snapshots.parquet"], frames["inputs_bands.parquet"], frames["market.parquet"], None, shas


def read_inputs_real(layout):
    from weather.reporting.scorecards import dev_scorecard_data as data   # read-only import
    lay = data.load_layout(layout, data.DEV_FIRST, W_LAST)
    labels = lay.labels[["row_key", "winner"]].copy()
    shas = dict(lay.file_sha256)
    shas["labels.parquet"] = {"sha256": lay.file_sha256["labels.parquet"], "opened": True}
    return lay.snaps[SNAP_COLS].copy(), lay.bands[BAND_COLS].copy(), lay.market[MARKET_COLS].copy(), labels, shas


# ----------------------------------------------------------------------------- population (README 3b-3e)

def build_population(snaps, bands, market):
    s = snaps.copy()
    s["date"] = s["date"].astype(str)
    d = s["date"].map(date.fromisoformat)
    if (d > W_LAST).any():
        raise SystemExit("refused: a snapshot after 2026-09-29")
    s = s[(d >= W_FIRST) & (d <= W_LAST)]
    # dedup: last captured per (market, local target date, local hour); ties -> largest row_key
    s = s.sort_values(["market", "date", "local_hour", "captured_at_local", "row_key"])
    s = s.groupby(["market", "date", "local_hour"], sort=False).tail(1)
    floor = s[list(FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    s = s.assign(floor_value=floor.to_numpy(float))
    keep_keys = set(s["row_key"])
    b = bands[bands["row_key"].isin(keep_keys)]
    mk = market[market["row_key"].isin(keep_keys)]
    rows = b.merge(mk, on=["row_key", "band_index"], how="left", validate="one_to_one")
    rows = rows.merge(s[["row_key", "market", "date", "local_hour", "n_bands", "floor_value"]], on="row_key",
                      how="left", validate="many_to_one")
    counts = rows.groupby("row_key").agg(n_rows=("band_index", "size"), n_price=("p_market_yes", "count"))
    complete = counts.index[(counts.n_rows == counts.n_price)
                            & (counts.n_rows == s.set_index("row_key").loc[counts.index, "n_bands"].astype(int))]
    incomplete = int(len(keep_keys) - len(complete))
    rows = rows[rows["row_key"].isin(set(complete))]
    msum = rows.groupby("row_key")["p_market_yes"].transform("sum")
    zero_sum = int(rows.loc[msum <= 0, "row_key"].nunique())
    rows = rows[msum > 0]
    rows = rows.sort_values(["date", "market", "local_hour", "row_key", "band_index"]).reset_index(drop=True)
    # floor-impossible: the dev_scorecard.py Table rule (lines 149-153), recomputed here
    fb = rows["floor_value"].to_numpy(float)
    imp = (rows["kind"].to_numpy() != "gte") & (rows["high"].to_numpy(float) < np.floor(fb + 0.5))
    imp = np.where(np.isnan(fb), False, imp)
    rows["impossible"] = imp
    info = {"snapshots_selected": int(len(keep_keys)), "incomplete_ladders_dropped": incomplete,
            "zero_price_ladders_dropped": zero_sum, "ladders": int(rows["row_key"].nunique()),
            "band_rows_all": int(len(rows)), "band_rows_scored": int((~imp).sum()),
            "impossible_rows": int(imp.sum()),
            "impossible_vs_layout_flag_disagree": int((imp != rows["floor_impossible"].fillna(False)
                                                       .astype(bool).to_numpy()).sum()),
            "dates": int(rows["date"].nunique()), "markets": int(rows["market"].nunique()),
            "market_days": int(rows.groupby(["market", "date"]).ngroups)}
    return rows, info


class Pop:
    """Row arrays; ladders contiguous; ladder-level quantities over the FULL captured ladder (C1)."""

    def __init__(self, rows):
        self.m = rows["p_market_yes"].to_numpy(float)
        key = rows["row_key"].to_numpy()
        change = np.r_[True, key[1:] != key[:-1]]
        self.ladder_start = np.flatnonzero(change)
        self.ladder = np.cumsum(change) - 1
        self.n_ladders = len(self.ladder_start)
        lsum = np.add.reduceat(self.m, self.ladder_start)
        lcount = np.diff(np.r_[self.ladder_start, len(self.m)])
        self.mt = self.m / lsum[self.ladder]                       # m~ = m / sum(m), full ladder
        self.g1 = self.mt - (1.0 / lcount)[self.ladder]            # A1: m~ - ladder mean of m~, full ladder
        self.dates = sorted(rows["date"].unique())
        self.D = len(self.dates)
        self.date_idx = rows["date"].map({d: i for i, d in enumerate(self.dates)}).to_numpy()
        self.markets = sorted(rows["market"].unique())
        self.market_idx = rows["market"].map({x: i for i, x in enumerate(self.markets)}).to_numpy()
        self.hour = rows["local_hour"].to_numpy(int)
        self.bin = np.digitize(np.clip(self.m, 0.0, 1.0), BIN_EDGES, right=False)
        self.scored = ~rows["impossible"].to_numpy(bool)
        self.band_index = rows["band_index"].to_numpy(int)
        self.row_key = key
        self.ladder_key = key[self.ladder_start]
        self.ladder_date = self.date_idx[self.ladder_start]
        # q_beta over the full ladder, one column per beta (float32 keeps it near 130 MB)
        self.q = np.empty((len(self.m), len(BETA_GRID)), np.float32)
        for k, beta in enumerate(BETA_GRID):
            p = np.power(self.mt, beta)
            self.q[:, k] = p / np.add.reduceat(p, self.ladder_start)[self.ladder]

    def y_from_winner(self, winner_by_key):
        w = pd.Series(winner_by_key).reindex(self.ladder_key)
        if w.isna().any():
            raise Untestable("labels", {"snapshots_without_label": int(w.isna().sum())})
        return (self.band_index == w.to_numpy(int)[self.ladder]).astype(float)

    def synthetic_y(self, beta, rng):
        """One winner per ladder drawn from q_beta (beta = 1: the categorical m~)."""
        p = np.power(self.mt, beta)
        p = p / np.add.reduceat(p, self.ladder_start)[self.ladder]
        cum = np.cumsum(p)
        before = cum[self.ladder_start] - p[self.ladder_start]
        target = before + rng.random(self.n_ladders)
        pick = np.searchsorted(cum, target, side="right")
        ends = np.r_[self.ladder_start[1:], len(p)] - 1
        pick = np.minimum(np.maximum(pick, self.ladder_start), ends)
        y = np.zeros(len(p))
        y[pick] = 1.0
        return y


# ----------------------------------------------------------------------------- sufficient statistics

class Stats:
    """Per-cell sums over the rows in ``mask``. Cells are sorted by date; ``starts`` index date groups."""

    def __init__(self, pop, y, mask, cell, n_cells):
        r = y - pop.mt                                             # residual on the normalised price m~
        idx = np.flatnonzero(mask)
        c = cell[idx]
        bc = lambda w: np.bincount(c, weights=w, minlength=n_cells)
        self.RR = bc(r[idx] ** 2)
        self.GR1 = bc(pop.g1[idx] * r[idx])
        self.GG1 = bc(pop.g1[idx] ** 2)
        cb = c * N_BINS + pop.bin[idx]
        self.S = np.bincount(cb, weights=r[idx], minlength=n_cells * N_BINS).reshape(n_cells, N_BINS)
        self.N = np.bincount(cb, minlength=n_cells * N_BINS).reshape(n_cells, N_BINS).astype(float)
        K = len(BETA_GRID)
        self.BR = np.empty((n_cells, K))
        self.GR3 = np.empty((n_cells, K))
        self.GG3 = np.empty((n_cells, K))
        yi, mti, ri = y[idx], pop.mt[idx], r[idx]
        for k in range(K):
            q = pop.q[idx, k].astype(float)
            g3 = q - mti
            self.BR[:, k] = bc((yi - q) ** 2)
            self.GR3[:, k] = bc(g3 * ri)
            self.GG3[:, k] = bc(g3 ** 2)
        # reorder beta columns so argmin's first minimum is the beta closest to 1 (ties rule)
        self.BR, self.GR3, self.GG3 = self.BR[:, BETA_ORDER], self.GR3[:, BETA_ORDER], self.GG3[:, BETA_ORDER]


def group(x, starts):
    return np.add.reduceat(x, starts, axis=1)


def deltas(fit, ev, W, starts):
    """Delta per arm for each weight row of W (draws x cells). LODO leaves out every copy of a date."""
    out = np.empty((W.shape[0], 3))
    kpick = np.empty((W.shape[0], len(starts)), int)
    per = max(1, CHUNK_ELEMS // (W.shape[1] * len(BETA_GRID)))
    for a in range(0, W.shape[0], per):
        w = W[a:a + per].astype(float)
        rr = w @ ev.RR
        # A1
        gr1, gg1 = w @ ev.GR1, w @ ev.GG1
        # A2
        T, TN = w @ fit.S, w @ fit.N
        U, UN = group(w[:, :, None] * fit.S[None], starts), group(w[:, :, None] * fit.N[None], starts)
        den = TN[:, None, :] - UN
        g = np.divide(T[:, None, :] - U, den, out=np.zeros_like(den), where=den > 1e-9)
        Ue, UNe = group(w[:, :, None] * ev.S[None], starts), group(w[:, :, None] * ev.N[None], starts)
        gr2, gg2 = (g * Ue).sum((1, 2)), (g * g * UNe).sum((1, 2))
        # A3
        L = w @ fit.BR
        UL = group(w[:, :, None] * fit.BR[None], starts)
        k = np.argmin(L[:, None, :] - UL, axis=2)
        UGR = group(w[:, :, None] * ev.GR3[None], starts)
        UGG = group(w[:, :, None] * ev.GG3[None], starts)
        gr3 = np.take_along_axis(UGR, k[:, :, None], 2)[:, :, 0].sum(1)
        gg3 = np.take_along_axis(UGG, k[:, :, None], 2)[:, :, 0].sum(1)
        for j, (gr, gg) in enumerate(((gr1, gg1), (gr2, gg2), (gr3, gg3))):
            den = np.sqrt(gg * rr)
            out[a:a + per, j] = np.divide(gr, den, out=np.zeros_like(gr), where=den > 0)
        kpick[a:a + per] = k
    return out, kpick


def date_weights(D):
    rng_iid = np.random.default_rng(SEED)
    rng_blk = np.random.default_rng(SEED)
    rng_circ = np.random.default_rng(SEED)
    iid = rng_iid.multinomial(D, np.full(D, 1.0 / D), size=B_DATE)

    def blocks(rng, draws, circular):
        nb = math.ceil(D / BLOCK_LEN)
        starts = rng.integers(0, D if circular else D - BLOCK_LEN + 1, size=(draws, nb))
        idx = ((starts[:, :, None] + np.arange(BLOCK_LEN)) % D).reshape(draws, -1)[:, :D]
        W = np.zeros((draws, D), int)
        np.add.at(W, (np.repeat(np.arange(draws), D), idx.ravel()), 1)
        return W

    return {"date_clustered": iid, "block3": blocks(rng_blk, B_BLOCK, False),
            "block3_circular": blocks(rng_circ, B_CIRC, True)}


def interval(x):
    return [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]


def deciding(pop, y, schemes, eval_mask=None):
    """Point Delta, per-scheme intervals, widest bounds and SE for the three arms (date cells)."""
    D = pop.D
    starts = np.arange(D)
    fit = Stats(pop, y, pop.scored, pop.date_idx, D)
    ev = fit if eval_mask is None else Stats(pop, y, eval_mask, pop.date_idx, D)
    point, kp = deltas(fit, ev, np.ones((1, D)), starts)
    res = {}
    draws = {name: deltas(fit, ev, W, starts)[0] for name, W in schemes.items()}
    for j, arm in enumerate(ARMS):
        per = {name: {"ci95": interval(d[:, j]), "sd": float(d[:, j].std(ddof=1))} for name, d in draws.items()}
        lo = min(v["ci95"][0] for v in per.values())
        hi = max(v["ci95"][1] for v in per.values())
        se = max(v["sd"] for v in per.values())
        res[arm] = {"point": float(point[0, j]), "per_scheme": per, "widest": [lo, hi], "se": se,
                    "power_at_edge": power_at_edge(se)}
    res["_lodo_beta_by_date"] = BETA_GRID[BETA_ORDER[kp[0]]].tolist()
    res["_stats"] = fit
    return res


def in_sample(pop, y):
    """Training-score check (EF 1c): in-sample fits on the scored rows."""
    fit = Stats(pop, y, pop.scored, pop.date_idx, pop.D)
    rr = fit.RR.sum()
    S, N = fit.S.sum(0), fit.N.sum(0)
    rbar = np.divide(S, N, out=np.zeros_like(S), where=N > 0)
    a2_frac = float((rbar * S).sum() ** 2 / ((rbar * rbar * N).sum() * rr)) if (rbar * rbar * N).sum() > 0 else 0.0
    a2_brier_cut = float((rbar * S).sum() / rr)                   # in-sample direct cut, sum(N rbar^2)/sum(r^2)
    br = fit.BR.sum(0)
    k_hat = int(np.argmin(br))
    beta_hat = float(BETA_GRID[BETA_ORDER[k_hat]])
    k_one = int(np.flatnonzero(BETA_GRID[BETA_ORDER] == 1.0)[0])
    return {"beta_hat": beta_hat, "brier_at_beta_hat": float(br[k_hat]), "brier_at_beta_1": float(br[k_one]),
            "a3_in_sample_brier_fraction": float(1.0 - br[k_hat] / br[k_one]),
            "a2_in_sample_brier_fraction": a2_brier_cut, "a2_in_sample_cosine_sq": a2_frac,
            "ok": bool(br[k_hat] <= br[k_one] + 1e-12 and a2_brier_cut >= -1e-12)}


# ----------------------------------------------------------------------------- steps

def step_positive_control(layout):
    from weather.reporting.scorecards import dev_scorecard as sc            # read-only import
    from weather.reporting.scorecards import dev_scorecard_data as data
    payload = sc.run_score(str(layout), "2026-08-01", "2026-09-29", data.CandidateSpec(kind="served"))
    got = {}
    for row in payload["rows"]:
        if row["market"] == sc.ALL_MARKETS and row["block"] in POSITIVE_CONTROL:
            got[row["block"]] = row["gap_ratio"]["estimate"]
    numbers = {"expected": POSITIVE_CONTROL, "got": got,
               "rounded": {k: round(v, 3) for k, v in got.items()}}
    if any(round(got.get(k, float("nan")), 3) != v for k, v in POSITIVE_CONTROL.items()):
        raise Untestable("1_positive_control", numbers)
    return numbers


def control_summary(res, ins):
    return {"in_sample_beta_hat": ins["beta_hat"],
            **{arm: {"point": res[arm]["point"], "widest": res[arm]["widest"], "se": res[arm]["se"]}
               for arm in ARMS}}


def step_synthetic(pop, schemes):
    rng = np.random.default_rng(SEED)
    y_null = pop.synthetic_y(1.0, rng)
    rng = np.random.default_rng(SEED)
    y_plant = pop.synthetic_y(PLANTED_BETA_TRUE, rng)
    null_res, null_ins = deciding(pop, y_null, schemes), in_sample(pop, y_null)
    plant_res, plant_ins = deciding(pop, y_plant, schemes), in_sample(pop, y_plant)
    checks = {
        "null_all_arms_cover_0": all(null_res[a]["widest"][0] <= 0.0 <= null_res[a]["widest"][1] for a in ARMS),
        "null_beta_hat_in_range": NULL_BETA[0] <= null_ins["beta_hat"] <= NULL_BETA[1],
        "planted_beta_hat_in_range": PLANTED_BETA[0] <= plant_ins["beta_hat"] <= PLANTED_BETA[1],
        "planted_a3_widest_lower_gt_0": plant_res["A3_power_lodo"]["widest"][0] > 0.0,
    }
    numbers = {"null": control_summary(null_res, null_ins), "planted": control_summary(plant_res, plant_ins),
               "checks": checks}
    if not all(checks.values()):
        raise Untestable("2_synthetic_controls", numbers)
    return numbers, (y_null, null_res, null_ins)


def step_training(ins, label):
    numbers = {"labels": label, **{k: v for k, v in ins.items()}}
    if not ins["ok"]:
        raise Untestable("3_training_score_check", numbers)
    return numbers


def step_power(res, label):
    numbers = {"labels": label, **{arm: {"se_widest_of_three": res[arm]["se"],
                                         "per_scheme_sd": {k: v["sd"] for k, v in res[arm]["per_scheme"].items()},
                                         "power_at_edge": res[arm]["power_at_edge"],
                                         "mde80": (Z + 0.8416212335729143) * res[arm]["se"]} for arm in ARMS}}
    if any(res[arm]["power_at_edge"] < POWER_GATE for arm in ARMS):
        raise Untestable("4_realised_power", numbers)
    return numbers


# ----------------------------------------------------------------------------- verdict and descriptives (real run only)

def arm_label(arm, lo, hi):
    if arm == "A1_linear":
        killed = lo > -EDGE and hi < EDGE
        positive = lo > 0 or hi < 0
    else:
        killed = hi < EDGE
        positive = lo > 0
    return killed, positive


def verdict(res):
    arms = {}
    for arm in ARMS:
        killed, positive = arm_label(arm, *res[arm]["widest"])
        arms[arm] = "KILLED" if killed else ("SCREEN-POSITIVE (descriptive only)" if positive
                                             else "NOT KILLED, NOT SCREEN-POSITIVE")
    if all(v == "KILLED" for v in arms.values()):
        line = "US11: KILL at edge size (all three arms below Delta 0.2236)"
    else:
        line = ("US11: NOT KILLED (earns only a follow-up prereg, which must include a book-mid arm on the "
                "[0, .10) bins before any use; never an edge claim)")
    return {"verdict": line, "arms": arms}


def ratio_boot(num, den, schemes, point_num, point_den):
    out = {"point": float(point_num / point_den) if point_den > 0 else None, "per_scheme": {}}
    for name, W in schemes.items():
        a, b = W @ num, W @ den
        x = np.divide(a, b, out=np.full(len(a), np.nan), where=b > 0)
        x = x[np.isfinite(x)]
        out["per_scheme"][name] = interval(x) if len(x) else [None, None]
    vals = [v for v in out["per_scheme"].values() if v[0] is not None]
    out["widest"] = [min(v[0] for v in vals), max(v[1] for v in vals)] if vals else [None, None]
    return out


def bin_table(pop, y, mask, schemes):
    r = y - pop.mt
    idx = np.flatnonzero(mask)
    D = pop.D
    rows = []
    for b in range(N_BINS):
        sel = idx[pop.bin[idx] == b]
        n_d = np.bincount(pop.date_idx[sel], minlength=D).astype(float)
        s_r = np.bincount(pop.date_idx[sel], weights=r[sel], minlength=D)
        s_m = np.bincount(pop.date_idx[sel], weights=pop.m[sel], minlength=D)
        s_mt = np.bincount(pop.date_idx[sel], weights=pop.mt[sel], minlength=D)
        s_y = np.bincount(pop.date_idx[sel], weights=y[sel], minlength=D)
        lo = 0.0 if b == 0 else BIN_EDGES[b - 1]
        hi = 1.0 if b == N_BINS - 1 else BIN_EDGES[b]
        rows.append({"bin": [lo, hi], "n": int(len(sel)), "dates_with_obs": int((n_d > 0).sum()),
                     "thin": bool((n_d > 0).sum() < THIN_BIN_DATES),
                     "mean_m": float(s_m.sum() / n_d.sum()) if n_d.sum() else None,
                     "mean_m_normalised": float(s_mt.sum() / n_d.sum()) if n_d.sum() else None,
                     "d_b_raw_point": float((s_y.sum() - s_m.sum()) / n_d.sum()) if n_d.sum() else None,
                     "observed": float(s_y.sum() / n_d.sum()) if n_d.sum() else None,
                     "d_b": ratio_boot(s_r, n_d, schemes, s_r.sum(), n_d.sum())})
    return rows


def calibration_line(pop, y, schemes):
    idx = np.flatnonzero(pop.scored)
    d = pop.date_idx[idx]
    m, yy = pop.mt[idx], y[idx]
    sums = np.stack([np.bincount(d, weights=w, minlength=pop.D)
                     for w in (np.ones_like(m), m, yy, m * m, m * yy)], 1)

    def fit(t):
        n, sm, sy, smm, smy = t.T
        slope = (n * smy - sm * sy) / (n * smm - sm * sm)
        return slope, (sy - slope * sm) / n

    s0, a0 = fit(sums.sum(0)[None])
    out = {"slope": float(s0[0]), "intercept": float(a0[0]), "per_scheme": {}}
    for name, W in schemes.items():
        s, a = fit(W @ sums)
        out["per_scheme"][name] = {"slope": interval(s), "intercept": interval(a)}
    out["slope_widest"] = [min(v["slope"][0] for v in out["per_scheme"].values()),
                           max(v["slope"][1] for v in out["per_scheme"].values())]
    return out


def pearson_point(pop, y, res):
    """Pearson correlation of g and r on scored rows at the point LODO fits."""
    r = y - pop.mt
    sc = pop.scored
    fit = res["_stats"]
    S, N = fit.S, fit.N
    T, TN = S.sum(0), N.sum(0)
    g2_tab = np.divide(T[None] - S, TN[None] - N, out=np.zeros_like(S), where=(TN[None] - N) > 1e-9)
    g2 = g2_tab[pop.date_idx, pop.bin]
    beta_d = np.array(res["_lodo_beta_by_date"])
    kcol = np.searchsorted(BETA_GRID, beta_d)[pop.date_idx]
    g3 = pop.q[np.arange(len(pop.m)), kcol].astype(float) - pop.mt
    out = {}
    for arm, g in zip(ARMS, (pop.g1, g2, g3)):
        out[arm] = float(np.corrcoef(g[sc], r[sc])[0, 1])
    return out


def crossed_interval(pop, y):
    """Descriptive crossed date x market interval (EF 5) for the three arms, 2,000 draws."""
    cell_keys = sorted(set(zip(pop.date_idx.tolist(), pop.market_idx.tolist())))
    index = {k: i for i, k in enumerate(cell_keys)}
    cell = np.array([index[k] for k in zip(pop.date_idx.tolist(), pop.market_idx.tolist())])
    cd = np.array([k[0] for k in cell_keys])
    cm = np.array([k[1] for k in cell_keys])
    starts = np.flatnonzero(np.r_[True, cd[1:] != cd[:-1]])
    st = Stats(pop, y, pop.scored, cell, len(cell_keys))
    rng = np.random.default_rng(SEED)
    D, M = pop.D, len(pop.markets)
    wd = rng.multinomial(D, np.full(D, 1 / D), size=B_CROSSED)
    wm = rng.multinomial(M, np.full(M, 1 / M), size=B_CROSSED)
    W = wd[:, cd] * wm[:, cm]
    d, _ = deltas(st, st, W, starts)
    return {arm: interval(d[:, j]) for j, arm in enumerate(ARMS)}


def public(res):
    return {arm: {k: res[arm][k] for k in ("point", "per_scheme", "widest", "se", "power_at_edge")} for arm in ARMS}


def descriptives(pop, y, schemes, res):
    out = {"bins_scored": bin_table(pop, y, pop.scored, schemes),
           "calibration_line": calibration_line(pop, y, schemes),
           "pearson_g_r": pearson_point(pop, y, res),
           "lodo_beta_by_date": dict(zip(pop.dates, res["_lodo_beta_by_date"]))}
    tab = out["bins_scored"]
    n_tot = sum(t["n"] for t in tab)
    out["ece"] = float(sum(t["n"] / n_tot * abs(t["d_b"]["point"]) for t in tab if t["n"]))
    r = (y - pop.mt)[pop.scored]
    out["f_bin_in_sample_oracle"] = float(sum(t["n"] * t["d_b"]["point"] ** 2 for t in tab if t["n"]) / (r * r).sum())
    out["include_impossible_same_g"] = public(deciding(pop, y, schemes, eval_mask=np.ones(len(pop.m), bool)))
    out["bins_all_rows_including_impossible"] = bin_table(pop, y, np.ones(len(pop.m), bool), schemes)
    out["crossed_date_x_market_ci95"] = crossed_interval(pop, y)
    blocks = {}
    for name, (h0, h1) in HOUR_BLOCKS.items():
        hm = (pop.hour >= h0) & (pop.hour <= h1)
        sub = pop.scored.copy()
        pop.scored = sub & hm
        try:
            blocks[name] = {"deciding_arms_fit_within_block": public(deciding(pop, y, schemes)),
                            "bins": bin_table(pop, y, pop.scored, schemes)}
        finally:
            pop.scored = sub
    out["hour_blocks"] = blocks
    return out


# ----------------------------------------------------------------------------- main

def git_tip(path):
    try:
        tip = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=30).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=30).stdout.strip()
        return {"tip": tip, "script_dir_dirty": bool(dirty)}
    except Exception as exc:                                       # receipt records the failure
        return {"tip": None, "error": repr(exc)}


def peak_mb():
    try:
        import ctypes
        from ctypes import wintypes as w

        class PMC(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                        ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", ctypes.c_size_t),
                        ("f", ctypes.c_size_t)]
        k32, ps = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = w.HANDLE
        ps.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMC), w.DWORD]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return int(c.PeakWorkingSetSize // 2 ** 20)
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic-only", action="store_true")
    mode.add_argument("--real-run", action="store_true")
    ap.add_argument("--expect-sha", help="refuse unless this script's sha256 equals the pinned value")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    script = Path(__file__).resolve()
    script_sha = sha256_file(script)
    if args.real_run and args.expect_sha != script_sha:
        raise SystemExit(f"refused: --real-run needs --expect-sha equal to this script's sha256 {script_sha}")
    layout = Path(args.layout)
    manifest_before = sha256_file(layout / "manifest.json")
    receipt = {"schema": "market_reliability_bin_receipt/1", "mode": "real" if args.real_run else "synthetic_only",
               "script_sha256": script_sha, "git": git_tip(script.parent), "seed": SEED,
               "draws": {"date_clustered": B_DATE, "block3": B_BLOCK, "block3_circular": B_CIRC,
                         "crossed_descriptive": B_CROSSED},
               "edge": EDGE, "window": [W_FIRST.isoformat(), W_LAST.isoformat()],
               "layout": str(layout), "layout_manifest_sha256_before": manifest_before,
               "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                            "pyarrow": pyarrow.__version__},
               "steps": {}}
    try:
        if args.real_run:
            snaps, bands, market, labels, shas = read_inputs_real(layout)
        else:
            snaps, bands, market, labels, shas = read_inputs_synthetic(layout)
        receipt["input_sha256"] = shas
        rows, info = build_population(snaps, bands, market)
        del snaps, bands, market
        receipt["population"] = info
        pop = Pop(rows)
        del rows
        schemes = date_weights(pop.D)
        if args.real_run:
            receipt["steps"]["1_positive_control"] = step_positive_control(layout)
        else:
            receipt["steps"]["1_positive_control"] = {"status": "NOT RUN (synthetic-only: needs labels)"}
        synth, (y_null, null_res, null_ins) = step_synthetic(pop, schemes)
        receipt["steps"]["2_synthetic_controls"] = synth
        if args.real_run:
            y = pop.y_from_winner(dict(zip(labels["row_key"], labels["winner"])))
            receipt["steps"]["3_training_score_check"] = step_training(in_sample(pop, y), "real")
            res = deciding(pop, y, schemes)
            receipt["steps"]["4_realised_power"] = step_power(res, "real")
            # every earlier step passed: Delta may now be written
            receipt["deciding"] = public(res)
            receipt["verdict"] = verdict(res)
            receipt["descriptive"] = descriptives(pop, y, schemes, res)
        else:
            receipt["steps"]["3_training_score_check"] = step_training(null_ins, "synthetic null (dry run)")
            receipt["steps"]["4_realised_power"] = step_power(null_res, "synthetic null projection (dry run)")
            receipt["verdict"] = {"verdict": "NONE (synthetic-only dry run; no real Delta exists)"}
    except Untestable as exc:
        receipt["steps"][exc.step] = {"status": "FAILED", **exc.numbers}
        receipt["verdict"] = {"verdict": f"US11: UNTESTABLE (failed at {exc.step})"}
    receipt["layout_manifest_sha256_after"] = sha256_file(layout / "manifest.json")
    receipt["manifest_unchanged"] = receipt["layout_manifest_sha256_after"] == manifest_before
    receipt["seconds"] = round(time.perf_counter() - t0, 2)
    receipt["peak_working_set_mb"] = peak_mb()
    text = json.dumps(receipt, indent=1, sort_keys=True, default=float)
    Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({"verdict": receipt["verdict"], "steps": receipt["steps"],
                      "population": receipt.get("population"), "seconds": receipt["seconds"],
                      "peak_working_set_mb": receipt["peak_working_set_mb"],
                      "manifest_unchanged": receipt["manifest_unchanged"],
                      "receipt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                     indent=1, sort_keys=True, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
