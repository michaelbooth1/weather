"""Model-edge week-1 development screens: scoring (dates 2026-07-31..2026-09-29 only).

Run only through ``test_me_screens_dev.py`` (phase ``score``) under the workstation heavy wrapper, after
the kill-rule blocks are committed in docs/research/model-edge-screens-2026-10-19.md section 2.

Every label/market read goes through the HARNESS v3 gate (H1) with purpose ``development`` for every arm
family; the sealed single-shot pass (``v3_score.run``) is run first and its result sha256 recorded. The
screen statistics below are computed on the same v3_core Table (same floor, fallback, W matrix).

Universal kill rule (declared before scoring; block 00-16 for every candidate):
  killed if the point estimate (candidate - served Brier; for lever 8, blend - market) is >= 0, OR fewer
  than 7 of 11 markets share its sign, OR the input-removed twin captures >= 75% of the effect.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools.research.model_parity import (v3_arms, v3_controls, v3_core, v3_gate, v3_inputs, v3_outcomes,
                                         v3_power, v3_score)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DOC = "docs/research/model-edge-screens-2026-10-19.md"
DECLARED_MARKER = "KILL RULE DECLARED BEFORE SCORING"
DEV_FIRST, DEV_LAST = "2026-07-31", "2026-09-29"
PURPOSE = "development"
BLOCK = "00-16"
FOLD_SPLIT = "2026-08-23"            # lever 8 cross-fit: fold A < 08-23 <= fold B (the v2 strata boundary)
KILL_MIN_MARKETS = 7
KILL_TWIN_SHARE = 0.75
H3_DATES = (20, 45)
H3_EFFECT_FRACTION = 0.5
H3_BAR = 0.0133
TAIL_GAP = 0.30
SCREEN_FAMILY = "model_edge_dev_screens"

# arm file -> (lever, role)
ARMS = {
    "me_arm_l7_v2q.py": ("lever7", "candidate"),
    "me_arm_l13_bt.py": ("lever13/lever5-stage9", "candidate"),
    "v3_arm_mg1_like.py": ("context", "reference (MG-1-like, v2 c1 family; not a new candidate)"),
    "v3_arm_served.py": ("context", "identity"),
}
E2_ARMS = ("served_identity", "mg1_like_v2_read")


def _git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def check_declared(commit):
    """The declared blocks must be committed (an ancestor of HEAD) before scoring."""
    if _git("merge-base", "--is-ancestor", commit, "HEAD").returncode != 0:
        raise AssertionError(f"declared commit {commit} is not an ancestor of HEAD")
    text = _git("show", f"{commit}:{DOC}").stdout
    if DECLARED_MARKER not in text:
        raise AssertionError(f"{DOC} at {commit} lacks the declared-blocks section")
    return {"commit": commit, "doc_sha256_at_commit": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _dates():
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(DEV_FIRST, DEV_LAST)]


def sealed_pass(layout, out, gate):
    prereg = out / "screens_prereg.json"
    sha = v3_controls.write_prereg(prereg, list(ARMS) + ["market_identity"], purpose=PURPOSE,
                                   note="model-edge week-1 development screens; kill rule in " + DOC)
    path, digest, payload = v3_score.run(prereg, sha, layout, out / "sealed", gate=gate)
    return {"prereg_sha256": sha, "result": str(path), "result_sha256": digest,
            "sealed_ok": v3_score.verify_sealed(path), "HARNESS_V3_SHA256": payload["HARNESS_V3_SHA256"],
            "arm_code_sha256": payload["arm_code_sha256"], "gate": payload["gate"],
            "E1": v3_controls.summarise_run(payload), "leakage_suspects": payload["leakage_suspects"]}


class Screen:
    def __init__(self, layout, gate):
        dates = _dates()
        self.tickets = {}
        self.arms = {}
        for name in ARMS:
            arm = v3_arms.load_arm(HERE / name)
            self.arms[arm.NAME] = arm
            self.tickets[arm.FAMILY] = gate.require(arm.FAMILY, dates, PURPOSE, arm.READS_NBM_GUIDANCE)
        ticket = gate.require(SCREEN_FAMILY, dates, PURPOSE, True)
        self.snaps, self.bands, self.manifest = v3_inputs.read_inputs(layout, gate, SCREEN_FAMILY, True)
        # outcome-free first: every candidate vector and its input-removed twin before the join
        self.cands = {}
        for name, arm in self.arms.items():
            self.cands[name] = v3_arms.build(arm, self.snaps, self.bands)
            s2, b2 = v3_arms.input_removed(arm, self.snaps, self.bands)
            self.cands[name + "__input_removed"] = v3_arms.build(arm, s2, b2)
        labels, market = v3_outcomes.load_outcomes(layout, gate, ticket)
        if max(labels.date.astype(str)) > DEV_LAST or max(self.snaps.date.astype(str)) > DEV_LAST:
            raise AssertionError("a row after 2026-09-29")
        t = self.t = v3_core.Table(self.snaps, self.bands)
        lab = labels.set_index("row_key").reindex(t.snaps.row_key)
        winner = lab.winner.to_numpy(int)
        self.y = (self.bands.band_index.to_numpy(int) == np.repeat(winner, t.n)).astype(float)
        self.pm = market.set_index(["row_key", "band_index"]).p_market_yes.reindex(
            pd.MultiIndex.from_arrays([self.bands.row_key, self.bands.band_index])).to_numpy(float)
        v3_score.screen_planted_labels(self.snaps, self.bands, labels, self.y)
        self.vec, self.use = {}, {}
        for name, cand in self.cands.items():
            pc, use, _ = t.candidate_vector(cand, floor=True)
            self.vec[name], self.use[name] = pc, use
        self.b_served = t.snapshot_brier(t.p_served, self.y)
        self.b_market = t.snapshot_brier(self.pm, self.y)
        self.markets = sorted(self.snaps.market.astype(str).unique())
        self.fold_b = (self.snaps.date.astype(str) >= FOLD_SPLIT).to_numpy()

    # ------------------------------------------------------------------ generic effect tables
    def effect(self, snap_vals, base_vals, group, scope=None):
        t = self.t
        mask = t.group_mask(group) & (np.ones(len(t.snaps), bool) if scope is None else scope)
        idx, d = t.cells(snap_vals - base_vals, mask)
        iv = t.interval(idx, d, effect=v3_core.MDE_EFFECT)
        per_market = pd.Series(d, index=[t.keys[i][1] for i in idx]).groupby(level=0).mean()
        return iv, per_market, idx, d

    def kill(self, est, per_market, twin_est):
        sign = np.sign(est)
        same = int((np.sign(per_market) == sign).sum()) if sign != 0 else 0
        share = (twin_est / est) if est < 0 else None
        reasons = []
        if est >= 0:
            reasons.append("point estimate >= 0")
        if same < KILL_MIN_MARKETS:
            reasons.append(f"only {same}/{len(per_market)} markets share the sign")
        if share is not None and share >= KILL_TWIN_SHARE:
            reasons.append(f"input-removed twin captures {share:.3f} of the effect")
        return {"estimate": est, "markets_sharing_sign": same, "markets": int(len(per_market)),
                "twin_estimate": twin_est, "twin_share": share, "killed": bool(reasons), "reasons": reasons,
                "verdict": "KILLED" if reasons else "SURVIVES"}

    def components(self, idx, cells):
        return v3_controls._components(SimpleNamespace(t=self.t), idx, cells)

    def h3(self, idx, cells):
        comp = v3_power.components_from_entry(self.components(idx, cells))
        out = {"components": comp}
        for n in H3_DATES:
            out[str(n)] = v3_power.plan(comp["var_date"], comp["var_market"], comp["var_resid"], n,
                                        comp["dev_markets"], comp["dev_estimate"], H3_EFFECT_FRACTION, H3_BAR)
        return out

    # ------------------------------------------------------------------ E1 screens (levers 7, 13)
    def arm_screen(self, name):
        t, y = self.t, self.y
        b_arm = t.snapshot_brier(self.vec[name], y)
        b_twin = t.snapshot_brier(self.vec[name + "__input_removed"], y)
        groups = {}
        for g in v3_core.groups():
            if not t.group_mask(g).any():
                continue
            iv, pm, idx, d = self.effect(b_arm, self.b_served, g)
            tw, _, _, _ = self.effect(b_twin, self.b_served, g)
            mk, _, _, _ = self.effect(b_arm, self.b_market, g)
            groups[g] = {"arm_minus_served": iv, "twin_minus_served": tw, "arm_minus_market": mk,
                         "per_market_arm_minus_served": pm.to_dict(),
                         "coverage_share": float(self.use[name][t.group_mask(g)].mean())}
        iv, pm, idx, d = self.effect(b_arm, self.b_served, BLOCK)
        tw = groups[BLOCK]["twin_minus_served"]["estimate"]
        res = {"groups": groups, "kill": self.kill(iv["estimate"], pm, tw)}
        if not res["kill"]["killed"]:
            res["h3"] = self.h3(idx, d)
        return res

    def increment(self, a, b, group=BLOCK):
        ba = self.t.snapshot_brier(self.vec[a], self.y)
        bb = self.t.snapshot_brier(self.vec[b], self.y)
        iv, pm, _, _ = self.effect(ba, bb, group)
        return {"a": a, "b": b, "group": group, "a_minus_b": iv,
                "markets_negative": int((pm < 0).sum()), "per_market": pm.to_dict()}

    # ------------------------------------------------------------------ lever 8 (E2 blend)
    def e2(self, name):
        t, y, pm_ = self.t, self.y, self.pm
        p = self.vec.get(name, t.p_served)
        dates = sorted(self.snaps.date.astype(str).unique())
        da = [d for d in dates if d < FOLD_SPLIT]
        db = [d for d in dates if d >= FOLD_SPLIT]
        w_full = v3_score.fit_blend_weights(t, p, y, pm_, dates)
        w_a = v3_score.fit_blend_weights(t, p, y, pm_, da)
        w_b = v3_score.fit_blend_weights(t, p, y, pm_, db)
        twin = name + "__input_removed"
        # an arm with no inputs (served) has no input-removed twin; its declared twin is the market alone
        p_twin = self.vec.get(twin) if self.arms[name].INPUTS else None
        out = {"weights_in_sample_full": w_full, "weights_fit_fold_A_lt_0823": w_a,
               "weights_fit_fold_B_ge_0823": w_b, "groups": {}}
        for g in v3_core.groups():
            if g not in w_a or g not in w_b:
                continue
            # out-of-fold: fold A scored with weights fit on B, fold B with weights fit on A
            oof = np.where(self.fold_b, t.snapshot_brier(v3_score.blend(p, pm_, w_a[g]), y),
                           t.snapshot_brier(v3_score.blend(p, pm_, w_b[g]), y))
            ins = t.snapshot_brier(v3_score.blend(p, pm_, w_full[g]), y)
            if p_twin is not None:
                tw_oof = np.where(self.fold_b, t.snapshot_brier(v3_score.blend(p_twin, pm_, w_a[g]), y),
                                  t.snapshot_brier(v3_score.blend(p_twin, pm_, w_b[g]), y))
            else:
                tw_oof = self.b_market.copy()       # served: removing the model leaves the market
            iv, pmk, idx, d = self.effect(oof, self.b_market, g)
            ivi, _, _, _ = self.effect(ins, self.b_market, g)
            twv, _, _, _ = self.effect(tw_oof, self.b_market, g)
            r_idx, r_a = t.cells(oof, t.group_mask(g))
            _, r_m = t.cells(self.b_market, t.group_mask(g))
            out["groups"][g] = {"oof_blend_minus_market": iv, "in_sample_blend_minus_market": ivi,
                                "oof_twin_blend_minus_market": twv,
                                "oof_R_blend_over_market": t.interval(r_idx, r_a, r_m),
                                "per_market_oof": pmk.to_dict()}
            if g == BLOCK:
                out["kill"] = self.kill(iv["estimate"], pmk, twv["estimate"])
                if not out["kill"]["killed"]:
                    out["h3"] = self.h3(idx, d)
        return out

    # ------------------------------------------------------------------ lever 13 (tail)
    def tail(self):
        t, y = self.t, self.y
        ps, pm_ = t.p_served, self.pm
        se_s, se_m = (ps - y) ** 2, (pm_ - y) ** 2
        tail = (se_s > se_m) & (np.abs(ps - pm_) >= TAIL_GAP)
        pos = np.clip(se_s - se_m, 0, None)
        snap = t.band_snap
        s = t.snaps
        floor_b = np.repeat(pd.to_numeric(s.floor_bucket, errors="coerce").to_numpy(float), t.n)
        kind, low, high = self.bands.kind.to_numpy(), self.bands.low.to_numpy(float), self.bands.high.to_numpy(float)
        lo = np.where(kind == "lte", -np.inf, low)
        hi = np.where(kind == "gte", np.inf, high)
        floor_rel = np.where(np.isnan(floor_b), "no_floor",
                             np.where(hi < floor_b, "below_floor",
                                      np.where((lo <= floor_b) & (hi >= floor_b), "holds_floor_bucket",
                                               np.where(lo <= floor_b + 2, "just_above_floor_le2",
                                                        "above_floor_gt2"))))
        mg1_cov = np.repeat(self.use["mg1_like_v2_read"], t.n)
        frame = pd.DataFrame({
            "market": s.market.astype(str).to_numpy()[snap], "block": s.block.astype(str).to_numpy()[snap],
            "local_hour": t.local_hour[snap], "stratum": s.stratum.astype(str).to_numpy()[snap],
            "floor_relation": floor_rel, "winner_band": y == 1,
            "direction": np.where(ps > pm_, "served_above_market", "served_below_market"),
            "mg1_covered": mg1_cov, "tail": tail, "pos": pos, "exc_tail": np.where(tail, se_s - se_m, 0.0)})
        total_pos = pos.sum()
        res = {"definition": "band row with served SE > market SE and |p_served - p_market| >= 0.30 "
                             "(EF 1/1f lens, this table's rows)",
               "band_rows": int(len(frame)), "tail_rows": int(tail.sum()),
               "tail_row_share": float(tail.mean()),
               "tail_share_of_positive_excess": float(pos[tail].sum() / total_pos), "by": {}}
        for col in ("market", "block", "local_hour", "stratum", "floor_relation", "winner_band", "direction",
                    "mg1_covered"):
            g = frame.groupby(col)
            tab = pd.DataFrame({"rows": g.size(), "tail_rows": g["tail"].sum(),
                                "tail_excess": g.exc_tail.sum()})
            tab["tail_rate"] = tab.tail_rows / tab.rows
            tab["share_of_all_tail_excess"] = tab.tail_excess / frame.exc_tail.sum()
            res["by"][col] = {str(k): {kk: float(vv) for kk, vv in v.items()} for k, v in tab.iterrows()}
        cross = frame[frame["tail"]].groupby(["direction", "winner_band", "floor_relation"]).exc_tail.sum()
        res["by"]["direction_x_winner_x_floor"] = {" | ".join(map(str, k)): float(v / frame.exc_tail.sum())
                                                   for k, v in cross.sort_values(ascending=False).items()}
        # does any arm move the tail? share of tail excess removed, cell-clustered interval
        res["arms_tail_excess_removed"] = {}
        bands = self.bands.assign(excess=np.where(tail, se_s - se_m, 0.0))
        for name, p in self.vec.items():
            se_c = (p - y) ** 2
            improve = np.where(tail, se_s - se_c, 0.0)
            per = {}
            for g in ("00-16", "17-23", "all"):
                sel = tail & t.group_mask(g)[snap]
                cells = pd.DataFrame({"date": bands.date.astype(str).to_numpy()[sel],
                                      "market": bands.market.astype(str).to_numpy()[sel],
                                      "improve": improve[sel], "excess": (se_s - se_m)[sel]}).groupby(
                    ["date", "market"])[["improve", "excess"]].sum().reset_index()
                idx = np.array([t.key_index[(a, b)] for a, b in zip(cells.date, cells.market)])
                per[g] = {"tail_rows": int(sel.sum()),
                          "share_removed": t.interval(idx, cells.improve.to_numpy(), cells.excess.to_numpy())}
            res["arms_tail_excess_removed"][name] = per
        return res


def run(layout, out, declared_commit, gate=None):
    out = Path(out)
    gate = gate or v3_gate.default_gate()
    rec = {"declared": check_declared(declared_commit), "purpose": PURPOSE, "dates": [DEV_FIRST, DEV_LAST],
           "block": BLOCK, "kill_rule": {"point_ge_0": True, "min_markets_sharing_sign": KILL_MIN_MARKETS,
                                         "twin_share_kill": KILL_TWIN_SHARE},
           "h3": {"dates": H3_DATES, "effect_fraction": H3_EFFECT_FRACTION, "bar": H3_BAR},
           "HARNESS_V3_SHA256": v3_score.harness_v3_sha256()}
    rec["sealed"] = sealed_pass(layout, out, gate)
    sc = Screen(layout, gate)
    rec["scored_dates"] = sorted(sc.snaps.date.astype(str).unique())
    rec["market_days"] = len(sc.t.keys)
    rec["markets"] = sc.markets
    rec["arm_code_sha256"] = {n: a.CODE_SHA256 for n, a in sc.arms.items()}
    rec["E1"] = {n: sc.arm_screen(n) for n in sc.arms if n != "served_identity"}
    rec["increments"] = {"l7_v2_quantile_read_minus_mg1_like": sc.increment("l7_v2_quantile_read",
                                                                             "mg1_like_v2_read")}
    for g in ("06-09", "13-16", "17-23"):
        rec["increments"][f"l7_v2q_minus_mg1_like_{g}"] = sc.increment("l7_v2_quantile_read", "mg1_like_v2_read", g)
    rec["E2"] = {n: sc.e2(n) for n in E2_ARMS}
    rec["tail"] = sc.tail()
    rec["leakage_suspects"] = rec["sealed"]["leakage_suspects"]
    return rec
