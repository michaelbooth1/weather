"""Model-edge lever 13 follow-up: TAIL RE-SPLIT diagnostic (descriptive, development, dates <= 2026-09-29).

Run only through ``test_me_screens_dev.py`` (phase ``tail``) under the workstation heavy wrapper. Labels and
market prices are read through the HARNESS v3 gate (purpose ``development``). No candidate is scored for a
decision; every number is descriptive.

Vectors (all through ``v3_core.Table.candidate_vector`` with the 81a floor mask and served fallback):

- ``served``     the served vector with the floor mask only (pre-#191 serving, which is every dev date);
- ``r1_lockin``  the v2 swarm ladder rung 1 = registered d-defect-r2 (S1 heuristic + S2 learned late-day lock-in
                 restored on the served final bands, production constants): the emulation of post-#191 evening
                 serving (EF 10q). Rebuilt with ``ladder_parity`` / ``d_defect_evening_stage`` unchanged; the
                 calibration artifacts it reads are this checkout's ``artifacts/calibration`` (unchanged since
                 2026-07-07, so the swarm's copy); its snapshot Brier is checked against the swarm's saved
                 ``snapb_ladder-r1.npy``;
- ``mg1_like``   the HARNESS v3 MG-1-like arm (Normal(v2_mean, max(v2_stddev, 1)));
- ``c1``         the ladder's MG-1 read in r-t5-inc-c1 form (H = max(B, X));
- ``r2``         ladder rung 2 = c1 where covered + the restored lock-in (checked against ``snapb_ladder-r2.npy``).

Tail = band rows with served SE > market SE and |p_served - p_market| >= 0.30 (EF 1/1f lens on this table).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import v3_arms, v3_core, v3_gate, v3_inputs, v3_outcomes

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEV_FIRST, DEV_LAST = "2026-07-31", "2026-09-29"
FAMILY = "model_edge_tail_resplit"
TAIL_GAP = 0.30
LADDER_OUT = Path(r"C:\swarm\out\ladder")
BLOCKS = ("00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all")
NON_NBM_COLUMNS = ("hrrr_high", "nws_grid_high_raw", "forecast_high", "high_so_far", "guidance_physical_floor")


def _ladder_vectors(snaps, bands):
    """Rebuild ladder r1 / c1 / r2 band vectors exactly as ladder_parity.run_rungs builds them."""
    from tools.research.model_parity import d_defect_evening_stage as dd
    dd.ART = REPO / "artifacts" / "calibration"
    from tools.research.model_parity import ladder_parity as lp
    n = snaps.n_bands.to_numpy().astype(int)
    offs = np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)
    band_snap = np.repeat(np.arange(len(snaps)), n)
    S = lp.strengths(snaps)
    Bb = S["B"].to_numpy(float)[band_snap]
    sb = S["s"].to_numpy(float)[band_snap]
    hasBb = ~np.isnan(S["B"].to_numpy(float))[band_snap]
    p1 = lp.lockin_on(bands, bands.p_served.to_numpy(float), Bb, sb)
    c = lp.renorm(bands[["row_key", "band_index"]].assign(p=p1))
    r1 = c[hasBb]
    pc1 = lp.c1_probs(snaps, bands, offs)
    c1cov = ~np.isnan(pc1)
    base = np.where(c1cov, pc1, bands.p_served.to_numpy(float))
    p2c = lp.lockin_on(bands, np.nan_to_num(base), np.nan_to_num(Bb), np.where(hasBb, sb, 0.0))
    c2 = lp.renorm(bands[["row_key", "band_index"]].assign(p=p2c))
    p2 = np.where(c1cov, c2.p.to_numpy(), c.p.to_numpy())
    r2 = bands.loc[hasBb, ["row_key", "band_index"]].assign(p=p2[hasBb])
    c1 = bands.loc[c1cov, ["row_key", "band_index"]].assign(p=pc1[c1cov])
    strength = S["s"].to_numpy(float)
    return {"r1_lockin": r1, "c1": c1, "r2": r2}, strength


class Tail:
    def __init__(self, layout, gate):
        dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(DEV_FIRST, DEV_LAST)]
        ticket = gate.require(FAMILY, dates, "development", True)
        snaps, bands, _ = v3_inputs.read_inputs(layout, gate, FAMILY, True)
        cands, self.strength = _ladder_vectors(snaps, bands)          # outcome-free, before the join
        mg1 = v3_arms.load_arm(HERE / "v3_arm_mg1_like.py")
        cands["mg1_like"] = v3_arms.build(mg1, snaps, bands)
        cands["served"] = bands[["row_key", "band_index"]].assign(p=bands.p_served.to_numpy(float))
        labels, market = v3_outcomes.load_outcomes(layout, gate, ticket)
        if max(labels.date.astype(str)) > DEV_LAST:
            raise AssertionError("a label after 2026-09-29")
        self.snaps, self.bands = snaps, bands
        t = self.t = v3_core.Table(snaps, bands)
        lab = labels.set_index("row_key").reindex(t.snaps.row_key)
        self.winner = lab.winner.to_numpy(int)
        self.settled = pd.to_numeric(lab.settlement_high, errors="coerce").to_numpy(float)
        self.y = (bands.band_index.to_numpy(int) == np.repeat(self.winner, t.n)).astype(float)
        self.pm = market.set_index(["row_key", "band_index"]).p_market_yes.reindex(
            pd.MultiIndex.from_arrays([bands.row_key, bands.band_index])).to_numpy(float)
        self.vec = {k: t.candidate_vector(v, floor=True)[0] for k, v in cands.items()}
        self.se = {k: (v - self.y) ** 2 for k, v in self.vec.items()}
        ps = t.p_served
        self.se_s, self.se_m = (ps - self.y) ** 2, (self.pm - self.y) ** 2
        self.tail = (self.se_s > self.se_m) & (np.abs(ps - self.pm) >= TAIL_GAP)
        self.exc = np.where(self.tail, self.se_s - self.se_m, 0.0)
        snap = t.band_snap
        self.b_market = snaps.market.astype(str).to_numpy()[snap]
        self.b_date = snaps.date.astype(str).to_numpy()[snap]
        self.b_hour = t.local_hour[snap]
        dist = np.abs(bands.band_index.to_numpy(int) - np.repeat(self.winner, t.n))
        self.position = np.where(dist == 0, "winner", np.where(dist == 1, "adjacent", "far"))

    # ------------------------------------------------------------------ checks
    def ladder_check(self):
        out = {}
        t = self.t
        for name, fn in (("r1_lockin", "snapb_ladder-r1.npy"), ("r2", "snapb_ladder-r2.npy")):
            p = LADDER_OUT / fn
            if not p.exists():
                out[name] = {"status": "swarm file missing"}
                continue
            ref = np.load(p)
            mine = t.snapshot_brier(self.vec[name], self.y)
            out[name] = {"n": int(len(ref)), "same_length": bool(len(ref) == len(mine)),
                         "max_abs_diff": float(np.max(np.abs(ref - mine))) if len(ref) == len(mine) else None}
        return out

    # ------------------------------------------------------------------ helpers
    def gmask(self, g):
        return self.t.group_mask(g)[self.t.band_snap]

    def removed(self, name, sel):
        """Share of the tail excess on rows ``sel`` removed by vector ``name`` (cell-clustered W interval)."""
        t = self.t
        improve = (self.se_s - self.se[name])[sel]
        excess = (self.se_s - self.se_m)[sel]
        if not sel.any():
            return None
        cells = pd.DataFrame({"date": self.b_date[sel], "market": self.b_market[sel], "i": improve,
                              "e": excess}).groupby(["date", "market"])[["i", "e"]].sum().reset_index()
        idx = np.array([t.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
        iv = t.interval(idx, cells.i.to_numpy(), cells.e.to_numpy())
        return {"estimate": iv["estimate"], "ci95": iv["ci95"], "tail_rows": int(sel.sum())}

    # ------------------------------------------------------------------ 1. re-split
    def resplit(self):
        tot = self.exc.sum()
        f = pd.DataFrame({"block": self.snaps.block.astype(str).to_numpy()[self.t.band_snap],
                          "market": self.b_market, "position": self.position, "tail": self.tail,
                          "exc": self.exc})
        out = {"total_tail_rows": int(self.tail.sum()), "band_rows": int(len(f)),
               "tail_row_share": float(self.tail.mean()),
               "tail_share_of_positive_excess": float(self.exc.sum() / np.clip(self.se_s - self.se_m, 0, None).sum()),
               "all_rows_pre_191": True}
        for keys in (["position"], ["block", "position"], ["block", "market"], ["block", "market", "position"]):
            g = f.groupby(keys)
            tab = pd.DataFrame({"rows": g.size(), "tail_rows": g["tail"].sum(), "share": g.exc.sum() / tot})
            tab["rate"] = tab.tail_rows / tab.rows
            out[" x ".join(keys)] = {" | ".join(map(str, k if isinstance(k, tuple) else (k,))): {
                "rows": int(v.rows), "tail_rows": int(v.tail_rows), "rate": float(v.rate), "share": float(v.share)}
                for k, v in tab.sort_values("share", ascending=False).iterrows()}
        return out

    def evening(self):
        """How much of the 17-23 tail the emulated post-#191 lock-in (ladder r1) removes."""
        ev = self.tail & self.gmask("17-23")
        res = {"r1_lockin_all": self.removed("r1_lockin", ev), "r2_all": self.removed("r2", ev),
               "lockin_active_share_of_17_23_tail_rows": float(
                   (self.strength[self.t.band_snap][ev] > 0).mean()),
               "by_market": {}, "by_position": {}}
        for m in sorted(set(self.b_market)):
            res["by_market"][m] = self.removed("r1_lockin", ev & (self.b_market == m))
        for p in ("winner", "adjacent", "far"):
            res["by_position"][p] = self.removed("r1_lockin", ev & (self.position == p))
        for h in range(17, 24):
            res.setdefault("by_hour", {})[str(h)] = self.removed("r1_lockin", ev & (self.b_hour == h))
        return res

    # ------------------------------------------------------------------ 2. attribution of the 00-16 tail
    def attribution(self):
        names = ("served", "mg1_like", "c1", "r1_lockin", "r2")
        out = {"blocks": {}, "markets_00_16": {}}
        for g in ("00-05", "06-09", "10-12", "13-16", "00-16"):
            sel = self.tail & self.gmask(g)
            out["blocks"][g] = {n: self.removed(n, sel) for n in names}
            out["blocks"][g]["tail_share_of_all_tail_excess"] = float(self.exc[sel].sum() / self.exc.sum())
        sel16 = self.tail & self.gmask("00-16")
        for m in sorted(set(self.b_market)):
            s = sel16 & (self.b_market == m)
            out["markets_00_16"][m] = {n: (self.removed(n, s) or {}).get("estimate") for n in names}
            out["markets_00_16"][m]["share_of_00_16_tail_excess"] = float(self.exc[s].sum() / self.exc[sel16].sum())
        # decomposition (point): floor-only, then NBM (mg1_like - floor), lock-in (r2 - c1), residual (1 - r2)
        dec = {}
        for g in ("00-05", "06-09", "10-12", "13-16", "00-16"):
            b = out["blocks"][g]
            fl, mg, c1, r2 = (b[n]["estimate"] for n in ("served", "mg1_like", "c1", "r2"))
            dec[g] = {"floor_mask_only": fl, "nbm_read_mg1_like_beyond_floor": mg - fl,
                      "c1_form_minus_mg1_like": c1 - mg,
                      "lockin_on_top_of_c1": r2 - c1, "residual_after_r2": 1.0 - r2}
        out["decomposition_point"] = dec
        return out

    # ------------------------------------------------------------------ residual tail after r2
    def residual(self):
        p2 = self.vec["r2"]
        se2 = self.se["r2"]
        tail2 = (se2 > self.se_m) & (np.abs(p2 - self.pm) >= TAIL_GAP)
        pos2 = np.clip(se2 - self.se_m, 0, None)
        exc2 = np.where(tail2, se2 - self.se_m, 0.0)
        f = pd.DataFrame({"block": self.snaps.block.astype(str).to_numpy()[self.t.band_snap],
                          "market": self.b_market, "hour": self.b_hour, "position": self.position,
                          "tail": tail2, "exc": exc2,
                          "dir": np.where(p2 > self.pm, "r2_above_market", "r2_below_market")})
        tot = exc2.sum()
        out = {"definition": "band rows with r2 SE > market SE and |p_r2 - p_market| >= 0.30",
               "tail_rows": int(tail2.sum()), "tail_row_share": float(tail2.mean()),
               "tail_share_of_r2_positive_excess": float(exc2.sum() / pos2.sum()),
               "r2_tail_excess_over_served_tail_excess": float(exc2.sum() / self.exc.sum())}
        for keys in (["block"], ["market"], ["hour"], ["position"], ["dir", "position"], ["block", "market"]):
            g = f.groupby(keys)
            tab = pd.DataFrame({"rows": g.size(), "tail_rows": g["tail"].sum(), "share": g.exc.sum() / tot})
            tab["rate"] = tab.tail_rows / tab.rows
            out[" x ".join(keys)] = {" | ".join(map(str, k if isinstance(k, tuple) else (k,))): {
                "rows": int(v.rows), "tail_rows": int(v.tail_rows), "rate": float(v.rate), "share": float(v.share)}
                for k, v in tab.sort_values("share", ascending=False).head(40).iterrows()}
        out["correlates"] = self.correlates(tail2, exc2)
        return out

    def correlates(self, tail2, exc2):
        """Descriptive: do non-NBM captured columns point where the market sits relative to r2 (00-16)?"""
        t, s = self.t, self.snaps
        kind = self.bands.kind.to_numpy()
        low, high = self.bands.low.to_numpy(float), self.bands.high.to_numpy(float)
        mid = np.where(kind == "lte", high, np.where(kind == "gte", low, (low + high) / 2.0))
        cen = lambda p: np.add.reduceat(p * mid, t.offsets) / np.add.reduceat(p, t.offsets)
        c_r2, c_mk = cen(self.vec["r2"]), cen(self.pm)
        gap = c_mk - c_r2                                   # where the market centre sits relative to r2
        snap_tail = np.add.reduceat(tail2.astype(float), t.offsets) > 0
        snap_exc = np.add.reduceat(exc2, t.offsets)
        v2 = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
        floor = pd.to_numeric(s.floor, errors="coerce").to_numpy(float)
        cols = {c: pd.to_numeric(s[c], errors="coerce").to_numpy(float) for c in NON_NBM_COLUMNS}
        feats = {
            "hrrr_minus_r2_centre": cols["hrrr_high"] - c_r2,
            "nws_grid_minus_r2_centre": cols["nws_grid_high_raw"] - c_r2,
            "forecast_high_minus_r2_centre": cols["forecast_high"] - c_r2,
            "hrrr_minus_v2_mean": cols["hrrr_high"] - v2,
            "nws_grid_minus_v2_mean": cols["nws_grid_high_raw"] - v2,
            "forecast_high_minus_v2_mean": cols["forecast_high"] - v2,
            "r2_centre_minus_floor": c_r2 - floor,
            "v2_age_hours": pd.to_numeric(s.v2_age_hours, errors="coerce").to_numpy(float),
        }
        out = {}
        for g in ("00-05", "06-09", "10-12", "13-16", "00-16"):
            m = t.group_mask(g)
            res = {"snapshots": int(m.sum()), "residual_tail_snapshot_share": float(snap_tail[m].mean()),
                   "mean_abs_market_minus_r2_centre": float(np.nanmean(np.abs(gap[m]))), "features": {}}
            for k, x in feats.items():
                ok = m & ~np.isnan(x) & ~np.isnan(gap)
                if ok.sum() < 100:
                    continue
                xr = pd.Series(x[ok]).rank().to_numpy()
                gr = pd.Series(gap[ok]).rank().to_numpy()
                er = pd.Series(snap_exc[ok]).rank().to_numpy()
                ax = pd.Series(np.abs(x[ok])).rank().to_numpy()
                tl = snap_tail[ok]
                # mechanical baseline: the same feature shuffled within (market, block) keeps the -r2 centre
                # term shared with the market gap but destroys the column's own information
                rng = np.random.default_rng(20261020)
                xo = x[ok]
                grp = pd.Series(np.arange(ok.sum())).groupby(
                    [s.market.astype(str).to_numpy()[ok], s.block.astype(str).to_numpy()[ok]])
                perm = np.empty(ok.sum(), int)
                for _, ix in grp.indices.items():
                    perm[ix] = rng.permutation(ix)
                if k.endswith("_minus_r2_centre"):          # x = column - r2 centre: shuffle the column only
                    base_resid = (xo + c_r2[ok])[perm] - c_r2[ok]
                elif k == "r2_centre_minus_floor":          # x = r2 centre - floor: shuffle the floor only
                    base_resid = c_r2[ok] - (c_r2[ok] - xo)[perm]
                else:                                       # no r2 term: plain shuffle
                    base_resid = xo[perm]
                tg = (self.settled[ok] - c_r2[ok])
                tok = ~np.isnan(tg)
                res["features"][k] = {
                    "n": int(ok.sum()),
                    "spearman_with_market_minus_r2_centre": float(np.corrcoef(xr, gr)[0, 1]),
                    "sign_agreement_with_market_gap_when_abs_ge_1": float(np.mean(
                        np.sign(x[ok][np.abs(x[ok]) >= 1]) == np.sign(gap[ok][np.abs(x[ok]) >= 1])))
                    if (np.abs(x[ok]) >= 1).sum() >= 50 else None,
                    "spearman_shuffled_baseline_with_market_gap": float(np.corrcoef(
                        pd.Series(base_resid).rank().to_numpy(), gr)[0, 1]),
                    "spearman_with_settled_minus_r2_centre": float(np.corrcoef(
                        pd.Series(xo[tok]).rank().to_numpy(), pd.Series(tg[tok]).rank().to_numpy())[0, 1]),
                    "spearman_shuffled_baseline_with_settled_gap": float(np.corrcoef(
                        pd.Series(base_resid[tok]).rank().to_numpy(), pd.Series(tg[tok]).rank().to_numpy())[0, 1]),
                    "spearman_abs_with_residual_tail_excess": float(np.corrcoef(ax, er)[0, 1]),
                    "mean_abs_in_tail_snapshots": float(np.nanmean(np.abs(x[ok][tl]))) if tl.any() else None,
                    "mean_abs_in_other_snapshots": float(np.nanmean(np.abs(x[ok][~tl]))) if (~tl).any() else None}
            out[g] = res
        return out


def run(layout, gate=None):
    gate = gate or v3_gate.default_gate()
    tl = Tail(layout, gate)
    return {"purpose": "development", "dates": [DEV_FIRST, DEV_LAST], "family": FAMILY,
            "gate": gate.identity(), "scored_dates": [min(tl.b_date), max(tl.b_date)],
            "market_days": len(tl.t.keys), "ladder_check": tl.ladder_check(),
            "resplit": tl.resplit(), "evening_post191_emulation": tl.evening(),
            "attribution_00_16": tl.attribution(), "residual_after_r2": tl.residual()}
