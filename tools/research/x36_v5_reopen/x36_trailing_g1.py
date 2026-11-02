"""Lane L47, K row 112, G1: nested LOYO 2021-25 (Aug 15..Sep 29, 07-12) of the trailing excess-bias centre shift on
P3d_N_fix. Rule: docs/research/x36-v5-reopen-2026-11-01/rule_x36_trailing_final.md
(sha256 032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2).

Candidate (per rule): mu' = mu - lam * clip(b_recent(m, t; W) - b_train(m), +-3 F). The width comes from the
unshifted mu, and the floor is applied after the shift (both inside predictive_distribution). The grid is
W in {7, 14}, lam in {0, .25, .5, .75, 1}. Ties go to the smaller lam, then the smaller W.

Fixed before the run, and not varied after it:
* d(m, u) = NBP 07Z mean (L9 corpus 1ae4bf52...) - WU high (data/wunderground daily_summary). This comes from the
  ``dseries`` step (light, the C row 111 loaders). Only Aug 1..Sep 29 of 2021-25 is read.
* b_recent(m, t; W) = mean d over the market's W latest dates strictly before t, in the same year, from Aug 1. Where
  fewer than W exist, the shift is 0 and the row is counted.
* b_train(m) is nested: the mean of d over Aug 1..Sep 29 of the FIT years only (outer: years != held; inner: years
  outside {other, held}). The held-out year never informs its own correction.
* Training and fitting use every frame row (as R-A). Selection and the gate use target dates Aug 15..Sep 29 only.
* Inner selection: summed Brier over the inner held-out rows. The tabulated kernel is scored first, then the best 3
  plus lam=0 are re-scored exactly (the R-S method, table error <= 1e-6 per row).
* Positive control (before any gate number): this run's P3d_N_fix base reproduces R-A's 07-12 LOYO rows to 1e-9
  (same keys). The rows are C:\\t\\l2\\rung0712\\emit\\loyo_rows.jsonl, sha256 RA_ROWS_SHA256 below. R-K has no 07-12
  rows. R-A's are the 07-12 reference that R-R, R-S and R-Q reproduced at 0 difference.
* Gate: KILL unless the pooled dBrier (candidate - P3d_N_fix) point is < -0.0005. The 95% date-clustered bootstrap
  (2000 draws, seed 20261024) is reported.

Machinery: the rung-0712 ``pooled_residual_model`` and L15 ``spread_information_rung`` are not on master. ``loyo``
binds them from a pinned run-env worktree (``--run-env``, branch claude/rq-run-env-20261029 at
558889b13ac7d7165ddb299daa160052862aeb50), checked by file sha before any import. They are read-only imports.

Subcommands:
  dseries  light, run directly: write d(m, u) for 2021-25 Aug 1..Sep 29.
  loyo     heavy, run only via scripts\\ops\\workstation_heavy.ps1 -Queue (-m tools.research.x36_v5_reopen.x36_trailing_g1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

RULE_SHA256 = "032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2"
RUN_ENV_HEAD = "558889b13ac7d7165ddb299daa160052862aeb50"
PRM_SHA256 = "04e87406aca906f6c3853cfa12128bc1ab5ee7c8cf2a7f0dc59907c83cdb84db"
RUNG_SHA256 = "0eedce73af8637ca213de429475515e0b3293893bb37bac2b080bdce7f153212"
TRAIN_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
RA_ROWS_SHA256 = "21cacdaabcf50165da084a748b42a0b862c36c9e1f4b8d4bdb506c07c927f54d"
YEARS = (2021, 2022, 2023, 2024, 2025)
HOURS = (7, 8, 9, 10, 11, 12)
WINDOWS = (7, 14)
LAMBDAS = (0.0, 0.25, 0.5, 0.75, 1.0)
CLIP = 3.0
SEASON_FIRST = (8, 1)
SEASON_LAST = (9, 29)
GATE_FIRST = (8, 15)
KILL_LINE = -0.0005
CONTROL_TOL = 1e-9
TABLE_TOL = 1e-6
EXACT_TOP = 3
DRAWS = 2000
SEED = 20261024
SCHEMA = "l47_x36_trailing_g1/1"
ARM = "P3d_T"


class G1Error(RuntimeError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def in_season(day):
    return SEASON_FIRST <= (day.month, day.day) <= SEASON_LAST and day.year in YEARS


def in_gate(day_text):
    d = date.fromisoformat(str(day_text)[:10])
    return GATE_FIRST <= (d.month, d.day) <= SEASON_LAST


# ------------------------------------------------------------------ pure pieces (tested)

def grid():
    """Combos in tie-break order: smaller lam first, then smaller W. lam=0 is one combo."""
    out = [(0, 0.0)]
    for lam in LAMBDAS[1:]:
        for w in WINDOWS:
            out.append((w, lam))
    return out


def b_recent(series, market, day, w):
    """Mean d over the market's w latest dates strictly before ``day`` in the same year, else None."""
    d = date.fromisoformat(str(day)[:10])
    prior = [(u, v) for u, v in series.get(market, ()) if u < d.isoformat() and u[:4] == d.isoformat()[:4]]
    if len(prior) < w:
        return None
    prior.sort()
    return sum(v for _, v in prior[-w:]) / w


