"""Frozen-baseline replay trend (item 217).

Measures the settlement-scored skill of the **current** model code against a
**pinned baseline** code over the **same** captured-input corpus, so model
improvement is observed with weather held constant. Live-forward day-over-day
skill (item 117) conflates code and weather; this module removes the weather by
scoring both code versions on identical observations and reporting the
current-minus-baseline delta over time.

Inputs are variant prediction exports (the same long-table rows item 69/142/143
already produce): each row carries ``probability`` (the model's prediction for a
band), ``market_yes`` (market price), and ``outcome`` (settled 0/1), keyed by the
observation ``(market_id, target_date, snapshot_id, band_key)``. Scoring is
restricted to the intersection of observations present in both exports — that
shared set is the frozen corpus.

Subcommands:

* ``pin``    -- pin a durable baseline (manifest + copied prediction export).
* ``update`` -- score current vs the pinned baseline, append one rolling trend
  row (upsert by run-date), and write the JSON payload + Markdown report.
* ``report`` -- re-render the report from the existing trend series.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.io import copy_file_atomic, write_json_atomic, write_text_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.reporting.candidate_lifecycle.multi_variant_shadow import (
    ALIASES,
    normalize_rows,
    observation_key,
)
from weather.schema_registry import schema_version

TREND_SCHEMA_VERSION = schema_version("frozen_baseline_replay_trend")
MANIFEST_SCHEMA_VERSION = schema_version("frozen_baseline_manifest")

DEFAULT_DIR = data_path() / "backtest"
DEFAULT_MANIFEST = DEFAULT_DIR / "frozen_baseline_manifest.json"
DEFAULT_TREND_JSONL = DEFAULT_DIR / "frozen_baseline_replay_trend.jsonl"
DEFAULT_JSON_OUT = DEFAULT_DIR / "frozen_baseline_replay_trend.json"
DEFAULT_REPORT_OUT = DEFAULT_DIR / "frozen_baseline_replay_trend_report.md"
DEFAULT_BASELINE_STORE = DEFAULT_DIR / "frozen_baselines"

_EPS = 1e-6

# ``build_payload`` deliberately continues to use the canonical row normalizer.
# These are the only normalized fields that can affect its validation errors,
# observation keys, run date, score aggregates, or report slices.  Keep every
# accepted raw alias so projecting a wide retained export cannot change those
# semantics.
_PREDICTION_INPUT_FIELDS = (
    "variant_id",
    "variant_family",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "cutoff_regime",
)
_PREDICTION_INPUT_COLUMNS = tuple(
    dict.fromkeys(
        column
        for field in _PREDICTION_INPUT_FIELDS
        for column in ALIASES.get(field, (field,))
    )
)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _json_prediction_rows(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "predictions", "variant_rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"{path} is not a JSON array or object with rows/predictions")


def _iter_prediction_rows(paths):
    """Yield raw rows without retaining a whole input file in memory.

    CSV and JSONL are streamed. JSON arrays retain their historical whole-file
    parsing behavior because the standard-library JSON decoder is not
    incremental; retained production prediction exports use CSV.
    """
    for path in paths:
        path = Path(path)
        if path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)
        elif path.suffix.lower() == ".json":
            yield from _json_prediction_rows(path)
        else:
            with path.open("r", encoding="utf-8", newline="") as handle:
                yield from csv.DictReader(handle)


def read_prediction_rows(paths, variant_id=None):
    """Read only score-relevant rows and columns from prediction exports.

    The variant predicate is applied while CSV/JSONL rows are streamed, before
    either irrelevant variants or wide attribution fields can accumulate in
    memory. Row order and raw value types are preserved so canonical
    normalization, selected-row numbering, and validation behavior remain the
    same as the former read-all-then-filter path.
    """
    rows = []
    for row in _iter_prediction_rows(paths):
        if variant_id and row.get("variant_id") != variant_id:
            continue
        rows.append({column: row.get(column) for column in _PREDICTION_INPUT_COLUMNS if column in row})
    return rows


def _brier(probability, outcome):
    return (float(probability) - float(outcome)) ** 2


def _logloss(probability, outcome):
    p = min(1.0 - _EPS, max(_EPS, float(probability)))
    y = float(outcome)
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


def _filter_variant(rows, variant_id):
    if not variant_id:
        return rows
    return [row for row in rows if row.get("variant_id") == variant_id]


def prediction_index(rows):
    """Collapse normalized rows to one settled prediction per observation.

    Returns ``{obs_key: {probability, market_yes, outcome, market_id, regime}}``.
    Only observations with a settled ``outcome`` (0/1) and a numeric
    ``probability`` are retained. Duplicate keys (e.g. the same band scored under
    multiple variant rows) are averaged so a single export resolves to at most
    one prediction per observation.
    """
    grouped = defaultdict(list)
    for row in rows:
        if row.get("outcome") not in (0, 1):
            continue
        if row.get("probability") is None:
            continue
        grouped[observation_key(row)].append(row)
    index = {}
    for key, members in grouped.items():
        probs = [float(r["probability"]) for r in members]
        markets = [float(r["market_yes"]) for r in members if r.get("market_yes") is not None]
        index[key] = {
            "probability": sum(probs) / len(probs),
            "market_yes": (sum(markets) / len(markets)) if markets else None,
            "outcome": int(members[0]["outcome"]),
            "market_id": members[0].get("market_id"),
            "regime": members[0].get("cutoff_regime") or "unknown",
        }
    return index


def _new_acc():
    return {
        "n": 0,
        "n_market": 0,
        "brier_current": 0.0,
        "brier_baseline": 0.0,
        "brier_market": 0.0,
        "logloss_current": 0.0,
        "logloss_baseline": 0.0,
        "logloss_market": 0.0,
    }


def _accumulate(acc, cur, base):
    y = cur["outcome"]
    acc["n"] += 1
    acc["brier_current"] += _brier(cur["probability"], y)
    acc["brier_baseline"] += _brier(base["probability"], y)
    acc["logloss_current"] += _logloss(cur["probability"], y)
    acc["logloss_baseline"] += _logloss(base["probability"], y)
    market_yes = cur.get("market_yes")
    if market_yes is None:
        market_yes = base.get("market_yes")
    if market_yes is not None:
        acc["n_market"] += 1
        acc["brier_market"] += _brier(market_yes, y)
        acc["logloss_market"] += _logloss(market_yes, y)


def _finalize(acc):
    n = acc["n"]
    nm = acc["n_market"]
    if not n:
        return None
    bc = acc["brier_current"] / n
    bb = acc["brier_baseline"] / n
    lc = acc["logloss_current"] / n
    lb = acc["logloss_baseline"] / n
    out = {
        "shared_observations": n,
        "brier_current": bc,
        "brier_baseline": bb,
        # Negative = current code BETTER than the baseline on identical weather.
        "brier_delta_current_minus_baseline": bc - bb,
        "logloss_current": lc,
        "logloss_baseline": lb,
        "logloss_delta_current_minus_baseline": lc - lb,
    }
    if nm:
        bm = acc["brier_market"] / nm
        lm = acc["logloss_market"] / nm
        out.update({
            "scored_market_observations": nm,
            "brier_market": bm,
            "brier_delta_current_minus_market": bc - bm,
            "brier_delta_baseline_minus_market": bb - bm,
            "logloss_market": lm,
        })
    return out


def compare_predictions(current_rows, baseline_rows):
    """Score current vs baseline over the shared (frozen) corpus.

    Both inputs are normalized rows. Returns overall / per-market / per-regime
    aggregates plus corpus coverage counts. Weather is held constant because
    every scored observation is the *same* captured snapshot for both code
    versions.
    """
    current = prediction_index(current_rows)
    baseline = prediction_index(baseline_rows)
    shared = sorted(set(current) & set(baseline))

    overall = _new_acc()
    by_market = defaultdict(_new_acc)
    by_regime = defaultdict(_new_acc)
    for key in shared:
        cur = current[key]
        base = baseline[key]
        # An observation only holds weather constant if both code versions agree
        # on the settled outcome; mismatches indicate label drift and are skipped.
        if cur["outcome"] != base["outcome"]:
            continue
        _accumulate(overall, cur, base)
        _accumulate(by_market[cur["market_id"] or "unknown"], cur, base)
        _accumulate(by_regime[cur["regime"]], cur, base)

    market_days = {(v["market_id"], k[1]) for k, v in current.items() if k in set(shared)}
    coverage = {
        "shared_observations": len(shared),
        "current_only_observations": len(set(current) - set(baseline)),
        "baseline_only_observations": len(set(baseline) - set(current)),
        "shared_market_days": len(market_days),
        "shared_markets": len({current[k]["market_id"] for k in shared}),
    }
    return {
        "coverage": coverage,
        "overall": _finalize(overall),
        "by_market": {m: _finalize(a) for m, a in sorted(by_market.items()) if _finalize(a)},
        "by_regime": {r: _finalize(a) for r, a in sorted(by_regime.items()) if _finalize(a)},
    }


def _run_date(current_rows):
    dates = [str(r.get("target_date"))[:10] for r in current_rows if r.get("target_date")]
    return max(dates) if dates else None


def build_payload(
    current_rows,
    baseline_rows,
    *,
    manifest=None,
    code_identity=None,
    current_paths=None,
    baseline_paths=None,
    generated_at=None,
):
    norm_current, current_errors = normalize_rows(current_rows)
    norm_baseline, baseline_errors = normalize_rows(baseline_rows)
    comparison = compare_predictions(norm_current, norm_baseline)
    shared = comparison["coverage"]["shared_observations"]
    overall = comparison["overall"]
    status = "PRESENT" if (shared > 0 and overall) else "MISSING"
    reasons = []
    if not norm_baseline:
        reasons.append("no_baseline_predictions")
    elif shared == 0:
        reasons.append("no_shared_frozen_observations")
    manifest = manifest or {}
    return {
        "schema_version": TREND_SCHEMA_VERSION,
        "generated_at_utc": generated_at or utc_iso(),
        "run_date": _run_date(norm_current),
        "independent_baseline_status": status,
        "status_reasons": reasons,
        "baseline_id": manifest.get("baseline_id"),
        "baseline_code_identity": manifest.get("code_identity"),
        "baseline_pinned_at_utc": manifest.get("pinned_at_utc"),
        "current_code_identity": code_identity,
        "current_paths": [str(p) for p in current_paths or []],
        "baseline_paths": [str(p) for p in baseline_paths or []],
        "coverage": comparison["coverage"],
        "overall": overall,
        "by_market": comparison["by_market"],
        "by_regime": comparison["by_regime"],
        "validation_errors": current_errors,
        "baseline_validation_errors": baseline_errors,
    }


def trend_row(payload):
    """Compact rolling-series row (upsert by run-date)."""
    overall = payload.get("overall") or {}
    return {
        "schema_version": TREND_SCHEMA_VERSION,
        "run_date": payload.get("run_date"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "baseline_id": payload.get("baseline_id"),
        "current_code_identity": payload.get("current_code_identity"),
        "independent_baseline_status": payload.get("independent_baseline_status"),
        "shared_observations": (payload.get("coverage") or {}).get("shared_observations", 0),
        "brier_current": overall.get("brier_current"),
        "brier_baseline": overall.get("brier_baseline"),
        "brier_delta_current_minus_baseline": overall.get("brier_delta_current_minus_baseline"),
        "brier_delta_current_minus_market": overall.get("brier_delta_current_minus_market"),
        "logloss_delta_current_minus_baseline": overall.get("logloss_delta_current_minus_baseline"),
    }


# --- persistence ------------------------------------------------------------


def load_trend(path=DEFAULT_TREND_JSONL):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def upsert_trend(row, path=DEFAULT_TREND_JSONL):
    """Append the row, replacing any existing row with the same run-date."""
    rows = [r for r in load_trend(path) if r.get("run_date") != row.get("run_date")]
    rows.append(row)
    rows.sort(key=lambda r: str(r.get("run_date") or ""))
    path = Path(path)
    write_text_atomic(
        path,
        "\n".join(json.dumps(r, sort_keys=True, default=str) for r in rows) + "\n",
    )
    return rows


def write_json(path, payload):
    return write_json_atomic(path, payload, trailing_newline=True)


def load_manifest(path=DEFAULT_MANIFEST):
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def pin_baseline(
    baseline_predictions,
    *,
    baseline_id,
    code_identity=None,
    corpus_id=None,
    manifest_path=DEFAULT_MANIFEST,
    store_dir=DEFAULT_BASELINE_STORE,
):
    """Pin a durable baseline: copy the prediction export(s) into a stable store
    and write the manifest. Returns the manifest dict."""
    store_dir = Path(store_dir) / baseline_id
    store_dir.mkdir(parents=True, exist_ok=True)
    stored = []
    for src in baseline_predictions:
        src = Path(src)
        dest = store_dir / src.name
        copy_file_atomic(src, dest)
        stored.append(str(dest))
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "pinned_at_utc": utc_iso(),
        "code_identity": code_identity,
        "corpus_id": corpus_id,
        "predictions_paths": stored,
        "source_paths": [str(p) for p in baseline_predictions],
    }
    write_json_atomic(manifest_path, manifest, trailing_newline=True)
    return manifest


# --- rendering --------------------------------------------------------------


def _delta_label(value):
    if value is None:
        return "-"
    return f"{value:+.4f}"


def render_report(payload, trend_rows=None):
    overall = payload.get("overall") or {}
    coverage = payload.get("coverage") or {}
    lines = [
        "# Frozen-Baseline Replay Trend (weather held constant)",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run date: `{payload.get('run_date')}`",
        f"Independent baseline status: **{payload.get('independent_baseline_status')}**",
        f"Baseline: `{payload.get('baseline_id')}` "
        f"(code `{payload.get('baseline_code_identity')}`, pinned {payload.get('baseline_pinned_at_utc')})",
        f"Current code: `{payload.get('current_code_identity')}`",
        "",
        "## Corpus Coverage (frozen = shared observations)",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Shared observations (scored)", coverage.get("shared_observations", 0)],
            ["Shared market-days", coverage.get("shared_market_days", 0)],
            ["Shared markets", coverage.get("shared_markets", 0)],
            ["Current-only observations", coverage.get("current_only_observations", 0)],
            ["Baseline-only observations", coverage.get("baseline_only_observations", 0)],
        ],
    )
    lines += ["", "## Skill: current vs pinned baseline (same weather)", ""]
    if overall:
        lines += markdown_table(
            ["Metric", "Current", "Baseline", "Current - Baseline", "Current - Market"],
            [
                [
                    "Brier",
                    fmt_num(overall.get("brier_current")),
                    fmt_num(overall.get("brier_baseline")),
                    _delta_label(overall.get("brier_delta_current_minus_baseline")),
                    _delta_label(overall.get("brier_delta_current_minus_market")),
                ],
                [
                    "Log loss",
                    fmt_num(overall.get("logloss_current")),
                    fmt_num(overall.get("logloss_baseline")),
                    _delta_label(overall.get("logloss_delta_current_minus_baseline")),
                    "-",
                ],
            ],
        )
        lines += [
            "",
            "Negative `Current - Baseline` = the current code is **better** than the "
            "pinned baseline on identical captured inputs (code-attributable gain). "
            "`Current - Market` is the live-forward-style skill shown for reference.",
        ]
    else:
        lines += ["_No shared frozen observations to score._"]

    by_regime = payload.get("by_regime") or {}
    if by_regime:
        lines += ["", "## By Regime (current - baseline Brier, weather constant)", ""]
        lines += markdown_table(
            ["Regime", "Shared Obs", "Current Brier", "Baseline Brier", "Delta"],
            [
                [
                    regime,
                    agg.get("shared_observations", 0),
                    fmt_num(agg.get("brier_current")),
                    fmt_num(agg.get("brier_baseline")),
                    _delta_label(agg.get("brier_delta_current_minus_baseline")),
                ]
                for regime, agg in by_regime.items()
            ],
        )

    by_market = payload.get("by_market") or {}
    if by_market:
        lines += ["", "## By Market (current - baseline Brier, weather constant)", ""]
        lines += markdown_table(
            ["Market", "Shared Obs", "Current Brier", "Baseline Brier", "Delta", "Current - Market"],
            [
                [
                    market,
                    agg.get("shared_observations", 0),
                    fmt_num(agg.get("brier_current")),
                    fmt_num(agg.get("brier_baseline")),
                    _delta_label(agg.get("brier_delta_current_minus_baseline")),
                    _delta_label(agg.get("brier_delta_current_minus_market")),
                ]
                for market, agg in by_market.items()
            ],
        )

    trend_rows = trend_rows if trend_rows is not None else load_trend()
    if trend_rows:
        lines += ["", "## Rolling Trend (one row per run-date)", ""]
        lines += markdown_table(
            ["Run Date", "Baseline", "Shared Obs", "Brier Cur-Base", "Brier Cur-Market"],
            [
                [
                    row.get("run_date"),
                    row.get("baseline_id"),
                    row.get("shared_observations", 0),
                    _delta_label(row.get("brier_delta_current_minus_baseline")),
                    _delta_label(row.get("brier_delta_current_minus_market")),
                ]
                for row in trend_rows
            ],
        )
        deltas = [
            row.get("brier_delta_current_minus_baseline")
            for row in trend_rows
            if row.get("brier_delta_current_minus_baseline") is not None
        ]
        if len(deltas) >= 2:
            improved = deltas[-1] < deltas[0]
            lines += [
                "",
                f"Since the first tracked run the current-vs-baseline Brier delta moved "
                f"{deltas[0]:+.4f} -> {deltas[-1]:+.4f} "
                f"({'improving' if improved else 'not improving'} on fixed weather).",
            ]
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pin = sub.add_parser("pin", help="Pin a durable baseline prediction export.")
    pin.add_argument("baseline_predictions", nargs="+")
    pin.add_argument("--baseline-id", required=True)
    pin.add_argument("--code-identity", default=None)
    pin.add_argument("--corpus-id", default=None)
    pin.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    pin.add_argument("--store-dir", default=str(DEFAULT_BASELINE_STORE))

    upd = sub.add_parser("update", help="Score current vs pinned baseline and append a trend row.")
    upd.add_argument("current_predictions", nargs="+")
    upd.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    upd.add_argument("--baseline-predictions", nargs="*", default=None,
                     help="Override the manifest's baseline export(s).")
    upd.add_argument("--code-identity", default=None)
    upd.add_argument("--current-variant-id", default=None,
                     help="When the current export has multiple variants, score only this one.")
    upd.add_argument("--baseline-variant-id", default=None,
                     help="When the baseline export has multiple variants, score only this one.")
    upd.add_argument("--trend-jsonl", default=str(DEFAULT_TREND_JSONL))
    upd.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    upd.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))

    rep = sub.add_parser("report", help="Re-render the report from the trend series.")
    rep.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    rep.add_argument("--trend-jsonl", default=str(DEFAULT_TREND_JSONL))
    rep.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "pin":
        manifest = pin_baseline(
            [Path(p) for p in args.baseline_predictions],
            baseline_id=args.baseline_id,
            code_identity=args.code_identity,
            corpus_id=args.corpus_id,
            manifest_path=args.manifest,
            store_dir=args.store_dir,
        )
        print(f"Pinned baseline '{manifest['baseline_id']}' -> {args.manifest}")
        return 0
    if args.command == "update":
        manifest = load_manifest(args.manifest) or {}
        baseline_paths = args.baseline_predictions or manifest.get("predictions_paths") or []
        if not baseline_paths:
            print("No baseline pinned; run `pin` first or pass --baseline-predictions.")
            return 2
        current_rows = read_prediction_rows(
            args.current_predictions,
            variant_id=args.current_variant_id,
        )
        baseline_rows = read_prediction_rows(
            baseline_paths,
            variant_id=args.baseline_variant_id,
        )
        payload = build_payload(
            current_rows,
            baseline_rows,
            manifest=manifest,
            code_identity=args.code_identity,
            current_paths=args.current_predictions,
            baseline_paths=baseline_paths,
        )
        rows = upsert_trend(trend_row(payload), args.trend_jsonl)
        write_json(args.json_out, payload)
        write_text_atomic(args.report_out, render_report(payload, rows))
        overall = payload.get("overall") or {}
        print(f"Frozen-baseline trend: status={payload['independent_baseline_status']} "
              f"shared={payload['coverage']['shared_observations']} "
              f"brier_cur-base={_delta_label(overall.get('brier_delta_current_minus_baseline'))}")
        print(f"JSON {args.json_out}; report {args.report_out}; trend {args.trend_jsonl}")
        return 0
    if args.command == "report":
        payload = json.loads(Path(args.json_out).read_text(encoding="utf-8")) if Path(args.json_out).exists() else {}
        write_text_atomic(
            args.report_out,
            render_report(payload, load_trend(args.trend_jsonl)),
        )
        print(f"Report written to {args.report_out}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
