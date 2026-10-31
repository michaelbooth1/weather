r"""Pooled sub-bar candidates against the market: P0-only kill-at-edge read (lane L17, 2026-10-31; ledger row 94).

Rule ``docs/research/p5-screens-2026-10-31/rule_pooled_subbar_wgate.md`` (Amendment A3, sha256 ``RULE_SHA256``,
branch ``claude/p5-screens-20261031``). A3 rescopes the row to the P0 stage only (master ruling): the w-gate legs
are DROPPED from the decision and are not run, not even as context.

K = 3 blocks (POOL-0712, F2-1316, POOL-0006). Per block the candidate is the equal-weight log pool of the
block's testable members, on the intersection of their coverage (every member covered); elsewhere the market.
A member is testable only with an A3-pinned dev band emit (sha256 checked) that is attested capture-time; any
other member is UNTESTABLE and drops from its pool, and a block with no testable member is UNTESTABLE (p = 1,
it keeps its K slot).

P0 (a local copy of ``mr_sweep.p0_candidate``'s placebo and paired-Delta steps, taking the pooled band vector
directly instead of a tilt): Delta = rho(c - m, y - m) - mean_j rho(placebo_j - m, y - m) over the 20
calibration-matched disagreement placebos, with a date-clustered and a block-3 (moving blocks of 3 consecutive
scored dates) bootstrap. Verdicts (A3): "KILL at edge size" when the wider of the two 95% upper bounds is below
rho 0.2236; otherwise "P0 survivor; w untested (underpowered)", which carries no claim and only queues a powered
w read. BH (q 0.10, K = 3) is reported as context only.

Controls before any candidate (any failure writes a VOID receipt and no candidate row): served R, MG-1 07-12
excess and the MG-1 w = 0 identity (``mr_gate.market_controls``); C3, the w = 0 identity per pooled candidate;
C5, the planted Gaussian SYN+ / SYN- per block (CONTROL, in memory only; SYN+ must be a P0 survivor with a
Delta lower bound > 0, SYN- must read Delta < 0).

No network I/O. B-bound files are imported read-only and sha-checked against the A3 pins at start and before the
receipt; the receipt records the git tree sha and those file shas. Writes once under ``--out``, which must lie
below ``C:/t/l17/pool/`` and must not exist.

    python -m weather.calibration.pooled_subbar_wgate --layout C:/swarm/v3layout --out C:/t/l17/pool/run1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "pooled_subbar_wgate/1"
GATE = "POOLED-SUBBAR-P0"
LEDGER_ROW = 94
RULE_PATH = "docs/research/p5-screens-2026-10-31/rule_pooled_subbar_wgate.md"
RULE_SHA256 = "bd081e402c2c91fe16b560fab530c7d66f1bade9bc98b767a139231ae464b74d"
OUT_ROOT = Path("C:/t/l17/pool")
LAST_ALLOWED = ls.LAST_ALLOWED  # 2026-09-29
EDGE_RHO = math.sqrt(0.05)  # 0.2236: rho for a 5% Brier gain against the market
SYN_SEED = 20261031
SYN_SHRINK = 0.5
BLOCK_LEN = 3
K = 3
EPS = 1e-4
VERDICT_KILL = "KILL at edge size"
VERDICT_SURVIVOR = "P0 survivor; w untested (underpowered)"
VERDICT_UNTESTABLE = "UNTESTABLE"
# block id -> local hour range (rule section 2)
BLOCKS = {"POOL-0712": (7, 12), "F2-1316": (13, 16), "POOL-0006": (0, 6)}
# A3 member pins: (member, block, emit path, emit sha256, capture-time attested). Only a member with a pinned emit
# whose capture-time emission is attested in A3 is testable; the rest are UNTESTABLE (rule section 2).
MEMBERS = (
    ("R-Q A", "POOL-0712", r"C:\t\l15\rq\emit0712\dev_P3d_N_fix_Q.jsonl",
     "98a31cb757e44d332ca70a680d40200ebf66b4899d408002330ee4a98728f038", False),
    ("R-I", "POOL-0712", None, None, False),
    ("X17", "POOL-0712", None, None, False),
    ("A2", "POOL-0712", None, None, False),
    ("ASOS", "POOL-0712", None, None, False),
    ("F2", "F2-1316", None, None, False),
    ("R-PD", "POOL-0006", None, None, False),
    ("R-N", "POOL-0006", None, None, False),
)
# A3 B-bound pins: the run imports these read-only (master 035f5bb19 versions) and refuses on any mismatch.
BBOUND_NAMES = frozenset({
    "mg2_composite.py", "mg2_p3d_n.py", "r0_ols_floor_devfit.py", "l6_stack.py", "mg1.py", "upstream_obs_screen.py",
    "r0_ols_floor_challenger.py", "observed_running_max.py", "mg_serve_core.py", "dev_scorecard.py",
    "dev_scorecard_data.py", "loss_atlas.py", "mg2_inputs.py", "mg2_input_allowlist.py",
    "guidance_extract_parser.py", "b_scorer.py", "pooled_residual_model.py"})
BBOUND_PINS = {
    "src/weather/calibration/pooled_residual_model.py":
        "52c497a95a69c3fbf78dbfe030b3190d93e940f180b81867a241552b3932a170",
    "src/weather/reporting/scorecards/dev_scorecard.py":
        "6447876a0956eac4f67132bc69dba48c26a672f7554ec46e8bfbe94ffe801b56",
    "src/weather/reporting/scorecards/dev_scorecard_data.py":
        "90627f7a9cc365c10115593b2a012aa2e63252db057606c3e649ac3e3e2f1220",
    "src/weather/reporting/scorecards/loss_atlas.py":
        "d18d173e63971ebac12bcc4873286ac09db3cabc89afbf30a51c0e39313a2320",
}
RUN_IMPORTS = ("weather.calibration.market_blend", "weather.calibration.gap_to_market_atlas",
               "weather.reporting.scorecards.dev_scorecard", "weather.reporting.scorecards.dev_scorecard_data",
               "weather.reporting.scorecards.loss_atlas")


class PoolError(mg.GateError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- guards

def check_out_dir(out_dir, root=OUT_ROOT):
    """``out_dir`` must sit strictly below ``root`` and must not exist yet (write once)."""
    out = Path(out_dir).resolve()
    base = Path(root).resolve()
    if base not in out.parents:
        raise PoolError(f"refusing to write outside {base}: {out}")
    if out.exists():
        raise PoolError(f"refusing to overwrite an existing output directory {out}")
    return out


def check_dates(dates):
    """Refuse any date after 2026-09-29 (the planted control reads dev outcomes only up to then)."""
    last = LAST_ALLOWED.isoformat()
    bad = sorted({str(d) for d in dates if str(d) > last})
    if bad:
        raise PoolError(f"refusing dates after {last}: {bad[:3]}")


def bbound_check(repo_root, pins=BBOUND_PINS, modules=None):
    """Every loaded B-bound file under ``repo_root`` must be pinned, and match its pin; returns {path: sha}."""
    root = Path(repo_root).resolve()
    seen = {}
    for mod in list((modules if modules is not None else sys.modules).values()):
        f = getattr(mod, "__file__", None)
        if not f or Path(f).name not in BBOUND_NAMES:
            continue
        p = Path(f).resolve()
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            raise PoolError(f"B-bound file {p} is loaded from outside the run tree {root}") from None
        seen[rel] = _sha(p)
    unpinned = sorted(set(seen) - set(pins))
    if unpinned:
        raise PoolError(f"B-bound files loaded without an A3 pin: {unpinned}")
    bad = {k: v for k, v in seen.items() if v != pins[k]}
    if bad:
        raise PoolError(f"B-bound files differ from their A3 pins: {bad}")
    return dict(sorted(seen.items()))


def git_tree(repo_root):
    proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True,
                          timeout=60, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def member_status(spec):
    """(testable, reason) for one member pin, before any file is read beyond its sha."""
    name, _, path, sha, capture_time = spec
    if path is None or sha is None:
        return False, "no A3-pinned dev band emit"
    if not capture_time:
        return False, "pinned emit is not attested capture-time (S1 re-emission required)"
    if not Path(path).is_file():
        return False, f"pinned emit missing: {path}"
    got = _sha(path)
    if got != sha:
        raise PoolError(f"{name}: {path} sha256 {got} is not the A3 pin {sha}")
    return True, "pinned"


# ----------------------------------------------------------------------------- the pooled candidate

def log_pool(table, vectors, covers):
    """Equal-weight log pool of the member band vectors on the snapshots every member covers; the market
    elsewhere. Members are clipped to [EPS, 1]; impossible bands get 0; each snapshot renormalised to sum(m)."""
    if not vectors:
        raise PoolError("log pool needs at least one member")
    covered = np.logical_and.reduce([np.asarray(c, bool) for c in covers])
    logs = np.mean([np.log(np.clip(np.asarray(v, float), EPS, 1.0)) for v in vectors], axis=0)
    g = np.where(table.impossible, 0.0, np.exp(logs))
    s_m = np.bincount(table.band_snap, weights=table.p_market, minlength=len(table.snaps))
    s_g = np.bincount(table.band_snap, weights=g, minlength=len(table.snaps))
    scale = np.divide(s_m, s_g, out=np.zeros_like(s_m), where=s_g > 0)
    c = g * np.repeat(scale, table.n)
    cov_b = np.repeat(covered, table.n)
    return np.where(cov_b, c, table.p_market), covered


# ----------------------------------------------------------------------------- P0 on a band vector

def block_counts(n_dates, draws=sw.DRAWS, seed=sw.SEED, length=BLOCK_LEN):
    """Moving-block bootstrap date counts: ceil(n/L) blocks of L consecutive dates, truncated to n."""
    rng = np.random.default_rng(seed + 3)
    nb = -(-n_dates // length)
    starts = rng.integers(0, max(n_dates - length + 1, 1), size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(length)).reshape(draws, -1)[:, :n_dates]
    idx = np.minimum(idx, n_dates - 1)
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx])


def p0_vector(cid, c_fit, covered, fit_t, score_t, counts, bcounts, score_dates, donors):
    """``mr_sweep.p0_candidate`` from the placebo step on, for a given band vector ``c_fit`` and its snapshot
    coverage (both on ``fit_t``). Returns (result, rows)."""
    from weather.calibration import market_blend as mb

    cov_float = np.repeat(covered.astype(float), fit_t.n)
    placebos, donor_ok = [], np.ones(len(fit_t.snaps), bool)
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(fit_t, c_fit, seed, donors[seed])
        donor_ok &= np.bincount(fit_t.band_snap, weights=cov_float[donors[seed][0]],
                                minlength=len(fit_t.snaps)) == fit_t.n
        placebos.append(pl)
    pop_fit = covered & donor_ok
    pop = mb.restrict_snap(fit_t, score_t, pop_fit)
    band = pop[score_t.band_snap]
    m, e = score_t.p_market, score_t.y - score_t.p_market
    didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    c = mb.restrict(fit_t, score_t, c_fit)
    pls = [mb.restrict(fit_t, score_t, p) for p in placebos]
    nd = len(score_dates)
    sums_c = sw.date_sums((c - m)[band], e[band], didx[band], nd)
    sums_pl = [sw.date_sums((p - m)[band], e[band], didx[band], nd) for p in pls]
    n_dates, n_snaps = int((sums_c[0] > 0).sum()), int(pop.sum())
    res = {"candidate": cid, "coverage": {"fit_covered_snapshots": int(covered.sum()),
                                          "population_snapshots": n_snaps, "population_dates": n_dates}}
    if n_dates < sw.MIN_DATES or n_snaps < sw.MIN_SNAPS:
        res.update(testable=False, p0={"p_one_sided": 1.0, "delta": None, "ci95": [None, None]},
                   p0_block3={"ci95": [None, None]})
        return res, []
    res["testable"] = True
    res["p0"] = sw.paired_delta(sums_c, sums_pl, counts)
    res["p0_block3"] = sw.paired_delta(sums_c, sums_pl, bcounts)
    rows = [{"candidate": cid, "date": score_dates[i], "sums_c": sums_c[:, i].tolist(),
             "sums_pl": [s[:, i].tolist() for s in sums_pl]} for i in range(nd)]
    return res, rows


def wider_upper(res):
    ups = [u for u in (res["p0"]["ci95"][1], res["p0_block3"]["ci95"][1]) if u is not None]
    return max(ups) if ups else None


def decide(results):
    """A3 labels per block (BH over K = 3 reported as context only); mutates and returns ``results``."""
    ids = list(BLOCKS)
    adj, reject = sw.bh_adjust([results[b]["p0"]["p_one_sided"] for b in ids])
    for b, q, rj in zip(ids, adj, reject):
        r = results[b]
        r["bh_q_context"], r["bh_reject_context"] = float(q), bool(rj)
        if not r.get("testable"):
            r["verdict"] = VERDICT_UNTESTABLE
            continue
        up = wider_upper(r)
        r["wider_upper_95"] = up
        r["verdict"] = VERDICT_KILL if up is not None and up < EDGE_RHO else VERDICT_SURVIVOR
    return results


# ----------------------------------------------------------------------------- C5 planted control

def _band_edges(table):
    b = table.bands
    kind, lo, hi = b.kind.astype(str).to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float)
    left = np.where(kind == "lte", -np.inf, lo - 0.5)
    right = np.where(kind == "gte", np.inf, hi + 0.5)
    return left, right


def planted(table, geo, mask, sign, seed=SYN_SEED):
    """CONTROL only (rule (a) C5): Gaussian bands centred at mu_m + sign*0.5*(y_mid - mu_m) + eps, width sigma_m,
    eps ~ N(0, sd(y_mid - mu_m)) (seeded; the same eps for both signs). In memory; returns (vector, covered)."""
    from scipy.stats import norm

    ny = np.bincount(table.band_snap, weights=table.y, minlength=len(table.snaps))
    zy = np.bincount(table.band_snap, weights=table.y * geo["z"], minlength=len(table.snaps))
    with np.errstate(invalid="ignore", divide="ignore"):
        y_mid = np.where(ny > 0, zy / ny, np.nan)
    gap = y_mid - geo["mu"]
    ok = np.asarray(mask, bool) & np.isfinite(gap)
    sd = float(np.std(gap[ok])) if ok.any() else 1.0
    eps = np.random.default_rng(seed).normal(0.0, sd if sd > 0 else 1.0, len(gap))
    centre = geo["mu"] + sign * SYN_SHRINK * np.where(ok, gap, 0.0) + eps
    sig = np.sqrt(geo["var"])
    left, right = _band_edges(table)
    cb, sb = np.repeat(centre, table.n), np.repeat(sig, table.n)
    p = norm.cdf((right - cb) / sb) - norm.cdf((left - cb) / sb)
    vec, _ = log_pool(table, [p], [ok])
    return vec, ok


def synthetic_controls(fit_t, score_t, geo, counts, bcounts, score_dates, donors, members_per_block):
    """Per block, pooled at the block's member count by replacing every member with the planted vector (a log
    pool of identical vectors is that vector). SYN+ must be a P0 survivor with lower bound > 0; SYN- Delta < 0."""
    from weather.calibration import market_blend as mb

    out = {}
    for block, (lo, hi) in BLOCKS.items():
        mask = mb.hour_mask(fit_t, lo, hi)
        rec = {"label": "CONTROL", "block": block, "pooled_members": members_per_block[block]}
        for name, sign in (("SYN+", 1.0), ("SYN-", -1.0)):
            vec, ok = planted(fit_t, geo, mask, sign)
            vec, ok = log_pool(fit_t, [vec] * members_per_block[block], [ok] * members_per_block[block])
            res, _ = p0_vector(f"CONTROL {name} {block}", vec, ok, fit_t, score_t, counts, bcounts, score_dates,
                               donors)
            rec[name] = {"label": "CONTROL", "testable": res["testable"], "delta": res["p0"].get("delta"),
                         "ci95": res["p0"].get("ci95"), "ci95_block3": res["p0_block3"].get("ci95"),
                         "p_one_sided": res["p0"].get("p_one_sided"), "coverage": res["coverage"]}
        sp, sm = rec["SYN+"], rec["SYN-"]
        ups = [u for u in (sp["ci95"][1], sp["ci95_block3"][1]) if u is not None]
        plus_ok = bool(sp["testable"] and sp["ci95"][0] is not None and sp["ci95"][0] > 0
                       and ups and max(ups) >= EDGE_RHO)
        minus_ok = bool(sm["testable"] and sm["delta"] is not None and sm["delta"] < 0)
        rec["checks"] = {"syn_plus_p0_survivor_lower_above_0": plus_ok, "syn_minus_delta_below_0": minus_ok}
        rec["verdict"] = "PASS" if plus_ok and minus_ok else "FAIL"
        out[block] = rec
    return out


# ----------------------------------------------------------------------------- the run

def _write(out, name, payload):
    path = out / name
    if path.exists():
        raise PoolError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=mg._default), encoding="utf-8")
    return path


def line_for(block, r):
    if r["verdict"] == VERDICT_UNTESTABLE:
        return f"{VERDICT_UNTESTABLE}: {block} ({r.get('reason', 'coverage')}); context BH q {r['bh_q_context']:.3f}"
    p0, ci, cb = r["p0"], r["p0"]["ci95"], r["p0_block3"]["ci95"]
    return (f"{r['verdict']}: {block} Delta {p0['delta']:+.4f} date [{ci[0]:+.4f}, {ci[1]:+.4f}] block-3 "
            f"[{cb[0]:+.4f}, {cb[1]:+.4f}]; wider upper {r['wider_upper_95']:+.4f} vs edge {EDGE_RHO:.4f}; "
            f"context BH q {r['bh_q_context']:.3f}")


def run(*, layout, out_dir, allow_dirty=False, repo_root=None):
    import importlib

    root = Path(repo_root or Path(__file__).resolve().parents[3])
    code = ls.require_clean(ls.code_state(), allow_dirty)
    rule = root / RULE_PATH
    if not rule.is_file() or _sha(rule) != RULE_SHA256:
        raise PoolError(f"rule {rule} is not the pinned A3 rule {RULE_SHA256}")
    for name in RUN_IMPORTS:
        importlib.import_module(name)
    bb_start = bbound_check(root)
    from weather.calibration import gap_to_market_atlas as gta
    from weather.calibration import market_blend as mb

    out = check_out_dir(out_dir)
    status = {spec[0]: member_status(spec) for spec in MEMBERS}
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    check_dates(fit_t.snaps.date.astype(str))
    out.mkdir(parents=True)
    base = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
            "git_tree": git_tree(root), "bbound_sha256": bb_start,
            "evidence_class": "development (dev window, P0-only kill-at-edge read; A3 rescope, w legs dropped)",
            "layout_manifest_sha256": lay.manifest_sha256,
            "module_sha256": {"pooled_subbar_wgate": _sha(__file__), "mr_sweep": _sha(sw.__file__),
                              "mr_gate": _sha(mg.__file__), "market_blend": _sha(mb.__file__),
                              "gap_to_market_atlas": _sha(gta.__file__)},
            "constants": {"edge_rho": EDGE_RHO, "draws": sw.DRAWS, "seed": sw.SEED, "block_len": BLOCK_LEN,
                          "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q, "k": K, "eps": EPS,
                          "min_dates": sw.MIN_DATES, "min_snapshots": sw.MIN_SNAPS, "syn_seed": SYN_SEED},
            "members": [{"member": s[0], "block": s[1], "emit": s[2], "emit_sha256": s[3], "capture_time": s[4],
                         "testable": status[s[0]][0], "reason": status[s[0]][1]} for s in MEMBERS],
            "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                           "n_scored_dates": len(scored)}}
    try:
        controls = mg.market_controls(fit_t, score_t)
    except mb.ControlFailed as exc:
        _write(out, "pooled_subbar_VOID.json", {**base, "verdict": "VOID", "reason": str(exc)})
        raise
    loaded = {b: [] for b in BLOCKS}
    for name, block, path, _, _ in MEMBERS:
        if not status[name][0]:
            continue
        p_fit, cov_fit, meta = gta.load_candidate(str(path), mg.TRAINED_THROUGH, lay, folds, fit_t)
        lo, hi = BLOCKS[block]
        loaded[block].append((name, p_fit, cov_fit & mb.hour_mask(fit_t, lo, hi), meta.get("coverage")))
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    check_dates(score_dates)
    counts, bcounts = sw.boot_counts(len(score_dates)), block_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    pools, coverage = {}, {}
    for block, mem in loaded.items():
        coverage[block] = {"members": {n: int(c.sum()) for n, _, c, _ in mem}}
        if mem:
            vec, cov = log_pool(fit_t, [v for _, v, _, _ in mem], [c for _, _, c, _ in mem])
            pools[block] = (vec, cov)
            coverage[block]["intersection"] = int(cov.sum())
            controls[f"C3_w0_identity_{block}"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec))
    n_members = {b: max(1, sum(1 for s in MEMBERS if s[1] == b)) for b in BLOCKS}
    controls["C5_synthetic"] = synthetic_controls(fit_t, score_t, geo, counts, bcounts, score_dates, donors,
                                                  n_members)
    failed = [k for k, v in controls.items() if k != "C5_synthetic" and v.get("verdict") != "PASS"]
    failed += [f"C5 {b}" for b, v in controls["C5_synthetic"].items() if v["verdict"] != "PASS"]
    if failed:
        _write(out, "pooled_subbar_VOID.json", {**base, "verdict": "VOID", "controls": controls,
                                                "coverage": coverage})
        raise mb.ControlFailed(f"refused: controls failed {failed} (run VOID)")
    results, rows = {}, []
    for block in BLOCKS:
        if block not in pools:
            results[block] = {"candidate": block, "testable": False, "reason": "no testable member",
                              "p0": {"p_one_sided": 1.0, "delta": None, "ci95": [None, None]},
                              "p0_block3": {"ci95": [None, None]}}
            continue
        res, r = p0_vector(block, *pools[block], fit_t, score_t, counts, bcounts, score_dates, donors)
        results[block], rows = res, rows + r
    decide(results)
    bb_end = bbound_check(root)
    if bb_end != bb_start:
        raise PoolError("B-bound files changed during the run")
    (out / "pooled_subbar_rows.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n" for r in rows), encoding="utf-8")
    receipt = {**base, "controls": controls, "coverage": coverage, "results": results,
               "lines": [line_for(b, results[b]) for b in BLOCKS],
               "rows_sha256": _sha(out / "pooled_subbar_rows.jsonl")}
    _write(out, "pooled_subbar.json", receipt)
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.pooled_subbar_wgate",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rec = run(layout=a.layout, out_dir=a.out)
    print("\n".join(rec["lines"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