def b_train(series, years):
    """{market: mean d over the given years} (season dates only, as written by ``dseries``)."""
    out = {}
    for m, lst in series.items():
        vals = [v for u, v in lst if int(u[:4]) in years]
        if vals:
            out[m] = sum(vals) / len(vals)
    return out


def recent_table(series, keys):
    """{(market, date, W): b_recent or None} for every (market, date) key and every W."""
    return {(m, str(d)[:10], w): b_recent(series, m, d, w) for m, d in keys for w in WINDOWS}


def shift(recent, train_means, market, day, w, lam):
    """The centre shift subtracted from mu; 0 when lam is 0 or b_recent is unavailable."""
    if lam == 0.0:
        return 0.0
    br = recent[(market, str(day)[:10], w)]
    if br is None or market not in train_means:
        return 0.0
    return lam * max(-CLIP, min(CLIP, br - train_means[market]))


def pick(scores):
    """Minimum summed Brier; ties within 1e-12 go to the earliest combo in ``grid()`` order."""
    best = min(scores.values())
    for combo in grid():
        if combo in scores and scores[combo] <= best + 1e-12:
            return combo
    raise G1Error("no combo scored")


def verdict(point):
    return {"kill_line": KILL_LINE, "point": point, "pass": bool(point < KILL_LINE),
            "verdict": "PASS (G2 eligible on the coordinator's go)" if point < KILL_LINE else "KILL"}


def clustered(rows, a, b, draws=DRAWS, seed=SEED):
    """a - b per hour and pooled (mean per row), date-clustered percentile bootstrap, one shared generator."""
    import numpy as np

    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    groups["pooled"] = rows
    rng = np.random.default_rng(seed)
    out = {}
    for name, rs in groups.items():
        for metric in ("brier", "log"):
            by_date = defaultdict(list)
            for r in rs:
                by_date[r["date"]].append(r[f"{a}_{metric}"] - r[f"{b}_{metric}"])
            dates = sorted(by_date)
            sums = np.array([sum(by_date[d]) for d in dates])
            counts = np.array([len(by_date[d]) for d in dates])
            idx = rng.integers(0, len(dates), size=(draws, len(dates)))
            boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
            out[f"{name}|{metric}"] = {"estimate": float(sums.sum() / counts.sum()),
                                       "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                                       "base_mean": float(np.mean([r[f"{b}_{metric}"] for r in rs])),
                                       "n": len(rs), "n_dates": len(dates)}
    return out


