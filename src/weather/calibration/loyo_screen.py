"""Research only: a generic nested leave-one-year-out history screen for one candidate feature column.

The screen answers one question cheaply and on history only: does a candidate column, entering a fixed control arm
through a fixed mechanism, lower the per-row Brier of that arm under strictly nested leave-one-year-out (LOYO) on
the 2021-25 archives? It reports

* dR = mean over scored rows of [Brier(candidate) - Brier(control)], pooled and per local hour, with a seeded
  date-clustered percentile bootstrap interval (2,000 draws by default);
* rows, coverage (the share of rows where the column is defined) and the per-row control check against a frozen
  reference LOYO (for example R-A's ``loyo_rows.jsonl``: same rows, max abs diff at most 1e-9);
* one verdict line under a rule the caller states before the run (``upper<0`` and the like).

It reuses, rather than re-derives, the machinery that R-S and R-Q ran (lane L15,
``weather.calibration.spread_information_rung``): the P3d_N_fix arm of ``pooled_residual_model``, the market-centred
scale modulation, the inner-LOYO beta selection on ``RS_BETA_GRID`` and the training frame. That module and the
rung-0712 ``pooled_residual_model`` it needs are NOT on ``master`` (2026-10-30); they live on
``claude/rq-run-env-20261029``. The generic parts here (column loading and joining, the clustered summary, the control
check, the verdict) need neither and are tested on any base; the ``P3d_N_fix`` / ``scale`` runner imports the rung
module lazily and refuses with a clear message where it is missing. See
``docs/research/loyo-screen-harness-2026-10-30.md`` for what a screen can and cannot kill.

Subcommands (heavy; run only through ``scripts\\ops\\workstation_heavy.ps1``):

``run``
    The screen: ``--column`` (parquet or jsonl keyed on market, date, hour) into ``--control-arm`` P3d_N_fix by
    ``--mechanism`` scale, on ``--records`` and ``--nbm-train-corpus`` for ``--hours``; optional ``--control-rows``;
    ``--rule`` gives the verdict. Writes ``<name>_loyo.json`` and ``<name>_loyo_rows.jsonl`` (never overwrites).
    The receipt records the worktree's git HEAD and dirty flag; a dirty tree refuses unless ``--allow-dirty``.
``mr-gate``
    The MR gate (``weather.calibration.mr_gate``, rule 37cb46be): does a ruled candidate predict the market's
    error (P0) and earn a walk-forward log-pool weight over placebo and floor-only (w)? Dev window only.
``mr-sweep``
    The MR P0 sweep (``weather.calibration.mr_sweep``, rule 85f8192c, ledger row 78): 17 capture-time replay
    signals, paired P0 against the disagreement placebo, BH q = 0.10, the w gate for survivors. Dev window only.
``export-rq-gefs-column``
    The reproduction adapter: R-Q variant A's GEFS member-spread column ``u`` on the training frame's keys, written
    as a column file, so that ``run`` can reproduce R-Q gate 1 from a column alone.

Boundaries: offline, no network, never imported by serving, capture or release code (importing it on the capture
host raises ``ProductionImportRefused`` through ``pooled_residual_model``). History only: a column row dated after
2026-09-29 is refused, and the training frame must hold no 2026 row. Outputs must lie outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from weather.calibration import pooled_residual_model as prm  # refuses to load on the capture host

NAME = "loyo_screen"
SCHEMA = "loyo_screen/1"
LAST_ALLOWED = date(2026, 9, 29)
HISTORY_YEARS = (2021, 2022, 2023, 2024, 2025)
KEY = ("market", "date", "hour")
DEFAULT_DRAWS = prm.BOOTSTRAP_DRAWS
DEFAULT_SEED = prm.BOOTSTRAP_SEED
CONTROL_TOLERANCE = 1e-9
CONTROL_ARMS = ("P3d_N_fix",)
MECHANISMS = ("scale",)
BLOCK_HOURS = {"0712": (7, 8, 9, 10, 11, 12), "1316": (13, 14, 15, 16)}
METRICS = ("brier", "log")
_RULE = re.compile(r"^\s*(estimate|lower|upper)\s*(<=|<|>=|>)\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$")


class ScreenError(ValueError):
    """An input breaks the screen's contract (nothing is written)."""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_state(path=None):
    """The git HEAD and dirty flag of the worktree holding ``path`` (default: this module).

    Dirty means ``git status --porcelain`` lists anything, untracked files included. Outside a git worktree,
    or when git fails, the head is None and the tree counts as dirty.
    """
    import subprocess

    where = Path(path or __file__).resolve()
    where = where if where.is_dir() else where.parent

    def git(*args):
        proc = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, timeout=60,
                              check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    head, root = git("rev-parse", "HEAD"), git("rev-parse", "--show-toplevel")
    status = git("status", "--porcelain") if head else None
    dirty = status is None or bool(status)
    return {"git_head": head, "worktree": root, "dirty": dirty,
            "dirty_paths": [] if not status else status.splitlines()[:50]}


