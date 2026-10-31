r"""Pooled sub-bar candidates against the market: P0-only kill-at-edge read (lane L17, 2026-10-31; ledger row 94).

Rule ``docs/research/p5-screens-2026-10-31/rule_pooled_subbar_wgate.md`` (Amendment A3, sha256 ``RULE_SHA256``,
branch ``claude/p5-screens-20261031``). A3 rescopes the row to the P0 stage only (master ruling): the w-gate legs
are DROPPED from the decision and are not run, not even as context.

K = 3 blocks (POOL-0712, F2-1316, POOL-0006). Per block the candidate is the equal-weight log pool of the
block's testable members, on the intersection of their coverage (every member covered); elsewhere the market.
Master Clarification 1 (C4) and the 2026-10-31 ruling (option (a)): a member is testable only through a C4
receipt of the shared replay harness ``weather.calibration.pool0006_replay`` (run branch
``claude/p5-pool0006-replay-20261031``, module sha256 ``HARNESS_SHA256``): its replayed emit reproduced the
member's recorded headline to 1e-9, and the emit's sha256 matches the receipt. Only R-PD and R-N (POOL-0006) have
a harness. A block with fewer than 2 C4 survivors is UNTESTABLE (p = 1, it keeps its K slot): POOL-0712
(Reopen-if: per-member replay harnesses incl. an X17 per-snapshot vector) and F2-1316 (by construction, one
member) are UNTESTABLE as built.

P0 (a local copy of ``mr_sweep.p0_candidate``'s placebo and paired-Delta steps, taking the pooled band vector
directly instead of a tilt): Delta = rho(c - m, y - m) - mean_j rho(placebo_j - m, y - m) over the 20
calibration-matched disagreement placebos, with a date-clustered and a block-3 (moving blocks of 3 consecutive
scored dates; REV-2: circular, ceil(n/3) wrapping blocks, B 2,000, seed 20261024 - the row 93 counts)
bootstrap. Verdicts (A3): "KILL at edge size" when the wider of the two 95% upper bounds is below
rho 0.2236; otherwise "P0 survivor; w untested (underpowered)", which carries no claim and only queues a powered
w read. BH (q 0.10, K = 3) is reported as context only.

Controls before any candidate (any failure writes a VOID receipt and no candidate row): served R, MG-1 07-12
excess and the MG-1 w = 0 identity (``mr_gate.market_controls``); C3, the w = 0 identity per pooled candidate;
C5, the planted Gaussian SYN+ / SYN- per block (CONTROL, in memory only; Clarification 1: plant scale
SYN_SHRINK 0.75 frozen; pass iff the SYN+ lower bound > 0, the SYN+ wider upper >= 0.2236 and the SYN- upper
bound < 0, "lower" / "upper" being the smaller / larger of the date-clustered and block-3 bounds).

Master Clarification 3 (``CLARIFICATION3_PATH``, sha256 ``CLARIFICATION3_SHA256``, checked byte-identical before
any layout is read): C5 gates only the TESTABLE block(s) (POOL-0006). C5 is still computed on the UNTESTABLE
blocks as a diagnostic; any diagnostic failure sets the top-level receipt field ``c5_diagnostic_failure`` and
prints a banner, and master reviews it before the POOL-0006 verdict is labelled. A diagnostic failure never VOIDs
by itself. The receipt carries the C4 run-env disclosure (``C4_RUN_ENV_DISCLOSURE``).

No network I/O. B-bound files are imported read-only and sha-checked against the A3 pins at start and before the
receipt; the receipt records the git tree sha and those file shas. Writes once under ``--out``, which must lie
below ``C:/t/l17/pool/`` and must not exist.

    python -m weather.calibration.pooled_subbar_wgate --layout C:/swarm/v3layout --out C:/t/l17/pool/run1 \
        --c4-receipt R-PD=C:/t/l17/pool/c4/rpd/c4_R-PD.json --c4-receipt R-N=C:/t/l17/pool/c4/rn/c4_R-N.json
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
CLARIFICATION3_PATH = "docs/research/p5-screens-2026-10-31/clarification3_pooled_subbar_wgate.md"
CLARIFICATION3_SHA256 = "8ccc6bfed214df241a892f5c28562619ab2d2b72962c6e504e48e384e7cd398d"
C4_RUN_ENV_DISCLOSURE = (
    "Clarification 3 (ii): the C4 replays run in the members' recorded run env "
    "68920c47defcd5e23af16bba7ec1b957baee6a64, as Clarification 1 requires. It differs from the pool tree only in "
    "r0_ols_floor_challenger (a default-preserving metar_only parameter) and pooled_residual_model; the scorecard "
    "code (f69071ac) is identical.")
OUT_ROOT = Path("C:/t/l17/pool")
LAST_ALLOWED = ls.LAST_ALLOWED  # 2026-09-29
EDGE_RHO = math.sqrt(0.05)  # 0.2236: rho for a 5% Brier gain against the market
SYN_SEED = 20261031
SYN_SHRINK = 0.75  # Clarification 1 freeze addendum (toy calibration, s = 0.75)
BLOCK_LEN = 3
REV2_B, REV2_SEED = 2000, 20261024  # C3 REV-2 block-3 (same counts as row 93)
MIN_C4_SURVIVORS = 2  # Clarification 1: a block with fewer is UNTESTABLE
K = 3
EPS = 1e-4
VERDICT_KILL = "KILL at edge size"
VERDICT_SURVIVOR = "P0 survivor; w untested (underpowered)"
VERDICT_UNTESTABLE = "UNTESTABLE"
# block id -> local hour range (rule section 2)
BLOCKS = {"POOL-0712": (7, 12), "F2-1316": (13, 16), "POOL-0006": (0, 6)}
# Members (rule section 2, fixed). Testable only through a C4 receipt of the shared replay harness; the rest are
# UNTESTABLE with the recorded reason (Clarification 1; master ruling 2026-10-31, option (a)).
NO_HARNESS_0712 = ("no per-member replay harness (Clarification 1 C4); Reopen-if: per-member replay harnesses "
                   "incl. an X17 per-snapshot vector")
MEMBERS = (
    ("R-Q A", "POOL-0712", NO_HARNESS_0712),
    ("R-I", "POOL-0712", NO_HARNESS_0712),
    ("X17", "POOL-0712", NO_HARNESS_0712),
    ("A2", "POOL-0712", NO_HARNESS_0712),
    ("ASOS", "POOL-0712", NO_HARNESS_0712),
    ("F2", "F2-1316", "F2-1316 is UNTESTABLE by construction (one member, never 2 C4 survivors)"),
    ("R-PD", "POOL-0006", None),
    ("R-N", "POOL-0006", None),
)
# The shared replay harness (claude/p5-pool0006-replay-20261031 @ 95df98c966e205a3f94deb7e0c9e592898da6ebe) and
# each harnessed member's recorded gate 2 receipt (rule section 2, last column).
HARNESS_SCHEMA = "pool0006_replay/1"
HARNESS_SHA256 = "6d6f4f416b85f70a55e6c19ad1256fb94424573d106dba2df1e43c7b8b182f34"
HARNESS_RUN_ENV = "68920c47defcd5e23af16bba7ec1b957baee6a64"
C4_TOL = 1e-9
C4_RECORDED = {
    "R-PD": ("86268ec6a71267e536a280324ef4fd7e273356fea550ffa0bc9907a70aa20914", -0.023170310481208888),
    "R-N": ("d299bbf591150c8c74de6c83e372c73c14076fff6ebf82e5bbb95a39b382831c", -0.010530471121291537),
}
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


def member_status(spec, receipt=None):
    """(testable, reason, emit path or None, emit sha256 or None) for one member, from its C4 receipt.

    A member without a harness keeps its recorded UNTESTABLE reason. A harnessed member needs a receipt of the
    pinned harness at the pinned run env, for this member and its recorded gate 2 receipt, with C4 passed (every
    abs diff <= 1e-9 and the recorded estimate equal to the pin), and an emit whose sha256 matches the receipt.
    A missing receipt or a failed C4 drops the member (Clarification 1); a forged or inconsistent one refuses."""
    name, _, fixed_reason = spec
    if fixed_reason is not None:
        return False, fixed_reason, None, None
    if receipt is None:
        return False, "no C4 receipt (member not replayed)", None, None
    rec = json.loads(Path(receipt).read_text(encoding="utf-8"))
    rec_sha, rec_est = C4_RECORDED[name]
    if rec.get("schema") != HARNESS_SCHEMA or rec.get("member") != name:
        raise PoolError(f"{name}: {receipt} is not a {HARNESS_SCHEMA} receipt for this member")
    if rec.get("module_sha256") != HARNESS_SHA256 or rec.get("run_env_commit") != HARNESS_RUN_ENV:
        raise PoolError(f"{name}: C4 receipt is not from the pinned harness {HARNESS_SHA256} at {HARNESS_RUN_ENV}")
    if rec.get("recorded_gate2_sha256") != rec_sha:
        raise PoolError(f"{name}: C4 receipt replays {rec.get('recorded_gate2_sha256')}, not the recorded {rec_sha}")
    c4 = rec.get("c4") or {}
    if (c4.get("recorded") or {}).get("estimate") != rec_est:
        raise PoolError(f"{name}: C4 receipt's recorded headline is not {rec_est}")
    diffs = list((c4.get("abs_diff") or {}).values())
    passed = bool(c4.get("pass")) and len(diffs) == 3 and all(d is not None and d <= C4_TOL for d in diffs)
    if not passed:
        return False, "C4 FAIL (replayed headline differs from the recorded one beyond 1e-9)", None, None
    emit = rec.get("emit") or {}
    path, sha = emit.get("path"), emit.get("sha256")
    if not path or not Path(path).is_file():
        return False, f"C4 passed but the emit is missing: {path}", None, None
    got = _sha(path)
    if got != sha:
        raise PoolError(f"{name}: emit {path} sha256 {got} is not the C4 receipt's {sha}")
    return True, "C4 PASS", str(path), sha


def block_testable(status, members=MEMBERS, minimum=MIN_C4_SURVIVORS):
    """{block: (testable, n C4 survivors)}: a block needs at least ``minimum`` C4 survivors."""
    out = {}
    for block in BLOCKS:
        n = sum(1 for m in members if m[1] == block and status[m[0]][0])
        out[block] = (n >= minimum, n)
    return out


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

def block_counts(n_dates, b=REV2_B, seed=REV2_SEED, length=BLOCK_LEN):
    """C3 REV-2 circular block bootstrap date counts (``c3_kill_tier.block_counts`` verbatim, b1d8e65f): ceil(n/L)
    blocks of L consecutive dates wrapping modulo n, truncated to n; B 2,000, seed 20261024."""
    k = -(-n_dates // length)
    starts = np.random.default_rng(seed).integers(n_dates, size=(b, k))
    idx = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)


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
    """CONTROL only (rule (a) C5): Gaussian bands centred at mu_m + sign*SYN_SHRINK*(y_mid - mu_m) + eps (s 0.75,
    Clarification 1), width sigma_m,
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