def load_series(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("schema") != SCHEMA + "/dseries":
        raise G1Error("not a G1 dseries file")
    series = defaultdict(list)
    for r in obj["rows"]:
        d = date.fromisoformat(r["d"])
        if not in_season(d):
            raise G1Error(f"dseries row outside 2021-25 Aug 1..Sep 29: {r['d']}")
        series[r["m"]].append((r["d"], float(r["x"])))
    for m in series:
        series[m].sort()
    return dict(series), obj


# ------------------------------------------------------------------ dseries (light, normal environment)

def cmd_dseries(a):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import x36_v5 as base

    out = Path(a.out)
    if out.exists():
        raise G1Error(f"refusing to overwrite {out}")
    if sha256_file(a.train_corpus) != TRAIN_CORPUS_SHA256:
        raise G1Error("training corpus sha mismatch")
    corpus = [r for r in base.load_corpus(a.train_corpus, False)
              if in_season(date.fromisoformat(r["target_date"])) and r.get("cycle") == "07"]
    labels = base.load_labels(a.repo, set(YEARS), in_season)
    ps = base.pairs(corpus, labels)
    seen = set()
    for p in ps:
        if (p["m"], p["d"]) in seen:
            raise G1Error(f"duplicate d for {p['m']} {p['d']}")
        seen.add((p["m"], p["d"]))
    rows = sorted(({"m": p["m"], "d": p["d"], "x": p["x"]} for p in ps), key=lambda r: (r["m"], r["d"]))
    res = {"schema": SCHEMA + "/dseries", "module_sha256": sha256_file(__file__),
           "base_module_sha256": sha256_file(base.__file__), "train_corpus_sha256": TRAIN_CORPUS_SHA256,
           "n_rows": len(rows), "n_corpus_season_07z": len(corpus), "rows": rows}
    out.write_text(json.dumps(res, sort_keys=True), encoding="utf-8")
    print(json.dumps({"n_rows": len(rows), "n_corpus": len(corpus), "sha256": sha256_file(out)}))


# ------------------------------------------------------------------ loyo (heavy, pinned run env)

def bind_run_env(run_env):
    root = Path(run_env).resolve()
    src = root / "src"
    calib = src / "weather" / "calibration"
    if sha256_file(calib / "pooled_residual_model.py") != PRM_SHA256:
        raise G1Error("run-env pooled_residual_model sha mismatch")
    if sha256_file(calib / "spread_information_rung.py") != RUNG_SHA256:
        raise G1Error("run-env spread_information_rung sha mismatch")
    loaded = [k for k in sys.modules if k == "weather" or k.startswith("weather.")]
    if loaded:
        raise G1Error(f"weather already imported before binding the run env: {loaded[:3]}")
    sys.path.insert(0, str(src))
    from weather.calibration import pooled_residual_model as prm
    from weather.calibration import spread_information_rung as rung

    for mod in (prm, rung):
        if Path(mod.__file__).resolve().parent != calib:
            raise G1Error(f"{mod.__name__} resolved outside the run env: {mod.__file__}")
    import subprocess

    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=False).stdout.strip()
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True,
                            check=False).stdout.strip()
    if head != RUN_ENV_HEAD or status:
        raise G1Error(f"run env not at a clean {RUN_ENV_HEAD}: head {head}, dirty {bool(status)}")
    return prm, rung, {"run_env": str(root), "run_env_head": head, "prm_sha256": PRM_SHA256,
                       "rung_sha256": RUNG_SHA256}