def require_clean(state, allow_dirty):
    """Refuse a dirty or unknown tree unless ``allow_dirty``; returns the receipt record."""
    if state["dirty"] and not allow_dirty:
        detail = "no git HEAD" if state["git_head"] is None else f"{len(state['dirty_paths'])} changed path(s)"
        raise ScreenError(f"refusing to run on a dirty tree ({detail} at {state['worktree']}); "
                          "commit first or pass --allow-dirty")
    return {**state, "allow_dirty": bool(allow_dirty)}


# ----------------------------------------------------------------------------- the candidate column

def load_column(path, value=None):
    """{(market, 'YYYY-MM-DD', hour): float} from a parquet or jsonl column file, plus its record.

    The file has the key columns ``market``, ``date`` and ``hour`` and one value column (named by ``value``, or the
    only other column). A duplicate key, a non-integer hour or a date after 2026-09-29 refuses. A null or non-finite
    value is kept as NaN: the row is then undefined and the mechanism leaves it unmodulated.
    """
    import pandas as pd

    path = Path(path)
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix in (".jsonl", ".json"):
        frame = pd.read_json(path, lines=True, dtype=False)
    else:
        raise ScreenError(f"column file must be .parquet or .jsonl: {path}")
    missing = [k for k in KEY if k not in frame.columns]
    if missing:
        raise ScreenError(f"column file lacks key columns {missing}")
    others = [c for c in frame.columns if c not in KEY]
    if value is None:
        if len(others) != 1:
            raise ScreenError(f"name the value column with --value; candidates are {others}")
        value = others[0]
    if value not in frame.columns:
        raise ScreenError(f"value column {value!r} not in {list(frame.columns)}")
    out = {}
    for market, day, hour, v in zip(frame["market"], frame["date"], frame["hour"], frame[value]):
        d = str(day)[:10]
        if date.fromisoformat(d) > LAST_ALLOWED:
            raise ScreenError(f"column row after {LAST_ALLOWED}: {market} {d}")
        if float(hour) != int(hour):
            raise ScreenError(f"hour {hour!r} is not an integer local hour")
        key = (str(market), d, int(hour))
        if key in out:
            raise ScreenError(f"duplicate column key {key}")
        x = float("nan") if v is None or pd.isna(v) else float(v)
        out[key] = x if math.isfinite(x) else float("nan")
    return out, {"path": str(path), "sha256": sha256_file(path), "value": value, "rows": len(out)}


def join_column(markets, dates, hours, column):
    """u per frame row (NaN where the column has no defined value) and the coverage record."""
    import numpy as np

    u = np.array([column.get((str(m), str(d)[:10], int(h)), float("nan")) for m, d, h in zip(markets, dates, hours)],
                 dtype=float)
    keys = {(str(m), str(d)[:10], int(h)) for m, d, h in zip(markets, dates, hours)}
    defined = int(np.isfinite(u).sum())
    return u, {"frame_rows": int(len(u)), "defined": defined, "coverage": defined / len(u) if len(u) else 0.0,
               "column_keys_outside_frame": sum(1 for k in column if k not in keys)}


# ----------------------------------------------------------------------------- summary, control, verdict

def clustered_summary(rows, candidate, control, draws=DEFAULT_DRAWS, seed=DEFAULT_SEED):
    """dR = candidate - control per hour and pooled (mean per row), date-clustered percentile bootstrap.

    The group order (hours ascending, then pooled), the metric order (brier, then log when present) and the single
    generator shared across groups are those of ``spread_information_rung.loyo_summary``, so a P3d_N_fix screen
    reproduces an R-S / R-Q summary draw for draw.
    """
    import numpy as np

    if not rows:
        raise ScreenError("no scored rows")
    metrics = [m for m in METRICS if f"{control}_{m}" in rows[0] and f"{candidate}_{m}" in rows[0]]
    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    groups["pooled"] = rows
    rng = np.random.default_rng(seed)
    out = {}
    for name, rs in groups.items():
        for metric in metrics:
            by_date = defaultdict(list)
            for r in rs:
                by_date[r["date"]].append(r[f"{candidate}_{metric}"] - r[f"{control}_{metric}"])
            dates = sorted(by_date)
            sums = np.array([sum(by_date[d]) for d in dates])
            counts = np.array([len(by_date[d]) for d in dates])
            idx = rng.integers(0, len(dates), size=(draws, len(dates)))
            boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
            out[f"{name}|{metric}"] = {
                "dR": float(sums.sum() / counts.sum()),
                "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                "control_mean": float(np.mean([r[f"{control}_{metric}"] for r in rs])),
                "n": len(rs), "n_dates": len(dates)}
    return out


