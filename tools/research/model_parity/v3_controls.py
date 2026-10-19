"""HARNESS v3 controls on DEVELOPMENT data (target dates <= 2026-09-29 only).

Run through ``test_v3_controls_dev.py`` under ``scripts/ops/workstation_heavy.ps1 -Kind pytest``.
Every label/market read goes through the gate with purpose ``control``. Nothing here is evidence
for a new claim; the dev dates were already read by 79a/81a/111h and swarm v2.

    (0) v2 positive control unchanged: 111h C1 -0.006891 [-0.011894, -0.002688]; served/market 1.768x
    (a) EF section 3 serving-floor shift 1.6639 -> 1.4980 from its committed fixture
    (b) injected-skill candidate recovered at the H3-predicted power
    (c) a planted label column in a candidate's input is refused
    (d) the market as its own candidate gives R = 1 exactly (single-shot scorer, sealed)
    (e) 200 date-shuffle permutations of a pure-oracle injection show no edge in >= 95%
    (f) every arm is also scored with its inputs removed (input-removed twin)
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import (v3_arms, v3_core, v3_gate, v3_inputs, v3_outcomes, v3_power,
                                         v3_score)

HERE = Path(__file__).resolve().parent
DEV_FIRST, DEV_LAST = "2026-07-31", "2026-09-29"
CONTROL_FAMILY = "harness_v3_controls"
FLOOR_FIXTURE_COMMIT = "ba748b76289f8d04864c7c7faf0448128c393e9d"
FLOOR_FIXTURE_PATH = "tests/fixtures/reporting/model_market_skill_tracker/hard_floor_snapshot_deltas.csv"
FLOOR_FIXTURE_SHA256 = "8ac77c0840b0ad6dd581cb0ecfc2449ffc5db53d788d715861c7411b07291405"
FLOOR_SEED, FLOOR_REPS = 3_215_258_335, 2000
FLOOR_REFERENCE = {"baseline": 1.6639158425, "hard": 1.4979600580, "delta": -0.1659557845,
                   "ci95": [-0.3552671491, -0.0697874559]}
TARGET_EFFECT = -0.0050          # one half of the MG-1 00-16 development estimate (-0.0100, EF 10q)
GROUP = "00-16"


# ----------------------------------------------------------------------------- (0)

def v2_positive_control():
    from tools.research.model_parity import harness as h
    pc = h.positive_control()
    facts = h.table_facts()
    return {"HARNESS_SHA256": h.harness_sha256(), "exact_81a_summarize": pc["exact_81a_summarize"],
            "pass": pc["pass"], "served_to_market_ratio": facts["served_to_market_ratio"],
            "snapshots": pc["snapshots"], "market_days": pc["market_days"],
            "eligible_snapshots": pc["eligible_snapshots"]}


# ----------------------------------------------------------------------------- (a)

def floor_shift(csv_bytes, gate):
    """EF 3 reproduction exactly as the 2026-08-06 skill tracker computed it (seed 3215258335)."""
    sha = hashlib.sha256(csv_bytes).hexdigest()
    if sha != FLOOR_FIXTURE_SHA256:
        raise AssertionError(f"floor fixture sha256 {sha} != {FLOOR_FIXTURE_SHA256}")
    frame = pd.read_csv(io.BytesIO(csv_bytes), usecols=["target_date", "market_id", "baseline_current_brier",
                                                        "hard_current_brier", "market_brier"])
    gate.require("serving_floor_control", sorted(frame.target_date.unique()), "control", False)
    base, hard, mk = (frame[c].to_numpy(float) for c in ("baseline_current_brier", "hard_current_brier",
                                                         "market_brier"))
    dates, markets = frame.target_date.astype(str).to_numpy(), frame.market_id.astype(str).to_numpy()
    ud, um = sorted(np.unique(dates)), sorted(np.unique(markets))
    di = np.array([ud.index(x) for x in dates])
    mi = np.array([um.index(x) for x in markets])
    rng = np.random.default_rng(FLOOR_SEED)
    draws = []
    for _ in range(FLOOR_REPS):
        dc = np.bincount(rng.integers(0, len(ud), len(ud)), minlength=len(ud))
        mc = np.bincount(rng.integers(0, len(um), len(um)), minlength=len(um))
        w = dc[di] * mc[mi]
        den = float(np.dot(w, mk))
        if den > 0:
            draws.append(float(np.dot(w, hard) / den - np.dot(w, base) / den))
    out = {"source": {"commit": FLOOR_FIXTURE_COMMIT, "path": FLOOR_FIXTURE_PATH, "sha256": sha},
           "dates": [ud[0], ud[-1]], "date_clusters": len(ud), "market_clusters": len(um),
           "market_days": int(frame[["target_date", "market_id"]].drop_duplicates().shape[0]),
           "snapshots": int(len(frame)), "baseline_ratio": float(base.sum() / mk.sum()),
           "hard_ratio": float(hard.sum() / mk.sum()),
           "ci95": [float(x) for x in np.quantile(draws, [0.025, 0.975])]}
    out["delta"] = out["hard_ratio"] - out["baseline_ratio"]
    out["pass"] = (round(out["baseline_ratio"], 10) == FLOOR_REFERENCE["baseline"]
                   and round(out["hard_ratio"], 10) == FLOOR_REFERENCE["hard"]
                   and [round(x, 10) for x in out["ci95"]] == FLOOR_REFERENCE["ci95"])
    return out


# ----------------------------------------------------------------------------- dev table

class Dev:
    """Dev layout + labels + market under one control ticket."""

    def __init__(self, layout, gate):
        dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(DEV_FIRST, DEV_LAST)]
        self.ticket = gate.require(CONTROL_FAMILY, dates, "control", True)
        self.snaps, self.bands, self.manifest = v3_inputs.read_inputs(layout, gate, CONTROL_FAMILY, True)
        labels, market = v3_outcomes.load_outcomes(layout, gate, self.ticket)
        if max(self.snaps.date.astype(str)) > DEV_LAST or max(labels.date.astype(str)) > DEV_LAST:
            raise AssertionError("a dev row is after 2026-09-29")
        self.t = v3_core.Table(self.snaps, self.bands)
        lab = labels.set_index("row_key").reindex(self.t.snaps.row_key)
        self.bucket = lab.settlement_bucket.to_numpy(float)
        winner = lab.winner.to_numpy(int)
        self.y = (self.bands.band_index.to_numpy(int) == np.repeat(winner, self.t.n)).astype(float)
        self.pm = market.set_index(["row_key", "band_index"]).p_market_yes.reindex(
            pd.MultiIndex.from_arrays([self.bands.row_key, self.bands.band_index])).to_numpy(float)
        self.mask = self.t.group_mask(GROUP)

    def delta_cells(self, p):
        """Equal-weight (date, market) cells of candidate - served Brier in GROUP."""
        t = self.t
        idx, c = t.cells(t.snapshot_brier(p, self.y) - t.snapshot_brier(t.p_served, self.y), self.mask)
        return idx, c

    def floored(self, p):
        cand = self.bands[["row_key", "band_index"]].assign(p=p)
        return self.t.candidate_vector(cand, floor=True)[0]


def _inject(dev, lam, rng, centre=0.6, spread=0.5):
    """Cell-level injection with date and market structure (so power is not trivially 1).

    Each (date, market) cell moves every snapshot lam toward the truth with probability
    q = clip(centre + spread * (z_date + z_market) / sqrt(2), 0, 1), otherwise toward one random band
    chosen per cell. The net effect is negative on average but varies by date, market and cell."""
    t = dev.t
    dates = sorted(t.snaps.date.astype(str).unique())
    markets = sorted(t.snaps.market.astype(str).unique())
    zd = dict(zip(dates, rng.normal(size=len(dates))))
    zm = dict(zip(markets, rng.normal(size=len(markets))))
    q = np.array([min(1.0, max(0.0, centre + spread * (zd[k[0]] + zm[k[1]]) / np.sqrt(2))) for k in t.keys])
    truthful_cell = rng.random(len(t.keys)) < q
    rand_rank = rng.random(len(t.keys))
    truthful = truthful_cell[t.cell]
    rand_band = np.minimum((rand_rank[t.cell] * t.n).astype(int), t.n - 1)
    target = np.where(truthful, -1, rand_band)
    tgt = np.where(np.repeat(target, t.n) < 0, dev.y,
                   (dev.bands.band_index.to_numpy(int) == np.repeat(target, t.n)).astype(float))
    return (1 - lam) * t.p_served + lam * tgt


def _components(dev, idx, cells, seed=20261019, draws=2000):
    """Crossed (W), date-only and market-only bootstrap SDs of the equal market-day mean."""
    keys = [dev.t.keys[i] for i in idx]
    d = np.array([k[0] for k in keys])
    m = np.array([k[1] for k in keys])
    ud, um = np.unique(d), np.unique(m)
    di, mi = np.searchsorted(ud, d), np.searchsorted(um, m)
    rng = np.random.default_rng(seed)
    wd = rng.multinomial(len(ud), np.full(len(ud), 1 / len(ud)), size=draws)[:, di]
    wm = rng.multinomial(len(um), np.full(len(um), 1 / len(um)), size=draws)[:, mi]
    est = lambda w: (w @ cells) / w.sum(axis=1)
    crossed = dev.t.interval(idx, cells)
    z = 1.959963984540054
    return {"estimate": float(cells.mean()), "n_cells": int(len(cells)), "markets_n": int(len(um)),
            "W_sd": crossed["boot_sd"], "W_ci95": crossed["ci95"],
            "date_only_ci95": [float(cells.mean() - z * est(wd).std()), float(cells.mean() + z * est(wd).std())],
            "market_only_ci95": [float(cells.mean() - z * est(wm).std()), float(cells.mean() + z * est(wm).std())]}


def injected_skill(dev, experiments=400, seed=20261019, target_power=0.6):
    """(b): calibrate lam so the injection's GROUP delta is TARGET_EFFECT; take variance components
    from its own dev cells; choose the date count whose H3-predicted power is nearest target_power;
    compare with the empirical GO rate of crossed resamples (dates and markets with replacement)."""
    rng_seed = seed
    effect = lambda lam: dev.delta_cells(dev.floored(_inject(dev, lam, np.random.default_rng(rng_seed))))[1].mean()
    grid = np.linspace(0, 1, 41)
    curve = [effect(x) for x in grid]
    first = next((i for i, e in enumerate(curve) if e <= TARGET_EFFECT), None)
    if first is None or first == 0:
        return {"pass": False, "status": "TARGET_EFFECT_NOT_REACHABLE", "curve": list(zip(grid.tolist(), curve))}
    lo, hi = grid[first - 1], grid[first]
    for _ in range(30):
        lam = (lo + hi) / 2
        lo, hi = (lam, hi) if effect(lam) > TARGET_EFFECT else (lo, lam)
    lam = (lo + hi) / 2
    p = dev.floored(_inject(dev, lam, np.random.default_rng(rng_seed)))
    idx, cells = dev.delta_cells(p)
    w_based = dev.t.interval(idx, cells, effect=v3_core.MDE_EFFECT)
    comp = v3_power.components_from_entry(_components(dev, idx, cells))
    args = (comp["var_date"], comp["var_market"], comp["var_resid"])
    m = comp["dev_markets"]
    analytic = {n: v3_power.plan(*args, n, m, float(cells.mean()), 1.0, sims=1, seed=seed)["analytic_power"]
                for n in range(4, 57)}
    d_sub = min(analytic, key=lambda n: abs(analytic[n] - target_power))
    pred = v3_power.plan(*args, d_sub, m, dev_estimate=float(cells.mean()), effect_fraction=1.0,
                         sims=2000, seed=seed)
    keys = [dev.t.keys[i] for i in idx]
    table = pd.DataFrame({"date": [k[0] for k in keys], "market": [k[1] for k in keys], "v": cells}).pivot(
        index="date", columns="market", values="v").dropna()
    x = table.to_numpy(float)
    rng = np.random.default_rng(seed + 7)
    go = 0
    for _ in range(experiments):
        sub = x[rng.integers(0, x.shape[0], d_sub)][:, rng.integers(0, x.shape[1], x.shape[1])]
        go += int(sub.mean() + 1.959963984540054 * v3_power.crossed_se(sub) < 0)
    emp = go / experiments
    pp = pred["simulated_power_go_given_effect"]
    mc_se = float(np.sqrt(pp * (1 - pp) / experiments + pp * (1 - pp) / pred["sims"]))
    return {"lambda": lam, "injection": "cell-level, date/market structured (centre 0.6, spread 0.5)", "group": GROUP,
            "target_effect": TARGET_EFFECT, "recovered_full_dev": w_based, "components": comp,
            "design": {"dates": d_sub, "markets": int(x.shape[1])},
            "h3_predicted_power": pp, "h3_analytic_power": pred["analytic_power"], "h3_mde80": pred["mde80"],
            "h3_go_given_null": pred["simulated_go_given_null"], "empirical_power": emp,
            "experiments": experiments, "mc_se": mc_se, "balanced_dates_available": int(x.shape[0]),
            "pass": bool(abs(emp - pp) <= max(0.10, 3 * mc_se)
                         and w_based["ci95"][0] <= TARGET_EFFECT <= w_based["ci95"][1])}


def date_shuffle(dev, permutations=200, lam=0.30, seed=20261019):
    """(e): pure-oracle injection toward the settled bucket of a DIFFERENT date (same market)."""
    t = dev.t
    real_p = dev.floored((1 - lam) * t.p_served + lam * dev.y)
    real_idx, real_cells = dev.delta_cells(real_p)
    real = t.interval(real_idx, real_cells)
    dates = np.array(sorted(t.snaps.date.astype(str).unique()))
    snap_date = t.snaps.date.astype(str).to_numpy()
    snap_mkt = t.snaps.market.astype(str).to_numpy()
    md_bucket = pd.Series(dev.bucket).groupby([snap_date, snap_mkt]).first()
    kind, low, high = t.bands.kind.to_numpy(), t.bands.low.to_numpy(float), t.bands.high.to_numpy(float)
    rng = np.random.default_rng(seed)
    rows, edges = [], 0
    for _ in range(permutations):
        while True:
            perm = rng.permutation(len(dates))
            if not (perm == np.arange(len(dates))).any():
                break
        mapping = dict(zip(dates, dates[perm]))
        src = pd.MultiIndex.from_arrays([[mapping[d] for d in snap_date], snap_mkt])
        b = md_bucket.reindex(src).to_numpy(float)
        bb = np.repeat(b, t.n)
        contains = ((kind == "lte") | (bb >= low)) & ((kind == "gte") | (bb <= high)) & ~np.isnan(bb)
        p = np.where(np.repeat(np.isnan(b), t.n), t.p_served,
                     (1 - lam) * t.p_served + lam * contains.astype(float))
        idx, cells = dev.delta_cells(dev.floored(p))
        iv = t.interval(idx, cells)
        edge = iv["ci95"][1] < 0
        edges += int(edge)
        rows.append({"estimate": iv["estimate"], "ci95": iv["ci95"], "edge": bool(edge)})
    share_no_edge = 1 - edges / permutations
    return {"lambda": lam, "group": GROUP, "unshuffled_oracle": real, "permutations": permutations,
            "derangements": True, "edges": edges, "share_no_edge": share_no_edge,
            "estimate_quantiles": np.quantile([r["estimate"] for r in rows], [0, .05, .5, .95, 1]).tolist(),
            "pass": bool(share_no_edge >= 0.95 and real["ci95"][1] < 0)}


# ----------------------------------------------------------------------------- (c), (d), (f)

def write_planted_layout(layout, out, gate):
    """A copy of the dev layout whose snapshot inputs carry settlement_high under a bland name."""
    snaps, bands, _ = v3_inputs.read_inputs(layout, gate, CONTROL_FAMILY, True)
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(DEV_FIRST, DEV_LAST)]
    labels, market = v3_outcomes.load_outcomes(layout, gate, gate.require(CONTROL_FAMILY, dates, "control", True))
    lab = labels.set_index("row_key").reindex(snaps.row_key)
    planted = snaps.assign(aux_station_feature=lab.settlement_high.to_numpy(float))
    return v3_outcomes.write_layout(out, planted, bands, labels, market, source={"planted_from": str(layout)})


def write_prereg(path, arms, purpose="control", **extra):
    specs = []
    for a in arms:
        if a in v3_score.BUILTINS:
            specs.append({"builtin": a})
        else:
            p = HERE / a
            specs.append({"path": str(p), "code_sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    prereg = {"schema": v3_score.PREREG_SCHEMA, "prereg_id": Path(path).stem, "purpose": purpose,
              "dates": {"start": DEV_FIRST, "end": DEV_LAST}, "arms": specs, **extra}
    Path(path).write_text(json.dumps(prereg, indent=1), encoding="utf-8")
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarise_run(payload):
    e1 = payload["E1"]
    out = {}
    for name, r in e1.items():
        out[name] = {g: {"R": x["E1_R_arm_over_market"]["estimate"], "R_ci95": x["E1_R_arm_over_market"]["ci95"],
                         "arm_minus_served": x["arm_minus_served"]["estimate"],
                         "arm_minus_served_ci95": x["arm_minus_served"]["ci95"],
                         "coverage": x["arm_coverage_share"], "market_days": x["market_days"]}
                     for g, x in r["groups"].items() if "E1_R_arm_over_market" in x}
    return out