def _bounds(r):
    """(lower, upper): the smaller lower and the larger upper of the date-clustered and block-3 95% bounds."""
    los = [v for v in (r["ci95"][0], r["ci95_block3"][0]) if v is not None]
    ups = [v for v in (r["ci95"][1], r["ci95_block3"][1]) if v is not None]
    return (min(los) if len(los) == 2 else None), (max(ups) if len(ups) == 2 else None)


def c5_checks(sp, sm):
    """Clarification 1 C5 pass rule for one block's SYN+ / SYN- records."""
    lo_p, up_p = _bounds(sp) if sp["testable"] else (None, None)
    _, up_m = _bounds(sm) if sm["testable"] else (None, None)
    return {"syn_plus_lower_above_0": bool(lo_p is not None and lo_p > 0),
            "syn_plus_wider_upper_at_least_edge": bool(up_p is not None and up_p >= EDGE_RHO),
            "syn_minus_upper_below_0": bool(up_m is not None and up_m < 0)}


def synthetic_controls(fit_t, score_t, geo, counts, bcounts, score_dates, donors, members_per_block):
    """Per block, pooled at the block's member count by replacing every member with the planted vector (a log
    pool of identical vectors is that vector). Clarification 1: PASS iff the SYN+ lower bound > 0, the SYN+ wider
    upper >= 0.2236 and the SYN- upper bound < 0 (lower / upper = smaller / larger of date and block-3)."""
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
        rec["checks"] = c5_checks(rec["SYN+"], rec["SYN-"])
        rec["verdict"] = "PASS" if all(rec["checks"].values()) else "FAIL"
        out[block] = rec
    return out