def parse_rule(rule):
    """``(field, op, threshold)`` from e.g. ``upper<0``; fields are estimate, lower and upper of pooled dR Brier."""
    match = _RULE.match(str(rule or ""))
    if not match:
        raise ScreenError(f"rule {rule!r} is not '<estimate|lower|upper> <op> <number>'")
    return match.group(1), match.group(2), float(match.group(3))


def verdict(summary, rule, metric="brier"):
    field, op, threshold = parse_rule(rule)
    pooled = summary[f"pooled|{metric}"]
    value = {"estimate": pooled["dR"], "lower": pooled["ci95"][0], "upper": pooled["ci95"][1]}[field]
    passed = {"<": value < threshold, "<=": value <= threshold, ">": value > threshold, ">=": value >= threshold}[op]
    return {"rule": f"{field} {op} {threshold:g}", "metric": metric, "value": value, "pass": bool(passed),
            "line": (f"{'PASS' if passed else 'FAIL'}: pooled dR {pooled['dR']:+.5f} "
                     f"[{pooled['ci95'][0]:+.5f}, {pooled['ci95'][1]:+.5f}] ({pooled['n']} rows, "
                     f"{pooled['n_dates']} dates); rule {field} {op} {threshold:g}")}


def control_check(rows, control, reference_rows, tolerance=CONTROL_TOLERANCE):
    """The screen's control arm against a frozen reference LOYO, per (hour, market, date); refuses on a miss."""
    ref = {}
    with open(reference_rows, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            ref[(int(r["hour"]), str(r["market"]), str(r["date"])[:10])] = float(r[f"{control}_brier"])
    missing = [r for r in rows if (int(r["hour"]), str(r["market"]), str(r["date"])[:10]) not in ref]
    if missing or len(ref) != len(rows):
        raise ScreenError(f"control rows differ: screen {len(rows)}, reference {len(ref)}, unmatched {len(missing)}")
    worst = max(abs(r[f"{control}_brier"] - ref[(int(r["hour"]), str(r["market"]), str(r["date"])[:10])])
                for r in rows)
    if worst > tolerance:
        raise ScreenError(f"control arm does not reproduce the reference LOYO: max abs diff {worst}")
    return {"reference_rows": len(ref), "max_abs_diff": worst, "tolerance": tolerance,
            "reference_rows_sha256": sha256_file(reference_rows)}


# ----------------------------------------------------------------------------- the P3d_N_fix / scale runner

def _rung():
    """The L15 rung module (R-S / R-Q machinery); absent on master as of 2026-10-30."""
    try:
        from weather.calibration import spread_information_rung as rung
    except ModuleNotFoundError as exc:
        raise ScreenError(
            "the P3d_N_fix / scale runner needs weather.calibration.spread_information_rung and the rung-0712 "
            "pooled_residual_model (claude/rq-run-env-20261029); this base does not have them") from exc
    return rung


def training_frame(records_root, nbm_train_corpus, hours, markets=prm.R0_MARKETS):
    """R-S / R-Q's own training frame (records + NBM at the cutoff), restricted to ``hours``; 2021-25 only."""
    rung = _rung()
    frame, buckets, _, inputs = rung._training_inputs(records_root, nbm_train_corpus, markets, hours)
    years = sorted(int(y) for y in frame["year"].unique())
    if not set(years) <= set(HISTORY_YEARS):
        raise ScreenError(f"training frame years {years} are not inside {HISTORY_YEARS}")
    return frame, buckets, {**inputs, "years": years}


def run_scale_p3d_n_fix(frame, u, buckets, hours, candidate):
    """Nested LOYO per hour with u as a per-market centred scale modulator of P3d_N_fix (R-Q's variant A form)."""
    rows, betas, dev, diag = _rung().rs_loyo(frame, u, buckets, hours, centring="market", arm=candidate)
    return rows, {"betas": {f"h{h:02d}|{y}": v for (h, y), v in sorted(betas.items())},
                  "dev_betas": {f"h{h:02d}": v for h, v in sorted(dev.items())},
                  "x_diagnostics": {f"h{h:02d}": v for h, v in sorted(diag.items())}}


RUNNERS = {("P3d_N_fix", "scale"): run_scale_p3d_n_fix}


def screen(*, column, records_root, nbm_train_corpus, out_dir, name, rule, hours, control_arm="P3d_N_fix",
           mechanism="scale", value=None, control_rows=None, draws=DEFAULT_DRAWS, seed=DEFAULT_SEED,
           markets=prm.R0_MARKETS, allow_dirty=False):
    """One screen: the rule is parsed first (a bad rule refuses before any data is read).

    The receipt records the git HEAD and dirty flag of this module's worktree; a dirty tree refuses unless
    ``allow_dirty``.
    """
    import numpy as np

    parse_rule(rule)
    runner = RUNNERS.get((control_arm, mechanism))
    if runner is None:
        raise ScreenError(f"no runner for control arm {control_arm!r} by mechanism {mechanism!r}; "
                          f"available {sorted(RUNNERS)}")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name) or name == control_arm:
        raise ScreenError(f"candidate name {name!r} must be a word distinct from the control arm")
    code = require_clean(code_state(), allow_dirty)
    out = prm.require_output_outside_repo(out_dir)
    names = (f"{name}_loyo.json", f"{name}_loyo_rows.jsonl")
    for n in names:
        if (out / n).exists():
            raise ScreenError(f"refusing to overwrite {out / n}")
    col, col_record = load_column(column, value)
    frame, buckets, inputs = training_frame(records_root, nbm_train_corpus, hours, markets)
    u, coverage = join_column(frame["market"], frame["target_date"], frame["hour"], col)
    rows, fit = runner(frame, u, buckets, hours, name)
    controls = control_check(rows, control_arm, control_rows) if control_rows else None
    summary = clustered_summary(rows, name, control_arm, draws=draws, seed=seed)
    result = {"schema": SCHEMA, "name": name, "control_arm": control_arm, "mechanism": mechanism,
              "hours": list(hours), "draws": draws, "seed": seed, "rows": len(rows),
              "dates": len({r["date"] for r in rows}), "coverage": coverage, "column": col_record,
              "controls": controls, "summary": summary, "per_hour_dR_brier":
                  {k.split("|")[0]: v["dR"] for k, v in summary.items() if k.endswith("|brier") and k[0] == "h"},
              "verdict": verdict(summary, rule), "fit": fit, "code": code,
              "inputs": {**inputs, "module_sha256": sha256_file(__file__),
                         "prm_module_sha256": sha256_file(prm.__file__),
                         "rung_module_sha256": sha256_file(_rung().__file__),
                         "u_defined": int(np.isfinite(u).sum()), "u_rows": int(len(u))}}
    out.mkdir(parents=True, exist_ok=True)
    prm._write_jsonl(out / names[1], rows)
    (out / names[0]).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ----------------------------------------------------------------------------- the R-Q reproduction adapter

