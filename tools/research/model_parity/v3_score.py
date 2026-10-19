"""HARNESS v3 H4/H5/H6/H7: the single-shot scorer.

    python -m tools.research.model_parity.v3_score --prereg P.json --prereg-sha256 <hex> \
        --layout <v3 layout dir> --out <dir> [--look K]

Order of operations (each step refuses before the next one runs):

1. Exit 3 at once if a sealed result for this prereg (and look) already exists.
2. Verify the prereg's sha256 (exit 2) and every arm's pinned code sha256 (exit 2).
3. Ask the gate (H1) for every (arm family, prereg date); a refusal exits 5 with nothing read.
4. Read outcome-free inputs, build every arm AND its input-removed twin.
5. Compute the non-binding O'Brien-Fleming futility boundaries (H7) and write+seal them.
6. Only now join labels and market prices; screen the inputs for planted label columns (exit 4).
7. Score all arms in one pass: E1 R = Brier_arm / Brier_market per block; E2 frozen-weight
   arm+market blend ("complementary information", never edge); arm - served for context.
8. Write the result JSON, its sha256 sidecar, mark both read-only; THEN append the label ledger
   (H6) and, for a confirmation, the forward alpha ledger "spent" row; THEN print.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

import numpy as np
import pandas as pd

from tools.research.model_parity import (v3_arms, v3_core, v3_gate, v3_inputs, v3_outcomes,
                                         v3_sequential)

PREREG_SCHEMA = "harness_v3_prereg/1"
RESULT_SCHEMA = "harness_v3_result/1"
BLEND_FIT_LAST_DATE = "2026-09-29"
LEAKAGE_SUSPECT_RATIO = 0.5
LABEL_MATCH_SHARE = 0.99
LABEL_MATCH_MIN_ROWS = 50
BUILTINS = ("market_identity",)
EXIT_OK, EXIT_VERIFY, EXIT_SEALED, EXIT_LEAK, EXIT_GATE = 0, 2, 3, 4, 5
V3_FILES = ("harness.py", "__init__.py", "v3_gate.py", "v3_inputs.py", "v3_outcomes.py", "v3_core.py",
            "v3_arms.py", "v3_dryrun.py", "v3_power.py", "v3_sequential.py", "v3_score.py")


class ScoreRefused(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def harness_v3_sha256():
    """sha256 over the v2 harness and every v3 module, in V3_FILES order."""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in V3_FILES:
        digest.update((here / name).read_bytes())
    return digest.hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def seal(path, payload):
    """Write JSON, a sha256 sidecar, and set both read-only. Refuses to overwrite."""
    path = Path(path)
    side = path.with_name(path.name + ".sha256")
    if path.exists() or side.exists():
        raise ScoreRefused(EXIT_SEALED, f"sealed file already exists: {path}")
    data = json.dumps(payload, indent=1, sort_keys=True, default=float).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as stream:
        stream.write(data)
    with open(side, "x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{_sha(data)}  {path.name}\n")
    for p in (path, side):
        os.chmod(p, stat.S_IREAD)
    return _sha(data)


def verify_sealed(path):
    path = Path(path)
    data = path.read_bytes()
    want = path.with_name(path.name + ".sha256").read_text(encoding="utf-8").split()[0]
    return _sha(data) == want and not os.access(path, os.W_OK)


# ----------------------------------------------------------------------------- label screen

def screen_planted_labels(snaps, bands, labels, y):
    """Refuse when any input column is a label in disguise (name or content)."""
    v3_arms.screen_names(snaps, bands)
    lab = labels.set_index("row_key").reindex(snaps.row_key)
    hits = []
    for col in snaps.columns:
        x = pd.to_numeric(snaps[col], errors="coerce").to_numpy(float)
        for target in ("settlement_high", "settlement_bucket"):
            t = pd.to_numeric(lab[target], errors="coerce").to_numpy(float)
            ok = ~np.isnan(x) & ~np.isnan(t)
            if ok.sum() >= LABEL_MATCH_MIN_ROWS and ok.mean() >= LABEL_MATCH_SHARE and \
                    np.mean(np.abs(x[ok] - t[ok]) < 1e-9) >= LABEL_MATCH_SHARE:
                hits.append(f"snapshot column {col!r} reproduces {target}")
    for col in bands.columns:
        x = pd.to_numeric(bands[col], errors="coerce").to_numpy(float)
        ok = ~np.isnan(x)
        win, lose = ok & (y == 1), ok & (y == 0)
        if ok.sum() >= LABEL_MATCH_MIN_ROWS and ok.mean() >= LABEL_MATCH_SHARE and win.any() and \
                set(np.unique(x[ok])) <= {0.0, 1.0} and np.mean(x[win] == 1) >= LABEL_MATCH_SHARE and \
                np.mean(x[lose] == 0) >= LABEL_MATCH_SHARE:
            hits.append(f"band column {col!r} reproduces the winner indicator")
    if hits:
        raise ScoreRefused(EXIT_LEAK, "planted label column(s) in candidate input: " + "; ".join(hits))
    return True


# ----------------------------------------------------------------------------- endpoints

def _group_tables(t, p_arm, use, y, p_market, scope):
    served = t.snapshot_brier(t.p_served, y)
    market = t.snapshot_brier(p_market, y)
    arm = t.snapshot_brier(p_arm, y)
    out = {}
    for g in v3_core.groups():
        mask = t.group_mask(g) & scope
        if not mask.any():
            out[g] = {"status": "NO_DATA"}
            continue
        idx, a = t.cells(arm, mask)
        _, s = t.cells(served, mask)
        _, m = t.cells(market, mask)
        keys = [t.keys[i] for i in idx]
        per_market = pd.Series(a - m, index=[k[1] for k in keys]).groupby(level=0).mean()
        market_est = float(m.mean())
        out[g] = {"market_days": int(len(idx)), "dates": len({k[0] for k in keys}),
                  "markets": len({k[1] for k in keys}), "snapshots": int(mask.sum()),
                  "arm_coverage_share": float(use[mask].mean()),
                  "brier_arm": float(a.mean()), "brier_market": market_est, "brier_served": float(s.mean()),
                  "E1_R_arm_over_market": {**t.interval(idx, a, m), "interpretable": market_est >= 0.005},
                  "arm_minus_market": t.interval(idx, a - m),
                  "arm_minus_served": t.interval(idx, a - s, effect=v3_core.MDE_EFFECT),
                  "markets_arm_below_market": int((per_market < 0).sum()),
                  "leakage_suspect": bool(a.mean() < LEAKAGE_SUSPECT_RATIO * market_est)}
    return out


def blend(p_arm, p_market, weight):
    return weight * p_arm + (1.0 - weight) * p_market


def fit_blend_weights(t, p_arm, y, p_market, dates, grid=None):
    """Per-group weight on the arm minimising equal-market-day Brier, fit dates <= 2026-09-29 only."""
    if max(dates) > BLEND_FIT_LAST_DATE:
        raise ScoreRefused(EXIT_GATE, "blend weights may be fit only on dates <= 2026-09-29")
    grid = np.round(np.arange(0, 1.0001, 0.01), 2) if grid is None else grid
    scope = t.snaps.date.astype(str).isin(set(dates)).to_numpy()
    weights = {}
    for g in v3_core.groups():
        mask = t.group_mask(g) & scope
        if not mask.any():
            continue
        best = min(grid, key=lambda w: t.cells(t.snapshot_brier(blend(p_arm, p_market, w), y), mask)[1].mean())
        weights[g] = float(best)
    return weights


# ----------------------------------------------------------------------------- the pass

def _load_prereg(path, sha):
    data = Path(path).read_bytes()
    if _sha(data) != sha:
        raise ScoreRefused(EXIT_VERIFY, f"prereg sha256 {_sha(data)} != {sha}")
    prereg = json.loads(data.decode("utf-8"))
    if prereg.get("schema") != PREREG_SCHEMA:
        raise ScoreRefused(EXIT_VERIFY, "prereg schema mismatch")
    if prereg["purpose"] not in v3_gate.JOIN_PURPOSES:
        raise ScoreRefused(EXIT_VERIFY, f"prereg purpose {prereg['purpose']!r}")
    return prereg


def _date_range(start, end):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, end, freq="D")]


def run(prereg_path, prereg_sha256, layout, out_dir, look=None, gate=None, repo_root=None,
        label_ledger=None, alpha_ledger_spend=True):
    out_dir = Path(out_dir)
    stem = prereg_sha256[:16] + (f".look{look}" if look else "")
    result_path = out_dir / f"{stem}.result.json"
    if result_path.exists() or result_path.with_name(result_path.name + ".sha256").exists():
        raise ScoreRefused(EXIT_SEALED, f"a sealed result already exists: {result_path}")
    prereg = _load_prereg(prereg_path, prereg_sha256)
    gate = gate or v3_gate.default_gate()
    root = Path(repo_root) if repo_root else Path(prereg_path).resolve().parent
    purpose = prereg["purpose"]
    arms, builtins = [], []
    for spec in prereg["arms"]:
        if "builtin" in spec:
            if spec["builtin"] not in BUILTINS or purpose == "confirmation":
                raise ScoreRefused(EXIT_VERIFY, f"builtin arm {spec['builtin']!r} not allowed here")
            builtins.append(spec["builtin"])
            continue
        path = Path(spec["path"])
        path = path if path.is_absolute() else root / path
        try:
            arms.append(v3_arms.load_arm(path, spec["code_sha256"]))
        except v3_arms.ArmError as exc:
            raise ScoreRefused(EXIT_VERIFY, str(exc)) from exc
    names = [a.NAME for a in arms] + builtins
    if len(set(names)) != len(names):
        raise ScoreRefused(EXIT_VERIFY, "duplicate arm names")
    dates = _date_range(prereg["dates"]["start"], prereg["dates"]["end"])
    tickets = {}
    families = {(a.FAMILY, a.READS_NBM_GUIDANCE) for a in arms} or {(prereg.get("family", "control"), False)}
    try:
        for fam, reads in sorted(families):
            tickets[(fam, reads)] = gate.require(fam, dates, purpose, reads)
        fam0, reads0 = sorted(families)[0]
        snaps, bands, manifest = v3_inputs.read_inputs(layout, gate, fam0, reads0, purpose="coverage")
    except v3_gate.GateRefused as exc:
        raise ScoreRefused(EXIT_GATE, str(exc)) from exc
    keep = snaps.date.astype(str).isin(set(dates)).to_numpy()
    snaps = snaps[keep].reset_index(drop=True)
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    if not len(snaps):
        raise ScoreRefused(EXIT_GATE, "no input rows inside the prereg date range")
    # ---- outcome-free: build arms and their input-removed twins
    candidates = {}
    for arm in arms:
        candidates[arm.NAME] = v3_arms.build(arm, snaps, bands)
        s2, b2 = v3_arms.input_removed(arm, snaps, bands)
        candidates[arm.NAME + "__input_removed"] = v3_arms.build(arm, s2, b2)
    # ---- H7 boundaries sealed before any join
    interim = prereg.get("interim")
    bounds = None
    if interim:
        bounds = v3_sequential.boundaries(interim["looks"], interim.get("alpha", 0.025), interim.get("beta", 0.2))
        bpath = out_dir / f"{prereg_sha256[:16]}.boundaries.json"
        if bpath.exists():
            if json.loads(bpath.read_text(encoding="utf-8")) != json.loads(json.dumps(bounds, sort_keys=True)):
                raise ScoreRefused(EXIT_VERIFY, "sealed boundaries differ from the prereg's")
        else:
            seal(bpath, bounds)
    boundaries_written_before_join = True
    # ---- join (labels + market) under the gate tickets
    try:
        first = tickets[sorted(tickets)[0]]
        for (fam, reads), tk in tickets.items():
            for name in (v3_outcomes.LABEL_FILE, v3_outcomes.MARKET_FILE):
                v3_inputs.gate_file(gate, manifest, name, fam, purpose, reads)
        labels, market = v3_outcomes.load_outcomes(layout, gate, first)
    except v3_gate.GateRefused as exc:
        raise ScoreRefused(EXIT_GATE, str(exc)) from exc
    t = v3_core.Table(snaps, bands)
    lab = labels.set_index("row_key").reindex(t.snaps.row_key)
    if lab.winner.isna().any():
        raise ScoreRefused(EXIT_VERIFY, "a scored snapshot has no label")
    winner = lab.winner.to_numpy(int)
    y = (bands.band_index.to_numpy(int) == np.repeat(winner, t.n)).astype(float)
    mk = market.set_index(["row_key", "band_index"]).p_market_yes.reindex(
        pd.MultiIndex.from_arrays([bands.row_key, bands.band_index])).to_numpy(float)
    if np.isnan(mk).any():
        raise ScoreRefused(EXIT_VERIFY, "a scored band has no market price")
    screen_planted_labels(snaps, bands, labels, y)
    scope = np.ones(len(t.snaps), bool)
    # ---- one pass over every arm
    results, vectors = {}, {}
    for name, cand in candidates.items():
        pc, use, reason = t.candidate_vector(cand, floor=True)
        vectors[name] = pc
        results[name] = {"reason_counts": {k: int(v) for k, v in zip(*np.unique(reason, return_counts=True))},
                         "groups": _group_tables(t, pc, use, y, mk, scope)}
    for name in builtins:
        vectors[name] = mk.copy()
        results[name] = {"builtin": True, "floor_applied": False,
                         "groups": _group_tables(t, mk, np.ones(len(t.snaps), bool), y, mk, scope)}
    e2 = {}
    weights = (prereg.get("E2") or {}).get("weights") or {}
    for name, per_group in weights.items():
        e2[name] = {"label": "complementary information (model+market blend), NOT edge",
                    "weights_frozen_in_prereg": per_group, "fit_last_date": BLEND_FIT_LAST_DATE,
                    "groups": {}}
        for g, w in per_group.items():
            pb = blend(vectors[name], mk, float(w))
            tab = _group_tables(t, pb, np.ones(len(t.snaps), bool), y, mk, t.group_mask(g))[g]
            e2[name]["groups"][g] = {"weight": float(w), "E2_R_blend_over_market": tab["E1_R_arm_over_market"],
                                     "blend_minus_market": tab["arm_minus_market"]}
    primary = prereg.get("primary")
    decision = None
    if primary:
        tab = results[primary["arm"]]["groups"][primary["block"]]
        r = tab["E1_R_arm_over_market"]
        z = (1.0 - r["estimate"]) / r["boot_sd"] if r["boot_sd"] and r["boot_sd"] > 0 else math.inf
        decision = {"arm": primary["arm"], "block": primary["block"], "z_improvement": z,
                    "R": r["estimate"], "R_ci95": r["ci95"]}
        if bounds and look:
            decision["look"] = look
            decision["outcome"] = v3_sequential.interim_decision(bounds, look, z)
        else:
            decision["outcome"] = "GO" if r["ci95"][1] < 1.0 else "NO-GO"
    payload = {"schema": RESULT_SCHEMA, "prereg_sha256": prereg_sha256, "prereg_id": prereg.get("prereg_id"),
               "purpose": purpose, "development": purpose != "confirmation", "look": look,
               "HARNESS_V3_SHA256": harness_v3_sha256(),
               "arm_code_sha256": {a.NAME: a.CODE_SHA256 for a in arms},
               "gate": gate.identity(), "layout_manifest_sha256": {
                   k: v["sha256"] for k, v in manifest["files"].items()},
               "date_range": [dates[0], dates[-1]], "scored_dates": sorted(t.snaps.date.astype(str).unique()),
               "scored_market_days": len(t.keys), "boundaries": bounds,
               "boundaries_sealed_before_join": boundaries_written_before_join,
               "E1": results, "E2": e2, "decision": decision,
               "leakage_suspects": sorted(f"{n}:{g}" for n, r in results.items()
                                          for g, x in r["groups"].items() if x.get("leakage_suspect")),
               "sealed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    digest = seal(result_path, payload)
    ledger_path = Path(label_ledger) if label_ledger else out_dir / "label_ledger.jsonl"
    led = v3_outcomes.LabelLedger(ledger_path)
    for fam, _ in sorted(tickets):
        led.record(fam, labels, prereg_sha256)
    if purpose == "confirmation" and alpha_ledger_spend:
        for (fam, _), tk in tickets.items():
            v3_gate.append_row({"schema": v3_gate.LEDGER_SCHEMA, "row_id": f"spent-{prereg_sha256[:16]}-{fam}",
                                "family": fam, "date_start": dates[0], "date_end": dates[-1], "status": "spent",
                                "scope": "join", "decided_by": "v3_score", "decided_at": payload["sealed_utc"][:10],
                                "reason": f"confirmation scored under prereg {prereg_sha256}",
                                "source": str(result_path)}, gate.ledger_path)
    return result_path, digest, payload


def summary_lines(payload):
    lines = [f"sealed {payload['prereg_sha256'][:16]} purpose={payload['purpose']} "
             f"HARNESS_V3_SHA256={payload['HARNESS_V3_SHA256']}"]
    for name, r in payload["E1"].items():
        g = r["groups"].get("00-16", {})
        if "E1_R_arm_over_market" in g:
            x = g["E1_R_arm_over_market"]
            lines.append(f"{name}: 00-16 R={x['estimate']:.4f} [{x['ci95'][0]:.4f}, {x['ci95'][1]:.4f}]")
    if payload["decision"]:
        lines.append(f"decision: {payload['decision']['outcome']}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="HARNESS v3 single-shot scorer")
    ap.add_argument("--prereg", required=True)
    ap.add_argument("--prereg-sha256", required=True)
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--look", type=int)
    ap.add_argument("--repo-root")
    a = ap.parse_args(argv)
    try:
        path, digest, payload = run(a.prereg, a.prereg_sha256, a.layout, a.out, a.look, repo_root=a.repo_root)
    except ScoreRefused as exc:
        print(f"REFUSED ({exc.code}): {exc}", file=sys.stderr)
        return exc.code
    for line in summary_lines(payload):
        print(line)
    print(f"result {path} sha256 {digest}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
