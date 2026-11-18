"""Gap-to-market atlas: each existing candidate's R against the market, by pool x hour block x heat third.

Descriptive development evidence only (C dev scorecard window, scored dates 2026-08-15..2026-09-29 through
the dev scorecard's own date guard; nothing after 2026-09-29, no 88a or panel data). It is not
confirmation, edge or promotion evidence, fits no new model and creates no new candidate: it reads
vectors that already exist (MG-1 builtin, L3's arm A distributions, the L6 own-obs stack module, and
optionally L2's P3d vectors) through the scorecard's contract (rule-4 floor mask, renormalise, served
fallback). Each candidate is reported ONLY against the market; candidate-minus-candidate deltas are
deliberately not computed (a separate pre-declared pick compares the afternoon arms).

R = mean over (date, market) cells of the candidate's per-snapshot Brier / the same for the market
(``dev_scorecard.ratio_interval``). Intervals: date-clustered (``Table.w_date``, 2,000 draws, seed
20260921) for every cell; the crossed date x market interval too for multi-market pools. MDE80 is the
scorecard's ``mde80`` on the date-clustered bootstrap of R (R units).

Controls, always first, else exit 7 and nothing is written: served R 1.774 (all) and 1.526 (00-16)
(``loss_atlas.positive_control``); MG-1 07-12 excess over market 0.012 (3 dp); L6 own-stack 07-12
Brier - MG-1 = -0.0036243 (L3 dev4); arm A pooled 07-12 blended R equal to L3's dev4 value.

    python -m weather.calibration.gap_to_market_atlas --layout C:\\swarm\\v3layout \\
        --arm-a C:\\t\\l3\\dev_l8\\dev_l8_high_so_far_ols_floor.jsonl --dev4 C:\\t\\l3\\dev4\\dev_scores_v4.json \\
        [--p3d <jsonl|parquet|csv|module:path> --p3d-trained-through DATE] --out-dir C:\\t\\l10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from weather.reporting.scorecards import loss_atlas as la  # refuses import on the capture host

la.refuse_production_import()

import numpy as np  # noqa: E402

from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402

SCHEMA = "gap_to_market_atlas/1"
RANGE = ("2026-08-01", "2026-09-29")
PRIMARY = ("atlanta", "austin", "chicago", "dallas", "denver")
BLOCKS = (("06-09", 6, 9), ("10-12", 10, 12), ("07-12", 7, 12), ("12-16", 12, 16), ("13-16", 13, 16),
          ("00-16", 0, 16)) + tuple((f"h{h:02d}", h, h) for h in range(7, 17))
LATE = (("17-23", 17, 23),) + tuple((f"h{h:02d}", h, h) for h in range(17, 24))
HEAT = (("all", None), ("cool", 1), ("mid", 2), ("hot", 3))
COMPOSITE_SWITCH_HOUR = 13
MG1_EXCESS_0712 = 0.012
L6_MINUS_MG1_0712 = -0.003624288037781625
DEFAULT_L6_MODULE = Path(__file__).resolve().parents[3] / (
    "src/weather/reporting/scorecards/free_source_candidates/l6_own_candidate.py")


class ControlFailed(data.Refused):
    exit_code = 7


def _sha(path):
    return data.sha256_file(path)


def load_candidate(source, trained_through, layout, folds, table):
    """``module:<path>`` (walk-forward per fold), a ``.jsonl[.gz]`` distribution file, or a vectors table."""
    if source.startswith("module:"):
        spec = data.CandidateSpec("module", source[len("module:"):])
        frame, meta = data.module_predictions(spec, layout, folds)
        meta = dict(meta, kind="module", walk_forward="enforced_fit_per_fold", sha256=_sha(spec.path))
    else:
        kind = "distributions" if ".jsonl" in Path(source).name else "vectors"
        spec = data.CandidateSpec(kind, source, trained_through, False)
        builder = data.distribution_predictions if kind == "distributions" else data.vector_predictions
        frame, meta = builder(spec, layout, folds)
        meta = dict(meta, kind=kind, sha256=_sha(source))
    p, cov, reasons = vector_and_coverage(table, frame)
    return p, cov, dict(meta, source=source, coverage=reasons)


def vector_and_coverage(table, frame):
    """The scorecard's vector plus a per-snapshot mask of where the candidate (not served) is used.

    The mask mirrors ``Table.candidate_vector``'s reason codes (lane L3 ``covered_mask``) and is checked
    against its candidate count.
    """
    p, reasons = table.candidate_vector(frame)
    f = frame[frame.row_key.isin(table.snap_pos.index)]
    pos = table.snap_pos.reindex(f.row_key.to_numpy()).to_numpy().astype(int)
    flat = table.offsets[pos] + f.band_index.to_numpy(int)
    given = np.zeros(len(table.bands), bool)
    pc = np.zeros(len(table.bands))
    given[flat] = True
    pc[flat] = f.p.to_numpy(float)
    pc[table.impossible] = 0.0
    n_given = np.bincount(table.band_snap, weights=given, minlength=len(table.snaps))
    total = np.bincount(table.band_snap, weights=pc, minlength=len(table.snaps))
    cov = (n_given == table.n) & table.has_floor & (total > 0)
    if int(cov.sum()) != int(reasons.get("candidate", 0)):
        raise data.Refused(f"refused: coverage mask {int(cov.sum())} != scorecard candidate count {reasons}")
    return p, cov, reasons


def cell_stats(table, cand_b, market_b, mask, pooled):
    idx, c = table.cells(cand_b, mask)
    _, m = table.cells(market_b, mask)
    if not len(idx):
        return None
    wd = table.w_date[:, idx]
    num, den = wd @ c, wd @ m
    boot = np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)
    point = float(c.sum() / m.sum()) if m.sum() > 0 else math.nan
    fin = boot[np.isfinite(boot)]
    ci = np.quantile(fin, [.025, .975]).tolist() if len(fin) else [None, None]
    mde = sc.mde80(point, boot, effect=-0.05)
    n_dates = len({table.keys[i][0] for i in idx})
    out = {"R": point, "ci95_date": ci, "mde80_R": mde.get("mde80"), "n_market_days": int(len(idx)),
           "n_dates": n_dates, "n_markets": len({table.keys[i][1] for i in idx}), "n_snapshots": int(mask.sum()),
           "brier_market": float(m.mean()), "brier_candidate": float(c.mean()),
           "interpretable": bool(m.mean() >= sc.MARKET_BRIER_FLOOR),
           "powered_clusters": bool(n_dates >= sc.CLUSTER_FLOOR)}
    if pooled:
        out["ci95_crossed"] = sc.ratio_interval(table.w[:, idx], c, m)["ci95"]
    return out


def atlas(table, cands, market_b, terc_snap):
    pools = [("ALL", None), ("PRIMARY5", PRIMARY)] + [(mk, (mk,)) for mk in sorted(set(table.markets))]
    hour = table.local_hour
    out = {}
    for name, (p, cov) in cands.items():
        b = table.brier(p)
        rows = []
        for pool, members in pools:
            in_pool = np.ones(len(hour), bool) if members is None else np.isin(table.markets, members)
            for group, lo, hi in BLOCKS + LATE:
                for heat, k in HEAT:
                    mask = in_pool & (hour >= lo) & (hour <= hi)
                    if k is not None:
                        mask &= terc_snap == k
                    st = cell_stats(table, b, market_b, mask, members is None or len(members) > 1)
                    if st is None:
                        continue
                    st.update(pool=pool, group=group, heat=heat, late_flag=(lo >= 17),
                              coverage=float(cov[mask].mean()))
                    covm = mask & cov
                    if st["coverage"] < 0.999 and covm.any():
                        cs = cell_stats(table, b, market_b, covm, False)
                        st["covered_only"] = {kk: cs[kk] for kk in ("R", "ci95_date", "n_market_days")}
                    rows.append(st)
        out[name] = rows
    return out


def run(args):
    for path, label in ((args.layout, "layout"), (args.arm_a, "arm A"), (args.p3d, "P3d")):
        la.screen_input_path(path, label)
    start, end = data.check_range(*RANGE)
    layout = data.load_layout(args.layout, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(layout, scored)
    controls = {"served": la.positive_control(table)}                       # raises ControlFailed
    market_b = table.brier(table.p_market)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)

    p_mg1, cov_mg1, mg1_reasons = vector_and_coverage(table, la.mg1_frame(table))
    mg1_b = table.brier(p_mg1)
    excess = float(table.cells(mg1_b - market_b, w0712)[1].mean())
    controls["mg1"] = {"excess_over_market_07_12": excess, "expected": MG1_EXCESS_0712,
                       "verdict": "PASS" if round(excess, 3) == MG1_EXCESS_0712 else "FAIL"}

    p_l6, cov_l6, meta_l6 = load_candidate(f"module:{args.l6_module}", None, layout, folds, table)
    d = float(table.cells(table.brier(p_l6) - mg1_b, w0712)[1].mean())
    controls["l6_own_stack"] = {"brier_minus_mg1_07_12": d, "expected": L6_MINUS_MG1_0712,
                                "verdict": "PASS" if abs(d - L6_MINUS_MG1_0712) <= 1e-6 else "FAIL"}

    p_a, cov_a, meta_a = load_candidate(args.arm_a, "2025-12-31", layout, folds, table)
    idx, c = table.cells(table.brier(p_a), w0712)
    _, m = table.cells(market_b, w0712)
    r_a = float(c.sum() / m.sum())
    dev4 = json.loads(Path(args.dev4).read_text(encoding="utf-8")) if args.dev4 else None
    exp_a = None
    if dev4:
        exp_a = next(r["R_candidate"]["estimate"] for r in dev4["candidates"]["arm_a"]["rows"]
                     if r["reference"] == "served" and r["scope"] == "blended" and r["market"] == "ALL"
                     and r["group"] == "07-12")
    controls["arm_a_dev4"] = {"R_07_12_blended": r_a, "expected": exp_a,
                              "verdict": "PASS" if exp_a is not None and abs(r_a - exp_a) <= 1e-9 else "FAIL"}
    failed = [k for k, v in controls.items() if v["verdict"] != "PASS"]
    if failed:
        raise ControlFailed(f"refused: controls failed {failed}: {json.dumps(controls)}")

    pre = (table.local_hour < COMPOSITE_SWITCH_HOUR)[table.band_snap]
    p_comp = np.where(pre, p_l6, p_a)
    cov_comp = np.where(table.local_hour < COMPOSITE_SWITCH_HOUR, cov_l6, cov_a)
    cands = {"mg1": (p_mg1, cov_mg1), "arm_a": (p_a, cov_a), "composite": (p_comp, cov_comp)}
    meta = {"mg1": {"rule": "r-t5-inc-c1 (loss_atlas.mg1_frame)", "coverage": mg1_reasons},
            "arm_a": meta_a, "l6_own_stack": meta_l6,
            "composite": {"rule": f"local_hour < {COMPOSITE_SWITCH_HOUR}: MG-1 + L6 own-obs stack "
                                  f"(module, walk-forward per fold); >= {COMPOSITE_SWITCH_HOUR}: arm A"}}
    if args.p3d:
        p_p, cov_p, meta_p = load_candidate(args.p3d, args.p3d_trained_through, layout, folds, table)
        cands["p3d"] = (p_p, cov_p)
        meta["p3d"] = meta_p

    ctx = la.Context(layout, table, la.WINDOW)
    terc_cell = la.heat_terciles(ctx)                 # 1 cool, 2 mid, 3 hot (market 07-12 centre, in-market)
    terc_snap = terc_cell[table.cell]
    rows = atlas(table, cands, market_b, terc_snap)
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"schema": SCHEMA, "evidence_class": "development, descriptive (not a claim)",
            "code_sha256": code, "scorecard_code_sha256": sc.code_sha256(), "loss_atlas_code_sha256":
            la.code_sha256(), "layout_manifest_sha256": layout.manifest_sha256,
            "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                           "n_market_days": len(table.keys), "n_snapshots": int(len(table.snaps))},
            "constants": {"draws": sc.DRAWS, "seed": sc.SEED, "market_brier_floor": sc.MARKET_BRIER_FLOOR,
                          "cluster_floor": sc.CLUSTER_FLOOR, "heat": "within-market tercile of the market's "
                          "07-12 mean centre (ex ante; loss_atlas.heat_terciles)"},
            "controls": controls, "candidates": meta, "rows": rows,
            "discipline": "each candidate vs the market only; no candidate-minus-candidate deltas"}


# ----------------------------------------------------------------------------- report

RENDER_CANDS = ("mg1", "arm_a", "p3d", "composite")
LABEL = {"mg1": "MG-1", "arm_a": "Arm A", "p3d": "P3d", "composite": "Composite"}
MAIN = ("06-09", "10-12", "07-12", "12-16", "13-16", "00-16")
HOURS = tuple(f"h{h:02d}" for h in range(7, 24))


def f3(x):
    return "n/a" if x is None else f"{x:.3f}"


def cell(r, n=True):
    if r is None:
        return "-"
    lo, hi = r["ci95_date"]
    s = f"{f3(r['R'])} [{f3(lo)}, {f3(hi)}]"
    if r["R"] is not None and r["R"] <= 1:
        s = f"**{s}**"
    elif lo is not None and lo <= 1:
        s = f"*{s}*"
    if r.get("coverage", 1) < 0.95:
        s += f" c{100 * r['coverage']:.0f}%"
    if not r["interpretable"]:
        s += " (!)"
    return s


def render(payload):
    idx = {}
    cands = [c for c in RENDER_CANDS if c in payload["rows"]]
    for c in cands:
        for r in payload["rows"][c]:
            idx[(c, r["pool"], r["group"], r["heat"])] = r
    g = lambda c, p, b, h="all": idx.get((c, p, b, h))  # noqa: E731
    pop, ctl = payload["population"], payload["controls"]
    L = ["# Gap-to-market atlas (L10)", "",
         "**Descriptive development evidence, not a claim.** Each candidate's R = candidate Brier / market Brier "
         f"(R < 1 beats the market) on the C dev scorecard window ({pop['first_date']}..{pop['last_date']}, "
         f"{pop['n_dates']} dates, {pop['n_market_days']} market-days, 11 markets), served fallback where a "
         "candidate is absent. Brackets: date-clustered 95% CI (2,000 draws, seed 20260921). **Bold** R <= 1; "
         "*italic* CI includes 1; `cNN%` candidate coverage (rest is served fallback); (!) market Brier < 0.005, "
         "R not interpretable. Candidates are compared only with the market; no candidate-vs-candidate deltas.", "",
         f"Controls: served R all {ctl['served']['observed']['all']:.3f} / 00-16 {ctl['served']['observed']['00-16']:.3f} "
         f"({ctl['served']['verdict']}); MG-1 07-12 excess {ctl['mg1']['excess_over_market_07_12']:.4f} "
         f"({ctl['mg1']['verdict']}); L6 own-stack 07-12 Brier - MG-1 {ctl['l6_own_stack']['brier_minus_mg1_07_12']:.7f} "
         f"({ctl['l6_own_stack']['verdict']}); arm A 07-12 R {ctl['arm_a_dev4']['R_07_12_blended']:.4f} = L3 dev4 "
         f"({ctl['arm_a_dev4']['verdict']}).", ""]
    hdr = "| " + " | ".join(LABEL[c] for c in cands) + " |"
    sep = " --- |" * len(cands)
    for pool in ("PRIMARY5", "ALL"):
        L += [f"## {pool}: blocks and hours (all heat)", "", "| Block | n md " + hdr, "| --- | --- |" + sep]
        for b in MAIN + HOURS:
            r0 = g(cands[0], pool, b)
            if r0 is None:
                continue
            L.append(f"| {b} | {r0['n_market_days']} | " + " | ".join(cell(g(c, pool, b)) for c in cands) + " |")
        L.append("")
    L += ["## Heat third (within-market tercile of the market's 07-12 centre)", "",
          "| Pool | Block | Heat | n md " + hdr, "| --- | --- | --- | --- |" + sep]
    for pool in ("PRIMARY5", "ALL"):
        for b in ("07-12", "13-16", "00-16"):
            for h in ("hot", "mid", "cool"):
                r0 = g(cands[0], pool, b, h)
                L.append(f"| {pool} | {b} | {h} | {r0['n_market_days']} | "
                         + " | ".join(cell(g(c, pool, b, h)) for c in cands) + " |")
    L += ["", "## Per market (all heat)", "", "| Market | Block | n md " + hdr, "| --- | --- | --- |" + sep]
    markets = sorted({k[1] for k in idx} - {"ALL", "PRIMARY5"})
    for mk in markets:
        for b in ("07-12", "13-16", "00-16"):
            r0 = g(cands[0], mk, b)
            L.append(f"| {mk} | {b} | {r0['n_market_days']} | " + " | ".join(cell(g(c, mk, b)) for c in cands) + " |")
    # where any candidate reaches R <= 1 or comes close (interpretable hours <= 16 only)
    live = [(c, p, b, h, r) for (c, p, b, h), r in idx.items()
            if not r["late_flag"] and r["interpretable"] and r["R"] is not None]
    le1 = sorted([t for t in live if t[4]["R"] <= 1], key=lambda t: t[4]["R"])
    big = [t for t in le1 if t[4]["n_market_days"] >= 40 or (t[3] == "all" and t[2] in MAIN)]
    near = sorted([t for t in live if t[2] in MAIN and t[4]["n_market_days"] >= 40
                   and t[4]["ci95_date"][0] is not None and t[4]["ci95_date"][0] <= 1], key=lambda t: t[4]["R"])
    head = ["| Candidate | Pool | Block | Heat | R [date CI] | n md | n dates | MDE80 (R) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]

    def row(t):
        r = t[4]
        return (f"| {LABEL[t[0]]} | {t[1]} | {t[2]} | {t[3]} | {cell(r)} | {r['n_market_days']} | "
                f"{r['n_dates']} | {f3(r['mde80_R'])} |")
    L += ["", f"## Point estimate R <= 1 (hours <= 16, interpretable): {len(le1)} of {len(live)} cells", "",
          f"{len(le1) - len(big)} of them are heat-third or single-hour cells of one market (14-15 market-days, "
          "MDE80 mostly 0.3-2 in R): chance hits across many cells, kept in the JSON only. The rest:", "", *head]
    L += [row(t) for t in big]
    L += ["", f"## Close: block-level cells with >= 40 market-days whose CI includes 1: {len(near)}", "",
          "Not findings (many cells, four candidates): where an edge test could have power. MDE80 = 80%-power "
          "minimum detectable change in R from the date-clustered bootstrap; crossed intervals for pooled rows "
          "are wider.", "", *head]
    L += [row(t) for t in near]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.gap_to_market_atlas")
    ap.add_argument("--layout")
    ap.add_argument("--arm-a")
    ap.add_argument("--l6-module", default=str(DEFAULT_L6_MODULE))
    ap.add_argument("--dev4", help="L3 dev_scores_v4.json (arm A reproduction control)")
    ap.add_argument("--render-from", help="re-render the Markdown from an existing rows JSON (no scoring)")
    ap.add_argument("--p3d")
    ap.add_argument("--p3d-trained-through")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    if args.render_from:
        payload = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
        md = out / "gap_to_market.md"
        md.write_text(render(payload), encoding="utf-8", newline="\n")
        print(json.dumps({"md": str(md), "rows_sha256": data.sha256_file(args.render_from)}))
        return 0
    if not (args.layout and args.arm_a and args.dev4):
        ap.error("--layout, --arm-a and --dev4 are required unless --render-from is given")
    try:
        payload = run(args)
    except (data.Refused, data.LayoutError, data.LeakageError, data.WalkForwardError) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1).encode("utf-8")
    path = out / "gap_to_market_rows.json"
    path.write_bytes(blob)
    (out / "gap_to_market.md").write_text(render(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"json": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                      "controls": {k: v["verdict"] for k, v in payload["controls"].items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