def export_rq_gefs_column(*, records_root, nbm_train_corpus, gefs_corpus, out_path, hours, markets=prm.R0_MARKETS):
    """R-Q variant A's u (ln max(GEFS member SD, 0.25); NaN below 25 members) on the training frame's keys."""
    import pandas as pd
    from weather.market.market_registry import spec_for_id

    rung = _rung()
    out_path = prm.require_output_outside_repo(out_path)
    if out_path.exists():
        raise ScreenError(f"refusing to overwrite {out_path}")
    gefs, ginputs = rung.load_gefs(gefs_corpus, "A")
    frame, _, inputs = training_frame(records_root, nbm_train_corpus, hours, markets)
    timezones = {m: spec_for_id(m).timezone for m in markets}
    rows = [{"market": str(m), "date": str(d)[:10], "hour": int(h),
             "u_gefs_sd": rung.gefs_u(gefs, m, str(d)[:10], int(h), timezones[m], "A")}
            for m, d, h in zip(frame["market"], frame["target_date"], frame["hour"])]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["market", "date", "hour", "u_gefs_sd"]).to_parquet(out_path, index=False)
    record = {"schema": f"{SCHEMA}/column", "path": str(out_path), "sha256": sha256_file(out_path),
              "rows": len(rows), "inputs": {**inputs, **ginputs}, "rung_module_sha256": sha256_file(rung.__file__)}
    out_path.with_suffix(".json").write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    return record


