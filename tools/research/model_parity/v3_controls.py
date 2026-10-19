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


def _inject(dev, lam, rng, centre=0.55, spread=1.0):
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
    return {"lambda": lam, "injection": "cell-level, date/market structured (centre 0.55, spread 1.0)", "group": GROUP,
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



# ----------------------------------------------------------------------------- (b2) mid-power calibration
# Added 2026-10-20 (master-agent ruling): H3 predicted vs empirical power where it matters, ~0.40 and
# ~0.55-0.60, with tight empirical intervals.

def _wilson(k, n, z=1.959963984540054):
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [float(centre - half), float(centre + half)]


def _calibrated_cells(dev, target, seed):
    effect = lambda lam: dev.delta_cells(dev.floored(_inject(dev, lam, np.random.default_rng(seed))))[1].mean()
    grid = np.linspace(0, 0.5, 21)
    curve = [effect(x) for x in grid]
    first = next((i for i, e in enumerate(curve) if e <= target), None)
    if first is None or first == 0:
        return None
    lo, hi = grid[first - 1], grid[first]
    for _ in range(22):
        lam = (lo + hi) / 2
        lo, hi = (lam, hi) if effect(lam) > target else (lo, lam)
    lam = (lo + hi) / 2
    idx, cells = dev.delta_cells(dev.floored(_inject(dev, lam, np.random.default_rng(seed))))
    return lam, idx, cells


def _empirical_power(x, d_sub, experiments, seed):
    rng = np.random.default_rng(seed)
    go = 0
    for _ in range(experiments):
        sub = x[rng.integers(0, x.shape[0], d_sub)][:, rng.integers(0, x.shape[1], x.shape[1])]
        go += int(sub.mean() + 1.959963984540054 * v3_power.crossed_se(sub) < 0)
    return go


def power_calibration(dev, targets=(0.575, 0.40), effects=(-0.0004, -0.0005, -0.0006, -0.0007, -0.0008, -0.001, -0.0012, -0.0015),
                      min_dates=8, experiments=4000, sims=20000, seed=20261020):
    """For each target power choose (injected effect, new dates) from H3's analytic power, then
    compare H3's simulated prediction (bootstrap-SD components, as H3 ships, and two-way MoM
    components) with the empirical GO rate of ``experiments`` crossed resamples of the real cells."""
    from scipy.stats import norm
    pool = []
    for eff in effects:
        got = _calibrated_cells(dev, eff, seed)
        if got is None:
            continue
        lam, idx, cells = got
        keys = [dev.t.keys[i] for i in idx]
        table = pd.DataFrame({"date": [k[0] for k in keys], "market": [k[1] for k in keys], "v": cells}).pivot(
            index="date", columns="market", values="v").dropna()
        x = table.to_numpy(float)
        comp = v3_power.components_from_entry(_components(dev, idx, cells))
        mom = v3_power.components_from_table(x)
        for d in range(min_dates, x.shape[0] + 1):
            se = v3_power.analytic_se(comp["var_date"], comp["var_market"], comp["var_resid"], d, x.shape[1])
            power = float(norm.cdf(abs(cells.mean()) / se - 1.959963984540054))
            pool.append({"effect": eff, "lam": lam, "dates": d, "analytic": power, "x": x, "comp": comp,
                         "mom": mom, "estimate": float(cells.mean())})
    out = {"targets": list(targets), "experiments": experiments, "sims": sims, "min_dates": min_dates,
           "rule": "GO iff mean + 1.96 * two-way MoM crossed SE < 0 (H3's own rule) in both worlds",
           "designs": []}
    for k, target in enumerate(targets):
        if not pool:
            out["designs"].append({"target": target, "status": "NO_DESIGN"})
            continue
        best = min(pool, key=lambda r: (abs(r["analytic"] - target), -r["dates"]))
        x, d, m = best["x"], best["dates"], best["x"].shape[1]

        def args(c):
            return c["var_date"], c["var_market"], c["var_resid"]
        pred = v3_power.simulate(best["estimate"], *args(best["comp"]), d, m, sims=sims, seed=seed + 10 * k)
        pred_mom = v3_power.simulate(best["estimate"], *args(best["mom"]), d, m, sims=sims, seed=seed + 10 * k + 1)
        null = v3_power.simulate(0.0, *args(best["comp"]), d, m, sims=sims, seed=seed + 10 * k + 2)
        go = _empirical_power(x, d, experiments, seed + 10 * k + 3)
        emp = go / experiments
        se_diff = float(np.sqrt(emp * (1 - emp) / experiments + pred * (1 - pred) / sims))
        se_diff_mom = float(np.sqrt(emp * (1 - emp) / experiments + pred_mom * (1 - pred_mom) / sims))
        out["designs"].append({
            "target": target, "injected_effect": best["effect"], "realised_estimate": best["estimate"],
            "lambda": best["lam"], "dates": d, "markets": m, "balanced_dates_available": int(x.shape[0]),
            "components_bootstrap_sd": {kk: best["comp"][kk] for kk in ("var_date", "var_market", "var_resid")},
            "components_mom": {kk: best["mom"][kk] for kk in ("var_date", "var_market", "var_resid")},
            "h3_analytic_power": best["analytic"], "h3_predicted_power": pred, "h3_go_given_null": null,
            "h3_mom_predicted_power": pred_mom,
            "empirical_power": emp, "empirical_ci95_wilson": _wilson(go, experiments), "empirical_go": go,
            "bias_h3_minus_empirical": pred - emp,
            "bias_ci95": [pred - emp - 1.96 * se_diff, pred - emp + 1.96 * se_diff],
            "bias_mom_minus_empirical": pred_mom - emp,
            "bias_mom_ci95": [pred_mom - emp - 1.96 * se_diff_mom, pred_mom - emp + 1.96 * se_diff_mom]})
    return out



# ----------------------------------------------------------------------------- NO-GO reachability (2026-10-20)

NOGO_BLOCKS = ("00-05", "06-09", "10-12", "13-16")


def _arm_vector(dev, arm_file):
    from tools.research.model_parity import v3_arms
    arm = v3_arms.load_arm(HERE / arm_file)
    return dev.t.candidate_vector(v3_arms.build(arm, dev.snaps, dev.bands))[0], arm.CODE_SHA256


def _block_table(dev, p, e2_weight):
    """Balanced (D, M, K+1) influence table: K 00-16 blocks' R plus E2 (00-16 group)."""
    t = dev.t
    arm = t.snapshot_brier(p, dev.y)
    mkt = t.snapshot_brier(dev.pm, dev.y)
    blend = t.snapshot_brier(e2_weight * p + (1 - e2_weight) * dev.pm, dev.y)
    frames = []
    for name in NOGO_BLOCKS + ("E2",):
        mask = t.group_mask("00-16" if name == "E2" else name)
        idx, a = t.cells(blend if name == "E2" else arm, mask)
        _, m = t.cells(mkt, mask)
        frames.append(pd.DataFrame({"key": idx, f"a_{name}": a, f"m_{name}": m}).set_index("key"))
    cells = pd.concat(frames, axis=1, join="inner")
    cells["date"] = [t.keys[i][0] for i in cells.index]
    cells["market"] = [t.keys[i][1] for i in cells.index]
    full = cells.groupby("date").market.transform("size") == cells.market.nunique()
    cells = cells[full]
    names = NOGO_BLOCKS + ("E2",)
    ratio = {n: float(cells[f"a_{n}"].sum() / cells[f"m_{n}"].sum()) for n in names}
    for n in names:
        cells[f"z_{n}"] = (cells[f"a_{n}"] - ratio[n] * cells[f"m_{n}"]) / cells[f"m_{n}"].mean()
    dates, markets = sorted(cells.date.unique()), sorted(cells.market.unique())
    cube = np.stack([cells.pivot(index="date", columns="market", values=f"z_{n}").loc[dates, markets].to_numpy()
                     for n in names], axis=-1)
    return ratio, cube


def nogo_reachability(dev, forward=(20, 45, 90), sims=20000, interim=20, final=45, futility_z=0.2656,
                      seed=20261020):
    pm1, sha_mg1 = _arm_vector(dev, "v3_arm_mg1_like.py")
    psv, _ = _arm_vector(dev, "v3_arm_served.py")
    dates = sorted(dev.snaps.date.astype(str).unique())
    w = v3_score.fit_blend_weights(dev.t, pm1, dev.y, dev.pm, dates)["00-16"]
    ratio, cube = _block_table(dev, pm1, w)
    _, cube_served = _block_table(dev, psv, w)
    comps = {"mg1_like": v3_power.mom_cov(cube), "served": v3_power.mom_cov(cube_served)}
    r_dev = np.array([ratio[b] for b in NOGO_BLOCKS])
    e2_dev = ratio["E2"] - 1.0
    scen = {"dev_observed": (r_dev, e2_dev), "half_effect": (1 + (r_dev - 1) / 2, e2_dev / 2),
            "null_R_eq_1": (np.ones(len(NOGO_BLOCKS)), 0.0)}
    out = {"arm_code_sha256": sha_mg1, "e2_weight_00_16_fit_on_dev": w, "dev_R": dict(zip(NOGO_BLOCKS, r_dev.tolist())),
           "dev_E2_minus_1": e2_dev, "balanced_dates": int(cube.shape[0]), "markets": int(cube.shape[1]),
           "components_diag": {k: {"date": np.diag(c[0]).tolist(), "market": np.diag(c[1]).tolist(),
                                   "resid": np.diag(c[2]).tolist()} for k, c in comps.items()},
           "rule": "NO-GO: lower 95% bound of R > 1.05 in every 00-16 block AND E2 upper bound > -0.5% of market Brier",
           "half_effect_definition": "R = 1 + (R_dev - 1) / 2 per block; E2 halved",
           "nogo": []}
    for cname, cc in comps.items():
        for sname, (rm, em) in scen.items():
            for n in forward:
                r = v3_power.simulate_nogo(rm, em, cc, n, cube.shape[1], sims=sims, seed=seed + n)
                out["nogo"].append({"components": cname, "scenario": sname, **r})
    # interim futility (H7 boundary at t = 20/45) on two statistics
    idx, delta = dev.delta_cells(pm1)
    keys = [dev.t.keys[i] for i in idx]
    dtab = pd.DataFrame({"date": [k[0] for k in keys], "market": [k[1] for k in keys], "v": delta}).pivot(
        index="date", columns="market", values="v").dropna().to_numpy()[:, :, None]
    t = dev.t
    mask = t.group_mask("00-16")
    i1, a = t.cells(t.snapshot_brier(pm1, dev.y), mask)
    _, m = t.cells(t.snapshot_brier(dev.pm, dev.y), mask)
    r16 = float(a.sum() / m.sum())
    z16 = (a - r16 * m) / m.mean()
    k16 = [t.keys[i] for i in i1]
    rtab = pd.DataFrame({"date": [k[0] for k in k16], "market": [k[1] for k in k16], "v": z16}).pivot(
        index="date", columns="market", values="v").dropna().to_numpy()[:, :, None]
    stats = {"arm_minus_served_00_16": (float(delta.mean()), v3_power.mom_cov(dtab)),
             "R_minus_1_00_16": (r16 - 1.0, v3_power.mom_cov(rtab))}
    from tools.research.model_parity import v3_sequential
    out["h7_boundary_check"] = v3_sequential.boundaries([interim / final, 1.0])["looks"][0]
    out["interim"] = []
    for sname, (dev_eff, cc) in stats.items():
        for label, eff in (("dev_observed", dev_eff), ("half_effect", dev_eff / 2), ("null", 0.0)):
            r = v3_power.simulate_interim(eff, cc, interim, final, dtab.shape[1], futility_z, sims=sims,
                                          seed=seed + 7)
            out["interim"].append({"statistic": sname, "scenario": label, "effect": eff, **r})
    return out



def power_calibration_real_noise(dev, targets=(0.575, 0.40), designs=(20, 45), experiments=8000, sims=20000,
                                 seed=20261021):
    """Injected effect on REAL candidate noise: the MG-1-like arm's 00-16 (arm - served) cells,
    re-centred to exactly the injected effect. That is a synthetic candidate whose true effect is
    known and whose date/market/residual structure is the real one (the regime EDGE-1 lives in).
    The effect is chosen per (dates, target) from H3's analytic power; H3's simulated prediction
    (bootstrap-SD components, as shipped, and two-way MoM) is compared with ``experiments`` crossed
    resamples (dates and markets with replacement) of the re-centred cells."""
    from scipy.stats import norm
    from tools.research.model_parity import v3_arms
    arm = v3_arms.load_arm(HERE / "v3_arm_mg1_like.py")
    p = dev.t.candidate_vector(v3_arms.build(arm, dev.snaps, dev.bands))[0]
    idx, cells = dev.delta_cells(p)
    keys = [dev.t.keys[i] for i in idx]
    x0 = pd.DataFrame({"date": [k[0] for k in keys], "market": [k[1] for k in keys], "v": cells}).pivot(
        index="date", columns="market", values="v").dropna().to_numpy(float)
    centred = x0 - x0.mean()
    comp = v3_power.components_from_entry(_components(dev, idx, cells - cells.mean()))
    mom = v3_power.components_from_table(centred)
    args = lambda c: (c["var_date"], c["var_market"], c["var_resid"])
    m = x0.shape[1]
    out = {"source": "mg1_like arm - served, 00-16 cells, re-centred", "arm_code_sha256": arm.CODE_SHA256,
           "dev_estimate": float(cells.mean()), "balanced_dates": int(x0.shape[0]), "markets": m,
           "components_bootstrap_sd": {k: comp[k] for k in ("var_date", "var_market", "var_resid")},
           "components_mom": {k: mom[k] for k in ("var_date", "var_market", "var_resid")},
           "experiments": experiments, "sims": sims, "designs": []}
    k = 0
    for d in designs:
        se = v3_power.analytic_se(*args(comp), d, m)
        for target in targets:
            effect = -float((Z975_ + norm.ppf(target)) * se)
            pred = v3_power.simulate(effect, *args(comp), d, m, sims=sims, seed=seed + k)
            pred_mom = v3_power.simulate(effect, *args(mom), d, m, sims=sims, seed=seed + k + 1)
            go = _empirical_power(centred + effect, d, experiments, seed + k + 2)
            emp = go / experiments
            se_b = float(np.sqrt(emp * (1 - emp) / experiments + pred * (1 - pred) / sims))
            se_m = float(np.sqrt(emp * (1 - emp) / experiments + pred_mom * (1 - pred_mom) / sims))
            out["designs"].append({
                "target": target, "dates": d, "markets": m, "injected_effect": effect,
                "h3_analytic_power": float(norm.cdf(-effect / se - Z975_)), "h3_predicted_power": pred,
                "h3_mom_predicted_power": pred_mom, "empirical_power": emp,
                "empirical_ci95_wilson": _wilson(go, experiments), "empirical_go": go,
                "bias_h3_minus_empirical": pred - emp, "bias_ci95": [pred - emp - 1.96 * se_b, pred - emp + 1.96 * se_b],
                "bias_mom_minus_empirical": pred_mom - emp,
                "bias_mom_ci95": [pred_mom - emp - 1.96 * se_m, pred_mom - emp + 1.96 * se_m]})
            k += 10
    return out


Z975_ = 1.959963984540054