def c5_gate(c5, blocks_ok, stream=None):
    """Clarification 3 (i): (gating failures, diagnostic field). C5 gates only the testable blocks; a failure in an
    UNTESTABLE block is a diagnostic: it never VOIDs by itself, sets ``flag`` and prints a banner for master review
    before the verdict is labelled."""
    for block, rec in c5.items():
        rec["role"] = "gating" if blocks_ok[block][0] else "diagnostic"
    gating = [f"C5 {b}" for b, v in c5.items() if v["role"] == "gating" and v["verdict"] != "PASS"]
    diag = sorted(b for b, v in c5.items() if v["role"] == "diagnostic" and v["verdict"] != "PASS")
    banner = None
    if diag:
        banner = (f"*** C5 DIAGNOSTIC FAILURE in UNTESTABLE block(s) {', '.join(diag)}: not a VOID (Clarification 3); "
                  "MASTER REVIEW REQUIRED before the POOL-0006 verdict is labelled ***")
        print(banner, file=stream if stream is not None else sys.stdout, flush=True)
    field = {"flag": bool(diag), "blocks": diag, "banner": banner, "master_review_before_label": bool(diag),
             "gating_blocks": sorted(b for b, v in c5.items() if v["role"] == "gating")}
    return gating, field


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


def run(*, layout, out_dir, c4_receipts=None, allow_dirty=False, repo_root=None):
    import importlib

    root = Path(repo_root or Path(__file__).resolve().parents[3])
    c4_receipts = dict(c4_receipts or {})
    unknown = sorted(set(c4_receipts) - {m[0] for m in MEMBERS if m[2] is None})
    if unknown:
        raise PoolError(f"C4 receipts given for members without a harness: {unknown}")
    code = ls.require_clean(ls.code_state(), allow_dirty)
    rule = root / RULE_PATH
    if not rule.is_file() or _sha(rule) != RULE_SHA256:
        raise PoolError(f"rule {rule} is not the pinned A3 rule {RULE_SHA256}")
    clar3 = root / CLARIFICATION3_PATH
    if not clar3.is_file() or _sha(clar3) != CLARIFICATION3_SHA256:
        raise PoolError(f"{clar3} is not the pinned Clarification 3 {CLARIFICATION3_SHA256}")
    for name in RUN_IMPORTS:
        importlib.import_module(name)
    bb_start = bbound_check(root)
    from weather.calibration import gap_to_market_atlas as gta
    from weather.calibration import market_blend as mb

    out = check_out_dir(out_dir)
    status = {spec[0]: member_status(spec, c4_receipts.get(spec[0])) for spec in MEMBERS}
    blocks_ok = block_testable(status)
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    check_dates(fit_t.snaps.date.astype(str))
    out.mkdir(parents=True)
    base = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
            "clarification3": {"path": CLARIFICATION3_PATH, "sha256": CLARIFICATION3_SHA256,
                               "c4_run_env_disclosure": C4_RUN_ENV_DISCLOSURE},
            "git_tree": git_tree(root), "bbound_sha256": bb_start,
            "evidence_class": "development (dev window, P0-only kill-at-edge read; A3 rescope, w legs dropped)",
            "layout_manifest_sha256": lay.manifest_sha256,
            "module_sha256": {"pooled_subbar_wgate": _sha(__file__), "mr_sweep": _sha(sw.__file__),
                              "mr_gate": _sha(mg.__file__), "market_blend": _sha(mb.__file__),
                              "gap_to_market_atlas": _sha(gta.__file__)},
            "constants": {"edge_rho": EDGE_RHO, "draws": sw.DRAWS, "seed": sw.SEED, "block_len": BLOCK_LEN,
                          "block3": {"scheme": "REV-2 circular", "b": REV2_B, "seed": REV2_SEED},
                          "syn_shrink": SYN_SHRINK, "min_c4_survivors": MIN_C4_SURVIVORS, "c4_tol": C4_TOL,
                          "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q, "k": K, "eps": EPS,
                          "min_dates": sw.MIN_DATES, "min_snapshots": sw.MIN_SNAPS, "syn_seed": SYN_SEED},
            "harness": {"schema": HARNESS_SCHEMA, "module_sha256": HARNESS_SHA256, "run_env": HARNESS_RUN_ENV},
            "members": [{"member": m[0], "block": m[1], "testable": status[m[0]][0], "reason": status[m[0]][1],
                         "emit": status[m[0]][2], "emit_sha256": status[m[0]][3],
                         "c4_receipt": c4_receipts.get(m[0]),
                         "c4_receipt_sha256": _sha(c4_receipts[m[0]]) if m[0] in c4_receipts else None}
                        for m in MEMBERS],
            "blocks": {b: {"testable": ok, "c4_survivors": n, "k_slot": True} for b, (ok, n) in blocks_ok.items()},
            "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                           "n_scored_dates": len(scored)}}
    try:
        controls = mg.market_controls(fit_t, score_t)
    except mb.ControlFailed as exc:
        _write(out, "pooled_subbar_VOID.json", {**base, "verdict": "VOID", "reason": str(exc)})
        raise
    loaded = {b: [] for b in BLOCKS}
    for name, block, _ in MEMBERS:
        if not status[name][0] or not blocks_ok[block][0]:
            continue
        p_fit, cov_fit, meta = gta.load_candidate(status[name][2], mg.TRAINED_THROUGH, lay, folds, fit_t)
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
    c5_failed, c5_diag = c5_gate(controls["C5_synthetic"], blocks_ok)
    failed = [k for k, v in controls.items() if k != "C5_synthetic" and v.get("verdict") != "PASS"] + c5_failed
    if failed:
        _write(out, "pooled_subbar_VOID.json", {**base, "verdict": "VOID", "c5_diagnostic_failure": c5_diag,
                                                "controls": controls, "coverage": coverage})
        raise mb.ControlFailed(f"refused: controls failed {failed} (run VOID)")
    results, rows = {}, []
    for block in BLOCKS:
        if block not in pools:
            reason = (f"fewer than {MIN_C4_SURVIVORS} C4 survivors ({blocks_ok[block][1]})"
                      + ("; " + NO_HARNESS_0712.split("; ", 1)[1] if block == "POOL-0712" else "")
                      + ("; by construction (one member)" if block == "F2-1316" else ""))
            results[block] = {"candidate": block, "testable": False, "reason": reason,
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
    receipt = {**base, "c5_diagnostic_failure": c5_diag, "controls": controls, "coverage": coverage,
               "results": results,
               "lines": ([c5_diag["banner"]] if c5_diag["flag"] else []) + [line_for(b, results[b]) for b in BLOCKS],
               "rows_sha256": _sha(out / "pooled_subbar_rows.jsonl")}
    _write(out, "pooled_subbar.json", receipt)
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.pooled_subbar_wgate",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--c4-receipt", action="append", default=[], metavar="MEMBER=PATH",
                    help="a pool0006_replay C4 receipt (repeat per member)")
    a = ap.parse_args(argv)
    receipts = {}
    for item in a.c4_receipt:
        name, sep, path = item.partition("=")
        if not sep or name in receipts:
            raise PoolError(f"--c4-receipt wants MEMBER=PATH once per member: {item!r}")
        receipts[name] = path
    rec = run(layout=a.layout, out_dir=a.out, c4_receipts=receipts)
    print("\n".join(rec["lines"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