# ----------------------------------------------------------------------------- CLI

def _hours(text):
    if text in BLOCK_HOURS:
        return BLOCK_HOURS[text]
    hours = tuple(int(h) for h in str(text).split(","))
    if not hours or any(h < 0 or h > 23 for h in hours) or len(set(hours)) != len(hours):
        raise argparse.ArgumentTypeError(f"hours {text!r}: a block (0712, 1316) or distinct comma-separated hours")
    return hours


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.loyo_screen")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="nested LOYO 2021-25 screen of one candidate column")
    r.add_argument("--column", required=True)
    r.add_argument("--value", help="the value column (default: the only non-key column)")
    r.add_argument("--name", required=True, help="candidate arm label, e.g. P3d_N_fix_Q")
    r.add_argument("--control-arm", default="P3d_N_fix", choices=CONTROL_ARMS)
    r.add_argument("--mechanism", default="scale", choices=MECHANISMS)
    r.add_argument("--records", required=True)
    r.add_argument("--nbm-train-corpus", required=True)
    r.add_argument("--hours", type=_hours, required=True)
    r.add_argument("--control-rows", help="frozen reference LOYO rows for the control arm (e.g. R-A loyo_rows.jsonl)")
    r.add_argument("--rule", required=True, help="verdict rule on pooled dR Brier, e.g. 'upper<0'")
    r.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--out", required=True)
    r.add_argument("--allow-dirty", action="store_true",
                   help="run on a worktree with uncommitted changes (recorded in the receipt)")
    e = sub.add_parser("export-rq-gefs-column", help="R-Q variant A's GEFS member-spread column")
    e.add_argument("--records", required=True)
    e.add_argument("--nbm-train-corpus", required=True)
    e.add_argument("--gefs-corpus", required=True)
    e.add_argument("--hours", type=_hours, required=True)
    e.add_argument("--out", required=True, help="the .parquet column file to write")
    g = sub.add_parser("mr-gate", help="MR gate (rule 37cb46be): market-residual P0 and walk-forward w, dev window")
    g.add_argument("--layout", required=True, help="dev scorecard layout (C:/swarm/v3layout)")
    g.add_argument("--candidate", action="append", default=[], metavar="NAME=PATH",
                   help="a ruled candidate and its pinned dev emit (default: every ruled candidate)")
    g.add_argument("--out", required=True)
    g.add_argument("--allow-dirty", action="store_true")
    w = sub.add_parser("mr-sweep", help="MR P0 sweep (rule 85f8192c): 17 replay signals, BH q 0.10, dev window")
    w.add_argument("--layout", required=True, help="dev scorecard layout (C:/swarm/v3layout)")
    w.add_argument("--replay-root", required=True, help="captured replay inputs (replay-inputs-le0929)")
    w.add_argument("--out", required=True)
    w.add_argument("--allow-dirty", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "run":
        result = screen(column=args.column, value=args.value, name=args.name, control_arm=args.control_arm,
                        mechanism=args.mechanism, records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                        hours=args.hours, control_rows=args.control_rows, rule=args.rule, draws=args.draws,
                        seed=args.seed, out_dir=args.out, allow_dirty=args.allow_dirty)
        print(json.dumps({"verdict": result["verdict"]["line"], "controls": result["controls"],
                          "coverage": result["coverage"]}, indent=1))
        return 0  # a FAIL verdict is a result, not an error
    if args.command == "mr-gate":
        from weather.calibration import mr_gate

        cands = dict(c.split("=", 1) for c in args.candidate) or None
        receipt = mr_gate.run(layout=args.layout, out_dir=args.out, candidates=cands, allow_dirty=args.allow_dirty)
        print(json.dumps({"lines": receipt["lines"], "controls": {k: v["verdict"] for k, v in
                                                                  receipt["controls"].items()}}, indent=1))
        return 0
    if args.command == "mr-sweep":
        from weather.calibration import mr_sweep

        receipt = mr_sweep.run(layout=args.layout, out_dir=args.out, replay_root=args.replay_root,
                               allow_dirty=args.allow_dirty)
        print(json.dumps({"lines": receipt["lines"], "controls": {k: v["verdict"] for k, v in
                                                                  receipt["controls"].items()}}, indent=1))
        return 0
    record = export_rq_gefs_column(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                                   gefs_corpus=args.gefs_corpus, hours=args.hours, out_path=args.out)
    print(json.dumps({k: record[k] for k in ("path", "sha256", "rows")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
