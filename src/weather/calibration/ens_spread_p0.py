r"""ECMWF ENS member spread against the market: kill-only P0 (lane L17, 2026-10-31; dev-window ledger row 93).

Rule ``docs/research/p5-screens-2026-10-31/rule_ens_spread_p0.md`` (Amendment A3, sha256 ``RULE_SHA256``,
branch ``claude/p5-screens-20261031``). Machinery: ``mr_sweep`` (rule 85f8192c) sections 1-5, imported unchanged;
``mr_gate.gate_candidate`` for a survivor only.

K = 2 type S, sign + candidates on the G2 cache ``points.parquet`` (sha-pinned, read only, never fetched or
rebuilt; rows with target_date > 2026-09-29 are filtered out at read time and never materialised):

- ENS-SD-0712: ``ens_sd_f`` of (station, target D) from the 00Z run of D, on local 07-12 snapshots;
- ENS-SD-0006: ``ens_sd_f`` of (station, target D) from the 00Z run of D-1, on local 00-06 snapshots;
- covered iff ``available_utc`` <= ``captured_at_utc``, ``n_members`` == 51 and the value is finite.

Order: the parent controls (served R, MG-1 07-12 excess, w = 0 identity) and the A4 synthetic sign controls
(SYN+ must SURVIVE and SYN- must read Delta < 0, per block, labelled CONTROL, in memory only) run before any
candidate is scored; any failure writes a VOID receipt and no candidate row. Verdicts (A3, fixed at P0):
"P0 survivor; w underpowered (0.28-0.31), context only" for a P0 survivor (testable, BH q 0.10 over K = 2
rejects, Delta lower bound > 0), "KILL at edge size" otherwise, or UNTESTABLE. A survivor's w gate (context only,
it cannot change the verdict) runs in its own block; ``mr_gate.BLOCKS`` gains "00-06" at runtime (accepted in
A3; recorded in the receipt) without editing ``mr_gate``.

No network I/O. B-bound files are imported read-only from this tree (master 035f5bb19 versions, A3) and
sha-checked against the A3 pins at start and before the receipt; the receipt records the git tree sha and those
file shas. Writes once under ``--out``, which must lie below ``C:/t/l17/ens/`` and must not exist.

    python -m weather.calibration.ens_spread_p0 --layout C:/swarm/v3layout --out C:/t/l17/ens/run1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "ens_spread_p0/1"
GATE = "ENS-SPREAD-P0"
LEDGER_ROW = 93
RULE_PATH = "docs/research/p5-screens-2026-10-31/rule_ens_spread_p0.md"
RULE_SHA256 = "25fc62bd2208fab2a88f1c51d2338456887bc6a51acabca0b6950dd6f2174c92"
POINTS_SHA256 = "bd761fa52869d244addda7fb3746276e1eb6aad2416ac2fdc3291750d7320a7e"
DEFAULT_POINTS = r"C:\Users\Michael\Documents\github\weather\data\research\free_sources\ecmwf_ens\points.parquet"
OUT_ROOT = Path("C:/t/l17/ens")
LAST_ALLOWED = ls.LAST_ALLOWED  # 2026-09-29
FIRST_TARGET = "2026-07-31"
N_MEMBERS = 51
SYN_SEED = 20261031
K = 2
# (id, block, run offset in days from target D, local hour range) - rule section 4
CANDIDATES = (
    ("ENS-SD-0712", "07-12", 0, (7, 12)),
    ("ENS-SD-0006", "00-06", 1, (0, 6)),
)
EXTRA_BLOCKS = {"00-06": (0, 6)}  # runtime addition to mr_gate.BLOCKS (A2 disclosure, accepted in A3)
VERDICT_SURVIVOR = "P0 survivor; w underpowered (0.28-0.31), context only"
VERDICT_KILL = "KILL at edge size"
# A3 B-bound pins: imported read-only (master 035f5bb19 versions); the run refuses on any mismatch.
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
               "weather.reporting.scorecards.loss_atlas", "weather.sources.free_screens.common")


class EnsError(mg.GateError):
    pass


# ----------------------------------------------------------------------------- guards

def check_out_dir(out_dir, root=OUT_ROOT):
    """``out_dir`` must sit strictly below ``root`` and must not exist yet (write once)."""
    out = Path(out_dir).resolve()
    base = Path(root).resolve()
    if base not in out.parents:
        raise EnsError(f"refusing to write outside {base}: {out}")
    if out.exists():
        raise EnsError(f"refusing to overwrite an existing output directory {out}")
    return out


def load_points(path, expected_sha=POINTS_SHA256):
    """The pinned G2 ENS table, 2026 targets <= 2026-09-29 only (later rows are filtered at read time)."""
    import pyarrow.parquet as pq

    sha = ls.sha256_file(path)
    if sha != expected_sha:
        raise EnsError(f"points.parquet sha256 {sha} is not the pinned {expected_sha}")
    last = LAST_ALLOWED.isoformat()
    tbl = pq.read_table(path, columns=["run", "station", "target_date", "ens_sd_f", "n_members", "available_utc"],
                        filters=[("target_date", "<=", last), ("target_date", ">=", FIRST_TARGET)])
    pts = tbl.to_pandas()
    if (pts.target_date.astype(str) > last).any():
        raise EnsError("points rows after 2026-09-29 reached the reader")
    return pts, sha


def station_map(markets):
    """Layout market -> ICAO for the US settlement stations; toronto (no ENS row) maps to None."""
    from weather.sources.free_screens.common import us_stations

    icao = {s.market: s.icao for s in us_stations()}
    out = {}
    for mk in sorted(set(markets)):
        if mk == "toronto":
            out[mk] = None
        elif mk in icao:
            out[mk] = icao[mk]
        else:
            raise EnsError(f"layout market {mk!r} has no US station mapping")
    return out


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
            raise EnsError(f"B-bound file {p} is loaded from outside the run tree {root}") from None
        seen[rel] = _sha(p)
    unpinned = sorted(set(seen) - set(pins))
    if unpinned:
        raise EnsError(f"B-bound files loaded without an A3 pin: {unpinned}")
    bad = {k: v for k, v in seen.items() if v != pins[k]}
    if bad:
        raise EnsError(f"B-bound files differ from their A3 pins: {bad}")
    return dict(sorted(seen.items()))


def git_tree(repo_root):
    proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True,
                          timeout=60, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


# ----------------------------------------------------------------------------- capture-time values

def _as_utc(values):
    """Timestamps (tz-aware column) or ISO strings (any offset) -> naive UTC datetime64[ns] (NaT if missing)."""
    s = pd.Series(values).reset_index(drop=True)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        return s.dt.tz_convert(None).to_numpy("datetime64[ns]")
    return sw._utc(s.astype(object).where(s.notna(), None))


def candidate_values(snaps, markets, local_hour, points, smap):
    """Per candidate: ``ens_sd_f`` on each snapshot of the candidate's block (NaN where uncovered or outside
    the block), plus the extracted feature frame (one row per candidate and snapshot in its block)."""
    pts = points.copy()
    pts["key"] = pts.station.astype(str) + "|" + pts.run.astype(str) + "|" + pts.target_date.astype(str)
    if pts.key.duplicated().any():
        raise EnsError("points.parquet has duplicate (station, run, target_date) rows")
    pts = pts.set_index("key")
    cap = _as_utc(snaps.captured_at_utc)
    dates = snaps.date.astype(str).to_numpy()
    if (dates > LAST_ALLOWED.isoformat()).any():
        raise EnsError("a snapshot is dated after 2026-09-29")
    icao = np.array([smap.get(m) for m in markets], dtype=object)
    out, feats = {}, []
    for cid, _, offset, (lo, hi) in CANDIDATES:
        in_block = (local_hour >= lo) & (local_hour <= hi) & (icao != None)  # noqa: E711
        runs = np.array([(date.fromisoformat(d) - timedelta(days=offset)).isoformat() for d in dates], dtype=object)
        keys = [f"{i}|{r}|{d}" if ok else None for i, r, d, ok in zip(icao, runs, dates, in_block)]
        hit = pts.reindex([k if k is not None else "" for k in keys])
        sd = hit.ens_sd_f.to_numpy(float)
        nm = hit.n_members.to_numpy(float)
        avail = _as_utc(hit.available_utc)
        ok = (in_block & np.isfinite(sd) & (nm == N_MEMBERS) & ~np.isnat(avail) & ~np.isnat(cap)
              & (avail <= cap))
        out[cid] = np.where(ok, sd, np.nan)
        sel = np.flatnonzero(in_block)
        feats.append(pd.DataFrame({"candidate": cid, "row_key": snaps.row_key.to_numpy()[sel],
                                   "market": np.asarray(markets)[sel], "date": dates[sel],
                                   "local_hour": np.asarray(local_hour)[sel], "station": icao[sel],
                                   "run": runs[sel], "captured_at_utc": snaps.captured_at_utc.astype(str).to_numpy()[sel],
                                   "available_utc": avail[sel], "n_members": nm[sel], "ens_sd_f": sd[sel],
                                   "covered": ok[sel]}))
    return out, pd.concat(feats, ignore_index=True)


# ----------------------------------------------------------------------------- A4 synthetic control

def synthetic_values(table, geo, block_mask, seed=SYN_SEED):
    """CONTROL only (rule (a) A4): r = ((y_mid - mu_m)^2 - sigma_m^2)/sigma_m^2 per snapshot from the settled
    band midpoint, plus noise of SD sd(r); returns (SYN+, SYN-) on ``block_mask`` (NaN elsewhere). In memory."""
    ny = np.bincount(table.band_snap, weights=table.y, minlength=len(table.snaps))
    zy = np.bincount(table.band_snap, weights=table.y * geo["z"], minlength=len(table.snaps))
    with np.errstate(invalid="ignore", divide="ignore"):
        y_mid = np.where(ny > 0, zy / ny, np.nan)
    r = ((y_mid - geo["mu"]) ** 2 - geo["var"]) / geo["var"]
    ok = block_mask & np.isfinite(r)
    sd = float(np.std(r[ok])) if ok.any() else 1.0
    eps = np.random.default_rng(seed).normal(0.0, sd if sd > 0 else 1.0, len(r))
    plus = np.where(ok, r + eps, np.nan)
    return plus, -plus


def synthetic_controls(fit_t, score_t, geo, counts, score_dates, donors, block_masks):
    """Per block: SYN+ must SURVIVE (Delta lower bound > 0 and p <= the rank-1 BH threshold q/K), SYN- must read
    Delta < 0. Both always run; only Delta, CI and p are kept (labelled CONTROL)."""
    out = {}
    for block, mask in block_masks.items():
        plus, minus = synthetic_values(fit_t, geo, mask)
        rec = {"label": "CONTROL", "block": block}
        for name, vals in (("SYN+", plus), ("SYN-", minus)):
            res, _ = sw.p0_candidate(f"CONTROL {name} {block}", "S", 1, vals, fit_t, score_t, geo, counts,
                                     score_dates, donors)
            p0 = res["p0"]
            rec[name] = {"label": "CONTROL", "testable": res["testable"], "delta": p0.get("delta"),
                         "ci95": p0.get("ci95"), "p_one_sided": p0.get("p_one_sided"),
                         "coverage": res["coverage"]}
        sp, sm = rec["SYN+"], rec["SYN-"]
        plus_ok = bool(sp["testable"] and sp["ci95"][0] is not None and sp["ci95"][0] > 0
                       and sp["p_one_sided"] <= sw.BH_Q / K)
        minus_ok = bool(sm["testable"] and sm["delta"] is not None and sm["delta"] < 0)
        rec["verdict"] = "PASS" if plus_ok and minus_ok else "FAIL"
        rec["checks"] = {"syn_plus_survives": plus_ok, "syn_minus_delta_below_0": minus_ok}
        out[block] = rec
    return out


# ----------------------------------------------------------------------------- per-market per-date rows

def market_date_rows(cid, vecs, fit_t, score_t, score_dates):
    """Per (market, date) sufficient sums for the candidate and the 20 placebos, on its P0 population."""
    from weather.calibration import market_blend as mb

    pop = mb.restrict_snap(fit_t, score_t, vecs["pop_fit"])
    band = pop[score_t.band_snap]
    m, e = score_t.p_market, score_t.y - score_t.p_market
    didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    c = mb.restrict(fit_t, score_t, vecs["c_fit"])
    pls = [mb.restrict(fit_t, score_t, p) for p in vecs["placebos_fit"]]
    mk_b = score_t.markets[score_t.band_snap]
    rows = []
    for mk in sorted(set(score_t.markets)):
        sel = band & (mk_b == mk)
        if not sel.any():
            continue
        sc_ = sw.date_sums((c - m)[sel], e[sel], didx[sel], len(score_dates))
        sp = [sw.date_sums((p - m)[sel], e[sel], didx[sel], len(score_dates)) for p in pls]
        for i in np.flatnonzero(sc_[0] > 0):
            rows.append({"candidate": cid, "market": mk, "date": score_dates[i], "sums_c": sc_[:, i].tolist(),
                         "sums_pl": [s[:, i].tolist() for s in sp]})
    return rows


def _population(cid, values_fit, fit_t, geo, donors):
    """Re-derive the P0 population and the placebo vectors exactly as ``mr_sweep.p0_candidate`` does."""
    covered = np.isfinite(values_fit)
    s = sw.band_signal("S", 1, np.where(covered, values_fit, np.nan), fit_t, geo)
    c_fit, _ = sw.tilt(fit_t, geo, s, covered)
    cov_float = np.repeat(covered.astype(float), fit_t.n)
    donor_ok = np.ones(len(fit_t.snaps), bool)
    placebos = []
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(fit_t, c_fit, seed, donors[seed])
        donor_ok &= np.bincount(fit_t.band_snap, weights=cov_float[donors[seed][0]],
                                minlength=len(fit_t.snaps)) == fit_t.n
        placebos.append(pl)
    return {"c_fit": c_fit, "placebos_fit": placebos, "pop_fit": covered & donor_ok}


# ----------------------------------------------------------------------------- decision

def decide(results):
    """BH over K = 2 and the A3 verdict labels (fixed at P0); mutates and returns ``results``."""
    ids = [c[0] for c in CANDIDATES]
    adj, reject = sw.bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    for cid, q, rj in zip(ids, adj, reject):
        r = results[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"], r["bh_reject"] = float(q), bool(rj)
        r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["verdict"] = (VERDICT_SURVIVOR if r["survive"] else
                        ("UNTESTABLE" if not r["testable"] else VERDICT_KILL))
    return results


def line_for(r):
    if not r["testable"]:
        return (f"UNTESTABLE: {r['candidate']} coverage {r['coverage']['population_snapshots']} snapshots / "
                f"{r['coverage']['population_dates']} dates; q {r['bh_q']:.3f}")
    p0, ci = r["p0"], r["p0"]["ci95"]
    tail = ""
    if "w_gate" in r:
        tail = f"; w gate (context only) {r['w_gate']['verdict']} (mean w {r['w_gate']['w']['summary']['mean']:.3f})"
    return (f"{r['verdict']}: {r['candidate']} delta {p0['delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]; "
            f"p {p0['p_one_sided']:.4f}; BH q {r['bh_q']:.3f}; rho_c {p0['rho_c']:+.4f}, "
            f"rho_pl {p0['rho_pl_mean']:+.4f}{tail}")


def _write(out, name, payload):
    path = out / name
    if path.exists():
        raise EnsError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=mg._default), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- the run

def run(*, layout, out_dir, points=DEFAULT_POINTS, allow_dirty=False, repo_root=None):
    import importlib

    code = ls.require_clean(ls.code_state(), allow_dirty)
    root = Path(repo_root or Path(__file__).resolve().parents[3])
    rule = root / RULE_PATH
    if not rule.is_file() or ls.sha256_file(rule) != RULE_SHA256:
        raise EnsError(f"rule {rule} is not the pinned A3 rule {RULE_SHA256}")
    for name in RUN_IMPORTS:
        importlib.import_module(name)
    bb_start = bbound_check(root)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = check_out_dir(out_dir)
    pts, points_sha = load_points(points)
    for block, hours in EXTRA_BLOCKS.items():
        if mg.BLOCKS.get(block, hours) != hours:
            raise EnsError(f"mr_gate.BLOCKS already defines {block} differently")
        mg.BLOCKS[block] = hours
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    smap = station_map(fit_t.markets)
    out.mkdir(parents=True)
    base = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
            "git_tree": git_tree(root), "bbound_sha256": bb_start,
            "evidence_class": ("development (dev window, kill-only P0; verdict fixed at P0: "
                               f"{VERDICT_KILL!r} or {VERDICT_SURVIVOR!r})"),
            "points_sha256": points_sha, "layout_manifest_sha256": lay.manifest_sha256,
            "module_sha256": {"ens_spread_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                              "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
            "scorecard_code_sha256": sc.code_sha256(), "station_map": smap,
            "runtime_block_addition": EXTRA_BLOCKS,
            "constants": {"draws": sw.DRAWS, "seed": sw.SEED, "placebo_seeds": list(sw.PLACEBO_SEEDS),
                          "bh_q": sw.BH_Q, "k": K, "sigma2_floor": sw.SIGMA2_FLOOR, "min_dates": sw.MIN_DATES,
                          "min_snapshots": sw.MIN_SNAPS, "n_members": N_MEMBERS, "syn_seed": SYN_SEED},
            "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                           "n_scored_dates": len(scored), "n_market_days": len(score_t.keys)}}
    try:
        controls = mg.market_controls(fit_t, score_t)
    except mb.ControlFailed as exc:
        _write(out, "ens_spread_p0_VOID.json", {**base, "verdict": "VOID", "reason": str(exc)})
        raise
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    us = np.array([smap.get(m) is not None for m in fit_t.markets])
    block_masks = {blk: mb.hour_mask(fit_t, lo, hi) & us for _, blk, _, (lo, hi) in CANDIDATES}
    controls["A4_synthetic"] = synthetic_controls(fit_t, score_t, geo, counts, score_dates, donors, block_masks)
    if any(v["verdict"] != "PASS" for v in controls["A4_synthetic"].values()):
        _write(out, "ens_spread_p0_VOID.json", {**base, "verdict": "VOID", "controls": controls})
        raise mb.ControlFailed("refused: A4 synthetic control failed (run VOID)")

    values, feats = candidate_values(fit_t.snaps, fit_t.markets, fit_t.local_hour, pts, smap)
    feats.to_parquet(out / "features.parquet", index=False)
    results, kept, rows, mrows = {}, {}, [], []
    for cid, block, _, _ in CANDIDATES:
        res, vecs = sw.p0_candidate(cid, "S", 1, values[cid], fit_t, score_t, geo, counts, score_dates, donors)
        rows += res.pop("_rows", [])
        res["block"] = block
        results[cid] = res
        if vecs is not None:
            kept[cid] = vecs
            mrows += market_date_rows(cid, _population(cid, values[cid], fit_t, geo, donors), fit_t, score_t,
                                      score_dates)
    decide(results)
    for cid, block, _, _ in CANDIDATES:
        if not results[cid]["survive"]:
            continue
        vec = kept[cid]
        controls[f"w0_identity_{cid}"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
        if controls[f"w0_identity_{cid}"]["verdict"] != "PASS":
            _write(out, "ens_spread_p0_VOID.json", {**base, "verdict": "VOID", "controls": controls})
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, block, fit_t, score_t, vec["c_fit"], vec["covered"], p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"role": "context only (A3: w underpowered 0.28-0.31, cannot change the verdict)",
                                  "verdict": "PASS (w)" if g["w"]["pass"] else "FAIL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}
    (out / "ens_spread_p0_rows.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n" for r in rows), encoding="utf-8")
    (out / "ens_spread_p0_market_rows.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n" for r in mrows), encoding="utf-8")
    if bbound_check(root) != bb_start:
        raise EnsError("B-bound files changed during the run")
    receipt = {**base, "controls": controls, "results": results,
               "lines": [line_for(results[c[0]]) for c in CANDIDATES],
               "rows_sha256": ls.sha256_file(out / "ens_spread_p0_rows.jsonl"),
               "market_rows_sha256": ls.sha256_file(out / "ens_spread_p0_market_rows.jsonl"),
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet")}
    _write(out, "ens_spread_p0.json", receipt)
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.ens_spread_p0", description=__doc__.split("\n")[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--points", default=DEFAULT_POINTS)
    a = ap.parse_args(argv)
    rec = run(layout=a.layout, out_dir=a.out, points=a.points)
    print("\n".join(rec["lines"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
