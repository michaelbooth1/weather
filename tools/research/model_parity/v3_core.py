"""HARNESS v3 scoring core on in-memory arrays (no file access).

Semantics follow harness v2 exactly (rule 4 floor mask + renormalise, served fallback on every
uncovered row, per-snapshot Brier = mean over bands, equal market-day cells, one crossed
date x market weight matrix from ``crossed_weights`` with DRAWS/SEED) so that a v3 score of a
candidate equals its v2 score on the same rows.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tools.research.missing_information.methods import crossed_weights
from tools.research.morning_guidance.statistics import DRAWS, SEED, inference
from tools.research.model_parity import v3_arms
from tools.research.model_parity.v3_inputs import FLOOR_FIELDS, GROUPS, group_mask

CANDIDATE_COLUMNS = ("row_key", "band_index", "p")
MDE_EFFECT = -0.0075
LABELISH = v3_arms.LABELISH   # labels and market prices: never in candidate frames


class LeakageError(AssertionError):
    pass


def floor_values(snaps):
    vals = snaps[list(FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce")
    return vals.max(axis=1, skipna=True).to_numpy(float)


def floor_impossible(bands, snaps, offsets):
    """81a mask: non-gte band with high < floor(floor + 0.5) is impossible."""
    floor = floor_values(snaps)
    n = snaps.n_bands.to_numpy()
    fb = np.repeat(floor, n)
    bucket = np.floor(fb + 0.5)
    imp = (bands.kind.to_numpy() != "gte") & (bands.high.to_numpy(float) < bucket)
    return np.where(np.isnan(fb), False, imp), ~np.isnan(floor)


class Table:
    """Aligned snapshot/band arrays for one scoring population."""

    def __init__(self, snaps, bands):
        self.snaps = snaps.reset_index(drop=True)
        self.bands = bands.reset_index(drop=True)
        n = self.snaps.n_bands.to_numpy().astype(int)
        self.n = n
        self.offsets = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
        self.band_snap = np.repeat(np.arange(len(self.snaps)), n)
        self.snap_pos = pd.Series(np.arange(len(self.snaps)), index=self.snaps.row_key.to_numpy())
        self.p_served = self.bands.p_served.to_numpy(float)
        self.impossible, self.has_floor = floor_impossible(self.bands, self.snaps, self.offsets)
        if "floor_impossible" in self.bands.columns:          # v2 cache precomputed mask: must agree
            stored = self.bands.floor_impossible.to_numpy(bool)
            if not (stored == self.impossible).all():
                raise ValueError("stored floor_impossible disagrees with the rule-4 mask")
        self.local_hour = self.snaps.local_hour.to_numpy(int)
        keys = sorted(set(zip(self.snaps.date.astype(str), self.snaps.market.astype(str))))
        self.keys = keys
        self.key_index = {k: i for i, k in enumerate(keys)}
        self.cell = np.array([self.key_index[(d, m)] for d, m in
                              zip(self.snaps.date.astype(str), self.snaps.market.astype(str))])
        self.w = crossed_weights([k[0] for k in keys], [k[1] for k in keys], draws=DRAWS, seed=SEED)

    # ------------------------------------------------------------------ candidates
    def candidate_vector(self, candidate, floor=True):
        """Return (p per band, use per snapshot, reason per snapshot) with v2 semantics."""
        if not isinstance(candidate, pd.DataFrame):
            raise TypeError("candidate must be a DataFrame row_key, band_index, p")
        cols = set(candidate.columns)
        if LABELISH & cols:
            raise LeakageError(f"candidate frame carries forbidden columns {sorted(LABELISH & cols)}")
        if cols != set(CANDIDATE_COLUMNS):
            raise ValueError(f"candidate columns must be exactly {CANDIDATE_COLUMNS}, got {sorted(cols)}")
        if candidate.duplicated(["row_key", "band_index"]).any():
            raise ValueError("duplicate (row_key, band_index) in candidate")
        candidate = candidate[candidate.row_key.isin(self.snap_pos.index)]
        pos = self.snap_pos.reindex(candidate.row_key.to_numpy()).to_numpy().astype(int)
        bi = candidate.band_index.to_numpy(int)
        if ((bi < 0) | (bi >= self.n[pos])).any():
            raise ValueError("band_index out of range")
        pc = np.full(len(self.bands), np.nan)
        pc[self.offsets[pos] + bi] = candidate.p.to_numpy(float)
        given = ~np.isnan(pc)
        n_given = np.bincount(self.band_snap, weights=given, minlength=len(self.snaps))
        if ((n_given > 0) & (n_given < self.n)).any():
            raise ValueError("some snapshots have probabilities for only some bands")
        provided = n_given == self.n
        if (pc[given] < 0).any() or not np.isfinite(pc[given]).all():
            raise ValueError("candidate probabilities must be finite and >= 0")
        reason = np.where(provided, "candidate", "absent").astype(object)
        if floor:
            no_floor = provided & ~self.has_floor
            reason[no_floor] = "missing_floor"
            pc[self.impossible & given] = 0.0
        else:
            no_floor = np.zeros(len(self.snaps), bool)
        total = np.bincount(self.band_snap, weights=np.where(given, pc, 0.0), minlength=len(self.snaps))
        zero = provided & ~no_floor & ~(total > 0)
        reason[zero] = "zero_mass_after_floor"
        use = provided & ~no_floor & ~zero
        scale = np.where((total > 0) & (np.abs(total - 1.0) > 1e-12), total, 1.0)
        pc = np.where(use[self.band_snap], pc / scale[self.band_snap], self.p_served)
        return pc, use, reason

    # ------------------------------------------------------------------ statistics
    def snapshot_brier(self, p, y):
        return np.add.reduceat((p - y) ** 2, self.offsets) / self.n

    def cells(self, snap_values, mask):
        """Equal-weight mean of per-snapshot values within each (date, market) cell under mask."""
        idx = self.cell[mask]
        sums = np.bincount(idx, weights=snap_values[mask], minlength=len(self.keys))
        counts = np.bincount(idx, minlength=len(self.keys))
        present = np.flatnonzero(counts)
        return present, sums[present] / counts[present]

    def interval(self, idx, a, b=None, effect=None):
        a = np.asarray(a, float)
        b = np.ones(len(a)) if b is None else np.asarray(b, float)
        point = float(a.sum() / b.sum()) if b.sum() > 0 else float("nan")
        sub = self.w[:, idx]
        num, den = sub @ a, sub @ b
        boot = np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)
        if effect is not None:
            out = inference(point, boot, effect)
            out["ci95"] = [float(x) for x in out["ci95"]]
        else:
            fin = boot[np.isfinite(boot)]
            out = {"estimate": point, "ci95": np.quantile(fin, [.025, .975]).tolist() if len(fin)
                   else [math.nan, math.nan], "valid_draws": int(len(fin))}
        fin = boot[np.isfinite(boot)]
        out["boot_sd"] = float(fin.std(ddof=1)) if len(fin) > 1 else math.nan
        return out

    def group_mask(self, group):
        return group_mask(self.local_hour, group)


def groups():
    return [g for g, _, _ in GROUPS]