def training_frame(prm, records_root, train_corpus):
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    if sha256_file(train_corpus) != TRAIN_CORPUS_SHA256:
        raise G1Error("training corpus sha mismatch")
    markets = prm.R0_MARKETS
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = prm.dev_training_frame(records_root, markets)
    years = sorted(int(y) for y in frame["year"].unique())
    if not set(years) <= set(YEARS):
        raise G1Error(f"training frame years {years} outside 2021-25")
    frame, stats = prm.attach_training_nbm(frame, l9.load_nbm(train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(HOURS)].reset_index(drop=True)
    return frame, buckets, {"train_nbm": stats, "years": years, "frame_rows": int(len(frame))}


def _brier_exact(prm, fm, r, mu):
    dist = prm.predictive_distribution(mu, r["s"], r["F"], r["z"], r["buckets"], r["p_clim"])
    return fm.brier_score(dist, r["actual"]), fm.log_loss(dist, r["actual"])


def run_loyo(prm, rung, frame, buckets, series):
    import numpy as np
    from weather.calibration import feature_model as fm

    combos = grid()
    rows, picks, counts = [], {}, defaultdict(int)
    zeros = np.zeros(len(frame))
    recent = recent_table(series, set(zip(frame["market"], (str(d)[:10] for d in frame["target_date"]))))
    for hour in HOURS:
        mask = (frame["hour"] == hour).to_numpy()
        at_hour = frame[mask].reset_index(drop=True)
        x_hour = zeros[mask]
        years = sorted(int(y) for y in at_hour["year"].unique())
        fits = {}

        def preds(excluded, target):
            key = frozenset(excluded)
            if key not in fits:
                fits[key] = rung._fit(at_hour, x_hour, key, "pooled")
            entry = fits[key]
            sel = (at_hour["year"] == target).to_numpy()
            out = rung.predict_rows(entry, at_hour[sel].reset_index(drop=True), buckets, x_hour[sel], 0.0)
            for r in out:
                if r["actual"] is None:
                    raise G1Error(f"row without an outcome: {r['market']} {r['date']} h{hour}")
            return out

        for held in years:
            inner_rows = []
            for other in years:
                if other == held:
                    continue
                tm = b_train(series, set(years) - {other, held})
                for r in preds({other, held}, other):
                    if in_gate(r["date"]):
                        inner_rows.append((r, {c: shift(recent, tm, r["market"], r["date"], *c) for c in combos}))
            approx = {c: 0.0 for c in combos}
            for r, sh in inner_rows:
                for c in combos:
                    approx[c] += rung.fast_brier(r["yhat"] - sh[c], r["s"], r["F"], r["table"], r["p_clim"],
                                                 r["actual"])
            order = sorted(combos, key=lambda c: (approx[c], combos.index(c)))[:EXACT_TOP]
            exact = {}
            for c in sorted(set(order) | {(0, 0.0)}, key=combos.index):
                exact[c] = sum(_brier_exact(prm, fm, r, r["yhat"] - sh[c])[0] for r, sh in inner_rows)
            err = max(abs(exact[c] - approx[c]) / max(1, len(inner_rows)) for c in exact)
            if err > TABLE_TOL:
                raise G1Error(f"kernel table error {err} above {TABLE_TOL} (h{hour} held {held})")
            chosen = pick(exact)
            picks[f"h{hour:02d}|{held}"] = {"W": chosen[0], "lam": chosen[1], "inner_rows": len(inner_rows),
                                            "inner_brier_base": exact[(0, 0.0)], "inner_brier_pick": exact[chosen],
                                            "table_error_per_row": err}
            tm = b_train(series, set(years) - {held})
            for r in preds({held}, held):
                b0, l0 = _brier_exact(prm, fm, r, r["yhat"])
                row = {"hour": int(hour), "year": int(held), "market": r["market"], "date": r["date"],
                       "P3d_N_fix_brier": b0, "P3d_N_fix_log": l0, "gate": in_gate(r["date"])}
                if row["gate"]:
                    s = shift(recent, tm, r["market"], r["date"], *chosen)
                    available = chosen[1] == 0.0 or recent[(r["market"], r["date"], chosen[0])] is not None
                    counts["gate_rows"] += 1
                    counts["gate_rows_shift_unavailable"] += int(not available)
                    b1, l1 = (b0, l0) if s == 0.0 else _brier_exact(prm, fm, r, r["yhat"] - s)
                    row.update({f"{ARM}_brier": b1, f"{ARM}_log": l1, "shift": s, "W": chosen[0], "lam": chosen[1]})
                rows.append(row)
            print(f"g1 h{hour:02d} held {held}: pick W={chosen[0]} lam={chosen[1]}", flush=True)
    return rows, picks, dict(counts)


def control(rows, ra_path):
    if sha256_file(ra_path) != RA_ROWS_SHA256:
        raise G1Error("R-A reference rows sha mismatch")
    ref = {}
    for line in Path(ra_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ref[(int(r["hour"]), r["market"], str(r["date"])[:10])] = float(r["P3d_N_fix_brier"])
    got = {(r["hour"], r["market"], r["date"]): r["P3d_N_fix_brier"] for r in rows}
    same = set(ref) == set(got)
    worst = max((abs(got[k] - ref[k]) for k in set(ref) & set(got)), default=float("inf"))
    return {"reference": str(ra_path), "reference_sha256": RA_ROWS_SHA256, "n_reference": len(ref),
            "n_rows": len(got), "same_keys": same, "max_abs_diff": worst, "tolerance": CONTROL_TOL,
            "pass": bool(same and worst <= CONTROL_TOL)}


def cmd_loyo(a):
    prm, rung, env = bind_run_env(a.run_env)
    out = prm.require_output_outside_repo(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = ("g1_result.json", "g1_rows.jsonl")
    for n in names:
        if (out / n).exists():
            raise G1Error(f"refusing to overwrite {out / n}")
    series, sobj = load_series(a.dseries)
    frame, buckets, finfo = training_frame(prm, a.records, a.train_corpus)
    res = {"schema": SCHEMA, "rule_sha256": RULE_SHA256, "module_sha256": sha256_file(__file__),
           "inputs": {**env, **finfo, "dseries": str(a.dseries), "dseries_sha256": sha256_file(a.dseries),
                      "dseries_rows": sobj["n_rows"], "records": str(a.records),
                      "train_corpus_sha256": TRAIN_CORPUS_SHA256},
           "grid": [list(c) for c in grid()], "hours": list(HOURS)}

    def finish():
        (out / names[0]).write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: res.get(k) for k in ("stopped_at", "verdict")}, default=str), flush=True)

    rows, picks, counts = run_loyo(prm, rung, frame, buckets, series)
    prm._write_jsonl(out / names[1], rows)
    res.update({"picks": picks, "counts": counts})
    res["control"] = control(rows, a.ra_rows)
    if not res["control"]["pass"]:
        res["stopped_at"] = "positive control failed (STOP, not a gate result)"
        finish()
        return 3
    gate_rows = [r for r in rows if r["gate"]]
    res["summary"] = clustered(gate_rows, ARM, "P3d_N_fix")
    res["shift_stats"] = {"mean_abs_shift": float(sum(abs(r["shift"]) for r in gate_rows) / len(gate_rows)),
                          "share_nonzero": float(sum(r["shift"] != 0.0 for r in gate_rows) / len(gate_rows))}
    res["verdict"] = verdict(res["summary"]["pooled|brier"]["estimate"])
    finish()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="x36_trailing_g1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dseries")
    d.add_argument("--train-corpus", required=True)
    d.add_argument("--repo", required=True)
    d.add_argument("--out", required=True)
    lo = sub.add_parser("loyo")
    lo.add_argument("--run-env", required=True)
    lo.add_argument("--records", required=True)
    lo.add_argument("--train-corpus", required=True)
    lo.add_argument("--dseries", required=True)
    lo.add_argument("--ra-rows", required=True)
    lo.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "dseries":
        cmd_dseries(a)
        return 0
    return cmd_loyo(a)


if __name__ == "__main__":
    sys.exit(main())
